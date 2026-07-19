"""Shared infrastructure for state-scanner collectors.

This module provides the `CollectorResult` dataclass, the `_run` subprocess
wrapper, and the module-level logger used by every collector in this package.

Invariants preserved from the pre-split scan.py:
- `CollectorResult.soft_error` appends `{error, detail}` dicts and logs a warning.
- `_run` never raises on non-zero rc; returns (rc, stdout, stderr).
- Timeouts coerce to rc=124 (matches GNU timeout convention).
- Missing commands coerce to rc=127.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("state-scanner.scan")

# ----- Forgejo hosts canonical resolver -------------------------------------
# Used by ALL forgejo-aware collectors (forgejo_config.py + issue_scan.py).
# See OpenSpec aria-forgejo-hosts-parameterization for design rationale.

ARIA_FORGEJO_HOSTS_ENV = "ARIA_FORGEJO_HOSTS"
_LEGACY_FORGEJO_FALLBACK: tuple[str, ...] = ("forgejo.10cg.pub",)


def _parse_env_forgejo_hosts() -> tuple[str, ...] | None:
    """Parse `ARIA_FORGEJO_HOSTS` env var (comma-separated host list).

    Returns None when env var is unset, empty, or all-whitespace — callers
    fall through to config / defaults. Duplicates preserved.
    """
    raw = os.environ.get(ARIA_FORGEJO_HOSTS_ENV, "")
    if not raw.strip():
        return None
    hosts = tuple(h.strip() for h in raw.split(",") if h.strip())
    return hosts or None


def _read_config_forgejo_hosts(project_root: Path) -> tuple[str, ...] | None:
    """Read `.aria/config.json` → `state_scanner.issue_scan.platform_hostnames.forgejo`.

    Fail-soft: missing file / parse error / key absent / non-list value → None.
    Empty list `[]` → None (fall through to defaults — explicit empty equals unset,
    avoids silently disabling all forgejo detection).
    """
    cfg_path = project_root / ".aria" / "config.json"
    if not cfg_path.is_file():
        return None
    try:
        with cfg_path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    hosts = (
        ((raw.get("state_scanner") or {}).get("issue_scan") or {})
        .get("platform_hostnames", {})
        .get("forgejo")
    )
    if not isinstance(hosts, list) or not hosts:
        return None
    cleaned = tuple(h for h in hosts if isinstance(h, str) and h.strip())
    return cleaned or None


def resolve_forgejo_hosts(project_root: Path) -> tuple[str, ...]:
    """Canonical 3-layer precedence resolver for Forgejo hostnames.

    Precedence (highest first):
      1. ARIA_FORGEJO_HOSTS env (comma-separated)
      2. .aria/config.json → state_scanner.issue_scan.platform_hostnames.forgejo
      3. Legacy fallback ("forgejo.10cg.pub",)

    Returns an immutable tuple; never empty (fallback guaranteed). Callers must
    treat the result as authoritative — do NOT re-implement precedence locally.
    """
    env_hosts = _parse_env_forgejo_hosts()
    if env_hosts:
        return env_hosts
    config_hosts = _read_config_forgejo_hosts(project_root)
    if config_hosts:
        return config_hosts
    return _LEGACY_FORGEJO_FALLBACK


# ----- handoff multibranch scan cap canonical resolver ----------------------
# Used by handoff_multibranch.py to bound how many remote branches are scanned.
# See OpenSpec state-scanner-output-cap-hardening (#71) for design rationale.
# Structure mirrors resolve_forgejo_hosts (env > config > default) but the value
# domain is `int` not `tuple[str, ...]`, so the layer parsers handle int-domain
# footguns explicitly (bad strings, bool-is-int, non-positive values).

ARIA_HANDOFF_MAX_BRANCHES_ENV = "ARIA_HANDOFF_MAX_BRANCHES"
_DEFAULT_MAX_BRANCHES: int = 20
# Recommended upper bound. Per OQ3 (owner 2026-06-03): warn-only + honor the
# user value — exceeding this logs a warning but the resolver still returns the
# user-set value (do NOT silently clamp / override user intent). The bound
# exists because each scanned branch costs up to 3 git subprocesses (5s timeout
# each), so very large values can make scan.py slow.
_MAX_BRANCHES_UPPER_BOUND: int = 500


def _parse_env_max_branches() -> int | None:
    """Parse `ARIA_HANDOFF_MAX_BRANCHES` env var (a single positive integer).

    Returns None (caller falls through to config / default) when the env var is
    unset, empty, all-whitespace, non-numeric, or ``<= 0``. Surrounding
    whitespace is tolerated. ``int(...)`` is guarded against ValueError/TypeError.
    """
    raw = os.environ.get(ARIA_HANDOFF_MAX_BRANCHES_ENV, "")
    if not raw.strip():
        return None
    try:
        val = int(raw.strip())
    except (ValueError, TypeError):
        return None
    if val <= 0:
        return None
    return val


def _read_config_max_branches(project_root: Path) -> int | None:
    """Read `.aria/config.json` → `state_scanner.handoff_multibranch.max_branches`.

    Fail-soft: missing file / parse error / key absent → None. Value must be a
    genuine ``int`` and ``> 0``; ``bool`` is explicitly rejected (``bool`` is an
    ``int`` subclass footgun — ``True`` would otherwise read as ``1``). Any other
    type (float, str, ...) → None → fall through to next layer.
    """
    cfg_path = project_root / ".aria" / "config.json"
    if not cfg_path.is_file():
        return None
    try:
        with cfg_path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    val = ((raw.get("state_scanner") or {}).get("handoff_multibranch") or {}).get(
        "max_branches"
    )
    if not isinstance(val, int) or isinstance(val, bool):
        return None
    if val <= 0:
        return None
    return val


def _honor_with_upper_bound_warning(val: int, source: str) -> int:
    """Return ``val`` unchanged; log a warning if it exceeds the recommended bound.

    Per OQ3 (owner decision 2026-06-03): warn-only — never clamp. The user value
    is authoritative; we only surface a performance advisory.
    """
    if val > _MAX_BRANCHES_UPPER_BOUND:
        log.warning(
            "handoff max_branches=%d (from %s) exceeds recommended upper bound "
            "(%d); honoring user value but scanning this many branches may be "
            "slow (each branch costs up to 3 git subprocesses).",
            val,
            source,
            _MAX_BRANCHES_UPPER_BOUND,
        )
    return val


def resolve_max_branches_scanned(project_root: Path) -> int:
    """Canonical 3-layer precedence resolver for the multibranch scan cap.

    Precedence (highest first):
      1. ARIA_HANDOFF_MAX_BRANCHES env (single positive int)
      2. .aria/config.json → state_scanner.handoff_multibranch.max_branches
      3. Default (20 — backward compatible with the pre-#71 hardcoded constant)

    Each layer independently falls through on absent/invalid/non-positive input
    (e.g. env="0" falls through to config, not straight to default). Values from
    env or config that exceed the recommended upper bound are honored (warn-only,
    per OQ3) — never clamped. Always returns a positive int.
    """
    env_val = _parse_env_max_branches()
    if env_val is not None:
        return _honor_with_upper_bound_warning(
            env_val, f"env {ARIA_HANDOFF_MAX_BRANCHES_ENV}"
        )
    config_val = _read_config_max_branches(project_root)
    if config_val is not None:
        return _honor_with_upper_bound_warning(
            config_val, "config state_scanner.handoff_multibranch.max_branches"
        )
    return _DEFAULT_MAX_BRANCHES


# ----- worktree scan cap canonical resolver ---------------------------------
# Used by handoff_worktrees.py to bound how many worktrees are scanned for
# cross-worktree handoff discovery. See OpenSpec cross-worktree-handoff-discovery
# (#139) for design rationale. Structure mirrors resolve_max_branches_scanned
# (env > config > default), but this is a PARALLEL resolver — NOT a reuse of the
# branch one, which hardwires ARIA_HANDOFF_MAX_BRANCHES / handoff_multibranch.
# max_branches / default 20 (all branch-specific). Local worktree counts are far
# smaller than remote branch counts, so the default is lower (8 vs 20).

ARIA_WORKTREE_MAX_SCANNED_ENV = "ARIA_WORKTREE_MAX_SCANNED"
_DEFAULT_MAX_WORKTREES: int = 8
# Recommended upper bound (warn-only per OQ3 mirror — honor user value, never
# clamp). Worktree enumeration is cheaper than branch scan (one git call total,
# plus one dir scan per worktree) so the bound is generous.
_MAX_WORKTREES_UPPER_BOUND: int = 64


def _parse_env_max_worktrees() -> int | None:
    """Parse `ARIA_WORKTREE_MAX_SCANNED` env var (a single positive integer).

    Returns None (caller falls through to config / default) when the env var is
    unset, empty, all-whitespace, non-numeric, or ``<= 0``. Surrounding
    whitespace is tolerated. ``int(...)`` is guarded against ValueError/TypeError.
    """
    raw = os.environ.get(ARIA_WORKTREE_MAX_SCANNED_ENV, "")
    if not raw.strip():
        return None
    try:
        val = int(raw.strip())
    except (ValueError, TypeError):
        return None
    if val <= 0:
        return None
    return val


def _read_config_max_worktrees(project_root: Path) -> int | None:
    """Read `.aria/config.json` → `state_scanner.worktree_scan.max_worktrees`.

    Fail-soft: missing file / parse error / key absent → None. Value must be a
    genuine ``int`` and ``> 0``; ``bool`` is explicitly rejected (``bool`` is an
    ``int`` subclass footgun — ``True`` would otherwise read as ``1``). Any other
    type (float, str, ...) → None → fall through to next layer.
    """
    cfg_path = project_root / ".aria" / "config.json"
    if not cfg_path.is_file():
        return None
    try:
        with cfg_path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    val = ((raw.get("state_scanner") or {}).get("worktree_scan") or {}).get(
        "max_worktrees"
    )
    if not isinstance(val, int) or isinstance(val, bool):
        return None
    if val <= 0:
        return None
    return val


def _honor_worktrees_upper_bound_warning(val: int, source: str) -> int:
    """Return ``val`` unchanged; log a warning if it exceeds the recommended bound.

    Warn-only — never clamp (mirrors the branch resolver's OQ3 decision). The
    user value is authoritative; we only surface a performance advisory.
    """
    if val > _MAX_WORKTREES_UPPER_BOUND:
        log.warning(
            "worktree max_worktrees=%d (from %s) exceeds recommended upper bound "
            "(%d); honoring user value but scanning this many worktrees may be slow.",
            val,
            source,
            _MAX_WORKTREES_UPPER_BOUND,
        )
    return val


def resolve_max_worktrees_scanned(project_root: Path) -> int:
    """Canonical 3-layer precedence resolver for the worktree scan cap.

    Precedence (highest first):
      1. ARIA_WORKTREE_MAX_SCANNED env (single positive int)
      2. .aria/config.json → state_scanner.worktree_scan.max_worktrees
      3. Default (8 — local worktree counts are small)

    Parallel to ``resolve_max_branches_scanned`` but with worktree-specific
    env/config keys and a lower default. Each layer independently falls through
    on absent/invalid/non-positive input. Values that exceed the recommended
    upper bound are honored (warn-only) — never clamped. Always returns a
    positive int.
    """
    env_val = _parse_env_max_worktrees()
    if env_val is not None:
        return _honor_worktrees_upper_bound_warning(
            env_val, f"env {ARIA_WORKTREE_MAX_SCANNED_ENV}"
        )
    config_val = _read_config_max_worktrees(project_root)
    if config_val is not None:
        return _honor_worktrees_upper_bound_warning(
            config_val, "config state_scanner.worktree_scan.max_worktrees"
        )
    return _DEFAULT_MAX_WORKTREES


@dataclass
class CollectorResult:
    data: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, str]] = field(default_factory=list)

    def soft_error(self, kind: str, detail: str) -> None:
        self.errors.append({"error": kind, "detail": detail})
        log.warning("collector soft error: %s — %s", kind, detail)


def _noninteractive_git_env(timeout: int) -> dict[str, str]:
    """Build `_run`'s child environment: LC_ALL=C (#143) + the task 3.4
    non-interactive contract. Split out as a named function so the contract is
    unit-testable without spawning a process (`test_common.py`).

    `ConnectTimeout` is derived from the caller's own `timeout` and capped at 10s.
    It must be STRICTLY smaller than the subprocess deadline (hence `timeout - 1`),
    otherwise the two expire together, TimeoutExpired wins the race, and ssh's own
    bounded failure — which carries a classifiable error instead of an opaque
    rc=124 — never gets to happen.

    ⚠️ Boundary (review M1): the inequality needs `timeout >= 2`, so the caller's
    timeout is floored at 2 for THIS derivation only. A 1s git timeout is already
    outside any regime where an ssh handshake completes; giving the ssh side one
    extra second changes nothing except restoring the ordering.
    Verified end-to-end against an unroutable host
    in `test_common.py`: with `min(timeout, 10)` that test returned rc=124 (hung to
    the deadline); with `timeout - 1` it returns ssh's own connect failure.
    """
    env = {**os.environ, "LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0"}
    if not env.get("GIT_SSH_COMMAND"):
        # Floor the caller timeout at 2 so the strict inequality below actually
        # holds: at timeout==1, `max(1, 0) == 1 == timeout` would reinstate the very
        # race this derivation exists to avoid (review M1).
        connect_timeout = max(1, min(max(int(timeout), 2) - 1, 10))
        env["GIT_SSH_COMMAND"] = (
            f"ssh -o BatchMode=yes -o ConnectTimeout={connect_timeout}"
        )
    return env


def _run(cmd: list[str], cwd: Path, timeout: int = 5) -> tuple[int, str, str]:
    """subprocess wrapper: returns (rc, stdout, stderr). Never raises on non-zero rc.

    **Contract guarantee**: stdout/stderr are ALWAYS strings (possibly empty),
    never None. Callers can safely call ``.splitlines()`` / ``.strip()`` /
    ``.startswith()`` without explicit None checks.

    Locale safety (#61 fix, 2026-05-20): explicit `encoding="utf-8"` +
    `errors="replace"` prevents crashes on Windows CJK locale where the default
    `text=True` would fall back to `locale.getpreferredencoding()` (e.g. GBK on
    Chinese Windows) and fail on UTF-8 git output (commit messages with CJK
    characters or emoji per aria-standards git-commit.md 双语规范). Matches the
    defensive pattern already used at openspec.py:38, readme.py:30, upm.py:335.

    Locale forcing (#143 fix, v1.46.1): `env={**os.environ, "LC_ALL": "C"}` forces
    git to emit ENGLISH diagnostics so collectors' English stderr-substring matching
    (coordination_fetch benign gate / _classify_error / multi_remote / issue_scan)
    is reliable on any host locale. Orthogonal to the #61 UTF-8 fix above: LC_ALL=C
    governs git's OWN diagnostic text; encoding="utf-8" governs byte→str decoding of
    passthrough (commit msgs / refs / paths — UTF-8 byte-identical under LC_ALL=C,
    verified via `git log --oneline` md5). LANG=C is redundant once LC_ALL=C is set
    (LC_ALL collapses all LC_*), so it is omitted.

    Non-interactive contract (task 3.4, main spec stale-refs-false-parity): git
    must NEVER be able to block on a prompt here. `timeout=` alone is not that
    guarantee — it is a *deadline*, so a credential prompt on a private HTTPS
    remote or an unknown-host-key prompt on SSH burns the FULL timeout on every
    affected leg, and F3′'s per-scan fetch budget then reports `not_attempted`
    for legs that never got a slot. Three orthogonal doors are closed:

    - `stdin=DEVNULL` — git's prompt reads hit EOF instead of waiting on a tty
      that, under scan.py, may not even be the operator's terminal.
    - `GIT_TERMINAL_PROMPT=0` — git's own switch for "fail instead of asking"
      (covers the HTTPS credential-helper path, which does not read stdin).
    - `GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=N"` — BatchMode
      kills passphrase/host-key prompts; ConnectTimeout bounds the TCP hang that
      BatchMode alone does not (a firewalled host stalls in connect(), long
      before ssh would have asked anything).

    ⚠️ `GIT_SSH_COMMAND` is set ONLY when the adopter has not set it. Clobbering a
    custom ssh wrapper (proxy jump, alternate identity, sshd on a nonstandard
    port) would break the fetch outright — a louder failure than the hang this
    guards. In that case the other two doors plus `timeout=` still apply, and the
    adopter's wrapper is the right place for their own BatchMode.

    Because prompts are structurally unreachable, the "auth failure prompts only
    once" requirement holds by construction: an auth failure returns a non-zero rc
    on the spot, gets a bounded label via `classify_git_error`, and is never
    re-asked — there is no interactive retry path to dedupe.

    Defensive None guard (#131 fix, 2026-05-28): ``(p.stdout or "")`` /
    ``(p.stderr or "")`` belt-and-suspenders for any future Python subprocess
    thread race that surfaces None outputs despite ``capture_output=True``.
    Forgejo Aria #131 reported AttributeError on ``out.splitlines()`` from a
    v1.20.0 install (before #61 fix landed the encoding parameter); v1.30.3
    documents and codifies the str-only return contract explicitly.
    """
    try:
        p = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",     # #61 fix: force UTF-8 (git output is UTF-8 by spec)
            errors="replace",     # #61 fix: never raise on partial/invalid bytes
            timeout=timeout,
            check=False,
            # #143 (locale hardening, v1.46.1): force C locale so git emits ENGLISH
            # diagnostics, making collectors' English stderr-substring matching
            # (coordination_fetch benign gate / _classify_error / multi_remote /
            # issue_scan) reliable on any host locale. Orthogonal to #61's UTF-8
            # decoding: LC_ALL governs git's OWN diagnostic text; encoding="utf-8"
            # governs byte→str decoding of passthrough (commit msgs / refs / paths,
            # which stay UTF-8 byte-identical under LC_ALL=C — verified). LANG=C is
            # redundant once LC_ALL=C is set (LC_ALL collapses all LC_*), so omitted.
            # task 3.4 (non-interactive contract): see docstring. stdin=DEVNULL is
            # NOT implied by capture_output — that governs stdout/stderr only, and
            # the child would otherwise inherit this process's stdin.
            stdin=subprocess.DEVNULL,
            env=_noninteractive_git_env(timeout),
        )
        # #131 fix: enforce str return contract — defensive against any future
        # subprocess thread race that surfaces None outputs despite capture_output.
        return p.returncode, (p.stdout or ""), (p.stderr or "")
    except subprocess.TimeoutExpired as e:
        return 124, "", f"timeout after {timeout}s: {e}"
    except FileNotFoundError as e:
        return 127, "", f"command not found: {e}"
    except UnicodeDecodeError as e:
        # #61 defensive: shouldn't fire with errors="replace" above, but
        # if the reader thread races and surfaces here, soften to a non-fatal
        # rc rather than letting it propagate to scan.py exit 30.
        return 125, "", f"decode error: {e}"


# ---------------------------------------------------------------------------
# Rule #7 typed error classification channel (stderr choke point)
# ---------------------------------------------------------------------------
# Spec B (state-scanner-snapshot-stderr-secret-leak, v5 option B): git command
# stderr can carry secrets (a failed `git fetch` echoes the remote URL, whose
# userinfo segment may hold an access token — Layer-2 aria-runner containers use
# exactly such HTTPS-with-embedded-token URLs). snapshot["errors"][].detail is read
# into the AI conversation, so raw stderr must NEVER reach it (Rule #7).
#
# The STRUCTURAL guarantee is narrow and precise: once a stderr string is passed to
# classify_git_error it CANNOT survive — _map_git_error_signal reads it only to pick a
# bounded label, then it is dropped, and the returned GitErrorClass has NO stderr field
# (TYPE-LEVEL incapable of carrying raw stderr). This also caps the secondary leak where
# _run's TimeoutExpired/FileNotFoundError branches put the argv (which for fetch includes
# the credential URL) into the returned stderr string: that string dies in
# classify_git_error; only the hardcoded `cmd` literal (e.g. "git log") and rc survive.
#
# What is NOT structurally forced: that every site ACTUALLY routes stderr through this
# channel. A future author could still write `soft_error(k, err.strip())` and bypass it.
# That routing invariant is enforced by best-effort means — the AC-2 lint
# (scripts/lint_stderr_typed_channel.py) plus the Task 3.1b code-review of the site list
# (Spec B v5 option B: AC-2 is explicitly best-effort, code-review is the authoritative
# completeness gate). So: "raw stderr cannot live inside a GitErrorClass" is structural;
# "every site uses a GitErrorClass" is lint + review, not structure.
#
# The git CLI-domain signal map lives here as the single SOT. issue_scan.py has its
# own independent CLI-domain _classify_error for forgejo/gh failures (OQ-B2:
# intentionally NOT merged — different failure domain, already returns enums, and
# issue_status.fetch_error is a published schema field). coordination_fetch's
# _classify_error DELEGATES to classify_git_error(...).label (keeping only its own
# "git fetch ..." wording layer) so the signal map is not duplicated.

_RC_COMMAND_NOT_FOUND = 127

# Network-level signals (DNS / TCP / TLS / timeout). v5 §3b expansion adds
# "unable to access" / "failed to connect" / "couldn't connect" / "tls".
_NETWORK_SIGNALS = (
    "could not resolve",
    "connection refused",
    "timed out",
    "ssl",
    "tls",
    "network",
    "unable to connect",
    "unable to access",
    "failed to connect",
    "couldn't connect",
    "fatal: repository",
)


@dataclass(frozen=True)
class GitErrorClass:
    """Typed, secret-free classification of a git command failure.

    Deliberately has NO stderr/detail field: once a raw stderr string is passed to
    classify_git_error it cannot survive into this object, so a GitErrorClass can be
    safely embedded in snapshot errors / detail strings (Rule #7).
    """

    label: str
    rc: int
    cmd: str


def _map_git_error_signal(rc: int, stderr: str) -> str:
    """(rc, stderr) → bounded label. The ONLY consumer of raw git stderr in the
    typed channel; the label set is closed to {git_missing, auth_403, non_ff,
    network, other}. This is a DETERMINISTIC TOTAL FUNCTION, not a mutually-exclusive
    partition: branches are evaluated in a FIXED first-match order (git_missing → auth
    → non_ff → network), so a stderr that happens to contain signals for two branches
    (e.g. a crafted "403 ... could not resolve") is resolved by that order (→ auth_403,
    R6-m4). The catch-all `other` covers the complement (fail-closed). Order is thus
    load-bearing on overlapping inputs and must not be reshuffled — locked by
    test_r6m4_auth_before_network_when_both (memory
    feedback_predicate_tiers_need_total_partition_proof)."""
    if rc == _RC_COMMAND_NOT_FOUND:
        return "git_missing"

    stderr_lower = stderr.lower()

    # Authentication failures (HTTP 401/403 or SSH publickey rejection). R6-m1
    # guard: match "permission denied (publickey)" ONLY, never bare "permission
    # denied" (a local FS permission error must not be mislabelled auth_403).
    if (
        "403" in stderr
        or "401" in stderr
        or "authentication failed" in stderr_lower
        or "permission denied (publickey)" in stderr_lower
    ):
        return "auth_403"

    # Non-fast-forward (force-push / orphan ref rewound)
    if "non-fast-forward" in stderr_lower or "rejected" in stderr_lower:
        return "non_ff"

    # Network-level failures
    if any(sig in stderr_lower for sig in _NETWORK_SIGNALS):
        return "network"

    # Fail-closed catch-all (covers the complement; consumers treat "other" as a
    # non-benign / unreachable-remote signal).
    return "other"


def classify_git_error(rc: int, stderr: str, cmd: str) -> GitErrorClass:
    """Consume (rc, stderr, cmd) → secret-free GitErrorClass. `stderr` is read only
    to derive the label and is NOT retained; `cmd` MUST be a hardcoded command-name
    literal (e.g. "git log"), never argv (which could carry a credential URL)."""
    return GitErrorClass(label=_map_git_error_signal(rc, stderr), rc=rc, cmd=cmd)


# ---------------------------------------------------------------------------
# F3′ (main spec stale-refs-false-parity, Phase 1) — deterministic test seams
# ---------------------------------------------------------------------------
# remote_refresh's concurrency / deadline / freshness logic needs deterministic
# injection points because under mock `_run` every fetch returns instantly, so
# the real wall-clock deadline and the real UTC clock cannot reproduce the states
# these fixtures must construct (a deadline-cut leg, a 14h-stale fetched_at, a
# sparse rotation rhythm). Three env seams (v9 8M-13) + one Rule #7 safe host
# resolver. These are READ-ONLY probes of os.environ — deliberately NOT part of
# the .aria/config.json layered resolvers above (they are test/CI seams, not user
# knobs, so they must not be silently settable via a committed config file).

ARIA_SCAN_NOW_ENV = "ARIA_SCAN_NOW"
ARIA_SCAN_OFFLINE_ENV = "ARIA_SCAN_OFFLINE"
ARIA_SCAN_FETCH_BUDGET_ENV = "ARIA_SCAN_FETCH_BUDGET"

_OFFLINE_TRUTHY = frozenset({"1", "true", "yes", "on"})


def scan_now() -> datetime:
    """Return 'now' as a tz-aware UTC datetime, honoring ``ARIA_SCAN_NOW``.

    Every freshness / generation-age / priority-ordering computation MUST read the
    current time through this single injection point (never a bare
    ``datetime.now()`` / ``time.time()``) so tests can pin a deterministic 'now'
    via ``ARIA_SCAN_NOW=<ISO 8601>``. Fail-soft: an unset, empty, or unparseable
    override falls back to the real UTC clock — a malformed override never crashes
    a scan. A naive (offset-less) override is interpreted as UTC.
    """
    raw = os.environ.get(ARIA_SCAN_NOW_ENV, "")
    if raw.strip():
        try:
            dt = datetime.fromisoformat(raw.strip())
        except (ValueError, TypeError):
            dt = None
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
    return datetime.now(timezone.utc)


def is_scan_offline() -> bool:
    """True when ``ARIA_SCAN_OFFLINE`` is set to a truthy value (1/true/yes/on).

    Offline mode short-circuits every network fetch (remote_refresh legs emit
    ``fetch_ok="not_attempted"`` without advancing ``fetched_at``; issue_scan
    forces its cache path) so two consecutive scans over a frozen environment
    produce byte-identical snapshots (9.7 stability freeze). Any other value
    (unset / 0 / false) → online. Case-insensitive, surrounding whitespace ignored.
    """
    return os.environ.get(ARIA_SCAN_OFFLINE_ENV, "").strip().lower() in _OFFLINE_TRUTHY


def fetch_budget_override() -> int | None:
    """Return the ``ARIA_SCAN_FETCH_BUDGET`` leg cap, or None when unset/invalid.

    Test seam ONLY (not a production knob). Under mock ``_run`` every leg returns
    instantly, so the production wall-clock deadline never fires and the
    "deadline cut some legs" state is unconstructable. This override caps how many
    legs the scheduler admits (stop-admitting after N dispatched) through the SAME
    stop → cancel → cache-writeback path the production deadline drives — never a
    parallel path (memory
    feedback_noop_in_test_env_hardening_needs_mechanism_assertion). Unset, empty,
    non-numeric, or ``<= 0`` → None (no override; the production deadline governs).
    ``bool`` is rejected (``True`` must not read as budget 1).
    """
    raw = os.environ.get(ARIA_SCAN_FETCH_BUDGET_ENV, "")
    if not raw.strip():
        return None
    try:
        val = int(raw.strip())
    except (ValueError, TypeError):
        return None
    return val if val > 0 else None


def resolve_remote_host(repo_dir: Path, remote: str, timeout: int = 5) -> str | None:
    """Resolve a remote's hostname via ``git remote get-url``. Rule #7 SAFE.

    Returns ONLY the bare hostname (e.g. ``"github.com"``), NEVER the full URL — an
    HTTPS remote URL can embed credentials (``https://user:TOKEN@host/...``; Layer-2
    aria-runner containers use exactly such URLs) and this function's output flows
    into snapshot fields, per-host concurrency bucketing, and logs. On any failure
    (rc != 0, empty output, unparseable URL) returns None; the raw URL — and thus any
    embedded credential — is never returned, logged, or surfaced.

    Handles three URL forms:
      - ``scheme://[user[:pw]@]host[:port]/path``  (https / ssh / git — urlsplit)
      - ``[user@]host:org/repo.git``               (scp-like, no scheme — regex)
    """
    rc, out, _ = _run(
        ["git", "remote", "get-url", remote], cwd=repo_dir, timeout=timeout
    )
    if rc != 0:
        return None
    first = out.strip().splitlines()[0].strip() if out.strip() else ""
    if not first:
        return None
    if "://" in first:
        try:
            host = urllib.parse.urlsplit(first).hostname
        except (ValueError, TypeError):
            return None
        return host or None
    # scp-like: [user@]host:path — host is between optional 'user@' and the ':'
    m = re.match(r"^(?:[^@/]+@)?([^:/]+):", first)
    if m:
        return m.group(1) or None
    return None

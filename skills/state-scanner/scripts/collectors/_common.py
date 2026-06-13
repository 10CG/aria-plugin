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
import subprocess
from dataclasses import dataclass, field
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
            env={**os.environ, "LC_ALL": "C"},
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

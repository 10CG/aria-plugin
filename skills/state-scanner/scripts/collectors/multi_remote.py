"""Phase 1.12 — Multi-remote parity collector (v1.15.0+).

Produces the `multi_remote` block documented in `state-scanner/SKILL.md` §1.12
"多远程 Parity". Canonical schema source-of-truth is `git-remote-helper` SKILL.md;
this collector is the fallback in-process implementation invoked when the helper
is not available (or unconditionally, since the current in-tree topology ships
the collector as the primary integration point).

Design invariants (do not break without a snapshot_schema_version bump):
- stdlib-only (subprocess, json, os, pathlib, re).
- fail-soft: every git call is wrapped; a single failure yields `parity: unknown`
  with `reason` populated, never propagates as an exception.
- All git invocations carry a 5s default timeout (configurable via
  `state_scanner.multi_remote.timeout_seconds`).
- Disabled mode (`state_scanner.multi_remote.enabled: false`) emits
  `{"enabled": false}` and nothing else.
- `overall_parity` semantics (F4′, main spec stale-refs-false-parity, Phase 1 —
  SUPERSEDES the pre-Phase-1 QA-C1 + BA-R1-C1 wording; see `_overall_parity`
  docstring for the authoritative 4-clause decision table):
    * true  = enforced_set ≠ ∅ AND at least one remote has `parity == equal`
              AND `evidence_grade == "fresh"` for that same remote (⚠️ BOTH —
              a stale_unverified `equal` is NOT positive evidence, see D20) AND
              no remote has `parity ∈ {behind, diverged}` AND no remote is
              `blocking_unknown` AND no gitlink is `gitlink_blocking`
              (Phase 1: `gitlink_integrity` is always `[]`, vacuously satisfied).
    * false = zero fresh-`equal` evidence OR any blocker above.
    * `parity: ahead`   does NOT count (→ `has_pending_push`)
    * `parity: unknown` does NOT contribute evidence (→ `has_unreachable_remote`
                         is now driven ONLY by `fetch_ok=="false"`, see
                         `_has_unreachable_remote` — no longer by `reason`
                         enumeration or the `reachable` field)
    SKILL.md §1.12 spec text is kept in sync with this definition.
  `_aggregate_flags` (below) is the PRE-Phase-1 pure helper — retained verbatim
  (and still directly unit-tested) for `has_pending_push`'s historical
  computation, but `collect_multi_remote` no longer sources
  `overall_parity`/`has_unreachable_remote` from it; those two flags now flow
  through `_overall_parity`/`_has_unreachable_remote` after the F1′/F4′
  freshness join (see `collect_multi_remote`).

Output shape (conformant to SKILL.md §1.12 schema; F2′ retired
`local_refs_stale` — FETCH_HEAD-mtime is a repo-global single value that any
remote's fetch resets, structurally unusable as a per-remote freshness signal;
replaced by the per-remote `evidence_grade` field below, joined from the F3′
`remote_refresh` collector's per-leg `fetched_at`/`fetch_ok` map):

    multi_remote:
      enabled: bool
      main_repo: RepoParity           # when enabled=true
      submodules: [RepoParity, ...]   # same shape, path-keyed
      overall_parity: bool
      has_unreachable_remote: bool
      has_pending_push: bool

    RepoParity:
      path: str                       # "." for main_repo, relative path for submodules
      local_head: str | null
      branch: str | null
      remotes:
        - name: str
          remote_head: str | null
          parity: equal|ahead|behind|diverged|unknown
          behind_count: int | null
          ahead_count: int | null
          reachable: bool             # false only when verify_mode=ls_remote and call fails
          reason: null | no_local_tracking_ref | shallow_clone | detached_head
                  | auth_failed | not_found | network_timeout | not_refreshed
                  | rev_list_failed | rev_list_parse_failed | parse_error
                  | remote_branch_missing
          method: local_refs | ls_remote
          evidence_grade: fresh | stale_unverified | expired   # D20, F1′/F4′ join
          fetch_ok: "true" | "false" | "not_attempted"          # F3′ leg join
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ._common import CollectorResult, _run, scan_now
from .git import _current_branch, _enumerate_submodule_paths, _is_shallow

_DEFAULT_TIMEOUT = 5

# F1′/F4′ freshness join defaults (main spec stale-refs-false-parity, Phase 1) —
# mirror `state_scanner.sync_freshness.*` in config-loader/DEFAULTS.json +
# .aria/config.template.json (Phase 0 landed). Hardcoded here per this
# collector-package's existing pattern (`_load_config` never reads
# DEFAULTS.json at runtime; DEFAULTS.json is adopter-facing documentation, the
# Python constant is the runtime default — same split as
# `_DEFAULT_REFRESH_DEADLINE_SECONDS` et al. in remote_refresh.py).
_DEFAULT_EVIDENCE_WINDOW_SECONDS = 3600
_DEFAULT_HARD_CAP_DAYS = 7
_DEFAULT_K_MIN = 3

# F3′ remote_refresh (Phase 0.5) cache — same relative path as
# `remote_refresh._CACHE_RELATIVE`. Duplicated (not imported): remote_refresh.py
# imports FROM this module (`_list_remotes` / `_load_config` /
# `resolve_enforced_remotes`), so importing back would be circular. Any change
# to the cache path/key format must be mirrored in both modules.
_REMOTE_REFRESH_CACHE_RELATIVE = ".aria/cache/remote-refresh.json"


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------
def _load_config(project_root: Path) -> dict[str, Any]:
    """Read `.aria/config.json` → `state_scanner.multi_remote` block.

    Missing file / missing block → defaults (enabled=true, verify_mode=local_refs).
    Malformed JSON → defaults + soft error logged by caller if it cares.

    F2′ retirement note (main spec stale-refs-false-parity, Phase 1): this used
    to inherit `warn_after_hours` from the sibling `sync_check` block when
    `multi_remote` omitted it. That inheritance is REMOVED — `warn_after_hours` /
    FETCH_HEAD-mtime staleness is retired wholesale (see module docstring);
    `sync_check.warn_after_hours` remains in the config schema for `sync.py`'s
    own (unrelated, F9′/Phase-2) consumption only, never read here.
    """
    cfg_path = project_root / ".aria" / "config.json"
    if not cfg_path.exists():
        return {}
    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    ss = raw.get("state_scanner") or {}
    return ss.get("multi_remote") or {}


def _load_sync_freshness_config(project_root: Path) -> dict[str, Any]:
    """Read `.aria/config.json` → `state_scanner.sync_freshness` block (Phase 0
    landed keys: `evidence_window_seconds` / `hard_cap_days` / `k_min` — D15′/D18
    thresholds for the F1′ dual-role predicates). Deliberately a SEPARATE read
    from `_load_config`: `sync_freshness` is a sibling block, unrelated to
    `multi_remote`'s own enabled/verify_mode/timeout_seconds keys. Same
    fail-soft contract: missing file/block or malformed JSON → `{}` (callers
    apply hardcoded defaults)."""
    cfg_path = project_root / ".aria" / "config.json"
    if not cfg_path.exists():
        return {}
    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    ss = raw.get("state_scanner") or {}
    return ss.get("sync_freshness") or {}


def resolve_enforced_remotes(
    configured: "list[str] | None",
    actual_remotes: list[str],
    read_only: tuple[str, ...] = (),
) -> tuple[list[str], list[str]]:
    """F5′ (main spec stale-refs-false-parity, Phase 0) — resolve which remotes to
    enforce parity on. Pure function; INERT until F4′ (Phase 1) wires it into
    overall_parity.

    Returns ``(enforced, no_matching)``:
    - ``enforced``: remotes to actually check, in ``actual_remotes`` order, minus
      ``read_only``.
    - ``no_matching``: configured names absent from ``actual_remotes`` — recorded as
      ``no_matching_remote`` observability, NEVER fetched as ghost fail legs.

    🔴 **The F5′ trap** (published cross-skill contract, phase-c-integrator/SKILL.md +
    config-loader DEFAULTS): a NON-EMPTY ``configured`` list is an explicit allowlist →
    intersect with ``actual``. An EMPTY list ``[]`` OR ``None`` means **AUTO-DISCOVER
    all remotes**, NOT the empty set. Coding ``[]`` as "check nothing" makes every
    default adopter's ``overall_parity`` go false — a louder regression than the bug
    this spec fixes. `if configured:` is falsy for both `[]` and `None`, so both route
    to auto-discover; only a truthy (non-empty) list is treated as an allowlist.
    """
    actual = list(actual_remotes)
    ro = set(read_only)
    if configured:  # truthy = non-empty explicit allowlist
        want = set(configured)
        enforced = [r for r in actual if r in want and r not in ro]
        no_matching = [r for r in configured if r not in actual]
        return enforced, no_matching
    # [] or None → auto-discover all remotes (the trap: NOT an empty set)
    return [r for r in actual if r not in ro], []


# ---------------------------------------------------------------------------
# Git helpers (repo-local only — shared helpers live in .git)
# ---------------------------------------------------------------------------
# T3.6 consolidation: `_current_branch` / `_is_shallow` / `_enumerate_submodule_paths`
# are imported from .git with timeout support added in T3.6. Local helpers below
# are specific to multi_remote (need short-sha output, per-repo-dir context).


def _head_commit(repo_dir: Path, timeout: int) -> str | None:
    rc, out, _ = _run(["git", "rev-parse", "--short=7", "HEAD"], repo_dir, timeout=timeout)
    if rc != 0:
        return None
    v = out.strip()
    return v or None


def _list_remotes(repo_dir: Path, timeout: int) -> list[str]:
    rc, out, _ = _run(["git", "remote"], repo_dir, timeout=timeout)
    if rc != 0:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def _gitdir_for(repo_dir: Path, timeout: int) -> Path | None:
    """Resolve the actual .git directory (handles submodule `.git` file indirection)."""
    rc, out, _ = _run(
        ["git", "rev-parse", "--git-dir"], repo_dir, timeout=timeout
    )
    if rc != 0:
        return None
    p = Path(out.strip())
    if not p.is_absolute():
        p = (repo_dir / p).resolve()
    return p


# F2′ retirement note: `_fetch_head_age_hours` (repo-global FETCH_HEAD mtime)
# used to live here. Removed wholesale (main spec stale-refs-false-parity,
# Phase 1) — any remote's fetch resets the single FETCH_HEAD file, so it could
# never distinguish "this remote was just refreshed" from "a sibling remote
# was refreshed 3 days ago"; see module docstring + proposal §现状 item 4/6.
# `_gitdir_for` (above) is retained — it is a generic git-dir resolver with its
# own direct test coverage, independent of the retired staleness computation.


# ---------------------------------------------------------------------------
# Parity computation
# ---------------------------------------------------------------------------
def _remote_parity_local_refs(
    repo_dir: Path,
    remote: str,
    branch: str | None,
    local_head: str | None,
    shallow: bool,
    timeout: int,
) -> dict[str, Any]:
    """Compute parity via local tracking ref (no network). Default path."""
    base: dict[str, Any] = {
        "name": remote,
        "remote_head": None,
        "parity": "unknown",
        "behind_count": None,
        "ahead_count": None,
        "reachable": True,
        "reason": None,
        "method": "local_refs",
    }

    if branch is None:
        base["reason"] = "detached_head"
        return base

    if shallow:
        base["reason"] = "shallow_clone"
        return base

    ref = f"refs/remotes/{remote}/{branch}"
    rc, out, _ = _run(
        ["git", "rev-parse", "--short=7", ref], repo_dir, timeout=timeout
    )
    if rc != 0:
        base["reason"] = "no_local_tracking_ref"
        base["reachable"] = True  # local op succeeded-to-run; we just lack the ref
        return base
    base["remote_head"] = out.strip() or None

    if local_head is None:
        # Cannot compute counts without a local HEAD
        base["reason"] = "detached_head"
        return base

    # Compute ahead/behind using full-length refs to avoid ambiguous short-sha matches.
    rc, out, _ = _run(
        ["git", "rev-list", "--left-right", "--count", f"HEAD...{ref}"],
        repo_dir,
        timeout=timeout,
    )
    if rc != 0:
        base["reason"] = "rev_list_failed"
        return base
    parts = out.strip().split()
    if len(parts) != 2:
        base["reason"] = "rev_list_parse_failed"
        return base
    try:
        ahead, behind = int(parts[0]), int(parts[1])
    except ValueError:
        base["reason"] = "rev_list_parse_failed"
        return base

    base["ahead_count"] = ahead
    base["behind_count"] = behind
    if ahead > 0 and behind > 0:
        base["parity"] = "diverged"
    elif ahead > 0:
        base["parity"] = "ahead"
    elif behind > 0:
        base["parity"] = "behind"
    else:
        base["parity"] = "equal"
    return base


def _remote_parity_ls_remote(
    repo_dir: Path,
    remote: str,
    branch: str | None,
    local_head: str | None,
    shallow: bool,
    timeout: int,
) -> dict[str, Any]:
    """Verify parity by calling `git ls-remote <remote> <branch>` (network I/O).

    This resolves remote_head directly from the server. Ahead/behind counts still
    require a local rev-list, so if the fetched sha is unreachable from HEAD we
    degrade gracefully to just reporting remote_head + reachable=true with a
    best-effort equal/behind classification.
    """
    base: dict[str, Any] = {
        "name": remote,
        "remote_head": None,
        "parity": "unknown",
        "behind_count": None,
        "ahead_count": None,
        "reachable": True,
        "reason": None,
        "method": "ls_remote",
    }

    if branch is None:
        base["reason"] = "detached_head"
        return base

    rc, out, err = _run(
        ["git", "ls-remote", "--heads", remote, branch], repo_dir, timeout=timeout
    )
    if rc != 0:
        base["reachable"] = False
        low = (err or "").lower()
        if "could not resolve host" in low or "timed out" in low or "timeout" in low:
            base["reason"] = "network_timeout"
        elif "authentication failed" in low or "permission denied" in low:
            base["reason"] = "auth_failed"
        elif "not found" in low or "does not exist" in low:
            base["reason"] = "not_found"
        else:
            base["reason"] = "network_timeout"
        return base

    # Output is "<sha>\t<ref>"; first line only (single branch).
    first = out.strip().split("\n", 1)[0] if out.strip() else ""
    if not first:
        # QA-I1 fix (post_implementation audit R1): empty stdout with rc=0 means
        # the remote responded but this branch does not exist on it — a new
        # feature branch that has never been pushed, not an unreachable remote.
        # Marking reachable=False would suppress push reminders incorrectly.
        base["reason"] = "remote_branch_missing"
        base["reachable"] = True
        return base
    if "\t" not in first:
        # Malformed output — remote reachable but response unparseable.
        base["reason"] = "parse_error"
        base["reachable"] = True
        return base
    sha = first.split("\t", 1)[0].strip()
    base["remote_head"] = sha[:7] if len(sha) >= 7 else sha or None

    if shallow:
        # Can't compute counts in shallow clones.
        base["reason"] = "shallow_clone"
        return base

    if local_head is None:
        base["reason"] = "detached_head"
        return base

    # Try rev-list HEAD...<sha>; if <sha> not in local object db, degrade.
    rc, out, _ = _run(
        ["git", "rev-list", "--left-right", "--count", f"HEAD...{sha}"],
        repo_dir,
        timeout=timeout,
    )
    if rc != 0:
        # Unknown sha locally → we know remote_head but not counts; flag equal iff heads match.
        if local_head and sha.startswith(local_head):
            base["parity"] = "equal"
            base["ahead_count"] = 0
            base["behind_count"] = 0
        # else leave parity=unknown with reason None (best-effort)
        return base
    parts = out.strip().split()
    if len(parts) != 2:
        return base
    try:
        ahead, behind = int(parts[0]), int(parts[1])
    except ValueError:
        return base
    base["ahead_count"] = ahead
    base["behind_count"] = behind
    if ahead > 0 and behind > 0:
        base["parity"] = "diverged"
    elif ahead > 0:
        base["parity"] = "ahead"
    elif behind > 0:
        base["parity"] = "behind"
    else:
        base["parity"] = "equal"
    return base


# ---------------------------------------------------------------------------
# Per-repo scan
# ---------------------------------------------------------------------------
def _scan_repo(
    repo_dir: Path,
    path_label: str,
    verify_mode: str,
    timeout: int,
) -> dict[str, Any]:
    """Scan one repo (main or submodule). Returns repo_block.

    F2′ retirement note: this used to return `(repo_block, stale_flag)` — the
    second element was a dead `False` constant (`_scan_repo` never actually
    computed per-repo staleness; the real, always-broken staleness path lived
    in `collect_multi_remote` via `_fetch_head_age_hours`, also retired). Now
    returns the block alone; per-remote freshness (`evidence_grade`) is
    computed by `collect_multi_remote` AFTER this function returns, via the
    F1′/F4′ join against the F3′ `remote_refresh` cache.
    """
    shallow = _is_shallow(repo_dir, timeout)
    branch = _current_branch(repo_dir, timeout)
    local_head = _head_commit(repo_dir, timeout)
    remotes = _list_remotes(repo_dir, timeout)

    remote_results: list[dict[str, Any]] = []
    for rname in remotes:
        if verify_mode == "ls_remote":
            r = _remote_parity_ls_remote(
                repo_dir, rname, branch, local_head, shallow, timeout
            )
        else:
            r = _remote_parity_local_refs(
                repo_dir, rname, branch, local_head, shallow, timeout
            )
        remote_results.append(r)

    return {
        "path": path_label,
        "local_head": local_head,
        "branch": branch,
        "remotes": remote_results,
    }


# ---------------------------------------------------------------------------
# F1′/F4′ predicates (main spec stale-refs-false-parity, Phase 1)
# ---------------------------------------------------------------------------
# SOT = proposal F4′ v8 formula block (D15′ dual-role predicates + D20 evidence_grade
# full partition). These are PURE functions consuming the per-leg fetch signals that
# remote_refresh (F3′, Phase 0.5) produces (fetched_at / fetch_ok / generation /
# consecutive_unverified). `collect_multi_remote` wires them to real remote_refresh
# data (the join helpers further below: `_remote_refresh_leg_key` /
# `_read_remote_refresh_cache` / `_leg_evidence_grade`). Registered in the D16
# predicate-domain table (references/predicate-domain-table.md). Retired
# single-role predicate 可信(r) is forbidden (its single-role conflation was the
# R7 three-Critical root).


def _evidence_eligible(
    fetched_at: datetime | None, now: datetime, window_seconds: int
) -> bool:
    """证据资格(r) — D15′ ∃ side: world-time fresh positive evidence.

    fetched_at is None ⇒ False. A negative wall-clock age (fetched_at in the future
    — clock rollback / NTP jump, R9-M3) is treated as null ⇒ False (fail-CLOSED): a
    rollback could otherwise make a 14h-stale fetch present a false-fresh age.
    """
    if fetched_at is None:
        return False
    age = (now - fetched_at).total_seconds()
    if age < 0:
        return False
    return age <= window_seconds


def _exemption_eligible(
    fetched_at: datetime | None,
    now: datetime,
    generation_fetched: int | None,
    scan_generation: int,
    k_eff: int,
    hard_cap_seconds: int,
    consecutive_unverified: int,
) -> bool:
    """豁免资格(r) — D15′+D18 downgrade side: attention-rhythm fresh.

    Any missing / out-of-range input ⇒ False (fail-CLOSED). Guards: fetched_at
    present ∧ 0 ≤ wall-age ≤ hard_cap ∧ generation present ∧ 0 ≤ generation_age ≤
    k_eff ∧ consecutive_unverified < k_eff (D18). Negative generation_age (lost-update
    rollback, RM-6b) is clamped to null.
    """
    if fetched_at is None:
        return False
    age = (now - fetched_at).total_seconds()
    if age < 0 or age > hard_cap_seconds:
        return False
    if generation_fetched is None:
        return False
    generation_age = scan_generation - generation_fetched
    if generation_age < 0:
        return False
    if generation_age > k_eff:
        return False
    if consecutive_unverified >= k_eff:
        return False
    return True


def _evidence_grade(evidence_eligible: bool, exemption_eligible: bool) -> str:
    """D20 three-tier FULL PARTITION — the single definition point (D16 lock rule #2).

    E-first (owner R9-m1). The if/elif/else structure IS the mutual-exclusion +
    exhaustiveness proof: exactly one branch executes per call, so the E∧¬X cell
    (True, False) lands unambiguously in ``fresh`` and can never be simultaneously
    claimed by the stale_unverified branch — this is the structural cure for the R8
    11th-recurrence overlap cell (two agents independently wrote three
    independently-evaluated flags that could both fire on E∧¬X).
    """
    if evidence_eligible:
        return "fresh"
    if exemption_eligible:
        return "stale_unverified"
    return "expired"


def _apply_freshness_downgrade(remote_entry: dict[str, Any], evidence_grade: str) -> None:
    """Writes the per-remote `evidence_grade` field onto `remote_entry` IN PLACE
    (independent field, never folded into `reason` — `reason` stays a
    fetch-mechanism enum, `evidence_grade` is the orthogonal freshness-of-that-
    answer axis; folding them was the R7-flagged trap).

    Downgrade only applies to `parity == "equal"` entries: `"expired"` (¬E∧¬X)
    rewrites `parity` → `"unknown"` + `reason` → `"not_refreshed"` — never let a
    doubly-stale `equal` masquerade as positive evidence (the founding 14h-stale
    accident this Spec exists to kill). `"fresh"` / `"stale_unverified"` leave
    `parity` untouched: `stale_unverified` is F1′'s designed diagnostic middle
    tier — still literally `"equal"`, but `_overall_parity`'s ∃-clause gates on
    `evidence_grade == "fresh"`, NOT on `parity == "equal"` alone, so it does not
    resurrect the accident (see `_overall_parity` docstring clause 2).
    """
    remote_entry["evidence_grade"] = evidence_grade
    if remote_entry.get("parity") != "equal":
        return
    if evidence_grade == "expired":
        remote_entry["parity"] = "unknown"
        remote_entry["reason"] = "not_refreshed"


# ---------------------------------------------------------------------------
# F3′↔F1′ join (Phase 1, increment 4b) — reads the remote_refresh cache and
# turns each remote entry's raw fetch signals into an evidence_grade.
# ---------------------------------------------------------------------------
def _remote_refresh_leg_key(repo: str, remote: str) -> str:
    """Cache-key format for a (repo, remote) leg — MUST byte-for-byte match
    `remote_refresh._leg_key` (duplicated here, not imported, to avoid a
    circular import: remote_refresh.py imports FROM this module). Main repo
    `repo == "."` — the SAME label `_scan_repo` already stamps onto
    `repo_block["path"]`, so a submodule's `origin` can never alias the main
    repo's `origin` cache entry (top_risks: keying by remote-name alone would
    let a never-fetched submodule leg borrow the main repo's `fetched_at`)."""
    return f"{repo}::{remote}"


def _read_remote_refresh_cache(project_root: Path) -> dict[str, Any]:
    """Read the F3′ `remote_refresh` (Phase 0.5) cache
    (`.aria/cache/remote-refresh.json`). Fail-soft: missing file / malformed
    JSON / non-dict payload → `{}` — every leg then joins as `leg=None` below,
    which `_leg_evidence_grade` treats identically to `fetched_at=null`
    (evidence_grade="expired", the fail-CLOSED default). "We have no cache" and
    "we have a cache saying this leg was never fetched" must produce the SAME
    verdict — never a friendlier one for the missing-cache case."""
    cache_file = project_root / _REMOTE_REFRESH_CACHE_RELATIVE
    if not cache_file.is_file():
        return {}
    try:
        raw = cache_file.read_text(encoding="utf-8", errors="replace")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _parse_leg_fetched_at(raw: Any) -> datetime | None:
    """Parse a cached leg's `fetched_at` ISO string (mirrors
    `remote_refresh._parse_iso`, duplicated for the same circular-import
    reason as `_remote_refresh_leg_key`). Non-string / empty / unparseable →
    None. A naive (offset-less) timestamp is treated as UTC."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        dt = datetime.fromisoformat(raw.strip())
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _leg_evidence_grade(
    leg: dict[str, Any] | None,
    now: datetime,
    scan_generation: int,
    evidence_window_seconds: int,
    hard_cap_seconds: int,
    k_eff: int,
) -> str:
    """Join one remote_refresh (F3′) leg record into a D20 `evidence_grade`.
    `leg` is None when this remote has no matching cache entry — never fetched
    by remote_refresh (e.g. outside `enforced_remotes`, or the cache/scan
    hasn't run yet) — and is treated identically to `fetched_at=null`
    (fail-CLOSED ⇒ eventually "expired", never silently "fresh"). Malformed
    cache field types (non-int generation/consecutive counters) fail-soft to
    the same values `_exemption_eligible` already treats as absent."""
    fetched_at = _parse_leg_fetched_at(leg.get("fetched_at")) if leg else None
    generation_fetched = leg.get("generation_fetched") if leg else None
    if not isinstance(generation_fetched, int) or isinstance(generation_fetched, bool):
        generation_fetched = None
    consecutive_unverified = leg.get("consecutive_unverified", 0) if leg else 0
    if not isinstance(consecutive_unverified, int) or isinstance(consecutive_unverified, bool):
        consecutive_unverified = 0
    e = _evidence_eligible(fetched_at, now, evidence_window_seconds)
    x = _exemption_eligible(
        fetched_at,
        now,
        generation_fetched,
        scan_generation,
        k_eff,
        hard_cap_seconds,
        consecutive_unverified,
    )
    return _evidence_grade(e, x)


_BENIGN_UNCONDITIONAL_REASONS = frozenset(
    {"detached_head", "shallow_clone", "remote_branch_missing"}
)


def _benign_unknown(parity: str | None, reason: str | None, evidence_eligible: bool) -> bool:
    """parity==unknown that is benign (does NOT block overall_parity).

    ① fetch-independent reasons (detached_head / shallow_clone / remote_branch_missing
    — ls-remote answers authoritatively) are unconditionally benign. ② the
    no_local_tracking_ref assertion ("really never published") is benign ONLY when the
    evidence is world-time fresh. Everything else (incl. None / parse_error / Spec B
    catch-all values) is NOT benign.
    """
    if parity != "unknown":
        return False
    if reason in _BENIGN_UNCONDITIONAL_REASONS:
        return True
    if reason == "no_local_tracking_ref":
        return evidence_eligible
    return False


def _blocking_unknown(parity: str | None, reason: str | None, evidence_eligible: bool) -> bool:
    """fail-CLOSED: any unknown parity that is NOT benign blocks. Defined as the strict
    complement of _benign_unknown — NEVER a positive enumeration of blocking reasons
    (a positive enum fails OPEN on any unlisted / future / classifier catch-all value:
    the invariant's 5th recurrence). Do not rewrite as ``reason in {...}``."""
    return parity == "unknown" and not _benign_unknown(parity, reason, evidence_eligible)


def _has_unreachable_remote(fetch_ok: str) -> bool:
    """Reads the fetch_ok three-state ONLY (zero reason-enumeration). ``not_attempted``
    (deadline-cut / backoff — "we didn't ask") is NOT unreachable ("we can't reach");
    only an actual failed fetch (``"false"``) is. The 6th recurrence was a positive
    reason-enumeration here that missed Spec B classifier catch-all values."""
    return fetch_ok == "false"


def _gitlink_blocking(g: dict[str, Any]) -> bool:
    """F10″ gitlink-layer blocking predicate (interface for Phase 2A). In Phase 1
    gitlink_integrity is always [] so this is never invoked with data; the
    orphan_unverified + consecutive≥k_eff (D18) branch lands in Phase 2A (tasks 13.4)."""
    return g.get("status") == "orphaned"


def _overall_parity(
    enforced_entries: list[dict[str, Any]], gitlink_integrity: list[dict[str, Any]]
) -> bool:
    """F4′ v8 decision table (SOT = proposal L459-506). Four clauses:

      1. enforced_set ≠ ∅            (guard the ``all([])`` vacuous-true)
      2. ∃ r: parity==equal ∧ evidence_grade=="fresh"   (⚠️ BOTH — a stale_unverified
         equal keeps parity==equal so a parity-only ∃ check resurrects the 14h accident)
      3. ∀ R: ¬gitlink_blocking(R)   (Phase 1 placeholder — gitlink_integrity=[] ⇒
         vacuously true; a UNIVERSAL-NEGATION clause, so empty input is safe, unlike
         clause 1's positive-evidence empty set)
      4. ∀ r: parity ∉ {behind, diverged} ∧ ¬blocking_unknown(r)
    """
    if not enforced_entries:
        return False
    has_fresh_equal = any(
        e.get("parity") == "equal" and e.get("evidence_grade") == "fresh"
        for e in enforced_entries
    )
    if not has_fresh_equal:
        return False
    if any(_gitlink_blocking(g) for g in gitlink_integrity):
        return False
    for e in enforced_entries:
        if e.get("parity") in ("behind", "diverged"):
            return False
        # evidence_grade=="fresh" ⟺ 证据资格(r) (E) by _evidence_grade's definition,
        # so it is the correct gate for _benign_unknown's ② no_local_tracking_ref branch.
        if _blocking_unknown(
            e.get("parity"), e.get("reason"), e.get("evidence_grade") == "fresh"
        ):
            return False
    return True


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------
def _aggregate_flags(all_remote_entries: list[dict[str, Any]]) -> dict[str, bool]:
    """Compute overall_parity / has_unreachable_remote / has_pending_push.

    Phase 1 (F1′/F4′) note: `collect_multi_remote` no longer sources its
    `overall_parity`/`has_unreachable_remote` output from this function — those
    now flow through `_overall_parity`/`_has_unreachable_remote` after the
    freshness join (see module docstring "Design invariants"). This function is
    RETAINED VERBATIM (pre-Phase-1 pure logic, still directly unit-tested in
    `test_multi_remote.py`) as a legacy reference implementation; it is dead
    code from `collect_multi_remote`'s perspective, not deleted because its own
    tests still exercise its documented QA-C1 behavior directly.

    QA-C1 fix (post_implementation audit R1): `overall_parity=True` requires at
    LEAST ONE remote with confirmed `parity=equal`. When every remote returns
    `unknown` (no_local_tracking_ref / shallow_clone / detached_head / network
    failure), we have zero positive evidence of parity and must return False —
    otherwise downstream recommenders silently suppress push reminders on
    unpushed feature branches. The prior implementation initialized
    `overall_parity=True` and only flipped on behind/diverged, which meant
    all-unknown inputs short-circuited to True with no data.
    """
    if not all_remote_entries:
        return {
            "overall_parity": False,  # QA-C1: no remotes = no evidence = not confirmed
            "has_unreachable_remote": False,
            "has_pending_push": False,
        }
    has_equal_evidence = False
    blocks_parity = False
    has_unreachable = False
    has_pending_push = False
    for r in all_remote_entries:
        p = r.get("parity")
        if not r.get("reachable", True):
            has_unreachable = True
        if p == "equal":
            has_equal_evidence = True
            continue
        if p == "ahead":
            has_pending_push = True
            # ahead does NOT flip overall_parity (normal pending-push state)
            continue
        if p in ("behind", "diverged"):
            blocks_parity = True
        elif p == "unknown":
            # unknown does NOT flip overall_parity by itself (fail-soft),
            # but it also does NOT contribute equal evidence. network-class
            # reasons still surface via has_unreachable_remote.
            if r.get("reason") in ("network_timeout", "auth_failed", "not_found"):
                has_unreachable = True
            continue
    overall_parity = has_equal_evidence and not blocks_parity
    return {
        "overall_parity": overall_parity,
        "has_unreachable_remote": has_unreachable,
        "has_pending_push": has_pending_push,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def collect_multi_remote(project_root: Path) -> CollectorResult:
    """Phase 1.12 multi-remote parity collector.

    Reads `.aria/config.json` → `state_scanner.multi_remote`:
      - enabled (default true)
      - verify_mode: "local_refs" (default) | "ls_remote"
      - timeout_seconds (default 5)
    (F2′ retired `warn_after_hours` — see `_load_config` docstring.)

    F1′/F4′ freshness join (Phase 1, increment 4b): after scanning parity for
    every remote (unchanged git-side logic), this function reads the F3′
    `remote_refresh` (Phase 0.5) cache (`.aria/cache/remote-refresh.json`,
    `_read_remote_refresh_cache`) and joins each remote entry to its
    (repo_path, remote_name) leg — main repo path is `"."`, NEVER a bare remote
    name (top_risks: a bare-remote-name key would let a submodule's `origin`
    borrow the main repo's `fetched_at`). Each entry is annotated in place with
    `evidence_grade` (D20) via `_apply_freshness_downgrade`, which also
    rewrites `parity`/`reason` for "expired" `equal` entries
    (`not_refreshed`). `overall_parity` and `has_unreachable_remote` are then
    computed from the ANNOTATED entries via `_overall_parity` /
    `_has_unreachable_remote` (no longer via `_aggregate_flags`, which is
    retained only for its own direct tests — see its docstring).

    A missing/stale/absent remote_refresh cache degrades EVERY leg to
    `leg=None` → `evidence_grade="expired"` (fail-CLOSED, never silently
    "fresh") — this collector never re-implements fetching itself; that is
    exclusively `remote_refresh`'s job (module boundary, remote_refresh.py
    docstring "Keeping this boundary sharp is deliberate").

    `sync_freshness.{evidence_window_seconds,hard_cap_days,k_min}` (Phase 0
    landed config keys, `_load_sync_freshness_config`) supply the D15′/D18
    thresholds. `k_eff` (豁免资格's generation-age ceiling) is set to `k_min`
    unconditionally in this increment: `remote_refresh` (F3′) does not yet
    persist a per-host `observed_rotation` statistic (see its module notes),
    so this collector is permanently in the proposal's documented "cold start"
    state, whose defined fallback IS `k_eff = k_min` (fail-CLOSED, biased red
    rather than silently green) — NOT an ad-hoc simplification. A future
    increment that adds `observed_rotation` persistence must replace this
    constant with `min(K_CAP, max(k_min, observed_rotation))` per proposal §F3′.
    """
    r = CollectorResult()
    cfg = _load_config(project_root)

    enabled = cfg.get("enabled", True)
    if enabled is False:
        r.data = {"enabled": False}
        return r

    verify_mode = str(cfg.get("verify_mode", "local_refs")).lower()
    if verify_mode not in ("local_refs", "ls_remote"):
        verify_mode = "local_refs"
    timeout = int(cfg.get("timeout_seconds", _DEFAULT_TIMEOUT) or _DEFAULT_TIMEOUT)

    # Guard: must be inside a git working tree; otherwise emit enabled=true + empty blocks.
    rc, _, _ = _run(
        ["git", "rev-parse", "--is-inside-work-tree"], project_root, timeout=timeout
    )
    if rc != 0:
        r.soft_error("multi_remote_not_a_git_repo", f"rc={rc}")
        # pre_merge R1 fix (QA-R1-C1 / CR-R1-m1 / BA-R1-I1, 3/4 agent consensus):
        # emit overall_parity=False for the not-a-git-repo fallback. The prior
        # value True reinstated the pre-QA-C1 behaviour on this error path
        # because _aggregate_flags is never reached. Zero remotes = zero positive
        # evidence = overall_parity must be False (matches `_overall_parity([], [])`).
        r.data = {
            "enabled": True,
            "main_repo": None,
            "submodules": [],
            "overall_parity": False,
            "has_unreachable_remote": False,
            "has_pending_push": False,
        }
        return r

    # --- Main repo
    main_block = _scan_repo(project_root, ".", verify_mode, timeout)

    # --- Submodules
    submodule_blocks: list[dict[str, Any]] = []
    for rel_path in _enumerate_submodule_paths(project_root, timeout=timeout):
        sm_dir = project_root / rel_path
        if not sm_dir.exists() or not (sm_dir / ".git").exists():
            # Uninitialized submodule — skip (SKILL.md §1.12 fail-soft philosophy).
            continue
        try:
            block = _scan_repo(sm_dir, rel_path, verify_mode, timeout)
        except Exception as e:  # pragma: no cover — defensive
            r.soft_error("multi_remote_submodule_failed", f"{rel_path}: {e}")
            continue
        submodule_blocks.append(block)

    # --- F1′/F4′ freshness join: annotate every remote entry with evidence_grade
    # (and fetch_ok) by joining against the F3′ remote_refresh cache.
    freshness_cfg = _load_sync_freshness_config(project_root)
    evidence_window_seconds = int(
        freshness_cfg.get("evidence_window_seconds", _DEFAULT_EVIDENCE_WINDOW_SECONDS)
        or _DEFAULT_EVIDENCE_WINDOW_SECONDS
    )
    hard_cap_days = int(
        freshness_cfg.get("hard_cap_days", _DEFAULT_HARD_CAP_DAYS) or _DEFAULT_HARD_CAP_DAYS
    )
    hard_cap_seconds = hard_cap_days * 86400
    k_min = int(freshness_cfg.get("k_min", _DEFAULT_K_MIN) or _DEFAULT_K_MIN)
    k_eff = k_min  # cold-start fallback — see docstring above.

    refresh_cache = _read_remote_refresh_cache(project_root)
    raw_legs = refresh_cache.get("legs")
    legs_by_key: dict[str, Any] = raw_legs if isinstance(raw_legs, dict) else {}
    scan_generation = refresh_cache.get("scan_generation")
    if not isinstance(scan_generation, int) or isinstance(scan_generation, bool):
        scan_generation = 0
    now = scan_now()

    for block in [main_block, *submodule_blocks]:
        for remote_entry in block["remotes"]:
            leg = legs_by_key.get(
                _remote_refresh_leg_key(block["path"], remote_entry["name"])
            )
            leg = leg if isinstance(leg, dict) else None
            grade = _leg_evidence_grade(
                leg, now, scan_generation, evidence_window_seconds, hard_cap_seconds, k_eff
            )
            _apply_freshness_downgrade(remote_entry, grade)
            remote_entry["fetch_ok"] = (leg or {}).get("fetch_ok", "not_attempted")

    # --- Aggregate flags across all ANNOTATED remote entries (main + submodules)
    all_remote_entries: list[dict[str, Any]] = list(main_block["remotes"])
    for sb in submodule_blocks:
        all_remote_entries.extend(sb["remotes"])

    # ahead-detection is UNCHANGED (task 5.3 preserved decision) — computed
    # directly rather than via `_aggregate_flags` (see that function's Phase 1
    # docstring note for why it is bypassed here).
    has_pending_push = any(e.get("parity") == "ahead" for e in all_remote_entries)
    has_unreachable_remote = any(
        _has_unreachable_remote(e.get("fetch_ok", "not_attempted"))
        for e in all_remote_entries
    )
    # Phase 1: F5′ enforced-remote filtering is NOT yet wired here — every
    # discovered remote (unfiltered by `enforced_remotes`/`read_only_remotes`)
    # is passed as `enforced_entries` (task 6 scope, a later increment).
    # gitlink_integrity is the Phase 1 placeholder (always `[]` — Phase 2A/F10″
    # wires real data without changing this call site, see `_overall_parity`).
    overall_parity = _overall_parity(all_remote_entries, gitlink_integrity=[])

    data: dict[str, Any] = {
        "enabled": True,
        "main_repo": main_block,
        "submodules": submodule_blocks,
        "overall_parity": overall_parity,
        "has_unreachable_remote": has_unreachable_remote,
        "has_pending_push": has_pending_push,
    }

    r.data = data
    return r

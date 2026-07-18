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
              (Phase 2A/F10″: `gitlink_integrity` now carries real per-(R,S)
              verdicts — see `_classify_gitlink_pair`; repos with zero declared
              submodules still produce `[]`, vacuously satisfied).
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
      gitlink_integrity: [GitlinkPair, ...]   # Phase 2A/F10″ — see _classify_gitlink_pair

    GitlinkPair:
      remote: str                     # R — main repo's remote name
      submodule: str                  # S — declared submodule relative path
      status: ok|orphaned|orphan_unverified|no_published_ref|not_a_gitlink
              |uninitialized|shallow_unverifiable|no_matching_remote|soft_error
      consecutive_unverified: int      # gitlink-layer D18 counter, keyed (R,S)
                                        # — NOT the same counter as the
                                        # per-(repo,remote) leg counter below

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
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ._common import CollectorResult, _run, is_scan_offline, log, scan_now
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

# F10″/Phase 2A gitlink-layer (R,S) D18 counter cache — a SEPARATE physical
# file from `_REMOTE_REFRESH_CACHE_RELATIVE` above (blueprint
# `orphan_unverified_counter`: two independent per-scan writers sharing one
# physical file would make "who writes last" ambiguous; remote_refresh.py
# already owns that file's `legs`/`scan_generation` shape exclusively). Owned
# entirely by THIS module — the gitlink reachability check itself runs here,
# so its own D18 counter is written here too (`_write_gitlink_cache_atomic`),
# never by remote_refresh.py.
_GITLINK_CACHE_RELATIVE = ".aria/cache/gitlink-integrity.json"

_GITLINK_MODE_SUBMODULE = "160000"

# D18 (gitlink layer) counter reset states (tasks 13.4 — "清零绑「本 scan 该对
# 完成裁决 (status ∈ {ok, orphaned})」", a DIFFERENT clearing condition from the
# parity-layer per-leg counter, which clears on fetch success). The remaining
# six statuses (no_published_ref / not_a_gitlink / uninitialized /
# no_matching_remote / shallow_unverifiable / soft_error) are structural
# skip/soft-error states, not "was this pair verified or not" questions — the
# counter FREEZES on all of them (neither increments nor resets). This freeze
# reading is the blueprint's own INFERENCE, not spec-verbatim text (tasks 13.4
# only states the orphan_unverified/+1 and ok-or-orphaned/clear rules) — locked
# by a dedicated test per the blueprint's explicit request
# (`test_gitlink_integrity.py`), not left to implementer discretion silently.
_GITLINK_COUNTER_RESET_STATUSES = frozenset({"ok", "orphaned"})


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

# Public alias (F9′ 9.1, main spec state-scanner-stale-refs-false-parity): the
# session-closer `handoff_autofill.py` sibling-skill consumer needs this same
# reason set to triage `parity==unknown` (benign vs must-warn) without silently
# re-deriving/duplicating the literal set — "不重造". The leading-underscore
# name above stays the internal spelling used throughout this module; this is
# the only symbol other skills should import.
BENIGN_UNCONDITIONAL_REASONS = _BENIGN_UNCONDITIONAL_REASONS


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


def _gitlink_blocking(g: dict[str, Any], k_eff: int) -> bool:
    """F10″ gitlink-layer blocking predicate. `orphaned` always blocks (G is
    provably unreachable AND both legs are exemption-eligible AND generations
    are correctly ordered — see `_gitlink_reachability_verdict`).
    `orphan_unverified` blocks only once its OWN (R,S) D18 counter reaches
    `k_eff` (mirrors the parity-layer D18 escalation, tasks 13.4's F4′
    "gitlink 层裁决" sub-clause) — below that it is a benign-visible diagnostic
    (staleness/time-order ambiguity), not yet a confirmed breakage. Every other
    status (no_published_ref / not_a_gitlink / uninitialized /
    no_matching_remote / shallow_unverifiable / soft_error / ok) is
    benign-visible and never blocks."""
    status = g.get("status")
    if status == "orphaned":
        return True
    if status == "orphan_unverified":
        c = g.get("consecutive_unverified", 0)
        if not isinstance(c, int) or isinstance(c, bool):
            c = 0
        return c >= k_eff
    return False


# ---------------------------------------------------------------------------
# F10″/Phase 2A — orphaned-gitlink cross-repo reachability (multi_remote.py:
# blueprint p2_f10 — R5-C-A accident remedy). Five functions:
#   _resolve_published_gitlink_sha / _gitlink_unreachable /
#   _looks_like_no_such_commit / _gitlink_reachability_verdict /
#   _classify_gitlink_pair — orchestrating the nine-branch domain (tasks 13.2's
# eight non-ok exits + the implicit "ok" healthy exit) for one (remote,
# submodule) pair. Wired into `collect_multi_remote`'s R×S double loop below.
# ---------------------------------------------------------------------------


def _parse_ls_tree_gitlink_entry(ls_tree_output: str) -> str | None:
    """Parse ONE `git ls-tree <C> -- <path>` line into a gitlink sha, or None
    when the path is not currently a gitlink at C.

    Two distinct git-level facts both collapse into this single None outcome
    (blueprint `eight_branch_domain` gap-fill decision): (a) the path does not
    exist in C's tree at all (`ls-tree` exits 0 with EMPTY stdout — NOT a
    non-zero rc, tasks 13.2#2's "不能按 rc 探" — R7 backend M-1 verified this
    against a real repo), and (b) the path exists but is not a gitlink entry
    (`mode != 160000`, e.g. an ordinary directory). Both are byte-indistinguishable
    from "there is currently no gitlink at this path" without further
    disambiguation the blueprint declined to add a tenth branch for — both
    route callers to the same `not_a_gitlink` status.

    Anchors on the FIRST tab via `partition("\\t")`, never a bare `.split()` —
    a submodule path may itself contain spaces, which would misparse under a
    whitespace-only split. Malformed lines (no tab, <3 prefix fields) are
    treated the same as "not a gitlink" (fail-soft, never raises)."""
    text = ls_tree_output.strip()
    if not text:
        return None
    line = text.splitlines()[0]
    prefix, sep, _path = line.partition("\t")
    if not sep:
        return None
    fields = prefix.split()
    if len(fields) < 3 or fields[0] != _GITLINK_MODE_SUBMODULE:
        return None
    sha = fields[2].strip()
    return sha or None


def _resolve_published_gitlink_sha(
    main_repo_dir: Path,
    main_branch: str | None,
    remote: str,
    submodule_path: str,
    timeout: int,
) -> tuple[str | None, str | None]:
    """F10″ steps 1-2 — resolve `(C, G)` for ONE (remote, submodule) pair,
    self-contained (runs its OWN rev-parse). Kept as a standalone, directly
    unit-testable primitive.

    ⚠️ Production callers do NOT invoke this function from inside the
    `collect_multi_remote` R×S double loop — that would re-run the IDENTICAL
    rev-parse `|submodules|` times for the same R (top_risks: blows the
    O(|R|) call count up to O(|R|×|S|), pure waste since C does not depend on
    S). Instead `collect_multi_remote` resolves C ONCE per R with the same
    rev-parse this function performs (small deliberate duplication — same
    accepted pattern as `_remote_refresh_leg_key`/`_parse_leg_fetched_at`
    mirroring `remote_refresh._leg_key`/`_parse_iso` elsewhere in this module),
    and `_classify_gitlink_pair` receives that pre-resolved C directly (its
    `c`/`main_leg_ok` parameters) — doing ONLY the per-S ls-tree step, via the
    SAME `_parse_ls_tree_gitlink_entry` helper this function uses, so the
    parsing logic itself is never duplicated.

    C = `git rev-parse refs/remotes/{remote}/{main_branch}` — `main_branch is
    None`, OR rc != 0, OR empty stdout ⇒ `(None, None)` (caller routes to
    `no_published_ref`). G = the gitlink sha `git ls-tree {C} -- {submodule_path}`
    records (mode == 160000 only; see `_parse_ls_tree_gitlink_entry`) — `None`
    when the ls-tree call itself fails (rc != 0) or the path isn't a gitlink.
    """
    if main_branch is None:
        return None, None
    rc, out, _ = _run(
        ["git", "rev-parse", f"refs/remotes/{remote}/{main_branch}"],
        main_repo_dir,
        timeout=timeout,
    )
    if rc != 0:
        return None, None
    c = out.strip()
    if not c:
        return None, None

    rc, out, _ = _run(
        ["git", "ls-tree", c, "--", submodule_path], main_repo_dir, timeout=timeout
    )
    if rc != 0:
        return c, None
    return c, _parse_ls_tree_gitlink_entry(out)


def _looks_like_no_such_commit(stderr: str) -> bool:
    """Read-once stderr substring probe for git's rc=129 "object does not exist
    in this repo's local odb at all" failure mode. Deliberately NOT routed
    through `classify_git_error`/`GitErrorClass` — `gitlink_integrity`'s schema
    has no detail/stderr-carrying field whatsoever, so Rule #7's "never
    persisted" guarantee is satisfied STRUCTURALLY (there is nowhere for the
    string to go), a stronger guarantee than a typed channel with a bounded
    label field. `stderr` is read here ONLY to compute this bool and is then
    discarded — nothing derived from it is retained by the caller.

    ⚠️ Pattern-matches current git CLI wording (owner-verified on one git
    version only, per blueprint top_risks) — `rc == 129` itself is the PRIMARY
    signal (`_gitlink_unreachable` checks it first); this substring match is a
    secondary corroboration, not the sole gate, precisely so a future git
    version's slightly different wording degrades to `soft_error` (safe
    direction) rather than silently stops firing."""
    low = stderr.lower()
    return any(
        sig in low for sig in ("no such commit", "bad object", "not a valid object name")
    )


def _gitlink_unreachable(
    submodule_dir: Path, remote: str, g: str, timeout: int
) -> tuple[bool, bool]:
    """F10″ step — `(unreachable, is_soft_error)`. Runs
    `git -C {submodule_dir} branch -r --contains {G} --list "{remote}/*"`
    (branch-reachability ONLY — RM-11's deliberate tag-space exclusion).

    rc == 0 ∧ empty stdout ⇒ `(True, False)` — G genuinely exists in S's local
    object database but no `R/*` remote-tracking branch's ancestry contains it
    ("mirror lag": the more common, less severe unreachable case).

    rc == 129 ∧ `_looks_like_no_such_commit(stderr)` ⇒ `(True, False)` — G does
    not exist in S's local odb AT ALL ("nowhere to be found": the MORE severe
    case). tasks 13.2#6 / R7 backend C-4 explicitly forbid downgrading this to
    `soft_error` — a severity INVERSION (treating "G doesn't exist anywhere" as
    a lighter finding than "G exists but isn't mirrored yet") is exactly the
    bug this branch exists to prevent. Order matters: rc is checked BEFORE
    inspecting whether stdout happened to be empty, so a 129 can never fall
    through to the softer "other rc≠0" branch below.

    Any OTHER non-zero rc (repo corruption, permission errors, etc.) ⇒
    `(False, True)` — we genuinely could not run the check, so we say so
    honestly rather than guessing either "reachable" or "orphaned"."""
    rc, out, err = _run(
        [
            "git",
            "-C",
            str(submodule_dir),
            "branch",
            "-r",
            "--contains",
            g,
            "--list",
            f"{remote}/*",
        ],
        submodule_dir,
        timeout=timeout,
    )
    if rc == 0:
        return out.strip() == "", False
    if rc == 129 and _looks_like_no_such_commit(err):
        return True, False
    return False, True


def _gitlink_reachability_verdict(
    main_leg: dict[str, Any] | None,
    sub_leg: dict[str, Any] | None,
    now: datetime,
    scan_generation: int,
    evidence_window_seconds: int,
    hard_cap_seconds: int,
    k_eff: int,
    unreachable: bool,
) -> str:
    """The final (R,S) verdict once the contains check ran (called for BOTH the
    reachable and unreachable outcomes — the 豁免资格 gate below applies to each,
    since a conclusion drawn off stale refs is unverified whichever way it points).
    Reuses the already-landed `_exemption_eligible` (豁免资格) TWICE — once for
    the main repo's `(".", R)` leg, once for the submodule's `(S, R)` leg — NOT
    the gitlink-layer `orphan_unverified` (R,S)-keyed counter (a DIFFERENT
    counter with a different key space, see `_GITLINK_COUNTER_RESET_STATUSES`
    and the cache functions below).

    `main_leg`/`sub_leg` are `remote_refresh` per-leg cache RECORDS (the same
    shape `_leg_evidence_grade` consumes) — `None` (never fetched / no cache
    entry) is treated identically to a present-but-null `fetched_at`
    (fail-CLOSED, same convention `_leg_evidence_grade` already uses).

    `main_exempt ∧ sub_exempt ∧ gen(S,R) ≥ gen(主仓,R)` (all three, RM-1/RM-2)
    ⇒ `"orphaned"` (a confirmed, non-stale, non-time-order-ambiguous breakage).
    Otherwise ⇒ `"orphan_unverified"` (staleness or cross-leg generation skew
    means we cannot yet rule out a time-order illusion — D18 escalates it to
    blocking only after `k_eff` consecutive unresolved scans, see
    `_gitlink_blocking`).

    `evidence_window_seconds` is accepted for parameter-list symmetry with the
    other F1′/F4′ join call sites this function's sibling functions share
    (e.g. `_leg_evidence_grade`) but is NOT itself consumed here — gitlink
    verdicts gate exclusively on 豁免资格 (`_exemption_eligible`), never on
    证据资格 (`_evidence_eligible`); see the proposal's `gitlink_orphaned(R)`
    predicate-table row, which lists only 豁免资格 conjuncts."""

    def _exempt(leg: dict[str, Any] | None) -> bool:
        fetched_at = _parse_leg_fetched_at(leg.get("fetched_at")) if leg else None
        generation_fetched = leg.get("generation_fetched") if leg else None
        if not isinstance(generation_fetched, int) or isinstance(generation_fetched, bool):
            generation_fetched = None
        consecutive_unverified = leg.get("consecutive_unverified", 0) if leg else 0
        if (
            not isinstance(consecutive_unverified, int)
            or isinstance(consecutive_unverified, bool)
        ):
            consecutive_unverified = 0
        return _exemption_eligible(
            fetched_at,
            now,
            generation_fetched,
            scan_generation,
            k_eff,
            hard_cap_seconds,
            consecutive_unverified,
        )

    def _generation_of(leg: dict[str, Any] | None) -> int | None:
        gen = leg.get("generation_fetched") if leg else None
        return gen if isinstance(gen, int) and not isinstance(gen, bool) else None

    main_exempt = _exempt(main_leg)
    sub_exempt = _exempt(sub_leg)
    main_gen = _generation_of(main_leg)
    sub_gen = _generation_of(sub_leg)
    gen_ok = main_gen is not None and sub_gen is not None and sub_gen >= main_gen

    if not (main_exempt and sub_exempt and gen_ok):
        # ¬豁免 / cross-leg generation skew ⇒ we cannot verify the pair THIS scan,
        # regardless of what the (possibly stale) contains check said. Both a stale
        # "reachable" and a stale "unreachable" collapse to orphan_unverified —
        # D18 escalates it to blocking only after k_eff consecutive unresolved scans.
        return "orphan_unverified"
    # 豁免 holds ⇒ the contains result is trustworthy (fresh-enough refs):
    return "orphaned" if unreachable else "ok"


def _classify_gitlink_pair(
    main_repo_dir: Path,
    main_branch: str | None,
    sub_dir: Path,
    sub_path: str,
    remote: str,
    main_leg: dict[str, Any] | None,
    sub_leg: dict[str, Any] | None,
    timeout: int,
    now: datetime,
    scan_generation: int,
    evidence_window_seconds: int,
    hard_cap_seconds: int,
    k_eff: int,
    c: str | None,
    main_leg_ok: bool,
) -> str:
    """Orchestrates the F10″ nine-branch domain (tasks 13.2's eight non-ok
    exits + the implicit "ok" healthy exit) for ONE (remote, submodule_path)
    pair, in the FIXED order the blueprint derives (`eight_branch_domain` —
    load-bearing; reordering can change which branch a given fixture lands in):

      1. `no_published_ref`    — `main_leg_ok` is False (caller could not
         resolve C for this R at all — resolved ONCE per R by the caller, see
         below; main-repo detached HEAD routes here for every S, tasks 13.6)
      2. `not_a_gitlink`       — ls-tree(C, S) is empty OR mode != 160000
         (`_parse_ls_tree_gitlink_entry`'s gap-fill; this step only reads the
         MAIN repo's object database, so it is safe even when S itself is not
         yet initialized — "此步只读主仓对象库, 不require S 已 init")
      3. `uninitialized`       — S has no on-disk `.git`
      4. `no_matching_remote`  — S has no remote literally named `remote`
         (checked BEFORE the `contains` call — R7 RM-3: `rc=0` empty output is
         BYTE-IDENTICAL between "no matching remote" and "genuine orphan"; the
         distinction can only be made at the leg-enumeration layer, never by
         inspecting `contains`'s own result)
      5. `shallow_unverifiable` — S is a shallow clone (reachability is
         undecidable, not merely inconvenient — an honest, non-blocking
         "unknown", not a "no")
      6. contains-based verdict — `ok` (branch-reachable) /
         `soft_error` (the check itself could not run) /
         `orphaned` / `orphan_unverified` (via `_gitlink_reachability_verdict`)

    `c` / `main_leg_ok`: the CALLER (`collect_multi_remote`) resolves the main
    repo's published commit on `remote` ONCE per R (outer loop, mirroring the
    rev-parse `_resolve_published_gitlink_sha` performs) and passes the result
    here. `main_leg_ok=False` short-circuits to branch 1 without this function
    touching git at all — it never re-derives C itself."""
    if not main_leg_ok:
        return "no_published_ref"

    rc, out, _ = _run(["git", "ls-tree", c, "--", sub_path], main_repo_dir, timeout=timeout)
    if rc != 0:
        # ls-tree COMMAND failed (GC race that made the just-resolved C unreachable,
        # disk I/O error) — a distinct event from "the path is genuinely not a gitlink
        # in C". Fold the two together and a transient command failure masquerades as
        # a structural not_a_gitlink verdict (review Important). Only rc==0 empty
        # output / mode≠160000 is the honest not_a_gitlink.
        return "soft_error"
    g = _parse_ls_tree_gitlink_entry(out)
    if g is None:
        return "not_a_gitlink"

    if not sub_dir.exists() or not (sub_dir / ".git").exists():
        return "uninitialized"

    if remote not in _list_remotes(sub_dir, timeout):
        return "no_matching_remote"

    if _is_shallow(sub_dir, timeout):
        return "shallow_unverifiable"

    unreachable, is_soft_error = _gitlink_unreachable(sub_dir, remote, g, timeout)
    if is_soft_error:
        return "soft_error"
    # The 豁免资格 gate applies to BOTH conclusions (branch 5: ¬豁免 ⇒ orphan_unverified
    # regardless of reachability). A reachable verdict computed off STALE remote-tracking
    # refs is no more trustworthy than an unreachable one — reporting "ok" on unverified
    # refs is the same stale-evidence-as-positive-proof false-green this Spec exists to
    # kill (review BLOCKER). So route reachable through the same freshness gate.
    return _gitlink_reachability_verdict(
        main_leg,
        sub_leg,
        now,
        scan_generation,
        evidence_window_seconds,
        hard_cap_seconds,
        k_eff,
        unreachable,
    )


# ---------------------------------------------------------------------------
# F10″/Phase 2A — gitlink-layer (R,S) D18 counter cache. A SEPARATE physical
# file from the F3′ remote_refresh cache (see `_GITLINK_CACHE_RELATIVE`'s
# module-level docstring above) — owned entirely by this module.
# ---------------------------------------------------------------------------
def _gitlink_pair_key(remote: str, submodule: str) -> str:
    """Cache key for a (R, S) gitlink pair — SAME `"{a}::{b}"` textual
    convention as `_remote_refresh_leg_key`/`remote_refresh._leg_key`, but a
    DIFFERENT key space in a DIFFERENT physical file — never confused with a
    (repo, remote) leg key even when a remote name and a submodule path happen
    to collide as strings, because they never share a cache file."""
    return f"{remote}::{submodule}"


def _read_gitlink_cache(project_root: Path) -> dict[str, Any]:
    """Fail-soft read of the gitlink-layer (R,S) counter cache. Missing file /
    malformed JSON / non-dict payload → `{}` — every pair then starts this
    scan's counter arithmetic from a prior count of 0 (same fail-soft
    convention as `_read_remote_refresh_cache`)."""
    cache_file = project_root / _GITLINK_CACHE_RELATIVE
    if not cache_file.is_file():
        return {}
    try:
        raw = cache_file.read_text(encoding="utf-8", errors="replace")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_gitlink_cache_atomic(project_root: Path, pairs: dict[str, dict[str, Any]]) -> None:
    """Single-thread, ONE-TIME read-merge-atomic-write (tmp+rename), mirroring
    `remote_refresh._write_cache_atomic`'s pattern at small scale (this cache
    has one flat `pairs` map, not `legs`+`scan_generation` — generalizing that
    function's merge logic was judged not worth the coupling; blueprint
    `orphan_unverified_counter` persistence note — this module already accepts
    this class of small duplication for `_leg_key`/`_parse_iso`, for the same
    circular-import reason).

    Re-reads whatever is CURRENTLY on disk and merges `pairs` on top before the
    atomic write, so a concurrent scan's write is never silently clobbered into
    data loss (RM-6a's accepted "stale but never corrupt" degradation
    direction, mirrored here for this cache too)."""
    cache_file = project_root / _GITLINK_CACHE_RELATIVE
    try:
        current_on_disk = _read_gitlink_cache(project_root)
    except Exception:  # pragma: no cover — defensive
        current_on_disk = {}
    raw_pairs = current_on_disk.get("pairs")
    merged: dict[str, Any] = dict(raw_pairs) if isinstance(raw_pairs, dict) else {}
    merged.update(pairs)
    payload = {"pairs": merged}
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_file.with_name(cache_file.name + f".tmp{os.getpid()}")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, cache_file)
    except OSError as exc:
        # fail-soft (never crash the collector) but NOT silent — mirrors
        # remote_refresh._write_cache_atomic's same tradeoff: a persistent
        # write failure here pins every (R,S) pair's D18 counter at its prior
        # value, which can delay (never falsely trigger) the orphan_unverified
        # → blocking escalation.
        log.warning(
            "gitlink_integrity: cache write failed (%s); D18 (R,S) counters "
            "will not advance until this succeeds",
            exc,
        )


def _overall_parity(
    enforced_entries: list[dict[str, Any]],
    gitlink_integrity: list[dict[str, Any]],
    k_eff: int,
) -> bool:
    """F4′ v8 decision table (SOT = proposal L459-506). Four clauses:

      1. enforced_set ≠ ∅            (guard the ``all([])`` vacuous-true)
      2. ∃ r: parity==equal ∧ evidence_grade=="fresh"   (⚠️ BOTH — a stale_unverified
         equal keeps parity==equal so a parity-only ∃ check resurrects the 14h accident)
      3. ∀ R: ¬gitlink_blocking(R, k_eff)   (Phase 2A/F10″: `gitlink_integrity` now
         carries real per-(R,S) verdicts; a UNIVERSAL-NEGATION clause, so empty input
         is safe, unlike clause 1's positive-evidence empty set — repos with zero
         declared submodules always pass this clause vacuously)
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
    if any(_gitlink_blocking(g, k_eff) for g in gitlink_integrity):
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
        # evidence = overall_parity must be False (matches `_overall_parity([], [], 0)`).
        r.data = {
            "enabled": True,
            "main_repo": None,
            "submodules": [],
            "overall_parity": False,
            "has_unreachable_remote": False,
            "has_pending_push": False,
            "gitlink_integrity": [],
        }
        return r

    # --- Main repo
    main_block = _scan_repo(project_root, ".", verify_mode, timeout)

    # --- Submodules
    # `submodule_paths` (ALL declared paths, incl. UNINITIALIZED ones) is
    # captured once here and reused by the F10″ gitlink loop below — that loop
    # needs to see uninitialized submodules too (`uninitialized` is one of its
    # own status values), unlike `submodule_blocks` here, which skips them.
    submodule_paths = _enumerate_submodule_paths(project_root, timeout=timeout)
    submodule_blocks: list[dict[str, Any]] = []
    for rel_path in submodule_paths:
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

    # --- F10″/Phase 2A: gitlink cross-repo reachability check. Produces
    # `gitlink_integrity[]`, one entry per (R, S) pair, R ranging over the main
    # repo's ENFORCED remotes and S ranging over ALL declared submodule paths
    # (`submodule_paths`, captured above — includes uninitialized ones, unlike
    # `submodule_blocks`). Skipped entirely when there are no declared
    # submodules at all (no (R,S) pairs possible ⇒ zero git calls paid for a
    # check that can never fire — also keeps every pre-existing submodule-less
    # test fixture from needing new mocked commands).
    main_branch = main_block["branch"]
    gitlink_integrity_list: list[dict[str, Any]] = []
    if submodule_paths:
        enforced_main_remotes, _ = resolve_enforced_remotes(
            cfg.get("enforced_remotes"),
            [rr["name"] for rr in main_block["remotes"]],
            tuple(cfg.get("read_only_remotes") or ()),
        )
        gitlink_cache = _read_gitlink_cache(project_root)
        raw_gitlink_pairs = gitlink_cache.get("pairs")
        gitlink_pairs_on_disk: dict[str, Any] = (
            raw_gitlink_pairs if isinstance(raw_gitlink_pairs, dict) else {}
        )
        gitlink_pairs_out: dict[str, dict[str, Any]] = {}

        for remote in enforced_main_remotes:
            # C is resolved ONCE per R here (NOT inside the S loop below) —
            # the O(|R|) vs O(|R|×|S|) discipline `_resolve_published_gitlink_sha`'s
            # docstring calls out. main_branch is None (main repo detached HEAD,
            # a CI-checkout state) ⇒ c stays None / main_leg_ok stays False for
            # EVERY S under this R (tasks 13.6: routes every (R,S) pair to
            # `no_published_ref`, never touching git for the S side at all).
            c: str | None = None
            main_leg_ok = False
            if main_branch is not None:
                rc, out, _ = _run(
                    ["git", "rev-parse", f"refs/remotes/{remote}/{main_branch}"],
                    project_root,
                    timeout=timeout,
                )
                if rc == 0 and out.strip():
                    c = out.strip()
                    main_leg_ok = True

            main_leg = legs_by_key.get(_remote_refresh_leg_key(".", remote))
            main_leg = main_leg if isinstance(main_leg, dict) else None

            for sub_path in submodule_paths:
                sub_dir = project_root / sub_path
                sub_leg = legs_by_key.get(_remote_refresh_leg_key(sub_path, remote))
                sub_leg = sub_leg if isinstance(sub_leg, dict) else None

                status = _classify_gitlink_pair(
                    project_root,
                    main_branch,
                    sub_dir,
                    sub_path,
                    remote,
                    main_leg,
                    sub_leg,
                    timeout,
                    now,
                    scan_generation,
                    evidence_window_seconds,
                    hard_cap_seconds,
                    k_eff,
                    c,
                    main_leg_ok,
                )

                pair_key = _gitlink_pair_key(remote, sub_path)
                prior_pair = gitlink_pairs_on_disk.get(pair_key)
                prior_count = (
                    prior_pair.get("consecutive_unverified", 0)
                    if isinstance(prior_pair, dict)
                    else 0
                )
                if (
                    not isinstance(prior_count, int)
                    or isinstance(prior_count, bool)
                    or prior_count < 0
                ):
                    prior_count = 0
                if is_scan_offline():
                    # 9.7 counter face: an offline scan verified nothing this round,
                    # so it must NOT advance the D18 counter (parity-layer
                    # consecutive_unverified freezes offline in remote_refresh for the
                    # same reason). Keeping prior_count keeps repeated offline scans
                    # byte-stable (test_channel7_8 / test_two_consecutive_runs_diff_zero).
                    new_count = prior_count
                elif status in _GITLINK_COUNTER_RESET_STATUSES:
                    new_count = 0
                elif status == "orphan_unverified":
                    new_count = prior_count + 1
                else:
                    # frozen: structural skip/soft_error states are neither a
                    # "new evidence" nor a "confirmed unverified" event.
                    new_count = prior_count

                gitlink_pairs_out[pair_key] = {"consecutive_unverified": new_count}
                gitlink_integrity_list.append(
                    {
                        "remote": remote,
                        "submodule": sub_path,
                        "status": status,
                        "consecutive_unverified": new_count,
                    }
                )

        _write_gitlink_cache_atomic(project_root, gitlink_pairs_out)

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
    # gitlink_integrity now carries REAL per-(R,S) verdicts (Phase 2A/F10″,
    # computed above) — repos with zero declared submodules still pass `[]`.
    overall_parity = _overall_parity(
        all_remote_entries, gitlink_integrity=gitlink_integrity_list, k_eff=k_eff
    )

    data: dict[str, Any] = {
        "enabled": True,
        "main_repo": main_block,
        "submodules": submodule_blocks,
        "overall_parity": overall_parity,
        "has_unreachable_remote": has_unreachable_remote,
        "has_pending_push": has_pending_push,
        "gitlink_integrity": gitlink_integrity_list,
    }

    r.data = data
    return r

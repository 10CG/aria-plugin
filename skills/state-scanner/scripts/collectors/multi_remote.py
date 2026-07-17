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
- `overall_parity` semantics (explicit, post-QA-C1 + BA-R1-C1):
    * true  = at least one remote has `parity == equal` AND no remote has
              `parity ∈ {behind, diverged}`. Positive-evidence + no-blockers
              rule — zero-info inputs (all unknown, empty list, not-a-git-repo)
              yield `False`.
    * false = zero `equal` evidence OR any `parity ∈ {behind, diverged}`
    * `parity: ahead`   does NOT count (→ `has_pending_push`)
    * `parity: unknown` does NOT contribute evidence (→ `has_unreachable_remote`
                         when the reason is network-class)
    SKILL.md §1.12 spec text is kept in sync with this definition.

Output shape (conformant to SKILL.md §1.12 schema):

    multi_remote:
      enabled: bool
      main_repo: RepoParity           # when enabled=true
      submodules: [RepoParity, ...]   # same shape, path-keyed
      overall_parity: bool
      has_unreachable_remote: bool
      has_pending_push: bool
      local_refs_stale: bool          # optional, set when FETCH_HEAD > warn_after_hours

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
                  | auth_failed | not_found | network_timeout
          method: local_refs | ls_remote
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ._common import CollectorResult, _run
from .git import _current_branch, _enumerate_submodule_paths, _is_shallow

_DEFAULT_TIMEOUT = 5
_DEFAULT_WARN_AFTER_HOURS = 24


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------
def _load_config(project_root: Path) -> dict[str, Any]:
    """Read `.aria/config.json` → `state_scanner.multi_remote` block.

    Missing file / missing block → defaults (enabled=true, verify_mode=local_refs).
    Malformed JSON → defaults + soft error logged by caller if it cares.
    """
    cfg_path = project_root / ".aria" / "config.json"
    if not cfg_path.exists():
        return {}
    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    ss = raw.get("state_scanner") or {}
    mr = ss.get("multi_remote") or {}
    # warn_after_hours inherits from sync_check block if not set on multi_remote
    sync_cfg = ss.get("sync_check") or {}
    if "warn_after_hours" not in mr and "warn_after_hours" in sync_cfg:
        mr["warn_after_hours"] = sync_cfg["warn_after_hours"]
    return mr


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


def _fetch_head_age_hours(repo_dir: Path, timeout: int) -> float | None:
    """Return hours since FETCH_HEAD last modified, or None if file missing."""
    gitdir = _gitdir_for(repo_dir, timeout)
    if gitdir is None:
        return None
    fh = gitdir / "FETCH_HEAD"
    if not fh.exists():
        return None
    try:
        mtime = fh.stat().st_mtime
    except OSError:
        return None
    return max(0.0, (time.time() - mtime) / 3600.0)


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
) -> tuple[dict[str, Any], bool]:
    """Scan one repo (main or submodule). Returns (repo_block, stale_flag)."""
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

    repo_block: dict[str, Any] = {
        "path": path_label,
        "local_head": local_head,
        "branch": branch,
        "remotes": remote_results,
    }
    # Staleness only meaningful for local_refs mode.
    stale = False
    return repo_block, stale


# ---------------------------------------------------------------------------
# F1′/F4′ predicates (main spec stale-refs-false-parity, Phase 1)
# ---------------------------------------------------------------------------
# SOT = proposal F4′ v8 formula block (D15′ dual-role predicates + D20 evidence_grade
# full partition). These are PURE functions consuming the per-leg fetch signals that
# remote_refresh (F3′, Phase 0.5) produces (fetched_at / fetch_ok / generation /
# consecutive_unverified). They are additive here; collect_multi_remote wires them to
# real remote_refresh data in a later increment. Registered in the D16 predicate-domain
# table (references/predicate-domain-table.md). Retired single-role predicate 可信(r) is
# forbidden (its single-role conflation was the R7 three-Critical root).


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
      - warn_after_hours (default 24; falls back to sync_check.warn_after_hours)
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
    warn_after_hours = float(
        cfg.get("warn_after_hours", _DEFAULT_WARN_AFTER_HOURS) or _DEFAULT_WARN_AFTER_HOURS
    )

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
        # evidence = overall_parity must be False (matches `_aggregate_flags([])`).
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
    main_block, _ = _scan_repo(project_root, ".", verify_mode, timeout)

    # --- Submodules
    submodule_blocks: list[dict[str, Any]] = []
    for rel_path in _enumerate_submodule_paths(project_root, timeout=timeout):
        sm_dir = project_root / rel_path
        if not sm_dir.exists() or not (sm_dir / ".git").exists():
            # Uninitialized submodule — skip (SKILL.md §1.12 fail-soft philosophy).
            continue
        try:
            block, _ = _scan_repo(sm_dir, rel_path, verify_mode, timeout)
        except Exception as e:  # pragma: no cover — defensive
            r.soft_error("multi_remote_submodule_failed", f"{rel_path}: {e}")
            continue
        submodule_blocks.append(block)

    # --- Aggregate flags across all remote entries (main + submodules)
    all_remote_entries: list[dict[str, Any]] = list(main_block["remotes"])
    for sb in submodule_blocks:
        all_remote_entries.extend(sb["remotes"])
    flags = _aggregate_flags(all_remote_entries)

    # --- FETCH_HEAD staleness (main repo only; submodules handled implicitly)
    local_refs_stale = False
    if verify_mode == "local_refs":
        age = _fetch_head_age_hours(project_root, timeout)
        if age is not None and age > warn_after_hours:
            local_refs_stale = True

    data: dict[str, Any] = {
        "enabled": True,
        "main_repo": main_block,
        "submodules": submodule_blocks,
        **flags,
    }
    if local_refs_stale:
        data["local_refs_stale"] = True

    r.data = data
    return r

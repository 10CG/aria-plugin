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
- `overall_parity` semantics (explicit):
    * true  = all per-remote `parity == equal`
    * false = any per-remote `parity ∈ {behind, diverged}`
    * `parity: ahead`   does NOT count (→ `has_pending_push`)
    * `parity: unknown` does NOT count (→ `has_unreachable_remote`)

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
        r.data = {
            "enabled": True,
            "main_repo": None,
            "submodules": [],
            "overall_parity": True,
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

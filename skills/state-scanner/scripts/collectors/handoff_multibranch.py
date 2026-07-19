"""Phase 1 (multi-terminal-coordination) — cross-branch handoff track rebuilder.

Scans every ``origin/*`` branch for ``docs/handoff/*.md`` files, calls
``parse_handoff_frontmatter`` from the sibling ``handoff`` collector, and
reconstructs the multi-track dashboard track list consumed by TASK-005.

This collector is **read-only**: it uses ``git show`` / ``git ls-tree`` /
``git log`` to inspect remote refs without touching the working tree or index.
It MUST run AFTER ``collect_remote_refresh`` (Phase 0.5, F3′) so that all remote
refs are present locally. (Pre-F6′ this was ``collect_coordination_fetch``; that
collector's network I/O was retired into ``remote_refresh.py`` and
``coordination_fetch.py`` is now a pure derivation shim.)

Return schema (top-level snapshot key: ``tracks_multibranch``):

    {
        "exists": bool,         # True when ≥1 track found across all branches
        "tracks": list[dict],   # One entry per (branch, file) pair — see below
        "branches_scanned": int,
        "legacy_count": int,    # Tracks that fell back to legacy (no frontmatter)
        "collision": {          # TASK-000 (#133) — additive, ADVISORY-ONLY
            "kind": str,        # "none" | "cross_owner" | "self_multi_container"
            "groups": list,     # list[list[str]] — per colliding track_id: oc members
        },
        "errors": list[str],    # Accumulated non-fatal error messages
    }

Each entry in ``tracks`` is:

    {
        "track_id": str,          # frontmatter["track-id"] OR "legacy:<branch>:<filename>"
        "owner_container": str,   # frontmatter["owner-container"] OR "unknown"
        "phase": str,             # frontmatter["phase"] OR "unknown"
        "status": str,            # frontmatter["status"] OR "legacy"
        "updated_at": str,        # frontmatter["updated-at"] OR git log committer date (ISO)
        "branch": str,            # short branch name (no "origin/" prefix)
        "filename": str,          # basename of the handoff file
        "legacy": bool,           # True when frontmatter was absent/incomplete
    }

Design notes:

- ``git ls-tree`` + ``git show`` operate on remote ref objects — no checkout.
- ``latest.md`` is excluded per ``feedback_collector_exclude_navigation_pointer``
  memory entry (it is a navigation pointer, not a real handoff document).
- Same ``track_id`` appearing on multiple branches is intentionally preserved
  (collision detection per session-handoff.md §2.3.5).  TASK-005 renders the
  collision signals.
- Frontmatter parsing uses a stdlib-only YAML-subset parser (since v1.30.2,
  fix for Forgejo aria-plugin #57 Finding 2) — no external dep required.
- Performance: limited to ``refs/remotes/origin/`` (shallow ref list from
  TASK-003 fetch) — history is not walked.
- If the remote branch count exceeds the resolved scan cap (default 20, see
  resolve_max_branches_scanned in _common.py; #71 v1.38.0) only the first N
  branches (most-recent by committerdate) are processed.  A soft_error notes
  the cap, quoting the resolved value.

Spec: openspec/changes/multi-terminal-coordination/tasks.md §1.4
Task: TASK-004 (backend-architect)
Deps: remote_refresh.py (F3′; supersedes TASK-003 coordination_fetch.py fetching)
      + TASK-009 (handoff.py parse_handoff_frontmatter)
"""

from __future__ import annotations

from pathlib import Path

# Note (Round 6 review): `git show` / `git ls-tree` invocations below intentionally
# omit the `--` ref/path separator because `for-each-ref` upstream already filters
# to legitimate `refs/remotes/origin/*` strings — there is no path that could be
# misinterpreted as a flag. Adding `--` would require a refactor for `git show`'s
# `<ref>:<path>` syntax (which does not accept `--` between ref and path).

from ._common import (
    CollectorResult,
    _run,
    classify_git_error,
    log,
    resolve_max_branches_scanned,
)
from .handoff import parse_handoff_frontmatter

# ---------------------------------------------------------------------------
# Collision classification (TASK-000, concurrent-session-upm-safety #133).
# Persist the advisory collision summary (tracks_multibranch.collision) so that
# downstream consumers (state-scanner Phase 2 advisory / track_board renderer)
# read one source of truth instead of recomputing — and so the field is no
# longer a phantom (sister R1 C1).  Import is guarded: lib/ is a sibling of
# scripts/, not under collectors/, so we inject the state-scanner root onto
# sys.path (mirrors scripts/renderers/track_board.py's strategy).
# ---------------------------------------------------------------------------
try:
    import sys as _sys
    from pathlib import Path as _Path
    _SS_ROOT = str(_Path(__file__).resolve().parent.parent.parent)  # state-scanner/
    if _SS_ROOT not in _sys.path:
        _sys.path.insert(0, _SS_ROOT)
    from lib.collision import classify as _classify_collision_summary  # type: ignore[import]
    _COLLISION_AVAILABLE = True
except ImportError:
    _COLLISION_AVAILABLE = False  # fail-soft: collision summary degrades to none

# ── Constants ─────────────────────────────────────────────────────────────────

# Maximum number of remote branches to scan per run.
# Tasks.md §1.3 notes fetch is limited to refs/heads/* already; this is
# an additional guard against excessively large repos.
# v1.38.0 (#71): the cap is now 3-layer configurable (env > config > default 20)
# via `resolve_max_branches_scanned()` in _common.py — resolved per-run inside
# collect_handoff_multibranch(), no longer a module-level constant. Large repos
# (e.g. 440 remote branches) set state_scanner.handoff_multibranch.max_branches
# or ARIA_HANDOFF_MAX_BRANCHES to lift the default.

# File excluded from handoff doc detection (navigation pointer, not a doc).
# Must match POINTER_FILENAME in handoff.py for consistency.
_POINTER_FILENAME: str = "latest.md"

# The remote name that remote_refresh.py fetches from (F3′, Phase 0.5).
_REMOTE: str = "origin"

# docs/handoff/ tree path (trailing slash required by git ls-tree --name-only)
_HANDOFF_TREE_PATH: str = "docs/handoff"

# Short timeout for per-file git show (content read).
_GIT_SHOW_TIMEOUT: int = 5

# Timeout for listing branch refs and ls-tree.
_GIT_LIST_TIMEOUT: int = 5


# ── Helpers ───────────────────────────────────────────────────────────────────


def _list_origin_branches(project_root: Path) -> tuple[list[str], str | None]:
    """Return (branch_names, error_msg|None) where branch_names are short names.

    Uses ``git for-each-ref --format='%(refname:short)' refs/remotes/origin/``
    to enumerate all remote branches that were populated by TASK-003 fetch.
    Excludes the synthetic ``origin/HEAD`` pointer.
    """
    # Sort by committerdate desc so most-recently-updated branches win the
    # scan cap (Round 8 tech-lead Finding #4 fix — previously
    # lexicographic order let archive/* + bugfix/* steal scan budget from
    # master + feature/*; first dogfood run after v1.22.0 ship immediately
    # surfaced this in real use against this very Aria repo).
    cmd = [
        "git",
        "for-each-ref",
        "--sort=-committerdate",
        "--format=%(refname:short)",
        "refs/remotes/origin/",
    ]
    rc, stdout, stderr = _run(cmd, cwd=project_root, timeout=_GIT_LIST_TIMEOUT)
    if rc != 0:
        # Internal classification (Spec B v5 R8 C-1): stderr is consumed here and
        # NOT returned raw — the caller receives a bounded label, so stderr never
        # escapes this function into snapshot.
        cls = classify_git_error(rc, stderr, "git for-each-ref")
        return [], f"git for-each-ref {cls.label} (rc={cls.rc})"

    branches: list[str] = []
    for line in stdout.splitlines():
        short = line.strip()
        if not short:
            continue
        # Strip "origin/" prefix to get the bare branch name.
        # e.g. "origin/feature/multi-terminal-coordination" → "feature/multi-terminal-coordination"
        if short.startswith(f"{_REMOTE}/"):
            bare = short[len(f"{_REMOTE}/"):]
        else:
            bare = short
        # Exclude the HEAD pointer ref
        if bare == "HEAD":
            continue
        branches.append(bare)

    # Preserve `git for-each-ref --sort=-committerdate` ordering (most-recently-updated
    # branches first) so the scan cap keeps active branches over stale ones.
    # Round 8 tech-lead Finding #4 fix — previously `sorted(branches)` undid the git
    # sort and let archive/* + bugfix/* steal scan budget. Surfaced at zero-day dogfood.
    return branches, None


def _list_handoff_files(project_root: Path, branch: str) -> tuple[list[str], str | None]:
    """Return (filenames, error_msg|None) of handoff .md files on a remote branch.

    Uses ``git ls-tree -r --name-only origin/<branch> -- docs/handoff/``.
    Excludes ``latest.md`` (navigation pointer).

    Returns only the basename (not the full path) for each file so callers
    compose the full git-object path as needed.
    """
    ref = f"{_REMOTE}/{branch}"
    cmd = [
        "git",
        "ls-tree",
        "-r",
        "--name-only",
        ref,
        "--",
        _HANDOFF_TREE_PATH,
    ]
    rc, stdout, stderr = _run(cmd, cwd=project_root, timeout=_GIT_LIST_TIMEOUT)

    if rc != 0:
        # Branch may have been deleted between fetch and now, or the tree path
        # simply doesn't exist — not an error worth blocking the scan for.
        stderr_lower = stderr.lower()
        if "not a tree object" in stderr_lower or "not a valid object" in stderr_lower:
            return [], None  # Branch has no docs/handoff/ tree — silently skip
        # benign-skip preserved above (still first, still in-function); only a
        # NON-benign failure reaches classify_git_error (Spec B v5 R8 C-1 / R7 m-1).
        cls = classify_git_error(rc, stderr, "git ls-tree")
        return [], f"git ls-tree failed for {ref} ({cls.label}, rc={cls.rc})"

    filenames: list[str] = []
    for line in stdout.splitlines():
        path = line.strip()
        if not path:
            continue
        basename = Path(path).name
        if not basename.endswith(".md"):
            continue
        if basename == _POINTER_FILENAME:
            # Exclude navigation pointer per feedback_collector_exclude_navigation_pointer
            log.debug(
                "handoff_multibranch: excluding pointer file '%s' on branch '%s'",
                basename,
                branch,
            )
            continue
        filenames.append(basename)

    return filenames, None


def _read_file_content(
    project_root: Path, branch: str, filename: str
) -> tuple[str | None, str | None]:
    """Return (content, error_msg|None) for a handoff file on a remote branch.

    Uses ``git show origin/<branch>:docs/handoff/<filename>`` to read the file
    object without checking out the branch.
    """
    ref = f"{_REMOTE}/{branch}:{_HANDOFF_TREE_PATH}/{filename}"
    cmd = ["git", "show", ref]
    rc, stdout, stderr = _run(cmd, cwd=project_root, timeout=_GIT_SHOW_TIMEOUT)
    if rc != 0:
        cls = classify_git_error(rc, stderr, "git show")
        return None, f"git show failed for {ref} ({cls.label}, rc={cls.rc})"
    return stdout, None


def _get_file_commit_date(
    project_root: Path, branch: str, filename: str
) -> str:
    """Return the ISO 8601 UTC committer date for the most recent commit touching a file.

    Uses ``git log -1 --format=%aI origin/<branch> -- docs/handoff/<filename>``.
    %aI = strict ISO 8601 format of author date (UTC-aware).

    Falls back to empty string if git log fails or returns nothing.
    """
    ref = f"{_REMOTE}/{branch}"
    path = f"{_HANDOFF_TREE_PATH}/{filename}"
    cmd = ["git", "log", "-1", "--format=%aI", ref, "--", path]
    rc, stdout, _stderr = _run(cmd, cwd=project_root, timeout=_GIT_LIST_TIMEOUT)
    if rc != 0:
        return ""
    return stdout.strip()


def _make_legacy_track_id(branch: str, filename: str) -> str:
    """Construct a deterministic legacy track_id from branch + filename.

    Format: ``legacy:<branch>:<filename>`` per task spec §Impl notes.
    The branch separator is ":" which is invalid in git branch names,
    so there is no ambiguity.
    """
    return f"legacy:{branch}:{filename}"


# ── Public entry point ────────────────────────────────────────────────────────


def collect_handoff_multibranch(
    project_root: Path,
    remote: str = _REMOTE,
) -> CollectorResult:
    """Scan all remote branches for handoff docs and rebuild the track list.

    Args:
        project_root: Absolute path to the project root (passed by scan.py).
        remote:       git remote name (default: "origin"; injectable for tests).

    Returns a CollectorResult whose ``.data`` dict matches the
    ``tracks_multibranch`` schema documented in the module docstring.
    Never raises — all errors are accumulated via ``r.errors`` and the
    per-track ``errors`` list in the returned data.
    """
    r = CollectorResult()
    error_messages: list[str] = []

    # Resolve the scan cap (env > config > default 20; #71 v1.38.0). Resolved
    # once per run so the value is stable across the cap check + soft_error text.
    max_branches = resolve_max_branches_scanned(project_root)

    # PyYAML probe removed in v1.30.2 — parse_handoff_frontmatter now uses a
    # stdlib parser (fix for Forgejo aria-plugin #57 Finding 2). Frontmatter
    # parsing no longer requires any external dep.

    # ── Enumerate remote branches ─────────────────────────────────────────────
    branches, list_err = _list_origin_branches(project_root)
    if list_err is not None:
        r.soft_error("handoff_multibranch_branch_list_failed", list_err)
        r.data = {
            "exists": False,
            "tracks": [],
            "branches_scanned": 0,
            "legacy_count": 0,
            "collision": {"kind": "none", "groups": []},
            "errors": [list_err],
        }
        return r

    # Performance cap: only scan first `max_branches` branches (resolved above).
    # Branches are pre-sorted by committerdate desc (most-recent first) by
    # _list_origin_branches. Cap keeps active over stale.
    if len(branches) > max_branches:
        capped_msg = (
            f"Remote branch count ({len(branches)}) exceeds cap "
            f"({max_branches}); scanning only the first "
            f"{max_branches} branches (most-recent by committerdate)."
        )
        r.soft_error("handoff_multibranch_branch_cap", capped_msg)
        error_messages.append(capped_msg)
        log.warning("handoff_multibranch: %s", capped_msg)
        branches = branches[:max_branches]

    # ── Scan each branch ──────────────────────────────────────────────────────
    tracks: list[dict] = []
    legacy_count: int = 0
    branches_scanned: int = 0

    for branch in branches:
        # List handoff files on this branch
        filenames, ls_err = _list_handoff_files(project_root, branch)
        if ls_err is not None:
            msg = f"[{branch}] {ls_err}"
            error_messages.append(msg)
            r.soft_error("handoff_multibranch_ls_tree_failed", msg)
            # Continue scanning other branches
            branches_scanned += 1
            continue

        if not filenames:
            # Branch has no docs/handoff/ tree or only latest.md — silently skip.
            branches_scanned += 1
            continue

        branches_scanned += 1

        for filename in filenames:
            # Read file content via git show
            content, show_err = _read_file_content(project_root, branch, filename)

            if show_err is not None or content is None:
                # git show failed: mark as legacy + soft_error
                msg = f"[{branch}/{filename}] git show failed: {show_err or 'empty content'}"
                error_messages.append(msg)
                r.soft_error("handoff_multibranch_git_show_failed", msg)
                fallback_date = _get_file_commit_date(project_root, branch, filename)
                tracks.append(
                    {
                        "track_id": _make_legacy_track_id(branch, filename),
                        "owner_container": "unknown",
                        "phase": "unknown",
                        "status": "legacy",
                        "updated_at": fallback_date,
                        "branch": branch,
                        "filename": filename,
                        "legacy": True,
                    }
                )
                legacy_count += 1
                continue

            # Attempt frontmatter parse (stdlib parser since v1.30.2, no external dep)
            fm = parse_handoff_frontmatter(content)

            if fm is not None:
                # Well-formed frontmatter: emit as a first-class track row.
                tracks.append(
                    {
                        "track_id": fm["track-id"],
                        "owner_container": fm["owner-container"],
                        "phase": fm["phase"],
                        "status": fm["status"],
                        "updated_at": fm["updated-at"],
                        "branch": branch,
                        "filename": filename,
                        "legacy": False,
                    }
                )
                log.debug(
                    "handoff_multibranch: parsed track '%s' on branch '%s'",
                    fm["track-id"],
                    branch,
                )
            else:
                # No frontmatter or incomplete schema: legacy fallback per §2.3.4.
                # updated_at = git log committer date (superior to local mtime for
                # cross-branch files where mtime is not stable).
                fallback_date = _get_file_commit_date(project_root, branch, filename)
                tracks.append(
                    {
                        "track_id": _make_legacy_track_id(branch, filename),
                        "owner_container": "unknown",
                        "phase": "unknown",
                        "status": "legacy",
                        "updated_at": fallback_date,
                        "branch": branch,
                        "filename": filename,
                        "legacy": True,
                    }
                )
                legacy_count += 1
                log.debug(
                    "handoff_multibranch: legacy fallback for '%s' on branch '%s' "
                    "(no frontmatter or incomplete schema)",
                    filename,
                    branch,
                )

    # Collision summary (TASK-000, #133) — additive, advisory-only.
    # Built from the lossy track->ClaimRecord approximation via lib.collision;
    # MUST NOT be used as a gating input downstream (DEC-20260519-001).
    # Fail-soft: if lib import was unavailable, degrade to "none" rather than
    # raising (collision is an advisory surface, never load-bearing).
    if _COLLISION_AVAILABLE:
        try:
            # now=None -> classify/reconcile use datetime.now(timezone.utc).
            # Collision kind does not depend on freshness, so a fixed "now" is
            # unnecessary here (only stale-takeover labelling would, which the
            # summary does not surface).
            collision = _classify_collision_summary(tracks)
        except Exception as exc:  # noqa: BLE001 — advisory field never breaks scan
            collision = {"kind": "none", "groups": []}
            error_messages.append(f"collision classify failed (degraded to none): {exc}")
    else:
        collision = {"kind": "none", "groups": []}

    r.data = {
        "exists": len(tracks) > 0,
        "tracks": tracks,
        "branches_scanned": branches_scanned,
        "legacy_count": legacy_count,
        "collision": collision,
        "errors": error_messages,
    }
    return r

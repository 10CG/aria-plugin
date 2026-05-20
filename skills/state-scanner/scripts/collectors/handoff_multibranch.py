"""Phase 1 (multi-terminal-coordination) — cross-branch handoff track rebuilder.

Scans every ``origin/*`` branch for ``docs/handoff/*.md`` files, calls
``parse_handoff_frontmatter`` from the sibling ``handoff`` collector, and
reconstructs the multi-track dashboard track list consumed by TASK-005.

This collector is **read-only**: it uses ``git show`` / ``git ls-tree`` /
``git log`` to inspect remote refs without touching the working tree or index.
It MUST run AFTER ``collect_coordination_fetch`` (TASK-003) so that all remote
refs are present locally.

Return schema (top-level snapshot key: ``tracks_multibranch``):

    {
        "exists": bool,         # True when ≥1 track found across all branches
        "tracks": list[dict],   # One entry per (branch, file) pair — see below
        "branches_scanned": int,
        "legacy_count": int,    # Tracks that fell back to legacy (no frontmatter)
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
- If PyYAML is unavailable, a ``soft_error`` is emitted but scanning continues;
  all docs fall back to ``legacy`` in that mode (graceful degradation per §2.3.4).
- Performance: limited to ``refs/remotes/origin/`` (shallow ref list from
  TASK-003 fetch) — history is not walked.
- If the remote branch count exceeds MAX_BRANCHES_SCANNED (20) only the first 20
  branches (sorted lexicographically) are processed.  A soft_error notes the cap.

Spec: openspec/changes/multi-terminal-coordination/tasks.md §1.4
Task: TASK-004 (backend-architect)
Deps: TASK-003 (coordination_fetch.py) + TASK-009 (handoff.py parse_handoff_frontmatter)
"""

from __future__ import annotations

from pathlib import Path

# Note (Round 6 review): `git show` / `git ls-tree` invocations below intentionally
# omit the `--` ref/path separator because `for-each-ref` upstream already filters
# to legitimate `refs/remotes/origin/*` strings — there is no path that could be
# misinterpreted as a flag. Adding `--` would require a refactor for `git show`'s
# `<ref>:<path>` syntax (which does not accept `--` between ref and path).

from ._common import CollectorResult, _run, log
from .handoff import parse_handoff_frontmatter

# ── Constants ─────────────────────────────────────────────────────────────────

# Maximum number of remote branches to scan per run.
# Tasks.md §1.3 notes fetch is limited to refs/heads/* already; this is
# an additional guard against excessively large repos.
MAX_BRANCHES_SCANNED: int = 20

# File excluded from handoff doc detection (navigation pointer, not a doc).
# Must match POINTER_FILENAME in handoff.py for consistency.
_POINTER_FILENAME: str = "latest.md"

# The remote name that coordination_fetch.py fetches from (TASK-003).
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
    cmd = [
        "git",
        "for-each-ref",
        "--format=%(refname:short)",
        "refs/remotes/origin/",
    ]
    rc, stdout, stderr = _run(cmd, cwd=project_root, timeout=_GIT_LIST_TIMEOUT)
    if rc != 0:
        return [], f"git for-each-ref failed (rc={rc}): {stderr.strip()[:200]}"

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

    return sorted(branches), None


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
        return [], f"git ls-tree failed for {ref} (rc={rc}): {stderr.strip()[:200]}"

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
        return None, f"git show failed for {ref} (rc={rc}): {stderr.strip()[:200]}"
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

    # ── PyYAML availability probe ─────────────────────────────────────────────
    # If yaml is not importable, parse_handoff_frontmatter will return None for
    # every doc (YAML parse fails silently inside the helper).  We surface a
    # soft_error here for operator visibility, but continue scanning in full
    # legacy-degradation mode per §2.3.4.
    yaml_available = True
    try:
        import yaml as _yaml_probe  # noqa: F401
    except ImportError:
        yaml_available = False
        r.soft_error(
            "handoff_yaml_unavailable",
            "PyYAML is not installed — all handoff docs will be treated as "
            "legacy tracks. Run `pip install pyyaml` to enable frontmatter "
            "parsing.",
        )
        log.warning(
            "handoff_multibranch: PyYAML unavailable; running in full legacy-fallback mode"
        )

    # ── Enumerate remote branches ─────────────────────────────────────────────
    branches, list_err = _list_origin_branches(project_root)
    if list_err is not None:
        r.soft_error("handoff_multibranch_branch_list_failed", list_err)
        r.data = {
            "exists": False,
            "tracks": [],
            "branches_scanned": 0,
            "legacy_count": 0,
            "errors": [list_err],
        }
        return r

    # Performance cap: only scan first MAX_BRANCHES_SCANNED branches.
    # Branches are already sorted lexicographically by _list_origin_branches.
    if len(branches) > MAX_BRANCHES_SCANNED:
        capped_msg = (
            f"Remote branch count ({len(branches)}) exceeds cap "
            f"({MAX_BRANCHES_SCANNED}); scanning only the first "
            f"{MAX_BRANCHES_SCANNED} branches (lexicographic order)."
        )
        r.soft_error("handoff_multibranch_branch_cap", capped_msg)
        error_messages.append(capped_msg)
        log.warning("handoff_multibranch: %s", capped_msg)
        branches = branches[:MAX_BRANCHES_SCANNED]

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

            # Attempt frontmatter parse (returns None when yaml unavailable too)
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
                    "(no frontmatter or incomplete schema; yaml_available=%s)",
                    filename,
                    branch,
                    yaml_available,
                )

    r.data = {
        "exists": len(tracks) > 0,
        "tracks": tracks,
        "branches_scanned": branches_scanned,
        "legacy_count": legacy_count,
        "errors": error_messages,
    }
    return r

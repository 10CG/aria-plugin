"""Worktree 自动创建 + 子模块独立 checkout (Design A, 条件触发).

per multi-terminal-coordination tasks.md §3.2 + proposal §What/Design A
per concurrent_tracks.needs_worktree=True 触发

Design A spine: track-id ↔ branch ↔ worktree = 1:1:1

Path strategy:
    worktree_path = repo_root / "worktrees" / <track_id>
    (NOT .git/worktrees/ — kept separate to avoid confusion with git's own
     administrative dir.  Callers may pass an alternative worktree_root if the
     project convention differs.)

Submodule checkout:
    git worktree add places a *file* at <worktree>/.git that points back to
    the main repo's .git/worktrees/<name>/ administrative dir.  Running
    `git submodule update --init --recursive` inside the new worktree
    initialises independent submodule checkouts under that worktree — each
    submodule gets its own working tree while sharing the main object store.

Rule #7 compliance:
    All subprocess calls use capture_output=True.  stdout/stderr are never
    printed or logged at a level visible in the chat channel.  Errors are
    coerced to short, non-secret token strings before logging.

Spec task:  openspec/changes/multi-terminal-coordination/tasks.md §3.2
Task:       TASK-024 (P3 Round 2)
Deps:       TASK-023 (concurrent_tracks.py — ConcurrentTracksResult.needs_worktree)
            TASK-011 (track_id.py — derive_track_id)
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import NamedTuple, Optional

from .track_id import derive_track_id

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Worktrees live under repo_root/worktrees/<track_id>/
# This keeps them visible in `git worktree list` but out of .git/.
WORKTREE_ROOT_DIRNAME: str = "worktrees"

# Default branch prefix, consistent with existing Aria naming (feature-dev,
# branch-manager, etc.).
_BRANCH_PREFIX: str = "feature"


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


class WorktreeCreateResult(NamedTuple):
    """Outcome of a single create_worktree / remove_worktree call.

    Fields
    ------
    success : bool
        True when the intended operation completed without a fatal error.
        For create_worktree: worktree is usable (submodule failure is
        non-fatal — check submodules_initialized separately).
        For remove_worktree: worktree has been removed.
    track_id : str
        Normalised track_id (output of derive_track_id).
    worktree_path : str | None
        Absolute path to the worktree directory.  None on hard failure
        before the path was determined.
    branch_name : str | None
        Git branch associated with the worktree.  None on hard failure.
    submodules_initialized : bool
        True when git submodule update --init --recursive completed
        successfully inside the new worktree.  Always False for
        remove_worktree or when init_submodules=False.
    already_existed : bool
        create_worktree: True when the worktree already existed (idempotent).
        remove_worktree: always False (removal is not an existence check).
    error : str | None
        Short error token; None on full success.  Possible values:
          "not_a_git_repo"                  — repo_path is not a git repo
          "worktree_add_failed"             — git worktree add returned != 0
          "submodule_init_failed"           — submodule update failed (non-fatal
                                              for create; success=True still set)
          "worktree_exists_no_branch"       — path exists but no matching branch
          "worktree_not_found"              — remove: path does not exist
          "worktree_has_uncommitted_changes" — remove: dirty + force=False
          "worktree_remove_failed"          — git worktree remove returned != 0
    """

    success: bool
    track_id: str
    worktree_path: Optional[str]
    branch_name: Optional[str]
    submodules_initialized: bool
    already_existed: bool
    error: Optional[str]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _run(cmd: list[str], *, cwd: Path) -> tuple[int, str, str]:
    """Execute a git command and return (returncode, stdout, stderr).

    Rule #7: capture_output=True.  stdout/stderr are never printed.
    """
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError:
        return -1, "", "file_not_found"
    except OSError as exc:
        return -1, "", f"os_error:{type(exc).__name__}"


def _is_git_repo(repo: Path) -> bool:
    """Return True when repo_path is the root of a git repository."""
    rc, _out, _err = _run(
        ["git", "-C", str(repo), "rev-parse", "--git-dir"],
        cwd=repo,
    )
    return rc == 0


def _branch_exists(repo: Path, branch: str) -> bool:
    """Return True when the local branch exists."""
    rc, _out, _err = _run(
        ["git", "-C", str(repo), "show-ref", "--verify", "--quiet",
         f"refs/heads/{branch}"],
        cwd=repo,
    )
    return rc == 0


def _worktree_registered(repo: Path, worktree_path: Path) -> bool:
    """Return True when worktree_path appears in `git worktree list`."""
    entries = list_worktrees(repo)
    target = str(worktree_path.resolve())
    return any(e.get("path") == target for e in entries)


def _default_branch_name(track_id: str) -> str:
    return f"{_BRANCH_PREFIX}/{track_id}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_worktree(
    raw_track_id: str,
    branch_name: Optional[str] = None,
    *,
    repo_path: Optional[Path] = None,
    base_branch: str = "master",
    init_submodules: bool = True,
    worktree_root: Optional[Path] = None,
) -> WorktreeCreateResult:
    """Create an isolated git worktree for a track (Design A, conditional).

    Intended to be called when ConcurrentTracksResult.needs_worktree is True.
    The function is idempotent: calling it twice with the same track_id returns
    already_existed=True on the second call without modifying anything.

    Args:
        raw_track_id:
            Arbitrary raw identifier; normalised internally via derive_track_id.
        branch_name:
            Branch to associate with the worktree.  Defaults to
            "feature/<track_id>".
        repo_path:
            Absolute path to the repository root.  Defaults to Path.cwd().
        base_branch:
            Base branch for new-branch creation.  Default "master".
        init_submodules:
            Run `git submodule update --init --recursive` inside the new
            worktree.  Submodule failure is non-fatal: success=True is still
            returned with submodules_initialized=False and
            error="submodule_init_failed".
        worktree_root:
            Parent directory for all worktrees.  Defaults to
            repo_path / "worktrees".  Callers may pass repo_path / ".git" /
            "worktrees" for git-native placement, though this is not
            recommended (confusable with git's administrative dir).

    Returns:
        WorktreeCreateResult.  Never raises — all errors are captured.

    Mechanism:
        1. Normalise: track_id = derive_track_id(raw_track_id)
        2. worktree_path = worktree_root / track_id
        3. If worktree_path already registered in git worktree list → idempotent
           return (already_existed=True, success=True).
        4. Ensure worktree_path.parent exists (mkdir parents=True, exist_ok=True).
        5a. Branch does NOT exist:
              git worktree add -b <branch> <worktree_path> <base_branch>
        5b. Branch exists:
              git worktree add <worktree_path> <branch>
        6. If init_submodules:
              git -C <worktree_path> submodule update --init --recursive
    """
    repo: Path = repo_path if repo_path is not None else Path.cwd()

    # ── Step 0: validate git repo ─────────────────────────────────────────────
    if not _is_git_repo(repo):
        logger.warning(
            "worktree_manager.create_worktree: not a git repo at %s", repo
        )
        return WorktreeCreateResult(
            success=False,
            track_id=derive_track_id(raw_track_id),
            worktree_path=None,
            branch_name=None,
            submodules_initialized=False,
            already_existed=False,
            error="not_a_git_repo",
        )

    # ── Step 1: normalise track_id ────────────────────────────────────────────
    track_id = derive_track_id(raw_track_id)

    # ── Step 2: resolve paths ─────────────────────────────────────────────────
    wt_root = worktree_root if worktree_root is not None else repo / WORKTREE_ROOT_DIRNAME
    worktree_path = wt_root / track_id
    branch = branch_name if branch_name is not None else _default_branch_name(track_id)

    # ── Step 3: idempotency check ─────────────────────────────────────────────
    if _worktree_registered(repo, worktree_path):
        logger.debug(
            "worktree_manager.create_worktree: worktree already registered "
            "at %s (track_id=%s)",
            worktree_path,
            track_id,
        )
        return WorktreeCreateResult(
            success=True,
            track_id=track_id,
            worktree_path=str(worktree_path),
            branch_name=branch,
            submodules_initialized=False,  # not re-run on idempotent return
            already_existed=True,
            error=None,
        )

    # Edge case: path exists on disk but git does not know about it.
    # This is a dirty/stale state — report it rather than silently clobbering.
    if worktree_path.exists():
        logger.warning(
            "worktree_manager.create_worktree: worktree path exists on disk "
            "but is NOT registered in git worktree list — stale directory? "
            "(path=%s, track_id=%s)",
            worktree_path,
            track_id,
        )
        branch_ok = _branch_exists(repo, branch)
        if not branch_ok:
            return WorktreeCreateResult(
                success=False,
                track_id=track_id,
                worktree_path=str(worktree_path),
                branch_name=branch,
                submodules_initialized=False,
                already_existed=False,
                error="worktree_exists_no_branch",
            )
        # Branch exists but worktree not registered: fall through and let git
        # worktree add handle it (it will fail cleanly if path is non-empty).

    # ── Step 4: ensure parent directory exists ────────────────────────────────
    worktree_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Step 5: git worktree add ──────────────────────────────────────────────
    branch_exists = _branch_exists(repo, branch)

    if not branch_exists:
        # Create new branch from base_branch.
        cmd = [
            "git", "-C", str(repo),
            "worktree", "add",
            "-b", branch,
            str(worktree_path),
            base_branch,
        ]
        logger.debug(
            "worktree_manager.create_worktree: adding worktree with new "
            "branch=%s base=%s path=%s",
            branch,
            base_branch,
            worktree_path,
        )
    else:
        # Attach existing branch to a new worktree.
        cmd = [
            "git", "-C", str(repo),
            "worktree", "add",
            str(worktree_path),
            branch,
        ]
        logger.debug(
            "worktree_manager.create_worktree: adding worktree for existing "
            "branch=%s path=%s",
            branch,
            worktree_path,
        )

    rc_add, _out_add, err_add = _run(cmd, cwd=repo)
    if rc_add != 0:
        logger.warning(
            "worktree_manager.create_worktree: git worktree add failed "
            "(rc=%d, track_id=%s): %s",
            rc_add,
            track_id,
            err_add[:200],
        )
        return WorktreeCreateResult(
            success=False,
            track_id=track_id,
            worktree_path=str(worktree_path),
            branch_name=branch,
            submodules_initialized=False,
            already_existed=False,
            error="worktree_add_failed",
        )

    logger.info(
        "worktree_manager.create_worktree: worktree created at %s "
        "(branch=%s, track_id=%s)",
        worktree_path,
        branch,
        track_id,
    )

    # ── Step 6: submodule init (optional, non-fatal) ──────────────────────────
    submodules_ok = False
    submodule_error: Optional[str] = None

    if init_submodules:
        rc_sub, _out_sub, err_sub = _run(
            ["git", "-C", str(worktree_path),
             "submodule", "update", "--init", "--recursive"],
            cwd=worktree_path,
        )
        if rc_sub == 0:
            submodules_ok = True
            logger.debug(
                "worktree_manager.create_worktree: submodules initialized "
                "in worktree %s",
                worktree_path,
            )
        else:
            submodule_error = "submodule_init_failed"
            logger.warning(
                "worktree_manager.create_worktree: submodule update failed "
                "(rc=%d, worktree=%s): %s",
                rc_sub,
                worktree_path,
                err_sub[:200],
            )
            # Non-fatal: worktree was created successfully; caller can re-run
            # submodule init manually.

    return WorktreeCreateResult(
        success=True,
        track_id=track_id,
        worktree_path=str(worktree_path),
        branch_name=branch,
        submodules_initialized=submodules_ok,
        already_existed=False,
        error=submodule_error,
    )


def list_worktrees(
    repo_path: Optional[Path] = None,
) -> list:
    """List all worktrees registered with this repository.

    Parses `git worktree list --porcelain` output.  Each worktree record is
    a blank-line-delimited block of `key value` lines (and bare sentinel).

    Args:
        repo_path: Absolute path to repository root.  Defaults to Path.cwd().

    Returns:
        List of dicts, one per worktree:
            {
                "path":      str,   # absolute path
                "head":      str,   # commit SHA (empty string for unborn)
                "branch":    str,   # "refs/heads/<name>" or "(detached)" or ""
                "is_bare":   bool,
                "is_main":   bool,  # True for the primary worktree
            }
        Returns [] on any git error (never raises).
    """
    repo: Path = repo_path if repo_path is not None else Path.cwd()

    rc, out, err = _run(
        ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
        cwd=repo,
    )
    if rc != 0:
        logger.warning(
            "worktree_manager.list_worktrees: git worktree list failed "
            "(rc=%d): %s",
            rc,
            err[:200],
        )
        return []

    results: list = []
    # Records are separated by blank lines.
    for block in out.split("\n\n"):
        block = block.strip()
        if not block:
            continue

        entry: dict = {
            "path": "",
            "head": "",
            "branch": "",
            "is_bare": False,
            "is_main": False,
        }
        is_first = True
        for line in block.splitlines():
            line = line.strip()
            if not line:
                continue
            if line == "bare":
                entry["is_bare"] = True
                continue
            if " " in line:
                key, _, value = line.partition(" ")
                if key == "worktree":
                    entry["path"] = value
                    if is_first:
                        # The very first record in porcelain output is the
                        # main (primary) worktree.
                        entry["is_main"] = True
                elif key == "HEAD":
                    entry["head"] = value
                elif key == "branch":
                    entry["branch"] = value
                elif key == "detached":
                    entry["branch"] = "(detached)"
            is_first = False

        if entry["path"]:
            results.append(entry)

    # Correct is_main: only the first entry should be True.
    # (The flag is set per-line above; this ensures only index 0 is True.)
    for i, e in enumerate(results):
        e["is_main"] = i == 0

    logger.debug(
        "worktree_manager.list_worktrees: found %d worktrees", len(results)
    )
    return results


def remove_worktree(
    track_id: str,
    *,
    repo_path: Optional[Path] = None,
    force: bool = False,
    worktree_root: Optional[Path] = None,
) -> WorktreeCreateResult:
    """Remove the worktree associated with track_id.

    Companion to create_worktree; intended to be called as part of track
    lifecycle teardown (TASK-025 scope).

    Args:
        track_id:
            Normalised track_id (caller should have already called
            derive_track_id — this function does NOT re-normalise to avoid
            double-normalisation surprises at call sites that store the
            canonical id).
        repo_path:
            Absolute path to repository root.  Defaults to Path.cwd().
        force:
            Pass --force to git worktree remove.  Required when the worktree
            has uncommitted changes.  Default False (conservative).
        worktree_root:
            Parent directory for all worktrees.  Defaults to
            repo_path / "worktrees".

    Returns:
        WorktreeCreateResult with:
          success=True      — worktree removed (or was already absent)
          already_existed=False  — removal context; field semantics differ from
                                   create_worktree
          error tokens:
            "not_a_git_repo"                   — repo_path is not a git repo
            "worktree_not_found"               — path not registered in git
            "worktree_has_uncommitted_changes"  — dirty + force=False
            "worktree_remove_failed"            — git worktree remove != 0

    Never raises.
    """
    repo: Path = repo_path if repo_path is not None else Path.cwd()

    # ── Validate git repo ─────────────────────────────────────────────────────
    if not _is_git_repo(repo):
        logger.warning(
            "worktree_manager.remove_worktree: not a git repo at %s", repo
        )
        return WorktreeCreateResult(
            success=False,
            track_id=track_id,
            worktree_path=None,
            branch_name=None,
            submodules_initialized=False,
            already_existed=False,
            error="not_a_git_repo",
        )

    # ── Resolve path ──────────────────────────────────────────────────────────
    wt_root = worktree_root if worktree_root is not None else repo / WORKTREE_ROOT_DIRNAME
    worktree_path = wt_root / track_id

    # ── Check registration ────────────────────────────────────────────────────
    if not _worktree_registered(repo, worktree_path):
        logger.warning(
            "worktree_manager.remove_worktree: worktree not registered "
            "(track_id=%s, path=%s)",
            track_id,
            worktree_path,
        )
        return WorktreeCreateResult(
            success=False,
            track_id=track_id,
            worktree_path=str(worktree_path),
            branch_name=None,
            submodules_initialized=False,
            already_existed=False,
            error="worktree_not_found",
        )

    # ── git worktree remove ───────────────────────────────────────────────────
    cmd = ["git", "-C", str(repo), "worktree", "remove"]
    if force:
        cmd.append("--force")
    cmd.append(str(worktree_path))

    rc_rm, _out_rm, err_rm = _run(cmd, cwd=repo)

    if rc_rm == 0:
        logger.info(
            "worktree_manager.remove_worktree: removed worktree at %s "
            "(track_id=%s)",
            worktree_path,
            track_id,
        )
        return WorktreeCreateResult(
            success=True,
            track_id=track_id,
            worktree_path=str(worktree_path),
            branch_name=None,
            submodules_initialized=False,
            already_existed=False,
            error=None,
        )

    # Classify git error.
    err_lower = err_rm.lower()
    if "uncommitted changes" in err_lower or "contains modified or untracked" in err_lower:
        error_token = "worktree_has_uncommitted_changes"
    else:
        error_token = "worktree_remove_failed"

    logger.warning(
        "worktree_manager.remove_worktree: git worktree remove failed "
        "(rc=%d, track_id=%s, kind=%s): %s",
        rc_rm,
        track_id,
        error_token,
        err_rm[:200],
    )
    return WorktreeCreateResult(
        success=False,
        track_id=track_id,
        worktree_path=str(worktree_path),
        branch_name=None,
        submodules_initialized=False,
        already_existed=False,
        error=error_token,
    )


# ---------------------------------------------------------------------------
# Lifecycle / archive constants
# ---------------------------------------------------------------------------

# Archive sub-directory created under worktree_root when archive_mode=True.
WORKTREE_ARCHIVE_DIRNAME: str = "_archive"

# Terminal claim statuses that trigger cleanup.
_TERMINAL_STATUSES: frozenset = frozenset({"done", "abandoned"})


# ---------------------------------------------------------------------------
# Lifecycle result type
# ---------------------------------------------------------------------------


class LifecycleResult(NamedTuple):
    """Outcome of a cleanup_on_release / auto_cleanup_done_tracks entry.

    Fields
    ------
    success : bool
        True when the intended operation completed without a fatal error.
    track_id : str
        Normalised track_id.
    action : str
        One of:
          "archived"  — worktree moved to _archive/<YYYY-MM>/<track_id>/
          "removed"   — worktree destroyed via git worktree remove
          "kept"      — cleanup skipped because of uncommitted changes
                        (had_uncommitted=True, force=False)
          "skipped"   — worktree path was not registered; nothing to do
          "error"     — unexpected failure (check error field)
    worktree_path : str | None
        Original absolute path of the worktree; None when path was never
        determined.
    archived_path : str | None
        Destination path after archiving; non-None only when action="archived".
    had_uncommitted : bool
        True when has_uncommitted_changes() returned True for this worktree.
    error : str | None
        Short, non-secret error token; None on success.  Possible values:
          "worktree_has_uncommitted_changes"  — dirty + force=False (kept)
          "cannot_cleanup_main_worktree"      — refused to touch main worktree
          "worktree_move_failed"              — git worktree move returned != 0
          "worktree_remove_failed"            — git worktree remove returned != 0
          "not_a_git_repo"                    — repo path validation failed
    """

    success: bool
    track_id: str
    action: str
    worktree_path: Optional[str]
    archived_path: Optional[str]
    had_uncommitted: bool
    error: Optional[str]


# ---------------------------------------------------------------------------
# has_uncommitted_changes
# ---------------------------------------------------------------------------


def has_uncommitted_changes(worktree_path: Path) -> bool:
    """Return True when the worktree has any uncommitted changes.

    Uses ``git -C <worktree> status --porcelain --ignore-submodules=none``
    so that dirty submodule states are also detected.  Any non-empty output
    means the worktree is dirty.

    Rule #7: capture_output=True — stdout/stderr never printed.

    Args:
        worktree_path: Absolute path to the worktree directory.

    Returns:
        True  — worktree is dirty (or status command failed ambiguously).
        False — worktree is clean.
    """
    rc, out, err = _run(
        ["git", "-C", str(worktree_path), "status", "--porcelain",
         "--ignore-submodules=none"],
        cwd=worktree_path,
    )
    if rc != 0:
        # If git status itself fails (e.g. not-a-git-dir) treat as dirty to be
        # conservative — better to refuse cleanup than to silently discard work.
        logger.warning(
            "worktree_manager.has_uncommitted_changes: git status failed "
            "(rc=%d, path=%s): %s",
            rc,
            worktree_path,
            err[:200],
        )
        return True
    return bool(out.strip())


# ---------------------------------------------------------------------------
# cleanup_on_release
# ---------------------------------------------------------------------------


def cleanup_on_release(
    track_id: str,
    *,
    repo_path: Optional[Path] = None,
    worktree_root: Optional[Path] = None,
    archive_mode: bool = True,
    force: bool = False,
) -> "LifecycleResult":
    """Clean up the worktree after a track enters a terminal state.

    Called after release_claim(status='done'/'abandoned') to archive or
    destroy the worktree associated with track_id.

    Args:
        track_id:
            Normalised track_id (caller should call derive_track_id first).
        repo_path:
            Absolute path to the repository root.  Defaults to Path.cwd().
        worktree_root:
            Parent directory containing per-track worktrees.  Defaults to
            repo_path / "worktrees".
        archive_mode:
            True  — move worktree to _archive/<YYYY-MM>/<track_id>/ (default,
                     preserves history for potential recovery).
            False — destroy via ``git worktree remove`` (aggressive; suited for
                     CI or test cleanup where history retention is not needed).
        force:
            True  — proceed even when the worktree has uncommitted changes
                    (dangerous; must be explicitly set by caller after user
                     confirmation).
            False — abort with action="kept" and an error token (default).

    Returns:
        LifecycleResult.  Never raises — all errors are captured (fail-soft).

    Mechanism:
        1. Validate repo is a git repo.
        2. Determine worktree_path = worktree_root / track_id.
        3. If worktree_path not registered → action="skipped", success=True.
        4. If is_main worktree → action="error", error="cannot_cleanup_main_worktree".
        5. has_uncommitted_changes():
             True + force=False → action="kept",
                                   error="worktree_has_uncommitted_changes"
             True + force=True  → continue (user override)
             False              → continue
        6. archive_mode=True:
             a. archive_path = worktree_root/_archive/<YYYY-MM>/<track_id>
             b. archive_path.parent.mkdir(parents=True, exist_ok=True)
             c. git worktree move <worktree_path> <archive_path>
             d. Fallback on failure: action="error", error="worktree_move_failed"
           archive_mode=False:
             a. git worktree remove [--force] <worktree_path>
             b. On failure: action="error", error="worktree_remove_failed"
        7. Return LifecycleResult.
    """
    from datetime import datetime as _dt, timezone as _tz

    repo: Path = repo_path if repo_path is not None else Path.cwd()

    # ── Step 1: validate git repo ─────────────────────────────────────────────
    if not _is_git_repo(repo):
        logger.warning(
            "worktree_manager.cleanup_on_release: not a git repo at %s", repo
        )
        return LifecycleResult(
            success=False,
            track_id=track_id,
            action="error",
            worktree_path=None,
            archived_path=None,
            had_uncommitted=False,
            error="not_a_git_repo",
        )

    # ── Step 2: resolve paths ─────────────────────────────────────────────────
    wt_root = worktree_root if worktree_root is not None else repo / WORKTREE_ROOT_DIRNAME
    worktree_path = wt_root / track_id

    # ── Step 3: check registration ────────────────────────────────────────────
    if not _worktree_registered(repo, worktree_path):
        logger.debug(
            "worktree_manager.cleanup_on_release: worktree not registered, "
            "skipping (track_id=%s, path=%s)",
            track_id,
            worktree_path,
        )
        return LifecycleResult(
            success=True,
            track_id=track_id,
            action="skipped",
            worktree_path=str(worktree_path),
            archived_path=None,
            had_uncommitted=False,
            error=None,
        )

    # ── Step 4: refuse to touch main worktree ────────────────────────────────
    entries = list_worktrees(repo)
    for entry in entries:
        if entry.get("path") == str(worktree_path.resolve()) and entry.get("is_main"):
            logger.warning(
                "worktree_manager.cleanup_on_release: refusing to cleanup "
                "main worktree (track_id=%s, path=%s)",
                track_id,
                worktree_path,
            )
            return LifecycleResult(
                success=False,
                track_id=track_id,
                action="error",
                worktree_path=str(worktree_path),
                archived_path=None,
                had_uncommitted=False,
                error="cannot_cleanup_main_worktree",
            )

    # ── Step 5: uncommitted-changes check ────────────────────────────────────
    dirty = has_uncommitted_changes(worktree_path)
    if dirty and not force:
        logger.warning(
            "worktree_manager.cleanup_on_release: worktree has uncommitted "
            "changes — refusing cleanup (use force=True to override) "
            "(track_id=%s, path=%s)",
            track_id,
            worktree_path,
        )
        return LifecycleResult(
            success=False,
            track_id=track_id,
            action="kept",
            worktree_path=str(worktree_path),
            archived_path=None,
            had_uncommitted=True,
            error="worktree_has_uncommitted_changes",
        )

    # ── Step 6a: archive_mode=True — git worktree move ───────────────────────
    if archive_mode:
        month_tag = _dt.now(_tz.utc).strftime("%Y-%m")
        archive_path = wt_root / WORKTREE_ARCHIVE_DIRNAME / month_tag / track_id
        archive_path.parent.mkdir(parents=True, exist_ok=True)

        rc_mv, _out_mv, err_mv = _run(
            ["git", "-C", str(repo), "worktree", "move",
             str(worktree_path), str(archive_path)],
            cwd=repo,
        )
        if rc_mv == 0:
            logger.info(
                "worktree_manager.cleanup_on_release: archived worktree "
                "%s → %s (track_id=%s)",
                worktree_path,
                archive_path,
                track_id,
            )
            return LifecycleResult(
                success=True,
                track_id=track_id,
                action="archived",
                worktree_path=str(worktree_path),
                archived_path=str(archive_path),
                had_uncommitted=dirty,
                error=None,
            )

        # Fallback: git worktree move not supported or failed.
        logger.warning(
            "worktree_manager.cleanup_on_release: git worktree move failed "
            "(rc=%d, track_id=%s): %s — archive failed",
            rc_mv,
            track_id,
            err_mv[:200],
        )
        return LifecycleResult(
            success=False,
            track_id=track_id,
            action="error",
            worktree_path=str(worktree_path),
            archived_path=None,
            had_uncommitted=dirty,
            error="worktree_move_failed",
        )

    # ── Step 6b: archive_mode=False — git worktree remove ────────────────────
    cmd_rm = ["git", "-C", str(repo), "worktree", "remove"]
    if force:
        cmd_rm.append("--force")
    cmd_rm.append(str(worktree_path))

    rc_rm, _out_rm, err_rm = _run(cmd_rm, cwd=repo)
    if rc_rm == 0:
        logger.info(
            "worktree_manager.cleanup_on_release: removed worktree at %s "
            "(track_id=%s)",
            worktree_path,
            track_id,
        )
        return LifecycleResult(
            success=True,
            track_id=track_id,
            action="removed",
            worktree_path=str(worktree_path),
            archived_path=None,
            had_uncommitted=dirty,
            error=None,
        )

    logger.warning(
        "worktree_manager.cleanup_on_release: git worktree remove failed "
        "(rc=%d, track_id=%s): %s",
        rc_rm,
        track_id,
        err_rm[:200],
    )
    return LifecycleResult(
        success=False,
        track_id=track_id,
        action="error",
        worktree_path=str(worktree_path),
        archived_path=None,
        had_uncommitted=dirty,
        error="worktree_remove_failed",
    )


# ---------------------------------------------------------------------------
# auto_cleanup_done_tracks
# ---------------------------------------------------------------------------


def auto_cleanup_done_tracks(
    repo_path: Optional[Path] = None,
    *,
    worktree_root: Optional[Path] = None,
    archive_mode: bool = True,
    dry_run: bool = False,
) -> list:
    """Scan all registered worktrees; clean up those whose claim is terminal.

    Intended for scheduled cleanup jobs (e.g. Phase D.3 hook) or CI teardown.
    For each non-main worktree whose path basename matches a track_id with a
    ``status='done'`` or ``status='abandoned'`` claim, call
    ``cleanup_on_release()``.

    Args:
        repo_path:
            Absolute path to the repository root.  Defaults to Path.cwd().
        worktree_root:
            Parent directory containing per-track worktrees.  Defaults to
            repo_path / "worktrees".  Used to derive track_id from each
            worktree path basename.
        archive_mode:
            Forwarded to cleanup_on_release.  Default True.
        dry_run:
            True — compute results without executing any cleanup.  Each entry
            has action="skipped" (would-clean) or action="skipped" (already
            skipped).  Callers may inspect had_uncommitted / error fields on
            would-clean entries by pre-calling has_uncommitted_changes.

    Returns:
        list[LifecycleResult] — one entry per non-main worktree examined.
        Empty list when list_worktrees() returns no non-main entries or on
        hard failure.  Never raises.

    Mechanism:
        1. list_worktrees(repo_path) → all worktrees.
        2. Skip main worktree (is_main=True).
        3. For each worktree, derive track_id = Path(entry["path"]).name.
        4. Restrict to worktrees under worktree_root (skip entries outside it).
        5. read_claims(repo_path) → all claims.
        6. Locate the most-recent claim for this track_id.
        7. claim.status in {"done", "abandoned"} → cleanup (or dry_run skip).
           Otherwise → LifecycleResult(action="skipped", success=True).
        8. Return collected results.
    """
    from .coordination_ref import read_claims as _read_claims

    repo: Path = repo_path if repo_path is not None else Path.cwd()
    wt_root = worktree_root if worktree_root is not None else repo / WORKTREE_ROOT_DIRNAME

    # ── Step 1: list worktrees ────────────────────────────────────────────────
    all_worktrees = list_worktrees(repo)
    if not all_worktrees:
        logger.debug("worktree_manager.auto_cleanup_done_tracks: no worktrees found")
        return []

    # ── Step 5: read all claims once ─────────────────────────────────────────
    # Fail-soft: if read_claims errors, we cannot determine terminal status so
    # we conservatively skip all cleanup.
    try:
        claims_result = _read_claims(repo)
    except Exception as exc:
        logger.warning(
            "worktree_manager.auto_cleanup_done_tracks: read_claims() raised "
            "%s — skipping all cleanup",
            type(exc).__name__,
        )
        return []

    # Build a dict: track_id → most-recent claim record.
    # "Most recent" = the record with the latest heartbeat_at string.
    # ClaimRecord is a NamedTuple; we compare heartbeat_at as ISO strings
    # (lexicographic order is identical to chronological for UTC ISO 8601).
    claim_map: dict = {}
    for rec in (claims_result.claims if claims_result.ref_exists else []):
        tid = getattr(rec, "track_id", None)
        if tid is None:
            continue
        existing = claim_map.get(tid)
        if existing is None:
            claim_map[tid] = rec
        else:
            # Compare heartbeat_at lexicographically.
            if getattr(rec, "heartbeat_at", "") > getattr(existing, "heartbeat_at", ""):
                claim_map[tid] = rec

    results: list = []

    # ── Steps 2-8: process each non-main worktree ─────────────────────────────
    for entry in all_worktrees:
        if entry.get("is_main"):
            continue  # never touch the main worktree

        wt_path = Path(entry.get("path", ""))
        if not wt_path.is_relative_to(wt_root):
            # Worktree is outside our managed root — skip silently.
            logger.debug(
                "worktree_manager.auto_cleanup_done_tracks: worktree %s is "
                "outside worktree_root %s — skipping",
                wt_path,
                wt_root,
            )
            continue

        track_id = wt_path.name  # basename = track_id by Design A convention

        claim = claim_map.get(track_id)
        if claim is None:
            # No claim record found — conservative: do not touch.
            logger.debug(
                "worktree_manager.auto_cleanup_done_tracks: no claim for "
                "track_id=%s — skipping",
                track_id,
            )
            results.append(
                LifecycleResult(
                    success=True,
                    track_id=track_id,
                    action="skipped",
                    worktree_path=str(wt_path),
                    archived_path=None,
                    had_uncommitted=False,
                    error=None,
                )
            )
            continue

        claim_status = getattr(claim, "status", "")
        if claim_status not in _TERMINAL_STATUSES:
            # Active / yielded claim — do not touch.
            logger.debug(
                "worktree_manager.auto_cleanup_done_tracks: claim status=%s "
                "is not terminal for track_id=%s — skipping",
                claim_status,
                track_id,
            )
            results.append(
                LifecycleResult(
                    success=True,
                    track_id=track_id,
                    action="skipped",
                    worktree_path=str(wt_path),
                    archived_path=None,
                    had_uncommitted=False,
                    error=None,
                )
            )
            continue

        # Terminal status — eligible for cleanup.
        if dry_run:
            logger.debug(
                "worktree_manager.auto_cleanup_done_tracks: dry_run=True, "
                "would cleanup track_id=%s (status=%s)",
                track_id,
                claim_status,
            )
            results.append(
                LifecycleResult(
                    success=True,
                    track_id=track_id,
                    action="skipped",
                    worktree_path=str(wt_path),
                    archived_path=None,
                    had_uncommitted=has_uncommitted_changes(wt_path),
                    error=None,
                )
            )
            continue

        logger.info(
            "worktree_manager.auto_cleanup_done_tracks: cleaning up "
            "track_id=%s (claim status=%s)",
            track_id,
            claim_status,
        )
        result = cleanup_on_release(
            track_id,
            repo_path=repo,
            worktree_root=wt_root,
            archive_mode=archive_mode,
            force=False,  # always conservative in batch mode
        )
        results.append(result)

    logger.debug(
        "worktree_manager.auto_cleanup_done_tracks: processed %d worktrees, "
        "%d results",
        len(all_worktrees) - 1,  # subtract main
        len(results),
    )
    return results

"""Orphan ref ops for Layer L coordination (multi-terminal-coordination).

This module provides idempotent bootstrap of ``refs/aria/coordination`` —
the git orphan ref that stores claim files for multi-terminal coordination.

The ref is entirely separate from the project's commit history (no common
ancestor with master/feature branches).  It is created via low-level git
plumbing commands so no worktree state is disturbed.

Bootstrap procedure:
  1. Check local ref  → already exists: return early (no write)
  2. Check remote ref → exists: fetch it locally, return early (no write)
  3. Neither exists   → create orphan commit using the well-known empty-tree
     SHA and ``git update-ref``
  4. Optionally push the newly created ref to the remote

Rule #7 compliance:
  All subprocess calls use ``capture_output=True``.  stdout/stderr are never
  printed; errors are coerced to short, non-secret strings.

Spec: openspec/changes/multi-terminal-coordination/tasks.md §2.3, §2.9 (d)
Task: TASK-012 (P2 Round 2)
Deps: TASK-010 (claim_schema.py — sibling module in this lib package)
"""

from __future__ import annotations

import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REF_NAME: str = "refs/aria/coordination"
REMOTE_REF: str = "refs/remotes/origin/aria/coordination"

# The git well-known empty-tree SHA — constant across ALL git repositories.
# Computed by: git hash-object -t tree /dev/null
# Verified stable since git 1.6.x; safe to use as a constant.
EMPTY_TREE_SHA: str = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

BOOTSTRAP_COMMIT_MSG: str = "Aria coordination ref bootstrap"


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


class BootstrapResult(NamedTuple):
    """Outcome of a single ``bootstrap()`` call.

    Fields
    ------
    created : bool
        True only when *this* call created the ref (i.e. it did not exist
        locally or remotely beforehand).
    ref_existed_local : bool
        True when the local ref was already present before this call.
    ref_existed_remote : bool
        True when the remote ref was already present before this call
        (and was subsequently fetched).
    commit_sha : str
        The SHA the ref currently points to — either the newly created orphan
        commit or the pre-existing commit.  Empty string on hard failure.
    pushed : bool
        True when this call successfully pushed the ref to the remote.
        Always False when ``created=False`` (ref was pre-existing).
    error : str | None
        Short error token when any git command failed; ``None`` on full
        success.  Possible values: ``"not_a_git_repo"``,
        ``"repo_path_missing"``, ``"commit_tree_failed"``,
        ``"update_ref_failed"``, ``"fetch_failed"``, ``"push_auth_failed"``,
        ``"push_failed"``.
    """

    created: bool
    ref_existed_local: bool
    ref_existed_remote: bool
    commit_sha: str
    pushed: bool
    error: str | None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _run(
    cmd: list[str],
    *,
    cwd: Path,
    input: str | None = None,
) -> tuple[int, str, str]:
    """Run a git command and return (returncode, stdout, stderr).

    Rule #7: capture_output=True; stdout/stderr are never printed.
    The caller is responsible for inspecting the returncode.
    """
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            input=input,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError:
        # Either git is not on PATH, or cwd does not exist.
        return -1, "", "file_not_found"
    except OSError as exc:
        return -1, "", f"os_error:{type(exc).__name__}"


def _ref_exists_local(repo: Path, ref: str) -> bool | None:
    """Return True/False whether a local ref exists.  None on git error."""
    rc, _out, _err = _run(
        ["git", "-C", str(repo), "show-ref", "--verify", "--quiet", ref],
        cwd=repo,
    )
    if rc == 0:
        return True
    if rc == 1:
        # show-ref --verify exits 1 when ref does not exist — expected path
        return False
    # rc < 0 → FileNotFoundError (not a repo / git missing)
    return None


def _resolve_ref(repo: Path, ref: str) -> str:
    """Return the commit SHA that ``ref`` points to, or empty string."""
    rc, out, _err = _run(
        ["git", "-C", str(repo), "rev-parse", ref],
        cwd=repo,
    )
    if rc == 0 and out:
        return out
    return ""


def _bootstrap_commit_msg_with_date() -> str:
    date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    return f"{BOOTSTRAP_COMMIT_MSG} ({date_str})"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def bootstrap(
    repo_path: Path | None = None,
    *,
    remote: str = "origin",
    push: bool = True,
) -> BootstrapResult:
    """Idempotently initialise ``refs/aria/coordination`` as an orphan ref.

    The function is safe to call multiple times; subsequent calls after the
    first successful bootstrap are cheap no-ops (a single ``show-ref``
    check).

    Steps
    -----
    1. Validate ``repo_path`` resolves to a real git repository by checking
       whether ``git show-ref --verify`` can run without a "not a git repo"
       error.
    2. Check local ref ``refs/aria/coordination``.
       Exists  →  return ``BootstrapResult(created=False, ref_existed_local=True,
       commit_sha=<current SHA>, ...)`` immediately (idempotent early exit).
    3. Check remote ref ``refs/remotes/origin/aria/coordination``.
       Exists  →  fetch it into the local namespace via
       ``git fetch <remote> refs/aria/coordination:refs/aria/coordination``
       and return ``BootstrapResult(created=False, ref_existed_remote=True,
       commit_sha=<fetched SHA>, ...)``.
    4. Neither exists  →  create a new orphan commit:
         a. ``git commit-tree <EMPTY_TREE_SHA> -m "<msg>"``  (no -p parent)
         b. ``git update-ref refs/aria/coordination <commit_sha>``
    5. If ``push=True``:
         ``git push <remote> refs/aria/coordination``
         Success  →  ``pushed=True``
         Auth error (401/403)  →  ``pushed=False, error="push_auth_failed"``
         Other failure  →  ``pushed=False, error="push_failed"``
         The locally created ref is retained even on push failure.

    Parameters
    ----------
    repo_path : Path | None
        Absolute path to the repository root.  Defaults to ``Path.cwd()``.
        Pass an explicit value in tests to keep operations hermetic.
    remote : str
        Name of the git remote to use.  Default ``"origin"``.
    push : bool
        Whether to push the newly created ref to the remote.
        Set ``False`` in unit tests to avoid any network I/O.

    Returns
    -------
    BootstrapResult
        See ``BootstrapResult`` docstring for field semantics.
    """
    repo: Path = repo_path if repo_path is not None else Path.cwd()

    # ── Step 0: repo path must exist ─────────────────────────────────────────
    if not repo.exists():
        logger.warning(
            "coordination_ref.bootstrap: repo_path does not exist: %s", repo
        )
        return BootstrapResult(
            created=False,
            ref_existed_local=False,
            ref_existed_remote=False,
            commit_sha="",
            pushed=False,
            error="repo_path_missing",
        )

    # ── Step 1: confirm repo is a valid git repo ──────────────────────────────
    # Use a lightweight rev-parse check.  rc=-1 means FileNotFoundError (no git
    # binary or not a directory); rc=128 means "not a git repository".
    rc_check, _out, err_check = _run(
        ["git", "-C", str(repo), "rev-parse", "--git-dir"],
        cwd=repo,
    )
    if rc_check != 0:
        logger.warning(
            "coordination_ref.bootstrap: not a git repository (rc=%d): %s",
            rc_check,
            repo,
        )
        return BootstrapResult(
            created=False,
            ref_existed_local=False,
            ref_existed_remote=False,
            commit_sha="",
            pushed=False,
            error="not_a_git_repo",
        )

    # ── Step 2: check local ref ───────────────────────────────────────────────
    local_exists = _ref_exists_local(repo, REF_NAME)

    if local_exists is None:
        # show-ref returned an unexpected rc — treat as "not a git repo"
        return BootstrapResult(
            created=False,
            ref_existed_local=False,
            ref_existed_remote=False,
            commit_sha="",
            pushed=False,
            error="not_a_git_repo",
        )

    if local_exists:
        sha = _resolve_ref(repo, REF_NAME)
        logger.debug(
            "coordination_ref.bootstrap: local ref already exists at %s", sha
        )
        return BootstrapResult(
            created=False,
            ref_existed_local=True,
            ref_existed_remote=False,
            commit_sha=sha,
            pushed=False,
            error=None,
        )

    # ── Step 3: check remote ref ──────────────────────────────────────────────
    # ``refs/remotes/<remote>/aria/coordination`` is populated only if a prior
    # fetch has run.  We check the local remote-tracking ref to avoid a
    # network round-trip just for the existence check.
    remote_tracking_ref = f"refs/remotes/{remote}/aria/coordination"
    remote_exists = _ref_exists_local(repo, remote_tracking_ref)
    # remote_exists=None means git error; treat conservatively as False
    if remote_exists is None:
        remote_exists = False

    if remote_exists:
        # Fetch the remote ref into the local namespace so callers can read it.
        fetch_refspec = f"{REF_NAME}:{REF_NAME}"
        rc_fetch, _out, err_fetch = _run(
            ["git", "-C", str(repo), "fetch", remote, fetch_refspec],
            cwd=repo,
        )
        if rc_fetch != 0:
            logger.warning(
                "coordination_ref.bootstrap: fetch of remote ref failed "
                "(rc=%d): %s",
                rc_fetch,
                err_fetch,
            )
            return BootstrapResult(
                created=False,
                ref_existed_local=False,
                ref_existed_remote=True,
                commit_sha="",
                pushed=False,
                error="fetch_failed",
            )
        sha = _resolve_ref(repo, REF_NAME)
        logger.debug(
            "coordination_ref.bootstrap: fetched remote ref → local at %s", sha
        )
        return BootstrapResult(
            created=False,
            ref_existed_local=False,
            ref_existed_remote=True,
            commit_sha=sha,
            pushed=False,
            error=None,
        )

    # ── Step 4: create orphan commit ─────────────────────────────────────────
    # Use the git well-known empty-tree SHA directly (constant, no subprocess).
    # ``git commit-tree`` creates a commit object with no parent, giving us a
    # true orphan (history-isolated) ref.
    msg = _bootstrap_commit_msg_with_date()
    rc_ct, sha_raw, err_ct = _run(
        ["git", "-C", str(repo), "commit-tree", EMPTY_TREE_SHA, "-m", msg],
        cwd=repo,
        input="",
    )
    if rc_ct != 0 or not sha_raw:
        logger.warning(
            "coordination_ref.bootstrap: commit-tree failed (rc=%d): %s",
            rc_ct,
            err_ct,
        )
        return BootstrapResult(
            created=False,
            ref_existed_local=False,
            ref_existed_remote=False,
            commit_sha="",
            pushed=False,
            error="commit_tree_failed",
        )

    commit_sha = sha_raw

    # Point the ref at the new orphan commit.
    rc_ur, _out, err_ur = _run(
        ["git", "-C", str(repo), "update-ref", REF_NAME, commit_sha],
        cwd=repo,
    )
    if rc_ur != 0:
        logger.warning(
            "coordination_ref.bootstrap: update-ref failed (rc=%d): %s",
            rc_ur,
            err_ur,
        )
        return BootstrapResult(
            created=False,
            ref_existed_local=False,
            ref_existed_remote=False,
            commit_sha="",
            pushed=False,
            error="update_ref_failed",
        )

    logger.info(
        "coordination_ref.bootstrap: created orphan ref %s → %s",
        REF_NAME,
        commit_sha,
    )

    # ── Step 5: push (optional) ───────────────────────────────────────────────
    if not push:
        return BootstrapResult(
            created=True,
            ref_existed_local=False,
            ref_existed_remote=False,
            commit_sha=commit_sha,
            pushed=False,
            error=None,
        )

    rc_push, _out, err_push = _run(
        ["git", "-C", str(repo), "push", remote, REF_NAME],
        cwd=repo,
    )

    if rc_push == 0:
        logger.info(
            "coordination_ref.bootstrap: pushed %s to %s", REF_NAME, remote
        )
        return BootstrapResult(
            created=True,
            ref_existed_local=False,
            ref_existed_remote=False,
            commit_sha=commit_sha,
            pushed=True,
            error=None,
        )

    # Classify push failure.
    err_push_lower = err_push.lower()
    if (
        "403" in err_push
        or "401" in err_push
        or "authentication failed" in err_push_lower
        or "permission denied" in err_push_lower
    ):
        push_error = "push_auth_failed"
    else:
        push_error = "push_failed"

    logger.warning(
        "coordination_ref.bootstrap: push failed (rc=%d, kind=%s): %s",
        rc_push,
        push_error,
        err_push,
    )
    # Local ref is already created; do NOT roll it back.
    return BootstrapResult(
        created=True,
        ref_existed_local=False,
        ref_existed_remote=False,
        commit_sha=commit_sha,
        pushed=False,
        error=push_error,
    )

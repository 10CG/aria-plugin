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

CRUD operations (TASK-013):
  read_claims()  — list all claim files from the orphan ref tree
  write_claim()  — write current session's claim (file-per-writer partitioning)
  push_coordination_ref()  — push local ref to remote
  fetch_coordination_ref() — fetch remote ref to local

File-per-writer invariant:
  Each session writes only ``claims/<container>/<session>.yaml``.  Two
  containers can never write the same file path, so push is always a
  fast-forward add or in-place replace of exactly one file.  The write_claim
  API enforces this by deriving the path exclusively from record.container
  and record.session; callers cannot supply an arbitrary path.

Rule #7 compliance:
  All subprocess calls use ``capture_output=True``.  stdout/stderr are never
  printed; errors are coerced to short, non-secret strings.

Spec: openspec/changes/multi-terminal-coordination/tasks.md §2.3, §2.9 (d)
Task: TASK-012 (P2 Round 2) + TASK-013 (P2 Round 3)
Deps: TASK-010 (claim_schema.py — sibling module in this lib package)
      TASK-011 (identity.py — ClaimRecord.container / .session values)
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple, Optional

# yaml is an optional dependency; absence degrades read_claims / write_claim
# gracefully rather than hard-crashing at import time.
try:
    import yaml as _yaml  # type: ignore[import-untyped]

    _YAML_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover
    _yaml = None  # type: ignore[assignment]
    _YAML_AVAILABLE = False

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REF_NAME: str = "refs/aria/coordination"
REMOTE_REF: str = "refs/remotes/origin/aria/coordination"

# Path prefix inside the coordination ref tree for active/yielded claims.
_CLAIMS_PREFIX: str = "claims"

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


class ReadClaimsResult(NamedTuple):
    """Result of :func:`read_claims`.

    Fields
    ------
    claims : list[ClaimRecord]
        All parsed claim records found under the coordination ref tree.
        Records with ``status="unknown"`` (unrecognised schema version) are
        included — callers / reconcile decide how to handle them.
    errors : list[str]
        Human-readable problem descriptions for any files that could not be
        parsed.  Non-empty does not mean the overall call failed; it means
        some files were skipped.
    ref_exists : bool
        False when the local ref does not exist at all (brand-new repo or
        bootstrap not yet run).  ``claims`` will be empty in that case.
    """

    claims: list  # list[ClaimRecord] — avoids circular import at module level
    errors: list  # list[str]
    ref_exists: bool


class WriteClaimResult(NamedTuple):
    """Result of :func:`write_claim`.

    Fields
    ------
    success : bool
    commit_sha : str
        The new commit SHA on the coordination ref; empty string on failure.
    blob_sha : str
        The blob SHA of the written YAML content; empty string on failure.
    claim_path : str
        The path inside the ref tree (e.g. ``claims/devbox-A/s-7f3a@0931.yaml``).
        Empty string on failure.
    error : str | None
        Short error token; ``None`` on full success.  Possible values:
        ``"yaml_unavailable"``, ``"ref_not_exists"``, ``"bootstrap_failed"``,
        ``"hash_object_failed"``, ``"mktree_failed"``, ``"commit_tree_failed"``,
        ``"update_ref_failed"``, ``"missing_container_or_session"``.
    """

    success: bool
    commit_sha: str
    blob_sha: str
    claim_path: str
    error: Optional[str]


class PushResult(NamedTuple):
    """Result of :func:`push_coordination_ref`.

    Fields
    ------
    success : bool
    error_kind : str | None
        Short error category: ``"auth_failed"``, ``"non_ff"``, ``"network"``,
        ``"push_failed"``.  ``None`` on success.
    error_msg : str | None
        Short non-secret context; ``None`` on success.
    """

    success: bool
    error_kind: Optional[str]
    error_msg: Optional[str]


class FetchResult(NamedTuple):
    """Result of :func:`fetch_coordination_ref`.

    Fields
    ------
    success : bool
    error_kind : str | None
        Short error category: ``"auth_failed"``, ``"network"``,
        ``"fetch_failed"``.  ``None`` on success.
    error_msg : str | None
        Short non-secret context; ``None`` on success.
    ref_updated : bool
        True when the local ref was actually advanced (remote had newer
        commits).  False when already up-to-date or on failure.
    """

    success: bool
    error_kind: Optional[str]
    error_msg: Optional[str]
    ref_updated: bool


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _run(
    cmd: list[str],
    *,
    cwd: Path,
    input: str | None = None,
    extra_env: dict | None = None,
) -> tuple[int, str, str]:
    """Run a git command and return (returncode, stdout, stderr).

    Rule #7: capture_output=True; stdout/stderr are never printed.
    The caller is responsible for inspecting the returncode.

    Parameters
    ----------
    extra_env:
        Optional dict of extra environment variables merged on top of the
        current process environment.  Used by write_claim to pass
        ``GIT_INDEX_FILE`` without touching the global environment.
    """
    import os as _os_run

    env = None
    if extra_env:
        env = {**_os_run.environ, **extra_env}

    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            input=input,
            env=env,
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


# ---------------------------------------------------------------------------
# TASK-013 — Claim CRUD + push/fetch
# ---------------------------------------------------------------------------


def read_claims(
    repo_path: Path | None = None,
    *,
    include_archive: bool = False,
) -> ReadClaimsResult:
    """List all claim records stored in the coordination ref tree.

    Mechanism
    ---------
    1. ``git ls-tree -r refs/aria/coordination`` — enumerate all blob paths.
    2. For each path under ``claims/`` (and optionally ``archive/``):
       ``git show refs/aria/coordination:<path>`` → raw YAML bytes.
    3. ``yaml.safe_load`` → dict → ``claim_schema.parse_claim`` → ClaimRecord.
    4. yaml.YAMLError is caught per file; corrupt files are added to ``errors``
       and skipped (soft-error, not a fatal failure).
    5. parse_claim returning None is also soft-error; unknown-schema records
       (status="unknown") are included so callers can observe them.

    Parameters
    ----------
    repo_path:
        Absolute path to the repository root.  Defaults to ``Path.cwd()``.
        Pass a ``tmp_path`` in tests to keep operations hermetic.
    include_archive:
        When True, also parse files under ``archive/<YYYY-MM>/``.

    Returns
    -------
    ReadClaimsResult
        ``ref_exists=False`` and empty lists when the local ref does not
        exist.  Non-empty ``errors`` list does not mean a hard failure.
    """
    # Lazy import to avoid hard dependency at module load time.
    from .claim_schema import parse_claim  # type: ignore[import]

    repo: Path = repo_path if repo_path is not None else Path.cwd()

    if not _YAML_AVAILABLE:
        # yaml missing — cannot parse any claim files.
        return ReadClaimsResult(claims=[], errors=["yaml_unavailable"], ref_exists=False)

    # Check ref existence first (cheap).
    local_exists = _ref_exists_local(repo, REF_NAME)
    if not local_exists:
        return ReadClaimsResult(claims=[], errors=[], ref_exists=False)

    # Enumerate all blobs in the ref tree.
    rc_ls, ls_out, ls_err = _run(
        ["git", "-C", str(repo), "ls-tree", "-r", "--full-tree", REF_NAME],
        cwd=repo,
    )
    if rc_ls != 0:
        return ReadClaimsResult(
            claims=[],
            errors=[f"ls_tree_failed:{ls_err[:120]}"],
            ref_exists=True,
        )

    claims: list = []
    errors: list = []

    for line in ls_out.splitlines():
        # ls-tree output: "<mode> blob <sha>\t<path>"
        line = line.strip()
        if not line:
            continue
        try:
            meta, path = line.split("\t", 1)
        except ValueError:
            errors.append(f"ls_tree_parse_error:{line[:80]}")
            continue

        # Filter by path prefix.
        if path.startswith(_CLAIMS_PREFIX + "/"):
            pass  # always include active/yielded claims
        elif include_archive and path.startswith("archive/"):
            pass
        else:
            continue

        # Read blob content.
        rc_show, content, show_err = _run(
            ["git", "-C", str(repo), "show", f"{REF_NAME}:{path}"],
            cwd=repo,
        )
        if rc_show != 0:
            errors.append(f"show_failed:{path}:{show_err[:80]}")
            logger.warning(
                "coordination_ref.read_claims: git show failed for %s: %s",
                path,
                show_err,
            )
            continue

        # Parse YAML.
        try:
            raw = _yaml.safe_load(content)
        except Exception as exc:  # yaml.YAMLError or anything unexpected
            errors.append(f"yaml_parse_error:{path}:{type(exc).__name__}")
            logger.warning(
                "coordination_ref.read_claims: YAML parse error for %s: %s",
                path,
                type(exc).__name__,
            )
            continue

        if not isinstance(raw, dict):
            errors.append(f"yaml_not_mapping:{path}")
            continue

        record = parse_claim(raw)
        if record is None:
            errors.append(f"claim_schema_invalid:{path}")
            continue

        claims.append(record)

    return ReadClaimsResult(claims=claims, errors=errors, ref_exists=True)


def write_claim(
    record,  # ClaimRecord — untyped to avoid circular import at definition time
    repo_path: Path | None = None,
    *,
    auto_bootstrap: bool = True,
) -> WriteClaimResult:
    """Write a single claim file to the coordination ref tree.

    File-per-writer invariant
    -------------------------
    The claim path is derived exclusively from ``record.container`` and
    ``record.session``:  ``claims/<record.container>/<record.session>.yaml``.
    Callers cannot supply an arbitrary path; two different sessions/containers
    will always write to different files, guaranteeing push is non-conflicting.

    Mechanism (temporary-worktree approach — simpler than raw mktree plumbing)
    ----------
    1. If the ref does not exist + ``auto_bootstrap=True``, call bootstrap().
    2. ``yaml.safe_dump(serialize_claim(record))`` → UTF-8 bytes.
    3. ``git hash-object -w --stdin`` → blob_sha.
    4. Create a TemporaryDirectory as a scratch worktree:
       a. Write claim YAML to ``<tmp>/claims/<container>/<session>.yaml``.
       b. ``git --git-dir=<repo>/.git --work-tree=<tmp> add <claim_path>``
       c. ``git --git-dir=<repo>/.git --work-tree=<tmp> write-tree`` → tree_sha.
    5. ``git commit-tree <tree_sha> -p <current_ref_sha> -m "claim: ..."``
       → new_commit_sha.
    6. ``git update-ref refs/aria/coordination <new_commit_sha>``.
    7. Clean up TemporaryDirectory automatically (context manager).

    Note: step 4 uses the repo's git-dir but a fresh, isolated work-tree so
    it never touches any existing worktrees or staged index.

    Parameters
    ----------
    record:
        A ``ClaimRecord`` with non-empty ``container`` and ``session`` fields.
    repo_path:
        Absolute path to repository root.  Defaults to ``Path.cwd()``.
    auto_bootstrap:
        When True and the ref does not exist, call ``bootstrap(push=False)``
        before writing.  Set False in tests that pre-create the ref manually.

    Returns
    -------
    WriteClaimResult
    """
    from .claim_schema import serialize_claim  # type: ignore[import]

    repo: Path = repo_path if repo_path is not None else Path.cwd()

    if not _YAML_AVAILABLE:
        return WriteClaimResult(
            success=False,
            commit_sha="",
            blob_sha="",
            claim_path="",
            error="yaml_unavailable",
        )

    # Validate required identity fields.
    container = getattr(record, "container", "")
    session = getattr(record, "session", "")
    if not container or not session:
        return WriteClaimResult(
            success=False,
            commit_sha="",
            blob_sha="",
            claim_path="",
            error="missing_container_or_session",
        )

    claim_path = f"{_CLAIMS_PREFIX}/{container}/{session}.yaml"

    # Ensure the ref exists.
    local_exists = _ref_exists_local(repo, REF_NAME)
    if not local_exists:
        if not auto_bootstrap:
            return WriteClaimResult(
                success=False,
                commit_sha="",
                blob_sha="",
                claim_path=claim_path,
                error="ref_not_exists",
            )
        boot = bootstrap(repo_path=repo, push=False)
        if boot.error and not boot.commit_sha:
            return WriteClaimResult(
                success=False,
                commit_sha="",
                blob_sha="",
                claim_path=claim_path,
                error="bootstrap_failed",
            )

    # Serialize the record to YAML bytes.
    raw_dict = serialize_claim(record)
    yaml_text = _yaml.safe_dump(raw_dict, default_flow_style=False, allow_unicode=True)
    yaml_bytes = yaml_text.encode("utf-8")

    # Write blob into git object store.
    rc_ho, blob_sha, ho_err = _run(
        ["git", "-C", str(repo), "hash-object", "-w", "--stdin"],
        cwd=repo,
        input=yaml_text,
    )
    if rc_ho != 0 or not blob_sha:
        logger.warning(
            "coordination_ref.write_claim: hash-object failed (rc=%d): %s",
            rc_ho,
            ho_err,
        )
        return WriteClaimResult(
            success=False,
            commit_sha="",
            blob_sha="",
            claim_path=claim_path,
            error="hash_object_failed",
        )

    # Resolve git-dir (works for both regular repos and worktrees).
    rc_gd, git_dir_raw, _gd_err = _run(
        ["git", "-C", str(repo), "rev-parse", "--git-dir"],
        cwd=repo,
    )
    if rc_gd != 0 or not git_dir_raw:
        return WriteClaimResult(
            success=False,
            commit_sha="",
            blob_sha=blob_sha,
            claim_path=claim_path,
            error="hash_object_failed",
        )
    git_dir = Path(git_dir_raw) if Path(git_dir_raw).is_absolute() else repo / git_dir_raw

    # Build new tree via a temporary, isolated work-tree.
    with tempfile.TemporaryDirectory(prefix="aria-coord-") as tmp_str:
        tmp = Path(tmp_str)

        # Create the claim file on the temp filesystem.
        claim_file = tmp / claim_path
        claim_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            claim_file.write_bytes(yaml_bytes)
        except OSError as exc:
            return WriteClaimResult(
                success=False,
                commit_sha="",
                blob_sha=blob_sha,
                claim_path=claim_path,
                error=f"write_tmp_failed:{type(exc).__name__}",
            )

        # Stage the single file.  We use a fresh GIT_INDEX_FILE so we do not
        # disturb any existing index (working-tree or other worktrees).
        tmp_index = tmp / ".git-index-tmp"
        scratch_env = {"GIT_INDEX_FILE": str(tmp_index)}

        # Start from the current ref tree so existing files are preserved.
        current_sha = _resolve_ref(repo, REF_NAME)
        if current_sha:
            # Read the existing tree into our scratch index.
            rc_rt, _rt_out, rt_err = _run(
                [
                    "git",
                    "--git-dir",
                    str(git_dir),
                    "--work-tree",
                    str(tmp),
                    "read-tree",
                    f"{REF_NAME}^{{tree}}",
                ],
                cwd=repo,
                extra_env=scratch_env,
            )
            # read-tree may fail if the tree is empty; treat as non-fatal.
            if rc_rt != 0:
                logger.debug(
                    "coordination_ref.write_claim: read-tree returned %d (%s); "
                    "proceeding with empty index",
                    rc_rt,
                    rt_err,
                )

        # Add / replace the specific blob in the scratch index.
        rc_ui, _ui_out, ui_err = _run(
            [
                "git",
                "--git-dir",
                str(git_dir),
                "update-index",
                "--add",
                "--cacheinfo",
                f"100644,{blob_sha},{claim_path}",
            ],
            cwd=repo,
            extra_env=scratch_env,
        )
        if rc_ui != 0:
            logger.warning(
                "coordination_ref.write_claim: update-index failed (rc=%d): %s",
                rc_ui,
                ui_err,
            )
            return WriteClaimResult(
                success=False,
                commit_sha="",
                blob_sha=blob_sha,
                claim_path=claim_path,
                error="mktree_failed",
            )

        # Write the tree object from the scratch index.
        rc_wt, tree_sha, wt_err = _run(
            [
                "git",
                "--git-dir",
                str(git_dir),
                "write-tree",
            ],
            cwd=repo,
            extra_env=scratch_env,
        )
        if rc_wt != 0 or not tree_sha:
            logger.warning(
                "coordination_ref.write_claim: write-tree failed (rc=%d): %s",
                rc_wt,
                wt_err,
            )
            return WriteClaimResult(
                success=False,
                commit_sha="",
                blob_sha=blob_sha,
                claim_path=claim_path,
                error="mktree_failed",
            )

    # Commit the new tree on top of the current ref.
    commit_msg = (
        f"claim: {container}/{session} "
        f"status={getattr(record, 'status', '?')} "
        f"phase={getattr(record, 'phase', '?')}"
    )
    current_sha = _resolve_ref(repo, REF_NAME)
    ct_cmd = ["git", "-C", str(repo), "commit-tree", tree_sha, "-m", commit_msg]
    if current_sha:
        ct_cmd += ["-p", current_sha]

    rc_ct, new_commit_sha, ct_err = _run(ct_cmd, cwd=repo)
    if rc_ct != 0 or not new_commit_sha:
        logger.warning(
            "coordination_ref.write_claim: commit-tree failed (rc=%d): %s",
            rc_ct,
            ct_err,
        )
        return WriteClaimResult(
            success=False,
            commit_sha="",
            blob_sha=blob_sha,
            claim_path=claim_path,
            error="commit_tree_failed",
        )

    # Advance the ref.
    rc_ur, _ur_out, ur_err = _run(
        ["git", "-C", str(repo), "update-ref", REF_NAME, new_commit_sha],
        cwd=repo,
    )
    if rc_ur != 0:
        logger.warning(
            "coordination_ref.write_claim: update-ref failed (rc=%d): %s",
            rc_ur,
            ur_err,
        )
        return WriteClaimResult(
            success=False,
            commit_sha="",
            blob_sha=blob_sha,
            claim_path=claim_path,
            error="update_ref_failed",
        )

    logger.info(
        "coordination_ref.write_claim: wrote %s → commit %s",
        claim_path,
        new_commit_sha,
    )
    return WriteClaimResult(
        success=True,
        commit_sha=new_commit_sha,
        blob_sha=blob_sha,
        claim_path=claim_path,
        error=None,
    )


def push_coordination_ref(
    repo_path: Path | None = None,
    *,
    remote: str = "origin",
) -> PushResult:
    """Push the local coordination ref to the remote.

    Executes ``git push <remote> refs/aria/coordination:refs/aria/coordination``.

    Failure classification
    ----------------------
    - 401 / 403 / "authentication failed" / "permission denied"
      → ``error_kind="auth_failed"`` (do not retry — operator action required)
    - Non-fast-forward rejection
      → ``error_kind="non_ff"`` (caller should fetch + replay; TASK-019)
    - DNS / unreachable / timeout patterns
      → ``error_kind="network"``
    - Any other git push failure
      → ``error_kind="push_failed"``

    Parameters
    ----------
    repo_path:
        Absolute path to repository root.  Defaults to ``Path.cwd()``.
    remote:
        Git remote name.  Default ``"origin"``.

    Returns
    -------
    PushResult
    """
    repo: Path = repo_path if repo_path is not None else Path.cwd()

    refspec = f"{REF_NAME}:{REF_NAME}"
    rc, _out, err = _run(
        ["git", "-C", str(repo), "push", remote, refspec],
        cwd=repo,
    )

    if rc == 0:
        logger.info(
            "coordination_ref.push_coordination_ref: pushed %s to %s/%s",
            REF_NAME,
            remote,
            REF_NAME,
        )
        return PushResult(success=True, error_kind=None, error_msg=None)

    err_lower = err.lower()

    if (
        "401" in err
        or "403" in err
        or "authentication failed" in err_lower
        or "permission denied" in err_lower
    ):
        kind = "auth_failed"
    elif "non-fast-forward" in err_lower or "rejected" in err_lower:
        kind = "non_ff"
    elif (
        "could not resolve host" in err_lower
        or "unable to connect" in err_lower
        or "connection refused" in err_lower
        or "timed out" in err_lower
        or "network" in err_lower
    ):
        kind = "network"
    else:
        kind = "push_failed"

    logger.warning(
        "coordination_ref.push_coordination_ref: push failed "
        "(rc=%d, kind=%s, remote=%s)",
        rc,
        kind,
        remote,
    )
    return PushResult(success=False, error_kind=kind, error_msg=err[:200])


def fetch_coordination_ref(
    repo_path: Path | None = None,
    *,
    remote: str = "origin",
) -> FetchResult:
    """Fetch the remote coordination ref into the local namespace.

    Executes ``git fetch <remote> refs/aria/coordination:refs/aria/coordination``.

    The function records the local ref SHA before and after the fetch to
    determine whether the ref was actually updated (i.e. the remote had
    newer commits).

    Failure classification
    ----------------------
    - 401 / 403 / authentication patterns → ``error_kind="auth_failed"``
    - DNS / unreachable / network patterns → ``error_kind="network"``
    - Any other git fetch failure           → ``error_kind="fetch_failed"``

    Parameters
    ----------
    repo_path:
        Absolute path to repository root.  Defaults to ``Path.cwd()``.
    remote:
        Git remote name.  Default ``"origin"``.

    Returns
    -------
    FetchResult
    """
    repo: Path = repo_path if repo_path is not None else Path.cwd()

    # Capture the pre-fetch SHA to detect whether the ref advanced.
    sha_before = _resolve_ref(repo, REF_NAME)

    refspec = f"{REF_NAME}:{REF_NAME}"
    rc, _out, err = _run(
        ["git", "-C", str(repo), "fetch", remote, refspec],
        cwd=repo,
    )

    if rc == 0:
        sha_after = _resolve_ref(repo, REF_NAME)
        ref_updated = sha_after != sha_before and bool(sha_after)
        logger.info(
            "coordination_ref.fetch_coordination_ref: fetched from %s "
            "(updated=%s, sha=%s)",
            remote,
            ref_updated,
            sha_after,
        )
        return FetchResult(
            success=True,
            error_kind=None,
            error_msg=None,
            ref_updated=ref_updated,
        )

    err_lower = err.lower()

    if (
        "401" in err
        or "403" in err
        or "authentication failed" in err_lower
        or "permission denied" in err_lower
    ):
        kind = "auth_failed"
    elif (
        "could not resolve host" in err_lower
        or "unable to connect" in err_lower
        or "connection refused" in err_lower
        or "timed out" in err_lower
        or "network" in err_lower
    ):
        kind = "network"
    else:
        kind = "fetch_failed"

    logger.warning(
        "coordination_ref.fetch_coordination_ref: fetch failed "
        "(rc=%d, kind=%s, remote=%s)",
        rc,
        kind,
        remote,
    )
    return FetchResult(
        success=False,
        error_kind=kind,
        error_msg=err[:200],
        ref_updated=False,
    )

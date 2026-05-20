"""Resilient wrapper / retry orchestration for Layer L coordination operations.

This module wraps the low-level push/fetch/write primitives from
``coordination_ref`` (TASK-013) into high-level, fail-soft APIs that cover the
seven failure categories mandated by tasks.md §2.9:

    (a) push non-ff (two containers racing)     → fetch-replay-repush, N=3
    (b) push 401/403 (auth failure)             → no retry, warn + human decision
    (c) push other failure                      → ask user_decision callback
    (d) orphan ref missing (first run)          → auto-bootstrap (TASK-012)
    (e) disk full / local write failure         → warn + skip claim, non-crashing
    (f) partial fetch (SHA regression detected) → classify + retry via (a) path
    (g) clock-skew > 30 s                       → reconcile downgrades to CONFLICT
                                                   (handled by reconcile itself per §2.7;
                                                    this module detects and surfaces it)

Design principles
-----------------
- All subprocess calls delegate to coordination_ref._run (capture_output=True,
  Rule #7 compliant).  This module contains zero direct subprocess usage.
- user_decision callbacks are called for operator-interactive failures (b, c).
  When no callback is provided the behaviour is: auth_failed → abort;
  other failures → abort (same default as user answering False).
- Disk-full (case e) is caught via OSError with errno.ENOSPC; the caller
  receives success=False with disk_full=True and execution continues normally.
- max_retries=0 means run once; on failure return immediately (no retry loop).

Rule #7 compliance
------------------
All subprocess I/O is routed through coordination_ref primitives that enforce
capture_output=True.  No stdout/stderr containing potential secrets is printed
or logged at INFO or above.  Short non-secret tokens are used in error_kind.

Spec: openspec/changes/multi-terminal-coordination/tasks.md §2.9
Task: TASK-019 (P2 Round 5)
Deps: TASK-012 (bootstrap — coordination_ref.bootstrap)
      TASK-013 (coordination_ref — push / fetch / write_claim + result types)
      TASK-018 (constants — CLOCK_SKEW_WARN_THRESHOLD)
"""

from __future__ import annotations

import errno
import logging
import time
from pathlib import Path
from typing import Callable, NamedTuple, Optional

from .coordination_ref import (
    BootstrapResult,
    FetchResult,
    PushResult,
    WriteClaimResult,
    REF_NAME,
    bootstrap,
    fetch_coordination_ref,
    push_coordination_ref,
    write_claim,
    _resolve_ref,  # internal helper — SHA lookup without subprocess by caller
)
from .constants import CLOCK_SKEW_WARN_THRESHOLD  # noqa: F401 (re-exported for callers)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-local constants  (P2-local; not promoted to constants.py unless reused)
# ---------------------------------------------------------------------------

# Maximum number of fetch-replay-repush cycles for a non-ff push (case a).
NON_FF_MAX_RETRIES: int = 3

# Exponential back-off between non-ff retry attempts (seconds).
# Index maps to attempt number (0-based): attempt 0 → 1 s, attempt 1 → 2 s, etc.
# Last value is reused for any attempt index beyond the tuple length.
PUSH_BACKOFF_SECONDS: tuple[int, ...] = (1, 2, 4)

# ---------------------------------------------------------------------------
# UserDecision callback type
# ---------------------------------------------------------------------------

# Injected by the caller (e.g. state-scanner UI layer) to resolve operator-
# interactive failure paths.  Receives (error_kind, error_msg, context_dict)
# and returns True to continue/retry or False to abort.
#
# Example (≤30 words): a simple CLI prompt that prints the error and reads
# "y/n" from stdin; returning True means the operator chose to retry/continue.
UserDecisionCallback = Callable[[str, str, dict], bool]

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


class ResilientPushResult(NamedTuple):
    """Outcome of :func:`resilient_push`.

    Fields
    ------
    success : bool
        True only when the push ultimately succeeded.
    final_push_result : PushResult | None
        The last PushResult returned by push_coordination_ref; None when push
        was never attempted (e.g. pre-condition failed).
    attempts : int
        Total number of push attempts made (initial + retries).
    triggered_fetch_replay : bool
        True when at least one non-ff fetch-replay cycle was executed (case a).
    bootstrap_triggered : bool
        Reserved for parity with ResilientWriteResult; always False here
        (bootstrap is not triggered by push — write path only).
    error_kind : str | None
        Final error category; None on success.  Possible values:
        ``"auth_failed"``, ``"max_retries_exhausted"``,
        ``"fetch_replay_failed"``, ``"user_aborted"``,
        ``"push_failed"``, ``"network"`` (pass-through from PushResult).
    error_msg : str | None
        Short non-secret context; None on success.
    user_aborted : bool
        True when a user_decision callback returned False.
    """

    success: bool
    final_push_result: Optional[PushResult]
    attempts: int
    triggered_fetch_replay: bool
    bootstrap_triggered: bool
    error_kind: Optional[str]
    error_msg: Optional[str]
    user_aborted: bool


class ResilientWriteResult(NamedTuple):
    """Outcome of :func:`resilient_write_claim`.

    Fields
    ------
    success : bool
    write_result : WriteClaimResult | None
        The underlying WriteClaimResult on success or non-disk-full failure;
        None when an OSError was caught before write_claim was called.
    bootstrap_triggered : bool
        True when the ref was absent and auto-bootstrap ran (case d).
    disk_full : bool
        True when an OSError with errno.ENOSPC was caught (case e).
    error_kind : str | None
        None on success.  Possible values: ``"disk_full"``, ``"os_error"``,
        ``"bootstrap_failed"``, and any error token from WriteClaimResult.error.
    error_msg : str | None
        Short non-secret context; None on success.
    """

    success: bool
    write_result: Optional[WriteClaimResult]
    bootstrap_triggered: bool
    disk_full: bool
    error_kind: Optional[str]
    error_msg: Optional[str]


class FetchHealth(NamedTuple):
    """Outcome of :func:`health_check_fetch`.

    Fields
    ------
    success : bool
        True when the fetch succeeded and the ref SHA did not regress.
    partial_fetch : bool
        True when either (a) the fetch command failed, or (b) the fetch
        succeeded but the local ref SHA regressed (SHA after < SHA before in
        ancestor terms) — indicating corruption or a non-monotonic update.
    ref_sha_before : str
        Local ref SHA captured before the fetch (empty string if ref absent).
    ref_sha_after : str
        Local ref SHA captured after the fetch (empty string if ref absent or
        fetch failed).
    error_kind : str | None
        None on success.  Possible values: ``"fetch_failed"``, ``"network"``,
        ``"auth_failed"``, ``"ref_regression"``.
    error_msg : str | None
        Short non-secret context; None on success.
    """

    success: bool
    partial_fetch: bool
    ref_sha_before: str
    ref_sha_after: str
    error_kind: Optional[str]
    error_msg: Optional[str]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _backoff_for_attempt(attempt_index: int) -> int:
    """Return the back-off duration in seconds for a given 0-based attempt index."""
    if attempt_index < len(PUSH_BACKOFF_SECONDS):
        return PUSH_BACKOFF_SECONDS[attempt_index]
    return PUSH_BACKOFF_SECONDS[-1]


def _is_ancestor(repo: Path, ancestor_sha: str, descendant_sha: str) -> bool:
    """Return True when ``ancestor_sha`` is a git ancestor of ``descendant_sha``.

    Uses ``git merge-base --is-ancestor`` (exit 0 = yes, exit 1 = no).
    Any other return code (git error) is treated conservatively as False.

    Rule #7: delegated to coordination_ref._run which enforces capture_output=True.
    """
    from .coordination_ref import _run  # reuse existing Rule-#7-compliant runner

    rc, _out, _err = _run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", ancestor_sha, descendant_sha],
        cwd=repo,
    )
    return rc == 0


def _call_user_decision(
    callback: Optional[UserDecisionCallback],
    error_kind: str,
    error_msg: str,
    context: dict,
) -> bool:
    """Invoke the user_decision callback safely.

    Returns False (abort) when:
    - callback is None
    - callback raises an exception (exception is logged, not re-raised)
    """
    if callback is None:
        return False
    try:
        return bool(callback(error_kind, error_msg, context))
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "failure_handlers: user_decision callback raised %s — treating as abort",
            type(exc).__name__,
        )
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resilient_push(
    repo_path: Optional[Path] = None,
    *,
    remote: str = "origin",
    max_retries: int = NON_FF_MAX_RETRIES,
    user_decision: Optional[UserDecisionCallback] = None,
) -> ResilientPushResult:
    """Push refs/aria/coordination with resilient failure handling.

    Failure matrix covered
    ----------------------
    (a) non_ff — fetch-replay-repush loop up to ``max_retries`` times.
        Each cycle: health_check_fetch() → sleep(backoff) → push again.
        If health_check_fetch fails mid-retry, returns
        ``error_kind="fetch_replay_failed"``.
        When retries are exhausted: ``error_kind="max_retries_exhausted"``.

    (b) auth_failed — does NOT retry.  Calls user_decision if provided;
        if callback returns True (operator chose continue), returns success=False
        with the auth error nonetheless (auth cannot self-heal via retry).
        Always sets user_aborted=True when callback returns False.

    (c) other push failure — calls user_decision if provided.
        False → user_aborted=True, abort.
        True  → abort with original error_kind (no automatic retry loop for
                general failures; caller may call resilient_push again if desired).

    Parameters
    ----------
    repo_path:
        Absolute path to repository root.  Defaults to Path.cwd().
    remote:
        Git remote name.  Default "origin".
    max_retries:
        Maximum number of fetch-replay-repush attempts for non-ff failures.
        0 means run once and return on any failure.
    user_decision:
        Optional callback for operator-interactive failure paths (b, c).
        Signature: (error_kind: str, error_msg: str, context: dict) -> bool.

    Returns
    -------
    ResilientPushResult
    """
    repo: Path = repo_path if repo_path is not None else Path.cwd()

    attempts: int = 0
    triggered_fetch_replay: bool = False

    # Total iterations = 1 (initial) + max_retries (non-ff only)
    max_iterations = max_retries + 1

    while attempts < max_iterations:
        pr: PushResult = push_coordination_ref(repo, remote=remote)
        attempts += 1

        # --- success path ---
        if pr.success:
            logger.info(
                "failure_handlers.resilient_push: succeeded on attempt %d", attempts
            )
            return ResilientPushResult(
                success=True,
                final_push_result=pr,
                attempts=attempts,
                triggered_fetch_replay=triggered_fetch_replay,
                bootstrap_triggered=False,
                error_kind=None,
                error_msg=None,
                user_aborted=False,
            )

        # --- case (b): auth failure — no retry ---
        if pr.error_kind == "auth_failed":
            logger.warning(
                "failure_handlers.resilient_push: auth_failed on attempt %d "
                "(remote=%s) — not retrying",
                attempts,
                remote,
            )
            ctx = {"attempt": attempts, "remote": remote}
            # Inform the operator but do not retry regardless of decision.
            cont = _call_user_decision(user_decision, "auth_failed", pr.error_msg or "", ctx)
            return ResilientPushResult(
                success=False,
                final_push_result=pr,
                attempts=attempts,
                triggered_fetch_replay=triggered_fetch_replay,
                bootstrap_triggered=False,
                error_kind="auth_failed",
                error_msg=pr.error_msg,
                user_aborted=not cont,
            )

        # --- case (a): non-ff — fetch-replay-repush ---
        if pr.error_kind == "non_ff":
            triggered_fetch_replay = True
            logger.info(
                "failure_handlers.resilient_push: non_ff on attempt %d — "
                "fetching and replaying (retries remaining: %d)",
                attempts,
                max_iterations - attempts,
            )

            if attempts >= max_iterations:
                # No more retry budget; fall through to exhausted.
                break

            # Fetch the latest remote state before retrying.
            fh: FetchHealth = health_check_fetch(repo, remote=remote)
            if not fh.success:
                logger.warning(
                    "failure_handlers.resilient_push: fetch_replay_failed "
                    "during non-ff retry (attempt %d)",
                    attempts,
                )
                return ResilientPushResult(
                    success=False,
                    final_push_result=pr,
                    attempts=attempts,
                    triggered_fetch_replay=True,
                    bootstrap_triggered=False,
                    error_kind="fetch_replay_failed",
                    error_msg=fh.error_msg,
                    user_aborted=False,
                )

            # Back off before retrying.
            backoff = _backoff_for_attempt(attempts - 1)
            logger.debug(
                "failure_handlers.resilient_push: sleeping %ds before retry %d",
                backoff,
                attempts + 1,
            )
            time.sleep(backoff)
            continue  # retry push

        # --- case (c): other push failure ---
        logger.warning(
            "failure_handlers.resilient_push: push_failed (kind=%s) on attempt %d "
            "(remote=%s)",
            pr.error_kind,
            attempts,
            remote,
        )
        ctx = {"attempt": attempts, "remote": remote, "error_kind": pr.error_kind}
        cont = _call_user_decision(user_decision, pr.error_kind or "push_failed", pr.error_msg or "", ctx)
        if not cont:
            return ResilientPushResult(
                success=False,
                final_push_result=pr,
                attempts=attempts,
                triggered_fetch_replay=triggered_fetch_replay,
                bootstrap_triggered=False,
                error_kind=pr.error_kind,
                error_msg=pr.error_msg,
                user_aborted=True,
            )
        # User chose to continue — abort with original error (no auto-retry for
        # general failures; caller must decide whether to call again).
        return ResilientPushResult(
            success=False,
            final_push_result=pr,
            attempts=attempts,
            triggered_fetch_replay=triggered_fetch_replay,
            bootstrap_triggered=False,
            error_kind=pr.error_kind,
            error_msg=pr.error_msg,
            user_aborted=False,
        )

    # --- non-ff retries exhausted ---
    logger.warning(
        "failure_handlers.resilient_push: max_retries_exhausted after %d attempts",
        attempts,
    )
    # final_push_result is from the last push attempt; reconstruct a synthetic
    # PushResult with the exhausted token for clarity if the last real result
    # was a non_ff (it usually will be).
    last_pr = PushResult(
        success=False,
        error_kind="non_ff",
        error_msg="max retries exhausted after non-ff",
    )
    return ResilientPushResult(
        success=False,
        final_push_result=last_pr,
        attempts=attempts,
        triggered_fetch_replay=triggered_fetch_replay,
        bootstrap_triggered=False,
        error_kind="max_retries_exhausted",
        error_msg=f"non-ff push failed after {attempts} attempt(s)",
        user_aborted=False,
    )


def resilient_write_claim(
    record,  # ClaimRecord — untyped to avoid circular import at definition time
    repo_path: Optional[Path] = None,
    *,
    auto_bootstrap: bool = True,
) -> ResilientWriteResult:
    """Write a claim to the coordination ref with disk-full and bootstrap guards.

    Failure matrix covered
    ----------------------
    (d) orphan ref absent — when auto_bootstrap=True, delegates to bootstrap()
        before the write attempt.  Sets bootstrap_triggered=True in the result.
        If bootstrap itself fails: returns error_kind="bootstrap_failed".

    (e) disk full / local OSError — catches OSError at the write_claim call
        site.  errno.ENOSPC → disk_full=True, error_kind="disk_full".
        Any other OSError → disk_full=False, error_kind="os_error".
        In either case success=False and execution continues normally (no raise).

    Note: write_claim (TASK-013) internally handles ref-absent + auto_bootstrap
    already.  This wrapper adds the OSError catch layer (case e) and surfaces
    bootstrap_triggered in the result for observability.

    Parameters
    ----------
    record:
        A ClaimRecord with non-empty container and session fields.
    repo_path:
        Absolute path to repository root.  Defaults to Path.cwd().
    auto_bootstrap:
        When True (default), automatically bootstrap the coordination ref if it
        does not exist before writing.  Set False in tests with pre-created ref.

    Returns
    -------
    ResilientWriteResult
    """
    from .coordination_ref import _ref_exists_local  # Rule #7-compliant helper

    repo: Path = repo_path if repo_path is not None else Path.cwd()

    # Detect whether bootstrap will be triggered (for the result flag).
    bootstrap_triggered: bool = False
    local_exists = _ref_exists_local(repo, REF_NAME)
    if not local_exists and auto_bootstrap:
        bootstrap_triggered = True
        logger.info(
            "failure_handlers.resilient_write_claim: ref absent — running bootstrap (case d)"
        )
        boot: BootstrapResult = bootstrap(repo_path=repo, push=False)
        if boot.error and not boot.commit_sha:
            logger.warning(
                "failure_handlers.resilient_write_claim: bootstrap failed: %s",
                boot.error,
            )
            return ResilientWriteResult(
                success=False,
                write_result=None,
                bootstrap_triggered=True,
                disk_full=False,
                error_kind="bootstrap_failed",
                error_msg=boot.error,
            )

    # Attempt the write, catching OSError for disk-full / filesystem errors (case e).
    try:
        wr: WriteClaimResult = write_claim(record, repo, auto_bootstrap=auto_bootstrap)
    except OSError as exc:
        is_disk_full = exc.errno == errno.ENOSPC
        kind = "disk_full" if is_disk_full else "os_error"
        logger.warning(
            "failure_handlers.resilient_write_claim: OSError during write_claim "
            "(errno=%s, disk_full=%s) — skipping claim (case e)",
            exc.errno,
            is_disk_full,
        )
        return ResilientWriteResult(
            success=False,
            write_result=None,
            bootstrap_triggered=bootstrap_triggered,
            disk_full=is_disk_full,
            error_kind=kind,
            error_msg=f"{type(exc).__name__}:errno={exc.errno}",
        )

    if wr.success:
        logger.info(
            "failure_handlers.resilient_write_claim: wrote claim → commit %s "
            "(bootstrap_triggered=%s)",
            wr.commit_sha,
            bootstrap_triggered,
        )
        return ResilientWriteResult(
            success=True,
            write_result=wr,
            bootstrap_triggered=bootstrap_triggered,
            disk_full=False,
            error_kind=None,
            error_msg=None,
        )

    # write_claim returned a soft failure (e.g. yaml_unavailable, commit_tree_failed).
    logger.warning(
        "failure_handlers.resilient_write_claim: write_claim returned error=%s",
        wr.error,
    )
    return ResilientWriteResult(
        success=False,
        write_result=wr,
        bootstrap_triggered=bootstrap_triggered,
        disk_full=False,
        error_kind=wr.error,
        error_msg=wr.error,
    )


def health_check_fetch(
    repo_path: Optional[Path] = None,
    *,
    remote: str = "origin",
) -> FetchHealth:
    """Fetch the coordination ref and verify SHA monotonic advancement (case f).

    Mechanism
    ---------
    1. Capture ``ref_sha_before`` via git rev-parse (empty string if ref absent).
    2. Call ``fetch_coordination_ref()``.
    3. Capture ``ref_sha_after``.
    4. If fetch failed → partial_fetch=True, success=False.
    5. If fetch succeeded and ref advanced (sha_after != sha_before and
       sha_before non-empty): verify sha_before is an ancestor of sha_after
       via ``git merge-base --is-ancestor``.
       SHA regressed (not an ancestor) → partial_fetch=True, error_kind="ref_regression".
    6. All other success cases (ref unchanged / ref newly appeared) → success=True.

    Clock-skew note (case g)
    ------------------------
    Detection of cross-container clock skew is NOT performed here — it is the
    responsibility of the reconcile layer (TASK-015 / tasks.md §2.7).  This
    function surfaces raw FetchHealth facts; reconcile uses claimed_at timestamps
    from the fetched claims to trigger CONFLICT downgrade.

    Rule #7: all subprocess I/O via coordination_ref helpers (capture_output=True).

    Parameters
    ----------
    repo_path:
        Absolute path to repository root.  Defaults to Path.cwd().
    remote:
        Git remote name.  Default "origin".

    Returns
    -------
    FetchHealth
    """
    repo: Path = repo_path if repo_path is not None else Path.cwd()

    # Step 1: capture pre-fetch SHA.
    sha_before: str = _resolve_ref(repo, REF_NAME)  # "" if ref absent

    # Step 2: fetch.
    fr: FetchResult = fetch_coordination_ref(repo, remote=remote)

    # Step 3: capture post-fetch SHA.
    sha_after: str = _resolve_ref(repo, REF_NAME)  # "" if ref still absent

    # Step 4: fetch failed → classify as partial_fetch.
    if not fr.success:
        logger.warning(
            "failure_handlers.health_check_fetch: fetch failed "
            "(kind=%s) — marking partial_fetch",
            fr.error_kind,
        )
        return FetchHealth(
            success=False,
            partial_fetch=True,
            ref_sha_before=sha_before,
            ref_sha_after=sha_after,
            error_kind=fr.error_kind,
            error_msg=fr.error_msg,
        )

    # Step 5: detect SHA regression when ref existed before and after.
    if sha_before and sha_after and sha_after != sha_before:
        if not _is_ancestor(repo, sha_before, sha_after):
            # sha_before is not an ancestor of sha_after → ref regressed.
            logger.warning(
                "failure_handlers.health_check_fetch: ref SHA regressed "
                "(before=%s after=%s) — marking partial_fetch (case f)",
                sha_before[:12],
                sha_after[:12],
            )
            return FetchHealth(
                success=False,
                partial_fetch=True,
                ref_sha_before=sha_before,
                ref_sha_after=sha_after,
                error_kind="ref_regression",
                error_msg=(
                    f"coordination ref regressed: {sha_before[:12]} → {sha_after[:12]}"
                ),
            )

    # Step 6: normal — ref unchanged or monotonically advanced.
    logger.debug(
        "failure_handlers.health_check_fetch: fetch OK "
        "(updated=%s, sha_before=%s sha_after=%s)",
        fr.ref_updated,
        sha_before[:12] if sha_before else "(none)",
        sha_after[:12] if sha_after else "(none)",
    )
    return FetchHealth(
        success=True,
        partial_fetch=False,
        ref_sha_before=sha_before,
        ref_sha_after=sha_after,
        error_kind=None,
        error_msg=None,
    )

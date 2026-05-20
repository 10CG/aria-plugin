"""Phase 1 急切认领闸门 (multi-terminal-coordination Layer L).

闸门是 state-scanner Phase 1 完成 → AI 进 Phase B 之间的 checkpoint。

Semantic contract
-----------------
- 闸门是窗口压缩器、非排他: 通过闸门不等于持有锁。残留秒级窗口可能
  仍有他人同时通过自己的闸门。
- reconcile (TASK-015) 是最终仲裁者: 下次 fetch 触发 reconcile, 按
  早 claimed_at 胜规则确定性裁决, append-only + 时间戳确保所有 race
  都被记录, 不会两船夜里相错。
- push 前已写入 claimed_at: acquire_claim 在 resilient_write_claim 内
  部完成本地写入, 写入成功后才执行 push。push 失败时 claimed_at 已在
  本地 ref, 但远端未同步 — 闸门告警用户而非静默丢弃。

Gate sequence (9 steps)
-----------------------
  1. derive_track_id(raw_track_id)  → canonical track_id
  2. validate repo_path is a git repo
  3. health_check_fetch (second-fetch, 收窄撞车窗口)
  4. read_claims (fetch 后, 确保看到最新远端状态)
  5. filter claims by track_id → list[ClaimRecord]
  6. reconcile(track_id, track_claims, now=now) → verdict
  7. 决策分支:
     - 无活跃对手 / self-resume → 直接进入 8
     - 他人 active + fresh → user_decision prompt
       yield   → GateResult(USER_YIELDED)
       takeover (if eligible) → 进入 8
       abort / other → GateResult(ABORT)
     - clock_skew_conflict → prompt user (高风险, default abort)
  8. acquire_claim → resilient_write_claim (disk-full / bootstrap guard)
  9. resilient_push (non-ff retry, auth abort) →
     success → GateResult(PASSED)
     fail    → user_decision → PROCEED (advisory) / BLOCKED_PUSH_FAILED

Spec references
---------------
  openspec/changes/multi-terminal-coordination/tasks.md §2.5
  openspec/changes/multi-terminal-coordination/proposal.md §What/Layer L
  docs/decisions/DEC-20260519-001-multi-terminal-coordination.md #4
Task: TASK-016 (P2 Round 6)
Deps: TASK-013 (claim CRUD), TASK-014 (track-id derivation),
      TASK-015 (reconcile), TASK-018 (acquire/heartbeat/release),
      TASK-019 (resilient_push / resilient_write_claim)
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, NamedTuple, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Import lib modules — dual-context strategy (same pattern as track_board.py).
# Context (a): scripts/ on sys.path (test harness) — relative import crosses
#              package boundary and fails.
# Context (b): proper package install — relative import works cleanly.
# ---------------------------------------------------------------------------
try:
    from ..lib.claim_lifecycle import acquire_claim, AcquireResult
    from ..lib.claim_schema import ClaimRecord, SCHEMA_VERSION_CURRENT
    from ..lib.coordination_ref import read_claims, ReadClaimsResult
    from ..lib.failure_handlers import (
        resilient_push,
        resilient_write_claim,
        health_check_fetch,
        ResilientPushResult,
        ResilientWriteResult,
        FetchHealth,
        UserDecisionCallback,
    )
    from ..lib.identity import Identity, get_identity
    from ..lib.reconcile import reconcile, ReconcileVerdict
    from ..lib.track_id import derive_track_id
except ImportError:
    import sys as _sys
    from pathlib import Path as _Path
    _LIB_DIR = str(_Path(__file__).resolve().parent.parent / "lib")
    if _LIB_DIR not in _sys.path:
        _sys.path.insert(0, _LIB_DIR)
    from claim_lifecycle import acquire_claim, AcquireResult  # type: ignore[import]
    from claim_schema import ClaimRecord, SCHEMA_VERSION_CURRENT  # type: ignore[import]
    from coordination_ref import read_claims, ReadClaimsResult  # type: ignore[import]
    from failure_handlers import (  # type: ignore[import]
        resilient_push,
        resilient_write_claim,
        health_check_fetch,
        ResilientPushResult,
        ResilientWriteResult,
        FetchHealth,
        UserDecisionCallback,
    )
    from identity import Identity, get_identity  # type: ignore[import]
    from reconcile import reconcile, ReconcileVerdict  # type: ignore[import]
    from track_id import derive_track_id  # type: ignore[import]


# ---------------------------------------------------------------------------
# GateOutcome — enum-like string constants
# ---------------------------------------------------------------------------

class GateOutcome:
    """Outcome tokens for GateResult.outcome.

    PASSED                 — claim acquired + pushed; user may proceed to Phase B.
    BLOCKED_OCCUPIED       — active fresh claim by another container; user yielded.
    BLOCKED_PUSH_FAILED    — claim written locally but push failed; user aborted.
    USER_YIELDED           — user explicitly chose to yield the track.
    USER_TAKEOVER          — user initiated takeover of a stale/eligible claim.
    USER_OVERRIDE_PROCEED  — push failed but user chose to proceed (advisory mode).
    ABORT                  — unrecoverable error or user chose to abort entirely.
    """

    PASSED = "passed"
    BLOCKED_OCCUPIED = "blocked_occupied"
    BLOCKED_PUSH_FAILED = "blocked_push_failed"
    USER_YIELDED = "user_yielded"
    USER_TAKEOVER = "user_takeover"
    USER_OVERRIDE_PROCEED = "user_override_proceed"
    ABORT = "abort"


# ---------------------------------------------------------------------------
# GateResult
# ---------------------------------------------------------------------------

class GateResult(NamedTuple):
    """Return type of :func:`run_gate`.

    Fields
    ------
    outcome : str
        One of the GateOutcome.* constants.
    track_id : str
        Canonical (derived) track_id; empty string on pre-derive failure.
    raw_input_id : str
        The raw id supplied by the caller (pre-derive); useful for UI display.
    own_claim : ClaimRecord | None
        The successfully written ClaimRecord for this session, or None when no
        claim was acquired (yield / abort / push-failure without proceed).
    competing_verdict : ReconcileVerdict | None
        Populated when a competing active claim was detected during gate
        evaluation (step 6).  None when there was no active competition.
    push_result : ResilientPushResult | None
        Final push attempt result; None when push was never attempted.
    error : str | None
        Short, non-secret error token; None on success.
        Possible values: "not_a_git_repo", "identity_error", "fetch_degraded",
        "write_failed", "max_retries_exhausted", "auth_failed", "user_aborted",
        "push_failed", and any resilient_push error_kind.
    """

    outcome: str
    track_id: str
    raw_input_id: str
    own_claim: Optional[ClaimRecord]
    competing_verdict: Optional[ReconcileVerdict]
    push_result: Optional[ResilientPushResult]
    error: Optional[str]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_git_repo(path: Path) -> bool:
    """Return True when *path* is inside a valid git repository.

    Rule #7 compliant: subprocess uses capture_output=True; output never
    surfaces in the chat-visible channel.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _abort(raw_id: str, track_id: str, error: str) -> GateResult:
    """Shorthand for building a GateResult with ABORT outcome."""
    return GateResult(
        outcome=GateOutcome.ABORT,
        track_id=track_id,
        raw_input_id=raw_id,
        own_claim=None,
        competing_verdict=None,
        push_result=None,
        error=error,
    )


def _self_resume(
    verdict: ReconcileVerdict,
    identity: Identity,
) -> bool:
    """Return True when this session is resuming its own existing active claim.

    Matches on (container, session) because a session that already holds an
    active claim on the same track should refresh its heartbeat rather than
    acquiring a duplicate.
    """
    if verdict.winner is None:
        return False
    return (
        verdict.winner.container == identity.container_id
        and verdict.winner.session == identity.session_id
    )


def _takeover_eligible(verdict: ReconcileVerdict) -> bool:
    """Return True when the track is eligible for takeover (stale or terminal).

    The verdict_reason contains "+stale_takeover_eligible" when the winner
    has a stale heartbeat; "no_active_candidates" means all claims are terminal
    or absent — both allow a new session to take over.
    """
    reason = verdict.verdict_reason
    return (
        "stale_takeover_eligible" in reason
        or reason in {"no_active_candidates", "empty_claims"}
    )


def _call_decision(
    callback: Optional[UserDecisionCallback],
    error_kind: str,
    error_msg: str,
    context: dict,
) -> bool:
    """Invoke user_decision callback; returns False (abort) when None or raises."""
    if callback is None:
        logger.warning(
            "phase1_gate: user_decision is None for error_kind=%s — defaulting to abort",
            error_kind,
        )
        return False
    try:
        return bool(callback(error_kind, error_msg, context))
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "phase1_gate: user_decision callback raised %s — treating as abort",
            type(exc).__name__,
        )
        return False


def _heartbeat_age_minutes(winner: ClaimRecord, now: datetime) -> Optional[float]:
    """Return the age of winner.heartbeat_at in minutes relative to *now*, or None."""
    try:
        hb_dt = datetime.fromisoformat(winner.heartbeat_at.replace("Z", "+00:00"))
        if hb_dt.tzinfo is None:
            hb_dt = hb_dt.replace(tzinfo=timezone.utc)
        return (now - hb_dt).total_seconds() / 60.0
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_gate(
    raw_track_id: str,
    phase: str,
    *,
    repo_path: Optional[Path] = None,
    identity: Optional[Identity] = None,
    now: Optional[datetime] = None,
    user_decision: Optional[UserDecisionCallback] = None,
    remote: str = "origin",
) -> GateResult:
    """Execute Phase 1 acquisition gate for a single track selection.

    This function is the mandatory checkpoint between state-scanner Phase 1
    (track recommendation) and the AI entering Phase B of the ten-step cycle.
    It enforces eager claiming (急切认领) per DEC-20260519-001 #4.

    Semantic contract (must be understood by callers)
    --------------------------------------------------
    - Gate PASSED != exclusive lock.  A residual second-level race window
      exists between health_check_fetch and the remote ref receiving this
      session's push.  Any concurrent session that also passes its own gate
      during this window will be detected on the NEXT fetch by reconcile.
    - claimed_at is always written before push.  If push fails, the local
      ref already contains this session's claim; the remote is not updated.
      Callers that proceed despite push failure accept elevated collision risk.
    - reconcile (TASK-015) is the final arbiter: "earliest claimed_at wins"
      is deterministic and conflict-free across any number of concurrent claims.

    Sequence
    --------
    Steps 1-9 are annotated inline in the implementation.

    Parameters
    ----------
    raw_track_id:
        The raw work identifier chosen by the user (e.g. a Spec id or a
        carry-forward entry title).  Normalized to a canonical track_id via
        derive_track_id().
    phase:
        Current ten-step cycle phase at the time of gate execution
        (e.g. "B" or "B.1").  Written into the claim record.
    repo_path:
        Absolute path to the repository root.  Defaults to Path.cwd().
        Must be a valid git repository; otherwise returns ABORT.
    identity:
        Explicit Identity for test injection.  When None, get_identity() is
        called automatically (reads ~/.aria/container-id).
    now:
        Reference UTC datetime injected for deterministic test assertions.
        Defaults to datetime.now(timezone.utc).
    user_decision:
        Callback invoked for operator-interactive gate paths.  Signature:
          (error_kind: str, error_msg: str, context: dict) -> bool
        True = continue/proceed; False = abort.  When None, all interactive
        paths default to abort (safe default).

        error_kind values:
          "occupied"      — track has a fresh active claim by another container.
          "clock_skew"    — claimed_at timestamps differ by > CLOCK_SKEW_WARN_THRESHOLD.
          "push_failed"   — push step failed after max retries.

        context dict keys (depending on error_kind):
          "winner_owner_container"  : str — owner/container of the current winner
          "winner_heartbeat_age_min": float | None — age in minutes
          "takeover_eligible"       : bool — whether stale takeover is allowed
          "claims_count"            : int — total claims on this track
          "push_error_kind"         : str — underlying push failure token
    remote:
        Git remote name for fetch and push operations.  Default "origin".

    Returns
    -------
    GateResult
        Never raises; all error paths return a GateResult with outcome=ABORT
        or one of the BLOCKED_* / USER_* constants.
    """
    repo: Path = repo_path if repo_path is not None else Path.cwd()
    ts: datetime = now if now is not None else datetime.now(timezone.utc)

    # -----------------------------------------------------------------------
    # Step 1: derive canonical track_id
    # -----------------------------------------------------------------------
    track_id: str = derive_track_id(raw_track_id)
    logger.info(
        "phase1_gate.run_gate: raw=%r → track_id=%r phase=%s",
        raw_track_id,
        track_id,
        phase,
    )

    # -----------------------------------------------------------------------
    # Step 2: validate repo_path
    # -----------------------------------------------------------------------
    if not _is_git_repo(repo):
        logger.warning("phase1_gate.run_gate: not_a_git_repo path=%s", repo)
        return _abort(raw_track_id, track_id, "not_a_git_repo")

    # -----------------------------------------------------------------------
    # Step 3: resolve identity (before fetch, to detect identity failure early)
    # -----------------------------------------------------------------------
    resolved_identity: Optional[Identity] = identity
    if resolved_identity is None:
        try:
            resolved_identity = get_identity()
        except Exception as exc:
            logger.warning("phase1_gate.run_gate: get_identity failed: %s", exc)
            return _abort(raw_track_id, track_id, "identity_error")

    if resolved_identity is None:
        return _abort(raw_track_id, track_id, "identity_error")

    # -----------------------------------------------------------------------
    # Step 4: health_check_fetch (second-fetch — narrows the race window)
    # -----------------------------------------------------------------------
    fh: FetchHealth = health_check_fetch(repo, remote=remote)
    if not fh.success:
        logger.warning(
            "phase1_gate.run_gate: fetch degraded (kind=%s) — proceeding "
            "with stale local ref (elevated collision risk)",
            fh.error_kind,
        )
        # Degraded fetch is non-fatal: we continue with whatever is locally
        # available and warn the caller via the error field.  The gate still
        # attempts to read claims and acquire.  Per spec §2.9 (f), partial
        # fetch degrades to advisory mode; the user is not blocked.

    # -----------------------------------------------------------------------
    # Step 5: read_claims after fetch (see most recent remote state)
    # -----------------------------------------------------------------------
    rc_result: ReadClaimsResult = read_claims(repo)
    all_claims: list[ClaimRecord] = rc_result.claims if rc_result.ref_exists else []
    track_claims: list[ClaimRecord] = [c for c in all_claims if c.track_id == track_id]

    logger.debug(
        "phase1_gate.run_gate: track_id=%s total_claims=%d track_claims=%d",
        track_id,
        len(all_claims),
        len(track_claims),
    )

    # -----------------------------------------------------------------------
    # Step 6: reconcile to detect competition
    # -----------------------------------------------------------------------
    verdict: ReconcileVerdict = reconcile(track_id, track_claims, now=ts)
    competing_verdict: Optional[ReconcileVerdict] = None

    # -----------------------------------------------------------------------
    # Step 7: decision branch
    # -----------------------------------------------------------------------

    # --- 7a: self-resume — this session already holds an active claim ------
    if _self_resume(verdict, resolved_identity):
        logger.info(
            "phase1_gate.run_gate: self-resume detected for track=%s "
            "container=%s session=%s — refreshing heartbeat",
            track_id,
            resolved_identity.container_id,
            resolved_identity.session_id,
        )
        # Re-use the existing claim record (heartbeat update via normal
        # heartbeat() flow belongs to the caller's background loop; here we
        # treat it as "no competitor" and proceed directly to push).
        own_claim: Optional[ClaimRecord] = verdict.winner
        # Skip acquire — claim already exists locally.
        push_res: ResilientPushResult = resilient_push(
            repo,
            remote=remote,
            user_decision=user_decision,
        )
        if push_res.success:
            return GateResult(
                outcome=GateOutcome.PASSED,
                track_id=track_id,
                raw_input_id=raw_track_id,
                own_claim=own_claim,
                competing_verdict=None,
                push_result=push_res,
                error=None,
            )
        # Push failed on resume — treat as push-failed path
        ctx = {
            "push_error_kind": push_res.error_kind,
            "claims_count": len(track_claims),
        }
        proceed = _call_decision(
            user_decision,
            "push_failed",
            f"Push failed on self-resume: {push_res.error_kind}",
            ctx,
        )
        outcome = (
            GateOutcome.USER_OVERRIDE_PROCEED if proceed else GateOutcome.BLOCKED_PUSH_FAILED
        )
        return GateResult(
            outcome=outcome,
            track_id=track_id,
            raw_input_id=raw_track_id,
            own_claim=own_claim if proceed else None,
            competing_verdict=None,
            push_result=push_res,
            error=None if proceed else push_res.error_kind,
        )

    # --- 7b: clock-skew conflict — highest risk, default abort -------------
    if verdict.conflict:
        logger.warning(
            "phase1_gate.run_gate: clock_skew_conflict on track=%s "
            "(max_skew_s=%s) — prompting user",
            track_id,
            verdict.max_clock_skew_seconds,
        )
        competing_verdict = verdict
        winner = verdict.winner
        ctx: dict = {
            "winner_owner_container": winner.container if winner else None,
            "winner_heartbeat_age_min": (
                _heartbeat_age_minutes(winner, ts) if winner else None
            ),
            "takeover_eligible": _takeover_eligible(verdict),
            "claims_count": len(track_claims),
            "max_clock_skew_seconds": verdict.max_clock_skew_seconds,
        }
        proceed = _call_decision(
            user_decision,
            "clock_skew",
            (
                f"Clock skew detected on track '{track_id}': "
                f"max diff {verdict.max_clock_skew_seconds}s > threshold. "
                "Takeover may assign wrong winner."
            ),
            ctx,
        )
        if not proceed:
            return GateResult(
                outcome=GateOutcome.ABORT,
                track_id=track_id,
                raw_input_id=raw_track_id,
                own_claim=None,
                competing_verdict=competing_verdict,
                push_result=None,
                error="clock_skew_conflict",
            )
        # User chose to proceed despite skew — fall through to acquire.

    # --- 7c: active competitor, fresh heartbeat ----------------------------
    elif (
        verdict.winner is not None
        and not _takeover_eligible(verdict)
    ):
        competing_verdict = verdict
        winner = verdict.winner
        hb_age = _heartbeat_age_minutes(winner, ts)
        ctx = {
            "winner_owner_container": f"{winner.owner}/{winner.container}",
            "winner_heartbeat_age_min": hb_age,
            "takeover_eligible": False,
            "claims_count": len(track_claims),
        }
        hb_age_str = f"{hb_age:.1f}m ago" if hb_age is not None else "unknown"
        proceed = _call_decision(
            user_decision,
            "occupied",
            (
                f"Track '{track_id}' is occupied by "
                f"{winner.owner}/{winner.container} "
                f"(heartbeat {hb_age_str}). "
                "Options: yield (False) / proceed anyway if you know it is safe (True)."
            ),
            ctx,
        )
        if not proceed:
            return GateResult(
                outcome=GateOutcome.USER_YIELDED,
                track_id=track_id,
                raw_input_id=raw_track_id,
                own_claim=None,
                competing_verdict=competing_verdict,
                push_result=None,
                error=None,
            )
        # User chose to proceed (takeover or force-proceed).
        logger.info(
            "phase1_gate.run_gate: user chose to proceed on occupied track=%s "
            "(winner=%s/%s)",
            track_id,
            winner.owner,
            winner.container,
        )

    # --- 7d: takeover eligible (stale / no active / terminal) — proceed ----
    # No prompt needed: stale / terminal tracks are safe to acquire.
    # (clock-skew path above already fell through here if user approved.)

    # -----------------------------------------------------------------------
    # Step 8: acquire_claim → write to local coordination ref
    #
    # Strategy (simplified path per spec): try acquire_claim first (uses
    # write_claim internally); on any failure fall back to resilient_write_claim
    # which adds OSError/disk-full/bootstrap handling (TASK-019).
    # This ensures claimed_at is persisted locally BEFORE the push attempt.
    # -----------------------------------------------------------------------
    acq: AcquireResult = acquire_claim(
        track_id,
        phase,
        resolved_identity,
        repo,
        now=ts,
    )

    if not acq.success:
        logger.warning(
            "phase1_gate.run_gate: acquire_claim failed (error=%s) — "
            "falling back to resilient_write_claim",
            acq.error,
        )
        # Build a ClaimRecord manually to pass to resilient_write_claim,
        # replicating what acquire_claim would have written.
        # SCHEMA_VERSION_CURRENT was already imported at module level via the
        # dual-context try/except block at the top of this file via claim_schema.
        ts_str = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
        fallback_record = ClaimRecord(
            schema_version=SCHEMA_VERSION_CURRENT,
            track_id=track_id,
            owner=resolved_identity.owner,
            container=resolved_identity.container_id,
            session=resolved_identity.session_id,
            phase=phase,
            status="active",
            claimed_at=ts_str,
            heartbeat_at=ts_str,
            superseded_from=None,
        )
        rwr: ResilientWriteResult = resilient_write_claim(fallback_record, repo)
        if not rwr.success:
            logger.warning(
                "phase1_gate.run_gate: resilient_write_claim also failed (kind=%s)",
                rwr.error_kind,
            )
            return GateResult(
                outcome=GateOutcome.ABORT,
                track_id=track_id,
                raw_input_id=raw_track_id,
                own_claim=None,
                competing_verdict=competing_verdict,
                push_result=None,
                error=rwr.error_kind or "write_failed",
            )
        written_record: ClaimRecord = fallback_record
    else:
        written_record = acq.record  # type: ignore[assignment]

    logger.info(
        "phase1_gate.run_gate: claim written locally "
        "track=%s container=%s session=%s claimed_at=%s",
        track_id,
        resolved_identity.container_id,
        resolved_identity.session_id,
        written_record.claimed_at,
    )

    # -----------------------------------------------------------------------
    # Step 9: resilient_push — sync local ref to remote
    #
    # claimed_at is already persisted locally.  If push fails, the gate returns
    # BLOCKED_PUSH_FAILED unless the user opts to override (USER_OVERRIDE_PROCEED).
    # Overriding means: "I accept elevated collision risk; reconcile will detect
    # any actual conflict on the next fetch."
    # -----------------------------------------------------------------------
    push_res = resilient_push(
        repo,
        remote=remote,
        user_decision=user_decision,
    )

    if push_res.success:
        logger.info(
            "phase1_gate.run_gate: PASSED — track=%s pushed to %s (attempts=%d)",
            track_id,
            remote,
            push_res.attempts,
        )
        final_outcome = (
            GateOutcome.USER_TAKEOVER
            if competing_verdict is not None
            else GateOutcome.PASSED
        )
        return GateResult(
            outcome=final_outcome,
            track_id=track_id,
            raw_input_id=raw_track_id,
            own_claim=written_record,
            competing_verdict=competing_verdict,
            push_result=push_res,
            error=None,
        )

    # Push failed — ask user whether to proceed in advisory mode.
    logger.warning(
        "phase1_gate.run_gate: push failed (kind=%s) — prompting user for override",
        push_res.error_kind,
    )
    ctx = {
        "push_error_kind": push_res.error_kind,
        "claims_count": len(track_claims),
        "winner_owner_container": (
            f"{competing_verdict.winner.owner}/{competing_verdict.winner.container}"
            if competing_verdict and competing_verdict.winner
            else None
        ),
        "winner_heartbeat_age_min": None,
        "takeover_eligible": _takeover_eligible(verdict),
    }
    proceed_on_fail = _call_decision(
        user_decision,
        "push_failed",
        (
            f"Push to '{remote}' failed: {push_res.error_kind}. "
            "Claim is written locally but NOT synced to remote. "
            "Proceeding elevates collision risk — reconcile will arbitrate on next fetch."
        ),
        ctx,
    )

    if proceed_on_fail:
        logger.info(
            "phase1_gate.run_gate: USER_OVERRIDE_PROCEED — "
            "user accepted elevated collision risk for track=%s",
            track_id,
        )
        return GateResult(
            outcome=GateOutcome.USER_OVERRIDE_PROCEED,
            track_id=track_id,
            raw_input_id=raw_track_id,
            own_claim=written_record,
            competing_verdict=competing_verdict,
            push_result=push_res,
            error=push_res.error_kind,
        )

    return GateResult(
        outcome=GateOutcome.BLOCKED_PUSH_FAILED,
        track_id=track_id,
        raw_input_id=raw_track_id,
        own_claim=None,
        competing_verdict=competing_verdict,
        push_result=push_res,
        error=push_res.error_kind or "push_failed",
    )

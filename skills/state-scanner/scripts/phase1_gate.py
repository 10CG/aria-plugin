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
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple, Optional

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
    from ..lib.constants import CLOCK_SKEW_WARN_THRESHOLD
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
    # Context (a): scripts/ imported directly (test harness / CLI entry).  The
    # lib/ modules cross-import each other with *relative* imports (from
    # .claim_schema ...), so they must be imported AS the ``lib`` package — not
    # as top-level modules off lib/ on sys.path (that breaks the intra-lib
    # relative imports with "no known parent package").  Add the skill root
    # (parent of lib/) to sys.path and import via the package, matching the
    # proven convention in tests/test_race_window.py.
    import sys as _sys
    from pathlib import Path as _Path
    _SKILL_ROOT = str(_Path(__file__).resolve().parent.parent)
    # Force skill root to the FRONT of sys.path (even if a lower-priority copy
    # already exists).  This guarantees the top-level name ``lib`` resolves to
    # Layer L's lib (state-scanner/lib) and NOT scripts/lib — the two packages
    # share the name ``lib`` (collector helpers vs Layer L; see
    # collectors/openspec.py:29).  Convention (repo-wide): top-level ``lib`` ==
    # Layer L; scripts/lib is only ever imported by bare module name
    # (carry_forward / spec_complete), so fronting skill root is collision-safe.
    while _SKILL_ROOT in _sys.path:
        _sys.path.remove(_SKILL_ROOT)
    _sys.path.insert(0, _SKILL_ROOT)
    from lib.claim_lifecycle import acquire_claim, AcquireResult  # type: ignore[import]
    from lib.claim_schema import ClaimRecord, SCHEMA_VERSION_CURRENT  # type: ignore[import]
    from lib.constants import CLOCK_SKEW_WARN_THRESHOLD  # type: ignore[import]
    from lib.coordination_ref import read_claims, ReadClaimsResult  # type: ignore[import]
    from lib.failure_handlers import (  # type: ignore[import]
        resilient_push,
        resilient_write_claim,
        health_check_fetch,
        ResilientPushResult,
        ResilientWriteResult,
        FetchHealth,
        UserDecisionCallback,
    )
    from lib.identity import Identity, get_identity  # type: ignore[import]
    from lib.reconcile import reconcile, ReconcileVerdict  # type: ignore[import]
    from lib.track_id import derive_track_id  # type: ignore[import]


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
    USER_OVERRIDE_PROCEED  — push failed but user chose to proceed (block mode).
    ADVISORY_PROCEED       — advisory mode force-proceeded past a would-block path
                             (occupied / clock_skew / push_failed).  A claim was
                             written (and pushed unless push itself failed) and a
                             surface marker is attached for the orchestration layer
                             to render (TASK-003/004).  Distinct from USER_* — no
                             operator interaction occurred; reconcile arbitrates.
    ABORT                  — unrecoverable error or user chose to abort entirely.
    """

    PASSED = "passed"
    BLOCKED_OCCUPIED = "blocked_occupied"
    BLOCKED_PUSH_FAILED = "blocked_push_failed"
    USER_YIELDED = "user_yielded"
    USER_TAKEOVER = "user_takeover"
    USER_OVERRIDE_PROCEED = "user_override_proceed"
    ADVISORY_PROCEED = "advisory_proceed"
    ABORT = "abort"


# ---------------------------------------------------------------------------
# AdvisorySurface — branch-differentiated warning payload (advisory mode)
# ---------------------------------------------------------------------------

@dataclass
class AdvisorySurface:
    """Warning payload attached to a GateResult when advisory mode force-proceeded
    past a path that would have aborted/yielded in block mode.

    R1-M1 / R2-Major-B: advisory 放行移除的只是 abort/yield **动作**, 不移除
    **告警面**.  The orchestration layer (state-scanner 阶段 2 推荐区) renders
    ``message`` as a 🔴 line so the collision stays visible + auditable
    (advisory-over-hardlock, DEC-20260519-001 #1).  reconcile remains the final
    arbiter; this surface never changes winner determination.

    kind values (branch-differentiated, NOT blanket-silenced):
      "occupied"    — 7c: another container holds a fresh active claim.
      "clock_skew"  — 7b: highest-risk path; ``max_clock_skew_seconds`` retained
                      so the operator can check container clock sync.
      "push_failed" — step 9 / self-resume: claim written locally but not synced.
    """

    kind: str
    message: str
    carry_id: Optional[str] = None            # copy-able canonical track_id (R1-m5)
    winner_owner_container: Optional[str] = None
    winner_heartbeat_age_min: Optional[float] = None
    max_clock_skew_seconds: Optional[float] = None
    push_error_kind: Optional[str] = None


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
    surface : AdvisorySurface | None
        Populated only when outcome == ADVISORY_PROCEED: the branch-differentiated
        warning the orchestration layer must render (TASK-004).  None on every
        block-mode path and on clean advisory passes with no competition.
    """

    outcome: str
    track_id: str
    raw_input_id: str
    own_claim: Optional[ClaimRecord]
    competing_verdict: Optional[ReconcileVerdict]
    push_result: Optional[ResilientPushResult]
    error: Optional[str]
    surface: Optional[AdvisorySurface] = None


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

def _run_gate_impl(
    raw_track_id: str,
    phase: str,
    *,
    repo_path: Optional[Path] = None,
    identity: Optional[Identity] = None,
    now: Optional[datetime] = None,
    user_decision: Optional[UserDecisionCallback] = None,
    remote: str = "origin",
    mode: str = "advisory",
) -> GateResult:
    """Execute Phase 1 acquisition gate for a single track selection.

    Internal implementation.  Callers use :func:`run_gate` (which wraps this with
    source-partitioned telemetry, TASK-011) or :func:`run_gate_synthetic`.

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
    mode:
        Outcome posture for would-block paths (7b clock_skew / 7c occupied /
        step 9 push_failed).  Default "advisory" (matches config default
        ``state_scanner.coordination.mode``, TASK-001).

        "advisory" (default) — advisory-over-hardlock: NEVER abort/yield on
          competition.  Force-proceed like the 7d takeover branch — write and
          push this session's own claim (step 8/9), and attach an
          :class:`AdvisorySurface` so the collision is rendered + auditable.
          Outcome == ADVISORY_PROCEED.  reconcile arbitrates on next fetch.
          ``user_decision`` is not consulted in this mode.
        "block" — legacy behaviour: consult ``user_decision`` and return
          ABORT / USER_YIELDED / BLOCKED_PUSH_FAILED on the respective paths.

        R1-M1: advisory 放行 **必须写 claim** — otherwise "reconcile 仍是最终
        仲裁" is vacuous (no second claim to arbitrate, no audit trail).
        R2-Major-B: advisory drops the abort *action*, NOT the warning *surface*;
        the 7b clock_skew signal is retained, not blanket-silenced.

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
    # advisory_surface is set only in advisory mode when a would-block path
    # (7b/7c/step9) is force-proceeded; it rides on the final GateResult so the
    # orchestration layer can render the warning (TASK-004).
    advisory_surface: Optional[AdvisorySurface] = None

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
        # Push failed on resume — treat as push-failed path.
        if mode == "advisory":
            # advisory: the local claim already exists (self-resume); proceed
            # and surface the push failure.
            return GateResult(
                outcome=GateOutcome.ADVISORY_PROCEED,
                track_id=track_id,
                raw_input_id=raw_track_id,
                own_claim=own_claim,
                competing_verdict=None,
                push_result=push_res,
                error=push_res.error_kind,
                surface=AdvisorySurface(
                    kind="push_failed",
                    message=(
                        f"self-resume push 失败 ({push_res.error_kind}) —— claim 已在"
                        "本地; advisory 放行, reconcile 下次 fetch 仲裁"
                    ),
                    carry_id=track_id,
                    push_error_kind=push_res.error_kind,
                ),
            )
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
        if mode == "advisory":
            # R2-Major-B: advisory drops the abort action, NOT the clock-skew
            # warning (this is the highest-risk path — silencing it here would
            # make advisory MORE dangerous than block).  Retain the skew signal.
            advisory_surface = AdvisorySurface(
                kind="clock_skew",
                message=(
                    f"⚠️ 时钟偏移 {verdict.max_clock_skew_seconds}s "
                    f"(> {CLOCK_SKEW_WARN_THRESHOLD}s 阈值) —— reconcile winner "
                    "判定可能有误, 请检查容器时钟同步"
                ),
                carry_id=track_id,
                winner_owner_container=(
                    f"{winner.owner}/{winner.container}" if winner else None
                ),
                max_clock_skew_seconds=verdict.max_clock_skew_seconds,
            )
            # fall through to acquire (step 8) — write + push our own claim.
        else:
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
        if mode == "advisory":
            # R1-M1/R1-m5: advisory proceeds and writes its own claim; surface
            # echoes the copy-able canonical carry-id so the operator can paste
            # it verbatim (reduces transcription drift).
            advisory_surface = AdvisorySurface(
                kind="occupied",
                message=(
                    f"{winner.owner}/{winner.container} {hb_age_str} 已认领 "
                    f"{track_id}"
                ),
                carry_id=track_id,
                winner_owner_container=f"{winner.owner}/{winner.container}",
                winner_heartbeat_age_min=hb_age,
            )
            logger.info(
                "phase1_gate.run_gate: advisory proceed on occupied track=%s "
                "(winner=%s/%s) — writing own claim, reconcile will arbitrate",
                track_id,
                winner.owner,
                winner.container,
            )
            # fall through to acquire (step 8).
        else:
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
        if advisory_surface is not None:
            # advisory force-proceeded past 7b/7c — claim written + pushed;
            # surface rides along for the orchestration layer to render.
            final_outcome = GateOutcome.ADVISORY_PROCEED
        elif competing_verdict is not None:
            final_outcome = GateOutcome.USER_TAKEOVER
        else:
            final_outcome = GateOutcome.PASSED
        return GateResult(
            outcome=final_outcome,
            track_id=track_id,
            raw_input_id=raw_track_id,
            own_claim=written_record,
            competing_verdict=competing_verdict,
            push_result=push_res,
            error=None,
            surface=advisory_surface,
        )

    # Push failed — claim is already written locally.
    if mode == "advisory":
        # advisory: proceed with elevated collision risk; surface the failure
        # so it stays visible.  reconcile arbitrates on the next fetch.
        logger.warning(
            "phase1_gate.run_gate: push failed (kind=%s) — advisory proceed "
            "(claim written locally, not synced)",
            push_res.error_kind,
        )
        _push_note = (
            f"; 且 push 到 '{remote}' 失败 ({push_res.error_kind}) —— claim 已写本地"
            "未同步远端 (撞车风险升高)"
        )
        if advisory_surface is not None:
            # COMPOSITE path (7b clock_skew / 7c occupied then push also failed):
            # AUGMENT the existing surface — do NOT overwrite it (audit Critical:
            # a blanket kind=push_failed surface would silently drop the
            # max_clock_skew_seconds / winner signal on the most dangerous path,
            # re-breaking R2-Major-B).  Keep kind + skew/winner; append push info.
            advisory_surface = replace(
                advisory_surface,
                message=advisory_surface.message + _push_note,
                push_error_kind=push_res.error_kind,
            )
        else:
            # Clean step 9 (no prior competition) — this IS a pure push failure.
            advisory_surface = AdvisorySurface(
                kind="push_failed",
                message=(
                    f"push 到 '{remote}' 失败 ({push_res.error_kind}) —— claim 已写本地"
                    "未同步远端; advisory 放行, reconcile 下次 fetch 仲裁 (撞车风险升高)"
                ),
                carry_id=track_id,
                push_error_kind=push_res.error_kind,
            )
        return GateResult(
            outcome=GateOutcome.ADVISORY_PROCEED,
            track_id=track_id,
            raw_input_id=raw_track_id,
            own_claim=written_record,
            competing_verdict=competing_verdict,
            push_result=push_res,
            error=push_res.error_kind,
            surface=advisory_surface,
        )

    # block mode — ask user whether to proceed despite the push failure.
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


# ---------------------------------------------------------------------------
# Telemetry (TASK-011 — source-partitioned, structural anti-spoof)
#
# run_gate() is wrapped so every non-abort outcome appends one JSONL record.
# The partition (which file) is chosen STRUCTURALLY from `source`, not from a
# self-reported field a caller can forge (R2-Major-C):
#   source == "production"  → .aria/coordination-telemetry.jsonl        (probe reads THIS only)
#   source == "harness"     → .aria/coordination-telemetry-nonprod.jsonl (run_gate_synthetic)
#   source is None (lib/pytest direct call) → nonprod file               (NEVER production)
# Only ONE call site passes source="production": the CLI _main (the AI
# orchestration layer's entry).  A harness/library call therefore CANNOT append
# to the production partition — TASK-012's probe reads only the production file.
# ---------------------------------------------------------------------------

_PRODUCTION_SOURCE = "production"
_HARNESS_SOURCE = "harness"
_PROD_TELEMETRY_FILE = "coordination-telemetry.jsonl"
_NONPROD_TELEMETRY_FILE = "coordination-telemetry-nonprod.jsonl"


def _telemetry_path(repo: Path, source: Optional[str]) -> Path:
    """Return the source-partitioned telemetry file (structural, not spoofable)."""
    fname = _PROD_TELEMETRY_FILE if source == _PRODUCTION_SOURCE else _NONPROD_TELEMETRY_FILE
    return repo / ".aria" / fname


def _emit_telemetry(
    repo: Path,
    result: GateResult,
    source: Optional[str],
    ts: datetime,
    latency_ms: int,
) -> None:
    """Append one telemetry record.  NEVER raises (telemetry must not break the
    gate) and SKIPS abort outcomes (not a coordination observation)."""
    if result.outcome == GateOutcome.ABORT:
        return
    try:
        import json as _json

        record = {
            "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": source or "library",  # structural partition tag (non-spoofable default)
            "arm": "manual",  # run_gate is the P1 live arm (TASK-014); auto/semi pending
            "outcome": result.outcome,
            "track_id": result.track_id,
            "claim_written": result.own_claim is not None,
            "collision_surfaced": result.surface is not None,
            "surface_kind": result.surface.kind if result.surface is not None else None,
            "latency_ms": latency_ms,
        }
        path = _telemetry_path(repo, source)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(_json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:  # pragma: no cover — defensive; telemetry is best-effort
        logger.debug("phase1_gate: telemetry emit skipped (%s)", exc)


def _gated(
    raw_track_id: str,
    phase: str,
    *,
    repo_path: Optional[Path] = None,
    identity: Optional[Identity] = None,
    now: Optional[datetime] = None,
    user_decision: Optional[UserDecisionCallback] = None,
    remote: str = "origin",
    mode: str = "advisory",
    _source: Optional[str] = None,
) -> GateResult:
    """PRIVATE telemetry-wrapping entry.  ``_source`` selects the telemetry
    partition and is intentionally NOT exposed on the public :func:`run_gate`
    signature (audit REVISE, telemetry-antispoof Important): the production
    partition ("production") is therefore reachable ONLY from this private
    function, which just ONE call site — the CLI :func:`_main` — invokes with
    ``_source="production"``.  Public callers (:func:`run_gate`) can only ever
    write the non-production partition, closing the "any caller can pass
    source=production" spoof hole (spec proposal.md:264 结构性不可调用方覆盖).
    Delegates the 9-step gate logic to :func:`_run_gate_impl`."""
    import time as _time

    repo: Path = repo_path if repo_path is not None else Path.cwd()
    ts: datetime = now if now is not None else datetime.now(timezone.utc)
    t0 = _time.monotonic()
    result = _run_gate_impl(
        raw_track_id,
        phase,
        repo_path=repo,
        identity=identity,
        now=ts,
        user_decision=user_decision,
        remote=remote,
        mode=mode,
    )
    latency_ms = int((_time.monotonic() - t0) * 1000)
    _emit_telemetry(repo, result, _source, ts, latency_ms)
    return result


def run_gate(
    raw_track_id: str,
    phase: str,
    *,
    repo_path: Optional[Path] = None,
    identity: Optional[Identity] = None,
    now: Optional[datetime] = None,
    user_decision: Optional[UserDecisionCallback] = None,
    remote: str = "origin",
    mode: str = "advisory",
) -> GateResult:
    """Public entry — runs the acquisition gate and records telemetry to the
    NON-production partition (library/direct-call source).

    There is intentionally NO ``source`` parameter: production telemetry is
    written only by the CLI production path (:func:`_main` → :func:`_gated`
    with ``_source="production"``), so no public/library/test caller can inflate
    the production partition the TASK-012 probe reads.  See :func:`_run_gate_impl`
    for the full 9-step semantic contract and mode behaviour.
    """
    return _gated(
        raw_track_id,
        phase,
        repo_path=repo_path,
        identity=identity,
        now=now,
        user_decision=user_decision,
        remote=remote,
        mode=mode,
        _source=None,
    )


def run_gate_synthetic(raw_track_id: str, phase: str, **kwargs) -> GateResult:
    """Harness-only entry (consumed by the TASK-013 AB harness).

    Routes to the "harness" telemetry partition — never production.  ``_source``
    is forced here and cannot be overridden by callers.  Do NOT use in
    production — the AI orchestration layer calls the CLI instead.
    """
    kwargs.pop("_source", None)  # harness may not override the partition
    kwargs.pop("source", None)  # defend against stale callers using the old kwarg
    return _gated(raw_track_id, phase, _source=_HARNESS_SOURCE, **kwargs)


# ---------------------------------------------------------------------------
# CLI entry (TASK-002 — completes TASK-024 integration)
#
# run_gate is a pure library function; the AI orchestration layer (state-scanner
# 阶段 2 推荐 / Phase B-entry) has no way to call it except via subprocess.  This
# CLI is the stable, Bash-invocable contract that finally wires run_gate into
# production (layer-l-integration.md:15 Design A — gate runs at Phase B entry,
# NOT inside scan.py).  It is also the stitch point exercised by TASK-005(d).
#
# Contract:
#   stdin : none
#   args  : --raw-track-id --phase [--mode advisory|block] [--repo-path] [--remote]
#   stdout: single JSON object (GateResult projection; see _gate_result_to_dict)
#   exit  : 0 when the AI may proceed to Phase B (passed / advisory_proceed /
#           user_takeover / user_override_proceed); 1 otherwise (yield / block /
#           abort).  Errors in argument parsing exit 2 (argparse default).
#
# Known limitation (PP-R2): the CLI is designed for advisory mode.  A single
# JSON round-trip cannot carry a live user_decision callback, so mode=block via
# the CLI degrades interactive decision points to user_decision=None (safe
# default = abort).  Interactive block-mode is out of scope for this Spec;
# production default is advisory, and block's interactive paths are covered by
# TASK-005(a) function-level tests, not the CLI.
#
# NOTE (PP-R4 / TASK-011): this CLI is the single production call site — it
# passes source="production" so telemetry lands in the partition the TASK-012
# probe reads.  No other caller passes "production" (run_gate_synthetic forces
# "harness"; library/pytest calls default to None → non-production).
# ---------------------------------------------------------------------------

# Outcomes from which the AI orchestration layer may proceed into Phase B.
_PROCEED_OUTCOMES = frozenset(
    {
        GateOutcome.PASSED,
        GateOutcome.ADVISORY_PROCEED,
        GateOutcome.USER_TAKEOVER,
        GateOutcome.USER_OVERRIDE_PROCEED,
    }
)


def _claim_to_dict(claim: Optional[ClaimRecord]) -> Optional[dict]:
    """Project a ClaimRecord to a JSON-safe dict (no secrets; identity + timing)."""
    if claim is None:
        return None
    return {
        "track_id": claim.track_id,
        "owner": claim.owner,
        "container": claim.container,
        "session": claim.session,
        "phase": claim.phase,
        "status": claim.status,
        "claimed_at": claim.claimed_at,
    }


def _gate_result_to_dict(result: GateResult) -> dict:
    """Project a GateResult into the JSON contract consumed by the orchestration
    layer (state-scanner 阶段 2).  Surfaces the branch-differentiated warning so
    the recommendation region can render 🔴 without re-deriving it (TASK-004)."""
    surface: Optional[dict] = None
    if result.surface is not None:
        s = result.surface
        surface = {
            "kind": s.kind,
            "message": s.message,
            "carry_id": s.carry_id,
            "winner_owner_container": s.winner_owner_container,
            "winner_heartbeat_age_min": s.winner_heartbeat_age_min,
            "max_clock_skew_seconds": s.max_clock_skew_seconds,
            "push_error_kind": s.push_error_kind,
        }
    competing_winner: Optional[dict] = None
    if (
        result.competing_verdict is not None
        and result.competing_verdict.winner is not None
    ):
        w = result.competing_verdict.winner
        competing_winner = {"owner": w.owner, "container": w.container}
    return {
        "outcome": result.outcome,
        "proceed": result.outcome in _PROCEED_OUTCOMES,
        "track_id": result.track_id,
        "raw_input_id": result.raw_input_id,
        "error": result.error,
        "own_claim": _claim_to_dict(result.own_claim),
        "competing_winner": competing_winner,
        "surface": surface,
        "push_success": (
            result.push_result.success if result.push_result is not None else None
        ),
    }


def _main(argv: Optional[list[str]] = None) -> int:
    """CLI entry — see module-level CLI contract above."""
    import argparse
    import json

    parser = argparse.ArgumentParser(
        prog="phase1_gate",
        description=(
            "Layer L 急切认领闸门 CLI — AI 编排层在用户确认进 Phase B 时调用 "
            "(advisory 编排层接线; 完成 multi-terminal-coordination TASK-024)"
        ),
    )
    parser.add_argument(
        "--raw-track-id",
        required=True,
        help="用户选定的 carry-id 原始串 (未归一; run_gate 内部 derive_track_id 归一)",
    )
    parser.add_argument(
        "--phase", required=True, help="当前十步循环 phase (如 B / B.1), 写入 claim"
    )
    parser.add_argument(
        "--mode",
        default="advisory",
        choices=["advisory", "block"],
        help="outcome 姿态; 默认 advisory (放行+写推 claim+surface)。见 CLI 已知限制",
    )
    parser.add_argument("--repo-path", default=None, help="仓库根路径 (默认 cwd)")
    parser.add_argument("--remote", default="origin", help="git remote (默认 origin)")
    args = parser.parse_args(argv)

    repo = Path(args.repo_path) if args.repo_path else Path.cwd()
    # This is the ONE production call site — it invokes the PRIVATE _gated with
    # _source="production" (the public run_gate has no source param, so no other
    # caller can reach the production partition — audit telemetry-antispoof fix).
    result = _gated(
        args.raw_track_id,
        args.phase,
        repo_path=repo,
        remote=args.remote,
        mode=args.mode,
        _source=_PRODUCTION_SOURCE,
        # user_decision omitted — advisory ignores it; block via CLI degrades to
        # the None safe-default (abort) per the documented PP-R2 limitation.
    )
    print(json.dumps(_gate_result_to_dict(result), ensure_ascii=False, indent=2))
    return 0 if result.outcome in _PROCEED_OUTCOMES else 1


if __name__ == "__main__":
    import sys as _sys

    _sys.exit(_main())

"""TASK-005 — P1 golden tests for run_gate advisory mode (DEC-20260704-002).

These are the FIRST direct tests of the run_gate orchestrator.  Prior to
DEC-002 run_gate had zero production callers AND zero direct unit tests
(dead code on arrival, aria-plugin #95 / mother-spec TASK-024 never wired).

Coverage (maps to detailed-tasks.yaml TASK-005 verification bullets):
  (a) advisory outcome mapping — occupied(7c) / clock_skew(7b) / push_fail(step9)
      all PROCEED with own_claim != None and a real acquire_claim + push call,
      returning outcome=ADVISORY_PROCEED + an AdvisorySurface.
  (b) reconcile determinism is unaffected by mode (real reconcile drives both).
  (c) block mode preserves the legacy abort/yield/block semantics.
  (d) CLI stitch — g._main(argv) exercises the argparse → run_gate → JSON
      projection contract (TASK-002), the sole coupling point between the AI
      orchestration layer and run_gate.
  (e) advisory 7b still exposes max_clock_skew_seconds (not blanket-silenced).
  (f) default-mode lock-in — calling run_gate WITHOUT `mode` proceeds (advisory),
      guarding the warn→advisory default (feedback_default_value_flip_needs_lock_in_test).

Note on "(c) coordination.enabled off → zero call": that invariant lives at the
orchestration layer (state-scanner SKILL.md decides whether to invoke the CLI at
all); run_gate has no `enabled` param, so "not called" cannot be asserted here.
It is covered by the SKILL.md contract + TASK-010 back-compat tests.

Strategy: mock the six git-touching module boundaries on `phase1_gate`
(_is_git_repo / health_check_fetch / read_claims / acquire_claim /
resilient_push) — reconcile stays REAL so the 7b/7c decision is genuinely
exercised.  No real git, no network.

Spec: openspec/changes/interactive-session-dedup-coordination
Task: TASK-005
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

# Path bootstrap — scripts/ for phase1_gate, skill root for Layer L `lib`.
# Order matters: skill root MUST precede scripts/ so top-level `lib` resolves to
# Layer L's lib (state-scanner/lib), not scripts/lib (collector helpers, which
# share the name).  Insert scripts first, then skill root, so skill root lands
# at sys.path[0].  (phase1_gate's import fallback also enforces this, but we keep
# the test self-consistent for its own top-level `from lib.*` imports below.)
_SKILL_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _SKILL_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

import phase1_gate as g  # noqa: E402
from lib.claim_schema import ClaimRecord  # noqa: E402
from lib.identity import Identity  # noqa: E402
from lib.failure_handlers import FetchHealth, ResilientPushResult  # noqa: E402
from lib.coordination_ref import ReadClaimsResult  # noqa: E402
from lib.claim_lifecycle import AcquireResult  # noqa: E402

_NOW = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)
_ME = Identity(owner="me", container_id="cA", session_id="s-me")
_TRACK = "carry-dedup-golden"

# Sentinel to distinguish "mode omitted" (default lock-in test) from an explicit
# value, since None is not a valid mode.
_OMIT = object()


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _claim(
    owner: str,
    container: str,
    claimed_at: datetime,
    *,
    heartbeat_at: datetime | None = None,
    track_id: str = _TRACK,
    status: str = "active",
    session: str = "s-x",
    phase: str = "B",
) -> ClaimRecord:
    ts = _iso(claimed_at)
    hb = _iso(heartbeat_at or claimed_at)
    return ClaimRecord(
        schema_version="1",
        track_id=track_id,
        owner=owner,
        container=container,
        session=session,
        phase=phase,
        status=status,
        claimed_at=ts,
        heartbeat_at=hb,
        superseded_from=None,
    )


def _our_written_claim() -> ClaimRecord:
    return _claim("me", "cA", _NOW, session="s-me")


@contextlib.contextmanager
def _boundaries(
    *,
    claims: list[ClaimRecord],
    push_success: bool = True,
    acquire_success: bool = True,
):
    """Patch the six git-touching boundaries; reconcile stays real."""
    fetch = FetchHealth(
        success=True,
        partial_fetch=False,
        ref_sha_before="a" * 40,
        ref_sha_after="a" * 40,
        error_kind=None,
        error_msg=None,
    )
    rc = ReadClaimsResult(claims=list(claims), errors=[], ref_exists=True)
    acq = AcquireResult(
        success=acquire_success,
        record=_our_written_claim() if acquire_success else None,
        error=None if acquire_success else "write_failed",
    )
    push = ResilientPushResult(
        success=push_success,
        final_push_result=None,
        attempts=1,
        triggered_fetch_replay=False,
        bootstrap_triggered=False,
        error_kind=None if push_success else "non_ff_exhausted",
        error_msg=None,
        user_aborted=False,
    )
    push_mock = mock.Mock(return_value=push)
    acquire_mock = mock.Mock(return_value=acq)
    with mock.patch.object(g, "_is_git_repo", return_value=True), mock.patch.object(
        g, "health_check_fetch", return_value=fetch
    ), mock.patch.object(g, "read_claims", return_value=rc), mock.patch.object(
        g, "acquire_claim", acquire_mock
    ), mock.patch.object(
        g, "resilient_push", push_mock
    ):
        yield {"acquire": acquire_mock, "push": push_mock}


def _run(claims, mode=_OMIT, *, push_success=True, acquire_success=True, user_decision=None):
    # Real tempdir as repo_path so run_gate's telemetry emission (TASK-011) is
    # isolated + auto-cleaned (source=None → non-production partition).
    with tempfile.TemporaryDirectory() as td:
        kwargs = dict(
            repo_path=Path(td),
            identity=_ME,
            now=_NOW,
            user_decision=user_decision,
        )
        if mode is not _OMIT:
            kwargs["mode"] = mode
        with _boundaries(
            claims=claims, push_success=push_success, acquire_success=acquire_success
        ) as mocks:
            result = g.run_gate(_TRACK, "B", **kwargs)
    return result, mocks


class TestAdvisoryOccupied(unittest.TestCase):
    """(a) 7c occupied — advisory proceeds, writes + pushes own claim."""

    def test_advisory_occupied_proceeds_and_writes_claim(self):
        competitor = _claim("other", "cB", _NOW, heartbeat_at=_NOW)  # fresh → not takeover-eligible
        result, mocks = _run([competitor], mode="advisory")
        self.assertEqual(result.outcome, g.GateOutcome.ADVISORY_PROCEED)
        self.assertIsNotNone(result.own_claim, "advisory MUST write a claim (R1-M1)")
        self.assertIsNotNone(result.surface)
        self.assertEqual(result.surface.kind, "occupied")
        self.assertEqual(result.surface.carry_id, _TRACK, "copy-able carry-id echoed (R1-m5)")
        self.assertIn("other/cB", result.surface.message)
        #真调 acquire_claim + push (not just returned a marker)
        mocks["acquire"].assert_called_once()
        mocks["push"].assert_called_once()

    def test_block_occupied_yields_on_user_false(self):
        """(c) block mode preserves legacy yield semantics."""
        competitor = _claim("other", "cB", _NOW, heartbeat_at=_NOW)
        result, mocks = _run(
            [competitor], mode="block", user_decision=lambda *_: False
        )
        self.assertEqual(result.outcome, g.GateOutcome.USER_YIELDED)
        self.assertIsNone(result.own_claim)
        self.assertIsNone(result.surface)
        mocks["acquire"].assert_not_called()


class TestAdvisoryClockSkew(unittest.TestCase):
    """(a)+(e) 7b clock_skew — advisory proceeds but RETAINS the skew warning."""

    def _skewed_claims(self):
        # Two active fresh claims 60s apart → reconcile conflict=True (>30s).
        c1 = _claim("other", "cB", datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc), heartbeat_at=_NOW)
        c2 = _claim("third", "cC", datetime(2026, 7, 4, 12, 1, 0, tzinfo=timezone.utc), heartbeat_at=_NOW, session="s-c")
        return [c1, c2]

    def test_advisory_clock_skew_proceeds_with_warning_retained(self):
        result, _ = _run(self._skewed_claims(), mode="advisory")
        self.assertEqual(result.outcome, g.GateOutcome.ADVISORY_PROCEED)
        self.assertIsNotNone(result.surface)
        self.assertEqual(result.surface.kind, "clock_skew")
        # (e) the highest-risk signal must survive advisory (not blanket-silenced).
        self.assertIsNotNone(
            result.surface.max_clock_skew_seconds,
            "advisory 7b MUST retain max_clock_skew_seconds (R2-Major-B)",
        )
        self.assertGreater(result.surface.max_clock_skew_seconds, 30)

    def test_block_clock_skew_aborts_on_user_false(self):
        """(c) block mode still aborts the highest-risk path on user reject."""
        result, _ = _run(
            self._skewed_claims(), mode="block", user_decision=lambda *_: False
        )
        self.assertEqual(result.outcome, g.GateOutcome.ABORT)
        self.assertEqual(result.error, "clock_skew_conflict")


class TestAdvisoryPushFailed(unittest.TestCase):
    """(a) step 9 push failure — advisory proceeds; claim written locally."""

    def test_advisory_push_fail_proceeds_with_surface(self):
        result, mocks = _run([], mode="advisory", push_success=False)  # no competition
        self.assertEqual(result.outcome, g.GateOutcome.ADVISORY_PROCEED)
        self.assertIsNotNone(result.own_claim, "claim written locally before push")
        self.assertIsNotNone(result.surface)
        self.assertEqual(result.surface.kind, "push_failed")
        self.assertEqual(result.surface.push_error_kind, "non_ff_exhausted")
        self.assertEqual(result.error, "non_ff_exhausted")
        mocks["push"].assert_called_once()

    def test_block_push_fail_blocks_on_user_false(self):
        """(c) block mode returns BLOCKED_PUSH_FAILED when user declines."""
        result, _ = _run(
            [], mode="block", push_success=False, user_decision=lambda *_: False
        )
        self.assertEqual(result.outcome, g.GateOutcome.BLOCKED_PUSH_FAILED)
        self.assertIsNone(result.own_claim)

    def test_advisory_self_resume_push_fail_proceeds(self):
        """7a self-resume + push fail — advisory proceeds; independent push_failed
        surface (no prior competition surface to augment)."""
        # A claim by OUR identity (owner=me/container=cA/session=s-me) → self-resume.
        own = _claim("me", "cA", _NOW, heartbeat_at=_NOW, session="s-me")
        result, _ = _run([own], mode="advisory", push_success=False)
        self.assertEqual(result.outcome, g.GateOutcome.ADVISORY_PROCEED)
        self.assertIsNotNone(result.own_claim, "self-resume keeps the existing claim")
        self.assertIsNotNone(result.surface)
        self.assertEqual(result.surface.kind, "push_failed")
        self.assertEqual(result.surface.push_error_kind, "non_ff_exhausted")


class TestAdvisoryCompositePaths(unittest.TestCase):
    """Composite 7b/7c + push-fail — the augment (not overwrite) fix.

    Audit Critical/Important: when a collision path (clock_skew / occupied)
    ALSO hits a push failure, the surface must be AUGMENTED, not replaced by a
    blanket kind=push_failed that silently drops the skew/winner signal.
    """

    def _skewed(self):
        c1 = _claim("other", "cB", datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc), heartbeat_at=_NOW)
        c2 = _claim("third", "cC", datetime(2026, 7, 4, 12, 1, 0, tzinfo=timezone.utc), heartbeat_at=_NOW, session="s-c")
        return [c1, c2]

    def test_clock_skew_then_push_fail_retains_skew(self):
        result, _ = _run(self._skewed(), mode="advisory", push_success=False)
        self.assertEqual(result.outcome, g.GateOutcome.ADVISORY_PROCEED)
        self.assertIsNotNone(result.surface)
        self.assertEqual(result.surface.kind, "clock_skew", "must NOT be overwritten to push_failed")
        self.assertIsNotNone(
            result.surface.max_clock_skew_seconds,
            "composite path MUST retain the skew signal (audit Critical)",
        )
        self.assertEqual(result.surface.push_error_kind, "non_ff_exhausted", "push info augmented")
        self.assertIn("push", result.surface.message)

    def test_occupied_then_push_fail_retains_occupied(self):
        competitor = _claim("other", "cB", _NOW, heartbeat_at=_NOW)
        result, _ = _run([competitor], mode="advisory", push_success=False)
        self.assertEqual(result.outcome, g.GateOutcome.ADVISORY_PROCEED)
        self.assertIsNotNone(result.surface)
        self.assertEqual(result.surface.kind, "occupied", "must NOT be overwritten to push_failed")
        self.assertEqual(result.surface.winner_owner_container, "other/cB", "winner retained")
        self.assertEqual(result.surface.push_error_kind, "non_ff_exhausted", "push info augmented")


class TestCleanAdvisoryPass(unittest.TestCase):
    """No competition — advisory yields a plain PASSED (surface=None)."""

    def test_no_competition_is_plain_passed(self):
        result, _ = _run([], mode="advisory")
        self.assertEqual(result.outcome, g.GateOutcome.PASSED)
        self.assertIsNone(result.surface)
        self.assertIsNotNone(result.own_claim)


class TestDefaultModeLockIn(unittest.TestCase):
    """(f) omitting `mode` must behave as advisory (default flip lock-in)."""

    def test_default_mode_proceeds_not_aborts(self):
        competitor = _claim("other", "cB", _NOW, heartbeat_at=_NOW)
        result, _ = _run([competitor])  # NOTE: mode omitted entirely
        self.assertEqual(
            result.outcome,
            g.GateOutcome.ADVISORY_PROCEED,
            "unset mode must default to advisory, not block/abort",
        )
        self.assertIsNotNone(result.own_claim)


class TestCliStitch(unittest.TestCase):
    """(d) CLI stitch — argparse → run_gate → JSON projection contract."""

    def test_cli_advisory_occupied_json_contract(self):
        # The CLI entry does NOT inject now/identity (production entry by design),
        # so build a competitor fresh w.r.t. real time (else it reads as stale →
        # takeover-eligible → plain PASSED) and pin identity deterministically.
        now_real = datetime.now(timezone.utc)
        competitor = _claim("other", "cB", now_real, heartbeat_at=now_real)
        with tempfile.TemporaryDirectory() as td:
            argv = [
                "--raw-track-id",
                _TRACK,
                "--phase",
                "B",
                "--mode",
                "advisory",
                "--repo-path",
                td,
            ]
            buf = io.StringIO()
            with _boundaries(claims=[competitor]), mock.patch.object(
                g, "get_identity", return_value=_ME
            ):
                with contextlib.redirect_stdout(buf):
                    exit_code = g._main(argv)
        payload = json.loads(buf.getvalue())
        self.assertEqual(exit_code, 0, "advisory proceed → exit 0")
        self.assertEqual(payload["outcome"], "advisory_proceed")
        self.assertTrue(payload["proceed"])
        self.assertEqual(payload["track_id"], _TRACK)
        self.assertIsNotNone(payload["own_claim"])
        self.assertEqual(payload["own_claim"]["owner"], "me")
        self.assertIsNotNone(payload["surface"])
        self.assertEqual(payload["surface"]["kind"], "occupied")
        self.assertEqual(payload["surface"]["carry_id"], _TRACK)
        self.assertEqual(payload["competing_winner"], {"owner": "other", "container": "cB"})

    def test_cli_non_git_repo_aborts_exit1(self):
        """Real code path (no mocks): non-git dir → abort JSON, exit 1, no network."""
        import subprocess

        proc = subprocess.run(
            [
                sys.executable,
                str(_SCRIPTS / "phase1_gate.py"),
                "--raw-track-id",
                _TRACK,
                "--phase",
                "B",
                "--repo-path",
                "/tmp",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 1)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["outcome"], "abort")
        self.assertEqual(payload["error"], "not_a_git_repo")


if __name__ == "__main__":
    unittest.main()

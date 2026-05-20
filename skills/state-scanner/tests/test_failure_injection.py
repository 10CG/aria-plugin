"""TASK-022 — P2 Round 7: Failure Injection Matrix Tests for failure_handlers.py.

Covers all 7 failure paths mandated by tasks.md §2.10 (3):

    (a) push non-ff       → fetch-replay-repush, up to max_retries cycles
    (b) push 401/403      → no retry; warn + user_decision callback
    (c) push other fail   → call user_decision; user_aborted flag set/unset
    (d) orphan ref absent → auto-bootstrap before write
    (e) disk full / OSErr → warn + skip claim, non-crashing; success=False
    (f) partial fetch     → ref SHA regression detected; partial_fetch=True
    (g) clock-skew        → CLOCK_SKEW_WARN_THRESHOLD=30 exported constant

Strategy: all 7 git subprocess calls are mock-patched at the lib.failure_handlers
or lib.coordination_ref module boundary; no real git commands are executed.

Spec: openspec/changes/multi-terminal-coordination/tasks.md §2.10
Task: TASK-022 (P2 Round 7)
Deps: TASK-019 (failure_handlers.py — the SUT)
"""

from __future__ import annotations

import errno
import sys
import unittest
from pathlib import Path
from unittest import mock

# ---------------------------------------------------------------------------
# Path bootstrap — make 'lib' importable as a package when run from the
# state-scanner/ directory:  python3 -m unittest tests.test_failure_injection
# ---------------------------------------------------------------------------
_SKILL_ROOT = Path(__file__).resolve().parent.parent   # .../state-scanner/
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

from lib.failure_handlers import (  # noqa: E402  (after sys.path fixup)
    CLOCK_SKEW_WARN_THRESHOLD,
    FetchHealth,
    NON_FF_MAX_RETRIES,
    ResilientPushResult,
    ResilientWriteResult,
    UserDecisionCallback,
    health_check_fetch,
    resilient_push,
    resilient_write_claim,
)
from lib.coordination_ref import (  # noqa: E402
    BootstrapResult,
    FetchResult,
    PushResult,
    WriteClaimResult,
)

# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------

_FAKE_REPO = Path("/tmp/fake-repo")


def _make_claim_record():
    """Return a minimal ClaimRecord fixture (no real YAML needed)."""
    from lib.claim_schema import ClaimRecord  # noqa: PLC0415

    return ClaimRecord(
        schema_version="1",
        track_id="t-abc",
        owner="tester",
        container="devbox-A",
        session="s-test001",
        phase="B.2",
        status="active",
        claimed_at="2026-01-01T00:00:00+00:00",
        heartbeat_at="2026-01-01T00:00:00+00:00",
        superseded_from=None,
    )


# ---------------------------------------------------------------------------
# Case (a): push non-ff → fetch-replay-repush
# ---------------------------------------------------------------------------


class TestCaseA_NonFfFetchReplay(unittest.TestCase):
    """case (a): non-ff push triggers fetch-replay-repush loop."""

    @mock.patch("lib.failure_handlers.time")
    @mock.patch("lib.failure_handlers.health_check_fetch")
    @mock.patch("lib.failure_handlers.push_coordination_ref")
    def test_non_ff_eventually_succeeds(self, mock_push, mock_hcf, mock_time):
        """Two non-ff failures then success; triggered_fetch_replay=True, attempts=3."""
        mock_push.side_effect = [
            PushResult(False, "non_ff", "Updates were rejected"),
            PushResult(False, "non_ff", "Updates were rejected"),
            PushResult(True, None, None),
        ]
        mock_hcf.return_value = FetchHealth(
            success=True,
            partial_fetch=False,
            ref_sha_before="abc",
            ref_sha_after="def",
            error_kind=None,
            error_msg=None,
        )

        result = resilient_push(
            repo_path=_FAKE_REPO,
            max_retries=2,
            user_decision=None,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.attempts, 3)
        self.assertTrue(result.triggered_fetch_replay)
        self.assertIsNone(result.error_kind)
        self.assertEqual(mock_hcf.call_count, 2)

    @mock.patch("lib.failure_handlers.time")
    @mock.patch("lib.failure_handlers.health_check_fetch")
    @mock.patch("lib.failure_handlers.push_coordination_ref")
    def test_non_ff_exhausts_retries(self, mock_push, mock_hcf, mock_time):
        """All push attempts non-ff → max_retries_exhausted."""
        mock_push.return_value = PushResult(False, "non_ff", "Updates were rejected")
        mock_hcf.return_value = FetchHealth(
            success=True,
            partial_fetch=False,
            ref_sha_before="abc",
            ref_sha_after="def",
            error_kind=None,
            error_msg=None,
        )

        result = resilient_push(
            repo_path=_FAKE_REPO,
            max_retries=2,
            user_decision=None,
        )

        self.assertFalse(result.success)
        self.assertEqual(result.error_kind, "max_retries_exhausted")
        # max_retries=2 → 3 total attempts
        self.assertEqual(result.attempts, 3)
        self.assertTrue(result.triggered_fetch_replay)

    @mock.patch("lib.failure_handlers.time")
    @mock.patch("lib.failure_handlers.health_check_fetch")
    @mock.patch("lib.failure_handlers.push_coordination_ref")
    def test_non_ff_fetch_replay_fails_mid_retry(self, mock_push, mock_hcf, mock_time):
        """health_check_fetch fails during retry → fetch_replay_failed (not exhausted)."""
        mock_push.return_value = PushResult(False, "non_ff", "rejected")
        mock_hcf.return_value = FetchHealth(
            success=False,
            partial_fetch=True,
            ref_sha_before="abc",
            ref_sha_after="abc",
            error_kind="network",
            error_msg="Connection refused",
        )

        result = resilient_push(
            repo_path=_FAKE_REPO,
            max_retries=3,
            user_decision=None,
        )

        self.assertFalse(result.success)
        self.assertEqual(result.error_kind, "fetch_replay_failed")
        self.assertTrue(result.triggered_fetch_replay)
        # Only 1 push attempt before fetch abort
        self.assertEqual(result.attempts, 1)


# ---------------------------------------------------------------------------
# Case (b): push 401/403 auth failure → no retry
# ---------------------------------------------------------------------------


class TestCaseB_AuthFailedNoRetry(unittest.TestCase):
    """case (b): auth_failed push is not retried; user_decision callback is invoked."""

    @mock.patch("lib.failure_handlers.push_coordination_ref")
    def test_auth_failed_no_retry_callback_returns_false(self, mock_push):
        """Callback returns False (abort) → user_aborted=True, single attempt."""
        mock_push.return_value = PushResult(False, "auth_failed", "401 Unauthorized")

        callback_calls: list[str] = []

        def callback(error_kind: str, error_msg: str, ctx: dict) -> bool:
            callback_calls.append(error_kind)
            return False  # operator chooses to abort

        result = resilient_push(
            repo_path=_FAKE_REPO,
            max_retries=3,
            user_decision=callback,
        )

        self.assertFalse(result.success)
        self.assertEqual(result.error_kind, "auth_failed")
        self.assertEqual(result.attempts, 1)   # not retried
        self.assertTrue(result.user_aborted)
        self.assertEqual(callback_calls, ["auth_failed"])

    @mock.patch("lib.failure_handlers.push_coordination_ref")
    def test_auth_failed_callback_returns_true_still_fails(self, mock_push):
        """Even if callback returns True (continue), auth failure is not retried.
        Auth cannot self-heal — result is still success=False."""
        mock_push.return_value = PushResult(False, "auth_failed", "403 Forbidden")

        result = resilient_push(
            repo_path=_FAKE_REPO,
            max_retries=3,
            user_decision=lambda ek, em, ctx: True,  # operator says "continue"
        )

        self.assertFalse(result.success)
        self.assertEqual(result.error_kind, "auth_failed")
        self.assertEqual(result.attempts, 1)      # still not retried
        self.assertFalse(result.user_aborted)     # callback returned True

    @mock.patch("lib.failure_handlers.push_coordination_ref")
    def test_auth_failed_no_callback(self, mock_push):
        """No callback provided → user_aborted=True (default-False maps to abort)."""
        mock_push.return_value = PushResult(False, "auth_failed", "401")

        result = resilient_push(
            repo_path=_FAKE_REPO,
            max_retries=3,
            user_decision=None,
        )

        self.assertFalse(result.success)
        self.assertEqual(result.error_kind, "auth_failed")
        self.assertEqual(result.attempts, 1)
        self.assertTrue(result.user_aborted)


# ---------------------------------------------------------------------------
# Case (c): other push failure → user_decision
# ---------------------------------------------------------------------------


class TestCaseC_OtherPushFailureUserDecision(unittest.TestCase):
    """case (c): non-auth, non-non_ff failure routes through user_decision."""

    @mock.patch("lib.failure_handlers.push_coordination_ref")
    def test_other_failure_callback_abort(self, mock_push):
        """Callback returns False → user_aborted=True."""
        mock_push.return_value = PushResult(False, "network", "Connection timed out")

        result = resilient_push(
            repo_path=_FAKE_REPO,
            max_retries=2,
            user_decision=lambda ek, em, ctx: False,
        )

        self.assertFalse(result.success)
        self.assertEqual(result.error_kind, "network")
        self.assertTrue(result.user_aborted)
        self.assertEqual(result.attempts, 1)

    @mock.patch("lib.failure_handlers.push_coordination_ref")
    def test_other_failure_callback_proceed(self, mock_push):
        """Callback returns True (continue) → user_aborted=False, still success=False.
        No automatic retry for general failures; caller may re-invoke."""
        mock_push.return_value = PushResult(False, "push_failed", "unexpected error")

        result = resilient_push(
            repo_path=_FAKE_REPO,
            max_retries=2,
            user_decision=lambda ek, em, ctx: True,
        )

        self.assertFalse(result.success)
        self.assertEqual(result.error_kind, "push_failed")
        self.assertFalse(result.user_aborted)
        self.assertEqual(result.attempts, 1)

    @mock.patch("lib.failure_handlers.push_coordination_ref")
    def test_other_failure_no_callback(self, mock_push):
        """No callback → _call_user_decision returns False → user_aborted=True."""
        mock_push.return_value = PushResult(False, "network", "DNS failure")

        result = resilient_push(
            repo_path=_FAKE_REPO,
            max_retries=2,
            user_decision=None,
        )

        self.assertFalse(result.success)
        self.assertEqual(result.error_kind, "network")
        self.assertTrue(result.user_aborted)


# ---------------------------------------------------------------------------
# Case (d): orphan ref absent → auto-bootstrap
# ---------------------------------------------------------------------------


class TestCaseD_OrphanRefAutoBootstrap(unittest.TestCase):
    """case (d): missing local ref triggers bootstrap before write_claim."""

    @mock.patch("lib.failure_handlers.write_claim")
    @mock.patch("lib.failure_handlers.bootstrap")
    @mock.patch("lib.coordination_ref._ref_exists_local")
    def test_auto_bootstrap_on_missing_ref_succeeds(
        self, mock_exists, mock_bootstrap, mock_write
    ):
        """Ref absent → bootstrap runs → write succeeds → bootstrap_triggered=True."""
        mock_exists.return_value = False
        mock_bootstrap.return_value = BootstrapResult(
            created=True,
            ref_existed_local=False,
            ref_existed_remote=False,
            commit_sha="aabbccdd",
            pushed=False,
            error=None,
        )
        mock_write.return_value = WriteClaimResult(
            success=True,
            commit_sha="eeff0011",
            blob_sha="bblobsha",
            claim_path="claims/devbox-A/s-test001.yaml",
            error=None,
        )

        result = resilient_write_claim(
            _make_claim_record(),
            repo_path=_FAKE_REPO,
            auto_bootstrap=True,
        )

        self.assertTrue(result.success)
        self.assertTrue(result.bootstrap_triggered)
        self.assertFalse(result.disk_full)
        self.assertIsNone(result.error_kind)
        mock_bootstrap.assert_called_once()

    @mock.patch("lib.failure_handlers.write_claim")
    @mock.patch("lib.failure_handlers.bootstrap")
    @mock.patch("lib.coordination_ref._ref_exists_local")
    def test_auto_bootstrap_bootstrap_fails(
        self, mock_exists, mock_bootstrap, mock_write
    ):
        """Bootstrap fails (no commit_sha) → error_kind='bootstrap_failed', no write attempt."""
        mock_exists.return_value = False
        mock_bootstrap.return_value = BootstrapResult(
            created=False,
            ref_existed_local=False,
            ref_existed_remote=False,
            commit_sha="",
            pushed=False,
            error="commit_tree_failed",
        )

        result = resilient_write_claim(
            _make_claim_record(),
            repo_path=_FAKE_REPO,
            auto_bootstrap=True,
        )

        self.assertFalse(result.success)
        self.assertTrue(result.bootstrap_triggered)
        self.assertEqual(result.error_kind, "bootstrap_failed")
        mock_write.assert_not_called()

    @mock.patch("lib.failure_handlers.write_claim")
    @mock.patch("lib.coordination_ref._ref_exists_local")
    def test_no_bootstrap_when_ref_exists(self, mock_exists, mock_write):
        """Ref already present → bootstrap_triggered=False."""
        mock_exists.return_value = True
        mock_write.return_value = WriteClaimResult(
            success=True,
            commit_sha="cafe1234",
            blob_sha="b10bsha",
            claim_path="claims/devbox-A/s-test001.yaml",
            error=None,
        )

        result = resilient_write_claim(
            _make_claim_record(),
            repo_path=_FAKE_REPO,
            auto_bootstrap=True,
        )

        self.assertTrue(result.success)
        self.assertFalse(result.bootstrap_triggered)


# ---------------------------------------------------------------------------
# Case (e): disk full / local write failure → non-crashing
# ---------------------------------------------------------------------------


class TestCaseE_DiskFull(unittest.TestCase):
    """case (e): OSError on write_claim is caught; success=False, no exception raised."""

    @mock.patch("lib.failure_handlers.write_claim")
    @mock.patch("lib.coordination_ref._ref_exists_local")
    def test_enospc_disk_full(self, mock_exists, mock_write):
        """errno.ENOSPC → disk_full=True, error_kind='disk_full'."""
        mock_exists.return_value = True
        mock_write.side_effect = OSError(errno.ENOSPC, "No space left on device")

        result = resilient_write_claim(
            _make_claim_record(),
            repo_path=_FAKE_REPO,
        )

        self.assertFalse(result.success)
        self.assertTrue(result.disk_full)
        self.assertEqual(result.error_kind, "disk_full")
        self.assertIsNone(result.write_result)

    @mock.patch("lib.failure_handlers.write_claim")
    @mock.patch("lib.coordination_ref._ref_exists_local")
    def test_eacces_not_disk_full(self, mock_exists, mock_write):
        """errno.EACCES → disk_full=False, error_kind='os_error'; no exception."""
        mock_exists.return_value = True
        mock_write.side_effect = OSError(errno.EACCES, "Permission denied")

        result = resilient_write_claim(
            _make_claim_record(),
            repo_path=_FAKE_REPO,
        )

        self.assertFalse(result.success)
        self.assertFalse(result.disk_full)
        self.assertEqual(result.error_kind, "os_error")

    @mock.patch("lib.failure_handlers.write_claim")
    @mock.patch("lib.coordination_ref._ref_exists_local")
    def test_disk_full_does_not_raise(self, mock_exists, mock_write):
        """Critical non-crashing guarantee: no exception escapes the wrapper."""
        mock_exists.return_value = True
        mock_write.side_effect = OSError(errno.ENOSPC, "No space left on device")

        try:
            result = resilient_write_claim(
                _make_claim_record(),
                repo_path=_FAKE_REPO,
            )
        except Exception as exc:  # noqa: BLE001
            self.fail(f"resilient_write_claim raised unexpectedly: {exc!r}")

        # Execution continued normally — success is False but no crash
        self.assertFalse(result.success)
        self.assertTrue(result.disk_full)


# ---------------------------------------------------------------------------
# Case (f): partial fetch → SHA regression detection
# ---------------------------------------------------------------------------


class TestCaseF_PartialFetch(unittest.TestCase):
    """case (f): fetch succeeds but SHA regresses → partial_fetch=True, ref_regression."""

    @mock.patch("lib.failure_handlers._is_ancestor")
    @mock.patch("lib.failure_handlers._resolve_ref")
    @mock.patch("lib.failure_handlers.fetch_coordination_ref")
    def test_sha_regression_detected(self, mock_fetch, mock_resolve, mock_ancestor):
        """SHA changes but before is NOT ancestor of after → ref_regression."""
        mock_resolve.side_effect = ["abc123abc123abc123abc123", "def456def456def456def456"]
        mock_fetch.return_value = FetchResult(
            success=True,
            error_kind=None,
            error_msg=None,
            ref_updated=True,
        )
        mock_ancestor.return_value = False  # regression: before is not ancestor of after

        result = health_check_fetch(repo_path=_FAKE_REPO)

        self.assertFalse(result.success)
        self.assertTrue(result.partial_fetch)
        self.assertEqual(result.error_kind, "ref_regression")
        self.assertEqual(result.ref_sha_before, "abc123abc123abc123abc123")
        self.assertEqual(result.ref_sha_after, "def456def456def456def456")

    @mock.patch("lib.failure_handlers._is_ancestor")
    @mock.patch("lib.failure_handlers._resolve_ref")
    @mock.patch("lib.failure_handlers.fetch_coordination_ref")
    def test_sha_monotonic_advance_ok(self, mock_fetch, mock_resolve, mock_ancestor):
        """SHA advances and before IS ancestor of after → success=True, no regression."""
        mock_resolve.side_effect = ["aaa111", "bbb222"]
        mock_fetch.return_value = FetchResult(
            success=True,
            error_kind=None,
            error_msg=None,
            ref_updated=True,
        )
        mock_ancestor.return_value = True  # healthy monotonic advance

        result = health_check_fetch(repo_path=_FAKE_REPO)

        self.assertTrue(result.success)
        self.assertFalse(result.partial_fetch)
        self.assertIsNone(result.error_kind)

    @mock.patch("lib.failure_handlers._resolve_ref")
    @mock.patch("lib.failure_handlers.fetch_coordination_ref")
    def test_fetch_failure_marks_partial(self, mock_fetch, mock_resolve):
        """fetch_coordination_ref failure → partial_fetch=True, success=False."""
        mock_resolve.return_value = "abc"
        mock_fetch.return_value = FetchResult(
            success=False,
            error_kind="network",
            error_msg="Connection refused",
            ref_updated=False,
        )

        result = health_check_fetch(repo_path=_FAKE_REPO)

        self.assertFalse(result.success)
        self.assertTrue(result.partial_fetch)
        self.assertEqual(result.error_kind, "network")

    @mock.patch("lib.failure_handlers._resolve_ref")
    @mock.patch("lib.failure_handlers.fetch_coordination_ref")
    def test_ref_newly_appeared_not_regression(self, mock_fetch, mock_resolve):
        """Ref absent before (empty SHA) then appears after → not a regression."""
        mock_resolve.side_effect = ["", "newsha123"]  # "" before, sha after
        mock_fetch.return_value = FetchResult(
            success=True,
            error_kind=None,
            error_msg=None,
            ref_updated=True,
        )

        result = health_check_fetch(repo_path=_FAKE_REPO)

        # sha_before="" → regression check is skipped → success
        self.assertTrue(result.success)
        self.assertFalse(result.partial_fetch)


# ---------------------------------------------------------------------------
# Case (g): clock-skew threshold constant exported
# ---------------------------------------------------------------------------


class TestCaseG_ClockSkewConstant(unittest.TestCase):
    """case (g): clock-skew detection is delegated to reconcile; this test
    verifies the shared constant is correctly exported from failure_handlers
    so downstream consumers (reconcile, track_board) can import from one source."""

    def test_clock_skew_threshold_exported_value(self):
        """CLOCK_SKEW_WARN_THRESHOLD == 30 seconds (matches NTP sync tolerance)."""
        self.assertEqual(CLOCK_SKEW_WARN_THRESHOLD, 30)

    def test_clock_skew_threshold_is_int(self):
        """Constant must be an int for comparison arithmetic in reconcile."""
        self.assertIsInstance(CLOCK_SKEW_WARN_THRESHOLD, int)

    def test_non_ff_max_retries_exported(self):
        """NON_FF_MAX_RETRIES is exported and equals 3 per spec §2.9(a)."""
        self.assertEqual(NON_FF_MAX_RETRIES, 3)

    def test_user_decision_callback_is_callable_type(self):
        """UserDecisionCallback type alias is present and the protocol is correct
        (callable accepting 3 args returning bool)."""
        # Verify a conformant callable satisfies runtime isinstance checks via call
        cb: UserDecisionCallback = lambda ek, em, ctx: True
        self.assertTrue(cb("kind", "msg", {}))


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main()

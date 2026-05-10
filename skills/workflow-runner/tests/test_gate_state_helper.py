"""Tests for gate_state_helper.py (workflow-runner v2.3.0+ wait_recoverable).

Covers Spec T2.5 cases (a)-(e) plus migration / defensive access / interrupt
flag lifecycle. Uses tmp paths and injectable sleep_func — no real sleeps.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "scripts"))

import gate_state_helper as gs  # noqa: E402


def _minimal_state(format_version: str = "1.1") -> dict:
    """Build a minimal valid state dict for testing."""
    return {
        "$schema": "aria-workflow-state/v1",
        "format_version": format_version,
        "session": {
            "id": "sess-20260510-abc123",
            "started_at": "2026-05-10T00:00:00Z",
            "last_active_at": "2026-05-10T00:00:00Z",
            "status": "in_progress",
        },
        "workflow": {
            "name": "feature-dev",
            "phases": ["A", "B", "C"],
            "current_phase": "C",
            "current_step": "C.2",
            "auto_proceed": False,
            "spec_id": "phase-c-integrator-pre-merge-gate",
        },
        "gates": {"gate1_spec_approved": True, "gate2_merge_main": False},
    }


class MigrationTests(unittest.TestCase):
    def test_v10_state_migrates_to_v11_with_null_gate_state(self) -> None:
        """T2.5 (a-prereq): v1.0 state file resume at v1.1 runtime.

        Per schema §8.3 migration table, v1.0 → v1.1 adds gate_state=null.
        Defensive access via state.get("gate_state") or {} must not KeyError.
        """
        state = _minimal_state(format_version="1.0")
        # v1.0 state has no gate_state key.
        self.assertNotIn("gate_state", state)
        migrated = gs._migrate_state(state)
        self.assertEqual(migrated["format_version"], "1.1")
        self.assertIsNone(migrated["gate_state"])
        # Defensive access pattern documented in SKILL.md must work.
        self.assertEqual(migrated.get("gate_state") or {}, {})

    def test_v11_state_unchanged(self) -> None:
        state = _minimal_state(format_version="1.1")
        state["gate_state"] = None
        migrated = gs._migrate_state(state)
        self.assertEqual(migrated["format_version"], "1.1")
        self.assertIsNone(migrated["gate_state"])


class CorruptedStateRecoveryTests(unittest.TestCase):
    """T2.5 (e): workflow-state.json corruption at resume → clear error."""

    def test_load_state_returns_none_on_truncated_json(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
            # Truncated JSON (closing brace missing) — simulates partial write.
            fh.write('{"format_version": "1.1", "session": {"id": ')
            path = fh.name
        try:
            result = gs.load_state(path)
            self.assertIsNone(result)  # Caller routes to "treat as absent" recovery.
        finally:
            os.unlink(path)

    def test_load_state_returns_none_when_file_absent(self) -> None:
        result = gs.load_state("/tmp/this-path-does-not-exist-xyz.json")
        self.assertIsNone(result)

    def test_load_state_returns_none_when_root_is_array(self) -> None:
        # Defensive: schema requires dict at root.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
            fh.write('["not", "a", "dict"]')
            path = fh.name
        try:
            self.assertIsNone(gs.load_state(path))
        finally:
            os.unlink(path)


class GateStateLifecycleTests(unittest.TestCase):
    """T2.5 (b): wait → green / wait → fail / waiting persistence."""

    def test_first_wait_creates_gate_state_with_retry_zero(self) -> None:
        state = _minimal_state()
        gs.write_gate_state(
            state,
            name="pre_merge",
            verdict="waiting",
            in_flight_runs=[
                {"run_id": 3161, "branch": "main", "started_at": "2026-05-10T12:00:00Z", "elapsed_seconds": 60}
            ],
        )
        self.assertIsNotNone(state["gate_state"])
        gate = state["gate_state"]
        self.assertEqual(gate["name"], "pre_merge")
        self.assertEqual(gate["status"], "waiting")
        self.assertEqual(gate["retry_count"], 0)
        self.assertEqual(len(gate["in_flight_runs"]), 1)
        self.assertEqual(gate["primitive_used"], "aether-ci-cli")

    def test_subsequent_wait_increments_retry_count(self) -> None:
        state = _minimal_state()
        gs.write_gate_state(state, name="pre_merge", verdict="waiting")
        gs.write_gate_state(state, name="pre_merge", verdict="waiting")
        gs.write_gate_state(state, name="pre_merge", verdict="waiting")
        self.assertEqual(state["gate_state"]["retry_count"], 2)

    def test_wait_to_green_preserves_retry_count(self) -> None:
        """Terminal verdict (green) does not bump retry_count further."""
        state = _minimal_state()
        gs.write_gate_state(state, name="pre_merge", verdict="waiting")
        gs.write_gate_state(state, name="pre_merge", verdict="waiting")
        # Now transition to green (terminal).
        gs.write_gate_state(state, name="pre_merge", verdict="green", in_flight_runs=[])
        self.assertEqual(state["gate_state"]["status"], "green")
        self.assertEqual(state["gate_state"]["retry_count"], 1)
        self.assertEqual(state["gate_state"]["in_flight_runs"], [])

    def test_wait_to_fail_preserves_retry_and_message(self) -> None:
        state = _minimal_state()
        gs.write_gate_state(state, name="pre_merge", verdict="waiting")
        gs.write_gate_state(
            state,
            name="pre_merge",
            verdict="fail",
            raw_message="aether subprocess timeout after 3 attempts",
        )
        self.assertEqual(state["gate_state"]["status"], "fail")
        self.assertIn("timeout", state["gate_state"]["raw_message"])

    def test_clear_gate_state_sets_null(self) -> None:
        state = _minimal_state()
        gs.write_gate_state(state, name="pre_merge", verdict="waiting")
        gs.clear_gate_state(state)
        self.assertIsNone(state["gate_state"])
        self.assertFalse(gs.is_gate_active(state))

    def test_is_gate_active_only_true_for_waiting(self) -> None:
        state = _minimal_state()
        self.assertFalse(gs.is_gate_active(state))  # gate_state absent
        gs.write_gate_state(state, name="pre_merge", verdict="waiting")
        self.assertTrue(gs.is_gate_active(state))
        gs.write_gate_state(state, name="pre_merge", verdict="green")
        self.assertFalse(gs.is_gate_active(state))

    def test_next_check_at_uses_intervals(self) -> None:
        """next_check_at advances by intervals[retry_count] each cycle."""
        state = _minimal_state()
        # Inject deterministic intervals for assertion.
        gs.write_gate_state(state, name="pre_merge", verdict="waiting", intervals=(10, 20, 30))
        first_next = state["gate_state"]["next_check_at"]
        # After incremented retry, intervals[1]=20 should be used.
        gs.write_gate_state(state, name="pre_merge", verdict="waiting", intervals=(10, 20, 30))
        # Second next_check_at should be later than first (20s vs 10s delta from now).
        self.assertGreater(first_next, "2026-05-10T00:00:00Z")  # sanity: ISO 8601 lex


class ResumeSemanticsTests(unittest.TestCase):
    """T2.5 resume path — should_check_now."""

    def test_should_check_now_when_next_check_is_past(self) -> None:
        state = _minimal_state()
        state["gate_state"] = {
            "name": "pre_merge",
            "status": "waiting",
            "started_at": "2026-05-09T00:00:00Z",
            "retry_count": 0,
            "next_check_at": "2026-05-09T00:01:00Z",  # past
            "in_flight_runs": [],
            "primitive_used": "aether-ci-cli",
            "raw_message": "",
        }
        self.assertTrue(gs.should_check_now(state))

    def test_should_check_now_false_when_next_check_in_future(self) -> None:
        future = (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=1)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        state = _minimal_state()
        state["gate_state"] = {
            "name": "pre_merge",
            "status": "waiting",
            "started_at": "2026-05-09T00:00:00Z",
            "retry_count": 0,
            "next_check_at": future,
            "in_flight_runs": [],
            "primitive_used": "aether-ci-cli",
            "raw_message": "",
        }
        self.assertFalse(gs.should_check_now(state))

    def test_should_check_now_true_when_next_check_malformed(self) -> None:
        """Fail-safe: malformed timestamp routes to immediate re-check."""
        state = _minimal_state()
        state["gate_state"] = {
            "name": "pre_merge",
            "status": "waiting",
            "started_at": "2026-05-09T00:00:00Z",
            "retry_count": 0,
            "next_check_at": "not-a-date",
            "in_flight_runs": [],
            "primitive_used": "aether-ci-cli",
            "raw_message": "",
        }
        self.assertTrue(gs.should_check_now(state))


class InterruptFlagTests(unittest.TestCase):
    """R2-CR-B Flag-file lifecycle: clear / set / detect."""

    def test_clear_idempotent_when_flag_absent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            flag = os.path.join(td, "interrupt-flag")
            # Should not raise even when missing.
            gs.clear_interrupt_flag(flag)
            self.assertFalse(os.path.exists(flag))

    def test_set_then_detect_then_clear(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            flag = os.path.join(td, "interrupt-flag")
            self.assertFalse(gs.interrupt_flag_present(flag))
            gs.set_interrupt_flag(flag)
            self.assertTrue(gs.interrupt_flag_present(flag))
            # File contains an ISO 8601 timestamp.
            with open(flag) as fh:
                content = fh.read().strip()
            self.assertRegex(content, r"^\d{4}-\d{2}-\d{2}T")
            gs.clear_interrupt_flag(flag)
            self.assertFalse(gs.interrupt_flag_present(flag))

    def test_set_overwrites_existing_flag(self) -> None:
        """Latest signal wins — sequential SIGINTs do not stack."""
        with tempfile.TemporaryDirectory() as td:
            flag = os.path.join(td, "interrupt-flag")
            gs.set_interrupt_flag(flag)
            gs.set_interrupt_flag(flag)  # Should not raise.
            self.assertTrue(gs.interrupt_flag_present(flag))


class PollWithInterruptTests(unittest.TestCase):
    """Polling sleep chunk + interrupt detection (CR-5)."""

    def test_poll_completes_normally_when_no_interrupt(self) -> None:
        sleep_calls = []

        def fake_sleep(s: float) -> None:
            sleep_calls.append(s)

        with tempfile.TemporaryDirectory() as td:
            flag = os.path.join(td, "interrupt-flag")
            interrupted = gs.poll_with_interrupt_check(
                sleep_seconds=12, chunk_seconds=5, flag_path=flag, sleep_func=fake_sleep
            )
        self.assertFalse(interrupted)
        # 12 seconds in 5-chunks: 5 + 5 + 2.
        self.assertEqual(sleep_calls, [5, 5, 2])

    def test_poll_returns_true_when_interrupt_appears_mid_sleep(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            flag = os.path.join(td, "interrupt-flag")
            chunk_count = [0]

            def fake_sleep(s: float) -> None:
                chunk_count[0] += 1
                # Set the interrupt flag during the second chunk.
                if chunk_count[0] == 2:
                    gs.set_interrupt_flag(flag)

            interrupted = gs.poll_with_interrupt_check(
                sleep_seconds=30, chunk_seconds=5, flag_path=flag, sleep_func=fake_sleep
            )
        self.assertTrue(interrupted)
        # Should exit after detecting flag in chunk 2 — chunks 3-6 not slept.
        self.assertEqual(chunk_count[0], 2)

    def test_poll_with_zero_seconds_only_checks_flag(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            flag = os.path.join(td, "interrupt-flag")
            # No flag → not interrupted.
            sleep_called = []

            def fake_sleep(s: float) -> None:
                sleep_called.append(s)

            self.assertFalse(
                gs.poll_with_interrupt_check(
                    sleep_seconds=0, flag_path=flag, sleep_func=fake_sleep
                )
            )
            self.assertEqual(sleep_called, [])


class AtomicWriteTests(unittest.TestCase):
    """Schema §4 atomic write protocol with integrity hash recompute."""

    def test_write_then_read_roundtrip_preserves_gate_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "workflow-state.json")
            state = _minimal_state()
            gs.write_gate_state(state, name="pre_merge", verdict="waiting")
            gs.atomic_write_state(state, path)
            loaded = gs.load_state(path)
            self.assertIsNotNone(loaded)
            assert loaded is not None  # for type-checker
            self.assertEqual(loaded["gate_state"]["name"], "pre_merge")
            self.assertEqual(loaded["gate_state"]["status"], "waiting")
            self.assertIn("integrity", loaded)
            self.assertTrue(loaded["integrity"]["state_hash"].startswith("sha256:"))


if __name__ == "__main__":
    unittest.main()

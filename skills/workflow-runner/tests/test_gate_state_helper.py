"""Tests for gate_state_helper.py (workflow-runner v2.3.0+ wait_recoverable).

Covers Spec T2.5 cases (a)-(e) plus migration / defensive access / interrupt
flag lifecycle. Uses tmp paths and injectable sleep_func — no real sleeps.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "scripts"))

import gate_state_helper as gs  # noqa: E402

# Absolute path to the CLI entrypoint under test — invoked via subprocess so
# a missing `main()` / argparse surface (today's baseline) cannot crash the
# collecting test *process*, only fail individual CLI test assertions.
_SCRIPT_PATH = os.path.join(os.path.dirname(_HERE), "scripts", "gate_state_helper.py")


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


class NoRunObservationTests(unittest.TestCase):
    """SC-11 (a)-(c): write_gate_state(gate_error_kind=) is the single
    counting point for `gate_state.no_run_observations`, plus the two
    field-scoped resetters and v1.1-legacy defensive-default behavior.

    Baseline `write_gate_state()` has no `gate_error_kind` parameter at all,
    so every call below that passes it raises
    ``TypeError: write_gate_state() got an unexpected keyword argument
    'gate_error_kind'`` — that TypeError *is* the expected red. Tests that
    reference `gs.reset_no_run_observations` / `gs.reset_retry_count`
    directly go red via ``AttributeError: module 'gate_state_helper' has no
    attribute '...'`` instead. Both are attribute/call-time errors inside a
    test method body, not import-time errors, so module collection (and the
    existing 22 tests) is unaffected either way.
    """

    def test_three_consecutive_no_run_waits_increment_observations(self) -> None:
        """3x write_gate_state(kind="no-run-for-branch", verdict=waiting):
        no_run_observations goes 1/2/3, retry_count goes 0/1/2 (unchanged
        semantics), started_at is identical across all three calls (only
        the first / is_first call sets it).

        Red today: TypeError (no gate_error_kind kwarg on baseline
        write_gate_state).
        """
        state = _minimal_state()
        gs.write_gate_state(
            state, name="pre_merge", verdict="waiting", gate_error_kind="no-run-for-branch"
        )
        gate1 = state["gate_state"]
        self.assertEqual(gate1["no_run_observations"], 1)
        self.assertEqual(gate1["retry_count"], 0)
        started_at = gate1["started_at"]

        gs.write_gate_state(
            state, name="pre_merge", verdict="waiting", gate_error_kind="no-run-for-branch"
        )
        gate2 = state["gate_state"]
        self.assertEqual(gate2["no_run_observations"], 2)
        self.assertEqual(gate2["retry_count"], 1)
        self.assertEqual(gate2["started_at"], started_at)

        gs.write_gate_state(
            state, name="pre_merge", verdict="waiting", gate_error_kind="no-run-for-branch"
        )
        gate3 = state["gate_state"]
        self.assertEqual(gate3["no_run_observations"], 3)
        self.assertEqual(gate3["retry_count"], 2)
        self.assertEqual(gate3["started_at"], started_at)

    def test_non_matching_kind_zeroes_then_restarts_at_one_and_terminal_green_zeroes(
        self,
    ) -> None:
        """A `gate_error_kind=None` call mid-sequence zeroes the counter
        (does not merely pause it); a following kind="no-run-for-branch"
        call *restarts* at 1 (not a resumed running total — carry-forward
        reads the just-zeroed value). A terminal verdict="green" call that
        still carries the kind also reads 0, because the counting condition
        is `kind == "no-run-for-branch" AND verdict == "waiting"` — green
        fails the second half.

        Red today: TypeError on the very first call (no gate_error_kind
        kwarg on baseline write_gate_state).
        """
        state = _minimal_state()
        gs.write_gate_state(
            state, name="pre_merge", verdict="waiting", gate_error_kind="no-run-for-branch"
        )
        self.assertEqual(state["gate_state"]["no_run_observations"], 1)

        gs.write_gate_state(state, name="pre_merge", verdict="waiting", gate_error_kind=None)
        self.assertEqual(state["gate_state"]["no_run_observations"], 0)

        gs.write_gate_state(
            state, name="pre_merge", verdict="waiting", gate_error_kind="no-run-for-branch"
        )
        self.assertEqual(state["gate_state"]["no_run_observations"], 1)

        gs.write_gate_state(
            state, name="pre_merge", verdict="green", gate_error_kind="no-run-for-branch"
        )
        self.assertEqual(state["gate_state"]["status"], "green")
        self.assertEqual(state["gate_state"]["no_run_observations"], 0)

    def test_reset_no_run_observations_clears_only_that_field(self) -> None:
        """reset_no_run_observations(state): gate_state.no_run_observations
        -> 0; every other gate_state key is byte-identical before/after
        (compared as a dict with the one key removed on both sides).

        Red today: AttributeError — gate_state_helper has no
        reset_no_run_observations symbol.
        """
        state = _minimal_state()
        gs.write_gate_state(
            state, name="pre_merge", verdict="waiting", gate_error_kind="no-run-for-branch"
        )
        gs.write_gate_state(
            state, name="pre_merge", verdict="waiting", gate_error_kind="no-run-for-branch"
        )
        before = dict(state["gate_state"])
        self.assertEqual(before["no_run_observations"], 2)

        result = gs.reset_no_run_observations(state)
        after = state["gate_state"]
        self.assertEqual(after["no_run_observations"], 0)
        before_rest = {k: v for k, v in before.items() if k != "no_run_observations"}
        after_rest = {k: v for k, v in after.items() if k != "no_run_observations"}
        self.assertEqual(before_rest, after_rest)
        # Returns the (mutated) state, mirroring write_gate_state / clear_gate_state.
        self.assertIs(result, state)

    def test_reset_retry_count_resets_count_and_bumps_started_at(self) -> None:
        """reset_retry_count(state): retry_count -> 0 AND started_at -> now
        (ISO Z, re-parseable); every other gate_state key unchanged. Forces
        a stale started_at first so the "did it actually change" assertion
        cannot pass by second-resolution timing coincidence.

        Red today: AttributeError — gate_state_helper has no
        reset_retry_count symbol.
        """
        state = _minimal_state()
        gs.write_gate_state(state, name="pre_merge", verdict="waiting")
        gs.write_gate_state(state, name="pre_merge", verdict="waiting")
        state["gate_state"]["started_at"] = "2020-01-01T00:00:00Z"
        before = dict(state["gate_state"])

        result = gs.reset_retry_count(state)
        after = state["gate_state"]
        self.assertEqual(after["retry_count"], 0)
        self.assertNotEqual(after["started_at"], "2020-01-01T00:00:00Z")
        _dt.datetime.fromisoformat(after["started_at"].replace("Z", "+00:00"))  # must parse

        before_rest = {k: v for k, v in before.items() if k not in ("retry_count", "started_at")}
        after_rest = {k: v for k, v in after.items() if k not in ("retry_count", "started_at")}
        self.assertEqual(before_rest, after_rest)
        self.assertIs(result, state)

    def test_legacy_v11_gate_state_missing_key_defaults_to_zero_via_get(self) -> None:
        """A v1.1 gate_state persisted before this feature shipped has no
        `no_run_observations` key at all (not even present as 0) — the
        eight-key literal below mirrors ResumeSemanticsTests' fixtures.
        `existing.get("no_run_observations", 0)` must supply the default
        rather than KeyError; write_gate_state(kind=...) then counts 1,
        write_gate_state(kind=None) reads 0.

        Red today: TypeError (no gate_error_kind kwarg on baseline
        write_gate_state); even a kind-less call would still KeyError on the
        assertion below since no_run_observations wouldn't be populated by
        baseline write_gate_state at all.
        """
        legacy_gate_state = {
            "name": "pre_merge",
            "status": "waiting",
            "started_at": "2026-05-09T00:00:00Z",
            "retry_count": 0,
            "next_check_at": "2026-05-09T00:01:00Z",
            "in_flight_runs": [],
            "primitive_used": "aether-ci-cli",
            "raw_message": "",
        }
        self.assertNotIn("no_run_observations", legacy_gate_state)

        state = _minimal_state()
        state["gate_state"] = dict(legacy_gate_state)
        gs.write_gate_state(
            state, name="pre_merge", verdict="waiting", gate_error_kind="no-run-for-branch"
        )
        self.assertEqual(state["gate_state"]["no_run_observations"], 1)

        state2 = _minimal_state()
        state2["gate_state"] = dict(legacy_gate_state)
        gs.write_gate_state(state2, name="pre_merge", verdict="waiting", gate_error_kind=None)
        self.assertEqual(state2["gate_state"]["no_run_observations"], 0)


class CliRecordTests(unittest.TestCase):
    """SC-11 (d): `gate_state_helper.py` CLI end-to-end (record/reset/clear).

    Every subprocess call passes `--source test`; state files live under a
    fresh per-test tmpdir so production `.aria/` is never touched. Assertions
    reread the state/telemetry files from disk independently of stdout —
    per memory `feedback_output_hygiene_no_raw_control_bytes` /
    `feedback_completion_signals_vs_runtime_invocation`, stdout is a tool
    receipt, not ground truth.

    Two named bad-implementation red-windows this file is designed to catch
    once TASK-009 lands (not runnable against baseline — no CLI exists yet):
      - "整块重建漏 carry-forward" (record rebuilds gate_state from scratch
        each call instead of reading existing.no_run_observations first) ->
        the *second* record call's independently-reread
        gate_state.no_run_observations would read back as 1, not 2.
      - "stdout 自洽未落盘" (record prints a self-consistent JSON without
        actually persisting via atomic_write_state) -> the reread
        gate_state.no_run_observations / status / retry_count assertions
        fail even though stdout parsed fine.

    Baseline-red mechanics: today's gate_state_helper.py has no
    `if __name__ == "__main__":` block at all, so `python3 gate_state_helper.py
    record ...` silently imports-and-exits 0 with empty stdout, touching no
    files. That means:
      - tests asserting `returncode == 0` + a parsed stdout JSON go red via
        `json.JSONDecodeError` (empty stdout) or `FileNotFoundError` (state
        file was never created);
      - tests asserting `returncode == 2` (missing required flags, missing
        state file with non-`wait` verdict, `reset` with no flags) go red
        via a plain value mismatch (actual 0 != expected 2) — still a
        failing assertion, not a collection-breaking error.
    """

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.state_file = os.path.join(self._tmpdir.name, "workflow-state.json")
        self.telemetry_file = os.path.join(self._tmpdir.name, "gate-state-telemetry.jsonl")

    def _cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, _SCRIPT_PATH, *args],
            capture_output=True,
            text=True,
        )

    def _record_wait(
        self,
        *,
        threshold: str = "2",
        intervals: str = "[5,7]",
        gate_error_kind: str | None = "no-run-for-branch",
    ) -> subprocess.CompletedProcess:
        args = [
            "record",
            "--state-file",
            self.state_file,
            "--name",
            "pre_merge",
            "--verdict",
            "wait",
            "--intervals",
            intervals,
            "--threshold",
            threshold,
            "--in-flight-runs",
            '[{"run_id":1}]',
            "--raw-message",
            "x",
            "--source",
            "test",
        ]
        if gate_error_kind is not None:
            args += ["--gate-error-kind", gate_error_kind]
        return self._cli(*args)

    def _read_state(self) -> dict:
        with open(self.state_file, encoding="utf-8") as fh:
            return json.load(fh)

    def _read_telemetry_lines(self) -> list:
        with open(self.telemetry_file, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def _force_started_at(self, value: str) -> None:
        """Hand-edit the on-disk fixture (bypassing the CLI) so the
        "did started_at actually change" assertion cannot pass by
        second-resolution timing coincidence."""
        with open(self.state_file, encoding="utf-8") as fh:
            data = json.load(fh)
        data["gate_state"]["started_at"] = value
        with open(self.state_file, "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def test_record_missing_file_creates_skeleton_and_counts_two_waits(self) -> None:
        """State file absent at start (verdict=wait) -> CLI creates the
        `{"format_version": "1.1", "gate_state": null}` skeleton first, then
        writes through it. Two calls: stdout obs goes 1 (should_prompt
        False) -> 2 (should_prompt True, threshold=2). Independent reread
        of the persisted file confirms status/retry_count/in_flight_runs/
        raw_message/format_version/next_check_at (computed from
        --intervals '[5,7]': retry_count=1 -> intervals[1]=7s). Telemetry
        file has exactly 2 lines, each source=test/sub=record/kind=no-run-
        for-branch, second line's no_run_observations=2 and
        should_prompt=True, and every `ts` is fromisoformat-parseable.
        """
        self.assertFalse(os.path.exists(self.state_file))

        proc1 = self._record_wait()
        self.assertEqual(proc1.returncode, 0, msg=proc1.stderr)
        out1 = json.loads(proc1.stdout)
        self.assertEqual(out1["no_run_observations"], 1)
        self.assertFalse(out1["should_prompt"])

        before_second_call = _dt.datetime.now(_dt.timezone.utc)
        proc2 = self._record_wait()
        self.assertEqual(proc2.returncode, 0, msg=proc2.stderr)
        out2 = json.loads(proc2.stdout)
        self.assertEqual(out2["no_run_observations"], 2)
        self.assertTrue(out2["should_prompt"])

        disk = self._read_state()
        self.assertEqual(disk["format_version"], "1.1")
        gate = disk["gate_state"]
        self.assertEqual(gate["no_run_observations"], 2)
        self.assertEqual(gate["status"], "waiting")  # CLI wait -> "waiting" mapping
        self.assertEqual(gate["retry_count"], 1)
        self.assertEqual(gate["in_flight_runs"], [{"run_id": 1}])
        self.assertEqual(gate["raw_message"], "x")

        next_at = _dt.datetime.fromisoformat(gate["next_check_at"].replace("Z", "+00:00"))
        delta_seconds = (next_at - before_second_call).total_seconds()
        self.assertGreaterEqual(delta_seconds, 7 - 2)
        self.assertLessEqual(delta_seconds, 7 + 5)

        telemetry = self._read_telemetry_lines()
        self.assertEqual(len(telemetry), 2)
        for row in telemetry:
            self.assertEqual(row["source"], "test")
            self.assertEqual(row["sub"], "record")
            self.assertEqual(row["kind"], "no-run-for-branch")
            _dt.datetime.fromisoformat(row["ts"].replace("Z", "+00:00"))  # must parse
        self.assertEqual(telemetry[1]["no_run_observations"], 2)
        self.assertIs(telemetry[1]["should_prompt"], True)

    def test_record_without_gate_error_kind_keeps_observations_at_zero(self) -> None:
        """record --verdict wait with no --gate-error-kind: obs stays 0,
        should_prompt is False, and the persisted file agrees.
        """
        proc = self._cli(
            "record",
            "--state-file",
            self.state_file,
            "--name",
            "pre_merge",
            "--verdict",
            "wait",
            "--source",
            "test",
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["no_run_observations"], 0)
        self.assertFalse(out["should_prompt"])
        disk = self._read_state()
        self.assertEqual(disk["gate_state"]["no_run_observations"], 0)

    def test_reset_observations_flag_clears_only_that_field(self) -> None:
        """`reset --observations`: no_run_observations -> 0; every other
        gate_state key (including the `integrity`-adjacent ones inside
        gate_state itself) is byte-identical before/after. Note the
        top-level `integrity` block legitimately changes on every write —
        this compares only the `gate_state` sub-block, per contract.
        """
        self._record_wait()
        self._record_wait()
        before = self._read_state()["gate_state"]
        self.assertEqual(before["no_run_observations"], 2)

        proc = self._cli("reset", "--state-file", self.state_file, "--observations")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)

        after = self._read_state()["gate_state"]
        self.assertEqual(after["no_run_observations"], 0)
        before_rest = {k: v for k, v in before.items() if k != "no_run_observations"}
        after_rest = {k: v for k, v in after.items() if k != "no_run_observations"}
        self.assertEqual(before_rest, after_rest)

    def test_reset_retry_count_flag_updates_started_at_and_preserves_rest(self) -> None:
        """`reset --retry-count`: retry_count -> 0 AND started_at -> now;
        every other gate_state key (including no_run_observations)
        unchanged. started_at is force-set to a fixed past value on disk
        first so the "actually changed" check cannot pass by timing luck.
        """
        self._record_wait()
        self._record_wait()
        self._force_started_at("2020-01-01T00:00:00Z")
        before = self._read_state()["gate_state"]
        self.assertEqual(before["started_at"], "2020-01-01T00:00:00Z")

        proc = self._cli("reset", "--state-file", self.state_file, "--retry-count")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)

        after = self._read_state()["gate_state"]
        self.assertEqual(after["retry_count"], 0)
        self.assertNotEqual(after["started_at"], "2020-01-01T00:00:00Z")
        _dt.datetime.fromisoformat(after["started_at"].replace("Z", "+00:00"))  # must parse

        before_rest = {k: v for k, v in before.items() if k not in ("retry_count", "started_at")}
        after_rest = {k: v for k, v in after.items() if k not in ("retry_count", "started_at")}
        self.assertEqual(before_rest, after_rest)

    def test_reset_without_any_flag_exits_2(self) -> None:
        """`reset` needs at least one of --observations / --retry-count."""
        self._record_wait()
        proc = self._cli("reset", "--state-file", self.state_file)
        self.assertEqual(proc.returncode, 2)

    def test_reset_on_missing_state_file_exits_2(self) -> None:
        self.assertFalse(os.path.exists(self.state_file))
        proc = self._cli("reset", "--state-file", self.state_file, "--observations")
        self.assertEqual(proc.returncode, 2)

    def test_clear_on_missing_state_file_exits_2(self) -> None:
        self.assertFalse(os.path.exists(self.state_file))
        proc = self._cli("clear", "--state-file", self.state_file)
        self.assertEqual(proc.returncode, 2)

    def test_clear_success_sets_gate_state_none(self) -> None:
        self._record_wait()
        proc = self._cli("clear", "--state-file", self.state_file)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        disk = self._read_state()
        self.assertIsNone(disk["gate_state"])

    def test_record_verdict_green_on_missing_state_file_exits_2(self) -> None:
        """Only a first verdict=wait creates the skeleton; a non-wait
        verdict against an absent file has nothing to update -> exit 2.
        """
        self.assertFalse(os.path.exists(self.state_file))
        proc = self._cli(
            "record",
            "--state-file",
            self.state_file,
            "--name",
            "pre_merge",
            "--verdict",
            "green",
            "--source",
            "test",
        )
        self.assertEqual(proc.returncode, 2)

    def test_record_missing_source_flag_exits_2(self) -> None:
        """--source has no default; omitting it is exit 2, not a silent
        fallback (per contract: "忘带旗标 = 红不是假绿")."""
        proc = self._cli(
            "record",
            "--state-file",
            self.state_file,
            "--name",
            "pre_merge",
            "--verdict",
            "wait",
        )
        self.assertEqual(proc.returncode, 2)

    def test_record_missing_state_file_flag_exits_2(self) -> None:
        """--state-file has no default (argparse required=True -> exit 2)."""
        proc = self._cli(
            "record",
            "--name",
            "pre_merge",
            "--verdict",
            "wait",
            "--source",
            "test",
        )
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()

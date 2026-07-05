"""TASK-011/012 — telemetry partition + runtime-invocation probe self-tests.

The anti-spoof lock (R2-Major-C / PP-R2-qa-Major): the production telemetry
partition must be UNPOLLUTABLE from any harness or library entry.  These tests
assert that structurally:

  - run_gate(source=None)      (library/pytest direct) → production count UNCHANGED
  - run_gate_synthetic(...)    (harness)               → production count UNCHANGED
  - run_gate(source="production") (the CLI path)        → production count +1

and that the probe (coordination_probe) reads ONLY the production partition and
counts only source=="production" records.

Without this lock, TASK-012's probe could pass on a test-only invocation —
exactly the "勾选完成 ≠ 运行现实" false-green this Spec exists to prevent
(feedback_completion_signals_vs_runtime_invocation /
 feedback_noop_in_test_env_hardening_needs_mechanism_assertion).

Spec: openspec/changes/interactive-session-dedup-coordination
Task: TASK-012 (self-test) + TASK-011 (partition mechanism)
"""

from __future__ import annotations

import contextlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

_SKILL_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _SKILL_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

import phase1_gate as g  # noqa: E402
import coordination_probe as probe  # noqa: E402
from lib.claim_schema import ClaimRecord  # noqa: E402
from lib.identity import Identity  # noqa: E402
from lib.failure_handlers import FetchHealth, ResilientPushResult  # noqa: E402
from lib.coordination_ref import ReadClaimsResult  # noqa: E402
from lib.claim_lifecycle import AcquireResult  # noqa: E402

_NOW = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)
# _RECENT is wall-clock-now so records used by the recency-checking probe are
# fresh under the probe's real-clock 14-day window (deterministic enough: the
# test runs seconds after import).
_RECENT = datetime.now(timezone.utc)
_STALE = _RECENT - timedelta(days=60)  # older than the probe's 14-day window
_ME = Identity(owner="me", container_id="cA", session_id="s-me")
_TRACK = "carry-telemetry"

_PROD = ".aria/coordination-telemetry.jsonl"
_NONPROD = ".aria/coordination-telemetry-nonprod.jsonl"


def _our_claim() -> ClaimRecord:
    return ClaimRecord(
        schema_version="1", track_id=_TRACK, owner="me", container="cA",
        session="s-me", phase="B", status="active",
        claimed_at="2026-07-04T12:00:00Z", heartbeat_at="2026-07-04T12:00:00Z",
        superseded_from=None,
    )


@contextlib.contextmanager
def _clean_gate():
    """Patch git boundaries so run_gate reaches a clean PASSED (no competition)."""
    fetch = FetchHealth(True, False, "a" * 40, "a" * 40, None, None)
    rc = ReadClaimsResult(claims=[], errors=[], ref_exists=True)
    acq = AcquireResult(success=True, record=_our_claim(), error=None)
    push = ResilientPushResult(True, None, 1, False, False, None, None, False)
    with mock.patch.object(g, "_is_git_repo", return_value=True), mock.patch.object(
        g, "health_check_fetch", return_value=fetch
    ), mock.patch.object(g, "read_claims", return_value=rc), mock.patch.object(
        g, "acquire_claim", return_value=acq
    ), mock.patch.object(
        g, "resilient_push", return_value=push
    ):
        yield


def _count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for ln in path.read_text().splitlines() if ln.strip())


class TestTelemetryPartitionAntiSpoof(unittest.TestCase):
    def test_library_call_never_touches_production_partition(self):
        with tempfile.TemporaryDirectory() as td, _clean_gate():
            repo = Path(td)
            # source omitted → None → library/non-production
            g.run_gate(_TRACK, "B", repo_path=repo, identity=_ME, now=_NOW)
            self.assertEqual(_count(repo / _PROD), 0, "library call MUST NOT write production")
            self.assertEqual(_count(repo / _NONPROD), 1, "library call → non-production partition")

    def test_synthetic_harness_never_touches_production_partition(self):
        with tempfile.TemporaryDirectory() as td, _clean_gate():
            repo = Path(td)
            g.run_gate_synthetic(_TRACK, "B", repo_path=repo, identity=_ME, now=_NOW)
            self.assertEqual(_count(repo / _PROD), 0, "harness MUST NOT write production")
            self.assertEqual(_count(repo / _NONPROD), 1, "harness → non-production partition")

    def test_synthetic_cannot_override_source_to_production(self):
        with tempfile.TemporaryDirectory() as td, _clean_gate():
            repo = Path(td)
            # even if a caller tries to force source="production" via synthetic
            g.run_gate_synthetic(
                _TRACK, "B", repo_path=repo, identity=_ME, now=_NOW, source="production"
            )
            self.assertEqual(_count(repo / _PROD), 0, "synthetic ignores source override")

    def test_production_source_via_private_gated_writes_production_partition(self):
        # Production partition is reachable ONLY via the private _gated path
        # (audit telemetry-antispoof fix). This mirrors what the CLI _main does.
        with tempfile.TemporaryDirectory() as td, _clean_gate():
            repo = Path(td)
            g._gated(_TRACK, "B", repo_path=repo, identity=_ME, now=_NOW, _source="production")
            self.assertEqual(_count(repo / _PROD), 1, "explicit production → production partition")
            self.assertEqual(_count(repo / _NONPROD), 0)

    def test_public_run_gate_has_no_source_param(self):
        """Structural lock: the public API cannot select the production partition."""
        import inspect

        self.assertNotIn(
            "source",
            inspect.signature(g.run_gate).parameters,
            "run_gate must NOT expose `source` (else any caller could write production)",
        )
        # and a public call always lands in the non-production partition
        with tempfile.TemporaryDirectory() as td, _clean_gate():
            repo = Path(td)
            g.run_gate(_TRACK, "B", repo_path=repo, identity=_ME, now=_NOW)
            self.assertEqual(_count(repo / _PROD), 0)
            self.assertEqual(_count(repo / _NONPROD), 1)

    def test_abort_outcome_emits_no_telemetry(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            # non-git repo → abort at step 2, before any coordination happened
            with mock.patch.object(g, "_is_git_repo", return_value=False):
                g._gated(_TRACK, "B", repo_path=repo, identity=_ME, now=_NOW, _source="production")
            self.assertEqual(_count(repo / _PROD), 0, "abort is not a coordination observation")

    def test_record_shape_has_structural_source_and_arm(self):
        with tempfile.TemporaryDirectory() as td, _clean_gate():
            repo = Path(td)
            g._gated(_TRACK, "B", repo_path=repo, identity=_ME, now=_NOW, _source="production")
            rec = json.loads((repo / _PROD).read_text().splitlines()[0])
            self.assertEqual(rec["source"], "production")
            self.assertEqual(rec["arm"], "manual")
            self.assertIn("ts", rec)
            self.assertIn("claim_written", rec)
            self.assertIn("collision_surfaced", rec)


class TestCoordinationProbe(unittest.TestCase):
    def _write_config(self, repo: Path, enabled: bool):
        (repo / ".aria").mkdir(parents=True, exist_ok=True)
        cfg = {"state_scanner": {"coordination": {"enabled": enabled, "mode": "advisory"}}}
        (repo / ".aria" / "config.json").write_text(json.dumps(cfg))

    def _write_prod_lines(self, repo: Path, lines):
        (repo / ".aria").mkdir(parents=True, exist_ok=True)
        (repo / ".aria" / "coordination-telemetry.jsonl").write_text("\n".join(lines) + "\n")

    def test_probe_ok_when_gate_disabled(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            self._write_config(repo, enabled=False)
            self.assertEqual(probe.main([str(repo)]), 0)

    def test_probe_fails_when_enabled_but_no_records(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            self._write_config(repo, enabled=True)  # enabled, but no telemetry yet
            self.assertEqual(probe.main([str(repo)]), 1)

    def test_probe_ok_when_enabled_with_recent_production_record(self):
        with tempfile.TemporaryDirectory() as td, _clean_gate():
            repo = Path(td)
            self._write_config(repo, enabled=True)
            g._gated(_TRACK, "B", repo_path=repo, identity=_ME, now=_RECENT, _source="production")
            self.assertEqual(probe.count_production_invocations(repo), 1)
            self.assertEqual(probe.main([str(repo)]), 0)

    def test_probe_stale_production_record_fails(self):
        """Recency lock (audit Critical): an OLD production record must not keep
        the probe green — else it can't detect run_gate re-degrading to dead code."""
        with tempfile.TemporaryDirectory() as td, _clean_gate():
            repo = Path(td)
            self._write_config(repo, enabled=True)
            g._gated(_TRACK, "B", repo_path=repo, identity=_ME, now=_STALE, _source="production")
            self.assertEqual(
                probe.count_production_invocations(repo), 0,
                "a >14d-old production record is not a RECENT invocation",
            )
            self.assertEqual(probe.main([str(repo)]), 1, "stale-only → probe FAIL")

    def test_probe_ignores_nonproduction_records(self):
        """Enabled + only harness/library records → probe still FAILS (structural)."""
        with tempfile.TemporaryDirectory() as td, _clean_gate():
            repo = Path(td)
            self._write_config(repo, enabled=True)
            # library + harness calls only → nonprod partition populated, prod empty
            g.run_gate(_TRACK, "B", repo_path=repo, identity=_ME, now=_RECENT)  # source=None
            g.run_gate_synthetic(_TRACK, "B", repo_path=repo, identity=_ME, now=_RECENT)
            self.assertEqual(probe.count_production_invocations(repo), -1)  # prod file absent
            self.assertEqual(probe.main([str(repo)]), 1, "harness/library records can't satisfy the probe")

    def test_probe_ignores_hand_written_harness_and_malformed_lines(self):
        """The source=='production' filter (belt-and-braces) is exercised: a prod
        FILE that exists but holds only harness/library/malformed lines → count 0."""
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            self._write_config(repo, enabled=True)
            recent_ts = _RECENT.strftime("%Y-%m-%dT%H:%M:%SZ")
            self._write_prod_lines(repo, [
                json.dumps({"ts": recent_ts, "source": "harness", "outcome": "passed"}),
                json.dumps({"ts": recent_ts, "source": "library", "outcome": "passed"}),
                "{ this is not valid json",
                "",
            ])
            self.assertEqual(
                probe.count_production_invocations(repo), 0,
                "non-production + malformed lines in the prod file must not count",
            )
            self.assertEqual(probe.main([str(repo)]), 1)


if __name__ == "__main__":
    unittest.main()

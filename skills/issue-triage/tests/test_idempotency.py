"""T4 — Idempotency tests: same input -> same output (modulo generated_at).

Verifies that running build_triage_report() twice with identical inputs produces
identical output except for the generated_at timestamp field.

References:
  Mid-review concern 11: idempotency contract.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from collectors import CollectorResult
from triage import EXIT_PARTIAL, EXIT_OK, build_triage_report


def _ok_result_with_data(**kwargs: Any) -> CollectorResult:
    r = CollectorResult()
    r.data = {"collection_status": "ok", **kwargs}
    return r


def _make_fixed_results() -> list[CollectorResult]:
    """Return a fixed set of 5 CollectorResults for deterministic runs."""
    step1 = _ok_result_with_data(
        title="status normalize bug",
        body="Plugin version: 1.18.0\nSee `scripts/collectors/_inflight.py:42`",
        labels=["bug"],
        comments=[],
        state="open",
        number=101,
        url="https://forgejo.10cg.pub/10CG/Aria/issues/101",
        created_at="2026-05-01T10:00:00Z",
        updated_at="2026-05-10T14:30:00Z",
    )
    step2 = _ok_result_with_data(
        _triage_tool_version="1.19.0",
        reported="1.18.0",
        current="1.19.0",
        gap="behind",
    )
    step3 = _ok_result_with_data(
        cited_paths=[
            {
                "file_path": "scripts/collectors/_inflight.py",
                "line": 42,
                "format": "backtick",
                "exists": False,
                "line_in_range": None,
                "snippet": None,
                "warning": "file not found",
            }
        ],
        matches_description=False,
    )
    step4 = _ok_result_with_data(likely_fix_candidates=[])
    step5 = _ok_result_with_data(
        remote_prs=[],
        local_branches=[],
        worktrees=[],
    )
    return [step1, step2, step3, step4, step5]


class TestIdempotency:
    """Mid-review concern 11: same inputs produce same output (modulo generated_at)."""

    def _run_once(self, tmp_path: Path, ts: str) -> dict[str, Any]:
        """Run build_triage_report once with fixed collector results and a fixed timestamp."""
        steps = _make_fixed_results()

        with patch("triage.collect_issue", return_value=steps[0]), \
             patch("triage.collect_version", return_value=steps[1]), \
             patch("triage.collect_code", return_value=steps[2]), \
             patch("triage.collect_history", return_value=steps[3]), \
             patch("triage.collect_inflight", return_value=steps[4]), \
             patch("triage._now_iso", return_value=ts):
            report, code = build_triage_report("10CG/Aria", 101, tmp_path)
        return report

    def test_two_runs_identical_except_generated_at(self, tmp_path: Path) -> None:
        """Running twice with different timestamps -> all fields identical except generated_at.

        Mid-review concern 11: idempotency contract.
        """
        ts1 = "2026-05-13T10:00:00Z"
        ts2 = "2026-05-13T10:01:00Z"

        report1 = self._run_once(tmp_path, ts1)
        report2 = self._run_once(tmp_path, ts2)

        assert report1 != {} and report2 != {}, "Reports must not be empty"

        # generated_at is allowed to differ
        assert report1["generated_at"] == ts1
        assert report2["generated_at"] == ts2

        # Strip generated_at from both and compare
        r1 = copy.deepcopy(report1)
        r2 = copy.deepcopy(report2)
        del r1["generated_at"]
        del r2["generated_at"]

        assert r1 == r2, (
            "Reports differ beyond generated_at. "
            f"Keys that differ: {[k for k in r1 if r1.get(k) != r2.get(k)]}"
        )

    def test_same_timestamp_fully_identical(self, tmp_path: Path) -> None:
        """Same inputs AND same timestamp -> fully identical reports."""
        ts = "2026-05-13T10:00:00Z"

        report1 = self._run_once(tmp_path, ts)
        report2 = self._run_once(tmp_path, ts)

        assert report1 == report2, "Reports with identical inputs/timestamp must be identical"

    def test_json_serializable(self, tmp_path: Path) -> None:
        """Output report must be fully JSON-serializable."""
        ts = "2026-05-13T10:00:00Z"
        report = self._run_once(tmp_path, ts)

        try:
            serialized = json.dumps(report, ensure_ascii=False)
            deserialized = json.loads(serialized)
        except (TypeError, ValueError) as exc:
            pytest.fail(f"Report is not JSON-serializable: {exc}")

        assert deserialized == report

    def test_schema_version_stable(self, tmp_path: Path) -> None:
        """schema_version field must be stable across runs."""
        ts = "2026-05-13T10:00:00Z"
        report1 = self._run_once(tmp_path, ts)
        report2 = self._run_once(tmp_path, ts)
        assert report1["schema_version"] == report2["schema_version"]
        assert report1["schema_version"] == "1.0"

    def test_triage_tool_version_stable(self, tmp_path: Path) -> None:
        """triage_tool_version must be stable across runs."""
        ts = "2026-05-13T10:00:00Z"
        report1 = self._run_once(tmp_path, ts)
        report2 = self._run_once(tmp_path, ts)
        assert report1["triage_tool_version"] == report2["triage_tool_version"]

    def test_verdict_null_in_mechanical_output(self, tmp_path: Path) -> None:
        """Mechanical output scaffold: verdict must be null (not set by collectors)."""
        ts = "2026-05-13T10:00:00Z"
        report = self._run_once(tmp_path, ts)
        assert report["verdict"] is None, (
            "verdict must be null in mechanical collector output. "
            "AI sets verdict in Step 6."
        )

    def test_repro_scaffold_zero_hit_count(self, tmp_path: Path) -> None:
        """Mechanical output scaffold: repro.hit_count=0, total_count=0, hit_rate='0/0'."""
        ts = "2026-05-13T10:00:00Z"
        report = self._run_once(tmp_path, ts)
        repro = report["repro"]
        assert repro["hit_count"] == 0
        assert repro["total_count"] == 0
        assert repro["hit_rate"] == "0/0"
        assert repro["exit_mode"] is None
        assert repro["cases"] == []

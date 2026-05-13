"""T4.4 — Exit code boundary tests for steps_with_data thresholds.

Exit code contract (T1.8, R2 QA-R2-2):
  30 — steps_with_data < 2  (hard fail; report NOT written)
  10 — steps_with_data >= 2 AND <= 4
   0 — steps_with_data == 5

Evaluation order: 30 first, then 10, else 0.

Mid-review concern 3: synthesize collector results with steps_with_data in
{0, 1, 2, 4, 5} and assert the correct exit codes.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

# Ensure scripts/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from triage import EXIT_HARD_FAIL, EXIT_OK, EXIT_PARTIAL, _step_has_data, build_triage_report
from collectors import CollectorResult


def _ok_result(**extra: Any) -> CollectorResult:
    """Return a CollectorResult with collection_status=ok."""
    r = CollectorResult()
    r.data = {"collection_status": "ok", **extra}
    return r


def _err_result(**extra: Any) -> CollectorResult:
    """Return a CollectorResult with collection_status=error."""
    r = CollectorResult()
    r.data = {"collection_status": "error", **extra}
    return r


class TestStepHasData:
    """Unit tests for the _step_has_data predicate in triage.py."""

    def test_ok_status_has_data(self) -> None:
        """collection_status=ok -> _step_has_data returns True."""
        r = _ok_result()
        assert _step_has_data(r) is True

    def test_error_status_no_data(self) -> None:
        """collection_status=error -> _step_has_data returns False."""
        r = _err_result()
        assert _step_has_data(r) is False

    def test_skipped_status_no_data(self) -> None:
        """collection_status=skipped -> _step_has_data returns False.

        Skipped steps do not count as 'data-producing' for the threshold.
        """
        r = CollectorResult()
        r.data = {"collection_status": "skipped"}
        assert _step_has_data(r) is False


class TestExitCodeBoundaries:
    """Mid-review concern 3: boundary tests for steps_with_data thresholds.

    All tests monkeypatch the 5 collectors to return synthetic results.
    """

    def _make_steps(self, n_ok: int) -> list[CollectorResult]:
        """Return a list of 5 CollectorResults: first n_ok are 'ok', rest 'error'."""
        results = []
        for i in range(5):
            if i < n_ok:
                results.append(_ok_result())
            else:
                results.append(_err_result())
        return results

    def _run_with_n_ok(self, n_ok: int, tmp_path: Path) -> tuple[dict, int]:
        """Run build_triage_report with n_ok collectors returning ok status."""
        steps = self._make_steps(n_ok)

        # step1 needs extra fields for triage.py to proceed
        steps[0].data.update({"body": "", "comments": [], "title": "", "labels": [], "state": "", "number": 101})
        # step2 needs _triage_tool_version
        steps[1].data.update({"_triage_tool_version": "1.19.0", "current": "1.19.0", "reported": None, "gap": None})
        # step3 needs cited_paths
        steps[2].data.update({"cited_paths": [], "matches_description": None})
        # step4 needs likely_fix_candidates
        steps[3].data.update({"likely_fix_candidates": []})
        # step5 needs three sections
        steps[4].data.update({"remote_prs": [], "local_branches": [], "worktrees": []})

        with patch("triage.collect_issue", return_value=steps[0]), \
             patch("triage.collect_version", return_value=steps[1]), \
             patch("triage.collect_code", return_value=steps[2]), \
             patch("triage.collect_history", return_value=steps[3]), \
             patch("triage.collect_inflight", return_value=steps[4]):
            return build_triage_report("10CG/Aria", 101, tmp_path)

    def test_zero_steps_exit_30(self, tmp_path: Path) -> None:
        """steps_with_data=0 -> exit code 30 (hard fail).

        Mid-review concern 3: 0 steps -> EXIT_HARD_FAIL.
        """
        report, code = self._run_with_n_ok(0, tmp_path)
        assert code == EXIT_HARD_FAIL

    def test_one_step_exit_30(self, tmp_path: Path) -> None:
        """steps_with_data=1 -> exit code 30 (hard fail, still < 2).

        Mid-review concern 3: 1 step -> EXIT_HARD_FAIL.
        """
        report, code = self._run_with_n_ok(1, tmp_path)
        assert code == EXIT_HARD_FAIL

    def test_two_steps_exit_10(self, tmp_path: Path) -> None:
        """steps_with_data=2 -> exit code 10 (partial, >= 2 AND <= 4).

        Mid-review concern 3: 2 steps -> EXIT_PARTIAL (boundary at 2).
        """
        report, code = self._run_with_n_ok(2, tmp_path)
        assert code == EXIT_PARTIAL

    def test_four_steps_exit_10(self, tmp_path: Path) -> None:
        """steps_with_data=4 -> exit code 10 (partial, >= 2 AND <= 4).

        Mid-review concern 3: 4 steps -> EXIT_PARTIAL (boundary at 4).
        """
        report, code = self._run_with_n_ok(4, tmp_path)
        assert code == EXIT_PARTIAL

    def test_five_steps_exit_0(self, tmp_path: Path) -> None:
        """steps_with_data=5 -> exit code 0 (all succeeded).

        Mid-review concern 3: 5 steps -> EXIT_OK.
        """
        report, code = self._run_with_n_ok(5, tmp_path)
        assert code == EXIT_OK

    def test_hard_fail_returns_empty_report(self, tmp_path: Path) -> None:
        """Exit code 30 must return an empty report dict (not written to disk).

        T1.8: hard fail — report NOT written.
        """
        report, code = self._run_with_n_ok(0, tmp_path)
        assert code == EXIT_HARD_FAIL
        assert report == {}

    def test_partial_report_has_required_keys(self, tmp_path: Path) -> None:
        """Exit code 10 (partial) still produces a report with required top-level keys."""
        report, code = self._run_with_n_ok(2, tmp_path)
        assert code == EXIT_PARTIAL
        for key in ("schema_version", "issue_ref", "steps", "repro", "verdict", "errors"):
            assert key in report, f"Missing required key: {key}"

    def test_exit_0_report_has_required_keys(self, tmp_path: Path) -> None:
        """Exit code 0 produces a report with required top-level keys."""
        report, code = self._run_with_n_ok(5, tmp_path)
        assert code == EXIT_OK
        for key in ("schema_version", "issue_ref", "steps", "repro", "verdict", "errors"):
            assert key in report, f"Missing required key: {key}"


class TestMainCLIExitCodes:
    """Integration-level: main() does not write report on EXIT_HARD_FAIL."""

    def test_hard_fail_does_not_write_output_file(self, tmp_path: Path) -> None:
        """Exit 30: main() must NOT write the output file.

        T1.8: 'hard fail — report NOT written'.
        """
        output_file = tmp_path / "report.json"

        def fake_build(owner_repo: str, issue_number: int, project_root: Path):
            return {}, EXIT_HARD_FAIL

        with patch("triage.build_triage_report", side_effect=fake_build):
            from triage import main
            code = main([
                "--issue", "10CG/Aria#101",
                "--output", str(output_file),
                "--project-root", str(tmp_path),
            ])

        assert code == EXIT_HARD_FAIL
        assert not output_file.exists(), "Report file must NOT be written on hard fail"

    def test_partial_writes_output_file(self, tmp_path: Path) -> None:
        """Exit 10: main() writes the report file."""
        output_file = tmp_path / "report.json"

        def fake_build(owner_repo: str, issue_number: int, project_root: Path):
            return {
                "schema_version": "1.0",
                "triage_tool_version": "1.19.0",
                "issue_ref": "10CG/Aria#101",
                "generated_at": "2026-05-13T00:00:00Z",
                "steps": {},
                "repro": {"exit_mode": None, "cases": [], "hit_count": 0, "total_count": 0, "hit_rate": "0/0"},
                "verdict": None,
                "severity": None,
                "recommended_action": None,
                "deviation_note": None,
                "errors": [],
            }, EXIT_PARTIAL

        with patch("triage.build_triage_report", side_effect=fake_build):
            from triage import main
            code = main([
                "--issue", "10CG/Aria#101",
                "--output", str(output_file),
                "--project-root", str(tmp_path),
            ])

        assert code == EXIT_PARTIAL
        assert output_file.exists(), "Report file MUST be written on partial success"

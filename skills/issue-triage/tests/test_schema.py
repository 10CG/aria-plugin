"""T4.1 — JSON schema validation tests.

Covers:
  - Mid-review concern 1: partial-repro conditional
  - Mid-review concern 2: mechanical scaffold passes (verdict=null)
  - Positive validation for all 7 verdict values
  - Negative validation for structural violations

References:
  T1.7 (schema design), T4.1 (validation test requirement)
  Mid-review M1: schema negative partial-repro
  Mid-review M2: mechanical scaffold positive
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

jsonschema = pytest.importorskip(
    "jsonschema",
    reason="python3-jsonschema not installed — install via: sudo apt-get install python3-jsonschema",
)

_SCHEMA_PATH = (
    Path(__file__).parent.parent / "references" / "triage-report.schema.json"
)


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    """Load the triage report JSON schema."""
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _validate(instance: dict[str, Any], schema: dict[str, Any]) -> None:
    """Validate instance against schema; raises jsonschema.ValidationError on failure."""
    jsonschema.validate(instance=instance, schema=schema)


def _should_fail(instance: dict[str, Any], schema: dict[str, Any]) -> None:
    """Assert that instance fails schema validation."""
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=instance, schema=schema)


# ── Positive: mechanical output scaffold ─────────────────────────────────────

class TestSchemaPositive:
    """Mid-review concern 2: mechanical output scaffold must pass schema."""

    def test_minimal_scaffold_passes(self, schema: dict[str, Any], minimal_valid_report: dict[str, Any]) -> None:
        """verdict=null, deviation_note=null -> passes (conditional only fires on partial-repro).

        Mid-review concern 2: mechanical-output scaffold must be schema-valid.
        """
        _validate(minimal_valid_report, schema)

    def test_verdict_confirmed_no_deviation_note(self, schema: dict[str, Any], minimal_valid_report: dict[str, Any]) -> None:
        """verdict=confirmed without deviation_note -> passes (deviation_note only required for partial-repro)."""
        report = copy.deepcopy(minimal_valid_report)
        report["verdict"] = "confirmed"
        report["severity"] = "major"
        report["recommended_action"] = "hotfix"
        _validate(report, schema)

    def test_verdict_partial_repro_with_deviation_note(self, schema: dict[str, Any], minimal_valid_report: dict[str, Any]) -> None:
        """verdict=partial-repro + non-empty deviation_note -> passes.

        Mid-review concern 1 (positive case): partial-repro + filled deviation_note is valid.
        """
        report = copy.deepcopy(minimal_valid_report)
        report["verdict"] = "partial-repro"
        report["severity"] = "minor"
        report["deviation_note"] = "Reproduced 2/4 cases; main crash missing, side effect present"
        _validate(report, schema)

    def test_all_seven_verdict_values(self, schema: dict[str, Any], minimal_valid_report: dict[str, Any]) -> None:
        """All 7 verdict enum values are accepted (non-partial-repro ones don't need deviation_note)."""
        non_partial_verdicts = [
            "confirmed",
            "not-reproducible",
            "fixed-in-X",
            "duplicate-of-#N",
            "needs-info",
            "wont-fix",
        ]
        for verdict in non_partial_verdicts:
            report = copy.deepcopy(minimal_valid_report)
            report["verdict"] = verdict
            _validate(report, schema)

    def test_all_severity_values(self, schema: dict[str, Any], minimal_valid_report: dict[str, Any]) -> None:
        """All 4 severity enum values are accepted."""
        for severity in ("critical", "major", "minor", "trivial"):
            report = copy.deepcopy(minimal_valid_report)
            report["verdict"] = "confirmed"
            report["severity"] = severity
            _validate(report, schema)

    def test_all_recommended_action_values(self, schema: dict[str, Any], minimal_valid_report: dict[str, Any]) -> None:
        """All 4 recommended_action enum values are accepted."""
        for action in ("hotfix", "next-cycle", "backlog", "close"):
            report = copy.deepcopy(minimal_valid_report)
            report["recommended_action"] = action
            _validate(report, schema)

    def test_repro_with_cases(self, schema: dict[str, Any], minimal_valid_report: dict[str, Any]) -> None:
        """Repro section with populated cases validates correctly."""
        report = copy.deepcopy(minimal_valid_report)
        report["repro"] = {
            "exit_mode": "auto",
            "cases": [
                {
                    "case_id": "C1",
                    "input": "run triage --issue 101",
                    "expected_behavior": "exit 0",
                    "actual_behavior": "exit 10",
                    "match": False,
                    "notes": "step5 returned error",
                }
            ],
            "hit_count": 0,
            "total_count": 1,
            "hit_rate": "0/1",
        }
        report["verdict"] = "confirmed"
        _validate(report, schema)

    def test_cited_path_entry(self, schema: dict[str, Any], minimal_valid_report: dict[str, Any]) -> None:
        """A step3_code with cited_paths entries passes schema."""
        report = copy.deepcopy(minimal_valid_report)
        report["steps"]["step3_code"] = {
            "collection_status": "ok",
            "cited_paths": [
                {
                    "file_path": "scripts/collectors/_inflight.py",
                    "line": 42,
                    "format": "backtick",
                    "exists": True,
                    "line_in_range": True,
                    "snippet": "42: section_errors.append(...)",
                    "warning": None,
                }
            ],
            "matches_description": True,
        }
        _validate(report, schema)


# ── Negative: partial-repro conditional ─────────────────────────────────────

class TestSchemaPartialReproNegative:
    """Mid-review concern 1: partial-repro + missing/null deviation_note must fail.

    T4.1 requirement: schema negative tests for partial-repro conditional.
    """

    def test_partial_repro_deviation_note_null_fails(self, schema: dict[str, Any], minimal_valid_report: dict[str, Any]) -> None:
        """verdict=partial-repro + deviation_note=null -> schema validation fails.

        Mid-review concern 1 (negative case #1).
        """
        report = copy.deepcopy(minimal_valid_report)
        report["verdict"] = "partial-repro"
        report["deviation_note"] = None  # null is not allowed when partial-repro
        _should_fail(report, schema)

    def test_partial_repro_deviation_note_key_missing_fails(self, schema: dict[str, Any], minimal_valid_report: dict[str, Any]) -> None:
        """verdict=partial-repro + deviation_note key absent -> schema validation fails.

        Mid-review concern 1 (negative case #2): key completely missing.
        """
        report = copy.deepcopy(minimal_valid_report)
        report["verdict"] = "partial-repro"
        report.pop("deviation_note", None)  # remove the key entirely
        _should_fail(report, schema)

    def test_partial_repro_empty_string_deviation_note_fails(self, schema: dict[str, Any], minimal_valid_report: dict[str, Any]) -> None:
        """verdict=partial-repro + deviation_note="" (empty string) -> fails (minLength: 1)."""
        report = copy.deepcopy(minimal_valid_report)
        report["verdict"] = "partial-repro"
        report["deviation_note"] = ""
        _should_fail(report, schema)


# ── Negative: structural violations ──────────────────────────────────────────

class TestSchemaNegativeStructural:
    """Schema rejects structurally invalid reports."""

    def test_missing_required_top_level_field(self, schema: dict[str, Any], minimal_valid_report: dict[str, Any]) -> None:
        """Removing a required top-level field fails validation."""
        report = copy.deepcopy(minimal_valid_report)
        del report["issue_ref"]
        _should_fail(report, schema)

    def test_invalid_verdict_enum(self, schema: dict[str, Any], minimal_valid_report: dict[str, Any]) -> None:
        """verdict must be one of 7 values or null."""
        report = copy.deepcopy(minimal_valid_report)
        report["verdict"] = "invalid-verdict"
        _should_fail(report, schema)

    def test_invalid_severity_enum(self, schema: dict[str, Any], minimal_valid_report: dict[str, Any]) -> None:
        """severity must be in the allowed enum or null."""
        report = copy.deepcopy(minimal_valid_report)
        report["severity"] = "extreme"
        _should_fail(report, schema)

    def test_invalid_hit_rate_format(self, schema: dict[str, Any], minimal_valid_report: dict[str, Any]) -> None:
        """hit_rate must match N/M pattern."""
        report = copy.deepcopy(minimal_valid_report)
        report["repro"]["hit_rate"] = "2-of-4"
        _should_fail(report, schema)

    def test_missing_steps_object(self, schema: dict[str, Any], minimal_valid_report: dict[str, Any]) -> None:
        """Missing 'steps' key fails validation."""
        report = copy.deepcopy(minimal_valid_report)
        del report["steps"]
        _should_fail(report, schema)

    def test_invalid_collection_status(self, schema: dict[str, Any], minimal_valid_report: dict[str, Any]) -> None:
        """collection_status must be 'ok', 'error', or 'skipped'."""
        report = copy.deepcopy(minimal_valid_report)
        report["steps"]["step1_issue"]["collection_status"] = "unknown"
        _should_fail(report, schema)

    def test_errors_array_item_missing_required_field(self, schema: dict[str, Any], minimal_valid_report: dict[str, Any]) -> None:
        """Error array items must have step, error, detail fields."""
        report = copy.deepcopy(minimal_valid_report)
        report["errors"] = [{"step": "step1_issue", "error": "cli_missing"}]  # missing 'detail'
        _should_fail(report, schema)

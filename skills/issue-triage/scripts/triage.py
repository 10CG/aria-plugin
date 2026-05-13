#!/usr/bin/env python3
"""issue-triage mechanical collector — entry point.

Spec: openspec/changes/aria-issue-triage-sop/
Schema: aria/skills/issue-triage/references/triage-report-schema.md

Accepts an issue reference, runs 5 mechanical collection steps, and writes
a triage-report.json. Step 6 (reproduction) and verdict fields are left as
placeholders to be filled by AI after review of the JSON output.

Coverage (schema v1.0):
  Step 1: Read issue body + comments + labels (forgejo CLI)
  Step 2: Version check reported vs current (fail-soft 5-path chain)
  Step 3: Code path verification (3 citation formats: backtick / prose / md-link)
  Step 4: Git log on cited files (likely_fix_candidates: [{sha, message, match_reason}])
  Step 5: In-flight check (remote_prs / local_branches / worktrees)

Exit code contract (T1.8, R2 QA-R2-2 — evaluation order: 30 first, then 10, else 0):
  0  — all 5 collectors succeeded (steps_with_data == 5)
  10 — partial collector errors (steps_with_data >= 2 AND <= 4)
  30 — hard fail (steps_with_data < 2) — report NOT written

stdlib-only: argparse, json, logging, os, pathlib, re, sys, subprocess, datetime.
No third-party dependencies.

Rule #7 (secret-hygiene): all forgejo subprocess calls use capture_output=True.
Tokens are never echoed to stdout/stderr.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Add the scripts/ directory to sys.path so `collectors` package is importable
# when triage.py is run directly (e.g. python scripts/triage.py ...).
_SCRIPTS_DIR = Path(__file__).parent.resolve()
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from collectors import (  # noqa: E402
    CollectorResult,
    collect_code,
    collect_history,
    collect_inflight,
    collect_issue,
    collect_version,
    log,
)

# ── Constants ────────────────────────────────────────────────────────────────

TRIAGE_REPORT_SCHEMA_VERSION = "1.0"

EXIT_OK = 0           # all 5 collectors succeeded
EXIT_PARTIAL = 10     # steps_with_data >= 2 AND <= 4
EXIT_HARD_FAIL = 30   # steps_with_data < 2 — do NOT write report

LOG_LEVEL_CHOICES = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

# Default owner/repo for bare issue number references
DEFAULT_OWNER_REPO = "10CG/Aria"

# ── Issue reference parsing ──────────────────────────────────────────────────

_ISSUE_URL_RE = re.compile(
    r"(?:https?://[^/]+)?/?([^/]+/[^/]+)/issues/(\d+)", re.IGNORECASE
)
_OWNER_REPO_NUM_RE = re.compile(r"^([^/#]+/[^/#]+)#(\d+)$")
_BARE_NUM_RE = re.compile(r"^#?(\d+)$")


def _parse_issue_ref(issue_arg: str, default_owner_repo: str) -> tuple[str, int] | None:
    """Parse an issue reference into (owner/repo, issue_number).

    Accepted formats:
      - https://forgejo.example.com/owner/repo/issues/42
      - owner/repo#42
      - 42  or  #42  (uses default_owner_repo)

    Returns None if parsing fails.
    """
    s = issue_arg.strip()

    # URL form
    m = _ISSUE_URL_RE.search(s)
    if m:
        return m.group(1), int(m.group(2))

    # owner/repo#N form
    m = _OWNER_REPO_NUM_RE.match(s)
    if m:
        return m.group(1), int(m.group(2))

    # Bare number (uses default)
    m = _BARE_NUM_RE.match(s)
    if m:
        return default_owner_repo, int(m.group(1))

    return None


# ── Snapshot builder ─────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _collection_status(result: CollectorResult) -> str:
    return result.data.get("collection_status", "error")


def _step_has_data(result: CollectorResult) -> bool:
    """Return True if a collector produced usable data (status ok or partial)."""
    status = _collection_status(result)
    return status in ("ok",)


def build_triage_report(
    owner_repo: str,
    issue_number: int,
    project_root: Path,
) -> tuple[dict[str, Any], int]:
    """Run all 5 collectors and return (report_dict, exit_code).

    Exit code evaluation order (R2 QA-R2-2):
      1. Check hard fail threshold first (< 2 steps with data → exit 30)
      2. Then partial (2-4 steps → exit 10)
      3. Otherwise exit 0
    """
    issue_ref = f"{owner_repo}#{issue_number}"
    errors: list[dict[str, Any]] = []

    # ── Step 1: Read issue ───────────────────────────────────────────────────
    step1 = collect_issue(owner_repo, issue_number, project_root)
    for err in step1.errors:
        errors.append({"step": "step1_issue", **err})

    issue_body = step1.data.get("body", "")
    issue_comments = step1.data.get("comments", [])

    # ── Step 2: Version check ────────────────────────────────────────────────
    step2 = collect_version(project_root, issue_body, issue_comments)
    for err in step2.errors:
        errors.append({"step": "step2_version", **err})

    # Extract triage_tool_version (R2 QA-R2-m3)
    triage_tool_version: str = step2.data.pop("_triage_tool_version", "unknown")

    # ── Step 3: Code path verification ──────────────────────────────────────
    step3 = collect_code(project_root, issue_body, issue_comments)
    for err in step3.errors:
        errors.append({"step": "step3_code", **err})

    cited_paths = step3.data.get("cited_paths", [])

    # ── Step 4: Git history ──────────────────────────────────────────────────
    step4 = collect_history(project_root, cited_paths, issue_number)
    for err in step4.errors:
        errors.append({"step": "step4_history", **err})

    # ── Step 5: In-flight check ──────────────────────────────────────────────
    step5 = collect_inflight(owner_repo, project_root, issue_number, cited_paths)
    for err in step5.errors:
        errors.append({"step": "step5_inflight", **err})

    # ── Pre-flight sanity check (T1.1, T1.8) ────────────────────────────────
    steps_with_data = sum(
        1 for s in [step1, step2, step3, step4, step5] if _step_has_data(s)
    )
    log.info(
        "triage: steps_with_data=%d/5 for %s",
        steps_with_data,
        issue_ref,
    )

    # Determine exit code (evaluate 30 first, then 10, else 0)
    if steps_with_data < 2:
        return {}, EXIT_HARD_FAIL

    # ── Assemble report ──────────────────────────────────────────────────────
    report: dict[str, Any] = {
        "schema_version": TRIAGE_REPORT_SCHEMA_VERSION,
        "triage_tool_version": triage_tool_version,
        "issue_ref": issue_ref,
        "generated_at": _now_iso(),
        "steps": {
            "step1_issue": step1.data,
            "step2_version": step2.data,
            "step3_code": step3.data,
            "step4_history": step4.data,
            "step5_inflight": step5.data,
        },
        # Step 6 (reproduction) is filled by AI after reviewing this report.
        # Placeholder structure provided for schema compliance.
        "repro": {
            "exit_mode": None,
            "cases": [],
            "hit_count": 0,
            "total_count": 0,
            "hit_rate": "0/0",
        },
        # Verdict and severity are AI-determined in Step 6.
        "verdict": None,
        "severity": None,
        "recommended_action": None,
        "deviation_note": None,
        "errors": errors,
    }

    if steps_with_data <= 4:
        exit_code = EXIT_PARTIAL
    else:
        exit_code = EXIT_OK

    return report, exit_code


# ── CLI ───────────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="triage.py",
        description=(
            "issue-triage mechanical collector. "
            "Runs Steps 1-5, writes triage-report.json. "
            "Step 6 (reproduction) is performed by AI."
        ),
    )

    issue_group = parser.add_mutually_exclusive_group(required=True)
    issue_group.add_argument(
        "--issue",
        metavar="REF",
        help=(
            "Issue reference: '<owner>/<repo>#N', bare number N, "
            "or https://forgejo.example.com/owner/repo/issues/N"
        ),
    )
    issue_group.add_argument(
        "--issue-url",
        metavar="URL",
        help="Full Forgejo issue URL (alternative to --issue)",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".aria/triage-report.json"),
        help="Output path for triage-report.json (default: .aria/triage-report.json)",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Project root directory (default: cwd)",
    )
    parser.add_argument(
        "--default-repo",
        metavar="OWNER/REPO",
        default=DEFAULT_OWNER_REPO,
        help=f"Default owner/repo for bare issue numbers (default: {DEFAULT_OWNER_REPO})",
    )

    env_level = os.environ.get("TRIAGE_LOG_LEVEL", "WARNING").upper()
    default_level = env_level if env_level in LOG_LEVEL_CHOICES else "WARNING"
    parser.add_argument(
        "--log-level",
        choices=LOG_LEVEL_CHOICES,
        type=str.upper,
        default=default_level,
        help=f"Logging level (default: {default_level}; env TRIAGE_LOG_LEVEL)",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level, logging.WARNING),
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    # Resolve issue reference
    issue_arg = args.issue or args.issue_url
    parsed = _parse_issue_ref(issue_arg, args.default_repo)
    if parsed is None:
        print(
            f"ERROR: Cannot parse issue reference: {issue_arg!r}. "
            "Use '<owner>/<repo>#N', a bare number, or a full Forgejo URL.",
            file=sys.stderr,
        )
        return EXIT_HARD_FAIL

    owner_repo, issue_number = parsed
    project_root = args.project_root.resolve()

    log.info(
        "triage: starting — issue=%s#%d project_root=%s",
        owner_repo, issue_number, project_root,
    )

    try:
        report, exit_code = build_triage_report(owner_repo, issue_number, project_root)
    except Exception:
        log.exception("triage: uncaught error in build_triage_report")
        print(
            "ERROR: Unexpected internal error — check --log-level DEBUG for details.",
            file=sys.stderr,
        )
        return EXIT_HARD_FAIL

    # Pre-flight gate: do NOT write report when hard fail
    if exit_code == EXIT_HARD_FAIL:
        print(
            "Insufficient data — check credentials and issue ref",
            file=sys.stderr,
        )
        return EXIT_HARD_FAIL

    # Write report
    rendered = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=False)
    output_path: Path = args.output
    if not output_path.is_absolute():
        output_path = project_root / output_path

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"ERROR: Cannot write report to {output_path}: {exc}", file=sys.stderr)
        return EXIT_HARD_FAIL

    log.info("triage: report written to %s (exit=%d)", output_path, exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())

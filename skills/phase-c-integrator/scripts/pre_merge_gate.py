#!/usr/bin/env python3
"""Pre-merge precondition gate helper for phase-c-integrator C.2.4.

Forgejo Issue #60 — consume aether `aether ci status --in-flight` primitive
(aether-cli #116, SHA f29abee 2026-05-06) and compute three-state verdict
(green / wait / fail) on the aria side. The aether-pre-merge-check skill
(P0-B) was never shipped; verdict computation lives in this helper.

stdlib + subprocess only (no third-party deps). Cross-platform: assumes
POSIX-like shell for `which`. Windows users go through Git Bash / WSL.

Usage (CLI):
    pre_merge_gate.py --pr-branch <branch> [--main-branch main] [--config-file path]

Output: single JSON line on stdout matching SKILL.md §C.2.4 Output schema.
Exit code: 0 = success (any verdict). Non-zero = helper failure
(distinct from gate verdict=fail which is a successful query).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import shutil
import subprocess
import sys
import time
from typing import Any

# aether-cli baseline (from spec D1 §Contract Source).
AETHER_CLI_MIN_SHA = "f29abee"
AETHER_CLI_MIN_DATE = "2026-05-06"

# Subprocess retry backoff (seconds) when primitive_call_timeout fires.
RETRY_BACKOFF = (5, 15, 45)
MAX_RETRY_ATTEMPTS = len(RETRY_BACKOFF)

# Verdict enum values.
VERDICT_GREEN = "green"
VERDICT_WAIT = "wait"
VERDICT_FAIL = "fail"

DEFAULT_CONFIG = {
    "enabled": True,
    "primitive_preference": ["aether-ci-cli"],
    "no_aether_fallback": "skip_with_warning",
    "wait_timeout_seconds": 1800,
    "wait_check_intervals": [30, 60, 120, 300, 300],
    "primitive_call_timeout_seconds": 30,
    "poll_chunk_seconds": 5,
    "user_escape_hatch": True,
}


def detect_aether() -> tuple[bool, str | None]:
    """Return (available, aether_binary_path)."""
    binary = shutil.which("aether")
    if binary:
        return True, binary
    config_yaml = os.path.expanduser("~/.aether/config.yaml")
    if os.path.exists(config_yaml):
        # Config exists but binary missing — treat as not available so
        # caller routes through no_aether_fallback rather than failing
        # mid-call. The presence of config is informational only.
        return False, None
    return False, None


def verify_aether_in_flight_flag(binary: str, timeout: int = 5) -> bool:
    """Return True if `aether ci status --help` advertises `--in-flight`.

    Older binaries (pre PR #116, before 2026-05-06) lack this flag and
    must be upgraded before the gate can function. We grep stdout to
    avoid version-string parsing.
    """
    try:
        result = subprocess.run(
            [binary, "ci", "status", "--help"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
    haystack = (result.stdout or "") + (result.stderr or "")
    return "in-flight" in haystack


def _run_aether_with_retry(
    binary: str, args: list[str], timeout: int
) -> tuple[int, str, str]:
    """Run aether subprocess with timeout + retry. Return (exit_code, stdout, stderr).

    Retries on TimeoutExpired only; other exceptions bubble up. SIGTERM-induced
    timeout returns exit_code -15 in Python's subprocess convention; we map
    that to a synthetic -1 exit code in the caller for clarity.
    """
    last_exc: subprocess.TimeoutExpired | None = None
    for attempt in range(MAX_RETRY_ATTEMPTS):
        try:
            result = subprocess.run(
                [binary] + args,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return result.returncode, result.stdout or "", result.stderr or ""
        except subprocess.TimeoutExpired as exc:
            last_exc = exc
            if attempt < MAX_RETRY_ATTEMPTS - 1:
                time.sleep(RETRY_BACKOFF[attempt])
    # All retries exhausted — return synthetic timeout exit code.
    stderr = f"primitive call timeout after {MAX_RETRY_ATTEMPTS} attempts"
    if last_exc is not None:
        stderr += f" (last: {last_exc})"
    return -1, "", stderr


def _query_aether(
    binary: str, branch: str, in_flight_only: bool, timeout: int
) -> tuple[bool, dict[str, Any] | None, str]:
    """Call `aether ci status` and parse JSON. Return (ok, parsed_data, error_msg).

    `parsed_data` is the contents of the top-level `data` field on success.
    Malformed JSON / unexpected schema → ok=False with error_msg populated.
    """
    args = ["ci", "status", "--branch", branch, "--json"]
    if in_flight_only:
        args.append("--in-flight")
    code, stdout, stderr = _run_aether_with_retry(binary, args, timeout=timeout)
    if code != 0:
        msg = stderr.strip() or f"aether exit {code}"
        return False, None, msg
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return False, None, f"malformed JSON from aether: {exc}"
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        return False, None, f"unexpected aether payload shape: {stdout[:200]}"
    data = payload.get("data")
    if not isinstance(data, dict):
        return False, None, "aether payload missing data object"
    return True, data, ""


def _normalize_pr_ci_status(runs: list[dict[str, Any]]) -> str:
    """Map aether CIRun list → passing | failing | pending.

    Takes the most recent run (assumed first in list). Conservative mapping:
    unknown statuses route to pending so the caller waits rather than races.
    """
    if not runs:
        return "pending"
    latest = runs[0]
    status = (latest.get("status") or "").lower()
    if status in ("success", "passing", "passed", "completed"):
        return "passing"
    if status in ("failure", "failing", "failed", "error", "cancelled", "canceled"):
        return "failing"
    return "pending"


def _translate_in_flight_run(aether_run: dict[str, Any]) -> dict[str, Any]:
    """aether CIRun dict → internal in_flight_runs[] schema.

    Field mapping per SKILL.md §C.2.4 Output schema:
      id          → run_id
      branch      → branch
      started_at  → started_at (assumed ISO 8601 from aether)
      [computed]  → elapsed_seconds (now - started_at)
    Missing/malformed fields default rather than raise; gate must be robust.
    """
    started_at = aether_run.get("started_at") or ""
    elapsed = 0
    if started_at:
        try:
            # aether emits ISO 8601 with trailing Z; fromisoformat needs +00:00.
            iso = started_at.replace("Z", "+00:00")
            started_dt = _dt.datetime.fromisoformat(iso)
            now_dt = _dt.datetime.now(_dt.timezone.utc)
            elapsed = max(0, int((now_dt - started_dt).total_seconds()))
        except (ValueError, TypeError):
            elapsed = 0
    return {
        "run_id": aether_run.get("id") or aether_run.get("run_id") or 0,
        "branch": aether_run.get("branch") or "",
        "started_at": started_at,
        "elapsed_seconds": elapsed,
    }


def compute_verdict(
    main_in_flight_runs: list[dict[str, Any]], pr_ci_status: str
) -> str:
    """Compute three-state verdict per SKILL.md §C.2.4 step 5."""
    if pr_ci_status in ("failing", "error"):
        return VERDICT_FAIL
    if pr_ci_status == "pending":
        return VERDICT_WAIT
    # pr_ci_status == "passing"
    if not main_in_flight_runs:
        return VERDICT_GREEN
    return VERDICT_WAIT


def _build_output(
    verdict: str,
    pr_ci_status: str,
    in_flight_runs: list[dict[str, Any]],
    primitive_used: str,
    raw_message: str = "",
) -> dict[str, Any]:
    return {
        "verdict": verdict,
        "pr_ci_status": pr_ci_status,
        "in_flight_runs": in_flight_runs,
        "primitive_used": primitive_used,
        "primitive_version_sha": AETHER_CLI_MIN_SHA,
        "raw_message": raw_message,
    }


def _no_aether_output(no_aether_fallback: str) -> dict[str, Any]:
    """Build output for the no-aether-detected case per fallback config."""
    if no_aether_fallback == "abort":
        return _build_output(
            verdict=VERDICT_FAIL,
            pr_ci_status="pending",
            in_flight_runs=[],
            primitive_used="manual",
            raw_message=(
                "aether binary not available and no_aether_fallback=abort: "
                "install aether or set no_aether_fallback=skip_with_warning"
            ),
        )
    # skip_with_warning (default): treat as green so workflow proceeds, but
    # mark the message so callers / reports surface the skip.
    return _build_output(
        verdict=VERDICT_GREEN,
        pr_ci_status="pending",
        in_flight_runs=[],
        primitive_used="manual",
        raw_message=(
            "aether binary not available; gate skipped per no_aether_fallback=skip_with_warning"
        ),
    )


def gate_check(
    pr_branch: str,
    main_branch: str = "main",
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the pre-merge gate end-to-end. Return SKILL.md §C.2.4 output dict.

    Exceptions are caught and translated into verdict=fail with raw_message —
    callers can rely on a structured return rather than try/except.
    """
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    if not cfg["enabled"]:
        return _build_output(
            verdict=VERDICT_GREEN,
            pr_ci_status="pending",
            in_flight_runs=[],
            primitive_used="manual",
            raw_message="pre_merge_gate.enabled=false; gate skipped",
        )
    available, binary = detect_aether()
    if not available or binary is None:
        return _no_aether_output(cfg["no_aether_fallback"])
    if not verify_aether_in_flight_flag(binary):
        return _build_output(
            verdict=VERDICT_FAIL,
            pr_ci_status="pending",
            in_flight_runs=[],
            primitive_used="aether-ci-cli",
            raw_message=(
                f"aether binary at {binary} lacks --in-flight flag; "
                f"upgrade to aether-cli >= commit {AETHER_CLI_MIN_SHA} "
                f"({AETHER_CLI_MIN_DATE})"
            ),
        )
    timeout = int(cfg["primitive_call_timeout_seconds"])
    main_ok, main_data, main_err = _query_aether(
        binary, branch=main_branch, in_flight_only=True, timeout=timeout
    )
    if not main_ok:
        return _build_output(
            verdict=VERDICT_FAIL,
            pr_ci_status="pending",
            in_flight_runs=[],
            primitive_used="aether-ci-cli",
            raw_message=f"main in-flight query failed: {main_err}",
        )
    pr_ok, pr_data, pr_err = _query_aether(
        binary, branch=pr_branch, in_flight_only=False, timeout=timeout
    )
    if not pr_ok:
        return _build_output(
            verdict=VERDICT_FAIL,
            pr_ci_status="pending",
            in_flight_runs=[],
            primitive_used="aether-ci-cli",
            raw_message=f"PR CI status query failed: {pr_err}",
        )
    main_runs_raw = main_data.get("runs") or []
    pr_runs_raw = pr_data.get("runs") or []
    if not isinstance(main_runs_raw, list) or not isinstance(pr_runs_raw, list):
        return _build_output(
            verdict=VERDICT_FAIL,
            pr_ci_status="pending",
            in_flight_runs=[],
            primitive_used="aether-ci-cli",
            raw_message="aether returned non-list runs field",
        )
    in_flight_runs = [_translate_in_flight_run(r) for r in main_runs_raw if isinstance(r, dict)]
    pr_ci_status = _normalize_pr_ci_status([r for r in pr_runs_raw if isinstance(r, dict)])
    verdict = compute_verdict(in_flight_runs, pr_ci_status)
    return _build_output(
        verdict=verdict,
        pr_ci_status=pr_ci_status,
        in_flight_runs=in_flight_runs,
        primitive_used="aether-ci-cli",
        raw_message="",
    )


def _load_config_from_file(path: str) -> dict[str, Any]:
    """Read .aria/config.json and extract phase_c_integrator.pre_merge_gate block."""
    try:
        with open(path, encoding="utf-8") as fh:
            full = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    pci = full.get("phase_c_integrator") or {}
    if not isinstance(pci, dict):
        return {}
    block = pci.get("pre_merge_gate") or {}
    return block if isinstance(block, dict) else {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pre-merge precondition gate (C.2.4)")
    parser.add_argument("--pr-branch", required=True, help="PR feature branch name")
    parser.add_argument("--main-branch", default="main", help="Main branch to check (default: main)")
    parser.add_argument(
        "--config-file",
        default=".aria/config.json",
        help="Path to .aria/config.json (default: .aria/config.json)",
    )
    args = parser.parse_args(argv)
    config = _load_config_from_file(args.config_file)
    output = gate_check(
        pr_branch=args.pr_branch, main_branch=args.main_branch, config=config
    )
    sys.stdout.write(json.dumps(output, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())

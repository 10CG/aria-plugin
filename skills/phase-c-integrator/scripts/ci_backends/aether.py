"""Aether CI backend (10CG default, full implementation).

Per [DEC 2026-05-28] §Q1 (b) — contract + Aether full + GHA stub.

Migrated from pre_merge_gate.py per proposal.md §A.2 responsibility table:
- detect_aether() body              → AetherBackend.probe() (classmethod)
- verify_aether_in_flight_flag()    → AetherBackend._verify_in_flight_flag() (private), called by precheck()
- _run_aether_with_retry()          → AetherBackend._run_with_retry() (private)
- _query_aether()                   → split into AetherBackend.query_pr_ci() + .query_branch_in_flight()
- _normalize_pr_ci_status()         → AetherBackend._normalize_pr_ci_status() (private)
- _translate_in_flight_run()        → AetherBackend._translate_in_flight_run() (private)
- AETHER_CLI_MIN_SHA / _DATE        → module-level constants here
- RETRY_BACKOFF / MAX_RETRY_ATTEMPTS → module-level constants here

Behavior is byte-for-byte preserved (Hard Constraint #1) — only call site
changes (gate_check uses backend.query_*() instead of _query_aether direct).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import shutil
import subprocess
import time
from typing import Any, ClassVar

from .base import CIBackend, CIStatus, InFlightStatus


# aether-cli baseline (from spec D1 §Contract Source, preserved from
# pre_merge_gate.py L33-34).
AETHER_CLI_MIN_SHA = "f29abee"
AETHER_CLI_MIN_DATE = "2026-05-06"

# Subprocess retry backoff (seconds) when primitive_call_timeout fires.
# Preserved from pre_merge_gate.py L37-38.
RETRY_BACKOFF = (5, 15, 45)
MAX_RETRY_ATTEMPTS = len(RETRY_BACKOFF)


class AetherBackend(CIBackend):
    name: ClassVar[str] = "aether-ci-cli"

    # Default subprocess timeout (overridable per-call via cfg["primitive_call_timeout_seconds"]
    # in gate_check; pre_merge_gate.py reads cfg then passes through; here we
    # accept timeout param on query methods to preserve flexibility).
    DEFAULT_TIMEOUT = 30

    def __init__(self, binary: str | None = None, timeout: int = DEFAULT_TIMEOUT):
        self.binary = binary or shutil.which("aether")
        if not self.binary:
            # Should not happen if probe() was called first, but defensive
            # check protects against direct instantiation.
            raise RuntimeError(
                "AetherBackend instantiated but `aether` binary not on PATH. "
                "Call AetherBackend.probe() first to verify availability."
            )
        self.timeout = timeout

    @classmethod
    def probe(cls) -> bool:
        """Detect aether CLI availability (preserves detect_aether() L57-68).

        Returns True if `aether` binary on PATH. The ~/.aether/config.yaml
        check is preserved as informational (returns False if config exists
        but binary missing — original behavior).
        """
        binary = shutil.which("aether")
        if binary:
            return True
        config_yaml = os.path.expanduser("~/.aether/config.yaml")
        if os.path.exists(config_yaml):
            # Config exists but binary missing — treat as not available so
            # caller routes through no_ci_fallback rather than failing mid-call.
            # The presence of config is informational only (preserved).
            return False
        return False

    def precheck(self) -> tuple[bool, str]:
        """Verify the aether binary supports --in-flight flag.

        Older binaries (pre PR #116, before 2026-05-06) lack this flag and
        must be upgraded before the gate can function. Preserves gate_check
        L296-307 verify_aether_in_flight_flag failure semantic.
        """
        if not self._verify_in_flight_flag():
            return False, (
                f"aether binary at {self.binary} lacks --in-flight flag; "
                f"upgrade to aether-cli >= commit {AETHER_CLI_MIN_SHA} "
                f"({AETHER_CLI_MIN_DATE})"
            )
        return True, ""

    def query_pr_ci(self, pr_ref: str) -> CIStatus:
        """Query PR CI status. Preserves _query_aether(in_flight_only=False) +
        _normalize_pr_ci_status logic from pre_merge_gate.py L320-330 + L160-185.
        """
        ok, data, err = self._query(branch=pr_ref, in_flight_only=False)
        if not ok:
            # Raise via standard mechanism — gate_check will catch via the
            # error_message path. Use a non-NIE exception so Hard Constraint
            # #7 distinction is preserved (NIE = stub backend; this = aether
            # transport/parse failure).
            raise AetherQueryError(f"PR CI status query failed: {err}")
        pr_runs_raw = data.get("runs") or []
        if not isinstance(pr_runs_raw, list):
            raise AetherQueryError("aether returned non-list runs field")
        state = self._normalize_pr_ci_status(
            [r for r in pr_runs_raw if isinstance(r, dict)]
        )
        return CIStatus(
            state=state,
            checked_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
        )

    def query_branch_in_flight(self, branch: str) -> InFlightStatus:
        """Query main branch in-flight runs. Preserves _query_aether(
        in_flight_only=True) + _translate_in_flight_run logic from L309-318 + L188-214.
        """
        ok, data, err = self._query(branch=branch, in_flight_only=True)
        if not ok:
            raise AetherQueryError(f"main in-flight query failed: {err}")
        main_runs_raw = data.get("runs") or []
        if not isinstance(main_runs_raw, list):
            raise AetherQueryError("aether returned non-list runs field")
        translated = [
            self._translate_in_flight_run(r)
            for r in main_runs_raw
            if isinstance(r, dict)
        ]
        return InFlightStatus(
            runs=translated,
            checked_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
        )

    # ──────────────────────────── private helpers ────────────────────────────

    def _verify_in_flight_flag(self, attempts: int = 2) -> bool:
        """Return True if `aether ci status --help` advertises `--in-flight`.

        R2 hardening (CR-M1, preserved from pre_merge_gate.py L71-100):
        bumped default timeout 5s → 10s + 2 attempts to avoid false negatives
        on cold caches / slow filesystems. A single slow `aether --help`
        should not flip a binary's flag-presence verdict.
        """
        last_haystack = ""
        for _ in range(attempts):
            try:
                result = subprocess.run(
                    [self.binary, "ci", "status", "--help"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                continue
            last_haystack = (result.stdout or "") + (result.stderr or "")
            if "in-flight" in last_haystack:
                return True
        # Loop exhausted (preserved from L96-100).
        return "in-flight" in last_haystack

    def _run_with_retry(self, args: list[str]) -> tuple[int, str, str]:
        """Run aether subprocess with timeout + retry. Return (exit_code, stdout, stderr).

        Preserves _run_aether_with_retry from pre_merge_gate.py L103-130.
        Retries on TimeoutExpired only; other exceptions bubble up.
        """
        last_exc: subprocess.TimeoutExpired | None = None
        for attempt in range(MAX_RETRY_ATTEMPTS):
            try:
                result = subprocess.run(
                    [self.binary] + args,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                )
                return result.returncode, result.stdout or "", result.stderr or ""
            except subprocess.TimeoutExpired as exc:
                last_exc = exc
                if attempt < MAX_RETRY_ATTEMPTS - 1:
                    time.sleep(RETRY_BACKOFF[attempt])
        stderr = f"primitive call timeout after {MAX_RETRY_ATTEMPTS} attempts"
        if last_exc is not None:
            stderr += f" (last: {last_exc})"
        return -1, "", stderr

    def _query(
        self, branch: str, in_flight_only: bool
    ) -> tuple[bool, dict[str, Any] | None, str]:
        """Call `aether ci status` and parse JSON. Return (ok, parsed_data, error_msg).

        Preserves _query_aether from pre_merge_gate.py L133-157.
        """
        args = ["ci", "status", "--branch", branch, "--json"]
        if in_flight_only:
            args.append("--in-flight")
        code, stdout, stderr = self._run_with_retry(args)
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

    @staticmethod
    def _normalize_pr_ci_status(runs: list[dict[str, Any]]) -> str:
        """Map aether CIRun list → passing | failing | pending.

        Preserves _normalize_pr_ci_status from pre_merge_gate.py L160-185.
        Selects the most recent run by `started_at` (descending) rather than
        relying on aether's list ordering. Conservative mapping: unknown
        statuses route to pending so the caller waits rather than races.
        """
        if not runs:
            return "pending"

        def _started_key(run: dict[str, Any]) -> str:
            return run.get("started_at") or ""

        sorted_runs = sorted(runs, key=_started_key, reverse=True)
        latest = sorted_runs[0]
        status = (latest.get("status") or "").lower()
        if status in ("success", "passing", "passed", "completed"):
            return "passing"
        if status in ("failure", "failing", "failed", "error", "cancelled", "canceled"):
            return "failing"
        return "pending"

    @staticmethod
    def _translate_in_flight_run(aether_run: dict[str, Any]) -> dict[str, Any]:
        """aether CIRun dict → internal in_flight_runs[] schema.

        Preserves _translate_in_flight_run from pre_merge_gate.py L188-214.
        """
        started_at = aether_run.get("started_at") or ""
        elapsed = 0
        if started_at:
            try:
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


class AetherQueryError(Exception):
    """Raised by AetherBackend query_*() methods when subprocess fails or
    aether returns malformed/error response.

    Distinct from NotImplementedError (Hard Constraint #7 — stub backend
    indicator that MUST propagate). AetherQueryError indicates a transient
    or recoverable issue; gate_check catches it and translates to
    verdict=FAIL with error message.
    """

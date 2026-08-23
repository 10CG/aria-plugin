#!/usr/bin/env python3
"""gate_state lifecycle helper for workflow-runner v2.3.0+ wait_recoverable.

Reference implementation of the gate_state block (Forgejo Issue #60 D2).
Handles read/write/migrate/clear of `.aria/workflow-state.json`'s gate_state
field with v1.0 → v1.1 schema migration and defensive access.

stdlib only (no third-party deps). The CLI (`python3 gate_state_helper.py
{record,reset,clear} ...`) is the runtime entry point — workflow-runner
§wait_recoverable invokes it via subprocess so gate-state persistence never
depends on an LLM caller re-deriving the write. The Python API (load_state,
write_gate_state, clear_gate_state, is_gate_active, should_check_now, plus
reset_no_run_observations / reset_retry_count) is the module's importable
surface, used by the CLI itself and by tests/re-implementers.

Usage (CLI):
    python3 gate_state_helper.py record --state-file .aria/workflow-state.json \\
        --name pre_merge --verdict wait --gate-error-kind no-run-for-branch \\
        --source production
    python3 gate_state_helper.py reset --state-file .aria/workflow-state.json \\
        --observations
    python3 gate_state_helper.py clear --state-file .aria/workflow-state.json

Usage (Python):
    from gate_state_helper import (
        load_state, write_gate_state, clear_gate_state,
        is_gate_active, should_check_now,
    )
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import sys
import time
import uuid
from typing import Any

CURRENT_SCHEMA_VERSION = "1.1"

GATE_STATUS_WAITING = "waiting"
GATE_STATUS_GREEN = "green"
GATE_STATUS_FAIL = "fail"

# Default poll intervals when caller doesn't supply config (matches
# phase_c_integrator.pre_merge_gate.wait_check_intervals default).
DEFAULT_INTERVALS_SECONDS = (30, 60, 120, 300, 300)


def _utcnow_iso() -> str:
    """ISO 8601 wall clock with explicit UTC marker."""
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _compute_integrity(state: dict[str, Any]) -> str:
    """SHA-256 of JSON content with integrity block excluded."""
    snapshot = {k: v for k, v in state.items() if k != "integrity"}
    payload = json.dumps(snapshot, sort_keys=True, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _migrate_state(state: dict[str, Any]) -> dict[str, Any]:
    """Apply additive migrations to bring state to CURRENT_SCHEMA_VERSION.

    v1.0 → v1.1: add gate_state default null.
    Unknown / future versions are returned unchanged (caller logs warn).
    """
    fmt = str(state.get("format_version", "1.0"))
    if fmt == "1.0":
        state.setdefault("gate_state", None)
        state["format_version"] = CURRENT_SCHEMA_VERSION
    return state


def load_state(path: str = ".aria/workflow-state.json") -> dict[str, Any] | None:
    """Read state file, apply migration, return parsed dict or None if absent.

    Corrupt or unparseable files return None per schema §8.1 (caller is
    responsible for renaming the corrupt file out of the way).
    """
    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
    except FileNotFoundError:
        return None
    try:
        state = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(state, dict):
        return None
    return _migrate_state(state)


def atomic_write_state(state: dict[str, Any], path: str = ".aria/workflow-state.json") -> None:
    """Atomic write per schema §4: write to .tmp + rename.

    Recomputes integrity hash before write. The state dict may be mutated.
    """
    state["integrity"] = {
        "state_hash": _compute_integrity(state),
        "validated_at": _utcnow_iso(),
    }
    tmp_path = path + ".tmp"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, path)


def _next_check_at(retry_count: int, intervals: tuple[int, ...] = DEFAULT_INTERVALS_SECONDS) -> str:
    """Compute next_check_at = now + intervals[min(retry_count, len-1)].

    Per Spec D1 CR-3 patch: array exhausted → repeat intervals[-1] until
    wait_timeout_seconds (timeout enforcement is caller's responsibility).
    """
    idx = min(retry_count, len(intervals) - 1)
    delta = _dt.timedelta(seconds=intervals[idx])
    return (_dt.datetime.now(_dt.timezone.utc) + delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_gate_state(
    state: dict[str, Any],
    *,
    name: str,
    verdict: str,
    in_flight_runs: list[dict[str, Any]] | None = None,
    primitive_used: str = "aether-ci-cli",
    raw_message: str = "",
    intervals: tuple[int, ...] = DEFAULT_INTERVALS_SECONDS,
    gate_error_kind: str | None = None,
) -> dict[str, Any]:
    """Update state.gate_state per latest gate check verdict. Returns mutated state.

    First wait verdict creates gate_state with retry_count=0; subsequent waits
    increment retry_count and recompute next_check_at. green/fail verdicts
    update status without bumping retry_count (terminal states).

    `gate_error_kind` is the single counting point for
    `gate_state.no_run_observations` (SC-11): when
    `gate_error_kind == "no-run-for-branch"` AND `verdict == GATE_STATUS_WAITING`,
    the counter increments from whatever was already on `existing` (defaulting
    absent/legacy state to 0 via `.get(..., 0)`); any other combination resets
    it to 0. This is a fresh per-call read of `existing`, not a running total
    gated on `is_first` — a `None`-kind call zeroes it, and a following
    matching-kind call restarts at 1.
    """
    existing = state.get("gate_state") or {}
    is_first = not existing or existing.get("name") != name
    if is_first:
        retry_count = 0
        started_at = _utcnow_iso()
    else:
        # Bump retry only for waiting → waiting transitions; terminal verdicts
        # capture the count at terminal time without further increment.
        if verdict == GATE_STATUS_WAITING and existing.get("status") == GATE_STATUS_WAITING:
            retry_count = int(existing.get("retry_count", 0)) + 1
        else:
            retry_count = int(existing.get("retry_count", 0))
        started_at = existing.get("started_at") or _utcnow_iso()

    if gate_error_kind == "no-run-for-branch" and verdict == GATE_STATUS_WAITING:
        no_run_observations = int(existing.get("no_run_observations", 0)) + 1
    else:
        no_run_observations = 0

    state["gate_state"] = {
        "name": name,
        "status": verdict,
        "started_at": started_at,
        "retry_count": retry_count,
        "next_check_at": _next_check_at(retry_count, intervals) if verdict == GATE_STATUS_WAITING else _utcnow_iso(),
        "in_flight_runs": in_flight_runs or [],
        "primitive_used": primitive_used,
        "raw_message": raw_message,
        "no_run_observations": no_run_observations,
    }
    return state


def clear_gate_state(state: dict[str, Any]) -> dict[str, Any]:
    """Set gate_state to null (terminal: workflow done or gate consumed)."""
    state["gate_state"] = None
    return state


def reset_no_run_observations(state: dict[str, Any]) -> dict[str, Any]:
    """Zero out gate_state.no_run_observations only. No-op if gate_state is None."""
    gate_state = state.get("gate_state")
    if not gate_state:
        return state
    gate_state["no_run_observations"] = 0
    return state


def reset_retry_count(state: dict[str, Any]) -> dict[str, Any]:
    """Zero out gate_state.retry_count and bump started_at to now.

    No-op if gate_state is None.
    """
    gate_state = state.get("gate_state")
    if not gate_state:
        return state
    gate_state["retry_count"] = 0
    gate_state["started_at"] = _utcnow_iso()
    return state


def is_gate_active(state: dict[str, Any]) -> bool:
    """True iff gate_state.status == waiting (workflow should resume polling)."""
    gs = state.get("gate_state") or {}
    return gs.get("status") == GATE_STATUS_WAITING


def should_check_now(state: dict[str, Any]) -> bool:
    """On resume: True iff next_check_at is in the past (immediate re-check).

    Returns True for absent / malformed next_check_at to fail-safe toward
    re-checking rather than waiting indefinitely.
    """
    gs = state.get("gate_state") or {}
    next_at = gs.get("next_check_at")
    if not next_at or not isinstance(next_at, str):
        return True
    try:
        # Spec persists with trailing Z; fromisoformat needs +00:00.
        iso = next_at.replace("Z", "+00:00")
        next_dt = _dt.datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return True
    now_dt = _dt.datetime.now(_dt.timezone.utc)
    return now_dt >= next_dt


# --- Interrupt flag-file lifecycle (R2-CR-B) ---

INTERRUPT_FLAG_PATH = ".aria/.workflow-interrupt"


def clear_interrupt_flag(path: str = INTERRUPT_FLAG_PATH) -> None:
    """Resume entry / fresh start: unconditionally clear stale flag.

    Idempotent — missing flag is not an error.
    """
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def set_interrupt_flag(path: str = INTERRUPT_FLAG_PATH) -> None:
    """SIGINT handler entry: atomic O_CREAT|O_EXCL write.

    Best-effort atomic via tmp+rename. If file already exists (prior interrupt
    not yet consumed), overwrite — caller treats latest signal as authoritative.
    """
    tmp = f"{path}.tmp.{uuid.uuid4().hex[:8]}"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(_utcnow_iso() + "\n")
    os.replace(tmp, path)


def interrupt_flag_present(path: str = INTERRUPT_FLAG_PATH) -> bool:
    """Polling chunk check: True iff interrupt flag exists."""
    return os.path.exists(path)


def poll_with_interrupt_check(
    sleep_seconds: int,
    *,
    chunk_seconds: int = 5,
    flag_path: str = INTERRUPT_FLAG_PATH,
    sleep_func=time.sleep,  # injectable for tests
) -> bool:
    """Sleep for sleep_seconds in chunks, returning True if interrupted.

    Caller handles routing to suspended state on True return; False means
    the sleep completed normally and the next gate check should fire.

    `sleep_func` is injectable so tests can avoid real time.sleep.
    """
    if sleep_seconds <= 0:
        return interrupt_flag_present(flag_path)
    elapsed = 0
    while elapsed < sleep_seconds:
        chunk = min(chunk_seconds, sleep_seconds - elapsed)
        sleep_func(chunk)
        elapsed += chunk
        if interrupt_flag_present(flag_path):
            return True
    return False


# --- CLI (runtime entry point; workflow-runner §wait_recoverable invokes via subprocess) ---

_VERDICT_MAP = {
    "wait": GATE_STATUS_WAITING,
    "green": GATE_STATUS_GREEN,
    "fail": GATE_STATUS_FAIL,
}


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gate_state_helper.py",
        description="gate_state lifecycle CLI (record / reset / clear).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_record = sub.add_parser("record", help="Record a gate-check verdict.")
    p_record.add_argument("--state-file", required=True)
    p_record.add_argument("--name", default="pre_merge")
    p_record.add_argument("--verdict", required=True, choices=sorted(_VERDICT_MAP))
    p_record.add_argument("--gate-error-kind", default=None)
    p_record.add_argument("--threshold", type=int, default=3)
    p_record.add_argument("--intervals", default=None, help="JSON list of ints, seconds.")
    p_record.add_argument("--in-flight-runs", default=None, help="JSON list of run objects.")
    p_record.add_argument("--raw-message", default="")
    p_record.add_argument("--source", required=True, choices=["production", "test"])

    p_reset = sub.add_parser("reset", help="Reset one or more gate_state fields.")
    p_reset.add_argument("--state-file", required=True)
    p_reset.add_argument("--observations", action="store_true")
    p_reset.add_argument("--retry-count", action="store_true")

    p_clear = sub.add_parser("clear", help="Clear gate_state to null.")
    p_clear.add_argument("--state-file", required=True)

    return parser


def _telemetry_path_for(state_file: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(state_file)), "gate-state-telemetry.jsonl")


def _append_telemetry(state_file: str, row: dict[str, Any]) -> None:
    path = _telemetry_path_for(state_file)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _cli_record(args: argparse.Namespace) -> int:
    verdict = _VERDICT_MAP[args.verdict]

    try:
        intervals = (
            tuple(json.loads(args.intervals)) if args.intervals is not None else DEFAULT_INTERVALS_SECONDS
        )
    except (json.JSONDecodeError, TypeError, ValueError):
        print(f"gate_state_helper: --intervals is not valid JSON: {args.intervals!r}", file=sys.stderr)
        return 2

    try:
        in_flight_runs = json.loads(args.in_flight_runs) if args.in_flight_runs is not None else []
    except (json.JSONDecodeError, TypeError, ValueError):
        print(
            f"gate_state_helper: --in-flight-runs is not valid JSON: {args.in_flight_runs!r}",
            file=sys.stderr,
        )
        return 2

    path = args.state_file
    if os.path.exists(path):
        state = load_state(path)
        if state is None:
            print(f"gate_state_helper: state file {path!r} is corrupt/unreadable", file=sys.stderr)
            return 2
    elif verdict == GATE_STATUS_WAITING:
        state = {"format_version": CURRENT_SCHEMA_VERSION, "gate_state": None}
    else:
        print(
            f"gate_state_helper: state file {path!r} does not exist and --verdict "
            f"{args.verdict!r} is not 'wait' (only a first wait creates the skeleton)",
            file=sys.stderr,
        )
        return 2

    write_gate_state(
        state,
        name=args.name,
        verdict=verdict,
        in_flight_runs=in_flight_runs,
        raw_message=args.raw_message,
        intervals=intervals,
        gate_error_kind=args.gate_error_kind,
    )
    atomic_write_state(state, path)

    gate = state["gate_state"]
    no_run_observations = int(gate.get("no_run_observations", 0))
    should_prompt = no_run_observations >= args.threshold
    retry_count = int(gate.get("retry_count", 0))

    started_at_raw = gate.get("started_at")
    try:
        started_dt = _dt.datetime.fromisoformat(str(started_at_raw).replace("Z", "+00:00"))
        elapsed_seconds = int((_dt.datetime.now(_dt.timezone.utc) - started_dt).total_seconds())
    except (ValueError, TypeError):
        elapsed_seconds = 0

    _append_telemetry(
        path,
        {
            "ts": _utcnow_iso(),
            "source": args.source,
            "sub": "record",
            "verdict": args.verdict,
            "kind": args.gate_error_kind,
            "no_run_observations": no_run_observations,
            "should_prompt": should_prompt,
        },
    )

    print(
        json.dumps(
            {
                "retry_count": retry_count,
                "no_run_observations": no_run_observations,
                "should_prompt": should_prompt,
                "elapsed_seconds": elapsed_seconds,
                "next_check_at": gate.get("next_check_at"),
            }
        )
    )
    return 0


def _cli_reset(args: argparse.Namespace) -> int:
    if not args.observations and not args.retry_count:
        print("gate_state_helper: reset requires --observations and/or --retry-count", file=sys.stderr)
        return 2

    path = args.state_file
    if not os.path.exists(path):
        print(f"gate_state_helper: state file {path!r} does not exist", file=sys.stderr)
        return 2
    state = load_state(path)
    if state is None or not state.get("gate_state"):
        print(f"gate_state_helper: state file {path!r} has no active gate_state to reset", file=sys.stderr)
        return 2

    if args.observations:
        reset_no_run_observations(state)
    if args.retry_count:
        reset_retry_count(state)
    atomic_write_state(state, path)

    print(json.dumps({"ok": True}))
    return 0


def _cli_clear(args: argparse.Namespace) -> int:
    path = args.state_file
    if not os.path.exists(path):
        print(f"gate_state_helper: state file {path!r} does not exist", file=sys.stderr)
        return 2
    state = load_state(path)
    if state is None:
        print(f"gate_state_helper: state file {path!r} is corrupt/unreadable", file=sys.stderr)
        return 2

    clear_gate_state(state)
    atomic_write_state(state, path)

    print(json.dumps({"ok": True}))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    if args.command == "record":
        return _cli_record(args)
    if args.command == "reset":
        return _cli_reset(args)
    if args.command == "clear":
        return _cli_clear(args)
    parser.error(f"unknown command: {args.command!r}")  # pragma: no cover - argparse `choices` blocks this
    return 2


if __name__ == "__main__":
    sys.exit(main())

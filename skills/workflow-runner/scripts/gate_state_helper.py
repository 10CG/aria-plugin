#!/usr/bin/env python3
"""gate_state lifecycle helper for workflow-runner v2.3.0+ wait_recoverable.

Reference implementation of the gate_state block (Forgejo Issue #60 D2).
Handles read/write/migrate/clear of `.aria/workflow-state.json`'s gate_state
field with v1.0 → v1.1 schema migration and defensive access.

stdlib only (no third-party deps). The actual workflow-runner skill is
markdown-driven (LLM caller handles state); this helper exists so the
behavior is testable and serves as a canonical reference for any
re-implementer.

Usage (Python):
    from gate_state_helper import (
        load_state, write_gate_state, clear_gate_state,
        is_gate_active, should_check_now,
    )
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
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
) -> dict[str, Any]:
    """Update state.gate_state per latest gate check verdict. Returns mutated state.

    First wait verdict creates gate_state with retry_count=0; subsequent waits
    increment retry_count and recompute next_check_at. green/fail verdicts
    update status without bumping retry_count (terminal states).
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

    state["gate_state"] = {
        "name": name,
        "status": verdict,
        "started_at": started_at,
        "retry_count": retry_count,
        "next_check_at": _next_check_at(retry_count, intervals) if verdict == GATE_STATUS_WAITING else _utcnow_iso(),
        "in_flight_runs": in_flight_runs or [],
        "primitive_used": primitive_used,
        "raw_message": raw_message,
    }
    return state


def clear_gate_state(state: dict[str, Any]) -> dict[str, Any]:
    """Set gate_state to null (terminal: workflow done or gate consumed)."""
    state["gate_state"] = None
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

#!/usr/bin/env python3
"""TASK-012 — runtime-invocation probe for the Layer L coordination gate.

Reads ONLY the production telemetry partition
(``.aria/coordination-telemetry.jsonl``) and asserts that ``run_gate()`` has been
invoked through the production CLI entry **recently**.  This is the anti-dead-code
liveness check demanded by aria-plugin #95: a gate that is *wired* but no longer
*called* is the "勾选完成 ≠ 运行现实" failure DEC-20260704-002 exists to catch.

Recency matters (audit Critical fix): the partition is append-only and never
trimmed, so counting *all-time* production records would let ONE historical
record keep the probe green forever — it could not detect run_gate re-degrading
into dead code.  The probe therefore only counts production records whose ``ts``
is within ``max_age_days`` (default 14, matched to a dogfood/ship cadence), the
same "现在时" semantics as the sibling issue-cache-freshness check.

Partition guarantee (accurate scope — NOT over-claimed):
  The production partition file is written only when ``_source=="production"``,
  and after the audit tightening that value is reachable ONLY from the private
  ``phase1_gate._gated`` (invoked with ``_source="production"`` by exactly one
  call site, the CLI ``_main``).  The PUBLIC API — ``run_gate`` (no source param)
  and ``run_gate_synthetic`` (forces "harness") — CANNOT write the production
  partition, so ordinary library/pytest/harness callers cannot inflate this
  count.  What this does NOT defend against: someone calling the private
  ``_gated(_source="production")`` directly, or hand-editing the JSONL file.
  Those are out of the threat model (accidental dead-code, not adversarial
  forgery) and are called out here so maintainers don't over-trust the guarantee.

Exit codes (custom-check contract, same as issue-cache-freshness):
  0 — OK  (gate disabled, or ≥1 RECENT production invocation recorded)
  1 — FAIL/WARN (gate enabled but no recent production record → dead-code risk)
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_PROD_FILE = ".aria/coordination-telemetry.jsonl"
_DEFAULT_MAX_AGE_DAYS = 14


def _gate_enabled(repo: Path) -> bool:
    """True iff state_scanner.coordination.enabled == true in .aria/config.json."""
    cfg = repo / ".aria" / "config.json"
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
    except Exception:
        return False
    coord = data.get("state_scanner", {}).get("coordination", {})
    return bool(coord.get("enabled", False))


def _parse_ts(value) -> "datetime | None":
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def count_production_invocations(
    repo: Path,
    *,
    max_age_days: int = _DEFAULT_MAX_AGE_DAYS,
    now: "datetime | None" = None,
) -> int:
    """Count RECENT well-formed production records in the production partition.

    Only the production partition is read.  A record counts iff (a) it is
    valid JSON, (b) ``source == "production"``, and (c) its ``ts`` is within
    ``max_age_days`` of ``now``.  Returns -1 when the partition file is absent.
    Malformed / stale / non-production lines are skipped, not fatal."""
    prod = repo / _PROD_FILE
    if not prod.exists():
        return -1  # sentinel: partition absent
    ref = now if now is not None else datetime.now(timezone.utc)
    if ref.tzinfo is None:  # normalize a tz-naive injected `now` (symmetry with _parse_ts)
        ref = ref.replace(tzinfo=timezone.utc)
    cutoff = ref - timedelta(days=max_age_days)
    n = 0
    try:
        text = prod.read_text(encoding="utf-8")
    except Exception:
        return -1
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if not (isinstance(rec, dict) and rec.get("source") == "production"):
            continue
        ts = _parse_ts(rec.get("ts"))
        if ts is None or ts < cutoff:
            continue  # stale or unparseable timestamp → not a RECENT invocation
        n += 1
    return n


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    repo = Path(argv[0]) if argv else Path.cwd()

    if not _gate_enabled(repo):
        print("OK (coordination gate disabled)")
        return 0

    prod = repo / _PROD_FILE
    n = count_production_invocations(repo)
    if not prod.exists():
        print(
            "NO PRODUCTION RECORDS — run_gate never invoked via the CLI "
            "(dead-code risk); dogfood (TASK-019) should produce ≥1"
        )
        return 1
    if n == 0:
        print(
            f"STALE — no production run_gate record within {_DEFAULT_MAX_AGE_DAYS}d "
            "(wired but not recently called → dead-code risk); or partition holds "
            "only non-production / malformed records"
        )
        return 1
    print(f"OK ({n} recent production run_gate invocation(s) recorded)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

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

--------------------------------------------------------------------------
#95 follow-up A (runtime-probe-archive-gate-integration, TASK-003): thin shell
--------------------------------------------------------------------------
This module used to own its own read+parse+count logic. It now DELEGATES that
to the generalized ``lib/runtime_probe.py`` (TASK-001/002) via a hardcoded
coordination descriptor — this is the first (and, pre-#95, only) caller of
that generalized probe. The CLI contract (argv / exit codes / messages) for
the FOUR pre-existing reachable states is preserved BYTE-FOR-BYTE (SC-9):

    disabled          → "OK (coordination gate disabled)"           exit 0
    partition missing → "NO PRODUCTION RECORDS — ..."                exit 1
    normal (n>=1)     → "OK (N recent production ... recorded)"      exit 0
    all-stale (n==0)  → "STALE — no production run_gate record ..."  exit 1

The ONE intentional behavior change (explicit, regression-locked, not a
silent drift): a partition that EXISTS but fails to read (e.g. permission
denied) used to fall through ``count_production_invocations``'s ``-1``
sentinel into the "normal" branch's format string, producing an
``"OK (-1 recent production run_gate invocation(s) recorded)"`` exit-0
FALSE GREEN (#95 audit-Critical finding). It now maps to a STALE-class warn
message + exit 1 — see the ``outcome == "warn"`` branch in ``main()``.

Exit codes (custom-check contract):
  0 — OK  (gate disabled, or ≥1 RECENT production invocation recorded)
  1 — FAIL/WARN (gate enabled but no recent production record → dead-code
      risk; OR the partition exists but could not be read — no longer a
      silent false green)

  This probe uses only the 0/1 subset. The sibling issue-cache-freshness check
  (Spec C: state-scanner-issue-cache-freshness-assertion) additionally uses
  exit 2 → "skip" (insufficient data / migration state). custom_checks.py maps
  rc==2 to a distinct "skip" status; this probe never emits it.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Import lib.runtime_probe (scripts/lib/runtime_probe.py).
#
# Unlike spec_complete.py / collectors/openspec.py, this module never has a
# "proper package" import context to try first: there is no scripts/__init__.py,
# and every real call site (state-checks.yaml CLI invocation, and
# tests/test_phase1_gate_telemetry.py's ``import coordination_probe as probe``)
# reaches this file as a BARE top-level module — never as e.g. ``scripts.
# coordination_probe``. So there is no dual-context try/except dance here
# (nothing to "try" first); we go straight to the sys.path fallback style.
#
# Deliberately NOT ``import lib.runtime_probe``: in some test sys.path layouts
# the top-level name ``lib`` resolves to state-scanner/lib (Layer L — a
# DIFFERENT package, claim_schema.py etc.), not scripts/lib — the exact
# collision documented in collectors/openspec.py:29. Inserting scripts/lib
# itself onto sys.path and importing the bare module name sidesteps the
# collision entirely.
# ---------------------------------------------------------------------------
_LIB_DIR = str(Path(__file__).resolve().parent / "lib")
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)
from runtime_probe import _scan_partition, probe  # type: ignore[import]  # noqa: E402

_PROD_FILE = ".aria/coordination-telemetry.jsonl"
_DEFAULT_MAX_AGE_DAYS = 14
_SYMBOL = "run_gate"
_ENABLED_WHEN = "state_scanner.coordination.enabled"

# Hardcoded coordination descriptor (TASK-003) — the values this module used
# to have as module-level constants, now expressed as a runtime_probe
# descriptor. Author-controlled and always well-formed, so it is passed
# straight to probe() without a validate_descriptor() round-trip.
_DESCRIPTOR = {
    "partition": _PROD_FILE,
    "symbol": _SYMBOL,
    "max_age_days": _DEFAULT_MAX_AGE_DAYS,
    "enabled_when": _ENABLED_WHEN,
}


def count_production_invocations(
    repo: Path,
    *,
    max_age_days: int = _DEFAULT_MAX_AGE_DAYS,
    now: "datetime | None" = None,
) -> int:
    """BACKWARD-COMPAT shim.

    Preserved as a public function purely because tests/test_phase1_gate_telemetry.py
    — belonging to a DIFFERENT, already-shipped spec (interactive-session-dedup-
    coordination) — imports and calls it directly, asserting the EXACT legacy
    int-sentinel contract: ``-1`` when the partition is absent (or unreadable —
    the old code collapsed both into the same sentinel), ``0`` when readable but
    zero RECENT production records exist (stale/non-production/empty), ``N>=1``
    for N recent production records.

    Delegates the actual scan to ``lib.runtime_probe._scan_partition`` (the
    single SOT for this parse loop — not duplicated here) and re-expresses the
    structured result as the legacy sentinel shape. Note this function does
    NOT consult ``enabled_when`` / the coordination config switch at all —
    exactly like the original implementation, it is a pure partition-counting
    primitive; the gate/switch semantics live only in ``main()``.
    """
    ref = now if now is not None else datetime.now(timezone.utc)
    scan = _scan_partition(Path(repo) / _PROD_FILE, max_age_days=max_age_days, now=ref)
    if scan["status"] in ("missing", "unreadable"):
        return -1
    return scan["recent_count"]


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    repo = Path(argv[0]) if argv else Path.cwd()
    now = datetime.now(timezone.utc)

    result = probe(_DESCRIPTOR, repo, now)
    outcome = result["outcome"]

    if outcome == "skipped":
        # Covers both skipped sub-reasons (switch off / config missing-or-
        # unreadable) uniformly — the legacy _gate_enabled() also collapsed
        # both into plain False, so this preserves that merge (SC-9 state:
        # disabled).
        print("OK (coordination gate disabled)")
        return 0

    if outcome == "pass":
        print(f"OK ({result['count']} recent production run_gate invocation(s) recorded)")
        return 0

    if outcome == "invalid":
        # Only theoretically reachable: the hardcoded descriptor above is
        # always well-formed, so this can only fire if .aria/config.json
        # itself is malformed in a specific way (state_scanner key resolving
        # to a non-object). The legacy _gate_enabled() would have raised an
        # UNCAUGHT AttributeError in this exact scenario (chained .get() on a
        # non-dict) — not one of the four SC-9-locked states, so no byte-
        # compat obligation here; this is a pure robustness improvement
        # (graceful warn+exit1 instead of a crash).
        print(f"STALE — runtime probe declaration/config invalid: {result['reason']}")
        return 1

    if outcome != "warn":
        # Defensive floor (SFH M-2): probe()'s contract defines exactly four
        # outcomes (pass/warn/skipped/invalid) and the other three are all
        # handled above — this is only reachable if that contract is ever
        # violated (e.g. a future new outcome value added upstream). Fail
        # honestly with the raw outcome instead of silently falling into the
        # "warn"-branch wording below, which would misdiagnose whatever this
        # outcome actually means.
        print(f"STALE — runtime probe returned unrecognized outcome {outcome!r}: {result.get('reason', '')}")
        return 1

    # outcome == "warn": partition missing / unreadable (new, false-green fix)
    # / all stale / only non-production records. Message selection mirrors
    # the legacy four-state dispatch (SC-9); the one new sub-case (unreadable)
    # gets a new STALE-class message, not the old silent "OK (-1 ...)".
    partition_path = repo / _PROD_FILE
    if not partition_path.exists():
        print(
            "NO PRODUCTION RECORDS — run_gate never invoked via the CLI "
            "(dead-code risk); dogfood (TASK-019) should produce ≥1"
        )
        return 1
    # COUPLING LOCK: this substring check is tied to the exact wording
    # lib.runtime_probe.probe()'s `scan["status"] == "unreadable"` branch
    # emits ("production telemetry partition unreadable (IO error): ...").
    # If that upstream reason text ever changes, this branch silently stops
    # matching and falls through to the generic all-stale message below —
    # keep the two in sync.
    if "unreadable" in result["reason"]:
        # result["reason"] already reads "production telemetry partition
        # unreadable (IO error): <path>: <error>" — print it directly rather
        # than re-wrapping in another "unreadable (...)" layer.
        print(
            f"STALE — {result['reason']}; treating an unreadable partition as "
            "a dead-code risk (false-green fix, #95 follow-up A)"
        )
        return 1
    print(
        f"STALE — no production run_gate record within {_DEFAULT_MAX_AGE_DAYS}d "
        "(wired but not recently called → dead-code risk); or partition holds "
        "only non-production / malformed records"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())

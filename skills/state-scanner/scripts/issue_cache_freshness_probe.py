#!/usr/bin/env python3
"""Spec C — issue-cache-freshness probe (Phase 1.13 liveness reverse-evidence).

Reverse-evidence check that Phase 1.13 (issue scan) is actually producing fresh
data. Reads the PREVIOUS ``.aria/state-snapshot.json`` (lag-1: at custom-check
evaluation time in Phase 1.11 the *current* scan has not written its snapshot yet,
so the file on disk is the previous scan's output — this check audits the previous
scan; a fault surfaces on the next scan).

PRIMARY signal (A1, review-driven) — issue-fetch HEALTH, not a Δ threshold:
  The upper-bound Δ = generated_at − fetched_at check alone is near-vacuous on real
  data: the collector only serves cache within 1×TTL (issue_scan.py cache gate), so
  a real snapshot's Δ is always < 1×TTL < 2×TTL → it can never emit STALE, and the
  actual failure mode (fetch broke → fetched_at=None) would map to SKIP = a green
  void exactly when it should alarm (review Finding 1/2). So the primary staleness
  trigger is a MISSING ``issue_status.fetched_at`` while issue_scan is ENABLED
  (persistent fetch failure, all repos failed) → STALE (surfaced, not hidden).
  A TRANSIENT ``fetch_error`` WITH a still-fresh ``fetched_at`` is NOT stale (spec
  AC-2 orthogonality — a cached-but-fresh value survives one failed refresh), so
  the trigger keys on ``fetched_at`` presence, not on ``fetch_error``/``source``.
  The Δ upper bound is retained only as a SECONDARY guard.

Verdicts (returned by ``evaluate``; the CLI maps them to the custom-check contract):
  "ok"    — issue_scan disabled, OR issue fetch healthy and Δ ≤ 2×TTL
  "stale" — issue_scan enabled but the previous scan's issue fetch is broken
            (fetch_error set / source unavailable / no fetched_at), OR (secondary)
            Δ > 2×TTL
  "skip"  — insufficient data to judge: no previous snapshot / previous snapshot
            missing generated_at (pre-Spec-C schema) / no issue_status (issue_scan
            was off in the previous scan) / corrupt JSON / unparseable timestamps.
            Visible, counted as NEITHER pass NOR fail (AC-5b).

Known limitation (aggregate semantics — review-confirm Major, documented not fixed):
  ``issue_status.fetched_at`` is the aggregate ``min`` over all scanned repos
  (issue_scan.py). With ``scan_submodules=true``, if the MAIN repo's fetch is broken
  (fetch_error set, its per-repo fetched_at=None) but a submodule still fetched, the
  aggregate fetched_at is the submodule's fresh stamp → this probe reports OK even
  though the main repo's issue-awareness is dead. This is NOT introduced by A1 (the
  old Δ-only mechanism had the identical aggregate blind spot) and is consistent with
  the aggregate reading "is issue-awareness refreshing ANYWHERE". A per-repo (main)
  assertion would tighten this — deferred as a follow-up; do not read this check as a
  per-repo guarantee.

CLI contract (B1): "skip" is signalled to collectors/custom_checks.py by printing a
first stdout line beginning with the "##SKIP##" marker and exiting 0 — a collision-
free stdout marker, NOT exit code 2 (grep/diff/argparse use 2 for real errors).
  ok    → print message, exit 0
  stale → print message, exit 1
  skip  → print "##SKIP## <message>", exit 0

Output is deterministic bucketed text (no embedded Δ digits; fetch_error labels are
a bounded enum) so two evaluations of the same previous snapshot render identically
(AC-4).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

_DEFAULT_TTL_SECONDS = 900

# Must match collectors/custom_checks.py SKIP_MARKER (the framework owns the
# convention; this standalone script prints the agreed literal).
SKIP_MARKER = "##SKIP##"


def _iso(s: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp. Accepts both the 'Z' form produced by
    scan.py/issue_scan._now_iso() and the '+00:00' form; returns an aware dt."""
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def evaluate(repo: Path) -> tuple[str, str]:
    """Pure evaluation: return (verdict, message) with verdict in
    {"ok", "stale", "skip"}. No printing, no sys.exit — directly unit-testable."""
    try:
        cfg = json.loads((repo / ".aria" / "config.json").read_text(encoding="utf-8"))
    except Exception:
        # Config unreadable → cannot tell if issue_scan is enabled; SKIP (visible)
        # rather than green-washing or failing.
        return "skip", "SKIP (config unreadable)"

    iss_cfg = (cfg.get("state_scanner") or {}).get("issue_scan") or {}
    if not iss_cfg.get("enabled"):
        return "ok", "OK (disabled)"

    try:
        ttl = float(iss_cfg.get("cache_ttl_seconds", _DEFAULT_TTL_SECONDS))
    except (TypeError, ValueError):
        ttl = float(_DEFAULT_TTL_SECONDS)

    snap_path = repo / ".aria" / "state-snapshot.json"
    try:
        snap = json.loads(snap_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "skip", "SKIP (no previous snapshot — first run)"
    except Exception:
        return "skip", "SKIP (previous snapshot unreadable/corrupt)"
    if not isinstance(snap, dict):
        return "skip", "SKIP (previous snapshot not an object)"

    gen = snap.get("generated_at")
    if not gen:
        return "skip", "SKIP (previous snapshot missing generated_at — pre-Spec-C schema)"

    issue_status = snap.get("issue_status")
    if not isinstance(issue_status, dict):
        # issue_status absent/None/non-dict → previous scan had issue_scan disabled,
        # or a hand-edited/corrupt snapshot. Genuine no-data → SKIP (not this check's
        # fault domain, and must not crash on non-dict — review R-b1).
        return "skip", "SKIP (previous snapshot has no issue_status — issue_scan was off)"

    # --- PRIMARY (A1): issue-fetch health -----------------------------------
    # The staleness trigger is a MISSING fetched_at (no usable data at all —
    # persistent fetch failure: token expired / network down / CLI missing, all
    # repos failed → aggregate fetched_at=None per issue_scan.py). This is the
    # green-void the Δ-only check missed (review Finding 1): issue-awareness is not
    # refreshing, surface it as STALE.
    #
    # A TRANSIENT fetch_error WITH a still-fresh fetched_at is deliberately NOT
    # stale (spec AC-2 orthogonality: "fetch attempt failed" and "data staleness"
    # are independent — a cached-but-fresh value survives one failed refresh). So
    # we key on fetched_at presence, NOT on fetch_error / source alone.
    fetched = issue_status.get("fetched_at")
    if not fetched:
        return "stale", "STALE — issue fetch has no usable data (all repos failed / source unavailable); issue-awareness not refreshing"

    # --- SECONDARY: Δ upper bound (defensive; rarely reachable — collector gates
    # cache at 1×TTL so real Δ < 1×TTL, but a hand-built / cross-config snapshot
    # could exceed it) -------------------------------------------------------
    try:
        delta = (_iso(gen) - _iso(str(fetched))).total_seconds()
    except Exception:
        return "skip", "SKIP (unparseable timestamps)"

    if delta <= 2 * ttl:
        return "ok", "OK"
    return "stale", "STALE — data older than 2xTTL at scan time"


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    repo = Path(argv[0]) if argv else Path.cwd()
    verdict, msg = evaluate(repo)
    if verdict == "skip":
        print(f"{SKIP_MARKER} {msg}")
        return 0
    print(msg)
    return 0 if verdict == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())

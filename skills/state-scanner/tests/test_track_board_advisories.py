#!/usr/bin/env python3
"""track_board ⚪ identity-drift advisory rendering + old-snapshot tolerance.

owner-container-identity-key-and-collision-parser TASK-004 (SC-8) / TASK-019 (SC-10).
"""
from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

_SS_ROOT = Path(__file__).resolve().parent.parent
if str(_SS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SS_ROOT))
if str(_SS_ROOT / "scripts") not in sys.path:
    sys.path.append(str(_SS_ROOT / "scripts"))

from lib import collision  # noqa: E402
from collectors.handoff_multibranch import dedupe_latest_per_track_container  # noqa: E402
from renderers.track_board import render_track_board  # noqa: E402

_FIXTURE = _SS_ROOT / "tests" / "fixtures" / "handoff-tracks-frozen-2026-09-05.json"
_NOW = datetime(2026, 9, 5, 0, 0, tzinfo=timezone.utc)


def _snapshot(tracks: list[dict], collision_field: dict | None) -> dict:
    tm = {
        "exists": bool(tracks),
        "tracks": tracks,
        "branches_scanned": ["master"],
        "legacy_count": sum(1 for t in tracks if t.get("legacy")),
        "errors": [],
    }
    if collision_field is not None:
        tm["collision"] = collision_field
    return {
        "tracks_multibranch": tm,
        "coordination_fetch": {"attempted": True, "success": True, "fetched_at": "2026-09-05T00:00:00Z"},
    }


def _row(track_id, oc, status="active", updated="2026-09-01T00:00:00Z", filename=None):
    return {"track_id": track_id, "owner_container": oc, "status": status, "phase": "B",
            "updated_at": updated, "filename": filename or f"{updated[:10]}-{track_id}.md", "branch": "master", "legacy": False}


class TestOldSnapshotTolerance(unittest.TestCase):
    """SC-8: a snapshot written before this spec has no ``identity_advisories``
    (or no ``collision`` at all) — the board must still render (baseline-green
    lock-in, not RED)."""

    def test_missing_identity_advisories_key_does_not_crash(self):
        tracks = [_row("t", "alice/aaaa1111"), _row("t", "bob/bbbb2222")]
        out = render_track_board(_snapshot(tracks, {"kind": "cross_owner", "groups": [["alice/aaaa1111", "bob/bbbb2222"]]}), now=_NOW)
        self.assertIn("COLLISION", out)

    def test_missing_collision_block_does_not_crash(self):
        out = render_track_board(_snapshot([_row("t", "alice/aaaa1111")], None), now=_NOW)
        self.assertIsInstance(out, str)


class TestAdvisoryRendering(unittest.TestCase):
    """SC-10: ⚪ lines are computed by the renderer from the RAW tracks (pre-dedupe)."""

    def test_fixture_renders_exactly_two_advisory_lines(self):
        rows = json.loads(_FIXTURE.read_text(encoding="utf-8"))["tracks"]
        out = render_track_board(_snapshot(rows, {"kind": "none", "groups": [], "identity_advisories": []}), now=_NOW)
        adv_lines = [l for l in out.splitlines() if l.startswith("⚪")]
        self.assertEqual(len(adv_lines), 2, out[-800:])
        keys = sorted(l.split()[2].rstrip(":") for l in adv_lines)
        self.assertEqual(keys, ["023236f2", "bfe8285d"])
        for l in adv_lines:
            self.assertIn("aria-runner-bot", l)
            self.assertIn("simonfish", l)
            self.assertIn("first_seen=", l)
            self.assertIn("last_seen=", l)

    def test_counterfactual_deduped_rows_yield_zero_advisories(self):
        """If the renderer computed advisories on post-dedupe rows, the fixture
        would give 0 (each (track, identity_key) collapses to one owner)."""
        rows = json.loads(_FIXTURE.read_text(encoding="utf-8"))["tracks"]
        deduped, _ = dedupe_latest_per_track_container(rows)
        self.assertEqual(len(collision.identity_drift_advisories(rows)), 2)
        self.assertEqual(collision.identity_drift_advisories(deduped), [])

    def test_no_advisory_no_section(self):
        tracks = [_row("t", "alice/aaaa1111"), _row("u", "alice/aaaa1111")]
        out = render_track_board(_snapshot(tracks, {"kind": "none", "groups": [], "identity_advisories": []}), now=_NOW)
        self.assertNotIn("⚪", out)
        self.assertNotIn("IDENTITY-DRIFT", out)


if __name__ == "__main__":
    unittest.main()

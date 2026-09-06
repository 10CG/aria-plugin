#!/usr/bin/env python3
"""Frozen-corpus attribution for the Layer H collision pipeline.

owner-container-identity-key-and-collision-parser TASK-006 (SC-6) + TASK-016 (SC-11).

The fixture ``tests/fixtures/handoff-tracks-frozen-2026-09-05.json`` is this
repository's own handoff history (996 rows, eight frontmatter fields, produced
by ``tests/fixtures/freeze_corpus.py``).  Baseline on aria 7dd0135 (recorded in
the spec's experiment table, R3 three seats reproduced independently):

    variant A (3-part parser, old dedupe key)       -> 1 group  self_multi_container
    D1 (2-part + identity_key dedupe, no window)    -> 2 groups self_multi_container
    D1 + D-3(a) 30-day Layer H window               -> 0 groups

Every group that the production path still produces WITHOUT the window is
attributed mechanically here — nobody eyeballs the corpus:

    all rows in the group older than LAYER_H_ACTIVE_WINDOW_DAYS -> "stale(#182)"
    else kind == cross_owner                                    -> "true-collision"
    else kind == self_multi_container                           -> "same-owner-multi-machine"

A synthetic, freshly-dated true collision is injected to prove the attribution
can say "true-collision" at all (counterfactual for the rule set).
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SS_ROOT = Path(__file__).resolve().parent.parent
if str(_SS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SS_ROOT))
if str(_SS_ROOT / "scripts") not in sys.path:
    sys.path.append(str(_SS_ROOT / "scripts"))

from lib import collision  # noqa: E402
from lib.constants import LAYER_H_ACTIVE_WINDOW_DAYS  # noqa: E402  (RED on 7dd0135: ImportError)
from collectors.handoff_multibranch import dedupe_latest_per_track_container  # noqa: E402

_FIXTURE = _SS_ROOT / "tests" / "fixtures" / "handoff-tracks-frozen-2026-09-05.json"
_FROZEN_NOW = datetime(2026, 9, 5, 0, 0, tzinfo=timezone.utc)


def _load_rows() -> list[dict]:
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    rows = payload["tracks"]
    assert payload["fields"] == ["track_id", "owner_container", "status", "phase", "updated_at", "filename", "branch", "legacy"]
    return [dict(r) for r in rows]


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _attribute(group_members: list[str], kind: str, rows_by_oc: dict[str, list[dict]], now: datetime) -> str:
    cutoff = now - timedelta(days=LAYER_H_ACTIVE_WINDOW_DAYS)
    member_rows = [r for oc in group_members for r in rows_by_oc.get(oc, [])]
    if member_rows and all(_parse(r["updated_at"]) < cutoff for r in member_rows):
        return "stale(#182)"
    if kind == "cross_owner":
        return "true-collision"
    if kind == "self_multi_container":
        return "same-owner-multi-machine"
    return "unclassified"


def _production_groups(rows: list[dict], *, now: datetime, apply_window: bool):
    """The exact collector path: (window) -> dedupe -> classify; returns per-group (members, kind)."""
    src = collision.filter_layer_h_fresh(rows, now=now) if apply_window else rows
    deduped, _ = dedupe_latest_per_track_container(src)
    summary = collision.classify(deduped, now=now)
    # classify() only exposes the aggregate kind; recover per-group kind by
    # re-classifying each group's members in isolation (same rows, same rules).
    out = []
    for members in summary["groups"]:
        sub = [r for r in deduped if r["owner_container"] in members]
        kind = collision.classify(sub, now=now)["kind"]
        out.append((members, kind))
    return out, summary


class TestFrozenCorpusAttribution(unittest.TestCase):
    def setUp(self):
        self.rows = _load_rows()
        self.rows_by_oc: dict[str, list[dict]] = {}
        for r in self.rows:
            self.rows_by_oc.setdefault(r["owner_container"], []).append(r)

    def test_fixture_is_the_frozen_996_row_corpus(self):
        self.assertEqual(len(self.rows), 996)
        self.assertTrue(all(set(r) == {"track_id", "owner_container", "status", "phase", "updated_at", "filename", "branch", "legacy"} for r in self.rows))

    def test_without_window_every_group_is_stale_182(self):
        """D1 without the window: the groups the corpus still yields are all
        2026-05..07 residue — mechanically attributed stale(#182), none is a
        true collision. How it goes red: an implementation that keeps the owner
        segment inside the uuid identity_key (or drops the 'non-empty, non-
        unknown owner' rule) produces a cross_owner group here -> 'true-collision'."""
        groups, summary = _production_groups(self.rows, now=_FROZEN_NOW, apply_window=False)
        self.assertGreaterEqual(len(groups), 1, summary)
        table = {tuple(m): _attribute(m, k, self.rows_by_oc, _FROZEN_NOW) for m, k in groups}
        self.assertTrue(all(v == "stale(#182)" for v in table.values()), table)
        self.assertNotEqual(summary["kind"], "cross_owner", summary)

    def test_with_window_zero_groups(self):
        """D-3(a): applying LAYER_H_ACTIVE_WINDOW_DAYS before dedupe -> 0 groups."""
        groups, summary = _production_groups(self.rows, now=_FROZEN_NOW, apply_window=True)
        self.assertEqual(groups, [], summary)
        self.assertEqual(summary, {"kind": "none", "groups": []})

    def test_injected_fresh_true_collision_is_attributed_true_collision(self):
        now_s = _FROZEN_NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
        injected = [
            {"track_id": "synthetic-true-collision", "owner_container": "alice/aaaa1111", "status": "active", "phase": "B", "updated_at": now_s, "filename": "2026-09-05-inj-a.md", "branch": "master", "legacy": False, "injected": True},
            {"track_id": "synthetic-true-collision", "owner_container": "bob/bbbb2222", "status": "active", "phase": "B", "updated_at": now_s, "filename": "2026-09-05-inj-b.md", "branch": "master", "legacy": False, "injected": True},
        ]
        rows = self.rows + injected
        by_oc = dict(self.rows_by_oc)
        for r in injected:
            by_oc.setdefault(r["owner_container"], []).append(r)
        groups, summary = _production_groups(rows, now=_FROZEN_NOW, apply_window=True)
        self.assertEqual(len(groups), 1, summary)
        members, kind = groups[0]
        self.assertEqual(members, ["alice/aaaa1111", "bob/bbbb2222"])
        self.assertEqual(_attribute(members, kind, by_oc, _FROZEN_NOW), "true-collision")
        self.assertEqual(summary["kind"], "cross_owner")

    def test_family_key_strip_has_zero_corpus_collisions(self):
        """D-0(a): stripping ``-<8hex>`` from every corpus track_id must not
        merge two previously distinct tracks (e.g. ``x-20260719`` -> ``x``
        collides with nothing)."""
        pat = re.compile(r"-[0-9a-f]{8}$")
        originals = {r["track_id"] for r in self.rows if not r["legacy"]}
        stripped_map: dict[str, set[str]] = {}
        for tid in originals:
            stripped_map.setdefault(pat.sub("", tid), set()).add(tid)
        merged = {k: v for k, v in stripped_map.items() if len(v) > 1}
        self.assertEqual(merged, {}, merged)
        self.assertIn("x-20260719", originals)
        # and the library agrees on the shape rule for that row
        rec = collision.track_to_claim_record({"track_id": "x-20260719", "owner_container": "a/b", "updated_at": "2026-07-19T00:00:00Z"})
        self.assertEqual(rec.track_id, "x")


class TestLayerHWindowSingleImplementation(unittest.TestCase):
    """SC-11: stale active rows never reach groups; collector and renderer share
    ONE freshness predicate living in lib/."""

    def test_stale_active_rows_absent_from_groups(self):
        rows = _load_rows()
        cutoff = _FROZEN_NOW - timedelta(days=LAYER_H_ACTIVE_WINDOW_DAYS)
        stale_active = {r["owner_container"] for r in rows if r["status"] == "active" and _parse(r["updated_at"]) < cutoff}
        self.assertGreater(len(stale_active), 0, "fixture must contain stale active rows for this test to bite")
        groups, _ = _production_groups(rows, now=_FROZEN_NOW, apply_window=True)
        in_groups = {oc for m, _k in groups for oc in m}
        self.assertEqual(in_groups & stale_active, set())

    def test_predicate_defined_once_in_lib(self):
        lib_text = (_SS_ROOT / "lib" / "collision.py").read_text(encoding="utf-8")
        const_text = (_SS_ROOT / "lib" / "constants.py").read_text(encoding="utf-8")
        collector = (_SS_ROOT / "scripts" / "collectors" / "handoff_multibranch.py").read_text(encoding="utf-8")
        renderer = (_SS_ROOT / "scripts" / "renderers" / "track_board.py").read_text(encoding="utf-8")
        self.assertRegex(const_text, r"^LAYER_H_ACTIVE_WINDOW_DAYS\s*[:=]", "constant must live in lib/constants.py")
        self.assertIn("def layer_h_is_fresh", lib_text)
        self.assertIn("def filter_layer_h_fresh", lib_text)
        day_compare = re.compile(r"timedelta\(\s*days\s*=")
        self.assertEqual(len(day_compare.findall(collector)), 0, "collector must not re-implement the window")
        self.assertEqual(len(day_compare.findall(renderer)), 0, "renderer must not re-implement the window")
        self.assertGreaterEqual(len(day_compare.findall(lib_text)), 1)
        # both consumers call the same lib entry point
        self.assertIn("filter_layer_h_fresh", collector)
        self.assertIn("filter_layer_h_fresh", renderer)


if __name__ == "__main__":
    unittest.main()

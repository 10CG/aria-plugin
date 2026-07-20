#!/usr/bin/env python3
"""SC-8: real-corpus golden zero-false-alarm check (aria-plugin #113 TASK-007).

Method (memory `feedback_gate_tracks_reality_synthetic_fixture`): block/pass
CONTRACTS are pinned by self-contained synthetic fixtures (test_detailed_tasks.py
/ test_gate_yaml_datasource.py). This file is the complementary **bounded
real-corpus sample** proving the new parser does not misfire on the actual
yaml-only specs that exist in the Aria meta-repo today — the three specs whose
archive dirs carry `detailed-tasks.yaml` and no `tasks.md`:

    2026-05-29-aria-context-monitor            (9 tasks, 2 integration titles)
    2026-05-30-ai-native-estimator             (8 tasks, 1 integration title)
    2026-05-30-emergency-hotfix-and-audit-file-scope (8 tasks, 0 integration titles)

Every task in all three is `status: done`, so the residual axis must be clean for
all three; the integrity axis (SC-2b) fires only for the first two. Outside the
Aria meta-repo checkout the corpus is absent → SkipTest (existing
`_require_meta_archive` precedent, not a silent pass).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

# `_helpers` already puts scripts/ on sys.path; importing collectors._status
# BEFORE the bare lib modules pre-loads the collectors package, resolving the
# pre-existing spec_complete ↔ collectors/__init__ cycle (same ordering as
# test_spec_complete.py:56-57). Only scripts/lib is inserted here — inserting
# scripts/ itself at position 0 would shadow the top-level `lib` package
# (state-scanner/lib) for the WHOLE suite (test_collision et al).
from _helpers import tmp_project  # noqa: E402,F401
from collectors._status import _normalize_status  # noqa: E402,F401

_LIB_DIR = str(Path(__file__).resolve().parent.parent / "scripts" / "lib")
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)
from detailed_tasks import is_done_status, parse_detailed_tasks  # noqa: E402
from spec_complete import gate_result, is_spec_complete  # noqa: E402

# tests/ → state-scanner → skills → aria → <meta-repo root>
_META_ARCHIVE_ROOT = Path(__file__).resolve().parents[4] / "openspec" / "archive"

_INTEGRATION_CLAIM = "archive-safety-net-integration-claims-unverified"
_UNPARSEABLE_CLAIM = "archive-safety-net-source-unparseable"
_RETIRED_BLANKET = "archive-safety-net-source-unsupported"

# spec dir name → expected count of done-family integration titles (實測 2/1/0).
_GOLDEN = {
    "2026-05-29-aria-context-monitor": 2,
    "2026-05-30-ai-native-estimator": 1,
    "2026-05-30-emergency-hotfix-and-audit-file-scope": 0,
}


def _require_meta_archive() -> Path:
    if not _META_ARCHIVE_ROOT.is_dir():
        raise unittest.SkipTest(
            f"real-tree dogfood corpus not found at {_META_ARCHIVE_ROOT} "
            "(expected when aria-plugin is tested outside the Aria meta-repo checkout)"
        )
    return _META_ARCHIVE_ROOT


def _golden_dirs():
    archive = _require_meta_archive()
    found = {}
    for name in _GOLDEN:
        d = archive / name
        if (d / "detailed-tasks.yaml").is_file() and not (d / "tasks.md").is_file():
            found[name] = d
    if not found:
        raise unittest.SkipTest("no yaml-only golden spec dirs present in this checkout")
    # All-or-nothing: a PARTIAL corpus (one spec renamed / re-archived) must be a
    # loud failure, not silently reduced coverage (pre-merge silent-failure-hunter).
    missing = sorted(set(_GOLDEN) - set(found))
    if missing:
        raise AssertionError(
            f"golden corpus partially present — {len(found)}/{len(_GOLDEN)} found, "
            f"missing (renamed? re-archived? gained a tasks.md?): {missing}"
        )
    return found


class TestSC8GoldenCorpus(unittest.TestCase):
    def test_all_parse_ok_and_all_tasks_done(self):
        for name, d in _golden_dirs().items():
            with self.subTest(spec=name):
                parsed = parse_detailed_tasks(
                    (d / "detailed-tasks.yaml").read_text(encoding="utf-8", errors="replace")
                )
                self.assertTrue(parsed["parse_ok"], f"{name}: {parsed['reason']}")
                self.assertTrue(parsed["tasks"], name)
                non_done = [t["id"] for t in parsed["tasks"] if not is_done_status(t["raw_status"])]
                self.assertEqual(non_done, [], f"{name} unexpected non-done: {non_done}")

    def test_residual_axis_clean_for_all(self):
        for name, d in _golden_dirs().items():
            with self.subTest(spec=name):
                result = gate_result(d)
                claims = {c["claim"] for c in result["unverified_claims"]}
                self.assertNotIn(_UNPARSEABLE_CLAIM, claims, name)
                self.assertNotIn(_RETIRED_BLANKET, claims, name)
                payload = result["d_payload"]
                deferred = payload["deferred_items"] if payload else []
                self.assertEqual(deferred, [], f"{name} unexpected residuals: {deferred}")

    def test_integrity_axis_per_fixture_expectation(self):
        for name, d in _golden_dirs().items():
            expected = _GOLDEN[name]
            with self.subTest(spec=name, expected_integration_titles=expected):
                result = gate_result(d)
                claims = {c["claim"] for c in result["unverified_claims"]}
                if expected:
                    self.assertIn(_INTEGRATION_CLAIM, claims, name)
                    self.assertEqual(result["verdict"], "warn", name)
                    entry = next(
                        c for c in result["unverified_claims"] if c["claim"] == _INTEGRATION_CLAIM
                    )
                    self.assertIn(f"含 {expected} 条", entry["reason"], entry["reason"])
                else:
                    # full pass: residual-axis clean ∧ zero done-family integration titles
                    self.assertNotIn(_INTEGRATION_CLAIM, claims, name)
                    self.assertEqual(result["verdict"], "pass", name)
                    self.assertIsNone(result["d_payload"], name)

    def test_is_spec_complete_true_for_all(self):
        for name, d in _golden_dirs().items():
            with self.subTest(spec=name):
                verdict = is_spec_complete(d)
                self.assertTrue(verdict["complete"], f"{name}: {verdict['reason']}")


if __name__ == "__main__":
    unittest.main()

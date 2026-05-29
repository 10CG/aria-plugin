#!/usr/bin/env python3
"""Deterministic structural tests for token_telemetry (Rule #6 substitute + TASK-007 fallback).

stdlib unittest only (no pytest dependency). Run:
  python3 -m unittest discover -s aria/skills/aria-token-telemetry/tests -p 'test_*.py'
or directly:
  python3 aria/skills/aria-token-telemetry/tests/test_token_telemetry.py

Fixtures: aria-plugin-benchmarks/context-monitor/ (relay fresh/stale/corrupt/schema-mismatch,
transcript sample/no-usage). Per feedback_deterministic_structural_skill_rule6_substitute.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone

# locate token_telemetry.py (scripts/ sibling of tests/)
_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.join(_HERE, "..", "scripts")
sys.path.insert(0, _SCRIPTS)
import token_telemetry as tt  # noqa: E402

# fixtures dir: aria-plugin-benchmarks/context-monitor/ (repo root = 4 levels up from tests/)
_REPO = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
_FIX = os.path.join(_REPO, "aria-plugin-benchmarks", "context-monitor")


def _fresh_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_fixture(name):
    with open(os.path.join(_FIX, name), "r", encoding="utf-8") as fh:
        return fh.read()


class _ProjectRoot:
    """Build a temp project root with optional relay cache + transcript discovery patch."""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="aria-tt-test-")
        os.makedirs(os.path.join(self.root, ".aria", "cache"), exist_ok=True)

    def write_cache(self, content):
        with open(os.path.join(self.root, ".aria", "cache", "context-window.json"), "w", encoding="utf-8") as fh:
            fh.write(content)

    def write_config(self, cm: dict):
        with open(os.path.join(self.root, ".aria", "config.json"), "w", encoding="utf-8") as fh:
            json.dump({"context_monitor": cm}, fh)

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


class RelayPathTests(unittest.TestCase):
    def setUp(self):
        self.p = _ProjectRoot()
        self._orig_find = tt.find_transcript
        tt.find_transcript = lambda root: None  # isolate: no transcript unless explicitly tested

    def tearDown(self):
        tt.find_transcript = self._orig_find
        self.p.cleanup()

    def test_relay_fresh_high_confidence(self):
        self.p.write_cache(_load_fixture("relay-fresh.json").replace("REPLACE_FRESH", _fresh_iso()))
        r = tt.collect(self.p.root)
        self.assertEqual(r["source"], "relay_cache")
        self.assertEqual(r["confidence"], "high")
        self.assertEqual(r["window_source"], "runtime")
        self.assertEqual(r["used_percentage"], 16)
        self.assertIsNone(r["used_percentage_proxy"], "口径不混用: relay 路径 proxy 必 null")
        self.assertEqual(r["context_window_size"], 1_000_000)
        self.assertEqual(r["model_id"], "claude-opus-4-8[1m]")
        self.assertGreaterEqual(r["staleness_seconds"], 0)

    def test_relay_stale_falls_back(self):
        # stale relay + no transcript → unavailable (proves it did NOT trust stale relay)
        self.p.write_cache(_load_fixture("relay-stale.json"))
        r = tt.collect(self.p.root)
        self.assertNotEqual(r["source"], "relay_cache", "stale relay must not be trusted")
        self.assertEqual(r["source"], "unavailable")

    def test_relay_corrupt_no_exception(self):
        self.p.write_cache(_load_fixture("relay-corrupt.json"))
        r = tt.collect(self.p.root)  # must not raise
        self.assertEqual(r["source"], "unavailable")
        self.assertIsNone(r["used_percentage"])
        self.assertIsNone(r["used_percentage_proxy"], "unavailable 态两者皆 null (一致性)")

    def test_relay_missing_used_percentage_falls_back(self):
        # review Minor 1: relay cache valid size+fresh but no used_percentage must NOT
        # return confidence=high with used_percentage=null (contradiction) → fall back.
        import json as _json
        cache = _json.loads(_load_fixture("relay-fresh.json").replace("REPLACE_FRESH", _fresh_iso()))
        del cache["used_percentage"]
        self.p.write_cache(_json.dumps(cache))
        r = tt.collect(self.p.root)
        self.assertNotEqual(r["source"], "relay_cache",
                            "relay missing used_percentage must fall back, not return high+null")
        self.assertEqual(r["source"], "unavailable")  # no transcript patched in setUp

    def test_relay_schema_mismatch_ignored(self):
        self.p.write_cache(_load_fixture("relay-schema-mismatch.json").replace("REPLACE_FRESH", _fresh_iso()))
        r = tt.collect(self.p.root)
        self.assertNotEqual(r["source"], "relay_cache", "schema_version mismatch must be ignored")

    def test_custom_staleness_threshold_override(self):
        # relay-stale (year 2020) normally → fallback; with a huge custom threshold it
        # becomes "fresh" → relay_cache. Proves config override is honored deterministically.
        self.p.write_cache(_load_fixture("relay-stale.json"))
        self.p.write_config({"staleness_threshold_seconds": 10**12})
        r = tt.collect(self.p.root)
        self.assertEqual(r["source"], "relay_cache", "huge threshold must make 2020 cache fresh")
        self.assertEqual(r["confidence"], "high")


class TranscriptPathTests(unittest.TestCase):
    def setUp(self):
        self.p = _ProjectRoot()
        self._orig_find = tt.find_transcript

    def tearDown(self):
        tt.find_transcript = self._orig_find
        self.p.cleanup()

    def test_transcript_fallback_proxy(self):
        tt.find_transcript = lambda root: os.path.join(_FIX, "transcript-sample.jsonl")
        r = tt.collect(self.p.root)
        self.assertEqual(r["source"], "transcript_fallback")
        self.assertEqual(r["confidence"], "estimate")
        self.assertIsNone(r["used_percentage"], "口径不混用: transcript 路径 used_percentage 必 null")
        self.assertIsNotNone(r["used_percentage_proxy"])
        # last-turn occupancy = 10 + 1000 + 148000 = 149010 → fits 200K tier (empirical_peak)
        self.assertEqual(r["window_source"], "empirical_peak")
        self.assertEqual(r["context_window_size"], 200_000)

    def test_transcript_no_usage_unavailable(self):
        tt.find_transcript = lambda root: os.path.join(_FIX, "transcript-no-usage.jsonl")
        r = tt.collect(self.p.root)
        self.assertEqual(r["source"], "unavailable")

    def test_parse_transcript_usage_window_independent(self):
        """raw counts interface reusable by #18, independent of window%."""
        usage = tt.parse_transcript_usage(os.path.join(_FIX, "transcript-sample.jsonl"))
        self.assertEqual(usage["input_tokens"], 10)  # last turn wins
        self.assertEqual(usage["cache_read_input_tokens"], 148000)
        self.assertEqual(usage["model"], "claude-opus-4-8")
        self.assertNotIn("window", usage, "raw counts must not carry window")


class WindowResolveTiers(unittest.TestCase):
    """window 4-tier resolve: cached_size_reuse > config > empirical_peak > default."""

    def test_tier1_cached_size_reuse(self):
        size, src = tt.resolve_window({"input_tokens": 10}, {}, last_known_size=1_000_000)
        self.assertEqual(src, "cached_size_reuse")
        self.assertEqual(size, 1_000_000)

    def test_tier2_config(self):
        size, src = tt.resolve_window({"input_tokens": 10}, {"window_tokens": 500_000}, last_known_size=None)
        self.assertEqual(src, "config")
        self.assertEqual(size, 500_000)

    def test_tier3_empirical_peak(self):
        usage = {"input_tokens": 1, "cache_read_input_tokens": 300_000, "cache_creation_input_tokens": 0}
        size, src = tt.resolve_window(usage, {}, last_known_size=None)
        self.assertEqual(src, "empirical_peak")
        self.assertEqual(size, 1_000_000, "300K occupancy snaps to 1M tier")

    def test_tier4_default(self):
        size, src = tt.resolve_window({"input_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}, {}, last_known_size=None)
        self.assertEqual(src, "default")
        self.assertEqual(size, 200_000)

    def test_window_source_enum_has_5(self):
        self.assertEqual(len(tt.WINDOW_SOURCE_ENUM), 5)

    def test_staleness_default_300(self):
        self.assertEqual(tt.DEFAULT_STALENESS_THRESHOLD_SECONDS, 300)
        self.assertEqual(tt.staleness_threshold({}), 300)


if __name__ == "__main__":
    unittest.main(verbosity=2)

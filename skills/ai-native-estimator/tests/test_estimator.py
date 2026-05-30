#!/usr/bin/env python3
"""ai-native-estimator tests (Rule #6 deterministic structural substitute, #18 v1).

Covers all 11 Success Criteria. stdlib unittest only. Run:
  python3 aria/skills/ai-native-estimator/tests/test_estimator.py
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "scripts"))
import estimator as est  # noqa: E402


def _turn(uuid, ts, out, cc=0, inp=1, cr=0, sid="s1"):
    return json.dumps({
        "type": "assistant", "uuid": uuid, "parentUuid": None,
        "sessionId": sid, "timestamp": ts,
        "message": {"usage": {"input_tokens": inp, "output_tokens": out,
                              "cache_creation_input_tokens": cc, "cache_read_input_tokens": cr}},
    })


class _Env:
    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="est-test-")
        os.makedirs(os.path.join(self.root, ".aria"), exist_ok=True)
        self.warns = []

    def warn(self, m):
        self.warns.append(m)

    def transcript(self, lines):
        fd, path = tempfile.mkstemp(suffix=".jsonl", dir=self.root)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        return path

    def config(self, cm):
        with open(os.path.join(self.root, ".aria", "config.json"), "w", encoding="utf-8") as fh:
            json.dump({"ai_native_estimator": cm}, fh)

    def variance_count(self):
        return len(est.read_variance(self.root))

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.e = _Env()

    def tearDown(self):
        self.e.cleanup()

    def test_capture_appends_and_advances_watermark(self):
        t = self.e.transcript([_turn("u1", "2026-05-30T06:00:00.0Z", out=10, cc=5),
                               _turn("u2", "2026-05-30T06:01:00.0Z", out=20, cc=5)])
        r = est.capture(self.e.root, {"spec_slug": "demo", "spec_level": 2}, t, warn=self.e.warn)
        self.assertIsNotNone(r)
        self.assertEqual(r["work_metric"], (10 + 20) + (5 + 5), "output+cache_creation summed over range")
        self.assertEqual(r["n_turns"], 2)
        self.assertEqual(r["cycle_id"], "demo-u2")  # end_uuid[:8]
        wm = est._read_watermark(self.e.root)
        self.assertEqual(wm["last_uuid"], "u2")

    def test_idempotent_empty_range_skip(self):
        # SC: rerun w/o new turns → skip, no append, watermark unchanged (NEW-C-1 fix)
        t = self.e.transcript([_turn("u1", "2026-05-30T06:00:00Z", out=10)])
        est.capture(self.e.root, {"spec_slug": "demo", "spec_level": 2}, t)
        wm1 = est._read_watermark(self.e.root)
        r2 = est.capture(self.e.root, {"spec_slug": "demo", "spec_level": 2}, t, warn=self.e.warn)
        self.assertIsNone(r2, "empty range → skip")
        self.assertEqual(self.e.variance_count(), 1, "no duplicate record")
        self.assertEqual(est._read_watermark(self.e.root), wm1, "watermark unchanged")

    def test_incremental_only_new_turns(self):
        t1 = self.e.transcript([_turn("u1", "2026-05-30T06:00:00Z", out=10)])
        est.capture(self.e.root, {"spec_slug": "demo", "spec_level": 2}, t1)
        # second transcript = same file content + 1 new turn
        t2 = self.e.transcript([_turn("u1", "2026-05-30T06:00:00Z", out=10),
                                _turn("u2", "2026-05-30T06:05:00Z", out=99)])
        r = est.capture(self.e.root, {"spec_slug": "demo", "spec_level": 2}, t2, warn=self.e.warn)
        self.assertEqual(r["n_turns"], 1, "only the new turn u2")
        self.assertEqual(r["work_metric"], 99)

    def test_uuid_miss_timestamp_fallback_warn(self):
        t1 = self.e.transcript([_turn("u1", "2026-05-30T06:00:00Z", out=10)])
        est.capture(self.e.root, {"spec_slug": "demo", "spec_level": 2}, t1)
        # rotated transcript: different uuids, later timestamps
        t2 = self.e.transcript([_turn("x9", "2026-05-30T07:00:00Z", out=50, sid="s2")])
        r = est.capture(self.e.root, {"spec_slug": "demo", "spec_level": 2}, t2, warn=self.e.warn)
        self.assertIsNotNone(r, "fallback captured new file's later-timestamp turns")
        self.assertTrue(any("fallback" in w for w in self.e.warns), "warned about fallback")

    def test_wall_clock_null_when_no_timestamp(self):
        t = self.e.transcript([_turn("u1", None, out=10), _turn("u2", None, out=5)])
        r = est.capture(self.e.root, {"spec_slug": "demo", "spec_level": 2}, t)
        self.assertIsNone(r["wall_clock_seconds"], "null when timestamps missing")

    def test_wall_clock_derived(self):
        t = self.e.transcript([_turn("u1", "2026-05-30T06:00:00Z", out=1),
                               _turn("u2", "2026-05-30T06:00:30Z", out=1)])
        r = est.capture(self.e.root, {"spec_slug": "demo", "spec_level": 2}, t)
        self.assertEqual(r["wall_clock_seconds"], 30)

    def test_raw_all_four_components_stored(self):
        t = self.e.transcript([_turn("u1", "2026-05-30T06:00:00Z", out=10, cc=3, inp=7, cr=100)])
        r = est.capture(self.e.root, {"spec_slug": "demo", "spec_level": 2}, t)
        self.assertEqual(r["tokens"], {"input": 7, "output": 10, "cache_read": 100, "cache_creation": 3})

    def test_no_transcript_skip_warn(self):
        r = est.capture(self.e.root, {"spec_slug": "demo", "spec_level": 2}, "/no/file.jsonl", warn=self.e.warn)
        self.assertIsNone(r)
        self.assertTrue(any("no transcript" in w.lower() or "no usage" in w.lower() for w in self.e.warns))

    def test_enabled_false_not_triggered(self):
        self.e.config({"enabled": False})
        t = self.e.transcript([_turn("u1", "2026-05-30T06:00:00Z", out=10)])
        r = est.capture(self.e.root, {"spec_slug": "demo", "spec_level": 2}, t)
        self.assertIsNone(r, "enabled:false → no capture")
        self.assertEqual(self.e.variance_count(), 0)

    def test_spec_level_null_recorded(self):
        t = self.e.transcript([_turn("u1", "2026-05-30T06:00:00Z", out=10)])
        r = est.capture(self.e.root, {"spec_slug": "quickfix", "spec_level": None}, t)
        self.assertIsNone(r["spec_level"])


class ForecastTests(unittest.TestCase):
    def setUp(self):
        self.e = _Env()

    def tearDown(self):
        self.e.cleanup()

    def _seed(self, level, metrics):
        # write variance records directly — unit-isolate forecast from capture/watermark
        for i, m in enumerate(metrics):
            est._append_variance(self.e.root, {
                "cycle_id": f"s{level}-{i}", "spec": f"s{level}-{i}", "spec_level": level,
                "captured_at": f"2026-05-30T06:0{i}:00.000Z", "work_metric": m,
                "wall_clock_seconds": 60, "tokens": {}})

    def test_insufficient_has_uncalibrated_and_bootstrap(self):
        self._seed(2, [100])  # N=1 < 3
        r = est.forecast(self.e.root, 2)
        self.assertEqual(r["status"], "insufficient")
        self.assertIs(r["uncalibrated"], True)
        self.assertEqual(r["bootstrap"], 150000)
        self.assertEqual(r["have"], 1)

    def test_median_when_enough(self):
        self._seed(2, [100, 300, 200])  # N=3, median 200
        r = est.forecast(self.e.root, 2)
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["median_work_metric"], 200)
        self.assertEqual(r["n"], 3)

    def test_cross_level_isolation(self):
        self._seed(2, [100, 200, 300])  # L2 N=3
        self._seed(1, [50])             # L1 N=1
        r = est.forecast(self.e.root, 1)
        self.assertEqual(r["status"], "insufficient", "L1 insufficient even though L2 has ≥3")
        self.assertEqual(r["have"], 1)

    def test_bootstrap_always_numeric_out_of_range_level(self):
        # review Minor#3: out-of-range level (L4) → bootstrap still numeric, not None
        r = est.forecast(self.e.root, 4)
        self.assertEqual(r["status"], "insufficient")
        self.assertIsInstance(r["bootstrap"], (int, float))
        self.assertIs(r["uncalibrated"], True)

    def test_forecast_none(self):
        r = est.forecast(self.e.root, None)
        self.assertEqual(r["status"], "insufficient")
        self.assertEqual(r["reason"], "no_spec_level")

    def test_spec_level_null_not_in_forecast(self):
        # 3 null-level records must NOT satisfy forecast(2) or forecast(None)-as-data
        for i in range(3):
            t = self.e.transcript([_turn(f"n{i}", f"2026-05-30T06:0{i}:00Z", out=100)])
            est.capture(self.e.root, {"spec_slug": f"q{i}", "spec_level": None}, t)
        self.assertEqual(est.forecast(self.e.root, 2)["status"], "insufficient")


class VelocityForecastNullSafe(unittest.TestCase):
    def setUp(self):
        self.e = _Env()

    def tearDown(self):
        self.e.cleanup()

    def test_velocity_empty_returns_list_no_raise(self):
        self.assertEqual(est.velocity(self.e.root), [])

    def test_velocity_window_and_order(self):
        for i in range(5):
            t = self.e.transcript([_turn(f"u{i}", f"2026-05-30T06:0{i}:00Z", out=10 * i)])
            est.capture(self.e.root, {"spec_slug": f"s{i}", "spec_level": 2}, t)
        v = est.velocity(self.e.root, window=2)
        self.assertEqual(len(v), 2, "window honored")
        self.assertIn("work_metric", v[0])
        self.assertIn("wall_clock_seconds", v[0])

    def test_forecast_excludes_wall_clock(self):
        t = self.e.transcript([_turn("u1", "2026-05-30T06:00:00Z", out=10),
                               _turn("u2", "2026-05-30T06:09:00Z", out=10)])
        est.capture(self.e.root, {"spec_slug": "demo", "spec_level": 2}, t)
        r = est.forecast(self.e.root, 2)
        self.assertNotIn("wall_clock", json.dumps(r), "forecast must not surface wall_clock")


class PortabilityTests(unittest.TestCase):
    """TASK-008: cross-project portability."""
    def setUp(self):
        self.e = _Env()

    def tearDown(self):
        self.e.cleanup()

    def test_missing_variance_forecast_insufficient(self):
        r = est.forecast(self.e.root, 2)
        self.assertEqual(r["status"], "insufficient")

    def test_history_empty_no_raise(self):
        self.assertEqual(est.history(self.e.root), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

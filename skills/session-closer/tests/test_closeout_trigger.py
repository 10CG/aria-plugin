"""closeout_trigger 单测 — 覆盖 proposal AC-6 (5 档) + 口径不混用 (TASK-006).

跑法: python3 aria/skills/session-closer/tests/test_closeout_trigger.py
  或: cd aria/skills/session-closer && python3 -m unittest discover tests
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from closeout_trigger import (  # noqa: E402
    DEFAULT_THRESHOLD,
    evaluate_closeout_trigger,
    occupancy_from_telemetry,
)


def relay(pct):
    return {"source": "relay_cache", "confidence": "high",
            "used_percentage": pct, "used_percentage_proxy": None}


def transcript(proxy_pct):
    return {"source": "transcript_fallback", "confidence": "estimate",
            "used_percentage": None, "used_percentage_proxy": proxy_pct}


UNAVAILABLE = {"source": "unavailable", "used_percentage": None,
               "used_percentage_proxy": None}


class TestAC6Branches(unittest.TestCase):
    # 档 1: relay 90% + uncommitted → nudge
    def test_relay_high_with_uncommitted_nudges(self):
        v = evaluate_closeout_trigger(relay(90), {"uncommitted": True})
        self.assertTrue(v["should_nudge"])
        self.assertEqual(v["reason"], "context_pressure_with_unshipped")

    # 档 2: relay 50% → 静默 (低于阈值)
    def test_relay_low_silent(self):
        v = evaluate_closeout_trigger(relay(50), {"uncommitted": True})
        self.assertFalse(v["should_nudge"])
        self.assertEqual(v["reason"], "occupancy_below_threshold")

    # 档 3: relay 90% 但无未交接 → 静默
    def test_relay_high_no_unshipped_silent(self):
        v = evaluate_closeout_trigger(relay(90), {})
        self.assertFalse(v["should_nudge"])
        self.assertEqual(v["reason"], "no_unshipped_work")

    # 档 4: 第三信号 (新 memory 未入 §8) 独立触发 — uncommitted=0 + followups=[]
    def test_third_signal_memory_independent_nudges(self):
        v = evaluate_closeout_trigger(
            relay(90),
            {"uncommitted": False, "followups_nonempty": False,
             "new_memory_unrecorded": True},
        )
        self.assertTrue(v["should_nudge"])

    # 档 5: source=unavailable → 静默, 不报错
    def test_unavailable_silent_no_error(self):
        v = evaluate_closeout_trigger(UNAVAILABLE, {"uncommitted": True})
        self.assertFalse(v["should_nudge"])
        self.assertIsNone(v["occupancy"])
        self.assertEqual(v["reason"], "occupancy_unavailable")


class TestSourceFieldNoMixing(unittest.TestCase):
    """口径不混用: relay 只读 used_percentage, transcript 只读 used_percentage_proxy。"""

    def test_relay_reads_used_percentage_not_proxy(self):
        occ, src = occupancy_from_telemetry(relay(77))
        self.assertEqual(occ, 77)
        self.assertEqual(src, "relay_cache")

    def test_transcript_reads_proxy_not_used_percentage(self):
        # used_percentage=None, used_percentage_proxy=88 → 必读 proxy=88, 不读 None
        occ, src = occupancy_from_telemetry(transcript(88))
        self.assertEqual(occ, 88)
        self.assertEqual(src, "transcript_fallback")

    def test_transcript_high_proxy_nudges_via_proxy(self):
        # 若误读 used_percentage(None) 会 occupancy=None → 静默; 正确读 proxy=90 → nudge
        v = evaluate_closeout_trigger(transcript(90), {"uncommitted": True})
        self.assertTrue(v["should_nudge"])
        self.assertEqual(v["occupancy"], 90)


class TestRelayCacheSchemaContract(unittest.TestCase):
    """I-1 (code-review): 契约锁定 — relay cache 原始 schema (无 source) 不可当 telemetry 输出喂。

    closeout_trigger 期望 token_telemetry.py 输出 (含 source); 误喂 relay cache (无 source)
    → 落 unavailable → 恒不 nudge。本测试断言该误用被安全降级 (静默, 非崩溃)。
    """

    def test_relay_cache_without_source_falls_unavailable(self):
        # relay cache 原始形态 (无 source 字段, 仅 used_percentage)
        relay_cache_raw = {"used_percentage": 90, "captured_at": "2026-06-25"}
        occ, src = occupancy_from_telemetry(relay_cache_raw)
        self.assertIsNone(occ)        # 无 source → 不读 used_percentage
        self.assertIsNone(src)
        v = evaluate_closeout_trigger(relay_cache_raw, {"uncommitted": True})
        self.assertFalse(v["should_nudge"])   # 恒不 nudge (证明须喂 token_telemetry 输出)
        self.assertEqual(v["reason"], "occupancy_unavailable")


class TestThresholdBoundary(unittest.TestCase):
    def test_exactly_threshold_nudges(self):
        v = evaluate_closeout_trigger(relay(DEFAULT_THRESHOLD), {"uncommitted": True})
        self.assertTrue(v["should_nudge"])  # >= threshold

    def test_just_below_threshold_silent(self):
        v = evaluate_closeout_trigger(relay(DEFAULT_THRESHOLD - 1), {"uncommitted": True})
        self.assertFalse(v["should_nudge"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

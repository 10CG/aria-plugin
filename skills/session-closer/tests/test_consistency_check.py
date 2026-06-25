"""consistency_check 单测 — 覆盖 proposal AC-4 (4 类各独立 fixture + advisory exit 0)
+ R1 C-1 字段修正的真 snapshot 集成测试 (堵手造 fixture 假绿).

跑法: python3 aria/skills/session-closer/tests/test_consistency_check.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

_SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
sys.path.insert(0, _SCRIPTS)

from consistency_check import check_consistency, data_from_snapshot  # noqa: E402

_SCRIPT_PATH = os.path.join(_SCRIPTS, "consistency_check.py")
# 真 snapshot (项目根 .aria/state-snapshot.json), 用于 adapter 集成测试 (R1 C-1)
_REAL_SNAPSHOT = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..",
                              ".aria", "state-snapshot.json")


# --- 4 类 committed fixture (每类只注入自己那类不一致) ------------------------

FIX_CLASS1 = {"upm_cycle": 9, "latest_archive_cycle": 8}          # cycle mismatch
FIX_CLASS2 = {"active_change_ids": ["spec-x"], "upm_in_progress_ids": []}  # active 未入 UPM
FIX_CLASS3 = {"high_priority_unfinished_us": ["US-007"], "carry_forward_us": []}  # 未 carry
FIX_CLASS4 = {"prd_referenced_us": ["US-099"], "known_us_ids": ["US-001"]}  # broken ref

FIX_CLEAN = {
    "upm_cycle": 8, "latest_archive_cycle": 8,
    "active_change_ids": ["spec-x"], "upm_in_progress_ids": ["spec-x"],
    "high_priority_unfinished_us": ["US-007"], "carry_forward_us": ["US-007"],
    "prd_referenced_us": ["US-001"], "known_us_ids": ["US-001"],
}


class TestFourClasses(unittest.TestCase):
    def test_class1_cycle_mismatch(self):
        f = check_consistency(FIX_CLASS1)
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["dimension"], "upm_vs_archive")
        self.assertEqual(f[0]["kind"], "cycle_mismatch")

    def test_class2_active_change_not_in_upm(self):
        f = check_consistency(FIX_CLASS2)
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["dimension"], "openspec_vs_upm")

    def test_class3_unfinished_us_not_carried(self):
        f = check_consistency(FIX_CLASS3)
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["dimension"], "requirements_vs_handoff")

    def test_class4_broken_us_ref(self):
        f = check_consistency(FIX_CLASS4)
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["dimension"], "prd_vs_requirements")

    def test_clean_no_flags(self):
        self.assertEqual(check_consistency(FIX_CLEAN), [])

    def test_combined_all_four(self):
        combined = {**FIX_CLASS1, **FIX_CLASS2, **FIX_CLASS3, **FIX_CLASS4}
        dims = {fl["dimension"] for fl in check_consistency(combined)}
        self.assertEqual(dims, {"upm_vs_archive", "openspec_vs_upm",
                                "requirements_vs_handoff", "prd_vs_requirements"})

    def test_all_advisory_severity(self):
        for fix in (FIX_CLASS1, FIX_CLASS2, FIX_CLASS3, FIX_CLASS4):
            for fl in check_consistency(fix):
                self.assertEqual(fl["severity"], "advisory")


class TestMissingDataNoCrash(unittest.TestCase):
    def test_empty_no_crash(self):
        self.assertEqual(check_consistency({}), [])
        self.assertEqual(check_consistency(None), [])

    def test_partial_fields_skip(self):
        # 只有 upm_cycle 无 archive cycle → 类1 跳过(不报错)
        self.assertEqual(check_consistency({"upm_cycle": 9}), [])


class TestSnapshotAdapter(unittest.TestCase):
    """R1 C-1: 字段路径修正 (changes 非 active_changes / current_cycle 非 cycle_number)。"""

    def test_data_from_snapshot_extracts(self):
        snap = {
            # R1 C-1: 真 schema 字段名 current_cycle / changes
            "upm": {"current_cycle": 9, "in_progress_change_ids": []},
            "openspec": {"changes": {"items": [{"id": "spec-x"}]}},
            "requirements": {"stories": {"items": [
                {"id": "US-007", "status": "in_progress", "priority": "P1"},
                {"id": "US-001", "status": "done", "priority": "P2"},
            ]}},
        }
        d = data_from_snapshot(snap, latest_archive_cycle=8, carry_forward_us=[])
        self.assertEqual(d["upm_cycle"], 9)
        self.assertIn("spec-x", d["active_change_ids"])
        self.assertIn("US-007", d["high_priority_unfinished_us"])
        self.assertNotIn("US-001", d["high_priority_unfinished_us"])  # done, 不算未完成
        # 跑校验: cycle 9!=8 + active 未入 + US-007 未 carry → 3 flags
        self.assertEqual(len(check_consistency(d)), 3)

    def test_old_field_names_yield_empty(self):
        # 回归守卫 (R1 C-1): 用旧 (错) 字段名 → adapter 提取不到 → 证明修正生效
        old_schema = {
            "upm": {"cycle_number": 9},
            "openspec": {"active_changes": {"items": [{"id": "spec-x"}]}},
        }
        d = data_from_snapshot(old_schema)
        self.assertIsNone(d["upm_cycle"])           # cycle_number 不再被读
        self.assertEqual(d["active_change_ids"], [])  # active_changes 不再被读


class TestRealSnapshotAdapter(unittest.TestCase):
    """真 snapshot 集成测试 (R1 C-1): 把 falsify 边界从手造 fixture 推到真 adapter。"""

    @unittest.skipUnless(os.path.isfile(_REAL_SNAPSHOT), "真 snapshot 不存在 (非 Aria 仓库)")
    def test_real_snapshot_extracts_changes_not_empty(self):
        with open(_REAL_SNAPSHOT, encoding="utf-8") as f:
            snap = json.load(f)
        d = data_from_snapshot(snap)
        # Aria 当前有 active changes (M6/M7 + 本 cycle) → changes 提取非空 (字段修正后)
        self.assertGreater(len(d["active_change_ids"]), 0,
                           "openspec.changes 提取应非空 — 若空说明字段路径漂移回退")
        # upm_cycle 读 current_cycle (Aria 自身 UPM 可能 None, 但不应 KeyError)
        self.assertIn("upm_cycle", d)


class TestAdvisoryExitZero(unittest.TestCase):
    """advisory: 即使有 flag, CLI 也 exit 0 (非阻塞)。"""

    def test_cli_exit_zero_with_flags(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tf:
            json.dump(FIX_CLASS1, tf)
            path = tf.name
        try:
            r = subprocess.run(
                [sys.executable, _SCRIPT_PATH, "--data-json", path],
                capture_output=True, text=True, timeout=15,
            )
            self.assertEqual(r.returncode, 0, msg=r.stderr)  # advisory 非阻塞
            out = json.loads(r.stdout)
            self.assertEqual(out["count"], 1)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)

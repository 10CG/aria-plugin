"""handoff_autofill 单测 — AC-2(§7 + ahead 告警)/ AC-3(§2)/ AC-3b(机械补漏)/
AC-5(§8)/ §5 四维 + R1 C-2/M-1 字段修正 & adapter 重建 & 真 snapshot 集成.

跑法: python3 aria/skills/session-closer/tests/test_handoff_autofill.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from handoff_autofill import (  # noqa: E402
    assemble_from_snapshot,
    assemble_unfinished,
    carry_forward_from_inventory,
    cross_check_unfilled,
    enumerate_new_memory,
    fill_sync_section,
    four_dim_status,
    grep_unchecked_tasks,
)

_REAL_SNAPSHOT = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..",
                              ".aria", "state-snapshot.json")


def _repo(label_branch, head, *remotes):
    return {"branch": label_branch, "local_head": head, "remotes": list(remotes)}


def _rem(name, parity, ahead=0, reachable=True):
    return {"name": name, "parity": parity, "ahead_count": ahead, "reachable": reachable}


class TestSyncSectionAC2(unittest.TestCase):
    def test_in_sync_no_warning(self):
        mr = {"main_repo": _repo("master", "abc1234", _rem("origin", "equal"), _rem("github", "equal"))}
        r = fill_sync_section(mr)
        self.assertEqual(len(r["lines"]), 1)
        self.assertIn("abc1234", r["lines"][0])
        self.assertEqual(r["warnings"], [])

    def test_ahead_produces_warning(self):
        # AC-2: 本地 ahead origin 1 → 告警行
        mr = {"main_repo": _repo("master", "deadbee", _rem("origin", "ahead", ahead=1))}
        r = fill_sync_section(mr)
        self.assertTrue(any("ahead 1" in w for w in r["warnings"]))

    def test_submodule_included(self):
        mr = {
            "main_repo": _repo("master", "aaa1111", _rem("origin", "equal")),
            "submodules": [{"path": "aria", "branch": "master", "local_head": "bbb2222",
                            "remotes": [_rem("origin", "equal")]}],
        }
        r = fill_sync_section(mr)
        self.assertEqual(len(r["lines"]), 2)
        self.assertTrue(any("aria" in ln for ln in r["lines"]))

    def test_unreachable_remote_warns(self):
        mr = {"main_repo": _repo("master", "ccc3333", _rem("origin", "unknown", reachable=False))}
        r = fill_sync_section(mr)
        self.assertTrue(any("不可达" in w for w in r["warnings"]))

    def test_empty_no_crash(self):
        self.assertEqual(fill_sync_section(None), {"lines": [], "warnings": []})


class TestAssembleUnfinishedAC3(unittest.TestCase):
    def test_all_mechanical_sources(self):
        out = assemble_unfinished(
            followups=["fu1", "fu2"],
            carry_forward=["cf1"],
            unchecked_tasks=[{"source": "tasks.md:spec-x", "item": "t1"}],
            subagent_pending=["TASK-003"],
        )
        srcs = [o["source"] for o in out]
        self.assertEqual(len(out), 5)
        self.assertIn("upm.followups", srcs)
        self.assertIn("openspec.carry_forward_inventory", srcs)
        self.assertTrue(any(s.startswith("tasks.md") for s in srcs))
        self.assertIn("subagent-state", srcs)

    def test_followup_dict_normalized(self):
        # R1 M-1: followup 是 dict (FollowupRow) → 归一化为可读, 不渲染成 "{'..': ..}"
        out = assemble_unfinished(followups=[{"item": "补 X 测试", "owner": "me"}])
        self.assertEqual(out[0]["item"], "补 X 测试")

    def test_grep_unchecked_tasks(self):
        with tempfile.TemporaryDirectory() as d:
            sp = os.path.join(d, "spec-x")
            os.makedirs(sp)
            with open(os.path.join(sp, "tasks.md"), "w", encoding="utf-8") as f:
                f.write("# T\n- [ ] 未完成甲\n- [x] 已完成\n- [ ] 未完成乙\n")
            items = grep_unchecked_tasks(d)
            self.assertEqual(len(items), 2)
            self.assertEqual(items[0]["item"], "未完成甲")

    def test_grep_missing_dir_no_crash(self):
        self.assertEqual(grep_unchecked_tasks("/nonexistent/xyz"), [])


class TestCarryForwardInventory(unittest.TestCase):
    """R1 M-1: carry_forward_inventory 是 dict 非 list → 从 by_change 提取。"""

    def test_dict_by_change_list_values(self):
        inv = {"total": 2, "active_change_count": 1,
               "by_change": {"spec-x": ["carry A", "carry B"]}}
        out = carry_forward_from_inventory(inv)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0], {"change": "spec-x", "item": "carry A"})

    def test_real_collector_count_samples_shape(self):
        # I-2 (code-review): 真 collector by_change 形态 {cid: {count, samples}}
        inv = {"total": 2, "active_change_count": 1,
               "by_change": {"spec-x": {"count": 2, "samples": ["carry A text", "carry B text"]}}}
        out = carry_forward_from_inventory(inv)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0], {"change": "spec-x", "item": "carry A text"})
        # 不得产 "count=...; samples=[...]" 垃圾
        self.assertFalse(any("count=" in o["item"] for o in out))

    def test_count_no_samples_fallback(self):
        inv = {"by_change": {"spec-z": {"count": 3, "samples": []}}}
        out = carry_forward_from_inventory(inv)
        self.assertEqual(len(out), 1)
        self.assertIn("3 项", out[0]["item"])

    def test_dict_by_change_scalar_value(self):
        inv = {"by_change": {"spec-y": "single carry"}}
        out = carry_forward_from_inventory(inv)
        self.assertEqual(out, [{"change": "spec-y", "item": "single carry"}])

    def test_empty_inventory_no_crash(self):
        self.assertEqual(carry_forward_from_inventory(None), [])
        self.assertEqual(carry_forward_from_inventory({"by_change": {}}), [])

    def test_not_dict_raw_passed_as_list_no_crash(self):
        # 防御: 即便 by_change 误传 dict 整体, 直接遍历不再产 dict-keys 垃圾
        inv = {"by_change": ["loose1", "loose2"]}
        out = carry_forward_from_inventory(inv)
        self.assertEqual([o["item"] for o in out], ["loose1", "loose2"])


class TestCrossCheckUnfilledAC3b(unittest.TestCase):
    """AC-3b 机械补漏: 静态输入对 (snapshot 有 X + AI 草稿不含 X → flag X)。"""

    def test_snapshot_item_omitted_by_ai_flagged(self):
        mechanical = [{"source": "upm.followups", "item": "补 X 测试"},
                      {"source": "upm.followups", "item": "更新 Y 文档"}]
        ai_mentioned = ["更新 Y 文档"]   # AI 内省漏了 "补 X 测试"
        missed = cross_check_unfilled(ai_mentioned, mechanical)
        self.assertEqual(len(missed), 1)
        self.assertEqual(missed[0]["item"], "补 X 测试")
        self.assertTrue(missed[0]["omitted_by_ai"])

    def test_all_mentioned_no_miss(self):
        mechanical = [{"item": "a"}, {"item": "b"}]
        self.assertEqual(cross_check_unfilled(["a", "b"], mechanical), [])

    def test_whitespace_case_insensitive_match(self):
        mechanical = [{"item": "  补 X 测试 "}]
        self.assertEqual(cross_check_unfilled(["补 x 测试"], mechanical), [])

    def test_empty_ai_flags_all(self):
        mechanical = [{"item": "a"}, {"item": "b"}]
        self.assertEqual(len(cross_check_unfilled([], mechanical)), 2)


class TestEnumerateMemoryAC5(unittest.TestCase):
    def test_mtime_fixed_timestamps(self):
        with tempfile.TemporaryDirectory() as d:
            started_at = 1_000_000_000  # 固定基准 (R1 fix QA-minor6 防 flaky)
            for name in ("feedback_a.md", "project_b.md"):
                p = os.path.join(d, name)
                open(p, "w").close()
                os.utime(p, (started_at + 100, started_at + 100))
            old = os.path.join(d, "old.md")
            open(old, "w").close()
            os.utime(old, (started_at - 100, started_at - 100))
            idx = os.path.join(d, "MEMORY.md")
            open(idx, "w").close()
            os.utime(idx, (started_at + 100, started_at + 100))

            new = enumerate_new_memory(d, started_at)
            self.assertEqual(set(new), {"feedback_a.md", "project_b.md"})

    def test_missing_dir_no_crash(self):
        self.assertEqual(enumerate_new_memory("/nonexistent", 1), [])
        self.assertEqual(enumerate_new_memory(".", None), [])


class TestFourDimStatus(unittest.TestCase):
    def test_extracts_four_dims(self):
        # R1 C-2: 真 schema 字段 current_cycle / changes
        snap = {
            "upm": {"current_cycle": 9},
            "openspec": {"changes": {"total": 4}, "pending_archive": []},
            "requirements": {"stories": {"total": 19, "by_status": {"done": 16}}},
        }
        s = four_dim_status(snap, prd_exists=True)
        self.assertEqual(s["UPM"]["cycle"], 9)
        self.assertEqual(s["OpenSpec"]["active_changes"], 4)
        self.assertEqual(s["UserStory"]["total"], 19)
        self.assertTrue(s["PRD"]["present"])

    def test_old_field_names_yield_none(self):
        # 回归守卫 (R1 C-2): 旧字段名 → 提取不到 → 证明修正生效
        snap = {"upm": {"cycle_number": 9}, "openspec": {"active_changes": {"total": 4}}}
        s = four_dim_status(snap)
        self.assertIsNone(s["UPM"]["cycle"])
        self.assertIsNone(s["OpenSpec"]["active_changes"])


class TestAssembleFromSnapshot(unittest.TestCase):
    """R1 M-1: 重建的 adapter 层 — sync_status.multi_remote 嵌套路径 + dict carry_forward。"""

    def test_adapter_nested_multi_remote_and_dict_carry(self):
        snap = {
            "sync_status": {"multi_remote": {
                "main_repo": _repo("master", "abc1234", _rem("origin", "ahead", ahead=2))}},
            "upm": {"followups": [{"item": "fu A"}]},
            "openspec": {"carry_forward_inventory": {"by_change": {"spec-x": ["cf A"]}}},
        }
        out = assemble_from_snapshot(snap)
        # §7 从嵌套 sync_status.multi_remote 取到 ahead 告警
        self.assertTrue(any("ahead 2" in w for w in out["sync"]["warnings"]))
        items = [u["item"] for u in out["unfinished"]]
        self.assertIn("fu A", items)
        self.assertIn("spec-x: cf A", items)


class TestRealSnapshotAdapter(unittest.TestCase):
    """真 snapshot 集成 (R1 M-1/C-2): falsify 边界推到真 adapter, 堵手造 fixture 假绿。"""

    @unittest.skipUnless(os.path.isfile(_REAL_SNAPSHOT), "真 snapshot 不存在 (非 Aria 仓库)")
    def test_real_snapshot_assemble_no_crash_and_fields(self):
        with open(_REAL_SNAPSHOT, encoding="utf-8") as f:
            snap = json.load(f)
        out = assemble_from_snapshot(snap)
        # §7: Aria 当前 clean+parity → 至少 main 一行, 无 KeyError
        self.assertTrue(len(out["sync"]["lines"]) >= 1)
        # §5: openspec.changes.total 非 None (字段修正后真 snapshot 有 active changes)
        self.assertIsNotNone(out["four_dim"]["OpenSpec"]["active_changes"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

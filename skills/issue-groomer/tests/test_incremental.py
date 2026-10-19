"""Tests for lib/incremental.py — issue-groomer 增量状态与复用引擎 (TASK-005, 裁定④).

Covers the TASK-005 verification bullets:
  1. Tier A 复用 = 分类输出 + 判据输入快照; **时间敏感字段跨档触发重分类**
     (即使 issue_key 未变 — 纯时钟流逝场景) (TierAPlanTests)。
  2. Tier B provenance 门: provenance 变 ⇒ stale-assessment; 完整拼接串
     (harness + model_id) 比对; 条目/文档两级 fail-closed 方向
     (TierBGateTests)。
  3. 裁定④ 判定形态: 引擎全程不写 groom-assessments.json — 重写 state 多轮
     后该文件**字节不变**; save_state 结构上不触 assessments reader
     (AssessmentsUntouchedInvariantTests)。
  4. groom-state.json 单一固定路径原子写 (temp+rename), rename 崩溃模拟
     不留半文件 (AtomicWriteTests)。
  5. diff 基元 (TASK-006 消费): 集合差精确 + baseline (DiffTests)。
  6. groom-assessments.json 键结构契约 (本任务拥有, TASK-010 消费):
     ASSESSMENTS_SCHEMA_DOC + 机读常量 (ContractConstantsTests)。

fixture 形态锚点 (裁定-7 防形态脱节):
  - issue 行 = TASK-001 fetch 归一形态超集; comment 行逐字取自真语料
    scratchpad/issues-sample-body-comments-2026-10-18.json (Aria#233
    comment id=28794) — 与 test_fingerprint.py 同锚。
  - provenance {harness: "claude-code", model_id: "glm-5.2"} 对齐本仓
    Layer 2 主力 LLM 实况 (GLM via Luxeno)。
  - taxonomy 用注入 dict (过 tier_a SC-9), 不读盘 — 测试零真盘依赖。
时钟全注入 (FixedClock): staleness 跨档用 updated=2026-10-01 +
now 2026-10-05 (age 4d, "<7d") → 2026-10-10 (age 9d, "7-30d")。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

# Add scripts/ to path for direct module import (house convention).
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "scripts"))

from lib import fingerprint, incremental, tier_a  # noqa: E402


# ------------------------------------------------------------- 语料真形态 anchors

# 逐字取自 scratchpad/issues-sample-body-comments-2026-10-18.json (Aria#233)。
CORPUS_COMMENT_ARIA233 = {
    "id": 28794,
    "created_at": "2026-10-15T16:58:30Z",
    "updated_at": "2026-10-15T16:58:30Z",
    "body": "…(语料 body_len=9033, 此处取形态不取全文)…",
}

# 注入 taxonomy (过 tier_a SC-9; 不读盘 — 与 test_fingerprint 同判)。
TAXONOMY_V1 = {
    "version": 1,
    "categories": {"bug": "kind/bug", "feature": "kind/feature"},
    "title_prefixes": {"[缺陷]": "bug", "[feature]": "feature"},
    "label_signals": {"kind/bug": "bug", "kind/feature": "feature"},
}
TAXONOMY_V2 = {  # 规则升级形态: 新增分类 ⇒ taxonomy_hash 变
    "version": 1,
    "categories": {"bug": "kind/bug", "feature": "kind/feature", "docs": "kind/docs"},
    "title_prefixes": {"[缺陷]": "bug", "[feature]": "feature", "[docs]": "docs"},
    "label_signals": {"kind/bug": "bug", "kind/feature": "feature", "kind/docs": "docs"},
}
TAX_HASH_V1 = tier_a.taxonomy_hash(TAXONOMY_V1)
TAX_HASH_V2 = tier_a.taxonomy_hash(TAXONOMY_V2)

PROVENANCE = {"harness": "claude-code", "model_id": "glm-5.2"}
PROV_KEY = fingerprint.combined_provenance_key(PROVENANCE)

CTX_FP = {  # TASK-004 上下文面四分量形态 (内容任意, build 原样保存)
    "openspec_changes_hash": "0f" * 32,
    "git_heads": {"/home/dev/Aria": "ab" * 20},
    "handoff_pointer": "2026-10-18-235-cycle-done.md",
    "taxonomy_hash": TAX_HASH_V1,
}

# 时钟锚点 (staleness 跨档: updated=2026-10-01 ⇒ age 4d / 9d)
NOW_ROUND1 = datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc)    # "<7d"
NOW_ROUND2 = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)   # "7-30d"
NOW_TTL = datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)      # ttl 判定锚


def _issue(**overrides):
    """fetch 层归一形态基线行 (超集; 显式排除字段默认缺席)。"""
    base = {
        "repo": "Aria",
        "number": 233,
        "title": "[缺陷][示例] incremental 基线",
        "labels": ["kind/bug"],
        "created": "2026-09-01",
        "updated": "2026-10-01",
        "comments_count": 1,
        "body": "body v1",
        "comments": [dict(CORPUS_COMMENT_ARIA233)],
        "comments_error": None,
    }
    base.update(overrides)
    return base


def _faces(issues):
    return fingerprint.fingerprint_issues(issues)


def _classified(issues, now, taxonomy=TAXONOMY_V1):
    return tier_a.classify(list(issues), taxonomy, now)


def _assessment_entry(harness="claude-code", model_id="glm-5.2",
                      created_at="2026-10-18T08:30:00Z", **extra):
    entry = {
        "verdict_priorities": [{"from": "P2", "to": "P3", "rationale": "…"}],
        "suspected_fixed": {"verdict": False, "rationale": "…"},
        "provenance": {"harness": harness, "model_id": model_id},
        "created_at": created_at,
    }
    entry.update(extra)
    return entry


def _assessments_doc(entries):
    return {"schema_version": 1, "assessments": dict(entries)}


def _tmp_engine(doc_reader=None, now=None, rename_fn=None, state_name="groom-state.json"):
    """(tempdir, state_path, engine) — 每测试独立 tempdir, addCleanup 收尾。"""
    tmp = tempfile.TemporaryDirectory()
    state_path = Path(tmp.name) / ".aria" / "cache" / state_name
    engine = incremental.IncrementalEngine(
        state_path,
        assessments_reader=doc_reader,
        now_fn=now or (lambda: NOW_ROUND1),
        rename_fn=rename_fn,
    )
    return tmp, state_path, engine


# ------------------------------------------------------------------ 契约常量

class ContractConstantsTests(unittest.TestCase):
    """groom-assessments.json 契约 (TASK-005 拥有, TASK-010 消费) 的机读锚点。"""

    def test_schema_doc_covers_all_contract_keys(self):
        doc = incremental.ASSESSMENTS_SCHEMA_DOC
        for key in ("schema_version", "assessments", "verdict_priorities",
                    "suspected_fixed", "owner_decisions", "provenance",
                    "model_id", "created_at", "harness"):
            self.assertIn(key, doc, f"contract doc must document key {key!r}")
        # 反事实: 契约文本漏任一键 ⇒ TASK-010 手抄即漂移。

    def test_schema_doc_pins_ruling4_and_additive_only(self):
        doc = incremental.ASSESSMENTS_SCHEMA_DOC
        self.assertIn("additive-only", doc)
        self.assertIn("不写", doc)  # groom.py 全程不写该文件 (裁定④)
        self.assertIn(".aria/groom-assessments.json", doc)  # 落点钉死

    def test_machine_readable_constants_match_doc(self):
        self.assertEqual(incremental.ASSESSMENTS_ROOT_REQUIRED_KEYS, ("schema_version", "assessments"))
        self.assertEqual(incremental.ASSESSMENTS_ENTRY_REQUIRED_KEYS, ("provenance", "created_at"))
        self.assertEqual(
            sorted(incremental.ASSESSMENTS_ENTRY_OPTIONAL_KEYS),
            ["owner_decisions", "suspected_fixed", "verdict_priorities"],
        )
        self.assertEqual(incremental.ASSESSMENTS_PROVENANCE_KEYS, ("harness", "model_id"))
        self.assertEqual(incremental.STATE_SCHEMA_VERSION, 1)
        self.assertEqual(incremental.ASSESSMENTS_SCHEMA_VERSION, 1)


# ------------------------------------------------------------- 判据输入快照

class JudgementInputsTests(unittest.TestCase):

    def test_inputs_extracted_from_classified_record(self):
        rec = _classified([_issue()], NOW_ROUND1)[0]
        inputs = incremental.judgement_inputs_from(rec, TAX_HASH_V1)
        self.assertEqual(inputs, {
            "staleness_tier": "<7d",      # updated=2026-10-01, now=10-05 ⇒ age 4d
            "activity_tier": "1-2",       # comments_count=1
            "taxonomy_hash": TAX_HASH_V1,
        })

    def test_absent_fields_yield_none_not_guessed_tier(self):
        issue = _issue()
        del issue["updated"]       # 无 staleness 信号
        del issue["comments_count"]  # 无 activity 信号
        rec = _classified([issue], NOW_ROUND1)[0]
        inputs = incremental.judgement_inputs_from(rec, TAX_HASH_V1)
        self.assertIsNone(inputs["staleness_tier"])  # 缺席 ≠ "0" 档, 不猜
        self.assertIsNone(inputs["activity_tier"])

    def test_shape_is_exactly_three_fields(self):
        rec = _classified([_issue()], NOW_ROUND1)[0]
        inputs = incremental.judgement_inputs_from(rec, TAX_HASH_V1)
        self.assertEqual(
            sorted(inputs),
            ["activity_tier", "staleness_tier", "taxonomy_hash"],
        )


# ------------------------------------------------------------------ state 载入

class StateLoadTests(unittest.TestCase):

    def test_missing_state_is_baseline(self):
        tmp, state_path, engine = _tmp_engine()
        with tmp:
            state, baseline = engine.load_state()
            self.assertEqual(state, {})
            self.assertTrue(baseline)

    def test_saved_state_round_trips(self):
        tmp, state_path, engine = _tmp_engine()
        with tmp:
            state = engine.build_next_state(
                {}, {"reused": [], "new": ["Aria#233"], "closed": [], "reclassify": ["Aria#233"]},
                _faces([_issue()]), _classified([_issue()], NOW_ROUND1), TAX_HASH_V1,
                CTX_FP, PROVENANCE,
            )
            engine.save_state(state)
            loaded, baseline = engine.load_state()
            self.assertFalse(baseline)
            self.assertEqual(loaded, state)  # JSON 往返无损

    def _write_and_load(self, text):
        tmp, state_path, engine = _tmp_engine()
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(text, encoding="utf-8")
        return tmp, engine

    def test_corrupt_json_raises(self):
        tmp, engine = self._write_and_load("{not json")
        with tmp:
            with self.assertRaises(ValueError):
                engine.load_state()

    def test_root_not_object_raises(self):
        tmp, engine = self._write_and_load("[1, 2]")
        with tmp:
            with self.assertRaises(ValueError):
                engine.load_state()

    def test_wrong_schema_version_raises(self):
        tmp, engine = self._write_and_load(json.dumps({"schema_version": 2, "issues": {}}))
        with tmp:
            with self.assertRaises(ValueError):
                engine.load_state()

    def test_boolean_schema_version_raises(self):
        # JSON true == 1 (Python) — 无 isinstance(bool) 守卫会静默当 v1 放行。
        tmp, engine = self._write_and_load(json.dumps({"schema_version": True, "issues": {}}))
        with tmp:
            with self.assertRaises(ValueError):
                engine.load_state()

    def test_issues_not_object_raises(self):
        tmp, engine = self._write_and_load(json.dumps({"schema_version": 1, "issues": []}))
        with tmp:
            with self.assertRaises(ValueError):
                engine.load_state()

    def test_last_run_not_object_raises(self):
        tmp, engine = self._write_and_load(json.dumps({"schema_version": 1, "last_run": 3}))
        with tmp:
            with self.assertRaises(ValueError):
                engine.load_state()


# ----------------------------------------------------------- diff 基元 (TASK-006)

class DiffTests(unittest.TestCase):

    def test_set_difference_exact(self):
        result = incremental.compute_diff(["Aria#1", "Aria#2", "Aria#3"], ["Aria#2", "SilkNode#9"])
        self.assertEqual(result["new"], ["SilkNode#9"])
        self.assertEqual(result["closed"], ["Aria#1", "Aria#3"])  # 排序输出
        self.assertFalse(result["baseline"])

    def test_identical_sets_empty_diff(self):
        result = incremental.compute_diff(["Aria#1", "Aria#2"], ["Aria#2", "Aria#1"])
        self.assertEqual(result["new"], [])
        self.assertEqual(result["closed"], [])

    def test_disjoint_sets_full_swap(self):
        result = incremental.compute_diff(["A#1"], ["B#1"])
        self.assertEqual(result["new"], ["B#1"])
        self.assertEqual(result["closed"], ["A#1"])

    def test_empty_prev_is_baseline_and_dedups_input(self):
        result = incremental.compute_diff([], ["A#1", "A#1", "B#2"])
        self.assertEqual(result["new"], ["A#1", "B#2"])  # 重复键去重 (集合语义)
        self.assertEqual(result["closed"], [])
        self.assertTrue(result["baseline"])


# ------------------------------------------------------------- Tier A 复用计划

class TierAPlanTests(unittest.TestCase):
    """复用门: issue_key 未变 且 判据输入快照未变 ⇒ 复用; 任一变 ⇒ 重分类。"""

    @staticmethod
    def _saved_round(engine, issues, now, taxonomy=TAXONOMY_V1):
        """一轮完整流: 载入 → plan → build → save; 返回 (plan, next_state, loaded)。"""
        state, _ = engine.load_state()
        faces = _faces(issues)
        classified = _classified(issues, now, taxonomy)
        tax_hash = tier_a.taxonomy_hash(taxonomy)
        plan = engine.plan_tier_a(state, faces, classified, tax_hash)
        nxt = engine.build_next_state(state, plan, faces, classified, tax_hash, CTX_FP, PROVENANCE)
        engine.save_state(nxt)
        return plan, nxt

    def test_unchanged_key_and_inputs_reuse(self):
        tmp, state_path, engine = _tmp_engine(now=lambda: NOW_ROUND1)
        with tmp:
            self._saved_round(engine, [_issue()], NOW_ROUND1)
            state, baseline = engine.load_state()
            self.assertFalse(baseline)
            plan = engine.plan_tier_a(state, _faces([_issue()]), _classified([_issue()], NOW_ROUND1), TAX_HASH_V1)
            self.assertEqual(plan["reused"], ["Aria#233"])
            self.assertEqual(plan["reclassify"], [])
            self.assertEqual(plan["new"], [])
            self.assertEqual(plan["closed"], [])
            self.assertFalse(plan["baseline_run"])

    def test_staleness_cross_tier_reclassifies_despite_unchanged_issue_key(self):
        # 纯时钟流逝: issue 一个字节没变 ⇒ issue_key 不变; staleness <7d → 7-30d。
        tmp, state_path, engine = _tmp_engine(now=lambda: NOW_ROUND1)
        with tmp:
            self._saved_round(engine, [_issue()], NOW_ROUND1)
            state, _ = engine.load_state()
            faces = _faces([_issue()])
            self.assertEqual(  # 前提钉死: 跨档场景下 issue_key 确实未变
                state["issues"]["Aria#233"]["issue_key"],
                fingerprint.combined_issue_key(faces["Aria#233"]),
            )
            plan = engine.plan_tier_a(state, faces, _classified([_issue()], NOW_ROUND2), TAX_HASH_V1)
            self.assertEqual(plan["reused"], [])
            self.assertEqual(plan["reclassify"], ["Aria#233"])

    def test_staleness_same_tier_reuses(self):
        # 对照: 时钟流逝但未跨档 (4d → 6d, 都 <7d) ⇒ 快照不变 ⇒ 复用。
        now_r2 = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)  # age 6d
        tmp, state_path, engine = _tmp_engine(now=lambda: NOW_ROUND1)
        with tmp:
            self._saved_round(engine, [_issue()], NOW_ROUND1)
            state, _ = engine.load_state()
            plan = engine.plan_tier_a(state, _faces([_issue()]), _classified([_issue()], now_r2), TAX_HASH_V1)
            self.assertEqual(plan["reused"], ["Aria#233"])

    def test_activity_cross_tier_reclassifies(self):
        # comments_count 1 → 5 ("1-2" → "3-9"); comments 列表不动 ⇒ face 不变。
        tmp, state_path, engine = _tmp_engine(now=lambda: NOW_ROUND1)
        with tmp:
            self._saved_round(engine, [_issue()], NOW_ROUND1)
            state, _ = engine.load_state()
            changed = _issue(comments_count=5)
            self.assertEqual(  # 前提钉死: activity 轴独立触发 (issue_key 未变)
                state["issues"]["Aria#233"]["issue_key"],
                fingerprint.combined_issue_key(_faces([changed])["Aria#233"]),
            )
            plan = engine.plan_tier_a(state, _faces([changed]), _classified([changed], NOW_ROUND1), TAX_HASH_V1)
            self.assertEqual(plan["reclassify"], ["Aria#233"])

    def test_taxonomy_hash_change_reclassifies(self):
        # 规则升级 (taxonomy_hash 变) ⇒ 全量重分类 — 即使 issue/时钟全不变。
        tmp, state_path, engine = _tmp_engine(now=lambda: NOW_ROUND1)
        with tmp:
            self._saved_round(engine, [_issue()], NOW_ROUND1)
            state, _ = engine.load_state()
            plan = engine.plan_tier_a(
                state, _faces([_issue()]), _classified([_issue()], NOW_ROUND1, TAXONOMY_V2), TAX_HASH_V2
            )
            self.assertEqual(plan["reused"], [])
            self.assertEqual(plan["reclassify"], ["Aria#233"])

    def test_issue_key_change_reclassifies(self):
        tmp, state_path, engine = _tmp_engine(now=lambda: NOW_ROUND1)
        with tmp:
            self._saved_round(engine, [_issue()], NOW_ROUND1)
            state, _ = engine.load_state()
            edited = _issue(title="[缺陷][示例] incremental 基线 v2")  # title 编辑 ⇒ key 变
            plan = engine.plan_tier_a(state, _faces([edited]), _classified([edited], NOW_ROUND1), TAX_HASH_V1)
            self.assertEqual(plan["reused"], [])
            self.assertEqual(plan["reclassify"], ["Aria#233"])

    def test_staleness_none_to_value_reclassifies(self):
        # updated 字段缺席 → 在场: 快照 None → "<7d"; updated 不在 face 字段内
        # ⇒ issue_key 不变 — 纯判据输入轴触发。
        tmp, state_path, engine = _tmp_engine(now=lambda: NOW_ROUND1)
        with tmp:
            bare = _issue()
            del bare["updated"]
            self._saved_round(engine, [bare], NOW_ROUND1)
            state, _ = engine.load_state()
            self.assertIsNone(state["issues"]["Aria#233"]["judgement_inputs"]["staleness_tier"])
            with_updated = _issue()  # updated 回到 "2026-10-01"
            plan = engine.plan_tier_a(state, _faces([with_updated]), _classified([with_updated], NOW_ROUND1), TAX_HASH_V1)
            self.assertEqual(plan["reclassify"], ["Aria#233"])

    def test_new_and_closed_precise(self):
        tmp, state_path, engine = _tmp_engine(now=lambda: NOW_ROUND1)
        with tmp:
            self._saved_round(engine, [_issue(), _issue(repo="Aria", number=240)], NOW_ROUND1)
            state, _ = engine.load_state()
            # 本轮: 233 还在, 240 关了, 250 新开
            current = [_issue(), _issue(repo="Aria", number=250)]
            plan = engine.plan_tier_a(state, _faces(current), _classified(current, NOW_ROUND1), TAX_HASH_V1)
            self.assertEqual(plan["new"], ["Aria#250"])
            self.assertEqual(plan["closed"], ["Aria#240"])
            self.assertIn("Aria#250", plan["reclassify"])  # reclassify ⊇ new
            self.assertNotIn("Aria#233", plan["reclassify"])

    def test_baseline_state_all_new(self):
        tmp, state_path, engine = _tmp_engine(now=lambda: NOW_ROUND1)
        with tmp:
            issues = [_issue(), _issue(repo="SilkNode", number=12)]
            plan = engine.plan_tier_a({}, _faces(issues), _classified(issues, NOW_ROUND1), TAX_HASH_V1)
            self.assertTrue(plan["baseline_run"])
            self.assertEqual(plan["new"], ["Aria#233", "SilkNode#12"])
            self.assertEqual(plan["reused"], [])
            self.assertEqual(plan["closed"], [])
            self.assertEqual(plan["reclassify"], ["Aria#233", "SilkNode#12"])

    def test_suspicious_prev_entry_not_reused(self):
        # prev 条目缺 tier_a (条目级可疑) ⇒ 宁重评不误复用 — load 不拒载、plan 降级。
        tmp, state_path, engine = _tmp_engine(now=lambda: NOW_ROUND1)
        with tmp:
            self._saved_round(engine, [_issue()], NOW_ROUND1)
            state, _ = engine.load_state()
            del state["issues"]["Aria#233"]["tier_a"]  # 模拟条目损伤
            plan = engine.plan_tier_a(state, _faces([_issue()]), _classified([_issue()], NOW_ROUND1), TAX_HASH_V1)
            self.assertEqual(plan["reused"], [])
            self.assertEqual(plan["reclassify"], ["Aria#233"])
            self.assertEqual(plan["new"], [])  # 已知条目 (非首见) ⇒ 不算 new

    def test_faces_classified_key_mismatch_raises(self):
        tmp, state_path, engine = _tmp_engine(now=lambda: NOW_ROUND1)
        with tmp:
            faces = _faces([_issue()])
            classified_missing = []  # faces 有 233, classified 空 — 接线错误
            with self.assertRaises(ValueError):
                engine.plan_tier_a({}, faces, classified_missing, TAX_HASH_V1)
            with self.assertRaises(ValueError):  # classified 重复身份 — 拒绝静默覆盖
                engine.plan_tier_a({}, faces, _classified([_issue(), _issue()], NOW_ROUND1), TAX_HASH_V1)


# ------------------------------------------------------------- Tier B 复用门

class TierBGateTests(unittest.TestCase):

    @staticmethod
    def _gate(doc, provenance=None, **kw):
        engine = incremental.IncrementalEngine(
            "unused-state.json", assessments_reader=lambda: doc, now_fn=lambda: NOW_TTL
        )
        return engine.gate_tier_b(provenance if provenance is not None else PROVENANCE, **kw)

    def test_matching_provenance_reusable(self):
        result = self._gate(_assessments_doc({"Aria#233": _assessment_entry()}))
        self.assertEqual(result["reusable"], ["Aria#233"])
        self.assertEqual(result["stale"], {})

    def test_harness_change_makes_stale(self):
        doc = _assessments_doc({"Aria#233": _assessment_entry(harness="cursor")})
        result = self._gate(doc)
        self.assertEqual(result["stale"], {"Aria#233": "provenance-mismatch"})

    def test_model_id_change_makes_stale(self):
        doc = _assessments_doc({"Aria#233": _assessment_entry(model_id="gpt-x")})
        result = self._gate(doc)
        self.assertEqual(result["stale"], {"Aria#233": "provenance-mismatch"})

    def test_current_model_id_none_is_stale(self):
        # 脚本层 model_id 未知 (None) ⇒ 与任何具体 model_id 不匹配 ⇒ stale (fail-closed)。
        doc = _assessments_doc({"Aria#233": _assessment_entry()})
        result = self._gate(doc, provenance={"harness": "claude-code", "model_id": None})
        self.assertEqual(result["stale"], {"Aria#233": "provenance-mismatch"})

    def test_entry_missing_provenance_stale(self):
        entry = _assessment_entry()
        del entry["provenance"]
        result = self._gate(_assessments_doc({"Aria#233": entry}))
        self.assertEqual(result["stale"], {"Aria#233": "provenance-missing"})

    def test_entry_provenance_invalid_shape_stale(self):
        for bad in ({}, "claude-code", {"harness": "claude-code"}):  # 缺分量/非 dict/缺 model_id
            with self.subTest(bad=bad):
                entry = _assessment_entry()
                entry["provenance"] = bad
                result = self._gate(_assessments_doc({"Aria#233": entry}))
                self.assertEqual(result["stale"], {"Aria#233": "provenance-invalid"})

    def test_entry_not_object_stale(self):
        result = self._gate(_assessments_doc({"Aria#233": 42}))
        self.assertEqual(result["stale"], {"Aria#233": "entry-not-object"})
        result = self._gate(_assessments_doc({"Aria#233": ["x"]}))
        self.assertEqual(result["stale"], {"Aria#233": "entry-not-object"})

    def test_no_assessments_available_empty_result(self):
        for reader_value in (None,):  # reader 返回 None = 文件缺席
            result = self._gate(reader_value)
            self.assertEqual(result, {"reusable": [], "stale": {}, "orphaned": []})
        engine = incremental.IncrementalEngine("unused.json")  # reader 未注入
        self.assertEqual(
            engine.gate_tier_b(PROVENANCE),
            {"reusable": [], "stale": {}, "orphaned": []},
        )

    def test_orphaned_keys_not_stale_not_reusable(self):
        # assessment 键不在本轮 issue 键集 ⇒ orphaned (issue 已关闭), 不进 stale。
        doc = _assessments_doc({"Aria#233": _assessment_entry(), "Aria#240": _assessment_entry()})
        result = self._gate(doc, current_keys=["Aria#233"])
        self.assertEqual(result["reusable"], ["Aria#233"])
        self.assertEqual(result["stale"], {})
        self.assertEqual(result["orphaned"], ["Aria#240"])

    def test_ttl_expiry_makes_stale(self):
        # NOW_TTL=2026-10-19T12:00Z; created=10-09 ⇒ age 10d; ttl=7 ⇒ 过期。
        doc = _assessments_doc({"Aria#233": _assessment_entry(created_at="2026-10-09T12:00:00Z")})
        result = self._gate(doc, assessments_ttl=7)
        self.assertEqual(result["stale"], {"Aria#233": "ttl-expired"})

    def test_ttl_boundary_day_counts_as_expired(self):
        # 边界: age == ttl (整 7 天) ⇒ 过期 (>= 语义钉死, 防 off-by-one 歧义)。
        doc = _assessments_doc({"Aria#233": _assessment_entry(created_at="2026-10-12T12:00:00Z")})
        self.assertEqual(
            self._gate(doc, assessments_ttl=7)["stale"], {"Aria#233": "ttl-expired"}
        )
        # 差一秒未到期 ⇒ 可复用
        doc2 = _assessments_doc({"Aria#233": _assessment_entry(created_at="2026-10-12T12:00:01Z")})
        self.assertEqual(self._gate(doc2, assessments_ttl=7)["stale"], {})

    def test_ttl_generous_still_reusable(self):
        doc = _assessments_doc({"Aria#233": _assessment_entry(created_at="2026-10-18T08:30:00Z")})
        result = self._gate(doc, assessments_ttl=30)
        self.assertEqual(result["reusable"], ["Aria#233"])

    def test_ttl_inactive_ignores_created_at_age(self):
        # ttl 未配置 ⇒ created_at 年龄不影响复用 (只有 provenance 门)。
        doc = _assessments_doc({"Aria#233": _assessment_entry(created_at="2020-01-01T00:00:00Z")})
        result = self._gate(doc)  # 无 assessments_ttl
        self.assertEqual(result["reusable"], ["Aria#233"])

    def test_ttl_unparseable_created_at_stale(self):
        doc = _assessments_doc({"Aria#233": _assessment_entry(created_at="yesterday-ish")})
        result = self._gate(doc, assessments_ttl=7)
        self.assertEqual(result["stale"], {"Aria#233": "created-at-unparseable"})

    def test_created_at_missing_stale_even_without_ttl(self):
        # created_at 是契约必填键 — 缺即违约条目, 复用门不放行。
        entry = _assessment_entry()
        del entry["created_at"]
        result = self._gate(_assessments_doc({"Aria#233": entry}))
        self.assertEqual(result["stale"], {"Aria#233": "created-at-missing"})

    def test_document_root_shape_violations_raise(self):
        for bad_doc, why in (
            ([], "root not object"),
            ({"schema_version": 2, "assessments": {}}, "future version"),
            ({"assessments": {}}, "missing schema_version"),
            ({"schema_version": 1}, "missing assessments"),
            ({"schema_version": 1, "assessments": []}, "assessments not object"),
        ):
            with self.subTest(why=why):
                with self.assertRaises(ValueError):
                    self._gate(bad_doc)

    def test_unknown_top_level_keys_tolerated(self):
        # additive-only 的 reader 方向: 未来写者新增键 ⇒ 旧 reader 忽略不炸。
        doc = _assessments_doc({"Aria#233": _assessment_entry()})
        doc["future_field"] = {"anything": True}
        result = self._gate(doc)
        self.assertEqual(result["reusable"], ["Aria#233"])

    def test_malformed_current_provenance_raises(self):
        # 本轮 provenance 面非法 = 调用方接线错误 — loud, 不静默产全 stale。
        with self.assertRaises(ValueError):
            self._gate(_assessments_doc({}), provenance={"harness": ""})


# ------------------------------------------------------ 默认 assessments reader

class DefaultAssessmentsReaderTests(unittest.TestCase):

    def test_missing_file_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            reader = incremental.default_assessments_reader(tmp)
            self.assertIsNone(reader())

    def test_valid_file_parsed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".aria" / "groom-assessments.json"
            path.parent.mkdir(parents=True)
            doc = _assessments_doc({"Aria#233": _assessment_entry()})
            path.write_text(json.dumps(doc), encoding="utf-8")
            self.assertEqual(incremental.default_assessments_reader(tmp)(), doc)

    def test_existing_but_invalid_json_raises(self):
        # 存在的坏文件不冒充缺席 (fail-closed) — 与「文件缺席 ⇒ None」结构可区分。
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".aria" / "groom-assessments.json"
            path.parent.mkdir(parents=True)
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(ValueError):
                incremental.default_assessments_reader(tmp)()


# ---------------------------------------------------------------- state 构建

class BuildStateTests(unittest.TestCase):

    @staticmethod
    def _run_two_rounds(engine, round2_issues=None, round2_now=None):
        issues = [_issue(), _issue(repo="Aria", number=240)]
        _, state1 = TierAPlanTests._saved_round(engine, issues, NOW_ROUND1)
        state, _ = engine.load_state()
        current = round2_issues if round2_issues is not None else issues
        now2 = round2_now or NOW_ROUND1
        faces = _faces(current)
        classified = _classified(current, now2)
        plan = engine.plan_tier_a(state, faces, classified, TAX_HASH_V1)
        state2 = engine.build_next_state(state, plan, faces, classified, TAX_HASH_V1, CTX_FP, PROVENANCE)
        return state1, state2, plan

    def test_state_shape_matches_contract(self):
        tmp, state_path, engine = _tmp_engine(now=lambda: NOW_ROUND1)
        with tmp:
            state = engine.build_next_state(
                {}, {"reused": [], "new": ["Aria#233"], "closed": [], "reclassify": ["Aria#233"]},
                _faces([_issue()]), _classified([_issue()], NOW_ROUND1), TAX_HASH_V1,
                CTX_FP, PROVENANCE,
            )
            self.assertEqual(sorted(state), ["issues", "last_run", "schema_version"])
            self.assertEqual(state["schema_version"], 1)
            self.assertEqual(sorted(state["last_run"]), ["context_fingerprint", "provenance"])
            self.assertEqual(state["last_run"]["context_fingerprint"], CTX_FP)  # 全量保存
            self.assertEqual(state["last_run"]["provenance"], PROVENANCE)
            entry = state["issues"]["Aria#233"]
            self.assertEqual(
                sorted(entry), ["issue_key", "judgement_inputs", "last_classified_at", "tier_a"]
            )
            self.assertEqual(sorted(entry["tier_a"]), ["category", "signals"])

    def test_reused_entry_carried_verbatim_with_original_timestamp(self):
        stamps = iter([NOW_ROUND1, NOW_ROUND2])  # r1 fresh=10-05; r2 fresh=10-10
        tmp, state_path, engine = _tmp_engine(now=lambda: next(stamps))
        with tmp:
            state1, state2, plan = self._run_two_rounds(engine)  # r2 与 r1 全同 ⇒ 复用
            self.assertEqual(plan["reused"], ["Aria#233", "Aria#240"])
            self.assertEqual(state2["issues"]["Aria#233"], state1["issues"]["Aria#233"])  # 逐字续传
            self.assertIn("2026-10-05T12:00:00Z", state2["issues"]["Aria#233"]["last_classified_at"])

    def test_reclassified_entry_gets_fresh_timestamp(self):
        clock = {"now": NOW_ROUND1}
        tmp, state_path, engine = _tmp_engine(now=lambda: clock["now"])
        with tmp:
            TierAPlanTests._saved_round(engine, [_issue()], NOW_ROUND1)  # fresh @ 10-05
            state, _ = engine.load_state()
            edited = [_issue(title="[缺陷][示例] incremental 基线 v2")]  # key 变 ⇒ reclassify
            faces, classified = _faces(edited), _classified(edited, NOW_ROUND1)
            plan = engine.plan_tier_a(state, faces, classified, TAX_HASH_V1)
            self.assertEqual(plan["reclassify"], ["Aria#233"])
            clock["now"] = NOW_ROUND2  # 推进时钟 ⇒ 新条目时间戳取新值
            state2 = engine.build_next_state(state, plan, faces, classified, TAX_HASH_V1, CTX_FP, PROVENANCE)
            self.assertEqual(state2["issues"]["Aria#233"]["last_classified_at"], "2026-10-10T12:00:00Z")
            self.assertNotEqual(
                state2["issues"]["Aria#233"]["last_classified_at"],
                state["issues"]["Aria#233"]["last_classified_at"],
            )

    def test_closed_issues_dropped_from_next_state(self):
        tmp, state_path, engine = _tmp_engine(now=lambda: NOW_ROUND1)
        with tmp:
            _, state2, _ = self._run_two_rounds(engine, round2_issues=[_issue()])  # 240 本轮缺席
            self.assertEqual(sorted(state2["issues"]), ["Aria#233"])

    def test_assessments_ttl_carry_forward_and_override(self):
        tmp, state_path, engine = _tmp_engine(now=lambda: NOW_ROUND1)
        with tmp:
            issues = [_issue()]
            faces, classified = _faces(issues), _classified(issues, NOW_ROUND1)
            plan = {"reused": [], "new": ["Aria#233"], "closed": [], "reclassify": ["Aria#233"]}
            s1 = engine.build_next_state({}, plan, faces, classified, TAX_HASH_V1, CTX_FP, PROVENANCE,
                                         assessments_ttl=7)
            self.assertEqual(s1["assessments_ttl"], 7)
            s2 = engine.build_next_state(s1, plan, faces, classified, TAX_HASH_V1, CTX_FP, PROVENANCE)
            self.assertEqual(s2["assessments_ttl"], 7)  # 缺省续传
            s3 = engine.build_next_state(s2, plan, faces, classified, TAX_HASH_V1, CTX_FP, PROVENANCE,
                                         assessments_ttl=14)
            self.assertEqual(s3["assessments_ttl"], 14)  # 显式覆盖
            s4 = engine.build_next_state(s3, plan, faces, classified, TAX_HASH_V1, CTX_FP, PROVENANCE,
                                         assessments_ttl=None)
            self.assertNotIn("assessments_ttl", s4)  # None = 清除 (不写 null)

    def test_state_serialization_deterministic(self):
        tmp, state_path, engine = _tmp_engine(now=lambda: NOW_ROUND1)
        with tmp:
            issues = [_issue()]
            args = ({}, {"reused": [], "new": ["Aria#233"], "closed": [], "reclassify": ["Aria#233"]},
                    _faces(issues), _classified(issues, NOW_ROUND1), TAX_HASH_V1, CTX_FP, PROVENANCE)
            s1 = engine.build_next_state(*args)
            s2 = engine.build_next_state(*args)
            self.assertEqual(
                json.dumps(s1, sort_keys=True), json.dumps(s2, sort_keys=True)
            )  # 同时钟同输入 ⇒ 字节稳定 (跨运行可比性)


# ------------------------------------------------------------------- 原子写

class AtomicWriteTests(unittest.TestCase):

    def test_save_creates_nested_path_and_valid_json(self):
        tmp, state_path, engine = _tmp_engine()
        with tmp:
            self.assertFalse(state_path.exists())  # .aria/cache/ 尚不存在
            state = {"schema_version": 1, "last_run": None, "issues": {}}
            engine.save_state(state)
            self.assertTrue(state_path.is_file())
            self.assertEqual(json.loads(state_path.read_text(encoding="utf-8")), state)

    def test_save_leaves_no_temp_file(self):
        tmp, state_path, engine = _tmp_engine()
        with tmp:
            engine.save_state({"schema_version": 1, "issues": {}})
            leftovers = list(state_path.parent.glob(f"{state_path.name}.tmp*"))
            self.assertEqual(leftovers, [])

    def test_crash_during_rename_fresh_write_leaves_no_half_file(self):
        def crashing_rename(src, dst):
            raise RuntimeError("simulated crash mid-rename")
        tmp, state_path, engine = _tmp_engine(rename_fn=crashing_rename)
        with tmp:
            with self.assertRaises(RuntimeError):
                engine.save_state({"schema_version": 1, "issues": {"A#1": {}}})
            self.assertFalse(state_path.exists())  # 目标路径不存在 = 旧态之一
            self.assertEqual(list(state_path.parent.glob(f"{state_path.name}.tmp*")), [])

    def test_crash_during_rename_overwrite_keeps_previous_bytes(self):
        tmp, state_path, engine = _tmp_engine()
        with tmp:
            v1 = {"schema_version": 1, "issues": {"A#1": {"issue_key": "k1"}}}
            engine.save_state(v1)
            before = state_path.read_bytes()
            def crashing_rename(src, dst):
                raise RuntimeError("simulated crash mid-rename")
            engine2 = incremental.IncrementalEngine(state_path, rename_fn=crashing_rename,
                                                    now_fn=lambda: NOW_ROUND1)
            with self.assertRaises(RuntimeError):
                engine2.save_state({"schema_version": 1, "issues": {"A#1": {"issue_key": "k2"}}})
            self.assertEqual(state_path.read_bytes(), before)  # 旧内容原封不动
            self.assertEqual(list(state_path.parent.glob(f"{state_path.name}.tmp*")), [])

    def test_save_supersedes_previous_state(self):
        tmp, state_path, engine = _tmp_engine()
        with tmp:
            engine.save_state({"schema_version": 1, "issues": {"A#1": {"v": 1}}})
            engine.save_state({"schema_version": 1, "issues": {"A#1": {"v": 2}}})
            self.assertEqual(json.loads(state_path.read_text(encoding="utf-8"))["issues"]["A#1"]["v"], 2)


# --------------------------------------------- 裁定④: assessments 永不被引擎写

class AssessmentsUntouchedInvariantTests(unittest.TestCase):
    """不变量: groom.py / 引擎重写 state (多轮) 前后, groom-assessments.json
    **字节不变** — 引擎对该文件只读 (注入 reader), 无任何写面。"""

    def test_state_rewrites_leave_assessments_bytes_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            aria = root / ".aria"
            aria.mkdir()
            apath = aria / "groom-assessments.json"
            original = json.dumps(
                _assessments_doc({"Aria#233": _assessment_entry()}), indent=2, ensure_ascii=False
            ) + "\n"
            apath.write_text(original, encoding="utf-8")

            stamps = iter([NOW_ROUND1, NOW_ROUND2, NOW_ROUND2])
            engine = incremental.IncrementalEngine(
                aria / "cache" / "groom-state.json",
                assessments_reader=incremental.default_assessments_reader(root),
                now_fn=lambda: next(stamps, NOW_ROUND2),
            )
            issue = _issue()
            for label, now, issues in (
                ("baseline", NOW_ROUND1, [issue]),
                ("cross-tier reclassify", NOW_ROUND2, [issue]),   # staleness 跨档
                ("identical reuse", NOW_ROUND2, [issue]),
            ):
                with self.subTest(round=label):
                    state, _ = engine.load_state()
                    faces = _faces(issues)
                    classified = _classified(issues, now)
                    plan = engine.plan_tier_a(state, faces, classified, TAX_HASH_V1)
                    engine.save_state(engine.build_next_state(
                        state, plan, faces, classified, TAX_HASH_V1, CTX_FP, PROVENANCE
                    ))
                    self.assertEqual(apath.read_bytes(), original.encode("utf-8"))

    def test_save_state_never_invokes_assessments_reader(self):
        calls = []

        def counting_reader():
            calls.append(1)
            return None

        tmp, state_path, engine = _tmp_engine(doc_reader=counting_reader)
        with tmp:
            engine.save_state({"schema_version": 1, "issues": {}})
            engine.save_state({"schema_version": 1, "issues": {"A#1": {}}})
            self.assertEqual(calls, [])  # 写 state 全程零 assessment 触碰

    def test_engine_holds_no_assessments_path(self):
        # 结构性防伪: 引擎实例状态里不存在 assessment 路径 — 写面在结构上不可达
        # (reader 闭包持有只读路径, 引擎无法经它写)。
        tmp, state_path, engine = _tmp_engine(
            doc_reader=incremental.default_assessments_reader("/tmp")
        )
        with tmp:
            self.assertNotIn("groom-assessments", repr(vars(engine)))


if __name__ == "__main__":
    unittest.main()

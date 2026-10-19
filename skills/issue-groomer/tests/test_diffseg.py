"""TASK-006 — lib/diffseg.py 测试 (diff 段引擎, SC-4)。

覆盖任务 verification: "SC-4: baseline run = no-diff (专属 fixture);
新增/已关闭=集合差; 漂移仅有新评估条目报告 + top-N 上限 fixture"。

  1. baseline 语义 (BaselineTests): no-diff 空集三数组 + baseline_run=true;
     有对照内容的 plan 同样短路; 参数校验先于短路 (垃圾 top_n 在 baseline
     轮同样上抛)。
  2. 常规面 (SetDiffTests): new/closed 键级直通 (排序+去重); drift 候选池
     = reclassify ∪ new ∪ assessed_keys; reused 未重评不进 drift, 经
     assessed_keys 点名 (Tier B stale 重评) 才进; 域外/closed 键不产生
     漂移; 产出面恒为纯 JSON 数据。
  3. top-N 截断 (TopNTests): 全量重评 100 条 top_n=20 ⇒ 恰 20 +
     truncated + total 100, 截断集 = 字典序前 20 (确定性; number 段为
     字符串序 'Aria#10' < 'Aria#2'); top_n 边界 (0/负/bool/None) 语义
     钉死; None 超 schema maxItems=100 护栏上抛; 不变量
     truncated <=> total > len(drift) 参数化扫档。
  4. 形状 fail-closed (PlanShapeTests): plan 缺键/非 mapping/非 bool
     baseline_run/非 str 键; assessed_keys 非 str 键。
  5. 富化基元 (EnrichmentTests): split_issue_key 往返 + 非法形态;
     build_diff_ref / build_drift_entry 产 schema 条目形态。
  6. schema 一致性 (SchemaFaceTests): 产出 diff 面经富化过
     groom-report.schema.json DiffSection (复用 test_schema.mini_validate);
     additive 字段在 schema 中可选且 required 集不变 (additive-only 证明);
     schema maxItems 与模块常量锁步; 负向 (未知字段 / 缺 from) 有牙齿。
  7. 集成 (PipelineIntegrationTests): 真 IncrementalEngine.plan_tier_a 三轮
     (baseline → 全复用 → taxonomy 升级全量重评) → build_diff_segment
     端到端 — plan 形状契约实证 (非 hand-built plan), 含 Tier B stale
     重评 (assessed_keys) 注入形态。

fixture 形态锚点 (裁定-7 防形态脱节): taxonomy/provenance/上下文指纹形态
对齐 test_incremental.py (同锚); issue 行 = fetch 层归一形态超集。

References:
  openspec/changes/issue-groomer-p1-mvp (proposal §1 diff 段, SC-4);
  scripts/lib/incremental.py (plan_tier_a / compute_diff 契约);
  scripts/groom-report.schema.json (DiffSection, snapshot_schema_version 1.1)。
"""

from __future__ import annotations

import copy
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

# Add scripts/ to path for direct module import (house convention).
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "scripts"))

from lib import diffseg, fingerprint, incremental, tier_a  # noqa: E402

# 生产层 mini-validate (stdlib 结构断言器; SOT = lib/schema_validate.py,
# B.3 依赖方向修正后不再经 test_schema 转引)。
from lib.schema_validate import mini_validate  # noqa: E402

_SCHEMA_PATH = (
    Path(__file__).parent.parent / "scripts" / "groom-report.schema.json"
)


# ------------------------------------------------------------- fixture 基元

TAXONOMY_V1 = {
    "version": 1,
    "categories": {"bug": "kind/bug", "feature": "kind/feature"},
    "title_prefixes": {"[缺陷]": "bug", "[feature]": "feature"},
    "label_signals": {"kind/bug": "bug", "kind/feature": "feature"},
}
TAXONOMY_V2 = {  # 规则升级形态: 新增分类 ⇒ taxonomy_hash 变 ⇒ 全量重评
    "version": 1,
    "categories": {"bug": "kind/bug", "feature": "kind/feature", "docs": "kind/docs"},
    "title_prefixes": {"[缺陷]": "bug", "[feature]": "feature", "[docs]": "docs"},
    "label_signals": {"kind/bug": "bug", "kind/feature": "feature", "kind/docs": "docs"},
}

PROVENANCE = {"harness": "claude-code", "model_id": "glm-5.2"}
CTX_FP = {  # TASK-004 上下文面四分量形态 (内容任意, build 原样保存)
    "openspec_changes_hash": "0f" * 32,
    "git_heads": {"/home/dev/Aria": "ab" * 20},
    "handoff_pointer": "2026-10-18-235-cycle-done.md",
    "taxonomy_hash": tier_a.taxonomy_hash(TAXONOMY_V1),
}

NOW = datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)


def _plan(
    *,
    baseline_run: bool = False,
    new: list[str] | tuple[str, ...] = (),
    closed: list[str] | tuple[str, ...] = (),
    reused: list[str] | tuple[str, ...] = (),
    reclassify: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    """plan_tier_a 直出形态基线 (五键; 测试内手构, 集成测试另用真引擎)。"""
    return {
        "baseline_run": baseline_run,
        "new": list(new),
        "closed": list(closed),
        "reused": list(reused),
        "reclassify": list(reclassify),
    }


def _issue(repo: str, number: int, title: str) -> dict[str, Any]:
    """fetch 层归一形态超集 (与 test_incremental._issue 同判)。"""
    return {
        "repo": repo,
        "number": number,
        "title": title,
        "labels": ["kind/bug"],
        "created": "2026-09-01",
        "updated": "2026-10-01",
        "comments_count": 0,
        "body": "b",
        "comments": [],
        "comments_error": None,
    }


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def diff_node(schema: dict[str, Any]) -> dict[str, Any]:
    return schema["$defs"]["DiffSection"]


# ── 1. baseline 语义 (SC-4 专属 fixture) ─────────────────────────────────────


class TestBaseline:
    def test_baseline_plan_yields_no_diff_face(self) -> None:
        """baseline_run=true ⇒ 三数组恒空 + baseline_run true + additive 归零。"""
        seg = diffseg.build_diff_segment(_plan(baseline_run=True))
        assert seg == {
            "new": [],
            "closed": [],
            "drift": [],
            "baseline_run": True,
            "drift_truncated": False,
            "drift_total": 0,
        }

    def test_baseline_short_circuits_even_with_populated_faces(self) -> None:
        """首跑全量 new/reclassify (50/100 条) 一样 no-diff — 首跑无对照面,
        总量在 summary 层报 (TASK-017), diff 面不冒充对照。"""
        keys = [f"R#{n}" for n in range(1, 101)]
        plan = _plan(baseline_run=True, new=keys[:50], reclassify=keys)
        seg = diffseg.build_diff_segment(plan)
        assert seg["new"] == [] and seg["closed"] == [] and seg["drift"] == []
        assert seg["baseline_run"] is True
        assert seg["drift_truncated"] is False and seg["drift_total"] == 0

    def test_param_validation_precedes_baseline_shortcut(self) -> None:
        """垃圾 top_n 在 baseline 轮同样 ValueError — 校验先于短路 (fail-closed,
        不因「反正要短路」放过接线错误)。"""
        with pytest.raises(ValueError, match="top_n"):
            diffseg.build_diff_segment(_plan(baseline_run=True), top_n=-1)
        with pytest.raises(ValueError, match="top_n"):
            diffseg.build_diff_segment(_plan(baseline_run=True), top_n=True)


# ── 2. 常规面: 集合差直通 + 漂移候选池 ───────────────────────────────────────


class TestSetDiff:
    def test_new_closed_passthrough_sorted(self) -> None:
        """new/closed 键级直通: 排序输出 + 防御去重 (乱序/重复入, 有序无重出)。"""
        plan = _plan(
            new=["B#2", "A#1", "B#2"],
            closed=["C#9", "C#3"],
            reclassify=["A#1", "B#2"],
        )
        seg = diffseg.build_diff_segment(plan)
        assert seg["new"] == ["A#1", "B#2"]
        assert seg["closed"] == ["C#3", "C#9"]

    def test_drift_pool_defaults_to_reclassify_union_new(self) -> None:
        """assessed_keys=None (机械层无 Tier B 信息) ⇒ 候选池 = reclassify ∪ new
        (new 并入 plan_tier_a 的 reclassify ⊇ new 不变量之外也成立 — 防御并集)。"""
        plan = _plan(new=["A#5"], reclassify=["B#7"], reused=["C#9"])
        seg = diffseg.build_diff_segment(plan)
        assert seg["drift"] == ["A#5", "B#7"]
        assert seg["drift_truncated"] is False and seg["drift_total"] == 2

    def test_reused_unassessed_excluded_from_drift(self) -> None:
        """复用条目 (reused 且未重评) 不进 drift — 复用不是重新分类/评估。"""
        plan = _plan(reused=["A#1", "A#2"], reclassify=["A#3"])
        seg = diffseg.build_diff_segment(plan)
        assert seg["drift"] == ["A#3"]

    def test_reused_reassessed_enters_drift(self) -> None:
        """reused 经 assessed_keys 点名 (Tier B stale 重评) ⇒ 进 drift —
        分类未变但评估刷新, 正是漂移面的典型来源。"""
        plan = _plan(reused=["A#1", "A#2"], reclassify=["A#3"])
        seg = diffseg.build_diff_segment(plan, assessed_keys=["A#2"])
        assert seg["drift"] == ["A#2", "A#3"]
        assert seg["drift_total"] == 2

    def test_assessed_keys_outside_current_domain_pruned(self) -> None:
        """域外 assessed_keys (已 closed 键 / 本轮从未在册键) 不产生漂移 —
        报告只承本轮在册条目。"""
        plan = _plan(
            new=["A#1"],
            closed=["Z#99"],
            reused=["A#2"],
            reclassify=["A#3"],
        )
        seg = diffseg.build_diff_segment(plan, assessed_keys=["Z#99", "GHOST#1"])
        assert seg["drift"] == ["A#1", "A#3"]

    def test_output_is_plain_json_data(self) -> None:
        """产出面恒为纯 JSON 数据 (纯函数契约: json round-trip 等值)。"""
        plan = _plan(new=["A#1"], closed=["B#2"], reclassify=["A#1", "C#3"])
        seg = diffseg.build_diff_segment(plan)
        assert json.loads(json.dumps(seg)) == seg


# ── 3. top-N 截断 (SC-4 top-N 上限 fixture) ──────────────────────────────────


class TestTopN:
    def test_full_reassess_100_top_20_exact(self) -> None:
        """全量重评 (taxonomy 升级 ⇒ reclassify=全体) 100 条 top_n=20 ⇒
        drift 恰 20 + truncated true + total 100; 截断集 = 排序前 20 (确定性)。"""
        keys = [f"R#{n}" for n in range(1, 101)]
        plan = _plan(reclassify=keys)
        seg = diffseg.build_diff_segment(plan, top_n=20)
        assert len(seg["drift"]) == 20
        assert seg["drift_truncated"] is True
        assert seg["drift_total"] == 100
        assert seg["drift"] == sorted(keys)[:20]

    def test_truncation_order_is_lexicographic(self) -> None:
        """排序 = 键字符串纯字典序 (与 incremental.py 全模块口径一致):
        number 段按字符串序, 'Aria#10' < 'Aria#2' < 'Aria#9' — 钉死非数值序。"""
        plan = _plan(reclassify=["Aria#9", "Aria#2", "Aria#10"])
        seg = diffseg.build_diff_segment(plan, top_n=None)
        assert seg["drift"] == ["Aria#10", "Aria#2", "Aria#9"]

    def test_top_n_zero_pinned(self) -> None:
        """top_n=0 = 恒空面但 drift_total 照报 (截断到零 ≠ 无候选)。"""
        plan = _plan(reclassify=["A#1", "A#2", "A#3"])
        seg = diffseg.build_diff_segment(plan, top_n=0)
        assert seg["drift"] == []
        assert seg["drift_truncated"] is True
        assert seg["drift_total"] == 3

    def test_top_n_negative_raises(self) -> None:
        """top_n<0 = 接线错误 ⇒ ValueError (不 abs、不静默当 0)。"""
        with pytest.raises(ValueError, match="top_n"):
            diffseg.build_diff_segment(_plan(reclassify=["A#1"]), top_n=-1)

    def test_top_n_bool_rejected(self) -> None:
        """bool 是 int 子类陷阱: True(==1) 不当上限 1 用 ⇒ ValueError。"""
        with pytest.raises(ValueError, match="top_n"):
            diffseg.build_diff_segment(_plan(reclassify=["A#1"]), top_n=True)

    def test_top_n_none_is_uncapped(self) -> None:
        """None = 不截断 (全量候选直通); 护栏内 (30 ≤ 100) 合法。"""
        keys = [f"R#{n}" for n in range(1, 31)]
        seg = diffseg.build_diff_segment(_plan(reclassify=keys), top_n=None)
        assert seg["drift"] == sorted(keys)
        assert seg["drift_truncated"] is False and seg["drift_total"] == 30

    def test_top_n_none_beyond_schema_guardrail_raises(self) -> None:
        """None 且候选 150 > schema maxItems=100 ⇒ ValueError — 运行时超护栏
        须先 bump schema minor, 不静默产出 schema 非法报告。"""
        keys = [f"R#{n}" for n in range(1, 151)]
        with pytest.raises(ValueError, match="maxItems"):
            diffseg.build_diff_segment(_plan(reclassify=keys), top_n=None)

    def test_top_n_above_pool_no_truncation(self) -> None:
        """top_n (20) > 候选数 (5) ⇒ 全量入面, truncated false, total == len。"""
        keys = [f"R#{n}" for n in range(1, 6)]
        seg = diffseg.build_diff_segment(_plan(reclassify=keys), top_n=20)
        assert seg["drift"] == sorted(keys)
        assert seg["drift_truncated"] is False and seg["drift_total"] == 5

    @pytest.mark.parametrize("top_n", [0, 1, 7, 20, 99, None])
    def test_truncation_invariant_pair(self, top_n: int | None) -> None:
        """不变量扫档 (10 候选): len(drift) = min(top_n, total) (None=total);
        truncated <=> total > len(drift) — 两 additive 字段永不说谎。"""
        keys = [f"K#{n}" for n in range(1, 11)]
        seg = diffseg.build_diff_segment(_plan(reclassify=keys), top_n=top_n)
        expected_len = 10 if top_n is None else min(top_n, 10)
        assert seg["drift_total"] == 10
        assert len(seg["drift"]) == expected_len
        assert seg["drift_truncated"] is (expected_len < 10)
        assert seg["drift"] == sorted(keys)[:expected_len]


# ── 4. plan 形状 fail-closed ────────────────────────────────────────────────


class TestPlanShape:
    @pytest.mark.parametrize(
        "missing", ["baseline_run", "new", "closed", "reused", "reclassify"]
    )
    def test_missing_plan_key_raises(self, missing: str) -> None:
        plan = _plan()
        del plan[missing]
        with pytest.raises(ValueError, match="plan"):
            diffseg.build_diff_segment(plan)

    def test_non_mapping_plan_raises(self) -> None:
        with pytest.raises(ValueError, match="plan"):
            diffseg.build_diff_segment(["A#1"])  # type: ignore[arg-type]

    def test_non_bool_baseline_run_raises(self) -> None:
        with pytest.raises(ValueError, match="baseline_run"):
            diffseg.build_diff_segment(_plan(baseline_run="yes"))  # type: ignore[arg-type]

    def test_non_str_key_in_plan_raises(self) -> None:
        with pytest.raises(ValueError, match=r"plan\.new"):
            diffseg.build_diff_segment(_plan(new=["A#1", 42]))  # type: ignore[list-item]

    def test_non_str_assessed_key_raises(self) -> None:
        with pytest.raises(ValueError, match="assessed_keys"):
            diffseg.build_diff_segment(_plan(), assessed_keys=["A#1", None])  # type: ignore[list-item]


# ── 5. 富化基元 (TASK-017 组装 seam) ────────────────────────────────────────


class TestEnrichment:
    @pytest.mark.parametrize(
        "key,repo,number",
        [
            ("Aria#233", "Aria", 233),
            ("aria-plugin#12", "aria-plugin", 12),
            ("Aether#1", "Aether", 1),
        ],
    )
    def test_split_issue_key_roundtrip(self, key: str, repo: str, number: int) -> None:
        """合法键拆分 (含带连字符裸仓名 — 跨仓形态)。"""
        assert diffseg.split_issue_key(key) == (repo, number)

    @pytest.mark.parametrize(
        "bad", ["Aria", "#123", "Aria#", "Aria#x", "Aria#0", "Aria#-3", "Aria# 5", "Aria#1.5", 123]
    )
    def test_split_issue_key_malformed_raises(self, bad: Any) -> None:
        """非法键形态全谱 ⇒ ValueError (组装层不猜; number<1 违 schema minimum)。"""
        with pytest.raises(ValueError):
            diffseg.split_issue_key(bad)

    def test_build_diff_ref_shape(self) -> None:
        ref = diffseg.build_diff_ref("Aria#241", "标题原文")
        assert ref == {"repo": "Aria", "number": 241, "title": "标题原文"}

    def test_build_diff_ref_rejects_non_str_title(self) -> None:
        with pytest.raises(ValueError, match="title"):
            diffseg.build_diff_ref("Aria#1", 42)  # type: ignore[arg-type]

    def test_build_drift_entry_shape(self) -> None:
        entry = diffseg.build_drift_entry("aria-plugin#208", "标题", "P1", "P2")
        assert entry == {
            "repo": "aria-plugin",
            "number": 208,
            "title": "标题",
            "from": "P1",
            "to": "P2",
        }

    def test_build_drift_entry_rejects_non_str_values(self) -> None:
        with pytest.raises(ValueError, match="from/to"):
            diffseg.build_drift_entry("Aria#1", "t", 5, "P2")  # type: ignore[arg-type]


# ── 6. schema 一致性 (复用 test_schema 的 mini-validate 思路) ───────────────


class TestSchemaFace:
    def test_additive_fields_present_optional_and_typed(
        self, schema: dict[str, Any]
    ) -> None:
        """1.1 additive 面: drift_truncated (boolean) / drift_total (integer
        minimum 0) 在 DiffSection.properties 且不入 required (旧报告无二字段
        仍合法 — additive-only 证明之一)。"""
        node = schema["$defs"]["DiffSection"]
        assert node["properties"]["drift_truncated"]["type"] == "boolean"
        assert node["properties"]["drift_total"]["type"] == "integer"
        assert node["properties"]["drift_total"]["minimum"] == 0
        assert "drift_truncated" not in node["required"]
        assert "drift_total" not in node["required"]

    def test_required_keyset_unchanged_four(self, schema: dict[str, Any]) -> None:
        """additive-only 证明之二: required 集仍恰为原四键 (加字段不动必填面)。"""
        assert set(schema["$defs"]["DiffSection"]["required"]) == {
            "new",
            "closed",
            "drift",
            "baseline_run",
        }

    def test_maxitems_lockstep_with_module_constant(
        self, schema: dict[str, Any]
    ) -> None:
        """schema drift.maxItems == diffseg.DRIFT_SCHEMA_MAX_ITEMS 锁步
        (护栏 bump minor 时两处须同步 — 机械兜底防漂移)。"""
        assert (
            schema["$defs"]["DiffSection"]["properties"]["drift"]["maxItems"]
            == diffseg.DRIFT_SCHEMA_MAX_ITEMS
            == 100
        )

    def _enriched_section(self, seg: dict[str, Any]) -> dict[str, Any]:
        """键级 diff 面 → schema 条目形态 (title/判读值以确定性 dummy 供值 —
        富化映射本身是 TASK-017 职责, 此处只验 schema 形态兼容)。"""
        return {
            "new": [diffseg.build_diff_ref(k, f"title {k}") for k in seg["new"]],
            "closed": [diffseg.build_diff_ref(k, f"title {k}") for k in seg["closed"]],
            "drift": [
                diffseg.build_drift_entry(k, f"title {k}", "P1", "P2")
                for k in seg["drift"]
            ],
            "baseline_run": seg["baseline_run"],
            "drift_truncated": seg["drift_truncated"],
            "drift_total": seg["drift_total"],
        }

    def test_enriched_regular_section_validates(
        self, schema: dict[str, Any], diff_node: dict[str, Any]
    ) -> None:
        """常规产出面 (含 additive 二字段) 经富化过 DiffSection 校验。"""
        plan = _plan(
            new=["Aria#241"],
            closed=["aria-plugin#199"],
            reused=["Aria#236"],
            reclassify=["aria-plugin#208", "Aria#241"],
        )
        seg = diffseg.build_diff_segment(plan)
        errors = mini_validate(self._enriched_section(seg), diff_node, root=schema)
        assert errors == [], "\n".join(errors)

    def test_enriched_section_without_additive_fields_still_validates(
        self, schema: dict[str, Any], diff_node: dict[str, Any]
    ) -> None:
        """additive-only 证明之三: 删去 1.1 二字段的 diff 段 (1.0 形态) 仍过
        1.1 schema 校验 — 新字段可选, 未版本化收窄被结构性排除。"""
        plan = _plan(new=["Aria#241"], reclassify=["Aria#241"])
        seg = diffseg.build_diff_segment(plan)
        enriched = self._enriched_section(seg)
        del enriched["drift_truncated"]
        del enriched["drift_total"]
        errors = mini_validate(enriched, diff_node, root=schema)
        assert errors == [], "\n".join(errors)

    def test_enriched_truncated_section_validates(
        self, schema: dict[str, Any], diff_node: dict[str, Any]
    ) -> None:
        """截断形态 (truncated true / total > len) 同样 schema 合法。"""
        keys = [f"R#{n}" for n in range(1, 31)]
        seg = diffseg.build_diff_segment(_plan(reclassify=keys), top_n=3)
        assert seg["drift_truncated"] is True
        errors = mini_validate(self._enriched_section(seg), diff_node, root=schema)
        assert errors == [], "\n".join(errors)

    def test_enriched_baseline_section_validates(
        self, schema: dict[str, Any], diff_node: dict[str, Any]
    ) -> None:
        """baseline no-diff 空集形态过 DiffSection 校验 (SC-4 专属 fixture)。"""
        seg = diffseg.build_diff_segment(_plan(baseline_run=True))
        errors = mini_validate(self._enriched_section(seg), diff_node, root=schema)
        assert errors == [], "\n".join(errors)

    def test_enriched_negative_unknown_field_rejected(
        self, schema: dict[str, Any], diff_node: dict[str, Any]
    ) -> None:
        """负向 (有牙齿): diff 段私加未知字段 ⇒ 封闭键集拒绝。"""
        seg = diffseg.build_diff_segment(_plan(new=["A#1"], reclassify=["A#1"]))
        enriched = self._enriched_section(seg)
        enriched["drift_next_page"] = "R#5"
        errors = mini_validate(enriched, diff_node, root=schema)
        assert any("additional property" in e for e in errors), errors

    def test_enriched_negative_drift_entry_missing_from_rejected(
        self, schema: dict[str, Any], diff_node: dict[str, Any]
    ) -> None:
        """负向 (有牙齿): DriftEntry 缺必填 from ⇒ 校验报错 (反事实: 若
        mini_validate 恒绿则本组正/负断言循环自证)。"""
        seg = diffseg.build_diff_segment(_plan(reclassify=["A#1"]))
        enriched = self._enriched_section(seg)
        del enriched["drift"][0]["from"]
        errors = mini_validate(enriched, diff_node, root=schema)
        assert any("required property 'from'" in e for e in errors), errors


# ── 7. 集成: 真 plan_tier_a 三轮管线 ─────────────────────────────────────────


class TestPipelineIntegration:
    def test_three_round_incremental_pipeline(self) -> None:
        """incremental → diffseg 端到端: baseline 轮 / 全复用轮 (空漂移面 +
        assessed_keys 注入形态) / taxonomy 升级全量重评轮 (drift = 全体)。"""
        issues = [
            _issue("Aria", n, f"[缺陷] issue {n}") for n in (1, 2, 3)
        ]
        engine = incremental.IncrementalEngine()
        faces = fingerprint.fingerprint_issues(issues)
        hash_v1 = tier_a.taxonomy_hash(TAXONOMY_V1)
        hash_v2 = tier_a.taxonomy_hash(TAXONOMY_V2)
        assert hash_v1 != hash_v2
        classified_v1 = tier_a.classify(issues, TAXONOMY_V1, NOW)
        all_keys = ["Aria#1", "Aria#2", "Aria#3"]

        # Round 1: 无 state ⇒ baseline (no-diff 空集)
        plan1 = engine.plan_tier_a({}, faces, classified_v1, hash_v1)
        assert plan1["baseline_run"] is True
        seg1 = diffseg.build_diff_segment(plan1)
        assert seg1["new"] == [] and seg1["drift"] == [] and seg1["baseline_run"] is True

        state1 = engine.build_next_state(
            {}, plan1, faces, classified_v1, hash_v1, CTX_FP, PROVENANCE
        )

        # Round 2: 逐字复用 ⇒ drift 空 (复用不是重评); assessed_keys 点名
        # 一个 reused 键 (Tier B stale 重评形态) ⇒ 恰该键入 drift
        plan2 = engine.plan_tier_a(state1, faces, classified_v1, hash_v1)
        assert plan2["reused"] == all_keys and plan2["reclassify"] == []
        seg2 = diffseg.build_diff_segment(plan2)
        assert seg2 == {
            "new": [],
            "closed": [],
            "drift": [],
            "baseline_run": False,
            "drift_truncated": False,
            "drift_total": 0,
        }
        seg2b = diffseg.build_diff_segment(plan2, assessed_keys=["Aria#2"])
        assert seg2b["drift"] == ["Aria#2"] and seg2b["drift_total"] == 1

        # Round 3: taxonomy 升级 (裁定-1: 规则变化不许吃旧结论) ⇒ 全量重评
        classified_v2 = tier_a.classify(issues, TAXONOMY_V2, NOW)
        plan3 = engine.plan_tier_a(state1, faces, classified_v2, hash_v2)
        assert plan3["reclassify"] == all_keys and plan3["reused"] == []
        seg3 = diffseg.build_diff_segment(plan3)
        assert seg3["baseline_run"] is False
        assert seg3["new"] == [] and seg3["closed"] == []
        assert seg3["drift"] == all_keys
        assert seg3["drift_truncated"] is False and seg3["drift_total"] == 3

    def test_closed_issue_diff_face_from_engine_plan(self) -> None:
        """集合差面经真引擎: 本轮少一条 (Aria#3 已关) ⇒ closed 直通 + 不入
        漂移候选 (域外交集剪除)。"""
        issues = [_issue("Aria", n, f"[缺陷] issue {n}") for n in (1, 2)]
        engine = incremental.IncrementalEngine()
        faces = fingerprint.fingerprint_issues(issues)
        hash_v1 = tier_a.taxonomy_hash(TAXONOMY_V1)
        classified = tier_a.classify(issues, TAXONOMY_V1, NOW)

        plan1 = engine.plan_tier_a({}, faces, classified, hash_v1)
        full_issues = [_issue("Aria", n, f"[缺陷] issue {n}") for n in (1, 2, 3)]
        full_faces = fingerprint.fingerprint_issues(full_issues)
        full_classified = tier_a.classify(full_issues, TAXONOMY_V1, NOW)
        plan_full = engine.plan_tier_a({}, full_faces, full_classified, hash_v1)
        state_full = engine.build_next_state(
            {}, plan_full, full_faces, full_classified, hash_v1, CTX_FP, PROVENANCE
        )

        plan_now = engine.plan_tier_a(state_full, faces, classified, hash_v1)
        assert plan_now["closed"] == ["Aria#3"]
        seg = diffseg.build_diff_segment(plan_now)
        assert seg["closed"] == ["Aria#3"]
        assert "Aria#3" not in seg["drift"]

"""TASK-007 — SC-1 增量状态 10+1 态 fixture 矩阵 (spec issue-groomer-p1-mvp).

验收面: proposal SC-1「10 态矩阵 + 第 11 态 (并发: 两文件各自
last-writer-wins, 裁定④) 全绿且逐态反事实成立 + 分量级 mandate 全绿
(③ 四分量 / ⑨ 两分量 / ⑩ comment-edit 判别 + 合成样本)」; 十态枚举 =
DEC-20261018-001 裁定-9 v3 (主仓 .aria/decisions/ §裁定-9)。

矩阵形态: 每态走**完整两 (三) 轮引擎流** (load_state → fingerprint →
classify → context_fingerprint → plan_tier_a → build_next_state →
save_state — 与 scripts/groom.py 编排同序), 不是孤立函数单测 (那是
test_incremental.py / test_fingerprint.py 的领地; 本文件与其互补, 锚点
常量同源)。轮间 state 经磁盘重载 (真持久化路径)。

反事实纪律 (SC-1 逐态 mandate): 每个测试方法 docstring 含一句
「机制退化成常量时本态为何必红」— 任一指纹分量 / 复用门输入退化为
常量 (或被错误代理替代) 时, 对应态的断言必须失败, 不许恒绿。

fixture 形态 (裁定-7 防形态脱节): 基线 issue 行与 comment 行**逐字取自**
2026-10-18 真语料 (scratchpad 快照三件套; 见 CORPUS_* 常量与
TestCorpusAnchorFreshness 的 live 交叉核对 — 语料在场时验证嵌入常量
未与真语料漂移)。comment-edit 判别样本经 fixtures/corpus_loader.py 的
synth_comment_set / with_synthetic_edit 合成 (updated_at > created_at,
编辑落在最老评论上 — count / max(created_at) / 最新行三类错误代理全部
失明的判别位形)。

注入面全用: tempdir project root (openspec 树 + handoff latest.md +
.aria/)/ 注入 now_fn / 注入 git_head_fn / 注入 taxonomy dict — 零真盘
依赖、零真 git 依赖、零 flaky 时钟。

③ 态语义边界 (DEC 裁定-9 主控裁决语义修正后, 如实钉死): 上下文变化
**分层消费** — **Tier A 免**: 上下文面前三分量 (openspec / git HEAD /
handoff pointer) 不是 Tier A 复用门输入, incremental.py 健全性论证:
tier_a.classify 输入面 ⊆ issue_key ∪ judgement_inputs (taxonomy_hash
是唯一入 judgement_inputs 的上下文分量), 上下文其余分量数学上不可能
改变 Tier A 分类 ⇒ ③a/③b/③c 的 Tier A plan 断言 = 维持 reused (分层
属性钉进矩阵)。**Tier B 全量 stale**: 评估落档于旧上下文 (assessment
entry.context_key ≠ 本轮 fingerprint.context_key) ⇒ context-changed
(「上下文一变 ⇒ 全量重评」的实现形态 — 引擎只诚实标 stale, 重评由适配
层做; plugin#110 类静默陈旧: issue 本体未动、spec ship 后评估翻转,
由此封堵)。③a/③b/③c 断言面 = 指纹层单分量敏感 + 变化持久进 last_run
+ Tier B 门全量 context-changed + Tier A plan 维持 reused; ③d 断言 =
reclassify (裁定-1 规则变化不许吃旧结论 — taxonomy_hash 入判据输入)。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TESTS_DIR.parent / "scripts"
_FIXTURES_DIR = _TESTS_DIR / "fixtures"
for _p in (str(_SCRIPTS_DIR), str(_FIXTURES_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lib import fingerprint, incremental, tier_a  # noqa: E402
import corpus_loader as cl  # noqa: E402

_HAS_CORPUS = all(
    (cl.DEFAULT_CORPUS_DIR / name).is_file()
    for name in (cl.FULL_FILENAME, cl.CURATED_FILENAME, cl.SAMPLE_FILENAME)
)
requires_corpus = pytest.mark.skipif(
    not _HAS_CORPUS,
    reason="scratchpad corpus trio absent (accepted single-point risk; spec "
           "issue-groomer-p1-mvp) — regenerate with: python3 "
           "aria/skills/issue-groomer/scripts/regen_corpus.py --date 2026-10-18",
)


# ------------------------------------------------------------- 语料真形态锚点
# 逐字取自 scratchpad/issues-open-2026-10-18.json (curated 150 行) 与
# scratchpad/issues-sample-body-comments-2026-10-18.json。
# TestCorpusAnchorFreshness 在语料在场时逐字段交叉核对这组常量。

CORPUS_ROW_ARIA233 = {
    "repo": "Aria", "number": 233,
    "title": "[Layer L] 长会话里的在制 claim 会被对方例行收尾的 "
             "--sweep-stale 永久标成 abandoned, 原持有方只收到 benign 的 "
             "claim_not_found",
    "labels": [], "created": "2026-10-15", "updated": "2026-10-15", "comments": 1,
}
CORPUS_ROW_ARIA236 = {
    "repo": "Aria", "number": 236,
    "title": "[archived] pre-merge-completeness-gate-change-scope 归档跟踪 "
             "(10CG/Aria#199, v1.76.0)",
    "labels": [], "created": "2026-10-17", "updated": "2026-10-17", "comments": 0,
}
CORPUS_ROW_PLUGIN110 = {
    "repo": "aria-plugin", "number": 110,
    "title": "[state-scanner] sync_status 撒谎: 陈旧 remote-tracking ref 下报 "
             "parity=equal / overall_parity=true (十步循环统一入口的假绿)",
    "labels": [], "created": "2026-07-12", "updated": "2026-09-30", "comments": 3,
}
CORPUS_COMMENT_ARIA233 = {
    "id": 28794, "created_at": "2026-10-15T16:58:30Z",
    "updated_at": "2026-10-15T16:58:30Z", "body_len": 9033,
}
CORPUS_COMMENTS_PLUGIN110 = [
    {"id": 15789, "created_at": "2026-07-15T01:16:25Z",
     "updated_at": "2026-07-15T01:16:25Z", "body_len": 561},
    {"id": 16240, "created_at": "2026-07-19T15:10:51Z",
     "updated_at": "2026-07-19T15:10:51Z", "body_len": 1368},
    {"id": 27451, "created_at": "2026-09-30T22:19:30Z",
     "updated_at": "2026-09-30T22:19:30Z", "body_len": 16374},
]

# 注入 taxonomy (过 tier_a SC-9; 不读盘 — 与 test_incremental.py 同锚)。
TAXONOMY_V1 = {
    "version": 1,
    "categories": {"bug": "kind/bug", "feature": "kind/feature"},
    "title_prefixes": {"[缺陷]": "bug", "[feature]": "feature"},
    "label_signals": {"kind/bug": "bug", "kind/feature": "feature"},
}
TAXONOMY_V2 = {  # 规则升级: 新增 docs 分类 ⇒ taxonomy_hash 变
    "version": 1,
    "categories": {"bug": "kind/bug", "feature": "kind/feature", "docs": "kind/docs"},
    "title_prefixes": {"[缺陷]": "bug", "[feature]": "feature", "[docs]": "docs"},
    "label_signals": {"kind/bug": "bug", "kind/feature": "feature", "kind/docs": "docs"},
}

PROVENANCE = {"harness": "claude-code", "model_id": "glm-5.2"}     # 本仓 Layer 2 实况
PROVENANCE_HARNESS_FLIP = {"harness": "cursor", "model_id": "glm-5.2"}
PROVENANCE_MODEL_FLIP = {"harness": "claude-code", "model_id": "gpt-x"}

GIT_SHA_A = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
GIT_SHA_B = "f6e5d4c3b2a1f6e5d4c3b2a1f6e5d4c3b2a1f6e5"

# 时钟锚点 (全注入; staleness 档以基线 updated=2026-10-15 计):
#   NOW_0      10-19T12:00Z → age 4d  "<7d"
#   NOW_TOUCH  10-21T12:00Z → age 6d  "<7d"  (同档不同戳 — 复用不刷新时间戳的判别位形)
#   NOW_CROSS  10-25T12:00Z → age 10d "7-30d" (跨档)
#   NOW_REOPEN 10-19T15:00Z → age 4d  "<7d"
NOW_0 = datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)
NOW_TOUCH = datetime(2026, 10, 21, 12, 0, 0, tzinfo=timezone.utc)
NOW_CROSS = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
NOW_REOPEN = datetime(2026, 10, 19, 15, 0, 0, tzinfo=timezone.utc)

_BODY_V1 = "issue-groomer P1 matrix fixture body v1 (anchor: Aria#233 corpus row)"


def _aria233(**overrides):
    """基线 issue = Aria#233 真语料行 + fetch 归一超集字段 (face 五键全覆盖)。"""
    base = {
        **CORPUS_ROW_ARIA233,
        "comments_count": CORPUS_ROW_ARIA233["comments"],
        "body": _BODY_V1,
        "comments": [dict(CORPUS_COMMENT_ARIA233)],
        "comments_error": None,
    }
    base.update(overrides)
    return base


def _aria236(**overrides):
    base = {
        **CORPUS_ROW_ARIA236,
        "comments_count": CORPUS_ROW_ARIA236["comments"],
        "body": _BODY_V1,
        "comments": [],  # 语料 comments=0 ⇒ 零评论 (face 三态的 None 态)
        "comments_error": None,
    }
    base.update(overrides)
    return base


def _plugin110(**overrides):
    base = {
        **CORPUS_ROW_PLUGIN110,
        "comments_count": CORPUS_ROW_PLUGIN110["comments"],
        "body": _BODY_V1,
        "comments": [dict(c) for c in CORPUS_COMMENTS_PLUGIN110],
        "comments_error": None,
    }
    base.update(overrides)
    return base


def _only_these_keys_differ(before: dict, after: dict, expected: list[str]) -> None:
    """分量纪律断言体: before/after 恰在 expected 键上不同, 其余逐键相等。"""
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    assert changed == sorted(expected), (
        f"expected exactly {sorted(expected)} to differ, got {changed} "
        f"(before={before}, after={after})"
    )


def _assert_only_face_field_changed(face1: dict, face2: dict, field: str) -> None:
    """issue 面四分量纪律: 恰恰 field 变了, 其余三分量不变。"""
    _only_these_keys_differ(face1, face2, [field])


class _GroomRig:
    """两轮状态机 rig: tempdir project root + 全注入 (now/git_head/taxonomy)
    + 与 groom.py 同序的完整编排。engine 持真实 state 路径与真实
    assessments reader (default_assessments_reader — 只读闭包)。"""

    def __init__(self, root: Path):
        self.root = root
        self.state_path = root / ".aria" / "cache" / "groom-state.json"
        self.assessments_path = root / ".aria" / "groom-assessments.json"
        # 上下文面的可注入素材 (③ 态在此逐分量变异)
        spec_dir = root / "openspec" / "changes" / "spec-matrix"
        spec_dir.mkdir(parents=True)
        (spec_dir / "proposal.md").write_text("baseline proposal body\n", encoding="utf-8")
        handoff_dir = root / "docs" / "handoff"
        handoff_dir.mkdir(parents=True)
        (handoff_dir / "latest.md").write_text(
            "# handoff\n\n**Latest**: [cycle 118](./2026-10-18-118-matrix.md)\n",
            encoding="utf-8",
        )
        self.now = NOW_0
        self.git_head = GIT_SHA_A
        self.taxonomy = TAXONOMY_V1
        self.engine = incremental.IncrementalEngine(
            self.state_path,
            assessments_reader=incremental.default_assessments_reader(root),
            now_fn=lambda: self.now,
        )

    def context(self) -> dict:
        return fingerprint.context_fingerprint(
            self.root,
            git_roots=[self.root],
            git_head_fn=lambda _gr: self.git_head,
            taxonomy=self.taxonomy,
        )

    def run(self, issues: list[dict], *, save: bool = True) -> dict:
        """一轮完整流 (load → fingerprint → classify → context → plan →
        gate → build → save); 轮首 state 从磁盘重载 (真持久化路径)。"""
        prev_state, baseline = self.engine.load_state()
        faces = fingerprint.fingerprint_issues(issues)
        classified = tier_a.classify(list(issues), self.taxonomy, self.now)
        ctx = self.context()
        tax_hash = ctx["taxonomy_hash"]
        plan = self.engine.plan_tier_a(prev_state, faces, classified, tax_hash)
        # 上下文门与 groom.py 同接线 (DEC 裁定-9): context_key 来自本轮 ctx。
        gate = self.engine.gate_tier_b(
            PROVENANCE, current_keys=faces.keys(),
            context_key=fingerprint.context_key(ctx),
        )
        next_state = self.engine.build_next_state(
            prev_state, plan, faces, classified, tax_hash, ctx, PROVENANCE
        )
        if save:
            self.engine.save_state(next_state)
        return {
            "prev_state": prev_state, "baseline": baseline, "faces": faces,
            "plan": plan, "gate": gate, "next_state": next_state, "ctx": ctx,
        }


def _write_assessments(rig: _GroomRig, entries: dict) -> None:
    """模拟适配层 (TASK-010, 唯一写者) 写 groom-assessments.json。"""
    rig.assessments_path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"schema_version": 1, "assessments": entries}
    rig.assessments_path.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _assessment_entry(harness="claude-code", model_id="glm-5.2",
                      created_at="2026-10-18T08:30:00Z", context_key=None) -> dict:
    """适配层评估条目。``context_key`` 缺省不带 (v1 旧档形 — 上下文门关闭
    场景/⑨ provenance 系沿用); 传入即写入 (DEC 裁定-9 契约必填键)。"""
    entry = {
        "verdict_priorities": [{"from": "P2", "to": "P3", "rationale": "…"}],
        "suspected_fixed": {"verdict": False, "rationale": "…"},
        "provenance": {"harness": harness, "model_id": model_id},
        "created_at": created_at,
    }
    if context_key is not None:
        entry["context_key"] = context_key
    return entry


# ════════════════════════════════════ ① 新条目 ═══════════════════════════════

class TestState01NewEntry:
    """① 新条目: state 无此键 → new + reclassify (reclassify ⊇ new)。

    反事实: 若「首见检测」退化成常量 (prev 查询恒命中 / new 恒空 — 例如
    复用门误把未知键当 reused), 则 new == [] 断言必红; 若 reclassify 不
    吸收 new, assertIn 断言必红。
    """

    def test_state_absent_key_is_new_and_reclassified(self, tmp_path):
        rig = _GroomRig(tmp_path)
        r1 = rig.run([_aria233()])
        assert r1["plan"]["baseline_run"] is True
        assert r1["plan"]["new"] == ["Aria#233"]
        assert r1["plan"]["reclassify"] == ["Aria#233"]
        r2 = rig.run([_aria233(), _aria236()])
        assert r2["plan"]["baseline_run"] is False
        assert r2["plan"]["new"] == ["Aria#236"]          # state 无此键
        assert r2["plan"]["reused"] == ["Aria#233"]       # 既有条目不受牵连
        assert "Aria#236" in r2["plan"]["reclassify"]     # new ⊆ reclassify
        assert r2["plan"]["closed"] == []
        assert sorted(r2["next_state"]["issues"]) == ["Aria#233", "Aria#236"]


# ════════════════════════════════════ ② 未变 ════════════════════════════════

class TestState02Unchanged:
    """② 未变: 同 issue_key 同判据输入 → reused, 条目逐字续传 (时间戳不刷新)。

    反事实: 若复用门退化成「恒重分类」(judgement_inputs 比较失效), reused
    == [] 必红; 若复用实现错误地刷新 last_classified_at (复用≠重新分类),
    时间戳等于 NOW_TOUCH 戳的断言必红。
    """

    def test_identical_round_reuses_and_preserves_timestamp(self, tmp_path):
        rig = _GroomRig(tmp_path)
        r1 = rig.run([_aria233()])
        rig.now = NOW_TOUCH  # 同档推进时钟 — 复用不许刷新时间戳
        r2 = rig.run([_aria233()])
        assert r2["plan"]["reused"] == ["Aria#233"]
        assert r2["plan"]["reclassify"] == []
        assert r2["plan"]["new"] == []
        assert r2["plan"]["closed"] == []
        # 逐字续传: r2 条目与 r1 逐字节相等 (含 last_classified_at = NOW_0 戳)
        assert (json.dumps(r2["next_state"]["issues"]["Aria#233"], sort_keys=True)
                == json.dumps(r1["next_state"]["issues"]["Aria#233"], sort_keys=True))
        assert r2["next_state"]["issues"]["Aria#233"]["last_classified_at"] \
            == "2026-10-19T12:00:00Z"


# ═══════════════════════════════════ ③ 上下文变 ═════════════════════════════

class TestState03ContextChange:
    """③ 上下文变 — 分量级 mandate: 四分量各设独立变体, 每个只动一个分量。

    分层语义 (DEC 裁定-9, 见模块 docstring): Tier A 免 (分类输入 ⊆
    issue_key ∪ judgement_inputs — 上下文其余分量数学上不可能改变分类);
    Tier B 全量 stale (评估落档于旧上下文 ⇒ context-changed, 重评由适配层做)。

    反事实 (逐分量): 若 openspec_changes_hash / git_heads / handoff_pointer /
    taxonomy_hash 任一分量退化为常量 (恒空树 hash / 恒 None / 恒固定指针 /
    恒内置层 hash), 对应变体的「恰一分量不同」断言必红 (变为零分量不同);
    若上下文门退化成恒放行 (比对被删/缺键被当匹配), 对应变体的
    context-changed 断言必红 (Tier B 静默陈旧复活 = #110); ③d 若
    taxonomy_hash 不入 judgement_inputs, reclassify 断言必红。
    """

    def _seed_assessed_rig(self, tmp_path, keys):
        """r1 建档 + 评估落档于 r1 上下文 (context_key = r1 ctx 指纹);
        返回 (rig, r1)。前提自证: 同上下文门下全部 reusable。"""
        rig = _GroomRig(tmp_path)
        r1 = rig.run(list(keys.values()))
        _write_assessments(rig, {
            k: _assessment_entry(context_key=fingerprint.context_key(r1["ctx"]))
            for k in keys
        })
        premise = rig.engine.gate_tier_b(
            PROVENANCE, current_keys=list(keys),
            context_key=fingerprint.context_key(r1["ctx"]),
        )
        assert premise["reusable"] == sorted(keys)  # 前提钉死: 旧上下文可复用
        assert premise["stale"] == {}
        return rig, r1

    def _assert_context_flip(self, r1, r2, component, key="Aria#233"):
        """分量级 + 分层纪律的公共断言体。"""
        _only_these_keys_differ(r1["ctx"], r2["ctx"], [component])
        # 变化持久进下一轮 state (last_run 全量 + 便捷单键)
        assert r2["next_state"]["last_run"]["context_fingerprint"] == r2["ctx"]
        assert (r2["next_state"]["last_run"]["context_key"]
                == fingerprint.context_key(r2["ctx"]))
        # key 层分量敏感: 恰一分量变 ⇒ context_key 必变 (门判变的前提面)
        assert (fingerprint.context_key(r1["ctx"])
                != fingerprint.context_key(r2["ctx"]))
        # Tier B: 评估落档于旧上下文 ⇒ 全量 stale (context-changed) —
        # DEC 裁定-9「上下文一变 ⇒ 全量重评」的引擎侧实现形态。
        assert r2["gate"]["reusable"] == []
        assert r2["gate"]["stale"] == {key: "context-changed"}
        assert r2["gate"]["orphaned"] == []
        # Tier 分层: Tier A 免 — 分类输入不含该分量 ⇒ plan 维持 reused
        # (裁定-9 精确语义; 未来把上下文变化接进 Tier A 重评须先改 DEC/引擎,
        # 本矩阵此时变红)。
        assert r2["plan"]["reused"] == [key]
        assert r2["plan"]["reclassify"] == []

    def test_03a_openspec_changes_hash_variant(self, tmp_path):
        rig, r1 = self._seed_assessed_rig(tmp_path, {"Aria#233": _aria233()})
        (rig.root / "openspec" / "changes" / "spec-matrix" / "proposal.md").write_text(
            "baseline proposal body\namended: in-flight spec revised\n", encoding="utf-8"
        )
        r2 = rig.run([_aria233()])
        self._assert_context_flip(r1, r2, "openspec_changes_hash")

    def test_03b_git_head_variant(self, tmp_path):
        rig, r1 = self._seed_assessed_rig(tmp_path, {"Aria#233": _aria233()})
        rig.git_head = GIT_SHA_B  # 注入 git_head_fn — 只动 git_heads 分量
        r2 = rig.run([_aria233()])
        self._assert_context_flip(r1, r2, "git_heads")

    def test_03c_handoff_pointer_variant(self, tmp_path):
        rig, r1 = self._seed_assessed_rig(tmp_path, {"Aria#233": _aria233()})
        (rig.root / "docs" / "handoff" / "latest.md").write_text(
            "# handoff\n\n**Latest**: [cycle 119](./2026-10-19-119-matrix.md)\n",
            encoding="utf-8",
        )
        r2 = rig.run([_aria233()])
        assert r2["ctx"]["handoff_pointer"] == "2026-10-19-119-matrix.md"
        self._assert_context_flip(r1, r2, "handoff_pointer")

    def test_03c2_missing_context_key_old_archive_stale(self, tmp_path):
        """③ 附属: v1 旧档形 (entry 无 context_key 键) 在门激活 ⇒
        context-missing (fail-closed) — 与 context-changed 结构可区分。"""
        rig = _GroomRig(tmp_path)
        rig.run([_aria233()])
        _write_assessments(rig, {"Aria#233": _assessment_entry()})  # 无 context_key
        r2 = rig.run([_aria233()])  # 上下文未变, 但条目缺键 ⇒ fail-closed
        assert r2["gate"]["reusable"] == []
        assert r2["gate"]["stale"] == {"Aria#233": "context-missing"}

    def test_03d_taxonomy_hash_variant_reclassifies(self, tmp_path):
        rig = _GroomRig(tmp_path)
        r1 = rig.run([_aria233()])
        ctx1 = r1["ctx"]
        rig.taxonomy = TAXONOMY_V2  # 规则升级 — 唯一动 taxonomy_hash 分量
        r2 = rig.run([_aria233()])
        _only_these_keys_differ(ctx1, r2["ctx"], ["taxonomy_hash"])
        # taxonomy_hash 入 judgement_inputs (裁定-1: 规则变化不许吃旧结论)
        # ⇒ 全量重分类 — 即使分类输出未变 (category 两轮都 unknown,
        # SC-4「判据输入变而分类输出同 ⇒ 重分类不复用」的矩阵实例)。
        assert r2["plan"]["reused"] == []
        assert r2["plan"]["reclassify"] == ["Aria#233"]


# ═══════════════════════════════════ ④ 已关闭 ═══════════════════════════════

class TestState04Closed:
    """④ 已关闭: 键从本轮集合消失 → closed; 下一轮 state 不再持有该键。

    反事实: 若 closed 检测退化 (prev−current 差集失效为常量空集), closed
    == ["Aria#236"] 必红; 若 build_next_state 不丢弃 closed 键, issues 键集
    断言必红。
    """

    def test_disappearing_key_is_closed_and_dropped(self, tmp_path):
        rig = _GroomRig(tmp_path)
        rig.run([_aria233(), _aria236()])
        r2 = rig.run([_aria233()])  # 236 本轮缺席 (已关闭)
        assert r2["plan"]["closed"] == ["Aria#236"]
        assert r2["plan"]["new"] == []
        assert r2["plan"]["reused"] == ["Aria#233"]
        assert sorted(r2["next_state"]["issues"]) == ["Aria#233"]  # closed 键出局


# ═══════════════════════════════ ⑤ 关闭后重开 ═══════════════════════════════

class TestState05Reopened:
    """⑤ 关闭后重开: closed 之后同键再现 → 走 new 路径重评, 不恢复旧记录
    (DEC 裁定-9 ⑤ 钉死语义)。

    反事实: 若引擎在任何位置保留了 closed 键的历史 (复活旧条目而非重评),
    new == ["Aria#236"] 必红且 last_classified_at 会等于 r1 旧戳 — 两条断言
    都红。
    """

    def test_reopened_key_walks_new_path_with_fresh_record(self, tmp_path):
        rig = _GroomRig(tmp_path)
        rig.run([_aria233(), _aria236()])              # r1: 两键在册
        rig.run([_aria233()])                          # r2: 236 closed, state 丢键
        rig.now = NOW_REOPEN                           # r3: 236 重开 (内容与 r1 全同)
        r3 = rig.run([_aria233(), _aria236()])
        assert r3["plan"]["new"] == ["Aria#236"]       # new 路径, 非 reused
        assert "Aria#236" not in r3["plan"]["reused"]
        assert "Aria#236" in r3["plan"]["reclassify"]
        assert r3["plan"]["reused"] == ["Aria#233"]    # 未关条目不受牵连
        # 不恢复旧记录: 新条目时间戳 = r3 时钟, 不是 r1 的 NOW_0 戳
        assert r3["next_state"]["issues"]["Aria#236"]["last_classified_at"] \
            == "2026-10-19T15:00:00Z"


# ═══════════════════════════ ⑥ 编辑但内容等价 ═══════════════════════════════

class TestState06EditContentEquivalent:
    """⑥ 编辑但内容等价: updated_at 变而 title/body/labels/comments 不变
    (同 staleness 档) → issue_key 不变 → 复用。附 ⑥b: 显式排除字段
    (assignee/milestone/due_date) 编辑 → 指纹面结构上不读 → 复用
    (DEC 裁定-9 显式排除集的负向镜像 fixture)。

    反事实 (⑥a): 若 updated 被误读入 issue 面 (排除面破缺), issue_key 变 ⇒
    reused 断言红; 若复用门漏比 judgement_inputs, ⑥a 仍绿 (同档) — 该轴由
    ⑧ 钉。反事实 (⑥b): 若指纹读取面扩到排除字段, face 变 ⇒ reused 红。
    """

    def test_06a_updated_at_shift_within_tier_reuses(self, tmp_path):
        rig = _GroomRig(tmp_path)
        r1 = rig.run([_aria233()])                     # updated=2026-10-15, age 4d
        touched = _aria233(updated="2026-10-17")       # 触碰: age 2d, 同 "<7d" 档
        r2 = rig.run([touched])
        # 前提钉死: issue 面 (title/body/labels/comments) 逐分量未变
        assert r2["faces"]["Aria#233"] == r1["faces"]["Aria#233"]
        assert r2["plan"]["reused"] == ["Aria#233"]
        assert r2["plan"]["reclassify"] == []

    def test_06b_excluded_field_edit_reuses(self, tmp_path):
        rig = _GroomRig(tmp_path)
        r1 = rig.run([_aria233()])
        edited = _aria233(assignee="simonfishgit", milestone="v1.8.0",
                          due_date="2026-11-01")        # 裁定-9 显式排除三字段
        r2 = rig.run([edited])
        assert r2["faces"]["Aria#233"] == r1["faces"]["Aria#233"]  # 面逐字不变
        assert r2["plan"]["reused"] == ["Aria#233"]
        assert r2["plan"]["reclassify"] == []


# ═══════════════════════ ⑦ rebase 后 updated_at 平移 ════════════════════════

class TestState07RebaseUpdatedShift:
    """⑦ rebase 后 updated_at 变但内容同 → 复用 (updated_at 不入指纹)。
    rebase 位形 = 日期整体大幅平移 (跨多日), 与 ⑥ 的「触碰」区分;
    平移保持同 staleness 档 (跨档属 ⑧ 的合法触发, 不在本态)。

    反事实: 若 updated 入 issue 面, 大幅平移即变 key ⇒ reused 红; 结构性
    断言 (任意幅度 updated 值同 key) 在任何「部分读入」实现下必红。
    """

    def test_wholesale_date_shift_same_tier_reuses(self, tmp_path):
        rig = _GroomRig(tmp_path)
        # 09-15 → 09-10: age 34d → 39d, 同 "30-90d" 档 (rebase 平移位形)
        r1 = rig.run([_aria233(updated="2026-09-15")])
        r2 = rig.run([_aria233(updated="2026-09-10")])
        assert r2["faces"]["Aria#233"] == r1["faces"]["Aria#233"]
        assert r2["plan"]["reused"] == ["Aria#233"]
        assert r2["plan"]["reclassify"] == []
        # 结构性: updated 任意幅度 (跨档幅度也行) 都不进 issue_key —
        # issue_face 读取面封闭为五键, updated 结构上不被读。
        for wild_updated in ("2001-01-01", "2099-12-31"):
            face = fingerprint.issue_face(_aria233(updated=wild_updated))
            assert fingerprint.combined_issue_key(face) \
                == fingerprint.combined_issue_key(r1["faces"]["Aria#233"])


# ═══════════════════════ ⑧ 时间敏感字段跨档 ═════════════════════════════════

class TestState08TimeTierCrossing:
    """⑧ 时间敏感字段跨档: 注入 now 使 staleness 档变 (<7d → 7-30d) →
    重分类, 即使 issue_key 不变 (DEC 裁定-9: 判据输入含时间敏感字段,
    跨档即触发 — 纯时钟流逝场景)。

    反事实: 若 staleness 档被排除出 judgement_inputs (快照退化成常量),
    r2 会误判 reused ⇒ reclassify == [...] 断言必红 (误复用 = 契约侵蚀)。
    """

    def test_clock_crossing_tier_reclassifies_despite_identical_issue(self, tmp_path):
        rig = _GroomRig(tmp_path)
        r1 = rig.run([_aria233()])                     # now=NOW_0 ⇒ "<7d"
        rig.now = NOW_CROSS                            # age 10d ⇒ "7-30d"
        r2 = rig.run([_aria233()])                     # issue 逐字节未动
        # 前提钉死: 跨档场景下 issue_key 确实未变 (纯判据输入轴触发)
        assert r2["faces"]["Aria#233"] == r1["faces"]["Aria#233"]
        assert (r1["next_state"]["issues"]["Aria#233"]["judgement_inputs"]
                ["staleness_tier"]) == "<7d"
        assert r2["plan"]["reused"] == []
        assert r2["plan"]["reclassify"] == ["Aria#233"]
        # 重分类后的 state 记录新档 (下一轮同 now 复用)
        assert r2["next_state"]["issues"]["Aria#233"]["judgement_inputs"][
            "staleness_tier"] == "7-30d"


# ═══════════════════════════ ⑨ provenance 变 ════════════════════════════════

class TestState09ProvenanceChange:
    """⑨ provenance 变 — 分量级 mandate: harness 与 model_id 各设独立变体,
    各自单独翻转 → Tier B 门 stale (fail-closed, 杜绝跨 harness 静默复用)。

    反事实: 若复用门只比 harness (model_id 分量退化掉), ⑨b 会误判
    reusable ⇒ stale 断言红; 只比 model_id 则 ⑨a 红; 拼接串退化为常量则
    两变体全红。
    """

    ENTRY_KEYS = ["Aria#233", "aria-plugin#110"]

    def _seeded_rig(self, tmp_path):
        rig = _GroomRig(tmp_path)
        rig.run([_aria233(), _plugin110()])            # r1: state 建档
        _write_assessments(rig, {k: _assessment_entry() for k in self.ENTRY_KEYS})
        return rig

    def test_09a_harness_variant_makes_all_stale(self, tmp_path):
        rig = self._seeded_rig(tmp_path)
        base = rig.engine.gate_tier_b(PROVENANCE, current_keys=self.ENTRY_KEYS)
        assert base["reusable"] == self.ENTRY_KEYS     # 前提: 基线可复用
        flipped = rig.engine.gate_tier_b(
            PROVENANCE_HARNESS_FLIP, current_keys=self.ENTRY_KEYS
        )
        assert flipped["reusable"] == []
        assert flipped["stale"] == {k: "provenance-mismatch" for k in self.ENTRY_KEYS}
        assert flipped["orphaned"] == []
        # 分量纪律: 恰 harness 一分量翻转 ⇒ 拼接串必变
        assert (fingerprint.combined_provenance_key(PROVENANCE)
                != fingerprint.combined_provenance_key(PROVENANCE_HARNESS_FLIP))

    def test_09b_model_id_variant_makes_all_stale(self, tmp_path):
        rig = self._seeded_rig(tmp_path)
        flipped = rig.engine.gate_tier_b(
            PROVENANCE_MODEL_FLIP, current_keys=self.ENTRY_KEYS
        )
        assert flipped["reusable"] == []
        assert flipped["stale"] == {k: "provenance-mismatch" for k in self.ENTRY_KEYS}
        assert (fingerprint.combined_provenance_key(PROVENANCE)
                != fingerprint.combined_provenance_key(PROVENANCE_MODEL_FLIP))
        # 两变体各自独立翻转, 拼接串两两互异 (分量级 mandate 的完整性)
        assert (fingerprint.combined_provenance_key(PROVENANCE_HARNESS_FLIP)
                != fingerprint.combined_provenance_key(PROVENANCE_MODEL_FLIP))


# ═══════════════════ ⑩ issue 内容面正向 (四子分量) ══════════════════════════

class TestState10IssueFacePositive:
    """⑩ issue 内容面正向 — 四子分量各独立必红: label 人工增删 / title 实质
    编辑 / body 编辑 / comments 最新 updated_at 变。任一发生 ⇒ 必判变触发
    重评 (DEC 裁定-9 ⑩; 与 apply_payload 自写 label 后的下轮判变同 fixture
    覆盖)。附 comment-edit 判别 (合成 updated_at>created_at 样本)。

    反事实 (逐子分量): 若 labels_hash / title_hash / body_hash /
    comments_latest_updated_at 任一分量退化成常量 (或被 count 等代理替代),
    对应变体的 issue_key-变 + reclassify 断言必红 — ⑩ 是四分量各自的
    核心反事实。
    """

    def _assert_reclassified(self, r1, r2, key):
        assert r2["faces"][key] != r1["faces"][key]
        assert (fingerprint.combined_issue_key(r2["faces"][key])
                != fingerprint.combined_issue_key(r1["faces"][key]))
        assert r2["plan"]["reused"] == []
        assert r2["plan"]["reclassify"] == [key]
        assert r2["plan"]["new"] == []   # 已知条目 ⇒ 非 new

    def test_10a_label_add_then_remove(self, tmp_path):
        rig = _GroomRig(tmp_path)
        r1 = rig.run([_aria233()])                          # labels=[] (语料原样)
        r2 = rig.run([_aria233(labels=["kind/bug"])])       # 人工增标
        _assert_only_face_field_changed(
            r1["faces"]["Aria#233"], r2["faces"]["Aria#233"], "labels_hash")
        self._assert_reclassified(r1, r2, "Aria#233")
        r3 = rig.run([_aria233()])                          # 人工删标 (回到空)
        _assert_only_face_field_changed(
            r2["faces"]["Aria#233"], r3["faces"]["Aria#233"], "labels_hash")
        assert r3["plan"]["reused"] == []
        assert r3["plan"]["reclassify"] == ["Aria#233"]

    def test_10b_title_substantive_edit(self, tmp_path):
        rig = _GroomRig(tmp_path)
        r1 = rig.run([_aria233()])
        edited_title = CORPUS_ROW_ARIA233["title"] + " (跟进: sweep-stale 已加 claim 年龄豁免)"
        r2 = rig.run([_aria233(title=edited_title)])
        _assert_only_face_field_changed(
            r1["faces"]["Aria#233"], r2["faces"]["Aria#233"], "title_hash")
        self._assert_reclassified(r1, r2, "Aria#233")

    def test_10c_body_edit(self, tmp_path):
        rig = _GroomRig(tmp_path)
        r1 = rig.run([_aria233()])
        r2 = rig.run([_aria233(body=_BODY_V1 + "\n补充: 复现步骤与 claim TTL 数值。")])
        _assert_only_face_field_changed(
            r1["faces"]["Aria#233"], r2["faces"]["Aria#233"], "body_hash")
        self._assert_reclassified(r1, r2, "Aria#233")

    def test_10d_comments_latest_updated_at_change(self, tmp_path):
        """评论编辑判别位形: 真语料 aria-plugin#110 三评论, 编辑落在**最老**
        评论 (with_synthetic_edit index=0) — count 与 max(created_at) 双双
        不变, 唯 max(updated_at) 变 ⇒ 唯 comments 分量判变。
        """
        rig = _GroomRig(tmp_path)
        r1 = rig.run([_plugin110()])
        edited = cl.with_synthetic_edit(CORPUS_COMMENTS_PLUGIN110, index=0)
        assert len(edited) == len(CORPUS_COMMENTS_PLUGIN110)              # count 不变
        assert (sorted(c["created_at"] for c in edited)
                == sorted(c["created_at"] for c in CORPUS_COMMENTS_PLUGIN110))
        assert (max(c["created_at"] for c in edited)
                == max(c["created_at"] for c in CORPUS_COMMENTS_PLUGIN110))
        r2 = rig.run([_plugin110(comments=edited)])
        _assert_only_face_field_changed(
            r1["faces"]["aria-plugin#110"], r2["faces"]["aria-plugin#110"],
            "comments_latest_updated_at")
        self._assert_reclassified(r1, r2, "aria-plugin#110")
        # 判据输入未变 (comments_count=3 两轮同) — 变化纯由 face 承载
        assert (r1["next_state"]["issues"]["aria-plugin#110"]["judgement_inputs"]
                == r2["prev_state"]["issues"]["aria-plugin#110"]["judgement_inputs"])

    def test_10e_comment_edit_discrimination_synthetic(self, tmp_path):
        """⑩ 分量级 mandate 附属: 合成 updated_at>created_at 样本, 断言引擎
        取 max(updated_at) 而非 max(created_at)/count/最新行错误代理。
        """
        rows = cl.synth_comment_set(n=3, start="2026-10-15T10:00:00Z",
                                    step_s=3600, edit_index=0)
        # 位形自证: 最老评论被编辑, 其 updated_at (13:00) > 所有 created_at
        assert cl.comment_is_edited(rows[0]) is True
        assert not any(cl.comment_is_edited(r) for r in rows[1:])
        face = fingerprint.issue_face(_aria233(comments=rows))
        got = face["comments_latest_updated_at"]
        assert got == max(r["updated_at"] for r in rows)           # 正代理: max(updated_at)
        assert got == rows[0]["updated_at"]                        # 编辑行本身
        assert got != max(r["created_at"] for r in rows)           # 错代理 1: max(created_at)
        assert got != str(len(rows))                               # 错代理 2: count
        # 错代理 3: 「最新行」(未经编辑的行) — rows[-1] 未被编辑, 其 updated_at
        # != 全局 max(updated_at):
        assert rows[-1]["updated_at"] != got
        # 顺序无关: 乱序喂入 face 值不变 (自取 max, 不依赖上游顺序)
        shuffled = [rows[2], rows[0], rows[1]]
        assert fingerprint.issue_face(_aria233(comments=shuffled))[
            "comments_latest_updated_at"] == got


# ═══════════════ ⑪ 并发: 两文件各自 last-writer-wins (裁定④) ════════════════

class TestState11ConcurrentLastWriterWins:
    """⑪ 并发 (裁定④): 两终端 A/B 对同一 state 路径各自整轮计算后先后落盘
    (A 先 B 后) ⇒ state = B 版 (last-writer-wins, 无合并不半文件); 不变量:
    多轮 state 写后 groom-assessments.json **字节不变** (引擎对该文件零写面,
    物理隔离)。两文件**各自** LWW: assessments 自身的末写者胜由适配层写者
    承担, state 文件不因适配层写 assessments 而变。

    反事实: 若引擎对并发写做了任何跨写者合并 (而非整文件替换 — 含「按键
    保留先写者」的冲突安全合并), 最终文件 == B 构建态的**整体相等**断言红
    (B 侧 233 是 reclassify 新条目, 与 A 侧 reused 续传条目逐字节可区分);
    若引擎存在 assessment 写面 (违反裁定④), 字节不变断言红; 若写非原子
    (半文件), valid-JSON 断言红。
    """

    def test_two_writers_state_last_wins_assessments_untouched(self, tmp_path):
        rig = _GroomRig(tmp_path)
        rig.run([_aria233()])                               # 共享基线 (seed)
        _write_assessments(rig, {"Aria#233": _assessment_entry()})
        assessments_before = rig.assessments_path.read_bytes()
        state_path = rig.state_path

        # 终端 A: 基于共享基线计算 (只看 233), 未落盘
        rig.now = NOW_0
        base_a = rig.engine.load_state()[0]
        faces_a = fingerprint.fingerprint_issues([_aria233()])
        classified_a = tier_a.classify([_aria233()], rig.taxonomy, rig.now)
        ctx_a = rig.context()
        plan_a = rig.engine.plan_tier_a(base_a, faces_a, classified_a,
                                        ctx_a["taxonomy_hash"])
        state_a = rig.engine.build_next_state(base_a, plan_a, faces_a, classified_a,
                                              ctx_a["taxonomy_hash"], ctx_a, PROVENANCE)
        # 终端 B: 同一基线 (A 尚未保存 — 并发读), 多看 236 + 233 有新编辑
        # (reclassify 路径 — 使 B 版 233 条目与 A 版逐字节可区分, 「按键合并」
        # 型退化方可检出), 时钟不同。
        rig.now = NOW_TOUCH
        base_b = rig.engine.load_state()[0]                 # 仍读到 seed 版
        edited_233 = _aria233(title=CORPUS_ROW_ARIA233["title"] + " (B 侧新编辑)")
        faces_b = fingerprint.fingerprint_issues([edited_233, _aria236()])
        classified_b = tier_a.classify([edited_233, _aria236()], rig.taxonomy, rig.now)
        ctx_b = rig.context()
        plan_b = rig.engine.plan_tier_a(base_b, faces_b, classified_b,
                                        ctx_b["taxonomy_hash"])
        state_b = rig.engine.build_next_state(base_b, plan_b, faces_b, classified_b,
                                              ctx_b["taxonomy_hash"], ctx_b, PROVENANCE)
        # A 先落盘, B 后落盘
        rig.engine.save_state(state_a)
        assert rig.assessments_path.read_bytes() == assessments_before
        rig.engine.save_state(state_b)
        assert rig.assessments_path.read_bytes() == assessments_before  # 多轮写后字节不变

        final = json.loads(state_path.read_text(encoding="utf-8"))     # 原子性: 恒完整 JSON
        # LWW 全量钉死: 最终文件与 B 构建态**整体相等** (不只是键集 — 233 条目
        # 也是 B 的 reclassify 新条目, 非 A 的 reused 续传条目)。
        assert json.dumps(final, sort_keys=True) == json.dumps(state_b, sort_keys=True)
        assert final["issues"]["Aria#233"] == state_b["issues"]["Aria#233"]
        assert sorted(final["issues"]) == ["Aria#233", "Aria#236"]      # 非 A 版 ({233})
        assert (final["issues"]["Aria#236"]["last_classified_at"]
                == "2026-10-21T12:00:00Z")  # 236 = B 首见 (身份轴, 不依赖 face 敏感度)
        assert list(state_path.parent.glob(f"{state_path.name}.tmp*")) == []

        # 两文件各自 LWW 的另一半: 适配层两次写 assessments (A 后 B) ⇒ B 版;
        # state 文件不因适配层写动作而变一字节。
        state_bytes_before = state_path.read_bytes()
        _write_assessments(rig, {"Aria#233": _assessment_entry()})      # 写者 A
        _write_assessments(rig, {"Aria#233": _assessment_entry(),
                                 "Aria#236": _assessment_entry()})      # 写者 B (最后)
        final_assessments = json.loads(rig.assessments_path.read_text(encoding="utf-8"))
        assert sorted(final_assessments["assessments"]) == ["Aria#233", "Aria#236"]
        assert state_path.read_bytes() == state_bytes_before


# ═════════════════ 语料锚点新鲜度 (裁定-7, 语料在场时核对) ═══════════════════

class TestCorpusAnchorFreshness:
    """嵌入常量 == live 语料 (语料缺席时整类 skip — 再生成命令见 marker)。

    反事实: 若本文件锚点与真语料漂移 (手搓 fixture 形态脱节), 此处必红 —
    裁定-7 防形态脱节的机械守卫。
    """

    @requires_corpus
    def test_embedded_rows_match_live_corpus(self):
        curated = {(r["repo"], r["number"]): r for r in cl.load_curated()}
        for embedded in (CORPUS_ROW_ARIA233, CORPUS_ROW_ARIA236, CORPUS_ROW_PLUGIN110):
            live = curated[(embedded["repo"], embedded["number"])]
            assert live == embedded, (
                f"anchor {(embedded['repo'], embedded['number'])} drifted from live corpus"
            )

    @requires_corpus
    def test_embedded_comments_match_live_corpus(self):
        doc = cl.load_sample()
        assert cl.sample_comments(doc, "Aria", 233) == [CORPUS_COMMENT_ARIA233]
        assert cl.sample_comments(doc, "aria-plugin", 110) == CORPUS_COMMENTS_PLUGIN110

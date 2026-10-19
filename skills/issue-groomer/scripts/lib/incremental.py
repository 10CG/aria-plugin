#!/usr/bin/env python3
"""issue-groomer 增量状态与复用引擎 (P1 MVP, 10CG/Aria#238, TASK-005; 裁定④).

两文件各自 last-writer-wins (裁定④, SC-1 第 11 态):

- ``groom-state.json`` (默认 ``.aria/cache/groom-state.json``, 路径可注入) —
  **本引擎独占读写**的机械状态 (可再生缓存: 删掉重跑即重建)。单一固定路径,
  **原子写** temp+rename (plugin#180 两半教训): 先序列化到内存, 再写同目录
  temp 文件 + fsync, 最后 rename; 任一步失败 ⇒ 删 temp + 上抛, 目标路径只
  可能是「旧内容」或「不存在」, 结构上不落半文件。
- ``groom-assessments.json`` (默认 ``.aria/groom-assessments.json``) — **适配层
  (TASK-010, AI) 独占写**的 Tier B 语义评估。本引擎对它**只读**: 模块内不存在
  任何 assessment 写面 — assessments 在 public API 上只以注入的 reader
  callable 出现 (``IncrementalEngine`` 连它的路径都不持有), ``save_state``
  结构上触不到该文件 ⇒「groom.py 重写 state 后 assessments 字节不变」是
  可断言不变量 (物理隔离, 无跨文件合并语义; 两文件并发写互不干扰)。

state 文件契约 (v1, additive-only)::

    {"schema_version": 1,
     "last_run": {"context_fingerprint": <TASK-004 上下文面全量 dict (四分量 +
                                  additive ``degraded`` 告知面, A-3)>,
                  "context_key": <fingerprint.context_key(四分量) — 便捷单键,
                                  Tier B 上下文门的比对基元 (DEC 裁定-9)>,
                  "provenance": <{"harness": str, "model_id": str|None} 全量>,
                  "scope_degraded": <list[str], 可选 (B-1 additive) — 作用域解析
                                  降级项 (main / submodule:<path> / repo:<bare>),
                                  调用方显式传入才写 (含空清单 = 已核验零降级)>,
                  "degraded": <list[str], 可选 (A-3 additive) — 上下文指纹降级
                                  分量名 (git_heads / handoff_pointer); 非空才写>},
     "issues": {"<repo>#<number>": {
         "issue_key":        <fingerprint.combined_issue_key — issue 面四元组指纹>,
         "tier_a":           {"category": str, "signals": [TASK-002 信号列表]},
         "judgement_inputs": {"staleness_tier": str|None,   # 判据输入快照 —
                              "activity_tier": str|None,    # 时间敏感字段入快照,
                              "taxonomy_hash": str}},       # 跨档即触发重分类
         "last_classified_at": "<ISO 8601 UTC>"},
         ...},
     "assessments_ttl": <int 天, 可选 — 适配层经 CLI 注入, 引擎原样保存/续传>}

Tier A 复用规则 (SC-4): **issue_key 未变 且 判据输入快照未变 ⇒ 复用上次分类**
(state 条目逐字续传, ``last_classified_at`` 不刷新 — 复用不是重新分类)。
健全性论证: tier_a.classify 的输入面 = title/labels (⊆ issue_key) +
staleness 档 + activity 档 (⊆ judgement_inputs) + taxonomy (⊆
judgement_inputs.taxonomy_hash); (issue_key, judgement_inputs) 相等 ⇒ 分类
输出必然相等, 复用无损。**时间敏感字段跨档 (如 staleness ``<7d`` →
``7-30d``, 纯时钟流逝, issue_key 不变) ⇒ 重分类**; taxonomy 升级
(taxonomy_hash 变) ⇒ 全量重分类 (裁定-1: 规则变化不许吃旧结论)。
任何 prev 条目形状可疑 (缺 issue_key / 缺 tier_a / 缺 judgement_inputs) ⇒
宁重评不误复用 (fail-closed 方向)。

Tier B provenance 门 (裁定③) + 上下文门 (DEC 裁定-9, plugin#110): 复用门 =
``fingerprint.combined_provenance_key`` **完整拼接串相等** (harness +
model_id 两分量都比对) **且** (``context_key`` 传入时) entry.context_key ==
本轮上下文指纹键; 不匹配 / 条目形状非法 / (assessments_ttl 激活时)
created_at 过期 ⇒ 该条进 **stale 集** (``{key: reason}``; 报告层以 null
呈现, 引擎不改写不删除)。model_id: 脚本层未知即 None — None 与任何具体
model_id 不匹配 ⇒ stale (fail-closed: 宁重评不误复用)。上下文门分层
(裁定-9 精确语义): **Tier A 免** — 分类输入 ⊆ issue_key ∪ judgement_inputs
(taxonomy_hash 已在判据输入), 上下文其余分量数学上不可能改变 Tier A 分类;
**Tier B 全量 stale 即「上下文一变 ⇒ 全量重评」的实现形态** — 引擎只负责
诚实标 stale, 重评由适配层做。``context_key=None`` (缺省) = 上下文门不
启用 (向后兼容: 测试注入 / 早期调用方), 传入即激活。

diff 接口 (TASK-006 消费): ``compute_diff(prev_keys, current_keys)`` 纯集合差
→ ``{"new": [...], "closed": [...], "baseline": bool}`` (排序输出, 确定性)。
baseline: state 文件缺席 ⇒ 全部 new (``baseline_run=True``)。

时钟/读盘全可注入 (``now_fn`` / ``rename_fn`` / assessments reader),
测试零真盘依赖 (tempdir + 注入)。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import fingerprint

__all__ = [
    "STATE_SCHEMA_VERSION",
    "ASSESSMENTS_SCHEMA_VERSION",
    "DEFAULT_STATE_RELPATH",
    "DEFAULT_ASSESSMENTS_RELPATH",
    "ASSESSMENTS_SCHEMA_DOC",
    "ASSESSMENTS_ROOT_REQUIRED_KEYS",
    "ASSESSMENTS_ENTRY_REQUIRED_KEYS",
    "ASSESSMENTS_ENTRY_OPTIONAL_KEYS",
    "ASSESSMENTS_PROVENANCE_KEYS",
    "STALE_REASONS",
    "IncrementalEngine",
    "compute_diff",
    "default_assessments_reader",
    "judgement_inputs_from",
]

STATE_SCHEMA_VERSION = 1
ASSESSMENTS_SCHEMA_VERSION = 1

# 裁定④: 状态文件单一固定路径 (cache/ = 可再生); assessments 独立文件
# (刻意不在 cache/ 下 — Tier B 评估是 AI 语义产物, 非机械可再生缓存,
# 「清 cache」不得连带丢失)。
DEFAULT_STATE_RELPATH = Path(".aria") / "cache" / "groom-state.json"
DEFAULT_ASSESSMENTS_RELPATH = Path(".aria") / "groom-assessments.json"

# state 条目内判据输入快照的固定键集 (与 build/比较双侧共用一个构造点)。
_JUDGEMENT_INPUT_FIELDS = ("staleness_tier", "activity_tier", "taxonomy_hash")

# stale reason 封闭枚举 (报告层按 reason 文案化; 新增 reason = additive)。
STALE_REASONS = frozenset({
    "entry-not-object",        # 条目不是 JSON object
    "provenance-missing",      # 条目缺 provenance 键 (契约必填)
    "provenance-invalid",      # provenance 形状非法 (非 dict / 缺分量)
    "provenance-mismatch",     # combined_provenance_key 与本轮不等 (复用门主判据)
    "context-missing",         # 条目缺 context_key 键 (契约必填; 上下文门激活时 — 未来旧档/缺省, fail-closed)
    "context-changed",         # entry.context_key ≠ 本轮 context_key (DEC 裁定-9: 上下文一变 ⇒ Tier B 全量重评)
    "created-at-missing",      # 条目缺 created_at 键 (契约必填)
    "created-at-unparseable",  # created_at 非 ISO 8601 (ttl 激活时才需要解析)
    "ttl-expired",             # created_at + assessments_ttl ≤ now (边界算过期)
})

_UNSET = object()  # assessments_ttl 续传/显式覆盖的区分哨兵


# ------------------------------------------------ groom-assessments.json 契约
#
# 本任务 (TASK-005) 拥有该契约; TASK-010 (SKILL.md 适配层) 是唯一写者与
# 主要消费者 — SKILL.md 须逐字引用本常量 (或指针), 不得另立 paraphrase 分叉。

ASSESSMENTS_SCHEMA_DOC = """\
groom-assessments.json 键结构契约 v1 (TASK-005 拥有; TASK-010 适配层写入/消费)
==========================================================================

落点   : <project_root>/.aria/groom-assessments.json (独立于 .aria/cache/ —
         Tier B 评估是 AI 语义产物, 非机械可再生缓存, 清 cache 不得连带丢失)。
写者   : 仅 SKILL.md 适配层 (AI, 经 Claude Code / 其他 harness)。groom.py 与
         lib/incremental.py 全程不写该文件 (裁定④ 两文件各自
         last-writer-wins; 引擎对它只读, public API 上无 assessment 写面)。
读者   : lib/incremental.py (Tier B 复用门) + 渲染层 (报告呈现)。

根结构 (v1, additive-only — 只允许新增键, 永不移除/改名/改型既有键;
reader 必须忽略未知键; 破坏性变更被本契约禁止, 故 schema_version 恒 1):

  {
    "schema_version": 1,
    "assessments": {
      "<repo>#<number>": { <entry>, ... }
    }
  }

entry (键 = f"{repo}#{number}", 与 issue 身份键同形):

  {
    "verdict_priorities": [...],     # 可选 — 优先级裁决面 ( Tier B 语义评估)
    "suspected_fixed":     {...},    # 可选 — 疑似已修可关单判断
    "owner_decisions":     {...},    # 可选 — owner 决策面抽取
    "provenance": {                  # 必填 — 复用门比对面 (裁定③ 分层采集)
      "harness":  "<非空 str, 调用 harness 自报>",
      "model_id": "<str|None — 适配层补全; None=未补全>"
    },
    "created_at": "<ISO 8601, 推荐 UTC Z 形态>",  # 必填 — ttl 判定锚点
    "context_key": "<sha256 hex — fingerprint.context_key(评估时上下文面), "
                   "必填 — 上下文门比对面 (DEC 裁定-9; 取自评估轮 "
                   "groom-state.json last_run.context_key)>"
  }

复用门 : entry.provenance 经 fingerprint.combined_provenance_key 得完整拼接串,
         与本轮 provenance 拼接串**相等**才可复用; 且 (上下文门激活时)
         entry.context_key 与本轮 fingerprint.context_key 相等。以下任一 ⇒
         stale (报告层以 null 呈现该条, 引擎返回 stale 集 {key: reason},
         不改写不删除):
           provenance-mismatch / provenance-missing / provenance-invalid /
           entry-not-object / context-missing (上下文门激活时缺 context_key —
           未来旧档/缺省, fail-closed) / context-changed (上下文面 (openspec/
           git HEAD/handoff/taxonomy) 任一分量变 ⇒ Tier B 全量重评, DEC
           裁定-9: issue 本体未动而 spec ship 后评估翻转的 plugin#110 类
           静默陈旧由此封堵) / created-at-missing / created-at-unparseable /
           ttl-expired (groom-state.json 的 assessments_ttl 天数激活时,
           created_at + ttl ≤ now 即过期; 边界算过期)。
         model_id=None (脚本层未知) 与任何具体 model_id 不匹配 ⇒ stale —
         fail-closed 方向: 宁重评不误复用。
         判序: entry-not-object → provenance-* → context-* → created-at-* →
         ttl-expired (先身份门后新鲜度门; 多违规条目报第一个命中)。

示例   :
  {
    "schema_version": 1,
    "assessments": {
      "Aria#233": {
        "verdict_priorities": [{"from": "P2", "to": "P3", "rationale": "..."}],
        "suspected_fixed": {"verdict": false, "rationale": "..."},
        "provenance": {"harness": "claude-code", "model_id": "glm-5.2"},
        "created_at": "2026-10-19T08:30:00Z",
        "context_key": "5f2a...c9 (64 hex — 评估轮上下文面指纹)"
      }
    }
  }
"""

# 机读锚点 (SKILL.md / 渲染层按常量引用, 防手抄漂移; 与上文文档块互为校对)。
ASSESSMENTS_ROOT_REQUIRED_KEYS = ("schema_version", "assessments")
ASSESSMENTS_ENTRY_REQUIRED_KEYS = ("provenance", "created_at", "context_key")
ASSESSMENTS_ENTRY_OPTIONAL_KEYS = ("verdict_priorities", "suspected_fixed", "owner_decisions")
ASSESSMENTS_PROVENANCE_KEYS = ("harness", "model_id")


# ------------------------------------------------------------------- 纯函数面

def judgement_inputs_from(classified_record: Mapping[str, Any], taxonomy_hash: str) -> dict[str, Any]:
    """tier_a.classify 输出行 → 判据输入快照 ``{staleness_tier, activity_tier,
    taxonomy_hash}`` (Tier A 复用门的比较面之一)。

    - staleness/activity 取 classify 信号列表中对应 kind 的 ``value``;
      信号缺席 (``updated`` / ``comments_count`` 字段缺席 ⇒ 无信号) ⇒ ``None``
      (缺席不是 ``"0"`` 档, 不猜 — None 与任何档名互异, 字段出现即触发重分类)。
    - taxonomy_hash 由调用方传入 (TASK-004 上下文面 SOT 的同一分量,
      ``context_fingerprint()["taxonomy_hash"]``), 引擎不自算。
    """
    if not isinstance(classified_record, Mapping):
        raise ValueError(
            f"classified record must be a mapping, got {type(classified_record).__name__}"
        )
    if not isinstance(taxonomy_hash, str) or not taxonomy_hash:
        raise ValueError(f"taxonomy_hash must be a non-empty string, got {taxonomy_hash!r}")
    signals = classified_record.get("signals") or []
    if not isinstance(signals, list):
        raise ValueError("'signals' must be a list")

    def _tier(kind: str) -> str | None:
        for sig in signals:
            if isinstance(sig, Mapping) and sig.get("kind") == kind:
                value = sig.get("value")
                return value if isinstance(value, str) else None
        return None

    return {
        "staleness_tier": _tier("staleness"),
        "activity_tier": _tier("activity"),
        "taxonomy_hash": taxonomy_hash,
    }


def compute_diff(
    prev_keys: Iterable[str],
    current_keys: Iterable[str],
) -> dict[str, Any]:
    """集合差 (TASK-006 diff 段引擎的数据基元): prev state issue 键 vs 本轮键
    → ``{"new": [...], "closed": [...], "baseline": <prev 为空>}``。

    - new   = current − prev (本轮首见, 需全新分类/评估)
    - closed = prev − current (上轮在、本轮不在 — 已关闭/移出作用域)
    - 输出排序 (确定性); 输入重复键去重 (集合语义)。
    - baseline = prev 键集为空 (含 state 文件缺席的 baseline run)。
    """
    prev_set = set(prev_keys)
    current_set = set(current_keys)
    return {
        "new": sorted(current_set - prev_set),
        "closed": sorted(prev_set - current_set),
        "baseline": not prev_set,
    }


def _issue_key_of(record: Mapping[str, Any], where: str) -> str:
    repo = record.get("repo")
    number = record.get("number")
    if repo is None or number is None:
        raise ValueError(f"{where}: missing identity field(s): repo={repo!r} number={number!r}")
    return f"{repo}#{number}"


def _as_utc(dt: datetime) -> datetime:
    """naive 视作 UTC (状态/契约时间戳规约); aware 归一 UTC。"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso_z(dt: datetime) -> str:
    return _as_utc(dt).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: Any) -> datetime | None:
    """ISO 8601 → aware-UTC datetime; 不可解析/非 str ⇒ None (不抛 —
    条目级数据降级由 stale 集承载, 不炸整跑)。"""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return _as_utc(datetime.fromisoformat(raw))
    except ValueError:
        return None


def _default_now() -> datetime:
    return datetime.now(timezone.utc)


def _default_rename(src: Path, dst: Path) -> None:
    os.replace(src, dst)


# ------------------------------------------------------------------- 引擎面

class IncrementalEngine:
    """增量决策引擎: state 载入/校验 → Tier A 复用计划 / Tier B provenance 门
    → 下一轮 state 构建 → 原子写。

    注入面 (全部可选, 缺省面向生产):
      - ``state_path``: state 文件路径 (默认 DEFAULT_STATE_RELPATH 相对 cwd —
        groom.py 显式传 ``<project_root>/.aria/cache/groom-state.json``)。
      - ``assessments_reader``: ``() -> dict | None`` (None = 文件缺席);
        **只读** — 引擎不持有 assessment 路径, save_state 结构上触不到它。
        生产接线用 ``default_assessments_reader(project_root)``。
      - ``now_fn``: ``() -> datetime`` — last_classified_at / ttl 判定时钟。
      - ``rename_fn``: ``(src, dst)`` — 原子换名原语 (测试注入崩溃模拟)。
    """

    def __init__(
        self,
        state_path: str | Path = DEFAULT_STATE_RELPATH,
        *,
        assessments_reader: Any = None,
        now_fn: Any = None,
        rename_fn: Any = None,
    ) -> None:
        self._state_path = Path(state_path)
        self._assessments_reader = assessments_reader  # 只读 seam; 无写面
        self._now_fn = now_fn or _default_now
        self._rename_fn = rename_fn or _default_rename

    # ------------------------------------------------------------ state 载入

    def load_state(self) -> tuple[dict[str, Any], bool]:
        """读 state 文件 → ``(state, baseline_run)``。

        - 文件缺席 ⇒ ``({}, True)`` (baseline: 全部 new, 无可复用面)。
        - 文档级形状违规 (非法 JSON / 非 object / schema_version 缺席或不等 /
          issues 非 object / last_run 非 dict|None) ⇒ ValueError **上抛**
          (fail-closed: 自家原子写不应产出这些形态, 出现即外部损伤或版本
          错配, 静默 baseline 会把损伤吞成「无历史」)。
        - 条目级可疑 (缺 issue_key 等) 不在此拒载 — 交给 plan_tier_a 按
          「宁重评不误复用」逐条降级 (load 宽、复用严, 两级职责分离)。
        """
        try:
            text = self._state_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}, True
        try:
            state = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"groom-state.json is not valid JSON ({self._state_path}): {exc}") from exc
        if not isinstance(state, dict):
            raise ValueError(f"groom-state.json root must be an object, got {type(state).__name__}")
        version = state.get("schema_version")
        if version != STATE_SCHEMA_VERSION or isinstance(version, bool):
            raise ValueError(
                f"groom-state.json schema_version must be {STATE_SCHEMA_VERSION}, got {version!r}"
            )
        if "issues" in state and not isinstance(state["issues"], dict):
            raise ValueError(f"groom-state.json 'issues' must be an object, got {type(state['issues']).__name__}")
        last_run = state.get("last_run")
        if last_run is not None and not isinstance(last_run, dict):
            raise ValueError(f"groom-state.json 'last_run' must be an object or null, got {type(last_run).__name__}")
        return state, False

    # ---------------------------------------------------------- Tier A 复用

    def plan_tier_a(
        self,
        state: Mapping[str, Any],
        faces: Mapping[str, Mapping[str, Any]],
        classified: Iterable[Mapping[str, Any]],
        taxonomy_hash: str,
    ) -> dict[str, Any]:
        """Tier A 复用计划: 对比 state.issues 与本轮 (faces, classified) →
        ``{baseline_run, new, closed, reused, reclassify}`` (后四者排序键列表)。

        - 复用门 (双条件同时成立): prev.issue_key == combined_issue_key(face)
          且 prev.judgement_inputs == judgement_inputs_from(classified, hash)。
          任一变 (含纯时钟跨档 — staleness/activity 档名入快照) ⇒ reclassify。
        - ``reclassify ⊇ new`` (new = 首见, 也要分类); reused 条目可从 state
          逐字续传 (build_next_state 据此保留 last_classified_at)。
        - faces 键集与 classified 行身份键集必须相等 (接线错误 fail-closed,
          不静默取交集); classified 重复身份 ⇒ ValueError (与
          fingerprint.fingerprint_issues 同判: 拒绝静默覆盖)。
        """
        if not isinstance(state, Mapping):
            raise ValueError(f"state must be a mapping, got {type(state).__name__}")
        rows: dict[str, Mapping[str, Any]] = {}
        for idx, rec in enumerate(classified):
            key = _issue_key_of(rec, f"classified[{idx}]")
            if key in rows:
                raise ValueError(f"duplicate classified identity {key!r} at classified[{idx}] — refusing silent overwrite")
            rows[key] = rec
        face_keys = set(faces)
        row_keys = set(rows)
        if face_keys != row_keys:
            missing = sorted(face_keys - row_keys)
            extra = sorted(row_keys - face_keys)
            raise ValueError(f"faces and classified key sets differ (missing-in-classified={missing}, extra-in-classified={extra})")

        prev_issues = state.get("issues") or {}
        inputs: dict[str, dict[str, Any]] = {
            key: judgement_inputs_from(rows[key], taxonomy_hash) for key in rows
        }
        new: list[str] = []
        reused: list[str] = []
        reclassify: list[str] = []
        for key in sorted(rows):
            prev = prev_issues.get(key)
            if not isinstance(prev, dict):
                new.append(key)
                reclassify.append(key)
                continue
            if self._tier_a_reusable(prev, faces[key], inputs[key]):
                reused.append(key)
            else:
                reclassify.append(key)
        closed = sorted(set(prev_issues) - row_keys)
        return {
            "baseline_run": not prev_issues,
            "new": new,
            "closed": closed,
            "reused": reused,
            "reclassify": reclassify,
        }

    @staticmethod
    def _tier_a_reusable(
        prev_entry: Mapping[str, Any],
        face: Mapping[str, Any],
        current_inputs: Mapping[str, Any],
    ) -> bool:
        """复用门本体 — prev 条目任一前提面可疑 ⇒ False (宁重评不误复用)。"""
        if not isinstance(prev_entry.get("issue_key"), str):
            return False
        if prev_entry["issue_key"] != fingerprint.combined_issue_key(face):
            return False
        prev_inputs = prev_entry.get("judgement_inputs")
        if not isinstance(prev_inputs, Mapping):
            return False
        if any(f not in prev_inputs for f in _JUDGEMENT_INPUT_FIELDS):
            return False
        if dict(prev_inputs) != dict(current_inputs):
            return False
        tier_a = prev_entry.get("tier_a")
        if not isinstance(tier_a, Mapping) or "category" not in tier_a or "signals" not in tier_a:
            return False
        return True

    # -------------------------------------------------------- Tier B 复用门

    def gate_tier_b(
        self,
        current_provenance: Mapping[str, Any],
        *,
        current_keys: Iterable[str] | None = None,
        assessments_ttl: int | None = None,
        context_key: str | None = None,
    ) -> dict[str, Any]:
        """Tier B provenance + 上下文门 (只读 assessments): →
        ``{"reusable": [...], "stale": {key: reason}, "orphaned": [...]}``。

        - 复用门 = ``combined_provenance_key`` 完整拼接串相等 (harness +
          model_id 两分量); 失败方向一律 stale, 绝不误复用 (见 STALE_REASONS)。
        - 上下文门 (DEC 裁定-9): ``context_key`` 传入 (groom.py 从本轮
          context_fingerprint 取 ``fingerprint.context_key``) 即激活 —
          entry 缺 ``context_key`` 键 ⇒ "context-missing" (未来旧档/缺省,
          fail-closed); entry.context_key ≠ 本轮 ⇒ "context-changed"
          (上下文一变 ⇒ Tier B 全量 stale, 重评由适配层做 — 引擎只诚实
          标 stale)。``context_key=None`` (缺省) = 门不启用 (向后兼容测试
          注入 / 早期调用方)。非 None 时须为非空 str, 否则 ValueError
          (本轮面接线错误 loud, 同 provenance 校验判)。
        - ``current_keys`` 给定 (groom.py 传本轮 issue 键集) 时: 不在其中的
          assessment 键归 ``orphaned`` (issue 已关闭/移出作用域 — 不复用也
          不 stale, 报告层自裁); None = 对全部 assessment 键评门。
        - 文档级违规 (根非 object / schema_version 不等 / 缺 assessments /
          assessments 非 object) ⇒ ValueError 上抛 (TASK-010 写者违约 —
          loud, 不静默当无文件); 条目级违规 ⇒ 逐条 stale (数据降级可呈现)。
        - ``assessments_ttl`` (天, 取自 state): 激活时 created_at + ttl ≤
          now ⇒ "ttl-expired" (边界算过期); created_at 不可解析 ⇒
          "created-at-unparseable"。
        """
        if self._assessments_reader is None:
            return {"reusable": [], "stale": {}, "orphaned": []}
        if context_key is not None and (
            not isinstance(context_key, str) or not context_key.strip()
        ):
            raise ValueError(
                f"context_key must be None (门不启用) or a non-empty string "
                f"(fingerprint.context_key 产物), got {context_key!r}"
            )
        doc = self._assessments_reader()
        if doc is None:
            return {"reusable": [], "stale": {}, "orphaned": []}
        if not isinstance(doc, dict):
            raise ValueError(f"groom-assessments.json root must be an object, got {type(doc).__name__}")
        version = doc.get("schema_version")
        if version != ASSESSMENTS_SCHEMA_VERSION or isinstance(version, bool):
            raise ValueError(
                f"groom-assessments.json schema_version must be {ASSESSMENTS_SCHEMA_VERSION}, got {version!r}"
            )
        entries = doc.get("assessments")
        if not isinstance(entries, dict):
            raise ValueError(
                f"groom-assessments.json 'assessments' must be an object, got {type(entries).__name__}"
            )
        current_key = fingerprint.combined_provenance_key(current_provenance)  # 本轮面也校验
        key_set = None if current_keys is None else set(current_keys)
        now = _as_utc(self._now_fn())

        reusable: list[str] = []
        stale: dict[str, str] = {}
        orphaned: list[str] = []
        for key in sorted(entries):
            if key_set is not None and key not in key_set:
                orphaned.append(key)
                continue
            reason = self._entry_stale_reason(
                entries[key], current_key, assessments_ttl, now, context_key
            )
            if reason is None:
                reusable.append(key)
            else:
                stale[key] = reason
        return {"reusable": reusable, "stale": stale, "orphaned": orphaned}

    @staticmethod
    def _entry_stale_reason(
        entry: Any,
        current_prov_key: str,
        ttl: int | None,
        now: datetime,
        current_ctx_key: str | None = None,
    ) -> str | None:
        """单条 assessment 判门; None = 可复用, 否则返回 STALE_REASONS 成员。

        判序 (契约文档钉死): entry-not-object → provenance-* → context-* →
        created-at-* → ttl-expired — 先身份门 (provenance + 上下文) 后
        新鲜度门 (ttl); 多违规条目报第一个命中。``current_ctx_key=None``
        = 上下文门不启用 (skip context-* 两判)。"""
        if not isinstance(entry, dict):
            return "entry-not-object"
        if "provenance" not in entry:
            return "provenance-missing"
        try:
            entry_key = fingerprint.combined_provenance_key(entry["provenance"])
        except (TypeError, ValueError):
            return "provenance-invalid"
        if entry_key != current_prov_key:
            return "provenance-mismatch"
        if current_ctx_key is not None:
            if "context_key" not in entry:
                return "context-missing"
            if entry["context_key"] != current_ctx_key:
                return "context-changed"
        if "created_at" not in entry:
            return "created-at-missing"
        if ttl is not None:
            created = _parse_iso(entry["created_at"])
            if created is None:
                return "created-at-unparseable"
            if now - created >= timedelta(days=ttl):
                return "ttl-expired"
        return None

    # ------------------------------------------------------- state 构建与写

    def build_next_state(
        self,
        prev_state: Mapping[str, Any],
        plan: Mapping[str, Any],
        faces: Mapping[str, Mapping[str, Any]],
        classified: Iterable[Mapping[str, Any]],
        taxonomy_hash: str,
        context_fingerprint: Mapping[str, Any],
        provenance: Mapping[str, Any],
        *,
        assessments_ttl: Any = _UNSET,
        scope_degraded: Any = _UNSET,
        context_degraded: Any = _UNSET,
    ) -> dict[str, Any]:
        """构建下一轮 state (不落盘 — 落盘由 save_state 原子完成)。

        - reused 键 (plan.reused ∩ prev.issues): prev 条目**逐字续传**
          (issue_key/judgement_inputs 相等 ⇒ 内容一致; last_classified_at
          保留 — 复用不是重新分类)。
        - 其余本轮键: 新条目 ``{issue_key, tier_a{category,signals},
          judgement_inputs, last_classified_at: now_fn()}``。
        - 上轮已 closed 的键不进下一轮 state (集合差方向)。
        - ``last_run`` = 本轮 context_fingerprint **全量** + 其便捷单键
          ``context_key`` (``fingerprint.context_key(context_fingerprint)`` —
          Tier B 上下文门比对基元; 形状经其校验, 缺分量 fail-closed) +
          provenance 全量 (TASK-004 产物原样; provenance 形状经
          combined_provenance_key 校验)。
        - classified 重复身份 ⇒ ValueError (与 plan_tier_a / fingerprint
          同判: 后行静默覆盖前行 = state 丢失一个条目的历史, 拒绝)。
        - ``assessments_ttl``: 缺省 (_UNSET) 续传 prev 值; 显式传值 (含
          None=清除) 覆盖; 值非 None 时写入, None 不写键。
        - ``scope_degraded`` (B-1 additive): 缺省 (_UNSET) 不写键 (旧调用
          方零扰动); 显式传入即写 ``last_run.scope_degraded`` — 含空清单
          (空清单 = 作用域解析已跑且零降级, 与「键缺席 = 未跑」可区分)。
        - ``context_degraded`` (A-3 additive): 缺省 (_UNSET) 不写键; 传入
          且**非空**才写 ``last_run.degraded`` (降级分量名清单 —
          ``git_heads`` / ``handoff_pointer``; 全健康不落键, 健康是常态
          不是事件)。
        """
        if not isinstance(prev_state, Mapping):
            raise ValueError(f"prev_state must be a mapping, got {type(prev_state).__name__}")
        if not isinstance(context_fingerprint, Mapping):
            raise ValueError(
                f"context_fingerprint must be a mapping, got {type(context_fingerprint).__name__}"
            )
        fingerprint.combined_provenance_key(provenance)  # 形状校验 (fail-closed)
        ctx_key = fingerprint.context_key(context_fingerprint)  # 形状校验 + 便捷单键
        rows: dict[str, Mapping[str, Any]] = {}
        for idx, rec in enumerate(classified):
            key = _issue_key_of(rec, f"classified[{idx}]")
            if key in rows:
                raise ValueError(f"duplicate classified identity {key!r} at classified[{idx}] — refusing silent overwrite")
            rows[key] = rec
        if set(faces) != set(rows):
            missing = sorted(set(faces) - set(rows))
            extra = sorted(set(rows) - set(faces))
            raise ValueError(f"faces and classified key sets differ (missing-in-classified={missing}, extra-in-classified={extra})")

        prev_issues = prev_state.get("issues") or {}
        reused_set = set(plan.get("reused") or [])
        issues: dict[str, dict[str, Any]] = {}
        stamp = _iso_z(self._now_fn())
        for key in sorted(rows):
            if key in reused_set and isinstance(prev_issues.get(key), dict):
                issues[key] = dict(prev_issues[key])  # 逐字续传 (含原时间戳)
                continue
            rec = rows[key]
            issues[key] = {
                "issue_key": fingerprint.combined_issue_key(faces[key]),
                "tier_a": {"category": rec.get("category"), "signals": list(rec.get("signals") or [])},
                "judgement_inputs": judgement_inputs_from(rec, taxonomy_hash),
                "last_classified_at": stamp,
            }
        next_ttl = prev_state.get("assessments_ttl") if assessments_ttl is _UNSET else assessments_ttl
        last_run: dict[str, Any] = {
            "context_fingerprint": dict(context_fingerprint),
            "context_key": ctx_key,
            "provenance": dict(provenance),
        }
        if scope_degraded is not _UNSET:
            last_run["scope_degraded"] = list(scope_degraded)  # B-1 additive
        if context_degraded is not _UNSET and context_degraded:
            last_run["degraded"] = list(context_degraded)      # A-3 additive
        state: dict[str, Any] = {
            "schema_version": STATE_SCHEMA_VERSION,
            "last_run": last_run,
            "issues": issues,
        }
        if next_ttl is not None:
            state["assessments_ttl"] = next_ttl
        return state

    def save_state(self, state: Mapping[str, Any]) -> None:
        """原子写 state (temp+rename; 本方法**只写 state_path**, 结构上触不到
        groom-assessments.json — 裁定④ 不变量的实现面)。

        序列化先落内存 (序列化失败 ⇒ 磁盘零扰动); temp 同目录 (rename 原子性
        要求同 fs) + pid 后缀 (并发跑 tmp 互踩面收窄); 写后 fsync 再 rename;
        rename 后 best-effort 目录 fsync。任一步异常 ⇒ 删 temp + 上抛,
        目标路径保持「旧内容或不存在」。
        """
        if not isinstance(state, Mapping):
            raise ValueError(f"state must be a mapping, got {type(state).__name__}")
        payload = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        path = self._state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            self._rename_fn(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        self._fsync_dir_best_effort(path.parent)

    @staticmethod
    def _fsync_dir_best_effort(directory: Path) -> None:
        """rename 后目录项持久化 (best-effort: 不支持 fsync 的 fs 不炸)。"""
        try:
            dirfd = os.open(str(directory), os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(dirfd)
        except OSError:
            pass
        finally:
            os.close(dirfd)


def default_assessments_reader(project_root: str | Path) -> Any:
    """生产接线: ``() -> dict | None`` — 读 ``<root>/.aria/groom-assessments.json``
    (只读)。文件缺席 ⇒ None (无评估可用, 门空转); 存在但非法 JSON ⇒
    ValueError 上抛 (fail-closed: 存在的坏文件不冒充缺席)。

    返回的是闭包 — 引擎持有 reader 而非路径, 模块内不存在 assessment 写面。
    """
    path = Path(project_root) / DEFAULT_ASSESSMENTS_RELPATH

    def reader() -> dict[str, Any] | None:
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        return json.loads(text)  # JSONDecodeError (ValueError 子类) 上抛

    return reader

#!/usr/bin/env python3
"""issue-groomer diff 段引擎 (P1 MVP, 10CG/Aria#238, TASK-006; SC-4).

消费 ``incremental.plan_tier_a`` 的计划面, 产出 ``groom-report.schema.json``
DiffSection 的 **键级** diff 面; schema 条目形态 ({repo, number, title} /
{..., from, to}) 的富化基元 (``build_diff_ref`` / ``build_drift_entry``)
也由本模块提供 — title 来自 fetch 语料、drift from/to 来自 Tier B 判读
对照, 机械层不产语义, 组装 (groom.py, TASK-017) 只做映射。

职责切面:

- **集合差面** (new/closed): plan.new / plan.closed 键级直通 (排序输出,
  确定性; 防御去重 — plan_tier_a 产物本已排序无重复, 双保险不改语义)。
- **漂移面** (drift, SC-4「仅有新评估条目报告」): 候选池 =
  ``plan.reclassify ∪ plan.new ∪ assessed_keys`` (assessed_keys = Tier B
  本轮重评键集, 典型 = gate_tier_b 的 stale 键经适配层重评后的产物;
  None = 机械层无 Tier B 信息) 再交本轮在册键域
  ``plan.new ∪ plan.reused ∪ plan.reclassify``:
  - reused 条目默认不进 (复用不是重评); 经 assessed_keys 点名
    (Tier B stale 重评) 才进;
  - 域外键 (已 closed / 本轮不在册) 不产生漂移 — 报告只承在册条目。
- **top-N 截断** (防爆量): 候选按键字符串**字典序**排序后取前 ``top_n``;
  截断显式报告于 additive 字段 ``drift_truncated`` + ``drift_total``
  (截断前全量计数; 未截断时 == len(drift)) — 截断不静默, 消费者可提示
  「还有 N 条未展示」。排序口径 = ``sorted(key)`` 纯字典序, 与
  incremental.py 全模块键排序一致 (number 段为字符串序:
  ``'Aria#10' < 'Aria#2'``); 确定性是契约, 「自然数值序」不是。
- **baseline 语义** (SC-4 专属 fixture): ``plan.baseline_run=True`` ⇒
  no-diff 空集 — 首跑无对照面, 三数组恒空 (总量在 summary 层报,
  TASK-017); 但**参数/形状校验先于短路**, 垃圾输入在 baseline 轮同样
  ValueError (fail-closed)。
- **top_n 语义** (钉死): ``int >= 0`` = 截断上限 (0 = 恒空面但
  drift_total 照报); ``None`` = 不截断; 负数 / bool ⇒ ValueError (接线
  错误, 不猜)。任何路径产出面长度 > schema ``drift.maxItems`` (100,
  DRIFT_SCHEMA_MAX_ITEMS 锁步常量) ⇒ ValueError — 运行时 N 超护栏须先
  bump schema minor, 不静默产出 schema 非法报告。

schema 演进注记: drift_truncated / drift_total 为 snapshot_schema_version
1.1 新增**可选**字段 (additive-only); 本模块产出面**恒含**二字段 (固定
六键形态, 消费面零分支), 外部生产者可省略。

纯函数, 零 IO, 全可测。
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

__all__ = [
    "DRIFT_SCHEMA_MAX_ITEMS",
    "DEFAULT_TOP_N",
    "build_diff_segment",
    "split_issue_key",
    "build_diff_ref",
    "build_drift_entry",
]

# 与 groom-report.schema.json DiffSection.drift.maxItems 锁步 (测试双向钉:
# schema 护栏 bump minor 时本值须同步 — 机械兜底防两处漂移)。
DRIFT_SCHEMA_MAX_ITEMS = 100

# top_n 缺省 (SC-4「top-N 上限防爆量」; CLI 可注入, 运行时不得超过护栏)。
DEFAULT_TOP_N = 20

# plan_tier_a 直出形态的五键 (additive 计划键容忍 — 只读这五个)。
_PLAN_LIST_KEYS = ("new", "closed", "reused", "reclassify")


# ------------------------------------------------------------- 富化基元面

def split_issue_key(key: str) -> tuple[str, int]:
    """issue 身份键 ``"<repo>#<number>"`` → ``(repo, number)``。

    - rpartition('#'): number 侧锚定数字段; repo 裸仓名不含 '#' (fetch 层
      归一形态), 即便含也取最后一个 '#' 分隔, number 侧校验兜底。
    - 非法形态 (非 str / 无 '#' / number 非纯数字 / number < 1 — schema
      minimum:1) ⇒ ValueError (fail-closed: 组装层不猜)。
    """
    if not isinstance(key, str):
        raise ValueError(f"issue key must be a string, got {type(key).__name__}")
    repo, sep, raw_number = key.rpartition("#")
    if not sep or not repo or not raw_number.isdigit():
        raise ValueError(f"malformed issue key {key!r} (expected '<repo>#<number>')")
    number = int(raw_number)
    if number < 1:
        raise ValueError(f"issue number must be >= 1 (schema minimum), got {key!r}")
    return repo, number


def build_diff_ref(key: str, title: str) -> dict[str, Any]:
    """键级 new/closed 条目 → schema DiffRef ``{repo, number, title}``。

    groom.py (TASK-017) 组装报告时以 fetch 语料 title 逐键映射。
    """
    if not isinstance(title, str):
        raise ValueError(f"title must be a string for {key!r}, got {type(title).__name__}")
    repo, number = split_issue_key(key)
    return {"repo": repo, "number": number, "title": title}


def build_drift_entry(key: str, title: str, from_value: str, to_value: str) -> dict[str, Any]:
    """键级漂移候选 → schema DriftEntry ``{repo, number, title, from, to}``。

    from / to = Tier B 判读值 (先前 / 本次 — 优先级档或评估值文本) 的
    **显式传入面**: 机械层不产语义, 适配层 (TASK-010) 重评对照后由组装层
    (TASK-017) 供值。
    """
    if not isinstance(title, str):
        raise ValueError(f"title must be a string for {key!r}, got {type(title).__name__}")
    if not isinstance(from_value, str) or not isinstance(to_value, str):
        raise ValueError(
            f"drift from/to must be strings for {key!r}, "
            f"got from={type(from_value).__name__}, to={type(to_value).__name__}"
        )
    repo, number = split_issue_key(key)
    return {"repo": repo, "number": number, "title": title, "from": from_value, "to": to_value}


# ------------------------------------------------------------- 校验 helper

def _validated_keys(values: Iterable[Any], where: str) -> list[str]:
    """可迭代键集 → list[str]; 非 str 元素 ⇒ ValueError (接线错误 loud)。"""
    out: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError(f"{where}: keys must be strings, got {type(value).__name__} {value!r}")
        out.append(value)
    return out


# ------------------------------------------------------------- diff 段引擎

def build_diff_segment(
    plan: Mapping[str, Any],
    *,
    top_n: int | None = DEFAULT_TOP_N,
    assessed_keys: Iterable[str] | None = None,
) -> dict[str, Any]:
    """``IncrementalEngine.plan_tier_a`` 计划面 → 键级 diff 段。

    产出面 (固定六键, 恒含 additive 二字段)::

        {"new": [key...],            # 本轮首见 (排序)
         "closed": [key...],         # 上轮在、本轮不在 (排序)
         "drift": [key...],          # 漂移候选 (字典序, top_n 截断后)
         "baseline_run": bool,
         "drift_truncated": bool,    # drift 是否截断 (未入面候选见 drift_total)
         "drift_total": int}         # 截断前候选全量计数

    语义要点 (模块 docstring 的函数级摘要; 细判据见模块头):

    - baseline_run=True ⇒ no-diff 空集 (三数组恒空, additive 字段归零);
      参数/形状校验**先于**短路。
    - drift 候选池 = reclassify ∪ new ∪ assessed_keys, 交本轮在册键域;
      reused 默认不进, 经 assessed_keys 点名才进; closed/域外键不进。
    - top_n: int >= 0 = 截断上限 (0 = 恒空面); None = 不截断; 负数/bool
      ⇒ ValueError。产出面 > schema maxItems(100) ⇒ ValueError (护栏)。
    - plan 形状 = plan_tier_a 直出五键 {baseline_run, new, closed, reused,
      reclassify}; 缺键 / 非法类型 ⇒ ValueError (fail-closed); 计划面
      additive 额外键容忍 (只读五键)。
    """
    # ---- 形状与参数校验 (先于 baseline 短路 — 任何轮次垃圾输入都 loud)
    if not isinstance(plan, Mapping):
        raise ValueError(f"plan must be a mapping, got {type(plan).__name__}")
    missing = [k for k in ("baseline_run", *_PLAN_LIST_KEYS) if k not in plan]
    if missing:
        raise ValueError(
            f"plan missing required key(s) {missing} (expected plan_tier_a output shape)"
        )
    baseline_run = plan["baseline_run"]
    if not isinstance(baseline_run, bool):
        raise ValueError(f"plan.baseline_run must be bool, got {type(baseline_run).__name__}")
    plan_lists = {
        key: _validated_keys(plan[key], f"plan.{key}") for key in _PLAN_LIST_KEYS
    }
    if top_n is not None:
        if isinstance(top_n, bool) or not isinstance(top_n, int):
            raise ValueError(f"top_n must be an int >= 0 or None (no cap), got {top_n!r}")
        if top_n < 0:
            raise ValueError(f"top_n must be >= 0, got {top_n}")
    assessed: set[str] = set()
    if assessed_keys is not None:
        assessed = set(_validated_keys(assessed_keys, "assessed_keys"))

    # ---- baseline: no-diff 空集 (首跑无对照面; 总量在 summary 层报)
    if baseline_run:
        return {
            "new": [],
            "closed": [],
            "drift": [],
            "baseline_run": True,
            "drift_truncated": False,
            "drift_total": 0,
        }

    # ---- 集合差面: 键级直通 (排序 + 防御去重)
    new_keys = sorted(set(plan_lists["new"]))
    closed_keys = sorted(set(plan_lists["closed"]))

    # ---- 漂移候选池: 仅「本轮有新评估」的条目, 交本轮在册键域
    current_domain = (
        set(plan_lists["new"]) | set(plan_lists["reused"]) | set(plan_lists["reclassify"])
    )
    pool = (set(plan_lists["new"]) | set(plan_lists["reclassify"]) | assessed) & current_domain
    ordered = sorted(pool)
    drift_total = len(ordered)
    drift = ordered if top_n is None else ordered[:top_n]
    if len(drift) > DRIFT_SCHEMA_MAX_ITEMS:
        raise ValueError(
            f"drift face would carry {len(drift)} entries > schema guardrail "
            f"maxItems={DRIFT_SCHEMA_MAX_ITEMS} (groom-report.schema.json "
            "DiffSection.drift): runtime top_n must stay within the guardrail — "
            "raise it via schema minor bump first, never emit a schema-invalid report"
        )
    return {
        "new": new_keys,
        "closed": closed_keys,
        "drift": drift,
        "baseline_run": False,
        "drift_truncated": len(drift) < drift_total,
        "drift_total": drift_total,
    }

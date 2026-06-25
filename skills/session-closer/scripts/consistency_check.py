#!/usr/bin/env python3
"""session-closer · 跨维一致性校验器 (TASK-004).

在收尾时对 UPM / OpenSpec / User Story / PRD 四维做 **advisory** 一致性检查,
输出结构化 flag 回填 handoff §5。**永不阻塞**(CLI exit 0,即使有 flag)——
advisory-over-hardlock,修复是 owner/后续 action(proposal OOS-2)。

4 类不一致 (proposal AC-4):
  1. upm_vs_archive       : UPM cycle ↔ 最新归档 cycle 不符
  2. openspec_vs_upm      : active change 未在 UPM in-progress
  3. requirements_vs_handoff: 高优先级未完成 US 未入 §2 carry-forward
  4. prd_vs_requirements  : PRD 引用的 US 在 requirements 不存在 (broken ref)

字段漂移修正 (R1 post_spec audit C-1, v1.39→v1.49 schema):
  - openspec 顶层 list 是 `changes` 非 `active_changes` (collectors/openspec.py:273)
  - UPM cycle 字段是 `current_cycle` 非 `cycle_number` (collectors/upm.py:391)
  - `upm.in_progress_change_ids` 在当前 snapshot schema **不存在** → 类 2 在真
    snapshot 上 upm_in_progress_ids 恒空 = **fixture-only + 第三方 manual**。该维需要
    UPM 暴露 in-progress change id 列表 (当前 collectors/upm.py 未采), 非静默 no-op:
    check_consistency 仍可用 fixture 验, 真 snapshot 上该类沉默是 **已知数据缺口**。
"""
from __future__ import annotations

import json


def _flag(dimension, kind, detail):
    return {"dimension": dimension, "kind": kind, "severity": "advisory", "detail": detail}


def check_consistency(data):
    """纯函数。data 缺字段则该类跳过(不报错)。返回 advisory flag 列表(可空)。"""
    data = data or {}
    flags = []

    # 类 1: UPM cycle ↔ 最新归档 cycle
    uc = data.get("upm_cycle")
    ac = data.get("latest_archive_cycle")
    if uc is not None and ac is not None and uc != ac:
        flags.append(_flag("upm_vs_archive", "cycle_mismatch",
                            f"UPM cycle {uc} != 最新归档 cycle {ac}"))

    # 类 2: active change 未在 UPM in-progress
    # NOTE (R1 C-1): upm_in_progress_ids 来自 snapshot 不存在的字段 → 真 snapshot 上恒空 →
    # 该类在真环境沉默 (fixture-only)。保留逻辑供 fixture 验 + 未来 UPM 字段补齐后即生效。
    in_prog = set(data.get("upm_in_progress_ids") or [])
    for cid in (data.get("active_change_ids") or []):
        if cid not in in_prog:
            flags.append(_flag("openspec_vs_upm", "active_change_not_in_upm",
                               f"active change '{cid}' 未列入 UPM in-progress"))

    # 类 3: 高优先级未完成 US 未入 §2 carry-forward
    carried = set(data.get("carry_forward_us") or [])
    for us in (data.get("high_priority_unfinished_us") or []):
        if us not in carried:
            flags.append(_flag("requirements_vs_handoff", "unfinished_us_not_carried",
                               f"高优先级未完成 {us} 未进 §2 carry-forward"))

    # 类 4: PRD 引用 US 在 requirements 不存在 (broken ref)
    known = set(data.get("known_us_ids") or [])
    for us in (data.get("prd_referenced_us") or []):
        if us not in known:
            flags.append(_flag("prd_vs_requirements", "broken_us_ref",
                               f"PRD 引用 {us} 在 requirements 不存在"))

    return flags


def data_from_snapshot(snapshot, *, carry_forward_us=None, prd_referenced_us=None,
                       latest_archive_cycle=None):
    """从 state-scanner snapshot 抽取四维输入(best-effort,缺字段→None/[])。

    R1 C-1 字段修正: openspec.changes (非 active_changes) / upm.current_cycle (非 cycle_number)。
    """
    snapshot = snapshot or {}
    upm = snapshot.get("upm") or {}
    openspec = snapshot.get("openspec") or {}
    reqs = (snapshot.get("requirements") or {}).get("stories") or {}

    # R1 C-1: 顶层是 `changes` 非 `active_changes`
    active = openspec.get("changes") or {}
    active_ids = [it.get("id") for it in (active.get("items") or []) if it.get("id")]

    story_items = reqs.get("items") or []
    known_us = [it.get("id") for it in story_items if it.get("id")]
    high_unfinished = [
        it.get("id") for it in story_items
        if it.get("id") and str(it.get("status") or "").lower() in ("in_progress", "pending")
        and str(it.get("priority") or "").upper() in ("P0", "P1")
    ]

    return {
        # R1 C-1: current_cycle 非 cycle_number
        "upm_cycle": upm.get("current_cycle"),
        "latest_archive_cycle": latest_archive_cycle,
        "active_change_ids": active_ids,
        # R1 C-1: in_progress_change_ids 不在当前 schema → 真 snapshot 恒空 (fixture-only 维)
        "upm_in_progress_ids": upm.get("in_progress_change_ids") or [],
        "high_priority_unfinished_us": high_unfinished,
        "carry_forward_us": carry_forward_us or [],
        "known_us_ids": known_us,
        "prd_referenced_us": prd_referenced_us or [],
    }


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="session-closer cross-dimension consistency check (advisory)")
    p.add_argument("--data-json", default=None, help="直接喂结构化 data(测试/调试用)")
    p.add_argument("--snapshot-json", default=None, help="state-scanner snapshot path")
    a = p.parse_args(argv)

    if a.data_json:
        with open(a.data_json, encoding="utf-8") as f:
            data = json.load(f)
    elif a.snapshot_json:
        with open(a.snapshot_json, encoding="utf-8") as f:
            data = data_from_snapshot(json.load(f))
    else:
        data = {}

    flags = check_consistency(data)
    print(json.dumps({"flags": flags, "count": len(flags)}, ensure_ascii=False, indent=2))
    # advisory: 永不因 flag 而非 0 退出
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

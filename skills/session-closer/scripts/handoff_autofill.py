#!/usr/bin/env python3
"""session-closer · handoff 模板自动填充 + 机械补漏交叉核验 (TASK-003 §7/§2/§5 + TASK-005 §8).

机械消费 state-scanner snapshot, 回填 9 段 handoff 模板:
  §7 提交清单   ← snapshot.sync_status.multi_remote  (ahead/parity, 不同步告警)
  §2 carry-fwd  ← upm.followups + openspec.carry_forward_inventory.by_change + tasks.md `- [ ]` + subagent-state
  §5 四维状态   ← upm / openspec / requirements / PRD
  §8 memory     ← 本 session 新增 memory *.md (mtime > started_at)

**定位 (AD-2)**: session-closer 中机械 autofill 是 **AI 对话内省的兜底 (backstop)**, 非承重。
AI 先内省出未完成/经验 → autofill 机械 **交叉核验补漏** (cross_check_unfilled): snapshot
有但 AI 没提的项 → flag「机械补漏」。

字段漂移修正 (R1 post_spec audit C-2, v1.39→v1.49 schema):
  - §7 multi_remote 嵌套于 snapshot.sync_status.multi_remote (非顶层 multi_remote)
  - §5 UPM cycle 字段是 current_cycle (非 cycle_number)
  - §5 openspec 顶层 list 是 changes (非 active_changes)
  - §2 carry_forward_inventory 是 dict {total, active_change_count, by_change} (非 list)
    → carry_forward_from_inventory 从 by_change 提取为 list

纯函数为主, I/O 函数取显式路径, 便于单测。advisory/best-effort: 缺字段不报错。
"""
from __future__ import annotations

import os
import re

_UNCHECKED_RE = re.compile(r"^\s*[-*]\s+\[ \]\s+(.*\S)", re.MULTILINE)


# --- §7 提交清单 ---------------------------------------------------------------

def fill_sync_section(multi_remote):
    """返回 {'lines': [...], 'warnings': [...]}。

    每 repo(主仓 + 各 submodule)一行 parity 摘要; ahead>0 / parity≠equal /
    has_pending_push / 不可达 → 告警行。
    """
    mr = multi_remote or {}
    lines, warnings = [], []

    def _one(label, repo):
        if not repo:
            return
        head = (repo.get("local_head") or "?")[:7]
        branch = repo.get("branch") or "(detached)"
        parts = []
        for r in repo.get("remotes") or []:
            parts.append(f"{r.get('name')}={r.get('parity')}")
            if (r.get("ahead_count") or 0) > 0:
                warnings.append(f"[{label}] ahead {r['ahead_count']} vs {r.get('name')} — 需 push")
            if r.get("parity") not in ("equal", None) and r.get("parity") != "unknown":
                warnings.append(f"[{label}] parity={r.get('parity')} vs {r.get('name')}")
            if r.get("reachable") is False:
                warnings.append(f"[{label}] remote {r.get('name')} 不可达")
        lines.append(f"[{label}] {branch} = {head} | " + " ".join(parts))

    _one("main", mr.get("main_repo"))
    for sub in mr.get("submodules") or []:
        _one(sub.get("path") or "submodule", sub)
    if mr.get("has_pending_push"):
        warnings.append("multi_remote: has_pending_push=true")
    return {"lines": lines, "warnings": warnings}


# --- §2 carry-forward 汇编 -----------------------------------------------------

def grep_unchecked_tasks(changes_dir):
    """新增轻量 grep(非既有 collector): 扫 active openspec/changes/*/tasks.md 原始 `- [ ]`。"""
    items = []
    if not os.path.isdir(changes_dir):
        return items
    for name in sorted(os.listdir(changes_dir)):
        tasks = os.path.join(changes_dir, name, "tasks.md")
        if os.path.isfile(tasks):
            try:
                with open(tasks, encoding="utf-8", errors="replace") as f:
                    body = f.read()
            except OSError:
                continue
            for m in _UNCHECKED_RE.findall(body):
                items.append({"source": f"tasks.md:{name}", "item": m.strip()})
    return items


def _normalize_followup(f):
    """followup 可能是 str 或 dict (FollowupRow)。归一化为可读 str (R1 M-1)。"""
    if isinstance(f, str):
        return f
    if isinstance(f, dict):
        # 优先取语义字段; 否则拼非空 scalar 值
        for k in ("item", "text", "note", "summary", "title", "description"):
            if f.get(k):
                return str(f[k])
        parts = [f"{k}={v}" for k, v in f.items() if v not in (None, "", [], {})]
        return "; ".join(parts) if parts else str(f)
    return str(f)


def carry_forward_from_inventory(inventory):
    """openspec.carry_forward_inventory 是 dict {total, active_change_count, by_change}。
    从 by_change 提取为可遍历 list (R1 M-1: 直接当 list 遍历会取 dict keys 产垃圾)。

    by_change: {change_id: [items]} 或 {change_id: scalar}。返回 [{change, item}]。
    """
    inv = inventory or {}
    by_change = inv.get("by_change") or {}
    out = []
    if isinstance(by_change, dict):
        for cid, items in by_change.items():
            if isinstance(items, (list, tuple)):
                for it in items:
                    out.append({"change": cid, "item": _normalize_followup(it)})
            else:
                out.append({"change": cid, "item": _normalize_followup(items)})
    elif isinstance(by_change, (list, tuple)):
        for it in by_change:
            out.append({"change": None, "item": _normalize_followup(it)})
    return out


def assemble_unfinished(*, followups=None, carry_forward=None,
                        unchecked_tasks=None, subagent_pending=None):
    """汇编 §2 机械来源候选。返回 [{source, item}]。"对话上下文" best-effort 不在此(由 AI 补)。"""
    out = []
    for f in followups or []:
        out.append({"source": "upm.followups", "item": _normalize_followup(f)})
    for c in carry_forward or []:
        if isinstance(c, dict) and "item" in c:
            label = c["item"] if not c.get("change") else f"{c['change']}: {c['item']}"
            out.append({"source": "openspec.carry_forward_inventory", "item": label})
        else:
            out.append({"source": "openspec.carry_forward_inventory", "item": _normalize_followup(c)})
    out.extend(unchecked_tasks or [])
    for s in subagent_pending or []:
        out.append({"source": "subagent-state", "item": str(s)})
    return out


# --- 机械补漏交叉核验 (AC-3b, AD-2 backstop) ------------------------------------

def _item_key(text):
    """归一化 item 文本为比对 key (去空白/小写, 截断), 用于 AI 内省 vs 机械集合比对。"""
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def cross_check_unfilled(ai_mentioned, mechanical_items):
    """AC-3b 机械补漏: 给定 AI 内省已提及项 (str 集合) + 机械汇编项,
    返回机械有但 AI 没提的项 (标 omitted_by_ai=True 供 §2 flag「机械补漏」)。

    纯函数, 静态输入对可证伪 (snapshot 有 X + AI 草稿不含 X → flag X)。
    """
    mentioned = {_item_key(x) for x in (ai_mentioned or [])}
    missed = []
    for m in mechanical_items or []:
        text = m.get("item") if isinstance(m, dict) else m
        if _item_key(text) not in mentioned:
            entry = dict(m) if isinstance(m, dict) else {"item": text}
            entry["omitted_by_ai"] = True
            missed.append(entry)
    return missed


# --- §5 四维状态 ---------------------------------------------------------------

def four_dim_status(snapshot, *, prd_exists=None):
    snapshot = snapshot or {}
    upm = snapshot.get("upm") or {}
    op = snapshot.get("openspec") or {}
    reqs = (snapshot.get("requirements") or {}).get("stories") or {}
    # R1 C-2: 顶层是 changes 非 active_changes
    active = (op.get("changes") or {}).get("total")
    return {
        # R1 C-2: current_cycle 非 cycle_number
        "UPM": {"present": bool(upm), "cycle": upm.get("current_cycle")},
        "OpenSpec": {"active_changes": active, "pending_archive": len(op.get("pending_archive") or [])},
        "UserStory": {"total": reqs.get("total"), "by_status": reqs.get("by_status")},
        "PRD": {"present": prd_exists},
    }


# --- §8 memory 枚举 (TASK-005) -------------------------------------------------

def enumerate_new_memory(memory_dir, since_epoch):
    """返回本 session 新增 memory: mtime > since_epoch 的 *.md(排除 MEMORY*.md 索引)。"""
    out = []
    if not os.path.isdir(memory_dir) or since_epoch is None:
        return out
    for name in sorted(os.listdir(memory_dir)):
        if not name.endswith(".md") or name.startswith("MEMORY"):
            continue
        path = os.path.join(memory_dir, name)
        try:
            mt = os.path.getmtime(path)
        except OSError:
            continue
        if mt > since_epoch:
            out.append(name)
    return out


# --- snapshot adapter + 编排 (R1 M-1: 解析编排层原在被弃薄入口 prose, 此处重建) -----

def assemble_from_snapshot(snapshot, *, changes_dir=None, subagent_pending=None):
    """从真 snapshot 组装 §7/§2/§5 机械结果。R1 M-1 重建的 adapter 层。

    返回 {sync, unfinished, four_dim}。供 session-closer step0/3 机械兜底 + cross_check。
    """
    snapshot = snapshot or {}
    sync_status = snapshot.get("sync_status") or {}
    multi_remote = sync_status.get("multi_remote") or {}   # R1 C-2: 嵌套路径
    upm = snapshot.get("upm") or {}
    openspec = snapshot.get("openspec") or {}

    followups = upm.get("followups") or []
    carry_forward = carry_forward_from_inventory(openspec.get("carry_forward_inventory"))
    unchecked = grep_unchecked_tasks(changes_dir) if changes_dir else []

    return {
        "sync": fill_sync_section(multi_remote),
        "unfinished": assemble_unfinished(
            followups=followups, carry_forward=carry_forward,
            unchecked_tasks=unchecked, subagent_pending=subagent_pending),
        "four_dim": four_dim_status(snapshot),
    }


def main(argv=None):
    import argparse
    import json
    p = argparse.ArgumentParser(description="session-closer handoff autofill (mechanical backstop)")
    p.add_argument("--snapshot-json", required=True, help="state-scanner snapshot path")
    p.add_argument("--changes-dir", default=None, help="openspec/changes dir for unchecked-task grep")
    a = p.parse_args(argv)
    with open(a.snapshot_json, encoding="utf-8") as f:
        snapshot = json.load(f)
    result = assemble_from_snapshot(snapshot, changes_dir=a.changes_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

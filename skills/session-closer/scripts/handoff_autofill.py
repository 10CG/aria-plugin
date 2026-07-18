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

def _benign_unconditional_reasons():
    """从 state-scanner `multi_remote` collector 导入权威 benign-reason 集合 (F9′ 9.1:
    「不重造」— 不在本文件重复字面量, 避免两处漂移)。

    兄弟 skill 跨包导入, 仿 `owner_container()` 下方对 `lib.identity` 的既有 sys.path
    模式。best-effort: 任何失败(如布局变化)→ 返回空集, 使调用方把**所有**
    `parity=unknown` 都保守地升级为 warning —— 宁可多报一条噪音, 也不可回到「静默吞掉」
    的假绿通道 (本函数存在的原因)。
    """
    try:
        import sys
        from pathlib import Path

        # state-scanner/scripts 是兄弟 skill 的 collectors 包根; 加入 sys.path 使
        # `collectors.multi_remote` 可解析 (与 scan.py 自身的相对导入拓扑一致)。
        _ss_scripts = str(Path(__file__).resolve().parents[2] / "state-scanner" / "scripts")
        if _ss_scripts not in sys.path:
            sys.path.insert(0, _ss_scripts)
        from collectors.multi_remote import BENIGN_UNCONDITIONAL_REASONS

        return BENIGN_UNCONDITIONAL_REASONS
    except Exception:
        return frozenset()


def _unknown_is_benign(reason, evidence_grade, benign_reasons):
    """`parity=="unknown"` 是否可安全静默 (F9′ 9.1 reason 分诊, 取代旧版「一律吞掉」)。

    与 `multi_remote._benign_unknown` 同源判据, 用 `evidence_grade=="fresh"` 替代其
    `evidence_eligible` 参数 (session-closer 侧只拿得到 snapshot 里的 evidence_grade
    字符串, 不是 collector 内部的中间布尔量, 语义等价: `evidence_grade=="fresh"` 正是
    `_evidence_grade` 判定 `evidence_eligible=True` 的那一档)。
    """
    if reason in benign_reasons:
        return True
    if reason == "no_local_tracking_ref" and evidence_grade == "fresh":
        return True
    return False


def fill_sync_section(multi_remote):
    """返回 {'lines': [...], 'warnings': [...]}。

    每 repo(主仓 + 各 submodule)一行 parity 摘要; ahead>0 / parity≠equal(非 benign
    unknown) / has_pending_push / 不可达 → 告警行。

    F9′ 9.1: `parity=="unknown"` 不再无条件静默 —— 只有 benign reason (detached_head/
    shallow_clone/remote_branch_missing, 或 no_local_tracking_ref 且 evidence_grade
    =="fresh") 才不告警; 其余 unknown (not_refreshed/network_timeout/auth_failed/
    no_local_tracking_ref 非 fresh/未识别 reason) 一律升级为 warning — 否则 F1′ 的
    `unknown` 会被 session-closer 静默吞掉, 变成新的假绿通道。
    """
    mr = multi_remote or {}
    lines, warnings = [], []
    benign_reasons = _benign_unconditional_reasons()

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
            parity = r.get("parity")
            if parity == "unknown":
                reason = r.get("reason")
                evidence_grade = r.get("evidence_grade")
                if not _unknown_is_benign(reason, evidence_grade, benign_reasons):
                    warnings.append(
                        f"[{label}] parity=unknown reason={reason} "
                        f"(evidence_grade={evidence_grade}) vs {r.get('name')} — 未验证, 需人工核实"
                    )
            elif parity not in ("equal", None):
                warnings.append(f"[{label}] parity={parity} vs {r.get('name')}")
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

    by_change 真形态 (collectors/openspec.py:248): {change_id: {"count": N, "samples": [...]}}。
    兼容形态: {change_id: [items]} / {change_id: scalar} / [loose items]。返回 [{change, item}]。
    """
    inv = inventory or {}
    by_change = inv.get("by_change") or {}
    out = []
    if isinstance(by_change, dict):
        for cid, items in by_change.items():
            if isinstance(items, dict) and ("samples" in items or "count" in items):
                # 真 collector 形态: {count, samples} — 从 samples 展开 (I-2 code-review)
                samples = items.get("samples") or []
                if samples:
                    for s in samples:
                        out.append({"change": cid, "item": _normalize_followup(s)})
                elif items.get("count"):
                    out.append({"change": cid, "item": f"{items['count']} 项 carry-forward (无 sample)"})
            elif isinstance(items, (list, tuple)):
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

def owner_container():
    """机械 owner-container (frontmatter 用) — 替代 AI 手填 (DEC-20260704-002 §4,
    病根 #3: 手填漂移出 6 种不一致值破坏 collision 分类)。

    复用 Layer L 的 identity.get_identity().owner_container (state-scanner 兄弟 skill)。
    best-effort: 任何失败返回 None, 调用方 (phase-d-closer D.3 / session-closer step4)
    保留手填作 fallback。与本模块 advisory/缺字段不报错 哲学一致。
    """
    try:
        import sys
        from pathlib import Path

        # state-scanner/lib 是兄弟 skill 的包; 加其 skill root 使 `from lib.identity` 解析。
        _ss_root = str(Path(__file__).resolve().parents[2] / "state-scanner")
        if _ss_root not in sys.path:
            sys.path.insert(0, _ss_root)
        from lib.identity import get_identity

        ident = get_identity()
        return ident.owner_container if ident is not None else None
    except Exception:
        return None


def assemble_from_snapshot(snapshot, *, changes_dir=None, subagent_pending=None):
    """从真 snapshot 组装 §7/§2/§5 机械结果 + frontmatter owner-container。R1 M-1 重建的 adapter 层。

    返回 {sync, unfinished, four_dim, frontmatter}。供 session-closer step0/3 机械兜底 + cross_check。
    """
    snapshot = snapshot or {}
    sync_status = snapshot.get("sync_status") or {}
    multi_remote = sync_status.get("multi_remote") or {}   # R1 C-2: 嵌套路径
    upm = snapshot.get("upm") or {}
    openspec = snapshot.get("openspec") or {}

    followups = upm.get("followups") or []
    carry_forward = carry_forward_from_inventory(openspec.get("carry_forward_inventory"))
    unchecked = grep_unchecked_tasks(changes_dir) if changes_dir else []

    # M-1 (code-review): 探测 PRD 存在性 (snapshot.project_root/docs/requirements/prd*.md)
    prd_exists = None
    root = snapshot.get("project_root")
    if root:
        req_dir = os.path.join(root, "docs", "requirements")
        try:
            prd_exists = any(n.startswith("prd") and n.endswith(".md")
                             for n in os.listdir(req_dir))
        except OSError:
            prd_exists = False

    return {
        "sync": fill_sync_section(multi_remote),
        "unfinished": assemble_unfinished(
            followups=followups, carry_forward=carry_forward,
            unchecked_tasks=unchecked, subagent_pending=subagent_pending),
        "four_dim": four_dim_status(snapshot, prd_exists=prd_exists),
        "frontmatter": {"owner_container": owner_container()},  # 机械填, 替代手填 (§4)
    }


def main(argv=None):
    import argparse
    import json
    p = argparse.ArgumentParser(description="session-closer handoff autofill (mechanical backstop)")
    p.add_argument("--snapshot-json", default=None, help="state-scanner snapshot path")
    p.add_argument("--changes-dir", default=None, help="openspec/changes dir for unchecked-task grep")
    p.add_argument(
        "--owner-container",
        action="store_true",
        help="仅打印机械 owner-container (get_identity) 供 frontmatter 逐字粘贴, 替代手填",
    )
    a = p.parse_args(argv)
    if a.owner_container:
        oc = owner_container()
        print(oc if oc is not None else "")
        return 0 if oc is not None else 1
    if not a.snapshot_json:
        p.error("--snapshot-json required unless --owner-container")
    with open(a.snapshot_json, encoding="utf-8") as f:
        snapshot = json.load(f)
    result = assemble_from_snapshot(snapshot, changes_dir=a.changes_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

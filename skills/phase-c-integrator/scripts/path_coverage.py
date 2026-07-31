#!/usr/bin/env python3
"""Workflow 触发覆盖评估器 — C.2.4 path coverage (aria-plugin #122, v1.65.0+).

判定「本次变更 (main...pr 三点 diff) 是否可能触发任何自动 CI workflow」, 供
pre_merge_gate.gate_check 在 (a) PR CI 查询之前调用。三值 decision:

- covered        — 至少一个 workflow 会 (或无法排除会) 为本变更自动触发
- not_applicable — 高置信零覆盖: 全部 workflow 解析成功且确定不会自动触发
- unknown        — 评估自身失败 (git diff 失败 / workflow 解析失败且无 covered)

Spec SOT: openspec/changes/phase-c-gate-path-coverage-not-applicable/proposal.md
核心原则 (D2, fail-toward-covered): 任何不确定 → 行为退回现状 (gate 照常查询/等待);
绝不把「解析不了」当「无覆盖」。unknown 与 covered 在 gate 层行为一致, 但 decision
字面与 reason 可辨 (D9 可观测性: 评估器自身失效必须可见)。

执行上下文契约 (§0/D11):
- 仓根 = 本进程 cwd 的 `git rev-parse --show-toplevel`; 调用方须在执行 C.2 合并的
  目标仓根内调用 (子模块合并 → 子模块根; 主仓 PR → 主仓根)。
- main_branch 由调用方显式传真值 (不依赖 "main" 默认)。
- diff 用 `--no-renames`: rename 呈现为 delete+add 两条, 新旧路径都参与匹配。
- 假定完整 clone; shallow 缺 merge-base → git-diff-failed → unknown, 不误判。

判定规则 1-8 (§1, 互斥+全覆盖, 此序即数据依赖执行序):
  1. git diff 失败              → unknown,        reason=git-diff-failed: <err>
  2. diff 成功但输出为空        → covered,        reason=empty-diff
  3. 变更含 workflows 目录下文件 → covered,        reason=workflow-files-changed
  4. 零 workflow 文件 (前置短路) → not_applicable, reason=no-workflow-files
  5. 逐 workflow 解析 (中间步骤, 不产终态)
  6. 任一 workflow 判 covered   → covered,        reason=workflow-trigger-matched
  7. 无 covered ∧ 有 parse 失败 → unknown,        reason=workflow-parse-failed: <files>
  8. 全解析成功且全不触发       → not_applicable, reason=no-triggering-paths

stdlib-only (先例: state-scanner custom_checks minimal parser / lib/detailed_tasks)。
本模块永不 raise — 内部全捕获, 失败落 unknown + reason。
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import Any

WORKFLOW_DIRS = (".forgejo/workflows", ".gitea/workflows", ".github/workflows")

# D7: 「零覆盖贡献」触发键 = 精确白名单两键。其余任何未建模顶层触发键
# (pull_request_target / repository_dispatch / workflow_call / ...) 是否自动触发
# 无法确知 → 按未建模构造, 该 workflow 记 covered (R2-C1: pull_request_target
# 是真自动触发, 按字面归零贡献会产生假 not_applicable)。
NON_AUTO_TRIGGER_KEYS = frozenset({"workflow_dispatch", "schedule"})
AUTO_TRIGGER_KEYS = frozenset({"push", "pull_request"})

_GIT_TIMEOUT = 15


def _result(
    decision: str,
    reason: str,
    workflows_scanned: int = 0,
    matched_workflows: list[str] | None = None,
    changed_files_count: int = 0,
) -> dict[str, Any]:
    return {
        "decision": decision,
        "workflows_scanned": workflows_scanned,
        "matched_workflows": matched_workflows or [],
        "changed_files_count": changed_files_count,
        "reason": reason,
    }


def _run_git(args: list[str], cwd: str | None) -> tuple[bool, str, str]:
    """Run git, return (ok, stdout, err_summary). Never raises."""
    try:
        proc = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
            cwd=cwd,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return False, "", f"{type(exc).__name__}: {exc}"
    if proc.returncode != 0:
        summary = (proc.stderr or "").strip().splitlines()
        return False, "", summary[0] if summary else f"git exit {proc.returncode}"
    return True, proc.stdout or "", ""


def _repo_root() -> tuple[str | None, str]:
    """仓根 = cwd 的 rev-parse --show-toplevel (D11)。失败 → (None, err)。"""
    ok, out, err = _run_git(["rev-parse", "--show-toplevel"], cwd=None)
    if not ok:
        return None, err
    root = out.strip()
    return (root, "") if root else (None, "empty toplevel")


def _strip_comment(line: str) -> str:
    """剥行内 # 注释 (quote-aware 简化版: 引号内 # 不剥)。"""
    out = []
    quote: str | None = None
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            out.append(ch)
            continue
        if ch == "#":
            break
        out.append(ch)
    return "".join(out)


def _unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def _glob_to_regex(pattern: str) -> re.Pattern | None:
    """Workflow paths glob → regex。`**` 跨目录 / `*` 单段 / `?` 单字符。

    含未建模语法 (字符类 `[` / 否定前缀 `!` / brace / 反斜杠转义等) → 返回 None,
    调用方一律按「判定为匹配」处理 (BA-1: matcher 层 fail-toward-covered, SC-14)。
    大小写敏感 (QA-8)。
    """
    if not pattern or pattern.startswith("!"):
        return None
    out: list[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        ch = pattern[i]
        if ch == "*":
            if pattern[i : i + 2] == "**":
                out.append(".*")
                i += 2
            else:
                out.append("[^/]*")
                i += 1
        elif ch == "?":
            out.append("[^/]")
            i += 1
        elif ch in "[]{}\\+!":
            return None  # 未建模语法 → caller 判匹配
        else:
            out.append(re.escape(ch))
            i += 1
    try:
        return re.compile("^" + "".join(out) + "$")
    except re.error:
        return None


def _pattern_matches_any(pattern: str, changed_files: list[str]) -> bool:
    rx = _glob_to_regex(pattern)
    if rx is None:
        return True  # 未建模语法 → 判匹配 → covered 方向
    return any(rx.match(f) for f in changed_files)


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


_TOP_KEY_RE = re.compile(r"^([A-Za-z_\"'][A-Za-z0-9_.\-\"']*):(\s|$)")
_ON_SCALAR_RE = re.compile(r"^(?:\"on\"|'on'|on):\s*(.+)$")


def _parse_workflow(text: str) -> dict[str, Any]:
    """最小 YAML 触发子集解析: 只认 `on:` 块的结构。

    返回 {"parse_ok": bool, "covered_uncertain": bool, "triggers": [...]}:
    - covered_uncertain=True — 含未建模自动触发键 / paths-ignore / 无法辨识的
      构造级内容 → 该 workflow 按 covered (per-workflow 级不确定, D2)。
    - triggers: [{"key": "push"|"pull_request", "paths": [glob,...] | None}]
      paths=None 表示该触发无 paths 过滤 (→ 全触发, covered)。
    - parse_ok=False — 文件级结构解析失败 (读不出 on: 块) → parse_failed。
    """
    lines = text.splitlines()
    # 定位 0 缩进 on: 行 (标量 / flow 列表 / 块映射三形, D6)。
    on_idx = None
    scalar_val: str | None = None
    for i, raw in enumerate(lines):
        line = _strip_comment(raw).rstrip()
        if not line or _indent_of(raw) != 0:
            continue
        m = _ON_SCALAR_RE.match(line)
        if m:
            on_idx, scalar_val = i, m.group(1).strip()
            break
        if line in ("on:", '"on":', "'on':"):
            on_idx, scalar_val = i, None
            break
    if on_idx is None:
        return {"parse_ok": False, "covered_uncertain": False, "triggers": []}

    triggers: list[dict[str, Any]] = []
    covered_uncertain = False

    if scalar_val is not None:
        # 标量形 `on: push` / flow 列表形 `on: [push, pull_request]` — 无 paths 过滤。
        keys = (
            [k.strip() for k in scalar_val.strip("[]").split(",")]
            if scalar_val.startswith("[")
            else [scalar_val]
        )
        for k in keys:
            k = _unquote(k)
            if not k:
                continue
            if k in AUTO_TRIGGER_KEYS:
                triggers.append({"key": k, "paths": None})
            elif k not in NON_AUTO_TRIGGER_KEYS:
                covered_uncertain = True  # 未建模触发键 (R2-C1)
        return {
            "parse_ok": True,
            "covered_uncertain": covered_uncertain,
            "triggers": triggers,
        }

    # 块映射形: on: 块延伸到下一个 0 缩进顶层键 (或 EOF)。
    block: list[str] = []
    for raw in lines[on_idx + 1 :]:
        stripped = _strip_comment(raw).rstrip()
        if stripped and _indent_of(raw) == 0:
            if _TOP_KEY_RE.match(stripped):
                break
        block.append(raw)

    # 触发键 = 块内最浅缩进层的 `key:` 行。
    key_indent = None
    i = 0
    while i < len(block):
        raw = block[i]
        line = _strip_comment(raw).rstrip()
        if not line.strip():
            i += 1
            continue
        ind = _indent_of(raw)
        if key_indent is None:
            key_indent = ind
        if ind != key_indent:
            i += 1
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_\-]*):\s*(.*)$", line.strip())
        if not m:
            covered_uncertain = True  # 认不出的构造 (anchors 等) → covered 方向
            i += 1
            continue
        key = m.group(1)
        # 收集该触发键的子块 (更深缩进直到回到 key_indent 或更浅)。
        sub: list[str] = []
        j = i + 1
        while j < len(block):
            nraw = block[j]
            nline = _strip_comment(nraw).rstrip()
            if nline.strip() and _indent_of(nraw) <= key_indent:
                break
            sub.append(nraw)
            j += 1
        if key in AUTO_TRIGGER_KEYS:
            paths, sub_uncertain = _extract_paths(sub)
            if sub_uncertain:
                covered_uncertain = True
            triggers.append({"key": key, "paths": paths})
        elif key in NON_AUTO_TRIGGER_KEYS:
            pass  # 零覆盖贡献 (D7 精确白名单)
        else:
            covered_uncertain = True  # pull_request_target 等未建模触发键 (R2-C1)
        i = j
    return {
        "parse_ok": True,
        "covered_uncertain": covered_uncertain,
        "triggers": triggers,
    }


def _extract_paths(sub_lines: list[str]) -> tuple[list[str] | None, bool]:
    """从触发子块提取 `paths:` 列表。返回 (paths | None, uncertain)。

    - `paths:` 缺席 → (None, False): 无过滤 → 全触发。
    - `paths-ignore:` 在场 → (不论 paths) uncertain=True (未建模否定过滤, D2)。
    - `paths: [a, b]` flow 形与块列表 `- 'glob'` 形都认。
    - paths: 后无任何列表项 → uncertain (结构可疑, covered 方向)。
    """
    paths: list[str] | None = None
    uncertain = False
    i = 0
    while i < len(sub_lines):
        raw = sub_lines[i]
        line = _strip_comment(raw).strip()
        if not line:
            i += 1
            continue
        if line.startswith("paths-ignore:"):
            uncertain = True
            i += 1
            continue
        if line.startswith("paths:"):
            rest = line[len("paths:") :].strip()
            items: list[str] = []
            if rest:
                if rest.startswith("[") and rest.endswith("]"):
                    items = [
                        _unquote(x) for x in rest[1:-1].split(",") if x.strip()
                    ]
                else:
                    uncertain = True  # paths: <非列表标量> — 认不出
            else:
                base_ind = _indent_of(raw)
                j = i + 1
                while j < len(sub_lines):
                    nraw = sub_lines[j]
                    nline = _strip_comment(nraw).strip()
                    if not nline:
                        j += 1
                        continue
                    if _indent_of(nraw) <= base_ind:
                        break
                    if nline.startswith("- "):
                        items.append(_unquote(nline[2:]))
                    elif nline.startswith("-") and len(nline) > 1:
                        items.append(_unquote(nline[1:]))
                    else:
                        break
                    j += 1
                if not items:
                    uncertain = True
            if items:
                paths = items
            i += 1
            continue
        i += 1
    return paths, uncertain


def _workflow_covers(parsed: dict[str, Any], changed_files: list[str]) -> bool:
    """单 workflow 覆盖判定 (parse_ok=True 前提)。

    covered ⟺ 含未建模构造 (covered_uncertain) ∨ 任一自动触发满足:
    paths=None (无过滤) ∨ 任一 pattern 命中任一 changed file (OR 语义, QA-4:
    push 与 pull_request 逐触发独立判定)。
    """
    if parsed["covered_uncertain"]:
        return True
    for trig in parsed["triggers"]:
        paths = trig["paths"]
        if paths is None:
            return True
        if any(_pattern_matches_any(p, changed_files) for p in paths):
            return True
    return False


def _find_workflow_files(root: str) -> list[str]:
    """三目录下 *.yml / *.yaml, 相对仓根路径, 排序稳定。"""
    found: list[str] = []
    for d in WORKFLOW_DIRS:
        full = os.path.join(root, d)
        if not os.path.isdir(full):
            continue
        try:
            names = sorted(os.listdir(full))
        except OSError:
            continue
        for name in names:
            if name.endswith((".yml", ".yaml")) and os.path.isfile(
                os.path.join(full, name)
            ):
                found.append(f"{d}/{name}")
    return found


def evaluate_path_coverage(
    main_branch: str, pr_branch: str, repo_root: str | None = None
) -> dict[str, Any]:
    """入口。按判定规则 1-8 产出 decision/reason (docstring 见模块头)。永不 raise。"""
    try:
        return _evaluate(main_branch, pr_branch, repo_root)
    except Exception as exc:  # 兜底: 评估器自身 bug 不得影响 gate (D2)
        return _result("unknown", f"git-diff-failed: internal error {exc!r}")


def _evaluate(
    main_branch: str, pr_branch: str, repo_root: str | None
) -> dict[str, Any]:
    root = repo_root
    if root is None:
        root, err = _repo_root()
        if root is None:
            return _result("unknown", f"git-diff-failed: {err}")

    # 规则 1: git diff (三点 merge-base, --no-renames 使 rename 呈 delete+add)。
    ok, out, err = _run_git(
        [
            "diff",
            "--name-only",
            "--no-renames",
            f"{main_branch}...{pr_branch}",
        ],
        cwd=root,
    )
    if not ok:
        return _result("unknown", f"git-diff-failed: {err}")
    changed = [ln.strip() for ln in out.splitlines() if ln.strip()]
    n_changed = len(changed)

    workflow_files = _find_workflow_files(root)
    n_wf = len(workflow_files)

    # 规则 2: 空 diff — 异常形态, 保守。
    if not changed:
        return _result("covered", "empty-diff", n_wf, [], 0)

    # 规则 3: 对 CI 配置本身动刀的 PR 永不 not_applicable (D10/QA-1)。
    dirs_prefix = tuple(d + "/" for d in WORKFLOW_DIRS)
    if any(f.startswith(dirs_prefix) for f in changed):
        return _result("covered", "workflow-files-changed", n_wf, [], n_changed)

    # 规则 4: 零 workflow 文件 — 循环前置短路 (消除规则 8 空真重叠)。
    if n_wf == 0:
        return _result(
            "not_applicable", "no-workflow-files", 0, [], n_changed
        )

    # 规则 5: 逐 workflow 解析 (中间步骤)。
    matched: list[str] = []
    parse_failed: list[str] = []
    for rel in workflow_files:
        try:
            with open(
                os.path.join(root, rel), encoding="utf-8", errors="replace"
            ) as fh:
                text = fh.read()
        except OSError:
            parse_failed.append(rel)
            continue
        parsed = _parse_workflow(text)
        if not parsed["parse_ok"]:
            parse_failed.append(rel)
            continue
        if _workflow_covers(parsed, changed):
            matched.append(rel)

    # 规则 6: covered 优先于 parse_failed (真实覆盖是更强信号, BA-4)。
    if matched:
        return _result(
            "covered", "workflow-trigger-matched", n_wf, matched, n_changed
        )
    # 规则 7: 无 covered ∧ 有解析失败 — 没读懂的 workflow 可能覆盖。
    if parse_failed:
        return _result(
            "unknown",
            "workflow-parse-failed: " + ", ".join(parse_failed),
            n_wf,
            [],
            n_changed,
        )
    # 规则 8: 高置信零覆盖。
    return _result(
        "not_applicable", "no-triggering-paths", n_wf, [], n_changed
    )

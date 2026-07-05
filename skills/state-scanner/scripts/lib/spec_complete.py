#!/usr/bin/env python3
"""Single executable SOT for OpenSpec spec completeness verdict (契约 A, #134)
+ 归档完成声称真实性证据闸 (C 分级 + D auto-issue payload, #95, TG-1).

Spec (契约 A, #134): openspec/archive/.../aria-archive-completeness-gate/ (DEC-20260609-001)
Spec (C/D 扩展, #95): openspec/changes/aria-archive-gate-runtime-reality/ (DEC-20260704-003)

    is_spec_complete(spec_dir) -> {"complete": bool, "reason": str}

判定逻辑 (A1.2, 无歧义形式):

    complete := (tasks.md 存在 AND 全 [x] AND 无 inline carry-forward/defer 注释)
                OR (_normalize_status(Status) == 'done')

- tasks.md absent → verdict 仅由 Status 归一化决定 (绝非 vacuously True,
  否则反向击穿 gap(a) Approved-only 即归档旁路)。
- tasks.md 存在但 0 个 checkbox → tasks 分支不可验证, 同样回落 Status 分支
  (同一 vacuous-truth 防线)。
- ``implemented`` 不算 complete (DEC §3 D2: post-merge 但未 verify/archive-ready)。
- carry-forward 子类 (gap(b)): 全 [x] 但含 defer/carry-forward inline 注释 →
  complete=False。复用 ``lib/carry_forward.py`` 同一正则, 不双写。
- fail-soft (A1.3, stdlib-only): spec_dir 无 proposal.md / OSError →
  ``complete=False`` + 诊断 reason; 文本读取一律 ``errors='replace'``。

--------------------------------------------------------------------------
#95 扩展 (TG-1, DEC-20260704-003): ``gate_result(spec_dir) -> {...}``
--------------------------------------------------------------------------

完成度 (#134) 验的是 checkbox **存在**, 不验其**属实**。``gate_result`` 新增一条
**独立** (与 ``complete`` 正交, 可 ``complete=True ∧ verdict="block"``) 的
tri-state 判定轴, 核验 tasks.md 里代码集成类完成声称 (关键词: 集成/接线/wire/
integration/调用/registered/hook) 有无真实生产语义引用:

    gate_result(spec_dir) -> {
        "complete": bool,             # 复用 #134 is_spec_complete, 不改动
        "complete_reason": str,
        "verdict": "pass" | "warn" | "block",
        "blocking_reasons": [str, ...],
        "warnings": [str, ...],
        "unverified_claims": [{"claim": str, "reason": str, "symbols": [str]}],
        "d_payload": {...} | None,    # TASK-011, 供 openspec-archive Step2 建 issue
        "soft_errors": [str, ...],    # TASK-008 fail-soft 诊断轨迹 (从不因此 block)
    }

管线 (每步 fail-soft, 见 TASK-008):
  1. 符号提取 (TASK-002, ``extract_claim_symbols``) — 从 detailed-tasks.yaml
     ``deliverables:`` (按 tasks.md 行号前缀 parent 关联) + proposal.md
     ``### Key Deliverables`` + tasks.md 行内 backtick/路径 三源提取候选符号。
     提取不到 → 不可核验, 计入 unverified_claims, 不 block (非猜)。
  2. 生产引用核验 (TASK-003/004, ``classify_symbol_liveness``) — 语义级
     (剥注释/docstring 后) 匹配: (i) 代码引用 (import/调用/属性/装饰器/赋值别名)
     (ii) dynamic-dispatch (getattr/importlib/globals 字符串) (iii) aria-plugin
     集成面 (SKILL.md Bash 真调用 / hooks.json·config 注册) (iv) 通用调用面
     (shell/Makefile/CI 按字面脚本路径调用)。搜索排除: *.md 散文 (SKILL.md 除外,
     单独按 Bash block 判定) / 声明性 *.yaml·*.yml (CI workflow yaml 除外) /
     测试文件 (test_*/`*_test.py`/tests//conftest.py) / dogfood·ops 目录
     (``.aria/scripts/dogfood/``) / 符号自身定义文件。
  3. fail-toward-warn (TASK-005) — 三态: alive(不 block) / dead(所有生产出现
     全属"不算引用"或零出现 → block 候选) / ambiguous(出现但不落入任一清单 →
     降级 warn, 不 block)。
  4. 产物抽验 (TASK-006, ``classify_artifact_claim``) — dogfood/benchmark/deploy
     类声称核验可链接产物 (如 ab-results 路径) 是否存在; 遥测类声称 (fix A
     out-of-scope) 恒走 warn 通道, 不列产物类别。
  5. C-block/C-warn 装配 (TASK-009/010) 汇入 ``gate_result``; D payload
     (TASK-011, ``_build_d_payload``) 聚合 deferred 未勾项 + 全部 unverified_claims
     (无论是否 ack) 生成 issue body + 去重 marker ``<!-- archive-tracker:{spec_id} -->``
     (实际 Forgejo issue 创建是 TG-2 openspec-archive Step2 SKILL.md Bash 侧职责,
     本模块只产 payload)。

verdict 单调升级 (pass < warn < block), 从不因后续判定降级。已知局限 (非绕过口,
显式承认, 见 proposal §What Changes 1 known-limitation): 本模块是**静态**正则
启发式, 非 AST/语义分析器 —— 字符串字面量/非常规 wiring 形态可能被误分类;
误分类方向刻意偏向"不 block"(fail-toward-warn), 详见各函数 docstring。

TASK-014 determination (collectors/openspec.py additive surface, TG-4 归属,
非本 TG-1 交付物 — 记录于此供 TG-4 agent 参考): D 侧 tracker (Forgejo issue)
是外部产物, state-scanner 现有 opt-in ``issue_status`` collector (Phase 1.13)
已通用覆盖"是否有 open issue"关切, 无需为本 gate 专门新增字段。C-warn 侧
``unverified_claims`` 会被 TG-2 (TASK-012) 写入归档 proposal.md frontmatter
(镜像 #134 ``archive_type`` 读取模式, 见 ``collectors/openspec.py::_read_archive_type``);
是否新增对称的 ``_read_unverified_claims`` reader 取决于 TASK-012 最终写入的
frontmatter 字段名/格式 (未定, TASK-012 尚未实现) —— 本 agent 不预先假设该格式
单方面改 collectors/openspec.py (协调风险), 留给 TASK-012 落地后的 TG-4 agent
判定 (若需, 应为 additive 字段 + ``.get(field, [])`` 防 KeyError, 不 bump
``snapshot_schema_version``)。

Thin CLI (供 SKILL.md 的 AI agent 经 Bash 调用 — 无法 import Python):

    python3 spec_complete.py <spec_dir>                # 既有 #134 二元 gate (不变)
    python3 spec_complete.py --gate <spec_dir>          # 新增 #95 tri-state gate

stdout 输出 verdict JSON (ensure_ascii 默认 True, 防 Windows GBK stdout 异常);
exit code: 0 = complete/allow(pass|warn) / 1 = incomplete/block / 2 = usage 或非预期错误。

多入口一致 verdict 不变量 (AC-1) — 同一 spec_dir 必须得到相同 JSON:
- collectors/openspec.py (Python import, A2.3)
- openspec-archive SKILL.md Step1 完成 gate (Bash, TG-B B1.2; #95 TG-2 C-gate)
- phase-d-closer D.2 skip_evaluation (Bash, TG-B B4.1; #95 TG-3 D.2 gate)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Dual-context imports (same pattern as collectors/openspec.py header note):
#   (a) imported as lib.spec_complete / package context — relative import works;
#   (b) run as a script (thin CLI) or imported as a bare module — __package__
#       is empty, relative import raises ImportError → insert the needed dirs
#       onto sys.path and import absolutely. The `lib` top-level name is
#       deliberately avoided (may be bound to state-scanner/lib by
#       handoff_multibranch.py).
# ---------------------------------------------------------------------------
try:
    from .carry_forward import _extract_carry_forward_annotations
except ImportError:
    _LIB_DIR = str(Path(__file__).resolve().parent)
    if _LIB_DIR not in sys.path:
        sys.path.insert(0, _LIB_DIR)
    from carry_forward import _extract_carry_forward_annotations  # type: ignore[import]

# Status 提取/归一化复用 collectors/_status.py 唯一 SOT (A1.2)。CLI 上下文中
# scripts/ 不在 sys.path → import 前插入 scripts/ (= 本文件 parent.parent)。
try:
    from collectors._status import _extract_status, _normalize_status
except ImportError:
    _SCRIPTS_DIR = str(Path(__file__).resolve().parent.parent)
    if _SCRIPTS_DIR not in sys.path:
        sys.path.insert(0, _SCRIPTS_DIR)
    from collectors._status import _extract_status, _normalize_status  # type: ignore[import]

# Markdown task checkbox: `- [x]` / `* [ ]` 等。捕获括号内单字符; checked 仅
# 认 x/X — 其它标记 (如 `[~]`) 视为未完成 (gate 宁紧勿松)。
_CHECKBOX_RE = re.compile(r"^\s*[-*]\s*\[(.)\]", re.MULTILINE)


def is_spec_complete(spec_dir: str | Path) -> dict:
    """Return ``{"complete": bool, "reason": str}`` for one OpenSpec change dir.

    纯函数 (除文件读取外无副作用); 任何 I/O 失败 fail-soft 为
    ``complete=False`` + 诊断 reason, 不抛异常 (OSError 之外的意外异常由
    CLI 层兜底为 exit 2)。
    """
    spec_dir = Path(spec_dir)
    proposal = spec_dir / "proposal.md"

    # ── fail-soft 前置 (A1.3): proposal.md 缺失/不可读 → gate 不放行 ──
    if not proposal.is_file():
        return {
            "complete": False,
            "reason": f"proposal.md not found in {spec_dir} — malformed spec dir, gate stays closed",
        }
    try:
        proposal_text = proposal.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"complete": False, "reason": f"proposal.md unreadable ({e}) — gate stays closed"}

    normalized = _normalize_status(_extract_status(proposal_text))

    # ── tasks.md 分支 ──
    tasks_file = spec_dir / "tasks.md"
    tasks_reason: str
    if not tasks_file.is_file():
        tasks_reason = "tasks.md absent — verdict by normalized Status only"
    else:
        try:
            tasks_text = tasks_file.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            tasks_reason = f"tasks.md unreadable ({e})"
        else:
            boxes = _CHECKBOX_RE.findall(tasks_text)
            unchecked = [b for b in boxes if b not in ("x", "X")]
            if not boxes:
                tasks_reason = "tasks.md has no checkboxes — tasks branch unverifiable"
            elif unchecked:
                tasks_reason = f"tasks.md has {len(unchecked)}/{len(boxes)} unchecked task(s)"
            else:
                annotations = _extract_carry_forward_annotations(tasks_text)
                if annotations:
                    # gap(b) 闭合: 全 [x] 但实施被 inline 注释 defer
                    tasks_reason = (
                        f"全[x] 但含 {len(annotations)} 条 carry-forward/defer 注释"
                    )
                else:
                    return {
                        "complete": True,
                        "reason": (
                            f"tasks.md 全 [x] ({len(boxes)} task(s), "
                            "无 carry-forward/defer 注释)"
                        ),
                    }

    # ── Status 分支 (OR 的右半): 仅 normalized == 'done' 放行 ──
    if normalized == "done":
        return {"complete": True, "reason": f"normalized Status == 'done' ({tasks_reason})"}

    reason = f"{tasks_reason}; normalized Status = '{normalized}' (≠ done)"
    if normalized == "implemented":
        # DEC §3 D2 rationale 硬编码: implemented = post-merge 未 verified
        reason += " — implemented 不算 complete (DEC-20260609-001 §3 D2)"
    return {"complete": False, "reason": reason}


# =============================================================================
# #95 TG-1 扩展 — C 分级证据闸 + D payload (DEC-20260704-003)
# =============================================================================

# ---------------------------------------------------------------------------
# TASK-002: 符号提取
# ---------------------------------------------------------------------------

# tasks.md [x] 行的代码集成类完成声称关键词 (proposal §What Changes 1)。"集成" 用负向
# 前瞻排除 "集成测试" —— 后者是测试覆盖声称 ("unit + integration test suite"), 与本
# 分级闸要核验的"组件 X 被接入生产"完全不同语义, 误配会把测试任务的 deliverables
# (往往就是 test_*.py 文件名) 错当成集成符号核验 (dogfood 实测踩坑: golden fixture
# 里 "P1 单元 + 集成测试" 声称错误触发, 提取到的 test_p1_layer_h 只活在
# ab-results 缓存 JSON 里, 制造无意义 warn 噪音)。
_INTEGRATION_KEYWORD_PATTERNS = (
    re.compile(r"集成(?!测试)"),
    re.compile(r"接线"),
    re.compile(r"wire", re.IGNORECASE),
    re.compile(r"integration", re.IGNORECASE),
    re.compile(r"调用"),
    re.compile(r"registered", re.IGNORECASE),
    re.compile(r"hook", re.IGNORECASE),
)


def _line_has_integration_keyword(line: str) -> bool:
    return any(p.search(line) for p in _INTEGRATION_KEYWORD_PATTERNS)

# 任意 checkbox 行 (含未勾选) — 捕获 (mark, 可选 parent_id 数字前缀, 行文本)。
# 与既有 `_CHECKBOX_RE` 分开维护 (不复用/不修改 #134 的正则, TASK-001 "不重写")。
_CHECKBOX_ANY_RE = re.compile(
    r"^\s*[-*]\s*\[(.)\]\s*(?:([0-9]+(?:\.[0-9]+)*)\s+)?(.*)$", re.MULTILINE
)

# 路径式符号候选: 以已知代码扩展名结尾的 token (deliverables/Key Deliverables/
# tasks.md 行内 均适用)。
_CODE_EXT_RE = re.compile(r"([A-Za-z0-9_./\-]+\.(?:py|sh|js|mjs|cjs|ts|rb|go))\b")

# tasks.md 行内 backtick 裸 identifier (无扩展名), 如 `` `phase1_gate` ``。
_BACKTICK_IDENTIFIER_RE = re.compile(r"`([a-zA-Z_][a-zA-Z0-9_.]*)`")

# detailed-tasks.yaml 任务条目边界: `  - id: TASK-XXX`。
_TASK_ID_LINE_RE = re.compile(r"^([ \t]*)-\s*id:\s*(\S+)", re.MULTILINE)

# proposal.md Key Deliverables 小节标题 (英文惯例 + 中文兜底)。
_KEY_DELIVERABLES_HEADING_RE = re.compile(
    r"^#{1,4}\s*(?:Key Deliverables|关键交付物)\s*$", re.MULTILINE | re.IGNORECASE
)


def _iter_task_items(tasks_md_text: str) -> list[dict]:
    """Parse every checkbox line in tasks.md — checked/unchecked/parent_id/text.

    Fail-soft: 正则不匹配的行天然被跳过 (非 checkbox 行), 不算异常。
    """
    items = []
    for m in _CHECKBOX_ANY_RE.finditer(tasks_md_text):
        mark, parent_id, line = m.group(1), m.group(2), (m.group(3) or "").strip()
        items.append(
            {"checked": mark in ("x", "X"), "mark": mark, "parent_id": parent_id, "line": line}
        )
    return items


def _stem_from_path_token(token: str) -> str:
    """basename without extension, from a path-like token (e.g. 'a/b/foo.py' → 'foo')."""
    return Path(token.rstrip("/")).stem


def _is_test_shaped_symbol(symbol: str, path_token: str | None) -> bool:
    """Filter out candidate symbols whose deliverable is itself a TEST artifact
    (a test-file path, or a bare backtick identifier conventionally named as a
    test) — these are test-coverage claims ("写单元测试"), not "component X
    wired into production" claims. Without this filter, any test-suite-creation
    deliverable would SYSTEMATICALLY false-block once test paths are excluded
    from the production-reference search (§TASK-003/004) — a test symbol's
    only natural home IS a test file, so it can never show a non-test
    occurrence. dogfood found this regression across multiple real archived
    specs (``test_scan_integration``, ``test_t7_crash_recovery``,
    ``secret-scan.test``, etc. from test-suite tasks) before this filter existed.
    """
    if path_token and _is_test_path(path_token):
        return True
    name = symbol.rsplit("/", 1)[-1]
    return name.startswith("test_") or name.endswith("_test")


def _extract_symbol_candidates_from_strings(items: list[str]) -> list[dict]:
    """Extract ``{"symbol": stem, "path": raw_path_token}`` from raw deliverable/
    prose strings — any substring matching a recognized code-file path pattern.
    Test-shaped candidates (``_is_test_shaped_symbol``) are dropped at
    extraction time, not merely excluded from the search later.
    """
    out: list[dict] = []
    for s in items:
        for m in _CODE_EXT_RE.finditer(s):
            path_token = m.group(1)
            stem = _stem_from_path_token(path_token)
            if stem and not _is_test_shaped_symbol(stem, path_token):
                out.append({"symbol": stem, "path": path_token})
    return out


def _extract_inline_symbols_from_tasks_line(line: str) -> list[dict]:
    """tasks.md 关联行内的代码路径/backtick identifier (proposal §What Changes 1)."""
    out = _extract_symbol_candidates_from_strings([line])
    for m in _BACKTICK_IDENTIFIER_RE.finditer(line):
        ident = m.group(1)
        if "." not in ident and not _is_test_shaped_symbol(ident, None):
            # 已被上面路径式提取覆盖的带扩展名 token 不重复计入; 裸 test_* 名同样过滤
            out.append({"symbol": ident, "path": None})
    return out


def _extract_key_deliverables_section(proposal_text: str) -> list[str]:
    """Return bullet lines under proposal.md's '### Key Deliverables' heading."""
    m = _KEY_DELIVERABLES_HEADING_RE.search(proposal_text)
    if not m:
        return []
    rest = proposal_text[m.end():]
    stop = re.search(r"^\s*(#{1,4}\s|---\s*$)", rest, re.MULTILINE)
    section = rest[: stop.start()] if stop else rest
    return [ln.strip() for ln in section.splitlines() if ln.strip().startswith(("-", "*"))]


def _split_task_blocks(detailed_tasks_text: str) -> list[tuple[str, str]]:
    """Slice detailed-tasks.yaml into ``[(task_id, block_text), ...]`` by ``- id:`` boundaries.

    Light line-based scanner (stdlib-only, NOT a general YAML parser — mirrors
    the scoped-parser convention already used by collectors/custom_checks.py).
    """
    matches = list(_TASK_ID_LINE_RE.finditer(detailed_tasks_text))
    blocks = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(detailed_tasks_text)
        blocks.append((m.group(2), detailed_tasks_text[start:end]))
    return blocks


def _extract_yaml_key_list(block_text: str, key: str) -> list[str]:
    """Extract a YAML list value for `key` within one task-entry block.

    Supports both flow style (``key: ["a", "b"]``) and block style
    (``key:\\n  - a\\n  - b``) — the two shapes observed in detailed-tasks.yaml.
    Not a general YAML parser (deliberately scoped, stdlib-only, fail-soft: any
    unrecognized shape just yields ``[]``, never raises).
    """
    escaped_key = re.escape(key)
    m = re.search(rf"^[ \t]*{escaped_key}:\s*\[(.*?)\]", block_text, re.MULTILINE | re.DOTALL)
    if m:
        pairs = re.findall(r'"([^"]*)"|\'([^\']*)\'', m.group(1))
        return [a or b for a, b in pairs]

    m = re.search(rf"^([ \t]*){escaped_key}:\s*$", block_text, re.MULTILINE)
    if not m:
        return []
    key_indent = len(m.group(1))
    items: list[str] = []
    for line in block_text[m.end():].splitlines():
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" \t"))
        if indent <= key_indent:
            break
        stripped = line.strip()
        if stripped.startswith("- "):
            items.append(stripped[2:].strip())
        elif items:
            items[-1] = items[-1] + " " + stripped  # wrapped continuation line
        else:
            break
    return items


def _extract_deliverables_for_parent(detailed_tasks_text: str, parent_id: str) -> list[str]:
    """Return raw ``deliverables:`` strings for detailed-tasks.yaml entries whose
    ``parent:`` field textually names `parent_id` (e.g. tasks.md item "2.5" ↔
    ``parent: "2.5"`` or composite ``parent: "2.4 + 4.2-4.5 + 5.1"``).
    """
    if not parent_id:
        return []
    results: list[str] = []
    token_re = re.compile(r"(?<![\d.])" + re.escape(parent_id) + r"(?![\d.])")
    for _task_id, block in _split_task_blocks(detailed_tasks_text):
        m = re.search(r"^[ \t]*parent:\s*(.+?)\s*$", block, re.MULTILINE)
        if not m:
            continue
        parent_field = m.group(1).strip().strip("\"'")
        if parent_field and token_re.search(parent_field):
            results.extend(_extract_yaml_key_list(block, "deliverables"))
    return results


def extract_claim_symbols(spec_dir: str | Path, claim: dict) -> dict:
    """TASK-002 entry point: extract candidate symbols for one tasks.md `[x]` claim.

    ``claim``: ``{"parent_id": str|None, "line": str}`` (as produced by
    ``_iter_task_items``). Extraction sources (proposal §What Changes 1, in
    priority-agnostic union — all three are tried, results de-duplicated):
      1. tasks.md 行内 backtick identifier / path token (same line as the claim)
      2. detailed-tasks.yaml — the task entry whose ``parent:`` names this claim's
         item number → its ``deliverables:`` list
      3. proposal.md ``### Key Deliverables`` bullets (spec-wide fallback)

    Returns ``{"symbols": [str,...], "extractable": bool, "sources": {...},
    "definition_paths_by_symbol": {symbol: {path,...}}, "soft_errors": [...]}``.
    ``extractable=False`` (无法提取符号) is itself a valid, expected outcome —
    the caller must route it to "unverifiable" (warn), never guess a symbol.
    fail-soft (TASK-008): any single source failing does not affect the others.
    """
    spec_dir = Path(spec_dir)
    candidates: list[dict] = []
    sources: dict[str, list[str]] = {}
    soft_errors: list[str] = []

    try:
        inline = _extract_inline_symbols_from_tasks_line(claim.get("line", ""))
        if inline:
            sources["tasks_inline"] = [c["symbol"] for c in inline]
        candidates.extend(inline)
    except Exception as e:  # pragma: no cover - defensive, regex-only logic
        soft_errors.append(f"tasks_inline extraction failed: {e}")

    try:
        dt_path = spec_dir / "detailed-tasks.yaml"
        parent_id = claim.get("parent_id")
        if dt_path.is_file() and parent_id:
            dt_text = dt_path.read_text(encoding="utf-8", errors="replace")
            deliverables = _extract_deliverables_for_parent(dt_text, parent_id)
            dt_candidates = _extract_symbol_candidates_from_strings(deliverables)
            if dt_candidates:
                sources["detailed_tasks_deliverables"] = [c["symbol"] for c in dt_candidates]
            candidates.extend(dt_candidates)
    except OSError as e:
        soft_errors.append(f"detailed-tasks.yaml read failed: {e}")
    except Exception as e:
        soft_errors.append(f"detailed-tasks.yaml extraction failed: {e}")

    try:
        proposal_path = spec_dir / "proposal.md"
        if proposal_path.is_file():
            proposal_text = proposal_path.read_text(encoding="utf-8", errors="replace")
            kd_lines = _extract_key_deliverables_section(proposal_text)
            kd_candidates = _extract_symbol_candidates_from_strings(kd_lines)
            if kd_candidates:
                sources["proposal_key_deliverables"] = [c["symbol"] for c in kd_candidates]
            candidates.extend(kd_candidates)
    except OSError as e:
        soft_errors.append(f"proposal.md read failed: {e}")
    except Exception as e:
        soft_errors.append(f"proposal Key Deliverables extraction failed: {e}")

    symbols: list[str] = []
    definition_paths_by_symbol: dict[str, set[str]] = {}
    seen: set[str] = set()
    for c in candidates:
        sym = c.get("symbol")
        if not sym:
            continue
        if sym not in seen:
            seen.add(sym)
            symbols.append(sym)
        if c.get("path"):
            definition_paths_by_symbol.setdefault(sym, set()).add(c["path"])

    return {
        "symbols": symbols,
        "extractable": bool(symbols),
        "sources": sources,
        "definition_paths_by_symbol": definition_paths_by_symbol,
        "soft_errors": soft_errors,
    }


# ---------------------------------------------------------------------------
# TASK-003/004/005: 生产语义引用核验 + fail-toward-warn
# ---------------------------------------------------------------------------

_TRIPLE_DQ_RE = re.compile(r'"""[\s\S]*?"""')
_TRIPLE_SQ_RE = re.compile(r"'''[\s\S]*?'''")
_LINE_COMMENT_RE = re.compile(r"#.*$", re.MULTILINE)
_DQ_STRING_RE = re.compile(r'"(?:[^"\\\n]|\\.)*"')
_SQ_STRING_RE = re.compile(r"'(?:[^'\\\n]|\\.)*'")


def _strip_comments_and_docstrings(text: str) -> str:
    """Best-effort removal of Python ``#`` line comments + triple-quoted
    docstring/string blocks (proposal §What Changes 1: "剥注释/docstring 后匹配").

    Heuristic, not a tokenizer — stdlib-only + fail-soft by construction (a
    regex substitution never raises). Used for the (i)/(iv) alive-pattern
    checks — deliberately KEEPS regular single/double-quoted string literals
    intact (see ``_strip_string_literals`` for the further-stripped variant
    used by the prose-vs-unclassified decision) so that legitimate code
    adjacent to a string (e.g. ``foo("x") if bar(...)``) is not mangled.
    """
    no_docstrings = _TRIPLE_DQ_RE.sub(" ", text)
    no_docstrings = _TRIPLE_SQ_RE.sub(" ", no_docstrings)
    return _LINE_COMMENT_RE.sub("", no_docstrings)


def _strip_string_literals(text: str) -> str:
    """Additionally strip ordinary single-line ``"..."``/``'...'`` string
    literals from (comment/docstring-already-stripped) `text`.

    proposal §What Changes 1 explicitly lists "描述性字符串字面量" (descriptive
    string literals) under "不算引用" (NOT a reference) — same bucket as
    comments/docstrings/prose. This is called ONLY to decide "is this
    occurrence exclusively prose-shaped" (``_classify_file_occurrence``'s
    fallback); it is NEVER used for the alive-pattern checks themselves,
    because ``_dynamic_dispatch_match`` (ii) *requires* seeing quoted strings
    (``getattr(mod, "symbol")`` etc.) — stripping them there would break that
    category entirely. Naive line-based regex (no multi-line string support,
    stdlib-only, fail-soft): a rare pathological string containing an
    unescaped quote could survive un-stripped, which only biases the result
    towards "unclassified" (warn) rather than "prose" (block-eligible) — i.e.
    the residual error direction still matches fail-toward-warn.
    """
    no_dq = _DQ_STRING_RE.sub(" ", text)
    return _SQ_STRING_RE.sub(" ", no_dq)


def _code_reference_match(stripped_text: str, symbol: str) -> bool:
    """(i) 代码引用: import 语句 / 调用 X( / 属性 X. / 装饰器 @X / 赋值别名。"""
    sym = re.escape(symbol)
    patterns = (
        rf"^\s*from\s+\S+\s+import\s+.*\b{sym}\b",
        rf"^\s*import\s+\S*\b{sym}\b",
        rf"^\s*from\s+\S*\b{sym}\b\S*\s+import\b",
        rf"\b{sym}\s*\(",
        rf"\b{sym}\.",
        rf"@\s*{sym}\b",
        rf"=\s*{sym}\b",
    )
    return any(re.search(p, stripped_text, re.MULTILINE) for p in patterns)


def _dynamic_dispatch_match(text: str, symbol: str) -> bool:
    """(ii) dynamic-dispatch: getattr/importlib/globals() 反射中的符号名字符串.

    Intentionally checked against the ORIGINAL (non-comment-stripped) text —
    this category's signal IS a string literal by definition, so it must not
    be excluded by string/docstring stripping.
    """
    sym = re.escape(symbol)
    patterns = (
        rf"getattr\s*\([^)]*[\'\"]{sym}[\'\"]",
        rf"globals\(\)\s*\[\s*[\'\"]{sym}[\'\"]",
        rf"importlib\.[a-zA-Z_]+\(\s*[\'\"][^\'\"]*{sym}[^\'\"]*[\'\"]",
    )
    return any(re.search(p, text) for p in patterns)


def _literal_script_path_match(text: str, symbol: str, definition_paths: set[str] | None) -> bool:
    """(iv) 通用调用面: 按字面整脚本路径调用 (shell/cron/Makefile/CI)."""
    if f"{symbol}.py" in text or f"{symbol}.sh" in text:
        return True
    for dp in definition_paths or ():
        if dp and dp in text:
            return True
    return False


_BASH_BLOCK_RE = re.compile(r"```(?:bash|sh)\s*\n([\s\S]*?)```")


def _skill_md_has_real_bash_invocation(
    text: str, symbol: str, definition_paths: set[str] | None
) -> bool:
    """(iii) aria-plugin 集成面 pt1: SKILL.md 内 **Bash 代码块** 真调用该符号/脚本
    (非散文提及 — 提及若不在 ```bash/```sh 代码围栏内, 按普通 .md 散文处理)。
    """
    for block in _BASH_BLOCK_RE.findall(text):
        if _literal_script_path_match(block, symbol, definition_paths):
            return True
        if re.search(r"\b" + re.escape(symbol) + r"\b", block):
            return True
    return False


def _config_has_registration(text: str, symbol: str, definition_paths: set[str] | None) -> bool:
    """(iii) aria-plugin 集成面 pt2: hooks.json / config 内注册该 hook/命令。"""
    return _literal_script_path_match(text, symbol, definition_paths) or (symbol in text)


def _is_ci_workflow_path(rel_path: str) -> bool:
    """CI workflow yaml + broader platform config under ``.github/``/``.forgejo/``
    (branch protection, secret scanning, dependabot, issue templates, etc.) —
    these represent REAL external-platform wiring, not declarative planning
    metadata like ``detailed-tasks.yaml``. Widened beyond just ``workflows/``
    (dogfood found a real miss: ``aria/.github/secret_scanning.yml`` literally
    lists a script path but isn't under ``workflows/``).
    """
    norm = "/" + rel_path.replace("\\", "/")
    return "/.forgejo/" in norm or "/.github/" in norm


def _is_hooks_or_config_path(rel_path: str) -> bool:
    """(iii) hooks.json / ``.aria/config.json`` — the two known aria-plugin
    registration files. Deliberately NARROW (not "any .json file") — a blanket
    ``ext == ".json"`` match was empirically found to false-positive on
    generated/cache JSON (e.g. a cached issue-title snapshot merely quoting a
    symbol name in prose is not a "registration").
    """
    name = Path(rel_path).name
    norm = "/" + rel_path.replace("\\", "/")
    if name == "hooks.json":
        return True
    return name == "config.json" and "/.aria/" in norm


def _is_test_path(rel_path: str) -> bool:
    """测试文件 (test_*/`*_test.py`/tests//conftest.py) — 排除, 不计入 either 桶。"""
    norm = rel_path.replace("\\", "/")
    parts = norm.split("/")
    if any(p in ("tests", "test") for p in parts[:-1]):
        return True
    name = parts[-1] if parts else norm
    return name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"


def _is_dogfood_ops_path(rel_path: str) -> bool:
    """dogfood·ops 核验脚本目录 (属核验非生产) — 排除。"""
    norm = "/" + rel_path.replace("\\", "/")
    return "/.aria/scripts/dogfood/" in norm


def _is_definition_file(rel_path: str, definition_paths: set[str]) -> bool:
    """符号自身定义文件 — 排除 (自引用不算引用)。"""
    norm = rel_path.replace("\\", "/").lstrip("./")
    for dp in definition_paths or ():
        if not dp:
            continue
        dpn = dp.replace("\\", "/").lstrip("./")
        if norm == dpn or norm.endswith("/" + dpn) or dpn.endswith("/" + norm):
            return True
    return False


def _find_project_root(spec_dir: Path) -> Path | None:
    """Locate the project root above ``<root>/openspec/{changes,archive}/<id>/``.

    Fail-soft, best-effort: prefers the ancestor whose child is the closest
    ``openspec`` segment; falls back to walking up looking for ``.git``; returns
    ``None`` if neither is found (caller then degrades to ``spec_dir.parent``).
    """
    try:
        resolved = Path(spec_dir).resolve()
    except OSError:
        return None
    parts = resolved.parts
    try:
        rev_idx = parts[::-1].index("openspec")
        idx = len(parts) - 1 - rev_idx
        if idx > 0:
            return Path(*parts[:idx])
    except ValueError:
        pass
    cur = resolved
    for _ in range(8):
        try:
            if (cur / ".git").exists():
                return cur
        except OSError:
            break
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


_GREP_LINE_RE = re.compile(r"^(.*?):(\d+):(.*)$")


def _parse_grep_output(stdout: str, project_root: Path) -> list[tuple[str, int, str]]:
    results: list[tuple[str, int, str]] = []
    for raw_line in stdout.splitlines():
        m = _GREP_LINE_RE.match(raw_line)
        if not m:
            continue
        abs_path_str, lineno_str, content = m.group(1), m.group(2), m.group(3)
        try:
            rel = str(Path(abs_path_str).relative_to(project_root))
        except ValueError:
            rel = abs_path_str
        try:
            lineno = int(lineno_str)
        except ValueError:
            continue
        results.append((rel.replace("\\", "/"), lineno, content))
    return results


def _walk_symbol_occurrences_pure_python(
    symbol: str, project_root: Path
) -> list[tuple[str, int, str]]:
    """TASK-008 fallback when ``grep`` is unavailable — pure os.walk + substring scan."""
    results: list[tuple[str, int, str]] = []
    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for fname in filenames:
            fpath = Path(dirpath) / fname
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if symbol not in text:
                continue
            rel = str(fpath.relative_to(project_root)).replace("\\", "/")
            for i, line in enumerate(text.splitlines(), start=1):
                if symbol in line:
                    results.append((rel, i, line))
    return results


def _grep_symbol_occurrences(
    symbol: str, project_root: Path
) -> tuple[list[tuple[str, int, str]], bool]:
    """Return ``(occurrences, authoritative)`` — occurrences =
    ``[(relative_path, line_no, line_text), ...]`` for every literal occurrence
    of `symbol` under `project_root`. Never raises (TASK-008).

    ``authoritative`` is **False** when the search degraded (a tier errored /
    timed out, plain-grep exited ≥2 returning only partial output, or it fell
    through to the pure-Python walk which silently skips unreadable files).
    Callers MUST NOT emit a ``dead`` verdict on a non-authoritative search —
    "zero occurrences" then cannot be distinguished from "search missed the
    reference", and a false ``dead`` would hard-block a legitimate archive
    (SC 既有正常归档零影响; silent-failure-hunter C1 fix 2026-07-05).

    Search-scope fail-soft ladder:
      1. ``git grep --recurse-submodules`` (fast path) — deliberately preferred
         over a raw filesystem walk: it (a) naturally scopes the search to
         *tracked* files only, excluding gitignored scratch/cache/workspace
         dirs (empirically found to cause false "alive" classifications —
         e.g. a cached ``.aria/state-snapshot.json`` or a
         ``.aria/skill-restructure-workspace/`` backup copy can contain a
         verbatim copy of a symbol name with no bearing on whether it is
         actually wired into production), and (b) crosses submodule
         boundaries (aria-plugin's ``aria/`` is a git submodule of the outer
         project — without ``--recurse-submodules`` its content would be
         invisible to a plain top-level grep).
      2. Plain ``grep -r`` (project isn't a git repo, or `git` errored).
      3. Pure-Python ``os.walk`` (neither `git` nor `grep` available).
    """
    if not symbol:
        return [], True
    try:
        proc = subprocess.run(
            ["git", "-C", str(project_root), "grep", "-n", "-I", "-F", "--recurse-submodules", "--", symbol],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode in (0, 1):  # 0=found, 1=no matches — both authoritative
            return _parse_grep_output(proc.stdout, project_root), True
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        pass
    try:
        proc = subprocess.run(
            ["grep", "-rn", "-I", "--exclude-dir=.git", "-F", "--", symbol, str(project_root)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # grep exit: 0=found / 1=no match (both authoritative); ≥2=error → partial/degraded
        return _parse_grep_output(proc.stdout, project_root), proc.returncode in (0, 1)
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        pass
    # tier 3: pure-Python walk silently skips unreadable files → non-authoritative
    return _walk_symbol_occurrences_pure_python(symbol, project_root), False


def _classify_file_occurrence(
    rel_path: str, project_root: Path, symbol: str, definition_paths: set[str]
) -> dict:
    """Classify ONE file's occurrence of `symbol` into alive / prose / unclassified.

    Returns ``{"alive": bool, "categories": [str,...], "prose": bool}``. Raises
    only on unreadable file (caller treats that as fail-soft "unclassified").
    """
    abs_path = project_root / rel_path
    name = Path(rel_path).name
    ext = Path(rel_path).suffix.lower()
    text = abs_path.read_text(encoding="utf-8", errors="replace")

    if name == "SKILL.md":
        if _skill_md_has_real_bash_invocation(text, symbol, definition_paths):
            return {"alive": True, "categories": ["aria_plugin_integration"], "prose": False}
        return {"alive": False, "categories": [], "prose": True}  # 散文提及, 不算引用

    if ext in (".md", ".markdown", ".rst"):
        return {"alive": False, "categories": [], "prose": True}  # docs/CHANGELOG/audit-reports 等散文

    if ext == "" and name in ("VERSION", "CHANGELOG", "README", "LICENSE", "NOTICE", "AUTHORS"):
        # 无扩展名的人类可读元文档惯例名 (如本仓 aria/VERSION — "人类可读版本快照",
        # 逐条 changelog 式散文段落) — 与 *.md 散文同归宿, 不算引用。
        return {"alive": False, "categories": [], "prose": True}

    if _is_hooks_or_config_path(rel_path):
        if _config_has_registration(text, symbol, definition_paths):
            return {"alive": True, "categories": ["aria_plugin_integration"], "prose": False}
        return {"alive": False, "categories": [], "prose": False}

    if ext in (".yaml", ".yml"):
        stripped_yaml = _strip_comments_and_docstrings(text)
        if _is_ci_workflow_path(rel_path):
            if _literal_script_path_match(stripped_yaml, symbol, definition_paths):
                return {"alive": True, "categories": ["generic_path_call"], "prose": False}
            return {"alive": False, "categories": [], "prose": False}
        # 非 CI yaml (如 detailed-tasks.yaml 自身/其它声明性元数据) = 声明意图非
        # 运行时调用面 — 与 deliverables 提取源同理, 不能自证已引用。
        return {"alive": False, "categories": [], "prose": True}

    # 通用 "代码性" 文件 (.py/.js/.ts/.sh/Makefile/其它 .json fixture 等):
    # (iv) 的字面路径匹配也必须在剥注释/docstring 后的文本上做 —— 否则任何文件
    # (含本模块自身的说明性 docstring!) 只要在注释里提过 "symbol.py" 这个字符串
    # 就会被误判为"已引用" (dogfood 实测踩坑: collectors/openspec.py 一行
    # "Dual-context import (same pattern as phase1_gate.py)" 注释曾误报 alive)。
    stripped = _strip_comments_and_docstrings(text)
    categories: list[str] = []
    if _code_reference_match(stripped, symbol):
        categories.append("code_reference")
    if _dynamic_dispatch_match(text, symbol):
        categories.append("dynamic_dispatch")
    if _literal_script_path_match(stripped, symbol, definition_paths):
        categories.append("generic_path_call")
    if categories:
        return {"alive": True, "categories": categories, "prose": False}
    if symbol not in _strip_string_literals(stripped):
        # 该文件里符号的唯一出现形态是注释/docstring/描述性字符串字面量 — 全部
        # 剥除后不再出现于代码体, 与 *.md 散文同归宿 ("不算引用", proposal
        # §What Changes 1), 不计入 unclassified/ambiguous (否则任何提及本符号的
        # 说明性注释或日志字符串, 包括本模块自身描述 golden 反例的 docstring,
        # 都会把死代码误判为 warn 而非 block —
        # dogfood 实测踩坑, 见 coordination_ref.py/collectors/openspec.py 教训)。
        return {"alive": False, "categories": [], "prose": True}
    return {"alive": False, "categories": [], "prose": False}  # 未分类形态 (TASK-005): 剥注释后仍在代码体出现, 但不落入已知 alive 形态


def _symbol_has_python_definition(
    symbol: str,
    project_root: Path,
    definition_paths: set[str] | None,
    occurrences: list[tuple[str, int, str]],
) -> bool:
    """符号是否为确凿的 Python 代码 (有磁盘定义) — 判 "死代码" 的前提 (C-block 门槛)。

    True 若: (a) 某 definition_path 是磁盘存在的 .py 文件; 或 (b) 生产代码中出现
    ``def SYMBOL`` / ``class SYMBOL``; 或 (c) 生产代码中存在名为 ``SYMBOL.py`` 的模块文件。

    无 Python 定义 → 符号**不是代码** (markdown/prompt-only skill 的 documented convention
    概念, 如 audit-engine 的 ``drift_warning``, 无任何 .py) → 不可能是 "dead-code-on-arrival",
    由调用方降级 fail-toward-warn (warn 非 block), 兑现 SC "既有正常归档零影响"。
    """
    for dp in definition_paths or ():
        p = Path(dp)
        if not p.is_absolute():
            p = project_root / dp
        if p.suffix == ".py" and p.is_file():
            return True
    module_basename = f"{symbol}.py"
    def_re = re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+" + re.escape(symbol) + r"\b")
    for rel_path, _lineno, content in occurrences:
        if _is_test_path(rel_path) or _is_dogfood_ops_path(rel_path):
            continue
        if Path(rel_path).name == module_basename:
            return True
        if rel_path.endswith(".py") and def_re.search(content):
            return True
    return False


def classify_symbol_liveness(
    symbol: str, project_root: Path, definition_paths: set[str] | None = None
) -> dict:
    """TASK-003/004/005: tri-state liveness verdict for one candidate symbol.

    Returns ``{"status": "alive"|"dead"|"ambiguous", "alive_categories": [...],
    "prose_files": [...], "unclassified_files": [...], "soft_error": str|None}``.

    - **alive**: 任一生产出现落入 (i)-(iv) 任一 alive 类别 → 不 block。
    - **dead**: 所有生产出现 (若有) 全属"不算引用"(散文/注释/docstring/测试/
      dogfood/自身定义文件) 或零出现 → 高置信死代码, block 候选。
    - **ambiguous**: 存在至少一处生产出现, 落在两清单之外 (未分类 wiring 形态)
      → fail-toward-warn (TASK-005 正控5), 降级 warn 非 block。

    fail-soft (TASK-008): grep/读取异常 → ``status="ambiguous"`` + soft_error
    (即放行, 不 block —— 与"未分类形态"同归宿, 全新增判定异常均不得导致 block)。
    """
    definition_paths = definition_paths or set()
    try:
        occurrences, search_authoritative = _grep_symbol_occurrences(symbol, project_root)
    except Exception as e:  # pragma: no cover - _grep_symbol_occurrences 已内部 fail-soft
        return {
            "status": "ambiguous",
            "alive_categories": [],
            "prose_files": [],
            "unclassified_files": [],
            "soft_error": f"occurrence search failed: {e}",
        }

    by_file: dict[str, list[tuple[int, str]]] = {}
    for rel_path, lineno, content in occurrences:
        by_file.setdefault(rel_path, []).append((lineno, content))

    alive_categories: set[str] = set()
    unclassified_files: list[str] = []
    prose_files: list[str] = []

    for rel_path in by_file:
        if _is_test_path(rel_path) or _is_dogfood_ops_path(rel_path):
            continue
        if _is_definition_file(rel_path, definition_paths):
            continue
        try:
            classification = _classify_file_occurrence(
                rel_path, project_root, symbol, definition_paths
            )
        except OSError as e:
            unclassified_files.append(f"{rel_path} (unreadable: {e})")
            continue
        if classification["alive"]:
            alive_categories.update(classification["categories"])
        elif classification["prose"]:
            prose_files.append(rel_path)
        else:
            unclassified_files.append(rel_path)

    soft_error = None
    if alive_categories:
        status = "alive"
    elif unclassified_files:
        status = "ambiguous"
    elif not _symbol_has_python_definition(symbol, project_root, definition_paths, occurrences):
        # 亲验 fix (2026-07-05): 符号无 Python 定义 → 非代码 (markdown/prompt-only skill
        # 概念, 如 audit-engine drift_warning) → 不可判 "死代码" → fail-toward-warn (warn
        # 非 block), 不误伤合法归档 (SC 既有正常归档零影响)。仅 "有定义 ∧ 零生产引用" 才是
        # 高置信 dead-code-on-arrival (Layer L phase1_gate)。
        status = "ambiguous"
        unclassified_files.append(
            f"(no Python definition for '{symbol}' — not code, cannot be dead-code → warn)"
        )
    elif not search_authoritative:
        # C1 fix (silent-failure-hunter 2026-07-05): 引用搜索降级 (grep 退出≥2 / 超时 /
        # pure-Python fallback 静默跳过不可读文件) → "零出现"不可信 (可能漏看真引用) → 不判
        # 死代码 → fail-toward-warn + soft_error (loud), 不因搜索失败误 block 合法归档。
        status = "ambiguous"
        soft_error = (
            f"reference search for '{symbol}' was non-authoritative (grep degraded / "
            "pure-Python fallback / timeout) — 'dead-code' NOT asserted, fail-toward-warn"
        )
        unclassified_files.append(f"(search degraded for '{symbol}' → warn)")
    else:
        status = "dead"

    return {
        "status": status,
        "alive_categories": sorted(alive_categories),
        "prose_files": prose_files,
        "unclassified_files": unclassified_files,
        "soft_error": soft_error,
    }


# ---------------------------------------------------------------------------
# TASK-006: 产物抽验 (dogfood/benchmark/deploy 声称)
# ---------------------------------------------------------------------------

_DOGFOOD_BENCHMARK_DEPLOY_KEYWORDS = (
    "dogfood",
    "benchmark",
    "ab-test",
    "ab_test",
    "ab 测试",
    "部署",
    "deploy",
    "上线",
)
_TELEMETRY_KEYWORDS = ("遥测", "telemetry", "runtime-invoke", "运行时探针", "运行时调用探测")
_ARTIFACT_PATH_TOKEN_RE = re.compile(r"[\w./\-]*(?:ab-results|ab-suite)[\w./\-]*")


def _matches_any(text: str, keywords: tuple[str, ...]) -> bool:
    low = text.lower()
    return any(kw.lower() in low for kw in keywords)


def classify_artifact_claim(claim_line: str, spec_dir: Path, project_root: Path | None) -> dict:
    """TASK-006: dogfood/benchmark/deploy 完成声称的产物抽验 — fail-soft, 从不抛出。

    - 遥测类声称 (fix A out-of-scope, proposal §What Changes 1 末段): 恒
      ``verified=False`` 走"无法核验 → warn"通道, **不列产物类别** (过渡期无
      遥测基建 → 恒 warn 噪音, 与 block 无关)。
    - dogfood/benchmark/deploy 类: 声称行内若能提取一个存在于磁盘的可链接产物
      路径 (如 ``ab-results/...``) → verified=True; 否则 verified=False (warn)。
    - 其它 (非上述两类) 完成声称: 与本 TASK-006 无关, ``category="not_artifact_claim"``,
      不产生 warn (由 TASK-009/010 的符号引用核验通道处理)。
    """
    try:
        if _matches_any(claim_line, _TELEMETRY_KEYWORDS):
            return {
                "category": "telemetry",
                "verified": False,
                "reason": "遥测/运行时-invoke 核验属 fix A (out-of-scope); 静态 C 无法核验 → warn",
            }
        if not _matches_any(claim_line, _DOGFOOD_BENCHMARK_DEPLOY_KEYWORDS):
            return {"category": "not_artifact_claim", "verified": True, "reason": ""}

        root = project_root or _find_project_root(spec_dir) or spec_dir
        for tok in _ARTIFACT_PATH_TOKEN_RE.findall(claim_line):
            tok = tok.strip(" .,;")
            if not tok:
                continue
            candidate = Path(tok)
            candidate = candidate if candidate.is_absolute() else (root / candidate)
            if candidate.exists():
                return {
                    "category": "artifact_claim",
                    "verified": True,
                    "reason": f"linked artifact exists: {tok}",
                }
        return {
            "category": "artifact_claim",
            "verified": False,
            "reason": "dogfood/benchmark/deploy claim 无可链接产物路径或路径不存在",
        }
    except Exception as e:  # TASK-008: 全 fail-soft, 从不因异常 block
        return {"category": "artifact_claim", "verified": False, "reason": f"soft_error: {e}"}


def _check_artifact_claims(tasks_text: str, spec_dir: Path, project_root: Path) -> list[dict]:
    """Run ``classify_artifact_claim`` over every checked `[x]` tasks.md item."""
    findings = []
    for item in _iter_task_items(tasks_text):
        if not item["checked"]:
            continue
        finding = classify_artifact_claim(item["line"], spec_dir, project_root)
        if finding["category"] != "not_artifact_claim":
            finding = dict(finding)
            finding["claim"] = item["line"]
            findings.append(finding)
    return findings


# ---------------------------------------------------------------------------
# TASK-011: D payload (deferred/unverified 聚合 + issue body + 去重 marker)
# ---------------------------------------------------------------------------


def _extract_deferred_or_unchecked_items(tasks_text: str) -> list[dict]:
    """聚合 tasks.md 未勾选 `[ ]` 项 + inline carry-forward/defer 注释 (复用 #134
    ``carry_forward`` 正则 SOT, 不双写)。供 D payload"未完成项"清单使用。
    """
    out: list[dict] = []
    for item in _iter_task_items(tasks_text):
        if not item["checked"]:
            out.append({"parent_id": item["parent_id"], "line": item["line"], "reason": "unchecked"})
    for annotation in _extract_carry_forward_annotations(tasks_text):
        out.append({"parent_id": None, "line": annotation, "reason": "carry-forward annotation"})
    return out


def _build_d_payload(
    spec_dir: str | Path, deferred_items: list[dict], unverified_claims: list[dict]
) -> dict | None:
    """TASK-011: assemble the D auto-issue payload (lib side only — the actual
    Forgejo API call is TG-2's ``openspec-archive`` Step2 SKILL.md Bash responsibility).

    Returns ``None`` when there is nothing to track (no deferred items AND no
    unverified claims) — D must not fire on a clean archive. Body embeds the
    dedup marker ``<!-- archive-tracker:{spec_id} -->`` (proposal §What Changes 2)
    so Step2 can search-before-create idempotently; the archive-commit SHA
    backlink is intentionally left as a placeholder — only the Bash layer knows
    the post-archive commit SHA.
    """
    if not deferred_items and not unverified_claims:
        return None
    spec_id = Path(spec_dir).name
    marker = f"<!-- archive-tracker:{spec_id} -->"
    lines = [marker, "", f"# Archive tracker: {spec_id}", ""]
    if deferred_items:
        lines.append("## 未完成/deferred 项")
        for d in deferred_items:
            lines.append(f"- {d['line']} ({d['reason']})")
        lines.append("")
    if unverified_claims:
        lines.append("## Unverified claims (无论是否 ack — 见 proposal §What Changes 2 ack 解耦)")
        for c in unverified_claims:
            lines.append(f"- {c['claim']} — {c['reason']}")
        lines.append("")
    lines.append("> 归档 SHA 回链: 由 openspec-archive Step2 归档提交后填入")
    return {
        "spec_id": spec_id,
        "marker": marker,
        "deferred_items": deferred_items,
        "unverified_claims": unverified_claims,
        "body": "\n".join(lines),
    }


# ---------------------------------------------------------------------------
# TASK-007: tri-state gate_result — 契约入口
# ---------------------------------------------------------------------------


def gate_result(spec_dir: str | Path) -> dict:
    """TASK-007: tri-state 完成声称真实性判定 — 与 #134 ``complete`` 字段正交。

    See module docstring for the full pipeline description + returned schema.
    ``verdict`` 单调升级 (pass < warn < block); 全 fail-soft (TASK-008): 任何
    子判定异常记入 ``soft_errors``, 从不因此升级 verdict / 抛出异常。
    """
    spec_dir = Path(spec_dir)
    result: dict = {
        "complete": False,
        "complete_reason": "",
        "verdict": "pass",
        "blocking_reasons": [],
        "warnings": [],
        "unverified_claims": [],
        "d_payload": None,
        "soft_errors": [],
    }

    try:
        complete_verdict = is_spec_complete(spec_dir)
        result["complete"] = complete_verdict["complete"]
        result["complete_reason"] = complete_verdict["reason"]
    except Exception as e:  # pragma: no cover - is_spec_complete 已 fail-soft
        result["soft_errors"].append(f"is_spec_complete failed: {e}")

    tasks_path = spec_dir / "tasks.md"
    if not tasks_path.is_file():
        return result  # 无 tasks.md → 无完成声称可核验, fail-soft 放行 (pass)

    try:
        tasks_text = tasks_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        result["soft_errors"].append(f"tasks.md read failed: {e}")
        return result

    try:
        all_items = _iter_task_items(tasks_text)
    except Exception as e:  # pragma: no cover - regex-only, defensive
        result["soft_errors"].append(f"tasks.md checkbox parse failed: {e}")
        all_items = []

    integration_claims = [
        it for it in all_items if it["checked"] and _line_has_integration_keyword(it["line"])
    ]

    project_root = _find_project_root(spec_dir) or spec_dir.parent

    # ── C-block/C-warn (TASK-009/010): 代码集成类完成声称 ──
    for claim in integration_claims:
        try:
            extraction = extract_claim_symbols(spec_dir, claim)
        except Exception as e:
            result["soft_errors"].append(
                f"symbol extraction failed for claim {claim['line'][:60]!r}: {e}"
            )
            continue

        if not extraction["extractable"]:
            result["unverified_claims"].append(
                {"claim": claim["line"], "reason": "no extractable symbol (fail-soft)", "symbols": []}
            )
            if result["verdict"] == "pass":
                result["verdict"] = "warn"
            continue

        def_by_symbol = extraction.get("definition_paths_by_symbol", {})
        for symbol in extraction["symbols"]:
            try:
                liveness = classify_symbol_liveness(
                    symbol, project_root, def_by_symbol.get(symbol, set())
                )
            except Exception as e:  # pragma: no cover - classify_symbol_liveness 已 fail-soft
                result["soft_errors"].append(f"liveness check failed for {symbol!r}: {e}")
                # m2 (silent-failure-hunter): 分析失败的 claim 也 surface 到 unverified_claims
                # (→ warn + 进 D tracker), 不静默丢进 soft_errors (gate 职责是 surface 声称)
                result["unverified_claims"].append(
                    {
                        "claim": claim["line"],
                        "reason": f"liveness analysis failed for {symbol!r} (fail-soft)",
                        "symbols": [symbol],
                    }
                )
                if result["verdict"] != "block":
                    result["verdict"] = "warn"
                continue

            if liveness["status"] == "dead":
                result["blocking_reasons"].append(
                    f"symbol {symbol!r} (claim: {claim['line'][:80]!r}) has zero "
                    "production semantic reference (dead-code-on-arrival)"
                )
                result["verdict"] = "block"
            elif liveness["status"] == "ambiguous":
                result["warnings"].append(
                    f"symbol {symbol!r} reference form unclassified — fail-toward-warn "
                    f"(unclassified_files={liveness.get('unclassified_files')}, "
                    f"soft_error={liveness.get('soft_error')})"
                )
                # 把降级/未分类的 soft_error 也提到 result 顶层 soft_errors (可见性, C1)
                if liveness.get("soft_error"):
                    result["soft_errors"].append(liveness["soft_error"])
                result["unverified_claims"].append(
                    {
                        "claim": claim["line"],
                        "reason": f"symbol {symbol!r} unclassified reference form",
                        "symbols": [symbol],
                    }
                )
                if result["verdict"] != "block":
                    result["verdict"] = "warn"
            # alive → 无 action, 不 block 不 warn

    # ── C-warn (TASK-006/010): dogfood/benchmark/deploy 产物抽验 + 遥测 ──
    try:
        artifact_findings = _check_artifact_claims(tasks_text, spec_dir, project_root)
    except Exception as e:
        result["soft_errors"].append(f"artifact claim check failed: {e}")
        artifact_findings = []

    for finding in artifact_findings:
        if not finding["verified"]:
            result["unverified_claims"].append(
                {"claim": finding["claim"], "reason": finding["reason"], "symbols": []}
            )
            if result["verdict"] != "block":
                result["verdict"] = "warn"

    # ── D payload (TASK-011): deferred 未勾项 + 全部 unverified_claims (无论 ack) ──
    try:
        deferred_items = _extract_deferred_or_unchecked_items(tasks_text)
    except Exception as e:
        result["soft_errors"].append(f"deferred item extraction failed: {e}")
        deferred_items = []

    try:
        result["d_payload"] = _build_d_payload(spec_dir, deferred_items, result["unverified_claims"])
    except Exception as e:
        result["soft_errors"].append(f"D payload build failed: {e}")
        result["d_payload"] = None

    return result


def _main(argv: list[str]) -> int:
    """Thin CLI: stdout JSON verdict; exit 0=complete / 1=incomplete / 2=error.

    TASK-007 新增 ``--gate`` 模式 (沿用 exit code 契约, 0=allow[pass|warn] /
    1=block): ``python3 spec_complete.py --gate <spec_dir>`` → stdout 输出
    ``gate_result()`` 的 tri-state JSON。既有 ``python3 spec_complete.py <spec_dir>``
    行为完全不变 (legacy #134 二元 complete/incomplete)。
    """
    if len(argv) >= 2 and argv[1] == "--gate":
        # I2 fix: join argv[2:] 容忍未加引号的空格路径 (不因此误 usage 错)。
        spec_dir_arg = " ".join(argv[2:]) if len(argv) >= 3 else ""
        if not spec_dir_arg:
            # 真 usage 错 (无 path) — I2 fix: fail-toward-warn (不 block), allow + loud soft_error。
            print(
                json.dumps(
                    {
                        "complete": False,
                        "complete_reason": "",
                        "verdict": "warn",
                        "blocking_reasons": [],
                        "warnings": ["usage: spec_complete.py --gate <spec_dir> — missing spec_dir"],
                        "unverified_claims": [],
                        "d_payload": None,
                        "soft_errors": ["missing spec_dir arg → fail-toward-warn (not blocking)"],
                    }
                )
            )
            print("spec_complete.py --gate: missing spec_dir", file=sys.stderr)
            return 0
        try:
            result = gate_result(spec_dir_arg)
        except Exception as e:  # I1 fix: gate 意外 crash → fail-toward-warn (不 block 合法归档),
            # 但保持响亮 (soft_errors + stderr)。与 proposal「fail-soft→放行」契约对齐; 只有内部
            # 每步 fail-soft 都失守才可达此路径, 宁放行也不误 block (SC 既有正常归档零影响)。
            print(
                json.dumps(
                    {
                        "complete": False,
                        "complete_reason": "",
                        "verdict": "warn",
                        "blocking_reasons": [],
                        "warnings": [f"gate crashed — fail-toward-warn (not blocking): {e}"],
                        "unverified_claims": [],
                        "d_payload": None,
                        "soft_errors": [f"unexpected gate error: {e}"],
                    }
                )
            )
            print(f"spec_complete.py --gate crashed (fail-toward-warn): {e}", file=sys.stderr)
            return 0
        print(json.dumps(result))
        return 0 if result["verdict"] in ("pass", "warn") else 1

    if len(argv) != 2:
        print(json.dumps({"complete": False, "reason": "usage: spec_complete.py <spec_dir>"}))
        return 2
    try:
        verdict = is_spec_complete(argv[1])
    except Exception as e:  # 非预期异常兜底 — CLI 永远输出可解析 JSON
        print(json.dumps({"complete": False, "reason": f"unexpected error: {e}"}))
        return 2
    print(json.dumps(verdict))
    return 0 if verdict["complete"] else 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv))

#!/usr/bin/env python3
"""Single executable SOT for OpenSpec spec completeness verdict (契约 A, #134).

Spec: openspec/changes/aria-archive-completeness-gate/ (DEC-20260609-001)

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

Thin CLI (供 SKILL.md 的 AI agent 经 Bash 调用 — 无法 import Python):

    python3 spec_complete.py <spec_dir>

stdout 输出 verdict JSON (ensure_ascii 默认 True, 防 Windows GBK stdout 异常);
exit code: 0 = complete / 1 = incomplete / 2 = usage 或非预期错误。

多入口一致 verdict 不变量 (AC-1) — 同一 spec_dir 必须得到相同 JSON:
- collectors/openspec.py (Python import, A2.3)
- openspec-archive SKILL.md Step1 完成 gate (Bash, TG-B B1.2)
- phase-d-closer D.2 skip_evaluation (Bash, TG-B B4.1)
"""

from __future__ import annotations

import json
import re
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


def _main(argv: list[str]) -> int:
    """Thin CLI: stdout JSON verdict; exit 0=complete / 1=incomplete / 2=error."""
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

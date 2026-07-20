#!/usr/bin/env python3
"""Single SOT for detailed-tasks.yaml parsing (task-planner path B datasource).

aria-plugin #113 (state-scanner-gate-yaml-datasource). Two layers:

1. **Slicer** (relocated from ``spec_complete.py``, #134 A1.1b pattern — the same
   physical-move-and-re-import convention ``carry_forward.py`` uses so both
   ``spec_complete.py`` (gate) and this module share ONE ``- id:`` boundary
   parser, no double-write): ``_TASK_ID_LINE_RE`` + ``_split_task_blocks``.
2. **Status-extraction layer** (new): ``parse_detailed_tasks(text)`` returns
   per-task ``{id, raw_status, title}`` for the yaml-only archive gate.

stdlib-only, fail-soft (never raises); NOT a general YAML parser — strictly
scoped to the detailed-tasks.yaml shape (a top-level ``tasks:`` block of
``- id: TASK-XXX`` entries). Mirrors the scoped-parser convention already used
by ``collectors/custom_checks.py`` ("Minimal YAML parser").

Design decisions (proposal §What Changes 1 + 决策 8/10/12/16/17/18; post_spec
R1→R5 CONVERGED):
- **range-bounded** counting: only the span from ``tasks:`` to the next 0-indent
  top-level key (or EOF) is considered — excludes ``execution_order:`` / sibling
  keys whose block-style list items sit at the same indent as ``- id:``
  (R4: 11/17 corpus false-mismatch incl. 3/3 golden without this bound).
- **indent-anchored** counting: base indent = the first ``- id:`` match's captured
  ``([ \\t]*)``; only same-indent direct ``- `` items count (R3: nested
  deliverables/verification sub-lists must not inflate, 17/17 corpus).
- **fail-CLOSED** whitelist: done-family = {done, completed}; everything else
  (pending/deferred/blocked/in_progress/unknown/None) counts as residual.
- **normalization chain** (order matches custom_checks precedent): strip \\r →
  quote-aware strip inline comment → strip whitespace → strip surrounding quotes.
  Empty/quote-only value normalizes to None (status-missing).
"""
from __future__ import annotations

import re

def _strip_inline_comment(value: str) -> str:
    """Strip a ` # comment` tail from an inline YAML scalar. Preserves `#` inside quotes.

    **Physically hosted here** (aria-plugin #113 implementation note, amending
    proposal 决策 16's stated import direction): the quote-aware SOT used to live
    in ``collectors/custom_checks.py``, and the proposal planned for this module
    to import it from there. That direction is impossible — importing
    ``collectors.custom_checks`` executes ``collectors/__init__.py``, which
    imports ``collectors.openspec`` → ``spec_complete`` → back into this module
    while it is still initializing (circular import; the package ``__init__`` is
    the cycle vector, not custom_checks itself).

    Resolution follows the codebase's established answer to exactly this problem
    (``lib/carry_forward.py``, #134 A1.1b): move the shared helper physically INTO
    ``lib/`` and have the original home re-import it, so the definition stays
    single-sourced with the dependency edge pointing collectors → lib.
    ``collectors/custom_checks.py`` now re-imports this function.

    (Deliberately NOT ``frontmatter_block.py:_strip_inline_comment`` — that
    same-named sibling is a naive ``find(" #")`` with no quote awareness; picking
    it would truncate quoted values containing ``#``, breaking SC-1/SC-14.)
    """
    in_single = False
    in_double = False
    for i, ch in enumerate(value):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            # Require a space before `#` to avoid chopping `#abc` inside unquoted strings
            if i == 0 or value[i - 1].isspace():
                return value[:i].rstrip()
    return value


# detailed-tasks.yaml 任务条目边界: `  - id: TASK-XXX` (physically hosted here;
# spec_complete.py re-imports this exact object — decision 8, SC-9 boundary
# consistency test).
_TASK_ID_LINE_RE = re.compile(r"^([ \t]*)-\s*id:\s*(\S+)", re.MULTILINE)

# 0-indent top-level key line (generalizes frontmatter_block.py:81's single-key
# `^runtime_probe:` precedent). Used to bound the `tasks:` block.
_TOP_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):")

# done-family whitelist (fail-CLOSED; lowercase exact-match after normalization).
_DONE_FAMILY = frozenset({"done", "completed"})


def _split_task_blocks(detailed_tasks_text: str) -> list[tuple[str, str]]:
    """Slice detailed-tasks.yaml into ``[(task_id, block_text), ...]`` by ``- id:`` boundaries.

    Light line-based scanner (stdlib-only, NOT a general YAML parser — mirrors
    the scoped-parser convention already used by collectors/custom_checks.py).
    The last block extends to the end of the *given text*; callers that must
    exclude trailing sibling keys pass an already-bounded text (see
    ``parse_detailed_tasks``).
    """
    matches = list(_TASK_ID_LINE_RE.finditer(detailed_tasks_text))
    blocks = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(detailed_tasks_text)
        blocks.append((m.group(2), detailed_tasks_text[start:end]))
    return blocks


def is_done_status(raw_status: str | None) -> bool:
    """True iff ``raw_status`` is in the fail-CLOSED done-family whitelist.

    None (missing/empty) and every non-whitelisted value → False (residual).
    """
    if raw_status is None:
        return False
    return raw_status.lower() in _DONE_FAMILY


def _normalize_status_value(raw: str) -> str | None:
    """Normalize a raw ``status:`` value tail. Returns None for empty/quote-only.

    Order (decision 16, aligned with custom_checks real execution order —
    _strip_inline_comment then .strip() then quote judgement):
      strip \\r → quote-aware strip comment → strip whitespace → strip quotes.
    """
    # NOTE (pre-merge code-review M-4, honesty): for whole-file CRLF the real
    # guarantor is `str.splitlines()` in parse_detailed_tasks — it consumes the
    # \r\n pair before values ever reach here (SC-11 passes with this .replace
    # removed). The strip is retained as defense-in-depth for an EMBEDDED lone
    # \r inside a value, which splitlines() does not remove from mid-line text.
    v = raw.replace("\r", "")
    v = _strip_inline_comment(v)
    v = v.strip()
    if len(v) >= 2 and (
        (v[0] == '"' and v[-1] == '"') or (v[0] == "'" and v[-1] == "'")
    ):
        v = v[1:-1]
    v = v.strip()
    return v or None


def _normalize_title_value(raw: str) -> str:
    """Normalize a raw ``title:`` value — strip \\r + whitespace + surrounding
    quotes ONLY (NO comment stripping: titles may contain unquoted ``#``,
    decision 16)."""
    v = raw.replace("\r", "").strip()
    if len(v) >= 2 and (
        (v[0] == '"' and v[-1] == '"') or (v[0] == "'" and v[-1] == "'")
    ):
        v = v[1:-1]
    return v


_FIELD_INDENT_RE = re.compile(r"^([ \t]*)-(\s*)id:")


def _field_indent_width(block_text: str) -> int | None:
    """Column at which the task's OWN scalar fields start, derived from its
    ``- id:`` header line (``id:`` and its sibling keys share that column)."""
    first_line = block_text.split("\n", 1)[0]
    m = _FIELD_INDENT_RE.match(first_line)
    if not m:
        return None
    return len(m.group(1)) + 1 + len(m.group(2))


def _extract_block_key(block_text: str, key: str) -> str | None:
    """Value tail of ``key:`` **at the task's own field column**, or None.

    Anchoring to the exact field column (not a permissive ``^[ \\t]*``) is
    load-bearing (pre-merge code-review I-4): a permissive anchor lets a
    DEEPER-indented ``status:`` line shadow the task's real one — e.g. a line
    inside a folded scalar (``notes: >`` / ``  status: done``) or a nested
    sub-mapping key appearing before the real field. Both were reproduced
    yielding ``done`` for tasks that should have counted as residual — a
    new false-green, exactly the direction this change exists to close.
    Shallower/absent → None → treated as residual (fail-CLOSED).
    """
    width = _field_indent_width(block_text)
    if width is None:  # pragma: no cover - block always starts at a `- id:` line
        return None
    pattern = re.compile(rf"^[ \t]{{{width}}}{re.escape(key)}:(.*)$", re.MULTILINE)
    m = pattern.search(block_text)
    if not m:
        return None
    return m.group(1)


def _extract_block_status(block_text: str) -> str | None:
    raw = _extract_block_key(block_text, "status")
    if raw is None:
        return None
    return _normalize_status_value(raw)


def _extract_block_title(block_text: str) -> str:
    raw = _extract_block_key(block_text, "title")
    if raw is None:
        return ""
    return _normalize_title_value(raw)


def _tasks_block_bounds(lines: list[str]) -> tuple[int, int] | None:
    """Return ``(start, end)`` line indices for the ``tasks:`` block body: from the
    line AFTER the 0-indent ``tasks:`` key up to the next 0-indent top-level key
    (or EOF). None if no top-level ``tasks:`` key exists.
    """
    tasks_indices = [
        i for i, line in enumerate(lines)
        if (m := _TOP_KEY_RE.match(line)) and m.group(1) == "tasks"
    ]
    if not tasks_indices:
        return None
    if len(tasks_indices) > 1:
        # Duplicate top-level `tasks:` (illegal YAML). Parsing only the first
        # block would silently drop every task in the others while reporting
        # parse_ok=True — the same hidden-entry class SC-3e closes, invisible to
        # the self-consistency count because that count is scoped to one block
        # (pre-merge code-review M-5). Fail closed instead.
        return None
    tasks_idx = tasks_indices[0]
    end_idx = len(lines)
    for j in range(tasks_idx + 1, len(lines)):
        if _TOP_KEY_RE.match(lines[j]):
            end_idx = j
            break
    return (tasks_idx + 1, end_idx)


def parse_detailed_tasks(text: str) -> dict:
    """Parse a detailed-tasks.yaml into ``{parse_ok, tasks, reason}``.

    ``tasks`` = ``[{"id": str|None, "raw_status": str|None, "title": str}, ...]``.
    Never raises (fail-soft). ``parse_ok=False`` only on the file-level four
    states: unreadable (caller's concern) / no top-level ``tasks:`` / zero
    ``- id:`` entries / structural self-inconsistency (list-item count mismatch).
    Entry-level defects (missing status/id) do NOT fail the whole file.
    """
    result: dict = {"parse_ok": False, "tasks": [], "reason": ""}
    lines = text.splitlines()

    bounds = _tasks_block_bounds(lines)
    if bounds is None:
        result["reason"] = "no single unambiguous top-level `tasks:` block (absent or duplicated)"
        return result
    start, end = bounds
    block_text = "\n".join(lines[start:end])

    id_matches = list(_TASK_ID_LINE_RE.finditer(block_text))
    if not id_matches:
        result["reason"] = "zero `- id:` entries under tasks:"
        return result

    # indent-anchored + range-bounded self-consistency count (SC-3e/3f).
    base_indent = id_matches[0].group(1)
    direct_item_re = re.compile(rf"^{re.escape(base_indent)}-\s", re.MULTILINE)
    direct_count = len(direct_item_re.findall(block_text))
    if direct_count != len(id_matches):
        result["reason"] = (
            f"structural self-inconsistency: {direct_count} base-indent list-item(s) "
            f"vs {len(id_matches)} `- id:` match(es) — hidden entry "
            "(id not first field / dash-id split across lines)"
        )
        return result

    tasks = []
    for task_id, block in _split_task_blocks(block_text):
        tasks.append(
            {
                "id": task_id,
                "raw_status": _extract_block_status(block),
                "title": _extract_block_title(block),
            }
        )
    result["parse_ok"] = True
    result["tasks"] = tasks
    result["reason"] = f"{len(tasks)} task(s) parsed"
    return result

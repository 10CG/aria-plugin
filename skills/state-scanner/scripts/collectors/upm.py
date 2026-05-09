"""Phase 1.4 — UPM phase_cycle + active_module collector.

State-scanner-inter-cycle-surfacing additions (2026-05-09):
- G2: `## Pending Followups` markdown table parser → `followups[]`
- G3: handoff doc pointer detection in raw_block top → `handoff_doc`
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ._common import CollectorResult

# Aria 主项目的 UPM 使用 strategic-commit-orchestrator 约定路径; 其他项目可能在 mobile/backend 子模块
_UPM_CANDIDATES = [
    "docs/project-planning/unified-progress-management.md",
    "mobile/docs/project-planning/unified-progress-management.md",
    "backend/docs/project-planning/unified-progress-management.md",
]

# YAML block 提取: HTML 注释 <!-- UPMv2-STATE ... --> 或 ```yaml UPMv2-STATE ... ```
_UPM_HTML_BLOCK = re.compile(
    r"<!--\s*UPMv2-STATE\s*\n([\s\S]+?)\n-->", re.MULTILINE
)
_UPM_FENCED_BLOCK = re.compile(
    r"```(?:yaml)?\s*\n(UPMv2-STATE:[\s\S]+?)\n```", re.MULTILINE
)

_YAML_BLOCK_SCALAR_MARKERS = {"|", ">", "|-", ">-", "|+", ">+"}

# ----- G2: Pending Followups table parsing ---------------------------------
# Heading anchor: `## Pending Followups` (H2 or H3, case-sensitive). Per BA-10
# follow-up, we use `[ \t]` instead of `\s` to explicitly REJECT fullwidth
# space (U+3000) and other unicode whitespace from the prefix.
_FOLLOWUPS_HEADING = re.compile(
    r"^[ \t]{0,3}#{2,3}[ \t]+Pending Followups[ \t]*$",
    re.MULTILINE,
)
# Priority column normalization: P0/P1/P2/P3 (case-insensitive), else "unknown".
_PRIORITY_VALID = re.compile(r"^[Pp][0-3]$")
# Column-name normalization map. Keys lowercased, accept English + Chinese.
_COLUMN_ALIASES: dict[str, str] = {
    "priority": "priority",
    "pri": "priority",
    "优先级": "priority",
    "item": "item",
    "事项": "item",
    "任务": "item",
    "source": "source",
    "来源": "source",
    "tracking": "tracking",
    "跟踪": "tracking",
    "next action": "next_action",
    "next_action": "next_action",
    "下一步": "next_action",
    "next": "next_action",
}
_PIPE_ESCAPE_PLACEHOLDER = "\x00"


def _split_table_row(row_text: str) -> list[str]:
    """Split a markdown table row on `|` while honoring `\\|` pipe-escape.

    Strips the leading/trailing pipe and surrounding whitespace from each cell.
    """
    # Replace escaped pipes with NUL so split doesn't see them.
    masked = row_text.replace("\\|", _PIPE_ESCAPE_PLACEHOLDER)
    parts = masked.split("|")
    # Drop empty cells from leading/trailing pipes (`| a | b |` → ['', 'a', 'b', '']).
    if parts and parts[0].strip() == "":
        parts = parts[1:]
    if parts and parts[-1].strip() == "":
        parts = parts[:-1]
    return [p.replace(_PIPE_ESCAPE_PLACEHOLDER, "|").strip() for p in parts]


def _is_separator_row(cells: list[str]) -> bool:
    """A markdown table separator row is `|---|---|...|` (only dashes/colons)."""
    if not cells:
        return False
    return all(re.fullmatch(r":?-{3,}:?", c) for c in cells)


def _normalize_priority(raw: str) -> str:
    s = raw.strip()
    if _PRIORITY_VALID.match(s):
        return s.upper()
    return "unknown"


def _parse_followups_table(text: str) -> list[dict[str, Any]] | None:
    """G2: parse `## Pending Followups` table from UPM markdown text.

    Returns:
        - None if no `## Pending Followups` heading is found (consumer treats
          the field as absent — distinct from "section exists but empty").
        - [] if heading exists but no table rows present.
        - [...] otherwise, with per-row dicts.
    """
    m = _FOLLOWUPS_HEADING.search(text)
    if m is None:
        return None

    # Scan from end of heading line forward, line by line.
    after = text[m.end():]
    lines = after.splitlines()

    # Find the first table row (line starting with `|` after optional spaces),
    # tolerating intervening blank lines / prose paragraphs.
    table_lines: list[str] = []
    started = False
    for line in lines:
        stripped = line.strip()
        # Stop if we hit a new heading (next section).
        if re.match(r"^#{1,6}[ \t]+\S", stripped):
            break
        if stripped.startswith("|"):
            started = True
            table_lines.append(stripped)
            continue
        if started:
            # Already in table; non-pipe line ends the table.
            break

    if not table_lines:
        return []

    # First row = header; second row should be separator (skipped).
    header_cells = _split_table_row(table_lines[0])
    body_lines = table_lines[1:]
    # Skip separator if present.
    if body_lines:
        sep_cells = _split_table_row(body_lines[0])
        if _is_separator_row(sep_cells):
            body_lines = body_lines[1:]

    # Map header columns → canonical names. Unknown columns → keep raw lowercased.
    canonical_columns: list[str] = []
    for h in header_cells:
        key = h.strip().lower()
        canonical_columns.append(_COLUMN_ALIASES.get(key, key))

    out: list[dict[str, Any]] = []
    for idx, raw_row in enumerate(body_lines, start=1):
        cells = _split_table_row(raw_row)
        if not cells:
            continue
        row_data: dict[str, Any] = {
            "row_index": idx,
            "priority": "unknown",
            "item": None,
            "source": None,
            "tracking": None,
            "next_action": None,
            "raw_row": raw_row,
        }
        for col_idx, canonical in enumerate(canonical_columns):
            if col_idx >= len(cells):
                break
            value = cells[col_idx]
            if canonical == "priority":
                row_data["priority"] = _normalize_priority(value)
            elif canonical in ("item", "source", "tracking", "next_action"):
                row_data[canonical] = value if value else None
        out.append(row_data)
    return out


# ----- G3: handoff_doc pointer detection ----------------------------------
# Primary regex: explicit phrase enumeration (Chinese + English + Emoji).
_HANDOFF_PRIMARY = re.compile(
    r"^>\s*[^\n]*?(?:Next session 入口|下次 session 入口|🚪 Next session)"
    r"[^\n]*?\(([^)]+\.md)\)",
    re.MULTILINE,
)
# Fallback regex: keyword-based (R2-converged form, NO standalone "入口" alternation
# per BA-02 fix — Chinese "入口" alone would over-match technical prose like
# "函数入口" / "调试入口").
_HANDOFF_FALLBACK = re.compile(
    r"^>\s*.*?(?:handoff|session)[^()\n]{0,80}\(([^)]+\.md)\)",
    re.MULTILINE,
)
_URL_SCHEME = re.compile(r"^https?://", re.IGNORECASE)
_HANDOFF_SCAN_LINES = 30  # raw_block top ±30 lines per Spec L114


def _detect_handoff_doc(
    raw_block: str | None, project_root: Path, r: CollectorResult
) -> dict[str, Any] | None:
    """G3: scan raw_block top for handoff doc pointer; return HandoffDoc or None.

    Returns None when no match (consumer-visible: `handoff_doc: null` —
    distinguishes "scanned, no match" from key-absent which means
    "pre-TX-G3 scanner version").
    """
    if not raw_block:
        return None

    # Limit scan to top N lines per Spec.
    lines = raw_block.splitlines()
    head = "\n".join(lines[:_HANDOFF_SCAN_LINES])

    raw_path: str | None = None
    raw_match: str | None = None
    m = _HANDOFF_PRIMARY.search(head)
    if m is not None:
        raw_path = m.group(1).strip()
        raw_match = m.group(0)
    else:
        m = _HANDOFF_FALLBACK.search(head)
        if m is not None:
            raw_path = m.group(1).strip()
            raw_match = m.group(0)

    if raw_path is None:
        return None

    # Three-state path resolution per BA-11 + Spec L264-267.
    if _URL_SCHEME.match(raw_path):
        # URL — preserve verbatim, mark non-existent, soft-error.
        r.soft_error("unsupported_path_format", f"handoff_doc URL: {raw_path}")
        return {
            "path": raw_path,
            "exists": False,
            "raw_match": raw_match,
        }

    candidate = Path(raw_path)
    if candidate.is_absolute():
        # Absolute — resolve, no relative_to rewrite.
        try:
            resolved = candidate.resolve()
            return {
                "path": str(candidate),
                "exists": resolved.exists(),
                "raw_match": raw_match,
            }
        except OSError:
            return {
                "path": raw_path,
                "exists": False,
                "raw_match": raw_match,
            }

    # Relative path — try (project_root / raw).resolve() then relative_to.
    abs_path = (project_root / raw_path).resolve()
    try:
        rel = abs_path.relative_to(project_root.resolve())
        return {
            "path": str(rel),
            "exists": abs_path.exists(),
            "raw_match": raw_match,
        }
    except ValueError:
        # relative_to failed — path escapes project_root. Fail-soft: keep raw.
        r.soft_error("handoff_path_escapes_project", raw_path)
        return {
            "path": raw_path,
            "exists": abs_path.exists(),
            "raw_match": raw_match,
        }


def _extract_yaml_scalar(block: str, key: str) -> str | None:
    """Extract `key: value` from YAML-ish block.

    Limitations (stdlib-only):
    - `key: |` or `key: >` (block scalar): returns None, not the literal marker.
      Real block scalar bodies span multiple lines and cannot be parsed inline here.
    - Nested mappings / anchors / flow style: not supported; returns None.
    - Partition uses FIRST colon, so `key: M1: Layer 2` → "M1: Layer 2" (preserved).
    """
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            continue
        k, _, v = stripped.partition(":")
        if k.strip() != key:
            continue
        v = v.strip()
        if "#" in v:
            v = v[: v.index("#")].strip()
        v = v.strip("\"'")
        if v in _YAML_BLOCK_SCALAR_MARKERS:
            return None
        return v or None
    return None


def collect_upm_state(project_root: Path) -> CollectorResult:
    """Extract UPM machine-readable phase/cycle/module block + inter-cycle fields.

    Output shape (post-G2/G3 ship):
      {
        "configured": bool,
        "source_file": str | null,
        "current_phase": str | null,
        "current_cycle": str | null,
        "active_module": str | null,
        "raw_block": str | null,
        # G2 — present only when UPM has `## Pending Followups` section.
        # Consumer: `upm.get("followups", [])` defensive access.
        "followups": list[FollowupRow]?,
        # G3 — null when scanned but no match; absent only on pre-TX-G3 scanner.
        "handoff_doc": HandoffDoc | null,
      }
    UPM is optional. Missing file → configured: false, all fields null (fail-soft).
    """
    r = CollectorResult()
    found_path: Path | None = None
    for candidate in _UPM_CANDIDATES:
        p = project_root / candidate
        if p.exists():
            found_path = p
            break

    if found_path is None:
        # Schema §upm L160: missing UPM → `followups` + `handoff_doc` keys ABSENT
        # (distinguishes "scanner ran, found nothing" from "no UPM to scan").
        r.data = {
            "configured": False,
            "source_file": None,
            "current_phase": None,
            "current_cycle": None,
            "active_module": None,
            "raw_block": None,
        }
        return r

    try:
        text = found_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        r.soft_error("upm_read_failed", str(e))
        # Read error: same absence semantic as no-UPM-file (no successful scan).
        r.data = {
            "configured": False,
            "source_file": str(found_path.relative_to(project_root)),
            "current_phase": None,
            "current_cycle": None,
            "active_module": None,
            "raw_block": None,
        }
        return r

    block = None
    m = _UPM_HTML_BLOCK.search(text)
    if m:
        block = m.group(1).strip()
    else:
        m2 = _UPM_FENCED_BLOCK.search(text)
        if m2:
            block = m2.group(1).strip()

    # G2: parse Pending Followups table (independent of UPMv2-STATE block).
    followups = _parse_followups_table(text)

    if block is None:
        r.soft_error("upm_block_not_found", "UPMv2-STATE marker missing")
        # Block missing: G3 had no raw_block to scan, so handoff_doc key is ABSENT
        # (consistent with schema's null-vs-absent contract — null is reserved for
        # "scanned raw_block, no match"). G2 followups still emitted if
        # `## Pending Followups` heading exists in the surrounding text.
        data: dict[str, Any] = {
            "configured": True,
            "source_file": str(found_path.relative_to(project_root)),
            "current_phase": None,
            "current_cycle": None,
            "active_module": None,
            "raw_block": None,
        }
        if followups is not None:
            data["followups"] = followups
        r.data = data
        return r

    phase = _extract_yaml_scalar(block, "current_phase") or _extract_yaml_scalar(block, "phase")
    cycle = _extract_yaml_scalar(block, "current_cycle") or _extract_yaml_scalar(block, "cycle")
    module = _extract_yaml_scalar(block, "active_module") or _extract_yaml_scalar(block, "module")

    # G3: detect handoff doc pointer in UPMv2-STATE block top.
    handoff_doc = _detect_handoff_doc(block, project_root, r)

    data = {
        "configured": True,
        "source_file": str(found_path.relative_to(project_root)),
        "current_phase": phase,
        "current_cycle": cycle,
        "active_module": module,
        "raw_block": block,
        "handoff_doc": handoff_doc,
    }
    if followups is not None:
        data["followups"] = followups
    r.data = data
    return r

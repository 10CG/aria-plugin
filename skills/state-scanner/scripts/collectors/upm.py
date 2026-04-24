"""Phase 1.4 — UPM phase_cycle + active_module collector."""

from __future__ import annotations

import re
from pathlib import Path

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
    """Extract UPM machine-readable phase/cycle/module block.

    Output shape:
      {
        "configured": bool,
        "source_file": str | null,
        "current_phase": str | null,
        "current_cycle": str | null,
        "active_module": str | null,
        "raw_block": str | null
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

    if block is None:
        r.soft_error("upm_block_not_found", "UPMv2-STATE marker missing")
        r.data = {
            "configured": True,
            "source_file": str(found_path.relative_to(project_root)),
            "current_phase": None,
            "current_cycle": None,
            "active_module": None,
            "raw_block": None,
        }
        return r

    phase = _extract_yaml_scalar(block, "current_phase") or _extract_yaml_scalar(block, "phase")
    cycle = _extract_yaml_scalar(block, "current_cycle") or _extract_yaml_scalar(block, "cycle")
    module = _extract_yaml_scalar(block, "active_module") or _extract_yaml_scalar(block, "module")

    r.data = {
        "configured": True,
        "source_file": str(found_path.relative_to(project_root)),
        "current_phase": phase,
        "current_cycle": cycle,
        "active_module": module,
        "raw_block": block,
    }
    return r

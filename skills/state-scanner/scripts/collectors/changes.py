"""Phase 1.5 — Changes analysis collector."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._common import CollectorResult

_CODE_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".dart", ".sh"}
_TEST_MARKERS = ("test_", "_test.", "/tests/", "/test/", ".test.", ".spec.")
_DOC_EXTS = {".md", ".rst", ".txt"}
_CONFIG_EXTS = {".json", ".yaml", ".yml", ".toml", ".ini"}


def _classify_file(path: str) -> str:
    """Classify file as 'code'/'test'/'docs'/'config'/'other'."""
    if any(marker in path for marker in _TEST_MARKERS):
        return "test"
    suffix = Path(path).suffix
    if suffix in _CODE_EXTS:
        return "code"
    if suffix in _DOC_EXTS:
        return "docs"
    if suffix in _CONFIG_EXTS:
        return "config"
    return "other"


def collect_changes_analysis(git_state: dict[str, Any]) -> CollectorResult:
    """Analyze staged+unstaged+untracked changes for complexity and skill impact.

    Heuristic (TL-2 advisory_from_collector — workflow-runner / AI may override):
      - L1: 0-2 files, no code changes OR only docs
      - L2: 3-10 files, mixed code+test+docs, no arch docs
      - L3: >10 files OR arch docs touched OR SKILL.md modified
    """
    r = CollectorResult()
    # R2-N3: dedupe by path so change_count aligns with uncommitted_count.
    all_files = sorted(
        set(git_state.get("staged_files", []))
        | set(git_state.get("unstaged_files", []))
        | set(git_state.get("untracked_files", []))
    )
    file_types = {"code": 0, "test": 0, "docs": 0, "config": 0, "other": 0}
    for f in all_files:
        file_types[_classify_file(f)] += 1

    arch_impact = any(
        "docs/architecture/" in f or "ARCHITECTURE.md" in f for f in all_files
    )
    test_coverage = file_types["test"] > 0 and file_types["code"] > 0

    modified_skills = sorted(
        {
            f.split("/skills/")[1].split("/")[0]
            for f in all_files
            if "/skills/" in f and ("SKILL.md" in f or f.endswith(".py") or f.endswith(".md"))
        }
    )

    skill_changes = {
        "detected": any("SKILL.md" in f for f in all_files),
        "modified_skills": modified_skills,
        "ab_status": {"verified": [], "needs_benchmark": modified_skills},
    }

    n = len(all_files)
    complexity = "Level 1"
    if arch_impact or skill_changes["detected"] or n > 10:
        complexity = "Level 3"
    elif n >= 3 or (file_types["code"] + file_types["test"]) >= 1:
        complexity = "Level 2"

    r.data = {
        "change_count": n,
        "file_types": file_types,
        "complexity": complexity,
        "architecture_impact": arch_impact,
        "test_coverage": test_coverage,
        "skill_changes": skill_changes,
    }
    return r

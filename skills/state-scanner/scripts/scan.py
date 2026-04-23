#!/usr/bin/env python3
"""state-scanner mechanical collector — Phase 0 + Phase 1 + Phase 1.5-1.10.

Spec: openspec/changes/state-scanner-mechanical-enforcement/
Schema: aria/skills/state-scanner/references/state-snapshot-schema.md
Audit: .aria/audit-reports/post_spec-2026-04-23T2058Z-state-scanner-mechanical.md

Coverage (schema v1.0):
- Phase 0: interrupt recovery (workflow-state.json)
- Phase 1: git state (branch, status, upstream, recent_commits)
- Phase 1.4: UPM phase_cycle + active_module (fail-soft if UPM absent)
- Phase 1.5: changes analysis (file_types, complexity L1-L3, skill_changes)
- Phase 1.5-req: requirements (PRD + User Stories, 5 Status regex variants)
- Phase 1.6: OpenSpec (changes + archive)
- Phase 1.7: architecture (system-architecture.md header)
- Phase 1.8: README sync (version + skill count consistency)
- Phase 1.9: standards submodule presence
- Phase 1.10: audit reports latest

Invariants (do not break without schema bump):
- Top-level field `snapshot_schema_version` is the ONLY version gate SKILL.md asserts on.
- `issue_status.schema_version` is a nested, independent field (CF-3 naming isolation).
- Collectors are fail-soft: per-phase errors produce `{"error": "<kind>", "detail": "<msg>"}`
  entries and never abort the whole scan.
- stdlib-only: subprocess, json, os, pathlib, argparse, re, sys. No third-party deps.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SNAPSHOT_SCHEMA_VERSION = "1.0"

EXIT_OK = 0
EXIT_SCAN_PARTIAL = 10          # some collectors soft-errored but output is usable
EXIT_HARD_PRECONDITION = 20     # cwd is not a git repo, etc.
EXIT_INTERNAL_BUG = 30          # uncaught exception path


log = logging.getLogger("state-scanner.scan")


@dataclass
class CollectorResult:
    data: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, str]] = field(default_factory=list)

    def soft_error(self, kind: str, detail: str) -> None:
        self.errors.append({"error": kind, "detail": detail})
        log.warning("collector soft error: %s — %s", kind, detail)


def _run(cmd: list[str], cwd: Path, timeout: int = 5) -> tuple[int, str, str]:
    """subprocess wrapper: returns (rc, stdout, stderr). Never raises on non-zero rc."""
    try:
        p = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        return 124, "", f"timeout after {timeout}s: {e}"
    except FileNotFoundError as e:
        return 127, "", f"command not found: {e}"


# ----------------------------------------------------------------------------
# Phase 0: Interrupt Recovery
# ----------------------------------------------------------------------------

def collect_interrupt_state(project_root: Path) -> CollectorResult:
    """Read .aria/workflow-state.json and report interrupt status.

    Output shape:
      {
        "present": bool,
        "status": "none" | "in_progress" | "suspended" | "failed" | "corrupted",
        "branch_anchor_match": bool | null,
        "session_age_seconds": int | null,
        "raw": {...} | null
      }
    """
    r = CollectorResult()
    state_file = project_root / ".aria" / "workflow-state.json"

    if not state_file.exists():
        r.data = {
            "present": False,
            "status": "none",
            "branch_anchor_match": None,
            "session_age_seconds": None,
            "raw": None,
        }
        return r

    try:
        raw = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        r.soft_error("workflow_state_corrupted", str(e))
        r.data = {
            "present": True,
            "status": "corrupted",
            "branch_anchor_match": None,
            "session_age_seconds": None,
            "raw": None,
        }
        return r

    anchor_branch = (raw.get("git_anchor") or {}).get("branch")
    current_branch = _current_branch(project_root)
    branch_match = (
        (anchor_branch == current_branch) if (anchor_branch and current_branch) else None
    )

    r.data = {
        "present": True,
        "status": raw.get("status", "in_progress"),
        "branch_anchor_match": branch_match,
        "session_age_seconds": None,  # T1.2 defers session-age calc to later patch
        "raw": raw,
    }
    return r


# ----------------------------------------------------------------------------
# Phase 1: Git State
# ----------------------------------------------------------------------------

def _current_branch(project_root: Path) -> str | None:
    rc, out, _ = _run(["git", "branch", "--show-current"], project_root)
    if rc != 0:
        return None
    branch = out.strip()
    return branch or None


def collect_git_state(project_root: Path) -> CollectorResult:
    """Collect git status, branch, upstream divergence, and recent commits.

    Output shape:
      {
        "is_git_repo": bool,
        "current_branch": str | null,
        "detached_head": bool,
        "staged_files": [str, ...],
        "unstaged_files": [str, ...],
        "untracked_files": [str, ...],
        "uncommitted_count": int,
        "upstream": {
          "configured": bool,
          "name": str | null,        # e.g. "origin/master"
          "ahead": int | null,
          "behind": int | null,
          "reason": str | null       # "no_upstream" | "shallow_clone" | "detached_head" | null
        },
        "recent_commits": [{"sha": str, "subject": str}, ...],
        "shallow": bool
      }
    """
    r = CollectorResult()
    rc, _, _ = _run(["git", "rev-parse", "--is-inside-work-tree"], project_root)
    if rc != 0:
        r.soft_error("not_a_git_repo", f"rc={rc}")
        r.data = {"is_git_repo": False}
        return r

    data: dict[str, Any] = {"is_git_repo": True, "shallow": _is_shallow(project_root)}

    branch = _current_branch(project_root)
    data["current_branch"] = branch
    data["detached_head"] = branch is None

    # status --porcelain=v1 -z for safe parsing; v1 keeps XY two-char prefix
    rc, out, err = _run(["git", "status", "--porcelain=v1", "-z"], project_root)
    if rc != 0:
        r.soft_error("git_status_failed", err.strip())
        data.update(
            staged_files=[], unstaged_files=[], untracked_files=[], uncommitted_count=0
        )
    else:
        staged, unstaged, untracked = _parse_porcelain_z(out)
        data["staged_files"] = staged
        data["unstaged_files"] = unstaged
        data["untracked_files"] = untracked
        data["uncommitted_count"] = len(staged) + len(unstaged) + len(untracked)

    data["upstream"] = _collect_upstream(project_root, branch, data["shallow"])
    data["recent_commits"] = _collect_recent_commits(project_root, r)

    r.data = data
    return r


def _is_shallow(project_root: Path) -> bool:
    rc, out, _ = _run(["git", "rev-parse", "--is-shallow-repository"], project_root)
    return rc == 0 and out.strip() == "true"


def _parse_porcelain_z(raw: str) -> tuple[list[str], list[str], list[str]]:
    """Parse `git status --porcelain=v1 -z` output into staged/unstaged/untracked lists.

    NUL-separated. Rename/copy entries have two names separated by an extra NUL; we
    only keep the destination path for staging/unstaging bookkeeping.
    """
    staged: list[str] = []
    unstaged: list[str] = []
    untracked: list[str] = []

    tokens = raw.split("\x00")
    i = 0
    while i < len(tokens):
        entry = tokens[i]
        if not entry:
            i += 1
            continue
        # entry is "XY path" where XY is two chars and space separates path
        if len(entry) < 4:
            i += 1
            continue
        xy = entry[:2]
        path = entry[3:]
        # Renames/copies: next token holds original path → skip it
        if xy[0] in ("R", "C") or xy[1] in ("R", "C"):
            i += 2
            if xy[0] != " ":
                staged.append(path)
            if xy[1] != " ":
                unstaged.append(path)
            continue
        if xy == "??":
            untracked.append(path)
        else:
            if xy[0] != " ":
                staged.append(path)
            if xy[1] != " ":
                unstaged.append(path)
        i += 1

    return staged, unstaged, untracked


def _collect_upstream(
    project_root: Path, branch: str | None, shallow: bool
) -> dict[str, Any]:
    if branch is None:
        return {
            "configured": False,
            "name": None,
            "ahead": None,
            "behind": None,
            "reason": "detached_head",
        }
    if shallow:
        return {
            "configured": None,
            "name": None,
            "ahead": None,
            "behind": None,
            "reason": "shallow_clone",
        }

    rc, out, _ = _run(
        ["git", "rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}"], project_root
    )
    if rc != 0:
        return {
            "configured": False,
            "name": None,
            "ahead": None,
            "behind": None,
            "reason": "no_upstream",
        }
    upstream = out.strip()

    rc, out, err = _run(
        ["git", "rev-list", "--left-right", "--count", f"HEAD...{upstream}"],
        project_root,
    )
    if rc != 0:
        return {
            "configured": True,
            "name": upstream,
            "ahead": None,
            "behind": None,
            "reason": "rev_list_failed",
        }
    parts = out.strip().split()
    if len(parts) != 2:
        return {
            "configured": True,
            "name": upstream,
            "ahead": None,
            "behind": None,
            "reason": "parse_failed",
        }
    ahead, behind = int(parts[0]), int(parts[1])
    return {
        "configured": True,
        "name": upstream,
        "ahead": ahead,
        "behind": behind,
        "reason": None,
    }


_COMMIT_LINE = re.compile(r"^([0-9a-f]{7,40})\s+(.*)$")


def _collect_recent_commits(
    project_root: Path, r: CollectorResult, limit: int = 5
) -> list[dict[str, str]]:
    rc, out, err = _run(
        ["git", "log", "--oneline", f"-{limit}", "--no-decorate"], project_root
    )
    if rc != 0:
        r.soft_error("git_log_failed", err.strip())
        return []
    commits: list[dict[str, str]] = []
    for line in out.splitlines():
        m = _COMMIT_LINE.match(line.strip())
        if m:
            commits.append({"sha": m.group(1), "subject": m.group(2)})
    return commits


# ----------------------------------------------------------------------------
# Phase 1.4: UPM phase_cycle + active_module
# ----------------------------------------------------------------------------

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

    # Minimal YAML-ish parsing (stdlib-only): look for `key: value` at line start
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
        # Block scalar marker alone → unsupported, return None rather than leaking "|"
        if v in _YAML_BLOCK_SCALAR_MARKERS:
            return None
        return v or None
    return None


# ----------------------------------------------------------------------------
# Phase 1.5: Changes Analysis
# ----------------------------------------------------------------------------

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

    Output shape:
      {
        "change_count": int,
        "file_types": {"code": int, "test": int, "docs": int, "config": int, "other": int},
        "complexity": "Level 1" | "Level 2" | "Level 3",
        "architecture_impact": bool,
        "test_coverage": bool,
        "skill_changes": {
          "detected": bool,
          "modified_skills": [str, ...],
          "ab_status": {"verified": [], "needs_benchmark": [...]}
        }
      }
    Heuristic (documented in schema.md):
      - L1: 0-2 files, no code changes OR only docs
      - L2: 3-10 files, mixed code+test+docs, no arch docs
      - L3: >10 files OR arch docs touched OR SKILL.md modified
    """
    r = CollectorResult()
    all_files = (
        list(git_state.get("staged_files", []))
        + list(git_state.get("unstaged_files", []))
        + list(git_state.get("untracked_files", []))
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


# ----------------------------------------------------------------------------
# Phase 1.5 (requirements): PRD + User Stories
# ----------------------------------------------------------------------------

# 5 Status extraction regex variants per SKILL.md Phase 1.5
_STATUS_PATTERNS = [
    re.compile(r"^\*\*Status\*\*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\*\*状态\*\*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^>\s*\*\*Status\*\*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^Status:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\|\s*(?:Status|状态)\s*\|\s*(.+?)\s*\|", re.IGNORECASE | re.MULTILINE),
]


def _extract_status(text: str) -> str | None:
    for pat in _STATUS_PATTERNS:
        m = pat.search(text)
        if m:
            # Take first line segment (e.g., "done (2026-04-23, ...)" → keep full)
            raw = m.group(1).strip()
            return raw
    return None


def _normalize_status(raw: str | None) -> str:
    """Normalize Status string to OpenSpec-aligned lifecycle states.

    Preserves semantic distinction between Draft/Reviewed/Approved/In Progress/Done
    per OpenSpec standard. `ready` is for User Stories with explicit `ready` marker only.
    """
    if raw is None:
        return "unknown"
    low = raw.lower()
    # Order matters: check specific states before generic ones
    for token in ("done", "complete"):
        if token in low:
            return "done"
    for token in ("in progress", "in_progress", "in-progress", "进行中"):
        if token in low:
            return "in_progress"
    if "approved" in low:
        return "approved"
    if "reviewed" in low:
        return "reviewed"
    if "ready" in low:
        return "ready"
    for token in ("draft", "pending", "placeholder"):
        if token in low:
            return "pending"
    return "unknown"


def collect_requirements(project_root: Path) -> CollectorResult:
    """Scan docs/requirements/ for PRD + User Stories with Status extraction.

    Output shape:
      {
        "configured": bool,
        "prd": [{"path": str, "status": str, "raw_status": str | null}, ...],
        "stories": {
          "total": int,
          "by_status": {"ready": int, "in_progress": int, "done": int, "pending": int, "unknown": int},
          "items": [{"id": str, "path": str, "status": str, "raw_status": str | null}, ...]
        }
      }
    Fail-soft: requirements/ absent → configured: false, empty shells.
    """
    r = CollectorResult()
    req_dir = project_root / "docs" / "requirements"
    if not req_dir.is_dir():
        r.data = {
            "configured": False,
            "prd": [],
            "stories": {"total": 0, "by_status": {}, "items": []},
        }
        return r

    prd_items: list[dict[str, Any]] = []
    for prd_path in sorted(req_dir.glob("prd-*.md")):
        try:
            raw = _extract_status(prd_path.read_text(encoding="utf-8", errors="replace"))
        except OSError as e:
            r.soft_error("prd_read_failed", f"{prd_path.name}: {e}")
            continue
        prd_items.append(
            {
                "path": str(prd_path.relative_to(project_root)),
                "status": _normalize_status(raw),
                "raw_status": raw,
            }
        )

    stories_dir = req_dir / "user-stories"
    story_items: list[dict[str, Any]] = []
    by_status = {"ready": 0, "in_progress": 0, "done": 0, "pending": 0, "unknown": 0}
    if stories_dir.is_dir():
        for us_path in sorted(stories_dir.glob("US-*.md")):
            try:
                raw = _extract_status(us_path.read_text(encoding="utf-8", errors="replace"))
            except OSError as e:
                r.soft_error("us_read_failed", f"{us_path.name}: {e}")
                continue
            st = _normalize_status(raw)
            by_status[st] = by_status.get(st, 0) + 1
            story_items.append(
                {
                    "id": us_path.stem,
                    "path": str(us_path.relative_to(project_root)),
                    "status": st,
                    "raw_status": raw,
                }
            )

    r.data = {
        "configured": True,
        "prd": prd_items,
        "stories": {
            "total": len(story_items),
            "by_status": by_status,
            "items": story_items,
        },
    }
    return r


# ----------------------------------------------------------------------------
# Phase 1.6: OpenSpec (changes + archive)
# ----------------------------------------------------------------------------

def collect_openspec(project_root: Path) -> CollectorResult:
    """Scan openspec/changes/ + openspec/archive/ for active + archived Specs."""
    r = CollectorResult()
    spec_root = project_root / "openspec"
    changes_dir = spec_root / "changes"
    archive_dir = spec_root / "archive"

    if not changes_dir.is_dir():
        r.data = {
            "configured": False,
            "changes": {"total": 0, "items": []},
            "archive": {"total": 0, "items": []},
            "pending_archive": [],
        }
        return r

    change_items: list[dict[str, Any]] = []
    pending_archive: list[dict[str, Any]] = []
    for d in sorted(changes_dir.iterdir()):
        if not d.is_dir():
            continue
        proposal = d / "proposal.md"
        if not proposal.exists():
            continue
        try:
            raw = _extract_status(proposal.read_text(encoding="utf-8", errors="replace"))
        except OSError as e:
            r.soft_error("spec_read_failed", f"{d.name}: {e}")
            continue
        st = _normalize_status(raw)
        item = {
            "id": d.name,
            "path": str(proposal.relative_to(project_root)),
            "status": st,
            "raw_status": raw,
        }
        change_items.append(item)
        if st == "done":
            pending_archive.append({"id": d.name, "reason": "Status=done still in changes/"})

    archive_items: list[dict[str, Any]] = []
    if archive_dir.is_dir():
        for d in sorted(archive_dir.iterdir()):
            if not d.is_dir():
                continue
            m = re.match(r"^(\d{4}-\d{2}-\d{2})-(.+)$", d.name)
            archive_items.append(
                {
                    "path": str(d.relative_to(project_root)),
                    "date": m.group(1) if m else None,
                    "feature": m.group(2) if m else d.name,
                }
            )

    r.data = {
        "configured": True,
        "changes": {"total": len(change_items), "items": change_items},
        "archive": {"total": len(archive_items), "items": archive_items},
        "pending_archive": pending_archive,
    }
    return r


# ----------------------------------------------------------------------------
# Phase 1.7: Architecture Status
# ----------------------------------------------------------------------------

_ARCH_STATUS_PAT = re.compile(r"^>?\s*\*\*Status\*\*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_ARCH_LAST_UPD = re.compile(r"^>?\s*\*\*Last Updated\*\*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_ARCH_PRD = re.compile(r"^>?\s*\*\*Parent PRD\*\*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)


def collect_architecture(project_root: Path) -> CollectorResult:
    r = CollectorResult()
    arch_file = project_root / "docs" / "architecture" / "system-architecture.md"
    if not arch_file.is_file():
        r.data = {
            "exists": False,
            "path": None,
            "status": None,
            "last_updated": None,
            "parent_prd": None,
            "chain_valid": None,
        }
        return r

    try:
        text = arch_file.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        r.soft_error("arch_read_failed", str(e))
        r.data = {
            "exists": True,
            "path": str(arch_file.relative_to(project_root)),
            "status": None,
            "last_updated": None,
            "parent_prd": None,
            "chain_valid": None,
        }
        return r

    def _first(p: re.Pattern[str]) -> str | None:
        m = p.search(text)
        return m.group(1).strip() if m else None

    status = _first(_ARCH_STATUS_PAT)
    last_upd = _first(_ARCH_LAST_UPD)
    parent_prd = _first(_ARCH_PRD)
    chain_valid = _is_real_prd_reference(parent_prd)

    r.data = {
        "exists": True,
        "path": str(arch_file.relative_to(project_root)),
        "status": status,
        "last_updated": last_upd,
        "parent_prd": parent_prd,
        "chain_valid": chain_valid,
    }
    return r


_PRD_PLACEHOLDER_MARKERS = {
    "tbd", "pending", "(pending)", "(tbd)", "n/a", "todo", "(todo)", "placeholder",
    "待填写", "待定", "未定",
}


def _is_real_prd_reference(parent_prd: str | None) -> bool:
    """Reject placeholder strings as chain_valid=True (audit IMP-2 fix).

    A real PRD reference must be non-empty and not a known placeholder token.
    File-existence verification is deferred (filename vs markdown link variance).
    """
    if not parent_prd:
        return False
    low = parent_prd.strip().lower()
    if low in _PRD_PLACEHOLDER_MARKERS:
        return False
    return True


# ----------------------------------------------------------------------------
# Phase 1.8: README sync check
# ----------------------------------------------------------------------------

_VERSION_PAT = re.compile(r"^\s*\*\*(?:版本|Version)\*\*[:：]\s*v?([\d.]+)", re.IGNORECASE | re.MULTILINE)


def collect_readme_sync(project_root: Path) -> CollectorResult:
    r = CollectorResult()
    root_readme = project_root / "README.md"
    plugin_json = project_root / "aria" / ".claude-plugin" / "plugin.json"

    def _read_version_from_readme(path: Path) -> str | None:
        if not path.is_file():
            return None
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        m = _VERSION_PAT.search(text)
        return m.group(1) if m else None

    root_readme_version = _read_version_from_readme(root_readme)

    plugin_version = None
    aria_readme_version = None
    if plugin_json.is_file():
        try:
            plugin_data = json.loads(plugin_json.read_text(encoding="utf-8"))
            plugin_version = plugin_data.get("version")
        except (OSError, json.JSONDecodeError) as e:
            r.soft_error("plugin_json_read_failed", str(e))

    aria_readme = project_root / "aria" / "README.md"
    aria_readme_version = _read_version_from_readme(aria_readme)

    r.data = {
        "root": {
            "exists": root_readme.is_file(),
            "version": root_readme_version,
        },
        "submodules": {
            "aria": {
                "exists": aria_readme.is_file(),
                "readme_version": aria_readme_version,
                "plugin_version": plugin_version,
                "version_match": (
                    aria_readme_version == plugin_version
                    if (aria_readme_version and plugin_version)
                    else None
                ),
            }
        },
    }
    return r


# ----------------------------------------------------------------------------
# Phase 1.9: standards submodule
# ----------------------------------------------------------------------------

def collect_standards(project_root: Path) -> CollectorResult:
    r = CollectorResult()
    gitmodules = project_root / ".gitmodules"
    standards_dir = project_root / "standards"

    if not gitmodules.exists():
        r.data = {"registered": False, "initialized": False}
        return r

    try:
        text = gitmodules.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        r.soft_error("gitmodules_read_failed", str(e))
        r.data = {"registered": False, "initialized": False}
        return r

    registered = "path = standards" in text or "path=standards" in text
    initialized = (
        standards_dir.is_dir() and any(standards_dir.iterdir()) if standards_dir.exists() else False
    )
    r.data = {"registered": registered, "initialized": initialized}
    return r


# ----------------------------------------------------------------------------
# Phase 1.10: latest audit report
# ----------------------------------------------------------------------------

_AUDIT_FM = re.compile(r"^---\s*\n([\s\S]+?)\n---", re.MULTILINE)


def collect_audit(project_root: Path) -> CollectorResult:
    """Parse .aria/audit-reports/ for most recent report frontmatter."""
    r = CollectorResult()
    audit_dir = project_root / ".aria" / "audit-reports"
    if not audit_dir.is_dir():
        r.data = {"enabled": None, "last_audit": None}
        return r

    reports = sorted(audit_dir.glob("*.md"), key=lambda p: p.stat().st_mtime)
    if not reports:
        r.data = {"enabled": True, "last_audit": None}
        return r

    latest = reports[-1]
    try:
        text = latest.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        r.soft_error("audit_read_failed", str(e))
        r.data = {"enabled": True, "last_audit": None}
        return r

    fm = _AUDIT_FM.search(text)
    meta: dict[str, Any] = {}
    if fm:
        for line in fm.group(1).splitlines():
            if ":" not in line:
                continue
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip().strip("\"'")

    r.data = {
        "enabled": True,
        "last_audit": {
            "path": str(latest.relative_to(project_root)),
            "checkpoint": meta.get("checkpoint"),
            "verdict": meta.get("verdict"),
            "converged": meta.get("converged"),
            "timestamp": meta.get("timestamp"),
        },
    }
    return r


# ----------------------------------------------------------------------------
# Top-level orchestration
# ----------------------------------------------------------------------------

def build_snapshot(project_root: Path) -> tuple[dict[str, Any], int]:
    """Run all collectors and return (snapshot, exit_code)."""
    errors: list[dict[str, Any]] = []

    phase0 = collect_interrupt_state(project_root)
    phase1_git = collect_git_state(project_root)
    phase1_4_upm = collect_upm_state(project_root)
    phase1_5_changes = collect_changes_analysis(phase1_git.data)
    phase1_5_req = collect_requirements(project_root)
    phase1_6_openspec = collect_openspec(project_root)
    phase1_7_arch = collect_architecture(project_root)
    phase1_8_readme = collect_readme_sync(project_root)
    phase1_9_standards = collect_standards(project_root)
    phase1_10_audit = collect_audit(project_root)

    for collector_name, result in [
        ("interrupt", phase0),
        ("git", phase1_git),
        ("upm", phase1_4_upm),
        ("changes", phase1_5_changes),
        ("requirements", phase1_5_req),
        ("openspec", phase1_6_openspec),
        ("architecture", phase1_7_arch),
        ("readme", phase1_8_readme),
        ("standards", phase1_9_standards),
        ("audit", phase1_10_audit),
    ]:
        for err in result.errors:
            errors.append({"collector": collector_name, **err})

    snapshot = {
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "generated_by": "scan.py",
        "project_root": str(project_root),
        "interrupt": phase0.data,
        "git": phase1_git.data,
        "upm": phase1_4_upm.data,
        "changes": phase1_5_changes.data,
        "requirements": phase1_5_req.data,
        "openspec": phase1_6_openspec.data,
        "architecture": phase1_7_arch.data,
        "readme": phase1_8_readme.data,
        "standards": phase1_9_standards.data,
        "audit": phase1_10_audit.data,
        "errors": errors,
    }

    if not phase1_git.data.get("is_git_repo", False):
        return snapshot, EXIT_HARD_PRECONDITION

    exit_code = EXIT_SCAN_PARTIAL if errors else EXIT_OK
    return snapshot, exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="state-scanner scan.py",
        description="Collect state-scanner Phase 0+1 data as JSON snapshot.",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Project root to scan (default: cwd)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write JSON snapshot to this path (default: stdout only)",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("STATE_SCANNER_LOG_LEVEL", "WARNING"),
        help="Python logging level (default: WARNING)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.WARNING),
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    try:
        snapshot, exit_code = build_snapshot(args.project_root.resolve())
    except Exception:  # noqa: BLE001 — top-level guard
        log.exception("uncaught collector error")
        return EXIT_INTERNAL_BUG

    rendered = json.dumps(snapshot, indent=2, ensure_ascii=False, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())

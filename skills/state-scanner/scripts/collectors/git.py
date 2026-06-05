"""Phase 1 — Git state collector."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ._common import CollectorResult, _run

_COMMIT_LINE = re.compile(r"^([0-9a-f]{7,40})\s+(.*)$")


def _current_branch(project_root: Path, timeout: int = 5) -> str | None:
    """Return the checked-out branch name, or None when detached / on non-branch.

    T3.6 consolidation (4-agent audit consensus): added optional `timeout` for
    collectors with their own budget (e.g. multi_remote.py's ls-remote path).
    Default preserves the pre-T3.6 behavior.
    """
    rc, out, _ = _run(["git", "branch", "--show-current"], project_root, timeout=timeout)
    if rc != 0:
        return None
    branch = out.strip()
    return branch or None


def _is_shallow(project_root: Path, timeout: int = 5) -> bool:
    """Return True if the repo is a shallow clone. T3.6: optional timeout."""
    rc, out, _ = _run(
        ["git", "rev-parse", "--is-shallow-repository"], project_root, timeout=timeout
    )
    return rc == 0 and out.strip() == "true"


_SUBMODULE_PATH_PAT = re.compile(r"^submodule\..+\.path\s+(.+)$")


def _enumerate_submodule_paths(
    project_root: Path, timeout: int = 5, r: CollectorResult | None = None
) -> list[str]:
    """Return submodule paths from `.gitmodules` (initialized or not).

    T3.6 consolidation (TL-I2 / BA-M1 / QA-I5 / CR-I1): single source of truth
    for submodule enumeration. Fails soft — missing `.gitmodules` or parse
    failure yields `[]`. Passing a CollectorResult lets callers surface the
    parse failure as a soft_error without changing the return contract.
    """
    gitmodules = project_root / ".gitmodules"
    if not gitmodules.exists():
        return []
    rc, out, _err = _run(
        ["git", "config", "-f", ".gitmodules", "--get-regexp", r"^submodule\..+\.path$"],
        project_root,
        timeout=timeout,
    )
    if rc != 0:
        if r is not None:
            r.soft_error("gitmodules_parse_failed", f"rc={rc}")
        return []
    paths: list[str] = []
    for line in out.splitlines():
        m = _SUBMODULE_PATH_PAT.match(line.strip())
        if m:
            path = m.group(1).strip()
            if path:
                paths.append(path)
    return paths


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
        if len(entry) < 4:
            i += 1
            continue
        xy = entry[:2]
        path = entry[3:]
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
        # R2-N2: shallow repos cannot compute ahead/behind; configured=False keeps bool contract.
        return {
            "configured": False,
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

    rc, out, _err = _run(
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


def _resolve_git_dir(project_root: Path, timeout: int = 5) -> Path | None:
    """Return the resolved git dir Path, or None on failure.

    `git rev-parse --git-dir` returns a RELATIVE path (`.git`) in a normal
    superproject checkout but an ABSOLUTE path for linked worktrees / submodules
    (gitfile indirection, e.g. `/repo/.git/worktrees/<name>`). We MUST resolve
    relative output against `project_root` rather than the process CWD, else
    marker detection silently misfires when CWD != project_root.
    """
    rc, out, _ = _run(["git", "rev-parse", "--git-dir"], project_root, timeout=timeout)
    if rc != 0:
        return None
    raw = out.strip()
    if not raw:
        return None
    p = Path(raw)
    return p if p.is_absolute() else (project_root / p)


def _rebase_detail(git_dir: Path) -> str | None:
    """Best-effort rebase descriptor (head-name / onto). None on any failure."""
    for sub in ("rebase-merge", "rebase-apply"):
        d = git_dir / sub
        if d.is_dir():
            try:
                head_name = None
                onto = None
                if (d / "head-name").exists():
                    head_name = (d / "head-name").read_text(encoding="utf-8").strip()
                if (d / "onto").exists():
                    onto = (d / "onto").read_text(encoding="utf-8").strip()
                parts = [p for p in (head_name, f"onto {onto}" if onto else None) if p]
                return "; ".join(parts) if parts else None
            except OSError:
                return None
    return None


def _has_unmerged(
    project_root: Path, r: CollectorResult | None = None, timeout: int = 5
) -> bool:
    """True if the index has unmerged (conflicted) paths.

    rc != 0 falls back to False (safe direction: don't escalate wording) but
    emits a soft_error — this only runs after an operation was confirmed, so a
    git failure here is an anomaly worth surfacing rather than swallowing.
    """
    rc, out, _ = _run(
        ["git", "diff", "--diff-filter=U", "--name-only"], project_root, timeout=timeout
    )
    if rc != 0:
        if r is not None:
            r.soft_error("unmerged_probe_failed", f"rc={rc}")
        return False
    return bool(out.strip())


def _detect_git_operation(
    project_root: Path, r: CollectorResult | None = None, timeout: int = 5
) -> dict[str, Any]:
    """Detect an in-progress git operation via `$GIT_DIR/` marker files.

    Output shape:
      {
        "operation": "none" | "rebase" | "merge" | "cherry_pick" | "revert" | "bisect",
        "has_conflicts": bool,   # only computed when operation != "none" (OQ4 conditional eval)
        "detail": str | null     # best-effort rebase head-name/onto
      }

    Priority (multi-marker = anomalous mid-state): rebase > merge > cherry_pick
    > revert > bisect. Fail-soft: git-dir resolution failure or a read error
    yields operation "none" (+ soft_error when `r` is provided), never raising
    and never blocking the rest of git collection.

    Aria #135: the interrupt collector only reads `.aria/workflow-state.json`
    and `detached_head` stays False during a paused rebase (branch name still
    resolves), so a suspended git operation was reported as `interrupt:none`.
    """
    none_result = {"operation": "none", "has_conflicts": False, "detail": None}
    git_dir = _resolve_git_dir(project_root, timeout=timeout)
    if git_dir is None:
        if r is not None:
            r.soft_error("git_dir_unresolved", "git rev-parse --git-dir failed")
        return dict(none_result)

    try:
        operation: str | None = None
        detail: str | None = None
        if (git_dir / "rebase-merge").is_dir() or (git_dir / "rebase-apply").is_dir():
            operation = "rebase"
            detail = _rebase_detail(git_dir)
        elif (git_dir / "MERGE_HEAD").exists():
            operation = "merge"
        elif (git_dir / "CHERRY_PICK_HEAD").exists():
            operation = "cherry_pick"
        elif (git_dir / "REVERT_HEAD").exists():
            operation = "revert"
        elif (git_dir / "BISECT_LOG").exists():
            operation = "bisect"
    except OSError as e:
        if r is not None:
            r.soft_error("git_operation_probe_failed", str(e))
        return dict(none_result)

    if operation is None:
        return dict(none_result)

    return {
        "operation": operation,
        "has_conflicts": _has_unmerged(project_root, r, timeout=timeout),
        "detail": detail,
    }


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
        "status_clean": bool,    # derived: staged_files == [] and unstaged_files == []
                                  # untracked files do NOT count (per state-scanner-inter-cycle-surfacing TX.0)
        "upstream": {
          "configured": bool,
          "name": str | null,
          "ahead": int | null,
          "behind": int | null,
          "reason": str | null
        },
        "recent_commits": [{"sha": str, "subject": str}, ...],
        "shallow": bool,
        "git_operation_in_progress": {           # Aria #135, additive (v1.39.0+)
          "operation": "none" | "rebase" | "merge" | "cherry_pick" | "revert" | "bisect",
          "has_conflicts": bool,                 # only computed when operation != "none"
          "detail": str | null                   # best-effort rebase head-name/onto
        }
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
    # Aria #135: surface in-progress git operations (rebase/merge/...) that
    # detached_head + workflow-state.json both miss. Additive, fail-soft.
    data["git_operation_in_progress"] = _detect_git_operation(project_root, r)

    rc, out, err = _run(["git", "status", "--porcelain=v1", "-z"], project_root)
    if rc != 0:
        r.soft_error("git_status_failed", err.strip())
        data.update(
            staged_files=[], unstaged_files=[], untracked_files=[], uncommitted_count=0
        )
        # Fail-soft: when status read fails, treat as not-clean (conservative).
        data["status_clean"] = False
    else:
        staged, unstaged, untracked = _parse_porcelain_z(out)
        data["staged_files"] = staged
        data["unstaged_files"] = unstaged
        data["untracked_files"] = untracked
        # R1-I4: dedupe by path so MM entries count once.
        unique_paths = set(staged) | set(unstaged) | set(untracked)
        data["uncommitted_count"] = len(unique_paths)
        # Derived field (state-scanner-inter-cycle-surfacing TX.0):
        # status_clean = no staged AND no unstaged. Untracked excluded by design
        # (handoff/scratch files commonly left untracked between cycles).
        data["status_clean"] = (not staged) and (not unstaged)

    data["upstream"] = _collect_upstream(project_root, branch, data["shallow"])
    data["recent_commits"] = _collect_recent_commits(project_root, r)

    r.data = data
    return r

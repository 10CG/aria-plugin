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
          "name": str | null,
          "ahead": int | null,
          "behind": int | null,
          "reason": str | null
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
        # R1-I4: dedupe by path so MM entries count once.
        unique_paths = set(staged) | set(unstaged) | set(untracked)
        data["uncommitted_count"] = len(unique_paths)

    data["upstream"] = _collect_upstream(project_root, branch, data["shallow"])
    data["recent_commits"] = _collect_recent_commits(project_root, r)

    r.data = data
    return r

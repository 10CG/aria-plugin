"""Phase 1.12 — local/remote sync status collector.

Detects the sync state between the local git repository and its remote(s):
- FETCH_HEAD freshness (remote_refs_age)
- Current branch upstream divergence (ahead/behind) with four-state fail-soft
- Per-submodule drift between tree_commit / head_commit / remote_commit

**Critical directional guard** (US-008 root cause, pre_merge Round 1 M1 fix):
  - behind_count > 0 → hint_type="update" (git submodule update --remote)
  - ahead_count  > 0 → hint_type="push"   (push local to origin; do NOT update --remote!)
  - both == 0 but tree_vs_remote=true → hint_type="manual_check"

Never suggesting `update --remote` blindly avoids the data-loss scenario of
overwriting unpushed local commits.

**Scope**: This collector implements single-remote (origin) detection only.
Multi-remote parity belongs to Phase 1.12's T3.3 extension and is intentionally
left as a future hook via `sync_status.multi_remote` (currently `{"enabled": False}`
stub so downstream consumers can detect its absence uniformly).

**Stdlib-only, fail-soft, no network**:
- Only subprocess / pathlib / typing.
- Any git invocation failing sets its field to null + soft_error entry.
- No `git fetch` / `ls-remote`. Remote commit comes from local `refs/remotes/origin/*`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._common import CollectorResult, _run
from .git import _current_branch, _is_shallow


# Remote-commit fallback chain order for submodules
_ORIGIN_HEAD_REFS = [
    "refs/remotes/origin/HEAD",
    "refs/remotes/origin/master",
    "refs/remotes/origin/main",
]


def _has_remote(project_root: Path) -> bool:
    """Return True if `git remote` has any output."""
    rc, out, _ = _run(["git", "remote"], project_root)
    return rc == 0 and bool(out.strip())


def _fetch_head_age(project_root: Path, r: CollectorResult) -> str:
    """Return FETCH_HEAD age in compact form: Nm / Nh / Nd / 'never'.

    Strategy: read .git/FETCH_HEAD mtime (portable, no `stat -c` vs `stat -f` split).
    Bucket: <1h → minutes; <1d → hours; >=1d → days.
    Missing file → 'never'.
    """
    # Resolve .git dir (supports worktrees + submodules via `git rev-parse --git-dir`)
    rc, out, _err = _run(["git", "rev-parse", "--git-dir"], project_root)
    if rc != 0:
        return "never"
    git_dir = (project_root / out.strip()).resolve() if not Path(out.strip()).is_absolute() else Path(out.strip())
    fetch_head = git_dir / "FETCH_HEAD"

    if not fetch_head.exists():
        return "never"

    try:
        mtime = fetch_head.stat().st_mtime
    except OSError as e:
        r.soft_error("fetch_head_stat_failed", str(e))
        return "never"

    import time

    age_sec = max(0, int(time.time() - mtime))
    if age_sec < 3600:
        minutes = max(1, age_sec // 60)
        return f"{minutes}m"
    if age_sec < 86400:
        hours = age_sec // 3600
        return f"{hours}h"
    days = age_sec // 86400
    return f"{days}d"


def _collect_current_branch(
    project_root: Path, branch: str | None, shallow: bool, has_remote: bool, r: CollectorResult
) -> dict[str, Any]:
    """Collect current-branch sync state with four-state fail-soft.

    Four states (Phase 1.12 spec §4):
      - normal:         name=<branch>, upstream=<u>, ahead/behind=int, reason=null
      - shallow_clone:  shallow=true → ahead/behind=null, reason="shallow_clone"
      - no_upstream:    upstream=null → ahead/behind=null, reason="no_upstream"
      - detached_head:  name=null → ahead/behind=null, reason="detached_head"
    """
    # Detached HEAD check first — overrides other states
    if branch is None:
        return {
            "name": None,
            "upstream": None,
            "upstream_configured": False,
            "ahead": None,
            "behind": None,
            "diverged": None,
            "reason": "detached_head",
        }

    # Probe upstream name
    upstream: str | None = None
    upstream_configured = False
    if has_remote:
        rc, out, _err = _run(
            ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
            project_root,
        )
        if rc == 0 and out.strip():
            upstream = out.strip()
            upstream_configured = True

    if not upstream_configured:
        return {
            "name": branch,
            "upstream": None,
            "upstream_configured": False,
            "ahead": None,
            "behind": None,
            "diverged": None,
            "reason": "no_upstream",
        }

    # Shallow clone: cannot compute ahead/behind reliably
    if shallow:
        return {
            "name": branch,
            "upstream": upstream,
            "upstream_configured": True,
            "ahead": None,
            "behind": None,
            "diverged": None,
            "reason": "shallow_clone",
        }

    # Normal path: compute ahead/behind via --left-right --count
    rc, out, err = _run(
        ["git", "rev-list", "--left-right", "--count", f"HEAD...{upstream}"],
        project_root,
    )
    if rc != 0:
        r.soft_error("rev_list_failed", err.strip() or f"rc={rc}")
        return {
            "name": branch,
            "upstream": upstream,
            "upstream_configured": True,
            "ahead": None,
            "behind": None,
            "diverged": None,
            "reason": "rev_list_failed",
        }
    parts = out.strip().split()
    if len(parts) != 2:
        r.soft_error("rev_list_parse_failed", f"unexpected output: {out!r}")
        return {
            "name": branch,
            "upstream": upstream,
            "upstream_configured": True,
            "ahead": None,
            "behind": None,
            "diverged": None,
            "reason": "parse_failed",
        }

    try:
        ahead = int(parts[0])
        behind = int(parts[1])
    except ValueError:
        r.soft_error("rev_list_parse_failed", f"non-integer counts: {out!r}")
        return {
            "name": branch,
            "upstream": upstream,
            "upstream_configured": True,
            "ahead": None,
            "behind": None,
            "diverged": None,
            "reason": "parse_failed",
        }

    diverged = ahead > 0 and behind > 0
    return {
        "name": branch,
        "upstream": upstream,
        "upstream_configured": True,
        "ahead": ahead,
        "behind": behind,
        "diverged": diverged,
        "reason": None,
    }


def _enumerate_submodule_paths(project_root: Path, r: CollectorResult) -> list[str]:
    """Return submodule paths from .gitmodules (initialized or not).

    Uses `git config -f .gitmodules --get-regexp path` for robust parsing.
    Returns [] if no .gitmodules or parsing fails (fail-soft).
    """
    gitmodules = project_root / ".gitmodules"
    if not gitmodules.exists():
        return []

    rc, out, err = _run(
        ["git", "config", "-f", ".gitmodules", "--get-regexp", r"^submodule\..+\.path$"],
        project_root,
    )
    if rc != 0:
        r.soft_error("submodule_enum_failed", err.strip() or f"rc={rc}")
        return []

    paths: list[str] = []
    for line in out.splitlines():
        # Line form: `submodule.<name>.path <path>`
        parts = line.strip().split(None, 1)
        if len(parts) == 2:
            paths.append(parts[1])
    return paths


def _collect_submodule_entry(
    project_root: Path, path: str, r: CollectorResult
) -> dict[str, Any]:
    """Collect one submodule's sync state.

    Returns entry with drift hints. Fail-soft: missing submodule dir / uninitialized
    submodule → tree_commit captured, head_commit/remote_commit may be null.
    """
    entry: dict[str, Any] = {
        "path": path,
        "tree_commit": None,
        "head_commit": None,
        "remote_commit": None,
        "remote_commit_source": "unavailable",
        "drift": {
            "workdir_vs_tree": False,
            "tree_vs_remote": False,
            "behind_count": None,
            "ahead_count": None,
            "hint": None,
            "hint_type": None,
        },
    }

    # 1. tree_commit via ls-tree HEAD
    rc, out, err = _run(["git", "ls-tree", "HEAD", "--", path], project_root)
    if rc == 0 and out.strip():
        # Format: <mode> <type> <sha>\t<path>
        tok = out.split()
        if len(tok) >= 3:
            entry["tree_commit"] = tok[2][:40]
    else:
        r.soft_error(
            "submodule_ls_tree_failed",
            f"path={path} err={err.strip() or f'rc={rc}'}",
        )

    # 2. head_commit via inner `git rev-parse HEAD`
    sub_dir = project_root / path
    if sub_dir.exists():
        rc2, out2, err2 = _run(["git", "rev-parse", "HEAD"], sub_dir)
        if rc2 == 0 and out2.strip():
            entry["head_commit"] = out2.strip()[:40]
        else:
            r.soft_error(
                "submodule_head_failed",
                f"path={path} err={err2.strip() or f'rc={rc2}'}",
            )
    # else: not checked out — head_commit stays null (uninitialized submodule)

    # 3. remote_commit via local origin refs (fallback chain)
    if sub_dir.exists():
        for ref in _ORIGIN_HEAD_REFS:
            rc3, out3, _e = _run(["git", "rev-parse", ref], sub_dir)
            if rc3 == 0 and out3.strip():
                entry["remote_commit"] = out3.strip()[:40]
                entry["remote_commit_source"] = "local_ref"
                break

    # 4. Compute drift fields
    tree_commit = entry["tree_commit"]
    head_commit = entry["head_commit"]
    remote_commit = entry["remote_commit"]

    # workdir_vs_tree: working-copy HEAD differs from supermodule's record
    if tree_commit and head_commit and tree_commit != head_commit:
        entry["drift"]["workdir_vs_tree"] = True

    # BA-I1 fix (post_implementation audit R1): emit explicit zeros when
    # tree == remote (aligned) so consumers can distinguish "confirmed 0 drift"
    # from "unable to measure" (the latter keeps null via fail-soft paths).
    # SKILL.md §1.12 declares behind_count/ahead_count as `int | null`; null
    # should mean "measurement unavailable", not "zero".
    if tree_commit and remote_commit and tree_commit == remote_commit:
        entry["drift"]["behind_count"] = 0
        entry["drift"]["ahead_count"] = 0

    # tree_vs_remote + directional counts
    if tree_commit and remote_commit and tree_commit != remote_commit and sub_dir.exists():
        entry["drift"]["tree_vs_remote"] = True

        # behind_count: commits in remote that tree lacks (tree..remote)
        rc_b, out_b, _eb = _run(
            ["git", "rev-list", "--count", f"{tree_commit}..{remote_commit}"],
            sub_dir,
        )
        behind_count: int | None = None
        if rc_b == 0 and out_b.strip().isdigit():
            behind_count = int(out_b.strip())
        else:
            r.soft_error(
                "submodule_behind_count_failed",
                f"path={path} tree={tree_commit} remote={remote_commit}",
            )

        # ahead_count: commits in tree that remote lacks (remote..tree)
        rc_a, out_a, _ea = _run(
            ["git", "rev-list", "--count", f"{remote_commit}..{tree_commit}"],
            sub_dir,
        )
        ahead_count: int | None = None
        if rc_a == 0 and out_a.strip().isdigit():
            ahead_count = int(out_a.strip())
        else:
            r.soft_error(
                "submodule_ahead_count_failed",
                f"path={path} remote={remote_commit} tree={tree_commit}",
            )

        entry["drift"]["behind_count"] = behind_count
        entry["drift"]["ahead_count"] = ahead_count

        # Directional guard — THE critical Phase 1.12 design decision
        # behind > 0 → safe to `update --remote`
        # ahead  > 0 → must `push` (update --remote would discard local commits)
        # both 0/null but tree_vs_remote true → ambiguous (shallow clone / missing history)
        if behind_count is not None and behind_count > 0:
            entry["drift"]["hint"] = f"git submodule update --remote {path}"
            entry["drift"]["hint_type"] = "update"
        elif ahead_count is not None and ahead_count > 0:
            entry["drift"]["hint"] = (
                f"提示: {path} 本地领先远程 {ahead_count} commits, 在 submodule 中 git push"
            )
            entry["drift"]["hint_type"] = "push"
        else:
            entry["drift"]["hint"] = (
                f"⚠️ {path}: tree_commit 与 remote_commit 不同但无法确定方向 (可能 shallow clone), 请手动检查"
            )
            entry["drift"]["hint_type"] = "manual_check"

    return entry


def collect_sync_state(project_root: Path) -> CollectorResult:
    """Collect Phase 1.12 sync_status snapshot (single-remote scope).

    Output shape (sync_status):
      {
        "remote_refs_age": str,          # "Nm"|"Nh"|"Nd"|"never"
        "has_remote": bool,
        "shallow": bool,
        "current_branch": {
          "name": str | null,
          "upstream": str | null,
          "upstream_configured": bool,
          "ahead": int | null,
          "behind": int | null,
          "diverged": bool | null,
          "reason": str | null,          # "no_upstream"|"shallow_clone"|"detached_head"|"rev_list_failed"|"parse_failed"|null
        },
        "submodules": [
          { "path": str,
            "tree_commit": str | null,
            "head_commit": str | null,
            "remote_commit": str | null,
            "remote_commit_source": str,  # "local_ref"|"unavailable"
            "drift": {
              "workdir_vs_tree": bool,
              "tree_vs_remote": bool,
              "behind_count": int | null,
              "ahead_count": int | null,
              "hint": str | null,
              "hint_type": str | null,    # "update"|"push"|"manual_check"|null
            }
          }
        ],
        "multi_remote": {"enabled": false}   # T3.3 extension point
      }
    """
    r = CollectorResult()

    # Precondition: must be inside a git worktree; otherwise return minimal default
    rc, _out, _err = _run(["git", "rev-parse", "--is-inside-work-tree"], project_root)
    if rc != 0:
        r.soft_error("not_a_git_repo", f"rc={rc}")
        r.data = {
            "remote_refs_age": "never",
            "has_remote": False,
            "shallow": False,
            "current_branch": {
                "name": None,
                "upstream": None,
                "upstream_configured": False,
                "ahead": None,
                "behind": None,
                "diverged": None,
                "reason": "not_a_git_repo",
            },
            "submodules": [],
            "multi_remote": {"enabled": False},
        }
        return r

    has_remote = _has_remote(project_root)
    shallow = _is_shallow(project_root)
    branch = _current_branch(project_root)
    remote_refs_age = _fetch_head_age(project_root, r)

    current_branch = _collect_current_branch(project_root, branch, shallow, has_remote, r)

    submodules: list[dict[str, Any]] = []
    for sub_path in _enumerate_submodule_paths(project_root, r):
        submodules.append(_collect_submodule_entry(project_root, sub_path, r))

    r.data = {
        "remote_refs_age": remote_refs_age,
        "has_remote": has_remote,
        "shallow": shallow,
        "current_branch": current_branch,
        "submodules": submodules,
        "multi_remote": {"enabled": False},  # T3.3 extension point
    }
    return r

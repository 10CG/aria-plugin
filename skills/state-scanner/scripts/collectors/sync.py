"""Phase 1.12 — local/remote sync status collector.

Detects the sync state between the local git repository and its remote(s):
- FETCH_HEAD freshness (remote_refs_age) — **DEPRECATED** (F9′ 8.4, main spec
  state-scanner-stale-refs-false-parity): Phase 0.5 `remote_refresh` (F3′) now
  runs its own fetches BEFORE this collector, rewriting `.git/FETCH_HEAD` every
  scan — so this field degenerates to "how long ago did *this same scan's own
  fetch* happen", never a real staleness signal. Field is KEPT (not removed,
  backward-compat for existing consumers) but callers should read
  `sync_status.multi_remote.*.remotes[].evidence_grade` instead (the real F1′/
  F3′/F4′-joined freshness SOT — see multi_remote.py).
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

import json

from pathlib import Path
from typing import Any

from ._common import CollectorResult, _run, classify_git_error, log, scan_now
from .git import _current_branch, _enumerate_submodule_paths, _is_shallow


# Remote-commit fallback chain order for submodules
_ORIGIN_HEAD_REFS = [
    "refs/remotes/origin/HEAD",
    "refs/remotes/origin/master",
    "refs/remotes/origin/main",
]


def _multi_remote_enabled_in_config(project_root: Path) -> bool:
    """Read `.aria/config.json` → `state_scanner.multi_remote.enabled`, defaulting
    to `True` (mirrors `multi_remote._load_config`'s own default — missing file /
    missing block / malformed JSON all fall back to "enabled"). Duplicated (not
    imported) deliberately: this collector's module docstring commits to staying
    network/import-light and this is a one-line, fail-soft read, not worth a
    cross-module coupling for a single Phase-2 review-driven runtime assertion
    (see `collect_sync_state`'s `multi_remote_data is None` warning below).
    """
    cfg_path = project_root / ".aria" / "config.json"
    if not cfg_path.exists():
        return True
    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return True
    ss = raw.get("state_scanner") or {}
    mr = ss.get("multi_remote") or {}
    return mr.get("enabled", True) is not False


def _has_remote(project_root: Path) -> bool:
    """Return True if `git remote` has any output."""
    rc, out, _ = _run(["git", "remote"], project_root)
    return rc == 0 and bool(out.strip())


def _fetch_head_age(project_root: Path, r: CollectorResult) -> str:
    """Return FETCH_HEAD age in compact form: Nm / Nh / Nd / 'never'.

    **DEPRECATED** (F9′ 8.4) — see module docstring. Kept for the
    `remote_refs_age` field's backward-compat, but since Phase 0.5
    `remote_refresh` fetches (and rewrites FETCH_HEAD) before this collector
    runs, the value is now near-constantly "1m" post-scan and carries no
    staleness signal. Use `evidence_grade` (multi_remote.py) instead.

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

    # 9.7 wall-clock face: "now" is scan_now() (honors ARIA_SCAN_NOW), never the
    # real system clock — otherwise this age bucket can tick a minute boundary
    # between two offline-frozen scans that never touch FETCH_HEAD (remote_refresh
    # skips the fetch entirely offline), breaking the stability-freeze invariant.
    age_sec = max(0, int(scan_now().timestamp() - mtime))
    if age_sec < 3600:
        minutes = max(1, age_sec // 60)
        return f"{minutes}m"
    if age_sec < 86400:
        hours = age_sec // 3600
        return f"{hours}h"
    days = age_sec // 86400
    return f"{days}d"


def _upstream_evidence_grade(
    upstream: str | None, remote_entries: list[dict[str, Any]] | None
) -> str:
    """F9′ 8.1 — join `current_branch.upstream` to its `multi_remote.main_repo.remotes[]`
    entry's `evidence_grade` (D20, F1′/F3′/F4′ freshness SOT).

    `remote_entries` is the MAIN repo's `remotes[]` list (from `collect_multi_remote`'s
    `main_repo` block) — the caller (`collect_sync_state`) is responsible for passing
    the right slice; this helper never re-scopes by path.

    Remote-name extraction: `upstream` has shape `"<remote>/<branch...>"`. Git remote
    NAMES never contain `/` (git itself forbids it), so `upstream.partition("/")[0]`
    always yields the correct remote name regardless of how many `/` the BRANCH name
    itself contains (e.g. `"origin/feature/sub/branch"` → `"origin"`, not truncated
    early) — no need for the heavier `git config branch.<b>.remote` lookup.

    Fail-CLOSED default `"expired"` covers: `upstream is None` (detached_head /
    no_upstream paths), `remote_entries is None` (caller didn't pass `multi_remote_data`
    — F9′ back-compat default), and "no entry named that remote" (multi_remote disabled,
    or the remote isn't one multi_remote enumerated). Zero evidence must never resolve
    to `"fresh"`.
    """
    if not upstream or not remote_entries:
        return "expired"
    remote_name = upstream.partition("/")[0]
    for entry in remote_entries:
        if entry.get("name") == remote_name:
            grade = entry.get("evidence_grade")
            return grade if isinstance(grade, str) else "expired"
    return "expired"


def _collect_current_branch(
    project_root: Path,
    branch: str | None,
    shallow: bool,
    has_remote: bool,
    r: CollectorResult,
    remote_entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Collect current-branch sync state with four-state fail-soft.

    Four states (Phase 1.12 spec §4):
      - normal:         name=<branch>, upstream=<u>, ahead/behind=int, reason=null
      - shallow_clone:  shallow=true → ahead/behind=null, reason="shallow_clone"
      - no_upstream:    upstream=null → ahead/behind=null, reason="no_upstream"
      - detached_head:  name=null → ahead/behind=null, reason="detached_head"

    F9′ 8.1 (main spec state-scanner-stale-refs-false-parity, additive): every return
    also carries `evidence_grade` (D20), joined from `remote_entries` (the caller's
    `multi_remote.main_repo.remotes[]` slice) via `_upstream_evidence_grade`. This is
    PURELY additive — the US-008 directional guard below (behind/ahead/diverged
    computation) is untouched byte-for-byte; `evidence_grade` never gates or rewrites
    `ahead`/`behind`/`reason` here (unlike `multi_remote._apply_freshness_downgrade`,
    which DOES rewrite `parity` — that rewrite stays scoped to the `multi_remote` block
    and is deliberately NOT mirrored onto `sync_status.current_branch`, which keeps its
    own local-git-only measurement semantics per this collector's module docstring).
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
            "evidence_grade": _upstream_evidence_grade(None, remote_entries),
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
            "evidence_grade": _upstream_evidence_grade(None, remote_entries),
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
            "evidence_grade": _upstream_evidence_grade(upstream, remote_entries),
        }

    # Normal path: compute ahead/behind via --left-right --count
    rc, out, err = _run(
        ["git", "rev-list", "--left-right", "--count", f"HEAD...{upstream}"],
        project_root,
    )
    if rc != 0:
        cls = classify_git_error(rc, err, "git rev-list")
        r.soft_error("rev_list_failed", f"git rev-list {cls.label} (rc={cls.rc})")
        return {
            "name": branch,
            "upstream": upstream,
            "upstream_configured": True,
            "ahead": None,
            "behind": None,
            "diverged": None,
            "reason": "rev_list_failed",
            "evidence_grade": _upstream_evidence_grade(upstream, remote_entries),
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
            "evidence_grade": _upstream_evidence_grade(upstream, remote_entries),
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
            "evidence_grade": _upstream_evidence_grade(upstream, remote_entries),
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
        "evidence_grade": _upstream_evidence_grade(upstream, remote_entries),
    }


def _submodule_evidence_grade(remote_entries: list[dict[str, Any]] | None) -> str:
    """F9′ 8.1 — join a submodule's `drift` block to its `multi_remote` submodule
    block's "origin" remote entry's `evidence_grade`.

    Why "origin" specifically (not "first entry" / not all entries merged): this
    module's `remote_commit` fallback chain (`_ORIGIN_HEAD_REFS`, module-top constant)
    is origin-only by construction — `entry["remote_commit"]` here NEVER reflects any
    other remote, so joining a non-origin remote's freshness would attach a freshness
    grade to a measurement that remote never produced. `remote_entries` is the
    caller-supplied slice of THIS submodule's `multi_remote.submodules[].remotes[]`
    (never the main repo's — a bare "origin" name collision across repos is exactly
    the top_risks trap `multi_remote._remote_refresh_leg_key` already guards against
    by keying on `(repo_path, remote_name)`, not `remote_name` alone; this helper
    relies on the CALLER having already scoped `remote_entries` to the right repo).

    Fail-CLOSED default `"expired"`: `remote_entries is None` (F9′ back-compat —
    caller didn't pass `multi_remote_data`) or no "origin" entry present (multi_remote
    disabled / origin not enumerated) both mean zero evidence, never "fresh".
    """
    if not remote_entries:
        return "expired"
    for entry in remote_entries:
        if entry.get("name") == "origin":
            grade = entry.get("evidence_grade")
            return grade if isinstance(grade, str) else "expired"
    return "expired"


def _collect_submodule_entry(
    project_root: Path,
    path: str,
    r: CollectorResult,
    remote_entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Collect one submodule's sync state.

    Returns entry with drift hints. Fail-soft: missing submodule dir / uninitialized
    submodule → tree_commit captured, head_commit/remote_commit may be null.

    F9′ 8.1 (additive): `entry["drift"]["evidence_grade"]` is joined from
    `remote_entries` (caller's `multi_remote.submodules[path].remotes[]` slice) via
    `_submodule_evidence_grade`, written AFTER the US-008 directional guard below —
    that guard (behind→update / ahead→push / directional_guard) is read-only here,
    unchanged byte-for-byte; `evidence_grade` never influences `hint`/`hint_type`.
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
        cls = classify_git_error(rc, err, "git ls-tree")
        r.soft_error(
            "submodule_ls_tree_failed",
            f"path={path} err={cls.label} (rc={cls.rc})",
        )

    # 2. head_commit via inner `git rev-parse HEAD`
    sub_dir = project_root / path
    if sub_dir.exists():
        rc2, out2, err2 = _run(["git", "rev-parse", "HEAD"], sub_dir)
        if rc2 == 0 and out2.strip():
            entry["head_commit"] = out2.strip()[:40]
        else:
            cls = classify_git_error(rc2, err2, "git rev-parse")
            r.soft_error(
                "submodule_head_failed",
                f"path={path} err={cls.label} (rc={cls.rc})",
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

    # F9′ 8.1 — evidence_grade join, unconditional (fires for every branch above,
    # including the "no drift at all" / "workdir_vs_tree only" paths, not just the
    # tree_vs_remote directional-guard branch) — see docstring.
    entry["drift"]["evidence_grade"] = _submodule_evidence_grade(remote_entries)

    return entry


def collect_sync_state(
    project_root: Path, multi_remote_data: dict[str, Any] | None = None
) -> CollectorResult:
    """Collect Phase 1.12 sync_status snapshot (single-remote scope).

    F9′ (main spec state-scanner-stale-refs-false-parity, OQ-E=(a)) — `multi_remote_data`
    is the ALREADY-COLLECTED `collect_multi_remote(project_root).data` block, passed in
    by the caller. **`scan.py` MUST call `collect_multi_remote` BEFORE `collect_sync_state`
    and pass its `.data` here** — this collector never re-collects or re-fetches
    multi_remote itself (module boundary: this file stays network-free per its own
    top-of-file docstring). `multi_remote_data=None` (the default — back-compat for any
    other caller that hasn't been updated, and the historical/direct-call shape) makes
    every `evidence_grade` resolve to `"expired"` (fail-CLOSED: "caller didn't tell me"
    must never silently mean "fresh") — this is the DIRECTLY OBSERVABLE fingerprint of
    the ordering dependency if it's ever violated (see `_upstream_evidence_grade` /
    `_submodule_evidence_grade` docstrings, and top_risks #3 in the F9′ blueprint).

    Output shape (sync_status):
      {
        "remote_refs_age": str,          # "Nm"|"Nh"|"Nd"|"never" — DEPRECATED (F9′ 8.4),
                                          # see _fetch_head_age docstring; use
                                          # multi_remote.*.remotes[].evidence_grade instead
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
          "evidence_grade": str,         # "fresh"|"stale_unverified"|"expired" — F9′ 8.1, joined from multi_remote
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
              "evidence_grade": str,      # "fresh"|"stale_unverified"|"expired" — F9′ 8.1, joined from multi_remote (origin leg)
            }
          }
        ],
        "multi_remote": {"enabled": false}   # T3.3 extension point; overwritten by scan.py
      }
    """
    r = CollectorResult()

    # Phase 2 review Minor (b) — scan.py 换序运行时断言: if the caller omitted
    # `multi_remote_data` while config says multi_remote is enabled, every
    # `evidence_grade` below silently degrades to "expired" (see docstring above)
    # with NO observable signal other than re-reading this whole function's
    # source — a caller who reorders `collect_multi_remote`/`collect_sync_state`
    # in scan.py (or forgets to pass `.data`) gets a silent freshness downgrade,
    # not an error. Promote it from grep-only to log-observable. Best-effort:
    # config read failures never raise here (see `_multi_remote_enabled_in_config`
    # fail-soft default), and this never changes `r.data` — advisory only.
    if multi_remote_data is None and _multi_remote_enabled_in_config(project_root):
        log.warning(
            "collect_sync_state: multi_remote_data is None but "
            "state_scanner.multi_remote.enabled is not false — evidence_grade "
            "will resolve to 'expired' for all fields. Caller should collect "
            "multi_remote FIRST and pass its .data (see module docstring)."
        )

    # F9′ 8.1 — pre-parse the caller-supplied multi_remote block into the two slices
    # `_collect_current_branch`/`_collect_submodule_entry` need. Any shape surprise
    # (disabled / missing / malformed) degrades to `None` per-slice → downstream
    # `evidence_grade` resolves "expired" via the helpers' own fail-CLOSED default;
    # never raises.
    main_repo_remotes: list[dict[str, Any]] | None = None
    submodules_by_path: dict[str, list[dict[str, Any]]] = {}
    if isinstance(multi_remote_data, dict) and multi_remote_data.get("enabled"):
        main_repo = multi_remote_data.get("main_repo")
        if isinstance(main_repo, dict):
            remotes = main_repo.get("remotes")
            if isinstance(remotes, list):
                main_repo_remotes = remotes
        for sm in multi_remote_data.get("submodules") or []:
            if isinstance(sm, dict) and isinstance(sm.get("path"), str):
                remotes = sm.get("remotes")
                if isinstance(remotes, list):
                    submodules_by_path[sm["path"]] = remotes

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
                "evidence_grade": "expired",
            },
            "submodules": [],
            "multi_remote": {"enabled": False},
        }
        return r

    has_remote = _has_remote(project_root)
    shallow = _is_shallow(project_root)
    branch = _current_branch(project_root)
    remote_refs_age = _fetch_head_age(project_root, r)

    current_branch = _collect_current_branch(
        project_root, branch, shallow, has_remote, r, remote_entries=main_repo_remotes
    )

    submodules: list[dict[str, Any]] = []
    for sub_path in _enumerate_submodule_paths(project_root, r=r):
        submodules.append(
            _collect_submodule_entry(
                project_root, sub_path, r, remote_entries=submodules_by_path.get(sub_path)
            )
        )

    r.data = {
        "remote_refs_age": remote_refs_age,
        "has_remote": has_remote,
        "shallow": shallow,
        "current_branch": current_branch,
        "submodules": submodules,
        "multi_remote": {"enabled": False},  # T3.3 extension point
    }
    return r

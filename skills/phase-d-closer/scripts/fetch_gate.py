#!/usr/bin/env python3
"""Phase D.1 fetch-gate — 切口1 (concurrent-session-upm-safety #133, TASK-006).

Fail-soft advisory check run *before* phase-d-closer D.1 writes the UPM /
progress doc.  Surfaces "origin moved ahead and the incoming commits touch the
UPM file (or there is a known cross-track collision)" so the AI can fetch+rebase
the shared doc BEFORE editing it — avoiding the write-time merge thrash that
advisory-at-scan-time cannot prevent (#133 Problem-1, audit C1).

Design constraints (proposal §3 / AC-1 / DEC-20260519-001):
  - FAIL-SOFT, never blocks: any git failure → soft-warn, verdict stays non-blocking.
    This is NOT the C.2.4.5 fail-hard pre-merge gate.
  - CREDENTIAL-SAFE: fetch failures are classified to a stable non-secret enum
    (network|auth_403|non_ff|git_missing|other); raw stderr is NEVER echoed
    (remote URLs may embed tokens).  R1 I7.
  - ADVISORY-ONLY: returns a verdict for the caller to surface; does not write,
    does not lock, does not auto-enable anything.

Pattern provenance (replicated, NOT imported — R1 I1/I2):
  - default-branch resolve: symbolic-ref → fallback, mirrors
    state-scanner sync.py::_resolve_default_branch (module-private, other skill).
  - ahead/behind: ``git rev-list --left-right --count`` form, mirrors
    state-scanner git.py — but the original locks ``@{upstream}``; 切口1 needs
    ``HEAD...origin/<default>``, so the command form is replicated, not called.
  - error classification: mirrors state-scanner coordination_fetch.py::_classify_error
    (non-secret enum) so callers can surface a kind without leaking credentials.

Public API:
    run_fetch_gate(project_root, *, collision_kind="none",
                   upm_source_file=None, timeout=30, _runner=None) -> dict

Verdict mapping (proposal §3 / tasks 5.3):
    fetch failed                                  → verdict "silent" + warning (fail-soft)
    behind == 0                                   → "silent"
    behind  > 0 AND upm_source_file touched       → "strong"   (incoming commits hit UPM)
    behind  > 0 AND collision_kind != "none"      → "advisory" (known cross-track churn)
    behind  > 0 AND neither                       → "silent"   (pure behind → no prompt fatigue)

Spec:  openspec/changes/concurrent-session-upm-safety/ (TASK-006, 切口1)
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Optional

# Default-branch resolution candidates (priority order). Mirrors
# state-scanner sync.py::_ORIGIN_HEAD_REFS + _DEFAULT_BRANCH_FALLBACKS.
_ORIGIN_HEAD_REFS = (
    "refs/remotes/origin/HEAD",
    "refs/remotes/origin/master",
    "refs/remotes/origin/main",
)
_DEFAULT_BRANCH_FALLBACKS = ("master", "main")

_FETCH_TIMEOUT_DEFAULT = 30  # seconds (proposal §3: independent of scan 1.16 cache)
_GIT_QUICK_TIMEOUT = 5       # seconds for cheap local ref ops


# ---------------------------------------------------------------------------
# git runner (injectable for tests)
# ---------------------------------------------------------------------------

def _default_runner(args: list[str], cwd: Path, timeout: int) -> tuple[int, str, str]:
    """Run ``git <args>`` returning (rc, stdout, stderr); never raises."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timed out"
    except (OSError, ValueError) as exc:  # git missing / bad args
        return 127, "", str(exc)


# ---------------------------------------------------------------------------
# Credential-safe error classification (mirrors coordination_fetch._classify_error)
# ---------------------------------------------------------------------------

def _classify_error(rc: int, stderr: str) -> str:
    """Map a failed git op to a stable, NON-SECRET error_kind enum.

    Raw stderr is intentionally never returned — remote URLs in stderr may embed
    credentials.  Returns: network | auth_403 | non_ff | git_missing | other.
    """
    s = (stderr or "").lower()
    if "could not resolve host" in s or "timed out" in s or "connection" in s:
        return "network"
    if "403" in s or "authentication failed" in s or "permission denied" in s:
        return "auth_403"
    if "non-fast-forward" in s or "rejected" in s:
        return "non_ff"
    if "not found" in s or "does not appear to be a git repo" in s:
        return "git_missing"
    return "other"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_default_branch(run, cwd: Path) -> Optional[str]:
    """Resolve the default branch (symbolic-ref → ref probe → name probe → None).

    Mirrors state-scanner sync.py::_resolve_default_branch (replicated to keep
    phase-d-closer self-contained — no cross-skill runtime import).
    """
    rc, out, _ = run(["symbolic-ref", "refs/remotes/origin/HEAD"], cwd, _GIT_QUICK_TIMEOUT)
    if rc == 0 and out.strip():
        ref = out.strip()
        prefix = "refs/remotes/origin/"
        if ref.startswith(prefix):
            return ref[len(prefix):]
    for ref in _ORIGIN_HEAD_REFS:
        rc, _, _ = run(["show-ref", "--verify", "--quiet", ref], cwd, _GIT_QUICK_TIMEOUT)
        if rc == 0:
            return ref.rsplit("/", 1)[-1]
    for name in _DEFAULT_BRANCH_FALLBACKS:
        rc, _, _ = run(["show-ref", "--verify", "--quiet", f"refs/heads/{name}"], cwd, _GIT_QUICK_TIMEOUT)
        if rc == 0:
            return name
    return None


def _behind_count(run, cwd: Path, default_branch: str) -> Optional[int]:
    """Return how many commits HEAD is behind origin/<default_branch>; None on failure.

    Uses ``git rev-list --left-right --count HEAD...origin/<def>`` (left = ahead,
    right = behind).  Mirrors state-scanner git.py form but targets origin/<def>
    rather than @{upstream}.
    """
    ref = f"origin/{default_branch}"
    rc, out, _ = run(
        ["rev-list", "--left-right", "--count", f"HEAD...{ref}"], cwd, _GIT_QUICK_TIMEOUT
    )
    if rc != 0:
        return None
    parts = out.split()
    if len(parts) != 2:
        return None
    try:
        return int(parts[1])  # right side = behind
    except ValueError:
        return None


def _upm_touched(run, cwd: Path, default_branch: str, upm_source_file: Optional[str]) -> bool:
    """True if any incoming (behind) commit touched the UPM source file.

    NULL-GUARD (R1 I4): when upm_source_file is None (project has no UPM, e.g.
    Aria itself), there is nothing to touch → return False, skip the check.
    """
    if not upm_source_file:
        return False
    ref = f"origin/{default_branch}"
    rc, out, _ = run(
        ["log", "--name-only", "--format=", f"HEAD..{ref}", "--", upm_source_file],
        cwd, _GIT_QUICK_TIMEOUT,
    )
    if rc != 0:
        return False  # fail-soft: cannot determine → assume not touched
    return bool(out.strip())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_fetch_gate(
    project_root,
    *,
    collision_kind: str = "none",
    upm_source_file: Optional[str] = None,
    timeout: int = _FETCH_TIMEOUT_DEFAULT,
    _runner: Optional[Callable] = None,
) -> dict:
    """Run the D.1 pre-write fetch-gate. Fail-soft, advisory-only, never raises.

    Args:
        project_root:    repo root (str or Path).
        collision_kind:  tracks_multibranch.collision.kind from the snapshot
                         ("none" | "cross_owner" | "self_multi_container").
        upm_source_file: upm.source_file from the snapshot (None when no UPM).
        timeout:         fetch timeout in seconds (default 30).
        _runner:         injectable git runner (rc, out, err) for tests.

    Returns dict:
        verdict:        "silent" | "advisory" | "strong"
        behind:         int | None
        default_branch: str | None
        fetch_ok:       bool
        error_kind:     str | None   (non-secret enum when fetch failed)
        upm_touched:    bool
        warning:        str | None   (fail-soft notice; NEVER contains raw stderr)
        message:        str          (advisory text for the caller to surface)
    """
    run = _runner or _default_runner
    cwd = Path(project_root)

    result = {
        "verdict": "silent",
        "behind": None,
        "default_branch": None,
        "fetch_ok": False,
        "error_kind": None,
        "upm_touched": False,
        "warning": None,
        "message": "",
    }

    default_branch = _resolve_default_branch(run, cwd)
    result["default_branch"] = default_branch
    if not default_branch:
        result["warning"] = "无法解析 default branch (无 origin/HEAD) — 跳过 fetch-gate, 不阻塞"
        return result

    # Fresh fetch (independent of scan 1.16 cache). Fail-soft + credential-safe.
    rc, _out, err = run(["fetch", "origin", default_branch], cwd, timeout)
    if rc != 0:
        kind = _classify_error(rc, err)
        result["error_kind"] = kind
        result["warning"] = (
            f"fetch origin/{default_branch} 失败 (kind={kind}) — 看板可能陈旧, "
            f"不阻塞 D.1 写入"  # NOTE: raw stderr intentionally NOT included (R1 I7)
        )
        return result

    result["fetch_ok"] = True
    behind = _behind_count(run, cwd, default_branch)
    result["behind"] = behind
    if not behind or behind <= 0:
        result["message"] = f"与 origin/{default_branch} 同步 (behind=0) — 安全写 UPM"
        return result

    touched = _upm_touched(run, cwd, default_branch, upm_source_file)
    result["upm_touched"] = touched

    if touched:
        result["verdict"] = "strong"
        result["message"] = (
            f"⚠️ origin/{default_branch} 领先 {behind} commit 且**触及 UPM 文件** "
            f"({upm_source_file}) — 写 UPM 前先 git fetch + rebase, 避免 merge thrash "
            f"(见 concurrent-session-write-safety convention)"
        )
    elif collision_kind != "none":
        result["verdict"] = "advisory"
        result["message"] = (
            f"🔀 origin/{default_branch} 领先 {behind} commit 且存在 collision "
            f"({collision_kind}) — 建议写 UPM 前 fetch + 对账"
        )
    else:
        # Pure behind, no UPM touch, no collision → stay silent (防 prompt fatigue)
        result["verdict"] = "silent"
        result["message"] = (
            f"origin/{default_branch} 领先 {behind} commit (未触及 UPM, 无 collision) — 静默"
        )
    return result

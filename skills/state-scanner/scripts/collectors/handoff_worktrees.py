"""Phase 1.15b — Cross-worktree handoff discovery collector (#139).

When a session handoff is written in a *feature* worktree (branch not yet merged
to main) and the next session starts in the *main* worktree, ``scan.py`` — which
collects against the current working directory — cannot see that handoff. The
new session is then steered into the wrong state (2026-06-04 SilkNode
cut2-batch1 incident).

This collector enumerates every git worktree, resolves each one's latest handoff
doc (reusing ``handoff.py``'s H5 pointer→mtime ``_resolve_latest`` helper),
arbitrates the *global* latest across trees by frontmatter ``updated-at`` (in the
epoch domain), and surfaces when that global latest lives in a worktree OTHER
than the current one — so state-scanner Phase 2 can advise an ``EnterWorktree``.

Design: OpenSpec ``cross-worktree-handoff-discovery`` (#139) + DEC-20260611-002.
Read-only discovery — no writes, no claim/heartbeat (that is Layer L's job;
this collector and Layer L's ``phase1_gate`` are orthogonal — see
``references/layer-l-integration.md``). On a single-worktree project this is a
near-no-op (``others=[]``, ``global_latest_elsewhere=None``).

Field shape (additive top-level ``handoff_worktrees`` key, snapshot schema 1.0 —
additive, no ``snapshot_schema_version`` bump):

- ``enabled``: bool — config ``state_scanner.worktree_scan.enabled`` (default
  True). Distinguishes "config-disabled" from "enumeration failed": both yield
  ``enumerated=False``, but disabled has NO ``worktree_enumeration_failed`` soft
  error while failure does (R2 N-1).
- ``enumerated``: bool — ``git worktree list`` was attempted AND succeeded.
- ``worktree_count``: int — number of reachable, non-bare/non-prunable worktrees
  incl. the current one (0 when not enumerated).
- ``others``: list[dict] — one entry per OTHER worktree that has a resolved
  latest handoff, sorted by ``path`` lexicographically::

      {path, branch, doc, updated_at, status, track_id, cmp_key_source}

  ``cmp_key_source`` ∈ {"frontmatter" (used updated-at), "mtime" (fallback)} —
  named to avoid colliding with ``handoff.latest_source``'s "mtime" semantics.
  A legacy doc (no §2.3.1 frontmatter) aligns with ``handoff_multibranch.py``
  track-dict conventions: ``status='legacy'``, ``track_id`` filename-derived,
  ``updated_at`` = mtime ISO, ``cmp_key_source='mtime'``. The tree-internal
  resolution source (pointer|mtime, i.e. ``latest_source``) is deliberately NOT
  recorded — Phase 2 does not depend on it (additive later if needed; R2 N-7).
- ``global_latest_elsewhere``: None | {path, branch, doc, status, age_hours} —
  non-null ONLY when the cross-tree-arbitrated global latest lives in a tree
  OTHER than the current one. ``status`` is carried verbatim (Phase 2 gates on
  ``status == "active"``; the field stays arbitration-honest regardless of
  status). ``age_hours`` basis = the arbitration key (updated-at epoch, or mtime
  epoch when degraded).

Soft errors (``errors[]`` + snapshot exit code 10):
- ``worktree_enumeration_failed`` — ``git worktree list`` failed (``enumerated``
  stays False).
- ``worktree_unreachable`` — a listed worktree dir is gone/inaccessible (skip
  it, record path).
- ``worktree_scan_cap`` — more OTHER worktrees than the resolved cap (warn-only;
  the current tree is always resolved as the arbitration baseline).
- ``handoff_canonical_scan_failed`` — per-tree ``docs/handoff`` scan failed
  (message prefixed with the worktree path).
- ``handoff_pointer_target_missing`` / ``handoff_stat_failed`` — per-tree
  resolution signals from ``_resolve_latest``, prefixed with the worktree path
  (R2 N-3). The #137 ``handoff_frontmatter_missing`` signal is deliberately NOT
  emitted for other trees (it anchors to the current tree's latest; emitting it
  cross-tree would pollute ``errors[]`` and mis-fire E2 — R2 m-7).
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ._common import (
    CollectorResult,
    _run,
    classify_git_error,
    resolve_max_worktrees_scanned,
)
from .handoff import (
    _ScanError,
    _resolve_latest,
    _scan_md_files,
    parse_handoff_frontmatter,
)


def _read_worktree_scan_enabled(project_root: Path) -> bool:
    """Read ``state_scanner.worktree_scan.enabled``; default True (fail-soft → True).

    Mirrors the fail-soft posture of the other config readers: missing file /
    parse error / key absent → default. Only an explicit ``false`` disables.
    """
    cfg_path = project_root / ".aria" / "config.json"
    if not cfg_path.is_file():
        return True
    try:
        with cfg_path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return True
    val = ((raw.get("state_scanner") or {}).get("worktree_scan") or {}).get("enabled")
    if val is None:
        return True
    return bool(val)


def _parse_updated_at_epoch(value: str) -> Optional[float]:
    """Parse an ISO-8601 ``updated-at`` to epoch seconds; None on failure.

    Compatible with both ``Z`` and ``+HH:MM`` offset forms WITHOUT relying on
    Python 3.11's ``fromisoformat`` ``Z`` support (the plugin sandbox has no
    Python-version floor — R2 N-4/I-3). Naive timestamps are assumed UTC.
    """
    if not value:
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    try:
        return dt.timestamp()
    except (OverflowError, OSError, ValueError):
        return None


def _list_worktrees(project_root: Path) -> tuple[Optional[list[dict]], Optional[str]]:
    """Run ``git worktree list --porcelain``; return (worktrees, error).

    On success ``error`` is None and ``worktrees`` is a list of::

        {"path": str, "branch": str, "bare": bool, "prunable": bool}

    ``branch`` is the short name (``refs/heads/feat/x`` → ``feat/x``) or
    ``"(detached)"`` for a detached HEAD. On git failure returns (None, msg);
    the caller emits ``worktree_enumeration_failed``.
    """
    rc, out, err = _run(["git", "worktree", "list", "--porcelain"], cwd=project_root)
    if rc != 0:
        cls = classify_git_error(rc, err, "git worktree list")
        return None, f"git worktree list {cls.label} (rc={cls.rc})"

    worktrees: list[dict] = []
    cur: dict = {}
    for line in out.splitlines():
        if not line.strip():
            if cur:
                worktrees.append(cur)
                cur = {}
            continue
        if line.startswith("worktree "):
            cur = {
                "path": line[len("worktree "):].strip(),
                "branch": "(detached)",
                "bare": False,
                "prunable": False,
            }
        elif line.startswith("branch "):
            ref = line[len("branch "):].strip()
            cur["branch"] = (
                ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref
            )
        elif line == "bare":
            cur["bare"] = True
        elif line == "detached":
            cur["branch"] = "(detached)"
        elif line.startswith("prunable"):
            cur["prunable"] = True
    if cur:
        worktrees.append(cur)
    return worktrees, None


def _build_entry(
    wt_path: Path,
    latest: Path,
    branch: str,
    mtime_epoch: Optional[float],
    r: CollectorResult,
    is_current: bool,
) -> Optional[dict]:
    """Build one worktree's handoff entry (arbitration key + display metadata).

    Reads the resolved latest doc, parses §2.3.1 frontmatter, and computes the
    cross-tree arbitration key in the epoch domain. Does NOT emit
    ``handoff_frontmatter_missing`` (current-tree-only; R2 m-7). ``mtime_epoch``
    may be passed by the caller (from ``_resolve_latest``) to avoid a second
    stat(); when None it is computed here.
    """
    if mtime_epoch is None:
        try:
            mtime_epoch = latest.stat().st_mtime
        except OSError as e:
            # doc stat race (resolved by 1.15 then deleted before 1.15b re-stat) —
            # use handoff_stat_failed (precise) not worktree_unreachable; fail-soft.
            r.soft_error("handoff_stat_failed", f"{wt_path}: {latest} stat failed: {e}")
            return None
    mtime_iso = datetime.fromtimestamp(mtime_epoch, tz=timezone.utc).isoformat(
        timespec="seconds"
    )

    try:
        content: Optional[str] = latest.read_text(encoding="utf-8", errors="replace")
    except OSError:
        content = None
    fm = parse_handoff_frontmatter(content) if content else None

    if fm is not None:
        status = fm["status"]
        track_id = fm["track-id"]
        updated_at_raw = fm["updated-at"]
        epoch = _parse_updated_at_epoch(updated_at_raw)
        if epoch is not None:
            cmp_key_source = "frontmatter"
            updated_at = updated_at_raw
        else:
            # frontmatter present but updated-at malformed → degrade to mtime
            # for the arbitration key; show the raw value honestly (R2 N-4/I-3).
            cmp_key_source = "mtime"
            epoch = mtime_epoch
            updated_at = updated_at_raw
    else:
        # legacy doc (no/incomplete frontmatter) — align handoff_multibranch.py
        status = "legacy"
        track_id = latest.name
        updated_at = mtime_iso
        epoch = mtime_epoch
        cmp_key_source = "mtime"

    try:
        doc_rel = str(latest.relative_to(wt_path))
    except ValueError:
        doc_rel = latest.name

    return {
        "path": str(wt_path),
        "branch": branch,
        "doc": doc_rel,
        "updated_at": updated_at,
        "status": status,
        "track_id": track_id,
        "cmp_key_source": cmp_key_source,
        # internal-only (stripped before output):
        "epoch": epoch,
        "age_hours": round((time.time() - epoch) / 3600, 2),
        "is_current": is_current,
    }


def _current_tree_entry(
    project_root: Path,
    current_handoff: dict,
    branch: str,
    r: CollectorResult,
) -> Optional[dict]:
    """Build the current tree's entry by CONSUMING Phase 1.15 output (R2 N-6/m-6).

    Reuses ``collect_handoff``'s already-resolved ``latest_path`` (no re-scan,
    no second pointer→mtime resolution), then reads+parses it for the
    arbitration key — the 1.15 dict carries no ``updated-at``/``status``.
    """
    if not current_handoff.get("exists"):
        return None
    latest_rel = current_handoff.get("latest_path")
    if not latest_rel:
        return None  # exists but stat-failed upstream (latest_path None)
    latest = project_root / latest_rel
    return _build_entry(project_root, latest, branch, None, r, is_current=True)


def _resolve_tree_handoff(
    wt_path: Path, branch: str, r: CollectorResult, is_current: bool
) -> Optional[dict]:
    """Scan + resolve one OTHER worktree's latest handoff via the shared helper."""
    if not wt_path.is_dir():
        r.soft_error("worktree_unreachable", f"{wt_path}: worktree directory missing")
        return None
    canonical = wt_path / "docs" / "handoff"
    try:
        files = _scan_md_files(canonical)
    except _ScanError as e:
        r.soft_error("handoff_canonical_scan_failed", f"{wt_path}: {e}")
        return None
    if not files:
        return None
    resolution = _resolve_latest(canonical, files)
    # Per-tree signals, prefixed with the worktree path (R2 N-3).
    for kind, msg in resolution.signals:
        r.soft_error(kind, f"{wt_path}: {msg}")
    if resolution.stat_failed or resolution.latest is None:
        return None
    return _build_entry(
        wt_path, resolution.latest, branch, resolution.mtime_epoch, r, is_current
    )


def _arbitrate(entries: list[dict]) -> Optional[dict]:
    """Pick the global latest across trees; return global_latest_elsewhere or None.

    Max arbitration ``epoch`` wins. Ties: the current tree wins if it is among
    the leaders (no false advisory); otherwise the lexicographically smallest
    ``path`` wins (deterministic, same key as ``others[]`` sort — R2 N-2).
    Returns None when the winner IS the current tree (or no entries).
    """
    if not entries:
        return None
    max_epoch = max(e["epoch"] for e in entries)
    leaders = [e for e in entries if e["epoch"] == max_epoch]
    current_leaders = [e for e in leaders if e["is_current"]]
    if current_leaders:
        winner = current_leaders[0]
    else:
        winner = min(leaders, key=lambda e: e["path"])
    if winner["is_current"]:
        return None
    return {
        "path": winner["path"],
        "branch": winner["branch"],
        "doc": winner["doc"],
        "status": winner["status"],
        "age_hours": winner["age_hours"],
    }


def collect_handoff_worktrees(
    project_root: Path, current_handoff: Optional[dict] = None
) -> CollectorResult:
    """Phase 1.15b — discover handoffs across all git worktrees (#139).

    ``current_handoff`` is the Phase 1.15 ``collect_handoff`` data dict; when
    provided, the current tree's latest is consumed from it instead of being
    re-scanned (R2 N-6/m-6). When omitted (e.g. unit tests calling this collector
    directly), the current tree falls back to a fresh scan.
    """
    r = CollectorResult()

    if not _read_worktree_scan_enabled(project_root):
        r.data = {
            "enabled": False,
            "enumerated": False,
            "worktree_count": 0,
            "others": [],
            "global_latest_elsewhere": None,
        }
        return r

    worktrees, enum_err = _list_worktrees(project_root)
    if worktrees is None:
        r.soft_error("worktree_enumeration_failed", enum_err or "unknown")
        r.data = {
            "enabled": True,
            "enumerated": False,
            "worktree_count": 0,
            "others": [],
            "global_latest_elsewhere": None,
        }
        return r

    cur_resolved = project_root.resolve()
    cap = resolve_max_worktrees_scanned(project_root)

    # Exclude bare/prunable; tag reachability + current-tree (double-sided
    # canonical compare so a symlinked cwd does not mis-classify the current
    # tree as "other" → self-referential advisory — R2 m-8).
    tagged: list[tuple[dict, bool]] = []
    for w in worktrees:
        if w["bare"]:
            continue  # bare worktree has no working tree → silently skip
        if w["prunable"]:
            # working tree gone / gitdir stale (e.g. the dir was rm'd). Surface
            # it (it may have hidden a handoff) but do not attempt to scan it.
            r.soft_error(
                "worktree_unreachable",
                f"{w['path']}: prunable (working tree gone or gitdir stale)",
            )
            continue
        try:
            wt_resolved = Path(w["path"]).resolve()
        except OSError:
            r.soft_error("worktree_unreachable", f"{w['path']}: path resolve failed")
            continue
        tagged.append((w, wt_resolved == cur_resolved))

    worktree_count = len(tagged)

    # Cap applies to OTHER trees only — the current tree is always resolved as
    # the arbitration baseline (R2 N-1: cap never drops the baseline).
    current_tagged = [t for t in tagged if t[1]]
    # Sort other trees by path BEFORE the cap so the surviving set is
    # deterministic across runs and consistent with the others[] sort / tie-break
    # key (path lexicographic), rather than git's enumeration (creation) order.
    other_tagged = sorted(
        (t for t in tagged if not t[1]), key=lambda t: t[0]["path"]
    )
    if len(other_tagged) > cap:
        r.soft_error(
            "worktree_scan_cap",
            f"{len(other_tagged)} other worktrees exceed cap {cap}; "
            f"scanning first {cap} by path order",
        )
        other_tagged = other_tagged[:cap]

    entries: list[dict] = []
    for w, is_current in current_tagged + other_tagged:
        if is_current and current_handoff is not None:
            entry = _current_tree_entry(
                project_root, current_handoff, w["branch"], r
            )
        else:
            entry = _resolve_tree_handoff(Path(w["path"]), w["branch"], r, is_current)
        if entry is not None:
            entries.append(entry)

    global_elsewhere = _arbitrate(entries)

    others_out = [
        {
            "path": e["path"],
            "branch": e["branch"],
            "doc": e["doc"],
            "updated_at": e["updated_at"],
            "status": e["status"],
            "track_id": e["track_id"],
            "cmp_key_source": e["cmp_key_source"],
        }
        for e in sorted(
            (e for e in entries if not e["is_current"]), key=lambda e: e["path"]
        )
    ]

    r.data = {
        "enabled": True,
        "enumerated": True,
        "worktree_count": worktree_count,
        "others": others_out,
        "global_latest_elsewhere": global_elsewhere,
    }
    return r

"""Phase 1.6 — OpenSpec (changes + archive) collector."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from ._common import CollectorResult, scan_now
from ._status import (
    _STATUS_HEAD_MAX_CHARS,
    _extract_status,
    _normalize_status,
    _status_field_overlong,
)

# ---------------------------------------------------------------------------
# Carry-forward extraction moved to scripts/lib/carry_forward.py (#134 A1.1b,
# archive-completeness-gate) so lib/spec_complete.py can reuse the SAME regex
# without a spec_complete ↔ openspec circular import. Both names stay
# re-exported here for backward compatibility (tests import them from this
# module). Dual-context import (same pattern as phase1_gate.py):
#   (a) proper package install — relative `..lib` resolves cleanly;
#   (b) scan.py / test harness — scripts/ is on sys.path and `collectors` is a
#       TOP-LEVEL package, so `..` is unresolvable → fall back to inserting the
#       scripts/lib dir and importing the bare module. Deliberately NOT
#       `from lib.carry_forward import ...`: the top-level name `lib` may
#       already be bound to state-scanner/lib (skill root) by
#       handoff_multibranch.py's _SS_ROOT sys.path insertion.
#
# `_FRONTMATTER_RE` / `_frontmatter_block` moved the same way to
# scripts/lib/frontmatter_block.py (runtime-probe-archive-gate-integration,
# TASK-004, #95 follow-up A) so lib/spec_complete.py (TASK-005) can reuse the
# SAME frontmatter-block regex too, without opening a THIRD circular-import
# path. Re-exported here unchanged, for the same backward-compat reason.
# ---------------------------------------------------------------------------
try:
    from ..lib.carry_forward import (  # type: ignore[import]
        _CARRY_FORWARD_RE,
        _extract_carry_forward_annotations,
    )
    from ..lib.frontmatter_block import (  # type: ignore[import]
        _FRONTMATTER_RE,
        _frontmatter_block,
    )
    from ..lib.spec_complete import is_spec_complete  # type: ignore[import]
except ImportError:
    import sys as _sys
    from pathlib import Path as _Path

    _SCRIPTS_LIB_DIR = str(_Path(__file__).resolve().parent.parent / "lib")
    if _SCRIPTS_LIB_DIR not in _sys.path:
        _sys.path.insert(0, _SCRIPTS_LIB_DIR)
    from carry_forward import (  # type: ignore[import]
        _CARRY_FORWARD_RE,
        _extract_carry_forward_annotations,
    )
    from frontmatter_block import (  # type: ignore[import]
        _FRONTMATTER_RE,
        _frontmatter_block,
    )
    from spec_complete import is_spec_complete  # type: ignore[import]


# ---------------------------------------------------------------------------
# #134 archive-completeness-gate consumption side (DEC-20260609-001 契约 B + D3)
# ---------------------------------------------------------------------------

# design_deferred staleness threshold N=30 days — deliberately a HARDCODED
# constant (A2.2), not config-driven (stdlib-only, no config plumbing).
_DESIGN_DEFERRED_STALENESS_DAYS = 30

# Incomplete specs in these normalized states ALWAYS land in design_deferred
# (DEC §3 D3): post-gate lifecycle slots whose implementation evidence is
# missing. {in_progress, ready, pending} are deliberately EXCLUDED — they are
# surfaced by requirements.priority_items elsewhere (requirements.py
# _PRIORITY_STATUSES). fresh-approved (<30d) is a legal in-flight state
# (visible as-is in changes[].items, not a black hole).
_DESIGN_DEFERRED_ALWAYS_STATES = frozenset({"reviewed", "active", "implemented"})

# Recognized machine-readable `archive_type` frontmatter values (契约 B). The
# write side (openspec-archive Step2, TG-B same version) only ever writes
# `implementation-deferred`; any other value is treated as unreadable —
# fail-soft null + soft_error so unknown formats degrade visibly, not silently.
_KNOWN_ARCHIVE_TYPES = frozenset({"implementation-deferred"})

# stdlib-only frontmatter field extraction (C5: 不引 PyYAML — 消费侧只需逐行
# 字段 regex)。frontmatter 区块 = 文件起始 `---` 行至下一 `---` 行之间 (提取逻辑
# + CRLF 处理见 lib/frontmatter_block.py::_FRONTMATTER_RE, 本文件仅 re-import
# — 见上方 import 区块注释, #132 同类教训随 move 带走不复制)。
_ARCHIVE_TYPE_FIELD_RE = re.compile(r"^archive_type[ \t]*[：:][ \t]*(.+?)[ \t]*$", re.MULTILINE)
_UPDATED_AT_FIELD_RE = re.compile(r"^updated-at[ \t]*[：:][ \t]*(.+?)[ \t]*$", re.MULTILINE)


def _read_archive_type(archive_entry: Path, r: CollectorResult) -> str | None:
    """Read frontmatter `archive_type` from an archived spec's proposal.md (A2.1).

    fail-soft (C5, stdlib-only, errors='replace'): proposal.md 缺失 / OSError /
    不认识的值 → None + soft_error (稳定 key=`archive_type_unreadable`, 与
    `spec_read_failed`/`tasks_read_failed`/`status_field_truncated` 同模式)。
    无 frontmatter 或 frontmatter 无该字段 = 正常归档 (标记是 v1.42.0+ 增量)
    → None, 无诊断。
    """
    proposal = archive_entry / "proposal.md"
    if not proposal.is_file():
        r.soft_error(
            "archive_type_unreadable", f"{archive_entry.name}: proposal.md not found"
        )
        return None
    try:
        text = proposal.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        r.soft_error("archive_type_unreadable", f"{archive_entry.name}: {e}")
        return None
    fm = _frontmatter_block(text)
    if fm is None:
        return None  # normal archive without frontmatter — not an error
    m = _ARCHIVE_TYPE_FIELD_RE.search(fm)
    if m is None:
        return None  # frontmatter present but no archive_type field — not an error
    value = m.group(1).strip().strip("'\"")
    if value not in _KNOWN_ARCHIVE_TYPES:
        r.soft_error(
            "archive_type_unreadable",
            f"{archive_entry.name}: unrecognized archive_type {value!r}",
        )
        return None
    return value


def _staleness_days(proposal: Path, proposal_text: str) -> int:
    """proposal.md age in whole days — frontmatter `updated-at` 优先, 回落 mtime.

    fail-soft: updated-at 不可解析 → mtime; mtime 不可得 → 0 (视为 fresh —
    surface 侧宁缺勿噪; gate 侧才是 fail-closed)。
    """
    ts: float | None = None
    fm = _frontmatter_block(proposal_text)
    if fm is not None:
        m = _UPDATED_AT_FIELD_RE.search(fm)
        if m:
            try:
                dt = datetime.fromisoformat(
                    m.group(1).strip().strip("'\"").replace("Z", "+00:00")
                )
                ts = dt.timestamp()
            except ValueError:
                ts = None
    if ts is None:
        try:
            ts = proposal.stat().st_mtime
        except OSError:
            return 0
    # 9.7 wall-clock face: scan_now() honors ARIA_SCAN_NOW instead of the real
    # system clock (day-granularity, so this only matters at a day-boundary edge —
    # but that edge is exactly the kind of environment-dependent flake 9.7 exists
    # to close for a frozen offline scan).
    return max(0, int((scan_now().timestamp() - ts) / 86400))


def _detect_stray_openspec_artifacts(spec_root: Path, r: CollectorResult) -> list[str]:
    """#166 defect 1: proposal-like artifacts under openspec/ that are NOT in the
    canonical openspec/changes/<id>/ layout — evidence that changes/ drifted
    (proposals landed in the wrong place). Two real shapes: a bare ``*proposal*.md``
    directly under openspec/, or a subdir (other than changes/, archive/) holding a
    proposal.md. Excludes the standard project.md. Names feed the layout_drift detail.

    An unreadable openspec/ (permission/IO) is surfaced as ``openspec_scan_failed``
    soft_error — NOT swallowed (a silently-empty result would make an unreadable
    openspec/ look identical to a non-OpenSpec repo, the exact false-green this
    change exists to kill; matches every other read-failure in this module).
    """
    stray: list[str] = []
    try:
        entries = sorted(spec_root.iterdir())
    except OSError as e:
        r.soft_error("openspec_scan_failed", f"openspec/ unreadable: {e}")
        return stray
    for entry in entries:
        if entry.name in ("changes", "archive"):
            continue
        if entry.is_file() and "proposal" in entry.name and entry.suffix == ".md":
            stray.append(entry.name)
        elif entry.is_dir() and (entry / "proposal.md").is_file():
            stray.append(entry.name + "/")
    return stray


def collect_openspec(project_root: Path) -> CollectorResult:
    """Scan openspec/changes/ + openspec/archive/ for active + archived Specs."""
    r = CollectorResult()
    spec_root = project_root / "openspec"
    changes_dir = spec_root / "changes"
    archive_dir = spec_root / "archive"

    change_items: list[dict[str, Any]] = []
    pending_archive: list[dict[str, Any]] = []
    design_deferred: list[dict[str, Any]] = []
    carry_forward_by_change: dict[str, dict[str, Any]] = {}
    carry_forward_total = 0

    # #166 defect 1: openspec/ exists but openspec/changes/ vanished (git drops empty
    # dirs after the last spec is archived) → do NOT early-return a silent all-zero
    # payload. The changes loop below no-ops when changes/ is absent, archive/ is still
    # scanned orthogonally, and the layout_drift verdict is emitted after that scan
    # (so it can reuse archive_items instead of probing archive/ a second time).
    for d in sorted(changes_dir.iterdir()) if changes_dir.is_dir() else []:
        if not d.is_dir():
            continue
        proposal = d / "proposal.md"
        if not proposal.exists():
            continue
        try:
            proposal_text = proposal.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            r.soft_error("spec_read_failed", f"{d.name}: {e}")
            continue
        raw = _extract_status(proposal_text)
        st = _normalize_status(raw)
        # #50 fix: surface over-long separator-less Status fields so spec authors
        # get visible feedback (the head was hard-cut at _STATUS_HEAD_MAX_CHARS).
        if _status_field_overlong(raw):
            r.soft_error(
                "status_field_truncated",
                f"{d.name}: Status field head exceeds {_STATUS_HEAD_MAX_CHARS} "
                "chars with no separator — lifecycle keyword may be lost",
            )
        item = {
            "id": d.name,
            "path": str(proposal.relative_to(project_root)),
            "status": st,
            "raw_status": raw,
        }
        change_items.append(item)
        # A2.5 (#134, DEC-20260609-001 §3 D2): archive-ready 集 = {done} ONLY。
        # `implemented` (= post-merge, awaiting verify/archive) 刻意不入
        # pending_archive — 否则等价重开 gap(b)。状态归一化唯一 SOT =
        # collectors/_status.py::_normalize_status, 不得在此另写字面匹配。
        if st == "done":
            pending_archive.append({"id": d.name, "reason": "Status=done still in changes/"})

        # A2.2 (#134, DEC §3 D3): design_deferred surface — gate↔surface 互补。
        # 谓词: complete==False ∩ ( unknown ∪ (approved ∧ staleness>=30d) ∪
        # {reviewed,active,implemented} )。in_progress/ready/pending 排除 (别处
        # priority_items surface); fresh-approved (<30d) 合法在飞不卷入。
        # complete 判定经 lib/spec_complete.py 单一 SOT (A2.3, 契约 A), 不复制逻辑。
        verdict = is_spec_complete(d)
        if not verdict["complete"]:
            staleness = _staleness_days(proposal, proposal_text)
            if (
                st == "unknown"
                or st in _DESIGN_DEFERRED_ALWAYS_STATES
                or (st == "approved" and staleness >= _DESIGN_DEFERRED_STALENESS_DAYS)
            ):
                design_deferred.append(
                    {
                        "id": d.name,
                        "status": st,
                        "staleness_days": staleness,
                        "reason": verdict["reason"],
                    }
                )

        # Phase 1.6.1: scan tasks.md for inline carry-forward annotations.
        # aria-plugin #113 (SC-7): when tasks.md is absent, fall back to the
        # detailed-tasks.yaml raw text through the SAME regex SOT (task-planner
        # path B specs used to contribute a structural 0 — display-side false
        # green). Precedence mirrors the gate (决策 6): tasks.md present ⇒ yaml
        # NOT consulted, so dual-layer output stays byte-identical (stale
        # A.3-era yaml annotations must not double-count).
        tasks_file = d / "tasks.md"
        annotation_source = None
        if tasks_file.is_file():
            annotation_source = ("tasks_read_failed", tasks_file)
        elif (d / "detailed-tasks.yaml").is_file():
            annotation_source = ("detailed_tasks_read_failed", d / "detailed-tasks.yaml")
        if annotation_source is not None:
            error_kind, source_path = annotation_source
            try:
                tasks_content = source_path.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                r.soft_error(error_kind, f"{d.name}: {e}")
                continue
            matches = _extract_carry_forward_annotations(tasks_content)
            if matches:
                samples = [
                    (m[:80] + "...") if len(m) > 80 else m
                    for m in matches[:3]
                ]
                carry_forward_by_change[d.name] = {
                    "count": len(matches),
                    "samples": samples,
                }
                carry_forward_total += len(matches)

    archive_items: list[dict[str, Any]] = []
    if archive_dir.is_dir():
        # fail-soft listing: an unreadable archive/ must neither crash the whole scan
        # nor vanish silently (#166 review, silent-failure-hunter).
        try:
            archive_entries = sorted(archive_dir.iterdir())
        except OSError as e:
            r.soft_error("openspec_scan_failed", f"openspec/archive/ unreadable: {e}")
            archive_entries = []
        for d in archive_entries:
            if not d.is_dir():
                continue
            m = re.match(r"^(\d{4}-\d{2}-\d{2})-(.+)$", d.name)
            archive_items.append(
                {
                    "path": str(d.relative_to(project_root)),
                    "date": m.group(1) if m else None,
                    "feature": m.group(2) if m else d.name,
                    # A2.1 (#134, 契约 B 消费侧): additive str|null (v1.42.0+)
                    "archive_type": _read_archive_type(d, r),
                }
            )

    # #166 defect 1 verdict: changes/ missing while openspec/ exists. Scream only with
    # evidence of prior/misplaced OpenSpec use (archive_items non-empty — reused from
    # the scan above — or stray proposals); stay silent for a genuine cold-start so the
    # signal keeps its meaning. openspec/ absent entirely never reaches here.
    if not changes_dir.is_dir() and spec_root.is_dir():
        stray = _detect_stray_openspec_artifacts(spec_root, r)
        if stray or archive_items:
            hint = f"misplaced: {', '.join(stray)}" if stray else "archive/ has content"
            r.soft_error(
                "layout_drift",
                f"openspec/ exists but openspec/changes/ is missing ({hint}) — "
                f"active changes (if any) are invisible and new specs may be "
                f"misplaced. Restore changes/ (e.g. add openspec/changes/.gitkeep so "
                f"the dir persists when empty).",
            )

    r.data = {
        # #166 defect 1: configured tracks the documented `openspec/changes/ exists`
        # semantics (drift path stays False; layout_drift soft_error disambiguates
        # "drifted" from "not configured" — no code branches on this field).
        "configured": changes_dir.is_dir(),
        "changes": {"total": len(change_items), "items": change_items},
        "archive": {"total": len(archive_items), "items": archive_items},
        "pending_archive": pending_archive,
        "design_deferred": design_deferred,
        "carry_forward_inventory": {
            "total": carry_forward_total,
            "active_change_count": len(change_items),
            "by_change": carry_forward_by_change,
        },
    }
    return r

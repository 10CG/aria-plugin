"""latest.md derived-artifact writer (TASK-006).

Writes ``docs/handoff/latest.md`` based on the number of active tracks in the
current scan snapshot.  Three scenarios are handled:

    * **Single active track** (count == 1): writes a backward-compatible
      pointer pointing at that track's handoff filename.
    * **Multi active track** (count >= 2): writes a deprecation banner listing
      all active tracks and instructing readers to use /aria:state-scanner.
    * **Zero active track** (count == 0): writes a minimal "no active tracks"
      placeholder.

The function is test-friendly:

    - ``output_path`` is an explicit parameter (no hardcoded path).
    - ``now`` can be injected for deterministic output.
    - Writing is atomic: content is written to ``<output_path>.tmp`` and then
      renamed over ``output_path`` via ``os.replace``.

This writer is **NOT called by scan.py**.  It is invoked by
phase-d-closer D.3 after a session handoff decision has been made.

TODO(TASK-integrate): wire call-site in phase-d-closer D.3 step once
Layer L (TASK-011+) claim data is available in snapshot and the
integration is designed; see tasks.md §1.6 and §3.x.

Public API:
    write_latest_md(snapshot, output_path, now=None) -> dict

Return dict schema:
    {
        "action":        "pointer" | "banner" | "skipped",
        "path":          str,          # absolute path written
        "content_lines": int,          # number of lines written
        "degraded_reason": str | None, # None | "missing_filename" | "target_in_subdir"
    }

Spec:  openspec/changes/multi-terminal-coordination/tasks.md §1.6
Task:  TASK-006 (backend-architect)
Deps:  TASK-005 (track_board.py — defines active track semantics)
       TASK-004 (handoff_multibranch.py — tracks_multibranch schema)
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Constants ──────────────────────────────────────────────────────────────────

# Semantic authority note: latest.md is a *prose* fallback pointer.
# The frontmatter inside the actual handoff document is the canonical
# semantic authority per session-handoff.md §2.3.
_SEMANTIC_AUTHORITY_NOTE = (
    "**Semantic authority**: handoff doc YAML frontmatter "
    "(per session-handoff.md §2.3), not this file. "
    "本文件由 state-scanner v1.22.x+ writers/latest_md_writer.py 派生生成,"
    "不应手动编辑。"
)

_COMPAT_NOTE = (
    "**Note**: 自 multi-terminal-coordination v1.22.x+, state-scanner Phase 1 看板\n"
    "从全分支 frontmatter 重建;本 latest.md 仅供向后兼容老 session 读。语义权威在\n"
    "handoff doc 自身的 YAML frontmatter (per session-handoff.md §2.3)。"
)


# ── Active-track filtering ─────────────────────────────────────────────────────


def _get_active_tracks(snapshot: dict) -> list[dict]:
    """Extract tracks whose frontmatter status == "active" from the snapshot.

    Reads ``snapshot["tracks_multibranch"]["tracks"]``.
    Returns an empty list when the key is absent or malformed (never raises).

    Legacy tracks (``status == "legacy"``) are intentionally excluded from the
    active count: they carry no heartbeat signal and the board already renders
    them distinctly.  Multi-track banner includes them as a separate annotation
    (see _render_banner).
    """
    try:
        tmb: dict = snapshot.get("tracks_multibranch") or {}
        tracks: list[dict] = tmb.get("tracks") or []
    except (AttributeError, TypeError):
        return []

    active: list[dict] = []
    for t in tracks:
        status = (t.get("status") or "").lower().strip()
        if status == "active":
            active.append(t)
    return active


def _get_legacy_tracks(snapshot: dict) -> list[dict]:
    """Return tracks with status == "legacy" for banner annotation."""
    try:
        tmb: dict = snapshot.get("tracks_multibranch") or {}
        tracks: list[dict] = tmb.get("tracks") or []
    except (AttributeError, TypeError):
        return []
    return [t for t in tracks if (t.get("status") or "").lower().strip() == "legacy"]


# ── Content renderers ──────────────────────────────────────────────────────────


def _render_pointer(track: dict, now: datetime) -> tuple[str, str | None]:
    """Render the single-track pointer content, plus its machine-readable reason.

    Returns ``(content, reason)``. ``reason`` is ``None`` when a real pointer was
    written, and otherwise names why it could not be — ``missing_filename`` or
    ``target_in_subdir``. Callers publish that value verbatim as
    ``degraded_reason``: it is decided HERE and nowhere else, so the page text
    and the machine-readable field cannot disagree. (They used to be two
    independent computations that only agreed by coincidence.)

    A pointer in ``latest.md`` is relative, and the consumer that reads it back
    (``collectors/handoff.py``) scans ``docs/handoff/`` NON-recursively. A target
    under a subdirectory is therefore unaddressable rather than merely awkward,
    which is why it degrades instead of writing a link that resolves to nothing.
    """
    filename: str | None = track.get("filename") or None
    track_id: str = track.get("track_id") or "(unknown)"
    phase: str = track.get("phase") or "unknown"
    updated_at: str = track.get("updated_at") or ""

    if not filename:
        # Edge case: active track but filename missing (should not happen with
        # well-formed frontmatter, but handle gracefully).
        return _render_pointer_unavailable(track_id, now, reason="missing_filename")

    # Guard on the DATA, never on the shape of the string: `filename` is always a
    # basename by contract, so sniffing it for "/" would be a predicate that can
    # never fire. The relative path is what carries the directory segment, and a
    # track predating that key falls back to the basename — which compares equal
    # and keeps the flat world writing real pointers (10CG/Aria#195).
    rel = track.get("rel_path") or track.get("filename")
    if rel != filename:
        return _render_pointer_unavailable(
            track_id, now, reason="target_in_subdir", rel=rel
        )

    # Build the "updated=<date>" display value: use the ISO string's date portion
    # if available, otherwise the raw string, otherwise "unknown".
    if updated_at and len(updated_at) >= 10:
        display_updated = updated_at[:10]
    elif updated_at:
        display_updated = updated_at
    else:
        display_updated = "unknown"

    lines: list[str] = [
        "# Aria Handoff — Latest",
        "",
        "> 此文件指向最近一次 session handoff。Aria 项目内部约定:",
        "> 始终 Read 本文件作为 next session 入口,内容指向具体的日期版 handoff。",
        "> 自 v1.22.x 起,本 pointer 仅在**单 active track** 且**目标在 `docs/handoff/` 顶层**时写真实指针;",
        "> **多 track** 场景由 state-scanner 多 track 看板 surface,本文件成为 deprecation banner。",
        "",
        f"**Latest**: [{filename}](./{filename})"
        f" — {track_id} @ phase={phase} updated={display_updated}",
        "",
        _COMPAT_NOTE,
    ]
    return "\n".join(lines) + "\n", None


def _render_pointer_unavailable(
    track_id: str,
    now: datetime,
    *,
    reason: str,
    rel: str | None = None,
) -> tuple[str, str]:
    """Fallback page for the two cases where no real pointer can be written.

    ``reason`` is returned verbatim and is one of the two non-``None`` members of
    the ``degraded_reason`` enum:

    - ``missing_filename`` — the single active track carries no filename.
    - ``target_in_subdir`` — the target lives under a subdirectory of
      ``docs/handoff/``. A relative pointer cannot address it, because the
      consumer reading ``latest.md`` back scans that directory non-recursively.

    ``rel`` is the relative path, quoted into the page for the subdir case so a
    human sees which file was meant.
    """
    now_iso = now.strftime("%Y-%m-%dT%H:%MZ")
    if reason == "target_in_subdir":
        cause = (
            f"> _原因: 目标在 docs/handoff/ 的子目录下 (`{rel}`),"
            " latest.md 的相对指针无法指向它 —— 读回 pointer 的"
            " `collectors/handoff.py` 只扫顶层、不递归, 指过去也读不到。_"
        )
    else:
        cause = "> _原因: active track 数据缺少 filename 字段,无法构建指针。_"
    lines: list[str] = [
        "# Aria Handoff — Latest",
        "",
        "> 此文件指向最近一次 session handoff。Aria 项目内部约定:",
        "> 始终 Read 本文件作为 next session 入口,内容指向具体的日期版 handoff。",
        "> 自 v1.22.x 起,本 pointer 仅在**单 active track** 且**目标在 `docs/handoff/` 顶层**时写真实指针;",
        "> **多 track** 场景由 state-scanner 多 track 看板 surface,本文件成为 deprecation banner。",
        "",
        f"**Latest**: (pointer 不可用) — track={track_id} @ {now_iso}",
        "",
        cause,
        "> _请运行 `/aria:state-scanner` 获取完整看板。_",
        "",
        _COMPAT_NOTE,
    ]
    return "\n".join(lines) + "\n", reason


def _render_banner(active_tracks: list[dict], legacy_tracks: list[dict], now: datetime) -> str:
    """Render the multi-track deprecation banner.

    Lists all active tracks in a markdown table.
    Legacy tracks are appended as a separate table section with a note.
    """
    n_active = len(active_tracks)
    now_iso = now.strftime("%Y-%m-%dT%H:%MZ")

    lines: list[str] = [
        "# Aria Handoff — Latest (deprecated in multi-track context)",
        "",
        f"> ⚠ 当前有 {n_active} 个 active tracks 在飞 — `latest.md` 单指针**无法准确表达**。",
        "> 请运行 `/aria:state-scanner` 查看完整多 track 看板。",
        f"> Active tracks (per coordination scan @ {now_iso}):",
        ">",
        "> | track-id | owner-container | phase | updated-at |",
        "> |----------|-----------------|-------|------------|",
    ]

    # Populate table rows for active tracks
    for t in active_tracks:
        tid = t.get("track_id") or "(unknown)"
        owner = t.get("owner_container") or "unknown"
        phase = t.get("phase") or "—"
        updated = t.get("updated_at") or "—"
        # Truncate updated-at to 16 chars (YYYY-MM-DDTHH:MM) for table readability
        if len(updated) > 16:
            updated = updated[:16] + "Z"
        lines.append(f"> | {tid} | {owner} | {phase} | {updated} |")

    # Append legacy tracks section when present
    if legacy_tracks:
        lines.append(">")
        lines.append("> **Legacy tracks** (no frontmatter — mtime fallback):")
        lines.append(">")
        lines.append("> | track-id (legacy) | branch | filename | updated-at |")
        lines.append("> |-------------------|--------|----------|------------|")
        for t in legacy_tracks:
            tid = t.get("track_id") or "(unknown)"
            branch = t.get("branch") or "—"
            filename = t.get("filename") or "—"
            updated = t.get("updated_at") or "—"
            if len(updated) > 16:
                updated = updated[:16] + "Z"
            lines.append(f"> | {tid} | {branch} | {filename} | {updated} |")

    lines += [
        "",
        _SEMANTIC_AUTHORITY_NOTE,
    ]
    return "\n".join(lines) + "\n"


def _render_zero_tracks(now: datetime) -> str:
    """Render the zero-active-tracks placeholder."""
    now_iso = now.strftime("%Y-%m-%dT%H:%MZ")
    lines: list[str] = [
        "# Aria Handoff — (no active tracks)",
        "",
        f"_state-scanner: 0 active tracks 当前 (scanned @ {now_iso})。_",
        "_请运行新 session 启动 cycle。_",
    ]
    return "\n".join(lines) + "\n"


# ── Atomic write helper ────────────────────────────────────────────────────────


def _atomic_write(output_path: Path, content: str) -> None:
    """Write content to output_path atomically via a .tmp intermediate.

    1. Ensures parent directory exists (``mkdir parents=True, exist_ok=True``).
    2. Writes to ``<output_path>.tmp``.
    3. Renames to ``output_path`` via ``os.replace`` (atomic on POSIX).

    Raises OSError on failure (caller should handle).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(tmp_path, output_path)


# ── Public API ─────────────────────────────────────────────────────────────────


def write_latest_md(
    snapshot: dict,
    output_path: Path,
    now: Optional[datetime] = None,
) -> dict:
    """Write ``docs/handoff/latest.md`` derived from the active track count.

    Args:
        snapshot:    Full scan.py snapshot dict.  Reads
                     ``snapshot["tracks_multibranch"]["tracks"]``.
        output_path: Destination path for ``latest.md``.  The parent
                     directory is created automatically if absent.
                     Pass ``Path("docs/handoff/latest.md")`` relative to
                     project root, or an absolute path for testing.
        now:         UTC datetime for timestamp rendering.  Inject a fixed
                     value in tests for determinism.  Defaults to
                     ``datetime.now(timezone.utc)``.

    Returns:
        dict with keys:
            ``action``        — "pointer" | "banner" | "skipped"
            ``path``          — str(output_path) as written
            ``content_lines`` — number of newline-separated lines written
            ``degraded_reason`` — always present; None when a real pointer was
                                  written, else "missing_filename" | "target_in_subdir"

    Never raises for missing/malformed snapshot data — all edge cases
    produce graceful fallback content.  OSError from the filesystem is
    propagated to the caller (phase-d-closer D.3 step handles it).

    Scenarios:
        active count == 0  → "skipped" action, zero-track placeholder
        active count == 1  → "pointer" action, backward-compatible pointer
        active count >= 2  → "banner"  action, deprecation banner + table
        count == 1, target in subdir → "pointer" action, degraded_reason="target_in_subdir"
            (a degraded page naming the cause, instead of a link that resolves to nothing)
    """
    if now is None:
        now = datetime.now(tz=timezone.utc)

    active_tracks = _get_active_tracks(snapshot)
    n_active = len(active_tracks)

    # Initialised before the dispatch so every branch publishes the key. Only the
    # single-track branch can change it, and it does so by UNPACKING the renderer's
    # own verdict — this function must never recompute that judgement, or the page
    # text and this field become two independent computations that agree only by
    # coincidence (10CG/Aria#195).
    degraded_reason: str | None = None

    if n_active == 0:
        content = _render_zero_tracks(now)
        action = "skipped"

    elif n_active == 1:
        content, degraded_reason = _render_pointer(active_tracks[0], now)
        action = "pointer"

    else:
        # n_active >= 2: multi-track deprecation banner
        legacy_tracks = _get_legacy_tracks(snapshot)
        content = _render_banner(active_tracks, legacy_tracks, now)
        action = "banner"

    _atomic_write(output_path, content)

    content_lines = content.count("\n")

    return {
        "action": action,
        "path": str(output_path),
        "content_lines": content_lines,
        # Always present, on all three branches: the public contract in
        # references/phase-1-collectors.md declares a fixed-shape dict, and a key
        # that exists on only one branch is exactly the "contract says one thing,
        # implementation does another" defect this change exists to remove.
        "degraded_reason": degraded_reason,
    }

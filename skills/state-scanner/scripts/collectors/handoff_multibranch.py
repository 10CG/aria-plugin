"""Phase 1 (multi-terminal-coordination) — cross-branch handoff track rebuilder.

Scans every ``origin/*`` branch for ``docs/handoff/*.md`` files, calls
``parse_handoff_frontmatter`` from the sibling ``handoff`` collector, and
reconstructs the multi-track dashboard track list consumed by TASK-005.

This collector is **read-only**: it uses ``git show`` / ``git ls-tree`` /
``git log`` to inspect remote refs without touching the working tree or index.
It MUST run AFTER ``collect_remote_refresh`` (Phase 0.5, F3′) so that all remote
refs are present locally. (Pre-F6′ this was ``collect_coordination_fetch``; that
collector's network I/O was retired into ``remote_refresh.py`` and
``coordination_fetch.py`` is now a pure derivation shim.)

Return schema (top-level snapshot key: ``tracks_multibranch``):

    {
        "exists": bool,         # True when ≥1 track found across all branches
        "tracks": list[dict],   # One entry per (branch, file) pair — see below
        "branches_scanned": int,
        "legacy_count": int,    # Tracks that fell back to legacy (no frontmatter)
        "collision": {          # TASK-000 (#133) — additive, ADVISORY-ONLY
            "kind": str,        # "none" | "cross_owner" | "self_multi_container"
            "groups": list,     # list[list[str]] — per colliding track_id: oc members
            "dedupe": dict,     # OPTIONAL (#155) — {"input_tracks": N, "after_dedupe": M,
                                #   "legacy_passthrough": L} — N/M count non-legacy rows
                                # ONLY (legacy rows never fold; L is their count).
                                # present ONLY when deduping collapsed >=1 non-legacy row;
                                # see "Collision dedupe" section below.
        },
        "errors": list[str],    # Accumulated non-fatal error messages
    }

Each entry in ``tracks`` is:

    {
        "track_id": str,          # frontmatter["track-id"] OR "legacy:<branch>:<filename>"
        "owner_container": str,   # frontmatter["owner-container"] OR "unknown"
        "phase": str,             # frontmatter["phase"] OR "unknown"
        "status": str,            # frontmatter["status"] OR "legacy"
        "updated_at": str,        # frontmatter["updated-at"] OR git log committer date (ISO)
        "branch": str,            # short branch name (no "origin/" prefix)
        "filename": str,          # basename of the handoff file
        "legacy": bool,           # True when frontmatter was absent/incomplete
    }

Design notes:

- ``git ls-tree`` + ``git show`` operate on remote ref objects — no checkout.
- ``latest.md`` is excluded per ``feedback_collector_exclude_navigation_pointer``
  memory entry (it is a navigation pointer, not a real handoff document).
- Same ``track_id`` appearing on multiple branches is intentionally preserved
  (collision detection per session-handoff.md §2.3.5).  TASK-005 renders the
  collision signals.
- ``tracks[]`` itself is NEVER deduped (full history stays additive). Only the
  list handed to collision *classification* is deduped, one row per
  ``(track_id, owner/container)`` — the SESSION segment of ``owner_container``
  does NOT participate in the grouping key (round 3, finding [m]; split via
  ``lib.collision.split_owner_container``, read-only import) — newest
  ``updated_at`` wins, ties broken by dictionary-max filename then
  dictionary-max branch (round 3, finding [M1]; fully deterministic,
  input-order-invariant) — fix for aria-plugin#155: stale ``status: active``
  historical handoff rows for an already-closed track were keeping
  ``tracks_multibranch.collision.kind`` at ``self_multi_container`` forever,
  because ``lib/collision.py::classify()`` groups by ``track_id`` only and
  never expires non-terminal rows. See the public
  ``dedupe_latest_per_track_container`` below — also imported verbatim by
  ``renderers/track_board.py`` so the board and this collector agree on one
  snapshot.
- Frontmatter parsing uses a stdlib-only YAML-subset parser (since v1.30.2,
  fix for Forgejo aria-plugin #57 Finding 2) — no external dep required.
- Performance: limited to ``refs/remotes/origin/`` (shallow ref list from
  TASK-003 fetch) — history is not walked.
- If the remote branch count exceeds the resolved scan cap (default 20, see
  resolve_max_branches_scanned in _common.py; #71 v1.38.0) only the first N
  branches (most-recent by committerdate) are processed.  A soft_error notes
  the cap, quoting the resolved value.

Spec: openspec/changes/multi-terminal-coordination/tasks.md §1.4
Task: TASK-004 (backend-architect)
Deps: remote_refresh.py (F3′; supersedes TASK-003 coordination_fetch.py fetching)
      + TASK-009 (handoff.py parse_handoff_frontmatter)

aria-plugin#155 (backend-architect, fix/issue-batch-149-151-155-134): added
collision-classification-input dedupe (public ``dedupe_latest_per_track_container``
+ additive ``collision.dedupe`` audit key) — see "Collision dedupe" section
below and the module-level comment above ``dedupe_latest_per_track_container``.
Round 2 (same task, post-review): filename tie-break on ``updated_at`` ties
(round 1 silently picked list-iteration-order on a tie — wrong on this repo's
own real data); ``dedupe_latest_per_track_container`` made public and its
signature changed to ``-> (deduped, stats)``; ``collision.dedupe`` counts now
exclude legacy rows (``legacy_passthrough`` added); ``renderers/track_board.py``
now imports and applies the same function so the board's COLLISION lines and
this collector's ``collision.groups`` never diverge.
Round 3 (same task, second post-review): [M1] the sort key gained a 4th
level, ``branch`` (dictionary-max), closing the remaining non-determinism on
the mainline multi-branch shape — the SAME handoff file reachable from
multiple branches (identical track_id/owner_container/updated_at/filename),
where round 2's 3-level key still silently fell back to branch-scan-order.
[m] the dedupe grouping key changed from the raw ``owner_container`` string
to ``(owner, container)`` via ``lib.collision.split_owner_container`` — the
SESSION segment no longer participates, so two historical rows for the same
track+container that differ only by session (e.g. an old ``active`` row from
one session, a newer ``done`` row from a later session) now correctly fold
into one representative instead of surviving as two separate dedupe-of-one
groups.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from pathlib import Path

# Note (Round 6 review): `git show` / `git ls-tree` invocations below intentionally
# omit the `--` ref/path separator because `for-each-ref` upstream already filters
# to legitimate `refs/remotes/origin/*` strings — there is no path that could be
# misinterpreted as a flag. Adding `--` would require a refactor for `git show`'s
# `<ref>:<path>` syntax (which does not accept `--` between ref and path).

from ._common import (
    CollectorResult,
    _run,
    classify_git_error,
    log,
    resolve_max_branches_scanned,
)
from .handoff import parse_handoff_frontmatter

# ---------------------------------------------------------------------------
# Collision classification (TASK-000, concurrent-session-upm-safety #133).
# Persist the advisory collision summary (tracks_multibranch.collision) so that
# downstream consumers (state-scanner Phase 2 advisory / track_board renderer)
# read one source of truth instead of recomputing — and so the field is no
# longer a phantom (sister R1 C1).  Import is guarded: lib/ is a sibling of
# scripts/, not under collectors/, so we inject the state-scanner root onto
# sys.path (mirrors scripts/renderers/track_board.py's strategy).
# ---------------------------------------------------------------------------
try:
    import sys as _sys
    from pathlib import Path as _Path
    _SS_ROOT = str(_Path(__file__).resolve().parent.parent.parent)  # state-scanner/
    if _SS_ROOT not in _sys.path:
        _sys.path.insert(0, _SS_ROOT)
    from lib.collision import (  # type: ignore[import]
        classify as _classify_collision_summary,
        split_owner_container as _split_owner_container,
        identity_key as _identity_key,
        identity_drift_advisories as _identity_drift_advisories,
        filter_layer_h_fresh as _filter_layer_h_fresh,
    )
    _COLLISION_AVAILABLE = True
except ImportError:
    _COLLISION_AVAILABLE = False  # fail-soft: collision summary degrades to none
    _split_owner_container = None  # type: ignore[assignment]  # dedupe grouping falls back to raw owner_container string (see dedupe_latest_per_track_container)
    _identity_key = None  # type: ignore[assignment]
    _identity_drift_advisories = None  # type: ignore[assignment]
    _filter_layer_h_fresh = None  # type: ignore[assignment]

# ── Constants ─────────────────────────────────────────────────────────────────

# Maximum number of remote branches to scan per run.
# Tasks.md §1.3 notes fetch is limited to refs/heads/* already; this is
# an additional guard against excessively large repos.
# v1.38.0 (#71): the cap is now 3-layer configurable (env > config > default 20)
# via `resolve_max_branches_scanned()` in _common.py — resolved per-run inside
# collect_handoff_multibranch(), no longer a module-level constant. Large repos
# (e.g. 440 remote branches) set state_scanner.handoff_multibranch.max_branches
# or ARIA_HANDOFF_MAX_BRANCHES to lift the default.

# File excluded from handoff doc detection (navigation pointer, not a doc).
# Must match POINTER_FILENAME in handoff.py for consistency.
_POINTER_FILENAME: str = "latest.md"

# The remote name that remote_refresh.py fetches from (F3′, Phase 0.5).
_REMOTE: str = "origin"

# docs/handoff/ tree path (trailing slash required by git ls-tree --name-only)
_HANDOFF_TREE_PATH: str = "docs/handoff"

# Short timeout for per-file git show (content read).
_GIT_SHOW_TIMEOUT: int = 5

# Timeout for listing branch refs and ls-tree.
_GIT_LIST_TIMEOUT: int = 5


# ── Helpers ───────────────────────────────────────────────────────────────────


def _list_origin_branches(project_root: Path) -> tuple[list[str], str | None]:
    """Return (branch_names, error_msg|None) where branch_names are short names.

    Uses ``git for-each-ref --format='%(refname:short)' refs/remotes/origin/``
    to enumerate all remote branches that were populated by TASK-003 fetch.
    Excludes the synthetic ``origin/HEAD`` pointer.
    """
    # Sort by committerdate desc so most-recently-updated branches win the
    # scan cap (Round 8 tech-lead Finding #4 fix — previously
    # lexicographic order let archive/* + bugfix/* steal scan budget from
    # master + feature/*; first dogfood run after v1.22.0 ship immediately
    # surfaced this in real use against this very Aria repo).
    cmd = [
        "git",
        "for-each-ref",
        "--sort=-committerdate",
        "--format=%(refname:short)",
        "refs/remotes/origin/",
    ]
    rc, stdout, stderr = _run(cmd, cwd=project_root, timeout=_GIT_LIST_TIMEOUT)
    if rc != 0:
        # Internal classification (Spec B v5 R8 C-1): stderr is consumed here and
        # NOT returned raw — the caller receives a bounded label, so stderr never
        # escapes this function into snapshot.
        cls = classify_git_error(rc, stderr, "git for-each-ref")
        return [], f"git for-each-ref {cls.label} (rc={cls.rc})"

    branches: list[str] = []
    for line in stdout.splitlines():
        short = line.strip()
        if not short:
            continue
        # Strip "origin/" prefix to get the bare branch name.
        # e.g. "origin/feature/multi-terminal-coordination" → "feature/multi-terminal-coordination"
        if short.startswith(f"{_REMOTE}/"):
            bare = short[len(f"{_REMOTE}/"):]
        else:
            bare = short
        # Exclude the HEAD pointer ref
        if bare == "HEAD":
            continue
        branches.append(bare)

    # Preserve `git for-each-ref --sort=-committerdate` ordering (most-recently-updated
    # branches first) so the scan cap keeps active branches over stale ones.
    # Round 8 tech-lead Finding #4 fix — previously `sorted(branches)` undid the git
    # sort and let archive/* + bugfix/* steal scan budget. Surfaced at zero-day dogfood.
    return branches, None


def _list_handoff_files(project_root: Path, branch: str) -> tuple[list[str], str | None]:
    """Return (filenames, error_msg|None) of handoff .md files on a remote branch.

    Uses ``git ls-tree -r --name-only origin/<branch> -- docs/handoff/``.
    Excludes ``latest.md`` (navigation pointer).

    Returns only the basename (not the full path) for each file so callers
    compose the full git-object path as needed.
    """
    ref = f"{_REMOTE}/{branch}"
    cmd = [
        "git",
        "ls-tree",
        "-r",
        "--name-only",
        ref,
        "--",
        _HANDOFF_TREE_PATH,
    ]
    rc, stdout, stderr = _run(cmd, cwd=project_root, timeout=_GIT_LIST_TIMEOUT)

    if rc != 0:
        # Branch may have been deleted between fetch and now, or the tree path
        # simply doesn't exist — not an error worth blocking the scan for.
        stderr_lower = stderr.lower()
        if "not a tree object" in stderr_lower or "not a valid object" in stderr_lower:
            return [], None  # Branch has no docs/handoff/ tree — silently skip
        # benign-skip preserved above (still first, still in-function); only a
        # NON-benign failure reaches classify_git_error (Spec B v5 R8 C-1 / R7 m-1).
        cls = classify_git_error(rc, stderr, "git ls-tree")
        return [], f"git ls-tree failed for {ref} ({cls.label}, rc={cls.rc})"

    filenames: list[str] = []
    for line in stdout.splitlines():
        path = line.strip()
        if not path:
            continue
        basename = Path(path).name
        if not basename.endswith(".md"):
            continue
        if basename == _POINTER_FILENAME:
            # Exclude navigation pointer per feedback_collector_exclude_navigation_pointer
            log.debug(
                "handoff_multibranch: excluding pointer file '%s' on branch '%s'",
                basename,
                branch,
            )
            continue
        filenames.append(basename)

    return filenames, None


def _read_file_content(
    project_root: Path, branch: str, filename: str
) -> tuple[str | None, str | None]:
    """Return (content, error_msg|None) for a handoff file on a remote branch.

    Uses ``git show origin/<branch>:docs/handoff/<filename>`` to read the file
    object without checking out the branch.
    """
    ref = f"{_REMOTE}/{branch}:{_HANDOFF_TREE_PATH}/{filename}"
    cmd = ["git", "show", ref]
    rc, stdout, stderr = _run(cmd, cwd=project_root, timeout=_GIT_SHOW_TIMEOUT)
    if rc != 0:
        cls = classify_git_error(rc, stderr, "git show")
        return None, f"git show failed for {ref} ({cls.label}, rc={cls.rc})"
    return stdout, None


def _get_file_commit_date(
    project_root: Path, branch: str, filename: str
) -> str:
    """Return the ISO 8601 UTC committer date for the most recent commit touching a file.

    Uses ``git log -1 --format=%aI origin/<branch> -- docs/handoff/<filename>``.
    %aI = strict ISO 8601 format of author date (UTC-aware).

    Falls back to empty string if git log fails or returns nothing.
    """
    ref = f"{_REMOTE}/{branch}"
    path = f"{_HANDOFF_TREE_PATH}/{filename}"
    cmd = ["git", "log", "-1", "--format=%aI", ref, "--", path]
    rc, stdout, _stderr = _run(cmd, cwd=project_root, timeout=_GIT_LIST_TIMEOUT)
    if rc != 0:
        return ""
    return stdout.strip()


def _make_legacy_track_id(branch: str, filename: str) -> str:
    """Construct a deterministic legacy track_id from branch + filename.

    Format: ``legacy:<branch>:<filename>`` per task spec §Impl notes.
    The branch separator is ":" which is invalid in git branch names,
    so there is no ambiguity.
    """
    return f"legacy:{branch}:{filename}"


# ── Collision dedupe (aria-plugin#155) ──────────────────────────────────────
#
# Bug: a track that lived across N daily handoff docs in the SAME (track_id,
# owner_container) accumulates N rows in ``tracks[]`` — one per git ls-tree
# hit. Every OLD row's frontmatter was frozen at write time (``status:
# active``); only the newest row for that (track_id, owner_container) is ever
# rewritten to a terminal status when the track closes. ``lib/collision.py``'s
# ``classify()`` groups candidates by ``track_id`` ONLY (not by
# owner_container) and treats every non-terminal row as an active candidate,
# so the frozen-active historical rows outlive the real close forever — the
# track never stops looking like it collides.
#
# Fix: before calling ``classify()``, collapse ``tracks`` to one row per
# (track_id, owner/container) — dropping the session segment (round 3,
# finding [m] — see dedupe_latest_per_track_container's own docstring for
# why session must not participate in the grouping key) — the row that sorts
# greatest under the four-level key below wins — and feed ONLY that deduped
# view to classification. ``tracks_multibranch.tracks[]`` itself is never
# touched (schema-additive; see module docstring).
#
# Public function (round 2, post-review): ``dedupe_latest_per_track_container``
# is deliberately PUBLIC (not a module-private ``_`` helper) — it is imported
# verbatim by ``renderers/track_board.py`` so the board's COLLISION lines and
# this collector's persisted ``collision.groups`` are computed from the exact
# same deduped view of the exact same snapshot (round-1 review minor finding:
# the renderer used to recompute collidability off the raw, undeduped
# ``tracks[]``, so it could still show a phantom COLLISION line for a track
# this collector had already stopped flagging).
#
# Tie-break, finalized (round 3): the sort key is FOUR levels, all
# comparable, fully deterministic —
# ``(parse_ok, parsed_updated_at, filename, branch)``.
#
# Level 2 filename (round 2, major finding a): round 1's sort key was
# ``(parse_ok, parsed_datetime)`` only. When two rows in the same group parse
# to the IDENTICAL instant — the real-world case that surfaced this: this
# project's own ``docs/handoff/`` has produced same-track same-container rows
# that both stamp date-only ``updated_at: 2026-07-19`` (no time-of-day, so
# both parse to that day's 00:00) — ``max()`` breaks the tie by keeping
# whichever row it saw FIRST while iterating (Python's ``max()`` never
# replaces the running max on a "not strictly greater" comparison). Row order
# is ``git ls-tree``'s alphabetical listing order, an accident of iteration,
# not a meaningful "which one is actually later" signal — and it picked the
# wrong row against this repo's own real data. **Filename, dictionary order,
# MAX wins**: handoff filenames are ``YYYY-MM-DD-...``-prefixed, so the
# lexicographically greater filename among same-instant rows is also the
# later-authored one in every observed case.
#
# Level 3 branch (round 3, finding [M1]): filename alone still under-
# determines the mainline multi-branch shape — the SAME handoff file (same
# track_id, same owner_container, same updated_at, same filename byte-for-
# byte) reachable from MULTIPLE branches that share it via a common ancestor.
# On that exact 3-way tie, round 2's key again silently fell back to
# ``max()``'s "first seen while iterating" — ``branches`` scan order
# (committerdate desc), an accidental value with respect to this decision,
# not a "which copy is canonical" signal. **Branch name, dictionary order,
# MAX wins** removes the last iteration-order dependency: the winning row is
# now a pure function of the candidate rows' own field values, invariant to
# the order ``tracks`` is built/passed in (see
# ``TestDedupeTiebreakByBranchWhenUpdatedAtAndFilenameTie`` — reversing the
# input list yields the identical winner).


def _updated_at_sort_key(updated_at: str | None) -> tuple[int, datetime]:
    """Parse-success/value sort key for one row's ``updated_at``.

    Successfully-parsed ISO 8601 timestamps (including date-only strings,
    e.g. ``"2026-07-19"`` — ``datetime.fromisoformat`` treats a bare date as
    that day's 00:00) sort by their real value. Anything that fails to parse
    (missing, malformed, e.g. the literal ``"corrupt-not-a-date"``) sorts in
    a strictly lower priority bucket, so it can NEVER win the "latest" slot —
    even though as a raw string it may be lexicographically greater than
    every real ISO-8601 timestamp (``"c" > "2"``), which is exactly the
    naive-``max(str)`` bug this guards against.

    This is the first two components of ``_dedupe_sort_key`` below; kept as
    its own function purely for separation of concerns (parse-and-bucket one
    field vs. build the full compound tie-break key).
    """
    raw = (updated_at or "").strip()
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (1, dt)
    except (ValueError, AttributeError):
        return (0, datetime.min.replace(tzinfo=timezone.utc))


def _dedupe_sort_key(row: dict) -> tuple[int, datetime, str, str]:
    """Full dedupe "latest wins" sort key: four levels, all-comparable,
    fully deterministic — ``(parse_ok, updated_at, filename, branch)``.

    ``filename`` is the round-2 tie-break (see the module-comment block above
    for the real-data motivation): when two rows in a group parse to the
    identical ``updated_at`` instant, the row whose ``filename`` is
    dictionary-order GREATEST wins, never "whichever the group happened to
    iterate first".

    ``branch`` is the round-3 4th level (M1): the mainline multi-branch-scan
    shape is the SAME handoff file (identical content — same track_id, same
    owner_container, same ``updated_at``, same filename) reachable from
    MULTIPLE branches (a shared ancestor commit before the branches diverged
    — an ordinary occurrence, not an edge case, once ``branches_scanned`` > 1
    for any project with more than one long-lived branch). On that exact
    3-way tie (dt AND filename identical), the round-2 key still fell back to
    ``max()``'s "keep whichever row it saw first while iterating" — i.e.
    ``branches`` list order (``git for-each-ref --sort=-committerdate``,
    itself the accidental-relative-to-this-decision committerdate of
    whichever branch tip happens to sort first), not a real "which copy is
    canonical" signal. ``branch`` name (plain string comparison, dictionary-
    max wins) makes the pick depend only on the row's OWN fields — invariant
    to `tracks[]`'s build order regardless of branch scan order or list
    reversal.
    """
    bucket, dt = _updated_at_sort_key(row.get("updated_at"))
    return (bucket, dt, row.get("filename") or "", row.get("branch") or "")


def dedupe_latest_per_track_container(
    tracks: list[dict],
) -> tuple[list[dict], dict]:
    """Collapse historical rows to one-per-``(track_id, owner/container)`` before
    collision classification.

    Groups ``tracks`` by ``(track_id, owner, container)`` — the OWNER and
    CONTAINER segments only, taken via ``lib.collision.split_owner_container``
    (round 3, finding [m]; read-only import, ``lib/collision.py`` itself is
    NOT modified). Segment convention is the lib's, not ours: a 3-segment
    ``owner/container/session`` splits as named; a 2-segment ``a/b`` splits as
    ``(owner='', container='a', session='b')`` (i.e. the lib treats the 2nd
    segment as the session), so 2-segment handoff values group by their FIRST
    segment only — identical to how ``classify()`` partitions claims, which is
    what keeps this view and the classification consistent. The SESSION
    segment deliberately does NOT participate in the grouping key: two historical rows for the same track that differ only
    by session are still the SAME physical container's history over time —
    e.g. an old ``status: active`` row from session ``s1`` and a newer
    ``status: done`` row from session ``s2`` in the identical
    ``owner/container`` are the SAME container closing out, not two
    containers. Grouping by the full raw ``owner_container`` string (round 1
    and round 2's key) left such session-differing rows in SEPARATE
    dedupe-of-one groups, so the stale ``active`` row never got superseded by
    its own container's later ``done`` row and could still manufacture a
    false-positive collision against a genuinely different container
    elsewhere (same bug shape as the original #155 report, one dimension
    over). Falls back to the RAW ``owner_container`` string as the grouping
    key (round 1/2 behaviour) only if the ``lib.collision`` import itself is
    unavailable (``_split_owner_container is None`` — fail-soft, matches
    ``_COLLISION_AVAILABLE`` elsewhere in this module; this function is never
    gated behind that flag since round-2 tests call it directly).

    Keeps only the row that sorts greatest under ``_dedupe_sort_key`` —
    updated_at-latest, ties broken by dictionary-max filename, then
    dictionary-max branch (see module comment above ``_dedupe_sort_key``).
    ``status == "legacy"`` rows pass through UNCHANGED, un-grouped: a legacy
    track_id already embeds branch+filename (``legacy:<branch>:<filename>``),
    so two legacy rows can never share a dedupe key with each other or with a
    real track, and every legacy row's ``owner_container`` is ``"unknown"``
    — which ``classify()`` already excludes from collision attribution
    regardless — so this choice has no observable effect on the
    classification result either way.

    This is a read-only view built for classification input ONLY; the
    persisted ``tracks_multibranch.tracks[]`` snapshot is never mutated or
    replaced (it intentionally retains full, undeduped history).

    Returns ``(deduped, stats)``:
        deduped: the deduped list (order is not significant — ``classify()``
            sorts internally by track_id and by owner_container within each
            group).
        stats:   ``{"input_tracks": int, "after_dedupe": int,
                  "legacy_passthrough": int}`` — ``input_tracks``/
                  ``after_dedupe`` count ONLY the non-legacy (real,
                  dedupe-eligible) rows; ``legacy_passthrough`` is the count
                  of ``status == "legacy"`` rows, which never fold (round 2
                  finding: round 1's counts folded legacy rows into
                  ``input_tracks``/``after_dedupe``, which both over-counted
                  "how many rows this dedupe pass actually touched" and left
                  the mixed accounting undocumented).
    """
    groups: dict[tuple, list[dict]] = {}
    legacy: list[dict] = []
    for t in tracks:
        if t.get("status") == "legacy":
            legacy.append(t)
            continue
        if _split_owner_container is not None and _identity_key is not None:
            # owner-container-identity-key SC-4: key on identity_key so the same
            # uuid container under two git identities (Aria #193 drift) folds
            # to its newest row; hostname containers keep the owner segment.
            owner, container, _session = _split_owner_container(
                t.get("owner_container") or ""
            )
            key = (t.get("track_id"), _identity_key(owner, container))
        else:
            # Fail-soft fallback (lib.collision unavailable): raw string,
            # round 1/2 behaviour — session segment still participates, so
            # the [m] fold is not applied, but grouping remains well-defined.
            key = (t.get("track_id"), t.get("owner_container"))
        groups.setdefault(key, []).append(t)

    deduped: list[dict] = [
        max(rows, key=_dedupe_sort_key) for rows in groups.values()
    ]
    input_nonlegacy = sum(len(rows) for rows in groups.values())
    stats = {
        "input_tracks": input_nonlegacy,
        "after_dedupe": len(deduped),
        "legacy_passthrough": len(legacy),
    }
    deduped.extend(legacy)
    return deduped, stats


# ── Public entry point ────────────────────────────────────────────────────────


def collect_handoff_multibranch(  # noqa: C901 — linear collector, kept in one place on purpose

    project_root: Path,
    remote: str = _REMOTE,
    now: Optional[datetime] = None,  # owner-container-identity-key: Layer H window reference (tests pin it)
) -> CollectorResult:
    """Scan all remote branches for handoff docs and rebuild the track list.

    Args:
        project_root: Absolute path to the project root (passed by scan.py).
        remote:       git remote name (default: "origin"; injectable for tests).

    Returns a CollectorResult whose ``.data`` dict matches the
    ``tracks_multibranch`` schema documented in the module docstring.
    Never raises — all errors are accumulated via ``r.errors`` and the
    per-track ``errors`` list in the returned data.
    """
    r = CollectorResult()
    error_messages: list[str] = []

    # Resolve the scan cap (env > config > default 20; #71 v1.38.0). Resolved
    # once per run so the value is stable across the cap check + soft_error text.
    max_branches = resolve_max_branches_scanned(project_root)

    # PyYAML probe removed in v1.30.2 — parse_handoff_frontmatter now uses a
    # stdlib parser (fix for Forgejo aria-plugin #57 Finding 2). Frontmatter
    # parsing no longer requires any external dep.

    # ── Enumerate remote branches ─────────────────────────────────────────────
    branches, list_err = _list_origin_branches(project_root)
    if list_err is not None:
        r.soft_error("handoff_multibranch_branch_list_failed", list_err)
        r.data = {
            "exists": False,
            "tracks": [],
            "branches_scanned": 0,
            "legacy_count": 0,
            "collision": {"kind": "none", "groups": [], "identity_advisories": []},
            "errors": [list_err],
        }
        return r

    # Performance cap: only scan first `max_branches` branches (resolved above).
    # Branches are pre-sorted by committerdate desc (most-recent first) by
    # _list_origin_branches. Cap keeps active over stale.
    if len(branches) > max_branches:
        capped_msg = (
            f"Remote branch count ({len(branches)}) exceeds cap "
            f"({max_branches}); scanning only the first "
            f"{max_branches} branches (most-recent by committerdate)."
        )
        r.soft_error("handoff_multibranch_branch_cap", capped_msg)
        error_messages.append(capped_msg)
        log.warning("handoff_multibranch: %s", capped_msg)
        branches = branches[:max_branches]

    # ── Scan each branch ──────────────────────────────────────────────────────
    tracks: list[dict] = []
    legacy_count: int = 0
    branches_scanned: int = 0

    for branch in branches:
        # List handoff files on this branch
        filenames, ls_err = _list_handoff_files(project_root, branch)
        if ls_err is not None:
            msg = f"[{branch}] {ls_err}"
            error_messages.append(msg)
            r.soft_error("handoff_multibranch_ls_tree_failed", msg)
            # Continue scanning other branches
            branches_scanned += 1
            continue

        if not filenames:
            # Branch has no docs/handoff/ tree or only latest.md — silently skip.
            branches_scanned += 1
            continue

        branches_scanned += 1

        for filename in filenames:
            # Read file content via git show
            content, show_err = _read_file_content(project_root, branch, filename)

            if show_err is not None or content is None:
                # git show failed: mark as legacy + soft_error
                msg = f"[{branch}/{filename}] git show failed: {show_err or 'empty content'}"
                error_messages.append(msg)
                r.soft_error("handoff_multibranch_git_show_failed", msg)
                fallback_date = _get_file_commit_date(project_root, branch, filename)
                tracks.append(
                    {
                        "track_id": _make_legacy_track_id(branch, filename),
                        "owner_container": "unknown",
                        "phase": "unknown",
                        "status": "legacy",
                        "updated_at": fallback_date,
                        "branch": branch,
                        "filename": filename,
                        "legacy": True,
                    }
                )
                legacy_count += 1
                continue

            # Attempt frontmatter parse (stdlib parser since v1.30.2, no external dep)
            fm = parse_handoff_frontmatter(content)

            if fm is not None:
                # Well-formed frontmatter: emit as a first-class track row.
                tracks.append(
                    {
                        "track_id": fm["track-id"],
                        "owner_container": fm["owner-container"],
                        "phase": fm["phase"],
                        "status": fm["status"],
                        "updated_at": fm["updated-at"],
                        "branch": branch,
                        "filename": filename,
                        "legacy": False,
                    }
                )
                log.debug(
                    "handoff_multibranch: parsed track '%s' on branch '%s'",
                    fm["track-id"],
                    branch,
                )
            else:
                # No frontmatter or incomplete schema: legacy fallback per §2.3.4.
                # updated_at = git log committer date (superior to local mtime for
                # cross-branch files where mtime is not stable).
                fallback_date = _get_file_commit_date(project_root, branch, filename)
                tracks.append(
                    {
                        "track_id": _make_legacy_track_id(branch, filename),
                        "owner_container": "unknown",
                        "phase": "unknown",
                        "status": "legacy",
                        "updated_at": fallback_date,
                        "branch": branch,
                        "filename": filename,
                        "legacy": True,
                    }
                )
                legacy_count += 1
                log.debug(
                    "handoff_multibranch: legacy fallback for '%s' on branch '%s' "
                    "(no frontmatter or incomplete schema)",
                    filename,
                    branch,
                )

    # Collision summary (TASK-000, #133) — additive, advisory-only.
    # Built from the lossy track->ClaimRecord approximation via lib.collision;
    # MUST NOT be used as a gating input downstream (DEC-20260519-001).
    # Fail-soft: if lib import was unavailable, degrade to "none" rather than
    # raising (collision is an advisory surface, never load-bearing).
    if _COLLISION_AVAILABLE:
        try:
            # aria-plugin#155: collapse to one row per (track_id,
            # owner/container — session segment dropped, round 3 finding [m])
            # — newest updated_at wins (filename then branch dictionary-max
            # tie-break, rounds 2/3) — BEFORE classifying, so stale
            # historical "active" rows from an already-closed track can no
            # longer manufacture a permanent self_multi_container/cross_owner
            # false positive. tracks[] itself is untouched.
            deduped_tracks, dedupe_stats = dedupe_latest_per_track_container(tracks)
            # owner-container-identity-key D-3(a): drop Layer H rows older than
            # LAYER_H_ACTIVE_WINDOW_DAYS (single implementation in lib/collision)
            # AFTER dedupe (stats stay calendar-independent) and BEFORE classify,
            # so 2026-05..07 residue can no longer manufacture a permanent group.
            fresh_tracks = _filter_layer_h_fresh(deduped_tracks, now=now)
            collision = _classify_collision_summary(fresh_tracks, now=now)
            # ⚪ same-identity-multi-owner advisory (D3): computed on the RAW
            # rows — BEFORE dedupe, which folds exactly the rows it must see.
            # Always present (additive, [] when no drift) — SC-8.
            collision["identity_advisories"] = _identity_drift_advisories(tracks)
            if dedupe_stats["after_dedupe"] < dedupe_stats["input_tracks"]:
                # Additive audit field — only present when deduping actually
                # collapsed >=1 NON-legacy row, so a snapshot with no
                # historical accumulation keeps the pre-#155 {"kind",
                # "groups"} shape byte-for-byte (test_collision.py pins exact
                # equality there). Round 2: counts exclude legacy rows (which
                # never fold) — see dedupe_latest_per_track_container's
                # docstring for why round 1's mixed accounting was wrong.
                collision["dedupe"] = dedupe_stats
        except Exception as exc:  # noqa: BLE001 — advisory field never breaks scan
            collision = {"kind": "none", "groups": [], "identity_advisories": []}
            error_messages.append(f"collision classify failed (degraded to none): {exc}")
    else:
        collision = {"kind": "none", "groups": [], "identity_advisories": []}

    r.data = {
        "exists": len(tracks) > 0,
        "tracks": tracks,
        "branches_scanned": branches_scanned,
        "legacy_count": legacy_count,
        "collision": collision,
        "errors": error_messages,
    }
    return r

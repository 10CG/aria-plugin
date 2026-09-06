"""Tests — aria-plugin#155: ``tracks_multibranch.collision`` false-positive
``self_multi_container`` from a track's STALE historical handoff frontmatter,
permanently mis-flagging an already-closed track as colliding.

Bug (from the issue, reproduced against this repo's own snapshot too): a
track that lived across N daily handoff docs in the SAME (track_id,
owner_container) accumulates N rows in ``tracks_multibranch.tracks[]`` — one
per ``git ls-tree`` hit under ``docs/handoff/``. Every OLD row's frontmatter
was frozen at write time (``status: active``) and is never rewritten when the
track later closes; only the newest row for that (track_id, owner_container)
ever says ``status: done``. ``lib/collision.py``'s ``classify()`` groups
candidates by ``track_id`` ONLY (not by owner_container) and keeps every
non-terminal row as an "active candidate" (reconcile's losers/yielders stay
active, they just don't "win"), so those frozen-``active`` historical rows
outlive the close forever — the track never stops looking like it collides,
even though the real, current state per container is exactly one active
container (no collision at all).

Status: round 1 (GREEN) landed the fix as a private
``_dedupe_tracks_for_collision`` helper in ``collect_handoff_multibranch``.
This file is now round 2 (post-review) — the reviewer found the round-1
fix under-tested in two ways this file now closes, plus a divergence in a
file this test file does NOT own:

  (a) MAJOR — round 1's dedupe "latest wins" sort key was
      ``(parse_ok, parsed updated_at)`` only. On a real tie (this repo's own
      data: two rows for the same track+container both stamp date-only
      ``updated_at: 2026-07-19``), ``max()`` silently fell back to
      whichever row it iterated FIRST — ``git ls-tree`` alphabetical order,
      an accident, not a real "latest" signal — and picked the WRONG row.
      The finalized tie-break is filename, dictionary order, MAX wins (see
      ``TestDedupeTiebreakByFilenameWhenUpdatedAtTies`` below).
  (b) MAJOR — the original TC5 (corrupt ``updated_at``) asserted only
      ``collision["kind"]``, which gave it ZERO rejection power: a naive
      "raw string ``max()``" bad implementation ALSO lands on
      ``kind="none"`` for that fixture (the wrongly-selected corrupt row
      fails ISO-8601 validation downstream inside ``classify()`` and gets
      fail-soft SKIPPED there, coincidentally leaving the same single active
      claim a correct implementation would). Fixed by asserting directly on
      which row ``dedupe_latest_per_track_container`` (now PUBLIC — see
      below) selected (see
      ``TestDedupeUnparseableUpdatedAtSortsLastNotFirst``).

The fix (finalized design, round 2): ``dedupe_latest_per_track_container`` is
a PUBLIC function (not `_`-prefixed) in ``handoff_multibranch.py``, signature
``(tracks) -> (deduped, stats)``. It groups ``tracks`` by
``(track_id, owner_container)`` and keeps only the row that sorts greatest
under ``(parse_ok, parsed updated_at, filename)`` — unparseable
``updated_at`` sorts LAST (never wins) and same-instant ties resolve to the
dictionary-max filename. ``status == "legacy"`` rows pass through un-grouped
(their track_id already embeds branch+filename so they can never collide
with a real group anyway). Only the deduped list is fed to
``_classify_collision_summary``; ``tracks_multibranch.tracks[]`` itself
stays the untouched full history (additive fix, not a schema break). The
additive audit key ``tracks_multibranch.collision.dedupe`` records
``{"input_tracks": N, "after_dedupe": M, "legacy_passthrough": L}`` — N/M
count non-legacy rows only (round 2: round 1 mixed legacy rows into these
counts undocumented).

``renderers/track_board.py`` (round 2, NOT owned by this test file's original
scope but exercised here read-only via its public ``render_track_board``)
now imports this same ``dedupe_latest_per_track_container`` and applies it
before computing its own COLLISION lines, so the board and the collector's
persisted ``collision`` summary can never diverge on the same snapshot — see
``TestBoardAndCollectorAgreeOnCollisionCount`` below.

Round 3 (second post-review) closes two further findings, both against
``dedupe_latest_per_track_container`` itself (``renderers/track_board.py``
needs no further change — it imports that function verbatim, so it inherits
both fixes automatically):

  [M1] MAJOR — round 2's sort key, ``(parse_ok, parsed updated_at,
      filename)``, is still under-determined on the multi-branch scan's
      MAINLINE shape: the SAME handoff file (identical track_id,
      owner_container, updated_at, AND filename — byte-for-byte the same
      content) reachable from MULTIPLE branches sharing a common ancestor.
      On that exact 3-way tie, ``max()`` again silently fell back to
      whichever row it saw FIRST while iterating ``tracks`` — branch-scan
      order (``git for-each-ref --sort=-committerdate``), an accidental
      value with respect to this decision. Fixed by adding ``branch``
      (dictionary-max) as a 4th, fully-deterministic tie-break level:
      ``(parse_ok, parsed updated_at, filename, branch)``. See
      ``TestDedupeTiebreakByBranchWhenUpdatedAtAndFilenameTie`` below —
      it asserts the winner is IDENTICAL whether the input list is fed
      forward or reversed.
  [m] minor — the dedupe grouping key was the RAW ``owner_container``
      string (all 3 segments: owner/container/session), so two historical
      rows for the same track and the same physical container that differ
      only by SESSION (e.g. an old ``status: active`` row from session
      ``s1``, a newer ``status: done`` row from session ``s2``, same
      ``owner/container``) never collapsed into one representative — each
      survived as its own dedupe-of-one group, so the stale ``active`` s1
      row could still count as a live candidate downstream even though its
      own container had already moved on. Fixed by grouping on
      ``(track_id, owner, container)`` via
      ``lib.collision.split_owner_container`` (read-only import — that
      module is owned by a different in-flight container fixing #134, and
      remains untouched here), dropping the session segment from the key.
      See ``TestDedupeFoldsAcrossSessionsWithinSameContainer`` below.

SCOPE FENCES for this file (unchanged from round 1, still binding):
  * Does not import, call, or assert against ``lib/collision.py`` directly —
    that module is owned by a different, concurrently in-flight container
    fixing a separate bug (#134); this file only observes its behavior
    indirectly through the collector's (and, for the new board-agreement
    tests, the renderer's) persisted/rendered output.
  * Editable files for this task: ``collectors/handoff_multibranch.py``,
    ``renderers/track_board.py``, THIS file, and the
    ``tracks_multibranch.collision`` section of
    ``references/state-snapshot-schema.md`` — nothing else.

Run:
    cd .../state-scanner/tests
    python3 -m pytest -q -p no:cacheprovider test_handoff_multibranch_collision_dedupe.py
    python3 run_tests.py handoff_multibranch_collision_dedupe

Spec: aria-plugin#155
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

# ── Ensure collectors (and renderers) packages are importable ──────────────
# Ordering matters (aria-plugin#134, see test_collision.py's header comment):
# state-scanner/ has TWO `lib` packages — `lib/` (has collision.py) and
# `scripts/lib/` (does not). handoff_multibranch.py's own guarded import
# (`from lib.collision import classify`) resolves whichever `lib` sys.path
# finds FIRST. Under a single-module pytest run, tests/__init__.py makes
# pytest prepend the state-scanner root to sys.path itself; naively then
# inserting scripts/ at position 0 (as a plain "make collectors importable"
# snippet would) pushes that root behind scripts/ and silently rebinds `lib`
# to the wrong (collision.py-less) package -> handoff_multibranch.py's import
# raises ImportError -> _COLLISION_AVAILABLE=False -> collision degrades to
# "none" for EVERY scenario, which would make every "expected none" test in
# this file pass for the wrong reason and mask the real bug. Mirroring
# test_collision.py's own fix: root goes to the FRONT, scripts/ to the END.
#
# Round 2 addition: this file now also imports renderers.track_board (for
# TestBoardAndCollectorAgreeOnCollisionCount). track_board.py's OWN internal
# sys.path fallback inserts scripts/ AHEAD of the state-scanner root (the
# very ordering bug this comment warns about) — but by the time that code
# runs, `sys.modules['lib']` is already bound correctly below (we import
# collectors.handoff_multibranch FIRST, which binds it), so track_board's
# subsequent `from lib.constants import ...` etc. reuse the already-correct
# binding regardless of its own sys.path order. Import order below
# (collectors, then renderers) is therefore load-bearing — do not reorder.
_TESTS_DIR = Path(__file__).resolve().parent
_SS_ROOT = _TESTS_DIR.parent
if str(_SS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SS_ROOT))
_SCRIPTS_DIR = _SS_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.append(str(_SCRIPTS_DIR))

from collectors.handoff_multibranch import (  # noqa: E402
    collect_handoff_multibranch,
    dedupe_latest_per_track_container,
)
from renderers.track_board import render_track_board  # noqa: E402

# Fixed reference "now" for render_track_board determinism (freshness emoji /
# LAST-PING are irrelevant to the assertions below, which only count
# "⚠ COLLISION" lines, but a fixed now keeps output fully reproducible).
_FIXED_NOW = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)

# ── Deterministic git identity, isolated from host config (Rule #7: capture_output) ──
_GIT_ENV = {
    **os.environ,
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}


def _git(cwd: str, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env=_GIT_ENV)


def _frontmatter(track_id: str, oc: str, status: str, updated_at: str, phase: str = "B.2") -> str:
    """Build a well-formed 5-field §2.3.1 handoff frontmatter block.

    ``updated_at`` is written verbatim (no validation at parse time — see
    ``collectors/handoff.py::parse_handoff_frontmatter``), which is what lets
    TC5 below plant a deliberately unparseable value.
    """
    return (
        "---\n"
        f"track-id: {track_id}\n"
        f"owner-container: {oc}\n"
        f"phase: {phase}\n"
        f"status: {status}\n"
        f"updated-at: {updated_at}\n"
        "---\n\n# Aria — Session Handoff\n"
    )


def _build_repo(tmp: str, files: "list[tuple[str, str, str, str, str]]") -> Path:
    """Commit every ``(filename, track_id, owner_container, status, updated_at)``
    row from ``files`` into ONE commit under ``docs/handoff/``, then publish
    that commit to ``refs/remotes/origin/<default-branch>`` — no real remote
    needed, since ``collect_handoff_multibranch`` only reads
    ``refs/remotes/origin/*`` refs (same technique as
    ``test_collision.py::_build_multibranch_repo`` and
    ``test_p1_layer_h.py::_build_local_repo_with_remote_branches``).

    All rows land on a single branch tip deliberately: ``owner_container``
    (frontmatter), not the git branch, is what drives collision grouping —
    real repos also frequently accumulate many historical
    ``docs/handoff/*.md`` files together on one branch over time.
    """
    root = Path(tmp)
    _git(tmp, "init", "-q")
    handoff_dir = root / "docs" / "handoff"
    handoff_dir.mkdir(parents=True, exist_ok=True)
    for filename, track_id, oc, status, updated_at in files:
        (handoff_dir / filename).write_text(
            _frontmatter(track_id, oc, status, updated_at), encoding="utf-8"
        )
        _git(tmp, "add", f"docs/handoff/{filename}")
    _git(tmp, "commit", "-q", "-m", "handoffs")
    default_branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=tmp, check=True, capture_output=True, text=True, env=_GIT_ENV,
    ).stdout.strip()
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp, check=True, capture_output=True, text=True, env=_GIT_ENV,
    ).stdout.strip()
    _git(tmp, "update-ref", f"refs/remotes/origin/{default_branch}", sha)
    return root


class TestSelfMultiContainerFalsePositiveFromStaleHistory(unittest.TestCase):
    """Faithful reproduction of the issue's own real-world snapshot: a track
    with 3 STALE ``status: active`` historical handoffs plus a 4th, newest,
    ``status: done`` row — all in ONE (track_id, owner_container) — alongside
    exactly ONE still-genuinely-active row in a second owner_container.
    """

    def test_stale_active_history_no_longer_manufactures_a_collision(self):
        """RED reason: ``collision["kind"]`` currently comes back
        ``"self_multi_container"`` (asserted "none"). ``classify()`` groups
        candidates by track_id only, so the 3 frozen ``status: active``
        historical rows for ``aria-runner-bot/023236f2`` outlive that row's
        real close (the 4th, newest, ``done`` row) and keep the container set
        at 2 (``{aria-runner-bot, simonfish}``) forever. After the collector
        dedupes to one row per (track_id, owner_container) — keeping only the
        ``updated_at``-latest — ``aria-runner-bot``'s sole surviving row is
        ``done`` and ``simonfish``'s sole row is ``active``: only ONE
        container is genuinely active for this track, so ``kind`` must be
        ``"none"``.
        """
        track_id = "customer-data-controls-cache-transparency"
        files = [
            ("2026-08-02-t1.md", track_id, "aria-runner-bot/023236f2", "active", "2026-08-02T09:00:00Z"),
            ("2026-08-10-t1.md", track_id, "aria-runner-bot/023236f2", "active", "2026-08-10T09:00:00Z"),
            ("2026-08-16-t1.md", track_id, "aria-runner-bot/023236f2", "active", "2026-08-16T09:00:00Z"),
            ("2026-08-20-t1.md", track_id, "aria-runner-bot/023236f2", "done", "2026-08-20T09:00:00Z"),
            ("2026-08-18-t1-other.md", track_id, "simonfish/bfe8285d", "active", "2026-08-18T09:00:00Z"),
        ]
        with tempfile.TemporaryDirectory(prefix="ss-c155-t1-") as tmp:
            root = _build_repo(tmp, files)
            result = collect_handoff_multibranch(root)
            data = result.data

            # Schema-additive contract pin: the fix must dedupe only what is
            # FED to classify(), never the persisted tracks[] snapshot itself
            # (this line passes today — no dedup happens anywhere yet — and
            # must keep passing after the fix; it is here so a GREEN
            # implementation that collapses tracks[] itself gets caught).
            self.assertEqual(
                len(data["tracks"]), 5,
                "tracks_multibranch.tracks[] must retain the full, undeduped "
                "history (additive fix) — dedup is scoped to collision "
                "classification input only",
            )

            coll = data["collision"]
            self.assertEqual(
                coll["kind"],
                "none",
                f"expected no collision (own container's latest handoff is "
                f"done; the other container's single handoff is active, so "
                f"only one container is genuinely active) — got {coll!r}",
            )


class TestSelfMultiContainerRealCollisionSurvivesDedupe(unittest.TestCase):
    """Negative control (over-fix guard): BOTH containers' latest handoff is
    still ``active`` — a genuine, ongoing collision. Deduping history down to
    one row per (track_id, owner_container) must NOT erase it.
    """

    def test_both_latest_active_still_reports_self_multi_container(self):
        """Pins the additive audit key
        ``tracks_multibranch.collision.dedupe`` (``{"input_tracks",
        "after_dedupe", "legacy_passthrough"}`` — round 2: counts are
        non-legacy rows only, ``legacy_passthrough`` records the (here: 0)
        legacy rows separately). The exact counts and the preserved
        ``"self_multi_container"`` kind are asserted so the fix is pinned to
        more than just "the key exists".
        """
        track_id = "twin-track"
        files = [
            ("2026-08-02-t2a.md", track_id, "aria-runner-bot/023236f2", "active", "2026-08-02T09:00:00Z"),
            ("2026-08-10-t2a.md", track_id, "aria-runner-bot/023236f2", "active", "2026-08-10T09:00:00Z"),
            ("2026-08-20-t2a.md", track_id, "aria-runner-bot/023236f2", "active", "2026-08-20T09:00:00Z"),
            ("2026-08-05-t2b.md", track_id, "simonfish/bfe8285d", "active", "2026-08-05T09:00:00Z"),
            ("2026-08-12-t2b.md", track_id, "simonfish/bfe8285d", "active", "2026-08-12T09:00:00Z"),
            ("2026-08-19-t2b.md", track_id, "simonfish/bfe8285d", "active", "2026-08-19T09:00:00Z"),
        ]
        with tempfile.TemporaryDirectory(prefix="ss-c155-t2-") as tmp:
            root = _build_repo(tmp, files)
            result = collect_handoff_multibranch(root)
            coll = result.data["collision"]

            self.assertIn(
                "dedupe", coll,
                "tracks_multibranch.collision.dedupe (additive audit field) "
                "is missing from the collector's output",
            )
            self.assertEqual(
                coll["dedupe"],
                {"input_tracks": 6, "after_dedupe": 2, "legacy_passthrough": 0},
                f"expected 6 raw rows collapsed to 2 (one per container) — got {coll['dedupe']!r}",
            )
            # SC-4 (owner-container-identity-key TASK-003): the two rows are TWO
            # commit identities on TWO uuid containers (aria-runner-bot vs
            # simonfish) -> cross_owner under the two-part §2.3.5 reading.
            # How it goes red on 7dd0135: self_multi_container (3-part parser
            # drops the owner segment, both owners collapse to "unknown").
            self.assertEqual(
                coll["kind"],
                "cross_owner",
                "both containers' LATEST handoff is still status=active and the "
                f"two owner strings differ — real cross-owner collision; got {coll!r}",
            )

    def test_both_latest_active_same_owner_is_self_multi_container(self):
        """Same-owner variant of the fixture above: ``simonfish`` on two uuid
        containers -> self_multi_container (one attributable owner, two
        identity_keys)."""
        track_id = "twin-track"
        files = [
            ("2026-08-20-t2a.md", track_id, "simonfish/023236f2", "active", "2026-08-20T09:00:00Z"),
            ("2026-08-19-t2b.md", track_id, "simonfish/bfe8285d", "active", "2026-08-19T09:00:00Z"),
        ]
        with tempfile.TemporaryDirectory(prefix="ss-ick-t2s-") as tmp:
            root = _build_repo(tmp, files)
            coll = collect_handoff_multibranch(root).data["collision"]
            self.assertEqual(coll["kind"], "self_multi_container", coll)
            self.assertEqual(coll["groups"], [["simonfish/023236f2", "simonfish/bfe8285d"]], coll)


class TestCrossOwnerRealCollisionSurvivesDedupe(unittest.TestCase):
    """Negative control #2: same guard, but for the more severe
    ``cross_owner`` kind (different OWNERS, not just different containers
    under the same owner) — dedup must not accidentally downgrade or erase
    this either.
    """

    def test_both_latest_active_different_owners_still_reports_cross_owner(self):
        """Same shape as the self_multi_container negative control. The
        exact counts (3 raw rows -> 2 deduped, 0 legacy) and the preserved
        ``"cross_owner"`` kind are pinned.
        """
        track_id = "cross-track"
        files = [
            ("2026-08-02-t3a.md", track_id, "alice/box-A/s1", "active", "2026-08-02T09:00:00Z"),
            ("2026-08-15-t3a.md", track_id, "alice/box-A/s1", "active", "2026-08-15T09:00:00Z"),
            ("2026-08-10-t3b.md", track_id, "bob/box-B/s2", "active", "2026-08-10T09:00:00Z"),
        ]
        with tempfile.TemporaryDirectory(prefix="ss-c155-t3-") as tmp:
            root = _build_repo(tmp, files)
            result = collect_handoff_multibranch(root)
            coll = result.data["collision"]

            self.assertIn(
                "dedupe", coll,
                "tracks_multibranch.collision.dedupe (additive audit field) "
                "is missing from the collector's output",
            )
            self.assertEqual(
                coll["dedupe"],
                {"input_tracks": 3, "after_dedupe": 2, "legacy_passthrough": 0},
                f"expected 3 raw rows collapsed to 2 (one per owner_container) — got {coll['dedupe']!r}",
            )
            self.assertEqual(
                coll["kind"],
                "cross_owner",
                f"two DIFFERENT owners' latest handoff are both active — must stay cross_owner; got {coll!r}",
            )


class TestDedupeUsesRealTimestampNotListingOrder(unittest.TestCase):
    """Adversarial guard against a plausible-but-wrong GREEN implementation:
    picking "the last row encountered while iterating tracks[]" instead of
    genuinely parsing and comparing ``updated_at``. ``git ls-tree`` (and
    therefore the order ``tracks[]`` is built in) lists files in
    ALPHABETICAL order, which this fixture deliberately makes the OPPOSITE
    of chronological order.
    """

    def test_filename_alphabetical_order_does_not_dictate_the_winner(self):
        """Regression guard: the real-latest row (``aaa-done-newest.md``,
        updated_at 2026-08-20, status done) sorts ALPHABETICALLY FIRST while
        the real-oldest row (``zzz-active-oldest.md``, updated_at
        2026-08-02, status active) sorts alphabetically LAST — i.e. LAST in
        ``git ls-tree``'s (and therefore ``tracks[]``'s) iteration order. A
        dedupe that picks "whichever row comes last while iterating" instead
        of genuinely comparing parsed ``updated_at`` values would keep the
        WRONG (stale, active) row as the container's representative and this
        assertion would fail.
        """
        track_id = "order-trap-track"
        files = [
            ("aaa-done-newest.md", track_id, "aria-runner-bot/023236f2", "done", "2026-08-20T09:00:00Z"),
            ("zzz-active-oldest.md", track_id, "aria-runner-bot/023236f2", "active", "2026-08-02T09:00:00Z"),
            ("mmm-other.md", track_id, "simonfish/bfe8285d", "active", "2026-08-18T09:00:00Z"),
        ]
        with tempfile.TemporaryDirectory(prefix="ss-c155-t4-") as tmp:
            root = _build_repo(tmp, files)
            result = collect_handoff_multibranch(root)
            coll = result.data["collision"]
            self.assertEqual(
                coll["kind"],
                "none",
                f"the genuinely-latest row (by updated_at, not filename order) "
                f"for aria-runner-bot is status=done — expected no collision; got {coll!r}",
            )


class TestDedupeUnparseableUpdatedAtSortsLastNotFirst(unittest.TestCase):
    """Adversarial guard against a plausible-but-wrong implementation:
    picking the "latest" row via raw string comparison of ``updated_at``
    instead of parsing it as ISO 8601. The malformed value used here
    (``"corrupt-not-a-date"``) is lexicographically GREATER than every real
    ISO-8601 timestamp string (``"c" > "2"``), so ``max(rows, key=lambda r:
    r["updated_at"])`` would silently pick the corrupt row as "latest" and
    keep the container wrongly flagged active — exactly what the design
    note's "解析失败的排后" (parse failures sort last) rule exists to prevent.

    Round 2 finding (b): the original version of this test asserted ONLY
    ``coll["kind"]``, which turned out to have ZERO rejection power against
    exactly the bad implementation it names above. A naive raw-string-``max``
    ALSO lands on ``kind="none"`` for this fixture: it wrongly selects the
    corrupt row as "latest" for aria-runner-bot, but that row then fails
    ISO-8601 validation inside ``classify()``'s own
    ``track_to_claim_record()`` and is fail-soft SKIPPED there — leaving
    exactly one (simonfish's) active claim, which ALSO yields
    ``kind="none"``. Fixed below by asserting directly on which row
    ``dedupe_latest_per_track_container`` (now public) actually selected.
    """

    def test_corrupt_updated_at_never_wins_the_latest_slot(self):
        """Also implicitly asserts the collector never raises on a malformed
        ``updated_at`` — a raised exception here would surface as a test
        ERROR, not the assertion failures below, which would itself be
        informative about an unhandled crash in the dedupe path.
        """
        track_id = "malformed-date-track"
        files = [
            ("2026-08-02-valid-active.md", track_id, "aria-runner-bot/023236f2", "active", "2026-08-02T09:00:00Z"),
            ("corrupt-frontmatter-active.md", track_id, "aria-runner-bot/023236f2", "active", "corrupt-not-a-date"),
            ("2026-08-20-valid-done.md", track_id, "aria-runner-bot/023236f2", "done", "2026-08-20T09:00:00Z"),
            ("2026-08-18-other-active.md", track_id, "simonfish/bfe8285d", "active", "2026-08-18T09:00:00Z"),
        ]
        with tempfile.TemporaryDirectory(prefix="ss-c155-t5-") as tmp:
            root = _build_repo(tmp, files)
            result = collect_handoff_multibranch(root)
            data = result.data

            # Real rejection power (round 2 fix): assert directly on which
            # row the dedupe helper selected for the aria-runner-bot group,
            # not just on the downstream (fail-soft-laundered) kind.
            deduped, _stats = dedupe_latest_per_track_container(data["tracks"])
            winner = next(
                row for row in deduped
                if row["track_id"] == track_id
                and row["owner_container"] == "aria-runner-bot/023236f2"
            )
            self.assertEqual(
                winner["filename"],
                "2026-08-20-valid-done.md",
                f"the corrupt-updated_at row must never win the 'latest' "
                f"slot for aria-runner-bot — got {winner['filename']!r} "
                f"(status={winner.get('status')!r})",
            )

            coll = data["collision"]
            self.assertEqual(
                coll["kind"],
                "none",
                f"the true latest (parsed) row for aria-runner-bot is "
                f"status=done — the unparseable-timestamp row must never "
                f"win the 'latest' slot; got {coll!r}",
            )


class TestDedupeTiebreakByFilenameWhenUpdatedAtTies(unittest.TestCase):
    """Round 2 finding (a) — real-repo-shaped regression: this project's own
    ``docs/handoff/`` has produced two same-track same-container handoff
    files that both stamp date-only ``updated_at: 2026-07-19`` (no
    time-of-day) — a genuine tie under ISO-8601 parsing (both parse to that
    day's 00:00). Round 1's dedupe picked the winner via plain
    ``max(rows, key=lambda r: (parse_ok, dt))``: on a tie, Python's ``max()``
    keeps whichever row it saw FIRST while iterating ``rows`` — which for a
    single-branch fixture is ``git ls-tree``'s ALPHABETICAL file order, an
    accident of listing order, not a meaningful "later" signal — and it
    picked the WRONG file against this repo's own real data. The finalized
    tiebreak: filename, dictionary order, MAX wins — handoff filenames are
    ``YYYY-MM-DD-...``-prefixed, so the lexicographically greater name is
    also the later-authored one among same-day files.
    """

    def test_lexicographically_greater_filename_wins_the_tie(self):
        """``...-a.md`` (status active) sorts BEFORE ``...-b.md`` (status
        done) both alphabetically AND in ``git ls-tree``/``tracks[]``
        iteration order — the exact shape that made round 1's plain
        ``(parse_ok, dt)`` key silently pick the FIRST-seen (active, wrong)
        row on a tie. The fixed key must pick ``...-b.md`` (done, the
        dictionary-greater filename) instead. Asserted both directly (which
        row won) and via the downstream collision kind (only one genuinely
        active container should remain).
        """
        track_id = "tiebreak-track"
        files = [
            ("2026-07-19-a.md", track_id, "aria-runner-bot/023236f2", "active", "2026-07-19"),
            ("2026-07-19-b.md", track_id, "aria-runner-bot/023236f2", "done", "2026-07-19"),
            ("2026-07-18-other.md", track_id, "simonfish/bfe8285d", "active", "2026-07-18T09:00:00Z"),
        ]
        with tempfile.TemporaryDirectory(prefix="ss-c155-t6-") as tmp:
            root = _build_repo(tmp, files)
            result = collect_handoff_multibranch(root)
            data = result.data

            deduped, _stats = dedupe_latest_per_track_container(data["tracks"])
            winner = next(
                row for row in deduped
                if row["track_id"] == track_id
                and row["owner_container"] == "aria-runner-bot/023236f2"
            )
            self.assertEqual(
                winner["filename"],
                "2026-07-19-b.md",
                f"tie on date-only updated_at must resolve to the "
                f"lexicographically GREATER filename ('...-b.md'), not "
                f"first-iteration-order '...-a.md' — got {winner['filename']!r}",
            )
            self.assertEqual(winner["status"], "done")

            coll = data["collision"]
            self.assertEqual(
                coll["kind"],
                "none",
                f"the tie-winning row for aria-runner-bot is status=done — "
                f"only ONE genuinely active container remains (simonfish) — "
                f"expected no collision; got {coll!r}",
            )


class TestBoardAndCollectorAgreeOnCollisionCount(unittest.TestCase):
    """Round 2 minor finding: ``renderers/track_board.py`` used to compute
    its "⚠ COLLISION" lines straight off the undeduped
    ``tracks_multibranch.tracks[]`` (its own local ``all_collidable`` filter,
    no dedupe applied) — diverging from the collector's now-deduped
    ``tracks_multibranch.collision.groups`` the moment a track accumulates
    >=2 historical rows per (track_id, owner_container). Fixed by importing
    the SAME ``dedupe_latest_per_track_container`` into the renderer (no
    duplicated logic — see track_board.py's own import block) and applying
    it before building ``all_collidable``.

    Closing the input-dedupe gap alone was NOT sufficient to reach real
    parity: running this fix against THIS repo's own real
    ``tracks_multibranch`` snapshot (the round-2 acceptance check) surfaced
    three further, pre-existing divergences purely inside
    ``_render_collision_lines``/its caller — none of which touch
    ``lib/collision.py`` (owned by a different in-flight container) or
    duplicate its logic:

      1. ClaimRecord construction was one all-or-nothing list comprehension
         — one track anywhere with a malformed field discarded the
         reconcile-based verdict for the WHOLE board, falling back to the
         cruder, status-blind P1 detector. Fixed: per-track try/except,
         mirroring ``classify()``'s own per-item fail-soft loop.
      2. ``active_claims`` never recovered a stale-takeover-demoted winner
         (a claim reconcile moves to ``superseded`` for staleness, not
         because it is genuinely terminal) — ``classify()`` does this
         recovery explicitly and documents why; the renderer's parallel
         construction had silently drifted from it.
      3. The generic ``else`` fallback branch unconditionally rendered a
         COLLISION line whenever ``verdict.yielders`` was non-empty, even
         when ``_classify_collision`` correctly said "none" (e.g.
         same-owner+container "self-serial" claims) — there was no
         explicit ``kind == "none"`` case.

    This test class runs BOTH ``collect_handoff_multibranch`` and
    ``render_track_board`` against the SAME fixture/snapshot and pins their
    COLLISION line counts (and, for the three findings above, the exact
    mechanism) together, so a future re-divergence on any of these four
    fronts fails here rather than only surfacing on the next manual
    real-repo check.
    """

    @staticmethod
    def _collision_line_count(board_text: str) -> int:
        return sum(
            1 for line in board_text.splitlines()
            if line.lstrip().startswith("⚠ COLLISION")
        )

    def test_stale_history_false_positive_produces_zero_board_collision_lines(self):
        """Same fixture as
        ``TestSelfMultiContainerFalsePositiveFromStaleHistory``: the
        collector reports ``kind="none"`` / ``groups=[]`` post-fix — the
        board must show 0 "⚠ COLLISION" lines, not the pre-#155 phantom
        line a renderer still reading raw ``tracks[]`` would show.
        """
        track_id = "customer-data-controls-cache-transparency-board"
        files = [
            ("2026-08-02-b1.md", track_id, "aria-runner-bot/023236f2", "active", "2026-08-02T09:00:00Z"),
            ("2026-08-10-b1.md", track_id, "aria-runner-bot/023236f2", "active", "2026-08-10T09:00:00Z"),
            ("2026-08-16-b1.md", track_id, "aria-runner-bot/023236f2", "active", "2026-08-16T09:00:00Z"),
            ("2026-08-20-b1.md", track_id, "aria-runner-bot/023236f2", "done", "2026-08-20T09:00:00Z"),
            ("2026-08-18-b1-other.md", track_id, "simonfish/bfe8285d", "active", "2026-08-18T09:00:00Z"),
        ]
        with tempfile.TemporaryDirectory(prefix="ss-c155-board1-") as tmp:
            root = _build_repo(tmp, files)
            result = collect_handoff_multibranch(root)
            data = result.data
            snapshot = {"tracks_multibranch": data}
            board = render_track_board(snapshot, now=_FIXED_NOW)

            self.assertEqual(
                data["collision"]["groups"], [],
                f"collector must report zero collision groups; got {data['collision']!r}",
            )
            board_count = self._collision_line_count(board)
            self.assertEqual(
                board_count,
                len(data["collision"]["groups"]),
                f"board COLLISION line count ({board_count}) must equal "
                f"collector groups count ({len(data['collision']['groups'])}); "
                f"board=\n{board}",
            )

    def test_real_collision_produces_matching_board_collision_line_count(self):
        """Negative control: a genuine ongoing collision (both containers'
        latest handoff still active) must still show up on the board, and
        its line count must equal the collector's groups count (1 here).

        Both rows are >30min old relative to ``_FIXED_NOW``, so this
        incidentally also exercises reconcile's Rule 6 stale-takeover path
        (the "winning" claim gets demoted to ``superseded`` and
        ``verdict.winner`` becomes ``None``) — which is exactly the shape
        that needs the stale-winner recovery below to still classify
        correctly (see ``test_stale_takeover_winner_is_recovered_...``
        for a version of this that isolates and names that mechanism
        explicitly).
        """
        track_id = "twin-track-board"
        files = [
            ("2026-08-02-tb2a.md", track_id, "aria-runner-bot/023236f2", "active", "2026-08-02T09:00:00Z"),
            ("2026-08-10-tb2a.md", track_id, "aria-runner-bot/023236f2", "active", "2026-08-10T09:00:00Z"),
            ("2026-08-05-tb2b.md", track_id, "simonfish/bfe8285d", "active", "2026-08-05T09:00:00Z"),
            ("2026-08-12-tb2b.md", track_id, "simonfish/bfe8285d", "active", "2026-08-12T09:00:00Z"),
        ]
        with tempfile.TemporaryDirectory(prefix="ss-c155-board2-") as tmp:
            root = _build_repo(tmp, files)
            result = collect_handoff_multibranch(root)
            data = result.data
            snapshot = {"tracks_multibranch": data}
            board = render_track_board(snapshot, now=_FIXED_NOW)

            self.assertEqual(
                len(data["collision"]["groups"]), 1,
                f"expected exactly 1 colliding track_id; got {data['collision']!r}",
            )
            board_count = self._collision_line_count(board)
            self.assertEqual(
                board_count,
                len(data["collision"]["groups"]),
                f"board COLLISION line count ({board_count}) must equal "
                f"collector groups count ({len(data['collision']['groups'])}); "
                f"board=\n{board}",
            )

    def test_stale_takeover_winner_is_recovered_for_board_classification(self):
        """Round 2 finding, discovered via the real-repo acceptance check
        (this project's own ``aria-submodule-gate-block-flip`` track): even
        after feeding BOTH paths the same deduped input, the board and the
        collector could still disagree, because ``_render_collision_lines``
        built its ``active_claims`` from only ``yielders`` + ``winner`` —
        NOT also the non-terminal claim reconcile demotes to ``superseded``
        under Rule 6 (stale-takeover-eligible winner). When the earlier
        (recency-wise) of two active claims is itself >30min old, reconcile
        demotes it to ``superseded`` and sets ``winner=None`` — leaving only
        the OTHER (still-active) claim as a lone yielder, i.e. 1 claim, which
        ``classify_claims`` correctly calls "none" (needs >=2). Without
        recovering the demoted-but-non-terminal claim back into
        ``active_claims`` (exactly what ``lib/collision.py::classify()``
        already does, and this fix now mirrors), the board would silently
        DROP a real collision the collector still reports.

        Fixture: same owner ("acme"), two containers, one claim 3 hours old
        (stale — becomes the demoted "winner") and one claim 10 minutes old
        (fresh — the surviving yielder). Both non-terminal ("active").
        """
        track_id = "stale-winner-recovery-track"
        files = [
            ("2026-08-23-stale.md", track_id, "acme/boxA/s1", "active", "2026-08-23T09:00:00Z"),
            ("2026-08-23-fresh.md", track_id, "acme/boxB/s2", "active", "2026-08-23T11:50:00Z"),
        ]
        with tempfile.TemporaryDirectory(prefix="ss-c155-board5-") as tmp:
            root = _build_repo(tmp, files)
            result = collect_handoff_multibranch(root)
            data = result.data
            coll = data["collision"]
            self.assertEqual(
                coll["kind"],
                "self_multi_container",
                f"same owner (acme), two containers, both non-terminal — "
                f"a real collision even though one claim is stale enough to "
                f"be reconcile's demoted winner; got {coll!r}",
            )
            self.assertEqual(len(coll["groups"]), 1)

            snapshot = {"tracks_multibranch": data}
            board = render_track_board(snapshot, now=_FIXED_NOW)
            board_count = self._collision_line_count(board)
            self.assertEqual(
                board_count,
                1,
                f"the board must still render this collision — a renderer "
                f"that only looks at yielders+winner (not the recovered "
                f"stale-demoted claim) would silently show 0 lines here "
                f"while the collector reports 1; board=\n{board}",
            )
            self.assertIn(
                f"⚠ COLLISION self-multi-container {track_id}", board,
                f"expected a self-multi-container line naming the track; board=\n{board}",
            )

    def test_owner_container_self_serial_yields_zero_board_lines_despite_yielders(self):
        """Round 2 finding, discovered via the real-repo acceptance check
        (this project's own
        ``aria-2-0-m5-replay-reconciler-drift-review-loop-audit`` track):
        ``reconcile()`` groups purely by track_id and produces a
        winner/yielders split WITHOUT itself deduplicating by
        (owner, container) — so two claims that ``classify_claims`` will
        later call "self-serial" (same owner AND container, different
        session only — not a real race) still show up with
        ``verdict.yielders`` non-empty. The PRIOR renderer code had no
        explicit branch for ``collision_kind == "none"`` and fell into a
        generic ``else`` fallback that unconditionally rendered a COLLISION
        line whenever yielders existed — regardless of what
        ``_classify_collision`` actually said. Fixed: an explicit
        ``elif collision_kind == "none": pass`` (see track_board.py) skips
        rendering, matching ``lib/collision.py::classify()``, which has
        always correctly excluded self-serial "none" tracks from
        ``collision.groups``.
        """
        track_id = "self-serial-owner-container-track"
        files = [
            ("2026-08-23-ss1.md", track_id, "acme/boxA/s1", "active", "2026-08-23T11:55:00Z"),
            ("2026-08-23-ss2.md", track_id, "acme/boxA/s2", "active", "2026-08-23T11:55:00Z"),
        ]
        with tempfile.TemporaryDirectory(prefix="ss-c155-board6-") as tmp:
            root = _build_repo(tmp, files)
            result = collect_handoff_multibranch(root)
            data = result.data
            self.assertEqual(
                data["collision"]["groups"], [],
                f"same owner+container (different session only) is "
                f"self-serial, not a real collision; got {data['collision']!r}",
            )

            snapshot = {"tracks_multibranch": data}
            board = render_track_board(snapshot, now=_FIXED_NOW)
            board_count = self._collision_line_count(board)
            self.assertEqual(
                board_count, 0,
                f"reconcile still produces a non-empty yielders tuple for "
                f"same-owner+container claims (it does not itself apply "
                f"owner/container dedup) — the board must not render a "
                f"COLLISION line on that basis alone when classify_claims "
                f"says 'none'; board=\n{board}",
            )

    def test_one_malformed_track_elsewhere_does_not_blank_a_real_collision(self):
        """Round 2 finding, discovered via the real-repo acceptance check
        (this project's own real ``docs/handoff/`` data has a track with a
        malformed ``updated_at``: ``"2026-05-28T~14:00Z"``). The PRIOR
        renderer built ALL of ``all_collidable``'s ClaimRecords in one
        all-or-nothing list comprehension: one bad track anywhere in the
        WHOLE collidable set raised, the outer ``except`` caught it, and the
        board fell back board-WIDE to the cruder, status-blind P1
        ``_detect_collisions`` — which would have WRONGLY flagged the
        ``done``-vs-``active`` pair below as a collision (P1 does not look
        at status at all). Fixed: per-track try/except (mirrors
        ``lib/collision.py::classify()``'s own per-item fail-soft loop) —
        the malformed track is skipped, the REST still go through the P2
        reconcile path, and the ``done``/``active`` pair is correctly
        excluded (only one non-terminal claim ever existed for it).
        """
        false_positive_tid = "false-positive-done-vs-active-track"
        malformed_tid = "elsewhere-malformed-timestamp-track"
        files = [
            ("2026-08-01-fp-a.md", false_positive_tid, "dave/boxD/s4", "done", "2026-08-01T09:00:00Z"),
            ("2026-08-23-fp-b.md", false_positive_tid, "eve/boxE/s5", "active", "2026-08-23T11:55:00Z"),
            ("2026-08-23-bad.md", malformed_tid, "carol/boxC/s3", "active", "not-a-valid-timestamp-at-all"),
        ]
        with tempfile.TemporaryDirectory(prefix="ss-c155-board7-") as tmp:
            root = _build_repo(tmp, files)
            result = collect_handoff_multibranch(root)
            data = result.data
            self.assertEqual(
                data["collision"]["groups"], [],
                f"done-vs-active is not a real collision, and the malformed "
                f"track fail-softs out of classification entirely; "
                f"got {data['collision']!r}",
            )

            snapshot = {"tracks_multibranch": data}
            board = render_track_board(snapshot, now=_FIXED_NOW)
            board_count = self._collision_line_count(board)
            self.assertEqual(
                board_count, 0,
                f"one malformed-timestamp track elsewhere must not fall the "
                f"WHOLE board back to the status-blind P1 detector, which "
                f"would wrongly flag the done-vs-active pair; board=\n{board}",
            )


class TestDedupeTiebreakByBranchWhenUpdatedAtAndFilenameTie(unittest.TestCase):
    """Round 3, finding [M1] — the mainline multi-branch-scan shape: the SAME
    handoff file (identical ``track_id``/``owner_container``/``updated_at``/
    ``filename``) reachable from TWO branches sharing a common ancestor
    commit. This is not an edge case — any project with more than one
    long-lived branch (release branches, an in-flight feature branch cut
    from a commit that already carries a handoff doc, etc.) produces exactly
    this shape the moment ``branches_scanned`` > 1.

    Calls ``dedupe_latest_per_track_container`` directly (not through the
    git-fixture-building collector path used elsewhere in this file) because
    the property under test is about the PURE function's behavior on a given
    input list, independent of how ``tracks[]`` happens to be built/ordered.
    """

    @staticmethod
    def _row(branch: str, status: str) -> dict:
        return {
            "track_id": "branch-tie-track",
            "owner_container": "acme/boxA",
            "phase": "B.2",
            "status": status,
            "updated_at": "2026-08-01T09:00:00Z",
            "branch": branch,
            "filename": "same-file.md",
            "legacy": False,
        }

    def test_lexicographically_greater_branch_wins_regardless_of_input_order(self):
        """``row_a`` (branch ``"aaa-branch"``, status active) and ``row_b``
        (branch ``"zzz-branch"``, status done) tie on EVERY field the round-2
        (3-level) key compared — ``updated_at`` and ``filename`` are
        identical byte-for-byte between the two rows, only ``branch``
        differs. A round-2-shaped key (no branch level) would pick whichever
        row ``max()`` saw FIRST while iterating — i.e. the FORWARD list's
        first element and the REVERSED list's first element, which are
        DIFFERENT rows — making the result depend on ``tracks[]`` build
        order. The fixed 4-level key must pick the SAME row
        (``"zzz-branch"``, dictionary-greater) in both directions.
        """
        row_a = self._row("aaa-branch", "active")
        row_b = self._row("zzz-branch", "done")

        deduped_fwd, stats_fwd = dedupe_latest_per_track_container([row_a, row_b])
        deduped_rev, stats_rev = dedupe_latest_per_track_container([row_b, row_a])

        self.assertEqual(len(deduped_fwd), 1)
        self.assertEqual(len(deduped_rev), 1)
        self.assertEqual(
            deduped_fwd[0]["branch"], "zzz-branch",
            f"forward-order dedupe must pick the dictionary-greater branch "
            f"row — got {deduped_fwd[0]!r}",
        )
        self.assertEqual(
            deduped_rev[0]["branch"], "zzz-branch",
            f"reversed-order dedupe must pick the SAME row as forward-order "
            f"— got {deduped_rev[0]!r}",
        )
        self.assertEqual(
            deduped_fwd[0], deduped_rev[0],
            "the winning row must be IDENTICAL regardless of input list "
            "order — a round-2-shaped (branch-blind) key would fail this "
            "by picking whichever row it saw first while iterating",
        )
        self.assertEqual(deduped_fwd[0]["status"], "done")
        self.assertEqual(stats_fwd, stats_rev)
        self.assertEqual(stats_fwd, {"input_tracks": 2, "after_dedupe": 1, "legacy_passthrough": 0})


class TestDedupeFoldsAcrossSessionsWithinSameContainer(unittest.TestCase):
    """Round 3, finding [m] — the dedupe grouping key must be
    ``(track_id, owner, container)`` (via ``lib.collision.split_owner_container``,
    read-only import), NOT the raw ``owner_container`` string: two historical
    rows for the same track and the SAME physical owner/container that
    differ only by SESSION (3rd segment) are the same container's history
    over time, and must fold into one representative — not survive as two
    separate dedupe-of-one groups (which would let a stale ``active`` row
    from an old session keep counting as a live candidate even though its
    own container has moved on, e.g. to ``done`` under a newer session).
    """

    def test_old_active_session_folds_under_newer_done_session_same_container(self):
        """``acme/boxA`` has two historical rows across two SESSIONS
        (``s1`` old/active, ``s2`` new/done) — same owner, same container.
        ``acme/boxB`` has one genuinely active row (different container,
        same owner ``acme``). A dedupe key that does not drop the session
        segment leaves ``boxA``'s old-active-``s1`` row as its own
        dedupe-of-one group — an undead non-terminal candidate — which
        would incorrectly pair with ``boxB``'s active row into
        ``self_multi_container`` (2 distinct containers, same owner). The
        fixed key folds both ``boxA`` rows into one (the newer, ``done``,
        row wins on ``updated_at``), leaving only ``boxB`` as a genuinely
        active container — 1 active candidate — so ``kind`` must be
        ``"none"``.
        """
        track_id = "session-fold-track"
        files = [
            ("2026-08-02-s1.md", track_id, "acme/boxA/s1", "active", "2026-08-02T09:00:00Z"),
            ("2026-08-20-s2.md", track_id, "acme/boxA/s2", "done", "2026-08-20T09:00:00Z"),
            ("2026-08-18-other.md", track_id, "acme/boxB/s3", "active", "2026-08-18T09:00:00Z"),
        ]
        with tempfile.TemporaryDirectory(prefix="ss-c155-r3-session-") as tmp:
            root = _build_repo(tmp, files)
            result = collect_handoff_multibranch(root)
            data = result.data

            deduped, stats = dedupe_latest_per_track_container(data["tracks"])
            self.assertEqual(
                stats,
                {"input_tracks": 3, "after_dedupe": 2, "legacy_passthrough": 0},
                f"the two acme/boxA rows (sessions s1/s2) must fold into ONE "
                f"— expected 3 raw rows -> 2 after dedupe; got {stats!r}",
            )
            box_a_rows = [
                row for row in deduped
                if row["track_id"] == track_id and row["owner_container"].startswith("acme/boxA")
            ]
            self.assertEqual(
                len(box_a_rows), 1,
                f"acme/boxA's two sessions must collapse to exactly one "
                f"representative row; got {box_a_rows!r}",
            )
            self.assertEqual(
                box_a_rows[0]["filename"], "2026-08-20-s2.md",
                "the newer (s2, done) row must be acme/boxA's surviving "
                f"representative — got {box_a_rows[0]!r}",
            )

            coll = data["collision"]
            self.assertEqual(
                coll["dedupe"],
                {"input_tracks": 3, "after_dedupe": 2, "legacy_passthrough": 0},
                f"persisted collision.dedupe must match the same stats; got {coll.get('dedupe')!r}",
            )
            self.assertEqual(
                coll["kind"],
                "none",
                f"acme/boxA's latest (done) session must supersede its own "
                f"stale-active older session — only acme/boxB is genuinely "
                f"active — expected no collision; got {coll!r}",
            )

    def test_two_containers_each_multi_session_latest_active_still_collides(self):
        """Negative control (over-fix guard): BOTH containers have 2
        sessions each, and BOTH containers' LATEST session is still
        ``active`` — a genuine, ongoing ``self_multi_container`` collision.
        Folding across sessions within EACH container must not erase it —
        the fold must not accidentally merge the two DIFFERENT containers
        with each other.
        """
        track_id = "session-fold-collision-track"
        files = [
            ("2026-08-01-a-s1.md", track_id, "acme/boxA/s1", "active", "2026-08-01T09:00:00Z"),
            ("2026-08-15-a-s2.md", track_id, "acme/boxA/s2", "active", "2026-08-15T09:00:00Z"),
            ("2026-08-05-b-s1.md", track_id, "acme/boxB/s1", "active", "2026-08-05T09:00:00Z"),
            ("2026-08-19-b-s2.md", track_id, "acme/boxB/s2", "active", "2026-08-19T09:00:00Z"),
        ]
        with tempfile.TemporaryDirectory(prefix="ss-c155-r3-session2-") as tmp:
            root = _build_repo(tmp, files)
            result = collect_handoff_multibranch(root)
            data = result.data
            coll = data["collision"]

            self.assertEqual(
                coll["dedupe"],
                {"input_tracks": 4, "after_dedupe": 2, "legacy_passthrough": 0},
                f"each container's 2 sessions must fold to 1 (4 -> 2 total, "
                f"NOT 4 -> 1, which would mean the two containers were "
                f"wrongly merged with each other); got {coll.get('dedupe')!r}",
            )
            self.assertEqual(
                coll["kind"],
                "self_multi_container",
                f"both containers' latest session is still active — a real "
                f"ongoing collision — per-container session folding must "
                f"not erase it; got {coll!r}",
            )


if __name__ == "__main__":
    unittest.main()


def _row(track_id, oc, status, updated_at, filename, branch="master", legacy=False):
    return {
        "track_id": track_id, "owner_container": oc, "status": status,
        "updated_at": updated_at, "filename": filename, "branch": branch,
        "phase": "B.2", "legacy": legacy,
    }


class TestDedupeRound3Residuals(unittest.TestCase):
    """#155 round-3 rebuttal residuals — direct-call tests on
    `dedupe_latest_per_track_container` with rejection power for the
    specific bad implementations the rebuttal seat constructed."""

    def test_legacy_rows_pass_through_and_are_counted_separately(self):
        """2 legacy + 3 non-legacy (2 fold into 1 + 1 singleton) ->
        input_tracks=3, after_dedupe=2, legacy_passthrough=2, legacy rows
        present verbatim. How it goes red: round-1's mixed counting
        (input_tracks=len(tracks)=5, after_dedupe=4, legacy_passthrough=0)."""
        rows = [
            _row("legacy:master:2026-05-01-x.md", "unknown", "legacy", "2026-05-01T00:00:00Z", "2026-05-01-x.md", legacy=True),
            _row("legacy:master:2026-05-02-y.md", "unknown", "legacy", "2026-05-02T00:00:00Z", "2026-05-02-y.md", legacy=True),
            _row("t1", "alice/box-A", "active", "2026-08-01T00:00:00Z", "2026-08-01-t1.md"),
            _row("t1", "alice/box-A", "done", "2026-08-02T00:00:00Z", "2026-08-02-t1.md"),
            _row("t2", "bob/box-B", "active", "2026-08-02T00:00:00Z", "2026-08-02-t2.md"),
        ]
        deduped, stats = dedupe_latest_per_track_container(rows)
        self.assertEqual(stats, {"input_tracks": 3, "after_dedupe": 2, "legacy_passthrough": 2})
        self.assertEqual(sum(1 for r in deduped if r["status"] == "legacy"), 2)
        self.assertEqual([r["status"] for r in deduped if r["track_id"] == "t1"], ["done"])

    def test_owner_segment_participates_in_grouping_key(self):
        """SC-4 (owner-container-identity-key TASK-003) — dedupe key is
        ``(track_id, identity_key)``; three arms:

        A. uuid container, two owners (`alice/aaaa1111` vs `bob/aaaa1111`) ->
           ONE identity_key (aaaa1111) -> folds to the newest row.
           How it goes red on 7dd0135: 2 rows (owner still in the key).
        B. hostname container, two owners (`alice/box` vs `bob/box`) -> two
           identity_keys (`alice/box` / `bob/box`) -> stays two rows.
        C. adversarial: `devbox01` is 8 chars but NOT hex -> hostname domain ->
           `alice/devbox01` vs `bob/devbox01` stay two rows.
        """
        # A — uuid domain folds across owners
        rows_a = [
            _row("t1", "alice/aaaa1111", "active", "2026-08-01T00:00:00Z", "2026-08-01-a.md"),
            _row("t1", "bob/aaaa1111", "active", "2026-08-02T00:00:00Z", "2026-08-02-b.md"),
        ]
        deduped_a, stats_a = dedupe_latest_per_track_container(rows_a)
        self.assertEqual(stats_a["after_dedupe"], 1, deduped_a)
        self.assertEqual(deduped_a[0]["owner_container"], "bob/aaaa1111")
        # B — hostname domain keeps the owner segment
        rows_b = [
            _row("t1", "alice/box", "active", "2026-08-01T00:00:00Z", "2026-08-01-a.md"),
            _row("t1", "bob/box", "active", "2026-08-01T00:00:00Z", "2026-08-01-b.md"),
        ]
        deduped_b, stats_b = dedupe_latest_per_track_container(rows_b)
        self.assertEqual(stats_b["after_dedupe"], 2)
        self.assertEqual(sorted(r["owner_container"] for r in deduped_b), ["alice/box", "bob/box"])
        # C — 8-char non-hex hostname is not a uuid
        rows_c = [
            _row("t1", "alice/devbox01", "active", "2026-08-01T00:00:00Z", "2026-08-01-a.md"),
            _row("t1", "bob/devbox01", "active", "2026-08-01T00:00:00Z", "2026-08-01-b.md"),
        ]
        deduped_c, stats_c = dedupe_latest_per_track_container(rows_c)
        self.assertEqual(stats_c["after_dedupe"], 2)

    def test_sort_key_prefers_filename_over_branch(self):
        """Equal updated_at; row A has the GREATER filename but LESSER branch,
        row B the reverse. The 4-level key (parse_ok, updated_at, filename,
        branch) picks A. How it goes red: a (…, branch, filename) key picks B."""
        a = _row("t1", "alice/box", "done", "2026-08-01T00:00:00Z", "2026-08-01-zzz.md", branch="aaa")
        b = _row("t1", "alice/box", "active", "2026-08-01T00:00:00Z", "2026-08-01-aaa.md", branch="zzz")
        for order in ([a, b], [b, a]):
            deduped, _ = dedupe_latest_per_track_container(order)
            self.assertEqual(len(deduped), 1)
            self.assertEqual(deduped[0]["filename"], "2026-08-01-zzz.md")
            self.assertEqual(deduped[0]["status"], "done")


class TestTwoPartBoardEchoAndAdvisoryWiring(unittest.TestCase):
    """owner-container-identity-key-and-collision-parser TASK-003 (c) / TASK-005."""

    def test_board_echoes_original_two_part_strings(self):
        """SC-4: the board's collision line must echo the ORIGINAL two-part
        strings. How it goes red on 7dd0135: the label lookup is keyed on the
        split tuple ('' , 'simonfish', 'bfe8285d') while the ClaimRecord carries
        ('unknown', 'simonfish', 'bfe8285d') -> lookup misses -> the board prints
        the reconstructed 'unknown/simonfish/bfe8285d'."""
        from renderers.track_board import render_track_board
        snapshot = {
            "tracks_multibranch": {
                "exists": True,
                "tracks": [
                    _row("twin", "aria-runner-bot/023236f2", "active", "2026-08-20T09:00:00Z", "2026-08-20-a.md"),
                    _row("twin", "simonfish/bfe8285d", "active", "2026-08-19T09:00:00Z", "2026-08-19-b.md"),
                ],
                "branches_scanned": ["master"],
                "legacy_count": 0,
                "collision": {"kind": "cross_owner", "groups": [["aria-runner-bot/023236f2", "simonfish/bfe8285d"]], "identity_advisories": []},
                "errors": [],
            },
            "coordination_fetch": {"attempted": True, "success": True, "fetched_at": "2026-08-21T00:00:00Z"},
        }
        out = render_track_board(snapshot, now=datetime(2026, 8, 21, tzinfo=timezone.utc))
        collision_lines = [l for l in out.splitlines() if "COLLISION" in l]
        self.assertEqual(len(collision_lines), 1, out)
        line = collision_lines[0]
        self.assertIn("cross-owner", line)
        self.assertIn("aria-runner-bot/023236f2", line)
        self.assertIn("simonfish/bfe8285d", line)
        self.assertNotIn("unknown/", line)

    def test_advisory_wired_before_dedupe_same_track_two_owner_strings(self):
        """SC-2 端到端 (TASK-005): two handoffs for the SAME track_id from the
        same uuid container under two owner strings. Dedupe folds them to one
        row; the advisory must be computed on the PRE-dedupe rows, so exactly
        one advisory survives. How it goes red: (i) on 7dd0135 the key does not
        exist; (ii) if :709 passes deduped_tracks to the advisory -> 0."""
        track_id = "drift-track"
        files = [
            ("2026-08-10-x.md", track_id, "simonfish/aaaa1111", "active", "2026-08-10T09:00:00Z"),
            ("2026-08-20-y.md", track_id, "aria-runner-bot/aaaa1111", "active", "2026-08-20T09:00:00Z"),
        ]
        with tempfile.TemporaryDirectory(prefix="ss-ick-adv-") as tmp:
            root = _build_repo(tmp, files)
            coll = collect_handoff_multibranch(root).data["collision"]
            self.assertIn("identity_advisories", coll, coll)
            self.assertEqual(coll["kind"], "none", coll)   # one identity_key after dedupe
            self.assertEqual(len(coll["identity_advisories"]), 1, coll)
            adv = coll["identity_advisories"][0]
            self.assertEqual(adv["identity_key"], "aaaa1111")
            self.assertEqual(adv["owners"], ["aria-runner-bot", "simonfish"])
            self.assertEqual(adv["first_seen"], "2026-08-10T09:00:00Z")
            self.assertEqual(adv["last_seen"], "2026-08-20T09:00:00Z")

    def test_real_two_part_two_people_two_machines_is_cross_owner(self):
        """SC-2 端到端: real two-part frontmatter, two people on two uuid
        containers -> cross_owner. How it goes red on 7dd0135: self_multi_container."""
        files = [
            ("2026-08-20-a.md", "shared", "alice/aaaa1111", "active", "2026-08-20T09:00:00Z"),
            ("2026-08-20-b.md", "shared", "bob/bbbb2222", "active", "2026-08-20T09:00:00Z"),
        ]
        with tempfile.TemporaryDirectory(prefix="ss-ick-2p-") as tmp:
            root = _build_repo(tmp, files)
            coll = collect_handoff_multibranch(root).data["collision"]
            self.assertEqual(coll["kind"], "cross_owner", coll)
            self.assertEqual(coll["groups"], [["alice/aaaa1111", "bob/bbbb2222"]], coll)
            self.assertEqual(coll["identity_advisories"], [])


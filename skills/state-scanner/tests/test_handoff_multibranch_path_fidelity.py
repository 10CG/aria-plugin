"""Tests — 10CG/Aria#195: ``handoff_multibranch`` enumerates recursively but keeps
only the basename, so every handoff file living under a SUBDIRECTORY of
``docs/handoff/`` is unreadable and silently demoted to a fake ``legacy`` track.

Bug: ``_list_handoff_files`` runs ``git ls-tree -r --name-only`` (recursive), then
reduces each hit to ``Path(path).name``. ``_read_file_content`` re-composes the
object path as ``docs/handoff/<filename>``. For a file that only ever existed at
``docs/handoff/archive/x.md`` that recomposition points at a path that does not
exist, so ``git show`` fails with rc=128 and the row is emitted as
``legacy: True`` with a ``handoff_multibranch_git_show_failed`` soft_error —
once per (file, branch). Reported in production as 34 such errors per scan
(2 files x 17 origin branches) with ``scan.py`` exiting 10.

Fix shape (A′, decision 2026-09-07, re-affirmed 2026-09-12): the enumeration
layer returns the path RELATIVE to ``docs/handoff/`` and every consumer composes
the git object path from that, while ``filename`` keeps its documented basename
semantics. A new ``rel_path`` field carries the relative path; a flat repo
therefore satisfies ``rel_path == filename``.

This file is the RED-first suite for that change (tasks.md 1.2). It is written
against the B.1 baseline (aria ``1cb3872``) where every assertion below fails,
either as ``AssertionError`` or — for the two Success Criteria that pin the new
``unreadable_count`` key with a DIRECT index — as ``KeyError``.

Batch 1 (TASK-003): the enumeration-and-read family, SC-1 / SC-3 / SC-8 / SC-9 /
SC-16 / SC-18. Batches 2-4 (TASK-004..006) append to THIS file; it is one
TestCase module by design so the batches never write the same file in parallel.
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

# sys.path order is load-bearing and must not be reordered (same hazard the
# sibling test_handoff_multibranch_collision_dedupe.py documents at length):
# the state-scanner root goes to the FRONT so `lib` binds to the Layer L
# package that owns collision.py, and scripts/ goes to the END. Inserting
# scripts/ at position 0 rebinds `lib` to the collision.py-less package, which
# degrades collision to "none" everywhere and would make assertions pass for
# the wrong reason.
_TESTS_DIR = Path(__file__).resolve().parent
_SS_ROOT = _TESTS_DIR.parent
if str(_SS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SS_ROOT))
_SCRIPTS_DIR = _SS_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.append(str(_SCRIPTS_DIR))

from collectors import handoff_multibranch as hmb  # noqa: E402
from collectors.handoff_multibranch import collect_handoff_multibranch  # noqa: E402

# ── Deterministic git identity, isolated from host config (Rule #7: capture_output) ──
#
# NOTE — scope of this env (SC-3 depends on understanding it): _GIT_ENV is passed
# as ``env=`` to the FIXTURE's own subprocess calls only. The code under test
# reaches git through ``collectors._common._run`` -> ``_noninteractive_git_env``,
# which builds ``{**os.environ, "LC_ALL": "C", ...}`` and therefore CANNOT see
# this dict. Anything that must hold for the subprocess under test has to be set
# either in the repo's own local config or in ``os.environ``.
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

_GIT_SHOW_FAILED = "handoff_multibranch_git_show_failed"
_UNEXPECTED_PREFIX = "handoff_multibranch_unexpected_path_prefix"
_UNDECODABLE_PATH = "handoff_multibranch_undecodable_path"


def _git(cwd: str, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env=_GIT_ENV)


def _git_out(cwd: str, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=_GIT_ENV
    ).stdout.strip()


def _frontmatter(track_id: str, oc: str = "tester/c0ffee01", status: str = "active",
                 updated_at: str = "2026-05-09T10:00:00Z", phase: str = "B.2") -> str:
    """Build a well-formed 5-field handoff frontmatter block (§2.3.1 schema)."""
    return (
        "---\n"
        f"track-id: {track_id}\n"
        f"owner-container: {oc}\n"
        f"phase: {phase}\n"
        f"status: {status}\n"
        f"updated-at: {updated_at}\n"
        "---\n\n# Aria — Session Handoff\n"
    )


def _commit(tmp: str, msg: str = "handoffs", *, date: "str | None" = None) -> None:
    """Stage everything and commit, optionally pinning the commit's dates.

    ``date`` sets BOTH ``GIT_AUTHOR_DATE`` and ``GIT_COMMITTER_DATE`` for this
    one commit. Pinning is mandatory wherever a criterion distinguishes two
    commits by date: ``%aI`` has second resolution, and two commits made by the
    same test in the same second otherwise carry the identical stamp — measured
    behaviour, and the reason SC-4 / SC-13 call this out explicitly. ``_GIT_ENV``
    pins identity but deliberately does NOT pin dates.
    """
    env = dict(_GIT_ENV)
    if date is not None:
        env["GIT_AUTHOR_DATE"] = date
        env["GIT_COMMITTER_DATE"] = date
    subprocess.run(["git", "add", "-A"], cwd=tmp, check=True, capture_output=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=tmp, check=True,
                   capture_output=True, env=env)


def _publish_ref(tmp: str) -> str:
    """Publish the current tip to refs/remotes/origin/<branch> and return the branch.

    No real remote and no clone: ``collect_handoff_multibranch`` only ever reads
    ``refs/remotes/origin/*``, so writing that ref directly is enough (the
    technique test_collision.py and test_p1_layer_h.py already use).
    """
    branch = _git_out(tmp, "rev-parse", "--abbrev-ref", "HEAD")
    sha = _git_out(tmp, "rev-parse", "HEAD")
    _git(tmp, "update-ref", f"refs/remotes/origin/{branch}", sha)
    return branch


def _publish(tmp: str, *, date: "str | None" = None) -> str:
    """One-commit convenience: commit the working tree, then publish the tip."""
    _commit(tmp, date=date)
    return _publish_ref(tmp)


def _init_repo(tmp: str, *, quote_path: bool = True) -> Path:
    """``git init`` plus the repo-LOCAL settings that fixtures rely on.

    ``core.quotePath`` is pinned in the repo's own config on purpose — see
    ``test_non_ascii_filename_not_escaped`` for why an env-var-based isolation
    cannot reach the subprocess under test.
    """
    root = Path(tmp)
    _git(tmp, "init", "-q")
    _git(tmp, "config", "core.quotePath", "true" if quote_path else "false")
    (root / "docs" / "handoff").mkdir(parents=True, exist_ok=True)
    return root


def _write(root: Path, rel_under_handoff: str, content: str) -> None:
    """Write ``docs/handoff/<rel_under_handoff>``, creating parent dirs."""
    target = root / "docs" / "handoff" / rel_under_handoff
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _rows_by(tracks: "list[dict]", *, branch: str, filename: str) -> "list[dict]":
    """Select rows by (branch, filename) — deliberately NOT by rel_path.

    Selecting on ``rel_path`` would make the first failing assertion of the
    counterfactual patch land on the selection itself (an empty match) instead
    of on the field being tested, and that patch can no longer be narrowed.
    """
    return [t for t in tracks if t.get("branch") == branch and t.get("filename") == filename]


def _kinds(result) -> "list[str]":
    """Kind literals from CollectorResult.errors.

    ``CollectorResult.soft_error(kind, detail)`` appends ``{"error": kind,
    "detail": detail}`` (_common.py), so the kind lives under the "error" key.
    This is the channel the SCs assert on — NOT ``data["errors"]``, which only
    carries message strings and would make several assertions vacuously green
    on the baseline.
    """
    return [e.get("error") for e in result.errors]


class TestSubdirPathFidelity(unittest.TestCase):
    """SC-1 / SC-8 / SC-16 / SC-18 — enumeration keeps the relative path."""

    def test_subdir_file_read_as_real_track(self):
        """SC-1, the issue's headline symptom.

        A handoff doc that has only ever existed at
        ``docs/handoff/archive/2026-05-09-session-end.md`` must be read through
        its real path and emitted as a first-class track.

        RED on the B.1 baseline: enumeration reduces the hit to the basename, so
        ``git show origin/<branch>:docs/handoff/2026-05-09-session-end.md``
        resolves to nothing, the row is demoted to ``legacy: True`` and a
        ``handoff_multibranch_git_show_failed`` soft_error is recorded.
        """
        with TemporaryDirectory() as tmp:
            root = _init_repo(tmp)
            _write(root, "archive/2026-05-09-session-end.md",
                   _frontmatter("session-end-20260509", updated_at="2026-05-09T10:00:00Z"))
            branch = _publish(tmp)

            r = collect_handoff_multibranch(root)

            rows = _rows_by(r.data["tracks"], branch=branch,
                            filename="2026-05-09-session-end.md")
            self.assertEqual(len(rows), 1, "the subdir file must yield exactly one row")
            row = rows[0]
            self.assertFalse(row["legacy"], "must be a first-class track, not a legacy stub")
            self.assertEqual(row["track_id"], "session-end-20260509",
                             "track_id must come from the frontmatter")
            self.assertEqual(row["updated_at"], "2026-05-09T10:00:00Z",
                             "updated_at must come from the frontmatter, not git log")
            self.assertEqual(row["filename"], "2026-05-09-session-end.md",
                             "filename keeps its documented basename semantics")
            self.assertEqual(row["rel_path"], "archive/2026-05-09-session-end.md",
                             "rel_path must retain the directory segment")
            self.assertEqual(r.data["legacy_count"], 0)
            self.assertNotIn(_GIT_SHOW_FAILED, _kinds(r),
                             "reading through the real path must not fail")

    def test_pointer_excluded_at_any_depth(self):
        """SC-8 — pointer exclusion is depth-agnostic, and a near-miss name is not.

        First half (recording-only, already true on the baseline because the
        basename is compared against the constant): neither ``latest.md`` nor
        ``archive/latest.md`` appears in ``tracks[]``. It guards against a future
        narrowing regressing silently.

        Second half (the discriminating one): ``archive/latest-notes.md`` is NOT
        the pointer, so it enters ``tracks[]`` with the directory segment kept in
        ``rel_path`` and the basename in ``filename``.
        """
        with TemporaryDirectory() as tmp:
            root = _init_repo(tmp)
            _write(root, "latest.md", "# pointer\n")
            _write(root, "archive/latest.md", "# archived pointer\n")
            _write(root, "archive/latest-notes.md", _frontmatter("latest-notes-track"))
            branch = _publish(tmp)

            r = collect_handoff_multibranch(root)
            tracks = r.data["tracks"]

            self.assertEqual(_rows_by(tracks, branch=branch, filename="latest.md"), [],
                             "latest.md must be excluded at any depth")

            rows = _rows_by(tracks, branch=branch, filename="latest-notes.md")
            self.assertEqual(len(rows), 1, "latest-notes.md is not the pointer")
            self.assertEqual(rows[0]["rel_path"], "archive/latest-notes.md")
            self.assertEqual(rows[0]["filename"], "latest-notes.md")

    def test_flat_repo_rel_path_equals_filename(self):
        """SC-16 — in a flat repo every row satisfies ``rel_path == filename``.

        The fixture deliberately carries BOTH a file with well-formed frontmatter
        and one without: the assertion is a universal predicate over
        ``tracks[]``, and a frontmatter-only fixture would satisfy the legacy
        construction site vacuously.

        RED on the B.1 baseline: ``rel_path`` does not exist yet (KeyError on the
        row), and ``unreadable_count`` does not exist in ``data`` either.
        """
        with TemporaryDirectory() as tmp:
            root = _init_repo(tmp)
            _write(root, "2026-05-01-with-fm.md", _frontmatter("flat-with-fm"))
            _write(root, "2026-05-02-no-fm.md", "# no frontmatter here\n")
            _publish(tmp)

            r = collect_handoff_multibranch(root)
            tracks = r.data["tracks"]

            self.assertEqual(len(tracks), 2, "both files must produce a row")
            self.assertEqual({t["legacy"] for t in tracks}, {False, True},
                             "fixture must exercise both construction sites")
            for t in tracks:
                self.assertEqual(t["rel_path"], t["filename"],
                                 f"flat repo must satisfy rel_path == filename for {t!r}")
                self.assertNotIn("/", t["rel_path"])
                self.assertNotIn("/", t["filename"])
            self.assertEqual(r.data["unreadable_count"], 0)

    def test_undecodable_filename_skipped_with_signal(self):
        """SC-18 — a name that is not valid UTF-8 is skipped WITH a signal.

        The bad name is created through a bytes path so the byte 0xff reaches
        the index verbatim. Skipping it must be explicit: a dedicated kind, and
        NOT a ``git show`` failure.

        RED on the B.1 baseline: (b) fails with ``KeyError`` because
        ``unreadable_count`` does not exist. (a) and (c) happen to be green
        there — the escaped name loses its ``.md`` suffix and is dropped by the
        extension filter — so this criterion's baseline-failing status rests on
        (b); (a) and (c) are the forward locks that keep the skip from
        degenerating into a silent drop.
        """
        with TemporaryDirectory() as tmp:
            root = _init_repo(tmp)
            _write(root, "ok.md", _frontmatter("undecodable-neighbour"))
            bad = os.path.join(tmp.encode(), b"docs", b"handoff", b"2026-\xff-bad.md")
            with open(bad, "wb") as fh:
                fh.write(b"# not valid utf-8 in the NAME\n")
            branch = _publish(tmp)

            r = collect_handoff_multibranch(root)
            tracks = r.data["tracks"]

            for t in tracks:
                self.assertNotIn("bad", t["filename"],
                                 f"the undecodable name must not reach tracks[]: {t!r}")
            self.assertEqual(len(tracks), 1,
                             f"only the healthy file may produce a row, got {tracks!r}")
            self.assertEqual(len(_rows_by(tracks, branch=branch, filename="ok.md")), 1,
                             "the healthy neighbour must still be collected")
            self.assertEqual(r.data["unreadable_count"], 0,
                             "an undecodable NAME is not an unreadable file")
            kinds = _kinds(r)
            self.assertIn(_UNDECODABLE_PATH, kinds, "the skip must be signalled")
            self.assertNotIn(_GIT_SHOW_FAILED, kinds,
                             "the bad name must never reach git show")


class TestNonAsciiEnumeration(unittest.TestCase):
    """SC-3 — non-ASCII names survive enumeration unescaped."""

    def test_non_ascii_filename_not_escaped(self):
        """SC-3 — a CJK handoff filename is read as a real track.

        JUDGEMENT DEPENDS ON ``core.quotePath`` AND THAT IS DELIBERATE. The
        "quoted + octal-escaped" output this criterion red-tests is not an
        unconditional property of ``git ls-tree --name-only``; it is the product
        of ``core.quotePath`` being true (git's default). Measured on git 2.39.5
        in an isolated repo: the default prints
        ``"docs/handoff/2026-\\346\\265\\213..."`` while ``-c
        core.quotePath=false`` prints the name verbatim.

        The fixture therefore pins ``core.quotePath=true`` in the repo's OWN
        local config (``_init_repo``). An env-var approach cannot work here:
        ``_GIT_ENV`` is only passed to the fixture's own subprocesses, whereas
        the code under test goes through ``_common._noninteractive_git_env``,
        which inherits ``os.environ``. Pinning it locally also states the
        expected value positively, so the criterion keeps its discriminating
        power even if git ever flips the default.

        RED on the B.1 baseline: enumeration has no ``-z``, so the escaped name
        carries a trailing quote, fails ``.endswith(".md")`` and is dropped —
        the track never appears at all (it does NOT get as far as a failing
        ``git show``).
        """
        with TemporaryDirectory() as tmp:
            root = _init_repo(tmp, quote_path=True)
            _write(root, "2026-测试-交接.md", _frontmatter("cjk-track"))
            _write(root, "2026-05-03-ascii.md", _frontmatter("ascii-neighbour"))
            branch = _publish(tmp)

            self.assertEqual(_git_out(tmp, "config", "--get", "core.quotePath"), "true",
                             "the fixture's own precondition must hold")

            r = collect_handoff_multibranch(root)
            tracks = r.data["tracks"]

            rows = _rows_by(tracks, branch=branch, filename="2026-测试-交接.md")
            self.assertEqual(len(rows), 1, "the CJK-named file must be collected")
            row = rows[0]
            self.assertEqual(row["track_id"], "cjk-track")
            self.assertNotIn('"', row["filename"], "filename must not carry git's quoting")
            self.assertNotIn("\\3", row["filename"], "filename must not carry octal escapes")
            self.assertEqual(row["rel_path"], "2026-测试-交接.md")
            self.assertNotIn(_GIT_SHOW_FAILED, _kinds(r))


class TestUnexpectedPrefixGuard(unittest.TestCase):
    """SC-9 — the prefix guard reports instead of swallowing."""

    _BRANCH = "master"

    def _fake_run(self, *, enumerated: "list[str]"):
        """Fake ``_run`` dispatching on the command's second token.

        ``_run`` is the single exit for ALL FOUR git calls this collector makes
        (for-each-ref / ls-tree / show / log), imported once and reused, so a
        fake that answers every command with the same payload would make the
        "other files still collected" assertion unsatisfiable by construction.

        The ls-tree leg additionally mirrors the REAL output framing of whichever
        flags it is called with: NUL-separated (with git's trailing NUL) when the
        caller passes ``-z``, newline-separated otherwise. Without that, the
        baseline — which does not pass ``-z`` — would fail merely because it
        cannot parse a NUL blob, and the red would stop being attributable to
        the missing guard.
        """
        def fake(cmd, cwd=None, timeout=5):
            token = cmd[1] if len(cmd) > 1 else ""
            if token == "for-each-ref":
                return (0, f"origin/{self._BRANCH}\n", "")
            if token == "ls-tree":
                if "-z" in cmd:
                    return (0, "".join(p + "\0" for p in enumerated), "")
                return (0, "\n".join(enumerated) + "\n", "")
            if token == "show":
                return (0, _frontmatter("prefix-guard-neighbour"), "")
            if token == "log":
                return (0, "2026-05-04T10:00:00Z\n", "")
            return (1, "", "unmocked")
        return fake

    def test_unexpected_prefix_soft_errors(self):
        """SC-9 — a row outside ``docs/handoff/`` is reported, and only that row.

        Four assertions, any of which missing would let a bad implementation
        pass: (a) the kind literal is the dedicated
        ``handoff_multibranch_unexpected_path_prefix`` — reusing the branch-level
        ls-tree kind would leave consumers unable to tell "whole branch failed"
        from "one row had a strange prefix"; (b) the other files on the same
        branch are still collected — without it the naive "abandon the whole
        branch" implementation is green while being worse than the original bug;
        (c) on a well-formed flat enumeration the count of that kind is 0, so the
        trailing empty segment that ``-z`` always produces is dropped rather than
        reported once per branch; (d) the message channel carries it too, since
        all four existing kinds are paired across both channels.
        """
        with TemporaryDirectory() as tmp:
            root = _init_repo(tmp)
            enumerated = [
                "docs/handoff/2026-05-04-good.md",
                "docs/other/2026-05-04-stray.md",
            ]
            with mock.patch.object(hmb, "_run", self._fake_run(enumerated=enumerated)):
                r = collect_handoff_multibranch(root)

            kinds = _kinds(r)
            self.assertEqual(kinds.count(_UNEXPECTED_PREFIX), 1,
                             "exactly one prefix violation must be reported")
            tracks = r.data["tracks"]
            self.assertEqual(
                _rows_by(tracks, branch=self._BRANCH, filename="2026-05-04-stray.md"), [],
                "the offending row must not enter tracks[]")
            self.assertEqual(
                len(_rows_by(tracks, branch=self._BRANCH, filename="2026-05-04-good.md")), 1,
                "the other file on the same branch must still be collected")
            self.assertTrue(
                any(_UNEXPECTED_PREFIX in m for m in r.data["errors"]),
                "the message channel must carry the kind as well")

    def test_flat_enumeration_reports_no_prefix_violation(self):
        """SC-9 (c) — the trailing empty segment must not be reported.

        ``git ls-tree -r --name-only -z`` terminates its output with NUL, so a
        naive ``split("\\0")`` always yields one trailing empty segment. Feeding
        that into the new guard would emit one
        ``handoff_multibranch_unexpected_path_prefix`` per branch — exactly the
        alarm noise this change exists to remove.
        """
        with TemporaryDirectory() as tmp:
            root = _init_repo(tmp)
            enumerated = [
                "docs/handoff/2026-05-04-good.md",
                "docs/handoff/2026-05-05-also-good.md",
            ]
            with mock.patch.object(hmb, "_run", self._fake_run(enumerated=enumerated)):
                r = collect_handoff_multibranch(root)

            self.assertEqual(_kinds(r).count(_UNEXPECTED_PREFIX), 0,
                             "a well-formed enumeration must report no violation")
            self.assertEqual(len(r.data["tracks"]), 2, "both files must be collected")


class TestDatesAndLegacyIdentity(unittest.TestCase):
    """SC-4 / SC-13 — committer dates and legacy identity follow the real path."""

    def test_moved_file_dates(self):
        """SC-4 — ``updated_at`` semantics split across three cases.

        Case 1 is RECORDING-ONLY (same value before and after the change): a file
        committed at the top level and later ``git mv``-ed into ``archive/`` has
        BOTH its old and its new path touched by the move commit, so
        ``git log -1`` returns the move date either way. It exists so that
        whoever later reaches for ``--follow`` on ``_get_file_commit_date`` sees
        on the spot that it would not help.

        Case 2 is the discriminating one: a file that has NEVER existed at the
        top level gets a real, non-empty date only if the log is queried through
        its real relative path.

        Case 3: frontmatter wins over any git date.
        """
        with TemporaryDirectory() as tmp:
            root = _init_repo(tmp)

            # Case 1, step 1: born at the top level.
            _write(root, "2026-05-09-moved.md", "# no frontmatter\n")
            _commit(tmp, "born at top level", date="2026-05-09T10:00:00+00:00")
            # Case 1, step 2: moved into archive/ on a DIFFERENT date.
            (root / "docs" / "handoff" / "archive").mkdir(parents=True, exist_ok=True)
            _git(tmp, "mv", "docs/handoff/2026-05-09-moved.md",
                 "docs/handoff/archive/2026-05-09-moved.md")
            _commit(tmp, "move into archive", date="2026-08-15T10:00:00+00:00")

            # Case 2: never at the top level, no frontmatter.
            _write(root, "archive/2026-06-01-x.md", "# no frontmatter either\n")
            _commit(tmp, "archive-only file", date="2026-06-01T10:00:00+00:00")

            # Case 3: same shape but WITH frontmatter.
            _write(root, "archive/2026-07-01-with-fm.md",
                   _frontmatter("archive-fm-track", updated_at="2026-07-01T00:00:00Z"))
            branch = _publish(tmp, date="2026-08-20T10:00:00+00:00")

            r = collect_handoff_multibranch(root)
            tracks = r.data["tracks"]

            moved = _rows_by(tracks, branch=branch, filename="2026-05-09-moved.md")
            self.assertEqual(len(moved), 1, "the moved file must yield one row")
            self.assertTrue(
                moved[0]["updated_at"].startswith("2026-08-15"),
                f"recording-only: the move date is what git log returns, got "
                f"{moved[0]['updated_at']!r}")

            never_top = _rows_by(tracks, branch=branch, filename="2026-06-01-x.md")
            self.assertEqual(len(never_top), 1)
            self.assertTrue(
                never_top[0]["updated_at"].startswith("2026-06-01"),
                f"a file that never existed at the top level must still get its "
                f"own real commit date, got {never_top[0]['updated_at']!r}")

            with_fm = _rows_by(tracks, branch=branch, filename="2026-07-01-with-fm.md")
            self.assertEqual(len(with_fm), 1)
            self.assertEqual(with_fm[0]["updated_at"], "2026-07-01T00:00:00Z",
                             "frontmatter must win over any git date")

    def test_legacy_track_id_uses_rel_path(self):
        """SC-13 — two same-named files at different depths are two distinct tracks.

        ``docs/handoff/x.md`` and ``docs/handoff/archive/x.md``, both WITHOUT
        frontmatter, land in separate commits with explicitly pinned and
        different dates.

        RED on the B.1 baseline: enumeration reduces both to ``x.md``, so both
        rows get ``legacy:<branch>:x.md`` as their id and both resolve their date
        through the top-level path.

        Note (deliberately NOT asserted): these two legacy rows never fold into
        one another even today — ``dedupe_latest_per_track_container`` skips rows
        whose ``status`` is ``legacy`` before grouping, a documented passthrough.
        A "does not fold" assertion would therefore be green regardless of this
        change and was dropped from the criterion.
        """
        with TemporaryDirectory() as tmp:
            root = _init_repo(tmp)
            _write(root, "x.md", "# top level, no frontmatter\n")
            _commit(tmp, "top-level x", date="2026-03-01T10:00:00+00:00")
            _write(root, "archive/x.md", "# archived, no frontmatter\n")
            branch = _publish(tmp, date="2026-04-01T10:00:00+00:00")

            r = collect_handoff_multibranch(root)
            tracks = r.data["tracks"]
            legacy_rows = [t for t in tracks if t["legacy"]]

            self.assertEqual(len(legacy_rows), 2, f"expected two legacy rows, got {tracks!r}")
            self.assertEqual(
                {t["track_id"] for t in legacy_rows},
                {f"legacy:{branch}:x.md", f"legacy:{branch}:archive/x.md"},
                "legacy track_id must carry the relative path, not the basename")

            by_id = {t["track_id"]: t for t in legacy_rows}
            top = by_id[f"legacy:{branch}:x.md"]
            arch = by_id[f"legacy:{branch}:archive/x.md"]
            self.assertTrue(top["updated_at"].startswith("2026-03-01"),
                            f"top-level row must take its own commit date, got "
                            f"{top['updated_at']!r}")
            self.assertTrue(arch["updated_at"].startswith("2026-04-01"),
                            f"archived row must take its own commit date, got "
                            f"{arch['updated_at']!r}")
            self.assertNotEqual(top["updated_at"], arch["updated_at"],
                                "the two rows must not share a date")
            self.assertEqual(top["rel_path"], "x.md")
            self.assertEqual(arch["rel_path"], "archive/x.md")


class TestUnreadableAccounting(unittest.TestCase):
    """SC-5 / SC-14 — unreadable files are counted, never faked into legacy."""

    def test_unreadable_not_downgraded_to_legacy(self):
        """SC-5 — a file that cannot be read is reported, not invented as legacy.

        ``_read_file_content`` is patched to fail for one specific file so the
        failure is precise and independent of git's own error surface.

        RED on the B.1 baseline: the failure path currently appends a synthetic
        ``legacy: True`` row, so ``tracks[]`` contains it, ``legacy_count`` is
        bumped, and ``unreadable_count`` does not exist at all.
        """
        with TemporaryDirectory() as tmp:
            root = _init_repo(tmp)
            _write(root, "readable.md", _frontmatter("readable-track"))
            _write(root, "archive/unreadable.md", _frontmatter("unreadable-track"))
            branch = _publish(tmp)

            real_read = hmb._read_file_content

            def fake_read(project_root, branch_name, filename):
                if "unreadable" in filename:
                    return (None, "git show failed for <ref> (other, rc=128)")
                return real_read(project_root, branch_name, filename)

            with mock.patch.object(hmb, "_read_file_content", fake_read):
                r = collect_handoff_multibranch(root)

            tracks = r.data["tracks"]
            self.assertIn(_GIT_SHOW_FAILED, _kinds(r), "the failure must be signalled")
            self.assertEqual(
                _rows_by(tracks, branch=branch, filename="unreadable.md"), [],
                "an unreadable file must NOT be invented as a legacy track")
            self.assertEqual(r.data["legacy_count"], 0,
                             "an unreadable file is not a legacy track")
            self.assertEqual(r.data["unreadable_count"], 1)
            self.assertEqual(len(_rows_by(tracks, branch=branch, filename="readable.md")), 1,
                             "the readable neighbour must still be collected")

    def test_unreadable_count_present_on_failsoft_early_return(self):
        """SC-14 — the fail-soft early return carries ``unreadable_count`` too.

        The field claims to always exist with a default of 0; without this the
        only coverage would be the happy path, and the early-return dict is
        exactly where a "only fixed the normal path" implementation breaks
        consumers that index it directly.

        RED on the B.1 baseline: the early-return dict has six keys and
        ``unreadable_count`` is not one of them, so the direct index raises
        ``KeyError``.
        """
        with TemporaryDirectory() as tmp:
            root = _init_repo(tmp)
            _write(root, "unused.md", _frontmatter("unused-track"))
            _publish(tmp)

            def fake_list(project_root):
                return ([], "git for-each-ref permission denied (rc=128)")

            with mock.patch.object(hmb, "_list_origin_branches", fake_list):
                r = collect_handoff_multibranch(root)

            self.assertIn("handoff_multibranch_branch_list_failed", _kinds(r))
            self.assertTrue(r.data["errors"], "the message channel must be non-empty")
            self.assertEqual(r.data["tracks"], [])
            self.assertEqual(r.data["unreadable_count"], 0)


if __name__ == "__main__":
    unittest.main()

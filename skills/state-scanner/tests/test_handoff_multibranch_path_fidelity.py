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


# ── SC-2 frozen-baseline fixture ──────────────────────────────────────────────
#
# The fixture repo below is the SOT for both the frozen JSON under fixtures/ and
# the test that compares against it. Its file list AND its per-commit dates are
# part of the criterion: the no-frontmatter row takes its ``updated_at`` from
# ``git log -1 --format=%aI``, so without pinned dates the frozen JSON could
# never match a second run and the red would be unreproducible.
_FLAT_BASELINE_FIXTURE = "handoff-multibranch-flat-baseline-2026-09-25.json"
_FLAT_BASELINE_FILES = (
    # (rel path under docs/handoff, has frontmatter, commit date)
    ("2026-09-01-alpha.md", True, "2026-09-01T10:00:00+00:00"),
    ("2026-09-02-beta.md", False, "2026-09-02T10:00:00+00:00"),
)


def build_flat_baseline_repo(tmp: str) -> "tuple[Path, str]":
    """Build the SC-2 hermetic flat repo. Public: the fixture generator imports it.

    Single ``master`` branch, fixed file set, one commit per file with explicitly
    pinned dates. A hermetic repo (rather than this repo) is mandatory: the
    collector enumerates every ``refs/remotes/origin/*`` and emits one row per
    (branch, file), so running against a live repo would gain roughly one row per
    handoff doc the moment any branch is pushed.
    """
    root = _init_repo(tmp)
    for rel, has_fm, date in _FLAT_BASELINE_FILES:
        stem = rel[:-3]
        content = _frontmatter(f"flat-{stem}", updated_at="2026-09-01T00:00:00Z") \
            if has_fm else "# no frontmatter\n"
        _write(root, rel, content)
        _commit(tmp, f"add {rel}", date=date)
    branch = _publish_ref(tmp)
    return root, branch


def _load_freeze_corpus():
    """Import ``tests/fixtures/freeze_corpus.py`` by path.

    Loaded by file rather than re-typing its ``FIELDS`` tuple: that constant is
    the projection's single source of truth, and a copied literal would drift the
    moment the corpus schema changes.
    """
    import importlib.util

    path = _TESTS_DIR / "fixtures" / "freeze_corpus.py"
    spec = importlib.util.spec_from_file_location("_freeze_corpus_for_fidelity", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestCrossFileConsumers(unittest.TestCase):
    """SC-6 / SC-17 / SC-2 — consumers downstream of the collector."""

    def test_scan_ancestry_consumer_uses_relative_path(self):
        """SC-6 — the AC-5 ancestry probe must query the file's REAL path.

        ``tracks_data`` is produced end-to-end by ``collect_handoff_multibranch``
        on the same temp repo; hand-rolling it would mean the collector is never
        exercised and the counterfactual would go false.

        All four preconditions of ``_same_branch_head_unreachable_tracks`` are
        configured explicitly (non-empty ``current_branch``, ``detached_head``
        false, non-empty ``enforced_remotes``, and the track's ``branch`` equal to
        ``current_branch``) — any one of them missing makes the function return
        early with empty lists, which is green for the wrong reason.

        ``enforced_remotes`` deliberately contains a remote with no
        remote-tracking ref, which forces that track into ``inconclusive[]``.
        That is where assertion (c) lives — a REGRESSION LOCK, not a
        baseline-failing assertion: the reported ``filename`` must STAY a
        basename even though the git path composed for the probe becomes the
        relative path. Both values come from the same track, and keeping them
        apart is precisely what this change is about. Do not delete (c) for
        "not being red on the baseline" — it locks "must not change".
        """
        import scan

        with TemporaryDirectory() as tmp:
            root = _init_repo(tmp)
            _write(root, "archive/2026-05-09-session-end.md",
                   _frontmatter("session-end-20260509"))
            branch = _publish(tmp)

            tracks_data = collect_handoff_multibranch(root).data
            git_data = {"current_branch": branch, "detached_head": False}
            seen_cmds: "list[list[str]]" = []
            real_run = scan._run

            def spy(cmd, cwd, timeout=5):
                seen_cmds.append(list(cmd))
                return real_run(cmd, cwd, timeout=timeout)

            with mock.patch.object(scan, "_run", spy):
                _offenders, inconclusive = scan._same_branch_head_unreachable_tracks(
                    root, git_data, tracks_data, ["origin", "upstream"])

            log_paths = [c[-1] for c in seen_cmds if c[:3] == ["git", "log", "-1"]]
            self.assertIn("docs/handoff/archive/2026-05-09-session-end.md", log_paths,
                          f"the probe must query the real path, got {log_paths!r}")

            origin_probe = [c for c in seen_cmds
                            if c[:3] == ["git", "log", "-1"] and f"origin/{branch}" in c]
            self.assertEqual(len(origin_probe), 1, "origin must be probed exactly once")
            rc, out, _ = real_run(origin_probe[0], root, timeout=5)
            self.assertEqual(rc, 0, "the origin probe must succeed")
            self.assertTrue(out.strip(), "the origin probe must return a non-empty SHA")

            self.assertEqual(len(inconclusive), 1,
                             f"the unreachable remote must land in inconclusive, got "
                             f"{inconclusive!r}")
            self.assertEqual(inconclusive[0]["filename"], "2026-05-09-session-end.md",
                             "the REPORTED filename must stay a basename")
            self.assertNotIn("/", inconclusive[0]["filename"])

    def test_subdir_track_opens_cross_owner_collision(self):
        """SC-17 — a subdir handoff can flip ``collision.kind`` to ``cross_owner``.

        Two well-formed handoffs for the SAME ``track_id`` under DIFFERENT owner
        containers, one at the top level and one under ``archive/``, both with
        ``updated_at`` inside the Layer H window. ``now`` is pinned through the
        collector's own parameter — without it the criterion would silently turn
        red as the calendar moves past the window.

        RED on the B.1 baseline: the archived one is demoted to legacy with
        ``owner_container`` of ``"unknown"``, which the collidable filter drops,
        so only one container is left and ``kind`` stays ``"none"``.
        """
        from datetime import datetime, timezone

        pinned_now = datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)
        with TemporaryDirectory() as tmp:
            root = _init_repo(tmp)
            _write(root, "2026-05-09-shared.md",
                   _frontmatter("shared-track", oc="simonfish/c1", status="active",
                                updated_at="2026-05-09T10:00:00Z"))
            _write(root, "archive/2026-05-10-shared.md",
                   _frontmatter("shared-track", oc="aria-runner-bot/c2", status="active",
                                updated_at="2026-05-10T10:00:00Z"))
            _publish(tmp)

            r = collect_handoff_multibranch(root, now=pinned_now)

            self.assertEqual(r.data["legacy_count"], 0,
                             "both handoffs must be read as first-class tracks")
            self.assertNotIn(_GIT_SHOW_FAILED, _kinds(r))
            self.assertEqual(r.data["collision"]["kind"], "cross_owner")
            self.assertEqual(len(r.data["collision"]["groups"]), 1)

    def test_flat_repo_matches_frozen_baseline_projection(self):
        """SC-2 — a flat repo's behaviour is unchanged, compared through the projection.

        Fixture (file list and dates are part of the criterion): ``master`` only,
        ``2026-09-01-alpha.md`` WITH frontmatter committed at
        ``2026-09-01T10:00:00+00:00``, ``2026-09-02-beta.md`` WITHOUT frontmatter
        committed at ``2026-09-02T10:00:00+00:00``. The second file's
        ``updated_at`` comes from ``git log``, which is why the dates are pinned.

        Comparison goes through ``freeze_corpus.FIELDS`` (imported by path, not
        re-typed), an eight-field projection that does NOT include ``rel_path``.
        Comparing whole dicts would be permanently red under the adopted design,
        and the documented consequence of a permanently red assertion is that
        somebody trims it.
        """
        fc = _load_freeze_corpus()
        fixture = _TESTS_DIR / "fixtures" / _FLAT_BASELINE_FIXTURE
        self.assertTrue(fixture.exists(), f"frozen baseline missing: {fixture}")
        frozen = __import__("json").loads(fixture.read_text(encoding="utf-8"))
        self.assertEqual(tuple(frozen["fields"]), fc.FIELDS,
                         "the frozen projection must use the current FIELDS tuple")

        with TemporaryDirectory() as tmp:
            root, _branch = build_flat_baseline_repo(tmp)
            r = collect_handoff_multibranch(root)

        self.assertEqual(fc.trim(r.data["tracks"]), frozen["tracks"],
                         "a flat repo must project identically to the frozen baseline")
        self.assertEqual(r.data["legacy_count"], frozen["legacy_count"])


class TestDedupeSortKey(unittest.TestCase):
    """SC-7 and the fifth sort-key level."""

    @staticmethod
    def _row(rel_path: str, filename: str = "2026-07-19-x.md") -> dict:
        return {
            "track_id": "tie-track",
            "owner_container": "simonfish/c1",
            "phase": "B.2",
            "status": "active",
            "updated_at": "2026-07-19T10:00:00Z",
            "branch": "master",
            "filename": filename,
            "rel_path": rel_path,
            "legacy": False,
        }

    def test_dedupe_tiebreak_prefers_lexicographic_max_path(self):
        """characterization test — hypothetical input: dictionary-max filename wins.

        Two rows in one group with identical ``updated_at`` and ``filename``
        values of ``2026-07-19-x.md`` and ``archive/2026-07-19-x.md``: the
        dictionary-greatest one is selected.

        Under the adopted design the collector CANNOT produce a ``filename`` of
        ``archive/…`` (``filename`` is always a basename), so this records the
        dedupe function's behaviour on a hypothetical input rather than any
        behaviour change of this spec. It exists so that whoever later changes
        the sort semantics sees the current answer on the spot.
        """
        from collectors.handoff_multibranch import dedupe_latest_per_track_container

        top = self._row("2026-07-19-x.md", filename="2026-07-19-x.md")
        arch = self._row("archive/2026-07-19-x.md", filename="archive/2026-07-19-x.md")
        for rows in ([top, arch], [arch, top]):
            deduped, _stats = dedupe_latest_per_track_container(list(rows))
            self.assertEqual(len(deduped), 1)
            self.assertEqual(deduped[0]["filename"], "archive/2026-07-19-x.md",
                             "dictionary-max filename must win regardless of input order")

    def test_dedupe_fifth_level_prefers_toplevel_rel_path(self):
        """Fifth sort-key level — a top-level row beats any nested one, order-invariantly.

        Same-basename-different-directory rows tie on all four existing levels
        (parse_ok, updated_at, filename, branch), so today the winner is whichever
        row ``max()`` happened to see first — reverse the input and the winner
        changes. The fifth level makes the pick depend only on the rows' own
        fields: the top-level row (``rel_path == filename``) wins; among nested
        rows the dictionary-greatest ``rel_path`` wins.

        RED on the B.1 baseline: with only four levels the reversed input selects
        the other row.
        """
        from collectors.handoff_multibranch import dedupe_latest_per_track_container

        top = self._row("x.md", filename="x.md")
        arch = self._row("archive/x.md", filename="x.md")
        for rows in ([top, arch], [arch, top]):
            deduped, _stats = dedupe_latest_per_track_container(list(rows))
            self.assertEqual(len(deduped), 1)
            self.assertEqual(deduped[0]["rel_path"], "x.md",
                             "the top-level row must win regardless of input order")

        nested_a = self._row("archive/x.md", filename="x.md")
        nested_b = self._row("old/x.md", filename="x.md")
        for rows in ([nested_a, nested_b], [nested_b, nested_a]):
            deduped, _stats = dedupe_latest_per_track_container(list(rows))
            self.assertEqual(len(deduped), 1)
            self.assertEqual(deduped[0]["rel_path"], "old/x.md",
                             "among nested rows the dictionary-max rel_path must win")


class TestPointerRoundtrip(unittest.TestCase):
    """SC-15 — writer/collector pointer roundtrip across all six layouts.

    ``errors[]`` below always means the kind set of the ``CollectorResult``
    returned by ``collect_handoff`` — never ``data["errors"]``, which that
    collector does not even have.
    """

    _POINTER_MISSING = "handoff_pointer_target_missing"

    @staticmethod
    def _snapshot(tracks: "list[dict]") -> dict:
        return {"tracks_multibranch": {"tracks": tracks}}

    @staticmethod
    def _active_track(track_id: str, filename: str) -> dict:
        """Eight-field active row WITHOUT ``rel_path`` (old-snapshot shape).

        Mirrors ``test_p1_layer_h.py``'s own ``_active_track`` factory, which
        always carries ``filename`` and never ``rel_path`` — that is exactly the
        old-snapshot shape layout 3 needs.
        """
        return {
            "track_id": track_id,
            "owner_container": "devbox-A/sess-001",
            "phase": "B.2",
            "status": "active",
            "updated_at": "2026-05-20T10:00:00Z",
            "branch": "feature/test",
            "filename": filename,
            "legacy": False,
        }

    def _write_latest(self, root: Path, snapshot: dict) -> dict:
        from writers.latest_md_writer import write_latest_md

        return write_latest_md(snapshot, root / "docs" / "handoff" / "latest.md")

    def _handoff_kinds(self, root: Path) -> "list[str]":
        from collectors.handoff import collect_handoff

        return [e.get("error") for e in collect_handoff(root).errors]

    def test_pointer_roundtrip_toplevel(self):
        """SC-15 layout 1 — flat world roundtrip stays intact.

        Mostly a REGRESSION LOCK: the flat roundtrip already works on the B.1
        baseline, and what this guards is an over-eager guard breaking it.
        Assertion (i) is the baseline-failing part — ``degraded_reason`` is read
        with a DIRECT index on purpose: the baseline has no such key, so the
        index raises ``KeyError``. Written as ``.get()`` it would return ``None``
        on a missing key and be permanently green.

        All three steps run for real: collector, then writer, then the handoff
        collector reading back what the writer produced.
        """
        from collectors.handoff import collect_handoff

        with TemporaryDirectory() as tmp:
            root = _init_repo(tmp)
            _write(root, "2026-08-20-x.md", _frontmatter("toplevel-track", status="active"))
            _publish(tmp)

            tracks_data = collect_handoff_multibranch(root).data
            result = self._write_latest(root, self._snapshot(tracks_data["tracks"]))

            latest_text = (root / "docs" / "handoff" / "latest.md").read_text(encoding="utf-8")
            self.assertIn("[2026-08-20-x.md](./2026-08-20-x.md)", latest_text,
                          "(a) a real pointer must be written")

            handoff_data = collect_handoff(root).data
            self.assertEqual(handoff_data["latest_source"], "pointer", "(b)")
            self.assertEqual(handoff_data["latest_filename"], "2026-08-20-x.md", "(b)")
            self.assertNotIn(self._POINTER_MISSING, self._handoff_kinds(root), "(c)")
            self.assertIsNone(result["degraded_reason"], "(i) machine-readable face")

    def test_pointer_roundtrip_subdir_guarded(self):
        """SC-15 layout 2 — a subdir target must degrade, with a stated reason.

        FIXTURE COMPOSITION IS PART OF THE CRITERION: besides the one active
        track under ``archive/``, the top level keeps a non-active ``.md``. Take
        the fixture "minimally" (archive-only) and ``handoff.py``'s
        ``canonical_files`` comes back empty, ``collect_handoff`` returns early,
        and ``handoff_pointer_target_missing`` becomes structurally impossible —
        assertion (e) would then be green no matter whether the guard exists.

        (d) has two halves with different power. The first half ("no real
        pointer") is ALSO true on the baseline, but for an unrelated reason: the
        archived file is demoted to legacy there, leaving zero active tracks, so
        the writer takes the ``skipped`` branch and writes a placeholder page.
        Only the second half — the degraded text naming the subdir reason — is
        baseline-failing. (h) is the machine-readable counterpart.
        """
        with TemporaryDirectory() as tmp:
            root = _init_repo(tmp)
            _write(root, "archive/2026-08-20-x.md",
                   _frontmatter("subdir-track", status="active"))
            _write(root, "2026-05-01-old.md",
                   _frontmatter("old-track", status="done",
                                updated_at="2026-05-01T10:00:00Z"))
            _publish(tmp)

            tracks_data = collect_handoff_multibranch(root).data
            result = self._write_latest(root, self._snapshot(tracks_data["tracks"]))

            latest_text = (root / "docs" / "handoff" / "latest.md").read_text(encoding="utf-8")
            self.assertNotIn("**Latest**: [", latest_text,
                             "(d) first half: no real pointer line")
            self.assertNotIn("[2026-08-20-x.md](./2026-08-20-x.md)", latest_text,
                             "(d) without the guard the writer emits exactly this "
                             "basename link, with no directory segment")
            self.assertIn("子目录", latest_text,
                          "(d) second half: the degraded text must name the subdir reason")
            self.assertNotIn(self._POINTER_MISSING, self._handoff_kinds(root),
                             "(e) regression lock on the guard")
            self.assertEqual(result["degraded_reason"], "target_in_subdir", "(h)")

    def test_pointer_written_when_rel_path_key_absent(self):
        """SC-15 layout 3 — an old snapshot without ``rel_path`` still gets a pointer.

        REGRESSION LOCK for the missing-key fallback, plus (j) as the
        baseline-failing half. This is the ONLY layout that covers the
        missing-key branch: layouts 1 and 2 are produced end-to-end by the new
        collector, where ``rel_path`` always exists.

        Counterfactual it guards: writing the predicate as
        ``track.get("rel_path") != filename`` makes a missing key compare as
        ``None != filename`` — permanently true — so every old snapshot would
        degrade.
        """
        with TemporaryDirectory() as tmp:
            root = _init_repo(tmp)
            (root / "docs" / "handoff").mkdir(parents=True, exist_ok=True)
            snapshot = self._snapshot([self._active_track("old-snap-track", "x.md")])

            result = self._write_latest(root, snapshot)

            latest_text = (root / "docs" / "handoff" / "latest.md").read_text(encoding="utf-8")
            self.assertIn("[x.md](./x.md)", latest_text,
                          "(g) a missing rel_path key must still yield a real pointer")
            self.assertIsNone(result["degraded_reason"], "(j) machine-readable face")

    def test_degraded_reason_present_when_no_active_track(self):
        """SC-15 layout 4 — the ``skipped`` branch carries the key too.

        Pins the "always present" contract on the branch the other layouts never
        reach. Without it, an implementation that adds the key only on the
        pointer branch passes every other assertion while the public contract in
        ``references/phase-1-collectors.md`` declares a key that does not exist
        on two of three branches.
        """
        with TemporaryDirectory() as tmp:
            root = _init_repo(tmp)
            result = self._write_latest(root, self._snapshot([]))

            self.assertEqual(result["action"], "skipped")
            self.assertIsNone(result["degraded_reason"])

    def test_degraded_reason_present_on_multi_track_banner(self):
        """SC-15 layout 5 — the ``banner`` branch carries the key too.

        Same contract as layout 4, on the other non-pointer branch.
        """
        with TemporaryDirectory() as tmp:
            root = _init_repo(tmp)
            snapshot = self._snapshot([
                self._active_track("track-a", "2026-05-20-a.md"),
                self._active_track("track-b", "2026-05-21-b.md"),
            ])
            result = self._write_latest(root, snapshot)

            self.assertEqual(result["action"], "banner")
            self.assertIsNone(result["degraded_reason"])

    def test_degraded_reason_missing_filename_when_filename_absent(self):
        """SC-15 layout 6 — the third enumeration value, ``missing_filename``.

        ``degraded_reason`` is a three-value enum, and this branch has zero tests
        today: every ``_active_track`` factory in the suite always carries
        ``filename``. Without this layout an implementation could emit any string
        here — even reuse ``target_in_subdir`` — and stay green, while this spec
        is actively changing that very function's signature and wording.
        """
        with TemporaryDirectory() as tmp:
            root = _init_repo(tmp)
            track = self._active_track("no-filename-track", "placeholder.md")
            del track["filename"]
            result = self._write_latest(root, self._snapshot([track]))

            self.assertEqual(result["action"], "pointer",
                             "a single active track still takes the pointer branch")
            self.assertEqual(result["degraded_reason"], "missing_filename")


if __name__ == "__main__":
    unittest.main()

"""Phase 1.15 handoff collector tests (H0 spec 2026-05-14).

Covers:
- mtime sort DESC (latest_path correctness)
- age_hours computation (epoch-based, no timezone skew)
- misplaced_files detection (.aria/handoff/*.md)
- additive field (snapshot field present + schema_version stays "1.0")
- Edge: empty docs/handoff/
- Edge: docs/handoff/ missing
- Edge: non-UTF-8 filenames (Linux-only; defensively skipped)
- soft_error on stat() failure
"""

from __future__ import annotations

import os
import time
import unittest
from pathlib import Path

from _helpers import tmp_project, write_file
from collectors.handoff import collect_handoff


def _touch(path: Path, mtime_offset: float) -> None:
    """Set both atime+mtime to (now + offset) seconds."""
    target = time.time() + mtime_offset
    os.utime(path, (target, target))


class TestHandoffMtimeSort(unittest.TestCase):
    """latest_path should reflect newest file by mtime, not lexical order."""

    def test_newest_by_mtime_wins(self):
        with tmp_project() as root:
            handoff = root / "docs" / "handoff"
            handoff.mkdir(parents=True)
            # Lexically oldest filename, but newest mtime
            (handoff / "2020-01-01-old-name.md").write_text("# old name\n", encoding="utf-8")
            (handoff / "2026-05-01-middle.md").write_text("# middle\n", encoding="utf-8")
            (handoff / "2026-04-01-newest-by-mtime.md").write_text("# winner\n", encoding="utf-8")
            # Make 2020-01-01-old-name the most recently modified
            _touch(handoff / "2020-01-01-old-name.md", mtime_offset=0)
            _touch(handoff / "2026-05-01-middle.md", mtime_offset=-3600)
            _touch(handoff / "2026-04-01-newest-by-mtime.md", mtime_offset=-7200)

            r = collect_handoff(root)

            self.assertTrue(r.data["exists"])
            self.assertEqual(r.data["latest_filename"], "2020-01-01-old-name.md")
            self.assertEqual(r.data["latest_path"], "docs/handoff/2020-01-01-old-name.md")

    def test_age_hours_is_epoch_based(self):
        with tmp_project() as root:
            handoff = root / "docs" / "handoff"
            handoff.mkdir(parents=True)
            f = handoff / "foo.md"
            f.write_text("# foo\n", encoding="utf-8")
            # Set mtime to ~2.5h ago
            _touch(f, mtime_offset=-2.5 * 3600)

            r = collect_handoff(root)

            # Expect ~2.5h, within 0.1h tolerance (test execution time)
            self.assertIsNotNone(r.data["age_hours"])
            self.assertGreater(r.data["age_hours"], 2.4)
            self.assertLess(r.data["age_hours"], 2.6)


class TestMisplacedDetection(unittest.TestCase):
    """misplaced_files lists ALL .aria/handoff/*.md, sorted, relative paths."""

    def test_misplaced_files_listed_when_present(self):
        with tmp_project() as root:
            # Canonical empty
            # Forbidden has 3 files
            forbidden = root / ".aria" / "handoff"
            forbidden.mkdir(parents=True)
            (forbidden / "z-last.md").write_text("# z\n", encoding="utf-8")
            (forbidden / "a-first.md").write_text("# a\n", encoding="utf-8")
            (forbidden / "m-middle.md").write_text("# m\n", encoding="utf-8")

            r = collect_handoff(root)

            self.assertEqual(
                r.data["misplaced_files"],
                [
                    ".aria/handoff/a-first.md",
                    ".aria/handoff/m-middle.md",
                    ".aria/handoff/z-last.md",
                ],
            )
            self.assertFalse(r.data["exists"])  # canonical empty
            self.assertIsNone(r.data["latest_path"])

    def test_no_misplaced_when_clean(self):
        with tmp_project() as root:
            (root / "docs" / "handoff").mkdir(parents=True)
            (root / "docs" / "handoff" / "ok.md").write_text("# ok\n", encoding="utf-8")
            # .aria/handoff/ doesn't exist at all

            r = collect_handoff(root)

            self.assertEqual(r.data["misplaced_files"], [])
            self.assertTrue(r.data["exists"])

    def test_aria_handoff_with_non_md_does_not_count(self):
        """Non-.md files in .aria/handoff/ are NOT misplaced (matches L1 hook pattern)."""
        with tmp_project() as root:
            forbidden = root / ".aria" / "handoff"
            forbidden.mkdir(parents=True)
            (forbidden / "README.json").write_text("{}", encoding="utf-8")
            (forbidden / "notes.txt").write_text("notes", encoding="utf-8")

            r = collect_handoff(root)

            self.assertEqual(r.data["misplaced_files"], [])


class TestSchemaAdditive(unittest.TestCase):
    """Field shape must be stable and snapshot version stays 1.0."""

    def test_returned_data_has_all_eight_keys(self):
        with tmp_project() as root:
            (root / "docs" / "handoff").mkdir(parents=True)
            (root / "docs" / "handoff" / "foo.md").write_text("# foo\n", encoding="utf-8")

            r = collect_handoff(root)

            expected_keys = {
                "exists",
                "latest_path",
                "latest_filename",
                "last_modified_iso",
                "age_hours",
                "latest_source",  # H5 fix — added
                "misplaced_files",
                "canonical_dir",
            }
            self.assertEqual(set(r.data.keys()), expected_keys)
            self.assertEqual(r.data["canonical_dir"], "docs/handoff/")

    def test_iso_timestamp_is_utc(self):
        with tmp_project() as root:
            (root / "docs" / "handoff").mkdir(parents=True)
            f = root / "docs" / "handoff" / "foo.md"
            f.write_text("# foo\n", encoding="utf-8")

            r = collect_handoff(root)

            iso = r.data["last_modified_iso"]
            self.assertIsNotNone(iso)
            # ISO 8601 UTC ends with +00:00 (timezone-aware)
            self.assertTrue(iso.endswith("+00:00"), f"Expected UTC suffix, got {iso}")


class TestLatestPointerPriority(unittest.TestCase):
    """H5 fix: latest.md pointer is the human-maintained semantic 'latest';
    mtime-max only wins when pointer absent/unparseable/stale.

    Scenario: a predecessor handoff edited post-hoc (closeout / rebase)
    gets the newest mtime and would otherwise shadow the real latest.
    """

    def _write_pointer(self, handoff: Path, target: str) -> None:
        (handoff / "latest.md").write_text(
            f"# Aria Handoff — Latest\n\n"
            f"**Latest**: [{target}](./{target}) — desc\n",
            encoding="utf-8",
        )

    def test_pointer_wins_over_newer_mtime(self):
        with tmp_project() as root:
            handoff = root / "docs" / "handoff"
            handoff.mkdir(parents=True)
            (handoff / "2026-05-15-real-latest.md").write_text("# real\n", encoding="utf-8")
            (handoff / "2026-05-10-old-predecessor.md").write_text("# old\n", encoding="utf-8")
            self._write_pointer(handoff, "2026-05-15-real-latest.md")
            # Predecessor edited post-hoc → newest mtime (the H5 trap)
            _touch(handoff / "2026-05-10-old-predecessor.md", mtime_offset=0)
            _touch(handoff / "2026-05-15-real-latest.md", mtime_offset=-7200)

            r = collect_handoff(root)

            self.assertEqual(r.data["latest_filename"], "2026-05-15-real-latest.md")
            self.assertEqual(r.data["latest_source"], "pointer")
            self.assertEqual(r.errors, [])

    def test_no_pointer_falls_back_to_mtime(self):
        with tmp_project() as root:
            handoff = root / "docs" / "handoff"
            handoff.mkdir(parents=True)
            (handoff / "a.md").write_text("# a\n", encoding="utf-8")
            (handoff / "b.md").write_text("# b\n", encoding="utf-8")
            _touch(handoff / "b.md", mtime_offset=0)
            _touch(handoff / "a.md", mtime_offset=-3600)
            # No latest.md pointer at all

            r = collect_handoff(root)

            self.assertEqual(r.data["latest_filename"], "b.md")
            self.assertEqual(r.data["latest_source"], "mtime")

    def test_stale_pointer_falls_back_to_mtime_with_soft_error(self):
        with tmp_project() as root:
            handoff = root / "docs" / "handoff"
            handoff.mkdir(parents=True)
            (handoff / "exists.md").write_text("# e\n", encoding="utf-8")
            self._write_pointer(handoff, "2026-99-99-deleted.md")  # target absent

            r = collect_handoff(root)

            self.assertEqual(r.data["latest_filename"], "exists.md")
            self.assertEqual(r.data["latest_source"], "mtime")
            error_kinds = {e["error"] for e in r.errors}
            self.assertIn("handoff_pointer_target_missing", error_kinds)

    def test_pointer_targeting_itself_ignored(self):
        with tmp_project() as root:
            handoff = root / "docs" / "handoff"
            handoff.mkdir(parents=True)
            (handoff / "real.md").write_text("# real\n", encoding="utf-8")
            self._write_pointer(handoff, "latest.md")  # degenerate self-ref

            r = collect_handoff(root)

            # Falls back to mtime (only real.md qualifies)
            self.assertEqual(r.data["latest_filename"], "real.md")
            self.assertEqual(r.data["latest_source"], "mtime")


class TestLatestPointerExclusion(unittest.TestCase):
    """QA-M2 fix: `latest.md` is a pointer file, not a handoff doc.

    Including it would make mtime sort always surface the pointer
    (which is updated on every handoff write), instead of the actual
    newest handoff doc.
    """

    def test_latest_md_not_picked_as_latest(self):
        with tmp_project() as root:
            handoff = root / "docs" / "handoff"
            handoff.mkdir(parents=True)
            (handoff / "2026-05-01-real.md").write_text("# real\n", encoding="utf-8")
            (handoff / "latest.md").write_text("# pointer\n", encoding="utf-8")
            # latest.md mtime is newer (just written after the other)
            _touch(handoff / "latest.md", mtime_offset=0)
            _touch(handoff / "2026-05-01-real.md", mtime_offset=-3600)

            r = collect_handoff(root)

            self.assertEqual(r.data["latest_filename"], "2026-05-01-real.md")
            self.assertNotEqual(r.data["latest_filename"], "latest.md")

    def test_only_pointer_in_dir_yields_empty(self):
        with tmp_project() as root:
            handoff = root / "docs" / "handoff"
            handoff.mkdir(parents=True)
            (handoff / "latest.md").write_text("# pointer\n", encoding="utf-8")

            r = collect_handoff(root)

            self.assertFalse(r.data["exists"])
            self.assertIsNone(r.data["latest_path"])


class TestPermissionErrors(unittest.TestCase):
    """QA-M1 fix: permission-denied directory must emit soft_error,
    not silently return exists=False with empty errors[]."""

    def test_canonical_unreadable_emits_soft_error(self):
        with tmp_project() as root:
            handoff = root / "docs" / "handoff"
            handoff.mkdir(parents=True)
            (handoff / "ok.md").write_text("# ok\n", encoding="utf-8")
            # Make dir unreadable (chmod 000)
            os.chmod(handoff, 0o000)
            try:
                r = collect_handoff(root)

                self.assertFalse(r.data["exists"])
                # Must have at least one error entry naming the scan failure
                error_kinds = {e["error"] for e in r.errors}
                self.assertIn("handoff_canonical_scan_failed", error_kinds)
            finally:
                # Restore so tempdir cleanup works
                os.chmod(handoff, 0o755)


class TestHookSmokeIntegration(unittest.TestCase):
    """QA-M3 fix: wrap shell hook smoke test so run_tests.py discovers it."""

    def test_hook_smoke_test_passes(self):
        import subprocess

        tests_dir = Path(__file__).resolve().parent
        smoke_script = tests_dir / "test_handoff_hook.sh"
        if not smoke_script.is_file():
            self.skipTest(f"hook smoke script not found at {smoke_script}")

        r = subprocess.run(
            ["bash", str(smoke_script)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            r.returncode,
            0,
            msg=f"hook smoke test failed (rc={r.returncode}):\n{r.stdout}\n{r.stderr}",
        )
        self.assertIn("PASS: 10", r.stdout)
        self.assertIn("FAIL: 0", r.stdout)


class TestEdgeCases(unittest.TestCase):
    """Defensive edge cases per proposal §Risk and Success Criteria."""

    def test_canonical_dir_empty(self):
        with tmp_project() as root:
            (root / "docs" / "handoff").mkdir(parents=True)  # empty dir

            r = collect_handoff(root)

            self.assertFalse(r.data["exists"])
            self.assertIsNone(r.data["latest_path"])
            self.assertIsNone(r.data["last_modified_iso"])
            self.assertIsNone(r.data["age_hours"])
            self.assertEqual(r.data["misplaced_files"], [])
            self.assertEqual(r.data["canonical_dir"], "docs/handoff/")

    def test_canonical_dir_missing(self):
        with tmp_project() as root:
            # docs/handoff/ doesn't exist at all
            r = collect_handoff(root)

            self.assertFalse(r.data["exists"])
            self.assertIsNone(r.data["latest_path"])
            self.assertEqual(r.data["misplaced_files"], [])

    def test_both_dirs_populated(self):
        """Drift state — exists=true AND misplaced_files non-empty."""
        with tmp_project() as root:
            (root / "docs" / "handoff").mkdir(parents=True)
            (root / "docs" / "handoff" / "good.md").write_text("# g\n", encoding="utf-8")
            (root / ".aria" / "handoff").mkdir(parents=True)
            (root / ".aria" / "handoff" / "bad.md").write_text("# b\n", encoding="utf-8")

            r = collect_handoff(root)

            self.assertTrue(r.data["exists"])
            self.assertEqual(r.data["latest_filename"], "good.md")
            self.assertEqual(r.data["misplaced_files"], [".aria/handoff/bad.md"])

    def test_no_errors_on_happy_path(self):
        with tmp_project() as root:
            (root / "docs" / "handoff").mkdir(parents=True)
            (root / "docs" / "handoff" / "foo.md").write_text("# foo\n", encoding="utf-8")

            r = collect_handoff(root)

            self.assertEqual(r.errors, [])


if __name__ == "__main__":
    unittest.main()

"""#166 defect 1 — openspec/ exists but changes/ missing.

Spec `state-scanner-openspec-collector-false-green`: the collector must no longer
return a silent all-zero payload (configured=False, archive.total=0) when
`openspec/` exists but `openspec/changes/` has vanished (git drops empty dirs
after the last spec is archived). It must (a) still scan `archive/` orthogonally
and (b) emit a `layout_drift` soft_error when there is evidence of prior/misplaced
OpenSpec use — while staying silent for a genuine cold-start / non-OpenSpec repo.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from _helpers import tmp_project, write_file
from collectors._common import CollectorResult
from collectors.openspec import _detect_stray_openspec_artifacts, collect_openspec


def _archived(root, name: str) -> None:
    write_file(
        root / "openspec" / "archive" / name / "proposal.md",
        "# archived\n\n> **Status**: Complete\n",
    )


class TestLayoutDriftDefect1(unittest.TestCase):
    def test_changes_missing_archive_present_emits_drift_and_scans_archive(self):
        # SC-1: openspec/ exists, changes/ missing, archive/ has 2 →
        #       errors contains layout_drift AND archive.total == 2 (not silent 0).
        with tmp_project() as root:
            (root / "openspec").mkdir()
            _archived(root, "2026-01-01-foo")
            _archived(root, "2026-01-02-bar")
            r = collect_openspec(root)
            kinds = {e["error"] for e in r.errors}
            self.assertIn("layout_drift", kinds)
            self.assertEqual(r.data["archive"]["total"], 2)

    def test_cold_start_no_drift(self):
        # SC-2 negative control: openspec/ exists (only project.md), no changes/,
        #       no archive/, no stray proposal → NO layout_drift + configured False.
        with tmp_project() as root:
            (root / "openspec").mkdir()
            write_file(root / "openspec" / "project.md", "# project\n")
            r = collect_openspec(root)
            kinds = {e["error"] for e in r.errors}
            self.assertNotIn("layout_drift", kinds)
            self.assertFalse(r.data["configured"])

    def test_drift_detail_names_stray_bare_md(self):
        # SC-3 (shape a): bare *proposal*.md directly under openspec/ named in detail.
        with tmp_project() as root:
            (root / "openspec").mkdir()
            write_file(root / "openspec" / "my-change-proposal.md", "> **Status**: Draft\n")
            r = collect_openspec(root)
            drift = [e for e in r.errors if e["error"] == "layout_drift"]
            self.assertTrue(drift, "layout_drift expected for stray bare proposal")
            self.assertIn("my-change-proposal.md", drift[0]["detail"])

    def test_drift_detail_names_stray_subdir(self):
        # SC-3 (shape b): subdir-with-proposal.md not under changes/ named in detail.
        with tmp_project() as root:
            (root / "openspec").mkdir()
            write_file(root / "openspec" / "some-feature" / "proposal.md", "> **Status**: Draft\n")
            r = collect_openspec(root)
            drift = [e for e in r.errors if e["error"] == "layout_drift"]
            self.assertTrue(drift, "layout_drift expected for stray proposal subdir")
            self.assertIn("some-feature", drift[0]["detail"])

    def test_drift_configured_stays_false(self):
        # SC-4: drift path keeps configured == False (documented `changes/ exists` semantics).
        with tmp_project() as root:
            (root / "openspec").mkdir()
            _archived(root, "2026-01-01-foo")
            r = collect_openspec(root)
            self.assertFalse(r.data["configured"])

    def test_no_openspec_dir_stays_silent(self):
        # guard: openspec/ absent entirely → configured False, NO layout_drift
        #        (genuinely not using OpenSpec — must not scream).
        with tmp_project() as root:
            r = collect_openspec(root)
            kinds = {e["error"] for e in r.errors}
            self.assertNotIn("layout_drift", kinds)
            self.assertFalse(r.data["configured"])


class TestUnreadableSurfaces(unittest.TestCase):
    """#166 review follow-up (silent-failure-hunter): an unreadable openspec/ or
    archive/ must SCREAM (soft_error), not silently look like a clean non-OpenSpec
    repo — that is the very false-green this change exists to kill — and must not
    crash the whole scan either.
    """

    def test_unreadable_openspec_emits_soft_error(self):
        with tmp_project() as root:
            (root / "openspec").mkdir()
            r = CollectorResult()
            with mock.patch.object(Path, "iterdir", side_effect=PermissionError("denied")):
                stray = _detect_stray_openspec_artifacts(root / "openspec", r)
            self.assertEqual(stray, [])
            self.assertIn("openspec_scan_failed", {e["error"] for e in r.errors})

    def test_unreadable_archive_soft_errors_without_crashing(self):
        with tmp_project() as root:
            (root / "openspec" / "archive").mkdir(parents=True)
            real_iterdir = Path.iterdir

            def _boom(self):
                if self.name == "archive":
                    raise PermissionError("denied")
                return real_iterdir(self)

            with mock.patch.object(Path, "iterdir", _boom):
                r = collect_openspec(root)  # must not raise
            self.assertIn("openspec_scan_failed", {e["error"] for e in r.errors})


if __name__ == "__main__":
    unittest.main()

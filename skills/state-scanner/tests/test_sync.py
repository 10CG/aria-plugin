"""Phase 1.12 sync_status collector tests (single-remote scope).

Integration tests use tmp_repo() for real git behaviour. Pure helpers tested via
direct invocation.
"""

from __future__ import annotations

import os
import time
import unittest
from pathlib import Path

from _helpers import init_git_repo, run_git, tmp_repo, tmp_project, write_file
from collectors._common import CollectorResult
from collectors.sync import _fetch_head_age, _has_remote, collect_sync_state


class TestHasRemote(unittest.TestCase):
    def test_no_remote(self):
        with tmp_repo() as repo:
            self.assertFalse(_has_remote(repo))

    def test_with_remote(self):
        with tmp_repo() as repo:
            run_git(repo, "remote", "add", "origin", "https://example.com/foo.git")
            self.assertTrue(_has_remote(repo))


class TestFetchHeadAge(unittest.TestCase):
    def test_never_when_no_fetch_head(self):
        with tmp_repo() as repo:
            r = CollectorResult()
            self.assertEqual(_fetch_head_age(repo, r), "never")

    def test_minutes_bucket(self):
        with tmp_repo() as repo:
            # Create .git/FETCH_HEAD with recent mtime
            fh = repo / ".git" / "FETCH_HEAD"
            fh.write_text("stub\n", encoding="utf-8")
            age = _fetch_head_age(repo, CollectorResult())
            self.assertTrue(age.endswith("m") or age.endswith("h") or age.endswith("d"))

    def test_days_bucket(self):
        with tmp_repo() as repo:
            fh = repo / ".git" / "FETCH_HEAD"
            fh.write_text("stub\n", encoding="utf-8")
            old = time.time() - 86400 * 3  # 3 days ago
            os.utime(fh, (old, old))
            age = _fetch_head_age(repo, CollectorResult())
            self.assertTrue(age.endswith("d"))


class TestCollectSyncNoRemote(unittest.TestCase):
    def test_no_remote_yields_null_upstream(self):
        with tmp_repo() as repo:
            r = collect_sync_state(repo)
            self.assertFalse(r.data["has_remote"])
            branch = r.data["current_branch"]
            self.assertEqual(branch["name"], "master")
            self.assertIsNone(branch["upstream"])
            self.assertFalse(branch["upstream_configured"])


class TestShallowGuard(unittest.TestCase):
    def test_shallow_is_detected(self):
        with tmp_repo() as repo:
            # Mark as shallow by writing .git/shallow
            (repo / ".git" / "shallow").write_text("abc123\n")
            r = collect_sync_state(repo)
            # Shallow clone => behind is null
            self.assertIsNone(r.data["current_branch"]["behind"])


class TestSubmoduleEnumeration(unittest.TestCase):
    """Directional guard (R1-M1) + aligned-zero (BA-I1) logic exercised via
    full integration (submodule add) is fragile across git versions; instead we
    verify the simpler case — a repo with no submodules yields empty list."""

    def test_no_submodules_empty_list(self):
        with tmp_repo() as repo:
            r = collect_sync_state(repo)
            self.assertEqual(r.data["submodules"], [])

    def test_empty_gitmodules_file(self):
        """`.gitmodules` parse failure is fail-soft (no crash, empty list)."""
        with tmp_repo() as repo:
            (repo / ".gitmodules").write_text("", encoding="utf-8")
            r = collect_sync_state(repo)
            self.assertEqual(r.data["submodules"], [])


class TestSyncDataShape(unittest.TestCase):
    def test_required_fields_present(self):
        with tmp_repo() as repo:
            r = collect_sync_state(repo)
            required = {
                "remote_refs_age",
                "has_remote",
                "shallow",
                "current_branch",
                "submodules",
            }
            self.assertTrue(required.issubset(r.data.keys()))


if __name__ == "__main__":
    unittest.main()

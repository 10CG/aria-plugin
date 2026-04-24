"""Phase 1.12 multi_remote parity collector tests.

Focuses on _aggregate_flags (pure function) and the not-a-git-repo fallback.
"""

from __future__ import annotations

import unittest

from _helpers import tmp_project, tmp_repo
from collectors.multi_remote import _aggregate_flags, collect_multi_remote


class TestAggregateFlags(unittest.TestCase):
    def test_empty_input_is_not_parity(self):
        """QA-C1: zero evidence → overall_parity=False."""
        flags = _aggregate_flags([])
        self.assertFalse(flags["overall_parity"])

    def test_single_equal_remote(self):
        flags = _aggregate_flags([{"parity": "equal", "reachable": True}])
        self.assertTrue(flags["overall_parity"])

    def test_equal_plus_ahead_is_parity(self):
        """Ahead = pending push, not a parity blocker."""
        flags = _aggregate_flags(
            [
                {"parity": "equal", "reachable": True},
                {"parity": "ahead", "reachable": True},
            ]
        )
        self.assertTrue(flags["overall_parity"])
        self.assertTrue(flags["has_pending_push"])

    def test_behind_blocks_parity(self):
        flags = _aggregate_flags(
            [
                {"parity": "equal", "reachable": True},
                {"parity": "behind", "reachable": True},
            ]
        )
        self.assertFalse(flags["overall_parity"])

    def test_diverged_blocks_parity(self):
        flags = _aggregate_flags([{"parity": "diverged", "reachable": True}])
        self.assertFalse(flags["overall_parity"])

    def test_unknown_network_reason_surfaces_unreachable(self):
        flags = _aggregate_flags(
            [{"parity": "unknown", "reason": "network_timeout", "reachable": False}]
        )
        self.assertTrue(flags["has_unreachable_remote"])
        self.assertFalse(flags["overall_parity"])  # no equal evidence

    def test_only_ahead_without_equal_is_not_parity(self):
        """QA-C1 subtle case: ahead alone is no positive evidence."""
        flags = _aggregate_flags([{"parity": "ahead", "reachable": True}])
        self.assertFalse(flags["overall_parity"])
        self.assertTrue(flags["has_pending_push"])


class TestCollectorNotAGitRepo(unittest.TestCase):
    def test_tmpdir_without_git(self):
        """R1-C1 fix: not-a-git-repo must return overall_parity=False (not True)."""
        with tmp_project() as root:
            r = collect_multi_remote(root)
            self.assertTrue(r.data["enabled"])
            self.assertFalse(r.data["overall_parity"])
            self.assertEqual(r.data["submodules"], [])


class TestCollectorGitRepoNoRemote(unittest.TestCase):
    def test_git_repo_no_remote(self):
        """Empty remotes list aggregates to overall_parity=False (QA-C1)."""
        with tmp_repo() as repo:
            r = collect_multi_remote(repo)
            self.assertTrue(r.data["enabled"])
            self.assertFalse(r.data["overall_parity"])


class TestCollectorDisabled(unittest.TestCase):
    def test_config_disabled(self):
        import json

        from _helpers import write_file

        with tmp_repo() as repo:
            write_file(
                repo / ".aria" / "config.json",
                json.dumps(
                    {
                        "state_scanner": {
                            "multi_remote": {"enabled": False}
                        }
                    }
                ),
            )
            r = collect_multi_remote(repo)
            self.assertFalse(r.data["enabled"])
            self.assertEqual(len(r.data), 1)


if __name__ == "__main__":
    unittest.main()

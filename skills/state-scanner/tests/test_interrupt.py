"""Phase 0 interrupt collector tests."""

from __future__ import annotations

import json
import unittest

from _helpers import tmp_repo, write_file
from collectors.interrupt import collect_interrupt_state


class TestInterruptAbsent(unittest.TestCase):
    def test_no_state_file(self):
        with tmp_repo() as repo:
            r = collect_interrupt_state(repo)
            self.assertFalse(r.data["present"])
            self.assertEqual(r.data["status"], "none")
            self.assertIsNone(r.data["raw"])
            self.assertEqual(r.errors, [])


class TestInterruptPresent(unittest.TestCase):
    def test_in_progress_with_matching_anchor(self):
        with tmp_repo(branch="master") as repo:
            write_file(
                repo / ".aria" / "workflow-state.json",
                json.dumps(
                    {"status": "in_progress", "git_anchor": {"branch": "master"}}
                ),
            )
            r = collect_interrupt_state(repo)
            self.assertTrue(r.data["present"])
            self.assertEqual(r.data["status"], "in_progress")
            self.assertTrue(r.data["branch_anchor_match"])

    def test_in_progress_with_mismatched_anchor(self):
        with tmp_repo(branch="master") as repo:
            write_file(
                repo / ".aria" / "workflow-state.json",
                json.dumps(
                    {
                        "status": "in_progress",
                        "git_anchor": {"branch": "other-branch"},
                    }
                ),
            )
            r = collect_interrupt_state(repo)
            self.assertEqual(r.data["status"], "in_progress")
            self.assertFalse(r.data["branch_anchor_match"])

    def test_failed_status_preserved(self):
        with tmp_repo() as repo:
            write_file(
                repo / ".aria" / "workflow-state.json",
                json.dumps({"status": "failed", "git_anchor": {"branch": "master"}}),
            )
            r = collect_interrupt_state(repo)
            self.assertEqual(r.data["status"], "failed")

    def test_suspended_status_preserved(self):
        with tmp_repo() as repo:
            write_file(
                repo / ".aria" / "workflow-state.json",
                json.dumps(
                    {"status": "suspended", "git_anchor": {"branch": "master"}}
                ),
            )
            r = collect_interrupt_state(repo)
            self.assertEqual(r.data["status"], "suspended")


class TestInterruptCorrupted(unittest.TestCase):
    def test_malformed_json(self):
        with tmp_repo() as repo:
            write_file(repo / ".aria" / "workflow-state.json", "{not valid json")
            r = collect_interrupt_state(repo)
            self.assertEqual(r.data["status"], "corrupted")
            self.assertTrue(r.data["present"])
            self.assertEqual(len(r.errors), 1)
            self.assertEqual(r.errors[0]["error"], "workflow_state_corrupted")

    def test_empty_file(self):
        with tmp_repo() as repo:
            write_file(repo / ".aria" / "workflow-state.json", "")
            r = collect_interrupt_state(repo)
            self.assertEqual(r.data["status"], "corrupted")


class TestInterruptAnchorNullSafety(unittest.TestCase):
    """branch_anchor_match must be None (not False) when anchor is missing,
    to preserve the 'unknown' semantic separate from 'known-mismatch'."""

    def test_missing_git_anchor(self):
        with tmp_repo() as repo:
            write_file(
                repo / ".aria" / "workflow-state.json",
                json.dumps({"status": "in_progress"}),
            )
            r = collect_interrupt_state(repo)
            self.assertIsNone(r.data["branch_anchor_match"])

    def test_empty_anchor_branch(self):
        with tmp_repo() as repo:
            write_file(
                repo / ".aria" / "workflow-state.json",
                json.dumps({"status": "in_progress", "git_anchor": {}}),
            )
            r = collect_interrupt_state(repo)
            self.assertIsNone(r.data["branch_anchor_match"])


if __name__ == "__main__":
    unittest.main()

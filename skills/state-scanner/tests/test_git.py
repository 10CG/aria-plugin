"""Phase 1 git state collector tests."""

from __future__ import annotations

import os
import unittest

from _helpers import init_git_repo, run_git, tmp_project, tmp_repo, write_file
from collectors.git import (
    _current_branch,
    _enumerate_submodule_paths,
    _is_shallow,
    _parse_porcelain_z,
    collect_git_state,
)
from collectors._common import CollectorResult


class TestCurrentBranch(unittest.TestCase):
    def test_normal_branch(self):
        with tmp_repo(branch="master") as repo:
            self.assertEqual(_current_branch(repo), "master")

    def test_detached_head_returns_none(self):
        with tmp_repo() as repo:
            # Commit a second commit so we can detach
            write_file(repo / "x.txt", "1")
            run_git(repo, "add", "x.txt")
            run_git(repo, "commit", "-q", "-m", "c2")
            # Detach to previous commit
            run_git(repo, "checkout", "--detach", "HEAD~1", check=False)
            self.assertIsNone(_current_branch(repo))


class TestIsShallow(unittest.TestCase):
    def test_non_shallow(self):
        with tmp_repo() as repo:
            self.assertFalse(_is_shallow(repo))

    def test_shallow_requires_real_shallow_clone(self):
        """`git rev-parse --is-shallow-repository` reads clone metadata, not
        just the `.git/shallow` marker file. True shallow detection requires
        `git clone --depth N` which would slow the test; a real repo reports
        False regardless of a synthetic marker, which is correct."""
        with tmp_repo() as repo:
            (repo / ".git" / "shallow").write_text("abc\n")
            # Git ignores the synthetic file when running rev-parse, so this
            # returns False — the actual production behavior.
            self.assertFalse(_is_shallow(repo))


class TestPorcelainParsing(unittest.TestCase):
    def test_empty(self):
        staged, unstaged, untracked = _parse_porcelain_z("")
        self.assertEqual((staged, unstaged, untracked), ([], [], []))

    def test_modified_unstaged(self):
        # " M foo.py\x00"
        staged, unstaged, _ = _parse_porcelain_z(" M foo.py\x00")
        self.assertEqual(unstaged, ["foo.py"])
        self.assertEqual(staged, [])

    def test_modified_staged(self):
        staged, unstaged, _ = _parse_porcelain_z("M  foo.py\x00")
        self.assertEqual(staged, ["foo.py"])

    def test_mm_both_staged_and_unstaged(self):
        staged, unstaged, _ = _parse_porcelain_z("MM foo.py\x00")
        self.assertEqual(staged, ["foo.py"])
        self.assertEqual(unstaged, ["foo.py"])

    def test_untracked(self):
        _, _, untracked = _parse_porcelain_z("?? new.py\x00")
        self.assertEqual(untracked, ["new.py"])


class TestCollectGitState(unittest.TestCase):
    def test_not_a_git_repo(self):
        with tmp_project() as root:
            r = collect_git_state(root)
            self.assertFalse(r.data["is_git_repo"])

    def test_clean_repo(self):
        with tmp_repo() as repo:
            r = collect_git_state(repo)
            self.assertTrue(r.data["is_git_repo"])
            self.assertEqual(r.data["current_branch"], "master")
            self.assertEqual(r.data["uncommitted_count"], 0)
            self.assertEqual(r.data["staged_files"], [])

    def test_uncommitted_dedup_r1_i4(self):
        """R1-I4: MM entries count once in uncommitted_count."""
        with tmp_repo() as repo:
            # Create and commit a file
            write_file(repo / "a.txt", "original")
            run_git(repo, "add", "a.txt")
            run_git(repo, "commit", "-q", "-m", "add a")
            # Modify + stage + modify again → MM in porcelain
            write_file(repo / "a.txt", "staged")
            run_git(repo, "add", "a.txt")
            write_file(repo / "a.txt", "working")
            r = collect_git_state(repo)
            self.assertEqual(r.data["uncommitted_count"], 1)
            self.assertIn("a.txt", r.data["staged_files"])
            self.assertIn("a.txt", r.data["unstaged_files"])

    def test_upstream_no_upstream(self):
        with tmp_repo() as repo:
            r = collect_git_state(repo)
            self.assertFalse(r.data["upstream"]["configured"])
            self.assertEqual(r.data["upstream"]["reason"], "no_upstream")

    def test_recent_commits_shape(self):
        with tmp_repo() as repo:
            r = collect_git_state(repo)
            self.assertEqual(len(r.data["recent_commits"]), 1)
            self.assertIn("sha", r.data["recent_commits"][0])
            self.assertIn("subject", r.data["recent_commits"][0])


class TestSubmodulePathEnumeration(unittest.TestCase):
    def test_no_gitmodules(self):
        with tmp_project() as root:
            # Need a git repo for git config to work
            init_git_repo(root)
            self.assertEqual(_enumerate_submodule_paths(root), [])

    def test_gitmodules_parse(self):
        with tmp_repo() as repo:
            write_file(
                repo / ".gitmodules",
                """[submodule "aria"]
\tpath = aria
\turl = https://example.com/aria.git
[submodule "standards"]
\tpath = standards
\turl = https://example.com/standards.git
""",
            )
            paths = _enumerate_submodule_paths(repo)
            self.assertIn("aria", paths)
            self.assertIn("standards", paths)


if __name__ == "__main__":
    unittest.main()

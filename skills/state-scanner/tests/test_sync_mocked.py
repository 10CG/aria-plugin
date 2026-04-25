"""Phase 1.12 sync collector — subprocess-mocked unit tests (T6.5-followup).

Bumps coverage of `collectors.sync` from 18% → ≥70% by mocking `_run` to drive
all four current_branch states + every submodule directional-guard branch
without needing real submodules on disk.

Mocking strategy:
    `unittest.mock.patch("collectors.sync._run", side_effect=fake_run)` lets us
    dispatch on the git argv to return synthesized (rc, stdout, stderr) tuples.
    This keeps the tests stdlib-only (no pytest/coverage deps) and runs in <1s.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from _helpers import tmp_repo, write_file
from collectors._common import CollectorResult
from collectors.sync import (
    _collect_current_branch,
    _collect_submodule_entry,
    collect_sync_state,
)


def _make_run(table: dict[tuple[str, ...], tuple[int, str, str]]):
    """Build a fake `_run` that dispatches on the git argv tuple.

    `table` maps argv-tuples → (rc, stdout, stderr). Unknown commands return
    (1, "", "unmocked: <cmd>") so test failures point at the missing entry.
    """
    def fake(cmd, cwd, timeout=5):  # signature must match collectors._common._run
        key = tuple(cmd)
        if key in table:
            return table[key]
        # Try prefix match (helpful for dynamic args like ls-tree paths)
        for k, v in table.items():
            if len(k) <= len(key) and tuple(key[: len(k)]) == k:
                return v
        return (1, "", f"unmocked: {' '.join(cmd)}")

    return fake


class TestCurrentBranchStates(unittest.TestCase):
    """All four states from Phase 1.12 spec §4."""

    def test_detached_head(self):
        r = CollectorResult()
        out = _collect_current_branch(Path("/x"), branch=None, shallow=False, has_remote=True, r=r)
        self.assertEqual(out["reason"], "detached_head")
        self.assertIsNone(out["name"])
        self.assertIsNone(out["ahead"])
        self.assertIsNone(out["behind"])

    def test_no_upstream_when_no_remote(self):
        r = CollectorResult()
        out = _collect_current_branch(Path("/x"), branch="master", shallow=False, has_remote=False, r=r)
        self.assertEqual(out["reason"], "no_upstream")
        self.assertFalse(out["upstream_configured"])
        self.assertIsNone(out["upstream"])

    def test_no_upstream_when_remote_but_no_tracking(self):
        r = CollectorResult()
        run_table = {
            ("git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (1, "", "no upstream"),
        }
        with mock.patch("collectors.sync._run", side_effect=_make_run(run_table)):
            out = _collect_current_branch(
                Path("/x"), branch="feat", shallow=False, has_remote=True, r=r
            )
        self.assertEqual(out["reason"], "no_upstream")
        self.assertEqual(out["name"], "feat")

    def test_shallow_with_upstream(self):
        r = CollectorResult()
        run_table = {
            ("git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (
                0, "origin/master\n", ""
            ),
        }
        with mock.patch("collectors.sync._run", side_effect=_make_run(run_table)):
            out = _collect_current_branch(
                Path("/x"), branch="master", shallow=True, has_remote=True, r=r
            )
        self.assertEqual(out["reason"], "shallow_clone")
        self.assertEqual(out["upstream"], "origin/master")
        self.assertIsNone(out["ahead"])

    def test_normal_path_ahead_behind(self):
        r = CollectorResult()
        run_table = {
            ("git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (
                0, "origin/master\n", ""
            ),
            ("git", "rev-list", "--left-right", "--count", "HEAD...origin/master"): (
                0, "2\t5\n", ""
            ),
        }
        with mock.patch("collectors.sync._run", side_effect=_make_run(run_table)):
            out = _collect_current_branch(
                Path("/x"), branch="master", shallow=False, has_remote=True, r=r
            )
        self.assertEqual(out["ahead"], 2)
        self.assertEqual(out["behind"], 5)
        self.assertTrue(out["diverged"])
        self.assertIsNone(out["reason"])

    def test_normal_path_pure_ahead(self):
        r = CollectorResult()
        run_table = {
            ("git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (
                0, "origin/master\n", ""
            ),
            ("git", "rev-list", "--left-right", "--count", "HEAD...origin/master"): (
                0, "3\t0\n", ""
            ),
        }
        with mock.patch("collectors.sync._run", side_effect=_make_run(run_table)):
            out = _collect_current_branch(
                Path("/x"), branch="master", shallow=False, has_remote=True, r=r
            )
        self.assertEqual(out["ahead"], 3)
        self.assertEqual(out["behind"], 0)
        self.assertFalse(out["diverged"])

    def test_rev_list_failed_yields_soft_error(self):
        r = CollectorResult()
        run_table = {
            ("git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (
                0, "origin/master\n", ""
            ),
            ("git", "rev-list", "--left-right", "--count", "HEAD...origin/master"): (
                128, "", "fatal: bad revision"
            ),
        }
        with mock.patch("collectors.sync._run", side_effect=_make_run(run_table)):
            out = _collect_current_branch(
                Path("/x"), branch="master", shallow=False, has_remote=True, r=r
            )
        self.assertEqual(out["reason"], "rev_list_failed")
        self.assertTrue(any(e["error"] == "rev_list_failed" for e in r.errors))

    def test_rev_list_parse_failure(self):
        r = CollectorResult()
        run_table = {
            ("git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (
                0, "origin/master\n", ""
            ),
            ("git", "rev-list", "--left-right", "--count", "HEAD...origin/master"): (
                0, "weird-output\n", ""
            ),
        }
        with mock.patch("collectors.sync._run", side_effect=_make_run(run_table)):
            out = _collect_current_branch(
                Path("/x"), branch="master", shallow=False, has_remote=True, r=r
            )
        self.assertEqual(out["reason"], "parse_failed")

    def test_rev_list_non_integer(self):
        r = CollectorResult()
        run_table = {
            ("git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (
                0, "origin/master\n", ""
            ),
            ("git", "rev-list", "--left-right", "--count", "HEAD...origin/master"): (
                0, "x\ty\n", ""
            ),
        }
        with mock.patch("collectors.sync._run", side_effect=_make_run(run_table)):
            out = _collect_current_branch(
                Path("/x"), branch="master", shallow=False, has_remote=True, r=r
            )
        self.assertEqual(out["reason"], "parse_failed")


class TestSubmoduleEntry(unittest.TestCase):
    """Cover all 4 hint_type branches of `_collect_submodule_entry`."""

    def _setup(self, repo: Path, sub_path: str = "vendor/lib") -> Path:
        sub_dir = repo / sub_path
        sub_dir.mkdir(parents=True, exist_ok=True)
        # Make `sub_dir / .git` exist so `sub_dir.exists()` is true (the entry
        # function only checks `sub_dir.exists()`, not whether it's a real repo).
        return sub_dir

    def test_aligned_emits_zero_counts(self):
        """BA-I1 (post_implementation R1): tree==remote → behind=0, ahead=0."""
        with tmp_repo() as repo:
            self._setup(repo)
            same_sha = "a" * 40
            run_table = {
                ("git", "ls-tree", "HEAD", "--", "vendor/lib"): (
                    0, f"160000 commit {same_sha}\tvendor/lib\n", ""
                ),
                ("git", "rev-parse", "HEAD"): (0, f"{same_sha}\n", ""),
                ("git", "rev-parse", "refs/remotes/origin/HEAD"): (0, f"{same_sha}\n", ""),
            }
            with mock.patch("collectors.sync._run", side_effect=_make_run(run_table)):
                r = CollectorResult()
                entry = _collect_submodule_entry(repo, "vendor/lib", r)
            self.assertEqual(entry["drift"]["behind_count"], 0)
            self.assertEqual(entry["drift"]["ahead_count"], 0)
            self.assertFalse(entry["drift"]["tree_vs_remote"])
            self.assertIsNone(entry["drift"]["hint_type"])

    def test_behind_remote_yields_update_hint(self):
        with tmp_repo() as repo:
            self._setup(repo)
            tree = "a" * 40
            remote = "b" * 40
            run_table = {
                ("git", "ls-tree", "HEAD", "--", "vendor/lib"): (
                    0, f"160000 commit {tree}\tvendor/lib\n", ""
                ),
                ("git", "rev-parse", "HEAD"): (0, f"{tree}\n", ""),
                ("git", "rev-parse", "refs/remotes/origin/HEAD"): (0, f"{remote}\n", ""),
                ("git", "rev-list", "--count", f"{tree}..{remote}"): (0, "4\n", ""),
                ("git", "rev-list", "--count", f"{remote}..{tree}"): (0, "0\n", ""),
            }
            with mock.patch("collectors.sync._run", side_effect=_make_run(run_table)):
                r = CollectorResult()
                entry = _collect_submodule_entry(repo, "vendor/lib", r)
            self.assertEqual(entry["drift"]["hint_type"], "update")
            self.assertIn("update --remote", entry["drift"]["hint"])
            self.assertEqual(entry["drift"]["behind_count"], 4)
            self.assertEqual(entry["drift"]["ahead_count"], 0)
            self.assertTrue(entry["drift"]["tree_vs_remote"])

    def test_ahead_of_remote_yields_push_hint(self):
        """The critical R1-M1 directional guard: ahead → push, NOT update."""
        with tmp_repo() as repo:
            self._setup(repo)
            tree = "a" * 40
            remote = "b" * 40
            run_table = {
                ("git", "ls-tree", "HEAD", "--", "vendor/lib"): (
                    0, f"160000 commit {tree}\tvendor/lib\n", ""
                ),
                ("git", "rev-parse", "HEAD"): (0, f"{tree}\n", ""),
                ("git", "rev-parse", "refs/remotes/origin/HEAD"): (0, f"{remote}\n", ""),
                ("git", "rev-list", "--count", f"{tree}..{remote}"): (0, "0\n", ""),
                ("git", "rev-list", "--count", f"{remote}..{tree}"): (0, "2\n", ""),
            }
            with mock.patch("collectors.sync._run", side_effect=_make_run(run_table)):
                r = CollectorResult()
                entry = _collect_submodule_entry(repo, "vendor/lib", r)
            self.assertEqual(entry["drift"]["hint_type"], "push")
            self.assertIn("领先远程", entry["drift"]["hint"])

    def test_ambiguous_yields_manual_check(self):
        """Both counts 0 but tree != remote → manual_check (shallow / missing history)."""
        with tmp_repo() as repo:
            self._setup(repo)
            tree = "a" * 40
            remote = "b" * 40
            run_table = {
                ("git", "ls-tree", "HEAD", "--", "vendor/lib"): (
                    0, f"160000 commit {tree}\tvendor/lib\n", ""
                ),
                ("git", "rev-parse", "HEAD"): (0, f"{tree}\n", ""),
                ("git", "rev-parse", "refs/remotes/origin/HEAD"): (0, f"{remote}\n", ""),
                ("git", "rev-list", "--count", f"{tree}..{remote}"): (0, "0\n", ""),
                ("git", "rev-list", "--count", f"{remote}..{tree}"): (0, "0\n", ""),
            }
            with mock.patch("collectors.sync._run", side_effect=_make_run(run_table)):
                r = CollectorResult()
                entry = _collect_submodule_entry(repo, "vendor/lib", r)
            self.assertEqual(entry["drift"]["hint_type"], "manual_check")
            self.assertIn("手动检查", entry["drift"]["hint"])

    def test_inner_rev_parse_HEAD_failure(self):
        """sub_dir exists but `git rev-parse HEAD` inside it fails → soft_error."""
        with tmp_repo() as repo:
            self._setup(repo)
            tree = "a" * 40
            run_table = {
                ("git", "ls-tree", "HEAD", "--", "vendor/lib"): (
                    0, f"160000 commit {tree}\tvendor/lib\n", ""
                ),
                ("git", "rev-parse", "HEAD"): (128, "", "fatal: not a git repo"),
                ("git", "rev-parse", "refs/remotes/origin/HEAD"): (1, "", "no ref"),
                ("git", "rev-parse", "refs/remotes/origin/master"): (1, "", "no ref"),
                ("git", "rev-parse", "refs/remotes/origin/main"): (1, "", "no ref"),
            }
            with mock.patch("collectors.sync._run", side_effect=_make_run(run_table)):
                r = CollectorResult()
                entry = _collect_submodule_entry(repo, "vendor/lib", r)
            self.assertIsNone(entry["head_commit"])
            self.assertTrue(any(e["error"] == "submodule_head_failed" for e in r.errors))

    def test_count_failure_logs_soft_error(self):
        with tmp_repo() as repo:
            self._setup(repo)
            tree = "a" * 40
            remote = "b" * 40
            run_table = {
                ("git", "ls-tree", "HEAD", "--", "vendor/lib"): (
                    0, f"160000 commit {tree}\tvendor/lib\n", ""
                ),
                ("git", "rev-parse", "HEAD"): (0, f"{tree}\n", ""),
                ("git", "rev-parse", "refs/remotes/origin/HEAD"): (0, f"{remote}\n", ""),
                ("git", "rev-list", "--count", f"{tree}..{remote}"): (1, "", "boom"),
                ("git", "rev-list", "--count", f"{remote}..{tree}"): (1, "", "boom"),
            }
            with mock.patch("collectors.sync._run", side_effect=_make_run(run_table)):
                r = CollectorResult()
                entry = _collect_submodule_entry(repo, "vendor/lib", r)
            self.assertIsNone(entry["drift"]["behind_count"])
            self.assertIsNone(entry["drift"]["ahead_count"])
            kinds = [e["error"] for e in r.errors]
            self.assertIn("submodule_behind_count_failed", kinds)
            self.assertIn("submodule_ahead_count_failed", kinds)

    def test_workdir_vs_tree_drift(self):
        """tree_commit != head_commit → workdir_vs_tree=True."""
        with tmp_repo() as repo:
            self._setup(repo)
            tree = "a" * 40
            head = "c" * 40
            run_table = {
                ("git", "ls-tree", "HEAD", "--", "vendor/lib"): (
                    0, f"160000 commit {tree}\tvendor/lib\n", ""
                ),
                ("git", "rev-parse", "HEAD"): (0, f"{head}\n", ""),
                ("git", "rev-parse", "refs/remotes/origin/HEAD"): (1, "", "no ref"),
                ("git", "rev-parse", "refs/remotes/origin/master"): (1, "", "no ref"),
                ("git", "rev-parse", "refs/remotes/origin/main"): (1, "", "no ref"),
            }
            with mock.patch("collectors.sync._run", side_effect=_make_run(run_table)):
                r = CollectorResult()
                entry = _collect_submodule_entry(repo, "vendor/lib", r)
            self.assertTrue(entry["drift"]["workdir_vs_tree"])
            self.assertIsNone(entry["remote_commit"])
            self.assertEqual(entry["remote_commit_source"], "unavailable")

    def test_ls_tree_failure_soft_error(self):
        with tmp_repo() as repo:
            self._setup(repo)
            run_table = {
                ("git", "ls-tree", "HEAD", "--", "vendor/lib"): (1, "", "ls-tree failed"),
                ("git", "rev-parse", "HEAD"): (0, "a" * 40 + "\n", ""),
            }
            with mock.patch("collectors.sync._run", side_effect=_make_run(run_table)):
                r = CollectorResult()
                entry = _collect_submodule_entry(repo, "vendor/lib", r)
            self.assertIsNone(entry["tree_commit"])
            self.assertTrue(any(e["error"] == "submodule_ls_tree_failed" for e in r.errors))

    def test_uninitialized_submodule_dir_missing(self):
        """sub_dir does NOT exist → head_commit + remote_commit both null."""
        with tmp_repo() as repo:
            tree = "a" * 40
            run_table = {
                ("git", "ls-tree", "HEAD", "--", "missing/sub"): (
                    0, f"160000 commit {tree}\tmissing/sub\n", ""
                ),
            }
            with mock.patch("collectors.sync._run", side_effect=_make_run(run_table)):
                r = CollectorResult()
                entry = _collect_submodule_entry(repo, "missing/sub", r)
            self.assertEqual(entry["tree_commit"], tree)
            self.assertIsNone(entry["head_commit"])
            self.assertIsNone(entry["remote_commit"])

    def test_origin_master_fallback(self):
        """origin/HEAD missing → falls through to origin/master."""
        with tmp_repo() as repo:
            self._setup(repo)
            tree = "a" * 40
            head = "a" * 40  # aligned
            run_table = {
                ("git", "ls-tree", "HEAD", "--", "vendor/lib"): (
                    0, f"160000 commit {tree}\tvendor/lib\n", ""
                ),
                ("git", "rev-parse", "HEAD"): (0, f"{head}\n", ""),
                ("git", "rev-parse", "refs/remotes/origin/HEAD"): (1, "", "no head"),
                ("git", "rev-parse", "refs/remotes/origin/master"): (0, f"{tree}\n", ""),
            }
            with mock.patch("collectors.sync._run", side_effect=_make_run(run_table)):
                r = CollectorResult()
                entry = _collect_submodule_entry(repo, "vendor/lib", r)
            self.assertEqual(entry["remote_commit"], tree)
            self.assertEqual(entry["remote_commit_source"], "local_ref")


class TestCollectSyncStateNotARepo(unittest.TestCase):
    def test_not_a_git_repo_path(self):
        run_table = {("git", "rev-parse", "--is-inside-work-tree"): (128, "", "not a repo")}
        with mock.patch("collectors.sync._run", side_effect=_make_run(run_table)):
            r = collect_sync_state(Path("/no/such/path"))
        self.assertEqual(r.data["current_branch"]["reason"], "not_a_git_repo")
        self.assertFalse(r.data["has_remote"])
        self.assertFalse(r.data["shallow"])
        self.assertEqual(r.data["submodules"], [])
        self.assertEqual(r.data["multi_remote"], {"enabled": False})


class TestCollectSyncStateEndToEnd(unittest.TestCase):
    """End-to-end exercise via real tmp_repo with a real submodule entry written
    to .gitmodules — the inner submodule git calls are mocked out."""

    def test_with_gitmodules_and_mocked_remote(self):
        with tmp_repo() as repo:
            # Real .gitmodules entry triggers _enumerate_submodule_paths
            write_file(
                repo / ".gitmodules",
                '[submodule "lib"]\n\tpath = lib\n\turl = https://example.com/lib.git\n',
            )
            (repo / "lib").mkdir()
            tree = "1" * 40
            head = "2" * 40
            remote = "3" * 40
            run_table = {
                ("git", "rev-parse", "--is-inside-work-tree"): (0, "true\n", ""),
                ("git", "remote"): (0, "origin\n", ""),
                ("git", "rev-parse", "--git-dir"): (0, ".git\n", ""),
                ("git", "ls-tree", "HEAD", "--", "lib"): (
                    0, f"160000 commit {tree}\tlib\n", ""
                ),
                ("git", "rev-parse", "HEAD"): (0, f"{head}\n", ""),
                ("git", "rev-parse", "refs/remotes/origin/HEAD"): (0, f"{remote}\n", ""),
                ("git", "rev-list", "--count", f"{tree}..{remote}"): (0, "1\n", ""),
                ("git", "rev-list", "--count", f"{remote}..{tree}"): (0, "0\n", ""),
                ("git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (
                    1, "", "no upstream"
                ),
            }
            with mock.patch("collectors.sync._run", side_effect=_make_run(run_table)):
                r = collect_sync_state(repo)
            self.assertTrue(r.data["has_remote"])
            self.assertEqual(len(r.data["submodules"]), 1)
            sub = r.data["submodules"][0]
            self.assertEqual(sub["path"], "lib")
            self.assertEqual(sub["drift"]["hint_type"], "update")


class TestFetchHeadAgeBuckets(unittest.TestCase):
    """Cover all three age buckets + git-dir resolution paths."""

    def test_minutes_bucket_explicit(self):
        import os
        import time as _time

        from collectors.sync import _fetch_head_age

        with tmp_repo() as repo:
            fh = repo / ".git" / "FETCH_HEAD"
            fh.write_text("stub\n")
            recent = _time.time() - 600  # 10 min ago
            os.utime(fh, (recent, recent))
            self.assertEqual(_fetch_head_age(repo, CollectorResult())[-1], "m")

    def test_hours_bucket_explicit(self):
        import os
        import time as _time

        from collectors.sync import _fetch_head_age

        with tmp_repo() as repo:
            fh = repo / ".git" / "FETCH_HEAD"
            fh.write_text("stub\n")
            mid = _time.time() - 7200  # 2h ago
            os.utime(fh, (mid, mid))
            self.assertEqual(_fetch_head_age(repo, CollectorResult())[-1], "h")

    def test_git_dir_failure_returns_never(self):
        from collectors.sync import _fetch_head_age

        run_table = {("git", "rev-parse", "--git-dir"): (128, "", "not a repo")}
        with mock.patch("collectors.sync._run", side_effect=_make_run(run_table)):
            self.assertEqual(_fetch_head_age(Path("/x"), CollectorResult()), "never")

    def test_absolute_git_dir_path(self):
        """Branch where rev-parse --git-dir returns an absolute path."""
        import os
        import tempfile
        import time as _time

        from collectors.sync import _fetch_head_age

        with tempfile.TemporaryDirectory() as td:
            git_dir = Path(td) / ".git"
            git_dir.mkdir()
            fh = git_dir / "FETCH_HEAD"
            fh.write_text("stub\n")
            recent = _time.time() - 60
            os.utime(fh, (recent, recent))
            run_table = {("git", "rev-parse", "--git-dir"): (0, str(git_dir) + "\n", "")}
            with mock.patch("collectors.sync._run", side_effect=_make_run(run_table)):
                age = _fetch_head_age(Path(td), CollectorResult())
            self.assertEqual(age[-1], "m")

    # Note: OSError branch in _fetch_head_age is defensive — exercised by
    # the existing test_sync.py::test_never_when_no_fetch_head sibling case
    # via missing-file path. Stat-OSError simulation is brittle across
    # platforms (root vs non-root, tempfile cleanup interactions), so we
    # leave that single defensive line uncovered intentionally.


class TestCollectSyncIntegration(unittest.TestCase):
    """Cover the assembling code path in `collect_sync_state` end-to-end."""

    def test_full_with_remote_no_submodules(self):
        with tmp_repo() as repo:
            run_git_table = {
                ("git", "rev-parse", "--is-inside-work-tree"): (0, "true\n", ""),
                ("git", "remote"): (0, "origin\n", ""),
                ("git", "rev-parse", "--git-dir"): (0, ".git\n", ""),
                ("git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): (
                    0, "origin/master\n", ""
                ),
                ("git", "rev-list", "--left-right", "--count", "HEAD...origin/master"): (
                    0, "0\t0\n", ""
                ),
            }
            with mock.patch("collectors.sync._run", side_effect=_make_run(run_git_table)):
                r = collect_sync_state(repo)
        cb = r.data["current_branch"]
        self.assertTrue(r.data["has_remote"])
        self.assertEqual(cb["upstream"], "origin/master")
        self.assertEqual(cb["ahead"], 0)
        self.assertEqual(cb["behind"], 0)
        self.assertIsNone(cb["reason"])
        self.assertEqual(r.data["multi_remote"], {"enabled": False})


class TestHasRemoteEdgeCases(unittest.TestCase):
    def test_rc_zero_empty_output(self):
        from collectors.sync import _has_remote

        run_table = {("git", "remote"): (0, "  \n", "")}
        with mock.patch("collectors.sync._run", side_effect=_make_run(run_table)):
            self.assertFalse(_has_remote(Path("/x")))

    def test_rc_nonzero(self):
        from collectors.sync import _has_remote

        run_table = {("git", "remote"): (1, "", "no remote")}
        with mock.patch("collectors.sync._run", side_effect=_make_run(run_table)):
            self.assertFalse(_has_remote(Path("/x")))


if __name__ == "__main__":
    unittest.main()

"""Aria #135 — git operation in-progress detection tests.

Covers `_detect_git_operation` + its wiring into `collect_git_state`:
single markers, multi-marker priority, worktree git-dir resolution, conflict
detection (conditional eval), fail-soft, and the additive clean-repo contract.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from _helpers import run_git, tmp_project, tmp_repo, write_file
from collectors._common import CollectorResult
from collectors.git import (
    _detect_git_operation,
    _resolve_git_dir,
    collect_git_state,
)


def _git_dir(repo: Path) -> Path:
    """Resolve the repo's git dir the way the collector does."""
    gd = _resolve_git_dir(repo)
    assert gd is not None
    return gd


class TestSingleMarker(unittest.TestCase):
    def test_clean_repo_is_none(self):
        with tmp_repo() as repo:
            res = _detect_git_operation(repo)
            self.assertEqual(
                res, {"operation": "none", "has_conflicts": False, "detail": None}
            )

    def test_rebase_merge_dir(self):
        with tmp_repo() as repo:
            (_git_dir(repo) / "rebase-merge").mkdir()
            self.assertEqual(_detect_git_operation(repo)["operation"], "rebase")

    def test_rebase_apply_dir(self):
        with tmp_repo() as repo:
            (_git_dir(repo) / "rebase-apply").mkdir()
            self.assertEqual(_detect_git_operation(repo)["operation"], "rebase")

    def test_merge_head(self):
        with tmp_repo() as repo:
            (_git_dir(repo) / "MERGE_HEAD").write_text("deadbeef\n")
            self.assertEqual(_detect_git_operation(repo)["operation"], "merge")

    def test_cherry_pick_head(self):
        with tmp_repo() as repo:
            (_git_dir(repo) / "CHERRY_PICK_HEAD").write_text("deadbeef\n")
            self.assertEqual(_detect_git_operation(repo)["operation"], "cherry_pick")

    def test_revert_head(self):
        with tmp_repo() as repo:
            (_git_dir(repo) / "REVERT_HEAD").write_text("deadbeef\n")
            self.assertEqual(_detect_git_operation(repo)["operation"], "revert")

    def test_bisect_log(self):
        with tmp_repo() as repo:
            (_git_dir(repo) / "BISECT_LOG").write_text("git bisect start\n")
            self.assertEqual(_detect_git_operation(repo)["operation"], "bisect")


class TestMultiMarkerPriority(unittest.TestCase):
    """Multi-marker is an anomalous mid-state; highest priority wins."""

    def test_rebase_beats_merge(self):
        with tmp_repo() as repo:
            gd = _git_dir(repo)
            (gd / "rebase-merge").mkdir()
            (gd / "MERGE_HEAD").write_text("x\n")
            self.assertEqual(_detect_git_operation(repo)["operation"], "rebase")

    def test_merge_beats_cherry_pick(self):
        with tmp_repo() as repo:
            gd = _git_dir(repo)
            (gd / "MERGE_HEAD").write_text("x\n")
            (gd / "CHERRY_PICK_HEAD").write_text("y\n")
            self.assertEqual(_detect_git_operation(repo)["operation"], "merge")


class TestWorktreeGitDir(unittest.TestCase):
    """Linked worktrees expose an ABSOLUTE git dir; resolution must follow it
    (Aria #135 OQ2 / related to #139)."""

    def test_rebase_marker_in_worktree_git_dir(self):
        # Worktree path lives in its OWN tempdir (NOT repo.parent, which resolves
        # to a fixed $TMPDIR and would leak across runs → `worktree add` exit 128).
        with tmp_repo() as repo, tempfile.TemporaryDirectory(prefix="ss-wt-") as wtbase:
            wt = Path(wtbase) / "wt"
            run_git(repo, "worktree", "add", "-q", str(wt), "-b", "wtbranch")
            # The worktree's git dir is absolute: <repo>/.git/worktrees/wt
            wt_git_dir = _resolve_git_dir(wt)
            self.assertIsNotNone(wt_git_dir)
            self.assertTrue(wt_git_dir.is_absolute())
            (wt_git_dir / "rebase-merge").mkdir()
            self.assertEqual(_detect_git_operation(wt)["operation"], "rebase")
            # Main worktree unaffected (separate git dir).
            self.assertEqual(_detect_git_operation(repo)["operation"], "none")
            run_git(repo, "worktree", "remove", "--force", str(wt), check=False)


class TestConflictDetection(unittest.TestCase):
    def test_real_merge_conflict_has_conflicts_true(self):
        with tmp_repo() as repo:
            write_file(repo / "f.txt", "base\n")
            run_git(repo, "add", "f.txt")
            run_git(repo, "commit", "-q", "-m", "base")
            run_git(repo, "checkout", "-q", "-b", "feature")
            write_file(repo / "f.txt", "feature\n")
            run_git(repo, "add", "f.txt")
            run_git(repo, "commit", "-q", "-m", "feature")
            run_git(repo, "checkout", "-q", "master")
            write_file(repo / "f.txt", "master\n")
            run_git(repo, "add", "f.txt")
            run_git(repo, "commit", "-q", "-m", "master")
            run_git(repo, "merge", "feature", check=False)  # → conflict
            res = _detect_git_operation(repo)
            self.assertEqual(res["operation"], "merge")
            self.assertTrue(res["has_conflicts"])

    def test_synthetic_marker_without_conflict_is_false(self):
        with tmp_repo() as repo:
            (_git_dir(repo) / "MERGE_HEAD").write_text("x\n")
            res = _detect_git_operation(repo)
            self.assertEqual(res["operation"], "merge")
            self.assertFalse(res["has_conflicts"])


class TestRebaseDetail(unittest.TestCase):
    def test_detail_reads_head_name_and_onto(self):
        with tmp_repo() as repo:
            rm = _git_dir(repo) / "rebase-merge"
            rm.mkdir()
            (rm / "head-name").write_text("refs/heads/master\n")
            (rm / "onto").write_text("a9665fb\n")
            detail = _detect_git_operation(repo)["detail"]
            self.assertIsNotNone(detail)
            self.assertIn("refs/heads/master", detail)
            self.assertIn("onto a9665fb", detail)


class TestFailSoft(unittest.TestCase):
    def test_non_git_dir_is_none_with_soft_error(self):
        with tmp_project() as proj:
            r = CollectorResult()
            res = _detect_git_operation(proj, r)
            self.assertEqual(res["operation"], "none")
            self.assertTrue(any(e["error"] == "git_dir_unresolved" for e in r.errors))


class TestCollectGitStateWiring(unittest.TestCase):
    def test_clean_repo_field_present_none_shape(self):
        """AC-3: clean repo must carry the additive field in none form."""
        with tmp_repo() as repo:
            data = collect_git_state(repo).data
            self.assertEqual(
                data["git_operation_in_progress"],
                {"operation": "none", "has_conflicts": False, "detail": None},
            )

    def test_paused_rebase_surfaced(self):
        """AC-1: the #135 repro — paused rebase no longer reads as none."""
        with tmp_repo() as repo:
            (_git_dir(repo) / "rebase-merge").mkdir()
            data = collect_git_state(repo).data
            # detached_head stays False (branch still resolves) — the exact #135 gap
            self.assertFalse(data["detached_head"])
            self.assertEqual(
                data["git_operation_in_progress"]["operation"], "rebase"
            )


if __name__ == "__main__":
    unittest.main()

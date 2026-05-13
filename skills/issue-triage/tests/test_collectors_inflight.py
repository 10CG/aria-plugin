"""T4 — Inflight collector tests: 3-section independence + worktree + error cases.

Covers:
  - Mid-review concern 8: 3-section independence (owner_repo empty -> remote_prs=[])
  - Mid-review concern 8: all 3 sections fail -> collection_status=error
  - Mid-review concern 12: worktree branch with '+' prefix is stripped correctly
  - Section isolation: one section failing does not block others
  - _collect_remote_prs PR keyword matching
  - _classify_forgejo_error mapping: 401/403/404/429 -> expected category strings

References:
  T1.6 — Step 5 in-flight check
  Mid-review m5 fix: '+ feature/active-worktree' -> 'feature/active-worktree'
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from collectors._inflight import (
    _build_search_keywords,
    _collect_local_branches,
    _collect_worktrees,
    collect_inflight,
)
from collectors._issue import _classify_forgejo_error


class TestBuildSearchKeywords:
    """Keyword building for branch/PR matching."""

    def test_issue_number_generates_keywords(self) -> None:
        """Issue number 101 -> multiple keyword forms generated."""
        kws = _build_search_keywords(101, [])
        assert "101" in kws
        assert "issue-101" in kws
        assert "fix-101" in kws

    def test_zero_issue_number_no_number_keywords(self) -> None:
        """Issue number 0 -> no numeric keywords."""
        kws = _build_search_keywords(0, [])
        assert "0" not in kws

    def test_cited_paths_add_stems(self) -> None:
        """Cited file paths contribute their stems to keyword list."""
        cited = [{"file_path": "scripts/collectors/_inflight.py", "exists": True}]
        kws = _build_search_keywords(101, cited)
        assert "_inflight" in kws

    def test_dedup_in_keywords(self) -> None:
        """Same stem from multiple paths -> appears once."""
        cited = [
            {"file_path": "a/_inflight.py", "exists": True},
            {"file_path": "b/_inflight.py", "exists": True},
        ]
        kws = _build_search_keywords(0, cited)
        assert kws.count("_inflight") == 1


class TestForgejoErrorMapping:
    """Mid-review concern 10: _classify_forgejo_error maps HTTP codes correctly."""

    def test_401_returns_auth_failed(self) -> None:
        """RC with '401' in stderr -> auth_failed.

        Mid-review concern 10: 401 mapping.
        """
        result = _classify_forgejo_error(1, "error: 401 Unauthorized", "")
        assert result == "auth_failed"

    def test_403_returns_auth_failed(self) -> None:
        """RC with '403' in combined output -> auth_failed.

        Mid-review concern 10: 403 mapping.
        """
        result = _classify_forgejo_error(1, "403 Forbidden access denied", "")
        assert result == "auth_failed"

    def test_404_returns_not_found(self) -> None:
        """RC with '404' in stderr -> not_found.

        Mid-review concern 10: 404 mapping.
        """
        result = _classify_forgejo_error(1, "error: 404 not found", "")
        assert result == "not_found"

    def test_429_returns_rate_limited(self) -> None:
        """RC with '429' in stderr -> rate_limited.

        Mid-review concern 10: 429 mapping.
        """
        result = _classify_forgejo_error(1, "429 too many requests rate limit", "")
        assert result == "rate_limited"

    def test_127_returns_cli_missing(self) -> None:
        """RC=127 -> cli_missing (command not found)."""
        result = _classify_forgejo_error(127, "", "")
        assert result == "cli_missing"

    def test_124_returns_timeout(self) -> None:
        """RC=124 -> timeout."""
        result = _classify_forgejo_error(124, "", "")
        assert result == "timeout"

    def test_unauthorized_string_returns_auth_failed(self) -> None:
        """'unauthorized' string in stderr -> auth_failed."""
        result = _classify_forgejo_error(1, "unauthorized request", "")
        assert result == "auth_failed"

    def test_unknown_error_fallback(self) -> None:
        """Unknown RC with no recognizable pattern -> unknown_error."""
        result = _classify_forgejo_error(1, "some random error", "")
        assert result == "unknown_error"


class TestWorktreeBranchStripping:
    """Mid-review concern 12: worktree branch '+' prefix is stripped in local_branches."""

    def test_plus_prefix_stripped_from_branch(self, git_repo: Path) -> None:
        """'+ feature/active-worktree' in git branch -a output -> stripped to 'feature/active-worktree'.

        Mid-review m5 fix: lstrip('*+ ') on branch lines.
        """
        # Simulate git branch -a output with '+' prefix (worktree-checked-out branch)
        raw_output = "  master\n+ feature/active-worktree\n  feature/other\n"

        with patch("collectors._inflight._run") as mock_run:
            mock_run.return_value = (0, raw_output, "")
            branches, err = _collect_local_branches(101, [], git_repo, timeout=5)

        assert err is None
        # '+' prefix must be stripped
        assert "feature/active-worktree" in branches
        assert "+ feature/active-worktree" not in branches, (
            "'+ feature/active-worktree' with '+' prefix must NOT appear — "
            "the '+' lstrip fix (m5) is broken if this assertion fails."
        )

    def test_star_prefix_stripped_from_current_branch(self, git_repo: Path) -> None:
        """'* master' (current branch) -> stripped to 'master'."""
        raw_output = "* master\n  feature/fix-101\n"
        with patch("collectors._inflight._run") as mock_run:
            mock_run.return_value = (0, raw_output, "")
            branches, err = _collect_local_branches(101, [], git_repo, timeout=5)
        # '*' prefix must be stripped
        assert "master" in branches
        assert "* master" not in branches

    def test_arrow_branches_excluded(self, git_repo: Path) -> None:
        """'remotes/origin/HEAD -> origin/master' lines are excluded."""
        raw_output = "  remotes/origin/HEAD -> origin/master\n  remotes/origin/master\n"
        with patch("collectors._inflight._run") as mock_run:
            mock_run.return_value = (0, raw_output, "")
            branches, err = _collect_local_branches(101, [], git_repo, timeout=5)
        for b in branches:
            assert "->" not in b, f"Arrow branch leaked into output: {b}"


class TestCollectWorktrees:
    """Worktree list parsing."""

    def test_porcelain_parsing(self, git_repo: Path) -> None:
        """git worktree list --porcelain output parsed into path/branch/is_main."""
        porcelain_output = (
            "worktree /home/dev/project\n"
            "HEAD abc1234\n"
            "branch refs/heads/master\n"
            "\n"
            "worktree /home/dev/project-wt\n"
            "HEAD def5678\n"
            "branch refs/heads/feature/fix-101\n"
            "\n"
        )
        with patch("collectors._inflight._run") as mock_run:
            mock_run.return_value = (0, porcelain_output, "")
            worktrees, err = _collect_worktrees(git_repo, timeout=5)

        assert err is None
        assert len(worktrees) == 2
        # First entry is main
        assert worktrees[0]["is_main"] is True
        assert worktrees[0]["branch"] == "master"
        # Second entry
        assert worktrees[1]["branch"] == "feature/fix-101"
        assert "refs/heads/" not in worktrees[1]["branch"]  # prefix stripped

    def test_empty_worktree_list(self, git_repo: Path) -> None:
        """No worktrees output -> empty list."""
        with patch("collectors._inflight._run") as mock_run:
            mock_run.return_value = (0, "", "")
            worktrees, err = _collect_worktrees(git_repo, timeout=5)
        assert worktrees == []
        assert err is None

    def test_git_not_found_error(self, git_repo: Path) -> None:
        """RC=127 -> error='git_not_found'."""
        with patch("collectors._inflight._run") as mock_run:
            mock_run.return_value = (127, "", "command not found: git")
            worktrees, err = _collect_worktrees(git_repo, timeout=5)
        assert err == "git_not_found"
        assert worktrees == []


class TestCollectInflightSectionIndependence:
    """Mid-review concern 8: 3-section independence."""

    def test_empty_owner_repo_remote_prs_empty(self, git_repo: Path) -> None:
        """owner_repo='' -> remote_prs=[], other sections still run.

        Mid-review concern 8 (first case): owner_repo empty + git success -> remote_prs=[].
        """
        with patch("collectors._inflight._collect_local_branches") as mock_local, \
             patch("collectors._inflight._collect_worktrees") as mock_wt:
            mock_local.return_value = (["feature/fix-101"], None)
            mock_wt.return_value = ([{"path": "/tmp/wt", "branch": "master", "is_main": True}], None)

            result = collect_inflight("", git_repo, 101, [], timeout=5)

        assert result.data["remote_prs"] == []
        # Other sections still populated
        assert "feature/fix-101" in result.data["local_branches"]
        assert len(result.data["worktrees"]) >= 1

    def test_all_three_sections_fail_returns_error(self, git_repo: Path) -> None:
        """All 3 sections fail -> collection_status='error'.

        Mid-review concern 8 (second case): all sections fail -> error.
        """
        with patch("collectors._inflight._collect_remote_prs") as mock_pr, \
             patch("collectors._inflight._collect_local_branches") as mock_local, \
             patch("collectors._inflight._collect_worktrees") as mock_wt:
            mock_pr.return_value = ([], "auth_failed")
            mock_local.return_value = ([], "git_not_found")
            mock_wt.return_value = ([], "git_not_found")

            result = collect_inflight("10CG/Aria", git_repo, 101, [], timeout=5)

        assert result.data["collection_status"] == "error", (
            "When all 3 sections fail, collection_status must be 'error'. "
            f"Got: {result.data['collection_status']!r}"
        )

    def test_two_sections_fail_one_ok_returns_ok(self, git_repo: Path) -> None:
        """2 sections fail, 1 succeeds -> collection_status='ok'."""
        with patch("collectors._inflight._collect_remote_prs") as mock_pr, \
             patch("collectors._inflight._collect_local_branches") as mock_local, \
             patch("collectors._inflight._collect_worktrees") as mock_wt:
            mock_pr.return_value = ([], "auth_failed")
            mock_local.return_value = ([], "git_not_found")
            mock_wt.return_value = ([{"path": "/tmp/main", "branch": "master", "is_main": True}], None)

            result = collect_inflight("10CG/Aria", git_repo, 101, [], timeout=5)

        assert result.data["collection_status"] == "ok"

    def test_all_sections_return_empty_is_ok_not_error(self, git_repo: Path) -> None:
        """All sections return empty data (no error) -> collection_status='ok'."""
        with patch("collectors._inflight._collect_remote_prs") as mock_pr, \
             patch("collectors._inflight._collect_local_branches") as mock_local, \
             patch("collectors._inflight._collect_worktrees") as mock_wt:
            mock_pr.return_value = ([], None)  # empty but no error
            mock_local.return_value = ([], None)
            mock_wt.return_value = ([], None)

            result = collect_inflight("10CG/Aria", git_repo, 101, [], timeout=5)

        assert result.data["collection_status"] == "ok"
        assert result.data["remote_prs"] == []
        assert result.data["local_branches"] == []
        assert result.data["worktrees"] == []

    def test_output_has_all_three_section_keys(self, git_repo: Path) -> None:
        """Result always contains remote_prs, local_branches, worktrees keys."""
        with patch("collectors._inflight._collect_remote_prs") as mock_pr, \
             patch("collectors._inflight._collect_local_branches") as mock_local, \
             patch("collectors._inflight._collect_worktrees") as mock_wt:
            mock_pr.return_value = ([], None)
            mock_local.return_value = ([], None)
            mock_wt.return_value = ([], None)

            result = collect_inflight("10CG/Aria", git_repo, 101, [], timeout=5)

        for key in ("remote_prs", "local_branches", "worktrees"):
            assert key in result.data, f"Missing section key: {key}"


class TestForgejoApiTimeout:
    """T4.4: API timeout -> collection_status=error."""

    def test_timeout_in_remote_prs_section(self, git_repo: Path) -> None:
        """Forgejo CLI timeout (rc=124) in remote_prs -> section error, not total failure."""
        with patch("collectors._inflight._collect_remote_prs") as mock_pr, \
             patch("collectors._inflight._collect_local_branches") as mock_local, \
             patch("collectors._inflight._collect_worktrees") as mock_wt:
            mock_pr.return_value = ([], "timeout")
            mock_local.return_value = (["feature/fix-101"], None)
            mock_wt.return_value = ([], None)

            result = collect_inflight("10CG/Aria", git_repo, 101, [], timeout=5)

        # Timeout in one section -> ok (other sections succeeded)
        assert result.data["collection_status"] == "ok"
        # Soft error recorded
        pr_errors = [e for e in result.errors if "timeout" in e.get("detail", "")]
        assert len(pr_errors) >= 1

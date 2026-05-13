"""T4 — History collector tests: likely_fix_candidates empty/populated.

Covers:
  - Mid-review concern 7: empty array when no matching commits (NOT null/missing)
  - Populated candidates when commits contain fix keywords
  - Multi-keyword match_reason accumulation
  - Issue-specific reference matching (#N / issue N)
  - Skipped status when no cited paths provided

References:
  T1.5 — Step 4 git log on cited files
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from collectors._history import (
    _match_reasons,
    _parse_git_log_oneline,
    collect_history,
)


class TestMatchReasons:
    """Unit tests for keyword matching logic."""

    def test_fix_keyword_matched(self) -> None:
        """'fix' in commit message -> match_reason contains 'fix'."""
        reasons = _match_reasons("fix: normalize status field")
        assert "fix" in reasons

    def test_resolve_keyword_matched(self) -> None:
        """'resolve' -> match_reason contains 'resolve'."""
        reasons = _match_reasons("resolve collection_status inconsistency")
        assert "resolve" in reasons

    def test_close_issue_keyword_matched(self) -> None:
        """'close #101' -> match_reason contains 'close_issue'."""
        reasons = _match_reasons("chore: close #101 workaround")
        assert "close_issue" in reasons

    def test_normalize_keyword_matched(self) -> None:
        """'normalize' -> match_reason contains 'normalize'."""
        reasons = _match_reasons("normalize the collection_status field")
        assert "normalize" in reasons

    def test_no_keywords_empty_list(self) -> None:
        """Commit with no fix keywords -> empty match_reason list."""
        reasons = _match_reasons("docs: update changelog for v1.19.0")
        assert reasons == []

    def test_multiple_keywords_all_collected(self) -> None:
        """Multiple keywords in one message -> all appear in match_reason.

        Note: 'patch' keyword uses \\bpatch\\b (word boundary), so 'patching'
        does NOT match. Use the exact word 'patch' to trigger it.
        """
        reasons = _match_reasons("fix: resolve bug via patch to normalize logic")
        assert "fix" in reasons
        assert "resolve" in reasons
        assert "patch" in reasons
        assert "normalize" in reasons

    def test_case_insensitive_matching(self) -> None:
        """Keyword matching is case-insensitive."""
        reasons = _match_reasons("FIX: RESOLVE the BUG")
        assert "fix" in reasons
        assert "resolve" in reasons
        assert "bug" in reasons


class TestParseGitLogOneline:
    """Unit tests for git log --oneline parser."""

    def test_parses_sha_and_message(self) -> None:
        """Standard git log --oneline line -> (sha, message) tuple."""
        output = "abc1234 fix: normalize status\ndef5678 feat: add collector\n"
        result = _parse_git_log_oneline(output)
        assert len(result) == 2
        assert result[0] == ("abc1234", "fix: normalize status")
        assert result[1] == ("def5678", "feat: add collector")

    def test_empty_output_empty_list(self) -> None:
        """Empty output -> empty list."""
        assert _parse_git_log_oneline("") == []

    def test_blank_lines_ignored(self) -> None:
        """Blank lines in output are skipped."""
        output = "\nabc1234 fix: something\n\n"
        result = _parse_git_log_oneline(output)
        assert len(result) == 1

    def test_no_decorate_output_clean(self) -> None:
        """--no-decorate output has no (HEAD->branch) decoration in message."""
        # This would appear without --no-decorate, testing that our parser
        # handles clean output correctly
        output = "abc1234 fix: clean commit message without decoration\n"
        result = _parse_git_log_oneline(output)
        assert result[0][1] == "fix: clean commit message without decoration"


class TestCollectHistorySkipped:
    """collect_history returns skipped when no cited paths."""

    def test_no_cited_paths_skipped(self, tmp_path: Path) -> None:
        """No cited paths -> collection_status=skipped, likely_fix_candidates=[].

        T1.5: skipped when no cited paths.
        """
        result = collect_history(tmp_path, [], 101)
        assert result.data["collection_status"] == "skipped"

    def test_no_cited_paths_empty_array_not_null(self, tmp_path: Path) -> None:
        """No cited paths -> likely_fix_candidates is [] (not None, not missing).

        Mid-review concern 7: empty array contract.
        """
        result = collect_history(tmp_path, [], 101)
        candidates = result.data.get("likely_fix_candidates")
        assert candidates is not None, "likely_fix_candidates must not be None"
        assert isinstance(candidates, list), "likely_fix_candidates must be a list"
        assert len(candidates) == 0

    def test_nonexistent_files_skipped(self, tmp_path: Path) -> None:
        """Cited paths where exists=False -> skipped (no real files to git log)."""
        cited = [{"file_path": "nonexistent.py", "exists": False}]
        result = collect_history(tmp_path, cited, 101)
        assert result.data["collection_status"] == "skipped"


class TestCollectHistoryWithGitRepo:
    """collect_history with a real git repo fixture."""

    def test_fix_commit_found_in_candidates(self, git_repo: Path) -> None:
        """Repo with 'fix: resolve close #101 normalize' commit -> candidate found.

        T1.5: keyword matching against git log output.
        """
        # The git_repo fixture has a fix commit touching _inflight.py
        cited = [{
            "file_path": "scripts/collectors/_inflight.py",
            "exists": True,
            "file_path": "scripts/collectors/_inflight.py",
        }]
        result = collect_history(git_repo, cited, 101)
        assert result.data["collection_status"] == "ok"
        candidates = result.data["likely_fix_candidates"]
        assert isinstance(candidates, list)
        assert len(candidates) >= 1

    def test_fix_candidate_has_required_fields(self, git_repo: Path) -> None:
        """Each fix candidate has sha, message, match_reason fields."""
        cited = [{"file_path": "scripts/collectors/_inflight.py", "exists": True}]
        result = collect_history(git_repo, cited, 101)
        candidates = result.data["likely_fix_candidates"]
        assert len(candidates) >= 1
        c = candidates[0]
        assert "sha" in c
        assert "message" in c
        assert "match_reason" in c
        assert isinstance(c["match_reason"], list)
        assert len(c["match_reason"]) >= 1

    def test_empty_candidates_when_no_fix_commits(self, git_repo_no_fix_commits: Path) -> None:
        """Repo with no fix-keyword commits -> likely_fix_candidates is [] (not null).

        Mid-review concern 7: empty array when no matching commits.
        """
        cited = [{"file_path": "scripts/collectors/_version.py", "exists": True}]
        result = collect_history(git_repo_no_fix_commits, cited, 101)
        assert result.data["collection_status"] == "ok"
        candidates = result.data["likely_fix_candidates"]
        assert candidates is not None, "must not be None"
        assert isinstance(candidates, list)
        assert len(candidates) == 0, (
            f"Expected empty array but got {candidates}. "
            "This repo has no fix-keyword commits."
        )

    def test_issue_specific_ref_matched(self, git_repo: Path) -> None:
        """Commit with '#101' reference -> match_reason includes issue_ref_#101."""
        cited = [{"file_path": "scripts/collectors/_inflight.py", "exists": True}]
        result = collect_history(git_repo, cited, 101)
        candidates = result.data["likely_fix_candidates"]
        # The fixture commit message contains 'close #101'
        issue_ref_candidates = [
            c for c in candidates
            if any("issue_ref_#101" in r for r in c["match_reason"])
        ]
        assert len(issue_ref_candidates) >= 1

    def test_sha_dedup_across_files(self, git_repo: Path) -> None:
        """Same SHA from multiple cited files appears only once in candidates."""
        # Both files were touched by the same fix commit in the fixture
        cited = [
            {"file_path": "scripts/collectors/_inflight.py", "exists": True},
            {"file_path": "scripts/collectors/_common.py", "exists": True},
        ]
        result = collect_history(git_repo, cited, 101)
        candidates = result.data["likely_fix_candidates"]
        shas = [c["sha"] for c in candidates]
        assert len(shas) == len(set(shas)), f"Duplicate SHAs found: {shas}"

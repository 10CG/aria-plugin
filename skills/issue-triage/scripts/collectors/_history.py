"""Step 4 — Git log on cited files (recent N=20 commits, keyword matching).

For each cited file path from step3_code, runs:
  git log -n 20 --oneline -- <file>

Filters commits by keywords that suggest a fix or relevant change:
  fix, resolve, close #N, normalize, issue #N, bug, revert, patch

Returns likely_fix_candidates: [{sha, message, match_reason}]
An empty array means no candidates were found (boolean False at read time).

collection_status values:
  ok      — git log ran successfully for at least one cited file
  error   — git log failed (not a repo, no cited files, etc.)
  skipped — no cited file paths available from step3
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ._common import CollectorResult, _run, log

_STATUS_OK = "ok"
_STATUS_ERROR = "error"
_STATUS_SKIPPED = "skipped"

_GIT_LOG_COUNT = 20

# Keywords that suggest a commit is a likely fix candidate.
# Each entry is (keyword_pattern, match_reason_label)
_FIX_KEYWORDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bfix\b", re.IGNORECASE), "fix"),
    (re.compile(r"\bresolve\b", re.IGNORECASE), "resolve"),
    (re.compile(r"\bclose\s+#\d+", re.IGNORECASE), "close_issue"),
    (re.compile(r"\bnormalize\b", re.IGNORECASE), "normalize"),
    (re.compile(r"\bbug\b", re.IGNORECASE), "bug"),
    (re.compile(r"\brevert\b", re.IGNORECASE), "revert"),
    (re.compile(r"\bpatch\b", re.IGNORECASE), "patch"),
    (re.compile(r"\bregression\b", re.IGNORECASE), "regression"),
    (re.compile(r"\bhotfix\b", re.IGNORECASE), "hotfix"),
]


def _match_reasons(message: str) -> list[str]:
    """Return list of match_reason labels for commit message keywords."""
    reasons: list[str] = []
    for pattern, label in _FIX_KEYWORDS:
        if pattern.search(message):
            reasons.append(label)
    return reasons


def _issue_keyword(issue_number: int) -> re.Pattern[str] | None:
    """Build a pattern that matches '#N' or 'issue N' for the triage issue."""
    if issue_number <= 0:
        return None
    return re.compile(
        rf"(?:#\s*{issue_number}|issue\s+{issue_number})", re.IGNORECASE
    )


def _parse_git_log_oneline(output: str) -> list[tuple[str, str]]:
    """Parse `git log --oneline` output into list of (sha, message) tuples."""
    result: list[tuple[str, str]] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(" ", 1)
        if len(parts) == 2:
            result.append((parts[0], parts[1]))
        elif len(parts) == 1:
            result.append((parts[0], ""))
    return result


def collect_history(
    project_root: Path,
    cited_paths: list[dict[str, Any]] | None = None,
    issue_number: int = 0,
) -> CollectorResult:
    """Collect Step 4 git history data.

    Args:
        project_root: project root directory.
        cited_paths: list of path dicts from step3_code.cited_paths.
        issue_number: triage issue number (used for keyword matching).

    Returns CollectorResult with data matching step4_history schema.
    """
    r = CollectorResult()
    if cited_paths is None:
        cited_paths = []

    # Collect unique existing file paths from step3 results
    file_paths: list[str] = []
    for cp in cited_paths:
        if isinstance(cp, dict) and cp.get("exists") and cp.get("file_path"):
            fp = cp["file_path"]
            if fp not in file_paths:
                file_paths.append(fp)

    if not file_paths:
        r.data = {
            "collection_status": _STATUS_SKIPPED,
            "likely_fix_candidates": [],
        }
        log.info("step4_history: no existing cited file paths — skipped")
        return r

    issue_pattern = _issue_keyword(issue_number)
    candidates: list[dict[str, Any]] = []
    seen_shas: set[str] = set()
    any_success = False
    any_error = False

    for file_path in file_paths:
        cmd = [
            "git", "log",
            f"-n{_GIT_LOG_COUNT}",
            "--oneline",
            "--no-decorate",  # defensive: prevent (HEAD->branch) decorations from polluting message field
            "--",
            file_path,
        ]
        rc, out, err = _run(cmd, project_root, timeout=15)

        if rc == 127:
            r.soft_error("git_not_found", "git CLI not found")
            any_error = True
            continue
        if rc != 0:
            r.soft_error("git_log_failed", f"rc={rc} file={file_path}: {err.strip()[:200]}")
            any_error = True
            continue

        any_success = True
        commits = _parse_git_log_oneline(out)

        for sha, message in commits:
            if sha in seen_shas:
                continue

            # Check issue-specific pattern first
            reasons: list[str] = []
            if issue_pattern and issue_pattern.search(message):
                reasons.append(f"issue_ref_#{issue_number}")

            reasons.extend(_match_reasons(message))

            if reasons:
                seen_shas.add(sha)
                candidates.append({
                    "sha": sha,
                    "message": message,
                    "file": file_path,
                    "match_reason": reasons,
                })

    if not any_success and any_error:
        r.data = {
            "collection_status": _STATUS_ERROR,
            "likely_fix_candidates": [],
        }
        return r

    r.data = {
        "collection_status": _STATUS_OK,
        "likely_fix_candidates": candidates,
    }
    return r

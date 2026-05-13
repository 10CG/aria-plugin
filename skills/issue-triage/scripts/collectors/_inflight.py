"""Step 5 — In-flight check (three independent sections).

Three sections are queried independently; each fails soft without blocking the others:

  remote_prs[]   — Forgejo GET /repos/<owner>/<repo>/pulls?state=open&limit=50
                   + keyword match against issue number, cited file basenames,
                   and fix/normalize/triage keywords.

  local_branches[] — git branch -a --list "*<keyword>*" for each keyword derived
                     from the issue number and cited file stems.

  worktrees[]     — git worktree list --porcelain parsed into {path, branch} pairs.

Rule #7 (secret-hygiene): all forgejo CLI calls use capture_output=True via _run().

collection_status values:
  ok      — at least one section returned data (even if empty)
  error   — all three sections failed
  skipped — no owner/repo available for remote_prs query
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ._common import CollectorResult, _run, log

_STATUS_OK = "ok"
_STATUS_ERROR = "error"
_STATUS_SKIPPED = "skipped"

# Keywords appended to every branch search regardless of issue content
_UNIVERSAL_KEYWORDS = ["fix", "triage", "normalize"]


def _build_search_keywords(
    issue_number: int,
    cited_paths: list[dict[str, Any]],
) -> list[str]:
    """Build keyword list for branch/PR matching from issue context."""
    keywords: list[str] = []

    # Issue number in various forms
    if issue_number > 0:
        keywords.append(str(issue_number))
        keywords.append(f"#{issue_number}")
        keywords.append(f"issue-{issue_number}")
        keywords.append(f"fix-{issue_number}")

    # Basenames (stems) of cited files
    for cp in cited_paths or []:
        if isinstance(cp, dict) and cp.get("file_path"):
            stem = Path(cp["file_path"]).stem
            if stem and stem not in keywords:
                keywords.append(stem)

    return keywords


def _collect_remote_prs(
    owner_repo: str,
    issue_number: int,
    cited_paths: list[dict[str, Any]],
    project_root: Path,
    timeout: int = 10,
) -> tuple[list[dict[str, Any]], str | None]:
    """Fetch open PRs and keyword-match them.

    Returns (pr_list, error_or_None).
    """
    endpoint = f"/repos/{owner_repo}/pulls?state=open&limit=50"
    rc, out, err = _run(["forgejo", "GET", endpoint], project_root, timeout=timeout)

    if rc == 127:
        return [], "cli_missing"
    if rc == 124:
        return [], "timeout"
    if rc != 0:
        combined = (out + " " + err).lower()
        if any(k in combined for k in ("401", "unauthorized", "403", "forbidden")):
            return [], "auth_failed"
        if "404" in combined or "not found" in combined:
            return [], "not_found"
        return [], f"forgejo_error_rc{rc}"

    try:
        prs = json.loads(out) if out.strip() else []
    except json.JSONDecodeError as exc:
        return [], f"parse_error: {exc}"

    if not isinstance(prs, list):
        if isinstance(prs, dict) and "message" in prs:
            return [], f"api_error: {prs['message']}"
        return [], "unexpected_response_type"

    keywords = _build_search_keywords(issue_number, cited_paths)
    keywords.extend(_UNIVERSAL_KEYWORDS)

    matched: list[dict[str, Any]] = []
    for pr in prs:
        if not isinstance(pr, dict):
            continue
        title = str(pr.get("title") or "").lower()
        body = str(pr.get("body") or "").lower()
        head_branch = str((pr.get("head") or {}).get("ref") or "").lower()
        haystack = f"{title} {body} {head_branch}"

        match_reasons: list[str] = []
        for kw in keywords:
            if kw.lower() in haystack:
                match_reasons.append(kw)

        if match_reasons:
            matched.append({
                "number": pr.get("number"),
                "title": str(pr.get("title") or ""),
                "state": str(pr.get("state") or "open"),
                "html_url": str(pr.get("html_url") or pr.get("url") or ""),
                "head_branch": str((pr.get("head") or {}).get("ref") or ""),
                "match_reasons": match_reasons,
            })

    return matched, None


def _collect_local_branches(
    issue_number: int,
    cited_paths: list[dict[str, Any]],
    project_root: Path,
    timeout: int = 10,
) -> tuple[list[str], str | None]:
    """Find local (including remote-tracking) branches matching issue keywords.

    Returns (branch_list, error_or_None).
    """
    keywords = _build_search_keywords(issue_number, cited_paths)

    if not keywords:
        return [], None

    found: set[str] = set()

    for kw in keywords:
        # git branch -a --list "*<keyword>*"
        rc, out, err = _run(
            ["git", "branch", "-a", "--list", f"*{kw}*"],
            project_root,
            timeout=timeout,
        )
        if rc == 127:
            return [], "git_not_found"
        if rc != 0:
            log.warning("step5_inflight local_branches: git branch rc=%d kw=%r", rc, kw)
            continue

        for line in out.splitlines():
            branch = line.strip().lstrip("*+ ").strip()  # `+` prefix for worktree-checked-out branches
            if branch and "->" not in branch:
                found.add(branch)

    return sorted(found), None


def _collect_worktrees(
    project_root: Path,
    timeout: int = 10,
) -> tuple[list[dict[str, Any]], str | None]:
    """Parse `git worktree list --porcelain` output.

    Returns (worktree_list, error_or_None).
    Each entry: {path, branch, is_main}
    """
    rc, out, err = _run(
        ["git", "worktree", "list", "--porcelain"],
        project_root,
        timeout=timeout,
    )

    if rc == 127:
        return [], "git_not_found"
    if rc != 0:
        return [], f"git_worktree_error_rc{rc}"

    worktrees: list[dict[str, Any]] = []
    current: dict[str, Any] = {}

    for line in out.splitlines():
        line = line.rstrip()
        if line.startswith("worktree "):
            if current:
                worktrees.append(current)
            current = {"path": line[len("worktree "):].strip(), "branch": None, "is_main": False}
        elif line.startswith("branch "):
            # branch refs/heads/<name>
            ref = line[len("branch "):].strip()
            # Strip refs/heads/ prefix for readability
            if ref.startswith("refs/heads/"):
                ref = ref[len("refs/heads/"):]
            current["branch"] = ref
        elif line == "bare":
            current["is_main"] = False
            current["bare"] = True
        elif line.startswith("HEAD "):
            # detached HEAD: HEAD <sha>
            current["head"] = line[len("HEAD "):].strip()

    if current:
        worktrees.append(current)

    # The first worktree is the main checkout
    if worktrees:
        worktrees[0]["is_main"] = True

    return worktrees, None


def collect_inflight(
    owner_repo: str,
    project_root: Path,
    issue_number: int = 0,
    cited_paths: list[dict[str, Any]] | None = None,
    timeout: int = 10,
) -> CollectorResult:
    """Collect Step 5 in-flight data (three independent sections).

    Args:
        owner_repo: "<owner>/<repo>" string (for remote_prs).
        project_root: project root directory.
        issue_number: triage issue number.
        cited_paths: list of path dicts from step3_code.cited_paths.
        timeout: subprocess timeout seconds.

    Returns CollectorResult with data matching step5_inflight schema.
    """
    r = CollectorResult()
    if cited_paths is None:
        cited_paths = []

    section_errors: list[str] = []

    # Section 1: remote PRs (requires owner_repo)
    remote_prs: list[dict[str, Any]] = []
    if owner_repo:
        prs, pr_err = _collect_remote_prs(
            owner_repo, issue_number, cited_paths, project_root, timeout
        )
        remote_prs = prs
        if pr_err:
            r.soft_error("remote_prs_error", pr_err)
            section_errors.append(f"remote_prs: {pr_err}")
            log.warning("step5_inflight remote_prs: %s", pr_err)
    else:
        log.info("step5_inflight: no owner_repo — remote_prs skipped")
        section_errors.append("remote_prs: skipped (no owner_repo)")

    # Section 2: local branches
    local_branches, branch_err = _collect_local_branches(
        issue_number, cited_paths, project_root, timeout
    )
    if branch_err:
        r.soft_error("local_branches_error", branch_err)
        section_errors.append(f"local_branches: {branch_err}")
        log.warning("step5_inflight local_branches: %s", branch_err)

    # Section 3: worktrees
    worktrees, worktree_err = _collect_worktrees(project_root, timeout)
    if worktree_err:
        r.soft_error("worktrees_error", worktree_err)
        section_errors.append(f"worktrees: {worktree_err}")
        log.warning("step5_inflight worktrees: %s", worktree_err)

    # Determine collection_status
    total_sections = 3
    error_count = len([e for e in section_errors if "skipped" not in e])
    if error_count >= total_sections:
        status = _STATUS_ERROR
    else:
        status = _STATUS_OK

    r.data = {
        "collection_status": status,
        "remote_prs": remote_prs,
        "local_branches": local_branches,
        "worktrees": worktrees,
    }
    return r

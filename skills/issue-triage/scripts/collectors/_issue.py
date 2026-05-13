"""Step 1 — Read issue body + comments + labels.

Fetches the issue from Forgejo using the forgejo CLI wrapper.
Rule #7 (secret-hygiene): all subprocess calls use capture_output=True.
Token/credentials are never echoed.

collection_status values:
  ok      — issue fetched successfully
  error   — forgejo CLI failed (auth, network, not found, etc.)
  skipped — no owner/repo/number could be parsed
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ._common import CollectorResult, _run, log

_STATUS_OK = "ok"
_STATUS_ERROR = "error"
_STATUS_SKIPPED = "skipped"


def _empty_step() -> dict[str, Any]:
    return {
        "collection_status": _STATUS_SKIPPED,
        "title": "",
        "body": "",
        "labels": [],
        "comments": [],
        "state": "",
        "number": None,
    }


def collect_issue(
    owner_repo: str,
    issue_number: int,
    project_root: Path,
    timeout: int = 10,
) -> CollectorResult:
    """Fetch issue + comments from Forgejo API.

    Args:
        owner_repo: "<owner>/<repo>" string.
        issue_number: integer issue number.
        project_root: repo root (used as cwd for subprocess).
        timeout: subprocess timeout seconds.

    Returns CollectorResult with data matching step1_issue schema.
    """
    r = CollectorResult()

    if not owner_repo or issue_number <= 0:
        r.data = _empty_step()
        log.warning("step1_issue: skipped — invalid owner_repo=%r or issue_number=%d",
                    owner_repo, issue_number)
        return r

    # Fetch issue metadata
    endpoint_issue = f"/repos/{owner_repo}/issues/{issue_number}"
    rc_issue, out_issue, err_issue = _run(
        ["forgejo", "GET", endpoint_issue], project_root, timeout=timeout
    )

    if rc_issue == 127:
        r.soft_error("cli_missing", "forgejo CLI not found")
        r.data = {**_empty_step(), "collection_status": _STATUS_ERROR}
        return r

    if rc_issue != 0:
        detail = _classify_forgejo_error(rc_issue, err_issue, out_issue)
        r.soft_error(detail, f"issue fetch rc={rc_issue}")
        r.data = {**_empty_step(), "collection_status": _STATUS_ERROR}
        return r

    try:
        issue_obj = json.loads(out_issue) if out_issue.strip() else {}
    except json.JSONDecodeError as exc:
        r.soft_error("parse_error", f"issue JSON decode: {exc}")
        r.data = {**_empty_step(), "collection_status": _STATUS_ERROR}
        return r

    if isinstance(issue_obj, dict) and "message" in issue_obj:
        r.soft_error("api_error", str(issue_obj.get("message", "")))
        r.data = {**_empty_step(), "collection_status": _STATUS_ERROR}
        return r

    # Fetch comments
    endpoint_comments = (
        f"/repos/{owner_repo}/issues/{issue_number}/comments?limit=50"
    )
    rc_comments, out_comments, err_comments = _run(
        ["forgejo", "GET", endpoint_comments], project_root, timeout=timeout
    )

    comments: list[dict[str, Any]] = []
    if rc_comments == 0 and out_comments.strip():
        try:
            raw_comments = json.loads(out_comments)
            if isinstance(raw_comments, list):
                for c in raw_comments:
                    if isinstance(c, dict):
                        comments.append({
                            "id": c.get("id"),
                            "body": str(c.get("body") or ""),
                            "user": str((c.get("user") or {}).get("login") or ""),
                            "created_at": str(c.get("created_at") or ""),
                        })
        except json.JSONDecodeError as exc:
            log.warning("step1_issue: comments JSON decode failed: %s", exc)
    elif rc_comments != 0:
        log.warning(
            "step1_issue: comments fetch failed rc=%d — continuing without comments",
            rc_comments,
        )

    # Normalise labels
    raw_labels = issue_obj.get("labels") or []
    labels: list[str] = []
    for lbl in raw_labels:
        if isinstance(lbl, dict):
            name = lbl.get("name")
            if isinstance(name, str):
                labels.append(name)
        elif isinstance(lbl, str):
            labels.append(lbl)

    r.data = {
        "collection_status": _STATUS_OK,
        "number": int(issue_obj.get("number") or issue_number),
        "title": str(issue_obj.get("title") or ""),
        "body": str(issue_obj.get("body") or ""),
        "state": str(issue_obj.get("state") or ""),
        "labels": labels,
        "comments": comments,
        "url": str(issue_obj.get("html_url") or issue_obj.get("url") or ""),
        "created_at": str(issue_obj.get("created_at") or ""),
        "updated_at": str(issue_obj.get("updated_at") or ""),
    }
    return r


def _classify_forgejo_error(rc: int, stderr: str, stdout: str) -> str:
    """Map exit code + stderr to a short error category string."""
    if rc == 127:
        return "cli_missing"
    if rc == 124:
        return "timeout"
    combined = (stderr + " " + stdout).lower()
    if any(k in combined for k in ("401", "unauthorized")):
        return "auth_failed"
    if any(k in combined for k in ("403", "forbidden")):
        return "auth_failed"
    if any(k in combined for k in ("404", "not found")):
        return "not_found"
    if any(k in combined for k in ("429", "rate limit", "too many")):
        return "rate_limited"
    if any(k in combined for k in (
        "could not resolve", "network", "unreachable", "connection refused"
    )):
        return "network_unavailable"
    return "unknown_error"

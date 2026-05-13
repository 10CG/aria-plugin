"""Step 3 — Code path verification.

Extracts file:line citations from issue body/comments and verifies:
  - The file path exists in the project root.
  - The cited line number (if given) is within the file's line count.
  - Reads a snippet around the cited line for AI-assisted verification.

Supports 3 citation formats (T1.4, R1 QA-m4):
  1. Backtick inline:  `path/to/file.py:42`  or  `path/to/file.py`
  2. Prose:           path/to/file.py line 42  /  path/to/file.py L42
  3. Markdown link:   [text](url)  where URL contains a file path (with or
                      without #L42 anchor)

collection_status values:
  ok      — at least one citation was found and processed
  error   — citation extraction or file read failed for all entries
  skipped — no citations found in issue body/comments
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ._common import CollectorResult, log

_STATUS_OK = "ok"
_STATUS_ERROR = "error"
_STATUS_SKIPPED = "skipped"

# ── Citation extraction regexes ──────────────────────────────────────────────

# Format 1: backtick inline — `path/to/file.py:42`  or  `path/to/file.py`
_BACKTICK_RE = re.compile(
    r"`([^\s`]+\.(?:py|js|ts|go|rs|rb|java|c|cpp|h|md|yaml|yml|json|toml|sh|bash))"
    r"(?::(\d+))?`",
    re.IGNORECASE,
)

# Format 2a: prose line reference — path/to/file.py line 42
_PROSE_LINE_RE = re.compile(
    r"([\w./\-]+\.(?:py|js|ts|go|rs|rb|java|c|cpp|h|md|yaml|yml|json|toml|sh|bash))"
    r"\s+[Ll](?:ine\s*)?(\d+)",
    re.IGNORECASE,
)

# Format 2b: prose L42 reference — path/to/file.py L42
_PROSE_L_RE = re.compile(
    r"([\w./\-]+\.(?:py|js|ts|go|rs|rb|java|c|cpp|h|md|yaml|yml|json|toml|sh|bash))"
    r":L?(\d+)",
    re.IGNORECASE,
)

# Format 3: markdown link — [label](url) where url contains a file path,
# optionally with #L42 anchor.
# Captures (link_text, url, optional_anchor_line)
_MD_LINK_RE = re.compile(
    r"\[([^\]]*)\]\(((?:https?://[^\s)]*?)"
    r"([\w./\-]+\.(?:py|js|ts|go|rs|rb|java|c|cpp|h|md|yaml|yml|json|toml|sh|bash))"
    r"(?:#[Ll](\d+))?[^\s)]*)\)",
    re.IGNORECASE,
)

# Also catch bare-URL or path references inside markdown links to local files
# e.g. [file.py](aria/skills/foo/file.py#L10)
_MD_LOCAL_LINK_RE = re.compile(
    r"\[([^\]]*)\]\(((?!\s*https?://)"
    r"([\w./\-]+\.(?:py|js|ts|go|rs|rb|java|c|cpp|h|md|yaml|yml|json|toml|sh|bash))"
    r"(?:#[Ll](\d+))?)\)",
    re.IGNORECASE,
)

_SNIPPET_CONTEXT = 3  # lines above and below cited line


def _extract_citations(text: str) -> list[dict[str, Any]]:
    """Return list of {file_path, line, format} dicts from all citation formats."""
    seen: set[tuple[str, int | None]] = set()
    results: list[dict[str, Any]] = []

    def _add(file_path: str, line: int | None, fmt: str) -> None:
        key = (file_path, line)
        if key in seen:
            return
        seen.add(key)
        results.append({"file_path": file_path, "line": line, "format": fmt})

    # Format 1: backtick
    for m in _BACKTICK_RE.finditer(text):
        _add(m.group(1), int(m.group(2)) if m.group(2) else None, "backtick")

    # Format 2a: prose "line N"
    for m in _PROSE_LINE_RE.finditer(text):
        _add(m.group(1), int(m.group(2)), "prose_line")

    # Format 2b: prose :L42 / :42
    for m in _PROSE_L_RE.finditer(text):
        _add(m.group(1), int(m.group(2)), "prose_l")

    # Format 3a: markdown link (remote URL with file path)
    for m in _MD_LINK_RE.finditer(text):
        file_path = m.group(3)
        line = int(m.group(4)) if m.group(4) else None
        _add(file_path, line, "md_link")

    # Format 3b: markdown link (local relative path)
    for m in _MD_LOCAL_LINK_RE.finditer(text):
        file_path = m.group(3)
        line = int(m.group(4)) if m.group(4) else None
        _add(file_path, line, "md_link_local")

    return results


def _verify_citation(
    citation: dict[str, Any],
    project_root: Path,
) -> dict[str, Any]:
    """Check whether a cited path exists and line is in range.

    Returns a result dict with:
      file_path, line, format, exists, line_in_range, snippet, warning
    """
    file_path: str = citation["file_path"]
    cited_line: int | None = citation["line"]
    fmt: str = citation["format"]

    # Try both relative-to-project-root and as-is
    candidate = project_root / file_path
    if not candidate.is_file():
        # Try stripping leading slashes / ./ prefixes
        stripped = file_path.lstrip("/").lstrip("./")
        candidate = project_root / stripped
        if not candidate.is_file():
            return {
                "file_path": file_path,
                "line": cited_line,
                "format": fmt,
                "exists": False,
                "line_in_range": None,
                "snippet": None,
                "warning": "file not found",
            }

    # File exists — read and verify line range
    try:
        lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return {
            "file_path": file_path,
            "line": cited_line,
            "format": fmt,
            "exists": True,
            "line_in_range": None,
            "snippet": None,
            "warning": f"file read error: {exc}",
        }

    total_lines = len(lines)
    line_in_range: bool | None = None
    snippet: str | None = None
    warning: str | None = None

    if cited_line is not None:
        line_in_range = 1 <= cited_line <= total_lines
        if line_in_range:
            # 0-indexed slice for context window
            start = max(0, cited_line - 1 - _SNIPPET_CONTEXT)
            end = min(total_lines, cited_line + _SNIPPET_CONTEXT)
            snippet_lines = lines[start:end]
            # Prefix each line with its 1-based line number
            numbered = [
                f"{start + i + 1}: {l}"
                for i, l in enumerate(snippet_lines)
            ]
            snippet = "\n".join(numbered)
        else:
            warning = (
                f"line {cited_line} out of range (file has {total_lines} lines)"
            )
    else:
        # No line number — provide a short file header as context
        head = lines[:min(5, total_lines)]
        snippet = "\n".join(f"{i + 1}: {l}" for i, l in enumerate(head))

    return {
        "file_path": file_path,
        "line": cited_line,
        "format": fmt,
        "exists": True,
        "line_in_range": line_in_range,
        "snippet": snippet,
        "warning": warning,
        "total_lines": total_lines,
    }


def collect_code(
    project_root: Path,
    issue_body: str = "",
    comments: list[dict[str, Any]] | None = None,
) -> CollectorResult:
    """Collect Step 3 code path verification data.

    Args:
        project_root: project root directory.
        issue_body: raw issue body text from step1_issue.
        comments: list of comment dicts from step1_issue.

    Returns CollectorResult with data matching step3_code schema.
    """
    r = CollectorResult()
    if comments is None:
        comments = []

    # Gather all text to search for citations
    texts = [issue_body] + [c.get("body", "") for c in comments if isinstance(c, dict)]
    all_text = "\n".join(t for t in texts if t)

    citations = _extract_citations(all_text)

    if not citations:
        r.data = {
            "collection_status": _STATUS_SKIPPED,
            "cited_paths": [],
            "matches_description": None,
        }
        log.info("step3_code: no citations found in issue body/comments")
        return r

    verified: list[dict[str, Any]] = []
    any_error = False
    for citation in citations:
        try:
            result = _verify_citation(citation, project_root)
            verified.append(result)
        except Exception as exc:
            log.warning("step3_code: unexpected error verifying %r: %s", citation, exc)
            any_error = True
            verified.append({
                "file_path": citation.get("file_path", ""),
                "line": citation.get("line"),
                "format": citation.get("format", "unknown"),
                "exists": None,
                "line_in_range": None,
                "snippet": None,
                "warning": f"unexpected error: {exc}",
            })

    # matches_description: True if all cited files exist and (where given) line
    # numbers are in range. Left to AI for final judgment — we set conservative
    # bool here based on mechanical checks only.
    all_exist = all(v.get("exists") for v in verified)
    all_in_range = all(
        v.get("line_in_range") is not False  # None (no line cited) is OK
        for v in verified
    )
    matches_description: bool | None = (all_exist and all_in_range) if verified else None

    status = _STATUS_ERROR if (any_error and not verified) else _STATUS_OK

    r.data = {
        "collection_status": status,
        "cited_paths": verified,
        "matches_description": matches_description,
    }
    return r

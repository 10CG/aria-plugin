"""Step 2 — Version check (reported vs current) with fail-soft chain.

Attempts to discover the current project version via a 5-path chain:
  1. {project_root}/aria/.claude-plugin/plugin.json  (Aria meta-repo)
  2. {project_root}/.claude-plugin/plugin.json        (Aria plugin standalone)
  3. {project_root}/VERSION                            (SilkNode + generic)
  4. {project_root}/package.json                       (JS projects)
  5. {project_root}/pyproject.toml                     (Python projects)

First hit wins. All failures → version.current = "unknown", gap = null.

Also reads triage_tool_version from path 1 (aria/.claude-plugin/plugin.json)
per R2 QA-R2-m3 — populated once here, written to top-level report field.

collection_status values:
  ok      — current version resolved via any path
  error   — all 5 paths failed (current = "unknown")
  skipped — no issue body available to extract reported version from
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ._common import CollectorResult, log

_STATUS_OK = "ok"
_STATUS_ERROR = "error"
_STATUS_SKIPPED = "skipped"

# Regex patterns to extract "reported" version from issue body / comments
_VERSION_PATTERNS = [
    re.compile(r"(?:Plugin|version|v)[:\s]+v?(\d+\.\d+\.\d+[^\s,\]]*)", re.IGNORECASE),
    re.compile(r"\bv(\d+\.\d+\.\d+[^\s,\]]*)\b"),
]

# Regex to parse pyproject.toml [project] version = "..."
_PYPROJECT_VERSION_RE = re.compile(
    r'^\s*version\s*=\s*["\']([^"\']+)["\']', re.MULTILINE
)


def _read_json_version(path: Path) -> str | None:
    """Read 'version' field from a JSON file. Returns None on any failure."""
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        v = data.get("version")
        if isinstance(v, str) and v.strip():
            return v.strip()
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        log.debug("version: failed to read %s: %s", path, exc)
    return None


def _read_version_file(path: Path) -> str | None:
    """Read a plain VERSION file (single-line semver). Returns None on failure."""
    if not path.is_file():
        return None
    try:
        content = path.read_text(encoding="utf-8").strip()
        # Accept first non-empty line that looks like a semver
        for line in content.splitlines():
            line = line.strip()
            if re.match(r"^\d+\.\d+\.\d+", line):
                return line
    except (OSError, UnicodeDecodeError) as exc:
        log.debug("version: failed to read VERSION file %s: %s", path, exc)
    return None


def _read_pyproject_version(path: Path) -> str | None:
    """Parse [project] version from pyproject.toml using stdlib.

    Tries tomllib (Python 3.11+) first; falls back to regex for older Pythons.
    Returns None on failure.
    """
    if not path.is_file():
        return None
    try:
        # tomllib is stdlib in Python 3.11+
        import tomllib  # type: ignore[import]
        with path.open("rb") as f:
            data = tomllib.load(f)
        v = (data.get("project") or {}).get("version")
        if isinstance(v, str) and v.strip():
            return v.strip()
        # Also check [tool.poetry.version] as fallback
        v = (data.get("tool") or {}).get("poetry", {}).get("version")
        if isinstance(v, str) and v.strip():
            return v.strip()
    except ImportError:
        # Python < 3.11: fall back to regex
        pass
    except Exception as exc:
        log.debug("version: tomllib parse failed %s: %s", path, exc)

    # Regex fallback
    try:
        content = path.read_text(encoding="utf-8")
        m = _PYPROJECT_VERSION_RE.search(content)
        if m:
            return m.group(1).strip()
    except (OSError, UnicodeDecodeError) as exc:
        log.debug("version: pyproject.toml regex fallback failed %s: %s", path, exc)
    return None


def _discover_current_version(project_root: Path) -> tuple[str, str | None]:
    """Fail-soft 5-path chain. Returns (version_string, triage_tool_version_or_None).

    triage_tool_version is sourced from path 1 (Aria meta-repo) OR path 2
    (Aria plugin standalone repo); both are plugin.json with `version` field.
    Other paths (VERSION/package.json/pyproject.toml) are project-specific
    and do NOT seed triage_tool_version. If the chain fully fails, returns
    ("unknown", None).

    R2 QA-R2-m3 + mid-review M2 fix: path 1 OR path 2 (was path 1 only).
    """
    triage_tool_version: str | None = None

    # Path 1: aria/.claude-plugin/plugin.json (Aria meta-repo)
    p1 = project_root / "aria" / ".claude-plugin" / "plugin.json"
    v = _read_json_version(p1)
    if v:
        triage_tool_version = v
        return v, triage_tool_version

    # Path 2: .claude-plugin/plugin.json (Aria plugin standalone repo)
    p2 = project_root / ".claude-plugin" / "plugin.json"
    v = _read_json_version(p2)
    if v:
        # plugin.json (path 2) ALSO seeds triage_tool_version per M2 fix
        triage_tool_version = v
        return v, triage_tool_version

    # Path 3: VERSION file
    p3 = project_root / "VERSION"
    v = _read_version_file(p3)
    if v:
        return v, triage_tool_version

    # Path 4: package.json
    p4 = project_root / "package.json"
    v = _read_json_version(p4)
    if v:
        return v, triage_tool_version

    # Path 5: pyproject.toml
    p5 = project_root / "pyproject.toml"
    v = _read_pyproject_version(p5)
    if v:
        return v, triage_tool_version

    return "unknown", triage_tool_version


def _extract_reported_version(issue_body: str, comments: list[dict[str, Any]]) -> str | None:
    """Extract reported version from issue body text and comments."""
    texts = [issue_body] + [c.get("body", "") for c in comments if isinstance(c, dict)]
    for text in texts:
        if not text:
            continue
        for pat in _VERSION_PATTERNS:
            m = pat.search(text)
            if m:
                return m.group(1)
    return None


def _version_gap(reported: str | None, current: str) -> str | None:
    """Compute a human-readable gap label. Returns None if either is unknown."""
    if not reported or current == "unknown":
        return None
    if reported == current:
        return "same"
    # Simple semver comparison: if reported < current → "behind"
    try:
        def _parse(v: str) -> tuple[int, ...]:
            # Strip leading 'v'
            v = v.lstrip("v")
            parts = v.split(".")
            return tuple(int(p) for p in parts[:3] if p.isdigit())

        r_parts = _parse(reported)
        c_parts = _parse(current)
        if r_parts and c_parts:
            if r_parts < c_parts:
                return "behind"
            if r_parts > c_parts:
                return "ahead"
        return "different"
    except Exception:
        return "different"


def collect_version(
    project_root: Path,
    issue_body: str = "",
    comments: list[dict[str, Any]] | None = None,
) -> CollectorResult:
    """Collect Step 2 version data.

    Args:
        project_root: project root directory.
        issue_body: raw issue body text (from step1_issue).
        comments: list of comment dicts from step1_issue.

    Returns CollectorResult with data matching step2_version schema.
    Also stores triage_tool_version in data["_triage_tool_version"] for
    triage.py to promote to the top-level report field.
    """
    r = CollectorResult()
    if comments is None:
        comments = []

    current, triage_tool_version = _discover_current_version(project_root)
    reported = _extract_reported_version(issue_body, comments)
    gap = _version_gap(reported, current)

    status: str
    if current == "unknown":
        status = _STATUS_ERROR
        r.soft_error("version_discovery_failed", "all 5 version paths failed")
        log.warning(
            "step2_version: all version paths exhausted — current=unknown"
        )
    else:
        status = _STATUS_OK

    r.data = {
        "collection_status": status,
        "reported": reported,
        "current": current,
        "gap": gap,
        # Internal field: triage.py promotes this to top-level triage_tool_version.
        "_triage_tool_version": triage_tool_version or "unknown",
    }
    return r

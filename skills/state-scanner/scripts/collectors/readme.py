"""Phase 1.8 — README sync check collector."""

from __future__ import annotations

import json
import re
from pathlib import Path

from ._common import CollectorResult

_VERSION_PAT = re.compile(
    r"^>?\s*\*\*(?:版本|Version)\*\*[:：]\s*v?([\d.]+)", re.IGNORECASE | re.MULTILINE
)


def collect_readme_sync(project_root: Path) -> CollectorResult:
    r = CollectorResult()
    root_readme = project_root / "README.md"
    plugin_json = project_root / "aria" / ".claude-plugin" / "plugin.json"

    def _read_version_from_readme(path: Path) -> str | None:
        if not path.is_file():
            return None
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        m = _VERSION_PAT.search(text)
        return m.group(1) if m else None

    root_readme_version = _read_version_from_readme(root_readme)

    plugin_version = None
    aria_readme_version = None
    if plugin_json.is_file():
        try:
            plugin_data = json.loads(plugin_json.read_text(encoding="utf-8"))
            plugin_version = plugin_data.get("version")
        except (OSError, json.JSONDecodeError) as e:
            r.soft_error("plugin_json_read_failed", str(e))

    aria_readme = project_root / "aria" / "README.md"
    aria_readme_version = _read_version_from_readme(aria_readme)

    r.data = {
        "root": {
            "exists": root_readme.is_file(),
            "version": root_readme_version,
        },
        "submodules": {
            "aria": {
                "exists": aria_readme.is_file(),
                "readme_version": aria_readme_version,
                "plugin_version": plugin_version,
                "version_match": (
                    aria_readme_version == plugin_version
                    if (aria_readme_version and plugin_version)
                    else None
                ),
            }
        },
    }
    return r

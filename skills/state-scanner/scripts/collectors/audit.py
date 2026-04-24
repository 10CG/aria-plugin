"""Phase 1.10 — latest audit report frontmatter collector."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ._common import CollectorResult

_AUDIT_FM = re.compile(r"^---\s*\n([\s\S]+?)\n---", re.MULTILINE)


def collect_audit(project_root: Path) -> CollectorResult:
    """Parse .aria/audit-reports/ for most recent report frontmatter."""
    r = CollectorResult()
    audit_dir = project_root / ".aria" / "audit-reports"
    if not audit_dir.is_dir():
        r.data = {"enabled": None, "last_audit": None}
        return r

    reports = sorted(audit_dir.glob("*.md"), key=lambda p: p.stat().st_mtime)
    if not reports:
        r.data = {"enabled": True, "last_audit": None}
        return r

    latest = reports[-1]
    try:
        text = latest.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        r.soft_error("audit_read_failed", str(e))
        r.data = {"enabled": True, "last_audit": None}
        return r

    fm = _AUDIT_FM.search(text)
    meta: dict[str, Any] = {}
    if fm:
        for line in fm.group(1).splitlines():
            if ":" not in line:
                continue
            k, _, v = line.partition(":")
            raw_v = v.strip().strip("\"'")
            # R1-I6: coerce YAML-like booleans so `converged == True` works.
            if raw_v.lower() in ("true", "yes"):
                meta[k.strip()] = True
            elif raw_v.lower() in ("false", "no"):
                meta[k.strip()] = False
            else:
                meta[k.strip()] = raw_v

    r.data = {
        "enabled": True,
        "last_audit": {
            "path": str(latest.relative_to(project_root)),
            "checkpoint": meta.get("checkpoint"),
            "verdict": meta.get("verdict"),
            "converged": meta.get("converged"),
            "timestamp": meta.get("timestamp"),
        },
    }
    return r

"""Shared infrastructure for state-scanner collectors.

This module provides the `CollectorResult` dataclass, the `_run` subprocess
wrapper, and the module-level logger used by every collector in this package.

Invariants preserved from the pre-split scan.py:
- `CollectorResult.soft_error` appends `{error, detail}` dicts and logs a warning.
- `_run` never raises on non-zero rc; returns (rc, stdout, stderr).
- Timeouts coerce to rc=124 (matches GNU timeout convention).
- Missing commands coerce to rc=127.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("state-scanner.scan")

# ----- Forgejo hosts canonical resolver -------------------------------------
# Used by ALL forgejo-aware collectors (forgejo_config.py + issue_scan.py).
# See OpenSpec aria-forgejo-hosts-parameterization for design rationale.

ARIA_FORGEJO_HOSTS_ENV = "ARIA_FORGEJO_HOSTS"
_LEGACY_FORGEJO_FALLBACK: tuple[str, ...] = ("forgejo.10cg.pub",)


def _parse_env_forgejo_hosts() -> tuple[str, ...] | None:
    """Parse `ARIA_FORGEJO_HOSTS` env var (comma-separated host list).

    Returns None when env var is unset, empty, or all-whitespace — callers
    fall through to config / defaults. Duplicates preserved.
    """
    raw = os.environ.get(ARIA_FORGEJO_HOSTS_ENV, "")
    if not raw.strip():
        return None
    hosts = tuple(h.strip() for h in raw.split(",") if h.strip())
    return hosts or None


def _read_config_forgejo_hosts(project_root: Path) -> tuple[str, ...] | None:
    """Read `.aria/config.json` → `state_scanner.issue_scan.platform_hostnames.forgejo`.

    Fail-soft: missing file / parse error / key absent / non-list value → None.
    Empty list `[]` → None (fall through to defaults — explicit empty equals unset,
    avoids silently disabling all forgejo detection).
    """
    cfg_path = project_root / ".aria" / "config.json"
    if not cfg_path.is_file():
        return None
    try:
        with cfg_path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    hosts = (
        ((raw.get("state_scanner") or {}).get("issue_scan") or {})
        .get("platform_hostnames", {})
        .get("forgejo")
    )
    if not isinstance(hosts, list) or not hosts:
        return None
    cleaned = tuple(h for h in hosts if isinstance(h, str) and h.strip())
    return cleaned or None


def resolve_forgejo_hosts(project_root: Path) -> tuple[str, ...]:
    """Canonical 3-layer precedence resolver for Forgejo hostnames.

    Precedence (highest first):
      1. ARIA_FORGEJO_HOSTS env (comma-separated)
      2. .aria/config.json → state_scanner.issue_scan.platform_hostnames.forgejo
      3. Legacy fallback ("forgejo.10cg.pub",)

    Returns an immutable tuple; never empty (fallback guaranteed). Callers must
    treat the result as authoritative — do NOT re-implement precedence locally.
    """
    env_hosts = _parse_env_forgejo_hosts()
    if env_hosts:
        return env_hosts
    config_hosts = _read_config_forgejo_hosts(project_root)
    if config_hosts:
        return config_hosts
    return _LEGACY_FORGEJO_FALLBACK


@dataclass
class CollectorResult:
    data: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, str]] = field(default_factory=list)

    def soft_error(self, kind: str, detail: str) -> None:
        self.errors.append({"error": kind, "detail": detail})
        log.warning("collector soft error: %s — %s", kind, detail)


def _run(cmd: list[str], cwd: Path, timeout: int = 5) -> tuple[int, str, str]:
    """subprocess wrapper: returns (rc, stdout, stderr). Never raises on non-zero rc.

    Locale safety (#61 fix, 2026-05-20): explicit `encoding="utf-8"` +
    `errors="replace"` prevents crashes on Windows CJK locale where the default
    `text=True` would fall back to `locale.getpreferredencoding()` (e.g. GBK on
    Chinese Windows) and fail on UTF-8 git output (commit messages with CJK
    characters or emoji per aria-standards git-commit.md 双语规范). Matches the
    defensive pattern already used at openspec.py:38, readme.py:30, upm.py:335.
    """
    try:
        p = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",     # #61 fix: force UTF-8 (git output is UTF-8 by spec)
            errors="replace",     # #61 fix: never raise on partial/invalid bytes
            timeout=timeout,
            check=False,
        )
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        return 124, "", f"timeout after {timeout}s: {e}"
    except FileNotFoundError as e:
        return 127, "", f"command not found: {e}"
    except UnicodeDecodeError as e:
        # #61 defensive: shouldn't fire with errors="replace" above, but
        # if the reader thread races and surfaces here, soften to a non-fatal
        # rc rather than letting it propagate to scan.py exit 30.
        return 125, "", f"decode error: {e}"

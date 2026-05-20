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

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("state-scanner.scan")


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

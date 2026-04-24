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
    """subprocess wrapper: returns (rc, stdout, stderr). Never raises on non-zero rc."""
    try:
        p = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        return 124, "", f"timeout after {timeout}s: {e}"
    except FileNotFoundError as e:
        return 127, "", f"command not found: {e}"

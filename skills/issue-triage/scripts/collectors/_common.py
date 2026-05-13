"""Shared infrastructure for issue-triage collectors.

Provides CollectorResult dataclass, _run subprocess wrapper, and module-level
logger used by every collector in this package.

Rule #7 (secret-hygiene): _run always uses capture_output=True so that tokens
and secrets from forgejo CLI are never echoed to stdout/stderr visible in chat.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("issue-triage.triage")


@dataclass
class CollectorResult:
    data: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, str]] = field(default_factory=list)

    def soft_error(self, kind: str, detail: str) -> None:
        self.errors.append({"error": kind, "detail": detail})
        log.warning("collector soft error: %s — %s", kind, detail)


def _run(cmd: list[str], cwd: Path, timeout: int = 10) -> tuple[int, str, str]:
    """subprocess wrapper: returns (rc, stdout, stderr). Never raises on non-zero rc.

    Rule #7 compliance: capture_output=True ensures stdout/stderr are never
    forwarded to the process's own stdout/stderr streams. Callers must only
    inspect return code and parsed JSON body — never print raw stdout/stderr.
    """
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

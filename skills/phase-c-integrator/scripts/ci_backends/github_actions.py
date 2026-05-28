"""GitHub Actions CI backend stub (v1.31.0).

Per [DEC 2026-05-28] §Q1 (b) — contract + Aether full + GHA stub.
Real implementation deferred to v1.32.0+ next cycle (~4-6h L2 Spec).

probe() is real (detects gh CLI installed + authed). The two query methods
raise NotImplementedError with operable messages per Hard Constraint #4.
gate_check() will propagate the NIE per Hard Constraint #7 (NOT route to
no_ci_fallback) — set `ci_backends: []` in .aria/config.json to explicitly
disable backend probing.
"""
import shutil
import subprocess
from typing import ClassVar

from .base import CIBackend, CIStatus, InFlightStatus


class GitHubActionsBackend(CIBackend):
    name: ClassVar[str] = "github-actions"

    @classmethod
    def probe(cls) -> bool:
        if not shutil.which("gh"):
            return False
        try:
            result = subprocess.run(
                ["gh", "auth", "status"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False

    def query_pr_ci(self, pr_ref: str) -> CIStatus:
        raise NotImplementedError(
            "GHA backend probe succeeded but query_pr_ci not implemented; "
            "PR welcome (see aria/skills/phase-c-integrator/SKILL.md §C.2.4.X). "
            "Per Hard Constraint #7, gate_check() will abort here, NOT skip — "
            "set ci_backends: [] in .aria/config.json to explicitly disable."
        )

    def query_branch_in_flight(self, branch: str) -> InFlightStatus:
        raise NotImplementedError(
            "GHA backend probe succeeded but query_branch_in_flight not "
            "implemented; PR welcome (see aria/skills/phase-c-integrator/"
            "SKILL.md §C.2.4.X). Per Hard Constraint #7, gate_check() will "
            "abort here, NOT skip — set ci_backends: [] in .aria/config.json "
            "to explicitly disable."
        )

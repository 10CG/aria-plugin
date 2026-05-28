"""CI backend abstraction (ABC + data contracts).

Per [DEC 2026-05-28] §Q4 (b) 双方法 + dataclass + Hard Constraint #8 (static registry).

Implementations live in sibling files (aether.py, github_actions.py) and are
registered in __init__.py via static import (no decorator, no entry-point).
Precedence is BACKENDS list order in __init__.py — no priority field per
Rev1 R1 ba F-06 + qa F-06.

Per Hard Constraint #7: backend.query_*() methods MUST raise NotImplementedError
if probe() succeeds but query is unimplemented (e.g. GHA stub). gate_check()
will propagate the NIE (abort, NOT route through no_ci_fallback) to prevent
Rule #8 mechanism silent downgrade.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar, Literal


@dataclass
class CIStatus:
    """PR CI status check result (per Rule #8 (a) check).

    Backend implementations translate their native CI response (e.g. Aether JSON,
    GitHub Actions JSON) into this neutral schema. Callers access via attribute
    (not dict key) per AC-5.4.
    """

    state: Literal["passing", "failing", "pending", "not_found"]
    run_id: str | None = None
    url: str | None = None
    checked_at: str = ""  # ISO 8601


@dataclass
class InFlightStatus:
    """Main branch in-flight run check result (per Rule #8 (b) check).

    The runs field is list-of-dict (not typed) because each backend has a
    different native run schema. Callers should only consume the `has_runs`
    property and treat the runs list as opaque diagnostic data.
    """

    runs: list[dict] = field(default_factory=list)
    checked_at: str = ""  # ISO 8601

    @property
    def has_runs(self) -> bool:
        return len(self.runs) > 0


class CIBackend(ABC):
    """Abstract base for CI backend integrations.

    Subclasses MUST set the ClassVar `name` to a unique string identifier
    (e.g. "aether-ci-cli", "github-actions"). They MUST implement probe()
    as a classmethod (cheap availability check) and the two query methods.

    Precedence between multiple available backends is determined by the order
    in `BACKENDS` list in __init__.py (Aether first, GitHub Actions second).
    No `priority` field on this class — list order is the explicit precedence
    mechanism (Hard Constraint #8).
    """

    name: ClassVar[str]

    @classmethod
    @abstractmethod
    def probe(cls) -> bool:
        """Detect whether this backend is available on current machine.

        Cheap operation (e.g. shutil.which + optional auth check). MUST be
        side-effect-free and idempotent. Cached via module-level _probe_cache
        in __init__.py — call ci_backends.reset_probe_cache() between tests
        to invalidate (per Hard Constraint #11 Option B).
        """
        ...

    def precheck(self) -> tuple[bool, str]:
        """Optional per-backend post-probe readiness check.

        Default: always (True, ""). Subclasses MAY override for version
        validation or other backend-specific assertions that can't be
        cheaply expressed in probe() (e.g. AetherBackend checks that the
        binary supports the required --in-flight flag).

        Returns (ok, error_message). If ok=False, gate_check translates to
        verdict=FAIL with the error_message in raw_message field. Distinct
        from NotImplementedError (Hard Constraint #7) which must propagate
        and NOT be caught — precheck failures indicate the backend is
        installed but mis-configured (recoverable by user action), while
        NIE indicates the backend is a stub that needs implementation.

        Rev1.2 Phase B addition (not in proposal.md §A — discovered during
        Aether migration as the cleanest way to preserve byte-for-byte the
        verify_aether_in_flight_flag failure → upgrade message behavior).
        """
        return True, ""

    @abstractmethod
    def query_pr_ci(self, pr_ref: str) -> CIStatus:
        """Query PR CI status (Rule #8 (a) check).

        MUST raise NotImplementedError with operable message if this is a stub
        backend (probe() returns True but actual query is not implemented).
        gate_check() will propagate NIE — the caller MUST NOT catch and route
        through no_ci_fallback per Hard Constraint #7.
        """
        ...

    @abstractmethod
    def query_branch_in_flight(self, branch: str) -> InFlightStatus:
        """Query main branch in-flight CI runs (Rule #8 (b) check).

        Same NIE contract as query_pr_ci.
        """
        ...

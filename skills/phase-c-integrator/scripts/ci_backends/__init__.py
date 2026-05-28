"""CI backend registry (static import list per Hard Constraint #8).

Order in BACKENDS list is precedence: AetherBackend probed first,
GitHubActionsBackend probed second. No decorator-based registration,
no setuptools entry-points — explicit static imports only.

Per Hard Constraint #11 (Rev1 Option B): probe results cached in
module-level _probe_cache dict. Call reset_probe_cache() to invalidate
between tests (or between different environments in the same process).
The cache prevents repeated subprocess calls within a single gate_check
invocation but MUST be reset for test isolation.
"""
from .base import CIBackend, CIStatus, InFlightStatus
from .aether import AetherBackend, AetherQueryError
from .github_actions import GitHubActionsBackend

BACKENDS: list[type[CIBackend]] = [AetherBackend, GitHubActionsBackend]

# Probe result cache (Hard Constraint #11 Option B — module-level dict,
# explicitly NOT @functools.lru_cache for test isolation).
_probe_cache: dict[type[CIBackend], bool] = {}


def cached_probe(backend_cls: type[CIBackend]) -> bool:
    """Return cached probe result for a backend class, populating cache if missing."""
    if backend_cls not in _probe_cache:
        _probe_cache[backend_cls] = backend_cls.probe()
    return _probe_cache[backend_cls]


def reset_probe_cache() -> None:
    """Clear the probe result cache.

    Idempotent — safe to call when cache is empty. Tests MUST call this in
    tearDown (or via pytest fixture autouse=True) to prevent state leakage
    between test methods that mock probe() differently.
    """
    _probe_cache.clear()


__all__ = [
    "CIBackend",
    "CIStatus",
    "InFlightStatus",
    "AetherBackend",
    "AetherQueryError",
    "GitHubActionsBackend",
    "BACKENDS",
    "cached_probe",
    "reset_probe_cache",
]

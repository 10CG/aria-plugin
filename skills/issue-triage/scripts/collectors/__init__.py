"""issue-triage collectors package.

Each module exports a `collect_<step>()` function that returns a `CollectorResult`.
Collectors are fail-soft: per-step errors produce `{error, detail}` entries and
never abort the whole triage run.

Invariants (do not break without a triage-report schema_version bump):
- Shared infra lives in `_common.py` (CollectorResult, _run, log).
- All public collector functions are re-exported here for a single import point.
- stdlib-only: subprocess, json, re, os, pathlib, logging. No third-party deps.
- Rule #7 (secret-hygiene): every forgejo CLI call uses capture_output=True.
"""

from ._common import CollectorResult, log
from ._code import collect_code
from ._history import collect_history
from ._inflight import collect_inflight
from ._issue import collect_issue
from ._version import collect_version

__all__ = [
    "CollectorResult",
    "log",
    "collect_code",
    "collect_history",
    "collect_inflight",
    "collect_issue",
    "collect_version",
]

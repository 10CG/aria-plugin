"""state-scanner collectors package.

Each module exports a `collect_<phase>()` function that returns a `CollectorResult`.
Collectors are fail-soft: per-phase errors produce `{error, detail}` entries and
never abort the whole scan.

Invariants (do not break without a snapshot_schema_version bump):
- Shared infra lives in `_common.py` (CollectorResult, _run, log).
- Status regex + normalization lives in `_status.py` (shared by requirements + openspec).
- Git helpers are in `git.py`; `interrupt.py` imports `_current_branch` from there.
- All public collector functions are re-exported here for a single import point.
"""

from ._common import CollectorResult, log
from .architecture import collect_architecture
from .audit import collect_audit
from .changes import collect_changes_analysis
from .custom_checks import collect_custom_checks
from .forgejo_config import collect_forgejo_config
from .git import collect_git_state
from .handoff import collect_handoff
from .interrupt import collect_interrupt_state
from .issue_scan import collect_issue_scan
from .multi_remote import collect_multi_remote
from .openspec import collect_openspec
from .readme import collect_readme_sync
from .requirements import collect_requirements
from .standards import collect_standards
from .sync import collect_sync_state
from .upm import collect_upm_state

__all__ = [
    "CollectorResult",
    "log",
    "collect_architecture",
    "collect_audit",
    "collect_changes_analysis",
    "collect_custom_checks",
    "collect_forgejo_config",
    "collect_git_state",
    "collect_handoff",
    "collect_interrupt_state",
    "collect_issue_scan",
    "collect_multi_remote",
    "collect_openspec",
    "collect_readme_sync",
    "collect_requirements",
    "collect_standards",
    "collect_sync_state",
    "collect_upm_state",
]

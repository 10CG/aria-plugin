"""#166 defect 2 — gate_result() blind to detailed-tasks.yaml-only specs.

Spec `state-scanner-openspec-collector-false-green`: the archive safety net
(`spec_complete.py::gate_result`) early-returns at the tasks.md-absent branch,
so a spec that uses `detailed-tasks.yaml` (task-planner path B) instead of
`tasks.md` silently passes (verdict=pass, d_payload=None) — its residual
deferred/unverified items get buried at archive time with no tracker.

Fix (owner option A): the yaml-only branch must append an `unverified_claims`
entry (with `symbols` key) + set verdict=warn + build a non-None d_payload, so
both #95 surfacing paths (warn_overlay frontmatter + D auto-issue tracker) light
up even in headless archival. Full yaml parsing is deferred (follow-up).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from _helpers import tmp_project, write_file

# Import bare `spec_complete` via scripts/lib (top-level `lib` is shadowed by the
# skill-root package once handoff_multibranch inserts _SS_ROOT — same mechanism
# as test_spec_complete.py + collectors/openspec.py fallback branch).
_LIB_DIR = str(Path(__file__).resolve().parent.parent / "scripts" / "lib")
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)
from spec_complete import gate_result  # noqa: E402

# The stable claim tag the fix appends (tests match on this, not on prose wording).
_SOURCE_UNSUPPORTED_CLAIM = "archive-safety-net-source-unsupported"


def _yaml_only_spec(root, spec_id: str = "yaml-only-spec"):
    spec_dir = root / "openspec" / "changes" / spec_id
    write_file(spec_dir / "proposal.md", f"# {spec_id}\n\n> **Status**: Approved\n\n## Why\ntest\n")
    write_file(spec_dir / "detailed-tasks.yaml", "tasks:\n  - id: TASK-001\n    status: pending\n")
    return spec_dir


class TestGateYamlOnlyDefect2(unittest.TestCase):
    def test_yaml_only_warns_and_builds_payload(self):
        # SC-5: yaml-only → verdict=warn + unverified_claims non-empty (with symbols) + d_payload != None.
        with tmp_project() as root:
            spec_dir = _yaml_only_spec(root)
            result = gate_result(spec_dir)
            self.assertEqual(result["verdict"], "warn")
            self.assertTrue(result["unverified_claims"], "expected a source-unsupported unverified claim")
            claims = {c["claim"] for c in result["unverified_claims"]}
            self.assertIn(_SOURCE_UNSUPPORTED_CLAIM, claims)
            entry = next(c for c in result["unverified_claims"] if c["claim"] == _SOURCE_UNSUPPORTED_CLAIM)
            self.assertIn("symbols", entry)  # type contract {claim, reason, symbols}
            self.assertIsNotNone(result["d_payload"])  # → D auto-issue tracker fires (headless)

    def test_both_sources_no_false_warn(self):
        # SC-6 negative control: tasks.md AND detailed-tasks.yaml both present →
        #   goes the tasks.md path, must NOT emit the source-unsupported claim.
        with tmp_project() as root:
            spec_dir = root / "openspec" / "changes" / "both-spec"
            write_file(spec_dir / "proposal.md", "# both\n\n> **Status**: Approved\n\n## Why\ntest\n")
            write_file(spec_dir / "tasks.md", "# tasks\n\n- [x] 1.1 finished\n")
            write_file(spec_dir / "detailed-tasks.yaml", "tasks:\n  - id: TASK-001\n    status: done\n")
            result = gate_result(spec_dir)
            claims = {c["claim"] for c in result["unverified_claims"]}
            self.assertNotIn(_SOURCE_UNSUPPORTED_CLAIM, claims)


if __name__ == "__main__":
    unittest.main()

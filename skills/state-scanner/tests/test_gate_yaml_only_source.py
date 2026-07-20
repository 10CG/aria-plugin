"""#166 defect 2 → aria-plugin #113: gate_result() and detailed-tasks.yaml-only specs.

**History.** #166 defect 2 fixed the archive safety net's total blindness to
`detailed-tasks.yaml`-only specs (task-planner path B): the tasks.md-absent branch
early-returned with `verdict=pass` / `d_payload=None`, burying residual items at
archive time with no tracker. v1.61.0's fix was an honest but *blanket* posture —
EVERY yaml-only spec got a `archive-safety-net-source-unsupported` unverified
claim + warn, because the gate did not parse the yaml at all.

**Now (#113, this file's current contract).** The gate parses the yaml, so the
blanket tag is retired in favour of precise per-spec verdicts. The test below was
rewritten accordingly (SC-9 carve-out: it encoded the now-retired behaviour and
had to change with it — keeping it green would have welded the blanket noise back
in). Full three-state coverage lives in `test_gate_yaml_datasource.py`; this file
keeps the historical entry points: the residual case that #166 originally cared
about, and the dual-layer negative control (unchanged semantics).
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

# Retired in #113 — asserted absent so the blanket posture cannot silently return.
_SOURCE_UNSUPPORTED_CLAIM = "archive-safety-net-source-unsupported"


def _yaml_only_spec(root, spec_id: str = "yaml-only-spec"):
    spec_dir = root / "openspec" / "changes" / spec_id
    write_file(spec_dir / "proposal.md", f"# {spec_id}\n\n> **Status**: Approved\n\n## Why\ntest\n")
    write_file(spec_dir / "detailed-tasks.yaml", "tasks:\n  - id: TASK-001\n    status: pending\n")
    return spec_dir


class TestGateYamlOnlyDefect2(unittest.TestCase):
    def test_yaml_only_residual_is_enumerated_not_blanketed(self):
        """#113 supersedes the v1.61.0 blanket: the same one-pending-task fixture
        now yields a PRECISE residual in d_payload (so the D auto-issue tracker
        still fires headless, #166's core requirement) with NO blanket claim and
        no verdict inflation (residuals ride the `complete` axis, not `verdict`).
        """
        with tmp_project() as root:
            spec_dir = _yaml_only_spec(root)
            result = gate_result(spec_dir)
            self.assertNotIn(
                _SOURCE_UNSUPPORTED_CLAIM,
                {c["claim"] for c in result["unverified_claims"]},
            )
            self.assertEqual(result["verdict"], "pass")
            self.assertIsNotNone(result["d_payload"])  # → D auto-issue tracker fires
            items = result["d_payload"]["deferred_items"]
            self.assertEqual([i["parent_id"] for i in items], ["TASK-001"])
            self.assertEqual(items[0]["reason"], "status=pending")

    def test_both_sources_no_false_warn(self):
        # Negative control (semantics unchanged across #166 → #113): tasks.md AND
        # detailed-tasks.yaml both present → goes the tasks.md path, no yaml-only claim.
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

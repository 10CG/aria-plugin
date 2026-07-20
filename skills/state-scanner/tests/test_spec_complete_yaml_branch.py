#!/usr/bin/env python3
"""SC-6: is_spec_complete() yaml tasks-branch (aria-plugin #113 TASK-005).

Third axis of the same root cause: with tasks.md absent the verdict used to be
"by normalized Status only" (single signal), so a `detailed-tasks.yaml`-only spec
whose tasks are all done but whose prose Status lagged fell to complete=False and
landed in `design_deferred[]` noise. The OR structure gains a symmetric left half:

    complete := (tasks.md 全[x] ∧ 无标注)
                OR (detailed-tasks.yaml 全 done ∧ 无标注)     # ← new
                OR (_normalize_status(Status) == 'done')

Direction is noise-reduction only (False→True happens only when the yaml really
is all-done and annotation-free); no new False is introduced.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

from _helpers import tmp_project, write_file

# `_helpers` (imported above) already puts scripts/ on sys.path — do NOT insert
# it again at position 0 here: that would move scripts/ ahead of the
# state-scanner root and shadow the top-level `lib` package suite-wide
# (test_collision / test_coordination_ref_lib import `from lib import ...`).
_LIB_DIR = str(Path(__file__).resolve().parent.parent / "scripts" / "lib")
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)
from spec_complete import is_spec_complete  # noqa: E402


def _spec(root, spec_id, status_line, yaml_text):
    spec_dir = root / "openspec" / "changes" / spec_id
    write_file(spec_dir / "proposal.md", f"# {spec_id}\n\n> **Status**: {status_line}\n\n## Why\nx\n")
    write_file(spec_dir / "detailed-tasks.yaml", yaml_text)
    return spec_dir


_ALL_DONE = "tasks:\n  - id: TASK-001\n    status: done\n  - id: TASK-002\n    status: completed\n"
_HAS_RESIDUAL = "tasks:\n  - id: TASK-001\n    status: done\n  - id: TASK-002\n    status: pending\n"


class TestSC6YamlCompleteBranch(unittest.TestCase):
    def test_all_done_yaml_completes_even_when_status_lags(self):
        with tmp_project() as root:
            verdict = is_spec_complete(_spec(root, "s1", "Approved", _ALL_DONE))
            self.assertTrue(verdict["complete"], verdict["reason"])
            self.assertIn("detailed-tasks.yaml", verdict["reason"])

    def test_residual_and_status_not_done_is_incomplete(self):
        with tmp_project() as root:
            verdict = is_spec_complete(_spec(root, "s2", "Approved", _HAS_RESIDUAL))
            self.assertFalse(verdict["complete"])
            self.assertIn("1/2", verdict["reason"])

    def test_residual_but_status_done_still_completes(self):
        # OR right half unchanged — symmetric with the tasks.md path's
        # "unchecked boxes + Status=done → complete" existing behaviour.
        with tmp_project() as root:
            verdict = is_spec_complete(_spec(root, "s3", "Complete", _HAS_RESIDUAL))
            self.assertTrue(verdict["complete"], verdict["reason"])

    def test_annotation_blocks_complete_even_when_all_done(self):
        yaml_text = _ALL_DONE + "    notes: '[TODO: still owed]'\n"
        with tmp_project() as root:
            verdict = is_spec_complete(_spec(root, "s4", "Approved", yaml_text))
            self.assertFalse(verdict["complete"], verdict["reason"])

    def test_parse_failure_falls_through_to_status(self):
        with tmp_project() as root:
            verdict = is_spec_complete(_spec(root, "s5", "Approved", "metadata:\n  x: 1\n"))
            self.assertFalse(verdict["complete"])
            verdict2 = is_spec_complete(_spec(root, "s6", "Complete", "metadata:\n  x: 1\n"))
            self.assertTrue(verdict2["complete"])

    def test_no_yaml_no_tasks_md_unchanged(self):
        with tmp_project() as root:
            spec_dir = root / "openspec" / "changes" / "s7"
            write_file(spec_dir / "proposal.md", "# s7\n\n> **Status**: Approved\n\n## Why\nx\n")
            verdict = is_spec_complete(spec_dir)
            self.assertFalse(verdict["complete"])
            self.assertIn("Status only", verdict["reason"])


class TestDesignDeferredNoiseReduction(unittest.TestCase):
    """Downstream: an all-done yaml-only spec must stop landing in design_deferred."""

    def test_all_done_yaml_leaves_design_deferred(self):
        from collectors.openspec import collect_openspec  # noqa: E402

        with tmp_project() as root:
            _spec(root, "quiet-spec", "Approved", _ALL_DONE)
            data = collect_openspec(Path(root)).data
            ids = {d["id"] for d in data["design_deferred"]}
            self.assertNotIn("quiet-spec", ids)


if __name__ == "__main__":
    unittest.main()

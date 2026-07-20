#!/usr/bin/env python3
"""SC-7: carry_forward_inventory yaml fallback (aria-plugin #113 TASK-006).

collectors/openspec.py only ever read tasks.md for inline carry-forward/defer
annotations, so a `detailed-tasks.yaml`-only spec (task-planner path B) always
contributed 0 — a display-side false green (#113 triage case-3). Fallback reads
the yaml raw text through the SAME regex SOT when tasks.md is absent.

Precedence negative control (决策 6): tasks.md present → yaml NOT scanned, so a
dual-layer spec's output is byte-identical (stale A.3-era yaml annotations must
not double-count).
"""
from __future__ import annotations


import os
import unittest
from pathlib import Path

from _helpers import tmp_project, write_file

from collectors.openspec import collect_openspec  # noqa: E402

_PROPOSAL = "# spec\n\n> **Status**: in_progress\n\n## Why\ntest\n"
_ANNOTATION_YAML = (
    "tasks:\n"
    "  - id: TASK-001\n"
    "    title: first\n"
    "    status: pending\n"
    "    notes: '[TODO: wire the follow-up]'\n"
    "  - id: TASK-002\n"
    "    title: second\n"
    "    status: pending\n"
    "    notes: '[deferred: owner gate]'\n"
)


def _inventory(root):
    return collect_openspec(Path(root)).data["carry_forward_inventory"]


class TestSC7YamlFallback(unittest.TestCase):
    def test_yaml_only_annotations_counted(self):
        with tmp_project() as root:
            spec = root / "openspec" / "changes" / "yaml-only"
            write_file(spec / "proposal.md", _PROPOSAL)
            write_file(spec / "detailed-tasks.yaml", _ANNOTATION_YAML)
            inv = _inventory(root)
            self.assertEqual(inv["total"], 2, inv)
            self.assertIn("yaml-only", inv["by_change"])
            self.assertEqual(inv["by_change"]["yaml-only"]["count"], 2)

    def test_dual_layer_precedence_yaml_not_scanned(self):
        # tasks.md present (even with ZERO annotations) → yaml annotations must
        # NOT be picked up; the spec contributes nothing.
        with tmp_project() as root:
            spec = root / "openspec" / "changes" / "dual-layer"
            write_file(spec / "proposal.md", _PROPOSAL)
            write_file(spec / "tasks.md", "# tasks\n\n- [x] 1.1 clean\n")
            write_file(spec / "detailed-tasks.yaml", _ANNOTATION_YAML)
            inv = _inventory(root)
            self.assertEqual(inv["total"], 0, inv)
            self.assertNotIn("dual-layer", inv["by_change"])

    def test_tasks_md_annotations_still_win(self):
        # positive control: tasks.md path unchanged
        with tmp_project() as root:
            spec = root / "openspec" / "changes" / "md-spec"
            write_file(spec / "proposal.md", _PROPOSAL)
            write_file(spec / "tasks.md", "# tasks\n\n- [x] 1.1 done [TODO: later]\n")
            write_file(spec / "detailed-tasks.yaml", _ANNOTATION_YAML)
            inv = _inventory(root)
            self.assertEqual(inv["total"], 1, inv)

    def test_yaml_only_without_annotations_is_zero(self):
        with tmp_project() as root:
            spec = root / "openspec" / "changes" / "clean-yaml"
            write_file(spec / "proposal.md", _PROPOSAL)
            write_file(
                spec / "detailed-tasks.yaml",
                "tasks:\n  - id: TASK-001\n    title: clean\n    status: done\n",
            )
            inv = _inventory(root)
            self.assertEqual(inv["total"], 0)

    def test_unreadable_yaml_surfaces_soft_error(self):
        # An unreadable *regular file* — a directory would fail the `.is_file()`
        # guard and never reach the OSError arm at all (pre-merge
        # silent-failure-hunter: the earlier fixture asserted total==0, which
        # held whether or not the soft_error existed — vacuously green).
        with tmp_project() as root:
            spec = root / "openspec" / "changes" / "bad-yaml"
            write_file(spec / "proposal.md", _PROPOSAL)
            yaml_path = spec / "detailed-tasks.yaml"
            write_file(yaml_path, _ANNOTATION_YAML)
            os.chmod(yaml_path, 0o000)
            try:
                if os.access(yaml_path, os.R_OK):  # running as root — chmod is a no-op
                    self.skipTest("cannot make a file unreadable as this user")
                result = collect_openspec(Path(root))
                self.assertEqual(result.data["carry_forward_inventory"]["total"], 0)
                kinds = {e.get("kind") or e.get("error") for e in result.errors}
                self.assertIn("detailed_tasks_read_failed", kinds, result.errors)
            finally:
                os.chmod(yaml_path, 0o644)

    def test_yaml_is_a_directory_is_ignored(self):
        # `.is_file()` False → no fallback attempted, no crash, no spurious error
        with tmp_project() as root:
            spec = root / "openspec" / "changes" / "dir-yaml"
            write_file(spec / "proposal.md", _PROPOSAL)
            (spec / "detailed-tasks.yaml").mkdir(parents=True, exist_ok=True)
            result = collect_openspec(Path(root))
            self.assertEqual(result.data["carry_forward_inventory"]["total"], 0)


if __name__ == "__main__":
    unittest.main()

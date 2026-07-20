#!/usr/bin/env python3
"""SC-12 / SC-13: runtime_probe reachability for yaml-only specs (#113 TASK-004).

**What changes.** `gate_result`'s tasks.md-absent arm returned before the probe
fold (`_fold_runtime_probe_declaration`), so a declared `runtime_probe:` was
silently skipped. Under v1.61.0 that skip hid behind a blanket warn; once #113
lets a clean yaml-only spec reach a genuine `pass`, "declared a probe, passed,
probe never evaluated" would be a NEW false-green corner. The yaml-present arm
therefore falls through to the fold.

**What deliberately does NOT change (SC-13).** This reverses
DEC-20260705-001 §What Changes ③ R3 **only for the yaml-present subclass**, whose
premise ("structurally incomplete spec ⇒ probe meaningless") is exactly what the
precise parser invalidates. The other two tasks.md-absent subclasses keep the
v1.54.0 designed early return:
  - proposal-only (neither tasks.md nor detailed-tasks.yaml) — locked by
    `test_spec_complete.py::TestRuntimeProbeFoldL2ProposalOnlyEvaporates`
    (untouched guard, asserts zero trace);
  - tasks.md present-but-unreadable (OSError arm).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from _helpers import tmp_project, write_file

_LIB_DIR = str(Path(__file__).resolve().parent.parent / "scripts" / "lib")
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)
from spec_complete import gate_result  # noqa: E402

# A declaration whose partition file will not exist → probe resolves to a
# well-formed non-pass outcome without needing live telemetry.
_PROBE_YAML = (
    "runtime_probe:\n"
    "  partition: nonexistent-partition-for-test\n"
    "  symbol: some_symbol\n"
    "  max_age_days: 14\n"
)

_CLEAN_YAML = "tasks:\n  - id: TASK-001\n    title: parser work\n    status: done\n"


def _spec_with_probe(root, spec_id, *, yaml_text: str | None):
    spec_dir = root / "openspec" / "changes" / spec_id
    write_file(
        spec_dir / "proposal.md",
        "---\n" + _PROBE_YAML + "---\n\n"
        f"# {spec_id}\n\n> **Status**: Approved\n\n## Why\ntest\n",
    )
    if yaml_text is not None:
        write_file(spec_dir / "detailed-tasks.yaml", yaml_text)
    return spec_dir


class TestSC12YamlOnlyProbeReached(unittest.TestCase):
    def test_declaration_is_evaluated_for_yaml_only_spec(self):
        with tmp_project() as root:
            result = gate_result(_spec_with_probe(root, "probe-yaml-spec", yaml_text=_CLEAN_YAML))
            # the declaration must be evaluated → the conditional key exists
            self.assertIn("runtime_probe", result)
            self.assertIn(result["runtime_probe"]["outcome"], {"pass", "warn", "skipped", "invalid"})

    def test_probe_warn_reaches_unverified_claims_and_payload(self):
        with tmp_project() as root:
            result = gate_result(_spec_with_probe(root, "probe-warn-spec", yaml_text=_CLEAN_YAML))
            # Pin the fixture premise FIRST (pre-merge silent-failure-hunter):
            # guarding the assertions behind an unasserted `if` would silently
            # degrade this test to a no-op if a missing partition were ever
            # reclassified (e.g. to `skipped`), leaving the SC-12 double-write
            # contract untested while staying green.
            self.assertIn(
                result["runtime_probe"]["outcome"],
                {"warn", "invalid"},
                "fixture premise: a missing partition must resolve to warn/invalid",
            )
            # probe-warn double-write (#95 TASK-007) must survive the new arm:
            # the entry has to be aggregated into d_payload, not dropped.
            self.assertEqual(result["verdict"], "warn")
            self.assertTrue(result["unverified_claims"])
            self.assertIsNotNone(result["d_payload"])
            payload_claims = {c["claim"] for c in result["d_payload"]["unverified_claims"]}
            self.assertEqual(payload_claims, {c["claim"] for c in result["unverified_claims"]})

    def test_residuals_and_probe_coexist_in_payload(self):
        residual_yaml = "tasks:\n  - id: TASK-001\n    title: x\n    status: pending\n"
        with tmp_project() as root:
            result = gate_result(_spec_with_probe(root, "probe-mixed-spec", yaml_text=residual_yaml))
            self.assertIn("runtime_probe", result)
            self.assertIsNotNone(result["d_payload"])
            # residual half survives the fold-order change
            self.assertEqual(
                [i["parent_id"] for i in result["d_payload"]["deferred_items"]], ["TASK-001"]
            )


class TestSC13ProbeBoundaryNegControl(unittest.TestCase):
    """The reversal is scoped to the yaml-present arm — the other two
    tasks.md-absent subclasses keep the v1.54.0 designed early return."""

    def test_proposal_only_still_evaporates(self):
        with tmp_project() as root:
            result = gate_result(_spec_with_probe(root, "probe-bare-spec", yaml_text=None))
            self.assertNotIn("runtime_probe", result)
            self.assertEqual(result["warnings"], [])
            self.assertEqual(result["unverified_claims"], [])
            self.assertEqual(result["soft_errors"], [])
            self.assertIsNone(result["d_payload"])
            self.assertEqual(result["verdict"], "pass")

    def test_readable_tasks_md_folds_probe_as_before(self):
        with tmp_project() as root:
            spec_dir = _spec_with_probe(root, "probe-readable-md-spec", yaml_text=_CLEAN_YAML)
            write_file(spec_dir / "tasks.md", "# tasks\n\n- [x] 1.1 done\n")
            result = gate_result(spec_dir)
            self.assertIn("runtime_probe", result)  # tasks.md path folds probe as always

    def test_unreadable_tasks_md_still_early_returns(self):
        """The OSError arm (`tasks.md` present but unreadable) is the SECOND
        designed early return SC-13 protects. It needs a real unreadable read to
        exercise — a directory named `tasks.md` fails `.is_file()` and would route
        to the yaml arm instead, testing nothing (pre-merge code-review I-3: the
        previous version of this test asserted the opposite of its own name).
        """
        with tmp_project() as root:
            spec_dir = _spec_with_probe(root, "probe-unreadable-md-spec", yaml_text=_CLEAN_YAML)
            tasks_md = spec_dir / "tasks.md"
            write_file(tasks_md, "# tasks\n\n- [x] 1.1 done\n")

            real_read_text = Path.read_text

            def selective_read(self_path, *a, **kw):
                if self_path == tasks_md:
                    raise OSError("injected unreadable tasks.md")
                return real_read_text(self_path, *a, **kw)

            with patch.object(Path, "read_text", selective_read):
                result = gate_result(spec_dir)

            self.assertNotIn("runtime_probe", result)  # designed early return holds
            self.assertIsNone(result["d_payload"])
            self.assertTrue(
                any("tasks.md read failed" in e for e in result["soft_errors"]),
                result["soft_errors"],
            )


if __name__ == "__main__":
    unittest.main()

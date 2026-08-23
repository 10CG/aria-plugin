"""SC-14 doc-sync mechanical checks for aria-plugin#152 (no-run-for-branch).

TASK-010a (this file) lands FIRST and is deliberately RED against the current
tree: it pins down six assertions about doc/config surfaces that TASK-010 and
TASK-011 are supposed to update, plus one already-shipped code fact (TASK-003)
kept as a GREEN control so the harness itself is proven non-vacuous.

GREEN-end ownership (who is expected to flip each assertion, and in what order):
  1. pr_ci_status enum lines in SKILL.md (:180, :276) missing `not_found`
     -> TASK-011
  2. SKILL.md "三态结果:" summary block missing `gate_error` key
     -> TASK-011
  3. main-repo .aria/config.template.json phase_c_integrator.pre_merge_gate
     missing `path_coverage_enabled` / `no_run_prompt_after_observations`
     -> TASK-010
  4. main-repo docs/decisions/DEC-20260731-001-...md missing forward-pointer
     heading + missing 📌 marker in the 退役裁定 section
     -> TASK-011
  5. path_coverage.py module docstring still says "共 9 个" instead of
     "共 8 个" terminal reasons
     -> TASK-011
  6. pre_merge_gate.DEFAULT_CONFIG["no_run_prompt_after_observations"] == 3
     -> TASK-003 (already shipped; GREEN from the start, negative control)

Each test method's docstring states, in one sentence, how it can go red and
how it flips green — per project convention (memory
feedback_test_asserts_what_its_name_claims.md): a test's claimed meaning must
match what it actually verifies.

Run: python3 -m pytest skills/phase-c-integrator/tests/test_doc_sync_no_run.py -q
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup — same pattern as test_pre_merge_gate.py in this directory.
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
_SKILL_MD = _HERE.parent / "SKILL.md"
_SCRIPTS_DIR = _HERE.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import path_coverage  # noqa: E402
import pre_merge_gate  # noqa: E402

# ---------------------------------------------------------------------------
# Main-repo root: this file lives at
#   aria/skills/phase-c-integrator/tests/test_doc_sync_no_run.py
# inside the aria-plugin repo, itself a git submodule of the Aria meta-repo.
# parents[0]=tests -> [1]=phase-c-integrator -> [2]=skills -> [3]=aria ->
# [4]=<Aria meta-repo root>, where docs/decisions/ and .aria/ live (same
# precedent as skills/state-scanner/tests/test_spec_complete.py:94).
# ---------------------------------------------------------------------------
_ARIA_META_ROOT = Path(__file__).resolve().parents[4]


def _snippet(text: str, needle: str, radius: int = 40) -> str:
    """Small context window around `needle` in `text`, for readable asserts."""
    idx = text.find(needle)
    if idx == -1:
        return f"<{needle!r} not found; len(text)={len(text)}>"
    start = max(0, idx - radius)
    end = min(len(text), idx + len(needle) + radius)
    return text[start:end]


class DocSyncNoRunTests(unittest.TestCase):
    """SC-14 mechanical doc-sync checks for aria-plugin#152."""

    # -- 1. SKILL.md pr_ci_status enum lines -------------------------------

    def test_pr_ci_status_enum_lines_include_not_found(self) -> None:
        """RED now, GREEN after TASK-011.

        How it goes red: an "enum line" is any SKILL.md line containing both
        `pr_ci_status` and the literal `"passing"`; the two current instances
        (output-schema summary ~:180 and JSON schema ~:276) both list only
        passing|failing|pending|not_applicable, so `not_found` is absent from
        at least one (currently both) -> assertEqual(missing, []) fails.
        How it goes green: TASK-011 appends `not_found` to every such line.
        """
        text = _SKILL_MD.read_text(encoding="utf-8")
        lines = text.split("\n")
        enum_lines = [
            line for line in lines if "pr_ci_status" in line and '"passing"' in line
        ]
        self.assertGreaterEqual(
            len(enum_lines),
            2,
            "locator guard failed: expected >=2 pr_ci_status enum lines in "
            f"SKILL.md, found {len(enum_lines)}: {enum_lines!r}",
        )
        missing = [line for line in enum_lines if "not_found" not in line]
        self.assertEqual(
            missing,
            [],
            f"pr_ci_status enum line(s) still missing not_found: {missing!r}",
        )

    # -- 2. SKILL.md 三态结果 summary block ---------------------------------

    def test_three_state_summary_block_includes_gate_error(self) -> None:
        """RED now, GREEN after TASK-011.

        How it goes red: the block runs from the line containing `三态结果:`
        up to (excluding) the next line that either starts with `##` or is
        non-empty with zero indentation (currently the `C.2.4.5 - ...` line);
        that block currently ends at `path_coverage: {...}` without ever
        mentioning `gate_error` -> assertIn fails.
        How it goes green: TASK-011 adds a `gate_error` line to the block.
        """
        text = _SKILL_MD.read_text(encoding="utf-8")
        lines = text.split("\n")
        start = next(
            (i for i, line in enumerate(lines) if "三态结果:" in line), None
        )
        self.assertIsNotNone(start, "SKILL.md 未找到「三态结果:」摘要块起点")
        end = len(lines)
        for i in range(start + 1, len(lines)):
            line = lines[i]
            stripped = line.strip()
            if line.startswith("##"):
                end = i
                break
            if stripped != "" and line == stripped:
                end = i
                break
        block = "\n".join(lines[start:end])
        self.assertIn(
            "output:",
            block,
            f"locator guard failed: block has no output: marker: {block!r}",
        )
        self.assertIn(
            "gate_error",
            block,
            f"三态结果 summary block still missing gate_error key: {block!r}",
        )

    # -- 3. main-repo .aria/config.template.json ----------------------------

    def test_config_template_has_no_run_gate_keys(self) -> None:
        """RED now (file present), GREEN after TASK-010; SkipTest only if the
        main-repo config file itself is absent (e.g. aria-plugin cloned
        standalone outside the Aria meta-repo).

        How it goes red: the current phase_c_integrator.pre_merge_gate block
        in .aria/config.template.json has 8 keys, neither
        `path_coverage_enabled` nor `no_run_prompt_after_observations` among
        them -> assertIn fails on the first missing key.
        How it goes green: TASK-010 adds both keys to that block.
        """
        config_path = _ARIA_META_ROOT / ".aria" / "config.template.json"
        if not config_path.is_file():
            raise unittest.SkipTest(
                f"main-repo config template not found at {config_path} "
                "(expected when aria-plugin is tested outside the Aria meta-repo checkout)"
            )
        data = json.loads(config_path.read_text(encoding="utf-8"))
        gate_cfg = data.get("phase_c_integrator", {}).get("pre_merge_gate", {})
        self.assertIn(
            "path_coverage_enabled",
            gate_cfg,
            f"pre_merge_gate keys currently present: {sorted(gate_cfg.keys())!r}",
        )
        self.assertIn(
            "no_run_prompt_after_observations",
            gate_cfg,
            f"pre_merge_gate keys currently present: {sorted(gate_cfg.keys())!r}",
        )

    # -- 4. main-repo DEC-20260731-001 doc -----------------------------------

    def test_dec_doc_forward_pointer_and_marker(self) -> None:
        """RED now (file present), GREEN after TASK-011; SkipTest only if the
        main-repo decision doc itself is absent.

        How it goes red: (i) the last `## `-heading section is currently
        `## 交叉引用`, which does not contain the string `前向指针`
        -> assertIn on the last heading fails; (ii) the `## 退役裁定` section
        (bounded by the next `## ` heading) currently has five bullet points
        with no `📌` character anywhere -> assertIn on the section fails.
        How it goes green: TASK-011 (i) adds a 前向指针-labelled trailing
        section/heading, and (ii) adds a 📌-marked line inside 退役裁定.
        """
        dec_path = (
            _ARIA_META_ROOT
            / "docs"
            / "decisions"
            / "DEC-20260731-001-c24-wait-adjudication-retirement.md"
        )
        if not dec_path.is_file():
            raise unittest.SkipTest(
                f"main-repo decision doc not found at {dec_path} "
                "(expected when aria-plugin is tested outside the Aria meta-repo checkout)"
            )
        text = dec_path.read_text(encoding="utf-8")
        lines = text.split("\n")
        heading_idxs = [i for i, line in enumerate(lines) if line.startswith("## ")]
        self.assertGreaterEqual(
            len(heading_idxs),
            2,
            f"locator guard failed: expected >=2 '## ' headings, found {len(heading_idxs)}",
        )
        last_heading = lines[heading_idxs[-1]]
        self.assertIn(
            "前向指针",
            last_heading,
            f"last '## ' heading still missing 前向指针: {last_heading!r}",
        )

        retire_idx = next(
            (i for i in heading_idxs if "退役裁定" in lines[i]), None
        )
        self.assertIsNotNone(retire_idx, "未找到「## 退役裁定」小节标题")
        later_idxs = [i for i in heading_idxs if i > retire_idx]
        section_end = later_idxs[0] if later_idxs else len(lines)
        section = "\n".join(lines[retire_idx:section_end])
        self.assertIn(
            "过渡规则",
            section,
            f"locator guard failed: 退役裁定 section missing 过渡规则 anchor: {section!r}",
        )
        self.assertIn(
            "📌",
            section,
            f"退役裁定 section still missing 📌 marker: {section!r}",
        )

    # -- 5. path_coverage.py module docstring --------------------------------

    def test_path_coverage_docstring_says_eight_terminal_reasons(self) -> None:
        """RED now, GREEN after TASK-011.

        How it goes red: the module docstring currently reads
        "终态 reason 封闭集共 9 个" (nine), not "...共 8 个" (eight)
        -> assertIn on the eight-count phrase fails, and assertNotIn on the
        stale "共 9 个" phrase also fails (both fire on this file today).
        How it goes green: TASK-011 rewrites the closing sentence to 8.
        """
        doc = path_coverage.__doc__ or ""
        self.assertIn(
            "终态 reason 封闭集共 8 个",
            doc,
            "docstring missing target phrase; context around 封闭集: "
            f"{_snippet(doc, '封闭集')!r}",
        )
        self.assertNotIn(
            "共 9 个",
            doc,
            f"docstring still contains stale count: {_snippet(doc, '共 9 个')!r}",
        )

    # -- 6. pre_merge_gate.DEFAULT_CONFIG (negative control, already GREEN) --

    def test_default_config_has_no_run_prompt_threshold(self) -> None:
        """GREEN from the start (TASK-003 landed before this file).

        Kept as a negative control: proves the six-test harness is not
        vacuously red end-to-end — this one specific fact about the *code*
        side (as opposed to docs) already matches the target, so it must
        pass while the other five (doc/config side) fail.
        """
        self.assertIn(
            "no_run_prompt_after_observations", pre_merge_gate.DEFAULT_CONFIG
        )
        self.assertEqual(
            pre_merge_gate.DEFAULT_CONFIG["no_run_prompt_after_observations"], 3
        )


if __name__ == "__main__":
    unittest.main()

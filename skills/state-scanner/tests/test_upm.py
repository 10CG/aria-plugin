"""Phase 1.4 UPM state collector tests.

Covers D4: YAML `key: |` block scalars return None (not literal '|').
"""

from __future__ import annotations

import unittest

from _helpers import tmp_project, write_file
from collectors.upm import _extract_yaml_scalar, collect_upm_state


class TestYamlScalarExtraction(unittest.TestCase):
    def test_simple_key_value(self):
        block = "current_phase: Phase4\ncurrent_cycle: Cycle9\n"
        self.assertEqual(_extract_yaml_scalar(block, "current_phase"), "Phase4")

    def test_colon_in_value_preserved(self):
        """First-colon partition: `key: M1: Layer 2` → value = 'M1: Layer 2'."""
        block = "current_phase: M1: Layer 2\n"
        self.assertEqual(_extract_yaml_scalar(block, "current_phase"), "M1: Layer 2")

    def test_inline_comment_stripped(self):
        block = "active_module: mobile # note\n"
        self.assertEqual(_extract_yaml_scalar(block, "active_module"), "mobile")

    def test_quoted_value(self):
        block = 'active_module: "mobile"\n'
        self.assertEqual(_extract_yaml_scalar(block, "active_module"), "mobile")

    def test_d4_block_scalar_returns_none(self):
        """D4 intentional divergence: `key: |` must return None, not literal '|'."""
        block = "description: |\n  multi-line\n  content\n"
        self.assertIsNone(_extract_yaml_scalar(block, "description"))

    def test_d4_other_block_markers(self):
        for marker in [">", "|-", ">-", "|+", ">+"]:
            block = f"k: {marker}\n"
            self.assertIsNone(
                _extract_yaml_scalar(block, "k"),
                msg=f"marker {marker!r}",
            )

    def test_missing_key_returns_none(self):
        self.assertIsNone(_extract_yaml_scalar("foo: bar\n", "missing"))

    def test_comments_and_blanks_skipped(self):
        block = "# comment\n\ncurrent_phase: X\n"
        self.assertEqual(_extract_yaml_scalar(block, "current_phase"), "X")


class TestUpmCollector(unittest.TestCase):
    def test_no_upm_file(self):
        with tmp_project() as root:
            r = collect_upm_state(root)
            self.assertFalse(r.data["configured"])
            self.assertIsNone(r.data["current_phase"])

    def test_html_comment_block(self):
        with tmp_project() as root:
            write_file(
                root / "docs" / "project-planning" / "unified-progress-management.md",
                """# UPM

<!-- UPMv2-STATE
current_phase: Phase4
current_cycle: Cycle9
active_module: mobile
-->
""",
            )
            r = collect_upm_state(root)
            self.assertTrue(r.data["configured"])
            self.assertEqual(r.data["current_phase"], "Phase4")
            self.assertEqual(r.data["active_module"], "mobile")

    def test_fenced_yaml_block(self):
        with tmp_project() as root:
            write_file(
                root / "docs" / "project-planning" / "unified-progress-management.md",
                """# UPM

```yaml
UPMv2-STATE:
current_phase: PhaseA
current_cycle: C1
active_module: backend
```
""",
            )
            r = collect_upm_state(root)
            self.assertTrue(r.data["configured"])
            self.assertEqual(r.data["current_phase"], "PhaseA")


# -------------------------------------------------------------------------
# G2: Pending Followups table parsing (T2.3.a-h)
# -------------------------------------------------------------------------


def _upm_with_followups(followups_section: str, with_state: bool = True) -> str:
    """Build a minimal UPM markdown body with optional UPMv2-STATE + a section."""
    state_block = (
        "<!-- UPMv2-STATE\ncurrent_phase: P\n-->\n\n" if with_state else ""
    )
    return f"# UPM\n\n{state_block}{followups_section}\n"


class TestPendingFollowupsParserG2(unittest.TestCase):
    """G2 (state-scanner-inter-cycle-surfacing 2026-05-09): table parser tests."""

    def test_t2_3_a_normal_table(self):
        """T2.3.a: normal 4-6 row table with mixed P1/P2/P3."""
        body = """## Pending Followups

| Priority | Item | Source | Tracking | Next Action |
|----------|------|--------|----------|-------------|
| P1 | Ship feature X | issue#42 | sprint-3 | review |
| P2 | Refactor Y | git ref abc123 | backlog | none |
| P3 | Doc update | wiki | none | author |
| P1 | Hotfix Z | incident#9 | active | deploy |
"""
        with tmp_project() as root:
            write_file(
                root / "docs" / "project-planning" / "unified-progress-management.md",
                _upm_with_followups(body),
            )
            r = collect_upm_state(root)
            fu = r.data["followups"]
            self.assertEqual(len(fu), 4)
            self.assertEqual(fu[0]["priority"], "P1")
            self.assertEqual(fu[0]["item"], "Ship feature X")
            self.assertEqual(fu[0]["source"], "issue#42")
            self.assertEqual(fu[1]["priority"], "P2")
            self.assertEqual(fu[3]["priority"], "P1")
            for row in fu:
                self.assertIn("raw_row", row)

    def test_t2_3_b_empty_table(self):
        """T2.3.b: header + separator only → empty list."""
        body = """## Pending Followups

| Priority | Item |
|----------|------|
"""
        with tmp_project() as root:
            write_file(
                root / "docs" / "project-planning" / "unified-progress-management.md",
                _upm_with_followups(body),
            )
            r = collect_upm_state(root)
            self.assertEqual(r.data["followups"], [])

    def test_t2_3_c_chinese_column_aliases(self):
        """T2.3.c: Chinese column names normalize via alias map."""
        body = """## Pending Followups

| 优先级 | 事项 | 来源 |
|--------|------|------|
| P1 | 上线功能 X | issue#1 |
"""
        with tmp_project() as root:
            write_file(
                root / "docs" / "project-planning" / "unified-progress-management.md",
                _upm_with_followups(body),
            )
            r = collect_upm_state(root)
            fu = r.data["followups"]
            self.assertEqual(len(fu), 1)
            self.assertEqual(fu[0]["priority"], "P1")
            self.assertEqual(fu[0]["item"], "上线功能 X")
            self.assertEqual(fu[0]["source"], "issue#1")

    def test_t2_3_d_missing_columns_filled_null(self):
        """T2.3.d: when a column is missing, the field stays null."""
        body = """## Pending Followups

| Priority | Item |
|----------|------|
| P1 | only two cols |
"""
        with tmp_project() as root:
            write_file(
                root / "docs" / "project-planning" / "unified-progress-management.md",
                _upm_with_followups(body),
            )
            r = collect_upm_state(root)
            fu = r.data["followups"]
            self.assertEqual(len(fu), 1)
            self.assertEqual(fu[0]["item"], "only two cols")
            self.assertIsNone(fu[0]["source"])
            self.assertIsNone(fu[0]["tracking"])
            self.assertIsNone(fu[0]["next_action"])

    def test_t2_3_e_inline_code_in_cell(self):
        """T2.3.e: inline code (`` ` `` wrapped) preserved verbatim."""
        body = """## Pending Followups

| Priority | Item |
|----------|------|
| P2 | call `frobnicate()` after init |
"""
        with tmp_project() as root:
            write_file(
                root / "docs" / "project-planning" / "unified-progress-management.md",
                _upm_with_followups(body),
            )
            r = collect_upm_state(root)
            self.assertEqual(
                r.data["followups"][0]["item"],
                "call `frobnicate()` after init",
            )

    def test_t2_3_f_pipe_escape_in_cell(self):
        """T2.3.f: `\\|` restored as literal `|` after split."""
        body = "## Pending Followups\n\n| Priority | Item |\n|----------|------|\n| P1 | a \\| b \\| c |\n"
        with tmp_project() as root:
            write_file(
                root / "docs" / "project-planning" / "unified-progress-management.md",
                _upm_with_followups(body),
            )
            r = collect_upm_state(root)
            self.assertEqual(r.data["followups"][0]["item"], "a | b | c")

    def test_t2_3_g_multi_table_negative_no_followups_heading(self):
        """T2.3.g: UPM with another table but no `## Pending Followups` heading
        → followups field absent (not empty list)."""
        body = """## Other Section

| Col1 | Col2 |
|------|------|
| a | b |
"""
        with tmp_project() as root:
            write_file(
                root / "docs" / "project-planning" / "unified-progress-management.md",
                _upm_with_followups(body),
            )
            r = collect_upm_state(root)
            self.assertNotIn("followups", r.data)

    def test_t2_3_h_heading_with_leading_space_and_prose_between(self):
        """T2.3.h: heading allows 0-3 leading spaces; prose between heading and table OK."""
        body = """  ### Pending Followups

Some prose paragraph explaining the table below.

More prose.

| Priority | Item |
|----------|------|
| P1 | gated by prose |
"""
        with tmp_project() as root:
            write_file(
                root / "docs" / "project-planning" / "unified-progress-management.md",
                _upm_with_followups(body),
            )
            r = collect_upm_state(root)
            self.assertEqual(len(r.data["followups"]), 1)
            self.assertEqual(r.data["followups"][0]["item"], "gated by prose")

    def test_fullwidth_space_in_heading_rejected(self):
        """BA-10 follow-up: fullwidth space U+3000 in heading prefix MUST NOT match.

        `\\s` includes U+3000; we use `[ \\t]` to reject it explicitly.
        """
        # `　` between `##` and `Pending` — must NOT match.
        body = "##　Pending Followups\n\n| Priority | Item |\n|----|----|\n| P1 | x |\n"
        with tmp_project() as root:
            write_file(
                root / "docs" / "project-planning" / "unified-progress-management.md",
                _upm_with_followups(body),
            )
            r = collect_upm_state(root)
            self.assertNotIn("followups", r.data)

    def test_unknown_priority_normalized(self):
        """Priority value not in P0-P3 → 'unknown' (case-insensitive accepts P3)."""
        body = """## Pending Followups

| Priority | Item |
|----------|------|
| URGENT | something |
| p2 | lowercase OK |
"""
        with tmp_project() as root:
            write_file(
                root / "docs" / "project-planning" / "unified-progress-management.md",
                _upm_with_followups(body),
            )
            r = collect_upm_state(root)
            fu = r.data["followups"]
            self.assertEqual(fu[0]["priority"], "unknown")
            self.assertEqual(fu[1]["priority"], "P2")


# -------------------------------------------------------------------------
# G3: handoff_doc pointer detection (T3.3.a-e)
# -------------------------------------------------------------------------


def _upm_with_state_block(state_body: str) -> str:
    """Build a UPM markdown body with the given content inside UPMv2-STATE block."""
    return f"# UPM\n\n<!-- UPMv2-STATE\n{state_body}\n-->\n"


class TestHandoffDocG3(unittest.TestCase):
    """G3 (state-scanner-inter-cycle-surfacing 2026-05-09): handoff doc detection."""

    def test_t3_3_a_chinese_emoji_english_three_forms(self):
        """T3.3.a: 3 entry forms — Chinese + English + Emoji — all matched."""
        # Chinese form
        with tmp_project() as root:
            write_file(
                root / "docs" / "project-planning" / "unified-progress-management.md",
                _upm_with_state_block(
                    "current_phase: P\n> Next session 入口: 见 [docs/handoff/x.md](docs/handoff/x.md)"
                ),
            )
            (root / "docs" / "handoff").mkdir(parents=True, exist_ok=True)
            (root / "docs" / "handoff" / "x.md").write_text("h")
            r = collect_upm_state(root)
            hd = r.data["handoff_doc"]
            self.assertIsNotNone(hd)
            self.assertEqual(hd["path"], "docs/handoff/x.md")
            self.assertTrue(hd["exists"])

        # English form (fallback regex)
        with tmp_project() as root:
            write_file(
                root / "docs" / "project-planning" / "unified-progress-management.md",
                _upm_with_state_block(
                    "current_phase: P\n> handoff: see [handoff.md](handoff.md)"
                ),
            )
            (root / "handoff.md").write_text("h")
            r = collect_upm_state(root)
            self.assertEqual(r.data["handoff_doc"]["path"], "handoff.md")

        # Emoji form (primary regex)
        with tmp_project() as root:
            write_file(
                root / "docs" / "project-planning" / "unified-progress-management.md",
                _upm_with_state_block(
                    "current_phase: P\n> 🚪 Next session: 见 [docs/handoff/y.md](docs/handoff/y.md)"
                ),
            )
            (root / "docs" / "handoff").mkdir(parents=True, exist_ok=True)
            (root / "docs" / "handoff" / "y.md").write_text("h")
            r = collect_upm_state(root)
            self.assertEqual(r.data["handoff_doc"]["path"], "docs/handoff/y.md")

    def test_t3_3_b_multi_link_first_match_wins(self):
        """T3.3.b: when multiple matches, only the first is kept."""
        with tmp_project() as root:
            write_file(
                root / "docs" / "project-planning" / "unified-progress-management.md",
                _upm_with_state_block(
                    "current_phase: P\n"
                    "> Next session 入口: 见 [docs/handoff/first.md](docs/handoff/first.md)\n"
                    "> Next session 入口: 见 [docs/handoff/second.md](docs/handoff/second.md)"
                ),
            )
            (root / "docs" / "handoff").mkdir(parents=True, exist_ok=True)
            (root / "docs" / "handoff" / "first.md").write_text("h")
            r = collect_upm_state(root)
            self.assertEqual(r.data["handoff_doc"]["path"], "docs/handoff/first.md")

    def test_t3_3_c_path_not_existent_fail_soft(self):
        """T3.3.c: path that doesn't exist → exists=false, no error raised."""
        with tmp_project() as root:
            write_file(
                root / "docs" / "project-planning" / "unified-progress-management.md",
                _upm_with_state_block(
                    "current_phase: P\n> handoff: see [missing.md](missing.md)"
                ),
            )
            r = collect_upm_state(root)
            hd = r.data["handoff_doc"]
            self.assertEqual(hd["path"], "missing.md")
            self.assertFalse(hd["exists"])

    def test_t3_3_d_negative_chinese_word_alone(self):
        """T3.3.d: standalone Chinese 入口 (without `Next session` / `下次 session`
        / `🚪 Next session` / `handoff` / `session`) → no match (BA-02 fix)."""
        with tmp_project() as root:
            # `> 函数入口在 (xxx.md)` and `> 调试入口: 见 [debug.md](debug.md)` — neither matches.
            write_file(
                root / "docs" / "project-planning" / "unified-progress-management.md",
                _upm_with_state_block(
                    "current_phase: P\n"
                    "> 函数入口在 (function.md)\n"
                    "> 调试入口: 见 [debug.md](debug.md)"
                ),
            )
            r = collect_upm_state(root)
            self.assertIsNone(r.data["handoff_doc"])

    def test_t3_3_e_cross_line_no_match(self):
        """T3.3.e: `> Next session 入口...\\n>(下一行) (handoff.md)` MUST NOT match.

        The `[^\\n]` class in the primary regex prevents cross-line greedy match.
        """
        with tmp_project() as root:
            write_file(
                root / "docs" / "project-planning" / "unified-progress-management.md",
                _upm_with_state_block(
                    "current_phase: P\n> Next session 入口: 待补充\n> 见下一行 (handoff.md)"
                ),
            )
            r = collect_upm_state(root)
            self.assertIsNone(r.data["handoff_doc"])

    def test_url_path_unsupported_format(self):
        """URL path (http/https) → exists=false + soft_error('unsupported_path_format')."""
        with tmp_project() as root:
            write_file(
                root / "docs" / "project-planning" / "unified-progress-management.md",
                _upm_with_state_block(
                    "current_phase: P\n"
                    "> handoff: see [https://example.com/x.md](https://example.com/x.md)"
                ),
            )
            r = collect_upm_state(root)
            hd = r.data["handoff_doc"]
            self.assertEqual(hd["path"], "https://example.com/x.md")
            self.assertFalse(hd["exists"])
            error_kinds = [e["error"] for e in r.errors]
            self.assertIn("unsupported_path_format", error_kinds)

    def test_handoff_doc_absent_when_no_match(self):
        """No handoff hint → handoff_doc: null (key present, value null)."""
        with tmp_project() as root:
            write_file(
                root / "docs" / "project-planning" / "unified-progress-management.md",
                _upm_with_state_block("current_phase: P"),
            )
            r = collect_upm_state(root)
            self.assertIsNone(r.data["handoff_doc"])


if __name__ == "__main__":
    unittest.main()

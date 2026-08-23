"""Phase 1.7 architecture collector tests.

Covers D3: chain_valid must reject placeholder strings (TBD / pending / N/A).
"""

from __future__ import annotations

import unittest
from pathlib import Path

from _helpers import tmp_project, write_file
from collectors.architecture import _is_real_prd_reference, collect_architecture


class TestPrdReferenceValidation(unittest.TestCase):
    """D3 intentional divergence: placeholder tokens yield chain_valid=False."""

    def test_real_reference(self):
        self.assertTrue(_is_real_prd_reference("prd-v1.md"))
        self.assertTrue(_is_real_prd_reference("docs/prd-v2.md"))

    def test_placeholders_rejected(self):
        for placeholder in ["TBD", "(pending)", "n/a", "TODO", "placeholder", "待定"]:
            self.assertFalse(_is_real_prd_reference(placeholder))

    def test_none_and_empty(self):
        self.assertFalse(_is_real_prd_reference(None))
        self.assertFalse(_is_real_prd_reference(""))
        # NOTE: "   " (whitespace-only) currently returns True because strip().lower()
        # produces "" which isn't in the placeholder markers set. Documented as-is;
        # call site should .strip() before passing if whitespace should count as empty.


class TestArchitectureCollector(unittest.TestCase):
    def test_missing_file(self):
        with tmp_project() as root:
            r = collect_architecture(root)
            self.assertFalse(r.data["exists"])
            self.assertIsNone(r.data["chain_valid"])

    def test_valid_architecture(self):
        with tmp_project() as root:
            write_file(
                root / "docs" / "architecture" / "system-architecture.md",
                "**Status**: active\n**Last Updated**: 2026-04-24\n**Parent PRD**: prd-v2.md\n",
            )
            r = collect_architecture(root)
            self.assertTrue(r.data["exists"])
            self.assertEqual(r.data["status"], "active")
            self.assertEqual(r.data["last_updated"], "2026-04-24")
            self.assertEqual(r.data["parent_prd"], "prd-v2.md")
            self.assertTrue(r.data["chain_valid"])

    def test_d3_placeholder_breaks_chain(self):
        """D3 regression guard: Parent PRD='TBD' yields chain_valid=False, not True."""
        with tmp_project() as root:
            write_file(
                root / "docs" / "architecture" / "system-architecture.md",
                "**Status**: draft\n**Parent PRD**: TBD\n",
            )
            r = collect_architecture(root)
            self.assertTrue(r.data["exists"])
            self.assertFalse(r.data["chain_valid"])

    def test_blockquote_style_headers(self):
        with tmp_project() as root:
            write_file(
                root / "docs" / "architecture" / "system-architecture.md",
                "> **Status**: draft\n> **Parent PRD**: prd-v1.md\n",
            )
            r = collect_architecture(root)
            self.assertEqual(r.data["status"], "draft")
            self.assertEqual(r.data["parent_prd"], "prd-v1.md")


class TestRegexHardening(unittest.TestCase):
    """Spec `state-scanner-collector-regex-hardening` (2026-04-25): heading
    prefix + fullwidth colon support for architecture field extractors."""

    def test_fullwidth_colon_status(self):
        """i18n: Chinese IME default fullwidth `：` (U+FF1A) must work."""
        with tmp_project() as root:
            write_file(
                root / "docs" / "architecture" / "system-architecture.md",
                "**Status**：active\n**Parent PRD**：prd-zh.md\n**Last Updated**：2026-04-25\n",
            )
            r = collect_architecture(root)
            self.assertEqual(r.data["status"], "active")
            self.assertEqual(r.data["parent_prd"], "prd-zh.md")
            self.assertEqual(r.data["last_updated"], "2026-04-25")

    def test_heading_prefix_status(self):
        """`## Status: Draft` (heading-prefixed, no bold) must work."""
        with tmp_project() as root:
            write_file(
                root / "docs" / "architecture" / "system-architecture.md",
                "## Status: draft\n## Parent PRD: prd-v3.md\n## Last Updated: 2026-04-25\n",
            )
            r = collect_architecture(root)
            self.assertEqual(r.data["status"], "draft")
            self.assertEqual(r.data["parent_prd"], "prd-v3.md")
            self.assertEqual(r.data["last_updated"], "2026-04-25")

    def test_heading_with_fullwidth_colon(self):
        """Heading + fullwidth colon combined."""
        with tmp_project() as root:
            write_file(
                root / "docs" / "architecture" / "system-architecture.md",
                "## Status：active\n## Parent PRD：prd-cn.md\n",
            )
            r = collect_architecture(root)
            self.assertEqual(r.data["status"], "active")
            self.assertEqual(r.data["parent_prd"], "prd-cn.md")

    def test_heading_with_bold(self):
        """`## **Status**: Draft` (heading + bold combined) must work."""
        with tmp_project() as root:
            write_file(
                root / "docs" / "architecture" / "system-architecture.md",
                "## **Status**: draft\n## **Parent PRD**: prd-v4.md\n",
            )
            r = collect_architecture(root)
            self.assertEqual(r.data["status"], "draft")
            self.assertEqual(r.data["parent_prd"], "prd-v4.md")

    def test_blockquote_with_fullwidth_colon(self):
        """`> **Status**：active` (blockquote + fullwidth)."""
        with tmp_project() as root:
            write_file(
                root / "docs" / "architecture" / "system-architecture.md",
                "> **Status**：active\n> **Parent PRD**：prd-bq.md\n",
            )
            r = collect_architecture(root)
            self.assertEqual(r.data["status"], "active")
            self.assertEqual(r.data["parent_prd"], "prd-bq.md")

    def test_backward_compat_unchanged(self):
        """v1.17.2 baseline format still works (regression baseline)."""
        with tmp_project() as root:
            write_file(
                root / "docs" / "architecture" / "system-architecture.md",
                "**Status**: active\n**Parent PRD**: prd-baseline.md\n**Last Updated**: 2026-04-24\n",
            )
            r = collect_architecture(root)
            self.assertEqual(r.data["status"], "active")
            self.assertEqual(r.data["parent_prd"], "prd-baseline.md")
            self.assertEqual(r.data["last_updated"], "2026-04-24")


class TestQualifiedParentPrdVariant(unittest.TestCase):
    """#151: `Parent PRD` must accept an optional qualifier between the key
    and the colon (e.g. `Parent PRD (v1)`), which is a legitimate real-world
    form when one architecture doc hangs off multiple PRDs and each link
    needs a distinguishing label — not a typo. RED against current
    `_ARCH_PRD` (`architecture.py:28-31`), which only allows a single bare
    `(?:\\*\\*)?` between `Parent PRD` and `[：:]` — no qualifier slot.

    Design pinned here (per issue #151 "建议" + owner-set direction):
    - multiple hits collect into an additive `parent_prds: list[str]`
    - existing single-value `parent_prd` stays = first hit (back-compat)
    - `chain_valid` becomes "at least one parsed PRD path exists", not a
      single-value placeholder-only check
    - a bare (non-markdown-link) reference like the pre-existing
      `test_valid_architecture`'s `"prd-v2.md"` keeps its current
      not-existence-checked, non-placeholder-only semantics (that test is
      frozen and asserts chain_valid=True for a file that doesn't exist on
      disk in its tmp fixture) — only markdown-link-form entries
      (`[text](target)`) get their target resolved and existence-checked.
    """

    def test_qualified_variant_collected_as_list(self):
        """RED reason: current regex has no slot for ` (v1)` / ` (v2)`
        between `Parent PRD` and the colon, so `.search()` matches neither
        line at all -> `parent_prd` stays None (not "prd-v1.md") and
        `chain_valid` is False. Separately, `assertIn("parent_prds", ...)`
        fails standalone since the additive field doesn't exist in `r.data`
        at all yet (KeyError-shaped gap, caught as an assertion here)."""
        with tmp_project() as root:
            write_file(
                root / "docs" / "architecture" / "system-architecture.md",
                "**Parent PRD (v1)**: prd-v1.md\n"
                "**Parent PRD (v2)**: prd-v2.md\n",
            )
            r = collect_architecture(root)
            self.assertIn("parent_prds", r.data)
            self.assertEqual(r.data["parent_prds"], ["prd-v1.md", "prd-v2.md"])
            # back-compat: singular field = first hit, doc order.
            self.assertEqual(r.data["parent_prd"], "prd-v1.md")
            # bare non-link reference, non-placeholder: same shape
            # test_valid_architecture already relies on for chain_valid=True
            # with a file that doesn't exist on disk — that test is frozen,
            # so this must hold too (see class docstring).
            self.assertTrue(r.data["chain_valid"])

    def test_single_unqualified_hit_yields_singleton_list(self):
        """Negative control (over-fix guard, #151-style "unqualified form
        still matches"): one ordinary `**Parent PRD**:` line with NO
        qualifier must still produce a 1-element `parent_prds`, proving the
        new list mechanism doesn't require a qualifier to activate and
        doesn't need 2+ hits to produce a well-formed list. RED reason:
        `parent_prds` is absent from `r.data` today (`assertIn` fails) —
        the single-value extraction itself already works pre-fix and is not
        what this test is probing."""
        with tmp_project() as root:
            write_file(
                root / "docs" / "architecture" / "system-architecture.md",
                "**Parent PRD**: prd-solo.md\n",
            )
            r = collect_architecture(root)
            self.assertIn("parent_prds", r.data)
            self.assertEqual(r.data["parent_prds"], ["prd-solo.md"])
            self.assertEqual(r.data["parent_prd"], "prd-solo.md")

    def test_qualified_variant_arbitrary_content(self):
        """The qualifier grammar must be generic (any parenthesized content),
        not hardcoded to `v1`/`v2` tokens — matches the issue's suggested
        `Parent PRD(?:\\s*\\([^)]*\\))?` pattern. RED reason: `**Parent PRD
        (draft, under review)**:` doesn't match the current regex at all
        (no qualifier slot), so `parent_prd` is None instead of the
        expected value."""
        with tmp_project() as root:
            write_file(
                root / "docs" / "architecture" / "system-architecture.md",
                "**Parent PRD (draft, under review)**: docs/requirements/prd-x.md\n",
            )
            r = collect_architecture(root)
            self.assertEqual(r.data["parent_prd"], "docs/requirements/prd-x.md")
            self.assertIn("parent_prds", r.data)
            self.assertEqual(r.data["parent_prds"], ["docs/requirements/prd-x.md"])

    def test_chain_valid_true_when_at_least_one_qualified_link_resolves(self):
        """`chain_valid` criterion = "at least one parsed PRD path exists",
        NOT "first entry" and NOT "all entries". Two qualified markdown-link
        entries: v1's link target is missing on disk, v2's target is a real
        file this test creates. Must resolve True (v2 saves it), and BOTH
        entries — including the broken one — must still be present in
        `parent_prds` (the list is a transparent record, not
        pre-filtered-to-valid-only). RED reason: today neither qualified
        line matches at all, so `parent_prd` stays None -> chain_valid False
        (wrong reason: "no input", not "no valid entry"), and `parent_prds`
        is missing from `r.data` entirely.

        Pins the round-2 rebuttal major: each `parent_prds` entry for a
        link-form line stores the link **target** verbatim
        (`../requirements/...md`) — NOT the raw `[text](target)` capture
        (brackets and display text included). A bad implementation that
        stores the whole `[text](target)` string in the list and only
        extracts `target` transiently for the existence check would still
        pass a length-only assertion; this exact-value assertion does not."""
        with tmp_project() as root:
            write_file(root / "docs" / "requirements" / "real-prd.md", "# real\n")
            write_file(
                root / "docs" / "architecture" / "system-architecture.md",
                "**Parent PRD (v1)**: [ghost-prd.md](../requirements/ghost-prd.md)\n"
                "**Parent PRD (v2)**: [real-prd.md](../requirements/real-prd.md)\n",
            )
            r = collect_architecture(root)
            self.assertIn("parent_prds", r.data)
            self.assertEqual(
                r.data["parent_prds"],
                ["../requirements/ghost-prd.md", "../requirements/real-prd.md"],
            )
            # link form: `parent_prd` (singular, first hit) is also the
            # TARGET, not the raw `[ghost-prd.md](../requirements/ghost-prd.md)`
            # capture — see class docstring / round-2 note above.
            self.assertEqual(r.data["parent_prd"], "../requirements/ghost-prd.md")
            self.assertTrue(r.data["chain_valid"])

    def test_chain_valid_false_when_all_qualified_links_unresolved(self):
        """Negative control (over-fix guard): a non-empty, 2-element
        `parent_prds` must NOT make `chain_valid` trivially True — both
        qualified entries here point at markdown-link targets that exist
        nowhere on disk, so `chain_valid` must stay False. RED reason
        (different shape than a plain wrong-value failure): the qualified
        lines don't match the current regex at all, so `assertIn` on
        `parent_prds` fails first — `chain_valid` happens to already read
        False today, but for the wrong reason (None input, not "zero valid
        entries out of a real list of 2"). Also pins exact target-only
        storage (see previous test's docstring) for the all-broken case."""
        with tmp_project() as root:
            write_file(
                root / "docs" / "architecture" / "system-architecture.md",
                "**Parent PRD (v1)**: [ghost1.md](../requirements/ghost1.md)\n"
                "**Parent PRD (v2)**: [ghost2.md](../requirements/ghost2.md)\n",
            )
            r = collect_architecture(root)
            self.assertIn("parent_prds", r.data)
            self.assertEqual(
                r.data["parent_prds"],
                ["../requirements/ghost1.md", "../requirements/ghost2.md"],
            )
            self.assertFalse(r.data["chain_valid"])

    def test_real_repo_two_prd_chain_valid_true(self):
        """Ground-truth reproduction of the issue against the actual main
        Aria repo (2 levels above the `aria` submodule this test lives in):
        `docs/architecture/system-architecture.md` really has two
        `**Parent PRD (vN)**:` lines linking to
        `../requirements/prd-aria-v{1,2}.md`, and both targets really exist
        on disk today. After the fix this MUST report chain_valid=True.
        RED reason: the qualified lines don't match today, so `parent_prd`
        is None and `chain_valid` is False. Skips (not fails) if this
        worktree doesn't have the expected superproject layout above the
        submodule (e.g. `aria` checked out standalone without `Aria`).

        Pins the round-2 rebuttal major with an EXACT list-equality
        assertion (not `assertGreaterEqual(len(...), 2)`, which a bad
        implementation storing raw `[text](target)` strings — or picking up
        an unrelated stray `Parent PRD` hit elsewhere in the doc — could
        still satisfy)."""
        main_repo_root = Path(__file__).resolve().parents[4]
        arch_file = main_repo_root / "docs" / "architecture" / "system-architecture.md"
        prd_v1 = main_repo_root / "docs" / "requirements" / "prd-aria-v1.md"
        prd_v2 = main_repo_root / "docs" / "requirements" / "prd-aria-v2.md"
        marker = main_repo_root / "CLAUDE.md"
        if not (arch_file.is_file() and prd_v1.is_file() and prd_v2.is_file() and marker.is_file()):
            self.skipTest(
                "main Aria repo layout not found above the aria submodule "
                f"checkout ({main_repo_root}); expected docs/architecture/"
                "system-architecture.md + docs/requirements/prd-aria-v{1,2}.md "
                "+ CLAUDE.md"
            )
        r = collect_architecture(main_repo_root)
        self.assertTrue(r.data["exists"])
        self.assertEqual(
            r.data["parent_prds"],
            [
                "../requirements/prd-aria-v1.md",
                "../requirements/prd-aria-v2.md",
            ],
        )
        self.assertEqual(r.data["parent_prd"], "../requirements/prd-aria-v1.md")
        self.assertTrue(r.data["chain_valid"])


class TestParentPrdRound2RegexFixes(unittest.TestCase):
    """#151 round 2 — rebuttal-seat minors, now closed with dedicated tests.

    Two independent regex gaps in the round-1 `_ARCH_PRD` / `_MD_LINK_FULL`
    patterns, each with its own RED reason against round-1 code:

    1. The qualifier slot only sat BEFORE the closing `**`
       (`Parent PRD (v1)**:`) — `Parent PRD** (v1):` (qualifier AFTER the
       closing `**`) did not match at all, and a qualifier with one level
       of nested parens (`(v1 (draft))`) also did not match (the round-1
       character class was `[^)]*`, which stops at the FIRST `)` — the
       inner nested one — leaving a dangling unmatched `)` that breaks the
       rest of the pattern).
    2. `_MD_LINK_FULL` required the ENTIRE captured value to be nothing but
       `[text](target)` (anchored with a trailing `$`). Any trailing
       decoration — a CommonMark link title, a stray annotation — made the
       whole entry fall back to the bare-text path, which has NO disk
       check, so a broken link with trailing decoration silently reported
       chain_valid=True. This is the fail-open bug the negative-control
       test below pins directly.
    """

    def test_qualifier_after_closing_bold_matches(self):
        """`**Parent PRD** (v1): prd-v1.md` — qualifier AFTER the closing
        `**`, not before. RED reason: round-1's qualifier slot only sits
        BEFORE `(?:\\*\\*)?`, so this line doesn't match `_ARCH_PRD` at all
        -> `parent_prd` is None instead of `"prd-v1.md"`."""
        with tmp_project() as root:
            write_file(
                root / "docs" / "architecture" / "system-architecture.md",
                "**Parent PRD** (v1): prd-v1.md\n",
            )
            r = collect_architecture(root)
            self.assertEqual(r.data["parent_prd"], "prd-v1.md")
            self.assertEqual(r.data["parent_prds"], ["prd-v1.md"])

    def test_nested_parens_not_supported_and_unclosed_paren_does_not_backtrack(self):
        """Round 3 REVERSAL of the round-2 nested-paren grammar.

        `\\((?:[^()]*|\\([^()]*\\))*\\)` is the `(a*)*` catastrophic-backtracking
        shape: a line starting with `Parent PRD (` whose paren never closes
        (a typo) made `finditer` go exponential (rebuttal-seat critical).
        The qualifier is now LINEAR `\\([^()]*\\)`: nested parens are simply
        not a match (no hit), and an unclosed paren with 40 nested opens
        must finish instantly with zero hits. How it goes red: restore the
        nesting grammar and the timing assertion below blows past 1s."""
        import time

        with tmp_project() as root:
            write_file(
                root / "docs" / "architecture" / "system-architecture.md",
                "**Parent PRD (v1 (draft))**: prd-v1.md\n"
                "**Parent PRD (" + "(" * 40 + " typo never closes\n",
            )
            t0 = time.monotonic()
            r = collect_architecture(root)
            self.assertLess(time.monotonic() - t0, 1.0)
            self.assertEqual(r.data["parent_prds"], [])
            self.assertFalse(r.data["chain_valid"])

    def test_link_with_trailing_title_extracts_target_only_and_resolves(self):
        """`[text](real-prd.md "Some Title")` — CommonMark optional link
        title. Must still be recognized as a link (disk-checked) and the
        stored value must be the target ONLY (`real-prd.md`), the `"Some
        Title"` portion excluded. RED reason: round-1's `_MD_LINK_FULL`
        (`^\\[[^\\]]*\\]\\(([^)]+)\\)$`) captures `real-prd.md "Some Title"`
        as ONE group (title included, since `[^)]+` is greedy up to the
        first `)`) and stores that whole string — including the quoted
        title — as `parent_prds[0]`, and the disk check then looks for a
        file literally named `real-prd.md "Some Title"`, which doesn't
        exist -> chain_valid False instead of True."""
        with tmp_project() as root:
            write_file(root / "docs" / "requirements" / "real-prd.md", "# real\n")
            write_file(
                root / "docs" / "architecture" / "system-architecture.md",
                '**Parent PRD**: [text](../requirements/real-prd.md "Some Title")\n',
            )
            r = collect_architecture(root)
            self.assertEqual(r.data["parent_prds"], ["../requirements/real-prd.md"])
            self.assertTrue(r.data["chain_valid"])

    def test_link_with_trailing_decoration_broken_target_stays_invalid(self):
        """Negative control pinning the round-1 fail-open bug directly:
        `[x](../missing.md) (primary)` — a markdown link whose target does
        NOT exist on disk, followed by trailing decoration `(primary)`.
        Must still be recognized as a link (target extracted as
        `../missing.md`, trailing decoration discarded) and DISK-CHECKED,
        so `chain_valid` must be False. RED reason: round-1's
        `_MD_LINK_FULL` requires the ENTIRE captured value to be nothing
        but `[text](target)` (`$`-anchored) — the trailing ` (primary)`
        breaks that whole-string match, so this entry falls back to the
        bare-text path (`_is_real_prd_reference`), which has NO disk check
        and only rejects placeholder tokens — `"[x](../missing.md)
        (primary)"` is non-empty and not a placeholder, so round-1 reports
        chain_valid=True for a link that is provably broken on disk."""
        with tmp_project() as root:
            write_file(
                root / "docs" / "architecture" / "system-architecture.md",
                "**Parent PRD**: [x](../missing.md) (primary)\n",
            )
            r = collect_architecture(root)
            self.assertEqual(r.data["parent_prds"], ["../missing.md"])
            self.assertFalse(r.data["chain_valid"])


if __name__ == "__main__":
    unittest.main()


class TestParentPrdRound3(unittest.TestCase):
    """#151 round 3 — rebuttal-seat majors/minors on round 2, each pinned.

    - negative controls on the qualifier slot (over-wide grammars like
      `Parent PRD[^:]*:` must NOT match `Parent PRD v1:` / `Parent PRDs:`);
    - `#fragment` / `?query` stripped before the disk check (round-2 false
      negative: target existed but `is_file()` was asked about
      `prd.md#sec`);
    - CommonMark `<dest>` and `'title'` / `(title)` forms recognised as
      links (round-2 narrow grammar kicked them onto the no-disk-check
      bare-text path = fail-open on a broken target);
    - URL-scheme destinations keep bare-text semantics (round 2 flipped
      them from True to False).
    """

    def _doc(self, root: Path, line: str) -> None:
        write_file(root / "docs" / "architecture" / "system-architecture.md", line + "\n")

    def test_qualifier_negative_controls(self):
        """`**Parent PRD v1**:` and `**Parent PRDs**:` are NOT Parent PRD
        lines. How it goes red: an over-wide slot such as
        `Parent PRD[^：:]*[：:]` matches both and yields parent_prds=['x']."""
        for line in ("**Parent PRD v1**: x", "**Parent PRDs**: x", "Parent PRD-ish: x"):
            with self.subTest(line=line), tmp_project() as root:
                self._doc(root, line)
                r = collect_architecture(root)
                self.assertEqual(r.data["parent_prds"], [], line)
                self.assertIsNone(r.data["parent_prd"])

    def test_fragment_and_query_stripped_before_disk_check(self):
        """`[p](../requirements/prd.md#sec)` with the file present resolves.
        How it goes red: round 2 passed `prd.md#sec` to `is_file()` -> False."""
        with tmp_project() as root:
            write_file(root / "docs" / "requirements" / "prd.md", "# prd\n")
            self._doc(root, "**Parent PRD (v1)**: [p](../requirements/prd.md#sec) (primary)")
            r = collect_architecture(root)
            self.assertEqual(r.data["parent_prds"], ["../requirements/prd.md#sec"])
            self.assertTrue(r.data["chain_valid"])

    def test_angle_bracket_dest_and_single_quote_title_are_links(self):
        """`[p](<../requirements/missing.md> 'T')` is a LINK whose target is
        missing -> chain_valid False. How it goes red: round-2 grammar
        (double-quote title only, no `<dest>`) failed the prefix match, so
        the entry fell back to bare text (no disk check) -> True (fail-open)."""
        for line in (
            "**Parent PRD**: [p](<../requirements/missing.md> 'T')",
            "**Parent PRD**: [p]( ../requirements/missing.md (title) )",
        ):
            with self.subTest(line=line), tmp_project() as root:
                self._doc(root, line)
                r = collect_architecture(root)
                self.assertEqual(r.data["parent_prds"], ["../requirements/missing.md"], line)
                self.assertFalse(r.data["chain_valid"], line)

    def test_url_scheme_destination_keeps_bare_text_semantics(self):
        """`[PRD](https://wiki/prd)` cannot be disk-checked -> counts as a
        real reference (pre-#151 behaviour). How it goes red: round 2 ran
        `is_file()` on the URL -> False."""
        with tmp_project() as root:
            self._doc(root, "**Parent PRD**: [PRD](https://wiki.example/prd)")
            r = collect_architecture(root)
            self.assertEqual(r.data["parent_prds"], ["https://wiki.example/prd"])
            self.assertTrue(r.data["chain_valid"])


"""Tests for `lib/linked_issue_field.py` + `scripts/linked_issue_field_probe.py`
(OpenSpec `linked-issue-field-availability`, TASK-001..006 — RED-first).

Neither module exists yet at the time this file is written (baseline @ d69091d):
the top-level `from lib.linked_issue_field import ...` below is EXPECTED to raise
ImportError until TASK-007 lands `lib/linked_issue_field.py`. That is the intended
RED signature for this whole file — do not wrap it in try/except.

Covers (contract = `openspec/changes/linked-issue-field-availability/proposal.md`
§2-§4 + Success Criteria table; `detailed-tasks.yaml` TASK-001..006 verification):
  - SC-1: E0 three-predicate location rule (line anchor / fence exclusion /
    first-hit) + two-spelling closed set (canonical `Linked Issue` + alias
    `关联 Issue`) with ASCII case folding, no plural widening.
  - SC-2: E2 "first non-blank char after the colon must be a backtick" —
    real-corpus regression against a `... (triage `confirmed`, ...)` line.
  - SC-3: E4/E5/E6 multi-value token splitting + per-element normalization.
  - SC-4: §2 sentinel set (`none`/`无`, closed, case-folded on ASCII only,
    unstripped E3 string is the judged object).
  - SC-5: `linked_issue_field_probe.py` check-mode CLI, 6 arms + 2 degraded
    sub-arms, via real subprocess against a throwaway project root.
  - SC-6: SOT template (`standards/openspec/templates/proposal-minimal.md`)
    self-compliance + `spec-drafter/SKILL.md` reference integrity.
  - SC-7a: `spec-drafter/SKILL.md`'s `### Level 2 预览` fenced preview skeleton
    header alignment with the SOT + negative control on its placeholder value.
  - SC-8: `.aria/state-checks.yaml` registration + real subprocess run.
  - SC-9: `--emit-arg` CLI mode (E6 mechanical host), including the two
    mutually-exclusive-flag and missing-file failure paths.
  - Bad-implementation matrix (TASK-006): an independent, flaw-parameterized
    reference extractor (`_ref_extract`) instantiated as 13 named `_bad_*`
    functions, each isolating exactly one of the flaw categories named in the
    proposal's "它怎么会红" column, proving every adversarial fixture actually
    discriminates a wrong implementation from the right one.

Fixture provenance: real-corpus lines are embedded verbatim with a comment
citing the source path:line; everything else is synthetic, inlined as string
literals (no reads from `openspec/` at test time — this repo's own Spec docs
are exactly the false-positive trap §3 of the proposal is about).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

# --- sys.path setup (contract §3 / test_release_by_track.py:23-25 / test_collision.py:22-33) ---
# TWO same-named `lib` packages exist under state-scanner/ (lib/ has collision.py,
# scripts/lib/ does not) — the skill root must win, so scripts/ is APPENDED, never
# inserted ahead of it. `_helpers` also does its own `sys.path.insert(0, scripts/)`
# as an import side effect; appending scripts/ ourselves FIRST makes _helpers's own
# "already in sys.path" guard a no-op, so it cannot silently re-order us.
_SKILL_ROOT = str(Path(__file__).resolve().parents[1])
if _SKILL_ROOT not in sys.path:
    sys.path.insert(0, _SKILL_ROOT)
sys.path.append(str(Path(_SKILL_ROOT) / "scripts"))

from _helpers import tmp_project, write_file  # noqa: E402

from lib.linked_issue_field import (  # noqa: E402
    FieldVerdict,
    extract_linked_issue_field,
    is_sentinel,
    emit_arg,
    FIELD_NAMES,
    SENTINELS,
    VERDICTS,
)
from lib.collision import normalize_linked_issue  # noqa: E402
from collectors.custom_checks import _parse_state_checks_yaml  # noqa: E402

_PROBE = Path(_SKILL_ROOT) / "scripts" / "linked_issue_field_probe.py"

# 主仓根. ⚠️ 契约 (CONTRACT-linked-issue-field.md:60) 与本任务硬约束都写
# `parents[3]` —— 但从本文件的真实路径逐段核算 (aria/skills/state-scanner/tests/
# test_linked_issue_field.py), parents[3] 落在 `aria/` 子模块自身 (它没有
# `standards/` 也没有 `.aria/`), 是**差一层**的错误; parents[4] 才是含
# `standards/`/`​.aria/` 的主仓根 —— 与本目录内四份既有测试的同款用法一致
# (test_architecture.py:311 / test_spec_complete.py:94 / test_gate_yaml_golden_
# corpus.py:42 / phase-c-integrator/tests/test_doc_sync_no_run.py:61, 全部
# `parents[4]`)。已在汇报里点名请主控裁 — 这里按「让测试真的测到东西」选
# parents[4], 不采用会让 SC-6/SC-8 恒 skip 的 parents[3]。
_MAIN_REPO_ROOT = Path(__file__).resolve().parents[4]
_TEMPLATE_PATH = _MAIN_REPO_ROOT / "standards" / "openspec" / "templates" / "proposal-minimal.md"
_STATE_CHECKS_PATH = _MAIN_REPO_ROOT / ".aria" / "state-checks.yaml"
_SPEC_DRAFTER_SKILL = Path(_SKILL_ROOT).parent / "spec-drafter" / "SKILL.md"

_KELVIN_SIGN = "K"  # U+212A KELVIN SIGN — lower()s to ASCII 'k' under Unicode
# case-folding but is NOT itself ASCII; distinguishes re.IGNORECASE|re.ASCII (must
# reject) from bare re.IGNORECASE (Unicode-folds and would wrongly accept).


# ---------------------------------------------------------------------------
# Shared CLI helpers
# ---------------------------------------------------------------------------


def _run_probe(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_PROBE), *args], capture_output=True, text=True
    )


def _first_line(stdout: str) -> str:
    """One shared parser for the CLI's first-line status prefix (OK/FAIL/##SKIP##)."""
    return stdout.split("\n", 1)[0]


# ---------------------------------------------------------------------------
# SC-1 fixtures (E0 三谓词 + 两拼写集合封闭)
# ---------------------------------------------------------------------------

_SC1A_TEXT = "# Proposal\n\n> **关联 Issue**: `10CG/aria-plugin#122`\n\n## Why\ntest\n"

_SC1B_TEXT = (
    "# Proposal\n\nIntro text, no real field.\n\n"
    "```\n> **关联 Issue**: `10CG/aria-plugin#122`\n```\n\n## Why\ntest\n"
)

_SC1C_TEXT = "# Proposal\n\n   > > **关联 Issue**: `10CG/aria-plugin#122`\n\n## Why\ntest\n"

_SC1D_TEXT = (
    "# Proposal\n\nIntro text, no real field.\n\n"
    "> ```\n> **关联 Issue**: `other/repo#999`\n> ```\n\n## Why\ntest\n"
)

_SC1E_TEXT = "# Proposal\n\n> **Linked Issue**: `10CG/aria-plugin#122`\n\n## Why\ntest\n"

_SC1F_TEXT = "# Proposal\n\n> **Linked Issues**: `10CG/aria-plugin#122`\n\n## Why\ntest\n"

_SC1G1_TEXT = "# Proposal\n\n> **Linked issue**: `10CG/aria-plugin#122`\n\n## Why\ntest\n"

_SC1G2_TEXT = "# Proposal\n\n> **LINKED ISSUE**: `10CG/aria-plugin#122`\n\n## Why\ntest\n"

_SC1H_TEXT = (
    "# Proposal\n\n> **Lin" + _KELVIN_SIGN + "ed Issue**: `10CG/aria-plugin#122`\n\n## Why\ntest\n"
)

# SC-2: real corpus, verbatim — openspec/archive/2026-06-11-audit-drift-guard/proposal.md:5
_SC2_REAL_LINE = (
    "> **关联 Issue**: Forgejo [aria-plugin#17]"
    "(https://forgejo.10cg.pub/10CG/aria-plugin/issues/17) "
    "(triage `confirmed`, [comment-12282]"
    "(https://forgejo.10cg.pub/10CG/aria-plugin/issues/17#issuecomment-12282))"
)
_SC2_TEXT = "# Proposal\n\n" + _SC2_REAL_LINE + "\n\n## Why\ntest\n"

# SC-3: multi-value E4/E5/E6 (canonical spelling — not pinned by the proposal
# table to a spelling, so `Linked Issue` is used per §2 "写入侧只教 canonical").
_SC3A_TEXT = "# Proposal\n\n> **Linked Issue**: `10CG/a#1, 10CG/b#2`\n\n## Why\ntest\n"
_SC3B_TEXT = "# Proposal\n\n> **Linked Issue**: `10CG/a#1, [b](url)`\n\n## Why\ntest\n"

# SC-4: sentinel six branches. (a) is pinned by the proposal table to canonical
# `Linked Issue` spelling with the CJK sentinel `无`; (b) is the real-corpus line
# (openspec/archive/2026-08-23-linked-issue-normalization/proposal.md:6, alias
# spelling per that file); (c)-(f) are not spelling-pinned, so canonical is used.
_SC4A_TEXT = "# Proposal\n\n> **Linked Issue**: `无` — 说明\n\n## Why\ntest\n"
_SC4B_REAL_LINE = "> **关联 Issue**: 无"
_SC4B_TEXT = "# Proposal\n\n" + _SC4B_REAL_LINE + "\n\n## Why\ntest\n"
_SC4C_TEXT = "# Proposal\n\n> **Linked Issue**: `none`\n\n## Why\ntest\n"
_SC4D_TEXT = "# Proposal\n\n> **Linked Issue**: `None`\n\n## Why\ntest\n"
_SC4E_TEXT = "# Proposal\n\n> **Linked Issue**: `N/A`\n\n## Why\ntest\n"
_SC4F_TEXT = "# Proposal\n\n> **Linked Issue**: `none `\n\n## Why\ntest\n"

# SC-9: single-file --emit-arg fixtures (canonical spelling; not pinned).
_SC9A_TEXT = "# Proposal\n\n> **Linked Issue**: `{<org>/<repo>#<n>}`\n"
_SC9B_TEXT = "# Proposal\n\n> **Linked Issue**: `none`\n"
_SC9C_TEXT = "# Proposal\n\n> **Linked Issue**: `10CG/a#1, 10CG/b#2`\n"
_SC9D_TEXT = "# Proposal\n\nNo field line at all.\n"


# ---------------------------------------------------------------------------
# Expected (verdict, token_str, emit) triples for every SC-1~4/SC-9 fixture —
# single source of truth consumed by both the direct SC test classes and the
# TASK-006 bad-implementation matrix (memory `pasted-evidence-is-derived`:
# one definition, not re-typed per consumer).
# ---------------------------------------------------------------------------

_FIXTURES: dict[str, tuple[str, tuple[str, "str | None", str]]] = {
    "SC1a": (_SC1A_TEXT, ("OK", "10CG/aria-plugin#122", "10CG/aria-plugin#122")),
    "SC1b": (_SC1B_TEXT, ("NO_FIELD", None, "")),
    "SC1c": (_SC1C_TEXT, ("NO_FIELD", None, "")),
    "SC1d": (_SC1D_TEXT, ("NO_FIELD", None, "")),
    "SC1e": (_SC1E_TEXT, ("OK", "10CG/aria-plugin#122", "10CG/aria-plugin#122")),
    "SC1f": (_SC1F_TEXT, ("NO_FIELD", None, "")),
    "SC1g1": (_SC1G1_TEXT, ("OK", "10CG/aria-plugin#122", "10CG/aria-plugin#122")),
    "SC1g2": (_SC1G2_TEXT, ("OK", "10CG/aria-plugin#122", "10CG/aria-plugin#122")),
    "SC1h": (_SC1H_TEXT, ("NO_FIELD", None, "")),
    "SC2": (_SC2_TEXT, ("NO_TOKEN", None, "")),
    "SC3a": (_SC3A_TEXT, ("OK", "10CG/a#1, 10CG/b#2", "10CG/a#1")),
    "SC3b": (_SC3B_TEXT, ("BAD_TOKEN", "10CG/a#1, [b](url)", "")),
    "SC4a": (_SC4A_TEXT, ("OK", "无", "")),
    "SC4b": (_SC4B_TEXT, ("NO_TOKEN", None, "")),
    "SC4c": (_SC4C_TEXT, ("OK", "none", "")),
    "SC4d": (_SC4D_TEXT, ("OK", "None", "")),
    "SC4e": (_SC4E_TEXT, ("BAD_TOKEN", "N/A", "")),
    "SC4f": (_SC4F_TEXT, ("BAD_TOKEN", "none ", "")),
    "SC9a": (_SC9A_TEXT, ("BAD_TOKEN", "{<org>/<repo>#<n>}", "")),
    "SC9b": (_SC9B_TEXT, ("OK", "none", "")),
    "SC9c": (_SC9C_TEXT, ("OK", "10CG/a#1, 10CG/b#2", "10CG/a#1")),
    "SC9d": (_SC9D_TEXT, ("NO_FIELD", None, "")),
}

# Fixtures that are, BY CONSTRUCTION, immune to all 13 named flaw categories
# below: SC1a/SC4b are pinned by the proposal/real-corpus to a spelling+content
# combination with no exploitable confound for any of the 13 flaws (clean single
# value / bare-CJK-sentinel-with-no-code-span respectively); SC9d is the "no
# field line exists at all" case, which nothing can misparse into something
# else. These three serve as REGRESSION fixtures (the good implementation must
# still get them right — asserted in `test_good_implementation_matches_expected`)
# but are excluded from the "must be discriminated" assertion. Flagged in the
# session report as a scoping judgment call.
_MATRIX_EXEMPT = {"SC1a", "SC4b", "SC9d"}


# ---------------------------------------------------------------------------
# TASK-006 — bad-implementation matrix: one independent, flaw-parameterized
# reference extractor instantiated 13 ways, one per proposal "它怎么会红" flaw.
# ---------------------------------------------------------------------------

_CANONICAL_FIELD_RE = re.compile(
    r"^> \*\*(?:Linked Issue|关联 Issue)\*\*:", re.IGNORECASE | re.ASCII
)
_LOOSE_FIELD_RE = re.compile(r"\*\*(?:Linked Issue|关联 Issue)\*\*:")
_CHINESE_ONLY_FIELD_RE = re.compile(r"^> \*\*关联 Issue\*\*:", re.IGNORECASE | re.ASCII)
_NO_CASE_FOLD_FIELD_RE = re.compile(r"^> \*\*(?:Linked Issue|关联 Issue)\*\*:", re.ASCII)
_UNICODE_FOLD_FIELD_RE = re.compile(r"^> \*\*(?:Linked Issue|关联 Issue)\*\*:", re.IGNORECASE)
_LOOSE_PLURAL_FIELD_RE = re.compile(
    r"^> \*\*(?:Linked Issues?|关联 Issue)\*\*:", re.IGNORECASE | re.ASCII
)

_FENCE_RE = re.compile(r"^[ ]{0,3}(?:> ?)?(?:```|~~~)")
_FENCE_NO_BQ_RE = re.compile(r"^[ ]{0,3}(?:```|~~~)")


def _ref_extract(
    text: str,
    *,
    field_re: "re.Pattern[str]" = _CANONICAL_FIELD_RE,
    fence_re: "re.Pattern[str] | None" = _FENCE_RE,
    code_span_mode: str = "immediate",  # "immediate" | "first_anywhere"
    element_mode: str = "all",  # "all" | "first_only" | "whole_string"
    extra_sentinels: tuple[str, ...] = (),
    sentinel_strip: bool = False,
) -> FieldVerdict:
    """Independent flaw-parameterized reference extractor (TASK-006).

    Deliberately does NOT import any regex/logic from `lib.linked_issue_field`
    (only `normalize_linked_issue`, the shared already-shipped dependency) so
    that a bug shared with the module-under-test cannot hide from the matrix.
    Each `_bad_*` wrapper below fixes every parameter to the E0-E6-correct
    default EXCEPT one, isolating exactly one flaw per adversarial fixture.
    """
    lines = text.split("\n")
    in_fence = False
    hit = None
    for i, raw_line in enumerate(lines):
        line = raw_line.rstrip("\r")
        if fence_re is not None and fence_re.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = field_re.search(line)
        if m and hit is None:
            hit = (i + 1, line, m.end())
    if hit is None:
        return FieldVerdict("NO_FIELD", None, (), None)
    line_no, line, end = hit
    rest = line[end:]

    if code_span_mode == "immediate":
        rest2 = rest.lstrip(" \t")
        if not rest2 or rest2[0] != "`":
            return FieldVerdict("NO_TOKEN", None, (), line_no)
        close = rest2.find("`", 1)
        if close == -1:
            return FieldVerdict("NO_TOKEN", None, (), line_no)
        token_str = rest2[1:close]
    else:  # first_anywhere: first backtick pair anywhere in the remainder
        start = rest.find("`")
        if start == -1:
            return FieldVerdict("NO_TOKEN", None, (), line_no)
        close = rest.find("`", start + 1)
        if close == -1:
            return FieldVerdict("NO_TOKEN", None, (), line_no)
        token_str = rest[start + 1 : close]

    sentinel_check = token_str.strip() if sentinel_strip else token_str
    sentinel_set = {"none", *extra_sentinels}
    if sentinel_check == "无" or (
        sentinel_check.isascii() and sentinel_check.lower() in sentinel_set
    ):
        elements = tuple(e.strip() for e in token_str.split(","))
        return FieldVerdict("OK", token_str, elements, line_no)

    elements = tuple(e.strip() for e in token_str.split(","))
    if element_mode == "whole_string":
        check_targets = (token_str,)
        reported_elements = (token_str,)
    elif element_mode == "first_only":
        check_targets = elements[:1]
        reported_elements = elements
    else:
        check_targets = elements
        reported_elements = elements

    bad = tuple(e for e in check_targets if normalize_linked_issue(e) is None)
    if bad:
        return FieldVerdict("BAD_TOKEN", token_str, reported_elements, line_no, bad)
    return FieldVerdict("OK", token_str, reported_elements, line_no)


def _bad_emit_passthrough(fv: FieldVerdict) -> str:
    """Flaw 13: emit_arg ignores verdict and always passes the first element/
    raw token through — the K8/NEW-01 recurrence the proposal names by name."""
    if fv.token_elements:
        return fv.token_elements[0]
    return fv.token_str or ""


def _bad_loose_predicate(text: str) -> FieldVerdict:
    """Flaw 1 — 松谓词: no line anchor, no fence exclusion at all."""
    return _ref_extract(text, field_re=_LOOSE_FIELD_RE, fence_re=None)


def _bad_no_fence_machine(text: str) -> FieldVerdict:
    """Flaw 2 — 无 fence 状态机: anchored predicate 1 kept, predicate 2 removed."""
    return _ref_extract(text, fence_re=None)


def _bad_fence_missing_bq_prefix(text: str) -> FieldVerdict:
    """Flaw 3 — fence 正则缺 `(?:> ?)?`: blockquote-nested fences go undetected."""
    return _ref_extract(text, fence_re=_FENCE_NO_BQ_RE)


def _bad_chinese_only(text: str) -> FieldVerdict:
    """Flaw 4 — 只认中文拼写: rejects the canonical `Linked Issue` spelling."""
    return _ref_extract(text, field_re=_CHINESE_ONLY_FIELD_RE)


def _bad_no_case_fold(text: str) -> FieldVerdict:
    """Flaw 5 — 不折叠大小写: exact-case only, rejects `Linked issue`/`LINKED ISSUE`."""
    return _ref_extract(text, field_re=_NO_CASE_FOLD_FIELD_RE)


def _bad_unicode_fold(text: str) -> FieldVerdict:
    """Flaw 6 — Unicode 折叠 (无 re.ASCII): IGNORECASE without ASCII, so the
    U+212A KELVIN SIGN homoglyph unicode-folds to 'k' and wrongly matches."""
    return _ref_extract(text, field_re=_UNICODE_FOLD_FIELD_RE)


def _bad_loose_plural(text: str) -> FieldVerdict:
    """Flaw 7 — 放宽单复数: accepts `Linked Issues` (集合外拼写)."""
    return _ref_extract(text, field_re=_LOOSE_PLURAL_FIELD_RE)


def _bad_first_code_span_anywhere(text: str) -> FieldVerdict:
    """Flaw 8 — 取第一个 code span: scans for the first backtick pair anywhere
    in the line's remainder instead of requiring it immediately after the
    colon (E2) — this is exactly what mis-extracts triage verdicts (SC-2)."""
    return _ref_extract(text, code_span_mode="first_anywhere")


def _bad_whole_string_to_normalize(text: str) -> FieldVerdict:
    """Flaw 9 — 整串直喂归一: does not split on `,` (E4 skipped); the whole
    raw token string is treated as the sole element."""
    return _ref_extract(text, element_mode="whole_string")


def _bad_first_element_only(text: str) -> FieldVerdict:
    """Flaw 10 — 只校验首元素: splits correctly but only validates element[0],
    silently accepting a bad second+ element."""
    return _ref_extract(text, element_mode="first_only")


def _bad_sentinel_uses_stripped(text: str) -> FieldVerdict:
    """Flaw 11 — 哨兵判定吃 strip 后元素: judges the sentinel against the
    E4-stripped string rather than the raw E3 token_str (R6/QA M2 pitfall)."""
    return _ref_extract(text, sentinel_strip=True)


def _bad_na_as_sentinel(text: str) -> FieldVerdict:
    """Flaw 12 — `N/A` 当哨兵: widens the closed sentinel set with `n/a`."""
    return _ref_extract(text, extra_sentinels=("n/a",))


_BAD_EXTRACTORS = {
    "loose_predicate": _bad_loose_predicate,
    "no_fence_machine": _bad_no_fence_machine,
    "fence_missing_bq_prefix": _bad_fence_missing_bq_prefix,
    "chinese_only": _bad_chinese_only,
    "no_case_fold": _bad_no_case_fold,
    "unicode_fold": _bad_unicode_fold,
    "loose_plural": _bad_loose_plural,
    "first_code_span_anywhere": _bad_first_code_span_anywhere,
    "whole_string_to_normalize": _bad_whole_string_to_normalize,
    "first_element_only": _bad_first_element_only,
    "sentinel_uses_stripped": _bad_sentinel_uses_stripped,
    "na_as_sentinel": _bad_na_as_sentinel,
    # 13th flaw acts on emit_arg, not on the extractor — handled specially in
    # the matrix test below rather than living in this dict.
}


# ===========================================================================
# TestConstants
# ===========================================================================


class TestConstants(unittest.TestCase):
    def test_exported_constants(self):
        self.assertEqual(FIELD_NAMES, ("Linked Issue", "关联 Issue"))
        self.assertEqual(SENTINELS, ("none", "无"))
        self.assertEqual(VERDICTS, ("NO_FIELD", "NO_TOKEN", "BAD_TOKEN", "OK"))


# ===========================================================================
# SC-1 — E0 location predicates + two-spelling closed set (TASK-001)
# ===========================================================================


class TestSC1Location(unittest.TestCase):
    """baseline 必红 (proposal SC-1): 今天没有任何实现, 顶部 import 即 ImportError."""

    def test_sc1a_alias_spelling_ok(self):
        fv = extract_linked_issue_field(_SC1A_TEXT)
        self.assertEqual(fv.verdict, "OK")
        self.assertEqual(fv.token_str, "10CG/aria-plugin#122")

    def test_sc1b_fenced_example_not_field(self):
        """它怎么会红: 松谓词/无 fence 状态机的实现会把围栏内示例当真字段 ⇒ 红."""
        fv = extract_linked_issue_field(_SC1B_TEXT)
        self.assertEqual(fv.verdict, "NO_FIELD")

    def test_sc1c_indented_double_blockquote_not_field(self):
        """它怎么会红: 松谓词 (不锚行首) 的实现在 `   > > ` 前缀上仍会命中 ⇒ 红.
        真实语料同形: 母 Spec cc1bdef:75 (该行已迁出, 当前树不存在)."""
        fv = extract_linked_issue_field(_SC1C_TEXT)
        self.assertEqual(fv.verdict, "NO_FIELD")

    def test_sc1d_blockquote_nested_fence_not_field(self):
        """它怎么会红: fence 正则漏 `(?:> ?)?` 的实现在此抽出 `other/repo#999` ⇒ 红."""
        fv = extract_linked_issue_field(_SC1D_TEXT)
        self.assertEqual(fv.verdict, "NO_FIELD")

    def test_sc1e_canonical_spelling_ok(self):
        """它怎么会红: 只认中文拼写的实现在此判 NO_FIELD ⇒ 红."""
        fv = extract_linked_issue_field(_SC1E_TEXT)
        self.assertEqual(fv.verdict, "OK")
        self.assertEqual(fv.token_str, "10CG/aria-plugin#122")

    def test_sc1f_plural_spelling_rejected(self):
        """它怎么会红: 放宽单复数的实现在此判 OK ⇒ 红 (集合封闭)."""
        fv = extract_linked_issue_field(_SC1F_TEXT)
        self.assertEqual(fv.verdict, "NO_FIELD")

    def test_sc1g_case_variants_folded(self):
        """它怎么会红: 不折叠大小写的实现在两个大小写变体上都判 NO_FIELD ⇒ 红."""
        fv1 = extract_linked_issue_field(_SC1G1_TEXT)
        fv2 = extract_linked_issue_field(_SC1G2_TEXT)
        self.assertEqual(fv1.verdict, "OK")
        self.assertEqual(fv2.verdict, "OK")
        self.assertEqual(fv1.token_str, "10CG/aria-plugin#122")
        self.assertEqual(fv2.token_str, "10CG/aria-plugin#122")

    def test_sc1h_unicode_homoglyph_rejected(self):
        """A.2 补夹具 (h): KELVIN SIGN (U+212A) 同形字不属 ASCII 折叠范围.
        它怎么会红: 折叠用了 re.IGNORECASE 但漏 re.ASCII 的实现在此判 OK ⇒ 红."""
        fv = extract_linked_issue_field(_SC1H_TEXT)
        self.assertEqual(fv.verdict, "NO_FIELD")

    def test_e0_predicate1_negative_controls(self):
        """E0 谓词 1 的负控逐条 — 全部 NO_FIELD."""
        cases = [
            (">> ", ">> **关联 Issue**: `10CG/a#1`"),
            ("> > (space between)", "> > **关联 Issue**: `10CG/a#1`"),
            ("leading space", " > **关联 Issue**: `10CG/a#1`"),
            ("zero space after >", ">**关联 Issue**: `10CG/a#1`"),
            ("two spaces after >", ">  **关联 Issue**: `10CG/a#1`"),
            ("fullwidth colon", "> **关联 Issue**：`10CG/a#1`"),
            ("single star", "> *关联 Issue*: `10CG/a#1`"),
            ("triple star", "> ***关联 Issue***: `10CG/a#1`"),
        ]
        for label, line in cases:
            with self.subTest(label=label):
                text = f"# Proposal\n\n{line}\n\n## Why\ntest\n"
                fv = extract_linked_issue_field(text)
                self.assertEqual(fv.verdict, "NO_FIELD", f"{label!r} wrongly matched")

    def test_e0_predicate3_first_hit_wins(self):
        """E0 谓词 3: 两条合法字段行 (头部 + 正文讨论处) ⇒ 取第一条."""
        text = (
            "# Proposal\n\n"
            "> **关联 Issue**: `10CG/first#1`\n\n"
            "Some body text discussing this field again:\n\n"
            "> **关联 Issue**: `10CG/second#2`\n"
        )
        fv = extract_linked_issue_field(text)
        self.assertEqual(fv.verdict, "OK")
        self.assertEqual(fv.token_str, "10CG/first#1")
        self.assertEqual(fv.line_no, 3)

    def test_long_header_field_on_line_61_still_found(self):
        """D2 承重实证 (proposal 引 openspec/archive/2026-08-16-premerge-gate-
        branch-existence/proposal.md:61 的形状): 不得用「只扫前 N 行」的实现 —
        字段行放在超长 blockquote 头部的第 61 行仍须 OK.
        它怎么会红: 任何「只扫头部前 N 行」的实现在此判 NO_FIELD ⇒ 红."""
        lines = ["# Proposal"] + [
            f"> continuation blockquote filler line {i}" for i in range(2, 61)
        ]
        lines.append("> **关联 Issue**: `10CG/aria-plugin#137`")
        text = "\n".join(lines) + "\n"
        fv = extract_linked_issue_field(text)
        self.assertEqual(fv.verdict, "OK")
        self.assertEqual(fv.line_no, 61)
        self.assertEqual(fv.token_str, "10CG/aria-plugin#137")


# ===========================================================================
# SC-2 — E2 token start position (TASK-001)
# ===========================================================================


class TestSC2TokenStart(unittest.TestCase):
    def test_sc2_markdown_link_form_is_no_token(self):
        """它怎么会红: 取该行第一个 code span 的实现抽出 `confirmed` ⇒ 红.
        真实语料: openspec/archive/2026-06-11-audit-drift-guard/proposal.md:5
        (逐字复用, 该形状在语料上另有 5 处同类实例)."""
        fv = extract_linked_issue_field(_SC2_TEXT)
        self.assertEqual(fv.verdict, "NO_TOKEN")
        self.assertIsNone(fv.token_str)


# ===========================================================================
# SC-3 — E4/E5/E6 multi-value (TASK-002)
# ===========================================================================


class TestSC3MultiValue(unittest.TestCase):
    def test_sc3a_two_valid_elements_ok_emits_first(self):
        fv = extract_linked_issue_field(_SC3A_TEXT)
        self.assertEqual(fv.verdict, "OK")
        self.assertEqual(fv.token_elements, ("10CG/a#1", "10CG/b#2"))
        self.assertEqual(emit_arg(fv), "10CG/a#1")

    def test_sc3b_second_element_invalid_bad_token(self):
        """它怎么会红: 只校验首元素的实现在此判 OK ⇒ 红."""
        fv = extract_linked_issue_field(_SC3B_TEXT)
        self.assertEqual(fv.verdict, "BAD_TOKEN")
        self.assertIn("[b](url)", fv.bad_elements)
        self.assertEqual(emit_arg(fv), "")

    def test_e3_unclosed_backtick_is_no_token(self):
        text = "# Proposal\n\n> **Linked Issue**: `10CG/a#1\n"
        fv = extract_linked_issue_field(text)
        self.assertEqual(fv.verdict, "NO_TOKEN")
        self.assertIsNone(fv.token_str)

    def test_e3_empty_code_span_is_bad_token(self):
        text = "# Proposal\n\n> **Linked Issue**: ``\n"
        fv = extract_linked_issue_field(text)
        self.assertEqual(fv.verdict, "BAD_TOKEN")
        self.assertEqual(fv.token_str, "")
        self.assertEqual(fv.bad_elements, ("",))


# ===========================================================================
# SC-4 — §2 sentinel set, six branches (TASK-002)
# ===========================================================================


class TestSC4Sentinel(unittest.TestCase):
    def test_sc4a_cjk_sentinel_with_trailing_note_ok_no_emit(self):
        fv = extract_linked_issue_field(_SC4A_TEXT)
        self.assertEqual(fv.verdict, "OK")
        self.assertEqual(fv.token_str, "无")
        self.assertEqual(emit_arg(fv), "")

    def test_sc4b_bare_cjk_sentinel_no_code_span_is_no_token(self):
        """它怎么会红: 接受裸 `无` (无 code span) 的实现在此判 OK ⇒ 红.
        真实语料: openspec/archive/2026-08-23-linked-issue-normalization/
        proposal.md:6 逐字 `> **关联 Issue**: 无`."""
        fv = extract_linked_issue_field(_SC4B_TEXT)
        self.assertEqual(fv.verdict, "NO_TOKEN")
        self.assertIsNone(fv.token_str)

    def test_sc4c_ascii_none_ok(self):
        """它怎么会红: 只认 `无` 的实现在此判 BAD_TOKEN ⇒ 红 (owner 2026-08-30 6i)."""
        fv = extract_linked_issue_field(_SC4C_TEXT)
        self.assertEqual(fv.verdict, "OK")
        self.assertEqual(emit_arg(fv), "")

    def test_sc4d_ascii_none_case_folded_ok(self):
        fv = extract_linked_issue_field(_SC4D_TEXT)
        self.assertEqual(fv.verdict, "OK")
        self.assertEqual(emit_arg(fv), "")

    def test_sc4e_na_is_bad_token(self):
        """它怎么会红: 把 `N/A` 当哨兵的实现在此判 OK ⇒ 红 (集合封闭)."""
        fv = extract_linked_issue_field(_SC4E_TEXT)
        self.assertEqual(fv.verdict, "BAD_TOKEN")

    def test_sc4f_trailing_whitespace_none_is_bad_token(self):
        """它怎么会红: E5 哨兵判定复用 E4 已 strip 元素的实现 (R6/QA M2 亲踩)
        会把 `` `none ` `` 判合法哨兵 ⇒ 红. 断言 E3 不 strip: token_str == 'none '."""
        fv = extract_linked_issue_field(_SC4F_TEXT)
        self.assertEqual(fv.token_str, "none ")
        self.assertEqual(fv.verdict, "BAD_TOKEN")


class TestIsSentinelDirect(unittest.TestCase):
    def test_positive(self):
        for s in ("none", "None", "NONE", "无"):
            with self.subTest(s=s):
                self.assertTrue(is_sentinel(s))

    def test_negative(self):
        for s in ("none ", " 无", "N/A", "", "無"):  # 無 (traditional) != 无
            with self.subTest(s=s):
                self.assertFalse(is_sentinel(s))

    def test_non_ascii_homoglyph_rejected(self):
        # U+217D SMALL ROMAN NUMERAL ONE THOUSAND FIVE HUNDRED, not a real 'n'
        self.assertFalse(is_sentinel("ⅽONE"))
        self.assertFalse(is_sentinel(_KELVIN_SIGN + "ONE"))


# ===========================================================================
# SC-5 — probe check-mode CLI, six arms (TASK-003)
# ===========================================================================


class TestSC5ProbeCheckMode(unittest.TestCase):
    def test_sc5_scope_missing_is_skip(self):
        with tmp_project() as root:
            proc = _run_probe([str(root)])
            self.assertEqual(proc.returncode, 0)
            self.assertTrue(_first_line(proc.stdout).startswith("##SKIP##"))

    def test_sc5_scope_empty_dir_is_skip(self):
        with tmp_project() as root:
            (root / "openspec" / "changes").mkdir(parents=True)
            proc = _run_probe([str(root)])
            self.assertEqual(proc.returncode, 0)
            self.assertTrue(_first_line(proc.stdout).startswith("##SKIP##"))

    def test_sc5_a_unlisted_no_field_is_violation(self):
        """它怎么会红: 判 OK 的正向枚举/catch-all 实现 ⇒ 红 (放行 NO_FIELD)."""
        with tmp_project() as root:
            write_file(
                root / "openspec" / "changes" / "track-a" / "proposal.md",
                "# Track A\n\nNo field here.\n",
            )
            wl = write_file(
                root / ".aria" / "linked-issue-field-grandfathered.txt",
                "# empty allowlist\n",
            )
            proc = _run_probe([str(root), "--grandfathered", str(wl)])
            self.assertEqual(proc.returncode, 1)
            self.assertTrue(_first_line(proc.stdout).startswith("FAIL"))
            self.assertIn("openspec/changes/track-a/proposal.md", proc.stdout)
            self.assertIn("NO_FIELD", proc.stdout)

    def test_sc5_b_all_grandfathered_is_ok(self):
        with tmp_project() as root:
            write_file(root / "openspec" / "changes" / "track-b1" / "proposal.md", "# B1\n\nNo field.\n")
            write_file(root / "openspec" / "changes" / "track-b2" / "proposal.md", "# B2\n\nNo field.\n")
            wl = write_file(
                root / ".aria" / "linked-issue-field-grandfathered.txt",
                "openspec/changes/track-b1\nopenspec/changes/track-b2\n",
            )
            proc = _run_probe([str(root), "--grandfathered", str(wl)])
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(_first_line(proc.stdout), "OK (2 份在范围内, 2 条在册)")

    def test_sc5_c_stale_allowlist_three_letter_forms(self):
        """三子情形同批: (a) 目录不存在且 archive 无同 slug; (b1) 不以
        `openspec/changes/` 起首; (b2) archive/*-<slug> 存在; (c) 仍在作用域且
        已合规. 它怎么会红: 静默忽略陈旧条目的实现 (allowlist 退化为永久豁免) ⇒ 红."""
        with tmp_project() as root:
            write_file(
                root / "openspec" / "changes" / "track-ok" / "proposal.md",
                "# OK\n\n> **Linked Issue**: `10CG/aria-plugin#1`\n",
            )
            write_file(
                root / "openspec" / "archive" / "2026-01-01-track-gone-b" / "proposal.md",
                "# archived\n",
            )
            wl = write_file(
                root / ".aria" / "linked-issue-field-grandfathered.txt",
                "\n".join(
                    [
                        "docs/handoff/foo",
                        "openspec/changes/track-gone-a",
                        "openspec/changes/track-gone-b",
                        "openspec/changes/track-ok",
                    ]
                )
                + "\n",
            )
            proc = _run_probe([str(root), "--grandfathered", str(wl)])
            self.assertEqual(proc.returncode, 1)
            self.assertEqual(_first_line(proc.stdout), "FAIL 4 项")
            self.assertIn("FAIL allowlist 陈旧: docs/handoff/foo (b)", proc.stdout)
            self.assertIn("FAIL allowlist 陈旧: openspec/changes/track-gone-a (a)", proc.stdout)
            self.assertIn("FAIL allowlist 陈旧: openspec/changes/track-gone-b (b)", proc.stdout)
            self.assertIn("FAIL allowlist 陈旧: openspec/changes/track-ok (c)", proc.stdout)

    def test_sc5_d_degraded_missing_collision_module_is_skip(self):
        """真实降级夹具 (proposal 新表面 #1(a)): 把探针 + lib/__init__.py +
        lib/linked_issue_field.py 复制到临时目录, 不含 lib/collision.py.
        它怎么会红: 判 OK 的实现 ⇒ 红 (零证据当正证据)."""
        with tmp_project() as root:
            copy_root = root / "copy"
            (copy_root / "scripts").mkdir(parents=True)
            (copy_root / "lib").mkdir(parents=True)
            shutil.copy2(_PROBE, copy_root / "scripts" / "linked_issue_field_probe.py")
            shutil.copy2(
                Path(_SKILL_ROOT) / "lib" / "__init__.py", copy_root / "lib" / "__init__.py"
            )
            shutil.copy2(
                Path(_SKILL_ROOT) / "lib" / "linked_issue_field.py",
                copy_root / "lib" / "linked_issue_field.py",
            )
            # deliberately NOT copying lib/collision.py
            proc = subprocess.run(
                [
                    sys.executable,
                    str(copy_root / "scripts" / "linked_issue_field_probe.py"),
                    str(root),
                    "--grandfathered",
                    str(root / "does-not-exist.txt"),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0)
            self.assertTrue(_first_line(proc.stdout).startswith("##SKIP##"))

    def test_sc5_e1_missing_allowlist_all_compliant(self):
        with tmp_project() as root:
            write_file(
                root / "openspec" / "changes" / "track-ok" / "proposal.md",
                "# OK\n\n> **Linked Issue**: `10CG/aria-plugin#1`\n",
            )
            missing_wl = root / ".aria" / "linked-issue-field-grandfathered.txt"
            proc = _run_probe([str(root), "--grandfathered", str(missing_wl)])
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(_first_line(proc.stdout), "OK (1 份在范围内, 0 条在册)")
            self.assertEqual(
                proc.stdout.rstrip("\n").splitlines()[-1],
                "(白名单文件缺失, 视为空集)",
            )

    def test_sc5_e2_missing_allowlist_with_violation(self):
        """⚠️ R4/K9 订正措辞: 文件缺失本身不得成为错误, 但作用域内不合规仍须 exit 1."""
        with tmp_project() as root:
            write_file(
                root / "openspec" / "changes" / "track-bad" / "proposal.md",
                "# Bad\n\nNo field.\n",
            )
            missing_wl = root / ".aria" / "linked-issue-field-grandfathered.txt"
            proc = _run_probe([str(root), "--grandfathered", str(missing_wl)])
            self.assertEqual(proc.returncode, 1)
            self.assertTrue(_first_line(proc.stdout).startswith("FAIL"))
            self.assertIn("track-bad", proc.stdout)
            self.assertEqual(
                proc.stdout.rstrip("\n").splitlines()[-1],
                "(白名单文件缺失, 视为空集)",
            )

    def test_sc5_two_fail_types_ordering(self):
        """两类 FAIL 同时出现 ⇒ 违规行 (rel 字典序) 在前, 陈旧行 (e 字典序) 在后."""
        with tmp_project() as root:
            write_file(
                root / "openspec" / "changes" / "track-bad" / "proposal.md",
                "# Bad\n\nNo field.\n",
            )
            wl = write_file(
                root / ".aria" / "linked-issue-field-grandfathered.txt",
                "openspec/changes/track-missing\n",
            )
            proc = _run_probe([str(root), "--grandfathered", str(wl)])
            self.assertEqual(proc.returncode, 1)
            self.assertEqual(_first_line(proc.stdout), "FAIL 2 项")
            lines = proc.stdout.splitlines()
            violation_idx = next(i for i, l in enumerate(lines) if "track-bad" in l)
            stale_idx = next(i for i, l in enumerate(lines) if "陈旧" in l)
            self.assertLess(violation_idx, stale_idx)


# ===========================================================================
# SC-9 — --emit-arg CLI mode (TASK-004)
# ===========================================================================


class TestSC9EmitArg(unittest.TestCase):
    def _run_emit(self, path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_PROBE), "--emit-arg", str(path)],
            capture_output=True,
            text=True,
        )

    def test_sc9a_placeholder_bad_token_emits_empty(self):
        """它怎么会红: 把 BAD_TOKEN 串照传 (K8/NEW-01 复现) 的实现 ⇒ stdout 非空 ⇒ 红."""
        with tmp_project() as root:
            p = write_file(root / "proposal.md", _SC9A_TEXT)
            proc = self._run_emit(p)
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(proc.stdout, "")

    def test_sc9b_sentinel_emits_empty(self):
        """它怎么会红: 对哨兵打印 `none` 的实现 ⇒ stdout 非空 ⇒ 红."""
        with tmp_project() as root:
            p = write_file(root / "proposal.md", _SC9B_TEXT)
            proc = self._run_emit(p)
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(proc.stdout, "")

    def test_sc9c_real_token_emits_first_element_no_trailing_newline(self):
        with tmp_project() as root:
            p = write_file(root / "proposal.md", _SC9C_TEXT)
            proc = self._run_emit(p)
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(proc.stdout, "10CG/a#1")  # 逐字节, 无末尾换行

    def test_sc9d_no_field_emits_empty(self):
        with tmp_project() as root:
            p = write_file(root / "proposal.md", _SC9D_TEXT)
            proc = self._run_emit(p)
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(proc.stdout, "")

    def test_sc9_missing_file_exit2_empty_stdout(self):
        with tmp_project() as root:
            missing = root / "does-not-exist.md"
            proc = self._run_emit(missing)
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(proc.stdout, "")
            self.assertTrue(proc.stderr.strip())

    def test_sc9_mutually_exclusive_with_grandfathered(self):
        with tmp_project() as root:
            p = write_file(root / "proposal.md", _SC9B_TEXT)
            wl = write_file(root / "wl.txt", "")
            proc = subprocess.run(
                [
                    sys.executable,
                    str(_PROBE),
                    "--emit-arg",
                    str(p),
                    "--grandfathered",
                    str(wl),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 2)


# ===========================================================================
# SC-6 — SOT template self-compliance (TASK-005)
# ===========================================================================


class TestSC6Template(unittest.TestCase):
    def test_sc6_template_field_and_usage_note_and_reference(self):
        """它怎么会红: 模板加字段但写裸文本/markdown 链接 ⇒ (i) 红; 用中文 alias
        写字段行 ⇒ (ii) 红; 漏 Usage Note ⇒ (iii) 红; spec-drafter 引用路径漂移
        ⇒ (iv) 红. baseline 必红: 该模板今天 grep 'Linked Issue' = 0 (实读 @ 334c609)."""
        if not _TEMPLATE_PATH.is_file():
            self.skipTest(f"跨仓已知限: {_TEMPLATE_PATH} 不存在 (plugin 单独分发)")
        text = _TEMPLATE_PATH.read_text(encoding="utf-8")
        lines = text.split("\n")

        field_re = re.compile(
            r"^> \*\*(?:" + "|".join(re.escape(n) for n in FIELD_NAMES) + r")\*\*:",
            re.IGNORECASE | re.ASCII,
        )
        hits = [i for i, l in enumerate(lines) if field_re.match(l)]
        self.assertEqual(len(hits), 1, f"expected exactly 1 E0 hit, got {hits}")

        # (ii) canonical spelling, not alias — 写入侧只教一种
        self.assertTrue(
            lines[hits[0]].startswith("> **Linked Issue**:"),
            f"field line uses non-canonical spelling: {lines[hits[0]]!r}",
        )

        # (i) library agrees: placeholder ⇒ BAD_TOKEN (D8: 不断言 E5)
        fv = extract_linked_issue_field(text)
        self.assertEqual(fv.verdict, "BAD_TOKEN")
        self.assertEqual(fv.line_no, hits[0] + 1)

        # (iii) Template Usage Notes carries the `none` literal + both phrases
        notes_idx = text.find("## Template Usage Notes")
        self.assertNotEqual(notes_idx, -1, "模板缺 ## Template Usage Notes 段")
        notes_section = text[notes_idx:]
        self.assertIn("`none`", notes_section)
        self.assertIn("不留空", notes_section)
        self.assertIn("不删行", notes_section)

        # (iv) spec-drafter/SKILL.md's relative reference resolves to this file
        skill_text = _SPEC_DRAFTER_SKILL.read_text(encoding="utf-8")
        m = re.search(r"\(([^)]*proposal-minimal\.md)\)", skill_text)
        self.assertIsNotNone(
            m, "spec-drafter/SKILL.md 未找到 proposal-minimal.md 相对路径引用"
        )
        resolved = (_SPEC_DRAFTER_SKILL.parent / m.group(1)).resolve()
        self.assertTrue(resolved.is_file(), f"引用路径未解析到存在文件: {resolved}")
        self.assertEqual(resolved, _TEMPLATE_PATH.resolve())


# ===========================================================================
# SC-7a — spec-drafter preview fence header alignment (TASK-005)
# ===========================================================================


class TestSC7aPreviewFence(unittest.TestCase):
    def test_sc7a_preview_fence_header_aligned_with_sot_and_negative_control(self):
        """它怎么会红: 只在正文声明必填不改预览骨架 ⇒ 围栏内 0 命中 ⇒ (i) 红; 字段行
        写在围栏外 (块边界排除) ⇒ 红; 骨架默认写 `none` (把正证据做成默认值) ⇒
        (ii) 负控红. baseline (i) 必红: 该文件今天 grep 'Linked Issue' = 0,
        预览骨架头部只有两行 (:139-140 @ d69091d)."""
        text = _SPEC_DRAFTER_SKILL.read_text(encoding="utf-8")
        heading = "### Level 2 预览"
        h_idx = text.find(heading)
        self.assertNotEqual(h_idx, -1, "SKILL.md 缺 ### Level 2 预览 标题")
        after_heading = text[h_idx + len(heading) :]
        fence_start = after_heading.find("```")
        self.assertNotEqual(fence_start, -1, "标题后未找到 ``` 围栏起始")
        body_start = fence_start + 3
        fence_end = after_heading.find("```", body_start)
        self.assertNotEqual(fence_end, -1, "未找到 ``` 围栏收尾")
        fence_inner = after_heading[body_start:fence_end]

        # (i) 围栏内含逐字两行, 四行相对顺序与 SOT 一致
        self.assertIn("> **Created**:", fence_inner)
        self.assertIn("> **Linked Issue**:", fence_inner)
        order_markers = ["> **Level**", "> **Status**", "> **Created**", "> **Linked Issue**"]
        positions = [fence_inner.find(m) for m in order_markers]
        for marker, pos in zip(order_markers, positions):
            self.assertNotEqual(pos, -1, f"missing {marker!r} inside preview fence")
        self.assertEqual(positions, sorted(positions), "四行顺序与 SOT 不一致")

        # (ii) 负控: 该行值不是哨兵, 是 SOT 同串 placeholder — 围栏内文本单独喂给
        # extract_linked_issue_field (不含围栏 marker 本身, 故不会被 E0 谓词 2 误判
        # 成"仍在围栏内"从而 0 命中)
        fv = extract_linked_issue_field(fence_inner)
        self.assertEqual(fv.verdict, "BAD_TOKEN")
        self.assertFalse(is_sentinel(fv.token_str))
        self.assertEqual(fv.token_str, "{<org>/<repo>#<n>}")

    def test_sc7a_field_outside_fence_not_counted(self):
        """块边界: 围栏外出现同形行不计入 (仅围栏内求值)."""
        fabricated = (
            "### Level 2 预览\n\n"
            "> **Linked Issue**: `should-not-count/x#1`\n\n"
            "```\nno real field in here\n```\n"
        )
        h_idx = fabricated.find("### Level 2 预览")
        after_heading = fabricated[h_idx + len("### Level 2 预览") :]
        fence_start = after_heading.find("```")
        body_start = fence_start + 3
        fence_end = after_heading.find("```", body_start)
        fence_inner = after_heading[body_start:fence_end]
        fv = extract_linked_issue_field(fence_inner)
        self.assertEqual(fv.verdict, "NO_FIELD")


# ===========================================================================
# SC-8 — check registration + real run (TASK-005)
# ===========================================================================


class TestSC8Registration(unittest.TestCase):
    def test_sc8_registered_and_runnable(self):
        """它怎么会红: 只建脚本不注册 ⇒ (a) 红; 探针放回 `.aria/probes/` ⇒ (b) 红
        (直接钉住 D3 的宿主改判); 探针崩溃 (traceback → stdout 空) ⇒ (c) 红.
        baseline 必红: 三者今天都不存在."""
        if not _STATE_CHECKS_PATH.is_file():
            self.skipTest(f"跨仓已知限: {_STATE_CHECKS_PATH} 不存在 (plugin 单独分发)")
        text = _STATE_CHECKS_PATH.read_text(encoding="utf-8")
        parsed = _parse_state_checks_yaml(text)
        entries = [
            c for c in parsed["checks"] if c.get("name") == "linked-issue-field-availability"
        ]
        self.assertEqual(
            len(entries), 1, "state-checks.yaml 未含 linked-issue-field-availability 条目 (或重复)"
        )
        entry = entries[0]
        command = entry.get("command", "")
        py_tokens = [tok for tok in command.split() if tok.endswith(".py")]
        self.assertEqual(len(py_tokens), 1, f"command 中 .py 路径数量异常: {py_tokens!r}")
        script_rel = py_tokens[0]
        script_path = _MAIN_REPO_ROOT / script_rel
        self.assertTrue(script_path.is_file(), f"command 指向的脚本不存在: {script_path}")

        # (b) 随 plugin 分发, 不是 .aria/
        self.assertTrue(script_rel.startswith("aria/skills/"), script_rel)

        # (c) 实跑: exit ∈ {0,1}, 首个非空 stdout 行前缀 ∈ {OK, FAIL, ##SKIP##}
        # (不断言 exit 值本身 — 断言值会把测试绑死在当日语料上)
        proc = subprocess.run(
            command, shell=True, cwd=str(_MAIN_REPO_ROOT), capture_output=True, text=True
        )
        self.assertIn(proc.returncode, (0, 1), f"stderr={proc.stderr!r}")
        nonblank = next((l for l in proc.stdout.splitlines() if l.strip()), "")
        self.assertTrue(
            nonblank.startswith("OK")
            or nonblank.startswith("FAIL")
            or nonblank.startswith("##SKIP##"),
            f"unexpected first non-blank stdout line: {nonblank!r}",
        )


# ===========================================================================
# TASK-006 — bad-implementation matrix
# ===========================================================================


class TestBadImplementationMatrix(unittest.TestCase):
    """夹具 × 坏实现 ⇒ 哪格红 (proposal 各 SC「它怎么会红」列的机械化版本).

    | 夹具  | 判它红的 _bad_*                                    |
    |-------|-----------------------------------------------------|
    | SC1a  | (无 — 正证据 regression fixture, 见 _MATRIX_EXEMPT)  |
    | SC1b  | loose_predicate, no_fence_machine                    |
    | SC1c  | loose_predicate                                      |
    | SC1d  | loose_predicate, no_fence_machine, fence_missing_bq  |
    | SC1e  | chinese_only                                         |
    | SC1f  | loose_plural                                         |
    | SC1g1 | no_case_fold                                         |
    | SC1g2 | no_case_fold                                         |
    | SC1h  | unicode_fold                                         |
    | SC2   | first_code_span_anywhere                             |
    | SC3a  | chinese_only, whole_string_to_normalize              |
    | SC3b  | chinese_only, first_element_only                     |
    | SC4a  | chinese_only                                         |
    | SC4b  | (无 — 正证据 regression fixture, 见 _MATRIX_EXEMPT)  |
    | SC4c  | chinese_only                                         |
    | SC4d  | chinese_only                                         |
    | SC4e  | chinese_only, na_as_sentinel                         |
    | SC4f  | chinese_only, sentinel_uses_stripped                 |
    | SC9a  | chinese_only, bad_token_passthrough_emit (13th flaw) |
    | SC9b  | chinese_only                                         |
    | SC9c  | chinese_only, whole_string_to_normalize              |
    | SC9d  | (无 — 正证据 regression fixture, 见 _MATRIX_EXEMPT)  |

    SC1a/SC4b/SC9d 是「干净的正例/绝对缺席」情形, 13 个具名 flaw 里没有一个
    对它们有可乘之机 (没有 confound 可利用) —— 它们只承担「好实现必须答对」
    的回归职责, 不承担「区分力」职责; 已在 `_MATRIX_EXEMPT` 显式列出, 不是
    静默漏判。SC-1(a)/(c)/(e) 的字段名拼写由 proposal SC-1 表逐字钉死
    (a)/(c) = alias, (e) = canonical, 不可更改；SC-3/SC-4(a,c-f)/SC-9 拼写
    不受表格约束, 一律选用 canonical `Linked Issue` —— 这个选择顺带让
    `chinese_only` 成为它们共同的判别项之一, 与「写入侧只教 canonical」的
    §2 精神一致。
    """

    def test_good_implementation_matches_expected_for_every_fixture(self):
        for label, (text, expected) in _FIXTURES.items():
            with self.subTest(label=label):
                fv = extract_linked_issue_field(text)
                got = (fv.verdict, fv.token_str, emit_arg(fv))
                self.assertEqual(got, expected, f"{label}: got {got}, want {expected}")

    def test_each_adversarial_fixture_has_a_discriminating_bad_impl(self):
        for label, (text, expected) in _FIXTURES.items():
            if label in _MATRIX_EXEMPT:
                continue
            with self.subTest(label=label):
                discriminated = False
                culprits = []
                for name, fn in _BAD_EXTRACTORS.items():
                    fv = fn(text)
                    got = (fv.verdict, fv.token_str, emit_arg(fv))
                    if got != expected:
                        discriminated = True
                        culprits.append(name)
                # 13th flaw: correct extraction, bad emit_arg
                good_fv = extract_linked_issue_field(text)
                bad_emit_got = (good_fv.verdict, good_fv.token_str, _bad_emit_passthrough(good_fv))
                if bad_emit_got != expected:
                    discriminated = True
                    culprits.append("bad_token_passthrough_emit")
                self.assertTrue(
                    discriminated,
                    f"{label}: no _bad_* impl differs from expected {expected} — "
                    "fixture has no discriminative power",
                )

    def test_at_least_twelve_bad_extractors_defined(self):
        # 12 in the flaw-parameterized dict + the 13th (emit-level) flaw.
        self.assertGreaterEqual(len(_BAD_EXTRACTORS) + 1, 12)
        self.assertEqual(len(_BAD_EXTRACTORS) + 1, 13)


if __name__ == "__main__":
    unittest.main()

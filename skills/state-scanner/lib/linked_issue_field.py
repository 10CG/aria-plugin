"""Linked Issue field extraction — E0–E6 (OpenSpec `linked-issue-field-availability`).

Pure-function host for the field-location + token-extraction rules defined in
``openspec/changes/linked-issue-field-availability/proposal.md`` §3 (E0–E6) and
the sentinel set defined in that proposal's §2. **The rule set is defined in
this module and nowhere else** — consumers across the repo (the check-mode CLI
in ``scripts/linked_issue_field_probe.py``, and any cross-skill probe such as
``sibling-spec-probe``) import ``extract_linked_issue_field`` / ``is_sentinel``
/ ``emit_arg`` from here rather than re-implementing any part of E0–E6.

Rule summary (see the proposal for the full rationale and adversarial corpus):

  E0 — locate the field's hosting line: three predicates, all must hold.
       (1) line-anchored `> **Linked Issue**:` / `> **关联 Issue**:` (ASCII
           case-folded on the ASCII spelling only; two-spelling closed set,
           no plural widening); (2) fenced-code-block exclusion (a state
           machine flips on ```/~~~ fence lines, optionally nested inside a
           blockquote, and those lines never count as a hit themselves);
           (3) first matching line in document order wins.
  E1 — the line's content after the field prefix, unstripped.
  E2 — the first non-blank character after the colon must be a backtick;
       otherwise the field is present but has no usable token (``NO_TOKEN``).
  E3 — the token string is everything between that backtick and the next
       one, verbatim (unstripped); an unclosed backtick is ``NO_TOKEN``.
  E4 — the token string splits on ASCII `,` into token elements, each
       individually ``str.strip()``-ed.
  E5 — legality: the *raw* E3 token string (not an E4-stripped element) is
       judged against the sentinel set first; failing that, every element
       must round-trip through ``normalize_linked_issue`` (imported from
       ``lib.collision``) to a non-``None`` key, or the field is
       ``BAD_TOKEN`` (with the offending elements named).
  E6 — the value a caller should feed as a `--linked-issue` CLI argument:
       the first token element, verbatim, and *only* when the verdict is
       ``OK`` and the token is not a sentinel — every other outcome
       (sentinel, ``BAD_TOKEN``, ``NO_TOKEN``, ``NO_FIELD``) must omit the
       argument entirely (a sentinel string is truthy and a raw ``BAD_TOKEN``
       string must never reach a comparison surface).

§2 sentinel set (closed, read-side ASCII-case-folded): canonical ``none``
(any ASCII casing) and alias ``无`` (a single U+65E0 byte-for-byte). Nothing
else counts — not ``N/A``, not a value with surrounding whitespace, not a
non-ASCII homoglyph. Write-side tooling should only ever emit ``none``.

This module carries no path- or scope-selection policy (which files to scan,
whether to honor an allowlist, etc.) — that is the CLI's job.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .collision import normalize_linked_issue

FIELD_NAMES = ("Linked Issue", "关联 Issue")
SENTINELS = ("none", "无")
VERDICTS = ("NO_FIELD", "NO_TOKEN", "BAD_TOKEN", "OK")

# E0 predicate 1: line-anchored field header. ASCII case-folding only (a
# non-ASCII homoglyph in the "Linked Issue" spelling must NOT match).
_FIELD_RE = re.compile(
    r"^> \*\*(?:Linked Issue|关联 Issue)\*\*:", re.IGNORECASE | re.ASCII
)

# E0 predicate 2: fenced-code-block boundary (optionally nested one level
# inside a blockquote prefix). Toggles an in-fence boolean; the fence line
# itself never participates in predicate 1.
_FENCE_RE = re.compile(r"^[ ]{0,3}(?:> ?)?(?:```|~~~)")


@dataclass(frozen=True)
class FieldVerdict:
    verdict: str
    token_str: Optional[str]
    token_elements: tuple[str, ...]
    line_no: Optional[int]
    bad_elements: tuple[str, ...] = ()


def is_sentinel(token_str) -> bool:
    """§2 sentinel test, judged against a raw (unstripped) string.

    True iff `token_str` is exactly the alias `无` (single U+65E0), or is
    ASCII and ASCII-lower-cased equals `none`. Closed set — everything else
    (including `N/A`, trailing/leading whitespace, non-ASCII homoglyphs)
    returns False.
    """
    return isinstance(token_str, str) and (
        token_str == "无" or (token_str.isascii() and token_str.lower() == "none")
    )


def emit_arg(fv: FieldVerdict) -> str:
    """E6: the `--linked-issue` argument value for `fv`.

    Only the (OK, non-sentinel) cell produces a real value (the first token
    element, verbatim); every other of the four verdicts, and the sentinel
    sub-case of OK, must yield the empty string so a caller can omit the
    flag entirely rather than feed a sentinel or an unparseable string into
    a comparison surface.
    """
    if fv.verdict == "OK" and not is_sentinel(fv.token_str):
        return fv.token_elements[0]
    return ""


def extract_linked_issue_field(text: str) -> FieldVerdict:
    """Run E0–E6 over a full proposal document's text and return its verdict.

    `text` is a text blob (not a path) so that non-filesystem callers (e.g. a
    probe reading a `git cat-file` blob from a remote ref) can reuse this
    function unchanged.
    """
    lines = text.split("\n")
    in_fence = False
    hit_line_no: Optional[int] = None
    hit_line: Optional[str] = None
    for i, raw_line in enumerate(lines):
        line = raw_line.rstrip("\r")
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if _FIELD_RE.match(line):
            hit_line_no = i + 1
            hit_line = line
            break

    if hit_line_no is None or hit_line is None:
        return FieldVerdict("NO_FIELD", None, (), None)

    m = _FIELD_RE.match(hit_line)
    assert m is not None  # hit_line was only set when _FIELD_RE matched it
    rest = hit_line[m.end():]  # E1 — unstripped remainder of the line

    rest2 = rest.lstrip(" \t")  # E2 — skip leading spaces/tabs only
    if rest2 == "" or rest2[0] != "`":
        return FieldVerdict("NO_TOKEN", None, (), hit_line_no)

    end = rest2.find("`", 1)
    if end == -1:
        return FieldVerdict("NO_TOKEN", None, (), hit_line_no)  # unclosed
    token_str = rest2[1:end]  # E3 — verbatim, unstripped

    token_elements = tuple(e.strip() for e in token_str.split(","))  # E4

    if is_sentinel(token_str):  # E5 — judged against the raw E3 string
        return FieldVerdict("OK", token_str, token_elements, hit_line_no)

    bad = tuple(e for e in token_elements if normalize_linked_issue(e) is None)
    if bad:
        return FieldVerdict(
            "BAD_TOKEN", token_str, token_elements, hit_line_no, bad
        )
    return FieldVerdict("OK", token_str, token_elements, hit_line_no)

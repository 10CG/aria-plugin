"""Phase 1.7 — Architecture status collector.

Regex hardening (Spec `state-scanner-collector-regex-hardening`, 2026-04-25):
- 3 field-extractor patterns widened to accept BOTH halfwidth `:` (U+003A)
  and fullwidth `：` (U+FF1A) via `[：:]` character class — fullwidth is the
  default produced by Chinese IMEs in markdown documents.
- Optional heading prefix `(?:#{1,6}\\s+)?` allows `## Status: Active` form
  alongside the existing `**Status**: Active` and `> **Status**: Active`.
- Pattern is `^(?:#{1,6}\\s+)?\\s*>?\\s*\\*\\*<KEY>\\*\\*[：:]\\s*<VAL>` —
  the union of: optional heading + optional blockquote + bold key + dual colon.

Qualified `Parent PRD` variant (issue #151, 2026-08-23):
- `_ARCH_PRD` gained an optional qualifier slot between the `Parent PRD`
  literal and the colon, so `**Parent PRD (v1)**:` / `**Parent PRD (v2)**:`
  (a real-world form when one architecture doc hangs off multiple PRDs,
  e.g. this repo's own `docs/architecture/system-architecture.md`) are no
  longer chain_valid false negatives.
- Because a qualifier enables *multiple* `Parent PRD` lines in one doc, all
  hits are now collected via `finditer` into an additive `parent_prds:
  list[str]` field. The existing single-value `parent_prd` stays = the
  first hit (doc order) for back-compat.
- `chain_valid` semantics widen from "the one parent_prd is real" to "at
  least one parsed entry resolves": markdown-link-form entries
  (`[text](target)`) resolve `target` relative to the architecture file's
  own directory and require the file to exist on disk; bare-text entries
  keep the pre-#151, no-disk-check `_is_real_prd_reference` semantics
  (frozen by `test_valid_architecture`, which asserts chain_valid=True for
  a bare reference that does not exist on disk in its tmp fixture).

Round-2 fixes (issue #151, rebuttal-seat majors/minors, 2026-08-23):
- Qualifier slot now matches on **either side** of the closing `**`:
  `**Parent PRD (v1)**:` (qualifier before `**`) AND
  `**Parent PRD** (v1):` (qualifier after `**`) both match — the round-1
  regex only had the first slot. Round 3 reverted the round-2 "one level of nesting" grammar
  (catastrophic backtracking on an unclosed paren) — the qualifier is LINEAR.
- `_MD_LINK_FULL` (round-1, `^\\[[^\\]]*\\]\\(([^)]+)\\)$`, a *whole-string*
  match) is replaced by `_MD_LINK_PREFIX` — a **prefix** match (`.match()`,
  no trailing `$`) using CommonMark-shaped link-destination/title grammar:
  `^\\[([^\\]]*)\\]\\(([^)\\s]+)(?:\\s+"[^"]*")?\\)`. Round-1's whole-string
  requirement meant ANY trailing decoration after the `)` — a stray
  comment, a CommonMark title the round-1 grammar didn't special-case, a
  trailing annotation like `(primary)` — made the whole entry fail the
  link check and fall back to the bare-text path, which has **no disk
  check** at all: a broken link with trailing decoration silently reported
  chain_valid=True (fail-open). The prefix match + explicit optional-title
  grammar fixes this: link entries are recognized (and disk-checked)
  regardless of what (if anything) trails the `)`, and a `"title"` is
  correctly excluded from the extracted target path.
- `parent_prds` entries store the **target only** for link-form input, not
  the raw `[text](target)` text — this is a value-shape change from
  pre-#151 for markdown-link-form `Parent PRD` lines (see schema doc
  "Round-2" note for the back-compat framing correction).
"""

from __future__ import annotations

import re
from pathlib import Path

from ._common import CollectorResult

_ARCH_STATUS_PAT = re.compile(
    r"^(?:#{1,6}\s+)?\s*>?\s*(?:\*\*)?Status(?:\*\*)?[：:]\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_ARCH_LAST_UPD = re.compile(
    r"^(?:#{1,6}\s+)?\s*>?\s*(?:\*\*)?Last Updated(?:\*\*)?[：:]\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
# Parenthesized qualifier, e.g. `(v1)` / `(v2)` / `(draft v1)`. Deliberately
# LINEAR (`[^()]*`): the round-2 one-level-nesting form `\((?:[^()]*|\([^()]*\))*\)`
# is the classic `(a*)*` catastrophic-backtracking shape — a line starting with
# `Parent PRD (` whose paren never closes (a typo) made `finditer` go
# exponential. Nesting is not a real-world need; a qualifier is one token.
_PAREN_QUAL = r"\([^()]*\)"

_ARCH_PRD = re.compile(
    r"^(?:#{1,6}\s+)?\s*>?\s*(?:\*\*)?Parent PRD"
    rf"(?:\s*{_PAREN_QUAL})?"
    r"(?:\*\*)?"
    rf"(?:\s*{_PAREN_QUAL})?"
    r"[：:]\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# #151 round 2: matches a captured Parent PRD value that STARTS WITH a
# markdown link (`[text](target [ "title" ])`) — a PREFIX match (`.match()`,
# no trailing `$`), not a whole-string match, so trailing decoration after
# the `)` (a stray comment, a `(primary)` annotation, ...) does not knock
# the entry back onto the no-disk-check bare-text path (round-1's
# `_MD_LINK_FULL` did exactly that — fail-open on a broken link with any
# trailing text). An optional CommonMark link title is recognized and
# excluded from the extracted target (group 2).
# Grammar (round 3): destination may be wrapped in CommonMark angle brackets
# `<dest>`; an optional title may be `"..."`, `'...'` or `(...)`; whitespace is
# tolerated inside the parens. `#fragment` / `?query` are stripped from the
# destination before the disk check (`_link_target_path`), and a destination
# with a URL scheme (`https://...`) is not disk-checkable — it keeps the
# pre-#151 bare-text semantics (non-empty + non-placeholder ⇒ counts).
_MD_LINK_PREFIX = re.compile(
    r"^\[([^\]]*)\]\(\s*<?([^\s)>]+)>?"
    r"(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*\)"
)
_URL_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")


def _link_target_path(target: str) -> str:
    """Strip `#fragment` / `?query` — they are not part of the file path."""
    return target.split("#", 1)[0].split("?", 1)[0]

_PRD_PLACEHOLDER_MARKERS = {
    "tbd", "pending", "(pending)", "(tbd)", "n/a", "todo", "(todo)", "placeholder",
    "待填写", "待定", "未定",
}


def _is_real_prd_reference(parent_prd: str | None) -> bool:
    """Reject placeholder strings as chain_valid=True (audit IMP-2).

    A real PRD reference must be non-empty and not a known placeholder token.
    File-existence verification is deferred (filename vs markdown link variance).
    """
    if not parent_prd:
        return False
    low = parent_prd.strip().lower()
    if low in _PRD_PLACEHOLDER_MARKERS:
        return False
    return True


def _parse_prd_entry(raw: str) -> tuple[str, bool]:
    """Split one matched `Parent PRD` capture into (stored_value, is_link).

    A markdown-link-form entry (`[text](target)`, optionally followed by a
    `"title"` and/or arbitrary trailing decoration — link recognition is a
    PREFIX match, see `_MD_LINK_PREFIX`) stores its link `target` (not the
    raw `[text](target)` text, and not any trailing title/decoration) and
    is flagged `is_link=True` so `_prd_entry_resolves` does a disk
    existence check. Anything that doesn't start with `[text](target)` (a
    bare filename/path) is stored verbatim, `is_link=False`, and keeps the
    pre-#151 semantics.
    """
    m = _MD_LINK_PREFIX.match(raw)
    if m:
        return m.group(2).strip(), True
    return raw, False


def _prd_entry_resolves(stored_value: str, is_link: bool, arch_file: Path) -> bool:
    """Per-entry `chain_valid` predicate (issue #151).

    - link entry: `stored_value` (the link target) must resolve to a real
      file on disk, relative to the architecture doc's own directory (the
      natural base for a relative markdown link such as
      `../requirements/prd-x.md`).
    - bare-text entry: falls back to `_is_real_prd_reference` — non-empty,
      not a known placeholder token, no disk check (frozen behaviour;
      `test_valid_architecture` asserts chain_valid=True for a bare
      reference absent from disk in its tmp fixture).
    """
    if is_link:
        if _URL_SCHEME.match(stored_value):
            # Remote PRD (wiki/URL): cannot be disk-checked; bare-text semantics.
            return _is_real_prd_reference(stored_value)
        rel = _link_target_path(stored_value)
        if not rel:
            return False
        try:
            target_path = (arch_file.parent / rel).resolve()
        except (OSError, ValueError):
            return False
        return target_path.is_file()
    return _is_real_prd_reference(stored_value)


def collect_architecture(project_root: Path) -> CollectorResult:
    r = CollectorResult()
    arch_file = project_root / "docs" / "architecture" / "system-architecture.md"
    if not arch_file.is_file():
        r.data = {
            "exists": False,
            "path": None,
            "status": None,
            "last_updated": None,
            "parent_prd": None,
            "parent_prds": None,
            "chain_valid": None,
        }
        return r

    try:
        text = arch_file.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        r.soft_error("arch_read_failed", str(e))
        r.data = {
            "exists": True,
            "path": str(arch_file.relative_to(project_root)),
            "status": None,
            "last_updated": None,
            "parent_prd": None,
            "parent_prds": None,
            "chain_valid": None,
        }
        return r

    def _first(p: re.Pattern[str]) -> str | None:
        m = p.search(text)
        return m.group(1).strip() if m else None

    status = _first(_ARCH_STATUS_PAT)
    last_upd = _first(_ARCH_LAST_UPD)

    # #151: collect ALL `Parent PRD` hits (qualified variants like
    # `(v1)`/`(v2)` make multiple hits a legitimate real-world shape), not
    # just the first. chain_valid = at least one collected entry resolves.
    parent_prds: list[str] = []
    chain_valid = False
    for m in _ARCH_PRD.finditer(text):
        raw = m.group(1).strip()
        stored_value, is_link = _parse_prd_entry(raw)
        parent_prds.append(stored_value)
        if _prd_entry_resolves(stored_value, is_link, arch_file):
            chain_valid = True

    parent_prd = parent_prds[0] if parent_prds else None

    r.data = {
        "exists": True,
        "path": str(arch_file.relative_to(project_root)),
        "status": status,
        "last_updated": last_upd,
        "parent_prd": parent_prd,
        "parent_prds": parent_prds,
        "chain_valid": chain_valid,
    }
    return r

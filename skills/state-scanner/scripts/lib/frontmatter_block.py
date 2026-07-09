"""Frontmatter block extraction — single regex SOT, plus a restricted
YAML-subset parser for the ``runtime_probe:`` declaration.

``_FRONTMATTER_RE`` / ``_frontmatter_block`` physically moved here from
``collectors/openspec.py`` (runtime-probe-archive-gate-integration, TASK-004,
#95 follow-up A) — same discipline as the ``lib/carry_forward.py`` move
(#134 A1.1b, archive-completeness-gate): a single leaf-module SOT lets
``lib/spec_complete.py`` (TASK-005) reuse the exact same frontmatter-block
regex without creating a ``spec_complete`` <-> ``collectors.openspec``
circular import (``collectors/openspec.py`` already imports
``lib.spec_complete`` at module load — see that file's header note).
``collectors/openspec.py`` re-imports both names from here unchanged, so the
pattern (and its behavior) stays single-sourced, not duplicated.

This module is a **leaf**: it imports nothing from ``collectors/`` or any
other ``lib/*`` module — stdlib (``re``) only. That is what keeps the
dependency graph acyclic:

    collectors.openspec  -> lib.frontmatter_block  -> (nothing)
    collectors.openspec  -> lib.spec_complete       -> lib.frontmatter_block -> (nothing)

If ``lib.spec_complete`` ever imported ``collectors.openspec`` instead of
this module directly, that would close the cycle — hence the hard rule:
``spec_complete.py`` must import ``frontmatter_block`` directly, never via
``collectors.openspec``.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Moved verbatim from collectors/openspec.py. Semantics unchanged: match a
# YAML frontmatter block anchored at the file's ABSOLUTE start (`^---`) so a
# `---` appearing later in the prose body (e.g. inside a fenced code block or
# a markdown horizontal rule) is never mistaken for a frontmatter delimiter.
# \r?\n: CRLF checkout (Windows core.autocrlf) 下标记不可静默丢失 (#132 同类教训)。
# ---------------------------------------------------------------------------
_FRONTMATTER_RE = re.compile(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t\r]*(?:\n|$)", re.DOTALL)


def _frontmatter_block(text: str) -> str | None:
    """Return the YAML frontmatter body (delimiters excluded), or None."""
    m = _FRONTMATTER_RE.match(text)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# runtime_probe declaration — restricted YAML subset (stdlib-only, no
# PyYAML — proposal.md §What Changes 1 "解析约束"). Recognized shape:
#
#   runtime_probe:
#     partition: <scalar>       # optional trailing comment, anywhere
#     symbol: <scalar>
#     max_age_days: <scalar>
#     enabled_when: <scalar>
#
# - Fixed 2-space indent, scalar-only sub-keys.
# - Trailing comments: the first literal ' #' (space immediately followed by
#   '#') found in a value onward is dropped to end of line — bare-scalar
#   semantics, no quote/escape lexing.
# - Unknown extra scalar sub-keys (same 2-space, `key: value` shape) are
#   tolerated and passed through in `fields` — the value layer (TASK-001,
#   lib/runtime_probe.py) ignores what it doesn't recognize. This is a
#   deliberate choice, NOT a 5th textual rejection form.
# - Anything else — deeper nesting, flow-style `{}`, YAML anchors/aliases
#   (`&`/`*`), multi-line block-scalar values (`|`/`>`), tab-indented lines
#   (a bare `lstrip(" ")` cannot see tabs, so a tab-led line's indent would
#   otherwise miscompute to 0 and be silently misread as a dedent — see the
#   `line != line.lstrip()` guard below), or any other shape outside this
#   restricted grammar — is "声明无效" (invalid): fail toward warn, never
#   guess at intent.
#
# Type conversion / requiredness / value-range validation (e.g. "symbol is
# required", "max_age_days must be a positive int") is explicitly OUT of
# scope for this module — that is the value layer's job (TASK-001). This
# module only answers "is the TEXT shape parseable, and if so what are the
# raw strings".
# ---------------------------------------------------------------------------

_TOP_KEY_RE = re.compile(r"^runtime_probe:(.*)$")
_SUB_KEY_RE = re.compile(r"^  ([A-Za-z_][A-Za-z0-9_]*):(.*)$")
# YAML block-scalar header: `|` (literal) or `>` (folded), optionally
# followed by a chomping indicator (`+`/`-`) and/or an explicit indentation
# digit, in either order enough to catch the common forms (`|`, `|-`, `|2`,
# `>+3`, ...). Detection-only — we reject on sight, never parse the block.
_BLOCK_SCALAR_RE = re.compile(r"^[|>][+\-]?\d*$")


def _strip_inline_comment(value: str) -> str:
    """Drop everything from the first literal ' #' (space+hash) onward.

    Bare-scalar semantics (proposal §What 1): no quote/escape handling, and a
    '#' not preceded by a space is left as literal text (rare/unspecified
    edge case — this is a restricted subset, not a full YAML comment lexer).
    """
    idx = value.find(" #")
    return value if idx == -1 else value[:idx]


def _rejected_scalar_reason(value: str) -> str | None:
    """Classify an already comment-stripped, trimmed scalar value.

    Returns a rejection reason slug for flow-style / anchor-or-alias /
    multiline-block-scalar values, or None if `value` is an acceptable bare
    scalar (including the empty string — an empty value is a text-layer-legal
    "no content", requiredness is the value layer's concern).
    """
    if value.startswith("{"):
        return "flow_style_mapping"
    if value.startswith(("&", "*")):
        return "anchor_or_alias"
    if _BLOCK_SCALAR_RE.match(value):
        return "multiline_value"
    return None


def extract_runtime_probe(fm_block: str | None) -> dict:
    """Parse the ``runtime_probe:`` declaration out of a frontmatter body.

    `fm_block` is the return value of `_frontmatter_block()` (the frontmatter
    body text, delimiters excluded) — or None if the caller found no
    frontmatter block at all.

    Returns exactly one of:

      {"status": "absent"}
          `fm_block` is None, or it has no top-level `runtime_probe:` key.

      {"status": "ok", "fields": {key: raw_str, ...}}
          Comment-stripped raw scalar strings, keyed by whatever sub-key
          names were present (including unrecognized ones — see module
          docstring). Type conversion / validation is TASK-001's job, not
          this layer's.

      {"status": "invalid", "reason": str}
          Text-layer rejection — the declaration exists but its shape falls
          outside the restricted grammar (see module docstring for the
          canonical forms). `reason` is a short diagnostic slug, not a fixed
          enum contract.
    """
    if fm_block is None:
        return {"status": "absent"}

    lines = fm_block.splitlines()

    start = None
    top_rest = ""
    for i, line in enumerate(lines):
        m = _TOP_KEY_RE.match(line)
        if m:
            start = i
            top_rest = m.group(1)
            break
    if start is None:
        return {"status": "absent"}

    # Reject anything but a bare `runtime_probe:` (optionally trailing
    # whitespace / a comment) on the top-key line itself — a same-line value
    # means the declaration isn't the expected block mapping.
    top_value = _strip_inline_comment(top_rest).strip()
    if top_value:
        reason = _rejected_scalar_reason(top_value)
        return {
            "status": "invalid",
            "reason": reason or "unexpected_inline_value_on_top_key_line",
        }

    fields: dict[str, str] = {}
    i = start + 1
    n = len(lines)
    while i < n:
        line = lines[i]
        if line.strip() == "":
            i += 1
            continue

        indent = len(line) - len(line.lstrip(" "))
        if indent == 0:
            if line != line.lstrip():
                # Leading whitespace exists (e.g. a tab) that a space-only
                # lstrip(" ") can't see, so `indent` miscomputes to 0 even
                # though this ISN'T a genuine dedent. Treating it as "block
                # ended" here would silently drop this line and every
                # subsequent one (e.g. max_age_days / enabled_when) instead
                # of rejecting the malformed declaration — reject instead.
                return {"status": "invalid", "reason": "tab_indentation"}
            break  # dedent — a sibling top-level key; runtime_probe block ends

        m = _SUB_KEY_RE.match(line)
        if m is None or indent != 2:
            # Doesn't fit the fixed "exactly 2-space indent, scalar `key:`"
            # shape — deeper nesting (indent > 2, incl. a mapping/sequence
            # under a sub-key), a flow-style block opener, or some other
            # malformed line. Never guess: invalid.
            content = line.strip()
            if content.startswith("{"):
                return {"status": "invalid", "reason": "flow_style_mapping"}
            if indent > 2:
                return {"status": "invalid", "reason": "deeper_nesting"}
            return {"status": "invalid", "reason": "malformed_line"}

        key, rest = m.group(1), m.group(2)
        value = _strip_inline_comment(rest).strip()
        reason = _rejected_scalar_reason(value)
        if reason is not None:
            return {"status": "invalid", "reason": reason}
        fields[key] = value
        i += 1

    return {"status": "ok", "fields": fields}

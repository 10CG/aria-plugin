#!/usr/bin/env python3
"""Canonical normalizer for state-snapshot.json (stdlib-only).

Spec: references/json-diff-normalizer.md (T7.0)
Consumers: tests/test_snapshot_stability.py, T7 dogfooding diffs

Rules (see references/json-diff-normalizer.md for full):
1. sorted keys
2. absolute paths → <project_root>
3. timestamp whitelist → <timestamp>
4. ephemeral path fields → <placeholder>
5. 40-char SHAs → 7-char abbreviation
6. floats → round(value, 6)
7. null → absent
8. errors[] sorted by (error, detail)
9. submodules[] sorted by path, remotes[] sorted by name
10. recent_commits[] dropped (too volatile)
11. inter-cycle raw fields dropped: followups[*].raw_row, handoff_doc.raw_match
    (TX.1.a, state-scanner-inter-cycle-surfacing 2026-05-08)

CLI:
  python3 normalize_snapshot.py INPUT [--output OUTPUT]

Exit codes:
  0 — normalized successfully
  1 — input file missing / unreadable
  2 — input is not valid JSON (or contains NaN/Inf)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# --- Constants -----------------------------------------------------------

TIMESTAMP_KEYS = frozenset(
    {"fetched_at", "last_updated", "timestamp", "last_active_at", "generated_at"}
)

# Ephemeral path fields. NOTE: `output` is intentionally NOT in this set —
# custom_checks results carry a legitimate `output` field (stdout first-line)
# that's part of the contract. scan.py does not echo CLI args into the
# snapshot, so there is no `output` key to scrub at the top level.
EPHEMERAL_PATH_KEYS = {
    "project_root": "<project_root>",
    "cache_path": "<cache_path>",
}

DROP_KEYS = frozenset(
    {
        "recent_commits",
        # TX.1.a (state-scanner-inter-cycle-surfacing): drop raw fallback strings
        # to keep canonical form stable when upstream markdown wording drifts.
        # Both keys are unique to inter-cycle surfacing structures (followups +
        # handoff_doc) — no collision with other v1.0 schema fields.
        "raw_row",
        "raw_match",
    }
)

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
# NOTE: the initial draft had a generic `_ABS_PATH_RE` for any leading-`/`
# string with 2+ segments. Dropped in favor of a project_root-prefix-only
# rewrite (see Rule 2 in references/json-diff-normalizer.md). Conservative
# design: zero-false-positive at the cost of leaving non-project absolute
# paths (e.g., `/tmp/*`, `/usr/bin/git`) untouched. At v3.0 snapshot shape,
# scan.py does not emit such paths in any field.


# --- Core transforms -----------------------------------------------------


def _norm_value(key: str | None, value: Any, project_root: str | None) -> Any:
    """Transform a single value per normalization rules.

    `key` is the containing key (for whitelist lookups). `project_root` is the
    detected absolute project root (used to normalize absolute paths).
    """
    # Rule 6 — float precision
    if isinstance(value, float):
        return round(value, 6)

    # Rule 3 — timestamp whitelist (checked at leaf-key level by caller)
    # Rule 4 — ephemeral path whitelist (same)
    if isinstance(value, str):
        # Rule 2 — absolute path normalization
        if project_root and value.startswith(project_root):
            rest = value[len(project_root) :].lstrip("/")
            return f"<project_root>/{rest}" if rest else "<project_root>"
        # Rule 5 — full SHA abbreviation
        if _SHA_RE.match(value):
            return value[:7]
        return value

    return value


def _transform(obj: Any, project_root: str | None, containing_key: str | None = None) -> Any:
    """Recursively apply normalization rules to a JSON-like object."""
    # Leaf-key whitelists (must check before recursion so nested dicts at a
    # whitelisted key get collapsed, though practically our timestamps are
    # always strings).
    if containing_key in TIMESTAMP_KEYS and obj is not None:
        return "<timestamp>"
    if containing_key in EPHEMERAL_PATH_KEYS and obj is not None:
        return EPHEMERAL_PATH_KEYS[containing_key]

    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k in sorted(obj.keys()):
            if k in DROP_KEYS:
                continue  # Rule 10
            v = obj[k]
            if v is None:
                continue  # Rule 7 — null dropped
            out[k] = _transform(v, project_root, containing_key=k)
        return out

    if isinstance(obj, list):
        items = [_transform(v, project_root, containing_key=containing_key) for v in obj]
        # Rule 8 + 9 — stable ordering for specific parent keys
        if containing_key == "errors":
            items.sort(key=lambda e: (e.get("error", ""), e.get("detail", "")) if isinstance(e, dict) else (str(e), ""))
        elif containing_key == "submodules":
            items.sort(
                key=lambda s: s.get("path", "") if isinstance(s, dict) else str(s)
            )
        elif containing_key == "remotes":
            items.sort(
                key=lambda r: r.get("name", "") if isinstance(r, dict) else str(r)
            )
        return items

    return _norm_value(containing_key, obj, project_root)


def _validate_no_nan(obj: Any) -> None:
    """Raise ValueError if obj contains NaN or Inf floats."""
    if isinstance(obj, float):
        if obj != obj or obj in (float("inf"), float("-inf")):
            raise ValueError(f"non-finite float not JSON-representable: {obj!r}")
    elif isinstance(obj, dict):
        for v in obj.values():
            _validate_no_nan(v)
    elif isinstance(obj, list):
        for v in obj:
            _validate_no_nan(v)


def normalize(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Normalize a state-snapshot dict per T7.0 rules.

    Returns a new dict; does not mutate input.
    """
    _validate_no_nan(snapshot)
    # Detect project_root for absolute-path rewriting. After detection, the
    # actual project_root key will be replaced via EPHEMERAL_PATH_KEYS rule.
    project_root = snapshot.get("project_root") if isinstance(snapshot.get("project_root"), str) else None
    return _transform(snapshot, project_root)


# --- CLI ------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("input", type=Path, help="snapshot JSON to normalize")
    p.add_argument(
        "--output", "-o", type=Path, help="write normalized JSON here (default: stdout)"
    )
    args = p.parse_args(argv)

    if not args.input.is_file():
        print(f"error: input not found: {args.input}", file=sys.stderr)
        return 1

    try:
        data = json.loads(args.input.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"error: cannot parse JSON: {e}", file=sys.stderr)
        return 2

    try:
        normalized = normalize(data)
    except ValueError as e:
        print(f"error: normalization failed: {e}", file=sys.stderr)
        return 2

    rendered = json.dumps(normalized, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())

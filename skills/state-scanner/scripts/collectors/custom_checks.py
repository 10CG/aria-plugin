"""Phase 1.11 — Project-level custom health checks collector.

Reads `.aria/state-checks.yaml` (schema version "1") and runs each enabled check
serially with a per-check timeout and a total-budget guard.

YAML subset supported (stdlib-only — no PyYAML):
- Top-level scalar `version: "1"`
- Top-level list `checks:` with mapping items
- Per-check fields: name, description, command, severity, fix, timeout_seconds,
  enabled (scalar or `|` block scalar).
- `#` comments outside block scalars.

Anything outside this subset raises ValueError, which the collector catches and
reports as `parse_error`. This intentionally refuses to silently accept nested
maps, flow style, anchors, etc.

Security model (from SKILL.md §1.11):
- Commands run with shell=True (the schema explicitly documents "shell command"
  and real configs use multi-line `|` scripts). Same trust model as hooks.json.
- `fix` is advisory text only; never executed.
- Check failure never aborts the scan.

Exit code mapping (SKILL.md §1.11 step 3):
- rc == 0, stdout 1st line starts with "##SKIP##" → skip (see below)
- rc == 0 (otherwise) → pass
- rc == 124 (timeout)  → timeout
- rc == 127            → error (command not found)
- rc otherwise non-zero → fail

Skip status (Spec C AC-5b): a check signals "insufficient data / not-applicable"
(visible, counted as NEITHER pass NOR fail) by exiting 0 AND making its first
NON-BLANK stdout line begin with the sentinel "##SKIP##" (leading blank lines and
leading whitespace are tolerated). A STDOUT MARKER — not an exit
code — is used deliberately: exit code 2 collides with grep (file not found),
diff (trouble), and argparse (usage error), so an rc==2→skip mapping would
silently downgrade an adopter's genuinely-failing check from fail to skip
(review B-finding). No tool naturally prints "##SKIP##", so the marker cannot be
triggered by accident. (Distinct from the collector-level "skipped" budget-
exhaust status below, which a check command cannot itself emit.)
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

from ._common import CollectorResult

DEFAULT_TIMEOUT_SECONDS = 15
MAX_TIMEOUT_SECONDS = 60
TOTAL_BUDGET_SECONDS = 60

# A check signals "skip" (visible, not pass/fail — Spec C AC-5b) by exiting 0 with
# a first stdout line beginning with this sentinel. Collision-free stdout marker
# rather than exit code 2 (which grep/diff/argparse use for real errors).
SKIP_MARKER = "##SKIP##"


# ---------------------------------------------------------------------------
# Minimal YAML parser — strictly scoped to state-checks.yaml shape.
# ---------------------------------------------------------------------------

_BOOL_TRUE = {"true", "yes", "on"}
_BOOL_FALSE = {"false", "no", "off"}


def _coerce_scalar(raw: str) -> Any:
    """Coerce a YAML-ish inline scalar to bool/int/str.

    Quoted strings keep their inner value verbatim. Unquoted tokens that match
    bool or int literals are coerced; everything else is str.
    """
    s = raw.strip()
    if not s:
        return ""
    # Quoted
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    low = s.lower()
    if low in _BOOL_TRUE:
        return True
    if low in _BOOL_FALSE:
        return False
    # Integer
    if s.lstrip("-").isdigit():
        try:
            return int(s)
        except ValueError:
            pass
    return s


def _strip_inline_comment(value: str) -> str:
    """Strip ` # comment` tail from an inline scalar. Preserves `#` inside quotes."""
    in_single = False
    in_double = False
    for i, ch in enumerate(value):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            # Require a space before `#` to avoid chopping `#abc` inside unquoted strings
            if i == 0 or value[i - 1].isspace():
                return value[:i].rstrip()
    return value


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _parse_state_checks_yaml(text: str) -> dict[str, Any]:
    """Parse state-checks.yaml into `{"version": str, "checks": [dict, ...]}`.

    Raises ValueError on any structural issue. This is a narrow parser — it
    intentionally rejects YAML features outside the documented schema.
    """
    # Split to raw lines; keep original for block scalar bodies.
    lines = text.splitlines()

    # Strip comment-only or blank lines from top-level scanning, but keep their
    # positions for block scalars to avoid accidentally absorbing comments.
    result: dict[str, Any] = {"version": None, "checks": []}
    i = 0
    n = len(lines)

    def _skip_blank_and_comment(idx: int) -> int:
        while idx < n:
            stripped = lines[idx].strip()
            if not stripped or stripped.startswith("#"):
                idx += 1
                continue
            break
        return idx

    while i < n:
        i = _skip_blank_and_comment(i)
        if i >= n:
            break
        line = lines[i]
        if _indent_of(line) != 0:
            raise ValueError(f"unexpected indent at line {i + 1}")
        stripped = line.strip()
        # `checks:` opens the list
        if stripped == "checks:":
            i += 1
            items, i = _parse_check_list(lines, i)
            result["checks"] = items
            continue
        # `key: value` at top level (only `version` supported)
        if ":" not in stripped:
            raise ValueError(f"expected `key: value` at line {i + 1}: {line!r}")
        key, _, rest = stripped.partition(":")
        key = key.strip()
        rest = _strip_inline_comment(rest).strip()
        if key == "version":
            result["version"] = _coerce_scalar(rest) if rest else None
        else:
            # Unknown top-level keys are ignored for forward-compat; schema only
            # normatively defines `version` and `checks`.
            pass
        i += 1

    if result["version"] is None:
        raise ValueError("missing required top-level field: version")
    return result


def _parse_check_list(lines: list[str], start: int) -> tuple[list[dict[str, Any]], int]:
    """Parse a `-` prefixed list of mappings under `checks:`. Returns (items, next_i)."""
    items: list[dict[str, Any]] = []
    i = start
    n = len(lines)
    list_indent: int | None = None

    while i < n:
        raw = lines[i]
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        indent = _indent_of(raw)
        if indent == 0:
            break  # new top-level key
        if list_indent is None:
            list_indent = indent
        if indent < list_indent:
            break
        if indent > list_indent:
            raise ValueError(f"unexpected indent in checks list at line {i + 1}")
        if not stripped.startswith("- "):
            raise ValueError(f"expected `- ` list item at line {i + 1}: {raw!r}")

        # First key on the same line as `-`: e.g., `- name: "foo"`
        first_key_line = stripped[2:]  # drop leading "- "
        item: dict[str, Any] = {}
        mapping_indent = indent + 2  # keys after `- ` align here
        if first_key_line:
            _consume_mapping_line(first_key_line, item, lines, i, mapping_indent,
                                  block_body_fetcher=_fetch_block_body_starting_after)
            # Determine if the first-key's value spans multiple lines (block scalar).
            # _consume_mapping_line advanced via returning new i. Need to handle it
            # differently: rewrite to walk consistently.
        i += 1

        # Consume remaining keys of this mapping until we see the next `- ` at
        # list_indent or a dedent past list_indent.
        while i < n:
            nxt = lines[i]
            nxt_stripped = nxt.strip()
            if not nxt_stripped or nxt_stripped.startswith("#"):
                i += 1
                continue
            nxt_indent = _indent_of(nxt)
            if nxt_indent <= list_indent:
                break
            if nxt_indent != mapping_indent:
                raise ValueError(f"unexpected indent in mapping at line {i + 1}")
            key_line = nxt_stripped
            i = _consume_mapping_line(key_line, item, lines, i, mapping_indent,
                                      block_body_fetcher=_fetch_block_body_starting_next)

        items.append(item)

    return items, i


def _consume_mapping_line(
    key_line: str,
    item: dict[str, Any],
    lines: list[str],
    current_i: int,
    mapping_indent: int,
    *,
    block_body_fetcher,
) -> int:
    """Handle `key: value` or `key: |` on the current line.

    Returns the new line index to continue from.
    """
    if ":" not in key_line:
        raise ValueError(f"expected `key: value` at line {current_i + 1}: {key_line!r}")
    k, _, v = key_line.partition(":")
    key = k.strip()
    rest = _strip_inline_comment(v).strip()

    if rest == "|":
        # Block scalar — body lines are those indented > mapping_indent.
        body, new_i = block_body_fetcher(lines, current_i, mapping_indent)
        item[key] = body
        return new_i

    item[key] = _coerce_scalar(rest) if rest else ""
    return current_i + 1


def _fetch_block_body_starting_next(
    lines: list[str], key_line_i: int, mapping_indent: int
) -> tuple[str, int]:
    """Collect block scalar body beginning at key_line_i + 1.

    Returns (body_text, next_line_index_after_block).
    """
    body_lines: list[str] = []
    i = key_line_i + 1
    n = len(lines)
    block_indent: int | None = None
    while i < n:
        raw = lines[i]
        if raw.strip() == "":
            # Blank lines inside a block scalar are preserved as empty.
            body_lines.append("")
            i += 1
            continue
        ind = _indent_of(raw)
        if ind <= mapping_indent:
            break
        if block_indent is None:
            block_indent = ind
        if ind < block_indent:
            break
        body_lines.append(raw[block_indent:])
        i += 1
    # Trim trailing blank lines per YAML clip (default) semantics.
    while body_lines and body_lines[-1] == "":
        body_lines.pop()
    return "\n".join(body_lines) + "\n", i


def _fetch_block_body_starting_after(*_args, **_kwargs):  # pragma: no cover
    # Block scalar on the first `- key: |` line is unusual; we refuse rather
    # than silently accept to keep the parser surface tight.
    raise ValueError("block scalar immediately after `- ` is not supported; "
                     "start the key on the next line")


# ---------------------------------------------------------------------------
# Check execution
# ---------------------------------------------------------------------------


def _run_check(
    check: dict[str, Any], project_root: Path, remaining_budget: float
) -> tuple[dict[str, Any], float]:
    """Run a single check. Returns (result_entry, elapsed_seconds)."""
    name = check.get("name") or "<unnamed>"
    severity = check.get("severity") or "info"
    fix = check.get("fix")

    # Per-check timeout: user-configured clamped to [1, 60]; further bounded by
    # remaining total budget so we never exceed 60s combined.
    raw_timeout = check.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    try:
        per_check = int(raw_timeout)
    except (TypeError, ValueError):
        per_check = DEFAULT_TIMEOUT_SECONDS
    per_check = max(1, min(per_check, MAX_TIMEOUT_SECONDS))
    effective_timeout = max(1, min(per_check, int(remaining_budget)))

    command = check.get("command")
    if not command:
        entry = {
            "name": name,
            "status": "error",
            "severity": severity,
            "output": "missing command",
        }
        if fix:
            entry["fix"] = fix
        return entry, 0.0

    start = time.monotonic()
    try:
        p = subprocess.run(
            command,
            cwd=str(project_root),
            shell=True,  # schema documents `command` as a shell script; see module docstring
            capture_output=True,
            text=True,
            timeout=effective_timeout,
            check=False,
        )
        rc = p.returncode
        # First NON-BLANK stdout line (not literally line[0]): a leading blank line
        # is a common shell-output habit and must not hide the ##SKIP## marker,
        # which would silently upgrade a skip to pass (review B1-confirm Major).
        first_line = next(
            (ln for ln in (p.stdout or "").splitlines() if ln.strip()), ""
        )
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        entry = {
            "name": name,
            "status": "timeout",
            "severity": severity,
            "output": f"timeout after {effective_timeout}s",
        }
        if fix:
            entry["fix"] = fix
        return entry, elapsed

    elapsed = time.monotonic() - start

    if rc == 127:
        status = "error"
    elif rc == 0:
        # lstrip so leading whitespace on the marker line still matches.
        status = "skip" if first_line.lstrip().startswith(SKIP_MARKER) else "pass"
    else:
        status = "fail"

    entry = {
        "name": name,
        "status": status,
        "severity": severity,
        "output": first_line or f"rc={rc}",
    }
    if fix:
        entry["fix"] = fix
    return entry, elapsed


# ---------------------------------------------------------------------------
# Public collector
# ---------------------------------------------------------------------------


def collect_custom_checks(project_root: Path) -> CollectorResult:
    r = CollectorResult()
    config_path = project_root / ".aria" / "state-checks.yaml"
    if not config_path.is_file():
        r.data = {"configured": False}
        return r

    try:
        text = config_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        r.soft_error("state_checks_read_failed", str(e))
        r.data = {"configured": False, "parse_error": str(e)}
        return r

    try:
        parsed = _parse_state_checks_yaml(text)
    except ValueError as e:
        r.soft_error("state_checks_parse_failed", str(e))
        r.data = {"configured": False, "parse_error": str(e)}
        return r

    version = parsed.get("version")
    if str(version) != "1":
        r.soft_error(
            "state_checks_unsupported_version", f"version={version!r}, expected '1'"
        )
        r.data = {
            "configured": False,
            "parse_error": f"unsupported schema version: {version!r}",
        }
        return r

    check_defs = parsed.get("checks") or []
    results: list[dict[str, Any]] = []
    passed = 0
    failed = 0
    skipped = 0
    budget_remaining = float(TOTAL_BUDGET_SECONDS)

    for cdef in check_defs:
        if cdef.get("enabled", True) is False:
            continue
        if budget_remaining <= 0:
            results.append(
                {
                    "name": cdef.get("name", "<unnamed>"),
                    "status": "skipped",
                    "severity": cdef.get("severity", "info"),
                    "output": "total budget exhausted",
                }
            )
            r.soft_error(
                "custom_checks_budget_exhausted",
                f"skipped {cdef.get('name', '<unnamed>')}",
            )
            continue
        entry, elapsed = _run_check(cdef, project_root, budget_remaining)
        budget_remaining -= elapsed
        results.append(entry)
        # Three-branch tally (Spec C AC-5b): "skip" is visible but counted as
        # neither pass nor fail — a not-applicable / insufficient-data verdict must
        # not depress the pass rate the way "fail" does. "error"/"timeout" remain in
        # the failed bucket (unchanged). Consumers must not assume passed+failed==total
        # (already untrue for collector-level budget "skipped" entries above).
        status = entry["status"]
        if status == "pass":
            passed += 1
        elif status == "skip":
            skipped += 1
        else:
            failed += 1

    r.data = {
        "configured": True,
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "results": results,
    }
    return r

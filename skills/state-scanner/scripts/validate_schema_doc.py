#!/usr/bin/env python3
"""Validate state-snapshot-schema.md vs scan.py vs live snapshot output.

T4.3 deliverable (Spec CF-4 decision: schema.md is source-of-truth + manual
maintenance + this consistency validator replaces the earlier auto-generation
approach).

Three checks (all TOP-LEVEL KEY GRANULARITY):

1. `SNAPSHOT_SCHEMA_VERSION` constant in `scan.py` matches the `Schema version`
   line in `state-snapshot-schema.md`.
2. Every top-level key listed in schema.md §"Top-level invariants" table
   actually appears in a live scan output (except `issue_status` which is
   opt-in).
3. Every top-level key emitted by scan.py on a real project is documented in
   schema.md (detects forgotten additions).

**Scope limitation** (pre_merge R1 QA-T4-R1-I2): nested field completeness is
NOT checked. A collector can emit a new nested key that is undocumented in
schema.md and this validator will pass. Nested schema drift must be caught by
human review or a future extension (T6 scope). Example: `issue_status.warning`
was emitted but undocumented for one PR cycle before pre_merge audit caught it.

Exits 0 on success, 1 on any mismatch. Non-fatal — intended to run in CI or
manually before doc / scan changes merge.

Usage:
    python3 aria/skills/state-scanner/scripts/validate_schema_doc.py
        [--project-root PATH]   # default cwd (must be inside a git repo;
                                # scan.py exits rc=20 otherwise and the
                                # validator aborts with a setup error)
        [--quiet]               # only print on failure
        [--offline]             # 9.6 (main spec state-scanner-stale-refs-
                                # false-parity, Phase 3): run scan.py with
                                # ARIA_SCAN_OFFLINE=1. Without this flag,
                                # every invocation of this validator (CI or
                                # manual, pre-commit or ad hoc) pays a full
                                # network fetch across every enforced remote
                                # (F3′ remote_refresh) plus a live issue-scan
                                # API call — this validator only checks
                                # TOP-LEVEL key presence (see module
                                # docstring "Scope limitation"), which is
                                # 100% determined by which top-level blocks
                                # scan.py emits, not by any live network
                                # value. `--offline` gets the same key-
                                # presence guarantee (remote_refresh /
                                # coordination_fetch / issue_status still
                                # emit their top-level block, just with
                                # `not_attempted`/cache-sourced leaves) at
                                # zero network cost and zero flakiness.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SCHEMA_DOC_CANDIDATES = [
    # Relative to THIS script's parent (when run from /home/dev/Aria):
    Path(__file__).resolve().parent.parent / "references" / "state-snapshot-schema.md",
]
SCAN_SCRIPT = Path(__file__).resolve().parent / "scan.py"
OPTIONAL_TOP_LEVEL_KEYS = {"issue_status"}  # opt-in per Phase 1.13


def _read_scan_constant() -> str:
    text = SCAN_SCRIPT.read_text(encoding="utf-8")
    m = re.search(r'SNAPSHOT_SCHEMA_VERSION\s*=\s*"([\d.]+)"', text)
    if not m:
        raise RuntimeError("SNAPSHOT_SCHEMA_VERSION constant not found in scan.py")
    return m.group(1)


def _find_schema_doc() -> Path:
    for p in SCHEMA_DOC_CANDIDATES:
        if p.is_file():
            return p
    raise RuntimeError(f"schema doc not found; tried: {SCHEMA_DOC_CANDIDATES}")


def _read_schema_doc_version(schema_doc: Path) -> str:
    text = schema_doc.read_text(encoding="utf-8")
    # Match "> **Schema version**: `1.0`" (trailing backtick required to avoid
    # grabbing prose that mentions the phrase).
    m = re.search(r"\*\*Schema version\*\*:\s*`([\d.]+)`", text)
    if not m:
        raise RuntimeError("'Schema version: `X.Y`' line not found in schema doc")
    return m.group(1)


def _read_schema_doc_top_keys(schema_doc: Path) -> set[str]:
    """Parse the top-level invariants table for documented key names.

    The table has rows like `| `key_name` | ... | ... | ...`. We grab every
    `| \`NAME\`` occurrence at line start of a table row.
    """
    text = schema_doc.read_text(encoding="utf-8")
    # Restrict to the §Top-level invariants section to avoid matching nested
    # example tables (e.g. Worked examples in overall_parity section).
    section_start = text.find("## Top-level invariants")
    next_section_start = text.find("\n## ", section_start + 1)
    section = text[section_start:next_section_start] if section_start >= 0 else ""
    keys = set()
    for line in section.splitlines():
        m = re.match(r"^\|\s*`([a-z_]+)`\s*\|", line)
        if m:
            keys.add(m.group(1))
    return keys


def _run_scan(project_root: Path, offline: bool = False) -> dict:
    """Run scan.py and return the parsed JSON snapshot.

    9.6: `offline=True` sets `ARIA_SCAN_OFFLINE=1` in the child's environment
    (scan.py / remote_refresh.py / issue_scan.py all gate their network calls
    on this — see `collectors/_common.py:is_scan_offline`). This validator
    only checks top-level KEY PRESENCE (module docstring "Scope limitation"),
    which offline mode does not change: every collector still emits its
    top-level block, just with `not_attempted`/cached leaves instead of live
    network values.
    """
    env = dict(os.environ)
    if offline:
        env["ARIA_SCAN_OFFLINE"] = "1"
    p = subprocess.run(
        [sys.executable, str(SCAN_SCRIPT), "--project-root", str(project_root)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=env,
    )
    if p.returncode not in (0, 10):  # 10 = partial, still usable
        raise RuntimeError(
            f"scan.py failed (rc={p.returncode}): {p.stderr[:500]}"
        )
    return json.loads(p.stdout)


def _check(label: str, ok: bool, detail: str, quiet: bool) -> bool:
    if ok:
        if not quiet:
            print(f"  \u2713 {label}")
    else:
        print(f"  \u2717 {label}: {detail}", file=sys.stderr)
    return ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--project-root", type=Path, default=Path.cwd())
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument(
        "--offline",
        action="store_true",
        help="run scan.py with ARIA_SCAN_OFFLINE=1 (9.6): avoids a full "
        "network fetch on every validation run — this validator only checks "
        "top-level key presence, which offline mode does not affect.",
    )
    args = ap.parse_args(argv)

    try:
        schema_doc = _find_schema_doc()
        doc_version = _read_schema_doc_version(schema_doc)
        scan_version = _read_scan_constant()
        doc_keys = _read_schema_doc_top_keys(schema_doc)
        snapshot = _run_scan(args.project_root.resolve(), offline=args.offline)
    except RuntimeError as e:
        print(f"validator setup error: {e}", file=sys.stderr)
        return 1

    live_keys = set(snapshot.keys())

    if not args.quiet:
        print(f"schema doc:  {schema_doc}")
        print(f"doc version: {doc_version}")
        print(f"scan.py version: {scan_version}")
        print(f"documented keys: {len(doc_keys)}; live snapshot keys: {len(live_keys)}")
        print()

    all_ok = True

    all_ok &= _check(
        "version constant matches doc",
        doc_version == scan_version,
        f"doc={doc_version!r}, scan.py={scan_version!r}",
        args.quiet,
    )

    # Every documented required key should be present in live output.
    required_doc_keys = doc_keys - OPTIONAL_TOP_LEVEL_KEYS
    missing_from_live = required_doc_keys - live_keys
    all_ok &= _check(
        "all documented required keys appear in live output",
        not missing_from_live,
        f"missing in live: {sorted(missing_from_live)}",
        args.quiet,
    )

    # Every live key should be documented (otherwise schema.md lags scan.py).
    # `issue_status` may or may not be present; we still require it to be
    # documented when it does appear.
    undocumented = live_keys - doc_keys
    all_ok &= _check(
        "all live keys are documented",
        not undocumented,
        f"live keys missing from schema.md: {sorted(undocumented)}",
        args.quiet,
    )

    if all_ok:
        if not args.quiet:
            print("\n\u2713 schema doc and scan.py are in sync.")
        return 0
    print("\n\u2717 schema doc is out of sync with scan.py output.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

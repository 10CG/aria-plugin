#!/usr/bin/env python3
"""state-scanner mechanical collector — thin CLI + orchestration layer.

Spec: openspec/changes/state-scanner-mechanical-enforcement/
Schema: aria/skills/state-scanner/references/state-snapshot-schema.md

This module is intentionally minimal after the TL-1 split (post_spec audit,
2026-04-23). All phase logic lives in `collectors/` — see `collectors/__init__.py`
for the exported surface.

Coverage (schema v1.0):
- Phase 0:    interrupt recovery (workflow-state.json)
- Phase 1:    git state (branch, status, upstream, recent_commits)
- Phase 1.4:  UPM phase_cycle + active_module (fail-soft if UPM absent)
- Phase 1.5:  changes analysis (file_types, complexity L1-L3, skill_changes)
- Phase 1.5-req: requirements (PRD + User Stories, 5 Status regex variants)
- Phase 1.6:  OpenSpec (changes + archive)
- Phase 1.7:  architecture (system-architecture.md header)
- Phase 1.8:  README sync (version + skill count consistency)
- Phase 1.9:  standards submodule presence
- Phase 1.10: audit reports latest
- Phase 1.11: project-level custom health checks (.aria/state-checks.yaml)
- Phase 1.12: local/remote sync + multi-remote parity (fail-soft, no network
              for `local_refs` mode; optional `ls_remote` opt-in)
- Phase 1.13: Issue awareness (opt-in via issue_scan.enabled; Forgejo/GitHub)
- Phase 1.14: Forgejo CLAUDE.local.md config detection
- Phase 1.15: Session-handoff doc surfacing (docs/handoff/ canonical + .aria/
              handoff/ misplaced detection; additive top-level `handoff` field)
- Phase 1.16: Coordination fetch (git fetch with 30s TTL cache; prerequisite for
              Phase 1.17; additive top-level `coordination_fetch` field)
- Phase 1.17: Cross-branch handoff track rebuild (scans all origin/* branches for
              docs/handoff/*.md, parses frontmatter, legacy fallback for pre-v1.1.0
              docs; additive top-level `tracks_multibranch` field)

Invariants (do not break without schema bump):
- Top-level field `snapshot_schema_version` is the ONLY version gate SKILL.md
  asserts on.
- `issue_status.schema_version` is a nested, independent field (CF-3 naming
  isolation).
- stdlib-only: argparse, json, logging, os, pathlib, sys. Collectors add only
  subprocess + re. No third-party deps.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from collectors import (
    collect_architecture,
    collect_audit,
    collect_changes_analysis,
    collect_coordination_fetch,
    collect_custom_checks,
    collect_forgejo_config,
    collect_git_state,
    collect_handoff,
    collect_handoff_multibranch,
    collect_interrupt_state,
    collect_issue_scan,
    collect_multi_remote,
    collect_openspec,
    collect_readme_sync,
    collect_requirements,
    collect_standards,
    collect_sync_state,
    collect_upm_state,
    log,
)

SNAPSHOT_SCHEMA_VERSION = "1.0"

EXIT_OK = 0
EXIT_SCAN_PARTIAL = 10          # some collectors soft-errored but output is usable
EXIT_HARD_PRECONDITION = 20     # cwd is not a git repo, etc.
EXIT_INTERNAL_BUG = 30          # uncaught exception path

LOG_LEVEL_CHOICES = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def build_snapshot(project_root: Path) -> tuple[dict[str, Any], int]:
    """Run all collectors and return (snapshot, exit_code)."""
    errors: list[dict[str, Any]] = []

    phase0 = collect_interrupt_state(project_root)
    phase1_git = collect_git_state(project_root)
    phase1_4_upm = collect_upm_state(project_root)
    phase1_5_changes = collect_changes_analysis(phase1_git.data)
    phase1_5_req = collect_requirements(project_root)
    phase1_6_openspec = collect_openspec(project_root)
    phase1_7_arch = collect_architecture(project_root)
    phase1_8_readme = collect_readme_sync(project_root)
    phase1_9_standards = collect_standards(project_root)
    phase1_10_audit = collect_audit(project_root)
    phase1_11_custom = collect_custom_checks(project_root)
    phase1_12_sync = collect_sync_state(project_root)
    phase1_12_multi = collect_multi_remote(project_root)
    phase1_13_issue = collect_issue_scan(project_root)
    phase1_14_forgejo = collect_forgejo_config(project_root)
    phase1_15_handoff = collect_handoff(project_root)
    # Phase 1.16: coordination fetch (TASK-003) — must run before multibranch scan.
    # collect_coordination_fetch is idempotent with a 30s TTL cache; running it here
    # ensures all remote refs are available even if the caller did not pre-fetch.
    phase1_16_coord_fetch = collect_coordination_fetch(project_root)
    # Phase 1.17: cross-branch handoff track rebuild (TASK-004).
    # Depends on phase1_16_coord_fetch having populated refs/remotes/origin/*.
    phase1_17_handoff_mb = collect_handoff_multibranch(project_root)

    # T3.3 contract: multi_remote.data returns the inner block; nest under
    # sync_status.multi_remote (overrides the T3.2 stub of {"enabled": false}).
    if isinstance(phase1_12_sync.data, dict):
        phase1_12_sync.data["multi_remote"] = phase1_12_multi.data

    for collector_name, result in [
        ("interrupt", phase0),
        ("git", phase1_git),
        ("upm", phase1_4_upm),
        ("changes", phase1_5_changes),
        ("requirements", phase1_5_req),
        ("openspec", phase1_6_openspec),
        ("architecture", phase1_7_arch),
        ("readme", phase1_8_readme),
        ("standards", phase1_9_standards),
        ("audit", phase1_10_audit),
        ("custom_checks", phase1_11_custom),
        ("sync", phase1_12_sync),
        ("multi_remote", phase1_12_multi),
        ("issue_scan", phase1_13_issue),
        ("forgejo_config", phase1_14_forgejo),
        ("handoff", phase1_15_handoff),
        ("coordination_fetch", phase1_16_coord_fetch),
        ("handoff_multibranch", phase1_17_handoff_mb),
    ]:
        for err in result.errors:
            errors.append({"collector": collector_name, **err})

    snapshot = {
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "generated_by": "scan.py",
        "project_root": str(project_root),
        "interrupt": phase0.data,
        "git": phase1_git.data,
        "upm": phase1_4_upm.data,
        "changes": phase1_5_changes.data,
        "requirements": phase1_5_req.data,
        "openspec": phase1_6_openspec.data,
        "architecture": phase1_7_arch.data,
        "readme": phase1_8_readme.data,
        "standards": phase1_9_standards.data,
        "audit": phase1_10_audit.data,
        "custom_checks": phase1_11_custom.data,
        "sync_status": phase1_12_sync.data,
        "forgejo_config": phase1_14_forgejo.data,
        "handoff": phase1_15_handoff.data,
        "coordination_fetch": phase1_16_coord_fetch.data,
        "tracks_multibranch": phase1_17_handoff_mb.data,
        "errors": errors,
    }

    # Phase 1.13 is opt-in: issue_status appears only when enabled=true per SKILL.md.
    # `enabled: false` branch returns {"enabled": false} — omit issue_status entirely
    # so schema validators can still treat presence as a signal, matching pre-T3.4 behavior.
    if phase1_13_issue.data.get("enabled"):
        snapshot["issue_status"] = phase1_13_issue.data.get("issue_status")

    if not phase1_git.data.get("is_git_repo", False):
        return snapshot, EXIT_HARD_PRECONDITION

    exit_code = EXIT_SCAN_PARTIAL if errors else EXIT_OK
    return snapshot, exit_code


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="state-scanner scan.py",
        description="Collect state-scanner Phase 0+1 data as JSON snapshot.",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Project root to scan (default: cwd)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write JSON snapshot to this path (default: stdout only)",
    )
    # CR-I3 fix: --log-level is now strictly validated. Env var still honored as the
    # default so external callers can set STATE_SCANNER_LOG_LEVEL without flag churn,
    # but any unknown value falls back to WARNING rather than silently passing through.
    env_level = os.environ.get("STATE_SCANNER_LOG_LEVEL", "WARNING").upper()
    default_level = env_level if env_level in LOG_LEVEL_CHOICES else "WARNING"
    parser.add_argument(
        "--log-level",
        choices=LOG_LEVEL_CHOICES,
        type=str.upper,
        default=default_level,
        help=f"Python logging level (default: {default_level}; env STATE_SCANNER_LOG_LEVEL)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level, logging.WARNING),
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    try:
        snapshot, exit_code = build_snapshot(args.project_root.resolve())
    except Exception:  # noqa: BLE001 — top-level guard
        log.exception("uncaught collector error")
        return EXIT_INTERNAL_BUG

    rendered = json.dumps(snapshot, indent=2, ensure_ascii=False, sort_keys=True)
    # R1-I3: --output is exclusive with stdout to keep shell pipes clean.
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())

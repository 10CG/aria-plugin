#!/usr/bin/env python3
"""state-scanner mechanical collector — thin CLI + orchestration layer.

Spec: openspec/changes/state-scanner-mechanical-enforcement/
Schema: aria/skills/state-scanner/references/state-snapshot-schema.md

This module is intentionally minimal after the TL-1 split (post_spec audit,
2026-04-23). All phase logic lives in `collectors/` — see `collectors/__init__.py`
for the exported surface.

Coverage (schema v1.0):
- Phase 0:    interrupt recovery (workflow-state.json)
- Phase 0.5:  remote_refresh (F3′, main spec state-scanner-stale-refs-false-parity,
              Phase 1 increment 5) — fetches every enforced (repo, remote) leg
              (main repo + every INITIALIZED submodule) BEFORE any other Phase-1
              collector reads local git state, so `git.upstream.behind` /
              `sync_status.current_branch` / `multi_remote` never disagree about
              freshness inside the same snapshot (tasks 3.9). Additive top-level
              `remote_refresh` field. Also runs the special (".", "origin")
              coordination-ref fetch (Fetch 2) formerly owned by Phase 1.16 —
              see below.
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
- Phase 1.15b: Cross-worktree handoff discovery (#139; enumerates git worktrees,
              arbitrates the global-latest handoff, flags when it lives in a
              worktree other than the current one; additive top-level
              `handoff_worktrees` field)
- Phase 1.16: Coordination fetch — RETIRED as an independent network fetch
              (F6′, Phase 1 increment 5). `coordination_fetch` is now a PURE
              derivation (`derive_legacy_coordination_fetch_block`) off Phase
              0.5's `remote_refresh` (".", "origin") leg — same additive
              top-level `coordination_fetch` field, byte-compatible schema, no
              second TTL cache. Still a prerequisite for Phase 1.17 (the
              underlying fetch now happens even earlier, at Phase 0.5).
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
from datetime import timezone
from pathlib import Path
from typing import Any

from collectors import (
    CollectorResult,
    collect_architecture,
    collect_audit,
    collect_changes_analysis,
    collect_custom_checks,
    collect_forgejo_config,
    collect_git_state,
    collect_handoff,
    collect_handoff_multibranch,
    collect_handoff_worktrees,
    collect_interrupt_state,
    collect_issue_scan,
    collect_multi_remote,
    collect_openspec,
    collect_readme_sync,
    collect_remote_refresh,
    collect_requirements,
    collect_standards,
    collect_sync_state,
    collect_upm_state,
    derive_legacy_coordination_fetch_block,
    log,
    scan_now,
)
from collectors._common import _run, classify_git_error

SNAPSHOT_SCHEMA_VERSION = "1.0"

EXIT_OK = 0
EXIT_SCAN_PARTIAL = 10          # some collectors soft-errored but output is usable
EXIT_HARD_PRECONDITION = 20     # cwd is not a git repo, etc.
EXIT_INTERNAL_BUG = 30          # uncaught exception path

LOG_LEVEL_CHOICES = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def _same_branch_head_unreachable_tracks(
    project_root: Path,
    git_data: dict[str, Any],
    tracks_data: dict[str, Any],
    enforced_remotes: list[str],
    timeout: int = 5,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """AC-5 support (task 2.12) — find handoff tracks published on the CURRENT
    branch's remote counterpart whose introducing commit HEAD cannot reach.

    Checked against the SAME remote set the verdict was computed over
    (`enforced_remotes_resolved`), never a hardcoded `origin` (review I4). Two
    distinct bugs come from hardcoding it: (a) if `origin` is read-only or outside
    the allowlist, `overall_parity` can legitimately be true while `origin` itself is
    arbitrarily stale ⇒ the detector fires a FALSE contradiction against a remote the
    verdict never consulted; (b) a repo whose primary remote is not named `origin`
    gets empty `git log` output on every track ⇒ the detector silently never fires.
    Detection set and verdict set must be the same set, or the comparison is
    meaningless in both directions.

    Scope discipline, verbatim from AC-5: only tracks whose ``branch`` equals the
    HEAD branch qualify. "Any commit HEAD cannot reach" would flag every repo that
    merely has other active branches — a false-red on healthy repos, and the AC
    text calls that out explicitly as the wrong predicate.

    Returns ``(offenders, inconclusive)``:
    - ``offenders``: tracks proven unreachable from HEAD.
    - ``inconclusive``: tracks the detector could not EVALUATE (git command failed).

    🔴 The two must not be merged into one "nothing to report" bucket. `rc != 0` and
    `rc == 0 with empty output` look alike at the call site but mean opposite things:
    the second is a real answer ("this file has no commit on that ref"), the first is
    the absence of an answer (`origin/<branch>` missing locally, fetch never landed,
    subprocess deadline, git binary gone). And the rc != 0 population correlates
    POSITIVELY with the condition being detected — a missing or unfetchable
    `origin/<branch>` is precisely the stale-remote-ref world this spec exists to stop
    lying about. Swallowing it would make the one detector guarding the originating
    accident go quiet exactly in the accident's neighborhood, while the snapshot still
    ships green. That is fail-OPEN in a codebase whose invariant is 宁可报红, 不可假绿.
    """
    branch = git_data.get("current_branch")
    if not branch or git_data.get("detached_head"):
        return [], []
    tracks = tracks_data.get("tracks")
    if not isinstance(tracks, list):
        return [], []
    if not enforced_remotes:
        return [], []

    offenders: list[dict[str, str]] = []
    inconclusive: list[dict[str, str]] = []
    for t in tracks:
        if not isinstance(t, dict) or t.get("branch") != branch:
            continue
        filename = t.get("filename")
        if not filename:
            continue
        for remote in enforced_remotes:
            cmd = [
                "git", "log", "-1", "--format=%H",
                f"{remote}/{branch}", "--", f"docs/handoff/{filename}",
            ]
            rc, out, err = _run(cmd, project_root, timeout=timeout)
            if rc != 0:
                # Rule #7: route stderr through the typed channel — a bounded label
                # survives, the raw text (which can carry a credential URL) does not.
                inconclusive.append({
                    "filename": str(filename),
                    "remote": str(remote),
                    "error": classify_git_error(rc, err, "git log").label,
                })
                continue
            sha = out.strip()
            if not sha:
                continue  # a real answer: no commit for this file on that ref
            rc_anc, _, _ = _run(
                ["git", "merge-base", "--is-ancestor", sha, "HEAD"],
                project_root,
                timeout=timeout,
            )
            if rc_anc != 0:
                offenders.append({
                    "track_id": str(t.get("track_id", "")),
                    "filename": str(filename),
                    "remote": str(remote),
                    "commit": sha[:7],
                })
    return offenders, inconclusive


def _check_snapshot_self_consistency(
    project_root: Path,
    git_data: dict[str, Any],
    tracks_data: dict[str, Any],
    sync_data: dict[str, Any],
) -> list[dict[str, Any]]:
    """AC-5 (task 2.12) — the cross-collector invariant this whole spec started from.

    The originating accident was ONE SNAPSHOT CONTRADICTING ITSELF: `tracks_multibranch`
    listed handoff files that existed on `origin/master` while `sync_status` reported
    `parity: equal` against that same ref. Both readings came from the same stale
    remote-tracking ref, so neither collector could notice on its own — the
    contradiction is only visible where their outputs meet, which is here.

    F3′ (Phase 0.5, fetch --prune before any Phase-1 collector reads local git state)
    removes the CAUSE; this check is the detector that keeps its removal honest. If it
    ever fires again, the fingerprint is recorded rather than silently shipped as a
    green verdict.

    Deliberately placed at the assembly layer, NOT inside either collector: it is a
    statement about two collectors' joint output, and `multi_remote` (Phase 1.12)
    runs before `handoff_multibranch` (Phase 1.17) so it could not consume it anyway
    without a reordering this spec has no reason to risk.

    Verdict shape follows AC-5's disjunction — an offending track is a contradiction
    ONLY when the snapshot simultaneously claims health: `overall_parity == true` AND
    the current branch's own `reason` is empty. Either of those already being honest
    means the snapshot is telling the truth about being behind/uncertain, and the
    tracks are simply the evidence for it.
    """
    # Cheap guards first (M4): if the snapshot is not claiming health, nothing the
    # detector finds can be a contradiction — skip the subprocesses entirely.
    multi = sync_data.get("multi_remote") or {}
    current = sync_data.get("current_branch") or {}
    claims_health = multi.get("overall_parity") is True and not current.get("reason")
    if not claims_health:
        return []

    enforced_remotes = multi.get("enforced_remotes_resolved") or []
    offenders, inconclusive = _same_branch_head_unreachable_tracks(
        project_root, git_data, tracks_data, enforced_remotes
    )

    out: list[dict[str, Any]] = []
    if offenders:
        out.append({
            "kind": "snapshot_self_contradiction",
            "detail": (
                f"{len(offenders)} handoff track(s) on origin/{git_data.get('current_branch')} "
                "are unreachable from HEAD, yet overall_parity=true with no reason on the "
                "current branch (AC-5). Remote-tracking refs are likely stale despite the "
                "F3′ refresh — re-run with a successful fetch before trusting parity."
            ),
            "tracks": offenders,
        })
    if inconclusive:
        # Distinct from the contradiction above: we do not know whether the snapshot
        # is lying, and that itself must be on the record while it claims health.
        # Silence here would be indistinguishable from "checked, all clear".
        out.append({
            "kind": "snapshot_consistency_inconclusive",
            "detail": (
                f"AC-5 could not be evaluated for {len(inconclusive)} track(s) on "
                f"origin/{git_data.get('current_branch')} (git command failed) while the "
                "snapshot claims overall_parity=true with no reason. Treat the parity "
                "verdict as unverified for this scan."
            ),
            "tracks": inconclusive,
        })
    return out


def build_snapshot(project_root: Path) -> tuple[dict[str, Any], int]:
    """Run all collectors and return (snapshot, exit_code)."""
    # Top-level scan-start timestamp (Spec C: issue-cache-freshness lag-1 assertion).
    # Captured at entry so it reflects "when this scan started"; issue_status.fetched_at
    # is stamped later during collect_issue_scan, so a live fetch yields fetched_at >=
    # generated_at (negative Δ = healthiest signal). ISO 8601 UTC 'Z' form matches
    # issue_scan._now_iso() for same-format subtraction. Additive field; does NOT bump
    # snapshot_schema_version (references/state-snapshot-schema.md §Versioning).
    # Routed through scan_now() (9.7 wall-clock face) — honors ARIA_SCAN_NOW so a
    # frozen-clock scan never derives a timestamp from the real system clock.
    # astimezone(utc) first: scan_now() honors an ARIA_SCAN_NOW override that may
    # carry a non-UTC offset (naive overrides are already coerced to UTC, but an
    # explicit-offset override is returned verbatim) — the 'Z' suffix below is only
    # honest once the instant is normalized to UTC.
    generated_at = scan_now().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    errors: list[dict[str, Any]] = []

    phase0 = collect_interrupt_state(project_root)
    # Phase 0.5 (F3′, main spec state-scanner-stale-refs-false-parity): fetch
    # every enforced (repo, remote) leg BEFORE any Phase-1 collector reads local
    # git state — must run first so `git.upstream.behind` (Phase 1) and
    # `sync_status`/`multi_remote` (Phase 1.12) never disagree about freshness
    # inside the same snapshot (tasks 3.9). Also owns the (".", "origin")
    # coordination-ref fetch formerly run independently at Phase 1.16.
    phase0_5_remote_refresh = collect_remote_refresh(project_root)
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
    # F9′ (main spec state-scanner-stale-refs-false-parity, OQ-E=(a)) — ordering
    # anchor: collect_multi_remote MUST run before collect_sync_state. sync.py's
    # current_branch/submodule evidence_grade join (8.1) consumes
    # collect_multi_remote(...).data directly (not a re-read of any cache) — if this
    # order is ever reversed, multi_remote_data stays the caller-omitted default
    # (None) and every evidence_grade in sync_status silently resolves "expired"
    # (fail-CLOSED, see collect_sync_state's own docstring) — that is the observable
    # symptom to grep for if this invariant regresses.
    phase1_12_multi = collect_multi_remote(project_root)
    phase1_12_sync = collect_sync_state(
        project_root, multi_remote_data=phase1_12_multi.data
    )
    phase1_13_issue = collect_issue_scan(project_root)
    phase1_14_forgejo = collect_forgejo_config(project_root)
    phase1_15_handoff = collect_handoff(project_root)
    # Phase 1.15b: cross-worktree handoff discovery (#139). Consumes 1.15 data for
    # the current tree's latest (no re-scan; R2 N-6/m-6) → registered right after.
    phase1_15b_worktrees = collect_handoff_worktrees(
        project_root, phase1_15_handoff.data
    )
    # Phase 1.16: coordination fetch (TASK-003) — RETIRED as an independent
    # network fetch (F6′, Phase 1 increment 5). The (".", "origin") fetch
    # already ran at Phase 0.5; this is now a PURE re-derivation of the legacy
    # schema off that leg's record — no I/O, cannot soft-error on its own.
    phase1_16_coord_fetch = CollectorResult(
        data=derive_legacy_coordination_fetch_block(phase0_5_remote_refresh.data)
    )
    # Phase 1.17: cross-branch handoff track rebuild (TASK-004).
    # Depends on Phase 0.5 having populated refs/remotes/origin/* (fetched even
    # earlier now than the retired Phase 1.16 independent fetch did).
    phase1_17_handoff_mb = collect_handoff_multibranch(project_root)

    # T3.3 contract: multi_remote.data returns the inner block; nest under
    # sync_status.multi_remote (overrides the T3.2 stub of {"enabled": false}).
    if isinstance(phase1_12_sync.data, dict):
        phase1_12_sync.data["multi_remote"] = phase1_12_multi.data

    for collector_name, result in [
        ("interrupt", phase0),
        ("remote_refresh", phase0_5_remote_refresh),
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
        ("handoff_worktrees", phase1_15b_worktrees),
        ("coordination_fetch", phase1_16_coord_fetch),
        ("handoff_multibranch", phase1_17_handoff_mb),
    ]:
        for err in result.errors:
            errors.append({"collector": collector_name, **err})

    # AC-5 (task 2.12): cross-collector self-consistency. Runs after every collector
    # so it can compare their joint output; attributed to a synthetic collector name
    # because no single collector owns the invariant.
    for err in _check_snapshot_self_consistency(
        project_root,
        phase1_git.data,
        phase1_17_handoff_mb.data,
        phase1_12_sync.data,
    ):
        errors.append({"collector": "snapshot_consistency", **err})

    snapshot = {
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "generated_by": "scan.py",
        "generated_at": generated_at,
        "project_root": str(project_root),
        "interrupt": phase0.data,
        "remote_refresh": phase0_5_remote_refresh.data,
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
        "handoff_worktrees": phase1_15b_worktrees.data,
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

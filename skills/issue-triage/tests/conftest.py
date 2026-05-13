"""pytest fixtures for aria/skills/issue-triage tests.

Dependency note:
  jsonschema is required for test_schema.py. It is NOT a stdlib module.
  In this environment it is installed as the system package python3-jsonschema.
  If jsonschema is unavailable, test_schema.py uses pytest.importorskip() to
  degrade gracefully (those tests are skipped rather than error).

Rule #7 compliance:
  All subprocess calls in the collectors under test use capture_output=True.
  Tests must NOT call forgejo or git against live remotes. All external calls
  are replaced by monkeypatching _common._run at import time.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Generator

import pytest

# ── Path setup ────────────────────────────────────────────────────────────────
# Ensure the scripts/ directory is importable as a package root so that
# `from collectors import ...` works inside the test session.
_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


# ── Fixtures — programmatic git repository ────────────────────────────────────

def _git(args: list[str], cwd: str) -> None:
    """Run a git command silently; raise on non-zero exit."""
    subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        check=True,
    )


@pytest.fixture()
def git_repo(tmp_path: Path) -> Generator[Path, None, None]:
    """Programmatic git repository with controlled commits.

    Yields the repo root Path. Automatically cleaned up by tmp_path.

    Commit log (controlled messages for keyword-matching tests):
      sha-3  fix: resolve close #101 normalize the status field   <- 4 keywords
      sha-2  refactor: extract _common helpers                    <- no fix keywords
      sha-1  feat: initial collector scaffold                     <- no fix keywords

    Files:
      scripts/collectors/_inflight.py   (stub, 50 lines)
      scripts/collectors/_common.py     (stub, 30 lines)
    """
    repo = tmp_path / "test-repo"
    repo.mkdir()

    scripts_dir = repo / "scripts" / "collectors"
    scripts_dir.mkdir(parents=True)

    # Configure git identity for the test repo (no global config needed)
    _git(["init", "-q"], str(repo))
    _git(["config", "user.email", "test@example.com"], str(repo))
    _git(["config", "user.name", "Test User"], str(repo))

    # commit 1: initial scaffold
    inflight = scripts_dir / "_inflight.py"
    inflight.write_text(
        "# inflight collector stub\n" + "pass\n" * 48,
        encoding="utf-8",
    )
    common = scripts_dir / "_common.py"
    common.write_text(
        "# common stub\n" + "pass\n" * 28,
        encoding="utf-8",
    )
    _git(["add", "."], str(repo))
    _git(["commit", "-m", "feat: initial collector scaffold"], str(repo))

    # commit 2: refactor (no fix keywords)
    common.write_text(
        "# common stub refactored\n" + "pass\n" * 29,
        encoding="utf-8",
    )
    _git(["add", "."], str(repo))
    _git(["commit", "-m", "refactor: extract _common helpers"], str(repo))

    # commit 3: fix commit with multiple matching keywords
    inflight.write_text(
        "# inflight collector fixed\n" + "# resolve close #101 normalize the status field\n" + "pass\n" * 47,
        encoding="utf-8",
    )
    _git(["add", "."], str(repo))
    _git(
        ["commit", "-m", "fix: resolve close #101 normalize the status field"],
        str(repo),
    )

    yield repo


@pytest.fixture()
def git_repo_no_fix_commits(tmp_path: Path) -> Generator[Path, None, None]:
    """Git repo with commits that have NO fix keywords.

    Used to verify likely_fix_candidates returns empty array (not null/missing).
    """
    repo = tmp_path / "test-repo-nofx"
    repo.mkdir()

    scripts_dir = repo / "scripts" / "collectors"
    scripts_dir.mkdir(parents=True)

    _git(["init", "-q"], str(repo))
    _git(["config", "user.email", "test@example.com"], str(repo))
    _git(["config", "user.name", "Test User"], str(repo))

    target = scripts_dir / "_version.py"
    target.write_text("# version collector stub\n" + "pass\n" * 20, encoding="utf-8")
    _git(["add", "."], str(repo))
    _git(["commit", "-m", "docs: update version collector comments"], str(repo))

    target.write_text("# version collector updated\n" + "pass\n" * 21, encoding="utf-8")
    _git(["add", "."], str(repo))
    _git(["commit", "-m", "chore: bump stub version"], str(repo))

    yield repo


# ── Fixtures — Forgejo fixture data ───────────────────────────────────────────

@pytest.fixture()
def forgejo_issue_101() -> dict[str, Any]:
    """Load the captured Forgejo issue-101 API response fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "forgejo" / "issue-101.json"
    return json.loads(fixture_path.read_text(encoding="utf-8"))


@pytest.fixture()
def forgejo_issue_not_found() -> dict[str, Any]:
    """Load the Forgejo 404 not-found response fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "forgejo" / "issue-not-found.json"
    return json.loads(fixture_path.read_text(encoding="utf-8"))


# ── Fixtures — issue body text ────────────────────────────────────────────────

def _load_issue_body(name: str) -> str:
    fixture_path = Path(__file__).parent / "fixtures" / "issue-bodies" / name
    return fixture_path.read_text(encoding="utf-8")


@pytest.fixture()
def issue_body_backtick() -> str:
    return _load_issue_body("backtick-citation.md")


@pytest.fixture()
def issue_body_prose() -> str:
    return _load_issue_body("prose-citation.md")


@pytest.fixture()
def issue_body_md_link() -> str:
    return _load_issue_body("md-link-citation.md")


@pytest.fixture()
def issue_body_no_citation() -> str:
    return _load_issue_body("no-citation.md")


# ── Fixtures — standalone aria-plugin repo ───────────────────────────────────

@pytest.fixture()
def standalone_plugin_repo(tmp_path: Path) -> Path:
    """Project root with ONLY .claude-plugin/plugin.json (path 2 of version chain).

    Used to verify triage_tool_version is populated from path 2 when path 1
    (aria/.claude-plugin/plugin.json) is absent (mid-review M2 fix verification).
    """
    root = tmp_path / "standalone-plugin"
    root.mkdir()
    plugin_dir = root / ".claude-plugin"
    plugin_dir.mkdir()
    plugin_json = {"name": "aria", "version": "1.19.0", "description": "test"}
    (plugin_dir / "plugin.json").write_text(
        json.dumps(plugin_json), encoding="utf-8"
    )
    return root


# ── Fixtures — minimal valid triage report ────────────────────────────────────

@pytest.fixture()
def minimal_valid_report() -> dict[str, Any]:
    """A minimal schema-valid triage report (mechanical output scaffold).

    verdict=null, deviation_note=null (conditional only fires on partial-repro).
    """
    return {
        "schema_version": "1.0",
        "triage_tool_version": "1.19.0",
        "issue_ref": "10CG/Aria#101",
        "generated_at": "2026-05-13T00:00:00Z",
        "steps": {
            "step1_issue": {
                "collection_status": "ok",
                "title": "test issue",
                "body": "test body",
                "labels": [],
                "comments": [],
            },
            "step2_version": {
                "collection_status": "ok",
                "current": "1.19.0",
                "reported": None,
                "gap": None,
            },
            "step3_code": {
                "collection_status": "skipped",
                "cited_paths": [],
                "matches_description": None,
            },
            "step4_history": {
                "collection_status": "skipped",
                "likely_fix_candidates": [],
            },
            "step5_inflight": {
                "collection_status": "ok",
                "remote_prs": [],
                "local_branches": [],
                "worktrees": [],
            },
        },
        "repro": {
            "exit_mode": None,
            "cases": [],
            "hit_count": 0,
            "total_count": 0,
            "hit_rate": "0/0",
        },
        "verdict": None,
        "severity": None,
        "recommended_action": None,
        "deviation_note": None,
        "errors": [],
    }

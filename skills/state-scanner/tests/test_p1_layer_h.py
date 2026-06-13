"""TASK-008 — P1 Unit + Integration Tests (5 cases) for Layer H.

Covers:
    Case A — Legacy doc graceful skip (no frontmatter → parse returns None;
              collect_handoff_multibranch marks track legacy=True, no exception)
    Case B — latest.md multi-track vs single-track:
              B.1 single active track → write_latest_md action="pointer"
              B.2 ≥2 active tracks   → write_latest_md action="banner"
    Case C — Backward-compat markdown: multi-track latest.md produced by B.2
              is valid readable markdown; collect_handoff main flow does not crash
    Case D — Offline red-bar injection: render_track_board emits ⚠ 离线 when
              coordination_fetch.degraded=True
    Case E — N=20+ remote branches performance baseline (elapsed < 30s)

Spec: openspec/changes/multi-terminal-coordination/tasks.md §1.8
Task: TASK-008 (qa-engineer)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

# ── Ensure collectors package is importable ───────────────────────────────────
_TESTS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TESTS_DIR.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# Also ensure _helpers is importable (some test helpers use it transitively)
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

# ── Lazy YAML availability probe ──────────────────────────────────────────────
try:
    import yaml as _yaml_probe  # noqa: F401
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

# ── SUT imports ───────────────────────────────────────────────────────────────
from collectors.handoff import collect_handoff, parse_handoff_frontmatter
from collectors.handoff_multibranch import collect_handoff_multibranch
from renderers.track_board import render_track_board
from writers.latest_md_writer import write_latest_md

# ── Git identity env for deterministic commits ───────────────────────────────
_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run git inside `repo` with deterministic identity (Rule #7: capture_output)."""
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        env=_GIT_ENV,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=check,
    )


def _build_local_repo_with_remote_branches(
    tmp_path: Path,
    branches: list[tuple[str, list[tuple[str, str]]]],
) -> tuple[Path, Path]:
    """Build a bare 'remote' repo and a clone with tracking refs populated.

    Args:
        tmp_path: Temp directory root for this test.
        branches: List of (branch_name, [(relative_path, content), ...]).
                  Each branch will have docs committed and be pushed to the
                  bare remote.

    Returns:
        (local_repo_path, bare_remote_path)

    Strategy: git clone of a bare repo gives the local repo a real "origin"
    with refs/remotes/origin/* populated after fetch — exactly what
    collect_handoff_multibranch expects (it reads refs/remotes/origin/*).
    """
    bare = tmp_path / "bare.git"
    bare.mkdir()
    _git(bare, "init", "--bare", "-q", "--initial-branch=master")

    # Create a throw-away staging repo to build the initial commit and branches.
    staging = tmp_path / "staging"
    staging.mkdir()
    _git(staging, "init", "-q", "--initial-branch=master")
    _git(staging, "remote", "add", "origin", str(bare))
    (staging / "README.md").write_text("# test\n", encoding="utf-8")
    _git(staging, "add", "README.md")
    _git(staging, "commit", "-q", "-m", "initial")
    _git(staging, "push", "-q", "origin", "master")

    for branch_name, files in branches:
        # Checkout a new branch from master for each feature branch
        _git(staging, "checkout", "-q", "-b", branch_name, "master")
        for rel_path, content in files:
            full = staging / rel_path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content, encoding="utf-8")
        _git(staging, "add", ".")
        _git(staging, "commit", "-q", "-m", f"handoff for {branch_name}")
        _git(staging, "push", "-q", "origin", branch_name)
        # Return to master for next iteration
        _git(staging, "checkout", "-q", "master")

    # Clone the bare repo — this gives us a proper local repo with
    # refs/remotes/origin/* already populated (git clone auto-fetches).
    local = tmp_path / "local"
    _git(tmp_path, "clone", "-q", str(bare), str(local))

    return local, bare


# ─────────────────────────────────────────────────────────────────────────────
# Case A — Legacy doc graceful skip
# ─────────────────────────────────────────────────────────────────────────────

class TestCaseA_LegacyDocGracefulSkip(unittest.TestCase):
    """(a) No-frontmatter legacy handoff → parse_handoff_frontmatter returns None;
       collect_handoff_multibranch marks track legacy=True, does not raise.
    """

    LEGACY_CONTENT = (
        "# Aria — Session Handoff\n\n"
        "## §0 Entry\n\nThis is a legacy-format handoff doc with no YAML frontmatter.\n"
    )

    def test_parse_returns_none_for_no_frontmatter(self):
        """parse_handoff_frontmatter(legacy_content) must return None — no raise."""
        result = parse_handoff_frontmatter(self.LEGACY_CONTENT)
        self.assertIsNone(result)

    def test_parse_returns_none_for_empty_string(self):
        """Empty document → None (not an exception)."""
        self.assertIsNone(parse_handoff_frontmatter(""))

    @unittest.skipIf(not _YAML_AVAILABLE, "PyYAML not installed — YAML path irrelevant")
    def test_parse_returns_none_for_incomplete_frontmatter(self):
        """Frontmatter present but missing required keys → None."""
        content = "---\ntrack-id: foo\n---\n\n# body\n"
        self.assertIsNone(parse_handoff_frontmatter(content))

    def test_collect_multibranch_legacy_track_marked_correctly(self):
        """collect_handoff_multibranch: legacy doc → legacy=True track, no exception."""
        import tempfile
        with tempfile.TemporaryDirectory(prefix="ss-a-") as td:
            tmp = Path(td)
            local, _bare = _build_local_repo_with_remote_branches(
                tmp,
                branches=[
                    (
                        "feature/legacy-handoff",
                        [("docs/handoff/2026-01-01-legacy.md", self.LEGACY_CONTENT)],
                    )
                ],
            )

            # Must not raise
            result = collect_handoff_multibranch(local, remote="origin")

            data = result.data
            self.assertIn("tracks", data)
            tracks = data["tracks"]

            # At least one track for our branch
            self.assertGreater(len(tracks), 0, "Expected ≥1 track from the legacy branch")

            # Every track for our legacy branch must be marked legacy
            branch_tracks = [t for t in tracks if "legacy-handoff" in t.get("branch", "")]
            self.assertGreater(len(branch_tracks), 0, "No track found for legacy-handoff branch")
            for t in branch_tracks:
                self.assertTrue(t["legacy"], f"Expected legacy=True for track {t!r}")
                self.assertEqual(t["status"], "legacy")
                # track_id must use the "legacy:" prefix scheme
                self.assertTrue(
                    t["track_id"].startswith("legacy:"),
                    f"Expected legacy: prefix, got {t['track_id']!r}",
                )

    def test_collect_multibranch_does_not_raise_on_legacy(self):
        """End-to-end: calling collector with a legacy doc branch must not propagate any exception."""
        import tempfile
        with tempfile.TemporaryDirectory(prefix="ss-a2-") as td:
            tmp = Path(td)
            local, _bare = _build_local_repo_with_remote_branches(
                tmp,
                branches=[
                    (
                        "legacy-branch",
                        [("docs/handoff/handoff-note.md", self.LEGACY_CONTENT)],
                    )
                ],
            )
            # Must not raise even if PyYAML is unavailable or doc is malformed
            try:
                result = collect_handoff_multibranch(local, remote="origin")
            except Exception as exc:  # noqa: BLE001
                self.fail(f"collect_handoff_multibranch raised unexpectedly: {exc!r}")

            # legacy_count must be ≥1 (the single legacy doc we added)
            self.assertGreaterEqual(result.data.get("legacy_count", 0), 1)


# ─────────────────────────────────────────────────────────────────────────────
# Case B — latest.md multi-track vs single-track
# ─────────────────────────────────────────────────────────────────────────────

_FIXED_NOW = datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)


def _active_track(track_id: str, filename: str) -> dict:
    return {
        "track_id": track_id,
        "owner_container": "devbox-A/sess-001",
        "phase": "B.2",
        "status": "active",
        "updated_at": "2026-05-20T10:00:00Z",
        "branch": "feature/test",
        "filename": filename,
        "legacy": False,
    }


class TestCaseB_LatestMdSingleVsMultiTrack(unittest.TestCase):
    """(b) write_latest_md: single track → pointer; multi track → banner."""

    def test_b1_single_track_pointer_action(self):
        """Single active track → action='pointer', file written, contains **Latest**."""
        import tempfile
        with tempfile.TemporaryDirectory(prefix="ss-b1-") as td:
            out = Path(td) / "docs" / "handoff" / "latest.md"
            snapshot = {
                "tracks_multibranch": {
                    "tracks": [_active_track("my-spec", "2026-05-20-my-spec.md")],
                    "branches_scanned": 1,
                    "legacy_count": 0,
                    "errors": [],
                    "exists": True,
                }
            }

            result = write_latest_md(snapshot, out, now=_FIXED_NOW)

            # Action must be "pointer"
            self.assertEqual(result["action"], "pointer")
            # File must actually be written
            self.assertTrue(out.is_file(), "latest.md was not written")
            content = out.read_text(encoding="utf-8")
            # Must contain the **Latest**: pointer line
            self.assertIn("**Latest**:", content)
            self.assertIn("2026-05-20-my-spec.md", content)

    def test_b1_parent_dir_auto_created(self):
        """write_latest_md creates the parent directory if absent."""
        import tempfile
        with tempfile.TemporaryDirectory(prefix="ss-b1b-") as td:
            out = Path(td) / "deep" / "nested" / "latest.md"
            snapshot = {
                "tracks_multibranch": {
                    "tracks": [_active_track("t1", "doc1.md")],
                    "branches_scanned": 1,
                    "legacy_count": 0,
                    "errors": [],
                    "exists": True,
                }
            }
            write_latest_md(snapshot, out, now=_FIXED_NOW)
            self.assertTrue(out.is_file())

    def test_b2_multi_track_banner_action(self):
        """Two active tracks → action='banner', file contains deprecation marker."""
        import tempfile
        with tempfile.TemporaryDirectory(prefix="ss-b2-") as td:
            out = Path(td) / "docs" / "handoff" / "latest.md"
            snapshot = {
                "tracks_multibranch": {
                    "tracks": [
                        _active_track("track-alpha", "2026-05-20-alpha.md"),
                        _active_track("track-beta", "2026-05-20-beta.md"),
                    ],
                    "branches_scanned": 2,
                    "legacy_count": 0,
                    "errors": [],
                    "exists": True,
                }
            }

            result = write_latest_md(snapshot, out, now=_FIXED_NOW)

            # Action must be "banner"
            self.assertEqual(result["action"], "banner")
            self.assertTrue(out.is_file(), "latest.md banner was not written")
            content = out.read_text(encoding="utf-8")
            # Must contain deprecation signal (per _render_banner heading)
            self.assertIn("deprecated in multi-track context", content)
            # Must list both track IDs in the markdown table
            self.assertIn("track-alpha", content)
            self.assertIn("track-beta", content)

    def test_b2_three_tracks_still_banner(self):
        """Three active tracks → still action='banner'."""
        import tempfile
        with tempfile.TemporaryDirectory(prefix="ss-b2b-") as td:
            out = Path(td) / "latest.md"
            snapshot = {
                "tracks_multibranch": {
                    "tracks": [
                        _active_track(f"track-{i}", f"doc-{i}.md") for i in range(3)
                    ],
                    "branches_scanned": 3,
                    "legacy_count": 0,
                    "errors": [],
                    "exists": True,
                }
            }
            result = write_latest_md(snapshot, out, now=_FIXED_NOW)
            self.assertEqual(result["action"], "banner")


# ─────────────────────────────────────────────────────────────────────────────
# Case C — Backward-compat: multi-track latest.md is readable markdown
# ─────────────────────────────────────────────────────────────────────────────

class TestCaseC_BackwardCompatMarkdownReadable(unittest.TestCase):
    """(c) Old session `cat latest.md` still gets readable markdown;
       collect_handoff main flow (L2 collector) does not crash.
    """

    def _write_multi_track_latest(self, out: Path) -> str:
        """Write a multi-track banner latest.md and return its content."""
        snapshot = {
            "tracks_multibranch": {
                "tracks": [
                    _active_track("track-x", "2026-05-20-x.md"),
                    _active_track("track-y", "2026-05-20-y.md"),
                ],
                "branches_scanned": 2,
                "legacy_count": 0,
                "errors": [],
                "exists": True,
            }
        }
        write_latest_md(snapshot, out, now=_FIXED_NOW)
        return out.read_text(encoding="utf-8")

    def test_multi_track_latest_is_valid_markdown_no_parse_error(self):
        """Content is a non-empty string without binary garbage — human-readable."""
        import tempfile
        with tempfile.TemporaryDirectory(prefix="ss-c-") as td:
            out = Path(td) / "docs" / "handoff" / "latest.md"
            content = self._write_multi_track_latest(out)

            # Basic markdown validity: must be non-empty, valid UTF-8 text
            self.assertIsInstance(content, str)
            self.assertGreater(len(content), 0)
            # Must contain at least one markdown heading (starts with #)
            self.assertTrue(
                any(line.startswith("#") for line in content.splitlines()),
                "Expected at least one markdown heading in latest.md content",
            )
            # Must contain human-readable guidance pointing to state-scanner
            self.assertIn("state-scanner", content)

    def test_multi_track_latest_does_not_crash_collect_handoff(self):
        """collect_handoff (L2) must not raise when latest.md is a multi-track banner.

        The L2 collector reads latest.md to check for the **Latest**: pointer
        pattern.  A banner-format file has no such pointer — that is fine;
        collect_handoff degrades to mtime fallback silently (no exception).
        """
        import tempfile
        with tempfile.TemporaryDirectory(prefix="ss-c2-") as td:
            handoff_dir = Path(td) / "docs" / "handoff"
            handoff_dir.mkdir(parents=True)

            # Write the real handoff doc
            (handoff_dir / "2026-05-20-real-doc.md").write_text(
                "# Real Handoff\n\n## §0\n\nSome content.\n", encoding="utf-8"
            )

            # Write a multi-track banner latest.md (no **Latest**: pointer)
            self._write_multi_track_latest(handoff_dir / "latest.md")

            # Must not raise
            try:
                result = collect_handoff(Path(td))
            except Exception as exc:  # noqa: BLE001
                self.fail(f"collect_handoff raised unexpectedly: {exc!r}")

            # Graceful degradation: collect_handoff returns exists=True
            # (real doc is present) and falls back to mtime; no hard error.
            self.assertTrue(result.data["exists"])
            # The pointer in the banner is not a valid **Latest**: target, so
            # latest_source must be "mtime" fallback (pointer unparseable)
            self.assertEqual(result.data["latest_filename"], "2026-05-20-real-doc.md")

    def test_banner_contains_human_readable_instruction(self):
        """Banner must include a human-readable instruction (not binary/garbage)."""
        import tempfile
        with tempfile.TemporaryDirectory(prefix="ss-c3-") as td:
            out = Path(td) / "latest.md"
            content = self._write_multi_track_latest(out)
            # Instruction: ⚠ + 当前有 ... active tracks
            self.assertIn("active tracks", content)


# ─────────────────────────────────────────────────────────────────────────────
# Case D — Offline red-bar injection
# ─────────────────────────────────────────────────────────────────────────────

class TestCaseD_OfflineRedBarInjection(unittest.TestCase):
    """(d) coordination_fetch.degraded=True → render_track_board first line
       contains ⚠ 离线 identifier and degradation_reason text.
    """

    def _make_degraded_snapshot(self) -> dict:
        return {
            "coordination_fetch": {
                "success": False,
                "cached": True,
                "degraded": True,
                "degradation_reason": "fetch_failed_using_stale_cache",
                "last_fetch_at": "2026-05-20T10:00:00Z",
                "age_seconds": 600,
                "refs_fetched": [],
                "error_kind": "network",
                "error_msg": "git fetch network error (rc=128)",
            },
            "tracks_multibranch": {
                "exists": True,
                "branches_scanned": 1,
                "legacy_count": 0,
                "errors": [],
                "tracks": [
                    {
                        "track_id": "test-track",
                        "owner_container": "devbox-A/sess-001",
                        "phase": "B.2",
                        "status": "active",
                        "updated_at": "2026-05-20T11:55:00Z",
                        "branch": "feature/test",
                        "filename": "2026-05-20-test.md",
                        "legacy": False,
                    }
                ],
            },
        }

    def test_first_line_contains_offline_warning(self):
        """render_track_board first line must contain ⚠ 离线 when degraded=True."""
        snapshot = self._make_degraded_snapshot()
        output = render_track_board(snapshot, now=_FIXED_NOW)
        lines = output.splitlines()

        self.assertGreater(len(lines), 0, "render_track_board returned empty output")
        first_line = lines[0]
        self.assertIn(
            "⚠ 离线",
            first_line,
            f"Expected '⚠ 离线' in first line, got: {first_line!r}",
        )

    def test_first_line_contains_degradation_reason(self):
        """First line must include the degradation_reason string."""
        snapshot = self._make_degraded_snapshot()
        output = render_track_board(snapshot, now=_FIXED_NOW)
        first_line = output.splitlines()[0]
        self.assertIn(
            "fetch_failed_using_stale_cache",
            first_line,
            f"Expected degradation_reason in first line, got: {first_line!r}",
        )

    def test_no_offline_bar_when_not_degraded(self):
        """When degraded=False, output must NOT start with ⚠ 离线."""
        snapshot = {
            "coordination_fetch": {
                "success": True,
                "cached": False,
                "degraded": False,
                "degradation_reason": None,
                "last_fetch_at": "2026-05-20T12:00:00Z",
                "age_seconds": 0,
                "refs_fetched": ["refs/heads/*"],
                "error_kind": None,
                "error_msg": None,
            },
            "tracks_multibranch": {
                "exists": True,
                "branches_scanned": 1,
                "legacy_count": 0,
                "errors": [],
                "tracks": [
                    {
                        "track_id": "ok-track",
                        "owner_container": "devbox-A/sess-002",
                        "phase": "A.2",
                        "status": "active",
                        "updated_at": "2026-05-20T11:59:00Z",
                        "branch": "feature/ok",
                        "filename": "2026-05-20-ok.md",
                        "legacy": False,
                    }
                ],
            },
        }
        output = render_track_board(snapshot, now=_FIXED_NOW)
        first_line = output.splitlines()[0]
        self.assertNotIn(
            "⚠ 离线",
            first_line,
            f"Did not expect offline warning, got: {first_line!r}",
        )

    def test_board_renders_track_data_even_when_degraded(self):
        """Degraded mode must still render track rows (not abort early)."""
        snapshot = self._make_degraded_snapshot()
        output = render_track_board(snapshot, now=_FIXED_NOW)
        self.assertIn("test-track", output)


# ─────────────────────────────────────────────────────────────────────────────
# Case F — coordination-ref fetch-failure yellow advisory (F5, Aria #144)
# ─────────────────────────────────────────────────────────────────────────────

class TestCaseF_CoordinationRefStaleYellowBar(unittest.TestCase):
    """(F5 #144) Fetch 1 ok + Fetch 2 non-benign fail → success=True, degraded=False,
    coordination_ref_present=None + a `coordination_ref_fetch_failed` soft_error in
    snapshot errors[]. The board must surface a non-blocking yellow advisory (the
    all-green board would otherwise hide this half-silent failure). Red bar takes
    precedence when degraded.
    """

    _YELLOW = "协调 ref 未取到"

    def _make_coord_failed_snapshot(self, *, degraded: bool = False) -> dict:
        return {
            "coordination_fetch": {
                "success": not degraded,           # Fetch 1 ok unless degraded
                "cached": False,
                "degraded": degraded,
                "degradation_reason": "fetch_failed_using_stale_cache" if degraded else None,
                "last_fetch_at": "2026-05-20T12:00:00Z",
                "age_seconds": 0,
                "refs_fetched": ["+refs/heads/*:refs/remotes/origin/*"],
                "error_kind": "network" if degraded else None,
                "error_msg": None,
                "coordination_ref_present": None,   # Fetch 2 outcome unknown
            },
            "errors": [
                {
                    "collector": "coordination_fetch",
                    "error": "coordination_ref_fetch_failed",
                    "detail": "network: git fetch timed out after 30s (rc=124)",
                }
            ],
            "tracks_multibranch": {
                "exists": True,
                "branches_scanned": 1,
                "legacy_count": 0,
                "errors": [],
                "tracks": [
                    {
                        "track_id": "cf-track",
                        "owner_container": "devbox-A/sess-003",
                        "phase": "B.2",
                        "status": "active",
                        "updated_at": "2026-05-20T11:58:00Z",
                        "branch": "feature/cf",
                        "filename": "2026-05-20-cf.md",
                        "legacy": False,
                    }
                ],
            },
        }

    def test_yellow_bar_shown_on_coordination_ref_fetch_failed(self):
        """Fetch 2 non-benign fail (not degraded) → yellow advisory present."""
        output = render_track_board(self._make_coord_failed_snapshot(), now=_FIXED_NOW)
        self.assertIn(self._YELLOW, output, f"Expected yellow advisory, got: {output!r}")
        self.assertNotIn("⚠ 离线", output, "Must NOT show the offline red bar (not degraded)")

    def test_yellow_bar_coexists_with_track_rows(self):
        """Advisory must not suppress the track table."""
        output = render_track_board(self._make_coord_failed_snapshot(), now=_FIXED_NOW)
        self.assertIn("cf-track", output)

    def test_red_bar_takes_precedence_when_degraded(self):
        """When degraded, show the red offline bar — NOT the yellow advisory."""
        output = render_track_board(self._make_coord_failed_snapshot(degraded=True), now=_FIXED_NOW)
        self.assertIn("⚠ 离线", output)
        self.assertNotIn(self._YELLOW, output, "Yellow advisory must yield to red bar when degraded")

    def test_no_yellow_bar_when_no_coordination_error(self):
        """Clean snapshot (no coordination_ref_fetch_failed) → no yellow advisory."""
        snapshot = self._make_coord_failed_snapshot()
        snapshot["errors"] = []  # no error → benign / success
        output = render_track_board(snapshot, now=_FIXED_NOW)
        self.assertNotIn(self._YELLOW, output)

    def test_no_yellow_bar_for_unrelated_error(self):
        """An unrelated soft_error must NOT trigger the coordination advisory."""
        snapshot = self._make_coord_failed_snapshot()
        snapshot["errors"] = [{"collector": "git", "error": "git_log_failed", "detail": "x"}]
        output = render_track_board(snapshot, now=_FIXED_NOW)
        self.assertNotIn(self._YELLOW, output)

    def test_no_yellow_bar_for_error_entry_missing_key(self):
        """fail-soft (code-review M-1): an errors[] entry without an `error` key must
        not crash nor trigger the advisory — pins the `.get("error")` graceful path
        against a future regression to `e["error"]`."""
        snapshot = self._make_coord_failed_snapshot()
        snapshot["errors"] = [{"collector": "x", "detail": "no-error-key"}]
        output = render_track_board(snapshot, now=_FIXED_NOW)
        self.assertNotIn(self._YELLOW, output)


# ─────────────────────────────────────────────────────────────────────────────
# Case E — N=20+ remote branches performance baseline
# ─────────────────────────────────────────────────────────────────────────────

_PERF_BRANCH_COUNT = 20
_PERF_ELAPSED_THRESHOLD_S = 30.0  # loose threshold for dev environments

_LEGACY_HANDOFF_TEMPLATE = (
    "# Aria — Session Handoff (branch {branch})\n\n"
    "## §0 Entry\n\nLegacy handoff doc for branch {branch}.\n"
)


class TestCaseE_NbranchPerformanceBaseline(unittest.TestCase):
    """(e) collect_handoff_multibranch on ≥20 remote branches completes < 30s.

    Performance baseline is recorded as a JSON file in tmp_path (not to the
    production .aria/benchmarks/ path — test isolation per TASK-008 spec).
    The baseline JSON schema is verified against the expected structure.
    """

    def test_e_twenty_branch_performance(self):
        """Build 20-branch fixture, time collect_handoff_multibranch, assert < 30s."""
        import tempfile
        with tempfile.TemporaryDirectory(prefix="ss-e-") as td:
            tmp = Path(td)

            # Build 20 branches, each with one legacy handoff doc
            branches = [
                (
                    f"feature/branch-{i:02d}",
                    [(
                        f"docs/handoff/2026-05-20-branch-{i:02d}.md",
                        _LEGACY_HANDOFF_TEMPLATE.format(branch=f"branch-{i:02d}"),
                    )],
                )
                for i in range(_PERF_BRANCH_COUNT)
            ]

            local, _bare = _build_local_repo_with_remote_branches(tmp, branches)

            start = time.perf_counter()
            result = collect_handoff_multibranch(local, remote="origin")
            elapsed = time.perf_counter() - start

            # Verify the collector returned data (not a hard failure)
            self.assertIn("tracks", result.data)
            self.assertGreaterEqual(
                result.data["branches_scanned"],
                _PERF_BRANCH_COUNT,
                f"Expected ≥{_PERF_BRANCH_COUNT} branches scanned, "
                f"got {result.data['branches_scanned']}",
            )

            # Performance assertion (loose: dev environment)
            self.assertLess(
                elapsed,
                _PERF_ELAPSED_THRESHOLD_S,
                f"collect_handoff_multibranch took {elapsed:.2f}s on "
                f"{_PERF_BRANCH_COUNT} branches (threshold: "
                f"{_PERF_ELAPSED_THRESHOLD_S}s)",
            )

            # ── Record baseline JSON in tmp_path (schema validation) ──────────
            # Per TASK-008 spec: production baseline goes to .aria/benchmarks/;
            # here we write to tmp_path only to validate the schema, avoiding
            # pollution of the working tree.
            head_sha = _get_head_sha(local)
            baseline = {
                "task": "TASK-008",
                "branches": _PERF_BRANCH_COUNT,
                "elapsed_seconds": round(elapsed, 3),
                "timestamp": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
                "git_sha": head_sha,
            }
            baseline_path = tmp / "p1-baseline.json"
            baseline_path.write_text(json.dumps(baseline, indent=2), encoding="utf-8")

            # Verify schema: all required keys present, correct types
            loaded = json.loads(baseline_path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["task"], "TASK-008")
            self.assertIsInstance(loaded["branches"], int)
            self.assertIsInstance(loaded["elapsed_seconds"], float)
            self.assertIsInstance(loaded["timestamp"], str)
            self.assertIsInstance(loaded["git_sha"], str)

    def test_e_baseline_json_schema_structure(self):
        """Verify the baseline JSON schema can roundtrip correctly (schema-only)."""
        baseline = {
            "task": "TASK-008",
            "branches": 20,
            "elapsed_seconds": 1.23,
            "timestamp": "2026-05-20T12:00:00+00:00",
            "git_sha": "abc1234",
        }
        dumped = json.dumps(baseline, indent=2)
        loaded = json.loads(dumped)
        self.assertEqual(set(loaded.keys()), {"task", "branches", "elapsed_seconds",
                                               "timestamp", "git_sha"})
        self.assertEqual(loaded["task"], "TASK-008")


def _get_head_sha(repo: Path) -> str:
    """Return the short HEAD SHA of `repo`, or 'unknown' on failure."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short=7", "HEAD"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return r.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


if __name__ == "__main__":
    unittest.main()

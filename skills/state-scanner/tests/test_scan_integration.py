"""scan.py end-to-end integration tests.

Verifies the top-level contract consumers depend on:
- snapshot_schema_version == "1.0"
- All required top-level keys present
- build_snapshot() returns (dict, exit_code)
- JSON output is valid and round-trippable
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from _helpers import tmp_repo, write_file

SCAN_PY = Path(__file__).resolve().parent.parent / "scripts" / "scan.py"


class TestScanPyDirectInvocation(unittest.TestCase):
    def test_help_exits_zero(self):
        p = subprocess.run(
            [sys.executable, str(SCAN_PY), "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(p.returncode, 0)

    def test_scan_minimal_repo(self):
        with tmp_repo() as repo:
            out = repo / "snap.json"
            p = subprocess.run(
                [
                    sys.executable,
                    str(SCAN_PY),
                    "--project-root",
                    str(repo),
                    "--output",
                    str(out),
                ],
                capture_output=True,
                text=True,
            )
            # Exit 0 (all good) or 10 (soft errors acceptable)
            self.assertIn(p.returncode, (0, 10))
            self.assertTrue(out.exists())

            snap = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(snap["snapshot_schema_version"], "1.0")
            self.assertEqual(snap["generated_by"], "scan.py")
            # Spec C: top-level generated_at present, ISO 8601 UTC 'Z' form, and
            # its addition does NOT bump the schema version (additive field).
            self.assertRegex(
                snap["generated_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
            )

    def test_non_git_repo_exit_20(self):
        """Hard precondition: not a git repo → exit 20 (SKILL.md §Exit code contract)."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "snap.json"
            p = subprocess.run(
                [
                    sys.executable,
                    str(SCAN_PY),
                    "--project-root",
                    str(tmp),
                    "--output",
                    str(out),
                ],
                capture_output=True,
                text=True,
            )
            # Should exit 20 (hard precondition fail) or 10 (soft handling)
            self.assertIn(p.returncode, (10, 20))


class TestBuildSnapshotShape(unittest.TestCase):
    """build_snapshot() must produce a stable shape — key drift breaks consumers."""

    def test_required_top_level_keys(self):
        from scan import build_snapshot

        with tmp_repo() as repo:
            snap, _ = build_snapshot(repo)
            required = {
                "snapshot_schema_version",
                "generated_by",
                "project_root",
                "interrupt",
                "git",
                "upm",
                "changes",
                "requirements",
                "openspec",
                "architecture",
                "readme",
                "standards",
                "audit",
                "custom_checks",
                "sync_status",
                "forgejo_config",
                "errors",
            }
            missing = required - set(snap.keys())
            self.assertEqual(missing, set(), msg=f"missing top-level keys: {missing}")

    def test_schema_version_constant(self):
        from scan import SNAPSHOT_SCHEMA_VERSION, build_snapshot

        self.assertEqual(SNAPSHOT_SCHEMA_VERSION, "1.0")
        with tmp_repo() as repo:
            snap, _ = build_snapshot(repo)
            self.assertEqual(snap["snapshot_schema_version"], "1.0")

    def test_errors_is_list(self):
        from scan import build_snapshot

        with tmp_repo() as repo:
            snap, _ = build_snapshot(repo)
            self.assertIsInstance(snap["errors"], list)


class TestIssueStatusOptIn(unittest.TestCase):
    """issue_status appears ONLY when issue_scan.enabled=true (Spec invariant)."""

    def test_issue_status_absent_when_disabled(self):
        from scan import build_snapshot

        with tmp_repo() as repo:
            # No .aria/config.json → issue_scan disabled → no issue_status key
            snap, _ = build_snapshot(repo)
            self.assertNotIn("issue_status", snap)

    def test_issue_status_present_when_enabled(self):
        from scan import build_snapshot

        with tmp_repo() as repo:
            write_file(
                repo / ".aria" / "config.json",
                json.dumps(
                    {"state_scanner": {"issue_scan": {"enabled": True}}}
                ),
            )
            snap, _ = build_snapshot(repo)
            self.assertIn("issue_status", snap)


class TestSnapshotSelfConsistencyAC5(unittest.TestCase):
    """AC-5 (task 2.12, main spec stale-refs-false-parity) — the cross-collector
    invariant the spec's originating accident violated: `tracks_multibranch` listing
    handoff files on `origin/master` that HEAD cannot reach, while `sync_status`
    simultaneously reports `overall_parity: true` with no reason.

    `_run` is mocked at the `scan` module boundary so each case pins ONE predicate;
    building real diverged repos would make the fixtures the thing under test.
    """

    HEALTHY_GIT = {"current_branch": "master", "detached_head": False}
    HEALTHY_TRACKS = {
        "tracks": [{"track_id": "t-1", "filename": "2026-07-19-x.md", "branch": "master"}]
    }
    CLAIMS_PARITY = {"multi_remote": {"overall_parity": True}, "current_branch": {"reason": None}}

    def _mock_run(self, *, ancestor_rc: int, log_rc: int = 0, sha: str = "deadbee0"):
        def fake(cmd, cwd, timeout=5):
            if cmd[:3] == ["git", "log", "-1"]:
                return (log_rc, f"{sha}\n" if log_rc == 0 else "", "")
            if cmd[:2] == ["git", "merge-base"]:
                return (ancestor_rc, "", "")
            return (1, "", "unmocked")
        return fake

    def _check(self, git_data, tracks_data, sync_data, *, ancestor_rc, log_rc=0):
        from unittest import mock

        import scan

        with mock.patch.object(scan, "_run", side_effect=self._mock_run(
            ancestor_rc=ancestor_rc, log_rc=log_rc
        )):
            return scan._check_snapshot_self_consistency(
                Path("/x"), git_data, tracks_data, sync_data
            )

    def test_contradiction_is_reported(self):
        """Unreachable same-branch track + snapshot claiming health = the fingerprint."""
        errs = self._check(
            self.HEALTHY_GIT, self.HEALTHY_TRACKS, self.CLAIMS_PARITY, ancestor_rc=1
        )
        self.assertEqual(len(errs), 1)
        self.assertEqual(errs[0]["kind"], "snapshot_self_contradiction")
        self.assertEqual(errs[0]["tracks"][0]["track_id"], "t-1")

    def test_reachable_track_is_silent(self):
        errs = self._check(
            self.HEALTHY_GIT, self.HEALTHY_TRACKS, self.CLAIMS_PARITY, ancestor_rc=0
        )
        self.assertEqual(errs, [])

    def test_honest_parity_false_is_not_a_contradiction(self):
        """The snapshot already admits it is not in sync — the unreachable tracks are
        the EVIDENCE for that, not a contradiction of it."""
        sync = {"multi_remote": {"overall_parity": False}, "current_branch": {"reason": None}}
        errs = self._check(self.HEALTHY_GIT, self.HEALTHY_TRACKS, sync, ancestor_rc=1)
        self.assertEqual(errs, [])

    def test_non_empty_reason_is_not_a_contradiction(self):
        """AC-5 is a disjunction: a non-empty `reason` also discharges it."""
        sync = {
            "multi_remote": {"overall_parity": True},
            "current_branch": {"reason": "network_timeout"},
        }
        errs = self._check(self.HEALTHY_GIT, self.HEALTHY_TRACKS, sync, ancestor_rc=1)
        self.assertEqual(errs, [])

    def test_other_branch_tracks_are_out_of_scope(self):
        """Scope discipline AC-5 states explicitly: "any commit HEAD cannot reach" would
        flag every repo that merely has other active branches (false-red on healthy
        repos). Only the HEAD branch's own tracks qualify."""
        tracks = {
            "tracks": [
                {"track_id": "t-2", "filename": "2026-07-19-y.md", "branch": "feature/other"}
            ]
        }
        errs = self._check(self.HEALTHY_GIT, tracks, self.CLAIMS_PARITY, ancestor_rc=1)
        self.assertEqual(errs, [])

    def test_detached_head_makes_no_claim(self):
        git_data = {"current_branch": "master", "detached_head": True}
        errs = self._check(git_data, self.HEALTHY_TRACKS, self.CLAIMS_PARITY, ancestor_rc=1)
        self.assertEqual(errs, [])

    def test_unresolvable_commit_makes_no_claim(self):
        """`git log` cannot name the introducing commit ⇒ no evidence in either
        direction ⇒ stay silent rather than guess (fail-toward-quiet on unknowns,
        since the loud path here would be a false accusation of inconsistency)."""
        errs = self._check(
            self.HEALTHY_GIT, self.HEALTHY_TRACKS, self.CLAIMS_PARITY,
            ancestor_rc=1, log_rc=1,
        )
        self.assertEqual(errs, [])

    def test_missing_tracks_block_is_tolerated(self):
        errs = self._check(self.HEALTHY_GIT, {}, self.CLAIMS_PARITY, ancestor_rc=1)
        self.assertEqual(errs, [])


if __name__ == "__main__":
    unittest.main()

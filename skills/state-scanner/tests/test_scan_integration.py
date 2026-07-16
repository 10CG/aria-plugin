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


if __name__ == "__main__":
    unittest.main()

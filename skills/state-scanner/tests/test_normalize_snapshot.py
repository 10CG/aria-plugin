"""T7.0 normalize_snapshot unit + integration tests."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

# Ensure scripts/ on path so `normalize_snapshot` imports cleanly
_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from normalize_snapshot import (  # noqa: E402
    DROP_KEYS,
    EPHEMERAL_PATH_KEYS,
    TIMESTAMP_KEYS,
    _SHA_RE,
    normalize,
)

SCAN_PY = _SCRIPTS / "scan.py"
NORMALIZE_PY = _SCRIPTS / "normalize_snapshot.py"


class TestRules(unittest.TestCase):
    """Each rule exercised individually with minimal input."""

    def test_rule_1_sorted_keys(self):
        out = normalize({"z": 1, "a": 2, "m": 3})
        self.assertEqual(list(out.keys()), ["a", "m", "z"])

    def test_rule_2_abs_path_to_sentinel(self):
        out = normalize({"project_root": "/home/dev/Aria", "git": {"where": "/home/dev/Aria/aria"}})
        self.assertEqual(out["project_root"], "<project_root>")
        self.assertEqual(out["git"]["where"], "<project_root>/aria")

    def test_rule_3_timestamp_whitelist(self):
        for key in ["fetched_at", "last_updated", "timestamp", "generated_at"]:
            out = normalize({key: "2026-04-24T10:00Z"})
            self.assertEqual(out[key], "<timestamp>")

    def test_rule_3_non_whitelisted_time_string_preserved(self):
        # A non-whitelisted key that happens to hold a timestamp-ish string
        # is preserved verbatim.
        out = normalize({"random_field": "2026-04-24T10:00Z"})
        self.assertEqual(out["random_field"], "2026-04-24T10:00Z")

    def test_rule_4_cache_path_scrubbed(self):
        out = normalize({"issue_status": {"cache_path": "/home/x/.aria/cache/issues.json"}})
        self.assertEqual(out["issue_status"]["cache_path"], "<cache_path>")

    def test_rule_4_output_NOT_scrubbed(self):
        """custom_checks.results[*].output is a contract field, must survive."""
        out = normalize(
            {"custom_checks": {"results": [{"name": "x", "output": "OK"}]}}
        )
        self.assertEqual(out["custom_checks"]["results"][0]["output"], "OK")

    def test_rule_5_sha_abbreviation(self):
        full = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
        out = normalize({"commit": full})
        self.assertEqual(out["commit"], full[:7])

    def test_rule_5_short_sha_preserved(self):
        out = normalize({"commit": "a1b2c3d"})
        self.assertEqual(out["commit"], "a1b2c3d")

    def test_rule_6_float_precision(self):
        out = normalize({"val": 1.000000001234567})
        self.assertEqual(out["val"], round(1.000000001234567, 6))

    def test_rule_7_null_dropped(self):
        out = normalize({"present": "x", "absent": None})
        self.assertIn("present", out)
        self.assertNotIn("absent", out)

    def test_rule_8_errors_sorted(self):
        out = normalize(
            {
                "errors": [
                    {"error": "z_err", "detail": "d"},
                    {"error": "a_err", "detail": "d"},
                ]
            }
        )
        self.assertEqual(out["errors"][0]["error"], "a_err")

    def test_rule_9_submodules_sorted(self):
        out = normalize(
            {
                "sync_status": {
                    "submodules": [{"path": "z"}, {"path": "a"}, {"path": "m"}]
                }
            }
        )
        paths = [sm["path"] for sm in out["sync_status"]["submodules"]]
        self.assertEqual(paths, ["a", "m", "z"])

    def test_rule_9_remotes_sorted(self):
        out = normalize({"remotes": [{"name": "origin"}, {"name": "github"}]})
        names = [r["name"] for r in out["remotes"]]
        self.assertEqual(names, ["github", "origin"])

    def test_rule_10_recent_commits_dropped(self):
        out = normalize({"git": {"recent_commits": [{"sha": "abc", "subject": "x"}]}})
        self.assertNotIn("recent_commits", out["git"])

    def test_rule_11_followups_raw_row_dropped(self):
        """TX.1.a: followups[*].raw_row dropped to stabilize canonical form."""
        out = normalize(
            {
                "upm": {
                    "followups": [
                        {
                            "row_index": 1,
                            "priority": "P1",
                            "item": "ship state-scanner-inter-cycle-surfacing",
                            "raw_row": "| 1 | P1 | ship ... | issue#85 | tracking | next |",
                        }
                    ]
                }
            }
        )
        row = out["upm"]["followups"][0]
        self.assertNotIn("raw_row", row)
        # Other fields must survive the DROP rule.
        self.assertEqual(row["priority"], "P1")
        self.assertEqual(row["row_index"], 1)

    def test_rule_11_handoff_doc_raw_match_dropped(self):
        """TX.1.a: handoff_doc.raw_match dropped (verbatim markdown line)."""
        out = normalize(
            {
                "upm": {
                    "handoff_doc": {
                        "path": "docs/handoff/2026-05-08-session-handoff.md",
                        "exists": True,
                        "raw_match": "> 🚪 Next session 入口: 见 [docs/handoff/2026-05-08-session-handoff.md](docs/handoff/2026-05-08-session-handoff.md)",
                    }
                }
            }
        )
        hd = out["upm"]["handoff_doc"]
        self.assertNotIn("raw_match", hd)
        self.assertEqual(hd["path"], "docs/handoff/2026-05-08-session-handoff.md")
        self.assertTrue(hd["exists"])

    def test_rule_11_priority_items_preserved(self):
        """TX.1.a: priority_items[] is NOT dropped — its content (id/file) is
        intentionally part of the canonical surface for cross-cycle diffs."""
        out = normalize(
            {
                "requirements": {
                    "stories": {
                        "priority_items": [
                            {
                                "id": "US-076",
                                "status_normalized": "in_progress",
                                "raw_status": "In Progress: M3 closeout",
                                "file": "docs/requirements/user-stories/US-076.md",
                            }
                        ]
                    }
                }
            }
        )
        items = out["requirements"]["stories"]["priority_items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], "US-076")


class TestEdgeCases(unittest.TestCase):
    def test_nan_rejected(self):
        with self.assertRaises(ValueError):
            normalize({"val": float("nan")})

    def test_inf_rejected(self):
        with self.assertRaises(ValueError):
            normalize({"val": float("inf")})

    def test_empty_dict(self):
        self.assertEqual(normalize({}), {})

    def test_deeply_nested(self):
        out = normalize(
            {"a": {"b": {"c": {"d": {"timestamp": "2026-04-24"}}}}}
        )
        self.assertEqual(out["a"]["b"]["c"]["d"]["timestamp"], "<timestamp>")


class TestConstants(unittest.TestCase):
    def test_output_not_in_ephemeral_keys(self):
        """Regression: v1 of the normalizer wrongly scrubbed `output`,
        corrupting custom_checks.results[*].output. This test pins the fix."""
        self.assertNotIn("output", EPHEMERAL_PATH_KEYS)

    def test_all_ephemeral_sentinels_angle_bracketed(self):
        for v in EPHEMERAL_PATH_KEYS.values():
            self.assertTrue(v.startswith("<") and v.endswith(">"))

    def test_timestamp_keys_are_leaves(self):
        # Common audit/state leaves
        for k in ("fetched_at", "last_updated", "timestamp", "last_active_at", "generated_at"):
            self.assertIn(k, TIMESTAMP_KEYS)

    def test_recent_commits_in_drop_keys(self):
        self.assertIn("recent_commits", DROP_KEYS)

    def test_inter_cycle_raw_keys_in_drop_keys(self):
        """TX.1.a: raw_row + raw_match pinned in DROP_KEYS."""
        self.assertIn("raw_row", DROP_KEYS)
        self.assertIn("raw_match", DROP_KEYS)


class TestStabilityIntegration(unittest.TestCase):
    """T7.2: two consecutive scan.py runs must produce byte-identical
    normalized output. This is the canonical drift-detection test."""

    def test_two_consecutive_runs_diff_zero(self):
        import tempfile

        with tempfile.TemporaryDirectory(prefix="ss-stability-") as tmp:
            tmp_dir = Path(tmp)
            # Use the live Aria project as the scan target
            project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
            snap1 = tmp_dir / "snap1.json"
            snap2 = tmp_dir / "snap2.json"
            norm1 = tmp_dir / "norm1.json"
            norm2 = tmp_dir / "norm2.json"

            for snap in (snap1, snap2):
                r = subprocess.run(
                    [
                        sys.executable,
                        str(SCAN_PY),
                        "--project-root",
                        str(project_root),
                        "--output",
                        str(snap),
                    ],
                    capture_output=True,
                    text=True,
                )
                self.assertIn(r.returncode, (0, 10), msg=f"scan.py failed: {r.stderr}")

            for snap, norm in [(snap1, norm1), (snap2, norm2)]:
                r = subprocess.run(
                    [sys.executable, str(NORMALIZE_PY), str(snap), "--output", str(norm)],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(r.returncode, 0, msg=f"normalize failed: {r.stderr}")

            n1 = norm1.read_text(encoding="utf-8")
            n2 = norm2.read_text(encoding="utf-8")
            self.assertEqual(
                n1, n2, msg="normalized snapshots drifted between consecutive runs"
            )


if __name__ == "__main__":
    unittest.main()

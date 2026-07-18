"""9.6 (main spec state-scanner-stale-refs-false-parity, Phase 3 QA):
`validate_schema_doc.py --offline` unit coverage.

Before this fix, `_run_scan()` invoked `scan.py` with no explicit env
override — every validation run (CI, pre-commit, or ad hoc) paid a full
F3′ `remote_refresh` network fetch across every enforced remote plus a live
`issue_scan` API call, even though this validator only checks TOP-LEVEL key
presence (module docstring "Scope limitation") — a value offline mode does
not affect (every collector still emits its top-level block, just with
`not_attempted`/cached leaves).

These tests mock `subprocess.run` so they exercise the real `_run_scan()`
env-propagation logic without needing network access or git-repo scaffolding
(no `tmp_repo()` — `_run_scan` never touches the filesystem beyond what
`subprocess.run` mocked out).
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import validate_schema_doc as vsd  # noqa: E402


def _fake_completed(stdout_obj):
    class _Result:
        returncode = 0
        stdout = json.dumps(stdout_obj)
        stderr = ""

    return _Result()


class TestRunScanOfflineFlag(unittest.TestCase):
    def test_offline_true_sets_env_var(self):
        captured = {}

        def fake_run(cmd, capture_output, text, timeout, check, env):
            captured["env"] = env
            return _fake_completed({"a": 1})

        with mock.patch.object(vsd.subprocess, "run", side_effect=fake_run):
            vsd._run_scan(Path("/tmp/whatever"), offline=True)

        self.assertEqual(captured["env"].get("ARIA_SCAN_OFFLINE"), "1")

    def test_offline_false_does_not_force_env_var(self):
        """Default (offline=False) must not silently force offline mode on
        callers who want a real live validation — it must also not strip an
        ARIA_SCAN_OFFLINE the caller's own environment already set (parent
        env is passed through verbatim, just not augmented)."""
        captured = {}

        def fake_run(cmd, capture_output, text, timeout, check, env):
            captured["env"] = env
            return _fake_completed({"a": 1})

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ARIA_SCAN_OFFLINE", None)
            with mock.patch.object(vsd.subprocess, "run", side_effect=fake_run):
                vsd._run_scan(Path("/tmp/whatever"), offline=False)

        self.assertNotIn("ARIA_SCAN_OFFLINE", captured["env"])

    def test_offline_default_is_false(self):
        """`_run_scan(project_root)` with no explicit `offline` kwarg must
        keep the pre-9.6 (non-offline) default — this is a backward-compat
        lock: any future caller that forgets to pass `offline=` must not
        silently start skipping network validation."""
        captured = {}

        def fake_run(cmd, capture_output, text, timeout, check, env):
            captured["env"] = env
            return _fake_completed({"a": 1})

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ARIA_SCAN_OFFLINE", None)
            with mock.patch.object(vsd.subprocess, "run", side_effect=fake_run):
                vsd._run_scan(Path("/tmp/whatever"))  # no offline kwarg

        self.assertNotIn("ARIA_SCAN_OFFLINE", captured["env"])

    def test_cli_offline_flag_parsed_and_forwarded(self):
        """--offline on the CLI must reach `_run_scan` as `offline=True`."""
        captured = {}

        def fake_run_scan(project_root, offline=False):
            captured["offline"] = offline
            captured["project_root"] = project_root
            return {"k": "v"}

        with mock.patch.object(vsd, "_run_scan", side_effect=fake_run_scan):
            with mock.patch.object(
                vsd, "_find_schema_doc", return_value=Path("/tmp/schema.md")
            ):
                with mock.patch.object(vsd, "_read_schema_doc_version", return_value="1.0"):
                    with mock.patch.object(vsd, "_read_scan_constant", return_value="1.0"):
                        with mock.patch.object(vsd, "_read_schema_doc_top_keys", return_value={"k"}):
                            rc = vsd.main(
                                ["--project-root", "/tmp/proj", "--offline", "--quiet"]
                            )

        self.assertEqual(rc, 0)
        self.assertTrue(captured["offline"])

    def test_cli_without_offline_flag_defaults_false(self):
        captured = {}

        def fake_run_scan(project_root, offline=False):
            captured["offline"] = offline
            return {"k": "v"}

        with mock.patch.object(vsd, "_run_scan", side_effect=fake_run_scan):
            with mock.patch.object(
                vsd, "_find_schema_doc", return_value=Path("/tmp/schema.md")
            ):
                with mock.patch.object(vsd, "_read_schema_doc_version", return_value="1.0"):
                    with mock.patch.object(vsd, "_read_scan_constant", return_value="1.0"):
                        with mock.patch.object(vsd, "_read_schema_doc_top_keys", return_value={"k"}):
                            vsd.main(["--project-root", "/tmp/proj", "--quiet"])

        self.assertFalse(captured["offline"])


if __name__ == "__main__":
    unittest.main()

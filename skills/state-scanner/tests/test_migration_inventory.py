#!/usr/bin/env python3
"""T3b label-migration inventory warning in phase1_gate and release_gate (S1 semantics).

owner-container-identity-key-and-collision-parser TASK-008 (SC-3 共同臂).

S1 = pure inventory: when ``~/.aria/container-id`` carries a non-empty
``label``, both gates report ``label_migration = {label, active_claims}`` (the
number of ACTIVE claims filed under ``claims/<label>/``) and log a warning.
No suppression, no behaviour change.  (S2 turns the same check into a release
gate — reserved TASK-028.)
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

_SS_ROOT = Path(__file__).resolve().parent.parent
if str(_SS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SS_ROOT))
if str(_SS_ROOT / "scripts") not in sys.path:
    sys.path.append(str(_SS_ROOT / "scripts"))

from lib.claim_schema import ClaimRecord  # noqa: E402
from lib.claim_lifecycle import label_migration_inventory  # noqa: E402  (RED on 7dd0135: ImportError)
from lib.coordination_ref import ReadClaimsResult  # noqa: E402
import phase1_gate as g  # noqa: E402
import release_gate as rg  # noqa: E402


def _claim(track, container, status="active", owner="me"):
    return ClaimRecord(
        schema_version="1", track_id=track, owner=owner, container=container,
        session="s-1", phase="B", status=status,
        claimed_at="2026-09-01T00:00:00Z", heartbeat_at="2026-09-01T00:00:00Z",
    )


_CLAIMS = [
    _claim("t1", "devbox-A"),
    _claim("t2", "devbox-A"),
    _claim("t3", "devbox-A", status="done"),
    _claim("t4", "aaaa1111"),
]


class TestInventoryHelper(unittest.TestCase):
    def test_empty_label_is_none(self):
        self.assertIsNone(label_migration_inventory("", _CLAIMS))
        self.assertIsNone(label_migration_inventory(None, _CLAIMS))  # type: ignore[arg-type]

    def test_counts_only_active_claims_under_label(self):
        inv = label_migration_inventory("devbox-A", _CLAIMS)
        self.assertEqual(inv["label"], "devbox-A")
        self.assertEqual(inv["active_claims"], 2)
        self.assertIn("devbox-A", inv["message"])
        self.assertIn("2", inv["message"])

    def test_label_with_no_claims_still_reports_zero(self):
        # S1: no suppression — label set means the warning surfaces even at 0.
        inv = label_migration_inventory("laptop", _CLAIMS)
        self.assertEqual(inv["active_claims"], 0)


class TestPhase1GateWiring(unittest.TestCase):
    def _run_cli(self, label):
        fake_result = mock.Mock(outcome="passed", track_id="t")
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(g, "_gated", return_value=fake_result), \
                mock.patch.object(g, "_gate_result_to_dict", return_value={"outcome": "passed"}), \
                mock.patch.object(g, "get_container_label", return_value=label), \
                mock.patch.object(g, "read_claims", return_value=ReadClaimsResult(claims=_CLAIMS, errors=[], ref_exists=True)):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = g._main(["--raw-track-id", "t", "--phase", "B", "--repo-path", tmp, "--no-push"])
        return rc, json.loads(buf.getvalue())

    def test_label_set_emits_label_migration(self):
        rc, out = self._run_cli("devbox-A")
        self.assertEqual(rc, 0)
        self.assertEqual(out["label_migration"], {"label": "devbox-A", "active_claims": 2, "message": out["label_migration"]["message"]})

    def test_label_empty_emits_null(self):
        _rc, out = self._run_cli("")
        self.assertIn("label_migration", out)
        self.assertIsNone(out["label_migration"])


class TestReleaseGateWiring(unittest.TestCase):
    def _run(self, label):
        fetch_ok = mock.Mock(success=True, error_kind=None)
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(rg, "fetch_coordination_ref", return_value=fetch_ok), \
                mock.patch.object(rg, "get_container_label", return_value=label), \
                mock.patch.object(rg, "read_claims", return_value=ReadClaimsResult(claims=_CLAIMS, errors=[], ref_exists=True)):
            return rg.run_release(None, repo_path=Path(tmp), no_push=True)

    def test_label_set_emits_label_migration(self):
        result = self._run("devbox-A")
        self.assertEqual(result["label_migration"]["label"], "devbox-A")
        self.assertEqual(result["label_migration"]["active_claims"], 2)

    def test_label_empty_emits_null(self):
        result = self._run("")
        self.assertIsNone(result["label_migration"])


if __name__ == "__main__":
    unittest.main()

"""Tests for Part C/B1 of coordination-claim-lifecycle-and-overlap.

Covers:
  - claim_lifecycle.release_claim_by_track (defect c core — WIP 6f4bbe4, ported
    from the original pytest-style bare functions to unittest so run_tests.py's
    stdlib discovery actually executes them; bare functions were silently
    skipped by unittest.TestLoader)
  - "abandoned" as a writable/parseable status (schema C-1)
  - linked_issue schema roundtrip + preservation through lifecycle (B1-1/B1-2)
  - coordination_ref.apply_tree_edits (C-2)
  - gc.archive_done_claims real git write (C-3a) + gc.sweep_stale_active (C-3b)
  - collision.linked_issue_overlaps (B1-3)
  - release_gate CLI I/O contract (C-4)
"""
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SKILL_ROOT = str(Path(__file__).resolve().parents[1])
if _SKILL_ROOT not in sys.path:
    sys.path.insert(0, _SKILL_ROOT)

from lib.coordination_ref import (  # noqa: E402
    bootstrap,
    read_claims,
    apply_tree_edits,
)
from lib.claim_lifecycle import (  # noqa: E402
    acquire_claim,
    heartbeat,
    release_claim_by_track,
)
from lib.claim_schema import parse_claim, serialize_claim, ClaimRecord  # noqa: E402
from lib.collision import linked_issue_overlaps  # noqa: E402
from lib.gc import archive_done_claims, sweep_stale_active  # noqa: E402
from lib.track_id import derive_track_id  # noqa: E402
from lib.identity import Identity  # noqa: E402

_RELEASE_GATE = Path(_SKILL_ROOT) / "scripts" / "release_gate.py"


def _sh(cmd, cwd):
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True)


def _fresh_repo() -> Path:
    d = tempfile.mkdtemp()
    repo = Path(d)
    _sh(["git", "init", "-q"], d)
    _sh(["git", "config", "user.email", "t@t"], d)
    _sh(["git", "config", "user.name", "t"], d)
    (repo / "x").write_text("x")
    _sh(["git", "add", "-A"], d)
    _sh(["git", "commit", "-qm", "init"], d)
    bootstrap(repo, push=False)
    return repo


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class TestReleaseByTrack(unittest.TestCase):
    """Ported WIP tests (defect c core)."""

    def test_release_from_fresh_session(self):
        repo = _fresh_repo()
        idA = Identity(owner="alice", container_id="cA", session_id="s1")
        acquire_claim(derive_track_id("carry-my-work.v2"), "B", identity=idA, repo_path=repo)

        ship = Identity(owner="alice", container_id="cA", session_id="s2-fresh")
        rel = release_claim_by_track(
            "carry-my-work.v2", status="done", identity=ship, repo_path=repo
        )
        self.assertTrue(rel.success)
        self.assertEqual(rel.record.status, "done")
        claims = read_claims(repo).claims
        self.assertEqual(
            [c.status for c in claims if c.container == "cA"], ["done"]
        )

    def test_release_idempotent(self):
        repo = _fresh_repo()
        idA = Identity(owner="alice", container_id="cA", session_id="s1")
        acquire_claim(derive_track_id("carry-x"), "B", identity=idA, repo_path=repo)
        ship = Identity(owner="alice", container_id="cA", session_id="s2")
        self.assertTrue(
            release_claim_by_track("carry-x", identity=ship, repo_path=repo).success
        )
        self.assertEqual(
            release_claim_by_track("carry-x", identity=ship, repo_path=repo).error,
            "claim_not_found",
        )

    def test_release_container_isolation(self):
        repo = _fresh_repo()
        norm = derive_track_id("carry-shared")
        acquire_claim(norm, "B", identity=Identity("alice", "cA", "s1"), repo_path=repo)
        acquire_claim(norm, "B", identity=Identity("bob", "cB", "s9"), repo_path=repo)
        release_claim_by_track(
            "carry-shared", identity=Identity("alice", "cA", "sx"), repo_path=repo
        )
        claims = {c.container: c.status for c in read_claims(repo).claims}
        self.assertEqual(claims["cA"], "done")
        self.assertEqual(claims["cB"], "active")

    def test_release_invalid_status(self):
        repo = _fresh_repo()
        r = release_claim_by_track(
            "carry-x", status="bogus", identity=Identity("a", "c", "s"), repo_path=repo
        )
        self.assertFalse(r.success)
        self.assertEqual(r.error, "invalid_status")

    def test_release_abandoned_roundtrips(self):
        """C-1 regression lock: before Part C, a written 'abandoned' claim was
        dropped by parse_claim on read-back (not in STATUS_WRITABLE)."""
        repo = _fresh_repo()
        idA = Identity(owner="alice", container_id="cA", session_id="s1")
        acquire_claim(derive_track_id("carry-dead"), "B", identity=idA, repo_path=repo)
        rel = release_claim_by_track(
            "carry-dead",
            status="abandoned",
            identity=Identity("alice", "cA", "s2"),
            repo_path=repo,
        )
        self.assertTrue(rel.success)
        rr = read_claims(repo)
        self.assertEqual([c.status for c in rr.claims], ["abandoned"])
        self.assertEqual(rr.errors, [])  # NOT dropped as claim_schema_invalid


class TestLinkedIssueSchema(unittest.TestCase):
    """B1-1: additive schema field + backward compat."""

    _BASE = {
        "schema_version": "1",
        "track_id": "t1",
        "owner": "o",
        "container": "c",
        "session": "s",
        "phase": "B",
        "status": "active",
        "claimed_at": "2026-07-11T00:00:00Z",
        "heartbeat_at": "2026-07-11T00:00:00Z",
    }

    def test_old_claim_without_linked_issue_parses(self):
        rec = parse_claim(dict(self._BASE))
        self.assertIsNotNone(rec)
        self.assertIsNone(rec.linked_issue)

    def test_linked_issue_roundtrip(self):
        raw = dict(self._BASE, linked_issue="10CG/Aria#160")
        rec = parse_claim(raw)
        self.assertEqual(rec.linked_issue, "10CG/Aria#160")
        out = serialize_claim(rec)
        self.assertEqual(out["linked_issue"], "10CG/Aria#160")

    def test_serialize_omits_none_linked_issue(self):
        rec = parse_claim(dict(self._BASE))
        self.assertNotIn("linked_issue", serialize_claim(rec))

    def test_linked_issue_wrong_type_invalid(self):
        self.assertIsNone(parse_claim(dict(self._BASE, linked_issue=160)))

    def test_lifecycle_preserves_linked_issue(self):
        """B1-2: acquire stores it; heartbeat + release must not drop it."""
        repo = _fresh_repo()
        idA = Identity(owner="alice", container_id="cA", session_id="s1")
        acq = acquire_claim(
            "t-li", "B", identity=idA, repo_path=repo, linked_issue="X#1"
        )
        self.assertEqual(acq.record.linked_issue, "X#1")
        hb = heartbeat("t-li", identity=idA, repo_path=repo)
        self.assertEqual(hb.record.linked_issue, "X#1")
        rel = release_claim_by_track(
            "t-li", identity=Identity("alice", "cA", "s2"), repo_path=repo
        )
        self.assertEqual(rel.record.linked_issue, "X#1")


class TestLinkedIssueOverlaps(unittest.TestCase):
    """B1-3: pure-function advisory."""

    @staticmethod
    def _claim(track, container, status="active", linked=None, owner="o"):
        return ClaimRecord(
            schema_version="1",
            track_id=track,
            owner=owner,
            container=container,
            session="s-" + container,
            phase="B",
            status=status,
            claimed_at="2026-07-11T00:00:00Z",
            heartbeat_at="2026-07-11T00:00:00Z",
            linked_issue=linked,
        )

    def test_same_issue_different_track_flagged(self):
        claims = [
            self._claim("mine", "cA", linked="A#7"),
            self._claim("theirs", "cB", linked="A#7"),
        ]
        out = linked_issue_overlaps(claims, "mine", "A#7")
        self.assertEqual([d["track_id"] for d in out], ["theirs"])

    def test_same_track_not_flagged(self):
        claims = [self._claim("mine", "cB", linked="A#7")]
        self.assertEqual(linked_issue_overlaps(claims, "mine", "A#7"), [])

    def test_terminal_and_no_issue_ignored(self):
        claims = [
            self._claim("t1", "cB", status="done", linked="A#7"),
            self._claim("t2", "cC", status="abandoned", linked="A#7"),
            self._claim("t3", "cD", linked=None),
            self._claim("t4", "cE", linked="B#8"),
        ]
        self.assertEqual(linked_issue_overlaps(claims, "mine", "A#7"), [])

    def test_none_own_issue_short_circuits(self):
        claims = [self._claim("theirs", "cB", linked="A#7")]
        self.assertEqual(linked_issue_overlaps(claims, "mine", None), [])


class TestApplyTreeEdits(unittest.TestCase):
    """C-2 primitive."""

    def test_batch_add_remove_single_commit(self):
        repo = _fresh_repo()
        r1 = apply_tree_edits(
            [("add", "claims/cA/s1.yaml", "a: 1\n"), ("add", "claims/cB/s2.yaml", "b: 2\n")],
            repo,
        )
        self.assertTrue(r1.success)
        self.assertEqual(r1.edit_count, 2)
        r2 = apply_tree_edits(
            [("remove", "claims/cA/s1.yaml"), ("add", "archive/2026-07/cA/s1.yaml", "a: 1\n")],
            repo,
        )
        self.assertTrue(r2.success)
        out = subprocess.run(
            ["git", "-C", str(repo), "ls-tree", "-r", "--name-only", "refs/aria/coordination"],
            capture_output=True,
            text=True,
        ).stdout.split()
        self.assertIn("archive/2026-07/cA/s1.yaml", out)
        self.assertIn("claims/cB/s2.yaml", out)
        self.assertNotIn("claims/cA/s1.yaml", out)

    def test_empty_edits_noop(self):
        repo = _fresh_repo()
        r = apply_tree_edits([], repo)
        self.assertTrue(r.success)
        self.assertEqual(r.edit_count, 0)
        self.assertEqual(r.commit_sha, "")

    def test_invalid_shapes_and_paths(self):
        repo = _fresh_repo()
        self.assertEqual(apply_tree_edits([("bogus", "p")], repo).error, "invalid_edit")
        self.assertEqual(apply_tree_edits([("add", "p")], repo).error, "invalid_edit")
        self.assertEqual(
            apply_tree_edits([("remove", "../escape.yaml")], repo).error, "invalid_path"
        )
        self.assertEqual(
            apply_tree_edits([("add", "/abs.yaml", "x")], repo).error, "invalid_path"
        )


class TestGcRealWrite(unittest.TestCase):
    """C-3a: archive_done_claims actually moves files now."""

    def _done_claim_repo(self, claimed_days_ago: int):
        repo = _fresh_repo()
        now = datetime.now(timezone.utc)
        old = _iso(now - timedelta(days=claimed_days_ago))
        rec = ClaimRecord(
            schema_version="1",
            track_id="t-done",
            owner="alice",
            container="cA",
            session="s1",
            phase="D",
            status="done",
            claimed_at=old,
            heartbeat_at=old,
        )
        import yaml

        apply_tree_edits(
            [("add", "claims/cA/s1.yaml", yaml.safe_dump(serialize_claim(rec)))], repo
        )
        return repo, now

    def test_write_moves_claim_to_archive(self):
        repo, now = self._done_claim_repo(claimed_days_ago=10)
        result = archive_done_claims(repo, now=now, dry_run=False)
        self.assertEqual(result.archived_count, 1)
        self.assertEqual(result.errors, [])
        rr = read_claims(repo, include_archive=True)
        paths = subprocess.run(
            ["git", "-C", str(repo), "ls-tree", "-r", "--name-only", "refs/aria/coordination"],
            capture_output=True,
            text=True,
        ).stdout.split()
        self.assertNotIn("claims/cA/s1.yaml", paths)
        self.assertTrue(any(p.startswith("archive/") for p in paths))
        self.assertEqual(len(rr.claims), 1)  # archived record still parseable

    def test_dry_run_writes_nothing(self):
        repo, now = self._done_claim_repo(claimed_days_ago=10)
        result = archive_done_claims(repo, now=now, dry_run=True)
        self.assertEqual(result.archived_count, 1)
        paths = subprocess.run(
            ["git", "-C", str(repo), "ls-tree", "-r", "--name-only", "refs/aria/coordination"],
            capture_output=True,
            text=True,
        ).stdout.split()
        self.assertIn("claims/cA/s1.yaml", paths)

    def test_within_retention_untouched(self):
        repo, now = self._done_claim_repo(claimed_days_ago=2)
        result = archive_done_claims(repo, now=now, dry_run=False)
        self.assertEqual(result.archived_count, 0)

    def test_abandoned_also_archived(self):
        """abandoned (sweep 产物) 与 done 走同一 retention 归档路径 —
        否则 abandoned 在 claims/ 树永久累积 (defect c 复形)."""
        repo = _fresh_repo()
        now = datetime.now(timezone.utc)
        old = _iso(now - timedelta(days=10))
        rec = ClaimRecord(
            schema_version="1",
            track_id="t-ab",
            owner="bot",
            container="cB",
            session="s1",
            phase="B",
            status="abandoned",
            claimed_at=old,
            heartbeat_at=old,
        )
        import yaml

        apply_tree_edits(
            [("add", "claims/cB/s1.yaml", yaml.safe_dump(serialize_claim(rec)))], repo
        )
        result = archive_done_claims(repo, now=now, dry_run=False)
        self.assertEqual(result.archived_count, 1)
        self.assertEqual(result.errors, [])


class TestSweepStaleActive(unittest.TestCase):
    """C-3b."""

    def test_sweep_stale_cross_container_fresh_untouched(self):
        repo = _fresh_repo()
        now = datetime.now(timezone.utc)
        stale_ts = now - timedelta(hours=2)
        acquire_claim(
            "t-stale", "B", identity=Identity("bot", "cBOT", "s1"),
            repo_path=repo, now=stale_ts,
        )
        acquire_claim(
            "t-fresh", "B", identity=Identity("me", "cME", "s2"),
            repo_path=repo, now=now,
        )
        result = sweep_stale_active(repo, now=now)
        self.assertEqual(result.swept, ["cBOT/s1"])
        statuses = {c.container: c.status for c in read_claims(repo).claims}
        self.assertEqual(statuses["cBOT"], "abandoned")
        self.assertEqual(statuses["cME"], "active")

    def test_sweep_preserves_last_alive_heartbeat(self):
        repo = _fresh_repo()
        now = datetime.now(timezone.utc)
        stale_ts = now - timedelta(hours=3)
        acquire_claim(
            "t-stale", "B", identity=Identity("bot", "cBOT", "s1"),
            repo_path=repo, now=stale_ts,
        )
        sweep_stale_active(repo, now=now)
        (rec,) = read_claims(repo).claims
        self.assertEqual(rec.heartbeat_at, _iso(stale_ts))

    def test_sweep_dry_run(self):
        repo = _fresh_repo()
        now = datetime.now(timezone.utc)
        acquire_claim(
            "t-stale", "B", identity=Identity("bot", "cBOT", "s1"),
            repo_path=repo, now=now - timedelta(hours=2),
        )
        result = sweep_stale_active(repo, now=now, dry_run=True)
        self.assertEqual(result.swept_count, 1)
        (rec,) = read_claims(repo).claims
        self.assertEqual(rec.status, "active")

    def test_sweep_ignores_terminal(self):
        repo = _fresh_repo()
        now = datetime.now(timezone.utc)
        old = now - timedelta(hours=2)
        acquire_claim(
            "t-x", "B", identity=Identity("a", "cA", "s1"), repo_path=repo, now=old
        )
        release_claim_by_track(
            "t-x", identity=Identity("a", "cA", "s2"), repo_path=repo, now=old
        )
        result = sweep_stale_active(repo, now=now)
        self.assertEqual(result.swept_count, 0)


class TestReleaseGateCli(unittest.TestCase):
    """C-4: subprocess I/O contract (no remote configured — fail-soft paths)."""

    def _run(self, repo, *args):
        proc = subprocess.run(
            [sys.executable, str(_RELEASE_GATE), "--repo-path", str(repo), *args],
            capture_output=True,
            text=True,
        )
        payload = json.loads(proc.stdout) if proc.stdout.strip() else None
        return proc.returncode, payload

    def test_release_happy_path(self):
        repo = _fresh_repo()
        # CLI resolves identity via get_identity(); acquire under the REAL
        # container id so release-by-track can match it.
        from lib.identity import get_identity

        ident = get_identity()
        acquire_claim(
            derive_track_id("carry-cli-test"), "B", identity=ident, repo_path=repo
        )
        rc, out = self._run(repo, "--raw-track-id", "carry-cli-test")
        self.assertEqual(rc, 0)
        self.assertTrue(out["released"]["success"])
        self.assertEqual(out["released"]["status"], "done")
        self.assertIsNone(out["hard_error"])
        # push attempted (claim written) but no remote → fail-soft, not hard
        self.assertFalse(out["push_success"])

    def test_release_not_found_benign_exit_zero(self):
        repo = _fresh_repo()
        rc, out = self._run(repo, "--raw-track-id", "never-claimed")
        self.assertEqual(rc, 0)
        self.assertFalse(out["released"]["success"])
        self.assertTrue(out["released"]["benign"])
        self.assertIsNone(out["hard_error"])
        self.assertIsNone(out["push_success"])  # nothing written → no push

    def test_sweep_and_gc_flags(self):
        repo = _fresh_repo()
        now = datetime.now(timezone.utc)
        acquire_claim(
            "t-stale", "B", identity=Identity("bot", "cBOT", "s1"),
            repo_path=repo, now=now - timedelta(hours=2),
        )
        rc, out = self._run(repo, "--sweep-stale", "--gc")
        self.assertEqual(rc, 0)
        self.assertEqual(out["sweep"]["swept_count"], 1)
        self.assertEqual(out["gc"]["archived_count"], 0)
        self.assertIsNone(out["released"])

    def test_no_action_args_usage_error(self):
        repo = _fresh_repo()
        proc = subprocess.run(
            [sys.executable, str(_RELEASE_GATE), "--repo-path", str(repo)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 2)

    def test_release_telemetry_partition_isolated(self):
        """release 遥测写独立分区, 不污染 run_gate 探针的 coordination-telemetry.jsonl."""
        repo = _fresh_repo()
        rc, _ = self._run(repo, "--raw-track-id", "whatever")
        self.assertEqual(rc, 0)
        self.assertTrue((repo / ".aria" / "coordination-release-telemetry.jsonl").exists())
        self.assertFalse((repo / ".aria" / "coordination-telemetry.jsonl").exists())


if __name__ == "__main__":
    unittest.main()

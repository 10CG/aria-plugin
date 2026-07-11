"""Tests for claim_lifecycle.release_claim_by_track (defect c, WIP).

Part of the coordination-claim-lifecycle-and-overlap spec (Phase B, in progress).
release_claim_by_track releases THIS container's active claim located by
(normalized track_id, container) instead of (container, session) — because a
later ship/close invocation has a fresh session_id and cannot match the
original acquiring session (the root cause of claims never being released).
"""
import subprocess
import tempfile
from pathlib import Path

import sys
_LIB = str(Path(__file__).resolve().parents[1])
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from lib.coordination_ref import bootstrap, read_claims  # noqa: E402
from lib.claim_lifecycle import acquire_claim, release_claim_by_track  # noqa: E402
from lib.track_id import derive_track_id  # noqa: E402
from lib.identity import Identity  # noqa: E402


def _sh(cmd, cwd):
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True)


def _fresh_repo():
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


def test_release_by_track_from_fresh_session():
    repo = _fresh_repo()
    idA = Identity(owner="alice", container_id="cA", session_id="s1")
    # acquire stores the NORMALIZED track_id (the CLI normalizes before acquire)
    acquire_claim(derive_track_id("carry-my-work.v2"), "B", identity=idA, repo_path=repo)

    # ship-time: fresh session, same container, release by the raw carry-id
    ship = Identity(owner="alice", container_id="cA", session_id="s2-fresh")
    rel = release_claim_by_track("carry-my-work.v2", status="done", identity=ship, repo_path=repo)
    assert rel.success and rel.record.status == "done"

    claims = read_claims(repo).claims
    assert [c.status for c in claims if c.container == "cA"] == ["done"]


def test_release_by_track_idempotent():
    repo = _fresh_repo()
    idA = Identity(owner="alice", container_id="cA", session_id="s1")
    acquire_claim(derive_track_id("carry-x"), "B", identity=idA, repo_path=repo)
    ship = Identity(owner="alice", container_id="cA", session_id="s2")
    assert release_claim_by_track("carry-x", identity=ship, repo_path=repo).success
    # releasing again: no active match -> benign claim_not_found
    assert release_claim_by_track("carry-x", identity=ship, repo_path=repo).error == "claim_not_found"


def test_release_by_track_container_isolation():
    repo = _fresh_repo()
    norm = derive_track_id("carry-shared")
    acquire_claim(norm, "B", identity=Identity("alice", "cA", "s1"), repo_path=repo)
    acquire_claim(norm, "B", identity=Identity("bob", "cB", "s9"), repo_path=repo)
    # alice releases only her own claim; bob's stays active
    release_claim_by_track("carry-shared", identity=Identity("alice", "cA", "sx"), repo_path=repo)
    claims = {c.container: c.status for c in read_claims(repo).claims}
    assert claims["cA"] == "done"
    assert claims["cB"] == "active"


def test_release_by_track_invalid_status():
    repo = _fresh_repo()
    r = release_claim_by_track("carry-x", status="bogus", identity=Identity("a", "c", "s"), repo_path=repo)
    assert not r.success and r.error == "invalid_status"

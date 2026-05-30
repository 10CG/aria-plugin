#!/usr/bin/env python3
"""Tests for lib/collision.py (TASK-000, concurrent-session-upm-safety #133).

Two layers:
  1. Synthetic classify()/helper logic tests — deterministic, exact-value, cover
     every branch (cross_owner / self_multi_container / self-serial->none /
     terminal-excluded / unknown-excluded / multi-group / fail-soft / emoji-drop).
  2. ONE real-collector fixture test (AC-0: "跑真实 collect_handoff_multibranch
     输出 fixture, 非手搓 schema") — builds a hermetic multi-branch git repo with
     conflicting handoff frontmatter, runs the REAL collector, asserts the
     persisted tracks_multibranch.collision summary. Guards against phantom-field
     regression (sister R1 C1).

Run:
    python3 -m pytest tests/test_collision.py -v
    python3 tests/test_collision.py          # fallback: plain asserts
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import collision  # noqa: E402
from collectors.handoff_multibranch import collect_handoff_multibranch  # noqa: E402

_NOW = None  # let reconcile_all default; freshness irrelevant for collision kind


def _track(track_id, oc, *, status="active", updated="2026-05-30T10:00:00Z"):
    return {
        "track_id": track_id,
        "owner_container": oc,
        "phase": "B",
        "status": status,
        "updated_at": updated,
    }


# ---------------------------------------------------------------------------
# classify() — aggregate logic
# ---------------------------------------------------------------------------


def test_classify_empty_is_none():
    assert collision.classify([]) == {"kind": "none", "groups": []}


def test_classify_single_track_is_none():
    out = collision.classify([_track("t1", "alice/box-A/s1")])
    assert out == {"kind": "none", "groups": []}


def test_classify_cross_owner():
    out = collision.classify([
        _track("t1", "alice/box-A/s1", updated="2026-05-30T10:00:00Z"),
        _track("t1", "bob/box-B/s2", updated="2026-05-30T10:01:00Z"),
    ])
    assert out["kind"] == "cross_owner"
    assert out["groups"] == [["alice/box-A/s1", "bob/box-B/s2"]]


def test_classify_self_multi_container():
    out = collision.classify([
        _track("x", "alice/box-A/s1", updated="2026-05-30T10:00:00Z"),
        _track("x", "alice/box-B/s2", updated="2026-05-30T10:01:00Z"),
    ])
    assert out["kind"] == "self_multi_container"
    assert out["groups"] == [["alice/box-A/s1", "alice/box-B/s2"]]


def test_classify_self_serial_is_none():
    # Same owner + same container (different session) -> self-serial -> none (R1 M3).
    out = collision.classify([
        _track("y", "alice/box-A/s1", updated="2026-05-30T10:00:00Z"),
        _track("y", "alice/box-A/s2", updated="2026-05-30T10:01:00Z"),
    ])
    assert out == {"kind": "none", "groups": []}


def test_classify_unknown_owner_excluded():
    # legacy / missing frontmatter -> owner_container "unknown" -> not collidable.
    out = collision.classify([
        _track("z", "unknown", status="legacy"),
        _track("z", "unknown", status="legacy"),
    ])
    assert out == {"kind": "none", "groups": []}


def test_classify_terminal_status_excluded():
    # A done/abandoned claim is terminal -> not an active candidate -> no collision.
    out = collision.classify([
        _track("t", "alice/box-A/s1", status="active"),
        _track("t", "bob/box-B/s2", status="done"),
    ])
    assert out == {"kind": "none", "groups": []}


def test_classify_multiple_groups_escalates_to_cross_owner():
    # One self-multi track + one cross-owner track -> overall cross_owner, 2 groups.
    out = collision.classify([
        _track("self", "alice/box-A/s1", updated="2026-05-30T10:00:00Z"),
        _track("self", "alice/box-B/s2", updated="2026-05-30T10:01:00Z"),
        _track("cross", "alice/box-A/s3", updated="2026-05-30T10:00:00Z"),
        _track("cross", "bob/box-C/s4", updated="2026-05-30T10:01:00Z"),
    ])
    assert out["kind"] == "cross_owner"  # most severe across groups
    assert len(out["groups"]) == 2
    assert ["alice/box-A/s1", "alice/box-B/s2"] in out["groups"]
    assert ["alice/box-A/s3", "bob/box-C/s4"] in out["groups"]


def test_classify_emoji_never_persisted():
    out = collision.classify([
        _track("t1", "alice/box-A/s1"),
        _track("t1", "bob/box-B/s2"),
    ])
    # Only kind + groups keys; no emoji / severity field leaks into the summary.
    assert set(out.keys()) == {"kind", "groups"}
    flat = "".join("".join(g) for g in out["groups"]) + out["kind"]
    assert "\U0001F534" not in flat and "\U0001F7E1" not in flat


def test_classify_failsoft_skips_bad_updated_at():
    # A track with unparseable updated_at is skipped (fail-soft), the rest classify.
    out = collision.classify([
        _track("t1", "alice/box-A/s1", updated="not-a-date"),
        _track("t1", "bob/box-B/s2", updated="2026-05-30T10:01:00Z"),
    ])
    # Only one valid claim remains -> no collision.
    assert out == {"kind": "none", "groups": []}


def test_classify_groups_members_sorted_and_deduped():
    out = collision.classify([
        _track("t1", "zoe/box-Z/s1", updated="2026-05-30T10:00:00Z"),
        _track("t1", "amy/box-A/s2", updated="2026-05-30T10:01:00Z"),
    ])
    assert out["groups"][0] == sorted(out["groups"][0])


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def test_split_owner_container_variants():
    assert collision.split_owner_container("a/b/c") == ("a", "b", "c")
    assert collision.split_owner_container("b/c") == ("", "b", "c")
    assert collision.split_owner_container("solo") == ("", "", "solo")
    assert collision.split_owner_container("") == ("", "", "")
    # 4-part: session keeps the remainder joined.
    assert collision.split_owner_container("a/b/c/d") == ("a", "b", "c/d")


def test_track_to_claim_record_raises_on_missing_fields():
    bad_no_tid = {"owner_container": "a/b/c", "updated_at": "2026-05-30T10:00:00Z"}
    try:
        collision.track_to_claim_record(bad_no_tid)
        assert False, "expected ValueError for missing track_id"
    except ValueError:
        pass
    bad_no_ts = {"track_id": "t", "owner_container": "a/b/c"}
    try:
        collision.track_to_claim_record(bad_no_ts)
        assert False, "expected ValueError for missing updated_at"
    except ValueError:
        pass


def test_classify_claims_returns_kind_and_emoji():
    from claim_schema import ClaimRecord

    def _cr(owner, container, session):
        return ClaimRecord(
            schema_version="1", track_id="t", owner=owner, container=container,
            session=session, phase="B", status="active",
            claimed_at="2026-05-30T10:00:00Z", heartbeat_at="2026-05-30T10:00:00Z",
        )

    kind, emoji = collision.classify_claims([_cr("a", "x", "1"), _cr("b", "y", "2")])
    assert kind == "cross_owner"
    assert emoji == "\U0001F534"
    kind2, emoji2 = collision.classify_claims([_cr("a", "x", "1")])
    assert kind2 == "none" and emoji2 == ""


# ---------------------------------------------------------------------------
# Real-collector fixture (AC-0: 非手搓 schema)
# ---------------------------------------------------------------------------


def _git(cwd, *args):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env=env)


def _build_multibranch_repo(tmp: str, branch_tracks: dict) -> None:
    """Build a repo with one origin/* ref per (branch -> handoff frontmatter).

    branch_tracks: {branch_name: (track_id, owner_container)}
    Each branch gets a committed docs/handoff/<branch>.md with 5-field frontmatter;
    the commit is then published to refs/remotes/origin/<branch> so the real
    collector (which scans refs/remotes/origin/*) sees it.
    """
    _git(tmp, "init", "-q")
    _git(tmp, "config", "user.email", "test@test.com")
    _git(tmp, "config", "user.name", "Test")
    # Base commit on the default branch so subsequent branches have a parent.
    root = Path(tmp)
    (root / "README.md").write_text("seed\n", encoding="utf-8")
    _git(tmp, "add", "README.md")
    _git(tmp, "commit", "-q", "-m", "seed")

    handoff_dir = root / "docs" / "handoff"
    handoff_dir.mkdir(parents=True, exist_ok=True)

    for branch, (track_id, oc) in branch_tracks.items():
        _git(tmp, "checkout", "-q", "-b", branch)
        fname = f"2026-05-30-{branch}.md"
        fm = (
            "---\n"
            f"track-id: {track_id}\n"
            f"owner-container: {oc}\n"
            "phase: B\n"
            "status: active\n"
            "updated-at: 2026-05-30T10:00:00Z\n"
            "---\n\n# handoff\n"
        )
        (handoff_dir / fname).write_text(fm, encoding="utf-8")
        _git(tmp, "add", f"docs/handoff/{fname}")
        _git(tmp, "commit", "-q", "-m", f"handoff on {branch}")
        # Publish to origin/<branch> (no real remote needed).
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=tmp, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
        _git(tmp, "update-ref", f"refs/remotes/origin/{branch}", sha)
        _git(tmp, "checkout", "-q", "master") if branch != "master" else None


def test_real_collector_emits_cross_owner_collision():
    """End-to-end: real collect_handoff_multibranch persists collision summary."""
    with tempfile.TemporaryDirectory() as tmp:
        # Two origin branches, same track-id, different owner -> cross_owner.
        _build_multibranch_repo(tmp, {
            "feature-a": ("shared-track", "alice/box-A/s1"),
            "feature-b": ("shared-track", "bob/box-B/s2"),
        })
        result = collect_handoff_multibranch(Path(tmp))
        data = result.data
        # Phantom-field guard: the key MUST exist with the documented shape.
        assert "collision" in data, "collision field missing from real collector output"
        coll = data["collision"]
        assert set(coll.keys()) == {"kind", "groups"}
        assert coll["kind"] == "cross_owner", f"got {coll!r}"
        assert len(coll["groups"]) == 1
        members = coll["groups"][0]
        assert "alice/box-A/s1" in members and "bob/box-B/s2" in members


def test_real_collector_no_collision_is_none():
    """Real collector with distinct track-ids -> kind none, groups empty."""
    with tempfile.TemporaryDirectory() as tmp:
        _build_multibranch_repo(tmp, {
            "feature-a": ("track-one", "alice/box-A/s1"),
            "feature-b": ("track-two", "bob/box-B/s2"),
        })
        result = collect_handoff_multibranch(Path(tmp))
        coll = result.data["collision"]
        assert coll == {"kind": "none", "groups": []}, f"got {coll!r}"


def run_all() -> int:
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ✓ {fn.__name__}")
        except AssertionError as e:
            print(f"  ✗ {fn.__name__}: {e}")
            failed += 1
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ {fn.__name__}: UNEXPECTED {type(e).__name__}: {e}")
            failed += 1
    if failed:
        print(f"\n💥 {failed} test(s) failed")
        sys.exit(1)
    print(f"\n🎉 All {len(fns)} tests passed!")
    return 0


if __name__ == "__main__":
    run_all()

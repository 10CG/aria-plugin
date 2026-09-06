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
from datetime import datetime, timezone
from pathlib import Path

# Add the state-scanner root (parent of lib/) so that ``lib`` is importable as a
# package — collision.py uses relative imports (from .claim_schema), so it must be
# imported as ``lib.collision``, NOT as a top-level ``collision`` with lib/ on path.
# Also add scripts/ for the collectors package — but as a *supplementary* search
# path (append), never ahead of the skill root: state-scanner/ has TWO `lib`
# packages (lib/ with collision.py vs scripts/lib/ without it); putting scripts/
# first binds `lib` to the wrong one and `from lib import collision` raises
# ImportError on single-module runs (aria-plugin#134; only masked under full
# discovery because alphabetically-earlier modules pre-bind sys.modules['lib']).
_SS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SS_ROOT))
sys.path.append(str(_SS_ROOT / "scripts"))

from lib import collision  # noqa: E402
from collectors.handoff_multibranch import collect_handoff_multibranch  # noqa: E402


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
    """SC-1 (owner-container-identity-key-and-collision-parser TASK-001).

    Layer H frontmatter is TWO-part ``<owner>/<container-id>`` per
    session-handoff.md §2.3.1; the former 3-part reading mis-attributed the
    owner segment to "container" and the container to "session".  How it goes
    red on aria 7dd0135: ``("", "simonfish", "bfe8285d")`` / ``("", "", "solo")``.
    """
    assert collision.split_owner_container("simonfish/bfe8285d") == ("simonfish", "bfe8285d", "")
    assert collision.split_owner_container("solo") == ("", "solo", "")
    assert collision.split_owner_container("a/b/c") == ("a", "b", "c")
    assert collision.split_owner_container("") == ("", "", "")
    # 4-part: session keeps the remainder joined (unchanged).
    assert collision.split_owner_container("a/b/c/d") == ("a", "b", "c/d")


# ---------------------------------------------------------------------------
# SC-2 判定臂 — 生产路径 dedupe → classify (TASK-002)
# ---------------------------------------------------------------------------

from collectors.handoff_multibranch import dedupe_latest_per_track_container  # noqa: E402


def _row(track_id, oc, *, status="active", updated="2026-08-20T10:00:00Z", filename=None):
    return {
        "track_id": track_id,
        "owner_container": oc,
        "phase": "B",
        "status": status,
        "updated_at": updated,
        "filename": filename or f"{updated[:10]}-{oc.replace('/', '-')}.md",
        "branch": "master",
        "legacy": False,
    }


def _classify_via_production_path(rows):
    deduped, _stats = dedupe_latest_per_track_container(rows)
    return collision.classify(deduped)


def test_arm_same_container_two_owners_is_none():
    # 同容器双 owner (git 身份漂移, #193): 一台机器 bfe8285d 两个提交身份 -> 折叠为 1 行 -> none.
    # RED on 7dd0135: 🟡 self_multi_container (3-part parser reads owners as containers).
    out = _classify_via_production_path([
        _row("t", "simonfish/bfe8285d", updated="2026-08-20T10:00:00Z"),
        _row("t", "aria-runner-bot/bfe8285d", updated="2026-08-21T10:00:00Z"),
    ])
    assert out["kind"] == "none", out
    assert out["groups"] == [], out


def test_arm_two_people_two_machines_is_cross_owner():
    # RED on 7dd0135: 🟡 (owner segment lost -> both "unknown" owners).
    out = _classify_via_production_path([
        _row("t", "alice/aaaa1111"),
        _row("t", "bob/bbbb2222"),
    ])
    assert out["kind"] == "cross_owner", out
    assert out["groups"] == [["alice/aaaa1111", "bob/bbbb2222"]], out


def test_arm_same_person_two_machines_is_self_multi_container():
    # RED on 7dd0135: none (both rows fold into one dedupe key (t, "", "simonfish")).
    out = _classify_via_production_path([
        _row("t", "simonfish/bfe8285d"),
        _row("t", "simonfish/023236f2"),
    ])
    assert out["kind"] == "self_multi_container", out
    assert out["groups"] == [["simonfish/023236f2", "simonfish/bfe8285d"]], out


def test_arm_drift_without_cooccurrence_is_cross_owner():
    # 漂移后无共现: 两个不同提交身份在两个 uuid 容器上 = 🔴 (诚实), ⚪ advisory 负责解释.
    out = _classify_via_production_path([
        _row("t", "aria-runner-bot/bfe8285d"),
        _row("t", "simonfish/023236f2"),
    ])
    assert out["kind"] == "cross_owner", out


def test_arm_zero_segment_vs_two_segment_same_hostname_is_self_multi_container():
    # "devbox01" (零段, owner 空 -> 不可归属) vs "simonfish/devbox01": 两个 identity_key, 可归属 owner 集合 = {simonfish}.
    out = _classify_via_production_path([
        _row("t", "devbox01"),
        _row("t", "simonfish/devbox01"),
    ])
    assert out["kind"] == "self_multi_container", out


def test_arm_unknown_owner_is_not_an_independent_owner():
    # owner 字面 "unknown" (git 未配 email) 与真实 owner 并存: 只有 1 个可归属 owner -> 🟡, 不是 🔴.
    out = _classify_via_production_path([
        _row("t", "unknown/aaaa1111"),
        _row("t", "alice/bbbb2222"),
    ])
    assert out["kind"] == "self_multi_container", out


# ---------------------------------------------------------------------------
# SC-2 advisory 臂 — identity_drift_advisories (函数级, 对 dedupe 前全语料) (TASK-002)
# ---------------------------------------------------------------------------


def test_advisory_same_container_two_owners_yields_exactly_one():
    # RED on 7dd0135: AttributeError (function does not exist).
    rows = [
        _row("t1", "simonfish/bfe8285d", updated="2026-07-01T10:00:00Z"),
        _row("t2", "aria-runner-bot/bfe8285d", updated="2026-09-01T10:00:00Z"),
        _row("t3", "simonfish/bfe8285d", updated="2026-08-01T10:00:00Z", status="done"),
    ]
    adv = collision.identity_drift_advisories(rows)
    assert isinstance(adv, list) and len(adv) == 1, adv
    a = adv[0]
    assert a["identity_key"] == "bfe8285d"
    assert a["owners"] == ["aria-runner-bot", "simonfish"]
    assert a["first_seen"] == "2026-07-01T10:00:00Z"
    assert a["last_seen"] == "2026-09-01T10:00:00Z"
    assert set(a.keys()) == {"identity_key", "owners", "first_seen", "last_seen"}


def test_advisory_three_owners_same_uuid_lists_three():
    rows = [
        _row("t1", "a/aaaa1111"),
        _row("t2", "b/aaaa1111"),
        _row("t3", "c/aaaa1111"),
    ]
    adv = collision.identity_drift_advisories(rows)
    assert len(adv) == 1 and adv[0]["owners"] == ["a", "b", "c"], adv


def test_advisory_ignores_legacy_unknown_and_hostname_containers():
    rows = [
        _row("t1", "unknown", status="legacy"),
        _row("t2", "unknown/aaaa1111"),          # owner "unknown" 不计
        _row("t3", "alice/aaaa1111"),            # 只有 1 个可归属 owner -> 不产生
        _row("t4", "alice/devbox01"),            # 主机名容器不是 uuid identity_key -> 不产生
        _row("t5", "bob/devbox01"),
        _row("t6", "devbox01"),
    ]
    assert collision.identity_drift_advisories(rows) == []


def test_advisory_no_input_is_empty_list():
    assert collision.identity_drift_advisories([]) == []


# ---------------------------------------------------------------------------
# D-0(a) 族键 — track_to_claim_record 纯形状剥离 (TASK-007)
# ---------------------------------------------------------------------------


def test_family_key_two_uuid_suffixed_tracks_collide():
    # <slug>-<uuid1> / <slug>-<uuid2> 两容器同一件事 -> 剥后同 track -> 可达 🔴.
    # RED on 7dd0135: none (两个 track_id 不同组).
    out = _classify_via_production_path([
        _row("slug-aaaa1111", "alice/aaaa1111"),
        _row("slug-bbbb2222", "bob/bbbb2222"),
    ])
    assert out["kind"] == "cross_owner", out
    assert len(out["groups"]) == 1, out


def test_family_key_strip_rules():
    base = {"owner_container": "alice/aaaa1111", "updated_at": "2026-08-20T10:00:00Z", "status": "active"}
    # 8 位小写 hex 尾段 -> 剥
    assert collision.track_to_claim_record({**base, "track_id": "slug-aaaa1111"}).track_id == "slug"
    # 7 位 -> 不剥
    assert collision.track_to_claim_record({**base, "track_id": "slug-abcdefg"}).track_id == "slug-abcdefg"
    # 8 位十进制也是 hex 形 (成文已知限制): 剥为 "x"; 与冻结语料零碰撞由 test_collision_frozen_corpus 承担
    assert collision.track_to_claim_record({**base, "track_id": "x-20260719"}).track_id == "x"
    # 大写 / 含非 hex -> 不剥
    assert collision.track_to_claim_record({**base, "track_id": "slug-AAAA1111"}).track_id == "slug-AAAA1111"
    assert collision.track_to_claim_record({**base, "track_id": "slug-devbox01"}).track_id == "slug-devbox01"


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
    from lib.claim_schema import ClaimRecord

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
    # Capture the default branch name (master vs main varies by git config).
    default_branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=tmp, check=True,
        capture_output=True, text=True,
    ).stdout.strip()

    for branch, (track_id, oc) in branch_tracks.items():
        # Branch from the default branch's seed commit. After committing the
        # handoff doc on a prior feature branch, switching away removes that
        # committed docs/handoff/ tree from the working copy — so we must
        # re-create the directory on each fresh branch.
        _git(tmp, "checkout", "-q", default_branch)
        _git(tmp, "checkout", "-q", "-b", branch)
        handoff_dir = root / "docs" / "handoff"
        handoff_dir.mkdir(parents=True, exist_ok=True)
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


def test_real_collector_emits_cross_owner_collision():
    """End-to-end: real collect_handoff_multibranch persists collision summary."""
    with tempfile.TemporaryDirectory() as tmp:
        # Two origin branches, same track-id, different owner -> cross_owner.
        _build_multibranch_repo(tmp, {
            "feature-a": ("shared-track", "alice/box-A/s1"),
            "feature-b": ("shared-track", "bob/box-B/s2"),
        })
        # Fixture rows are dated 2026-05-30; pin ``now`` inside the Layer H
        # window (D-3(a)) so the test is calendar-independent.
        result = collect_handoff_multibranch(Path(tmp), now=datetime(2026, 5, 31, tzinfo=timezone.utc))
        data = result.data
        # Phantom-field guard: the key MUST exist with the documented shape.
        assert "collision" in data, "collision field missing from real collector output"
        coll = data["collision"]
        # SC-8 (TASK-004): identity_advisories is ALWAYS present (list; [] when no drift).
        assert set(coll.keys()) == {"kind", "groups", "identity_advisories"}, coll.keys()
        assert coll["identity_advisories"] == []
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
        result = collect_handoff_multibranch(Path(tmp), now=datetime(2026, 5, 31, tzinfo=timezone.utc))
        coll = result.data["collision"]
        assert coll == {"kind": "none", "groups": [], "identity_advisories": []}, f"got {coll!r}"


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

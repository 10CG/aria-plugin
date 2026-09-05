"""SC-5 / SC-6 / SC-7 — ``heartbeat_by_track()`` 按 (container, 归一 track_id) 刷新.

Spec: ``openspec/changes/a1-entry-claim-duplicate-work-guard`` TASK-005 (parent 2.2).

既有 ``claim_lifecycle.heartbeat()`` 按 ``(container_id, session_id)`` 定位 claim
(``lib/claim_lifecycle.py`` heartbeat 正文), 所以**换一个 session 就刷不动自己容器
先前写下的 claim** —— 而 A.1 认领的现实正是「同一容器、同一条 track、跨多个 session
接力推进」。SWEEP_TTL 是 24h, 一条永不被刷新的 active claim 到点就被 sweep 成
``abandoned``, 于是活着的轨道会凭空消失。

怎么会红:
  - baseline (aria ``d69091d`` .. ``7dd0135``): ``heartbeat_by_track`` 不存在 ⇒
    本文件 import 即 ``ImportError`` ⇒ 全部用例红。
  - 实现若沿用 ``(container, session)`` 键 ⇒ SC-5 拿到 ``claim_not_found`` ⇒ 红。
  - 实现若只刷第一条匹配 ⇒ SC-6 第二条的 heartbeat_at 不动 ⇒ 红。
  - 实现若不归一 raw track-id ⇒ ``test_normalizes_raw_track_id_before_matching`` 红。
  - 实现若逐字段重建 ClaimRecord 而漏字段 ⇒ ``test_refresh_preserves_...`` 红。
  - SC-7 只写臂 1 (不刷新 ⇒ 被 sweep) 是零新路径覆盖 —— 臂 2 (刷新后 ⇒ 不被 sweep)
    才是新代码的唯一见证, 两臂缺一不可。
"""
import dataclasses
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SKILL_ROOT = str(Path(__file__).resolve().parents[1])
if _SKILL_ROOT not in sys.path:
    sys.path.insert(0, _SKILL_ROOT)

from lib.claim_lifecycle import (  # noqa: E402
    acquire_claim,
    heartbeat,
    heartbeat_by_track,
    release_claim_by_track,
)
from lib.constants import SWEEP_TTL  # noqa: E402
from lib.coordination_ref import bootstrap, read_claims  # noqa: E402
from lib.gc import sweep_stale_active  # noqa: E402
from lib.identity import Identity  # noqa: E402
from lib.track_id import derive_track_id  # noqa: E402

_TRACK = "a1-spec-1a2b3c4d"
_CONTAINER = "c023236f"


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


def _ident(session: str, container: str = _CONTAINER) -> Identity:
    return Identity("simonfish", container, session)


def _claims_by_session(repo: Path) -> dict:
    return {c.session: c for c in read_claims(repo).claims}


class TestHeartbeatByTrackCrossSession(unittest.TestCase):
    """SC-5: 换 session 仍能刷新本容器同一条 track 的 claim."""

    def test_refreshes_claim_written_by_a_different_session(self):
        repo = _fresh_repo()
        t0 = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc)
        t2 = t0 + timedelta(hours=6)
        acquire_claim(_TRACK, "A.1", identity=_ident("s-0001@1000"), repo_path=repo, now=t0)

        result = heartbeat_by_track(
            _TRACK, identity=_ident("s-9999@1600"), repo_path=repo, now=t2
        )

        self.assertTrue(result.success, f"error={result.error}")
        rec = _claims_by_session(repo)["s-0001@1000"]
        self.assertEqual(rec.heartbeat_at, "2026-09-05T16:00:00Z")
        self.assertEqual(rec.claimed_at, "2026-09-05T10:00:00Z", "claimed_at 不可变")

    def test_existing_heartbeat_cannot_refresh_across_sessions(self):
        """坏实现臂: 既有 heartbeat() 在同一场景下返回 claim_not_found.

        守的是上一条的可证伪性 —— 若它转绿, 说明既有 heartbeat 也跨 session 了,
        沿用旧键的坏实现将不再被 SC-5 抓住。
        """
        repo = _fresh_repo()
        t0 = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc)
        acquire_claim(_TRACK, "A.1", identity=_ident("s-0001@1000"), repo_path=repo, now=t0)

        # assertLogs 兼作捕获: 既断言 warning 内容, 又避免它经 lastResort 打到 stderr
        with self.assertLogs("lib.claim_lifecycle", level="WARNING") as cm:
            result = heartbeat(
                _TRACK, identity=_ident("s-9999@1600"), repo_path=repo,
                now=t0 + timedelta(hours=6),
            )
        self.assertTrue(any("no claim found" in m for m in cm.output))

        self.assertFalse(result.success)
        self.assertEqual(result.error, "claim_not_found")

    def test_normalizes_raw_track_id_before_matching(self):
        """传未归一的原始串也必须命中 (归一在函数内部做)."""
        raw = "A1.Spec_1a2b3c4d"
        self.assertEqual(derive_track_id(raw), _TRACK, "夹具前提: 归一后等于 _TRACK")
        repo = _fresh_repo()
        t0 = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc)
        acquire_claim(_TRACK, "A.1", identity=_ident("s-0001@1000"), repo_path=repo, now=t0)

        result = heartbeat_by_track(
            raw, identity=_ident("s-0001@1000"), repo_path=repo, now=t0 + timedelta(hours=1)
        )

        self.assertTrue(result.success, f"error={result.error}")
        self.assertEqual(_claims_by_session(repo)["s-0001@1000"].heartbeat_at,
                         "2026-09-05T11:00:00Z")


class TestHeartbeatByTrackOneToMany(unittest.TestCase):
    """SC-6: 同 (container, track) 的全部 active claim 一次刷完."""

    def test_refreshes_all_active_claims_for_same_container_and_track(self):
        repo = _fresh_repo()
        t0 = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc)
        t2 = t0 + timedelta(hours=6)
        acquire_claim(_TRACK, "A.1", identity=_ident("s-0001@1000"), repo_path=repo, now=t0)
        acquire_claim(_TRACK, "B.2", identity=_ident("s-0002@1200"), repo_path=repo, now=t0)

        heartbeat_by_track(_TRACK, identity=_ident("s-0003@1600"), repo_path=repo, now=t2)

        claims = _claims_by_session(repo)
        self.assertEqual(claims["s-0001@1000"].heartbeat_at, "2026-09-05T16:00:00Z")
        self.assertEqual(claims["s-0002@1200"].heartbeat_at, "2026-09-05T16:00:00Z",
                         "只刷第一条匹配的实现在此必红")

    def test_does_not_touch_other_containers_or_other_tracks(self):
        """负控: 不同容器 / 不同 track 的 claim 一律不动."""
        repo = _fresh_repo()
        t0 = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc)
        t2 = t0 + timedelta(hours=6)
        acquire_claim(_TRACK, "A.1", identity=_ident("s-mine@1000"), repo_path=repo, now=t0)
        acquire_claim(_TRACK, "A.1",
                      identity=_ident("s-other@1000", container="cOTHER"),
                      repo_path=repo, now=t0)
        acquire_claim("zzz-unrelated-9f8e7d6c", "B.2",
                      identity=_ident("s-unrel@1000"), repo_path=repo, now=t0)

        heartbeat_by_track(_TRACK, identity=_ident("s-new@1600"), repo_path=repo, now=t2)

        claims = _claims_by_session(repo)
        self.assertEqual(claims["s-mine@1000"].heartbeat_at, "2026-09-05T16:00:00Z")
        self.assertEqual(claims["s-other@1000"].heartbeat_at, "2026-09-05T10:00:00Z",
                         "跨容器不得被刷")
        self.assertEqual(claims["s-unrel@1000"].heartbeat_at, "2026-09-05T10:00:00Z",
                         "另一条 track 不得被刷")

    def test_refresh_preserves_all_other_claim_fields(self):
        """负控: 除 heartbeat_at 外 10 个字段逐字不变 (逐字段重建漏字段必红)."""
        repo = _fresh_repo()
        t0 = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc)
        acquire_claim(_TRACK, "A.1", identity=_ident("s-0001@1000"), repo_path=repo,
                      now=t0, linked_issue="10CG/Aria#174")
        before = _claims_by_session(repo)["s-0001@1000"]

        heartbeat_by_track(_TRACK, identity=_ident("s-0002@1600"), repo_path=repo,
                           now=t0 + timedelta(hours=6))
        after = _claims_by_session(repo)["s-0001@1000"]

        names = [f.name for f in dataclasses.fields(before)]
        self.assertIn("heartbeat_at", names)
        for name in names:
            if name == "heartbeat_at":
                self.assertNotEqual(getattr(after, name), getattr(before, name))
            else:
                self.assertEqual(getattr(after, name), getattr(before, name),
                                 f"字段 {name} 在刷新中被改动")


class TestSweepInteraction(unittest.TestCase):
    """SC-7 两臂: 不刷新 ⇒ 被 sweep; 经 by_track 刷新 ⇒ 不被 sweep."""

    def test_sweep_abandons_claim_that_was_never_refreshed(self):
        """臂 1 (既有行为, 无新代码路径 — 单独存在等于零覆盖)."""
        repo = _fresh_repo()
        t0 = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc)
        acquire_claim(_TRACK, "A.1", identity=_ident("s-0001@1000"), repo_path=repo, now=t0)

        sweep_stale_active(repo, now=t0 + timedelta(seconds=SWEEP_TTL + 1))

        self.assertEqual(_claims_by_session(repo)["s-0001@1000"].status, "abandoned")

    def test_sweep_spares_claim_refreshed_via_by_track(self):
        """臂 2 (新代码路径的唯一见证): 到点前用 by_track 刷一次 ⇒ 仍 active."""
        repo = _fresh_repo()
        t0 = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc)
        acquire_claim(_TRACK, "A.1", identity=_ident("s-0001@1000"), repo_path=repo, now=t0)

        heartbeat_by_track(_TRACK, identity=_ident("s-0002@1600"), repo_path=repo,
                           now=t0 + timedelta(seconds=SWEEP_TTL - 60))
        sweep_stale_active(repo, now=t0 + timedelta(seconds=SWEEP_TTL + 1))

        self.assertEqual(_claims_by_session(repo)["s-0001@1000"].status, "active")


class TestRenameTwoStep(unittest.TestCase):
    """SC-15 回归守卫 — 改名两步 (release 旧 + acquire 新) 不留孤儿、不误伤旁人.

    ⚠️ **baseline 即绿**: ``release_claim_by_track`` 与 ``acquire_claim`` 今天就这样
    工作。本类守的不是新行为, 而是 ``release_claim_by_track`` 里那个**三合取匹配键**
    (``rec.container == … and rec.track_id == norm and rec.status == "active"``)
    ——它一旦被放宽, 一次改名就会顺手废掉别人的 claim。

    怎么会红 (坏实现, 已实跑亲验后还原):
      A 去掉 ``container`` 合取 ⇒ 容器 B 的第三方 claim 被 abandoned ⇒ 红
      B 匹配键改按 container 批量 / 按 linked_issue ⇒ 同上 ⇒ 红
      C 匹配键改子串 (``"old-slug" in rec.track_id``) ⇒ 只有 ``zzz-unrelated`` 抓不到,
        故另备 ``old-slug-extra-…`` 前缀夹具, 由它变红
    """

    OLD = "old-slug-1a2b3c4d"
    NEW = "new-slug-1a2b3c4d"
    THIRD_PARTY = "zzz-unrelated-9f8e7d6c"      # 与旧/新不共享任何前缀或后缀
    PREFIX_SIBLING = "old-slug-extra-5e5e5e5e"  # 与 OLD 共享前缀, 专抓子串型坏实现
    # 容器 B 里**同 track_id** 的 claim —— 唯一能抓住「去掉 container 合取」的夹具。
    # Spec TASK-006 原写「第三方 (容器 B, 与旧/新不共享前缀/后缀) 会因去掉 container
    # 合取而被 abandoned」, 但 track_id 是精确相等: track 不同的 claim 无论有没有
    # container 合取都匹配不到 ⇒ 那条断言结构上无法变红。实跑负控当场证实 (NC5 全绿)。

    def _setup(self):
        repo = _fresh_repo()
        t0 = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc)
        acquire_claim(self.OLD, "A.1", identity=_ident("s-old@1000"), repo_path=repo, now=t0)
        acquire_claim(self.PREFIX_SIBLING, "A.1", identity=_ident("s-sib@1000"),
                      repo_path=repo, now=t0)
        acquire_claim(self.THIRD_PARTY, "B.2",
                      identity=_ident("s-3rd@1000", container="cOTHERPARTY"),
                      repo_path=repo, now=t0)
        acquire_claim(self.OLD, "A.1",
                      identity=_ident("s-peer@1000", container="cOTHERPARTY"),
                      repo_path=repo, now=t0)
        return repo, t0

    def _by_track(self, repo):
        out = {}
        for c in read_claims(repo).claims:
            out.setdefault(c.track_id, []).append(c)
        return out

    def test_rename_leaves_no_orphan_and_spares_bystanders(self):
        repo, t0 = self._setup()

        release_claim_by_track(self.OLD, status="abandoned", identity=_ident("s-new@1600"),
                               repo_path=repo, now=t0 + timedelta(hours=6))
        acquire_claim(self.NEW, "A.1", identity=_ident("s-new@1600"), repo_path=repo,
                      now=t0 + timedelta(hours=6))

        mine = [c for c in read_claims(repo).claims if c.container == _CONTAINER]
        old = [c for c in mine if c.track_id == self.OLD]
        self.assertEqual(len(old), 1, "本容器旧 claim 应被改写而非删除")
        self.assertEqual(old[0].status, "abandoned")
        active_new = [c for c in mine if c.track_id == self.NEW and c.status == "active"]
        self.assertEqual(len(active_new), 1, "新 track 恰一条 active")

    def test_third_party_claim_in_another_container_stays_active(self):
        """坏实现 A/B 的捕手: 容器 B 的无关 claim 必须毫发无损."""
        repo, t0 = self._setup()

        release_claim_by_track(self.OLD, status="abandoned", identity=_ident("s-new@1600"),
                               repo_path=repo, now=t0 + timedelta(hours=6))

        third = self._by_track(repo)[self.THIRD_PARTY]
        self.assertEqual([c.status for c in third], ["active"])

    def test_same_track_in_another_container_stays_active(self):
        """坏实现 A 的真捕手: 另一个容器**认领同一条 track** 的 claim 必须不动.

        这是「去掉 ``rec.container == resolved.container_id`` 合取」唯一会变红的
        场景 —— 两个容器抢同一条 track 正是本 Spec 要解决的碰撞形态本身。
        """
        repo, t0 = self._setup()

        release_claim_by_track(self.OLD, status="abandoned", identity=_ident("s-new@1600"),
                               repo_path=repo, now=t0 + timedelta(hours=6))

        peer = [c for c in read_claims(repo).claims
                if c.track_id == self.OLD and c.container == "cOTHERPARTY"]
        self.assertEqual([c.status for c in peer], ["active"],
                         "另一容器同 track 的 claim 不得被本容器的 release 波及")

    def test_prefix_sibling_track_in_same_container_stays_active(self):
        """坏实现 C 的捕手: 同容器、共享前缀但不同 track 的 claim 必须不动."""
        repo, t0 = self._setup()
        self.assertTrue(self.PREFIX_SIBLING.startswith("old-slug"),
                        "夹具前提: 该串确与 OLD 共享前缀, 否则抓不住子串型坏实现")

        release_claim_by_track(self.OLD, status="abandoned", identity=_ident("s-new@1600"),
                               repo_path=repo, now=t0 + timedelta(hours=6))

        sibling = self._by_track(repo)[self.PREFIX_SIBLING]
        self.assertEqual([c.status for c in sibling], ["active"])


if __name__ == "__main__":
    unittest.main()

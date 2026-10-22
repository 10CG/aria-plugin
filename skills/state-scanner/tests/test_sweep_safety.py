"""layer-l-sweep-safety-and-recovery (Aria #233) — SC 级 baseline-failing 套件。

Rule #6 判据 (skill-benchmark-exemption SOT 表): lib/scripts 代码 = deterministic
⇒ substitute = 本套结构化测试。反事实自证: 对改前基线 (v1.77.0) 本套必红 —
sweep_stale_active 无 container_id/cross_ttl_seconds 参数 (TypeError), 无 swept
provenance 字段, heartbeat/release 无 claim_swept 分支, restore_swept_claim 不存在
(ImportError)。

覆盖 (spec §1-§5):
  §1 分层 sweep: own 24h / cross 7d / --sweep-stale-all 全域单层
  §2 provenance: swept_by/swept_at 写入 + heartbeat_at 保留 + schema 往返
  §3 swept 信号: heartbeat/release 二次查找 → claim_swept (非 claim_not_found);
     legacy 无 provenance 的 abandoned 降级为 claim_not_found (不造未知 sweeper)
  §4 restore: 本容器恢复 / 他容器结构不可达 / provenance 清空 / heartbeat=now
  §5 phase1_gate acquire 复用路径刷心跳由 CLI 级测试覆盖 (test_a1_entry_gate_cli)
"""
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess

_SKILL_ROOT = str(Path(__file__).resolve().parents[1])
if _SKILL_ROOT not in sys.path:
    sys.path.insert(0, _SKILL_ROOT)

from lib.coordination_ref import bootstrap, read_claims  # noqa: E402
from lib.claim_lifecycle import (  # noqa: E402
    acquire_claim,
    heartbeat_by_track,
    release_claim_by_track,
    restore_swept_claim,
)
from lib.claim_schema import parse_claim, serialize_claim  # noqa: E402
from lib.constants import SWEEP_TTL, SWEEP_TTL_CROSS  # noqa: E402
from lib.gc import sweep_stale_active  # noqa: E402
from lib.identity import Identity  # noqa: E402


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


def _statuses(repo):
    return {c.container: c for c in read_claims(repo).claims}


class TestTieredSweep(unittest.TestCase):
    """§1 — 例行 sweep 分层: own 24h / cross 7d; operator 模式全域单层。"""

    def test_routine_sweeps_own_stale_but_spares_cross_25h(self):
        """#233 核心反事实: 25h 的邻居 claim 在例行收尾下必须存活 (旧行为: 被扫)。"""
        repo = _fresh_repo()
        now = datetime.now(timezone.utc)
        acquire_claim("t-own-stale", "B", identity=Identity("me", "cME", "s1"),
                      repo_path=repo, now=now - timedelta(hours=25))
        acquire_claim("t-nb-stale", "B", identity=Identity("bot", "cNB", "s2"),
                      repo_path=repo, now=now - timedelta(hours=25))
        result = sweep_stale_active(repo, now=now, container_id="cME")
        self.assertEqual(result.swept, ["cME/s1"])  # 只扫自己
        st = _statuses(repo)
        self.assertEqual(st["cME"].status, "abandoned")
        self.assertEqual(st["cNB"].status, "active")  # 25h 邻居存活

    def test_routine_sweeps_cross_after_7d(self):
        repo = _fresh_repo()
        now = datetime.now(timezone.utc)
        acquire_claim("t-nb-old", "B", identity=Identity("bot", "cNB", "s2"),
                      repo_path=repo, now=now - timedelta(days=8))
        result = sweep_stale_active(repo, now=now, container_id="cME")
        self.assertEqual(result.swept, ["cNB/s2"])  # 8d 邻居仍会被清 (死容器兜底)

    def test_routine_sweeps_own_after_24h_boundary(self):
        repo = _fresh_repo()
        now = datetime.now(timezone.utc)
        acquire_claim("t-own", "B", identity=Identity("me", "cME", "s1"),
                      repo_path=repo, now=now - timedelta(hours=25))
        result = sweep_stale_active(repo, now=now, container_id="cME")
        self.assertEqual(result.swept, ["cME/s1"])

    def test_operator_mode_sweeps_cross_at_24h(self):
        """--sweep-stale-all (container_id=None) = 旧全域单层语义。"""
        repo = _fresh_repo()
        now = datetime.now(timezone.utc)
        acquire_claim("t-nb", "B", identity=Identity("bot", "cNB", "s2"),
                      repo_path=repo, now=now - timedelta(hours=25))
        result = sweep_stale_active(repo, now=now, container_id=None)
        self.assertEqual(result.swept, ["cNB/s2"])

    def test_cross_ttl_overridable(self):
        repo = _fresh_repo()
        now = datetime.now(timezone.utc)
        acquire_claim("t-nb", "B", identity=Identity("bot", "cNB", "s2"),
                      repo_path=repo, now=now - timedelta(hours=30))
        result = sweep_stale_active(
            repo, now=now, container_id="cME", cross_ttl_seconds=3600
        )
        self.assertEqual(result.swept, ["cNB/s2"])

    def test_constants_tier_values(self):
        self.assertEqual(SWEEP_TTL, 86400)
        self.assertEqual(SWEEP_TTL_CROSS, 604800)  # owner 2026-10-22 主案 7d


class TestSweepProvenance(unittest.TestCase):
    """§2 — sweep 改写带出处; heartbeat_at 保留; schema 往返。"""

    def test_swept_record_carries_provenance(self):
        repo = _fresh_repo()
        now = datetime.now(timezone.utc)
        acq = acquire_claim("t-x", "B", identity=Identity("me", "cME", "s1"),
                            repo_path=repo, now=now - timedelta(hours=30))
        sweep_stale_active(repo, now=now, container_id="cME")
        rec = _statuses(repo)["cME"]
        self.assertEqual(rec.status, "abandoned")
        self.assertEqual(rec.swept_by, "cME")
        self.assertIsNotNone(rec.swept_at)
        self.assertEqual(rec.heartbeat_at, acq.record.heartbeat_at)  # last-alive 不动

    def test_operator_mode_provenance_is_operator(self):
        repo = _fresh_repo()
        now = datetime.now(timezone.utc)
        acquire_claim("t-x", "B", identity=Identity("bot", "cNB", "s2"),
                      repo_path=repo, now=now - timedelta(hours=30))
        sweep_stale_active(repo, now=now, container_id=None)
        self.assertEqual(_statuses(repo)["cNB"].swept_by, "operator")

    def test_schema_roundtrip_swept_fields(self):
        raw = {
            "schema_version": "1", "track_id": "t", "owner": "o",
            "container": "c", "session": "s", "phase": "B.2",
            "status": "abandoned", "claimed_at": "2026-10-01T00:00:00Z",
            "heartbeat_at": "2026-10-01T00:00:00Z",
            "swept_by": "cX", "swept_at": "2026-10-02T00:00:00Z",
        }
        rec = parse_claim(raw)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.swept_by, "cX")
        out = serialize_claim(rec)
        self.assertEqual(out["swept_by"], "cX")
        self.assertEqual(out["swept_at"], "2026-10-02T00:00:00Z")

    def test_malformed_swept_at_rejected(self):
        raw = {
            "schema_version": "1", "track_id": "t", "owner": "o",
            "container": "c", "session": "s", "phase": "B.2",
            "status": "abandoned", "claimed_at": "2026-10-01T00:00:00Z",
            "heartbeat_at": "2026-10-01T00:00:00Z",
            "swept_by": "cX", "swept_at": "not-a-date",
        }
        self.assertIsNone(parse_claim(raw))


class TestSweptSignal(unittest.TestCase):
    """§3 — heartbeat/release 的 claim_swept 信号 (消灭伪装 benign)。"""

    def _swept_repo(self):
        repo = _fresh_repo()
        now = datetime.now(timezone.utc)
        acquire_claim("t-live", "B", identity=Identity("me", "cME", "s1"),
                      repo_path=repo, now=now - timedelta(hours=25))
        # cME 的例行收尾把 cME 自己那条扫掉 (25h > 24h own 阈)
        sweep_stale_active(repo, now=now, container_id="cME")
        return repo, Identity("me", "cME", "s1")

    def test_heartbeat_on_swept_returns_claim_swept_with_provenance(self):
        repo, ident = self._swept_repo()
        result = heartbeat_by_track("t-live", identity=ident, repo_path=repo)
        self.assertFalse(result.success)
        self.assertEqual(result.error, "claim_swept")
        self.assertIsNotNone(result.record)
        self.assertEqual(result.record.swept_by, "cME")
        self.assertIsNotNone(result.record.swept_at)

    def test_release_on_swept_returns_claim_swept(self):
        repo, ident = self._swept_repo()
        result = release_claim_by_track("t-live", identity=ident, repo_path=repo)
        self.assertFalse(result.success)
        self.assertEqual(result.error, "claim_swept")
        self.assertIsNotNone(result.record.swept_at)

    def test_legacy_abandoned_without_provenance_stays_not_found(self):
        """pre-#167 legacy: 无出处的 abandoned 不伪装 claim_swept (不造未知 sweeper)。"""
        repo = ident = None
        repo = _fresh_repo()
        now = datetime.now(timezone.utc)
        acq = acquire_claim("t-old", "B", identity=Identity("me", "cME", "s1"),
                            repo_path=repo, now=now)
        # 手工把状态改成无 provenance 的 abandoned (模拟 legacy 记录)
        from lib.claim_schema import ClaimRecord
        import dataclasses
        legacy = dataclasses.replace(acq.record, status="abandoned")
        from lib.coordination_ref import apply_tree_edits
        import yaml
        path = f"claims/{legacy.container}/{legacy.session}.yaml"
        apply_tree_edits(
            [("add", path, yaml.safe_dump(serialize_claim(legacy), allow_unicode=True))],
            repo, message="test: legacy abandoned",
        )
        result = heartbeat_by_track("t-old", identity=Identity("me", "cME", "s9"),
                                    repo_path=repo)
        self.assertFalse(result.success)
        self.assertEqual(result.error, "claim_not_found")  # 降级而非捏造

    def test_genuinely_unclaimed_stays_not_found(self):
        repo = _fresh_repo()
        result = heartbeat_by_track("t-never", identity=Identity("me", "cME", "s1"),
                                    repo_path=repo)
        self.assertEqual(result.error, "claim_not_found")


class TestRestore(unittest.TestCase):
    """§4 — 恢复路径: 本容器恢复 / 他容器结构不可达 / provenance 清空。"""

    def _swept_repo(self):
        repo = _fresh_repo()
        now = datetime.now(timezone.utc)
        acquire_claim("t-live", "B", identity=Identity("me", "cME", "s1"),
                      repo_path=repo, now=now - timedelta(hours=25))
        sweep_stale_active(repo, now=now, container_id="cME")
        return repo

    def test_restore_own_swept_claim(self):
        repo = self._swept_repo()
        later = datetime.now(timezone.utc) + timedelta(minutes=1)
        result = restore_swept_claim(
            "t-live", identity=Identity("me", "cME", "s2"), repo_path=repo, now=later
        )
        self.assertTrue(result.success, result.error)
        rec = _statuses(repo)["cME"]
        self.assertEqual(rec.status, "active")
        self.assertIsNone(rec.swept_by)
        self.assertIsNone(rec.swept_at)
        self.assertEqual(rec.heartbeat_at, later.strftime("%Y-%m-%dT%H:%M:%SZ"))

    def test_restore_scoped_to_own_container(self):
        """结构性防伪: 他容器的 swept claim 对本容器不可达 (claim_not_found)。"""
        repo = _fresh_repo()
        now = datetime.now(timezone.utc)
        acquire_claim("t-nb", "B", identity=Identity("bot", "cNB", "s2"),
                      repo_path=repo, now=now - timedelta(days=8))
        sweep_stale_active(repo, now=now, container_id="cME")  # 8d 邻居被扫
        result = restore_swept_claim(
            "t-nb", identity=Identity("me", "cME", "s1"), repo_path=repo
        )
        self.assertFalse(result.success)
        self.assertEqual(result.error, "claim_not_found")  # 不是 spoofable
        self.assertEqual(_statuses(repo)["cNB"].status, "abandoned")  # 原状不动

    def test_restore_requires_swept_record(self):
        repo = _fresh_repo()
        result = restore_swept_claim(
            "t-none", identity=Identity("me", "cME", "s1"), repo_path=repo
        )
        self.assertFalse(result.success)
        self.assertEqual(result.error, "claim_not_found")


if __name__ == "__main__":
    unittest.main()

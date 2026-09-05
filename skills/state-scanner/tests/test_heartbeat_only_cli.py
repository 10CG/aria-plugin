"""SC-32 / SC-28 第二臂 — ``phase1_gate.py --heartbeat-only`` 模式.

Spec: ``openspec/changes/a1-entry-claim-duplicate-work-guard`` TASK-010 (parent 2.7)。

A.1 认领之后, claim 需要有人定期刷新, 否则 SWEEP_TTL 一到就被扫成 abandoned。
``--heartbeat-only`` 是给编排层 (state-scanner 入口) 的轻量模式: 只刷新, 不认领、
不判碰撞、不 fetch, 且遥测走**独立分区**——心跳是高频动作, 混进 production 分区会把
``coordination_probe`` 的「闸门最近真被调用过」判据冲成噪声。

怎么会红:
  - baseline: ``--heartbeat-only`` 不存在 ⇒ argparse exit 2 ⇒ 全部用例红 (TASK-016 关闭)。
  - 坏实现 1 (只加 flag 不松 ``--raw-track-id`` 的 required=True): 无 carry-id 那条拿到
    ``error: the following arguments are required: --raw-track-id``, 零遥测记录 ⇒ 红。
  - 坏实现 2 (只 ``logger.debug`` 不落盘): 零新增记录 ⇒ 红。``logger`` 无 handler,
    子进程里 debug 全丢, 「我记了日志」在这里等于什么都没记。
  - 坏实现 3 (写进 production 分区): SC-28 第二臂的行数断言 ⇒ 红。
  - 放松了 acquire 路径的 required (非 heartbeat 模式也不要 carry-id): argparse 负控 ⇒ 红。
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# ⚠️ state-scanner 下有**两个同名 `lib` 包**: skill root 的 Layer L 包 (claim_lifecycle /
# coordination_ref / collision …) 与 scripts/lib (carry_forward / detailed_tasks …)。
# 本文件两边都要用 (lib.coordination_ref + scripts/phase1_gate), 所以 skill root 必须
# 排在 scripts 前面。
#
# 常见的 `if p not in sys.path: sys.path.insert(0, p)` 写法在这里**不可靠**: 用
# `python3 -m unittest` 从 skill root 跑时, cwd 已经以绝对路径躺在 sys.path[0], 于是
# skill root 那次插入被守卫跳过, 只有 scripts 被插到最前 —— 顺序当场反过来, `lib` 绑到
# scripts/lib, 报一个看不出所以然的
# `ModuleNotFoundError: No module named 'lib.coordination_ref'`。
# 所以这里 remove-then-insert, 让最终次序与谁先在路径上无关。
_SKILL_ROOT = str(Path(__file__).resolve().parents[1])
_SCRIPTS = str(Path(_SKILL_ROOT) / "scripts")
for _p in (_SCRIPTS, _SKILL_ROOT):   # 后插者排前 ⇒ 最终 [_SKILL_ROOT, _SCRIPTS, ...]
    while _p in sys.path:
        sys.path.remove(_p)
    sys.path.insert(0, _p)

import dataclasses  # noqa: E402
from lib.coordination_ref import bootstrap, read_claims, write_claim  # noqa: E402
# 断言对象取自 _telemetry_path 的返回值, 不硬编码文件名 —— 文件名归属仍是待裁项
# (tasks.md「待 owner 裁」#3), 硬编码会让本文件在三案里的任意两案下变假红/假绿。
from phase1_gate import _telemetry_path, _PROD_TELEMETRY_FILE  # noqa: E402

_GATE = Path(_SKILL_ROOT) / "scripts" / "phase1_gate.py"
_TRACK = "a1-spec-1a2b3c4d"


def _sh(cmd, cwd):
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True)


def _fresh_repo(with_bare_remote: bool = False):
    d = tempfile.mkdtemp()
    repo = Path(d)
    _sh(["git", "init", "-q"], d)
    _sh(["git", "config", "user.email", "t@t"], d)
    _sh(["git", "config", "user.name", "t"], d)
    (repo / "x").write_text("x")
    _sh(["git", "add", "-A"], d)
    _sh(["git", "commit", "-qm", "init"], d)
    bootstrap(repo, push=False)
    bare = None
    if with_bare_remote:
        bare = Path(tempfile.mkdtemp())
        _sh(["git", "init", "-q", "--bare", "."], str(bare))
        _sh(["git", "remote", "add", "origin", str(bare)], d)
    return repo, bare


def _run(repo: Path, *args: str):
    proc = subprocess.run(
        [sys.executable, str(_GATE), "--repo-path", str(repo), *args],
        capture_output=True, text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _records(repo: Path, source: str):
    path = _telemetry_path(repo, source)
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _prod_line_count(repo: Path) -> int:
    p = repo / ".aria" / _PROD_TELEMETRY_FILE
    return len(p.read_text(encoding="utf-8").splitlines()) if p.exists() else 0


def _remote_sha(bare: Path) -> str:
    out = subprocess.run(["git", "-C", str(bare), "for-each-ref", "--format=%(objectname) %(refname)"],
                         capture_output=True, text=True)
    return out.stdout.strip()


class TestHeartbeatOnlyNoTrack(unittest.TestCase):
    """SC-32: 没有 carry-id 时也必须**留痕**, 而不是静默什么都不做."""

    def test_skipped_no_track_emits_exactly_one_heartbeat_record(self):
        repo, bare = _fresh_repo(with_bare_remote=True)
        before_hb = len(_records(repo, "heartbeat"))
        before_claims = len(read_claims(repo).claims)
        before_sha = _remote_sha(bare)

        rc, out, err = _run(repo, "--heartbeat-only", "--phase", "A.1")

        self.assertEqual(rc, 0, err[-600:])
        recs = _records(repo, "heartbeat")
        self.assertEqual(len(recs) - before_hb, 1, "必须恰新增一条 (零条 = 静默, 多条 = 重复记)")
        rec = recs[-1]
        self.assertEqual(rec["source"], "heartbeat", "遥测须落 heartbeat 分区标签")
        self.assertEqual(rec["outcome"], "skipped_no_track")
        self.assertEqual(len(read_claims(repo).claims), before_claims, "不得写 claim")
        self.assertEqual(_remote_sha(bare), before_sha, "不得推远端")


class TestHeartbeatOnlyRefresh(unittest.TestCase):
    """refreshed 臂: 带 carry-id 时刷新既有 claim, 不新建."""

    def test_refreshes_existing_claim_without_creating_one(self):
        repo, _ = _fresh_repo()
        rc0, _, err0 = _run(repo, "--raw-track-id", _TRACK, "--phase", "A.1",
                            "--mode", "advisory", "--no-push")
        self.assertEqual(rc0, 0, err0[-600:])
        # 时间戳是秒精度: acquire 与随后的 heartbeat 常落在同一秒, 直接比对会得到
        # 「没刷新」的假红。把既有 claim 的 heartbeat_at 回拨一小时, 让「是否前进」
        # 变成确定性观察, 不依赖两次调用之间恰好跨秒。
        seeded = read_claims(repo).claims
        self.assertEqual(len(seeded), 1, "夹具前提: 恰一条 claim")
        write_claim(dataclasses.replace(seeded[0], heartbeat_at="2026-09-05T00:00:00Z"), repo)
        before = {(c.container, c.session): c.heartbeat_at for c in read_claims(repo).claims}
        self.assertEqual(list(before.values()), ["2026-09-05T00:00:00Z"], "回拨已生效")

        rc, out, err = _run(repo, "--heartbeat-only", "--raw-track-id", _TRACK, "--phase", "A.1")

        self.assertEqual(rc, 0, err[-600:])
        after = {(c.container, c.session): c.heartbeat_at for c in read_claims(repo).claims}
        self.assertEqual(set(after), set(before), "不得新建 claim")
        self.assertNotEqual(after, before, "既有 claim 的 heartbeat_at 必须被刷新")
        self.assertEqual(_records(repo, "heartbeat")[-1]["outcome"], "refreshed")


class TestHeartbeatPartitionIsolation(unittest.TestCase):
    """SC-28 第二臂: 心跳绝不污染 production 分区 (coordination_probe 的判据面)."""

    def test_three_heartbeat_runs_leave_production_count_unchanged(self):
        repo, _ = _fresh_repo()
        rc0, _, err0 = _run(repo, "--raw-track-id", _TRACK, "--phase", "A.1",
                            "--mode", "advisory", "--no-push")
        self.assertEqual(rc0, 0, err0[-600:])
        before = _prod_line_count(repo)

        for _ in range(3):
            rc, _, err = _run(repo, "--heartbeat-only", "--raw-track-id", _TRACK,
                              "--phase", "A.1")
            self.assertEqual(rc, 0, err[-600:])

        self.assertEqual(_prod_line_count(repo), before,
                         "心跳写进 production 分区会把「闸门最近被真调用过」的判据冲成噪声")


class TestArgparseNegativeControl(unittest.TestCase):
    """§非目标: 放松 required 只限 heartbeat 模式, acquire 路径仍须 fail-fast."""

    def test_non_heartbeat_mode_still_requires_raw_track_id(self):
        repo, _ = _fresh_repo()

        rc, out, err = _run(repo, "--phase", "B", "--mode", "advisory", "--no-push")

        self.assertEqual(rc, 2, out[-300:])
        self.assertIn("--raw-track-id", err)


class TestHeartbeatPush(unittest.TestCase):
    """push 复用 acquire/release 同一管道, 且受同一个 no_push 门 (deliverable 明写)."""

    def _seed_and_backdate(self, repo: Path):
        rc, _, err = _run(repo, "--raw-track-id", _TRACK, "--phase", "A.1",
                          "--mode", "advisory", "--no-push")
        self.assertEqual(rc, 0, err[-600:])
        seeded = read_claims(repo).claims
        write_claim(dataclasses.replace(seeded[0], heartbeat_at="2026-09-05T00:00:00Z"), repo)

    def test_no_push_flag_skips_push_but_still_refreshes_locally(self):
        repo, bare = _fresh_repo(with_bare_remote=True)
        self._seed_and_backdate(repo)
        before_sha = _remote_sha(bare)

        rc, out, err = _run(repo, "--heartbeat-only", "--raw-track-id", _TRACK,
                            "--phase", "A.1", "--no-push")

        self.assertEqual(rc, 0, err[-600:])
        parsed = json.loads(out)
        self.assertEqual(parsed["outcome"], "refreshed")
        self.assertIs(parsed["push_skipped"], True)
        self.assertIs(parsed["push_success"], False, "主动跳过 ≠ 未尝试 (None) ≠ 推失败")
        self.assertEqual(parsed["push_skipped_reason"], "cli_flag")
        self.assertEqual(_remote_sha(bare), before_sha, "--no-push 下远端不得动")
        self.assertNotEqual(read_claims(repo).claims[0].heartbeat_at,
                            "2026-09-05T00:00:00Z", "本地刷新照常")

    def test_refresh_without_no_push_publishes_to_remote(self):
        repo, bare = _fresh_repo(with_bare_remote=True)
        self._seed_and_backdate(repo)
        before_sha = _remote_sha(bare)

        rc, out, err = _run(repo, "--heartbeat-only", "--raw-track-id", _TRACK,
                            "--phase", "A.1")

        self.assertEqual(rc, 0, err[-600:])
        parsed = json.loads(out)
        self.assertIs(parsed["push_skipped"], False)
        self.assertIs(parsed["push_success"], True, "可达 remote 下刷新应真的推上去")
        self.assertNotEqual(_remote_sha(bare), before_sha,
                            "没有这条对照, 上一条的「远端不动」恒真")

    def test_no_track_run_never_attempts_a_push(self):
        """没刷到东西就不该占一次网络往返 —— push_success 保持 None (未尝试)."""
        repo, _ = _fresh_repo(with_bare_remote=True)

        rc, out, err = _run(repo, "--heartbeat-only", "--phase", "A.1")

        self.assertEqual(rc, 0, err[-600:])
        parsed = json.loads(out)
        self.assertIsNone(parsed["push_success"])
        self.assertIs(parsed["push_skipped"], False)


if __name__ == "__main__":
    unittest.main()

"""SC-2 / SC-8 / SC-29 — A.1 入口认领的 CLI 全链路 (phase1_gate.py subprocess).

Spec: ``openspec/changes/a1-entry-claim-duplicate-work-guard`` TASK-007 (parent 2.4).

lib 层的测试锁不住 kwarg 穿线拼写错 (先例: ``test_release_by_track.py``
``TestPhase1GateLinkedIssueCli``), 所以这三条 SC 一律走真 subprocess + 真 JSON。
全部带 ``--no-push``: 夹具仓没有 remote, 也绝不能碰生产 coordination ref。

怎么会红:
  - baseline (aria ``d69091d`` .. ``7dd0135``): ``--include-terminal`` 是未知参数,
    argparse 以 exit 2 拒绝 ⇒ **本文件全部用例红**。SC-2 / SC-29 四臂的语义在 baseline
    本来就成立 (它们是回归守卫), 红只因这个 flag 还不存在 —— flag 落地 (TASK-014) 后
    它们转绿即证明「放宽门控没有改坏默认路径」。
  - SC-8 是唯一在语义上必红的一条: 终态 claim 今天无论如何都被 ``:272`` 丢弃。
  - 坏实现 A「门控重写后 --linked-issue 路径丢失」⇒ SC-2 正臂双方为空 ⇒ 红。
  - 坏实现 B「--include-terminal = 跳过全部 continue」⇒ 自排除失效 ⇒ SC-2 负控 + SC-29 两组红。
  - 删掉 ``lib/collision.py`` 自排除两行 ⇒ 同上三条红。
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_SKILL_ROOT = str(Path(__file__).resolve().parents[1])
if _SKILL_ROOT not in sys.path:
    sys.path.insert(0, _SKILL_ROOT)

from lib.claim_lifecycle import acquire_claim, release_claim_by_track  # noqa: E402
from lib.coordination_ref import bootstrap, read_claims  # noqa: E402
from lib.identity import Identity  # noqa: E402

_GATE = Path(_SKILL_ROOT) / "scripts" / "phase1_gate.py"
_ISSUE = "10CG/Aria#174"
_TRACK_A = "spec-x-aaaa1111"
_TRACK_B = "spec-x-bbbb2222"


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


def _gate(repo: Path, track: str, *extra: str):
    """跑一次 phase1_gate CLI, 返回 (returncode, parsed_json_or_None, stderr)."""
    proc = subprocess.run(
        [sys.executable, str(_GATE),
         "--raw-track-id", track, "--phase", "A.1", "--mode", "advisory",
         "--repo-path", str(repo), "--no-push", *extra],
        capture_output=True, text=True,
    )
    try:
        parsed = json.loads(proc.stdout)
    except (ValueError, TypeError):
        parsed = None
    return proc.returncode, parsed, proc.stderr


def _seed_other_container(repo: Path, track: str, container: str, session: str = "s1",
                          status: str = "active"):
    """在另一个容器名下种一条 claim; status 为终态时经生产路径 release 过去."""
    ident = Identity("peer", container, session)
    acquire_claim(track, "A.1", identity=ident, repo_path=repo, linked_issue=_ISSUE)
    if status != "active":
        release_claim_by_track(track, status=status, identity=ident, repo_path=repo)
    return ident


class TestSc2MutualVisibility(unittest.TestCase):
    """SC-2: 同 issue、不同 track-id 的两容器互相看得见 (baseline 语义即绿)."""

    def test_two_containers_same_issue_different_tracks_see_each_other(self):
        repo = _fresh_repo()
        _seed_other_container(repo, _TRACK_A, "cPEER")

        rc, out, err = _gate(repo, _TRACK_B, "--linked-issue", _ISSUE, "--include-terminal")

        self.assertEqual(rc, 0, err[-600:])
        overlap = out["linked_issue_overlap"]
        self.assertEqual(len(overlap), 1, overlap)
        hit = overlap[0]
        for field in ("track_id", "container", "claimed_at", "status", "linked_issue"):
            self.assertIn(field, hit)
        self.assertEqual(hit["track_id"], _TRACK_A)
        self.assertEqual(hit["container"], "cPEER")
        self.assertEqual(hit["status"], "active")
        self.assertEqual(hit["linked_issue"], _ISSUE)

    def test_reverse_direction_also_surfaces(self):
        """反向: 先有 B, 再由 A 认领 ⇒ A 看见 B."""
        repo = _fresh_repo()
        _seed_other_container(repo, _TRACK_B, "cPEER")

        rc, out, err = _gate(repo, _TRACK_A, "--linked-issue", _ISSUE, "--include-terminal")

        self.assertEqual(rc, 0, err[-600:])
        self.assertEqual([h["track_id"] for h in out["linked_issue_overlap"]], [_TRACK_B])

    def test_same_track_id_in_both_containers_yields_no_overlap(self):
        """SC-2 负控: 两容器用**同一串** ⇒ 自排除 ⇒ overlap 为空 (reconcile 的活)."""
        repo = _fresh_repo()
        _seed_other_container(repo, _TRACK_A, "cPEER")

        rc, out, err = _gate(repo, _TRACK_A, "--linked-issue", _ISSUE, "--include-terminal")

        self.assertEqual(rc, 0, err[-600:])
        self.assertEqual(out["linked_issue_overlap"], [])


class TestSc8TerminalVisibility(unittest.TestCase):
    """SC-8: 终态 claim 只在 --include-terminal 时可见 (唯一语义上必红的一条)."""

    def _run_terminal_case(self, status: str, extra: tuple):
        repo = _fresh_repo()
        _seed_other_container(repo, _TRACK_A, "cPEER", status=status)
        seeded = [c for c in read_claims(repo).claims if c.container == "cPEER"]
        self.assertEqual([c.status for c in seeded], [status], "夹具前提: 种子已是终态")
        return _gate(repo, _TRACK_B, "--linked-issue", _ISSUE, *extra)

    def test_done_claim_visible_with_include_terminal(self):
        rc, out, err = self._run_terminal_case("done", ("--include-terminal",))
        self.assertEqual(rc, 0, err[-600:])
        overlap = out["linked_issue_overlap"]
        self.assertEqual([h["track_id"] for h in overlap], [_TRACK_A])
        self.assertEqual(overlap[0]["status"], "done")

    def test_abandoned_claim_visible_with_include_terminal(self):
        rc, out, err = self._run_terminal_case("abandoned", ("--include-terminal",))
        self.assertEqual(rc, 0, err[-600:])
        overlap = out["linked_issue_overlap"]
        self.assertEqual([h["track_id"] for h in overlap], [_TRACK_A])
        self.assertEqual(overlap[0]["status"], "abandoned")

    def test_default_path_still_omits_terminal_claims(self):
        """不带 flag ⇒ 行为逐字节不变 (默认路径的回归守卫)."""
        rc, out, err = self._run_terminal_case("done", ())
        self.assertEqual(rc, 0, err[-600:])
        self.assertEqual(out["linked_issue_overlap"], [])


class TestSc29SelfExclusion(unittest.TestCase):
    """SC-29 两组: own claim 无论 active 还是终态, 都不出现在自己的 overlap 里."""

    def test_group1_own_active_claim_excluded(self):
        repo = _fresh_repo()
        rc1, out1, err1 = _gate(repo, _TRACK_A, "--linked-issue", _ISSUE, "--include-terminal")
        self.assertEqual(rc1, 0, err1[-600:])
        own_container = out1["own_claim"]["container"]

        rc2, out2, err2 = _gate(repo, _TRACK_A, "--linked-issue", _ISSUE, "--include-terminal")

        self.assertEqual(rc2, 0, err2[-600:])
        self.assertEqual(out2["linked_issue_overlap"], [])
        self.assertNotIn(own_container,
                         [h["container"] for h in out2["linked_issue_overlap"]])

    def test_group2_own_terminal_claim_still_excluded(self):
        """R3/QA-F4: 只测 active 那组视为未满足 —— 终态自排除是独立的一条."""
        repo = _fresh_repo()
        rc1, out1, err1 = _gate(repo, _TRACK_A, "--linked-issue", _ISSUE, "--include-terminal")
        self.assertEqual(rc1, 0, err1[-600:])
        own = out1["own_claim"]
        release_claim_by_track(
            _TRACK_A, status="done",
            identity=Identity(own["owner"], own["container"], own["session"]),
            repo_path=repo,
        )
        self.assertEqual(
            [c.status for c in read_claims(repo).claims if c.container == own["container"]],
            ["done"], "夹具前提: 自己那条已是终态",
        )

        rc2, out2, err2 = _gate(repo, _TRACK_A, "--linked-issue", _ISSUE, "--include-terminal")

        self.assertEqual(rc2, 0, err2[-600:])
        self.assertEqual(out2["linked_issue_overlap"], [])


if __name__ == "__main__":
    unittest.main()

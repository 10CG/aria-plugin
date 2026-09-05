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
from lib.coordination_ref import apply_tree_edits, bootstrap, read_claims  # noqa: E402
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


# ---------------------------------------------------------------------------
# 故障注入 —— 手段选择的实测依据 (TASK-008 verification「三选一, 钉一种」)
#
#   (a) 把 refs/aria/coordination 指向非 tree 对象: **实测行不通**。read_claims
#       全程 fail-soft, 损坏 ref 只得到 ReadClaimsResult(errors=['ls_tree_failed:
#       fatal: not a tree object'], ref_exists=True), 从不抛 ⇒ 触不到 phase1_gate
#       的 except 分支, 该手段结构上无法验 SC-33 / SC-25。
#   (b) PYTHONPATH 前插 lib/coordination_ref.py 替身: lib 是包, 其模块之间用相对
#       import 交叉引用, 只影子化一个模块就得把其余全部重导出, 脆且噪声大。
#   (c) **本文件钉这一种** —— 复用 test_failure_injection.py 的 module-boundary
#       思路, 但搬进子进程: 小 runner 先 import phase1_gate, 替换它模块全局里的
#       目标符号, 再调 _main()。argparse / 门控 / try-except / JSON 输出全程真跑,
#       只有被点名的那一个符号是假的。
# ---------------------------------------------------------------------------

_INJECT_RUNNER = """import sys
sys.path.insert(0, {scripts!r})
import phase1_gate

_orig = getattr(phase1_gate, {target!r})


def _boom(*a, **k):
    # 只在 _main() 自己的 advisory 块里抛。read_claims 同时被闸门主体
    # (_run_gate_impl 的 Step 5) 调用, 无差别替换会把闸门一起打崩, 测到的就不是
    # SC-33 要的那个 except 分支了 —— 实跑一次即暴露 (rc=1 + _run_gate_impl 栈)。
    if sys._getframe(1).f_code.co_name == "_main":
        raise RuntimeError({msg!r})
    return _orig(*a, **k)


assert hasattr(phase1_gate, {target!r}), "注入目标不在 phase1_gate 模块全局里"
setattr(phase1_gate, {target!r}, _boom)
sys.exit(phase1_gate._main())
"""


def _gate_injected(repo: Path, track: str, target: str, *extra: str):
    """跑 phase1_gate CLI, 但让 ``target`` 在 ``_main()` 的 advisory 块里抛异常."""
    runner = Path(tempfile.mkdtemp()) / "run_injected.py"
    runner.write_text(
        _INJECT_RUNNER.format(
            scripts=str(_GATE.parent),
            target=target,
            msg="injected failure: %s" % target,
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, str(runner),
         "--raw-track-id", track, "--phase", "A.1", "--mode", "advisory",
         "--repo-path", str(repo), "--no-push", *extra],
        capture_output=True, text=True,
    )
    try:
        parsed = json.loads(proc.stdout)
    except (ValueError, TypeError):
        parsed = None
    return proc.returncode, parsed, proc.stderr


def _seed_unknown_schema_claim(repo: Path, linked_issue: str = _ISSUE):
    """种一份 schema_version: "2" 的 claim blob (parse_claim 会给 unknown 哨兵).

    哨兵的 track_id / owner / container 等全是空串, linked_issue 为 None
    (claim_schema 的 dataclass 默认值) —— 所以它天然被 overlap 的第二道门丢弃,
    而不是被终态门丢弃。这正是 SC-24 要钉的: 计数看得见, 但绝不混进 overlap[]。
    """
    blob = (
        'schema_version: "2"\n'
        "track_id: future-track-cafe1234\n"
        "owner: peer\n"
        "container: cFUTURE\n"
        "session: s9\n"
        "phase: A.1\n"
        "status: active\n"
        "claimed_at: 2026-09-05T10:00:00Z\n"
        "heartbeat_at: 2026-09-05T10:00:00Z\n"
        f"linked_issue: {linked_issue}\n"
    )
    apply_tree_edits([("add", "claims/cFUTURE/s9.yaml", blob)], repo)


def _unreachable_remote(repo: Path):
    """让 Step 4 health_check_fetch 降级: origin 指向不存在的路径."""
    _sh(["git", "remote", "add", "origin", str(repo / "no-such-remote.git")], str(repo))


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


class TestSc24UnknownSchemaClaims(unittest.TestCase):
    """SC-24: 未知 schema 的 claim 要被**计数**, 但绝不混进 overlap[]."""

    def test_unknown_schema_claim_counted_but_not_in_overlap(self):
        repo = _fresh_repo()
        _seed_unknown_schema_claim(repo)
        seeded = [c for c in read_claims(repo).claims if c.status == "unknown"]
        self.assertEqual(len(seeded), 1, "夹具前提: 种子被解析成 unknown 哨兵")
        self.assertIsNone(seeded[0].linked_issue,
                          "夹具前提: 哨兵的 linked_issue 是 None (被第二道门丢弃, 非终态门)")

        rc, out, err = _gate(repo, _TRACK_B, "--linked-issue", _ISSUE, "--include-terminal")

        self.assertEqual(rc, 0, err[-600:])
        self.assertIn("unknown_schema_claims", out)
        self.assertGreaterEqual(out["unknown_schema_claims"], 1)
        # 强行放行哨兵的实现会塞进三个空串字段 —— 逐个否掉
        for hit in out["linked_issue_overlap"]:
            self.assertNotEqual(hit["track_id"], "", "哨兵被放行进了 overlap[]")
            self.assertNotEqual(hit["container"], "")
            self.assertNotEqual(hit["owner"], "")

    def test_keys_absent_when_neither_flag_given(self):
        """四态之一: 两个 flag 都不给 ⇒ 整块不跑 ⇒ 两个键都缺席 (additive 契约)."""
        repo = _fresh_repo()
        _seed_unknown_schema_claim(repo)

        rc, out, err = _gate(repo, _TRACK_B)

        self.assertEqual(rc, 0, err[-600:])
        self.assertNotIn("linked_issue_overlap", out)
        self.assertNotIn("unknown_schema_claims", out)


class TestSc33ReadClaimsRaises(unittest.TestCase):
    """SC-33: read_claims 抛 ⇒ 两个键都必须是 null, 且 error 非空."""

    def test_both_keys_null_and_error_set(self):
        repo = _fresh_repo()

        # 不带 --linked-issue: 门控须已放宽到 --include-terminal 也能进块
        rc, out, err = _gate_injected(repo, _TRACK_B, "read_claims", "--include-terminal")

        self.assertEqual(rc, 0, err[-600:])
        # 用 assertIn + assertIsNone, 不用 .get(k, 0) —— 后者会把「键缺席」读成 0,
        # 正是 M-4 在自己的修复里复发的那种静默
        self.assertIn("linked_issue_overlap", out)
        self.assertIsNone(out["linked_issue_overlap"])
        self.assertIn("unknown_schema_claims", out,
                      "只赋 overlap 而漏赋 unknown 的实现在此必红")
        self.assertIsNone(out["unknown_schema_claims"])
        self.assertIn("linked_issue_overlap_error", out)
        self.assertTrue(out["linked_issue_overlap_error"])

    def test_gate_itself_still_proceeds(self):
        """fail-soft: overlap advisory 崩了不许把闸门带下水."""
        repo = _fresh_repo()

        rc, out, err = _gate_injected(repo, _TRACK_B, "read_claims", "--include-terminal")

        self.assertEqual(rc, 0, err[-600:])
        self.assertTrue(out["proceed"])


class TestSc25OverlapRaises(unittest.TestCase):
    """SC-25 代码臂: linked_issue_overlaps 抛 ⇒ overlap 为 null 而非 []."""

    def test_overlap_null_not_empty_list(self):
        repo = _fresh_repo()
        _seed_other_container(repo, _TRACK_A, "cPEER")

        rc, out, err = _gate_injected(repo, _TRACK_B, "linked_issue_overlaps",
                                      "--linked-issue", _ISSUE)

        self.assertEqual(rc, 0, err[-600:])
        self.assertIn("linked_issue_overlap", out)
        self.assertIsNone(out["linked_issue_overlap"],
                          "baseline 在 except 里写 [] —— 与「真的没有碰撞」不可分辨")
        self.assertTrue(out.get("linked_issue_overlap_error"))


class TestSc10FetchDegraded(unittest.TestCase):
    """SC-10: Step 4 fetch 降级 ⇒ error 携带 fetch_degraded, 但仍放行."""

    def test_error_field_carries_fetch_degraded(self):
        repo = _fresh_repo()
        _unreachable_remote(repo)

        rc, out, err = _gate(repo, _TRACK_A)

        self.assertEqual(rc, 0, err[-600:])
        self.assertEqual(out["error"], "fetch_degraded")
        self.assertTrue(out["proceed"], "降级是 advisory, 不阻断")

    def test_reachable_remote_leaves_error_null(self):
        """对照臂 —— 没有它, 上一条恒真.

        实测: 连 remote 都没有的仓同样降级, 所以「不可达 remote ⇒ 降级」这句话
        单独立不住 (夹具删掉也会绿)。只有配一个**真的能 fetch** 的 bare remote,
        才证明 error 字段跟踪的是 fetch 是否真降级, 而不是恒为 fetch_degraded。
        """
        bare = Path(tempfile.mkdtemp())
        _sh(["git", "init", "-q", "--bare", "."], str(bare))
        repo = _fresh_repo()
        _sh(["git", "remote", "add", "origin", str(bare)], str(repo))

        rc, out, err = _gate(repo, _TRACK_A)

        self.assertEqual(rc, 0, err[-600:])
        self.assertIsNone(out["error"], "fetch 正常时 error 必须仍是 null")


class TestFourStateDistinguishable(unittest.TestCase):
    """§2.4b: 四种输出态在同一组夹具上两两可辨 (任意两态相同即失去诊断力)."""

    def _state(self, repo, *extra, inject=None):
        if inject:
            _, out, _ = _gate_injected(repo, _TRACK_B, inject, *extra)
        else:
            _, out, _ = _gate(repo, _TRACK_B, *extra)
        if out is None:
            # CLI 未产出 JSON (baseline: argparse 拒 --include-terminal, exit 2)。
            # 归一到同一个标记, 使四态塌缩为「可辨数 < 4」的干净 FAIL, 而不是 TypeError。
            return "no_json"
        return (
            "absent" if "linked_issue_overlap" not in out
            else "null" if out["linked_issue_overlap"] is None
            else "unknown_positive" if out.get("unknown_schema_claims", 0) > 0
            else "empty"
        )

    def test_four_states_are_pairwise_distinct(self):
        states = {
            "键缺席": self._state(_fresh_repo()),
            "空列表": self._state(_fresh_repo(), "--linked-issue", _ISSUE,
                                  "--include-terminal"),
            "unknown>0": self._state(
                (lambda r: (_seed_unknown_schema_claim(r), r)[1])(_fresh_repo()),
                "--linked-issue", _ISSUE, "--include-terminal"),
            "null+error": self._state(_fresh_repo(), "--include-terminal",
                                      inject="read_claims"),
        }
        self.assertEqual(
            len(set(states.values())), 4,
            f"四态未两两可辨: {states}",
        )


if __name__ == "__main__":
    unittest.main()

"""Tests for scripts/groom.py — issue-groomer CLI 主入口 (TASK-017).

Covers the TASK-017 verification bullets:
  1. CLI 全链路 smoke: fetch (mock) → tier_a → fingerprint → incremental →
     diffseg → groom-report 产出经 schema 校验通过 (TestEndToEndReport /
     TestCliSmoke — 进程内注入 fake runner + subprocess 实跑两条路径)。
  2. SC-5 实现面: apply_payload 差集 + idempotent 字段在本组装层计算
     (TestEndToEndReport.test_labels_payload_difference_and_no_remove)。
  3. harness 自报参数落 provenance 面 (裁定③ 第一层) — 顶层 report.harness
     + state.last_run.provenance + Tier B 复用门 (TestAssessmentGate)。
  4. 裁定④ 两文件写回: state 原子写 / 全程不触 groom-assessments.json —
     多轮跑后该文件字节不变 (TestAssessmentGate / TestCliSmoke)。
  5. 增量重跑: 第二轮 reused 为主 + drift 非空 (title 改动触发 reclassify,
     drift from/to = Tier A category 旧→新) (TestIncrementalRerun)。
  6. repos 作用域解析: --repos / config repos 键 / scan_submodules+
     .gitmodules 推导 (state-scanner 同款) / 三者皆无 ⇒ ConfigError
     (TestReposResolution)。
  7. B.3 修复轮 (fetch/作用域/CLI 族): A-1 整仓 fetch 失败 ⇒ exit 1 不写
     state (TestFetchFailureAborts) / E-1 classify 行级错误归因到仓
     (TestClassifyRowErrorAborts) / D-1 报告写盘先于 state
     (TestReportOutOrdering) / exit-2 argparse 预校验 (TestArgPrevalidation)
     / port URL (TestExtractOwnerRepoPort) / B-1·B-2 作用域降级三态
     (TestScopeDegradation) / A-3 降级告知落 state (state 形态测试)。

全 mock (fake runner 零网络); CLI smoke 经 --runner-bin 注入 fake wrapper
脚本 + GROOM_FAKE_CORPUS env (真 ForgejoCliRunner subprocess 通道)。
时钟注入 --now (防时移 flaky); 类名 Test* 前缀 (pytest 收集规则)。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

# Add scripts/ to path for direct module import (house convention).
_HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(_HERE), "scripts")
sys.path.insert(0, SCRIPTS)

import groom  # noqa: E402
from lib import fetch  # noqa: E402
from lib.schema_validate import mini_validate  # noqa: E402  # 生产层 SOT (B.3)

GROOM_PY = os.path.join(SCRIPTS, "groom.py")
SCHEMA_PATH = os.path.join(SCRIPTS, "groom-report.schema.json")

NOW_T0 = "2026-10-19T12:00:00Z"
NOW_T1 = "2026-10-19T13:00:00Z"


# ---------------------------------------------------------------- fixture helpers

def api_issue(number, *, title, labels=None, comments=0, body="",
              created="2026-10-10T10:00:00Z", updated=None):
    """Forgejo issue-list 行真 API 形态 (对齐 test_fetch.make_issue)。"""
    return {
        "number": number,
        "title": title,
        "labels": [{"name": n} for n in (labels or [])],
        "created_at": created,
        "updated_at": updated or created,
        "body": body,
        "comments": comments,
        "pull_request": None,
    }


def api_comment(cid, *, body="comment body",
                created="2026-10-15T16:58:30Z", updated=None):
    return {"id": cid, "body": body, "created_at": created,
            "updated_at": updated or created}


def make_corpus():
    """3 issue × 2 仓 (Aria#233 tracker 前缀 / Aria#241 无信号 /
    aria-plugin#208 bug 前缀+label) — 覆盖分类三形态与差集三形态。"""
    return {
        "repos": {
            "10CG/Aria": [
                api_issue(233, title="[tracker] v2.0 M6 dispatch tracking",
                          comments=0, updated="2026-10-10T10:00:00Z"),
                api_issue(241, title="讨论型条目 (无前缀无 label)",
                          comments=2, created="2026-09-20T10:00:00Z",
                          updated="2026-10-01T10:00:00Z"),
            ],
            "10CG/aria-plugin": [
                api_issue(208, title="[bug] issue-list fetch limit=50 静默丢数据",
                          labels=["bug"], comments=1,
                          created="2026-07-14T10:00:00Z",
                          updated="2026-09-01T10:00:00Z"),
            ],
        },
        "comments": {
            "10CG/Aria#241": [
                api_comment(9001), api_comment(9002, body="second"),
            ],
            "10CG/aria-plugin#208": [api_comment(9100)],
        },
    }


class FakeRunner:
    """corpus-driven fake CLI 通道: issue-list 分页 (page>=2 ⇒ 空页终止) +
    comments 端点全量 (对账计数由 fetch 层执行)。"""

    def __init__(self, corpus):
        self.corpus = corpus
        self.calls = []

    def call(self, method, endpoint, payload=None):
        assert method == "GET", f"unexpected method {method!r}"
        self.calls.append(endpoint)
        path, _, qs = endpoint.partition("?")
        page = 1
        for kv in qs.split("&"):
            if kv.startswith("page="):
                page = int(kv[5:])
        if page >= 2:
            return []
        m = re.match(r"^/repos/([^/]+)/([^/]+)/issues$", path)
        if m:
            return self.corpus["repos"].get(f"{m.group(1)}/{m.group(2)}", [])
        m = re.match(r"^/repos/([^/]+)/([^/]+)/issues/(\d+)/comments$", path)
        if m:
            return self.corpus["comments"].get(
                f"{m.group(1)}/{m.group(2)}#{m.group(3)}", []
            )
        raise AssertionError(f"unexpected endpoint {endpoint!r}")


def make_args(tmp_path, extra=()):
    argv = [
        "--repos", "Aria", "aria-plugin",
        "--project-root", str(tmp_path),
        "--harness", "test-harness",
        "--model-id", "test-model",
        "--now", NOW_T0,
        "--quiet",
        *extra,
    ]
    return groom.parse_args(argv)


def _init_git_project(tmp_path):
    """git 项目 fixture (B-2 strict 模式的前提): 主仓 origin → 10CG/Aria +
    .gitmodules 声明 submodule aria-plugin (目录同路径, origin → 10CG/
    aria-plugin)。幂等 (已 init 则跳过)。无 commit — rev-parse HEAD 失败
    ⇒ git_heads=None ⇒ 上下文降级面 (A-3) 如实可见, 不影响判变。"""
    if (tmp_path / ".git").exists():
        return
    def git(*args, cwd=None):
        subprocess.run(["git", "-C", str(cwd or tmp_path), *args],
                       check=True, capture_output=True)
    git("init", "-q")
    git("remote", "add", "origin", "git@forgejo.10cg.pub:10CG/Aria.git")
    git("config", "-f", ".gitmodules", "submodule.aria-plugin.path", "aria-plugin")
    git("config", "-f", ".gitmodules",
        "submodule.aria-plugin.url",
        "https://forgejo.10cg.pub/10CG/aria-plugin.git")
    sub = tmp_path / "aria-plugin"
    sub.mkdir(exist_ok=True)
    git("init", "-q", cwd=sub)
    git("remote", "add", "origin",
        "https://forgejo.10cg.pub/10CG/aria-plugin.git", cwd=sub)


def run(tmp_path, corpus, extra=(), now=None, runner=None):
    """进程内跑全编排 (fake runner 注入 + request_interval=0), 返回 report。

    ``now`` 非空时以 ``--now <now>`` 前置覆盖 (argparse 后值胜);
    ``runner`` 缺省 FakeRunner(corpus) — 失败注入测试传自定义 runner。"""
    _init_git_project(tmp_path)  # --repos 显式 ⇒ strict 映射须可解析 (B-2)
    argv_extra = ["--now", now, *extra] if now is not None else list(extra)
    args = make_args(tmp_path, argv_extra)
    return groom.run_pipeline(args, runner=runner or FakeRunner(corpus),
                              request_interval=0)


def state_path_of(tmp_path):
    return tmp_path / ".aria" / "cache" / "groom-state.json"


def current_context_key(tmp_path):
    """从已落盘 state 取本轮上下文指纹键 (DEC 裁定-9 Tier B 上下文门比对面)。

    两段式 fixture 的桥: r1 跑完写 state (last_run.context_key = 记录面),
    适配层评估条目以该键落档 (契约必填), r2 门激活比对。"""
    state = json.loads(state_path_of(tmp_path).read_text(encoding="utf-8"))
    return state["last_run"]["context_key"]


def write_assessments(tmp_path, entries):
    path = tmp_path / ".aria" / "groom-assessments.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": 1, "assessments": entries},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def entry_by_key(report, key):
    for e in report["issues"]:
        if f"{e['repo']}#{e['number']}" == key:
            return e
    raise AssertionError(f"issue {key} not in report")


# ── 1. 端到端报告形态 (SC-5 实现面 + schema 断言) ───────────────────────────


class TestEndToEndReport:
    def test_report_passes_schema_and_top_shape(self, tmp_path):
        report = run(tmp_path, make_corpus())
        schema = json.loads(Path(SCHEMA_PATH).read_text(encoding="utf-8"))
        errors = mini_validate(report, schema)
        assert errors == [], "\n".join(errors)
        assert report["snapshot_schema_version"] == "1.1"
        assert report["harness"] == "test-harness"  # 裁定③ 第一层: 自报落顶层
        assert report["generated_at"] == "2026-10-19T12:00:00Z"
        assert [(r["repo"], r["open_issues"]) for r in report["repos"]] == [
            ("Aria", 2), ("aria-plugin", 1),
        ]
        s = report["summary"]
        assert s["total_issues"] == 3 == len(report["issues"])
        assert s["by_repo"] == {"Aria": 2, "aria-plugin": 1}
        assert s["by_category"] == {"tracker": 1, "unknown": 1, "bug": 1}
        assert s["assessed"] == 0  # 无 assessments 文件 ⇒ 门空转

    def test_labels_payload_difference_and_no_remove(self, tmp_path):
        report = run(tmp_path, make_corpus())
        e233 = entry_by_key(report, "Aria#233")
        assert e233["labels_payload"]["existing"] == []
        assert e233["labels_payload"]["suggested"] == ["tracker"]
        ap = e233["labels_payload"]["apply_payload"]
        assert ap["add"] == ["tracker"]  # SC-5: suggested − existing 差集
        assert ap["idempotent"] is True
        assert ap["repo"] == "Aria" and ap["number"] == 233

        e208 = entry_by_key(report, "aria-plugin#208")
        lp = e208["labels_payload"]
        assert lp["existing"] == ["bug"] == lp["suggested"]
        assert lp["apply_payload"]["add"] == []  # 已有标签必不在 add 内

        e241 = entry_by_key(report, "Aria#241")
        assert e241["labels_payload"]["suggested"] == []  # unknown 不猜

        for e in report["issues"]:
            payload = e["labels_payload"]
            assert set(payload) == {"existing", "suggested", "apply_payload"}
            assert "remove" not in payload["apply_payload"]  # 封闭键集
            assert set(payload["apply_payload"]) == {
                "repo", "number", "add", "idempotent",
            }
            existing = set(payload["existing"])
            assert not (set(payload["apply_payload"]["add"]) & existing)

    def test_signal_mapping_and_confidence_source(self, tmp_path):
        report = run(tmp_path, make_corpus())
        e208 = entry_by_key(report, "aria-plugin#208")
        # tier_a kind 连字符 → schema SignalSource 下划线; 信号序
        # title-prefix → label → staleness → activity
        assert [s["source"] for s in e208["signals"]] == [
            "title_prefix", "label", "staleness", "activity",
        ]
        assert e208["signals"][0]["rule"] == "prefix:bug"
        assert "[bug]" in e208["signals"][0]["detail"]
        assert e208["signals"][1]["rule"] == "label:bug"
        assert e208["signals"][2]["rule"] == "staleness:30-90d"
        assert e208["signals"][3]["rule"] == "activity:1-2"
        assert e208["confidence_source"] == [
            "title_prefix", "label", "staleness", "activity",
        ]
        e241 = entry_by_key(report, "Aria#241")
        assert e241["category"] == "unknown"
        # 无分类信号 (title_prefix/label), 但属性信号 (staleness/activity)
        # 照样枚举 — tier_a 契约: 属性信号不参与 category 裁决。
        assert e241["confidence_source"] == ["staleness", "activity"]


# ── 2. 增量重跑 (reused 为主 + drift 非空 + state 形态) ─────────────────────


class TestIncrementalRerun:
    def test_second_run_reused_majority_and_drift_nonempty(self, tmp_path):
        corpus_v1 = make_corpus()
        report1 = run(tmp_path, corpus_v1)
        assert report1["diff"]["baseline_run"] is True
        assert report1["diff"]["new"] == []  # baseline: no-diff 空集语义

        corpus_v2 = make_corpus()
        corpus_v2["repos"]["10CG/Aria"][0]["title"] = \
            "[bug] v2.0 M6 dispatch tracking"  # 前缀翻转: tracker → bug
        report2 = run(tmp_path, corpus_v2, now=NOW_T1)

        assert report2["diff"]["baseline_run"] is False
        assert report2["diff"]["new"] == []
        drift = report2["diff"]["drift"]
        assert len(drift) == 1
        assert drift[0]["repo"] == "Aria" and drift[0]["number"] == 233
        assert drift[0]["from"] == "tracker"  # 旧 category (对照 state)
        assert drift[0]["to"] == "bug"        # 新 category (本轮分类)
        assert report2["diff"]["drift_total"] == 1
        assert report2["diff"]["drift_truncated"] is False
        assert report2["summary"]["diff_counts"] == {
            "new": 0, "closed": 0, "drift": 1,
        }

        # reused 为主: 未变条目 last_classified_at 逐字续传 (复用不是重新分类)
        state = json.loads(state_path_of(tmp_path).read_text(encoding="utf-8"))
        assert state["issues"]["Aria#241"]["last_classified_at"] == \
            "2026-10-19T12:00:00Z"
        assert state["issues"]["aria-plugin#208"]["last_classified_at"] == \
            "2026-10-19T12:00:00Z"
        assert state["issues"]["Aria#233"]["last_classified_at"] == \
            "2026-10-19T13:00:00Z"  # reclassify ⇒ 刷新
        assert state["issues"]["Aria#233"]["tier_a"]["category"] == "bug"

    def test_state_file_written_shape(self, tmp_path):
        run(tmp_path, make_corpus())
        path = state_path_of(tmp_path)
        assert path.is_file()
        state = json.loads(path.read_text(encoding="utf-8"))
        assert state["schema_version"] == 1
        assert state["last_run"]["provenance"] == {
            "harness": "test-harness", "model_id": "test-model",
        }
        ctx = state["last_run"]["context_fingerprint"]
        assert set(ctx) == {
            "openspec_changes_hash", "git_heads", "handoff_pointer",
            "taxonomy_hash", "degraded",
        }
        # A-3 E2E: fixture 仓无 commit (git_heads=None) 且无 handoff 文件
        # ⇒ 降级分量如实点名 (零告知 = 假绿); B-1: 显式 --repos 映射全成
        # ⇒ scope_degraded 空清单 (已核验零降级)。
        assert ctx["degraded"] == ["git_heads", "handoff_pointer"]
        assert state["last_run"]["degraded"] == ["git_heads", "handoff_pointer"]
        assert state["last_run"]["scope_degraded"] == []
        # DEC 裁定-9 记录面: last_run 便捷单键 = 全量面的 canonical 指纹
        ck = state["last_run"]["context_key"]
        assert isinstance(ck, str) and len(ck) == 64
        assert int(ck, 16) >= 0  # hex 形态
        assert set(state["issues"]) == {"Aria#233", "Aria#241", "aria-plugin#208"}
        for key, entry in state["issues"].items():
            assert set(entry) >= {
                "issue_key", "tier_a", "judgement_inputs", "last_classified_at",
            }, key


# ── 3. Tier B provenance 门 + 裁定④ assessments 不变量 ─────────────────────


class TestAssessmentGate:
    def _entries(self, ctx_key):
        """评估条目 (契约 v1: provenance / created_at / context_key 三必填 —
        context_key 取评估轮 state 记录面, DEC 裁定-9)。"""
        return {
            "aria-plugin#208": {
                "verdict_priorities": "P2 — 与全分页 fetch 修复轨相关",
                "suspected_fixed": True,
                "owner_decisions": ["是否随 #238 一起验收关单"],
                "provenance": {"harness": "test-harness", "model_id": "test-model"},
                "created_at": "2026-10-19T10:00:00Z",
                "context_key": ctx_key,
            },
            "Aria#233": {
                # assessments 文件面 verdict_priorities 是 list-of-dict
                # (TASK-005 契约示例形态) — 报告面是 string ⇒ 类型不符省略,
                # 不做语义转换 (机械层不造数据)。
                "verdict_priorities": [{"from": "P2", "to": "P3",
                                        "rationale": "..."}],
                "provenance": {"harness": "test-harness", "model_id": "test-model"},
                "created_at": "2026-10-19T10:00:00Z",
                "context_key": ctx_key,
            },
        }

    def test_matching_provenance_reused_in_report(self, tmp_path):
        run(tmp_path, make_corpus())  # r1: 落 state (context_key 记录面)
        write_assessments(tmp_path, self._entries(current_context_key(tmp_path)))
        # r2: 上下文未变 (tmp 内 openspec/git/handoff/taxonomy 均稳定) ⇒ 门放行
        report = run(tmp_path, make_corpus(), now=NOW_T1)
        e208 = entry_by_key(report, "aria-plugin#208")
        assert e208["assessment"] is not None
        assert e208["assessment"]["provenance"] == {
            "harness": "test-harness", "model_id": "test-model",
        }
        assert e208["assessment"]["verdict_priorities"] == \
            "P2 — 与全分页 fetch 修复轨相关"  # str 形态透传
        assert e208["assessment"]["suspected_fixed"] is True
        assert e208["assessment"]["owner_decisions"] == ["是否随 #238 一起验收关单"]
        assert report["summary"]["assessed"] == 2

        e233 = entry_by_key(report, "Aria#233")
        assert e233["assessment"] is not None
        assert "verdict_priorities" not in e233["assessment"]  # list ⇒ 省略

    def test_stale_provenance_nulls_assessment(self, tmp_path):
        run(tmp_path, make_corpus())
        entries = self._entries(current_context_key(tmp_path))
        entries["aria-plugin#208"]["provenance"] = {
            "harness": "claude-code",  # ≠ test-harness ⇒ provenance-mismatch
            "model_id": "test-model",  # (判序: provenance 先于上下文门)
        }
        write_assessments(tmp_path, entries)
        report = run(tmp_path, make_corpus(), now=NOW_T1)
        assert entry_by_key(report, "aria-plugin#208")["assessment"] is None
        assert entry_by_key(report, "Aria#233")["assessment"] is not None
        assert report["summary"]["assessed"] == 1

    def test_context_change_nulls_assessments(self, tmp_path):
        """DEC 裁定-9 E2E: 上下文分量变 (在制 spec 修订) ⇒ Tier B 全量 stale
        (context-changed) — issue 本体一字未动 (同 corpus), 评估不再被复用。

        反事实: 若 CLI 未把 context_key 接进门 (或门恒放行), 本测试必红
        (#110 类静默陈旧: spec ship 后评估翻转而引擎照旧复用)。"""
        run(tmp_path, make_corpus())
        write_assessments(tmp_path, self._entries(current_context_key(tmp_path)))
        # 上下文分量变: openspec 在制 spec 出现 + 修订 (两步都动 openspec 面)
        spec = tmp_path / "openspec" / "changes" / "issue-groomer-p1-mvp"
        spec.mkdir(parents=True)
        (spec / "proposal.md").write_text("proposal v1\n", encoding="utf-8")
        report_mid = run(tmp_path, make_corpus(), now=NOW_T1)
        assert report_mid["summary"]["assessed"] == 0  # 上下文已变 ⇒ 全 stale
        (spec / "proposal.md").write_text("proposal v1\namended\n", encoding="utf-8")
        report = run(tmp_path, make_corpus(), now=NOW_T1)
        assert report["summary"]["assessed"] == 0
        for key in ("Aria#233", "aria-plugin#208", "Aria#241"):
            assert entry_by_key(report, key)["assessment"] is None

    def test_assessments_file_bytes_unchanged(self, tmp_path):
        run(tmp_path, make_corpus())
        path = write_assessments(tmp_path, self._entries(current_context_key(tmp_path)))
        before = path.read_bytes()
        run(tmp_path, make_corpus(), now=NOW_T1)  # state 重写 (含门读 assessments)
        assert path.read_bytes() == before      # 裁定④: 字节不变

    def test_orphaned_assessment_key_not_in_report(self, tmp_path):
        run(tmp_path, make_corpus())
        entries = self._entries(current_context_key(tmp_path))
        entries["Aria#999"] = {  # 本轮不在册 (已关闭/移出作用域)
            "provenance": {"harness": "test-harness", "model_id": "test-model"},
            "created_at": "2026-10-19T10:00:00Z",
            "context_key": entries["Aria#233"]["context_key"],
        }
        write_assessments(tmp_path, entries)
        report = run(tmp_path, make_corpus(), now=NOW_T1)
        keys = {f"{e['repo']}#{e['number']}" for e in report["issues"]}
        assert "Aria#999" not in keys
        assert report["summary"]["assessed"] == 2  # 只算在册 reusable


# ── 4. repos 作用域解析 (config 回落对齐真实结构) ──────────────────────────


class TestReposResolution:
    def test_config_repos_key_used(self, tmp_path):
        cfg = tmp_path / ".aria" / "config.json"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(json.dumps({
            "state_scanner": {"issue_scan": {"enabled": True,
                                             "repos": ["Foo", "acme/Bar"]}},
        }), encoding="utf-8")
        res = groom.resolve_repos(None, tmp_path)
        assert res.specs == ["Foo", "acme/Bar"]
        assert res.scope_degraded == []  # 显式声明面: 无自动推导 ⇒ 无降级
        assert res.derived is False      # strict (resolve_git_roots 严格映射)

    def test_scan_submodules_derivation(self, tmp_path):
        # 真实 config 形态: 无 repos 键, scan_submodules=true ⇒ 主仓+子模块
        # origin 推导 (state-scanner issue_scan 同款语义)。
        def git(*args):
            subprocess.run(["git", "-C", str(tmp_path), *args],
                           check=True, capture_output=True)

        git("init", "-q")
        git("remote", "add", "origin", "git@forgejo.10cg.pub:10CG/Aria.git")
        git("config", "-f", ".gitmodules", "submodule.aria.path", "aria")
        git("config", "-f", ".gitmodules",
            "submodule.aria.url",
            "https://forgejo.10cg.pub/10CG/aria-plugin.git")
        sub = tmp_path / "aria"  # 目录名 aria ↔ 裸名 aria-plugin (映射面)
        sub.mkdir()
        subprocess.run(["git", "-C", str(sub), "init", "-q"],
                       check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(sub), "remote", "add", "origin",
             "https://forgejo.10cg.pub/10CG/aria-plugin.git"],
            check=True, capture_output=True)

        cfg = tmp_path / ".aria" / "config.json"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(json.dumps({
            "state_scanner": {"issue_scan": {"scan_submodules": True}},
        }), encoding="utf-8")

        res = groom.resolve_repos(None, tmp_path)
        assert res.specs == ["10CG/Aria", "10CG/aria-plugin"]
        assert res.scope_degraded == []  # 推导全成 ⇒ 零降级
        assert res.derived is True
        # 卫星仓真实路径映射 (submodule 目录 ↔ origin 裸仓名)
        roots = groom.resolve_git_roots(
            tmp_path, res.specs, strict=not res.derived
        )
        assert roots[0] == str(tmp_path)
        assert roots[1:] == [str(sub)]

    def test_missing_everything_errors(self, tmp_path):
        with pytest.raises(groom.ConfigError):
            groom.resolve_repos(None, tmp_path)


# ── 5. CLI 全链路 smoke (subprocess 实跑, mock 经 --runner-bin + env 注入) ──

FAKE_WRAPPER = r'''#!/usr/bin/env python3
import json, os, re, sys
corpus = json.load(open(os.environ["GROOM_FAKE_CORPUS"], encoding="utf-8"))
endpoint = sys.argv[2]
path, _, qs = endpoint.partition("?")
page = 1
for kv in qs.split("&"):
    if kv.startswith("page="):
        page = int(kv[5:])
fail = os.environ.get("GROOM_FAIL_REPO")  # A-1 失败注入: 指定仓 issue-list 恒 rc=1
if fail and page == 1 and path == "/repos/10CG/" + fail + "/issues":
    sys.stderr.write("simulated wrapper failure for " + fail + "\n")
    sys.exit(1)
if page >= 2:
    print("[]")
    sys.exit(0)
m = re.match(r"^/repos/([^/]+)/([^/]+)/issues$", path)
if m:
    key = m.group(1) + "/" + m.group(2)
    print(json.dumps(corpus.get("repos", {}).get(key, []), ensure_ascii=False))
    sys.exit(0)
m = re.match(r"^/repos/([^/]+)/([^/]+)/issues/(\d+)/comments$", path)
if m:
    key = m.group(1) + "/" + m.group(2) + "#" + m.group(3)
    print(json.dumps(corpus.get("comments", {}).get(key, []), ensure_ascii=False))
    sys.exit(0)
print("[]")
sys.exit(0)
'''


def _fake_wrapper(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    script = bindir / "fake-forgejo"
    script.write_text(FAKE_WRAPPER, encoding="utf-8")
    script.chmod(0o755)
    return script


def _corpus_file(tmp_path, corpus):
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(corpus, ensure_ascii=False), encoding="utf-8")
    return path


def _run_cli(tmp_path, corpus, extra=(), env_extra=None):
    _init_git_project(tmp_path)  # --repos 显式 ⇒ strict 映射须可解析 (B-2)
    fake_bin = _fake_wrapper(tmp_path)
    corpus_path = _corpus_file(tmp_path, corpus)
    argv = [
        sys.executable, GROOM_PY,
        "--repos", "Aria", "aria-plugin",
        "--project-root", str(tmp_path),
        "--harness", "cli-smoke",
        "--now", NOW_T0,
        "--runner-bin", str(fake_bin),
        "--quiet",
        *extra,
    ]
    env = dict(os.environ, GROOM_FAKE_CORPUS=str(corpus_path), **(env_extra or {}))
    return subprocess.run(argv, capture_output=True, text=True, env=env,
                          cwd=str(tmp_path), timeout=120)


class TestCliSmoke:
    def test_cli_smoke_exit0_stdout_json(self, tmp_path):
        proc = _run_cli(tmp_path, make_corpus())
        assert proc.returncode == 0, proc.stderr
        report = json.loads(proc.stdout)
        assert report["snapshot_schema_version"] == "1.1"
        assert report["harness"] == "cli-smoke"
        assert len(report["issues"]) == 3
        assert state_path_of(tmp_path).is_file()
        # state provenance: harness 自报落面 (裁定③ 第一层, 持久化侧)
        state = json.loads(state_path_of(tmp_path).read_text(encoding="utf-8"))
        assert state["last_run"]["provenance"]["harness"] == "cli-smoke"

    def test_cli_preserves_assessments_and_writes_state(self, tmp_path):
        # 两段式: r1 落 state 取 context_key, 评估条目带键落档 (契约必填),
        # r2 门全过 — 使「报告面 null 拒绝」保持为被测路径 (不被
        # context-missing 提前拦截)。
        proc = _run_cli(tmp_path, make_corpus())
        assert proc.returncode == 0, proc.stderr
        path = write_assessments(tmp_path, {
            "aria-plugin#208": {
                "owner_decisions": ["决策面条目"],
                "provenance": {"harness": "cli-smoke", "model_id": None},
                "created_at": "2026-10-19T10:00:00Z",
                "context_key": current_context_key(tmp_path),
            },
        })
        before = path.read_bytes()
        proc = _run_cli(tmp_path, make_corpus(), extra=["--now", NOW_T1])
        assert proc.returncode == 0, proc.stderr
        assert path.read_bytes() == before  # 裁定④ 不变量 (CLI 面)
        assert state_path_of(tmp_path).is_file()
        # model_id=None 与本轮 None 匹配 (复用门 + 上下文门均过), 但报告面
        # null 非法 ⇒ 该条整体降级 null
        report = json.loads(proc.stdout)
        assert entry_by_key(report, "aria-plugin#208")["assessment"] is None

    def test_cli_no_scope_config_error_exit2(self, tmp_path):
        proc = subprocess.run(
            [sys.executable, GROOM_PY,
             "--project-root", str(tmp_path), "--quiet"],
            capture_output=True, text=True, cwd=str(tmp_path), timeout=60,
        )
        assert proc.returncode == 2
        assert "config error" in proc.stderr
        assert "state_scanner.issue_scan" in proc.stderr or "--repos" in proc.stderr

    def test_cli_out_file(self, tmp_path):
        out = tmp_path / "report.json"
        proc = _run_cli(tmp_path, make_corpus(), extra=["--out", str(out)])
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout == ""  # stdout 不再打 JSON
        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["summary"]["total_issues"] == 3

    def test_cli_unexpected_exception_exit1_with_traceback(
        self, tmp_path, monkeypatch, capsys
    ):
        """E-4 兜底: 未分类异常 (非 ValueError/OSError/RuntimeError 家族)
        ⇒ 统一 exit 1, 完整 traceback 进 stderr — 退出码契约 0/1/2 全路径
        成立 (反事实: 无兜底时 KeyError 裸炸穿壳, 退出码 1 以 traceback
        形态交给解释器, 适配层无法按码分流)。"""
        def boom(args, **kw):
            raise KeyError("unexpected pipeline failure")

        monkeypatch.setattr(groom, "run_pipeline", boom)
        rc = groom.main([
            "--repos", "Aria",
            "--project-root", str(tmp_path),
            "--quiet",
        ])
        assert rc == 1
        err = capsys.readouterr().err
        assert "unexpected error" in err
        assert "Traceback" in err and "KeyError" in err


# ── 6. B.3 修复轮 (A-1/A-3/B-1/B-2/D-1/E-1/exit-2/port-URL) ────────────────


class RepoFailRunner:
    """corpus 正常路由 + 指定仓 issue-list 恒 FetchError (A-1 失败注入)。"""

    def __init__(self, corpus, fail_repo):
        self.inner = FakeRunner(corpus)
        self.fail_repo = fail_repo

    def call(self, method, endpoint, payload=None):
        if (
            method == "GET"
            and endpoint.startswith(f"/repos/10CG/{self.fail_repo}/issues?")
        ):
            raise fetch.FetchError(
                f"wrapper rc=1: simulated failure for {self.fail_repo}",
                endpoint=endpoint,
            )
        return self.inner.call(method, endpoint, payload)


class TestFetchFailureAborts:
    """A-1 CRITICAL: 任一仓 fetch 失败 ⇒ RuntimeError (exit 1) + 不写 state
    (state 保持上轮, 重跑幂等) — 半份语料 + closed 谎报结构上不可出厂。

    反事实: 若失败仓仍组装报告, 其条目对 diff 面呈现为 closed、对 state
    面被驱逐 — 下一轮全部谎报 new; 断言 closed == [] / state issues 键集
    不变必红。
    """

    def test_fetch_failure_raises_naming_repo_no_state(self, tmp_path):
        _init_git_project(tmp_path)
        args = make_args(tmp_path)
        with pytest.raises(RuntimeError) as ctx:
            groom.run_pipeline(
                args, runner=RepoFailRunner(make_corpus(), "aria-plugin"),
                request_interval=0,
            )
        msg = str(ctx.value)
        assert "fetch" in msg
        assert "aria-plugin" in msg            # stderr 明示哪仓失败
        assert not state_path_of(tmp_path).exists()  # 不写 state

    def test_failure_keeps_prior_state_no_phantom_closed(self, tmp_path):
        run(tmp_path, make_corpus())  # r1: 3 issue 入 state
        state_file = state_path_of(tmp_path)
        before = state_file.read_text(encoding="utf-8")
        _init_git_project(tmp_path)
        with pytest.raises(RuntimeError):
            groom.run_pipeline(
                make_args(tmp_path, ["--now", NOW_T1]),
                runner=RepoFailRunner(make_corpus(), "aria-plugin"),
                request_interval=0,
            )
        # state 逐字节保持上轮 (不驱逐失败仓条目)
        assert state_file.read_text(encoding="utf-8") == before
        # 修复后重跑 (幂等): aria-plugin 从未离开 ⇒ closed 空, 全量在册
        report = run(tmp_path, make_corpus(), now=NOW_T1)
        assert report["diff"]["closed"] == []
        assert report["summary"]["total_issues"] == 3
        assert report["diff"]["drift"] == []   # 失败轮不产生伪增量

    def test_cli_fetch_failure_exit1_stderr_names_repo(self, tmp_path):
        proc = _run_cli(
            tmp_path, make_corpus(),
            env_extra={"GROOM_FAIL_REPO": "aria-plugin"},
        )
        assert proc.returncode == 1
        assert "aria-plugin" in proc.stderr
        assert not state_path_of(tmp_path).exists()
        assert proc.stdout == ""                # 不出厂半份报告


class TestClassifyRowErrorAborts:
    """E-1: tier_a.classify 行级 ValueError ⇒ 该仓 error (不连坐好仓) +
    A-1 同款收口 (exit 1, 不写 state)。"""

    def test_bad_updated_classify_error_names_repo(self, tmp_path):
        corpus = make_corpus()
        # normalize 后 "not-a-date" (10 字符) 原样存活 ⇒ classify _parse_datetime 炸
        corpus["repos"]["10CG/aria-plugin"][0]["updated_at"] = "not-a-date"
        _init_git_project(tmp_path)
        with pytest.raises(RuntimeError) as ctx:
            groom.run_pipeline(
                make_args(tmp_path), runner=FakeRunner(corpus), request_interval=0
            )
        msg = str(ctx.value)
        assert "classify" in msg
        assert "aria-plugin" in msg            # 归因到仓, 不连坐 Aria
        assert "Aria" not in msg.replace("aria-plugin", "")
        assert not state_path_of(tmp_path).exists()


class TestReportOutOrdering:
    """D-1: --out 报告写盘先于 save_state — 报告面先落, state 后落。"""

    def test_report_write_failure_keeps_state_unwritten(self, tmp_path):
        _init_git_project(tmp_path)
        blocker = tmp_path / "blocker"
        blocker.write_text("i am a file", encoding="utf-8")
        out = blocker / "report.json"  # 父路径是普通文件 ⇒ NotADirectoryError
        with pytest.raises(OSError):
            groom.run_pipeline(
                make_args(tmp_path, ["--out", str(out)]),
                runner=FakeRunner(make_corpus()), request_interval=0,
            )
        assert not state_path_of(tmp_path).exists()  # state 未写

    @pytest.mark.skipif(os.geteuid() == 0, reason="root 无视目录只读位")
    def test_state_save_failure_report_already_written(self, tmp_path):
        # state 写失败 (cache 目录只读) ⇒ 报告已落盘 — 次序证明。
        _init_git_project(tmp_path)
        cache = tmp_path / ".aria" / "cache"
        cache.mkdir(parents=True)
        out = tmp_path / "report.json"
        os.chmod(cache, 0o500)
        try:
            with pytest.raises(OSError):
                groom.run_pipeline(
                    make_args(tmp_path, ["--out", str(out)]),
                    runner=FakeRunner(make_corpus()), request_interval=0,
                )
            assert out.is_file()  # 报告先于 state 落盘
            report = json.loads(out.read_text(encoding="utf-8"))
            assert report["summary"]["total_issues"] == 3
            assert not (cache / "groom-state.json").exists()
        finally:
            os.chmod(cache, 0o700)


class TestArgPrevalidation:
    """exit 2 预校验: --repos spec 形态 / --now ISO 可解析性在 argparse 层拦
    (p.error → usage + exit 2), 不进 pipeline 不冒充运行错误。"""

    @pytest.mark.parametrize("bad_spec", ["a/b/c", "", "/x", "x/"])
    def test_bad_repo_spec_exits_2(self, bad_spec):
        with pytest.raises(SystemExit) as ctx:
            groom.parse_args(["--repos", bad_spec, "--quiet"])
        assert ctx.value.code == 2

    def test_bad_now_exits_2(self):
        with pytest.raises(SystemExit) as ctx:
            groom.parse_args(["--repos", "Aria", "--now", "not-a-date"])
        assert ctx.value.code == 2

    def test_good_now_still_passes(self):
        args = groom.parse_args(["--repos", "Aria", "--now", "2026-10-19T12:00:00Z"])
        assert args.now == "2026-10-19T12:00:00Z"

    def test_cli_bad_spec_exit_2(self, tmp_path):
        proc = subprocess.run(
            [sys.executable, GROOM_PY,
             "--repos", "a/b/c", "--project-root", str(tmp_path), "--quiet"],
            capture_output=True, text=True, cwd=str(tmp_path), timeout=60,
        )
        assert proc.returncode == 2
        assert "usage" in proc.stderr and "--repos" in proc.stderr

    def test_cli_bad_now_exit_2(self, tmp_path):
        proc = subprocess.run(
            [sys.executable, GROOM_PY,
             "--repos", "Aria", "--now", "yesterday",
             "--project-root", str(tmp_path), "--quiet"],
            capture_output=True, text=True, cwd=str(tmp_path), timeout=60,
        )
        assert proc.returncode == 2
        assert "--now" in proc.stderr


class TestExtractOwnerRepoPort:
    """port URL: ``scheme://host:port/o/r.git`` — 端口被当 host 路径段 ⇒
    假阴性的回归钉 + 无端口三形态不回归。"""

    @pytest.mark.parametrize("url,expected", [
        ("https://forgejo.10cg.pub:3000/10CG/aria.git", "10CG/aria"),
        ("http://forgejo.internal:8080/10CG/aria-plugin.git", "10CG/aria-plugin"),
        ("ssh://git@forgejo.10cg.pub:2222/10CG/Aria.git", "10CG/Aria"),
        ("https://forgejo.10cg.pub:3000/10CG/aria.git?foo=1", "10CG/aria"),
        # 无端口回归面
        ("git@forgejo.10cg.pub:10CG/Aria.git", "10CG/Aria"),
        ("https://forgejo.10cg.pub/10CG/aria-plugin.git", "10CG/aria-plugin"),
        ("ssh://git@forgejo.10cg.pub/10CG/Aether.git", "10CG/Aether"),
        # 非数字端口 / 多段 ⇒ None (不猜)
        ("https://host:port/10CG/x/aria.git", None),
        ("", None),
    ])
    def test_extract(self, url, expected):
        assert groom._extract_owner_repo(url) == expected


class TestScopeDegradation:
    """B-1/B-2: 作用域解析三态 — 结构性缺席 (合法空) / git 失败 (ConfigError) /
    逐仓推导失败 (警告 + scope_degraded); strict 映射失败 ConfigError。"""

    @staticmethod
    def _write_scan_config(tmp_path):
        cfg = tmp_path / ".aria" / "config.json"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps({
            "state_scanner": {"issue_scan": {"scan_submodules": True}},
        }), encoding="utf-8")

    def test_gitmodules_structural_absence_is_legal_empty(self, tmp_path):
        # 无 .gitmodules ⇒ 合法空仓集 (非 git 仓 / 未用 submodule), 不炸。
        assert groom._submodule_paths(tmp_path) == []

    def test_gitmodules_enumeration_failure_config_error(
        self, tmp_path, monkeypatch
    ):
        (tmp_path / ".gitmodules").write_text("submodule.a.path aria\n",
                                              encoding="utf-8")
        monkeypatch.setattr(
            groom, "_git_raw", lambda args, cwd: (128, "", "fatal: bad config")
        )
        with pytest.raises(groom.ConfigError) as ctx:
            groom._submodule_paths(tmp_path)
        assert "git config -f .gitmodules" in str(ctx.value)

    def test_scan_submodule_origin_failure_degrades(self, tmp_path, monkeypatch):
        _init_git_project(tmp_path)
        self._write_scan_config(tmp_path)
        real = groom._origin_owner_repo

        def flaky(root):
            if Path(root) == tmp_path / "aria-plugin":
                return None  # submodule origin 推导失败
            return real(root)

        monkeypatch.setattr(groom, "_origin_owner_repo", flaky)
        warns: list[str] = []
        res = groom.resolve_repos(None, tmp_path, log=warns.append)
        assert res.specs == ["10CG/Aria"]           # 失败仓移出扫描
        assert res.scope_degraded == ["submodule:aria-plugin"]  # 但被点名
        assert res.derived is True
        assert any("aria-plugin" in w for w in warns)  # stderr 警告

    def test_scan_main_origin_failure_degrades(self, tmp_path, monkeypatch):
        _init_git_project(tmp_path)
        self._write_scan_config(tmp_path)
        real = groom._origin_owner_repo
        monkeypatch.setattr(
            groom, "_origin_owner_repo",
            lambda root: None if Path(root) == tmp_path else real(root),
        )
        res = groom.resolve_repos(None, tmp_path, log=lambda _m: None)
        assert res.specs == ["10CG/aria-plugin"]
        assert res.scope_degraded == ["main"]

    def test_scan_all_fail_still_config_error(self, tmp_path, monkeypatch):
        _init_git_project(tmp_path)
        self._write_scan_config(tmp_path)
        monkeypatch.setattr(groom, "_origin_owner_repo", lambda root: None)
        with pytest.raises(groom.ConfigError):
            groom.resolve_repos(None, tmp_path, log=lambda _m: None)

    def test_strict_unmapped_repo_config_error(self, tmp_path):
        # B-2: 显式 --repos 指名的仓映射不上本地路径 ⇒ exit 2 (用户意志 loud)。
        _init_git_project(tmp_path)
        with pytest.raises(groom.ConfigError) as ctx:
            groom.resolve_git_roots(tmp_path, ["Aria", "Kairos"], strict=True)
        assert "Kairos" in str(ctx.value)

    def test_strict_all_mapped_ok(self, tmp_path):
        _init_git_project(tmp_path)
        roots = groom.resolve_git_roots(tmp_path, ["Aria", "aria-plugin"],
                                        strict=True)
        assert roots == [str(tmp_path), str(tmp_path / "aria-plugin")]

    def test_non_strict_unmapped_degrades_not_raises(self, tmp_path):
        _init_git_project(tmp_path)
        warns: list[str] = []
        degraded: list[str] = []
        roots = groom.resolve_git_roots(
            tmp_path, ["Aria", "Kairos"], strict=False,
            log=warns.append, scope_degraded=degraded,
        )
        assert "repo:Kairos" in degraded
        assert any("Kairos" in w for w in warns)
        assert roots == [str(tmp_path)]  # Kairos 无路径, 不虚增

    def test_scope_degraded_recorded_in_state_e2e(self, tmp_path, monkeypatch):
        """E2E: scan_submodules 推导 + submodule origin 失败 ⇒ 报告照出
        (主仓数据完整), state last_run.scope_degraded 点名降级仓。"""
        _init_git_project(tmp_path)
        self._write_scan_config(tmp_path)
        real = groom._origin_owner_repo
        monkeypatch.setattr(
            groom, "_origin_owner_repo",
            lambda root: None if Path(root) == tmp_path / "aria-plugin"
            else real(root),
        )
        args = groom.parse_args([
            "--project-root", str(tmp_path),      # 无 --repos ⇒ config 回落
            "--harness", "test-harness",
            "--model-id", "test-model",
            "--now", NOW_T0,
            "--quiet",
        ])
        report = groom.run_pipeline(
            args, runner=FakeRunner(make_corpus()), request_interval=0
        )
        # specs 只剩 10CG/Aria ⇒ 只扫主仓 2 条 (aria-plugin 不在扫描面)
        assert [r["repo"] for r in report["repos"]] == ["Aria"]
        assert report["summary"]["total_issues"] == 2
        state = json.loads(state_path_of(tmp_path).read_text(encoding="utf-8"))
        assert state["last_run"]["scope_degraded"] == ["submodule:aria-plugin"]

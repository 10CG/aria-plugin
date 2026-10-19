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

GROOM_PY = os.path.join(SCRIPTS, "groom.py")
SCHEMA_PATH = os.path.join(SCRIPTS, "groom-report.schema.json")

# test_schema 的 mini_validate (与 groom 自校验同一 SOT; 测试独立复核双保险)。
sys.path.insert(0, _HERE)
from test_schema import mini_validate  # noqa: E402

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


def run(tmp_path, corpus, extra=(), now=None):
    """进程内跑全编排 (fake runner 注入 + request_interval=0), 返回 report。

    ``now`` 非空时以 ``--now <now>`` 前置覆盖 (argparse 后值胜)。"""
    argv_extra = ["--now", now, *extra] if now is not None else list(extra)
    args = make_args(tmp_path, argv_extra)
    return groom.run_pipeline(args, runner=FakeRunner(corpus),
                              request_interval=0)


def state_path_of(tmp_path):
    return tmp_path / ".aria" / "cache" / "groom-state.json"


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
            "taxonomy_hash",
        }
        assert set(state["issues"]) == {"Aria#233", "Aria#241", "aria-plugin#208"}
        for key, entry in state["issues"].items():
            assert set(entry) >= {
                "issue_key", "tier_a", "judgement_inputs", "last_classified_at",
            }, key


# ── 3. Tier B provenance 门 + 裁定④ assessments 不变量 ─────────────────────


class TestAssessmentGate:
    def _entries(self):
        return {
            "aria-plugin#208": {
                "verdict_priorities": "P2 — 与全分页 fetch 修复轨相关",
                "suspected_fixed": True,
                "owner_decisions": ["是否随 #238 一起验收关单"],
                "provenance": {"harness": "test-harness", "model_id": "test-model"},
                "created_at": "2026-10-19T10:00:00Z",
            },
            "Aria#233": {
                # assessments 文件面 verdict_priorities 是 list-of-dict
                # (TASK-005 契约示例形态) — 报告面是 string ⇒ 类型不符省略,
                # 不做语义转换 (机械层不造数据)。
                "verdict_priorities": [{"from": "P2", "to": "P3",
                                        "rationale": "..."}],
                "provenance": {"harness": "test-harness", "model_id": "test-model"},
                "created_at": "2026-10-19T10:00:00Z",
            },
        }

    def test_matching_provenance_reused_in_report(self, tmp_path):
        write_assessments(tmp_path, self._entries())
        report = run(tmp_path, make_corpus())
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
        entries = self._entries()
        entries["aria-plugin#208"]["provenance"] = {
            "harness": "claude-code",  # ≠ test-harness ⇒ provenance-mismatch
            "model_id": "test-model",
        }
        write_assessments(tmp_path, entries)
        report = run(tmp_path, make_corpus())
        assert entry_by_key(report, "aria-plugin#208")["assessment"] is None
        assert entry_by_key(report, "Aria#233")["assessment"] is not None
        assert report["summary"]["assessed"] == 1

    def test_assessments_file_bytes_unchanged(self, tmp_path):
        path = write_assessments(tmp_path, self._entries())
        before = path.read_bytes()
        run(tmp_path, make_corpus())            # 第一轮
        run(tmp_path, make_corpus(), now=NOW_T1)  # 第二轮 (state 重写)
        assert path.read_bytes() == before      # 裁定④: 字节不变

    def test_orphaned_assessment_key_not_in_report(self, tmp_path):
        entries = self._entries()
        entries["Aria#999"] = {  # 本轮不在册 (已关闭/移出作用域)
            "provenance": {"harness": "test-harness", "model_id": "test-model"},
            "created_at": "2026-10-19T10:00:00Z",
        }
        write_assessments(tmp_path, entries)
        report = run(tmp_path, make_corpus())
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
        assert groom.resolve_repos(None, tmp_path) == ["Foo", "acme/Bar"]

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

        specs = groom.resolve_repos(None, tmp_path)
        assert specs == ["10CG/Aria", "10CG/aria-plugin"]
        # 卫星仓真实路径映射 (submodule 目录 ↔ origin 裸仓名)
        roots = groom.resolve_git_roots(tmp_path, specs)
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


def _run_cli(tmp_path, corpus, extra=()):
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
    env = dict(os.environ, GROOM_FAKE_CORPUS=str(corpus_path))
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
        path = write_assessments(tmp_path, {
            "aria-plugin#208": {
                "owner_decisions": ["决策面条目"],
                "provenance": {"harness": "cli-smoke", "model_id": None},
                "created_at": "2026-10-19T10:00:00Z",
            },
        })
        before = path.read_bytes()
        proc = _run_cli(tmp_path, make_corpus())
        assert proc.returncode == 0, proc.stderr
        assert path.read_bytes() == before  # 裁定④ 不变量 (CLI 面)
        assert state_path_of(tmp_path).is_file()
        # model_id=None 与本轮 None 匹配 (复用门), 但报告面 null 非法 ⇒ null
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

"""Tests for lib/fetch.py — issue-groomer forgejo 双端点 fetch 层 (TASK-001).

Covers the TASK-001 verification bullets against the 2026-10-19 Runtime
Amendment contract (mock 形态对齐 references/forgejo-behavior-notes.md 实测):
  1. issue-list 真分页 (SC-2): 多页 mock / 空页终止 / 短页不终止 (多探测一页) /
     页上限 / 整页去重全见 ⇒ fail-closed (PaginationWalkTests)。
  2. comments 端点不做分页游走 (Amendment): 单次 GET 全量 + comments 计数字段
     对账 — 匹配落值 / 不匹配 ⇒ 三态 unknown + fetch_error, 绝不静默截断;
     >50-comment 截断反例 fixture 的真实形态 = **服务端忽略分页参数**
     (mock 恒全量返回, 断言代码不依赖 limit 生效) (CommentsReconciliationTests)。
  3. 三态 (值 / [] 零评论 / None unknown): 含传输失败连重试 2 次后 None、
     瞬时失败第 3 次恢复、issue-list 失败不重试整仓 fail-closed、计数字段
     缺席不发 GET (ThreeStateRetryTests)。
  4. PR 混同客户端过滤 (双保险第二层) (PRFilterTests)。
  5. 多仓隔离: 一仓挂不连坐 + owner/repo 映射参数化 + 重复仓名去重
     (MultiRepoIsolationTests)。
  6. 默认通道 ForgejoCliRunner 的 rc/JSON/timeout/OSError 错误映射与
     Rule #7 纪律 (错误面不含 wrapper stdout) (RunnerTests)。
  7. 行归一化 (normalize_issue) 的 tier_a 输入契约形态 + fetch_all 输出
     直接喂 tier_a.classify 的端到端契约对齐 (NormalizationTests /
     TierAContractTests)。

全 mock 注入 fake runner (零网络/零真 API); stdlib-only unittest。
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from unittest import mock

# Add scripts/ to path for direct module import (house convention).
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "scripts"))

from lib import fetch, tier_a  # noqa: E402


# ---------------------------------------------------------------- fixture helpers

def make_issue(number, *, title="", labels=None, comments=0, body="",
               created="2026-10-01T10:00:00Z", updated=None, **extra):
    """Forgejo issue-list 行真形态 (bare minimum + 可覆盖 extra)。

    ``comments=None`` ⇒ 整个 ``comments`` 键缺席 (计数字段缺失反例)。
    """
    row = {
        "number": number,
        "title": title,
        "labels": [{"name": n} for n in (labels or [])],
        "created_at": created,
        "updated_at": updated or created,
        "body": body,
        "pull_request": None,
    }
    if comments is not None:
        row["comments"] = comments
    # comments=None ⇒ 键缺席 (计数字段缺失反例)
    row.update(extra)
    return row


def make_comment(cid, *, body="comment body", created="2026-10-02T10:00:00Z", updated=None):
    return {"id": cid, "body": body, "created_at": created, "updated_at": updated or created}


class FakeRunner:
    """Scripted fake CLI 通道: endpoint → 返回值 / 异常实例 / callable。

    记录全部调用 (method, endpoint) 供断言 (调用序 / 次数 / URL 形态)。
    未路由的 endpoint = 测试 fixture 缺口, 直接 AssertionError。
    """

    def __init__(self, routes=None):
        self.routes = dict(routes or {})
        self.calls = []

    def call(self, method, endpoint, payload=None):
        self.calls.append((method, endpoint))
        if endpoint not in self.routes:
            raise AssertionError(f"unexpected endpoint in fixture: {method} {endpoint!r}")
        behavior = self.routes[endpoint]
        if isinstance(behavior, Exception):
            raise behavior
        if callable(behavior):
            return behavior()
        return behavior

    def count(self, endpoint):
        return sum(1 for _, ep in self.calls if ep == endpoint)


class FailNTimes:
    """callable 路由: 前 n 次抛 exc, 之后返回 then。"""

    def __init__(self, n, exc, then):
        self.n = n
        self.exc = exc
        self.then = then
        self.seen = 0

    def __call__(self):
        self.seen += 1
        if self.seen <= self.n:
            raise self.exc
        return self.then


LIST_BASE = "/repos/10CG/Aria/issues?state=open&type=issues&limit=50"


def list_ep(page=1, owner="10CG", repo="Aria", page_size=50):
    base = f"/repos/{owner}/{repo}/issues?state=open&type=issues&limit={page_size}"
    return base if page == 1 else f"{base}&page={page}"


def com_ep(number, owner="10CG", repo="Aria"):
    return f"/repos/{owner}/{repo}/issues/{number}/comments?limit=50"


def session_with(routes):
    return fetch.Session(FakeRunner(routes), request_interval=0)


def runner_of(session):
    return session._runner  # noqa: SLF001 — test seam


def simple_fetch_routes(issues):
    """fetch_all 最小路由: page1 = issues, page2 = [] (空页终止); comments 路由
    全覆盖 (count>0 → n 条; count==0 → [] — fetch_all 对 0 也发 GET 对账)。"""
    routes = {list_ep(1): list(issues), list_ep(2): []}
    for issue in issues:
        count = issue.get("comments", 0)
        if isinstance(count, int):
            routes[com_ep(issue["number"])] = [make_comment(i) for i in range(count)]
    return routes


# ------------------------------------------------------------------ SC-2: 真分页

class PaginationWalkTests(unittest.TestCase):
    """issue-list 端点: 多页游走 / 终止条件 / fail-closed 分支。"""

    def test_multi_page_walk_collects_all_and_stops_on_empty_page(self):
        page1 = [make_issue(i) for i in range(1, 51)]     # 满页 50
        page2 = [make_issue(i) for i in range(51, 81)]    # 30 条
        session = session_with({list_ep(1): page1, list_ep(2): page2, list_ep(3): []})
        rows = fetch.list_repo_issues(session, "10CG", "Aria")
        self.assertEqual([r["number"] for r in rows], list(range(1, 81)))
        runner = runner_of(session)
        # 恰好 3 次请求; page 1 URL 不带 &page= (house 形态), 之后递增。
        self.assertEqual([ep for _, ep in runner.calls], [list_ep(1), list_ep(2), list_ep(3)])

    def test_short_page_is_not_terminal(self):
        # 短页可能是服务端夹小页大小 — 不以短页判终点, 继续探测到空页 (零丢失纪律)。
        page1 = [make_issue(i) for i in range(1, 4)]  # 3 条 = 短页
        session = session_with({list_ep(1): page1, list_ep(2): []})
        rows = fetch.list_repo_issues(session, "10CG", "Aria")
        self.assertEqual(len(rows), 3)
        self.assertEqual(runner_of(session).count(list_ep(2)), 1)  # 短页后仍探测了 page 2

    def test_cross_page_dedup_by_number(self):
        # 窗口漂移: page 2 重复了 #1 (已见), 新行 #2 照收。
        session = session_with({
            list_ep(1): [make_issue(1)],
            list_ep(2): [make_issue(1), make_issue(2)],
            list_ep(3): [],
        })
        rows = fetch.list_repo_issues(session, "10CG", "Aria")
        self.assertEqual([r["number"] for r in rows], [1, 2])

    def test_entire_duplicate_page_fails_closed(self):
        # 整页全为已见条目 = 服务端疑似忽略 paging, 半份列表不可信 ⇒ FetchError。
        session = session_with({
            list_ep(1): [make_issue(1)],
            list_ep(2): [make_issue(1)],
        })
        with self.assertRaises(fetch.FetchError) as ctx:
            fetch.list_repo_issues(session, "10CG", "Aria")
        self.assertIn("already-seen", str(ctx.exception))

    def test_page_ceiling_exceeded_fails_closed(self):
        # 每页都是**新** issue 的满页 (2/页), 走到 ceiling+1 探测页仍非空 ⇒ 上限分支。
        routes = {
            list_ep(p, page_size=2): [make_issue(p * 2 - 1), make_issue(p * 2)]
            for p in (1, 2, 3)
        }
        session = session_with(routes)
        with self.assertRaises(fetch.FetchError) as ctx:
            fetch.list_repo_issues(session, "10CG", "Aria", page_size=2, page_ceiling=2)
        self.assertIn("page ceiling", str(ctx.exception))

    def test_empty_page_at_ceiling_probe_terminates(self):
        # 越过上限的探测页若为空 ⇒ 正常终止 (空页优先于上限判定)。
        session = session_with({
            list_ep(1, page_size=2): [make_issue(1), make_issue(2)],
            list_ep(2, page_size=2): [],
        })
        rows = fetch.list_repo_issues(session, "10CG", "Aria", page_size=2, page_ceiling=1)
        self.assertEqual(len(rows), 2)

    def test_non_list_response_raises(self):
        session = session_with({list_ep(1): {"unexpected": "object"}})
        with self.assertRaises(fetch.FetchError) as ctx:
            fetch.list_repo_issues(session, "10CG", "Aria")
        self.assertIn("expected a JSON array", str(ctx.exception))

    def test_row_without_int_number_raises(self):
        session = session_with({list_ep(1): [{"title": "no number"}]})
        with self.assertRaises(fetch.FetchError) as ctx:
            fetch.list_repo_issues(session, "10CG", "Aria")
        self.assertIn("'number'", str(ctx.exception))


class PRFilterTests(unittest.TestCase):
    """PR 混同客户端过滤: pull_request 非空 dict 或 URL 含 /pulls/ ⇒ 滤除。"""

    def test_pr_shapes_filtered_issues_kept(self):
        rows = [
            make_issue(1),                                              # 真 issue (pull_request: null)
            make_issue(2, pull_request={"ref": "main"}),                # PR 形态 1
            make_issue(3, pull_request=None, html_url="https://x/pulls/3"),  # PR 形态 2 (无 pull_request 字段信号)
            make_issue(4),                                              # 真 issue
        ]
        session = session_with({list_ep(1): rows, list_ep(2): []})
        kept = fetch.list_repo_issues(session, "10CG", "Aria")
        self.assertEqual([r["number"] for r in kept], [1, 4])


# ------------------------------------------- Amendment: comments 单取 + 计数对账

class CommentsReconciliationTests(unittest.TestCase):
    """comments 端点: 不做分页游走, 单次 GET 全量 + comments 计数字段对账。"""

    def test_match_lands_value_and_no_page_walk(self):
        routes = simple_fetch_routes([make_issue(233, comments=2)])
        runner = FakeRunner(routes)
        result = fetch.fetch_all(["Aria"], runner=runner, request_interval=0)
        issue = result["issues"][0]
        self.assertEqual(len(issue["comments"]), 2)
        self.assertIsNone(issue["comments_error"])
        self.assertIsNone(result["repos"][0]["error"])
        # 单次 GET, 无 &page= 游走 (Amendment: 该端点忽略分页, 游走只会重复)。
        self.assertEqual(runner.count(com_ep(233)), 1)
        self.assertIn(("GET", com_ep(233)), runner.calls)
        self.assertFalse(any("&page=" in ep and "/comments" in ep for _, ep in runner.calls))

    def test_mismatch_is_fail_closed_none_not_empty(self):
        # issue 对象说 5 条, 端点只回 3 条 ⇒ unknown (None), 绝不冒充零评论或半份值。
        routes = simple_fetch_routes([make_issue(7, comments=5)])
        routes[com_ep(7)] = [make_comment(i) for i in range(3)]
        result = fetch.fetch_all(["Aria"], runner=FakeRunner(routes), request_interval=0)
        issue = result["issues"][0]
        self.assertIsNone(issue["comments"])
        self.assertIn("reconciliation mismatch", issue["comments_error"])
        self.assertIn("5", issue["comments_error"])
        self.assertIn("3", issue["comments_error"])
        self.assertIn("#7", result["repos"][0]["error"])  # 汇总到 repo 级 error 面

    def test_gt50_counter_fixture_server_ignores_pagination(self):
        # >50-comment 截断反例的真实形态 (Amendment): 服务端忽略 limit/page,
        # 单次响应恒全量 (10cg.local#12 实测 52 条形态)。mock 钉此行为 —
        # 断言代码不依赖 limit 生效: 全量 52 条一次到手, 且仅一次 GET。
        routes = simple_fetch_routes([make_issue(12, comments=52)])
        routes[com_ep(12)] = [make_comment(1000 + i) for i in range(52)]
        runner = FakeRunner(routes)
        result = fetch.fetch_all(["Aria"], runner=runner, request_interval=0)
        issue = result["issues"][0]
        self.assertEqual(len(issue["comments"]), 52)
        self.assertEqual(runner.count(com_ep(12)), 1)
        self.assertIsNone(result["repos"][0]["error"])

    def test_zero_comments_is_empty_list_not_none(self):
        routes = simple_fetch_routes([make_issue(5, comments=0)])
        runner = FakeRunner(routes)
        result = fetch.fetch_all(["Aria"], runner=runner, request_interval=0)
        issue = result["issues"][0]
        self.assertEqual(issue["comments"], [])
        self.assertIsNotNone(issue["comments"])   # [] ≠ None: 零评论是值, 不是 unknown
        self.assertIsNone(issue["comments_error"])
        self.assertIsNone(result["repos"][0]["error"])
        # count==0 也发 GET 并对账 (0==0), 不跳过 — 对账是完备性证明本体。
        self.assertEqual(runner.count(com_ep(5)), 1)

    def test_comment_rows_normalized_shape(self):
        routes = simple_fetch_routes([make_issue(9, comments=1)])
        routes[com_ep(9)] = [{
            "id": 42, "body": "已修, 见 PR #77", "created_at": "2026-10-02T10:00:00Z",
            "updated_at": "2026-10-04T08:00:00Z", "user": {"login": "x"},  # user 等多余字段剔除
        }]
        result = fetch.fetch_all(["Aria"], runner=FakeRunner(routes), request_interval=0)
        c = result["issues"][0]["comments"][0]
        self.assertEqual(c, {
            "id": 42, "body": "已修, 见 PR #77",
            "created_at": "2026-10-02T10:00:00Z",  # 完整 ISO 精度 (comment-edit 判别面)
            "updated_at": "2026-10-04T08:00:00Z",
        })

    def test_comments_non_list_response_fails_the_issue(self):
        routes = simple_fetch_routes([make_issue(3, comments=1)])
        routes[com_ep(3)] = {"error": "shape"}
        result = fetch.fetch_all(["Aria"], runner=FakeRunner(routes), request_interval=0)
        issue = result["issues"][0]
        self.assertIsNone(issue["comments"])
        self.assertIn("expected a JSON array", issue["comments_error"])


# ------------------------------------------------------------- 三态 + 重试语义

class ThreeStateRetryTests(unittest.TestCase):
    """三态 (值 / [] / None) + 传输层重试 (连重试 2 次后 None)。"""

    def test_transport_failure_after_retries_is_unknown(self):
        routes = simple_fetch_routes([make_issue(11, comments=1)])
        boom = fetch.FetchError("GET x: wrapper rc=2: HTTP 500", endpoint="x")
        routes[com_ep(11)] = boom
        runner = FakeRunner(routes)
        result = fetch.fetch_all(["Aria"], runner=runner, request_interval=0)
        issue = result["issues"][0]
        self.assertIsNone(issue["comments"])             # unknown, 不冒充 []
        self.assertIn("3 attempt(s)", issue["comments_error"])
        self.assertEqual(runner.count(com_ep(11)), 3)    # 首次 + 重试 2
        self.assertIn("#11", result["repos"][0]["error"])

    def test_transient_failure_recovers_within_attempts(self):
        routes = simple_fetch_routes([make_issue(12, comments=1)])
        flaky = FailNTimes(2, fetch.FetchError("transient", endpoint="t"), [make_comment(1)])
        routes[com_ep(12)] = flaky
        result = fetch.fetch_all(["Aria"], runner=FakeRunner(routes), request_interval=0)
        issue = result["issues"][0]
        self.assertEqual(len(issue["comments"]), 1)      # 第 3 次成功 ⇒ 值三态
        self.assertIsNone(issue["comments_error"])
        self.assertIsNone(result["repos"][0]["error"])

    def test_issue_list_failure_is_not_retried_and_fails_repo(self):
        routes = {list_ep(1): fetch.FetchError("GET y: wrapper rc=2: HTTP 502", endpoint="y")}
        runner = FakeRunner(routes)
        result = fetch.fetch_all(["Aria"], runner=runner, request_interval=0)
        # issue-list 页失败不重试 (重试只属 comments 三态契约): 1 次调用即整仓 fail-closed。
        self.assertEqual(runner.count(list_ep(1)), 1)
        self.assertEqual(result["repos"][0]["open_issues"], 0)
        self.assertIn("issue-list fetch failed", result["repos"][0]["error"])
        self.assertEqual(result["issues"], [])

    def test_missing_count_field_is_unknown_without_get(self):
        # comments 计数字段缺席 ⇒ 对账结构上不可能 ⇒ unknown; 且不发 GET (无对账面的取回无意义)。
        routes = simple_fetch_routes([make_issue(8, comments=None)])
        runner = FakeRunner(routes)
        result = fetch.fetch_all(["Aria"], runner=runner, request_interval=0)
        issue = result["issues"][0]
        self.assertIsNone(issue["comments_count"])
        self.assertIsNone(issue["comments"])
        self.assertIn("count field missing or invalid", issue["comments_error"])
        self.assertEqual(runner.count(com_ep(8)), 0)     # 没发 GET
        self.assertIn("#8", result["repos"][0]["error"])

    def test_retry_sleeps_between_attempts(self):
        # 限速礼貌: 每两次请求之间 sleep (含重试请求); 首个请求前不 sleep。
        routes = {com_ep(1): fetch.FetchError("boom", endpoint="b")}
        session = fetch.Session(FakeRunner(routes), request_interval=0.1)
        with mock.patch.object(fetch.time, "sleep") as sleep:
            with self.assertRaises(fetch.FetchError):
                session.get(com_ep(1), attempts=3)
        self.assertEqual(sleep.call_count, 2)  # 3 次请求 ⇒ 2 次间隔 sleep


# ----------------------------------------------------------------- 多仓编排

class MultiRepoIsolationTests(unittest.TestCase):
    """多仓配置: 一仓挂不连坐 / owner 映射参数化 / 重复仓名去重。"""

    def test_one_repo_failure_does_not_affect_others(self):
        routes = simple_fetch_routes([make_issue(1, comments=1)])
        routes.update({
            list_ep(1, repo="Broke"): fetch.FetchError("GET z: wrapper rc=2: HTTP 404", endpoint="z"),
        })
        result = fetch.fetch_all(["Broke", "Aria"], runner=FakeRunner(routes), request_interval=0)
        by_repo = {e["repo"]: e for e in result["repos"]}
        self.assertIn("issue-list fetch failed", by_repo["Broke"]["error"])
        self.assertEqual(by_repo["Broke"]["open_issues"], 0)
        self.assertIsNone(by_repo["Aria"]["error"])       # 不连坐
        self.assertEqual(by_repo["Aria"]["open_issues"], 1)
        self.assertEqual([i["repo"] for i in result["issues"]], ["Aria"])

    def test_owner_mapping_parameterized(self):
        # "acme/Widget" 形态 = repo 名→owner/repo 映射参数化; 输出用裸仓名。
        routes = {
            list_ep(1): [],  # Aria 走默认 owner, 空仓即止 (page1 空 ⇒ 无 page2)
            list_ep(1, owner="acme", repo="Widget"): [make_issue(1, comments=0)],
            list_ep(2, owner="acme", repo="Widget"): [],
            com_ep(1, owner="acme", repo="Widget"): [],  # count=0 也发 GET 对账
        }
        runner = FakeRunner(routes)
        result = fetch.fetch_all(["Aria", "acme/Widget"], runner=runner, request_interval=0)
        self.assertEqual(result["repos"][1]["repo"], "Widget")
        self.assertEqual(result["issues"][0]["repo"], "Widget")
        self.assertEqual(runner.count(list_ep(1, owner="acme", repo="Widget")), 1)

    def test_duplicate_repo_specs_deduped(self):
        routes = simple_fetch_routes([make_issue(1)])
        runner = FakeRunner(routes)
        result = fetch.fetch_all(["Aria", "Aria"], runner=runner, request_interval=0)
        self.assertEqual(runner.count(list_ep(1)), 1)     # 同名仓只取一次
        self.assertEqual(len(result["repos"]), 1)

    def test_bad_repo_spec_raises_value_error(self):
        with self.assertRaises(ValueError):
            fetch.fetch_all(["a/b/c"], runner=FakeRunner({}), request_interval=0)

    def test_repo_summary_counts_match_issues(self):
        routes = simple_fetch_routes([make_issue(1), make_issue(2, comments=1), make_issue(3)])
        result = fetch.fetch_all(["Aria"], runner=FakeRunner(routes), request_interval=0)
        self.assertEqual(result["repos"][0]["open_issues"], 3)
        self.assertEqual(len(result["issues"]), 3)


# ------------------------------------------------------- 默认通道 (CLI wrapper)

class RunnerTests(unittest.TestCase):
    """ForgejoCliRunner: rc / JSON / timeout / OSError 错误映射 + Rule #7 纪律。"""

    def _call(self, completed, *, timeout_s=None):
        # patch 上下文内执行调用 (helper 返回后才退 with = patch 已还原的反例教训)。
        runner = fetch.ForgejoCliRunner(timeout_s=timeout_s) if timeout_s else fetch.ForgejoCliRunner()
        with mock.patch.object(fetch.subprocess, "run", return_value=completed):
            return runner.call("GET", "/x")

    def test_success_parses_stdout_json(self):
        out = self._call(mock.Mock(returncode=0, stdout='[{"number": 1}]\n', stderr=""))
        self.assertEqual(out, [{"number": 1}])

    def test_success_empty_stdout_returns_none(self):
        out = self._call(mock.Mock(returncode=0, stdout="  \n", stderr=""))
        self.assertIsNone(out)

    def test_nonzero_rc_raises_with_stderr_tail_only(self):
        # Rule #7: 错误面只带 rc + wrapper 已脱敏 stderr 尾部; stdout 原文不得出现。
        completed = mock.Mock(
            returncode=2, stdout='{"payload": "STDOUT-MARKER-MUST-NOT-LEAK"}',
            stderr="forgejo: HTTP 403 from /repos/10CG/Aria/issues",
        )
        with self.assertRaises(fetch.FetchError) as ctx:
            self._call(completed)
        msg = str(ctx.exception)
        self.assertIn("rc=2", msg)
        self.assertIn("HTTP 403", msg)
        self.assertNotIn("STDOUT-MARKER-MUST-NOT-LEAK", msg)

    def test_non_json_stdout_raises(self):
        completed = mock.Mock(returncode=0, stdout="not json at all", stderr="")
        with self.assertRaises(fetch.FetchError) as ctx:
            self._call(completed)
        self.assertIn("not JSON", str(ctx.exception))

    def test_timeout_raises(self):
        runner = fetch.ForgejoCliRunner(timeout_s=5)
        with mock.patch.object(
            fetch.subprocess, "run",
            side_effect=subprocess.TimeoutExpired(cmd=["forgejo"], timeout=5),
        ):
            with self.assertRaises(fetch.FetchError) as ctx:
                runner.call("GET", "/x")
        self.assertIn("timed out", str(ctx.exception))

    def test_wrapper_not_executable_raises(self):
        runner = fetch.ForgejoCliRunner()
        with mock.patch.object(fetch.subprocess, "run", side_effect=OSError("No such file")):
            with self.assertRaises(fetch.FetchError) as ctx:
                runner.call("GET", "/x")
        self.assertIn("not executable", str(ctx.exception))


# ----------------------------------------------------------------- 归一化形态

class NormalizationTests(unittest.TestCase):
    """normalize_issue → tier_a 输入契约的字段形态。"""

    def test_field_shapes_match_corpus_convention(self):
        row = fetch.normalize_issue(
            make_issue(208, title="[缺陷] x", labels=["bug", "area/ui"], body="正文",
                       created="2026-09-07T08:00:00Z", updated="2026-09-08T09:30:00Z",
                       comments=3),
            "Aria",
        )
        self.assertEqual(row["repo"], "Aria")               # 裸仓名
        self.assertEqual(row["number"], 208)
        self.assertEqual(row["title"], "[缺陷] x")
        self.assertEqual(row["labels"], ["bug", "area/ui"])  # label name 平面列表
        self.assertEqual(row["created"], "2026-09-07")       # 日期面 [:10] (语料同形)
        self.assertEqual(row["updated"], "2026-09-08")
        self.assertEqual(row["comments_count"], 3)
        self.assertEqual(row["body"], "正文")

    def test_lenient_fields(self):
        row = fetch.normalize_issue({"number": 1, "labels": ["raw-str", {"no_name": 1}, {"name": "ok"}]},
                                    "Aria")
        self.assertEqual(row["title"], "")
        self.assertEqual(row["labels"], ["ok"])
        self.assertEqual(row["created"], "")
        self.assertEqual(row["comments_count"], None)  # 计数字段缺席 ⇒ None 非 0

    def test_bad_number_raises(self):
        with self.assertRaises(ValueError):
            fetch.normalize_issue({"number": "x"}, "Aria")

    def test_split_repo_spec(self):
        self.assertEqual(fetch.split_repo_spec("Aria"), ("10CG", "Aria"))
        self.assertEqual(fetch.split_repo_spec("acme/W"), ("acme", "W"))
        self.assertEqual(fetch.split_repo_spec("W", "other"), ("other", "W"))
        for bad in ("", "a/b/c", "/x", "x/", " / "):
            with self.assertRaises(ValueError):
                fetch.split_repo_spec(bad)


# ------------------------------------------------------ 与 tier_a 输入契约对齐

class TierAContractTests(unittest.TestCase):
    """fetch_all 输出直接喂 tier_a.classify (输入契约超集, 端到端对齐证明)。"""

    def test_fetch_output_feeds_tier_a_classify(self):
        routes = simple_fetch_routes([
            make_issue(1, title="[bug] 崩了", labels=[], comments=2, updated="2026-10-01T00:00:00Z"),
            make_issue(2, title="无信号标题", comments=0, updated="2026-10-01T00:00:00Z"),
        ])
        result = fetch.fetch_all(["Aria"], runner=FakeRunner(routes), request_interval=0)
        rows = result["issues"]

        classified = tier_a.classify(rows)  # 契约超集: 直接可喂, 无需字段裁剪
        by_number = {c["number"]: c for c in classified}
        self.assertEqual(by_number[1]["category"], "bug")       # title 前缀命中内置层
        self.assertEqual(by_number[2]["category"], "unknown")   # 无显式信号不猜
        kinds1 = {s["kind"] for s in by_number[1]["signals"]}
        self.assertIn("activity", kinds1)                        # comments_count=2 → 活跃度信号
        self.assertIn("staleness", kinds1)                       # updated 在场 → 龄档信号
        # count=0 在场 (非缺席) ⇒ tier_a 产 "0" 档 activity 信号 (缺席才不产)。
        sources2 = {s["source"] for s in by_number[2]["signals"]}
        self.assertIn("activity:0", sources2)

    def test_unknown_state_does_not_masquerade_as_zero_activity(self):
        # comments=None (unknown) 的行, comments_count 也为 None ⇒ tier_a 不产
        # activity 信号 (缺席不是 0) — 失败不冒充零评论在分类面的投影。
        routes = simple_fetch_routes([make_issue(3, title="t", comments=None)])
        result = fetch.fetch_all(["Aria"], runner=FakeRunner(routes), request_interval=0)
        row = result["issues"][0]
        self.assertIsNone(row["comments"])
        self.assertIsNone(row["comments_count"])
        classified = tier_a.classify([row])
        self.assertEqual(classified[0]["category"], "unknown")
        self.assertNotIn("activity", {s["kind"] for s in classified[0]["signals"]})


if __name__ == "__main__":
    unittest.main()

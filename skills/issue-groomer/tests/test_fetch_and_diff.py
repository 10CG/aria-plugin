"""TASK-008 — SC-2/3/4/5/9 fixture 家族 + 反假绿全家桶 (issue-groomer P1).

每条 SC 的独立 fixture 家族 (detailed-tasks TASK-008 verification; spec
issue-groomer-p1-mvp proposal §4 + Runtime Amendment 2026-10-19):

- **SC-2 双端点分页**: issue-list 真分页 (满页/短页非终态/空页终止/越窗去重/
  页上限 fail-closed); comments 端点 **单次 GET 全量 + 计数对账**
  (Amendment 契约 — 服务端忽略 limit/page); >50-comment 截断反例的**真实
  形态 = 服务端忽略分页参数** (mock 恒全量 52 条, 10cg.local#12 实测锚,
  references/forgejo-behavior-notes.md §2); comments 三态 (值 / [] /
  None-unknown)。
- **SC-3 每判据独立反事实**: Tier A 四判据 (title 前缀 / label / staleness
  档 / 活跃度档) 各设独立 fixture — 单判据退化 (前缀表空 / label 表空 /
  档位函数恒返同档) ⇒ 对应分类判定必红; 负面 fixture (无信号 → unknown,
  signals 非空则红)。
- **SC-4 五 facet**: baseline no-diff 专属 / top-N 截断 (100 条 top_n=20 →
  恰 20 + truncated + total) / comments 三态指纹 / 复用规则 (判据输入变而
  issue_key 同 ⇒ 重分类不复用) / provenance 门 (provenance 变 ⇒ stale)。
- **SC-5 差集+幂等**: apply_payload.add = suggested−existing 差集
  (suggested ⊇ existing 部分交集构造); **mock 不编码 no-op** — 幂等断言只验
  差集代数 (no-op 前提 = TASK-009 live 实测记录, mock 不编码防断言循环
  自证); schema 封闭键集反事实 (注入 remove 字段 ⇒ schema 校验必红)。
- **SC-9 taxonomy 三层注错**: 前缀表 / 分类键 / label 名各注错一份 ⇒
  validate_taxonomy 必红 (三种独立, 无跨层污染) + fail-closed 不回落。

反事实纪律: 每个反事实 fixture 注释「退化成常量时为何必红」— fixture 构造
保证实现/配置退化 (判据被忽略、函数恒返常量、比较面缺键) 时对应断言必炸,
而非恒绿。

fixture 形态锚点 (裁定-7 防形态脱节): API 行 / 日期 / label / 评论计数取自
TASK-009 语料 (scratchpad/issues-open-2026-10-18.json 150 条 + sample
body+comments 三件套, 2026-10-18 快照) 与 forgejo-behavior-notes.md 的
live 实测形态; 语料行以常量内嵌 (测试不运行时依赖 scratchpad 单点)。

全 mock 零网络 (fake runner 注入); tempdir; 类名 Test* 前缀 (pytest 收集)。
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

# Add scripts/ + tests/ to path for direct module import (house convention).
_HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(_HERE), "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, _HERE)

import groom  # noqa: E402
from lib import diffseg, fetch, fingerprint, incremental, tier_a  # noqa: E402
from lib.schema_validate import mini_validate  # noqa: E402  # 生产层 SOT (B.3)

SCHEMA_PATH = os.path.join(SCRIPTS, "groom-report.schema.json")

# 语料快照次日 (快照 2026-10-18; 语料内 updated 全部 ≤ 快照日)。
NOW = datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)
NOW_ISO = "2026-10-19T12:00:00Z"


# ------------------------------------------------------------- fetch 层基元

def api_issue(number: int, *, title: str = "", labels=(),
              comments: int | None = 0, body: str = "",
              created: str = "2026-10-10T10:00:00Z",
              updated: str | None = None) -> dict[str, Any]:
    """Forgejo issue-list 行真 API 形态 (labels = [{"name": ...}] dict 行)。

    ``comments=None`` ⇒ 整个 ``comments`` 键缺席 (issue 对象计数字段缺失
    反例 — 对账结构上不可能 ⇒ 三态 unknown, 不发 GET)。
    """
    row: dict[str, Any] = {
        "number": number,
        "title": title,
        "labels": [{"name": n} for n in (labels or ())],
        "created_at": created,
        "updated_at": updated or created,
        "body": body,
        "pull_request": None,
    }
    if comments is not None:
        row["comments"] = comments
    return row


def api_comment(cid: int, *, body: str = "comment body",
                created: str = "2026-10-15T16:58:30Z",
                updated: str | None = None) -> dict[str, Any]:
    """comments 端点行真 API 形态。默认时间戳 = 语料 sample 里 Aria#233 的
    真实 comment (id 28794 @ 2026-10-15T16:58:30Z)。"""
    return {"id": cid, "body": body, "created_at": created,
            "updated_at": updated or created}


def comment_seq(n: int, *, start: str = "2026-08-01T08:00:00Z",
                step_s: int = 3600, id_base: int = 5000) -> list[dict[str, Any]]:
    """n 条升序 comment 集 (id 递增、created_at 最旧在前 = 端点实测排序形态)。"""
    t0 = datetime.fromisoformat(start.replace("Z", "+00:00"))
    rows = []
    for i in range(n):
        ts = (t0 + timedelta(seconds=step_s * i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows.append(api_comment(id_base + i, body=f"comment #{i}",
                                created=ts, updated=ts))
    return rows


def list_ep(page: int = 1, owner: str = "10CG", repo: str = "Aria",
            page_size: int = 50) -> str:
    base = f"/repos/{owner}/{repo}/issues?state=open&type=issues&limit={page_size}"
    return base if page == 1 else f"{base}&page={page}"


def com_ep(number: int, owner: str = "10CG", repo: str = "Aria") -> str:
    return f"/repos/{owner}/{repo}/issues/{number}/comments?limit=50"


class FakeRunner:
    """Scripted fake CLI 通道: endpoint 精确路由 → 值 / 异常实例 / callable。

    记录全部调用供断言 (调用序 / 次数 / URL 形态)。未路由 endpoint = fixture
    缺口, 直接 AssertionError (强于静默 None — 例: 「计数字段缺席不发 GET」
    fixture 靠未路由即炸来兜底)。零网络。
    """

    def __init__(self, routes: dict[str, Any] | None = None):
        self.routes = dict(routes or {})
        self.calls: list[str] = []

    def call(self, method: str, endpoint: str, payload=None):
        self.calls.append(endpoint)
        if endpoint not in self.routes:
            raise AssertionError(f"unexpected endpoint in fixture: {method} {endpoint!r}")
        behavior = self.routes[endpoint]
        if isinstance(behavior, Exception):
            raise behavior
        if callable(behavior):
            return behavior()
        return behavior

    def count(self, endpoint: str) -> int:
        return sum(1 for ep in self.calls if ep == endpoint)


class FailNTimes:
    """callable 路由: 前 n 次抛 exc, 之后返回 then (传输重试 fixture)。"""

    def __init__(self, n: int, exc: Exception, then: Any):
        self.n, self.exc, self.then = n, exc, then
        self.seen = 0

    def __call__(self):
        self.seen += 1
        if self.seen <= self.n:
            raise self.exc
        return self.then


def add_comment_routes(routes: dict[str, Any], issues: list[dict[str, Any]], *,
                       owner: str = "10CG", repo: str = "Aria",
                       comments_by_number: dict[int, Any] | None = None
                       ) -> dict[str, Any]:
    """给路由补 comments 端点 (fetch_all 对**每条** issue 发对账 GET, count 0
    也发): 按 issue 计数字段配等量行 (0 配 []); comments_by_number 显式覆盖。"""
    by_num = comments_by_number or {}
    for issue in issues:
        count = issue.get("comments", 0)
        routes.setdefault(
            com_ep(issue["number"], owner, repo),
            by_num[issue["number"]] if issue["number"] in by_num
            else (comment_seq(count) if isinstance(count, int) and count > 0 else []),
        )
    return routes


def fetch_all_routes(issues: list[dict[str, Any]], *,
                     owner: str = "10CG", repo: str = "Aria",
                     comments_by_number: dict[int, Any] | None = None) -> dict[str, Any]:
    """单仓最小路由: page1 = 全部 issue (≤50), page2 = 空页终止; comments
    端点按 issue 计数字段配等量行 (count 0 配 [], 对账 0==0)。"""
    routes: dict[str, Any] = {
        list_ep(1, owner, repo): list(issues),
        list_ep(2, owner, repo): [],
    }
    return add_comment_routes(routes, issues, owner=owner, repo=repo,
                              comments_by_number=comments_by_number)


def do_fetch_all(routes: dict[str, Any], **kwargs) -> tuple[dict[str, Any], FakeRunner]:
    runner = FakeRunner(routes)
    out = fetch.fetch_all(["Aria"], runner=runner, request_interval=0, **kwargs)
    return out, runner


def issue_row(result: dict[str, Any], number: int) -> dict[str, Any]:
    for row in result["issues"]:
        if row["number"] == number:
            return row
    raise AssertionError(f"issue #{number} not in fetch_all output")


# ------------------------------------------------------- tier_a / 引擎基元

# 语料锚定的 taxonomy (内置保守默认层的子集形态: 分类键 + 语料实测前缀
# [bug]x6 / [缺陷]x35 + 语料实测 label 家族 bug/type-bug)。
TAX = {
    "version": 1,
    "categories": {"bug": "bug", "feature": "feature",
                   "security": "security", "tracker": "tracker"},
    "title_prefixes": {"[bug]": "bug", "[缺陷]": "bug", "[feature]": "feature"},
    "label_signals": {"bug": "bug", "type/bug": "bug", "feature": "feature"},
}
TAX_NO_PREFIX = {**TAX, "title_prefixes": {}}   # 前缀表退化 (判据 1 单独退化)
TAX_NO_LABEL = {**TAX, "label_signals": {}}      # label 表退化 (判据 2 单独退化)

# 语料真实 title 锚 (scratchpad/issues-open-2026-10-18.json):
TITLE_BUG_223 = ("[bug] phase-c-integrator: submodule_gate.sh 写死 origin/master "
                 "—— 默认分支为 main 的仓库里对子模块指针回退空扫放行 "
                 "(mode=block 也 exit 0)")           # Aria#223, labels ["bug"]
TITLE_LABEL_ONLY_229 = ("secret-guard: guard-bypass.log 每条记录末尾缺换行"
                        "（被命令替换吞掉），多次放行的记录粘成一行")  # Aria#229
TITLE_NO_SIGNAL_233 = ("[Layer L] 长会话里的在制 claim 会被对方例行收尾的 "
                       "--sweep-stale 永久标成 abandoned")  # 前缀项目层, 默认层不收
TITLE_PRIO_PREFIX = "[P0][AB套件] p95 延迟回归: benchmark runner 冷启动争用"  # [P0]=优先级非分类

# fingerprint / incremental 消费的 fetch 归一形态超集 (fetched issue 行)。
CTX_FP = {  # build_next_state 只存不解释; 手造最小四分量 (与 test_diffseg 同锚)
    "openspec_changes_hash": "0f" * 32,
    "git_heads": {"/home/dev/Aria": "ab" * 20},
    "handoff_pointer": "2026-10-18-235-cycle-done.md",
    "taxonomy_hash": "ee" * 32,
}
PROV = {"harness": "claude-code", "model_id": "glm-5.2"}


def tier_issue(number: int, *, title: str = "", labels: tuple = (),
               updated: str | None = None, comments_count: int | None = None,
               repo: str = "Aria") -> dict[str, Any]:
    """tier_a.classify 输入契约行 (updated/comments_count 缺席 = 键不在)。"""
    row: dict[str, Any] = {"repo": repo, "number": number, "title": title,
                           "labels": list(labels)}
    if updated is not None:
        row["updated"] = updated
    if comments_count is not None:
        row["comments_count"] = comments_count
    return row


def fetched_issue(number: int, *, title: str = "", labels: tuple = (),
                  updated: str = "2026-10-01", comments_count: int = 0,
                  body: str = "b", comments: Any = None,
                  comments_error: str | None = None,
                  repo: str = "Aria") -> dict[str, Any]:
    """fetch 层归一形态超集行 (incremental/diffseg 消费面)。"""
    return {
        "repo": repo, "number": number, "title": title, "labels": list(labels),
        "created": "2026-09-01", "updated": updated,
        "comments_count": comments_count, "body": body,
        "comments": comments, "comments_error": comments_error,
    }


def make_engine(tmp_path: Path, *, now: datetime = NOW,
                assessments_reader=None) -> incremental.IncrementalEngine:
    return incremental.IncrementalEngine(
        tmp_path / "groom-state.json",
        assessments_reader=assessments_reader,
        now_fn=lambda: now,
    )


def classify_one(issue: dict[str, Any], tax: dict | None = TAX,
                 now: datetime | None = NOW) -> dict[str, Any]:
    return tier_a.classify([issue], tax, now=now)[0]


def sig_of(rec: dict[str, Any], kind: str) -> dict[str, Any] | None:
    for s in rec["signals"]:
        if s["kind"] == kind:
            return s
    return None


# ═════════════════════════ SC-2: 双端点分页 ═══════════════════════════════

class TestSC2IssueListPagination:
    """issue-list 端点真分页 (behavior-notes §3.1: page 生效, 越界页空数组)。

    反事实纪律: 终止条件退化成「短页即停」⇒ 短页后的新行丢失 ⇒ 计数断言必红;
    去重缺失 ⇒ 窗口漂移页 (整页重发) 计数膨胀 ⇒ set 大小断言必红。
    """

    def test_full_then_short_then_empty_page_terminates(self):
        """满页 50 → 短页 3 (非终态! 服务端可能夹小页) → 空页终止; 53 条零丢失。"""
        page1 = [api_issue(i, title=f"[bug] corpus issue #{i}") for i in range(1, 51)]
        page2 = [api_issue(i, title=f"[bug] corpus issue #{i}") for i in range(51, 54)]
        out, runner = do_fetch_all(add_comment_routes(
            {list_ep(1): page1, list_ep(2): page2, list_ep(3): []}, page1 + page2))
        assert [e["repo"] for e in out["repos"]] == ["Aria"]
        assert out["repos"][0]["error"] is None
        assert out["repos"][0]["open_issues"] == 53 == len(out["issues"])
        # 短页确实被继续探测 (page3 空页请求发生过) — 不是短页即停
        assert runner.count(list_ep(3)) == 1

    def test_page_one_url_has_no_page_param_incremental_after(self):
        """page1 URL 无 ``&page=`` (与 regen_corpus 逐字节同形), 后续页递增。"""
        issues = [api_issue(1), api_issue(2)]
        _, runner = do_fetch_all(add_comment_routes(
            {list_ep(1): [issues[0]], list_ep(2): [issues[1]], list_ep(3): []},
            issues))
        list_calls = [ep for ep in runner.calls if "/issues?" in ep]
        assert list_calls == [list_ep(1), list_ep(2), list_ep(3)]

    def test_cross_page_number_dedup_window_drift(self):
        """跨页 number 去重: page2 重发 #30-#50 (窗口漂移) + 新 #51-#52 ⇒ 恰 52 唯一。"""
        page1 = [api_issue(i) for i in range(1, 51)]
        page2 = [api_issue(i) for i in range(30, 53)]  # 30-50 重发 + 51-52 新
        out, _ = do_fetch_all(add_comment_routes(
            {list_ep(1): page1, list_ep(2): page2, list_ep(3): []},
            page1 + [i for i in page2 if i["number"] > 50]))
        numbers = [r["number"] for r in out["issues"]]
        assert len(numbers) == len(set(numbers)) == 52

    def test_entire_page_already_seen_fail_closed(self):
        """整页全为已见条目 (服务端游标卡死形态) ⇒ FetchError 整仓 fail-closed,
        绝不静默产出半份列表。"""
        page1 = [api_issue(i) for i in range(1, 51)]
        out, _ = do_fetch_all({list_ep(1): page1, list_ep(2): list(page1)})
        entry = out["repos"][0]
        assert entry["error"] is not None and "already-seen" in entry["error"]
        assert entry["open_issues"] == 0 and out["issues"] == []

    def test_page_ceiling_exceeded_fail_closed(self):
        """触及页上限 (page_ceiling 注入 2, 第 3 页仍满) ⇒ FetchError — 结构上
        不可能静默产出半份列表 (10k 条安全上限的缩小复现)。"""
        pages = {list_ep(p): [api_issue(p * 50 + i) for i in range(50)]
                 for p in (1, 2, 3)}
        with pytest.raises(fetch.FetchError, match="page ceiling"):
            fetch.list_repo_issues(
                fetch.Session(FakeRunner(pages), request_interval=0),
                "10CG", "Aria", page_ceiling=2,
            )


class TestSC2CommentsCountReconciliation:
    """comments 端点 Amendment 契约: 单次 GET 全量 + issue 计数字段对账
    (behavior-notes §2: 服务端忽略 limit/page; 完备性证明 = 计数对账)。

    反事实纪律: 对账缺失 (退化成「收到多少算多少」) ⇒ 截断负向 fixture
    (collected 50 < count 52) 会静默写半份 ⇒ unknown 断言必红。
    """

    def test_count_match_yields_value_state_endpoint_order_preserved(self):
        """计数 3 = 端点 3 条 ⇒ 值态; 保持端点顺序 (升序最旧在前)。"""
        comments = comment_seq(3)
        out, runner = do_fetch_all(
            fetch_all_routes([api_issue(233, title=TITLE_NO_SIGNAL_233,
                                        comments=3)],
                             comments_by_number={233: comments}))
        row = issue_row(out, 233)
        assert row["comments"] == [
            {"id": c["id"], "created_at": c["created_at"],
             "updated_at": c["updated_at"], "body": c["body"]}
            for c in comments
        ]  # 归一为 {id, created_at, updated_at, body}, 端点顺序原样
        assert row["comments_error"] is None
        assert runner.count(com_ep(233)) == 1  # 单次 GET, 无分页游走

    def test_count_mismatch_fail_closed_unknown_and_repo_error(self):
        """issue 对象说 5 条、端点回 3 条 ⇒ comments=None (unknown) + 逐条
        comments_error + repo error 汇总; 不重试 (对账失败非传输失败, 恰 1 GET)。"""
        out, runner = do_fetch_all(
            fetch_all_routes([api_issue(241, comments=5)],
                             comments_by_number={241: comment_seq(3)}))
        row = issue_row(out, 241)
        assert row["comments"] is None            # 不冒充值, 不冒充零评论
        assert "reconciliation mismatch" in row["comments_error"]
        assert "says 5" in row["comments_error"] and "returned 3" in row["comments_error"]
        repo_error = out["repos"][0]["error"]
        assert repo_error is not None and "#241" in repo_error
        assert runner.count(com_ep(241)) == 1     # 数据错误不重试

    def test_gt50_counterexample_server_ignores_paging_params(self):
        """>50-comment 截断反例的**真实形态** (behavior-notes §2 实验 2:
        10cg.local#12, 52 条): 服务端忽略 limit/page 恒全量返回 — mock 按
        「无论 query 如何都回全部 52 条」编码; URL 带 limit=50 只是 house
        形态, 断言全量 52 条到手且对账通过, **不依赖 limit 生效**。"""
        comments_52 = comment_seq(52)
        routes = {
            list_ep(1): [api_issue(12, title="[tracker] 52-comment 真实形态锚 "
                                              "(10cg.local#12)", comments=52)],
            list_ep(2): [],
            # mock 对该 endpoint 只有一条路由 (无 page 变体) — 若实现试图
            # 分页游走 (page=2), FakeRunner 未路由即炸: 游走在本契约下必红。
            com_ep(12): comments_52,
        }
        out, runner = do_fetch_all(routes)
        row = issue_row(out, 12)
        assert runner.count(com_ep(12)) == 1          # 单 GET 无游走
        assert len(row["comments"]) == 52             # 全量到手 (>50 不截断)
        assert row["comments"][0]["id"] < row["comments"][-1]["id"]  # 升序最旧在前
        assert row["comments_error"] is None          # 52 == 52 对账通过

    def test_gt50_negative_collected_lt_count_is_not_silent_half(self):
        """负向: 若响应真被截到 50 (服务端某天开始遵守 limit) ⇒ collected 50 <
        count 52 ⇒ fail-closed 落 unknown, 绝不静默接受 50 条半份。"""
        out, _ = do_fetch_all(
            fetch_all_routes([api_issue(12, comments=52)],
                             comments_by_number={12: comment_seq(50)}))
        row = issue_row(out, 12)
        assert row["comments"] is None
        assert "reconciliation mismatch" in row["comments_error"]


class TestSC2CommentsThreeStates:
    """comments 三态 (DEC-20261018-001 裁定-9 ①): 值 / [] (零评论) / None
    (unknown)。[] 与 None 结构可区分 — 失败不冒充零评论。

    反事实纪律: unknown 塌缩成 [] (退化) ⇒ ``is None`` 断言必红; 零评论
    塌缩成 None ⇒ ``== []`` 断言必红。
    """

    def test_value_state_nonzero_comments(self):
        out, _ = do_fetch_all(
            fetch_all_routes([api_issue(177, comments=6)]))  # 语料锚: Aria#177 = 6
        row = issue_row(out, 177)
        assert isinstance(row["comments"], list) and len(row["comments"]) == 6
        assert row["comments_error"] is None

    def test_zero_comments_is_empty_list_after_reconciliation(self):
        """count 0 + 端点 [] (对账 0==0 通过) ⇒ ``[]`` 零评论态 — 即便零评论
        也发 GET 对账 (不发 GET 的只有计数字段缺席形态)。"""
        out, runner = do_fetch_all(
            fetch_all_routes([api_issue(236, title=TITLE_PRIO_PREFIX, comments=0)]))
        row = issue_row(out, 236)
        assert row["comments"] == []          # 空列表, 不是 None
        assert row["comments_error"] is None
        assert runner.count(com_ep(236)) == 1  # 零评论也有对账 GET

    def test_transport_failure_after_retries_is_unknown(self):
        """传输失败连重试 attempts 次 (默认 3 = 首次 + 重试 2) 后 ⇒ None
        (unknown) + comments_error; 恰 3 次调用。"""
        flaky = FailNTimes(3, fetch.FetchError("wrapper rc=2"), comment_seq(2))
        out, runner = do_fetch_all({
            list_ep(1): [api_issue(241, comments=2)], list_ep(2): [],
            com_ep(241): flaky,
        })
        row = issue_row(out, 241)
        assert row["comments"] is None and row["comments_error"] is not None
        assert runner.count(com_ep(241)) == fetch.DEFAULT_COMMENT_ATTEMPTS == 3

    def test_transient_failure_recovers_within_retry_budget(self):
        """第 3 次 (重试预算内) 恢复 ⇒ 值态落定 (重试不是只能失败)。"""
        flaky = FailNTimes(2, fetch.FetchError("transient"), comment_seq(1))
        out, _ = do_fetch_all({
            list_ep(1): [api_issue(241, comments=1)], list_ep(2): [],
            com_ep(241): flaky,
        })
        row = issue_row(out, 241)
        assert len(row["comments"]) == 1 and row["comments_error"] is None

    def test_count_field_missing_no_get_and_prefilled_error(self):
        """issue 对象 comments 计数字段缺席 ⇒ 对账结构上不可能 ⇒ 不发 GET
        (com endpoint 未路由, 若实现发 GET 则 FakeRunner 直接炸) + None +
        预置 comments_error — 缺席不当 0。"""
        out, runner = do_fetch_all({
            list_ep(1): [api_issue(233, title=TITLE_NO_SIGNAL_233,
                                   comments=None)],  # 键缺席
            list_ep(2): [],
        })
        row = issue_row(out, 233)
        assert row["comments_count"] is None
        assert row["comments"] is None
        assert "count field missing" in row["comments_error"]
        assert not [ep for ep in runner.calls if "/comments" in ep]
        assert out["repos"][0]["error"] is not None  # repo 面汇总可见


# ═════════════════════ SC-3: 每判据独立反事实 ═════════════════════════════

class TestSC3TitlePrefixCriterion:
    """判据 1: title 前缀 (语料实证: 主要存量分类信号, [缺陷]x35/[bug]x6)。

    反事实纪律: 前缀表被清空 (退化) 后同 title 的 category 从 bug 变 unknown —
    若 classify 不真读前缀表 (硬编码/被忽略), 表空变体断言必红; 正向断言
    (有表 ⇒ bug) 与退化断言 (空表 ⇒ unknown) 成对, 保证判据独立起作用。
    """

    def test_prefix_signal_alone_drives_category(self):
        """单判据 fixture: 只给 title 前缀 (无 label/updated/comments_count) ⇒
        唯一信号 = title-prefix, category = bug。"""
        rec = classify_one(tier_issue(223, title=TITLE_BUG_223))
        assert rec["category"] == "bug"
        assert rec["signals"] == [
            {"source": "title-prefix:[bug]", "kind": "title-prefix",
             "value": "[bug]", "category": "bug"},
        ]

    def test_prefix_table_emptied_degrades_to_unknown(self):
        """退化模拟: 前缀表空 (其余层有效) ⇒ [bug] title 不再产信号且 category
        变 unknown — 单判据退化 ⇒ 对应分类判定必红 (bug → unknown)。"""
        rec = classify_one(tier_issue(223, title=TITLE_BUG_223), TAX_NO_PREFIX)
        assert rec["category"] == "unknown"
        assert rec["signals"] == []

    def test_prefix_degradation_does_not_break_label_criterion(self):
        """独立性: 前缀表空 + label 信号 issue ⇒ label 判据照常产 category —
        单判据退化不连坐其他判据。"""
        rec = classify_one(tier_issue(229, title=TITLE_LABEL_ONLY_229,
                                      labels=("bug",)), TAX_NO_PREFIX)
        assert rec["category"] == "bug"
        assert [s["kind"] for s in rec["signals"]] == ["label"]


class TestSC3LabelCriterion:
    """判据 2: label 名 (语料实证: 150 条中仅 5 条有 label, 全部 = "bug" 家族)。

    反事实纪律: label 表被清空后 label-only issue 的 category 从 bug 变
    unknown — 若 classify 不真读 label 表, 表空变体断言必红。
    """

    def test_label_signal_alone_drives_category(self):
        """单判据 fixture: 语料真实 label-only 行 (Aria#229: labels ["bug"],
        title 无分类前缀) ⇒ 唯一分类信号 = label, category = bug。"""
        rec = classify_one(tier_issue(229, title=TITLE_LABEL_ONLY_229,
                                      labels=("bug",)))
        assert rec["category"] == "bug"
        assert rec["signals"] == [
            {"source": "label:bug", "kind": "label", "value": "bug",
             "category": "bug"},
        ]

    def test_label_table_emptied_degrades_to_unknown(self):
        rec = classify_one(tier_issue(229, title=TITLE_LABEL_ONLY_229,
                                      labels=("bug",)), TAX_NO_LABEL)
        assert rec["category"] == "unknown"
        assert rec["signals"] == []

    def test_unknown_label_name_is_no_signal(self):
        """label 不在信号表 (如 area/* 优先级/区域标签) ⇒ 无信号不猜。"""
        rec = classify_one(tier_issue(233, title=TITLE_NO_SIGNAL_233,
                                      labels=("area/infra", "priority/P1")))
        assert rec["category"] == "unknown"
        assert rec["signals"] == []


class TestSC3StalenessTierCriterion:
    """判据 3: staleness 档 ([0,7) / [7,30) / [30,90) / [90,∞) 全分割)。

    反事实纪律: 档位函数退化成常量 ⇒ 同测内 92d 样本的 '>90d' 断言必红
    (3d 样本 '<7d' 仍绿 — 恒绿断言器抓不到的退化被成对样本抓住);
    collapse-detector fixture 把退化显式注入, 验证检测路径本身不是恒绿。
    """

    @pytest.mark.parametrize("updated,expected,anchor", [
        ("2026-10-17", "<7d", "Aria#236 语料真实 updated"),
        ("2026-09-28", "7-30d", "Aria#223 语料真实 updated"),
        ("2026-09-01", "30-90d", "Aria#208 语料真实 updated"),
        ("2026-07-19", ">90d", "Aria#167 语料真实 updated (age 92)"),
        ("2026-10-12", "7-30d", "边界 age==7 含左不含右 (合成)"),
        ("2026-09-19", "30-90d", "边界 age==30 (合成)"),
        ("2026-07-21", ">90d", "边界 age==90 (合成)"),
    ])
    def test_tier_assignment_corpus_anchors(self, updated, expected, anchor):
        """四档全有语料真实样本 + 三条跨档边界 (分割证明的边界含左不含右)。"""
        rec = classify_one(tier_issue(167, updated=updated))
        sig = sig_of(rec, "staleness")
        assert sig is not None and sig["value"] == expected, anchor

    def test_constant_tier_function_collapse_detector(self, monkeypatch):
        """元 fixture: 把退化 (恒返 '<7d') 显式注入 ⇒ 92d 样本档名塌缩 —
        证明正向断言对退化敏感 (检测路径通, 不是恒绿)。"""
        issue = tier_issue(167, updated="2026-07-19")  # age 92
        assert sig_of(classify_one(issue), "staleness")["value"] == ">90d"
        monkeypatch.setattr(tier_a, "staleness_tier", lambda age_days: "<7d")
        collapsed = sig_of(classify_one(issue), "staleness")
        assert collapsed is not None and collapsed["value"] == "<7d"

    def test_future_updated_clamped_to_youngest_tier(self):
        """updated 晚于 now (时钟偏移异常) ⇒ 确定性钳最低龄档, 不抛不猜高档。"""
        rec = classify_one(tier_issue(1, updated="2026-10-26"))  # now 之后 7d
        assert sig_of(rec, "staleness")["value"] == "<7d"

    def test_updated_field_absent_no_staleness_signal(self):
        """updated 缺席 ⇒ 无 staleness 信号 (缺席不是 0 档, 不猜)。"""
        rec = classify_one(tier_issue(1, title="[bug] x"))
        assert sig_of(rec, "staleness") is None


class TestSC3ActivityTierCriterion:
    """判据 4: 活跃度档 ((-∞,0] / [1,2] / [3,9] / [10,∞) 全分割)。

    反事实纪律: 档位函数退化成常量 ⇒ 12 条评论样本的 '10+' 断言必红;
    collapse-detector 同上验证检测路径。
    """

    @pytest.mark.parametrize("count,expected,anchor", [
        (0, "0", "零评论 (语料 150 条中多数)"),
        (1, "1-2", "aria-plugin#208 语料真实 comments=1"),
        (2, "1-2", "档上界 (含)"),
        (3, "3-9", "Aria#211 语料真实 comments=3"),
        (9, "3-9", "档上界 (含)"),
        (10, "10+", "档下界 (含)"),
        (12, "10+", "语料 150 条 max=12"),
    ])
    def test_tier_assignment_corpus_anchors(self, count, expected, anchor):
        rec = classify_one(tier_issue(211, comments_count=count))
        sig = sig_of(rec, "activity")
        assert sig is not None and sig["value"] == expected, anchor

    def test_negative_count_clamped_to_zero_tier(self):
        """负计数 (异常形态) 确定性归 0 档 — 分割在 Z 上全覆盖。"""
        assert sig_of(classify_one(tier_issue(1, comments_count=-3)),
                      "activity")["value"] == "0"

    def test_count_field_absent_no_activity_signal(self):
        """comments_count 缺席 ⇒ 无 activity 信号 — 缺席 ≠ 0 档 (出现即跨档,
        SC-4 复用规则的判据输入面)。"""
        rec = classify_one(tier_issue(1, title="[bug] x"))
        assert sig_of(rec, "activity") is None

    def test_constant_tier_function_collapse_detector(self, monkeypatch):
        issue = tier_issue(1, comments_count=12)
        assert sig_of(classify_one(issue), "activity")["value"] == "10+"
        monkeypatch.setattr(tier_a, "activity_tier", lambda count: "0")
        collapsed = sig_of(classify_one(issue), "activity")
        assert collapsed is not None and collapsed["value"] == "0"


class TestSC3UnknownNegativeFixture:
    """负面 fixture: 无显式编码信号 → category=unknown 不猜 (裁定-7)。

    反事实纪律: 实现「好心」给默认分类 (unknown 退化成某具体类) 或塞隐式
    信号 ⇒ category/signals 精确相等断言必红。
    """

    def test_no_signals_unknown_with_empty_signal_list(self):
        """操作化定义钉死: 无前缀命中 + 无已知 label + updated/comments_count
        缺席 ⇒ 输出恰为 {"category": "unknown", "signals": []}。"""
        rec = classify_one(tier_issue(233, title=TITLE_NO_SIGNAL_233))
        assert rec["category"] == "unknown"
        assert rec["signals"] == []

    def test_priority_prefix_is_not_a_category_signal(self):
        """[P0]-[P4] = 优先级标记非分类信号 (内置层刻意排除; 语料 [P0][AB套件]
        真实形态) ⇒ unknown, signals 空。"""
        rec = classify_one(tier_issue(1, title=TITLE_PRIO_PREFIX))
        assert rec["category"] == "unknown"
        assert rec["signals"] == []

    def test_conflicting_category_signals_reported_not_arbitrated(self):
        """双分类信号不一致 ⇒ conflict (信号集原样枚举, 绝不任选其一 —
        任选即隐性猜测); 属性信号 (staleness) 照常枚举但不参与裁决。"""
        rec = classify_one(tier_issue(1, title="[bug] x", labels=("feature",),
                                      updated="2026-10-01"))
        assert rec["category"] == "conflict"
        assert {s["kind"] for s in rec["signals"]} == {"title-prefix", "label",
                                                        "staleness"}


# ═════════════════════ SC-4: 增量语义五 facet ═════════════════════════════

class TestSC4BaselineNoDiff:
    """facet 1: baseline run = no-diff 专属 fixture (首跑无对照面)。

    反事实纪律: baseline 短路缺失 ⇒ drift 候选池 (new ∪ reclassify = 3 键)
    直接漏进 diff 面 ⇒ 三数组空断言必红。
    """

    def test_baseline_state_absent_yields_empty_diff_face(self, tmp_path):
        engine = make_engine(tmp_path)
        state, baseline = engine.load_state()
        assert baseline is True and state == {}
        issues = [
            fetched_issue(223, title=TITLE_BUG_223, labels=("bug",), comments=[]),
            fetched_issue(229, title=TITLE_LABEL_ONLY_229, comments=[]),
            fetched_issue(233, title=TITLE_NO_SIGNAL_233, comments=None,
                          comments_error="count field missing"),
        ]
        faces = fingerprint.fingerprint_issues(issues)
        classified = tier_a.classify(issues, TAX, now=NOW)
        plan = engine.plan_tier_a(state, faces, classified, CTX_FP["taxonomy_hash"])
        assert plan["baseline_run"] is True          # plan 面有内容 (new=3)
        assert len(plan["new"]) == 3 and len(plan["reclassify"]) == 3
        seg = diffseg.build_diff_segment(plan)       # 默认 top_n=20
        assert seg["new"] == [] and seg["closed"] == [] and seg["drift"] == []
        assert seg["baseline_run"] is True
        assert seg["drift_truncated"] is False and seg["drift_total"] == 0


class TestSC4TopNTruncation:
    """facet 2: top-N 截断防爆量 (100 条全量重评, top_n=20)。

    反事实纪律: 截断静默化 (不报 truncated/total) ⇒ 两个 additive 字段断言
    必红; 截断集非字典序前 20 ⇒ 与 sorted(pool)[:20] 的精确相等必红。
    """

    @staticmethod
    def _hundred_issues() -> list[dict[str, Any]]:
        return [fetched_issue(i, title=f"[bug] bulk corpus #{i}", comments=[])
                for i in range(1, 101)]

    def test_full_reassess_100_top20_exact_truncation_face(self, tmp_path):
        issues = self._hundred_issues()
        engine = make_engine(tmp_path)
        faces = fingerprint.fingerprint_issues(issues)
        classified = tier_a.classify(issues, TAX, now=NOW)
        hash_v1 = tier_a.taxonomy_hash(TAX)
        state1, _ = engine.load_state()
        plan1 = engine.plan_tier_a(state1, faces, classified, hash_v1)
        next1 = engine.build_next_state(state1, plan1, faces, classified,
                                        hash_v1, CTX_FP, PROV)
        engine.save_state(next1)

        # 第二轮: taxonomy 升级 (hash 变) ⇒ 全量重评 100 条 (真 plan, 非 hand-built)
        state2, _ = engine.load_state()
        hash_v2 = tier_a.taxonomy_hash(TAX_NO_LABEL)  # 规则变化 ⇒ 不同 hash
        plan2 = engine.plan_tier_a(state2, faces, classified, hash_v2)
        assert plan2["reused"] == [] and len(plan2["reclassify"]) == 100
        seg = diffseg.build_diff_segment(plan2, top_n=20)
        assert len(seg["drift"]) == 20                       # 恰 20
        assert seg["drift_truncated"] is True
        assert seg["drift_total"] == 100                     # 截断前全量计数
        pool = sorted(set(plan2["reclassify"]))              # 字典序 (键字符串序)
        assert seg["drift"] == pool[:20]
        assert seg["baseline_run"] is False

    def test_untruncated_face_reports_total_equal_to_len(self, tmp_path):
        """未截断对照: top_n=100 容纳全量 ⇒ truncated=False, total == len(drift)。"""
        plan = {
            "baseline_run": False, "new": [], "closed": [],
            "reused": [], "reclassify": [f"Aria#{i}" for i in range(1, 11)],
        }
        seg = diffseg.build_diff_segment(plan, top_n=100)
        assert seg["drift_truncated"] is False
        assert seg["drift_total"] == len(seg["drift"]) == 10


class TestSC4CommentsThreeStateFingerprint:
    """facet 3: issue 面指纹的 comments 三态 (值 / None-零评论 / "unknown")。

    语料锚: comment 默认时间戳 = Aria#233 真实 comment (28794 @
    2026-10-15T16:58:30Z, sample body+comments 语料)。
    反事实纪律: 任一态塌缩成另一态 (失败当零评论/零评论当失败) ⇒ 三 key
    两两互异断言必红 (combined_issue_key 序列化 null vs "unknown" vs 值)。
    """

    def test_value_state_takes_max_updated_at_order_insensitive(self):
        """值态 = max(updated_at), 自取 max 不依赖上游顺序 (端点升序只是实测
        事实); 升序/乱序同面。"""
        asc = comment_seq(3)
        desc = list(reversed(asc))
        f_asc = fingerprint.issue_face(fetched_issue(233, comments=asc))
        f_desc = fingerprint.issue_face(fetched_issue(233, comments=desc))
        assert f_asc == f_desc
        assert f_asc["comments_latest_updated_at"] == asc[-1]["updated_at"]

    def test_value_state_oldest_row_edit_beats_newer_creation(self):
        """comment-edit 判别 (合成 updated_at>created_at, 置于最老行): 最新值
        必须取 max(updated_at) — 取最后一行 / max(created_at) / count 的错误
        代理全部错过该编辑 ⇒ 断言红。"""
        rows = comment_seq(3)
        edited = dict(rows[0])  # 最老一条被编辑
        edited["updated_at"] = "2026-10-18T09:00:00Z"  # > 全部 created_at
        face = fingerprint.issue_face(fetched_issue(233, comments=[edited, *rows[1:]]))
        assert face["comments_latest_updated_at"] == "2026-10-18T09:00:00Z"

    def test_empty_comments_is_none_state(self):
        face = fingerprint.issue_face(fetched_issue(236, comments=[]))
        assert face["comments_latest_updated_at"] is None  # 零评论 ≠ unknown

    @pytest.mark.parametrize("issue", [
        fetched_issue(241, comments=None),
        fetched_issue(241, comments=None, comments_error="comments fetch failed: X"),
        fetched_issue(241, comments=[{"id": 1, "created_at": "2026-10-01T00:00:00Z",
                                      "updated_at": "2026-10-01T00:00:00Z"}],
                      comments_error="count reconciliation mismatch"),
        fetched_issue(241, comments=[{"id": 1, "created_at": "2026-10-01T00:00:00Z"}]),
    ], ids=["fetch-none", "fetch-error", "recon-mismatch-nonempty-list",
            "single-row-missing-timestamp"])
    def test_degraded_comment_faces_are_unknown_string(self, issue):
        """unknown 态的四种到达路径: comments=None / comments_error 在场 (即便
        列表非空 — fetch_error 纪律优先) / 对账不匹配 / 单条 updated_at 缺席。"""
        face = fingerprint.issue_face(issue)
        assert face["comments_latest_updated_at"] == fingerprint.COMMENTS_UNKNOWN
        assert face["comments_latest_updated_at"] == "unknown"  # 哨兵值钉死

    def test_three_states_pairwise_distinct_in_issue_key(self):
        """三态在 combined_issue_key 层两两互异 — 任一态实现塌缩 (如失败冒充
        零评论) ⇒ 集合大小 < 3 必红。"""
        faces = [
            fingerprint.issue_face(fetched_issue(1, comments=comment_seq(2))),
            fingerprint.issue_face(fetched_issue(1, comments=[])),
            fingerprint.issue_face(fetched_issue(1, comments=None)),
        ]
        keys = {fingerprint.combined_issue_key(f) for f in faces}
        assert len(keys) == 3


class TestSC4ReuseRuleCrossTier:
    """facet 4: 复用规则 — 判据输入变而 issue_key 同 ⇒ 重分类不复用。

    核心构造: issue 面指纹不读 updated/created ⇒ 纯时钟流逝 (now 前进跨档)
    时 issue_key 逐字节不变, 但 judgement_inputs.staleness_tier 跨档 ⇒
    plan 归 reclassify 而非 reused。
    反事实纪律: 复用门退化成只比 issue_key (judgement_inputs 缺失/恒等) ⇒
    跨档轮 key 误进 reused ⇒ 「not in reused」断言必红。
    """

    def test_pure_clock_cross_tier_same_issue_key_recategorizes(self, tmp_path):
        issue = fetched_issue(223, title=TITLE_BUG_223, labels=("bug",),
                              updated="2026-10-01", comments=[])  # 指纹输入两轮逐字节同
        now_young = datetime(2026, 10, 3, tzinfo=timezone.utc)   # age 2  ⇒ <7d
        now_crossed = datetime(2026, 12, 1, tzinfo=timezone.utc)  # age 61 ⇒ 30-90d
        key = "Aria#223"
        hash_v = tier_a.taxonomy_hash(TAX)

        engine = make_engine(tmp_path, now=now_young)
        faces = fingerprint.fingerprint_issues([issue])
        c1 = tier_a.classify([issue], TAX, now=now_young)
        state1, _ = engine.load_state()
        plan1 = engine.plan_tier_a(state1, faces, c1, hash_v)
        engine.save_state(engine.build_next_state(state1, plan1, faces, c1,
                                                  hash_v, CTX_FP, PROV))

        state2, _ = engine.load_state()
        c2 = tier_a.classify([issue], TAX, now=now_crossed)
        assert fingerprint.fingerprint_issues([issue]) == faces  # issue_key 同
        assert sig_of(c2[0], "staleness")["value"] != sig_of(c1[0], "staleness")["value"]
        plan2 = engine.plan_tier_a(state2, faces, c2, hash_v)
        assert key in plan2["reclassify"]
        assert key not in plan2["reused"]

    def test_same_tier_clock_advance_reuses(self, tmp_path):
        """对照组: 时钟前进但未跨档 (age 1 → 4, 同 <7d) ⇒ 复用 (差集代数的
        另一半 — 复用门不能过度触发, 否则每轮全量重评)。"""
        issue = fetched_issue(223, title=TITLE_BUG_223, updated="2026-10-01",
                              comments=[])
        hash_v = tier_a.taxonomy_hash(TAX)
        engine = make_engine(tmp_path, now=datetime(2026, 10, 2, tzinfo=timezone.utc))
        faces = fingerprint.fingerprint_issues([issue])
        c1 = tier_a.classify([issue], TAX, now=engine._now_fn())
        state1, _ = engine.load_state()
        plan1 = engine.plan_tier_a(state1, faces, c1, hash_v)
        engine.save_state(engine.build_next_state(state1, plan1, faces, c1,
                                                  hash_v, CTX_FP, PROV))
        state2, _ = engine.load_state()
        c2 = tier_a.classify([issue], TAX,
                             now=datetime(2026, 10, 5, tzinfo=timezone.utc))
        plan2 = engine.plan_tier_a(state2, faces, c2, hash_v)
        assert "Aria#223" in plan2["reused"]
        assert "Aria#223" not in plan2["reclassify"]

    def test_judgement_inputs_snapshot_fields_pinned(self):
        """判据输入快照恰含三键 (staleness_tier / activity_tier /
        taxonomy_hash) — 比较面的键集钉死: 缺任一键 ⇒ SC-4 facet 4 的跨档
        检测在该分量上失效 (fixture 红线)。"""
        rec = classify_one(tier_issue(223, title=TITLE_BUG_223,
                                      updated="2026-10-17", comments_count=1))
        inputs = incremental.judgement_inputs_from(rec, "hash-x")
        assert set(inputs) == {"staleness_tier", "activity_tier", "taxonomy_hash"}
        assert inputs["staleness_tier"] == "<7d"  # age 2 @ NOW
        assert inputs["activity_tier"] == "1-2"


class TestSC4ProvenanceGate:
    """facet 5: Tier B provenance 门 — 复用门 = combined_provenance_key 完整
    拼接串 (harness + model_id 两分量都比对); provenance 变 ⇒ stale。

    反事实纪律: 门退化成只比 harness (省略 model_id) ⇒ model_id 单独变体
    被误 reusable ⇒ mismatch 断言必红; model_id=None 冒充通配 ⇒ None 变体
    误 reusable ⇒ 必红。
    """

    @staticmethod
    def _gate(entries: dict[str, Any], current: dict[str, Any],
              keys: set[str] | None = None, ttl: int | None = None,
              now: datetime = NOW) -> dict[str, Any]:
        engine = incremental.IncrementalEngine(
            "unused-state-path",
            assessments_reader=lambda: {"schema_version": 1, "assessments": entries},
            now_fn=lambda: now,
        )
        return engine.gate_tier_b(current, current_keys=keys, assessments_ttl=ttl)

    ENTRY = {"provenance": {"harness": "claude-code", "model_id": "glm-5.2"},
             "created_at": "2026-10-19T08:00:00Z"}
    CURRENT = {"harness": "claude-code", "model_id": "glm-5.2"}

    def test_exact_provenance_match_is_reusable(self):
        gate = self._gate({"Aria#233": copy.deepcopy(self.ENTRY)},
                          copy.deepcopy(self.CURRENT))
        assert gate["reusable"] == ["Aria#233"] and gate["stale"] == {}

    def test_harness_change_is_mismatch(self):
        current = {"harness": "opencode", "model_id": "glm-5.2"}
        gate = self._gate({"Aria#233": copy.deepcopy(self.ENTRY)}, current)
        assert gate["stale"]["Aria#233"] == "provenance-mismatch"

    def test_model_id_change_alone_is_mismatch(self):
        """model_id 单独变 (harness 同) ⇒ stale — 门比对完整拼接串, 不是只比
        harness。退化成只比 harness 时本 fixture 必红。"""
        current = {"harness": "claude-code", "model_id": "glm-5.3"}
        gate = self._gate({"Aria#233": copy.deepcopy(self.ENTRY)}, current)
        assert gate["stale"]["Aria#233"] == "provenance-mismatch"

    def test_script_layer_model_none_never_matches_concrete(self):
        """本轮 model_id=None (脚本层未知) vs entry 具体 model_id ⇒ mismatch —
        fail-closed: 宁重评不误复用。"""
        current = {"harness": "claude-code", "model_id": None}
        gate = self._gate({"Aria#233": copy.deepcopy(self.ENTRY)}, current)
        assert gate["stale"]["Aria#233"] == "provenance-mismatch"

    @pytest.mark.parametrize("entry,reason", [
        ({"created_at": "2026-10-19T08:00:00Z"}, "provenance-missing"),
        ({"provenance": {"harness": "claude-code"},  # 缺 model_id 分量
          "created_at": "2026-10-19T08:00:00Z"}, "provenance-invalid"),
        ("garbage-not-an-object", "entry-not-object"),
        ({"provenance": {"harness": "claude-code", "model_id": "glm-5.2"}},
         "created-at-missing"),
    ], ids=["prov-missing", "prov-invalid", "entry-not-object", "created-missing"])
    def test_malformed_entries_fail_closed_per_reason(self, entry, reason):
        gate = self._gate({"Aria#233": entry}, copy.deepcopy(self.CURRENT))
        assert gate["stale"]["Aria#233"] == reason
        assert incremental.STALE_REASONS is not None and reason in incremental.STALE_REASONS

    def test_out_of_scope_key_is_orphaned_not_stale(self):
        """键不在本轮 current_keys ⇒ orphaned (issue 已关闭/移出作用域 — 不
        复用也不 stale, 与 provenance 失败正交)。"""
        gate = self._gate({"Aria#999": copy.deepcopy(self.ENTRY)},
                          copy.deepcopy(self.CURRENT), keys={"Aria#233"})
        assert gate["orphaned"] == ["Aria#999"]
        assert gate["stale"] == {} and gate["reusable"] == []

    def test_ttl_boundary_day_counts_as_expired(self):
        """ttl 激活时 created_at + ttl ≤ now 即过期 (边界算过期):
        created 2026-10-12 + ttl 7 = 10-19 ≤ now 10-19 ⇒ expired;
        ttl 未激活 (None) 同时长不判过期。"""
        entry = {"provenance": {"harness": "claude-code", "model_id": "glm-5.2"},
                 "created_at": "2026-10-12T12:00:00Z"}
        gate_on = self._gate({"Aria#233": entry}, copy.deepcopy(self.CURRENT), ttl=7)
        assert gate_on["stale"]["Aria#233"] == "ttl-expired"
        gate_off = self._gate({"Aria#233": entry}, copy.deepcopy(self.CURRENT), ttl=None)
        assert gate_off["reusable"] == ["Aria#233"]


# ═════════════════════ SC-5: 差集 + 幂等 + schema 封闭 ═════════════════════

# 项目级 taxonomy (裁定① 覆盖层): canonical label 与信号名分离 (kind/bug),
# 使「existing 与 suggested 部分交集」可构造。
PROJECT_LABELS_YAML = """\
version: 1
categories:
  bug: kind/bug
  feature: kind/feature
title_prefixes:
  "[bug]": bug
  "[缺陷]": bug
  "[feature]": feature
label_signals:
  kind/bug: bug
  bug: bug
  kind/feature: feature
"""


def groom_run(tmp_path: Path, corpus: dict[str, Any]) -> dict[str, Any]:
    """进程内跑全编排 (fake runner + request_interval=0 + 时钟注入)。

    B-2 前提: --repos 显式 ⇒ strict 路径映射 — 主仓 origin 推导为
    10CG/Aria (git init + remote), 否则 resolve_git_roots 按设计 ConfigError。
    """
    (tmp_path / ".aria").mkdir(exist_ok=True)
    (tmp_path / ".aria" / "labels.yaml").write_text(PROJECT_LABELS_YAML,
                                                    encoding="utf-8")
    if not (tmp_path / ".git").exists():
        subprocess.run(["git", "-C", str(tmp_path), "init", "-q"],
                       check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "remote", "add", "origin",
             "git@forgejo.10cg.pub:10CG/Aria.git"],
            check=True, capture_output=True)
    args = groom.parse_args([
        "--repos", "Aria",
        "--project-root", str(tmp_path),
        "--harness", "test-harness",
        "--model-id", "test-model",
        "--now", NOW_ISO,
        "--quiet",
    ])
    return groom.run_pipeline(args, runner=FakeRunner(corpus), request_interval=0)


def sc5_corpus() -> dict[str, Any]:
    """SC-5 差集面 corpus (issue-list 行 + comments 路由):

    - Aria#223: title [bug] 前缀, labels []           ⇒ suggested [kind/bug],
      existing []                    ⇒ add [kind/bug]        (差集 = 全量)
    - Aria#229: label 信号 "bug", labels ["bug"]       ⇒ suggested [kind/bug],
      existing ["bug"]               ⇒ add [kind/bug]        (交集空: 信号名 ≠ canonical)
    - Aria#900: title [bug], labels [kind/bug, area/infra] ⇒ existing ⊇
      suggested 单元素 (部分交集含差集) ⇒ add []             (交集被减掉)
    - Aria#241: 无信号 ⇒ unknown ⇒ suggested [] ⇒ add [] (不猜)
    - Aria#233: [Layer L] 前缀不在表, comments 1 (真实计数锚) ⇒ unknown。
    """
    issues = [
        api_issue(223, title=TITLE_BUG_223, labels=(), comments=0,
                  updated="2026-09-28T00:00:00Z"),
        api_issue(229, title=TITLE_LABEL_ONLY_229, labels=("bug",), comments=0,
                  updated="2026-10-07T00:00:00Z"),
        api_issue(900, title="[bug] 卫星仓 CI 拉取超时 (合成差集行)",
                  labels=("kind/bug", "area/infra"), comments=0),
        api_issue(241, title="讨论型条目 (无前缀无 label)", comments=2,
                  updated="2026-10-01T00:00:00Z"),
        api_issue(233, title=TITLE_NO_SIGNAL_233, comments=1,
                  updated="2026-10-15T00:00:00Z"),
    ]
    routes = fetch_all_routes(issues, comments_by_number={
        241: comment_seq(2), 233: [api_comment(28794)],
    })
    return routes


def sc5_payloads(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {f"{e['repo']}#{e['number']}": e["labels_payload"]
            for e in report["issues"]}


class TestSC5DifferenceAlgebra:
    """apply_payload.add = suggested − existing 差集 (SC-5 主断言, harness 无关)。

    反事实纪律: add 退化成 suggested 原样 (不减 existing) ⇒ #900 的 add ==
    ["kind/bug"] 非空 ⇒ 断言必红; 退化成 suggested ∩ existing ⇒ #223 (交集
    空) add 恒空 ⇒ 必红。
    """

    def test_difference_on_partial_intersection_corpus(self, tmp_path):
        report = groom_run(tmp_path, sc5_corpus())
        payloads = sc5_payloads(report)
        assert payloads["Aria#223"]["suggested"] == ["kind/bug"]
        assert payloads["Aria#223"]["apply_payload"]["add"] == ["kind/bug"]
        # existing 与 suggested 交集空 (label 信号名 "bug" ≠ canonical "kind/bug")
        assert payloads["Aria#229"]["suggested"] == ["kind/bug"]
        assert payloads["Aria#229"]["apply_payload"]["add"] == ["kind/bug"]
        # 部分交集: existing ⊇ suggested 单元素 ⇒ 交集被差集吃掉
        assert payloads["Aria#900"]["existing"] == ["kind/bug", "area/infra"]
        assert payloads["Aria#900"]["suggested"] == ["kind/bug"]
        assert payloads["Aria#900"]["apply_payload"]["add"] == []
        # unknown/conflict 不在 categories ⇒ 无建议 (不猜)
        assert payloads["Aria#241"]["suggested"] == []
        assert payloads["Aria#241"]["apply_payload"]["add"] == []
        assert payloads["Aria#233"]["suggested"] == []

    def test_add_disjoint_from_existing_for_every_entry(self, tmp_path):
        """差集代数第一半: 全条目 add ∩ existing = ∅ (已有标签必然不在 add 内)。"""
        report = groom_run(tmp_path, sc5_corpus())
        for entry in report["issues"]:
            add = set(entry["labels_payload"]["apply_payload"]["add"])
            existing = set(entry["labels_payload"]["existing"])
            assert not (add & existing), f"{entry['repo']}#{entry['number']}"


class TestSC5IdempotentAlgebra:
    """幂等 fixture — **mock 不编码 no-op** (SC-5 纪律)。

    「forgejo 对已有 label 的 add 为 no-op」是外部 API 行为断言, 唯一记录面 =
    references/forgejo-behavior-notes.md §1 (2026-10-19 live 实测, 实例
    11.0.16+gitea-1.22.0); 本测试不 mock forgejo API (防断言循环自证, spec
    §3 原文)。此处幂等 = 纯差集代数: (a) add ∩ existing = ∅;
    (b) 重复 apply 差集为空 — apply add 后 existing' = existing ∪ add,
    suggested − existing' = ∅。
    反事实纪律: add 非 suggested−existing (全量/交集) ⇒ (a) 或 (b) 必红。
    """

    def test_repeated_apply_difference_is_empty(self, tmp_path):
        report = groom_run(tmp_path, sc5_corpus())
        for entry in report["issues"]:
            lp = entry["labels_payload"]
            add, existing, suggested = (set(lp["apply_payload"]["add"]),
                                        set(lp["existing"]), set(lp["suggested"]))
            assert lp["apply_payload"]["idempotent"] is True  # schema const 钉死
            after_first_apply = existing | add
            assert not (suggested - after_first_apply)  # 第二轮差集恒空
            assert not (add & existing)

    def test_difference_is_minimal_write_face(self, tmp_path):
        """差集 = 写放大最小化 (live 实测结论 3: fresh add 每次 bump
        updated_at, 全量重加污染时间戳): add 恰为 suggested 中不在 existing
        的那部分 — 不多打一个已有标签。"""
        report = groom_run(tmp_path, sc5_corpus())
        for entry in report["issues"]:
            lp = entry["labels_payload"]
            assert set(lp["apply_payload"]["add"]) == \
                set(lp["suggested"]) - set(lp["existing"])


class TestSC5SchemaClosedKeySet:
    """schema 封闭键集反事实: LabelsPayload / ApplyPayload 均无 remove 键
    (additionalProperties:false) — 删标签动作在本契约中结构性不可表达
    (裁定-8)。注入 remove 字段的 payload ⇒ schema 校验必红。

    反事实纪律: 键集开放 (additionalProperties 退化为 true / remove 被合法
    化) ⇒ 注入后 mini_validate 仍返回 [] ⇒ 「非空」断言必红。
    """

    def test_report_validates_then_remove_injection_fails(self, tmp_path):
        report = groom_run(tmp_path, sc5_corpus())
        schema = json.loads(Path(SCHEMA_PATH).read_text(encoding="utf-8"))
        assert mini_validate(report, schema) == []  # 未注入: 真 report 合法

        inj_payload = copy.deepcopy(report)
        inj_payload["issues"][0]["labels_payload"]["apply_payload"]["remove"] = \
            ["kind/feature"]
        errors = mini_validate(inj_payload, schema)
        assert errors != [] and any("remove" in e for e in errors)

        inj_outer = copy.deepcopy(report)
        inj_outer["issues"][0]["labels_payload"]["remove"] = ["kind/feature"]
        assert mini_validate(inj_outer, schema) != []

    def test_apply_payload_key_set_pinned_in_real_report(self, tmp_path):
        """真报告全条目 apply_payload 键集恰 {repo, number, add, idempotent} —
        生产者面从未携带 remove (结构性, 非运行时承诺)。"""
        report = groom_run(tmp_path, sc5_corpus())
        for entry in report["issues"]:
            ap = entry["labels_payload"]["apply_payload"]
            assert set(ap) == {"repo", "number", "add", "idempotent"}
            assert "remove" not in ap


# ═════════════════════ SC-9: taxonomy 三层注错 ═════════════════════════════

# 三层注错 yaml 文本 (受限语法; 每份只注错一层, 其余两层有效 — 三种独立):
BAD_LAYER1_YAML = """\
version: 1
categories:
  bug: bug
  feature: feature
title_prefixes:
  "[bug]": no-such-category
label_signals:
  bug: bug
"""
BAD_LAYER2_YAML = """\
version: 1
categories:
  bug: ""
  feature: feature
title_prefixes:
  "[bug]": bug
label_signals:
  bug: bug
"""
BAD_LAYER3_YAML = """\
version: 1
categories:
  bug: bug
  feature: feature
title_prefixes:
  "[bug]": bug
label_signals:
  bug: feature
"""


class TestSC9TaxonomyThreeLayerInjection:
    """SC-9: 前缀表 / 分类键 / label 名三层各注错一份 ⇒ validate_taxonomy 必红
    (三种独立, 单层注错 ⇒ 恰一层错误, 无跨层污染)。

    反事实纪律: 某层校验退化成 no-op (检查缺失) ⇒ 该层注入返回空清单 ⇒
    非空断言必红; 「恰一条」断言同时钉死三层独立性 (一层注错不连坐)。
    """

    def _builtin(self) -> dict[str, Any]:
        return tier_a.load_builtin_taxonomy()

    def test_layer1_prefix_table_unknown_category(self):
        """前缀表注错: prefix 指向不存在的分类键 ⇒ 恰一条 prefix-unknown-category。"""
        tax = self._builtin()
        tax["title_prefixes"] = {"[bug]": "no-such-category"}
        problems = tier_a.validate_taxonomy(tax)
        assert len(problems) == 1
        assert problems[0].startswith("prefix-unknown-category: prefix '[bug]'")

    def test_layer2_category_key_empty_canonical_label(self):
        """分类键注错: canonical label 空 ⇒ 恰一条 canonical-label-empty。"""
        tax = self._builtin()
        tax["categories"] = {**tax["categories"], "bug": "  "}
        problems = tier_a.validate_taxonomy(tax)
        assert len(problems) == 1
        assert problems[0].startswith("canonical-label-empty: category 'bug'")

    def test_layer2_canonical_label_collision(self):
        """分类键注错 (第二形态): 两分类键 → 同一规范 label ⇒ 建议标签归属
        歧义, 恰一条 canonical-label-collision。"""
        tax = self._builtin()
        tax["categories"] = {**tax["categories"], "bug": "shared", "feature": "shared"}
        problems = tier_a.validate_taxonomy(tax)
        assert len(problems) == 1
        assert problems[0].startswith("canonical-label-collision: label 'shared'")

    def test_layer3_label_signal_unknown_category(self):
        """label 名注错: label 信号指向不存在的分类键 ⇒ 恰一条
        label-signal-unknown-category。"""
        tax = self._builtin()
        tax["label_signals"] = {**tax["label_signals"], "bug": "no-such-category"}
        problems = tier_a.validate_taxonomy(tax)
        assert len(problems) == 1
        assert problems[0].startswith("label-signal-unknown-category: label 'bug'")

    def test_layer3_canonical_label_contradiction(self):
        """label 名注错 (第二形态): label 是分类 X 的规范名、又指向 Y ⇒
        「被 X 建议」与「建议 Y」自相矛盾, 恰一条 contradiction。"""
        tax = self._builtin()
        tax["label_signals"] = {**tax["label_signals"], "bug": "feature"}
        problems = tier_a.validate_taxonomy(tax)
        assert len(problems) == 1
        assert problems[0].startswith(
            "canonical-label-contradiction: label 'bug'")

    def test_builtin_layer_is_clean(self):
        """对照组: 内置保守默认层零问题 (四条注错全红才有意义)。"""
        assert tier_a.validate_taxonomy(self._builtin()) == []

    @pytest.mark.parametrize("yaml_text,marker", [
        (BAD_LAYER1_YAML, "prefix-unknown-category"),
        (BAD_LAYER2_YAML, "canonical-label-empty"),
        (BAD_LAYER3_YAML, "canonical-label-contradiction"),
    ], ids=["layer1-prefix", "layer2-category", "layer3-label"])
    def test_injected_yaml_load_fail_closed(self, yaml_text, marker):
        """三层注错 yaml 各一份 ⇒ load_taxonomy_text 抛 ValueError 且消息指名
        该层 — 加载面 fail-closed (绝不带病上岗)。"""
        with pytest.raises(ValueError, match=marker):
            tier_a.load_taxonomy_text(yaml_text, source="<sc9-injection>")

    def test_project_layer_error_never_falls_back_to_builtin(self, tmp_path):
        """裁定① fail-closed: 项目级 labels.yaml 注错 ⇒ resolve_taxonomy 抛
        ValueError, 绝不静默回落内置层 (静默回落 = 拿错误 taxonomy 跑全量)。"""
        aria = tmp_path / ".aria"
        aria.mkdir()
        (aria / "labels.yaml").write_text(BAD_LAYER1_YAML, encoding="utf-8")
        with pytest.raises(ValueError, match="prefix-unknown-category"):
            tier_a.resolve_taxonomy(tmp_path)

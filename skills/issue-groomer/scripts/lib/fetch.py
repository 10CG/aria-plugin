#!/usr/bin/env python3
"""issue-groomer forgejo fetch 层 (P1 MVP, 10CG/Aria#238, TASK-001).

库层 (非 CLI): 输入 repos 配置 (裸仓名或 owner/仓名列表, 形如
state_scanner.issue_scan 的主仓+卫星仓清单), 输出结构化 issue + comments
数据, 供 Tier A 规则引擎 (lib/tier_a.py) 与增量指纹层消费。调用通道 =
house forgejo CLI wrapper (subprocess capture_output; Rule #7 纪律: wrapper
stdout 永不透传到任何 chat-visible 面, 错误面只带 rc + wrapper 已脱敏的
stderr 尾部行)。CLI 通道可注入 (runner 协议 = ``call(method, endpoint)``),
测试用 fake runner mock, 不触网络。

双端点契约 (含 2026-10-19 Runtime Amendment; 实测事实 SOT =
``references/forgejo-behavior-notes.md``, Forgejo 11.0.16+gitea-1.22.0):

1. **issue-list 端点 — 真分页**:
   ``GET /repos/{o}/{r}/issues?state=open&type=issues&limit=50`` 逐页递增
   ``&page=N``。终止条件 = **空页** (实测越界页返回空数组), 不是短页 — 服务端
   可能夹小页大小, 短页不等于最后一页 (state-scanner issue_scan QA-C2 与
   regen_corpus 同一纪律); 短页后继续探测, 多花一次请求换零丢失保证。
   跨页按 ``number`` 去重 (窗口漂移防御); 整页全为已见条目 / 触及页上限
   (page_ceiling) ⇒ 该仓 FetchError — 结构上不可能静默产出半份列表。
   page 1 的 URL 不带 ``&page=`` (与 regen_corpus 逐字节同形)。
2. **comments 端点 — 不做分页游走 (Amendment 修正)**: 实测该端点**忽略
   limit/page 恒全量返回** (升序最旧在前; 越界页回吐同页非空)。契约 =
   **单次 GET 全量 + 用 issue 对象的 ``comments`` 计数字段对账**:
   ``len(collected) != count`` ⇒ 该 issue 的 comments 数据置 None (unknown)
   + fetch_error, 绝不静默截断、绝不冒充零评论。代码**不依赖 limit 生效**
   (URL 带 ``limit=50`` 只是 house 形态; 完备性证明 = 计数对账, 非 limit
   参数 — >50-comment 截断反例 fixture 的真实形态即「服务端忽略分页参数」)。
3. **comments 三态** (对齐 DEC-20261018-001 裁定-9 issue 面指纹的 comments
   最新 updated_at 三态):
   - ``[row, ...]`` 非空 list = 有评论 (值)
   - ``[]``         空 list    = 零评论 (count==0 且端点对账 0==0 通过)
   - ``None``                  = unknown — 传输失败连重试 ``comment_attempts``
     次 (默认 3 = 首次 + 重试 2, 任务契约「连重试 2 次后」) / issue 对象
     ``comments`` 计数字段缺席或非法 (对账结构上不可能, 不发 GET) / 计数
     对账不匹配 (数据错误非传输错误, 不重试直接 fail-closed)。
     None 与 [] 结构可区分 — 失败不冒充零评论。
   issue-list 页失败**不重试**: 整仓 fail-closed (repo 条目 error 显式可见,
   可整跑重试), 不静默降级到部分数据。
4. **PR 混同双保险**: ``type=issues`` 请求参数 + 客户端过滤 (``pull_request``
   为非空 dict, 或 html_url/url 含 ``/pulls/``) — QA-C2 结论, 两者都做。
5. **多仓隔离**: 每仓独立 try — 一仓挂不连坐。失败面: issue-list 失败 =
   该仓 repo 条目 ``error`` + ``open_issues=0`` + 零条目; **normalize 阶段
   ValueError (行形态非法) 同入该仓 ``error``** (E-1: 归一化失败 = 该仓数据
   不可信, 不连坐其他仓, 也不静默丢行); comments 失败 = 逐条
   ``comments_error`` + repo 条目 ``error`` 汇总 (计数 + issue 号清单,
   超过 20 条折叠)。重复仓去重按 ``split_repo_spec`` 后的 **(owner, repo)
   二元组** (E-3: 别名双写 — 如 ``"Aria"`` 与 ``"10CG/Aria"`` — 不重复
   抓取; 保序)。**rc=0 + 空 stdout (runner 返回 None) ≠ 空页**: 空页是
   JSON ``[]``; None = 响应面结构违规 ⇒ FetchError (A-2), 绝不当空页
   (空 stdout 当空页 = 把「端点哑了」静默折成「仓里没 issue」)。
6. **限速礼貌**: 每两次请求之间 sleep ``request_interval`` (默认 0.1s; 含
   重试请求; 首个请求前不 sleep; 置 0 关闭)。

输出形态 (``fetch_all`` 返回值)::

    {"repos":   [{"repo": <裸仓名>, "open_issues": <int>, "error": <None|str>}, ...],
     "issues":  [{repo, number, title, labels, created, updated,
                  comments_count, body, comments, comments_error}, ...]}

issue 行是 tier_a.classify 输入契约 (``{repo, number, title, labels,
created, updated, comments_count?}``) 的**超集**: 额外带 ``body`` /
``comments`` / ``comments_error`` 供指纹层 (title/body/labels hash +
comments 最新 updated_at 三态) 与报告层消费。created/updated 取日期面
(``[:10]``, 语料快照同形; Tier A staleness 只用日期精度); comment 行的
created_at/updated_at 保留完整 ISO 精度 (comment-edit 判别需要
updated_at>created_at 的可比性) 且**保持端点返回顺序** (实测升序最旧在前;
指纹层自取 max(updated_at), 不依赖本层重排)。comment 行归一为
``{id, created_at, updated_at, body}``。
"""
from __future__ import annotations

import json
import subprocess
import time
from typing import Any, Sequence

__all__ = [
    "FetchError",
    "ForgejoCliRunner",
    "Session",
    "DEFAULT_BIN",
    "DEFAULT_OWNER",
    "DEFAULT_TIMEOUT_S",
    "DEFAULT_PAGE_SIZE",
    "DEFAULT_PAGE_CEILING",
    "DEFAULT_REQUEST_INTERVAL",
    "DEFAULT_COMMENT_ATTEMPTS",
    "split_repo_spec",
    "list_repo_issues",
    "fetch_issue_comments",
    "normalize_issue",
    "fetch_all",
]

DEFAULT_BIN = "/home/dev/.npm-global/bin/forgejo"
DEFAULT_OWNER = "10CG"
DEFAULT_TIMEOUT_S = 120.0
DEFAULT_PAGE_SIZE = 50           # Forgejo 服务端页大小上限 (超出也被夹)
DEFAULT_PAGE_CEILING = 200       # 单仓安全上限: 200 页 x 50 = 10k 条
DEFAULT_REQUEST_INTERVAL = 0.1   # 每两次请求之间的礼貌 sleep (秒)
DEFAULT_COMMENT_ATTEMPTS = 3     # 首次 + 重试 2 (契约「连重试 2 次后」)


class FetchError(RuntimeError):
    """单次 (或重试组) forgejo 调用 / 响应结构校验失败。

    ``endpoint`` 属性携带归因面 (供上层汇总); message 只含 rc + wrapper 已
    脱敏的 stderr 尾部行, 绝不含 wrapper stdout 原文 (Rule #7)。
    """

    def __init__(self, message: str, *, endpoint: str | None = None) -> None:
        super().__init__(message)
        self.endpoint = endpoint


# ---------------------------------------------------------- forgejo CLI 通道

class ForgejoCliRunner:
    """经 house CLI wrapper 的默认通道 (对齐 regen_corpus.Forgejo 模式)。

    ``call(method, endpoint, payload=None)`` → 解析后的 JSON (rc=0 且 stdout
    为空时返回 None); 失败抛 FetchError (rc!=0 / 超时 / wrapper 不可执行 /
    stdout 非 JSON)。凭据脱敏与端点 fallback 都活在 wrapper 内, 本类只做
    subprocess + 解析; stdout 永不透传。
    """

    def __init__(self, bin_path: str = DEFAULT_BIN, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        self._bin = bin_path
        self._timeout_s = timeout_s

    def call(self, method: str, endpoint: str, payload: dict[str, Any] | None = None) -> Any:
        cmd = [self._bin, method, endpoint]
        if payload is not None:
            cmd += ["-d", json.dumps(payload, ensure_ascii=False)]
        try:
            proc = subprocess.run(  # noqa: S603 固定 house wrapper 路径 (可注入替换)
                cmd, capture_output=True, text=True, timeout=self._timeout_s
            )
        except subprocess.TimeoutExpired as exc:
            raise FetchError(
                f"{method} {endpoint}: wrapper timed out after {self._timeout_s}s",
                endpoint=endpoint,
            ) from exc
        except OSError as exc:
            raise FetchError(
                f"{method} {endpoint}: wrapper not executable: {exc}",
                endpoint=endpoint,
            ) from exc
        if proc.returncode != 0:
            # stderr 尾部行 (wrapper 已脱敏); 绝不带 stdout 原文。
            tail = " | ".join((proc.stderr or "").strip().splitlines()[-3:])
            raise FetchError(
                f"{method} {endpoint}: wrapper rc={proc.returncode}: {tail}",
                endpoint=endpoint,
            )
        body = (proc.stdout or "").strip()
        if not body:
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise FetchError(
                f"{method} {endpoint}: response is not JSON: {exc}",
                endpoint=endpoint,
            ) from exc


class Session:
    """请求会话: runner 注入 + 全局限速 (每两次请求间 sleep, 含重试请求)。

    ``get(endpoint, attempts=N)``: 传输层重试 — 连续 N 次调用失败后抛
    FetchError (message 含尝试次数)。非传输层问题 (响应形态) 由调用方校验,
    不在本层重试。
    """

    def __init__(self, runner: Any, request_interval: float = DEFAULT_REQUEST_INTERVAL) -> None:
        self._runner = runner
        self._interval = float(request_interval)
        self._started = False  # 首个请求前不 sleep

    def get(self, endpoint: str, *, attempts: int = 1) -> Any:
        if attempts < 1:
            raise ValueError(f"attempts must be >= 1, got {attempts}")
        last: FetchError | None = None
        for _ in range(attempts):
            if self._started and self._interval > 0:
                time.sleep(self._interval)
            self._started = True
            try:
                return self._runner.call("GET", endpoint)
            except FetchError as exc:
                last = exc
        raise FetchError(
            f"GET {endpoint}: failed after {attempts} attempt(s): {last}",
            endpoint=endpoint,
        )


# ------------------------------------------------------------ repo spec 解析

def split_repo_spec(spec: str, default_owner: str = DEFAULT_OWNER) -> tuple[str, str]:
    """repo 配置项 → (owner, 裸仓名)。

    ``"Aria"`` → (default_owner, "Aria"); ``"acme/Widget"`` → ("acme",
    "Widget") (repo 名→owner/repo 映射参数化面)。空段 / 多于一段斜杠 /
    空串报 ValueError — 配置面 fail-closed, 不猜。
    """
    s = (spec or "").strip()
    parts = s.split("/")
    if len(parts) == 1:
        owner, name = default_owner, parts[0]
    elif len(parts) == 2:
        owner, name = parts
    else:
        raise ValueError(f"repo spec {spec!r}: expected 'Name' or 'owner/Name', got {len(parts)} segments")
    if not owner or not name:
        raise ValueError(f"repo spec {spec!r}: empty owner or repo name")
    return owner, name


# ------------------------------------------------------ issue-list 全分页游走

def _issue_list_endpoint(owner: str, repo: str, state: str, page_size: int) -> str:
    return f"/repos/{owner}/{repo}/issues?state={state}&type=issues&limit={page_size}"


def _is_pull_request(raw: dict[str, Any]) -> bool:
    """PR 混同客户端过滤 (与 ``type=issues`` 参数构成双保险, QA-C2)。"""
    if isinstance(raw.get("pull_request"), dict):
        return True
    url = str(raw.get("html_url") or raw.get("url") or "")
    return "/pulls/" in url


def list_repo_issues(
    session: Session,
    owner: str,
    repo: str,
    *,
    state: str = "open",
    page_size: int = DEFAULT_PAGE_SIZE,
    page_ceiling: int = DEFAULT_PAGE_CEILING,
) -> list[dict[str, Any]]:
    """单仓 issue-list 全分页游走, 返回 **PR 过滤后** 的原始 API 行 (未归一化)。

    终止 = 空页; 跨页按 ``number`` 去重; 整页已见 / 超页上限 / 行形态非法
    ⇒ FetchError (fail-closed, 绝不静默产出半份列表)。
    """
    base = _issue_list_endpoint(owner, repo, state, page_size)
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    for page in range(1, page_ceiling + 2):  # +1: 越过上限的探测页
        endpoint = base if page == 1 else f"{base}&page={page}"
        batch = session.get(endpoint)  # issue-list 页失败不重试 (模块契约第 3 条)
        if batch is None:
            # rc=0 + 空 stdout ≠ 空页 (空页是 JSON "[]") — 结构违规 fail-closed (A-2)。
            raise FetchError(
                f"{endpoint}: issue-list returned no content (rc=0, empty body) — "
                "an empty page must be a JSON '[]', not no-content",
                endpoint=endpoint,
            )
        if not isinstance(batch, list):
            raise FetchError(
                f"{endpoint}: issue-list expected a JSON array, got {type(batch).__name__}",
                endpoint=endpoint,
            )
        if not batch:
            return rows  # 空页 = 终止 (实测越界页返回空数组)
        if page > page_ceiling:
            raise FetchError(
                f"{owner}/{repo}: issue-list exceeded page ceiling {page_ceiling} "
                f"({page_ceiling * page_size} rows) — refusing a silently partial listing",
                endpoint=endpoint,
            )
        fresh: list[dict[str, Any]] = []
        for row in batch:
            if not isinstance(row, dict):
                raise FetchError(
                    f"{endpoint}: issue-list row is not an object: {type(row).__name__}",
                    endpoint=endpoint,
                )
            number = row.get("number")
            if isinstance(number, bool) or not isinstance(number, int):
                raise FetchError(
                    f"{endpoint}: issue-list row without integer 'number': {number!r}",
                    endpoint=endpoint,
                )
            if number not in seen:
                seen.add(number)
                fresh.append(row)
        if not fresh:
            raise FetchError(
                f"{endpoint}: entire page of already-seen issues (server ignoring paging?) "
                f"— refusing a silently partial listing",
                endpoint=endpoint,
            )
        rows.extend(r for r in fresh if not _is_pull_request(r))
    raise FetchError("unreachable: pagination loop always returns or raises")  # pragma: no cover


# ------------------------------------------------------------- comments 取回

def fetch_issue_comments(
    session: Session,
    owner: str,
    repo: str,
    number: int,
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
    attempts: int = DEFAULT_COMMENT_ATTEMPTS,
) -> list[dict[str, Any]]:
    """单条 issue 的 comments: **单次 GET 全量** (不做分页游走, Amendment 契约),
    返回归一化行 ``{id, created_at, updated_at, body}`` (保持端点顺序 = 升序
    最旧在前)。

    传输失败在 session 层重试 ``attempts`` 次后抛 FetchError; 响应形态非法也
    抛 FetchError (不重试)。**计数对账不在本函数** — 对账需要 issue 对象的
    ``comments`` 计数字段, 由 ``fetch_all`` 在两侧都到手后执行 (collected !=
    count ⇒ unknown 三态, fail-closed)。
    """
    endpoint = f"/repos/{owner}/{repo}/issues/{number}/comments?limit={page_size}"
    batch = session.get(endpoint, attempts=attempts)
    if batch is None:
        # 同判 issue-list (A-2): 零评论的端点形态是 "[]", 非 no-content。
        raise FetchError(
            f"{endpoint}: comments endpoint returned no content (rc=0, empty body) "
            "— zero comments must be a JSON '[]', not no-content",
            endpoint=endpoint,
        )
    if not isinstance(batch, list):
        raise FetchError(
            f"{endpoint}: comments endpoint expected a JSON array, got {type(batch).__name__}",
            endpoint=endpoint,
        )
    out: list[dict[str, Any]] = []
    for c in batch:
        if not isinstance(c, dict):
            raise FetchError(
                f"{endpoint}: comment row is not an object: {type(c).__name__}",
                endpoint=endpoint,
            )
        out.append(
            {
                "id": c.get("id"),
                "created_at": c.get("created_at"),
                "updated_at": c.get("updated_at"),
                "body": str(c.get("body") or ""),
            }
        )
    return out


# ----------------------------------------------------------------- 行归一化

def normalize_issue(raw: dict[str, Any], repo: str) -> dict[str, Any]:
    """原始 API issue 行 → tier_a 输入契约超集行 (comments/comments_error 由
    ``fetch_all`` 填充/覆盖)。

    - ``comments`` 计数字段缺席或非 int ⇒ ``comments_count=None`` +
      ``comments_error`` 预置 (对账结构上不可能 ⇒ 三态 unknown; 绝不当 0 —
      失败/缺席不冒充零评论)。
    - created/updated 取日期面 ``[:10]``; title/body None → ""; labels 只收
      dict 行的 str name (其余形态跳过, 缺席=无信号不是错误)。
    """
    number = raw.get("number")
    if isinstance(number, bool) or not isinstance(number, int):
        raise ValueError(f"{repo}: issue row without integer 'number': {number!r}")
    raw_labels = raw.get("labels")
    if raw_labels is None:
        raw_labels = []
    if not isinstance(raw_labels, list):
        raise ValueError(f"{repo}#{number}: 'labels' is not a list: {type(raw_labels).__name__}")
    labels = [l["name"] for l in raw_labels if isinstance(l, dict) and isinstance(l.get("name"), str)]

    raw_count = raw.get("comments")
    if isinstance(raw_count, bool) or not isinstance(raw_count, int):
        comments_count: int | None = None
        comments_error = (
            f"issue object 'comments' count field missing or invalid ({raw_count!r}) "
            f"— count reconciliation impossible"
        )
    else:
        comments_count = raw_count
        comments_error = None

    return {
        "repo": repo,
        "number": number,
        "title": str(raw.get("title") or ""),
        "labels": labels,
        "created": str(raw.get("created_at") or "")[:10],
        "updated": str(raw.get("updated_at") or "")[:10],
        "comments_count": comments_count,
        "body": str(raw.get("body") or ""),
        "comments": None,  # 三态占位; fetch_all 填充
        "comments_error": comments_error,
    }


# ------------------------------------------------------------------- 编排层

def fetch_all(
    repos: Sequence[str],
    *,
    runner: Any = None,
    default_owner: str = DEFAULT_OWNER,
    state: str = "open",
    page_size: int = DEFAULT_PAGE_SIZE,
    page_ceiling: int = DEFAULT_PAGE_CEILING,
    request_interval: float = DEFAULT_REQUEST_INTERVAL,
    comment_attempts: int = DEFAULT_COMMENT_ATTEMPTS,
) -> dict[str, Any]:
    """多仓编排: issue-list 全分页 + 逐 issue comments 单取 + 计数对账。

    每仓独立 try (一仓挂不连坐); 返回形态见模块 docstring。``runner`` 注入
    fake 即可全 mock (测试通道); 缺省 = ForgejoCliRunner (house wrapper)。
    """
    session = Session(runner if runner is not None else ForgejoCliRunner(), request_interval)
    result: dict[str, Any] = {"repos": [], "issues": []}
    seen: set[tuple[str, str]] = set()
    for spec in repos:
        owner, bare = split_repo_spec(spec, default_owner)
        if (owner, bare) in seen:
            continue  # (owner, repo) 二元组去重 (E-3): 别名双写 ("Aria" vs "10CG/Aria") 不重复抓取
        seen.add((owner, bare))
        entry: dict[str, Any] = {"repo": bare, "open_issues": 0, "error": None}
        try:
            raws = list_repo_issues(session, owner, bare, state=state,
                                    page_size=page_size, page_ceiling=page_ceiling)
        except FetchError as exc:
            entry["error"] = f"issue-list fetch failed: {exc}"
            result["repos"].append(entry)
            continue

        try:
            rows = [normalize_issue(r, bare) for r in raws]
        except ValueError as exc:
            # E-1: 归一化行形态非法 = 该仓数据不可信 ⇒ 该仓 error, 不连坐其他仓,
            # 也不静默丢行 (半份归一列表静默出厂 = 假绿)。
            entry["error"] = f"issue row normalization failed: {exc}"
            result["repos"].append(entry)
            continue
        entry["open_issues"] = len(rows)

        failed: list[int] = []
        for row in rows:
            if row["comments_count"] is None:
                # comments_error 已由 normalize_issue 预置 (计数字段缺席/非法)
                failed.append(row["number"])
                continue
            try:
                collected = fetch_issue_comments(session, owner, bare, row["number"],
                                                 page_size=page_size, attempts=comment_attempts)
            except FetchError as exc:
                row["comments"] = None  # unknown 三态 (传输失败连重试后)
                row["comments_error"] = f"comments fetch failed: {exc}"
                failed.append(row["number"])
                continue
            if len(collected) != row["comments_count"]:
                row["comments"] = None  # unknown 三态 (对账不匹配 — fail-closed)
                row["comments_error"] = (
                    f"count reconciliation mismatch: issue object says "
                    f"{row['comments_count']} comment(s), endpoint returned {len(collected)}"
                )
                failed.append(row["number"])
            else:
                row["comments"] = collected  # 值 / [] (零评论) 三态在此落定

        if failed:
            shown = ", ".join(f"#{n}" for n in failed[:20])
            extra = f" (+{len(failed) - 20} more)" if len(failed) > 20 else ""
            entry["error"] = (
                f"comments data unknown (None) for {len(failed)} issue(s): {shown}{extra}"
            )
        result["repos"].append(entry)
        result["issues"].extend(rows)
    return result

#!/usr/bin/env python3
"""issue-groomer 三面指纹引擎 (P1 MVP, 10CG/Aria#238, TASK-004; 裁定-9).

增量复用的判变基元: 三面指纹 (输入字段**封闭枚举 + 显式排除**, DEC-20261018-001
裁定-9 v3)。TASK-005 增量引擎以本模块产物作比较面 — **相等 ⇒ 可复用, 不等 ⇒
重评**。任何「取不到值」的态都落为结构可区分的降级标记 (``None`` /
``"unknown"``), 绝不冒充一个具体值 (失败不冒充零评论, 复刻 issue_scan
fetch_error 纪律); 「unknown 与上轮 unknown 比较是否判变」是下游增量引擎的
语义, 本模块只保证三态互不相同、不静默塌缩。

三面定义:

① **issue 面** (``issue_face`` / ``fingerprint_issues``): 每条 issue →
   ``{title_hash, body_hash, labels_hash, comments_latest_updated_at}``。
   - title/body: sha256 短哈希 (前 16 hex); None/缺席归一 ``""``。
   - labels_hash: **排序后** ``\\x1f`` (unit separator, 不见于 label 名) join
     再取短哈希 — **顺序不敏感** (label 增删才是信号, 打标顺序不是); 重复项
     不去重 (静默去重 = 磨掉真实差异)。
   - comments_latest_updated_at **三态** (对齐 fetch 层 comments 三态):
       值        = comments 非空 list 时 ``max(comments[].updated_at)`` —
                   评论流任何新增/编辑都推高 max (plugin#208: 评论是评估
                   关键输入); 端点返回升序最旧在前, 本层自取 max, 不依赖
                   上游顺序; ISO 同形字符串字典序 = 时间序。
       ``None``  = ``comments == []`` (零评论 — fetch 计数对账 0==0 通过的
                   空表, 与失败结构可区分)。
       ``"unknown"`` = ``comments is None`` 或 ``comments_error`` 非 None
                   (fetch 失败/对账不匹配/计数字段缺席 — Runtime Amendment
                   fail-closed 三态); 单条 comment 的 ``updated_at`` 缺席或
                   非 str 也归此态 (该条时间不可知 ⇒ 最新值无法诚实判定,
                   不猜、不静默跳过该条)。
   - **显式排除** (裁定-9): assignee / milestone / due_date — 本函数对 issue
     dict 的读取面封闭为 title/body/labels/comments/comments_error 五键,
     排除字段**结构上不被读取** ⇒ 其变化指纹不变 (不触发重评)。
   - 身份键 = ``f"{repo}#{number}"`` (与 tier_a.classify 同判: 缺席抛
     ValueError; 重复身份抛 ValueError — 拒绝静默覆盖)。

② **上下文面** (``context_fingerprint``, 仓库级非 per-issue) →
   ``{"openspec_changes_hash", "git_heads", "handoff_pointer", "taxonomy_hash"}``
   - openspec_changes_hash: ``openspec/changes/`` **全树内容级** hash (含
     proposal/tasks/design/specs delta — 在制 spec 任何实质修订必须触发
     重评): 递归收集 (相对路径, 文件字节) 对, **排序后**以长度前缀编码喂
     sha256 — 排序保证与目录遍历顺序无关 (跨运行稳定), 长度前缀保证
     (路径, 内容) 对的串接编码无歧义。**显式排除 ``openspec/archive/``**:
     它是 walk root 的兄弟子树, 结构上不在 changes/ 之下 (归档时 changes/
     目录消失已天然触发); 收集器仍带显式过滤钉住不变量 — walk root 若被
     未来重构上移到 openspec/, 过滤立即生效而非静默纳入 (历史 archive 修订
     不影响在制轨判断)。文件不可读 ⇒ OSError 上抛 (不产半份 hash)。
   - git_heads: 各仓 (主仓+卫星仓) ``git rev-parse HEAD`` — 覆盖无 OpenSpec
     的 Level 1 hotfix 代码变更。键 = 调用方传入的 root 串**原样** (稳定
     标识, 卫星仓可同名 basename 故不归一); 值 = 40-hex SHA; 失败 (非 git
     仓 / git 不可执行 / 超时) = ``None`` — 与任何 SHA 结构可区分, 下轮
     比较必不等 ⇒ 重评 (fail-closed 方向: 宁重评不误复用)。
     ``git_head_fn`` 可注入 (测试 mock, 零真仓依赖)。
   - handoff_pointer: 权威信号 = ``docs/handoff/latest.md`` 的 bare
     ``**Latest**:`` 指针行**目标文件名** (markdown link 目标, 剥 ``./``
     前缀; link 文本与目标不一致时取目标), **非 mtime** — 对齐本仓
     collector 以 pointer 为语义权威的既有教训 (mtime 在 rebase/checkout
     后被刚落地的历史文件顶掉)。行首锚定 ⇒ ``**Superseded (...)**`` /
     ``**Active (...)`` 等含 "Latest" 字样的行不匹配; 取首条匹配行; 无该
     行 / 文件缺席或不可读 ⇒ 降级 ``handoff_pointer=None``。
   - taxonomy_hash: 经 ``tier_a.resolve_taxonomy(project_root)`` 解析
     (裁定-1 覆盖语义: 项目级 ``.aria/labels.yaml`` 存在即**整体覆盖**内置
     层 — 项目文件变化自然反映进指纹) 后调 **``tier_a.taxonomy_hash``
     单点 SOT** — 本模块绝不自算 taxonomy 指纹 (canonical 形态保留声明
     顺序: 重排也算变, 保守触发重分类; 排除 ``_meta``)。项目文件非法 ⇒
     ValueError 上抛 (tier_a 契约, 不静默回落内置层)。``taxonomy=`` 可
     直接注入已解析 dict (调用方共享解析结果时免二次读盘)。

③ **provenance 面** (``provenance_face``, 裁定门 ③ 分层采集) →
   ``{harness, model_id}`` — harness = groom.py CLI 参数自报 (脚本层事实);
   model_id = ``None`` 表示脚本层未知, 由适配层写 assessment 时补全。
   ``combined_provenance_key`` 给出 canonical 拼接串 (复用门比对完整
   拼接串: provenance 变 ⇒ stale-assessment)。

比较基元: ``combined_issue_key(face)`` — issue 面四元组的 canonical JSON
(fixed field set + sort_keys) sha256 — 单个稳定串, 供增量引擎逐 issue 比较;
``None`` 序列化为 null, 与 ``"unknown"`` (字符串) 及任何时间戳值互不相等
(三态在 key 层同样互异)。

上下文面比较基元: ``context_key(ctx)`` — 上下文面四分量 dict 的 canonical
JSON (fixed field set + sort_keys) sha256 (DEC 裁定-9: 上下文一变 ⇒ Tier B
全量重评)。与 ``combined_issue_key`` 同构: 缺任一分量 ⇒ ValueError
(fail-closed, 不产半键); ``sort_keys`` 递归作用到 ``git_heads`` 内层 — 键序
不稳定 (dict 构造顺序) 不影响 key 值, 分量内容变 ⇒ key 必变。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable

from . import tier_a

__all__ = [
    "COMMENTS_UNKNOWN",
    "OPENSPEC_CHANGES_RELPATH",
    "HANDOFF_LATEST_RELPATH",
    "issue_face",
    "fingerprint_issues",
    "combined_issue_key",
    "provenance_face",
    "combined_provenance_key",
    "openspec_changes_hash",
    "handoff_pointer",
    "context_fingerprint",
    "context_key",
]

# comments 最新 updated_at 的第三态哨兵 (与 None-零评论 / ISO 值三态互斥)。
COMMENTS_UNKNOWN = "unknown"

# 指纹分量短哈希宽度 (sha256 hex 前 16 = 64 bit; 378 条量级判变用, 非抗碰撞)。
_SHORT_HASH_HEXLEN = 16

OPENSPEC_CHANGES_RELPATH = Path("openspec") / "changes"
HANDOFF_LATEST_RELPATH = Path("docs") / "handoff" / "latest.md"

_LATEST_LINE_PREFIX = "**Latest**:"  # 行首锚定; **Superseded/**Active 不匹配
_MD_LINK_TARGET_RE = re.compile(r"\]\(([^)]+)\)")
_MD_LINK_TEXT_RE = re.compile(r"\[([^\]]+)\]")

_ISSUE_FACE_FIELDS = ("title_hash", "body_hash", "labels_hash", "comments_latest_updated_at")
_CONTEXT_FACE_FIELDS = ("openspec_changes_hash", "git_heads", "handoff_pointer", "taxonomy_hash")
_PROVENANCE_FIELDS = ("harness", "model_id")

_GIT_TIMEOUT_S = 30.0
_LABELS_SEP = "\x1f"  # unit separator — 不见于 label 名, join 无歧义


def _short_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:_SHORT_HASH_HEXLEN]


# ------------------------------------------------------------------- ① issue 面

def _comments_latest_updated_at(issue: dict[str, Any]) -> str | None:
    """comments 三态收敛 (值 / None-零评论 / "unknown"); 见模块 docstring ①。"""
    if issue.get("comments_error") is not None:
        return COMMENTS_UNKNOWN  # fetch_error 面 — 不冒充零评论/具体值
    comments = issue.get("comments")
    if comments is None:
        return COMMENTS_UNKNOWN
    if not isinstance(comments, list):
        raise ValueError(
            f"{issue.get('repo')!r}#{issue.get('number')!r}: 'comments' must be a list or None, "
            f"got {type(comments).__name__}"
        )
    if not comments:
        return None  # 零评论 ([] 空表) — 与 unknown 结构可区分
    stamps: list[str] = []
    for c in comments:
        if not isinstance(c, dict):
            raise ValueError(
                f"{issue.get('repo')!r}#{issue.get('number')!r}: comment row is not an object: "
                f"{type(c).__name__}"
            )
        ts = c.get("updated_at")
        if not isinstance(ts, str):
            return COMMENTS_UNKNOWN  # 单条时间不可知 ⇒ 最新值无法诚实判定
        stamps.append(ts)
    return max(stamps)  # 自取 max, 不依赖上游顺序 (端点升序仅为实测事实)


def issue_face(issue: dict[str, Any]) -> dict[str, Any]:
    """单条 issue → issue 面四元组 (输入字段封闭枚举, 见模块 docstring ①)。

    读取面封闭为 title/body/labels/comments/comments_error 五键 —
    assignee/milestone/due_date 结构上不读 (显式排除集)。
    """
    if not isinstance(issue, dict):
        raise ValueError(f"issue must be a dict, got {type(issue).__name__}")
    labels = issue.get("labels")
    if labels is None:
        labels = []  # 缺席 = 无信号, 不是错误 (与 tier_a.classify 同判)
    if not isinstance(labels, list):
        raise ValueError(
            f"{issue.get('repo')!r}#{issue.get('number')!r}: 'labels' must be a list, "
            f"got {type(labels).__name__}"
        )
    return {
        "title_hash": _short_sha256(str(issue.get("title") or "")),
        "body_hash": _short_sha256(str(issue.get("body") or "")),
        "labels_hash": _short_sha256(_LABELS_SEP.join(sorted(str(l) for l in labels))),
        "comments_latest_updated_at": _comments_latest_updated_at(issue),
    }


def fingerprint_issues(issues: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """issue 列表 → ``{f"{repo}#{number}": issue_face}`` (TASK-001 fetch 输出形态)。

    身份缺席 / 重复身份 ⇒ ValueError (fail-closed, 拒绝静默覆盖 — 重复键的
    last-wins 会静默丢一行的指纹)。
    """
    faces: dict[str, dict[str, Any]] = {}
    for idx, issue in enumerate(issues):
        if not isinstance(issue, dict):
            raise ValueError(f"issue[{idx}] must be a dict, got {type(issue).__name__}")
        repo = issue.get("repo")
        number = issue.get("number")
        if repo is None or number is None:
            raise ValueError(f"issue[{idx}] missing identity field(s): repo={repo!r} number={number!r}")
        key = f"{repo}#{number}"
        if key in faces:
            raise ValueError(f"duplicate issue identity {key!r} at issue[{idx}] — refusing silent overwrite")
        faces[key] = issue_face(issue)
    return faces


def combined_issue_key(face: dict[str, Any]) -> str:
    """issue 面四元组 → 单个稳定比较串 (canonical JSON sha256)。

    fixed field set + sort_keys ⇒ 与 face dict 构造顺序无关; ``None`` 序列化
    null, 与 "unknown"/时间戳值互异 (三态在 key 层互异 — 任一态实现退化成
    另一态时 SC-1 ⑩ 类 fixture 必红)。
    """
    if not isinstance(face, dict):
        raise ValueError(f"issue face must be a dict, got {type(face).__name__}")
    missing = [f for f in _ISSUE_FACE_FIELDS if f not in face]
    if missing:
        raise ValueError(f"issue face missing field(s): {missing}")
    payload = {f: face[f] for f in _ISSUE_FACE_FIELDS}
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------- ③ provenance 面

def provenance_face(harness: str, model_id: str | None = None) -> dict[str, Any]:
    """provenance 面 (裁定门 ③ 分层采集): harness 脚本自报 (CLI 参数) +
    model_id 适配层补全 (None = 脚本层未知)。空串拒绝 (配置面 fail-closed)。"""
    if not isinstance(harness, str) or not harness.strip():
        raise ValueError(f"harness must be a non-empty string (CLI 自报), got {harness!r}")
    if model_id is not None and (not isinstance(model_id, str) or not model_id.strip()):
        raise ValueError(f"model_id must be None or a non-empty string (适配层补全), got {model_id!r}")
    return {"harness": harness, "model_id": model_id}


def combined_provenance_key(provenance: dict[str, Any]) -> str:
    """provenance 面 → canonical 拼接串 (复用门比对完整拼接串, 裁定门 ③)。"""
    if not isinstance(provenance, dict):
        raise ValueError(f"provenance must be a dict, got {type(provenance).__name__}")
    missing = [f for f in _PROVENANCE_FIELDS if f not in provenance]
    if missing:
        raise ValueError(f"provenance missing field(s): {missing}")
    payload = {f: provenance[f] for f in _PROVENANCE_FIELDS}
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------- ② 上下文面

def _archive_excluded(file_path: Path, project_root: Path) -> bool:
    """显式排除 ``openspec/archive/`` (按项目相对坐标判定, 与 walk root 解耦)。

    walk root 固定为 ``openspec/changes/`` 时本守卫结构上恒 False (archive/
    是兄弟子树) — 它钉住的是不变量: 若未来重构把 walk root 上移到
    ``openspec/``, 过滤立即生效而非静默纳入 archive 内容。
    """
    try:
        rel = file_path.relative_to(project_root)
    except ValueError:
        return False  # 不在 project_root 之下 (symlink 等) — 交由 walk root 边界管
    parts = rel.parts
    return len(parts) >= 2 and parts[0] == "openspec" and parts[1] == "archive"


def openspec_changes_hash(project_root: str | Path) -> str:
    """``openspec/changes/`` 全树内容级 hash (① 分量; 见模块 docstring ②)。

    (相对路径, 文件字节) 对收集后**全局排序**, 长度前缀编码喂 sha256 —
    排序 ⇒ 与遍历顺序无关 (跨运行稳定); 长度前缀 ⇒ 串接编码无歧义。
    changes/ 缺席或空树 = 空 feed 的 sha256 常量 (「零在制 spec」的稳定值)。
    文件不可读 ⇒ OSError 上抛 (不产半份 hash)。
    """
    root = Path(project_root)
    base = root / OPENSPEC_CHANGES_RELPATH
    entries: list[tuple[str, bytes]] = []
    if base.is_dir():
        for dirpath, _dirnames, filenames in os.walk(base):  # followlinks=False (防环)
            for name in filenames:
                path = Path(dirpath) / name
                if not path.is_file():
                    continue
                if _archive_excluded(path, root):
                    continue  # 显式排除守卫 (见 _archive_excluded docstring)
                entries.append((path.relative_to(base).as_posix(), path.read_bytes()))
    entries.sort()
    digest = hashlib.sha256()
    for rel, content in entries:
        digest.update(f"{len(rel)}:{rel}|{len(content)}:".encode("utf-8"))
        digest.update(content)
    return digest.hexdigest()


def _extract_pointer_target(rest: str) -> str:
    """指针行 ``**Latest**:`` 之后的内容 → 目标文件名。

    优先 markdown link 目标 ``](target)`` (display 文本≠目标时以目标为权威),
    次选 link 文本 ``[text]``, 兜底取整段剩余文本 — 三档都保持内容敏感:
    行内容任何实质变化 ⇒ 提取值变化 ⇒ 指纹变化 (降级方向 = 多判变, 不误稳)。
    """
    m = _MD_LINK_TARGET_RE.search(rest)
    if m:
        return m.group(1).removeprefix("./")
    m = _MD_LINK_TEXT_RE.search(rest)
    if m:
        return m.group(1).removeprefix("./")
    return rest.strip()


def handoff_pointer(project_root: str | Path) -> str | None:
    """handoff 权威信号 = latest.md bare ``**Latest**:`` 指针行目标文件名。

    行首锚定 (Superseded/Active 行含 "Latest" 字样不匹配); 首条匹配行生效;
    无该行 / 文件缺席或不可读 ⇒ ``None`` (降级标记, 非 mtime 回退 — mtime 在
    rebase/checkout 后被历史文件顶掉, 不做权威信号)。
    """
    path = Path(project_root) / HANDOFF_LATEST_RELPATH
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    for raw in text.splitlines():
        line = raw.lstrip()
        if line.startswith(_LATEST_LINE_PREFIX):
            return _extract_pointer_target(line[len(_LATEST_LINE_PREFIX):].strip())
    return None


def _default_git_head(root: str | Path) -> str | None:
    """``git -C <root> rev-parse HEAD`` (subprocess capture_output, stdout 不
    透传)。rc!=0 / git 不可执行 / 超时 ⇒ ``None`` (可区分降级: 与任何 SHA
    不等 ⇒ 下轮必判变 ⇒ 重评, fail-closed 方向)。"""
    try:
        proc = subprocess.run(  # noqa: S603 固定 git + 注入参数形态
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=_GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    sha = (proc.stdout or "").strip()
    return sha or None


def context_fingerprint(
    project_root: str | Path,
    git_roots: Iterable[str | Path] | str | Path | None = None,
    *,
    git_head_fn: Any = None,
    taxonomy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """上下文面四分量 (仓库级; 见模块 docstring ②)。

    - ``git_roots``: 参与指纹的仓清单 (主仓+卫星仓); None ⇒ ``[project_root]``;
      单个 str/Path 自动包成清单; 键 = 传入串原样。
    - ``git_head_fn``: ``fn(root) -> str|None``, 缺省 = ``_default_git_head``
      (真 subprocess); 测试注入 mock 即零真仓依赖。
    - ``taxonomy``: None ⇒ ``tier_a.resolve_taxonomy(project_root)`` (裁定-1
      覆盖语义); 也可注入已解析 dict。
    """
    root = Path(project_root)
    if git_head_fn is None:
        git_head_fn = _default_git_head
    if isinstance(git_roots, dict):
        # 防御: dict 会被 list() 迭代出键名当路径跑 (主 loop 亲验踩过), 静默产全 None-head
        raise TypeError("git_roots 须为路径可迭代 (list/tuple), 收到 dict — 键会被误当路径")
    if git_roots is None:
        roots: list[str | Path] = [project_root]
    elif isinstance(git_roots, (str, Path)):
        roots = [git_roots]
    else:
        roots = list(git_roots)
    git_heads = {str(gr): git_head_fn(gr) for gr in roots}
    if taxonomy is None:
        taxonomy = tier_a.resolve_taxonomy(root)
    return {
        "openspec_changes_hash": openspec_changes_hash(root),
        "git_heads": git_heads,
        "handoff_pointer": handoff_pointer(root),
        "taxonomy_hash": tier_a.taxonomy_hash(taxonomy),  # 单点 SOT, 不自算
    }


def context_key(ctx: dict[str, Any]) -> str:
    """上下文面四分量 → 单个稳定比较串 (canonical JSON sha256)。

    Tier B 复用门的上下文比对基元 (DEC 裁定-9: 上下文一变 ⇒ 全量重评):
    assessment entry 的 ``context_key`` 与本函数当前值相等才免
    ``context-changed``。fixed field set + sort_keys ⇒ 与 ``context_fingerprint``
    产物 dict 构造顺序无关; 缺任一分量 ⇒ ValueError (fail-closed — 不产
    半键, 调用方接线错误 loud 不静默)。与 ``combined_issue_key`` 同构
    (三键 canonical 化单点家族), 绝不自算分量 — 只 canonical 化已采集面。
    """
    if not isinstance(ctx, dict):
        raise ValueError(f"context fingerprint must be a dict, got {type(ctx).__name__}")
    missing = [f for f in _CONTEXT_FACE_FIELDS if f not in ctx]
    if missing:
        raise ValueError(f"context fingerprint missing field(s): {missing}")
    payload = {f: ctx[f] for f in _CONTEXT_FACE_FIELDS}
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

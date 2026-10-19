#!/usr/bin/env python3
"""issue-groomer CLI 主入口 (P1 MVP, 10CG/Aria#238, TASK-017) — 编排 + 报告组装。

单文件 main, **全程调 lib 层不复刻逻辑** (fetch / tier_a / fingerprint /
incremental / diffseg)。本文件的实现面只有三块:

  1. **作用域解析**: ``--repos`` 显式清单, 或回落 ``<project_root>/.aria/
     config.json`` 的 ``state_scanner.issue_scan`` 卫星仓形态 — 对齐本仓
     真实 config (无 ``repos`` 键, 卫星仓经 ``scan_submodules: true`` +
     ``.gitmodules`` 枚举 + 各仓 ``origin`` remote 推导 ``owner/repo``,
     state-scanner collectors/issue_scan 同款语义); 显式 ``repos`` 键
     (list[str]) 亦受支持 (向前兼容)。读不到 ⇒ ConfigError (exit 2,
     报错说明, 不猜)。**降级显式化 (B.3)**: 自动推导 (scan_submodules)
     的逐仓推导失败 ⇒ stderr 警告 + ``scope_degraded`` 记录 (落 state
     ``last_run.scope_degraded``, additive), 不静默缩作用域; 显式
     ``--repos``/``repos`` 键中的仓映射不上本地 git 路径 ⇒ ConfigError
     (用户意志 loud — 其 git HEAD 不入上下文指纹 = 上下文门 fail-OPEN)。
  2. **报告组装** (schema v1.1, ``scripts/groom-report.schema.json`` SOT):
     tier_a 信号面 → schema Signal 映射 (kind 连字符 → 枚举下划线);
     assessment 白名单投影 (assessments 文件面 → 报告面, 类型不符的面
     省略 — 机械层不转语义); **labels_payload 差集 + idempotent 在本层
     计算 (SC-5 实现面: add = suggested − existing, 无 remove 键)**;
     diff 段富化供值 (new/drift 的 title 取本轮 fetch 语料; closed 条目
     上轮 state 不存 title (TASK-005 契约) ⇒ 显式占位符不冒充标题;
     drift from/to = Tier A category 旧→新, 对照 state: from = prev
     ``tier_a.category``, 缺席 (new) = "(none)", to = 本轮分类)。
  3. **CLI 壳**: argparse / 退出码 (0 ok / 1 运行错误 / 2 配置错误) /
     stderr 进度 (--quiet 抑制) / stdout JSON (--out 写文件)。

裁定落点:
  - **裁定③ 第一层**: ``--harness`` (缺省 "unknown-cli") 落顶层 report
    ``harness`` 与 provenance 面 (fingerprint.provenance_face);
    ``--model-id`` 缺省 None (适配层补全)。
  - **裁定④ 两文件写回**: 只写 state (IncrementalEngine.save_state 原子
    temp+rename, 路径 = ``<root>/.aria/cache/groom-state.json`` 或
    ``--state-path``); 全程不触 ``.aria/groom-assessments.json`` — 经
    只读 reader (单次读盘缓存, gate 与投影共享同一快照, 中途变化不撕裂)。
  - **自校验 (fail-closed)**: 产出 report 先过 schema (``lib/
    schema_validate.mini_validate``, stdlib-only, 不依赖 jsonschema —
    校验实现住生产层, 与 tests/test_schema.py 同源单点 SOT; B.3 修正:
    不再直载 tests/ 或注入 pytest stub, 生产代码零测试环境耦合),
    校验失败 ⇒ 不写 state 不出厂, exit 1。

编排流程: fetch_all → **repo error 收口 (A-1: 任一仓 fetch 失败 ⇒
RuntimeError exit 1, 不组装报告不写 state — state 保持上轮, 重跑幂等)** →
resolve_taxonomy → classify (now 注入; 逐仓 try, 行级 ValueError ⇒ 该仓
error + 同款收口, E-1) → fingerprint_issues → context_fingerprint
(git_roots = project_root + 卫星仓真实路径, .gitmodules 目录名↔origin
裸仓名映射; 降级分量经 ``degraded`` 告知, A-3) → load_state →
plan_tier_a → gate_tier_b (读 assessments 若在; provenance 门 + 上下文门
— 上下文门收 fingerprint.context_key(context), DEC 裁定-9) → build_diff_segment →
组装 report → 自校验 → **报告写盘 (--out 时, 先于 state — D-1: 报告面
先落, state 后落; 报告写失败 ⇒ exit 1 且 state 未写)** →
build_next_state + save_state → 输出 (stdout)。

assessed_keys 面: 本层恒 None (机械层无 Tier B 重评信息; drift 候选 =
new ∪ reclassify)。适配层 (TASK-010) 的注入面是后续 additive 演进, 不
在本版私造。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple

if __package__ in (None, ""):  # 直接脚本执行: scripts/ 自动入 path (双保险)
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import diffseg, fetch, fingerprint, incremental, schema_validate, tier_a  # noqa: E402

__all__ = [
    "ConfigError",
    "SchemaError",
    "ScopeResolution",
    "parse_args",
    "resolve_repos",
    "resolve_git_roots",
    "run_pipeline",
    "main",
]

REPORT_SCHEMA_PATH = Path(__file__).resolve().parent / "groom-report.schema.json"
SNAPSHOT_SCHEMA_VERSION = "1.1"
DEFAULT_HARNESS = "unknown-cli"
DEFAULT_PROJECT_ROOT = "."

# closed 条目 DiffRef.title 占位: 上轮 state 不存 title (TASK-005 契约),
# 本轮 fetch 无该行 — 机械层不造标题, 显式占位 (schema 仅要求 string)。
CLOSED_TITLE_PLACEHOLDER = "(closed; not in current scan)"
# drift from 占位: 候选池含 new (上轮不在册, 无旧 category 档)。
DRIFT_FROM_NONE = "(none)"

_GIT_TIMEOUT_S = 15.0
_OWNER_REPO_RE = re.compile(r"^[^/\s]+/[^/\s]+$")
_SUBMODULE_PATH_RE = re.compile(r"^submodule\..+\.path\s+(.+)$")

# tier_a 信号 kind (连字符) → schema SignalSource 枚举 (下划线)。封闭映射:
# tier_a 新增 kind 时此处必须同步, 否则 classify 产物在组装层 fail-closed。
_KIND_TO_SCHEMA_SOURCE = {
    "title-prefix": "title_prefix",
    "label": "label",
    "staleness": "staleness",
    "activity": "activity",
}


class ConfigError(Exception):
    """作用域/配置面错误 (exit 2): --repos 缺省回落失败等, 报错说明不猜。"""


class SchemaError(Exception):
    """报告自校验失败 (exit 1): 不写 state、不出厂非法报告。"""


def _noop(_msg: str) -> None:  # 进程内调用 (测试) 的静默 log
    return None


# ------------------------------------------------------------------ 时间面

def _parse_now(text: str) -> datetime:
    """ISO 8601 → aware-UTC datetime (naive 视作 UTC; ValueError 上抛)。"""
    raw = text.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------ git 面
# 语义对齐 state-scanner ``scripts/collectors/issue_scan.py`` 的
# ``_extract_owner_repo`` / ``_enumerate_submodule_paths`` (跨 skill 不
# import, 插件自包含纪律 — 同判于 tier_a 对 detailed_tasks 的物理副本)。

def _git(args: list[str], cwd: Path) -> str | None:
    """``git -C cwd args`` → stdout (strip); 失败 (rc!=0 / git 缺席 / 超时)
    ⇒ None。subprocess capture_output, stdout 不透传 chat-visible 面。"""
    try:
        proc = subprocess.run(  # noqa: S603 固定 git + 注入参数形态
            ["git", *args],
            cwd=str(cwd), capture_output=True, text=True, timeout=_GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return (proc.stdout or "").strip() or None


def _git_raw(args: list[str], cwd: Path) -> tuple[int, str, str]:
    """``git -C cwd args`` → (rc, stdout, stderr 尾部行) — 需要区分「命令
    失败」与「成功但空输出」的调用面专用 (B-1: .gitmodules 枚举);
    git 缺席/超时 ⇒ (127, "", "<原因>") (结构上可视作失败, 不冒充成功)。"""
    try:
        proc = subprocess.run(  # noqa: S603 固定 git + 注入参数形态
            ["git", *args],
            cwd=str(cwd), capture_output=True, text=True, timeout=_GIT_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return 124, "", f"git timed out after {_GIT_TIMEOUT_S}s"
    except OSError as exc:
        return 127, "", f"git not executable: {exc}"
    tail = " | ".join((proc.stderr or "").strip().splitlines()[-2:])
    return proc.returncode, (proc.stdout or ""), tail


def _extract_owner_repo(remote_url: str) -> str | None:
    """remote URL → ``owner/repo``; 剥协议 / user@ / host(:port) / .git /
    query / fragment; 非「恰两段」形态 ⇒ None (不猜)。

    host 段吸收可选 ``:port`` (B.3: ``scheme://host:port/o/r.git`` —
    端口被当 host 路径段 ⇒ 三段形态 ⇒ None 的假阴性); scp 形态
    ``host:path`` 不带端口, 端口组回退不匹配即退回 ``[:/]`` 剥 host。"""
    s = (remote_url or "").strip()
    if not s:
        return None
    s = re.sub(r"^[a-z][a-z0-9+.-]*://", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^[^@/]+@", "", s)
    s = re.sub(r"^[^:/]+(?::\d+)?[:/]", "", s)
    s = re.sub(r"\.git(?:[?#/].*)?$", "", s)
    s = re.sub(r"\.git$", "", s)
    s = s.rstrip("/")
    return s if _OWNER_REPO_RE.match(s) else None


def _origin_owner_repo(root: Path) -> str | None:
    url = _git(["remote", "get-url", "origin"], root)
    return _extract_owner_repo(url) if url else None


def _submodule_paths(project_root: Path) -> list[str]:
    """.gitmodules 的 submodule path 清单 (B-1 三态收口):

    - ``.gitmodules`` 文件缺席 ⇒ [] (结构性缺席 = 合法空仓集, 非错误);
    - git/config 失败 (rc 非文档化的 0/1 — 如文件损坏 rc=128, git 缺席)
      ⇒ ConfigError (fail-closed: 枚举面损坏时静默空清单 = 静默缩作用域);
    - rc=0/1 (1 = ``--get-regexp`` 文档化「无匹配」) ⇒ 解析 stdout
      (空输出 = 无 submodule 条目, 合法空)。
    """
    root = Path(project_root)
    if not (root / ".gitmodules").exists():
        return []  # 结构性缺席 (非 git 仓 / 未用 submodule) — 合法空
    rc, out, err_tail = _git_raw(
        ["config", "-f", ".gitmodules", "--get-regexp", r"^submodule\..+\.path$"],
        root,
    )
    if rc not in (0, 1):  # 1 = --get-regexp 无匹配 (含空 .gitmodules), 文档化
        raise ConfigError(
            f"git config -f .gitmodules 枚举失败 (rc={rc}): {err_tail or 'no stderr'} "
            "— 无法枚举 submodule 清单, 拒绝静默按空作用域继续 (补救: 修复 "
            ".gitmodules / git 环境, 或 --repos 显式指定)"
        )
    paths: list[str] = []
    for line in out.splitlines():
        m = _SUBMODULE_PATH_RE.match(line.strip())
        if m and m.group(1).strip():
            paths.append(m.group(1).strip())
    return paths


# ------------------------------------------------------------ 作用域解析

class ScopeResolution(NamedTuple):
    """resolve_repos 产物: spec 清单 + 降级告知面 + 推导模式。

    - ``specs``: 扫描 spec 清单 (裸名或 ``owner/name``, fetch.split_repo_spec
      消费; 保序去重)。
    - ``scope_degraded``: 作用域降级项 (B-1): ``"main"`` (主仓 origin 推导
      失败) / ``"submodule:<path>"`` (子模块 origin 推导失败或目录未检出) /
      ``"repo:<bare>"`` (resolve_git_roots 非严格模式下裸名映射不上本地
      路径)。落 state ``last_run.scope_degraded`` (additive) — 降级必须
      显式可见, 不静默缩作用域。
    - ``derived``: True = scan_submodules 自动推导 (映射失败 ⇒ 降级告知);
      False = 显式声明 (--repos / config repos 键 — 映射失败由
      resolve_git_roots 以 ConfigError 收口, 用户意志 loud)。
    """

    specs: list[str]
    scope_degraded: list[str]
    derived: bool


def resolve_repos(
    explicit: list[str] | None, project_root: Path, *, log: Any = None
) -> ScopeResolution:
    """扫描仓清单: ``--repos`` 优先; 否则回落 config (见模块 docstring 第 1 块)。

    返回 ScopeResolution (specs + scope_degraded + derived); 任何回落失败
    ⇒ ConfigError (exit 2, 消息说明补救路径)。自动推导分支的逐仓失败 ⇒
    ``log`` 警告 + scope_degraded (B-1), 全员失败才 ConfigError。
    """
    if log is None:
        log = _noop
    if explicit:
        return ScopeResolution(list(dict.fromkeys(explicit)), [], False)
    root = Path(project_root)
    cfg_path = root / ".aria" / "config.json"
    if not cfg_path.is_file():
        raise ConfigError(
            f"未指定 --repos 且 {cfg_path} 不存在 — 无法确定扫描仓清单。"
            "补救: 传 --repos NAME [owner/NAME ...], 或提供 .aria/config.json "
            "的 state_scanner.issue_scan 配置 (repos 键或 scan_submodules)"
        )
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"读取 {cfg_path} 失败: {exc}") from exc
    if not isinstance(cfg, dict):
        raise ConfigError(f"{cfg_path} 根必须是 JSON object")
    scan = (cfg.get("state_scanner") or {}).get("issue_scan")
    if not isinstance(scan, dict):
        raise ConfigError(
            f"{cfg_path} 缺少 state_scanner.issue_scan 配置节 — 无法确定扫描"
            "仓清单 (补救: --repos 或补全该配置节)"
        )
    repos = scan.get("repos")
    if repos is not None:
        if (
            not isinstance(repos, list)
            or not repos
            or not all(isinstance(r, str) and r.strip() for r in repos)
        ):
            raise ConfigError(
                "state_scanner.issue_scan.repos 须为非空字符串列表 "
                f"(裸名或 owner/name), got {repos!r}"
            )
        return ScopeResolution(list(dict.fromkeys(repos)), [], False)
    if scan.get("scan_submodules"):
        # state-scanner 同款: 主仓 + 各 submodule 的 origin → owner/name。
        # B-1: 逐仓推导失败 ⇒ 警告 + scope_degraded, 不静默缩作用域;
        # .gitmodules 枚举失败 (git/config 面) ⇒ _submodule_paths ConfigError。
        specs: list[str] = []
        degraded: list[str] = []
        main = _origin_owner_repo(root)
        if main:
            specs.append(main)
        else:
            log("groom: 警告: 主仓 origin remote 无法推导 owner/repo — "
                "主仓移出本轮扫描 (scope degraded)")
            degraded.append("main")
        for sub in _submodule_paths(root):
            sub_dir = root / sub
            if not sub_dir.is_dir():
                log(f"groom: 警告: submodule '{sub}' 已声明但目录未检出 "
                    f"(未 init?) — 移出本轮扫描 (scope degraded)")
                degraded.append(f"submodule:{sub}")
                continue
            owner_repo = _origin_owner_repo(sub_dir)
            if owner_repo:
                specs.append(owner_repo)
            else:
                log(f"groom: 警告: submodule '{sub}' origin 推导失败 "
                    "(git remote get-url origin 失败或 URL 形态非法) — "
                    "移出本轮扫描 (scope degraded)")
                degraded.append(f"submodule:{sub}")
        if specs:
            return ScopeResolution(specs, degraded, True)
        raise ConfigError(
            "scan_submodules=true 但主仓/子模块的 origin remote 均无法推导 "
            "owner/repo (git remote get-url origin 失败或 URL 形态非法) — "
            "补救: --repos 显式指定"
        )
    raise ConfigError(
        "state_scanner.issue_scan 无 repos 键且 scan_submodules 未启用 — "
        "无法确定扫描仓清单 (补救: --repos 或启用 scan_submodules)"
    )


def resolve_git_roots(
    project_root: Path,
    repo_specs: list[str],
    *,
    strict: bool = True,
    log: Any = None,
    scope_degraded: list[str] | None = None,
) -> list[str]:
    """context_fingerprint 的 git_roots: project_root + 卫星仓**真实路径**
    (.gitmodules 目录 ↔ origin 裸仓名映射 — 卫星仓目录名可与裸仓名不同,
    如目录 ``aria`` ↔ 仓 ``aria-plugin``)。键 = 路径串原样 (fingerprint
    契约: 稳定标识, 不归一)。

    B-2 收口 — 映射不上的选中仓 (如 ``--repos`` 指定外仓) 不再静默只剩
    主仓 root (git_heads 覆盖面静默变窄 = 上下文门 fail-OPEN):

    - ``strict=True`` (显式声明: --repos / config repos 键): 任一选中仓
      的裸名映射不上主仓 origin 或任一 submodule origin ⇒ ConfigError
      (exit 2 — 用户显式点名的仓, 其 git HEAD 必须入指纹, 映射不上是
      loud 配置错误)。
    - ``strict=False`` (scan_submodules 自动推导): 映射不上 ⇒ ``log``
      警告 + 计入 ``scope_degraded`` (``repo:<bare>``), 继续跑 — 自动
      推导面降级是告知面不是硬错误 (B-1 同判)。
    """
    root = Path(project_root)
    if log is None:
        log = _noop
    if scope_degraded is None:
        scope_degraded = []
    roots = [str(root)]
    wanted: list[str] = []
    for spec in repo_specs:
        try:
            _owner, bare = fetch.split_repo_spec(spec)
        except ValueError:
            continue  # 同 spec 由 fetch 层稍后 fail-closed, 此处不抢报错
        if bare not in wanted:
            wanted.append(bare)
    covered: set[str] = set()
    main = _origin_owner_repo(root)
    if main is not None:
        covered.add(main.split("/", 1)[1])
    for sub in _submodule_paths(root):
        sub_dir = root / sub
        if not sub_dir.is_dir():
            continue
        owner_repo = _origin_owner_repo(sub_dir)
        if owner_repo is None:
            continue  # origin 推导失败: 自动模式下已由 resolve_repos 降级告知
        bare = owner_repo.split("/", 1)[1]
        if bare in wanted:
            roots.append(str(sub_dir))
            covered.add(bare)
    uncovered = [b for b in wanted if b not in covered]
    if uncovered:
        names = ", ".join(sorted(uncovered))
        if strict:
            raise ConfigError(
                f"显式指定的仓映射不到本项目的 git 路径 (主仓 origin / "
                f".gitmodules): {names} — 这些仓的 git HEAD 无法纳入上下文"
                "指纹 (上下文门将 fail-OPEN)。补救: 确认仓已作为 submodule "
                "检出且 origin remote 可推导, 或修正 --repos 清单"
            )
        log(f"groom: 警告: 仓 {names} 无法映射到本地路径 — 其 git HEAD 不在"
            " 上下文指纹内 (scope degraded)")
        scope_degraded.extend(f"repo:{b}" for b in sorted(uncovered))
    return roots


# ------------------------------------------------------ 信号/评估面映射

def _schema_signals(classified_rec: dict[str, Any], issue: dict[str, Any]) -> list[dict[str, Any]]:
    """tier_a 信号行 → schema Signal ``{source, rule, detail}``。

    未知 kind ⇒ ValueError (SignalSource 封闭枚举, additive 演进须先扩
    schema 再同步 ``_KIND_TO_SCHEMA_SOURCE``)。detail 形态稳定 (机械拼装,
    不含语义猜测), 供人读溯源。"""
    out: list[dict[str, Any]] = []
    for sig in classified_rec.get("signals") or []:
        kind = sig.get("kind")
        source = _KIND_TO_SCHEMA_SOURCE.get(kind)
        if source is None:
            raise ValueError(
                f"未知 Tier A 信号 kind {kind!r} — schema SignalSource 封闭枚举 "
                "(additive 时须同步 groom._KIND_TO_SCHEMA_SOURCE)"
            )
        value = sig.get("value")
        if kind == "title-prefix":
            rule = f"prefix:{sig.get('category')}"
            detail = f"title 前缀 '{value}' 命中前缀映射表分类键 {sig.get('category')}"
        elif kind == "label":
            rule = f"label:{value}"
            detail = f"tracker label '{value}' 命中分类键 {sig.get('category')}"
        elif kind == "staleness":
            rule = f"staleness:{value}"
            detail = f"最近更新 {issue.get('updated') or '(缺席)'}, staleness 档 '{value}'"
        else:  # activity (映射表保证 kind 只剩此项)
            rule = f"activity:{value}"
            detail = f"comments_count={issue.get('comments_count')!r}, 活跃度档 '{value}'"
        out.append({"source": source, "rule": rule, "detail": detail})
    return out


def _confidence_sources(schema_signals: list[dict[str, Any]]) -> list[str]:
    """Signal.source 保序去重 (confidence = 枚举命中信号集, 裁定-7)。"""
    out: list[str] = []
    for s in schema_signals:
        if s["source"] not in out:
            out.append(s["source"])
    return out


def _project_assessment(entry: Any) -> dict[str, Any] | None:
    """assessments 文件条目 → 报告 assessment 面 (白名单类型投影)。

    - provenance {harness, model_id} 必须**双双非空 str** 才可进报告
      (schema minLength 1; assessments 面 model_id=None 经复用门可匹配
      None==None, 但 null 形态报告面非法 ⇒ 该条整体降级 null — 报告
      schema 纪律, 与复用门独立两层)。
    - 语义可选面 (verdict_priorities/suspected_fixed/owner_decisions)
      类型不符 (如 assessments 面的 list-of-dict verdict_priorities vs
      报告面 string) ⇒ 该面省略 (报告面可选键), **不做语义转换** —
      机械层转语义 = 造数据; 适配层渲染时自取 assessments 原文件。
    - 未知键 (契约 additive-only) 一律忽略。
    """
    if not isinstance(entry, dict):
        return None
    prov = entry.get("provenance")
    if not isinstance(prov, dict):
        return None
    harness = prov.get("harness")
    model_id = prov.get("model_id")
    if not isinstance(harness, str) or not harness.strip():
        return None
    if not isinstance(model_id, str) or not model_id.strip():
        return None
    out: dict[str, Any] = {"provenance": {"harness": harness, "model_id": model_id}}
    vp = entry.get("verdict_priorities")
    if isinstance(vp, str):
        out["verdict_priorities"] = vp
    sf = entry.get("suspected_fixed")
    if isinstance(sf, bool):
        out["suspected_fixed"] = sf
    od = entry.get("owner_decisions")
    if isinstance(od, list) and all(isinstance(x, str) for x in od):
        out["owner_decisions"] = list(od)
    return out


# ------------------------------------------------------------- 报告组装

def _assemble_report(
    *,
    harness: str,
    now_dt: datetime,
    fetched: dict[str, Any],
    issues: list[dict[str, Any]],
    classified: list[dict[str, Any]],
    taxonomy: dict[str, Any],
    state: dict[str, Any],
    gate: dict[str, Any],
    seg: dict[str, Any],
    assessments_doc: dict[str, Any] | None,
) -> dict[str, Any]:
    """全量组装 schema v1.1 报告 (纯映射, 零 IO / 零 lib 逻辑复刻)。"""
    issue_by_key = {f"{i['repo']}#{i['number']}": i for i in issues}
    classified_by_key = {f"{r['repo']}#{r['number']}": r for r in classified}
    reusable = set(gate.get("reusable") or [])
    entries_doc = (assessments_doc or {}).get("assessments") or {}
    categories: dict[str, str] = taxonomy["categories"]

    issue_entries: list[dict[str, Any]] = []
    by_category: dict[str, int] = {}
    by_repo: dict[str, int] = {}
    assessed_n = 0
    for key in sorted(classified_by_key, key=diffseg.split_issue_key):
        rec = classified_by_key[key]
        issue = issue_by_key[key]
        category = rec["category"]
        signals = _schema_signals(rec, issue)
        assessment = (
            _project_assessment(entries_doc.get(key)) if key in reusable else None
        )
        if assessment is not None:
            assessed_n += 1

        existing = list(issue.get("labels") or [])
        # suggested: 分类键 → canonical label (labels.yaml SOT);
        # unknown/conflict 不在 categories ⇒ 无建议 (不猜)。
        suggested = [categories[category]] if category in categories else []
        existing_set = set(existing)
        add = [l for l in suggested if l not in existing_set]  # SC-5 差集
        labels_payload = {
            "existing": existing,
            "suggested": suggested,
            "apply_payload": {
                "repo": rec["repo"],
                "number": rec["number"],
                "add": add,
                "idempotent": True,  # schema const — 差集 ⇒ 重复 apply no-op
            },
        }
        issue_entries.append(
            {
                "repo": rec["repo"],
                "number": rec["number"],
                "title": issue.get("title") or "",
                "labels": existing,
                "category": category,
                "signals": signals,
                "confidence_source": _confidence_sources(signals),
                "assessment": assessment,
                "labels_payload": labels_payload,
            }
        )
        by_category[category] = by_category.get(category, 0) + 1
        by_repo[rec["repo"]] = by_repo.get(rec["repo"], 0) + 1

    # ---- diff 段富化 (title / category from-to 供值是本层职责) ----
    titles = {f"{i['repo']}#{i['number']}": i.get("title") or "" for i in issues}
    prev_issues = state.get("issues") or {}
    new_refs = [diffseg.build_diff_ref(k, titles[k]) for k in seg["new"]]
    closed_refs = [
        # closed 条目上轮 state 不存 title ⇒ 显式占位 (不冒充标题)
        diffseg.build_diff_ref(k, CLOSED_TITLE_PLACEHOLDER)
        for k in seg["closed"]
    ]
    drift_entries = []
    for k in seg["drift"]:
        prev_cat = None
        prev_entry = prev_issues.get(k)
        if isinstance(prev_entry, dict):
            prev_tier = prev_entry.get("tier_a")
            if isinstance(prev_tier, dict) and isinstance(prev_tier.get("category"), str):
                prev_cat = prev_tier["category"]
        drift_entries.append(
            diffseg.build_drift_entry(
                k, titles[k], prev_cat if prev_cat is not None else DRIFT_FROM_NONE,
                classified_by_key[k]["category"],
            )
        )
    diff_section = {
        "new": new_refs,
        "closed": closed_refs,
        "drift": drift_entries,
        "baseline_run": seg["baseline_run"],
        "drift_truncated": seg["drift_truncated"],
        "drift_total": seg["drift_total"],
    }

    repos_entries: list[dict[str, Any]] = []
    for e in fetched.get("repos") or []:
        out = {"repo": e["repo"], "open_issues": e["open_issues"]}
        if e.get("error"):
            out["error"] = e["error"]  # 失败显式可见 (schema: 成功时省略)
        repos_entries.append(out)

    return {
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "generated_at": _iso_z(now_dt),
        "harness": harness,
        "repos": repos_entries,
        "issues": issue_entries,
        "diff": diff_section,
        "summary": {
            "total_issues": len(issues),
            "by_category": by_category,
            "by_repo": by_repo,
            "assessed": assessed_n,
            "diff_counts": {
                "new": len(seg["new"]),
                "closed": len(seg["closed"]),
                "drift": len(seg["drift"]),
            },
        },
    }


# ------------------------------------------------------------- 自校验

def _mini_validate() -> Any:
    """出厂自校验入口 — 取 ``lib.schema_validate.mini_validate``。

    依赖方向 (B.3 修正): 校验实现住生产层 ``scripts/lib/schema_validate.py``
    (stdlib-only), 测试断言面 (``tests/test_schema.py``) 与本自校验同源
    import 单点 SOT — 生产代码不直载 tests/ 亦不依赖 pytest 环境。"""
    return schema_validate.mini_validate


def _self_check(report: dict[str, Any]) -> None:
    """产出 report 过 schema (mini-validate; 不依赖 jsonschema)。

    失败 ⇒ SchemaError — 不写 state、不出厂非法报告 (fail-closed)。"""
    schema = json.loads(REPORT_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = _mini_validate()(report, schema)
    if errors:
        raise SchemaError(
            "groom report 自校验失败 (schema v"
            f"{SNAPSHOT_SCHEMA_VERSION}):\n  " + "\n  ".join(errors)
        )


# ------------------------------------------------------------------ 编排

def _require_no_repo_errors(fetched: dict[str, Any], stage: str) -> None:
    """A-1 收口: 任一仓 ``repos[].error`` 非空 ⇒ RuntimeError (main 归一为
    exit 1), 消息逐仓点名 — 不组装报告、不写 state (state 保持上轮,
    重跑幂等)。半份语料 + closed 谎报 (失败仓条目全被视作已关闭) 结构上
    不可出厂。"""
    failed = [e for e in fetched.get("repos") or [] if e.get("error")]
    if failed:
        detail = "; ".join(f"{e['repo']}: {e['error']}" for e in failed)
        raise RuntimeError(
            f"{stage}: {len(failed)} repo(s) failed — 拒绝组装报告/写 state "
            f"(state 保持上轮, 重跑幂等): {detail}"
        )


def _report_payload(report: dict[str, Any]) -> str:
    """report → 出厂 JSON 文本 (唯一序列化点: --out 文件与 stdout 同形)。"""
    return json.dumps(report, ensure_ascii=False, indent=2) + "\n"


def run_pipeline(
    args: argparse.Namespace,
    *,
    runner: Any = None,
    request_interval: float = fetch.DEFAULT_REQUEST_INTERVAL,
    log: Any = None,
    report_out: str | Path | None = None,
) -> dict[str, Any]:
    """全编排 (可进程内调用, 测试注入 fake runner / request_interval=0)。

    返回组装后的 report dict (自校验已过, state 已写)。CLI 壳 (main) 只做
    参数解析 / 退出码 / 输出面。

    - A-1: fetch 后任一仓 error ⇒ RuntimeError (exit 1), 不写 state。
    - E-1: classify 逐仓 try, 行级 ValueError ⇒ 该仓 error + 同款收口。
    - D-1: ``report_out`` (``--out`` 落点) 的报告写盘发生在 save_state
      **之前** — 报告写失败 ⇒ OSError 上抛 (exit 1) 且 state 未写。
      ``report_out=None`` 时回落 ``args.out`` (进程内直调单参数面)。
    """
    if log is None:
        log = _noop
    if report_out is None:
        report_out = getattr(args, "out", None)  # 进程内直调回落 CLI 参数面
    project_root = Path(args.project_root)
    now_dt = _parse_now(args.now) if args.now else datetime.now(timezone.utc)

    scope = resolve_repos(args.repos, project_root, log=log)
    repos_specs = scope.specs
    active_runner = runner if runner is not None else fetch.ForgejoCliRunner(
        bin_path=args.runner_bin
    )
    fetched = fetch.fetch_all(
        repos_specs, runner=active_runner, request_interval=request_interval
    )
    _require_no_repo_errors(fetched, "fetch")  # A-1: 半份语料不出厂
    issues = fetched["issues"]
    log(f"groom: repos={len(fetched['repos'])} issues={len(issues)}")

    taxonomy = tier_a.resolve_taxonomy(project_root)
    # E-1: classify 逐仓 try — 行级 ValueError (输入形态非法) ⇒ 该仓 error
    # (其余仓不连坐), 随后同款 A-1 收口。逐仓调用与整批调用输出同序同值
    # (信号计算逐条独立; issues 本身按仓分块)。
    classified: list[dict[str, Any]] = []
    for entry in fetched["repos"]:
        repo_issues = [i for i in issues if i["repo"] == entry["repo"]]
        try:
            classified.extend(
                tier_a.classify(repo_issues, taxonomy, now=now_dt)
            )
        except ValueError as exc:
            entry["error"] = f"tier_a classify failed: {exc}"
    _require_no_repo_errors(fetched, "classify")
    faces = fingerprint.fingerprint_issues(issues)
    git_roots = resolve_git_roots(
        project_root, repos_specs, strict=not scope.derived,
        log=log, scope_degraded=scope.scope_degraded,  # B-2 接线
    )
    context = fingerprint.context_fingerprint(
        project_root,
        git_roots=git_roots,
        taxonomy=taxonomy,  # 共享解析结果, 免二次读盘
    )
    ctx_degraded = list(context.get("degraded") or [])  # A-3 告知面
    if ctx_degraded:
        log(f"groom: 上下文指纹降级分量: {', '.join(ctx_degraded)} "
            "(git_heads=None / handoff_pointer=None — 下轮比较必判变, "
            "fail-closed 方向; 降级已记入 state last_run.degraded)")
    provenance = fingerprint.provenance_face(args.harness, args.model_id)

    state_path = (
        Path(args.state_path)
        if args.state_path
        else project_root / incremental.DEFAULT_STATE_RELPATH
    )
    assessments_cache: dict[str, Any] = {}

    def _assessments_reader() -> dict[str, Any] | None:
        # 只读 + 单次读盘缓存: gate 与报告投影共享同一快照 (中途文件变化
        # 不撕裂); 引擎持有 reader 而非路径 (裁定④ 无 assessment 写面)。
        if "doc" not in assessments_cache:
            assessments_cache["doc"] = incremental.default_assessments_reader(
                project_root
            )()
        return assessments_cache["doc"]

    engine = incremental.IncrementalEngine(
        state_path, assessments_reader=_assessments_reader, now_fn=lambda: now_dt
    )

    state, _baseline = engine.load_state()
    taxonomy_hash = context["taxonomy_hash"]
    plan = engine.plan_tier_a(state, faces, classified, taxonomy_hash)
    log(
        "groom: tier_a baseline={baseline} new={new} reused={reused} "
        "reclassify={reclassify} closed={closed}".format(
            baseline=plan["baseline_run"], new=len(plan["new"]),
            reused=len(plan["reused"]), reclassify=len(plan["reclassify"]),
            closed=len(plan["closed"]),
        )
    )

    # ttl: CLI 显式值优先, 否则续传 state 值 (None = 门不激活)
    ttl = (
        args.assessments_ttl
        if args.assessments_ttl is not None
        else state.get("assessments_ttl")
    )
    gate = engine.gate_tier_b(
        provenance, current_keys=faces.keys(), assessments_ttl=ttl,
        # DEC 裁定-9: 上下文一变 ⇒ Tier B 全量重评 — 上下文门用本轮
        # context_fingerprint 的 canonical 键 (CLI 无需新参数, 上下文已采集)。
        context_key=fingerprint.context_key(context),
    )
    log(
        f"groom: tier_b reusable={len(gate['reusable'])} "
        f"stale={len(gate['stale'])} orphaned={len(gate['orphaned'])} ttl={ttl!r}"
    )

    seg = diffseg.build_diff_segment(plan, top_n=args.top_n)

    report = _assemble_report(
        harness=args.harness,
        now_dt=now_dt,
        fetched=fetched,
        issues=issues,
        classified=classified,
        taxonomy=taxonomy,
        state=state,
        gate=gate,
        seg=seg,
        assessments_doc=assessments_cache.get("doc"),
    )
    _self_check(report)  # 先校验后写盘 (fail-closed)
    log("groom: schema self-check ok (v1.1)")

    # D-1: --out 报告写盘先于 save_state (报告面先落, state 后落 — 报告
    # 写失败 ⇒ OSError 上抛 exit 1, state 未写; 反序会把「报告没出厂」的
    # 轮次静默记成已完成增量轮)。
    if report_out is not None:
        Path(report_out).write_text(_report_payload(report), encoding="utf-8")

    ttl_kwargs: dict[str, Any] = {}
    if args.assessments_ttl is not None:
        ttl_kwargs["assessments_ttl"] = args.assessments_ttl  # 显式值 (含清除语义由 build_next_state 定义)
    next_state = engine.build_next_state(
        state, plan, faces, classified, taxonomy_hash,
        context, provenance,
        scope_degraded=scope.scope_degraded,  # B-1: 降级落 state (additive)
        context_degraded=ctx_degraded,        # A-3: 指纹降级落 state (additive)
        **ttl_kwargs,
    )
    engine.save_state(next_state)  # 原子写; 结构上不触 assessments 文件
    log(f"groom: state saved -> {state_path}")
    return report


# ------------------------------------------------------------------ CLI 壳

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="groom.py",
        description="issue-groomer P1: 卫星仓 open issue 组合面梳理 "
        "(fetch → Tier A 粗分 → 增量指纹 → diff → schema v1.1 报告)",
    )
    p.add_argument("--repos", nargs="+", metavar="NAME",
                   help="扫描仓清单 (裸名或 owner/name); 缺省回落 "
                        ".aria/config.json 的 state_scanner.issue_scan 形态")
    p.add_argument("--project-root", default=DEFAULT_PROJECT_ROOT,
                   help="项目根 (taxonomy 覆盖层 / state / assessments / "
                        "openspec·handoff 指纹的锚点; 默认 cwd)")
    p.add_argument("--out", default=None, metavar="PATH",
                   help="报告输出文件 (缺省 stdout, JSON)")
    p.add_argument("--harness", default=DEFAULT_HARNESS,
                   help=f"harness 自报标识 (provenance 第一层; 默认 {DEFAULT_HARNESS!r})")
    p.add_argument("--model-id", default=None, metavar="ID",
                   help="模型标识 (缺省 None — 适配层补全; None 与任何具体 "
                        "model_id 不匹配 ⇒ assessments 判 stale)")
    p.add_argument("--now", default=None, metavar="ISO",
                   help="时钟注入 (ISO 8601; 缺省系统时钟) — staleness 档 / "
                        "ttl 判定 / generated_at / state 时间戳全用同一时钟")
    p.add_argument("--top-n", type=int, default=diffseg.DEFAULT_TOP_N,
                   help=f"drift top-N 截断上限 (默认 {diffseg.DEFAULT_TOP_N}; "
                        f"schema 护栏 {diffseg.DRIFT_SCHEMA_MAX_ITEMS})")
    p.add_argument("--assessments-ttl", type=int, default=None, metavar="DAYS",
                   help="assessment 有效期天数 (缺省续传 state 值; created_at+ttl "
                        "≤ now 判 stale)")
    p.add_argument("--runner-bin", default=fetch.DEFAULT_BIN, metavar="PATH",
                   help=f"forgejo CLI wrapper 路径 (默认 {fetch.DEFAULT_BIN})")
    p.add_argument("--state-path", default=None, metavar="PATH",
                   help="state 文件路径覆盖 (默认 <project_root>/"
                        ".aria/cache/groom-state.json)")
    p.add_argument("--quiet", action="store_true", help="抑制 stderr 进度行")
    args = p.parse_args(argv)
    if args.top_n < 0:
        p.error(f"--top-n 须 >= 0, got {args.top_n}")
    if args.assessments_ttl is not None and args.assessments_ttl < 0:
        p.error(f"--assessments-ttl 须 >= 0 (天), got {args.assessments_ttl}")
    # B.3 预校验 (exit 2): --repos spec 形态与 --now ISO 可解析性属「用户
    # 输入面」错误, 在 argparse 层拦 (p.error → usage + exit 2), 不进
    # pipeline 也不冒充运行错误 (exit 1)。同判据随后仍由 lib 层复验
    # (fetch.split_repo_spec / _parse_now), 此处只是把失败提前到零 IO。
    for spec in args.repos or []:
        try:
            fetch.split_repo_spec(spec)
        except ValueError as exc:
            p.error(f"--repos {spec!r}: {exc}")
    if args.now is not None:
        try:
            _parse_now(args.now)
        except ValueError as exc:
            p.error(f"--now {args.now!r}: 无法解析为 ISO 8601 ({exc})")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    def _log(msg: str) -> None:
        if not args.quiet:
            print(msg, file=sys.stderr)

    try:
        # D-1: --out 的报告写盘活在 run_pipeline 内 (先于 save_state);
        # main 只保留 stdout 面。
        report = run_pipeline(args, log=_log, report_out=args.out)
    except ConfigError as exc:
        print(f"groom: config error: {exc}", file=sys.stderr)
        return 2
    except SchemaError as exc:
        print(f"groom: {exc}", file=sys.stderr)
        return 1
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"groom: error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    except Exception:
        # 兜底 (E-4): 未分类运行错误统一 exit 1 (不裸 traceback 炸穿壳),
        # 完整 traceback 进 stderr 供诊断 — exit 码契约 0/1/2 全路径成立。
        print("groom: unexpected error (traceback follows):", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1
    if not args.out:
        try:
            sys.stdout.write(_report_payload(report))
        except OSError as exc:
            print(f"groom: 报告输出失败: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

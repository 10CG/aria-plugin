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
     报错说明, 不猜)。
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
  - **自校验 (fail-closed)**: 产出 report 先过 schema (test_schema 的
    mini_validate, stdlib-only, 不依赖 jsonschema; 直载 ``tests/
    test_schema.py`` — 生产环境缺 pytest 时注入最小 stub, 校验实现仍
    单点 SOT 不内联副本), 校验失败 ⇒ 不写 state 不出厂, exit 1。

编排流程: fetch_all → resolve_taxonomy → classify (now 注入) →
fingerprint_issues → context_fingerprint (git_roots = project_root +
卫星仓真实路径, .gitmodules 目录名↔origin 裸仓名映射) → load_state →
plan_tier_a → gate_tier_b (读 assessments 若在) → build_diff_segment →
组装 report → 自校验 → build_next_state + save_state → 输出。

assessed_keys 面: 本层恒 None (机械层无 Tier B 重评信息; drift 候选 =
new ∪ reclassify)。适配层 (TASK-010) 的注入面是后续 additive 演进, 不
在本版私造。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # 直接脚本执行: scripts/ 自动入 path (双保险)
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import diffseg, fetch, fingerprint, incremental, tier_a  # noqa: E402

__all__ = [
    "ConfigError",
    "SchemaError",
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


def _extract_owner_repo(remote_url: str) -> str | None:
    """remote URL → ``owner/repo``; 剥协议 / user@ / host(:port) / .git /
    query / fragment; 非「恰两段」形态 ⇒ None (不猜)。"""
    s = (remote_url or "").strip()
    if not s:
        return None
    s = re.sub(r"^[a-z][a-z0-9+.-]*://", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^[^@/]+@", "", s)
    s = re.sub(r"^[^:/]+[:/]", "", s)
    s = re.sub(r"\.git(?:[?#/].*)?$", "", s)
    s = re.sub(r"\.git$", "", s)
    s = s.rstrip("/")
    return s if _OWNER_REPO_RE.match(s) else None


def _origin_owner_repo(root: Path) -> str | None:
    url = _git(["remote", "get-url", "origin"], root)
    return _extract_owner_repo(url) if url else None


def _submodule_paths(project_root: Path) -> list[str]:
    """.gitmodules 的 submodule path 清单 (.gitmodules 缺席/解析失败 ⇒ [],
    fail-soft — 作用域推导的降级由 resolve_repos 的 fail-closed 收口)。"""
    out = _git(
        ["config", "-f", ".gitmodules", "--get-regexp", r"^submodule\..+\.path$"],
        project_root,
    )
    if out is None:
        return []
    paths: list[str] = []
    for line in out.splitlines():
        m = _SUBMODULE_PATH_RE.match(line.strip())
        if m and m.group(1).strip():
            paths.append(m.group(1).strip())
    return paths


# ------------------------------------------------------------ 作用域解析

def resolve_repos(explicit: list[str] | None, project_root: Path) -> list[str]:
    """扫描仓清单: ``--repos`` 优先; 否则回落 config (见模块 docstring 第 1 块)。

    返回 spec 清单 (裸名或 ``owner/name``, fetch.split_repo_spec 消费);
    任何回落失败 ⇒ ConfigError (exit 2, 消息说明补救路径)。
    """
    if explicit:
        return list(dict.fromkeys(explicit))  # 保序去重 (fetch 层亦去重, 双保险)
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
        return list(dict.fromkeys(repos))
    if scan.get("scan_submodules"):
        # state-scanner 同款: 主仓 + 各 submodule 的 origin → owner/name
        specs: list[str] = []
        main = _origin_owner_repo(root)
        if main:
            specs.append(main)
        for sub in _submodule_paths(root):
            owner_repo = _origin_owner_repo(root / sub)
            if owner_repo:
                specs.append(owner_repo)
        if specs:
            return specs
        raise ConfigError(
            "scan_submodules=true 但主仓/子模块的 origin remote 均无法推导 "
            "owner/repo (git remote get-url origin 失败或 URL 形态非法) — "
            "补救: --repos 显式指定"
        )
    raise ConfigError(
        "state_scanner.issue_scan 无 repos 键且 scan_submodules 未启用 — "
        "无法确定扫描仓清单 (补救: --repos 或启用 scan_submodules)"
    )


def resolve_git_roots(project_root: Path, repo_specs: list[str]) -> list[str]:
    """context_fingerprint 的 git_roots: project_root + 卫星仓**真实路径**
    (.gitmodules 目录 ↔ origin 裸仓名映射 — 卫星仓目录名可与裸仓名不同,
    如目录 ``aria`` ↔ 仓 ``aria-plugin``)。键 = 路径串原样 (fingerprint
    契约: 稳定标识, 不归一)。映射不上的选中仓 (如 --repos 指定外仓) 只剩
    主仓 root — git_heads 覆盖面如实变窄, 不虚增。"""
    root = Path(project_root)
    roots = [str(root)]
    wanted: set[str] = set()
    for spec in repo_specs:
        try:
            _owner, bare = fetch.split_repo_spec(spec)
        except ValueError:
            continue  # 同 spec 由 fetch 层稍后 fail-closed, 此处不抢报错
        wanted.add(bare)
    for sub in _submodule_paths(root):
        sub_dir = root / sub
        if not sub_dir.is_dir():
            continue
        owner_repo = _origin_owner_repo(sub_dir)
        if owner_repo is None:
            continue
        bare = owner_repo.split("/", 1)[1]
        if bare in wanted:
            roots.append(str(sub_dir))
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

_MINI_VALIDATE_CACHE: dict[str, Any] = {}


def _mini_validate() -> Any:
    """取 test_schema 的 mini_validate (单点 SOT, 不内联副本)。

    importlib 文件直载 ``tests/test_schema.py`` (不 sys.path 注入, 双 lib
    包顺序风险同判); 模块顶部 ``import pytest`` 在无 pytest 的生产环境
    ImportError ⇒ 注入最小 stub (fixture/mark.skipif 只需 decorator 形态,
    模块级即够) 再重载。校验器本体逻辑零分支降级。"""
    if "fn" in _MINI_VALIDATE_CACHE:
        return _MINI_VALIDATE_CACHE["fn"]
    path = Path(__file__).resolve().parents[1] / "tests" / "test_schema.py"
    spec = importlib.util.spec_from_file_location("_groom_inline_test_schema", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except ImportError:
        if "pytest" not in sys.modules:
            stub = types.ModuleType("pytest")
            stub.fixture = lambda *a, **k: (lambda f: f)  # type: ignore[attr-defined]
            stub.mark = types.SimpleNamespace(  # type: ignore[attr-defined]
                skipif=lambda *a, **k: (lambda f: f)
            )
            sys.modules["pytest"] = stub
        spec.loader.exec_module(mod)
    _MINI_VALIDATE_CACHE["fn"] = mod.mini_validate
    return mod.mini_validate


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

def run_pipeline(
    args: argparse.Namespace,
    *,
    runner: Any = None,
    request_interval: float = fetch.DEFAULT_REQUEST_INTERVAL,
    log: Any = None,
) -> dict[str, Any]:
    """全编排 (可进程内调用, 测试注入 fake runner / request_interval=0)。

    返回组装后的 report dict (自校验已过, state 已写)。CLI 壳 (main) 只做
    参数解析 / 退出码 / 输出面。"""
    if log is None:
        log = _noop
    project_root = Path(args.project_root)
    now_dt = _parse_now(args.now) if args.now else datetime.now(timezone.utc)

    repos_specs = resolve_repos(args.repos, project_root)
    active_runner = runner if runner is not None else fetch.ForgejoCliRunner(
        bin_path=args.runner_bin
    )
    fetched = fetch.fetch_all(
        repos_specs, runner=active_runner, request_interval=request_interval
    )
    issues = fetched["issues"]
    log(f"groom: repos={len(fetched['repos'])} issues={len(issues)}")

    taxonomy = tier_a.resolve_taxonomy(project_root)
    classified = tier_a.classify(issues, taxonomy, now=now_dt)
    faces = fingerprint.fingerprint_issues(issues)
    context = fingerprint.context_fingerprint(
        project_root,
        git_roots=resolve_git_roots(project_root, repos_specs),
        taxonomy=taxonomy,  # 共享解析结果, 免二次读盘
    )
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
        provenance, current_keys=faces.keys(), assessments_ttl=ttl
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

    ttl_kwargs: dict[str, Any] = {}
    if args.assessments_ttl is not None:
        ttl_kwargs["assessments_ttl"] = args.assessments_ttl  # 显式值 (含清除语义由 build_next_state 定义)
    next_state = engine.build_next_state(
        state, plan, faces, classified, taxonomy_hash,
        context, provenance, **ttl_kwargs,
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
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    def _log(msg: str) -> None:
        if not args.quiet:
            print(msg, file=sys.stderr)

    try:
        report = run_pipeline(args, log=_log)
    except ConfigError as exc:
        print(f"groom: config error: {exc}", file=sys.stderr)
        return 2
    except SchemaError as exc:
        print(f"groom: {exc}", file=sys.stderr)
        return 1
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"groom: error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    try:
        if args.out:
            Path(args.out).write_text(payload, encoding="utf-8")
        else:
            sys.stdout.write(payload)
    except OSError as exc:
        print(f"groom: 报告输出失败: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Pre-merge precondition gate helper for phase-c-integrator C.2.4.

Rule #8 (CLAUDE.md) — verify (a) PR CI passing + (b) main branch no in-flight
runs before merge. v1.31.0+ supports pluggable CI backends via the
ci_backends/ package (AetherBackend default, GitHubActionsBackend stub).

Exception contract (v1.31.0+, Hard Constraint #7 — NIE-propagation):
- Backend query_*() may raise NotImplementedError (stub backend). gate_check
  MUST propagate NIE to caller, NOT catch and route through no_ci_fallback.
  Callers MUST handle NIE explicitly. This breaks the old "exceptions are
  always translated to verdict=fail" contract — see Rule #8 wording in
  CLAUDE.md + SKILL.md §C.2.4.X for full rationale.
- AetherQueryError (or other backend transport errors) IS caught and
  translated to verdict=FAIL with raw_message (backward-compatible path).

stdlib + subprocess only (no third-party deps). Cross-platform: assumes
POSIX-like shell for `which`. Windows users go through Git Bash / WSL.

Usage (CLI):
    pre_merge_gate.py --pr-branch <branch> [--main-branch main] [--config-file path]

Output: single JSON line on stdout matching SKILL.md §C.2.4 Output schema.
Exit code: 0 = success (any verdict). Non-zero = helper failure
(distinct from gate verdict=fail which is a successful query).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import warnings
from typing import Any

from ci_backends import (
    BACKENDS,
    AetherQueryError,
    CIBackend,
    cached_probe,
)
# #137: 重试轴复用既有先例, ⛔ 不在本模块另造一套 backoff (memory fix-the-class)。
from ci_backends.aether import MAX_RETRY_ATTEMPTS, RETRY_BACKOFF
# v1.65.0+ (#122): path coverage 评估器。模块级符号, 测试经
# mock.patch.object(gate, "evaluate_path_coverage") 打桩 (镜像 resolve_ci_backend 先例)。
from path_coverage import evaluate_path_coverage  # noqa: E402

# Verdict enum values.
VERDICT_GREEN = "green"
VERDICT_WAIT = "wait"
VERDICT_FAIL = "fail"

# v1.31.0+ default config (Hard Constraint #8: ci_backends list order is
# the explicit precedence; absent vs [] disambiguation per AC-4.5).
DEFAULT_CONFIG = {
    "enabled": True,
    "ci_backends": None,  # None/missing = auto-detect; [] = explicit disable
    "no_ci_fallback": "skip_with_warning",
    "wait_timeout_seconds": 1800,
    "wait_check_intervals": [30, 60, 120, 300, 300],
    "primitive_call_timeout_seconds": 30,
    "poll_chunk_seconds": 5,
    "user_escape_hatch": True,
    # v1.65.0+ (#122): 路径覆盖感知默认开启 (owner sign-off 2026-07-27 单独批
    # 默认 true)。fail-toward-covered: 评估不确定时行为与关闭时逐字段一致。
    "path_coverage_enabled": True,
    # v1.66.5+ (#152): pr_ci_status="not_found" (远端零 run) 连续观测多少次后
    # 才提示用户人工核验; int ≥2 (不提供 1 —— 单次零 run 太常见于新分支首推,
    # 阈值 1 会把正常瞬时态当异常提示)。校验见 _effective_prompt_threshold。
    "no_run_prompt_after_observations": 3,
}

# Legacy key alias map for soft-deprecation (Hard Constraint #3).
# Old keys still readable until v2.0; new key wins on conflict (Hard #9).
_OLD_TO_NEW: dict[str, str] = {
    "primitive_preference": "ci_backends",  # value-shape changes — see _translate_value
    "no_aether_fallback": "no_ci_fallback",
}


def _translate_value(old_key: str, old_value: Any) -> Any:
    """Per-key value-shape translation for legacy alias (Rev1 complete table).

    Translation map:
      primitive_preference: ["aether-ci-cli"]  → ci_backends: [{"name": "aether-ci-cli"}]
                            ["foo", "bar"]    → ci_backends: [{"name": "foo"}, {"name": "bar"}]
                            []                → ci_backends: []  (preserves explicit-disable semantic)
      no_aether_fallback:   "skip_with_warning" → no_ci_fallback: "skip_with_warning"  (no shape change)
                            "abort"             → no_ci_fallback: "abort"              (no shape change)
    """
    if old_key == "primitive_preference":
        if not isinstance(old_value, list):
            return old_value  # defensive: malformed config, pass through
        return [{"name": n} for n in old_value]
    if old_key == "no_aether_fallback":
        return old_value  # string enum, no shape change
    return old_value  # defensive: unknown key (shouldn't reach since _OLD_TO_NEW filters)


def _normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    """Translate legacy config keys to v1.31.0 schema with deprecation warnings.

    Operates at the `phase_c_integrator.pre_merge_gate` config sub-dict level
    (caller responsibility to pass the right sub-dict, not top-level config).
    Per Hard Constraint #3 (alias support) + #9 (new key wins on conflict).
    """
    out = dict(config)  # shallow copy
    for old, new in _OLD_TO_NEW.items():
        if old in out:
            if new in out:
                # Conflict: new wins, old discarded (Hard Constraint #9).
                warnings.warn(
                    f"both_keys_present: ignoring `{old}`, using `{new}`",
                    DeprecationWarning,
                    stacklevel=2,
                )
                del out[old]
            else:
                # Soft alias: translate old → new + warn.
                warnings.warn(
                    f"`{old}` is deprecated; use `{new}`; "
                    f"will be removed in v2.0",
                    DeprecationWarning,
                    stacklevel=2,
                )
                out[new] = _translate_value(old, out.pop(old))
    return out


def _effective_prompt_threshold(cfg: dict[str, Any] | None) -> int:
    """no_run_prompt_after_observations 的有效值 (aria-plugin#152 唯一校验点)。

    cfg=None → 取 DEFAULT_CONFIG 自身; 键缺失 (`.get` 返回 None) → 回落默认值
    3, **不** warn (未显式配置是正常态, 不是配置错误)。值非 int / 是 bool
    (bool 是 int 子类, 须先排除, 否则 True 被当成合法整数 1 放行) / <2 → warn
    一次 (stacklevel=2, 指向调用方而非本函数) 并回落默认值; 阈值 1 未提供 ——
    单次零 run 在新分支首推场景太常见 (aria-plugin#152 探针), 阈值 1 会把正常
    瞬时态当异常提示。
    """
    source = cfg if cfg is not None else DEFAULT_CONFIG
    value = source.get("no_run_prompt_after_observations")
    default = DEFAULT_CONFIG["no_run_prompt_after_observations"]
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value < 2:
        warnings.warn(
            f"no_run_prompt_after_observations invalid ({value!r}); "
            f"must be int >= 2; falling back to {default}",
            stacklevel=2,
        )
        return default
    return value


def _no_run_gate_error(
    path_coverage: dict[str, Any] | None, threshold: int
) -> dict[str, Any]:
    """gate_error 载荷 (aria-plugin#152, pr_ci_status="not_found" 唯一产出点)。

    message 按 `(decision, reason 前缀)` 封闭表, 每档以 "no-run-for-branch: "
    开头 (使所有档含该子串, 供上游速判/grep)。封闭表 + 显式兜底 —— 不让
    KeyError 逃出 (理论不可达组合, 如 decision=not_applicable, 也落兜底档而
    非炸)。⛔ 渲染禁用 `str.format` (后续 dispatch 行含 JSON 花括号会炸);
    用 f-string/拼接。
    """
    if path_coverage is None:
        message = "no-run-for-branch: 远端零 run; 路径覆盖评估已关闭"
    else:
        decision = path_coverage.get("decision")
        reason = path_coverage.get("reason") or ""
        if decision == "covered" and reason == "workflow-trigger-matched":
            matched = path_coverage.get("matched_workflows") or []
            message = (
                f"no-run-for-branch: 变更 path-matched {', '.join(matched)} "
                "但远端零 run — 符合 aria-plugin#152 (新分支首推 × paths 过滤, "
                "Forgejo 不建 run), 或 run 尚未被 runner 领走, 或 workflow "
                "branches 过滤不含本分支"
            )
        elif decision == "covered" and reason == "workflow-files-changed":
            message = (
                "no-run-for-branch: 变更含 workflow 文件本身 (按 covered) 但"
                "远端零 run — 同 aria-plugin#152 形态, 或 run 尚未被 runner "
                "领走, 或 workflow branches 过滤不含本分支"
            )
        elif decision == "covered" and reason == "empty-diff":
            message = (
                "no-run-for-branch: main...PR 三点 diff 为空, 无变更可跑; "
                "远端零 run"
            )
        elif decision == "unknown" and reason.startswith(
            ("git-diff-failed", "workflow-parse-failed", "internal-error")
        ):
            message = (
                f"no-run-for-branch: 远端零 run; 路径覆盖未判定 (reason={reason})"
            )
            if reason.startswith("internal-error"):
                message += " — 评估器自身异常, 请报 issue"
        else:
            # 兜底: 封闭表外的任何组合 (含理论不可达的 not_applicable) —— 显式
            # 兜底而非 KeyError/IndexError 逃出。
            message = (
                f"no-run-for-branch: 远端零 run (path_coverage "
                f"decision={decision}, reason={reason})"
            )
    return {
        "kind": "no-run-for-branch",
        "message": message,
        "prompt_after_observations": threshold,
    }


def resolve_ci_backend(config: dict[str, Any]) -> CIBackend | None:
    """Resolve CI backend per [DEC 2026-05-28] §Q3 (b) config-first + probe fallback.

    Semantics (Hard Constraint #8 + AC-4.5):
      - config["ci_backends"] absent OR None  → auto-detect via BACKENDS list order
      - config["ci_backends"] is empty list [] → explicit disable (return None
        immediately, caller routes per no_ci_fallback). This is the canonical
        way for user to bypass CI backend integration in v1.31.0+.
      - config["ci_backends"] non-empty list  → try in user-specified order,
        return first that probes True;exhausted → None

    Returns None signals caller to route through no_ci_fallback path.
    """
    explicit = config.get("ci_backends")
    if explicit is not None:
        # User provided config (including [] = explicit disable per AC-4.5).
        if not explicit:
            return None
        name_map = {b.name: b for b in BACKENDS}
        for entry in explicit:
            backend_cls = name_map.get(
                entry.get("name") if isinstance(entry, dict) else entry
            )
            if backend_cls and cached_probe(backend_cls):
                return _instantiate(backend_cls, config)
        return None
    # Auto-detect (config missing or None).
    for backend_cls in BACKENDS:
        if cached_probe(backend_cls):
            return _instantiate(backend_cls, config)
    return None


def _instantiate(backend_cls: type[CIBackend], config: dict[str, Any]) -> CIBackend:
    """Instantiate backend with config-derived params where applicable.

    Currently only AetherBackend accepts a timeout param; future backends
    may accept different config-derived constructor args via this single
    extension point.
    """
    if backend_cls.name == "aether-ci-cli":
        timeout = int(config.get("primitive_call_timeout_seconds", 30))
        return backend_cls(timeout=timeout)
    return backend_cls()


def compute_verdict(
    main_in_flight_runs: list[dict[str, Any]],
    pr_ci_status: str,
    backend_name: str = "aether-ci-cli",
    cfg: dict[str, Any] | None = None,
    path_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute three-state verdict per SKILL.md §C.2.4 step 5.

    Hard Constraint #10 (Rev1) — extended signature accepts backend_name for
    primitive_used output field (replaces hardcoded "aether-ci-cli"). Default
    "aether-ci-cli" preserves backward compat for old test code calling with
    positional args (main_in_flight_runs, pr_ci_status).

    Returns full output dict (was: returns str). Backward-compat note: old
    callers expecting `str` must use new signature explicitly.

    Note: Returns dict for v1.31.0+ to consolidate the verdict + output_build
    code path that gate_check used to do in two steps. Old `compute_verdict`
    that returned str is replaced — Hard Constraint #10 locks new signature.

    v1.66.5+ (aria-plugin#152): `pr_ci_status == "not_found"` (远端零 run) →
    verdict=wait + `gate_error={"kind": "no-run-for-branch", ...}` (副本通道
    #137: 同一段文字同时写进 raw_message)。不论 main in-flight 与否都是 wait
    ((a) 轴本身就未判定, 无法与 (b) 轴的 green 状态叠加)。
    """
    # Verdict computation (preserved logic from pre_merge_gate.py L217-228).
    raw_message = ""
    gate_error: dict[str, Any] | None = None
    if pr_ci_status in ("failing", "error"):
        verdict = VERDICT_FAIL
    elif pr_ci_status == "pending":
        verdict = VERDICT_WAIT
    elif pr_ci_status == "not_applicable":
        # v1.65.0+ (#122) 显式分支 (BA-8: 不依赖 fallthrough 隐式兜底) —
        # (a) PR CI wait 已因路径零覆盖免除; (b) main in-flight 轴照常裁决 (D3)。
        pc_reason = (path_coverage or {}).get("reason", "")
        if main_in_flight_runs:
            verdict = VERDICT_WAIT
            raw_message = (
                "path_coverage: no workflow covers changed files "
                f"(reason={pc_reason}); PR CI wait skipped (not_applicable); "
                "waiting on main in-flight runs only ((b)-axis)"
            )
        else:
            verdict = VERDICT_GREEN
            raw_message = (
                "path_coverage: no workflow covers changed files "
                f"(reason={pc_reason}); PR CI wait skipped (not_applicable); "
                "main in-flight clear"
            )
    elif pr_ci_status == "not_found":
        # v1.66.5+ (#152): 必须落在 not_applicable 之后、main_in_flight_runs
        # 之前 —— ⚠️ 位置是承重的: 若放到 `elif main_in_flight_runs:` 之后,
        # (not_found, main 非空) 组合会先被那支 truthy 分支命中 (它不检查
        # pr_ci_status), gate_error 被悄悄吞掉, 只剩裸 wait 无诊断信息。
        # 不论 main in-flight 与否都是 wait —— (a) 轴本身未判定, 没有可与
        # (b) 轴 green 叠加的基础。
        verdict = VERDICT_WAIT
        gate_error = _no_run_gate_error(
            path_coverage, _effective_prompt_threshold(cfg)
        )
        raw_message = gate_error["message"]  # 副本通道 #137: 同文同写
    elif main_in_flight_runs:
        # pr_ci_status == "passing" + main has in-flight runs → wait
        verdict = VERDICT_WAIT
    else:
        # pr_ci_status == "passing" + main no in-flight → green
        verdict = VERDICT_GREEN

    return _build_output(
        verdict=verdict,
        pr_ci_status=pr_ci_status,
        in_flight_runs=main_in_flight_runs,
        primitive_used=backend_name,
        raw_message=raw_message,
        path_coverage=path_coverage,
        gate_error=gate_error,
    )


def _build_output(
    verdict: str,
    pr_ci_status: str,
    in_flight_runs: list[dict[str, Any]],
    primitive_used: str,
    raw_message: str = "",
    primitive_version_sha: str = "",
    path_coverage: dict[str, Any] | None = None,
    gate_error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the canonical output dict per SKILL.md §C.2.4 Output schema.

    v1.65.0+ (#122, BA-6): `path_coverage` 是 additive 可选键 — 仅当评估已执行
    且流程走到 compute_verdict 最终路径时在场 (path_coverage 非 None); 各早退
    分支 (enabled:false / no-backend / precheck 失败 / backend query 失败) 保持
    既有六键不变。

    #137/#152: `gate_error` 亦为 additive 可选键 — 三类在场: (1) main 分支存在性
    核验判 fail (`main-branch-not-found` / `main-branch-verify-failed`, 无
    path_coverage); (2) pr-branch 存在性核验判 fail (`pr-branch-not-found`,
    TASK-006 已实现); (3) pr_ci_status="not_found" 的 wait 态
    (`no-run-for-branch`, 带 `prompt_after_observations`, 可与 path_coverage
    同时在场)。它始终是**副本通道**: 同一段文字必定同时写入 `raw_message`
    (主通道), 消费方只读 raw_message 亦不丢信息。
    """
    # For Aether backend, populate primitive_version_sha from module constant.
    # For other backends, leave empty (or future: backend-specific version).
    if primitive_used == "aether-ci-cli" and not primitive_version_sha:
        from ci_backends.aether import AETHER_CLI_MIN_SHA
        primitive_version_sha = AETHER_CLI_MIN_SHA
    out = {
        "verdict": verdict,
        "pr_ci_status": pr_ci_status,
        "in_flight_runs": in_flight_runs,
        "primitive_used": primitive_used,
        "primitive_version_sha": primitive_version_sha,
        "raw_message": raw_message,
    }
    if path_coverage is not None:
        out["path_coverage"] = path_coverage
    if gate_error is not None:
        out["gate_error"] = gate_error
    return out


# --- 分支存在性核验 (main: #137 / PR: #152 仅 not_found 时) --------------------
#
# 症状: 后端结构上无法区分「分支不存在」与「分支没有 in-flight run」—— 两者都
# 产出 InFlightStatus(runs=[]) ⇒ 判 green。于是把 --main-branch 写成一个远端上
# 不存在的名字 (本项目主干是 master, 而缺省值是 main), 这条腿恒真。
#
# ⛔ 三条实测得出的禁令, 违反任一条都会让核验重新变成摆设:
#   1. 不得读退出码 —— `git ls-remote` 零命中亦返 rc=0;
#   2. 不得用 `--exit-code` —— 无命中返 rc=2, 会被 catch-all 误分类成"核验失败";
#   3. 不得用 pattern/glob 匹配 —— ls-remote 把参数当 glob, 'mast*' 会命中 master。
# 判据只能落在**解析出的 ref 名列表**上做精确字符串比对。
_LS_REMOTE_TIMEOUT = 30


def _sanitize_for_json(text: str) -> str:
    """剥掉孤立代理码位, 使字符串能过 json.dumps / encode(strict)。

    stderr 用 errors="surrogateescape" 解码 (它永不抛), 但可能留下孤立代理码位;
    那些码位会在 **json.dumps 时**炸 UnicodeEncodeError —— 离现场很远。故在出口
    就地净化。
    """
    return text.encode("utf-8", "replace").decode("utf-8")


def _verify_branch_exists(
    branch: str, remote: str, timeout: int = _LS_REMOTE_TIMEOUT
) -> tuple[str, str]:
    """核验 `branch` 在 `remote` 上确实存在。返回 (status, detail)。main 与 PR
    两处共用 (aria-plugin#152: 原 `_verify_main_branch_exists` 搬迁改名, 旧名
    保留为对本函数的位置参数包装, 见 `_verify_main_branch_exists`)。

    status ∈ {"ok", "not-found", "verify-failed"} —— 「分支不存在」与「核验本身
    没做成」必须分开, 二者混为一谈正是本 bug 的形状。

    轴复用 (⛔ 不再造第三份): 异常轴取 path_coverage.py 的
    `(TimeoutExpired, FileNotFoundError, OSError)` 元组; 重试轴取
    ci_backends/aether.py 的 `RETRY_BACKOFF`。
    ⚠️ 只有 TimeoutExpired 重试 —— FileNotFoundError/OSError 是确定性失败, 重试
    只是白等; rc!=0 同理 (SC-A7 逐字要求"未重试")。
    ⚠️ ⛔ 不传 `text=True`: 那会让 subprocess 自己解码, 于是 UnicodeDecodeError
    直接裸抛穿过 gate_check() (且它**不是** OSError 的子类, 上面的元组接不住)。
    我们自己用 surrogateescape 解码, 该异常结构上不可能发生。
    ⚠️ 不传 `cwd=`: 继承进程 cwd, 使 `origin` 按调用者所在仓解析。
    """
    target = "refs/heads/" + branch
    last_detail = ""
    for attempt in range(MAX_RETRY_ATTEMPTS):
        try:
            proc = subprocess.run(
                ["git", "ls-remote", "--heads", remote, branch],
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            last_detail = f"{type(exc).__name__}: {exc}"
            if attempt < MAX_RETRY_ATTEMPTS - 1:
                time.sleep(RETRY_BACKOFF[attempt])
                continue
            return "verify-failed", last_detail
        except (FileNotFoundError, OSError) as exc:
            return "verify-failed", f"{type(exc).__name__}: {exc}"

        if proc.returncode != 0:
            stderr = (proc.stderr or b"").decode("utf-8", errors="surrogateescape")
            return "verify-failed", (
                f"git ls-remote rc={proc.returncode}: {stderr.strip()}"
            )

        stdout = (proc.stdout or b"").decode("utf-8", errors="surrogateescape")
        ref_names = [
            line.split("\t", 1)[1].strip()
            for line in stdout.splitlines()
            if "\t" in line
        ]
        return ("ok" if target in ref_names else "not-found"), ""

    return "verify-failed", last_detail


def _verify_main_branch_exists(
    main_branch: str, remote: str, timeout: int = _LS_REMOTE_TIMEOUT
) -> tuple[str, str]:
    """旧名包装: 保关键字签名与默认值, 委托给 `_verify_branch_exists`
    (aria-plugin#152 搬迁改名)。`:449` 调用字面不改, 测试 mixin 对旧名打桩
    继续有效。"""
    return _verify_branch_exists(main_branch, remote, timeout)


def _no_ci_output(no_ci_fallback: str) -> dict[str, Any]:
    """Build output for the no-backend-available case per fallback config.

    Renamed from _no_aether_output (Rev1 R1 tech F-05 — backend-agnostic
    naming). Message text updated to reference "CI backend" instead of
    "aether" specifically.
    """
    if no_ci_fallback == "abort":
        return _build_output(
            verdict=VERDICT_FAIL,
            pr_ci_status="pending",
            in_flight_runs=[],
            primitive_used="manual",
            raw_message=(
                "no CI backend available and no_ci_fallback=abort: "
                "install a supported CI backend (aether-ci-cli currently) "
                "or set no_ci_fallback=skip_with_warning"
            ),
        )
    # skip_with_warning (default): treat as green so workflow proceeds, but
    # mark the message so callers / reports surface the skip.
    return _build_output(
        verdict=VERDICT_GREEN,
        pr_ci_status="pending",
        in_flight_runs=[],
        primitive_used="manual",
        raw_message=(
            "no CI backend available; gate skipped per no_ci_fallback=skip_with_warning"
        ),
    )


def gate_check(
    pr_branch: str,
    main_branch: str = "main",
    config: dict[str, Any] | None = None,
    remote: str = "origin",
) -> dict[str, Any]:
    """Run the pre-merge gate end-to-end. Return SKILL.md §C.2.4 output dict.

    Exception semantics (v1.31.0+, Hard Constraint #7):
      - NotImplementedError from backend.query_*() PROPAGATES (abort, NOT
        caught and routed to no_ci_fallback). Callers MUST handle NIE
        explicitly. This indicates a stub backend that needs implementation;
        silently skipping defeats Rule #8.
      - AetherQueryError (transport/parse failures) IS caught and translated
        to verdict=FAIL with raw_message (backward-compat path).
      - Other exceptions propagate (unchanged from prior behavior).

    Query order (Hard Constraint #1, ground truth gate_check L309-329):
      main in-flight FIRST → PR CI SECOND (early-fail on main in-flight short-
      circuits PR query). v1.65.0+ (#122): PR CI 查询是条件性的 — path coverage
      decision=not_applicable 时跳过 (a) 查询 (subprocess 调用数 0 或 1); (b)
      main in-flight 查询保持无条件执行, NIE 经 (b) 照常 propagate (SC-21)。
      (a) 腿返 not_found 时再做一次 PR 分支存在性核验 (第七个早退, #152)。
    """
    # Alias translation BEFORE merge with DEFAULT_CONFIG (Hard Constraint #9).
    # If we merged first, DEFAULT_CONFIG's new keys would always shadow user's
    # old-key values (new-wins rule would discard user intent). So:
    # 1. Normalize user config (translate user's old keys to new keys + warn)
    # 2. THEN merge with default (user's translated new key overrides default)
    user_normalized = _normalize_config(config or {})
    cfg = {**DEFAULT_CONFIG, **user_normalized}

    if not cfg["enabled"]:
        return _build_output(
            verdict=VERDICT_GREEN,
            pr_ci_status="pending",
            in_flight_runs=[],
            primitive_used="manual",
            raw_message="pre_merge_gate.enabled=false; gate skipped",
        )

    backend = resolve_ci_backend(cfg)
    if backend is None:
        return _no_ci_output(cfg["no_ci_fallback"])

    # Backend-specific precheck (e.g. AetherBackend verifies --in-flight flag
    # presence). Default precheck() returns (True, "") for backends with no
    # version constraints.
    ok, precheck_err = backend.precheck()
    if not ok:
        return _build_output(
            verdict=VERDICT_FAIL,
            pr_ci_status="pending",
            in_flight_runs=[],
            primitive_used=backend.name,
            raw_message=precheck_err,
        )

    # #137: main 分支存在性核验 —— 必须落在上面三道早退 (enabled=false /
    # no-backend / precheck 失败) **之后**, path coverage 评估**之前**。
    # ⚠️ 位置是承重的: 放在 path coverage 之后, 一个不存在的分支会先走完覆盖评估;
    # 放进下面那个 `if cfg.get("path_coverage_enabled", True):` 块内, 则关掉覆盖
    # 评估的调用方会连这道核验一起失去 —— 那是最自然的误植位置。
    mb_status, mb_detail = _verify_main_branch_exists(
        main_branch=main_branch,
        remote=remote,
        timeout=int(cfg.get("primitive_call_timeout_seconds", _LS_REMOTE_TIMEOUT)),
    )
    if mb_status != "ok":
        if mb_status == "not-found":
            kind = "main-branch-not-found"
            msg = f"main branch '{main_branch}' not found on remote '{remote}'"
        else:
            kind = "main-branch-verify-failed"
            msg = (
                f"could not verify main branch '{main_branch}' on remote "
                f"'{remote}': {mb_detail}"
            )
        msg = _sanitize_for_json(msg)
        return _build_output(
            verdict=VERDICT_FAIL,
            pr_ci_status="pending",
            in_flight_runs=[],
            primitive_used=backend.name,
            raw_message=msg,
            gate_error={"kind": kind, "message": msg},
        )

    # v1.65.0+ (#122): path coverage 评估 — precheck 之后、(a) PR CI 查询之前
    # (SKILL.md §C.2.4 步骤 2.5)。评估失败 (decision=unknown) → 行为退回现状。
    pc: dict[str, Any] | None = None
    if cfg.get("path_coverage_enabled", True):
        pc = evaluate_path_coverage(
            main_branch=main_branch, pr_branch=pr_branch
        )

    # Query order: main in-flight FIRST then PR CI SECOND (Rev1.1 corrected,
    # matches ground truth L309-329). Hard Constraint #7: NIE propagates.
    # (b) 无条件执行 — not_applicable 只免 (a), NIE 经 (b) 照常传出 (SC-21/D3)。
    try:
        in_flight = backend.query_branch_in_flight(main_branch)
    except NotImplementedError:
        raise  # Hard Constraint #7: propagate, do NOT route to no_ci_fallback
    except AetherQueryError as exc:
        return _build_output(
            verdict=VERDICT_FAIL,
            pr_ci_status="pending",
            in_flight_runs=[],
            primitive_used=backend.name,
            raw_message=str(exc),
        )

    if pc is not None and pc.get("decision") == "not_applicable":
        # 跳过 (a) PR CI 查询与其 wait — 高置信零覆盖 (SC-9/10 assert_not_called)。
        return compute_verdict(
            main_in_flight_runs=in_flight.runs,
            pr_ci_status="not_applicable",
            backend_name=backend.name,
            cfg=cfg,
            path_coverage=pc,
        )

    try:
        pr_status = backend.query_pr_ci(pr_branch)
    except NotImplementedError:
        raise  # Hard Constraint #7
    except AetherQueryError as exc:
        return _build_output(
            verdict=VERDICT_FAIL,
            pr_ci_status="pending",
            in_flight_runs=[],
            primitive_used=backend.name,
            raw_message=str(exc),
        )

    verify_note = ""  # 哨兵: 非 not_found 路径也可读 (R3 #3)
    if pr_status.state == "not_found":
        # #152 F5: 「PR 分支不存在」与「存在但零 run」在 backend 出口逐字节同形
        # —— 仅此时多付一次 ls-remote。
        st, detail = _verify_branch_exists(
            pr_branch,
            remote=remote,
            timeout=int(cfg.get("primitive_call_timeout_seconds", _LS_REMOTE_TIMEOUT)),
        )
        if st == "not-found":
            msg = _sanitize_for_json(
                f"PR branch '{pr_branch}' not found on remote '{remote}'"
            )
            return _build_output(
                verdict=VERDICT_FAIL,
                pr_ci_status="not_found",
                in_flight_runs=in_flight.runs,
                primitive_used=backend.name,
                raw_message=msg,
                path_coverage=pc,  # pc 在场 ⇔ enabled (pc 为 None 时 _build_output 自动不带键)
                gate_error={"kind": "pr-branch-not-found", "message": msg},
            )
        if st != "ok":
            verify_note = _sanitize_for_json(
                f" (PR 分支存在性核验失败: {detail})"
            )  # detail 是 git stderr, 必须消毒

    out = compute_verdict(
        main_in_flight_runs=in_flight.runs,
        pr_ci_status=pr_status.state,
        backend_name=backend.name,
        cfg=cfg,
        path_coverage=pc,
    )
    if out.get("gate_error"):
        # gate_check 知道分支名: 回填占位 (TASK-007b 渲染的 dispatch 行含
        # <pr_branch>) + 核验失败附注; 副本通道重同步。
        m = out["gate_error"]["message"].replace(
            "<pr_branch>", _sanitize_for_json(pr_branch)
        ) + verify_note
        out["gate_error"]["message"] = m
        out["raw_message"] = m
    return out


def _load_config_from_file(path: str) -> dict[str, Any]:
    """Read .aria/config.json and extract phase_c_integrator.pre_merge_gate block."""
    try:
        with open(path, encoding="utf-8") as fh:
            full = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    pci = full.get("phase_c_integrator") or {}
    if not isinstance(pci, dict):
        return {}
    block = pci.get("pre_merge_gate") or {}
    return block if isinstance(block, dict) else {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pre-merge precondition gate (C.2.4)")
    parser.add_argument("--pr-branch", required=True, help="PR feature branch name")
    parser.add_argument("--main-branch", default="main", help="Main branch to check (default: main)")
    parser.add_argument(
        "--remote",
        default="origin",
        help=(
            "Remote to verify --main-branch (always) and --pr-branch (only "
            "when PR CI returns not_found) exist on (default: origin)"
        ),
    )
    parser.add_argument(
        "--config-file",
        default=".aria/config.json",
        help="Path to .aria/config.json (default: .aria/config.json)",
    )
    args = parser.parse_args(argv)
    config = _load_config_from_file(args.config_file)
    # ⚠️ `remote=args.remote` 这一行是承重的: 只加 add_argument 而漏这行, CLI 上
    # 传 --remote 会被静默忽略, 核验仍查默认 origin ⇒ 看起来加了参数其实没接线。
    output = gate_check(
        pr_branch=args.pr_branch,
        main_branch=args.main_branch,
        config=config,
        remote=args.remote,
    )
    sys.stdout.write(json.dumps(output, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())

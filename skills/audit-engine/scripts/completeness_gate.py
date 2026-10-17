#!/usr/bin/env python3
"""completeness_gate.py -- pre-merge change-scope completeness gate.

OpenSpec SOT: openspec/changes/pre-merge-completeness-gate-change-scope/
proposal.md (all semantics -- this docstring is a pointer, not a
duplicate); execution order pinned in proposal.md §1.0 ("求值总序");
tasks.md's 读前必看 table overrides the proposal text where the two
disagree (see that file's header).

This file is built incrementally, one detailed-tasks.yaml TASK at a time
(TASK-008: CLI arg contract, config loading + inline defaults +
legacy-config mapping, P1 (格 A / audit_not_enabled), 同仓判定, and the
stdout/exit-code/short-circuit framework every later stage reuses.
TASK-009: ref resolution + two-base-axis staleness warnings
(unconditional, after 同仓判定, before P2a), P2a (--no-spec anchor-face
precondition), and P2's scope resolution S1->S4.
TASK-010: lazy OpenSpec Level parsing (P3) and the per-(checkpoint,
change_id) five-tier resolved_mode/enabled_by priority chain, five
structural exclusions, and dangling-skip (P4).
TASK-011: the empty-inclusion-set 格 B/C/D/E split + R-1/R-2 axis
reduction (P5), and 裁定 11's early-exit bypass wiring -- S4
(change_scope_unresolved) / no_spec_unverifiable / spec_level_undetermined
now downgrade to verdict=bypassed/exit 0 and short-circuit when
allow_incomplete_checkpoints=true (change_id_unanchored /
no_spec_contradicted stay hard errors, decision-sheet 2026-09-30 row 11).
TASK-012 (this pass): P6 -- report-attribution matching (proposal.md
§1.2/§1.2b: naming rules 1-3, the bounded-containment exclusion,
top-level-only iterdir() enumeration, the two global exclusion counts),
per-pair three-state judging (§1.3: present / not_applicable(a/b/c) /
missing), stderr trail lines (OK/INFO/ERROR plus the truncated-to-20
unattributed WARN), and the missing-bypass downgrade
(allow_incomplete_checkpoints=true with >=1 missing pair evaluates and
trails every pair first, then downgrades to verdict=bypassed/exit 0 --
not a short-circuit). This is the last TASK in the P0-P6 pipeline.

CLI usage (proposal.md §1, canonical call -- see also detailed-tasks.yaml
metadata.canonical_call)
------------------------------------------------------------------------
    python3 completeness_gate.py \\
        --repo-path <主仓 root> --diff-repo-path <C.2 合并目标仓 root> \\
        --base <diff 仓主干的远程跟踪 ref> [--anchor-base <主仓主干的远程跟踪 ref>] \\
        [--change-id <id> ...] [--no-spec]

stdout contract (proposal.md §1.4 -- exactly one JSON object, 16 keys)
------------------------------------------------------------------------
    schema_version, gate, verdict, error_kind, scope_source, change_ids,
    checked_checkpoints, no_prior_checkpoints, results,
    excluded_legacy_count, unattributed_count, unattributed,
    scanned_dir_depth, scan_status, bypassed, elapsed_ms

All human-readable [OK]/[INFO]/[WARN]/ERROR lines go to stderr only
(proposal.md §1.4 "人读行的输出通道 = stderr"). Exit codes: pass/bypassed
-> 0, fail -> 1, error -> 2 (EXIT_CODES below).
"""

import argparse
import json
import math
import re
import subprocess
import sys
import time
import traceback
from pathlib import Path


# ---------------------------------------------------------------------------
# Inlined config-loader defaults / legacy-compat mapping (SC-21). These are
# deliberately literal copies, not values read off disk at runtime (proposal
# .md §1.4 "为什么反转": config-loader has no programmatic entry point) --
# SC-21(1)/(2) assert equality against the live upstream files at TEST time
# so a future DEFAULTS.json/SKILL.md edit can't silently drift out from
# under this copy without failing a test.
# ---------------------------------------------------------------------------

DEFAULT_AUDIT = {
    "enabled": False,
    "mode": "adaptive",
    "adaptive_rules": {"level_1": "off", "level_2": "convergence", "level_3": "challenge"},
    "checkpoints": {
        "post_brainstorm": "off",
        "post_spec": "off",
        "post_planning": "off",
        "mid_implementation": "off",
        "mid_post_spec": "off",
        "post_implementation": "off",
        "pre_merge": "off",
        "post_closure": "off",
    },
}

LEGACY_CHECKPOINT_MAPPING = {
    "post_spec": "convergence",
    "post_implementation": "convergence",
    "pre_merge": "convergence",
}

STDOUT_SCHEMA_VERSION = "1"
GATE_NAME = "completeness_gate"

# proposal.md §1.4: "任一 missing -> verdict=fail exit 1; 全部 present/
# not_applicable -> verdict=pass exit 0; 豁免 -> verdict=bypassed exit 0;
# 输入/环境错 -> verdict=error exit 2".
EXIT_CODES = {"pass": 0, "bypassed": 0, "fail": 1, "error": 2}

MUTEX_MESSAGE = "--change-id 与 --no-spec 互斥 —— 前者声明本 cycle 有 spec, 后者声明没有"

P1_STDERR_LINE = (
    "[ERROR] completeness gate: audit 未启用 (audit.enabled != true) — "
    "调用方本应在 phase-c-integrator 步骤 2 早退, 到此说明接线断裂"
)

# TASK-009: P2a (--no-spec 输入合法性前置, proposal.md §1.0) 的两个 error_kind。
NO_SPEC_UNVERIFIABLE_LINE = (
    "[ERROR] completeness gate: no_spec_unverifiable — --no-spec 给出, 但锚点面 "
    "(--repo-path + --anchor-base) diff 为 0 行, 无法核验该声明"
)
NO_SPEC_CONTRADICTED_LINE = (
    "[ERROR] completeness gate: no_spec_contradicted — --no-spec 给出, 但锚点面 "
    "diff 触及 openspec/changes/**, 与声明矛盾"
)

# TASK-009: §1.1 S4 (作用域三个来源都不成立) 的 error_kind, 三个 fix 逐字照
# tasks.md 读前必看 第 7 条对第二个 fix 的改写 (「在锚点仓 (主仓) 的分支里
# 带上 openspec/changes/<id>/ 变更」, 覆盖 proposal.md 原写的「在分支里」)。
S4_STDERR_LINE = (
    "[ERROR] completeness gate: change_scope_unresolved — 未能解析 change 作用域 "
    "(无 --change-id, 锚点面 diff 未触及 openspec/changes/**, 也未给 --no-spec)。"
    "三个修法: (1) 传 --change-id <id>; (2) 在锚点仓 (主仓) 的分支里带上 "
    "openspec/changes/<id>/ 变更; (3) 若本 cycle 是 Level 1 (无 spec), 加 --no-spec"
)

# S1 (proposal.md §1.1): 锚点在 openspec/archive/ 下时, 目录名去掉这个日期
# 前缀后必须逐字等于 change_id (不用 glob -- SC-7(b) 锁掉裸 glob 的误命中)。
_ARCHIVE_DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-")


class GateError(Exception):
    """Short-circuits the pipeline with verdict=error, exit 2 (proposal.md
    §1.0 短路语义 type (1)). ``stderr_line`` is the full human-readable
    line for stderr; ``error_kind`` is one of the 9-value closed set in
    proposal.md §1.4's stdout contract."""

    def __init__(self, error_kind, stderr_line):
        super().__init__(error_kind)
        self.error_kind = error_kind
        self.stderr_line = stderr_line


def build_arg_parser():
    """P0 -- argparse 参数契约 (proposal.md §1): --repo-path /
    --diff-repo-path / --base 均 required=True, 无缺省, 不取 cwd;
    --anchor-base 可选 (缺省在 parse_args 里补 = --base); --change-id 可
    重复; --no-spec 是布尔旗标。"""
    parser = argparse.ArgumentParser(
        prog="completeness_gate.py",
        description="Pre-merge change-scope completeness gate.",
    )
    parser.add_argument("--repo-path", required=True, help="锚点仓根 (主仓根)")
    parser.add_argument(
        "--diff-repo-path", required=True,
        help="diff 仓根 (本次 C.2 实际执行合并的仓根); 同仓形态显式传与 --repo-path 相同的值",
    )
    parser.add_argument("--base", required=True, help="diff 仓主干的远程跟踪 ref, 无缺省")
    parser.add_argument(
        "--anchor-base", default=None,
        help="锚点仓主干的远程跟踪 ref; 缺省 = --base",
    )
    parser.add_argument(
        "--change-id", action="append", default=None,
        help="显式作用域 change id, 可重复; 与 --no-spec 互斥",
    )
    parser.add_argument(
        "--no-spec", action="store_true",
        help="声明本 cycle 是 Level 1、无 spec; 与 --change-id 互斥",
    )
    return parser


def parse_args(argv=None):
    """P0 -- 解析并规范化 CLI 参数: --anchor-base 缺省取 --base;
    --change-id 缺省规范化为 []; --change-id/--no-spec 互斥 (argparse 层
    exit 2, 文案逐字 = MUTEX_MESSAGE)。互斥检查必须用原始 (未规范化的)
    args.change_id 求值 -- None 与 [] 在这里语义不同, 规范化放在检查之后。
    ``args.anchor_base_explicit`` (TASK-009 新增) 记录 --anchor-base 是否
    由调用方显式传入 (在缺省填充**之前**求值) -- check_ref_staleness 的
    "同仓且 --anchor-base 缺省时只出一条" 折叠规则需要这个区分, 光看填充
    后的 args.anchor_base == args.base 分不清"缺省"和"显式传了同一个值"。"""
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.change_id and args.no_spec:
        parser.error(MUTEX_MESSAGE)
    args.change_id = args.change_id or []
    args.anchor_base_explicit = args.anchor_base is not None
    if args.anchor_base is None:
        args.anchor_base = args.base
    return args


def load_config(repo_path):
    """P0 -- 直读 <repo_path>/.aria/config.json (proposal.md §1.4 "config
    读取"), 应用旧配置兼容映射 (config-loader/SKILL.md §旧配置兼容层), 再与
    DEFAULT_AUDIT 合并。

    返回 (raw_audit, resolved_audit):
      - raw_audit: "audit" 块本身 (映射生效时是映射合成后的字面值), 未与
        DEFAULT_AUDIT 合并 -- 后续阶段 (TASK-010+) 判定 §1.3 级 1 "audit.
        checkpoints 自身含该键" 时必须读这份原始视图, 不能读 resolved_audit。
      - resolved_audit: raw_audit 与 DEFAULT_AUDIT 合并后的完整视图, 外加
        两个 allow_* 旗标 (缺省 False, 出处 = audit-engine/SKILL.md:385-388
        散文, 两者均不在 DEFAULTS.json 的 audit 键集内) 与 max_rounds (若
        raw_audit 给出)。P1 只读它的 "enabled" 键。

    坏 JSON (语法错误, 或顶层/audit/checkpoints/adaptive_rules 不是 object,
    或某个 checkpoint 的值不是字符串, 或 legacy 映射的
    agent_team_audit_points 不是数组) -> GateError("config_unreadable", ...),
    exit 2 (fail-closed, 刻意与 config-loader 自身"警告 + 返回缺省"的散文不
    同, 见 proposal.md §1.4; 嵌套字段的形状校验是对同一条原则的补齐, 审查
    意见采纳 -- 不校验会在 "**(... or {})" 解包处抛未捕获 TypeError, 以
    exit 1 崩溃, 与 verdict=fail 的契约码相撞)。config 文件缺失 (不是损坏)
    不算错误: raw_audit = {}, resolved_audit.enabled = False, 下游落 P1 的
    格 A。
    """
    config_path = Path(repo_path) / ".aria" / "config.json"
    if config_path.is_file():
        try:
            raw_text = config_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise GateError(
                "config_unreadable",
                f"[ERROR] completeness gate: 读取 {config_path} 失败: {exc}",
            )
        try:
            raw_config = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise GateError(
                "config_unreadable",
                f"[ERROR] completeness gate: {config_path} 不是合法 JSON ({exc})",
            )
        if not isinstance(raw_config, dict):
            raise GateError(
                "config_unreadable",
                f"[ERROR] completeness gate: {config_path} 顶层不是 JSON object",
            )
    else:
        raw_config = {}

    if "audit" in raw_config:
        if not isinstance(raw_config["audit"], dict):
            raise GateError(
                "config_unreadable",
                f"[ERROR] completeness gate: {config_path} 的 audit 字段不是 JSON object",
            )
        raw_audit = dict(raw_config["audit"])
    else:
        # config-loader/SKILL.md §旧配置兼容层 触发条件 (两条同时成立才映射):
        # experiments.agent_team_audit === true 且配置内不存在 audit 块。
        experiments = raw_config.get("experiments")
        agent_team_audit = isinstance(experiments, dict) and experiments.get("agent_team_audit") is True
        if agent_team_audit:
            points = experiments.get("agent_team_audit_points")
            if points is not None and not isinstance(points, list):
                raise GateError(
                    "config_unreadable",
                    f"[ERROR] completeness gate: {config_path} 的 "
                    "experiments.agent_team_audit_points 不是数组",
                )
            mapped_checkpoints = dict(DEFAULT_AUDIT["checkpoints"])
            for point in (points or []):
                if point in LEGACY_CHECKPOINT_MAPPING:
                    mapped_checkpoints[point] = LEGACY_CHECKPOINT_MAPPING[point]
            raw_audit = {"enabled": True, "mode": "manual", "checkpoints": mapped_checkpoints}
        else:
            raw_audit = {}

    # 审查意见 (robust/overfit lens, 对照 load_config 本就对顶层/audit 做过
    # 的同类 object 校验): checkpoints / adaptive_rules 若存在但不是 object
    # (例如 list / 字符串), 下面的 "**(... or {})" 解包会抛未捕获的
    # TypeError, 脚本以 Python 默认的 exit 1 + stdout 空白崩溃 -- exit 1 与
    # verdict=fail 的契约码撞车, 且丢失 error_kind。顶层/audit 不是 object
    # 已经判 config_unreadable, 这里对嵌套的两个子字段同口径补齐; 每个
    # checkpoint 的值若存在但不是字符串 (如 JSON 的 false/null/数字) 同样
    # 判 config_unreadable -- 否则 "resolved_mode == 'off'" 的字符串比较会
    # 对非字符串值恒假, 把一个本意是关闭的 checkpoint 悄悄解释成启用。
    checkpoints_val = raw_audit.get("checkpoints")
    if checkpoints_val is not None:
        if not isinstance(checkpoints_val, dict):
            raise GateError(
                "config_unreadable",
                f"[ERROR] completeness gate: {config_path} 的 audit.checkpoints 不是 JSON object",
            )
        for cp_name, cp_value in checkpoints_val.items():
            if not isinstance(cp_value, str):
                raise GateError(
                    "config_unreadable",
                    f"[ERROR] completeness gate: {config_path} 的 "
                    f"audit.checkpoints.{cp_name} 不是字符串",
                )
    adaptive_rules_val = raw_audit.get("adaptive_rules")
    if adaptive_rules_val is not None and not isinstance(adaptive_rules_val, dict):
        raise GateError(
            "config_unreadable",
            f"[ERROR] completeness gate: {config_path} 的 audit.adaptive_rules 不是 JSON object",
        )

    resolved_audit = {
        "enabled": raw_audit.get("enabled", DEFAULT_AUDIT["enabled"]),
        "mode": raw_audit.get("mode", DEFAULT_AUDIT["mode"]),
        "adaptive_rules": {
            **DEFAULT_AUDIT["adaptive_rules"],
            **(raw_audit.get("adaptive_rules") or {}),
        },
        "checkpoints": {
            **DEFAULT_AUDIT["checkpoints"],
            **(raw_audit.get("checkpoints") or {}),
        },
        # proposal.md §1.4 "两个 allow_* 键的缺省源": 不在 DEFAULTS.json 的
        # audit 键集内, 唯一出处是 audit-engine/SKILL.md:385-388 散文「默认
        # false」。**严格布尔 (审查意见采纳)**: 与 P1 对 "enabled" 的
        # `is not True` 同一口径 -- 字符串 "false" / 整数 1 这类非布尔真值
        # 不得打开这两个逃生口 (在源头归一化, 下游全部消费点因此同步修正,
        # 不需要逐个调用点补判断)。
        "allow_incomplete_checkpoints": raw_audit.get("allow_incomplete_checkpoints", False) is True,
        "allow_dangling_change_ids": raw_audit.get("allow_dangling_change_ids", False) is True,
    }
    if "max_rounds" in raw_audit:
        resolved_audit["max_rounds"] = raw_audit["max_rounds"]

    return raw_audit, resolved_audit


def _decode_git_bytes(raw):
    """git 不保证路径是合法 UTF-8; `text=True` 的严格解码会在非 ASCII/非法
    字节上抛 UnicodeDecodeError, 把本该是 git_failed 的失败变成未捕获崩溃
    (审查意见, 同本仓 phase-c-integrator/scripts/path_coverage.py 的
    10CG/aria-plugin#124 先例, 同一个 surrogateescape 口径)。"""
    return (raw or b"").decode("utf-8", errors="surrogateescape")


def _run_git(repo_path, *args):
    """通用 git 调用 helper: 失败 (进程本身起不来, 或 exit code 非 0) 一律
    转成 GateError("git_failed", ...) -- proposal.md 全文的 git_failed 是
    跨调用点共用的同一个 error_kind, 这里只是它第一个调用点 (同仓判定);
    TASK-009+ 的 merge-base / diff / ref 解析复用同一个 helper。成功时返回
    去掉首尾空白的 stdout (以 bytes 取回后 surrogateescape 解码, 见
    _decode_git_bytes)。"""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_path), *args],
            capture_output=True,
        )
    except OSError as exc:
        raise GateError(
            "git_failed",
            f"[ERROR] completeness gate: git {' '.join(args)} 无法执行 "
            f"(路径 {repo_path}): {exc}",
        )
    if proc.returncode != 0:
        raise GateError(
            "git_failed",
            f"[ERROR] completeness gate: git -C {repo_path} {' '.join(args)} "
            f"失败 (exit {proc.returncode}): {_decode_git_bytes(proc.stderr).strip()}",
        )
    return _decode_git_bytes(proc.stdout).strip()


def resolve_same_repo(repo_path, diff_repo_path):
    """同仓判定 (tasks.md 读前必看 第 30 条: 在 P1 之后求值, 在 ref 解析/陈旧
    比对之前无条件执行)。proposal.md §1 "同仓/跨仓的判定用 git toplevel 归
    一化, 不用字符串相等": 两面 rev-parse --show-toplevel 的输出逐字相等则
    同仓 -- 挡住软链/相对路径/尾斜杠形态差异被误判成跨仓 (或反之)。任一
    rev-parse 失败已由 _run_git 转成 GateError("git_failed", ...)。

    TASK-009 起开始消费这个布尔值 (check_ref_staleness 的折叠判据); 跨仓时
    not_applicable (b) 通道禁止触发等其余消费点仍是 TASK-011+ 的范围。
    """
    toplevel_repo = _run_git(repo_path, "rev-parse", "--show-toplevel")
    toplevel_diff = _run_git(diff_repo_path, "rev-parse", "--show-toplevel")
    return toplevel_repo == toplevel_diff


# ---------------------------------------------------------------------------
# TASK-009: ref resolution + two-base-axis staleness warnings. tasks.md 读前
# 必看 第 30 条 / TASK-009 verification 第 4 条: 这一段排在同仓判定之后、
# P2a 之前, 无条件执行 -- 不管后面 S1->S4 实际走哪一支 (SC-22.3 用 S1 的
# --change-id 路径喂一个解析不出来的 --base 就是在锁这一点: 明明走的是不
# 需要 diff 的 S1, --base 依然必须先能解析)。
# ---------------------------------------------------------------------------

def _try_git_rev_parse(repo_path, ref):
    """尽力解析 <ref> 在 <repo_path> 内的 SHA -- 解析不到 (ref 不存在) 返回
    None 而不抛错。调用方只用它探测"同名远程跟踪 ref 存不存在", 绝大多数
    hermetic fixture 根本没有 origin remote, 那是正常态, 不是错误 (区别于
    --base/--anchor-base 自身解析失败必须 git_failed 的语义, 后者走
    _run_git)。"""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "--verify", "--quiet", ref],
            capture_output=True, text=True,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _stale_ref_warning(axis_name, repo_path, ref, local_sha):
    """proposal.md §1 的 --base 条款: <ref> 不含 '/' 且同名远程跟踪 ref 存在
    且两者 SHA 不同时输出一行 WARN, 逐字点名是哪一根轴 (``axis_name`` =
    "base" 或 "anchor-base")。含 '/' 的 ref (调用方已经传的是远程跟踪 ref
    字面, 如 "origin/master") 结构上不可能"陈旧", 不查。"""
    if "/" in ref:
        return
    origin_ref = f"origin/{ref}"
    origin_sha = _try_git_rev_parse(repo_path, origin_ref)
    if origin_sha is None or origin_sha == local_sha:
        return
    print(
        f"[WARN] {axis_name} ref 陈旧: {ref}={local_sha} != {origin_ref}={origin_sha} "
        "— merge-base 可能偏移, 作用域解析 (S2/S3, 锚点面) 与 not_applicable (b) "
        "通道的路径集判据 (diff 面) 会被弱化",
        file=sys.stderr,
    )


def check_ref_staleness(repo_path, diff_repo_path, base, anchor_base,
                         same_repo, anchor_base_explicit):
    """两根轴各解析一次并各做一次陈旧比对: --base 轴在 diff 仓上 (它是"diff
    仓主干的远程跟踪 ref"), --anchor-base 轴在锚点仓上。解析失败 (ref 不存
    在等) 由 _run_git 统一转成 git_failed exit 2。**同仓且 --anchor-base
    未被显式传入时只做一次** (proposal.md §1: "同仓形态下 --anchor-base
    缺省 = --base ⇒ 只输出一条") -- 这不是去重补丁, 而是此时两轴指向同一个
    仓 + 同一个 ref 字符串, 本就是同一次比对, 用 "base" 命名 (SC-22.1 锁
    这个具体命名: 折叠后仍是 "base ref 陈旧", 不是 "anchor-base ref 陈旧")。
    跨仓时 (same_repo=False) 不折叠, 两轴总是各查一次, 即便字面值恰好相同
    (SC-17.4/17.5 系列的 cross-repo fixture 都没配 origin remote, 两轴各自
    静默跳过, 不产生 WARN, 但仍必须各自解析成功)。"""
    base_sha = _run_git(diff_repo_path, "rev-parse", "--verify", base)
    _stale_ref_warning("base", diff_repo_path, base, base_sha)

    if same_repo and not anchor_base_explicit:
        return

    anchor_sha = _run_git(repo_path, "rev-parse", "--verify", anchor_base)
    _stale_ref_warning("anchor-base", repo_path, anchor_base, anchor_sha)


# ---------------------------------------------------------------------------
# TASK-009: P2a (--no-spec 输入合法性前置) + P2 作用域解析 S1 -> S4
# (proposal.md §1.0 / §1.1)。
# ---------------------------------------------------------------------------

def _anchor_face_diff(repo_path, anchor_base):
    """S2/S3/P2a 共用的"锚点面 diff": git -C <repo_path> diff --name-only
    --no-renames -z $(git -C <repo_path> merge-base HEAD <anchor_base>) 的
    路径列表 (proposal.md §1.1 S2 行给的确切命令, -z 是审查意见补的实现细
    节, 见下)。merge-base 或 diff 本身失败 -> git_failed exit 2 (经
    _run_git 统一转换)。--no-renames: 与姊妹门 path_coverage
    (phase-c-integrator/SKILL.md:252) 对齐, 防纯归档移动的 PR 在 rename 检
    测开启时只报告目的侧路径 (§1.1 S2 行的论证)。**-z (审查意见采纳,
    phase-c-integrator/scripts/path_coverage.py 10CG/aria-plugin#124 同型
    先例)**: 不加 -z
    时 git 对非 ASCII 路径按 core.quotePath 转义成带引号的八进制转义串
    (如 "openspec/changes/foo/\\351\\231\\204.md"), split("/") 的首段会变
    成带引号的 "openspec, 使 S2/P2a 的路径前缀判断结构性失配 (P2a 的矛盾
    检测漏判 -> --no-spec 下误判无矛盾放行; S2 漏掉该 id)。-z 以 NUL 分隔
    且路径逐字节原样输出, 不受 core.quotePath 影响; 本仓语料当前 0 个非
    ASCII 路径, 属面向未来的健壮性修复, 不改变现有行为。"""
    merge_base = _run_git(repo_path, "merge-base", "HEAD", anchor_base)
    diff_output = _run_git(repo_path, "diff", "--name-only", "--no-renames", "-z", merge_base)
    # -z: NUL 分隔且非空输出带尾随 NUL; 滤空串同时处置尾随 NUL 与空 diff
    # 的 [""] (与 path_coverage.py 的同型注释同一口径)。
    return [token for token in diff_output.split("\0") if token]


def _extract_change_ids_from_diff(diff_paths):
    """从 diff 路径集里取 "openspec/changes/<id>/" 前缀, 去重 (不排序 --
    排序与否由调用方决定; S2 对外输出排序, 供 change_ids 字段确定性呈现)。
    **len(parts) >= 4 (审查意见采纳, 修正原先的 >= 3)**: 前缀
    "openspec/changes/<id>/" 本身要求 <id> 之后还有至少一层路径段 (该目录
    下的某个文件), 否则 openspec/changes/ 顶层的直属文件 (如 .gitkeep、
    README.md -- 本仓 state-scanner collectors/openspec.py:332 就建议写
    .gitkeep 维持空目录) 会被当成一个 change id, 对它求 missing 产生假红。
    "触及 openspec/changes/** (含顶层直属文件)" 这个更宽的判据另见
    _diff_touches_changes_dir, 两者原先共用本函数 (len>=3), P2a 那边"蒙对"
    是因为它只看"有没有 id", 不看 id 具体是什么。"""
    ids = set()
    for path in diff_paths:
        parts = path.split("/")
        if len(parts) >= 4 and parts[0] == "openspec" and parts[1] == "changes":
            ids.add(parts[2])
    return ids


def _diff_touches_changes_dir(diff_paths):
    """P2a 的 (iii) 矛盾检测 (proposal.md §1.1 S3(iii) / §1.0 P2a): 锚点面
    diff 是否触及 openspec/changes/** -- 这是比 _extract_change_ids_from_diff
    更宽的纯前缀判据 (不要求 <id> 后面还有路径段), 刻意拆成独立函数 (审查
    意见采纳): 原先两处共用 _extract_change_ids_from_diff, S2 收紧到
    len(parts)>=4 之后, 若 P2a 继续复用同一个函数, "diff 只碰
    openspec/changes/README.md" 这种形态会被判成"没有触及" (ids 为空集),
    与 S3(iii) "不触 openspec/changes/**" 的字面范围 (含顶层直属文件) 不
    符。"""
    return any(path.startswith("openspec/changes/") for path in diff_paths)


def _find_anchor(repo_path, change_id):
    """S1 锚点判定 (proposal.md §1.1 S1 行): openspec/changes/<id>/
    proposal.md, 或 openspec/archive/ 下**目录名去掉日期前缀后逐字等于**
    <id> 的目录里的 proposal.md。**逐字比对, 不用 glob** (R2 rework 收窄,
    SC-7(b) 锁掉裸 glob 对 "aria-orchestrator-divestiture" 误判
    "orchestrator" 有锚的反例)。TASK-010 起委托给 _find_proposal_path (P3
    的 Level 解析需要同一套判据的路径版本, 而不只是布尔值) -- 判据只在
    _find_proposal_path 里写一份, 这里与那里改一处就同步。"""
    return _find_proposal_path(repo_path, change_id) is not None


def resolve_via_explicit_ids(repo_path, change_ids, allow_dangling):
    """S1 (proposal.md §1.1): 每个显式 --change-id 必须有锚点; 无锚且
    allow_dangling_change_ids=false -> change_id_unanchored exit 2 (拼写错
    不能变成假红也不能变成假绿); 为 true 时降为 [WARN] 并按"该 id 零报告"
    继续 (dangling 集合原样回传, WARN 的 "Level 不可解析" 加长变体属于 P3/
    P4 的 Level+优先级链判定, 见 TASK-010, 这里只发 S1 自己这条通用告警)。
    保序去重 (dedup 后保留 CLI 给出的相对顺序; --change-id 语义上是一个显
    式集合, 顺序不是判据, 保序只是为了确定性和可读性)。"""
    ids, dangling, seen = [], set(), set()
    for cid in change_ids:
        if cid in seen:
            continue
        seen.add(cid)
        if _find_anchor(repo_path, cid):
            ids.append(cid)
            continue
        if allow_dangling:
            print(
                f"[WARN] dangling change_id: {cid} (allow_dangling_change_ids=true)",
                file=sys.stderr,
            )
            ids.append(cid)
            dangling.add(cid)
            continue
        raise GateError(
            "change_id_unanchored",
            "[ERROR] completeness gate: change_id_unanchored — --change-id "
            f"{cid} 在锚点仓内无对应锚点 (openspec/changes/{cid}/proposal.md, "
            "或 openspec/archive/ 下目录名去掉日期前缀后逐字等于该 id 的目录"
            "里的 proposal.md)",
        )
    return ids, dangling


def check_no_spec_precondition(repo_path, anchor_base):
    """P2a (proposal.md §1.0, R4 rework `a657bf0a`): --no-spec 给出时必须
    早于 P2 (S1->S4) 求值, 否则同仓下 S2 的 first-match 会先吃掉矛盾检测
    (§1.1b 判定表第 1 行)。在锚点面求 S3 的 (ii)(iii): diff 为 0 行 ->
    no_spec_unverifiable; 触 openspec/changes/** -> no_spec_contradicted。
    两者都不放行, 且**不受任何 allow_* 键豁免** (那是 TASK-011 的 P5 才接
    线的降级, 本阶段一律硬阻)。返回锚点面 diff, 供 P2 的 S2/S3 原样复用
    (同一次 git 调用, 不重算)。"""
    anchor_diff = _anchor_face_diff(repo_path, anchor_base)
    if len(anchor_diff) == 0:
        raise GateError("no_spec_unverifiable", NO_SPEC_UNVERIFIABLE_LINE)
    if _diff_touches_changes_dir(anchor_diff):
        raise GateError("no_spec_contradicted", NO_SPEC_CONTRADICTED_LINE)
    return anchor_diff


def resolve_scope(args, resolved_audit, anchor_diff_from_p2a):
    """P2, §1.1 S1 -> S4 (first-match)。返回 (scope_source, change_ids,
    dangling_ids); P3 (Level) / P4 (优先级链) / P5 / P6 是后续 TASK 的范围,
    这里只产出 §1.1 本身定义的三个量。"""
    if args.change_id:
        ids, dangling = resolve_via_explicit_ids(
            args.repo_path, args.change_id,
            resolved_audit["allow_dangling_change_ids"],
        )
        return "explicit", ids, dangling

    anchor_diff = (
        anchor_diff_from_p2a if anchor_diff_from_p2a is not None
        else _anchor_face_diff(args.repo_path, args.anchor_base)
    )
    diff_ids = sorted(_extract_change_ids_from_diff(anchor_diff))
    if diff_ids:
        return "diff", diff_ids, set()

    if args.no_spec:
        # S3: P2a 已经核验过 anchor_diff_from_p2a 非空且不触
        # openspec/changes/** (否则早就在 P2a 里 exit 2 了), 这里 first-match
        # 落到 S3 即代表三条核验全过。
        return "no_spec", [], set()

    raise GateError("change_scope_unresolved", S4_STDERR_LINE)


# ---------------------------------------------------------------------------
# TASK-010: P3 (按需 Level 解析, proposal.md §1.3 判据 1-3) + P4 (五档优先级
# 链、五项排除、逐对纳入、dangling-skip)。§1.0 求值总序: Level 只在某
# (checkpoint, change_id) 对于 P4 落到级 2a 时才对该 change 求值 (lazy, 不
# eager) -- _LevelCache 把"按需"与"同一个 change_id 在本次运行内只解析一次"
# 两条都做成机械保证, 不依赖调用方自己记得别重复调用。
# ---------------------------------------------------------------------------

# proposal.md §1.3 "Step 3 枚举 (:46-52) 追加一条排除": 五项排除 (裁定 1,
# tasks.md 读前必看 第 6 条) -- pre_merge 自身 + 三个"启用但条件触发, 合法
# 不产出报告"的 checkpoint (post_closure / mid_post_spec / mid_implementation)
# + post_brainstorm (裁定 1 新增, 与 mid_post_spec 同因)。这五项不进 Step 3
# 的逐 checkpoint 枚举, 但 resolve_checkpoint_mode() 本身对它们同样适用 --
# P5 需要单独对 pre_merge 求 resolved_mode/enabled_by (§1.4 格 B-E), 属
# TASK-011 范围。
EXCLUDED_CHECKPOINTS = frozenset({
    "pre_merge", "post_closure", "mid_post_spec", "mid_implementation", "post_brainstorm",
})

# resolve_inclusion() 的逐 checkpoint 枚举全集 (8 个已知 checkpoint 去掉五
# 项排除 = 3 个), 供 _explicit_only_checked_checkpoints() 复用同一个取值
# 范围 (审查意见采纳, 见该函数文档字符串)。
_KNOWN_NON_EXCLUDED_CHECKPOINTS = frozenset(DEFAULT_AUDIT["checkpoints"]) - EXCLUDED_CHECKPOINTS

# proposal.md §1.3 判据 2 "字段形态集": 行首去掉这一串字符 (str.lstrip 的
# 字符集语义 -- 任意组合/顺序, 直到遇到不在此集合里的字符为止, 不是逐个
# 类型分别处理) 后再判断是否以 "Level" / "Spec Level" 开头。
_LEVEL_LINE_STRIP_CHARS = " \t\r\n\v\f>-#*"
_LEVEL_STRIKETHROUGH_RE = re.compile(r"~~.*?~~")
_LEVEL_DIGIT_RE = re.compile(r"[123]")


def _match_level_line(line):
    """单行是否命中 §1.3 判据 2 的字段形态; 命中则返回冒号之后的原始子串
    (未剥删除线 -- 剥线是"取值"阶段的事, 见 _extract_level_value), 否则
    None。大小写敏感 (判据 2 逐字"大小写敏感"), 半角 ':' 或全角 '：' 都认。
    "Spec Level" 先试 (两者本就互斥: 以 "Spec Level" 开头的字符串不可能同时
    以 "Level" 开头, 首字符不同, 顺序只是贴合正文"Level 或 Spec Level"的
    可读性, 不影响正确性)。"""
    rest = line.lstrip(_LEVEL_LINE_STRIP_CHARS)
    for keyword in ("Spec Level", "Level"):
        if rest.startswith(keyword):
            rest = rest[len(keyword):]
            break
    else:
        return None
    if rest.startswith("**"):
        rest = rest[2:]
    if rest[:1] in (":", "："):  # 半角 ':' 或全角 '：'
        return rest[1:]
    return None


def _extract_level_value(text_after_colon):
    """判据 2 的"取值"阶段: 先剥掉全部 ~~...~~ 删除线片段 (非贪婪; proposal
    .md 举的真实语料样本 `~~2 (proposal only)~~ → **3**` 只有一段, 但正则
    本身不假设至多一段), 再取剩余文本里第一个 1/2/3 字符。取不到返回
    None。"""
    cleaned = _LEVEL_STRIKETHROUGH_RE.sub("", text_after_colon)
    m = _LEVEL_DIGIT_RE.search(cleaned)
    return int(m.group()) if m else None


def parse_level(proposal_text):
    """P3, proposal.md §1.3 判据 1+2: **全文件扫描, 不设 head-window**, 取
    "文档序第一条命中行" (单数 -- 命中行存在但取不出数字时视为整体解析
    失败, 不回退去找文档里后面可能存在的第二条候选行)。找不到命中行, 或
    命中行取不出数字, 一律返回 None (调用方按 None 触发
    spec_level_undetermined 或 dangling-skip, 见 _LevelCache.resolve)。"""
    for line in proposal_text.splitlines():
        after_colon = _match_level_line(line)
        if after_colon is not None:
            return _extract_level_value(after_colon)
    return None


def _find_change_dir(repo_path, change_id):
    """定位 change_id 对应的目录 (openspec/changes/<id>/ 本身, 或
    openspec/archive/ 下目录名去掉日期前缀后逐字等于 <id> 的目录), 不要求
    其中有 proposal.md -- (c) 通道 (_has_a2_artifact, 审查意见采纳) 需要在
    proposal.md 缺失时仍能检查 tasks.md/detailed-tasks.yaml 是否存在, 而
    不是"没有 proposal.md 就当整个 change 不存在"。找不到返回 None。

    **拒绝非单段 change_id (审查意见采纳)**: change_id 必须逐字等于
    Path(change_id).name, 否则一律视为找不到 -- change_id 含 "/" 或 "\\\\"、
    是 "." 或 ".." 时, 下面的 Path 拼接 (pathlib 的 "/" 运算符) 会把它当成
    多段路径甚至 (绝对路径时) 整段替换掉前面的 repo_path/openspec/changes
    前缀, 使本应判 change_id_unanchored 的拼写错改落到 repo 之外的任意路
    径上; S1 判据原文"目录名逐字等于 change_id"本就要求单段比较, 这里只
    是提前短路, 不新增 error_kind。"""
    if change_id != Path(change_id).name:
        return None
    direct = Path(repo_path) / "openspec" / "changes" / change_id
    if direct.is_dir():
        return direct
    archive_root = Path(repo_path) / "openspec" / "archive"
    if not archive_root.is_dir():
        return None
    for entry in sorted(archive_root.iterdir()):
        if not entry.is_dir():
            continue
        if _ARCHIVE_DATE_PREFIX_RE.sub("", entry.name) == change_id:
            return entry
    return None


def _find_proposal_path(repo_path, change_id):
    """定位 change_id 的 proposal.md (S1 锚点判据的路径版本, proposal.md
    §1.1 S1 行): openspec/changes/<id>/proposal.md, 否则 openspec/archive/
    下目录名去掉 ``^\\d{4}-\\d{2}-\\d{2}-`` 日期前缀后**逐字等于** <id> 的
    目录里的 proposal.md。找不到返回 None。_find_anchor() (S1, 只需要布尔
    值) 与 P3 的 Level 解析 (需要路径去读内容) 共用这一份判据; 目录定位委
    托给 _find_change_dir (含 change_id 单段校验)。"""
    change_dir = _find_change_dir(repo_path, change_id)
    if change_dir is None:
        return None
    candidate = change_dir / "proposal.md"
    return candidate if candidate.is_file() else None


def _parse_level_for_change(repo_path, change_id):
    """找不到锚点、读不了文件、或文件里解析不出 Level, 统一返回 None --
    proposal.md §1.1 末段"allow_dangling_change_ids=true 时 Level 解析失败
    与锚点缺失走同一条降级路径": 调用方 (_LevelCache) 不需要, 也不应该,
    区分这两种"None"的成因。"""
    path = _find_proposal_path(repo_path, change_id)
    if path is None:
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    return parse_level(text)


def _spec_level_undetermined_line(change_id):
    return (
        "[ERROR] completeness gate: spec_level_undetermined — change "
        f"{change_id} 的 proposal.md 未能解析出可用的 Level 字段, 无法在 "
        "adaptive 档为未显式配置的 checkpoint 推导启用状态。两个修法: "
        "(1) 在 proposal 头部补 `> **Level**:` 行 (`Spec Level` 亦可, 半角"
        "/全角冒号均可); (2) 在 audit.checkpoints 里显式写该 checkpoint"
    )


def _config_unreadable_mode_line(mode):
    return (
        f"[ERROR] completeness gate: config_unreadable — audit.mode 的值 "
        f"{mode!r} 不属于四值枚举 (adaptive / convergence / challenge / "
        "manual), 无法确定未显式配置的 checkpoint 该走优先级链的哪一档 "
        "(proposal.md §1.3 级 3)"
    )


class _LevelCache:
    """P3 的"按需 + 记忆化": 同一个 change_id 在同一次运行内的 Level 解析
    结果 (或 dangling-skip 判定) 只计算一次, 无论后面有多少个 checkpoint
    落到级 2a 都复用; dangling change_id 的 [WARN] 也因此天然只发一次
    (proposal.md §1.1 末段"该 id"是单数, 不是每个 checkpoint 各发一条)。"""

    def __init__(self, repo_path, allow_dangling_change_ids):
        self._repo_path = repo_path
        self._allow_dangling = allow_dangling_change_ids
        self._cache = {}
        self._warned = set()

    def resolve(self, change_id):
        """返回 (dangling, level)。``change_id=None`` 是 §1.1 S3
        "--no-spec ⇒ Level 视为 1" 的专用通道 (无 change_id 可读文件, 也
        不需要 -- P3 判据 3), 不参与下面的缓存/告警逻辑。dangling=True 时
        level 恒 None, 调用方 (resolve_checkpoint_mode) 按
        resolved_mode='off' / enabled_by='dangling-skip' 处理。
        allow_dangling_change_ids=false 时解析失败不会走到这个分支 -- 直接
        在这里 raise GateError('spec_level_undetermined', ...), 短路整个
        求值 (proposal.md §1.3 "解析不到 ⇒ error_kind=spec_level_undetermined,
        exit 2")。"""
        if change_id is None:
            return False, 1

        if change_id in self._cache:
            return self._cache[change_id]

        level = _parse_level_for_change(self._repo_path, change_id)
        if level is not None:
            result = (False, level)
        elif self._allow_dangling:
            if change_id not in self._warned:
                print(
                    f"[WARN] dangling change_id: {change_id} — Level 不可解析, "
                    "跳过 adaptive 推导",
                    file=sys.stderr,
                )
                self._warned.add(change_id)
            result = (True, None)
        else:
            raise GateError(
                "spec_level_undetermined", _spec_level_undetermined_line(change_id),
            )

        self._cache[change_id] = result
        return result


def resolve_checkpoint_mode(checkpoint, change_id, raw_audit, resolved_audit, level_cache,
                             dangling_ids=frozenset()):
    """§1.3 的五档优先级链, per (checkpoint, change_id)。返回 (resolved_mode,
    enabled_by)。**级 1 对 raw_audit 求值** (原始 config 的
    audit.checkpoints 自身是否含该键, 未与 DEFAULT_AUDIT 合并的那份视图);
    **2a/2b/2c/2d/3 对 resolved_audit 求值** (合并 DEFAULTS + 旧配置兼容
    映射 + 内联缺省之后的视图) -- proposal.md §1.3 表头"钉死"那一段, 两份
    视图不能混用。只有落到级 2a (mode=='adaptive' 且该 checkpoint 未被显式
    配置) 才会调用 level_cache.resolve(change_id), 这是全函数唯一读 change
    自身数据 (proposal.md) 的地方, 对应 P3 的"按需"。

    ``dangling_ids`` (审查意见采纳, TASK-010 verification 第 5 条 "allow_
    dangling_change_ids 为 true 且锚点缺失或 Level 不可解析 ⇒ 该 id 的非
    explicit 对取 resolved_mode off 与 enabled_by dangling-skip" -- 该句
    没有把"锚点缺失"限定在 adaptive 档): S1 在锚点缺失时已经知道某个
    change_id 是 dangling (与 mode 无关, 见 resolve_via_explicit_ids), 原
    实现只在 mode=='adaptive' 分支里问过 level_cache (它会重新发现"无锚点
    即 Level 不可解析"), convergence/challenge/manual 三档从未查过这个已
    知集合, 对 dangling id 的非 explicit checkpoint 原样按该 mode 的正常
    值处理 (如 manual 档混同成 manual-default, convergence 档混同成
    mode:convergence) -- 两者多数情况下恰好同为 "off"、无可观测差异,
    但在 resolve_pre_merge_axes 的格 C/E 判定上会错判 (manual-default 落
    格 C 硬阻 exit 2, 而本该按 owner 显式打开的降级路径落格 E pass)。此处
    在查 mode 之前先查这个显式集合, 不吃掉 adaptive 分支自己的 WARN (该
    分支独立发现 dangling 时仍打印"Level 不可解析"那条, 两条路径不重复)。
    缺省空集, 对未传此参数的既有调用点 (如仍在用的测试内部探针) 行为不
    变。"""
    raw_checkpoints = raw_audit.get("checkpoints") or {}
    if checkpoint in raw_checkpoints:
        return raw_checkpoints[checkpoint], "explicit"

    mode = resolved_audit["mode"]
    if mode == "adaptive":
        dangling, level = level_cache.resolve(change_id)
        if dangling:
            return "off", "dangling-skip"
        return resolved_audit["adaptive_rules"][f"level_{level}"], f"adaptive:level_{level}"
    if change_id in dangling_ids:
        return "off", "dangling-skip"
    if mode == "convergence":
        return "convergence", "mode:convergence"
    if mode == "challenge":
        return "challenge", "mode:challenge"
    if mode == "manual":
        return "off", "manual-default"

    raise GateError("config_unreadable", _config_unreadable_mode_line(mode))


def resolve_inclusion(change_ids, raw_audit, resolved_audit, level_cache,
                       dangling_ids=frozenset()):
    """P4: 对每个 change_id x 每个非排除 checkpoint 求 resolved_mode /
    enabled_by, resolved_mode != 'off' 才纳入。**逐对, 不叉乘** (tasks.md
    读前必看"迭代口径=逐对" / SC-20(7)): 每个 change 自己的纳入集互相独立,
    某 checkpoint 对 change A 纳入、对 change B 是 off, 只会给 A 产生一条
    pair。返回 (checked_checkpoints, pairs): 前者是各 change 纳入集的并集,
    sorted() 字典序; 后者只含真正纳入的 (checkpoint, change_id) 对, 每条
    携带 resolved_mode 与 enabled_by, 供 P5/P6 消费 (空集分格、报告归属匹配、
    三态判定、路由)。**change_ids 为空时哨兵求值一次** (TASK-012 补, 与
    resolve_pre_merge_axes 的 R-3 同一条判据): 结构上只有 --no-spec 会让
    change_ids 为 [] 还继续往下走 (S4-bypassed 在 resolve_scope 内部已经
    raise, 根本不会调用到这里) -- §1.1 S3 "Level 视为 1 (供 §1.3 Step 3 的
    adaptive 推导用)" 这句话管的是 Step 3 的全部 checkpoint, 不只是
    resolve_pre_merge_axes 单独处理的 pre_merge 一项, 所以这里同样要用
    change_id=None 求值一次, 不能让"没有 change_id"等价于"没有任何
    checkpoint 可被纳入"。level_cache.resolve(None) 已经把 None 当专用哨
    兵处理 (直接给 Level=1, 不缓存、不告警), 这里不需要再判空。"""
    checkpoints = sorted(_KNOWN_NON_EXCLUDED_CHECKPOINTS)
    checked = set()
    pairs = []
    for change_id in (change_ids if change_ids else [None]):
        for checkpoint in checkpoints:
            resolved_mode, enabled_by = resolve_checkpoint_mode(
                checkpoint, change_id, raw_audit, resolved_audit, level_cache, dangling_ids,
            )
            if resolved_mode == "off":
                continue
            checked.add(checkpoint)
            pairs.append({
                "checkpoint": checkpoint,
                "change_id": change_id,
                "resolved_mode": resolved_mode,
                "enabled_by": enabled_by,
            })
    return sorted(checked), pairs


# ---------------------------------------------------------------------------
# TASK-011: P5 (纳入集为空时的格 B/C/D/E, proposal.md §1.4) 与裁定 11 的三类
# 早退豁免 (S4 / no_spec_unverifiable / spec_level_undetermined 在
# allow_incomplete_checkpoints=true 下降为 bypassed/exit 0 并短路, tasks.md
# 读前必看 第 7/8 条)。
# ---------------------------------------------------------------------------

# 读前必看 第 7 条 (裁定 11): allow_incomplete_checkpoints 覆盖的三类早退
# error_kind -- 全部严格发生在 load_config() 成功返回之后 (P2a/P2/P3), 短路
# 语义由"异常直接终止 main() 的 try 块"天然实现, 这里只需要在 except 分支按
# error_kind 改判。change_id_unanchored / no_spec_contradicted 刻意不在这个
# 集合里 (决策单第 11 行: 两个 allow_* 都不救, 输入矛盾/核验面本身不可用都
# 不是"不完整")。
BYPASSABLE_EARLY_EXIT_KINDS = frozenset({
    "change_scope_unresolved", "no_spec_unverifiable", "spec_level_undetermined",
})

# TASK-011 verification 第 3 条 "S4 与 no_spec_unverifiable 取 1": 这两类早
# 退发生于 P2 作用域解析成功之前 (S4 本身就是解析失败; no_spec_unverifiable
# 发生于更早的 P2a), 统一 WARN 行的 scope_unresolved 置 1。
# spec_level_undetermined 发生于 P3, 此时 P2 已经成功解析出 change_ids --
# "作用域"本身是已解析的, 只是 Level 不可解析, 故取 0。
SCOPE_UNRESOLVED_KINDS = frozenset({"change_scope_unresolved", "no_spec_unverifiable"})

# 同条: 这两类豁免时在统一 WARN 行之后另加一行 "[WARN] bypassed: <error_kind>"
# (S4 没有这一行 -- 它的留痕就是统一 WARN 行本身, 这是 §1.1 末段原有定义;
# 这一行是裁定 11 新加的)。
EXTRA_BYPASS_WARN_KINDS = frozenset({"no_spec_unverifiable", "spec_level_undetermined"})


def _explicit_only_checked_checkpoints(raw_audit):
    """tasks.md 读前必看 第 8 条 (v2.2 扩至三类早退, TASK-011 verification 第
    4 条): S4 / no_spec_unverifiable / spec_level_undetermined 被豁免为
    bypassed 时, checked_checkpoints **不取"已产出值"** (那个写法由实现装配
    该字段的时机决定, 两个字面合规的实现会给不同值, post_planning R2
    PP2-M5) -- 一律只收**原始** config 的 audit.checkpoints 里显式写出、值
    非 "off" 且不属 EXCLUDED_CHECKPOINTS 五项排除的键, sorted() 输出。

    **取值范围按 cp 是否属于已知 checkpoint 名集过滤 (审查意见采纳)**:
    原实现直接遍历 raw_checkpoints 自己的键, 一个拼写错的键 (如
    "post_spce") 只要值非 "off" 就会被收进来 -- 与 resolve_inclusion() 的
    正常路径 (遍历 _KNOWN_NON_EXCLUDED_CHECKPOINTS 这个已知名集, 反向查
    raw_checkpoints 是否含该键) 取值范围不一致: 同一份 config, 正常路径
    下该拼写错的键从不会被查到 (不在已知名集里, 循环压根不会问它), 但走
    这条 explicit-only 分支却会把它纳入输出, 对同一个字段给出两种口径。"""
    raw_checkpoints = raw_audit.get("checkpoints") or {}
    return sorted(
        cp for cp, value in raw_checkpoints.items()
        if value != "off" and cp in _KNOWN_NON_EXCLUDED_CHECKPOINTS
    )


def _bypass_warn_line(missing_entries, scope_unresolved):
    """proposal.md §1.4 "豁免文案" (`execution-modes.md:82` 字面, 统一拼法,
    R1 勘正已删掉的第三种拼法不复用)。``missing_entries`` 是
    "{checkpoint}@{change_id}" 字符串列表, 半角逗号连接; TASK-011 的三类早
    退短路于 P4 产出 missing 对之前, 这里恒传 []  (留参数给 TASK-012 的
    "missing 被豁免" 复用, 不是本任务需要非空值)。"""
    return (
        f"[WARN] incomplete checkpoint gate bypassed: missing={','.join(missing_entries)} "
        f"; scope_unresolved={scope_unresolved}"
    )


def _render_change_id(change_id):
    """proposal.md §1.1 S3 "无 change_id" 渲染惯例 (trail 行写 `{cp} (无
    change_id)` 而非 `{cp}@None`) 在格 D/E 的逐 change trail 行里复用 --
    change_id 只有在 --no-spec 路线上才可能是 None (R-3)。"""
    return change_id if change_id is not None else "(无 change_id)"


_NO_PRIOR_CHECKPOINTS_PREFIX = (
    "[INFO] completeness gate: 无前置 checkpoint 纳入校验 (checked_checkpoints=[]) — "
)

# 格 B (proposal.md §1.4 表, R4 rework 删第四合取项后): 逐字字面, SC-15.3
# 断言子串 "无前置 checkpoint 纳入校验" + "[INFO]"。
BUCKET_B_INFO_LINE = (
    _NO_PRIOR_CHECKPOINTS_PREFIX
    + "依 audit.checkpoints/adaptive_rules 的配置放行 (Rule #10 白名单第一类"
    "「配置显式关闭」, configured-gate-authority.md:35), 非零证据判绿"
)

# 格 C (proposal.md §1.4 表): 两道启用守卫本可用 checkpoints 显式键判定此
# 格; SC 未锁定逐字文案 (只锁 error_kind/verdict/exit code), 这里按既有
# error_kind 行的措辞风格写。
BUCKET_C_STDERR_LINE = (
    "[ERROR] completeness gate: pre_merge_not_enabled — audit.enabled=true 但纳入"
    "集为空, 且 pre_merge 本身在作用域内全部 change 上都解析为 \"off\" "
    "(enabled_by 属于 explicit/manual-default, 两道启用守卫本可预判) — 调用方 "
    "phase-c-integrator 步骤 3 与 audit-engine 入口本应早退, 到此确系接线断裂"
)


def _bucket_d_info_line(change_id, level):
    """格 D (proposal.md §1.4 表): adaptive_rules 推导出 pre_merge=="off",
    两道启用守卫无法预判 (不知道被审 change 的 Level)。逐 change 各出一行
    (SC-15(9) 锁 "不是叉乘混出来的单值")。"""
    return (
        _NO_PRIOR_CHECKPOINTS_PREFIX
        + f"pre_merge 对 change {_render_change_id(change_id)} 由 "
        f"adaptive_rules.level_{level} 推导为 \"off\" (该 change 是 Level {level}), "
        "两道启用守卫结构上无法预判此格, 非接线断裂; 依配置放行 (Rule #10 白名单第一"
        "类), 非零证据判绿"
    )


def _bucket_e_info_line(change_id):
    """格 E (proposal.md §1.4 表): allow_dangling_change_ids 跳过了该
    change 的 adaptive 推导。该 id 已有的 "[WARN] dangling change_id: …" 行
    (由 _LevelCache 发出) 保留, 这里逐 change 各加一行 INFO。"""
    return (
        _NO_PRIOR_CHECKPOINTS_PREFIX
        + f"change {_render_change_id(change_id)} 的 adaptive 推导已因 "
        "allow_dangling_change_ids 跳过, pre_merge 取 \"off\"; 依 owner 显式开启的"
        "降级路径放行 (Rule #10 白名单第一类), 非零证据判绿"
    )


def resolve_pre_merge_axes(change_ids, raw_audit, resolved_audit, level_cache,
                            dangling_ids=frozenset()):
    """P5 的前置归约 (proposal.md §1.4 "前置归约" + R-1/R-2/R-3)。pre_merge
    自身是 EXCLUDED_CHECKPOINTS 成员, resolve_inclusion() 的逐 checkpoint
    循环永远不碰它 -- 格 B/C/D/E 的判据要单独对它求 resolved_mode/
    enabled_by, 复用同一个 resolve_checkpoint_mode()/level_cache (按需 +
    记忆化不变, 不会对已在 P4 解析过 Level 的 change 重复发 WARN)。

    返回 (reduced_off, bucket, per_change):
      - reduced_off: R-1 存在量化归约后 resolved(pre_merge) 是否 "off" --
        作用域内任一 change 非 off 即 False (落格 B, 此时 bucket 固定为
        None, 调用方不应该看它)。
      - bucket: 仅当 reduced_off 为 True 才有意义, R-2 可预判性优先归约出
        的桶名 "C" / "D" / "E"。
      - per_change: [(change_id, resolved_mode, enabled_by), ...], 按
        change_ids 给出的顺序, 供格 D/E 的逐 change trail 行使用。

    R-3 (作用域为空的两种来源): S4-bypassed 已在 main() 短路, 不会调用本函
    数; 唯一能让 change_ids 为空却仍走到这里的是 --no-spec (scope_source
    == "no_spec")。此时"存在量化"不能对空集合求值 (vacuous truth 会把
    reduced_off 错判成 True 而不实际求值) -- 改用哨兵 change_id=None 求值
    一次, level_cache.resolve(None) 直接给 (False, 1) ("Level 视为 1",
    §1.1 S3 同一条判据, 不是另起一套), 不需要"存在量化", 因为本就只有一个
    值。"""
    targets = change_ids if change_ids else [None]
    per_change = [
        (cid,) + resolve_checkpoint_mode(
            "pre_merge", cid, raw_audit, resolved_audit, level_cache, dangling_ids,
        )
        for cid in targets
    ]

    reduced_off = all(mode == "off" for _, mode, _ in per_change)
    if not reduced_off:
        return False, None, per_change

    enabled_bys = {enabled_by for _, _, enabled_by in per_change}
    if any(eb.startswith("adaptive:level_") for eb in enabled_bys):
        bucket = "D"
    elif "dangling-skip" in enabled_bys:
        bucket = "E"
    else:
        bucket = "C"
    return True, bucket, per_change


# ---------------------------------------------------------------------------
# TASK-012: P6 (报告归属匹配 + 三态判定 + 路由, proposal.md
# §1.2/§1.2b/§1.3/§1.4)。四段: 命名规则 1-3 + 顶层枚举 (本段), (b)/(c) 的
# not_applicable 判据, stderr trail 行模板, 最后是把三者接起来的编排函数
# run_completeness_check() (main() 在 checked_checkpoints 非空时调用它)。
# ---------------------------------------------------------------------------


def _collect_known_change_ids(repo_path):
    """proposal.md §1.2 规则 3 的 C 集: openspec/changes/* 的目录名, 并上
    openspec/archive/* 的目录名去掉 ^YYYY-MM-DD- 日期前缀 (复用 S1/P3 共用
    的 _ARCHIVE_DATE_PREFIX_RE, 不重复定义正则)。两个目录都只取顶层
    iterdir(), 都不存在时返回空集 (不是错误 -- 首次启用的仓本就可能两个都
    没有)。"""
    ids = set()
    changes_root = Path(repo_path) / "openspec" / "changes"
    if changes_root.is_dir():
        ids.update(entry.name for entry in changes_root.iterdir() if entry.is_dir())
    archive_root = Path(repo_path) / "openspec" / "archive"
    if archive_root.is_dir():
        ids.update(
            _ARCHIVE_DATE_PREFIX_RE.sub("", entry.name)
            for entry in archive_root.iterdir() if entry.is_dir()
        )
    return ids


def _list_top_level_report_names(repo_path):
    """proposal.md §1.2b: 只扫 <repo_path>/.aria/audit-reports/ 顶层
    (iterdir(), 不是 rglob()), 子目录内的文件不计入完整性证据。目录不存在
    时视为零份报告 (proposal.md §1.4 "报告目录不存在"), 在这里发出那条
    stderr WARN (SC-22(2) 锁逐字) 并返回空列表 -- 调用方不需要再区分"目录
    缺失"与"目录为空"这两种都给零文件名列表的情形, scan_status 由 main()
    另外调用 _scan_status() 独立给出, 与这里的 WARN 正交。sorted() 使后续
    legacy/unattributed 分类与断言可复现 (文件系统 iterdir() 顺序不保
    证)。"""
    reports_dir = Path(repo_path) / ".aria" / "audit-reports"
    if not reports_dir.is_dir():
        print(
            "[WARN] completeness gate: .aria/audit-reports/ 不存在, 按零报告评估",
            file=sys.stderr,
        )
        return []
    return sorted(entry.name for entry in reports_dir.iterdir() if entry.is_file())


def _hits_id(name, stem, change_id):
    """proposal.md §1.2 规则 2 (双侧界定或末段界定), 逐字且大小写敏感, 不做
    归一化。``name`` 是完整文件名 (含 .md), ``stem`` 是去掉 .md 的版本 --
    规则原文的两个子句分别对 ``f`` 与 ``stem`` 求值, 这里逐字照抄, 不合并
    简化成只用其中一个变量。"""
    return f"-{change_id}-" in name or stem.endswith(f"-{change_id}")


def _file_belongs(name, checkpoint, change_id, known_ids):
    """proposal.md §1.2 "文件 f 归属 (checkpoint, change_id) 当且仅当全部
    成立": 规则 1 (前缀 + .md 后缀) + 规则 2 (_hits_id) + 规则 3 (有界包含
    排除, 对称, R1 rework) 三条合取。规则 3: 若存在另一个已知 id ``other``
    (!= change_id) 使 change_id 的"括号形态" f"-{change_id}-" 是 other 括
    号形态 f"-{other}-" 的子串, 且 ``name`` 按规则 2 也命中 ``other``, 则
    name 不归属 change_id -- 单条子串判据等价覆盖前缀/后缀/中缀三型 (两侧
    各加一个 "-" 作哨兵, proposal.md §1.2 规则 3 的"等价"注记)。"""
    if not (name.startswith(f"{checkpoint}-") and name.endswith(".md")):
        return False
    stem = name[:-3]
    if not _hits_id(name, stem, change_id):
        return False
    bracket_cid = f"-{change_id}-"
    for other in known_ids:
        if other == change_id:
            continue
        if bracket_cid in f"-{other}-" and _hits_id(name, stem, other):
            return False
    return True


# proposal.md §1.2 两个排除计数表第一行: 真 2-field 旧 schema 的时间戳形态
# (F4) -- 只含数字 / T / Z / 冒号 / 句点 / 连字符, 应用在"去掉 {checkpoint}-
# 前缀之后"的剩余部分上 (调用点已用 name.startswith() 确认过前缀存在, 这里
# 不再对 checkpoint 名做 re.escape 拼接)。
_LEGACY_TIMESTAMP_RE = re.compile(r"^[0-9TZ:.\-]+\.md$")


def _classify_unmatched(all_names, checked_checkpoints, known_ids):
    """proposal.md §1.2 两个排除计数 + §1.4 "两个计数的作用域": 统计面 =
    顶层以**任一纳入校验的 checkpoint** 名开头的 .md 文件的并集 (未纳入的
    checkpoint 的同形文件三个桶都不收, SC-19(c) 锁)。对统计面内每个文件只
    问"按规则 2 对任何 c∈C 都命中过吗" (不叠加规则 3 的有界收窄 -- 规则 3
    只决定一个文件在多个候选 id 之间最终记到谁头上, 不影响"有没有被任何已
    知 id 命中过"这个布尔判断); 命中过的文件已经 (或将要) 算进某个
    change_id 的 matched, 不进这两个计数。返回 (excluded_legacy_count,
    sorted(unattributed))。"""
    excluded_legacy_count = 0
    unattributed = []
    for name in all_names:
        if not name.endswith(".md"):
            continue
        checkpoint = next(
            (cp for cp in checked_checkpoints if name.startswith(f"{cp}-")), None,
        )
        if checkpoint is None:
            continue
        stem = name[:-3]
        if any(_hits_id(name, stem, cid) for cid in known_ids):
            continue
        if _LEGACY_TIMESTAMP_RE.match(name[len(checkpoint) + 1:]):
            excluded_legacy_count += 1
        else:
            unattributed.append(name)
    return excluded_legacy_count, sorted(unattributed)


def _scan_status(repo_path):
    """<repo_path>/.aria/audit-reports/ 是否存在 -> "ok" | "dir_missing"
    (proposal.md §1.4 "报告目录不存在"; 运行面字段, 与 verdict 正交)。"""
    reports_dir = Path(repo_path) / ".aria" / "audit-reports"
    return "ok" if reports_dir.is_dir() else "dir_missing"


def _elapsed_ms(t0):
    """tasks.md 读前必看 第 24 条: 脚本入口到 stdout JSON 序列化前的墙钟
    耗时, 毫秒, int (不是 bool), 对全部输出 JSON 的运行 (含早退与 error) 都
    取真实计时, 不恒 0、不 null。math.ceil 对非负 float 的返回值在 Python 3
    是内建 int (不是 bool 子类), 且天然 >= 0。"""
    return math.ceil((time.monotonic() - t0) * 1000)


def build_envelope(*, verdict, error_kind=None, scope_source=None, change_ids=None,
                    checked_checkpoints=None, no_prior_checkpoints=False,
                    results=None, excluded_legacy_count=0, unattributed_count=0,
                    unattributed=None, scanned_dir_depth=1, scan_status="ok",
                    bypassed=False, elapsed_ms):
    """组装 stdout 的 16 键 JSON 信封 (proposal.md §1.4)。每个"P6 之前终止的
    运行" (tasks.md 读前必看 第 8 条) 只需省略对应关键字参数, 就能拿到该条
    钉死的非判定键缺省值 (results=[]、两个计数 0、unattributed=[]、
    scanned_dir_depth=1、no_prior_checkpoints=False); 待 TASK-010+ 补上真实
    值时, 通过同一组关键字参数传入, 不新增字段名。"""
    return {
        "schema_version": STDOUT_SCHEMA_VERSION,
        "gate": GATE_NAME,
        "verdict": verdict,
        "error_kind": error_kind,
        "scope_source": scope_source,
        "change_ids": [] if change_ids is None else change_ids,
        "checked_checkpoints": [] if checked_checkpoints is None else checked_checkpoints,
        "no_prior_checkpoints": no_prior_checkpoints,
        "results": [] if results is None else results,
        "excluded_legacy_count": excluded_legacy_count,
        "unattributed_count": unattributed_count,
        "unattributed": [] if unattributed is None else unattributed,
        "scanned_dir_depth": scanned_dir_depth,
        "scan_status": scan_status,
        "bypassed": bypassed,
        "elapsed_ms": elapsed_ms,
    }


def _is_phase_a_only_diff(diff_paths, change_ids):
    """proposal.md §1.2 not_applicable (b): diff **非空** 且全部变更文件
    路径都在 openspec/changes/{作用域内某个 id}/** 或 .aria/audit-reports/**
    之下 (Phase A-only PR)。这里读的是 --diff-repo-path + --base 轴的 diff
    (不是 S2/S3 改走的锚点面) -- 调用方只在 same_repo 时才会算它 (见
    run_completeness_check); 跨仓时 (b) 本就禁止触发 (proposal.md §1
    fail-closed 附加条款), 该条款从未被 R4 rework 的"S2/S3 改走锚点面"波
    及, 它要求 --diff-repo-path == --repo-path 这件事本身就说明它读的是
    diff 仓面, 否则这条前置约束无意义。空 diff 不满足"非空"前置, 返回
    False (与 missing 行"空集不放行"同方向, 不是 (b) 的免检)。"""
    if not diff_paths:
        return False
    scope_prefixes = tuple(f"openspec/changes/{cid}/" for cid in change_ids)
    for path in diff_paths:
        if path.startswith(".aria/audit-reports/"):
            continue
        if path.startswith(scope_prefixes):
            continue
        return False
    return True


_TASKS_HEADING_RE = re.compile(r"^#{2,}\s*Tasks", re.MULTILINE)


def _has_a2_artifact(repo_path, change_id):
    """proposal.md §1.2 "为什么改成「任何 A.2 产物」"(重写 c 的落点): 存在
    openspec/changes/{id}/tasks.md, 或 detailed-tasks.yaml, 或 proposal.md
    内联的 ^#{2,}\\s*Tasks 小节 (任一即可, 不要求两个文件都有 -- Level 2
    的 A.2 产物结构上就是内联的)。归档态复用 _find_change_dir 同一份目录
    判据 (direct 或 archive 日期前缀剥离)。

    **三者独立判定 (审查意见采纳, 修正原先 "proposal.md 不存在就直接返回
    False、不再看 tasks.md/detailed-tasks.yaml" 的早退)**: change 目录存
    在但 proposal.md 缺失时 (例如只有 tasks.md 的异常形态), 前两个文件判
    据仍要照查 -- proposal.md §1.2 (c) 原文 "tasks.md 与 detailed-tasks.yaml
    都不存在 **且** proposal.md 无 Tasks 小节" 是三个独立子句的合取, 不是
    "先看 proposal.md 存在与否再决定要不要看另外两个文件"。change_id 本
    身无锚点 (dangling, _find_change_dir 返回 None, 连目录都定位不到) 时
    三者字面皆不存在, 按"不存在任何 A.2 产物"返回 False。

    proposal.md 读取用 surrogateescape (审查意见采纳) 而非严格 utf-8 --
    _TASKS_HEADING_RE 只匹配 ASCII, 文件里其余部分若含非法字节不应该连带
    让 "## Tasks" 这行本来能匹配到的内容也读不出来。真正的 OSError (读取
    失败, 如权限错误) 时**保守方向视为"产物存在"** (返回 True, 下游继续
    走 missing 而不是 not_applicable 免检) -- 读取失败不等于内容不存在,
    免检是比 missing 更宽松的判决, 不能把"读不出来"悄悄当证据使。"""
    base_dir = _find_change_dir(repo_path, change_id)
    if base_dir is not None:
        if (base_dir / "tasks.md").is_file():
            return True
        if (base_dir / "detailed-tasks.yaml").is_file():
            return True
    proposal_path = base_dir / "proposal.md" if base_dir is not None else None
    if proposal_path is None or not proposal_path.is_file():
        return False
    try:
        text = proposal_path.read_text(encoding="utf-8", errors="surrogateescape")
    except OSError:
        return True
    return _TASKS_HEADING_RE.search(text) is not None


def _resolve_pair_status(checkpoint, change_id, matched, phase_a_only, repo_path):
    """proposal.md §1.3 "per (checkpoint, change_id) 三态", first-match:
    present (规则命中 >= 1 份) 先于 not_applicable 的三条通道 -- (a) S3 的
    change_id=None; (b) post_implementation 的 Phase-A-only (调用方已把
    "checkpoint==post_implementation 且 same_repo" 这两个前置叠进
    ``phase_a_only``); (c) post_planning 的无 A.2 产物 -- 其余落 missing。
    post_spec 没有 not_applicable 通道 (proposal.md:269), 这里不需要为它
    另写分支: (b)/(c) 按 checkpoint 名字面区分, 落不进任何一条就自然到
    missing。"""
    if matched:
        return "present", None
    if change_id is None:
        return "not_applicable", "level1-no-spec"
    if checkpoint == "post_implementation" and phase_a_only:
        return "not_applicable", "phase-a-only-no-implementation"
    if checkpoint == "post_planning" and not _has_a2_artifact(repo_path, change_id):
        return "not_applicable", "no-a2-artifact"
    return "missing", None


# proposal.md §1.4 "三态各有 audit trail 行": not_applicable 的
# "依据 = <机械事实: ... | ... | ...>" 三选一, 按 reason 取对应分支。
# "phase-a-only-no-implementation" 不在这里 -- proposal.md:321 的模板带
# "diff N 文件" 与具体 id 两个机械事实, 是运行时渲染值, 不是逐字不变的静
# 态文案 (审查意见采纳, 见 _not_applicable_trail_line)。
_NOT_APPLICABLE_BASIS = {
    "no-a2-artifact": "无 tasks.md/detailed-tasks.yaml 且 proposal.md 无 ## Tasks 小节",
    "level1-no-spec": "--no-spec 且 diff 不触 openspec/changes/",
}

# proposal.md §1.4 missing 行的 Fix 四项 (R5 rework 从三项补全, 修 Major
# `4fca2e7a` 的可执行性半) -- 四项逐字不随 (checkpoint, change_id) 变化,
# 抽成模块级常量, 每条 missing trail 行原样拼接。
_MISSING_FIX_TEXT = (
    "Fix: (1) 补跑缺失 checkpoint 审计 (对应 Phase Skill 重新调用); "
    "(2) 或在 audit.checkpoints 里显式写该 checkpoint —— adaptive 推导出的 "
    "checkpoint 其报告在产出侧调用链上不产出, 重新调用 Phase Skill 会再次"
    "早退; (3) 把该 checkpoint 改 \"off\"; (4) 临时开 allow_incomplete_checkpoints"
)


def _missing_trail_line(checkpoint, change_id, resolved_mode, excluded_legacy_count,
                         unattributed_count):
    """proposal.md §1.4 "missing" 行模板, 逐字 (含刻意不带方括号的 "ERROR:"
    前缀 -- 与 GateError 的 "[ERROR] completeness gate: ..." 不是同一种
    行: 前者是 fail/exit 1 的逐对留痕, 后者是 error/exit 2 的终局诊断)。两
    个计数是全局单值 (proposal.md §1.4 "两个计数的作用域"), 每条 missing
    行都原样复述同一对 (N, M), 不是按本行重算。"""
    return (
        f"ERROR: pre_merge audit 前序 checkpoint 报告缺失: {checkpoint}@{change_id} "
        f'配置 "{resolved_mode}" 但未找到 .aria/audit-reports/ 下含 "-{change_id}-" 或'
        f'以 "-{change_id}.md" 结尾的 {checkpoint} 报告 (真 legacy 不计入: '
        f"{excluded_legacy_count}; 归属不明: {unattributed_count}, 见下方清单)。"
        f"{_MISSING_FIX_TEXT}"
    )


def _not_applicable_trail_line(checkpoint, change_id, reason, diff_paths=None):
    """proposal.md §1.4 "not_applicable" 行模板。S3 (change_id=None) 时
    "{cp}@{change_id}" 整段渲染为 "{cp} (无 change_id)", 不是只把 change_id
    换成占位文字再接在 "@" 后面 -- "@" 本身也要消失, 不渲染 "@null" (§1.1
    S3 行逐字)。格 D/E 的逐 change trail 行用的 _render_change_id() 只换
    change_id 自身的值 (模板里 "change {X}" 的分隔符始终是空格, 不随
    change_id 是否为 None 变化), 这里的分隔符本身要变, 两处惯例同源但模板
    形状不同, 故不直接复用那个函数。

    ``diff_paths`` (审查意见采纳, 只在 reason=="phase-a-only-no-implementation"
    时由调用方传入且非 None): proposal.md:321 的模板是
    "diff N 文件全部在 openspec/changes/{id}/ 或 .aria/audit-reports/ 下
    (Phase A-only)", N 与 id 都是机械事实, 原实现用了一个不含这两个值的
    静态占位串 -- 这里按本行自己的 (change_id, diff_paths) 动态渲染, 不
    走 _NOT_APPLICABLE_BASIS 那张静态表。"""
    cp_part = (
        f"{checkpoint} (无 change_id)" if change_id is None
        else f"{checkpoint}@{change_id}"
    )
    if reason == "phase-a-only-no-implementation":
        basis = (
            f"diff {len(diff_paths)} 文件全部在 openspec/changes/{change_id}/ 或 "
            ".aria/audit-reports/ 下 (Phase A-only)"
        )
    else:
        basis = _NOT_APPLICABLE_BASIS[reason]
    return (
        f"[INFO] completeness gate: {cp_part} not_applicable ({reason}); "
        f"依据 = {basis}"
    )


def _unattributed_trail_line(checked_checkpoints, unattributed):
    """proposal.md §1.2/§1.4 "unattributed_count > 0 时另起一行" 的逐字模
    板: 全局一行 (不按 checkpoint 重复), checkpoint 名之间与文件名之间一
    律半角逗号 + 一个空格, 前 20 个按字典序截断, 超出时追加"其余 K 份"子
    句 (SC-4(2) 锁逐字相等)。调用方只在 len(unattributed) > 0 时才调用本
    函数, 这里不重复判断。"""
    total = len(unattributed)
    shown = unattributed[:20]
    tail = ""
    if total > 20:
        tail = f", … 其余 {total - 20} 份见 stdout 的 `unattributed`"
    return (
        f"[WARN] unattributed reports (checked={', '.join(checked_checkpoints)}): "
        f"{total} 份 — {', '.join(shown)}{tail}"
    )


def run_completeness_check(args, change_ids, checked_checkpoints, pairs, same_repo):
    """P6 (proposal.md §1.2/§1.2b/§1.3/§1.4): 对纳入集里真正纳入的每个
    (checkpoint, change_id) 对做报告归属匹配 + 三态判定, 边算边发 stderr
    trail 行 (OK/INFO/ERROR + 截断的 unattributed WARN), 并给出两个全局排
    除计数。pairs 的顺序即 results 的顺序 (resolve_inclusion 的"逐对, 不
    是叉乘"顺序, 调用方不需要另行排序 -- 没有 SC 要求 results 本身有序,
    都是靠 change_id/checkpoint 配对查找断言)。返回 (results,
    excluded_legacy_count, unattributed_count, unattributed, has_missing);
    verdict/exit code/是否降级 bypassed 由调用方 (main()) 根据 has_missing
    与 allow_incomplete_checkpoints 决定 -- 这里只负责"逐对评估并全部留
    痕", 不做短路判断 (tasks.md 读前必看第 7 条: missing 的豁免要求"仍逐
    对评估并全部留痕, 走完 P6 后"才降级, 不是提前退出)。"""
    known_ids = _collect_known_change_ids(args.repo_path)
    all_names = _list_top_level_report_names(args.repo_path)

    phase_a_only = False
    diff_paths = None  # 只在下面的 if 分支里求值; (b) trail 行渲染需要它
    if same_repo and "post_implementation" in checked_checkpoints:
        # (b) 读 --diff-repo-path + --base 轴 (same_repo 时与锚点面是同一
        # 个仓, 但可能是不同的 ref -- 调用方若显式传了不同的 --anchor-base
        # 仍要按 --base 求值); _anchor_face_diff() 的实现本就是"给定(仓,
        # ref) 求 merge-base 之后的 diff", 对哪个轴都通用, 这里复用它。
        diff_paths = _anchor_face_diff(args.diff_repo_path, args.base)
        phase_a_only = _is_phase_a_only_diff(diff_paths, change_ids)

    excluded_legacy_count, unattributed = _classify_unmatched(
        all_names, checked_checkpoints, known_ids,
    )

    results = []
    has_missing = False
    for pair in pairs:
        checkpoint, change_id = pair["checkpoint"], pair["change_id"]
        if change_id is None:
            matched = []
        else:
            matched = sorted(
                name for name in all_names
                if _file_belongs(name, checkpoint, change_id, known_ids)
            )
        status, reason = _resolve_pair_status(
            checkpoint, change_id, matched, phase_a_only, args.repo_path,
        )
        if status == "present":
            print(f"[OK] {checkpoint}@{change_id}: {len(matched)} 份", file=sys.stderr)
        elif status == "not_applicable":
            print(
                _not_applicable_trail_line(checkpoint, change_id, reason, diff_paths),
                file=sys.stderr,
            )
        else:
            has_missing = True
            print(
                _missing_trail_line(
                    checkpoint, change_id, pair["resolved_mode"],
                    excluded_legacy_count, len(unattributed),
                ),
                file=sys.stderr,
            )
        results.append({
            "checkpoint": checkpoint, "change_id": change_id, "status": status,
            "reason": reason, "enabled_by": pair["enabled_by"],
            "matched": matched, "matched_count": len(matched),
        })

    if unattributed:
        print(_unattributed_trail_line(checked_checkpoints, unattributed), file=sys.stderr)

    return results, excluded_legacy_count, len(unattributed), unattributed, has_missing


def main(argv=None):
    t0 = time.monotonic()
    args = parse_args(argv)  # argparse 负向格在此 sys.exit(2), stdout 全空

    # tasks.md 读前必看 第 8 条 "scope_source / change_ids 取已产出值否则
    # null/[]" (审查意见采纳, 修正原先两个 except 分支一律写 None/[] 的早
    # 退): 在 try 外先置缺省值, P2 (resolve_scope) 成功返回后再在原地重新
    # 赋值 -- 这样 P2 之后才发生的早退 (P3 的 spec_level_undetermined 被
    # 豁免的 bypassed 或原生 error、P4 坏 mode 值触发的 config_unreadable)
    # 命中的是"已产出值"这个分支, 而 P2 之前的早退 (P1/同仓判定/ref 解析/
    # P2a/S1/S4 本身) 两个变量从未被重新赋值, 自然留在这里的缺省值, 不需
    # 要按 error_kind 分别特判。
    scope_source, change_ids = None, []

    try:
        raw_audit, resolved_audit = load_config(args.repo_path)

        # P1 -- 格 A: 无条件前置, 排在作用域解析之前 (proposal.md §1.0)。用
        # `is not True` 而非 `!= True`, 拒绝 1 这类非布尔真值 (Python 里
        # 1 == True)。
        if resolved_audit["enabled"] is not True:
            raise GateError("audit_not_enabled", P1_STDERR_LINE)

        # 同仓判定 (读前必看 第 30 条: P1 之后、ref 解析/陈旧比对之前无条件
        # 执行)。
        same_repo = resolve_same_repo(args.repo_path, args.diff_repo_path)

        # TASK-009: ref 解析 + 两个 base 轴的陈旧告警 (读前必看 第 30 条 /
        # TASK-009 verification 第 4 条) -- 同仓判定之后、P2a 之前无条件
        # 执行, 不依赖后面 S1->S4 实际走哪一支 (SC-22.3 用 S1 路径喂一个解
        # 析不出来的 --base 照样必须在这里就 git_failed)。
        check_ref_staleness(
            args.repo_path, args.diff_repo_path, args.base, args.anchor_base,
            same_repo, args.anchor_base_explicit,
        )

        # P2a -- --no-spec 输入合法性前置 (proposal.md §1.0): 必须早于 P2
        # (S1->S4), 否则同仓下 S2 的 first-match 会先吃掉矛盾检测。未给
        # --no-spec 时是 no-op (anchor_diff 留 None, 供 P2 按需自行计算)。
        anchor_diff_from_p2a = None
        if args.no_spec:
            anchor_diff_from_p2a = check_no_spec_precondition(
                args.repo_path, args.anchor_base,
            )

        # P2 -- 作用域解析 S1 -> S4 (proposal.md §1.1)。scope_source 从本任
        # 务 (TASK-011) 起被 P5 的格 B-E 分支消费 (读前必看 第 8 条: 这条分
        # 支的 scope_source/change_ids 取"已产出值", 不是 None/[]); 赋值给
        # 的是 try 外已声明的同名变量, 之后任何早退 (except 分支) 读到的都
        # 是这里产出的值, 不需要分别传递。**dangling_ids 需要单独喂给 P4/
        # P5 (审查意见采纳, 修正原先"不需要单独喂"的论断)**: 该论断只对
        # mode=='adaptive' 成立 (_LevelCache 会在那条分支里重新按需发现
        # dangling), convergence/challenge/manual 三档从不查 level_cache,
        # S1 已经知道的"锚点缺失"信息在那三档下会被静默吞掉, 见
        # resolve_checkpoint_mode 的文档字符串。resolve_scope 内部的
        # error 分支 (S1 无锚点且不豁免 / S4) 是 P2 自己的终局, 与下面
        # P3/P4 新增的两个 error_kind 无关。
        scope_source, change_ids, dangling_ids = resolve_scope(
            args, resolved_audit, anchor_diff_from_p2a,
        )

        # P3 (按需 Level 解析) + P4 (五档优先级链/五项排除/逐对纳入/
        # dangling-skip, proposal.md §1.3)。checked_checkpoints 被下面的 P5
        # 分支消费; pairs (P6 的报告归属匹配/三态输入, TASK-012) 在纳入集
        # 非空时交给 run_completeness_check()。这里能新增触发的两个
        # GateError (级 3 坏 mode 值 -> config_unreadable; Level 解析失败且
        # 未开 allow_dangling_change_ids -> spec_level_undetermined) 都由下
        # 面的 except GateError 接住 -- 后者现在多了一条判断分支 (裁定 11
        # 的豁免), 前者仍落生成式的通用 error 分支。
        level_cache = _LevelCache(args.repo_path, resolved_audit["allow_dangling_change_ids"])
        checked_checkpoints, pairs = resolve_inclusion(
            change_ids, raw_audit, resolved_audit, level_cache, dangling_ids,
        )

        if checked_checkpoints:
            # P6 (报告归属匹配 + 三态 + 路由, proposal.md §1.2/§1.3/§1.4,
            # TASK-012)。纳入集非空时直接走 P6, 不经过 P5 的格 B-E 分支
            # (§1.0 P5: "纳入集为空时才判")。
            results, excluded_legacy_count, unattributed_count, unattributed, has_missing = (
                run_completeness_check(
                    args, change_ids, checked_checkpoints, pairs, same_repo,
                )
            )
            elapsed_ms = _elapsed_ms(t0)

            if has_missing and resolved_audit["allow_incomplete_checkpoints"]:
                # tasks.md 读前必看第 7 条 "missing 的豁免": 上面已经逐对评
                # 估并全部留痕, 走完 P6 后才把 verdict 降为 bypassed/exit 0
                # -- 不是短路, results/两个计数照常输出; 统一 WARN 行的
                # scope_unresolved=0 (作用域本身是已解析的, 跟 S4-bypassed
                # 那条 scope_unresolved=1 的早退不同源)。
                missing_entries = [
                    f"{r['checkpoint']}@{r['change_id']}" for r in results
                    if r["status"] == "missing"
                ]
                print(_bypass_warn_line(missing_entries, 0), file=sys.stderr)
                envelope = build_envelope(
                    verdict="bypassed", scope_source=scope_source, change_ids=change_ids,
                    checked_checkpoints=checked_checkpoints, results=results,
                    excluded_legacy_count=excluded_legacy_count,
                    unattributed_count=unattributed_count, unattributed=unattributed,
                    bypassed=True, scan_status=_scan_status(args.repo_path),
                    elapsed_ms=elapsed_ms,
                )
                sys.stdout.write(json.dumps(envelope, ensure_ascii=False, sort_keys=True) + "\n")
                return EXIT_CODES["bypassed"]

            verdict = "fail" if has_missing else "pass"
            envelope = build_envelope(
                verdict=verdict, scope_source=scope_source, change_ids=change_ids,
                checked_checkpoints=checked_checkpoints, results=results,
                excluded_legacy_count=excluded_legacy_count,
                unattributed_count=unattributed_count, unattributed=unattributed,
                scan_status=_scan_status(args.repo_path), elapsed_ms=elapsed_ms,
            )
            sys.stdout.write(json.dumps(envelope, ensure_ascii=False, sort_keys=True) + "\n")
            return EXIT_CODES[verdict]

        # P5 -- 纳入集为空, 判格 B/C/D/E (proposal.md §1.4, TASK-011)。
        # scope_source/change_ids 在这条分支上取"已产出值" (读前必看 第 8
        # 条): P2 已经成功解析过作用域, 不是短路, 与下面 except 分支里的
        # None/[] 不同。
        reduced_off, bucket, per_change = resolve_pre_merge_axes(
            change_ids, raw_audit, resolved_audit, level_cache, dangling_ids,
        )
        elapsed_ms = _elapsed_ms(t0)

        if not reduced_off:
            # 格 B。
            print(BUCKET_B_INFO_LINE, file=sys.stderr)
            envelope = build_envelope(
                verdict="pass", scope_source=scope_source, change_ids=change_ids,
                no_prior_checkpoints=True, scan_status=_scan_status(args.repo_path),
                elapsed_ms=elapsed_ms,
            )
            sys.stdout.write(json.dumps(envelope, ensure_ascii=False, sort_keys=True) + "\n")
            return EXIT_CODES["pass"]

        if bucket == "C":
            print(BUCKET_C_STDERR_LINE, file=sys.stderr)
            envelope = build_envelope(
                verdict="error", error_kind="pre_merge_not_enabled",
                scope_source=scope_source, change_ids=change_ids,
                scan_status=_scan_status(args.repo_path), elapsed_ms=elapsed_ms,
            )
            sys.stdout.write(json.dumps(envelope, ensure_ascii=False, sort_keys=True) + "\n")
            return EXIT_CODES["error"]

        # bucket in ("D", "E"): 两者都判 pass, 只是逐 change trail 措辞不同
        # (R-2: 并存时按格 D 处理, dangling-skip 的 change 仍各自按格 E 的
        # 文案出一行 -- proposal.md §1.4 格 D 行"两者并存"子句)。
        # explicit/manual-default 的 change (若与 adaptive/dangling-skip 混
        # 在同一作用域里) 不出 trail 行 -- 它们本就可预判, 不是这一格要解
        # 释的对象。
        for change_id, _resolved_mode, enabled_by in per_change:
            if enabled_by.startswith("adaptive:level_"):
                print(
                    _bucket_d_info_line(change_id, enabled_by.rsplit("_", 1)[1]),
                    file=sys.stderr,
                )
            elif enabled_by == "dangling-skip":
                print(_bucket_e_info_line(change_id), file=sys.stderr)

        envelope = build_envelope(
            verdict="pass", scope_source=scope_source, change_ids=change_ids,
            no_prior_checkpoints=True, scan_status=_scan_status(args.repo_path),
            elapsed_ms=elapsed_ms,
        )
        sys.stdout.write(json.dumps(envelope, ensure_ascii=False, sort_keys=True) + "\n")
        return EXIT_CODES["pass"]

    except GateError as exc:
        elapsed_ms = _elapsed_ms(t0)

        if (
            exc.error_kind in BYPASSABLE_EARLY_EXIT_KINDS
            and resolved_audit["allow_incomplete_checkpoints"]
        ):
            # tasks.md 读前必看 第 7/8 条 (裁定 11): S4 / no_spec_unverifiable
            # / spec_level_undetermined 在该旗标下降为 bypassed/exit 0 并短
            # 路 -- 短路已经发生 (上面的异常直接终止了 try 块, P5/P6 都不会
            # 再跑); change_id_unanchored / no_spec_contradicted 不在
            # BYPASSABLE_EARLY_EXIT_KINDS 里, 走不到这一支 (决策单第 11 行:
            # 两个 allow_* 都不救)。原本那条 "[ERROR] ..." 诊断行不重复打印
            # -- verdict 已经不是 error, 继续用 [ERROR] 前缀会跟 JSON 里的
            # verdict=bypassed 互相矛盾; 统一 WARN 行 (+ 适用时的额外一行)
            # 是这里唯一的留痕 (执笔人取舍)。
            scope_unresolved = 1 if exc.error_kind in SCOPE_UNRESOLVED_KINDS else 0
            print(_bypass_warn_line([], scope_unresolved), file=sys.stderr)
            if exc.error_kind in EXTRA_BYPASS_WARN_KINDS:
                print(f"[WARN] bypassed: {exc.error_kind}", file=sys.stderr)
            envelope = build_envelope(
                verdict="bypassed",
                scope_source=scope_source, change_ids=change_ids,
                checked_checkpoints=_explicit_only_checked_checkpoints(raw_audit),
                bypassed=True,
                scan_status=_scan_status(args.repo_path),
                elapsed_ms=elapsed_ms,
            )
            sys.stdout.write(json.dumps(envelope, ensure_ascii=False, sort_keys=True) + "\n")
            return EXIT_CODES["bypassed"]

        print(exc.stderr_line, file=sys.stderr)
        # checked_checkpoints 缺省 []: 读前必看 第 8 条的 explicit-only 收窄
        # 规则限定给上面那三类被豁免的早退, 本分支 (无论是否被豁免) 一律
        # 不取"已产出值" (理由同上 BYPASSABLE 分支的 docstring)。
        # **scope_source/change_ids 改读 try 外的同名变量 (审查意见采纳,
        # 修正原先一律硬写 None/[] 的早退)**: 读前必看 第 8 条"取已产出值
        # 否则 null/[]"管的是这两个字段, 不止 BYPASSABLE 的三类 -- P2 (作
        # 用域解析) 成功之后才发生的早退 (P3 原生 spec_level_undetermined、
        # P4 坏 mode 值触发的 config_unreadable) 这两个变量已经是 P2 产出
        # 的真实值, 不应该被这里硬写回 None/[]; P2 之前的早退 (P1/同仓判
        # 定/ref 解析/P2a/S1/S4 本身) 这两个变量从未被重新赋值, 读到的就
        # 是 try 外声明时的缺省值, 效果与原来的硬写等价。
        envelope = build_envelope(
            verdict="error",
            error_kind=exc.error_kind,
            scope_source=scope_source, change_ids=change_ids,
            scan_status=_scan_status(args.repo_path),
            elapsed_ms=elapsed_ms,
        )
        sys.stdout.write(json.dumps(envelope, ensure_ascii=False, sort_keys=True) + "\n")
        return EXIT_CODES["error"]


def _main_guarded(argv=None):
    """审查意见采纳 (robust lens): main() 内部已对 proposal.md 枚举过的
    error_kind 逐一捕获 (GateError), 但环境/配置形状里总有枚举未穷尽的
    一类 (例如 .aria/audit-reports/ 权限被设成不可读触发的 PermissionError
    -- 这类不是本次审查新增校验的对象, 没有专门的 error_kind), 未捕获异常
    会让 Python 默认行为接管: traceback 散落在 stdout/stderr 之间、exit 1。
    exit 1 与 verdict=fail 的契约码相撞, 消费方的 fail-closed 义务 (exit
    非 0/2 一律按 fail 处置) 这里碰巧不会误判成"放行", 但会把一次环境错误
    误诊成"有 missing checkpoint"。这里兜底: stdout 保持完全空白 (不写半
    截 JSON), traceback 打 stderr 供人工诊断, exit 2 与其余 error_kind 同
    码。argparse 自身的 SystemExit (--help / 参数错) 不是 Exception 的子
    类, 不受影响, 照常传播。"""
    try:
        return main(argv)
    except Exception:
        traceback.print_exc(file=sys.stderr)
        return EXIT_CODES["error"]


if __name__ == "__main__":
    sys.exit(_main_guarded())

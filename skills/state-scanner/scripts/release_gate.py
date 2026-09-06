#!/usr/bin/env python3
"""release_gate — Layer L claim 释放 CLI (coordination-claim-lifecycle-and-overlap Part C).

镜像 phase1_gate 的 subprocess 契约: AI 编排层 (phase-d-closer D.2 归档后 /
phase-c-integrator ship 收尾) 经 subprocess 调用, 把本 cycle 的 carry-id 对应
claim 标记 terminal, 根除 "claim 从不释放累积" (defect c)。

Contract:
  stdin : none
  args  : [--raw-track-id ID] [--status done|yielded|abandoned]
          [--sweep-stale] [--gc] [--repo-path] [--remote] [--no-push]
          至少给 --raw-track-id / --sweep-stale / --gc 之一。
  env   : ARIA_COORDINATION_NO_PUSH=1|true|yes ⇔ --no-push (同 phase1_gate;
          harness 安全 — AB benchmark 在真实仓 / 真实 origin 里跑)
  stdout: single JSON object (见 _result_to_dict)
  exit  : 0 — 所有请求动作完成或 benign (released / claim_not_found /
              sweep+gc 完成含 soft errors)
          1 — 硬错 (identity_error / write_failed / push auth 失败等)
          2 — argparse 用法错误

Advisory 契约 (proposal 部件 C): 释放失败不阻断 ship —— caller (phase-d-closer)
把 exit 1 当告警记录, 不 abort 收尾流程。exit code 只是给编排层的信号强度。

Telemetry: 写独立分区 .aria/coordination-release-telemetry.jsonl —— 不写
phase1_gate 的 coordination-telemetry.jsonl, 因为 runtime_probe._scan_partition
不按 symbol 过滤, 混写会虚增 run_gate 探针计数 (threshold-gate raw-count 膨胀坑)。

Rule #7: 所有 git I/O 经 lib 原语 (capture_output=True), stdout 只输出结构化 JSON。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# --- import bootstrap: 同 phase1_gate (scripts/ 直跑 vs 包内 import 双上下文) ---
try:
    from ..lib.claim_lifecycle import release_claim_by_track, AcquireResult, label_migration_inventory
    from ..lib.coordination_ref import fetch_coordination_ref, read_claims
    from ..lib.identity import get_container_label
    from ..lib.failure_handlers import resilient_push, no_push_requested_by_env
    from ..lib.gc import archive_done_claims, sweep_stale_active
    from ..lib.track_id import derive_track_id
except ImportError:
    import sys as _sys
    from pathlib import Path as _Path

    _SKILL_ROOT = str(_Path(__file__).resolve().parent.parent)
    while _SKILL_ROOT in _sys.path:
        _sys.path.remove(_SKILL_ROOT)
    _sys.path.insert(0, _SKILL_ROOT)
    from lib.claim_lifecycle import release_claim_by_track, AcquireResult, label_migration_inventory  # type: ignore[import]
    from lib.coordination_ref import fetch_coordination_ref, read_claims  # type: ignore[import]
    from lib.identity import get_container_label  # type: ignore[import]
    from lib.failure_handlers import resilient_push, no_push_requested_by_env  # type: ignore[import]
    from lib.gc import archive_done_claims, sweep_stale_active  # type: ignore[import]
    from lib.track_id import derive_track_id  # type: ignore[import]


_RELEASE_TELEMETRY_FILE = "coordination-release-telemetry.jsonl"

# release 结果里视为 benign 的 error token (ship 时 claim 早已释放/从未认领)。
_BENIGN_RELEASE_ERRORS = frozenset({"claim_not_found"})


def _emit_release_telemetry(repo: Path, payload: dict, ts: datetime) -> None:
    """Append one release telemetry record.  NEVER raises (best-effort)."""
    try:
        import json as _json

        record = {"ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"), "source": "production"}
        record.update(payload)
        path = repo / ".aria" / _RELEASE_TELEMETRY_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(_json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:  # pragma: no cover — telemetry must not break release
        logger.debug("release_gate: telemetry emit skipped (%s)", exc)


def run_release(
    raw_track_id: Optional[str],
    *,
    status: str = "done",
    sweep_stale: bool = False,
    gc: bool = False,
    repo_path: Optional[Path] = None,
    remote: str = "origin",
    now: Optional[datetime] = None,
    no_push: bool = False,
) -> dict:
    """Library entry — fetch → release → optional sweep/gc → push.

    每步 fail-soft: 单步失败记录进结果, 继续后续步骤 (advisory; reconcile 是
    最终仲裁, 本地成功 + push 失败也只是 "下次 fetch 时收敛")。

    ``no_push`` (CLI ``--no-push`` / env ``ARIA_COORDINATION_NO_PUSH``): 本地
    写照常, Step 5 push 整个跳过 —— 结果 ``push_skipped=True`` +
    ``push_success=False`` (与 push 失败 / 未写任何东西可区分)。

    Returns the JSON-safe result dict (see keys below).
    """
    repo: Path = repo_path if repo_path is not None else Path.cwd()
    ts: datetime = now if now is not None else datetime.now(timezone.utc)

    result: dict = {
        "released": None,          # None=未请求; dict 见下
        "sweep": None,             # None=未请求; {"swept_count", "swept", "errors"}
        "gc": None,                # None=未请求; {"archived_count", "errors"}
        "fetch_success": None,
        "push_success": None,
        "push_skipped": False,     # True 仅当本次真该 push 却被 no_push 跳过
        "push_skipped_reason": None,  # CLI 填 cli_flag|env_var (仅 push_skipped 时)
        "hard_error": None,        # 首个硬错 token; None = 全 benign
        "label_migration": None,   # T3b S1 inventory (owner-container-identity-key); null = 无 label
    }

    # Step 1: fetch (fail-soft — 拿最新 claim 状态; 失败继续用本地视图)
    fetch = fetch_coordination_ref(repo, remote=remote)
    result["fetch_success"] = fetch.success
    if not fetch.success:
        logger.warning(
            "release_gate: fetch failed (kind=%s) — proceeding with local view",
            fetch.error_kind,
        )

    # Step 1b: T3b label-migration inventory (S1: 纯告警, 无抑制; additive key)
    try:
        inv = label_migration_inventory(get_container_label(), read_claims(repo).claims)
    except Exception as exc:  # fail-soft
        logger.warning("release_gate: label migration inventory skipped (%s)", exc)
        inv = None
    result["label_migration"] = inv
    if inv is not None:
        logger.warning("release_gate: %s", inv["message"])

    wrote_anything = False

    # Step 2: release by track (仅当给了 carry-id)
    if raw_track_id:
        rel: AcquireResult = release_claim_by_track(
            raw_track_id, status=status, repo_path=repo, now=ts
        )
        released: dict = {
            "success": rel.success,
            "error": rel.error,
            "track_id": derive_track_id(raw_track_id),
            "status": status if rel.success else None,
            "benign": (not rel.success) and rel.error in _BENIGN_RELEASE_ERRORS,
        }
        result["released"] = released
        if rel.success:
            wrote_anything = True
        elif rel.error not in _BENIGN_RELEASE_ERRORS:
            result["hard_error"] = rel.error

    # Step 3: stale-active sweep (可选)
    if sweep_stale:
        sw = sweep_stale_active(repo, now=ts)
        result["sweep"] = {
            "swept_count": sw.swept_count,
            "swept": sw.swept,
            "errors": sw.errors,
        }
        if sw.swept_count > 0:
            wrote_anything = True
        for e in sw.errors:
            if e.startswith("git_write_failed") and result["hard_error"] is None:
                result["hard_error"] = e

    # Step 4: done-claim GC 归档 (可选)
    if gc:
        gr = archive_done_claims(repo, now=ts, dry_run=False)
        result["gc"] = {
            "archived_count": gr.archived_count,
            "archived_paths": gr.archived_paths,
            "errors": gr.errors,
        }
        if gr.archived_count > 0:
            wrote_anything = True
        for e in gr.errors:
            if e.startswith("git_write_failed") and result["hard_error"] is None:
                result["hard_error"] = e

    # Step 5: push (仅当本次真写了 ref)。用 resilient_push (review I2) — 与
    # acquire 路径 (phase1_gate) 同一失败矩阵: non-FF fetch-replay 重试 (正是
    # "别人刚推了 claim" 的协调目标场景), auth 不重试。仍 fail-soft: 失败只
    # 记录, reconcile 下次 fetch 仲裁; 但 auth 失败升 hard_error (需 operator)。
    if wrote_anything and no_push:
        # CLI --no-push / ARIA_COORDINATION_NO_PUSH (same channel as phase1_gate,
        # harness safety): local ref updated, remote deliberately NOT touched.
        # push_success=False + push_skipped=True keeps a skip distinguishable
        # from a failed push (push_skipped=False) and from "nothing written"
        # (push_success=None).  Not a hard_error — nothing went wrong.
        result["push_success"] = False
        result["push_skipped"] = True
        logger.info(
            "release_gate: push SKIPPED (no_push) — local ref updated only (remote=%s)",
            remote,
        )
    elif wrote_anything:
        push = resilient_push(repo, remote=remote)
        result["push_success"] = push.success
        if not push.success:
            logger.warning(
                "release_gate: push failed (kind=%s, attempts=%d) — local ref "
                "updated, remote converges on next fetch/reconcile",
                push.error_kind,
                push.attempts,
            )
            if push.error_kind == "auth_failed" and result["hard_error"] is None:
                result["hard_error"] = "push_auth_failed"

    _emit_release_telemetry(
        repo,
        {
            "op": "release_gate",
            "released": (result["released"] or {}).get("success"),
            "release_error": (result["released"] or {}).get("error"),
            "swept_count": (result["sweep"] or {}).get("swept_count"),
            "gc_archived": (result["gc"] or {}).get("archived_count"),
            "push_success": result["push_success"],
            "hard_error": result["hard_error"],
        },
        ts,
    )
    return result


def _main(argv: Optional[list[str]] = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(
        prog="release_gate",
        description=(
            "Layer L claim 释放 CLI — phase-d-closer 收尾时调用, 释放本 cycle "
            "carry-id 的 claim (镜像 phase1_gate acquire 契约; defect c 修复)"
        ),
    )
    parser.add_argument(
        "--raw-track-id",
        default=None,
        help="本 cycle 的 carry-id 原始串 (未归一; 内部 derive_track_id 归一)",
    )
    parser.add_argument(
        "--status",
        default="done",
        choices=["done", "yielded", "abandoned"],
        help="释放为的 terminal 状态 (默认 done)",
    )
    parser.add_argument(
        "--sweep-stale",
        action="store_true",
        help="顺带扫描: active 且 heartbeat 超 STALE_TTL → abandoned (跨 container)",
    )
    parser.add_argument(
        "--gc",
        action="store_true",
        help="顺带 GC: done 且超 retention 的 claim 移入 archive/<YYYY-MM>/",
    )
    parser.add_argument("--repo-path", default=None, help="仓库根路径 (默认 cwd)")
    parser.add_argument("--remote", default="origin", help="git remote (默认 origin)")
    parser.add_argument(
        "--no-push",
        action="store_true",
        help=(
            "跳过 Step 5 push (释放/sweep/gc 仍写本地 refs/aria/coordination, 不推远端); "
            "等价于环境变量 ARIA_COORDINATION_NO_PUSH=1|true|yes (同 phase1_gate; "
            "AB benchmark 等在真实仓跑的 harness 必须开)。输出 push_skipped / "
            "push_skipped_reason (cli_flag|env_var|null) 区分「主动跳过」与「push 失败」"
        ),
    )
    args = parser.parse_args(argv)

    if not args.raw_track_id and not args.sweep_stale and not args.gc:
        parser.error("至少需要 --raw-track-id / --sweep-stale / --gc 之一")

    repo = Path(args.repo_path) if args.repo_path else Path.cwd()
    # 同 phase1_gate._main: 推送抑制只在 CLI 边界解析一次, 显式 kwarg 下传
    # (lib 不读环境); reason 优先级: 显式 flag 胜过 env。
    env_no_push = no_push_requested_by_env()
    no_push = bool(args.no_push or env_no_push)
    push_skipped_reason = (
        "cli_flag" if args.no_push else ("env_var" if env_no_push else None)
    )
    # 顶层兜底 (review M4): "stdout = single JSON object" 契约在意外异常下也成立
    # — caller 永远拿得到可解析 JSON, 不会收到裸 traceback。
    try:
        result = run_release(
            args.raw_track_id,
            status=args.status,
            sweep_stale=args.sweep_stale,
            gc=args.gc,
            repo_path=repo,
            remote=args.remote,
            no_push=no_push,
        )
    except Exception as exc:  # noqa: BLE001 — CLI 契约兜底
        logger.warning("release_gate: unexpected error: %s", type(exc).__name__)
        result = {
            "released": None,
            "sweep": None,
            "gc": None,
            "fetch_success": None,
            "push_success": None,
            "push_skipped": False,
            "push_skipped_reason": None,
            "hard_error": f"unexpected:{type(exc).__name__}",
        }
    if result.get("push_skipped"):
        result["push_skipped_reason"] = push_skipped_reason
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["hard_error"] else 0


if __name__ == "__main__":
    import sys as _sys

    _sys.exit(_main())

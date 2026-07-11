#!/usr/bin/env python3
"""release_gate — Layer L claim 释放 CLI (coordination-claim-lifecycle-and-overlap Part C).

镜像 phase1_gate 的 subprocess 契约: AI 编排层 (phase-d-closer D.2 归档后 /
phase-c-integrator ship 收尾) 经 subprocess 调用, 把本 cycle 的 carry-id 对应
claim 标记 terminal, 根除 "claim 从不释放累积" (defect c)。

Contract:
  stdin : none
  args  : [--raw-track-id ID] [--status done|yielded|abandoned]
          [--sweep-stale] [--gc] [--repo-path] [--remote]
          至少给 --raw-track-id / --sweep-stale / --gc 之一。
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
    from ..lib.claim_lifecycle import release_claim_by_track, AcquireResult
    from ..lib.coordination_ref import fetch_coordination_ref
    from ..lib.failure_handlers import resilient_push
    from ..lib.gc import archive_done_claims, sweep_stale_active
    from ..lib.track_id import derive_track_id
except ImportError:
    import sys as _sys
    from pathlib import Path as _Path

    _SKILL_ROOT = str(_Path(__file__).resolve().parent.parent)
    while _SKILL_ROOT in _sys.path:
        _sys.path.remove(_SKILL_ROOT)
    _sys.path.insert(0, _SKILL_ROOT)
    from lib.claim_lifecycle import release_claim_by_track, AcquireResult  # type: ignore[import]
    from lib.coordination_ref import fetch_coordination_ref  # type: ignore[import]
    from lib.failure_handlers import resilient_push  # type: ignore[import]
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
) -> dict:
    """Library entry — fetch → release → optional sweep/gc → push.

    每步 fail-soft: 单步失败记录进结果, 继续后续步骤 (advisory; reconcile 是
    最终仲裁, 本地成功 + push 失败也只是 "下次 fetch 时收敛")。

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
        "hard_error": None,        # 首个硬错 token; None = 全 benign
    }

    # Step 1: fetch (fail-soft — 拿最新 claim 状态; 失败继续用本地视图)
    fetch = fetch_coordination_ref(repo, remote=remote)
    result["fetch_success"] = fetch.success
    if not fetch.success:
        logger.warning(
            "release_gate: fetch failed (kind=%s) — proceeding with local view",
            fetch.error_kind,
        )

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
    if wrote_anything:
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
    args = parser.parse_args(argv)

    if not args.raw_track_id and not args.sweep_stale and not args.gc:
        parser.error("至少需要 --raw-track-id / --sweep-stale / --gc 之一")

    repo = Path(args.repo_path) if args.repo_path else Path.cwd()
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
        )
    except Exception as exc:  # noqa: BLE001 — CLI 契约兜底
        logger.warning("release_gate: unexpected error: %s", type(exc).__name__)
        result = {
            "released": None,
            "sweep": None,
            "gc": None,
            "fetch_success": None,
            "push_success": None,
            "hard_error": f"unexpected:{type(exc).__name__}",
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["hard_error"] else 0


if __name__ == "__main__":
    import sys as _sys

    _sys.exit(_main())

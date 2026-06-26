#!/usr/bin/env python3
"""session-closer · context-pressure advisory trigger (TASK-006).

读 runtime-truth context occupancy (经 aria-token-telemetry) + 未交接成果信号,
判断是否 **advise** (nudge) 用户现在跑 /session-closer —— 赶在 context compaction
静默丢早期轮次、handoff 失真之前。

advisory-only: **永不自动执行**收尾。承袭 aria-context-monitor "只给数据不自动中断"
DEC (#104)。

口径不混用 (hard constraint): relay_cache → used_percentage;
transcript_fallback → used_percentage_proxy。两者绝不混用 (否则重蹈 #104 22% drift)。
"""
from __future__ import annotations

import json
import subprocess

DEFAULT_THRESHOLD = 85  # %, 对齐 aria-context-monitor ">85% 建议暂停"
_SIGNAL_KEYS = ("uncommitted", "followups_nonempty", "new_memory_unrecorded")


def occupancy_from_telemetry(telemetry):
    """按 source 读 **正确** 字段, 返回 (occupancy_pct_or_None, source)。

    relay_cache         → used_percentage        (runtime-truth, 0 偏差)
    transcript_fallback → used_percentage_proxy   (estimate; window 可能低估)
    unavailable / 其它  → None (信号不可用, 不报错)
    """
    source = (telemetry or {}).get("source")
    if source == "relay_cache":
        return telemetry.get("used_percentage"), source
    if source == "transcript_fallback":
        return telemetry.get("used_percentage_proxy"), source
    return None, source


def has_unshipped_work(signals):
    """任一未交接信号置位即为真。三信号: 未提交变更 / followups 非空 / 新 memory 未入 §8。"""
    return any(bool((signals or {}).get(k)) for k in _SIGNAL_KEYS)


def evaluate_closeout_trigger(telemetry, signals, threshold=DEFAULT_THRESHOLD):
    """纯 advisory 判定。返回结构化 verdict。

    should_nudge == True  ⟺  occupancy 已知 AND occupancy >= threshold
                              AND 至少一个未交接信号置位。
    occupancy 不可用 (unavailable) → 永不 nudge, 永不抛异常。
    """
    occ, source = occupancy_from_telemetry(telemetry)
    unshipped = has_unshipped_work(signals)
    if occ is None:
        return {
            "should_nudge": False,
            "occupancy": None,
            "source": source,
            "threshold": threshold,
            "has_unshipped": unshipped,
            "reason": "occupancy_unavailable",
        }
    if occ < threshold:
        reason = "occupancy_below_threshold"
    elif not unshipped:
        reason = "no_unshipped_work"
    else:
        reason = "context_pressure_with_unshipped"
    return {
        "should_nudge": occ >= threshold and unshipped,
        "occupancy": occ,
        "source": source,
        "threshold": threshold,
        "has_unshipped": unshipped,
        "reason": reason,
    }


def nudge_message(verdict, unshipped_count=None):
    occ = verdict.get("occupancy")
    n = unshipped_count if unshipped_count is not None else ("≥1" if verdict.get("has_unshipped") else 0)
    return (
        f"⚠️ context 已用 {occ}%(≥{verdict.get('threshold')}% 阈值),有 {n} 项未交接成果。"
        f"建议现在 `/session-closer` 写交接,赶在 compaction 失真前固化。"
    )


# --- CLI glue (best-effort; 纯函数以上, 便于单测) -------------------------------

def _git_uncommitted(project_root="."):
    try:
        r = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_root, capture_output=True, text=True, timeout=10,
        )
        return bool(r.stdout.strip())
    except Exception:
        return False


def _load_telemetry(telemetry_path=None):
    """读 token-telemetry JSON; path 缺省时返回 unavailable (调用方负责真正取数)。"""
    if not telemetry_path:
        return {"source": "unavailable"}
    try:
        with open(telemetry_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"source": "unavailable"}


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="session-closer context-pressure advisory trigger")
    p.add_argument("--project-root", default=".")
    p.add_argument("--telemetry-json", default=None, help="path to token_telemetry output JSON")
    p.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD)
    p.add_argument("--followups-nonempty", action="store_true")
    p.add_argument("--new-memory-unrecorded", action="store_true")
    a = p.parse_args(argv)

    telemetry = _load_telemetry(a.telemetry_json)
    signals = {
        "uncommitted": _git_uncommitted(a.project_root),
        "followups_nonempty": a.followups_nonempty,
        "new_memory_unrecorded": a.new_memory_unrecorded,
    }
    verdict = evaluate_closeout_trigger(telemetry, signals, threshold=a.threshold)
    print(json.dumps(verdict, ensure_ascii=False))
    if verdict["should_nudge"]:
        print(nudge_message(verdict))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

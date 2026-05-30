#!/usr/bin/env python3
"""ai-native-estimator (#18 v1) — Token 轴 cycle 粒度工作量采集 + 查询.

v1 = Token axis ONLY (Attention 轴 / L1-L2 / 5 集成 defer v2). 复用 aria-token-telemetry
iter_transcript_usage() 做 transcript range 解析. stdlib-only. 永不抛异常给消费方.

设计 (DEC-20260530-001 + post_spec Rev2):
  - 采集 = phase-d-closer 收尾调 capture(); cycle 粒度 (非 per-task)
  - watermark {last_uuid, last_timestamp, session_id, transcript_path}: 增量 anchor
  - 幂等主机制 = watermark 空区间 (重跑无新 turn → range 空 → skip)
  - cycle_id = {spec_slug}-{end_uuid[:8]} (range 末 uuid 锚, cycle 内稳定, 非 capture 时刻)
  - work_metric = output + cache_creation (cache_read 是上下文重载, 非"工作")
  - wall_clock_seconds = 被动元数据 (calendar-elapsed ≠ effort), null-safe
  - forecast cluster key = spec_level (L1/L2/L3); N<min_samples → uncalibrated bootstrap
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

# import sibling internal skill aria-token-telemetry (transcript parsing SoT)
_HERE = os.path.dirname(os.path.abspath(__file__))
_TT = os.path.join(_HERE, "..", "..", "aria-token-telemetry", "scripts")
sys.path.insert(0, _TT)
import token_telemetry as tt  # noqa: E402

ESTIMATOR_DIR_REL = ".aria/estimator"
VARIANCE_REL = ".aria/estimator/variance.jsonl"
WATERMARK_REL = ".aria/estimator/watermark.json"
CONFIG_REL = ".aria/config.json"

DEFAULT_MIN_SAMPLES = 3
DEFAULT_WINDOW = 10
DEFAULT_BOOTSTRAP = {"L1": 30000, "L2": 150000, "L3": 500000}


# --------------------------------------------------------------------------- #
# config / io helpers (never raise)
# --------------------------------------------------------------------------- #
def _load_config(project_root: str) -> dict:
    try:
        with open(os.path.join(project_root, CONFIG_REL), "r", encoding="utf-8") as fh:
            return (json.load(fh) or {}).get("ai_native_estimator", {}) or {}
    except (FileNotFoundError, OSError, json.JSONDecodeError, ValueError, TypeError):
        return {}


def _cfg(project_root, key, default):
    return _load_config(project_root).get(key, default)


def _atomic_write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def _read_watermark(project_root: str) -> dict | None:
    try:
        with open(os.path.join(project_root, WATERMARK_REL), "r", encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else None
    except (FileNotFoundError, OSError, json.JSONDecodeError, ValueError):
        return None


def _write_watermark(project_root: str, wm: dict) -> None:
    _atomic_write(os.path.join(project_root, WATERMARK_REL), json.dumps(wm, ensure_ascii=False, indent=2))


def read_variance(project_root: str) -> list:
    """Read all variance records. Missing/empty/corrupt-line tolerant. Never raises."""
    path = os.path.join(project_root, VARIANCE_REL)
    records = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except (json.JSONDecodeError, ValueError):
                    continue
    except (FileNotFoundError, OSError):
        return []
    return records


def _append_variance(project_root: str, record: dict) -> None:
    """Append one record atomically (read-all + rewrite via tmp→replace)."""
    existing = read_variance(project_root)
    existing.append(record)
    body = "\n".join(json.dumps(r, ensure_ascii=False) for r in existing) + "\n"
    _atomic_write(os.path.join(project_root, VARIANCE_REL), body)


def _parse_iso(ts):
    if not isinstance(ts, str) or not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------------------- #
# capture (TASK-003)
# --------------------------------------------------------------------------- #
def capture(project_root: str, cycle_meta: dict, transcript_path: str | None = None,
            warn=None) -> dict | None:
    """Capture cycle-grain token actuals. Returns record dict, or None if skipped.

    cycle_meta: {spec_slug, spec_level(int|None), n_tasks(int|None)}
    Idempotency PRIMARY = empty range (rerun w/o new turns → skip, watermark unchanged).
    Never raises; warnings via `warn` callback (default: stderr).
    """
    warn = warn or (lambda m: print(f"[estimator] WARN: {m}", file=sys.stderr))
    if not _cfg(project_root, "enabled", True):
        return None  # disabled → no capture

    path = transcript_path or tt.find_transcript(project_root)
    if not path:
        warn("no transcript found → skip capture")
        return None

    turns = tt.iter_transcript_usage(path)
    if not turns:
        warn("transcript has no usage turns → skip capture")
        return None

    wm = _read_watermark(project_root) or {}
    last_uuid = wm.get("last_uuid")
    last_ts = wm.get("last_timestamp")

    # determine incremental range
    rng = None
    if last_uuid:
        idx = next((i for i, t in enumerate(turns) if t.get("uuid") == last_uuid), None)
        if idx is not None:
            rng = turns[idx + 1:]
        else:
            # uuid not in this file → transcript rotated / session switched: timestamp fallback
            warn("watermark uuid not in current transcript (rotation/session switch) → timestamp fallback")
            last_dt = _parse_iso(last_ts)
            if last_dt is None:
                rng = turns  # no usable anchor → take all
            else:
                # review Minor#1: null-timestamp turns in fallback are conservatively
                # INCLUDED (can't compare → assume new), not silently dropped.
                rng = [t for t in turns
                       if (_parse_iso(t.get("timestamp")) is None
                           or _parse_iso(t.get("timestamp")) > last_dt)]
    else:
        rng = turns  # first ever capture

    if not rng:
        # empty range = PRIMARY idempotency: no new turns → skip, watermark unchanged
        return None

    end = rng[-1]
    end_uuid = end.get("uuid") or "nouuid"
    spec_slug = cycle_meta.get("spec_slug") or "nospec"
    cycle_id = f"{spec_slug}-{str(end_uuid)[:8]}"

    # secondary guard: cycle_id already recorded (watermark/variance desync recovery)
    if any(r.get("cycle_id") == cycle_id for r in read_variance(project_root)):
        warn(f"cycle_id {cycle_id} already recorded (secondary guard) → skip append, reconcile watermark")
        _write_watermark(project_root, {
            "last_uuid": end_uuid, "last_timestamp": end.get("timestamp"),
            "session_id": end.get("session_id"), "transcript_path": path,
        })
        return None

    # accumulate raw components over range
    agg = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}
    for t in rng:
        u = t.get("usage", {})
        agg["input"] += u.get("input_tokens", 0) or 0
        agg["output"] += u.get("output_tokens", 0) or 0
        agg["cache_read"] += u.get("cache_read_input_tokens", 0) or 0
        agg["cache_creation"] += u.get("cache_creation_input_tokens", 0) or 0

    work_metric = agg["output"] + agg["cache_creation"]

    # wall_clock (passive metadata; null-safe; calendar-elapsed != effort)
    start_dt = _parse_iso(rng[0].get("timestamp"))
    end_dt = _parse_iso(end.get("timestamp"))
    wall_clock = int((end_dt - start_dt).total_seconds()) if (start_dt and end_dt) else None

    record = {
        "cycle_id": cycle_id,
        "spec": spec_slug,
        "spec_level": cycle_meta.get("spec_level"),
        "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "uuid_range": [rng[0].get("uuid"), end_uuid],
        "n_turns": len(rng),
        "n_tasks": cycle_meta.get("n_tasks"),
        "tokens": agg,
        "work_metric": work_metric,
        "wall_clock_seconds": wall_clock,
    }
    _append_variance(project_root, record)
    _write_watermark(project_root, {
        "last_uuid": end_uuid, "last_timestamp": end.get("timestamp"),
        "session_id": end.get("session_id"), "transcript_path": path,
    })
    return record


# --------------------------------------------------------------------------- #
# query (TASK-004)
# --------------------------------------------------------------------------- #
def _median(values: list):
    s = sorted(values)
    n = len(s)
    if n == 0:
        return None
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def _bootstrap_seed(project_root, spec_level):
    seed = _cfg(project_root, "bootstrap_seed", DEFAULT_BOOTSTRAP) or DEFAULT_BOOTSTRAP
    # review Minor#3: out-of-range level (e.g. future L0/L4) → fall back to a numeric
    # default so the insufficient response always carries a number (never null).
    return seed.get(f"L{spec_level}") or DEFAULT_BOOTSTRAP.get(f"L{spec_level}") or 200000


def forecast(project_root: str, spec_level) -> dict:
    """Forecast work_metric for a spec_level. cross-level isolated; null-safe."""
    if spec_level is None:
        return {"status": "insufficient", "reason": "no_spec_level"}
    min_samples = _cfg(project_root, "min_samples", DEFAULT_MIN_SAMPLES)
    same = [r.get("work_metric") for r in read_variance(project_root)
            if r.get("spec_level") == spec_level and isinstance(r.get("work_metric"), (int, float))]
    if len(same) >= min_samples:
        return {"status": "ok", "spec_level": spec_level, "n": len(same),
                "median_work_metric": _median(same)}
    return {"status": "insufficient", "spec_level": spec_level,
            "have": len(same), "need": min_samples,
            "bootstrap": _bootstrap_seed(project_root, spec_level), "uncalibrated": True}


def history(project_root: str) -> list:
    """All variance records (incl wall_clock, null-safe)."""
    return read_variance(project_root)


def velocity(project_root: str, window: int | None = None) -> list:
    """Recent `window` cycles by captured_at desc; work_metric + wall_clock two cols."""
    if window is None:
        window = _cfg(project_root, "window", DEFAULT_WINDOW)
    recs = read_variance(project_root)
    # review Minor#2: tie-break same-captured_at by end uuid for stable ordering
    recs = sorted(recs, key=lambda r: (r.get("captured_at") or "",
                                       (r.get("uuid_range") or ["", ""])[1] or ""),
                  reverse=True)[:window]
    return [{"cycle_id": r.get("cycle_id"), "spec_level": r.get("spec_level"),
             "work_metric": r.get("work_metric"), "wall_clock_seconds": r.get("wall_clock_seconds")}
            for r in recs]


# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ai-native-estimator (#18 v1)")
    ap.add_argument("--project-root", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pc = sub.add_parser("capture")
    pc.add_argument("--spec-slug", required=True)
    pc.add_argument("--spec-level", type=int, default=None)
    pc.add_argument("--n-tasks", type=int, default=None)
    pc.add_argument("--transcript", default=None)
    pf = sub.add_parser("forecast"); pf.add_argument("--spec-level", type=int, default=None)
    sub.add_parser("history")
    pv = sub.add_parser("velocity"); pv.add_argument("--window", type=int, default=None)
    args = ap.parse_args(argv)

    if args.cmd == "capture":
        r = capture(args.project_root, {"spec_slug": args.spec_slug,
                    "spec_level": args.spec_level, "n_tasks": args.n_tasks}, args.transcript)
        print(json.dumps(r, ensure_ascii=False, indent=2) if r else '{"skipped": true}')
    elif args.cmd == "forecast":
        print(json.dumps(forecast(args.project_root, args.spec_level), ensure_ascii=False, indent=2))
    elif args.cmd == "history":
        print(json.dumps(history(args.project_root), ensure_ascii=False, indent=2))
    elif args.cmd == "velocity":
        print(json.dumps(velocity(args.project_root, args.window), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

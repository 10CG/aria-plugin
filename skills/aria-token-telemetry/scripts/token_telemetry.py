#!/usr/bin/env python3
"""aria-token-telemetry — Claude Code context/token telemetry 共享数据层.

Internal skill 脚本 (user-invocable: false). 消费方:
  - aria-context-monitor (user-facing): 实时 context 占用
  - aria-plugin #18 ai-native-estimator: 复用 raw token counts (window-independent)

stdlib-only. 永不抛异常给消费方 — 所有失败 graceful degrade 到 unavailable / transcript fallback.

数据来源 3 档: relay cache (runtime-truth) > transcript JSONL (estimate) > unavailable.
window 大小 4 档 (transcript fallback 时): cached_size_reuse > config > empirical_peak > default.

口径不混用 (R1-S2):
  relay 路径   → used_percentage       (runtime 口径 total_input/window), proxy = null
  transcript 路径 → used_percentage_proxy ((input+cache_read+cache_creation)/window), used_percentage = null
  unavailable  → 两者皆 null
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

SCHEMA_VERSION = "1.0"

# Staleness 阈值 (TASK-006 固化常量). config context_monitor.staleness_threshold_seconds 可覆盖.
DEFAULT_STALENESS_THRESHOLD_SECONDS = 300

# window_source enum (TASK-006, 5 值). relay 命中恒 = runtime.
WINDOW_SOURCE_RUNTIME = "runtime"
WINDOW_SOURCE_CACHED_SIZE_REUSE = "cached_size_reuse"
WINDOW_SOURCE_CONFIG = "config"
WINDOW_SOURCE_EMPIRICAL_PEAK = "empirical_peak"
WINDOW_SOURCE_DEFAULT = "default"
WINDOW_SOURCE_ENUM = (
    WINDOW_SOURCE_RUNTIME,
    WINDOW_SOURCE_CACHED_SIZE_REUSE,
    WINDOW_SOURCE_CONFIG,
    WINDOW_SOURCE_EMPIRICAL_PEAK,
    WINDOW_SOURCE_DEFAULT,
)

DEFAULT_WINDOW_TOKENS = 200_000
# Known Claude Code window tiers (used by empirical_peak snap-to-fitting-tier).
KNOWN_WINDOW_TIERS = (200_000, 1_000_000)

RELAY_CACHE_REL = ".aria/cache/context-window.json"
CONFIG_REL = ".aria/config.json"

SOURCE_RELAY = "relay_cache"
SOURCE_TRANSCRIPT = "transcript_fallback"
SOURCE_UNAVAILABLE = "unavailable"


# --------------------------------------------------------------------------- #
# Config / helpers
# --------------------------------------------------------------------------- #
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_config(project_root: str) -> dict:
    """Load .aria/config.json context_monitor block. Never raises."""
    path = os.path.join(project_root, CONFIG_REL)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
        return cfg.get("context_monitor", {}) or {}
    except (FileNotFoundError, OSError, json.JSONDecodeError, ValueError, TypeError):
        return {}


def staleness_threshold(cm_config: dict) -> int:
    val = cm_config.get("staleness_threshold_seconds")
    if isinstance(val, (int, float)) and val > 0:
        return int(val)
    return DEFAULT_STALENESS_THRESHOLD_SECONDS


def _parse_iso(ts: str):
    """Parse ISO8601 (tolerant of trailing Z). Returns aware datetime or None."""
    if not isinstance(ts, str) or not ts:
        return None
    try:
        s = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------------------- #
# Relay cache path
# --------------------------------------------------------------------------- #
def read_relay_cache(project_root: str):
    """Read .aria/cache/context-window.json.

    Returns (cache_dict, error) where error is one of None / 'missing' /
    'corrupt' / 'schema_mismatch'. Never raises.
    """
    path = os.path.join(project_root, RELAY_CACHE_REL)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, OSError):
        return None, "missing"
    except (json.JSONDecodeError, ValueError):
        return None, "corrupt"
    if not isinstance(data, dict):
        return None, "corrupt"
    if data.get("schema_version") != SCHEMA_VERSION:
        return None, "schema_mismatch"
    return data, None


def _from_relay(cache: dict, threshold: int) -> dict | None:
    """Build telemetry result from a fresh relay cache, or None if stale/invalid."""
    captured_at = cache.get("captured_at")
    dt = _parse_iso(captured_at)
    if dt is None:
        return None
    staleness = int((_now() - dt).total_seconds())
    if staleness < 0:
        staleness = 0
    if staleness > threshold:
        return None  # stale → caller falls back to transcript

    size = cache.get("context_window_size")
    if not isinstance(size, (int, float)) or size <= 0:
        return None

    # Consistency (review Minor 1): relay path consumers read used_percentage; a high-confidence
    # relay result with used_percentage=null is contradictory. Require it present+numeric, else
    # fall back to transcript (symmetric with the size check above).
    used = cache.get("used_percentage")
    if not isinstance(used, (int, float)):
        return None

    return {
        "source": SOURCE_RELAY,
        "confidence": "high",
        "schema_version": SCHEMA_VERSION,
        "context_window_size": int(size),
        "window_source": WINDOW_SOURCE_RUNTIME,
        "used_percentage": cache.get("used_percentage"),
        "used_percentage_proxy": None,
        "remaining_percentage": cache.get("remaining_percentage"),
        "total_input_tokens": cache.get("total_input_tokens"),
        "current_usage": cache.get("current_usage"),
        "model_id": cache.get("model_id"),
        "exceeds_200k_tokens": cache.get("exceeds_200k_tokens"),
        "captured_at": captured_at,
        "staleness_seconds": staleness,
    }


# --------------------------------------------------------------------------- #
# Transcript fallback path
# --------------------------------------------------------------------------- #
def find_transcript(project_root: str) -> str | None:
    """Locate current session transcript JSONL deterministically.

    Path: ~/.claude/projects/{cwd-slug}/*.jsonl, newest by mtime.
    cwd-slug = abspath with '/' -> '-'. Never raises.
    """
    try:
        abs_root = os.path.abspath(project_root)
        slug = abs_root.replace("/", "-")
        base = os.path.join(os.path.expanduser("~/.claude/projects"), slug)
        if not os.path.isdir(base):
            return None
        candidates = [
            os.path.join(base, f) for f in os.listdir(base) if f.endswith(".jsonl")
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        return candidates[0]
    except OSError:
        return None


def parse_transcript_usage(jsonl_path: str) -> dict | None:
    """Parse last assistant-turn usage block from transcript JSONL.

    Returns raw counts dict (window-INDEPENDENT — this is the #18 estimator axis)
    or None if no usage found. Never raises.

      { input_tokens, output_tokens, cache_creation_input_tokens,
        cache_read_input_tokens, model }
    """
    if not jsonl_path:
        return None
    last_usage = None
    last_model = None
    try:
        with open(jsonl_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue  # tolerate partial/corrupt lines
                msg = rec.get("message") if isinstance(rec, dict) else None
                if not isinstance(msg, dict):
                    continue
                usage = msg.get("usage")
                if isinstance(usage, dict) and "input_tokens" in usage:
                    last_usage = usage
                    last_model = msg.get("model")
    except (FileNotFoundError, OSError):
        return None
    if last_usage is None:
        return None
    return {
        "input_tokens": last_usage.get("input_tokens", 0) or 0,
        "output_tokens": last_usage.get("output_tokens", 0) or 0,
        "cache_creation_input_tokens": last_usage.get("cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": last_usage.get("cache_read_input_tokens", 0) or 0,
        "model": last_model,
    }


def iter_transcript_usage(jsonl_path: str) -> list:
    """Iterate ALL assistant-turn usage records from transcript JSONL (#18 estimator).

    Unlike parse_transcript_usage (which returns only the LAST turn), this returns
    a per-turn list in file order, each carrying the record's uuid / timestamp /
    session_id alongside the raw usage. Used by ai-native-estimator for cycle-grain
    watermark range capture + wall_clock derivation. Never raises (returns [] on error).

    Returns: list[{
      "uuid": str|None, "timestamp": str|None, "session_id": str|None,
      "usage": { input_tokens, output_tokens,
                 cache_creation_input_tokens, cache_read_input_tokens },  # raw field names
    }]  in transcript order (only assistant records with a usage block).
    """
    if not jsonl_path:
        return []
    turns = []
    try:
        with open(jsonl_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue  # tolerate partial/corrupt lines
                if not isinstance(rec, dict) or rec.get("type") != "assistant":
                    continue
                msg = rec.get("message")
                if not isinstance(msg, dict):
                    continue
                usage = msg.get("usage")
                if not (isinstance(usage, dict) and "input_tokens" in usage):
                    continue
                turns.append({
                    "uuid": rec.get("uuid"),
                    "timestamp": rec.get("timestamp"),
                    "session_id": rec.get("sessionId"),
                    "usage": {
                        "input_tokens": usage.get("input_tokens", 0) or 0,
                        "output_tokens": usage.get("output_tokens", 0) or 0,
                        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0) or 0,
                        "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0) or 0,
                    },
                })
    except (FileNotFoundError, OSError):
        return []
    return turns


def resolve_window(usage: dict, cm_config: dict, last_known_size) -> tuple[int, str]:
    """Resolve window size for transcript fallback. Returns (size, window_source).

    Priority: cached_size_reuse > config > empirical_peak > default.
    """
    # 1. cached_size_reuse — last relay-observed size (session-invariant)
    if isinstance(last_known_size, (int, float)) and last_known_size > 0:
        return int(last_known_size), WINDOW_SOURCE_CACHED_SIZE_REUSE
    # 2. config
    cfg_win = cm_config.get("window_tokens")
    if isinstance(cfg_win, (int, float)) and cfg_win > 0:
        return int(cfg_win), WINDOW_SOURCE_CONFIG
    # 3. empirical_peak — smallest known tier that fits observed input
    occupancy = (
        (usage.get("input_tokens") or 0)
        + (usage.get("cache_read_input_tokens") or 0)
        + (usage.get("cache_creation_input_tokens") or 0)
    )
    if occupancy > 0:
        for tier in sorted(KNOWN_WINDOW_TIERS):
            if occupancy <= tier:
                return tier, WINDOW_SOURCE_EMPIRICAL_PEAK
        # exceeds all known tiers → use largest known tier
        return max(KNOWN_WINDOW_TIERS), WINDOW_SOURCE_EMPIRICAL_PEAK
    # 4. default
    return DEFAULT_WINDOW_TOKENS, WINDOW_SOURCE_DEFAULT


def _from_transcript(project_root: str, cm_config: dict, last_known_size) -> dict | None:
    """Build telemetry result from transcript usage, or None if unavailable."""
    jsonl = find_transcript(project_root)
    usage = parse_transcript_usage(jsonl) if jsonl else None
    if usage is None:
        return None

    window, window_source = resolve_window(usage, cm_config, last_known_size)
    occupancy = (
        (usage.get("input_tokens") or 0)
        + (usage.get("cache_read_input_tokens") or 0)
        + (usage.get("cache_creation_input_tokens") or 0)
    )
    proxy = round(100.0 * occupancy / window, 1) if window > 0 else None
    remaining = round(100.0 - proxy, 1) if proxy is not None else None

    return {
        "source": SOURCE_TRANSCRIPT,
        "confidence": "estimate",
        "schema_version": SCHEMA_VERSION,
        "context_window_size": window,
        "window_source": window_source,
        "used_percentage": None,            # 口径不混用: transcript 不填 used_percentage
        "used_percentage_proxy": proxy,
        "remaining_percentage": remaining,
        "total_input_tokens": usage.get("input_tokens"),
        "current_usage": {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
        },
        "model_id": usage.get("model"),     # NOTE: transcript model 丢 [1m] 后缀 (见 schema.md)
        "exceeds_200k_tokens": occupancy > 200_000,
        "captured_at": None,
        "staleness_seconds": None,
    }


def _unavailable() -> dict:
    return {
        "source": SOURCE_UNAVAILABLE,
        "confidence": "estimate",
        "schema_version": SCHEMA_VERSION,
        "context_window_size": None,
        "window_source": None,
        "used_percentage": None,
        "used_percentage_proxy": None,      # 一致性: unavailable 态两者皆 null (R2-m3)
        "remaining_percentage": None,
        "total_input_tokens": None,
        "current_usage": None,
        "model_id": None,
        "exceeds_200k_tokens": None,
        "captured_at": None,
        "staleness_seconds": None,
    }


# --------------------------------------------------------------------------- #
# Public entry
# --------------------------------------------------------------------------- #
def collect(project_root: str = ".") -> dict:
    """Collect full telemetry, applying 3-tier fallback. Never raises."""
    cm_config = _load_config(project_root)
    threshold = staleness_threshold(cm_config)

    cache, _err = read_relay_cache(project_root)
    last_known_size = None
    if cache is not None:
        # even if stale, the size is reusable for cached_size_reuse
        sz = cache.get("context_window_size")
        if isinstance(sz, (int, float)) and sz > 0:
            last_known_size = int(sz)
        fresh = _from_relay(cache, threshold)
        if fresh is not None:
            return fresh

    transcript_result = _from_transcript(project_root, cm_config, last_known_size)
    if transcript_result is not None:
        return transcript_result

    return _unavailable()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="aria-token-telemetry collector")
    ap.add_argument("--project-root", default=".", help="project root (default cwd)")
    ap.add_argument("--json", action="store_true", help="emit JSON (default)")
    args = ap.parse_args(argv)
    result = collect(project_root=args.project_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

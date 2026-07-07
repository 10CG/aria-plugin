#!/usr/bin/env python3
"""Generalized runtime-invocation probe (#95 follow-up A, TASK-001/002).

Spec: openspec/changes/runtime-probe-archive-gate-integration/proposal.md
      (§What Changes ①② — DEC-20260705-001)

Generalizes the single-purpose ``coordination_probe.py`` (DEC-20260704-002,
TASK-012) into a reusable library: any spec can declare a ``runtime_probe``
frontmatter block (partition/symbol/max_age_days/enabled_when) asking "has
my production entry point really been invoked recently, or is it wired-but-
dead?" ``coordination_probe.py`` becomes the first (and, pre-#95, only)
caller — see that module for the concrete coordination descriptor.

Two entry points:

    validate_descriptor(fields, repo) -> {"status": "ok", "descriptor": {...}}
                                        | {"status": "invalid", "reason": str}

    probe(descriptor, repo, now) -> {"outcome": "pass"|"warn"|"skipped"|"invalid",
                                      "count": int, "reason": str, "symbol": str}

Division of labor between the two invalid-declaration checks (five forms
total, proposal §What 2 / SC-5):
  ``validate_descriptor`` owns the four forms decidable from the declaration
  alone (missing required field / wrong type / ``max_age_days`` <= 0 /
  ``partition`` escapes ``repo``). The fifth form — ``enabled_when``
  dotted-path resolving through a non-dict value — can only be decided once
  the REAL ``.aria/config.json`` content is loaded, which only happens
  inside ``probe()``; that path returns ``outcome="invalid"`` for the same
  reason (归清晰「声明无效」类, 每级 ``.get`` 防御, 不落外层异常兜底).

``fields`` passed to ``validate_descriptor`` is expected to be the raw
string dict produced by the text-layer restricted-YAML-subset parser (TG-2,
a parallel task — not imported here; this module is a stdlib-only leaf with
ZERO upstream imports, per the interface contract shared with TG-3's
``spec_complete.py``). This layer owns type conversion (e.g. ``max_age_days``
``str`` → ``int``) plus validation. Unknown extra scalar keys are tolerated
(ignored, not treated as invalid) — a deliberate leniency choice recorded
here for pre-merge review, not enforced schema strictness.

``probe()`` reuses the exact parsing semantics ``coordination_probe.py``
already established: malformed JSONL lines are skipped, not fatal; only
``source == "production"`` records count; a record only counts if its ``ts``
falls within ``max_age_days`` of the injected ``now`` (tz-naive values are
normalized to UTC — this exists so tests can inject a fixed clock
deterministically). ``symbol`` is a message label only — it does NOT filter
records (a partition is scoped to one mechanism by convention; no record-
level ``symbol`` field is read).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

_DEFAULT_MAX_AGE_DAYS = 14
_CONFIG_REL_PATH = (".aria", "config.json")


# ---------------------------------------------------------------------------
# TASK-001 — descriptor validation (value layer, four of five invalid forms)
# ---------------------------------------------------------------------------


def validate_descriptor(fields: dict, repo: Path) -> dict:
    """校验 + 类型转换 runtime_probe frontmatter 声明 (值层, SC-5 值层五形态之四)。

    Returns ``{"status": "ok", "descriptor": {partition, symbol, max_age_days,
    enabled_when}}`` (typed: ``partition``/``symbol`` ``str``, ``max_age_days``
    ``int``, ``enabled_when`` ``str`` or ``None``) or ``{"status": "invalid",
    "reason": str}``. Never raises for malformed input — "不猜不硬崩".
    """
    if not isinstance(fields, dict):
        return {
            "status": "invalid",
            "reason": f"descriptor must be a mapping, got {type(fields).__name__}",
        }

    # --- partition (required; relative; must resolve inside repo) ---
    partition = fields.get("partition")
    if partition is None or partition == "":
        return {"status": "invalid", "reason": "missing required field: partition"}
    if not isinstance(partition, str):
        return {
            "status": "invalid",
            "reason": f"partition must be a string, got {type(partition).__name__}",
        }

    partition_path = Path(partition)
    if partition_path.is_absolute():
        # pathlib 陷阱: repo / "/abs/path" 会静默丢弃 repo 前缀直接变成
        # "/abs/path" (Path.__truediv__ 对绝对右操作数的语义) — 必须在
        # join 之前单独判定绝对路径, 不能指望后续 is_relative_to 兜底。
        return {
            "status": "invalid",
            "reason": f"partition must be a relative path, got absolute: {partition!r}",
        }
    try:
        resolved = (repo / partition_path).resolve()
        repo_resolved = repo.resolve()
    except OSError as e:
        return {"status": "invalid", "reason": f"partition path resolution failed: {e}"}
    if not resolved.is_relative_to(repo_resolved):
        return {
            "status": "invalid",
            "reason": f"partition resolves outside repo: {partition!r}",
        }

    # --- symbol (required) ---
    symbol = fields.get("symbol")
    if symbol is None or symbol == "":
        return {"status": "invalid", "reason": "missing required field: symbol"}
    if not isinstance(symbol, str):
        return {
            "status": "invalid",
            "reason": f"symbol must be a string, got {type(symbol).__name__}",
        }

    # --- max_age_days (optional, default 14, positive int; raw value may be
    #     a string per the text-layer contract, hence the str->int conversion
    #     this layer owns) ---
    raw_max_age = fields.get("max_age_days", _DEFAULT_MAX_AGE_DAYS)
    if isinstance(raw_max_age, bool):  # bool is an int subclass — guard first
        return {
            "status": "invalid",
            "reason": f"max_age_days must be an integer, got bool: {raw_max_age!r}",
        }
    if isinstance(raw_max_age, int):
        max_age_days = raw_max_age
    elif isinstance(raw_max_age, str):
        try:
            max_age_days = int(raw_max_age.strip())
        except ValueError:
            return {
                "status": "invalid",
                "reason": f"max_age_days must be an integer, got: {raw_max_age!r}",
            }
    else:
        return {
            "status": "invalid",
            "reason": (
                f"max_age_days must be an integer, got "
                f"{type(raw_max_age).__name__}: {raw_max_age!r}"
            ),
        }
    if max_age_days <= 0:
        return {
            "status": "invalid",
            "reason": f"max_age_days must be >= 1, got: {max_age_days}",
        }

    # --- enabled_when (optional; dotted-path string; middle-segment-not-dict
    #     form is NOT decidable here — see probe()/_resolve_enabled_when) ---
    enabled_when = fields.get("enabled_when")
    if enabled_when in (None, ""):
        enabled_when = None
    elif not isinstance(enabled_when, str):
        return {
            "status": "invalid",
            "reason": f"enabled_when must be a string, got {type(enabled_when).__name__}",
        }

    return {
        "status": "ok",
        "descriptor": {
            "partition": partition,
            "symbol": symbol,
            "max_age_days": max_age_days,
            "enabled_when": enabled_when,
        },
    }


# ---------------------------------------------------------------------------
# internal helpers shared by probe() and coordination_probe.py's legacy shim
# ---------------------------------------------------------------------------


def _parse_ts(value) -> "datetime | None":
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _load_config(repo: Path) -> "dict | None":
    """Load ``.aria/config.json``. Returns ``None`` on ANY failure (missing /
    unreadable / malformed JSON / top-level not an object) — proposal text
    deliberately lumps "缺失/读不到" together into one conservative bucket
    (caller treats this as ``skipped`` + low-key note, never ``warn``)."""
    cfg_path = repo / _CONFIG_REL_PATH[0] / _CONFIG_REL_PATH[1]
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _resolve_enabled_when(config: dict, dotted_path: str) -> dict:
    """Walk ``dotted_path`` through ``config`` one segment at a time.

    A missing key at any level means "switch not configured" = off (not an
    error — config authors are not required to mention every optional
    switch). A non-dict value that we then need to descend INTO is the fifth
    invalid form (SC-5 值层五形态之五) — defended at every level via
    ``isinstance`` before indexing, never via a blanket except.

    Returns ``{"status": "ok", "value": <resolved leaf, or False if unset>}``
    or ``{"status": "invalid", "reason": str}``.
    """
    node = config
    for seg in dotted_path.split("."):
        if not isinstance(node, dict):
            return {
                "status": "invalid",
                "reason": (
                    f"enabled_when {dotted_path!r}: segment {seg!r} unreachable "
                    f"(parent resolved to {type(node).__name__}, expected object)"
                ),
            }
        if seg not in node:
            return {"status": "ok", "value": False}
        node = node[seg]
    return {"status": "ok", "value": node}


def _scan_partition(partition_path: Path, *, max_age_days: int, now: datetime) -> dict:
    """JSONL production-partition scan — the single SOT for both ``probe()``
    and ``coordination_probe.py``'s backward-compat ``count_production_invocations``
    shim (never duplicate this parse loop).

    Malformed JSON lines are skipped, not fatal. Only ``source == "production"``
    records are considered. A record is RECENT iff its ``ts`` parses and falls
    within ``[now - max_age_days, now]``.

    Returns one of:
      ``{"status": "missing"}``
      ``{"status": "unreadable", "error": str}``
      ``{"status": "ok", "recent_count": int, "saw_any_production": bool}``
    """
    if not partition_path.exists():
        return {"status": "missing"}
    try:
        text = partition_path.read_text(encoding="utf-8")
    except Exception as e:  # 沿用既有宽异常面 (原 coordination_probe.py 同型 try/except)
        return {"status": "unreadable", "error": str(e)}

    ref = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    cutoff = ref - timedelta(days=max_age_days)

    recent_count = 0
    saw_any_production = False
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue  # 坏行跳过不 fatal
        if not (isinstance(rec, dict) and rec.get("source") == "production"):
            continue
        saw_any_production = True
        ts = _parse_ts(rec.get("ts"))
        if ts is None or ts < cutoff:
            continue
        recent_count += 1

    return {"status": "ok", "recent_count": recent_count, "saw_any_production": saw_any_production}


# ---------------------------------------------------------------------------
# TASK-002 — probe(): tri-state (+ config-traversal invalid) liveness verdict
# ---------------------------------------------------------------------------


def probe(descriptor: dict, repo: Path, now: datetime) -> dict:
    """Runtime-invocation liveness check for one declared probe.

    ``descriptor`` is expected to be the typed descriptor returned by a
    successful ``validate_descriptor()`` call (``partition``/``symbol``
    already guaranteed valid; ``enabled_when`` is ``str`` or ``None``); this
    function does not re-validate those invariants (upstream's job — this
    keeps the "declaration invalid" taxonomy single-sourced in
    ``validate_descriptor``). It DOES defensively ``.get()`` with sane
    fallbacks so a directly-constructed descriptor degrades gracefully
    (worst case: probes an empty/odd partition path) rather than raising.

    outcome semantics:
      "pass"    — >=1 RECENT production record found.
      "warn"    — partition missing / exists-but-unreadable (IO error, the
                  fixed false-green edge) / all records stale / only
                  non-production records found.
      "skipped" — enabled_when switch resolved to a falsy value (including
                  "key not configured"), OR config file missing/unreadable
                  (conservative: cannot confirm the switch should be on, so
                  don't cry warn — 低调 note only).
      "invalid" — enabled_when dotted-path hit a non-dict mid-path value in
                  the REAL config content (fifth invalid form; only
                  decidable here, see module docstring).

    Returns ``{"outcome": ..., "count": int, "reason": str, "symbol": str}``.
    """
    symbol = descriptor.get("symbol", "")
    max_age_days = descriptor.get("max_age_days", _DEFAULT_MAX_AGE_DAYS)
    partition = descriptor.get("partition", "")

    enabled_when = descriptor.get("enabled_when")
    if enabled_when and isinstance(enabled_when, str):
        config = _load_config(repo)
        if config is None:
            return {
                "outcome": "skipped",
                "count": 0,
                "reason": "config file missing or unreadable (assumed off)",
                "symbol": symbol,
            }
        switch = _resolve_enabled_when(config, enabled_when)
        if switch["status"] == "invalid":
            return {"outcome": "invalid", "count": 0, "reason": switch["reason"], "symbol": symbol}
        if not switch["value"]:
            return {
                "outcome": "skipped",
                "count": 0,
                "reason": f"enabled_when {enabled_when!r} config switch is off",
                "symbol": symbol,
            }
        # switch is on → fall through to partition probing below

    partition_path = repo / partition
    scan = _scan_partition(partition_path, max_age_days=max_age_days, now=now)

    if scan["status"] == "missing":
        return {
            "outcome": "warn",
            "count": 0,
            "reason": f"production telemetry partition missing: {partition}",
            "symbol": symbol,
        }
    if scan["status"] == "unreadable":
        return {
            "outcome": "warn",
            "count": 0,
            "reason": (
                f"production telemetry partition unreadable (IO error): "
                f"{partition}: {scan['error']}"
            ),
            "symbol": symbol,
        }

    n = scan["recent_count"]
    if n >= 1:
        return {
            "outcome": "pass",
            "count": n,
            "reason": f"{n} recent production {symbol!r} record(s) within {max_age_days}d",
            "symbol": symbol,
        }
    if scan["saw_any_production"]:
        return {
            "outcome": "warn",
            "count": 0,
            "reason": f"no production {symbol!r} record within {max_age_days}d (all stale)",
            "symbol": symbol,
        }
    return {
        "outcome": "warn",
        "count": 0,
        "reason": (
            f"no production-sourced {symbol!r} record found "
            "(only non-production and/or malformed lines)"
        ),
        "symbol": symbol,
    }

"""Phase 1 (multi-terminal-coordination) — coordination fetch collector.

Runs `git fetch <remote> refs/heads/* refs/aria/coordination --no-tags`
and caches the fetch timestamp in `.aria/cache/coordination-fetch.json`
with a 30-second TTL so rapid successive scans skip redundant network I/O.

Return schema (top-level key: `coordination_fetch`):

    {
        "success": bool,              # True when fetch ran or cache was fresh
        "cached": bool,               # True when TTL not expired — no fetch ran;
                                      # also True when fetch fails but stale cache
                                      # is returned (degraded mode, TASK-007)
        "last_fetch_at": str,         # ISO 8601 UTC of the last successful fetch
        "age_seconds": int,           # Seconds since last_fetch_at (0 if never fetched)
        "refs_fetched": list[str],    # Refspecs attempted; empty on error or cache hit
        "error_kind": str | None,     # "network" | "auth_403" | "non_ff" | "git_missing"
                                      # | "other" | None (success path)
        "error_msg": str | None,      # Human-readable detail; None on success
        "degraded": bool,             # TASK-007: True when fetch failed but stale cache
                                      # data is being served in its place.
                                      # Renderer consumer should display a top-bar:
                                      # "⚠ 离线: 看板可能陈旧, 重复劳动风险升高"
        "degradation_reason": str | None,  # TASK-007: "fetch_failed_using_stale_cache"
                                           # when degraded=True, else None
    }

Design notes:
- Deliberately does NOT raise on any error — all errors surface via `success=False`
  and/or `degraded=True` fields.  The board renderer (TASK-005) reads the
  `degraded` signal and renders the offline red-bar; this collector only provides
  the signal.
- Cache path is `.aria/cache/coordination-fetch.json` relative to project_root.
  The `.aria/cache/` directory is created silently if absent.
- A corrupt or non-JSON cache file is treated as absent → normal fetch.
- Rule #7 compliance: subprocess uses `capture_output=True`; stdout/stderr are
  never printed. Error details are coerced to short, non-secret strings.
- Degradation semantics (TASK-007):
    * fetch fail + stale cache present  → success=False, cached=True,
                                          degraded=True,
                                          degradation_reason="fetch_failed_using_stale_cache"
    * fetch fail + no cache at all      → success=False, cached=False,
                                          degraded=False, degradation_reason=None
    * cache fresh (TTL not expired)     → success=True,  cached=True,
                                          degraded=False, degradation_reason=None
    * fetch success                     → success=True,  cached=False,
                                          degraded=False, degradation_reason=None

Example (for TASK-008 test authoring):
    # fetch fail + stale cache → degraded
    # subprocess returns rc=128, cache exists with last_fetch_at=10 min ago
    # → success=False, cached=True, degraded=True,
    #   degradation_reason="fetch_failed_using_stale_cache"

Spec: openspec/changes/multi-terminal-coordination/tasks.md §1.3, §1.7
Tasks: TASK-003 (backend-architect), TASK-007 (backend-architect)
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from ._common import CollectorResult, _run, log

# ── Constants ────────────────────────────────────────────────────────────────

FETCH_CACHE_TTL: int = 30  # seconds — skip fetch if last fetch was < TTL ago

COORDINATION_REF: str = "refs/aria/coordination"

# Refspecs passed to git fetch
_FETCH_REFSPECS: list[str] = ["refs/heads/*", COORDINATION_REF]

# Cache file location relative to project_root
_CACHE_RELATIVE: str = ".aria/cache/coordination-fetch.json"

# Cache file schema key names (kept compact for readability)
_CACHE_KEY_LAST_FETCH_AT: str = "last_fetch_at"
_CACHE_KEY_REFS: str = "refs"

# git exit code sentinels (from _run convention: rc=127 → command not found)
_RC_COMMAND_NOT_FOUND: int = 127


# ── Cache helpers ─────────────────────────────────────────────────────────────


def _cache_path(project_root: Path) -> Path:
    return project_root / _CACHE_RELATIVE


def _read_cache(cache_file: Path) -> dict | None:
    """Read and parse the fetch cache file.

    Returns the parsed dict on success, or None if:
    - file does not exist
    - file cannot be read (permission error)
    - file content is not valid JSON (corrupt)
    """
    if not cache_file.is_file():
        return None
    try:
        raw = cache_file.read_text(encoding="utf-8", errors="replace")
        return json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        log.debug("coordination_fetch: cache unreadable or corrupt (%s), treating as absent", exc)
        return None


def _write_cache(cache_file: Path, last_fetch_at_iso: str, refs: list[str]) -> None:
    """Write fetch timestamp + refs to cache file.

    Creates `.aria/cache/` silently if absent.  Errors are swallowed — a
    write failure means the next call will re-run fetch, which is safe.
    """
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            _CACHE_KEY_LAST_FETCH_AT: last_fetch_at_iso,
            _CACHE_KEY_REFS: refs,
        }
        cache_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as exc:
        log.warning("coordination_fetch: failed to write cache (%s); next call will re-fetch", exc)


def _iso_now_utc() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def _parse_iso_utc(iso: str) -> float | None:
    """Parse an ISO 8601 UTC string to a POSIX timestamp float, or None."""
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            # Treat naive timestamps as UTC (defensive)
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


# ── Error classification ──────────────────────────────────────────────────────


def _classify_error(rc: int, stderr: str) -> tuple[str, str]:
    """Map a git fetch non-zero exit to an (error_kind, error_msg) pair.

    Callers must have already confirmed rc != 0.
    error_msg is kept short and non-secret (no env var values, no tokens).
    """
    if rc == _RC_COMMAND_NOT_FOUND:
        return "git_missing", "git command not found in PATH"

    stderr_lower = stderr.lower()

    # Authentication failures (HTTP 401/403 or SSH key rejection)
    if "403" in stderr or "401" in stderr or "authentication failed" in stderr_lower:
        return "auth_403", f"git fetch authentication error (rc={rc})"

    # Non-fast-forward (someone force-pushed or orphan ref rewound)
    if "non-fast-forward" in stderr_lower or "rejected" in stderr_lower:
        return "non_ff", f"git fetch rejected / non-fast-forward (rc={rc})"

    # Network-level failures (DNS, TCP, SSL, timeout)
    network_signals = (
        "could not resolve",
        "connection refused",
        "timed out",
        "ssl",
        "network",
        "unable to connect",
        "fatal: repository",
    )
    if any(sig in stderr_lower for sig in network_signals):
        return "network", f"git fetch network error (rc={rc})"

    # Fall through to generic
    return "other", f"git fetch failed with rc={rc}"


# ── Public entry point ────────────────────────────────────────────────────────


def collect_coordination_fetch(
    project_root: Path,
    remote: str = "origin",
) -> CollectorResult:
    """Fetch coordination refs with 30-second TTL cache.

    Args:
        project_root: Absolute path to the project root (passed by scan.py).
        remote:       git remote name (default: "origin"; injectable for tests).

    Returns a CollectorResult whose `.data` dict matches the schema documented
    in the module docstring.  Never raises — all errors are surfaced via
    `r.soft_error` and the returned `success=False` / `error_kind` fields.
    """
    r = CollectorResult()
    now_ts = time.time()
    cache_file = _cache_path(project_root)
    cache = _read_cache(cache_file)

    # ── TTL check: skip fetch if cache is fresh ───────────────────────────────
    if cache is not None:
        last_fetch_iso: str | None = cache.get(_CACHE_KEY_LAST_FETCH_AT)
        if last_fetch_iso:
            last_ts = _parse_iso_utc(last_fetch_iso)
            if last_ts is not None:
                age = int(now_ts - last_ts)
                if age < FETCH_CACHE_TTL:
                    log.debug(
                        "coordination_fetch: cache fresh (%ds < %ds TTL), skipping fetch",
                        age,
                        FETCH_CACHE_TTL,
                    )
                    r.data = {
                        "success": True,
                        "cached": True,
                        "last_fetch_at": last_fetch_iso,
                        "age_seconds": age,
                        "refs_fetched": [],
                        "error_kind": None,
                        "error_msg": None,
                        "degraded": False,
                        "degradation_reason": None,
                    }
                    return r

    # ── Run git fetch ─────────────────────────────────────────────────────────
    cmd = ["git", "fetch", remote, "--no-tags"] + _FETCH_REFSPECS
    log.debug("coordination_fetch: running %s (cwd=%s)", " ".join(cmd), project_root)

    rc, _stdout, stderr = _run(cmd, cwd=project_root, timeout=30)

    fetch_at_iso = _iso_now_utc()

    if rc == 0:
        # Success: update cache and return success payload
        _write_cache(cache_file, fetch_at_iso, _FETCH_REFSPECS)
        r.data = {
            "success": True,
            "cached": False,
            "last_fetch_at": fetch_at_iso,
            "age_seconds": 0,
            "refs_fetched": list(_FETCH_REFSPECS),
            "error_kind": None,
            "error_msg": None,
            "degraded": False,
            "degradation_reason": None,
        }
        return r

    # ── Fetch failed ──────────────────────────────────────────────────────────
    # rc=124 = timeout (from _run); classify alongside other errors.
    error_kind, error_msg = (
        ("network", f"git fetch timed out after 30s (rc=124)")
        if rc == 124
        else _classify_error(rc, stderr)
    )

    log.warning("coordination_fetch: fetch failed — kind=%s msg=%s", error_kind, error_msg)
    r.soft_error("coordination_fetch_failed", f"{error_kind}: {error_msg}")

    # ── TASK-007: Offline degradation ─────────────────────────────────────────
    # If a stale cache entry exists (even though its TTL has expired), serve the
    # cached data and set degraded=True so the board renderer can display the
    # offline red-bar: "⚠ 离线: 看板可能陈旧, 重复劳动风险升高"
    #
    # Stale cache is only used when the JSON parsed successfully; a corrupt cache
    # is treated as absent (per _read_cache contract) → degraded=False path.
    #
    # Note: _write_cache is NOT called here — we must not overwrite a valid
    # stale entry with a failed-fetch timestamp.
    stale_last_fetch_iso: str = ""
    stale_age: int = 0
    has_usable_stale_cache: bool = False

    if cache is not None:
        cached_iso = cache.get(_CACHE_KEY_LAST_FETCH_AT, "")
        if cached_iso:
            stale_ts = _parse_iso_utc(cached_iso)
            if stale_ts is not None:
                stale_last_fetch_iso = cached_iso
                stale_age = int(now_ts - stale_ts)
                has_usable_stale_cache = True

    if has_usable_stale_cache:
        # Degraded mode: fetch failed but stale cache is available.
        log.warning(
            "coordination_fetch: serving stale cache (age=%ds) in degraded mode",
            stale_age,
        )
        r.soft_error(
            "coordination_fetch_degraded",
            f"fetch failed ({error_kind}); serving stale cache aged {stale_age}s",
        )
        r.data = {
            "success": False,
            "cached": True,
            "last_fetch_at": stale_last_fetch_iso,
            "age_seconds": stale_age,
            "refs_fetched": [],
            "error_kind": error_kind,
            "error_msg": error_msg,
            "degraded": True,
            "degradation_reason": "fetch_failed_using_stale_cache",
        }
    else:
        # No cache at all — pure failure, no data to serve.
        r.data = {
            "success": False,
            "cached": False,
            "last_fetch_at": stale_last_fetch_iso,
            "age_seconds": stale_age,
            "refs_fetched": [],
            "error_kind": error_kind,
            "error_msg": error_msg,
            "degraded": False,
            "degradation_reason": None,
        }
    return r

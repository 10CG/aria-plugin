"""Phase 1 (multi-terminal-coordination) — coordination fetch collector.

Runs TWO independent fetches (v1.46.0, Forgejo Aria #141 / aria-plugin #75):

  1. Fetch 1 (load-bearing): `git fetch <remote> --no-tags +refs/heads/*:refs/remotes/<remote>/*`
  2. Fetch 2 (coordination):  `git fetch <remote> --no-tags refs/aria/coordination`

Splitting them fixes a confirmed bug: bundling both into ONE atomic fetch made the
whole fetch fail rc=128 on any remote that never published `refs/aria/coordination`
(most non-multi-terminal projects), dropping the branch heads with it.  Now a
benign-absent coordination ref (Fetch 2) no longer breaks the branch-head refresh
(Fetch 1).  The fetch timestamp is cached in `.aria/cache/coordination-fetch.json`
with a 30-second TTL so rapid successive scans skip redundant network I/O.

Return schema (top-level key: `coordination_fetch`):

    {
        "success": bool,              # Reflects Fetch 1 (branch heads); True when it
                                      # ran successfully or the cache was fresh
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
        "coordination_ref_present": bool | None,  # v1.46.0 (#141): Fetch 2 outcome.
                                           # True  = coordination ref fetched
                                           # False = benign absent (not published)
                                           # None  = unknown (Fetch 1 failed → Fetch 2
                                           #         short-circuited, OR Fetch 2 failed
                                           #         non-benign).  Persisted in cache so
                                           #         cache-hit / stale-serve stay stable.
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
- Two-fetch semantics (v1.46.0, #141) — success/degraded anchor to Fetch 1:
    * Fetch 1 fail + stale cache        → success=False, cached=True, degraded=True,
                                          degradation_reason="fetch_failed_using_stale_cache",
                                          coordination_ref_present=<stale cache value>
                                          (Fetch 2 short-circuited — remote unusable)
    * Fetch 1 fail + no cache at all     → success=False, cached=False, degraded=False,
                                          coordination_ref_present=None
    * cache fresh (TTL not expired)      → success=True,  cached=True, degraded=False,
                                          coordination_ref_present=<cache value>
    * Fetch 1 ok + Fetch 2 ok            → success=True,  coordination_ref_present=True
    * Fetch 1 ok + Fetch 2 benign-absent → success=True,  coordination_ref_present=False,
                                          NO soft_error (coordination simply not published)
    * Fetch 1 ok + Fetch 2 non-benign    → success=True,  coordination_ref_present=None,
                                          soft_error("coordination_ref_fetch_failed", ...)
- benign-absent gate (Fetch 2): `_is_benign_coordination_absent` — rc==128 AND
  "couldn't find remote ref" AND "refs/aria/coordination" in stderr (all three),
  evaluated BEFORE `_classify_error`.  A missing coordination ref is NORMAL, not a
  fetch failure — the root cause of #141.

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


def _branch_heads_refspec(remote: str) -> str:
    """Refspec for the load-bearing branch-head fetch (Fetch 1).

    Wildcards in refspecs require the explicit ``src:dst`` form per git-fetch(1);
    the single-src ``refs/heads/*`` form is **invalid** (``fatal: invalid refspec``,
    rc=128).  Fix for Forgejo aria-plugin #57 Finding 1 (2026-05-28).

    Split out from coordination ref (Forgejo Aria #141 / aria-plugin #75,
    v1.46.0): bundling ``refs/aria/coordination`` into the same atomic fetch made
    the whole fetch fail rc=128 on remotes that never published the coordination
    ref (most non-multi-terminal projects), dropping the branch heads with it.
    """
    return f"+refs/heads/*:refs/remotes/{remote}/*"


def _is_benign_coordination_absent(rc: int, stderr: str) -> bool:
    """True when a Fetch 2 failure is the benign "coordination ref not published" case.

    Triple-AND gate (post_spec R1 OQ4, Forgejo Aria #141): a missing
    ``refs/aria/coordination`` on the remote is a NORMAL condition (the project
    simply does not use multi-terminal coordination), NOT a fetch failure.  All
    three must hold, evaluated BEFORE ``_classify_error`` (which would otherwise
    map rc=128 to "other"):

      1. ``rc == 128``                            — git's "ref not found" exit
      2. ``couldn't find remote ref`` in stderr   — git client-side wording,
         emitted at ref-advertisement time, server-agnostic (Forgejo/GitHub/SSH)
      3. ``refs/aria/coordination`` in stderr     — it is OUR ref that is absent,
         not some other concrete ref

    Narrow by design — a genuine network/auth/timeout failure (rc=124/127, or
    rc=128 with different wording) is NOT benign and must surface via soft_error.

    Known limitations (code-review #141, tracked as follow-ups F3/F4):
    - git cannot distinguish "ref absent" from "ref hidden by server-side ACL /
      uploadpack.hideRefs" — both emit "couldn't find remote ref".  An auth-masked
      coordination ref would read here as benign-absent.  NOT reachable in Aria's
      Forgejo deployment (repo-level read ACL governs refs/aria/* too, so a masked
      ref implies Fetch 1 already failed); `git ls-remote --exit-code` disambiguation
      is a follow-up.
    - the substring assumes English git output; callers run under an effective C
      locale.  `LC_ALL=C` hardening of `_run` is a follow-up.
    """
    if rc != 128:
        return False
    stderr_lower = stderr.lower()
    return (
        "couldn't find remote ref" in stderr_lower
        and COORDINATION_REF.lower() in stderr_lower
    )

# Cache file location relative to project_root
_CACHE_RELATIVE: str = ".aria/cache/coordination-fetch.json"

# Cache file schema key names (kept compact for readability)
_CACHE_KEY_LAST_FETCH_AT: str = "last_fetch_at"
_CACHE_KEY_REFS: str = "refs"
# v1.46.0 (#141): persisted so the cache-hit / stale-serve paths return a STABLE
# coordination_ref_present (else it would appear only on fetch-runs and disappear
# on cache-hits → normalize_snapshot two-consecutive-runs drift).
_CACHE_KEY_COORD_PRESENT: str = "coordination_ref_present"

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


def _write_cache(
    cache_file: Path,
    last_fetch_at_iso: str,
    refs: list[str],
    coordination_ref_present: bool | None,
) -> None:
    """Write fetch timestamp + refs + coordination-ref presence to cache file.

    Creates `.aria/cache/` silently if absent.  Errors are swallowed (OSError
    fail-soft) — a write failure means the next call will re-run fetch, which is
    safe.  ``coordination_ref_present`` is persisted (v1.46.0, #141) so cache-hit
    and stale-serve paths return a stable value.
    """
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            _CACHE_KEY_LAST_FETCH_AT: last_fetch_at_iso,
            _CACHE_KEY_REFS: refs,
            _CACHE_KEY_COORD_PRESENT: coordination_ref_present,
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
                        # Read back from cache so consecutive scans stay stable
                        # (None for legacy caches written before v1.46.0).
                        "coordination_ref_present": cache.get(_CACHE_KEY_COORD_PRESENT),
                    }
                    return r

    # ── Fetch 1: branch heads (load-bearing, runs first) ──────────────────────
    # Split from the coordination ref (#141 / aria-plugin #75): a single atomic
    # fetch bundling both failed rc=128 whenever refs/aria/coordination was absent
    # on the remote (most non-multi-terminal projects), dropping the branch heads
    # with it.  Fetch 1 must succeed independently to keep the branch view fresh.
    branch_refspec = _branch_heads_refspec(remote)
    cmd1 = ["git", "fetch", remote, "--no-tags", branch_refspec]
    log.debug("coordination_fetch: Fetch 1 (branch heads) %s (cwd=%s)", " ".join(cmd1), project_root)

    rc1, _stdout1, stderr1 = _run(cmd1, cwd=project_root, timeout=30)

    fetch_at_iso = _iso_now_utc()

    if rc1 != 0:
        # Fetch 1 failed → genuine failure.  Short-circuit: do NOT run Fetch 2 —
        # when the remote is unreachable the coordination ref state is unknowable.
        # Apply TASK-007 degraded semantics (anchored to the load-bearing fetch).
        # rc=124 = timeout (from _run); classify alongside other errors.
        error_kind, error_msg = (
            ("network", "git fetch timed out after 30s (rc=124)")
            if rc1 == 124
            else _classify_error(rc1, stderr1)
        )
        log.warning(
            "coordination_fetch: Fetch 1 (branch heads) failed — kind=%s msg=%s",
            error_kind,
            error_msg,
        )
        r.soft_error("coordination_fetch_failed", f"{error_kind}: {error_msg}")

        # Offline degradation: serve stale cache if available (incl. its last-known
        # coordination_ref_present); else pure failure with coordination unknown.
        # _write_cache is NOT called here — never overwrite a valid stale entry.
        stale_last_fetch_iso: str = ""
        stale_age: int = 0
        has_usable_stale_cache: bool = False
        stale_coord_present: bool | None = None

        if cache is not None:
            cached_iso = cache.get(_CACHE_KEY_LAST_FETCH_AT, "")
            if cached_iso:
                stale_ts = _parse_iso_utc(cached_iso)
                if stale_ts is not None:
                    stale_last_fetch_iso = cached_iso
                    stale_age = int(now_ts - stale_ts)
                    has_usable_stale_cache = True
                    stale_coord_present = cache.get(_CACHE_KEY_COORD_PRESENT)

        if has_usable_stale_cache:
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
                "coordination_ref_present": stale_coord_present,
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
                "coordination_ref_present": None,
            }
        return r

    # ── Fetch 2: coordination ref (only after Fetch 1 succeeds) ───────────────
    cmd2 = ["git", "fetch", remote, "--no-tags", COORDINATION_REF]
    log.debug("coordination_fetch: Fetch 2 (coordination ref) %s", " ".join(cmd2))

    rc2, _stdout2, stderr2 = _run(cmd2, cwd=project_root, timeout=30)

    refs_fetched: list[str] = [branch_refspec]
    coordination_ref_present: bool | None

    if rc2 == 0:
        coordination_ref_present = True
        refs_fetched.append(COORDINATION_REF)
    elif _is_benign_coordination_absent(rc2, stderr2):
        # Benign: coordination data simply not published — NORMAL, not an error.
        # No soft_error, no degraded, no kind=other.  (Evaluated BEFORE
        # _classify_error, which would otherwise map rc=128 to "other".)
        coordination_ref_present = False
        # info (not debug): "absent" is benign but, due to the git absent-vs-hidden
        # ambiguity (see _is_benign_coordination_absent), keep it traceable in logs.
        log.info("coordination_fetch: coordination ref absent (benign — not published)")
    else:
        # Genuine Fetch 2 failure (rc=124 timeout / rc=127 git-missing / network,
        # or rc=128 with other wording).  Fetch 1 already refreshed the branch
        # view, so success stays True; surface the coordination failure separately.
        coordination_ref_present = None
        f2_kind, f2_msg = (
            ("network", "git fetch timed out after 30s (rc=124)")
            if rc2 == 124
            else _classify_error(rc2, stderr2)
        )
        log.warning(
            "coordination_fetch: Fetch 2 (coordination ref) failed (non-benign) — kind=%s msg=%s",
            f2_kind,
            f2_msg,
        )
        r.soft_error("coordination_ref_fetch_failed", f"{f2_kind}: {f2_msg}")

    # Fetch 1 succeeded → branch view refreshed.  Persist cache (incl.
    # coordination_ref_present for stable cache-hit reads) and return success.
    _write_cache(cache_file, fetch_at_iso, refs_fetched, coordination_ref_present)
    r.data = {
        "success": True,
        "cached": False,
        "last_fetch_at": fetch_at_iso,
        "age_seconds": 0,
        "refs_fetched": refs_fetched,
        "error_kind": None,
        "error_msg": None,
        "degraded": False,
        "degradation_reason": None,
        "coordination_ref_present": coordination_ref_present,
    }
    return r

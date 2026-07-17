"""Phase 0.5 (main spec state-scanner-stale-refs-false-parity, F3′) — remote_refresh.

"Freshness is FETCHED, not MEASURED" (proposal §核心洞察). This collector fetches
every enforced (repo, remote) leg — the main repo plus every INITIALIZED submodule
— in parallel, per-host rate-limited, wall-clock-deadline-bounded, and produces
ONLY "what we know": `fetched_at` / `fetch_ok` / generation bookkeeping. It does
NOT compute "what it means" (`evidence_grade` / blocking) — that is F1′/F4′'s job,
implemented as pure functions in `multi_remote.py` (`_evidence_grade` et al.,
currently wired only up to that module's own inert predicates) and wired to THIS
collector's cache by a later increment. Keeping this boundary sharp is deliberate
(blueprint `collector_design`): two files computing the same three-tier verdict is
exactly the "parallel computation point" failure mode this Spec exists to kill.

Runs at Phase 0.5 — BEFORE `collect_git_state` (scan.py) — because
`git.upstream.behind` (stale local-refs read) and `sync_status.current_branch`
must not disagree with each other inside the same snapshot (tasks 3.9).

Concurrency model (blueprint `concurrency_model` / `budget_deadline_seam`):
  - One `concurrent.futures.ThreadPoolExecutor` PER HOST (not a global pool +
    semaphore), fed through a SEQUENTIAL ADMISSION GATE (`_should_stop_admitting`,
    checked leg-by-leg immediately before `submit()`) rather than
    `shutdown(cancel_futures=True)` post-hoc cancellation — the latter cancels
    whatever happens to still be queued at the instant `shutdown()` runs, which
    races against thread-scheduling latency (not the deadline) under a
    mocked/instant workload and can fabricate a cutoff that never actually
    happened (`_run_schedule` docstring has the full reasoning). 3.5a′'s
    "already-started keeps running, only not-yet-started is cut" semantics thus
    reduce to: a leg is either admitted — guaranteed to run to completion,
    however long its host's queue takes to reach it — or it is never submitted.
  - "Per-host" buckets by RESOLVED HOSTNAME (`_common.resolve_remote_host`), never
    by remote name — two remotes on two different repos can resolve to the same
    physical host and must share that host's concurrency budget (proposal
    R5-C-C: an implementation keyed on remote-name-count over-estimates true
    parallelism by ~3× on this project's own topology).
  - Anti-starvation (3.5b): legs are dispatched in `fetched_at` ascending order
    (never-fetched / `None` first) so a fixed deadline cuts a DIFFERENT tail each
    scan, guaranteeing every non-backoff leg is covered within a bounded number of
    rotations — instead of the same leg being starved on every single scan.
  - `_should_stop_admitting` is the SOLE "should we cut here" predicate, shared
    byte-for-byte by the production wall-clock path (`elapsed >= deadline`) and
    the `ARIA_SCAN_FETCH_BUDGET` test seam (`dispatched_count >= budget`) — see
    its docstring. Under mocked `_run`, every fetch returns instantly, so the
    real wall-clock deadline can never fire in tests; the budget seam replaces
    ONLY the trigger source, routing through the exact same
    dispatch → shutdown → cache-writeback code (memory
    feedback_noop_in_test_env_hardening_needs_mechanism_assertion).

Two-fetch semantics (#141, unchanged from `coordination_fetch.py`): Fetch 1
(branch heads, load-bearing, now with `--prune` — tasks 3.1/RC-1, a prerequisite
for the Phase-2A gitlink-orphan check) runs for every leg. Fetch 2
(`refs/aria/coordination`) runs ONLY for the (".", "origin") leg, and only after
Fetch 1 on that leg succeeds (tasks 3.15) — every other leg (non-origin remotes,
every submodule) never attempts it, so `coordination_ref_present` is non-null
ONLY on that one leg.

Cache (task 3.12/3.8/RM-6a/RM-6b): `.aria/cache/remote-refresh.json`, keyed by
`"<repo>::<remote>"` (see `_leg_key` — repo-relative path, "." for the main repo).
Written EXACTLY ONCE per scan by the main thread, AFTER every per-host scheduler
has finished (never from inside a worker thread — top_risks: an N-way naive
per-worker read-modify-write would drop legs under concurrent completion). A
read-merge-atomic-write (tmp+rename): re-reads whatever is currently on disk
(may differ from what this scan started with, if a concurrent process wrote in
between) and merges this scan's leg results on top, so a same-repo concurrent
scan's write is never silently clobbered into data loss — only "stale but never
corrupt" (RM-6a's accepted degradation direction).

`per_host_fetch_limit=0` (or a non-int / negative config value) is CLAMPED to 1,
never raised as `ValueError` — `ThreadPoolExecutor(max_workers=0)` would otherwise
crash the WHOLE scan, violating the collector-package fail-soft invariant
(`multi_remote.py:11` docstring: a single collector's bad input degrades, it never
propagates as an exception).
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ._common import (
    CollectorResult,
    _run,
    classify_git_error,
    fetch_budget_override,
    is_scan_offline,
    log,
    resolve_remote_host,
    scan_now,
)
from .coordination_fetch import (
    COORDINATION_REF,
    _branch_heads_refspec,
    _is_benign_coordination_absent,
)
from .git import _enumerate_submodule_paths
from .multi_remote import _list_remotes
from .multi_remote import _load_config as _load_multi_remote_config
from .multi_remote import resolve_enforced_remotes

_CACHE_RELATIVE = ".aria/cache/remote-refresh.json"

_DEFAULT_REFRESH_DEADLINE_SECONDS = 15.0
_DEFAULT_PER_HOST_FETCH_LIMIT = 4
_DEFAULT_FETCH_TIMEOUT_SECONDS = 30
_DEFAULT_TIMEOUT = 5  # local (non-network) git calls: remote listing, submodule enum

_MAIN_REPO_LABEL = "."
_MAIN_REPO_COORDINATION_REMOTE = "origin"


def _leg_key(repo: str, remote: str) -> str:
    """Cache / identity key for a (repo, remote) leg. SOT for downstream consumers
    (multi_remote.py's future wiring reads this same cache file)."""
    return f"{repo}::{remote}"


# ---------------------------------------------------------------------------
# Leg model
# ---------------------------------------------------------------------------
@dataclass
class _Leg:
    repo: str
    remote: str
    repo_dir: Path
    prior_fetched_at: datetime | None
    prior_generation_fetched: int | None
    prior_consecutive_unverified: int
    run_coordination_fetch: bool
    host: str | None = None


@dataclass
class _LegOutcome:
    leg: _Leg
    fetch_ok: str  # "true" | "false" | "not_attempted"
    fetched_at: datetime | None
    error_kind: str | None
    generation_fetched: int | None  # filled in by the caller once scan_generation is known
    consecutive_unverified: int
    coordination_ref_present: bool | None
    coordination_soft_error: str | None = None
    worker_error: str | None = None  # a leg worker thread crash — distinct from a
    # coordination Fetch-2 failure, so it surfaces under its own error kind (#4)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
def _load_config(project_root: Path) -> dict[str, Any]:
    """`state_scanner.multi_remote` — the SAME namespace `multi_remote.py` reads
    (task 1.6: no separate config door for `enforced_remotes`/`read_only_remotes`;
    this collector's OWN new keys — `refresh_deadline_seconds` / `per_host_fetch_limit`
    / `fetch_timeout_seconds` — live in that same block)."""
    return _load_multi_remote_config(project_root)


def _clamp_per_host_fetch_limit(raw: Any) -> int:
    """`ThreadPoolExecutor(max_workers=0)` raises `ValueError` — clamp to >=1
    (fail-soft, never crash the collector on a bad config value; top_risks)."""
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_PER_HOST_FETCH_LIMIT
    return val if val >= 1 else 1


def _clamp_deadline_seconds(raw: Any) -> float:
    """A non-positive `refresh_deadline_seconds` (e.g. -5) would make
    `_should_stop_admitting(0, ~0, deadline, None)` return True on the very first
    iteration → EVERY leg cut to `not_attempted` before any submit, silently
    disabling all fetching with no config-error signal. Clamp to the default on a
    non-positive / non-numeric value (fail-soft, mirrors _clamp_per_host_fetch_limit;
    silent-failure review Minor)."""
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return _DEFAULT_REFRESH_DEADLINE_SECONDS
    if val <= 0:
        log.warning(
            "remote_refresh: refresh_deadline_seconds=%r is non-positive; falling "
            "back to default %ss (a non-positive deadline would cut every leg)",
            raw,
            _DEFAULT_REFRESH_DEADLINE_SECONDS,
        )
        return _DEFAULT_REFRESH_DEADLINE_SECONDS
    return val


# ---------------------------------------------------------------------------
# ISO helpers
# ---------------------------------------------------------------------------
def _parse_iso(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        dt = datetime.fromisoformat(raw.strip())
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") if dt is not None else None


# ---------------------------------------------------------------------------
# Cache I/O
# ---------------------------------------------------------------------------
def _read_cache(cache_file: Path) -> dict[str, Any]:
    if not cache_file.is_file():
        return {}
    try:
        raw = cache_file.read_text(encoding="utf-8", errors="replace")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_cache_atomic(
    cache_file: Path, outcomes: list[_LegOutcome], scan_generation: int
) -> None:
    """Single-thread, ONE-TIME read-merge-atomic-write (task 3.12; top_risks'
    N-way lost-update guard). Re-reads whatever is CURRENTLY on disk (a concurrent
    scan may have written since this scan started) and merges this scan's results
    on top before an atomic tmp+rename write — never called from a worker thread,
    and never called per-leg (all outcomes are gathered in memory first)."""
    try:
        current_on_disk = _read_cache(cache_file)
    except Exception:  # pragma: no cover — defensive
        current_on_disk = {}

    disk_gen = current_on_disk.get("scan_generation")
    if not isinstance(disk_gen, int) or isinstance(disk_gen, bool):
        disk_gen = 0
    # RM-6b monotonic clamp: never let a concurrent writer's higher generation
    # regress backwards under ours.
    merged_generation = max(disk_gen, scan_generation)

    raw_legs = current_on_disk.get("legs")
    merged_legs: dict[str, Any] = dict(raw_legs) if isinstance(raw_legs, dict) else {}
    for o in outcomes:
        merged_legs[_leg_key(o.leg.repo, o.leg.remote)] = {
            "fetched_at": _iso(o.fetched_at),
            "fetch_ok": o.fetch_ok,
            "error_kind": o.error_kind,
            "generation_fetched": o.generation_fetched,
            "consecutive_unverified": o.consecutive_unverified,
            "coordination_ref_present": o.coordination_ref_present,
        }

    payload = {"scan_generation": merged_generation, "legs": merged_legs}
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_file.with_name(cache_file.name + f".tmp{os.getpid()}")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, cache_file)
    except OSError as exc:
        # fail-soft (never crash the collector) but NOT silent: this cache is the
        # SOLE freshness source multi_remote joins against (_read_remote_refresh_cache),
        # so a persistent write failure (disk full / read-only mount / perms) pins
        # every leg to stale → evidence_grade=expired → overall_parity permanently
        # False with zero diagnostic. Master's coordination_fetch logged this; keep
        # the warning (silent-failure review Important — this was a regression).
        log.warning(
            "remote_refresh: cache write failed (%s); freshness will not advance "
            "until this succeeds",
            exc,
        )


# ---------------------------------------------------------------------------
# Leg enumeration
# ---------------------------------------------------------------------------
def _enumerate_repos(project_root: Path, timeout: int) -> list[tuple[str, Path]]:
    """(repo_relative_path, repo_dir) for the main repo + every INITIALIZED
    submodule. Runs BEFORE any other Phase-1 collector (Phase 0.5), so it must
    enumerate repo topology itself — it cannot depend on `phase1_git` /
    `phase1_12_multi` output."""
    repos: list[tuple[str, Path]] = [(_MAIN_REPO_LABEL, project_root)]
    for rel_path in _enumerate_submodule_paths(project_root, timeout=timeout):
        sm_dir = project_root / rel_path
        if not sm_dir.exists() or not (sm_dir / ".git").exists():
            continue  # uninitialized submodule — fail-soft skip (multi_remote.py mirror)
        repos.append((rel_path, sm_dir))
    return repos


def _build_legs(
    project_root: Path, cfg: dict[str, Any], cache: dict[str, Any], timeout: int
) -> tuple[list[_Leg], list[dict[str, str]]]:
    """Returns (legs, no_matching_remotes). `no_matching_remotes` (RM-3/F5′) are
    configured-but-absent remote NAMES — recorded as observability, NEVER turned
    into a ghost fetch leg."""
    configured = cfg.get("enforced_remotes")
    read_only = tuple(cfg.get("read_only_remotes") or ())
    raw_cached_legs = cache.get("legs")
    cached_legs: dict[str, Any] = raw_cached_legs if isinstance(raw_cached_legs, dict) else {}

    legs: list[_Leg] = []
    no_matching: list[dict[str, str]] = []
    for repo_label, repo_dir in _enumerate_repos(project_root, timeout):
        actual_remotes = _list_remotes(repo_dir, timeout)
        enforced, no_match = resolve_enforced_remotes(configured, actual_remotes, read_only)
        for r in no_match:
            no_matching.append({"repo": repo_label, "remote": r})
        for remote in enforced:
            prior_raw = cached_legs.get(_leg_key(repo_label, remote))
            prior: dict[str, Any] = prior_raw if isinstance(prior_raw, dict) else {}

            prior_gen = prior.get("generation_fetched")
            if not isinstance(prior_gen, int) or isinstance(prior_gen, bool):
                prior_gen = None

            prior_unverified = prior.get("consecutive_unverified")
            if (
                not isinstance(prior_unverified, int)
                or isinstance(prior_unverified, bool)
                or prior_unverified < 0
            ):
                prior_unverified = 0

            legs.append(
                _Leg(
                    repo=repo_label,
                    remote=remote,
                    repo_dir=repo_dir,
                    prior_fetched_at=_parse_iso(prior.get("fetched_at")),
                    prior_generation_fetched=prior_gen,
                    prior_consecutive_unverified=prior_unverified,
                    run_coordination_fetch=(
                        repo_label == _MAIN_REPO_LABEL
                        and remote == _MAIN_REPO_COORDINATION_REMOTE
                    ),
                )
            )
    return legs, no_matching


def _resolve_hosts(legs: list[_Leg], timeout: int) -> None:
    """`git remote get-url` is a local config read (no network I/O) — safe to run
    unconditionally, including in offline mode, so `host` is always populated."""
    for leg in legs:
        leg.host = resolve_remote_host(leg.repo_dir, leg.remote, timeout=timeout)


def _sort_by_freshness(legs: list[_Leg]) -> list[_Leg]:
    """3.5b anti-starvation: dispatch order = `fetched_at` ascending, `None`
    (never-fetched) first. A fixed/declaration-order scheduler would cut the SAME
    tail every scan under a tight deadline — those legs' `fetched_at` would never
    advance and they would starve forever (proposal: "这才是 C-C 恒红的真正根因")."""
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    return sorted(
        legs, key=lambda leg: (leg.prior_fetched_at is not None, leg.prior_fetched_at or epoch)
    )


# ---------------------------------------------------------------------------
# Per-leg fetch (runs inside a per-host worker thread)
# ---------------------------------------------------------------------------
def _not_attempted_outcome(leg: _Leg) -> _LegOutcome:
    """Deadline/budget cut a leg before it ever started: `fetch_ok="not_attempted"`
    and `fetched_at` is NOT advanced ("we didn't ask" ≠ "the remote is
    unreachable" — `has_unreachable_remote` must stay unaffected downstream)."""
    return _LegOutcome(
        leg=leg,
        fetch_ok="not_attempted",
        fetched_at=leg.prior_fetched_at,
        error_kind=None,
        generation_fetched=leg.prior_generation_fetched,
        consecutive_unverified=leg.prior_consecutive_unverified,
        coordination_ref_present=None,
    )


def _do_fetch_leg(leg: _Leg, fetch_timeout: int) -> _LegOutcome:
    """Fetch 1 (branch heads, `--prune`, tasks 3.1/RC-1) always runs. Fetch 2
    (`refs/aria/coordination`) runs ONLY when `leg.run_coordination_fetch` is True
    — i.e. ONLY the (".", "origin") leg — and only after Fetch 1 on that leg
    succeeds (tasks 3.3/3.15: `fetch_ok` anchors to Fetch 1 alone; a benign-absent
    coordination ref on every other remote must never flip a leg to `fetch_ok=false`,
    or every non-origin remote would be permanently unreachable)."""
    branch_refspec = _branch_heads_refspec(leg.remote)
    cmd1 = ["git", "fetch", leg.remote, "--no-tags", "--prune", branch_refspec]
    rc1, _, err1 = _run(cmd1, cwd=leg.repo_dir, timeout=fetch_timeout)

    if rc1 != 0:
        # Fetch 1 failed: fetched_at is NOT advanced (3.7) — this leg honestly
        # keeps whatever it last had (however stale), never manufacturing false
        # freshness. error_kind goes through the Rule #7 typed channel only.
        return _LegOutcome(
            leg=leg,
            fetch_ok="false",
            fetched_at=leg.prior_fetched_at,
            error_kind=classify_git_error(rc1, err1, "git fetch").label,
            generation_fetched=leg.prior_generation_fetched,
            consecutive_unverified=leg.prior_consecutive_unverified,
            coordination_ref_present=None,
        )

    fetched_at = scan_now()
    coordination_ref_present: bool | None = None
    coordination_soft_error: str | None = None

    if leg.run_coordination_fetch:
        cmd2 = ["git", "fetch", leg.remote, "--no-tags", COORDINATION_REF]
        rc2, _, err2 = _run(cmd2, cwd=leg.repo_dir, timeout=fetch_timeout)
        if rc2 == 0:
            coordination_ref_present = True
        elif _is_benign_coordination_absent(rc2, err2):
            coordination_ref_present = False  # NORMAL — not published, not an error
        else:
            coordination_ref_present = None
            coordination_soft_error = classify_git_error(rc2, err2, "git fetch").label

    return _LegOutcome(
        leg=leg,
        fetch_ok="true",
        fetched_at=fetched_at,
        error_kind=None,
        generation_fetched=leg.prior_generation_fetched,  # caller fills in the new value
        consecutive_unverified=leg.prior_consecutive_unverified,
        coordination_ref_present=coordination_ref_present,
        coordination_soft_error=coordination_soft_error,
    )


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------
def _should_stop_admitting(
    dispatched_count: int, elapsed: float, deadline_seconds: float, budget: int | None
) -> bool:
    """THE single "stop admitting new legs" predicate — shared byte-for-byte by
    the production wall-clock path and the `ARIA_SCAN_FETCH_BUDGET` test seam.
    NEVER duplicate this logic inline at either call site (memory
    feedback_noop_in_test_env_hardening_needs_mechanism_assertion): a second,
    parallel "test-mode" implementation would let deadline-cut tests pass green
    while the real production deadline branch goes forever unexercised.

    `budget is not None` ⇒ test seam: stop once `dispatched_count` reaches it: the
    wall clock is IGNORED (mocked `_run` returns instantly in tests, so `elapsed`
    would never trip). `budget is None` ⇒ production: stop once `elapsed` reaches
    `deadline_seconds`.
    """
    if budget is not None:
        return dispatched_count >= budget
    return elapsed >= deadline_seconds


def _run_schedule(
    legs: list[_Leg],
    per_host_fetch_limit: int,
    fetch_timeout_seconds: int,
    refresh_deadline_seconds: float,
) -> tuple[list[_LegOutcome], list[dict[str, str]]]:
    """Dispatch `legs` (already sorted by `_sort_by_freshness`) to per-host
    executors using a SEQUENTIAL ADMISSION GATE: `_should_stop_admitting` is
    checked, one leg at a time, immediately BEFORE that leg is submitted — never
    after. This is 3.5a′'s "already-started keeps running, only not-yet-started
    is cut" semantics implemented WITHOUT `ThreadPoolExecutor.shutdown(...,
    cancel_futures=True)`: that stdlib mechanism cancels whatever happens to
    still be sitting in an executor's internal queue at the instant `shutdown()`
    is called, which is racy against thread-scheduling latency, not against the
    deadline itself — under a mocked/instant workload two legs genuinely admitted
    together can land on the same host's queue, and `cancel_futures=True` fired
    microseconds later (before the OS has even scheduled the second worker
    thread) would cancel a leg that was NEVER meant to be cut, fabricating a
    cutoff that never happened. The admission gate avoids that race entirely: a
    leg is either admitted (guaranteed to run to completion, however long the
    host queue takes to get to it — per-host throttling bounds CONCURRENCY, not
    which legs get to run) or it is never submitted at all. Returns (outcomes,
    skipped_remotes)."""
    budget = fetch_budget_override()
    start = time.monotonic()

    hosts: dict[str | None, list[_Leg]] = {}
    for leg in legs:
        hosts.setdefault(leg.host, []).append(leg)
    executors: dict[str | None, ThreadPoolExecutor] = {
        host: ThreadPoolExecutor(max_workers=per_host_fetch_limit) for host in hosts
    }

    futures: dict[Future, _Leg] = {}
    not_admitted: list[_Leg] = []
    dispatched_count = 0

    try:
        for i, leg in enumerate(legs):
            elapsed = time.monotonic() - start
            if _should_stop_admitting(
                dispatched_count, elapsed, refresh_deadline_seconds, budget
            ):
                not_admitted.extend(legs[i:])
                break
            fut = executors[leg.host].submit(_do_fetch_leg, leg, fetch_timeout_seconds)
            futures[fut] = leg
            dispatched_count += 1
    finally:
        # Every future here was ADMITTED (passed the gate above) — wait for all
        # of them unconditionally. No `cancel_futures`: admission already decided
        # which legs run: none of these should ever be cut post-hoc.
        for ex in executors.values():
            ex.shutdown(wait=True)

    outcomes: list[_LegOutcome] = []
    skipped: list[dict[str, str]] = []

    for leg in not_admitted:
        outcomes.append(_not_attempted_outcome(leg))
        skipped.append({"repo": leg.repo, "remote": leg.remote, "reason": "deadline"})

    for fut, leg in futures.items():
        try:
            outcomes.append(fut.result())
        except Exception as e:  # pragma: no cover — defensive; _do_fetch_leg never raises
            outcomes.append(
                _LegOutcome(
                    leg=leg,
                    fetch_ok="false",
                    fetched_at=leg.prior_fetched_at,
                    error_kind="other",
                    generation_fetched=leg.prior_generation_fetched,
                    consecutive_unverified=leg.prior_consecutive_unverified,
                    coordination_ref_present=None,
                    worker_error=f"leg worker raised: {e}",
                )
            )

    return outcomes, skipped


# ---------------------------------------------------------------------------
# Output assembly
# ---------------------------------------------------------------------------
def _build_output(
    outcomes: list[_LegOutcome], scan_generation: int, skipped: list[dict[str, str]]
) -> dict[str, Any]:
    legs_out = []
    for o in outcomes:
        legs_out.append(
            {
                "repo": o.leg.repo,
                "remote": o.leg.remote,
                "host": o.leg.host,
                "fetched_at": _iso(o.fetched_at),
                "fetch_ok": o.fetch_ok,
                "error_kind": o.error_kind,
                "scan_generation": scan_generation,
                "generation_fetched": o.generation_fetched,
                "consecutive_unverified": o.consecutive_unverified,
                "coordination_ref_present": o.coordination_ref_present,
            }
        )
    return {"legs": legs_out, "skipped_count": len(skipped), "skipped_remotes": skipped}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def collect_remote_refresh(project_root: Path) -> CollectorResult:
    """Phase 0.5 — F3′ `remote_refresh` collector.

    Fetches every enforced (repo, remote) leg in parallel, per-host rate-limited,
    deadline-bounded. Produces ONLY "what we know" — NOT "what it means"
    (see module docstring).

    Output shape (top-level key `remote_refresh`):
        {
          "legs": [
            {"repo": str, "remote": str, "host": str | null,
             "fetched_at": str | null,             # ISO 8601 UTC, seconds precision
             "fetch_ok": "true" | "false" | "not_attempted",
             "error_kind": str | null,              # Rule #7 typed label, never raw stderr
             "scan_generation": int | null,         # this scan's generation counter
             "generation_fetched": int | null,      # generation at which THIS leg last
                                                      # truly succeeded (Fetch 1)
             "consecutive_unverified": int,          # D18 counter, owned HERE: reset to 0
                                                      # on this leg's true fetch, +1 on any
                                                      # non-true online outcome, frozen offline
             "coordination_ref_present": bool | null},  # non-null ONLY for (".", "origin")
            ...
          ],
          "skipped_count": int,
          "skipped_remotes": [{"repo": str, "remote": str, "reason": "deadline"}],
          "no_matching_remotes": [{"repo": str, "remote": str}],  # only when non-empty
        }

    Config: `.aria/config.json` → `state_scanner.multi_remote`:
      - enforced_remotes / read_only_remotes (F5′, shared with multi_remote.py)
      - refresh_deadline_seconds (default 15)
      - per_host_fetch_limit (default 4; clamped to >=1)
      - fetch_timeout_seconds (default 30; per-fetch subprocess timeout)
      - timeout_seconds (default 5; LOCAL git calls only — remote listing, host
        resolution, submodule enumeration — never the network fetch itself)

    Test seams (all in `_common.py`, honored here):
      - `ARIA_SCAN_OFFLINE` — every leg reports `not_attempted`; `fetched_at` is
        never advanced; no cache write (nothing changed, nothing to persist).
      - `ARIA_SCAN_NOW` — `fetched_at` timestamps are stamped via `scan_now()`.
      - `ARIA_SCAN_FETCH_BUDGET` — caps how many legs get dispatched, replacing
        the wall-clock deadline as the "stop admitting" trigger (same downstream
        path — see `_should_stop_admitting`).
    """
    r = CollectorResult()
    cfg = _load_config(project_root)
    local_timeout = int(cfg.get("timeout_seconds", _DEFAULT_TIMEOUT) or _DEFAULT_TIMEOUT)
    refresh_deadline_seconds = _clamp_deadline_seconds(
        cfg.get("refresh_deadline_seconds", _DEFAULT_REFRESH_DEADLINE_SECONDS)
    )
    fetch_timeout_seconds = int(
        cfg.get("fetch_timeout_seconds", _DEFAULT_FETCH_TIMEOUT_SECONDS)
        or _DEFAULT_FETCH_TIMEOUT_SECONDS
    )
    per_host_fetch_limit = _clamp_per_host_fetch_limit(
        cfg.get("per_host_fetch_limit", _DEFAULT_PER_HOST_FETCH_LIMIT)
    )

    cache_file = project_root / _CACHE_RELATIVE
    cache = _read_cache(cache_file)
    prior_scan_generation = cache.get("scan_generation")
    if not isinstance(prior_scan_generation, int) or isinstance(prior_scan_generation, bool):
        prior_scan_generation = 0

    legs, no_matching = _build_legs(project_root, cfg, cache, local_timeout)
    if not legs:
        r.data = {"legs": [], "skipped_count": 0, "skipped_remotes": []}
        return r

    # Host resolution is a local `git remote get-url` read — no network I/O — so
    # it always runs, including offline, keeping the `host` field populated.
    _resolve_hosts(legs, local_timeout)

    if is_scan_offline():
        # 9.7 network + counter face: every leg is not_attempted, fetched_at is
        # NEVER advanced, scan_generation is NOT incremented (must stay
        # byte-stable across repeated offline scans — 9.7 stability freeze). No
        # cache write: nothing changed, nothing to persist.
        outcomes = [_not_attempted_outcome(leg) for leg in legs]
        r.data = _build_output(outcomes, prior_scan_generation, skipped=[])
        if no_matching:
            r.data["no_matching_remotes"] = no_matching
        return r

    ordered = _sort_by_freshness(legs)
    outcomes, skipped = _run_schedule(
        ordered, per_host_fetch_limit, fetch_timeout_seconds, refresh_deadline_seconds
    )

    new_scan_generation = prior_scan_generation + 1
    for o in outcomes:
        # RM-5/RM-9: generation_fetched only advances on a leg's OWN true Fetch-1
        # success this round; every other outcome (failed / not_attempted) keeps
        # whatever generation it last succeeded at (already the default from
        # `_do_fetch_leg` / `_not_attempted_outcome`).
        #
        # consecutive_unverified (D18) — R9-M6′ priority: fetch-success reset >
        # freeze > stale increment. The "freeze" arm is the offline early-return
        # above (counters never reach here); on this ONLINE path a true fetch resets
        # to 0, and any non-true outcome (failed / deadline-cut) is one more
        # unverified generation for this leg. This is determinable from fetch_ok
        # ALONE — it does NOT need evidence_grade — so it lives here in the collector
        # that persists the cache, not in F1′/F4′ (which only READ it). Without this,
        # the counter was pinned at 0 forever and the D18 guard in
        # _exemption_eligible was dead code (code-review + silent-failure Important).
        if o.fetch_ok == "true":
            o.generation_fetched = new_scan_generation
            o.consecutive_unverified = 0
        else:
            o.consecutive_unverified = o.leg.prior_consecutive_unverified + 1
        if o.coordination_soft_error:
            r.soft_error(
                "coordination_ref_fetch_failed",
                f"{o.leg.repo}/{o.leg.remote}: {o.coordination_soft_error}",
            )
        if o.worker_error:
            # distinct kind so a general leg-worker crash is not misattributed to the
            # coordination ref (which only the (".","origin") leg ever fetches) (#4)
            r.soft_error(
                "remote_refresh_leg_failed",
                f"{o.leg.repo}/{o.leg.remote}: {o.worker_error}",
            )

    _write_cache_atomic(cache_file, outcomes, new_scan_generation)

    r.data = _build_output(outcomes, new_scan_generation, skipped)
    if no_matching:
        r.data["no_matching_remotes"] = no_matching
    return r

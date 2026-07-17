"""Phase 1 — legacy `coordination_fetch` schema shim (F6′, Phase 1 increment 5).

Pre-increment-5 this module RAN its own two-fetch network I/O with an
independent 30-second TTL cache (`.aria/cache/coordination-fetch.json`). That
implementation is RETIRED (F6′ "read法(a)": retire + shim, never run two
independent fetchers in parallel — see `remote_refresh.py` module docstring
and proposal §F6′). All network I/O + scheduling now lives in
`remote_refresh.py` (Phase 0.5), which fetches every (repo, remote) leg,
including a special Fetch 2 (`refs/aria/coordination`) for exactly the
(".", "origin") leg.

This module now does exactly ONE thing: a PURE function,
`derive_legacy_coordination_fetch_block`, that reads that one leg's record out
of the `remote_refresh` collector's output and re-derives the OLD
`coordination_fetch` schema (byte-compatible keys) so downstream consumers —
`track_board.py`, `normalize_snapshot.py`'s TIMESTAMP_KEYS/DROP_KEYS, any
future reader — keep working unmodified (F6′ backward-compat shim, tasks
3.14). There is no cache here anymore: "fresh or not" is entirely inherited
from `remote_refresh`'s own per-leg `fetched_at`/`fetch_ok`, killing the "two
independent TTL caches disagreeing about the same origin" failure mode F6′
exists to retire.

Retained from the pre-increment-5 implementation (still load-bearing,
imported by `remote_refresh.py` and directly unit-tested):
  - `COORDINATION_REF` / `_branch_heads_refspec` — refspec builders.
  - `_is_benign_coordination_absent` — the Fetch-2 benign-absent triple-AND
    gate (a missing `refs/aria/coordination` on the remote is NORMAL, not a
    failure).
  - `_classify_error` — kept BYTE-IDENTICAL (delegates to
    `_common.classify_git_error`, see its own docstring) purely because
    `test_stderr_typed_channel.py::TestCoordinationFetchDelegation` pins its
    wording directly. `derive_legacy_coordination_fetch_block` does NOT call
    it — the leg record only carries a `error_kind` LABEL (already classified
    inside `remote_refresh.py`'s `_do_fetch_leg`, Rule #7 typed channel), not
    a raw `(rc, stderr)` pair, so a fresh, rc-free wording table
    (`_LABEL_ERROR_MESSAGES`) is used instead.

Task 3.14 mapping (SOT — the derivation formula, do not reinvent elsewhere):

    success            := (fetch_ok == "true")            # "not_attempted" → False (conservative)
    served_stale_cache := (fetch_ok == "false") AND a prior `fetched_at` exists
                           (remote_refresh does NOT advance `fetched_at` on a
                           failed Fetch 1 — the leg's `fetched_at` field IS the
                           stale value being "served")
    degraded           := served_stale_cache
    cached             := served_stale_cache
                           OR (fetch_ok == "not_attempted" AND a prior
                               `fetched_at` exists)   # the hidden 3rd cell
                           (blueprint top_risks: `not_attempted` can NEVER
                           satisfy `degraded`'s `fetch_ok=="false"` clause —
                           a deadline-cut leg with a usable prior value is
                           "cached but not degraded", never a red bar)
    degradation_reason := "fetch_failed_using_stale_cache" iff degraded, else None
    coordination_ref_present := passed through verbatim from the leg (only
                           the (".", "origin") leg ever has a non-null value —
                           see `remote_refresh.py`'s `run_coordination_fetch`)

`track_board.py` (Phase 1 increment 5) additionally reads `fetch_ok` THREE-
STATE directly off the `remote_refresh` top-level block (not through this
shim) to render a THIRD, non-red "未刷新" (not-refreshed) advisory for
`not_attempted` — `degraded`/`cached` alone cannot distinguish "we tried and
failed" from "we never tried this scan" (see `track_board.py` for the
rationale this module's docstring above already spells out).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ._common import classify_git_error, scan_now

# ── Constants (retained — consumed by remote_refresh.py) ──────────────────

COORDINATION_REF: str = "refs/aria/coordination"

_MAIN_REPO_LABEL: str = "."
_MAIN_REPO_REMOTE: str = "origin"


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

    Known limitations (code-review #141):
    - git cannot distinguish "ref absent" from "ref hidden by server-side ACL /
      uploadpack.hideRefs" — both emit "couldn't find remote ref".  An auth-masked
      coordination ref would read here as benign-absent.  NOT reachable in Aria's
      Forgejo deployment (repo-level read ACL governs refs/aria/* too, so a masked
      ref implies Fetch 1 already failed).  git-protocol-unsolvable (`ls-remote
      --exit-code` returns rc=2 for BOTH absent and hidden) → documented limitation,
      not fixed (Aria #142 wont-fix).
    - the English substring is RELIABLE: `_run` forces `LC_ALL=C` (#143, v1.46.1) so
      git emits English diagnostics regardless of host locale.
    """
    if rc != 128:
        return False
    stderr_lower = stderr.lower()
    return (
        "couldn't find remote ref" in stderr_lower
        and COORDINATION_REF.lower() in stderr_lower
    )


# ── Error classification (retained verbatim — pinned by test_stderr_typed_channel.py) ──


def _classify_error(rc: int, stderr: str) -> tuple[str, str]:
    """Map a git fetch non-zero exit to an (error_kind, error_msg) pair.

    Callers must have already confirmed rc != 0.
    error_msg is kept short and non-secret (no env var values, no tokens).

    Spec B v5 (option B): the (rc, stderr) → label SIGNAL MAP lives in
    ``_common.classify_git_error`` as the single SOT — this function DELEGATES to it
    for the label and keeps ONLY its own "git fetch ..." wording layer here (so the
    signal map is not duplicated into a third copy — R7 M-2). The wording strings are
    byte-identical to the pre-delegation implementation, so existing tests are green.

    NOT called by `derive_legacy_coordination_fetch_block` (Phase 1 increment 5) —
    that function only has an already-classified `error_kind` LABEL to work with
    (no raw `(rc, stderr)` pair survives past `remote_refresh.py`'s Rule #7 typed
    channel). Retained here solely because
    `test_stderr_typed_channel.py::TestCoordinationFetchDelegation` pins this exact
    delegation + wording directly.
    """
    label = classify_git_error(rc, stderr, "git fetch").label
    if label == "git_missing":
        return "git_missing", "git command not found in PATH"
    if label == "auth_403":
        return "auth_403", f"git fetch authentication error (rc={rc})"
    if label == "non_ff":
        return "non_ff", f"git fetch rejected / non-fast-forward (rc={rc})"
    if label == "network":
        return "network", f"git fetch network error (rc={rc})"
    return "other", f"git fetch failed with rc={rc}"


# ── Legacy-schema derivation (F6′ shim, task 3.14) ─────────────────────────

# rc-free wording — the leg record only carries an already-classified LABEL
# (see module docstring), never a raw stderr string, so this is intentionally
# NOT the same table as `_classify_error`'s (which needs `rc` for its wording).
_LABEL_ERROR_MESSAGES: dict[str, str] = {
    "git_missing": "git command not found in PATH",
    "auth_403": "git fetch authentication error",
    "non_ff": "git fetch rejected / non-fast-forward",
    "network": "git fetch network error",
    "other": "git fetch failed",
}

_EMPTY_BLOCK: dict[str, Any] = {
    "success": False,
    "cached": False,
    "last_fetch_at": "",
    "age_seconds": 0,
    "refs_fetched": [],
    "error_kind": None,
    "error_msg": None,
    "degraded": False,
    "degradation_reason": None,
    "coordination_ref_present": None,
}


def _find_origin_leg(remote_refresh_data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Find the (".", "origin") leg inside `remote_refresh`'s `legs` list.

    Fail-soft: a missing/malformed `remote_refresh_data` or an absent/non-list
    `legs` key returns None (the caller degrades to `_EMPTY_BLOCK`) — this is
    NOT an error, just "the origin leg has no data yet" (e.g. `origin` is not
    in `enforced_remotes`, or the very first scan of a fresh clone).
    """
    legs = (remote_refresh_data or {}).get("legs")
    if not isinstance(legs, list):
        return None
    for leg in legs:
        if (
            isinstance(leg, dict)
            and leg.get("repo") == _MAIN_REPO_LABEL
            and leg.get("remote") == _MAIN_REPO_REMOTE
        ):
            return leg
    return None


def _parse_iso_utc(iso: str):
    """Parse an ISO 8601 string to a tz-aware UTC datetime, or None."""
    try:
        dt = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _age_seconds(fetched_at_iso: Any) -> int:
    """`scan_now() - fetched_at`, clamped to >=0. Any unparseable/missing input
    (including a future timestamp — clock rollback) → 0, never negative."""
    if not isinstance(fetched_at_iso, str) or not fetched_at_iso.strip():
        return 0
    dt = _parse_iso_utc(fetched_at_iso)
    if dt is None:
        return 0
    age = (scan_now() - dt).total_seconds()
    return int(age) if age > 0 else 0


def derive_legacy_coordination_fetch_block(
    remote_refresh_data: dict[str, Any] | None,
) -> dict[str, Any]:
    """Derive the legacy `coordination_fetch` schema from `remote_refresh`'s
    (".", "origin") leg. Pure function — no I/O, cannot raise, cannot soft-error
    (there is nothing left for it to get wrong: the leg record it reads was
    already produced fail-soft by `remote_refresh.py`).

    Returns a dict matching the PRE-increment-5 `coordination_fetch` schema
    (see this module's docstring for the exact field-by-field mapping and
    module docstring header for the "why" — F6′ backward-compat shim).
    """
    leg = _find_origin_leg(remote_refresh_data)
    if leg is None:
        return dict(_EMPTY_BLOCK)

    fetch_ok = leg.get("fetch_ok")
    fetched_at = leg.get("fetched_at")
    has_stale_value = isinstance(fetched_at, str) and bool(fetched_at.strip())

    success = fetch_ok == "true"
    served_stale_cache = fetch_ok == "false" and has_stale_value
    degraded = served_stale_cache
    cached = served_stale_cache or (fetch_ok == "not_attempted" and has_stale_value)

    error_kind: str | None = leg.get("error_kind") if fetch_ok == "false" else None
    error_msg: str | None = _LABEL_ERROR_MESSAGES.get(error_kind) if error_kind else None
    degradation_reason: str | None = "fetch_failed_using_stale_cache" if degraded else None

    refs_fetched: list[str] = []
    if fetch_ok == "true":
        remote = leg.get("remote") or _MAIN_REPO_REMOTE
        refs_fetched.append(_branch_heads_refspec(remote))
        if leg.get("coordination_ref_present") is True:
            refs_fetched.append(COORDINATION_REF)

    return {
        "success": success,
        "cached": cached,
        "last_fetch_at": fetched_at if has_stale_value else "",
        "age_seconds": _age_seconds(fetched_at),
        "refs_fetched": refs_fetched,
        "error_kind": error_kind,
        "error_msg": error_msg,
        "degraded": degraded,
        "degradation_reason": degradation_reason,
        "coordination_ref_present": leg.get("coordination_ref_present"),
    }

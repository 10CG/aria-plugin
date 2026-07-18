# Predicate Domain Table (D16 SOT)

> **Owner spec**: `state-scanner-stale-refs-false-parity` (v10). **D16 decision**: the
> predicate-domain sweep — historically kept in the proposal — is moved HERE, into
> aria-plugin, so the plugin's own tests can read and lock it. This is the single
> source of truth for every boolean predicate the false-parity fix introduces or
> modifies. Every PR in the phased rollout (Phase 0 → 3) APPENDS its predicates here
> rather than the proposal writing them once at the end.
>
> **Why a machine-readable SOT** (memory `feedback_predicate_tiers_need_total_partition_proof`
> + `feedback_doc_claims_need_diff_verification_and_variant_sweep`): R7/R8 both had two
> independent agents miss the `E∧¬X` overlap格 in nothing-but-prose review. A predicate
> whose domain is not proven total (mutually-exclusive ∪ complete) is undefined behavior
> resolved by implementation order. The lock test (below) mechanizes the sweep.

## Lock test contract (D16)

`tests/` MUST assert, for the predicates registered below that are LIVE (implemented):
1. **Registration**: every boolean predicate in the code (the sweep set) appears in
   this table.
2. **Single definition**: each predicate is defined once, or every definition is
   byte-identical.
3. **Total partition**: for tiered predicates (e.g. `evidence_grade`), the guards are
   pairwise mutually exclusive AND jointly cover the domain (no overlap格, no gap).
4. **Retired-predicate zero-live-reference**: retired predicates (`可信(r)` /
   `freshness_window`) have zero live code references.

## Predicate registry

Legend — **Phase**: which rollout phase lands it. **Domain complete?**: is the input
domain fully partitioned. **Complement default**: value on the unregistered/else case
(fail-CLOSED = the safe default that does NOT green-wash).

| Predicate | Phase | Definition (summary) | Domain complete? | Complement default |
|-----------|-------|----------------------|:---:|--------------------|
| `resolve_enforced_remotes(configured, actual, read_only)` | 0 | non-empty configured → `set(configured) ∩ actual` (diff → `no_matching_remote`, no ghost legs); `[]`/`None` → `actual − read_only` (auto-discover, NOT empty set) | ✅ (`[]`/`None`/non-empty all covered) | `[]`/`None` ⇒ auto-discover (the F5′ trap: `[]` ≠ empty set) |
| `证据资格(r)` (evidence eligibility, ∃-side) | 1 (F1′/D15′) | `fetched_at(r) ≠ null ∧ (now − fetched_at) ≤ evidence_window (1h)` | ✅ (null ⇒ false) | `false` (fail-CLOSED) |
| `豁免资格(r)` (exemption eligibility, downgrade-side) | 1 (F1′/D15′/D18) | `fetched_at ≠ null ∧ generation_age ≤ k_eff ∧ wall ≤ hard_cap (7d) ∧ consecutive_unverified < k_eff` | ✅ (null / neg-clamp ⇒ false) | `false` (fail-CLOSED) |
| `evidence_grade(r)` | 1 (D20) | three-value `{fresh [E], stale_unverified [¬E∧X], expired [¬E∧¬X]}`; per-remote field, NOT in `parity.reason` | ✅ (three格 cover E×X) | `expired` ⇒ blocking (fail-CLOSED) |
| `has_unreachable_remote(r)` | 1 (F1′) | `fetch_ok(r) == "false"` (tried→failed; three-state, `not_attempted` ≠ false) | ✅ (three-state ⇒ no enumeration) |置位 (fail-CLOSED, zero enumeration) |
| `fetch_ok(r)` | 1 (F3′) | three-state `{true, false, not_attempted}` | ✅ (three-state) | — |
| `benign_unknown(r)` | 1 (F4′) | two buckets: ① fetch-independent (detached_head/shallow/remote_branch_missing) ② fetch-dependent (`no_local_tracking_ref ∧ 证据资格`) | ✅ | — (it is the allowlist) |
| `blocking_unknown(r)` | 1 (F4′) | `parity=="unknown" ∧ ¬benign_unknown(r)` | ✅ (complement) | 阻断 (fail-CLOSED) |
| `has_unpublished_branch(r)` | 1 (F4′) | `parity=="unknown" ∧ reason=="no_local_tracking_ref" ∧ 证据资格(r)` (per-remote) | ✅ | `false` |
| `_should_stop_admitting(dispatched_count, elapsed, deadline, budget)` | 1 (F3′, scheduling) | `budget is not None` (test seam) ⇒ `dispatched_count ≥ budget`; else (production) ⇒ `elapsed ≥ deadline_seconds` — the SOLE "stop admitting new legs" gate, checked leg-by-leg immediately before `submit()` (sequential admission gate, not post-hoc `cancel_futures`); shared byte-for-byte by both trigger sources (`remote_refresh.py:_should_stop_admitting`) | ✅ (two-branch total: `budget` present/absent) | — (not a fail-open/closed predicate; governs dispatch only, never freshness verdicts) |
| `gitlink_orphaned(R)` | 2A (F10″/D14) | ✅ **implemented** (`multi_remote.py::_classify_gitlink_pair`) — 9-branch cross-repo reachability (8 non-ok exits + the implicit healthy `ok` exit); `status=="orphaned" ⇒ blocking`; `status=="orphan_unverified"` visible + D18 time-escalation | ✅ (9 branches each with a home: `ok`/`orphaned`/`orphan_unverified`/`no_published_ref`/`not_a_gitlink`/`uninitialized`/`no_matching_remote`/`shallow_unverifiable`/`soft_error`) | visible + escalate (fail toward visible, then red) |
| `_gitlink_blocking(g, k_eff)` | 2A (F10″/D14) | `multi_remote.py` — `status=="orphaned" ⇒ true`; `status=="orphan_unverified" ⇒ (consecutive_unverified ≥ k_eff)`; every other status ⇒ `false`. Sole consumer of `gitlink_orphaned(R)`'s `status` output for `_overall_parity` clause 3 | ✅ (three-way: orphaned / orphan_unverified / everything-else, each with a defined return) | `false` (non-orphaned/non-escalated statuses never block) |

> **Phase 2A landed** (2026-07-1x): `gitlink_orphaned(R)`'s 9-branch domain and `_gitlink_blocking(g, k_eff)`
> are both implemented and wired into `collect_multi_remote`'s R×S double loop (main repo's enforced
> remotes × all declared submodule paths, including uninitialized ones). `gitlink_integrity[]` now
> carries real per-(R,S) verdicts in production snapshots (no longer hardcoded `[]`) — see
> `state-snapshot-schema.md` §`gitlink_integrity[]` status semantics for the full status table and
> `multi_remote.py::_classify_gitlink_pair`'s docstring for the FIXED evaluation order (load-bearing:
> reordering can change which branch a given fixture lands in). The (R,S)-keyed `consecutive_unverified`
> D18 counter persists in its own cache file `.aria/cache/gitlink-integrity.json` (`_gitlink_pair_key`,
> `_read_gitlink_cache`/`_write_gitlink_cache_atomic`) — a physically separate key space from the F3′
> `remote_refresh` per-leg counter of the same name (`_GITLINK_COUNTER_RESET_STATUSES = {ok, orphaned}`).

## Retired predicates (must have zero live references — lock test #4)

| Retired | Replaced by | Phase |
|---------|-------------|-------|
| `可信(r)` (single 300s wall-clock predicate) | `证据资格` + `豁免资格` (D15′ double-role split) | 1 |
| `freshness_window` config key | `sync_freshness.{evidence_window_seconds, hard_cap_days, k_min}` | 0 (key added) → 1 (old key swept) |

## Reused from Spec B (not defined here, referenced)

- `_common.classify_git_error(rc, stderr, cmd) → GitErrorClass` (Spec B, shipped v1.58.0):
  F3′'s per-remote `error_kind` reuses this. Its own signal map (`_map_git_error_signal`)
  is a fixed-order first-match total function (git_missing→auth→non_ff→network→other),
  NOT a mutually-exclusive partition — locked by `test_r6m4_auth_before_network_when_both`
  in Spec B's suite. Do NOT re-register it here (different owner spec).

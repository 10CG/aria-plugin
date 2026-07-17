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
| `gitlink_orphaned(R)` | 2A (F10″/D14) | 8-branch cross-repo reachability; `true ⇒ blocking`; `orphan_unverified` visible + D18 time-escalation | ✅ (8 branches each with a home) | visible + escalate (fail toward visible, then red) |

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

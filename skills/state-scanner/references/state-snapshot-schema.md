# state-snapshot.json — Schema Definition (source-of-truth)

> **Status**: Draft (T4 partial — stub created per pre_merge R1-C5 to resolve docstring dead link)
> **Schema version**: `1.0`
> **Owner**: AD-SSME-6 (2026-04-23 audit revision): this document is the source of truth; `scan.py` references it via `SNAPSHOT_SCHEMA_VERSION` constant only.
> **Full schema authoring**: deferred to T4.1 (next session)

## Purpose

This document defines the canonical JSON structure of `.aria/state-snapshot.json` produced by `aria/skills/state-scanner/scripts/scan.py`. SKILL.md Phase 2 asserts against `snapshot_schema_version` and consumes the nested fields documented here.

## Top-level invariants (v1.0)

Field naming collision guard (CF-3): **`snapshot_schema_version`** at top level is the ONLY version gate SKILL.md hard-asserts on. Nested `issue_status.schema_version` (inside `.aria/cache/issues.json` consumed by Phase 1.13) is an independent field with its own lifecycle — do NOT conflate.

| Top-level key | Source | Versioning |
|---|---|---|
| `snapshot_schema_version` | scan.py constant | equality check in SKILL.md |
| `generated_by` | scan.py `"scan.py"` | informational |
| `project_root` | CLI arg `--project-root` | informational |
| `interrupt` | Phase 0 collector | additive keys OK without bump |
| `git` | Phase 1 collector | additive keys OK without bump |
| `upm` | Phase 1.4 collector | additive keys OK without bump |
| `changes` | Phase 1.5 collector | additive keys OK without bump |
| `requirements` | Phase 1.5-req collector | additive keys OK without bump |
| `openspec` | Phase 1.6 collector | additive keys OK without bump |
| `architecture` | Phase 1.7 collector | additive keys OK without bump |
| `readme` | Phase 1.8 collector | additive keys OK without bump |
| `standards` | Phase 1.9 collector | additive keys OK without bump |
| `audit` | Phase 1.10 collector | additive keys OK without bump |
| `errors` | aggregated fail-soft errors | informational |

## Additive-change policy (R1-I1 backend-architect audit response)

When Phase 1.11-1.14 collectors land in T3:
- **Additive** (no version bump): new top-level key or new nested optional field with default absent
- **Breaking** (v1.0 → v1.1): rename key, change type, remove key, make previously-optional field required
- **Forward** (v1.0 → v2.0): restructure schema shape

SKILL.md Phase 2 asserts `snapshot_schema_version == "1.0"` literal (T5.3). To preserve this equality check without rewriting SKILL.md for every T3 addition, T3 MUST keep additions additive-compatible and preserve `"1.0"`.

## Exit code consumer contract (R1-I2 backend-architect audit response)

| Exit code | Semantic | SKILL.md action |
|---|---|---|
| 0 | OK, snapshot usable | proceed to schema_version check |
| 10 | Scan partial (soft errors, snapshot still usable) | proceed with warning |
| 20 | Hard precondition failed (not a git repo) | abort without reading snapshot |
| 30 | Internal bug (uncaught exception) | abort with bug report |

## Sister-bug divergence from v2.9 prose (R1-C6 tech-lead audit response)

Proposal.md §非目标 states "不改变 Phase 1.x 的数据采集语义". The following 5 behaviors in scan.py are **intentional divergences** from v2.9 SKILL.md prose, classified as bug-fixes (not regressions):

| Aspect | v2.9 prose behavior | v3.0 scan.py behavior | Reason |
|---|---|---|---|
| `Approved` Status | collapsed to `ready` | preserved as `approved` | OpenSpec 5-state lifecycle distinct semantics |
| `Reviewed` Status | collapsed to `pending` | preserved as `reviewed` | OpenSpec 5-state lifecycle distinct semantics |
| `chain_valid` for `"(pending)"` parent_prd | True (false positive) | False (placeholder rejected) | Placeholder is not a valid PRD reference |
| YAML block scalar `key: \|` | leaks literal `"\|"` as value | returns None | Block scalars unsupported in stdlib-only parser |
| `Active`/`Deprecated`/`Archived` Status | mapped to `unknown` | preserved as `active`/`deprecated`/`archived` (R1-I5 fix) | PRD lifecycle parity |

T7.1 dogfooding diff MUST exclude these 5 fields from equivalence assertion (via T7.0 canonical normalizer whitelist) or else the diff will flag them as regressions.

## Full schema

To be authored in T4.1 (next session). Current stub is minimum-viable to resolve docstring dead link per pre_merge R1-C5.

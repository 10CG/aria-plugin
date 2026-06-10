# state-snapshot.json — Schema Definition (source-of-truth)

> **Status**: Active (T4.1 authoring complete, 2026-04-24)
> **Schema version**: `1.0`
> **Owner**: AD-SSME-6 (2026-04-23 audit revision): this document is the source of truth; `scan.py` references it via `SNAPSHOT_SCHEMA_VERSION` constant only.

## Purpose

This document defines the canonical JSON structure of `.aria/state-snapshot.json` produced by `aria/skills/state-scanner/scripts/scan.py`. SKILL.md Phase 2 asserts against `snapshot_schema_version` and consumes the nested fields documented here.

## Top-level invariants (v1.0)

Field naming collision guard (CF-3): **`snapshot_schema_version`** at top level is the ONLY version gate SKILL.md hard-asserts on. Nested `issue_status.schema_version` (inside `.aria/cache/issues.json` consumed by Phase 1.13) is an independent field with its own lifecycle — do NOT conflate.

| Top-level key | Collector | Optional? | Versioning |
|---|---|---|---|
| `snapshot_schema_version` | scan.py constant | required | equality check in SKILL.md |
| `generated_by` | scan.py `"scan.py"` | required | informational |
| `project_root` | CLI `--project-root` | required | informational |
| `interrupt` | Phase 0 | required | additive keys OK |
| `git` | Phase 1 | required | additive keys OK |
| `upm` | Phase 1.4 | required | additive keys OK |
| `changes` | Phase 1.5 | required | additive keys OK |
| `requirements` | Phase 1.5-req | required | additive keys OK |
| `openspec` | Phase 1.6 | required | additive keys OK |
| `architecture` | Phase 1.7 | required | additive keys OK |
| `readme` | Phase 1.8 | required | additive keys OK |
| `standards` | Phase 1.9 | required | additive keys OK |
| `audit` | Phase 1.10 | required | additive keys OK |
| `custom_checks` | Phase 1.11 | required | additive keys OK (T3.1+) |
| `sync_status` | Phase 1.12 | required | additive keys OK (T3.2+) |
| `issue_status` | Phase 1.13 | **optional** (only when `issue_scan.enabled=true`) | additive keys OK (T3.4+) |
| `forgejo_config` | Phase 1.14 | required | additive keys OK (T3.5+) |
| `handoff` | Phase 1.15 | required | additive keys OK (H0 spec, 2026-05-14) |
| `errors` | aggregated fail-soft | required | informational |

**Emission rule for optional keys**: Phase 1.13 `issue_status` is the only optional top-level key. Its absence signals `issue_scan.enabled=false`, which is semantically distinct from `issue_status: null`. Consumers checking for the feature should use `"issue_status" in snapshot`, not `snapshot.get("issue_status")`.

## Additive-change policy (R1-I1)

- **Additive** (no version bump): new top-level key or new nested optional field with default absent
- **Breaking** (v1.0 → v1.1): rename key, change type, remove key, make previously-optional field required
- **Forward** (v1.0 → v2.0): restructure schema shape

SKILL.md Phase 2 asserts `snapshot_schema_version == "1.0"` literal. To preserve this without rewriting SKILL.md for every addition, new fields MUST be additive-compatible and preserve `"1.0"`.

### Backward-compat contract for inter-cycle surfacing fields (TX.0/TX-G2/TX-G3/TX-G4, 2026-05-08)

The four new nested fields shipped under `state-scanner-inter-cycle-surfacing` are all additive — schema version stays `"1.0"`. Consumers MUST use defensive access:

| Field | Defensive access | Absent semantic |
|---|---|---|
| `git.status_clean` | `git.get("status_clean", False)` | pre-TX.0 scan.py — caller treats as not-clean |
| `upm.followups` | `upm.get("followups", [])` | no `## Pending Followups` section OR pre-TX-G2 scan.py — empty list |
| `upm.handoff_doc` | `upm.get("handoff_doc")` | pre-TX-G3 scan.py (key absent) vs scanned-no-match (key present, value null) |
| `requirements.stories.priority_items` | `stories.get("priority_items", [])` | pre-TX-G4 scan.py — empty list |

`upm.handoff_doc`'s explicit `null` (vs key-absent) is the only field that distinguishes "scanner ran, found nothing" from "scanner version too old to scan". Other three additive fields collapse both cases to empty/false on the consumer side.

### Backward-compat contract for archive-completeness-gate fields (#134, v1.42.0)

Two additive nested fields under `openspec` — schema version stays `"1.0"` (no bump). Consumers MUST use defensive access:

| Field | Defensive access | Absent semantic |
|---|---|---|
| `openspec.archive.items[].archive_type` | `item.get("archive_type")` | pre-v1.42.0 scan.py — caller treats as normal archive (same as explicit `null`) |
| `openspec.design_deferred` | `openspec.get("design_deferred", [])` | pre-v1.42.0 scan.py — empty list |

## Exit code consumer contract (R1-I2)

| Exit code | Semantic | SKILL.md action |
|---|---|---|
| 0 | OK, snapshot usable | proceed to schema_version check |
| 10 | Scan partial (soft errors, snapshot still usable) | proceed with warning |
| 20 | Hard precondition failed (not a git repo) | abort without reading snapshot |
| 30 | Internal bug (uncaught exception) | abort with bug report |

---

# Full Schema (T4.1)

Each section below documents one top-level key. Types use Python-ish syntax: `str`, `int`, `bool`, `null`, `list[T]`, `dict[K,V]`. Unknown to consumers = treat as additive; absent OK unless marked **required**.

## `interrupt` (Phase 0)

```yaml
present: bool                   # .aria/workflow-state.json 是否存在
status: str                     # "none" | "in_progress" | "suspended" | "failed" | "corrupted"
branch_anchor_match: bool|null  # 当前分支是否匹配 git_anchor.branch (null if either side null)
session_age_seconds: int|null   # 距上次 session activity 秒数 (T1.2 deferred: 目前恒为 null)
raw: dict|null                  # 原始 workflow-state.json 内容 (corrupted → null)
```

## `git` (Phase 1)

```yaml
is_git_repo: bool               # rev-parse --is-inside-work-tree
current_branch: str|null        # null when detached HEAD
detached_head: bool
staged_files: list[str]
unstaged_files: list[str]
untracked_files: list[str]
uncommitted_count: int          # dedupe by path (R1-I4), MM entries count once
status_clean: bool              # derived: staged_files == [] AND unstaged_files == []
upstream:
  configured: bool
  name: str|null                # "origin/master"
  ahead: int|null
  behind: int|null
  reason: str|null              # enum: null | "no_upstream" | "shallow_clone" | "detached_head" | "rev_list_failed" | "parse_failed"
recent_commits: list[{sha: str, subject: str}]  # up to 5
shallow: bool
git_operation_in_progress:        # Aria #135, additive (v1.39.0+)
  operation: str                  # enum: "none" | "rebase" | "merge" | "cherry_pick" | "revert" | "bisect"
  has_conflicts: bool             # only computed when operation != "none" (OQ4 conditional eval); else false
  detail: str|null                # best-effort rebase head-name/onto
```

Fail-soft: `is_git_repo=false` → all other fields absent except `is_git_repo`, and scan.py exits rc=20.

### `git.git_operation_in_progress` (Aria #135, state-scanner-git-operation-awareness 2026-06-05)

Detects a **paused git-layer operation** that both `detached_head` and the `interrupt` collector miss: in a suspended rebase `git branch --show-current` still returns the branch, so `detached_head` is `False` and `interrupt.status` (which only reads `.aria/workflow-state.json`) reports `none`. Collected by `collectors/git.py::_detect_git_operation` via `$GIT_DIR/` marker files (`rebase-merge`/`rebase-apply` → rebase, `MERGE_HEAD` → merge, `CHERRY_PICK_HEAD` → cherry_pick, `REVERT_HEAD` → revert, `BISECT_LOG` → bisect; priority rebase > merge > cherry_pick > revert > bisect).

**git dir resolution**: `git rev-parse --git-dir` returns a relative path in a normal checkout but absolute for linked worktrees/submodules; the collector resolves relative output against `project_root` (not CWD).

**Orthogonal to `interrupt.status`** — independent field, never mutates interrupt-recovery semantics. Stage 2 consumes it via the `git_operation_in_progress` recommendation rule (priority 0.5) to degrade/block checkout·branch recommendations.

**Fail-soft**: git-dir resolution failure or read error → `{"operation":"none","has_conflicts":false,"detail":null}` + `git_dir_unresolved`/`git_operation_probe_failed` soft_error; never blocks the rest of git collection.

**Versioning**: additive nested optional field under `git` → `snapshot_schema_version` stays `"1.0"` (per §Versioning additive rule; consumers built before this ship use `git.get("git_operation_in_progress", {...none...})` defensive access).

**Backward-compat**: clean repos always carry the field in none form; older `scan.py` versions omit it and consumers must default to none.

### `git.status_clean` (TX.0, state-scanner-inter-cycle-surfacing 2026-05-08)

Derived `bool` consumed by SKILL.md inter-cycle resume sanity check (post-TX.2 降级 form). Definition:

```python
status_clean = (staged_files == []) and (unstaged_files == [])
```

**Untracked files are deliberately excluded** — handoff scratch files / draft notes commonly remain untracked between cycles and should not flip the field to `false`. If callers need full-tree cleanliness they must compose `status_clean and untracked_files == []` themselves.

**Fail-soft**: when `git status` itself errors (collector emits `git_status_failed` soft_error), `status_clean = false` (conservative: assume work in progress until proven otherwise).

**Backward-compat**: this is a derived field on existing collector output — consumers built before TX.0 ship are unaffected; new consumers MUST use `git.get("status_clean", False)` defensive access for snapshots produced by older `scan.py` versions.

## `upm` (Phase 1.4)

```yaml
configured: bool                # UPM 文件存在且含 UPMv2-STATE block
source_file: str|null           # 相对路径
current_phase: str|null
current_cycle: str|null
active_module: str|null
raw_block: str|null             # YAML-ish 原始内容 (未配置时 null)

# ---- inter-cycle surfacing fields (G2 + G3, shipped 2026-05-09 sub-PR (b)) ----
# Both fields are OPTIONAL on the consumer side: scan.py emits them in the
# happy path (UPM file present + parseable). Defensive access still required:
# pre-TX-G2/G3 scanners (versions before sub-PR (b)) won't emit them.
followups: list[FollowupRow]    # G2 — Pending Followups markdown table parse
                                # ABSENT when UPM has no `## Pending Followups` section
                                # ABSENT in all error-paths (no UPM file / read error / no UPMv2-STATE block)
                                # PRESENT EMPTY [] when section exists but table is empty
handoff_doc: HandoffDoc|null    # G3 — Next session 入口 pointer detected in raw_block
                                # ABSENT in all error-paths (no UPM file / read error / no UPMv2-STATE block)
                                # null when scanned (raw_block present) but no match

# Substructures
FollowupRow:
  row_index: int                # 1-based, table row order (post-header)
  priority: str                 # normalized: "P0"|"P1"|"P2"|"P3"|"unknown"
  item: str|null                # Item column raw text
  source: str|null              # Source column raw text (link / issue / git ref)
  tracking: str|null            # Tracking column raw text
  next_action: str|null         # Next Action column raw text
  raw_row: str                  # full markdown row, fallback for unmapped columns
                                # NOTE: dropped by normalize_snapshot.py (TX.1.a)

HandoffDoc:
  path: str                     # relative to project_root when path is in-tree;
                                # absolute path preserved when outside project_root;
                                # original string preserved + soft_error("unsupported_path_format")
                                #   when http://|https:// URL
  exists: bool                  # filesystem check (false when path outside project / URL)
  raw_match: str                # full matched line, fallback for parser regression debug
                                # NOTE: dropped by normalize_snapshot.py (TX.1.a)
```

Missing UPM → `configured: false`, all other fields null **and** `followups` / `handoff_doc` keys absent.

### `upm.followups` (G2 — Pending Followups parse, shipped sub-PR (b) 2026-05-09)

> **Implementation history**: TX.0 + TX.1 prerequisite shipped sub-PR (a) 2026-05-09 (aria-plugin#37, SHA 8ecee44). G2 collector shipped sub-PR (b) 2026-05-09 (aria-plugin#38). Earlier "planned for TX-G2" qualifier removed once `_parse_followups_table` landed in `collectors/upm.py`.

Parser anchors strictly on `^[ \t]{0,3}#{2,3}\s+Pending Followups\s*$` (case-sensitive, halfwidth space only — fullwidth U+3000 explicitly rejected per BA-10 follow-up). Below the heading, scans line-by-line until a `|`-prefixed row, then consumes contiguous markdown table rows.

Column-name normalization map: `Priority` / `优先级` / `Pri` → `priority`; missing columns yield `null`. Pipe-escape `\|` is restored after split. Embedded inline code is preserved verbatim in cell values. **Multi-table negative**: only the first table after `## Pending Followups` is consumed; subsequent tables are ignored even if the heading appears multiple times.

**Field-absence semantics**:
- No `## Pending Followups` section → `followups` key **absent** (consumer: `upm.get("followups")` returns `None`)
- Section present but empty table (only header + separator) → `followups: []`

### `upm.handoff_doc` (G3 — handoff pointer detection, shipped sub-PR (b) 2026-05-09)

> **Implementation history**: shipped sub-PR (b) 2026-05-09 (aria-plugin#38). `_detect_handoff_doc` in `collectors/upm.py` implements primary regex (Chinese / English / Emoji enumeration) + R2-converged fallback (BA-02 fix removed standalone "入口" alternation) + three-state path resolution (BA-11 relative_to fail-soft).

Scans `raw_block` (top ±30 lines) for the first match of:

- **Primary regex**: `r"^>\s*[^\n]*?(?:Next session 入口|下次 session 入口|🚪 Next session)[^\n]*?\(([^)]+\.md)\)"`
- **Fallback regex** (R2-converged, 移除独立 "入口"): `r"^>\s*.*?(?:handoff|session)[^()\n]{0,80}\(([^)]+\.md)\)"`

The `[^()\n]` class enforces single-line + balanced-paren-free body to prevent `> Next session ...\n>(下一行) (handoff.md)` cross-line false-matches.

**Path resolution three-state** (per BA-11 follow-up):
- Relative path → `(project_root / raw).resolve()` → `relative_to(project_root)`; fail-soft preserves raw + `errors[]` adds `handoff_path_escapes_project` if `relative_to` raises ValueError
- Absolute path → `Path(raw).resolve()`, no `relative_to` rewrite, `exists()` honored
- URL (`http://` / `https://`) → `path = raw`, `exists = false`, `errors[]` adds `unsupported_path_format`

**`errors[]` enum produced by G3** (collector = `upm`):
- `unsupported_path_format` — path is `http(s)://` URL
- `handoff_path_escapes_project` — relative path resolves outside project_root

**Field-absence semantics**: zero matches → `handoff_doc: null` (key present, value null) — distinguishes "scanned, found nothing" from "scanner version too old to scan" (key absent).

## `changes` (Phase 1.5)

```yaml
change_count: int               # dedupe by path (R2-N3)
file_types:
  code: int
  test: int
  docs: int
  config: int
  other: int
complexity: str                 # enum: "Level 1" | "Level 2" | "Level 3"
architecture_impact: bool       # any path under docs/architecture/ or ARCHITECTURE.md
test_coverage: bool             # test count > 0 AND code count > 0
skill_changes:
  detected: bool                # any SKILL.md in changed paths
  modified_skills: list[str]    # dedupe, sorted
  ab_status:
    verified: list[str]
    needs_benchmark: list[str]
```

**TL-2 note**: `complexity` is an `advisory_from_collector` heuristic (hardcoded thresholds 0-2 L1 / 3-10 L2 / >10 L3 with arch/skill-impact escalation). Workflow-runner / AI may override.

## `requirements` (Phase 1.5-req)

```yaml
configured: bool                # docs/requirements/ exists
prd: list[{path: str, status: str, raw_status: str|null}]
stories:
  total: int
  by_status: dict[str, int]     # OPEN-ENDED: keys from normalized lifecycle states
  items: list[{id: str, path: str, status: str, raw_status: str|null}]
  # ---- inter-cycle surfacing field (G4, shipped 2026-05-09 sub-PR (b)) ----
  priority_items: list[PriorityItem]  # derived view of items[]
                                       # PRESENT (possibly []) when configured: true
                                       # ABSENT when configured: false (no docs/requirements/) or pre-TX-G4 scanner

PriorityItem:
  id: str                       # US-XXX
  status_normalized: str        # in_progress | ready | pending (only these 3 statuses)
  raw_status: str|null          # original raw_status string from items[] entry
  priority_hint: str|null       # future-extension placeholder (US frontmatter Priority); null in TX-G4 ship
  file: str                     # relative path to story md file
```

**Status normalization** preserves: `archived` / `deprecated` / `done` / `in_progress` / `approved` / `reviewed` / `active` / `ready` / `pending` / `unknown` (R1-I5). **`by_status` is NOT a fixed-key dict** (R3-BA1) — consumers must not assume specific keys present.

### `requirements.stories.priority_items` (G4 — in-progress surfacing, shipped sub-PR (b) 2026-05-09)

> **Implementation history**: shipped sub-PR (b) 2026-05-09 (aria-plugin#38). `_derive_priority_items` in `collectors/requirements.py` derives view from existing `items[]` (no fs re-glob) + 3-level stable sort + configurable limit via `state_scanner.priority_items_limit`.

**Derived view** of `stories.items[]` — collector does NOT re-glob the filesystem; it filters + sorts the already-collected `story_items` once at the end of the requirements collector pass.

**Filter**: `status_normalized ∈ {in_progress, ready, pending}`. All other statuses (`done` / `archived` / etc.) are excluded.

**Sort (three-level stable tie-break, deterministic across OS / git clone)**:
1. `_STATUS_ORDER` ASC: `in_progress=0` < `ready=1` < `pending=2`
2. file mtime DESC (most recently touched first within same status)
3. file path LEX ASC (alphabetic when status + mtime both tie — guards against `git clone` flat-mtime degeneration)

**Slice**: head N (default 5, configurable via `state_scanner.priority_items_limit`). `mtime` is read via `Path.stat().st_mtime` exactly once per selected item (N≤5 typical).

**Field-absence semantics**: no candidates → `priority_items: []`; pre-TX-G4 scan.py → key absent (consumer: `stories.get("priority_items", [])` defensive access).

**Status extraction patterns** (`collectors/_status.py::_STATUS_PATTERNS`, applied in order, first match wins):

| # | Pattern | Sample |
|---|---------|--------|
| 1 | `^**Status**[：:]\s*(.+)` | `**Status**: Active` |
| 2 | `^**状态**[：:]\s*(.+)` | `**状态**：pending` |
| 3 | `^>\s***Status**[：:]\s*(.+)` | `> **Status**: done` |
| 4 | `^(?:#{1,6}\s+)?Status[：:]\s*(.+)` | `## Status: Reviewed` |
| 5 | `^\|\s*(?:Status\|状态)\s*\|\s*(.+)\s*\|` | `\| Status \| active \|` |
| 6 | `^>\s*.*?**(Status\|状态)**[：:]\s*([^\|\n]+?)(?=\s*(?:\|\|$))` | `> **优先级**：P0 \| **状态**：pending` |

**i18n note** (Spec `state-scanner-i18n-status-regex`, 2026-04-25): patterns 1-4 accept BOTH halfwidth `:` (U+003A) and fullwidth `：` (U+FF1A) via `[：:]` character class — fullwidth colon is the default produced by Chinese IMEs. Pattern 6 captures inline blockquote multi-meta lines (e.g. Kairos `US-009-tts-voice-clone.md` real-world sample) where status is not the first key. Negative cases (prose mention of `状态` outside `**...**` bold inside blockquote) do NOT match — pattern 6 requires both `>` blockquote anchor AND `**...**` bold wrapper to fire.

## `openspec` (Phase 1.6 + 1.6.1)

```yaml
configured: bool                # openspec/changes/ exists
changes:
  total: int
  items: list[{id: str, path: str, status: str, raw_status: str|null}]
archive:
  total: int
  items: list[{path: str, date: str|null, feature: str,
               archive_type: str|null}]        # additive (#134, v1.42.0+); null=normal archive or proposal.md unreadable
pending_archive: list[{id: str, reason: str}]  # Status=done 仍在 changes/ (archive-ready 集 = {done} ONLY, `implemented` 刻意排除 — DEC-20260609-001 §3 D2)
design_deferred:                               # additive (#134, v1.42.0+) — gate↔surface 互补 surface (DEC-20260609-001 §3 D3)
  list[{
    id: str,                                   # change 目录名
    status: str,                               # normalized status (_normalize_status SOT)
    staleness_days: int,                       # proposal.md age, frontmatter updated-at 优先, 回落 mtime
    reason: str                                # is_spec_complete() 的 incomplete 诊断
  }]
carry_forward_inventory:                       # Phase 1.6.1 (v1.23.0+)
  total: int                                   # sum across all active changes
  active_change_count: int                     # disambiguates 0-active vs N-active-but-clean
  by_change:                                   # only changes with count>0 appear
    <change_id>:
      count: int
      samples: list[str]                       # first 3, each truncated to 80 chars + "..."
```

**design_deferred surface** (#134 `aria-archive-completeness-gate`, v1.42.0+, additive):

- **谓词** (collectors/openspec.py A2.2): `is_spec_complete(spec)==False ∩ ( normalized==unknown ∪ (normalized==approved ∧ staleness_days>=30) ∪ normalized∈{reviewed, active, implemented} )`
- **排除**: `{in_progress, ready, pending}` (由 `requirements.stories.priority_items` 别处 surface); fresh-approved (staleness<30d) 合法在飞, changes[].items 原样可见, 不卷入
- **complete 判定唯一 SOT**: `scripts/lib/spec_complete.py::is_spec_complete` (契约 A); staleness 阈值 N=30 为 hardcode 常量 (非 config)
- **archive_type 消费** (契约 B): 仅识别 `implementation-deferred`; 缺 frontmatter / 缺字段 = 正常归档 → null 无诊断; proposal.md 缺失 / OSError / 未知值 → null + `soft_error(archive_type_unreadable)` fail-soft

**Carry-forward inventory** (Spec `state-scanner-inline-carry-forward-surfacing`, v1.23.0):

- **Pattern**: `r'\[(?:carry-forward|TODO|defer(?:red)?|known[ -]gap|PASS-with-note)\b[\s\S]*?\]'`
  - Positional anchoring: token group must touch opening `[`
  - Token-end `\b` blocks substring extension (e.g., `[carry-forwarded-stuff]` does NOT match)
  - `[\s\S]*?` non-greedy cross-line capture (handles multi-line annotations + CRLF)
- **Scope**: only `openspec/changes/*/tasks.md` (active changes only); `archive/` excluded; `proposal.md` not scanned
- **Multi-line normalization**: `\r\n` + `\n` + `\r` → single space in samples
- **Empty state**: field always present; `total=0` when no annotations OR no active changes; `active_change_count` disambiguates the two zero cases
- **INCLUDE policy**: annotations inside fenced code blocks (` ``` `) and HTML comments (`<!-- ... -->`) ARE counted
- **Backward compat**: additive to snapshot_schema_version 1.0 (no breaking change to existing consumers)

Recommendation rules consuming this field: `carry_forward_info` (INFO tier, 1≤total<5) and `carry_forward_pile` (WARNING tier, total≥5) — see [RECOMMENDATION_RULES.md](../RECOMMENDATION_RULES.md).

## `architecture` (Phase 1.7)

```yaml
exists: bool                    # docs/architecture/system-architecture.md
path: str|null
status: str|null                # Status: header
last_updated: str|null          # Last Updated: header
parent_prd: str|null            # Parent PRD: header
chain_valid: bool|null          # placeholder strings rejected (IMP-2)
```

**Field extractor patterns** (`collectors/architecture.py`, regex hardening Spec
`state-scanner-collector-regex-hardening`, 2026-04-25):

3 fields (`Status` / `Last Updated` / `Parent PRD`) accept the union form:

```
^(?:#{1,6}\s+)?\s*>?\s*(?:\*\*)?<KEY>(?:\*\*)?[：:]\s*<VAL>
```

i.e. **optional heading prefix** (`## `, `### `, ...) + **optional blockquote
prefix** (`>`) + **optional bold wrapper** (`**...**`) + **dual colon** (halfwidth
`:` and fullwidth `：` for Chinese IME). Real-world patterns supported:

- `**Status**: Active` (baseline bold)
- `**Status**：Active` (i18n fullwidth colon)
- `## Status: Active` (heading-prefixed, no bold)
- `> **Status**: Active` (blockquote)
- `## **Status**: Active` (heading + bold combined)

## `readme` (Phase 1.8)

```yaml
root:
  exists: bool
  version: str|null             # parsed from **版本**: or **Version**:
submodules:
  aria:
    exists: bool
    readme_version: str|null
    plugin_version: str|null    # from aria/.claude-plugin/plugin.json
    version_match: bool|null    # null if either side missing
```

**Version pattern** (`collectors/readme.py::_VERSION_PAT`): same union form as
architecture (heading prefix + blockquote prefix + optional bold + dual colon).
Per Spec `state-scanner-collector-regex-hardening` (2026-04-25), supports
`## Version: v1.2.3` form alongside `**Version**: v1.2.3` and
`> **Version**: v1.2.3`. i18n fullwidth colon already supported since v1.17.1.

## `standards` (Phase 1.9)

```yaml
registered: bool                # path = standards in .gitmodules
initialized: bool               # standards/ dir exists and non-empty
```

## `audit` (Phase 1.10)

```yaml
enabled: bool|null              # null when .aria/audit-reports/ absent
last_audit:
  path: str
  checkpoint: str|null          # e.g. "post_spec", "pre_merge", "post_implementation"
  verdict: str|null             # "PASS" | "PASS_WITH_WARNINGS" | "FAIL"
  converged: bool|null          # YAML-coerced bool (R1-I6)
  timestamp: str|null
```

Empty audit dir → `{enabled: true, last_audit: null}`; absent dir → `{enabled: null, last_audit: null}`.

## `custom_checks` (Phase 1.11, T3.1)

```yaml
configured: bool                # .aria/state-checks.yaml exists AND parseable
parse_error: str|null           # only when configured=false due to YAML error
total: int                      # enabled checks actually run
passed: int
failed: int
results: list[{
  name: str,
  status: str,                  # "pass" | "fail" | "timeout" | "error" | "skipped"
  severity: str,                # "info" | "warning" | "error"
  output: str,                  # stdout first line OR "timeout after Ns" / "rc=N"
  fix: str                      # only present when config provided fix text
}]
```

## `sync_status` (Phase 1.12, T3.2 + T3.3)

```yaml
remote_refs_age: str            # "Nm" | "Nh" | "Nd" | "never"
has_remote: bool                # git remote non-empty
shallow: bool
current_branch:
  name: str|null
  upstream: str|null
  upstream_configured: bool
  ahead: int|null
  behind: int|null
  diverged: bool
  reason: str|null              # enum: null | "no_upstream" | "shallow_clone" | "detached_head" | "not_a_git_repo"
submodules: list[{
  path: str,
  tree_commit: str,
  head_commit: str|null,
  remote_commit: str|null,
  remote_commit_source: str,    # enum: "local_ref" | "unavailable"
  drift: {
    workdir_vs_tree: bool,
    tree_vs_remote: bool,
    behind_count: int|null,     # BA-I1: 0 when aligned (not null)
    ahead_count: int|null,      # null reserved for fail-soft only
    hint: str|null,
    hint_type: str|null         # enum: null | "update" | "push" | "manual_check"
  }
}]
multi_remote:
  enabled: bool
  main_repo: {                  # null when disabled OR not-a-git-repo
    local_head: str|null,
    branch: str|null,
    path: str,                  # "." for main repo (per T3.3 impl convention)
    remotes: list[RemoteEntry]
  }|null
  submodules: list[{
    path: str,
    local_head: str|null,
    branch: str|null,
    remotes: list[RemoteEntry]
  }]
  overall_parity: bool          # see 精确定义 below
  has_unreachable_remote: bool
  has_pending_push: bool
  local_refs_stale: bool        # only emitted when FETCH_HEAD age > warn_after_hours

RemoteEntry:
  name: str
  remote_head: str|null
  parity: str                   # enum: "equal" | "ahead" | "behind" | "diverged" | "unknown"
  behind_count: int|null
  ahead_count: int|null
  reachable: bool
  reason: str|null              # enum: null | "auth_failed" | "not_found" | "network_timeout" | "no_local_tracking_ref" | "remote_branch_missing" | "parse_error" | "shallow_clone" | "detached_head"
  method: str                   # enum: "local_refs" | "ls_remote"
```

### `overall_parity` 精确定义 (post-QA-C1 + BA-R1-C1)

- `true`: **至少一个** remote 的 `parity == equal` AND no remote has `parity ∈ {behind, diverged}`
- `false`: zero `equal` evidence OR any `parity ∈ {behind, diverged}`
- **zero-info inputs** (all unknown / empty list / not-a-git-repo) → `false`
- `parity: ahead` 不计入 `overall_parity` (→ `has_pending_push`)
- `parity: unknown` 不计入 `equal` 证据 (→ `has_unreachable_remote` when network-class)

**Worked examples** (closes BA-R2-M2):

| Scenario | remotes | overall_parity | has_pending_push | has_unreachable_remote |
|---|---|---|---|---|
| All synced | origin=equal, github=equal | true | false | false |
| Feature branch never pushed (single) | origin=unknown (no_local_tracking_ref) | **false** | false | false |
| Feature branch never pushed (multi) | origin=unknown, github=unknown | **false** | false | false |
| Mixed: one synced, one behind | origin=equal, github=behind | **false** | false | false |
| Mixed: one synced, one unknown | origin=equal, github=unknown | **true** | false | false |
| **Single remote, unpushed commit** | origin=ahead (1 commit) | **false** | **true** | false |
| Multi: synced + unpushed | origin=equal, github=ahead | **true** | **true** | false |
| Network failure | origin=equal, github=unknown (network_timeout) | **true** | false | **true** |
| All networks down | origin=unknown (timeout), github=unknown (timeout) | false | false | **true** |
| Not a git repo | (empty, fallback) | false | false | false |

## `issue_status` (Phase 1.13, T3.4) — optional

Only present when `.aria/config.json` has `state_scanner.issue_scan.enabled: true`.

```yaml
schema_version: str             # writer always "1.1"; reader accepts {"1.0", "1.1"}
fetched_at: str                 # ISO 8601, min() across repos (conservative)
source: str                     # enum: "cache" | "live" | "unavailable"
fetch_error: str|null           # see fetch_error enum below
platform: str|null              # enum: "forgejo" | "github" | null
open_count: int
items: list[IssueItem]          # aggregated flat view
open_issues: list[IssueItem]    # v1.0 alias, same list object
repos: dict[str, {              # v1.1+: grouped by "owner/repo" key
  platform: str,
  source: str,
  fetch_error: str|null,
  fetched_at: str,
  open_count: int,
  items: list[IssueItem]
}]
label_summary: dict[str, int]   # label → count across all repos
warning: str|null               # "stage_timeout" when submodule scan was interrupted by total budget exhaustion; null otherwise. Unconditionally emitted (even on cache hits) per issue_scan.py:722.

IssueItem:
  number: int
  title: str
  labels: list[str]
  url: str
  repo: str                     # "owner/repo"
  linked_openspec: str|null     # heuristic match against openspec/changes/ dir names
  linked_us: str|null           # heuristic match against docs/requirements/user-stories/
  heuristic: bool               # always true (indicates linked_* fields are heuristic guesses)
```

### `fetch_error` enum (10 values)

| # | Value | Trigger |
|---|---|---|
| 1 | `network_unavailable` | offline / network unreachable |
| 2 | `cli_missing` | `forgejo` or `gh` CLI not in PATH |
| 3 | `auth_missing` | **reserved** — defined but never emitted in v1.0 (BA-I2). Token-probe code path scheduled for future enhancement; HTTP 401/403 currently coerces to `auth_failed` instead. |
| 4 | `auth_failed` | HTTP 401/403, invalid token |
| 5 | `rate_limited` | HTTP 429 |
| 6 | `not_found_or_no_access` | HTTP 404 OR private repo without access |
| 7 | `timeout` | API response > `api_timeout_seconds` |
| 8 | `platform_unknown` | all 4 platform-detection tiers failed |
| 9 | `parse_error` | JSON decode failure |
| 10 | `unknown` | catch-all |

### PR filtering (QA-C2)

`_normalize_items` rejects any raw item where:
- `"pull_request"` key is present (Forgejo PR marker), OR
- URL contains `"/pulls/"` (GitHub/Forgejo PR URL pattern)

`type=issues` query param is sent to Forgejo as defense-in-depth but is not relied upon (unreliable on older Forgejo versions).

## `forgejo_config` (Phase 1.14, T3.5)

```yaml
forgejo_remote_detected: bool
instance: str                   # only when detected=true
config_status: str              # only when detected=true; enum: "missing" | "incomplete" | "configured"
suggestion: str                 # only when detected=true AND config_status ∈ {missing, incomplete}
```

Four output states per SKILL.md §1.14:
1. `{forgejo_remote_detected: false}` — non-Forgejo origin, no further fields
2. `{forgejo_remote_detected: true, instance: "forgejo.10cg.pub", config_status: "missing", suggestion: "..."}` — no CLAUDE.local.md
3. Same shape but `config_status: "incomplete"` — file exists, no `forgejo:` block
4. `{forgejo_remote_detected: true, instance: "forgejo.10cg.pub", config_status: "configured"}` — no suggestion

**`forgejo:` block detection patterns** (`collectors/forgejo_config.py`, regex
hardening Spec `state-scanner-collector-regex-hardening`, 2026-04-25):

- `_FORGEJO_YAML_KEY = ^\s*>?\s*forgejo\s*[：:]` — accepts halfwidth + fullwidth
  colon (Chinese IME default `forgejo：`) + optional blockquote prefix
  (`> forgejo:` form found in mixed prose+config CLAUDE.local.md)
- `_FORGEJO_HEADING = ^\s*>?\s*#{1,3}\s+forgejo\b` — accepts blockquote-prefixed
  headings (`> ### forgejo`)
- Fenced code blocks (```yaml ... ```) are masked before matching (QA-I3 fix)

**QA-I3 fix**: `_has_forgejo_block` masks fenced code blocks (` ``` ... ``` `) before running YAML-key + heading heuristics to avoid false-positive "configured" on documentation examples.

**Known limitations** (carry-over from pre_merge audit, T6/T8 scope):
- `_KNOWN_FORGEJO_HOSTS` is a hardcoded tuple (not config-driven). Cross-project adopters on a different Forgejo instance must edit the collector source. Asymmetric with `issue_scan.platform_hostnames` which IS configurable.
- Only `origin` remote is checked. Non-origin Forgejo remotes (e.g. `upstream`) silently yield `forgejo_remote_detected: false`.

## `handoff` (Phase 1.15, H0 spec 2026-05-14)

```yaml
exists: bool                    # true if docs/handoff/*.md has any file
latest_path: str | null         # relative path to latest .md (pointer-first, mtime fallback)
latest_filename: str | null     # basename of latest_path
last_modified_iso: str | null   # UTC ISO 8601 (timezone-aware) of mtime
age_hours: float | null         # (time.time() - mtime) / 3600, rounded 2dp
latest_source: str | null       # "pointer" | "mtime" | null (H5 fix transparency)
misplaced_files: list[str]      # relative paths under .aria/handoff/*.md
canonical_dir: str              # always "docs/handoff/" (literal constant)
```

**`latest.md` is never itself a candidate (QA-M2, H1 follow-up doc)**:
the `docs/handoff/latest.md` pointer file is a navigation aid, not a
handoff document. `collectors/handoff.py::_scan_md_files` excludes the
`POINTER_FILENAME` (`latest.md`) constant from the candidate set entirely —
it never appears in `latest_path`, never counts toward `exists`, and is
not flagged in `misplaced_files`. A directory containing **only**
`latest.md` yields `exists=false`. (Without this exclusion, the pointer —
re-touched on every handoff write — would always win the mtime sort.)

**Latest detection (H5 fix, 2026-05-16)**: among the non-pointer
candidates, `latest_path` prefers the `docs/handoff/latest.md` pointer
*target* (the human-maintained semantic "Latest"). Raw mtime-max is only a
**fallback** — used when the pointer is absent / unparseable / targets a
missing file. `latest_source` exposes which path was taken
(`"pointer"` | `"mtime"` | `null`).

**Why**: a predecessor handoff edited post-hoc (closeout finalize / rebase /
typo fix) gets the newest mtime and would otherwise shadow the real latest
(memory `feedback_handoff_mtime_vs_pointer_divergence` — discovered at H0
closeout when an edited H0 handoff out-ranked the newer US-025 handoff).
Stale pointer (target absent) → `soft_error("handoff_pointer_target_missing")`
+ mtime fallback.

**Surfacing contract**: AI in state-scanner Phase 2 推荐前 SHOULD read
`handoff.latest_path` if `exists=true` AND `age_hours < 720` (30 days),
to ground recommendations in the previous session's carry-forward priority.
Since H5 fix `latest_path` is already pointer-resolved — AI no longer needs
to separately parse `latest.md` (collector does it mechanically).

**Drift detection** (Layer 2 of 5-layer enforcement, see OpenSpec
`aria-ten-step-session-handoff-stage` proposal §Layered defense matrix):
`misplaced_files != []` is the trigger signal for `RECOMMENDATION_RULES.md`
`handoff_drift` rule (Layer 3), which surfaces migration as priority workflow.

**Why `time.time()` not `datetime.now()`**: Avoid timezone/DST ambiguity.
mtime is filesystem-native UTC seconds-since-epoch; `time.time()` returns
the same scale. `datetime.now()` is local-time by default and would skew
`age_hours` by tz offset.

**Edge cases**:
- `docs/handoff/` absent or empty → `exists=false, latest_path=null,
  age_hours=null` but `misplaced_files` still computed
- Non-UTF-8 filename under canonical dir → silently skipped (rare; only on
  Linux filesystems with mixed encoding)
- `stat()` fails on a candidate file → `soft_error("handoff_stat_failed")`
  emitted to `errors[]`, `latest_path=null`, `latest_source=null`
- `latest.md` pointer targets a file absent from canonical dir →
  `soft_error("handoff_pointer_target_missing")` + mtime fallback
  (`latest_source="mtime"`)

## `errors` (aggregated fail-soft)

```yaml
errors: list[{
  collector: str,               # e.g. "git", "sync", "issue_scan"
  error: str,                   # snake_case error kind
  detail: str                   # human-readable context
}]
```

Every soft_error across all collectors is aggregated here in call order, namespaced by collector name. Exit code 10 fires when this list is non-empty.

---

## Change history

| Date | Change |
|---|---|
| 2026-04-23 | Stub created per pre_merge R1-C5 (docstring dead link fix) |
| 2026-04-24 | Full schema authored (T4.1) — 4 new top-level keys documented, BA-R*-I1 (`main_repo.path` + `items[].heuristic`) + BA-R*-M1/M2 (`auth_missing` reserved, single-remote ahead prose) + overall_parity worked examples + QA-C2 PR filtering + all fail-soft enum values backfilled |
| 2026-05-09 | TX.0 + TX.1 (state-scanner-inter-cycle-surfacing sub-PR-a) — 4 inter-cycle nested fields documented: `git.status_clean` (TX.0 ship), `upm.followups[]` + `upm.handoff_doc` (TX-G2/G3 reserved schema), `requirements.stories.priority_items[]` (TX-G4 reserved schema); backward-compat contract section added; schema version stays `"1.0"` (additive) |
| 2026-05-09 | sub-PR (b) — TX-G2/G3/G4 collectors shipped (aria-plugin#38). "Planned" qualifiers replaced with "shipped" + Implementation history blockquotes. KM-08 prerequisite NOTE blockquotes removed (gates satisfied). Error-path absence semantics clarified for `followups` + `handoff_doc` (both ABSENT in error-paths, schema previously documented only the no-UPM-file case). `errors[]` enum produced by G3 documented (`unsupported_path_format` + `handoff_path_escapes_project`) |
| 2026-05-14 | H0 (`aria-ten-step-session-handoff-stage`) T1 — added `handoff` top-level field (Phase 1.15). Additive, schema stays `"1.0"`. Surfaces latest `docs/handoff/*.md` for AI to read pre-recommendation + detects misplaced `.aria/handoff/*.md` for Layer 2 drift detection (5-layer enforcement). |
| 2026-05-16 | H5 fix (`fix/h5-handoff-pointer-divergence`) — `latest_path` now prefers `docs/handoff/latest.md` pointer target over raw mtime (mtime fallback only). New additive `latest_source` field (`"pointer"`/`"mtime"`/`null`). New `soft_error("handoff_pointer_target_missing")` for stale pointer. Schema stays `"1.0"` (additive). Fixes mtime-vs-pointer divergence found at H0 closeout. |
| 2026-06-10 | #134 `aria-archive-completeness-gate` (v1.42.0) — two additive nested fields under `openspec`: `archive.items[].archive_type` (str\|null, 契约 B 消费侧) + `design_deferred[]` (id/status/staleness_days/reason, gate↔surface 互补 per DEC-20260609-001 §3 D3). Backward-compat contract subsection added. Schema stays `"1.0"` (additive, no bump). |

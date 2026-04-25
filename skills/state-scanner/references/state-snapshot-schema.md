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
| `errors` | aggregated fail-soft | required | informational |

**Emission rule for optional keys**: Phase 1.13 `issue_status` is the only optional top-level key. Its absence signals `issue_scan.enabled=false`, which is semantically distinct from `issue_status: null`. Consumers checking for the feature should use `"issue_status" in snapshot`, not `snapshot.get("issue_status")`.

## Additive-change policy (R1-I1)

- **Additive** (no version bump): new top-level key or new nested optional field with default absent
- **Breaking** (v1.0 → v1.1): rename key, change type, remove key, make previously-optional field required
- **Forward** (v1.0 → v2.0): restructure schema shape

SKILL.md Phase 2 asserts `snapshot_schema_version == "1.0"` literal. To preserve this without rewriting SKILL.md for every addition, new fields MUST be additive-compatible and preserve `"1.0"`.

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
upstream:
  configured: bool
  name: str|null                # "origin/master"
  ahead: int|null
  behind: int|null
  reason: str|null              # enum: null | "no_upstream" | "shallow_clone" | "detached_head" | "rev_list_failed" | "parse_failed"
recent_commits: list[{sha: str, subject: str}]  # up to 5
shallow: bool
```

Fail-soft: `is_git_repo=false` → all other fields absent except `is_git_repo`, and scan.py exits rc=20.

## `upm` (Phase 1.4)

```yaml
configured: bool                # UPM 文件存在且含 UPMv2-STATE block
source_file: str|null           # 相对路径
current_phase: str|null
current_cycle: str|null
active_module: str|null
raw_block: str|null             # YAML-ish 原始内容 (未配置时 null)
```

Missing UPM → `configured: false`, all other fields null.

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
```

**Status normalization** preserves: `archived` / `deprecated` / `done` / `in_progress` / `approved` / `reviewed` / `active` / `ready` / `pending` / `unknown` (R1-I5). **`by_status` is NOT a fixed-key dict** (R3-BA1) — consumers must not assume specific keys present.

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

## `openspec` (Phase 1.6)

```yaml
configured: bool                # openspec/changes/ exists
changes:
  total: int
  items: list[{id: str, path: str, status: str, raw_status: str|null}]
archive:
  total: int
  items: list[{path: str, date: str|null, feature: str}]
pending_archive: list[{id: str, reason: str}]  # Status=done 仍在 changes/
```

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

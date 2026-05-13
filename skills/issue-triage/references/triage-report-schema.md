# Triage Report JSON Schema

> **Schema version**: 1.0
> **Source of truth**: this file (`references/triage-report-schema.md`)
> **Machine-readable companion**: `references/triage-report.schema.json` (jsonschema draft-07, used by CI gate)
> **Producer**: `scripts/triage.py` (Steps 1-5 mechanical; Step 6 AI-completed)
> **Consumer**: `SKILL.md` AI pipeline, CI schema validation, dogfooding rubric (T5)

---

## Top-level fields

| Field | Type | Required | Description |
|---|---|---|---|
| `schema_version` | string (semver) | yes | Always `"1.0"` for this revision |
| `triage_tool_version` | string | yes | Plugin version from `aria/.claude-plugin/plugin.json` (Step 2 collector reads this per R2 QA-R2-m3) |
| `issue_ref` | string | yes | `"<owner>/<repo>#N"` — canonical issue reference |
| `generated_at` | string (ISO-8601) | yes | UTC timestamp when triage.py ran |
| `steps` | object | yes | Nested per-step data (see below) |
| `repro` | object | yes | Step 6 reproduction results (AI-completed; scaffold present in mechanical output) |
| `verdict` | string (enum) | yes | One of 7 verdict values (AI-determined in Step 6) |
| `severity` | string (enum) | yes | `"critical"` \| `"major"` \| `"minor"` \| `"trivial"` (AI-determined) |
| `recommended_action` | string (enum) | yes | `"hotfix"` \| `"next-cycle"` \| `"backlog"` \| `"close"` (AI-determined) |
| `deviation_note` | string | **conditional** | Required when `verdict == "partial-repro"` (see Conditional requirement below) |
| `errors` | array | yes | Collector soft-error list; empty array on full success |

---

## `steps` object

### `steps.step1_issue` — Read issue

| Field | Type | Description |
|---|---|---|
| `collection_status` | `"ok"` \| `"error"` \| `"skipped"` | Collector outcome |
| `number` | integer | Issue number |
| `title` | string | Issue title |
| `body` | string | Issue body (raw markdown) |
| `state` | string | `"open"` \| `"closed"` |
| `labels` | array of string | Label names |
| `comments` | array of `{id, body, user, created_at}` | Issue comments |
| `url` | string | Issue URL |
| `created_at` | string (ISO-8601) | Issue creation timestamp |
| `updated_at` | string (ISO-8601) | Issue last-update timestamp |

### `steps.step2_version` — Version check

| Field | Type | Description |
|---|---|---|
| `collection_status` | `"ok"` \| `"error"` \| `"skipped"` | Collector outcome |
| `reported` | string \| null | Version extracted from issue body/comments (regex `version: X.Y.Z` / `Plugin: X.Y.Z`) |
| `current` | string | Current project version (`"unknown"` if all 5 paths failed) |
| `gap` | `"same"` \| `"behind"` \| `"ahead"` \| `"different"` \| null | Comparison result; null when either side is unknown |

**Fail-soft version discovery chain** (first hit wins):

1. `{project_root}/aria/.claude-plugin/plugin.json` → `version` field (Aria meta-repo)
2. `{project_root}/.claude-plugin/plugin.json` → `version` field (Aria plugin standalone)
3. `{project_root}/VERSION` → first semver-looking line
4. `{project_root}/package.json` → `version` field (JS projects)
5. `{project_root}/pyproject.toml` → `[project] version` or `[tool.poetry] version`
6. All fail → `current: "unknown"`, `gap: null`

### `steps.step3_code` — Code path verification

| Field | Type | Description |
|---|---|---|
| `collection_status` | `"ok"` \| `"error"` \| `"skipped"` | Collector outcome (`"skipped"` if no citations found) |
| `cited_paths` | array of `CitedPath` | One entry per citation found in issue body/comments |
| `matches_description` | boolean \| null | `true` if all cited files exist and all cited line numbers are in range; `null` if no citations |

**`CitedPath` object**:

| Field | Type | Description |
|---|---|---|
| `file_path` | string | File path as cited in the issue |
| `line` | integer \| null | Cited line number (null if not specified) |
| `format` | string | Citation format: `"backtick"` \| `"prose_line"` \| `"prose_l"` \| `"md_link"` \| `"md_link_local"` |
| `exists` | boolean \| null | Whether the file was found under project_root |
| `line_in_range` | boolean \| null | Whether the cited line is within file bounds; null if no line cited |
| `snippet` | string \| null | Code snippet around cited line (±3 lines, with line numbers) |
| `warning` | string \| null | Non-fatal warning (e.g. line out of range, file read error) |
| `total_lines` | integer | Total line count of the file (when `exists=true`) |

**Supported citation formats**:

1. **Backtick inline**: `` `path/to/file.py:42` `` or `` `path/to/file.py` ``
2. **Prose line**: `path/to/file.py line 42` or `path/to/file.py L42` or `path/to/file.py:42`
3. **Markdown link**: `[text](https://host/owner/repo/blob/sha/path/to/file.py#L42)` or `[text](path/to/file.py#L42)` (local)

### `steps.step4_history` — Git history

| Field | Type | Description |
|---|---|---|
| `collection_status` | `"ok"` \| `"error"` \| `"skipped"` | Collector outcome (`"skipped"` if no cited files exist) |
| `likely_fix_candidates` | array of `FixCandidate` | Commits matching fix keywords; empty array = no candidates (boolean false at read time) |

**`FixCandidate` object**:

| Field | Type | Description |
|---|---|---|
| `sha` | string | Short commit SHA |
| `message` | string | Commit subject line |
| `file` | string | File path that produced this candidate |
| `match_reason` | array of string | Keyword labels that triggered the match (e.g. `["fix", "issue_ref_#101"]`) |

**Match keywords**: `fix`, `resolve`, `close #N`, `normalize`, `bug`, `revert`, `patch`, `regression`, `hotfix`, `issue_ref_#N`

### `steps.step5_inflight` — In-flight check

| Field | Type | Description |
|---|---|---|
| `collection_status` | `"ok"` \| `"error"` \| `"skipped"` | Collector outcome |
| `remote_prs` | array of `InFlightPR` | Open PRs keyword-matched against issue context |
| `local_branches` | array of string | Branch names (including remote-tracking) matching issue keywords |
| `worktrees` | array of `Worktree` | All git worktrees from `git worktree list --porcelain` |

**`InFlightPR` object**:

| Field | Type | Description |
|---|---|---|
| `number` | integer \| null | PR number |
| `title` | string | PR title |
| `state` | string | PR state (always `"open"` for this query) |
| `html_url` | string | PR URL |
| `head_branch` | string | Source branch name |
| `match_reasons` | array of string | Keywords that triggered the match |

**`Worktree` object**:

| Field | Type | Description |
|---|---|---|
| `path` | string | Absolute filesystem path to the worktree |
| `branch` | string \| null | Branch checked out (null for detached HEAD) |
| `is_main` | boolean | True for the primary checkout |
| `head` | string | HEAD SHA (present for detached HEAD) |

---

## `repro` object (Step 6 — AI-completed)

| Field | Type | Required | Description |
|---|---|---|---|
| `exit_mode` | `"auto"` \| `"pause"` \| `"skip"` | yes | How Step 6 terminated |
| `cases` | array of `ReproCase` | yes | One entry per reproduction attempt (≥1 even when skipped to record missing-env reason) |
| `hit_count` | integer | yes | Number of cases where `match=true` (for mechanical comparison) |
| `total_count` | integer | yes | Total number of cases attempted |
| `hit_rate` | string | yes | Human-readable `"N/M"` string (e.g. `"2/4"`) |

**`ReproCase` object**:

| Field | Type | Required | Description |
|---|---|---|---|
| `case_id` | string | yes | Unique identifier for this case |
| `input` | string | yes | Input or trigger used |
| `expected_behavior` | string | yes | What the issue says should happen |
| `actual_behavior` | string | yes | What was observed |
| `match` | boolean \| null | yes | `true`=reproduced, `false`=not reproduced, `null`=inconclusive |
| `notes` | string | no | Additional notes from AI |

---

## Verdict enum (7 values)

| Verdict | Meaning |
|---|---|
| `confirmed` | Reproduced successfully; bug is real and consistent with issue description |
| `partial-repro` | Real defect found, but symptoms or hit-rate substantially deviate from the issue description (requires `deviation_note`) |
| `not-reproducible` | Could not reproduce the reported symptoms |
| `fixed-in-X` | Already fixed in commit/version X (Step 4 candidate found) |
| `duplicate-of-#N` | Another issue already covers this (reference the duplicate) |
| `needs-info` | Report is insufficient, or Step 6 was `skip` mode |
| `wont-fix` | Confirmed by-design or out-of-scope |

---

## Conditional requirement: `deviation_note`

When `verdict == "partial-repro"`, the `deviation_note` field is **required** (must be a non-empty string). This is enforced by the jsonschema `if/then` conditional in `triage-report.schema.json`:

```json
{
  "if": {
    "properties": { "verdict": { "const": "partial-repro" } },
    "required": ["verdict"]
  },
  "then": {
    "required": ["deviation_note"],
    "properties": {
      "deviation_note": { "type": "string", "minLength": 1 }
    }
  }
}
```

**Rationale**: `partial-repro` is the hardest verdict to communicate — the reporter and maintainer may disagree on what was observed. Forcing `deviation_note` ensures the structural discrepancy is explicitly documented. Origin: Aria issue #101 (self-reported 4/4, actual 2/4 main cause + 2/4 secondary bug).

---

## Exit code contract

| Code | Condition | Report written? |
|---|---|---|
| `0` | `steps_with_data == 5` | Yes |
| `10` | `steps_with_data >= 2 AND <= 4` | Yes |
| `30` | `steps_with_data < 2` | **No** (hard fail) |

Evaluation order: check `< 2` first (hard fail), then `<= 4` (partial), else `0`.

Exit 30 also emits to stderr: `"Insufficient data — check credentials and issue ref"`

---

## Schema history

| Version | Date | Changes |
|---|---|---|
| `1.0` | 2026-05-13 | Initial schema (T1.7, SCOPE_OK_R2) |

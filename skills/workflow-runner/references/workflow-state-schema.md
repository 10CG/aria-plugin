# Workflow State Schema Specification

> **Version**: 1.1 | **Format**: `aria-workflow-state/v1`
> **Consumers**: state-scanner, workflow-runner, phase-c-integrator (gate_state)
> **Storage**: `.aria/workflow-state.json` (project root)
> **Last change (v1.1, 2026-05-10)**: additive — `gate_state` top-level optional block (#60 D2)

---

## 1. Complete JSON Schema

```json
{
  "$schema": "aria-workflow-state/v1",
  "format_version": "1.1",

  "session": {
    "id": "string (sess-YYYYMMDD-XXXXXX)",
    "started_at": "string (ISO 8601)",
    "last_active_at": "string (ISO 8601)",
    "status": "in_progress | suspended | failed | completed"
  },

  "workflow": {
    "name": "string (workflow template ID)",
    "phases": ["string (phase letter)"],
    "current_phase": "string (phase letter or null)",
    "current_step": "string (step ID or null)",
    "auto_proceed": "boolean",
    "spec_id": "string | null"
  },

  "gates": {
    "gate1_spec_approved": "boolean",
    "gate2_merge_main": "boolean"
  },

  "gate_state": {
    "name": "string (pre_merge | pre_release | pre_deploy)",
    "status": "string (waiting | green | fail)",
    "started_at": "string (ISO 8601)",
    "retry_count": "integer (>=0)",
    "next_check_at": "string (ISO 8601)",
    "in_flight_runs": [
      {
        "run_id": "integer",
        "branch": "string",
        "started_at": "string (ISO 8601)",
        "elapsed_seconds": "integer (>=0)"
      }
    ],
    "primitive_used": "string (aether-ci-cli | manual)",
    "raw_message": "string"
  },

  "phase_results": {
    "<phase_letter>": {
      "status": "pending | in_progress | completed | failed | skipped",
      "started_at": "string (ISO 8601) | null",
      "completed_at": "string (ISO 8601) | null",
      "output": "object (phase-specific context)",
      "error": "string | null"
    }
  },

  "git_anchor": {
    "branch": "string",
    "commit_sha_at_start": "string (40-char hex SHA)",
    "worktree_path": "string | null"
  },

  "integrity": {
    "state_hash": "string (sha256:<hex>)",
    "validated_at": "string (ISO 8601)"
  }
}
```

### 1.1 Field Descriptions

#### `session`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | yes | Unique session identifier. Format: `sess-YYYYMMDD-XXXXXX` where `XXXXXX` is 6 random hex chars. Generated once at workflow start; never changes. |
| `started_at` | string | yes | ISO 8601 timestamp of workflow creation. |
| `last_active_at` | string | yes | ISO 8601 timestamp of the most recent state write. Updated on every persist. Used for concurrent session detection and staleness checks. |
| `status` | enum | yes | One of: `in_progress`, `suspended`, `failed`, `completed`. |

#### `workflow`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Workflow template identifier: `feature-dev`, `quick-fix`, `full-cycle`, `doc-update`, `commit-only`, or a custom name. |
| `phases` | string[] | yes | Ordered list of phase letters to execute (e.g., `["A", "B", "C"]`). Immutable after creation. |
| `current_phase` | string\|null | yes | The phase letter currently executing. `null` before first phase starts or after all phases complete. |
| `current_step` | string\|null | no | The step currently executing within the current phase (e.g., `"B.2"`). `null` when between steps. |
| `auto_proceed` | boolean | yes | If `true`, automatically advance to the next phase on completion. If `false`, pause after each phase for user confirmation. |
| `spec_id` | string\|null | no | OpenSpec change identifier associated with this workflow. Set during Phase A or passed from state-scanner context. |

#### `gates`

Quality gates that guard phase transitions. A gate must be `true` before the workflow may proceed past the corresponding checkpoint.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `gate1_spec_approved` | boolean | `false` | Set to `true` when the OpenSpec proposal is approved. Required before Phase A exits to Phase B. Workflows that skip Phase A (e.g., `quick-fix`) initialize this to `true`. |
| `gate2_merge_main` | boolean | `false` | Set to `true` when the feature branch is confirmed mergeable to main (CI green, no conflicts). Required before Phase C step C.2 (merge). |

#### `gate_state` (added v1.1, optional, may be `null`)

Tracks the currently-active **pre-action gate** (a gate that runs before a phase's action and may suspend the workflow waiting for an external condition). Currently only `pre_merge` is shipped (consumes phase-c-integrator C.2.4 + aether `--in-flight` primitive); `pre_release` / `pre_deploy` are reserved for future Specs.

Distinct from `gates.*` which are quality-gate booleans (passed/not-passed). `gate_state` is a stateful waiter object with retry / timing / external-state metadata.

| Field | Type | Required when present | Description |
|-------|------|------------------------|-------------|
| `name` | string | yes | Gate identifier. Open-set string for future extensibility; current shipped value: `pre_merge`. |
| `status` | enum | yes | `waiting` (in polling loop), `green` (last check passed, ready to consume), `fail` (last check failed, gate stopped). |
| `started_at` | string | yes | ISO 8601 of first gate check (entry to wait_recoverable). |
| `retry_count` | integer | yes | Number of completed polling cycles. Starts at 0; increments per re-invoke. |
| `next_check_at` | string | yes | ISO 8601 wall clock of next scheduled gate check. Used on resume to decide immediate-recheck vs wait-remainder. |
| `in_flight_runs` | array | yes | Snapshot of upstream in-flight CI runs from last check. Empty array when `status=green`. |
| `primitive_used` | string | yes | Source of the gate query: `aether-ci-cli` (normal) or `manual` (no-aether fallback path). |
| `raw_message` | string | no | Human-readable annotation, esp. on `fail` to surface upstream error. May be empty string. |

**Defensive access**: All consumers MUST use `state.get("gate_state") or {}` rather than `state["gate_state"]` to handle v1.0 state files migrated to v1.1 runtime (where field defaults to `null`).

**Lifecycle**:
- Created by phase-c-integrator C.2.4 first wait verdict
- Updated each polling cycle (retry_count += 1, next_check_at recomputed)
- Cleared (set to `null`) on workflow completion or final verdict (green merged / fail stopped)
- Preserved across workflow suspension (Ctrl-C → `session.status: suspended`) for resume

#### `phase_results`

Keyed by phase letter (`"A"`, `"B"`, `"C"`, `"D"`). Only phases listed in `workflow.phases` are expected to have entries.

| Field | Type | Description |
|-------|------|-------------|
| `status` | enum | One of: `pending`, `in_progress`, `completed`, `failed`, `skipped`. |
| `started_at` | string\|null | ISO 8601 timestamp when the phase began execution. |
| `completed_at` | string\|null | ISO 8601 timestamp when the phase reached a terminal status. |
| `output` | object | Phase-specific context data (see section 1.2). Passed as input context to subsequent phases via the context chain. |
| `error` | string\|null | Human-readable error description if `status` is `failed`. |

#### `git_anchor`

Captures the Git state at workflow start for drift detection.

| Field | Type | Description |
|-------|------|-------------|
| `branch` | string | Branch name the workflow operates on (e.g., `feature/add-auth`). |
| `commit_sha_at_start` | string | Full 40-character commit SHA at workflow creation. Used for drift detection. |
| `worktree_path` | string\|null | Absolute path to a Git worktree, if the workflow uses one. `null` for normal operation. |

#### `integrity`

| Field | Type | Description |
|-------|------|-------------|
| `state_hash` | string | SHA-256 hash of the entire state file content (excluding the `integrity` block itself). Format: `sha256:<64-hex-chars>`. |
| `validated_at` | string | ISO 8601 timestamp of the last integrity validation. |

### 1.2 Phase Output Schemas

Each phase writes structured output to `phase_results.<phase>.output`. These become input context for subsequent phases.

**Phase A output:**
```json
{
  "spec_id": "add-auth-feature",
  "spec_level": 2,
  "task_list": ["TASK-001", "TASK-002"],
  "task_count": 2,
  "assigned_agents": { "TASK-001": "backend-architect" }
}
```

**Phase B output:**
```json
{
  "branch_name": "feature/add-auth",
  "test_results": { "passed": true, "total": 15, "failed": 0, "coverage": 87.5 },
  "architecture_updated": false
}
```

**Phase C output:**
```json
{
  "commit_sha": "abc1234def5678...",
  "pr_url": "https://forgejo.example.com/org/repo/pulls/123",
  "pr_number": 123,
  "merge_method": "merge"
}
```

**Phase D output:**
```json
{
  "upm_updated": true,
  "spec_archived": true,
  "progress_entry": "Phase4-Cycle9"
}
```

---

## 2. State Machine

### 2.1 Session Status Transitions

```
                ┌─────────────┐
                │  (created)  │
                └──────┬──────┘
                       │ initialize
                       ▼
              ┌─────────────────┐
         ┌───▶│  in_progress    │◀──┐
         │    └────┬───────┬────┘   │
         │         │       │        │ resume
         │  finish │       │ pause  │
         │         │       ▼        │
         │         │  ┌──────────┐  │
         │         │  │suspended │──┘
         │         │  └──────────┘
         │         │       │
         │         │       │ (unrecoverable)
         │         ▼       ▼
         │    ┌──────────────────┐
         │    │    completed     │
         │    └──────────────────┘
         │
         │    ┌──────────────────┐
         └────│     failed       │
              └──────────────────┘
              (may retry → in_progress)
```

**Valid transitions:**

| From | To | Trigger |
|------|----|---------|
| *(initial)* | `in_progress` | Workflow created and first phase begins |
| `in_progress` | `suspended` | User pauses, `auto_proceed` is `false` between phases, or session timeout |
| `in_progress` | `completed` | All phases finished successfully |
| `in_progress` | `failed` | A phase fails with `on_error: stop` |
| `suspended` | `in_progress` | User resumes workflow |
| `failed` | `in_progress` | User retries from the failed phase |

Terminal states: `completed`. The `failed` state is retryable.

### 2.2 Phase Status Transitions

```
  pending ──▶ in_progress ──▶ completed
                   │
                   ├──▶ failed
                   │
                   └──▶ skipped
```

| From | To | Trigger |
|------|----|---------|
| `pending` | `in_progress` | Phase execution begins |
| `pending` | `skipped` | Phase skip condition met (e.g., `skip_if.has_openspec`) |
| `in_progress` | `completed` | All steps within phase succeed |
| `in_progress` | `failed` | A step fails |

---

## 3. Lifecycle

### 3.1 Creation

A new state file is created when workflow-runner starts a workflow. Either from a state-scanner recommendation or a direct user invocation.

```
1. Generate session.id  → sess-YYYYMMDD-XXXXXX
2. Set session.status   → in_progress
3. Set session.started_at, session.last_active_at → now()
4. Populate workflow.*  from template or user input
5. Initialize phase_results for each phase in workflow.phases → status: pending
6. Capture git_anchor   → current branch + HEAD SHA
7. Set gates defaults   → based on workflow type
8. Compute integrity    → hash, validated_at
9. Write file atomically (see section 4)
```

### 3.2 Updates

The state file is updated at each significant transition:

| Event | Fields Updated |
|-------|---------------|
| Phase starts | `workflow.current_phase`, `phase_results.<P>.status` -> `in_progress`, `phase_results.<P>.started_at`, `session.last_active_at` |
| Step changes | `workflow.current_step`, `session.last_active_at` |
| Phase completes | `phase_results.<P>.status` -> `completed`, `phase_results.<P>.completed_at`, `phase_results.<P>.output`, `session.last_active_at` |
| Phase fails | `phase_results.<P>.status` -> `failed`, `phase_results.<P>.error`, `session.status` -> `failed`, `session.last_active_at` |
| Gate passes | `gates.<gate>` -> `true`, `session.last_active_at` |
| Workflow completes | `session.status` -> `completed`, `workflow.current_phase` -> `null`, `session.last_active_at` |
| User suspends | `session.status` -> `suspended`, `session.last_active_at` |
| User resumes | `session.status` -> `in_progress`, `session.last_active_at` |

Every update recomputes `integrity.state_hash` and `integrity.validated_at`.

### 3.3 Cleanup

When `session.status` reaches `completed`:

1. The state file remains on disk for reference until the next workflow starts.
2. On next workflow creation, the old file is overwritten atomically.
3. No manual cleanup is required since the file is gitignored (see section 7).

When `session.status` is `failed` and the user discards the workflow, the state file may be deleted manually or overwritten by the next workflow.

---

## 4. Atomic Write Protocol

All writes to `workflow-state.json` must be atomic to prevent corruption from interrupted writes (e.g., process termination, disk full).

### Protocol

```
1. Serialize state to JSON string
2. Compute integrity.state_hash over the serialized content (excluding integrity block)
3. Insert integrity block, re-serialize
4. Write to temporary file:  .aria/workflow-state.json.tmp
5. Flush / fsync the temporary file
6. Rename .aria/workflow-state.json.tmp → .aria/workflow-state.json
```

The rename operation is atomic on POSIX filesystems. On failure at any step before rename, the original state file remains intact.

### Write Pseudocode

```python
import json, hashlib, os, tempfile

def persist_state(state, state_dir=".aria"):
    target = os.path.join(state_dir, "workflow-state.json")
    tmp = target + ".tmp"

    # 1. Strip integrity for hashing
    state_copy = deep_copy(state)
    state_copy.pop("integrity", None)
    payload = json.dumps(state_copy, indent=2, ensure_ascii=False)

    # 2. Compute hash
    state["integrity"] = {
        "state_hash": "sha256:" + hashlib.sha256(payload.encode()).hexdigest(),
        "validated_at": now_iso8601()
    }

    # 3. Write temp
    final_payload = json.dumps(state, indent=2, ensure_ascii=False)
    with open(tmp, "w") as f:
        f.write(final_payload)
        f.flush()
        os.fsync(f.fileno())

    # 4. Atomic rename
    os.rename(tmp, target)
```

---

## 5. Git Consistency Validation

Before each state update and on workflow resume, validate that the Git state has not drifted unexpectedly.

### 5.1 Branch Check

```
current_branch = git rev-parse --abbrev-ref HEAD
expected_branch = git_anchor.branch

if current_branch != expected_branch:
    → WARN: "Branch mismatch. Expected '{expected}', on '{current}'."
    → Action: Suspend workflow, prompt user to switch branches or update anchor.
```

### 5.2 SHA Drift Detection

```
original_sha = git_anchor.commit_sha_at_start
current_head = git rev-parse HEAD

if session.status == "suspended" and current_head != original_sha:
    # Commits were made outside the workflow
    → WARN: "HEAD has advanced since workflow started. {n} new commits detected."
    → Action: Log warning, allow user to acknowledge and continue.
    → Update git_anchor.commit_sha_at_start if user confirms.
```

### 5.3 Worktree Validation

```
if git_anchor.worktree_path is not null:
    if not exists(git_anchor.worktree_path):
        → ERROR: "Worktree path no longer exists."
        → Action: Fail workflow, suggest re-creating worktree.
```

### 5.4 When to Validate

| Event | Branch Check | SHA Drift | Worktree |
|-------|:---:|:---:|:---:|
| Workflow creation | yes | n/a (just captured) | yes (if set) |
| Phase start | yes | yes | yes |
| Workflow resume | yes | yes | yes |
| Before merge (C.2) | yes | yes | yes |

---

## 6. Concurrent Session Detection

Only one workflow session should be active per project at a time. Detection uses `session.id` and `session.last_active_at`.

### Detection Algorithm

```
1. Before creating a new workflow, read existing .aria/workflow-state.json
2. If file exists and session.status is "in_progress" or "suspended":
   a. Check session.last_active_at
   b. If last_active_at is within STALE_THRESHOLD (default: 30 minutes):
      → CONFLICT: "Active session '{session.id}' detected (last active {age} ago)."
      → Prompt user: "Terminate existing session and start new? [y/N]"
   c. If last_active_at exceeds STALE_THRESHOLD:
      → WARN: "Stale session '{session.id}' found (inactive for {age}). Overwriting."
      → Proceed with new workflow, overwriting the stale session.
3. If session.status is "completed" or "failed":
   → Proceed, overwrite allowed.
```

### Stale Session Threshold

| Scenario | Threshold |
|----------|-----------|
| Default | 30 minutes |
| Long-running workflows (full-cycle) | 2 hours |
| Suspended (explicit) | No auto-expire; requires user action |

An explicitly `suspended` workflow never auto-expires. The user must resume or discard it.

---

## 7. `.gitignore` Requirements

The workflow state file contains session-local, machine-specific data and must never be committed.

### Required `.gitignore` Entry

```gitignore
# Aria workflow state (session-local, not committed)
.aria/workflow-state.json
.aria/workflow-state.json.tmp
```

### Enforcement

- `state-scanner` should check for this `.gitignore` entry during status collection.
- If missing, emit a warning:
  ```
  WARN: .aria/workflow-state.json is not gitignored.
  Add '.aria/workflow-state.json' to your .gitignore to prevent committing session state.
  ```
- `workflow-runner` should add the entry automatically during first workflow creation if `.aria/` directory does not yet exist (create both `.aria/` and the `.gitignore` entry).

### What IS Committed vs What is NOT

| Path | Committed | Reason |
|------|:---------:|--------|
| `.aria/workflow-state.json` | no | Session-local state |
| `.aria/workflow-state.json.tmp` | no | Temporary write artifact |
| `openspec/changes/*.md` | yes | Persistent project artifacts |
| `docs/architecture/*.md` | yes | Persistent project artifacts |

---

## 8. Error Recovery

### 8.1 Corrupt or Unparseable File

```
On read of .aria/workflow-state.json:
  1. Attempt JSON.parse()
  2. If parse fails:
     → LOG WARN: "workflow-state.json is corrupt. Treating as absent."
     → Rename corrupt file to .aria/workflow-state.json.corrupt.<timestamp>
     → Proceed as if no state file exists.
```

### 8.2 Integrity Hash Mismatch

```
On read:
  1. Parse JSON successfully
  2. Extract and remove integrity block
  3. Re-hash remaining content
  4. Compare with integrity.state_hash

  If mismatch:
     → LOG WARN: "State file integrity check failed. File may have been manually edited."
     → Prompt user: "State file may be tampered. Trust current content? [y/N]"
     → If yes: recompute hash, continue.
     → If no: treat as absent, rename to .corrupt.<timestamp>
```

### 8.3 Missing Fields (Schema Migration)

```
On read:
  1. Parse JSON
  2. Check format_version
  3. If format_version < current:
     → Apply migration: fill missing fields with defaults
     → LOG INFO: "Migrated state file from v{old} to v{new}."
  4. If format_version > current:
     → LOG ERROR: "State file from newer version. Cannot process."
     → Treat as absent.
```

Default values for missing fields:

| Field | Default | Added in |
|-------|---------|----------|
| `gates.gate1_spec_approved` | `false` | v1.0 |
| `gates.gate2_merge_main` | `false` | v1.0 |
| `workflow.auto_proceed` | `true` | v1.0 |
| `workflow.spec_id` | `null` | v1.0 |
| `workflow.current_step` | `null` | v1.0 |
| `git_anchor.worktree_path` | `null` | v1.0 |
| `phase_results.<P>.error` | `null` | v1.0 |
| `gate_state` | `null` | v1.1 |

**Migration table — supported version transitions**:

| From | To | Action | Notes |
|------|-----|--------|-------|
| `1.0` | `1.1` | Add `gate_state: null` (additive only) | No data loss; consumers must use defensive `.get()` access. Migrating a `waiting`-state file is impossible from v1.0 (the concept didn't exist), so v1.0 → v1.1 always defaults to `null`. |
| `1.1` | `1.0` | Not supported (downgrade) | Treat as absent + warn user. |

### 8.4 Phase Failure Recovery

When a phase fails and the user wants to retry:

```
1. Verify git_anchor consistency (section 5)
2. Reset failed phase: phase_results.<P>.status → pending, clear error
3. Set session.status → in_progress
4. Set workflow.current_phase → the failed phase letter
5. Persist state
6. Re-execute from the failed phase
```

Previous phase outputs remain intact in `phase_results` and are available as context.

### 8.5 Process Crash Recovery

If the process terminates unexpectedly:

```
On next invocation:
  1. Read .aria/workflow-state.json
  2. If session.status == "in_progress":
     → The last write succeeded (atomic rename guarantees this)
     → Check workflow.current_phase and phase_results
     → Resume from the last known position
  3. If .tmp file exists but .json is stale:
     → The write was interrupted before rename
     → Discard .tmp, use existing .json
     → LOG WARN: "Incomplete write detected. Resuming from last persisted state."
```

---

## Appendix A: Full Example

A `feature-dev` workflow midway through Phase B:

```json
{
  "$schema": "aria-workflow-state/v1",
  "format_version": "1.1",

  "session": {
    "id": "sess-20260316-a3f7c1",
    "started_at": "2026-03-16T10:00:00+08:00",
    "last_active_at": "2026-03-16T10:12:45+08:00",
    "status": "in_progress"
  },

  "workflow": {
    "name": "feature-dev",
    "phases": ["A", "B", "C"],
    "current_phase": "B",
    "current_step": "B.2",
    "auto_proceed": true,
    "spec_id": "workflow-automation-enhancement"
  },

  "gates": {
    "gate1_spec_approved": true,
    "gate2_merge_main": false
  },

  "gate_state": null,

  "phase_results": {
    "A": {
      "status": "completed",
      "started_at": "2026-03-16T10:00:05+08:00",
      "completed_at": "2026-03-16T10:05:30+08:00",
      "output": {
        "spec_id": "workflow-automation-enhancement",
        "spec_level": 3,
        "task_list": ["TASK-001", "TASK-002", "TASK-003"],
        "task_count": 3,
        "assigned_agents": {
          "TASK-001": "backend-architect",
          "TASK-002": "backend-architect",
          "TASK-003": "knowledge-manager"
        }
      },
      "error": null
    },
    "B": {
      "status": "in_progress",
      "started_at": "2026-03-16T10:05:35+08:00",
      "completed_at": null,
      "output": {
        "branch_name": "feature/workflow-automation"
      },
      "error": null
    },
    "C": {
      "status": "pending",
      "started_at": null,
      "completed_at": null,
      "output": {},
      "error": null
    }
  },

  "git_anchor": {
    "branch": "feature/workflow-automation",
    "commit_sha_at_start": "481539d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7",
    "worktree_path": null
  },

  "integrity": {
    "state_hash": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "validated_at": "2026-03-16T10:12:45+08:00"
  }
}
```

---

## Appendix B: Quick Reference

### File Location

```
<project-root>/
  .aria/
    workflow-state.json       ← state file
    workflow-state.json.tmp   ← transient write artifact
```

### Session ID Format

```
sess-YYYYMMDD-XXXXXX

YYYYMMDD = date of creation
XXXXXX   = 6 random lowercase hex characters
Example  = sess-20260316-a3f7c1
```

### Hash Computation

```
1. Serialize full state as JSON (indent=2)
2. Remove the "integrity" key from the object
3. Re-serialize the remaining object (indent=2, ensure_ascii=false)
4. SHA-256 hash the UTF-8 encoded bytes
5. Prefix with "sha256:"
```

---

**Created**: 2026-03-16
**Version**: 1.0
**Referenced by**: [workflow-runner SKILL.md](../SKILL.md), [state-scanner SKILL.md](../../state-scanner/SKILL.md)

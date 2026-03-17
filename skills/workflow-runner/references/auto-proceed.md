# Auto-Proceed Mode Specification

> **Version**: 1.0 | **Feature**: Workflow Automation
> **Consumers**: workflow-runner
> **Related**: [workflow-state-schema.md](./workflow-state-schema.md), [WORKFLOWS.md](../WORKFLOWS.md)

---

## 1. Overview

Auto-Proceed Mode allows workflow-runner to automatically advance through Phases without pausing for user confirmation between each Phase. When disabled (the default), workflow-runner pauses after every Phase and waits for the user to confirm before continuing.

When enabled, Phase transitions happen automatically **except** at Gate pauses, where human review is required.

### Design Principles

- **Backward compatible**: `auto_proceed` defaults to `false`; existing behavior is unchanged
- **Gate integrity preserved**: Gates always require explicit checks; auto-proceed never bypasses a Gate
- **Observable**: Each transition is logged in workflow state; the user can inspect progress at any time

---

## 2. Configuration

### 2.1 Per-Workflow Input

The `auto_proceed` flag can be set in the workflow input:

```yaml
workflow: feature-dev
auto_proceed: true        # Enable auto-proceed for this run

config:
  context:
    module: "auth"
```

### 2.2 Project-Level Default

If `.aria/config.json` exists in the project root, workflow-runner reads the default from it:

```json
{
  "workflow_runner": {
    "auto_proceed": true
  }
}
```

### 2.3 Precedence

```
1. Explicit workflow input (highest priority)
2. .aria/config.json project default
3. Built-in default: false (lowest priority)
```

Resolution logic:

```yaml
resolve_auto_proceed:
  if workflow_input.auto_proceed is defined:
    use workflow_input.auto_proceed
  elif .aria/config.json exists AND has workflow_runner.auto_proceed:
    use .aria/config.json value
  else:
    use false
```

### 2.4 State File Recording

The resolved value is written to `workflow.auto_proceed` in `.aria/workflow-state.json` at workflow creation. This value is immutable for the duration of the session. See [workflow-state-schema.md](./workflow-state-schema.md) for the full schema.

---

## 3. Phase Transition Logic (Task 2.2)

### 3.1 Transition Table

| Transition | Gate | Auto-Proceed Behavior |
|------------|------|-----------------------|
| A → B | Gate 1 (Spec Approval) | **STOP.** Read `proposal.md` Status field. Only proceed if `Status: Approved`. |
| B → C | None | **Auto-proceed.** Trigger: phase-b-developer output `test_passed: true` AND no uncommitted non-test changes (see Section 4). |
| C → D | Gate 2 (conditional) | If merge target is `main` or `master`: **STOP** for interactive confirmation. Otherwise: **auto-proceed.** |
| D → done | None | **Auto-proceed** to cleanup (delete workflow-state.json). |

### 3.2 Transition Flow

```
Phase A completes
    │
    ├─ auto_proceed = false? → PAUSE, wait for user
    │
    └─ auto_proceed = true?
         │
         ├─ Gate 1 check: read proposal.md Status
         │    │
         │    ├─ Status = Approved → set gates.gate1_spec_approved = true → START Phase B
         │    │
         │    └─ Status ≠ Approved → STOP
         │         → Message: "Gate 1: proposal.md Status is not 'Approved'.
         │            Approve the spec before proceeding."
         │         → Set session.status = suspended
         │
         ▼
Phase B completes
    │
    ├─ auto_proceed = false? → PAUSE, wait for user
    │
    └─ auto_proceed = true?
         │
         └─ Completion signal check (Section 4)
              │
              ├─ Signal valid → START Phase C
              │
              └─ Signal invalid → STOP
                   → Message: "Phase B output does not meet completion criteria.
                      Check test results and uncommitted changes."
                   → Set session.status = suspended

Phase C completes
    │
    ├─ auto_proceed = false? → PAUSE, wait for user
    │
    └─ auto_proceed = true?
         │
         ├─ Workflow includes Phase D?
         │    │
         │    ├─ Gate 2 check: is merge target main/master?
         │    │    │
         │    │    ├─ Target = main/master → STOP
         │    │    │    → Message: "Gate 2: Merging to main requires confirmation."
         │    │    │    → Set session.status = suspended
         │    │    │
         │    │    └─ Target ≠ main/master → START Phase D
         │    │
         │    └─ (Gate 2 not applicable for non-merge workflows)
         │         → START Phase D
         │
         └─ No Phase D in workflow → cleanup, DONE

Phase D completes
    │
    └─ Cleanup: delete .aria/workflow-state.json → DONE
```

### 3.3 Gate Details

#### Gate 1: Spec Approval (A → B)

**Purpose**: Ensure human has reviewed and approved the OpenSpec proposal before development begins.

**Check procedure**:

```yaml
gate1_check:
  1. Locate proposal.md:
     - From phase_results.A.output.spec_id → openspec/changes/{spec_id}/proposal.md
     - Or from workflow context.spec_id
  2. Read the Status field in the YAML frontmatter or metadata section
  3. If Status contains "Approved" (case-insensitive):
     - Set gates.gate1_spec_approved = true
     - Proceed to Phase B
  4. If Status is anything else (Draft, In Review, Rejected, etc.):
     - STOP. Report current status to user
     - Set session.status = suspended
```

**Workflows that skip Phase A** (e.g., `quick-fix`, `commit-only`): Gate 1 is initialized to `true` since no spec is involved.

#### Gate 2: Main Branch Merge (C → D)

**Purpose**: Prevent unreviewed merges to the main branch.

**Check procedure**:

```yaml
gate2_check:
  1. Determine merge target:
     - From phase_results.C.output.merge_target
     - Or from git_anchor.branch (if merging current branch)
     - Or from workflow config.target_branch
  2. If target is "main" or "master":
     - STOP. Require explicit user confirmation
     - Message: "About to merge to {target}. Confirm to proceed."
     - Set session.status = suspended
     - On user confirmation: set gates.gate2_merge_main = true, proceed
  3. If target is any other branch:
     - Auto-proceed to Phase D
```

**Workflows without merge step** (e.g., `doc-update`): Gate 2 does not apply; auto-proceed to Phase D.

---

## 4. Completion Signal Definition (Task 2.3)

### 4.1 What "Development Complete" Means

"开发完成" (development complete) is determined by two conditions that must BOTH be true:

```yaml
completion_signal:
  condition_1:
    name: "Tests pass"
    check: phase_results.B.output.test_results.passed == true
    source: phase-b-developer output

  condition_2:
    name: "Clean working tree (excluding tests)"
    check: git status shows no uncommitted changes outside test directories
    source: git status at Phase B completion
```

### 4.2 Detection from Phase Results

workflow-runner reads the completion signal from the Phase B output stored in the workflow state:

```yaml
detect_completion:
  # Step 1: Check test results from phase-b-developer output
  phase_b_output = phase_results.B.output

  test_passed = phase_b_output.test_results.passed
  # Must be exactly `true`

  # Step 2: Check for uncommitted changes
  # phase-b-developer should report this in its output:
  uncommitted_changes = phase_b_output.uncommitted_non_test_changes
  # Expected: false (no uncommitted non-test changes)

  # Step 3: Evaluate
  if test_passed == true AND uncommitted_changes == false:
    → completion_signal = VALID → auto-proceed to Phase C
  else:
    → completion_signal = INVALID → STOP, report to user
```

### 4.3 What Counts as "Test Directories"

Files in the following paths are considered test artifacts and are excluded from the "clean working tree" check:

```yaml
test_directory_patterns:
  - "**/test/**"
  - "**/tests/**"
  - "**/__tests__/**"
  - "**/*.test.*"
  - "**/*.spec.*"
  - "**/test_*"
  - "**/*_test.*"
```

These patterns are conventionally recognized. Projects may override them via `.aria/config.json`:

```json
{
  "workflow_runner": {
    "test_patterns": ["src/test/**", "spec/**"]
  }
}
```

### 4.4 Fallback: Manual Signal

If phase-b-developer output does not contain `uncommitted_non_test_changes` (older versions), workflow-runner falls back to:

```yaml
fallback_check:
  1. Read phase_results.B.output.test_results.passed
  2. If passed == true:
     - Run `git status --porcelain` conceptually (via phase output or direct check)
     - Filter out files matching test_directory_patterns
     - If remaining list is empty → completion_signal = VALID
     - If remaining list is non-empty → completion_signal = INVALID
  3. If passed != true:
     - completion_signal = INVALID regardless
```

---

## 5. Behavior by Workflow Preset

Each preset workflow behaves differently with `auto_proceed: true`:

| Workflow | Gates Active | Auto-Proceed Behavior |
|----------|-------------|----------------------|
| `quick-fix` | None | Fully automatic. No Phase A, Gate 1 N/A. Typically B → C, no merge to main. |
| `feature-dev` | Gate 1 | Pauses at Gate 1 (A → B) for spec approval. B → C and completion are automatic. |
| `full-cycle` | Gate 1, Gate 2 | Pauses at Gate 1 (A → B) and Gate 2 (C → D, if target=main). |
| `commit-only` | None | Fully automatic. Single step, no transitions to gate. |
| `doc-update` | None | Fully automatic. No spec, no merge to main. |

### Workflow-Specific Notes

**quick-fix**: Skips Phase A entirely, so Gate 1 is pre-approved (`gate1_spec_approved: true`). The typical path is B → C with direct push (no PR to main), so Gate 2 does not trigger. Result: uninterrupted execution.

**feature-dev**: Includes Phase A, so Gate 1 is active. The user must approve the proposal before development proceeds. After Phase B, the completion signal (Section 4) determines whether to auto-proceed to Phase C. Phase D is not included in this workflow.

**full-cycle**: Both gates are active. Gate 1 requires spec approval after Phase A. Gate 2 triggers if Phase C merges to main/master, requiring explicit confirmation. This is the most conservative preset.

**commit-only**: Executes only C.1 (commit). No Phase transitions to gate. Completes immediately.

**doc-update**: Executes B.3 → C.1. No spec required (Gate 1 N/A), no merge to main (Gate 2 N/A). Completes without pauses.

---

## 6. State File Integration

### 6.1 Fields Used

Auto-proceed mode uses the following fields in `workflow-state.json`:

```yaml
workflow.auto_proceed: true|false    # Resolved at creation, immutable
gates.gate1_spec_approved: boolean   # Set when Gate 1 passes
gates.gate2_merge_main: boolean      # Set when Gate 2 passes
session.status: "suspended"          # Set when auto-proceed stops at a gate
```

### 6.2 Suspended → Resumed

When auto-proceed stops at a gate and sets `session.status: suspended`:

```yaml
resume_from_gate:
  1. User provides confirmation (approves spec, confirms merge)
  2. Set the corresponding gate to true
  3. Set session.status = in_progress
  4. Continue to the next Phase
```

### 6.3 Example: feature-dev with auto_proceed=true

```
1. Workflow starts: auto_proceed=true, session.status=in_progress
2. Phase A executes → completes
3. Gate 1 check: reads proposal.md
   - If Approved: gate1_spec_approved=true → Phase B starts automatically
   - If not: session.status=suspended → wait for user
4. Phase B executes → completes
5. Completion signal check: test_passed=true, no uncommitted changes
   → Phase C starts automatically
6. Phase C executes → completes
7. No Phase D in feature-dev → cleanup → DONE
```

---

## 7. Error Handling

### 7.1 Gate Check Failures

If a gate check itself fails (e.g., proposal.md not found):

```yaml
gate_check_error:
  action: suspend
  message: "Gate check failed: {error_detail}. Cannot auto-proceed."
  recovery: "Ensure the required artifact exists and retry."
```

### 7.2 Completion Signal Ambiguity

If phase-b-developer output is missing expected fields:

```yaml
missing_signal:
  action: suspend
  message: "Cannot determine completion signal. Phase B output missing test_results."
  recovery: "Check phase-b-developer output format. Manual proceed available."
```

### 7.3 Manual Override

At any suspension point, the user can:

1. **Proceed**: Force continue past the gate (`workflow-runner --resume`)
2. **Abort**: Cancel the workflow entirely
3. **Fix and retry**: Address the gate condition, then resume

---

## 8. Gate Enforcement, Manual Fallback & Failure Recovery

Gate enforcement details, manual/auto mode switching, and failure recovery flows are defined in a dedicated reference:

**→ [gate-enforcement.md](./gate-enforcement.md)**

Key points:
- Gate 2 (Merge to main) has absolute priority — never auto-bypasses
- Priority order: Gate 2 > Gate 1 > Failure Recovery > Manual Mode > Auto-Proceed
- Failure during auto-proceed triggers automatic fallback to manual mode

---

**Created**: 2026-03-16
**Version**: 1.0
**Referenced by**: [workflow-runner SKILL.md](../SKILL.md), [WORKFLOWS.md](../WORKFLOWS.md)

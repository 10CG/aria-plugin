#!/usr/bin/env bash
# Aria PreToolUse Hook: handoff-location-guard
#
# H0 (aria-ten-step-session-handoff-stage) Layer 1 of 5-layer defense-in-depth.
# Blocks Write / Edit / NotebookEdit attempts targeting .aria/handoff/*.md.
# Canonical handoff dir is docs/handoff/ (see standards/conventions/session-handoff.md).
#
# Input (stdin): Claude Code PreToolUse event JSON:
#   {
#     "tool_name": "Write" | "Edit" | "NotebookEdit" | ...,
#     "tool_input": { "file_path": "...", ... }
#   }
#
# Behavior:
#   - Pass-through (exit 0, no output) if tool is not a mutator OR path is not
#     in .aria/handoff/.
#   - Deny via JSON stdout payload (preferred per Claude Code hook spec):
#       exit 0 + stdout: {"decision": "block", "reason": "<message>"}
#   - Legacy deny via exit 2 + stderr if ARIA_HOOK_DENY_MODE=exit2.
#
# ─── TASK-009 (a): COMPATIBILITY AUDIT — NO LOGIC CHANGE NEEDED ───────────────
#
# Context: OpenSpec `multi-terminal-coordination` (v1.22.x+) extends Rule #9
# by adding machine-readable YAML frontmatter to handoff docs (§2.3 schema:
# track-id / owner-container / phase / status / updated-at). This hook guards
# the *location* of the write; it does NOT inspect file content or frontmatter.
#
# Decision: THIS HOOK REQUIRES NO MODIFICATION for multi-terminal-coordination.
#
# Rationale:
#   1. The guard condition is path-based only: it checks whether the resolved
#      file path matches `(?:^|[/\\])\.aria[/\\]handoff[/\\][^/\\]+\.md$`.
#   2. The new frontmatter schema lives inside docs/handoff/*.md (canonical),
#      not inside .aria/handoff/ (forbidden). The hook allows writes to
#      docs/handoff/ by design (pass-through for any non-forbidden path).
#   3. Frontmatter content parsing is the responsibility of the Layer 2
#      collector (collectors/handoff.py), not this hook.
#   4. Fail-open design (broken hook → exit 0) remains correct: a hook crash
#      must never block a legitimate write to docs/handoff/ with frontmatter.
#   5. The L5 template (aria/templates/session-handoff.md) now emits the
#      frontmatter block, so the write path is always docs/handoff/ — which
#      this hook already allows.
#
# Cross-references:
#   - Rule #9: standards/conventions/session-handoff.md §3 (enforcement matrix)
#   - L2 collector: aria/skills/state-scanner/scripts/collectors/handoff.py
#   - 5-layer matrix doc: aria/skills/state-scanner/docs/rule9-5layer-matrix.md
#   - Task coverage: TASK-009 (a) in openspec/changes/multi-terminal-coordination/tasks.md §1.9
# ─────────────────────────────────────────────────────────────────────────────

# NOTE (H1 follow-up, PR #46 audit Important-1): `set -e` here is NOT the
# safety mechanism. The DECISION=$(...) command substitution masks the
# python exit code per POSIX, so a python crash inside the heredoc does NOT
# abort this script. The intended safe behavior is the explicit fallthrough:
# empty/non-"DENY" $DECISION → `exit 0` (PASS, never block on hook failure).
# `set -e` only guards the trivial top-level statements; do not rely on it
# for the decision path. Fail-open is deliberate (a broken hook must never
# block legitimate writes).
set -e

DENY_MODE="${ARIA_HOOK_DENY_MODE:-json}"

EVENT_JSON="$(cat || true)"

if [ -z "$EVENT_JSON" ]; then
  exit 0
fi

# Pass event JSON via env var (heredoc + stdin pipe conflict — python3 with
# `-` reads heredoc as source; stdin pipe would be eaten by source consumption).
export ARIA_HOOK_EVENT="$EVENT_JSON"
DECISION=$(python3 <<'PY'
import json
import os
import re
import sys
from pathlib import Path

event_str = os.environ.get("ARIA_HOOK_EVENT", "")
try:
    event = json.loads(event_str) if event_str else {}
except json.JSONDecodeError:
    print("PASS")
    sys.exit(0)

tool_name = event.get("tool_name", "")
tool_input = event.get("tool_input") or {}
file_path = (
    tool_input.get("file_path")
    or tool_input.get("path")
    or tool_input.get("notebook_path")
    or ""
)

MUTATING_TOOLS = {"Write", "Edit", "NotebookEdit"}
if tool_name not in MUTATING_TOOLS:
    print("PASS")
    sys.exit(0)

if not file_path:
    print("PASS")
    sys.exit(0)

# Resolve to absolute path; follow symlinks to defeat circumvention.
try:
    resolved = Path(file_path).expanduser().resolve(strict=False)
except (OSError, RuntimeError):
    print("PASS")
    sys.exit(0)

# Forbidden pattern: path ending with `.aria/handoff/<file>.md`.
# Use [/\\] char class to match both POSIX `/` and Windows `\` separators
# (G2 audit fix per R2 backend-M2).
FORBIDDEN_RE = re.compile(
    r"(?:^|[/\\])\.aria[/\\]handoff[/\\][^/\\]+\.md$",
    re.IGNORECASE,
)

if FORBIDDEN_RE.search(str(resolved)):
    print("DENY")
else:
    print("PASS")
PY
)

if [ "$DECISION" != "DENY" ]; then
  exit 0
fi

# DENY path
MESSAGE=$(cat <<'EOM'
❌ Handoff docs must be written to docs/handoff/ (canonical location).

.aria/handoff/ is forbidden — see standards/conventions/session-handoff.md.

Reason: docs/ holds human-readable prose; .aria/ is for machine state only.

Action: rewrite path to docs/handoff/<filename>.

(Aria H0 spec, aria-plugin v1.21.0+ — Layer 1 of 5-layer enforcement.)
EOM
)

if [ "$DENY_MODE" = "exit2" ]; then
  echo "$MESSAGE" >&2
  exit 2
fi

# JSON deny payload (preferred)
printf '%s' "$MESSAGE" | python3 -c '
import json, sys
msg = sys.stdin.read()
print(json.dumps({"decision": "block", "reason": msg}))
'
exit 0

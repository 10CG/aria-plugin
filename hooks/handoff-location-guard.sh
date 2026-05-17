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

#!/usr/bin/env bash
# Smoke test for aria/hooks/handoff-location-guard.sh
#
# F7 audit fix per R1 qa-M1: PreToolUse hook smoke test via shell subprocess +
# synthetic event JSON, NOT Python unittest (PreToolUse hooks fire at Claude
# Code runtime; unittest cannot trigger the runtime hook event).
#
# Test cases:
#   1. Write to .aria/handoff/*.md → DENY (JSON payload to stdout)
#   2. Edit to .aria/handoff/*.md → DENY
#   3. Write to docs/handoff/*.md → PASS (no output)
#   4. Read tool → PASS (non-mutator)
#   5. Write to .aria/cache/foo.md → PASS (different .aria subdir)
#   6. Absolute path .aria/handoff/x.md → DENY (resolve absolute)
#   7. Empty/missing event JSON → PASS (defensive)
#   8. ARIA_HOOK_DENY_MODE=exit2 → exit code 2 + stderr message
#
# Usage:
#   bash aria/skills/state-scanner/tests/test_handoff_hook.sh

set -u  # treat unset vars as errors; do NOT set -e (we test exit codes)

HOOK="$(dirname "$0")/../../../hooks/handoff-location-guard.sh"
if [ ! -x "$HOOK" ]; then
  echo "FAIL: hook script not executable at $HOOK" >&2
  exit 1
fi

PASS_COUNT=0
FAIL_COUNT=0

run_case() {
  local name="$1"; local event="$2"; local expected_decision="$3"
  # expected_decision: "DENY_JSON" / "PASS_SILENT" / "DENY_EXIT2"
  local deny_mode="${4:-json}"

  output=$(printf '%s' "$event" | ARIA_HOOK_DENY_MODE="$deny_mode" bash "$HOOK" 2>&1)
  rc=$?

  case "$expected_decision" in
    DENY_JSON)
      if [ "$rc" -eq 0 ] && echo "$output" | grep -q '"decision": "block"'; then
        echo "✅ $name"
        PASS_COUNT=$((PASS_COUNT + 1))
      else
        echo "❌ $name — expected DENY_JSON, got rc=$rc, output: $output"
        FAIL_COUNT=$((FAIL_COUNT + 1))
      fi
      ;;
    PASS_SILENT)
      if [ "$rc" -eq 0 ] && [ -z "$output" ]; then
        echo "✅ $name"
        PASS_COUNT=$((PASS_COUNT + 1))
      else
        echo "❌ $name — expected PASS_SILENT, got rc=$rc, output: $output"
        FAIL_COUNT=$((FAIL_COUNT + 1))
      fi
      ;;
    DENY_EXIT2)
      if [ "$rc" -eq 2 ] && echo "$output" | grep -q "must be written to docs/handoff"; then
        echo "✅ $name"
        PASS_COUNT=$((PASS_COUNT + 1))
      else
        echo "❌ $name — expected DENY_EXIT2, got rc=$rc, output: $output"
        FAIL_COUNT=$((FAIL_COUNT + 1))
      fi
      ;;
    *)
      echo "❌ $name — bad expected_decision $expected_decision"
      FAIL_COUNT=$((FAIL_COUNT + 1))
      ;;
  esac
}

# ─── Test cases ────────────────────────────────────────────────────────────

run_case "1. Write to .aria/handoff/foo.md → DENY_JSON" \
  '{"tool_name": "Write", "tool_input": {"file_path": ".aria/handoff/foo.md"}}' \
  DENY_JSON

run_case "2. Edit to .aria/handoff/foo.md → DENY_JSON" \
  '{"tool_name": "Edit", "tool_input": {"file_path": ".aria/handoff/foo.md"}}' \
  DENY_JSON

run_case "3. Write to docs/handoff/foo.md → PASS_SILENT" \
  '{"tool_name": "Write", "tool_input": {"file_path": "docs/handoff/foo.md"}}' \
  PASS_SILENT

run_case "4. Read tool (non-mutator) → PASS_SILENT" \
  '{"tool_name": "Read", "tool_input": {"file_path": ".aria/handoff/foo.md"}}' \
  PASS_SILENT

run_case "5. Write to .aria/cache/foo.md (different .aria subdir) → PASS_SILENT" \
  '{"tool_name": "Write", "tool_input": {"file_path": ".aria/cache/foo.md"}}' \
  PASS_SILENT

run_case "6. Absolute path /tmp/.aria/handoff/x.md → DENY_JSON" \
  '{"tool_name": "Write", "tool_input": {"file_path": "/tmp/.aria/handoff/x.md"}}' \
  DENY_JSON

run_case "7. Empty event JSON → PASS_SILENT (defensive)" \
  '' \
  PASS_SILENT

run_case "8. exit2 mode for .aria/handoff/foo.md → DENY_EXIT2" \
  '{"tool_name": "Write", "tool_input": {"file_path": ".aria/handoff/foo.md"}}' \
  DENY_EXIT2 \
  exit2

# Edge: NotebookEdit tool with notebook_path
run_case "9. NotebookEdit .aria/handoff/foo.md → DENY_JSON" \
  '{"tool_name": "NotebookEdit", "tool_input": {"notebook_path": ".aria/handoff/foo.md"}}' \
  DENY_JSON

# Edge: Non-md file in .aria/handoff/ (e.g. .aria/handoff/README.json) should pass
run_case "10. Write to .aria/handoff/README.json (non-md) → PASS_SILENT" \
  '{"tool_name": "Write", "tool_input": {"file_path": ".aria/handoff/README.json"}}' \
  PASS_SILENT

# ─── Summary ───────────────────────────────────────────────────────────────

echo ""
echo "─── Summary ───"
echo "PASS: $PASS_COUNT"
echo "FAIL: $FAIL_COUNT"

if [ "$FAIL_COUNT" -gt 0 ]; then
  exit 1
fi
exit 0

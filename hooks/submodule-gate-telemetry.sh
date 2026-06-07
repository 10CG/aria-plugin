#!/usr/bin/env bash
# PostToolUse Bash hook — R-fix-1 (Spec aria-submodule-gate-operationalize, TG-1).
#
# === Why ===
# The submodule pointer regression gate (submodule_gate.sh, §C.2.4.5) only runs
# inside the full phase-c-integrator merge flow. Aria's actual ships go git-direct
# (`git add <submodule> && git commit && git push`), bypassing that flow → the gate
# recorded 0 executions over a 14-day window (block-flip D+14 Trigger C). This hook
# closes that invocation gap WITHOUT rerouting git-direct ship through
# phase-c-integrator (per agent-team over-engineering guard).
#
# === What ===
# On a `git commit` whose resulting HEAD touches a submodule gitlink (mode 160000),
# run submodule_gate.sh in WARN mode (locally, where origin IS reachable — unlike the
# CI runner, which is R-fix-2). The gate records a per-invocation execution line in
# submodule-gate-executions.jsonl (+ any warn telemetry), so total_gate_executions
# accumulates for the deferred block-flip minimum-observation guard.
#
# === Safety ===
# - PostToolUse → CANNOT block tool execution; always exit 0. Zero lockout risk
#   (contrast PreToolUse exit-2 self-lockout hazard).
# - Forces WARN mode: this hook is telemetry-only; enforcement (block) remains the
#   deferred block-flip Spec's job via the phase-c-integrator merge flow.
# - No-op on: non-commit commands, repos without .gitmodules, commits not touching a
#   gitlink (avoids telemetry noise, per tasks 1.4).
#
# === Hook contract ===
# Input (stdin JSON): { "tool_name": "Bash", "tool_input": {"command": "..."}, "cwd": "..." }
# Output: best-effort; one stderr line on record; never mutates, never blocks.

set -uo pipefail

input=$(cat 2>/dev/null || true)
[[ -z "$input" ]] && exit 0

# jq output piped through `tr -d '\r'` per shell-jq-crlf-hygiene (Windows native jq).
command=$(printf '%s' "$input" | jq -r '.tool_input.command // ""' 2>/dev/null | tr -d '\r')
cwd=$(printf '%s' "$input" | jq -r '.cwd // ""' 2>/dev/null | tr -d '\r')

# Only act on git commit invocations (the moment a gitlink bump is introduced,
# local HEAD ahead of origin/master → gate sees a meaningful transition).
[[ "$command" == *"git commit"* ]] || exit 0

# Resolve superproject root.
cd "${cwd:-$PWD}" 2>/dev/null || exit 0
root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
cd "$root" 2>/dev/null || exit 0

# Superproject only.
[[ -f .gitmodules ]] || exit 0

# Did the just-created HEAD commit touch a gitlink (mode 160000)? If not, no-op
# (most commits don't bump submodule pointers — avoids telemetry noise).
# Anchor on the raw mode columns ($1=":<srcmode>", $2="<dstmode>") so a path or
# blob SHA merely *containing* "160000" can't false-trigger (code-reviewer Minor #1).
git diff-tree --no-commit-id --raw -r HEAD 2>/dev/null \
    | awk '$1 == ":160000" || $2 == "160000" { f=1 } END { exit !f }' || exit 0

# Locate the gate script (hook lives in <plugin>/hooks/; gate in <plugin>/skills/...).
gate="${CLAUDE_PLUGIN_ROOT:-}/skills/phase-c-integrator/scripts/submodule_gate.sh"
if [[ ! -f "$gate" ]]; then
    gate="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd)/skills/phase-c-integrator/scripts/submodule_gate.sh"
fi
[[ -f "$gate" ]] || exit 0

# Run in WARN mode (telemetry only; never block). Gate records the execution.
# `timeout 15` leaves buffer under the 20s hook timeout (gate fetches origin per
# submodule; slow/blocked network → clean give-up, execution simply not recorded,
# best-effort per §What). Falls back to bare invocation if `timeout` is absent.
if command -v timeout >/dev/null 2>&1; then
    ARIA_SUBMODULE_GATE_MODE=warn timeout 15 bash "$gate" >/dev/null 2>&1 || true
else
    ARIA_SUBMODULE_GATE_MODE=warn bash "$gate" >/dev/null 2>&1 || true
fi
echo "[submodule-gate-telemetry] recorded gate execution (gitlink-touching commit)" >&2
exit 0

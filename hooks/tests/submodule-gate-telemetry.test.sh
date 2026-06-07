#!/usr/bin/env bash
# Tests for R-fix-1 (Spec aria-submodule-gate-operationalize TG-1):
#   (A) submodule_gate.sh writes a per-invocation execution record (incl. PASS)
#       → submodule-gate-executions.jsonl (total_gate_executions direct counter)
#   (B) submodule-gate-telemetry.sh PostToolUse hook triggers the gate ONLY on a
#       git-commit that touches a submodule gitlink; no-op otherwise.
#
# Real git fixtures (bare submodule + parent w/ origin + feature gitlink bump) —
# mocking git would validate the mock, not the behavior (same rationale as
# test_submodule_gate.sh).

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
GATE="$PLUGIN_ROOT/skills/phase-c-integrator/scripts/submodule_gate.sh"
HOOK="$PLUGIN_ROOT/hooks/submodule-gate-telemetry.sh"

PASS=0; FAIL=0
declare -a FAILS=()
report_pass() { PASS=$((PASS+1)); echo "  ✓ PASS: $1"; }
report_fail() { FAIL=$((FAIL+1)); FAILS+=("$1"); echo "  ✗ FAIL: $1" >&2; }

FIXTURE=""
cleanup() { [[ -n "$FIXTURE" && -d "$FIXTURE" ]] && rm -rf "$FIXTURE"; }
trap cleanup EXIT

# ─── fixture helpers (adapted from test_submodule_gate.sh) ───
PARENT_REPO=""
build_fixture() {
    # Builds: bare submodule (2 commits) + parent repo (origin master @ sub commit 1)
    #         + feature branch bumping gitlink to sub commit 2 (forward).
    # Sets global PARENT_REPO (NOT echo — git commands emit stdout that would
    # pollute a $(build_fixture) capture). Leaves parent on `feature` (HEAD
    # touches gitlink vs origin/master).
    FIXTURE=$(mktemp -d -t aria-gatetel-XXXXXX)
    local bare="$FIXTURE/sub.git" work="$FIXTURE/sub.work"
    git init -q --bare "$bare"
    git init -q "$work"
    git -C "$work" config user.email t@t; git -C "$work" config user.name t
    git -C "$work" config commit.gpgsign false
    echo c1 > "$work/f.txt"; git -C "$work" add .; git -C "$work" commit -q -m c1
    local sha1; sha1=$(git -C "$work" rev-parse HEAD)
    echo c2 > "$work/f.txt"; git -C "$work" add .; git -C "$work" commit -q -m c2
    local sha2; sha2=$(git -C "$work" rev-parse HEAD)
    git -C "$work" push -q "$bare" master 2>/dev/null || git -C "$work" push -q "$bare" HEAD:master

    local parent="$FIXTURE/parent"
    git init -q "$parent"
    git -C "$parent" config user.email t@t; git -C "$parent" config user.name t
    git -C "$parent" config commit.gpgsign false
    git -C "$parent" config protocol.file.allow always
    echo p > "$parent/README.md"; git -C "$parent" add README.md; git -C "$parent" commit -q -m init
    git -C "$parent" -c protocol.file.allow=always submodule add -q "$bare" submod
    git -C "$parent" -C submod checkout -q "$sha1" 2>/dev/null || git -C "$parent/submod" checkout -q "$sha1"
    git -C "$parent" add submod; git -C "$parent" commit -q -m "sub@c1"
    local pbare="$FIXTURE/parent.git"
    git init -q --bare "$pbare"
    git -C "$parent" remote add origin "$pbare"
    git -C "$parent" push -q origin master
    # feature branch: forward-bump gitlink to sha2
    git -C "$parent" checkout -q -b feature
    git -C "$parent/submod" checkout -q "$sha2"
    git -C "$parent" add submod; git -C "$parent" commit -q -m "bump sub@c2"
    PARENT_REPO="$parent"
}

# ─── Test A: gate writes executions.jsonl on PASS (forward bump) ───
echo "─── Test A: gate execution telemetry (PASS recorded) ───"
build_fixture; parent="$PARENT_REPO"
mdir="$FIXTURE/mymetrics"
( cd "$parent" && ARIA_METRICS_DIR="$mdir" ARIA_SUBMODULE_GATE_MODE=warn bash "$GATE" >/dev/null 2>&1 )
exec_file="$mdir/submodule-gate-executions.jsonl"
if [[ -f "$exec_file" ]] && [[ "$(wc -l < "$exec_file")" -eq 1 ]]; then
    report_pass "executions.jsonl has exactly 1 line after one gate run"
else
    report_fail "executions.jsonl missing or wrong line count (got: $([[ -f $exec_file ]] && wc -l < "$exec_file" || echo none))"
fi
if [[ -f "$exec_file" ]] && grep -q '"verdict":"PASS"' "$exec_file"; then
    report_pass "forward bump recorded as PASS execution (was previously unrecorded)"
else
    report_fail "PASS verdict not recorded in executions.jsonl"
fi
cleanup

# ─── Test B1: hook triggers gate on gitlink-touching commit ───
echo "─── Test B1: hook runs gate on gitlink-touching git commit ───"
build_fixture; parent="$PARENT_REPO"
mdir="$FIXTURE/mymetrics"
printf '{"tool_name":"Bash","tool_input":{"command":"git add submod && git commit -m bump"},"cwd":"%s"}' "$parent" \
  | ( ARIA_METRICS_DIR="$mdir" CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT" bash "$HOOK" >/dev/null 2>&1 )
exec_file="$mdir/submodule-gate-executions.jsonl"
if [[ -f "$exec_file" ]] && [[ "$(wc -l < "$exec_file")" -eq 1 ]]; then
    report_pass "hook invoked gate → executions.jsonl recorded for gitlink-touching commit"
else
    report_fail "hook did not record exactly 1 execution for gitlink-touching commit (got: $([[ -f $exec_file ]] && wc -l < "$exec_file" || echo none))"
fi
cleanup

# ─── Test B2: hook no-op on non-commit command ───
echo "─── Test B2: hook no-op on non-commit command ───"
build_fixture; parent="$PARENT_REPO"
mdir="$FIXTURE/mymetrics"
printf '{"tool_name":"Bash","tool_input":{"command":"git status"},"cwd":"%s"}' "$parent" \
  | ( ARIA_METRICS_DIR="$mdir" CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT" bash "$HOOK" >/dev/null 2>&1 )
if [[ ! -f "$mdir/submodule-gate-executions.jsonl" ]]; then
    report_pass "no executions recorded for non-commit command (git status)"
else
    report_fail "hook recorded execution for non-commit command (should no-op)"
fi
cleanup

# ─── Test B3: hook no-op on commit NOT touching a gitlink (tasks 1.4) ───
echo "─── Test B3: hook no-op on commit without gitlink change ───"
build_fixture; parent="$PARENT_REPO"
mdir="$FIXTURE/mymetrics"
# make a non-gitlink commit on feature
echo extra > "$parent/note.txt"; git -C "$parent" add note.txt; git -C "$parent" commit -q -m "docs: note (no gitlink)"
printf '{"tool_name":"Bash","tool_input":{"command":"git commit -m note"},"cwd":"%s"}' "$parent" \
  | ( ARIA_METRICS_DIR="$mdir" CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT" bash "$HOOK" >/dev/null 2>&1 )
if [[ ! -f "$mdir/submodule-gate-executions.jsonl" ]]; then
    report_pass "no executions recorded for commit not touching a gitlink (no telemetry noise)"
else
    report_fail "hook recorded execution for non-gitlink commit (should no-op)"
fi
cleanup

# ─── Test B4: hook no-op outside a superproject (no .gitmodules) ───
echo "─── Test B4: hook no-op in repo without .gitmodules ───"
FIXTURE=$(mktemp -d -t aria-gatetel-XXXXXX)
plain="$FIXTURE/plain"; git init -q "$plain"
git -C "$plain" config user.email t@t; git -C "$plain" config user.name t; git -C "$plain" config commit.gpgsign false
echo x > "$plain/x.txt"; git -C "$plain" add .; git -C "$plain" commit -q -m init
mdir="$FIXTURE/mymetrics"
printf '{"tool_name":"Bash","tool_input":{"command":"git commit -m x"},"cwd":"%s"}' "$plain" \
  | ( ARIA_METRICS_DIR="$mdir" CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT" bash "$HOOK" >/dev/null 2>&1 )
if [[ ! -f "$mdir/submodule-gate-executions.jsonl" ]]; then
    report_pass "no executions recorded in repo without .gitmodules"
else
    report_fail "hook recorded execution in non-superproject (should no-op)"
fi
cleanup

# ─── Test B5: hook no-op when path merely CONTAINS 160000 (Minor #1 anchored fix) ───
echo "─── Test B5: hook no-op on commit with path containing '160000' (no gitlink) ───"
build_fixture; parent="$PARENT_REPO"
mdir="$FIXTURE/mymetrics"
# add a file whose name contains 160000 — must NOT be mistaken for a gitlink (160000 mode)
echo data > "$parent/report160000.txt"; git -C "$parent" add report160000.txt; git -C "$parent" commit -q -m "data160000"
printf '{"tool_name":"Bash","tool_input":{"command":"git commit -m data160000"},"cwd":"%s"}' "$parent" \
  | ( ARIA_METRICS_DIR="$mdir" CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT" bash "$HOOK" >/dev/null 2>&1 )
if [[ ! -f "$mdir/submodule-gate-executions.jsonl" ]]; then
    report_pass "path containing '160000' (non-gitlink) does NOT false-trigger (anchored mode check)"
else
    report_fail "hook false-triggered on path containing '160000' (Minor #1 anchoring regression)"
fi
cleanup

echo "════════════════════════════════════════════════════════════"
echo "  Results: $PASS PASS / $FAIL FAIL"
echo "════════════════════════════════════════════════════════════"
if [[ "$FAIL" -gt 0 ]]; then
    echo "Failed:"; for f in "${FAILS[@]}"; do echo "  - $f"; done
    exit 1
fi
exit 0

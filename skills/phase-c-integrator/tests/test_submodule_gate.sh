#!/usr/bin/env bash
# test_submodule_gate.sh — 10-scenario replay test for submodule_gate.sh
#
# Spec: openspec/changes/aria-submodule-pointer-regression-gate/proposal.md §Acceptance criteria
# Tasks: §T-replay (T-replay-1 through T-replay-10)
#
# Strategy: ephemeral fixture dirs with real git operations (bare submodule repo +
# parent repo with gitlink + feature branch). Real git is non-negotiable because
# the bug class being prevented is a git graph traversal issue — mocking git
# would validate the mock, not the gate.
#
# Per-test cleanup via trap; full directory remove between tests.
#
# Usage:
#   ./test_submodule_gate.sh                # run all 10 scenarios
#   ./test_submodule_gate.sh 1 3 7          # run only specified scenarios

set -uo pipefail

# Resolve script + gate paths (test runs from anywhere)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATE_SCRIPT="$SCRIPT_DIR/../scripts/submodule_gate.sh"
[[ ! -x "$GATE_SCRIPT" ]] && { echo "ERROR: gate script not executable at $GATE_SCRIPT" >&2; exit 65; }

# Global counters
PASS=0
FAIL=0
SKIPPED=0
declare -a FAIL_DETAIL=()

# Per-test fixture root (deleted via trap)
FIXTURE_ROOT=""
cleanup() {
    [[ -n "$FIXTURE_ROOT" && -d "$FIXTURE_ROOT" ]] && rm -rf "$FIXTURE_ROOT"
}
trap cleanup EXIT

# ─── Helpers ───────────────────────────────────────────────────────────

report_pass() { PASS=$((PASS+1)); echo "  ✓ PASS: $1"; }
report_fail() {
    FAIL=$((FAIL+1))
    FAIL_DETAIL+=("$1")
    echo "  ✗ FAIL: $1" >&2
}

# Create fresh fixture root for one scenario
new_fixture() {
    FIXTURE_ROOT=$(mktemp -d -t aria-gate-test-XXXXXX)
}

# create_bare_submodule_repo <path> <num_commits>
# Creates a bare git repo at <path> with <num_commits> commits on master.
# Echoes the SHAs of each commit (newline-separated).
create_bare_submodule_repo() {
    local bare="$1"
    local n="$2"

    # Use a temporary working repo to build commits, then push to bare
    local work="$bare.work"
    git init -q --bare "$bare"
    git init -q "$work"
    pushd "$work" >/dev/null
    git config user.email "test@example.com"
    git config user.name "Test"
    git config commit.gpgsign false

    for ((i=1; i<=n; i++)); do
        echo "commit $i" > "file_$i.txt"
        git add . >/dev/null
        git commit -q -m "submodule commit $i"
        git rev-parse HEAD
    done

    git remote add origin "$bare"
    git push -q origin master 2>/dev/null || git push -q origin master:master
    popd >/dev/null
    rm -rf "$work"
}

# Create a parent repo with the bare submodule mounted, parent master at <gitlink_sha>
create_parent_repo_with_submodule() {
    local parent="$1" bare_sub="$2" gitlink_sha="$3" sub_path="${4:-submod}"

    git init -q "$parent"
    pushd "$parent" >/dev/null
    git config user.email "test@example.com"
    git config user.name "Test"
    git config commit.gpgsign false
    # Allow file:// submodule URLs for tests (modern git denies by default)
    git config protocol.file.allow always

    echo "parent" > README.md
    git add README.md
    git commit -q -m "parent init"

    # Add submodule at the bare repo
    git -c protocol.file.allow=always submodule add -q "$bare_sub" "$sub_path"
    # Check out specific submodule SHA
    git -C "$sub_path" -c protocol.file.allow=always checkout -q "$gitlink_sha"
    git add "$sub_path"
    git commit -q -m "parent: submodule at $gitlink_sha"

    # Need an "origin" remote for the parent so gate can do `git fetch origin master`
    local parent_bare="${parent}.bare"
    git init -q --bare "$parent_bare"
    git remote add origin "$parent_bare"
    git push -q origin master
    popd >/dev/null
}

# create_feature_branch <parent_repo> <sub_path> <feature_gitlink_sha>
create_feature_branch() {
    local parent="$1" sub_path="$2" feature_sha="$3"
    pushd "$parent" >/dev/null
    git checkout -q -b feature
    git -C "$sub_path" -c protocol.file.allow=always checkout -q "$feature_sha"
    git add "$sub_path"
    git commit -q -m "feature: bump $sub_path to $feature_sha"
    popd >/dev/null
}

# Run the gate from inside parent dir; capture stdout/stderr + exit code
# Usage: run_gate <parent_dir> [extra env vars...]
# Echoes: exit_code on first line, then stdout, then "---STDERR---", then stderr
run_gate() {
    local parent="$1"; shift
    local out err rc
    out=$(mktemp); err=$(mktemp)
    (
        cd "$parent" || exit 65
        "$@" "$GATE_SCRIPT"
    ) > "$out" 2> "$err"
    rc=$?
    echo "$rc"
    cat "$out"
    echo "---STDERR---"
    cat "$err"
    rm -f "$out" "$err"
}

# Assert helpers
assert_exit_code() {
    local actual="$1" expected="$2" name="$3"
    if [[ "$actual" == "$expected" ]]; then
        return 0
    else
        report_fail "$name: expected exit $expected, got $actual"
        return 1
    fi
}

assert_contains() {
    local output="$1" pattern="$2" name="$3"
    if echo "$output" | grep -q -- "$pattern"; then
        return 0
    else
        report_fail "$name: output missing pattern '$pattern'"
        return 1
    fi
}

assert_not_contains() {
    local output="$1" pattern="$2" name="$3"
    if echo "$output" | grep -q -- "$pattern"; then
        report_fail "$name: output should NOT contain '$pattern'"
        return 1
    else
        return 0
    fi
}

# ─── Scenario 1: Happy path forward bump ──────────────────────────────

scenario_1() {
    echo "─── T-replay-1: Happy path forward bump → PASS ───"
    new_fixture
    local bare="$FIXTURE_ROOT/bare-sub"
    local parent="$FIXTURE_ROOT/parent"
    local shas
    shas=$(create_bare_submodule_repo "$bare" 5)
    local sha1 sha5
    sha1=$(echo "$shas" | head -1)
    sha5=$(echo "$shas" | tail -1)

    create_parent_repo_with_submodule "$parent" "$bare" "$sha1"
    create_feature_branch "$parent" "submod" "$sha5"

    local result rc
    result=$(run_gate "$parent" env ARIA_SUBMODULE_GATE_MODE=block)
    rc=$(echo "$result" | head -1)

    if assert_exit_code "$rc" "0" "T-replay-1"; then
        assert_contains "$result" "forward bump" "T-replay-1" && report_pass "forward bump exits 0"
    fi
}

# ─── Scenario 2: Pure regression ───────────────────────────────────────

scenario_2() {
    echo "─── T-replay-2: Pure regression (ancestor) → BLOCK ───"
    new_fixture
    local bare="$FIXTURE_ROOT/bare-sub"
    local parent="$FIXTURE_ROOT/parent"
    local shas sha1 sha5
    shas=$(create_bare_submodule_repo "$bare" 5)
    sha1=$(echo "$shas" | head -1)
    sha5=$(echo "$shas" | tail -1)

    # Master at sha5, feature reverts to sha1 (ancestor)
    create_parent_repo_with_submodule "$parent" "$bare" "$sha5"
    create_feature_branch "$parent" "submod" "$sha1"

    # In block mode: should exit 1 with REGRESSION
    local result rc
    result=$(run_gate "$parent" env ARIA_SUBMODULE_GATE_MODE=block)
    rc=$(echo "$result" | head -1)

    if assert_exit_code "$rc" "1" "T-replay-2 block mode"; then
        assert_contains "$result" "REGRESSION" "T-replay-2 block mode" && \
        assert_contains "$result" "submodule=submod" "T-replay-2 block mode" && \
        report_pass "regression exits 1 with REGRESSION + submodule path"
    fi

    # In warn mode: should exit 0 with WOULD-BLOCK
    local result_warn rc_warn
    result_warn=$(run_gate "$parent" env ARIA_SUBMODULE_GATE_MODE=warn)
    rc_warn=$(echo "$result_warn" | head -1)

    if assert_exit_code "$rc_warn" "0" "T-replay-2 warn mode"; then
        assert_contains "$result_warn" "WOULD-BLOCK" "T-replay-2 warn mode" && \
        report_pass "warn mode logs WOULD-BLOCK, exits 0"
    fi
}

# ─── Scenario 3: Divergent history ─────────────────────────────────────

scenario_3() {
    echo "─── T-replay-3: Divergent history (unrelated branch) → BLOCK with DIVERGENT ───"
    new_fixture
    local bare="$FIXTURE_ROOT/bare-sub"
    local parent="$FIXTURE_ROOT/parent"

    # Create bare repo with main branch (5 commits) + diverged branch (3 commits from initial)
    local work="$bare.work"
    git init -q --bare "$bare"
    git init -q "$work"
    pushd "$work" >/dev/null
    git config user.email "t@e.com" && git config user.name "T" && git config commit.gpgsign false

    echo "main1" > f1.txt && git add . && git commit -q -m "main 1"
    local m1=$(git rev-parse HEAD)
    for i in 2 3 4 5; do echo "main$i" > "f$i.txt" && git add . && git commit -q -m "main $i"; done
    local mtip=$(git rev-parse HEAD)

    # Diverge from m1 into branch-B
    git checkout -q -b branch-B "$m1"
    echo "divB" > divB.txt && git add . && git commit -q -m "div B"
    local divB=$(git rev-parse HEAD)

    git remote add origin "$bare"
    git push -q origin master:master
    git push -q origin branch-B:branch-B
    popd >/dev/null
    rm -rf "$work"

    # Parent: master uses mtip, feature uses divB (unrelated branch)
    create_parent_repo_with_submodule "$parent" "$bare" "$mtip"
    create_feature_branch "$parent" "submod" "$divB"

    local result rc
    result=$(run_gate "$parent" env ARIA_SUBMODULE_GATE_MODE=block)
    rc=$(echo "$result" | head -1)

    if assert_exit_code "$rc" "1" "T-replay-3"; then
        assert_contains "$result" "DIVERGENT" "T-replay-3" && \
        assert_not_contains "$result" "REGRESSION" "T-replay-3" && \
        report_pass "divergent classified correctly (not REGRESSION)"
    fi
}

# ─── Scenario 4: Stale-ref incident replay ─────────────────────────────

scenario_4() {
    echo "─── T-replay-4: Stale-ref fetch recovery ───"
    new_fixture
    local bare="$FIXTURE_ROOT/bare-sub"
    local parent="$FIXTURE_ROOT/parent"
    local shas sha1 sha5
    shas=$(create_bare_submodule_repo "$bare" 5)
    sha1=$(echo "$shas" | head -1)
    sha5=$(echo "$shas" | tail -1)

    # Master at sha5, feature at sha5 (no-change), gate should PASS
    # The "stale-ref" aspect: parent's local origin/master ref pre-fetch may differ from remote
    # We simulate by advancing the parent bare repo AFTER parent's last fetch
    create_parent_repo_with_submodule "$parent" "$bare" "$sha5"
    create_feature_branch "$parent" "submod" "$sha5"

    # Advance parent's "remote" by adding a new commit there
    pushd "$parent" >/dev/null
    git checkout -q master
    echo "new master commit" > extra.txt
    git add extra.txt
    git commit -q -m "new master commit (simulating other terminal advance)"
    git push -q origin master
    git checkout -q feature
    popd >/dev/null

    # Now parent's local origin/master is stale until fetch
    # The gate's mandatory fetch should refresh it; then ancestry check should still pass (no-change)
    local result rc
    result=$(run_gate "$parent" env ARIA_SUBMODULE_GATE_MODE=block)
    rc=$(echo "$result" | head -1)

    if assert_exit_code "$rc" "0" "T-replay-4 stale-ref recovery"; then
        report_pass "stale-ref recovered by mandatory fetch, gate PASS"
    fi

    # Variation: fetch failure → break the origin URL
    pushd "$parent" >/dev/null
    git remote set-url origin "/nonexistent/path/to/bare.git"
    popd >/dev/null

    local result_fail rc_fail
    result_fail=$(run_gate "$parent" env ARIA_SUBMODULE_GATE_MODE=block)
    rc_fail=$(echo "$result_fail" | head -1)

    if assert_exit_code "$rc_fail" "2" "T-replay-4 fetch failure"; then
        assert_contains "$result_fail" "BLOCK: git fetch origin failed" "T-replay-4 fetch failure" && \
        report_pass "fetch failure → exit 2 + explicit diagnostic"
    fi
}

# ─── Scenario 5: Legitimate revert with trailer override ──────────────

scenario_5() {
    echo "─── T-replay-5: Legitimate revert with trailer override → ALLOW ───"
    new_fixture
    local bare="$FIXTURE_ROOT/bare-sub"
    local parent="$FIXTURE_ROOT/parent"
    local shas sha1 sha5
    shas=$(create_bare_submodule_repo "$bare" 5)
    sha1=$(echo "$shas" | head -1)
    sha5=$(echo "$shas" | tail -1)

    create_parent_repo_with_submodule "$parent" "$bare" "$sha5"

    # Create feature that rolls back submodule, WITH trailer in commit message
    pushd "$parent" >/dev/null
    git checkout -q -b feature
    git -C submod -c protocol.file.allow=always checkout -q "$sha1"
    git add submod
    git commit -q -m "feature: rollback submod

Submodule-Rollback: submod $sha5->$sha1 reason=test legitimate revert with trailer"
    popd >/dev/null

    local result rc
    result=$(run_gate "$parent" env ARIA_SUBMODULE_GATE_MODE=block)
    rc=$(echo "$result" | head -1)

    if assert_exit_code "$rc" "0" "T-replay-5 trailer override"; then
        assert_contains "$result" "ALLOW" "T-replay-5 trailer override" && \
        assert_contains "$result" "overridden by per-PR marker" "T-replay-5 trailer override" && \
        report_pass "valid trailer override allows + audit log"
    fi

    # Variation: mismatched SHAs in trailer should NOT override
    pushd "$parent" >/dev/null
    git reset -q --soft HEAD~1
    # Use bogus SHA in trailer
    local bogus="0000000000000000000000000000000000000000"
    git commit -q -m "feature: rollback submod

Submodule-Rollback: submod $bogus->$bogus reason=bogus mismatched override"
    popd >/dev/null

    local result_bad rc_bad
    result_bad=$(run_gate "$parent" env ARIA_SUBMODULE_GATE_MODE=block)
    rc_bad=$(echo "$result_bad" | head -1)

    if assert_exit_code "$rc_bad" "1" "T-replay-5 mismatched trailer"; then
        assert_not_contains "$result_bad" "ALLOW" "T-replay-5 mismatched trailer" && \
        report_pass "mismatched trailer rejected, gate blocks"
    fi
}

# ─── Scenario 6: No-change ─────────────────────────────────────────────

scenario_6() {
    echo "─── T-replay-6: No-change (same pointer) → PASS trivially ───"
    new_fixture
    local bare="$FIXTURE_ROOT/bare-sub"
    local parent="$FIXTURE_ROOT/parent"
    local shas sha3
    shas=$(create_bare_submodule_repo "$bare" 5)
    sha3=$(echo "$shas" | sed -n '3p')

    create_parent_repo_with_submodule "$parent" "$bare" "$sha3"
    # feature branch with SAME submodule pointer + a non-submodule change
    pushd "$parent" >/dev/null
    git checkout -q -b feature
    echo "feature work" > feature.txt
    git add feature.txt
    git commit -q -m "feature: non-submodule change"
    popd >/dev/null

    local result rc
    result=$(run_gate "$parent" env ARIA_SUBMODULE_GATE_MODE=block)
    rc=$(echo "$result" | head -1)

    if assert_exit_code "$rc" "0" "T-replay-6"; then
        assert_contains "$result" "unchanged" "T-replay-6" && \
        report_pass "no-change exits 0 trivially"
    fi
}

# ─── Scenario 7: First-time submodule (nil prior gitlink) — CRITICAL ──

scenario_7() {
    echo "─── T-replay-7: First-time submodule introduction (CRITICAL, qa R1 TEST GAP) ───"
    new_fixture
    local bare="$FIXTURE_ROOT/bare-sub"
    local parent="$FIXTURE_ROOT/parent"
    local shas sha1
    shas=$(create_bare_submodule_repo "$bare" 3)
    sha1=$(echo "$shas" | head -1)

    # Parent: master has NO submodule
    git init -q "$parent"
    pushd "$parent" >/dev/null
    git config user.email "t@e.com" && git config user.name "T" && git config commit.gpgsign false
    git config protocol.file.allow always
    echo "parent" > README.md
    git add README.md
    git commit -q -m "parent init"

    local pbare="$parent.bare"
    git init -q --bare "$pbare"
    git remote add origin "$pbare"
    git push -q origin master

    # feature: first introduce submodule
    git checkout -q -b feature
    git -c protocol.file.allow=always submodule add -q "$bare" newsub
    git -C newsub -c protocol.file.allow=always checkout -q "$sha1"
    git add newsub .gitmodules
    git commit -q -m "feature: first-time add newsub"
    popd >/dev/null

    local result rc
    result=$(run_gate "$parent" env ARIA_SUBMODULE_GATE_MODE=block)
    rc=$(echo "$result" | head -1)

    if assert_exit_code "$rc" "0" "T-replay-7 first-time submodule"; then
        assert_contains "$result" "first introduced" "T-replay-7" && \
        report_pass "first-time submodule PASS + INFO log (nil-SHA handled)"
    fi
}

# ─── Scenario 8: Submodule removed from feature ───────────────────────

scenario_8() {
    echo "─── T-replay-8: Submodule removed from feature ───"
    new_fixture
    local bare="$FIXTURE_ROOT/bare-sub"
    local parent="$FIXTURE_ROOT/parent"
    local shas sha2
    shas=$(create_bare_submodule_repo "$bare" 3)
    sha2=$(echo "$shas" | sed -n '2p')

    create_parent_repo_with_submodule "$parent" "$bare" "$sha2"
    pushd "$parent" >/dev/null
    git checkout -q -b feature
    # Remove submodule via standard procedure
    git submodule deinit -qf submod
    git rm -qf submod
    rm -rf .git/modules/submod
    git commit -q -m "feature: remove submod"
    popd >/dev/null

    local result rc
    result=$(run_gate "$parent" env ARIA_SUBMODULE_GATE_MODE=block)
    rc=$(echo "$result" | head -1)

    # Gate enumerates from .gitmodules which is now empty → trivially passes
    if assert_exit_code "$rc" "0" "T-replay-8 submodule removed"; then
        report_pass "submodule removed from feature: gate exits 0 (no .gitmodules entry to check)"
    fi
}

# ─── Scenario 9: Concurrent force-push race (deterministic pre-stage) ─

scenario_9() {
    echo "─── T-replay-9: Concurrent force-push race (deterministic pre-stage) ───"
    new_fixture
    local bare="$FIXTURE_ROOT/bare-sub"
    local parent="$FIXTURE_ROOT/parent"
    local shas sha1 sha2 sha3
    shas=$(create_bare_submodule_repo "$bare" 3)
    sha1=$(echo "$shas" | head -1)
    sha3=$(echo "$shas" | tail -1)

    create_parent_repo_with_submodule "$parent" "$bare" "$sha1"
    create_feature_branch "$parent" "submod" "$sha3"  # forward bump

    # Parent has already fetched at create_parent. Now simulate force-push BEFORE gate runs:
    # advance origin/master to a divergent commit (non-ancestor of current local origin/master)
    pushd "$parent" >/dev/null
    git checkout -q master
    local local_master_before=$(git rev-parse HEAD)
    popd >/dev/null

    # Force-push divergent commit to origin (via temporary work clone)
    local pbare="$parent.bare"
    local work2="$pbare.work2"
    git clone -q "$pbare" "$work2"
    pushd "$work2" >/dev/null
    git config user.email "t@e.com" && git config user.name "T" && git config commit.gpgsign false
    git config protocol.file.allow always
    # Reset to first parent commit (orphan-equivalent) then make a divergent commit
    local first_parent=$(git rev-list --max-parents=0 HEAD | head -1)
    git reset -q --hard "$first_parent"
    echo "divergent" > div.txt
    git add div.txt
    git commit -q -m "divergent master rewrite"
    git push -q -f origin master
    popd >/dev/null
    rm -rf "$work2"

    # Now parent's origin/master local ref is stale; the bare remote has divergent history
    # Gate will fetch → AFTER differs from BEFORE → ancestry check should detect non-ancestor → BLOCK exit 3
    local result rc
    result=$(run_gate "$parent" env ARIA_SUBMODULE_GATE_MODE=block)
    rc=$(echo "$result" | head -1)

    if assert_exit_code "$rc" "3" "T-replay-9 force-push detection"; then
        assert_contains "$result" "origin/master rewritten" "T-replay-9" && \
        report_pass "force-push (non-ancestor advance) detected via refspec assertion, exit 3"
    fi
}

# ─── Scenario 10: Detached HEAD submodule ──────────────────────────────

scenario_10() {
    echo "─── T-replay-10: Detached HEAD submodule (Rev1 NEW per qa I-qa-1) ───"
    new_fixture
    local bare="$FIXTURE_ROOT/bare-sub"
    local parent="$FIXTURE_ROOT/parent"
    local shas sha2 sha3
    shas=$(create_bare_submodule_repo "$bare" 3)
    sha2=$(echo "$shas" | sed -n '2p')
    sha3=$(echo "$shas" | tail -1)

    create_parent_repo_with_submodule "$parent" "$bare" "$sha2"
    create_feature_branch "$parent" "submod" "$sha3"

    # Submodule is now likely already detached (standard submodule update behavior),
    # but verify explicitly:
    pushd "$parent" >/dev/null
    pushd submod >/dev/null
    # Force detached HEAD state
    git -c protocol.file.allow=always checkout -q --detach HEAD
    local head_state=$(git symbolic-ref -q HEAD 2>/dev/null || echo "DETACHED")
    popd >/dev/null
    popd >/dev/null

    if [[ "$head_state" != "DETACHED" ]]; then
        echo "  ! WARN: expected DETACHED but got $head_state"
    fi

    local result rc
    result=$(run_gate "$parent" env ARIA_SUBMODULE_GATE_MODE=block)
    rc=$(echo "$result" | head -1)

    # Should still work — gate uses raw SHAs, not branch refs
    if assert_exit_code "$rc" "0" "T-replay-10 detached HEAD"; then
        assert_contains "$result" "forward bump" "T-replay-10" && \
        report_pass "detached HEAD submodule: ancestry check works on raw SHAs"
    fi
}

# ─── Main ──────────────────────────────────────────────────────────────

if [[ $# -gt 0 ]]; then
    SCENARIOS=("$@")
else
    SCENARIOS=(1 2 3 4 5 6 7 8 9 10)
fi

echo "════════════════════════════════════════════════════════════"
echo "  submodule_gate.sh — 10-scenario replay test"
echo "  Spec: aria-submodule-pointer-regression-gate"
echo "  Scenarios to run: ${SCENARIOS[*]}"
echo "════════════════════════════════════════════════════════════"
echo

for n in "${SCENARIOS[@]}"; do
    case "$n" in
        1) scenario_1 ;;
        2) scenario_2 ;;
        3) scenario_3 ;;
        4) scenario_4 ;;
        5) scenario_5 ;;
        6) scenario_6 ;;
        7) scenario_7 ;;
        8) scenario_8 ;;
        9) scenario_9 ;;
        10) scenario_10 ;;
        *) echo "  ! SKIP: unknown scenario $n"; SKIPPED=$((SKIPPED+1)) ;;
    esac
    echo
done

echo "════════════════════════════════════════════════════════════"
echo "  Results: $PASS PASS / $FAIL FAIL / $SKIPPED skipped"
echo "════════════════════════════════════════════════════════════"

if [[ "$FAIL" -gt 0 ]]; then
    echo
    echo "Failed assertions:"
    for d in "${FAIL_DETAIL[@]}"; do echo "  - $d"; done
    exit 1
fi

exit 0

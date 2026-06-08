#!/usr/bin/env bash
# Tests for R-fix-2 (Spec aria-submodule-gate-operationalize TG-2):
#   submodule-tripwire-audit.sh — host-cron post-merge ancestry audit (HEAD~1 vs HEAD).
#
# Real git fixtures (bare submodule + superproject with gitlink change across
# HEAD~1→HEAD). Mocking git would validate the mock, not the graph traversal.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUDIT="$SCRIPT_DIR/../scripts/submodule-tripwire-audit.sh"
[[ -f "$AUDIT" ]] || { echo "ERROR: audit script not found at $AUDIT" >&2; exit 65; }

PASS=0; FAIL=0; declare -a FAILS=()
report_pass() { PASS=$((PASS+1)); echo "  ✓ PASS: $1"; }
report_fail() { FAIL=$((FAIL+1)); FAILS+=("$1"); echo "  ✗ FAIL: $1" >&2; }

FIXTURE=""
cleanup() { [[ -n "$FIXTURE" && -d "$FIXTURE" ]] && rm -rf "$FIXTURE"; }
trap cleanup EXIT

PARENT=""
# build_fixture <direction>  (forward | backward)
# Superproject HEAD~1 = sub@first, HEAD = sub@second.
# forward:  HEAD~1=c1, HEAD=c2 (c1 ancestor of c2 → clean)
# backward: HEAD~1=c2, HEAD=c1 (c2 NOT ancestor of c1 → MISS)
build_fixture() {
    local direction="$1"
    FIXTURE=$(mktemp -d -t aria-tripwire-XXXXXX)
    local bare="$FIXTURE/sub.git" work="$FIXTURE/sub.work"
    git init -q --bare "$bare"; git init -q "$work"
    git -C "$work" config user.email t@t; git -C "$work" config user.name t; git -C "$work" config commit.gpgsign false
    echo c1 > "$work/f.txt"; git -C "$work" add .; git -C "$work" commit -q -m c1; local c1; c1=$(git -C "$work" rev-parse HEAD)
    echo c2 > "$work/f.txt"; git -C "$work" add .; git -C "$work" commit -q -m c2; local c2; c2=$(git -C "$work" rev-parse HEAD)
    git -C "$work" push -q "$bare" HEAD:master
    local first second
    if [[ "$direction" == "forward" ]]; then first="$c1"; second="$c2"; else first="$c2"; second="$c1"; fi

    local parent="$FIXTURE/parent"; git init -q "$parent"
    git -C "$parent" config user.email t@t; git -C "$parent" config user.name t; git -C "$parent" config commit.gpgsign false
    git -C "$parent" config protocol.file.allow always
    echo p > "$parent/README.md"; git -C "$parent" add README.md; git -C "$parent" commit -q -m init
    git -C "$parent" -c protocol.file.allow=always submodule add -q "$bare" submod
    git -C "$parent/submod" checkout -q "$first"; git -C "$parent" add submod; git -C "$parent" commit -q -m "sub@first"  # HEAD~1
    git -C "$parent/submod" checkout -q "$second"; git -C "$parent" add submod; git -C "$parent" commit -q -m "sub@second" # HEAD
    PARENT="$parent"
}

run_audit() { ( cd "$PARENT" && ARIA_METRICS_DIR="$FIXTURE/m" "$@" bash "$AUDIT" ); }

# ─── Test 1: forward bump → clean, exit 0, heartbeat recorded ───
echo "─── Test 1: forward bump → clean ───"
build_fixture forward
run_audit >/dev/null 2>&1; rc=$?
mf="$FIXTURE/m/submodule-gate-misses.jsonl"
if [[ $rc -eq 0 ]]; then report_pass "forward bump exits 0 (clean)"; else report_fail "forward bump exit $rc (expected 0)"; fi
if [[ -f "$mf" ]] && grep -q '"kind":"tripwire_run","result":"clean"' "$mf"; then
    report_pass "clean heartbeat (tripwire_run/clean) recorded"
else report_fail "clean heartbeat not recorded"; fi
if [[ -f "$mf" ]] && ! grep -q '"kind":"tripwire_miss"' "$mf"; then
    report_pass "no miss record on clean forward bump"
else report_fail "unexpected miss record on forward bump"; fi
cleanup

# ─── Test 2: regression (backward) → MISS, exit 1, miss recorded ───
echo "─── Test 2: backward bump → MISS ───"
build_fixture backward
run_audit >/dev/null 2>&1; rc=$?
mf="$FIXTURE/m/submodule-gate-misses.jsonl"
if [[ $rc -eq 1 ]]; then report_pass "regression exits 1 (MISS)"; else report_fail "regression exit $rc (expected 1)"; fi
if [[ -f "$mf" ]] && grep -q '"kind":"tripwire_miss","submodule":"submod"' "$mf"; then
    report_pass "tripwire_miss record written for backward bump"
else report_fail "tripwire_miss record missing"; fi
if [[ -f "$mf" ]] && grep -q '"kind":"tripwire_run","result":"miss"' "$mf"; then
    report_pass "heartbeat records result=miss"
else report_fail "heartbeat result!=miss"; fi
cleanup

# ─── Test 3: dry-run → no jsonl side effects ───
echo "─── Test 3: dry-run → no side effects ───"
build_fixture backward
run_audit ARIA_TRIPWIRE_DRY_RUN=1 >/dev/null 2>&1; rc=$?
mf="$FIXTURE/m/submodule-gate-misses.jsonl"
if [[ ! -f "$mf" ]]; then report_pass "dry-run writes no misses.jsonl"; else report_fail "dry-run wrote jsonl (should be no-op)"; fi
cleanup

# ─── Test 4: no .gitmodules → trivially clean, exit 0 ───
echo "─── Test 4: no .gitmodules → trivial clean ───"
FIXTURE=$(mktemp -d -t aria-tripwire-XXXXXX)
plain="$FIXTURE/plain"; git init -q "$plain"
git -C "$plain" config user.email t@t; git -C "$plain" config user.name t; git -C "$plain" config commit.gpgsign false
echo a > "$plain/a"; git -C "$plain" add .; git -C "$plain" commit -q -m c1
echo b > "$plain/a"; git -C "$plain" add .; git -C "$plain" commit -q -m c2
( cd "$plain" && ARIA_METRICS_DIR="$FIXTURE/m" bash "$AUDIT" >/dev/null 2>&1 ); rc=$?
if [[ $rc -eq 0 ]]; then report_pass "no .gitmodules → exit 0 trivial clean"; else report_fail "no .gitmodules exit $rc"; fi
cleanup

# ─── Test 5: no gitlink change between HEAD~1/HEAD → clean heartbeat, no miss ───
echo "─── Test 5: no-change → heartbeat only ───"
build_fixture forward
# add a non-gitlink commit so HEAD~1→HEAD has no gitlink change
echo note > "$PARENT/note.txt"; git -C "$PARENT" add note.txt; git -C "$PARENT" commit -q -m "docs note"
run_audit >/dev/null 2>&1; rc=$?
mf="$FIXTURE/m/submodule-gate-misses.jsonl"
if [[ $rc -eq 0 ]] && [[ -f "$mf" ]] && grep -q '"result":"clean"' "$mf" && ! grep -q 'tripwire_miss' "$mf"; then
    report_pass "no-change HEAD~1..HEAD → clean heartbeat, no miss"
else report_fail "no-change handling wrong (rc=$rc)"; fi
cleanup

# ─── Test 6: two submodules (one forward, one backward) → MISS only for backward ───
echo "─── Test 6: 2 submodules, one backward → 1 miss ───"
FIXTURE=$(mktemp -d -t aria-tripwire-XXXXXX)
mk_bare() {  # $1=name → echoes "c1 c2"
    local bare="$FIXTURE/$1.git" work="$FIXTURE/$1.work"
    git init -q --bare "$bare"; git init -q "$work"
    git -C "$work" config user.email t@t; git -C "$work" config user.name t; git -C "$work" config commit.gpgsign false
    echo a > "$work/f"; git -C "$work" add .; git -C "$work" commit -q -m c1; local c1; c1=$(git -C "$work" rev-parse HEAD)
    echo b > "$work/f"; git -C "$work" add .; git -C "$work" commit -q -m c2; local c2; c2=$(git -C "$work" rev-parse HEAD)
    git -C "$work" push -q "$bare" HEAD:master; echo "$c1 $c2"
}
read a1 a2 <<<"$(mk_bare suba)"
read b1 b2 <<<"$(mk_bare subb)"
parent="$FIXTURE/parent"; git init -q "$parent"
git -C "$parent" config user.email t@t; git -C "$parent" config user.name t; git -C "$parent" config commit.gpgsign false
git -C "$parent" config protocol.file.allow always
echo p > "$parent/README.md"; git -C "$parent" add README.md; git -C "$parent" commit -q -m init
git -C "$parent" -c protocol.file.allow=always submodule add -q "$FIXTURE/suba.git" suba
git -C "$parent" -c protocol.file.allow=always submodule add -q "$FIXTURE/subb.git" subb
# HEAD~1: suba@a1, subb@b2
git -C "$parent/suba" checkout -q "$a1"; git -C "$parent/subb" checkout -q "$b2"
git -C "$parent" add suba subb; git -C "$parent" commit -q -m "subs first"
# HEAD: suba@a2 (forward), subb@b1 (backward)
git -C "$parent/suba" checkout -q "$a2"; git -C "$parent/subb" checkout -q "$b1"
git -C "$parent" add suba subb; git -C "$parent" commit -q -m "suba fwd, subb back"
( cd "$parent" && ARIA_METRICS_DIR="$FIXTURE/m" bash "$AUDIT" >/dev/null 2>&1 ); rc=$?
mf="$FIXTURE/m/submodule-gate-misses.jsonl"
miss_count=$(grep -c '"kind":"tripwire_miss"' "$mf" 2>/dev/null || echo 0)
if [[ $rc -eq 1 ]] && [[ "$miss_count" -eq 1 ]] && grep -q '"submodule":"subb"' "$mf" && ! grep -q '"submodule":"suba"' "$mf"; then
    report_pass "multi-submodule: only backward (subb) flagged, forward (suba) clean, exit 1"
else report_fail "multi-submodule wrong (rc=$rc, miss_count=$miss_count)"; fi
cleanup

echo "════════════════════════════════════════════════════════════"
echo "  Results: $PASS PASS / $FAIL FAIL"
echo "════════════════════════════════════════════════════════════"
if [[ "$FAIL" -gt 0 ]]; then echo "Failed:"; for f in "${FAILS[@]}"; do echo "  - $f"; done; exit 1; fi
exit 0

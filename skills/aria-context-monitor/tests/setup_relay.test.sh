#!/bin/bash
# setup_relay.test.sh — TASK-007 bash-side fallback/idempotency tests.
# Self-contained; uses temp HOME + temp settings, never touches real ~/.claude.
# Run: bash aria/skills/aria-context-monitor/tests/setup_relay.test.sh
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SETUP="$HERE/../scripts/setup_relay.sh"
MARKER="# >>> aria-context-monitor relay >>>"
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ok   - $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  FAIL - $1"; }

if ! command -v jq >/dev/null 2>&1; then echo "SKIP: jq not available"; exit 0; fi

# ---- case 1: statusline-no-relay → inject, preserve custom bar ----
T1=$(mktemp -d)
cat > "$T1/sl.sh" <<'SL'
#!/bin/bash
input=$(cat)
# user custom context bar (must survive injection)
model=$(echo "$input" | jq -r '.model.display_name')
printf "MYBAR %s" "$model"
SL
echo "{\"statusLine\":{\"type\":\"command\",\"command\":\"bash $T1/sl.sh\"}}" > "$T1/settings.json"

out=$(bash "$SETUP" --settings "$T1/settings.json" 2>&1)
grep -qF "$MARKER" "$T1/sl.sh" && ok "case1: relay marker injected" || bad "case1: marker missing"
grep -q "MYBAR" "$T1/sl.sh" && ok "case1: custom bar preserved" || bad "case1: custom bar lost"
# marker must come AFTER input=$(cat)
cat_line=$(grep -n 'input=\$(cat)' "$T1/sl.sh" | head -1 | cut -d: -f1)
mk_line=$(grep -nF "$MARKER" "$T1/sl.sh" | head -1 | cut -d: -f1)
[ -n "$cat_line" ] && [ -n "$mk_line" ] && [ "$mk_line" -gt "$cat_line" ] && ok "case1: marker after input=\$(cat)" || bad "case1: marker position wrong"

# ---- case 2: run-twice idempotent (no duplicate marker) ----
bash "$SETUP" --settings "$T1/settings.json" >/dev/null 2>&1
count=$(grep -cF "$MARKER" "$T1/sl.sh")
[ "$count" -eq 1 ] && ok "case2: run-twice idempotent (1 marker, got $count)" || bad "case2: duplicate marker ($count)"
state=$(bash "$SETUP" --settings "$T1/settings.json" --status 2>&1)
echo "$state" | grep -q "relay-installed" && ok "case2: --status reports relay-installed" || bad "case2: status wrong: $state"

# ---- case 3: pre-existing relay marker recognized (no settings churn) ----
state3=$(bash "$SETUP" --settings "$T1/settings.json" 2>&1)
echo "$state3" | grep -q "no-op" && ok "case3: pre-existing marker → no-op" || bad "case3: not no-op: $state3"

# ---- case 4: no-statusline → minimal reference (temp HOME) ----
T4=$(mktemp -d)
HOME="$T4" bash "$SETUP" --settings "$T4/.claude/settings.json" >/dev/null 2>&1
ref="$T4/.claude/statusline-command.sh"
[ -f "$ref" ] && ok "case4: minimal reference created" || bad "case4: no reference script"
grep -qF "$MARKER" "$ref" 2>/dev/null && ok "case4: reference has relay block" || bad "case4: reference missing relay"
grep -q 'input=$(cat)' "$ref" 2>/dev/null && ok "case4: reference has input=\$(cat) anchor" || bad "case4: no anchor"

# ---- case 5: dry-run does not modify ----
T5=$(mktemp -d)
cat > "$T5/sl.sh" <<'SL'
#!/bin/bash
input=$(cat)
echo hi
SL
echo "{\"statusLine\":{\"type\":\"command\",\"command\":\"bash $T5/sl.sh\"}}" > "$T5/settings.json"
before=$(md5sum "$T5/sl.sh" | cut -d' ' -f1)
bash "$SETUP" --settings "$T5/settings.json" --dry-run >/dev/null 2>&1
after=$(md5sum "$T5/sl.sh" | cut -d' ' -f1)
[ "$before" = "$after" ] && ok "case5: dry-run does not modify script" || bad "case5: dry-run modified script"

rm -rf "$T1" "$T4" "$T5"
echo ""
echo "setup_relay tests: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1

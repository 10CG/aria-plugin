#!/usr/bin/env bash
# Self-test for jq-crlf-guard.sh (TASK-008). Non-vacuous: proves the guard FLAGS
# unguarded jq captures and does NOT flag guarded/exempt/constructor forms.
# Run: bash aria/hooks/tests/jq-crlf-guard.test.sh
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
GUARD="$HERE/jq-crlf-guard.sh"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ok   - $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL - $1"; }

# write a one-off script and return its path
mk() { local d; d="$(mktemp -d)"; printf '%s\n' "$2" > "$d/$1"; printf '%s' "$d/$1"; }

# guard exits 1 (flags) for the given file, 0 otherwise. Returns guard exit code.
run_guard() { bash "$GUARD" "$1" >/dev/null 2>&1; echo $?; }

# 1. real production tree is clean
[ "$(bash "$GUARD" >/dev/null 2>&1; echo $?)" = "0" ] && ok "real tree clean" || bad "real tree NOT clean"

# 2. unguarded Pattern B (VAR=$(jq -r '.field')) → FLAGGED
f="$(mk bad_b.sh 'x=$(printf "%s" "$i" | jq -r ".tool_name" 2>/dev/null)
echo "$x"')"
[ "$(run_guard "$f")" = "1" ] && ok "flags unguarded VAR=\$(jq -r)" || bad "missed unguarded VAR=\$(jq -r)"; rm -rf "$(dirname "$f")"

# 3. guarded Pattern B (strip on next line) → NOT flagged
f="$(mk ok_b.sh 'x=$(printf "%s" "$i" | jq -r ".tool_name" 2>/dev/null)
x="${x%$'"'"'\r'"'"'}"
echo "$x"')"
[ "$(run_guard "$f")" = "0" ] && ok "passes guarded VAR=\$(jq -r)+strip" || bad "false-positive on guarded capture"; rm -rf "$(dirname "$f")"

# 4. jq -n constructor → NOT flagged (not a consumer)
f="$(mk ctor.sh 'entry=$(jq -n --arg a "$x" "{a:\$a}")
echo "$entry"')"
[ "$(run_guard "$f")" = "0" ] && ok "exempts jq -n constructor" || bad "false-positive on jq -n"; rm -rf "$(dirname "$f")"

# 5. # crlf-ok annotation → NOT flagged
f="$(mk anno.sh 'body=$(printf "%s" "$i" | jq -r ".content" 2>/dev/null)  # crlf-ok: data body, must not strip
echo "$body"')"
[ "$(run_guard "$f")" = "0" ] && ok "exempts # crlf-ok annotated" || bad "false-positive on # crlf-ok"; rm -rf "$(dirname "$f")"

# 6. unguarded Pattern A (readarray < <(jq)) → FLAGGED
f="$(mk bad_a.sh 'readarray -t arr < <(jq -r ".a, .b" <<<"$i")
echo "${arr[0]}"')"
[ "$(run_guard "$f")" = "1" ] && ok "flags unguarded readarray<<(jq)" || bad "missed unguarded readarray"; rm -rf "$(dirname "$f")"

# 7. guarded Pattern A (| tr -d '\r') → NOT flagged
f="$(mk ok_a.sh 'readarray -t arr < <(jq -r ".a, .b" <<<"$i" | tr -d '"'"'\r'"'"')
echo "${arr[0]}"')"
[ "$(run_guard "$f")" = "0" ] && ok "passes guarded readarray+tr -d" || bad "false-positive on guarded readarray"; rm -rf "$(dirname "$f")"

echo ""
echo "jq-crlf-guard tests: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1

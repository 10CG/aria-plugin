#!/usr/bin/env bash
# Self-test for the CRLF test framework (lib/crlf-shim.sh).
# Proves the framework is non-vacuous: shim injects CR, both consumption shapes
# reproduce it, self-check is bidirectional, and the two-state assertion rejects
# hollow (non-flipping) results.
#
# Run: bash aria/hooks/tests/crlf-shim.test.sh   (needs jq, awk)
# Exit 0 if all pass, 1 otherwise.

set -u
source "$(dirname "$0")/lib/crlf-shim.sh"

pass=0; fail=0; failures=()
ok()   { pass=$((pass+1)); }
bad()  { fail=$((fail+1)); failures+=("FAIL [$1]"); }

shim="$(crlf_shim_create)" || { echo "cannot create shim"; exit 1; }

# 1. bidirectional self-check passes with a correct shim
if crlf_selfcheck "$shim" 2>/dev/null; then ok; else bad "selfcheck-correct-shim"; fi

# 2. self-check is genuinely bidirectional: a broken shim that injects NO CR
#    must FAIL selfcheck (proves it's not a one-sided always-pass).
broken_shim="$(mktemp -d)"
real_jq="$(command -v jq)"
printf '#!/usr/bin/env bash\n"%s" "$@"\n' "$real_jq" > "$broken_shim/jq"  # passthrough, no CR
chmod +x "$broken_shim/jq"
if crlf_selfcheck "$broken_shim" 2>/dev/null; then bad "selfcheck-rejects-broken-shim"; else ok; fi
rm -rf "$broken_shim"

# 3. readarray-pipe consumption shape retains CR under shim
if crlf_shape_readarray_has_cr "$shim"; then ok; else bad "shape-readarray-cr"; fi

# 4. command-subst consumption shape retains CR under shim
if crlf_shape_cmdsubst_has_cr "$shim"; then ok; else bad "shape-cmdsubst-cr"; fi

# 5. two-state assertion confirms a genuine flip (bug→ok)
if crlf_assert_two_state "genuine-flip" "bug" "ok" 2>/dev/null; then ok; else bad "two-state-accepts-flip"; fi

# 6. two-state assertion REJECTS hollow results (both ok = fix had no effect to prove)
if crlf_assert_two_state "hollow" "ok" "ok" 2>/dev/null; then bad "two-state-rejects-hollow"; else ok; fi

# 7. two-state assertion REJECTS inverted/no-bug-reproduced (pristine ok)
if crlf_assert_two_state "no-repro" "ok" "bug" 2>/dev/null; then bad "two-state-rejects-no-repro"; else ok; fi

# 8. make_pristine_copy strips a fix and is independently runnable
demo="$(mktemp)"; printf '#!/usr/bin/env bash\necho HELLO | tr -d "L"\n' > "$demo"; chmod +x "$demo"
pristine="$(crlf_make_pristine_copy "$demo" 's/ | tr -d "L"//')"
demo_out="$(bash "$demo")"; pristine_out="$(bash "$pristine")"
if [[ "$demo_out" == "HEO" && "$pristine_out" == "HELLO" ]]; then ok; else bad "make-pristine-copy"; fi
rm -f "$demo" "$pristine"

crlf_shim_destroy "$shim"

total=$((pass+fail))
echo "──────────────────────────────────────────────────"
echo "crlf-shim framework self-test"
echo "PASS: $pass / $total"
echo "FAIL: $fail / $total"
if [[ $fail -gt 0 ]]; then printf '  %s\n' "${failures[@]}"; exit 1; fi
exit 0

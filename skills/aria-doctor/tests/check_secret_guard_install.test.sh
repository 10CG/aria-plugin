#!/usr/bin/env bash
# Unit tests for aria-doctor::check_secret_guard_install.
#
# Run: bash aria/skills/aria-doctor/tests/check_secret_guard_install.test.sh
# Coverage: 8 cases (5 primary states × scenarios + 2 sub-flag + 1 banner-missing edge)
# Spec: openspec/changes/aria-secret-guard-plugin-default/detailed-tasks.yaml TASK-004

set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CHECK_SCRIPT="$SCRIPT_DIR/../scripts/check_secret_guard_install.sh"
pass=0
fail=0
failures=()

# ── Fixture builder ───────────────────────────────────────────────────────
# Creates a temp project + temp plugin root with controllable presence/content
# of the relevant files. Returns the project + plugin paths.
mk_fixture() {
  local project="$1" plugin="$2" \
        plugin_hook_content="$3" \
        local_hook_content="$4" \
        plugin_json_version="$5" \
        settings_content="$6"

  mkdir -p "$project/.claude/scripts" "$plugin/hooks" "$plugin/.claude-plugin"

  if [ "$plugin_hook_content" != "__MISSING__" ]; then
    printf '%s\n' "$plugin_hook_content" > "$plugin/hooks/secret-guard.sh"
  fi
  if [ "$local_hook_content" != "__MISSING__" ]; then
    printf '%s\n' "$local_hook_content" > "$project/.claude/scripts/secret-guard.sh"
  fi
  cat > "$plugin/.claude-plugin/plugin.json" <<EOF
{"name":"aria","version":"$plugin_json_version"}
EOF
  if [ "$settings_content" != "__MISSING__" ]; then
    printf '%s\n' "$settings_content" > "$project/.claude/settings.json"
  fi
}

# ── Test runner ───────────────────────────────────────────────────────────
# Args: name expected_state expected_sub_flags_jq_filter project plugin
run_case() {
  local name="$1" want_state="$2" want_sub_flags="$3" project="$4" plugin="$5"
  local out
  out=$(bash "$CHECK_SCRIPT" "$project" "$plugin" 2>/dev/null)
  local exit=$?

  if [ $exit -ne 0 ]; then
    fail=$((fail + 1))
    failures+=("FAIL [$name]: exit code $exit (expected 0)")
    return
  fi

  local got_state
  got_state=$(printf '%s' "$out" | jq -r '.state')
  if [ "$got_state" != "$want_state" ]; then
    fail=$((fail + 1))
    failures+=("FAIL [$name]: state want=$want_state got=$got_state | out=$out")
    return
  fi

  local got_sub_flags
  got_sub_flags=$(printf '%s' "$out" | jq -cr '.sub_flags | sort')
  if [ "$got_sub_flags" != "$want_sub_flags" ]; then
    fail=$((fail + 1))
    failures+=("FAIL [$name]: sub_flags want=$want_sub_flags got=$got_sub_flags | out=$out")
    return
  fi

  pass=$((pass + 1))
}

# ── Set up tmp scratch root ───────────────────────────────────────────────
SCRATCH=$(mktemp -d -t aria-doctor-tests.XXXXXX)
trap 'rm -rf "$SCRATCH"' EXIT

# ──────────────────────────────────────────────────────────────────────────
# Test 1: not_installed
# Neither plugin hook nor local hook present; settings.json absent.
# (R2 BA N1 closure: state reachable only if plugin not loaded / mis-resolved)
# ──────────────────────────────────────────────────────────────────────────
T1=$SCRATCH/t1; mkdir -p "$T1/proj" "$T1/plug"
mk_fixture "$T1/proj" "$T1/plug" "__MISSING__" "__MISSING__" "1.24.0" "__MISSING__"
run_case "1: not_installed (no plugin + no local)" \
  "not_installed" "[]" \
  "$T1/proj" "$T1/plug"

# ──────────────────────────────────────────────────────────────────────────
# Test 2: single_plugin
# Plugin hook present, no local hook. Expected state for new projects after v1.24.0.
# ──────────────────────────────────────────────────────────────────────────
T2=$SCRATCH/t2; mkdir -p "$T2/proj" "$T2/plug"
mk_fixture "$T2/proj" "$T2/plug" \
  "$(printf '%s\n%s\n' '#!/usr/bin/env bash' '# Aria-plugin secret-guard hook v1.24.0')" \
  "__MISSING__" "1.24.0" "__MISSING__"
run_case "2: single_plugin (plugin only)" \
  "single_plugin" "[]" \
  "$T2/proj" "$T2/plug"

# ──────────────────────────────────────────────────────────────────────────
# Test 3: single_local
# Local hook present, plugin hook absent. Advisory must mention BOTH causes
# (R2 BA N2: "plugin not loaded? OR plugin version < v1.24.0").
# ──────────────────────────────────────────────────────────────────────────
T3=$SCRATCH/t3; mkdir -p "$T3/proj" "$T3/plug"
mk_fixture "$T3/proj" "$T3/plug" "__MISSING__" \
  "$(printf '%s\n%s\n' '#!/usr/bin/env bash' '# secret-guard.sh v1.2.0 (SilkNode upstream)')" \
  "1.24.0" "__MISSING__"
run_case "3: single_local (local only, advisory dual-cause)" \
  "single_local" "[]" \
  "$T3/proj" "$T3/plug"
# Additional assertion: advisory includes both possible causes (R2 BA N2)
adv3=$(bash "$CHECK_SCRIPT" "$T3/proj" "$T3/plug" 2>/dev/null | jq -r '.advisory')
if echo "$adv3" | grep -q "plugin not loaded" && echo "$adv3" | grep -q "version < v1.24.0"; then
  : # OK, both causes mentioned
else
  fail=$((fail + 1))
  failures+=("FAIL [3-advisory: single_local must mention BOTH 'plugin not loaded' AND 'version < v1.24.0' per R2 BA N2 | got: $adv3]")
  pass=$((pass - 1))
fi

# ──────────────────────────────────────────────────────────────────────────
# Test 4: dual_install (clean — identical content, no sub-flags)
# Both hooks present with byte-identical content. Expected: KEEP advisory.
# ──────────────────────────────────────────────────────────────────────────
T4=$SCRATCH/t4; mkdir -p "$T4/proj" "$T4/plug"
IDENTICAL_CONTENT="$(printf '%s\n%s\n' '#!/usr/bin/env bash' '# Aria-plugin secret-guard hook v1.24.0')"
mk_fixture "$T4/proj" "$T4/plug" "$IDENTICAL_CONTENT" "$IDENTICAL_CONTENT" "1.24.0" "__MISSING__"
run_case "4: dual_install (identical content, no sub-flags, KEEP)" \
  "dual_install" "[]" \
  "$T4/proj" "$T4/plug"

# ──────────────────────────────────────────────────────────────────────────
# Test 5: dual_install + stale_local_version + divergent_content
# Local has banner with older version + content differs.
# ──────────────────────────────────────────────────────────────────────────
T5=$SCRATCH/t5; mkdir -p "$T5/proj" "$T5/plug"
mk_fixture "$T5/proj" "$T5/plug" \
  "$(printf '%s\n%s\n%s\n' '#!/usr/bin/env bash' '# Aria-plugin secret-guard hook v1.24.0' '# new line')" \
  "$(printf '%s\n%s\n' '#!/usr/bin/env bash' '# secret-guard.sh v1.2.0 (SilkNode upstream)')" \
  "1.24.0" "__MISSING__"
run_case "5: dual_install + stale_local_version + divergent_content" \
  "dual_install" '["divergent_content","stale_local_version"]' \
  "$T5/proj" "$T5/plug"

# ──────────────────────────────────────────────────────────────────────────
# Test 6: dual_install + divergent_content ONLY
# Local has banner with SAME version but content differs (local customization).
# ──────────────────────────────────────────────────────────────────────────
T6=$SCRATCH/t6; mkdir -p "$T6/proj" "$T6/plug"
mk_fixture "$T6/proj" "$T6/plug" \
  "$(printf '%s\n%s\n' '#!/usr/bin/env bash' '# Aria-plugin secret-guard hook v1.24.0')" \
  "$(printf '%s\n%s\n%s\n' '#!/usr/bin/env bash' '# Aria-plugin secret-guard hook v1.24.0' '# local custom tweak')" \
  "1.24.0" "__MISSING__"
run_case "6: dual_install + divergent_content only (same version, customized)" \
  "dual_install" '["divergent_content"]' \
  "$T6/proj" "$T6/plug"

# ──────────────────────────────────────────────────────────────────────────
# Test 7: corrupted_settings (precedence over all other state)
# Even with dual install, malformed settings.json forces corrupted_settings.
# ──────────────────────────────────────────────────────────────────────────
T7=$SCRATCH/t7; mkdir -p "$T7/proj" "$T7/plug"
mk_fixture "$T7/proj" "$T7/plug" \
  "$(printf '%s\n%s\n' '#!/usr/bin/env bash' '# Aria-plugin secret-guard hook v1.24.0')" \
  "$(printf '%s\n%s\n' '#!/usr/bin/env bash' '# Aria-plugin secret-guard hook v1.24.0')" \
  "1.24.0" \
  '{ this is: not, valid: json (((['
run_case "7: corrupted_settings (precedence over dual_install)" \
  "corrupted_settings" "[]" \
  "$T7/proj" "$T7/plug"

# ──────────────────────────────────────────────────────────────────────────
# Test 8: dual_install + divergent_content (BANNER-MISSING edge case)
# R2 QA NF2 closure: local copy has NO banner (current SilkNode HEAD reality).
# Expected: stale_local_version NOT set (undefined version → skip the check),
# only divergent_content fires via SHA256 compare.
# ──────────────────────────────────────────────────────────────────────────
T8=$SCRATCH/t8; mkdir -p "$T8/proj" "$T8/plug"
mk_fixture "$T8/proj" "$T8/plug" \
  "$(printf '%s\n%s\n' '#!/usr/bin/env bash' '# Aria-plugin secret-guard hook v1.24.0')" \
  "$(printf '%s\n%s\n' '#!/usr/bin/env bash' '# PreToolUse hook (no version banner — SilkNode HEAD shape)')" \
  "1.24.0" "__MISSING__"
run_case "8: dual_install + divergent_content (banner-missing edge, NO stale flag) [R2 QA NF2]" \
  "dual_install" '["divergent_content"]' \
  "$T8/proj" "$T8/plug"
# Additional assertion: stale_local_version must NOT be set + local_version must be null
out8=$(bash "$CHECK_SCRIPT" "$T8/proj" "$T8/plug" 2>/dev/null)
stale8=$(printf '%s' "$out8" | jq -r '.sub_flags | index("stale_local_version")')
ver8=$(printf '%s' "$out8" | jq -r '.details.local_version')
if [ "$stale8" = "null" ] && [ "$ver8" = "null" ]; then
  : # OK: stale_local_version absent, local_version null
else
  fail=$((fail + 1))
  failures+=("FAIL [8-NF2: banner-missing must yield local_version=null + no stale_local_version flag | got stale_index=$stale8 ver=$ver8 out=$out8]")
  pass=$((pass - 1))
fi

# ── Summary ───────────────────────────────────────────────────────────────
total=$((pass + fail))
echo
echo "──────────────────────────────────────────────────"
echo "check_secret_guard_install.sh unit tests"
echo "PASS: $pass / $total"
echo "FAIL: $fail / $total"
if [ "$fail" -gt 0 ]; then
  echo
  echo "Failures:"
  printf '  %s\n' "${failures[@]}"
  echo
  exit 1
fi
exit 0

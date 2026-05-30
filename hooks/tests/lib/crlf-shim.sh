#!/usr/bin/env bash
# crlf-shim.sh — reusable cross-platform CRLF test framework (single SoT).
#
# Source: source "$(dirname "$0")/lib/crlf-shim.sh"
# Purpose: faithfully reproduce on Linux/macOS CI the Windows-native-jq CRLF
#          behaviour that caused Forgejo Aria #132 (secret-guard fail-closed)
#          and its sibling sites (shell-jq-crlf-hardening Spec).
#
# Windows native jq builds emit CRLF on every output line. Bash consumers strip
# only the trailing \n: `readarray -t` keeps \r on every field; `$(…)` keeps a
# trailing \r on single values. This framework injects that \r via a PATH shim
# that wraps the real jq and re-appends \r to each output line (awk).
#
# Two consumption shapes are covered (Spec R1 M1 — they differ in CR placement):
#   1. readarray-pipe :  readarray -t v < <(jq … )       → \r on each of N lines
#   2. command-subst  :  v=$(… | jq …)  /  v=$(jq …)     → \r on the single value
#
# Anti-vacuity is first-class (Spec R1 C1 / R2): every primitive is BIDIRECTIONAL
# — it asserts the bug-state WITHOUT the shim/fix as well as the fixed-state WITH
# it, so a test that only ever passes (hollow) is caught.
#
# This library has NO global side effects on source; callers create/destroy the
# shim explicitly. All temp state lives under a per-call mktemp dir.

# ── shim lifecycle ──────────────────────────────────────────────────────────

# crlf_shim_create → echoes a dir path containing a CRLF-emitting `jq` shim.
# Prepend it to PATH to make any `jq` invocation emit CRLF. Caller must pass the
# returned dir to crlf_shim_destroy when done.
crlf_shim_create() {
  local real_jq shim_dir
  real_jq="$(command -v jq)"
  if [[ -z "$real_jq" ]]; then
    echo "crlf-shim: FATAL real jq not found on PATH" >&2
    return 3
  fi
  shim_dir="$(mktemp -d)"
  # awk re-appends \r\n to every line of real jq's stdout, simulating a
  # Windows native jq build. Real jq's args/stdin pass through untouched.
  cat > "$shim_dir/jq" <<SHIM
#!/usr/bin/env bash
"$real_jq" "\$@" | awk '{ printf "%s\r\n", \$0 }'
SHIM
  chmod +x "$shim_dir/jq"
  printf '%s' "$shim_dir"
}

crlf_shim_destroy() {
  local shim_dir="$1"
  [[ -n "$shim_dir" && -d "$shim_dir" ]] && rm -rf "$shim_dir"
}

# crlf_run_with_shim <shim_dir> <command...> — run command with shim on PATH.
crlf_run_with_shim() {
  local shim_dir="$1"; shift
  PATH="$shim_dir:$PATH" "$@"
}

# ── bidirectional self-check (frame against framework's own bugs) ───────────

# crlf_selfcheck → 0 if the shim genuinely injects CR AND plain jq does not.
# Bidirectional: a one-sided check (only "shim has CR") would pass even if the
# baseline already had CR (e.g. a broken assertion). We require BOTH:
#   (a) plain jq output has NO \r   (baseline clean)
#   (b) shimmed jq output HAS  \r   (injection works)
crlf_selfcheck() {
  local shim_dir="$1" plain shimmed
  plain="$(printf '%s' '{}' | jq -rn '"x"' | od -An -tx1 | tr -d ' \n')"
  shimmed="$(printf '%s' '{}' | crlf_run_with_shim "$shim_dir" jq -rn '"x"' | od -An -tx1 | tr -d ' \n')"
  if [[ "$plain" == *0d* ]]; then
    echo "crlf-shim selfcheck FAIL: baseline (no shim) already contains CR — assertions would be vacuous" >&2
    return 1
  fi
  if [[ "$shimmed" != *0d* ]]; then
    echo "crlf-shim selfcheck FAIL: shim did not inject CR — test would be vacuous" >&2
    return 1
  fi
  return 0
}

# ── consumption-shape probes (Spec R1 M1: cover both shapes) ────────────────

# crlf_shape_readarray_has_cr <shim_dir> → 0 if readarray-pipe shape retains CR.
# Mirrors secret-guard.sh:118 form. Confirms the framework reproduces the bug
# for the multi-line field-split consumption shape.
crlf_shape_readarray_has_cr() {
  local shim_dir="$1" first
  readarray -t _crlf_f < <(PATH="$shim_dir:$PATH" jq -rn '"string", "Bash"')
  first="${_crlf_f[0]:-}"
  unset _crlf_f
  [[ "$(printf '%s' "$first" | od -An -tx1 | tr -d ' \n')" == *0d* ]]
}

# crlf_shape_cmdsubst_has_cr <shim_dir> → 0 if command-subst shape retains CR.
# Mirrors secret-scan.sh:116 / setup_relay.sh form. `$()` strips trailing \n but
# keeps \r, so the single value carries a trailing CR.
crlf_shape_cmdsubst_has_cr() {
  local shim_dir="$1" v
  v="$(PATH="$shim_dir:$PATH" jq -rn '"string"')"
  [[ "$(printf '%s' "$v" | od -An -tx1 | tr -d ' \n')" == *0d* ]]
}

# ── two-state (anti-vacuity) assertion for silent-bypass sites ──────────────

# crlf_make_pristine_copy <script> <sed_expr> → echoes path to a temp copy of
# <script> with the fix removed via <sed_expr> (e.g. strip "| tr -d '\r'").
# Used to reproduce the pre-fix bug under the shim. Caller rm's the copy.
crlf_make_pristine_copy() {
  local script="$1" sed_expr="$2" tmp
  tmp="$(mktemp)"
  sed "$sed_expr" "$script" > "$tmp"
  chmod +x "$tmp"
  printf '%s' "$tmp"
}

# crlf_assert_two_state <label> <pristine_outcome> <fixed_outcome>
#   <pristine_outcome>/<fixed_outcome>: caller-computed booleans as strings
#     "bug" (bug reproduced / undesired behaviour) or "ok" (desired behaviour).
# Asserts the two states FLIP (pristine="bug", fixed="ok"). If they are equal,
# the test is hollow (the shim/fix had no effect) → FAIL.
# Returns 0 on confirmed flip, 1 otherwise. Prints a diagnostic on failure.
crlf_assert_two_state() {
  local label="$1" pristine="$2" fixed="$3"
  if [[ "$pristine" == "bug" && "$fixed" == "ok" ]]; then
    return 0
  fi
  echo "crlf two-state FAIL [$label]: expected pristine=bug→fixed=ok, got pristine=$pristine fixed=$fixed (hollow if equal)" >&2
  return 1
}

#!/usr/bin/env bash
# Regression test for secret-scan.sh PostToolUse hook (warn-only detector).
#
# Run: bash aria/hooks/tests/secret-scan.test.sh  (from aria-plugin repo root)
# Asserts: known-secret inputs make the hook EMIT a detection warning
#          (stdout JSON with .hookSpecificOutput.additionalContext + .systemMessage,
#          and NO tool_response mutation — the hook cannot redact);
#          clean inputs produce no detection warning (pass through silently).
#
# The hook is warn-only: it DETECTS secret-shaped content and warns via the
# PostToolUse channels Claude Code honors. It does NOT (and architecturally
# cannot) rewrite tool_response — so tests assert on the warning, never on a
# mutated output body.

set -u

HOOK="$(dirname "$0")/../secret-scan.sh"
pass=0
fail=0
failures=()

# Helper: build PostToolUse JSON envelope with given output content.
build_post() {
  local tool="$1" content="$2"
  jq -n --arg t "$tool" --arg c "$content" \
    '{tool_name: $t, tool_input: {}, tool_response: {output: $c}}'
}
build_post_read() {
  local content="$1"
  jq -n --arg c "$content" \
    '{tool_name: "Read", tool_input: {file_path: "/tmp/x"}, tool_response: {content: $c}}'
}

# `expect_detect <name> <expect_tag> <content>`: assert the hook EMITS a
# detection warning on stdout —
#   (1) stdout is valid JSON with BOTH .hookSpecificOutput.additionalContext
#       AND .systemMessage present (per AC-1, both channels required);
#   (2) the reported breakdown (carried in systemMessage) names <expect_tag>,
#       proving the specific pattern fired (detection-coverage preserved);
#   (3) stdout JSON has NO .tool_response key — warn-only hooks never mutate
#       tool output (structural absence of any redaction/mutation).
expect_detect() {
  local name="$1" expect_tag="$2" content="$3"
  local tmp_stdout tmp_stderr
  tmp_stdout="$(mktemp)" tmp_stderr="$(mktemp)"
  build_post "Bash" "$content" | "$HOOK" >"$tmp_stdout" 2>"$tmp_stderr"
  local stdout_out; stdout_out="$(cat "$tmp_stdout")"
  rm -f "$tmp_stdout" "$tmp_stderr"

  local addl sysmsg has_tr
  addl="$(printf '%s' "$stdout_out" | jq -r '.hookSpecificOutput.additionalContext // empty' 2>/dev/null)"
  sysmsg="$(printf '%s' "$stdout_out" | jq -r '.systemMessage // empty' 2>/dev/null)"
  has_tr="$(printf '%s' "$stdout_out" | jq -r 'has("tool_response")' 2>/dev/null)"

  # (1) both warning channels present
  if [[ -z "$addl" || -z "$sysmsg" ]]; then
    fail=$((fail + 1))
    failures+=("FAIL [$name]: missing additionalContext/systemMessage — stdout: $(printf '%s' "$stdout_out" | tr '\n' ' ' | head -c 200)")
    return
  fi
  # (2) breakdown names the expected tag
  if ! printf '%s' "$sysmsg" | grep -q -- "$expect_tag"; then
    fail=$((fail + 1))
    failures+=("FAIL [$name]: systemMessage missing tag=$expect_tag — sysmsg: $(printf '%s' "$sysmsg" | head -c 200)")
    return
  fi
  # (3) NO tool_response mutation key (warn-only never rewrites output)
  if [[ "$has_tr" != "false" ]]; then
    fail=$((fail + 1))
    failures+=("FAIL [$name]: stdout unexpectedly has tool_response key (warn-only hook must not mutate tool output)")
    return
  fi
  pass=$((pass + 1))
}

# `expect_pass <name> <input>`: assert hook is silent — emits NO detection
# warning (no additionalContext on stdout) on clean input.
expect_pass() {
  local name="$1" content="$2"
  local stdout_out addl
  stdout_out="$(build_post "Bash" "$content" | "$HOOK" 2>/dev/null)"
  addl="$(printf '%s' "$stdout_out" | jq -r '.hookSpecificOutput.additionalContext // empty' 2>/dev/null)"
  if [[ -n "$addl" ]]; then
    fail=$((fail + 1))
    failures+=("FAIL [$name]: false-positive detection on clean input — additionalContext: $(printf '%s' "$addl" | head -c 200)")
  else
    pass=$((pass + 1))
  fi
}

# ── DETECTION cases (per-pattern / per-tag coverage — validates real detection) ──

expect_detect "PEM private key (single line)"  "pem-private-key-block"  "snippet: -----BEGIN RSA PRIVATE KEY----- MIIE... -----END RSA PRIVATE KEY-----"
# R3 audit NEW-I-1: multi-line PEM body must also be fully detected (not just BEGIN header)
expect_detect "PEM private key (multi-line body)" "pem-private-key-block" "$(printf -- '-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEArandomBase64BodyAcrossManyLines\nMoreBase64Body\nMoreLines\n-----END RSA PRIVATE KEY-----')"

# R3 audit C-1 + C-2: PGP block + encrypted PEM with hyphen-bearing headers
expect_detect "PGP private key BLOCK" "pem-private-key-block" "$(printf -- '-----BEGIN PGP PRIVATE KEY BLOCK-----\nVersion: GnuPG v2\n\nsecretPGPbodyAcrossLines\nMoreBase64\n-----END PGP PRIVATE KEY BLOCK-----')"
expect_detect "encrypted PEM (Proc-Type+DEK-Info)" "pem-private-key-block" "$(printf -- '-----BEGIN RSA PRIVATE KEY-----\nProc-Type: 4,ENCRYPTED\nDEK-Info: AES-256-CBC,1234567890ABCDEF\n\nencryptedbase64bodySECRET\n-----END RSA PRIVATE KEY-----')"
expect_detect "OPENSSH PEM block" "pem-private-key-block" "$(printf -- '-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAABG5vbmU\nopensshSECRETbody\n-----END OPENSSH PRIVATE KEY-----')"
expect_detect "JWT token"            "jwt"                 "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
expect_detect "SilkNode API key"     "silknode-api-key"    "API key: sk-silk-FAKEFIXTUREPLEASEDoNotDetectMeABCDEFGH01234567890123456789"
expect_detect "OpenAI sk-proj key"   "openai-api-key"      "OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyzABCDEFGHIJ12345678"
expect_detect "Anthropic key"        "anthropic-api-key"   "ANTHROPIC_API_KEY=sk-ant-api03-aBcDeFgHiJkLmNoPqRsTuVwXyZabcdefghijklmnop_-_QR"
expect_detect "Stripe live secret"   "stripe-live-secret"  "STRIPE_SECRET_KEY=sk_live_51HabcXYZdefGHIjklMNOpqr"
expect_detect "Stripe webhook"       "stripe-webhook"      "STRIPE_WEBHOOK_SECRET=whsec_abc123XYZdef456GHI789"
expect_detect "GitHub PAT"           "github-pat"          "Token: ghp_FAKEFIXTUREPLEASEDoNotDetectMeABCD00"
expect_detect "GitLab PAT"           "gitlab-pat"          "GITLAB_TOKEN=glpat-aBcDeFgHiJkLmNoPqRsT"
expect_detect "AWS access key"       "aws-access-key-id"   "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"
expect_detect "Aliyun AK"            "aliyun-access-key-id" "OSS_ACCESS_KEY_ID=LTAI5tF5ZVYwy1cgwgYpiPtJ"
expect_detect "Discord webhook"      "discord-webhook"     "https://discord.com/api/webhooks/123456789012345678/aBcDeFgHiJkLmNoPqRsTuVwXyZ"
expect_detect "Slack webhook"        "slack-webhook"       "https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXX"
expect_detect "Postgres URL"         "postgres-url"        "DATABASE_URL=postgresql://luxeno:abc123XYZ@prod-db:5432/luxeno_prod"
expect_detect "Redis URL"            "redis-url"           "REDIS_URL=redis://default:secretpass123@redis:6379"
expect_detect "MongoDB URL"          "mongodb-url"         "MONGO_URL=mongodb+srv://admin:mongopass456@cluster0.example.net/db"
expect_detect "Basic auth URL"       "basic-auth-url"      "curl https://admin:supersecret123@internal.example.com/api"
expect_detect "Bearer token"         "bearer-token"        "curl -H 'Authorization: Bearer ya29.aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789' ..."
expect_detect "X-API-Key header"     "x-api-key-header"    "curl -H 'X-API-Key: abc123XYZdef456GHI789'"
expect_detect "env-line SECRET kw"   "env-line-secret-keyword" "NEXTAUTH_SECRET=8A4z5ifo7jMghdmu0LQ_u4NGOVEFueOZ8MjOSyUldM"
expect_detect "JSON password field"  "json-secret-field"   '{"username":"admin","password":"verysecret123!"}'
expect_detect "JSON api_key field"   "json-secret-field"   '{"data":{"api_key":"abc123XYZdef456"}}'
expect_detect "bcrypt hash"          "bcrypt-hash"         "password_hash=\$2b\$12\$abcdefghijklmnopqrstuvabcdefghijklmnopqrstuvwxyzABCDE"
expect_detect "GCP private_key_id"   "gcp-private-key-id"  '{"type":"service_account","private_key_id":"abc123def456789012345678901234567890abcd"}'

# ── PASS-THROUGH cases (no secret, no false-positive) ──────────────────────

expect_pass "plain ls output"        "$(printf 'README.md\npackage.json\nweb/\nload-tests/')"
expect_pass "git log output"         "$(printf 'commit abc123\nAuthor: Simon\nDate: 2026-05-17\n\n  fix: typo')"
expect_pass "non-secret env line"    "NODE_ENV=production"
expect_pass "build output"           "$(printf 'Compiled successfully.\n203 modules emitted.\nBuild time: 4.3s')"
expect_pass "version string"         "v1.2.3-build.abc123"
expect_pass "git SHA"                "commit 74e0550 (HEAD -> main)"
expect_pass "short hex hash"         "Hash: deadbeef"
expect_pass "URL no auth"            "Visit https://luxeno.ai/docs for more"
expect_pass "code snippet"           "function foo() { return 42; }"
expect_pass "user mentions secret"   "The user_secret column was renamed in migration 20260201."
expect_pass "fake low-entropy pass"  "password=hunter2"   # too short for env-line-secret-keyword

# ── EDGE cases ─────────────────────────────────────────────────────────────

# Empty content
expect_pass "empty output"           ""

# Read tool with secret content → detection warning present + tag named.
read_stdout="$(build_post_read "DATABASE_URL=postgresql://luxeno:abc123XYZ@prod-db:5432/luxeno_prod" | "$HOOK" 2>/dev/null)"
read_addl="$(printf '%s' "$read_stdout" | jq -r '.hookSpecificOutput.additionalContext // empty' 2>/dev/null)"
read_sys="$(printf '%s' "$read_stdout" | jq -r '.systemMessage // empty' 2>/dev/null)"
if [[ -n "$read_addl" && -n "$read_sys" ]] && printf '%s' "$read_sys" | grep -q "postgres-url"; then
  pass=$((pass + 1))
else
  fail=$((fail + 1))
  failures+=("FAIL [Read tool with secret content]: expected detection warning naming postgres-url, got: $(printf '%s' "$read_stdout" | tr '\n' ' ' | head -c 200)")
fi

# Multiple matches in one output → detection count >= 2 (in additionalContext).
multi="STRIPE=sk_live_aaaaaaaaaaaaaaaaaaaa
NEXTAUTH_SECRET=abc123XYZdef456GHI789"
multi_stdout="$(build_post "Bash" "$multi" | "$HOOK" 2>/dev/null)"
multi_addl="$(printf '%s' "$multi_stdout" | jq -r '.hookSpecificOutput.additionalContext // empty' 2>/dev/null)"
if printf '%s' "$multi_addl" | grep -qE 'DETECTED [0-9]+ secret-shape'; then
  num="$(printf '%s' "$multi_addl" | grep -oE 'DETECTED [0-9]+' | grep -oE '[0-9]+')"
  if [[ "$num" -ge 2 ]]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    failures+=("FAIL [Multiple matches]: expected >=2, got $num")
  fi
else
  fail=$((fail + 1))
  failures+=("FAIL [Multiple matches]: no DETECTED count found in additionalContext — stdout: $(printf '%s' "$multi_stdout" | tr '\n' ' ' | head -c 200)")
fi

# AC-7: exit-0-on-match — hook exits 0 even when it detects a secret.
build_post "Bash" "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE" | "$HOOK" >/dev/null 2>&1
match_exit=$?
if [[ "$match_exit" == "0" ]]; then
  pass=$((pass + 1))
else
  fail=$((fail + 1))
  failures+=("FAIL [exit-0-on-match]: want exit 0 on detection, got $match_exit")
fi

# AC-7: jq-missing path — with jq absent from PATH the hook fails open (exit 0)
# and emits the "detection skipped" warning (NOT any "redact"/"UNREDACTED" text).
jq_stub_dir="$(mktemp -d)"
ln -sf "$(command -v bash)" "$jq_stub_dir/bash" 2>/dev/null
jq_missing_combined="$(build_post "Bash" "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE" | PATH="$jq_stub_dir" "$HOOK" 2>&1; echo "exit=$?")"
rm -rf "$jq_stub_dir"
jq_missing_exit="${jq_missing_combined##*exit=}"
jq_missing_msg="${jq_missing_combined%exit=*}"
if [[ "$jq_missing_exit" == "0" ]] && printf '%s' "$jq_missing_msg" | grep -qi "detection skipped"; then
  pass=$((pass + 1))
else
  fail=$((fail + 1))
  failures+=("FAIL [jq-missing path]: want exit 0 + 'detection skipped' warning, got exit=$jq_missing_exit msg=$(printf '%s' "$jq_missing_msg" | tr '\n' ' ' | head -c 200)")
fi

# Large output > 1MB → skipped with NOTE
# Use python to build JSON (avoid bash ARG_MAX limit when constructing fixture).
tmpbig="$(mktemp)"
python3 -c "
import json, sys
content = 'harmless line ' * 80000   # ~1.1 MB
sys.stdout.write(json.dumps({'tool_name':'Bash','tool_input':{},'tool_response':{'output':content}}))
" > "$tmpbig"
stderr_out="$(cat "$tmpbig" | "$HOOK" 2>&1 >/dev/null)"
rm -f "$tmpbig"
if echo "$stderr_out" | grep -q "exceeds 1MB cap"; then
  pass=$((pass + 1))
else
  fail=$((fail + 1))
  failures+=("FAIL [size cap]: expected NOTE about 1MB cap, got: $(echo "$stderr_out" | head -c 200)")
fi

# Malformed JSON → silent pass-through
stderr_out="$(echo 'not json' | "$HOOK" 2>&1 >/dev/null; echo "exit=$?")"
exit_code="${stderr_out##*exit=}"
if [[ "$exit_code" == "0" ]]; then
  pass=$((pass + 1))
else
  fail=$((fail + 1))
  failures+=("FAIL [malformed JSON]: want exit 0, got $exit_code")
fi

# ──────────────────────────────────────────────────────────────────────────
# #132 follow-up (shell-jq-crlf-hardening TASK-003): CRLF regression.
# Windows native jq emits CRLF. The tool_type type-check at secret-scan.sh is
# `[[ "$tool_type" != "string" ]] && exit 0` — under CRLF, tool_type becomes
# "string\r", the gate trips, and the hook silently exits WITHOUT detecting
# (silent secret leak goes unwarned, Spec T1). Uses the shared CRLF framework.
# The detection signal is now the stderr "DETECTED ..." summary.
# ──────────────────────────────────────────────────────────────────────────
source "$(dirname "$0")/lib/crlf-shim.sh"
crlf_shim="$(crlf_shim_create)"

# Framework self-check (bidirectional) — guards against a vacuous shim.
if crlf_selfcheck "$crlf_shim" 2>/dev/null; then
  pass=$((pass + 1))
else
  fail=$((fail + 1)); failures+=("FAIL [crlf shim selfcheck]")
fi

# Bidirectional non-vacuous (Spec C1): pristine copy = tool_type CR-strip removed.
crlf_secret='AKIAIOSFODNN7EXAMPLE'
crlf_input="$(build_post "Bash" "config has $crlf_secret embedded")"
crlf_pristine="$(crlf_make_pristine_copy "$HOOK" '/would fail the type gate below/d')"
# (a) pristine (no fix) under CRLF shim → expect silent bypass (no DETECTED)
pristine_err="$(printf '%s' "$crlf_input" | crlf_run_with_shim "$crlf_shim" bash "$crlf_pristine" 2>&1 >/dev/null)"
echo "$pristine_err" | grep -q "DETECTED" && crlf_pristine_state="ok" || crlf_pristine_state="bug"
# (b) fixed under CRLF shim → expect detection restored
fixed_err="$(printf '%s' "$crlf_input" | crlf_run_with_shim "$crlf_shim" bash "$HOOK" 2>&1 >/dev/null)"
echo "$fixed_err" | grep -q "DETECTED" && crlf_fixed_state="ok" || crlf_fixed_state="bug"
if crlf_assert_two_state "secret-scan CRLF silent-bypass" "$crlf_pristine_state" "$crlf_fixed_state" 2>/dev/null; then
  pass=$((pass + 1))
else
  fail=$((fail + 1)); failures+=("FAIL [secret-scan CRLF bypass two-state]: pristine=$crlf_pristine_state fixed=$crlf_fixed_state (want bug->ok)")
fi
rm -f "$crlf_pristine"

# content / warn-only structure (AC-3 rework): under warn-only the hook emits NO
# tool_response mutation, so the old `jq '.tool_response.output'` fidelity check
# was vacuous. Assert instead: (1) the hook's stdout JSON has NO tool_response
# key (structural absence of any output-mutation) AND (2) detection still fires
# on CR-containing content (additionalContext warning present for input with a
# CR + a secret). This is a detection test, not a mutation-fidelity test.
fidelity_content="$(printf 'alpha\rbeta has AKIAIOSFODNN7EXAMPLE token\rgamma')"
fidelity_stdout="$(build_post "Bash" "$fidelity_content" | "$HOOK" 2>/dev/null)"
fidelity_has_tr="$(printf '%s' "$fidelity_stdout" | jq -r 'has("tool_response")' 2>/dev/null)"
fidelity_addl="$(printf '%s' "$fidelity_stdout" | jq -r '.hookSpecificOutput.additionalContext // empty' 2>/dev/null)"
if [[ "$fidelity_has_tr" == "false" && -n "$fidelity_addl" ]]; then
  pass=$((pass + 1))
else
  fidelity_addl_present="$([[ -n "$fidelity_addl" ]] && echo yes || echo no)"
  fail=$((fail + 1)); failures+=("FAIL [secret-scan CR content detection]: has_tool_response=$fidelity_has_tr detection_present=$fidelity_addl_present (want no tool_response key + detection fires)")
fi

crlf_shim_destroy "$crlf_shim"

# ── Summary ────────────────────────────────────────────────────────────────
total=$((pass + fail))
echo
echo "──────────────────────────────────────────────────"
echo "secret-scan.sh regression test"
echo "PASS: $pass / $total"
echo "FAIL: $fail / $total"
if [[ $fail -gt 0 ]]; then
  echo
  echo "Failures:"
  printf '  %s\n' "${failures[@]}"
  echo
  exit 1
fi
exit 0

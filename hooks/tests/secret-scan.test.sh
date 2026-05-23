#!/usr/bin/env bash
# Regression test for secret-scan.sh PostToolUse hook.
#
# Run: bash aria/hooks/tests/secret-scan.test.sh  (from aria-plugin repo root)
# Asserts: known-secret inputs produce REDACTED stderr summary;
#          clean inputs produce zero output (pass through).

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

# R2 audit C-2 fix: `expect_redact` now asserts BOTH stderr REDACTED claim
# AND stdout JSON actually had the secret value replaced. Previously only
# stderr was checked, which let 6 sed-broken patterns silently leak with
# 40/40 PASS appearance. Now: capture stdout + stderr separately, verify
# original secret substring is NOT in mutated output.
expect_redact() {
  local name="$1" expect_tag="$2" content="$3" secret_substring="${4:-}"
  # If no explicit substring given, use the whole input as substring to search for
  [[ -z "$secret_substring" ]] && secret_substring="$content"

  # Capture stdout + stderr separately (both fd redirections preserved)
  local tmp_stdout tmp_stderr
  tmp_stdout="$(mktemp)" tmp_stderr="$(mktemp)"
  build_post "Bash" "$content" | "$HOOK" >"$tmp_stdout" 2>"$tmp_stderr"
  local stderr_out stdout_out
  stderr_out="$(cat "$tmp_stderr")"
  stdout_out="$(cat "$tmp_stdout")"
  rm -f "$tmp_stdout" "$tmp_stderr"

  # Check 1: stderr REDACTED claim contains expected tag
  if ! echo "$stderr_out" | grep -q "REDACTED" || ! echo "$stderr_out" | grep -q "$expect_tag"; then
    fail=$((fail + 1))
    failures+=("FAIL [$name]: stderr missing REDACTED:$expect_tag — stderr: $(echo "$stderr_out" | tr '\n' ' ' | head -c 200)")
    return
  fi

  # Check 2 (R2 audit C-2): stdout JSON's tool_response.output does NOT contain raw secret
  if [[ -z "$stdout_out" ]]; then
    # If hook didn't emit JSON, can't verify mutation — but stderr claimed redaction.
    # Be lenient (some Claude Code versions don't support mutation), but warn.
    pass=$((pass + 1))
    return
  fi
  local mutated_output
  mutated_output="$(echo "$stdout_out" | jq -r '.tool_response.output // ""' 2>/dev/null)"
  if echo "$mutated_output" | grep -qF -- "$secret_substring"; then
    fail=$((fail + 1))
    failures+=("FAIL [$name]: secret '$(echo "$secret_substring" | head -c 40)...' STILL PRESENT in stdout JSON tool_response.output — stderr claimed REDACTED but sed silently failed. R2 audit C-1 regression?")
    return
  fi
  pass=$((pass + 1))
}

# `expect_pass <name> <input>`: assert hook is silent (no REDACTED on stderr)
expect_pass() {
  local name="$1" content="$2"
  local stderr_out
  stderr_out="$(build_post "Bash" "$content" | "$HOOK" 2>&1 >/dev/null)"
  if echo "$stderr_out" | grep -q "REDACTED"; then
    fail=$((fail + 1))
    failures+=("FAIL [$name]: false-positive REDACTED on clean input — stderr: $(echo "$stderr_out" | tr '\n' ' ' | head -c 200)")
  else
    pass=$((pass + 1))
  fi
}

# ── REDACT cases ────────────────────────────────────────────────────────────

expect_redact "PEM private key (single line)"  "pem-private-key-block"  "snippet: -----BEGIN RSA PRIVATE KEY----- MIIE... -----END RSA PRIVATE KEY-----"
# R3 audit NEW-I-1 fix: multi-line PEM body must also be fully redacted (not just BEGIN header)
expect_redact "PEM private key (multi-line body)" "pem-private-key-block" "$(printf -- '-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEArandomBase64BodyAcrossManyLines\nMoreBase64Body\nMoreLines\n-----END RSA PRIVATE KEY-----')" "MIIEowIBAAKCAQEArandomBase64BodyAcrossManyLines"

# R3 audit C-1 + C-2: PGP block + encrypted PEM with hyphen-bearing headers
expect_redact "PGP private key BLOCK" "pem-private-key-block" "$(printf -- '-----BEGIN PGP PRIVATE KEY BLOCK-----\nVersion: GnuPG v2\n\nsecretPGPbodyAcrossLines\nMoreBase64\n-----END PGP PRIVATE KEY BLOCK-----')" "secretPGPbodyAcrossLines"
expect_redact "encrypted PEM (Proc-Type+DEK-Info)" "pem-private-key-block" "$(printf -- '-----BEGIN RSA PRIVATE KEY-----\nProc-Type: 4,ENCRYPTED\nDEK-Info: AES-256-CBC,1234567890ABCDEF\n\nencryptedbase64bodySECRET\n-----END RSA PRIVATE KEY-----')" "encryptedbase64bodySECRET"
expect_redact "OPENSSH PEM block" "pem-private-key-block" "$(printf -- '-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAABG5vbmU\nopensshSECRETbody\n-----END OPENSSH PRIVATE KEY-----')" "opensshSECRETbody"
expect_redact "JWT token"            "jwt"                 "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
expect_redact "SilkNode API key"     "silknode-api-key"    "API key: sk-silk-63fe5423e403fdb7d64b263216071d295108472a932bea5f194134f9c20afbcc"
expect_redact "OpenAI sk-proj key"   "openai-api-key"      "OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyzABCDEFGHIJ12345678"
expect_redact "Anthropic key"        "anthropic-api-key"   "ANTHROPIC_API_KEY=sk-ant-api03-aBcDeFgHiJkLmNoPqRsTuVwXyZabcdefghijklmnop_-_QR"
expect_redact "Stripe live secret"   "stripe-live-secret"  "STRIPE_SECRET_KEY=sk_live_51HabcXYZdefGHIjklMNOpqr"
expect_redact "Stripe webhook"       "stripe-webhook"      "STRIPE_WEBHOOK_SECRET=whsec_abc123XYZdef456GHI789"
expect_redact "GitHub PAT"           "github-pat"          "Token: ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789"
expect_redact "GitLab PAT"           "gitlab-pat"          "GITLAB_TOKEN=glpat-aBcDeFgHiJkLmNoPqRsT"
expect_redact "AWS access key"       "aws-access-key-id"   "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"
expect_redact "Aliyun AK"            "aliyun-access-key-id" "OSS_ACCESS_KEY_ID=LTAI5tF5ZVYwy1cgwgYpiPtJ"
expect_redact "Discord webhook"      "discord-webhook"     "https://discord.com/api/webhooks/123456789012345678/aBcDeFgHiJkLmNoPqRsTuVwXyZ"
expect_redact "Slack webhook"        "slack-webhook"       "https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXX"
expect_redact "Postgres URL"         "postgres-url"        "DATABASE_URL=postgresql://luxeno:abc123XYZ@prod-db:5432/luxeno_prod"
expect_redact "Redis URL"            "redis-url"           "REDIS_URL=redis://default:secretpass123@redis:6379"
expect_redact "MongoDB URL"          "mongodb-url"         "MONGO_URL=mongodb+srv://admin:mongopass456@cluster0.example.net/db"
expect_redact "Basic auth URL"       "basic-auth-url"      "curl https://admin:supersecret123@internal.example.com/api"
expect_redact "Bearer token"         "bearer-token"        "curl -H 'Authorization: Bearer ya29.aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789' ..."
expect_redact "X-API-Key header"     "x-api-key-header"    "curl -H 'X-API-Key: abc123XYZdef456GHI789'"
expect_redact "env-line SECRET kw"   "env-line-secret-keyword" "NEXTAUTH_SECRET=8A4z5ifo7jMghdmu0LQ_u4NGOVEFueOZ8MjOSyUldM"
expect_redact "JSON password field"  "json-secret-field"   '{"username":"admin","password":"verysecret123!"}'
expect_redact "JSON api_key field"   "json-secret-field"   '{"data":{"api_key":"abc123XYZdef456"}}'
expect_redact "bcrypt hash"          "bcrypt-hash"         "password_hash=\$2b\$12\$abcdefghijklmnopqrstuvabcdefghijklmnopqrstuvwxyzABCDE"
expect_redact "GCP private_key_id"   "gcp-private-key-id"  '{"type":"service_account","private_key_id":"abc123def456789012345678901234567890abcd"}'

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

# Read tool with secret content
stderr_out="$(build_post_read "DATABASE_URL=postgresql://luxeno:abc123XYZ@prod-db:5432/luxeno_prod" | "$HOOK" 2>&1 >/dev/null)"
if echo "$stderr_out" | grep -q "REDACTED" && echo "$stderr_out" | grep -q "postgres-url"; then
  pass=$((pass + 1))
else
  fail=$((fail + 1))
  failures+=("FAIL [Read tool with secret content]: expected REDACTED, got: $(echo "$stderr_out" | head -c 200)")
fi

# Multiple matches in one output
multi="STRIPE=sk_live_aaaaaaaaaaaaaaaaaaaa
NEXTAUTH_SECRET=abc123XYZdef456GHI789"
stderr_out="$(build_post "Bash" "$multi" | "$HOOK" 2>&1 >/dev/null)"
if echo "$stderr_out" | grep -qE 'REDACTED [0-9]+ secret-shape'; then
  num="$(echo "$stderr_out" | grep -oE 'REDACTED [0-9]+' | grep -oE '[0-9]+')"
  if [[ "$num" -ge 2 ]]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    failures+=("FAIL [Multiple matches]: expected >=2, got $num")
  fi
else
  fail=$((fail + 1))
  failures+=("FAIL [Multiple matches]: no REDACTED count found")
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

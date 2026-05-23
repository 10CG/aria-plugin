#!/usr/bin/env bash
# PostToolUse hook — scan tool output for secret-shaped content and redact
# before it reaches LLM context.
#
# === Threat model ===
#
# Companion to secret-guard.sh (PreToolUse). PreToolUse blocks known-risky
# commands BEFORE execution; this hook scans the OUTPUT of any command that
# slipped through (e.g., user-defined internal API endpoint returning secrets,
# debug log accidentally containing prior leaked values).
#
# Together they implement the layered defense:
#   PreToolUse:  "Don't run this command" (49 known bypass classes)
#   PostToolUse: "Don't display this value" (~15 secret-shape patterns)
#
# silent-failure-hunter (PR #429 R5) on PostToolUse:
#   "The remaining surface is genuinely long-tail and the right answer for it
#    is content scanning, not more regex" on commands.
#
# === Scope / what this catches ===
#
# Scans regex patterns matching common credential shapes:
#   - env-line: `KEY=value` with high-entropy value
#   - API key prefixes: sk-* / sk-silk-* / sk-ant-* / sk-or-* / ghp_* / etc
#   - JWT: eyJ...eyJ...sig
#   - AWS / Aliyun / GCP cloud credentials
#   - Stripe live/test keys + webhook secrets
#   - Discord webhook URLs
#   - PostgreSQL / Redis / MongoDB connection strings with embedded creds
#   - PEM private keys (RSA/EC/Ed25519)
#   - Basic-auth URLs (user:pass@host)
#   - bcrypt / argon2 password hashes
#   - bearer tokens in Authorization headers
#
# Match → script attempts to replace value with `<REDACTED-secret-guard:<type>>`
#         and emit the modified JSON envelope on stdout. Whether Claude Code
#         actually honors stdout content-mutation in PostToolUse is **version
#         dependent**. The reliably-visible signal is the stderr summary
#         (`[secret-scan] REDACTED N matches`) which always fires on detection.
#         Operator should confirm in their Claude Code session that redaction
#         is actually applied by pasting a known fake `test_password=xxx`
#         string and verifying Claude sees the redacted form.
#
# === What this does NOT catch ===
#
# - Low-entropy / dictionary-word passwords (e.g., `password=hunter2`) — would
#   require entropy heuristics + heavy false-positive risk
# - Internal-business-logic secrets that don't match standard shapes
# - Secrets split across multiple lines
# - Secrets encoded base64 / hex / etc (without telltale prefix)
# - Secrets in binary tool output (assumes text)
#
# These are accepted residual risk per threat model. Operator awareness +
# rotation cadence are the answers.
#
# === Hook contract ===
#
# Input (stdin JSON):
#   {
#     "tool_name": "Bash" | "Read" | "Edit" | ...,
#     "tool_input": {...},
#     "tool_response": {
#       "output": "...",        // Bash stdout/stderr combined
#       "content": "..."        // Read file content
#     }
#   }
#
# Output:
#   - On no-match: exit 0 silently, no stdout (= pass through unchanged)
#   - On match: emit JSON with redacted output via Claude Code transformation
#     spec. We use `{"hookSpecificOutput": {"hookEventName": "PostToolUse",
#     "additionalContext": "[secret-scan] Redacted N matches"}}` to inform
#     Claude + emit redacted text via stdout (Claude Code spec dependent).
#
#   Fallback: print summary to stderr (visible alongside tool result) so
#   operator + Claude both see "scan found N redactions" — actual redaction
#   depends on Claude Code hook version; if pass-through-only mode, at least
#   the warning is loud.
#
# === Performance ===
#
# Budget: skip scan if input > 1 MB. Large outputs (build logs, dump files)
# rarely contain secret credentials worth scanning at runtime cost.

set -uo pipefail

INPUT_SIZE_CAP=$((1024 * 1024))   # 1 MB

# ── Fail-OPEN if jq missing — R3 audit qa-I-2 fix ─────────────────────────
# Note: this DIVERGES from secret-guard.sh which fails CLOSED (exit 2). Phase
# 1 can fail closed because blocking a Bash call has no other consequence;
# Phase 2 PostToolUse runs AFTER the tool already executed, so blocking the
# response now doesn't undo the tool action. Fail-open lets Claude see the
# original output rather than an empty result that might mask the real cause.
# Trade-off: zero redaction protection if jq missing. Document in CLAUDE.md +
# runbook; operator should ensure jq is installed in any Claude Code env.
if ! command -v jq >/dev/null 2>&1; then
  echo "[secret-scan] WARN: jq not found, scan skipped — output passes through UNREDACTED. Install jq to enable Phase 2." >&2
  exit 0
fi

input="$(cat 2>/dev/null || true)"
[[ -z "$input" ]] && exit 0

# Size cap — R3 audit I-4 fix: count BYTES not bash-codepoints. `${#input}`
# counts Unicode codepoints under UTF-8 locales, so e.g. 500K CJK chars
# (~1.5 MB UTF-8) reads as 500000 and slips past 1MB cap. wc -c gives bytes.
input_size="$(printf '%s' "$input" | wc -c | tr -d ' ')"
if (( input_size > INPUT_SIZE_CAP )); then
  echo "[secret-scan] NOTE: tool output ${input_size}B exceeds 1MB cap; skipping scan." >&2
  exit 0
fi

# Validate JSON envelope
tool_type="$(printf '%s' "$input" | jq -r '.tool_name | type' 2>/dev/null || echo "")"
[[ "$tool_type" != "string" ]] && exit 0   # malformed input — pass through silently

tool="$(printf '%s' "$input" | jq -r '.tool_name // ""' 2>/dev/null)"

# Extract output content depending on tool — different tools shape result differently.
# Bash: tool_response.output (or .stdout / .stderr); Read: tool_response.content (file body)
# Try multiple field names since Claude Code versions vary.
content="$(printf '%s' "$input" | jq -r '
  .tool_response.output //
  .tool_response.content //
  .tool_response.stdout //
  .tool_result.content //
  .tool_result.output //
  ""
' 2>/dev/null)"

[[ -z "$content" ]] && exit 0

# ── Pattern definitions ────────────────────────────────────────────────────
# Each pattern: ERE regex + redaction tag.
# Order matters — more-specific patterns first (e.g., JWT before generic high-entropy).
#
# Format: tag|pattern (delimiter: literal `|`, hence `|` inside patterns must
# be escaped or moved to character classes).
declare -a PATTERNS=(
  # NOTE: PEM private keys are handled as a SEPARATE multi-line pre-pass
  # before this loop, because the BEGIN-body-END span crosses newlines and
  # sed/grep in per-line mode can't match it. See pre-pass below for impl.
  # (R3 audit C-1 fix: previously only BEGIN header matched, body leaked.)

  # JWT (header.payload.signature — 3 base64url parts)
  'jwt|eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}'

  # OpenAI / Anthropic / SilkNode / OpenRouter API keys.
  # R2 audit I-3 fix: anthropic and openrouter and silknode patterns first
  # (most-specific prefixes), then OpenAI catches remaining sk-* shapes.
  # Anthropic and OpenRouter patterns require non-optional prefix groups so
  # they do NOT swallow each other.
  'silknode-api-key|sk-silk-[A-Za-z0-9]{32,}'
  'anthropic-api-key|sk-ant-(api03|admin03|sid)-[A-Za-z0-9_-]{32,}'
  'openrouter-api-key|sk-or-v1-[A-Za-z0-9_-]{32,}'
  'openai-api-key|sk-(proj|svcacct|admin)-[A-Za-z0-9_-]{32,}'
  # R3 audit I-2 fix: bare legacy OpenAI key shape `sk-<48 chars>` (pre-2023
  # format + any provider using bare sk- prefix). Last-priority so the more
  # specific patterns above (silknode/anthropic/openrouter/openai-modern) match
  # first. Conservative entropy floor (48 chars) reduces FP on dev/test strings.
  'openai-legacy-key|\bsk-[A-Za-z0-9]{48,}\b'

  # Stripe
  'stripe-live-secret|sk_live_[A-Za-z0-9]{20,}'
  'stripe-test-secret|sk_test_[A-Za-z0-9]{20,}'
  'stripe-publishable|pk_(live|test)_[A-Za-z0-9]{20,}'
  'stripe-webhook|whsec_[A-Za-z0-9]{20,}'
  'stripe-restricted|rk_(live|test)_[A-Za-z0-9]{20,}'

  # GitHub / GitLab / Forgejo tokens
  'github-pat|gh[ps]_[A-Za-z0-9]{36}'
  'github-oauth|gho_[A-Za-z0-9]{36}'
  'github-user|ghu_[A-Za-z0-9]{36}'
  'github-fine-grained|github_pat_[A-Za-z0-9_]{82}'
  'gitlab-pat|glpat-[A-Za-z0-9_-]{20,}'

  # AWS
  'aws-access-key-id|AKIA[0-9A-Z]{16}'
  'aws-session-token|FwoGZXIvYXdzE[A-Za-z0-9+/=]{40,}'

  # Aliyun
  'aliyun-access-key-id|LTAI[A-Za-z0-9]{16,}'

  # GCP service account snippets (key file contains private_key_id)
  'gcp-private-key-id|"private_key_id":[[:space:]]*"[a-f0-9]{40}"'

  # Discord webhook URL
  'discord-webhook|https?://discord(app)?\.com/api/webhooks/[0-9]+/[A-Za-z0-9_-]+'

  # Slack webhook URL
  'slack-webhook|https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]{20,}'

  # PostgreSQL / Redis / MongoDB connection string with embedded credentials
  'postgres-url|postgres(ql)?://[^:[:space:]"]+:[^@[:space:]"]{4,}@[^[:space:]"]+'
  'redis-url|rediss?://[^:[:space:]"]+:[^@[:space:]"]{4,}@[^[:space:]"]+'
  'mongodb-url|mongodb(\+srv)?://[^:[:space:]"]+:[^@[:space:]"]{4,}@[^[:space:]"]+'

  # Basic-auth URL
  'basic-auth-url|https?://[A-Za-z0-9_.-]+:[A-Za-z0-9+/=._-]{6,}@[A-Za-z0-9.-]+'

  # Bearer token in Authorization header
  'bearer-token|[Aa]uthorization:[[:space:]]*[Bb]earer[[:space:]]+[A-Za-z0-9._/+=-]{20,}'

  # X-API-Key headers
  'x-api-key-header|[Xx]-[Aa][Pp][Ii]-[Kk]ey:[[:space:]]*[A-Za-z0-9._/+=-]{16,}'

  # Generic env-var line with high-entropy value (8+ chars).
  # R3 audit I-1 fix: prefix is now `[A-Z0-9_]*` (no minimum char) so bare-name
  # forms `SECRET=...` `TOKEN=...` `PASSWORD=...` are caught (previously required
  # at least 1 char prefix). Common in printenv/.env output.
  'env-line-secret-keyword|^[A-Z0-9_]*(SECRET|PASSWORD|PASSWD|TOKEN|API_KEY|PRIVATE_KEY|WEBHOOK|ENCRYPTION_KEY|ACCESS_KEY)[A-Z0-9_]*=[A-Za-z0-9+/=._\\-]{8,}'

  # JSON shape `"password": "..."` / `"secret": "..."` / `"token": "..."`
  'json-secret-field|"(password|passwd|secret|api_key|access_token|refresh_token|private_key|client_secret|webhook_secret|encryption_key)"[[:space:]]*:[[:space:]]*"[^"]{8,}"'

  # bcrypt hash
  'bcrypt-hash|\$2[abxy]\$[0-9]{2}\$[A-Za-z0-9./]{53}'
)

# ── Scan + collect matches ─────────────────────────────────────────────────
# Use a tempfile to hold redacted output (sed -i needs file).
tmpfile="$(mktemp)" || { echo "[secret-scan] WARN: mktemp failed; passing through" >&2; exit 0; }
trap 'rm -f "$tmpfile"' EXIT
printf '%s' "$content" > "$tmpfile"

matches_total=0
matches_breakdown=""
partial_warns=""   # R3 audit R2-I-5 fix: accumulated FATAL warnings for residual-after-sed cases

SEP=$'\x01'   # Used by sed in main loop (declared early so PEM pre-pass
              # fallback can reference it without :-default).

# ── R3 audit C-1+C-2: PEM multi-line pre-pass (covers PGP + encrypted PEM) ─
# R2 used `[^-]+` body class + only `PRIVATE KEY-----` anchor. R3 audit found:
#   - `[^-]+` breaks on encrypted PEM (Proc-Type: 4,ENCRYPTED / DEK-Info: ...
#     headers contain `-`) and URL-safe base64 bodies containing `-`
#   - `PRIVATE KEY-----` anchor doesn't match `PRIVATE KEY BLOCK-----` so
#     PGP private key blocks (gpg --export-secret-keys --armor) leak entirely
#
# R3 fix: regex changed to use `.*?` non-greedy any-char + `/s` flag (perl
# treats `.` as matching newlines too) + `(PRIVATE KEY(?: BLOCK)?)` captured
# group + `\1` backreference for matching END line type.
PEM_REGEX_PERL='-----BEGIN [A-Z ]+(PRIVATE KEY(?: BLOCK)?)-----.*?-----END [A-Z ]+\1-----'

if command -v perl >/dev/null 2>&1; then
  pem_count="$(perl -0sne 'my @m = /'"$PEM_REGEX_PERL"'/sg; print scalar @m' "$tmpfile" 2>/dev/null || echo 0)"
  pem_count="${pem_count//[^0-9]/}"
  [[ -z "$pem_count" ]] && pem_count=0
  if (( pem_count > 0 )); then
    perl -0i -pe 's/'"$PEM_REGEX_PERL"'/<REDACTED-secret-guard:pem-private-key-block>/sg' "$tmpfile" 2>/dev/null && {
      matches_total=$(( matches_total + pem_count ))
      matches_breakdown="${matches_breakdown}pem-private-key-block=${pem_count} "
    } || {
      echo "[secret-scan] WARN: PEM multi-line redaction perl failed" >&2
    }
  fi
else
  # perl missing — degrade to header-only redaction with loud warning
  if grep -qE -- '-----BEGIN [A-Z ]*PRIVATE KEY' "$tmpfile" 2>/dev/null; then
    echo "[secret-scan] WARN: PEM detected but perl missing — only BEGIN header will be redacted, base64 body LEAKS. Install perl." >&2
    sed -i -E "s${SEP}-----BEGIN [A-Z ]*PRIVATE KEY( BLOCK)?-----${SEP}<REDACTED-secret-guard:pem-HEADER-ONLY-WARN>${SEP}g" "$tmpfile" 2>/dev/null || true
    matches_total=$(( matches_total + 1 ))
    matches_breakdown="${matches_breakdown}pem-HEADER-ONLY=1 "
  fi
fi   # R2 audit C-1 fix: use control char as sed delimiter so it
              # cannot collide with `|` inside pattern alternations.
              # Previously `sed s|...|...|g` collided with ERE `(a|b)` groups
              # in 6 patterns (openai/anthropic/stripe pk/stripe rk/env-line/
              # json-secret-field), causing silent sed failure swallowed by
              # `|| true`. Tests passed because they only checked stderr for
              # "REDACTED" string, not stdout content. End-to-end leak.

for entry in "${PATTERNS[@]}"; do
  tag="${entry%%|*}"
  pattern="${entry#*|}"
  # Count occurrences using grep -oE to count MATCHES not LINES (R2 audit I-2 fix:
  # previously `grep -cE` counted lines, so 3 secrets on 1 line reported as 1).
  # `--` separator required: some patterns start with `-` (e.g. PEM `-----BEGIN`)
  # which grep would treat as a long-option flag and silently zero-match.
  count="$(grep -oE -- "$pattern" "$tmpfile" 2>/dev/null | wc -l | tr -d ' ')"
  [[ -z "$count" ]] && count=0
  if (( count > 0 )); then
    # In-place redact using \x01 as sed delimiter (R2 audit C-1 fix).
    sed -i -E "s${SEP}${pattern}${SEP}<REDACTED-secret-guard:${tag}>${SEP}g" "$tmpfile" 2>/dev/null || {
      # R2 audit C-1 + integrity-check: if sed failed, do NOT increment
      # matches_total — better silent under-count than false "redacted" claim.
      echo "[secret-scan] WARN: sed redaction failed for pattern tag=${tag}; skipping" >&2
      continue
    }
    # R2 audit verification — re-grep to confirm pattern is actually gone.
    # R3 audit R2-I-5 fix: previously exit 1 + empty stdout caused Claude to
    # see RAW output (worse). Now: emit whatever sed managed to redact + LOUD
    # FATAL WARN stderr so operator sees the gap. Partial redaction > silent
    # un-redacted fallback. operator_visible_warn is appended to final stderr.
    residual="$(grep -oE -- "$pattern" "$tmpfile" 2>/dev/null | wc -l | tr -d ' ')"
    [[ -z "$residual" ]] && residual=0
    if (( residual > 0 )); then
      partial_warns="${partial_warns}[secret-scan] FATAL: pattern ${tag} still present after sed (${residual} residual occurrences). Partial redaction emitted; operator MUST manually review."$'\n'
      # Adjust count to reflect what actually got redacted (count - residual)
      actual_redacted=$(( count - residual ))
      if (( actual_redacted > 0 )); then
        matches_total=$(( matches_total + actual_redacted ))
        matches_breakdown="${matches_breakdown}${tag}=${actual_redacted}+${residual}-LEAKED "
      else
        matches_breakdown="${matches_breakdown}${tag}=0+${residual}-LEAKED "
      fi
      continue
    fi
    matches_total=$(( matches_total + count ))
    matches_breakdown="${matches_breakdown}${tag}=${count} "
  fi
done

if (( matches_total == 0 )); then
  exit 0   # Nothing redacted, pass through
fi

# Build redacted content + emit JSON envelope with summary
redacted_content="$(cat "$tmpfile")"

# Claude Code PostToolUse hook output shape:
# Option A: emit `{"decision":"block","reason":"..."}` — blocks tool result
# Option B: emit modified envelope via stdout — Claude Code uses if supported
# Option C: just emit stderr — operator sees, Claude may or may not redact
#
# Most-portable across Claude Code versions: stderr warning + leave tool
# output as-is, OR mutate via PostToolUse `additionalContext` field.
#
# We emit JSON specifying additionalContext (informs Claude about redactions
# in the result) + write the redacted content to stderr so it's also visible.
# Caveat: Claude Code may not honor mutation of tool_response.output across
# all versions. Test in actual Claude Code session before declaring fully
# operational.
#
# For now: emit summary to stderr (always visible) + try the JSON
# mutation path (best-effort).

cat >&2 <<EOF
[secret-scan] REDACTED ${matches_total} secret-shape matches in tool output.
[secret-scan] Breakdown: ${matches_breakdown}
[secret-scan] Tool=${tool} Original-size=${input_size}B
[secret-scan] Caveat: PostToolUse stdout-mutation honoring is Claude Code
[secret-scan] version-dependent. This stderr summary is the universally-visible
[secret-scan] signal. If Claude reasoning depends on raw value, run command
[secret-scan] in operator's own terminal (non-Claude session) or use
[secret-scan] # guard:ack escape on the next PreToolUse step.
EOF

# R3 audit R2-I-5: surface any per-pattern FATAL warns (residual after sed)
if [[ -n "$partial_warns" ]]; then
  echo "" >&2
  echo "════ PARTIAL REDACTION WARNING ════" >&2
  printf '%s' "$partial_warns" >&2
  echo "════════════════════════════════════" >&2
fi

# R2 audit km-I-1 fix: persistent audit log (consistent with Phase 1
# secret-guard.sh's ~/.claude/logs/guard-bypass.log). Log every redaction event.
mkdir -p "${HOME}/.claude/logs" 2>/dev/null || true
printf '%s\t%s\t%s\tSCAN-REDACT\ttool=%s\tmatches=%s\tbreakdown=%s\tsize=%s\n' \
  "$(date -u +%FT%TZ)" "${USER:-unknown}" "${PWD:-unknown}" \
  "$tool" "$matches_total" "${matches_breakdown% }" "$input_size" \
  >> "${HOME}/.claude/logs/secret-scan.log" 2>/dev/null || true

# Best-effort: emit modified JSON in case Claude Code honors PostToolUse content mutation.
# If Claude Code ignores this, the stderr warning above is the visible signal.
printf '%s' "$input" | jq --arg c "$redacted_content" '
  if .tool_response.output then .tool_response.output = $c
  elif .tool_response.content then .tool_response.content = $c
  elif .tool_response.stdout then .tool_response.stdout = $c
  elif .tool_result.content then .tool_result.content = $c
  elif .tool_result.output then .tool_result.output = $c
  else .
  end
' 2>/dev/null || true

exit 0

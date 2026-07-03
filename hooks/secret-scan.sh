#!/usr/bin/env bash
# PostToolUse hook — DETECT secret-shaped content in tool output and WARN.
#
# === What this hook does (and does NOT do) ===
#
# This is a warn-only DETECTOR. When a command's output contains secret-shaped
# content, it emits a warning through two Claude-Code-honored channels:
#   - hookSpecificOutput.additionalContext : tells Claude the output contains
#       N suspected secrets — treat as already-leaked, do not repeat the
#       value(s) in the reply, recommend rotating the affected credential(s).
#   - systemMessage                        : an operator-visible warning.
# It ALSO prints a summary to stderr and appends a line to
# ~/.claude/logs/secret-scan.log.
#
# It CANNOT redact or rewrite the tool output. A PostToolUse hook runs AFTER
# the tool result has already been produced: Claude Code exposes no field to
# replace tool_response, and hook stdout does not substitute the captured
# result (official hooks-guide line 891: "PostToolUse hooks can't undo actions
# since the tool has already executed"). This is an architectural limit, not a
# version-dependent behaviour. Detection here is a mitigation (stop Claude from
# echoing the value + prompt rotation), NOT prevention. The real prevention
# layer is the PreToolUse `secret-guard` hook, which blocks risky commands
# BEFORE they run.
#
# === Threat model ===
#
# Companion to secret-guard.sh (PreToolUse). PreToolUse blocks known-risky
# commands BEFORE execution; this hook scans the OUTPUT of any command that
# slipped through (e.g., user-defined internal API endpoint returning secrets,
# debug log accidentally containing prior leaked values).
#
# Together they implement the layered defense:
#   PreToolUse:  "Don't run this command"      (49 known bypass classes; effective prevention)
#   PostToolUse: "This output leaked a secret"  (~15 secret-shape patterns; detect + warn only)
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
# Match → the hook counts the occurrences and warns (additionalContext +
# systemMessage + stderr summary + log line). It does not alter the output.
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
#   - On no-match: exit 0 silently, no stdout.
#   - On match:    exit 0 + JSON on stdout:
#       {"hookSpecificOutput": {"hookEventName": "PostToolUse",
#         "additionalContext": "[secret-scan] DETECTED N ..."},
#        "systemMessage": "[secret-scan] Detected N ..."}
#     plus a stderr summary and a log line. NO tool_response mutation is
#     emitted — this hook cannot redact (see architectural limit above).
#
# === Performance ===
#
# Budget: skip scan if input > 1 MB. Large outputs (build logs, dump files)
# rarely contain secret credentials worth scanning at runtime cost.

set -uo pipefail

INPUT_SIZE_CAP=$((1024 * 1024))   # 1 MB

# ── Fail-OPEN if jq missing ────────────────────────────────────────────────
# Diverges from secret-guard.sh (PreToolUse) which fails CLOSED (exit 2).
# secret-guard can fail closed because blocking a Bash call before it runs has
# no downside. This PostToolUse hook runs AFTER the tool already executed, so
# there is nothing to block — it can only detect + warn. If jq is missing we
# fail open (exit 0) and skip detection rather than error out. Operator should
# ensure jq is installed in any Claude Code env so Phase 2 detection is active.
if ! command -v jq >/dev/null 2>&1; then
  echo "[secret-scan] WARN: jq not found — secret DETECTION skipped (jq missing). Install jq to enable Phase 2 detection." >&2
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
tool_type="${tool_type%$'\r'}"   # crlf-strip(#132 sibling): Windows native jq emits CRLF; $() keeps trailing \r → "string\r" would fail the type gate below and silently bypass detection (secret leak goes unwarned). Gate/comparison value → strip trailing CR (single scalar).
[[ "$tool_type" != "string" ]] && exit 0   # malformed input — pass through silently

tool="$(printf '%s' "$input" | jq -r '.tool_name // ""' 2>/dev/null)"
tool="${tool%$'\r'}"   # crlf-strip(#132 sibling): comparison/log value → strip trailing CR. NOTE: `content` below is the data body being SCANNED — deliberately NOT CR-stripped (would corrupt user content).

# Extract output content depending on tool — different tools shape result differently.
# Bash: tool_response.output (or .stdout / .stderr); Read: tool_response.content (file body)
# Try multiple field names since Claude Code versions vary.
content="$(printf '%s' "$input" | jq -r '  # crlf-ok: data body being SCANNED (internal counting scratch only) — must NOT CR-strip (would corrupt user content, Spec C2)
  .tool_response.output //
  .tool_response.content //
  .tool_response.stdout //
  .tool_result.content //
  .tool_result.output //
  ""
' 2>/dev/null)"

[[ -z "$content" ]] && exit 0

# ── Pattern definitions ────────────────────────────────────────────────────
# Each pattern: ERE regex + match tag.
# Order matters — more-specific patterns first (e.g., JWT before generic high-entropy).
#
# Format: tag|pattern (delimiter: literal `|`, hence `|` inside patterns must
# be escaped or moved to character classes).
declare -a PATTERNS=(
  # NOTE: PEM private keys are handled as a SEPARATE multi-line pre-pass
  # before this loop, because the BEGIN-body-END span crosses newlines and
  # sed/grep in per-line mode can't match it. See pre-pass below for impl.
  # (R3 audit C-1 fix: previously only BEGIN header matched, body went undetected.)

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

# ── Scan + count matches ───────────────────────────────────────────────────
# tmpfile is an INTERNAL match-counting scratch buffer: each matched span is
# replaced with a neutral sentinel (`<secret-scan-counted:TAG>`) so overlapping
# or adjacent patterns are not double-counted on subsequent passes. This buffer
# is NEVER emitted and is NEVER operator-visible — the hook is warn-only and
# does not redact or rewrite tool output. `sed -i` needs a file, hence the tmp.
tmpfile="$(mktemp)" || { echo "[secret-scan] WARN: mktemp failed; skipping detection" >&2; exit 0; }
trap 'rm -f "$tmpfile"' EXIT
printf '%s' "$content" > "$tmpfile"

matches_total=0
matches_breakdown=""
partial_warns=""   # accumulated warnings for spans that could not be isolated for exact counting

SEP=$'\x01'   # Used by sed in main loop (declared early so PEM pre-pass
              # fallback can reference it without :-default).

# ── R3 audit C-1+C-2: PEM multi-line pre-pass (covers PGP + encrypted PEM) ─
# R2 used `[^-]+` body class + only `PRIVATE KEY-----` anchor. R3 audit found:
#   - `[^-]+` breaks on encrypted PEM (Proc-Type: 4,ENCRYPTED / DEK-Info: ...
#     headers contain `-`) and URL-safe base64 bodies containing `-`
#   - `PRIVATE KEY-----` anchor doesn't match `PRIVATE KEY BLOCK-----` so
#     PGP private key blocks (gpg --export-secret-keys --armor) go undetected
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
    perl -0i -pe 's/'"$PEM_REGEX_PERL"'/<secret-scan-counted:pem-private-key-block>/sg' "$tmpfile" 2>/dev/null && {
      matches_total=$(( matches_total + pem_count ))
      matches_breakdown="${matches_breakdown}pem-private-key-block=${pem_count} "
    } || {
      echo "[secret-scan] WARN: PEM multi-line counting-pass (perl) failed" >&2
    }
  fi
else
  # perl missing — degrade to header-only DETECTION with loud warning.
  if grep -qE -- '-----BEGIN [A-Z ]*PRIVATE KEY' "$tmpfile" 2>/dev/null; then
    echo "[secret-scan] WARN: PEM private key detected but perl missing — only the BEGIN header line can be counted; multi-line body detection needs perl. Install perl for full PEM detection." >&2
    sed -i -E "s${SEP}-----BEGIN [A-Z ]*PRIVATE KEY( BLOCK)?-----${SEP}<secret-scan-counted:pem-header-only>${SEP}g" "$tmpfile" 2>/dev/null || true
    matches_total=$(( matches_total + 1 ))
    matches_breakdown="${matches_breakdown}pem-header-only=1 "
  fi
fi   # R2 audit C-1 fix: use control char as sed delimiter so it
     # cannot collide with `|` inside pattern alternations. Previously
     # `sed s|...|...|g` collided with ERE `(a|b)` groups in 6 patterns
     # (openai/anthropic/stripe pk/stripe rk/env-line/json-secret-field),
     # causing silent sed failure — which would corrupt the internal match
     # count (spans not consumed → re-counted or missed).

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
    # In-place counting-substitution using \x01 as sed delimiter (R2 audit C-1 fix).
    sed -i -E "s${SEP}${pattern}${SEP}<secret-scan-counted:${tag}>${SEP}g" "$tmpfile" 2>/dev/null || {
      # R2 audit C-1 + integrity-check: if the counting-substitution failed,
      # do NOT increment matches_total — better a silent under-count than a
      # wrong match total.
      echo "[secret-scan] WARN: counting-substitution failed for pattern tag=${tag}; skipping" >&2
      continue
    }
    # Re-grep to confirm the matched spans were consumed by the counting
    # substitution. If some remain, they could not be isolated for an exact
    # count; report the count as partial + warn (the match total may be
    # under-reported). The hook is warn-only, so this affects only counting
    # accuracy, never output content.
    residual="$(grep -oE -- "$pattern" "$tmpfile" 2>/dev/null | wc -l | tr -d ' ')"
    [[ -z "$residual" ]] && residual=0
    if (( residual > 0 )); then
      partial_warns="${partial_warns}[secret-scan] NOTE: pattern ${tag} still present after counting-substitution (${residual} span(s) could not be isolated for exact counting); match count may be under-reported."$'\n'
      # Adjust count to reflect what actually got isolated (count - residual)
      actual_counted=$(( count - residual ))
      if (( actual_counted > 0 )); then
        matches_total=$(( matches_total + actual_counted ))
        matches_breakdown="${matches_breakdown}${tag}=${actual_counted}+${residual}-uncounted "
      else
        matches_breakdown="${matches_breakdown}${tag}=0+${residual}-uncounted "
      fi
      continue
    fi
    matches_total=$(( matches_total + count ))
    matches_breakdown="${matches_breakdown}${tag}=${count} "
  fi
done

if (( matches_total == 0 )); then
  exit 0   # Nothing detected, pass through silently
fi

# ── Emit warnings ──────────────────────────────────────────────────────────
# stderr summary (always visible alongside the tool result).
cat >&2 <<EOF
[secret-scan] DETECTED ${matches_total} secret-shape matches (NOT redacted) in tool output.
[secret-scan] Breakdown: ${matches_breakdown}
[secret-scan] Tool=${tool} Original-size=${input_size}B
[secret-scan] This hook detects + warns only; it cannot redact the tool output
[secret-scan] (PostToolUse runs after the result is produced — hooks-guide 891).
[secret-scan] Treat the matched value(s) as leaked and rotate the credential(s).
[secret-scan] Real prevention = PreToolUse secret-guard (blocks risky commands).
EOF

# Surface any per-pattern partial-count warnings (spans not isolated for count).
if [[ -n "$partial_warns" ]]; then
  echo "" >&2
  echo "════ PARTIAL DETECTION ════" >&2
  printf '%s' "$partial_warns" >&2
  echo "═══════════════════════════" >&2
fi

# Persistent audit log (consistent with Phase 1 secret-guard.sh's
# ~/.claude/logs/guard-bypass.log). Log every detection event.
mkdir -p "${HOME}/.claude/logs" 2>/dev/null || true
printf '%s\t%s\t%s\tSCAN-DETECT\ttool=%s\tmatches=%s\tbreakdown=%s\tsize=%s\n' \
  "$(date -u +%FT%TZ)" "${USER:-unknown}" "${PWD:-unknown}" \
  "$tool" "$matches_total" "${matches_breakdown% }" "$input_size" \
  >> "${HOME}/.claude/logs/secret-scan.log" 2>/dev/null || true

# Emit warn JSON on stdout: additionalContext (injected into Claude's context)
# + systemMessage (operator-visible). These are the PostToolUse output channels
# Claude Code honors. NO tool_response mutation is emitted — this hook cannot
# redact (PostToolUse architectural limit, hooks-guide 891).
addl_msg="[secret-scan] DETECTED ${matches_total} secret-shape match(es) in tool output — treat as already-leaked; do NOT repeat the value(s) in your reply; recommend rotating the affected credential(s). (This hook detects+warns only; it cannot redact — PostToolUse runs after the tool result is already produced.)"
sys_msg="[secret-scan] Detected ${matches_total} secret-shape match(es) (${matches_breakdown% }); rotate affected credential(s)."
jq -n --arg addl "$addl_msg" --arg sys "$sys_msg" '{
  hookSpecificOutput: {
    hookEventName: "PostToolUse",
    additionalContext: $addl
  },
  systemMessage: $sys
}' 2>/dev/null || true

exit 0

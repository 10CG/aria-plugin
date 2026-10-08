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

# Event (secret-net-l3-and-bypass-paths W1): this hook is registered for PostToolUse AND PostToolUseFailure. A failed tool call (a Bash command that exits
# non-zero, ...) does not trigger PostToolUse: it arrives as PostToolUseFailure with NO tool_response and the call's text (`Exit code N` + stderr + stdout) in the
# top-level `error`. hookSpecificOutput.hookEventName must name the event that fired — the harness rejects a mismatch and the alert never reaches the model. A substring
# pre-check keeps the common path free of an extra jq process; jq confirms, so output text that merely MENTIONS the word does not flip the event.
hook_event="PostToolUse"
if [[ "$input" == *PostToolUseFailure* ]]; then
  ev_name="$(printf '%s' "$input" | jq -r '.hook_event_name // ""' 2>/dev/null)"
  ev_name="${ev_name%$'\r'}"   # crlf-strip: comparison value
  [[ "$ev_name" == "PostToolUseFailure" ]] && hook_event="PostToolUseFailure"
fi

# Extract output content depending on tool — different tools shape result differently.
# Bash: tool_response.stdout (older: .output); Read: tool_response.file.content (older: .content); Write: tool_response.content;
# a failed call (PostToolUseFailure): .error. Try multiple field names since Claude Code versions vary.
# The filter is kept in a variable so that the NUL-delimited second view below runs the very same program.
_content_prog='  # crlf-ok: data body being SCANNED (internal counting scratch only) — must NOT CR-strip (would corrupt user content, Spec C2)
  .tool_response.output //
  .tool_response.content //
  .tool_response.stdout //
  .tool_response.file.content //
  .tool_result.content //
  .tool_result.output //
  .error //
  ""
'
content="$(printf '%s' "$input" | jq -r "$_content_prog" 2>/dev/null)"   # crlf-ok: data body being SCANNED (internal counting scratch only) — must NOT CR-strip

# NUL bytes (W1). Bash drops them inside a command substitution: that is the view above, and why text with a NUL after every character (UTF-16LE shown by a tool)
# scans as the ASCII it spells. A NUL-DELIMITED body (/proc/<pid>/environ, `env -0`) is glued into one line by that view, so `KEY=value` records lose their line
# starts. When the raw envelope holds a JSON \u0000 escape (one string comparison; no extra process otherwise) a SECOND view is appended: the same extraction with
# NUL -> newline. It is appended only when it differs from the first, so input without a real NUL is scanned exactly as before (a text that merely MENTIONS the six
# characters \u0000 leaves the two views equal). Any transformation of the input must be a superset of what the baseline view detects — hence a second view, not a replacement.
if [[ "$input" == *'\u0000'* ]]; then
  nul_view="$(printf '%s' "$input" | jq -r "$_content_prog" 2>/dev/null | tr '\000' '\n')"   # crlf-ok: data body being SCANNED (same filter, NUL -> newline)
  [[ -n "$nul_view" && "$nul_view" != "$content" ]] && content="${content}"$'\n'"${nul_view}"
fi

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

  # ── W2 (secret-net-l3-and-bypass-paths): six generic key-shape tags, in THIS order (the order is the fingerprint traversal order, W4). They sit after
  # json-secret-field and before bcrypt-hash; the 31 patterns above keep their regex and their order. Every span they match goes through the classifier below
  # (value -> W3 whitelist -> entropy floor -> path form -> dotted identifier). ERE only (grep -E / sed -E), no backtracking, and LINEAR in the input length: no
  # unbounded greedy prefix in front of a character-class run (kv: key-name affixes of at most 64 characters each, cli: flag-name prefix of at most 40, both with a
  # left boundary; JSON keys start with `"`, header names with a literal). Header names are spelled as per-letter classes: BSD sed has neither -i nor the I modifier.
  # 1. json-credential-field: JSON key from a closed table (17 stems x snake / camel / Pascal / joined spellings = 58 names), string value of 16 or more characters.
  'json-credential-field|"(AccessToken|ApiKey|ApiToken|AuthToken|BearerToken|ClientSecret|JwtSecret|Passwd|Password|PrivateKey|RefreshToken|RegistrationToken|Secret|SecretKey|SessionToken|Sha1|Token|accessToken|access_token|accesstoken|apiKey|apiToken|api_key|api_token|apikey|apitoken|authToken|auth_token|authtoken|bearerToken|bearer_token|bearertoken|clientSecret|client_secret|clientsecret|jwtSecret|jwt_secret|jwtsecret|passwd|password|privateKey|private_key|privatekey|refreshToken|refresh_token|refreshtoken|registrationToken|registration_token|registrationtoken|secret|secretKey|secret_key|secretkey|sessionToken|session_token|sessiontoken|sha1|token)"[[:space:]]*:[[:space:]]*"[^"]{16,}"'
  # 2. json-env-secret-key: JSON key that is an upper-case environment variable name holding one of the keywords (Nomad / compose `Env` maps), value of 16 or more.
  'json-env-secret-key|"[A-Z0-9_]*(SECRET|PASSWORD|PASSWD|TOKEN|API_KEY|APIKEY|PRIVATE_KEY|WEBHOOK|ENCRYPTION_KEY|ACCESS_KEY)[A-Z0-9_]*"[[:space:]]*:[[:space:]]*"[^"]{16,}"'
  # 3. kv-secret-assign: INI / env / YAML assignment; upper-case key holding a keyword, optional `export`, `=` or `:` with optional blanks, one optional quote layer.
  'kv-secret-assign|(^|[^A-Za-z0-9_])(export[[:space:]]+)?[A-Z0-9_]{0,64}(SECRET|PASSWORD|PASSWD|TOKEN|API_KEY|APIKEY|PRIVATE_KEY|WEBHOOK|ENCRYPTION_KEY|ACCESS_KEY)[A-Z0-9_]{0,64}[[:space:]]*[=:][[:space:]]*["'"'"']?[A-Za-z0-9+/=._~-]{16,}'
  # 4. auth-header-token: `Authorization: token <v>` / `Authorization: Basic <v>` (header name case-insensitive: curl -v under HTTP/2 echoes it in lower case).
  'auth-header-token|[aA][uU][tT][hH][oO][rR][iI][zZ][aA][tT][iI][oO][nN]:[[:space:]]*([Tt]oken|[Bb]asic)[[:space:]]+[A-Za-z0-9._/+=-]{16,}'
  # 5. cf-access-client-secret: `CF-Access-Client-Secret: <v>` (header name case-insensitive).
  'cf-access-client-secret|[cC][fF]-[aA][cC][cC][eE][sS][sS]-[cC][lL][iI][eE][nN][tT]-[sS][eE][cC][rR][eE][tT]:[[:space:]]*[A-Za-z0-9._/+=-]{16,}'
  # 6. cli-secret-flag: `--token=<v>` style flags (`-` or `--`, a name ending in a keyword, the value joined with `=`).
  'cli-secret-flag|(^|[^A-Za-z0-9-])--?[A-Za-z0-9-]{0,40}(token|password|passwd|secret|api-key|apikey|access-key)=[A-Za-z0-9+/=._~-]{16,}'

  # bcrypt hash
  'bcrypt-hash|\$2[abxy]\$[0-9]{2}\$[A-Za-z0-9./]{53}'
)

# ── W2 classifier / W3 whitelist / W4 fingerprint helpers ──────────────────
# (secret-net-l3-and-bypass-paths.) A span that a pattern matched is handled here BEFORE the counting substitution consumes it: the credential body is cut out of
# the span (_value_of), the span is filtered, and what still counts is fingerprinted (W4). Filtering: the W3 whitelist for the six W2 tags and json-secret-field;
# entropy floor, path form and dotted identifier for the six W2 tags only. No other tag is filtered: their detections stay those of the baseline.
# Spans are UNTRUSTED text: the helpers only slice strings and use [[ =~ ]] -- no eval / source, no command substitution or arithmetic on the content. The
# classification path has no fork (builtins and [[ =~ ]]); helpers hand their result back through the global V. Regexes live in variables: bash 3.2 cannot parse
# a bare `<` inside [[ ]].
CLASSIFIED_TAGS=" json-secret-field json-credential-field json-env-secret-key kv-secret-assign auth-header-token cf-access-client-secret cli-secret-flag "
NEW_TAGS=" json-credential-field json-env-secret-key kv-secret-assign auth-header-token cf-access-client-secret cli-secret-flag "
V=""
# Character classes are ENUMERATED, never written as ranges: in bash < 5 under a non-C locale a glob range such as [a-z] follows the collation order (real bash
# 3.2.57 with en_US.UTF-8: [[ QWERTY == *[a-z]* ]] is true), which would let the entropy floor count capitals as lower case. (The ERE patterns above keep the
# baseline's range spelling: grep / sed read them by code point.)
_AZ='ABCDEFGHIJKLMNOPQRSTUVWXYZ'; _az='abcdefghijklmnopqrstuvwxyz'; _09='0123456789'
_RE_TRIM='^[[:space:]]*(.*[^[:space:]])[[:space:]]*$'
_RE_LASTWORD='([^[:space:]]+)$'
_RE_PFX_COLON='^[^:]*:'                                              # up to and including the first `:`
_RE_PFX_EQ='^[^=]*='                                                 # up to and including the first `=`
_RE_PFX_KV="^[^${_AZ}${_09}_]*[${_AZ}${_09}_]*[[:space:]]*[=:]"      # kv-secret-assign: boundary character / `export` / blanks, the key, blanks, `=` or `:`
_RE_URL_PW='^[^:]*://[^:]*:([^@]*)@'                                 # scheme://user:PASSWORD@  (the password: behind the first `:` after the user, up to the first `@`)
# Value extraction is LINEAR in the span length. Every `#` / `##` / `%` / `%%` deletion in this code finds a delimiter that is certainly there and lies within a
# constant number of characters of the start (the `:` behind a fixed header name, the quotes round a JSON value, the `://` behind the scheme). A delimiter that can
# be far away -- behind a blank run, a long key, a long password -- is found by ONE [[ =~ ]] scan and the rest is cut by LENGTH (${s:N}); the one optional character
# left (a quote) is tested with ${V:0:1}. NOT ${V#["']} or ${s%%X*} where the delimiter may be missing or far: bash tries the positions one by one and each try
# costs O(length), so a 300 KB value takes seconds of CPU, past the hook's 5 s timeout (SC-34).
_trimV() { if [[ "$V" =~ $_RE_TRIM ]]; then V="${BASH_REMATCH[1]}"; else V=""; fi; }
_cut_pfx() {   # $1 regex  $2 span  -> V = the span after the regex's match (one scan finds it, ${s:N} cuts); no match -> the span itself (counted, never dropped)
  if [[ "$2" =~ $1 ]]; then V="${2:${#BASH_REMATCH[0]}}"; else V="$2"; fi
}
_value_of() {   # $1 tag  $2 span  -> V = the credential body (the W4 table): what W3 / W2 classify and what is fingerprinted
  local tag="$1" span="$2" k
  case "$tag" in
    json-secret-field|json-credential-field|json-env-secret-key)
      _cut_pfx "$_RE_PFX_COLON" "$span"; _trimV; V="${V#\"}"; V="${V%\"}" ;;
    kv-secret-assign)
      _cut_pfx "$_RE_PFX_KV" "$span"; _trimV; case "${V:0:1}" in \"|\') V="${V:1}" ;; esac ;;
    auth-header-token|bearer-token) if [[ "$span" =~ $_RE_LASTWORD ]]; then V="${BASH_REMATCH[1]}"; else V="$span"; fi ;;
    cf-access-client-secret|x-api-key-header) k="${span%%:*}"; V="${span:${#k}+1}"; _trimV ;;
    cli-secret-flag|env-line-secret-keyword) _cut_pfx "$_RE_PFX_EQ" "$span" ;;
    postgres-url|redis-url|mongodb-url|basic-auth-url)
      if [[ "$span" =~ $_RE_URL_PW ]]; then V="${BASH_REMATCH[1]}"; else V="$span"; fi ;;
    gcp-private-key-id) k="${span%%:*}"; V="${span:${#k}+1}"; _trimV; V="${V#\"}"; V="${V%\"}" ;;
    pem-private-key-block|pem-header-only) V="" ;;
    *) V="$span" ;;   # provider-prefix keys, jwt, webhooks, bcrypt: the whole span is the credential
  esac
}
_RE_RED='^\[REDACTED[^]]*\]$'
_RE_ANGLE='^[<][^<>]*[>]$'
_RE_VARB='^\$\{[^}]*\}$'
_RE_TMPL='^\$?\{\{.*\}\}$'
_RE_MASK='^(\*+|x+|X+)$'
_wl_match() {   # W3 whitelist. $1 value; rc 0 = placeholder (not counted). WHOLE-value placeholder forms and deliberate marker words only, never a one-character prefix
  local v="$1"
  case "$v" in
    FAKE*|PLACEHOLDER*|NOT-REAL*|NOT_REAL*|NOTREAL*|REDACTED*) return 0 ;;   # marker words at the start of the value (case-sensitive)
  esac
  [[ "$v" =~ $_RE_RED ]] && return 0     # [REDACTED...] with the bracket closed
  [[ "$v" =~ $_RE_ANGLE ]] && return 0   # <...> without a < or > inside (also the counting sentinel <secret-scan-counted:TAG>)
  [[ "$v" =~ $_RE_VARB ]] && return 0    # ${...}
  [[ "$v" =~ $_RE_TMPL ]] && return 0    # {{...}} and ${{...}}
  [[ "$v" =~ $_RE_MASK ]] && return 0    # only * or x or X, repeated
  [[ "$v" == *"…" ]] && return 0         # ends with U+2026 (a truncated display); the ASCII "..." is NOT included
  return 1
}
_entropy_ok() {   # W2 entropy floor: at least two of the three classes lower / upper / digit (symbols are no class)
  local v="$1" n=0
  [[ "$v" == *[abcdefghijklmnopqrstuvwxyz]* ]] && n=$((n+1))
  [[ "$v" == *[ABCDEFGHIJKLMNOPQRSTUVWXYZ]* ]] && n=$((n+1))
  [[ "$v" == *[0123456789]* ]] && n=$((n+1))
  (( n >= 2 ))
}
_RE_PATHLEAD='^(/|~/|\./|\.\./)'
_RE_PATHCH="^[${_AZ}${_az}${_09}._~/-]+\$"
_RE_DOTID="^[${_AZ}${_az}_][${_AZ}${_az}${_09}_]*(\\.[${_AZ}${_az}_][${_AZ}${_az}${_09}_]*)+\$"
_path_form() {   # W2: a file path -- starts with / ~/ ./ ../, only [A-Za-z0-9._~/-], at least two `/` (`+` and `=` are no path characters: a base64 value is not a path)
  local v="$1"
  [[ "$v" =~ $_RE_PATHLEAD ]] || return 1
  [[ "$v" =~ $_RE_PATHCH ]] || return 1
  [[ "$v" == */*/* ]]
}
_dotted_ident() { [[ "$1" =~ $_RE_DOTID ]]; }   # W2: a dotted identifier chain (process.env.X, settings.X): the value is read from the environment / configuration
FP_ITEMS=""; FP_N=0
_fp_push() {   # $1 item -> the fingerprint list of the log line (W4), at most 10 items
  (( FP_N >= 10 )) && return 0
  FP_ITEMS="${FP_ITEMS:+$FP_ITEMS,}$1"; FP_N=$((FP_N+1))
}
_fp_add() {   # $1 credential body -> first 8 hex digits of its sha256 (value of 16 or more characters), L<length> for a shorter one (no hash: an unsalted prefix would
              # let a dictionary confirm a short password), "-" when neither sha256sum nor shasum can be run (fail-soft: the log line is still written)
  (( FP_N >= 10 )) && return 0
  local v="$1" h="" it
  if (( ${#v} < 16 )); then it="L${#v}"
  else
    if command -v sha256sum >/dev/null 2>&1; then h="$(printf '%s' "$v" | sha256sum 2>/dev/null)"
    elif command -v shasum >/dev/null 2>&1; then h="$(printf '%s' "$v" | shasum -a 256 2>/dev/null)"; fi
    it="${h:0:8}"; it="${it:--}"
  fi
  _fp_push "$it"
}

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
      pem_i=0   # W4: the PEM pre-pass comes first in the fingerprint order; a PEM block's item is "-" (no value is taken from it)
      while (( pem_i < pem_count && FP_N < 10 )); do _fp_push "-"; pem_i=$(( pem_i + 1 )); done
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
    _fp_push "-"   # W4: same item as a PEM block
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
    # W2 / W3 / W4: classification and fingerprints, one pass over the FIRST 200 spans of this tag, BEFORE the counting substitution consumes them (a span that the
    # classifier excludes is consumed all the same: nothing after it should count it). `keep` = the spans that count. The spans beyond 200 are not iterated: no
    # value, no classification, no fingerprint, they are added as (count - 200) -- fail-closed counting with a bounded iteration cost (SC-11 11w).
    fp_mark_items="$FP_ITEMS"; fp_mark_n="$FP_N"
    keep=0
    while IFS= read -r span; do
      _value_of "$tag" "$span"; v="$V"
      if [[ "$CLASSIFIED_TAGS" == *" $tag "* ]]; then
        _wl_match "$v" && continue
        if [[ "$NEW_TAGS" == *" $tag "* ]]; then
          _entropy_ok "$v" || continue
          _path_form "$v" && continue
          _dotted_ident "$v" && continue
        fi
      fi
      keep=$((keep+1))
      _fp_add "$v"
    done < <(grep -oE -- "$pattern" "$tmpfile" 2>/dev/null | head -n 200)
    (( count > 200 )) && keep=$(( keep + count - 200 ))
    # In-place counting-substitution using \x01 as sed delimiter (R2 audit C-1 fix).
    sed -i -E "s${SEP}${pattern}${SEP}<secret-scan-counted:${tag}>${SEP}g" "$tmpfile" 2>/dev/null || {
      # R2 audit C-1 + integrity-check: if the counting-substitution failed,
      # do NOT increment matches_total — better a silent under-count than a
      # wrong match total.
      echo "[secret-scan] WARN: counting-substitution failed for pattern tag=${tag}; skipping" >&2
      FP_ITEMS="$fp_mark_items"; FP_N="$fp_mark_n"   # W4: spans that are not counted are not fingerprinted either
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
      # Adjust the count to reflect what actually got isolated (keep - residual; keep = count minus the spans W2 / W3 exclude)
      actual_counted=$(( keep - residual ))
      if (( actual_counted > 0 )); then
        matches_total=$(( matches_total + actual_counted ))
        matches_breakdown="${matches_breakdown}${tag}=${actual_counted}+${residual}-uncounted "
      else
        matches_breakdown="${matches_breakdown}${tag}=0+${residual}-uncounted "
      fi
      continue
    fi
    if (( keep > 0 )); then   # every span of this tag may have been excluded by the W2 / W3 filters: then the tag is not reported at all
      matches_total=$(( matches_total + keep ))
      matches_breakdown="${matches_breakdown}${tag}=${keep} "
    fi
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
# W4: the 9th field `fp=` holds one fingerprint per counted span (at most 10, comma separated; sha256 hex prefix, L<length> or "-", see _fp_add), never a value.
printf '%s\t%s\t%s\tSCAN-DETECT\ttool=%s\tmatches=%s\tbreakdown=%s\tsize=%s\tfp=%s\n' \
  "$(date -u +%FT%TZ)" "${USER:-unknown}" "${PWD:-unknown}" \
  "$tool" "$matches_total" "${matches_breakdown% }" "$input_size" "${FP_ITEMS:--}" \
  >> "${HOME}/.claude/logs/secret-scan.log" 2>/dev/null || true

# Emit warn JSON on stdout: additionalContext (injected into Claude's context)
# + systemMessage (operator-visible). These are the PostToolUse output channels
# Claude Code honors. NO tool_response mutation is emitted — this hook cannot
# redact (PostToolUse architectural limit, hooks-guide 891).
# W5: descriptive only -- the tag breakdown (the hook's own tag table and counts) and the harness tool name. NEVER any tool_input text (file_path, command): it is
# decided by the repository or conversation being read, and additionalContext is the channel the model trusts most.
addl_msg="[secret-scan] DETECTED ${matches_total} secret-shape match(es) in tool output (tags: ${matches_breakdown% }; source: ${tool}) — treat as already-leaked; do NOT repeat the value(s) in your reply; recommend rotating the affected credential(s). (This hook detects+warns only; it cannot redact — PostToolUse runs after the tool result is already produced.)"
sys_msg="[secret-scan] Detected ${matches_total} secret-shape match(es) (${matches_breakdown% }); rotate affected credential(s)."
jq -n --arg ev "$hook_event" --arg addl "$addl_msg" --arg sys "$sys_msg" '{
  hookSpecificOutput: {
    hookEventName: $ev,
    additionalContext: $addl
  },
  systemMessage: $sys
}' 2>/dev/null || true

exit 0

#!/usr/bin/env bash
# PreToolUse hook — block raw reads of secret stores into LLM tool output.
#
# === THREAT MODEL + KNOWN LIMITATIONS (Read this before trusting the hook) ===
#
# What this hook IS:
#   A blacklist-based speed-bump that catches accidental secret reads emitted
#   by Claude (the LLM) in response to operator prompts. It covers the ~100
#   most common patterns: cloud secret managers (AWS/GCP/Aliyun/Doppler/etc.),
#   K8s/Vault/Nomad secret APIs, .env / id_rsa / .pem / .aws/credentials /
#   kubeconfig file reads, psql sensitive-column queries, base64-pipe-bash and
#   python/node HTTP wrappers, decryption tools (sops/age/gpg).
#
# What this hook is NOT:
#   - Not a complete prevention of secret exfiltration. A determined operator
#     or adversarial agent can bypass via shell quoting tricks, unknown
#     secret-store CLIs, novel file readers (perl/awk one-liners), or by
#     mangling tool_name input shape.
#   - Not a content scanner. The hook acts BEFORE tool execution, so it never
#     sees the output. If a command returns secrets and isn't in the blacklist,
#     they flow to LLM context unguarded. Phase 2 would add PostToolUse hook
#     that regex-scans output for `^[A-Z_]+=.+$` style env lines + redacts —
#     out of scope for current implementation.
#   - Not a defense against malicious operators. Anyone with shell access can
#     `chmod -x` this file or set SECRET_GUARD_BYPASS_NO_JQ=1.
#
# Coverage gaps explicitly known (Round 2 audit, addressed iteratively):
#   - File readers: cat/head/tail/less/more/tee/mapfile/readarray/dd/strings/
#     hexdump/od/awk/perl/while-read all covered as of Round 2; new ones may
#     emerge — add to risky_patterns when discovered.
#   - jq projection ALLOW path still leaks if operator writes `jq '.Items'`
#     (returns full object) or `jq '.Items.password'` (extracts value). Hook
#     can't distinguish a "safe field-name listing" from "value extraction"
#     without semantic knowledge of the data shape. Recommend `jq 'keys'`
#     or content-scan PostToolUse hook for true safety.
#   - Adversarial shell quoting (`c""at .env`, alias overrides) is out of
#     scope — Claude doesn't typically emit such constructs.
#
# Why this is still worth shipping:
#   The 2026-05-16 incident was a TYPICAL pattern — raw curl to Nomad var
#   endpoint, no jq filter, no malice. The hook prevents the same pattern +
#   ~80% of cousin patterns. Combined with operator awareness training (see
#   docs/operations/secret-rotation-runbook.md §1.3 principles) it's a
#   meaningful defense layer, not a guarantee.
#
# === History ===
#   v1.0: PR #429 initial — basic regex blacklist for Bash tool only
#   v1.1: Round 1 audit fixes (jq fail-closed; Read/Edit matcher; cat/tr/head/
#         tail removed from filter allowlist; aws/gcloud/op/pass/gh/aliyun;
#         python/node HTTP wrappers; base64-pipe-bash; sops/age/gpg; psql
#         column expansion; guard:ack reason + log)
#   v1.2: Round 2 audit fixes (jq -r identity bypass; 2>/dev/null mis-filter;
#         find/xargs/dd/strings/awk/perl readers; kubectl exec env|cat;
#         tee </mapfile </readarray <; doppler/infisical/bws/az/akeyless/
#         chamber/teller/glab; guard:ack 8-non-whitespace; Read/Edit case-
#         insensitive + .aws/credentials/kubeconfig/.tfstate/.key/.p12;
#         malformed tool_name → fail-closed; command length cap; SECRET_GUARD_
#         ACK_PATH one-shot via timestamp; pg/source/. .env readers)
#
# Operator bypass (logged to ~/.claude/logs/guard-bypass.log):
#   Bash:        ... # guard:ack: <reason ≥ 8 non-whitespace chars describing why>
#   Read/Edit:   SECRET_GUARD_ACK_PATH="$file_path" claude ...
#                (one-shot — must re-set before each subsequent Read/Edit on same path)

set -uo pipefail   # NOT -e — we control exit codes

# ── Fail-closed if jq missing ─────────────────────────────────────────────
if ! command -v jq >/dev/null 2>&1; then
  cat >&2 <<'EOF'
[secret-guard] FATAL: jq not installed. Hook cannot parse PreToolUse input
without it, and fails CLOSED (blocking all tool calls) to avoid silent
bypass. Install:
  apt-get install jq       # Debian/Ubuntu
  brew install jq          # macOS
  apk add jq               # Alpine

If jq cannot be installed in this environment and you accept the risk,
set: export SECRET_GUARD_BYPASS_NO_JQ=1
This bypass is logged to ~/.claude/logs/guard-bypass.log on every tool
call so post-event audit catches it.
EOF
  if [[ "${SECRET_GUARD_BYPASS_NO_JQ:-0}" == "1" ]]; then
    mkdir -p "${HOME}/.claude/logs" 2>/dev/null || true
    printf '%s\t%s\t%s\tJQ-MISSING-BYPASS\n' \
      "$(date -u +%FT%TZ)" "${USER:-unknown}" "${PWD:-unknown}" \
      >> "${HOME}/.claude/logs/guard-bypass.log" 2>/dev/null || true
    exit 0
  fi
  exit 2
fi

# ── Parse input — fail-closed on malformed JSON / malformed structure ─────
input="$(cat 2>/dev/null || true)"
if [[ -z "$input" ]]; then
  exit 0   # empty stdin — test invocation or harness misconfig. Allowed.
fi

# R2-C-4 fix: validate input is a JSON object with string tool_name.
# Previously `.tool_name // ""` returned empty for array/null/object → silent
# case-star fallthrough to exit 0. Now we explicitly check type and fail-closed
# on malformed structure.
tool_type="$(printf '%s' "$input" | jq -r '.tool_name | type' 2>/dev/null)"
if [[ "$tool_type" != "string" ]]; then
  if [[ "$tool_type" == "null" ]] || [[ -z "$tool_type" ]]; then
    # Missing/null tool_name on a non-empty input — likely malformed harness
    # input. Fail-closed: blocking is safer than silent allow.
    echo "[secret-guard] FATAL: malformed PreToolUse input — tool_name missing or null. Blocking." >&2
    exit 2
  fi
  echo "[secret-guard] FATAL: malformed PreToolUse input — tool_name is type=$tool_type (expected string). Blocking." >&2
  exit 2
fi

tool="$(printf '%s' "$input" | jq -r '.tool_name' 2>/dev/null)"

# ── log_ack with hard failure handling ────────────────────────────────────
# R4-C-1 fix: definition moved here from below `case` block so Read|Edit
# branch can call it. Bash needs functions defined before runtime call site.
# Previous R3 fix moved log_ack to address R3-C-10 (stderr leak of raw entry);
# moved correctly into the file but placed AFTER the case block that calls
# it from Read|Edit branch → `log_ack: command not found` stderr leak (the
# very thing R3-C-10 was meant to prevent). v1.4 restores correct ordering.
#
# Behavior: if log dir writable, append entry. If not writable, surface
# SHA256 prefix only to stderr (NOT raw entry) so audit signal preserved
# without re-leaking guard:ack reason or command args into LLM context.
log_ack() {
  local kind="$1" payload="$2"
  local entry
  entry="$(printf '%s\t%s\t%s\t%s\t%s\n' \
    "$(date -u +%FT%TZ)" "${USER:-unknown}" "${PWD:-unknown}" "$kind" "$payload")"
  if mkdir -p "${HOME}/.claude/logs" 2>/dev/null \
     && printf '%s' "$entry" >> "${HOME}/.claude/logs/guard-bypass.log" 2>/dev/null; then
    return 0
  fi
  local hash
  hash="$(printf '%s' "$entry" | sha256sum 2>/dev/null | head -c 16)"
  echo "[secret-guard] WARN: audit log write failed (HOME unwritable / disk full?)" >&2
  echo "[secret-guard] WARN: ack invocation hash=${hash:-unknown} (full entry NOT logged here to avoid re-leaking guard:ack reason or command args into LLM context)" >&2
  echo "[secret-guard] WARN: investigate via shell history / system journal / sudo journalctl --user-unit secret-guard" >&2
}

# ── R2 Multi-tool dispatch ─────────────────────────────────────────────────
case "$tool" in
  Read|Edit)
    file_path="$(printf '%s' "$input" | jq -r '.tool_input.file_path // ""' 2>/dev/null)"
    [[ -z "$file_path" ]] && exit 0

    # R2-C-6 fix: case-insensitive + expanded path list. Common high-value
    # secret file paths a future-Claude might Read without realizing.
    # Note: lowercased file_path for the match.
    lower_path="$(printf '%s' "$file_path" | tr '[:upper:]' '[:lower:]')"
    if echo "$lower_path" | grep -qE '\.env(\.[a-z0-9_.-]+)?$|\.envrc$|/secrets?/|/credentials?/|id_rsa$|id_ed25519$|id_ecdsa$|\.pem$|\.key$|\.gpg$|\.age$|\.p12$|\.pfx$|\.jks$|\.tfstate$|\.tfstate\.backup$|/\.aws/credentials$|/\.aws/config$|/\.kube/config$|kubeconfig$|service[_-]account.*\.json$|gcp[_-]key.*\.json$|firebase.*\.json$|\.ssh/known_hosts$|/secret[_-]token|/master[_-]key|/encryption[_-]key'; then
      # R3-C-9 fix: SECRET_GUARD_ACK_PATH cannot be unset across processes
      # (env var lives in the parent shell, hook subprocess can't unset it).
      # Previously hook just emitted "consumed" NOTE which was dead code.
      # Now: enforce one-shot via marker file + nonce. Operator must do:
      #   1. echo "$(date +%s%N)" > /tmp/secret-guard-ack-$$.nonce
      #   2. export SECRET_GUARD_ACK_PATH="$file_path"
      #   3. export SECRET_GUARD_ACK_NONCE="$(cat /tmp/secret-guard-ack-$$.nonce)"
      #   4. (single Read/Edit call)
      # Hook consumes the nonce by deleting the marker. Subsequent calls
      # with the same env vars but missing marker are rejected.
      if [[ "${SECRET_GUARD_ACK_PATH:-}" == "$file_path" ]]; then
        nonce="${SECRET_GUARD_ACK_NONCE:-}"
        marker="/tmp/secret-guard-ack-${USER:-anon}-${nonce}.nonce"
        if [[ -n "$nonce" ]] && [[ -e "$marker" ]]; then
          # Valid one-shot — consume marker file, log, allow.
          rm -f "$marker" 2>/dev/null
          log_ack "ACK-PATH-ONESHOT" "$tool($file_path) nonce=$nonce"
          exit 0
        fi
        # Marker missing or no nonce — log as repeat attempt and reject.
        log_ack "ACK-PATH-REPEAT-REJECTED" "$tool($file_path) (no valid nonce; SECRET_GUARD_ACK_PATH alone is not sufficient since v1.3)"
        echo "[secret-guard] BLOCKED: SECRET_GUARD_ACK_PATH set but no valid one-shot nonce." >&2
        echo "[secret-guard] To bypass: create a nonce marker file before each call:" >&2
        echo "  nonce=\$(date +%s%N)" >&2
        echo "  touch \"/tmp/secret-guard-ack-\${USER}-\${nonce}.nonce\"" >&2
        echo "  export SECRET_GUARD_ACK_NONCE=\"\$nonce\"" >&2
        echo "  export SECRET_GUARD_ACK_PATH=\"$file_path\"" >&2
        echo "  # ... your one $tool call ..." >&2
        echo "" >&2
        echo "Each Read/Edit on a secret path requires a fresh nonce marker. This enforces true one-shot per call." >&2
        exit 2
      fi
      cat >&2 <<EOF
[secret-guard] BLOCKED: $tool tool targeting secret-bearing file.
Path: $file_path

Why: Read/Edit contents go into Claude tool output, same leak risk as Bash.

How to proceed:
  (a) ssh to the host + vim interactively (no LLM context)
  (b) Edit via a Bash script with the value passed through read -rs
  (c) One-off bypass: export SECRET_GUARD_ACK_PATH="$file_path"
      then re-invoke the tool. ACK is path-specific and intended one-shot
      (re-set env for each subsequent call on same path).

Blocked: $tool($file_path)
EOF
      exit 2
    fi
    exit 0
    ;;
  Bash)
    : # fall through
    ;;
  *)
    exit 0
    ;;
esac

# ── Bash command analysis ─────────────────────────────────────────────────
command="$(printf '%s' "$input" | jq -r '.tool_input.command // ""' 2>/dev/null)"
[[ -z "$command" ]] && exit 0

# R2-I-5 fix: command length cap. A 10 MB command would make the 30+ regex
# iterations take 100s of ms. 64 KB is generous for any legitimate use.
cmd_len=${#command}
if (( cmd_len > 65536 )); then
  echo "[secret-guard] BLOCKED: Bash command exceeds 64 KB (got ${cmd_len} bytes). Likely a binary blob or extraction attempt — blocking. Split the command if legitimate." >&2
  exit 2
fi

# ── guard:ack escape ───────────────────────────────────────────────────────
# (log_ack function now defined earlier — see top-of-file fix for R4-C-1.)
# R2-C-9 fix: require 8 NON-WHITESPACE chars after `: ` (was: 8 of any char,
# allowing padding with spaces).
if echo "$command" | grep -qE '#[[:space:]]*guard:ack[[:space:]]*[:=][[:space:]]*[^[:space:]][^[:space:]]{7,}'; then
  log_ack "ACK-REASON" "$command"
  exit 0
fi
# Legacy bare `# guard:ack` (no reason) — accept with WARN, still logged.
# R2-C-9 refinement: bare ack only matches when there's NO `: <reason>` form.
# If operator wrote `# guard:ack: x       ` (insufficient non-whitespace), the
# reason rule above failed, and we should NOT silently downgrade to bare-ack.
# Pattern below requires guard:ack at line-end OR followed by non-:/= char.
if echo "$command" | grep -qE '#[[:space:]]*guard:ack[[:space:]]*$|#[[:space:]]*guard:ack[[:space:]]+[^:=[:space:]]'; then
  log_ack "ACK-NO-REASON" "$command"
  echo "[secret-guard] WARN: '# guard:ack' bypass used without reason." >&2
  echo "[secret-guard] WARN: Required form: '# guard:ack: <reason ≥ 8 NON-WHITESPACE chars>'" >&2
  exit 0
fi

# ── Filter detection (only REDACTING filters count) ────────────────────────
# Round 1 removed: cat/tr/head/tail/fold (preserve content), > file / 2> / >>
# Round 2 fixes:
#   - R2-C-1: `jq -r .` raw-flag identity now also rejected
#   - R2-C-10: `2>/dev/null` (stderr-only) no longer counts (was: any `>`)
has_filter=0

# jq filter detection — v1.3 (R3-C-1 fix): switched from "treat any non-`.`
# as projection" to "explicit safe-jq whitelist". Previously `.[]`, `values`,
# `..`, `tostring`, `@text`, `@base64`, `.Items` (returns full subobject),
# `.Items.password` (extracts value) all bypassed because regex only
# checked for literal `.`. R3 audit confirmed identity-equivalent expressions
# are unbounded.
#
# Safe jq patterns (allowlist):
#   jq keys         — returns field names only, no values
#   jq 'keys'
#   jq 'length'     — returns count
#   jq '. | length'
#   jq '. | keys'
#   jq '{<alias>: .<safe_field>}' — explicit allowlist projection
#   jq 'select(...)' — filter rows by predicate (semantic — operator knows)
#
# Everything else = no filter credit, fall through to risky_patterns check.
if echo "$command" | grep -qE "\|[[:space:]]*jq([[:space:]]+(-[a-zA-Z]+|--[a-z-]+))*[[:space:]]+[\"']?(.+\|[[:space:]]*)?(keys|length|paths|leaf_paths)[\"']?[[:space:]]*(\$|\|)"; then
  has_filter=1
fi
# Whitelisted: `jq '{alias: .safe_field}'` — single-line allowlist projection.
# Recognize the `{...}` object-construction shape as projection allowlist.
if echo "$command" | grep -qE "\|[[:space:]]*jq([[:space:]]+(-[a-zA-Z]+|--[a-z-]+))*[[:space:]]+[\"']?\{"; then
  has_filter=1
fi
# grep / sed / cut / awk — R4-C-2 fix: tighten to require actual redaction.
# Previously any 1-char arg counted as "filter" (`| grep .` / `| sed -n p` /
# `| awk 1` / `| cut -f1-` are identity-equivalent and leak full content).
# v1.4: require pattern that actually selects subset:
#   grep with anchored pattern (^ or $) OR -v/--invert OR -E/-F with content
#   sed with substitution (s///) OR delete (d) — not just `-n p` print-all
#   cut with -d AND -f<single-field> (not -f1- range)
#   awk with $N references (not just `1` for print-all)
if echo "$command" | grep -qE '\|[[:space:]]*grep([[:space:]]+-[a-zA-Z]+)*[[:space:]]+[^[:space:]]*[\^\$]'; then
  has_filter=1   # grep with anchor (probably real filtering)
fi
if echo "$command" | grep -qE '\|[[:space:]]*grep[[:space:]]+(-v|--invert-match)\b'; then
  has_filter=1   # grep -v inverts (probably filtering)
fi
if echo "$command" | grep -qE '\|[[:space:]]*sed[[:space:]]+[^[:space:]]*([Ss]/[^/]*/|[0-9]+d|[Dd])'; then
  has_filter=1   # sed s/// or delete
fi
# cut requires single field (not range like -f1- which is all-fields identity)
if echo "$command" | grep -qE '\|[[:space:]]*cut[[:space:]]+-[df][[:space:]]*[^[:space:]-]'; then
  has_filter=1   # cut -d= or -f1 (specific field)
fi
# awk content can contain spaces inside quotes; match `$N` anywhere in quoted arg
if echo "$command" | grep -qE "\|[[:space:]]*awk[[:space:]]+['\"][^'\"]*\\\$[0-9]"; then
  has_filter=1   # awk '{print $N}'
fi
if echo "$command" | grep -qE "\|[[:space:]]*awk[[:space:]]+['\"][^'\"]*/[^/]+/"; then
  has_filter=1   # awk '/regex/...'
fi
# R2-C-10 fix: only stdout-redirect to /dev/null counts. stderr-only (2>) and
# combined (&>) need separate handling.
#   `>/dev/null` and `>  /dev/null` — stdout discard, safe
#   `&>/dev/null` — both discard, safe (but rarely seen)
#   `2>/dev/null` — only stderr discard, stdout still flows: NOT a filter
if echo "$command" | grep -qE '([^0-9&]|^)>[[:space:]]*/dev/null'; then
  has_filter=1
fi
if echo "$command" | grep -qE '&>[[:space:]]*/dev/null'; then
  has_filter=1
fi
# curl -o /dev/null / --silent without explicit other output
if echo "$command" | grep -qE '(-o[[:space:]]+/dev/null|--output[[:space:]]+/dev/null)'; then
  has_filter=1
fi
# wc / sha256sum / md5sum — emit count/hash, not content
if echo "$command" | grep -qE '\|[[:space:]]*wc[[:space:]]+-[clw]'; then
  has_filter=1
fi
if echo "$command" | grep -qE '\|[[:space:]]*(sha256sum|md5sum|sha1sum|sha512sum)\b'; then
  has_filter=1
fi

# ── Risky read patterns ────────────────────────────────────────────────────
declare -a risky_patterns=(
  # Nomad Variables (HTTP API + CLI + alloc fs)
  'curl[^|]*/v1/var/'
  '/v1/var/'                                # any HTTP client to Nomad var path
  'nomad[[:space:]]+var[[:space:]]+(get|list)'
  'nomad[[:space:]]+alloc[[:space:]]+fs'
  'nomad[[:space:]]+operator[[:space:]]+api[^|]*/var/'

  # HashiCorp Vault
  'vault[[:space:]]+(read|kv[[:space:]]+get)'

  # Cloud-provider secret managers (R2-C-8 expanded)
  'aws[[:space:]]+secretsmanager'
  'aws[[:space:]]+ssm[[:space:]]+get-parameter'
  'aws[[:space:]]+kms[[:space:]]+decrypt'
  'gcloud[[:space:]]+secrets[[:space:]]+versions'
  'aliyun[[:space:]]+(ram|kms)'
  'az[[:space:]]+keyvault[[:space:]]+secret'              # Azure
  'akeyless[[:space:]]+(get-secret-value|list-items)'     # Akeyless

  # CLI password / secret managers
  'op[[:space:]]+(item|read)[[:space:]]+get'              # 1Password
  'op[[:space:]]+(item|read|inject)\b'
  'pass[[:space:]]+show'                                  # Unix pass
  'doppler[[:space:]]+(secrets|run)'                      # Doppler
  'infisical[[:space:]]+(secrets|export|run)'             # Infisical
  'bws[[:space:]]+secret[[:space:]]+get'                  # Bitwarden Secrets
  'chamber[[:space:]]+(read|export)'                      # Segment chamber
  'teller[[:space:]]+(env|show|copy)'                     # Spectral teller

  # Git-platform stored secrets
  'gh[[:space:]]+api[^|]*(/secrets|/variables|/environments/[^/]+/secrets)'
  'forgejo[[:space:]]+(GET[[:space:]])?[^|]*(actions/secrets|variables)'
  'glab[[:space:]]+variable[[:space:]]+get'               # GitLab CLI

  # Plain env-file reads (cat / head / tail / less / more)
  'cat[[:space:]]+[^|]*\.env(\b|/|$|[[:space:]])'
  'cat[[:space:]]+[^|]*\.envrc'
  '(head|tail|less|more)[[:space:]]+[^|]*\.env'

  # R4-C-4 fix: K8s / Docker container-mounted secret paths in Bash
  # (Read|Edit branch already covers via path regex; mirror here for Bash)
  '(cat|head|tail|less|more|strings|hexdump|od|xxd|tr|awk|perl|rev)[[:space:]]+[^|]*/(var/)?run/secrets/'
  '<[[:space:]]*[^|]*/(var/)?run/secrets/'

  # R2-C-3 fix: extended file readers (find/xargs/dd/strings/awk/perl/hexdump/od)
  'find[^|]*-name[^|]*\.env[^|]*-exec[[:space:]]+(cat|head|tail|less|more|strings|hexdump|od|dd)'
  'find[^|]*-name[^|]*\.env[^|]*\|[[:space:]]*xargs[[:space:]]+(cat|head|tail|strings|hexdump|od)'
  'xargs[^|]*(cat|head|tail|strings|hexdump|od)[^|]*\.env'
  '\.env[^|]*\|[[:space:]]*xargs[[:space:]]+(cat|head|tail|less|more|strings|hexdump|od|dd)'   # echo /x.env | xargs cat
  '\b(echo|printf|find|ls)[^|]*\.env[^|]*\|[[:space:]]*xargs'
  'dd[[:space:]]+if=[^|]*\.env'
  'strings[[:space:]]+[^|]*\.env'
  'hexdump[[:space:]]+[^|]*\.env'
  '(\bod\b)[[:space:]]+[^|]*\.env'
  'awk[[:space:]]+[^|]*[[:space:]]+[^|]*\.env'
  'perl[[:space:]]+-[a-zA-Z]*[ne][^|]*\.env'

  # R2-C-7 fix: bash file-readers that don't shell out to cat
  'tee[[:space:]]+[^|]*<[[:space:]]*[^|]*\.env'
  'mapfile[[:space:]]+[^<]*<[[:space:]]*[^|]*\.env'
  'readarray[[:space:]]+[^<]*<[[:space:]]*[^|]*\.env'
  'while[[:space:]]+(IFS=|read)[^|]*<[[:space:]]*[^|]*\.env'
  '<[[:space:]]*[^|]*\.env[[:space:]]*(\$\(|`)[^)]*cat'
  '\bcp[[:space:]]+[^|]*\.env[[:space:]]+/dev/(stdout|tty)'
  '^[[:space:]]*\.[[:space:]]+[^|]*\.env'                 # `. .env` source
  '^[[:space:]]*source[[:space:]]+[^|]*\.env'             # `source .env`

  # SSH-remote reads of secret files / dumps (R2-I-3 expanded)
  'ssh[^|]*(cat|head|tail|less|more|printenv|env|find|strings|hexdump|od|dd|awk|perl)[^|]*(\.env|\.envrc|/secrets|/credentials|id_rsa|id_ed25519|\.pem|\.key)'
  'ssh[^|]*\.env\.production'
  "ssh[^|]*['\"][^'\"]*printenv['\"]"
  "ssh[^|]*['\"][^'\"]*\\benv\\b[[:space:]]*['\"]"
  'ssh[^|]*systemd-cgls'
  # `set | grep ...pass/secret/token/key` — catches local + ssh-wrapped form.
  # Permissive: any `set | grep` followed by sensitive keyword. Risk: false-
  # positives on `set | grep keyword` for unrelated keys, but operators rarely
  # do that in dev/prod ops scripts. R2-I-3 fix.
  'set[[:space:]]*\|[[:space:]]*grep[[:space:]]+[^|]*(pass|secret|token|key|credential)'

  # Docker env dumps (compose / direct / inspect)
  'docker[[:space:]]+(compose[[:space:]]+)?exec[^|]*[[:space:]](printenv|env)([[:space:]]+\||[[:space:]]*$)'
  'docker[[:space:]]+inspect[^|]*--format[^|]*\.Config\.Env'

  # R2-C-5 fix: kubectl exec env|cat|printenv (the K8s secret leak path)
  'kubectl[[:space:]]+exec[^|]*[[:space:]]--[[:space:]]+(env|printenv|cat)\b'
  'kubectl[[:space:]]+exec[^|]*[[:space:]](env|printenv)([[:space:]]*$|[[:space:]]+\|)'
  'kubectl[[:space:]]+exec[^|]*--[^|]*(cat|head|tail)[^|]*(/run/secrets|\.env|/etc/[^|]*passwd)'

  # Bare printenv / bare env (no args = dump everything)
  '^[[:space:]]*printenv([[:space:]]+\||[[:space:]]*$)'
  '^[[:space:]]*env([[:space:]]+\||[[:space:]]*$)'
  '^[[:space:]]*/bin/printenv'                              # absolute path
  '^[[:space:]]*/usr/bin/printenv'

  # psql sensitive-column reads
  'psql[^|]*(key_encrypted|encrypted_data|encrypted_blob|ciphertext|key_material)'
  'psql[^|]*(SELECT|select)[^|]*(secret|password|passwd|token|api_key|private_key|webhook_secret|signing_key|hash|refresh_token|oauth_access_token|client_secret)'

  # K8s secret dumps
  'kubectl[[:space:]]+get[[:space:]]+secret[^|]+-o[[:space:]]+(yaml|json)'
  'kubectl[[:space:]]+describe[[:space:]]+(secret|configmap)'

  # Indirection bypasses
  'base64[[:space:]]+(-d|--decode)[^|]*\|[[:space:]]*(bash|sh|zsh|dash)'
  '\|[[:space:]]*base64[[:space:]]+(-d|--decode)[[:space:]]*\|[[:space:]]*(bash|sh|zsh|dash)'
  'python3?[[:space:]]+-c[^|]*(/v1/var/|secretsmanager|/secrets/|\.env|provider_key)'
  'node[[:space:]]+-e[^|]*(/v1/var/|secretsmanager|/secrets/|\.env|provider_key)'

  # Decryption tools — assume targeted at secret files
  'sops[[:space:]]+(-d|--decrypt)'
  'age[[:space:]]+(-d|--decrypt)'
  'gpg[[:space:]]+(-d|--decrypt)'
  'openssl[[:space:]]+(pkcs12|rsa|ec)[[:space:]]+[^|]*-in[[:space:]]+[^|]*\.(p12|pfx|pem|key)'   # R3-I-3

  # R3-C-1 fix: jq identity-equivalent expressions (each returns full content).
  # These bypass the R2 narrow `.` regex.
  '\|[[:space:]]*jq[[:space:]]+([^|]*[[:space:]])?["'"'"']?(\.\[\]|values|\.\.|tostring|@text|@json|@base64|@base64d|\.[[:space:]]+as[[:space:]]+\$[a-z])["'"'"']?'
  '\|[[:space:]]*jq[[:space:]]+([^|]*[[:space:]])?["'"'"']?\.[[:space:]]*\+[[:space:]]*""["'"'"']?'   # `. + ""`
  '\|[[:space:]]*jq[[:space:]]+([^|]*[[:space:]])?["'"'"']?(\.\[[0-9"\'']+\]|\.\["[^"]+"\]|\.[a-zA-Z_]+\.password|\.[a-zA-Z_]+\.secret|\.[a-zA-Z_]+\.key)["'"'"']?'   # jq value-extraction shapes

  # R3-C-2 fix: bash native file readers
  '\$\([[:space:]]*<[[:space:]]*[^|)]*\.env'              # $(< .env)
  'exec[[:space:]]+[0-9]+[[:space:]]*<[[:space:]]*[^|]*\.env'   # exec 3< .env
  'IFS=[[:space:]]*[^|]*read[[:space:]]+-d[^|]*<[[:space:]]*[^|]*\.env'   # IFS= read -d "" < .env
  'printf[[:space:]]+-v[[:space:]]+[A-Za-z_]+[^|]*\$\([[:space:]]*<[[:space:]]*[^|]*\.env'

  # R3-C-3 fix: common coreutils file readers
  '(rev|tac|nl|expand|unexpand|shuf|sort|uniq|split|csplit)[[:space:]]+[^|]*\.env'
  '(diff|cmp|comm)[[:space:]]+[^|]*\.env'
  'xxd[[:space:]]+[^|]*\.env'

  # R5-C-1 fix: Cloud instance metadata service (IMDS) endpoints.
  # AWS / Azure: 169.254.169.254 — returns live IAM/STS tokens
  # GCP: metadata.google.internal (or 169.254.169.254) with Metadata-Flavor: Google header
  # Aliyun: 100.100.100.200 — returns RAM role credentials
  # All three return time-bound credentials that grant full role permissions.
  '169\.254\.169\.254'
  '100\.100\.100\.200'
  'metadata\.google\.internal'
  'Metadata-Flavor:[[:space:]]+Google'

  # R3-C-4 fix: /proc/PID/environ direct reads
  'cat[[:space:]]+/proc/[0-9]+/environ'
  'cat[[:space:]]+/proc/self/environ'
  '(cat|head|tail|less|more|strings|hexdump|od|xxd|tr|awk|perl|rev)[[:space:]]+[^|]*/proc/(self|[0-9]+)/(environ|status|cmdline)'
  '<[[:space:]]*/proc/(self|[0-9]+)/(environ|status|cmdline)'

  # R3-C-5 fix: container runtime exec with env / env-extraction
  'nsenter[[:space:]]+[^|]*[[:space:]](env|printenv|cat[[:space:]]+/etc/passwd|cat[[:space:]]+/run/secrets)'
  'crictl[[:space:]]+exec[[:space:]]+[^|]*[[:space:]](env|printenv|cat[[:space:]]+/run/secrets|cat[[:space:]]+/proc)'
  'podman[[:space:]]+exec[[:space:]]+[^|]*[[:space:]](env|printenv|cat[[:space:]]+/run/secrets|cat[[:space:]]+/proc)'
  'ctr[[:space:]]+(task[[:space:]]+)?exec[[:space:]]+[^|]*[[:space:]](env|printenv)'
  'lxc[[:space:]]+exec[[:space:]]+[^|]*--[[:space:]]+(env|printenv|cat)'
  'machinectl[[:space:]]+shell[^|]*(env|printenv|cat[[:space:]]+/run/secrets)'

  # R3-C-6 fix: DB dump tools dumping entire database (incl. all secret columns)
  '\bpg_dump\b'
  '\bpg_dumpall\b'
  '\bmysqldump\b'
  '\bmongodump\b'
  'psql[[:space:]]+[^|]*\\COPY[^|]+TO[[:space:]]+STDOUT'
  'redis-cli[[:space:]]+GET[[:space:]]+[^|]+(secret|password|token|key|credential)'
  'redis-cli[[:space:]]+KEYS[[:space:]]+["'"'"']?\*?(secret|password|token|credential)'

  # R3-C-7 fix: other secret stores not covered in R1/R2
  'consul[[:space:]]+kv[[:space:]]+get'
  'etcdctl[[:space:]]+get'
  'secret-tool[[:space:]]+(lookup|search)'
  'keyring[[:space:]]+get'
  'summon[[:space:]]+(-f|-D|-p)'
  'berglas[[:space:]]+(read|access)'
  'envchain[[:space:]]+[a-zA-Z]+[[:space:]]+env'
  'vlt[[:space:]]+secret[[:space:]]+get'
  'knox[[:space:]]+get'
  'vault[[:space:]]+agent\b'

  # R3-C-8 (partial — covers Bash-emitted exfiltration to attacker-controlled
  # destinations; OUT OF ORIGINAL THREAT MODEL — accepting as defense-in-depth
  # for the adversarial-Claude scenario the hook docs already mention).
  'rsync[[:space:]]+[^|]*\.env[[:space:]]+[^|]+@'                           # rsync .env user@dst
  'scp[[:space:]]+[^|]*\.env[[:space:]]+[^|]+@'                             # scp .env user@dst
  'curl[[:space:]]+[^|]*-[dF][[:space:]]+["'"'"']?@?[^|]*\.env'              # curl -d @.env
  'curl[[:space:]]+[^|]*--data(-binary|-urlencode)?[[:space:]]+["'"'"']?@[^|]*\.env'
  'nc[[:space:]]+[^|]+[[:space:]]+[0-9]+[[:space:]]*<[[:space:]]*[^|]*\.env'

  # R3-I-1: lua HTTP wrappers (covered for completeness)
  'lua[[:space:]]+-e[^|]*(/v1/var/|secretsmanager|/secrets/|\.env|provider_key)'

  # R3-I-4: psql -f arbitrary file execution
  'psql[[:space:]]+[^|]*-f[[:space:]]+[^|]+\.sql'

  # R3-I-6: compgen -e / set -o posix; set (env-dump cousins)
  '^[[:space:]]*compgen[[:space:]]+-e([[:space:]]+\||[[:space:]]*$)'
  'set[[:space:]]+-o[[:space:]]+posix.*set[[:space:]]*\|[[:space:]]*grep'
)

for pat in "${risky_patterns[@]}"; do
  if echo "$command" | grep -qE "$pat"; then
    if [[ $has_filter -eq 0 ]]; then
      cat >&2 <<EOF
[secret-guard] BLOCKED: command reads a secret-bearing source without a
value-REDACTING filter. Matched pattern: $pat

Why: raw secrets reaching Claude tool output are sent to Anthropic
servers + prompt-cached. Treat as public leak per CLAUDE.md "NEVER expose
secrets" rule + 2026-05-16 incident.

Acceptable filters (must REDACT, not just pass through):
  | jq 'keys'                            # field NAMES only, no values
  | jq '{safe_alias: .nested.safe_field}' # explicit safe-field allowlist
  | grep '^SAFE_PREFIX='                  # specific safe lines
  | wc -c                                 # count only
  | sha256sum                             # hash only
  >/dev/null   (NOT 2>/dev/null)          # stdout discard
  -o /dev/null                            # curl discard

NOT acceptable (Round 1/2 audit found these create silent bypasses):
  | jq .  / jq -r .  / jq --raw-output .  # identity, returns full input
  | cat / cat -n / tr / head / tail / fold # preserve content
  > /tmp/x.json   # writes file, can be cat'd later
  2> /dev/null    # only stderr discarded, stdout still flows
  | jq '.Items'   # returns full object — use 'keys' to list field names

Reviewed one-off bypass (logged to ~/.claude/logs/guard-bypass.log):
  ... # guard:ack: <reason ≥ 8 NON-WHITESPACE chars describing why>

Command was: $command
EOF
      exit 2
    fi
  fi
done

exit 0

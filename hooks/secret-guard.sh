#!/usr/bin/env bash
# PreToolUse hook — block raw reads of secret stores into LLM tool output.
#
# === THREAT MODEL + KNOWN LIMITATIONS (Read this before trusting the hook) ===
#
# What this hook IS:
#   A blacklist-based speed-bump that catches accidental secret reads emitted
#   by Claude (the LLM) in response to operator prompts. It covers the
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
#     they flow to LLM context unguarded. The companion PostToolUse hook
#     secret-scan.sh scans the output after the fact (detect + warn only, it
#     cannot undo the leak) — see its header and secret-hygiene.md §5.
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
#   - Claude-config manifest (Aria #179) has 3 known residual gaps, same
#     "regex has no positional/argument parsing" root cause as above, all
#     unfixed by #179 (need #138 for a real fix):
#       (a) prose-position full-path text — a heredoc/string literal that
#           merely CONTAINS the text `cat ~/.bashrc` (discussion, not a real
#           read) is indistinguishable from a real read at the regex layer;
#           use `# guard:ack:` for these.
#       (b) quote-delimited bare sensitive name — `grep '.bashrc' f`: the
#           char right before the name is `'`, which IS in the prefix
#           whitelist (see note above `_sg_compute_credit`), so this form
#           is NOT relieved by the #179 whitelist fix — it still triggers
#           as a false positive same as before; only a discussion-vs-real-
#           read distinction (needs #138) would fix it.
#       (c) bare-filename/glob variants with no path prefix — `cat
#           settings.json` (relative bare name) or `cat
#           ~/.claude/settings.*` (glob) fall outside every manifest-style
#           row's matching surface, exactly like the pre-existing .bashrc/
#           .env rows already do; not a regression introduced by #179, just
#           the manifest approach's inherent ceiling.
#
# Why this is still worth shipping:
#   The 2026-05-16 incident was a TYPICAL pattern — raw curl to Nomad var
#   endpoint, no jq filter, no malice. The hook prevents the same pattern +
#   ~80% of cousin patterns. Combined with operator awareness training (see
#   standards/conventions/secret-hygiene.md §1 principles) it's a
#   meaningful defense layer, not a guarantee.
#
# === Project extension + residual gaps (secret-net-l3-and-bypass-paths) ===
#
# Extension: <project root>/.aria/secret-guard.paths adds blocks without touching
#   this file. One LITERAL substring per line (case-insensitive, `#` comments, 4-200
#   bytes per entry, at most 200 entries, file at most 32 KiB); the project root is
#   CLAUDE_PROJECT_DIR, else the stdin cwd. It can only ADD: every built-in verdict
#   comes first, and the first 64 occurrences of an entry in one command are checked.
#   A missing or invalid file turns the extension off SILENTLY (the built-in list is
#   unaffected). Coverage = the readers of the built-in app.ini row + Read/Edit; the
#   Grep tool, redirected reads, `source`, `dd`, `xargs cat`, `find -exec` and the
#   65th occurrence onwards are not covered. List the SHORTEST distinctive substring
#   (a file name), not a full path. Details: secret-hygiene.md §5.6.
# Residual gaps, all unfixed on purpose:
#   - `systemctl status` and `docker inspect <container>` (full JSON with Config.Env)
#     are allowed: common health checks, the false-positive cost is too high.
#     Credential-shaped lines in their output are alerted after the fact by
#     secret-scan.sh (failed calls too).
#   - The shared BLOCKED text lists `Acceptable filters` such as `| grep '^SAFE_PREFIX='`.
#     The tight families (claude-config, app.ini, the ps / pgrep -a / top -c /
#     docker top rows, extension entries) give no credit to line filters, so a
#     retry that follows the text is blocked again; the text is unchanged on
#     purpose (secret-hygiene.md §2.5, note).
#   - Shell variable indirection (`f=...; cat "$f"`) is covered only in part: literal
#     assignments are expanded in a second pass (at most 16 assignments and 8 replacements
#     per variable; beyond those COUNTS the variable passes). The SIZE of the expansion is
#     bounded as well -- a value up to 4096 characters, a substituted segment up to 8192
#     characters and 65536 characters of substituted text per command -- and beyond a SIZE
#     limit the whole command is BLOCKED as too large to scan ("split it", fail-closed,
#     owner ruling 2026-10-14), never passed. Arrays, `read <<<`, quote-spliced paths, `cd`
#     + a relative name, globs, `set --`, `$(printf ...)` and variables across two tool
#     calls pass; the output side is left to secret-scan.sh.
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
#   Aria #179 (2026-08-22): claude-config manifest gap, dual-plane fix.
#         (1) Manifest: ~/.claude/settings.json / settings.local.json /
#             ~/.claude.json (legacy global config, holds MCP tokens) added
#             on BOTH planes — Bash-face reader/name pattern row (existing 12
#             readers + `jq`, the natural JSON reader; the real 2026-08-09
#             leak command was `jq -c '{model, env: (.env // {})}'
#             ~/.claude/settings.json`) AND Read/Edit-face :546 path regex;
#             python3 -c / node -e source groups (:785/:786) extended with
#             the same names, kept on those narrow rows (not merged into the
#             generic reader alternation, to avoid reopening prose FPs).
#         (2) Credit tightening (claude-config sources only, detected by
#             re-matching $_SG_CLAUDE_CFG against the segment, not by "which
#             pattern fired"): the `jq '{...}'` shape-credit and every line/
#             column filter credit (grep anchor, grep -v, sed, cut, awk) no
#             longer apply — shape/line-level filtering isn't reliable
#             redaction for JSON (values can span or share a line). Only
#             name-literal (`keys`/`length`/`paths`), count (`wc -[clw]`),
#             hash (sha*/md5sum), and discard (`>/dev/null` etc.) credits
#             still count. Non-claude-config sources: unchanged.
#         (3) Prefix whitelist (FP fix): a sensitive name only triggers the
#             match when the char immediately before it is whitelisted —
#             NAME family $_SG_PP_NAME (full basenames: shell-rc files,
#             claude-config): start/whitespace/`"`/`'`/`=`/`/`/`~`; SUFFIX
#             family $_SG_PP_SUFFIX (names that can be a basename tail:
#             .env/.envrc/.pem/.key/.p12/id_rsa/…): NAME set + word chars/
#             `*`/`.`/`-` (so `prod.env`, `*.env`, `a.b.env` still match).
#             Regex/alternation literal contexts (`(`, `|`, `\`, `{`, `[`)
#             are never a trigger position either family — fixes the issue
#             self-match FP (`grep -oE '(\.bashrc|...)' <this file>`).
#             Applied to 14 risky_patterns rows (13 pre-existing sibling
#             rows + the 1 new claude-config row above; the python3/node
#             rows count among the 13). `/`-rooted names inside those rows
#             stay on a plain [^|]* branch (Amendment-2). See
#             .aria/notes/secret-guard-179-pattern-rows.md for the full
#             row-by-row rationale of what's in/out of scope.
#         3 known residual gaps of (3) listed above under "Coverage gaps".
#   secret-net-l3-and-bypass-paths (10CG/aria-plugin#154, #203; 10CG/Aria#221):
#         (1) Forgejo / Gitea app.ini joins the manifest on BOTH planes (Bash
#             readers, python3 -c / node -e, Read/Edit path regex) with tight credit.
#         (2) Process-table enumeration rows: ps with full command lines, pgrep -a,
#             top -c, docker top, wrapped env dumps, /proc/<pid>/environ|cmdline.
#         (3) Project extension .aria/secret-guard.paths (above): literal substrings,
#             judged by the built-in app.ini judgement, can only add blocks.
#         (4) Shell-variable indirection, a second pass after every built-in verdict
#             allowed (partial coverage, see the residual gaps above).
#         (5) Two false positives removed: os.environ single-key reads and the
#             metadata-only jq forms keys_unsorted / map_values(length).
#         The BLOCKED text is unchanged (the advice on credentials in argv lives in
#         secret-hygiene.md §3.8, not in this text).
#
# Operator bypass (logged to ~/.claude/logs/guard-bypass.log):
#   Bash:        ... # guard:ack: <reason ≥ 8 non-whitespace chars describing why>
#   Read/Edit:   SECRET_GUARD_ACK_PATH="$file_path" claude ...
#                (one-shot — must re-set before each subsequent Read/Edit on same path)

# ── Re-exec under bash if launched by another shell (#154 root fix) ─────────
# Claude Code's hook runner executes `command` hooks via $SHELL and ignores the
# `#!/usr/bin/env bash` shebang. On macOS $SHELL is zsh, so this hook can arrive
# under zsh — where bash-isms (read -d '', [[ =~ ]], 0-based arrays, process
# substitution) misparse every field → tool_type empty → fail-closed → ALL
# tools blocked. That is the #154 deadlock's deeper cause: replacing `readarray`
# alone is insufficient because the whole body is bash-specific. Re-exec
# guarantees the body always runs under bash (3.2+, present on macOS as
# /bin/bash). POSIX-sh syntax only above this line so zsh/sh reach it.
if [ -z "${BASH_VERSION:-}" ]; then
  exec bash "$0" "$@"
fi

set -uo pipefail   # NOT -e — we control exit codes

# 复刻 `echo "$x" | grep -qE "$re"` 的记录语义: 按 \n 拆行, 任一行命中即真。
# $1 = 正则 (不加引号代入 =~, 否则退化为字面匹配); $2 = 待判字符串 (段)
_sg_line_match() {
  local _re="$1" _s="$2" _l
  while IFS= read -r _l || [[ -n "$_l" ]]; do
    [[ "$_l" =~ $_re ]] && return 0
  done <<< "$_s"
  return 1
}

# _sg_safe_to_split() — §What.1: does $1 "look safe" to split on top-level
# ; && ||? Return 0 = safe to split, return 1 = degrade (fall back to the
# whole-command legacy verdict). Heuristic, NOT a complete parse — see
# proposal.md §What.1 for the known-incomplete caveat (转出 8).
#
# Judged in this order (any hit ⇒ return 1 / degrade):
#   1. Block chars (quote-aware char scan): { } ( ) ` [[ ]] << <<<
#   2. Block-starting keyword (NOT quote-aware): for/while/until/if/case/select
#      at a command position + word boundary. BLOCK_KW_RE text below is
#      copied byte-for-byte from proposal.md §What.1 — do not edit it.
#   3. Scope-establishing keyword/builtin (NOT quote-aware, same precision as
#      #2): exec/time at a command position + word boundary.
#   4. Bare background `&` (NOT quote-aware, independent char scan — TASK-029 /
#      §What.1 row 4): a lone `&` that is not part of && / &> / >& / |& / <&.
_sg_safe_to_split() {
  local _cmd="$1"
  local _n=${#_cmd}
  local _i _c _prev _next
  local _state=unquoted   # unquoted | single | double | dsingle ($'...')

  # ── 1. Block chars — quote-aware char scan ────────────────────────────────
  # Shared quote/escape state machine (TASK-001 ↔ TASK-003 contract): escape
  # (\) takes priority, then single-quote, then double-quote, then $'...'.
  _i=0
  while (( _i < _n )); do
    _c="${_cmd:_i:1}"
    case "$_state" in
      unquoted)
        case "$_c" in
          '\')
            (( _i += 2 ))
            continue
            ;;
          '$')
            if [[ "${_cmd:_i+1:1}" == "'" ]]; then
              _state=dsingle
              (( _i += 2 ))
              continue
            fi
            ;;
          "'")
            _state=single
            ;;
          '"')
            _state=double
            ;;
          '{'|'}'|'('|')'|'`')
            return 1
            ;;
          '[')
            [[ "${_cmd:_i+1:1}" == "[" ]] && return 1
            ;;
          ']')
            [[ "${_cmd:_i+1:1}" == "]" ]] && return 1
            ;;
          '<')
            [[ "${_cmd:_i+1:1}" == "<" ]] && return 1
            ;;
        esac
        ;;
      single)
        [[ "$_c" == "'" ]] && _state=unquoted
        ;;
      double)
        if [[ "$_c" == '\' ]]; then
          (( _i += 2 ))
          continue
        elif [[ "$_c" == '"' ]]; then
          _state=unquoted
        fi
        ;;
      dsingle)
        if [[ "$_c" == '\' ]]; then
          (( _i += 2 ))
          continue
        elif [[ "$_c" == "'" ]]; then
          _state=unquoted
        fi
        ;;
    esac
    (( _i += 1 ))
  done

  # ── 2. Block-starting keyword (命令位置 且 词边界) ─────────────────────────
  # Regulation-grade text, copied byte-for-byte from proposal.md §What.1 —
  # do NOT rewrite, do NOT use bare ^, do NOT write (^|\n) (ERE \n is the
  # letter n, not a newline). `nl` and `BLOCK_KW_RE` must be local to THIS
  # function (SC-20 injection B probes exactly this scoping trap).
  local nl=$'\n'
  local BLOCK_KW_RE='(^|'"$nl"'|;|&&|\|\||\||&|!|do|then|else|elif)[[:space:]]*(for|while|until|if|case|select)\b'
  [[ "$_cmd" =~ $BLOCK_KW_RE ]] && return 1

  # ── 3. Scope-establishing keyword/builtin (exec/time), same precision ────
  # Independent regex — deliberately NOT merged into BLOCK_KW_RE.
  local SCOPE_KW_RE='(^|'"$nl"'|;|&&|\|\||\||&|!|do|then|else|elif)[[:space:]]*(exec|time)\b'
  [[ "$_cmd" =~ $SCOPE_KW_RE ]] && return 1

  # ── 4. Bare background `&` (TASK-029 / §What.1 row 4) ─────────────────────
  # Independent char scan — deliberately NOT sharing a regex with block/scope
  # keywords (SC-16 counterfactual classification depends on this judge
  # staying its own character scan). Per-character neighbor test, excluding
  # && / &> / >& / |& / <& ; a lone `&` left over ⇒ degrade.
  _i=0
  while (( _i < _n )); do
    _c="${_cmd:_i:1}"
    if [[ "$_c" == '&' ]]; then
      _prev=""
      (( _i > 0 )) && _prev="${_cmd:_i-1:1}"
      _next="${_cmd:_i+1:1}"
      if [[ "$_prev" == '&' || "$_next" == '&' ]]; then
        : # && — excluded
      elif [[ "$_next" == '>' ]]; then
        : # &> — excluded
      elif [[ "$_prev" == '>' || "$_prev" == '|' || "$_prev" == '<' ]]; then
        : # >& / |& / <& — excluded
      else
        return 1
      fi
    fi
    (( _i += 1 ))
  done

  return 0
}

# _sg_split_top() — §2: split $1 on top-level ; && || (quote/escape-aware,
# same state machine as step 1 of _sg_safe_to_split — TASK-001 ↔ TASK-003
# contract). Fills the global array _SG_SEGS. Does NOT split on: | (single
# pipe — filter semantics), newline, bare &, \; (escaped). Empty and
# whitespace-only segments are dropped; kept segment text is NOT trimmed.
# Only called after _sg_safe_to_split has already returned 0 (safe).
_sg_split_top() {
  local _cmd="$1"
  _SG_SEGS=()
  local _n=${#_cmd}
  local _i _c _seg
  local _seg_start=0
  local _state=unquoted   # unquoted | single | double | dsingle ($'...')

  _i=0
  while (( _i < _n )); do
    _c="${_cmd:_i:1}"
    case "$_state" in
      unquoted)
        case "$_c" in
          '\')
            (( _i += 2 ))
            continue
            ;;
          '$')
            if [[ "${_cmd:_i+1:1}" == "'" ]]; then
              _state=dsingle
              (( _i += 2 ))
              continue
            fi
            ;;
          "'")
            _state=single
            ;;
          '"')
            _state=double
            ;;
          ';')
            _seg="${_cmd:_seg_start:_i-_seg_start}"
            [[ -n "${_seg//[[:space:]]/}" ]] && _SG_SEGS+=("$_seg")
            (( _i += 1 ))
            _seg_start=$_i
            continue
            ;;
          '&')
            if [[ "${_cmd:_i+1:1}" == "&" ]]; then
              _seg="${_cmd:_seg_start:_i-_seg_start}"
              [[ -n "${_seg//[[:space:]]/}" ]] && _SG_SEGS+=("$_seg")
              (( _i += 2 ))
              _seg_start=$_i
              continue
            fi
            ;;
          '|')
            if [[ "${_cmd:_i+1:1}" == "|" ]]; then
              _seg="${_cmd:_seg_start:_i-_seg_start}"
              [[ -n "${_seg//[[:space:]]/}" ]] && _SG_SEGS+=("$_seg")
              (( _i += 2 ))
              _seg_start=$_i
              continue
            fi
            ;;
        esac
        ;;
      single)
        [[ "$_c" == "'" ]] && _state=unquoted
        ;;
      double)
        if [[ "$_c" == '\' ]]; then
          (( _i += 2 ))
          continue
        elif [[ "$_c" == '"' ]]; then
          _state=unquoted
        fi
        ;;
      dsingle)
        if [[ "$_c" == '\' ]]; then
          (( _i += 2 ))
          continue
        elif [[ "$_c" == "'" ]]; then
          _state=unquoted
        fi
        ;;
    esac
    (( _i += 1 ))
  done

  _seg="${_cmd:_seg_start:_i-_seg_start}"
  [[ -n "${_seg//[[:space:]]/}" ]] && _SG_SEGS+=("$_seg")
}

# ── Aria #179: claude-config 源名组 (单一定义, 两处消费: risky_patterns 行 +
# _sg_compute_credit 收紧模式检测; 两处字面量漂移是 spec What.1b 点名的风险) ──
# ~/.claude/settings.json / .claude/settings.local.json 的 env 节点是 Claude Code
# 存放 API token 的标准位置; ~/.claude.json 是 legacy 全局配置 (含 MCP token)。
_SG_CLAUDE_CFG='\.claude/+(\./+)*settings\.json|\.claude/+(\./+)*settings\.local\.json|\.claude\.json'

# ── Aria #179 What.3 + Amendment-1: 前置字符白名单 (两族, 各自单一白名单) ──
# Used as `READER[[:space:]]+([^|]*${PP})?(NAMES)`: the optional group lets a
# single-space bare form (`cat .bashrc`) match via the mandatory whitespace
# alone (R1 A1-M2 争用), while any other char directly before the sensitive
# name must be in the whitelist — regex/alternation literal contexts
# (`(`, `|`, `\`, `{`, `[`) are therefore never a trigger position.
#   NAME family  (full basenames: shell rc files, claude config):
#     start / whitespace / quotes / `=` / `/` / `~`
#   SUFFIX family (names that can be a basename tail: .env .pem .key id_rsa…):
#     the NAME set + word chars + `*` + `.` + `-` (prod.env / *.env / a.b.env)
# Names that START with `/` (/etc/profile, /.aws/credentials, /.kube/config …)
# are NOT whitelisted at all: the char before their leading `/` is the tail of
# a path prefix (`~`, `}`, `)`, a word char …), not a basename boundary, so
# they keep the plain `[^|]*` branch (Amendment-2, Phase B review C-1 — the
# first TASK-010 cut whitelisted them and let `cat ${HOME}/.aws/credentials`
# through).
_SG_PP_NAME="(^|[[:space:]\"'=/])"
_SG_PP_SUFFIX="(^|[[:space:]\"'=/*A-Za-z0-9_.-])"

# ── secret-net-l3-and-bypass-paths (W8 / W11): shared names, single definition, several consumers ──
# W8: server-side config files of Forgejo / Gitea (JWT_SECRET, SECRET_KEY, INTERNAL_TOKEN live in app.ini; 10CG/aria-plugin#203). A path component holding
# `forgejo` or `gitea` (a word-internal prefix is fine: `git-forgejo`), then any non-blank non-quote characters of the same path, then `app.ini`; or
# `custom/conf/app.ini`. The right boundary (no letter / digit / `_` right after `app.ini`: the backup `app.ini.bak` is covered, `app.inix` is not) is added by
# each consumer. Consumers: the Bash-face reader row, the python3 -c / node -e source groups, the credit tightening below; the Read/Edit-face regex spells the
# same group in lower case. No \b anywhere in the new text (BSD regex does not support it, same family as 10CG/aria-plugin#144).
_SG_SRVCFG='[A-Za-z0-9._-]*(forgejo|gitea)[^[:space:]|;&"'"'"']*app\.ini|custom/conf/app\.ini'
# The printing readers of the W8 row: the 13 of the claude-config row plus nl tac rev sort uniq cut paste diff cmp comm xxd od hexdump base64 column fold (29).
_SG_READERS_PRINT='cat|grep|egrep|fgrep|rg|head|tail|less|more|strings|awk|sed|jq|nl|tac|rev|sort|uniq|cut|paste|diff|cmp|comm|xxd|od|hexdump|base64|column|fold'
# W11: process-table enumeration that prints argv / environ -- ps (procps semantics) in its argv-exposing spellings, pgrep / pstree `-a`, top `-c`, docker top,
# docker ps --no-trunc -- at a command position behind an optional launcher / absolute directory prefix, and behind remote / shell wrappers. The three rule rows in
# risky_patterns spell the same text as literals (a rule row that is only a variable is an empty string for the census, SC-31 31c); the copies below are what the
# credit tightening matches. _SG_PROCTAB_ALL is the tight copy: the ps family ONLY -- the env / printenv alternatives of the wrapper row exist in the rule row
# alone, they keep the baseline credit (a dump followed by `| cut -d= -f1` or `| wc -l` stays allowed). The two copies must not drift (SC-22 22bm / 22bn).
_SG_PROCTAB='(^|[;&|(){]|`|[[:cntrl:]])[[:blank:]]*((then|do|else|elif)[[:space:]]+)?((/[^[:space:]|;&"'"'"'`$()<>]*/)?(sudo|doas|nice|timeout|xargs|nohup|stdbuf|env|time|eval|setsid|ionice|unbuffer|command|exec)([[:space:]]+(-[^[:space:]]+([[:space:]]+[^-[:space:]|;&()<>`"'"'"'][^[:space:]|;&()<>`"'"'"']*)?|[0-9][0-9.]*[smhd]?|[A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*))*[[:space:]]+)?((/[^[:space:]|;&"'"'"'`$()<>]*/)?(ps[[:blank:]]+([a-zA-Z]+([^[:alnum:]_-]|$)|[0-9]+([^[:alnum:]_.-]|$)|([^|;&]*[[:blank:]])?-[a-zA-Z]*[fF]|([^|;&]*[[:blank:]])?(-[a-zA-Z]*[oO]|--format)[[:blank:]=]*[^[:blank:]|;&]*(args|cmd|command)|([^|;&]*[[:blank:]])?-[a-zA-Z]*O|([^|;&]*[[:blank:]])?-[a-zA-Z]*x[a-zA-Z]*([^[:alnum:]_-]|$)|([^|;&]*[[:blank:]])?-[a-zA-Z]*u[[:blank:]]*($|[|;&)<>]))|pgrep[[:blank:]]+([^|;&]*[[:blank:]])?(-[a-zA-Z]*a|--list-full)|pstree[[:blank:]]+([^|;&]*[[:blank:]])?(-[a-zA-Z]*a|--arguments)|top[[:blank:]]+([^|;&]*[[:blank:]])?-[a-zA-Z]*c))'
_SG_PS_REMOTE_T='(ssh|docker[[:space:]]+(compose[[:space:]]+)?exec|kubectl[[:space:]]+exec|nomad[[:space:]]+alloc[[:space:]]+exec|pct[[:space:]]+exec|lxc[[:space:]]+exec|podman[[:space:]]+exec|(sh|bash|zsh|dash)[[:space:]]+-c|watch)[^|]*[[:space:]'"'"'"(`](((/[^[:space:]|;&"'"'"'`$()<>]*/)?(ps[[:blank:]]+([a-zA-Z]+([^[:alnum:]_-]|$)|[0-9]+([^[:alnum:]_.-]|$)|([^|;&]*[[:blank:]])?-[a-zA-Z]*[fF]|([^|;&]*[[:blank:]])?(-[a-zA-Z]*[oO]|--format)[[:blank:]=]*[^[:blank:]|;&]*(args|cmd|command)|([^|;&]*[[:blank:]])?-[a-zA-Z]*O|([^|;&]*[[:blank:]])?-[a-zA-Z]*x[a-zA-Z]*([^[:alnum:]_-]|$)|([^|;&]*[[:blank:]])?-[a-zA-Z]*u[[:blank:]]*($|[|;&)<>]))|pgrep[[:blank:]]+([^|;&]*[[:blank:]])?(-[a-zA-Z]*a|--list-full)|pstree[[:blank:]]+([^|;&]*[[:blank:]])?(-[a-zA-Z]*a|--arguments)|top[[:blank:]]+([^|;&]*[[:blank:]])?-[a-zA-Z]*c)))'
_SG_PS_DOCKER='(docker|podman)[[:space:]]+((compose|container)[[:space:]]+)?top([^[:alnum:]_-]|$)|(docker|podman)[[:space:]]+(container[[:space:]]+)?(ps|ls)[[:space:]]+([^|;&]*[[:space:]])?--no-trunc'
_SG_PROCTAB_ALL="(${_SG_PROCTAB}|${_SG_PS_REMOTE_T}|${_SG_PS_DOCKER})"
# W11 /proc: the pid position of /proc/<pid>/environ|cmdline -- self, thread-self, digits, $$ $!, a glob token holding * or ?, $name, ${...}, $(...). A placeholder
# word (/proc/<pid>/cmdline, /proc/[pid]/environ) is prose, not a pid.
_SG_PIDTOK='(self|[0-9]+|[^/[:space:]]*[*?][^/[:space:]]*|\$\{[^}]*\}|\$[A-Za-z_][A-Za-z0-9_]*|\$\([^)]*\)|thread-self|\$[$!])'

_sg_compute_credit() {
  local seg="$1"
  # ── Filter detection (only REDACTING filters count) ────────────────────────
  # Round 1 removed: cat/tr/head/tail/fold (preserve content), > file / 2> / >>
  # Round 2 fixes:
  #   - R2-C-1: `jq -r .` raw-flag identity now also rejected
  #   - R2-C-10: `2>/dev/null` (stderr-only) no longer counts (was: any `>`)
  local has_filter=0

  # ── Aria #179 What.1b: claude-config 收紧模式 ─────────────────────────────
  # Detected by re-matching the source-name group against $seg (NOT by "which
  # risky_pattern fired" — this function has no such channel), so a mixed
  # segment (`cat ~/.env ~/.claude/settings.json | ...`) is always tightened,
  # with no ordering dependence. In tight mode only NAME-ONLY / COUNT / HASH /
  # DISCARD credits count: the `jq '{...}'` shape credit is pure shape (no
  # field-name check) and would hand back the exact `env` node these files
  # exist to protect; line/column filters (grep anchor, grep -v, sed, cut, awk)
  # are unreliable redaction for JSON (values span/nest lines). Non-claude
  # sources keep every existing credit rule unchanged.
  # W8 / W11 (secret-net-l3-and-bypass-paths): the same tightening for the Forgejo / Gitea app.ini name group and for the ps family of the process-table rows --
  # `ps -ef | grep -v grep` and `cat .../app.ini | grep '^JWT_SECRET'` still print whole command lines / the credential line, so a row-level filter is no credit.
  # wc / hash / discard / name-only credits stay.
  local tight=0
  if [[ "$seg" =~ ($_SG_CLAUDE_CFG|$_SG_SRVCFG) ]] || [[ "$seg" =~ $_SG_PROCTAB_ALL ]]; then
    tight=1
  fi

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
  if _sg_line_match "\|[[:space:]]*jq([[:space:]]+(-[a-zA-Z]+|--[a-z-]+))*[[:space:]]+[\"']?(.+\|[[:space:]]*)?(keys|length|paths|leaf_paths)[\"']?[[:space:]]*(\$|\|)" "$seg"; then
    has_filter=1
  fi
  # W12 (secret-net-l3-and-bypass-paths): anchored metadata-only forms -- the program is quoted, may start with ONE simple dotted path plus `|`, then exactly
  # one token (keys_unsorted | map_values(length)), and the closing quote follows the token at once. Deliberately NOT added to the word list above: that list
  # accepts anything after `word |`, so `jq 'keys_unsorted | $ENV'` would pass. No tight gate: the form is valid under the claude-config tightening too.
  if _sg_line_match "\|[[:space:]]*jq([[:space:]]+(-[a-zA-Z]+|--[a-z-]+))*[[:space:]]+[\"'](\.[A-Za-z_][A-Za-z0-9_.]*[[:space:]]*\|[[:space:]]*)?(keys_unsorted|map_values\(length\))[\"'][[:space:]]*(\$|\|)" "$seg"; then
    has_filter=1
  fi
  # Whitelisted: `jq '{alias: .safe_field}'` — single-line allowlist projection.
  # Recognize the `{...}` object-construction shape as projection allowlist.
  if [[ $tight -eq 0 ]] && _sg_line_match "\|[[:space:]]*jq([[:space:]]+(-[a-zA-Z]+|--[a-z-]+))*[[:space:]]+[\"']?\{" "$seg"; then
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
  if [[ $tight -eq 0 ]] && _sg_line_match '\|[[:space:]]*grep([[:space:]]+-[a-zA-Z]+)*[[:space:]]+[^[:space:]]*[\^\$]' "$seg"; then
    has_filter=1   # grep with anchor (probably real filtering)
  fi
  if [[ $tight -eq 0 ]] && _sg_line_match '\|[[:space:]]*grep[[:space:]]+(-v|--invert-match)\b' "$seg"; then
    has_filter=1   # grep -v inverts (probably filtering)
  fi
  if [[ $tight -eq 0 ]] && _sg_line_match '\|[[:space:]]*sed[[:space:]]+[^[:space:]]*([Ss]/[^/]*/|[0-9]+d|[Dd])' "$seg"; then
    has_filter=1   # sed s/// or delete
  fi
  # cut requires single field (not range like -f1- which is all-fields identity)
  if [[ $tight -eq 0 ]] && _sg_line_match '\|[[:space:]]*cut[[:space:]]+-[df][[:space:]]*[^[:space:]-]' "$seg"; then
    has_filter=1   # cut -d= or -f1 (specific field)
  fi
  # awk content can contain spaces inside quotes; match `$N` anywhere in quoted arg
  if [[ $tight -eq 0 ]] && _sg_line_match "\|[[:space:]]*awk[[:space:]]+['\"][^'\"]*\\\$[0-9]" "$seg"; then
    has_filter=1   # awk '{print $N}'
  fi
  if [[ $tight -eq 0 ]] && _sg_line_match "\|[[:space:]]*awk[[:space:]]+['\"][^'\"]*/[^/]+/" "$seg"; then
    has_filter=1   # awk '/regex/...'
  fi
  # R2-C-10 fix: only stdout-redirect to /dev/null counts. stderr-only (2>) and
  # combined (&>) need separate handling.
  #   `>/dev/null` and `>  /dev/null` — stdout discard, safe
  #   `&>/dev/null` — both discard, safe (but rarely seen)
  #   `2>/dev/null` — only stderr discard, stdout still flows: NOT a filter
  if _sg_line_match '([^0-9&]|^)>[[:space:]]*/dev/null' "$seg"; then
    has_filter=1
  fi
  if _sg_line_match '&>[[:space:]]*/dev/null' "$seg"; then
    has_filter=1
  fi
  # curl -o /dev/null / --silent without explicit other output
  if _sg_line_match '(-o[[:space:]]+/dev/null|--output[[:space:]]+/dev/null)' "$seg"; then
    has_filter=1
  fi
  # wc / sha256sum / md5sum — emit count/hash, not content
  if _sg_line_match '\|[[:space:]]*wc[[:space:]]+-[clw]' "$seg"; then
    has_filter=1
  fi
  if _sg_line_match '\|[[:space:]]*(sha256sum|md5sum|sha1sum|sha512sum)\b' "$seg"; then
    has_filter=1
  fi

  [[ $has_filter -eq 1 ]]
}

# ── secret-net-l3-and-bypass-paths (W9 / W10 / W13) ──
# Every function that _sg_judge_one and _sg_per_segment_eval call, directly or through another helper (_sg_core_eval, _sg_emit_blocked, _sg_vx_*, _sg_ext_* and their
# helpers), is defined HERE, above the unit-test sourcing gate: the SC-8 latency gate of the test suite sources this part and then pulls the two functions out by their
# anchors; a helper below the gate is command-not-found (rc=127) in that harness and the gate would stay green on a no-op (W14). The two anchored names and the closing
# `}` on a line of its own must not change. _sg_redact_echo (below the gate since the baseline) only feeds echo text that is discarded in that harness.

# W10 -- path through a shell variable (partial coverage): a SECOND pass that runs only after EVERY built-in verdict allowed (_sg_vx_pass), so the built-in verdict is never
# postponed or changed and the pass can only add blocks. Literal assignments are collected from the whole command (NAME=value, `for NAME in list`, one level of chaining; at
# most 16 assignments and 8 replacements per variable); every segment (the whole command when it degraded) that mentions $NAME or ${NAME} is judged once more with the
# values substituted in. TEXT ONLY: prefix + suffix concatenation with the remainder taken BY LENGTH (${s:N}); no eval (a value may hold a command substitution or back
# quotes: they must never run inside the hook), no ${s//p/r} (bash 5.2 patsub_replacement and the quote semantics of bash < 4.3 disagree about quotes and `&` in the
# replacement), no ${s#*"$pat"} (O(n^2) when the hit sits late in a long string).
# LENGTH BUDGET (review M6; fail-CLOSED, owner ruling 2026-10-14): without it the judged string is the segment plus references x value length, and one level of chaining
# multiplies a value by 8, so a 5 KB command overran the 5 s hook timeout (and a timeout lets the command through). Three limits, counted in characters. Beyond ANY of them the
# whole command is BLOCKED with a text of its own ("command too large to scan for secrets ... split it": _sg_emit_blocked with the 4th word oversize, status 2) and never
# passed: a copy that is not judged is a way past the guard, and padding a value or a chain would be the recipe. The oversize string is never built, expanded further, judged
# or scanned: the pass stops at the first overrun and nothing behind it is touched, so an overrun costs no more than the budgeted work in front of it (blocking is as cheap as
# passing was; the 5 s timeout and its fail-open, 10CG/aria-plugin#216, are not touched). (The COUNTS above -- 16 assignments, 8 replacements, 8 for statements -- are another
# bound and still pass beyond the limit, SC-21 21y.) (1) _SGV_VMAX: a value longer than that (as collected, or after chaining) blocks the
# command whether or not the variable is mentioned: _sg_vx_collect stops at it and returns 2; 4096 is PATH_MAX, a longer value is not one path. (2) _SGV_SMAX: a substituted
# copy (a segment, or the whole command) that would become longer blocks the command (status 2 of _sg_vx_apply; the W9 extension's look at the substituted whole command, after
# the pass, blocks on it only when an extension is in effect -- without one nothing is left unjudged). 8192 because a BLOCK verdict costs the square of the copy length
# (_sg_compute_credit on one long line: about 0.9 s at 8 KB, 3 s at 16 KB, 13 s at 32 KB) and a verdict that arrives after the timeout is lost. The limit counts the whole judged
# string, not its growth: a segment (in whole-command mode: the command) over 8192 characters that mentions a collected variable is blocked however small the value is.
# (3) _SGV_TMAX: all copies of one command together; once used up the command is blocked -- what many dense segments can cost is bounded too.
# _sg_vx_collect, _sg_vx_apply and _SG_SUB are names of the contract, like _sg_vx_pass: the budget probes of the suite use them.
_SGV_N=(); _SGV_V=()
_SG_SUB=""
_SG_RP=""
_SGV_VMAX=4096
_SGV_SMAX=8192
_SGV_TMAX=65536
# ── Time-budget fail-closed (secret-guard-time-budget-failclosed C; resolves 10CG/aria-plugin#216) ──
# Claude Code kills a PreToolUse hook at 5 s and then FAIL-OPENS (lets the command through, UNSCANNED). The expensive second pass (W10 variable expansion) and the W9 extension
# look can, on a slow platform (Windows MINGW64 measured ~2.6x Linux, #219), run past 5 s on a command that is still within the SIZE budget (_SGV_*). So the guard keeps its OWN
# time upper bound N (< CC's 5 s): once an expensive leg has spent N seconds it STOPS at the next boundary and BLOCKs (fail-closed), rather than letting CC's 5 s timeout fail-open.
# SECONDS (a bash builtin, 3.2-compatible, 1 s granularity -- NOT EPOCHREALTIME, which is bash 5+) is read at each leg boundary via _sg_over_budget. N defaults to 3 (owner ruling
# 2026-10-16: ~2 s of headroom under 5 s for hook teardown + the 1 s granularity error); SECRET_GUARD_TIME_BUDGET_S overrides it (a missing / empty / non-integer value falls back
# to 3 and never errors; a low value such as 0 forces the first checkpoint for deterministic tests). The clock _SG_T0 is reset at the START of _sg_vx_collect -- the single choke
# point every expensive leg passes through first -- so the budget measures THIS command's judgement (not wall time since the process started) and stays fresh when the test suite
# sources the hook and calls the functions directly. INVARIANT: the built-in direct judgement (_sg_core_eval, the #154 core) runs BEFORE any of this, is NEVER gated by the timer,
# and stays fast; the `# guard:ack` escape and the _SGV_* size budget are unchanged; fail-closed means an overrun BLOCKs (exit 2), never allows.
_SG_T0=$SECONDS
_SG_TIME_BUDGET=3
_sg_time_budget() {   # resolve SECRET_GUARD_TIME_BUDGET_S -> _SG_TIME_BUDGET (fork-free; default 3 on missing / empty / non-integer; 10# so a leading zero is not read as octal)
  case "${SECRET_GUARD_TIME_BUDGET_S:-}" in
    ''|*[!0-9]*) _SG_TIME_BUDGET=3 ;;
    *) _SG_TIME_BUDGET=$(( 10#${SECRET_GUARD_TIME_BUDGET_S} )) ;;
  esac
}
_sg_over_budget() {   # return 0 (true) once this judgement has spent >= the budget since _SG_T0 (budget resolved once at each reset site, not per checkpoint)
  (( SECONDS - _SG_T0 >= _SG_TIME_BUDGET ))
}
# _sg_vx_replace S PAT REP [MAX] : literal replace-all of PAT in S, at most 8 replacements -> _SG_RP; with MAX (characters) it stops with status 1 as soon as the result would be
# longer than MAX (_SG_RP is then S unchanged)
_sg_vx_replace() {
  local s="$1" pat="$2" rep="$3" max="${4:-0}" out="" g=0 pre
  _SG_RP="$s"
  while (( g < 8 )) && [[ "$s" == *"$pat"* ]]; do
    g=$((g+1)); pre="${s%%"$pat"*}"; out="${out}${pre}${rep}"; s="${s:$(( ${#pre} + ${#pat} ))}"
    (( max > 0 && ${#out} + ${#s} > max )) && return 1
  done
  _SG_RP="${out}${s}"
}
# _sg_vx_collect S : fills _SGV_N / _SGV_V from S. Status 0 = collected, 2 = a value is longer than _SGV_VMAX (as collected, or after one level of chaining): it stops at that
# value at once -- the value is neither stored nor looked at again and nothing behind it is collected -- and the caller blocks the command.
_sg_vx_collect() {
  _SG_T0=$SECONDS; _sg_time_budget   # reset the time-budget clock + resolve the budget once here: the single choke point every expensive leg (this collect's i×j chaining, _sg_vx_pass, the W9 extension look) passes first
  local rest="$1" m name val i j n=0 dup pre
  local _q="'" _d='"' _b='`'
  _SGV_N=(); _SGV_V=()
  [[ "$rest" == *'$'* && "$rest" == *=* ]] || [[ "$rest" == *'$'* && "$rest" == *' in '* ]] || return 0
  local re="(^|[;&|[:space:](${_d}${_b}${_q}])((export|declare|local|readonly|typeset)[[:space:]]+(-[a-zA-Z]+[[:space:]]+)*)?([A-Za-z_][A-Za-z0-9_]*)=(${_d}([^${_d}]*)${_d}|${_q}([^${_q}]*)${_q}|\\\$\\([^)]*\\)|${_b}[^${_b}]*${_b}|[^[:space:];&|)${_d}${_b}${_q}]*)"
  while (( n < 16 )) && [[ "$rest" =~ $re ]]; do
    (( n += 1 ))
    m="${BASH_REMATCH[0]}"; name="${BASH_REMATCH[5]}"; val="${BASH_REMATCH[6]}"
    pre="${rest%%"$m"*}"; rest="${rest:$(( ${#pre} + ${#m} ))}"
    [[ "$val" == \"*\" && ${#val} -ge 2 ]] && val="${val:1:${#val}-2}"
    [[ "$val" == \'*\' && ${#val} -ge 2 ]] && val="${val:1:${#val}-2}"
    (( ${#val} > _SGV_VMAX )) && return 2
    [[ -z "$val" || "$val" == *"\$$name"* || "$val" == *"\${$name}"* ]] && continue
    dup=0
    for (( i = 0; i < ${#_SGV_N[@]}; i++ )); do
      [[ "${_SGV_N[i]}" == "$name" && "${_SGV_V[i]}" == "$val" ]] && dup=1
    done
    (( dup )) || { _SGV_N+=("$name"); _SGV_V+=("$val"); }
  done
  rest="$1"; n=0
  local rf="(^|[;&|[:space:](])for[[:space:]]+([A-Za-z_][A-Za-z0-9_]*)[[:space:]]+in[[:space:]]+([^;&|)]*)"
  while (( n < 8 )) && [[ "$rest" =~ $rf ]]; do
    (( n += 1 ))
    m="${BASH_REMATCH[0]}"; name="${BASH_REMATCH[2]}"; val="${BASH_REMATCH[3]}"
    pre="${rest%%"$m"*}"; rest="${rest:$(( ${#pre} + ${#m} ))}"
    (( ${#val} > _SGV_VMAX )) && return 2
    [[ -z "$val" ]] && continue
    _SGV_N+=("$name"); _SGV_V+=("$val")
  done
  for (( i = 0; i < ${#_SGV_N[@]}; i++ )); do
    for (( j = 0; j < ${#_SGV_N[@]}; j++ )); do
      (( i == j )) && continue
      [[ -z "${_SGV_V[j]}" ]] && continue
      _sg_over_budget && return 3   # time-budget fail-closed: the O(vars^2) chaining is over budget -> status 3, caller BLOCKs (distinct from status 2 = value over _SGV_VMAX)
      if _sg_vx_replace "${_SGV_V[i]}" "\${${_SGV_N[j]}}" "${_SGV_V[j]}" "$_SGV_VMAX"; then _SGV_V[i]="$_SG_RP"; else return 2; fi
      if _sg_vx_replace "${_SGV_V[i]}" "\$${_SGV_N[j]}" "${_SGV_V[j]}" "$_SGV_VMAX"; then _SGV_V[i]="$_SG_RP"; else return 2; fi
    done
  done
  return 0
}
# _sg_vx_apply S : S with the collected values substituted -> _SG_SUB. Status 0 = a copy was built, 1 = nothing to substitute, 2 = the copy would be longer than _SGV_SMAX (not
# built, _SG_SUB stays S; the caller blocks the command). Per variable: ${NAME} through _sg_vx_replace, then $NAME with the same prefix accumulation (the already substituted text is never scanned again;
# the remainder keeps the character that ended the match, so $f$f works), at most 8 times.
_sg_vx_apply() {
  local s="$1" i n v m tail pre out guard changed=1
  _SG_SUB="$s"
  (( ${#_SGV_N[@]} )) || return 1
  [[ "$s" == *'$'* ]] || return 1
  for (( i = 0; i < ${#_SGV_N[@]}; i++ )); do
    n="${_SGV_N[i]}"; v="${_SGV_V[i]}"
    [[ -n "$v" ]] || continue
    if [[ "$s" == *"\${$n}"* ]]; then _sg_vx_replace "$s" "\${$n}" "$v" "$_SGV_SMAX" || return 2; s="$_SG_RP"; changed=0; fi
    out=""; guard=0
    while (( guard < 8 )) && [[ "$s" =~ \$${n}([^A-Za-z0-9_]|$) ]]; do
      (( guard += 1 ))
      m="${BASH_REMATCH[0]}"; tail="${BASH_REMATCH[1]}"
      if [[ -z "$tail" ]]; then pre="${s%"$m"}"; else pre="${s%%"$m"*}"; fi
      s="${s:$(( ${#pre} + ${#m} - ${#tail} ))}"
      [[ "$pre" == *\\ ]] && pre="${pre%\\}"
      out="${out}${pre}${v}"; changed=0
      (( ${#out} + ${#s} > _SGV_SMAX )) && return 2
    done
    (( guard )) && s="${out}${s}"
  done
  _SG_SUB="$s"
  return $changed
}
# _sg_vx_pass CMD MODE : the second pass -- judge the substituted copies. MODE is whole or segment, as _sg_core_eval left it in _SG_MODE (in segment mode _SG_SEGS holds
# the segments). The function name is a contract: the fault-injection and evaluation-order probes locate it by name. An overrun of the length budget (a value, a copy, the total)
# ends the pass at once with an oversize BLOCK (the size text of _sg_emit_blocked, status 2): nothing behind the overrun is built or judged.
_sg_vx_pass() {
  local cmd="$1" mode="$2" seg rc ar cr spent=0
  _sg_vx_collect "$cmd"
  cr=$?
  if [[ $cr -eq 3 ]]; then   # time-budget fail-closed: the chaining in _sg_vx_collect ran out of time
    _sg_emit_blocked "time" "$cmd" "$mode" timeout
    return 2
  fi
  if [[ $cr -eq 2 ]]; then
    _sg_emit_blocked "a variable value is longer than $_SGV_VMAX characters" "$cmd" "$mode" oversize
    return 2
  fi
  (( ${#_SGV_N[@]} )) || return 0
  if [[ "$mode" == whole ]]; then
    if _sg_over_budget; then   # time-budget fail-closed before the O(copy^2) whole-command judgement
      _sg_emit_blocked "time" "$cmd" whole timeout
      return 2
    fi
    _sg_vx_apply "$cmd"
    ar=$?
    if [[ $ar -eq 2 ]]; then
      _sg_emit_blocked "the command is longer than $_SGV_SMAX characters after variable expansion" "$cmd" whole oversize
      return 2
    fi
    if [[ $ar -eq 0 ]]; then _sg_judge_one "$_SG_SUB" whole; return $?; fi
    return 0
  fi
  for seg in "${_SG_SEGS[@]}"; do
    if _sg_over_budget; then   # time-budget fail-closed before each per-segment _sg_vx_apply / _sg_judge_one (the O(copy^2) hot leg)
      _sg_emit_blocked "time" "$cmd" segment timeout
      return 2
    fi
    _sg_vx_apply "$seg"
    ar=$?
    [[ $ar -eq 1 ]] && continue
    if [[ $ar -eq 2 ]]; then
      _sg_emit_blocked "a command segment is longer than $_SGV_SMAX characters after variable expansion" "$cmd" segment oversize
      return 2
    fi
    spent=$(( spent + ${#_SG_SUB} ))
    if (( spent > _SGV_TMAX )); then
      _sg_emit_blocked "the command segments together are longer than $_SGV_TMAX characters after variable expansion" "$cmd" segment oversize
      return 2
    fi
    _sg_judge_one "$_SG_SUB" segment
    rc=$?
    [[ $rc -ne 0 ]] && return "$rc"
  done
  return 0
}

# W9 -- project-level extension <project root>/.aria/secret-guard.paths: one LITERAL substring per line; it can only ADD blocks (the built-in verdict always comes first).
# ALL extension code lives in _sg_ext_* functions that are called ONLY through command substitution $( ... ): an internal error (set -u, exit, command not found) kills
# that subshell alone, and the caller treats every output other than the literal sentinel BLOCK as "extension not in effect". The built-in verdict and its fail-closed
# path are never touched (10CG/Aria#154 session-deadlock lesson). Entries and the command text are data: sliced, concatenated and compared as fixed strings, never
# evaluated, expanded or used as a pattern.
_sg_ext_root() {   # prints the project root (CLAUDE_PROJECT_DIR, else stdin cwd) or nothing
  local r="${CLAUDE_PROJECT_DIR:-}"
  if [[ -z "$r" && "$input" == *'"cwd"'* ]]; then
    r="$(printf '%s' "$input" | jq -r '.cwd // ""' 2>/dev/null | tr -d '\r')"
  fi
  printf '%s' "$r"
}
# _sg_ext_entries : the valid entries of the extension file, lower-cased, one per line; prints nothing when the extension is not in effect (no project root, not a
# readable regular file, > 32 KiB, a NUL byte, no valid entry, > 200 valid entries). An entry has 4..200 BYTES and holds an ASCII letter / digit or a non-ASCII byte;
# comment lines, blank lines, CRs, a leading UTF-8 BOM and surrounding blanks are dropped. Byte semantics: LC_ALL=C is exported for the readers, so lengths and the
# case folding (ASCII letters only) do not depend on the caller's locale; sed only (mawk counts bytes, gawk counts characters under UTF-8).
_sg_ext_entries() {   # prints the valid entries (lower-cased, one per line); prints nothing when the extension is not in effect
  local root f size
  local -x LC_ALL=C
  root="$(_sg_ext_root)"
  [[ -n "$root" ]] || return 0
  f="$root/.aria/secret-guard.paths"
  [[ -f "$f" && -r "$f" ]] || return 0
  size="$(wc -c < "$f" | tr -d ' ')"
  (( size <= 32768 )) || return 0
  tr -d '\000' < "$f" | cmp -s - "$f" || return 0
  local out
  out="$(tr -d '\r' < "$f" | tr '[:upper:]' '[:lower:]' | sed -E -e $'1s/^\xef\xbb\xbf//' -e 's/^[[:space:]]+//' -e 's/[[:space:]]+$//' -e '/^#/d' -e '/^.{4,200}$/!d' -e $'/[a-z0-9\x80-\xff]/!d')"
  [[ -n "$out" ]] || return 0
  local n
  n="$(printf '%s\n' "$out" | wc -l | tr -d ' ')"
  if (( n > 200 )); then   # more than 200 valid entries: the whole file is ignored, not truncated
    return 0
  fi
  printf '%s\n' "$out"
}
# _sg_ext_subst TEXT : TEXT with the first 64 occurrences of any entry (fixed strings, one grep pass, case-insensitive) replaced by the built-in app.ini name;
# prints nothing when no entry occurs.  Byte semantics: `grep -b` gives BYTE offsets, so the slicing counts bytes too (LC_ALL=C, exported).
_sg_ext_subst() {
  local text="$1" hits line off match out="" pos=0 n=0
  local -x LC_ALL=C
  hits="$(grep -oFib -f <(_sg_ext_entries) <(printf '%s' "$text") 2>/dev/null)"
  [[ -n "$hits" ]] || return 0
  while IFS= read -r line; do
    n=$((n+1)); (( n > 64 )) && break
    off="${line%%:*}"; match="${line#*:}"
    out="${out}${text:pos:off-pos}/etc/gitea/app.ini "
    pos=$(( off + ${#match} ))
  done <<< "$hits"
  printf '%s' "${out}${text:pos}"
}
# _sg_ext_pass TEXT : prints the sentinel BLOCK iff the BUILT-IN judgement of the substituted copy (_sg_ext_subst) blocks, nothing otherwise (also when no entry occurs).
# The judgement is _sg_core_eval itself -- _sg_safe_to_split / _sg_split_top / _sg_judge_one, tight credit by the app.ini name -- not a second state machine, so the
# extension agrees with the built-in app.ini rows on every command shape by construction. Its stdout / stderr (the BLOCKED text) are discarded here; the caller prints it.
_sg_ext_pass() {
  local sub
  sub="$(_sg_ext_subst "$1")"
  [[ -n "$sub" ]] || return 0
  _sg_over_budget && { printf 'TIME'; return 0; }   # time-budget fail-closed: an extension is in effect and matched, but the whole-string look is over budget -> sentinel TIME
  _sg_core_eval "$sub" >/dev/null 2>&1
  [[ $? -eq 2 ]] && printf 'BLOCK'
  return 0
}

_sg_ext_path_pass() {   # Read/Edit face: entry (lower-cased) as a literal substring of the path (grep -F -i, one pass)
  local p="$1"
  local -x LC_ALL=C
  if grep -qFi -f <(_sg_ext_entries) <(printf '%s' "$p") 2>/dev/null; then printf 'BLOCK'; fi
  return 0
}

# _sg_emit_blocked PAT SEG MODE [oversize] : the (unchanged) BLOCKED text, shared by every block path. With the 4th word `oversize` it prints the SIZE text instead (W10 length
# budget, fail-closed): nothing was matched, the command is too large to be checked; PAT then names the limit that was hit, SEG and MODE are not used. The size text echoes only
# the first 200 characters of the command (the command is by definition a large one).
_sg_emit_blocked() {
  local pat="$1" seg="$2" mode="$3" kind="${4:-}"
  if [[ "$kind" == timeout ]]; then
    _sg_time_budget
    cat >&2 <<EOF
[secret-guard] BLOCKED: command too complex to scan within the time budget (${_SG_TIME_BUDGET}s).

Nothing was matched. The secret scan did not finish within the guard's own time
budget, and a command that cannot be checked in time is blocked (fail-closed), not
allowed -- otherwise Claude Code's 5s hook timeout would kill the guard and let the
command through UNSCANNED (fail-open, 10CG/aria-plugin#216).

Split it into smaller commands and run them one at a time:
  - keep every variable value, and every command after expansion, short;
  - do not repeat one long \$VAR many times in a single command;
  - write long files with the Write / Edit tool instead of a heredoc.
命令过于复杂, 无法在时限内扫描其中是否含密钥, 请拆成更小的命令

Command was (first 200 characters): $(_sg_redact_echo "${command:0:200}")
EOF
    return 0
  fi
  if [[ "$kind" == oversize ]]; then
    cat >&2 <<EOF
[secret-guard] BLOCKED: command too large to scan for secrets. Limit hit: $pat

Nothing was matched. After variable expansion the command is bigger than the guard
can check reliably, and a command that cannot be checked is blocked (fail-closed),
not allowed.

Split it into smaller commands and run them one at a time:
  - keep every variable value, and every command after expansion, short;
  - do not repeat one long \$VAR many times in a single command;
  - write long files with the Write / Edit tool instead of a heredoc.
命令过大, 无法扫描其中是否含密钥, 请拆成更小的命令

Command was (first 200 characters): $(_sg_redact_echo "${command:0:200}")
EOF
    return 0
  fi
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

Command was: $(_sg_redact_echo "$command")
EOF
  if [[ "$mode" == "segment" ]]; then
    echo "Triggering segment: $(_sg_redact_echo "$seg")" >&2
  fi
}

# _sg_core_eval CMD : THE built-in judgement -- the baseline body of _sg_per_segment_eval, unchanged (safe-to-split check, top-level split, one _sg_judge_one per segment);
# it only records how it judged (_SG_MODE) so that the W10 pass knows whether _SG_SEGS holds segments.  The W9 extension calls this same function.
_SG_MODE=segment
_sg_core_eval() {
  local cmd="$1" seg rc
  if ! _sg_safe_to_split "$cmd"; then
    _SG_MODE=whole
    _sg_judge_one "$cmd" whole
    return $?
  fi
  _SG_MODE=segment
  _sg_split_top "$cmd"
  if [[ ${#_SG_SEGS[@]} -eq 0 ]]; then _SG_MODE=none; return 0; fi
  for seg in "${_SG_SEGS[@]}"; do
    _sg_judge_one "$seg" segment
    rc=$?
    [[ $rc -ne 0 ]] && return "$rc"
  done
  return 0
}

# Unit-test sourcing gate (#128): when sourced (not executed), stop here —
# functions above are defined, no stdin is consumed, no verdict is emitted.
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  return 0
fi

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
#
# v1.26.0 O3 perf: single jq call extracting all 4 fields at entry, one per
# line. Replaces 3 prior jq invocations (type check + tool_name + per-branch
# command/file_path extract). Saves ~2 × jq startup overhead. Case branches
# below no longer re-invoke jq for their fields.
#
# Field extraction: NUL-delimited (#154/#156/#157 fix). The prior `readarray -t`
# per-line form (e9dc0f7, v1.26.0) had two defects sharing this one line:
#   #154/#156: `readarray` is a bash-4.0+ builtin — macOS system /bin/bash (3.2)
#     and zsh lack it → hook crashes → _sg_fields empty → tool_type empty →
#     fail-closed below blocks ALL tools (session deadlock).
#   #157: per-line read truncates any field VALUE containing a newline (a
#     multiline tool_input.command: heredoc / multi-line script) at its first
#     newline. Line 2+ then never reaches ANY pattern below (silent Rule #7
#     failure — only the command's first line is scanned), and line 2 is
#     misparsed as file_path.
# Fix: `jq -j` joins the 4 fields with a NUL byte and `read -r -d ''` splits on
# NUL. Newline-safe (field values keep embedded newlines) AND portable to bash
# 3.2 / zsh (no readarray/mapfile). `while ... < <(...)` (process substitution,
# not a pipe) keeps the array in the current shell.
# CAVEAT: a *literal* NUL byte cannot appear in a JSON string, but a `\u0000`
# ESCAPE can, and jq decodes it to a real NUL that collides with the separator.
# So NUL is not a fully unambiguous separator on adversarial input — the
# field-count guard below (== 4) is what makes it safe (fail-closed on collision).
#
# `tr -d '\r'` strips carriage returns from jq output (#132): Windows native jq
# builds emit CRLF; without stripping, tool_type becomes "string\r" and fails
# the `!= "string"` check below, fail-closing ALL tools on Windows. Embedded CR
# is meaningless for secret-pattern matching, so stripping the whole stream is
# safe (orthogonal to NUL split: jq -j adds no newline, tr removes any CR;
# multiline command newline bytes are preserved).
_sg_fields=()
while IFS= read -r -d '' _sg_f; do
  _sg_fields+=("$_sg_f")
done < <(jq -j '(.tool_name | type) + "\u0000" + (.tool_name // "") + "\u0000" + (.tool_input.command // "") + "\u0000" + (.tool_input.file_path // "") + "\u0000"' 2>/dev/null <<<"$input" | tr -d '\r')
# NUL-in-field guard (v1.55.3, #154 follow-up — dev-claude spec Critical-2).
# A JSON u0000 escape inside a field value is decoded by jq into a real NUL byte
# that COLLIDES with the field separator, splitting that value into extra
# segments. Attack: a command value carrying an escaped NUL splits so that
# command="ls" (benign, allowed) while the real dumper (printenv/env) overflows
# into file_path, which the Bash branch never scans -> secret-dump bypass.
# jq output for a well-formed input is ALWAYS exactly 4 NUL-terminated segments;
# any other count means an embedded NUL (tampering) or malformed JSON (jq
# errored -> empty -> 0 fields). Fail-closed on anything but 4.
if [[ ${#_sg_fields[@]} -ne 4 ]]; then
  echo "[secret-guard] FATAL: malformed field count (${#_sg_fields[@]} != 4 — embedded NUL or bad input). Blocking." >&2
  exit 2
fi
tool_type="${_sg_fields[0]:-}"
tool="${_sg_fields[1]:-}"
command="${_sg_fields[2]:-}"
file_path="${_sg_fields[3]:-}"
unset _sg_fields _sg_f

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
  # #157 follow-up (dev-claude spec qa M-3): after the multiline fix, `command`
  # (passed as payload) can contain newlines/tabs. This log is TSV, one line per
  # entry — a raw newline would split one bypass event across several log lines
  # and an embedded tab would shift field columns. Collapse CR/LF/TAB to spaces
  # so the "one TSV row per event" invariant holds. (bash 2+; re-exec guard
  # guarantees bash.)
  kind="${kind//[$'\t\r\n']/ }"
  payload="${payload//[$'\t\r\n']/ }"
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
    # v1.26.0 O3 perf: file_path already extracted by entry jq call (line ~107).
    # If file_path absent (e.g. tool_input shape variation), entry call set it to "".
    [[ -z "$file_path" ]] && exit 0

    # R2-C-6 fix: case-insensitive + expanded path list. Common high-value
    # secret file paths a future-Claude might Read without realizing.
    # Note: lowercased file_path for the match.
    lower_path="$(printf '%s' "$file_path" | tr '[:upper:]' '[:lower:]')"
    _sg_hit=0
    if echo "$lower_path" | grep -qE '\.env(\.[a-z0-9_.-]+)?$|\.envrc$|/secrets?/|/credentials?/|id_rsa$|id_ed25519$|id_ecdsa$|\.ssh/id_[a-z0-9_]+$|\.pem$|\.key$|\.gpg$|\.age$|\.p12$|\.pfx$|\.jks$|\.tfstate$|\.tfstate\.backup$|/\.aws/credentials$|/\.aws/config$|/\.kube/config$|kubeconfig$|/\.docker/config\.json$|service[_-]account.*\.json$|gcp[_-]key.*\.json$|firebase.*\.json$|\.ssh/known_hosts$|/secret[_-]token|/master[_-]key|/encryption[_-]key|/\.claude/+(\./+)*settings\.json$|/\.claude/+(\./+)*settings\.local\.json$|/\.claude\.json$|[a-z0-9._-]*(forgejo|gitea)[^ ]*app\.ini([^a-z0-9_]|$)|custom/conf/app\.ini([^a-z0-9_]|$)'; then
      # (last three branches: Aria #179 — Claude Code config files, env node
      #  holds API tokens; mirrors the Bash-face claude-config row)
      # (last two branches: W8 secret-net-l3-and-bypass-paths — Forgejo / Gitea app.ini, the lower-cased spelling of $_SG_SRVCFG with the same right
      #  boundary; a Read / Edit of it is blocked, the ack nonce path below stays the escape hatch)
      _sg_hit=1
    fi
    # W9: the project-level extension adds literal-substring blocks on this face too (one grep pass over the path; ASCII case folding). Called ONLY through $( ): this
    # dispatch runs in the main shell, outside the fail-closed subshell, so a bare call that dies would end the hook with exit 1 = allow, built-in blocks included.
    if [[ $_sg_hit -eq 0 ]]; then
      _sgx="$( _sg_ext_path_pass "$file_path" 2>/dev/null )"
      [[ "$_sgx" == BLOCK ]] && _sg_hit=1
    fi
    if [[ $_sg_hit -eq 1 ]]; then
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
# v1.26.0 O3 perf: command already extracted by entry jq call (line ~107).
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

# ── Risky read patterns ────────────────────────────────────────────────────
declare -a risky_patterns=(
  # Nomad Variables (HTTP API + CLI + alloc fs)
  'curl[^|]*/v1/var/'
  '/v1/var/'                                # any HTTP client to Nomad var path
  'nomad[[:space:]]+var[[:space:]]+(get|list)'
  # Aria #170: `var put` renders the FULL variable (decrypted Items) as JSON
  # whenever stdout is not a TTY — which is always the case under the Bash
  # tool. `-out` help: "Defaults to none when stdout is a terminal and json
  # when the output is redirected." Existing has_filter credits (>/dev/null,
  # &>/dev/null) still allow the safe forms; `-out=none` alone is NOT exempted
  # (spec secret-guard-nomad-var-put-echo deliberately adds no new exemption).
  # Trailing boundary is load-bearing: without it `nomad var putty` misfires.
  # Widening that char class would also catch quoted textual mentions, at the
  # cost of a larger FP surface — deliberately not done, see spec 转出 4.
  'nomad[[:space:]]+var[[:space:]]+put([[:space:]]|$)'
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
  "cat[[:space:]]+([^|]*${_SG_PP_SUFFIX})?\.env(\b|/|$|[[:space:]])"
  "cat[[:space:]]+([^|]*${_SG_PP_SUFFIX})?\.envrc"
  "(head|tail|less|more)[[:space:]]+([^|]*${_SG_PP_SUFFIX})?\.env"

  # v1.25.0 O4 (closes v1.24.0 known-limit (c) F2): Local key-file reads via
  # plain Bash readers — mirrors Read|Edit branch file_path regex at line 153
  # to cover the gap where `cat ~/.ssh/id_rsa` (no SSH wrapper) wasn't blocked.
  # SSH-wrapped variant remains at line ~398. Pattern list intentionally
  # parallels the file_path regex (id_rsa / id_ed25519 / id_ecdsa / .pem /
  # .key / .p12 / .pfx / .jks / .gpg / .age / .tfstate / .aws/credentials /
  # .aws/config / .kube/config / kubeconfig) to maintain Bash↔Read parity.
  # #69: + base64 reader; non-standard ssh key names under .ssh/ (id_[A-Za-z0-9_]+);
  #      .docker/config.json (base64 registry auth). Standard id_rsa/ed25519/ecdsa
  #      still match anywhere (backward-compat); non-standard names anchored to .ssh/
  #      to keep FP low (`cat id_number.txt` must not block).
  "(cat|head|tail|less|more|strings|hexdump|od|xxd|base64)[[:space:]]+(([^|]*${_SG_PP_SUFFIX})?(id_rsa|id_ed25519|id_ecdsa|\.ssh/id_[A-Za-z0-9_]+|\.pem|\.key|\.p12|\.pfx|\.jks|\.gpg|\.age|\.tfstate)|[^|]*(/\.aws/(credentials|config)|/\.kube/config|/kubeconfig|/\.docker/config\.json))(\b|/|$|[[:space:]])"

  # 2026-07-01 incident: shell rc / login-env files commonly hold
  # `export SECRET=...` lines (e.g. FORGEJO_TOKEN in ~/.bashrc). A plain
  # `grep FORGEJO_TOKEN ~/.bashrc` (or cat/head) leaked the value straight to
  # tool output — double gap: `grep` was absent from every reader alternation
  # above, AND .bashrc/.profile/etc were not in the file list. Mirror the .env
  # treatment: block reads of these files by any common reader (ack-overridable
  # for legit non-secret reads via SECRET_GUARD_ACK_PATH). `grep` added here.
  "(cat|grep|egrep|fgrep|rg|head|tail|less|more|strings|awk|sed)[[:space:]]+(([^|]*${_SG_PP_NAME})?(\.bashrc|\.bash_profile|\.bash_login|\.zshrc|\.zprofile|\.profile|\.bash_aliases)|[^|]*(/etc/environment|/etc/profile))(\b|/|$|[[:space:]])"
  "ssh[^|]*(cat|grep|head|tail|less|more|strings|awk)(([^|]*${_SG_PP_NAME})?(\.bashrc|\.bash_profile|\.zshrc|\.profile)|[^|]*(/etc/environment|/etc/profile))"

  # Aria #179 (2026-08-09 incident): Claude Code's own config files hold API
  # tokens in their `env` node and were in NO manifest (Bash or Read/Edit).
  # `jq` added to the reader group — it is the natural JSON reader and the real
  # leak command was `jq -c '{model, env: (.env // {})}' ~/.claude/settings.json`.
  # python3/node readers are covered by extending the :785/:786 source groups.
  # Source-name group lives in $_SG_CLAUDE_CFG (shared with credit tightening).
  "(cat|grep|egrep|fgrep|rg|head|tail|less|more|strings|awk|sed|jq)[[:space:]]+([^|]*${_SG_PP_NAME})?(${_SG_CLAUDE_CFG})(\b|/|$|[[:space:]])"

  # W8 (secret-net-l3-and-bypass-paths): Forgejo / Gitea app.ini. The 29 printing readers (one by one in SC-16 16q) with their OWN left boundary -- the baseline reader
  # groups have none (`chmod` holds `od`) -- and the NAME front whitelist of Aria #179 before the path; right boundary: no letter / digit / `_` after app.ini.
  # Tight credit (_sg_compute_credit). python3 -c / node -e: see the two source groups below.
  "(^|[^[:alnum:]_.-])(${_SG_READERS_PRINT})[[:space:]]+(([^|]*${_SG_PP_NAME})?(${_SG_SRVCFG}))([^[:alnum:]_]|$)"

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
  "strings[[:space:]]+([^|]*${_SG_PP_SUFFIX})?\.env"
  "hexdump[[:space:]]+([^|]*${_SG_PP_SUFFIX})?\.env"
  "(\bod\b)[[:space:]]+([^|]*${_SG_PP_SUFFIX})?\.env"
  "awk[[:space:]]+[^|]*[[:space:]]+([^|]*${_SG_PP_SUFFIX})?\.env"
  "perl[[:space:]]+-[a-zA-Z]*[ne]([^|]*${_SG_PP_SUFFIX})?\.env"

  # R2-C-7 fix: bash file-readers that don't shell out to cat
  'tee[[:space:]]+[^|]*<[[:space:]]*[^|]*\.env'
  'mapfile[[:space:]]+[^<]*<[[:space:]]*[^|]*\.env'
  'readarray[[:space:]]+[^<]*<[[:space:]]*[^|]*\.env'
  'while[[:space:]]+(IFS=|read)[^|]*<[[:space:]]*[^|]*\.env'
  '<[[:space:]]*[^|]*\.env[[:space:]]*(\$\(|`)[^)]*cat'
  '\bcp[[:space:]]+[^|]*\.env[[:space:]]+/dev/(stdout|tty)'
  '(^|[;&|(){]|`|[[:cntrl:]])[[:blank:]]*\.[[:space:]]+[^|]*\.env'                 # `. .env` source
  '(^|[;&|(){]|`|[[:cntrl:]])[[:blank:]]*source[[:space:]]+[^|]*\.env'             # `source .env`

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
  'docker[[:space:]]+(compose[[:space:]]+)?exec[^|]*[[:space:]](printenv|env)([[:blank:]]*($|[;&|)}<>]|`|[[:cntrl:]]))'
  'docker[[:space:]]+inspect[^|]*--format[^|]*\.Config\.Env'

  # R2-C-5 fix: kubectl exec env|cat|printenv (the K8s secret leak path)
  'kubectl[[:space:]]+exec[^|]*[[:space:]]--[[:space:]]+(env|printenv|cat)\b'
  'kubectl[[:space:]]+exec[^|]*[[:space:]](env|printenv)([[:space:]]*$|[[:space:]]+\|)'
  'kubectl[[:space:]]+exec[^|]*--[^|]*(cat|head|tail)[^|]*(/run/secrets|\.env|/etc/[^|]*passwd)'

  # Bare printenv / bare env (no args = dump everything)
  '(^|[;&|(){]|`|[[:cntrl:]])[[:blank:]]*printenv([[:space:]]|[;&|)}<>]|`|$)'
  '(^|[;&|(){]|`|[[:cntrl:]])[[:blank:]]*env([[:blank:]]*($|[;&|)}<>]|`|[[:cntrl:]]))'
  '(^|[;&|(){]|`|[[:cntrl:]])[[:blank:]]*/bin/printenv'                              # absolute path
  '(^|[;&|(){]|`|[[:cntrl:]])[[:blank:]]*/usr/bin/printenv'
  # single-layer wrapper launching a dumper (sudo/nice/timeout/... env|printenv)
  # single-layer launcher wrapper: dumper must be the first non-flag token
  '(^|[;&|(){]|`|[[:cntrl:]])[[:blank:]]*(sudo|doas|nice|timeout|xargs|nohup|stdbuf|env|time|eval|setsid|ionice|unbuffer)\b([[:space:]]+-[^[:space:]]*|[[:space:]]+[0-9]+)*[[:space:]]+(env|printenv)([[:blank:]]*($|[;&|)}<>]|`|[[:cntrl:]]))'
  # `command env`/`command printenv` direct form only (not `command -v env`)
  '(^|[;&|(){]|`|[[:cntrl:]])[[:blank:]]*command[[:blank:]]+(env|printenv)([[:blank:]]*($|[;&|)}<>]|`|[[:cntrl:]]))'
  # shell keyword command positions (then/do/else/elif) before a dumper
  '(^|[;&|(){]|`|[[:cntrl:]])[[:blank:]]*(then|do|else|elif)[[:space:]]+(env|printenv)([[:blank:]]*($|[;&|)}<>]|`|[[:cntrl:]]))'

  # psql sensitive-column reads
  'psql[^|]*(key_encrypted|encrypted_data|encrypted_blob|ciphertext|key_material)'
  'psql[^|]*(SELECT|select)[^|]*(secret|password|passwd|token|api_key|private_key|webhook_secret|signing_key|hash|refresh_token|oauth_access_token|client_secret)'

  # K8s secret dumps
  'kubectl[[:space:]]+get[[:space:]]+secret[^|]+-o[[:space:]]+(yaml|json)'
  'kubectl[[:space:]]+describe[[:space:]]+(secret|configmap)'

  # Indirection bypasses
  'base64[[:space:]]+(-d|--decode)[^|]*\|[[:space:]]*(bash|sh|zsh|dash)'
  '\|[[:space:]]*base64[[:space:]]+(-d|--decode)[[:space:]]*\|[[:space:]]*(bash|sh|zsh|dash)'
  # Aria #179: + claude-config source group (python3 -c / node -e inline scripts
  # reading ~/.claude/settings.json etc.). Kept on the narrow `-c`/`-e` rows —
  # NOT merged into the generic reader alternation (prose-FP surface).
  # W8 / W11 (secret-net-l3-and-bypass-paths): + the Forgejo / Gitea app.ini name group and the /proc/<pid>/environ|cmdline names (same pid position as the /proc rows).
  "python3?[[:space:]]+-c([^|]*${_SG_PP_SUFFIX})?(/v1/var/|secretsmanager|/secrets/|\.env|provider_key|${_SG_CLAUDE_CFG}|${_SG_SRVCFG}|/proc/${_SG_PIDTOK}/(task/[^/[:space:]]+/)?(environ|cmdline))"
  "node[[:space:]]+-e([^|]*${_SG_PP_SUFFIX})?(/v1/var/|secretsmanager|/secrets/|\.env|provider_key|${_SG_CLAUDE_CFG}|${_SG_SRVCFG}|/proc/${_SG_PIDTOK}/(task/[^/[:space:]]+/)?(environ|cmdline))"

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
  # W11 (secret-net-l3-and-bypass-paths): the two rows above are rewritten IN PLACE. Baseline part unchanged (13 readers; (self|digits); environ|status|cmdline). Added: for
  # environ|cmdline ONLY, 11 more readers (xargs sed grep rg cut paste nl sort base64 cp dd) and the wider pid position _SG_PIDTOK (glob tokens, $$, $name, ${...}, $(...)),
  # plus the task/<tid>/ sub-path. `status` stays on the narrow baseline part (a metadata read such as grep VmRSS /proc/N/status stays allowed). Not a tight family.
  "((cat|head|tail|less|more|strings|hexdump|od|xxd|tr|awk|perl|rev)[[:space:]]+[^|]*/proc/(self|[0-9]+)/(environ|status|cmdline)|(cat|head|tail|less|more|strings|hexdump|od|xxd|tr|awk|perl|rev|xargs|sed|grep|rg|cut|paste|nl|sort|base64|cp|dd)[[:space:]]+[^|]*/proc/${_SG_PIDTOK}/(task/[^/[:space:]]+/)?(environ|cmdline))"
  "(<[[:space:]]*/proc/(self|[0-9]+)/(environ|status|cmdline)|<[[:space:]]*/proc/${_SG_PIDTOK}/(task/[^/[:space:]]+/)?(environ|cmdline))"
  # W11 (secret-net-l3-and-bypass-paths): process-table enumeration, three rows spelled as literals (see _SG_PROCTAB for the text and the credit copy).
  # 1. ps / pgrep / pstree / top in an argv-exposing form at a command position, optionally behind one launcher (15 words) and an absolute directory prefix;
  # 2. the same, and whole-environment dumps (env / printenv), behind remote / shell wrappers (ssh, docker|podman|kubectl|lxc exec, nomad alloc exec, pct exec,
  #    sh|bash -c, watch); 3. docker top and docker ps --no-trunc (podman alike). Reject (exit 2) with the shared BLOCKED text.
  '(^|[;&|(){]|`|[[:cntrl:]])[[:blank:]]*((then|do|else|elif)[[:space:]]+)?((/[^[:space:]|;&"'"'"'`$()<>]*/)?(sudo|doas|nice|timeout|xargs|nohup|stdbuf|env|time|eval|setsid|ionice|unbuffer|command|exec)([[:space:]]+(-[^[:space:]]+([[:space:]]+[^-[:space:]|;&()<>`"'"'"'][^[:space:]|;&()<>`"'"'"']*)?|[0-9][0-9.]*[smhd]?|[A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*))*[[:space:]]+)?((/[^[:space:]|;&"'"'"'`$()<>]*/)?(ps[[:blank:]]+([a-zA-Z]+([^[:alnum:]_-]|$)|[0-9]+([^[:alnum:]_.-]|$)|([^|;&]*[[:blank:]])?-[a-zA-Z]*[fF]|([^|;&]*[[:blank:]])?(-[a-zA-Z]*[oO]|--format)[[:blank:]=]*[^[:blank:]|;&]*(args|cmd|command)|([^|;&]*[[:blank:]])?-[a-zA-Z]*O|([^|;&]*[[:blank:]])?-[a-zA-Z]*x[a-zA-Z]*([^[:alnum:]_-]|$)|([^|;&]*[[:blank:]])?-[a-zA-Z]*u[[:blank:]]*($|[|;&)<>]))|pgrep[[:blank:]]+([^|;&]*[[:blank:]])?(-[a-zA-Z]*a|--list-full)|pstree[[:blank:]]+([^|;&]*[[:blank:]])?(-[a-zA-Z]*a|--arguments)|top[[:blank:]]+([^|;&]*[[:blank:]])?-[a-zA-Z]*c))'
  '(ssh|docker[[:space:]]+(compose[[:space:]]+)?exec|kubectl[[:space:]]+exec|nomad[[:space:]]+alloc[[:space:]]+exec|pct[[:space:]]+exec|lxc[[:space:]]+exec|podman[[:space:]]+exec|(sh|bash|zsh|dash)[[:space:]]+-c|watch)[^|]*[[:space:]'"'"'"(`](((/[^[:space:]|;&"'"'"'`$()<>]*/)?(ps[[:blank:]]+([a-zA-Z]+([^[:alnum:]_-]|$)|[0-9]+([^[:alnum:]_.-]|$)|([^|;&]*[[:blank:]])?-[a-zA-Z]*[fF]|([^|;&]*[[:blank:]])?(-[a-zA-Z]*[oO]|--format)[[:blank:]=]*[^[:blank:]|;&]*(args|cmd|command)|([^|;&]*[[:blank:]])?-[a-zA-Z]*O|([^|;&]*[[:blank:]])?-[a-zA-Z]*x[a-zA-Z]*([^[:alnum:]_-]|$)|([^|;&]*[[:blank:]])?-[a-zA-Z]*u[[:blank:]]*($|[|;&)<>]))|pgrep[[:blank:]]+([^|;&]*[[:blank:]])?(-[a-zA-Z]*a|--list-full)|pstree[[:blank:]]+([^|;&]*[[:blank:]])?(-[a-zA-Z]*a|--arguments)|top[[:blank:]]+([^|;&]*[[:blank:]])?-[a-zA-Z]*c))|printenv([[:space:]'"'"'"]|[;&|)}<>`]|$)|env([[:blank:]]*($|[;&|)}<>'"'"'"`])))'
  '(docker|podman)[[:space:]]+((compose|container)[[:space:]]+)?top([^[:alnum:]_-]|$)|(docker|podman)[[:space:]]+(container[[:space:]]+)?(ps|ls)[[:space:]]+([^|;&]*[[:space:]])?--no-trunc'

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
  '(^|[;&|(){]|`|[[:cntrl:]])[[:blank:]]*compgen[[:space:]]+-e([[:blank:]]*($|[;&|)}<>]|`|[[:cntrl:]]))'
  'set[[:space:]]+-o[[:space:]]+posix.*set[[:space:]]*\|[[:space:]]*grep'

  # ── #69 (Aether v1.28.0 14-day dogfood — 5 confirmed FN + corpus) ──────────
  # FN3: HashiCorp Vault HTTP API form (header + token literal). CLI forms
  # (`vault read|kv get|agent`) covered at ~line 359; this adds the curl/HTTP path.
  '(-H|--header)[[:space:]]*["'"'"']?[[:space:]]*X-Vault-Token:'           # vault HTTP auth header (require -H/--header so doc/grep mention of the name doesn't FP)
  'hvs\.[A-Za-z0-9]{24,}'                                                  # vault service token literal (≥24 → skip hvs.<benign-id>; real tokens ~95 chars)
  # FN4: kubectl exec indirect shell wrap — `-- sh -c '...env|cat...'` bypasses
  # the literal-reader-after-`--` patterns at ~line 444.
  'kubectl[[:space:]]+exec[^|]*--[^|]*(sh|bash)[[:space:]]+-c[^|]*(env|printenv|cat)'
  # base64/dd of key files (base64 added to reader set ~line 397; dd mirrors line 410)
  'dd[[:space:]]+[^|]*if=[^|]*(\.ssh/id_[A-Za-z0-9_]+|id_rsa|id_ed25519|id_ecdsa|\.pem|\.key|\.p12|\.pfx)'  # if= any arg position (dd bs=4k if=key)
  # FN5 + exfil-to-destination class (R3-C-8 threat-model extension, see ~line 536):
  # remote-copy (download OR upload) / local-copy / archive-pipe of key files &
  # the .ssh dir to a destination. `\bcp` avoids matching the `cp` inside `scp`.
  'scp[[:space:]]+[^|]*(\.ssh/id_[A-Za-z0-9_]+|id_rsa|id_ed25519|id_ecdsa|\.pem|\.key)'              # scp host:secret . | scp secret host: (/private/ dropped — redundant w/ .pem + macOS FP)
  'rsync[[:space:]]+[^|]*(\.ssh/id_[A-Za-z0-9_]+|id_rsa|id_ed25519|id_ecdsa|\.pem|\.key)'
  '\bcp[[:space:]]+[^|]*(\.ssh/id_[A-Za-z0-9_]+|id_rsa|id_ed25519|id_ecdsa|\.pem|\.key)([[:space:]]|$)'  # cp key dest (also matches key as final EOL arg)
  'tar[[:space:]]+[^|]*\.ssh([^a-zA-Z]|$)[^|]*\|[[:space:]]*(ssh|nc|curl|wget)'                      # tar ~/.ssh | ssh evil (.ssh boundary so .sshconfig doesn't FP)
  'wget[[:space:]]+[^|]*--post-file=[^|]*'                                                           # wget --post-file=.env
  # ── Forgejo credential-RESPONSE endpoints (aria-plugin #153, 2026-08-20 事故) ──
  # 命令形状无害, 凭据在响应里 (registration-token 实泄); PostToolUse 不能 redact
  # (#91), 只能请求侧拦。锚定「命令名 + 端点路径」(Aria#179 问题二: 裸词匹配过火)。
  # 已知残余 FP: 在 bash heredoc/字符串里引用这些端点路径会命中 —— 讨论文本请用
  # Write 工具或运行时拼装 (同 secret-guard-fp 既有口径)。同族 L2/L3 见 Aether#317/#154。
  '\b(forgejo|curl)\b[^|]*runners/registration-token'                                                # runner 注册 token (repo/org/admin 三作用域)
  '\b(forgejo|curl)\b[^|]*/users/[^[:space:]|/]+/tokens([[:space:]?/]|$)'                            # POST 建 PAT 返明文 sha1 (DELETE 同拦, 用 guard:ack 走维护)
  '\b(forgejo|curl)\b[^|]*/user/applications/oauth2'                                                 # oauth2 app 返 client_secret
)

# _sg_redact_echo() — value-shaped token redaction for BLOCKED stderr echoes
# (aria-plugin #145, Rule #7: exit-2 stderr is fed back to the AI = chat-visible;
# an inlined literal value in the blocked command would otherwise be echoed
# verbatim — the guard itself becoming the leak). Structure-preserving:
#   (a) key=value / key="v v" / key='v v'  ->  key=[REDACTED]
#   (b) bare runs of >=20 chars in [A-Za-z0-9+=_-] (base64/hex/token shapes)
#       -> [REDACTED]; `/` deliberately NOT in the class so filesystem paths
#       keep their diagnostic value.
# Over-redaction is acceptable (fail toward redaction); short positional
# secrets without `=` are a known residual — full-parse precision is #138's
# domain. Runs only on the (rare) block path: one sed fork, outside the
# SC-8-measured judgement hot path.
_sg_redact_echo() {
  printf '%s' "$1" | LC_ALL=C sed -E \
    -e "s/=(\"[^\"]*\"|'[^']*'|[^[:space:]]+)/=[REDACTED]/g" \
    -e "s/[A-Za-z0-9+=_-]{20,}/[REDACTED]/g"
}

# _sg_judge_one() — evaluate one string (whole command in "whole" mode, or one
# top-level segment in "segment" mode) against risky_patterns + credit. $1 =
# string to judge, $2 = mode (whole|segment). Returns 0 = allow, 2 = blocked
# (BLOCKED message already written to stderr; mode=whole reproduces canonical
# stderr byte-for-byte, zero new lines).
_sg_judge_one() {
  local seg="$1" mode="$2" pat
  local credit="" subj="$1" _w
  # W12 (secret-net-l3-and-bypass-paths): an os.environ single-key read (.environ.get( / .environb.get( / .environ[ / .environb[) is the same information as the
  # allowed os.getenv, but its `.env` prefix trips the interpreter rows. Every occurrence of the four literal substrings is cut out of the COPY that is
  # matched ($subj) and replaced by a neutral token without `.env`; the whole-table forms (os.environ, dict(os.environ), .items(), ...) are not in the list
  # and stay blocked. Prefix + length-based remainder concatenation, no ${s//p/r} and no eval: the key texts are never executed. credit and the BLOCKED
  # text keep working on the original $seg / $command.
  if [[ "$subj" == *environ* ]]; then
    while [[ "$subj" == *".environ.get("* ]]; do _w="${subj%%".environ.get("*}"; subj="${_w}.ek_(${subj:$(( ${#_w} + 13 ))}"; done
    while [[ "$subj" == *".environb.get("* ]]; do _w="${subj%%".environb.get("*}"; subj="${_w}.ek_(${subj:$(( ${#_w} + 14 ))}"; done
    while [[ "$subj" == *".environ["* ]]; do _w="${subj%%".environ["*}"; subj="${_w}.ek_[${subj:$(( ${#_w} + 9 ))}"; done
    while [[ "$subj" == *".environb["* ]]; do _w="${subj%%".environb["*}"; subj="${_w}.ek_[${subj:$(( ${#_w} + 10 ))}"; done
  fi
  for pat in "${risky_patterns[@]}"; do
    if [[ "$subj" =~ $pat ]]; then
      if [[ -z "$credit" ]]; then
        if _sg_compute_credit "$seg"; then credit=1; else credit=0; fi
      fi
      if [[ "$credit" == "0" ]]; then
        _sg_emit_blocked "$pat" "$seg" "$mode"
        return 2
      fi
      break
    fi
  done
  return 0
}

# _sg_per_segment_eval() — §What.3 fail-safe entry point: degrade to whole-
# command legacy verdict when $1 doesn't look safe to split, else split on
# top-level ; && || and judge each segment independently (credit computed
# fresh per segment — §What.3 SFH-M2, no sticky global). $1 = whole command.
# Returns 0 = allow, 2 = blocked, propagates _sg_judge_one's return code.
# Order (W9 / W10): 1. the built-in judgement (_sg_core_eval: the baseline body of this function, unchanged); 2. only if it allowed, the W10 variable pass (_sg_vx_pass);
# 3. only if both allowed, the W9 project extension -- on the original command, then on the variable-substituted whole command. A built-in block ends the evaluation
# before either later stage is even called, so nothing the built-ins decide is postponed or reversed. The extension runs ONLY inside command substitutions; its answer
# is the literal sentinel BLOCK, anything else (empty, error, fault) means "no extension block". Its own block prints the shared BLOCKED text (W13). Length budget: an overrun
# inside _sg_vx_pass blocks there; the extension's look at the substituted whole command, when that copy is too large to build, blocks here -- but only when an extension is in
# effect (entries exist: asked inside a command substitution like every other extension call), because without one nothing is left unjudged.
_sg_per_segment_eval() {
  local cmd="$1" rc ar _x
  _sg_core_eval "$cmd"
  rc=$?
  [[ $rc -ne 0 ]] && return "$rc"
  _SG_T0=$SECONDS; _sg_time_budget   # per-command time-budget reset: the _SG_MODE==none path skips _sg_vx_pass/_sg_vx_collect below but still runs the W9 ext checkpoint, so without this it would read a stale _SG_T0 (fresh process: ~process-start, benign; sourced suite: suite-start, spuriously fires)
  if [[ "$_SG_MODE" != none ]]; then
    _sg_vx_pass "$cmd" "$_SG_MODE"
    rc=$?
    [[ $rc -ne 0 ]] && return "$rc"
  fi
  _x="$( _sg_ext_pass "$cmd" 2>/dev/null )"
  if [[ "$_x" == TIME ]]; then   # time-budget fail-closed: the W9 extension look ran out of time
    _sg_emit_blocked "time" "$cmd" segment timeout
    return 2
  fi
  if [[ "$_x" != BLOCK ]] && (( ${#_SGV_N[@]} )); then
    _sg_vx_apply "$cmd"
    ar=$?
    if [[ $ar -eq 0 ]]; then
      _x="$( _sg_ext_pass "$_SG_SUB" 2>/dev/null )"
      if [[ "$_x" == TIME ]]; then   # time-budget fail-closed: the extension's look at the substituted whole command ran out of time
        _sg_emit_blocked "time" "$cmd" segment timeout
        return 2
      fi
    elif [[ $ar -eq 2 && -n "$( _sg_ext_entries 2>/dev/null )" ]]; then
      _sg_emit_blocked "the command is longer than $_SGV_SMAX characters after variable expansion, too large for the project extension (.aria/secret-guard.paths) to check" "$cmd" segment oversize
      return 2
    fi
  fi
  if [[ "$_x" == BLOCK ]]; then
    _sg_emit_blocked "(extension) .aria/secret-guard.paths" "$cmd" segment
    return 2
  fi
  return 0
}

# ── Per-segment verdict (#128) — the ENTIRE new logic runs inside one explicit
# subshell: under `set -u` an unbound-variable death is an unconditional shell
# termination that bypasses ERR traps / `||` / `if` guards (all only see
# "command returned non-zero"); the subshell boundary is the only mechanism
# that converts it into a plain non-zero status the parent can map to exit 2
# (fail-closed). Verdict crosses the boundary via exit code only: 0=allow,
# 2=block (message already on stderr), anything else=internal error.
( _sg_per_segment_eval "$command" )
_sg_rc=$?
if [[ $_sg_rc -eq 0 ]]; then
  exit 0
fi
if [[ $_sg_rc -eq 2 ]]; then
  exit 2
fi
echo "[secret-guard] BLOCKED: internal error in per-segment evaluation (rc=$_sg_rc). Failing closed." >&2
exit 2

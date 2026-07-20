#!/usr/bin/env bash
# PreToolUse hook — block `docker logout` aimed at a heavy host's shared
# docker credential store.
#
# === WHY (Aether #234) ===
#
# Two credential-wipe incidents, eight days apart, same root cause:
#   heavy-3, 2026-07-08 13:46:04Z — truffle-hound-v2 session, build cleanup
#   heavy-1, 2026-07-16 19:20:38Z — nexus v4.2.0 release retag
# Both were AI sessions that SSH'd into a heavy host as root, did legitimate
# docker work, then "politely" ran `docker logout forgejo.10cg.pub` on the way
# out. That host login state is NOT session-owned: it is the node's resident
# T2 registry credential (act_runner pulls runner-images through it; aether-build
# pulls base images through it). Logging out leaves a 16-byte `{"auths":{}}`
# file, and the next cold-cache CI build dies with `unauthorized`.
#
# Neither incident was malicious, and neither was caught for days — the second
# surfaced only when a release build failed in 1 second. Forensics needed two
# rounds because auditd is absent and journald had already rotated past the
# window. This hook exists so the third one never happens.
#
# === WHAT IT DOES ===
#
# Blocks a Bash command when ALL of:
#   1. it contains `docker logout`, AND
#   2. it contains an ssh/scp invocation targeting a heavy host
#      (heavy-1..5 by name, or 192.168.69.80-84 by address), AND
#   3. it does NOT set DOCKER_CONFIG (the prescribed isolation escape), AND
#   4. it carries no `# guard:ack: <reason>` operator override.
#
# The safe pattern it steers you to — never touch the host's default config:
#   ssh root@heavy-1 'DOCKER_CONFIG=/tmp/iso docker login ... && \
#                     DOCKER_CONFIG=/tmp/iso docker push ... ; rm -rf /tmp/iso'
# And most of the time you need nothing at all: the host is ALREADY logged in
# with the credential you want. Just pull/push.
#
# === WHAT IT IS NOT (honest limits) ===
#
#   - Not a sandbox. It reads one tool call's command string. If the logout and
#     the ssh land in SEPARATE tool calls (write script now, scp later, run it
#     in a third call), each call looks innocent and nothing is blocked. Both
#     known incidents happened to be single calls, so this catches the observed
#     shape — not the general case.
#   - Not a host-side control. `nomad alloc exec`, a runner job that gains a
#     writable mount, or anyone with a shell can still wipe the file. The
#     durable defenses are auditd watch (10cg.local#19, detective) and keeping
#     act_runner's valid_volumes off `**` (preventive, Aether #234).
#   - Not a scanner of what the command DOES. Pattern-based, pre-execution.
#   - DOCKER_CONFIG anywhere in the command is treated as isolation intent.
#     A command that isolates one docker call and then logs out the host config
#     in another would pass. Accepted: this is a speed-bump for an accident,
#     not a barrier against someone trying.
#
# Deliberately NOT blocked: `docker login` on a host (that is how a wiped node
# gets repaired) and logout on any non-heavy host (e.g. a dev box, whose docker
# login state IS session-owned).
#
# jq policy: if jq is missing this hook allows and warns, rather than adding a
# second way to deadlock a session (the #154 lesson). secret-guard.sh is the
# hook that hard-requires jq; this narrow guard does not re-litigate it.
#
# Operator bypass (logged to ~/.claude/logs/guard-bypass.log):
#   ... # guard:ack: <reason ≥ 8 non-whitespace chars>

set -u

# ── jq presence: warn-and-allow (see jq policy above) ─────────────────────
if ! command -v jq >/dev/null 2>&1; then
  echo "[host-docker-logout-guard] WARN: jq not found — guard inactive this call." >&2
  exit 0
fi

input="$(cat 2>/dev/null || true)"
[[ -z "$input" ]] && exit 0   # empty stdin — test invocation or harness quirk

# ── Parse — NUL-delimited so multi-line commands survive intact (#157) ────
# A heredoc-authored script is exactly the shape of incident 2; per-line reads
# would truncate it at the first newline and miss the logout entirely.
_fields=()
while IFS= read -r -d '' _f; do
  _fields+=("$_f")
done < <(jq -j '(.tool_name | type) + "\u0000" + (.tool_name // "") + "\u0000" + (.tool_input.command // "") + "\u0000"' 2>/dev/null <<<"$input" | tr -d '\r')

if [[ ${#_fields[@]} -ne 3 ]]; then
  echo "[host-docker-logout-guard] FATAL: malformed PreToolUse input. Blocking." >&2
  exit 2
fi

tool_type="${_fields[0]}"
tool_name="${_fields[1]}"
command_str="${_fields[2]}"

if [[ "$tool_type" != "string" ]]; then
  echo "[host-docker-logout-guard] FATAL: tool_name type=$tool_type (expected string). Blocking." >&2
  exit 2
fi

[[ "$tool_name" != "Bash" ]] && exit 0

# ── Detection ─────────────────────────────────────────────────────────────
# grep is line-oriented, so the ssh-target match cannot span lines (an `ssh`
# on one line and an unrelated `heavy-2` on another must not combine). The
# logout match is intentionally whole-command: in incident 2 it sat inside a
# heredoc several lines above the ssh that ran it.

printf '%s' "$command_str" | grep -Eq 'docker[[:space:]]+logout' || exit 0

_vector_re='(^|[^-[:alnum:]_])(ssh|scp)[[:space:]][^|;&]*(heavy-[1-5]|192\.168\.69\.8[0-4])'
printf '%s' "$command_str" | grep -Eq "$_vector_re" || exit 0

# Prescribed isolation → allow.
printf '%s' "$command_str" | grep -q 'DOCKER_CONFIG=' && exit 0

# ── guard:ack escape (mirrors secret-guard.sh) ────────────────────────────
log_ack() {
  local kind="$1" payload="$2"
  kind="${kind//[$'\t\r\n']/ }"
  payload="${payload//[$'\t\r\n']/ }"
  local entry
  entry="$(printf '%s\t%s\t%s\t%s\t%s\n' \
    "$(date -u +%FT%TZ)" "${USER:-unknown}" "${PWD:-unknown}" "$kind" "$payload")"
  mkdir -p "${HOME}/.claude/logs" 2>/dev/null \
    && printf '%s' "$entry" >> "${HOME}/.claude/logs/guard-bypass.log" 2>/dev/null \
    || true
}

if printf '%s' "$command_str" | grep -qE '#[[:space:]]*guard:ack[[:space:]]*[:=][[:space:]]*[^[:space:]][^[:space:]]{7,}'; then
  log_ack "HOST-LOGOUT-ACK" "$command_str"
  exit 0
fi

# ── Block ─────────────────────────────────────────────────────────────────
cat >&2 <<'EOF'
[host-docker-logout-guard] BLOCKED: `docker logout` targeting a heavy host.

That host's docker login state is the node's RESIDENT registry credential
(T2) — act_runner pulls runner-images through it and aether-build pulls base
images through it. It is not owned by this session, and logging out leaves the
node unable to pull private images until someone notices a failing CI build.
This exact "polite cleanup" wiped heavy-3 (2026-07-08) and heavy-1
(2026-07-16). See Aether #234.

What to do instead:

  * Nothing, usually — the host is already logged in with that credential.
    Just run your pull/push; no login, no logout.

  * If you need different credentials, isolate and never touch the default:
      ssh root@heavy-N 'DOCKER_CONFIG=/tmp/iso docker login ... ; \
                        DOCKER_CONFIG=/tmp/iso docker push ... ; rm -rf /tmp/iso'

  * If a node's credential is genuinely gone, repair it (do not log out):
      copy /root/.docker/config.json from a healthy heavy node, chmod 600,
      then verify with `aether doctor --check node_docker_auth_parity`.

Intentional removal (e.g. decommissioning a node) — append to the command:
  # guard:ack: <reason ≥ 8 non-whitespace chars>

Note: writing prose that merely mentions these words is not blocked; only an
ssh/scp command aimed at a heavy host is. If a doc-writing command trips this,
put the text in a file and pass it with -F/@file.
EOF
exit 2

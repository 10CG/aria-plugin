#!/usr/bin/env bash
# Regression test suite for host-docker-logout-guard.sh PreToolUse hook.
#
# Run: bash aria/hooks/tests/host-docker-logout-guard.test.sh  (from repo root)
# Expects: jq installed. Exit 0 if all pass, 1 if any fail.
#
# Guards Aether #234: two credential-wipe incidents (heavy-3 2026-07-08,
# heavy-1 2026-07-16) where an AI session SSH'd into a heavy host as root to
# run a build/release and "politely" ran `docker logout forgejo.10cg.pub` on
# the way out — destroying the node's resident T2 registry credential and
# breaking the next cold-cache CI build.
#
# The two BLOCK cases below are the VERBATIM command shapes of those two
# incidents (recovered from session transcripts). If either stops being
# blocked, the guard has regressed on a proven-real failure.
#
# ALLOW cases encode the two things this guard must NOT do:
#   1. block the prescribed safe pattern (DOCKER_CONFIG isolation), and
#   2. block prose that merely mentions the words — the secret-guard
#      false-positive-on-doc-words trap, hit twice before.

set -u

HOOK="$(dirname "$0")/../host-docker-logout-guard.sh"
pass=0
fail=0
failures=()

run_case() {
  local name="$1" want="$2" input="$3"
  local got exit_code
  got="$(echo "$input" | bash "$HOOK" 2>/dev/null; echo "exit=$?")"
  exit_code="${got##*exit=}"
  if [[ "$exit_code" == "$want" ]]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    failures+=("FAIL [$name]: want exit=$want, got exit=$exit_code")
  fi
}

bash_case() {
  local name="$1" want="$2" cmd="$3"
  run_case "$name" "$want" \
    "$(jq -n --arg c "$cmd" '{tool_name: "Bash", tool_input: {command: $c}}')"
}

# ── BLOCK (exit 2): real incident shapes ──────────────────────────────────

# Incident 1 — heavy-3, 2026-07-08 13:46:04Z (truffle-hound-v2 session).
# Compound remote command, IP form, logout buried mid-string with redirects.
bash_case "incident-1 heavy-3 ip-form compound" 2 \
'timeout 20 ssh -o ConnectTimeout=8 root@192.168.69.82 "rm -rf /opt/loopc-build /opt/loopc-ctx.tgz; docker logout forgejo.10cg.pub >/dev/null 2>&1; echo cleaned"'

# Incident 2 — heavy-1, 2026-07-16 19:20:36Z (nexus v4.2.0 release session).
# The logout lives inside a heredoc-authored script that is scp'd and then run
# remotely. Single tool call, so both the logout and the heavy target are in
# the command string.
bash_case "incident-2 heavy-1 heredoc-scp-run" 2 \
'cat > "$SP/retag.sh" <<'"'"'EOF'"'"'
#!/bin/sh
set -e
echo "$DP" | docker login forgejo.10cg.pub -u "$DU" --password-stdin >/dev/null 2>&1
docker tag forgejo.10cg.pub/10cg/nexus:54201d0 forgejo.10cg.pub/10cg/nexus:v4.2.0
docker push -q forgejo.10cg.pub/10cg/nexus:v4.2.0 >/dev/null
docker logout forgejo.10cg.pub >/dev/null 2>&1
EOF
scp -q "$SP/retag.sh" root@heavy-1:/tmp/.retag.sh
ssh root@heavy-1 '"'"'sh /tmp/.retag.sh; rm -f /tmp/.retag.sh'"'"''

# Minimal / cousin shapes
bash_case "plain hostname form"            2 "ssh root@heavy-1 'docker logout forgejo.10cg.pub'"
bash_case "hosts-alias form"               2 'ssh heavy-4 "docker logout forgejo.10cg.pub"'
bash_case "ip form bare"                   2 'ssh root@192.168.69.80 "docker logout"'
bash_case "logout before ssh in string"    2 'echo start; ssh root@heavy-2 "docker logout forgejo.10cg.pub"'

# ── ALLOW (exit 0): the prescribed safe pattern ───────────────────────────

bash_case "isolated DOCKER_CONFIG on heavy" 0 \
'ssh root@heavy-1 "DOCKER_CONFIG=/tmp/iso docker login forgejo.10cg.pub -u bot --password-stdin < /dev/null; DOCKER_CONFIG=/tmp/iso docker logout forgejo.10cg.pub; rm -rf /tmp/iso"'

# ── ALLOW (exit 0): negative controls — no remote-exec vector ─────────────
# These are the doc-words false positives that bit secret-guard twice.

bash_case "prose mentioning both terms"     0 \
'echo "heavy-1 上的 docker logout 是 #234 两起 wipe 的根因" >> /tmp/notes.md'
bash_case "commit msg via -F file"          0 'git commit -F /tmp/msg.txt'
bash_case "grep for the pattern in repo"    0 'grep -rn "docker logout" scripts/ | head'
bash_case "local logout, no heavy target"   0 'docker logout forgejo.10cg.pub'
bash_case "ssh to heavy, no logout"         0 'ssh root@heavy-1 "docker pull forgejo.10cg.pub/10cg/nexus:v4.2.0"'
bash_case "ssh elsewhere with logout"       0 'ssh dev@192.168.69.209 "docker logout forgejo.10cg.pub"'

# ── Harness contract ──────────────────────────────────────────────────────

run_case "non-Bash tool passes through"     0 \
  "$(jq -n '{tool_name: "Read", tool_input: {file_path: "/etc/hosts"}}')"
run_case "empty stdin allowed"              0 ""
run_case "malformed json fails closed"      2 "not-json-at-all"

# Operator escape hatch, mirroring secret-guard's guard:ack convention.
bash_case "guard:ack bypass"                0 \
'ssh root@heavy-1 "docker logout forgejo.10cg.pub"  # guard:ack: decommissioning heavy-1, credential intentionally removed'
bash_case "guard:ack too short rejected"    2 \
'ssh root@heavy-1 "docker logout forgejo.10cg.pub"  # guard:ack: x'

# ── Summary ───────────────────────────────────────────────────────────────

echo "host-docker-logout-guard: $pass passed, $fail failed"
if ((fail > 0)); then
  printf '%s\n' "${failures[@]}"
  exit 1
fi
exit 0

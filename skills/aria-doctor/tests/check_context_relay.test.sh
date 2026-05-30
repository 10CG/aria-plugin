#!/bin/bash
# check_context_relay.test.sh — TASK-006 CRLF robustness (shell-jq-crlf-hardening).
# Run: bash aria/skills/aria-doctor/tests/check_context_relay.test.sh
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
CHK="$HERE/../scripts/check_context_relay.sh"
MARKER="# >>> aria-context-monitor relay >>>"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ok   - $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL - $1"; }

command -v jq >/dev/null 2>&1 || { echo "SKIP: jq not available"; exit 0; }
source "$HERE/../../../hooks/tests/lib/crlf-shim.sh"

shim="$(crlf_shim_create)"
crlf_selfcheck "$shim" 2>/dev/null && ok "crlf shim selfcheck" || bad "crlf shim selfcheck"

# A statusline script with the relay marker already installed (check reads the
# open marker to report relay-installed).
T=$(mktemp -d)
{
  echo "#!/bin/bash"
  echo 'input=$(cat)'
  echo "$MARKER"
  echo "# <<< aria-context-monitor relay <<<"
  echo "echo hi"
} > "$T/sl.sh"
echo "{\"statusLine\":{\"type\":\"command\",\"command\":\"bash $T/sl.sh\"}}" > "$T/settings.json"

# Forward assertion: under Windows-native-jq CRLF, detection still reports
# relay-installed. NOTE: the `cmd` CR-strip in check_context_relay.sh:53 is
# DEFENSIVE — empirically the downstream `.sh` path extraction (grep -oE) is
# already robust to a trailing CR, so detection does not misfire with or without
# the strip. We assert correct detection under CRLF (not a two-state flip, which
# would be hollow here); the strip keeps the comparison value clean per the
# decision table in case downstream ever compares `cmd` directly.
state="$(crlf_run_with_shim "$shim" bash "$CHK" --settings "$T/settings.json" 2>/dev/null | jq -r '.state' 2>/dev/null)"
[ "$state" = "relay-installed" ] && ok "detects relay-installed under CRLF (state=$state)" || bad "wrong state under CRLF: $state"

# Sanity: same result without the shim (LF baseline).
state_lf="$(bash "$CHK" --settings "$T/settings.json" 2>/dev/null | jq -r '.state' 2>/dev/null)"
[ "$state_lf" = "relay-installed" ] && ok "detects relay-installed under LF (baseline)" || bad "wrong LF state: $state_lf"

crlf_shim_destroy "$shim"
rm -rf "$T"
echo ""
echo "check_context_relay tests: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1

#!/usr/bin/env bash
# check_parity.sh — Git 多远程 parity 检测 (纯读, 无网络写操作)
#
# Usage:
#   bash check_parity.sh --repo=<path> --branch=<name> \
#     [--verify-mode=local_refs|ls_remote] [--timeout=<seconds>]
#
# Output: JSON (canonical schema, see references/schema.md)
#
# Dependencies: jq (required), timeout/gtimeout/python3 (ls_remote mode)

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────────
REPO=""
BRANCH="master"
VERIFY_MODE="local_refs"
# v1.15.1: bumped default from 5s to 15s after dogfood discovery that Forgejo SSH
# over Cloudflare Access requires ~8s for ls-remote. 15s provides 2x headroom.
# For fast networks, override via --timeout=5.
TIMEOUT_SECONDS=15

# ── Argument parsing ──────────────────────────────────────────────────────────
for arg in "$@"; do
  case "$arg" in
    --repo=*)       REPO="${arg#*=}" ;;
    --branch=*)     BRANCH="${arg#*=}" ;;
    --verify-mode=*) VERIFY_MODE="${arg#*=}" ;;
    --timeout=*)    TIMEOUT_SECONDS="${arg#*=}" ;;
    *) echo "Unknown argument: $arg" >&2; exit 1 ;;
  esac
done

if [ -z "$REPO" ]; then
  echo "Error: --repo is required" >&2
  exit 1
fi

if [ ! -d "$REPO/.git" ] && ! git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1; then
  echo "Error: $REPO is not a git repository" >&2
  exit 1
fi

# ── Shallow clone guard ───────────────────────────────────────────────────────
IS_SHALLOW=false
if git -C "$REPO" rev-parse --is-shallow-repository >/dev/null 2>&1; then
  if [ "$(git -C "$REPO" rev-parse --is-shallow-repository 2>/dev/null)" = "true" ]; then
    IS_SHALLOW=true
  fi
elif [ -f "$REPO/.git/shallow" ]; then
  # Git < 2.15 fallback: presence of .git/shallow file indicates shallow clone
  IS_SHALLOW=true
fi

# ── Detached HEAD detection ───────────────────────────────────────────────────
DETACHED_HEAD=false
if ! git -C "$REPO" symbolic-ref -q HEAD >/dev/null 2>&1; then
  DETACHED_HEAD=true
fi

# ── Local HEAD ────────────────────────────────────────────────────────────────
LOCAL_HEAD=$(git -C "$REPO" rev-parse HEAD 2>/dev/null || echo "")
if [ -z "$LOCAL_HEAD" ]; then
  echo "Error: Could not resolve HEAD in $REPO" >&2
  exit 1
fi

# ── Timeout command detection (cross-platform) ────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TIMEOUT_CMD=""
if command -v timeout >/dev/null 2>&1; then
  TIMEOUT_CMD="timeout $TIMEOUT_SECONDS"
elif command -v gtimeout >/dev/null 2>&1; then
  TIMEOUT_CMD="gtimeout $TIMEOUT_SECONDS"
else
  # Fallback: Python subprocess timeout wrapper (inline, no extra file needed)
  TIMEOUT_CMD="python3 -c \"
import subprocess, sys, shlex
cmd = sys.argv[1:]
try:
    r = subprocess.run(cmd, timeout=$TIMEOUT_SECONDS, capture_output=False)
    sys.exit(r.returncode)
except subprocess.TimeoutExpired:
    sys.exit(124)
\" "
fi

# ── Enumerate remotes ─────────────────────────────────────────────────────────
REMOTES=$(git -C "$REPO" remote 2>/dev/null | sort -u)

if [ -z "$REMOTES" ]; then
  # No remotes configured — output minimal valid JSON
  jq -n \
    --arg repo_path "$REPO" \
    --arg branch "$BRANCH" \
    --arg local_head "$LOCAL_HEAD" \
    --argjson detached_head "$DETACHED_HEAD" \
    --argjson shallow "$IS_SHALLOW" \
    '{
      repo_path: $repo_path,
      branch: $branch,
      local_head: $local_head,
      detached_head: $detached_head,
      shallow: $shallow,
      remotes: [],
      overall_parity: true,
      has_unreachable_remote: false,
      has_pending_push: false
    }'
  exit 0
fi

# ── Build remotes JSON array ──────────────────────────────────────────────────
REMOTES_JSON="[]"

while IFS= read -r REMOTE; do
  [ -z "$REMOTE" ] && continue

  REMOTE_HEAD=""
  PARITY="unknown"
  BEHIND_COUNT=0
  AHEAD_COUNT=0
  REACHABLE="true"
  REASON="null"
  METHOD="$VERIFY_MODE"

  # ── Shallow clone: skip rev-list (unreliable), return unknown ─────────────
  if [ "$IS_SHALLOW" = "true" ]; then
    PARITY="unknown"
    REASON='"shallow_clone"'
    BEHIND_COUNT_JSON="null"
    AHEAD_COUNT_JSON="null"
    REACHABLE="true"
    REMOTE_HEAD_VAL=""

    ENTRY=$(jq -n \
      --arg name "$REMOTE" \
      --arg remote_head "$REMOTE_HEAD_VAL" \
      --arg parity "$PARITY" \
      --argjson behind_count null \
      --argjson ahead_count null \
      --argjson reachable true \
      --argjson reason '"shallow_clone"' \
      --arg method "$METHOD" \
      '{
        name: $name,
        remote_head: (if $remote_head == "" then null else $remote_head end),
        parity: $parity,
        behind_count: $behind_count,
        ahead_count: $ahead_count,
        reachable: $reachable,
        reason: "shallow_clone",
        method: $method
      }')
    REMOTES_JSON=$(echo "$REMOTES_JSON" | jq --argjson entry "$ENTRY" '. + [$entry]')
    continue
  fi

  # ── Detached HEAD: short-circuit with reason=detached_head ────────────────
  # In detached HEAD, per-remote comparison is ambiguous (no tracked branch).
  # Emit entry with reason=detached_head for each remote; top-level detached_head:true
  # signals consumers that parity values should be interpreted cautiously.
  if [ "$DETACHED_HEAD" = "true" ]; then
    ENTRY=$(jq -n \
      --arg name "$REMOTE" \
      --arg method "$METHOD" \
      '{
        name: $name,
        remote_head: null,
        parity: "unknown",
        behind_count: null,
        ahead_count: null,
        reachable: "unknown",
        reason: "detached_head",
        method: $method
      }')
    REMOTES_JSON=$(echo "$REMOTES_JSON" | jq --argjson entry "$ENTRY" '. + [$entry]')
    continue
  fi

  # ── Resolve remote head ───────────────────────────────────────────────────
  if [ "$VERIFY_MODE" = "local_refs" ]; then
    # local_refs mode: read from local tracking ref (no network)
    # NOTE: Use --verify -q to prevent rev-parse from echoing the literal ref name
    # when the ref doesn't exist. Without --verify, failed lookups print the ref
    # literal to stdout, bypassing the empty-string guard.
    REMOTE_HEAD=$(git -C "$REPO" rev-parse --verify -q "refs/remotes/$REMOTE/$BRANCH^{commit}" 2>/dev/null) || REMOTE_HEAD=""
    if [ -z "$REMOTE_HEAD" ]; then
      PARITY="unknown"
      REASON='"no_local_tracking_ref"'
      REACHABLE='"unknown"'

      ENTRY=$(jq -n \
        --arg name "$REMOTE" \
        --arg parity "$PARITY" \
        --argjson behind_count 0 \
        --argjson ahead_count 0 \
        --arg method "$METHOD" \
        '{
          name: $name,
          remote_head: null,
          parity: $parity,
          behind_count: $behind_count,
          ahead_count: $ahead_count,
          reachable: "unknown",
          reason: "no_local_tracking_ref",
          method: $method
        }')
      REMOTES_JSON=$(echo "$REMOTES_JSON" | jq --argjson entry "$ENTRY" '. + [$entry]')
      continue
    fi

  elif [ "$VERIFY_MODE" = "ls_remote" ]; then
    # ls_remote mode: query remote over network with timeout
    LS_OUTPUT=""
    LS_EXIT=0

    if command -v timeout >/dev/null 2>&1; then
      LS_OUTPUT=$(timeout "$TIMEOUT_SECONDS" git -C "$REPO" ls-remote "$REMOTE" "refs/heads/$BRANCH" 2>/dev/null) || LS_EXIT=$?
    elif command -v gtimeout >/dev/null 2>&1; then
      LS_OUTPUT=$(gtimeout "$TIMEOUT_SECONDS" git -C "$REPO" ls-remote "$REMOTE" "refs/heads/$BRANCH" 2>/dev/null) || LS_EXIT=$?
    else
      # Python subprocess timeout fallback
      LS_RESULT=$(python3 - <<PYEOF 2>/dev/null
import subprocess, sys, json
try:
    r = subprocess.run(
        ["git", "-C", "$REPO", "ls-remote", "$REMOTE", "refs/heads/$BRANCH"],
        capture_output=True, text=True, timeout=$TIMEOUT_SECONDS
    )
    result = {"rc": r.returncode, "out": r.stdout.strip()}
except subprocess.TimeoutExpired:
    result = {"rc": 124, "out": ""}
print(json.dumps(result))
PYEOF
)
      LS_OUTPUT=$(echo "$LS_RESULT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('out',''))" 2>/dev/null || echo "")
      LS_EXIT=$(echo "$LS_RESULT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('rc',1))" 2>/dev/null || echo "1")
    fi

    # Classify exit codes
    if [ "$LS_EXIT" -eq 124 ]; then
      # Timeout
      ENTRY=$(jq -n \
        --arg name "$REMOTE" \
        --arg method "$METHOD" \
        '{
          name: $name,
          remote_head: null,
          parity: "unknown",
          behind_count: null,
          ahead_count: null,
          reachable: false,
          reason: "network_timeout",
          method: $method
        }')
      REMOTES_JSON=$(echo "$REMOTES_JSON" | jq --argjson entry "$ENTRY" '. + [$entry]')
      continue
    elif [ "$LS_EXIT" -eq 128 ]; then
      # Auth failure
      ENTRY=$(jq -n \
        --arg name "$REMOTE" \
        --arg method "$METHOD" \
        '{
          name: $name,
          remote_head: null,
          parity: "unknown",
          behind_count: null,
          ahead_count: null,
          reachable: false,
          reason: "auth_failed",
          method: $method
        }')
      REMOTES_JSON=$(echo "$REMOTES_JSON" | jq --argjson entry "$ENTRY" '. + [$entry]')
      continue
    elif [ "$LS_EXIT" -ne 0 ]; then
      # Other error
      ENTRY=$(jq -n \
        --arg name "$REMOTE" \
        --arg method "$METHOD" \
        '{
          name: $name,
          remote_head: null,
          parity: "unknown",
          behind_count: null,
          ahead_count: null,
          reachable: false,
          reason: "error",
          method: $method
        }')
      REMOTES_JSON=$(echo "$REMOTES_JSON" | jq --argjson entry "$ENTRY" '. + [$entry]')
      continue
    fi

    # Parse SHA from ls-remote output (format: "<sha>\t<ref>")
    REMOTE_HEAD=$(echo "$LS_OUTPUT" | head -1 | cut -f1)
    if [ -z "$REMOTE_HEAD" ]; then
      # Branch not found on remote
      ENTRY=$(jq -n \
        --arg name "$REMOTE" \
        --arg method "$METHOD" \
        '{
          name: $name,
          remote_head: null,
          parity: "unknown",
          behind_count: null,
          ahead_count: null,
          reachable: true,
          reason: "not_found",
          method: $method
        }')
      REMOTES_JSON=$(echo "$REMOTES_JSON" | jq --argjson entry "$ENTRY" '. + [$entry]')
      continue
    fi
  fi

  # ── Parity calculation ────────────────────────────────────────────────────
  if [ "$LOCAL_HEAD" = "$REMOTE_HEAD" ]; then
    PARITY="equal"
    BEHIND_COUNT=0
    AHEAD_COUNT=0
  else
    # Calculate behind/ahead counts using local refs
    # Note: For ls_remote mode, we use the fetched SHA directly for rev-list
    # Update local ref temporarily if ls_remote mode (use the sha we got)
    if [ "$VERIFY_MODE" = "ls_remote" ]; then
      # Calculate against the remote SHA we fetched
      BEHIND_COUNT=$(git -C "$REPO" rev-list --count "HEAD..$REMOTE_HEAD" 2>/dev/null || echo "0")
      AHEAD_COUNT=$(git -C "$REPO" rev-list --count "$REMOTE_HEAD..HEAD" 2>/dev/null || echo "0")
    else
      BEHIND_COUNT=$(git -C "$REPO" rev-list --count "HEAD..refs/remotes/$REMOTE/$BRANCH" 2>/dev/null || echo "0")
      AHEAD_COUNT=$(git -C "$REPO" rev-list --count "refs/remotes/$REMOTE/$BRANCH..HEAD" 2>/dev/null || echo "0")
    fi

    if [ "$BEHIND_COUNT" -gt 0 ] && [ "$AHEAD_COUNT" -eq 0 ]; then
      PARITY="behind"
    elif [ "$AHEAD_COUNT" -gt 0 ] && [ "$BEHIND_COUNT" -eq 0 ]; then
      PARITY="ahead"
    elif [ "$AHEAD_COUNT" -gt 0 ] && [ "$BEHIND_COUNT" -gt 0 ]; then
      PARITY="diverged"
    else
      PARITY="unknown"
    fi
  fi

  # ── Build remote entry JSON ───────────────────────────────────────────────
  ENTRY=$(jq -n \
    --arg name "$REMOTE" \
    --arg remote_head "$REMOTE_HEAD" \
    --arg parity "$PARITY" \
    --argjson behind_count "$BEHIND_COUNT" \
    --argjson ahead_count "$AHEAD_COUNT" \
    --argjson reachable true \
    --arg method "$METHOD" \
    '{
      name: $name,
      remote_head: $remote_head,
      parity: $parity,
      behind_count: $behind_count,
      ahead_count: $ahead_count,
      reachable: $reachable,
      reason: null,
      method: $method
    }')
  REMOTES_JSON=$(echo "$REMOTES_JSON" | jq --argjson entry "$ENTRY" '. + [$entry]')

done <<< "$REMOTES"

# ── FETCH_HEAD staleness detection (local_refs mode only) ────────────────────
# Per Spec A: if verify_mode=local_refs and FETCH_HEAD mtime > 24h, flag stale.
LOCAL_REFS_STALE=false
if [ "$VERIFY_MODE" = "local_refs" ] && [ -f "$REPO/.git/FETCH_HEAD" ]; then
  # Get mtime (seconds since epoch) - portable across Linux/macOS
  if stat -c %Y "$REPO/.git/FETCH_HEAD" >/dev/null 2>&1; then
    FETCH_HEAD_MTIME=$(stat -c %Y "$REPO/.git/FETCH_HEAD" 2>/dev/null)
  elif stat -f %m "$REPO/.git/FETCH_HEAD" >/dev/null 2>&1; then
    FETCH_HEAD_MTIME=$(stat -f %m "$REPO/.git/FETCH_HEAD" 2>/dev/null)
  else
    FETCH_HEAD_MTIME=""
  fi
  if [ -n "$FETCH_HEAD_MTIME" ]; then
    NOW=$(date +%s)
    AGE_SECONDS=$((NOW - FETCH_HEAD_MTIME))
    # 24h = 86400s (default warn_after_hours)
    if [ "$AGE_SECONDS" -gt 86400 ]; then
      LOCAL_REFS_STALE=true
    fi
  fi
fi

# ── Compute summary fields ────────────────────────────────────────────────────
# overall_parity: true only if ALL remotes are "equal"
#   (ahead = pending push but not a parity failure, unknown = excluded)
#   Definition: false if any remote is "behind" or "diverged"
OVERALL_PARITY=$(echo "$REMOTES_JSON" | jq 'all(.[]; .parity != "behind" and .parity != "diverged")')

# has_pending_push: any remote with parity == "ahead"
HAS_PENDING_PUSH=$(echo "$REMOTES_JSON" | jq 'any(.[]; .parity == "ahead")')

# has_unreachable_remote: any remote with reachable == false
HAS_UNREACHABLE=$(echo "$REMOTES_JSON" | jq 'any(.[]; .reachable == false)')

# ── Final JSON output ─────────────────────────────────────────────────────────
jq -n \
  --arg repo_path "$REPO" \
  --arg branch "$BRANCH" \
  --arg local_head "$LOCAL_HEAD" \
  --argjson detached_head "$DETACHED_HEAD" \
  --argjson shallow "$IS_SHALLOW" \
  --argjson local_refs_stale "$LOCAL_REFS_STALE" \
  --argjson remotes "$REMOTES_JSON" \
  --argjson overall_parity "$OVERALL_PARITY" \
  --argjson has_unreachable_remote "$HAS_UNREACHABLE" \
  --argjson has_pending_push "$HAS_PENDING_PUSH" \
  '{
    repo_path: $repo_path,
    branch: $branch,
    local_head: $local_head,
    detached_head: $detached_head,
    shallow: $shallow,
    local_refs_stale: $local_refs_stale,
    remotes: $remotes,
    overall_parity: $overall_parity,
    has_unreachable_remote: $has_unreachable_remote,
    has_pending_push: $has_pending_push
  }'

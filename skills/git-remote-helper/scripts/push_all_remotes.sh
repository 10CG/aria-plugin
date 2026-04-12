#!/usr/bin/env bash
# push_all_remotes.sh — Git 多远程推送 (写操作, 仅授权 skill 调用)
#
# Usage:
#   bash push_all_remotes.sh --repo=<path> --branch=<name> \
#     [--remotes=origin,github]
#
# Output: JSON with pre/post SHA fields for consumer verification
#
# IMPORTANT: success is determined by SHA comparison, NOT exit code alone
#   success = (exit_code == 0) AND (post_remote_head == pre_local_head)
#
# Dependencies: jq (required)

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────────
REPO=""
BRANCH="master"
REMOTES_ARG=""

# ── Argument parsing ──────────────────────────────────────────────────────────
for arg in "$@"; do
  case "$arg" in
    --repo=*)     REPO="${arg#*=}" ;;
    --branch=*)   BRANCH="${arg#*=}" ;;
    --remotes=*)  REMOTES_ARG="${arg#*=}" ;;
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

# ── Validate branch exists locally ───────────────────────────────────────────
if ! git -C "$REPO" rev-parse --verify "$BRANCH" >/dev/null 2>&1; then
  echo "Error: branch '$BRANCH' does not exist in $REPO" >&2
  exit 1
fi

# ── Snapshot pre_local_head ───────────────────────────────────────────────────
PRE_LOCAL_HEAD=$(git -C "$REPO" rev-parse HEAD)

# ── Determine target remotes ──────────────────────────────────────────────────
if [ -n "$REMOTES_ARG" ]; then
  # Use whitelist (comma-separated)
  IFS=',' read -ra TARGET_REMOTES <<< "$REMOTES_ARG"
else
  # Push to all configured remotes
  mapfile -t TARGET_REMOTES < <(git -C "$REPO" remote 2>/dev/null | sort -u)
fi

if [ ${#TARGET_REMOTES[@]} -eq 0 ]; then
  # No remotes — output valid JSON indicating nothing to push
  jq -n \
    --arg repo_path "$REPO" \
    --arg branch "$BRANCH" \
    --arg pre_local_head "$PRE_LOCAL_HEAD" \
    '{
      repo_path: $repo_path,
      branch: $branch,
      pre_local_head: $pre_local_head,
      results: [],
      all_success: true
    }'
  exit 0
fi

# ── Push to each remote ───────────────────────────────────────────────────────
RESULTS_JSON="[]"
ALL_SUCCESS=true

for REMOTE in "${TARGET_REMOTES[@]}"; do
  REMOTE=$(echo "$REMOTE" | tr -d '[:space:]')
  [ -z "$REMOTE" ] && continue

  # Validate remote exists
  if ! git -C "$REPO" remote get-url "$REMOTE" >/dev/null 2>&1; then
    ENTRY=$(jq -n \
      --arg remote "$REMOTE" \
      '{
        remote: $remote,
        exit_code: 1,
        success: false,
        pre_remote_head: null,
        post_remote_head: null,
        message: ("Unknown remote \"" + $remote + "\"")
      }')
    RESULTS_JSON=$(echo "$RESULTS_JSON" | jq --argjson entry "$ENTRY" '. + [$entry]')
    ALL_SUCCESS=false
    continue
  fi

  # ── Snapshot pre_remote_head ────────────────────────────────────────────
  PRE_REMOTE_HEAD=$(git -C "$REPO" rev-parse "refs/remotes/$REMOTE/$BRANCH" 2>/dev/null || echo "")

  # ── Execute push ────────────────────────────────────────────────────────
  PUSH_OUTPUT=""
  PUSH_EXIT=0
  PUSH_OUTPUT=$(git -C "$REPO" push "$REMOTE" "$BRANCH" 2>&1) || PUSH_EXIT=$?

  # ── Snapshot post_remote_head ───────────────────────────────────────────
  # After a successful push, git updates refs/remotes/<remote>/<branch> locally.
  # We read this local ref — no network needed, no race condition.
  POST_REMOTE_HEAD=$(git -C "$REPO" rev-parse "refs/remotes/$REMOTE/$BRANCH" 2>/dev/null || echo "")

  # ── Strict success determination ────────────────────────────────────────
  # success = exit_code 0 AND post_remote_head matches pre_local_head
  # "Everything up-to-date" is handled correctly: if pre_remote == pre_local,
  # post_remote will still equal pre_local, so SHA comparison passes.
  # We do NOT parse the message text.
  if [ "$PUSH_EXIT" -eq 0 ] && [ -n "$POST_REMOTE_HEAD" ] && [ "$POST_REMOTE_HEAD" = "$PRE_LOCAL_HEAD" ]; then
    SUCCESS=true
  else
    SUCCESS=false
    ALL_SUCCESS=false
    if [ -z "$POST_REMOTE_HEAD" ]; then
      PUSH_OUTPUT="post-push verification failed: could not read refs/remotes/$REMOTE/$BRANCH"
    fi
  fi

  # Sanitize push output for JSON (truncate to avoid huge JSON)
  PUSH_MESSAGE=$(echo "$PUSH_OUTPUT" | head -5 | tr -d '\000-\037' | head -c 512)

  ENTRY=$(jq -n \
    --arg remote "$REMOTE" \
    --argjson exit_code "$PUSH_EXIT" \
    --argjson success "$SUCCESS" \
    --arg pre_remote_head "${PRE_REMOTE_HEAD:-}" \
    --arg post_remote_head "${POST_REMOTE_HEAD:-}" \
    --arg message "$PUSH_MESSAGE" \
    '{
      remote: $remote,
      exit_code: $exit_code,
      success: $success,
      pre_remote_head: (if $pre_remote_head == "" then null else $pre_remote_head end),
      post_remote_head: (if $post_remote_head == "" then null else $post_remote_head end),
      message: $message
    }')
  RESULTS_JSON=$(echo "$RESULTS_JSON" | jq --argjson entry "$ENTRY" '. + [$entry]')
done

# ── Final JSON output ─────────────────────────────────────────────────────────
jq -n \
  --arg repo_path "$REPO" \
  --arg branch "$BRANCH" \
  --arg pre_local_head "$PRE_LOCAL_HEAD" \
  --argjson results "$RESULTS_JSON" \
  --argjson all_success "$ALL_SUCCESS" \
  '{
    repo_path: $repo_path,
    branch: $branch,
    pre_local_head: $pre_local_head,
    results: $results,
    all_success: $all_success
  }'

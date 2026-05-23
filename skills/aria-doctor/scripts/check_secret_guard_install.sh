#!/usr/bin/env bash
# aria-doctor::check_secret_guard_install — detect dual-install state of
# aria-plugin v1.24.0+ default secret-guard hook vs. legacy project-local
# .claude/scripts/secret-guard.sh copy.
#
# Aria-plugin secret-guard hook v1.24.0+
#
# Spec: openspec/changes/aria-secret-guard-plugin-default §State Schema
# Memory: feedback_deterministic_structural_skill_rule6_substitute
#
# Usage:
#   bash check_secret_guard_install.sh [PROJECT_DIR] [PLUGIN_ROOT]
#
# Args:
#   PROJECT_DIR  — defaults to $CLAUDE_PROJECT_DIR or $PWD
#   PLUGIN_ROOT  — defaults to $CLAUDE_PLUGIN_ROOT;
#                  if unset, derived from the directory of this script
#                  (aria/skills/aria-doctor/scripts → aria/)
#
# Stdout: single-line compact JSON
#   {"state":"<primary>","sub_flags":[...],"advisory":"<text>","details":{...}}
#
# Exit:
#   0 — check succeeded (any state, including corrupted_settings)
#   2 — usage error (e.g. plugin root not resolvable)

set -u

PROJECT_DIR="${1:-${CLAUDE_PROJECT_DIR:-$PWD}}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEFAULT_PLUGIN_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"  # scripts → aria-doctor → skills → aria
PLUGIN_ROOT="${2:-${CLAUDE_PLUGIN_ROOT:-$DEFAULT_PLUGIN_ROOT}}"

PLUGIN_HOOK="$PLUGIN_ROOT/hooks/secret-guard.sh"
PLUGIN_JSON="$PLUGIN_ROOT/.claude-plugin/plugin.json"
LOCAL_HOOK="$PROJECT_DIR/.claude/scripts/secret-guard.sh"
SETTINGS_JSON="$PROJECT_DIR/.claude/settings.json"

# ── Banner regex spec (R2 QA NF2 closure) ─────────────────────────────────
# Project-local secret-guard.sh copies MAY optionally include a version
# banner in the file head matching this regex:
#   ^# (?:[Aa]ria(?:-plugin)?|[Ss]ecret-guard)[^\n]*\bv(\d+\.\d+\.\d+)\b
#
# Examples that match:
#   "# Aria-plugin secret-guard hook v1.24.0"
#   "# secret-guard.sh v1.2.0 (SilkNode upstream)"
#   "# Aria secret-guard v1.24.0+"
#
# When NO banner matches in the first 20 lines, version detection is
# undefined and `stale_local_version` sub-flag is NOT set (only
# `divergent_content` fires via SHA256 compare). This handles the
# current SilkNode HEAD bytewise-cherry-picked copy gracefully.
BANNER_REGEX='^# (Aria(-plugin)?|secret-guard)[^\n]*\bv([0-9]+\.[0-9]+\.[0-9]+)\b'

# ── Helper: extract version from banner (returns empty on no match) ───────
extract_banner_version() {
  local file="$1"
  [ -f "$file" ] || { echo ""; return; }
  head -n 20 "$file" 2>/dev/null \
    | grep -oE 'v[0-9]+\.[0-9]+\.[0-9]+' \
    | head -n 1 \
    | sed 's/^v//'
}

# ── Helper: extract plugin SOT version from plugin.json ───────────────────
extract_plugin_version() {
  [ -f "$PLUGIN_JSON" ] || { echo ""; return; }
  jq -r '.version // empty' "$PLUGIN_JSON" 2>/dev/null
}

# ── Helper: compare semver (returns 0 if v1<v2, 1 if v1>=v2) ──────────────
version_lt() {
  local v1="$1" v2="$2"
  [ -z "$v1" ] || [ -z "$v2" ] && return 1
  [ "$(printf '%s\n%s' "$v1" "$v2" | sort -V | head -n 1)" = "$v1" ] && [ "$v1" != "$v2" ]
}

# ── Helper: sha256 (empty if file missing) ────────────────────────────────
sha256_of() {
  local file="$1"
  [ -f "$file" ] || { echo ""; return; }
  sha256sum "$file" 2>/dev/null | awk '{print $1}'
}

# ── Helper: JSON-escape a string for embedding in compact output ──────────
json_escape() {
  local s="$1"
  printf '%s' "$s" | python3 -c 'import json,sys; sys.stdout.write(json.dumps(sys.stdin.read()))'
}

# ── Detection ─────────────────────────────────────────────────────────────
plugin_present=0
local_present=0
settings_corrupted=0

[ -f "$PLUGIN_HOOK" ] && plugin_present=1
[ -f "$LOCAL_HOOK" ] && local_present=1

# settings.json parse check — corrupted_settings takes precedence (mutex)
if [ -f "$SETTINGS_JSON" ]; then
  if ! jq -e . "$SETTINGS_JSON" >/dev/null 2>&1; then
    settings_corrupted=1
  fi
fi

# ── Primary state derivation (mutex) ──────────────────────────────────────
state=""
sub_flags=()
advisory=""

plugin_version="$(extract_plugin_version)"
local_version=""
plugin_sha=""
local_sha=""

if [ "$settings_corrupted" -eq 1 ]; then
  state="corrupted_settings"
  advisory=".claude/settings.json parse failed; aria-plugin hooks may still load via plugin SOT, but project-local registration is broken. Fix JSON or remove the file."
elif [ "$plugin_present" -eq 1 ] && [ "$local_present" -eq 1 ]; then
  state="dual_install"
  local_version="$(extract_banner_version "$LOCAL_HOOK")"
  plugin_sha="$(sha256_of "$PLUGIN_HOOK")"
  local_sha="$(sha256_of "$LOCAL_HOOK")"

  # divergent_content if SHAs differ
  if [ -n "$plugin_sha" ] && [ -n "$local_sha" ] && [ "$plugin_sha" != "$local_sha" ]; then
    sub_flags+=("divergent_content")
  fi

  # stale_local_version only if BOTH versions defined AND local < plugin
  if [ -n "$local_version" ] && [ -n "$plugin_version" ] && version_lt "$local_version" "$plugin_version"; then
    sub_flags+=("stale_local_version")
  fi

  if [ ${#sub_flags[@]} -eq 0 ]; then
    advisory="Double defense active (plugin + local hooks both fire on same event, per Q1 hook orchestrator merge semantics — see standards/conventions/secret-hygiene.md §5.4). KEEP as-is recommended for at least 1 minor cycle as fallback."
  else
    advisory="Dual install with divergence — investigate before any cleanup. divergent_content alone may indicate owner-local customization (preserve via Path 2 ack); divergent_content + stale_local_version typically means local is an older upstream snapshot — sync from plugin SOT or delete local copy."
  fi
elif [ "$plugin_present" -eq 1 ] && [ "$local_present" -eq 0 ]; then
  state="single_plugin"
  advisory="Plugin-default secret-guard active; no project-local copy. Expected state for new projects onboarded after aria-plugin v1.24.0."
elif [ "$plugin_present" -eq 0 ] && [ "$local_present" -eq 1 ]; then
  state="single_local"
  # R2 BA N2 closure: include both possible causes in advisory
  advisory="Project-local secret-guard.sh present but plugin hook not detected. Possible causes: (1) aria-plugin not loaded in current session (check ${CLAUDE_PLUGIN_ROOT:-CLAUDE_PLUGIN_ROOT env}); OR (2) aria-plugin version < v1.24.0 (predates plugin-default secret-guard). Run aria-doctor full check or aria-plugin upgrade."
else
  state="not_installed"
  # R2 BA N1 closure: declare runtime reachability semantics
  advisory="Neither plugin nor project-local secret-guard hook detected. Under normal plugin-loaded execution this state should assert-never (aria-plugin v1.24.0+ ships secret-guard as a built-in default hook). Reaching this state implies aria-plugin not loaded or PLUGIN_ROOT mis-resolved — verify CLAUDE_PLUGIN_ROOT and aria-plugin install."
fi

# ── Output (compact single-line JSON) ─────────────────────────────────────
# Build sub_flags JSON array
sub_flags_json="[]"
if [ ${#sub_flags[@]} -gt 0 ]; then
  sub_flags_json="[$(printf '"%s",' "${sub_flags[@]}" | sed 's/,$//')]"
fi

# Build details object
plugin_ver_json="null"
local_ver_json="null"
plugin_sha_json="null"
local_sha_json="null"
[ -n "$plugin_version" ] && plugin_ver_json="$(json_escape "$plugin_version")"
[ -n "$local_version" ] && local_ver_json="$(json_escape "$local_version")"
[ -n "$plugin_sha" ] && plugin_sha_json="$(json_escape "$plugin_sha")"
[ -n "$local_sha" ] && local_sha_json="$(json_escape "$local_sha")"

advisory_json="$(json_escape "$advisory")"
state_json="$(json_escape "$state")"

cat <<JSON
{"state":${state_json},"sub_flags":${sub_flags_json},"advisory":${advisory_json},"details":{"plugin_hook_present":$([ $plugin_present -eq 1 ] && echo true || echo false),"local_hook_present":$([ $local_present -eq 1 ] && echo true || echo false),"settings_json_valid":$([ $settings_corrupted -eq 0 ] && echo true || echo false),"plugin_version":${plugin_ver_json},"local_version":${local_ver_json},"plugin_sha256":${plugin_sha_json},"local_sha256":${local_sha_json},"plugin_hook_path":$(json_escape "$PLUGIN_HOOK"),"local_hook_path":$(json_escape "$LOCAL_HOOK")}}
JSON

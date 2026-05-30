#!/usr/bin/env bash
# jq-crlf-guard.sh — regression guard for shell-jq-crlf-hardening (#132 follow-up).
#
# Scans production shell scripts for jq-output consumption that READS values into
# shell variables/arrays without a CR strip — the class of bug behind #132 (and
# its siblings). Windows native jq emits CRLF; bash consumers keep the \r, which
# breaks gate/comparison logic.
#
# Usage:  bash aria/hooks/tests/jq-crlf-guard.sh [PATH ...]
#   default scan set = hooks/*.sh + skills/**/*.sh (excluding test files).
# Exit 0 = clean, 1 = unguarded site(s) found (printed with fix guidance).
#
# Two flagged patterns (the consuming forms — NOT jq -n constructors):
#   A. readarray/mapfile/while-read  < <( … jq … )   → needs `| tr -d '\r'`
#   B. VAR=$( … jq -r … )  capturing a scalar/field   → needs `${VAR%$'\r'}`
#      (line-anchored, so echo-embedded snippets and `jq -n`/`jq 'all('`/
#       `--argjson` accumulators are naturally NOT matched)
#
# Exemptions (a site is OK if any holds):
#   - the jq pipe already has `tr -d '\r'`
#   - Pattern B: a `${VAR%$'\r'}` strip of the SAME var within the next 3 lines
#   - an explicit `# crlf-ok` annotation on the capture line (data body / verified
#     safe — must state why)

set -u

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"   # aria-plugin root
violations=()

scan_file() {
  local f="$1"
  local -a lines
  mapfile -t lines < "$f"
  local n=${#lines[@]} i line
  for ((i=0; i<n; i++)); do
    line="${lines[i]}"

    # Pattern A: process-substitution into readarray/mapfile/while-read from jq
    if [[ "$line" =~ (readarray|mapfile|while[[:space:]].*read).*\<[[:space:]]*\<\(.*jq[[:space:]] ]]; then
      if [[ "$line" != *"tr -d '\r'"* && "$line" != *"# crlf-ok"* ]]; then
        violations+=("$f:$((i+1)): [A readarray<<(jq)] missing \`| tr -d '\\r'\` → $line")
      fi
      continue
    fi

    # Pattern B: line-anchored VAR=$( … jq -r … ) scalar/field capture
    if [[ "$line" =~ ^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*=.*\$\(.*jq[[:space:]]+-r[[:space:]] ]]; then
      # not a constructor and not already stripped on-line / annotated
      if [[ "$line" == *"tr -d '\r'"* || "$line" == *"# crlf-ok"* || "$line" == *"jq -n"* ]]; then
        continue
      fi
      # extract var name
      local var="${line#"${line%%[![:space:]]*}"}"   # ltrim
      var="${var%%=*}"
      # look ahead 5 lines for a ${var%...\r...} strip (accommodates an if/else/fi
      # block or grouped multi-var strips between capture and strip)
      local j stripped=0
      for ((j=i+1; j<=i+5 && j<n; j++)); do
        if [[ "${lines[j]}" == *"\${${var}%"* ]]; then stripped=1; break; fi
      done
      if [[ "$stripped" -eq 0 ]]; then
        violations+=("$f:$((i+1)): [B VAR=\$(jq -r) capture '$var'] missing \`\${${var}%\$'\\r'}\` strip (or # crlf-ok) → $line")
      fi
    fi
  done
}

# Build scan set
declare -a files
if [[ $# -gt 0 ]]; then
  files=("$@")
else
  mapfile -t files < <(find "$ROOT/hooks" "$ROOT/skills" -name '*.sh' \
    -not -path '*/tests/*' -not -name '*.test.sh' 2>/dev/null | sort)
fi

for f in "${files[@]}"; do
  [[ -f "$f" ]] && scan_file "$f"
done

if [[ ${#violations[@]} -gt 0 ]]; then
  echo "jq-crlf-guard: ${#violations[@]} unguarded jq-consumption site(s):" >&2
  printf '  %s\n' "${violations[@]}" >&2
  echo >&2
  echo "Fix: append \`| tr -d '\\r'\` to the jq pipe (multi-line readarray) or" >&2
  echo "     add \`VAR=\"\${VAR%\$'\\r'}\"\` after the capture (single value), or" >&2
  echo "     annotate \`# crlf-ok: <reason>\` if the value is a data body / verified safe." >&2
  exit 1
fi
echo "jq-crlf-guard: clean (${#files[@]} files scanned)"
exit 0

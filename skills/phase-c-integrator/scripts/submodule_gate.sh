#!/usr/bin/env bash
# submodule_gate.sh — Phase C.2.4.5 Submodule Pointer Regression Gate (B+)
#
# Spec: openspec/changes/aria-submodule-pointer-regression-gate/proposal.md (Approved 2026-05-24)
# DEC: .aria/decisions/2026-05-24-aria-124-submodule-pointer-regression-gate.md
# Forgejo: Aria #124
# Source incident: 2026-05-23 PR #123 (6fea5d7 silent regression + a8e0096 fast-forward fix)
#
# Usage:
#   ./submodule_gate.sh                    # gate the current PR's submodule pointers
#   ARIA_SUBMODULE_GATE_MODE=block ./submodule_gate.sh   # force block mode
#   ARIA_SUBMODULE_GATE_MODE=off ./submodule_gate.sh     # skip entirely
#
# Env vars:
#   ARIA_SUBMODULE_GATE_MODE=warn|block|off   (default: read from .aria/config.json,
#                                              fallback "warn" for v1.28.0)
#   ARIA_PR_NUMBER=N                           (optional: enables Forgejo PR label override)
#   ARIA_FORGEJO_REPO=10CG/Aria                (optional: defaults via remote URL inspection)
#
# Exit codes:
#   0  = gate PASS (forward bump / no-change / first-time / override) OR warn-mode WOULD-BLOCK logged
#   1  = block-mode BLOCK (regression or divergence, no override)
#   2  = fetch failure (all 3 retries exhausted; terminal)
#   3  = origin/master history rewritten (non-ancestor advance); operator confirm required
#   4  = git ls-tree / merge-base error (submodule fetch incomplete)
#   64 = usage error
#   65 = environment error (git missing, not a repo)

set -uo pipefail  # NOTE: no -e — we manage exit codes per-submodule deliberately

# ─── Config ────────────────────────────────────────────────────────────

MODE="${ARIA_SUBMODULE_GATE_MODE:-warn}"

# Locate aria-plugin metrics dir (relative to current repo root)
# When invoked from main Aria, plugin root = "aria/" submodule mount → "aria/metrics/"
# When invoked from inside aria-plugin (e.g., during plugin dev), root = "." → "metrics/"
if [[ -d "aria/metrics" ]]; then
    METRICS_DIR="aria/metrics"
elif [[ -d "metrics" ]]; then
    METRICS_DIR="metrics"
else
    # Create the most likely location (assume main repo)
    METRICS_DIR="${ARIA_METRICS_DIR:-aria/metrics}"
    mkdir -p "$METRICS_DIR" 2>/dev/null || METRICS_DIR="metrics"
    mkdir -p "$METRICS_DIR" 2>/dev/null || true
fi

WARNS_FILE="$METRICS_DIR/submodule-gate-warns.jsonl"
BLOCKS_FILE="$METRICS_DIR/submodule-gate-blocks.jsonl"
OVERRIDES_FILE="$METRICS_DIR/submodule-gate-overrides.jsonl"

FETCH_RETRIES=(1 2 4)

# ─── Pre-flight ────────────────────────────────────────────────────────

command -v git >/dev/null 2>&1 || { echo "ERROR: git CLI not found" >&2; exit 65; }
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "ERROR: not in a git repo" >&2; exit 65; }

# Off mode = skip entirely
if [[ "$MODE" == "off" ]]; then
    echo "INFO: submodule_gate.sh mode=off; skipping (per .aria/config.json or env)"
    exit 0
fi

# ─── Helpers ───────────────────────────────────────────────────────────

iso_now() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

log_telemetry() {
    # $1 = file, $2 = verdict, $3 = submodule, $4 = master_sha, $5 = feature_sha, $6 = mode/reason
    local file="$1" verdict="$2" sub="$3" master="$4" feature="$5" extra="$6"
    local pr="${ARIA_PR_NUMBER:-unknown}"
    local ts
    ts=$(iso_now)
    # JSONL append-only (kernel atomic write for <PIPE_BUF=4096 bytes)
    printf '{"timestamp":"%s","pr_id":"%s","submodule":"%s","master_sha":"%s","feature_sha":"%s","verdict":"%s","mode_or_reason":"%s","human_reviewed_as_fp":null}\n' \
        "$ts" "$pr" "$sub" "$master" "$feature" "$verdict" "$extra" >> "$file"
}

check_override_trailer() {
    # $1 = submodule, $2 = master_sha, $3 = feature_sha
    # Returns 0 if valid trailer present, 1 otherwise
    local sub="$1" master="$2" feature="$3"
    local msg
    msg=$(git log -1 --format=%B HEAD 2>/dev/null || echo "")
    [[ -z "$msg" ]] && return 1

    # Match both Unicode →(U+2192) and ASCII -> per Rev1 R1-ba-4 fix
    # Pattern: ^Submodule-Rollback: <sub> <old>(→|->)<new> reason=<...>$
    local line
    while IFS= read -r line; do
        if [[ "$line" =~ ^Submodule-Rollback:[[:space:]]+([^[:space:]]+)[[:space:]]+([^[:space:]→\>]+)(→|->)([^[:space:]]+)[[:space:]]+reason=.+ ]]; then
            local trailer_sub="${BASH_REMATCH[1]}"
            local trailer_old="${BASH_REMATCH[2]}"
            local trailer_new="${BASH_REMATCH[4]}"
            [[ "$trailer_sub" != "$sub" ]] && continue

            # SHA normalization (per Rev1 R1-qa M-qa-5 fix): resolve short to full
            local resolved_old resolved_new
            resolved_old=$(git -C "$sub" rev-parse "$trailer_old" 2>/dev/null) || continue
            resolved_new=$(git -C "$sub" rev-parse "$trailer_new" 2>/dev/null) || continue

            # Verify trailer SHAs match actual MASTER/FEATURE pointers
            if [[ "$resolved_old" == "$master" && "$resolved_new" == "$feature" ]]; then
                return 0
            fi
        fi
    done <<< "$msg"
    return 1
}

check_pr_label() {
    # $1 = required label
    # Returns 0 if PR has label, 1 otherwise (or on API failure → conservative no-label)
    local label="$1"
    [[ -z "${ARIA_PR_NUMBER:-}" ]] && return 1
    [[ -z "${ARIA_FORGEJO_REPO:-}" ]] && {
        # Try to infer from origin URL
        local origin_url
        origin_url=$(git remote get-url origin 2>/dev/null || echo "")
        if [[ "$origin_url" =~ /([^/]+)/([^/]+)\.git$ ]]; then
            ARIA_FORGEJO_REPO="${BASH_REMATCH[1]}/${BASH_REMATCH[2]}"
        else
            return 1
        fi
    }

    command -v forgejo >/dev/null 2>&1 || return 1

    local resp
    resp=$(forgejo GET "/repos/$ARIA_FORGEJO_REPO/issues/$ARIA_PR_NUMBER/labels" 2>/dev/null) || return 1
    echo "$resp" | grep -q "\"name\":[[:space:]]*\"$label\"" && return 0
    return 1
}

check_override() {
    # $1 = submodule, $2 = master_sha, $3 = feature_sha
    # Returns 0 if any override allows, 1 otherwise
    check_override_trailer "$1" "$2" "$3" && return 0
    check_pr_label "submodule-rollback-approved" && return 0
    return 1
}

# ─── Step 1: fail-loud fetch with bounded retries ──────────────────────

BEFORE_REMOTE=$(git rev-parse origin/master 2>/dev/null || echo "FIRST_RUN")

FETCH_OK=0
for delay in "${FETCH_RETRIES[@]}"; do
    if git fetch origin 2>&1; then
        FETCH_OK=1
        break
    fi
    sleep "$delay"
done

if [[ "$FETCH_OK" != 1 ]]; then
    log_telemetry "$BLOCKS_FILE" "FETCH_FAILURE" "(all)" "$BEFORE_REMOTE" "(unknown)" "fetch_exhausted_retries"
    echo "BLOCK: git fetch origin failed after ${#FETCH_RETRIES[@]} attempts (delays: ${FETCH_RETRIES[*]}s)" >&2
    echo "       Submodule pointer ancestry cannot be verified safely." >&2
    echo "       Manual remediation: investigate auth (PAT expiry?), network connectivity, or origin URL drift, then retry merge." >&2
    exit 2
fi

# ─── Step 2: refspec assertion ─────────────────────────────────────────

AFTER_REMOTE=$(git rev-parse origin/master 2>/dev/null || echo "FIRST_RUN")

if [[ "$BEFORE_REMOTE" != "FIRST_RUN" && "$BEFORE_REMOTE" != "$AFTER_REMOTE" ]]; then
    # origin/master moved; verify ancestry (legitimate forward advance vs history rewrite)
    if ! git merge-base --is-ancestor "$BEFORE_REMOTE" "$AFTER_REMOTE" 2>/dev/null; then
        log_telemetry "$BLOCKS_FILE" "ORIGIN_REWRITE" "(all)" "$BEFORE_REMOTE" "$AFTER_REMOTE" "non_ancestor_advance"
        echo "BLOCK: origin/master rewritten during fetch (non-ancestor advance: $BEFORE_REMOTE -> $AFTER_REMOTE)" >&2
        echo "       Operator confirm required: someone force-pushed to master." >&2
        exit 3
    fi
fi

# ─── Step 3: per-submodule loop ────────────────────────────────────────

exit_code=0
affected_count=0

# Enumerate submodules from .gitmodules (skip if no submodules)
if [[ ! -f .gitmodules ]]; then
    echo "INFO: no .gitmodules in repo; gate trivially passes"
    exit 0
fi

while IFS= read -r SUB; do
    [[ -z "$SUB" ]] && continue
    [[ ! -d "$SUB" ]] && {
        echo "INFO: $SUB enumerated in .gitmodules but directory absent; skipping"
        continue
    }

    # Per-submodule fetch (best-effort; ancestry check below catches stale)
    git -C "$SUB" fetch origin >/dev/null 2>&1 || true

    FEATURE_PTR=$(git ls-tree HEAD "$SUB" 2>/dev/null | awk '{print $3}')
    MASTER_PTR=$(git ls-tree origin/master "$SUB" 2>/dev/null | awk '{print $3}')

    # nil-SHA: first-time submodule (master had no gitlink at this path)
    if [[ -z "$MASTER_PTR" ]]; then
        echo "INFO: $SUB first introduced this PR (no prior master gitlink); gate PASS"
        continue
    fi

    # No-change
    if [[ "$FEATURE_PTR" == "$MASTER_PTR" ]]; then
        echo "OK: $SUB unchanged ($FEATURE_PTR)"
        continue
    fi

    echo "GATE: submodule=$SUB master=$MASTER_PTR feature=$FEATURE_PTR"

    # Forward bump?
    if git -C "$SUB" merge-base --is-ancestor "$MASTER_PTR" "$FEATURE_PTR" 2>/dev/null; then
        echo "PASS: $SUB forward bump"
        continue
    fi

    # Not forward — distinguish REGRESSION (feature is ancestor of master)
    # vs DIVERGENT (neither is ancestor of other)
    if git -C "$SUB" merge-base --is-ancestor "$FEATURE_PTR" "$MASTER_PTR" 2>/dev/null; then
        VERDICT="REGRESSION"
    else
        # Could be DIVERGENT, or exit 128 (SHA not in submodule DB)
        # Verify SHAs exist before declaring DIVERGENT
        if ! git -C "$SUB" cat-file -e "$FEATURE_PTR" 2>/dev/null; then
            echo "BLOCK: $SUB feature SHA $FEATURE_PTR not found in submodule DB after fetch (incomplete fetch?)" >&2
            log_telemetry "$BLOCKS_FILE" "FETCH_INCOMPLETE" "$SUB" "$MASTER_PTR" "$FEATURE_PTR" "feature_sha_missing"
            exit_code=4
            continue
        fi
        if ! git -C "$SUB" cat-file -e "$MASTER_PTR" 2>/dev/null; then
            echo "BLOCK: $SUB master SHA $MASTER_PTR not found in submodule DB after fetch" >&2
            log_telemetry "$BLOCKS_FILE" "FETCH_INCOMPLETE" "$SUB" "$MASTER_PTR" "$FEATURE_PTR" "master_sha_missing"
            exit_code=4
            continue
        fi
        VERDICT="DIVERGENT"
    fi

    affected_count=$((affected_count + 1))

    # Check override (commit trailer OR PR label)
    if check_override "$SUB" "$MASTER_PTR" "$FEATURE_PTR"; then
        echo "ALLOW: $SUB $VERDICT overridden by per-PR marker (audit logged)"
        log_telemetry "$OVERRIDES_FILE" "$VERDICT" "$SUB" "$MASTER_PTR" "$FEATURE_PTR" "override_applied"
        continue
    fi

    # Mode dispatch
    if [[ "$MODE" == "warn" ]]; then
        echo "WOULD-BLOCK: submodule=$SUB master=$MASTER_PTR feature=$FEATURE_PTR reason=$VERDICT" >&2
        log_telemetry "$WARNS_FILE" "$VERDICT" "$SUB" "$MASTER_PTR" "$FEATURE_PTR" "warn"
    else
        # block mode
        echo "BLOCK: $VERDICT — submodule=$SUB master=$MASTER_PTR feature=$FEATURE_PTR" >&2
        echo "       Override 1: add commit trailer 'Submodule-Rollback: $SUB $MASTER_PTR->$FEATURE_PTR reason=<reason>' to merge commit message" >&2
        echo "       Override 2: add PR label 'submodule-rollback-approved' (maintainer only)" >&2
        log_telemetry "$BLOCKS_FILE" "$VERDICT" "$SUB" "$MASTER_PTR" "$FEATURE_PTR" "block"
        [[ "$exit_code" == 0 ]] && exit_code=1
    fi
done < <(git config --file .gitmodules --get-regexp '^submodule\..*\.path$' 2>/dev/null | awk '{print $2}')

# ─── Summary ───────────────────────────────────────────────────────────

if [[ "$exit_code" == 0 ]]; then
    if [[ "$affected_count" == 0 ]]; then
        echo "✓ submodule_gate: all submodules unchanged/forward/first-time (mode=$MODE)"
    else
        echo "✓ submodule_gate: $affected_count submodule(s) flagged but allowed (mode=$MODE)"
    fi
fi

exit $exit_code

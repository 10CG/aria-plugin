#!/usr/bin/env bash
# submodule-tripwire-audit.sh — R-fix-2 (Spec aria-submodule-gate-operationalize TG-2).
#
# === Why ===
# The post-merge tripwire (.forgejo/workflows/submodule-gate-tripwire.yml) failed
# 5/5 dispatches: the Forgejo Actions runner cannot clone the `ssh://forgejo@...`
# submodules (no forgejo credentials; forgejo is behind Cloudflare Access). OQ2=(c):
# migrate the audit to a HOST cron, where forgejo IS reachable and submodules ARE
# checked out — sidestepping the runner→forgejo wall entirely.
#
# This is the standalone, locally-runnable + testable audit. A host cron invokes it
# (cron installation is owner infra, see §Install below). Same misses.jsonl telemetry
# contract as the workflow it replaces.
#
# === What ===
# For each submodule, compare its gitlink SHA at HEAD~1 vs HEAD (superproject tree).
# If the old SHA is NOT an ancestor of the new SHA (and they differ), a regression /
# divergence escaped the pre-merge gate (B+) → record a MISS + (optionally) file a
# Forgejo issue. Always record a tripwire_run heartbeat (outage detection).
#
# === Usage ===
#   ./submodule-tripwire-audit.sh                 # audit HEAD~1..HEAD in CWD superproject
#   ARIA_TRIPWIRE_DRY_RUN=1 ./submodule-tripwire-audit.sh   # no jsonl append, no issue
#   ARIA_TRIPWIRE_FILE_ISSUE=1 ./submodule-tripwire-audit.sh # file Forgejo issue on miss
#
# === Env ===
#   ARIA_METRICS_DIR        metrics dir (default: aria/metrics or metrics, auto-detected)
#   ARIA_TRIPWIRE_DRY_RUN   "1" → no side effects (no jsonl, no issue)
#   ARIA_TRIPWIRE_FILE_ISSUE "1" → file Forgejo issue on miss (needs `forgejo` CLI)
#   ARIA_FORGEJO_REPO       owner/repo for issue filing (default: inferred from origin)
#
# === Exit codes ===
#   0 = clean (no escaped regression) OR dry-run
#   1 = MISS detected (≥1 submodule regression/divergence escaped)
#   65 = environment error (not a git repo / no HEAD~1)
#
# === Install (host cron — owner infra) ===
#   # weekly, Sundays 04:00 UTC, in the superproject checkout that has forgejo access:
#   0 4 * * 0  cd /path/to/Aria && git pull -q && \
#     bash aria/skills/phase-c-integrator/scripts/submodule-tripwire-audit.sh >> /var/log/aria-tripwire.log 2>&1
#   # Writes aria/metrics/submodule-gate-misses.jsonl on a durable host volume
#   # (per feedback_periodic_job_acceptance_data_on_durable_volume).

set -uo pipefail

# ─── Pre-flight ───
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "ERROR: not a git repository" >&2
    exit 65
fi
if ! git rev-parse HEAD~1 >/dev/null 2>&1; then
    echo "ERROR: no HEAD~1 (need ≥2 commits to compare)" >&2
    exit 65
fi
if [[ ! -f .gitmodules ]]; then
    echo "INFO: no .gitmodules; tripwire trivially clean"
    exit 0
fi

DRY_RUN="${ARIA_TRIPWIRE_DRY_RUN:-0}"

# ─── Metrics dir (mirror submodule_gate.sh resolution) ───
if [[ -d "aria/metrics" ]]; then
    METRICS_DIR="aria/metrics"
elif [[ -d "metrics" ]]; then
    METRICS_DIR="metrics"
else
    METRICS_DIR="${ARIA_METRICS_DIR:-aria/metrics}"
    mkdir -p "$METRICS_DIR" 2>/dev/null || METRICS_DIR="metrics"
    mkdir -p "$METRICS_DIR" 2>/dev/null || true
fi
# Honor explicit ARIA_METRICS_DIR override even when a default dir exists.
[[ -n "${ARIA_METRICS_DIR:-}" ]] && METRICS_DIR="$ARIA_METRICS_DIR" && mkdir -p "$METRICS_DIR" 2>/dev/null || true
MISSES_FILE="$METRICS_DIR/submodule-gate-misses.jsonl"

iso_now() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

# ─── Audit HEAD~1 vs HEAD per submodule ───
declare -a MISSES=()
while IFS= read -r SUB; do
    [[ -z "$SUB" ]] && continue
    OLD=$(git ls-tree HEAD~1 "$SUB" 2>/dev/null | awk '{print $3}')
    NEW=$(git ls-tree HEAD "$SUB" 2>/dev/null | awk '{print $3}')
    [[ -z "$OLD" || -z "$NEW" ]] && continue       # first-time / removed
    [[ "$OLD" == "$NEW" ]] && continue              # no change

    git -C "$SUB" fetch origin --quiet 2>/dev/null || true

    # Guard against false MISS on incomplete fetch (mirrors submodule_gate.sh
    # FETCH_INCOMPLETE): if either SHA is absent from the submodule DB, the
    # merge-base would fail and wrongly flag a MISS. Skip + warn instead.
    if ! git -C "$SUB" cat-file -e "$OLD" 2>/dev/null || ! git -C "$SUB" cat-file -e "$NEW" 2>/dev/null; then
        echo "WARN: $SUB SHA missing from submodule DB (incomplete fetch); skipping ancestry check" >&2
        continue
    fi

    if ! git -C "$SUB" merge-base --is-ancestor "$OLD" "$NEW" 2>/dev/null; then
        MISSES+=("$SUB:$OLD:$NEW")
        echo "MISS: $SUB $OLD !ancestor-of $NEW (regression/divergence escaped gate)" >&2
    fi
done < <(git config --file .gitmodules --get-regexp '^submodule\..*\.path$' 2>/dev/null | awk '{print $2}')

COMMIT=$(git rev-parse HEAD 2>/dev/null || echo unknown)
RESULT="clean"; [[ ${#MISSES[@]} -gt 0 ]] && RESULT="miss"

# ─── Telemetry (heartbeat always; miss records on miss) ───
if [[ "$DRY_RUN" != "1" ]]; then
    printf '{"timestamp":"%s","kind":"tripwire_run","result":"%s","commit":"%s","source":"host-cron"}\n' \
        "$(iso_now)" "$RESULT" "$COMMIT" >> "$MISSES_FILE" 2>/dev/null || true
    # Guard empty-array expansion under `set -u` (fatal on Bash ≤4.3, e.g. macOS 3.2
    # / old CentOS — host-cron env is uncontrolled, and clean=empty is the common path).
    if [[ ${#MISSES[@]} -gt 0 ]]; then
        for m in "${MISSES[@]}"; do
            sub="${m%%:*}"; rest="${m#*:}"; old="${rest%%:*}"; new="${rest#*:}"
            printf '{"timestamp":"%s","kind":"tripwire_miss","submodule":"%s","old_sha":"%s","new_sha":"%s","commit":"%s","source":"host-cron"}\n' \
                "$(iso_now)" "$sub" "$old" "$new" "$COMMIT" >> "$MISSES_FILE" 2>/dev/null || true
        done
    fi
fi

# NOTE: submodule-gate-misses.jsonl is additive-superset vs the original workflow
# (adds `tripwire_miss` kind + `source` field). No strict-schema parser consumes it
# (only human review + `gate-tripwire-count` label counting) — verified R-fix-2.

# ─── Optional Forgejo issue on miss ───
if [[ "$RESULT" == "miss" && "$DRY_RUN" != "1" && "${ARIA_TRIPWIRE_FILE_ISSUE:-0}" == "1" ]] && command -v forgejo >/dev/null 2>&1; then
    repo="${ARIA_FORGEJO_REPO:-}"
    if [[ -z "$repo" ]]; then
        # best-effort infer owner/repo from origin URL
        repo=$(git remote get-url origin 2>/dev/null | sed -E 's#.*[:/]([^/]+/[^/]+)(\.git)?$#\1#; s#\.git$##')
    fi
    if [[ -n "$repo" ]]; then
        # Real newlines (printf) — a double-quoted "\n" would reach the issue body
        # as literal backslash-n (jq --arg doesn't interpret it).
        miss_lines=$(printf '%s\n' "${MISSES[@]}")
        body=$(printf 'Submodule pointer regression escaped (B+) gate — detected by host-cron tripwire.\n\nCommit: %s\nMisses:\n%s\n\n/label gate-tripwire-count' "$COMMIT" "$miss_lines")
        forgejo POST "/repos/$repo/issues" -d "$(jq -n --arg t "tripwire: submodule regression escaped (B+) — $COMMIT" --arg b "$body" '{title:$t,body:$b,labels:["gate-tripwire-count"]}')" >/dev/null 2>&1 || true
    fi
fi

if [[ "$RESULT" == "miss" ]]; then
    echo "✗ tripwire MISS — ${#MISSES[@]} submodule regression(s); see $MISSES_FILE" >&2
    exit 1
fi
echo "✓ tripwire clean — no submodule regressions in HEAD~1..HEAD"
exit 0

#!/usr/bin/env bash
# lib/secret-guard-w10-direct.sh HOOK MODE : the direct-call cases of the W10 fail-closed narrowing (10CG/aria-plugin#217), ported from v31/sc-direct.sh:
# ids, assertions, wanted values, reason tags and the sentinel unchanged. secret-guard.test.sh (sg_w10_cases) runs it with SC_BASH, the bash being tested,
# and turns its lines into PASS, FAIL or SKIP. MODE relax = a bash the relaxation is expected on (the gate must open; mechanism cases with a stubbed
# judgement at a 1 s deadline; growth, count, checkpoint and rows-only cases) | norelax = any other bash (the gate must stay closed; every case of the
# relaxation is reported once, as SKIP [platform], so both modes report the same ids). Changed from v31: the fallback-text cases (V6-S20, V6-S21) compare
# with the block the same hook writes when the gate is closed by WSL_DISTRO_NAME, set in the shell that sources it (no baseline file, no git history);
# that gate-closed call must itself give the status and text kind 59e333c gives for the same copy and mode (fbref, measured on the five bash in 3c), else
# FAIL [reference]: it runs the hook under test, so a slip in code or a constant both calls share would move both alike and the byte comparison would stay
# green (the suite's [reference]; the time text there is TIMED). A case whose tool is missing on the platform (ps) is SKIP [platform], not FAIL.
# The hook is sourced: it stops at its unit-test sourcing gate, so only the functions above that gate exist; risky_patterns, _sg_judge_one and
# _sg_redact_echo (below it) are pulled out by anchor, as the suite's SC-8 harness does. One line per case:
#   PASS|FAIL|MISSING|SETUP <id> <detail>   MISSING: a function the case calls is not defined in the hook under test (status 127 if it were called);
#                                            SETUP: the case could not be built (an injection anchor not found). The suite reports both as FAIL.
#   SKIP <id> [reason] <detail>             [platform]: see above; [root]: RLIMIT_NPROC does not bind this process, so no fork failure can be made
#                                            (post_planning R2 PP2-m2)
#   TIMED <id> <hard> <soft> <detail>       a case with a part that depends on the speed of the host: hard (ok|bad) = the checks no load explains
#                                            (status, text, bytes, lower bounds); soft (ok|bad) = the upper bound, or "the job finished before its
#                                            deadline". The suite turns it into PASS, FAIL or SKIP by the load rule of INV-7 (post_planning R2 PP2-A).
# A failed check names itself in the detail with a tag: [status] [rc] [stderr] [bytes] [value] [kind] [text] [count] [judged] [leftover] [wall<lo]
# [wall>hi] [fallback] [reference]. The last line is the sentinel "END sc-direct": a run that stops early (set -u, a crash) has none, and the suite reports that
# (V0-H1). SC_ONLY (set by the suite from SG_W10_ONLY) skips the slow cases that are not selected; the suite filters the lines again.
H=$1; MODE=$2
unset CLAUDE_PROJECT_DIR SECRET_GUARD_TIME_BUDGET_S WSL_DISTRO_NAME WSL_INTEROP _SG_RELAXED   # the caller's environment decides no case (R2 PP2-m14; WSL marks)
source "$H" </dev/null >/dev/null 2>&1
set +e
input=''; command=''
X=$(mktemp -d); trap 'rm -rf "$X"' EXIT
U=$$   # unique to this run: every stub process carries it in its arguments, so the leftover checks never count another run's stubs (R2 PP2-K)
SCO=${SC_ONLY:-.}
sel() { [[ "$1" =~ $SCO ]]; }
out() { printf '%s %s %s\n' "$1" "$2" "$3"; }
chk() { if [[ $1 == 0 ]]; then out PASS "$2" "$3"; else out FAIL "$2" "$3 $4"; fi; }   # STATUS-OF-THE-CHECK ID DETAIL TAG
NEEDMISS=''
need() { local f; for f in "$@"; do declare -F "$f" >/dev/null 2>&1 || { NEEDMISS=$f; return 1; }; done; return 0; }
miss() { local id; for id in "$@"; do out MISSING "$id" "[missing] the hook under test does not define $NEEDMISS"; done; }
timed() { printf 'TIMED %s %s %s %s\n' "$1" "$2" "$3" "$4"; }
tags3() {   # GOT WANT ("status text-kind count" fields): one tag per differing field
  local g w n i t=''; g=($1); w=($2); n=(status kind count)
  for i in 0 1 2; do [[ "${g[i]-}" == "${w[i]-}" ]] || t="$t[${n[i]}] "; done; printf '%s' "${t% }"; }
el() { awk -v a="${1/,/.}" -v b="${2/,/.}" 'BEGIN{printf "%.2f", b-a}'; }
ge() { awk -v a="$1" -v b="$2" 'BEGIN{exit !(a+0 >= b+0)}'; }
le() { awk -v a="$1" -v b="$2" 'BEGIN{exit !(a+0 <= b+0)}'; }
kindf() { if grep -q 'has a line longer than' "$1"; then echo longline; elif grep -q 'grows by more than' "$1"; then echo growth
  elif grep -q 'segments together are longer than' "$1"; then echo tmax; elif grep -q 'variable value is longer than' "$1"; then echo vmax
  elif grep -q 'too large to scan' "$1"; then echo oversize; elif grep -q 'within the time budget' "$1"; then echo time
  elif grep -q 'value-REDACTING filter' "$1"; then echo finding; elif [[ -s "$1" ]]; then echo other; else echo none; fi; }
cfg="/etc/forg""ejo/app"".ini"   # a credential-bearing config path, assembled here: no case ever reads it, the hook only judges text
x4=$(printf '%*s' 4000 '' | tr ' ' x); fill=$(printf ' y%.0s' $(seq 1 300)); fill100=$(printf ' y%.0s' $(seq 1 100))
# the parts of the hook below the sourcing gate that a case needs (by anchor, as the suite's SC-8 harness does)
awk '/^declare -a risky_patterns=\(/,/^\)$/' "$H" > "$X/rp.sh"; awk '/^_sg_judge_one\(\) \{/,/^\}$/' "$H" > "$X/jo.sh"; awk '/^_sg_redact_echo\(\) \{/,/^\}$/' "$H" > "$X/re.sh"
BELOW=no
if [[ -s "$X/rp.sh" && -s "$X/jo.sh" && -s "$X/re.sh" ]]; then source "$X/rp.sh"; source "$X/jo.sh"; source "$X/re.sh"; BELOW=yes; fi
nobelow() { local id; for id in "$@"; do out SETUP "$id" "risky_patterns / _sg_judge_one / _sg_redact_echo not found by anchor"; done; }
want_gate() { [[ $MODE == relax ]] && echo 0 || echo 1; }
gate() { _sg_relax_ok; echo $?; }
WG=$(want_gate)
RELAX_IDS="V3-G9-clock-backwards V3-G10-cap-3 V3-G12-time-left-zero-padded
V4-S1-allow V4-S2-block-with-text V4-S3-block-without-text V3-S4-slow-judgement V5-S5-pipe-holder V4-S6-spoofed-tail-0 V4-S7-time-checkpoint V4-S8-internal-error
V5-S9-child-left-behind V5-S13-detached-child V5-S13b-nothing-outlives-the-run V4-S11-bare-zero V5-S10-timer-fork-fails V5-S10b-no-judgement-without-timer
V5-S10c-dead-timer-no-judgement V5-S10d-no-judgement-with-dead-timer V5-S14-failing-sleep-kills-at-once V5-S15-job-refuses-outside-group-leader
V4-S19-block-text-bytes V5-S12-no-leftovers V4-S16-rerun-collect-checkpoint V4-S17-rerun-whole-checkpoint V4-S18-rerun-segment-checkpoint
V6-S20-segment-fallback-text V6-S21-whole-fallback-text
V8-D1-late-references-plain V8-D1-late-references-braced V8-D2-growth-8192-plain V8-D3-growth-8193-plain V8-D2-growth-8192-braced V8-D3-growth-8193-braced
V8-D4-growth-text-whole V8-D5-growth-text-segment
V9-C1-assignments-rerun V9-C1b-assignments-baseline V9-C2-references-rerun-c12 V9-C2b-references-baseline-c12 V9-C2-references-rerun-cb12
V9-C2b-references-baseline-cb12 V9-C3-for-statements-rerun V9-C3b-for-statements-baseline V9-C4-value-limit-in-rerun
V10-N1-environ-rows-only V10-N2-read-rows-only V10-N3-environ-big-judge V10-N4-read-big-judge V7-N5-read-big-judge-short-lines
V10-N6-filtered-long-line-rows-only V7-N7-big-judge-filtered-long-line V7-N10-blank-padded-long-line V7-N11-lmax-edge-normal V7-N12-lmax-edge-rows-only
V7-N8-whole-branch-returns-big-judge V7-N9-segment-routes-to-big-judge V7-N13-unmeasured-length-rows-only
V14-N1-nocredit-never-runs-credit V14-N2-longline-pattern-is-a-rule V14-G1-triggers-return-4-with-the-baseline-reason V14-G2-growth-limit-follows-gmax V14-F1-status-4-falls-back-to-the-baseline-block"   # the cases of MODE relax; SKIP [platform] in MODE norelax
OSR=$(cat /proc/sys/kernel/osrelease 2>/dev/null); WSLM=''; [[ -e /proc/sys/fs/binfmt_misc/WSLInterop ]] && WSLM=wsl

# ---------------- P2: the gate (both modes) ----------------
if need _sg_relax_ok; then
  _SG_P0=${EPOCHREALTIME:-}; r=$(gate); [[ $r == "$WG" ]]; chk $? V2-G1-gate "this bash: status $r (want $WG)" "[status]"
else miss V2-G1-gate; fi
# What 1 supplement (owner 2026-10-23): MACHINE MAJOR MINOR OSRELEASE [WSL]; only an x86_64 GNU/Linux build of bash 5.0-5.3 outside WSL opens it.
# Columns: case id suffix | machine | major | minor | kernel string (- = empty) | WSL mark (- = none; args3 = called with three arguments only) | want
while read -r sfx m ma mi osr wm w; do
  id="V2-G2-platform:$sfx"; [[ $osr == - ]] && osr=''
  if need _sg_relax_platform; then
    if [[ $wm == args3 ]]; then _sg_relax_platform "$m" "$ma" "$mi"; r=$?   # a missing argument closes the gate; under set -u it must not stop the caller
    else [[ $wm == - ]] && wm=''; _sg_relax_platform "$m" "$ma" "$mi" "$osr" "$wm"; r=$?; fi
    [[ $r == "$w" ]]; chk $? "$id" "status $r (want $w)" "[status]"
  else miss "$id"; fi
done <<'T'
x86_64-pc-linux-gnu:5.0 x86_64-pc-linux-gnu 5 0 6.8.0-45-generic - 0
x86_64-pc-linux-gnu:5.1 x86_64-pc-linux-gnu 5 1 6.8.0-45-generic - 0
x86_64-pc-linux-gnu:5.2 x86_64-pc-linux-gnu 5 2 6.8.0-45-generic - 0
x86_64-pc-linux-gnu:5.3 x86_64-pc-linux-gnu 5 3 6.8.0-45-generic - 0
aarch64-unknown-linux-gnu:5.2 aarch64-unknown-linux-gnu 5 2 6.8.0-45-generic - 1
x86_64-pc-linux-gnu:5.4 x86_64-pc-linux-gnu 5 4 6.8.0-45-generic - 1
x86_64-pc-linux-gnu:6.0 x86_64-pc-linux-gnu 6 0 6.8.0-45-generic - 1
x86_64-pc-linux-gnu:4.4 x86_64-pc-linux-gnu 4 4 6.8.0-45-generic - 1
x86_64-unknown-linux-gnu:3.2 x86_64-unknown-linux-gnu 3 2 6.8.0-45-generic - 1
x86_64-apple-darwin23.0.0:5.2 x86_64-apple-darwin23.0.0 5 2 6.8.0-45-generic - 1
x86_64-pc-msys:5.2 x86_64-pc-msys 5 2 6.8.0-45-generic - 1
x86_64-pc-cygwin:5.2 x86_64-pc-cygwin 5 2 6.8.0-45-generic - 1
x86_64-alpine-linux-musl:5.2 x86_64-alpine-linux-musl 5 2 6.8.0-45-generic - 1
aarch64-unknown-linux-android:5.2 aarch64-unknown-linux-android 5 2 6.8.0-45-generic - 1
x86_64-pc-linux-gnu:5.2:osrelease-wsl1 x86_64-pc-linux-gnu 5 2 4.4.0-19041-Microsoft - 1
x86_64-pc-linux-gnu:5.2:osrelease-wsl2 x86_64-pc-linux-gnu 5 2 5.15.153.1-microsoft-standard-WSL2 - 1
x86_64-pc-linux-gnu:5.2:osrelease-wsl2-2020 x86_64-pc-linux-gnu 5 2 4.19.128-microsoft-standard - 1
x86_64-pc-linux-gnu:5.2:osrelease-WSL-tag x86_64-pc-linux-gnu 5 2 6.6.36.3-WSL2-custom - 1
x86_64-pc-linux-gnu:5.2:wsl-mark x86_64-pc-linux-gnu 5 2 6.8.0-45-generic wsl 1
x86_64-pc-linux-gnu:5.2:osrelease-empty x86_64-pc-linux-gnu 5 2 - - 1
x86_64-pc-linux-gnu:5.2:three-args x86_64-pc-linux-gnu 5 2 - args3 1
T
if need _sg_relax_ok _sg_relax_platform; then
  saved_pl=$(declare -f _sg_relax_platform)
  _sg_relax_platform() { return 1; }
  _SG_P0=${EPOCHREALTIME:-}; r=$(gate); [[ $r == 1 ]]; chk $? V2-G3-gate-calls-platform "status $r with the platform check failing (want 1)" "[status]"
  M=$X/pl; rm -f "$M"; _sg_relax_platform() { printf '%s|%s|%s|%s|%s' "${1-}" "${2-}" "${3-}" "${4-}" "${5-}" > "$M"; return 0; }
  r=$( OSTYPE=darwin21; MACHTYPE=x86_64-apple-darwin23.0.0; HOSTTYPE=aarch64; _SG_P0=${EPOCHREALTIME:-}; gate >/dev/null; cat "$M" 2>/dev/null )
  exp="${BASH_VERSINFO[5]}|${BASH_VERSINFO[0]}|${BASH_VERSINFO[1]}|$OSR|$WSLM"
  [[ "$r" == "$exp" ]]; chk $? V2-G3b-gate-uses-build-facts "platform check got [$r], want [$exp] (OSTYPE, MACHTYPE and HOSTTYPE set to darwin / aarch64: R2 PP2-m8)" "[value]"
  eval "$saved_pl"
else miss V2-G3-gate-calls-platform V2-G3b-gate-uses-build-facts; fi
mkdir -p "$X/p1/.aria" "$X/p2/.aria" "$X/p3/.aria" "$X/p4/.aria/secret-guard.paths"
printf '%s\n' "some/entry/path" > "$X/p2/.aria/secret-guard.paths"; : > "$X/p3/.aria/secret-guard.paths"
for c in "p1 $WG project-without-extension-file" "p2 1 extension-file-with-entry" "p3 1 empty-extension-file" "p4 1 extension-path-is-a-directory"; do
  set -- $c
  if need _sg_relax_ok; then
    r=$( export CLAUDE_PROJECT_DIR="$X/$1"; _SG_P0=${EPOCHREALTIME:-}; gate ); [[ $r == "$2" ]]; chk $? "V2-G4-$3" "status $r (want $2)" "[status]"
  else miss "V2-G4-$3"; fi
done
if need _sg_relax_ok; then
  r=$( _SG_RELAXED=1; _SG_P0=${EPOCHREALTIME:-}; gate ); [[ $r == 1 ]]; chk $? V2-G5-nested "status $r (want 1)" "[status]"
  r=$( SECRET_GUARD_TIME_BUDGET_S=1; _SG_P0=$(awk -v e="${EPOCHREALTIME:-0}" 'BEGIN{sub(",",".",e); printf "%.6f", e-1.5}'); gate ); [[ $r == 1 ]]; chk $? V2-G6-no-time-left "status $r (want 1)" "[status]"
  r=$( _SG_P0=; gate ); [[ $r == 1 ]]; chk $? V2-G7-no-anchor "status $r (want 1)" "[status]"
  r=$( SECRET_GUARD_TIME_BUDGET_S=0; _SG_P0=${EPOCHREALTIME:-}; gate ); [[ $r == 1 ]]; chk $? V2-G8-budget-0 "status $r (want 1)" "[status]"
else miss V2-G5-nested V2-G6-no-time-left V2-G7-no-anchor V2-G8-budget-0; fi
r=$(env _SG_RELAXED=1 "$BASH" -c 'source "$1" </dev/null >/dev/null 2>&1; printf "[%s]" "${_SG_RELAXED-unset}"' _ "$H")
[[ $r == "[]" ]]; chk $? V2-G11-flag-not-from-environment "a hook sourced with _SG_RELAXED=1 in its environment holds $r (want [])" "[value]"
# both trigger points ask the gate (R2 PP2-D): with the platform check failing, a copy over 8192 is the baseline size block (2), never 4
cseg="x=$x4; : \$x \$x$fill"; cwh="(true); x=$x4; : \$x \$x$fill"
for c in "V2-G12-segment-trigger-asks-gate segment" "V2-G13-whole-trigger-asks-gate whole"; do
  set -- $c
  if ! need _sg_vx_pass; then miss "$1"; continue; fi
  if [[ $BELOW != yes ]]; then nobelow "$1"; continue; fi
  r=$( _sg_relax_platform() { return 1; }; _SG_RELAXED=; _SG_P0=${EPOCHREALTIME:-}
       if [[ $2 == segment ]]; then cmd=$cseg; _SG_SEGS=("x=$x4" ": \$x \$x$fill"); else cmd=$cwh; fi; command=$cmd
       _sg_vx_pass "$cmd" "$2" >/dev/null 2>"$X/g12"; echo "$? $(kindf "$X/g12")" )
  [[ $r == "2 oversize" ]]; chk $? "$1" "the platform check failing, a $2 copy over 8192: status/text [$r] (want [2 oversize], never 4)" "$(tags3 "$r" "2 oversize")"
done
# the project root through the stdin cwd (R2 PP2-D); the WSL marks of the environment (What 1 supplement): they can only close the gate
if need _sg_relax_ok; then
  r=$( unset CLAUDE_PROJECT_DIR; input="{\"tool_name\":\"Bash\",\"cwd\":\"$X/p2\"}"; _SG_P0=${EPOCHREALTIME:-}; gate ); [[ $r == 1 ]]
  chk $? V2-G14-cwd-extension-file-with-entry "the project root only through the stdin cwd, its extension file has an entry: status $r (want 1)" "[status]"
  r=$( unset CLAUDE_PROJECT_DIR; input="{\"tool_name\":\"Bash\",\"cwd\":\"$X/p1\"}"; _SG_P0=${EPOCHREALTIME:-}; gate ); [[ $r == "$WG" ]]
  chk $? V2-G15-cwd-project-without-extension-file "the project root only through the stdin cwd, no extension file: status $r (want $WG)" "[status]"
  r=$( export CLAUDE_PROJECT_DIR="$X/p1"; input="{\"tool_name\":\"Bash\",\"cwd\":\"$X/p2\"}"; _SG_P0=${EPOCHREALTIME:-}; gate ); [[ $r == "$WG" ]]
  chk $? V2-G16-environment-root-before-cwd "CLAUDE_PROJECT_DIR without an extension, a stdin cwd with one: status $r (want $WG: the environment's root comes first)" "[status]"
  r=$( export WSL_DISTRO_NAME=Ubuntu; _SG_P0=${EPOCHREALTIME:-}; gate ); [[ $r == 1 ]]; chk $? V2-G17-wsl-distro-name-closes-gate "WSL_DISTRO_NAME set: status $r (want 1)" "[status]"
  r=$( export WSL_INTEROP=/run/WSL/8_interop; _SG_P0=${EPOCHREALTIME:-}; gate ); [[ $r == 1 ]]; chk $? V2-G18-wsl-interop-closes-gate "WSL_INTEROP set: status $r (want 1)" "[status]"
else miss V2-G14-cwd-extension-file-with-entry V2-G15-cwd-project-without-extension-file V2-G16-environment-root-before-cwd V2-G17-wsl-distro-name-closes-gate V2-G18-wsl-interop-closes-gate; fi

# ---------------- the longline text, verbatim (Rule #6 block B: proposal What 5; both modes) ----------------
if ! need _sg_emit_blocked; then miss V11-S5-longline-head-verbatim V11-S6-longline-chinese-line-verbatim V11-S7-longline-text-verbatim
elif [[ $BELOW != yes ]]; then nobelow V11-S5-longline-head-verbatim V11-S6-longline-chinese-line-verbatim V11-S7-longline-text-verbatim
else
  L=${_SGV_LMAX:-8192}; command='cat /tmp/sc-x'
  _sg_emit_blocked 'PAT-X' 'SEG-X' whole longline 2>"$X/ll" >/dev/null
  cat > "$X/ll-want" <<EOF
[secret-guard] BLOCKED: command reads a secret-bearing source, and after variable
expansion it has a line longer than $L characters. Matched pattern: PAT-X

At this size the guard does not look for value-REDACTING filters (| jq 'keys',
| wc -c, >/dev/null, ...): on a line this long that check alone is too slow to
finish within the hook's time limit, so the match alone blocks the command
(fail-closed).

Split it into smaller commands and run them one at a time:
  - keep every variable value, and every command after expansion, short;
  - do not repeat one long \$VAR many times in a single command;
  - write long files with the Write / Edit tool instead of a heredoc.
命令读取含密钥的来源, 且变量展开后有超长的行, 这个尺寸下不评估脱敏过滤, 请拆成更小的命令

Command was (first 200 characters): cat /tmp/sc-x
EOF
  hd() { awk '/^Split it into smaller commands/{exit} {print}' "$1"; }                 # the description: everything before the instruction lines
  zh() { awk '/^Command was/{print prev; exit} NF{prev=$0}' "$1"; }                    # the line in Chinese: the last non-empty line before "Command was"
  dl() { diff <(printf '%s\n' "$1") <(printf '%s\n' "$2") | awk '/^[<>]/{print; n++} n==2{exit}' | tr '\n' ' ' | cut -c1-160; }
  a=$(hd "$X/ll"); b=$(hd "$X/ll-want"); [[ "$a" == "$b" ]]
  chk $? V11-S5-longline-head-verbatim "the description of the longline text equals proposal What 5 ($(printf '%s\n' "$b" | wc -l) lines)" "[text] $(dl "$a" "$b")"
  a=$(zh "$X/ll"); b=$(zh "$X/ll-want"); [[ "$a" == "$b" ]]
  chk $? V11-S6-longline-chinese-line-verbatim "the line in Chinese equals proposal What 5" "[text] got [$a]"
  cmp -s "$X/ll" "$X/ll-want"
  chk $? V11-S7-longline-text-verbatim "the whole longline text equals proposal What 5 ($(wc -c < "$X/ll-want") bytes)" "[text] $(dl "$(cat "$X/ll")" "$(cat "$X/ll-want")")"
fi

if [[ $MODE == relax ]]; then
  # ---------------- P3: the deadline value ----------------
  if need _sg_relax_left; then
    r=$( SECRET_GUARD_TIME_BUDGET_S=1; _SG_P0=$(awk -v e="$EPOCHREALTIME" 'BEGIN{sub(",",".",e); printf "%.6f", e+5}'); _sg_relax_left; echo "${_SG_LEFT:-}" )
    awk -v l="$r" 'BEGIN{exit !(l>0 && l<=1.0)}'; chk $? V3-G9-clock-backwards "time left $r with the anchor 5 s in the future, budget 1 (want 0 < left <= 1.000000)" "[value]"
    r=$( SECRET_GUARD_TIME_BUDGET_S=4; _SG_P0=$EPOCHREALTIME; _sg_relax_left; echo "${_SG_LEFT:-}" )
    awk -v l="$r" 'BEGIN{exit !(l>2.9 && l<=3.0)}'; chk $? V3-G10-cap-3 "time left $r at budget 4 (want 2.9 < left <= 3.000000: min(budget, 3))" "[value]"
    # R2 PP2-m13: the microseconds are zero-padded. A stopped clock (EPOCHREALTIME loses its special meaning once unset) 0.95 s after the anchor, budget 3
    r=$( unset EPOCHREALTIME; EPOCHREALTIME=1700000000.950000; _SG_P0=1700000000.000000; SECRET_GUARD_TIME_BUDGET_S=3; _sg_relax_left; echo "$? ${_SG_LEFT:-}" )
    [[ $r == "0 2.050000" ]]; chk $? V3-G12-time-left-zero-padded "status and time left [$r] on a stopped clock 0.95 s after the anchor, budget 3 (want [0 2.050000])" "[value]"
  else miss V3-G9-clock-backwards V3-G10-cap-3 V3-G12-time-left-zero-padded; fi

  # ---------------- P3 / P4 / P5: the job, with a stubbed judgement; deadline 1 s ----------------
  export SECRET_GUARD_TIME_BUDGET_S=1; _SG_MODE=whole
  jrun() {   # sets JRC JW JERR: _sg_relax_run on the current stub. The temp file first, then the anchor and the stopwatch at one instant (R2 PP2-A)
    local t0 t1
    JERR=$(mktemp -p "$X")
    t0=$EPOCHREALTIME; _SG_P0=$t0
    _sg_relax_run "cmd" 2>"$JERR"; JRC=$?
    t1=$EPOCHREALTIME; JW=$(el "$t0" "$t1")
  }
  jcase() {   # id want_rc min_wall max_wall want_stderr : rc, stderr and the lower bound are hard; the upper bound is soft. A case that wants the job to
              # finish (rc 0 or 2) and gets the bare fallback (rc 4, no text) is soft: the 1 s deadline cut a job that a slow host had not finished.
    local id=$1 want=$2 lo=$3 hi=$4 wsd=$5 sd hard=ok soft=ok t=''
    need _sg_relax_run _sg_relax_job || { miss "$id"; return 0; }
    jrun; sd=$(cat "$JERR")
    if [[ $JRC == "$want" ]]; then
      [[ "$sd" == "$wsd" ]] || { hard=bad; t+=' [stderr]'; }
      ge "$JW" "$lo" || { hard=bad; t+=' [wall<lo]'; }
      le "$JW" "$hi" || { soft=bad; t+=' [wall>hi]'; }
    elif [[ $want != 4 && $JRC == 4 && -z "$sd" ]]; then soft=bad; t+=' [fallback]'
    else hard=bad; t+=' [rc]'; fi
    timed "$id" $hard $soft "rc=$JRC (want $want) wall=${JW}s (want $lo..$hi) stderr=$(printf '%q' "${sd:0:40}") (want $(printf '%q' "$wsd"))$t"
  }
  lv() { ps -eo args | awk -v a="$1" '$1=="sleep" && $2==a' | wc -l; }
  lv5() { ps -eo args | awk -v u="$U" '$1=="sleep" && ($2=="10.111" u || $2=="6.222" u || $2=="10.333" u || $2=="2.718" u || $2=="7.777" u)' | wc -l; }
  if sel V4-S1-allow; then _sg_vx_pass() { return 0; }; jcase V4-S1-allow 0 0 0.3 ''; fi
  if sel V4-S2-block-with-text; then _sg_vx_pass() { echo "BLOCK TEXT" >&2; return 2; }; jcase V4-S2-block-with-text 2 0 0.3 'BLOCK TEXT'; fi
  if sel V4-S3-block-without-text; then _sg_vx_pass() { return 2; }; jcase V4-S3-block-without-text 4 0 0.3 ''; fi
  if sel V3-S4-slow-judgement; then _sg_vx_pass() { sleep "10.111$U"; return 0; }; jcase V3-S4-slow-judgement 4 0.85 1.3 ''; fi
  if sel V5-S5-pipe-holder; then _sg_vx_pass() { sleep "6.222$U" & wait; return 0; }; jcase V5-S5-pipe-holder 4 0.85 1.3 ''; fi
  if sel V4-S6-spoofed-tail-0; then _sg_vx_pass() { { sleep 0.5; printf 'x\n0\n' >&2; } & sleep "10.333$U"; return 0; }; jcase V4-S6-spoofed-tail-0 4 0.85 1.3 ''; fi
  if sel V4-S7-time-checkpoint; then _sg_vx_pass() { return 3; }; jcase V4-S7-time-checkpoint 4 0 0.3 ''; fi
  if sel V4-S8-internal-error; then _sg_vx_pass() { echo "$undefined_var_xyz"; return 0; }; jcase V4-S8-internal-error 4 0 0.3 ''; fi
  if sel V5-S9-child-left-behind; then _sg_vx_pass() { sleep "2.718$U" & return 0; }; jcase V5-S9-child-left-behind 0 0 0.3 ''; fi
  if sel V5-S13-detached-child || sel V5-S13b-nothing-outlives-the-run; then
    # budget 3 for this pair: the 1 s grace below must end well before the job's own timer would kill the group anyway (at 1 s it would hide BI-15)
    _sg_vx_pass() { sleep "7.777$U" >/dev/null 2>&1 & return 0; }; SECRET_GUARD_TIME_BUDGET_S=3 jcase V5-S13-detached-child 0 0 0.3 ''
    if ! command -v ps >/dev/null 2>&1; then out SKIP V5-S13b-nothing-outlives-the-run "[platform] ps not found: the processes left behind cannot be counted"
    elif need _sg_relax_run _sg_relax_job; then
      n=$(lv "7.777$U"); i=0; while (( n > 0 && i < 10 )); do sleep 0.1; n=$(lv "7.777$U"); i=$((i+1)); done   # at most 1 s of grace (R2 PP2-K)
      [[ $n == 0 ]]; chk $? V5-S13b-nothing-outlives-the-run "a child that does not hold the pipe, alive within 1 s after _sg_relax_run returned: $n (want 0; sleep 7.777$U is unique to this run)" "[leftover]"
    else miss V5-S13b-nothing-outlives-the-run; fi
  fi
  if sel V4-S11-bare-zero; then
    saved_job=$(declare -f _sg_relax_job)
    _sg_relax_job() { return 0; }; jcase V4-S11-bare-zero 4 0 0.3 ''
    unset -f _sg_relax_job; [[ -n "$saved_job" ]] && eval "$saved_job"
  fi
  nproc_binds() {   # status 0 when RLIMIT_NPROC binds this process. It does not for uid 0, nor with CAP_SYS_RESOURCE or CAP_SYS_ADMIN (getrlimit(2)); then probe
    local c; c=$(awk '/^CapEff:/{print $2}' /proc/self/status 2>/dev/null)
    if [[ "$(id -u)" != 0 && "$c" =~ ^[0-9a-fA-F]+$ ]] && (( ((16#$c >> 21) & 1) == 0 && ((16#$c >> 24) & 1) == 0 )); then return 0; fi
    ( ulimit -u 1 2>/dev/null; exec sh -c 'true & wait' ) >/dev/null 2>&1 && return 1   # the fork went through: the limit does not bind
    return 0
  }
  if sel V5-S10-timer-fork-fails || sel V5-S10b-no-judgement-without-timer; then
    if ! need _sg_relax_run _sg_relax_job; then miss V5-S10-timer-fork-fails V5-S10b-no-judgement-without-timer
    elif ! nproc_binds; then
      for id in V5-S10-timer-fork-fails V5-S10b-no-judgement-without-timer; do out SKIP "$id" "[root] RLIMIT_NPROC does not bind this process (uid 0, CAP_SYS_RESOURCE or CAP_SYS_ADMIN): no fork failure can be made (R2 PP2-m2)"; done
    else
      saved_job=$(declare -f _sg_relax_job)
      MK=$X/ran-10; rm -f "$MK"; _sg_vx_pass() { echo ran > "$MK"; return 0; }
      inj=$(declare -f _sg_relax_job | sed '0,/local me=\$BASHPID tp/s//local me=$BASHPID tp; ulimit -u 1/')
      if [[ "$inj" == *"ulimit -u 1"* ]]; then
        eval "$inj"; jcase V5-S10-timer-fork-fails 4 0 16.5 ''
        [[ ! -e "$MK" ]]; chk $? V5-S10b-no-judgement-without-timer "judgement started: $([[ -e $MK ]] && echo yes || echo no) (want no)" "[judged]"
        eval "$saved_job"
      else
        for id in V5-S10-timer-fork-fails V5-S10b-no-judgement-without-timer; do out SETUP "$id" "the timer line (local me=\$BASHPID tp) was not found in _sg_relax_job"; done
      fi
    fi
  fi
  # the defensive branch itself: a timer that is not running (here: replaced by a process that has already ended) -> no judgement at all
  if sel V5-S10c-dead-timer-no-judgement || sel V5-S10d-no-judgement-with-dead-timer; then
    if need _sg_relax_run _sg_relax_job; then
      saved_job=$(declare -f _sg_relax_job); fj=$saved_job; tpat='( sleep "$_SG_LEFT";'
      MK=$X/ran-10c; rm -f "$MK"; _sg_vx_pass() { echo ran > "$MK"; return 0; }
      if [[ "$fj" == *"$tpat"* && "$fj" == *'& tp=${!:-};'* ]]; then
        pre=${fj%%"$tpat"*}; rest=${fj#*"$tpat"}; rest=${rest#*'& tp=${!:-};'}
        eval "${pre}true & wait \"\$!\"; tp=\${!:-};${rest}"; jcase V5-S10c-dead-timer-no-judgement 4 0 0.3 ''
        [[ ! -e "$MK" ]]; chk $? V5-S10d-no-judgement-with-dead-timer "judgement started: $([[ -e $MK ]] && echo yes || echo no) (want no)" "[judged]"
        eval "$saved_job"
      else
        for id in V5-S10c-dead-timer-no-judgement V5-S10d-no-judgement-with-dead-timer; do out SETUP "$id" "the timer start (( sleep \"\$_SG_LEFT\"; ... & tp=\${!:-};) was not found in _sg_relax_job"; done
      fi
    else miss V5-S10c-dead-timer-no-judgement V5-S10d-no-judgement-with-dead-timer; fi
  fi
  # the timer fails closed: a sleep that fails at once (missing, or one that rejects fractional seconds) makes the timer kill the group at once -> fallback
  if sel V5-S14-failing-sleep-kills-at-once; then
    FS=$X/failsleep; mkdir -p "$FS"; printf '#!/bin/sh\nexit 1\n' > "$FS/sleep"; chmod +x "$FS/sleep"
    _sg_vx_pass() { local i; for (( i = 0; i < 10000000; i++ )); do :; done; return 0; }
    PATH="$FS:$PATH" jcase V5-S14-failing-sleep-kills-at-once 4 0 0.3 ''
  fi
  # the group-leader self-check (R2 PP2-J): set -m works on every measured bash, so only a direct call outside a group leader reaches the refusal
  if sel V5-S15-job-refuses-outside-group-leader; then
    if need _sg_relax_job; then
      MK=$X/ran-15; rm -f "$MK"; _sg_vx_pass() { echo ran > "$MK"; return 0; }
      r=$( _SG_LEFT=0.5; _SG_MODE=whole; ( _sg_relax_job "cmd" ) >/dev/null 2>&1; echo $? )
      j=no; [[ -e "$MK" ]] && j=yes; t=''; [[ $r == 9 ]] || t+='[status] '; [[ $j == no ]] || t+='[judged]'
      [[ -z "$t" ]]; chk $? V5-S15-job-refuses-outside-group-leader "_sg_relax_job in a shell that leads no process group: status $r, judgement started: $j (want 9, no)" "$t"
    else miss V5-S15-job-refuses-outside-group-leader; fi
  fi
  # the relaxed block text reaches stderr byte for byte: the text and exactly one newline (R2 QA-M15)
  if sel V4-S19-block-text-bytes; then
    if need _sg_relax_run _sg_relax_job; then
      _sg_vx_pass() { printf 'BLOCK TEXT\n' >&2; return 2; }
      jrun; printf 'BLOCK TEXT\n' > "$X/s19"; h=ok s=ok t=''
      if [[ $JRC == 2 ]]; then cmp -s "$X/s19" "$JERR" || { h=bad; t+=' [bytes]'; }; le "$JW" 0.3 || { s=bad; t+=' [wall>hi]'; }
      elif [[ $JRC == 4 && ! -s "$JERR" ]]; then s=bad; t+=' [fallback]'
      else h=bad; t+=' [rc]'; fi
      timed V4-S19-block-text-bytes $h $s "rc=$JRC (want 2) stderr $(wc -c < "$JERR") bytes, last byte $(tail -c 1 "$JERR" | od -An -c | tr -d ' ') (want 11 bytes: BLOCK TEXT and one newline) wall=${JW}s (want 0..0.3)$t"
    else miss V4-S19-block-text-bytes; fi
  fi
  if sel V5-S12-no-leftovers && ! command -v ps >/dev/null 2>&1; then out SKIP V5-S12-no-leftovers "[platform] ps not found: the stub processes left behind cannot be counted"
  elif sel V5-S12-no-leftovers; then
    n=$(lv5); i=0; while (( n > 0 && i < 10 )); do sleep 0.1; n=$(lv5); i=$((i+1)); done   # at most 1 s of grace (R2 PP2-K)
    [[ $n == 0 ]]; chk $? V5-S12-no-leftovers "stub processes of this run (arguments ending in $U) still alive after the cases: $n (want 0)" "[leftover]"
  fi
  source "$H" </dev/null >/dev/null 2>&1; set +e; unset CLAUDE_PROJECT_DIR SECRET_GUARD_TIME_BUDGET_S; input=''   # the real functions back, the default budget

  # ---------------- P4 / P6: the rerun's own exits ----------------
  ckp() {   # id mode cmd [segment...] : a time checkpoint inside the rerun returns 3 and writes no text; the caller falls back to the baseline block (R2 PP2-E)
    local id=$1 m=$2 c=$3 r t=''; shift 3
    sel "$id" || return 0
    need _sg_vx_pass || { miss "$id"; return 0; }
    r=$( export SECRET_GUARD_TIME_BUDGET_S=0; _SG_RELAXED=1; command=$c; [[ $m == segment ]] && _SG_SEGS=("$@"); _sg_vx_pass "$c" "$m" >/dev/null 2>"$X/ck"; echo $? )
    [[ $r == 3 ]] || t+='[status] '; [[ -s "$X/ck" ]] && t+='[stderr]'
    [[ -z "$t" ]]; chk $? "$id" "budget 0 inside the rerun, $m mode: status $r, stderr $(wc -c < "$X/ck") bytes $([[ -s $X/ck ]] && kindf "$X/ck") (want 3 and no text)" "$t"
  }
  ckp V4-S16-rerun-collect-checkpoint whole 'a=1; b=2; : $a $b'
  ckp V4-S17-rerun-whole-checkpoint whole 'a=1; : $a'
  ckp V4-S18-rerun-segment-checkpoint segment 'a=1; : $a' 'a=1' ': $a'
  fbref() {   # id -> "<status> <kind>": what 59e333c's _sg_vx_pass gives at fbt's gate-closed call (the same copy and mode; it ignores the WSL mark), measured
              # in 3c on the five bash: the same on each. An id without an entry fails.
    case $1 in
      V6-S20-segment-fallback-text|V6-S21-whole-fallback-text) echo '2 oversize' ;;
      *) echo 'unrecorded -' ;;
    esac
  }
  fbt() {   # id mode cmd [segment...] : with the gate open a copy over _SGV_SMAX ends the baseline pass with 4 and keeps the baseline's reason; the fallback
            # text written from it equals the block the same hook writes for the same copy with the gate closed by WSL_DISTRO_NAME, byte for
            # byte (R2 PP2-I; v31 compares with the baseline hook's file)
    local id=$1 m=$2 c=$3 r rb kb ref t=''; shift 3
    sel "$id" || return 0
    need _sg_vx_pass _sg_emit_blocked || { miss "$id"; return 0; }
    [[ $BELOW == yes ]] || { nobelow "$id"; return 0; }
    r=$( _sg_relax_ok() { return 0; }; _SG_RELAXED=; command=$c; [[ $m == segment ]] && _SG_SEGS=("$@")
         _sg_vx_pass "$c" "$m" >/dev/null 2>"$X/fb-pass"; s=$?; : > "$X/fb-hook"
         [[ $s == 4 ]] && _sg_emit_blocked "${_SG_OV_PAT:-}" "$c" "${_SG_OV_MODE:-}" oversize 2>"$X/fb-hook" >/dev/null
         echo "$s ${_SG_OV_MODE:-none} $(wc -c < "$X/fb-pass")" )
    cat > "$X/basefb.sh" <<'EOF'
B=$1; OUT=$2; m=$3; c=$4; shift 4
export WSL_DISTRO_NAME=Ubuntu   # the gate's closing switch, set in the shell that sources the hook: it writes its gate-closed block
source "$B" </dev/null >/dev/null 2>&1; set +e; input=''; _SG_P0=${EPOCHREALTIME:-}   # an anchor: only the WSL mark closes the gate
awk '/^_sg_redact_echo\(\) \{/,/^\}$/' "$B" > "$OUT.re"; source "$OUT.re"
command=$c; [[ $m == segment ]] && _SG_SEGS=("$@")
_sg_vx_pass "$c" "$m" >/dev/null 2>"$OUT"; echo $?
EOF
    rb=$("$BASH" "$X/basefb.sh" "$H" "$X/fb-base" "$m" "$c" "$@"); kb=$(kindf "$X/fb-base"); ref=$(fbref "$id")
    if [[ "$rb $kb" != "$ref" ]]; then   # [reference]: first the gate-closed call against 59e333c's known outcome for this copy (the time text: timing)
      if [[ $kb == time ]]; then timed "$id" ok bad "gate closed by WSL_DISTRO_NAME: status $rb $kb, reference (59e333c) $ref [time-text]"
      else out FAIL "$id" "gate closed by WSL_DISTRO_NAME: status $rb $kb, reference (59e333c, the same copy and mode) $ref [reference]"; fi
      return 0
    fi
    [[ $r == "4 $m 0" ]] || t+='[status] '; cmp -s "$X/fb-hook" "$X/fb-base" || t+='[bytes]'
    [[ -z "$t" ]]; chk $? "$id" "gate open, a $m copy over 8192: status/mode/text-bytes [$r] (want [4 $m 0]); fallback text $(wc -c < "$X/fb-hook") bytes vs the same hook's block with the gate closed by WSL_DISTRO_NAME (status $rb $kb) $(wc -c < "$X/fb-base") bytes: $(cmp -s "$X/fb-hook" "$X/fb-base" && echo IDENTICAL || echo "DIFFERENT, first line [$(head -1 "$X/fb-hook" | cut -c1-120)]")" "$t"
  }
  fbt V6-S20-segment-fallback-text segment "$cseg" "x=$x4" ": \$x \$x$fill"
  fbt V6-S21-whole-fallback-text whole "$cwh"

  # ---------------- P8: growth, measured against the input ----------------
  G=${_SGV_GMAX:-8192}
  grow() {   # id cmd want_status
    local id=$1 c=$2 want=$3 r
    sel "$id" || return 0
    need _sg_vx_collect _sg_vx_apply || { miss "$id"; return 0; }
    r=$( _SG_RELAXED=1; _sg_vx_collect "$c" >/dev/null 2>&1; _sg_vx_apply "$c" >/dev/null 2>&1; echo "$? $(( ${#_SG_SUB} - ${#c} ))" )
    [[ ${r%% *} == "$want" ]]; chk $? "$id" "apply status ${r%% *} growth ${r##* } (want status $want; the growth limit _SGV_GMAX is $G)" "[status]"
  }
  # growth = 2 x (4000 - len(reference)) + (len(b) - len(reference)): plain $a is 2 characters, braced ${a} is 4. The edge follows _SGV_GMAX (perturbation round)
  a=$x4; bp=$(printf '%*s' $(( G - 7994 )) '' | tr ' ' b); bb=$(printf '%*s' $(( G - 7988 )) '' | tr ' ' b)
  v2k=$(printf '%*s' 2000 '' | tr ' ' v); pad=$(printf '%*s' 6500 '' | tr ' ' y)
  grow V8-D1-late-references-plain "v=$v2k; : $pad \$v \$v" 0
  grow V8-D1-late-references-braced "v=$v2k; : $pad \${v} \${v}" 0
  grow V8-D2-growth-8192-plain "a=$a; b=$bp; : \$a \$a \$b" 0
  grow V8-D3-growth-8193-plain "a=$a; b=${bp}b; : \$a \$a \$b" 2
  grow V8-D2-growth-8192-braced "a=$a; b=$bb; : \${a} \${a} \${b}" 0
  grow V8-D3-growth-8193-braced "a=$a; b=${bb}b; : \${a} \${a} \${b}" 2
  gtext() {   # id mode cmd reason [segment...] : inside the rerun a growth over _SGV_GMAX blocks (status 2) with the size text, its "Limit hit:" line
              # verbatim (R2 PP2-G; Rule #6 block B: the two growth reason strings)
    local id=$1 m=$2 c=$3 why=$4 r l1 w1 t=''; shift 4
    sel "$id" || return 0
    need _sg_vx_pass || { miss "$id"; return 0; }
    [[ $BELOW == yes ]] || { nobelow "$id"; return 0; }
    r=$( _SG_RELAXED=1; command=$c; [[ $m == segment ]] && _SG_SEGS=("$@"); _sg_vx_pass "$c" "$m" >/dev/null 2>"$X/gt"; echo $? )
    l1=$(head -1 "$X/gt"); w1="[secret-guard] BLOCKED: command too large to scan for secrets. Limit hit: $why"
    [[ $r == 2 ]] || t+='[status] '; [[ "$l1" == "$w1" ]] || t+='[text]'
    [[ -z "$t" ]]; chk $? "$id" "status $r (want 2), first line [$(printf '%s' "$l1" | cut -c1-150)] (want [$w1])" "$t"
  }
  gtext V8-D4-growth-text-whole whole "(true); x=$x4; F=$cfg; cat \$F \$x \$x \$x \$x" "the command grows by more than $G characters after variable expansion"
  gtext V8-D5-growth-text-segment segment "x=$x4; F=$cfg; cat \$F \$x \$x \$x \$x" "a command segment grows by more than $G characters after variable expansion" \
    "x=$x4" "F=$cfg" "cat \$F \$x \$x \$x \$x"

  # ---------------- P9: no count bound inside the rerun (baseline bounds unchanged outside it) ----------------
  if need _sg_vx_collect _sg_vx_apply; then
    c20=$(for i in $(seq -w 1 20); do printf 'a%s=1; ' "$i"; done)": \$a20"
    r=$( _SG_RELAXED=1; _sg_vx_collect "$c20"; echo ${#_SGV_N[@]} ); [[ $r == 20 ]]; chk $? V9-C1-assignments-rerun "collected $r of 20 inside the rerun (want 20)" "[value]"
    r=$( _SG_RELAXED=; _sg_vx_collect "$c20"; echo ${#_SGV_N[@]} ); [[ $r == 16 ]]; chk $? V9-C1b-assignments-baseline "collected $r of 20 in the baseline pass (want 16, unchanged)" "[value]"
    c12="v=Q; : $(for i in $(seq 1 12); do printf '$v '; done)"; cb12="v=Q; : $(for i in $(seq 1 12); do printf '${v} '; done)"
    for k in c12 cb12; do
      r=$( _SG_RELAXED=1; _sg_vx_collect "${!k}"; _sg_vx_apply "${!k}" >/dev/null; [[ "$_SG_SUB" == *'$v'* || "$_SG_SUB" == *'${v}'* ]] && echo left || echo none )
      [[ $r == none ]]; chk $? "V9-C2-references-rerun-$k" "references left unexpanded inside the rerun: $r (want none)" "[value]"
      r=$( _SG_RELAXED=; _sg_vx_collect "${!k}"; _sg_vx_apply "${!k}" >/dev/null; [[ "$_SG_SUB" == *'$v'* || "$_SG_SUB" == *'${v}'* ]] && echo left || echo none )
      [[ $r == left ]]; chk $? "V9-C2b-references-baseline-$k" "references left unexpanded in the baseline pass: $r (want left, unchanged)" "[value]"
    done
    # R2 PP2-H: the third count bound (for statements) and the value limit, both reachable only because the rerun collects everything
    cf12=$(for i in $(seq 1 12); do printf 'for a%s in w%s; do :; done; ' "$i" "$i"; done)": \$a12"
    r=$( _SG_RELAXED=1; _sg_vx_collect "$cf12"; echo ${#_SGV_N[@]} ); [[ $r == 12 ]]; chk $? V9-C3-for-statements-rerun "collected $r of 12 for statements inside the rerun (want 12)" "[value]"
    r=$( _SG_RELAXED=; _sg_vx_collect "$cf12"; echo ${#_SGV_N[@]} ); [[ $r == 8 ]]; chk $? V9-C3b-for-statements-baseline "collected $r of 12 for statements in the baseline pass (want 8, unchanged)" "[value]"
  else miss V9-C1-assignments-rerun V9-C1b-assignments-baseline V9-C2-references-rerun-c12 V9-C2b-references-baseline-c12 V9-C2-references-rerun-cb12 \
            V9-C2b-references-baseline-cb12 V9-C3-for-statements-rerun V9-C3b-for-statements-baseline; fi
  if sel V9-C4-value-limit-in-rerun; then
    if ! need _sg_vx_pass; then miss V9-C4-value-limit-in-rerun
    elif [[ $BELOW != yes ]]; then nobelow V9-C4-value-limit-in-rerun
    else
      v5=$(printf '%*s' 5000 '' | tr ' ' v)
      c4="x=$x4; $(for i in $(seq -w 2 16); do printf 'b%s=1; ' "$i"; done)big=$v5; F=$cfg; : \$x \$x; cat \$F"
      r=$( _SG_RELAXED=1; command=$c4; _sg_vx_pass "$c4" whole >/dev/null 2>"$X/c4"; echo "$? $(kindf "$X/c4")" )
      [[ $r == "2 vmax" ]]; chk $? V9-C4-value-limit-in-rerun "the 17th assignment holds a value over 4096 (only the rerun collects it): status/text [$r] (want [2 vmax])" "$(tags3 "$r" "2 vmax")"
    fi
  fi

  # ---------------- P10 / P7: rows only keeps the W12 neutralisation; _sg_vx_big_judge routes by the copy's longest line; ruling C ----------------
  N_IDS="V10-N1-environ-rows-only V10-N2-read-rows-only V10-N3-environ-big-judge V10-N4-read-big-judge V7-N5-read-big-judge-short-lines V10-N6-filtered-long-line-rows-only
    V7-N7-big-judge-filtered-long-line V7-N8-whole-branch-returns-big-judge V7-N9-segment-routes-to-big-judge V7-N10-blank-padded-long-line V7-N11-lmax-edge-normal
    V7-N12-lmax-edge-rows-only V7-N13-unmeasured-length-rows-only
    V14-N1-nocredit-never-runs-credit V14-N2-longline-pattern-is-a-rule V14-G1-triggers-return-4-with-the-baseline-reason V14-G2-growth-limit-follows-gmax V14-F1-status-4-falls-back-to-the-baseline-block"
  if [[ $BELOW == yes ]]; then
    z=$(printf '%*s' 9000 '' | tr ' ' z)
    env1="python3 -c 'import os; print(os.environ.get(\"HOME\"))' $z"; rd="cat $cfg $z"; rdl="cat $cfg"$'\n'"$(for i in $(seq 1 40); do printf 'echo %0250d\n' 0; done)"
    one() {   # id fn args... -- want_rc want_kind
      local id=$1; shift; local want=${@: -2:1} wk=${@: -1} e rc k; set -- "${@:1:$#-3}"
      sel "$id" || return 0
      need "$1" || { miss "$id"; return 0; }
      e=$(mktemp -p "$X"); command="$2"; "$@" 2>"$e" >/dev/null; rc=$?; k=$(kindf "$e")
      [[ $rc == "$want" && $k == "$wk" ]]; chk $? "$id" "rc=$rc text=$k (want rc=$want text=$wk)" "$(tags3 "$rc $k" "$want $wk")"
    }
    one V10-N1-environ-rows-only _sg_judge_one "$env1" whole nocredit -- 0 none
    one V10-N2-read-rows-only _sg_judge_one "$rd" whole nocredit -- 2 longline
    one V10-N3-environ-big-judge _sg_vx_big_judge "$env1" whole -- 0 none
    one V10-N4-read-big-judge _sg_vx_big_judge "$rd" whole -- 2 longline
    one V7-N5-read-big-judge-short-lines _sg_vx_big_judge "$rdl" whole -- 2 finding
    # ruling C (R2 PP2-F): a line over _SGV_LMAX that matches a row is blocked even with a value-redacting filter -- credit is not evaluated at all
    one V10-N6-filtered-long-line-rows-only _sg_judge_one "cat $cfg | wc -c $z" whole nocredit -- 2 longline
    one V7-N7-big-judge-filtered-long-line _sg_vx_big_judge "cat $cfg | wc -c $z" whole -- 2 longline
    pad=$(printf '%*s' 4600 '')
    one V7-N10-blank-padded-long-line _sg_vx_big_judge "${pad}cat $cfg | wc -c$pad" whole -- 2 longline   # the blanks count: read with IFS= (R2 QA-M28)
    L=${_SGV_LMAX:-8192}; l1="cat $cfg "; n11="$l1$(printf '%*s' $(( L - ${#l1} )) '' | tr ' ' z)"   # a line of exactly _SGV_LMAX characters
    one V7-N11-lmax-edge-normal _sg_vx_big_judge "$n11" whole -- 2 finding
    one V7-N12-lmax-edge-rows-only _sg_vx_big_judge "${n11}z" whole -- 2 longline
    if sel V7-N8-whole-branch-returns-big-judge; then
      if need _sg_vx_pass; then
        c8="(true); F=$cfg; x=$x4; : \$x \$x; cat \$F; echo done >/dev/null"
        r=$( _SG_RELAXED=1; command=$c8; _sg_vx_pass "$c8" whole >/dev/null 2>"$X/n8"; echo "$? $(kindf "$X/n8") $(grep -c '^\[secret-guard\] BLOCKED' "$X/n8")" )
        [[ $r == "2 longline 1" ]]; chk $? V7-N8-whole-branch-returns-big-judge "rerun, whole copy over 8192 with a line over $L, a read and a filter elsewhere: status/text/block-headers [$r] (want [2 longline 1])" "$(tags3 "$r" "2 longline 1")"
      else miss V7-N8-whole-branch-returns-big-judge; fi
    fi
    if sel V7-N9-segment-routes-to-big-judge; then
      if need _sg_vx_pass; then
        c9="F=$cfg; x=$x4; cat \$F | wc -c \$x \$x$fill100"
        r=$( _SG_RELAXED=1; command=$c9; _SG_SEGS=("F=$cfg" "x=$x4" "cat \$F | wc -c \$x \$x$fill100"); _sg_vx_pass "$c9" segment >/dev/null 2>"$X/n9"; echo "$? $(kindf "$X/n9")" )
        [[ $r == "2 longline" ]]; chk $? V7-N9-segment-routes-to-big-judge "rerun, segment copy over 8192 with a line over $L, a read and a filter in the segment: status/text [$r] (want [2 longline])" "$(tags3 "$r" "2 longline")"
      else miss V7-N9-segment-routes-to-big-judge; fi
    fi
    if sel V7-N13-unmeasured-length-rows-only; then
      if need _sg_vx_big_judge; then
        # the line-length loop runs zero times (read fails at once): the length is unknown, so rows only -- never the cheaper-to-pass credit path (R2 PP2-F)
        r=$( read() { if [[ $# == 2 && $1 == -r && $2 == line ]]; then return 1; fi; builtin read "$@"; }; command="cat $cfg | wc -c"   # (IFS= is empty here: no "$*")
             _sg_vx_big_judge "cat $cfg | wc -c" whole >/dev/null 2>"$X/n13"; echo "$? $(kindf "$X/n13")" )
        [[ $r == "2 longline" ]]; chk $? V7-N13-unmeasured-length-rows-only "a filtered read whose line length cannot be measured: status/text [$r] (want [2 longline])" "$(tags3 "$r" "2 longline")"
      else miss V7-N13-unmeasured-length-rows-only; fi
    fi
    # ---- V14: cases added by TASK-003 for the independent mutants no case caught for its own reason (Q-7 Q-15 Q-22 Q-29 Q-31); no load dependence ----
    if sel V14-N1-nocredit-never-runs-credit; then   # Q-15: a matching row on a line over _SGV_LMAX blocks before the O(n^2) credit is ever computed
      if need _sg_compute_credit; then
        r=$( _sg_compute_credit() { : > "$X/n14a.mark"; return 0; }; command="$rd"; _sg_judge_one "$rd" whole nocredit >/dev/null 2>"$X/n14a"; echo "$? $(kindf "$X/n14a") $([[ -e "$X/n14a.mark" ]] && echo credit-run || echo credit-skipped)" )
        [[ $r == "2 longline credit-skipped" ]]; chk $? V14-N1-nocredit-never-runs-credit "nocredit on a matching line over ${_SGV_LMAX:-8192}: status/text/credit [$r] (want [2 longline credit-skipped]); the credit must not be computed before the longline block" "[judged]"
      else miss V14-N1-nocredit-never-runs-credit; fi
    fi
    if sel V14-N2-longline-pattern-is-a-rule; then   # Q-22: the longline text names the matched RULE, not the (long) copy
      command="$rd"; _sg_judge_one "$rd" whole nocredit >/dev/null 2>"$X/n14b"; n14p=$(sed -n 's/^.*Matched pattern: //p' "$X/n14b" | head -n 1); n14n=$(wc -c < "$X/n14b"); n14m=no
      for n14r in "${risky_patterns[@]}"; do [[ "$n14p" == "$n14r" ]] && { n14m=yes; break; }; done
      [[ $n14m == yes && $n14n -lt 3000 ]]; chk $? V14-N2-longline-pattern-is-a-rule "the longline text: the matched pattern is one of the rules: $n14m; text $n14n bytes (want yes, under 3000: the copy must not stand in for the pattern)" "[text]"
    fi
    if sel V14-G1-triggers-return-4-with-the-baseline-reason; then   # Q-7 (and the copy-paste of the two reason strings): both trigger points hand over with status 4 and keep their own baseline reason
      if need _sg_vx_pass; then
        g1c="v=$x4; : \$v \$v \$v"; g1S=${_SGV_SMAX:-8192}
        g1w=$( _sg_relax_ok() { return 0; }; command=$g1c; _sg_vx_pass "$g1c" whole >/dev/null 2>&1; echo "$?|$_SG_OV_PAT|$_SG_OV_MODE" )
        g1s=$( _sg_relax_ok() { return 0; }; command=$g1c; _SG_SEGS=("v=$x4" ": \$v \$v \$v"); _sg_vx_pass "$g1c" segment >/dev/null 2>&1; echo "$?|$_SG_OV_PAT|$_SG_OV_MODE" )
        g1wa="4|the command is longer than $g1S characters after variable expansion|whole"; g1sa="4|a command segment is longer than $g1S characters after variable expansion|segment"
        t=''; [[ ${g1w%%|*} == 4 && ${g1s%%|*} == 4 ]] || t+='[status] '; [[ "$g1w" == "$g1wa" && "$g1s" == "$g1sa" ]] || t+='[text]'
        [[ -z "$t" ]]; chk $? V14-G1-triggers-return-4-with-the-baseline-reason "gate stubbed open, baseline pass, a copy over $g1S: whole [${g1w:0:140}] (want [$g1wa]); segment [${g1s:0:140}] (want [$g1sa])" "$t"
      else miss V14-G1-triggers-return-4-with-the-baseline-reason; fi
    fi
    if sel V14-G2-growth-limit-follows-gmax; then   # Q-31: the growth limit of the rerun is _SGV_GMAX over the input, not _SGV_SMAX (both are 8192 today: perturb them apart)
      if need _sg_vx_collect _sg_vx_apply; then
        g2c="v=$(printf '%*s' 300 '' | tr ' ' w); : \$v"
        g2a=$( _SG_RELAXED=1; _SGV_GMAX=100; _sg_vx_collect "$g2c" >/dev/null 2>&1; _sg_vx_apply "$g2c" >/dev/null 2>&1; echo $? )
        g2b=$( _SG_RELAXED=1; _SGV_GMAX=400; _SGV_SMAX=100; _sg_vx_collect "$g2c" >/dev/null 2>&1; _sg_vx_apply "$g2c" >/dev/null 2>&1; echo $? )
        [[ "$g2a $g2b" == "2 0" ]]; chk $? V14-G2-growth-limit-follows-gmax "relaxed _sg_vx_apply, growth 298: _SGV_GMAX 100 -> status $g2a (want 2); _SGV_GMAX 400 with _SGV_SMAX 100 -> status $g2b (want 0); the limit is the growth over the input" "[status]"
      else miss V14-G2-growth-limit-follows-gmax; fi
    fi
    if sel V14-F1-status-4-falls-back-to-the-baseline-block; then   # Q-29: _sg_per_segment_eval turns status 4 of a failed rerun into the baseline block (status 2 and its reason), whatever the host load
      awk '/^_sg_per_segment_eval\(\) \{/,/^\}$/' "$H" > "$X/pse.sh"
      if [[ ! -s "$X/pse.sh" ]]; then out SETUP V14-F1-status-4-falls-back-to-the-baseline-block "_sg_per_segment_eval not found by anchor"
      elif ! need _sg_emit_blocked _sg_time_budget; then miss V14-F1-status-4-falls-back-to-the-baseline-block
      else
        f1p="the command is longer than ${_SGV_SMAX:-8192} characters after variable expansion"
        f1r=$( source "$X/pse.sh"; _sg_core_eval() { _SG_MODE=whole; return 0; }; _sg_vx_pass() { _SG_OV_PAT="$f1p"; _SG_OV_MODE=whole; return 4; }; _sg_relax_run() { return 4; }; command="$rd"; _sg_per_segment_eval "$rd" >/dev/null 2>"$X/f1"; echo $? )
        f1l=$(head -n 1 "$X/f1"); f1w="[secret-guard] BLOCKED: command too large to scan for secrets. Limit hit: $f1p"
        t=''; [[ $f1r == 2 ]] || t+='[status] '; [[ "$f1l" == "$f1w" ]] || t+='[text]'
        [[ -z "$t" ]]; chk $? V14-F1-status-4-falls-back-to-the-baseline-block "_sg_per_segment_eval with a rerun that falls back (status 4): status $f1r (want 2), first line [${f1l:0:140}] (want [$f1w])" "$t"
      fi
    fi
  else nobelow $N_IDS; fi
else
  # MODE norelax: the relaxation is not expected on this bash. Each of its cases is reported once, as SKIP [platform], so the list of ids is the same
  # on every platform (the suite's V0-H2)
  for id in $RELAX_IDS; do
    sel "$id" && out SKIP "$id" "[platform] the relaxation is not expected on this bash (${BASH_VERSINFO[5]} ${BASH_VERSINFO[0]}.${BASH_VERSINFO[1]}, kernel ${OSR:-<none>}${WSLM:+, WSLInterop}): MODE norelax"
  done
fi
echo "END sc-direct"

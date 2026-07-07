#!/usr/bin/env bash
# resweep_zero_regression.sh — TASK-013 (SC-1 最高优先): 零回归 re-sweep.
#
# runtime-probe-archive-gate-integration (#95 follow-up A) 声称: 对全部无
# `runtime_probe:` frontmatter 声明的 spec (== 现状 118 归档 + 6 活跃 changes
# 全部, 无一例外), gate_result() 的静态判定路径逐字节不变 (SC-1)。本脚本是该
# 声称的可执行证据: 在**同一 worktree 同一树内容**上, 对每个 spec_dir 分别用
# v1.53.0 基线代码 (加 runtime_probe 折入之前) 与本仓当前代码各跑一次
# `--gate`, 结构化比较两份 JSON — 控制变量只有代码版本, 消除
# `classify_symbol_liveness` 全 repo grep 面随语料/时间漂移的噪音 (对比
# "先跑基线快照、隔天再跑新代码" 这种非同源比较方式)。
#
# 可复现前提 (BASELINE_SCRIPTS_ROOT 默认值):
#   默认基线 = 本机 Claude Code 插件市场缓存的 v1.53.0 快照
#   (~/.claude/plugins/cache/10CG-aria-plugin/aria/1.53.0/skills/state-scanner/scripts)。
#   这份缓存由 marketplace 安装机制维护, 不属于本仓版本控制; 在没有该缓存目录
#   的机器上 (或 v1.53.0 已被更新的市场缓存替换) 必须显式传入
#   BASELINE_SCRIPTS_ROOT 指向一份 v1.53.0 tag/commit 的 state-scanner/scripts
#   checkout, 否则脚本 preflight 会直接报错退出 (不会静默跳过基线对比)。
#
# 用法:
#   bash resweep_zero_regression.sh              # 全语料 sweep (生产用法, SC-1)
#   bash resweep_zero_regression.sh --selftest   # 负控自证: 证明 diff 检测非
#                                                 # vacuous (不触碰真语料, 纯
#                                                 # $TMP 合成 fixture)
#
# 环境变量覆盖:
#   BASELINE_SCRIPTS_ROOT   基线 scripts/ 根目录 (默认见上)
#   CORPUS_ROOT             语料仓根 (含 openspec/archive|changes/); 默认从本
#                           文件位置向上walk-up 找到第一个含 openspec/archive
#                           的目录 (与 test_archive_gate_integration.sh 同一
#                           ROOT 探测手法)。--selftest 模式内部覆盖此变量指向
#                           合成语料, 不影响默认生产路径。
#
# 退出码: 0 = 全部 diff=0 (或 --selftest 通过); 1 = 发现 ≥1 diff (或
# --selftest 断言失败); 2 = preflight 失败 (基线/新代码/语料路径缺失, 环境
# 问题, 非回归发现)。
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NEW_LIB="$HERE/../scripts/lib/spec_complete.py"

DEFAULT_BASELINE_ROOT="/home/dev/.claude/plugins/cache/10CG-aria-plugin/aria/1.53.0/skills/state-scanner/scripts"
BASELINE_SCRIPTS_ROOT="${BASELINE_SCRIPTS_ROOT:-$DEFAULT_BASELINE_ROOT}"
BASELINE_LIB="$BASELINE_SCRIPTS_ROOT/lib/spec_complete.py"

_discover_root() {
  local d="$1"
  while [ "$d" != "/" ] && [ ! -d "$d/openspec/archive" ]; do d="$(dirname "$d")"; done
  printf '%s' "$d"
}
CORPUS_ROOT="${CORPUS_ROOT:-$(_discover_root "$HERE")}"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# ---------------------------------------------------------------------------
# gate_one <lib_path> <spec_dir> <out_file> — 跑一次 --gate, JSON 写到
# out_file, 把 exit code 存入 GATE_EXIT。-B 避免往 lib_path 所在目录 (基线场景
# 下是 plugin 市场缓存, 非本仓拥有) 写 __pycache__ 副作用。stderr 丢弃 (两份
# 代码在 --gate 模式下的 fail-toward-warn 设计保证不会因输入问题而在 stderr
# 抛出未捕获 traceback 且仍要求 stdout 是合法 JSON; 参见 spec_complete.py
# _main() usage/crash 两条 fallback 分支)。
# ---------------------------------------------------------------------------
gate_one() {
  local lib="$1" dir="$2" out="$3"
  python3 -B "$lib" --gate "$dir" >"$out" 2>/dev/null
  GATE_EXIT=$?
}

# ---------------------------------------------------------------------------
# compare_json <baseline_file> <new_file> — 结构化 (非文本行) JSON 相等性判定
# (json.loads 后 dict == dict, 免疫 key 顺序/空白差异造成的假阳); 不等时把
# sort_keys 规范化后的 unified diff 打到 stdout 供人工归因。exit 0=same /
# 1=diff / 2=某侧 JSON 解析失败 (本身就是要报告的异常情况, 视同 diff 处理,
# 见调用侧)。
# ---------------------------------------------------------------------------
compare_json() {
  python3 -B - "$1" "$2" <<'PY'
import difflib
import json
import sys

bp, np = sys.argv[1], sys.argv[2]


def load(path, label):
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    except OSError as e:
        print(f"{label}_UNREADABLE: {e}")
        return None
    if not raw.strip():
        print(f"{label}_EMPTY_OUTPUT")
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"{label}_INVALID_JSON: {e}: {raw[:200]!r}")
        return None


b = load(bp, "BASELINE")
n = load(np, "NEW")
if b is None or n is None:
    sys.exit(2)
if b == n:
    sys.exit(0)
bl = json.dumps(b, indent=2, sort_keys=True, ensure_ascii=False).splitlines()
nl = json.dumps(n, indent=2, sort_keys=True, ensure_ascii=False).splitlines()
for line in difflib.unified_diff(bl, nl, fromfile="baseline", tofile="new", lineterm=""):
    print(line)
sys.exit(1)
PY
}

# ---------------------------------------------------------------------------
# sweep <corpus_root> — 对 corpus_root/openspec/{archive,changes}/*/ 逐个跑
# gate_one(baseline) + gate_one(new) + compare_json, 打印 PASS/DIFF 行 +
# 尾部汇总。副作用: 设 SWEEP_N / SWEEP_DIFFS / DIFF_SPECS (供调用方 —— 生产
# sweep 或 --selftest —— 断言)。
# ---------------------------------------------------------------------------
sweep() {
  local corpus_root="$1"
  local n=0 diffs=0
  local slowest_spec="" slowest_ms=0
  local t_start t_end
  t_start=$(date +%s)
  DIFF_SPECS=()

  for d in "$corpus_root"/openspec/archive/*/ "$corpus_root"/openspec/changes/*/; do
    [ -d "$d" ] || continue
    n=$((n + 1))
    local spec_id kind t0 t1 dur_ms bexit nexit diff_out rc
    spec_id="$(basename "$d")"
    case "$d" in
      */openspec/archive/*) kind=archive ;;
      *) kind=changes ;;
    esac

    t0=$(date +%s%N)
    gate_one "$BASELINE_LIB" "$d" "$TMP/baseline.json"; bexit=$GATE_EXIT
    gate_one "$NEW_LIB" "$d" "$TMP/new.json"; nexit=$GATE_EXIT
    t1=$(date +%s%N)
    dur_ms=$(((t1 - t0) / 1000000))
    if [ "$dur_ms" -gt "$slowest_ms" ]; then
      slowest_ms=$dur_ms
      slowest_spec="$spec_id"
    fi

    diff_out="$(compare_json "$TMP/baseline.json" "$TMP/new.json")"; rc=$?

    if [ "$rc" -eq 0 ] && [ "$bexit" = "$nexit" ]; then
      printf 'PASS  %-8s %-70s %5dms\n' "$kind" "$spec_id" "$dur_ms"
    else
      diffs=$((diffs + 1))
      DIFF_SPECS+=("$spec_id")
      printf 'DIFF  %-8s %-70s %5dms  baseline_exit=%s new_exit=%s\n' "$kind" "$spec_id" "$dur_ms" "$bexit" "$nexit"
      if [ -n "$diff_out" ]; then
        printf '%s\n' "$diff_out" | sed 's/^/      | /'
      fi
      if [ "$bexit" != "$nexit" ] && [ "$rc" -eq 0 ]; then
        echo "      | NOTE: JSON 内容相同但 exit code 不同 (baseline=$bexit new=$nexit) — 不应发生 (exit 是 verdict 的纯函数), 请核查 _main() 分流逻辑"
      fi
    fi
  done

  t_end=$(date +%s)
  echo
  echo "== 汇总: ${n} specs swept, ${diffs} diff, wall $((t_end - t_start))s, slowest=${slowest_spec} (${slowest_ms}ms) =="
  SWEEP_N=$n
  SWEEP_DIFFS=$diffs
}

# ---------------------------------------------------------------------------
# run_selftest — 负控自证 (anti-false-green, DEC-002/SC-8 传统): 证明上面的
# diff 检测机制不是 vacuous "永远 PASS"。构造一个孤立合成语料 (纯 $TMP, 从不
# 触碰真实 openspec/ 树):
#   ctrl-nodecl   — 无 runtime_probe 声明, 期望 baseline/new 输出一致 → PASS
#                   (证明正常路径不会被 selftest 自身的构造方式误伤为假 DIFF)
#   divergent-decl — 官方 §What 1 示例 runtime_probe frontmatter (无对应
#                   telemetry 分区) → 新代码折入 "分区缺失" warn 并新增
#                   gate_result.runtime_probe 键 + warnings[]/unverified_claims[]
#                   条目; 基线代码完全不认识这个 frontmatter 键 (v1.53.0 无
#                   此 feature) 因而不可能产出同一组键 → 结构性 diff 由构造
#                   保证, 不依赖 probe 语义细节 (skipped/warn 等) 是否精确 →
#                   期望 DIFF
# 断言: 恰好 2 spec / 恰好 1 diff / diff 命中的是 divergent-decl 非 ctrl-nodecl。
# 任一断言失败 = selftest FAIL = diff 检测机制本身不可信, 不能作为 SC-1 证据。
# ---------------------------------------------------------------------------
run_selftest() {
  echo "== 负控自证 (--selftest): 证明 diff 检测机制非 vacuous =="
  echo

  local fake="$TMP/selftest-corpus"
  mkdir -p "$fake/openspec/archive/ctrl-nodecl" "$fake/openspec/changes/divergent-decl"

  printf '# Proposal: ctrl-nodecl\n> **Status**: Approved\n## Success Criteria\n- [ ] x\n' \
    >"$fake/openspec/archive/ctrl-nodecl/proposal.md"
  printf '# Tasks\n- [x] 1.1 done\n' >"$fake/openspec/archive/ctrl-nodecl/tasks.md"

  cat >"$fake/openspec/changes/divergent-decl/proposal.md" <<'EOF'
---
runtime_probe:
  partition: .aria/coordination-telemetry.jsonl
  symbol: run_gate
---
# Proposal: divergent-decl
> **Status**: Approved
## Success Criteria
- [ ] x
EOF
  printf '# Tasks\n- [x] 1.1 done\n' >"$fake/openspec/changes/divergent-decl/tasks.md"

  sweep "$fake"
  echo

  local ok=1
  if [ "$SWEEP_N" -ne 2 ]; then
    echo "SELFTEST FAIL: expected 2 specs swept, got $SWEEP_N"
    ok=0
  fi
  if [ "$SWEEP_DIFFS" -ne 1 ]; then
    echo "SELFTEST FAIL: expected exactly 1 diff, got $SWEEP_DIFFS"
    ok=0
  fi
  local found_divergent=0 found_ctrl_as_diff=0
  local s
  for s in "${DIFF_SPECS[@]:-}"; do
    [ "$s" = "divergent-decl" ] && found_divergent=1
    [ "$s" = "ctrl-nodecl" ] && found_ctrl_as_diff=1
  done
  if [ "$found_divergent" -ne 1 ]; then
    echo "SELFTEST FAIL: divergent-decl (engineered divergence) was NOT flagged as diff — diff 检测机制是 vacuous 的"
    ok=0
  fi
  if [ "$found_ctrl_as_diff" -eq 1 ]; then
    echo "SELFTEST FAIL: ctrl-nodecl (no-declaration control) was flagged as diff — 假阳性, selftest 构造本身有问题"
    ok=0
  fi

  if [ "$ok" -eq 1 ]; then
    echo "SELFTEST PASS — diff 检测机制非 vacuous (divergent-decl 真被抓到 1 例 diff, ctrl-nodecl 保持 PASS)"
    return 0
  fi
  return 1
}

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
if [ ! -f "$NEW_LIB" ]; then
  echo "FATAL: 新代码 lib 未找到: $NEW_LIB" >&2
  exit 2
fi
if [ ! -f "$BASELINE_LIB" ]; then
  echo "FATAL: 基线代码 lib 未找到: $BASELINE_LIB" >&2
  echo "  提示: 设置 BASELINE_SCRIPTS_ROOT 指向一份 v1.53.0 state-scanner/scripts checkout" >&2
  exit 2
fi

if [ "${1:-}" = "--selftest" ]; then
  run_selftest
  exit $?
fi

if [ ! -d "$CORPUS_ROOT/openspec/archive" ]; then
  echo "FATAL: 语料仓根未找到 openspec/archive: $CORPUS_ROOT" >&2
  echo "  提示: 设置 CORPUS_ROOT 指向含 openspec/archive 与 openspec/changes 的仓根" >&2
  exit 2
fi

echo "基线代码: $BASELINE_LIB"
echo "新代码:   $NEW_LIB"
echo "语料根:   $CORPUS_ROOT"
echo

sweep "$CORPUS_ROOT"

if [ "$SWEEP_DIFFS" -eq 0 ]; then
  exit 0
fi
echo
echo "DIFF specs: ${DIFF_SPECS[*]}"
exit 1

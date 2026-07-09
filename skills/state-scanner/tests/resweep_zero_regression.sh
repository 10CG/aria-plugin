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
# required-corpus 守卫 (TASK-017, SC-1 真语料显式确认, proposal.md §What
# 4(iii)): 生产 sweep (非 --selftest) 在全语料汇总之后, 额外对 coordination
# 归档 spec (2026-07-05-interactive-session-dedup-coordination) 显式核验三
# 件事 —— (a) 它确实出现在被扫语料中 (防 CORPUS_ROOT 发现静默漂移导致漏扫
# 却仍报"全绿"); (b) 其 proposal.md frontmatter 经生产同一套解析器
# (lib/frontmatter_block.py) 确认无 runtime_probe 声明 (owner 决策
# 2026-07-05: 归档纯净, 不回改归档, 也防未来误加声明破坏此假设); (c) 它的
# diff 结果 = PASS。三项皆通过才算"零动作路径对这一个具体 spec 确实验证
# 过", 而不只是隐含在 124-corpus 汇总行里蒙混过去。见 check_required_corpus()。
#
# 退出码: 0 = 全部 diff=0 且 required-corpus 守卫通过 (或 --selftest 通过);
# 1 = 发现 ≥1 diff 或 required-corpus 守卫失败 (或 --selftest 断言失败);
# 2 = preflight 失败 (基线/新代码/语料路径缺失, 环境问题, 非回归发现)。
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

# TASK-017 (SC-1 真语料显式确认, proposal.md §What 4(iii)): coordination 归档
# spec 保持"无声明"是本 change 的一个具体 owner 决策 (2026-07-05, 不回改归
# 档), 不能只靠"它恰好也落在 124-corpus 循环范围内"这个隐含事实——见下方
# check_required_corpus()。kind 对应 sweep() 的 case 分支 (archive|changes)。
REQUIRED_CORPUS_SPEC_ID="2026-07-05-interactive-session-dedup-coordination"
REQUIRED_CORPUS_SPEC_KIND="archive"

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
# 尾部汇总。副作用: 设 SWEEP_N / SWEEP_DIFFS / DIFF_SPECS / SWEPT_SPECS (供
# 调用方 —— 生产 sweep 或 --selftest —— 断言)。SWEPT_SPECS 是本次 sweep 实际
# 处理过的全部 spec_id (TASK-017 required-corpus 守卫用它核验"这个 spec 真被
# 语料发现命中过", 比"没出现在 DIFF_SPECS 里"更强 —— 后者无法区分"扫过且一
# 致"与"根本没扫到", 见 check_required_corpus())。
# ---------------------------------------------------------------------------
sweep() {
  local corpus_root="$1"
  local n=0 diffs=0
  local slowest_spec="" slowest_ms=0
  local t_start t_end
  t_start=$(date +%s)
  DIFF_SPECS=()
  SWEPT_SPECS=()

  for d in "$corpus_root"/openspec/archive/*/ "$corpus_root"/openspec/changes/*/; do
    [ -d "$d" ] || continue
    n=$((n + 1))
    local spec_id kind t0 t1 dur_ms bexit nexit diff_out rc
    spec_id="$(basename "$d")"
    case "$d" in
      */openspec/archive/*) kind=archive ;;
      *) kind=changes ;;
    esac
    SWEPT_SPECS+=("$spec_id")

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
# check_no_runtime_probe_declaration <proposal_md_path> — TASK-017 守卫 (b):
# 复用生产同一套 frontmatter 解析器 (lib/frontmatter_block.py::extract_runtime_probe,
# TASK-004 单一 SOT), 不用裸 grep 'runtime_probe:' —— 裸 grep 无法区分"合法
# 声明" (status=ok) 与"文本层不合法但仍是声明企图" (status=invalid, 例如更深
# 嵌套/flow-style), 也可能被 fenced code block 或散文提及误伤出假阳/假阴。
# status 为 ok 或 invalid 都算"存在声明", 只有 status==absent 才是本守卫要
# 的"保持无声明"。exit 0 = 确认 absent; exit 1 = 声明存在或解析/读取失败
# (诊断信息打到 stdout, 调用方决定转 stderr)。用 flat import (sys.path 插入
# lib/ 本身, 非 `lib.` 包前缀) —— 与 spec_complete.py 在同样"被当独立脚本跑"
# 上下文里的 fallback import 分支手法一致。
# ---------------------------------------------------------------------------
check_no_runtime_probe_declaration() {
  local proposal="$1"
  if [ ! -f "$proposal" ]; then
    echo "proposal.md 未找到: $proposal"
    return 1
  fi
  python3 -B - "$HERE/../scripts/lib" "$proposal" <<'PY'
import sys

lib_dir, path = sys.argv[1], sys.argv[2]
sys.path.insert(0, lib_dir)
from frontmatter_block import _frontmatter_block, extract_runtime_probe  # type: ignore[import]

with open(path, encoding="utf-8") as f:
    text = f.read()
result = extract_runtime_probe(_frontmatter_block(text))
status = result["status"]
if status == "absent":
    sys.exit(0)
print(f"{path} 含 runtime_probe 声明 (status={status}) —— 违反「归档纯净不回改」owner 决策 (2026-07-05)")
sys.exit(1)
PY
}

# ---------------------------------------------------------------------------
# check_required_corpus <spec_id> <kind> — TASK-017 (SC-1 真语料显式确认,
# proposal.md §What 4(iii)): coordination 归档 spec 保持"无声明"这一 owner
# 决策 (2026-07-05, 不回改归档) 不能只隐含在"124 specs 0 diff"汇总行里蒙混
# 过去 —— 汇总行既不会告诉你 CORPUS_ROOT 探测是否悄悄漂到了一个不含该 spec
# 的目录 (漏扫 ≠ 通过), 也不会告诉你有没有人未来给它误加了声明破坏"归档纯
# 净"这个假设。三项断言, 任一失败即整体 FAIL (对应 verification (a)/(b)/(c)):
#   (a) spec_id 确实出现在被扫语料中 (读 sweep() 填充的 SWEPT_SPECS, 而非重
#       新做一次目录存在性判断 —— 后者只能证明"磁盘上有这个目录", 证不了
#       "这次 sweep 真的处理过它", 在 CORPUS_ROOT 指错但该目录路径本身仍存
#       在的边缘场景下两者会分道扬镳)
#   (b) 其 proposal.md frontmatter 用生产同一套解析器确认 status==absent
#   (c) 该 spec_id 不在 DIFF_SPECS 中 (sweep() 判它 diff=0) —— 显式确认零动
#       作路径对这一个具体 spec 真的验证过, 不是"因为没扫到所以自然没 diff"
#       这种假阴性 (故 (c) 依赖 (a) 成立才有意义, 见下方 found 门控)
# 只读, 不修改任何被扫语料 (含目标 spec 本身), 符合"不回改归档"决策。
# ---------------------------------------------------------------------------
check_required_corpus() {
  local spec_id="$1" kind="$2"
  local ok=1 found=0 s

  for s in "${SWEPT_SPECS[@]:-}"; do
    [ "$s" = "$spec_id" ] && { found=1; break; }
  done
  if [ "$found" -eq 1 ]; then
    echo "REQUIRED-CORPUS (a) PASS: '$spec_id' 出现在被扫语料中"
  else
    echo "REQUIRED-CORPUS (a) FAIL: '$spec_id' 未出现在被扫语料中 —— corpus 发现静默漂移 (CORPUS_ROOT=$CORPUS_ROOT 下未命中 openspec/$kind/$spec_id/)" >&2
    ok=0
  fi

  local proposal="$CORPUS_ROOT/openspec/$kind/$spec_id/proposal.md"
  local decl_msg
  if decl_msg="$(check_no_runtime_probe_declaration "$proposal")"; then
    echo "REQUIRED-CORPUS (b) PASS: $proposal frontmatter 无 runtime_probe 声明 (status=absent)"
  else
    echo "REQUIRED-CORPUS (b) FAIL: ${decl_msg:-$proposal 解析失败}" >&2
    ok=0
  fi

  if [ "$found" -eq 1 ]; then
    local is_diff=0
    for s in "${DIFF_SPECS[@]:-}"; do
      [ "$s" = "$spec_id" ] && { is_diff=1; break; }
    done
    if [ "$is_diff" -eq 0 ]; then
      echo "REQUIRED-CORPUS (c) PASS: '$spec_id' diff=0 (零动作路径逐字节不变)"
    else
      echo "REQUIRED-CORPUS (c) FAIL: '$spec_id' 在本次 sweep 中被判定为 DIFF —— 零动作路径未保持不变" >&2
      ok=0
    fi
  else
    echo "REQUIRED-CORPUS (c) FAIL: 无法核验 —— spec 未被扫到, 见 (a)" >&2
    ok=0
  fi

  [ "$ok" -eq 1 ]
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

echo
echo "== required-corpus 守卫 (TASK-017, SC-1 真语料显式确认): $REQUIRED_CORPUS_SPEC_ID =="
guard_ok=1
check_required_corpus "$REQUIRED_CORPUS_SPEC_ID" "$REQUIRED_CORPUS_SPEC_KIND" || guard_ok=0

if [ "$SWEEP_DIFFS" -eq 0 ] && [ "$guard_ok" -eq 1 ]; then
  exit 0
fi
echo
if [ "$SWEEP_DIFFS" -ne 0 ]; then
  echo "DIFF specs: ${DIFF_SPECS[*]}"
fi
if [ "$guard_ok" -ne 1 ]; then
  echo "REQUIRED-CORPUS GUARD FAILED — 见上方 (a)/(b)/(c) 明细" >&2
fi
exit 1

#!/usr/bin/env bash
# 跨 skill 全量测试入口 — aria-plugin
#
# 为什么存在 (Aria #168 / post_planning 补审的 Critical):
#   每个 skill 的测试 runner 只扫自己的 tests/ (state-scanner 的 run_tests.py 把
#   TESTS_DIR 硬编码成 Path(__file__).parent), 而全仓只有它一个 runner。于是
#   「改了 A skill 里、消费方在 B skill 的代码, 只跑 A 的测试」= 结构性漏检。
#   2026-07-19 v1.62.0 真的因此 ship 了一条红测试: state-scanner 退役 `reachable`
#   字段后 session-closer 的消费方被正确修复, 但它自己的测试夹具没跟改, 而
#   「state-scanner 1248 全绿」这句话结构上看不见 session-closer。
#
# 设计要点 —— 区分「真失败」与「跑不了」:
#   本仓部分 skill 的测试是 pytest 套件 (有 conftest.py / import pytest), 而 pytest
#   不是本项目的依赖 (stdlib-only 是 state-scanner 的硬约束)。若把「没装 pytest」
#   算成红, 这个入口默认就是红的 —— 而一个默认红的检查等于没有检查, 会立刻被学会
#   忽略。这正是本 spec 全程在打的假绿/恒红对偶。所以: 缺依赖 => SKIP 并写明原因,
#   只有真正的测试失败才算 FAIL。
#
# 用法:
#   bash skills/run_all_tests.sh            # 全跑
#   bash skills/run_all_tests.sh --list     # 只列出会跑哪些, 不执行
# 退出码: 0 = 无 FAIL (可能有 SKIP); 1 = 至少一个 FAIL

set -uo pipefail
cd "$(dirname "$0")/.." || exit 2
SKILLS_DIR="skills"

LIST_ONLY=0
[ "${1:-}" = "--list" ] && LIST_ONLY=1

fail_count=0
skip_count=0
pass_count=0
total_tests=0
declare -a FAILED_DIRS=()
declare -a SKIPPED_DIRS=()

is_pytest_suite() {
  # conftest.py 存在, 或任一 test_*.py 顶层 import pytest
  [ -f "$1/conftest.py" ] && return 0
  grep -lq '^import pytest\|^from pytest' "$1"/test_*.py 2>/dev/null && return 0
  return 1
}

for tests_dir in $(find "$SKILLS_DIR" -type d -name tests | sort); do
  # 跳过没有测试文件的空目录
  ls "$tests_dir"/test_*.py >/dev/null 2>&1 || continue
  skill=$(echo "$tests_dir" | sed 's|^skills/||; s|/tests$||')

  if [ "$LIST_ONLY" = "1" ]; then
    printf '%-46s ' "$skill"
    if is_pytest_suite "$tests_dir"; then echo "(pytest)"; else echo "(unittest)"; fi
    continue
  fi

  printf '%-46s ' "$skill"

  if is_pytest_suite "$tests_dir"; then
    if ! python3 -c 'import pytest' >/dev/null 2>&1; then
      echo "SKIP — pytest 套件, 但本环境未装 pytest (非失败)"
      skip_count=$((skip_count + 1)); SKIPPED_DIRS+=("$skill")
      continue
    fi
    out=$(cd "$tests_dir" && python3 -m pytest -q 2>&1)
  elif [ -f "$tests_dir/run_tests.py" ]; then
    out=$(cd "$tests_dir" && python3 run_tests.py 2>&1)
  else
    out=$(cd "$tests_dir" && python3 -m unittest discover -s . -p "test_*.py" 2>&1)
  fi
  rc=$?

  n=$(echo "$out" | grep -oE 'Ran [0-9]+ test' | grep -oE '[0-9]+' | tail -1)
  n=${n:-$(echo "$out" | grep -oE '^[0-9]+ passed' | grep -oE '^[0-9]+')}
  n=${n:-0}
  total_tests=$((total_tests + n))

  if [ "$rc" -eq 0 ]; then
    echo "OK ($n tests)"
    pass_count=$((pass_count + 1))
  else
    echo "FAIL ($n tests) — 见下方详情"
    fail_count=$((fail_count + 1)); FAILED_DIRS+=("$skill")
    echo "$out" | grep -E '^(FAIL|ERROR):' | sed 's/^/    /' | head -10
  fi
done

[ "$LIST_ONLY" = "1" ] && exit 0

echo
echo "──────────────────────────────────────────────"
echo "skill 套件: ${pass_count} OK / ${fail_count} FAIL / ${skip_count} SKIP   (累计 ${total_tests} 个测试)"
if [ "${#SKIPPED_DIRS[@]}" -gt 0 ]; then
  echo "SKIP: ${SKIPPED_DIRS[*]}  (装 pytest 后即可纳入)"
fi
if [ "$fail_count" -gt 0 ]; then
  echo "FAIL: ${FAILED_DIRS[*]}"
  exit 1
fi
exit 0

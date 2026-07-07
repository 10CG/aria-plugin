#!/usr/bin/env bash
# test_coordination_probe_cli.sh — TASK-015 (SC-9): coordination_probe.py CLI
# 向后兼容回归 + read-failure 假绿修复独立锁定。
#
# runtime-probe-archive-gate-integration (#95 follow-up A) 把 coordination_probe.py
# 改薄壳, 委托给通用库 scripts/lib/runtime_probe.py (TASK-003)。薄壳契约
# (proposal.md §What 2 / SC-9): 对**四种既有可达状态** (disabled / 分区缺失 /
# 正常 n>=1 / 全陈旧 n==0) 的 stdout 消息 + exit code 必须**逐字节不变** ——
# .aria/state-checks.yaml 的 coordination-gate-invocation check 不该因薄壳化
# 而改变行为。唯一**有意**的行为变化是 read-failure (分区存在但不可读) 的
# 假绿修复: 旧实现落入 `count_production_invocations` 的 `-1` 哨兵值, 又被
# main() 的 `if n == 0` 判定漏过, 兜底打印 "OK (-1 ...)" exit 0 (#95
# audit-Critical 假绿); 新实现把这个形态归为 warn/STALE 类 exit 1。
#
# golden 制作协议 (hermetic): 本文件的 4 个 GOLDEN_* 字面量是**在撰写本测试
# 时**, 用 v1.53.0 薄壳化前基线
# (/home/dev/.claude/plugins/cache/10CG-aria-plugin/aria/1.53.0/skills/
#  state-scanner/scripts/coordination_probe.py — 当前 HEAD 39e1c21 之前的版本)
# 对下面 4 个 fixture 形状逐一实测 stdout+exit 后**手工固化成字面量**的——
# 不在运行时依赖 plugin cache 路径存在 (那是环境相关、非本仓可控的路径)。
# 运行时本脚本只调用**当前仓** coordination_probe.py, diff 对这些固化字面量。
# 任何要求变更这 4 个字面量的改动都应视为 CLI 契约破坏, 需要显式的 spec 决策。
#
# read-failure (fixture 5) 不做字面量 diff (旧行为本身就是要修复的 bug, 不是
# 要保留的契约; 新消息还含平台相关的 OSError 文本, 不适合钉死) —— 只断言
# exit=1 + stdout 以 "STALE" 开头 + 不含旧假绿的 "OK (" 片段 (SC-9)。
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROBE="$HERE/../scripts/coordination_probe.py"

TMP="$(mktemp -d)"
trap 'chmod -R u+rwx "$TMP" 2>/dev/null; rm -rf "$TMP"' EXIT

PASS_CNT=0; FAIL_CNT=0
ok(){ PASS_CNT=$((PASS_CNT+1)); printf '  ok   %s\n' "$1"; }
bad(){ FAIL_CNT=$((FAIL_CNT+1)); printf '  FAIL %s\n' "$1"; }

probe(){
  OUT="$(python3 "$PROBE" "$1" 2>/dev/null)"; EXIT=$?
}

# ---------------------------------------------------------------------------
# Fixture 时间戳相对当前时间生成 (非硬编码日历日期), 任何跑测日期都成立。
# max_age_days 窗口 = 14 (coordination_probe.py 硬编码常量); -1h/-2h 稳落窗口
# 内, -30d 稳落窗口外, 留足边界余量。
# ---------------------------------------------------------------------------
FRESH1="$(date -u -d '-1 hour'  '+%Y-%m-%dT%H:%M:%SZ')"
FRESH2="$(date -u -d '-2 hours' '+%Y-%m-%dT%H:%M:%SZ')"
STALE_TS="$(date -u -d '-30 days' '+%Y-%m-%dT%H:%M:%SZ')"

# ---------------------------------------------------------------------------
# Golden 字面量 (v1.53.0 基线实测捕获 — 见文件头协议; 任务报告附实测对照)
# ---------------------------------------------------------------------------
GOLDEN_DISABLED="OK (coordination gate disabled)"
GOLDEN_MISSING="NO PRODUCTION RECORDS — run_gate never invoked via the CLI (dead-code risk); dogfood (TASK-019) should produce ≥1"
GOLDEN_NORMAL_N2="OK (2 recent production run_gate invocation(s) recorded)"
GOLDEN_STALE="STALE — no production run_gate record within 14d (wired but not recently called → dead-code risk); or partition holds only non-production / malformed records"

echo "== 1. disabled (SC-9 状态 1/4 — 3 个子形状收敛到同一消息+exit) =="

D1A="$TMP/disabled_false"; mkdir -p "$D1A/.aria"
printf '{"state_scanner": {"coordination": {"enabled": false}}}' > "$D1A/.aria/config.json"
probe "$D1A"
[ "$OUT" = "$GOLDEN_DISABLED" ] && [ "$EXIT" = 0 ] && ok "disabled: enabled=false" || bad "disabled: enabled=false — got stdout=[$OUT] exit=$EXIT"

D1B="$TMP/disabled_missing_key"; mkdir -p "$D1B/.aria"
printf '{"state_scanner": {}}' > "$D1B/.aria/config.json"
probe "$D1B"
[ "$OUT" = "$GOLDEN_DISABLED" ] && [ "$EXIT" = 0 ] && ok "disabled: coordination 键缺失" || bad "disabled: coordination 键缺失 — got stdout=[$OUT] exit=$EXIT"

D1C="$TMP/disabled_no_config"; mkdir -p "$D1C"
probe "$D1C"
[ "$OUT" = "$GOLDEN_DISABLED" ] && [ "$EXIT" = 0 ] && ok "disabled: config.json 整体缺失" || bad "disabled: config.json 整体缺失 — got stdout=[$OUT] exit=$EXIT"

echo "== 2. 分区缺失 (SC-9 状态 2/4) =="

D2="$TMP/partition_missing"; mkdir -p "$D2/.aria"
printf '{"state_scanner": {"coordination": {"enabled": true}}}' > "$D2/.aria/config.json"
probe "$D2"
[ "$OUT" = "$GOLDEN_MISSING" ] && [ "$EXIT" = 1 ] && ok "分区缺失" || bad "分区缺失 — got stdout=[$OUT] exit=$EXIT"

echo "== 3. 正常 n>=1 (SC-9 状态 3/4) =="

D3="$TMP/normal_n2"; mkdir -p "$D3/.aria"
printf '{"state_scanner": {"coordination": {"enabled": true}}}' > "$D3/.aria/config.json"
cat > "$D3/.aria/coordination-telemetry.jsonl" <<EOF
{"ts": "$FRESH1", "source": "production", "arm": "manual"}
{"ts": "$FRESH2", "source": "production", "arm": "manual"}
{"ts": "$FRESH1", "source": "harness", "arm": "manual"}
{ this is not valid json
{"ts": "$STALE_TS", "source": "production", "arm": "manual"}

EOF
probe "$D3"
[ "$OUT" = "$GOLDEN_NORMAL_N2" ] && [ "$EXIT" = 0 ] && ok "正常: 2 条窗口内 production 记录 (+ 噪音行)" || bad "正常 n=2 — got stdout=[$OUT] exit=$EXIT"

echo "== 4. 全陈旧 n==0 (SC-9 状态 4/4) =="

D4="$TMP/all_stale"; mkdir -p "$D4/.aria"
printf '{"state_scanner": {"coordination": {"enabled": true}}}' > "$D4/.aria/config.json"
cat > "$D4/.aria/coordination-telemetry.jsonl" <<EOF
{"ts": "$STALE_TS", "source": "production", "arm": "manual"}
{"ts": "$FRESH1", "source": "harness", "arm": "manual"}
EOF
probe "$D4"
[ "$OUT" = "$GOLDEN_STALE" ] && [ "$EXIT" = 1 ] && ok "全陈旧: 仅 >14d production + 非 production 噪音" || bad "全陈旧 n=0 — got stdout=[$OUT] exit=$EXIT"

echo "== 5. read-failure — 新行为独立锁定 (非逐字节对旧版, 旧版本身是待修假绿) =="

if [ "$(id -u)" = "0" ]; then
  echo "  跳过 (以 root 运行 — chmod 000 不可读 fixture 对 root 无意义)"
else
  D5="$TMP/unreadable"; mkdir -p "$D5/.aria"
  printf '{"state_scanner": {"coordination": {"enabled": true}}}' > "$D5/.aria/config.json"
  printf '{"ts": "%s", "source": "production", "arm": "manual"}\n' "$FRESH1" > "$D5/.aria/coordination-telemetry.jsonl"
  chmod 000 "$D5/.aria/coordination-telemetry.jsonl"

  probe "$D5"
  [ "$EXIT" = 1 ] && ok "read-failure: exit=1" || bad "read-failure: exit=$EXIT (want 1)"
  case "$OUT" in
    STALE*) ok "read-failure: stdout 以 STALE 开头" ;;
    *) bad "read-failure: stdout 未以 STALE 开头: [$OUT]" ;;
  esac
  case "$OUT" in
    *"OK ("*) bad "read-failure: stdout 不应含旧假绿片段 'OK (' (got: [$OUT])" ;;
    *) ok "read-failure: stdout 不含 'OK (' 假绿片段" ;;
  esac

  chmod 644 "$D5/.aria/coordination-telemetry.jsonl"
fi

echo
echo "== 结果: $PASS_CNT passed, $FAIL_CNT failed =="
[ "$FAIL_CNT" -eq 0 ]

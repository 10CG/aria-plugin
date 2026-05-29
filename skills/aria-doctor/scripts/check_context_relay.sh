#!/bin/bash
# check_context_relay.sh — aria-context-monitor statusLine relay 安装状态诊断.
#
# 报告 3 态 (relay-installed / statusline-no-relay / no-statusline) + jq 可用性.
# 返回 JSON. 永不写入 (纯诊断, read-only).
#
# 用法: bash check_context_relay.sh [--settings PATH] [--help]
set -u

SETTINGS="${HOME}/.claude/settings.json"

while [ $# -gt 0 ]; do
  case "$1" in
    --settings) SETTINGS="$2"; shift 2 ;;
    --help)
      cat <<'H'
check_context_relay.sh — diagnose aria-context-monitor relay install state.
  --settings PATH   settings.json path (default ~/.claude/settings.json)
Outputs JSON: { state, jq_available, statusline_script, advisory }
  state: relay-installed | statusline-no-relay | no-statusline | no-settings | statusline-inline-or-missing-script
Exit 0 always (state encodes result).
H
      exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

MARKER_OPEN="# >>> aria-context-monitor relay >>>"

# jq availability
if command -v jq >/dev/null 2>&1; then jq_available=true; else jq_available=false; fi

emit() {  # state, script, advisory
  local state="$1" script="$2" advisory="$3"
  if [ "$jq_available" = true ]; then
    jq -n --arg s "$state" --argjson jq "$jq_available" --arg sc "$script" --arg a "$advisory" \
      '{state:$s, jq_available:$jq, statusline_script:$sc, advisory:$a}'
  else
    # jq 缺失时手工拼 JSON (诊断仍可用)
    printf '{"state":"%s","jq_available":false,"statusline_script":"%s","advisory":"%s"}\n' \
      "$state" "$script" "$advisory jq 缺失: relay 写入侧不工作, 仅 transcript fallback 可用, 请安装 jq。"
  fi
}

# --- 解析 statusLine ---
if [ ! -f "$SETTINGS" ]; then
  emit "no-settings" "" "无 settings.json — 运行 setup_relay.sh 建最小 reference statusline + relay。"
  exit 0
fi

cmd=""
if [ "$jq_available" = true ]; then
  cmd=$(jq -r '.statusLine.command // ""' "$SETTINGS" 2>/dev/null)
else
  cmd=$(grep -o '"command"[^,}]*' "$SETTINGS" 2>/dev/null | head -1)
fi

if [ -z "$cmd" ]; then
  emit "no-statusline" "" "statusLine 未配 — 运行 setup_relay.sh 建最小 reference + relay (或 aria-context-monitor 走 transcript fallback)。"
  exit 0
fi

script=$(printf '%s\n' "$cmd" | grep -oE '[^ "]+\.sh' | head -1)
if [ -z "$script" ] || [ ! -f "$script" ]; then
  emit "statusline-inline-or-missing-script" "$script" "statusLine command 非脚本文件或脚本缺失 — 无法自动注入, 见 aria-context-monitor SKILL.md 手动注入 relay 块。"
  exit 0
fi

if grep -qF "$MARKER_OPEN" "$script" 2>/dev/null; then
  emit "relay-installed" "$script" "relay 已安装 — aria-context-monitor 走 runtime-truth (source=relay_cache)。"
else
  emit "statusline-no-relay" "$script" "statusLine 已配但无 relay marker — 运行 setup_relay.sh 注入 (幂等, 自动备份)。"
fi
exit 0

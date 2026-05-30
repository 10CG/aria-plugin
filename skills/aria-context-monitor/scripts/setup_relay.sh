#!/bin/bash
# setup_relay.sh — 幂等注入 aria-context-monitor statusLine relay.
#
# 行为:
#   - statusLine 已配 + 引用脚本 → 在脚本 `input=$(cat)` 后注入 marker-包裹 relay 块
#   - 已注入 (marker 检测) → no-op (幂等)
#   - 无 statusLine → 建最小 reference statusline (仅 context bar + relay, 无个人偏好)
#
# relay 块约束: 复用 $input (不再 cat) / 注入在 input=$(cat) 之后 / atomic tmp($$)→rename /
#               仅写 cwd/.aria/cache/ (需 .aria 存在, 避免污染非 aria 项目).
#
# 用法: bash setup_relay.sh [--settings PATH] [--dry-run] [--status]
set -u

SETTINGS="${HOME}/.claude/settings.json"
DRY_RUN=0
STATUS_ONLY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --settings) SETTINGS="$2"; shift 2 ;;
    --dry-run)  DRY_RUN=1; shift ;;
    --status)   STATUS_ONLY=1; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

MARKER_OPEN="# >>> aria-context-monitor relay >>>"
MARKER_CLOSE="# <<< aria-context-monitor relay <<<"

# jq 硬依赖 (relay 块本身用 jq). 缺失 → graceful 提示退出.
if ! command -v jq >/dev/null 2>&1; then
  echo "STATUS: jq-missing"
  echo "relay 注入需要 jq (relay 块解析 statusLine stdin). 请先安装 jq。" >&2
  echo "降级: 无 relay 时 aria-context-monitor 走 transcript fallback (confidence=estimate)。" >&2
  exit 3
fi

# --- relay 块定义 (注入到 statusline 脚本) ------------------------------------
relay_block() {
  cat <<'RELAY'
# >>> aria-context-monitor relay >>>
# 复用上方 input=$(cat) 捕获的 $input (一次性 stdin 已耗尽, 不可再 cat).
__aria_cwd=$(printf '%s' "$input" | jq -r '.workspace.current_dir // .cwd // ""' 2>/dev/null)
__aria_cwd="${__aria_cwd%$'\r'}"   # crlf-strip(#132 sibling): Windows native jq emits CRLF; $() keeps trailing \r → the [ -d ] gate below would fail and relay would silently skip writing the cache. Single-scalar path → strip trailing CR.
if [ -n "$__aria_cwd" ] && [ -d "$__aria_cwd/.aria" ]; then
  mkdir -p "$__aria_cwd/.aria/cache" 2>/dev/null
  __aria_tmp="$__aria_cwd/.aria/cache/.context-window.$$.tmp"
  printf '%s' "$input" | jq -c '{schema_version:"1.0",captured_at:(now|todate),model_id:.model.id,context_window_size:.context_window.context_window_size,used_percentage:.context_window.used_percentage,remaining_percentage:.context_window.remaining_percentage,total_input_tokens:.context_window.total_input_tokens,current_usage:.context_window.current_usage,exceeds_200k_tokens:.exceeds_200k_tokens,transcript_path:.transcript_path}' > "$__aria_tmp" 2>/dev/null \
    && mv "$__aria_tmp" "$__aria_cwd/.aria/cache/context-window.json" 2>/dev/null \
    || rm -f "$__aria_tmp" 2>/dev/null
fi
# <<< aria-context-monitor relay <<<
RELAY
}

# --- 解析 statusLine 脚本路径 -------------------------------------------------
resolve_script_path() {
  [ -f "$SETTINGS" ] || { echo ""; return; }
  local cmd
  cmd=$(jq -r '.statusLine.command // ""' "$SETTINGS" 2>/dev/null)
  cmd="${cmd%$'\r'}"   # crlf-strip(#132 sibling): marker/path value → strip trailing CR (Windows native jq CRLF)
  [ -n "$cmd" ] || { echo ""; return; }
  # 提取以 .sh 结尾的 token (常见: "bash /path/script.sh")
  local p
  p=$(printf '%s\n' "$cmd" | grep -oE '[^ ]+\.sh' | head -1)
  echo "$p"
}

detect_state() {
  if [ ! -f "$SETTINGS" ]; then echo "no-settings"; return; fi
  local cmd
  cmd=$(jq -r '.statusLine.command // ""' "$SETTINGS" 2>/dev/null)
  cmd="${cmd%$'\r'}"   # crlf-strip(#132 sibling): comparison value → strip trailing CR (Windows native jq CRLF)
  if [ -z "$cmd" ]; then echo "no-statusline"; return; fi
  local sp
  sp=$(resolve_script_path)
  if [ -z "$sp" ] || [ ! -f "$sp" ]; then echo "statusline-inline-or-missing-script"; return; fi
  if grep -qF "$MARKER_OPEN" "$sp" 2>/dev/null; then echo "relay-installed"; return; fi
  echo "statusline-no-relay"
}

STATE=$(detect_state)

if [ "$STATUS_ONLY" -eq 1 ]; then
  echo "STATUS: $STATE"
  [ "$STATE" = "relay-installed" ] && echo "script: $(resolve_script_path)"
  exit 0
fi

case "$STATE" in
  relay-installed)
    echo "STATUS: relay-installed (no-op, 幂等)"
    echo "script: $(resolve_script_path)"
    exit 0
    ;;
  statusline-no-relay)
    SCRIPT=$(resolve_script_path)
    echo "STATE: statusline-no-relay → 注入 relay 到 $SCRIPT"
    if [ "$DRY_RUN" -eq 1 ]; then
      echo "--- dry-run: 将在 'input=\$(cat)' 后注入: ---"; relay_block
      exit 0
    fi
    cp "$SCRIPT" "$SCRIPT.aria-relay-bak.$$" 2>/dev/null
    TMP="$SCRIPT.aria-inject.$$"
    awk -v block="$(relay_block)" '
      { print }
      !done && /input=\$\(cat\)/ { print ""; print block; done=1 }
    ' "$SCRIPT" > "$TMP" 2>/dev/null
    if grep -qF "$MARKER_OPEN" "$TMP" 2>/dev/null; then
      mv "$TMP" "$SCRIPT"
      echo "STATUS: injected (backup: $SCRIPT.aria-relay-bak.$$)"
      exit 0
    else
      rm -f "$TMP"
      echo "ERROR: 未找到 'input=\$(cat)' 锚点, 注入失败. 请手动注入 relay 块或检查 statusLine 脚本结构。" >&2
      exit 4
    fi
    ;;
  no-statusline|no-settings)
    REF="${HOME}/.claude/statusline-command.sh"
    echo "STATE: $STATE → 建最小 reference statusline: $REF"
    if [ "$DRY_RUN" -eq 1 ]; then
      echo "--- dry-run: 将创建最小 reference (context bar + relay) ---"
      exit 0
    fi
    mkdir -p "${HOME}/.claude" 2>/dev/null
    [ -f "$REF" ] && cp "$REF" "$REF.aria-relay-bak.$$" 2>/dev/null
    {
      echo "#!/bin/bash"
      echo 'input=$(cat)'
      echo ""
      relay_block
      echo ""
      echo '# 最小 context bar (仅参考, 无个人偏好 — instance-layer 偏好请自行扩展)'
      echo 'used=$(printf '"'"'%s'"'"' "$input" | jq -r '"'"'.context_window.used_percentage // "?"'"'"' 2>/dev/null)'
      echo 'used=${used%$'"'"'\r'"'"'}'   # crlf-strip(#132 sibling): Windows native jq CRLF would render a stray CR in the status bar
      echo 'model=$(printf '"'"'%s'"'"' "$input" | jq -r '"'"'.model.display_name // "Claude"'"'"' 2>/dev/null)'
      echo 'model=${model%$'"'"'\r'"'"'}'   # crlf-strip(#132 sibling): same — single-scalar display value
      echo 'printf "%s | ctx %s%%" "$model" "$used"'
    } > "$REF"
    chmod +x "$REF" 2>/dev/null
    # wire settings.json statusLine if absent
    if [ -f "$SETTINGS" ]; then
      TMPS="$SETTINGS.aria.$$"
      jq --arg cmd "bash $REF" '.statusLine = {type:"command", command:$cmd}' "$SETTINGS" > "$TMPS" 2>/dev/null \
        && mv "$TMPS" "$SETTINGS" && echo "wired statusLine in $SETTINGS" || rm -f "$TMPS"
    else
      mkdir -p "$(dirname "$SETTINGS")" 2>/dev/null
      printf '{\n  "statusLine": { "type": "command", "command": "bash %s" }\n}\n' "$REF" > "$SETTINGS"
      echo "created $SETTINGS with statusLine"
    fi
    echo "STATUS: minimal-reference-created"
    exit 0
    ;;
  *)
    echo "STATE: $STATE (statusLine command 非脚本文件 / 无法定位)"
    echo "请确保 statusLine.command 引用一个 .sh 脚本, 或手动注入 relay 块 (见 SKILL.md)。" >&2
    exit 5
    ;;
esac

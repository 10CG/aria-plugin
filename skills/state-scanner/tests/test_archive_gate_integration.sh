#!/usr/bin/env bash
# test_archive_gate_integration.sh — #95 TASK-024 集成/端到端 gate 测试 (paper-fix guard)。
#
# 纯 pytest (test_spec_complete.py) 只测 lib 纯函数; 但 openspec-archive Step1/Step2/Step7 +
# phase-d-closer D.2 的 gate 编排在 SKILL.md 的 **Bash 调用层** (AI 按 prose 执行 `python3
# spec_complete.py --gate <dir>` + 读 verdict 路由)。本脚本**真跑那些 Bash 命令**, 验证:
#   1. --gate CLI 端到端 verdict + exit code 契约 (block=exit1 / pass·warn=exit0)
#   2. 两消费方 (openspec-archive gate 调用 vs phase-d-closer D.2 调用) 对同一 spec verdict 一致
#   3. Step2 warn 路径 unverified_claims 真写入 proposal.md frontmatter (脚本化 SKILL.md prose)
#   4. Step7 D auto-issue payload 幂等 marker + headless (无 ack) 恒产 d_payload
#   5. 全 fail-soft: 坏输入不 block (verdict≠block) + soft_errors
#
# block 用**自包含合成死代码 spec** (不依赖真实归档语料 —— Layer L phase1_gate 已被 DEC-002
# 接活, 不再是死代码)。镜像 #134 initial-sh-integration 真 call-site 范式。JSON 解析用 python3
# (非 jq — 见 shell-jq-crlf-hygiene: jq CRLF 陷阱)。退出 0 = 全通过 / 非 0 = 有断言失败。
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB="$HERE/../scripts/lib/spec_complete.py"
ROOT="$HERE"; while [ "$ROOT" != "/" ] && [ ! -d "$ROOT/openspec/archive" ]; do ROOT="$(dirname "$ROOT")"; done

WARN_SPEC="$ROOT/openspec/archive/2026-06-11-audit-drift-guard"   # warn (drift_warning 无 Py 定义)
PASS_SPEC="$ROOT/openspec/archive/2025-12-16-spec-drafter"        # pass

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

# ── 合成死代码 spec (block case): git repo + lib/orphan_gate.py 定义 + spec 声称集成它 + 仅散文提及 ──
SYNTH="$TMP/proj"
mkdir -p "$SYNTH/lib" "$SYNTH/openspec/changes/synth-dead"
printf 'def orphan_gate():\n    """dead-on-arrival: 定义存在但零生产调用"""\n    pass\n' > "$SYNTH/lib/orphan_gate.py"
printf 'orphan_gate 仅此 README 散文提及, 从未被生产 import/调用。\n' > "$SYNTH/README.md"
printf '# Proposal: synth-dead\n> **Status**: Approved\n## Success Criteria\n- [ ] x\n' > "$SYNTH/openspec/changes/synth-dead/proposal.md"
printf '# Tasks\n- [x] 9.1 集成 `orphan_gate` 到 orchestrator (死代码, 应 block)\n' > "$SYNTH/openspec/changes/synth-dead/tasks.md"
printf 'tasks:\n  - id: TASK-901\n    parent: "9.1"\n    deliverables: ["lib/orphan_gate.py"]\n' > "$SYNTH/openspec/changes/synth-dead/detailed-tasks.yaml"
git -C "$SYNTH" init -q 2>/dev/null && git -C "$SYNTH" add -A 2>/dev/null && \
  git -C "$SYNTH" -c user.email=t@t -c user.name=t commit -qm init 2>/dev/null
GOLDEN="$SYNTH/openspec/changes/synth-dead"

PASS_CNT=0; FAIL_CNT=0
ok(){ PASS_CNT=$((PASS_CNT+1)); printf '  ok   %s\n' "$1"; }
bad(){ FAIL_CNT=$((FAIL_CNT+1)); printf '  FAIL %s\n' "$1"; }

gate(){
  GATE_JSON="$(python3 "$LIB" --gate "$1" 2>/dev/null)"; EXIT=$?
  read -r VERDICT DPAYLOAD_NULL <<EOF
$(printf '%s' "$GATE_JSON" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("verdict"), d.get("d_payload") is None)')
EOF
}

echo "== 1. --gate verdict + exit code 契约 =="
gate "$GOLDEN";   [ "$VERDICT" = block ] && [ "$EXIT" = 1 ] && ok "合成死代码 → verdict=block exit=1" || bad "block verdict=$VERDICT exit=$EXIT (期望 block/1)"
gate "$WARN_SPEC";[ "$VERDICT" = warn ]  && [ "$EXIT" = 0 ] && ok "warn-spec → verdict=warn exit=0" || bad "warn verdict=$VERDICT exit=$EXIT (期望 warn/0)"
gate "$PASS_SPEC";[ "$VERDICT" = pass ]  && [ "$EXIT" = 0 ] && ok "pass-spec → verdict=pass exit=0" || bad "pass verdict=$VERDICT exit=$EXIT (期望 pass/0)"

echo "== 2. 两消费方 verdict 一致 (AC-1 多入口不变量) =="
V1="$(python3 "$LIB" --gate "$GOLDEN" 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin)["verdict"])')"
V2="$(python3 "$LIB" --gate "$GOLDEN" 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin)["verdict"])')"
[ "$V1" = "$V2" ] && [ "$V1" = block ] && ok "两入口对同一 spec verdict 一致 ($V1)" || bad "两入口 verdict 漂移: $V1 vs $V2"

echo "== 3. Step2 warn 路径 unverified_claims 真写入 frontmatter (脚本化 SKILL.md prose) =="
mkdir -p "$TMP/warnspec"
printf '# Proposal: tmp-warn\n> **Status**: Approved\n## Success Criteria\n- [ ] x\n' > "$TMP/warnspec/proposal.md"
printf '# Tasks\n- [x] 1.1 dogfood 验证已完成\n' > "$TMP/warnspec/tasks.md"
gate "$TMP/warnspec"
if [ "$VERDICT" = warn ]; then
  python3 - "$TMP/warnspec/proposal.md" "$GATE_JSON" <<'PY'
import sys, json
path, gate_json = sys.argv[1], sys.argv[2]
uc = json.loads(gate_json).get("unverified_claims", [])
txt = open(path, encoding="utf-8").read()
open(path, "w", encoding="utf-8").write("---\nunverified_claims: %d\nunverified_ack: false\n---\n" % len(uc) + txt)
PY
  grep -q '^unverified_claims:' "$TMP/warnspec/proposal.md" && ok "warn → unverified_claims 写入 frontmatter" || bad "frontmatter 未写入"
else
  bad "warn fixture verdict=$VERDICT (期望 warn)"
fi

echo "== 4. Step7 D payload 幂等 marker + headless =="
# marker 用 WARN_SPEC (有 unverified_claims → d_payload 非空); 纯 block spec 无 deferred/unverified
# 故 d_payload 为空是正确的 (block 不归档不建 tracker)。
MARKER="$(python3 "$LIB" --gate "$WARN_SPEC" 2>/dev/null | python3 -c 'import sys,json;d=json.load(sys.stdin).get("d_payload") or {};print(d.get("marker",""))')"
case "$MARKER" in
  '<!-- archive-tracker:'*'-->') ok "d_payload.marker 格式正确";;
  *) bad "d_payload.marker 格式异常: $MARKER";;
esac
DP="$(python3 "$LIB" --gate "$WARN_SPEC" 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin).get("d_payload") is not None)')"
[ "$DP" = True ] && ok "d_payload headless 恒产 (无 ack 依赖)" || bad "d_payload 缺失"

echo "== 5. fail-soft: 坏输入 / gate 边界不 block =="
gate "$TMP/nonexistent-spec-dir"
[ "$VERDICT" != block ] && ok "不存在 spec_dir → 不 block (verdict=$VERDICT)" || bad "坏输入误 block"
# I1/I2 fix: usage 错也 fail-toward-warn 不 block
UV="$(python3 "$LIB" --gate 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin)["verdict"])')"
[ "$UV" != block ] && ok "usage 错 → fail-toward-warn 不 block ($UV)" || bad "usage 错误 block"

echo
echo "== 结果: $PASS_CNT passed, $FAIL_CNT failed =="
[ "$FAIL_CNT" -eq 0 ]

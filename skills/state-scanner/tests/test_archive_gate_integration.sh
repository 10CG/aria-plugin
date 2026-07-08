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
#   6-9. runtime-probe-archive-gate-integration TASK-016 (#95 follow-up A, SC-10): 首次在连续
#      Step1-2 归档流程中按 openspec-archive SKILL.md :167-229 契约行使 runtime_probe warn_overlay
#      写入路径 — warn 正控 + {pass, mixed-pass, mixed-skipped, 声明无效} 四类负控, 断言经真实
#      解析路径 (_frontmatter_block()/_read_archive_type()/_staleness_days()), 非裸 grep。
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

# ── SC-10 (runtime-probe-archive-gate-integration TASK-016, #95 follow-up A) 共享 helper ──
# openspec-archive SKILL.md Step2 warn_overlay (:167-238) 写入契约的脚本化模拟 — Step 2 本身是
# AI 执行的 prose, 无可复用的生产 Python 函数 (与既有 §3 precedent 同样手写); 本 helper 把散落
# 的手写逻辑收敛成一份, 供 §3 与下方 §6-9 共享, 严格贴契约: 触发条件 verdict=="warn" (由调用方
# 判断是否要调本 helper, 本文件从不在 verdict!=warn 时调用) / 无既有块→文件绝对起始插入 (原内容
# 整体下移) vs 已有块→追加 / unverified_claims list-of-object (claim/reason/symbols) /
# runtime_probe 结果字段仅当探针自身 outcome∈{warn,invalid} 才写 (与门级 verdict 来源正交)。
# **同名键 merge-append 规则** (SKILL.md :213-221, 主控裁决 2026-07-08, 替代 TASK-016 首版
# replace-in-place 实现选择): 带声明 spec 的既有块必然已含作者自写的 `runtime_probe:` 顶层
# mapping (声明本身就是该 mapping 唯一发现途径), 结果字段 outcome/count/ts **merge-append
# 进同一 mapping** (symbol 已由声明携带则不重复写, 声明缺 symbol 时补写 probe 返回值) ——
# **不删不改任何作者声明字段** (partition/max_age_days/enabled_when 原样保留, 归档不改作者
# 本体), 不产生 YAML 重复键, 不新起第二个 runtime_probe mapping (reason 不落盘, 已在对应
# unverified_claims 条目里承载)。写到 $TMP (非提交物), 全程只用生产侧
# _FRONTMATTER_RE/_frontmatter_block/extract_runtime_probe (与 collectors/openspec.py 消费面
# 同一 SOT) 定位/复验块边界, 不做裸字符串猜测。
export SS_SCRIPTS_DIR="$HERE/../scripts"
export SS_TMP_DIR="$TMP"
E2ELIB="$TMP/e2e_probe_lib.py"
cat > "$E2ELIB" <<'PYLIB'
import json, os, sys
from pathlib import Path

_LIB_DIR = os.environ["SS_SCRIPTS_DIR"] + "/lib"
_SCRIPTS_DIR = os.environ["SS_SCRIPTS_DIR"]
for _p in (_LIB_DIR, _SCRIPTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from frontmatter_block import (  # noqa: E402
    _FRONTMATTER_RE,
    _frontmatter_block,
    _TOP_KEY_RE,
    _strip_inline_comment,
    _rejected_scalar_reason,
    extract_runtime_probe,
)
import collectors.openspec as _openspec_mod  # noqa: E402
from collectors._common import CollectorResult  # noqa: E402


def _q(s):
    return json.dumps(s, ensure_ascii=False)


class RuntimeProbeMergeContractError(RuntimeError):
    """顶键行既非裸块声明又非可识别的降级形态 (SKILL.md :226-227) —— 契约
    破坏, 必须显式报错, 不得静默追加第二个同名顶层键。同样覆盖"完全找不到
    顶键行"的结构上不可达兜底 (旧版在此静默退化成新增完整结果块, R1 修法
    改为同一 hard-fail 出口, 不再有第二条隐藏的兜底路径)。"""


def _merge_append_runtime_probe(lines, rp):
    """merge-append 语义 (openspec-archive SKILL.md "runtime_probe 同名键
    merge-append 规则" :213-227, 主控裁决 2026-07-08 — 替代 TASK-016 首版
    replace-in-place 实现选择; R1 [SFH I-1 / TL F3] 顶键定位与降级路径修法):

    顶键定位改产**等价语义** —— 复用生产 `_TOP_KEY_RE`/`_strip_inline_comment`
    两级解析原语 (非裸字符串 `==` 比较), 与 `extract_runtime_probe` 同一判定:
    顶键行尾随空格 / 行尾注释被生产解析器判合法声明, 定位不应因此失败。

    三路分叉 (SKILL.md :221-227, 与 `extract_runtime_probe` 的"拒绝任何非裸
    `runtime_probe:` 顶键行内容"判定同一棵判定树):

      (a) 裸块声明 (top_value 剥行尾注释剥首尾空白后为空) → 沿用既有
          merge-append: outcome/count/ts 追加进块内 (symbol 已由声明携带
          则不重复写), 既有作者子行原样保留、顺序不变。返回
          ``(new_lines, "merged")``。

      (b) 降级路径 (作者值非块 mapping —— 顶层 flow-style `{...}` / 锚点
          别名 `&`/`*` / 多行块量 `|`/`>`, 即 `_rejected_scalar_reason` 可
          归类的非空 top_value): merge-append 结构上不适用 →
          **保留作者行原样, 结果键不落盘** (不新起同名键/不产生重复键/不
          改写作者行; "无法核验"信号已由同批 unverified_claims 条目完整
          承载)。返回 ``(lines 原样不变, "degraded")``。

      (c) 意外结构 (非空 top_value 但 `_rejected_scalar_reason` 无法归类
          —— 既非(a)又非(b)) **以及** 扫描完毕未见任何顶层 `runtime_probe:`
          键 (write_rp=True 却无声明行, 结构上不可达: write_rp 恒源自对
          同一 proposal 文本 --gate 折入, 折入前提正是该顶键行已被生产
          `extract_runtime_probe` 定位到) —— 两种情形均视为**契约破坏**,
          **显式报错** (`RuntimeProbeMergeContractError`), 不再静默退化为
          "新增一个完整结果块" (旧版行为, 直接违反 SKILL.md "不产生 YAML
          重复键")。
    """
    start = None
    top_rest = ""
    for idx, line in enumerate(lines):
        m = _TOP_KEY_RE.match(line)
        if m:
            start = idx
            top_rest = m.group(1)
            break

    if start is None:
        raise RuntimeProbeMergeContractError(
            "write_rp=True but no top-level `runtime_probe:` line found in "
            "body — refusing silent duplicate-key fallback"
        )

    top_value = _strip_inline_comment(top_rest).strip()

    if top_value != "":
        reason = _rejected_scalar_reason(top_value)
        if reason is None:
            raise RuntimeProbeMergeContractError(
                f"unexpected runtime_probe top-key line shape: {lines[start]!r} "
                f"(top_value={top_value!r} unclassifiable — neither bare block "
                f"nor a recognized degraded form)"
            )
        # (b) 降级路径: 保留作者行原样, 结果键不落盘, 不消费/不改写该行
        # 之后的任何内容 (非块声明, 无"块内容"概念可言)。
        return list(lines), "degraded"

    # (a) 裸块声明 —— 与生产 extract_runtime_probe 同一判定 (top_value 剥
    # 注释剥空白后为空), 沿用既有 merge-append 行为。
    out = list(lines[: start + 1])
    has_symbol = False
    i = start + 1
    n = len(lines)
    while i < n and (lines[i].startswith(" ") or lines[i] == ""):
        if lines[i].strip().startswith("symbol:"):
            has_symbol = True
        out.append(lines[i])
        i += 1
    out.append(f"  outcome: {_q(rp['outcome'])}")
    out.append(f"  count: {rp['count']}")
    out.append(f"  ts: {_q(rp['ts'])}")
    if not has_symbol:
        out.append(f"  symbol: {_q(rp['symbol'])}")
    out.extend(lines[i:])
    return out, "merged"


def write_warn_overlay(proposal_path, gate_json, ack=False):
    """openspec-archive SKILL.md :167-238 warn_overlay write, hand-simulated
    (caller only invokes this when gate.verdict == "warn" — the SKILL.md
    trigger condition; SC-10 负控(a) verdict=pass never calls this)."""
    path = Path(proposal_path)
    text = path.read_text(encoding="utf-8")
    gate = json.loads(gate_json)
    uc = gate.get("unverified_claims", [])
    rp = gate.get("runtime_probe")
    # 内容归属条件 (SKILL.md :222-230, 与触发条件正交): 仅探针自身
    # outcome∈{warn,invalid} 才写 runtime_probe 结果字段, 与门级 verdict 来源无关。
    write_rp = rp is not None and rp.get("outcome") in ("warn", "invalid")

    new_lines = ["unverified_claims:"]
    for c in uc:
        new_lines.append(f"  - claim: {_q(c['claim'])}")
        new_lines.append(f"    reason: {_q(c['reason'])}")
        syms = "[" + ", ".join(_q(s) for s in c.get("symbols", [])) + "]"
        new_lines.append(f"    symbols: {syms}")
    new_lines.append(f"unverified_ack: {'true' if ack else 'false'}")

    m = _FRONTMATTER_RE.match(text)
    if m is None:
        # 无既有块 (118/118 现状) → 文件绝对起始插入新块, 原内容整体下移。
        # write_rp=True 在此分支理论不可达 (extract_runtime_probe(None) 恒
        # status=absent, 无声明就不可能有 outcome∈{warn,invalid} 的
        # gate_result.runtime_probe) —— 防御性兜底: 仍产出一个全新 4 字段
        # 结果块, 不静默吞掉。
        if write_rp:
            new_lines += [
                "runtime_probe:",
                f"  outcome: {_q(rp['outcome'])}",
                f"  count: {rp['count']}",
                f"  ts: {_q(rp['ts'])}",
                f"  symbol: {_q(rp['symbol'])}",
            ]
        new_text = "---\n" + "\n".join(new_lines) + "\n---\n" + text
    else:
        # 已有块 (本 change 唯一来源: 活跃期作者自写的 runtime_probe 声明本身
        # 就需要一个既有块才能被 gate 解析到) → merge-append 语义 (SKILL.md
        # "runtime_probe 同名键 merge-append 规则", 主控裁决 2026-07-08; R1
        # 修法): outcome/count/ts 追加进既有 runtime_probe: mapping 内
        # (symbol 仅声明未携带时补写), 不删不改任何作者声明字段, 不产生
        # YAML 重复键。`_merge_append_runtime_probe` 现在是这条规则的**唯一**
        # 出口 —— "merged"(追加)/"degraded"(降级路径, body_lines 原样不变)
        # 两态都已是终态, 不再需要旧版"未 merged 时退化新增完整块"的兜底
        # 分支 (该兜底已被移除, 换成函数内部的显式 hard-fail, 见其 docstring)。
        body_lines = m.group(1).splitlines()
        if write_rp:
            body_lines, _merge_outcome = _merge_append_runtime_probe(body_lines, rp)
        merged_body = "\n".join(body_lines + new_lines)
        new_text = "---\n" + merged_body + "\n---\n" + text[m.end():]
    path.write_text(new_text, encoding="utf-8")


def parse_unverified_claims(fm_body):
    """真实解析路径 (非裸 grep): 定位 `unverified_claims:` 顶层键, 结构化
    读出 list-of-object (claim/reason/symbols) — 缺席时返回 None。"""
    lines = fm_body.splitlines()
    start = next((i for i, l in enumerate(lines) if l == "unverified_claims:"), None)
    if start is None:
        return None
    items, cur, i = [], None, start + 1
    while i < len(lines):
        line = lines[i]
        if line.startswith("  - claim:"):
            if cur is not None:
                items.append(cur)
            cur = {"claim": json.loads(line.split(":", 1)[1].strip())}
        elif line.startswith("    reason:") and cur is not None:
            cur["reason"] = json.loads(line.split(":", 1)[1].strip())
        elif line.startswith("    symbols:") and cur is not None:
            cur["symbols"] = json.loads(line.split(":", 1)[1].strip())
        elif not (line.startswith("  ") or line == ""):
            break  # dedent — 下一顶层键
        i += 1
    if cur is not None:
        items.append(cur)
    return items


def parse_runtime_probe_result(fm_body):
    """真实解析路径: 定位含 `outcome` 子字段的 `runtime_probe:` 块 (与
    declaration 子块 [partition/symbol/...] 区分 — declaration 从无 outcome
    子字段), 缺席时返回 None。顶键行定位与写入侧 `_merge_append_runtime_probe`
    同一等价语义 (`_TOP_KEY_RE`/`_strip_inline_comment`, 容忍尾随空格/行尾
    注释) —— 若仍用裸 `== "runtime_probe:"` 字节比较, R1 新增案例(ii) 的
    "顶键行带行尾注释" 场景会在读侧误判块缺席, 即便写侧 merge-append 已经
    正确工作, 也测不出来 (读写两侧判定必须同一棵判定树, 否则测试本身就是
    盲区)。非空 top_value (降级路径场景) 时不当作块起点 —— 该行不消费,
    继续向后扫描 (与 `_merge_append_runtime_probe` 的"降级路径不生产结果键"
    互为镜像: 读侧自然返回 None, 无需额外分支)。"""
    lines = fm_body.splitlines()
    i, n = 0, len(lines)
    while i < n:
        m = _TOP_KEY_RE.match(lines[i])
        if m and _strip_inline_comment(m.group(1)).strip() == "":
            fields, j = {}, i + 1
            while j < n and lines[j].startswith("  "):
                k, _, v = lines[j].strip().partition(":")
                v = v.strip()
                try:
                    fields[k] = json.loads(v)
                except Exception:
                    fields[k] = v
                j += 1
            if "outcome" in fields:
                return fields
            i = j
            continue
        i += 1
    return None


def read_archived_summary(archive_dir):
    """归档后 proposal.md 的真实解析路径读回 — 驱动全部 SC-10 断言, 且顺带
    实跑两个既有生产消费者 (_read_archive_type / _staleness_days) 证明其
    不被新增字段扰动 (SC-10 "既有消费者无扰"), 以及生产侧 declaration 解析器
    本身 (extract_runtime_probe) 证明 merge-append 后的混合 mapping 仍解析
    为合法声明 (SKILL.md :220-221 "向前兼容...不制造「声明无效」噪音")。"""
    d = Path(archive_dir)
    proposal = d / "proposal.md"
    text = proposal.read_text(encoding="utf-8")
    fm = _frontmatter_block(text)
    r = CollectorResult()
    archive_type = _openspec_mod._read_archive_type(d, r)
    staleness = _openspec_mod._staleness_days(proposal, text)
    return {
        "fm_present": fm is not None,
        "starts_at_absolute_start": text.startswith("---"),
        # 原始 frontmatter 块逐行 (R1 案例(i)/(ii) 用来断言"作者行逐字节原样
        # 保留" + "无重复顶层键" —— 比逐个新增专用 summary 字段更直接, 复用
        # 同一份已解析好的行列表)。
        "fm_body_lines": fm.splitlines() if fm is not None else None,
        "unverified_claims": parse_unverified_claims(fm) if fm is not None else None,
        "runtime_probe_result": parse_runtime_probe_result(fm) if fm is not None else None,
        "declaration_parse_status": extract_runtime_probe(fm)["status"] if fm is not None else None,
        "archive_type": archive_type,
        "soft_errors": r.errors,
        "staleness_days": staleness,
        "body_after_frontmatter": text[_FRONTMATTER_RE.match(text).end():]
        if _FRONTMATTER_RE.match(text) else None,
    }


if __name__ == "__main__":
    _cmd = sys.argv[1]
    if _cmd == "write":
        write_warn_overlay(sys.argv[2], sys.argv[3])
    elif _cmd == "read":
        print(json.dumps(read_archived_summary(sys.argv[2])))
    else:
        raise SystemExit(f"unknown e2e_probe_lib cmd: {_cmd}")
PYLIB

probe_ts(){ # $1 = days_ago (float ok)
  python3 -c "from datetime import datetime,timezone,timedelta; print((datetime.now(timezone.utc)-timedelta(days=$1)).strftime('%Y-%m-%dT%H:%M:%SZ'))"
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
# precedent 修正 (TASK-016 顺带修复): 旧版此处以 'unverified_claims: %d' 计数形式写入 + 裸 grep
# 断言存在, 偏离 SKILL.md :195-199 的 list-of-object 契约 (claim/reason/symbols 逐条 YAML list
# item)。改用上方共享 helper 按契约真写入, 断言改走 _frontmatter_block() 真实解析路径 (非裸
# grep, 防插错位假阳), 并顺带验证「无既有块 → 文件绝对起始插入, 原内容完整下移」— 本 fixture 的
# proposal.md 本就不含既有 frontmatter, 天然覆盖该分支 (TASK-016 verification bullet 1 的
# "无既有块时验证块插入文件绝对起始" 由本节 + 下方 §6 正控合力覆盖: 本节覆盖"无既有块"分支,
# §6 覆盖 runtime_probe 结果键本身的落盘正确性)。
mkdir -p "$TMP/warnspec"
printf '# Proposal: tmp-warn\n> **Status**: Approved\n## Success Criteria\n- [ ] x\n' > "$TMP/warnspec/proposal.md"
printf '# Tasks\n- [x] 1.1 dogfood 验证已完成\n' > "$TMP/warnspec/tasks.md"
cp "$TMP/warnspec/proposal.md" "$TMP/warnspec/proposal.md.orig"
gate "$TMP/warnspec"
if [ "$VERDICT" = warn ]; then
  python3 "$E2ELIB" write "$TMP/warnspec/proposal.md" "$GATE_JSON"

  NEW_WARNSPEC_TEXT="$(cat "$TMP/warnspec/proposal.md")"
  case "$NEW_WARNSPEC_TEXT" in
    ---*) ok "无既有块 → 新块插入文件绝对起始" ;;
    *) bad "新块未插入绝对起始 (首字符非 ---)" ;;
  esac

  python3 -c "
import sys
new = open('$TMP/warnspec/proposal.md', encoding='utf-8').read()
orig = open('$TMP/warnspec/proposal.md.orig', encoding='utf-8').read()
sys.exit(0 if new.endswith(orig) else 1)
"
  [ $? -eq 0 ] && ok "原内容完整下移保留 (byte-for-byte 后缀)" || bad "原内容被截断/覆盖"

  UC_SUMMARY="$(python3 <<'PY'
import json, os, sys
sys.path.insert(0, os.environ["SS_TMP_DIR"])
from e2e_probe_lib import _frontmatter_block, parse_unverified_claims
text = open(os.path.join(os.environ["SS_TMP_DIR"], "warnspec", "proposal.md"), encoding="utf-8").read()
fm = _frontmatter_block(text)
print(json.dumps({"fm_present": fm is not None, "claims": parse_unverified_claims(fm) if fm is not None else None}))
PY
)"
  FM_PRESENT="$(printf '%s' "$UC_SUMMARY" | python3 -c 'import sys,json;print(json.load(sys.stdin)["fm_present"])')"
  [ "$FM_PRESENT" = True ] && ok "_frontmatter_block() 真实解析路径确认块存在" || bad "_frontmatter_block() 解析失败"
  UC_LEN="$(printf '%s' "$UC_SUMMARY" | python3 -c 'import sys,json;print(len(json.load(sys.stdin)["claims"] or []))')"
  UC_HAS_DOGFOOD="$(printf '%s' "$UC_SUMMARY" | python3 -c 'import sys,json;d=json.load(sys.stdin)["claims"] or [];print(any("dogfood" in c["claim"] for c in d))')"
  [ "$UC_LEN" = "1" ] && [ "$UC_HAS_DOGFOOD" = True ] && ok "真实解析路径确认 unverified_claims list-of-object 契约格式" || bad "list-of-object 解析异常: len=$UC_LEN has_dogfood=$UC_HAS_DOGFOOD"
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

# =============================================================================
# §6-9: runtime-probe-archive-gate-integration TASK-016 (#95 follow-up A, SC-10)
# 持久化 E2E — 首次在连续 Step1-2 归档流程中按契约行使 runtime_probe warn_overlay
# 写入路径。每个 fixture 独立 project root ($TMP/e2e-*), 走: Step1 (--gate 取
# JSON) → [仅 verdict==warn 时] Step2 (write_warn_overlay 按契约写) → 移入模拟
# archive/ 目录 → read_archived_summary() 真实解析路径核验。
# =============================================================================

echo "== 6. SC-10 正控: runtime_probe warn 折入 + merge-append 落盘 (首次连续 Step1-2 流程) =="
POS_ROOT="$TMP/e2e-pos"
POS_SPEC="$POS_ROOT/openspec/changes/probe-e2e-positive"
mkdir -p "$POS_SPEC" "$POS_ROOT/.aria"
# 声明四字段全部具名 (partition/symbol/max_age_days/enabled_when) —— merge-append 规则要求
# "作者声明字段无一丢失/无一被改", 四字段齐全才能把这条断言钉扎实; enabled_when 指向的开关
# 显式置真 (.aria/config.json), 使其"落入 partition 探测分支"而不误变成 skipped, 不干扰
# warn-outcome 的正控设计意图。
# updated-at 当场写入 (R1 [qa M-f4] _staleness_days 断言强化): 取本次跑测的
# "现在" (probe_ts 0, 而非硬编码日历日期 — 与文件其余时间戳同一"相对当前时间
# 生成"手法), 使下方 staleness_days 断言能从"非负整数"这种宽松形状检查收紧到
# 精确 `assertEqual 0` —— 顶层 0-indent 兄弟键, 在 runtime_probe: 块 dedent
# 边界之外, 不进入 merge-append 消费范围 (不扰动声明 4 字段/结果 3 字段断言)。
POS_UPDATED_AT="$(probe_ts 0)"
printf -- '---\nruntime_probe:\n  partition: .aria/probe-telemetry.jsonl\n  symbol: e2e_pos_symbol\n  max_age_days: 10\n  enabled_when: e2e.pos_switch\nupdated-at: %s\n---\n\n# probe-e2e-positive\n\n> **Status**: Approved\n\n## Why\ntest\n' "$POS_UPDATED_AT" > "$POS_SPEC/proposal.md"
printf '# Tasks\n\n- [x] task one\n- [x] task two\n' > "$POS_SPEC/tasks.md"
printf '{"e2e": {"pos_switch": true}}' > "$POS_ROOT/.aria/config.json"
# warn 形态: 全陈旧 (窗口 10d 外的唯一一条 production 记录, 20d 前)
printf '{"ts": "%s", "source": "production"}\n' "$(probe_ts 20)" > "$POS_ROOT/.aria/probe-telemetry.jsonl"

gate "$POS_SPEC"
[ "$VERDICT" = warn ] && ok "正控 Step1 verdict=warn (全陈旧探针 + 无其它声称)" || bad "正控 Step1 verdict=$VERDICT (期望 warn)"

if [ "$VERDICT" = warn ]; then
  python3 "$E2ELIB" write "$POS_SPEC/proposal.md" "$GATE_JSON"
fi
POS_ARCHIVE="$POS_ROOT/openspec/archive/2026-07-08-probe-e2e-positive"
mkdir -p "$POS_ROOT/openspec/archive"
mv "$POS_SPEC" "$POS_ARCHIVE"
POS_SUMMARY="$(python3 "$E2ELIB" read "$POS_ARCHIVE")"

RP_OUTCOME="$(printf '%s' "$POS_SUMMARY" | python3 -c 'import sys,json;d=json.load(sys.stdin)["runtime_probe_result"];print(d["outcome"] if d else "ABSENT")')"
[ "$RP_OUTCOME" = "warn" ] && ok "正控: runtime_probe.outcome=warn 真落盘归档后 frontmatter" || bad "正控: runtime_probe outcome got=$RP_OUTCOME"

# merge-append 规则核心断言: 归档后 mapping 同时含声明 4 字段原样 (partition/symbol/
# max_age_days/enabled_when, 值逐一比对不变) + 结果 3 字段 (outcome/count/ts) —— 无遗漏
# 无篡改, 字段集恰为二者并集 (无第三方杂项、无重复 symbol)。
DECL_PRESERVED="$(printf '%s' "$POS_SUMMARY" | python3 -c '
import sys, json
d = json.load(sys.stdin)["runtime_probe_result"] or {}
expected_decl = {
    "partition": ".aria/probe-telemetry.jsonl",
    "symbol": "e2e_pos_symbol",
    "max_age_days": 10,
    "enabled_when": "e2e.pos_switch",
}
print(all(d.get(k) == v for k, v in expected_decl.items()))
')"
[ "$DECL_PRESERVED" = True ] && ok "正控: 作者声明 4 字段原样保留 (无一丢失/无一被改)" || bad "正控: 声明字段被扰动: $POS_SUMMARY"

RP_KEYS="$(printf '%s' "$POS_SUMMARY" | python3 -c 'import sys,json;d=json.load(sys.stdin)["runtime_probe_result"] or {};print(sorted(d.keys()))')"
EXPECT_KEYS="['count', 'enabled_when', 'max_age_days', 'outcome', 'partition', 'symbol', 'ts']"
[ "$RP_KEYS" = "$EXPECT_KEYS" ] && ok "正控: mapping 字段集恰为声明∪结果 (无重复 symbol, 无 reason, 无杂项)" || bad "正控: 字段集异常: got=$RP_KEYS want=$EXPECT_KEYS"

RP_COUNT="$(printf '%s' "$POS_SUMMARY" | python3 -c 'import sys,json;d=json.load(sys.stdin)["runtime_probe_result"];print(d["count"])')"
[ "$RP_COUNT" = "0" ] && ok "正控: 结果字段 count=0 真落盘" || bad "正控: count got=$RP_COUNT"
RP_TS_OK="$(printf '%s' "$POS_SUMMARY" | python3 -c 'import sys,json,datetime;d=json.load(sys.stdin)["runtime_probe_result"];datetime.datetime.fromisoformat(d["ts"]);print(True)' 2>/dev/null)"
[ "$RP_TS_OK" = True ] && ok "正控: 结果字段 ts 为合法 ISO-8601 (真落盘)" || bad "正控: ts 不可解析"

DECL_STATUS="$(printf '%s' "$POS_SUMMARY" | python3 -c 'import sys,json;print(json.load(sys.stdin)["declaration_parse_status"])')"
[ "$DECL_STATUS" = ok ] && ok "正控: extract_runtime_probe() 对归档后混合 mapping 仍判 status=ok (向前兼容, 不制造声明无效噪音)" || bad "正控: declaration_parse_status got=$DECL_STATUS (期望 ok)"

UC_HAS_PROBE="$(printf '%s' "$POS_SUMMARY" | python3 -c 'import sys,json;d=json.load(sys.stdin)["unverified_claims"] or [];print(any(c["claim"]=="runtime_probe:e2e_pos_symbol" for c in d))')"
[ "$UC_HAS_PROBE" = True ] && ok "正控: probe-warn 条目在 unverified_claims 同批, list-of-object 契约格式" || bad "正控: unverified_claims 缺 probe-warn 条目"

DPAYLOAD_HAS="$(printf '%s' "$GATE_JSON" | python3 -c 'import sys,json;d=json.load(sys.stdin);p=d.get("d_payload") or {};print(any(c["claim"]=="runtime_probe:e2e_pos_symbol" for c in p.get("unverified_claims",[])))')"
[ "$DPAYLOAD_HAS" = True ] && ok "正控: d_payload 含该 probe-warn 条目 (D 兜底通路核验)" || bad "正控: d_payload 缺该条目"

ARCHTYPE="$(printf '%s' "$POS_SUMMARY" | python3 -c 'import sys,json;print(json.load(sys.stdin)["archive_type"])')"
SOFTERR="$(printf '%s' "$POS_SUMMARY" | python3 -c 'import sys,json;print(json.load(sys.stdin)["soft_errors"])')"
[ "$ARCHTYPE" = None ] && [ "$SOFTERR" = "[]" ] && ok "正控: _read_archive_type() 既有消费者无扰 (None, 零 soft_error)" || bad "正控: _read_archive_type 受扰: archive_type=$ARCHTYPE soft_errors=$SOFTERR"

# R1 [qa M-f4] 断言强化: fixture 的 updated-at 当场写入 (probe_ts 0, 即"现在"),
# 精确期望 staleness_days==0 —— 从"非负整数"这种任何值都能蒙混过关的宽松形状
# 检查, 收紧到 assertEqual 0 语义 (与 unittest assertEqual 同一严格度), 同时
# 顺带实证 _UPDATED_AT_FIELD_RE 真读到了这个新增顶层字段 (而非巧合落在 mtime
# 兜底分支上 — mtime 兜底同样会给出 0, 但不能证明 updated-at 解析路径本身
# 工作正常)。
STALENESS="$(printf '%s' "$POS_SUMMARY" | python3 -c 'import sys,json;print(json.load(sys.stdin)["staleness_days"])')"
[ "$STALENESS" = "0" ] && ok "正控: _staleness_days() 既有消费者无扰 (fixture updated-at 当场写入 → 精确 staleness_days=0)" || bad "正控: _staleness_days() got=$STALENESS (期望精确 0)"

echo "== 7. SC-10 负控(a): pass-outcome fixture 同流程 → 归档 frontmatter 无 runtime_probe 键 =="
A_ROOT="$TMP/e2e-negA"
A_SPEC="$A_ROOT/openspec/changes/probe-e2e-negA"
mkdir -p "$A_SPEC" "$A_ROOT/.aria"
printf -- '---\nruntime_probe:\n  partition: .aria/probe-telemetry.jsonl\n  symbol: e2e_negA_symbol\n---\n\n# probe-e2e-negA\n\n> **Status**: Approved\n\n## Why\ntest\n' > "$A_SPEC/proposal.md"
printf '# Tasks\n\n- [x] task one\n- [x] task two\n' > "$A_SPEC/tasks.md"
printf '{"ts": "%s", "source": "production"}\n' "$(probe_ts 1)" > "$A_ROOT/.aria/probe-telemetry.jsonl"

gate "$A_SPEC"
[ "$VERDICT" = pass ] && ok "负控(a) Step1 verdict=pass (窗口内新鲜记录)" || bad "负控(a) Step1 verdict=$VERDICT (期望 pass)"
if [ "$VERDICT" = warn ]; then python3 "$E2ELIB" write "$A_SPEC/proposal.md" "$GATE_JSON"; fi  # 触发条件不成立, 不应执行
A_ARCHIVE="$A_ROOT/openspec/archive/2026-07-08-probe-e2e-negA"
mkdir -p "$A_ROOT/openspec/archive"
mv "$A_SPEC" "$A_ARCHIVE"
A_SUMMARY="$(python3 "$E2ELIB" read "$A_ARCHIVE")"
A_RP="$(printf '%s' "$A_SUMMARY" | python3 -c 'import sys,json;print(json.load(sys.stdin)["runtime_probe_result"])')"
[ "$A_RP" = "None" ] && ok "负控(a): 归档 frontmatter 无 runtime_probe 键 (pass 不落盘)" || bad "负控(a): runtime_probe 键异常出现: $A_RP"

echo "== 8. SC-10 负控(b)/(b'): 混合场景 (probe∈{pass,skipped} ∧ 无关声称=warn) → unverified_claims 写入但 runtime_probe 键缺席 =="
# (b): probe=pass ∧ 无关 dogfood 声称 → verdict=warn (来源与探针无关)
B_ROOT="$TMP/e2e-negB"
B_SPEC="$B_ROOT/openspec/changes/probe-e2e-negB"
mkdir -p "$B_SPEC" "$B_ROOT/.aria"
printf -- '---\nruntime_probe:\n  partition: .aria/probe-telemetry.jsonl\n  symbol: e2e_negB_symbol\n---\n\n# probe-e2e-negB\n\n> **Status**: Approved\n\n## Why\ntest\n' > "$B_SPEC/proposal.md"
printf '# Tasks\n\n- [x] 6.1 dogfood 验证: 承载 ≥1 真实场景跑通 (无可链接产物路径)\n' > "$B_SPEC/tasks.md"
printf '{"ts": "%s", "source": "production"}\n' "$(probe_ts 1)" > "$B_ROOT/.aria/probe-telemetry.jsonl"

gate "$B_SPEC"
[ "$VERDICT" = warn ] && ok "负控(b) Step1 verdict=warn (由无关 dogfood 声称触发)" || bad "负控(b) Step1 verdict=$VERDICT (期望 warn)"
B_PROBE_MEM="$(printf '%s' "$GATE_JSON" | python3 -c 'import sys,json;print(json.load(sys.stdin)["runtime_probe"]["outcome"])')"
[ "$B_PROBE_MEM" = pass ] && ok "负控(b): 探针自身 outcome=pass (内存态, 与门级 verdict 来源无关)" || bad "负控(b): 探针 outcome got=$B_PROBE_MEM"
if [ "$VERDICT" = warn ]; then python3 "$E2ELIB" write "$B_SPEC/proposal.md" "$GATE_JSON"; fi
B_ARCHIVE="$B_ROOT/openspec/archive/2026-07-08-probe-e2e-negB"
mkdir -p "$B_ROOT/openspec/archive"
mv "$B_SPEC" "$B_ARCHIVE"
B_SUMMARY="$(python3 "$E2ELIB" read "$B_ARCHIVE")"
B_RP="$(printf '%s' "$B_SUMMARY" | python3 -c 'import sys,json;print(json.load(sys.stdin)["runtime_probe_result"])')"
[ "$B_RP" = "None" ] && ok "负控(b): runtime_probe 键缺席 (内容归属随探针自身 outcome, 非门级 verdict 来源)" || bad "负控(b): runtime_probe 键异常出现: $B_RP"
B_UC_DOGFOOD="$(printf '%s' "$B_SUMMARY" | python3 -c 'import sys,json;d=json.load(sys.stdin)["unverified_claims"] or [];print(any("dogfood" in c["claim"] for c in d))')"
[ "$B_UC_DOGFOOD" = True ] && ok "负控(b): unverified_claims 正常写入 dogfood 条目" || bad "负控(b): unverified_claims 缺 dogfood 条目"

# (b'): probe=skipped (enabled_when 声明但 .aria/config.json 缺失 → skipped) ∧ 无关 dogfood 声称 → verdict=warn
BP_ROOT="$TMP/e2e-negBp"
BP_SPEC="$BP_ROOT/openspec/changes/probe-e2e-negBp"
mkdir -p "$BP_SPEC"
printf -- '---\nruntime_probe:\n  partition: .aria/probe-telemetry.jsonl\n  symbol: e2e_negBp_symbol\n  enabled_when: some.switch.off\n---\n\n# probe-e2e-negBp\n\n> **Status**: Approved\n\n## Why\ntest\n' > "$BP_SPEC/proposal.md"
printf '# Tasks\n\n- [x] 6.1 dogfood 验证: 承载 ≥1 真实场景跑通 (无可链接产物路径)\n' > "$BP_SPEC/tasks.md"
# 有意不建 .aria/config.json → config 缺失 → skipped (非 warn, "低调 note")

gate "$BP_SPEC"
[ "$VERDICT" = warn ] && ok "负控(b') Step1 verdict=warn (由无关 dogfood 声称触发)" || bad "负控(b') Step1 verdict=$VERDICT (期望 warn)"
BP_PROBE_MEM="$(printf '%s' "$GATE_JSON" | python3 -c 'import sys,json;print(json.load(sys.stdin)["runtime_probe"]["outcome"])')"
[ "$BP_PROBE_MEM" = skipped ] && ok "负控(b'): 探针自身 outcome=skipped (内存态, config 缺失保守判定)" || bad "负控(b'): 探针 outcome got=$BP_PROBE_MEM"
if [ "$VERDICT" = warn ]; then python3 "$E2ELIB" write "$BP_SPEC/proposal.md" "$GATE_JSON"; fi
BP_ARCHIVE="$BP_ROOT/openspec/archive/2026-07-08-probe-e2e-negBp"
mkdir -p "$BP_ROOT/openspec/archive"
mv "$BP_SPEC" "$BP_ARCHIVE"
BP_SUMMARY="$(python3 "$E2ELIB" read "$BP_ARCHIVE")"
BP_RP="$(printf '%s' "$BP_SUMMARY" | python3 -c 'import sys,json;print(json.load(sys.stdin)["runtime_probe_result"])')"
[ "$BP_RP" = "None" ] && ok "负控(b'): runtime_probe 键缺席 (skipped 同构负控)" || bad "负控(b'): runtime_probe 键异常出现: $BP_RP"
BP_UC_DOGFOOD="$(printf '%s' "$BP_SUMMARY" | python3 -c 'import sys,json;d=json.load(sys.stdin)["unverified_claims"] or [];print(any("dogfood" in c["claim"] for c in d))')"
[ "$BP_UC_DOGFOOD" = True ] && ok "负控(b'): unverified_claims 正常写入 dogfood 条目" || bad "负控(b'): unverified_claims 缺 dogfood 条目"

echo "== 9. SC-10 负控(c'): 声明无效 flavor E2E → merge-append 落盘 outcome=invalid + unverified_claims 同批 =="
C_ROOT="$TMP/e2e-negC"
C_SPEC="$C_ROOT/openspec/changes/probe-e2e-negC"
mkdir -p "$C_SPEC"
printf -- '---\nruntime_probe:\n  symbol: e2e_negC_symbol\n---\n\n# probe-e2e-negC\n\n> **Status**: Approved\n\n## Why\ntest\n' > "$C_SPEC/proposal.md"  # 缺必填 partition → 值层声明无效
printf '# Tasks\n\n- [x] task one\n- [x] task two\n' > "$C_SPEC/tasks.md"

gate "$C_SPEC"
[ "$VERDICT" = warn ] && ok "负控(c') Step1 verdict=warn (声明无效自身致 warn, 无需额外无关声称)" || bad "负控(c') Step1 verdict=$VERDICT (期望 warn)"
if [ "$VERDICT" = warn ]; then python3 "$E2ELIB" write "$C_SPEC/proposal.md" "$GATE_JSON"; fi
C_ARCHIVE="$C_ROOT/openspec/archive/2026-07-08-probe-e2e-negC"
mkdir -p "$C_ROOT/openspec/archive"
mv "$C_SPEC" "$C_ARCHIVE"
C_SUMMARY="$(python3 "$E2ELIB" read "$C_ARCHIVE")"
C_RP_OUTCOME="$(printf '%s' "$C_SUMMARY" | python3 -c 'import sys,json;d=json.load(sys.stdin)["runtime_probe_result"];print(d["outcome"] if d else "ABSENT")')"
[ "$C_RP_OUTCOME" = "invalid" ] && ok "负控(c'): runtime_probe.outcome=invalid 真落盘" || bad "负控(c'): runtime_probe outcome got=$C_RP_OUTCOME"
# merge-append: 声明唯一字段 symbol 已由作者携带 → 结果不重复补写 symbol; mapping 恰为
# {symbol (声明, 原样) , outcome/count/ts (结果)} —— 无重复键、无遗漏。
C_SYMBOL_PRESERVED="$(printf '%s' "$C_SUMMARY" | python3 -c 'import sys,json;d=json.load(sys.stdin)["runtime_probe_result"] or {};print(d.get("symbol")=="e2e_negC_symbol")')"
[ "$C_SYMBOL_PRESERVED" = True ] && ok "负控(c'): 作者声明字段 symbol 原样保留 (无一被改)" || bad "负控(c'): symbol 被扰动: $C_SUMMARY"
C_RP_KEYS="$(printf '%s' "$C_SUMMARY" | python3 -c 'import sys,json;d=json.load(sys.stdin)["runtime_probe_result"] or {};print(sorted(d.keys()))')"
[ "$C_RP_KEYS" = "['count', 'outcome', 'symbol', 'ts']" ] && ok "负控(c'): mapping 字段集恰为声明∪结果 (symbol 未被重复补写)" || bad "负控(c'): 字段集异常: $C_RP_KEYS"
C_DECL_STATUS="$(printf '%s' "$C_SUMMARY" | python3 -c 'import sys,json;print(json.load(sys.stdin)["declaration_parse_status"])')"
[ "$C_DECL_STATUS" = ok ] && ok "负控(c'): extract_runtime_probe() 对归档后混合 mapping 仍判 status=ok (向前兼容)" || bad "负控(c'): declaration_parse_status got=$C_DECL_STATUS (期望 ok)"
C_UC_HAS="$(printf '%s' "$C_SUMMARY" | python3 -c 'import sys,json;d=json.load(sys.stdin)["unverified_claims"] or [];print(any(c["claim"]=="runtime_probe:e2e_negC_symbol" for c in d))')"
[ "$C_UC_HAS" = True ] && ok "负控(c'): unverified_claims 同批含该条目" || bad "负控(c'): unverified_claims 缺该条目"

echo "== 9b. SC-10 负控(c') 补充: 声明无效且缺 symbol → merge-append 补写 probe 返回的 symbol =="
# 文本层拒绝形态 (enabled_when 用 flow-style mapping, 沿用 test_runtime_probe.py/
# test_spec_complete.py 已锁定的同一拒绝形态) —— 整个声明解析失败, symbol 未知
# (parsed["fields"] 不存在), gate_result.runtime_probe.symbol=="" —— 直接验证 SKILL.md
# "同名键 merge-append 规则" 的另一半: "声明无效缺 symbol 时补写 probe 返回的 symbol"。
C2_ROOT="$TMP/e2e-negC2"
C2_SPEC="$C2_ROOT/openspec/changes/probe-e2e-negC2"
mkdir -p "$C2_SPEC"
printf -- '---\nruntime_probe:\n  partition: .aria/probe-telemetry.jsonl\n  enabled_when: {a: b}\n---\n\n# probe-e2e-negC2\n\n> **Status**: Approved\n\n## Why\ntest\n' > "$C2_SPEC/proposal.md"
printf '# Tasks\n\n- [x] task one\n- [x] task two\n' > "$C2_SPEC/tasks.md"

gate "$C2_SPEC"
[ "$VERDICT" = warn ] && ok "负控(c') 补充 Step1 verdict=warn (文本层声明无效自身致 warn)" || bad "负控(c') 补充 Step1 verdict=$VERDICT (期望 warn)"
C2_PROBE_SYMBOL_MEM="$(printf '%s' "$GATE_JSON" | python3 -c 'import sys,json;print(repr(json.load(sys.stdin)["runtime_probe"]["symbol"]))')"
[ "$C2_PROBE_SYMBOL_MEM" = "''" ] && ok "负控(c') 补充: 探针内存态 symbol 确为空字符串 (文本层无效, 符号未知)" || bad "负控(c') 补充: 探针 symbol got=$C2_PROBE_SYMBOL_MEM (期望 '')"
if [ "$VERDICT" = warn ]; then python3 "$E2ELIB" write "$C2_SPEC/proposal.md" "$GATE_JSON"; fi
C2_ARCHIVE="$C2_ROOT/openspec/archive/2026-07-08-probe-e2e-negC2"
mkdir -p "$C2_ROOT/openspec/archive"
mv "$C2_SPEC" "$C2_ARCHIVE"
C2_SUMMARY="$(python3 "$E2ELIB" read "$C2_ARCHIVE")"
C2_DECL_PRESERVED="$(printf '%s' "$C2_SUMMARY" | python3 -c '
import sys, json
d = json.load(sys.stdin)["runtime_probe_result"] or {}
print(d.get("partition") == ".aria/probe-telemetry.jsonl" and d.get("enabled_when") == "{a: b}")
')"
[ "$C2_DECL_PRESERVED" = True ] && ok "负控(c') 补充: 作者声明字段 partition/enabled_when 原样保留 (无一被改)" || bad "负控(c') 补充: 声明字段被扰动: $C2_SUMMARY"
C2_SYMBOL_SUPPLEMENTED="$(printf '%s' "$C2_SUMMARY" | python3 -c 'import sys,json;d=json.load(sys.stdin)["runtime_probe_result"] or {};print(d.get("symbol")=="")')"
[ "$C2_SYMBOL_SUPPLEMENTED" = True ] && ok "负控(c') 补充: 声明缺 symbol → merge-append 补写 probe 返回的 symbol (空串)" || bad "负控(c') 补充: symbol 补写异常"
C2_RP_KEYS="$(printf '%s' "$C2_SUMMARY" | python3 -c 'import sys,json;d=json.load(sys.stdin)["runtime_probe_result"] or {};print(sorted(d.keys()))')"
[ "$C2_RP_KEYS" = "['count', 'enabled_when', 'outcome', 'partition', 'symbol', 'ts']" ] && ok "负控(c') 补充: mapping 字段集恰为声明∪结果 (含补写的 symbol)" || bad "负控(c') 补充: 字段集异常: $C2_RP_KEYS"

# =============================================================================
# §10-11: R1 pre-merge 修复轮新增 —— openspec-archive SKILL.md "runtime_probe
# 同名键 merge-append 规则" :221-227 新增「降级路径 (作者值非块 mapping)」条款的
# 首次 E2E 覆盖 ([SFH I-1 / TL F3] `_merge_append_runtime_probe` 顶键定位改产
# 等价语义, 见 e2e_probe_lib.py 内 `_merge_append_runtime_probe` docstring)。
# =============================================================================

echo "== 10. R1 新增(i): 顶层 flow-style 声明 (作者值非块 mapping) → 降级路径, 结果键不落盘, 作者行原样保留 =="
# 顶层 flow-style `runtime_probe: {...}` —— extract_runtime_probe 文本层判 invalid
# (reason=flow_style_mapping), 与 §9/§9b 的"子键 flow-style" (enabled_when: {a: b})
# 不同形状: 本例是**顶键行自身**携带非空值, merge-append 结构上不适用 (无"块"可 merge
# 进), 必须走降级路径 —— 保留作者行原样, 结果键不落盘, 不新起第二个同名顶层键。
D_ROOT="$TMP/e2e-negD"
D_SPEC="$D_ROOT/openspec/changes/probe-e2e-negD"
mkdir -p "$D_SPEC"
D_DECL_LINE='runtime_probe: {partition: x}'
printf -- '---\n%s\n---\n\n# probe-e2e-negD\n\n> **Status**: Approved\n\n## Why\ntest\n' "$D_DECL_LINE" > "$D_SPEC/proposal.md"
printf '# Tasks\n\n- [x] task one\n- [x] task two\n' > "$D_SPEC/tasks.md"

gate "$D_SPEC"
[ "$VERDICT" = warn ] && ok "R1(i) Step1 verdict=warn (顶层 flow-style 声明文本层无效自身致 warn)" || bad "R1(i) Step1 verdict=$VERDICT (期望 warn)"
D_PROBE_OUTCOME_MEM="$(printf '%s' "$GATE_JSON" | python3 -c 'import sys,json;print(json.load(sys.stdin)["runtime_probe"]["outcome"])')"
[ "$D_PROBE_OUTCOME_MEM" = invalid ] && ok "R1(i): 探针内存态 outcome=invalid (文本层拒绝)" || bad "R1(i): 探针 outcome got=$D_PROBE_OUTCOME_MEM (期望 invalid)"
if [ "$VERDICT" = warn ]; then python3 "$E2ELIB" write "$D_SPEC/proposal.md" "$GATE_JSON"; fi
D_ARCHIVE="$D_ROOT/openspec/archive/2026-07-08-probe-e2e-negD"
mkdir -p "$D_ROOT/openspec/archive"
mv "$D_SPEC" "$D_ARCHIVE"
D_SUMMARY="$(python3 "$E2ELIB" read "$D_ARCHIVE")"

D_ASSERT="$(printf '%s' "$D_SUMMARY" | python3 -c '
import sys, json
d = json.load(sys.stdin)
lines = d["fm_body_lines"] or []
top_lines = [l for l in lines if l.startswith("runtime_probe:")]
print(json.dumps({
    "line_preserved": "runtime_probe: {partition: x}" in lines,
    "top_key_count": len(top_lines),
}))
')"
D_LINE_PRESERVED="$(printf '%s' "$D_ASSERT" | python3 -c 'import sys,json;print(json.load(sys.stdin)["line_preserved"])')"
[ "$D_LINE_PRESERVED" = True ] && ok "R1(i): 作者行逐字节原样保留 (降级路径不改写作者行)" || bad "R1(i): 作者行被改写: $D_SUMMARY"

D_TOPKEY_COUNT="$(printf '%s' "$D_ASSERT" | python3 -c 'import sys,json;print(json.load(sys.stdin)["top_key_count"])')"
[ "$D_TOPKEY_COUNT" = "1" ] && ok "R1(i): 无重复顶层键 (恰一行 runtime_probe: 前缀, 未静默追加第二个)" || bad "R1(i): 顶层键计数异常: $D_TOPKEY_COUNT"

D_RP_RESULT="$(printf '%s' "$D_SUMMARY" | python3 -c 'import sys,json;print(json.load(sys.stdin)["runtime_probe_result"])')"
[ "$D_RP_RESULT" = "None" ] && ok "R1(i): 无 runtime_probe 结果键 (降级路径, 结果不落盘)" || bad "R1(i): runtime_probe 结果键异常出现: $D_RP_RESULT"

D_UC_HAS_INVALID="$(printf '%s' "$D_SUMMARY" | python3 -c 'import sys,json;d=json.load(sys.stdin)["unverified_claims"] or [];print(any(c["claim"]=="runtime_probe" and "flow_style_mapping" in c["reason"] for c in d))')"
[ "$D_UC_HAS_INVALID" = True ] && ok "R1(i): unverified_claims 含 invalid 条目 (claim=runtime_probe 裸标签, reason 含 flow_style_mapping)" || bad "R1(i): unverified_claims 缺 invalid 条目: $D_SUMMARY"

D_DECL_STATUS="$(printf '%s' "$D_SUMMARY" | python3 -c 'import sys,json;print(json.load(sys.stdin)["declaration_parse_status"])')"
[ "$D_DECL_STATUS" = invalid ] && ok "R1(i): extract_runtime_probe() 对归档后原样声明仍判 status=invalid (降级路径未改写语义)" || bad "R1(i): declaration_parse_status got=$D_DECL_STATUS (期望 invalid)"

echo "== 11. R1 新增(ii): 顶键行带行尾注释 (合法声明) + warn 分区 → merge-append 正常工作 (声明∪结果单一 mapping) =="
# 与 §6 POS 正控同一 partition/config 设计 (全陈旧探针 → warn), 唯一变量是顶键行带
# 行尾注释 `runtime_probe:   # my probe` —— 生产解析器 (_TOP_KEY_RE/_strip_inline_
# comment) 判该行仍是合法裸块声明, merge-append 应正常工作: 声明字段保留 ∪ 结果
# 字段追加, 单一 mapping (不因注释误判块缺席而漏写结果, 也不因此另起一个块)。
E_ROOT="$TMP/e2e-negE"
E_SPEC="$E_ROOT/openspec/changes/probe-e2e-negE"
mkdir -p "$E_SPEC" "$E_ROOT/.aria"
E_TOP_LINE='runtime_probe:   # my probe'
printf -- '---\n%s\n  partition: .aria/probe-telemetry.jsonl\n  symbol: e2e_negE_symbol\n  max_age_days: 10\n  enabled_when: e2e.negE_switch\n---\n\n# probe-e2e-negE\n\n> **Status**: Approved\n\n## Why\ntest\n' "$E_TOP_LINE" > "$E_SPEC/proposal.md"
printf '# Tasks\n\n- [x] task one\n- [x] task two\n' > "$E_SPEC/tasks.md"
printf '{"e2e": {"negE_switch": true}}' > "$E_ROOT/.aria/config.json"
printf '{"ts": "%s", "source": "production"}\n' "$(probe_ts 20)" > "$E_ROOT/.aria/probe-telemetry.jsonl"

gate "$E_SPEC"
[ "$VERDICT" = warn ] && ok "R1(ii) Step1 verdict=warn (全陈旧探针, 顶键行注释不影响声明有效性)" || bad "R1(ii) Step1 verdict=$VERDICT (期望 warn)"
E_PROBE_OUTCOME_MEM="$(printf '%s' "$GATE_JSON" | python3 -c 'import sys,json;print(json.load(sys.stdin)["runtime_probe"]["outcome"])')"
[ "$E_PROBE_OUTCOME_MEM" = warn ] && ok "R1(ii): 探针内存态 outcome=warn (声明本身合法, 顶键行注释被生产解析器容忍)" || bad "R1(ii): 探针 outcome got=$E_PROBE_OUTCOME_MEM (期望 warn)"
if [ "$VERDICT" = warn ]; then python3 "$E2ELIB" write "$E_SPEC/proposal.md" "$GATE_JSON"; fi
E_ARCHIVE="$E_ROOT/openspec/archive/2026-07-08-probe-e2e-negE"
mkdir -p "$E_ROOT/openspec/archive"
mv "$E_SPEC" "$E_ARCHIVE"
E_SUMMARY="$(python3 "$E2ELIB" read "$E_ARCHIVE")"

E_RP_OUTCOME="$(printf '%s' "$E_SUMMARY" | python3 -c 'import sys,json;d=json.load(sys.stdin)["runtime_probe_result"];print(d["outcome"] if d else "ABSENT")')"
[ "$E_RP_OUTCOME" = "warn" ] && ok "R1(ii): merge-append 成功 — runtime_probe.outcome=warn 落盘 (顶键行注释未致误判块缺席)" || bad "R1(ii): runtime_probe outcome got=$E_RP_OUTCOME"

E_DECL_PRESERVED="$(printf '%s' "$E_SUMMARY" | python3 -c '
import sys, json
d = json.load(sys.stdin)["runtime_probe_result"] or {}
expected_decl = {
    "partition": ".aria/probe-telemetry.jsonl",
    "symbol": "e2e_negE_symbol",
    "max_age_days": 10,
    "enabled_when": "e2e.negE_switch",
}
print(all(d.get(k) == v for k, v in expected_decl.items()))
')"
[ "$E_DECL_PRESERVED" = True ] && ok "R1(ii): 声明字段保留 (顶键行注释场景下 4 字段原样不丢)" || bad "R1(ii): 声明字段被扰动: $E_SUMMARY"

E_RP_KEYS="$(printf '%s' "$E_SUMMARY" | python3 -c 'import sys,json;d=json.load(sys.stdin)["runtime_probe_result"] or {};print(sorted(d.keys()))')"
EXPECT_E_KEYS="['count', 'enabled_when', 'max_age_days', 'outcome', 'partition', 'symbol', 'ts']"
[ "$E_RP_KEYS" = "$EXPECT_E_KEYS" ] && ok "R1(ii): 结果字段追加 ∪ 声明字段 = 单一 mapping (字段集恰为并集)" || bad "R1(ii): 字段集异常: got=$E_RP_KEYS want=$EXPECT_E_KEYS"

E_TOPKEY_COUNT="$(printf '%s' "$E_SUMMARY" | python3 -c 'import sys,json;lines=json.load(sys.stdin)["fm_body_lines"] or [];print(sum(1 for l in lines if l.startswith("runtime_probe:")))')"
[ "$E_TOPKEY_COUNT" = "1" ] && ok "R1(ii): 单一 mapping (恰一个顶层 runtime_probe: 前缀行, 无重复键)" || bad "R1(ii): 顶层键计数异常: $E_TOPKEY_COUNT"

E_TOP_LINE_PRESERVED="$(printf '%s' "$E_SUMMARY" | python3 -c 'import sys,json;lines=json.load(sys.stdin)["fm_body_lines"] or [];print("runtime_probe:   # my probe" in lines)')"
[ "$E_TOP_LINE_PRESERVED" = True ] && ok "R1(ii): 顶键行本身 (含尾随注释) 原样保留" || bad "R1(ii): 顶键行被改写: $E_SUMMARY"

E_DECL_STATUS="$(printf '%s' "$E_SUMMARY" | python3 -c 'import sys,json;print(json.load(sys.stdin)["declaration_parse_status"])')"
[ "$E_DECL_STATUS" = ok ] && ok "R1(ii): extract_runtime_probe() 对归档后混合 mapping 仍判 status=ok (顶键行注释不制造声明无效噪音)" || bad "R1(ii): declaration_parse_status got=$E_DECL_STATUS (期望 ok)"

echo
echo "== 结果: $PASS_CNT passed, $FAIL_CNT failed =="
[ "$FAIL_CNT" -eq 0 ]

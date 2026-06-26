---
name: session-closer
description: |
  会话收尾 —— 在任意对话(含未走完十步循环的探索/调试/讨论 session)把"未交接成果"
  固化为 handoff。**与十步循环正交平级的会话仪式**(非周期收尾): AI 先内省本对话出
  未完成线程 + 待固化经验, 再用机械 autofill 交叉核验补漏, 写 docs/handoff/。leaf —
  终结于写交接, 不拖入十步循环。

  使用场景: "对话收尾" / "执行对话收尾" / "会话收尾" / "session closeout" / "收尾这次对话"
  / "写交接" / "写 handoff" / "收工" / "结束本次对话" / context 快满时主动收尾。

  不适用 (用 phase-d-closer): "Phase D" / "周期收尾" / "归档 Spec" / "更新 cycle 进度"
  —— 那是开发周期收尾, 不是会话收尾。
disable-model-invocation: false
user-invocable: true
allowed-tools: Bash, Read, Edit, Write, Grep, Glob
---

# Session Closer — 会话收尾仪式

> **版本**: 1.0.0 | **定位**: 与十步循环**正交平级**的 leaf skill (会话维度, 非周期维度)
> **Spec**: session-closer-synthesis (DEC-20260625-001) | supersedes session-closeout-internalization

## 我应该用这个 Skill 吗？

**用 session-closer (会话收尾)**: 你想收尾**这次对话/session** —— 把未完成的、值得记的、
四维不一致的, 在结束前固化进 handoff。不要求走完一个 Spec; 探索/调试/讨论/半成品 session 都适用。

**用 phase-d-closer (周期收尾)**: 你刚走完一个开发 cycle (A→B→C), 要 D.1 更新 UPM 进度 /
D.2 归档 Spec —— 那是**周期产物归档**, 不是会话收尾。

> **心智边界**: 要总结的是**这次对话** → session-closer; 要归档的是**一个开发周期的产物** → phase-d-closer。
> 详见 [standards/conventions/session-handoff.md](../../../standards/conventions/session-handoff.md) §周期收尾 vs 会话收尾。

---

## 核心结构 (AD-1/AD-2)

```
owner: "对话收尾"  ──►  session-closer (leaf)
                          │
   ① AI 内省 (一等公民) ──┤  step1: 本对话未完成线程/待办
                          │  step2: 值得固化但未写下的经验
   ② 机械兜底 (backstop) ─┤  step0/3: handoff_autofill + consistency_check
                          │           交叉核验补漏 (snapshot 有但 AI 没提 → flag)
   ③ 写交接 ──────────────┤  step4: 按共享 handoff-write 机制写 docs/handoff/
                          │
   ④ 终结 (leaf) ─────────┘  不调 phase-a/b/c/d / workflow-runner / openspec-archive
```

**对话内省优先**: AI 先审视本对话 (一等公民), 机械 autofill 是**补漏 backstop** 不是承重。

---

## 执行流程

### step 1 — 内省: 未完成线程/待办 (AI, load-bearing)

审视**本对话**, 列出未闭合的线程: 未完成的任务、悬而未决的讨论、提了没做的 follow-up、
答应了没兑现的检查。这是 owner 5 步收尾 step 1 的核心 —— **读对话本身**, 非读 git 状态。

### step 2 — 内省: 待固化经验 (AI, load-bearing)

审视本对话识别**值得沉淀但还没写下**的经验 (踩的坑、有效的做法、非显然的决策理由)。
输出**必须含结构标记段** (AC-5b):

```
[候选 memory]
- <经验1 一句话 + 建议 type: feedback/project/reference>
[未写下经验]
- <还没固化的教训>
```

判定值得固化 → 写 Claude Code memory (`~/.claude/projects/*/memory/*.md` + MEMORY.md 索引)
或提议 standards 更新。**主动提炼**, 非仅枚举已写的文件。

### step 0/3 — 机械交叉核验补漏 (autofill + consistency, backstop)

跑 scan.py 取 snapshot (或读既有 `.aria/state-snapshot.json`), 然后:

```bash
# §7 同步 / §2 未完成 / §5 四维 机械汇编
python3 ${CLAUDE_PLUGIN_ROOT}/skills/session-closer/scripts/handoff_autofill.py \
  --snapshot-json .aria/state-snapshot.json --changes-dir openspec/changes
# 四维一致性 advisory flag
python3 ${CLAUDE_PLUGIN_ROOT}/skills/session-closer/scripts/consistency_check.py \
  --snapshot-json .aria/state-snapshot.json
```

- **step 0 (同步)**: `sync` 段填 §7; ahead>0/parity≠equal/不可达 → 告警 → **不静默收尾**, 提议 push。
- **step 3 (四维)**: `four_dim` + consistency flag 填 §5; 列"已做但未在 UPM/US/Spec/PRD 反映"。
- **补漏 (AC-3b)**: 把 step1 AI 内省结果喂 `cross_check_unfilled(ai_mentioned, mechanical_items)` →
  snapshot 有但 AI 没提的项 → 标「机械补漏」并入 §2 (兜底 AI 遗漏)。

第三方优雅降级: snapshot 缺 UPM/PRD/US 维 → 对应段跳过, 不报错 (缺维跳维)。

### step 4 — 写 handoff (按共享 SOT)

按 **既有共享 handoff-write 机制 SOT**
[phase-d-closer/references/handoff-mechanics.md](../phase-d-closer/references/handoff-mechanics.md)
(slug 规则 / 9 段模板 variable 字典 / latest.md 2 子步骤 / Rule #9 L1+L5 路径 enforcement /
Forbidden patterns) 写 `docs/handoff/{YYYY-MM-DD}-{slug}.md`。

模板: [aria/templates/session-handoff.md](../../templates/session-handoff.md) (9 段)。
§2 含 AI 内省 (load-bearing) + 机械补漏 flag; §5 含 consistency flag; §8 列新 memory。

### step 4.5 — leaf 终结 (AC-1b)

写完 handoff 即**终结**。**绝不**调 phase-a/b/c/d / workflow-runner / openspec-archive。
若 step 3 检出"有 shipped 但未归档的 cycle" → **仅输出一段纯文本 advisory 提议**
"检出未归档 cycle X, 可另行 `/phase-d-closer` 归档", **不发起任何 Task/skill 调用** (advisory-over-hardlock)。

---

## 与十步循环的关系

session-closer 是**叶子**, 不编排其他 phase。它消费 state-scanner 的 collector (snapshot)
+ 复用 phase-d-closer 的 handoff-write 机制 SOT, 但**不路由穿过 phase-d-closer**。

| | session-closer | phase-d-closer |
|---|---|---|
| 维度 | 会话 (session) | 开发周期 (cycle) |
| 触发 | 任意对话收尾 | 走完 A→B→C 后 |
| 输入域 | **对话内容** + snapshot | repo/spec 状态 |
| 动作 | 内省 + 写 handoff (leaf) | D.1 进度 + D.2 归档 + D.3 handoff |
| handoff-write | 引用共享 SOT | 引用同一共享 SOT |

---

## 相关文档

- [scripts/handoff_autofill.py](./scripts/handoff_autofill.py) — §7/§2/§5 机械汇编 + 补漏交叉核验
- [scripts/consistency_check.py](./scripts/consistency_check.py) — 四维 advisory 一致性 flag
- [scripts/closeout_trigger.py](./scripts/closeout_trigger.py) — context 压力 advisory nudge
- [phase-d-closer/references/handoff-mechanics.md](../phase-d-closer/references/handoff-mechanics.md) — **共享 handoff-write SOT**
- [standards/conventions/session-handoff.md](../../../standards/conventions/session-handoff.md) — Rule #9 + 周期vs会话收尾消歧

---

**最后更新**: 2026-06-25 (session-closer-synthesis DEC-20260625-001 — 独立 leaf skill + 复用既有 ref + 对话内省优先)
**Skill版本**: 1.0.0

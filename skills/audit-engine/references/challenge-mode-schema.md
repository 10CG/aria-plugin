# Challenge 模式数据 Schema (Challenge Mode Schema)

## 概述

Challenge 模式通过讨论组与挑战组的对抗式审计，引入"挑战者"视角，
发现 convergence 模式可能遗漏的风险和问题。

---

## 数据流总览

```
Round N:

  Step 1: 讨论组 spawn
          |
          v
  discussion_output
          |
          v
  Step 2: 挑战组 spawn (输入: discussion_output)
          |
          v
  challenge_output
          |
          v
  Step 3: 全员合并 (输入: discussion_output + challenge_output)
          |
          v
  revised_discussion_output
          |
          v
  Step 4: 挑战组再审 (输入: revised_discussion_output)
          |
          v
  updated_challenge_output
          |
          v
  Step 5: Drift Check (收敛判定前; drift-checker 独立调用,
          输入: anchor + revised_discussion_output.decisions
                        ∪ updated_challenge_output.objections)
          |
          v
  drift_metrics (drift_ratio → 三档处置)
          |
          v
  收敛判定
```

---

## discussion_output Schema

讨论组的统一提案输出:

```json
{
  "proposal": "string (统一提案文本)",
  "decisions": [
    {
      "id": "d-001",
      "severity": "critical | major | minor",
      "category": "architecture | implementation | testing | documentation",
      "scope": "affected module or file",
      "summary": "truncated to 50 words"
    }
  ],
  "rationale": [
    "理由 1: ...",
    "理由 2: ..."
  ]
}
```

### 字段说明

| 字段 | 说明 |
|------|------|
| proposal | 讨论组对被审计内容的综合评估文本 |
| decisions | 结构化决策/问题/风险列表, 复用结论记录格式 |
| rationale | 支撑决策的理由列表 |

---

## challenge_output Schema

挑战组的质疑输出:

```json
{
  "objections": [
    {
      "id": "obj-001",
      "agent": "qa-engineer",
      "target_decision": "d-001",
      "severity": "critical | major | minor",
      "point": "质疑内容 (详细说明为什么不同意)",
      "status": "new"
    }
  ]
}
```

### objection status 状态流转

```
new       → 初始状态, 挑战组提出时
resolved  → 讨论组在全员合并中接受并修正了提案
overruled → 挑战组在再审中撤回了质疑 (原决策正确)
```

### 收敛影响

- `new` → 阻塞收敛 (有未解决的反对意见)
- `resolved` → 不阻塞
- `overruled` → 不阻塞

---

## Round 内步骤详解

### Step 1: 讨论组提案

```yaml
输入:
  - context: 被审计内容 (proposal.md / diff / UPM)
  - round > 1 时追加: 上一轮 challenge_output (供参考)

执行:
  - 通过 agent-team-audit 单轮引擎 spawn 讨论组 agents
  - 各 Agent 独立分析, 输出原始 issues
  - 汇总引擎合并 + 去重 + 结构化提取

输出: discussion_output
```

### Step 2: 挑战组质疑

```yaml
输入:
  - discussion_output (完整提案)
  - context: 被审计内容 (供交叉验证)

执行:
  - spawn 挑战组 agents
  - 逐条审查 discussion_output.decisions
  - 对不同意的决策提出 objection

输出: challenge_output
```

### Step 3: 全员合并讨论

```yaml
输入:
  - discussion_output (原始提案)
  - challenge_output (质疑列表)
  - context: 被审计内容

执行:
  - spawn 全员 (讨论组 + 挑战组)
  - 讨论每个 objection
  - 修正提案以回应合理质疑
  - 对不合理质疑给出反驳

输出: revised_discussion_output (修正后的提案)
```

### Step 4: 挑战组再审

```yaml
输入:
  - revised_discussion_output (修正后的提案)

执行:
  - spawn 挑战组 agents
  - 审查每个 objection 是否被妥善处理
  - 更新 objection status

输出: updated_challenge_output
  - status: new → resolved (已修正) 或 overruled (撤回质疑)
  - 可能追加新的 objection (status: new)
```

### Step 5: Drift Check (#17, v1.44.0)

收敛判定**前**执行 (对应 DEC-20260611-001 §3 D2):

```yaml
输入:
  - anchor (Step 0 固化快照, 见 audit-engine/SKILL.md "Step 0: Anchor 固化" 节)
  - revised_discussion_output.decisions ∪ updated_challenge_output.objections

执行:
  - audit-engine 内部轻量调用 drift-checker (非 agent-team-audit 编排的审计 agent)
  - 持 anchor 对结论清单逐条分类 on-topic / adjacent / off-topic
  - 计算 drift_ratio → 按三档处置决策树决定后续动作

输出: drift_metrics (写入审计报告 drift_metrics 区块, 非独立 audit report,
      不适用 8-field 契约, 见 agent-dispatch-contract.md scope 排除)
```

**三档处置决策树** (区间边界与 DEC-20260611-001 §4.3 逐字):

```
drift_ratio
├── < warn_threshold (默认 0.2)
│     → 正常进入收敛判定
├── [warn, refocus) 档
│     → Warning — 报告标注; 双模式语义不同
│       (challenge 模式见下方 drift-checker 节 "warn 档 challenge 模式语义";
│        convergence 模式见 convergence-algorithm.md warn 档分支)
└── >= refocus_threshold (默认 0.5, 含等号)
      → 强制 refocus 轮 (REFOCUS_ROUND); 连续 2 次 → DRIFT_TERMINATED
```

公式、分类规则、除零特判、partial anchor、时间契约见下方 **drift-checker 节**;
REFOCUS_ROUND / DRIFT_TERMINATED 终局语义见 [convergence-algorithm.md](./convergence-algorithm.md)。

---

## Agent 分组配置

从 `config.json audit.teams[checkpoint]` 读取:

```json
{
  "discussion": ["tech-lead", "backend-architect"],
  "challenge": ["qa-engineer", "knowledge-manager"]
}
```

**全员** = discussion + challenge (去重)。

**约束**: 讨论组和挑战组不能为空。若配置错误, 降级为 convergence 模式。

---

## 收敛判定 (Challenge 特殊规则)

```
converged = conclusions_stable AND objections_resolved

conclusions_stable:
  revised_discussion_output.decisions 的四元组集合
  == 上一轮 revised_discussion_output.decisions 的四元组集合

objections_resolved:
  updated_challenge_output.objections 中
  所有 status != "new" (即全部 resolved 或 overruled)
```

---

## drift-checker 节 (#17, 对应 DEC-20260611-001 §3 D2)

drift-checker 是 **audit-engine 内部轻量调用** — 与讨论组/挑战组/judge 三方分离的第四方独立视角 (消除自评偏置), **非** agent-team-audit 编排的审计 agent。每轮收敛判定前拿 anchor + 本轮结论清单逐条分类 on-topic / adjacent / off-topic, 输出结构化 `drift_metrics` 而非 audit report, **不适用 8-field 契约** (scope 排除见 agent-dispatch-contract.md)。

### drift_ratio 公式 (本体)

```
drift_ratio = off_topic / all
```

- **adjacent 不计入分子** — 公式与阈值语义不改 (DEC-20260611-001 §9 守界句: adjacent 不计入 drift_ratio 分子的公式不改, 仅加三类计数 `{on_topic, adjacent, off_topic}` 可观测性 annotation; 阈值默认值即 issue 原案)。
- **分母 per-mode 显式定义**:

| 模式 | 分母 (all) |
|------|-----------|
| convergence | 当轮 conclusion_records (实施映射真实 token: `round_N.conclusions`, 见 convergence-algorithm.md "集合比较逻辑" 节 `current_set = { key(r) for r in round_N.conclusions }`) |
| challenge | `revised_discussion_output.decisions ∪ updated_challenge_output.objections` (只看 decisions 会使挑战组 objections 发散 — drift 最常见路径 — 完全不可见, guard 半盲) |

### objection 分类规则

challenge objection **无结构化 scope** → 分类**仅基于 `point` 文本 + `anchor.in_scope` / `anchor.out_of_scope_hints` 关键词比对**, **置信度低于 decision 路径**。两类来源经 `off_topic_ids` namespace 前缀**字面区分**:

- `d-` = decision (来自 `revised_discussion_output.decisions`)
- `obj-` = objection (来自 `updated_challenge_output.objections`)

报告消费侧可据前缀区分两类来源 (及其置信度差异)。

### 空结论集除零特判

精确条件 per-mode (DEC D2):

- **convergence 模式**: `conclusion_records = ∅`
- **challenge 模式**: `decisions = ∅ AND objections = ∅` (**联合判空**, 即 `|decisions ∪ objections| = 0`; 防实现者以 `decisions = ∅` 单边触发致 objections 被误排除)

满足时 → `drift_ratio = 0` (vacuously zero), **跳过 LLM 调用**, 与 0-finding 双轮稳定性既有路径及 backward-compat 缺字段语义 (drift_ratio=0) 对齐。

### partial anchor 分类规则 (DEC §4.1 / R5)

anchor 结构完整但 `in_scope = [] AND out_of_scope_hints = []` 时:

- drift-checker 降为 **primary_goal 语义相似度单维分类**: 语义相关 → on-topic, 否则 adjacent;
- 报告标注 `anchor_scope_empty: true` + `drift_classification_confidence: low`;
- **不触发 fail-soft skip** (区别于全缺 anchor 的 `drift_anchor_missing` 路径 — 该路径才跳过 drift 计算)。

### warn 档 challenge 模式语义

challenge 模式收敛判据为 `objections_resolved`, 与 unanimous_pass **无关** → warn 档 (`[warn, refocus)`) **降格为仅标注不阻塞**: 报告追加 `drift_warning` 字段, **不覆盖 `objections_resolved`**; refocus 档 (`>= refocus_threshold`) 仍按 REFOCUS_ROUND 执行。(convergence 模式 warn 档 = 汇总层强制 `unanimous_pass=false`, 见 convergence-algorithm.md。)

### 时间契约

drift-checker **独立 30-60s 超时**, **不占 300s/轮 wall-clock** (并发控制条目见 audit-engine/SKILL.md §并发控制 [line ~261], 本文件不另造第二张并发表)。spawn 失败/超时 → fail-open: `drift_ratio=null` 按 `< warn` 档处理 + `drift_check_skipped: true`, 见 audit-engine/SKILL.md 错误处理表 (含与 `round_state.incomplete` 正交声明)。

---

## 中间数据存储

Challenge 模式的中间数据在内存中保持, 不持久化到文件:

```yaml
每轮保留:
  - discussion_output (当轮)
  - challenge_output (当轮)
  - revised_discussion_output (当轮)
  - updated_challenge_output (当轮)

跨轮传递:
  - 上一轮 challenge_output → 当轮 Step 1 (供参考)
  - 上一轮 revised_discussion_output → 当轮收敛比较

最终持久化:
  - 最终 revised_discussion_output → 审计报告结论
  - 所有 objections 历史 → 审计报告轮次记录
```

---

**最后更新**: 2026-03-27

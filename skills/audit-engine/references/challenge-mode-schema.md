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

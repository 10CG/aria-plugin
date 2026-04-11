# Agent Handoff Contract

> **Version**: 1.0.0
> **Purpose**: Agent 间结构化上下文传递协议

## Schema

当 subagent-driver 调度多个 Agent 依次执行时,前一个 Agent 的输出应包含以下结构化上下文块,供后续 Agent 消费:

```yaml
handoff:
  task_id: "triage-engine-implementation"
  agent_from: "backend-architect"
  agent_source: "plugin"          # "plugin" (内置) | "project" (项目级 .aria/agents/)
  decisions_made:
    - "triage.sh 使用 bash + python3 heredoc 模式"
    - "配置走 orchestrator.dispatch_policy 独立节点"
  artifacts_created:
    - "triage.sh"
    - "test-fixtures/"
  open_questions:
    - "飞书消息截断策略: 10 条 or 按字数?"
  constraints:
    - "不新增 heartbeat.sh 必需 env 变量"
```

## 字段定义

| 字段 | 必需 | 类型 | 说明 |
|------|------|------|------|
| `task_id` | 是 | string | 当前任务标识 |
| `agent_from` | 是 | string | 产出此 handoff 的 Agent name |
| `agent_source` | 否 | enum | `"plugin"` (默认) 或 `"project"` — 预留 Layer 2 项目级 Agent |
| `decisions_made` | 是 | string[] | 已做的技术/设计决策 |
| `artifacts_created` | 是 | string[] | 已创建的文件/产出物 |
| `open_questions` | 否 | string[] | 未解决的问题 (下一个 Agent 需关注) |
| `constraints` | 否 | string[] | 约束条件 (下一个 Agent 必须遵守) |

## 使用方式

Handoff contract 由 **caller (subagent-driver) 注入** 到下一个 Agent 的 prompt 中,不写在 Agent 的 description 中。

```
subagent-driver 调度流程:
  Agent A 执行 → 输出含 handoff block
  subagent-driver 提取 handoff
  Agent B 启动 → prompt 中注入 handoff context
```

## 与 STCO Description 的关系

```
STCO (description) = 路由信号 → 决定选哪个 Agent
Handoff (runtime)  = 执行上下文 → 决定 Agent 怎么工作
```

两者职责分离: description 不包含 handoff 信息,handoff 不影响路由。

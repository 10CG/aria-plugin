---
name: agent-router
description: |
  任务到 Agent 的智能路由器，根据任务类型、文件路径自动选择最合适的 Agent。

  使用场景：subagent-driver 需要为任务选择 Agent、不确定应该使用哪个 Agent
argument-hint: "[task-description]"
context: fork
agent: general-purpose
allowed-tools: Read, Glob, Grep, Bash
---

# Agent Router (智能路由器)

> **版本**: 1.0.0 | **类型**: 路由器 (Agent 选择)
> **更新**: 2026-01-22 - 初始版本

## 快速开始

### 我应该使用这个 Skill 吗？

**使用场景**:
- 为任务自动选择合适的 Agent
- 不确定应该使用哪个专业 Agent
- 需要智能 Agent 匹配

**不使用场景**:
- 已明确知道使用哪个 Agent → 直接调用
- 简单通用任务 → 使用 general-purpose

---

## 核心功能

| 功能 | 说明 |
|------|------|
| **智能路由** | 根据任务特征自动匹配 Agent |
| **置信度评分** | 对每个匹配结果评分 (0-1) |
| **多模式支持** | 自动 / 推荐 / 手动三种模式 |
| **用户覆盖** | 允许用户显式指定 Agent |
| **Fallback** | 无匹配时使用 general-purpose |

---

## 路由模式

### 自动模式 (auto)

```yaml
行为: 直接调用置信度最高的 Agent
触发: confidence >= threshold (默认 0.9)
条件: 用户未显式指定 Agent

示例:
  任务: "实现用户登录 API"
  路由结果: backend-architect (confidence: 0.95)
  动作: 直接使用 backend-architect
```

### 推荐模式 (recommend) - 默认

```yaml
行为: 展示 Top-3 Agent 供用户选择
触发: confidence < threshold 或有多个候选
条件: 用户未显式指定 Agent

示例:
  任务: "优化数据库查询"
  路由结果:
    [1] backend-architect (0.85) - 后端架构优化
    [2] qa-engineer (0.60) - 性能分析
    [3] general-purpose (0.50) - 通用优化
  动作: 询问用户选择
```

### 手动模式 (manual)

```yaml
行为: 使用用户显式指定的 Agent
触发: 用户在任务中指定
优先级: 最高 (覆盖自动和推荐)

示例:
  任务: "用 backend-architect 实现用户认证"
  路由结果: backend-architect (手动指定)
  动作: 直接使用 backend-architect
```

---

## 路由规则

### 文件路径匹配

| 路径模式 | 目标 Agent | 置信度 |
|----------|-----------|--------|
| `backend/**/*` | backend-architect | 0.90 |
| `api/**/*` | backend-architect | 0.95 |
| `database/**/*` | backend-architect | 0.90 |
| `mobile/**/*` | mobile-developer | 0.95 |
| `*.dart` | mobile-developer | 0.90 |
| `frontend/**/*` | general-purpose | 0.70 |
| `docs/**/*` | knowledge-manager | 0.85 |
| `ai/**/*` | ai-engineer | 0.90 |

### 任务类型匹配

| 任务类型 | 目标 Agent | 置信度 |
|----------|-----------|--------|
| `architecture` | knowledge-manager | 0.90 |
| `code-review` | qa-engineer | 0.95 |
| `ui-design` | ui-ux-designer | 0.90 |
| `legal` | legal-advisor | 0.95 |
| `api-doc` | api-documenter | 0.90 |
| `llm` / `rag` | ai-engineer | 0.90 |
| `tech-lead` / `planning` | tech-lead | 0.85 |

### 技术栈匹配

| 技术关键词 | 目标 Agent | 置信度 |
|-----------|-----------|--------|
| `React Native` | mobile-developer | 0.90 |
| `Flutter` | mobile-developer | 0.90 |
| `REST` / `GraphQL` | backend-architect | 0.85 |
| `vector` / `embedding` | ai-engineer | 0.90 |
| `OpenAPI` / `Swagger` | api-documenter | 0.90 |

---

## 输入参数

| 参数 | 必需 | 说明 | 默认值 |
|------|------|------|--------|
| `task` | ✅ | 任务描述 | - |
| `task_type` | ❌ | 任务类型 | 自动推断 |
| `files` | ❌ | 相关文件列表 | [] |
| `mode` | ❌ | 路由模式 | recommend |
| `threshold` | ❌ | 自动模式阈值 | 0.9 |
| `user_agent` | ❌ | 用户指定的 Agent | null |

---

## 输出格式

### 自动模式 (直接匹配)

```yaml
status: "auto_match"
agent: "backend-architect"
confidence: 0.95
reason: "任务涉及 API 设计，路径匹配 backend/**/*"
model: "sonnet"
```

### 推荐模式 (多候选)

```yaml
status: "recommend"
candidates:
  - rank: 1
    agent: "backend-architect"
    confidence: 0.85
    reason: "后端架构相关任务"
    model: "sonnet"

  - rank: 2
    agent: "qa-engineer"
    confidence: 0.60
    reason: "可能涉及性能分析"
    model: "sonnet"

  - rank: 3
    agent: "general-purpose"
    confidence: 0.50
    reason: "通用任务兜底"
    model: "sonnet"

user_select_required: true
```

### 手动模式 (用户指定)

```yaml
status: "manual"
agent: "mobile-developer"
confidence: 1.0
reason: "用户显式指定"
source: "user_override"
```

### 无匹配 (Fallback)

```yaml
status: "fallback"
agent: "general-purpose"
confidence: 0.0
reason: "无明确匹配规则"
fallback: true
```

---

## 执行流程

```yaml
路由流程:

  1. 解析输入:
     ├── 读取 task 描述
     ├── 读取 task_type (如有)
     ├── 读取 files 列表
     └── 检查 user_agent (手动指定)

  2. 手动模式检查:
     ├── if user_agent 存在:
     │   └── 返回手动模式结果
     └── else: 继续

  3. 规则匹配:
     ├── 文件路径匹配
     ├── 任务类型匹配
     ├── 技术栈匹配
     └── 关键词匹配

  4. 置信度聚合:
     ├── 合并所有匹配结果
     ├── 去重并排序
     └── 选择 Top-N

  5. 模式决策:
     ├── if mode == auto:
     │   ├── if top_confidence >= threshold:
     │   │   └── 返回自动匹配
     │   └── else:
     │       └── 返回推荐 (降级)
     │
     ├── if mode == recommend:
     │   └── 返回 Top-3 推荐
     │
     └── if mode == manual:
         └── 等待用户指定

  6. 返回结果
```

---

## 与 subagent-driver 集成

```yaml
subagent-driver 调用流程:

  1. 接收任务列表
  2. for each task:
     a. 调用 agent-router
        ├── task: 任务描述
        ├── files: 相关文件
        └── mode: recommend (配置)

     b. 获取路由结果
        ├── auto: 直接使用
        ├── recommend: 询问用户
        └── manual: 使用用户指定

     c. 启动 Fresh Subagent
        └── 使用选定 Agent

  3. 执行任务
  4. 任务间审查
  5. 4 选项完成
```

---

## 配置

### 项目级配置 (.claude/agent-router-config.json)

```json
{
  "enabled": true,
  "default_mode": "recommend",
  "confidence_threshold": 0.9,
  "max_candidates": 3,
  "fallback_agent": "general-purpose"
}
```

### 任务级覆盖

```yaml
# detailed-tasks.yaml
tasks:
  - id: TASK-001
    description: "实现用户认证"
    agent: backend-architect  # 手动指定
    files:
      - backend/api/auth.js
```

---

## Agent 能力矩阵

| Agent | 擅长任务 | 模型 | 颜色 |
|-------|---------|------|------|
| general-purpose | 通用任务、复杂搜索 | sonnet | gray |
| knowledge-manager | 文档架构、AI-DDD | sonnet | blue |
| tech-lead | 架构决策、任务规划 | opus | red |
| qa-engineer | 代码审查、质量保证 | sonnet | yellow |
| context-manager | 上下文管理、多任务协调 | opus | cyan |
| ai-engineer | LLM 应用、RAG 系统 | opus | yellow |
| backend-architect | API 设计、微服务 | sonnet | green |
| mobile-developer | React Native、Flutter | sonnet | pink |
| api-documenter | OpenAPI、SDK 生成 | haiku | orange |
| legal-advisor | 法律文档、合规 | haiku | purple |
| ui-ux-designer | 界面设计、用户体验 | sonnet | purple |

---

## 使用示例

### 示例 1: 自动匹配

```yaml
输入:
  task: "实现用户登录 REST API"
  files: ["backend/api/auth.js"]
  mode: auto

输出:
  status: auto_match
  agent: backend-architect
  confidence: 0.95
  reason: "文件路径匹配 backend/**/*，包含 API 关键词"
```

### 示例 2: 推荐模式

```yaml
输入:
  task: "优化用户注册流程性能"
  files: ["backend/api/register.js", "database/schema.sql"]
  mode: recommend

输出:
  status: recommend
  candidates:
    - rank: 1
      agent: backend-architect
      confidence: 0.75
      reason: "后端相关文件和性能优化"

    - rank: 2
      agent: qa-engineer
      confidence: 0.65
      reason: "性能分析和优化"

    - rank: 3
      agent: general-purpose
      confidence: 0.50
      reason: "通用任务兜底"
```

### 示例 3: 手动指定

```yaml
输入:
  task: "用 tech-lead 规划系统重构"
  user_agent: tech-lead

输出:
  status: manual
  agent: tech-lead
  confidence: 1.0
  source: user_override
```

---

## 错误处理

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| 无匹配规则 | 任务特征不符合任何规则 | 使用 general-purpose |
| Agent 不存在 | 指定的 Agent 无效 | 警告并回退到 general-purpose |
| 多高置信度 | 多个 Agent 置信度都 > threshold | 降级到推荐模式 |

---

## 相关文档

- [subagent-driver](../subagent-driver/SKILL.md) - Fresh Subagent 执行器
- [AGENTS_ARCHITECTURE.md](../../../.claude/agents/AGENTS_ARCHITECTURE.md) - Agent 架构
- [phase-b-developer](../phase-b-developer/SKILL.md) - Phase B 开发

---

**最后更新**: 2026-01-22
**Skill版本**: 1.0.0

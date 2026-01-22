# Agent 分配规则

> **版本**: 2.0.0
> **最后更新**: 2025-12-23
> **相关 Skill**: task-planner

---

## 概述

Agent 分配是 A.3 (Agent分配) 步骤的核心。基于任务的 deliverables 路径和任务类型，将任务分配给最合适的专业 Agent。

---

## 可用 Agent

| Agent | 专业领域 | 典型任务 |
|-------|---------|---------|
| `backend-architect` | 后端架构、API、数据库 | Python, FastAPI, DB schema |
| `mobile-developer` | Flutter、UI、状态管理 | Dart, Flutter widgets |
| `qa-engineer` | 测试策略、质量保证 | 测试文件, 覆盖率 |
| `api-documenter` | OpenAPI、SDK 文档 | API docs, contracts |
| `knowledge-manager` | 文档管理、知识库 | Markdown, 架构文档 |
| `tech-lead` | 技术决策、跨团队协调 | 架构决策 |

---

## 分配规则

### backend-architect

```yaml
适用条件:
  - API 设计和实现
  - 数据库设计
  - 后端架构

路径匹配:
  - backend/**/*.py
  - backend/src/**/*
  - **/migrations/*.sql
  - **/models/*.py
  - **/routes/*.py
  - **/services/*.py

关键词:
  - API, endpoint, route
  - database, schema, migration
  - service, authentication
```

### mobile-developer

```yaml
适用条件:
  - Flutter/Dart 代码
  - UI 组件
  - 状态管理

路径匹配:
  - mobile/**/*.dart
  - mobile/lib/**/*
  - **/widgets/*.dart
  - **/screens/*.dart
  - **/providers/*.dart

关键词:
  - widget, screen, page
  - state, provider, bloc
  - flutter, dart
```

### qa-engineer

```yaml
适用条件:
  - 测试编写
  - 质量验证
  - 代码审查

路径匹配:
  - **/test/**/*.dart
  - **/tests/**/*.py
  - **/*_test.dart
  - **/test_*.py

关键词:
  - test, testing, coverage
  - quality, verify, validate
  - review, audit
```

### api-documenter

```yaml
适用条件:
  - OpenAPI 规范
  - API 文档
  - SDK 文档

路径匹配:
  - **/openapi.yaml
  - **/swagger.yaml
  - docs/api/**/*
  - **/contracts/*.yaml

关键词:
  - OpenAPI, Swagger
  - API documentation
  - SDK, contract
```

### knowledge-manager

```yaml
适用条件:
  - 架构文档
  - 规范文档
  - README

路径匹配:
  - **/*.md
  - **/ARCHITECTURE.md
  - **/README.md
  - docs/**/*.md
  - standards/**/*.md

关键词:
  - documentation, document
  - architecture, design
  - README, guide
```

### tech-lead

```yaml
适用条件:
  - 技术决策
  - 跨模块协调
  - 架构重构

触发条件:
  - 任务影响多个模块
  - 架构级别的变更
  - 技术选型决策
  - 复杂度为 XL

关键词:
  - architecture, decision
  - cross-module, integration
  - refactor, redesign
```

---

## 分配算法

```yaml
步骤 1: 路径匹配
  - 分析任务的 deliverables 文件路径
  - 匹配上述路径模式
  - 确定候选 Agent 列表

步骤 2: 关键词匹配
  - 分析任务标题和描述
  - 匹配 Agent 专业领域关键词
  - 调整候选权重

步骤 3: 复杂度考虑
  - XL 复杂度优先考虑 tech-lead
  - 跨模块任务优先考虑 tech-lead
  - 测试相关优先考虑 qa-engineer

步骤 4: 最终选择
  - 选择匹配度最高的 Agent
  - 记录分配理由 (reason 字段)
  - 设置验收标准 (verification 字段)
```

---

## 分配输出

每个任务分配后应包含:

```yaml
- id: TASK-001
  # ... 其他字段 ...
  agent: backend-architect
  reason: "API design and database schema expertise"
  verification:
    - "Unit tests pass with >85% coverage"
    - "No security warnings from linter"
    - "API documentation updated"
```

---

## 多 Agent 协作

复杂任务可能需要多个 Agent 协作:

```yaml
场景: 新功能开发

任务分解:
  TASK-001 (数据模型):     backend-architect
  TASK-002 (API 实现):     backend-architect
  TASK-003 (UI 组件):      mobile-developer
  TASK-004 (API 测试):     qa-engineer
  TASK-005 (UI 测试):      qa-engineer
  TASK-006 (文档更新):     knowledge-manager

协作模式:
  - 串行: TASK-001 → TASK-002 (同一 Agent)
  - 并行: TASK-003 || TASK-004 (不同 Agent)
  - 汇聚: TASK-005, TASK-006 (等待前置完成)
```

---

## 相关文档

- [task-planner SKILL.md](./SKILL.md)
- [双层架构规范](./DUAL_LAYER_SPEC.md)
- [Phase A: 规范与规划](../../../standards/core/ten-step-cycle/phase-a-spec-planning.md)

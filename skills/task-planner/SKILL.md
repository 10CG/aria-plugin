---
name: task-planner
description: |
  将 OpenSpec 分解为可执行的任务列表。
  支持十步循环 A.2 (任务规划) + A.3 (Agent 分配)。
  实现双层任务架构：tasks.md (粗粒度) + detailed-tasks.yaml (细粒度)。

  使用场景：
  - "把这个 Spec 分解成任务"
  - "规划一下这个功能的开发任务"
  - "生成任务列表和执行顺序"
  - "分析任务依赖关系"

  特性:
  - 双层任务架构 (OpenSpec 兼容)
  - tasks.md 优先读取与解析
  - 自动生成 detailed-tasks.yaml
  - parent 字段链接
  - 复杂度评估、依赖分析、Agent 预分配
allowed-tools: Read, Write, Glob, Grep, AskUserQuestion
---

# 任务规划器 (Task Planner)

> **版本**: 2.0.0 | **十步循环**: A.2 + A.3 (Agent 预分配)
> **架构**: 双层任务架构 (tasks.md + detailed-tasks.yaml)

## 快速开始

### 我应该使用这个 Skill 吗？

**使用场景**:
- A.2: 将 OpenSpec proposal.md 分解为可执行任务
- 需要评估任务复杂度和工作量
- 需要分析任务间依赖关系
- 需要确定最优执行顺序
- 需要预分配执行 Agent

**不使用场景**:
- 创建 Spec → 使用 `spec-drafter` (A.1)
- 查询项目状态 → 使用 `state-scanner` (A.0)
- 创建功能分支 → 使用 `branch-manager` (B.1)

---

## 核心功能

| 功能 | 描述 |
|------|------|
| **双层架构** | tasks.md (粗粒度) + detailed-tasks.yaml (细粒度) |
| tasks.md 解析 | 读取 OpenSpec 标准格式的 tasks.md，提取功能清单 |
| 任务转换 | 将功能清单转换为原子化任务 (4-8h 粒度) |
| parent 链接 | 维护 tasks.md 编号与 TASK-{NNN} 的映射关系 |
| 复杂度评估 | 自动评估 S/M/L/XL 复杂度 |
| 依赖分析 | 识别任务间依赖，构建 DAG |
| Agent 预分配 | 根据任务类型建议 Agent |
| 状态跟踪 | 为每个任务添加 status 字段 |

---

## 执行流程

### A.2.1 - 读取 Spec (tasks.md 优先)

```yaml
输入:
  - spec_path: Spec 目录路径 (如 changes/user-auth/)

读取策略:
  IF tasks.md 存在:
    → 路径 A: 解析 tasks.md (OpenSpec 标准格式)
    → 输出: 双层架构
  ELSE:
    → 路径 B: 从 proposal.md 分解任务
    → 输出: 仅 detailed-tasks.yaml

  始终从 proposal.md 读取 ## Success Criteria 章节
```

**详细解析流程**: [DUAL_LAYER_SPEC.md](./DUAL_LAYER_SPEC.md)

### A.2.2 - 任务分解

```yaml
分解规则:
  粒度目标: 4-8 小时可完成
  原子性: 单一职责，便于验证
  可测试: 每个任务有明确验收标准

分解策略:
  XL/L 任务: 按功能模块/技术层级拆分
  M 任务: 按实现步骤拆分
  S 任务: 保持原样
```

### A.2.3 - 复杂度评估

| 维度 | S | M | L | XL |
|------|---|---|---|-----|
| 文件影响 | 1-2 | 3-5 | 6-10 | >10 |
| 依赖数量 | 0 | 1-2 | 3-4 | >4 |

**详细评估规则**: [COMPLEXITY_GUIDE.md](./COMPLEXITY_GUIDE.md)

### A.2.4 - 依赖分析

```yaml
隐式依赖推断:
  测试 → 实现
  文档 → 功能
  集成 → 组件
  API → 模型
```

### A.2.5 - 执行顺序生成

```yaml
排序算法:
  1. 拓扑排序 (尊重依赖)
  2. 同级按优先级: P0 > P1 > P2 > P3
  3. 并行任务分组
```

### A.2.6 - Agent 预分配

根据任务 deliverables 路径和关键词匹配合适的 Agent。

**分配规则详情**: [AGENT_MAPPING.md](./AGENT_MAPPING.md)

---

## 输入参数

| 参数 | 必需 | 说明 | 默认值 |
|------|------|------|--------|
| `spec_path` | ❌ | Spec 路径 (自动检测) | - |
| `module` | ❌ | 目标模块 | 从 Spec 提取 |
| `max_task_hours` | ❌ | 最大任务时长 | 8h |
| `include_tests` | ❌ | 自动添加测试任务 | true |

---

## 输出格式

### 任务列表 (Markdown)

```markdown
# Task Breakdown: {Feature Name}

> **Spec**: {spec_path}
> **Total Tasks**: {count}
> **Estimated**: {total_hours}h

## Task List

### TASK-001: {Title}
- **Complexity**: M
- **Dependencies**: None
- **Agent**: backend-architect
- **Deliverables**: {files}

## Execution Order
TASK-001 → TASK-002 → TASK-003

## Summary
| Complexity | Count | Hours |
|------------|-------|-------|
| S | 2 | 4h |
| M | 3 | 12h |
```

### 任务列表 (YAML)

**文件位置**: `{spec_path}/detailed-tasks.yaml`

```yaml
metadata:
  feature: user-authentication
  datasource: "tasks.md"
  total_tasks: 7

tasks:
  - id: TASK-001
    parent: "1.1"
    title: Add OTP column
    status: pending
    complexity: M
    dependencies: []
    deliverables:
      - backend/migrations/add_otp.sql
    agent: backend-architect
    verification:
      - "Migration runs successfully"
```

**完整格式规范**: [DUAL_LAYER_SPEC.md](./DUAL_LAYER_SPEC.md)

---

## 使用示例

```yaml
用户请求: "把 user-auth 这个 Spec 分解成任务"

处理:
  1. 读取 tasks.md (路径 A)
  2. 提取 checklist items
  3. 转换为原子任务
  4. 评估复杂度
  5. 分析依赖
  6. 分配 Agent
  7. 写入 detailed-tasks.yaml

输出:
  tasks: 8 个任务
  complexity: 2S + 4M + 2L
  estimated: 32h
```

---

## 与其他 Skills 的协作

```
spec-drafter (A.1) ─→ proposal.md + tasks.md
                            │
                            ▼
task-planner (A.2+A.3) ─→ detailed-tasks.yaml
                            │
                            ▼
branch-manager (B.1) ─→ feature/{TASK-ID}
```

---

## 错误处理

| 错误 | 解决方案 |
|------|----------|
| Spec 未找到 | 检查路径，或先执行 A.1 |
| tasks.md 格式错误 | 检查 `- [ ] X.Y Desc` 格式 |
| parent 提取失败 | 确保编号格式 `^\d+\.\d+$` |
| 循环依赖 | 审查依赖关系，打破循环 |

```yaml
容错策略:
  tasks.md 解析失败:
    → 自动 Fallback 到 proposal.md
    → 显示警告信息
```

---

## 检查清单

### 使用前
- [ ] Spec 已创建 (A.1 完成)
- [ ] 检查是否存在 tasks.md

### 使用后
- [ ] 任务列表已生成
- [ ] parent 字段已提取 (路径 A)
- [ ] detailed-tasks.yaml 已写入
- [ ] Agent 预分配完成
- [ ] 准备进入 B.1 分支创建

---

## 相关文档

### 子文件
- [DUAL_LAYER_SPEC.md](./DUAL_LAYER_SPEC.md) - 双层架构规范
- [AGENT_MAPPING.md](./AGENT_MAPPING.md) - Agent 分配规则
- [COMPLEXITY_GUIDE.md](./COMPLEXITY_GUIDE.md) - 复杂度评估指南

### 外部引用
- [十步循环概览](../../../standards/core/ten-step-cycle/README.md)
- [Phase A: 规范与规划](../../../standards/core/ten-step-cycle/phase-a-spec-planning.md)
- [spec-drafter](../spec-drafter/SKILL.md)
- [state-scanner](../state-scanner/SKILL.md)
- [branch-manager](../branch-manager/SKILL.md)

---

**最后更新**: 2025-12-23
**Skill版本**: 2.0.0
**架构**: 双层任务架构 (v2.0.0)

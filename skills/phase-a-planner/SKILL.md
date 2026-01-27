---
name: phase-a-planner
description: |
  十步循环 Phase A - 规划阶段执行器，编排 A.1-A.3 步骤。

  使用场景："执行规划阶段"、"Phase A"、"创建 Spec 并规划任务"
disable-model-invocation: false
user-invocable: true
allowed-tools: Read, Write, Glob, Grep, Task
---

# Phase A - 规划阶段 (Planner)

> **版本**: 1.0.0 | **十步循环**: A.1-A.3

## 快速开始

### 我应该使用这个 Skill 吗？

**使用场景**:
- 需要创建或选择 OpenSpec
- 需要规划任务分解
- 需要分配 Agent 执行
- 新功能开发的第一阶段

**不使用场景**:
- 简单修复 (Level 1) → 直接跳过 Phase A
- 已有 approved Spec → 跳过 A.1
- 已有 detailed-tasks.yaml → 跳过 A.2/A.3

---

## 核心功能

| 步骤 | Skill | 职责 | 输出 |
|------|-------|------|------|
| A.1 | spec-drafter | Spec 创建/选择 | spec_id, spec_status |
| A.2 | task-planner | 任务规划 | task_list, task_count |
| A.3 | task-planner | Agent 分配 | assigned_agents |

---

## 执行流程

### 输入

```yaml
context:
  phase_cycle: "Phase4-Cycle9"    # 当前进度
  module: "mobile"                # 目标模块
  changed_files: []               # 变更文件 (如有)
  user_intent: "开发用户认证"      # 用户意图

config:
  skip_steps: []                  # 跳过的步骤
  params:
    spec_level: 2                 # Spec 级别 (1/2/3)
```

### 步骤执行

```yaml
A.1 - Spec 管理:
  skill: spec-drafter
  skip_if:
    - has_openspec: true          # 已有活跃 Spec
    - complexity: Level1          # 简单任务
  action:
    - 检查现有 Spec
    - 创建新 Spec 或选择现有
  output:
    spec_id: "add-auth-feature"
    spec_status: "approved"

A.2 - 任务规划:
  skill: task-planner
  action: plan
  skip_if:
    - has_detailed_tasks: true    # 已有 detailed-tasks.yaml
  depends_on: A.1
  action:
    - 分解 Spec 为具体任务
    - 生成 tasks.md 和 detailed-tasks.yaml
  output:
    task_list: [TASK-001, TASK-002, ...]
    task_count: 5

A.3 - Agent 分配:
  skill: task-planner
  action: assign
  depends_on: A.2
  action:
    - 为每个任务分配最佳 Agent
    - 更新 detailed-tasks.yaml
  output:
    assigned_agents:
      TASK-001: backend-architect
      TASK-002: mobile-developer
```

### 输出

```yaml
success: true
steps_executed: [A.1, A.2, A.3]
steps_skipped: []
results:
  A.1:
    spec_id: "add-auth-feature"
    spec_status: "approved"
  A.2:
    task_count: 5
  A.3:
    agents_assigned: 5

context_for_next:
  spec_id: "add-auth-feature"
  task_list: [TASK-001, TASK-002, ...]
  assigned_agents: {...}
```

---

## 跳过规则

| 条件 | 跳过步骤 | 检测方法 |
|------|---------|----------|
| 已有活跃 Spec | A.1 | 扫描 openspec/changes/ |
| 复杂度 Level1 | A.1 | 变更文件 ≤3 + 简单类型 |
| 已有 tasks.yaml | A.2, A.3 | 检查 detailed-tasks.yaml |

### 跳过逻辑

```yaml
skip_evaluation:
  A.1:
    - condition: openspec/changes/{any}/proposal.md exists
      with_status: [approved, in_progress]
      action: skip A.1, use existing spec_id

  A.2_A.3:
    - condition: detailed-tasks.yaml exists
      with_status: not all completed
      action: skip A.2 and A.3, use existing tasks
```

---

## 输出格式

```
╔══════════════════════════════════════════════════════════════╗
║              PHASE A - PLANNING                              ║
╚══════════════════════════════════════════════════════════════╝

📋 执行计划
───────────────────────────────────────────────────────────────
  A.1 spec-drafter      → 创建/选择 Spec
  A.2 task-planner      → 任务规划
  A.3 task-planner      → Agent 分配

🚀 执行中...
───────────────────────────────────────────────────────────────
  ✅ A.1 完成 → Spec: add-auth-feature (approved)
  ✅ A.2 完成 → 任务数: 5
  ✅ A.3 完成 → Agent 已分配

📤 上下文输出
───────────────────────────────────────────────────────────────
  spec_id: add-auth-feature
  task_count: 5
  ready_for: Phase B
```

---

## 使用示例

### 示例 1: 完整规划

```yaml
输入:
  context:
    user_intent: "添加用户认证功能"
    module: "backend"

执行:
  A.1: 创建 Level 2 Spec → add-auth-feature
  A.2: 分解为 5 个任务
  A.3: 分配 Agent

输出:
  context_for_next:
    spec_id: "add-auth-feature"
    task_list: [TASK-001, ..., TASK-005]
```

### 示例 2: 跳过 A.1

```yaml
输入:
  context:
    openspec_id: "add-auth-feature"  # 已有 Spec

执行:
  A.1: 跳过 (已有 Spec)
  A.2: 规划任务
  A.3: 分配 Agent

输出:
  steps_skipped: [A.1]
```

### 示例 3: 全部跳过

```yaml
输入:
  context:
    has_detailed_tasks: true

执行:
  全部跳过 (已有完整规划)

输出:
  steps_skipped: [A.1, A.2, A.3]
  context_for_next:
    # 使用现有规划数据
```

---

## 错误处理

| 错误 | 原因 | 处理 |
|------|------|------|
| Spec 创建失败 | 信息不足 | 提示用户补充意图 |
| 任务规划失败 | Spec 不完整 | 回退到 A.1 完善 |
| Agent 分配失败 | 未知任务类型 | 使用 general-purpose |

---

## 与其他 Phase 的关系

```
state-scanner
    │
    ▼
phase-a-planner (本 Skill)
    │
    │ context_for_next:
    │   - spec_id
    │   - task_list
    │   - assigned_agents
    ▼
phase-b-developer
```

---

## 相关文档

- [spec-drafter](../spec-drafter/SKILL.md) - A.1 Spec 管理
- [task-planner](../task-planner/SKILL.md) - A.2/A.3 任务规划
- [phase-b-developer](../phase-b-developer/SKILL.md) - 下一阶段

---

**最后更新**: 2025-12-25
**Skill版本**: 1.0.0

# Workflow Runner v2.0 迁移指南

> 从 v1.0 (步骤级) 到 v2.0 (Phase 级) 的迁移说明

## 架构变更概览

### v1.0 架构

```
workflow-runner v1.0
    │
    ├── 直接调用 10 个步骤 Skills
    ├── 集中管理跳过规则 (SKIP_RULES.md)
    └── 手动上下文传递
```

### v2.0 架构

```
state-scanner v2.0 (统一入口)
    │
    │ 推荐工作流
    ▼
workflow-runner v2.0 (轻量编排器)
    │
    ├──▶ phase-a-planner (A.1-A.3)
    ├──▶ phase-b-developer (B.1-B.3)
    ├──▶ phase-c-integrator (C.1-C.2)
    └──▶ phase-d-closer (D.1-D.2)
```

---

## 主要变更

### 1. 执行单元变更

| v1.0 | v2.0 |
|------|------|
| 步骤 (A.1, B.2...) | Phase (A, B, C, D) |
| 直接执行 10 个步骤 | 调用 4 个 Phase Skills |

### 2. 跳过规则变更

| v1.0 | v2.0 |
|------|------|
| 集中在 SKIP_RULES.md | 分散到各 Phase Skill |
| workflow-runner 负责判断 | Phase Skill 自行判断 |

### 3. 上下文传递变更

| v1.0 | v2.0 |
|------|------|
| 手动传递 | 自动 context_for_next |
| 步骤间传递 | Phase 间传递 |

### 4. 入口变更

| v1.0 | v2.0 |
|------|------|
| 直接调用 workflow-runner | state-scanner → workflow-runner |
| 无智能推荐 | 智能工作流推荐 |

---

## 文件变更

### 删除的文件

```
.claude/skills/workflow-runner/SKIP_RULES.md  # 跳过规则移至各 Phase Skill
```

### 新增的文件

```
.claude/skills/phase-a-planner/SKILL.md
.claude/skills/phase-b-developer/SKILL.md
.claude/skills/phase-c-integrator/SKILL.md
.claude/skills/phase-d-closer/SKILL.md
.claude/skills/state-scanner/RECOMMENDATION_RULES.md
```

### 修改的文件

```
.claude/skills/workflow-runner/SKILL.md     # 重构为轻量编排器
.claude/skills/workflow-runner/WORKFLOWS.md # 使用 Phase 引用
.claude/skills/state-scanner/SKILL.md       # 升级为智能推荐入口
```

---

## 工作流定义变更

### v1.0 格式

```yaml
id: quick-fix
steps:
  - step: B.1
    skill: branch-manager
  - step: B.2
    skill: test-verifier
  - step: C.1
    skill: commit-msg-generator
```

### v2.0 格式

```yaml
id: quick-fix
phases:
  - phase: B
    skill: phase-b-developer
    config:
      skip_steps: [B.3]
  - phase: C
    skill: phase-c-integrator
```

---

## 使用方式变更

### v1.0 使用方式

```yaml
# 直接调用 workflow-runner
"运行 quick-fix 工作流"

# 自定义步骤
"执行 B.1, B.2, C.1"
```

### v2.0 使用方式

```yaml
# 通过 state-scanner 入口 (推荐)
"开始开发"
→ state-scanner 分析状态
→ 推荐 quick-fix
→ 用户确认
→ workflow-runner 执行

# 直接调用 (仍支持)
"运行 quick-fix 工作流"

# Phase 组合
"执行 Phase B 和 C"
```

---

## 兼容性

### 向后兼容

| 功能 | 兼容性 |
|------|--------|
| 预置工作流名称 | ✅ 兼容 (quick-fix, feature-dev 等) |
| 步骤列表语法 | ✅ 兼容 (自动映射到 Phase) |
| 工作流触发方式 | ✅ 兼容 |

### 不兼容变更

| 功能 | 变更 |
|------|------|
| SKIP_RULES.md | ❌ 已删除，迁移到各 Phase Skill |
| 细粒度步骤控制 | ⚠️ 改为 Phase 级配置 |
| 自定义跳过规则 | ⚠️ 在 Phase Skill 中配置 |

---

## 迁移步骤

### 1. 更新 Skills (自动)

新 Skills 已创建，无需手动迁移。

### 2. 迁移自定义工作流

如果有自定义工作流定义：

```yaml
# v1.0 格式
steps:
  - step: A.2
    skill: task-planner
  - step: B.1
    skill: branch-manager

# 迁移到 v2.0 格式
phases:
  - phase: A
    skill: phase-a-planner
    config:
      skip_steps: [A.1, A.3]  # 只执行 A.2
  - phase: B
    skill: phase-b-developer
    config:
      skip_steps: [B.2, B.3]  # 只执行 B.1
```

### 3. 迁移跳过规则

如果有自定义跳过规则：

```yaml
# v1.0 在 SKIP_RULES.md 中
custom_rules:
  - id: my_rule
    skip: [B.3]
    condition: ...

# v2.0 在调用时配置
phases:
  - phase: B
    config:
      skip_steps: [B.3]
```

---

## 常见问题

### Q: 为什么要迁移到 Phase 架构？

A: Phase 架构带来以下优势：
- 更低复杂度：管理 4 个 Phase 比 10 个步骤更简单
- 更灵活组合：Phase 可独立调用或自由组合
- 更清晰职责：跳过逻辑由 Phase Skill 自行管理
- 更易扩展：新增步骤只需修改对应 Phase Skill

### Q: 现有工作流会失效吗？

A: 不会。预置工作流名称保持不变，使用方式向后兼容。

### Q: 如何执行单个步骤？

A: 通过 Phase 配置跳过其他步骤：

```yaml
# 只执行 C.1
phases:
  - phase: C
    config:
      skip_steps: [C.2]
```

### Q: state-scanner 必须使用吗？

A: 不是必须的，但推荐使用。state-scanner 提供智能工作流推荐，可以直接调用 workflow-runner 跳过推荐步骤。

---

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v2.0.0 | 2025-12-25 | Phase-Based 架构重构 |
| v1.0.0 | 2025-12-24 | 初始版本 |

---

**最后更新**: 2025-12-25

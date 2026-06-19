---
name: spec-drafter
description: |
  辅助创建 OpenSpec proposal.md 文档，支持十步循环 A.1 (Spec管理)。

  使用场景："创建新功能的 Spec"、"需要写 proposal"
argument-hint: "[feature-name]"
disable-model-invocation: false
user-invocable: true
allowed-tools: Read, Write, Glob, Grep, AskUserQuestion
---

# Spec 起草助手 (Spec Drafter)

> **版本**: 2.0.0 | **十步循环**: A.1 Spec管理
> **架构**: 双层任务架构 (tasks.md + detailed-tasks.yaml)

## 快速开始

### 我应该使用这个 Skill 吗？

**使用场景**:
- A.1: 为新功能/变更创建 OpenSpec 规范
- 需要自动判断 Spec 级别 (Level 1/2/3)
- 需要生成符合模板的 proposal.md
- 需要拆解大功能为 tasks.md

**不使用场景**:
- 简单的 typo/格式修复 → Level 1，直接跳过 A.1
- 查询项目状态 → 使用 `state-scanner` (A.0)
- 规划任务执行 → 使用 `task-planner` (A.2)

---

## 核心功能

| 功能 | 描述 |
|------|------|
| Level 自动判断 | 根据需求内容判断 Spec 级别 (1/2/3) |
| 信息提取 | 从用户输入提取 Why/What/Tasks 等信息 |
| 模板生成 | 生成符合 OpenSpec 规范的 proposal.md |
| Level 3 扩展 | 架构变更时额外生成 tasks.md |
| 交互模式 | 逐章节确认和修改 |
| 上下文增强 | 集成 state-scanner 获取项目状态 |
| **头脑风暴集成** | 内置 brainstorm 流程，基于决策记录预填充 |

---

## 三级 Spec 策略

| Level | 名称 | 触发条件 | 产出物 |
|-------|------|---------|--------|
| **1** | Skip | 简单修复、配置、格式 | 无 Spec |
| **2** | Minimal | 中等功能 (1-3 天) | proposal.md |
| **3** | Full | 架构变更、跨模块 | proposal.md + tasks.md |

**详细判断规则**: [LEVEL_GUIDE.md](./LEVEL_GUIDE.md)

---

## 输入参数

| 参数 | 必需 | 说明 | 示例 |
|------|------|------|------|
| `requirement` | ✅ | 需求描述 | "创建用户认证功能" |
| `module` | ❌ | 目标模块 (自动检测) | `mobile`, `backend`, `standards` |
| `interactive` | ❌ | 是否交互模式 (默认 `true`) | `true`, `false` |
| `create_file` | ❌ | 是否直接创建文件 (默认 `false`) | `true`, `false` |
| `level_override` | ❌ | 强制指定 Level | `1`, `2`, `3` |

---

## 执行流程

```yaml
A.1.0 - 头脑风暴检查 (新增):
  - 检查是否有现有决策记录 (docs/decisions/)
  - 根据文档类型决定是否需要头脑风暴:
    * 创建 PRD: 检查是否有 problem decision-log
    * 创建 OpenSpec: 检查是否有 technical decision-log
  - 如无决策记录，询问是否先运行 brainstorm

A.1.1 - 收集需求信息:
  - 从决策记录预填充 (如有)
  - 提取需求标题 (Feature Name)
  - 提取动机说明 (Why)
  - 提取功能描述 (What)
  - 提取交付物列表 (Deliverables)
  - 提取约束条件 (Constraints)
  - 框架约定 (Framework Constraints, Aria #95, 可选): framework 项目 (Next.js /
    Astro / SvelteKit / Vue / Remix 等) 在 proposal 加一段已知 framework
    convention / anti-pattern (route handler export 限制 / private-folder
    routing / use client·server / metadata 白名单), 供 post_spec/post_impl
    审计 agent 直接对照 (见 agent-team-audit/references/audit-points.md
    「横切检查原则 · 框架约定」)。无 framework 项目跳过。

A.1.2 - Level 判断:
  - 关键词匹配 (Level 1/3 触发词)
  - 文件影响范围分析 (跨模块检测)
  - 变更类型识别 (breaking change)
  → 详见 [LEVEL_GUIDE.md](./LEVEL_GUIDE.md)

A.1.3 - 模块检测:
  - mobile: Flutter/Dart, UI组件, 移动端
  - backend: Python, API, FastAPI, 数据库
  - shared: 契约, Schema, OpenAPI
  - standards: 规范, Skill, OpenSpec

A.1.4 - 生成 Spec 文档:
  Level 2: standards/openspec/changes/{feature}/proposal.md
  Level 3: proposal.md + tasks.md (OpenSpec 双层架构格式)
  - 预填充决策引用 (如有决策记录)

A.1.5 - 交互确认 (可选):
  逐章节确认: Level → Why → What → Deliverables → Impact → Tasks → Success Criteria

A.1.6 - 验证提示:
  输出: "建议运行 openspec validate {feature} --strict 验证格式"
```

---

## 输出格式

### Level 2 预览

```
╔══════════════════════════════════════════════════════════╗
║           SPEC DRAFT PREVIEW (Level 2)                   ║
╚══════════════════════════════════════════════════════════╝

Feature: user-authentication
Module: backend
Location: standards/openspec/changes/user-authentication/proposal.md

──────────────────────────────────────────────────────────
# User Authentication

> **Level**: Minimal (Level 2 Spec)
> **Status**: Draft

## Why
为应用添加用户身份验证功能，保护敏感操作和数据。

## What
实现基于 JWT 的用户认证系统。

### Key Deliverables
- backend/src/services/auth_service.py
- backend/src/routes/auth_routes.py

## Tasks
- [ ] 设计用户数据模型
- [ ] 实现 JWT 认证服务

## Success Criteria
- [ ] 用户可注册和登录
- [ ] 测试覆盖率 >= 85%
──────────────────────────────────────────────────────────

🤔 Create this file? [Yes/No/Edit]
```

### Level 3 预览

```
╔══════════════════════════════════════════════════════════╗
║           SPEC DRAFT PREVIEW (Level 3 - Full)            ║
╚══════════════════════════════════════════════════════════╝

Feature: progress-management-refactor
Module: cross (standards + mobile + backend)

📄 Files to Generate:
   ├── proposal.md - 功能规范
   └── tasks.md    - 任务分解 (OpenSpec 双层架构)

🤔 Create these files? [Yes/No/Edit]
```

### Level 1 输出

```
═══════════════════════════════════════════════════════════
  LEVEL 1 DETECTED - SKIP SPEC
═══════════════════════════════════════════════════════════

此需求为简单修复，建议直接跳过 A.1：
- 类型: 文档格式/Typo 修复
- 影响: 单文件
- 风险: 极低

📋 推荐操作:
   直接进入 B.1 (分支创建) 开始开发
```

---

## 上下文增强

当指定 `module` 时，自动从 state-scanner 获取上下文：

```yaml
获取信息:
  - 当前 Phase/Cycle
  - 活跃风险列表
  - KPI 快照

填充到 Spec:
  - Impact.Risk: 关联现有风险
  - Success Criteria: 参考 KPI 目标
```

**详细示例**: [LEVEL_GUIDE.md](./LEVEL_GUIDE.md#上下文增强示例)

---

## 头脑风暴集成

### 集成概述

spec-drafter 与 brainstorm skill 深度集成，实现"决策优先于文档"的理念。

```yaml
流程:
  1. 检测决策记录
     ├── 有 decision-log → 预填充 Spec
     └── 无 decision-log → 询问是否先头脑风暴

  2. 预填充逻辑
     ├── Background ← problem 模式决策
     ├── Constraints ← 收集的约束条件
     ├── Technical Approach ← technical 模式决策
     └── Decisions ← 引用决策 ID

  3. 决策引用
     ├── 格式: [DEC-001](../../docs/decisions/problem-001.md)
     ├── 自动生成决策链接
     └── 保持可追溯性
```

### PRD 创建集成

```yaml
触发场景: 用户要创建 PRD 文档

检查流程:
  1. 扫描 docs/decisions/problem-*.md
  2. 检查是否有相关决策记录

  如有相关决策:
    - 基于决策内容预填充 PRD
    - 引用决策 ID

  如无相关决策:
    - 提示: "建议先运行 brainstorm.problem 澄清问题"
    - 选项:
      [1] 先头脑风暴 (推荐)
      [2] 直接创建 PRD
      [3] 取消
```

### OpenSpec 创建集成

```yaml
触发场景: 用户要创建 OpenSpec proposal

检查流程:
  1. 扫描 docs/decisions/technical-*.md
  2. 检查是否有相关技术决策

  如有相关决策:
    - 预填充技术方案
    - 引用决策 ID
    - 自动填充约束条件

  如无相关决策:
    - 提示: "建议先运行 brainstorm.technical 讨论技术方案"
    - 选项:
      [1] 先头脑风暴 (推荐)
      [2] 直接创建 OpenSpec
      [3] 取消
```

### 预填充格式

proposal.md 中引用决策的格式：

```markdown
# {Feature Name}

> **决策来源**: [DEC-001](../../docs/decisions/problem-001.md), [DEC-002](../../docs/decisions/technical-001.md)

## 背景
> 基于 [DEC-001](../../docs/decisions/problem-001.md) 的讨论

用户需要 24/7 可用的客服支持...

## 约束条件
| 类型 | 约束 | 来源 |
|------|------|------|
| business | 预算 < $500/月 | DEC-001 |
| technical | 私有化部署 | DEC-001 |

## 技术方案
> 基于 [DEC-002](../../docs/decisions/technical-001.md) 的决策

采用自建 RAG 方案 (FAISS + 本地模型)...

## 关键决策
| 决策 | 选择 | 理由 |
|------|------|------|
| 向量存储 | FAISS | 满足成本约束 |
| 嵌入模型 | 待定 | 需要 brainstorm.technical 讨论 |
```

### 决策追溯链

```yaml
决策链:
  problem-001 (问题定义)
    ↓ 引用
  requirements-001 (需求分解)
    ↓ 引用
  technical-001 (技术方案)
    ↓ 引用
  proposal.md (最终规范)

追溯:
  proposal.md → technical-001 → requirements-001 → problem-001
  完整的"为什么"决策链
```

---

## tasks.md 格式要求

Level 3 生成的 tasks.md 遵循 OpenSpec 双层架构：

```yaml
格式要求:
  - 使用 checkbox: - [ ] {Phase}.{Task} {Description}
  - 编号格式: 1.1, 1.2, 2.1 (Phase.Task)
  - 粗粒度: 功能层面，避免技术细节
  - 编号不可变: 一旦创建不能修改

不包含:
  - Agent 分配 (A.3 负责)
  - 时间估算 (A.2 负责)
  - 文件路径 (A.2 负责)
```

---

## 错误处理

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| 无法判断 Level | 需求描述过于模糊 | 提供更详细描述，或使用 `level_override` |
| 模块检测失败 | 需求未涉及具体模块 | 手动指定 `module` 参数 |
| 信息提取不完整 | 需求缺少关键信息 | 使用交互模式逐项补充 |
| 文件已存在 | 同名 Spec 已存在 | 检查现有 Spec，考虑更新而非新建 |

---

## 与其他 Skills 的协作

```
state-scanner (A.0) ──▶ 状态感知
        │
        ├── brainstorm (A.0.5) ──▶ 决策记录 ← 新增
        │                              │
        └──────────────────────────────┘
        ▼
spec-drafter (A.1) ──▶ proposal.md + tasks.md (基于决策预填充)
        │
        ▼
task-planner (A.2/A.3) ──▶ detailed-tasks.yaml
        │
        ▼
branch-manager (B.1) ──▶ 功能分支
```

### 头脑风暴集成点

```yaml
A.0.5 头脑风暴 (可选):
  ├── brainstorm.problem: 问题空间探索
  ├── brainstorm.requirements: 需求分解
  └── brainstorm.technical: 技术方案设计

A.1 Spec 创建:
  ├── 检测决策记录
  ├── 预填充 Spec 内容
  └── 引用决策 ID

决策记录 → Spec 同步:
  docs/decisions/*.md → openspec/changes/*/proposal.md
```

---

## 检查清单

### 使用前
- [ ] 确认需求描述清晰完整
- [ ] 了解涉及的模块范围

### 使用后
- [ ] 已生成 proposal.md (Level 2/3)
- [ ] 已生成 tasks.md (Level 3)
- [ ] Level 判断合理
- [ ] 运行 `openspec validate <feature> --strict` 验证格式
- [ ] 准备进入 A.2 任务规划

> **提示**: 生成文件后建议运行 `openspec validate <feature> --strict` 确保符合规范

---

## 子文件

- [LEVEL_GUIDE.md](./LEVEL_GUIDE.md) - Spec Level 决策指南

## 相关文档

- [十步循环概览](../../../standards/core/ten-step-cycle/README.md)
- [Phase A: 规范与规划](../../../standards/core/ten-step-cycle/phase-a-spec-planning.md)
- [OpenSpec 项目定义](../../../standards/openspec/project.md)
- [proposal-minimal 模板](../../../standards/openspec/templates/proposal-minimal.md)
- [brainstorm](../brainstorm/SKILL.md) - 头脑风暴引擎 (新增集成)
- [state-scanner](../state-scanner/SKILL.md)
- [task-planner](../task-planner/SKILL.md)

---

**最后更新**: 2026-06-19 (Aria #95: A.1.1 加可选 Framework Constraints 提取)
**Skill版本**: 2.2.0 (Framework Constraints 提取)
**架构**: 双层任务架构 (v2.0.0)

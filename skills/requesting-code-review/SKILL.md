---
name: requesting-code-review
description: |
  Use this skill when completing tasks, implementing major features, or before merging to verify work meets requirements. Dispatches aria:code-reviewer agent to review implementation against plan or requirements before proceeding.

  Two-phase review: Phase 1 (Specification Compliance) → Phase 2 (Code Quality).
  Core principle: Review early, review often.

  使用场景：任务完成后审查、主要功能完成后、合并到主分支前、遇到困难时获取新视角。

  参考: obra/superpowers requesting-code-review implementation.
disable-model-invocation: false
user-invocable: true
---

# Requesting Code Review / 请求代码审查

> **版本**: 1.0.0 | **层级**: Layer 1 (Execution Skill) | **分类**: Development Skills
> **更新**: 2026-02-06 - 基于 Superpowers 两阶段审查实现
> **参考**: [obra/superpowers requesting-code-review](https://github.com/obra/superpowers/blob/main/skills/requesting-code-review/SKILL.md)

---

## 快速开始 / Quick Start

### 我应该使用这个 skill 吗？ / Should I use this skill?

**使用场景 / When to Use**:
- ✅ After completing each task in subagent-driven development / 在 subagent-driven development 中每个任务完成后
- ✅ After completing major features / 完成主要功能后
- ✅ Before merging to main branch / 合并到主分支前
- ✅ When stuck (fresh perspective) / 遇到困难时（新视角）

**不使用场景 / When NOT to Use**:
- ❌ Simple documentation changes / 简单文档修改
- ❌ Trivial fixes / 琐碎修复
- ❌ Configuration updates / 配置文件更新

---

## 核心原则 / Core Principles

```
Review Early, Review Often / 早审查，常审查

┌─────────────────────────────────────────────────────────────┐
│                     审查时机                                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  最佳: 每个任务后审查 → 问题在复合前捕获                       │
│  良好: 每批任务后审查 → 批量问题一起处理                       │
│  勉强: 仅合并前审查 → 问题可能已经累积                          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 何时请求审查 / When to Request Review

### 强制场景 / Mandatory

- **每个任务完成后** / After each task in subagent-driven development
- **主要功能完成后** / After completing major feature
- **合并到主分支前** / Before merge to main branch

### 可选但有价值 / Optional but Valuable

- **遇到困难时** / When stuck (fresh perspective)
- **重构前** / Before refactoring (baseline check)
- **修复复杂 bug 后** / After fixing complex bug

---

## 如何请求 / How to Request

### 步骤 1: 获取 git SHA / Step 1: Get git SHA

```bash
# 获取起始 SHA (上一个提交或主分支)
BASE_SHA=$(git rev-parse HEAD~1)  # 或 origin/main
HEAD_SHA=$(git rev-parse HEAD)

# Windows PowerShell
$BASE_SHA = git rev-parse HEAD~1
$HEAD_SHA = git rev-parse HEAD
```

### 步骤 2: 准备参数 / Step 2: Prepare Parameters

| 参数 | 说明 | 示例 |
|------|------|------|
| `WHAT_WAS_IMPLEMENTED` | 刚刚实现的内容 | "添加了密码重置功能" |
| `PLAN_OR_REQUIREMENTS` | 计划或需求文档 | `tasks.md TASK-001` |
| `BASE_SHA` | 起始提交 SHA | `a7981ec` |
| `HEAD_SHA` | 结束提交 SHA | `3df7661` |

### 步骤 3: 调用代码审查 / Step 3: Dispatch Code Review

使用 Task 工具调用 `aria:code-reviewer` Agent，填充 `code-reviewer.md` 模板。

---

## 处理反馈 / Handling Feedback

| 问题类型 | 操作 / Action |
|----------|---------------|
| **Critical** | 立即修复 / Fix immediately |
| **Important** | 继续前修复 / Fix before proceeding |
| **Minor** | 记录稍后处理 / Note for later |
| **审查者错误** | 用技术理由反驳 / Push back with reasoning |

---

## 集成工作流 / Integration Workflow

### subagent-driven-development 集成

```
┌─────────────────────────────────────────────────────────────┐
│              Subagent-Driven Development 工作流               │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Fresh Subagent 执行任务                                       │
│       │                                                     │
│       ▼                                                     │
│  任务完成 → 请求代码审查 / requesting-code-review           │
│       │                                                     │
│       ▼                                                     │
│  aria:code-reviewer Agent 两阶段审查                          │
│       │                                                     │
│       ├─ Phase 1: 规范检查 (PASS → 继续, FAIL → 返回)           │
│       │                                                     │
│       ├─ Phase 2: 质量检查 (Critical/Important/Minor)            │
│       │                                                     │
│       ▼                                                     │
│  审查报告                                                  │
│       │                                                     │
│       ├─ 有 Critical/Important 问题 → 修复后重新审查            │
│       └─ 无问题或仅 Minor 问题 → 继续下一任务                   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 执行计划集成

```
每批 (3 个任务) 后审查:
  1. 完成任务 1-3
  2. 批量代码审查
  3. 获得反馈、应用
  4. 继续下一批
```

---

## 审查结果解读 / Interpreting Review Results

### Phase 1 结果

| 判定 | 含义 | 行动 |
|------|------|------|
| **PASS** | 规范合规，所有检查点通过 | 继续 Phase 2 |
| **FAIL** | 有关键缺失，阻塞继续 | 修复后重新提交 |

### Phase 2 结果

| 判定 | 含义 | 行动 |
|------|------|------|
| **PASS** | 无问题或仅 Minor 问题 | 可以继续 |
| **PASS_WITH_WARNINGS** | 有 Important 问题 | 建议修复后继续 |
| **FAIL** | 有 Critical 问题 | 必须修复 |

---

## 输出示例 / Output Example

### 示例 1: Phase 1 FAIL

```
## Phase 1: 规范合规性检查

**判定**: FAIL

#### 阻塞问题 (Blocking Issues)

1. **计划功能缺失**
   - 文件: `src/auth/password-reset.ts`
   - 缺少: 密码强度验证
   - 为什么重要: 安全要求
   - 如何修复: 添加强度验证逻辑

**审查终止**: 请修复上述问题后重新提交。
```

### 示例 2: Phase 1 PASS + Phase 2 PASS_WITH_WARNINGS

```
## Phase 1: 规范合规性检查

**判定**: PASS
所有检查点通过，继续 Phase 2...

## Phase 2: 代码质量检查

#### 优点
- 清晰的架构设计
- 良好的错误处理

#### 问题

##### Important (应该修复)
1. CLI 缺少帮助文本
2. 日期验证缺失

##### Minor (建议修复)
1. 缺少进度指示器

#### 评估
**是否可以继续?**: 需要修复
**理由**: 核心实现可靠，Important 问题容易修复
```

---

## Agent 模板 / Agent Template

审查模板位于: `code-reviewer.md`

```
占位符变量 / Placeholders:
  {WHAT_WAS_IMPLEMENTED}  - 实现描述
  {PLAN_OR_REQUIREMENTS}  - 计划参考
  {BASE_SHA}               - 起始 SHA
  {HEAD_SHA}               - 结束 SHA
```

---

## 相关文档 / Related Documentation

| 文档 | 路径 / Path |
|------|------------|
| Agent 定义 | `aria/agents/code-reviewer.md` |
| Superpowers 参考 | https://github.com/obra/superpowers/blob/main/skills/requesting-code-review/SKILL.md |
| Superpowers 模板 | https://github.com/obra/superpowers/blob/main/skills/requesting-code-review/code-reviewer.md |
| 对比分析 | `docs/analysis/aria-vs-superpowers-comparison.md` |
| OpenSpec 提案 | `openspec/changes/superpowers-two-phase-review/proposal.md` |

---

## FAQ

### Q: 什么时候必须请求代码审查？

**A**: 在以下场景必须请求审查：
- subagent-driven development 中每个任务完成后
- 完成主要功能后
- 合并到主分支前

### Q: Phase 1 FAIL 后可以继续吗？

**A**: 不可以。Phase 1 FAIL 意味着有关键缺失，必须修复后重新提交审查。这是为了确保问题在复合前被捕获。

### Q: Minor 问题可以忽略吗？

**A**: Minor 问题不影响继续，但建议记录下来稍后处理。积累的 Minor 问题可能成为技术债务。

### Q: 可以直接调用 aria:code-reviewer Agent 吗？

**A**: 可以，但建议通过本 Skill 调用，以确保正确的参数传递和上下文准备。

---

**版本**: 1.0.0
**创建日期**: 2026-02-06
**维护**: Aria 项目组
**许可**: MIT

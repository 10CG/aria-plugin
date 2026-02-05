---
name: brainstorm
description: |
  AI-DDD 头脑风暴引擎，通过多轮对话澄清需求、记录设计决策、生成结构化输出。
  支持问题空间探索、需求分解、技术方案设计三层模式。

  使用场景："我要做个新功能"、"如何设计这个功能"、"讨论技术方案"

argument-hint: "[mode] [topic]"
disable-model-invocation: false
user-invocable: true
allowed-tools: Read, Glob, Grep, Bash, AskUserQuestion
---

# 头脑风暴引擎 (Brainstorm v1.1)

> **版本**: 1.1.0 | **角色**: AI-DDD 协作思考的核心载体
> **状态**: Phase 1 核心框架已实现，Phase 2 集成完成

---

## 快速开始

### 我应该使用这个 Skill 吗？

**使用场景**:
- 需求还不清晰，需要多轮讨论澄清
- 需要记录设计决策和"为什么"的思考过程
- 需要在多个方案之间做选择
- 需要探索问题的本质而非急于实现

**不使用场景**:
- 需求明确，直接进入实现 → 使用 `phase-b-developer`
- 简单 bug 修复 → 使用 `quick-fix`
- 只需要生成文档 → 使用 `spec-drafter`

---

## 核心功能

| 功能 | 描述 |
|------|------|
| **智能引导对话** | 根据输入模糊度选择引导策略，防止过早收敛 |
| **决策记录** | 结构化记录"为什么选 A 而非 B"，可追溯 |
| **约束管理** | 收集并验证业务/技术/团队约束 |
| **方案对比** | 多维度方案分析，量化对比 |
| **领域建模** | 统一业务术语，识别领域边界 |
| **输出同步** | 自动生成 OpenSpec/PRD 草案 |

---

## 工作模式

### Mode 1: problem (问题空间探索)

```yaml
触发: 用户输入模糊，state-scanner 检测到新功能想法
目标: 澄清问题本质，区分真需求 vs 伪需求
输出: problem-definition.md + 决策: 是否需要 PRD
```

### Mode 2: requirements (需求分解)

```yaml
触发: PRD 创建时，功能优先级讨论
目标: 分解为 User Stories，确定优先级
输出: user-stories/US-*.md + 优先级矩阵
```

### Mode 3: technical (技术方案设计)

```yaml
触发: OpenSpec 创建前，架构选型讨论
目标: 技术方案设计，技术选型，风险评估
输出: decision-log.md + proposal.md 草案
```

---

## 执行流程

### 阶段 1: 初始化

```yaml
步骤 1: 模式检测
  输入分析: 用户意图识别，模糊度评估 (0-1)
  决策:
    - 高模糊度 (>=0.6) → problem 模式
    - 中模糊度 (0.3-0.6) + 有 PRD → requirements 模式
    - 低模糊度 (<0.3) + 有 US → technical 模式

步骤 2: 上下文加载
  检查: PRD? OpenSpec? 决策历史? 项目约束?

步骤 3: 引导策略选择
  选择模板: 开放探索型 / 结构化分解型 / 方案对比型
```

---

### 阶段 2: 对话引导

#### 状态机概览

```
INIT → CLARIFY → EXPLORE → CONVERGE → SUMMARY → COMPLETE
```

| 状态 | 目标 | 提问策略 |
|------|------|----------|
| **CLARIFY** | 统一术语 | "你说的 {术语} 具体指什么？" |
| **EXPLORE** | 探索选项 | "实现 {目标} 有哪些可能的方式？" |
| **CONVERGE** | 收敛方案 | "方案 {A} 和 {B} 的权衡是什么？" |
| **SUMMARY** | 确认决策 | "所以选择 {方案}，理由是 {理由}，对吗？" |

**详细定义**: [STATE_MACHINE.md](references/STATE_MACHINE.md)
**深度控制**: [DEPTH_CONTROL.md](references/DEPTH_CONTROL.md)
**决策记录**: [DECISION_WORKFLOW.md](references/DECISION_WORKFLOW.md)
**约束配置**: [config/constraints.yaml](config/constraints.yaml)

#### 引导策略矩阵

| 状态 | 目标 | 模板 |
|------|------|------|
| CLARIFY | 统一术语 | "你说的 {术语} 具体指什么？能举个例子吗？" |
| EXPLORE | 探索选项 | "实现 {目标} 有哪些可能的方式？有没有考虑过..." |
| CONVERGE | 收敛方案 | "方案 {A} 和 {B} 在 {维度} 上的权衡是什么？" |
| SUMMARY | 确认决策 | "所以综合来看，我们选择 {方案}，理由是 {理由}，对吗？" |

---

### 阶段 3: 输出生成

```yaml
problem 模式:
  主要: docs/decisions/problem-{id}.md
  可选: 触发 spec-drafter (创建 PRD)

requirements 模式:
  主要: docs/decisions/requirements-{id}.md + user-stories/
  可选: 更新 PRD

technical 模式:
  主要: docs/decisions/technical-{id}.md
  可选: openspec/changes/proposal.md (自动填充)
```

---

## 引导模板

**详细模板文件**:
- [problem.md](templates/problem.md) - 问题空间探索引导
- [requirements.md](templates/requirements.md) - 需求分解引导
- [technical.md](templates/technical.md) - 技术方案设计引导
- [common.md](templates/common.md) - 通用追问技巧

---

## 约束管理

### 约束分类

| 类别 | 约束示例 |
|------|----------|
| **business** | 预算、时间、合规 (GDPR)、资源 |
| **technical** | 部署方式、技术栈、性能、扩展性 |
| **team** | 技能、偏好、容量、协作方式 |

**完整约束库**: [config/constraints.yaml](config/constraints.yaml)

### 约束验证流程

```
1. 收集约束 (项目配置 + 对话提取)
2. 方案过滤 (检查硬约束)
3. 风险评估 (评估软约束)
4. 记录决策
```

---

## 与其他 Skills 的集成

### state-scanner 集成

```yaml
触发: 检测到模糊需求，复杂度 >= Level 2
推荐: "发现新功能想法，建议先进行头脑风暴"
选项: [1] 开始头脑风暴 [2] 直接创建 OpenSpec [3] 跳过
```

### spec-drafter 集成

```yaml
输入: 决策记录 + 约束条件 + 方案选择
行为: 自动填充 proposal.md 背景、预填充技术方案、引用决策 ID
```

### requirements-validator 集成

```yaml
验证: User Story 与决策记录一致性、约束条件是否违反
```

---

## 配置

### 项目级配置

```yaml
# .claude/aria.local.md
brainstorm:
  enabled: true
  trigger_mode: auto  # auto | always | manual
  auto_trigger:
    fuzziness_threshold: 0.6
    complexity_threshold: Level2
  conversation:
    max_rounds:
      problem: 10
      requirements: 15
      technical: 8
  output:
    save_decisions: true
    decision_dir: docs/decisions/
    auto_sync_openspec: true
```

### 会话级配置

```bash
/brainstorm problem "添加AI功能" \
  --fuzziness high \
  --max-rounds 15 \
  --constraints budget:$500
```

---

## 使用示例

**完整对话示例**: 见 [examples/](examples/)

### Problem 模式快速示例

```yaml
用户: /brainstorm problem "我想做个智能客服"

AI: 你说的 AI 功能具体指什么？
    a) 智能推荐  b) 自动补全  c) 对话助手  d) 其他

用户: c，智能客服

AI: 要解决什么问题？
    ... (继续澄清)

[最终输出]
╔═══════════════════════════════════════════════════════════╗
║                     问题定义                               ║
║ 核心问题: 用户咨询得不到及时响应                           ║
║ 约束: 预算<$500, 私有化部署                               ║
╚═══════════════════════════════════════════════════════════╝
```

---

## 输出文件规范

### 文件命名

```yaml
决策日志: docs/decisions/{mode}-{sequence}.md
示例: problem-001.md, technical-002.md
```

### 决策 ID 格式

```yaml
格式: DEC-{YYYYMMDD}-{序号}
示例: DEC-20260205-001
```

### 决策模板

```markdown
# 决策: DEC-{id} - {title}

> **日期**: {date} | **模式**: {mode}

## 背景
{背景描述}

## 约束条件
| 类型 | 约束 | 影响 |
|------|------|------|

## 最终选择
**方案**: {selected}

## 理由
{理由列表}

## 风险与缓解
| 风险 | 缓解措施 |
|------|----------|
```

---

## 错误处理

**完整错误场景**: 见 [examples/error-scenarios.md](examples/error-scenarios.md)

| 错误 | 处理 |
|------|------|
| 无法收敛 | 展示状态，提供强制选择/放宽约束选项 |
| 约束冲突 | 识别冲突，建议放宽约束 |
| 无可行方案 | 展示排除原因，建议新方案 |
| 用户中断 | 保存草稿，提供恢复方式 |

---

## 检查清单

### 使用前
- [ ] 有需要澄清的需求或想法
- [ ] 愿意进行多轮对话
- [ ] 准备记录决策

### 使用中
- [ ] 核心问题已澄清
- [ ] 约束条件已收集
- [ ] 方案已充分讨论
- [ ] 决策理由已记录

### 使用后
- [ ] 决策日志已创建
- [ ] 后续步骤已明确
- [ ] 相关文档已同步

---

## 相关文档

- [SKILL_DESIGN.md](./SKILL_DESIGN.md) - 设计文档
- [STATE_MACHINE.md](references/STATE_MACHINE.md) - 状态机详解
- [DEPTH_CONTROL.md](references/DEPTH_CONTROL.md) - 深度控制算法
- [DECISION_WORKFLOW.md](references/DECISION_WORKFLOW.md) - 决策记录流程
- [state-scanner](../state-scanner/SKILL.md) - 状态扫描入口
- [spec-drafter](../spec-drafter/SKILL.md) - 规范创建

---

**最后更新**: 2026-02-05
**Skill版本**: 1.1.0 (结构优化版)

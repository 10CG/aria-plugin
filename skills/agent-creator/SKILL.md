---
name: agent-creator
description: "Generate project-specific Agent configurations based on coverage gap analysis. Creates STCO-formatted Agent definitions with capabilities tags in .aria/agents/. Use when coverage-report.yaml identifies gaps that need new Agents."
---

# Agent 配置生成器

基于覆盖度缺口分析,生成项目专属 Agent 配置。

## 使用场景

- "根据缺口报告生成 Agent"
- "给这个项目创建一个数据库专家 Agent"
- agent-gap-analyzer 之后的第三步

## 前置条件

- `.aria/coverage-report.yaml` 存在 (由 agent-gap-analyzer 生成)
- 用户已确认需要生成的 Agent 列表

## 流程

### 1. 读取缺口

从 `.aria/coverage-report.yaml` 的 `gaps[]` 读取:
- suggested_agent.name
- suggested_agent.capabilities
- suggested_agent.scope

### 2. 匹配技术栈模板

按项目 tech_stack 选择模板:
- 模板目录: `${CLAUDE_PLUGIN_ROOT}/skills/agent-creator/templates/`
- 优先匹配具体技术栈, fallback 到 generic

### 3. 生成 Agent 定义

使用 few-shot exemplar (参考 code-reviewer + backend-architect 的结构) 生成:

**frontmatter** (STCO + capabilities):
```yaml
---
name: <name>
description: |
  <Scope: 领域名词>
  Use when: <触发场景>. NOT for <消歧>.
  Expects: <输入>
  Produces: <产出>
capabilities:
  - <tag1>
  - <tag2>
model: sonnet
color: green
---
```

**body** 最低质量标准:
- Focus Areas: 3+ 项
- Approach: 3+ 步骤
- Output: 2+ 类产出
- 不超过 60 行

### 4. 预览 + 确认

- 默认: 展示生成的 Agent 完整内容, 等待用户确认
- `--dry-run`: 仅展示不写入
- `--confirm`: 跳过预览直接写入

### 5. 写入

- 路径: `.aria/agents/<name>.md`
- 自动创建 `.aria/agents/` 目录 (如不存在)

## 同名保护

写入前检查:
1. `.aria/agents/<name>.md` 已存在 → 警告 "项目级 Agent 已存在, 是否覆盖?"
2. 插件级 `agents/<name>.md` 同名 → 警告 "将覆盖插件级 Agent 路由, 确认?"

## 重要

- 生成的 Agent 用于项目级, 不提交到 aria-plugin
- body 质量依赖 LLM, few-shot exemplar 提升一致性
- 人工确认是必须步骤, 不可跳过 (--confirm 仅用于脚本/自动化)

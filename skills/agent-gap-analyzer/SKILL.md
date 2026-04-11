---
name: agent-gap-analyzer
description: "Analyze project needs against existing Agent capabilities to identify coverage gaps. Reads project-profile.yaml and Agent capabilities tags, outputs deterministic coverage report. Use when evaluating which Agents are missing for a project."
---

# Agent 覆盖度分析器

对比项目需求与现有 Agent 能力,识别覆盖缺口。

## 使用场景

- "这个项目还缺什么 Agent?"
- "现有 Agent 能覆盖多少?"
- project-analyzer 之后的第二步

## 前置条件

- `.aria/project-profile.yaml` 存在 (由 project-analyzer 生成)
- Agent frontmatter 含 `capabilities` 字段 (US-010 STCO + US-011 T0)

## 流程

### 1. 加载输入

- 读取 `.aria/project-profile.yaml`
- 读取所有 Agent 的 capabilities:
  - 插件级: `${CLAUDE_PLUGIN_ROOT}/agents/*.md` frontmatter
  - 项目级: `.aria/agents/*.md` frontmatter (如存在)
- 读取 `${CLAUDE_PLUGIN_ROOT}/references/capabilities-taxonomy.yaml` 做标签规范化

### 2. 推导需求场景

从 project-profile 的 tech_stack + patterns 映射到能力标签需求:

```yaml
# 场景映射规则 (确定性, 非 LLM 推断)
tech_stack_mapping:
  orm: "Prisma" → 需求: [orm-migration, query-optimization, database-schema]
  framework: "Express" → 需求: [api-design, performance-optimization]
  testing: "Jest" → 需求: [test-strategy]
  ci_cd: "GitHub Actions" → 需求: [ci-cd-pipeline]
  deployment: "Docker" → 需求: [infrastructure]
```

### 3. 标签规范化

使用 capabilities-taxonomy.yaml 的同义词映射:
- Agent capability `database-schema` 匹配需求 `db-design` (同义词)
- 规范化后再做匹配,避免假缺口

### 4. 匹配计算

对每个需求场景:
- 遍历所有 Agent capabilities
- match_rate = 命中标签数 / 需求标签数
- covered: match_rate >= 0.5
- gap: match_rate < 0.5

### 5. 输出

`.aria/coverage-report.yaml` (schema_version: "1"):

```yaml
schema_version: "1"
project: "kairos"
timestamp: "2026-04-11T..."
covered:
  - scenario: "API design"
    matched_agent: "backend-architect"
    matched_capabilities: ["api-design"]
    match_rate: 1.0
gaps:
  - scenario: "ORM migration"
    required_capabilities: ["orm-migration", "query-optimization"]
    best_partial_match:
      agent: "backend-architect"
      matched: ["database-schema"]
      match_rate: 0.33
    suggested_agent:
      name: "database-specialist"
      capabilities: ["orm-migration", "query-optimization", "database-schema"]
summary:
  total_scenarios: 8
  covered: 5
  gaps: 3
  coverage_rate: 62.5%
```

## 重要

- 匹配基于 capabilities 标签 (确定性), 不使用 LLM 解析 description
- match_rate 是标签重合率, 非 AI 评分
- 场景列表来自规则映射, 非每次 LLM 推断

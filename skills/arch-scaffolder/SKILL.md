---
name: arch-scaffolder
description: |
  从 PRD 生成 System Architecture 文档骨架，自动提取关键信息并填充模板。

  使用场景：
  - "从 PRD 生成架构文档"
  - "创建系统架构骨架"
  - "初始化架构文档"
  - "arch-scaffolder"

  特性: PRD 分析、模板填充、智能提取、架构建议
allowed-tools: Read, Glob, Grep, Write
---

# Architecture Scaffolder Skill

> **版本**: 1.0.0 | **层级**: Layer 2 (Business Skill) | **分类**: Architecture Skills

## 快速开始

### 我应该使用这个 Skill 吗？

**使用场景**:
- PRD 已批准，需要创建 System Architecture
- 快速启动架构文档编写
- 确保架构文档结构符合规范

**不使用场景**:
- 已有架构文档需要更新 → 使用 `arch-update`
- 搜索架构信息 → 使用 `arch-search`
- 验证架构文档 → 使用 `requirements-validator`

---

## 核心功能

| 功能 | 描述 |
|------|------|
| **analyze-prd** | 分析 PRD 提取关键架构信息 |
| **generate-skeleton** | 生成架构文档骨架 |
| **suggest-decisions** | 建议技术决策点 |
| **validate-output** | 验证生成的骨架符合规范 |

---

## 执行流程

### 阶段 1: PRD 定位与验证

```yaml
定位路径:
  主项目: docs/requirements/prd-*.md
  模块级: {module}/docs/requirements/prd-*.md

验证项:
  - PRD 文件存在
  - PRD 状态为 approved (建议) 或 draft
  - PRD 包含必需章节

输出:
  prd_found: true/false
  prd_path: "docs/requirements/prd-xxx.md"
  prd_status: approved/draft
  prd_version: "1.0.0"
```

### 阶段 2: PRD 内容分析

```yaml
提取内容:
  basic_info:
    - 项目名称 (从标题)
    - 版本 (从 header)
    - 创建日期

  goals_section:
    - 产品目标
    - 成功标准
    - 质量属性要求

  scope_section:
    - 功能范围 (Must-have, Nice-to-have)
    - 模块划分 (如有)
    - 排除范围

  constraints:
    - 技术约束
    - 业务约束
    - 时间约束

  stakeholders:
    - 用户角色
    - 利益相关者

输出:
  extracted_info:
    project_name: "{name}"
    modules: [module1, module2, ...]
    quality_attributes: [performance, security, ...]
    constraints: [constraint1, constraint2, ...]
    stakeholders: [stakeholder1, ...]
```

### 阶段 3: 架构骨架生成

```yaml
生成内容:
  version_header:
    version: "0.1.0"
    status: "Draft"
    created: "{today}"
    parent_document: "{prd_path}"

  sections:
    executive_summary:
      - 从 PRD 目标生成摘要
      - 填充模块概览

    system_overview:
      - 从 PRD 提取目标和约束
      - 生成质量属性表

    architecture_diagram:
      - 生成占位符图
      - 基于模块列表生成初始结构

    module_boundaries:
      - 从 PRD 模块划分生成表格
      - 填充责任说明占位符

    technology_decisions:
      - 生成 TD-001 占位符
      - 基于约束建议决策点

    cross_cutting_concerns:
      - 根据质量属性生成章节
      - 填充标准关注点

    data_architecture:
      - 生成基础数据存储表
      - 添加占位符

    integration_patterns:
      - 基于模块关系生成模式
      - 生成契约位置占位符

    evolution_roadmap:
      - 从 PRD 版本路线图提取
      - 生成阶段占位符

    related_documents:
      - 链接 PRD
      - 生成模块架构链接占位符

输出路径:
  docs/architecture/system-architecture.md
```

### 阶段 4: 智能建议

```yaml
建议内容:
  technology_decisions:
    - 基于项目类型建议技术栈
    - 基于约束建议架构模式
    - 基于质量属性建议技术选型

  missing_sections:
    - 检测 PRD 中缺失但架构需要的信息
    - 生成待完善列表

  next_steps:
    - 建议优先完善的章节
    - 建议需要做的技术决策

输出:
  suggestions:
    tech_decisions:
      - "建议: 考虑使用 {technology} 因为 {reason}"
    missing_info:
      - "PRD 未明确: {topic}，架构需要补充"
    next_steps:
      - "优先完善: §5 Technology Decisions"
      - "需要决策: 数据库选型"
```

---

## 输出格式

### 生成报告

```yaml
scaffolder_result:
  timestamp: "2026-01-04T10:00:00+08:00"

  prd:
    path: "docs/requirements/prd-xxx.md"
    status: approved
    version: "1.0.0"

  extraction:
    project_name: "{name}"
    modules_found: N
    quality_attributes: N
    constraints: N

  generation:
    output_path: "docs/architecture/system-architecture.md"
    sections_generated: 10
    placeholders_added: N

  suggestions:
    tech_decisions: N
    missing_info: N
    next_steps: [...]

  validation:
    structure_valid: true
    warnings: []
```

### 生成的文档结构

```
docs/architecture/system-architecture.md
├── Version Header (自动填充)
├── §1 Executive Summary (部分填充)
├── §2 System Overview (部分填充)
├── §3 Architecture Diagram (占位符)
├── §4 Module Boundaries (基于 PRD 填充)
├── §5 Technology Decisions (占位符 + 建议)
├── §6 Cross-Cutting Concerns (占位符)
├── §7 Data Architecture (占位符)
├── §8 Integration Patterns (占位符)
├── §9 Evolution Roadmap (基于 PRD 填充)
├── §10 Related Documents (自动填充)
└── Version History (自动填充)
```

---

## 使用示例

### 示例 1: 从 PRD 生成骨架

```
用户: 从 PRD 生成架构文档

助手执行:
1. 定位 PRD 文件: docs/requirements/prd-todo-app-v1.md
2. 提取项目信息: Todo App, 3 modules, 5 quality attributes
3. 生成架构骨架: docs/architecture/system-architecture.md
4. 生成建议: 3 tech decisions needed

输出:
scaffolder_result:
  prd:
    path: "docs/requirements/prd-todo-app-v1.md"
    status: approved
  extraction:
    project_name: "Todo App"
    modules_found: 3
  generation:
    output_path: "docs/architecture/system-architecture.md"
    sections_generated: 10
  suggestions:
    next_steps:
      - "完善 §5 Technology Decisions"
      - "添加架构图"
      - "明确模块边界"
```

### 示例 2: 指定模块生成

```
用户: 为 mobile 模块生成架构骨架

助手执行:
1. 定位 PRD: mobile/docs/requirements/prd-mobile.md
2. 提取模块信息
3. 生成: mobile/docs/ARCHITECTURE.md

输出:
scaffolder_result:
  generation:
    output_path: "mobile/docs/ARCHITECTURE.md"
```

---

## 模板引用

生成的骨架基于以下模板：

```
standards/templates/system-architecture-template.md
```

可通过修改模板自定义生成内容。

---

## 与其他 Skills 的关系

```
┌─────────────────────────────────────────────────────────────────┐
│  state-scanner (Layer 3)                                        │
│      │ 推荐 create-architecture                                  │
│      ▼                                                          │
│  arch-scaffolder (Layer 2) ◄── 本 Skill                         │
│      │ 生成骨架后                                                │
│      ▼                                                          │
│  arch-update (Layer 2) ── 后续更新架构                           │
│      │                                                          │
│      ▼                                                          │
│  requirements-validator (Layer 2) ── 验证生成的文档              │
└─────────────────────────────────────────────────────────────────┘
```

---

## 错误处理

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| PRD 不存在 | 未创建 PRD | 提示先创建 PRD |
| 架构文档已存在 | 目标路径已有文件 | 提示使用 arch-update |
| PRD 结构不完整 | PRD 缺少必需章节 | 列出缺失章节，继续生成 |
| 模块信息不足 | PRD 未明确模块划分 | 生成占位符，提示补充 |

---

## 配置选项

```yaml
scaffolder_options:
  # 输出路径
  output_path: "docs/architecture/system-architecture.md"

  # 是否覆盖已有文件
  overwrite: false

  # 是否生成模块级架构
  module_level: false

  # 是否包含建议
  include_suggestions: true

  # 模板路径
  template_path: "standards/templates/system-architecture-template.md"
```

---

## 相关文档

- **模板**: `standards/templates/system-architecture-template.md`
- **规范**: `standards/core/documentation/system-architecture-spec.md`
- **PRD 模板**: `standards/templates/prd-template.md`
- **验证**: `.claude/skills/requirements-validator/SKILL.md`

---

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-01-04 | 初始版本 - 支持从 PRD 生成架构骨架 |

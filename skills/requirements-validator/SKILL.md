---
name: requirements-validator
description: |
  验证产品文档（PRD、System Architecture、User Story）格式，检查关联完整性。

  使用场景："验证需求文档"、"检查 PRD 格式"、"检查 User Story 关联"
argument-hint: "[--check-mode]"
disable-model-invocation: false
user-invocable: true
allowed-tools: Read, Glob, Grep
---

# Requirements Validator Skill

> **版本**: 2.1.0 | **层级**: Layer 2 (Business Skill) | **分类**: Requirements Skills

## 快速开始

### 我应该使用这个 Skill 吗？

**使用场景**:
- 验证 PRD 文档格式是否符合模板
- 验证 System Architecture 文档格式
- 验证 User Story 格式是否完整
- 检查文档层次和引用关系
- 检查 PRD ↔ Story ↔ OpenSpec 关联
- 分析需求覆盖率

**不使用场景**:
- 同步状态到 UPM → 使用 `requirements-sync`
- 同步到 Forgejo → 使用 `forgejo-sync`
- 整体项目状态扫描 → 使用 `state-scanner`

---

## 核心功能

| 功能 | 描述 |
|------|------|
| **validate-prd** | 验证 PRD 文档格式和必需节 |
| **validate-architecture** | 验证 System Architecture 文档格式 |
| **validate-story** | 验证 User Story 格式和字段 |
| **validate-hierarchy** | 验证文档层次结构和引用 |
| **check-associations** | 检查文档间双向关联 |
| **validate-chain** | 验证 PRD→Architecture→Stories 链路完整性 |
| **coverage-analysis** | 分析需求覆盖率 |

---

## 执行流程

### 阶段 1: 文件发现

```yaml
发现路径:
  prd_pattern: "{module}/docs/requirements/prd-*.md"
  architecture_pattern:
    - "docs/architecture/system-architecture.md"
    - "{module}/docs/ARCHITECTURE.md"
  story_pattern: "{module}/docs/requirements/user-stories/US-*.md"

输出:
  prd_files: [文件路径列表]
  architecture_files: [文件路径列表]
  story_files: [文件路径列表]
  requirements_configured: true/false
```

### 阶段 2: PRD 验证

```yaml
检查项:
  required_sections:
    - "## 文档目的"
    - "## 产品定位"
    - "## 功能范围"

  subsections:
    产品定位:
      - 目标用户
      - 核心价值
      - 成功标准
    功能范围:
      - Must-have
      - Nice-to-have
      - Out of Scope

  story_references:
    - 检查 User Story 表格存在
    - 提取 Story ID 列表

输出:
  prd_valid: true/false
  prd_issues: [{file, section, issue, severity}]
```

### 阶段 3: System Architecture 验证 (NEW)

```yaml
检查项:
  version_header:
    required_fields:
      - "Version" (X.Y.Z 格式)
      - "Status" (Draft|Review|Active|Deprecated|Archived)
      - "Created" (YYYY-MM-DD 格式)
    optional_fields:
      - "Parent Document"
      - "Last Updated"

  required_sections:
    - "## 1. Executive Summary" 或 "## 概述"
    - "## Architecture Diagram" 或 "## 架构图"
    - "## Module Boundaries" 或 "## 模块边界"
    - "## Technology Decisions" 或 "## 技术决策"

  diagrams:
    - 至少包含一个 ASCII 图或 Mermaid 图
    - 代码块类型: ```, ```mermaid, ```yaml

  parent_reference:
    - 如果是系统级架构，应引用 PRD
    - 如果是模块级架构，应引用系统架构

  version_history:
    - 包含版本历史表格

输出:
  architecture_valid: true/false
  architecture_issues: [{file, section, issue, severity}]
```

### 阶段 4: User Story 验证

```yaml
检查项:
  header_fields:
    - Story ID (格式: US-XXX)
    - Status (draft/ready/in_progress/done/blocked)
    - Priority (HIGH/MEDIUM/LOW)
    - Created (YYYY-MM-DD)
    - Forgejo Issue (可选)
    - Forgejo Milestone (可选)

  story_format:
    - "As a {role}"
    - "I want {feature}"
    - "So that {value}"

  acceptance_criteria:
    - 至少一个 Scenario
    - Given/When/Then 格式

输出:
  stories_valid: true/false
  story_issues: [{file, field, issue, severity}]
```

### 阶段 5: 文档层次验证 (NEW)

```yaml
检查项:
  层次定义:
    L0: docs/requirements/prd-*.md
    L1: docs/architecture/system-architecture.md
    L2: {module}/docs/requirements/prd-*.md, {module}/docs/ARCHITECTURE.md
    L3: {module}/docs/architecture/*.md, shared/contracts/*.yaml
    L4: 代码文档、指南

  向上引用检查:
    - L1 文档应引用 L0 PRD
    - L2 文档应引用 L1 系统架构
    - L3 文档应引用 L2 模块架构

  孤立文档检查:
    - 检测无引用的文档

  循环引用检查:
    - 检测 A→B→C→A 模式

输出:
  hierarchy_valid: true/false
  hierarchy_issues: [{file, issue, severity}]
```

### 阶段 6: 关联检查

```yaml
检查项:
  prd_to_story:
    - PRD 中列出的 Story 文件是否存在

  story_to_prd:
    - Story 引用的 PRD 文件是否存在

  story_to_openspec:
    - Story 引用的 OpenSpec 是否存在

  architecture_references:
    - 架构文档引用的文件是否存在
    - Parent Document 路径是否有效

输出:
  associations_valid: true/false
  association_issues: [{source, target, issue, severity}]
```

### 阶段 7: 覆盖率分析

```yaml
分析项:
  status_distribution:
    draft: N
    ready: N
    in_progress: N
    done: N
    blocked: N

  openspec_coverage:
    with_openspec: N
    without_openspec: N
    coverage_rate: "X%"

  architecture_coverage:
    modules_with_architecture: N
    modules_without_architecture: N
    architecture_rate: "X%"

输出:
  coverage:
    total: N
    by_status: {...}
    with_openspec: N
    without_openspec: N
    coverage_rate: "X%"
    architecture_coverage: "X%"
```

### 阶段 8: 需求链路验证 (NEW)

```yaml
检查项:
  chain_definition:
    PRD (L0) → System Architecture (L1) → User Stories → OpenSpec
    产品需求     系统架构设计              可实现需求单元   技术实现方案

  prd_to_architecture:
    检查:
      - System Architecture 是否存在
      - Architecture 是否引用 PRD (parent_prd 字段)
      - PRD approved 时 Architecture 应该存在
    时序约束:
      - Architecture.created >= PRD.created
      - Architecture.last_updated >= PRD.last_updated (如果 PRD 更新)

  architecture_to_stories:
    检查:
      - User Stories 是否在 Architecture 之后创建
      - Stories 的模块边界是否与 Architecture 一致
      - Ready 状态的 Stories 数量是否合理
    时序约束:
      - Story.created >= Architecture.created

  chain_status_consistency:
    检查:
      - PRD status=draft → Architecture 不应是 active
      - Architecture status=draft → Stories 不应是 in_progress/done
      - Architecture status=outdated → 阻止新 Stories 进入 ready

  openspec_linkage:
    检查:
      - Ready Stories 是否有关联的 OpenSpec
      - OpenSpec 是否引用正确的 Story

输出:
  chain_validation:
    chain_valid: true/false
    prd_to_architecture:
      valid: true/false
      issues: []
    architecture_to_stories:
      valid: true/false
      issues: []
    status_consistency:
      valid: true/false
      issues: []
    openspec_linkage:
      valid: true/false
      issues: []
```

---

## 验证模式

| 模式 | 描述 | 用途 |
|------|------|------|
| `full` | 完整验证 (所有检查) | 迭代规划、提交前检查 |
| `quick` | 快速验证 (仅必需字段) | 日常开发 |
| `check` | 只读模式 (不修改文件) | CI/CD 检查 |
| `architecture` | 仅架构文档验证 | 架构审查 |
| `hierarchy` | 仅层次结构验证 | 文档重构后验证 |
| `chain` | 需求链路验证 | PRD→Architecture→Stories 完整性检查 |

---

## 输出格式

```yaml
validation_result:
  mode: "full|quick|check|architecture|hierarchy|chain"
  timestamp: "2026-01-01T10:00:00+08:00"

  prd:
    valid: true/false
    files_checked: N
    issues: []

  architecture:
    valid: true/false
    files_checked: N
    issues: []

  stories:
    valid: true/false
    files_checked: N
    issues: []

  hierarchy:
    valid: true/false
    layers_checked: [L0, L1, L2, L3]
    issues: []

  associations:
    valid: true/false
    issues: []

  chain_validation:                     # 新增: 需求链路验证
    chain_valid: true/false
    prd_to_architecture:
      valid: true/false
      issues: []
    architecture_to_stories:
      valid: true/false
      issues: []
    status_consistency:
      valid: true/false
      issues: []
    openspec_linkage:
      valid: true/false
      issues: []

  coverage:
    total: N
    by_status:
      draft: N
      ready: N
      in_progress: N
      done: N
      blocked: N
    with_openspec: N
    without_openspec: N
    coverage_rate: "X%"
    architecture_coverage: "X%"

  summary:
    errors: N
    warnings: N
    info: N
    overall_valid: true/false
```

---

## 严重级别

| 级别 | 含义 | 示例 |
|------|------|------|
| `error` | 必须修复 | 缺少必需字段、文件不存在、循环引用 |
| `warning` | 建议修复 | 格式不规范、缺少可选节、孤立文档 |
| `info` | 信息提示 | 缺少 OpenSpec 关联、建议添加图表 |

---

## 使用示例

### 完整验证

```
用户: 验证所有需求文档

助手执行:
1. 发现 docs/ 下的所有产品文档
2. 验证 PRD 格式
3. 验证 System Architecture 格式
4. 验证所有 Story 格式
5. 验证文档层次结构
6. 检查关联完整性
7. 生成覆盖率报告

输出:
validation_result:
  prd:
    valid: true
    files_checked: 2
  architecture:
    valid: true
    files_checked: 3
  stories:
    valid: false
    files_checked: 8
    issues:
      - file: "US-003-xxx.md"
        field: "Status"
        issue: "无效状态值: 'pending'"
        severity: error
  hierarchy:
    valid: true
    layers_checked: [L0, L1, L2]
  coverage:
    total: 8
    with_openspec: 5
    coverage_rate: "62.5%"
    architecture_coverage: "100%"
```

### 架构验证

```
用户: 验证系统架构文档

助手执行:
1. 发现 docs/architecture/ 和 */docs/ARCHITECTURE.md
2. 验证版本头信息
3. 验证必需章节
4. 验证架构图存在
5. 验证引用完整性

输出:
validation_result:
  mode: "architecture"
  architecture:
    valid: true
    files_checked: 3
    issues:
      - file: "backend/docs/ARCHITECTURE.md"
        section: "Technology Decisions"
        issue: "建议添加决策原因"
        severity: warning
```

### 层次验证

```
用户: 验证文档层次结构

助手执行:
1. 构建文档层次树
2. 检查向上引用
3. 检测孤立文档
4. 检测循环引用

输出:
validation_result:
  mode: "hierarchy"
  hierarchy:
    valid: false
    layers_checked: [L0, L1, L2, L3]
    issues:
      - file: "mobile/docs/architecture/old-design.md"
        issue: "孤立文档: 未被任何文档引用"
        severity: warning
      - file: "backend/docs/ARCHITECTURE.md"
        issue: "缺少向上引用: 应引用 system-architecture.md"
        severity: error
```

### 需求链路验证

```
用户: 验证需求链路完整性

助手执行:
1. 检查 PRD → Architecture 链路
2. 检查 Architecture → Stories 链路
3. 检查状态一致性
4. 检查 OpenSpec 关联

输出:
validation_result:
  mode: "chain"
  chain_validation:
    chain_valid: false
    prd_to_architecture:
      valid: false
      issues:
        - issue: "PRD 已 approved 但 Architecture 不存在"
          severity: error
          suggestion: "创建 System Architecture 文档"
    architecture_to_stories:
      valid: true
      issues: []
    status_consistency:
      valid: false
      issues:
        - issue: "Architecture status=outdated 但有 Stories 是 in_progress"
          severity: warning
          suggestion: "更新 Architecture 或暂停开发"
    openspec_linkage:
      valid: true
      issues: []
```

---

## 与其他 Skills 的关系

```
┌─────────────────────────────────────────────────────────────┐
│  state-scanner (Layer 3)                                    │
│      │                                                      │
│      ▼ 调用                                                  │
│  requirements-validator (Layer 2) ◄── 本 Skill              │
│      │                                                      │
│      ▼ 输出供                                                │
│  requirements-sync (Layer 2) ── 使用验证结果更新 UPM         │
└─────────────────────────────────────────────────────────────┘
```

---

## 相关文档

- **规范**:
  - `standards/core/documentation/product-doc-hierarchy.md` (文档层次规范)
  - `standards/core/documentation/system-architecture-spec.md` (System Architecture 规范)
- **PRD 模板**: `standards/templates/prd-template.md`
- **Story 模板**: `standards/templates/user-story-template.md`
- **目录结构**: `standards/templates/requirements-directory-structure.md`

---

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 2.1.0 | 2026-01-04 | 添加需求链路验证 (阶段 8)，支持 PRD→Architecture→Stories 完整性检查 |
| 2.0.0 | 2026-01-02 | 添加 System Architecture 验证、文档层次验证 |
| 1.0.0 | 2026-01-01 | 初始版本 - PRD/Story 验证 |

# State Scanner - 推荐规则定义

> 智能工作流推荐引擎的规则配置

## 规则概览

| 规则 ID | 优先级 | 推荐工作流 | 触发条件 |
|---------|--------|-----------|----------|
| `commit_only` | 1 | C.1 only | 已暂存 + 无未暂存 |
| `requirements_issues` | 1.5 | requirements-check | 需求文档验证有错误 |
| `architecture_missing` | 1.6 | create-architecture | PRD 存在但无 Architecture |
| `architecture_outdated` | 1.7 | update-architecture | Architecture 状态为 outdated |
| `architecture_chain_broken` | 1.8 | fix-architecture | 需求链路不完整 |
| `quick_fix` | 2 | quick-fix | ≤3文件 + 简单修复 |
| `feature_with_spec` | 3 | feature-dev | 有 approved OpenSpec |
| `pending_stories` | 3.5 | start-implementation | 有就绪 Story 可实现 |
| `missing_openspec` | 3.8 | create-openspec | Story 无技术方案 |
| `doc_only` | 4 | doc-update | 仅 *.md 文件 |
| `feature_new` | 5 | full-cycle | Level2+ 无 Spec |
| `requirements_info` | 5.5 | (信息提示) | 需求追踪未配置 |

---

## 规则详情

### 1. commit_only (最高优先级)

```yaml
id: commit_only
priority: 1
description: 变更已就绪，只需提交

conditions:
  all:
    - on_feature_branch: true       # 不在 main/develop/master
    - has_staged_changes: true      # 有已暂存的文件
    - no_unstaged_changes: true     # 无未暂存的修改

recommendation:
  workflow: custom
  steps: [C.1]
  reason: "变更已暂存，只需提交"

detection:
  git_commands:
    - "git branch --show-current"   # 检查当前分支
    - "git diff --cached --name-only"  # 检查暂存区
    - "git diff --name-only"        # 检查未暂存
```

### 2. quick_fix

```yaml
id: quick_fix
priority: 2
description: 简单修复，快速流程

conditions:
  all:
    - changed_files: <= 3
    - change_type:
        any: [bugfix, typo, config, format]

  change_type_detection:
    bugfix:
      - commit_intent: contains "fix", "修复", "bug"
      - file_pattern: not new files
    typo:
      - commit_intent: contains "typo", "拼写", "错字"
    config:
      - file_pattern: "*.json", "*.yaml", "*.yml", "*.toml"
    format:
      - commit_intent: contains "format", "格式"

recommendation:
  workflow: quick-fix
  phases: [B, C]
  skip_steps: [B.3]
  reason: "简单修复，使用快速流程"
```

### 3. feature_with_spec

```yaml
id: feature_with_spec
priority: 3
description: 已有 OpenSpec，跳过规划

conditions:
  all:
    - has_openspec: true
    - openspec_status: approved

  openspec_detection:
    scan_path: "openspec/changes/*"
    status_check:
      - proposal.md exists
      - status field = "approved" or "in_progress"

recommendation:
  workflow: feature-dev
  phases: [B, C]
  skip_steps: [A.1, A.2, A.3]
  conditional_skips:
    - if: no_architecture_changes
      skip: [B.3]
  reason: "已有 OpenSpec，跳过规划阶段"
```

### 4. doc_only

```yaml
id: doc_only
priority: 4
description: 仅文档变更

conditions:
  all:
    - all_files_match: "*.md"
    - no_code_changes: true

  file_type_detection:
    docs: ["*.md", "*.mdx", "*.rst"]
    code: ["*.dart", "*.py", "*.js", "*.ts", "*.java", "*.go"]

recommendation:
  workflow: doc-update
  steps: [B.3, C.1]
  reason: "仅文档变更"
```

### 5. feature_new (兜底规则)

```yaml
id: feature_new
priority: 5
description: 新功能开发，完整流程

conditions:
  all:
    - complexity: >= Level2
    - has_openspec: false

  complexity_assessment:
    Level1:
      - changed_files: <= 3
      - single_module: true
    Level2:
      - changed_files: 4-10
      - or: multi_module, new_api, new_service
    Level3:
      - changed_files: > 10
      - or: architecture_change, breaking_change

recommendation:
  workflow: full-cycle
  phases: [A, B, C, D]
  reason: "新功能开发，建议完整流程"
```

---

## 架构相关规则详情

### 1.6 architecture_missing

```yaml
id: architecture_missing
priority: 1.6
description: PRD 存在但缺少 System Architecture

conditions:
  all:
    - prd_exists: true
    - prd_status: approved
    - architecture_exists: false

  detection:
    prd_check: "docs/requirements/prd-*.md" exists and status = approved
    arch_check: "docs/architecture/system-architecture.md" not exists

recommendation:
  workflow: create-architecture
  steps: [arch-scaffolder or manual creation]
  reason: "PRD 已批准，需要创建 System Architecture"
  suggestion:
    - "参考 standards/core/documentation/system-architecture-spec.md"
    - "或使用 arch-scaffolder skill 自动生成骨架"
```

### 1.7 architecture_outdated

```yaml
id: architecture_outdated
priority: 1.7
description: Architecture 状态为 outdated，需要更新

conditions:
  all:
    - architecture_exists: true
    - architecture_status: outdated

  detection:
    arch_check: "docs/architecture/system-architecture.md"
    status_field: Status = outdated

recommendation:
  workflow: update-architecture
  steps: [arch-update]
  reason: "System Architecture 已过时，建议先更新"
  context:
    last_updated: "{architecture.last_updated}"
    prd_updated: "{prd.last_updated}"
```

### 1.8 architecture_chain_broken

```yaml
id: architecture_chain_broken
priority: 1.8
description: PRD → Architecture 链路不完整

conditions:
  all:
    - architecture_exists: true
    - chain_valid: false

  detection:
    chain_issues:
      - architecture 未引用 parent_prd
      - prd 更新时间晚于 architecture
      - parent_prd 不存在

recommendation:
  workflow: fix-architecture
  steps: [arch-update, requirements-sync]
  reason: "需求链路不完整，建议修复"
  context:
    issues: "{chain_issues}"
```

---

## 需求相关规则详情

### 1.5 requirements_issues (高优先级)

```yaml
id: requirements_issues
priority: 1.5
description: 需求文档存在问题，需要先修复

conditions:
  all:
    - requirements_configured: true
    - requirements_validation_errors: true

  validation_detection:
    invoke: requirements-validator (check mode)
    check: validation_result.errors > 0

recommendation:
  workflow: requirements-check
  steps: [requirements-validator, requirements-sync]
  reason: "需求文档存在问题，建议先修复"
```

### 3.5 pending_stories

```yaml
id: pending_stories
priority: 3.5
description: 有就绪 Story 可开始实现

conditions:
  all:
    - requirements_configured: true
    - stories_ready: > 0
    - no_active_development: true  # 无进行中的 Story

  stories_detection:
    scan_path: "docs/requirements/user-stories/US-*.md"
    status_field: "Status"
    ready_statuses: [ready]

recommendation:
  workflow: start-implementation
  steps: [create-branch, phase-b-developer]
  reason: "有 {n} 个就绪 Story 可开始实现"
  context:
    ready_stories: [US-001, US-002, ...]
```

### 3.8 missing_openspec

```yaml
id: missing_openspec
priority: 3.8
description: 就绪 Story 缺少技术方案

conditions:
  all:
    - requirements_configured: true
    - stories_ready: > 0
    - story_without_openspec: true

  detection:
    for_each: ready_story
    check: openspec_link is null or openspec not exists

recommendation:
  workflow: create-openspec
  steps: [openspec:proposal]
  reason: "有就绪 Story，建议创建技术方案"
  context:
    uncovered_stories: [US-001, US-003]
```

### 5.5 requirements_info (信息提示)

```yaml
id: requirements_info
priority: 5.5
description: 需求追踪未配置（仅信息提示，不阻塞）

conditions:
  all:
    - requirements_configured: false

  detection:
    check: docs/requirements/ directory not exists

recommendation:
  workflow: null  # 不推荐工作流，仅提示
  info: "提示: 如需使用需求追踪，可创建 docs/requirements/ 目录"
  suggestion:
    - "参考 standards/templates/prd-template.md 创建 PRD"
    - "或继续使用 OpenSpec 作为轻量替代"
```

---

## 条件检测方法

### Git 状态检测

```yaml
git_detection:
  current_branch:
    command: "git branch --show-current"
    is_feature_branch: not in [main, master, develop]

  staged_files:
    command: "git diff --cached --name-only"
    has_staged: output not empty

  unstaged_files:
    command: "git diff --name-only"
    has_unstaged: output not empty

  changed_files_count:
    command: "git status --porcelain | wc -l"
```

### 文件类型检测

```yaml
file_type_classification:
  code:
    mobile: ["*.dart"]
    backend: ["*.py", "*.js"]
    shared: ["*.yaml", "*.json"]

  test:
    pattern: ["*_test.dart", "*_test.py", "test_*.py", "*.spec.js"]

  docs:
    pattern: ["*.md", "ARCHITECTURE.md", "README.md"]

  config:
    pattern: ["*.yaml", "*.yml", "*.json", "*.toml", "pubspec.yaml"]

  architecture:
    pattern: ["*ARCHITECTURE*.md", "docs/architecture/**"]
```

### OpenSpec 检测

**重要**: OpenSpec 有两个不同的目录需要扫描：

1. **`openspec/changes/`** - 活跃变更（进行中的 Spec）
2. **`openspec/archive/`** - 已完成变更（已归档的 Spec）

**注意**: `standards/openspec/` 是格式定义库（Git submodule），不存储项目变更。

```yaml
openspec_detection:
  # 扫描活跃变更
  changes_scan:
    path: "openspec/changes/"
    command: "find openspec/changes/ -name 'proposal.md' 2>/dev/null || echo 'NO_CHANGES'"

  # 扫描已归档变更
  archive_scan:
    path: "openspec/archive/"
    command: "ls -d openspec/archive/* 2>/dev/null || echo 'NO_ARCHIVE'"
    directory_format: "{YYYY-MM-DD}-{feature}"

  status_parsing:
    path: "openspec/changes/{id}/proposal.md"
    field: "Status"
    values: [Draft, Reviewed, Approved, In Progress, Complete]

  # 活跃 Spec 定义
  active_specs:
    filter: status in [Reviewed, Approved, In Progress]

  # 待归档检测
  pending_archive:
    condition: status == Complete AND path starts with "openspec/changes/"
    recommendation: "使用 /openspec-archive 归档"

  # 归档目录解析
  archive_parsing:
    from_directory: "{YYYY-MM-DD}-{feature}"
    extract:
      completion_date: "$1"  # YYYY-MM-DD 部分
      feature_name: "$2"      # feature 名称部分
```

### 复杂度评估

```yaml
complexity_assessment:
  factors:
    - changed_files_count
    - modules_affected
    - new_files_count
    - api_changes
    - architecture_impact

  scoring:
    Level1: score < 3
    Level2: score 3-7
    Level3: score > 7

  weights:
    changed_files: 1 per 3 files
    new_module: +3
    new_api: +2
    architecture_change: +3
```

### 架构状态检测

```yaml
architecture_detection:
  primary_path:
    path: "docs/architecture/system-architecture.md"
    check: file exists

  fallback_path:
    path: "{module}/docs/ARCHITECTURE.md"
    check: file exists

  status_extraction:
    from: header
    field: "Status"
    values: [draft, active, outdated]

  last_updated_extraction:
    from: header
    field: "Last Updated"
    format: "YYYY-MM-DD"

  parent_prd_detection:
    patterns:
      - "Parent Document.*prd-"
      - "References.*prd-"
      - "Based on.*prd-"
    extract: prd_id

  chain_validation:
    checks:
      - parent_prd_exists: prd file exists
      - parent_prd_match: architecture references correct prd
      - timestamp_order: prd.created <= architecture.created
    output:
      chain_valid: boolean
      chain_issues: list
```

### 需求状态检测

```yaml
requirements_detection:
  directory_check:
    paths:
      - "docs/requirements/"           # 主项目
      - "{module}/docs/requirements/"  # 模块级
    exists: requirements_configured

  prd_scan:
    pattern: "docs/requirements/prd-*.md"
    extract:
      - file_path
      - status (from header)

  stories_scan:
    pattern: "docs/requirements/user-stories/US-*.md"
    extract:
      - story_id
      - status
      - priority
      - openspec_link
    aggregate:
      total: count(*)
      ready: count(status = 'ready')
      in_progress: count(status = 'in_progress')
      done: count(status = 'done')

  validation:
    invoke: requirements-validator (check mode)
    check: validation_result.errors
```

---

## 推荐输出格式

```yaml
recommendation_output:
  primary:
    workflow: string          # 工作流名称
    steps: list               # 要执行的步骤
    skip_steps: list          # 跳过的步骤
    reason: string            # 推荐理由

  alternatives:
    - workflow: string
      reason: string
    - workflow: string
      reason: string

  context:
    phase_cycle: string       # 当前进度
    module: string            # 活跃模块
    changed_files: list       # 变更文件
    openspec_id: string       # 关联的 OpenSpec (如有)
```

---

## 自定义规则扩展

### 添加项目特定规则

```yaml
# 在此添加项目特定规则

custom_rules:
  - id: mobile_widget_update
    priority: 2.5  # 在 quick_fix 和 feature_with_spec 之间
    conditions:
      all:
        - file_pattern: "mobile/lib/widgets/**"
        - changed_files: <= 5
    recommendation:
      workflow: quick-fix
      reason: "Widget 更新，使用快速流程"

  - id: api_contract_change
    priority: 2.8
    conditions:
      all:
        - file_pattern: "shared/contracts/**"
    recommendation:
      workflow: full-cycle
      reason: "API 契约变更，需要完整流程"
```

---

## 规则冲突处理

```yaml
conflict_resolution:
  strategy: first_match  # 按优先级，第一个匹配的规则生效

  logging:
    on_conflict: true
    format: "规则冲突: {rule1} vs {rule2}, 选择 {winner}"

  override:
    user_can_override: true
    override_syntax: "使用 {workflow} 工作流"
```

---

## 调试模式

```yaml
debug_mode:
  enabled: false  # 设为 true 开启详细日志

  output:
    - 检测到的条件值
    - 每个规则的匹配结果
    - 最终选择的规则和理由
```

---

**最后更新**: 2026-02-08

## 变更历史

### v2.4.0 (2026-02-08)

- **新增**: OpenSpec archive 目录扫描支持
  - 区分 `openspec/changes/` 和 `openspec/archive/`
  - 添加待归档 Spec 检测
  - 明确 `standards/openspec/` 是格式定义库，不存储项目变更

# State Scanner - 推荐规则定义

> 智能工作流推荐引擎的规则配置

## 规则概览

| 规则 ID | 优先级 | 推荐工作流 | 触发条件 | 置信度 | 自动执行? |
|---------|--------|-----------|----------|--------|----------|
| `commit_only` | 1 | C.1 only | 已暂存 + 无未暂存 | 95% | Yes — 已暂存 + 无未暂存信号明确 |
| `readme_outdated` | 1.3 | doc-update | README 版本/日期不一致 | 85% | No — 用户可能有意延后 |
| `standards_missing` | 1.4 | (建议性提示) | standards 子模块未初始化 | 80% | No — 非阻塞，仅提醒 |
| `requirements_issues` | 1.5 | requirements-check | 需求文档验证有错误 | 85% | No — 用户可能希望延后处理 |
| `architecture_missing` | 1.6 | create-architecture | PRD 存在但无 Architecture | 80% | No |
| `architecture_outdated` | 1.7 | update-architecture | Architecture 状态为 outdated | 80% | No |
| `architecture_chain_broken` | 1.8 | fix-architecture | 需求链路不完整 | 80% | No |
| `quick_fix` | 2 | quick-fix | ≤3文件 + 简单修复 | 92% | Yes — ≤3 文件 + 简单类型信号清晰 |
| `feature_with_spec` | 3 | feature-dev | 有 approved OpenSpec | 88% | No — 进入开发是重大步骤 |
| `pending_stories` | 3.5 | start-implementation | 有就绪 Story 可实现 | 75% | No |
| `missing_openspec` | 3.8 | create-openspec | Story 无技术方案 | 70% | No |
| `fuzziness_requirement` | 4 | requirements-refine | 需求模糊需澄清 | 60% | No |
| `missing_prd` | 4.2 | create-prd | 无 PRD 文档 | 65% | No |
| `prd_refinement` | 4.4 | refine-prd | PRD 需细化 | 65% | No |
| `doc_only` | 5 | doc-update | 仅 *.md 文件 | 93% | Yes — 纯文档变更风险低 |
| `feature_new` | 6 | full-cycle | Level2+ 无 Spec | 70% | No — 完整循环需要规划 |
| `requirements_info` | 6.5 | (信息提示) | 需求追踪未配置 | — | No |

> **置信度评分方法**: 基于信号清晰度、风险等级、可逆性三维评估。详见 [references/confidence-scoring.md](./references/confidence-scoring.md)。
> **自动执行策略**: 仅当置信度 >90% 且项目启用 `auto_proceed` 时，推荐可自动执行而无需用户确认。

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

### 1.3 readme_outdated

```yaml
id: readme_outdated
priority: 1.3
description: README.md 版本号或日期与项目不一致

conditions:
  any:
    - readme_version_mismatch: true   # VERSION/plugin.json 与 README 版本不同
    - readme_date_mismatch: true      # CHANGELOG 最新日期与 README 日期不同

  detection:
    version_source:
      - VERSION file
      - aria/.claude-plugin/plugin.json (version field)
    date_source:
      - CHANGELOG.md (最新条目日期, 非 wall-clock)
    readme_paths:
      - README.md (根目录)
      - aria/README.md (子模块)

recommendation:
  workflow: doc-update
  steps: [update-readme]
  reason: "README.md 版本信息过时，建议更新以保持一致"
  non_blocking: true  # 不阻塞其他工作流
```

### 1.4 standards_missing

```yaml
id: standards_missing
priority: 1.4
description: standards 子模块已注册但未初始化

conditions:
  all:
    - gitmodules_has_standards: true   # .gitmodules 有 standards 条目
    - standards_dir_empty: true        # standards/ 目录不存在或为空

  detection:
    check_1: "grep -q 'standards' .gitmodules 2>/dev/null"
    check_2: "ls standards/ 2>/dev/null | head -1"

recommendation:
  workflow: null  # 不推荐工作流，仅提示
  info: "⚠️ aria-standards 子模块已注册但未初始化"
  suggestion: "git submodule update --init standards"
  non_blocking: true  # 建议性，不阻塞
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

### 4. fuzziness_requirement

```yaml
id: fuzziness_requirement
priority: 4
description: 需求描述模糊，需要澄清

conditions:
  all:
    - requirements_configured: true
    - requirement_fuzziness: high  # 需求文本含歧义关键词

  fuzziness_detection:
    indicators:
      - vague_terms: ["可能", "大概", "也许", "待定", "TBD"]
      - missing_acceptance_criteria: true
      - no_examples: true

recommendation:
  workflow: requirements-refine
  steps: [requirements-review, clarification]
  reason: "需求描述模糊，建议先澄清再实现"
```

### 4.2 missing_prd

```yaml
id: missing_prd
priority: 4.2
description: 项目无 PRD 文档

conditions:
  all:
    - requirements_configured: true
    - prd_exists: false
    - stories_total: > 0  # 有 Story 但无 PRD

  detection:
    check: "docs/requirements/prd-*.md" not exists

recommendation:
  workflow: create-prd
  steps: [prd-drafting]
  reason: "有 User Story 但缺少 PRD，建议创建产品需求文档"
```

### 4.4 prd_refinement

```yaml
id: prd_refinement
priority: 4.4
description: PRD 存在但需要细化

conditions:
  all:
    - prd_exists: true
    - prd_status: draft
    - prd_completeness: < 70%  # PRD 关键章节不完整

  completeness_check:
    required_sections:
      - objectives
      - user_stories_link
      - success_metrics
      - constraints

recommendation:
  workflow: refine-prd
  steps: [prd-review, prd-update]
  reason: "PRD 关键章节不完整，建议细化"
```

### 5. doc_only

```yaml
id: doc_only
priority: 5
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

### 6. feature_new (兜底规则)

```yaml
id: feature_new
priority: 6
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

### 6.5 requirements_info (信息提示)

```yaml
id: requirements_info
priority: 6.5
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
  # 扫描活跃变更 (三态检测)
  changes_scan:
    path: "openspec/changes/"
    step_1: "[ -d openspec/changes/ ] && echo 'EXISTS' || echo 'NOT_EXISTS'"
    step_2: "find openspec/changes/ -name 'proposal.md' 2>/dev/null"
    states:
      not_exists: configured = false                    # 目录不存在
      exists_empty: configured = true, changes.total = 0  # 目录存在但无 proposal.md (干净状态)
      exists_with_content: configured = true, scan proposals  # 正常扫描

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

### README 同步检测

```yaml
readme_detection:
  paths:
    - README.md
    - aria/README.md

  version_extraction:
    patterns:
      - "Version.*: (v?[0-9]+\\.[0-9]+\\.[0-9]+)"
      - "\\*\\*Version\\*\\*.*: (v?[0-9]+\\.[0-9]+\\.[0-9]+)"
      - "version: (v?[0-9]+\\.[0-9]+\\.[0-9]+)"

  version_source:
    primary: "cat VERSION 2>/dev/null | grep -oP '[0-9]+\\.[0-9]+\\.[0-9]+'"
    fallback: "grep '\"version\"' aria/.claude-plugin/plugin.json 2>/dev/null"

  date_extraction:
    readme_pattern: "更新.*: ([0-9]{4}-[0-9]{2}-[0-9]{2})"
    changelog_source: "head -20 CHANGELOG.md | grep -oP '[0-9]{4}-[0-9]{2}-[0-9]{2}' | head -1"

  comparison:
    version_match: readme_version == source_version
    date_match: readme_date == changelog_date
```

### Standards 子模块检测

```yaml
standards_detection:
  step_1:
    command: "grep -q 'standards' .gitmodules 2>/dev/null && echo 'REGISTERED' || echo 'NOT_REGISTERED'"
    result: registered (boolean)

  step_2:
    condition: registered == true
    command: "ls standards/ 2>/dev/null | head -1"
    result:
      empty_output: initialized = false
      has_output: initialized = true

  output:
    state_1: { registered: false }                          # 无条目 → 不提示
    state_2: { registered: true, initialized: false }       # 未初始化 → 警告
    state_3: { registered: true, initialized: true }        # 正常 → 无提示
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
      - status          # 使用多模式提取，见 SKILL.md Phase 1.5 Status 提取模式
      - priority
      - openspec_link
    status_patterns:     # 按优先级尝试，首个匹配即停止
      - /^Status:\s*(.+)/i                          # YAML-like header
      - /\*\*Status\*\*:\s*(.+)/i                   # Markdown bold
      - /\*\*状态\*\*:\s*(.+)/i                     # 中文键名
      - />\s*.*(?:Status|状态)[：:]\s*(.+)/i        # Blockquote 内嵌
      - /\|\s*(?:Status|状态)\s*\|\s*(.+?)\s*\|/i   # 表格列
    on_no_match: "unknown"  # 不报错，标记为未知
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

**最后更新**: 2026-03-16

## 变更历史

### v2.6.0 (2026-03-18)

- **新增**: 规则 `readme_outdated` (优先级 1.3) — README 版本/日期同步检测
- **新增**: 规则 `standards_missing` (优先级 1.4) — standards 子模块挂载检测
- **新增**: README 同步检测方法 (version + date extraction)
- **新增**: Standards 子模块检测方法 (三状态: 无条目/未初始化/正常)

### v2.5.0 (2026-03-16)

- **新增**: 置信度评分 (Confidence Scoring) — 每条规则附加置信度和自动执行标识
- **新增**: 规则 `fuzziness_requirement` (优先级 4) — 需求模糊检测
- **新增**: 规则 `missing_prd` (优先级 4.2) — 缺失 PRD 检测
- **新增**: 规则 `prd_refinement` (优先级 4.4) — PRD 细化建议
- **调整**: `doc_only` 优先级 4 → 5, `feature_new` 优先级 5 → 6, `requirements_info` 优先级 5.5 → 6.5
- **参考**: 详细评分方法见 [references/confidence-scoring.md](./references/confidence-scoring.md)

### v2.4.0 (2026-02-08)

- **新增**: OpenSpec archive 目录扫描支持
  - 区分 `openspec/changes/` 和 `openspec/archive/`
  - 添加待归档 Spec 检测
  - 明确 `standards/openspec/` 是格式定义库，不存储项目变更

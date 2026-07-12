# State Scanner — 规则操作 (Operations)

> 从 [RECOMMENDATION_RULES.md](../../RECOMMENDATION_RULES.md) 拆出。规则的操作元数据: 条件检测方法 / 推荐输出格式 / 自定义规则扩展 / 规则冲突处理 / 调试模式。

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
    # normalized by _normalize_status() — 唯一 SOT = scripts/collectors/_status.py
    # (raw `Draft`→pending, raw `Complete`/`Done`→done; 故 codomain 无 draft/complete)
    values: [pending, in_progress, approved, implemented, reviewed, active, ready, done, archived, deprecated, unknown]

  # 活跃 Spec 定义
  active_specs:
    filter: status in [reviewed, approved, in_progress]   # normalized by _normalize_status()

  # 待归档检测 (archive-ready 集 = {done} ONLY; `implemented` 刻意排除 — #134 A2.5, DEC-20260609-001 §3 D2)
  pending_archive:
    condition: status == done AND path starts with "openspec/changes/"  # normalized by _normalize_status() (collectors/_status.py 唯一 SOT; 对齐 collectors/openspec.py `st == 'done'`)
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
    # #158: plugin.json 是版本 SOT; 旧 primary (grep 人类可读 VERSION 快照) 会把
    # 文内示例串/历史行全部吐出, 不可作抽取源。实际 collector (collectors/readme.py)
    # 一直从 plugin.json json 解析 — 本参考文档此前与实现脱节, 现对齐。
    primary: "jq -r '.version' aria/.claude-plugin/plugin.json 2>/dev/null"
    fallback: "grep -m1 -oE '\\*\\*版本\\*\\*: *[0-9]+\\.[0-9]+\\.[0-9]+' aria/VERSION | grep -oE '[0-9]+\\.[0-9]+\\.[0-9]+'"

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

### 审计状态检测

```yaml
audit_detection:
  config_check:
    source: "config-loader → audit.*"
    fields:
      enabled: boolean
      mode: "adaptive | convergence | challenge | manual"
      checkpoints: object (各检查点 off/convergence/challenge)

  active_checkpoints:
    filter: "checkpoint value != 'off'"
    adaptive_note: "adaptive 模式下无显式 checkpoints 时由 adaptive_rules + complexity_level 决定"

  last_audit_scan:
    path: ".aria/audit-reports/"
    command: "ls .aria/audit-reports/*.md 2>/dev/null | sort | tail -1"
    frontmatter_fields:
      - checkpoint
      - verdict
      - converged
      - timestamp
    on_empty: "last_audit: null"

  unconverged_check:
    condition: "last_audit.converged == false"
    output: "has_unconverged: true"
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

**最后更新**: 2026-05-09


---
name: state-scanner
description: |
  项目状态扫描与智能工作流推荐，十步循环的统一入口。
  收集项目状态、分析变更、推荐最佳工作流、引导用户确认执行。

  使用场景："查看项目当前状态"、"我要提交代码"、"开发新功能"
argument-hint: "[intent]"
disable-model-invocation: false
user-invocable: true
allowed-tools: Read, Glob, Grep, Bash
---

# 状态扫描与智能推荐 (State Scanner v2.5)

> **版本**: 2.4.0 | **角色**: 十步循环统一入口

## 快速开始

### 我应该使用这个 Skill 吗？

**使用场景**:
- 开始任何开发任务前的状态检查
- 不确定应该使用哪个工作流
- 需要系统推荐最佳执行路径
- 查询多模块项目的整体进度

**不使用场景**:
- 已知要执行特定 Phase → 直接调用 Phase Skill
- 只想运行特定步骤 → 直接调用步骤 Skill

---

## 核心功能

| 功能 | 描述 |
|------|------|
| **状态感知** | 收集 Git 状态、UPM 进度、OpenSpec 状态、变更分析 |
| **智能推荐** | 基于状态生成工作流推荐，附带理由说明 |
| **用户确认** | 展示选项，让用户确认或自定义工作流 |
| **工作流启动** | 将确认的工作流传递给 workflow-runner 执行 |

---

## 配置 (config-loader)

执行前读取 `.aria/config.json`，缺失则使用默认值。参见 [config-loader](../config-loader/SKILL.md)。

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `state_scanner.confidence_threshold` | `90` | 置信度阈值 (0-100) |
| `state_scanner.auto_execute_enabled` | `false` | 高置信度自动执行 |
| `state_scanner.auto_execute_rules` | `["commit_only", "quick_fix", "doc_only"]` | 允许自动执行的规则 |
| `state_scanner.audit_log_path` | `".aria/audit.log"` | 审计日志路径 |
| `workflow.auto_proceed` | `false` | Phase 间自动推进 |

---

## 执行流程

### 阶段 0: 中断检测 (Pre-flight)

> 详细逻辑见 [interrupt-recovery.md](./references/interrupt-recovery.md) | 状态格式见 [workflow-state-schema.md](../workflow-runner/references/workflow-state-schema.md)

检查 `.aria/workflow-state.json` — 不存在或损坏则跳过进入阶段 1 (损坏时备份并警告)。若 status=`in_progress`|`suspended`: (1) 验证 `git_anchor.branch` 匹配当前分支，不匹配仅 Abandon/Inspect; (2) 若 `session.last_active_at`<5min 且 `session_id` 不同，警告并发冲突; (3) 展示 **[1]Resume [2]Abandon [3]Inspect** — Resume→workflow-runner(resume=true)，Abandon→删除状态进入阶段1，Inspect→详情后重选。若 status=`failed`: 显示失败上下文，提供 **[1]Retry [2]Abandon [3]Inspect**。

### 阶段 1: 状态收集

```yaml
收集内容:
  git:
    current_branch: 当前分支名
    uncommitted_changes: 未提交的变更数
    staged_files: 已暂存文件列表
    unstaged_files: 未暂存文件列表
    recent_commits: 最近 5 条提交

  project:
    phase_cycle: 从 UPM 读取当前 Phase/Cycle
    active_module: 活跃模块 (mobile/backend/shared)
    openspec_status: OpenSpec 变更状态

  changes:
    file_types: 变更文件类型分类 (code/test/docs/config)
    change_count: 变更文件数量
    complexity: 变更复杂度评估 (Level1/Level2/Level3)
    architecture_impact: 是否影响架构文档
    test_coverage: 是否有对应测试文件
    skill_changes:                    # v1.7.0 新增: Skill 变更检测
      detected: 是否有 SKILL.md 变更
      modified_skills: 变更的 Skill 列表
      ab_status:                      # 各 Skill 的 AB 验证状态
        verified: 有新鲜 AB 结果的 Skill 列表
        needs_benchmark: 缺少 AB 结果的 Skill 列表

  requirements:                       # 新增: 需求状态
    configured: 是否配置需求追踪
    prd_exists: PRD 文件是否存在
    stories:
      total: User Story 总数
      ready: 就绪待实现
      in_progress: 进行中
      done: 已完成
    coverage:
      with_openspec: 有技术方案的 Story 数
      without_openspec: 无技术方案的 Story 数
    forgejo:
      synced: 是否与 Forgejo 同步
      drift: 是否有状态偏差
```

### 阶段 1.5: 需求状态收集 (始终执行)

**重要**: 此阶段始终执行，即使需求目录不存在也要输出需求状态。

```yaml
检测路径:
  主项目: docs/requirements/
  模块级: {module}/docs/requirements/

检测步骤:
  1. 检查 docs/requirements/ 目录是否存在
  2. 如果存在:
     - 扫描 prd-*.md 文件
     - 扫描 user-stories/US-*.md 文件
     - 提取每个 Story 的 Status (见下方模式)
     - 调用 requirements-validator (check mode)
  3. 如果不存在:
     - 设置 configured: false
     - 输出未配置提示

Status 提取模式 (按优先级尝试):
  不同项目的 User Story 格式各异，必须覆盖以下常见变体:
  1. YAML-like header:    /^Status:\s*(.+)/i
  2. Markdown bold key:   /\*\*Status\*\*:\s*(.+)/i
  3. 中文键名:            /\*\*状态\*\*:\s*(.+)/i
  4. Blockquote 内嵌:     />\s*.*(?:Status|状态)[：:]\s*(.+)/i
  5. 表格列:              /\|\s*(?:Status|状态)\s*\|\s*(.+?)\s*\|/i
  提取到任一匹配即停止。未匹配到时标记为 "unknown" 而非报错。

输出 (已配置):
  requirements_status:
    configured: true
    prd_exists: true
    prd_path: "docs/requirements/prd-todo-app-v1.md"
    prd_status: Draft
    stories:
      total: 8
      ready: 3
      in_progress: 2
      done: 3
    coverage:
      with_openspec: 5
      without_openspec: 3
    validation:
      issues: []

输出 (未配置):
  requirements_status:
    configured: false
    expected_path: "docs/requirements/"
    suggestion: "如需启用需求追踪，创建 PRD 文件或使用 OpenSpec"
```

### 阶段 1.6: OpenSpec 状态扫描

**重要**: 此阶段始终执行，检测 OpenSpec 变更和归档状态。

**OpenSpec 目录结构说明**:

根据 OpenSpec 标准，项目中的 `openspec/` 目录包含两个子目录：

```
openspec/
├── changes/        # 活跃变更 (Draft/Review/Approved/In Progress)
└── archive/        # 已完成变更 (归档的 Spec)
```

**注意**: `standards/openspec/` 是格式定义库（作为 Git submodule），不存储项目变更。

```yaml
检测路径:
  主项目:
    - openspec/changes/      # 活跃变更
    - openspec/archive/      # 已完成变更

检测步骤:
  1. 检查 openspec/changes/ 目录是否存在 (用 [ -d ] 而非 ls)
     a. 不存在 → configured: false
     b. 存在但无 */proposal.md → changes.total: 0 (干净状态，非错误)
     c. 存在且有内容 → 扫描 proposal.md, 提取 Status
  2. 如果存在且有内容 (1c):
     - 扫描所有 {feature}/proposal.md 文件
     - 提取 Status 字段 (Draft/Reviewed/Approved/In Progress/Complete)
     - 统计各状态的 Spec 数量
  3. 检查 openspec/archive/ 目录是否存在
  4. 如果存在:
     - 扫描所有 {YYYY-MM-DD}-{feature}/ 目录
     - 提取完成日期和功能名称
     - 统计已归档的 Spec 数量
  5. 检查是否有 Status=Complete 但未归档的 Spec
  注意: 步骤 1b (目录存在但为空) 是合法状态，表示所有变更
  已归档完毕。不应报告为 "未配置" 或错误。

输出 (已配置):
  openspec_status:
    configured: true
    changes:
      total: 3
      draft: 1
      reviewed: 0
      approved: 1
      in_progress: 1
      complete: 0
      items:
        - id: "add-auth"
          status: "approved"
          path: "openspec/changes/add-auth/proposal.md"
        - id: "refactor-api"
          status: "in_progress"
          path: "openspec/changes/refactor-api/proposal.md"
    archive:
      total: 5
      items:
        - date: "2026-01-15"
          feature: "user-profile"
          path: "openspec/archive/2026-01-15-user-profile/"
        - date: "2026-01-20"
          feature: "payment-integration"
          path: "openspec/archive/2026-01-20-payment-integration/"
    pending_archive:
      - id: "completed-feature"
        reason: "Status=Complete but still in changes/"

输出 (干净状态 — 目录存在但无活跃变更):
  openspec_status:
    configured: true
    changes:
      total: 0
      note: "无活跃变更 (所有 Spec 已归档或尚未创建)"
    archive:
      total: 18
      # ...归档条目同上
    pending_archive: []

输出 (未配置 — 目录不存在):
  openspec_status:
    configured: false
    expected_paths:
      - "openspec/changes/"
      - "openspec/archive/"
    suggestion: "如需使用 OpenSpec，参考 standards/openspec/templates/"
```

### 阶段 1.7: 架构状态扫描

**重要**: 此阶段始终执行，检测 System Architecture 文档状态。

```yaml
检测路径:
  主项目: docs/architecture/system-architecture.md
  模块级: {module}/docs/ARCHITECTURE.md

检测步骤:
  1. 检查 docs/architecture/system-architecture.md 是否存在
  2. 如果存在:
     - 提取 Status header (draft | active | outdated)
     - 提取 Last Updated timestamp
     - 检测 Parent PRD 引用
  3. 检查与 PRD 的链路完整性:
     - PRD 是否存在
     - Architecture 是否引用 PRD
     - 时间戳是否合理 (Architecture 应晚于 PRD)

输出:
  architecture_status:
    exists: true
    path: "docs/architecture/system-architecture.md"
    status: active          # draft | active | outdated
    last_updated: "2026-01-01"
    parent_prd: "prd-v2.1.0"
    chain_valid: true       # PRD → Architecture 链路完整性
    chain_issues: []        # 链路问题列表

输出 (未配置):
  architecture_status:
    exists: false
    expected_path: "docs/architecture/system-architecture.md"
    suggestion: "建议创建 System Architecture 文档"
```

### 阶段 1.8: README 同步检查

**重要**: 此阶段始终执行，检测 README.md 版本信息是否与项目实际版本一致。

```yaml
检测路径:
  - README.md (项目根目录)
  - aria/README.md (插件子模块, 如存在)

检查项:
  - 版本号是否与 VERSION 文件或 plugin.json 一致
  - 最后更新日期是否与 CHANGELOG 最新条目日期一致 (非 wall-clock)

日期检查数据源: 以 CHANGELOG.md 最新条目日期为基准，非 wall-clock 时间。
避免随时间推移产生误报。

输出:
  readme_status:
    root:
      exists: true
      version_match: true | false
      date_match: true | false
      suggestion: "更新 README.md 版本号为 v1.7.0"  # 仅不一致时
    submodules:
      aria: { exists: true, version_match: true | false }

输出 (README 不存在):
  readme_status:
    root:
      exists: false
      suggestion: "项目缺少 README.md"
```

### 阶段 1.9: 插件依赖检测

**重要**: 此阶段始终执行，检测 aria-standards 子模块挂载状态。

```yaml
检查项:
  - .gitmodules 中是否有 standards 条目
  - standards/ 目录是否存在且非空

三种状态:
  1. .gitmodules 无 standards 条目 → 不提示 (项目不需要)
  2. .gitmodules 有条目但 standards/ 为空 → 警告 (未初始化)
  3. standards/ 正常存在 → 无提示

输出 (状态 2 - 未初始化):
  standards_status:
    registered: true
    initialized: false
    suggestion: "⚠️ aria-standards 子模块已注册但未初始化。建议: git submodule update --init standards"

输出 (状态 1 - 无需 standards):
  standards_status:
    registered: false

输出 (状态 3 - 正常):
  standards_status:
    registered: true
    initialized: true
```

**注意**: standards 对非 Aria 项目是**可选的**。检测结果为建议性提醒，不阻塞任何工作流。

---

### 阶段 2: 推荐决策

基于阶段 1 收集的状态，按优先级匹配推荐规则 (第一个匹配的规则生效)。

规则覆盖: commit_only → quick_fix → feature_with_spec → feature_new，
以及需求相关: requirements_issues, pending_stories, missing_prd, missing_openspec 等。

详细规则定义、优先级和条件见 [RECOMMENDATION_RULES.md](./RECOMMENDATION_RULES.md)。

### 阶段 3: 用户确认

```yaml
展示内容:
  - 当前状态摘要
  - 主推荐工作流 (标记 "推荐")
  - 2-3 个备选方案
  - 自定义组合选项

用户可以:
  - 选择推荐 [1]
  - 选择备选 [2-4]
  - 输入自定义 (如 "B.2 + C.1")
```

**默认行为: 必须展示 [1]-[4] 编号选项并等待用户选择。** 高置信度自动执行仅在 `.aria/config.json` 中 `auto_proceed=true` 且置信度 >90% 时触发，否则始终展示编号选项。详见 [references/confidence-scoring.md](./references/confidence-scoring.md)。

### 阶段 4: 工作流启动

```yaml
输出到 workflow-runner:
  workflow: 确认的工作流名称或自定义步骤
  context:
    phase_cycle: 当前进度
    module: 活跃模块
    changed_files: 变更文件列表
    skip_steps: 智能跳过的步骤
```

---

## 输出格式

> 完整输出格式参见 [references/output-formats.md](./references/output-formats.md)

### 标准输出示例

```
╔══════════════════════════════════════════════════════════════╗
║                    PROJECT STATE ANALYSIS                     ║
╚══════════════════════════════════════════════════════════════╝

📍 当前状态
───────────────────────────────────────────────────────────────
  分支: feature/add-auth
  模块: mobile
  Phase/Cycle: Phase4-Cycle9
  变更: 3 文件 (lib/*.dart, test/*.dart)
  OpenSpec: add-auth-feature (approved)

📊 变更分析
───────────────────────────────────────────────────────────────
  类型: 功能代码 + 测试
  复杂度: Level 2
  架构影响: 无
  测试覆盖: ✅ 有对应测试

📄 需求状态
───────────────────────────────────────────────────────────────
  配置状态: ✅ 已配置
  PRD: prd-todo-app-v1.md (Draft)
  User Stories: 8 个 (ready: 3, in_progress: 2, done: 3)
  OpenSpec 覆盖: 5/8 (62.5%)

🏗️ 架构状态
───────────────────────────────────────────────────────────────
  System Architecture: ✅ 存在
  状态: active | 需求链路: ✅ 完整

📋 OpenSpec 状态
───────────────────────────────────────────────────────────────
  活跃变更: 2 个 | 已归档: 5 个 | 待归档: 0 个

🎯 推荐工作流
───────────────────────────────────────────────────────────────
  ➤ [1] feature-dev (推荐)
      理由: 已有 OpenSpec，代码和测试就绪
  ○ [2] quick-fix
  ○ [3] full-cycle
  ○ [4] 自定义组合

🤔 选择 [1-4] 或输入自定义:
```

各场景的输出变体 (未配置、链路不完整、待归档、头脑风暴建议等) 见 [references/output-formats.md](./references/output-formats.md)。

---

## 输入参数

| 参数 | 必需 | 说明 | 示例 |
|------|------|------|------|
| `intent` | ❌ | 用户意图 (影响推荐) | "提交代码", "开发功能" |
| `module` | ❌ | 目标模块 (自动检测) | `mobile`, `backend` |
| `skip_recommendation` | ❌ | 跳过推荐直接扫描 | `true`, `false` |

---

## 使用示例

### 示例 1: 智能推荐

```yaml
用户: "我要提交代码"

state-scanner 执行:
  1. 检测 git status → 3 文件已暂存
  2. 分析变更类型 → 功能代码 + 测试
  3. 检查 OpenSpec → add-auth-feature (approved)
  4. 生成推荐 → feature-dev (跳过 Phase A)
  5. 展示选项，等待确认

用户: "1"

输出到 workflow-runner:
  workflow: feature-dev
  skip_steps: [A.1, A.2, A.3, B.3]
```

### 示例 2: 自定义组合

```yaml
用户: "只运行测试和提交"

state-scanner 执行:
  1. 收集状态
  2. 展示推荐

用户: "B.2 + C.1"

输出到 workflow-runner:
  workflow: custom
  steps: [B.2, C.1]
```

### 示例 3: 仅查看状态

```yaml
用户: "查看项目状态"

state-scanner 执行:
  输入: skip_recommendation: false

  输出: 完整状态报告 + 推荐选项

用户: "只看不执行"

结束，不调用 workflow-runner
```

---

## 推荐规则配置

详细推荐规则 (优先级、条件、自定义扩展) 见 [RECOMMENDATION_RULES.md](./RECOMMENDATION_RULES.md)。

---

## 与 Phase Skills 的关系

```
state-scanner v2.0 (本 Skill)
    │
    │ 推荐 + 用户确认
    ▼
workflow-runner v2.0
    │
    ├──▶ phase-a-planner (A.1-A.3)
    ├──▶ phase-b-developer (B.1-B.3)
    ├──▶ phase-c-integrator (C.1-C.2)
    └──▶ phase-d-closer (D.1-D.2)
```

---

## 实现注意事项

> **重要**: Claude Code 在 Windows 上使用 Git Bash/WSL。所有 Bash 命令必须使用跨平台兼容语法。

### 跨平台命令规范

| ✅ 正确 | ❌ 错误 |
|---------|---------|
| `ls path/*.md 2>/dev/null \|\| echo "NO"` | `if exist path\*.md (dir ...) else (echo NO)` |
| `ls docs/requirements/` | `dir docs\requirements\` |
| `[ -f file ] && cat file` | `if exist file (type file) else ...` |
| 路径使用 `/` | 路径使用 `\` |
| `2>/dev/null` | `2>nul` |

### 参考文档

详细的跨平台命令示例和调试技巧，见 **[`references/cross-platform-commands.md`](./references/cross-platform-commands.md)**。

---

## 错误处理

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| Git 状态获取失败 | 不在 Git 仓库中 | 提示初始化 Git |
| UPM 文档不存在 | 模块未配置 UPM | 使用默认进度信息 |
| 无法确定模块 | 文件分布多模块 | 提示用户手动指定 |
| 推荐冲突 | 多规则同时匹配 | 按优先级选择第一个 |
| Bash 语法错误 | 使用了 Windows CMD 语法 | 参考跨平台命令规范 |

---

## 检查清单

### 使用前
- [ ] 有待处理的变更或任务
- [ ] 了解大致想做什么

### 使用后
- [ ] 已了解当前项目状态
- [ ] 已确认执行的工作流
- [ ] workflow-runner 已接收执行计划

---

## 相关文档

### 参考文件
- [RECOMMENDATION_RULES.md](./RECOMMENDATION_RULES.md) - 推荐规则定义 (含置信度评分)
- [confidence-scoring.md](./references/confidence-scoring.md) - 置信度评分与自动执行策略
- [interrupt-recovery.md](./references/interrupt-recovery.md) - 中断恢复详细逻辑
- [output-formats.md](./references/output-formats.md) - 各场景输出格式定义
- [migration-v1-to-v2.md](./references/migration-v1-to-v2.md) - v1.0 → v2.0 迁移说明
- [cross-platform-commands.md](./references/cross-platform-commands.md) - 跨平台命令参考
### 工作流相关
- [brainstorm](../brainstorm/SKILL.md) - 头脑风暴引擎
- [workflow-runner](../workflow-runner/SKILL.md) - 工作流执行器
- [phase-a-planner](../phase-a-planner/SKILL.md) - 规划阶段
- [phase-b-developer](../phase-b-developer/SKILL.md) - 开发阶段
- [phase-c-integrator](../phase-c-integrator/SKILL.md) - 集成阶段
- [phase-d-closer](../phase-d-closer/SKILL.md) - 收尾阶段

---

**最后更新**: 2026-03-18
**Skill版本**: 2.6.0 (新增 README 同步检查、插件依赖检测、配置加载)

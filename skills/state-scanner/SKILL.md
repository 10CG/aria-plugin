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

# 状态扫描与智能推荐 (State Scanner v2.9)

> **版本**: 2.9.0 | **角色**: 十步循环统一入口

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
| **状态感知** | 收集 Git 状态、UPM 进度、OpenSpec 状态、审计状态、自定义检查、变更分析 |
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

  audit:                              # 新增: 审计状态
    enabled: true/false               # audit.enabled 配置值
    mode: adaptive/convergence/challenge/manual  # audit.mode 配置值
    active_checkpoints:               # 启用的检查点列表 (非 "off" 的)
      - post_spec
      - post_implementation
      - pre_merge
    last_audit:                       # 最近一次审计报告 (如有)
      checkpoint: post_spec           # 检查点名称
      timestamp: "2026-03-27T10:00:00Z"
      verdict: PASS/PASS_WITH_WARNINGS/FAIL
      converged: true/false

  custom_checks:                      # v2.8.0 新增: 项目级自定义检查
    configured: true/false            # .aria/state-checks.yaml 是否存在
    total: 3                          # 检查项总数
    passed: 2                         # 通过数
    failed: 1                         # 失败数
    results:                          # 各检查结果
      - name: "benchmark-summary-freshness"
        status: fail                  # pass/fail/timeout/error
        severity: warning             # info/warning/error
        output: "STALE"               # stdout 首行
        fix: "python3 scripts/aggregate-results.py"  # 修复建议 (如有)
      - name: "db-migration-status"
        status: pass
        severity: info
        output: "OK"

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

### 阶段 1.10: 审计状态扫描

**重要**: 此阶段始终执行，检测审计系统配置和最近审计报告状态。

```yaml
检测步骤:
  1. 通过 config-loader 读取 audit.* 配置块
     - audit.enabled == false 或字段缺失 → enabled: false, 跳过后续步骤
  2. 读取 audit.mode (adaptive/convergence/challenge/manual)
  3. 扫描 audit.checkpoints，收集非 "off" 的检查点列表
     - adaptive 模式下无显式 checkpoints 时，标注 "由 adaptive_rules 决定"
  4. 扫描 .aria/audit-reports/ 目录
     - 按文件名时间戳排序，取最新一份报告
     - 解析 frontmatter: checkpoint, verdict, converged, timestamp
  5. 检测未收敛报告:
     - 最新报告 converged == false → 标记 has_unconverged: true

输出 (已启用):
  audit_status:
    enabled: true
    mode: adaptive
    active_checkpoints:
      - post_spec
      - post_implementation
      - pre_merge
    last_audit:
      checkpoint: post_spec
      timestamp: "2026-03-27T10:00:00Z"
      verdict: PASS
      converged: true
    has_unconverged: false

输出 (已启用, 有未收敛报告):
  audit_status:
    enabled: true
    mode: challenge
    active_checkpoints: [post_spec, post_implementation, pre_merge]
    last_audit:
      checkpoint: post_implementation
      timestamp: "2026-03-27T14:00:00Z"
      verdict: PASS_WITH_WARNINGS
      converged: false
    has_unconverged: true

输出 (未启用):
  audit_status:
    enabled: false
```

### 阶段 1.11: 项目级自定义健康检查

**重要**: 此阶段始终执行，检测并运行项目级自定义健康检查。

```yaml
配置路径: .aria/state-checks.yaml

检测步骤:
  1. 检查 .aria/state-checks.yaml 是否存在 (用 [ -f ] 检测)
     a. 不存在 → configured: false, 静默跳过
     b. 存在但 YAML 解析失败 → 输出解析警告, 跳过
     c. 存在且有效 → 读取 checks 列表
  2. 验证 schema version 字段 (当前仅支持 "1")
  3. 串行执行每个 enabled=true 的检查:
     a. 工作目录: 项目根目录
     b. 超时: timeout_seconds (默认 15, 上限 60)
     c. 总超时: 60s (超出后跳过剩余检查并警告)
     d. 捕获 exit code: 0=pass, 非 0=fail
     e. 捕获 stdout 首行作为状态输出
     f. 超时 → status: timeout
     g. 命令不存在 (exit 127) → status: error
  4. 汇总结果到 custom_checks 数据结构

配置 Schema (.aria/state-checks.yaml):
  version: "1"                      # 必填, schema 版本
  checks:
    - name: string                  # 必填, 唯一标识
      description: string           # 必填, 人类可读描述 (AI 用于解释)
      command: string               # 必填, shell 命令
      severity: info|warning|error  # 必填, 影响推荐权重
      fix: string                   # 选填, 修复命令提示 (不自动执行)
      timeout_seconds: integer      # 选填, 默认 15, 上限 60
      enabled: boolean              # 选填, 默认 true

安全模型:
  - 与 hooks.json 信任模型一致, 不做沙箱
  - fix 命令仅作为建议展示, 需用户显式触发
  - 检查失败不阻塞 state-scanner 主流程

输出 (已配置, 有检查项):
  custom_checks:
    configured: true
    total: 3
    passed: 2
    failed: 1
    results:
      - name: "benchmark-summary-freshness"
        status: fail
        severity: warning
        output: "STALE"
        fix: "python3 scripts/aggregate-results.py"
      - name: "db-migration-status"
        status: pass
        severity: info
        output: "OK"
      - name: "license-audit"
        status: pass
        severity: error
        output: "OK"

输出 (已配置, 全部通过):
  custom_checks:
    configured: true
    total: 3
    passed: 3
    failed: 0
    results: [...]

输出 (未配置):
  custom_checks:
    configured: false

输出 (配置解析失败):
  custom_checks:
    configured: false
    parse_error: "YAML syntax error at line 5"
```

### 阶段 1.12: 本地/远程同步检测

**重要**: 此阶段始终执行 (fail-soft)，检测本地与远程的同步状态。

```yaml
sync_status:
  remote_refs_age: "2h"          # FETCH_HEAD 距今时长 (Nm|Nh|Nd|never)
  has_remote: true               # 是否有 git remote
  shallow: false                 # 是否为浅克隆
  current_branch:
    name: "master"
    upstream: "origin/master"
    upstream_configured: true
    ahead: 0
    behind: 3                    # null if upstream 缺失或 shallow
    diverged: false
    reason: null                 # "no_upstream"|"shallow_clone"|"detached_head"|null
  submodules:
    - path: "aria"
      tree_commit: "abc1234"     # 主仓库 HEAD 记录的 commit
      head_commit: "abc1234"     # 本地 checkout 的 commit
      remote_commit: "def5678"   # 远程默认分支 commit
      remote_commit_source: "ls-remote"
      drift:
        workdir_vs_tree: false
        tree_vs_remote: true
        behind_count: 4
        hint: "git submodule update --remote aria"
```

**字段语义 (四状态)**:

| 状态 | `shallow` | `behind` | `reason` |
|------|-----------|----------|----------|
| 正常 | false | 数字 | null |
| 浅克隆 | true | null | `"shallow_clone"` |
| 无 upstream | false | null | `"no_upstream"` |
| detached HEAD | false | null | `"detached_head"` |

**配置项** (`state_scanner.sync_check.*`):

| 字段 | 默认 | 说明 |
|------|------|------|
| `enabled` | `true` | 主开关 (本地 git 操作，默认开启) |
| `check_submodules` | `true` | 是否检测子模块偏差 |
| `warn_after_hours` | `24` | FETCH_HEAD 陈旧度告警阈值 |

**推荐规则联动**:
- `submodule_drift`: 任一 submodule `tree_vs_remote=true` → 降级推荐 + `git submodule update --remote` 提示
- `branch_behind_upstream`: `current_branch.behind >= 5` → 降级推荐 + "建议先 git pull" 提示

两条规则均不阻断推荐，仅降级 + 附加提示 (fail-soft)。

详细实现见 [references/sync-detection.md](./references/sync-detection.md)

---

### 阶段 1.13: Issue 感知扫描

**重要**: 此阶段为 opt-in，默认关闭 (`issue_scan.enabled=false`)，需用户显式开启。

```yaml
issue_status:
  fetched_at: "2026-04-09T10:23:00Z"
  source: cache                  # cache | live | unavailable
  fetch_error: null              # 见下方枚举表
  platform: forgejo              # forgejo | github | null
  open_count: 3
  items:
    - number: 6
      title: "state-scanner: add issue scan and sync detection"
      labels: ["enhancement", "skill"]
      url: "https://forgejo.10cg.pub/10CG/Aria/issues/6"
      linked_openspec: "state-scanner-issue-awareness"  # 启发式
      linked_us: null
  label_summary:
    bug: 1
    enhancement: 2
```

**`fetch_error` 枚举值速查表 (10 个)**:

| # | 枚举值 | 场景 |
|---|--------|------|
| 1 | `network_unavailable` | 离线 / 网络不可达 |
| 2 | `cli_missing` | CLI 未安装 (forgejo/gh) |
| 3 | `auth_missing` | token 未配置 |
| 4 | `auth_failed` | HTTP 401/403 |
| 5 | `rate_limited` | HTTP 429 |
| 6 | `not_found_or_no_access` | HTTP 404 或私有仓库无权限 |
| 7 | `timeout` | API 响应 > 5s |
| 8 | `platform_unknown` | 平台识别失败 |
| 9 | `parse_error` | JSON 解析失败 |
| 10 | `unknown` | 兜底未分类错误 |

**平台检测优先级 (4 级)**:
1. 显式声明: `state_scanner.issue_scan.platform` 非 null → 直接使用
2. hostname 匹配: `git remote get-url origin` 与 `platform_hostnames` 配置对比
3. 兜底推断: URL 包含 `github.com` → github；已知 Forgejo 域名 → forgejo
4. 全失败: `fetch_error: "platform_unknown"` + 静默跳过

**配置项** (`state_scanner.issue_scan.*`，9 个字段):

| 字段 | 默认 | 说明 |
|------|------|------|
| `enabled` | `false` | 主开关，opt-in |
| `platform` | `null` | 显式指定平台；null 则自动检测 |
| `platform_hostnames` | `{forgejo:[...], github:[...]}` | hostname → 平台映射，可扩展 |
| `cache_ttl_seconds` | `900` | 缓存 15 分钟 TTL |
| `cache_path` | `.aria/cache/issues.json` | 缓存文件位置 |
| `stage_timeout_seconds` | `12` | 整阶段超时 |
| `api_timeout_seconds` | `5` | 单次 API 调用超时 |
| `limit` | `20` | 单次拉取 Issue 上限 |
| `label_filter` | `[]` | 空表示不过滤；可设 `["bug","blocker"]` |

**推荐规则联动**:
- `open_blocker_issues`: 存在 label 包含 `blocker`/`critical` 的 open issue → 降级推荐 + "先 triage N 个阻塞 Issue" 提示

详细实现见 [references/issue-scanning.md](./references/issue-scanning.md)

---

### 阶段 2: 推荐决策

基于阶段 1 收集的状态，按优先级匹配推荐规则 (第一个匹配的规则生效)。

规则覆盖: commit_only → quick_fix → feature_with_spec → feature_new，
以及需求相关: requirements_issues, pending_stories, missing_prd, missing_openspec 等，
以及审计相关: audit_unconverged (当存在未收敛审计报告时提示)，
以及自定义检查: custom_check_failed (当 severity=error 的检查失败时阻断推荐)、
custom_check_warning (当 severity=warning 的检查失败时降级推荐并附加 fix 提示)，
以及同步检测: submodule_drift (子模块落后远程时降级)、branch_behind_upstream (分支落后 upstream ≥5 commits 时降级)，
以及 Issue 感知: open_blocker_issues (存在 blocker/critical label 的 open issue 时降级)。

当 `audit.enabled=true` 时，推荐输出中展示审计状态摘要:
- 上次审计的 verdict 和收敛状态
- 如果最新审计报告 `converged=false`，提示用户处理 (查看报告 / 重新审计 / 接受当前结论)

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
    complexity_level: Level1/Level2/Level3   # 传递给 workflow-runner
    audit:                                   # 审计配置摘要 (仅 audit.enabled=true 时)
      enabled: true
      mode: adaptive                        # 当前审计模式
      active_checkpoints: [post_spec, ...]  # 启用的检查点
```

**adaptive 集成**: state-scanner 的复杂度评估 (`changes.complexity`) 通过 `context.complexity_level` 传递给 workflow-runner。workflow-runner 在调用 Phase Skills 时将 Level 信息传递给 audit-engine，用于 adaptive 模式下按 `adaptive_rules` 决定各检查点使用 convergence 还是 challenge 模式 (Level 1 = off, Level 2 = convergence, Level 3 = challenge，可通过 config 覆盖)。

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

🛡️ 审计状态
───────────────────────────────────────────────────────────────
  审计系统: ✅ 已启用 (adaptive 模式)
  活跃检查点: post_spec, post_implementation, pre_merge
  上次审计: post_spec — PASS (收敛, 2 轮)

🔧 自定义检查
───────────────────────────────────────────────────────────────
  ✅ db-migration-status: OK
  ⚠️ benchmark-summary-freshness: STALE (warning)
     修复建议: python3 scripts/aggregate-results.py
  ✅ license-audit: OK

🔄 同步状态
───────────────────────────────────────────────────────────────
  当前分支: master (落后 origin/master 3 commits)
  远程引用: 2h 前同步
  子模块:
    ✅ standards: 同步
    ⚠️  aria: 落后远程 4 commits
        修复建议: git submodule update --remote aria

🎫 Open Issues
───────────────────────────────────────────────────────────────
  平台: Forgejo (10CG/Aria) — 3 open
  📌 #6  state-scanner issue scan         [enhancement]
         → 已关联 OpenSpec: state-scanner-issue-awareness
  数据来源: cache (2m ago) | ttl: 15m

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
- [sync-detection.md](./references/sync-detection.md) - 同步检测详细逻辑 (Phase 1.12)
- [issue-scanning.md](./references/issue-scanning.md) - Issue 扫描详细逻辑 (Phase 1.13)
### 审计相关
- [audit-engine](../audit-engine/SKILL.md) - 多轮收敛审计编排引擎
### 工作流相关
- [brainstorm](../brainstorm/SKILL.md) - 头脑风暴引擎
- [workflow-runner](../workflow-runner/SKILL.md) - 工作流执行器
- [phase-a-planner](../phase-a-planner/SKILL.md) - 规划阶段
- [phase-b-developer](../phase-b-developer/SKILL.md) - 开发阶段
- [phase-c-integrator](../phase-c-integrator/SKILL.md) - 集成阶段
- [phase-d-closer](../phase-d-closer/SKILL.md) - 收尾阶段

---

**最后更新**: 2026-04-09
**Skill版本**: 2.9.0 (新增 Phase 1.12 同步检测 + Phase 1.13 Issue 感知)

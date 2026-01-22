# Workflow Runner v2.0 - 工作流定义

> 基于 Phase 的工作流模板和自定义组合规范

## 预置工作流

### 1. quick-fix (快速修复)

```yaml
id: quick-fix
name: 快速修复工作流
description: 适用于简单 Bug 修复、typo 修正、配置调整

phases:
  - phase: B
    skill: phase-b-developer
    config:
      skip_steps: [B.3]     # 跳过架构同步
      coverage_check: false  # 不检查覆盖率

  - phase: C
    skill: phase-c-integrator
    config:
      create_pr: false       # 直接推送

estimated_time: 1-2 minutes

triggers:
  - "快速修复"
  - "修复 Bug"
  - "fix typo"
  - "运行 quick-fix"
```

### 2. feature-dev (功能开发)

```yaml
id: feature-dev
name: 功能开发工作流
description: 适用于新功能开发、中等规模任务

phases:
  - phase: A
    skill: phase-a-planner
    config:
      spec_level: 2

  - phase: B
    skill: phase-b-developer
    config:
      coverage_threshold: 80

  - phase: C
    skill: phase-c-integrator
    config:
      create_pr: true

estimated_time: 10-30 minutes

triggers:
  - "开发新功能"
  - "实现功能"
  - "运行 feature-dev"
```

### 3. doc-update (文档更新)

```yaml
id: doc-update
name: 文档更新工作流
description: 适用于架构文档、README 更新

steps:
  - step: B.3
    skill: arch-update
    config:
      validate: true

  - step: C.1
    skill: commit-msg-generator
    config:
      type: docs

estimated_time: 2-5 minutes

triggers:
  - "更新文档"
  - "文档变更"
  - "运行 doc-update"
```

### 4. full-cycle (完整循环)

```yaml
id: full-cycle
name: 完整十步循环
description: 适用于重大功能、需要完整 OpenSpec 流程

phases:
  - phase: A
    skill: phase-a-planner

  - phase: B
    skill: phase-b-developer

  - phase: C
    skill: phase-c-integrator

  - phase: D
    skill: phase-d-closer

estimated_time: 30-60 minutes

triggers:
  - "完整开发流程"
  - "执行十步循环"
  - "运行 full-cycle"
```

### 5. commit-only (仅提交)

```yaml
id: commit-only
name: 仅提交工作流
description: 变更已就绪，只需提交

steps:
  - step: C.1
    skill: commit-msg-generator
    config:
      enhanced_markers: true

estimated_time: < 1 minute

triggers:
  - state-scanner 检测: 已暂存 + 无未暂存
  - "只需要提交"
  - "运行 commit-only"
```

---

## 需求管理工作流 (Aria v3.0)

### 6. requirements-check (需求验证)

```yaml
id: requirements-check
name: 需求文档验证
description: 验证 PRD 和 User Story 格式、关联

steps:
  - step: validate
    skill: requirements-validator
    config:
      mode: full

  - step: forgejo-status
    skill: forgejo-sync
    config:
      action: status-check
    optional: true  # 仅当配置 Forgejo 时执行

  - step: scan
    skill: state-scanner
    config:
      focus: requirements

estimated_time: 1-2 minutes

triggers:
  - "/requirements-check"
  - "验证需求文档"
  - "检查需求完整性"
```

### 7. requirements-update (需求同步)

```yaml
id: requirements-update
name: 需求状态同步
description: 同步 Story 状态到 UPM 和 Forgejo

steps:
  - step: validate
    skill: requirements-validator
    config:
      mode: quick

  - step: sync-upm
    skill: requirements-sync
    config:
      mode: update

  - step: sync-forgejo
    skill: forgejo-sync
    config:
      action: bulk-sync
    optional: true

estimated_time: 1-3 minutes

triggers:
  - "/requirements-update"
  - "同步需求状态"
  - "更新 UPM 需求"
```

### 8. iteration-planning (迭代规划)

```yaml
id: iteration-planning
name: 迭代需求盘点
description: 迭代开始时的全面需求检查

steps:
  - step: full-validate
    skill: requirements-validator
    config:
      mode: full

  - step: sync-upm
    skill: requirements-sync
    config:
      mode: update

  - step: sync-forgejo
    skill: forgejo-sync
    config:
      action: bulk-sync
    optional: true

  - step: report
    skill: state-scanner
    config:
      focus: requirements
      output: planning-report

estimated_time: 3-5 minutes

triggers:
  - "/iteration-planning"
  - "迭代规划"
  - "需求盘点"
```

### 9. publish-prd (发布 PRD)

```yaml
id: publish-prd
name: PRD 发布到 Wiki
description: 将 PRD 发布到 Forgejo Wiki

steps:
  - step: validate
    skill: requirements-validator
    config:
      target: prd

  - step: publish
    skill: forgejo-sync
    config:
      action: prd-to-wiki

  - step: index
    skill: forgejo-sync
    config:
      action: prd-index
    optional: true

estimated_time: 1-2 minutes

triggers:
  - "/publish-prd"
  - "发布 PRD"
  - "PRD 到 Wiki"
```

---

## 自定义组合语法

### Phase 组合

```yaml
# 基础 Phase 组合
phases: [A, B, C]        # 顺序执行 A → B → C
phases: [B, C]           # 跳过 A，从 B 开始
phases: [A, B, C, D]     # 完整循环

# 带配置的 Phase 组合
phases:
  - phase: B
    config:
      skip_steps: [B.3]
  - phase: C
    config:
      create_pr: true
```

### 步骤组合

```yaml
# 直接指定步骤
steps: [B.1, B.2, C.1]   # 只执行指定步骤
steps: [C.1]             # 仅提交

# 步骤自动映射到 Phase
steps: [A.2, A.3, B.1]   → phases: [A, B] (部分执行)
```

### 混合组合

```yaml
# Phase + 步骤 skip
phases:
  - phase: B
    skip_steps: [B.3]    # Phase 内跳过特定步骤
  - phase: C

# 条件跳过
phases:
  - phase: A
    skip_if:
      - has_openspec: true  # 已有 OpenSpec 跳过 A
  - phase: B
  - phase: C
```

---

## 上下文传递机制

### 自动传递

```yaml
context_chain:
  initial:                    # 工作流启动时的上下文
    phase_cycle: "Phase4-Cycle9"
    module: "mobile"
    changed_files: [...]

  phase_a_output:             # Phase A 完成后追加
    spec_id: "add-auth-feature"
    task_list: [TASK-001, ...]
    assigned_agents: {...}

  phase_b_output:             # Phase B 完成后追加
    branch_name: "feature/add-auth"
    test_results:
      passed: true
      coverage: 87.5

  phase_c_output:             # Phase C 完成后追加
    commit_sha: "abc1234"
    pr_url: "https://..."
    pr_number: 123

  phase_d_output:             # Phase D 完成后追加
    upm_updated: true
    spec_archived: true
```

### 上下文合并规则

```yaml
merge_strategy:
  mode: deep_merge            # 深度合并
  conflict: later_wins        # 后续 Phase 覆盖

  preserved_keys:             # 始终保留的键
    - phase_cycle
    - module
    - spec_id
```

### 上下文访问

```yaml
# Phase B 访问 Phase A 输出
phase_b:
  use_from_context:
    - task_list               # 来自 Phase A
    - spec_id                 # 来自 Phase A

# Phase C 访问 Phase B 输出
phase_c:
  use_from_context:
    - branch_name             # 来自 Phase B
    - test_results            # 来自 Phase B
```

---

## Phase 到步骤映射

### Phase A (规划)

| 步骤 | Skill | 职责 | 可跳过 |
|------|-------|------|--------|
| A.1 | spec-drafter | Spec 管理 | 已有 OpenSpec |
| A.2 | task-planner | 任务规划 | 已有 tasks.yaml |
| A.3 | task-planner | Agent 分配 | 已有 tasks.yaml |

### Phase B (开发)

| 步骤 | Skill | 职责 | 可跳过 |
|------|-------|------|--------|
| B.1 | branch-manager | 分支创建 | 已在功能分支 |
| B.2 | test-verifier | 测试验证 | 无 (可降级) |
| B.3 | arch-update | 架构同步 | 无架构变更 |

### Phase C (集成)

| 步骤 | Skill | 职责 | 可跳过 |
|------|-------|------|--------|
| C.1 | commit-msg-generator | Git 提交 | 无变更 |
| C.2 | branch-manager | PR/合并 | 直接推送 |

### Phase D (收尾)

| 步骤 | Skill | 职责 | 可跳过 |
|------|-------|------|--------|
| D.1 | progress-updater | 进度更新 | 无 UPM |
| D.2 | openspec:archive | Spec 归档 | 无 OpenSpec |

---

## 工作流触发

### 显式触发

```
# 预置工作流
"运行 quick-fix 工作流"
"执行 feature-dev"

# Phase 组合
"执行 Phase B 和 C"
"运行 [B, C]"

# 步骤组合
"只执行 B.2 和 C.1"
```

### 隐式触发 (通过 state-scanner)

```yaml
# state-scanner 推荐
state_scanner_recommendation:
  workflow: quick-fix
  reason: "≤3 文件变更，类型为 bugfix"

# 用户确认后自动触发
→ workflow-runner 执行 quick-fix
```

### 参数覆盖

```yaml
# 覆盖默认配置
"运行 feature-dev，覆盖率阈值 90%"
→ phases:
    - phase: B
      config:
        coverage_threshold: 90
    - phase: C
```

---

## 错误处理

### Phase 级别配置

```yaml
phases:
  - phase: B
    on_error:
      action: stop          # stop | continue | rollback
      preserve:
        - branch_name       # 保留已创建的分支
      suggest: "修复测试后从 Phase B 重新开始"

  - phase: C
    on_error:
      action: rollback
      rollback_to: phase_b  # 回滚到 Phase B 完成状态
```

### 全局配置

```yaml
error_handling:
  default_action: stop
  log_level: info
  notify_on_failure: true
```

---

## 与 state-scanner 集成

### 推荐映射

| state-scanner 规则 | 推荐工作流 |
|-------------------|-----------|
| commit_only | commit-only |
| quick_fix | quick-fix |
| feature_with_spec | feature-dev (跳过 A.1) |
| doc_only | doc-update |
| feature_new | full-cycle |
| requirements_issues | requirements-check |
| pending_stories | iteration-planning |
| missing_prd | (建议创建 PRD) |
| forgejo_drift | requirements-update |

### 上下文传递

```yaml
# state-scanner 传递给 workflow-runner
from_state_scanner:
  workflow: quick-fix
  context:
    phase_cycle: "Phase4-Cycle9"
    module: "mobile"
    changed_files: [...]
    openspec_id: null
    branch: "feature/fix-bug"

# workflow-runner 转发给 Phase Skills
to_phase_skills:
  context: ${from_state_scanner.context}
  additional:
    workflow_id: "quick-fix"
    started_at: "2025-12-25T10:00:00Z"
```

---

## 示例：完整执行流程

### feature-dev 工作流

```yaml
1. 接收输入:
   workflow: feature-dev
   context:
     phase_cycle: "Phase4-Cycle9"
     module: "mobile"
     user_intent: "添加用户认证"

2. 执行 Phase A:
   → phase-a-planner
   ← output:
       spec_id: "add-auth-feature"
       task_count: 5
       assigned_agents: {...}

3. 执行 Phase B:
   → phase-b-developer
   ← output:
       branch_name: "feature/mobile/TASK-001-add-auth"
       test_passed: true
       coverage: 87.5

4. 执行 Phase C:
   → phase-c-integrator
   ← output:
       commit_sha: "abc1234"
       pr_url: "https://..."
       pr_number: 123

5. 汇总报告:
   status: SUCCESS
   phases_executed: [A, B, C]
   total_time: 2m 15s
```

---

**最后更新**: 2025-12-25
**版本**: 2.0.0

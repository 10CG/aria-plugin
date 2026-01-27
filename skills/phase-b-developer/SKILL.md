---
name: phase-b-developer
description: |
  十步循环 Phase B - 开发阶段执行器，编排 B.1-B.3 步骤。

  使用场景："执行开发阶段"、"Phase B"、"创建分支并运行测试"
argument-hint: "[--skip-tests]"
disable-model-invocation: false
user-invocable: true
allowed-tools: Bash, Read, Write, Glob, Grep, Task
---

# Phase B - 开发阶段 (Developer)

> **版本**: 1.3.0 | **十步循环**: B.1-B.3
> **更新**: 2026-01-22 - 集成 TDD 双保险机制

## 快速开始

### 我应该使用这个 Skill 吗？

**使用场景**:
- 需要创建功能分支
- 需要运行测试验证
- 需要同步架构文档
- 代码开发完成后的验证阶段

**不使用场景**:
- 已在功能分支 → 跳过 B.1
- 无测试文件 → B.2 降级模式
- 无架构变更 → 跳过 B.3

---

## 核心功能

| 步骤 | Skill | 职责 | 输出 |
|------|-------|------|------|
| B.1 | branch-manager | 分支创建 | branch_name |
| B.2 | test-verifier | 测试验证 | test_passed, coverage |
| B.3 | arch-update | 架构同步 | arch_updated |

---

## 执行流程

### 输入

```yaml
context:
  phase_cycle: "Phase4-Cycle9"
  module: "mobile"
  changed_files: ["lib/auth.dart", "test/auth_test.dart"]
  spec_id: "add-auth-feature"      # 来自 Phase A
  task_list: [TASK-001, ...]       # 来自 Phase A

config:
  skip_steps: []
  params:
    coverage_threshold: 80
    branch_prefix: "feature"
```

### 步骤执行

```yaml
B.1 - 分支管理:
  skill: branch-manager
  action: create
  skip_if:
    - already_on_feature_branch: true
  action:
    - 检查当前分支
    - 创建功能分支
  output:
    branch_name: "feature/mobile/TASK-001-add-auth"

B.2 - 测试验证:
  skill: test-verifier
  params:
    coverage_threshold: 80
  degrade_if:
    - no_test_files: true           # 降级模式，不阻塞
  action:
    - 检测变更文件类型
    - 运行对应测试
    - 检查覆盖率
  output:
    test_passed: true
    coverage: 87.5
    tests_run: 15

B.3 - 架构同步:
  skill: arch-update
  skip_if:
    - no_architecture_changes: true
  action:
    - 检测架构相关变更
    - 更新 ARCHITECTURE.md
  output:
    arch_updated: true
    files_modified: ["docs/ARCHITECTURE.md"]
```

### 输出

```yaml
success: true
steps_executed: [B.1, B.2, B.3]
steps_skipped: []
results:
  B.1:
    branch_name: "feature/mobile/TASK-001-add-auth"
  B.2:
    test_passed: true
    coverage: 87.5
  B.3:
    arch_updated: true

context_for_next:
  branch_name: "feature/mobile/TASK-001-add-auth"
  test_results:
    passed: true
    coverage: 87.5
  arch_sync_status: "updated"
```

---

## 跳过规则

| 条件 | 跳过步骤 | 检测方法 |
|------|---------|----------|
| 已在功能分支 | B.1 | 当前分支不是 main/develop |
| 无测试文件 | B.2 (降级) | 变更文件无对应 *_test.* |
| 无架构变更 | B.3 | 无 ARCHITECTURE.md 变更 |

### 跳过逻辑

```yaml
skip_evaluation:
  B.1:
    - check: git branch --show-current
      skip_if: not in [main, master, develop]
      reason: "已在功能分支"

  B.2:
    - check: test file mapping
      degrade_if: no corresponding test files
      action: 运行但不阻塞，输出警告

  B.3:
    - check: changed_files
      skip_if: no files match *ARCHITECTURE*.md
      reason: "无架构文档变更"
```

---

## 输出格式

```
╔══════════════════════════════════════════════════════════════╗
║              PHASE B - DEVELOPMENT                           ║
╚══════════════════════════════════════════════════════════════╝

📋 执行计划
───────────────────────────────────────────────────────────────
  B.1 branch-manager    → 创建分支
  B.2 test-verifier     → 测试验证
  B.3 arch-update       → 架构同步 (跳过 - 无架构变更)

🚀 执行中...
───────────────────────────────────────────────────────────────
  ✅ B.1 完成 → 分支: feature/mobile/TASK-001-add-auth
  ✅ B.2 完成 → 测试: 15/15 通过, 覆盖率: 87.5%
  ○  B.3 跳过 → 理由: 无架构文档变更

📤 上下文输出
───────────────────────────────────────────────────────────────
  branch: feature/mobile/TASK-001-add-auth
  tests: passed (87.5% coverage)
  ready_for: Phase C
```

---

## 使用示例

### 示例 1: 完整开发阶段

```yaml
输入:
  context:
    module: "mobile"
    changed_files: ["lib/auth.dart", "test/auth_test.dart"]

执行:
  B.1: 创建分支 → feature/mobile/TASK-001-add-auth
  B.2: 运行测试 → 15/15 通过
  B.3: 更新架构 → ARCHITECTURE.md 已更新

输出:
  context_for_next:
    branch_name: "feature/mobile/TASK-001-add-auth"
    test_passed: true
```

### 示例 2: 跳过分支创建

```yaml
输入:
  current_branch: "feature/add-auth"  # 已在功能分支

执行:
  B.1: 跳过 (已在功能分支)
  B.2: 运行测试
  B.3: 检查架构

输出:
  steps_skipped: [B.1]
  branch_name: "feature/add-auth"  # 使用现有分支
```

### 示例 3: 测试降级

```yaml
输入:
  changed_files: ["lib/new_feature.dart"]  # 无对应测试

执行:
  B.1: 创建分支
  B.2: 降级模式 (警告无测试)
  B.3: 检查架构

输出:
  B.2:
    mode: "degraded"
    warning: "lib/new_feature.dart 没有对应测试"
    suggestion: "使用 flutter-test-generator 生成测试"
```

---

## 错误处理

| 错误 | 原因 | 处理 |
|------|------|------|
| 分支创建失败 | 分支已存在 | 切换到现有分支 |
| 测试失败 | 代码问题 | 停止执行，报告失败 |
| 架构更新失败 | 文档格式错误 | 输出警告，继续执行 |

### 测试失败处理

```yaml
on_test_failure:
  action: stop
  report:
    - 失败的测试列表
    - 错误信息
    - 修复建议
  next_step: "修复测试后重新运行 Phase B"
```

---

## 与其他 Phase 的关系

```
phase-a-planner
    │
    │ context:
    │   - spec_id
    │   - task_list
    ▼
phase-b-developer (本 Skill)
    │
    │ context_for_next:
    │   - branch_name
    │   - test_results
    │   - arch_sync_status
    ▼
phase-c-integrator
```

---

## 新技能集成 (v1.2.0)

> **新增于 v1.2.0** - 集成 enforcement-mechanism-redesign 新技能

### 技能依赖图

```
phase-b-developer
    │
    ├──> branch-manager v2.0.0
    │    └── 自动模式决策 (Branch/Worktree)
    │
    ├──> subagent-driver v1.0.0
    │    └── Fresh Subagent 执行
    │
    └──> branch-finisher v1.0.0
         └── 完成流程 + 测试验证
```

### B.1 分支管理增强

```yaml
B.1 - 分支管理 (增强版):
  skill: branch-manager v2.0.0
  features:
    - 自动模式决策 (5因子评分)
    - Branch 模式 (简单任务)
    - Worktree 模式 (复杂/并行任务)

  mode_decision:
    factors:
      - file_count: 变更文件数
      - cross_directory: 跨目录变更
      - task_count: 任务数量
      - risk_level: 风险等级
      - parallel_needed: 并行需求
    threshold: 3  # >= 3 使用 Worktree

  output:
    mode: "branch" | "worktree"
    branch_name: "feature/mobile/TASK-001-xxx"
    worktree_path: ".git/worktrees/TASK-001-xxx"  # 仅 worktree 模式
```

### B.2 开发执行增强

```yaml
B.2 - 开发执行 (增强版):
  skill: subagent-driver v1.0.0
  features:
    - Fresh Subagent 模式
    - 任务间代码审查
    - 4选项完成流程
    - TDD 强制执行 (方案 A)

  execution_pattern:
    for_each_task:
      1. 启动 Fresh Subagent (隔离上下文)
      2. 应用 TDD 约束 (RED-GREEN-REFACTOR)
      3. 执行任务
      4. 任务间代码审查
      5. 更新状态

    tdd_enforcement:
      enabled: true              # 自动启用 TDD
      mode: "enforce"             # enforce | monitor | off
      rules:
        - test_before_code: true  # 必须先写测试
        - fail_first: true        # 测试必须先失败
        - minimal_implementation: true  # 最小实现原则

    inter_task_review:
      severity_levels:
        - Critical: 阻塞，必须修复
        - Major: 警告，建议修复
        - Minor: 提示，可忽略

  output:
    tasks_completed: [TASK-001, TASK-002, ...]
    review_issues: [...]
    tdd_compliance: "passed"      # TDD 合规状态
    context_for_finisher: {...}
```

### B.3 完成流程增强

```yaml
B.3 - 完成流程 (增强版):
  skill: branch-finisher v1.0.0
  features:
    - 测试前置验证
    - 4选项完成流程
    - Worktree 智能清理

  pre_validation:
    blocking:
      - unit_tests: 单元测试必须通过
      - type_check: 类型检查必须通过
      - build: 构建必须成功
    warning:
      - lint: Lint 检查 (可警告通过)
      - coverage: 覆盖率检查 (可警告通过)

  completion_options:
    "[1] 提交并创建 PR":
      action: commit + PR
      worktree_cleanup: 询问用户
    "[2] 继续修改":
      action: 返回开发
      worktree_cleanup: 否
    "[3] 放弃变更":
      action: 回滚
      worktree_cleanup: 强制清理
    "[4] 暂停保存":
      action: 保存状态
      worktree_cleanup: 否
```

### 集成执行流程

```yaml
完整 Phase B 执行流程 (v1.2.0):

  1. 接收 Phase A 输出
     ├── spec_id
     ├── task_list
     └── complexity_score

  2. B.1 分支管理 (branch-manager)
     ├── 评估复杂度
     ├── 决策模式 (Branch/Worktree)
     └── 创建分支/Worktree

  3. B.2 开发执行 (subagent-driver)
     ├── 加载任务列表
     ├── 逐任务执行 (Fresh Subagent)
     ├── 任务间审查
     └── 汇总结果

  4. B.3 完成流程 (branch-finisher)
     ├── 测试前置验证
     ├── 4选项完成流程
     └── Worktree 清理决策

  5. 输出到 Phase C
     ├── branch_name
     ├── test_results
     ├── completion_option
     └── ready_for_integration
```

### 配置参数

```yaml
phase_b_config:
  # branch-manager 配置
  branch_manager:
    mode_threshold: 3
    worktree_base: ".git/worktrees"
    branch_prefix: "feature"

  # subagent-driver 配置
  subagent_driver:
    isolation_level: "L2"  # L1/L2/L3
    enable_inter_task_review: true
    critical_blocks: true

  # branch-finisher 配置
  branch_finisher:
    run_tests: true
    run_lint: true
    run_build: true
    coverage_threshold: 85
    auto_cleanup: false

  # TDD 双保险配置 (v1.3.0 新增)
  tdd:
    # 方案 A: Fresh Subagent TDD 保护
    subagent_level:
      enabled: true
      mode: "enforce"           # enforce | monitor | off
      rules:
        test_before_code: true
        fail_first: true
        minimal_implementation: true

    # 方案 B: 主会话 TDD 保护 (由 workflow-runner 启用)
    session_level:
      enabled: true             # 由 workflow-runner pre-hook 控制
      strict_mode: false        # 首次使用建议 false
      skip_patterns:
        - "**/*.md"
        - "**/*.json"
        - "**/config/**"
```

---

## 相关文档

### 核心技能 (v1.2.0 新增)

- [branch-manager](../branch-manager/SKILL.md) - B.1 分支管理 (v2.0.0 自动模式决策)
- [subagent-driver](../subagent-driver/SKILL.md) - B.2 开发执行 (Fresh Subagent)
- [branch-finisher](../branch-finisher/SKILL.md) - B.3 完成流程 (测试验证+清理)

### 辅助技能

- [test-verifier](../test-verifier/SKILL.md) - 测试验证 (被 branch-finisher 调用)
- [arch-update](../arch-update/SKILL.md) - 架构同步
- [tdd-enforcer](../tdd-enforcer/SKILL.md) - TDD 强制执行

### Phase 关联

- [phase-a-planner](../phase-a-planner/SKILL.md) - 上一阶段
- [phase-c-integrator](../phase-c-integrator/SKILL.md) - 下一阶段

---

**最后更新**: 2026-01-21
**Skill版本**: 1.2.0

---

## Git Worktree 集成

> **新增于 v1.1.0**

Phase B 支持使用 Git Worktrees 创建隔离的开发环境。

### Worktree 模式

```yaml
use_worktree: true  # 启用 worktree 模式

B.1 - 分支创建 (Worktree 模式):
  action:
    - 使用 branch-manager 的 worktree 创建
    - 工作目录: .git/worktrees/{task-name}/
  output:
    worktree_path: ".git/worktrees/TASK-001-user-auth"
    branch_name: "feature/backend/TASK-001-user-auth"
```

### Worktree 路径切换

```yaml
切换到 worktree:
  command: cd .git/worktrees/{task-name}/

返回主分支:
  command: cd ../..

清理 worktree:
  command: git worktree remove .git/worktrees/{task-name}/
```

### Worktree 配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `use_worktree` | `false` | 是否启用 worktree 模式 |
| `worktree_base` | `.git/worktrees` | worktree 基础路径 |

---

## 两阶段评审机制

> **新增于 v1.1.0**

Phase B 扩展支持两阶段评审：**规范合规性** → **代码质量**。

### 评审流程

```yaml
B.Review - 两阶段评审:

  Phase 1 - 规范合规性检查:
    enabled: true
    blocking: true
    checks:
      - OpenSpec 格式验证
      - UPM 状态同步检查
      - 架构文档同步检查
    output:
      spec_compliance: pass/fail
      issues: [...]

  Phase 2 - 代码质量检查:
    enabled: true
    blocking: false  # 警告但不阻塞
    checks:
      - 测试覆盖率检查 (>= 85%)
      - 代码复杂度分析
      - 安全漏洞扫描
    output:
      code_quality_score: 0-100
      recommendations: [...]
```

### Phase 1: 规范合规性

| 检查项 | 说明 | 阻塞 |
|--------|------|------|
| OpenSpec 格式 | proposal.md/tasks.md 格式正确 | ✅ |
| UPM 状态 | 进度状态与实际一致 | ✅ |
| 架构文档 | 代码变更与文档同步 | ✅ |

**失败处理**: 关键问题必须修复后方可继续

### Phase 2: 代码质量

| 检查项 | 阈值 | 阻塞 |
|--------|------|------|
| 测试覆盖率 | >= 85% | ❌ (警告) |
| 代码复杂度 | <= 10 | ❌ (警告) |
| 安全扫描 | 无高危漏洞 | ❌ (警告) |

**失败处理**: 记录警告，生成改进建议

### 评审报告

```yaml
评审报告格式:
  summary:
    phase1_status: "pass"
    phase2_status: "warning"
    overall_score: 85

  phase1_issues:
    - severity: "critical"
      description: "UPM 状态未更新"
      fix_required: true

  phase2_recommendations:
    - type: "coverage"
      current: 82
      target: 85
      suggestion: "为 AuthManager 添加测试用例"
```

### 阻塞机制

```yaml
阻塞条件:
  - Phase 1 有 critical 级别问题
  - OpenSpec 格式验证失败

绕过选项:
  - 用户显式确认 "force_continue"
  - 标记为 "technical_debt" (技术债务)
```

### 评审配置

```yaml
review_config:
  enabled: true
  phase1:
    enabled: true
    blocking: true
    checks:
      openspec_format: true
      upm_sync: true
      arch_doc_sync: true
  phase2:
    enabled: true
    blocking: false
    checks:
      test_coverage:
        threshold: 85
      code_complexity:
        threshold: 10
      security_scan:
        level: "high"
```

---

## 两阶段评审与 Worktree 配合使用

```yaml
完整流程 (Worktree + 两阶段评审):

  B.1 - 创建 Worktree 分支
  ↓
  B.2 - 开发 + 测试验证
  ↓
  B.Review - Phase 1: 规范合规性
  ↓ (通过)
  B.Review - Phase 2: 代码质量
  ↓ (警告/通过)
  B.3 - 架构同步
```

---

## 相关文档 (更新)

- [branch-manager](../branch-manager/SKILL.md) - B.1 分支管理 + Worktree 支持
- [test-verifier](../test-verifier/SKILL.md) - B.2 测试验证
- [arch-update](../arch-update/SKILL.md) - B.3 架构同步
- [tdd-enforcer](../tdd-enforcer/SKILL.md) - TDD 强制执行
- [subagent-driver](../subagent-driver/SKILL.md) - B.2 Fresh Subagent 执行
- [branch-finisher](../branch-finisher/SKILL.md) - B.3 完成流程
- [phase-a-planner](../phase-a-planner/SKILL.md) - 上一阶段
- [phase-c-integrator](../phase-c-integrator/SKILL.md) - 下一阶段
- [Aria Workflow Enhancement](../../../standards/openspec/changes/aria-workflow-enhancement/proposal.md) - 增强提案

---

## TDD 双保险机制 (v1.3.0 新增)

> **设计目标**: 确保无论通过何种方式执行代码编写，TDD 规则都会被强制执行

### 为什么需要双保险？

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        TDD 保护缺口分析                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  单一保护点的问题:                                                       │
│  ┌────────────────┐      ┌────────────────┐                            │
│  │ workflow-runner│──┬──▶│ phase-b-dev    │                            │
│  │  (主会话 Hook) │  │   │                │                            │
│  └────────────────┘  │   └────────┬───────┘                            │
│                      │            │                                    │
│                      │            ├──▶ subagent-driver                   │
│                      │            │        │                            │
│                      │            │        ▼                            │
│                      │            │  ┌─────────────┐                    │
│                      │            │  │Fresh Subagent│ ← 新会话，无 Hook │
│                      │            │  └─────────────┘                    │
│                      │            │        ❌ TDD 保护失效              │
│                      │            │                                    │
│  用户直接编辑代码 ───┴────────────┴── ❌ 绕过 phase-b                  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                        双保险保护方案                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌────────────────┐                                                    │
│  │ workflow-runner│                                                    │
│  │  Pre-Hook B    │ ──▶ 方案 B: 启用主会话 TDD Hook                     │
│  └────────┬───────┘           ↓                                        │
│           │              ┌─────────┐                                   │
│           ▼              │主会话 TDD│ ← 保护用户直接编辑               │
│  ┌────────────────┐      └─────────┘                                   │
│  │ phase-b-dev    │                                                     │
│  │                │ ──▶ 方案 A: 传递 TDD 配置给 Subagent               │
│  └────────┬───────┘           ↓                                        │
│           │              ┌─────────────┐                               │
│           └─────────────▶│Subagent TDD │ ← 保护 Fresh Subagent        │
│                          └─────────────┘                               │
│                                                                         │
│  ✅ 完整闭环：主会话 + 子会话全覆盖                                     │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 方案 A: Fresh Subagent TDD 保护

```yaml
作用对象: subagent-driver 启动的 Fresh Subagent
触发时机: B.2 阶段调用 subagent-driver 时
传递方式: 通过 context 传递 TDD 配置
保护范围: 子会话内的所有代码编写操作

配置:
  phase_b_config.tdd.subagent_level:
    enabled: true
    mode: "enforce"
    rules:
      test_before_code: true
      fail_first: true
      minimal_implementation: true
```

### 方案 B: 主会话 TDD 保护

```yaml
作用对象: workflow-runner 主会话
触发时机: 进入 Phase B 之前的 pre-hook
启用方式: workflow-runner 自动调用 tdd-enforcer
保护范围: 主会话内的所有代码编写操作

配置:
  phase_b_config.tdd.session_level:
    enabled: true
    strict_mode: false
    skip_patterns: ["**/*.md", "**/*.json"]
```

### 执行流程

```yaml
完整 Phase B 执行 (TDD 双保险):

  1. workflow-runner pre-hook (方案 B)
     ├── 检测即将进入 Phase B
     ├── 调用 tdd-enforcer 启用主会话 TDD
     └── 返回 tdd_session_id

  2. phase-b-developer 执行
     ├── B.1: 创建分支
     ├── B.2: subagent-driver (方案 A)
     │   ├── 传递 TDD 配置到 Fresh Subagent
     │   ├── Fresh Subagent 启用时加载 TDD 约束
     │   └── 每个任务执行时强制 TDD
     └── B.3: branch-finisher
         ├── 运行所有测试 (质量门禁)
         └── 4 选项完成流程

  3. workflow-runner post-hook
     ├── 检测 Phase B 完成
     └── 可选: 保持或关闭 TDD Hook
```

### 配置优先级

```yaml
TDD 配置优先级 (从高到低):

  1. 项目配置 (.claude/tdd-config.json)
     └── 项目级开关，最高优先级

  2. 环境变量 (ARIA_TDD_ENABLED)
     └── 环境级覆盖

  3. phase_b_config.tdd
     └── Phase B 级别配置

  4. 默认值 (enabled: false)
     └── 兜底默认值
```

### 禁用 TDD

```yaml
# 方式 1: 项目级配置 (.claude/tdd-config.json)
{
  "enabled": false
}

# 方式 2: Phase 配置
phase_b_config:
  tdd:
    subagent_level:
      enabled: false
    session_level:
      enabled: false

# 方式 3: 临时跳过 (特定文件)
# tdd-enforcer 会根据 skip_patterns 自动跳过
```

---

**最后更新**: 2026-01-22
**Skill版本**: 1.3.0

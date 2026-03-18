---
name: phase-c-integrator
description: |
  十步循环 Phase C - 集成阶段执行器，编排 C.1-C.2 步骤。

  使用场景："执行集成阶段"、"Phase C"、"提交代码并创建 PR"
argument-hint: "[--skip-pr]"
disable-model-invocation: false
user-invocable: true
allowed-tools: Bash, Read, Write, Glob, Grep, Task
---

# Phase C - 集成阶段 (Integrator)

> **版本**: 1.1.0 | **十步循环**: C.1-C.2
> **更新**: 2026-01-21 - 集成 branch-finisher 完成流程

## 快速开始

### 我应该使用这个 Skill 吗？

**使用场景**:
- 需要提交代码变更
- 需要创建 Pull Request
- 需要合并分支
- 开发完成后的集成阶段

**不使用场景**:
- 无变更需要提交 → 跳过 C.1
- 不需要 PR → 跳过 C.2

---

## 配置 (config-loader)

执行前读取 `.aria/config.json`，缺失则使用默认值。参见 [config-loader](../config-loader/SKILL.md)。

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `experiments.agent_team_audit` | `false` | 启用 Agent Team 审计 (实验功能) |
| `experiments.agent_team_audit_points` | `["pre_merge"]` | 审计触发点 |

当 `agent_team_audit=true` 且 `"pre_merge"` 在 `agent_team_audit_points` 中时，C.2 合并前触发 Agent Team 审计。

---

## 核心功能

| 步骤 | Skill | 职责 | 输出 |
|------|-------|------|------|
| C.1 | commit-msg-generator | Git 提交 | commit_sha, message |
| C.2 | branch-manager | PR/合并 | pr_url, pr_number |

---

## 执行流程

### 输入

```yaml
context:
  phase_cycle: "Phase4-Cycle9"
  module: "mobile"
  changed_files: ["lib/auth.dart", "test/auth_test.dart"]
  branch_name: "feature/mobile/TASK-001-add-auth"  # 来自 Phase B
  test_results:                                     # 来自 Phase B
    passed: true
    coverage: 87.5

  # v1.1.0 新增: branch-finisher 输出
  completion_option: 1                              # 来自 branch-finisher
  worktree_path: ".git/worktrees/TASK-001-xxx"     # 可选
  validation_report:                                # 来自 branch-finisher
    passed: true
    blocking_failures: 0
    warnings: 1

config:
  skip_steps: []
  params:
    enhanced_markers: true        # 使用增强提交标记
    create_pr: true               # 是否创建 PR
```

### 步骤执行

```yaml
C.1 - Git 提交:
  skill: commit-msg-generator
  params:
    enhanced_markers: true
    subagent_type: "from_context"
    phase_cycle: "from_context"
    module: "from_context"
  skip_if:
    - no_changes_to_commit: true
  action:
    - 分析暂存区变更
    - 生成规范提交消息
    - 执行 git commit
  output:
    commit_sha: "abc1234"
    commit_message: "feat(auth): 添加用户认证..."

C.2 - PR/合并:
  skill: branch-manager
  action: pr
  skip_if:
    - no_pr_needed: true
    - direct_push_allowed: true
  action:
    - 推送分支到远程
    - 创建 Pull Request
    - (可选) 自动合并
  output:
    pr_url: "https://..."
    pr_number: 123

> **注意**: branch-manager 会自动处理 Cloudflare Access 配置。
> 统一规范见 `../forgejo-sync/PRE_CHECK.md`
```

### 输出

```yaml
success: true
steps_executed: [C.1, C.2]
steps_skipped: []
results:
  C.1:
    commit_sha: "abc1234"
    commit_message: "feat(auth): 添加用户认证..."
  C.2:
    pr_url: "https://..."
    pr_number: 123

context_for_next:
  commit_sha: "abc1234"
  pr_url: "https://..."
```

---

## 跳过规则

| 条件 | 跳过步骤 | 检测方法 |
|------|---------|----------|
| 无变更 | C.1 | git status --porcelain 为空 |
| 不需要 PR | C.2 | 配置或分支策略 |
| 直接推送 | C.2 | 在 develop 分支 |

### 跳过逻辑

```yaml
skip_evaluation:
  C.1:
    - check: git status --porcelain
      skip_if: empty
      reason: "没有需要提交的变更"

  C.2:
    - check: branch_name
      skip_if: in [develop, main]
      reason: "主分支不需要 PR"

    - check: config.create_pr
      skip_if: false
      reason: "配置为不创建 PR"
```

---

## 输出格式

```
╔══════════════════════════════════════════════════════════════╗
║              PHASE C - INTEGRATION                           ║
╚══════════════════════════════════════════════════════════════╝

📋 执行计划
───────────────────────────────────────────────────────────────
  C.1 commit-msg-generator  → Git 提交
  C.2 branch-manager        → 创建 PR

🚀 执行中...
───────────────────────────────────────────────────────────────
  ✅ C.1 完成 → Commit: abc1234
     Message: feat(auth): 添加用户认证 / Add user authentication

  ✅ C.2 完成 → PR #123 已创建
     URL: https://github.com/...

📤 上下文输出
───────────────────────────────────────────────────────────────
  commit: abc1234
  pr: #123
  ready_for: Phase D (可选)
```

---

## 使用示例

### 示例 1: 完整集成

```yaml
输入:
  context:
    branch_name: "feature/add-auth"
    test_results: { passed: true }

执行:
  C.1: 提交代码 → abc1234
  C.2: 创建 PR → #123

输出:
  commit_sha: "abc1234"
  pr_url: "https://..."
```

### 示例 2: 仅提交

```yaml
输入:
  config:
    create_pr: false

执行:
  C.1: 提交代码
  C.2: 跳过 (不需要 PR)

输出:
  steps_skipped: [C.2]
  commit_sha: "abc1234"
```

### 示例 3: 直接推送

```yaml
输入:
  context:
    branch_name: "develop"  # 在主分支

执行:
  C.1: 提交代码
  C.2: 跳过 (主分支不需要 PR)
  额外: git push

输出:
  commit_sha: "abc1234"
  pushed: true
```

---

## 提交消息增强

### 增强标记格式

```
feat(auth): 添加用户认证 / Add user authentication

- 实现 JWT token 验证
- 添加登录 API 端点

🤖 Executed-By: mobile-developer subagent
📋 Context: Phase4-Cycle9 功能开发
🔗 Module: mobile
```

### 标记来源

| 标记 | 来源 |
|------|------|
| 🤖 Executed-By | 执行的 Agent 类型 |
| 📋 Context | Phase/Cycle + 任务描述 |
| 🔗 Module | 活跃模块名 |

---

## 错误处理

| 错误 | 原因 | 处理 |
|------|------|------|
| 提交失败 | hook 拒绝 | 显示 hook 错误，提示修复 |
| PR 创建失败 | 权限问题 | 提示检查权限 |
| 推送失败 | 远程冲突 | 提示拉取最新代码 |

### Hook 失败处理

```yaml
on_commit_hook_failure:
  action: stop
  report:
    - Hook 错误信息
    - 缺少的标记或格式问题
  next_step: "使用 commit-msg-generator 重新生成消息"
```

---

## branch-finisher 集成 (v1.1.0)

> **新增于 v1.1.0** - 集成 branch-finisher 完成流程

### 完成选项处理

```yaml
completion_option_handling:
  "[1] 提交并创建 PR":
    action: 执行完整 Phase C
    steps: [C.1, C.2]
    worktree_cleanup: 在 PR 创建后询问

  "[2] 继续修改":
    action: 跳过 Phase C
    steps: []
    reason: "用户选择继续修改，不进入集成阶段"

  "[3] 放弃变更":
    action: 跳过 Phase C
    steps: []
    reason: "变更已放弃，无需集成"
    worktree_cleanup: 强制执行

  "[4] 暂停保存":
    action: 跳过 Phase C
    steps: []
    reason: "用户选择暂停，稍后恢复"
```

### 入口前置检查

```yaml
pre_check:
  # 检查 branch-finisher 输出
  completion_option:
    required: true
    valid_for_phase_c: [1]  # 只有选项 1 进入 Phase C

  # 检查测试验证结果
  validation_report:
    required: true
    must_pass: true
    warn_on: warnings > 0

  # 检查 Worktree 状态
  worktree_path:
    check: if exists
    action: 记录，用于后续清理
```

### 集成流程增强

```yaml
enhanced_flow:
  1. 接收 branch-finisher 输出
     ├── completion_option
     ├── validation_report
     └── worktree_path (可选)

  2. 前置检查
     ├── 验证 completion_option == 1
     ├── 验证 validation_report.passed
     └── 记录 worktree_path

  3. 执行 C.1 (提交)
     ├── 使用 commit-msg-generator
     ├── 包含增强标记
     └── 关联 task_id

  4. 执行 C.2 (PR)
     ├── 使用 branch-manager
     ├── 创建 PR
     └── 包含测试验证结果

  5. Worktree 清理决策
     ├── PR 创建成功?
     ├── 询问用户是否清理
     └── 执行清理或保留
```

### Worktree 清理时机

```yaml
worktree_cleanup_timing:
  trigger: PR 创建成功后
  default: 询问用户
  options:
    - "[1] 立即清理 (推荐)"
    - "[2] 保留 worktree"

  auto_cleanup_if:
    - PR merged
    - PR closed
```

### 输出增强

```yaml
context_for_next:
  # 原有字段
  commit_sha: "abc1234"
  pr_url: "https://..."
  pr_number: 123

  # v1.1.0 新增字段
  completion_option: 1
  worktree_status: "cleaned" | "preserved"
  validation_summary:
    passed: true
    warnings: 1
```

---

## 与其他 Phase 的关系

```
phase-b-developer
    │
    │ context:
    │   - branch_name
    │   - test_results
    ▼
branch-finisher (v1.1.0 新增)
    │
    │ context:
    │   - completion_option
    │   - validation_report
    │   - worktree_path
    ▼
phase-c-integrator (本 Skill)
    │
    │ context_for_next:
    │   - commit_sha
    │   - pr_url
    │   - worktree_status
    ▼
phase-d-closer
```

---

## 相关文档

### 核心技能

- [commit-msg-generator](../commit-msg-generator/SKILL.md) - C.1 提交生成
- [branch-manager](../branch-manager/SKILL.md) - C.2 PR/合并

### 集成技能 (v1.1.0 新增)

- [branch-finisher](../branch-finisher/SKILL.md) - 完成流程入口

### Phase 关联

- [phase-b-developer](../phase-b-developer/SKILL.md) - 上一阶段
- [phase-d-closer](../phase-d-closer/SKILL.md) - 下一阶段

---

**最后更新**: 2026-01-21
**Skill版本**: 1.1.0

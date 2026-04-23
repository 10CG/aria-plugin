---
name: phase-c-integrator
description: |
  十步循环 Phase C - 集成阶段执行器，编排 C.1-C.2 步骤。

  使用场景："执行集成阶段"、"Phase C"、"提交代码并创建 PR"
argument-hint: "[--skip-pr]"
disable-model-invocation: false
user-invocable: true
allowed-tools: Bash, Read, Write, Glob, Grep, Task, Skill
---

# Phase C - 集成阶段 (Integrator)

> **版本**: 1.2.0 | **十步循环**: C.1-C.2
> **更新**: 2026-03-27 - 升级审计触发从 agent-team-audit 改为 audit-engine

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
| `audit.enabled` | `false` | 启用 audit-engine 审计 (新) |
| `audit.checkpoints.pre_merge` | `"off"` | pre_merge 检查点模式 |
| `experiments.agent_team_audit` | `false` | 旧配置 (向后兼容，自动映射到 audit.*) |
| `experiments.agent_team_audit_points` | `["pre_merge"]` | 旧配置 (向后兼容) |
| `upm.milestone_driven` | `false` | 启用 C.2.6 里程碑子进度追加 (opt-in) |

当 `audit.enabled=true` 且 `audit.checkpoints.pre_merge != "off"` 时，C.2 合并前触发 audit-engine (pre_merge 检查点)。
旧配置 `experiments.agent_team_audit=true` 且 `"pre_merge" in agent_team_audit_points` 自动映射到新配置。

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
  pre_hook:                               # audit-engine 检查点
    audit_engine:
      checkpoint: pre_merge
      步骤:
        1. 通过 config-loader 读取 .aria/config.json audit 块
        2. 检查 audit.enabled — false 则跳过，保持现有行为不变
        3. 检查 audit.checkpoints.pre_merge — "off" 则跳过
        4. 如启用: 调用 audit-engine
           - checkpoint: "pre_merge"
           - mode: 来自配置 (convergence / challenge / adaptive)
           - context: PR diff (branch_name vs base)
        5. 处理 verdict:
           - PASS / PASS_WITH_WARNINGS → 继续推送和创建 PR
           - FAIL → 阻塞合并，输出审计报告
      backward_compat:
        audit.enabled=false: 完全跳过，Phase C 行为与之前完全相同
        旧配置 experiments.agent_team_audit: 由 audit-engine 内部映射处理
      fallback_description: |
        audit-engine 内部通过 agent-team-audit 单轮引擎执行审计。
        直接调用 agent-team-audit 已由 audit-engine 编排层取代。
      on_fail: 阻塞合并, 输出审计报告
      on_skip: 继续合并 (审计未启用)
  action:
    - (如 audit.enabled) 触发 audit-engine (pre_merge 检查点)
    - 推送分支到远程
    - 创建 Pull Request
    - (可选) 自动合并
  output:
    pr_url: "https://..."
    pr_number: 123
    audit_verdict: "PASS"                 # 如审计启用 (PASS | PASS_WITH_WARNINGS | FAIL)
    audit_report: ".aria/audit-reports/pre_merge-{timestamp}.md"

> **注意**: branch-manager 会自动处理 Cloudflare Access 配置。
> 统一规范见 `../forgejo-sync/PRE_CHECK.md`

C.2.5 - Multi-Remote Push Enforcement:
  触发条件:
    - Phase C.2 合并成功 (master 已 fast-forward)
    - 配置 phase_c_integrator.multi_remote_push.enabled: true (默认)
  skill: git-remote-helper (降级: 内联实现)
  action: 见下方 ### C.2.5 详细说明

C.2.6 - UPM Milestone Sub-progress Append (optional):
  触发条件:
    - C.2.5 multi-remote push 已完成 (或跳过)
    - 配置 upm.milestone_driven: true (默认 false，opt-in)
    - 当前 commit 与某 User Story 关联 (commit message 含 US-XXX 或 spec change_id)
  action: 见下方 ### C.2.6 详细说明
  backward_compat: upm.milestone_driven=false 时完全跳过，Phase C 行为与之前完全相同
```

### C.2.5 Multi-Remote Push Enforcement (v1.15.0+)

**触发条件**:
- Phase C.2 合并成功 (master 已 fast-forward)
- 配置 `phase_c_integrator.multi_remote_push.enabled: true` (默认)

**与 branch-manager 边界** (不重叠):
| Skill | 职责 | Remote 范围 |
|-------|------|-----------|
| branch-manager (C.2 PR 发起前) | 推送 feature 分支 + 创建 PR | 仅 origin |
| phase-c-integrator C.2.5 (PR 合并后) | 推送 master + 多 remote SHA 验证 | 所有 enforced remote |

**执行流程**:
1. 快照 `expected_sha = git rev-parse HEAD` (合并后本地 master HEAD)
2. 枚举子模块: `git submodule status --recursive`
3. 确定 `ENFORCED_REMOTES`: skill 级 `enforced_remotes == null` 时继承顶层 `multi_remote.enforced_remotes`, 空则自动发现所有 remote
4. **Per-Remote Matrix Gating** (对每个 REMOTE ∈ ENFORCED_REMOTES):
   - a. 遍历子模块, 调用 `git-remote-helper.push_all_remotes(SUBMODULE.path, SUBMODULE.branch, [REMOTE])`
   - b. 子模块推 REMOTE 任一失败 → 按失败优先级决策 (见下), 阻断则跳过本 REMOTE 的主仓库推送
   - c. 子模块全部成功 → 调用 helper.push_all_remotes(main_repo, branch, [REMOTE])
   - d. 主仓库推送成功 → 调用 helper.verify_parity_post_push(main_repo, branch, expected_sha, [REMOTE])
   - e. verify match=false → 同优先级决策
5. 所有 REMOTE 处理完毕, 全部通过 → 进入 Phase D
6. 任一阻断 → 输出具体失败 remote + 修复命令 (`git -C <path> push <remote> <branch>`)

**失败优先级** (决策表):
| 条件 | 行为 |
|------|------|
| remote ∈ `read_only_remotes` | warning 降级, 继续 (最高优先级) |
| `fail_on_partial_push: false` + 非 read_only | warning, 继续 |
| `fail_on_partial_push: true` + 非 read_only (默认) | **阻断**, 输出修复命令 |

**Per-Remote Matrix 示例**:
```
origin: sub1 ✅ sub2 ✅ main ✅ (已推)
github: sub1 ✅ sub2 ❌ (network timeout) → 跳过 main github; 但 origin 已完成
```

**子模块 detached HEAD**: 沿用 helper canonical (`detached_head: true` + HEAD SHA 比较), 警告但不阻断。

**降级策略**: 检测 `test -f "${ARIA_PLUGIN_ROOT:-aria}/skills/git-remote-helper/SKILL.md"` 存在性 (路径相对项目根; `ARIA_PLUGIN_ROOT` 环境变量优先)。不可用时用内联降级 (不重试, 简化实现), schema 仍一致。

**Race condition 处理**: verify 4 次 attempt 全部 match=false 默认阻断, 记录 "possible race condition"。

---

### C.2.6 UPM Milestone Sub-progress Append (v1.16.0+)

> **新增于 v1.16.0** — 修复 Forgejo #22 "multi-PR cycle UPM 信息盲区"问题。
> 源于 M1 closeout (2026-04-23) single-D.1 一次性更新 85 tasks 的实际痛点
> + silknode US-074 multi-PR migration 场景。

**触发条件**:
- C.2.5 已完成 (或已跳过)
- 配置 `upm.milestone_driven: true`
- commit message 或 spec change_id 中包含 `US-XXX` 模式

**关联识别逻辑**:

```bash
# 1. 从 commit message 中提取 US 编号
#    示例: "feat(m1): T4 complete — DEMO-001 E2E SUCCESS" 含 US-021 前缀
US_REF=$(git log -1 --format="%s %b" | grep -oE 'US-[0-9]+' | head -1)

# 2. 如果 commit message 无 US-XXX，尝试从 spec change_id 推断
if [ -z "$US_REF" ] && [ -n "$SPEC_CHANGE_ID" ]; then
  US_REF=$(grep -r "$SPEC_CHANGE_ID" openspec/changes/ \
    --include="proposal.md" -l | \
    xargs grep -oE 'US-[0-9]+' | head -1)
fi
```

**执行动作**:

```bash
# 获取当前 commit 信息
COMMIT_SHA=$(git rev-parse --short HEAD)
COMMIT_DATE=$(date +%Y-%m-%d)
COMMIT_TITLE=$(git log -1 --format="%s")
PR_URL="${PR_URL:-}"  # 来自 C.2 输出，无则留空

# 构造 sub-bullet
if [ -n "$PR_URL" ]; then
  SUB_BULLET="  - ${COMMIT_DATE}: ${COMMIT_SHA} — ${COMMIT_TITLE} (${PR_URL})"
else
  SUB_BULLET="  - ${COMMIT_DATE}: ${COMMIT_SHA} — ${COMMIT_TITLE}"
fi

# 定位 UPM 文档中对应 US 行并追加 sub-bullet
UPM_FILE=$(find . -name "unified-progress-management.md" \
  -not -path "*/archive/*" | head -1)

if [ -n "$UPM_FILE" ] && [ -n "$US_REF" ]; then
  # 将 [ ] IN_PROGRESS 更新为 [~] IN_PROGRESS (如当前状态为 [ ])
  sed -i "s/\[ \] \(.*${US_REF}.*\)/[~] \1/" "$UPM_FILE"
  # 在 US 行下方追加 sub-bullet
  sed -i "/.*${US_REF}.*/a\\${SUB_BULLET}" "$UPM_FILE"
fi
```

**状态标记约定**:

| 标记 | 含义 | 触发时机 |
|------|------|----------|
| `[ ]` | 未开始 / IN_PROGRESS (原有) | 初始状态 |
| `[~]` | 进行中，有中间进度记录 | C.2.6 首次追加时自动升级 |
| `[x]` | COMPLETED | D.1 final pass 写入 |

**sub-bullet 格式示例**:

```markdown
- [~] US-021: M1 MVP Layer 2 实现
  - 2026-04-20: abc1234 — feat(m1): T1 infra complete (https://forgejo.../pulls/18)
  - 2026-04-22: def5678 — feat(m1): T3 orchestrator ready (https://forgejo.../pulls/19)
  - 2026-04-23: ghi9012 — test(m1): T5 DEMO E2E complete (https://forgejo.../pulls/20)
```

**DoD**:
- `upm.milestone_driven=true` 时: UPM 文档对应 Story 行下出现 sub-bullet，状态从 `[ ]` 升级为 `[~]`
- `upm.milestone_driven=false` (默认) 时: Skill 无行为变化，完全向后兼容

**配置示例** (`.aria/config.json`):

```yaml
upm:
  milestone_driven: false  # 默认 false，保留 D.1-only 现有行为
                           # 设为 true 启用 C.2.6 中间进度追加
```

---

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

**最后更新**: 2026-03-27
**Skill版本**: 1.2.0

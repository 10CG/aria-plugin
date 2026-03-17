---
name: workflow-runner
description: |
  十步循环轻量编排器，协调 Phase Skills 执行，支持灵活组合。

  使用场景："执行 quick-fix 工作流"、"运行 [Phase B, Phase C]"、自定义 Phase 组合
argument-hint: "[workflow-name]"
disable-model-invocation: true
user-invocable: true
allowed-tools: Task, Read, Write, Glob, Grep
---

# Workflow Runner v2.2 (轻量编排器)

> **版本**: 2.2.0 | **架构**: Phase-Based
> **类型**: 编排器 (调用 Phase Skills)
> **更新**: 2026-02-05 - 添加 A.0.5 头脑风暴步骤集成

## 快速开始

### 我应该使用这个 Skill 吗？

**使用场景**:
- 接收 state-scanner 的工作流推荐
- 需要执行多个 Phase 的组合工作流
- 使用预置工作流模板

**不使用场景**:
- 只需执行单个 Phase → 直接使用对应 Phase Skill
- 需要状态感知和推荐 → 先使用 state-scanner
- 探索性开发 → 逐步手动调用

### 入口选择

```
用户任务
    │
    ├─ 需要状态感知/推荐? ──Yes──▶ state-scanner ──▶ workflow-runner
    │
    └─ 已知要执行的工作流? ──Yes──▶ workflow-runner (直接)
```

---

## 架构概览

### v2.0 vs v1.0

| 特性 | v1.0 | v2.0 |
|------|------|------|
| 执行单元 | 单步骤 (A.1, B.2...) | Phase (A, B, C, D) |
| 跳过逻辑 | 集中在 workflow-runner | 委托给各 Phase Skill |
| 上下文 | 手动传递 | 自动传递 context_for_next |
| 组合方式 | 步骤列表 | Phase 组合 |
| 复杂度 | 高 (管理10步) | 低 (管理4个Phase) |

### Phase Skills 架构

```
workflow-runner (编排器)
     │
     ├──▶ A.0.5 brainstorm (可选) ← 新增
     │         └── problem/requirements/technical 模式
     │
     ├──▶ phase-a-planner (A.1-A.3)
     │         └── spec-drafter (内置 brainstorm), task-planner
     │
     ├──▶ phase-b-developer (B.1-B.3)
     │         └── branch-manager, test-verifier, arch-update
     │
     ├──▶ phase-c-integrator (C.1-C.2)
     │         └── commit-msg-generator, branch-manager
     │
     └──▶ phase-d-closer (D.1-D.2)
               └── progress-updater, openspec:archive
```

---

## 预置工作流

| 工作流 | Phases | 适用场景 |
|--------|--------|---------|
| `quick-fix` | B → C | 简单 Bug 修复 |
| `feature-dev` | A → B → C | 功能开发 |
| `doc-update` | B.3 → C | 文档更新 |
| `full-cycle` | A → B → C → D | 完整开发周期 |
| `commit-only` | C.1 | 仅提交 |

详见 [WORKFLOWS.md](./WORKFLOWS.md)

---

## 执行流程

### 输入格式

```yaml
# 预置工作流
workflow: quick-fix

# 或 Phase 组合
phases: [B, C]

# 或自定义步骤
steps: [B.2, C.1]

# 可选配置
config:
  dry_run: false
  context:
    module: "mobile"
    spec_id: "add-auth-feature"
```

### 执行过程

```yaml
1. 解析工作流:
   - 预置模板 → 转换为 Phase 列表
   - Phase 组合 → 直接使用
   - 步骤列表 → 映射到 Phase

2. 上下文准备:
   - 接收 state-scanner 传递的上下文
   - 或读取当前项目状态

3. A.0.5 头脑风暴检查 (v2.2.0 新增):
   - 检测工作流包含 Phase A
   - 检查 state-scanner 推荐中是否包含 brainstorm 模式
   - 如果推荐 → 在 Phase A 前执行 brainstorm
   - 传递决策记录到 spec-drafter

4. Pre-Hook 检查 (v2.1.0):
   - 检测是否包含 Phase B
   - 如果包含 → 启用 TDD 主会话 Hook (方案 B)
   - 记录 tdd_session_id

5. Phase 顺序执行:
   - 调用对应 Phase Skill
   - 传递 context_for_next 到下一 Phase
   - 收集执行结果
   - 每个 Phase 完成后更新 workflow state (见 Workflow State Persistence)
   - 如启用 auto-proceed 模式，Phase 完成后自动推进到下一 Phase (Gate 暂停除外)。详见 [references/auto-proceed.md](./references/auto-proceed.md)

6. Post-Hook 清理 (v2.1.0):
   - 检测 Phase B 完成
   - 可选: 保持或关闭 TDD Hook

7. 结果汇总:
   - 生成执行报告
   - 返回最终状态
```

---

## 上下文传递

### 自动传递机制

```yaml
Phase A 输出:
  context_for_next:
    spec_id: "add-auth-feature"
    task_list: [TASK-001, ...]
    assigned_agents: {...}
           │
           ▼
Phase B 接收 + 输出:
  context_for_next:
    branch_name: "feature/add-auth"
    test_results: { passed: true, coverage: 87.5 }
           │
           ▼
Phase C 接收 + 输出:
  context_for_next:
    commit_sha: "abc1234"
    pr_url: "https://..."
           │
           ▼
Phase D 接收:
  # 使用所有上下文完成收尾
```

### 上下文合并

```yaml
context_merge:
  strategy: deep_merge
  priority: later_wins  # 后续 Phase 输出覆盖前面的
```

---

## Workflow State Persistence

工作流执行期间，通过 `.aria/workflow-state.json` 跟踪状态，支持中断恢复和进度可视化。

Schema 详见 [references/workflow-state-schema.md](./references/workflow-state-schema.md)

### State Creation

工作流启动时，创建初始状态文件:

1. 确保 `.aria/` 目录存在 (`mkdir -p .aria`)
2. 生成 `session_id` (格式: `sess-YYYYMMDD-XXXXXX`，X 为随机十六进制)
3. 写入初始状态:
   - `session.workflow_name`: 当前工作流名称
   - `session.phases`: 计划执行的 Phase 列表
   - `session.status`: `"running"`
   - `git_context.branch`, `git_context.start_commit`: 当前分支和 HEAD SHA
4. **原子写入**: 先写到 `.aria/workflow-state.json.tmp`，再 `rename` 覆盖正式文件

### State Updates

每个 Phase 完成后立即更新:

- `execution.current_phase` / `current_step`: 推进到下一 Phase
- `execution.phase_results.<phase>`: 记录该 Phase 输出 (status, context_for_next)
- `session.last_active_at`: 更新为当前时间戳
- `integrity.state_hash`: 重新计算 (SHA-256 of content without integrity block)

### Gate State

通过质量门时记录:

- **Gate 1** (Spec 审批): 设置 `gates.gate1_spec_approved: true`
- **Gate 2** (合并主干): 设置 `gates.gate2_merge_main: true`

Gate 强制执行逻辑、手动/自动模式切换、失败恢复详见 [references/gate-enforcement.md](./references/gate-enforcement.md)

### State Cleanup

工作流结束时的清理策略:

| 场景 | 动作 |
|------|------|
| 正常完成 | 删除 `.aria/workflow-state.json` |
| 用户放弃 | 删除 `.aria/workflow-state.json` |
| 执行失败 | 保留文件，设置 `session.status: "failed"` (供恢复使用) |

---

## 错误处理

### Phase 级别

```yaml
on_phase_error:
  action: stop          # stop | continue | rollback
  report: true
  suggestion: "查看 Phase X 错误详情"
```

### 可恢复策略

```yaml
recovery:
  Phase_B_failed:
    - 保留已创建的分支
    - 报告测试失败详情
    - 建议: "修复测试后从 Phase B 重新开始"

  Phase_C_failed:
    - 回滚 git commit (如果已执行)
    - 建议: "检查提交消息或 hook 错误"
```

---

## 输出格式

执行报告示例:

```
╔══════════════════════════════════════════════════════════════╗
║              WORKFLOW EXECUTION REPORT                        ║
╚══════════════════════════════════════════════════════════════╝

Workflow: feature-dev
Duration: 2m 15s
Status: SUCCESS

───────────────────────────────────────────────────────────────
PHASE RESULTS:

  Phase A (规划) - 45s
     spec_id: add-auth-feature
     tasks: 5

  Phase B (开发) - 60s
     branch: feature/add-auth
     tests: 15/15 passed (87.5% coverage)

  Phase C (集成) - 30s
     commit: abc1234
     pr: #123
───────────────────────────────────────────────────────────────
```

完整输出格式（含执行计划、使用示例等）详见 [references/output-formats.md](./references/output-formats.md)

---

## TDD 双保险 Pre-Hook (v2.1.0)

Phase B 执行时应用 TDD pre-hook 策略，在工作流级别自动启用 TDD 双保险机制：
- **方案 A**: phase-b-developer 传递 TDD 配置给 Fresh Subagent
- **方案 B**: workflow-runner 通过 Pre-Hook 启用主会话 TDD Hook

详见 [references/tdd-pre-hook.md](./references/tdd-pre-hook.md)

---

## 与 state-scanner 的协作

### 推荐流程

```
state-scanner
    │
    │ 收集状态 + 分析 + 推荐
    │
    ▼
recommendation:
  workflow: quick-fix
  context:
    phase_cycle: "Phase4-Cycle9"
    module: "mobile"
    changed_files: [...]
    │
    │ 用户确认
    │
    ▼
workflow-runner
    │
    │ 执行工作流
    │
    ▼
result
```

### 上下文继承

```yaml
# state-scanner 传递
context:
  phase_cycle: "Phase4-Cycle9"
  module: "mobile"
  changed_files: [...]

# workflow-runner 使用
→ 传递给 Phase A/B/C/D
→ 用于生成提交消息
→ 更新 UPM 进度
```

---

## 相关文档

- [WORKFLOWS.md](./WORKFLOWS.md) - 工作流详细定义
- [MIGRATION.md](./MIGRATION.md) - v1.0 → v2.0 迁移指南
- [references/tdd-pre-hook.md](./references/tdd-pre-hook.md) - TDD 双保险详细策略
- [references/output-formats.md](./references/output-formats.md) - 完整输出格式定义
- [references/workflow-state-schema.md](./references/workflow-state-schema.md) - 工作流状态 Schema
- [references/auto-proceed.md](./references/auto-proceed.md) - Auto-Proceed 模式规范
- [references/gate-enforcement.md](./references/gate-enforcement.md) - Gate 强制执行、手动回退、失败恢复
- [brainstorm](../brainstorm/SKILL.md) - 头脑风暴引擎 (新增 A.0.5)
- [state-scanner](../state-scanner/SKILL.md) - 状态感知与推荐
- [phase-a-planner](../phase-a-planner/SKILL.md) - Phase A
- [phase-b-developer](../phase-b-developer/SKILL.md) - Phase B
- [phase-c-integrator](../phase-c-integrator/SKILL.md) - Phase C
- [phase-d-closer](../phase-d-closer/SKILL.md) - Phase D
- [tdd-enforcer](../tdd-enforcer/SKILL.md) - TDD 强制执行

---

**最后更新**: 2026-03-16
**Skill版本**: 2.3.0

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

6. Post-Hook 清理 (v2.1.0):
   - 检测 Phase B 完成
   - 可选: 保持或关闭 TDD Hook

7. 结果汇总:
   - 生成执行报告
   - 返回最终状态
```

---

## 工作流详情

### quick-fix (快速修复)

```yaml
phases: [B, C]
skip_in_B: [B.3]  # Phase B 内部跳过 B.3

触发: "快速修复 Bug", "运行 quick-fix"
适用: 简单 Bug 修复、typo、配置调整
```

### feature-dev (功能开发)

```yaml
phases: [A, B, C]
skip_in_A: [A.1]  # 如果已有 OpenSpec
with_brainstorm: true  # 可选: 如 state-scanner 推荐

触发: "开发新功能", "运行 feature-dev"
适用: 新功能、中等规模开发

包含 A.0.5 (可选):
  - 如果 state-scanner 推荐包含 brainstorm
  - 在 Phase A 前执行头脑风暴
  - 传递决策记录到 spec-drafter
```

### doc-update (文档更新)

```yaml
steps: [B.3, C.1]  # 直接指定步骤

触发: "更新文档", "运行 doc-update"
适用: 架构文档、README 更新
```

### full-cycle (完整循环)

```yaml
phases: [A, B, C, D]

触发: "完整开发流程", "运行 full-cycle"
适用: 重大功能、版本发布
```

### commit-only (仅提交)

```yaml
steps: [C.1]

触发: state-scanner 检测已暂存变更
适用: 变更已就绪，只需提交
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

### 执行计划

```
╔══════════════════════════════════════════════════════════════╗
║              WORKFLOW EXECUTION PLAN                          ║
╚══════════════════════════════════════════════════════════════╝

Workflow: feature-dev
Phases: A → B → C

───────────────────────────────────────────────────────────────
💡 A.0.5 brainstorm (可选) ← 新增
   problem 模式            → 问题空间探索
   requirements 模式       → 需求分解
   technical 模式          → 技术方案设计

📋 Phase A (规划)
   A.1 spec-drafter      → Spec 管理 (基于决策预填充)
   A.2 task-planner      → 任务规划
   A.3 task-planner      → Agent 分配

🔨 Phase B (开发)
   B.1 branch-manager    → 分支创建
   B.2 test-verifier     → 测试验证
   B.3 arch-update       → 架构同步 (跳过)

📦 Phase C (集成)
   C.1 commit-msg-gen    → Git 提交
   C.2 branch-manager    → PR 创建
───────────────────────────────────────────────────────────────

🤔 Execute this workflow? [Yes/No]
```

### 执行报告

```
╔══════════════════════════════════════════════════════════════╗
║              WORKFLOW EXECUTION REPORT                        ║
╚══════════════════════════════════════════════════════════════╝

Workflow: feature-dev
Duration: 2m 15s
Status: ✅ SUCCESS

───────────────────────────────────────────────────────────────
PHASE RESULTS:

  ✅ Phase A (规划) - 45s
     spec_id: add-auth-feature
     tasks: 5

  ✅ Phase B (开发) - 60s
     branch: feature/add-auth
     tests: 15/15 passed (87.5% coverage)

  ✅ Phase C (集成) - 30s
     commit: abc1234
     pr: #123
───────────────────────────────────────────────────────────────

🎉 Workflow completed successfully!
```

---

## 使用示例

### 示例 1: 接收推荐执行

```yaml
# state-scanner 推荐
recommendation:
  workflow: quick-fix
  reason: "检测到 3 个文件变更，类型为 bugfix"

# workflow-runner 执行
执行: Phase B → Phase C
结果: commit_sha: "abc1234"
```

### 示例 2: 自定义 Phase 组合

```yaml
输入:
  phases: [B, C]
  config:
    context:
      branch_name: "existing-branch"

执行:
  Phase B: 使用现有分支，运行测试
  Phase C: 提交代码
```

### 示例 3: 仅提交

```yaml
输入:
  workflow: commit-only

执行:
  Phase C: 仅执行 C.1 (commit-msg-generator)
```

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
- [brainstorm](../brainstorm/SKILL.md) - 头脑风暴引擎 (新增 A.0.5)
- [state-scanner](../state-scanner/SKILL.md) - 状态感知与推荐
- [phase-a-planner](../phase-a-planner/SKILL.md) - Phase A
- [phase-b-developer](../phase-b-developer/SKILL.md) - Phase B
- [phase-c-integrator](../phase-c-integrator/SKILL.md) - Phase C
- [phase-d-closer](../phase-d-closer/SKILL.md) - Phase D
- [tdd-enforcer](../tdd-enforcer/SKILL.md) - TDD 强制执行

---

## TDD 双保险 Pre-Hook (v2.1.0 新增)

> **设计目标**: 在工作流级别自动启用 TDD，保护主会话的代码编写

### 方案 B 实现

workflow-runner 是 TDD 双保险中"方案 B"的实现者：

```yaml
workflow-runner (方案 B)
    │
    ├── 检测工作流包含 Phase B
    ├── Pre-Hook: 调用 tdd-enforcer
    │   ├── 启用主会话 TDD Hook
    │   └── 返回 tdd_session_id
    │
    ├──▶ phase-b-developer (方案 A)
    │       └── 传递 TDD 给 subagent-driver
    │           └── 保护 Fresh Subagent
    │
    └── Post-Hook: 可选关闭 TDD Hook
```

### Pre-Hook 触发条件

```yaml
触发条件:
  - 工作流包含 Phase B
  - phase_b_config.tdd.session_level.enabled = true
  - 项目未禁用 TDD (.claude/tdd-config.json)

不触发场景:
  - 工作流不包含 Phase B (如 commit-only)
  - 项目级配置禁用 TDD
  - 文档类工作流 (doc-update)
```

### Pre-Hook 执行流程

```yaml
Pre-Hook 执行:
  1. 检测工作流:
     - 解析 phases 列表
     - 检查是否包含 "B" 或 "phase-b-developer"

  2. 读取 TDD 配置:
     - 读取 .claude/tdd-config.json (如果存在)
     - 或使用 phase_b_config.tdd.session_level

  3. 启用 TDD Hook:
     - 调用 tdd-enforcer skill
     - 传递 strict_mode 和 skip_patterns
     - 获取 tdd_session_id

  4. 记录状态:
     - 保存 tdd_session_id 到上下文
     - 传递给 phase-b-developer
```

### Post-Hook 清理

```yaml
Post-Hook 执行:
  1. 检测 Phase B 完成:
     - phase-b-developer 返回成功状态

  2. 决策 TDD Hook 去留:
     - 默认: 关闭 Hook (释放资源)
     - 可选: 保持 Hook (连续开发场景)

  3. 清理或保持:
     - 关闭: 调用 tdd-enforcer --disable
     - 保持: 记录 tdd_session_id 供后续使用
```

### 配置示例

```yaml
# workflow-runner 输入
workflow: feature-dev
phases: [A, B, C]

config:
  tdd:
    session_level:            # 方案 B 配置
      enabled: true
      strict_mode: false
      skip_patterns:
        - "**/*.md"
        - "**/*.json"
    persist_after_phase_b: false  # Phase B 后是否保持
```

### 执行报告增强

```yaml
执行报告 (v2.1.0):

╔══════════════════════════════════════════════════════════════╗
║              WORKFLOW EXECUTION REPORT                        ║
╚══════════════════════════════════════════════════════════════╝

Workflow: feature-dev
Duration: 3m 45s
Status: ✅ SUCCESS

───────────────────────────────────────────────────────────────
🔒 TDD 双保险状态:
  方案 A (Fresh Subagent): ✅ 启用
  方案 B (主会话):        ✅ 启用
  tdd_session_id: sess-20260122-001

───────────────────────────────────────────────────────────────
PHASE RESULTS:

  ✅ Phase A (规划) - 45s
     spec_id: add-auth-feature
     tasks: 5

  ✅ Phase B (开发) - 120s
     branch: feature/add-auth
     tests: 15/15 passed (87.5% coverage)
     tdd_compliance: passed

  ✅ Phase C (集成) - 30s
     commit: abc1234
     pr: #123
───────────────────────────────────────────────────────────────

🎉 Workflow completed successfully!
```

### 双保险协作

```yaml
完整保护流程:

  [用户] "开发新功能"
     │
     ▼
  state-scanner
     │ 推荐工作流: feature-dev (A→B→C)
     ▼
  workflow-runner
     │
     ├── [Pre-Hook] 方案 B: 启用主会话 TDD
     │   └── tdd-enforcer --enable
     │
     ▼
  phase-a-planner (规划)
     │
     ▼
  phase-b-developer (开发)
     │
     ├── 方案 A: 传递 TDD 配置
     │   └── subagent-driver (tdd_config)
     │       └── Fresh Subagent (TDD 约束)
     │
     └── 用户直接编辑 ← 方案 B 保护
         └── tdd-enforcer Hook 拦截
     │
     ▼
  phase-c-integrator (集成)
     │
     ├── [Post-Hook] 可选关闭 TDD
     │   └── tdd-enforcer --disable
     │
     ▼
  完成
```

---

**最后更新**: 2026-02-05
**Skill版本**: 2.2.0 (新增 A.0.5 brainstorm 步骤)

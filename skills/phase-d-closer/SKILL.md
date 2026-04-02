---
name: phase-d-closer
description: |
  十步循环 Phase D - 收尾阶段执行器，编排 D.1-D.2 步骤。

  使用场景："执行收尾阶段"、"Phase D"、"更新进度并归档 Spec"
disable-model-invocation: false
user-invocable: true
allowed-tools: Read, Write, Glob, Grep, Bash, Task
---

# Phase D - 收尾阶段 (Closer)

> **版本**: 1.0.0 | **十步循环**: D.1-D.2

## 快速开始

### 我应该使用这个 Skill 吗？

**使用场景**:
- 需要更新 UPM 进度状态
- 需要归档完成的 OpenSpec
- 功能开发完成后的收尾阶段
- 里程碑完成时的状态同步

**不使用场景**:
- 无 UPM 配置 → 跳过 D.1
- 无活跃 OpenSpec → 跳过 D.2
- 快速修复 (Level 1) → 通常跳过整个 Phase D

---

## 核心功能

| 步骤 | Skill | 职责 | 输出 |
|------|-------|------|------|
| D.1 | progress-updater | 进度更新 | upm_updated |
| D.2 | openspec-archive | Spec 归档 (自动修正 CLI bug) | spec_archived |

---

## 执行流程

### 输入

```yaml
context:
  phase_cycle: "Phase4-Cycle9"
  module: "mobile"
  spec_id: "add-auth-feature"         # 来自 Phase A
  commit_sha: "abc1234"               # 来自 Phase C
  pr_url: "https://..."               # 来自 Phase C

config:
  skip_steps: []
  params:
    update_kpi: true
    archive_spec: true
```

### 步骤执行

```yaml
D.1 - 进度更新:
  skill: progress-updater
  skip_if:
    - no_upm: true                    # 模块无 UPM 配置
  action:
    - 读取当前 UPMv2-STATE
    - 更新 Cycle 进度
    - 写入新的状态
  output:
    upm_updated: true
    new_state:
      cycle: 10
      completed_tasks: [TASK-001, ...]

D.post - post_closure 审计检查点 (新增):
  checkpoint: post_closure
  trigger: D.1 完成后、D.2 归档前
  condition: audit.enabled == true
             AND audit.checkpoints.post_closure != "off"
  限制: 仅使用 convergence 模式 + max_rounds=1 (侧重经验提取，非质量阻塞)

  步骤:
    1. 检查触发条件 (audit.enabled + checkpoint enabled)
    2. 如启用: 调用 audit-engine
       - checkpoint: "post_closure"
       - mode: "convergence"  # 强制 convergence，忽略全局 mode 配置
       - max_rounds: 1        # 强制单轮，忽略全局 max_rounds 配置
       - context: 本次交付的 UPM 路径 (经验积累上下文)
    3. 不阻塞: 无论 verdict 结果如何，均继续执行 D.2
       (代码已合并，此检查点仅做经验提取，不做质量门禁)

  on_fail: 记录审计报告但不阻塞，继续 D.2
  on_skip: 直接进入 D.2

D.2 - Spec 归档:
  skill: openspec-archive
  skip_if:
    - no_openspec: true               # 无活跃 Spec
    - spec_not_complete: true         # Spec 未完成
  action:
    - 验证所有任务完成
    - 移动 Spec 到 archive/
    - 更新 Spec 状态
  output:
    spec_archived: true
    archive_path: "openspec/archive/add-auth-feature/"
```

### 输出

```yaml
success: true
steps_executed: [D.1, D.2]
steps_skipped: []
results:
  D.1:
    upm_updated: true
    new_cycle: 10
  D.2:
    spec_archived: true
    archive_path: "..."

context_for_next: null  # Phase D 是最后阶段
```

---

## 跳过规则

| 条件 | 跳过步骤 | 检测方法 |
|------|---------|----------|
| 无 UPM | D.1 | UPM 文档不存在 |
| 无 OpenSpec | D.2 | openspec/changes/ 为空 |
| Spec 未完成 | D.2 | tasks.md 有未完成项 |

### 跳过逻辑

```yaml
skip_evaluation:
  D.1:
    - check: UPM file exists
      paths:
        - mobile/docs/project-planning/unified-progress-management.md
        - backend/project-planning/unified-progress-management.md
      skip_if: not exists
      reason: "模块无 UPM 配置"

  D.2:
    - check: active OpenSpec
      command: "ls openspec/changes/"
      skip_if: empty
      reason: "无活跃 OpenSpec"

    - check: tasks completion
      file: "openspec/changes/{spec_id}/tasks.md"
      skip_if: has uncompleted tasks
      reason: "Spec 任务未全部完成"
```

---

## 输出格式

```
╔══════════════════════════════════════════════════════════════╗
║              PHASE D - CLOSURE                               ║
╚══════════════════════════════════════════════════════════════╝

📋 执行计划
───────────────────────────────────────────────────────────────
  D.1 progress-updater   → 更新 UPM 进度
  D.2 openspec:archive   → 归档 Spec

🚀 执行中...
───────────────────────────────────────────────────────────────
  ✅ D.1 完成 → UPM 已更新
     Module: mobile
     Cycle: 9 → 10

  ✅ D.2 完成 → Spec 已归档
     Spec: add-auth-feature
     Archive: openspec/archive/add-auth-feature/

🎉 工作流完成
───────────────────────────────────────────────────────────────
  状态: 所有步骤成功
  总耗时: 45s
```

---

## 使用示例

### 示例 1: 完整收尾

```yaml
输入:
  context:
    module: "mobile"
    spec_id: "add-auth-feature"

执行:
  D.1: 更新 UPM → Cycle 10
  D.2: 归档 Spec → archive/

输出:
  upm_updated: true
  spec_archived: true
```

### 示例 2: 仅更新进度

```yaml
输入:
  context:
    spec_id: null  # 无关联 Spec

执行:
  D.1: 更新 UPM
  D.2: 跳过 (无 Spec)

输出:
  steps_skipped: [D.2]
  upm_updated: true
```

### 示例 3: 全部跳过

```yaml
输入:
  context:
    module: "shared"  # 无 UPM
    spec_id: null     # 无 Spec

执行:
  D.1: 跳过 (无 UPM)
  D.2: 跳过 (无 Spec)

输出:
  steps_skipped: [D.1, D.2]
  reason: "收尾阶段无需执行"
```

---

## 进度更新内容

### UPMv2-STATE 更新

```yaml
更新字段:
  - cycleNumber: +1 或保持
  - lastUpdateAt: 当前时间
  - stateToken: 重新计算
  - completedTasks: 添加已完成任务
  - kpiSnapshot: 更新覆盖率等指标
```

### Spec 归档

```yaml
归档操作:
  1. 验证 tasks.md 所有任务标记 [x]
  2. 更新 proposal.md 状态为 Complete
  3. 移动目录: changes/{id}/ → archive/{id}/
  4. 记录归档时间和提交信息
```

---

## 错误处理

| 错误 | 原因 | 处理 |
|------|------|------|
| UPM 更新失败 | 并发冲突 | 重新读取并合并 |
| Spec 归档失败 | 任务未完成 | 列出未完成任务 |
| 状态写入失败 | 文件权限 | 提示检查权限 |

### 并发冲突处理

```yaml
on_upm_conflict:
  action: retry
  max_retries: 3
  strategy:
    1. 重新读取 UPMv2-STATE
    2. 合并变更
    3. 重新计算 stateToken
    4. 再次尝试写入
```

---

## 与其他 Phase 的关系

```
phase-c-integrator
    │
    │ context:
    │   - commit_sha
    │   - pr_url
    ▼
phase-d-closer (本 Skill)
    │
    │ 工作流结束
    ▼
  (完成)
```

---

## 相关文档

- [progress-updater](../progress-updater/SKILL.md) - D.1 进度更新
- [openspec:archive](../../commands/openspec/archive.md) - D.2 Spec 归档
- [phase-c-integrator](../phase-c-integrator/SKILL.md) - 上一阶段
- [UPM 规范](../../../standards/core/upm/unified-progress-management-spec.md)

---

**最后更新**: 2025-12-25
**Skill版本**: 1.0.0

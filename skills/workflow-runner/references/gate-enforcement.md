# Gate Enforcement, Manual Fallback & Failure Recovery

> **Version**: 1.0 | **Tasks**: 2.4, 2.5, 2.6, 2.7
> **Parent**: [workflow-runner SKILL.md](../SKILL.md)
> **Related**: [workflow-state-schema.md](./workflow-state-schema.md)
> **Created**: 2026-03-16

本文档定义了 workflow-runner 的质量门 (Gate) 强制执行机制、手动/自动模式切换、以及 auto-proceed 期间的失败恢复策略。

---

## 1. Gate 1: Spec Approval (Task 2.4)

Phase A 完成后、进入 Phase B 之前，必须验证 OpenSpec proposal 已获批准。

### 检测机制

```yaml
检测机制:
  1. 读取 openspec/changes/{spec_id}/proposal.md
  2. 解析 Status 字段 (在 YAML-like 元数据头部)
  3. 如果 Status != "Approved" → 暂停并通知用户:
     "⏸️ Gate 1: Spec 尚未审批 (当前: {status})"
     "请将 proposal.md 的 Status 改为 Approved 后继续"
  4. 如果 Status == "Approved" → 设置 gates.gate1_spec_approved = true → 继续
```

### 执行流程

```
Phase A 完成
    │
    ▼
读取 openspec/changes/{spec_id}/proposal.md
    │
    ├─ Status == "Approved"
    │       │
    │       ▼
    │   gates.gate1_spec_approved = true
    │   持久化到 workflow-state.json
    │   继续执行 Phase B
    │
    └─ Status != "Approved"
            │
            ▼
        暂停工作流 (session.status = "suspended")
        通知用户:
          "⏸️ Gate 1: Spec 尚未审批 (当前: {status})"
          "请将 proposal.md 的 Status 改为 Approved 后继续"
        等待用户确认后重新检测
```

### 特殊情况

| 场景 | 行为 |
|------|------|
| 工作流跳过 Phase A (如 `quick-fix`) | `gate1_spec_approved` 初始化为 `true`，不做检测 |
| `spec_id` 为 `null` | 跳过 Gate 1 检测，视为已通过 |
| `proposal.md` 文件不存在 | 视为 Status 未批准，暂停并通知用户 |
| `auto_proceed` 为 `true` | Gate 1 仍然强制暂停 (质量门优先于 auto-proceed) |

### Status 字段解析

在 `proposal.md` 文件的元数据头部 (YAML front matter 或 key-value 格式) 中查找:

```markdown
Status: Approved       ← 通过
Status: Draft          ← 未通过
Status: In Review      ← 未通过
Status: Rejected       ← 未通过
```

匹配规则: 精确匹配 `Approved` (不区分大小写)。任何其他值均视为未通过。

---

## 2. Gate 2: Merge to Main (Task 2.5)

Phase C 步骤 C.2 (merge) 执行前，如果目标分支是 `main` 或 `master`，必须获得人工确认。

### 检测机制

```yaml
检测机制:
  1. 检查当前 merge/PR 的目标分支
  2. 如果目标是 main 或 master → 强制交互暂停:
     "⏸️ Gate 2: Merge to main 需要人工确认"
     "目标分支: main"
     "变更摘要: {change_summary}"
     "[确认合并] [取消]"
  3. 无论 auto_proceed 设置如何，Gate 2 永远不能自动通过
  4. 用户确认后 → 设置 gates.gate2_merge_main = true → 继续
  5. 如果目标非 main/master → 自动通过，不暂停
```

### 执行流程

```
Phase C 步骤 C.2 (Merge)
    │
    ▼
检查目标分支
    │
    ├─ 目标 == main 或 master
    │       │
    │       ▼
    │   强制交互暂停 (无论 auto_proceed 设置):
    │     "⏸️ Gate 2: Merge to main 需要人工确认"
    │     "目标分支: {target_branch}"
    │     "变更摘要: {change_summary}"
    │     "[确认合并] [取消]"
    │       │
    │       ├─ 用户确认 → gates.gate2_merge_main = true → 执行合并
    │       └─ 用户取消 → 暂停工作流，不执行合并
    │
    └─ 目标 != main/master
            │
            ▼
        gates.gate2_merge_main = true (自动通过)
        继续执行合并
```

### 核心规则

**Gate 2 永远不能自动通过 (当目标是 main/master 时)。**

这是一个硬性安全约束:

- `auto_proceed = true` → Gate 2 仍然暂停
- `auto_proceed = false` → Gate 2 仍然暂停
- 任何配置或环境变量都不能绕过此检查

### 变更摘要生成

Gate 2 暂停时展示的 `change_summary` 内容:

```yaml
change_summary 包含:
  - 涉及的文件数量
  - 新增/修改/删除统计
  - 提交数量
  - 关联的 spec_id (如果有)
  - 关键变更的简要描述 (从 commit messages 提取)
```

---

## 3. Manual Mode Fallback (Task 2.6)

用户可以在工作流执行期间随时切换 auto-proceed 模式。

### 切换机制

```yaml
用户可随时切换:
  - 输入 "manual mode" 或 "手动模式" → auto_proceed 设为 false
  - 输入 "auto mode" 或 "自动模式" → auto_proceed 设为 true
  - 切换立即生效，不影响当前 Phase 执行
  - 切换记录到 workflow-state.json
```

### 切换流程

```
工作流执行中
    │
    ├─ 用户输入 "manual mode" 或 "手动模式"
    │       │
    │       ▼
    │   workflow.auto_proceed = false
    │   持久化到 workflow-state.json
    │   通知: "已切换到手动模式。每个 Phase 完成后将等待确认。"
    │   当前 Phase 继续执行 (不中断)
    │   下一个 Phase 转换时暂停等待确认
    │
    └─ 用户输入 "auto mode" 或 "自动模式"
            │
            ▼
        workflow.auto_proceed = true
        持久化到 workflow-state.json
        通知: "已切换到自动模式。Phase 完成后将自动继续。"
        当前 Phase 继续执行 (不中断)
        下一个 Phase 转换时自动继续 (除非遇到 Gate)
```

### 触发词识别

| 输入 | 效果 |
|------|------|
| `manual mode` | `auto_proceed = false` |
| `手动模式` | `auto_proceed = false` |
| `auto mode` | `auto_proceed = true` |
| `自动模式` | `auto_proceed = true` |

识别规则:
- 不区分大小写 (`Manual Mode` = `manual mode`)
- 可以出现在用户消息的任意位置
- 如果用户消息同时包含两种指令，以最后出现的为准

### 模式切换与 Gate 的交互

```
auto_proceed = true + Gate 未通过  → 暂停 (Gate 优先)
auto_proceed = true + Gate 已通过  → 自动继续
auto_proceed = false + Gate 未通过 → 暂停 (两者都要求暂停)
auto_proceed = false + Gate 已通过 → 暂停 (手动模式要求确认)
```

**结论**: Gate 和手动模式是独立的暂停机制，任一要求暂停则暂停。

### State 记录

切换时更新 `workflow-state.json`:

```json
{
  "workflow": {
    "auto_proceed": false
  }
}
```

每次切换同时更新 `session.last_active_at` 和 `integrity.state_hash`。

---

## 4. Failure Recovery (Task 2.7)

Auto-proceed 期间 Phase 执行失败时的自动恢复机制。

### 恢复机制

```yaml
Auto-proceed 期间 Phase 失败时:
  1. 持久化失败状态到 workflow-state.json:
     - session.status = "failed"
     - 记录失败的 Phase 和错误信息
  2. 自动回退到手动模式 (auto_proceed = false)
  3. 展示恢复上下文:
     "❌ Phase {phase} 执行失败"
     "错误: {error_summary}"
     "已自动切换到手动模式"
     "[重试当前 Phase] [跳过] [放弃工作流]"
  4. 等待用户决策后继续
```

### 失败处理流程

```
Phase 执行失败
    │
    ▼
1. 持久化失败状态
    │  session.status = "failed"
    │  phase_results.{phase}.status = "failed"
    │  phase_results.{phase}.error = "{error_description}"
    │  workflow.auto_proceed = false  ← 自动回退到手动模式
    │  session.last_active_at = now()
    │  重新计算 integrity.state_hash
    │  原子写入 workflow-state.json
    │
    ▼
2. 展示恢复上下文
    │  "❌ Phase {phase} 执行失败"
    │  "错误: {error_summary}"
    │  "已自动切换到手动模式"
    │
    ▼
3. 提供恢复选项
    │  [重试当前 Phase] [跳过] [放弃工作流]
    │
    ├─ 重试当前 Phase
    │       │
    │       ▼
    │   phase_results.{phase}.status = "pending"
    │   phase_results.{phase}.error = null
    │   session.status = "in_progress"
    │   workflow.current_phase = {failed_phase}
    │   持久化 → 重新执行该 Phase
    │
    ├─ 跳过
    │       │
    │       ▼
    │   phase_results.{phase}.status = "skipped"
    │   session.status = "in_progress"
    │   workflow.current_phase = {next_phase}
    │   持久化 → 继续下一个 Phase
    │   (注意: 跳过的 Phase 不产生 context_for_next)
    │
    └─ 放弃工作流
            │
            ▼
        session.status = "failed" (保持)
        删除 .aria/workflow-state.json
        通知: "工作流已放弃。分支和已有变更保留不动。"
```

### 失败状态示例

Phase B 执行失败后的 `workflow-state.json` 片段:

```json
{
  "session": {
    "id": "sess-20260316-a3f7c1",
    "status": "failed",
    "last_active_at": "2026-03-16T10:15:30+08:00"
  },
  "workflow": {
    "current_phase": "B",
    "current_step": "B.2",
    "auto_proceed": false
  },
  "phase_results": {
    "A": {
      "status": "completed",
      "output": { "spec_id": "add-auth-feature", "task_count": 3 },
      "error": null
    },
    "B": {
      "status": "failed",
      "started_at": "2026-03-16T10:05:35+08:00",
      "completed_at": null,
      "output": { "branch_name": "feature/add-auth" },
      "error": "Test suite failed: 3/15 tests failed (auth_middleware_test.js)"
    }
  }
}
```

### 自动回退的原因

在 auto-proceed 模式下失败时自动回退到手动模式，原因:

1. **安全性**: 失败表明存在预期外的问题，继续自动执行可能导致连锁失败
2. **上下文丢失**: 失败的 Phase 未产生完整的 `context_for_next`，后续 Phase 缺少输入
3. **人工判断**: 用户需要评估是重试、跳过还是放弃，这是不可自动化的决策

### 恢复后的模式

用户选择"重试"或"跳过"后:
- `auto_proceed` 保持 `false` (手动模式)
- 用户可以随时输入 `auto mode` 重新启用自动模式
- 这确保用户在问题解决后有意识地选择是否恢复自动执行

---

## 5. Gate 与 Auto-Proceed 的优先级总结

```
┌────────────────────────────────────────────────────────────────┐
│                    Phase 转换决策矩阵                          │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  优先级 (从高到低):                                            │
│                                                                │
│  1. Gate 2 (Merge to main)    → 永远暂停 (不可覆盖)           │
│  2. Gate 1 (Spec Approval)    → 暂停直到 Approved              │
│  3. Failure Recovery          → 暂停 + 回退到手动模式          │
│  4. Manual Mode               → 每个 Phase 后暂停              │
│  5. Auto-Proceed              → 自动继续                       │
│                                                                │
│  规则: 任何高优先级条件触发暂停，低优先级的自动继续无效        │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

---

**Created**: 2026-03-16
**Version**: 1.0
**Referenced by**: [workflow-runner SKILL.md](../SKILL.md)

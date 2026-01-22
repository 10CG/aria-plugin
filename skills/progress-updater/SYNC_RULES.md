# 双层同步规则

> **版本**: 1.0.0
> **最后更新**: 2025-12-23
> **相关 Skill**: progress-updater

---

## 概述

双层同步规则定义了 `tasks.md` (粗粒度) 与 `detailed-tasks.yaml` (细粒度) 之间的同步机制，确保两层任务视图始终保持一致。

---

## 同步方向

```
┌────────────────────────┐    ┌─────────────────────────────────┐
│      tasks.md          │    │     detailed-tasks.yaml         │
│  (Human-readable)      │    │       (AI-executable)           │
├────────────────────────┤    ├─────────────────────────────────┤
│ - [ ] 1.1 Task A       │ ─▶ │ - id: TASK-001                  │
│ - [ ] 1.2 Task B       │    │   parent: "1.1"                 │
│ - [x] 2.1 Task C       │ ◀─ │   status: completed             │
└────────────────────────┘    └─────────────────────────────────┘
     Forward Sync (A.2)            Backward Sync (D.1)
```

| 方向 | 触发时机 | 执行者 |
|------|---------|--------|
| **前向同步** | A.2 任务规划 | task-planner |
| **后向同步** | D.1 进度更新 | progress-updater |

---

## 后向同步执行流程

### 触发条件

当 `detailed-tasks.yaml` 中任务状态变为 `completed` 时触发。

### 执行步骤

```yaml
步骤 1: 读取任务状态变化
  - 识别新完成的任务 (status: completed)
  - 获取任务的 parent 字段 (如 "1.1")

步骤 2: 定位 tasks.md 对应项
  - 解析 tasks.md 内容
  - 查找匹配 parent 编号的 checkbox 行
  - 格式: `- [ ] {parent} {description}`

步骤 3: 更新 checkbox 状态
  - 将 `- [ ]` 改为 `- [x]`
  - 保持其他内容不变

步骤 4: 验证同步结果
  - 确认更新成功
  - 检查格式完整性
```

### 同步示例

```yaml
# detailed-tasks.yaml 变化
- id: TASK-001
  parent: "1.1"
  status: completed        # pending → completed

# tasks.md 更新前
- [ ] 1.1 Update phase-a-spec-planning.md

# tasks.md 更新后
- [x] 1.1 Update phase-a-spec-planning.md
```

---

## 三类冲突检测

### Type 1: 进度不匹配 (Progress Mismatch)

```yaml
场景: tasks.md 与 detailed-tasks.yaml 进度不一致

检测方式:
  - 对比 tasks.md checkbox 状态
  - 对比 detailed-tasks.yaml 中 status 字段

示例:
  tasks.md:           - [x] 1.1 Task A  (显示完成)
  detailed-tasks.yaml: status: pending   (显示未完成)

处理策略:
  - 以 detailed-tasks.yaml 为准 (单一事实来源)
  - 回写修正 tasks.md 的 checkbox
  - 记录警告日志
```

### Type 2: Parent 引用失败 (Parent Reference Failure)

```yaml
场景: detailed-tasks.yaml 中的 parent 在 tasks.md 中找不到

检测方式:
  - 解析 tasks.md 提取所有编号
  - 验证每个 TASK 的 parent 是否存在

示例:
  detailed-tasks.yaml: parent: "1.3"
  tasks.md: 只有 1.1 和 1.2，无 1.3

处理策略:
  - 标记为配置错误
  - 跳过该任务的同步
  - 报告详细错误信息
  - 建议: 重新运行 task-planner (A.2)
```

### Type 3: 任务定义冲突 (Task Definition Conflict)

```yaml
场景: 同一 parent 的任务标题不匹配

检测方式:
  - 对比 detailed-tasks.yaml 的 title
  - 对比 tasks.md 中对应 checkbox 的描述
  - 计算相似度

示例:
  detailed-tasks.yaml:
    parent: "1.1"
    title: "Update architecture docs"

  tasks.md:
    - [ ] 1.1 Create new feature  (完全不同)

处理策略:
  相似度 > 80%:
    - 视为轻微修改，自动同步
    - 记录警告

  相似度 < 80%:
    - 中止同步操作
    - 报告冲突详情
    - 需要人工介入或使用 --force
```

---

## 冲突处理策略

### 策略 A: 自动修复 (推荐)

```yaml
适用条件:
  - Type 1 (进度不匹配)
  - Type 3 且相似度 > 80%

处理流程:
  1. 记录冲突详情
  2. 以 detailed-tasks.yaml 为准
  3. 自动更新 tasks.md
  4. 输出警告信息
```

### 策略 B: 中止并报告

```yaml
适用条件:
  - Type 2 (Parent 引用失败)
  - Type 3 且相似度 < 80%

处理流程:
  1. 中止同步操作
  2. 输出详细冲突报告
  3. 等待人工处理

冲突报告格式:
  ═══════════════════════════════════════════════════════════════
    ⚠️ SYNC CONFLICT DETECTED
  ═══════════════════════════════════════════════════════════════

  Conflict Type: Parent Reference Failure
  Task ID: TASK-003
  Parent: "1.3"

  Issue: Parent "1.3" not found in tasks.md

  Available parents in tasks.md:
    - 1.1 Update docs
    - 1.2 Add tests

  建议操作:
    1. 检查 tasks.md 编号是否正确
    2. 重新运行 task-planner (A.2)
    3. 或使用 --force 强制重新生成

  ═══════════════════════════════════════════════════════════════
```

### 策略 C: 强制重新生成

```yaml
触发条件: 使用 --force 参数

处理流程:
  1. 备份当前 detailed-tasks.yaml
  2. 从 tasks.md 重新生成
  3. 丢失任务元数据 (complexity, agent 等)
  4. 需要重新执行 A.2 和 A.3

警告: 此操作会丢失任务的详细配置信息
```

---

## 编号不可变约束

### 规则

一旦 tasks.md 编号确立，**禁止修改**。

### 正确做法

**添加新任务**:
```markdown
## 1. Architecture Documentation
- [x] 1.1 Update phase-a-spec-planning.md
- [x] 1.2 Define responsibilities
- [ ] 1.3 Add examples (NEW)           # 在末尾添加
```

**取消任务**:
```markdown
## 1. Architecture Documentation
- [x] 1.1 Update phase-a-spec-planning.md
- [ ] 1.2 Define responsibilities (CANCELLED)   # 保留编号
- [ ] 1.3 Add examples
```

### 错误做法

```markdown
# ❌ 不要重新编号
## 1. Architecture Documentation
- [x] 1.1 Add examples               # 原来是 1.3
- [x] 1.2 Update docs                # 原来是 1.1
```

---

## 最佳实践

### DO

```yaml
✅ 任务完成后立即触发后向同步
✅ 定期检查两层一致性
✅ 使用 parent 字段建立明确关联
✅ 保持 tasks.md 编号稳定
✅ 在 SKILL.md 中记录同步时间
```

### DON'T

```yaml
❌ 不要手动修改 tasks.md 编号
❌ 不要跳过冲突检测
❌ 不要在两层独立维护进度
❌ 不要忽略同步警告
```

---

## 相关文档

- [progress-updater SKILL.md](./SKILL.md)
- [stateToken 计算规范](./STATETOKEN_SPEC.md)
- [双层架构规范](../task-planner/DUAL_LAYER_SPEC.md)
- [Phase A: 规范与规划](../../../standards/core/ten-step-cycle/phase-a-spec-planning.md)

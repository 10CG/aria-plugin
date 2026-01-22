---
name: progress-updater
description: |
  更新项目进度状态，写入 UPM 文档的 UPMv2-STATE 机读区块。
  支持十步循环中的 D.1 (进度更新)。

  使用场景：
  - "更新项目进度"
  - "标记任务完成"
  - "更新 mobile 模块 KPI"
  - "写入周期进度报告"

  特性: 自动 stateToken 计算、并发冲突检测、周期文档生成
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

# 进度更新器 (Progress Updater)

> **版本**: 2.0.0 | **十步循环**: D.1
> **架构**: 双层任务架构支持 (tasks.md + detailed-tasks.yaml)

## 快速开始

### 我应该使用这个 Skill 吗？

**使用场景**:
- D.1: 任务完成后更新项目进度
- 需要更新 UPM 文档的 KPI 指标
- 需要标记任务为已完成
- 需要写入周期进度报告

**不使用场景**:
- 只需要查询进度 → 使用 `state-scanner` (A.0)
- 需要规划任务 → 使用 `task-planner` (A.2)
- 需要归档 Spec → 使用 `openspec:archive` (D.2)

---

## 核心功能

| 功能 | 描述 |
|------|------|
| UPM 状态更新 | 更新 UPMv2-STATE YAML 区块所有字段 |
| stateToken 自动计算 | 自动重新计算并更新 stateToken |
| 任务状态同步 | 标记任务完成，更新候选任务 |
| 周期文档写入 | 创建/更新 progress-report.md 等文档 |
| 并发冲突检测 | 通过 stateToken 校验防止覆盖 |
| 双层架构后向同步 | 自动同步 TASK 完成状态到 tasks.md checkbox |
| 三类冲突检测 | 检测 Progress Mismatch、Parent Reference、Task Definition 冲突 |

---

## 输入参数

| 参数 | 必需 | 说明 | 示例 |
|------|------|------|------|
| `module` | ✅ | 目标模块 | `mobile`, `backend` |
| `commit_ref` | ⚠️ 推荐 | Git 提交引用 | `git:abc1234-任务描述` |
| `completed_tasks` | ❌ | 已完成任务列表 | `["TASK-001", "TASK-002"]` |
| `kpi_updates` | ❌ | KPI 更新数据 | `{coverage: "89.5%"}` |
| `risks_updates` | ❌ | 风险状态更新 | `[{id: "R1", status: "resolved"}]` |
| `next_candidates` | ❌ | 下一循环候选 | `[{id: "TASK-003", rationale: "..."}]` |
| `cycle_doc` | ❌ | 是否写入周期文档 | `true`, `false` (默认) |
| `spec_path` | ❌ | OpenSpec 变更目录路径 | `changes/user-auth` |

---

## 执行流程

```yaml
D.1.1 - 读取当前状态:
  - 调用 state-scanner 获取当前状态
  - 记录当前 stateToken (用于冲突检测)

D.1.2 - 准备更新数据:
  - 生成新的 lastUpdateAt (ISO 8601)
  - 构建 lastUpdateRef
  - 合并 kpi_updates 到 kpiSnapshot
  - 更新 risks 和 nextCycle.candidates

D.1.3 - 计算新 stateToken:
  → 详见 [STATETOKEN_SPEC.md](./STATETOKEN_SPEC.md)

D.1.4 - 写入周期文档 (可选):
  - 路径: docs/project-lifecycle/week{N}/
  - 创建 progress-report.md / quality-review.md

D.1.5 - 回写 UPM 文档:
  - 校验 stateToken 未被修改
  - 更新 UPMv2-STATE YAML 区块

D.1.6 - 双层架构后向同步 (可选):
  → 详见 [SYNC_RULES.md](./SYNC_RULES.md)
  - 如果提供了 spec_path
  - 执行三类冲突检测
  - 更新 tasks.md checkbox 状态
```

---

## UPM 路径规则

| 模块 | UPM 路径 |
|------|----------|
| `mobile` | `mobile/docs/project-planning/unified-progress-management.md` |
| `backend` | `backend/project-planning/unified-progress-management.md` |
| `shared` | `shared/project-planning/unified-progress-management.md` |
| `standards` | `standards/project-planning/unified-progress-management.md` |

---

## stateToken 计算

**完整算法**: [STATETOKEN_SPEC.md](./STATETOKEN_SPEC.md)

### 快速参考

```yaml
输入字段: module|stage|cycleNumber|lastUpdateAt|kpiSnapshot
算法: SHA256 → 取前 12 位
格式: "sha256:{12位哈希}"

示例:
  输入: mobile|Phase 4 - Development|9|2025-12-16T15:30:00+08:00|{...}
  输出: "sha256:a1b2c3d4e5f6"
```

---

## 并发冲突处理

**完整规范**: [STATETOKEN_SPEC.md](./STATETOKEN_SPEC.md#冲突检测机制)

### 快速参考

```yaml
检测时机: 写入 UPM 前校验 stateToken

处理策略:
  策略 A - 重读-合并-重试 (推荐): 最多 3 次
  策略 B - 报告冲突: 重试失败后请求人工干预
```

---

## 双层架构后向同步

**完整规范**: [SYNC_RULES.md](./SYNC_RULES.md)

### 快速参考

```yaml
同步方向: detailed-tasks.yaml → tasks.md

触发条件: 提供 spec_path 参数时

执行流程:
  1. 读取 completed 状态的任务
  2. 获取 parent 字段 (如 "1.1")
  3. 更新 tasks.md 对应 checkbox: [ ] → [x]
```

### 三类冲突检测

| 类型 | 说明 | 处理 |
|------|------|------|
| Type 1 | 进度不匹配 | 自动修复，警告 |
| Type 2 | Parent 引用失效 | 中止同步，报错 |
| Type 3 | 任务定义冲突 (相似度<80%) | 继续同步，警告 |

---

## 输出格式

### 成功响应

```
═══════════════════════════════════════════════════════════════
  PROGRESS UPDATE SUCCESSFUL
═══════════════════════════════════════════════════════════════

Module: mobile
Updated At: 2025-12-16T15:30:00+08:00

┌─────────────────────────────────────────────────────────────┐
│ State Changes                                               │
├─────────────────────────────────────────────────────────────┤
│ stateToken: sha256:abc123 → sha256:def456                   │
│ coverage: 87.2% → 89.5%                                     │
└─────────────────────────────────────────────────────────────┘

✅ Tasks Completed: 2
📋 Next Cycle Candidates Updated
📄 Cycle Documents: progress-report.md (created)
```

---

## 使用示例

### 基本进度更新

```yaml
用户请求: "更新 mobile 模块进度"

输入:
  module: mobile
  commit_ref: "git:abc1234-完成图表组件"

输出:
  新 stateToken: sha256:def456
```

### 带 KPI 更新

```yaml
用户请求: "更新进度，测试覆盖率提升到 89.5%"

输入:
  module: mobile
  kpi_updates:
    coverage: "89.5%"
    build: "green"
```

### 标记任务完成并同步 checkbox

```yaml
用户请求: "标记任务完成并同步 tasks.md"

输入:
  module: mobile
  completed_tasks: ["TASK-001", "TASK-002"]
  spec_path: "changes/user-auth"

流程:
  1. 更新 UPM 文档
  2. 执行三类冲突检测
  3. 更新 tasks.md checkbox
```

---

## 错误处理

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| UPM 文档未找到 | 路径不存在 | 检查模块是否已初始化 |
| stateToken 冲突 | 并发写入 | 重试或等待 |
| Parent 引用失效 | tasks.md 编号不存在 | 修复 detailed-tasks.yaml |
| YAML 格式错误 | 格式损坏 | 检查并修复语法 |

---

## 与其他 Skills 的协作

```
A.0: state-scanner ──▶ 读取当前状态
        │
A.1-C.2: 开发流程
        │
D.1: progress-updater (本 Skill)
        │
        ├─▶ 更新 UPM 文档
        ├─▶ 后向同步 tasks.md (可选)
        │
D.2: openspec:archive
```

---

## 检查清单

### 使用前
- [ ] 确认目标模块已初始化 UPM 文档
- [ ] 准备好 commit_ref (推荐)

### 使用后
- [ ] 确认 stateToken 已更新
- [ ] 确认 KPI 数据正确 (如有更新)
- [ ] 确认 tasks.md checkbox 已同步 (如使用后向同步)

---

## 子文件

- [STATETOKEN_SPEC.md](./STATETOKEN_SPEC.md) - stateToken 计算规范
- [SYNC_RULES.md](./SYNC_RULES.md) - 双层同步规则

## 相关文档

- [十步循环概览](../../../standards/core/ten-step-cycle/README.md)
- [Phase D: Closure](../../../standards/core/ten-step-cycle/phase-d-closure.md)
- [UPM 规范](../../../standards/core/upm/unified-progress-management-spec.md)
- [task-planner Skill](../task-planner/SKILL.md)
- [state-scanner Skill](../state-scanner/SKILL.md)

---

**最后更新**: 2025-12-23
**Skill版本**: 2.0.0
**架构**: 双层任务架构 (v2.0.0)

# Level 3 任务分解模板 (tasks.md)

> 此文件定义 Level 3 (Full Spec) 时生成的 tasks.md 模板格式

---

## 模板结构

当 spec-drafter 判断为 Level 3 时，除了生成 `proposal.md`，还会生成以下格式的 `tasks.md`：

```markdown
# {Feature Name} - Task Breakdown

> **Spec**: proposal.md
> **Created**: {YYYY-MM-DD}
> **Status**: Planning

## Overview

{Feature 简要说明，1-2句话}

---

## Dependencies

### External Dependencies
- {外部依赖 1}
- {外部依赖 2}

### Internal Dependencies
- {内部模块依赖}

---

## Task List

### Phase 1: {Phase Name}

#### TASK-001: {Task Title}
- **Description**: {任务详细描述}
- **Complexity**: {S/M/L/XL}
- **Estimated**: {小时数}h
- **Dependencies**: None
- **Agent**: {agent-type}
- **Acceptance Criteria**:
  - [ ] {验收条件 1}
  - [ ] {验收条件 2}

#### TASK-002: {Task Title}
- **Description**: {任务详细描述}
- **Complexity**: {S/M/L/XL}
- **Estimated**: {小时数}h
- **Dependencies**: TASK-001
- **Agent**: {agent-type}
- **Acceptance Criteria**:
  - [ ] {验收条件 1}

### Phase 2: {Phase Name}

#### TASK-003: {Task Title}
...

---

## Execution Order

```
TASK-001 ──────────────────────────▶ TASK-002
                                        │
                                        ▼
TASK-003 ──▶ TASK-004 ──▶ TASK-005 ──▶ TASK-006
```

或简单列表:
```
TASK-001 → TASK-002 → TASK-003 → TASK-004
                ↘
                  TASK-005 (parallel)
```

---

## Risk Assessment

| Risk ID | Description | Level | Mitigation |
|---------|-------------|-------|------------|
| R1 | {风险描述} | {P0/P1/P2} | {缓解措施} |
| R2 | {风险描述} | {P0/P1/P2} | {缓解措施} |

---

## Progress Tracking

| Task | Status | Assignee | Started | Completed |
|------|--------|----------|---------|-----------|
| TASK-001 | Pending | - | - | - |
| TASK-002 | Pending | - | - | - |
| TASK-003 | Pending | - | - | - |

---

## Notes

- {备注 1}
- {备注 2}
```

---

## 字段说明

### Complexity (复杂度)

| Level | 说明 | 典型时间 |
|-------|------|----------|
| **S** | 简单，单文件修改 | 1-2h |
| **M** | 中等，多文件修改 | 3-5h |
| **L** | 复杂，跨组件修改 | 6-8h |
| **XL** | 超大，需要拆分 | >8h |

### Agent Types

| Agent | 适用任务 |
|-------|----------|
| `backend-architect` | API设计、数据库、后端架构 |
| `mobile-developer` | Flutter/Dart、UI组件、状态管理 |
| `qa-engineer` | 测试策略、质量保证、代码审查 |
| `api-documenter` | OpenAPI规范、SDK文档 |
| `knowledge-manager` | 文档管理、架构文档 |
| `tech-lead` | 技术决策、跨模块协调 |

### Dependency Types

- **None**: 无依赖，可立即开始
- **TASK-XXX**: 依赖特定任务完成
- **External**: 依赖外部因素 (如 API 就绪)

---

## 生成示例

### 输入

```yaml
Feature: 重构进度管理系统
Module: cross (standards, mobile, backend)
Level: 3 (Full)
```

### 输出 tasks.md

```markdown
# Progress Management Refactor - Task Breakdown

> **Spec**: proposal.md
> **Created**: 2025-12-17
> **Status**: Planning

## Overview

重构进度管理系统，实现跨模块状态同步，统一 UPM 格式。

---

## Dependencies

### External Dependencies
- Mobile UPM 文档格式确定
- Backend UPM 文档格式确定

### Internal Dependencies
- standards/core/upm/ 规范已定义

---

## Task List

### Phase 1: 规范定义

#### TASK-001: 统一 UPMv2-STATE 格式
- **Description**: 定义跨模块通用的 UPMv2-STATE YAML 格式
- **Complexity**: M
- **Estimated**: 4h
- **Dependencies**: None
- **Agent**: knowledge-manager
- **Acceptance Criteria**:
  - [ ] YAML schema 定义完成
  - [ ] 所有必需字段有明确说明
  - [ ] 示例文档通过验证

#### TASK-002: 创建状态同步协议
- **Description**: 定义跨模块状态同步的协议和流程
- **Complexity**: M
- **Estimated**: 3h
- **Dependencies**: TASK-001
- **Agent**: tech-lead
- **Acceptance Criteria**:
  - [ ] 同步触发条件明确
  - [ ] 冲突解决策略定义
  - [ ] 回滚机制设计

### Phase 2: 实现迁移

#### TASK-003: 迁移 Mobile UPM
- **Description**: 将 Mobile 模块的 UPM 迁移到新格式
- **Complexity**: L
- **Estimated**: 6h
- **Dependencies**: TASK-001, TASK-002
- **Agent**: mobile-developer
- **Acceptance Criteria**:
  - [ ] UPMv2-STATE 格式正确
  - [ ] 历史数据保留
  - [ ] 验证脚本通过

#### TASK-004: 迁移 Backend UPM
- **Description**: 将 Backend 模块的 UPM 迁移到新格式
- **Complexity**: L
- **Estimated**: 6h
- **Dependencies**: TASK-001, TASK-002
- **Agent**: backend-architect
- **Acceptance Criteria**:
  - [ ] UPMv2-STATE 格式正确
  - [ ] 历史数据保留
  - [ ] 验证脚本通过

### Phase 3: 验证与文档

#### TASK-005: 集成测试
- **Description**: 测试跨模块状态同步功能
- **Complexity**: M
- **Estimated**: 4h
- **Dependencies**: TASK-003, TASK-004
- **Agent**: qa-engineer
- **Acceptance Criteria**:
  - [ ] 同步功能正常
  - [ ] 边界情况覆盖
  - [ ] 性能达标

#### TASK-006: 更新文档
- **Description**: 更新所有相关文档和使用指南
- **Complexity**: M
- **Estimated**: 3h
- **Dependencies**: TASK-005
- **Agent**: knowledge-manager
- **Acceptance Criteria**:
  - [ ] 规范文档更新
  - [ ] 使用指南完善
  - [ ] 迁移指南编写

---

## Execution Order

```
TASK-001 ──▶ TASK-002 ──┬──▶ TASK-003 ──┬──▶ TASK-005 ──▶ TASK-006
                        │               │
                        └──▶ TASK-004 ──┘
```

---

## Risk Assessment

| Risk ID | Description | Level | Mitigation |
|---------|-------------|-------|------------|
| R1 | 数据迁移可能丢失历史信息 | P1 | 迁移前完整备份，提供回滚脚本 |
| R2 | 跨模块同步可能产生冲突 | P1 | 设计明确的冲突解决策略 |
| R3 | 格式变更影响现有工具 | P2 | 渐进式迁移，保持向后兼容 |

---

## Progress Tracking

| Task | Status | Assignee | Started | Completed |
|------|--------|----------|---------|-----------|
| TASK-001 | Pending | - | - | - |
| TASK-002 | Pending | - | - | - |
| TASK-003 | Pending | - | - | - |
| TASK-004 | Pending | - | - | - |
| TASK-005 | Pending | - | - | - |
| TASK-006 | Pending | - | - | - |

---

## Notes

- 迁移期间保持两种格式并行，确保平滑过渡
- 优先完成 Mobile 迁移作为 pilot，总结经验后再迁移 Backend
```

---

## 使用说明

1. 当 spec-drafter 判断为 Level 3 时，自动使用此模板
2. 模板中的占位符 `{...}` 由信息提取引擎填充
3. 交互模式下允许用户修改每个任务的详情
4. 生成后存放在 `standards/openspec/changes/{feature}/tasks.md`

---

**最后更新**: 2025-12-17

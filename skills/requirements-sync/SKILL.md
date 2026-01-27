---
name: requirements-sync
description: |
  同步 User Story 状态到 UPM requirements 节，检测偏差并维护一致性。

  使用场景："同步需求状态到 UPM"、"检查 UPM 需求是否一致"
argument-hint: "[--dry-run]"
disable-model-invocation: false
user-invocable: true
allowed-tools: Read, Glob, Grep, Edit
---

# Requirements Sync Skill

> **版本**: 1.1.0 | **层级**: Layer 2 (Business Skill) | **分类**: Requirements Skills

## 快速开始

### 我应该使用这个 Skill 吗？

**使用场景**:
- Story 状态变更后更新 UPM
- 检查 UPM 记录是否与实际文件一致
- 批量同步需求状态
- 迭代规划时更新进度

**不使用场景**:
- 验证文档格式 → 使用 `requirements-validator`
- 同步到 Forgejo → 使用 `forgejo-sync`
- 整体项目状态 → 使用 `state-scanner`

---

## 核心功能

| 功能 | 描述 |
|------|------|
| **scan-stories** | 扫描 Story 文件，提取状态 |
| **update-upm** | 更新 UPM requirements 节 |
| **detect-drift** | 检测 UPM 与实际的偏差 |

---

## 执行流程

### 阶段 1: Story 扫描

```yaml
扫描路径:
  pattern: "{module}/docs/requirements/user-stories/US-*.md"

提取字段:
  - Story ID
  - Status (draft/ready/in_progress/done/blocked)
  - Priority
  - Forgejo Issue (如有)

输出:
  scanned_stories: N
  status_distribution:
    draft: N
    ready: N
    in_progress: N
    done: N
    blocked: N
```

### 阶段 2: PRD 扫描

```yaml
扫描路径:
  pattern: "{module}/docs/requirements/prd-*.md"

提取字段:
  - PRD ID (从文件名)
  - Status (从 header)
  - Path

输出:
  current_prd:
    id: "prd-v2.1.0-xxx"
    status: approved
    path: "docs/requirements/prd-v2.1.0-xxx.md"
```

### 阶段 2.5: System Architecture 扫描

```yaml
扫描路径:
  primary: "docs/architecture/system-architecture.md"
  fallback: "{module}/docs/ARCHITECTURE.md"

提取字段:
  - Exists (文件是否存在)
  - Status (从 header 提取: draft | active | outdated)
  - Last Updated (从 header)
  - Parent PRD (从文档引用提取)

输出:
  system_architecture:
    exists: true
    path: "docs/architecture/system-architecture.md"
    status: active
    last_updated: "2026-01-01"
    parent_prd: "prd-v2.1.0"
```

### 阶段 3: 偏差检测

```yaml
比较项:
  - UPM.requirements.user_stories.total vs 实际文件数
  - UPM.requirements.user_stories.{status} vs 实际状态统计
  - UPM.requirements.prd vs 实际 PRD 文件
  - UPM.requirements.system_architecture.exists vs 实际文件存在
  - UPM.requirements.system_architecture.status vs 实际 header 状态
  - UPM.requirements.system_architecture.parent_prd vs PRD 引用一致性

输出:
  drift_detected: true/false
  drift_items:
    - field: "user_stories.total"
      upm_value: 5
      actual_value: 8
      suggested_action: "update"
    - field: "system_architecture.status"
      upm_value: "active"
      actual_value: "outdated"
      suggested_action: "update"
```

### 阶段 4: UPM 更新 (update 模式)

```yaml
更新内容:
  requirements:
    prd:
      id: "{从文件提取}"
      status: "{从 header 提取}"
      path: "{文件路径}"
    system_architecture:
      exists: {文件是否存在}
      path: "{文件路径}"
      status: "{从 header 提取: draft|active|outdated}"
      last_updated: "{从 header 提取}"
      parent_prd: "{从文档引用提取}"
    user_stories:
      total: {实际数量}
      draft: {统计}
      ready: {统计}
      in_progress: {统计}
      done: {统计}
      blocked: {统计}

保留字段:
  - currentPhase
  - currentCycle
  - lastUpdateAt
  - 其他非 requirements 字段
```

---

## 同步模式

| 模式 | 描述 | 文件修改 |
|------|------|----------|
| `check` | 只检测偏差，不修改 | 否 |
| `update` | 检测并自动更新 UPM | 是 |
| `interactive` | 逐项确认后更新 | 是 |

---

## 输出格式

```yaml
sync_result:
  mode: "check|update|interactive"
  timestamp: "2026-01-01T10:00:00+08:00"

  scanned:
    stories: N
    prd: 1
    architecture: 1

  architecture_status:
    exists: true
    path: "docs/architecture/system-architecture.md"
    status: active
    parent_prd: "prd-v2.1.0"

  status_distribution:
    draft: N
    ready: N
    in_progress: N
    done: N
    blocked: N

  drift:
    detected: true/false
    items:
      - field: "user_stories.total"
        upm_value: 5
        actual_value: 8
        action: "updated|skipped"
      - field: "system_architecture.status"
        upm_value: "active"
        actual_value: "outdated"
        action: "updated|skipped"

  upm:
    updated: true/false
    changes_made:
      - "user_stories.total: 5 → 8"
      - "user_stories.ready: 2 → 3"
      - "system_architecture.status: active → outdated"
```

---

## 使用示例

### 检查模式

```
用户: 检查 UPM 需求是否一致

助手执行:
1. 扫描 Story 文件
2. 读取 UPM requirements 节
3. 比较并报告偏差

输出:
sync_result:
  mode: "check"
  drift:
    detected: true
    items:
      - field: "user_stories.ready"
        upm_value: 2
        actual_value: 3
        suggested_action: "update"
```

### 更新模式

```
用户: 同步需求状态到 UPM

助手执行:
1. 扫描 Story 文件
2. 检测偏差
3. 更新 UPM 文件

输出:
sync_result:
  mode: "update"
  upm:
    updated: true
    changes_made:
      - "user_stories.ready: 2 → 3"
```

---

## UPM 文件位置

```yaml
路径规范:
  Mobile:  mobile/docs/project-planning/unified-progress-management.md
  Backend: backend/project-planning/unified-progress-management.md

查找顺序:
  1. {module}/docs/project-planning/unified-progress-management.md
  2. {module}/project-planning/unified-progress-management.md
```

---

## 与其他 Skills 的关系

```
┌─────────────────────────────────────────────────────────────┐
│  requirements-validator (Layer 2)                           │
│      │ 验证后                                                │
│      ▼                                                      │
│  requirements-sync (Layer 2) ◄── 本 Skill                   │
│      │ 同步后                                                │
│      ▼                                                      │
│  forgejo-sync (Layer 2) ── 可选同步到 Forgejo               │
└─────────────────────────────────────────────────────────────┘
```

---

## 相关文档

- **规范**: `openspec/specs/requirements-sync/spec.md`
- **UPM 扩展**: `standards/core/upm/upm-requirements-extension.md`
- **UPM 规范**: `standards/core/upm/unified-progress-management-spec.md`

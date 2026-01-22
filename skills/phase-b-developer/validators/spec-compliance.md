# Phase 1: 规范合规性检查

> **版本**: 1.0.0
> **来源**: TASK-018
> **Skill**: phase-b-developer

---

## 概述

Phase 1 验证开发过程是否符合 Aria 项目规范，包括 OpenSpec 格式、UPM 状态同步、架构文档同步等。

---

## 检查项目

### 1. OpenSpec 格式验证

检查 OpenSpec 文档格式是否符合规范要求。

```yaml
检查项:
  - proposal.md 头部字段完整
  - tasks.md 编号格式正确
  - detailed-tasks.yaml 结构有效 (如存在)

验证规则:
  proposal.md:
    required_fields:
      - Level
      - Status
      - Module
      - Why
      - What
      - Impact
      - Scope
      - Success Criteria

  tasks.md:
    format: "- [ ] {phase}.{task} {description}"
    numbering: "sequential, no gaps"

  detailed-tasks.yaml:
    schema_valid: true
    parent_references: valid
```

### 2. UPM 状态同步检查

检查 UPM (Unified Progress Management) 状态是否与实际一致。

```yaml
检查项:
  - UPM 文件存在
  - stateToken 正确计算
  - 周期状态与实际一致

验证规则:
  upm_file:
    location: "{module}/docs/project-planning/unified-progress-management.md"
    required_sections:
      - Phase Status
      - Cycle Status
      - KPI Summary

  state_token:
    format: "{date}-{commit_count}"
    must_match: git log --oneline | wc -l

  synchronization:
    completed_tasks_marked: true
    in_progress_accurate: true
```

### 3. 架构文档同步检查

检查代码变更是否同步到架构文档。

```yaml
检查项:
  - 架构文档存在
  - 变更已记录
  - 文档版本更新

验证规则:
  architecture_docs:
    required_for:
      - new_components
      - api_changes
      - data_model_changes

  documentation_check:
    file_pattern: "docs/**/*ARCHITECTURE*.md"
    verify_sections:
      - 新增组件
      - 修改的接口
      - 数据模型变更

  version_sync:
    doc_version: must_match_code_version
    last_updated: within_last_24h
```

---

## 阻塞条件

以下条件将**阻塞**开发继续进行：

```yaml
critical_issues:
  openspec_format:
    - proposal.md 缺少必需字段
    - tasks.md 编号不连续
    - Level 3 spec 缺少 detailed-tasks.yaml

  upm_sync:
    - stateToken 不匹配
    - 已完成任务未标记
    - 周期状态错误

  arch_doc_sync:
    - 新组件无架构文档
    - API 变更未更新接口文档
```

---

## 验证流程

```yaml
输入:
  changed_files: [...]  # 变更的文件列表
  spec_id: "..."        # 关联的 Spec ID

步骤:
  1. 检测变更类型
     - 代码变更 → 检查架构文档
     - Spec 变更 → 检查格式
     - 状态变更 → 检查 UPM

  2. 执行验证
     - 运行对应检查规则
     - 收集问题列表

  3. 生成报告
     - 按严重程度分类
     - 提供修复建议

  4. 判断是否阻塞
     - Critical → 阻塞
     - Warning → 继续
```

---

## 报告格式

```yaml
Phase 1 Review Report:
  summary:
    status: "pass" | "fail" | "warning"
    checked_at: "2026-01-18T10:30:00Z"
    total_issues: 3

  openspec_format:
    status: "pass"
    issues: []

  upm_sync:
    status: "warning"
    issues:
      - severity: "warning"
        description: "stateToken 需要更新"
        suggestion: "运行 progress-updater skill"

  arch_doc_sync:
    status: "fail"
    issues:
      - severity: "critical"
        description: "新组件 UserAuth 无架构文档"
        file: "lib/auth/user_auth.dart"
        suggestion: "运行 arch-update skill 更新架构文档"

  blocking_issues:
    - arch_doc_sync.issue[0]

  recommendations:
    - "更新架构文档"
    - "同步 UPM 状态"
```

---

## 修复建议

| 问题类型 | 建议操作 | 相关 Skill |
|----------|----------|-----------|
| OpenSpec 格式错误 | 检查并修正格式 | `spec-drafter` |
| UPM 状态不同步 | 更新进度状态 | `progress-updater` |
| 架构文档缺失 | 生成/更新架构文档 | `arch-update` |
| 版本号不匹配 | 更新文档版本 | 手动编辑 |

---

## 集成到 phase-b-developer

```yaml
phase-b-developer:
  steps:
    - B.1: branch-manager
    - B.2: test-verifier
    - B.Review.Phase1: spec-compliance  # 新增
    - B.Review.Phase2: code-quality
    - B.3: arch-update

  配置:
    review_config:
      enabled: true
      phase1:
        enabled: true
        blocking: true
        checks:
          openspec_format: true
          upm_sync: true
          arch_doc_sync: true
```

---

## 示例

### 示例 1: 通过验证

```yaml
输入:
  changed_files: ["lib/auth.dart", "test/auth_test.dart"]
  spec_id: "user-auth"

验证:
  openspec_format: pass
  upm_sync: pass
  arch_doc_sync: pass (无架构变更)

结果:
  status: pass
  可以继续: Phase 2
```

### 示例 2: 阻塞问题

```yaml
输入:
  changed_files: ["lib/api/new_service.dart"]

验证:
  openspec_format: pass
  upm_sync: pass
  arch_doc_sync: fail
    - 新服务无架构文档

结果:
  status: fail
  阻塞: true
  建议: 运行 arch-update skill
```

---

**版本**: 1.0.0
**创建**: 2026-01-18
**相关**: [phase-b-developer](../SKILL.md)

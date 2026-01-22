# 评审报告模板

> **版本**: 1.0.0
> **来源**: TASK-021
> **Skill**: phase-b-developer

---

## 报告结构

```yaml
Phase B Review Report:
  # 报告头部
  metadata:
    generated_at: "2026-01-18T10:30:00Z"
    reviewer: "phase-b-developer"
    feature_id: "aria-workflow-enhancement"
    branch: "feature/standards/aria-workflow-enhancement"

  # 执行摘要
  summary:
    total_steps_executed: 3
    steps_skipped: 0
    overall_status: "pass" | "fail" | "warning"
    quality_score: 85

  # Phase 1: 规范合规性
  phase1_review:
    status: "pass" | "fail" | "warning"
    duration_ms: 150
    checks:
      openspec_format:
        status: "pass"
        details: "所有必需字段存在"
      upm_sync:
        status: "warning"
        details: "stateToken 需要更新"
      arch_doc_sync:
        status: "pass"
        details: "架构文档已同步"
    issues:
      - severity: "warning"
        category: "upm_sync"
        message: "UPM stateToken 需要更新"
        suggestion: "运行 progress-updater skill"

  # Phase 2: 代码质量
  phase2_review:
    status: "warning" | "pass" | "fail"
    duration_ms: 850
    checks:
      test_coverage:
        status: "warning"
        current: 78
        target: 85
        gap: 7
      code_complexity:
        status: "pass"
        average: 8
        max: 12
      security_scan:
        status: "pass"
        issues: 0
    recommendations:
      - "为 AuthManager.addUser() 添加测试"
      - "重构 authService.dart 中的高复杂度函数"

  # 阻塞问题
  blocking_issues:
    - id: "BLOCK-001"
      severity: "critical"
      phase: "phase1"
      category: "upm_sync"
      message: "UPM stateToken 不匹配"
      current_value: "2026-01-17-123"
      expected_value: "2026-01-18-125"
      suggestion: "运行 progress-updater skill"
      must_fix: true

  # 修复建议
  fix_suggestions:
    - priority: "P0"
      category: "upm_sync"
      action: "运行 progress-updater skill"
      estimated_time: "2 minutes"
    - priority: "P1"
      category: "test_coverage"
      action: "为 AuthManager 添加测试用例"
      estimated_time: "15 minutes"
    - priority: "P2"
      category: "code_complexity"
      action: "重构高复杂度函数"
      estimated_time: "30 minutes"

  # 下一步
  next_steps:
    - "修复阻塞问题"
    - "运行 progress-updater"
    - "添加测试用例"
    - "继续到 Phase C"
```

---

## Markdown 报告模板

```markdown
# Phase B 评审报告

**生成时间**: 2026-01-18 10:30:00 UTC
**功能**: aria-workflow-enhancement
**分支**: feature/standards/aria-workflow-enhancement

---

## 执行摘要

| 项目 | 状态 | 详情 |
|------|------|------|
| 总步骤 | 3 | B.1, B.2, B.3 |
| 跳过步骤 | 0 | - |
| 整体状态 | ⚠️ Warning | 有警告但可继续 |
| 质量评分 | 85/100 | Good |

---

## Phase 1: 规范合规性

| 检查项 | 状态 | 详情 |
|--------|------|------|
| OpenSpec 格式 | ✅ Pass | 所有必需字段存在 |
| UPM 状态同步 | ⚠️ Warning | stateToken 需要更新 |
| 架构文档同步 | ✅ Pass | 架构文档已同步 |

### 问题列表

- [ ] **[Warning]** UPM stateToken 需要更新
  - 当前: 2026-01-17-123
  - 预期: 2026-01-18-125
  - 建议: 运行 progress-updater skill

---

## Phase 2: 代码质量

| 检查项 | 状态 | 当前值 | 目标值 |
|--------|------|--------|--------|
| 测试覆盖率 | ⚠️ Warning | 78% | 85% |
| 代码复杂度 | ✅ Pass | avg: 8, max: 12 | avg: 10 |
| 安全扫描 | ✅ Pass | 0 issues | 0 issues |

### 改进建议

1. **提升测试覆盖率**
   - 当前: 78%, 目标: 85%, 差距: 7%
   - 为 `AuthManager.addUser()` 添加测试
   - 覆盖错误处理路径

2. **降低代码复杂度**
   - `auth_service.dart:authenticate` 复杂度为 12
   - 建议拆分函数

---

## 阻塞问题

无阻塞问题。

---

## 下一步操作

1. [ ] 运行 `progress-updater` 更新 UPM
2. [ ] 添加测试用例提升覆盖率
3. [ ] 继续 Phase C (提交集成)

---

*报告由 phase-b-developer 自动生成*
```

---

## JSON 报告格式

```json
{
  "metadata": {
    "generated_at": "2026-01-18T10:30:00Z",
    "reviewer": "phase-b-developer",
    "feature_id": "aria-workflow-enhancement",
    "branch": "feature/standards/aria-workflow-enhancement",
    "commit": "abc123"
  },
  "summary": {
    "total_steps_executed": 3,
    "steps_skipped": 0,
    "overall_status": "warning",
    "quality_score": 85,
    "can_continue": true
  },
  "phase1_review": {
    "status": "warning",
    "duration_ms": 150,
    "checks": {
      "openspec_format": {
        "status": "pass",
        "details": "所有必需字段存在"
      },
      "upm_sync": {
        "status": "warning",
        "details": "stateToken 需要更新"
      },
      "arch_doc_sync": {
        "status": "pass",
        "details": "架构文档已同步"
      }
    },
    "issues": [
      {
        "id": "WARN-001",
        "severity": "warning",
        "category": "upm_sync",
        "message": "UPM stateToken 需要更新",
        "suggestion": "运行 progress-updater skill"
      }
    ]
  },
  "phase2_review": {
    "status": "warning",
    "duration_ms": 850,
    "checks": {
      "test_coverage": {
        "status": "warning",
        "current": 78,
        "target": 85,
        "gap": 7
      },
      "code_complexity": {
        "status": "pass",
        "average": 8,
        "max": 12,
        "threshold": 10
      },
      "security_scan": {
        "status": "pass",
        "issues": 0
      }
    },
    "recommendations": [
      "为 AuthManager.addUser() 添加测试",
      "重构 authService.dart 中的高复杂度函数"
    ]
  },
  "blocking_issues": [],
  "fix_suggestions": [
    {
      "priority": "P0",
      "category": "upm_sync",
      "action": "运行 progress-updater skill",
      "estimated_time": "2 minutes"
    },
    {
      "priority": "P1",
      "category": "test_coverage",
      "action": "为 AuthManager 添加测试用例",
      "estimated_time": "15 minutes"
    }
  ],
  "next_steps": [
    "修复阻塞问题",
    "运行 progress-updater",
    "添加测试用例",
    "继续到 Phase C"
  ]
}
```

---

## 使用示例

### 生成报告

```bash
# 在 phase-b-developer 中
phase-b-developer --review

# 输出:
# - 控制台: Markdown 格式
# - 文件: review-report.json
```

### 导出报告

```yaml
导出格式:
  - console: 终端输出 (默认)
  - markdown: .md 文件
  - json: .json 文件
  - html: .html 文件 (待实现)

命令:
  --output-format markdown
  --output-file review-report.md
```

---

**版本**: 1.0.0
**创建**: 2026-01-18
**相关**: [phase-b-developer](../SKILL.md) | [spec-compliance](./spec-compliance.md) | [code-quality](./code-quality.md)

# 评审阻塞机制配置

> **版本**: 1.0.0
> **来源**: TASK-020
> **Skill**: phase-b-developer

---

## 概述

阻塞机制定义了哪些问题会**阻止**开发继续进行，确保关键问题在进入下一阶段前得到解决。

---

## 阻塞条件

### Phase 1: 规范合规性

```yaml
阻塞规则:
  critical:  # 必须修复
    - OpenSpec 格式错误
    - UPM stateToken 不匹配
    - 新组件无架构文档
    - API 变更未更新接口文档

  warning:  # 记录但不阻塞
    - 文档描述不够详细
    - 示例代码缺失
```

### 阻塞等级

| 等级 | 阻塞 | 通知 | 示例 |
|------|------|------|------|
| **critical** | ✅ | 强制 | UPM 状态错误 |
| **high** | ✅ | 强制 | 新组件无文档 |
| **medium** | ❌ | 警告 | 文档描述简略 |
| **low** | ❌ | 信息 | 建议补充示例 |

---

## 阻塞处理流程

```yaml
检测到问题:
  1. 识别问题类型和严重程度
  2. 判断是否满足阻塞条件
  3. 生成阻塞报告

如果是阻塞问题:
  → 停止执行
  → 显示问题和修复建议
  → 等待用户确认修复

如果不是阻塞问题:
  → 记录到警告列表
  → 继续执行
```

---

## 阻塞规则配置

### 配置文件

```json
{
  "blocking_rules": {
    "phase1": {
      "critical": [
        {
          "check": "openspec_format",
          "condition": "missing_required_fields",
          "message": "proposal.md 缺少必需字段",
          "suggestion": "运行 spec-drafter 修正格式",
          "fix_required": true
        },
        {
          "check": "upm_sync",
          "condition": "state_token_mismatch",
          "message": "UPM stateToken 与实际不符",
          "suggestion": "运行 progress-updater 更新",
          "fix_required": true
        }
      ],
      "high": [
        {
          "check": "arch_doc_sync",
          "condition": "new_component_no_doc",
          "message": "新组件缺少架构文档",
          "suggestion": "运行 arch-update 生成文档",
          "fix_required": true
        }
      ]
    }
  }
}
```

---

## 绕过选项

### 1. 用户显式确认

```yaml
force_continue: true
原因: "将在后续提交中修复"
记录: "技术债务 - 文档待更新"
```

### 2. 标记为技术债务

```yaml
标记: technical_debt
原因: "时间紧急，文档稍后补充"
优先级: P1  # 下个 Cycle 必须完成
```

### 3. 紧急情况

```yaml
场景: hotfix
绕过: 所有非安全相关的阻塞
要求: 说明紧急原因
后续: 必须补齐
```

---

## 阻塞报告格式

```yaml
阻塞报告:
  timestamp: "2026-01-18T10:30:00Z"
  blocked: true

  critical_issues:
    - id: BLOCK-001
      severity: critical
      check: "upm_sync"
      message: "UPM stateToken 不匹配"
      current: "2026-01-17-123"
      expected: "2026-01-18-125"
      suggestion: "运行 progress-updater skill"
      fix_required: true

  warning_issues:
    - id: WARN-001
      severity: medium
      check: "documentation"
      message: "示例代码缺失"
      suggestion: "添加使用示例"
      fix_required: false

  修复建议:
    - "运行 progress-updater skill 更新 UPM"
    - "添加示例代码到文档"

  绕过选项:
    - "1. 修复后继续 (推荐)"
    - "2. 标记为技术债务 (需说明原因)"
    - "3. 强制继续 (不推荐)"
```

---

## 阻塞决策树

```
                    检测到问题
                        │
                        ▼
              ┌─────────────────────┐
              │ 问题严重程度如何？   │
              └─────────────────────┘
                        │
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
    Critical         High          Medium/Low
        │               │               │
        ▼               ▼               ▼
    ┌───────┐       ┌───────┐       ┌───────┐
    │ 阻塞  │       │ 阻塞  │       │记录   │
    │强制修复│       │强制修复│       │继续   │
    └───────┘       └───────┘       └───────┘
        │               │
        ▼               ▼
    ┌─────────────────────────┐
    │ 是否需要绕过？           │
    └─────────────────────────┘
        │           │
        ▼           ▼
    是            否
        │           │
        ▼           ▼
    记录技术债务   修复后继续
        │
        ▼
    继续 (带警告)
```

---

## 实现示例

### 检查函数

```python
def should_block(issue: Issue) -> bool:
    """判断问题是否应该阻塞执行"""
    if issue.severity in ["critical", "high"]:
        return True

    # 可配置的阻塞条件
    if issue.category in BLOCKING_CATEGORIES:
        return True

    return False

def check_blocking(issues: List[Issue]) -> BlockingResult:
    """检查所有问题并返回阻塞结果"""
    blocking_issues = [i for i in issues if should_block(i)]

    if blocking_issues:
        return BlockingResult(
            blocked=True,
            issues=blocking_issues,
            suggestions=generate_suggestions(blocking_issues)
        )

    return BlockingResult(blocked=False)
```

---

**版本**: 1.0.0
**创建**: 2026-01-18
**相关**: [phase-b-developer](../SKILL.md) | [spec-compliance](./spec-compliance.md) | [code-quality](./code-quality.md)

# Phase 1 FAIL 阻塞场景示例

> **场景**: 代码审查在 Phase 1 失败，阻塞继续
> **Phase 1**: 规范合规性检查 - FAIL
> **结果**: 审查终止，必须修复后重新提交

---

## 场景描述

用户完成任务 TASK-002（添加密码重置功能），但 Phase 1 检查发现关键问题。

---

## 输入参数

```yaml
WHAT_WAS_IMPLEMENTED: 实现了密码重置功能，包括邮件发送和重置链接验证
PLAN_OR_REQUIREMENTS: detailed-tasks.yaml TASK-002
BASE_SHA: 3df7661
HEAD_SHA: 5a8b92c
```

---

## 审查结果

### Phase 1: 规范合规性检查

**判定**: ❌ FAIL - 审查终止

#### 阻塞问题 (Blocking Issues)

##### 1. 计划功能缺失 / Missing Planned Feature

- **文件**: `src/auth/password-reset.ts`
- **缺少什么 / What's Missing**: 密码强度验证功能
- **为什么重要 / Why it Matters**: 计划文档中明确要求密码必须包含大小写字母、数字、特殊字符
- **如何修复 / How to Fix**:
  ```typescript
  // 添加密码强度验证
  function validatePasswordStrength(password: string): boolean {
    const hasUpperCase = /[A-Z]/.test(password);
    const hasLowerCase = /[a-z]/.test(password);
    const hasNumber = /[0-9]/.test(password);
    const hasSpecial = /[^a-zA-Z0-9]/.test(password);
    return password.length >= 8 && hasUpperCase && hasLowerCase && hasNumber && hasSpecial;
  }
  ```

##### 2. 范围变更 / Scope Creep

- **文件**: `src/utils/date-formatter.ts` (计划外)
- **问题 / Issue**: 添加了计划外的日期格式化工具函数
- **为什么重要 / Why it Matters**: 超出计划范围，未经审查的功能可能引入风险
- **如何修复 / How to Fix**:
  - 选项 A: 移除该功能，从代码中删除
  - 选项 B: 更新计划文档，将该功能纳入规范

##### 3. OpenSpec 字段未同步 / OpenSpec Not Updated

- **文件**: `openspec/changes/task-002/proposal.md`
- **问题 / Issue**: 状态仍为 "Draft"，功能实现完成后未更新
- **为什么重要 / Why it Matters**: 文档与代码不同步，可能导致后续理解偏差
- **如何修复 / How to Fix**:
  ```markdown
  更新 proposal.md 状态:
    ---
    > **Status**: Draft → Implemented
    > **Completed**: 2026-02-06
  ```

---

## 审查终止通知

```
═════════════════════════════════════════════════════════════════════
                    ⚠️ CODE REVIEW FAILED - PHASE 1 ⚠️
════════════════════════════════════════════════════════════════════

任务: TASK-002
审查基准: detailed-tasks.yaml TASK-002
Git 范围: a7981ec..5a8b92c

发现 3 个阻塞问题，必须修复后重新提交:

1. [HIGH] 计划功能缺失 - 密码强度验证
   文件: src/auth/password-reset.ts
   修复: 添加密码强度验证逻辑

2. [MEDIUM] 范围变更 - 日期格式化工具
   文件: src/utils/date-formatter.ts
   修复: 移除功能或更新计划文档

3. [LOW] 文档未同步 - OpenSpec 状态
   文件: openspec/changes/task-002/proposal.md
   修复: 更新状态为 Implemented

═════════════════════════════════════════════════════════════════════

🚫 审查终止 - 请勿继续下一任务，直到上述问题得到解决
```

---

## 修复后重新提交

### 修复流程

1. **修复问题**:
   ```bash
   # 1. 添加密码强度验证
   # 2. 移除或规范化计划外功能
   # 3. 更新 OpenSpec 状态
   ```

2. **提交修复**:
   ```bash
   git add .
   git commit -m "fix: resolve TASK-002 blocking issues"
   ```

3. **重新请求审查**:
   - 重新调用 requesting-code-review Skill
   - 使用新的 HEAD_SHA
   - Phase 1 应该通过

---

## 关键要点

1. **Phase 1 FAIL 的影响**:
   - 审查立即终止，不进入 Phase 2
   - 用户不能继续下一任务
   - 确保问题在累积前被捕获

2. **阻塞问题的分类**:
   - HIGH: 功能缺失（必须修复）
   - MEDIUM: 范围变更（必须处理）
   - LOW: 文档问题（建议修复）

3. **修复验证**:
   - 修复后必须重新提交审查
   - 即使修复了，也可能发现其他问题

---

**示例版本**: 1.0.0
**创建日期**: 2026-02-06
**维护**: Aria 项目组

# 直接 Agent 调用方式示例

> **场景**: 直接调用 aria:code-reviewer Agent 进行代码审查
> **入口**: 使用 Task tool 启动 code-reviewer Agent
> **结果**: 完全自定义的审查流程

---

## 场景描述

用户需要对特定提交进行深度审查，使用完全自定义的审查参数。

---

## 调用方式

### 方式 1: 使用 Task tool

```yaml
Task tool 调用:
  subagent_type: "aria:code-reviewer"
  prompt: |
    请审查以下代码变更：

    WHAT_WAS_IMPLEMENTED: 重构用户服务模块，拆分为多个子服务
    PLAN_OR_REQUIREMENTS: detailed-tasks.yaml TASK-005
    BASE_SHA: 1a2b3c4
    HEAD_SHA: 9d8e7f6

    请使用中文输出审查结果。
```

### 方式 2: 通过 Agent 前缀

```bash
# 在 Claude Code 中执行
/code-reviewer

# 然后提供审查参数
```

---

## 完整示例

### 示例 1: 标准审查

```yaml
Task 启动:
  subagent_type: "aria:code-reviewer"
  prompt: |
    审查从 1a2b3c4 到 9d8e7f6 的变更。

    实现内容: 重构用户服务模块，引入依赖注入
    计划基准: detailed-tasks.yaml TASK-005

Agent 输出:
  ═════════════════════════════════════════════════════════════════════
                          CODE REVIEW REPORT
  ═════════════════════════════════════════════════════════════════════

  Phase 1: ✅ PASS
  Phase 2: ⚠️  PASS_WITH_WARNINGS

  Issues:
    Important (2):
      1. 装饰器模式可能导致循环依赖
      2. 缺少依赖图文档

  Assessment: 建议修复 Important 问题后继续
  ═════════════════════════════════════════════════════════════════════
```

### 示例 2: 仅 Phase 2 审查

```yaml
Task 启动:
  subagent_type: "aria:code-reviewer"
  prompt: |
    审查以下代码的代码质量（跳过规范检查）：

    实现内容: 修复用户登录时的 token 泄漏问题
    BASE_SHA: 7c9e3d4
    HEAD_SHA: 8d1f5e

    注意: 无详细计划，请仅执行 Phase 2 代码质量检查。

Agent 行为:
  - 跳过 Phase 1
  - 直接执行 Phase 2
  - 检查代码质量、安全、测试
```

### 示例 3: 自定义审查范围

```yaml
Task 启动:
  subagent_type: "aria:code-reviewer"
  prompt: |
    审查以下文件的代码质量：

    文件列表:
      - src/services/user-service.ts
      - src/middleware/auth.ts

    重点检查:
      1. 安全性 (SQL 注入、XSS)
      2. 错误处理
      3. 性能问题

    不需要检查: 代码风格

Agent 行为:
  - 仅审查指定文件
  - 重点检查安全相关
  - 跳过风格检查
```

---

## 高级用法

### 1. 指定输出语言

```yaml
prompt: |
  审查以下代码...

  请使用英语输出审查结果。
  Please output the review results in English.
```

### 2. 指定审查深度

```yaml
prompt: |
  审查以下代码...

  审查深度: 深度审查
  - 检查所有代码路径
  - 分析性能瓶颈
  - 提出优化建议
```

### 3. 指定审查标准

```yaml
prompt: |
  审查以下代码...

  审查标准:
    - 遵循 CLAUDE.md 中的规范
    - 符合项目编码约定
    - 满足 OpenSpec 需求
```

---

## 与 Skill 调用的对比

### 便利性对比

| 方面 | Skill 调用 | Agent 直接调用 |
|------|-----------|---------------|
| **准备时间** | 秒级 | 分钟级 |
| **参数输入** | 交互式收集 | 手动准备 |
| **模板填充** | 自动 | 手动 |
| **灵活性** | 标准流程 | 完全自定义 |

### 适用场景对比

```yaml
Skill 调用适合:
  - 日常任务审查
  - 标准流程需求
  - 快速审查

Agent 直接调用适合:
  - 特殊审查需求
  - 自定义审查标准
  - 深度分析
  - 集成到自定义流程
```

---

## 集成示例

### 集成到 CI/CD

```yaml
# .github/workflows/code-review.yml
name: Code Review

on:
  pull_request:
    types: [opened, synchronize]

jobs:
  code-review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Run Code Review
        run: |
          claude-code \
            --agent aria:code-reviewer \
            --prompt "Review PR #${{ github.event.number }}" \
            --output review-report.json

      - name: Comment PR
        uses: actions/github-script@v6
        with:
          script: |
            const report = require('./review-report.json');
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: formatReviewReport(report)
            });
```

### 集成到 Pre-commit Hook

```yaml
# .git-hooks/pre-commit
#!/bin/bash

echo "Running code review..."

CHANGED_FILES=$(git diff --cached --name-only)

if [ -n "$CHANGED_FILES" ]; then
  claude-code \
    --agent aria:code-reviewer \
    --prompt "Review staged changes" \
    --base HEAD \
    --head HEAD \
    --fail-on-critical

  REVIEW_EXIT=$?

  if [ $REVIEW_EXIT -ne 0 ]; then
    echo "❌ Code review failed. Please fix issues before committing."
    exit 1
  fi
fi

echo "✅ Code review passed."
```

---

## 常见问题

### Q: 如何获取 Agent 输出？

```yaml
方式 1: 查看终端输出
  Agent 输出会直接显示在终端

方式 2: 保存到文件
  prompt: |
    审查以下代码...
    请将结果保存到 review-report.md

方式 3: 使用 TaskOutput tool
  TaskOutput(task_id: "...", block: true)
```

### Q: 如何处理 Agent 失败？

```yaml
失败类型:
  1. Agent 启动失败
  2. 审查执行失败
  3. 审查超时

处理方式:
  - 查看错误日志
  - 检查输入参数
  - 减少审查范围
  - 增加超时时间
```

### Q: 可以并行调用多个 Agent 吗？

```yaml
可以:

Task(code-reviewer, ...)  # 审查模块 A
Task(code-reviewer, ...)  # 审查模块 B

注意:
  - 每个 Agent 是独立的 Fresh Subagent
  - 无历史污染
  - 可并行执行
```

---

## 性能优化

### 1. 缩小审查范围

```yaml
# 不推荐: 审查整个项目
prompt: "Review everything"

# 推荐: 审查变更部分
prompt: "Review changes from BASE_SHA to HEAD_SHA"
```

### 2. 使用增量审查

```yaml
# 第一次审查
prompt: "Review new feature X"

# 增量审查（基于第一次）
prompt: |
  Previous review: ... (引用第一次结果)
  New changes: ...
  Please review only the new changes.
```

### 3. 缓存审查结果

```yaml
缓存策略:
  - 保存审查报告到文件
  - 后续审查基于上次结果
  - 仅审查变更部分
```

---

**示例版本**: 1.0.0
**创建日期**: 2026-02-06
**维护**: Aria 项目组

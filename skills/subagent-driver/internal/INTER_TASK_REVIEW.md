# 任务间代码审查机制

> **Subagent Driver v1.0.0** | Inter-Task Code Review
> **Phase 2.3** | enforcement-mechanism-redesign

## Overview

任务间代码审查是 SDD 的核心质量保障机制，确保每个任务完成后由独立审查者检查代码质量。

---

## 审查流程

```
┌─────────────────────────────────────────────────────────────┐
│                    任务间代码审查流程                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  任务 N 完成                                                 │
│      │                                                      │
│      ▼                                                      │
│  收集变更 (git diff)                                         │
│      │                                                      │
│      ▼                                                      │
│  启动审查 Agent (code-reviewer)                              │
│      │                                                      │
│      ▼                                                      │
│  执行审查检查                                                │
│      ├─ 代码质量                                            │
│      ├─ 逻辑正确性                                          │
│      ├─ 安全漏洞                                            │
│      ├─ 测试覆盖                                            │
│      └─ 文档同步                                            │
│      │                                                      │
│      ▼                                                      │
│  生成审查报告                                                │
│      │                                                      │
│      ▼                                                      │
│  判定结果                                                    │
│      ├─ PASS → 继续任务 N+1                                 │
│      ├─ PASS_WITH_WARNINGS → 警告后继续                     │
│      └─ FAIL → 返回修复                                     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Implementation

### Pseudo-Code

```python
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from enum import Enum
import subprocess

class ReviewVerdict(Enum):
    PASS = "pass"
    PASS_WITH_WARNINGS = "pass_with_warnings"
    FAIL = "fail"

class IssueSeverity(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

@dataclass
class ReviewIssue:
    """审查问题"""
    severity: IssueSeverity
    file: str
    line: Optional[int]
    message: str
    suggestion: Optional[str] = None
    rule: Optional[str] = None  # 违反的规则

@dataclass
class ReviewReport:
    """审查报告"""
    task_id: str
    reviewer: str
    timestamp: str
    verdict: ReviewVerdict
    issues: List[ReviewIssue] = field(default_factory=list)
    summary: Dict[str, int] = field(default_factory=dict)
    execution_time: float = 0.0

    def __post_init__(self):
        # 计算摘要
        self.summary = {
            "high": len([i for i in self.issues if i.severity == IssueSeverity.HIGH]),
            "medium": len([i for i in self.issues if i.severity == IssueSeverity.MEDIUM]),
            "low": len([i for i in self.issues if i.severity == IssueSeverity.LOW]),
        }


class InterTaskReviewer:
    """任务间代码审查器"""

    # 审查规则
    REVIEW_RULES = {
        "security": {
            "patterns": [
                r"eval\s*\(",
                r"exec\s*\(",
                r"subprocess\.call.*shell=True",
                r"\.format\(.*\).*execute",
                r"f['\"].*\{.*\}.*execute",
            ],
            "severity": IssueSeverity.HIGH,
            "message": "潜在安全漏洞",
        },
        "code_quality": {
            "max_function_lines": 50,
            "max_file_lines": 500,
            "max_complexity": 10,
            "severity": IssueSeverity.MEDIUM,
        },
        "naming": {
            "patterns": {
                "function": r"^[a-z_][a-z0-9_]*$",
                "class": r"^[A-Z][a-zA-Z0-9]*$",
                "constant": r"^[A-Z_][A-Z0-9_]*$",
            },
            "severity": IssueSeverity.LOW,
        },
    }

    def __init__(
        self,
        project_root: str,
        review_threshold: IssueSeverity = IssueSeverity.HIGH
    ):
        self.project_root = project_root
        self.review_threshold = review_threshold

    def review(self, task_id: str) -> ReviewReport:
        """
        执行代码审查

        Args:
            task_id: 任务 ID

        Returns:
            ReviewReport: 审查报告
        """
        import time
        start_time = time.time()

        # 1. 收集变更
        changes = self._collect_changes()

        # 2. 执行审查
        issues = []

        # 2.1 安全检查
        issues.extend(self._check_security(changes))

        # 2.2 代码质量检查
        issues.extend(self._check_code_quality(changes))

        # 2.3 命名规范检查
        issues.extend(self._check_naming(changes))

        # 2.4 测试覆盖检查
        issues.extend(self._check_test_coverage(changes))

        # 3. 判定结果
        verdict = self._determine_verdict(issues)

        # 4. 生成报告
        report = ReviewReport(
            task_id=task_id,
            reviewer="inter-task-reviewer",
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            verdict=verdict,
            issues=issues,
            execution_time=time.time() - start_time,
        )

        return report

    def _collect_changes(self) -> Dict[str, str]:
        """收集 git 变更"""
        # 获取变更的文件列表
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~1"],
            capture_output=True,
            text=True,
            cwd=self.project_root,
        )
        changed_files = result.stdout.strip().split("\n")

        # 获取每个文件的 diff
        changes = {}
        for file in changed_files:
            if not file:
                continue
            diff_result = subprocess.run(
                ["git", "diff", "HEAD~1", "--", file],
                capture_output=True,
                text=True,
                cwd=self.project_root,
            )
            changes[file] = diff_result.stdout

        return changes

    def _check_security(self, changes: Dict[str, str]) -> List[ReviewIssue]:
        """安全检查"""
        import re
        issues = []

        for file, diff in changes.items():
            for pattern in self.REVIEW_RULES["security"]["patterns"]:
                matches = re.finditer(pattern, diff)
                for match in matches:
                    issues.append(ReviewIssue(
                        severity=IssueSeverity.HIGH,
                        file=file,
                        line=self._find_line_number(diff, match.start()),
                        message=f"安全风险: {pattern}",
                        suggestion="请检查此代码是否存在安全漏洞",
                        rule="security",
                    ))

        return issues

    def _check_code_quality(self, changes: Dict[str, str]) -> List[ReviewIssue]:
        """代码质量检查"""
        issues = []
        rules = self.REVIEW_RULES["code_quality"]

        for file, diff in changes.items():
            # 检查函数长度
            # 检查文件长度
            # 检查复杂度
            # (简化实现)
            pass

        return issues

    def _check_naming(self, changes: Dict[str, str]) -> List[ReviewIssue]:
        """命名规范检查"""
        issues = []
        # (简化实现)
        return issues

    def _check_test_coverage(self, changes: Dict[str, str]) -> List[ReviewIssue]:
        """测试覆盖检查"""
        issues = []

        # 检查是否有对应的测试文件
        for file in changes.keys():
            if file.endswith(".py") and not file.startswith("test_"):
                test_file = f"test_{file}"
                if test_file not in changes:
                    issues.append(ReviewIssue(
                        severity=IssueSeverity.MEDIUM,
                        file=file,
                        line=None,
                        message="缺少对应的测试文件",
                        suggestion=f"请添加 {test_file}",
                        rule="test_coverage",
                    ))

        return issues

    def _determine_verdict(self, issues: List[ReviewIssue]) -> ReviewVerdict:
        """判定审查结果"""
        high_count = len([i for i in issues if i.severity == IssueSeverity.HIGH])
        medium_count = len([i for i in issues if i.severity == IssueSeverity.MEDIUM])

        if high_count > 0:
            return ReviewVerdict.FAIL
        elif medium_count > 0:
            return ReviewVerdict.PASS_WITH_WARNINGS
        else:
            return ReviewVerdict.PASS

    def _find_line_number(self, diff: str, position: int) -> Optional[int]:
        """从 diff 位置找到行号"""
        # 简化实现
        lines = diff[:position].count("\n")
        return lines + 1
```

---

## 使用 code-reviewer Agent

### 集成 feature-dev:code-reviewer

```python
def review_with_agent(task_id: str, changes: Dict[str, str]) -> ReviewReport:
    """
    使用 code-reviewer agent 执行审查

    优势:
    - 更智能的代码理解
    - 上下文感知的建议
    - 自然语言解释
    """
    # 构建审查 prompt
    prompt = f"""
请审查以下代码变更 (任务 {task_id}):

## 变更文件
{format_changes(changes)}

## 审查要求
1. 检查代码质量 (可读性、命名、结构)
2. 检查逻辑正确性
3. 检查安全漏洞 (XSS, SQL 注入, 命令注入等)
4. 检查测试覆盖
5. 检查文档同步

## 输出格式
请按以下格式输出审查结果:

### 判定
PASS / PASS_WITH_WARNINGS / FAIL

### 问题列表
- [HIGH/MEDIUM/LOW] 文件:行号 - 问题描述
  建议: 修复建议

### 总结
简要总结审查结果
"""

    # 调用 code-reviewer agent
    result = Task(
        description=f"Review {task_id}",
        prompt=prompt,
        subagent_type="feature-dev:code-reviewer",
    )

    # 解析结果
    return parse_review_result(result)
```

---

## 审查报告格式

### YAML 格式

```yaml
# .claude/reviews/TASK-001-review.yaml
task_id: "TASK-001"
reviewer: "code-reviewer"
timestamp: "2026-01-21T10:30:00Z"

verdict: "pass_with_warnings"

issues:
  - severity: "high"
    file: "src/auth.py"
    line: 42
    message: "SQL 注入风险: 使用字符串拼接构建 SQL"
    suggestion: "使用参数化查询: cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))"
    rule: "security/sql-injection"

  - severity: "medium"
    file: "src/auth.py"
    line: 58
    message: "函数过长 (68 行 > 50 行限制)"
    suggestion: "拆分为多个小函数，每个函数专注单一职责"
    rule: "code-quality/function-length"

  - severity: "low"
    file: "src/auth.py"
    line: 12
    message: "变量命名不规范: 'x' 应使用描述性名称"
    suggestion: "重命名为 'user_count' 或类似描述性名称"
    rule: "naming/descriptive"

summary:
  high: 1
  medium: 1
  low: 1
  total: 3

execution_time: 12.5
```

### Markdown 格式 (用于显示)

```markdown
# 代码审查报告: TASK-001

**审查者**: code-reviewer
**时间**: 2026-01-21 10:30:00
**判定**: ⚠️ PASS_WITH_WARNINGS

## 问题列表

### 🔴 高严重度 (1)

1. **src/auth.py:42** - SQL 注入风险
   > 使用字符串拼接构建 SQL

   **建议**: 使用参数化查询

### 🟡 中严重度 (1)

1. **src/auth.py:58** - 函数过长
   > 68 行 > 50 行限制

   **建议**: 拆分为多个小函数

### 🟢 低严重度 (1)

1. **src/auth.py:12** - 变量命名不规范
   > 'x' 应使用描述性名称

## 总结

发现 1 个高严重度问题需要修复，1 个中严重度问题建议改进。
```

---

## 审查阈值配置

```yaml
# .claude/config.yml
review:
  # 阻止继续的阈值
  block_threshold: "high"  # high, medium, low

  # 警告阈值
  warn_threshold: "medium"

  # 跳过审查的文件模式
  skip_patterns:
    - "*.md"
    - "*.json"
    - "*.yaml"
    - "tests/fixtures/*"

  # 自定义规则
  custom_rules:
    - name: "no-console-log"
      pattern: "console\\.log"
      severity: "low"
      message: "生产代码中不应有 console.log"
```

---

## 审查结果处理

### PASS - 通过

```yaml
处理:
  - 记录审查报告
  - 继续下一任务
  - 无需用户干预
```

### PASS_WITH_WARNINGS - 警告通过

```yaml
处理:
  - 记录审查报告
  - 显示警告信息
  - 询问用户是否继续
  - 用户确认后继续
```

### FAIL - 不通过

```yaml
处理:
  - 记录审查报告
  - 显示问题列表
  - 返回当前任务修复
  - 修复后重新审查
```

---

## 与 4 选项完成流程集成

```
任务完成
    │
    ▼
代码审查
    │
    ├─ PASS ──────────────────────────────────┐
    │                                         │
    ├─ PASS_WITH_WARNINGS ────────────────────┤
    │     显示警告                             │
    │                                         │
    └─ FAIL ──────────────────────────────────┤
          显示问题                             │
                                              ▼
                                    显示 4 选项菜单
                                              │
                                    ┌─────────┼─────────┐
                                    │         │         │
                                    ▼         ▼         ▼
                              [1] 继续   [2] 修改   [3] 回退
                                    │         │         │
                                    ▼         ▼         ▼
                              下一任务   当前任务   重新开始
```

---

**Created**: 2026-01-21
**Part of**: enforcement-mechanism-redesign Phase 2.3

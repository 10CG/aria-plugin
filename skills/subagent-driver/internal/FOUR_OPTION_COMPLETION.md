# 4 选项完成流程

> **Subagent Driver v1.0.0** | Four-Option Completion Flow
> **Phase 2.4** | enforcement-mechanism-redesign

## Overview

4 选项完成流程是 SDD 的标准化任务完成机制，为用户提供清晰的下一步选择。

---

## 选项定义

```
┌─────────────────────────────────────────────────────────────┐
│                    4 选项完成流程                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  [1] 继续下一任务 (Continue)                                 │
│      → 当前任务满意，继续执行下一个任务                       │
│      → 启动新的 Fresh Subagent                              │
│                                                             │
│  [2] 修改当前任务 (Modify)                                   │
│      → 当前任务需要调整                                      │
│      → 在当前子代理中继续修改                                │
│                                                             │
│  [3] 回退并重做 (Rollback)                                   │
│      → 放弃当前变更，重新开始                                │
│      → git reset，启动新的 Fresh Subagent                   │
│                                                             │
│  [4] 暂停并保存 (Pause)                                      │
│      → 保存当前进度，稍后继续                                │
│      → 保存状态到 .claude/subagent-state/                   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Implementation

### Pseudo-Code

```python
from dataclasses import dataclass
from typing import Optional, List, Callable
from enum import Enum

class CompletionOption(Enum):
    CONTINUE = 1
    MODIFY = 2
    ROLLBACK = 3
    PAUSE = 4

@dataclass
class TaskCompletionContext:
    """任务完成上下文"""
    task_id: str
    changes: List[str]
    review_result: str  # pass, pass_with_warnings, fail
    review_issues: List[dict]
    next_task_id: Optional[str]
    session_id: str

@dataclass
class CompletionResult:
    """完成流程结果"""
    option: CompletionOption
    action_taken: str
    next_state: str


class FourOptionCompletionFlow:
    """4 选项完成流程"""

    def __init__(self, context: TaskCompletionContext):
        self.context = context

    def display_summary(self) -> str:
        """显示任务完成摘要"""
        summary = f"""
✅ 任务 {self.context.task_id} 完成

## 变更摘要
{self._format_changes()}

## 代码审查
{self._format_review()}

## 请选择下一步
"""
        return summary

    def display_options(self) -> str:
        """显示选项菜单"""
        options = []

        # 选项 1: 继续下一任务
        if self.context.next_task_id:
            options.append(f"[1] 继续下一任务 ({self.context.next_task_id})")
        else:
            options.append("[1] 完成所有任务 (无更多任务)")

        # 选项 2: 修改当前任务
        options.append(f"[2] 修改当前任务 (继续调整 {self.context.task_id})")

        # 选项 3: 回退并重做
        options.append("[3] 回退并重做 (放弃变更，重新开始)")

        # 选项 4: 暂停并保存
        options.append("[4] 暂停并保存 (保存进度，稍后继续)")

        return "\n".join(options) + "\n\n选择 [1/2/3/4]: "

    def execute_option(self, option: CompletionOption) -> CompletionResult:
        """执行选择的选项"""
        handlers = {
            CompletionOption.CONTINUE: self._handle_continue,
            CompletionOption.MODIFY: self._handle_modify,
            CompletionOption.ROLLBACK: self._handle_rollback,
            CompletionOption.PAUSE: self._handle_pause,
        }

        handler = handlers.get(option)
        if handler:
            return handler()
        else:
            raise ValueError(f"Unknown option: {option}")

    def _handle_continue(self) -> CompletionResult:
        """处理: 继续下一任务"""
        if self.context.next_task_id:
            # 启动下一个 Fresh Subagent
            return CompletionResult(
                option=CompletionOption.CONTINUE,
                action_taken=f"启动任务 {self.context.next_task_id}",
                next_state="in_progress",
            )
        else:
            # 所有任务完成
            return CompletionResult(
                option=CompletionOption.CONTINUE,
                action_taken="所有任务已完成",
                next_state="completed",
            )

    def _handle_modify(self) -> CompletionResult:
        """处理: 修改当前任务"""
        return CompletionResult(
            option=CompletionOption.MODIFY,
            action_taken=f"继续修改 {self.context.task_id}",
            next_state="modifying",
        )

    def _handle_rollback(self) -> CompletionResult:
        """处理: 回退并重做"""
        # 执行 git reset
        self._git_reset()

        return CompletionResult(
            option=CompletionOption.ROLLBACK,
            action_taken=f"回退 {self.context.task_id}，准备重做",
            next_state="rollback",
        )

    def _handle_pause(self) -> CompletionResult:
        """处理: 暂停并保存"""
        # 保存状态
        state_file = self._save_state()

        return CompletionResult(
            option=CompletionOption.PAUSE,
            action_taken=f"状态已保存到 {state_file}",
            next_state="paused",
        )

    def _format_changes(self) -> str:
        """格式化变更列表"""
        if not self.context.changes:
            return "  (无变更)"

        lines = []
        for change in self.context.changes:
            lines.append(f"  - {change}")
        return "\n".join(lines)

    def _format_review(self) -> str:
        """格式化审查结果"""
        result = self.context.review_result

        if result == "pass":
            icon = "✅"
            text = "通过"
        elif result == "pass_with_warnings":
            icon = "⚠️"
            text = "通过 (有警告)"
        else:
            icon = "❌"
            text = "未通过"

        issues = self.context.review_issues
        high = len([i for i in issues if i.get("severity") == "high"])
        medium = len([i for i in issues if i.get("severity") == "medium"])
        low = len([i for i in issues if i.get("severity") == "low"])

        return f"{icon} {text} ({high} 高, {medium} 中, {low} 低)"

    def _git_reset(self):
        """执行 git reset"""
        import subprocess
        subprocess.run(
            ["git", "reset", "--hard", "HEAD~1"],
            check=True,
        )

    def _save_state(self) -> str:
        """保存状态到文件"""
        import yaml
        import os

        state_dir = ".claude/subagent-state"
        os.makedirs(state_dir, exist_ok=True)

        state_file = f"{state_dir}/{self.context.session_id}.yaml"

        state = {
            "session_id": self.context.session_id,
            "current_task": self.context.task_id,
            "next_task": self.context.next_task_id,
            "status": "paused",
            "changes": self.context.changes,
        }

        with open(state_file, "w") as f:
            yaml.dump(state, f)

        return state_file
```

---

## 交互流程

### 标准流程

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  ✅ 任务 TASK-001 完成                                       │
│                                                             │
│  变更摘要:                                                   │
│    - 修改: src/auth.py (+42, -10)                           │
│    - 新增: tests/test_auth.py (+85)                         │
│    - 修改: docs/api.md (+15)                                │
│                                                             │
│  代码审查: ✅ 通过 (0 高, 1 中, 2 低)                         │
│                                                             │
│  请选择下一步:                                               │
│    [1] 继续下一任务 (TASK-002: 实现用户注册)                  │
│    [2] 修改当前任务 (继续调整 TASK-001)                       │
│    [3] 回退并重做 (放弃变更，重新开始)                        │
│    [4] 暂停并保存 (保存进度，稍后继续)                        │
│                                                             │
│  选择 [1/2/3/4]: _                                          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 审查失败流程

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  ⚠️ 任务 TASK-001 完成 (需要修复)                            │
│                                                             │
│  变更摘要:                                                   │
│    - 修改: src/auth.py (+42, -10)                           │
│                                                             │
│  代码审查: ❌ 未通过 (1 高, 0 中, 0 低)                       │
│                                                             │
│  问题列表:                                                   │
│    🔴 src/auth.py:42 - SQL 注入风险                          │
│       建议: 使用参数化查询                                   │
│                                                             │
│  请选择下一步:                                               │
│    [1] 继续下一任务 (不推荐 - 有未修复的高严重度问题)          │
│    [2] 修改当前任务 (推荐 - 修复问题后继续)                   │
│    [3] 回退并重做 (放弃变更，重新开始)                        │
│    [4] 暂停并保存 (保存进度，稍后继续)                        │
│                                                             │
│  选择 [1/2/3/4]: _                                          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 最后一个任务流程

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  ✅ 任务 TASK-003 完成 (最后一个任务)                         │
│                                                             │
│  变更摘要:                                                   │
│    - 修改: src/api.py (+20, -5)                             │
│                                                             │
│  代码审查: ✅ 通过 (0 高, 0 中, 1 低)                         │
│                                                             │
│  请选择下一步:                                               │
│    [1] 完成所有任务 (进入 Phase C 集成)                       │
│    [2] 修改当前任务 (继续调整 TASK-003)                       │
│    [3] 回退并重做 (放弃变更，重新开始)                        │
│    [4] 暂停并保存 (保存进度，稍后继续)                        │
│                                                             │
│  选择 [1/2/3/4]: _                                          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 选项详细说明

### 选项 1: 继续下一任务

```yaml
触发条件:
  - 用户对当前任务满意
  - 代码审查通过或用户接受警告

执行动作:
  1. 标记当前任务为 completed
  2. 更新状态文件
  3. 启动新的 Fresh Subagent
  4. 传递下一任务定义

后续状态:
  - 当前任务: completed
  - 下一任务: in_progress
```

### 选项 2: 修改当前任务

```yaml
触发条件:
  - 用户发现问题需要修复
  - 代码审查发现问题
  - 需要改进实现

执行动作:
  1. 保持当前子代理活跃
  2. 显示修改提示
  3. 等待用户输入修改指令
  4. 修改完成后重新触发审查

后续状态:
  - 当前任务: modifying
  - 子代理: 继续运行
```

### 选项 3: 回退并重做

```yaml
触发条件:
  - 当前方向错误
  - 需要完全重新开始
  - 变更不可接受

执行动作:
  1. 执行 git reset --hard HEAD~1
  2. 终止当前子代理
  3. 启动新的 Fresh Subagent
  4. 重新执行当前任务

后续状态:
  - 当前任务: pending (重置)
  - 变更: 已撤销
```

### 选项 4: 暂停并保存

```yaml
触发条件:
  - 需要中断工作
  - 等待外部输入
  - 时间不足

执行动作:
  1. 保存当前状态到文件
  2. 记录变更列表
  3. 记录下一任务信息
  4. 输出恢复命令

后续状态:
  - 会话: paused
  - 状态文件: .claude/subagent-state/{session_id}.yaml

恢复命令:
  subagent-driver --resume {session_id}
```

---

## 状态保存格式

```yaml
# .claude/subagent-state/sess-20260121-001.yaml
session_id: "sess-20260121-001"
paused_at: "2026-01-21T11:30:00Z"
status: "paused"

current_task:
  id: "TASK-002"
  status: "in_progress"
  changes:
    - "src/user.py"
    - "tests/test_user.py"

completed_tasks:
  - id: "TASK-001"
    status: "completed"
    review_result: "pass"

pending_tasks:
  - id: "TASK-003"
  - id: "TASK-004"

resume_info:
  branch: "feature/backend/TASK-001-user-auth"
  worktree_path: ".git/worktrees/TASK-001-user-auth"
  isolation_level: "L2"
```

---

## 与 AskUserQuestion 集成

```python
def prompt_user_choice(context: TaskCompletionContext) -> CompletionOption:
    """
    使用 AskUserQuestion 工具获取用户选择
    """
    flow = FourOptionCompletionFlow(context)

    # 构建问题
    question = {
        "question": f"任务 {context.task_id} 已完成，请选择下一步操作",
        "header": "下一步",
        "options": [
            {
                "label": f"继续 ({context.next_task_id or '完成'})",
                "description": "继续执行下一个任务或完成所有任务",
            },
            {
                "label": "修改",
                "description": "继续调整当前任务",
            },
            {
                "label": "回退",
                "description": "放弃变更，重新开始",
            },
            {
                "label": "暂停",
                "description": "保存进度，稍后继续",
            },
        ],
        "multiSelect": False,
    }

    # 调用 AskUserQuestion
    result = AskUserQuestion(questions=[question])

    # 解析结果
    choice_map = {
        "继续": CompletionOption.CONTINUE,
        "修改": CompletionOption.MODIFY,
        "回退": CompletionOption.ROLLBACK,
        "暂停": CompletionOption.PAUSE,
    }

    return choice_map.get(result, CompletionOption.CONTINUE)
```

---

**Created**: 2026-01-21
**Part of**: enforcement-mechanism-redesign Phase 2.4

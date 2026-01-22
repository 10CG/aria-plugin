# Fresh Subagent 启动逻辑

> **Subagent Driver v1.0.0** | Fresh Subagent 启动机制
> **Phase 2.2** | enforcement-mechanism-redesign

## Overview

Fresh Subagent 是 Subagent-Driven Development (SDD) 的核心机制，确保每个任务在干净的上下文中执行。

---

## 启动流程

```
┌─────────────────────────────────────────────────────────────┐
│                  Fresh Subagent 启动流程                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. 接收任务定义                                             │
│     ├─ task_id, description, files                         │
│     └─ acceptance_criteria, dependencies                   │
│                                                             │
│  2. 准备启动上下文                                           │
│     ├─ 读取 CLAUDE.md (项目配置)                            │
│     ├─ 读取任务相关文件                                      │
│     ├─ 构建任务 prompt                                      │
│     └─ 不加载历史对话 (关键!)                                │
│                                                             │
│  3. 选择隔离级别                                             │
│     ├─ L1: 对话隔离 (默认)                                  │
│     ├─ L2: 对话 + 文件隔离 (Worktree)                       │
│     └─ L3: 完全隔离 (独立进程)                              │
│                                                             │
│  4. 启动子代理                                               │
│     ├─ 创建新的 Agent 实例                                  │
│     ├─ 传递任务上下文                                        │
│     └─ 设置超时和资源限制                                    │
│                                                             │
│  5. 监控执行                                                 │
│     ├─ 记录执行日志                                          │
│     ├─ 收集变更文件                                          │
│     └─ 检测完成/失败状态                                     │
│                                                             │
│  6. 任务完成处理                                             │
│     ├─ 触发代码审查                                          │
│     ├─ 显示 4 选项菜单                                       │
│     └─ 等待用户选择                                          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Implementation

### Pseudo-Code

```python
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from enum import Enum
import uuid
import time

class IsolationLevel(Enum):
    L1 = "dialogue"      # 对话隔离
    L2 = "filesystem"    # 对话 + 文件隔离
    L3 = "full"          # 完全隔离

class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"

@dataclass
class TaskDefinition:
    """任务定义"""
    task_id: str
    description: str
    files: List[str]
    acceptance_criteria: List[str]
    dependencies: List[str] = None
    estimated_complexity: str = "medium"  # low, medium, high

@dataclass
class SubagentContext:
    """子代理上下文"""
    task: TaskDefinition
    project_config: str  # CLAUDE.md 内容
    relevant_files: Dict[str, str]  # 文件路径 -> 内容
    worktree_path: Optional[str] = None

@dataclass
class SubagentResult:
    """子代理执行结果"""
    task_id: str
    status: TaskStatus
    changes: List[str]
    execution_time: float
    error: Optional[str] = None


class FreshSubagentLauncher:
    """Fresh Subagent 启动器"""

    def __init__(
        self,
        project_root: str,
        isolation_level: IsolationLevel = IsolationLevel.L1
    ):
        self.project_root = project_root
        self.isolation_level = isolation_level
        self.active_subagents: Dict[str, Any] = {}

    def launch(self, task: TaskDefinition) -> str:
        """
        启动 Fresh Subagent

        Args:
            task: 任务定义

        Returns:
            subagent_id: 子代理 ID
        """
        subagent_id = f"sub-{uuid.uuid4().hex[:8]}"

        # 1. 准备上下文
        context = self._prepare_context(task)

        # 2. 根据隔离级别准备环境
        if self.isolation_level == IsolationLevel.L2:
            context.worktree_path = self._setup_worktree(task.task_id)
        elif self.isolation_level == IsolationLevel.L3:
            context.worktree_path = self._setup_isolated_process(task.task_id)

        # 3. 构建启动 prompt
        prompt = self._build_launch_prompt(context)

        # 4. 启动子代理
        subagent = self._create_subagent(subagent_id, prompt)

        # 5. 注册活跃子代理
        self.active_subagents[subagent_id] = {
            "task": task,
            "context": context,
            "subagent": subagent,
            "started_at": time.time(),
            "status": TaskStatus.IN_PROGRESS,
        }

        return subagent_id

    def _prepare_context(self, task: TaskDefinition) -> SubagentContext:
        """准备子代理上下文"""
        # 读取项目配置
        project_config = self._read_file("CLAUDE.md")

        # 读取任务相关文件
        relevant_files = {}
        for file_path in task.files:
            content = self._read_file(file_path)
            if content:
                relevant_files[file_path] = content

        return SubagentContext(
            task=task,
            project_config=project_config,
            relevant_files=relevant_files,
        )

    def _build_launch_prompt(self, context: SubagentContext) -> str:
        """构建启动 prompt"""
        prompt = f"""# Fresh Subagent Task

## 任务信息
- **Task ID**: {context.task.task_id}
- **描述**: {context.task.description}

## 验收标准
{self._format_criteria(context.task.acceptance_criteria)}

## 相关文件
{self._format_files(context.relevant_files)}

## 项目配置
{context.project_config}

## 执行要求
1. 专注于当前任务，不要处理其他任务
2. 完成后报告变更的文件列表
3. 确保所有验收标准都满足
4. 如果遇到阻塞问题，立即报告

## 开始执行
请开始执行任务 {context.task.task_id}。
"""
        return prompt

    def _setup_worktree(self, task_id: str) -> str:
        """设置 Worktree 隔离环境"""
        worktree_path = f".git/worktrees/{task_id}"
        # 调用 git worktree add
        # ...
        return worktree_path

    def _setup_isolated_process(self, task_id: str) -> str:
        """设置完全隔离环境"""
        # 创建独立进程
        # 设置资源限制
        # ...
        return f"/tmp/subagent-{task_id}"

    def _create_subagent(self, subagent_id: str, prompt: str) -> Any:
        """创建子代理实例"""
        # 使用 Claude Code Task tool 创建子代理
        # 关键: 不传递历史对话
        return {
            "id": subagent_id,
            "prompt": prompt,
            "created_at": time.time(),
        }

    def _read_file(self, path: str) -> Optional[str]:
        """读取文件内容"""
        try:
            with open(f"{self.project_root}/{path}", "r") as f:
                return f.read()
        except:
            return None

    def _format_criteria(self, criteria: List[str]) -> str:
        """格式化验收标准"""
        return "\n".join(f"- [ ] {c}" for c in criteria)

    def _format_files(self, files: Dict[str, str]) -> str:
        """格式化文件列表"""
        result = []
        for path, content in files.items():
            result.append(f"### {path}\n```\n{content[:500]}...\n```")
        return "\n".join(result)

    def get_result(self, subagent_id: str) -> SubagentResult:
        """获取子代理执行结果"""
        if subagent_id not in self.active_subagents:
            raise ValueError(f"Unknown subagent: {subagent_id}")

        info = self.active_subagents[subagent_id]
        # 收集执行结果
        # ...
        return SubagentResult(
            task_id=info["task"].task_id,
            status=info["status"],
            changes=[],  # 从 git diff 获取
            execution_time=time.time() - info["started_at"],
        )

    def terminate(self, subagent_id: str):
        """终止子代理"""
        if subagent_id in self.active_subagents:
            info = self.active_subagents[subagent_id]
            # 清理资源
            if info["context"].worktree_path:
                # git worktree remove
                pass
            del self.active_subagents[subagent_id]
```

---

## Claude Code Task Tool 集成

### 使用 Task Tool 启动子代理

```python
def launch_with_task_tool(task: TaskDefinition) -> str:
    """
    使用 Claude Code Task tool 启动 Fresh Subagent

    关键点:
    1. 使用 general-purpose subagent_type
    2. 不传递 resume 参数 (确保 fresh)
    3. 构建完整的任务 prompt
    """
    prompt = f"""
执行任务: {task.task_id}

## 任务描述
{task.description}

## 验收标准
{chr(10).join(f'- {c}' for c in task.acceptance_criteria)}

## 相关文件
{', '.join(task.files)}

## 执行要求
1. 阅读相关文件，理解当前实现
2. 按照验收标准完成任务
3. 完成后列出所有变更的文件
4. 确保代码质量和测试覆盖

开始执行。
"""

    # 调用 Task tool
    # 注意: 不使用 resume 参数，确保是 fresh subagent
    result = Task(
        description=f"Execute {task.task_id}",
        prompt=prompt,
        subagent_type="general-purpose",
        # 不设置 resume，确保 fresh
    )

    return result
```

---

## 隔离级别实现

### L1 - 对话隔离

```yaml
L1 实现:
  方法: 使用 Task tool 创建新子代理
  特点:
    - 不传递历史对话
    - 共享文件系统
    - 最低开销

  验证:
    - 检查子代理无法访问主 Agent 变量
    - 检查子代理无法引用之前的对话
```

### L2 - 文件隔离

```yaml
L2 实现:
  方法: L1 + Git Worktree
  特点:
    - 对话隔离
    - 独立工作目录
    - 文件变更不影响主目录

  流程:
    1. 创建 worktree: git worktree add {path} {branch}
    2. 在 worktree 中启动子代理
    3. 任务完成后合并变更
    4. 清理 worktree

  验证:
    - 检查 pwd 在 worktree 目录
    - 检查主目录文件未变更
```

### L3 - 完全隔离

```yaml
L3 实现:
  方法: L2 + 独立进程
  特点:
    - 对话隔离
    - 文件隔离
    - 进程隔离
    - 资源限制

  流程:
    1. 创建 worktree
    2. 启动独立 Claude Code 进程
    3. 通过 IPC 通信
    4. 任务完成后收集结果
    5. 清理进程和 worktree

  验证:
    - 检查 PID 不同
    - 检查资源使用独立
```

---

## 超时和资源限制

```yaml
默认限制:
  timeout: 30 分钟
  max_turns: 50
  max_file_edits: 20

按复杂度调整:
  low:
    timeout: 15 分钟
    max_turns: 20
  medium:
    timeout: 30 分钟
    max_turns: 50
  high:
    timeout: 60 分钟
    max_turns: 100
```

---

## 错误处理

| 错误 | 处理方式 |
|------|---------|
| 子代理超时 | 终止并报告，提供部分结果 |
| 子代理崩溃 | 记录日志，清理资源，报告失败 |
| Worktree 创建失败 | 降级到 L1 隔离 |
| 文件读取失败 | 警告并继续，标记缺失文件 |

---

## 日志记录

```yaml
日志格式:
  timestamp: "2026-01-21T10:30:00Z"
  subagent_id: "sub-abc12345"
  task_id: "TASK-001"
  event: "started" | "completed" | "failed" | "timeout"
  details:
    isolation_level: "L1"
    execution_time: 1234.5
    changes: ["file1.py", "file2.py"]
    error: null

日志位置: .claude/logs/subagent-{date}.log
```

---

**Created**: 2026-01-21
**Part of**: enforcement-mechanism-redesign Phase 2.2

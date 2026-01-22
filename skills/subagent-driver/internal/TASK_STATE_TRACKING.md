# 任务状态追踪

> **Subagent Driver v1.0.0** | Task State Tracking
> **Phase 2.6** | enforcement-mechanism-redesign

## Overview

任务状态追踪系统管理 SDD 会话中所有任务的执行状态，支持暂停、恢复和状态查询。

---

## 状态定义

```
┌─────────────────────────────────────────────────────────────┐
│                      任务状态流转                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  pending ──────────────────────────────────────────────┐    │
│     │                                                  │    │
│     ▼                                                  │    │
│  in_progress ──────────────────────────────────────┐   │    │
│     │                                              │   │    │
│     ├─────────────────────┐                        │   │    │
│     │                     │                        │   │    │
│     ▼                     ▼                        ▼   ▼    │
│  reviewing ───────► completed              failed  paused   │
│     │                     │                   │      │      │
│     │                     │                   │      │      │
│     └─────────────────────┴───────────────────┴──────┘      │
│                           │                                 │
│                           ▼                                 │
│                      (可恢复)                               │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 状态说明

| 状态 | 说明 | 可转换到 |
|------|------|---------|
| `pending` | 等待执行 | `in_progress` |
| `in_progress` | 正在执行 | `reviewing`, `failed`, `paused` |
| `reviewing` | 代码审查中 | `completed`, `in_progress` |
| `completed` | 已完成 | - |
| `failed` | 执行失败 | `pending` (重试) |
| `paused` | 已暂停 | `in_progress` (恢复) |

---

## Implementation

### Pseudo-Code

```python
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from enum import Enum
from datetime import datetime
import yaml
import os

class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"

@dataclass
class TaskState:
    """单个任务状态"""
    task_id: str
    status: TaskStatus
    subagent_id: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    review_result: Optional[str] = None
    changes: List[str] = field(default_factory=list)
    error: Optional[str] = None

@dataclass
class SessionState:
    """会话状态"""
    session_id: str
    started_at: str
    status: str  # active, paused, completed
    isolation_level: str
    branch_name: Optional[str] = None
    worktree_path: Optional[str] = None
    tasks: List[TaskState] = field(default_factory=list)
    current_task_index: int = 0

    @property
    def current_task(self) -> Optional[TaskState]:
        if 0 <= self.current_task_index < len(self.tasks):
            return self.tasks[self.current_task_index]
        return None

    @property
    def next_task(self) -> Optional[TaskState]:
        next_index = self.current_task_index + 1
        if next_index < len(self.tasks):
            return self.tasks[next_index]
        return None

    @property
    def completed_count(self) -> int:
        return len([t for t in self.tasks if t.status == TaskStatus.COMPLETED])

    @property
    def total_count(self) -> int:
        return len(self.tasks)


class TaskStateTracker:
    """任务状态追踪器"""

    STATE_DIR = ".claude/subagent-state"

    def __init__(self, session_id: str = None):
        self.session_id = session_id or self._generate_session_id()
        self.state: Optional[SessionState] = None
        self._ensure_state_dir()

    def _generate_session_id(self) -> str:
        """生成会话 ID"""
        from datetime import datetime
        return f"sess-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    def _ensure_state_dir(self):
        """确保状态目录存在"""
        os.makedirs(self.STATE_DIR, exist_ok=True)

    def _state_file_path(self) -> str:
        """获取状态文件路径"""
        return f"{self.STATE_DIR}/{self.session_id}.yaml"

    def initialize(
        self,
        tasks: List[str],
        isolation_level: str,
        branch_name: str = None,
        worktree_path: str = None,
    ):
        """
        初始化会话状态

        Args:
            tasks: 任务 ID 列表
            isolation_level: 隔离级别
            branch_name: 分支名
            worktree_path: worktree 路径
        """
        task_states = [
            TaskState(task_id=task_id, status=TaskStatus.PENDING)
            for task_id in tasks
        ]

        self.state = SessionState(
            session_id=self.session_id,
            started_at=datetime.now().isoformat(),
            status="active",
            isolation_level=isolation_level,
            branch_name=branch_name,
            worktree_path=worktree_path,
            tasks=task_states,
            current_task_index=0,
        )

        self._save()

    def start_task(self, task_id: str, subagent_id: str):
        """开始任务"""
        task = self._find_task(task_id)
        if task:
            task.status = TaskStatus.IN_PROGRESS
            task.subagent_id = subagent_id
            task.started_at = datetime.now().isoformat()
            self._save()

    def start_review(self, task_id: str):
        """开始审查"""
        task = self._find_task(task_id)
        if task:
            task.status = TaskStatus.REVIEWING
            self._save()

    def complete_task(
        self,
        task_id: str,
        review_result: str,
        changes: List[str],
    ):
        """完成任务"""
        task = self._find_task(task_id)
        if task:
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now().isoformat()
            task.review_result = review_result
            task.changes = changes
            self.state.current_task_index += 1
            self._save()

    def fail_task(self, task_id: str, error: str):
        """任务失败"""
        task = self._find_task(task_id)
        if task:
            task.status = TaskStatus.FAILED
            task.error = error
            self._save()

    def pause_session(self):
        """暂停会话"""
        self.state.status = "paused"
        current = self.state.current_task
        if current:
            current.status = TaskStatus.PAUSED
        self._save()

    def resume_session(self) -> SessionState:
        """恢复会话"""
        self._load()
        self.state.status = "active"
        current = self.state.current_task
        if current and current.status == TaskStatus.PAUSED:
            current.status = TaskStatus.IN_PROGRESS
        self._save()
        return self.state

    def get_status(self) -> Dict:
        """获取当前状态摘要"""
        return {
            "session_id": self.session_id,
            "status": self.state.status,
            "completed": self.state.completed_count,
            "total": self.state.total_count,
            "current_task": self.state.current_task.task_id if self.state.current_task else None,
            "next_task": self.state.next_task.task_id if self.state.next_task else None,
        }

    def _find_task(self, task_id: str) -> Optional[TaskState]:
        """查找任务"""
        for task in self.state.tasks:
            if task.task_id == task_id:
                return task
        return None

    def _save(self):
        """保存状态到文件"""
        state_dict = self._state_to_dict()
        with open(self._state_file_path(), "w") as f:
            yaml.dump(state_dict, f, default_flow_style=False, allow_unicode=True)

    def _load(self):
        """从文件加载状态"""
        with open(self._state_file_path(), "r") as f:
            state_dict = yaml.safe_load(f)
        self.state = self._dict_to_state(state_dict)

    def _state_to_dict(self) -> Dict:
        """状态转字典"""
        return {
            "session_id": self.state.session_id,
            "started_at": self.state.started_at,
            "status": self.state.status,
            "isolation_level": self.state.isolation_level,
            "branch_name": self.state.branch_name,
            "worktree_path": self.state.worktree_path,
            "current_task_index": self.state.current_task_index,
            "tasks": [
                {
                    "task_id": t.task_id,
                    "status": t.status.value,
                    "subagent_id": t.subagent_id,
                    "started_at": t.started_at,
                    "completed_at": t.completed_at,
                    "review_result": t.review_result,
                    "changes": t.changes,
                    "error": t.error,
                }
                for t in self.state.tasks
            ],
        }

    def _dict_to_state(self, d: Dict) -> SessionState:
        """字典转状态"""
        tasks = [
            TaskState(
                task_id=t["task_id"],
                status=TaskStatus(t["status"]),
                subagent_id=t.get("subagent_id"),
                started_at=t.get("started_at"),
                completed_at=t.get("completed_at"),
                review_result=t.get("review_result"),
                changes=t.get("changes", []),
                error=t.get("error"),
            )
            for t in d["tasks"]
        ]

        return SessionState(
            session_id=d["session_id"],
            started_at=d["started_at"],
            status=d["status"],
            isolation_level=d["isolation_level"],
            branch_name=d.get("branch_name"),
            worktree_path=d.get("worktree_path"),
            tasks=tasks,
            current_task_index=d.get("current_task_index", 0),
        )

    @classmethod
    def list_sessions(cls) -> List[Dict]:
        """列出所有会话"""
        sessions = []
        if os.path.exists(cls.STATE_DIR):
            for filename in os.listdir(cls.STATE_DIR):
                if filename.endswith(".yaml"):
                    session_id = filename[:-5]
                    tracker = cls(session_id)
                    tracker._load()
                    sessions.append(tracker.get_status())
        return sessions
```

---

## 状态文件格式

```yaml
# .claude/subagent-state/sess-20260121-093000.yaml
session_id: "sess-20260121-093000"
started_at: "2026-01-21T09:30:00"
status: "active"  # active, paused, completed
isolation_level: "L2"
branch_name: "feature/backend/TASK-001-user-auth"
worktree_path: ".git/worktrees/TASK-001-user-auth"
current_task_index: 1

tasks:
  - task_id: "TASK-001"
    status: "completed"
    subagent_id: "sub-abc12345"
    started_at: "2026-01-21T09:30:00"
    completed_at: "2026-01-21T10:00:00"
    review_result: "pass"
    changes:
      - "src/auth.py"
      - "tests/test_auth.py"
    error: null

  - task_id: "TASK-002"
    status: "in_progress"
    subagent_id: "sub-def67890"
    started_at: "2026-01-21T10:05:00"
    completed_at: null
    review_result: null
    changes: []
    error: null

  - task_id: "TASK-003"
    status: "pending"
    subagent_id: null
    started_at: null
    completed_at: null
    review_result: null
    changes: []
    error: null
```

---

## 状态查询命令

```bash
# 列出所有会话
subagent-driver --list-sessions

# 查看特定会话状态
subagent-driver --status sess-20260121-093000

# 恢复暂停的会话
subagent-driver --resume sess-20260121-093000

# 清理已完成的会话
subagent-driver --cleanup --older-than 7d
```

---

## 状态显示格式

```
┌─────────────────────────────────────────────────────────────┐
│  会话状态: sess-20260121-093000                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  状态: 🟢 活跃                                               │
│  进度: 1/3 (33%)                                            │
│  隔离级别: L2 (文件隔离)                                     │
│  分支: feature/backend/TASK-001-user-auth                   │
│                                                             │
│  任务列表:                                                   │
│    ✅ TASK-001 - 完成 (审查通过)                             │
│    🔄 TASK-002 - 进行中                                      │
│    ⏳ TASK-003 - 等待                                        │
│                                                             │
│  当前任务: TASK-002                                          │
│  下一任务: TASK-003                                          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 与其他组件集成

### 与 Fresh Subagent Launcher 集成

```python
def launch_task_with_tracking(
    tracker: TaskStateTracker,
    launcher: FreshSubagentLauncher,
    task: TaskDefinition,
):
    """启动任务并追踪状态"""
    # 启动子代理
    subagent_id = launcher.launch(task)

    # 更新状态
    tracker.start_task(task.task_id, subagent_id)

    # 等待完成
    result = launcher.get_result(subagent_id)

    # 更新状态
    if result.status == TaskStatus.COMPLETED:
        tracker.complete_task(
            task.task_id,
            review_result="pending",
            changes=result.changes,
        )
    else:
        tracker.fail_task(task.task_id, result.error)
```

### 与 4 选项完成流程集成

```python
def handle_completion_option(
    tracker: TaskStateTracker,
    option: CompletionOption,
):
    """处理完成选项并更新状态"""
    if option == CompletionOption.CONTINUE:
        # 状态已在 complete_task 中更新
        pass
    elif option == CompletionOption.MODIFY:
        # 保持当前状态
        pass
    elif option == CompletionOption.ROLLBACK:
        # 重置当前任务状态
        current = tracker.state.current_task
        if current:
            current.status = TaskStatus.PENDING
            current.subagent_id = None
            current.started_at = None
            tracker._save()
    elif option == CompletionOption.PAUSE:
        tracker.pause_session()
```

---

**Created**: 2026-01-21
**Part of**: enforcement-mechanism-redesign Phase 2.6

# Worktree 清理决策逻辑

> **Branch Finisher v1.0.0** | Worktree Cleanup Decision
> **Phase 3.4** | enforcement-mechanism-redesign

## Overview

Worktree 清理决策逻辑根据用户选择和上下文智能决定是否清理 worktree。

---

## 清理决策矩阵

```
┌─────────────────────────────────────────────────────────────┐
│                    Worktree 清理决策矩阵                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  完成选项          │ 默认清理? │ 可覆盖? │ 原因            │
│  ─────────────────┼───────────┼─────────┼─────────────────│
│  [1] 提交并创建PR │ ✅ 是     │ ✅ 是   │ 开发完成        │
│  [2] 继续修改     │ ❌ 否     │ ❌ 否   │ 还需继续        │
│  [3] 放弃变更     │ ✅ 是     │ ❌ 否   │ 变更已撤销      │
│  [4] 暂停保存     │ ❌ 否     │ ✅ 是   │ 稍后可能恢复    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Implementation

### Pseudo-Code

```python
from dataclasses import dataclass
from typing import Optional
from enum import Enum
import subprocess
import os
import shutil

class CleanupDecision(Enum):
    CLEANUP_NOW = "cleanup_now"
    KEEP = "keep"
    DEFER = "defer"

class CompletionOption(Enum):
    COMMIT_AND_PR = 1
    CONTINUE_EDITING = 2
    DISCARD_CHANGES = 3
    PAUSE_AND_SAVE = 4

@dataclass
class WorktreeInfo:
    """Worktree 信息"""
    path: str
    branch: str
    size_mb: float
    created_at: str
    is_current: bool

@dataclass
class CleanupResult:
    """清理结果"""
    success: bool
    message: str
    worktree_path: Optional[str] = None
    branch_deleted: bool = False


class WorktreeCleanupDecisionMaker:
    """Worktree 清理决策器"""

    def __init__(self, project_root: str):
        self.project_root = project_root

    def decide(
        self,
        completion_option: CompletionOption,
        worktree_path: str,
        user_preference: Optional[CleanupDecision] = None,
    ) -> CleanupDecision:
        """
        决定是否清理 worktree

        Args:
            completion_option: 用户选择的完成选项
            worktree_path: worktree 路径
            user_preference: 用户偏好 (可覆盖默认)

        Returns:
            CleanupDecision: 清理决策
        """
        # 默认决策规则
        default_decisions = {
            CompletionOption.COMMIT_AND_PR: CleanupDecision.CLEANUP_NOW,
            CompletionOption.CONTINUE_EDITING: CleanupDecision.KEEP,
            CompletionOption.DISCARD_CHANGES: CleanupDecision.CLEANUP_NOW,
            CompletionOption.PAUSE_AND_SAVE: CleanupDecision.KEEP,
        }

        default = default_decisions.get(completion_option, CleanupDecision.KEEP)

        # 用户偏好可以覆盖某些选项
        if user_preference:
            # 继续修改不能覆盖为清理
            if completion_option == CompletionOption.CONTINUE_EDITING:
                return CleanupDecision.KEEP

            # 放弃变更必须清理
            if completion_option == CompletionOption.DISCARD_CHANGES:
                return CleanupDecision.CLEANUP_NOW

            return user_preference

        return default

    def get_worktree_info(self, worktree_path: str) -> Optional[WorktreeInfo]:
        """获取 worktree 信息"""
        if not os.path.exists(worktree_path):
            return None

        # 获取分支信息
        try:
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True,
                text=True,
                cwd=worktree_path,
            )
            branch = result.stdout.strip()
        except:
            branch = "unknown"

        # 获取大小
        size_mb = self._get_directory_size(worktree_path) / (1024 * 1024)

        # 检查是否是当前目录
        is_current = os.path.realpath(os.getcwd()) == os.path.realpath(worktree_path)

        return WorktreeInfo(
            path=worktree_path,
            branch=branch,
            size_mb=size_mb,
            created_at="",  # 需要从 git 获取
            is_current=is_current,
        )

    def _get_directory_size(self, path: str) -> int:
        """获取目录大小"""
        total = 0
        for dirpath, dirnames, filenames in os.walk(path):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                try:
                    total += os.path.getsize(filepath)
                except:
                    pass
        return total


class WorktreeCleaner:
    """Worktree 清理器"""

    def __init__(self, project_root: str):
        self.project_root = project_root

    def cleanup(
        self,
        worktree_path: str,
        delete_branch: bool = False,
        force: bool = False,
    ) -> CleanupResult:
        """
        清理 worktree

        Args:
            worktree_path: worktree 路径
            delete_branch: 是否同时删除分支
            force: 是否强制清理

        Returns:
            CleanupResult: 清理结果
        """
        # 1. 检查是否在 worktree 中
        if self._is_in_worktree(worktree_path):
            return CleanupResult(
                success=False,
                message="当前在 worktree 目录中，请先切换到主目录",
                worktree_path=worktree_path,
            )

        # 2. 获取分支名 (在删除前)
        branch_name = self._get_worktree_branch(worktree_path)

        # 3. 删除 worktree
        try:
            cmd = ["git", "worktree", "remove", worktree_path]
            if force:
                cmd.append("--force")

            subprocess.run(
                cmd,
                check=True,
                cwd=self.project_root,
            )
        except subprocess.CalledProcessError as e:
            return CleanupResult(
                success=False,
                message=f"删除 worktree 失败: {e}",
                worktree_path=worktree_path,
            )

        # 4. 清理过期记录
        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=self.project_root,
        )

        # 5. 删除分支 (如果请求)
        branch_deleted = False
        if delete_branch and branch_name:
            try:
                subprocess.run(
                    ["git", "branch", "-D", branch_name],
                    check=True,
                    cwd=self.project_root,
                )
                branch_deleted = True
            except:
                pass  # 分支删除失败不影响整体结果

        return CleanupResult(
            success=True,
            message="Worktree 清理成功",
            worktree_path=worktree_path,
            branch_deleted=branch_deleted,
        )

    def _is_in_worktree(self, worktree_path: str) -> bool:
        """检查当前是否在 worktree 中"""
        current = os.path.realpath(os.getcwd())
        target = os.path.realpath(worktree_path)
        return current.startswith(target)

    def _get_worktree_branch(self, worktree_path: str) -> Optional[str]:
        """获取 worktree 的分支名"""
        try:
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True,
                text=True,
                cwd=worktree_path,
            )
            return result.stdout.strip() or None
        except:
            return None
```

---

## 交互流程

### 选项 1: 提交并创建 PR

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  Worktree 清理                                              │
│                                                             │
│  路径: .git/worktrees/TASK-001-user-auth                    │
│  分支: feature/backend/TASK-001-user-auth                   │
│  大小: 约 50MB                                              │
│                                                             │
│  PR 已创建成功，建议清理 worktree 释放空间。                  │
│                                                             │
│  请选择:                                                     │
│    [1] 立即清理 (推荐)                                       │
│    [2] 保留 worktree (可能需要后续修改)                      │
│                                                             │
│  选择 [1/2]: _                                              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 选项 3: 放弃变更

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  ⚠️ 确认放弃变更                                             │
│                                                             │
│  即将执行以下操作:                                           │
│    1. 撤销所有未提交的变更                                   │
│    2. 删除分支: feature/backend/TASK-001-user-auth          │
│    3. 清理 worktree: .git/worktrees/TASK-001-user-auth      │
│                                                             │
│  此操作不可恢复！                                            │
│                                                             │
│  确认放弃? [y/N]: _                                         │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 选项 4: 暂停保存

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  暂停并保存                                                  │
│                                                             │
│  状态已保存到: .claude/branch-state/TASK-001.yaml           │
│                                                             │
│  Worktree 将保留以便稍后恢复:                                │
│    路径: .git/worktrees/TASK-001-user-auth                  │
│    分支: feature/backend/TASK-001-user-auth                 │
│                                                             │
│  恢复命令:                                                   │
│    branch-finisher --resume TASK-001                        │
│                                                             │
│  注意: Worktree 会占用磁盘空间 (约 50MB)                     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 清理检查清单

```yaml
清理前检查:
  - [ ] 不在 worktree 目录中
  - [ ] 所有变更已提交或放弃
  - [ ] 用户已确认清理

清理步骤:
  - [ ] cd 回主目录
  - [ ] git worktree remove {path}
  - [ ] git worktree prune
  - [ ] 可选: git branch -D {branch}

清理后验证:
  - [ ] worktree 目录已删除
  - [ ] git worktree list 不显示该 worktree
```

---

## 错误处理

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| 当前在 worktree 中 | 无法删除当前目录 | 先 cd 到主目录 |
| worktree 有未提交变更 | 保护机制 | 使用 --force 或先提交 |
| 分支删除失败 | 分支保护或正在使用 | 手动处理分支 |
| 路径不存在 | 已被手动删除 | 运行 git worktree prune |

---

**Created**: 2026-01-21
**Part of**: enforcement-mechanism-redesign Phase 3.4

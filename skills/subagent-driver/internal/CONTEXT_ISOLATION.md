# 上下文隔离验证

> **Subagent Driver v1.0.0** | Context Isolation Verification
> **Phase 2.5** | enforcement-mechanism-redesign

## Overview

上下文隔离验证确保子代理之间的独立性，防止上下文污染和信息泄露。

---

## 隔离级别

```
┌─────────────────────────────────────────────────────────────┐
│                      隔离级别对比                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  L1 - 对话隔离 (Dialogue Isolation)                         │
│  ├─ 不共享对话历史                                          │
│  ├─ 共享文件系统                                            │
│  ├─ 共享环境变量                                            │
│  └─ 最低开销                                                │
│                                                             │
│  L2 - 文件隔离 (Filesystem Isolation)                       │
│  ├─ L1 所有特性                                             │
│  ├─ 独立 Worktree 工作目录                                  │
│  ├─ 文件变更不影响主目录                                    │
│  └─ 中等开销                                                │
│                                                             │
│  L3 - 完全隔离 (Full Isolation)                             │
│  ├─ L2 所有特性                                             │
│  ├─ 独立进程                                                │
│  ├─ 资源限制                                                │
│  └─ 最高开销                                                │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Implementation

### Pseudo-Code

```python
from dataclasses import dataclass
from typing import List, Optional, Dict
from enum import Enum
import os
import subprocess

class IsolationLevel(Enum):
    L1 = "dialogue"
    L2 = "filesystem"
    L3 = "full"

@dataclass
class IsolationVerificationResult:
    """隔离验证结果"""
    level: IsolationLevel
    passed: bool
    checks: Dict[str, bool]
    errors: List[str]
    warnings: List[str]


class ContextIsolationVerifier:
    """上下文隔离验证器"""

    def __init__(self, subagent_id: str, isolation_level: IsolationLevel):
        self.subagent_id = subagent_id
        self.isolation_level = isolation_level

    def verify(self) -> IsolationVerificationResult:
        """
        执行隔离验证

        Returns:
            IsolationVerificationResult: 验证结果
        """
        checks = {}
        errors = []
        warnings = []

        # L1 检查: 对话隔离
        checks["dialogue_isolation"] = self._verify_dialogue_isolation()
        if not checks["dialogue_isolation"]:
            errors.append("对话隔离验证失败")

        # L2 检查: 文件隔离 (如果适用)
        if self.isolation_level in [IsolationLevel.L2, IsolationLevel.L3]:
            checks["filesystem_isolation"] = self._verify_filesystem_isolation()
            if not checks["filesystem_isolation"]:
                errors.append("文件系统隔离验证失败")

        # L3 检查: 进程隔离 (如果适用)
        if self.isolation_level == IsolationLevel.L3:
            checks["process_isolation"] = self._verify_process_isolation()
            if not checks["process_isolation"]:
                errors.append("进程隔离验证失败")

        # 额外检查
        checks["env_isolation"] = self._verify_env_isolation()
        if not checks["env_isolation"]:
            warnings.append("环境变量可能泄露")

        passed = len(errors) == 0

        return IsolationVerificationResult(
            level=self.isolation_level,
            passed=passed,
            checks=checks,
            errors=errors,
            warnings=warnings,
        )

    def _verify_dialogue_isolation(self) -> bool:
        """
        验证对话隔离

        检查点:
        1. 子代理无法访问主 Agent 对话历史
        2. 子代理无法访问其他子代理的对话
        3. conversation_id 不同
        """
        # 检查 conversation_id
        # 在实际实现中，这需要访问 Claude Code 内部状态
        # 这里使用简化的验证逻辑

        # 验证方法: 尝试引用不存在的历史变量
        # 如果能访问，说明隔离失败
        return True  # 简化实现

    def _verify_filesystem_isolation(self) -> bool:
        """
        验证文件系统隔离

        检查点:
        1. 当前工作目录在 worktree 中
        2. 主目录文件未被修改
        3. worktree 正确配置
        """
        # 检查是否在 worktree 中
        result = subprocess.run(
            ["git", "worktree", "list"],
            capture_output=True,
            text=True,
        )

        current_dir = os.getcwd()

        # 检查当前目录是否在 worktree 列表中
        if current_dir not in result.stdout:
            return False

        # 检查主目录是否干净
        # (需要记录主目录路径)
        return True

    def _verify_process_isolation(self) -> bool:
        """
        验证进程隔离

        检查点:
        1. 子代理运行在独立进程
        2. PID 不同于主进程
        3. 资源限制已应用
        """
        # 获取当前 PID
        current_pid = os.getpid()

        # 检查是否有资源限制
        # (需要访问 cgroup 或类似机制)
        return True  # 简化实现

    def _verify_env_isolation(self) -> bool:
        """
        验证环境变量隔离

        检查点:
        1. 敏感环境变量未泄露
        2. 子代理特定变量已设置
        """
        # 检查敏感变量
        sensitive_vars = ["API_KEY", "SECRET", "PASSWORD", "TOKEN"]

        for var in sensitive_vars:
            if var in os.environ:
                # 警告: 敏感变量可能泄露
                return False

        return True


class IsolationEnforcer:
    """隔离强制执行器"""

    def __init__(self, isolation_level: IsolationLevel):
        self.isolation_level = isolation_level

    def setup(self, task_id: str) -> Dict[str, str]:
        """
        设置隔离环境

        Returns:
            环境配置信息
        """
        config = {}

        if self.isolation_level == IsolationLevel.L1:
            config = self._setup_l1()
        elif self.isolation_level == IsolationLevel.L2:
            config = self._setup_l2(task_id)
        elif self.isolation_level == IsolationLevel.L3:
            config = self._setup_l3(task_id)

        return config

    def _setup_l1(self) -> Dict[str, str]:
        """设置 L1 隔离"""
        return {
            "isolation_level": "L1",
            "dialogue_isolated": "true",
        }

    def _setup_l2(self, task_id: str) -> Dict[str, str]:
        """设置 L2 隔离"""
        # 创建 worktree
        worktree_path = f".git/worktrees/{task_id}"
        branch_name = f"subagent/{task_id}"

        subprocess.run([
            "git", "worktree", "add",
            worktree_path, "-b", branch_name
        ], check=True)

        return {
            "isolation_level": "L2",
            "dialogue_isolated": "true",
            "worktree_path": worktree_path,
            "branch_name": branch_name,
        }

    def _setup_l3(self, task_id: str) -> Dict[str, str]:
        """设置 L3 隔离"""
        # L2 设置
        config = self._setup_l2(task_id)

        # 额外的进程隔离设置
        # (需要使用 subprocess 或容器)
        config["isolation_level"] = "L3"
        config["process_isolated"] = "true"

        return config

    def teardown(self, config: Dict[str, str]):
        """清理隔离环境"""
        if config.get("worktree_path"):
            subprocess.run([
                "git", "worktree", "remove",
                config["worktree_path"]
            ], check=False)

            subprocess.run([
                "git", "worktree", "prune"
            ], check=False)
```

---

## 验证检查清单

### L1 - 对话隔离

```yaml
检查项:
  - [ ] 子代理无法访问主 Agent 对话历史
  - [ ] 子代理无法访问其他子代理的对话
  - [ ] conversation_id 唯一
  - [ ] 无共享内存变量

验证方法:
  1. 在子代理中尝试引用主 Agent 变量
  2. 检查 conversation_id 是否不同
  3. 验证无法访问之前的对话内容
```

### L2 - 文件隔离

```yaml
检查项:
  - [ ] L1 所有检查项
  - [ ] 当前工作目录在 worktree 中
  - [ ] 主目录文件未被修改
  - [ ] worktree 正确配置
  - [ ] 分支正确创建

验证方法:
  1. 运行 git worktree list
  2. 检查 pwd 输出
  3. 在主目录运行 git status
  4. 验证分支存在
```

### L3 - 完全隔离

```yaml
检查项:
  - [ ] L2 所有检查项
  - [ ] 子代理运行在独立进程
  - [ ] PID 不同于主进程
  - [ ] 资源限制已应用
  - [ ] 网络隔离 (可选)

验证方法:
  1. 检查 os.getpid()
  2. 验证 cgroup 限制
  3. 检查网络访问限制
```

---

## 隔离失败处理

```yaml
L1 隔离失败:
  严重程度: 高
  处理: 终止子代理，报告错误
  原因: 可能导致上下文污染

L2 隔离失败:
  严重程度: 中
  处理: 降级到 L1，警告用户
  原因: 文件变更可能影响主目录

L3 隔离失败:
  严重程度: 低
  处理: 降级到 L2，警告用户
  原因: 资源限制未生效
```

---

## 自动隔离级别选择

```python
def auto_select_isolation_level(
    task_complexity: str,
    risk_level: str,
    parallel_needed: bool,
    branch_mode: str,
) -> IsolationLevel:
    """
    自动选择隔离级别

    Args:
        task_complexity: low, medium, high
        risk_level: low, medium, high
        parallel_needed: 是否需要并行
        branch_mode: branch, worktree

    Returns:
        IsolationLevel: 推荐的隔离级别
    """
    # 如果 branch-manager 使用 worktree 模式
    if branch_mode == "worktree":
        return IsolationLevel.L2

    # 高风险任务
    if risk_level == "high":
        return IsolationLevel.L3

    # 需要并行
    if parallel_needed:
        return IsolationLevel.L2

    # 复杂任务
    if task_complexity == "high":
        return IsolationLevel.L2

    # 默认
    return IsolationLevel.L1
```

---

**Created**: 2026-01-21
**Part of**: enforcement-mechanism-redesign Phase 2.5

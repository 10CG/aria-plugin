# Branch Manager - Mode Decision Logic

> **Version**: 1.0.0
> **Part of**: branch-manager enhancement (OpenSpec enforcement-mechanism-redesign)

## Overview

自动模式决策系统根据任务复杂度智能选择 **Branch 模式** (常规分支) 或 **Worktree 模式** (隔离工作目录)。

---

## Scoring Algorithm

### Score Components

| 因素 | 权重 | 评分规则 | 分数 |
|------|------|---------|------|
| **file_count** | 低 | 1-3 个文件 | 0 |
| | | 4-10 个文件 | +1 |
| | | 10+ 个文件 | +3 |
| **cross_directory** | 中 | 不跨目录 | 0 |
| | | 跨目录 | +2 |
| **task_count** | 低 | 1-3 个任务 | 0 |
| | | 4-8 个任务 | +1 |
| | | 8+ 个任务 | +3 |
| **risk_level** | 中 | 低风险 (typo, config) | 0 |
| | | 中风险 (小功能) | +1 |
| | | 高风险 (重构, API 变更) | +3 |
| **parallel_needed** | 高 | 不需要并行 | 0 |
| | | 需要并行开发 | +5 |

### Decision Threshold

```
总分 >= 3 分  → Worktree 模式
总分 <  3 分  → Branch 模式
```

---

## Pseudo-Code Implementation

```python
def decide_mode(context: dict) -> str:
    """
    根据上下文决定使用 Branch 还是 Worktree 模式

    Args:
        context: {
            "files": ["path/to/file1", "path/to/file2", ...],
            "tasks": ["TASK-001", "TASK-002", ...],
            "risk_level": "low" | "medium" | "high",
            "parallel_needed": bool,
        }

    Returns:
        "branch" | "worktree"
    """
    score = 0

    # 1. file_count 评分
    file_count = len(context.get("files", []))
    if file_count <= 3:
        score += 0
    elif file_count <= 10:
        score += 1
    else:
        score += 3

    # 2. cross_directory 评分
    directories = set(os.path.dirname(f) for f in context.get("files", []))
    if len(directories) > 1:
        score += 2

    # 3. task_count 评分
    task_count = len(context.get("tasks", []))
    if task_count <= 3:
        score += 0
    elif task_count <= 8:
        score += 1
    else:
        score += 3

    # 4. risk_level 评分
    risk_level = context.get("risk_level", "low")
    risk_scores = {"low": 0, "medium": 1, "high": 3}
    score += risk_scores.get(risk_level, 0)

    # 5. parallel_needed 评分
    if context.get("parallel_needed", False):
        score += 5

    # 决策
    return "worktree" if score >= 3 else "branch"


def detect_risk_level(files: list[str], description: str) -> str:
    """
    根据文件列表和描述自动检测风险等级

    Returns:
        "low" | "medium" | "high"
    """
    # 高风险关键词
    high_risk_keywords = [
        "refactor", "rewrite", "architecture", "api", "breaking",
        "重构", "架构", "破坏性", "核心"
    ]

    # 低风险关键词
    low_risk_keywords = [
        "typo", "format", "lint", "config", "doc", "comment",
        "拼写", "格式", "配置", "文档", "注释"
    ]

    desc_lower = description.lower()

    if any(kw in desc_lower for kw in high_risk_keywords):
        return "high"
    elif any(kw in desc_lower for kw in low_risk_keywords):
        return "low"
    else:
        return "medium"


def detect_parallel_needs(openspec_path: str = None) -> bool:
    """
    检测是否需要并行开发

    检查点:
    1. 是否有多个独立子任务
    2. 是否明确标注了并行需求
    3. OpenSpec 中是否有并行标记
    """
    if not openspec_path:
        return False

    # 读取 tasks.md 或 detailed-tasks.yaml
    # 检查是否有 parallel: true 或类似标记
    # TODO: 实际实现需要解析 OpenSpec 文件
    return False
```

---

## Decision Examples

### Example 1: Simple Bugfix (Branch Mode)

```yaml
Input:
  files: ["lib/utils.py"]
  tasks: ["TASK-001"]
  risk_level: low
  parallel_needed: false

Scoring:
  file_count: 1 → 0
  cross_directory: false → 0
  task_count: 1 → 0
  risk_level: low → 0
  parallel_needed: false → 0

Total: 0 < 3 → Branch Mode
```

### Example 2: Medium Feature (Branch Mode)

```yaml
Input:
  files:
    - backend/src/routes/auth.py
    - backend/src/models/user.py
    - backend/src/services/auth.py
  tasks: ["TASK-001", "TASK-002"]
  risk_level: medium
  parallel_needed: false

Scoring:
  file_count: 3 → 0
  cross_directory: false → 0
  task_count: 2 → 0
  risk_level: medium → 1
  parallel_needed: false → 0

Total: 1 < 3 → Branch Mode
```

### Example 3: Complex Feature (Worktree Mode)

```yaml
Input:
  files:
    - backend/src/routes/auth.py
    - backend/src/models/user.py
    - backend/src/services/auth.py
    - backend/tests/test_auth.py
    - frontend/src/components/LoginForm.tsx
    - frontend/src/services/auth.ts
  tasks: ["TASK-001", "TASK-002", "TASK-003", "TASK-004"]
  risk_level: high
  parallel_needed: false

Scoring:
  file_count: 6 → 1
  cross_directory: true → 2
  task_count: 4 → 1
  risk_level: high → 3
  parallel_needed: false → 0

Total: 7 >= 3 → Worktree Mode
```

### Example 4: Parallel Development (Worktree Mode)

```yaml
Input:
  files: 5 files
  tasks: 3 tasks
  risk_level: medium
  parallel_needed: true

Scoring:
  file_count: 5 → 1
  cross_directory: false → 0
  task_count: 3 → 0
  risk_level: medium → 1
  parallel_needed: true → 5

Total: 7 >= 3 → Worktree Mode
```

---

## Integration with branch-manager

### Input Parameters

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `mode` | string | `auto` \| `branch` \| `worktree` | `auto` |
| `files` | list | 预期修改的文件列表 | `[]` |
| `task_count` | int | 预计任务数量 | 1 |
| `risk_level` | string | `low` \| `medium` \| `high` | 自动检测 |
| `parallel_needed` | bool | 是否需要并行开发 | 自动检测 |

### Usage

```bash
# 自动模式 (推荐)
branch-manager --mode auto --task-id TASK-001

# 强制使用 Branch
branch-manager --mode branch --task-id TASK-001

# 强制使用 Worktree
branch-manager --mode worktree --task-id TASK-001
```

---

## Mode Comparison

| 特性 | Branch 模式 | Worktree 模式 |
|------|------------|--------------|
| **工作目录** | 当前工作目录 | 独立 worktree 目录 |
| **适用场景** | 简单修改、串行开发 | 复杂功能、并行开发 |
| **切换成本** | 低 (git checkout) | 中 (cd 到 worktree) |
| **隔离性** | 共享工作区 | 完全隔离 |
| **构建缓存** | 可能失效 | 独立缓存 |

---

## Red Flags

### 不应使用 Worktree 的情况

1. **单文件修改** - Worktree 开销大于收益
2. **快速修复** - 切换分支更快
3. **磁盘空间不足** - Worktree 会复制工作目录

### 不应使用 Branch 的情况

1. **同时开发多个功能** - 频繁切换分支
2. **需要构建隔离** - 构建产物冲突
3. **高风险变更** - 需要隔离验证

---

**Created**: 2026-01-20
**Part of**: enforcement-mechanism-redesign Phase 1.1

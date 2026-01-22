# Directory Priority Selection Logic

> **Branch Manager v2.0.0** | 目录优先级选择
> **Phase 1.4** | enforcement-mechanism-redesign

## Overview

当使用 Worktree 模式时，需要决定 worktree 的放置位置。本模块定义了目录选择的优先级逻辑。

---

## Priority Order

```
1. 用户显式指定 (worktree_path 参数)
2. 项目配置文件 (.claude/config.yml)
3. 默认位置 (.git/worktrees/)
4. 备用位置 (../worktrees/ 或 ~/worktrees/)
5. 临时位置 (/tmp/worktrees/)
```

---

## Decision Tree

```
┌─────────────────────────────────────────────────────────────┐
│                    目录优先级决策树                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. 用户是否指定 worktree_path?                             │
│     ├─ YES → 使用指定路径                                   │
│     └─ NO  → 继续                                          │
│                                                             │
│  2. 是否存在 .claude/config.yml 配置?                       │
│     ├─ YES → 读取 worktree.base 配置                        │
│     │         ├─ 配置存在且可用 → 使用配置路径               │
│     │         └─ 配置无效/不可写 → 继续                     │
│     └─ NO  → 继续                                          │
│                                                             │
│  3. 默认位置 .git/worktrees/ 是否可用?                      │
│     ├─ YES → 使用默认位置                                   │
│     └─ NO  → 继续                                          │
│                                                             │
│  4. 备用位置 ../worktrees/ 是否可用?                        │
│     ├─ YES → 使用备用位置                                   │
│     └─ NO  → 继续                                          │
│                                                             │
│  5. 用户主目录 ~/worktrees/ 是否可用?                       │
│     ├─ YES → 使用主目录位置                                 │
│     └─ NO  → 继续                                          │
│                                                             │
│  6. 临时位置 /tmp/worktrees/ (最后兜底)                      │
│     └─ YES → 使用临时位置                                  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Implementation

### Pseudo-Code

```python
import os
import yaml
from pathlib import Path

class DirectoryPrioritySelector:
    """目录优先级选择器"""

    def __init__(self, project_root: str):
        self.project_root = Path(project_root).resolve()
        self.config = self._load_config()

    def select_worktree_directory(
        self,
        user_path: str = None,
        task_id: str = None,
        description: str = None
    ) -> str:
        """
        选择 worktree 目录

        Args:
            user_path: 用户显式指定的路径
            task_id: 任务 ID (用于生成默认目录名)
            description: 任务描述 (用于生成默认目录名)

        Returns:
            选择的 worktree 基础路径
        """
        # 1. 用户显式指定 (最高优先级)
        if user_path:
            path = self._validate_path(user_path)
            if path:
                return str(path)

        # 2. 项目配置文件
        config_path = self._get_config_path()
        if config_path:
            return config_path

        # 3. 默认位置
        default_path = self.project_root / ".git" / "worktrees"
        if self._is_available(default_path):
            return str(default_path)

        # 4. 备用位置 (项目上级)
        fallback_path = self.project_root.parent / "worktrees"
        if self._is_available(fallback_path):
            return str(fallback_path)

        # 5. 用户主目录
        home_path = Path.home() / "worktrees" / self.project_root.name
        if self._is_available(home_path):
            return str(home_path)

        # 6. 临时位置 (最后兜底)
        temp_path = Path("/tmp") / "worktrees" / self.project_root.name
        return str(temp_path)

    def _load_config(self) -> dict:
        """加载项目配置"""
        config_file = self.project_root / ".claude" / "config.yml"
        if not config_file.exists():
            return {}

        try:
            with open(config_file) as f:
                return yaml.safe_load(f) or {}
        except:
            return {}

    def _get_config_path(self) -> str | None:
        """从配置获取 worktree 路径"""
        worktree_config = self.config.get("worktree", {})
        if not worktree_config:
            return None

        base = worktree_config.get("base")
        if not base:
            return None

        # 支持相对路径和绝对路径
        path = Path(base)
        if not path.is_absolute():
            path = self.project_root / path

        if self._is_available(path):
            return str(path)

        return None

    def _validate_path(self, path: str) -> Path | None:
        """验证用户指定的路径"""
        p = Path(path)

        # 支持相对路径
        if not p.is_absolute():
            p = self.project_root / p

        # 检查是否可用
        if self._is_available(p):
            return p

        return None

    def _is_available(self, path: Path) -> bool:
        """检查路径是否可用"""
        try:
            # 父目录必须存在
            if not path.parent.exists():
                return False

            # 路径本身不存在或为空目录
            if not path.exists():
                # 尝试创建
                try:
                    path.mkdir(parents=True, exist_ok=True)
                    path.rmdir()  # 测试完成后删除
                except:
                    return False
                return True

            # 路径存在且为空目录
            if path.is_dir():
                return not any(path.iterate())

            # 路径存在但不是目录
            return False

        except:
            return False
```

---

## Configuration Format

### .claude/config.yml

```yaml
# branch-manager 配置
worktree:
  # worktree 基础路径 (可选)
  base: ".git/worktrees"  # 或 "../worktrees", "~/worktrees/project"

  # worktree 命名模板 (可选)
  name_template: "{task_id}-{description}"  # 默认

  # 自动清理配置 (可选)
  auto_cleanup:
    enabled: false
    after_merge: true
    after_days: 7

  # 最大 worktree 数量 (可选)
  max_count: 10
```

---

## Shell Implementation

```bash
#!/bin/bash
# scripts/select-worktree-directory.sh
# 目录优先级选择脚本

PROJECT_ROOT=${1:-.}
USER_PATH=${2:-}

# 1. 用户显式指定
if [ -n "$USER_PATH" ]; then
    if [ -d "$(dirname "$USER_PATH")" ]; then
        echo "$USER_PATH"
        exit 0
    fi
fi

# 2. 项目配置文件
CONFIG_FILE="$PROJECT_ROOT/.claude/config.yml"
if [ -f "$CONFIG_FILE" ]; then
    # 简单解析 YAML (需要 yq 或类似工具)
    BASE=$(grep -A1 "worktree:" "$CONFIG_FILE" | grep "base:" | cut -d: -f2 | xargs)
    if [ -n "$BASE" ]; then
        echo "$BASE"
        exit 0
    fi
fi

# 3. 默认位置
DEFAULT_PATH="$PROJECT_ROOT/.git/worktrees"
if [ -w "$(dirname "$DEFAULT_PATH")" ]; then
    echo "$DEFAULT_PATH"
    exit 0
fi

# 4. 备用位置
FALLBACK_PATH="$(dirname "$PROJECT_ROOT")/worktrees"
if [ -w "$(dirname "$FALLBACK_PATH")" ]; then
    echo "$FALLBACK_PATH"
    exit 0
fi

# 5. 用户主目录
HOME_PATH="$HOME/worktrees/$(basename "$PROJECT_ROOT")"
echo "$HOME_PATH"
exit 0
```

---

## Validation Rules

创建 worktree 前的验证检查：

```yaml
验证规则:
  路径存在性:
    - 父目录必须存在
    - 路径本身不应存在 (或为空目录)

  路径可写性:
    - 必须有创建目录的权限
    - 必须有写入文件的权限

  路径安全性:
    - 不应是系统关键目录
    - 不应有特殊字符

  磁盘空间:
    - 至少保留 1GB 可用空间
```

---

## Error Messages

| 场景 | 错误消息 | 建议 |
|------|---------|------|
| 路径不可写 | `无法写入路径: {path}` | 检查目录权限 |
| 父目录不存在 | `父目录不存在: {parent}` | 创建父目录或指定其他路径 |
| 路径已存在 | `路径已存在: {path}` | 使用不同的 task_id 或手动清理 |
| 磁盘空间不足 | `磁盘空间不足 (< 1GB)` | 清理磁盘或指定其他路径 |
| 所有路径不可用 | `无法找到可用的 worktree 位置` | 手动指定 worktree_path 参数 |

---

## Examples

### 示例 1: 使用默认位置

```bash
# 无配置，使用默认
$ branch-manager --mode auto --task-id TASK-001 --description "user-auth"

# 选择: .git/worktrees/
# 创建: .git/worktrees/TASK-001-user-auth/
```

### 示例 2: 使用配置文件

```yaml
# .claude/config.yml
worktree:
  base: "../worktrees"
```

```bash
$ branch-manager --mode auto --task-id TASK-001 --description "user-auth"

# 选择: ../worktrees/
# 创建: ../worktrees/TASK-001-user-auth/
```

### 示例 3: 用户显式指定

```bash
$ branch-manager --mode auto --task-id TASK-001 \
    --description "user-auth" \
    --worktree-path "~/my-worktrees/task-001"

# 选择: ~/my-worktrees/task-001
# 创建: ~/my-worktrees/task-001/
```

---

**Created**: 2026-01-20
**Part of**: enforcement-mechanism-redesign Phase 1.4

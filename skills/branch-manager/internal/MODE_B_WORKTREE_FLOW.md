# Mode B - Worktree Flow Implementation

> **Branch Manager v2.0.0** | Worktree 隔离开发流程
> **Phase 1.3** | enforcement-mechanism-redesign

## Overview

模式 B (Worktree) 使用 Git Worktree 创建隔离的工作目录，适用于：
- 复杂修改 (4+ 个文件)
- 跨目录/跨模块变更
- 需要构建隔离的场景
- 并行开发需求
- 评分 >= 3 的任务

---

## Execution Flow

```yaml
B.1.0 - 模式决策:
  → 决策结果: Worktree 模式
  → 输出理由

B.1.1 - 环境验证:
  ├─ 检查当前分支 (必须在 develop)
  ├─ 检查工作目录状态 (必须干净)
  ├─ 检查磁盘空间
  └─ 拉取最新代码 (git pull origin develop)

B.1.2 - Worktree 创建:
  ├─ 生成分支名: {branch_type}/{module}/{task_id}-{description}
  ├─ 生成 worktree 路径: .git/worktrees/{task_id}-{description}
  ├─ 检查路径是否已存在
  └─ 创建 worktree: git worktree add {path} {branch_name}

B.1.3 - 后续处理:
  ├─ 记录 worktree 信息到 .claude/worktrees/
  ├─ 输出 worktree 路径和 cd 命令
  └─ 返回下一步指示 (cd 到 worktree 开始开发)

B.1.4 - 清理指引:
  └─ 输出清理命令 (任务完成后)
```

---

## Implementation

### Pseudo-Code

```python
def execute_worktree_mode(context: dict) -> dict:
    """
    执行 Worktree 模式的分支创建流程

    Args:
        context: {
            "module": "backend",
            "task_id": "TASK-001",
            "description": "user-auth",
            "branch_type": "feature",
            "worktree_path": None,  # 自动生成
        }

    Returns:
        {
            "mode": "worktree",
            "branch_name": "feature/backend/TASK-001-user-auth",
            "worktree_path": ".git/worktrees/TASK-001-user-auth",
            "location": "worktree",
            "remote_push": "success",
            "decision_reason": "跨目录修改，使用隔离环境",
            "next_step": "cd .git/worktrees/TASK-001-user-auth",
            "cleanup_cmd": "git worktree remove .git/worktrees/TASK-001-user-auth"
        }
    """
    result = {"mode": "worktree"}

    # B.1.1 - 环境验证
    validate_environment_for_worktree(context)

    # B.1.2 - 生成分支名和路径
    branch_name = generate_branch_name(context)
    result["branch_name"] = branch_name

    worktree_path = generate_worktree_path(context)
    result["worktree_path"] = worktree_path

    # B.1.3 - 检查路径是否已存在
    check_worktree_available(worktree_path)

    # B.1.4 - 创建 worktree
    create_worktree(worktree_path, branch_name)

    # B.1.5 - 推送远程 (从 worktree)
    push_branch_from_worktree(worktree_path, branch_name)

    # B.1.6 - 记录信息
    result["location"] = "worktree"
    result["remote_push"] = "success"

    reasons = [
        "跨目录修改，使用隔离环境",
        "复杂功能，隔离构建产物",
        "并行开发需求",
    ]
    result["decision_reason"] = reasons[0]  # 根据实际评分选择

    result["next_step"] = f"cd {worktree_path}"
    result["cleanup_cmd"] = f"git worktree remove {worktree_path}"

    return result


def validate_environment_for_worktree(context: dict):
    """Worktree 专用环境验证"""
    # 基础验证 (同 Branch 模式)
    validate_environment(context)

    # 额外检查: 磁盘空间
    check_disk_space(minimum_gb=5)


def generate_worktree_path(context: dict) -> str:
    """
    生成 worktree 路径

    优先级:
    1. 用户指定路径
    2. .git/worktrees/{task_id}-{description}
    3. ../worktrees/{task_id}-{description}
    """
    if context.get("worktree_path"):
        return context["worktree_path"]

    task_id = context["task_id"]
    description = context["description"]

    # 默认路径
    return f".git/worktrees/{task_id}-{description}"


def check_worktree_available(path: str):
    """检查 worktree 路径是否可用"""
    if os.path.exists(path):
        raise FileExistsError(f"Worktree 路径 {path} 已存在")

    # 检查是否已存在同名 worktree
    existing = git("worktree list").strip()
    if path in existing:
        raise FileExistsError(f"Worktree {path} 已在 git 中注册")


def create_worktree(path: str, branch_name: str):
    """创建 worktree"""
    git(f"worktree add {path} {branch_name}")


def push_branch_from_worktree(worktree_path: str, branch_name: str):
    """从 worktree 推送分支"""
    original_dir = os.getcwd()
    try:
        os.chdir(worktree_path)
        git(f"push -u origin {branch_name}")
    finally:
        os.chdir(original_dir)


def cleanup_worktree(path: str):
    """清理 worktree"""
    # 1. 删除 worktree
    git(f"worktree remove {path}")

    # 2. 清理过期的 worktree 记录
    git("worktree prune")
```

---

## Shell Script Template

```bash
#!/bin/bash
# templates/worktree-create-enhanced.sh
# Worktree 模式分支创建脚本 (增强版)

set -e

BRANCH_TYPE=${1:-feature}
MODULE=${2:?Required: module}
TASK_ID=${3:?Required: task_id}
DESCRIPTION=${4:?Required: description}
WORKTREE_BASE=${5:-".git/worktrees"}

# 生成分支名和路径
BRANCH_NAME="${BRANCH_TYPE}/${MODULE}/${TASK_ID}-${DESCRIPTION}"
WORKTREE_PATH="${WORKTREE_BASE}/${TASK_ID}-${DESCRIPTION}"

echo "=== Worktree Mode: 隔离开发环境创建 ==="
echo "分支名: ${BRANCH_NAME}"
echo "Worktree: ${WORKTREE_PATH}"
echo ""

# 环境验证
echo "[1/5] 环境验证..."
CURRENT_BRANCH=$(git branch --show-current)
if [ "$CURRENT_BRANCH" != "develop" ]; then
    echo "❌ 错误: 当前在 ${CURRENT_BRANCH} 分支"
    echo "   请切换到 develop 分支"
    exit 1
fi

if [ -n "$(git status --porcelain)" ]; then
    echo "❌ 错误: 工作目录不干净"
    echo "   请先提交或 stash 变更"
    exit 1
fi

# 检查磁盘空间
echo "[2/5] 检查磁盘空间..."
# 简单检查: 确保 .git 目录可写
if [ ! -w .git ]; then
    echo "❌ 错误: .git 目录不可写"
    exit 1
fi

# 拉取最新代码
echo "[3/5] 拉取最新代码..."
git pull origin develop

# 检查 worktree 路径
echo "[4/5] 检查 worktree 路径..."
if [ -d "${WORKTREE_PATH}" ]; then
    echo "❌ 错误: Worktree 路径已存在"
    echo "   路径: ${WORKTREE_PATH}"
    echo "   如需清理，运行: git worktree remove ${WORKTREE_PATH}"
    exit 1
fi

# 创建 worktree
echo "[5/5] 创建 worktree..."
git worktree add "${WORKTREE_PATH}" "${BRANCH_NAME}"

# 推送远程
echo "    推送远程..."
cd "${WORKTREE_PATH}"
git push -u origin "${BRANCH_NAME}"
cd - > /dev/null

echo ""
echo "✅ Worktree 创建成功!"
echo ""
echo "   分支名: ${BRANCH_NAME}"
echo "   路径:   ${WORKTREE_PATH}"
echo ""
echo "➡️ 下一步:"
echo "   cd ${WORKTREE_PATH}"
echo "   # 开始开发..."
echo ""
echo "🧹 完成后清理:"
echo "   cd .."
echo "   git worktree remove ${WORKTREE_PATH}"
echo "   git worktree prune"
```

---

## Directory Priority Selection (Phase 1.4)

当需要决定 worktree 放置位置时，按以下优先级：

```python
def select_worktree_directory(context: dict) -> str:
    """
    目录优先级选择逻辑

    优先级:
    1. 用户指定 (worktree_path 参数)
    2. 项目配置 (.claude/config.yml worktree.base)
    3. 默认位置 (.git/worktrees/)
    4. 备用位置 (../worktrees/)
    """
    # 1. 用户指定
    if context.get("worktree_path"):
        return context["worktree_path"]

    # 2. 项目配置
    config_path = ".claude/config.yml"
    if os.path.exists(config_path):
        with open(config_path) as f:
            config = yaml.safe_load(f)
            if config.get("worktree", {}).get("base"):
                return config["worktree"]["base"]

    # 3. 默认位置
    default_path = ".git/worktrees/"
    if can_create_directory(default_path):
        return default_path

    # 4. 备用位置
    return "../worktrees/"
```

---

## Worktree Cleanup

任务完成后需要清理 worktree：

```bash
# 清理流程
cd ..                           # 离开 worktree
git worktree remove {path}      # 删除 worktree
git worktree prune              # 清理过期记录

# 或使用封装脚本
./templates/worktree-cleanup.sh {path}
```

---

## Error Handling

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| `不在 develop 分支` | 当前在其他分支 | `git checkout develop` |
| `工作目录不干净` | 有未提交变更 | `git stash` 或 `git commit` |
| `路径已存在` | worktree 路径冲突 | `git worktree remove {path}` 或使用不同名称 |
| `磁盘空间不足` | 空间不够 | 清理磁盘或使用不同路径 |
| `推送失败` | 网络或权限问题 | 检查网络连接和仓库权限 |

---

## Output Format

```yaml
成功输出:
  mode: "worktree"
  branch_name: "feature/backend/TASK-001-user-auth"
  worktree_path: ".git/worktrees/TASK-001-user-auth"
  location: "worktree"
  remote_push: "success"
  decision_reason: "跨目录修改，使用隔离环境"
  next_step: "cd .git/worktrees/TASK-001-user-auth"
  cleanup_cmd: "git worktree remove .git/worktrees/TASK-001-user-auth"

失败输出:
  error: "Worktree 路径已存在"
  suggestion: "运行: git worktree remove .git/worktrees/TASK-001-user-auth"
```

---

## Checklist

执行前:
- [ ] 确认在 develop 分支
- [ ] 确认工作目录干净
- [ ] 确认有足够磁盘空间
- [ ] 确认 task_id 和 description 准确

执行后:
- [ ] worktree 已创建
- [ ] 分支已推送到远程
- [ ] 已记录 worktree 路径
- [ ] 准备 cd 到 worktree 开始开发

完成后:
- [ ] cd 回主目录
- [ ] 清理 worktree
- [ ] 运行 git worktree prune

---

**Created**: 2026-01-20
**Part of**: enforcement-mechanism-redesign Phase 1.3

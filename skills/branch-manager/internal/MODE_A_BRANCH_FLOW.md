# Mode A - Branch Flow Implementation

> **Branch Manager v2.0.0** | 常规分支创建流程
> **Phase 1.2** | enforcement-mechanism-redesign

## Overview

模式 A (Branch) 是传统的分支创建方式，适用于：
- 简单修改 (1-3 个文件)
- 串行开发场景
- 快速修复和调试
- 评分 < 3 的任务

---

## Execution Flow

```yaml
B.1.0 - 模式决策:
  → 决策结果: Branch 模式
  → 输出理由

B.1.1 - 环境验证:
  ├─ 检查当前分支 (必须在 develop)
  ├─ 检查工作目录状态 (必须干净)
  └─ 拉取最新代码 (git pull origin develop)

B.1.2 - 分支创建:
  ├─ 生成分支名: {branch_type}/{module}/{task_id}-{description}
  ├─ 创建本地分支: git checkout -b {branch_name}
  └─ 推送远程: git push -u origin {branch_name}

B.1.3 - 后续处理:
  ├─ 记录分支信息到 .claude/branches/
  └─ 返回下一步指示 (开始 B.2)
```

---

## Implementation

### Pseudo-Code

```python
def execute_branch_mode(context: dict) -> dict:
    """
    执行 Branch 模式的分支创建流程

    Args:
        context: {
            "module": "backend",
            "task_id": "TASK-001",
            "description": "user-auth",
            "branch_type": "feature",
            "in_submodule": False,
        }

    Returns:
        {
            "mode": "branch",
            "branch_name": "feature/backend/TASK-001-user-auth",
            "location": "main_repo",
            "remote_push": "success",
            "decision_reason": "...",
            "next_step": "开始 B.2 执行验证"
        }
    """
    result = {"mode": "branch"}

    # B.1.1 - 环境验证
    validate_environment(context)

    # B.1.2 - 生成分支名
    branch_name = generate_branch_name(context)
    result["branch_name"] = branch_name

    # B.1.3 - 创建分支
    create_branch(branch_name)

    # B.1.4 - 推送远程
    push_branch(branch_name)

    # B.1.5 - 记录信息
    result["location"] = "submodule:" + context["module"] if context.get("in_submodule") else "main_repo"
    result["remote_push"] = "success"
    result["decision_reason"] = "简单修改，使用常规分支"
    result["next_step"] = "开始 B.2 执行验证"

    return result


def validate_environment(context: dict):
    """环境验证"""
    # 1. 检查当前分支
    current_branch = git("branch --show-current").strip()
    if current_branch != "develop":
        raise EnvironmentError(f"当前在 {current_branch} 分支，请切换到 develop")

    # 2. 检查工作目录
    status = git("status --porcelain")
    if status.strip():
        raise EnvironmentError("工作目录不干净，请先提交或 stash 变更")

    # 3. 拉取最新代码
    git("pull origin develop")

    # 4. 如果是子模块，进入子模块目录
    if context.get("in_submodule"):
        module_path = context["module"]
        if not os.path.exists(module_path):
            raise EnvironmentError(f"子模块目录 {module_path} 不存在")
        os.chdir(module_path)
        # 重复验证子模块状态
        validate_environment_submodule()


def generate_branch_name(context: dict) -> str:
    """生成分支名"""
    branch_type = context.get("branch_type", "feature")
    module = context["module"]
    task_id = context["task_id"]
    description = context["description"]

    # 格式: {branch_type}/{module}/{task_id}-{description}
    return f"{branch_type}/{module}/{task_id}-{description}"


def create_branch(branch_name: str):
    """创建本地分支"""
    git(f"checkout -b {branch_name}")


def push_branch(branch_name: str):
    """推送分支到远程"""
    git(f"push -u origin {branch_name}")
```

---

## Shell Script Template

```bash
#!/bin/bash
# templates/branch-create.sh
# Branch 模式分支创建脚本

set -e

BRANCH_TYPE=${1:-feature}
MODULE=${2:?Required: module}
TASK_ID=${3:?Required: task_id}
DESCRIPTION=${4:?Required: description}
IN_SUBMODULE=${5:-false}

# 生成分支名
BRANCH_NAME="${BRANCH_TYPE}/${MODULE}/${TASK_ID}-${DESCRIPTION}"

echo "=== Branch Mode: 分支创建 ==="
echo "分支名: ${BRANCH_NAME}"
echo ""

# 环境验证
echo "[1/4] 环境验证..."
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

# 拉取最新代码
echo "[2/4] 拉取最新代码..."
git pull origin develop

# 创建分支
echo "[3/4] 创建分支..."
git checkout -b "${BRANCH_NAME}"

# 推送远程
echo "[4/4] 推送远程..."
git push -u origin "${BRANCH_NAME}"

echo ""
echo "✅ 分支创建成功!"
echo "   分支名: ${BRANCH_NAME}"
echo "   位置: ${IN_SUBMODULE:+子模块 }main_repo"
echo ""
echo "➡️ 下一步: 开始 B.2 执行验证"
```

---

## Error Handling

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| `不在 develop 分支` | 当前在其他分支 | `git checkout develop` |
| `工作目录不干净` | 有未提交变更 | `git stash` 或 `git commit` |
| `分支已存在` | 分支名冲突 | 使用不同的 task_id 或 description |
| `推送失败` | 网络或权限问题 | 检查网络连接和仓库权限 |

---

## Output Format

```yaml
成功输出:
  mode: "branch"
  branch_name: "feature/backend/TASK-001-user-auth"
  location: "main_repo" | "submodule:backend"
  remote_push: "success"
  decision_reason: "简单修改，使用常规分支"
  next_step: "开始 B.2 执行验证"

失败输出:
  error: "当前不在 develop 分支"
  suggestion: "请先运行: git checkout develop"
```

---

## Checklist

执行前:
- [ ] 确认在 develop 分支
- [ ] 确认工作目录干净
- [ ] 确认 task_id 和 description 准确

执行后:
- [ ] 分支已创建
- [ ] 分支已推送到远程
- [ ] 已切换到新分支
- [ ] 准备开始 B.2 验证

---

**Created**: 2026-01-20
**Part of**: enforcement-mechanism-redesign Phase 1.2

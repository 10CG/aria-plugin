# 子模块分支工作流

> **Version**: 1.0.0
> **Purpose**: 详细说明在子模块内进行分支操作的完整流程

---

## 概述

本项目采用 Git Submodule 架构，包含以下子模块：

| 子模块 | 路径 | 远程仓库 |
|--------|------|----------|
| Backend | `backend/` | `10CG/todo-app-backend` |
| Mobile | `mobile/` | `10CG/todo-app-mobile` |
| Shared | `shared/` | `10CG/todo-app-shared` |
| Standards | `standards/` | `10CG/ai-ddd-standards` |
| Agents | `.claude/agents/` | `10CG/todo-app-agents` |

---

## 场景 1: 在子模块内开发功能

### 完整流程

```bash
# === B.1: 分支创建 ===

# 1. 确保主仓库干净
cd /path/to/todo-app
git status  # 应该是干净的

# 2. 进入子模块
cd backend/

# 3. 确保子模块 develop 最新
git checkout develop
git pull origin develop

# 4. 创建功能分支
git checkout -b feature/backend/TASK-001-user-auth
git push -u origin feature/backend/TASK-001-user-auth

# === B.2-C.1: 开发、测试、提交 ===
# ... 在子模块内完成开发工作 ...

# === C.2: 创建 PR ===

# 5. 推送并创建 PR (在子模块仓库)
git push origin feature/backend/TASK-001-user-auth

# 6. 使用 Forgejo API 创建 PR
source ~/.bash_profile
forgejo-api -X POST "$FORGEJO_API/repos/10CG/todo-app-backend/pulls" \
  -d '{
    "title": "feat(auth): 添加用户认证 / Add user authentication",
    "body": "## Summary\n\n实现 JWT 认证...",
    "head": "feature/backend/TASK-001-user-auth",
    "base": "develop"
  }'

# 7. 等待 PR 审批和合并...

# === PR 合并后 ===

# 8. 在子模块内更新 develop
git checkout develop
git pull origin develop

# 9. 删除本地功能分支
git branch -d feature/backend/TASK-001-user-auth

# 10. 回到主仓库
cd ..

# 11. 更新子模块指针
git add backend
git commit -m "chore(submodule): update backend to include user-auth feature"
git push origin develop
```

---

## 场景 2: 跨多个子模块的功能

当一个功能需要同时修改多个子模块时：

### 推荐方式: 顺序开发

```yaml
步骤:
  1. 确定依赖顺序:
     shared (契约定义) → backend (API 实现) → mobile (UI 实现)

  2. 在 shared 子模块:
     - 创建分支 feature/shared/TASK-001-auth-contract
     - 定义 API 契约
     - 创建 PR 并合并

  3. 在 backend 子模块:
     - 更新 shared 子模块: git submodule update --remote shared
     - 创建分支 feature/backend/TASK-001-user-auth
     - 实现 API
     - 创建 PR 并合并

  4. 在 mobile 子模块:
     - 更新 shared 子模块
     - 创建分支 feature/mobile/TASK-001-login-ui
     - 实现 UI
     - 创建 PR 并合并

  5. 最后在主仓库:
     - 更新所有子模块指针
     - 一次性提交
```

### 主仓库最终更新

```bash
cd /path/to/todo-app
git checkout develop
git pull origin develop

# 更新所有子模块到最新
git submodule update --remote

# 提交子模块指针更新
git add shared backend mobile
git commit -m "chore(submodule): update for TASK-001 user-auth feature

- shared: auth contract v1.0
- backend: auth API implementation
- mobile: login UI implementation"

git push origin develop
```

---

## 场景 3: 在主仓库创建 cross 分支

当需要同时修改主仓库文件和子模块时：

```bash
# 1. 在主仓库创建 cross 分支
cd /path/to/todo-app
git checkout develop
git pull origin develop
git checkout -b feature/cross/TASK-005-e2e-auth

# 2. 修改主仓库文件 (如 docs, scripts 等)
# ...

# 3. 进入子模块修改
cd backend/
git checkout develop
git pull origin develop
# 直接在 develop 上修改 (小变更) 或创建分支 (大变更)
cd ..

# 4. 提交主仓库变更 (包含子模块指针)
git add .
git commit -m "feat(cross): implement e2e auth tests"

# 5. 创建主仓库 PR
git push origin feature/cross/TASK-005-e2e-auth
# ... 创建 PR ...
```

---

## 注意事项

### 子模块状态检查

```bash
# 查看所有子模块状态
git submodule status

# 输出示例:
# +abc1234 backend (heads/develop)     # + 表示有本地变更
# -def5678 mobile                       # - 表示未初始化
#  ghi9012 shared (v1.0.0)             # 空格表示正常
```

### 子模块未初始化

```bash
# 初始化并更新所有子模块
git submodule update --init --recursive
```

### 子模块处于游离 HEAD

```bash
# 进入子模块
cd backend/

# 检查状态
git status
# HEAD detached at abc1234

# 切换到 develop
git checkout develop
```

### 防止意外提交子模块变更

在开发过程中，如果只想提交主仓库变更：

```bash
# 查看变更时排除子模块
git status --ignore-submodules

# 提交时排除子模块
git add --ignore-submodules .
```

---

## 子模块 PR 仓库对照表

| 模块 | 仓库路径 | PR 创建命令 |
|------|----------|-------------|
| Backend | `10CG/todo-app-backend` | `forgejo-api ... repos/10CG/todo-app-backend/pulls` |
| Mobile | `10CG/todo-app-mobile` | `forgejo-api ... repos/10CG/todo-app-mobile/pulls` |
| Shared | `10CG/todo-app-shared` | `forgejo-api ... repos/10CG/todo-app-shared/pulls` |
| Standards | `10CG/ai-ddd-standards` | `forgejo-api ... repos/10CG/ai-ddd-standards/pulls` |
| 主仓库 | `10CG/todo-app` | `forgejo-api ... repos/10CG/todo-app/pulls` |

---

## 相关文档

- [子模块功能边界和定位](../../docs/SUBMODULE_BOUNDARIES_AND_POSITIONING.md)
- [Git Submodule 工作流](../../../standards/workflow/git-submodule-workflow.md)
- [Forgejo API 使用指南](../../docs/FORGEJO_API_GUIDE.md)

---

**Version**: 1.0.0
**Created**: 2025-12-16

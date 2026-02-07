---
name: branch-manager
description: |
  管理 Git 分支的创建、推送和 PR 流程，支持十步循环中的 B.1 和 C.2。

  使用场景：开始新任务时创建分支、完成开发后创建 PR。
argument-hint: "[branch-name]"
disable-model-invocation: false
user-invocable: true
allowed-tools: Bash, Read, Grep
---

# 分支管理器 (Branch Manager)

> **版本**: 2.0.0 | **十步循环**: B.1, C.2
> **更新**: 2026-01-20 - 自动模式决策 (单一入口架构)

## 快速开始

### 我应该使用这个 skill 吗？

**使用场景**:
- B.1: 开始新任务，需要创建功能分支
- C.2: 完成开发，需要推送并创建 PR

**不使用场景**:
- 简单的 commit 操作 → 使用 `commit-msg-generator`
- 跨模块批量提交 → 使用 `strategic-commit-orchestrator`

---

## 核心功能

| 功能 | 十步循环 | 描述 |
|------|---------|------|
| **自动模式决策** | B.1 | 根据任务复杂度智能选择 Branch/Worktree |
| 创建分支 | B.1 | 验证环境 + 创建规范分支 + 推送远程 |
| 创建 PR | C.2 | 推送分支 + 创建 Forgejo PR + 等待审批 |

---

## 自动模式决策 (Auto Mode Decision)

> **新增于 v2.0.0** - 单一入口架构

branch-manager 现在支持**自动模式决策**，根据任务复杂度智能选择：

- **模式 A (Branch)**: 常规分支创建流程，适用于简单修改
- **模式 B (Worktree)**: 隔离工作目录，适用于复杂功能开发

### 模式选择算法

系统根据 5 个维度评分，**总分 >= 3 分时自动选择 Worktree 模式**：

| 评分因素 | 权重 | 评分规则 | 分数 |
|---------|------|---------|------|
| `file_count` | 低 | 1-3 个文件 | 0 |
| | | 4-10 个文件 | +1 |
| | | 10+ 个文件 | +3 |
| `cross_directory` | 中 | 不跨目录 | 0 |
| | | 跨目录 | +2 |
| `task_count` | 低 | 1-3 个任务 | 0 |
| | | 4-8 个任务 | +1 |
| | | 8+ 个任务 | +3 |
| `risk_level` | 中 | 低 (typo, config) | 0 |
| | | 中 (小功能) | +1 |
| | | 高 (重构, API 变更) | +3 |
| `parallel_needed` | 高 | 不需要并行 | 0 |
| | | 需要并行开发 | +5 |

**决策阈值**: `score >= 3` → Worktree, `score < 3` → Branch

### 模式选择示例

```yaml
# 示例 1: 简单 bugfix → Branch 模式
输入:
  files: ["lib/utils.py"]
  task_count: 1
  risk_level: low
评分: 0 + 0 + 0 + 0 + 0 = 0
结果: Branch 模式 (简单快速)

# 示例 2: 中等功能 → Branch 模式
输入:
  files: 3 个 backend 文件
  task_count: 2
  risk_level: medium
评分: 0 + 0 + 0 + 1 + 0 = 1
结果: Branch 模式 (单目录修改)

# 示例 3: 跨模块功能 → Worktree 模式
输入:
  files: 6 个文件 (backend + frontend)
  task_count: 4
  risk_level: high
评分: 1 + 2 + 1 + 3 + 0 = 7
结果: Worktree 模式 (隔离开发环境)

# 示例 4: 并行开发需求 → Worktree 模式
输入:
  parallel_needed: true
评分: 0 + 0 + 0 + 0 + 5 = 5
结果: Worktree 模式 (并行隔离)
```

### Mode 参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `mode` | `auto` (智能决策) \| `branch` (强制分支) \| `worktree` (强制隔离) | `auto` |

### 使用示例

```bash
# 自动模式 (推荐) - 根据任务自动选择
branch-manager --mode auto --task-id TASK-001

# 强制使用 Branch
branch-manager --mode branch --task-id TASK-001

# 强制使用 Worktree
branch-manager --mode worktree --task-id TASK-001
```

### 风险等级自动检测

系统根据描述关键词自动检测风险等级：

| 关键词 | 风险等级 |
|--------|---------|
| typo, format, lint, config, doc | `low` |
| refactor, architecture, api, breaking | `high` |
| 其他 | `medium` |

**详细决策逻辑**: 见 [internal/MODE_DECISION_LOGIC.md](./internal/MODE_DECISION_LOGIC.md)

---

## 环境验证 (Environment Validation)

> **新增于 v2.0.0** | 自动验证开发环境配置

分支创建前，branch-manager 会自动验证开发环境状态，确保可以顺利开始开发。

### 验证项目

| 验证项 | 说明 | 自动修复 |
|-------|------|---------|
| **Git 状态** | 当前分支、工作目录干净度 | 否 |
| **.gitignore** | 必需规则完整性 | 是 |
| **包管理器** | npm/pnpm/poetry/cargo/flutter/go 可用性 | 否 |
| **依赖安装** | node_modules/.venv/ 等依赖目录 | 是 |
| **测试基线** | 可选运行测试确保环境正常 | 否 |

### .gitignore 验证

自动检查以下必需规则：

| 类别 | 规则 |
|------|------|
| 构建产物 | `/build/`, `/dist/`, `/target/`, `*.py[cod]` |
| 依赖 | `/node_modules/`, `.venv/`, `venv/` |
| IDE | `.idea/`, `.vscode/`, `*.swp` |
| 环境变量 | `.env`, `.env.local` |
| Worktree | `.git/worktrees/` |

发现缺失规则时，会提示是否自动添加。

### 开发环境验证

根据项目类型自动检测：

```yaml
Node.js:
  检测文件: package.json
  包管理器: npm, pnpm, yarn
  依赖检查: node_modules/
  测试命令: npm test

Python:
  检测文件: pyproject.toml, requirements.txt
  包管理器: poetry, pip, uv
  依赖检查: .venv/, venv/
  测试命令: pytest

Rust:
  检测文件: Cargo.toml
  包管理器: cargo
  依赖检查: 自动 (无需检查)
  测试命令: cargo test

Flutter:
  检测文件: pubspec.yaml
  包管理器: flutter, dart
  依赖检查: .dart_tool/
  测试命令: flutter test

Go:
  检测文件: go.mod
  包管理器: go
  依赖检查: 自动 (无需检查)
  测试命令: go test ./...
```

### 验证参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `skip_gitignore_check` | 跳过 .gitignore 验证 | `false` |
| `skip_env_check` | 跳过环境验证 | `false` |
| `run_tests` | 运行测试基线 | `false` |
| `auto_fix` | 自动修复发现的问题 | `false` |

### 验证输出

```yaml
成功输出:
  environment:
    gitignore: "valid"
    ecosystem: "nodejs"
    manager: "pnpm"
    manager_version: "8.15.0"
    dependencies: "installed"
    tests: "skipped" | "passed" | "failed"

警告输出:
  warnings:
    - ".gitignore 缺少 /node_modules/ 规则"
    - "依赖未完全安装"

错误输出:
  errors:
    - "找不到包管理器 (npm/pnpm/yarn)"
    - "当前不在 develop 分支"
```

**详细验证逻辑**: 见 [internal/GITIGNORE_VALIDATOR.md](./internal/GITIGNORE_VALIDATOR.md) 和 [internal/ENVIRONMENT_VALIDATOR.md](./internal/ENVIRONMENT_VALIDATOR.md)

---

## B.1: 分支创建

### 触发条件

- A.3 Agent 分配完成
- 用户确认开始开发任务

### 输入参数

| 参数 | 必需 | 说明 | 示例 |
|------|------|------|------|
| `mode` | ❌ | 模式选择 (默认 `auto`) | `auto`, `branch`, `worktree` |
| `module` | ✅ | 目标模块 | `backend`, `mobile`, `shared`, `cross`, `docs`, `standards` |
| `task_id` | ✅ | 任务标识 | `TASK-001`, `ISSUE-42` |
| `description` | ✅ | 简短描述 | `user-auth`, `login-ui` |
| `files` | ❌ | 预期修改的文件列表 (用于自动决策) | `["lib/file.py"]` |
| `task_count` | ❌ | 预计任务数量 (用于自动决策) | `3` |
| `risk_level` | ❌ | 风险等级 (自动检测) | `low`, `medium`, `high` |
| `parallel_needed` | ❌ | 是否需要并行开发 | `true`, `false` |
| `branch_type` | ❌ | 分支类型 (默认 `feature`) | `feature`, `bugfix`, `hotfix`, `release`, `experiment` |
| `in_submodule` | ❌ | 是否在子模块内操作 | `true`, `false` (默认) |

### 执行流程

```yaml
B.1.0 - 模式决策 (mode=auto 时):
  - 收集上下文: files, task_count, risk_level, parallel_needed
  - 执行评分算法 (5 维度评分)
  - 决定模式: score >= 3 → worktree, else → branch
  - 输出决策结果和理由

B.1.1 - 环境验证:
  - 确认当前在正确的工作目录
  - 确认在 develop 分支
  - 确认工作目录干净 (无未提交变更)

B.1.1.5 - .gitignore 验证 (新增):
  - 检查 .gitignore 文件是否存在
  - 验证必需规则 (构建产物、依赖、IDE、环境变量、worktree)
  - 发现缺失? → 提示自动修复

B.1.1.6 - 开发环境验证 (新增):
  - 检测项目类型 (Node/Python/Rust/Flutter/Go)
  - 检查包管理器可用性 (npm/pnpm/poetry/cargo/flutter/go)
  - 检查依赖安装状态
  - 可选: 运行测试基线

B.1.1.7 - 拉取最新代码:
  - git pull origin develop

B.1.2 - 分支创建 (根据模式):
  模式 A - Branch:
    - 生成分支名: {branch_type}/{module}/{task_id}-{description}
    - 创建本地分支: git checkout -b {branch_name}
    - 推送远程: git push -u origin {branch_name}

  模式 B - Worktree:
    - 生成分支名: {branch_type}/{module}/{task_id}-{description}
    - 创建 worktree: git worktree add .git/worktrees/{task_id}-{desc} {branch_name}
    - 输出 worktree 路径
```

### 分支命名规范

| 类型 | 格式 | 示例 |
|------|------|------|
| feature | `feature/{module}/{task-id}-{desc}` | `feature/backend/TASK-001-user-auth` |
| bugfix | `bugfix/{module}/{issue}-{desc}` | `bugfix/mobile/ISSUE-42-login-crash` |
| hotfix | `hotfix/{version}-{desc}` | `hotfix/v1.2.1-security-patch` |
| release | `release/{version}` | `release/v1.3.0` |
| experiment | `experiment/{name}` | `experiment/openspec-pilot` |

### 模块标识符

| 模块 | 标识符 | 说明 |
|------|--------|------|
| Backend | `backend` | Python/FastAPI 服务 |
| Mobile | `mobile` | Flutter 应用 |
| Shared | `shared` | API 契约、schemas |
| Cross-module | `cross` | 多模块变更 |
| Documentation | `docs` | 仅文档变更 |
| Standards | `standards` | AI-DDD 规范 |

### 子模块操作

当 `in_submodule=true` 时：

```bash
# 1. 进入子模块目录
cd {submodule_path}  # 如 backend/, mobile/

# 2. 确保子模块 develop 最新
git checkout develop
git pull origin develop

# 3. 创建分支 (在子模块内)
git checkout -b feature/{module}/{task-id}-{desc}
git push -u origin feature/{module}/{task-id}-{desc}

# 4. 返回主仓库 (提醒用户)
cd ..
# 提醒: 完成后需要在主仓库更新子模块指针
```

---

## Git Worktrees 集成

> **新增于 v1.2.0**

Git Worktrees 允许在同一个仓库中同时检出多个分支到不同的工作目录，实现干净并行的开发。

### 何时使用 Worktrees

| 场景 | 传统方式 | Worktrees 方式 |
|------|----------|----------------|
| 同时开发多个功能 | 频繁切换分支，构建缓存失效 | 每个功能独立目录，构建隔离 |
| 紧急 hotfix | stash 当前工作，切换分支 | 直接在 worktree 中修复 |
| 代码审查 | 切换到 PR 分支查看 | 在 worktree 中并行查看 |

### Worktree 参数

| 参数 | 必需 | 说明 | 示例 |
|------|------|------|------|
| `use_worktree` | ❌ | 是否使用 worktree (默认 `false`) | `true`, `false` |
| `worktree_path` | ❌ | worktree 路径 (默认 `.git/worktrees/`) | custom path |

### 创建 Worktree 分支

```bash
# B.1 with --worktree flag
git worktree add .git/worktrees/{feature-name} feature/{module}/{task-id}-{desc}

# 完整示例
git worktree add .git/worktrees/TASK-001-user-auth feature/backend/TASK-001-user-auth
cd .git/worktrees/TASK-001-user-auth
```

### Worktree 目录结构

```
repository/
├── .git/
│   ├── worktrees/
│   │   ├── TASK-001-user-auth/
│   │   │   ├── .git                # worktree 的 git 文件
│   │   │   ├── lib/
│   │   │   ├── src/
│   │   │   └── tests/
│   │   ├── TASK-002-login-ui/
│   │   │   └── ...
│   │   └── ...
│   └── ...
├── lib/                             # 主分支工作区
├── src/
└── tests/
```

### Worktree 常用命令

```bash
# 列出所有 worktrees
git worktree list

# 创建 worktree
git worktree add <path> <branch>

# 删除 worktree
git worktree remove <path>

# 清理过期的 worktree
git worktree prune

# 移动 worktree
git worktree move <old-path> <new-path>
```

### Worktree 清理

任务完成后，清理 worktree 目录：

```bash
# 切换回主分支
cd ../..

# 删除 worktree
git worktree remove .git/worktrees/TASK-001-user-auth

# 或手动删除
rm -rf .git/worktrees/TASK-001-user-auth
git worktree prune
```

### Worktree 状态检查

```bash
# 检查所有 worktree 状态
git worktree list --porcelain

# 检查当前 worktree 分支
git branch --show-current
```

---

## 输出

```yaml
成功输出 (Branch 模式):
  mode: "branch"
  branch_name: "feature/backend/TASK-001-user-auth"
  location: "main_repo" | "submodule:{name}"
  remote_push: "success"
  decision_reason: "简单修改，使用常规分支"
  next_step: "开始 B.2 执行验证"

成功输出 (Worktree 模式):
  mode: "worktree"
  branch_name: "feature/backend/TASK-001-user-auth"
  worktree_path: ".git/worktrees/TASK-001-user-auth"
  location: "worktree"
  remote_push: "success"
  decision_reason: "跨目录修改，使用隔离环境"
  next_step: "cd 到 worktree 路径开始开发"

失败输出:
  error: "描述错误原因"
  suggestion: "建议的解决方案"
```

---

## C.2: 分支合并 / PR 创建

### 触发条件

- C.1 Git 提交完成
- 用户确认可以创建 PR

### 输入参数

| 参数 | 必需 | 说明 | 示例 |
|------|------|------|------|
| `branch_name` | ❌ | 分支名 (默认当前分支) | `feature/backend/TASK-001-user-auth` |
| `base_branch` | ❌ | 目标分支 (默认 `develop`) | `develop`, `main` |
| `spec_path` | ❌ | Spec 文件路径 | `standards/openspec/changes/auth/spec.md` |
| `issue_number` | ❌ | 关联的 Issue | `123` |
| `merge_strategy` | ❌ | 合并策略 (默认 `squash`) | `squash`, `merge`, `rebase` |
| `auto_merge` | ❌ | 自动合并 (默认 `false`) | `true`, `false` |

### 执行流程

```yaml
C.2.1 - 同步检查:
  - 获取最新的 develop: git fetch origin develop
  - Rebase 到最新: git rebase origin/develop
  - 解决冲突 (如有)

C.2.2 - 推送分支:
  - 推送到远程: git push origin {branch_name}
  - 如果 rebase 后需要: git push --force-with-lease origin {branch_name}

C.2.3 - 创建 PR (Forgejo):
  - 加载环境变量: source ~/.bash_profile
  - 调用 Forgejo API 创建 PR
  - 返回 PR URL

C.2.4 - 等待审批:
  - 输出 PR URL 供用户查看
  - 等待用户确认合并

C.2.5 - 合并 (可选，auto_merge=true 时):
  - 调用 Forgejo API 合并 PR
  - 删除远程分支
  - 删除本地分支
  - 切换回 develop 并更新
```

### PR 标题和正文格式

**标题格式**:
```
{type}({scope}): {中文描述} / {English description}
```

**正文模板**:
```markdown
## Summary

{从 commit 消息或 Spec 提取的摘要}

Implements: `{spec_path}` (如有)
Related Issue: #{issue_number} (如有)

## Changes

- {变更列表，从 git log 提取}

## Test Plan

- [ ] Unit tests pass
- [ ] Integration tests pass (if applicable)
- [ ] Manual testing completed

## Checklist

- [ ] Spec acceptance criteria satisfied
- [ ] Tests passing
- [ ] Documentation updated
- [ ] No security vulnerabilities
```

### Forgejo API 调用

> 🔒 **Cloudflare Access 支持**: 在调用 Forgejo API 前，AI **必须**检查 `forgejo.cloudflare_access.enabled` 配置。详见 `forgejo-sync/CONFIG.md` 中的 Cloudflare Access 章节。

#### API 调用前检查 (不可协商规则)

```yaml
Pre_API_Call_Check:
  1. 读取 forgejo.cloudflare_access.enabled
  2. 如果 enabled == true:
     → 添加 CF-Access-Client-Id 头部
     → 添加 CF-Access-Client-Secret 头部
  3. 如果 API 返回 403/CF 错误:
     → 自动提示用户配置 Cloudflare Access
```

#### 创建 PR

**标准模式** (无 Cloudflare Access):
```bash
curl -X POST "${FORGEJO_API}/repos/10CG/todo-app/pulls" \
  -H "Authorization: token ${FORGEJO_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "{pr_title}",
    "body": "{pr_body}",
    "head": "{branch_name}",
    "base": "{base_branch}"
  }'
```

**Cloudflare Access 模式** (cloudflare_access.enabled = true):
```bash
curl -X POST "${FORGEJO_API}/repos/10CG/todo-app/pulls" \
  -H "Authorization: token ${FORGEJO_TOKEN}" \
  -H "CF-Access-Client-Id: ${CF_ACCESS_CLIENT_ID}" \
  -H "CF-Access-Client-Secret: ${CF_ACCESS_CLIENT_SECRET}" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "{pr_title}",
    "body": "{pr_body}",
    "head": "{branch_name}",
    "base": "{base_branch}"
  }'
```

#### 合并 PR

**标准模式**:
```bash
# squash (推荐)
curl -X POST "${FORGEJO_API}/repos/10CG/todo-app/pulls/{pr_number}/merge" \
  -H "Authorization: token ${FORGEJO_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"Do": "squash"}'

# merge
curl -X POST "${FORGEJO_API}/repos/10CG/todo-app/pulls/{pr_number}/merge" \
  -H "Authorization: token ${FORGEJO_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"Do": "merge"}'
```

**Cloudflare Access 模式** (添加 CF 头部):
```bash
curl -X POST "${FORGEJO_API}/repos/10CG/todo-app/pulls/{pr_number}/merge" \
  -H "Authorization: token ${FORGEJO_TOKEN}" \
  -H "CF-Access-Client-Id: ${CF_ACCESS_CLIENT_ID}" \
  -H "CF-Access-Client-Secret: ${CF_ACCESS_CLIENT_SECRET}" \
  -H "Content-Type: application/json" \
  -d '{"Do": "squash"}'
```

#### 删除远程分支

**标准模式**:
```bash
curl -X DELETE "${FORGEJO_API}/repos/10CG/todo-app/branches/{branch_name}" \
  -H "Authorization: token ${FORGEJO_TOKEN}"
```

**Cloudflare Access 模式**:
```bash
curl -X DELETE "${FORGEJO_API}/repos/10CG/todo-app/branches/{branch_name}" \
  -H "Authorization: token ${FORGEJO_TOKEN}" \
  -H "CF-Access-Client-Id: ${CF_ACCESS_CLIENT_ID}" \
  -H "CF-Access-Client-Secret: ${CF_ACCESS_CLIENT_SECRET}"
```

### 子模块 PR 注意事项

在子模块内创建的分支：

```yaml
子模块 PR 流程:
  1. 在子模块仓库创建 PR (如 10CG/todo-app-backend)
  2. 合并后，回到主仓库
  3. 更新子模块指针:
     - git add {submodule_path}
     - git commit -m "chore(submodule): update {module} pointer"
  4. 主仓库可能也需要创建 PR
```

### 输出

```yaml
成功输出:
  pr_url: "https://forgejo.10cg.pub/10CG/todo-app/pulls/42"
  pr_number: 42
  status: "open" | "merged"
  branch_cleanup: "done" | "pending"
  next_step: "等待审批" | "开始 D.1 进度更新"

失败输出:
  error: "描述错误原因"
  suggestion: "建议的解决方案"
```

---

## 完整工作流示例

### 示例 1: 在主仓库创建功能分支

```yaml
用户请求: "开始 TASK-001 用户认证功能开发"

B.1 执行:
  输入:
    module: backend
    task_id: TASK-001
    description: user-auth
    branch_type: feature
    in_submodule: false

  执行:
    1. git checkout develop && git pull origin develop
    2. git checkout -b feature/backend/TASK-001-user-auth
    3. git push -u origin feature/backend/TASK-001-user-auth

  输出:
    ✅ 分支创建成功: feature/backend/TASK-001-user-auth
    📍 位置: 主仓库
    ➡️ 下一步: 开始 B.2 执行验证
```

### 示例 2: 在子模块内创建分支

```yaml
用户请求: "在 mobile 子模块创建登录 UI 分支"

B.1 执行:
  输入:
    module: mobile
    task_id: TASK-002
    description: login-ui
    in_submodule: true

  执行:
    1. cd mobile/
    2. git checkout develop && git pull origin develop
    3. git checkout -b feature/mobile/TASK-002-login-ui
    4. git push -u origin feature/mobile/TASK-002-login-ui
    5. cd ..

  输出:
    ✅ 分支创建成功: feature/mobile/TASK-002-login-ui
    📍 位置: 子模块 mobile
    ⚠️ 提醒: 完成后需在主仓库更新子模块指针
```

### 示例 3: 创建 PR

```yaml
用户请求: "C.1 完成，创建 PR"

C.2 执行:
  输入:
    branch_name: feature/backend/TASK-001-user-auth
    base_branch: develop
    spec_path: standards/openspec/changes/user-auth/spec.md
    merge_strategy: squash

  执行:
    1. git fetch origin develop
    2. git rebase origin/develop
    3. git push --force-with-lease origin feature/backend/TASK-001-user-auth
    4. source ~/.bash_profile
    5. forgejo-api -X POST ... (创建 PR)

  输出:
    ✅ PR 创建成功
    🔗 URL: https://forgejo.10cg.pub/10CG/todo-app/pulls/42
    📋 状态: 等待审批
    ➡️ 用户确认合并后，执行 D.1
```

---

## 检查清单

### B.1 创建分支前

- [ ] 确认在正确的工作目录（主仓库或子模块）
- [ ] 确认在 develop 分支
- [ ] 确认工作目录干净
- [ ] 确认任务 ID 和描述准确

### C.2 创建 PR 前

- [ ] 确认所有 commit 已完成
- [ ] 确认测试通过
- [ ] 确认文档已更新
- [ ] 确认分支已推送到远程

### C.2 合并后

- [ ] 确认 PR 已合并
- [ ] 确认本地 develop 已更新
- [ ] 确认分支已删除（本地和远程）
- [ ] 如果是子模块，确认主仓库指针已更新

---

## Red Flags (危险信号)

> **新增于 v2.0.0** | 使用 branch-manager 时需要注意的危险信号

### 模式选择 Red Flags

| 场景 | 为什么危险 | 正确做法 |
|------|----------|---------|
| 简单修改使用 Worktree | 开销大于收益，浪费磁盘空间 | 使用 `--mode branch` |
| 复杂跨模块修改使用 Branch | 频繁切换分支，构建缓存失效 | 使用 `--mode worktree` |
| 强制指定模式但不符合实际 | 可能导致后续开发问题 | 信任 `--mode auto` 决策 |

### 环境配置 Red Flags

| 场景 | 为什么危险 | 正确做法 |
|------|----------|---------|
| .gitignore 缺少关键规则 | 可能意外提交敏感文件或构建产物 | 运行 `--auto-fix` 修复 |
| 依赖未安装就开始开发 | 后续测试失败，浪费时间 | 先运行包管理器安装依赖 |
| 跳过测试基线验证 | 环境可能有问题，后续才发现 | 运行 `--run-tests` 验证 |
| 工作目录不干净 | 可能污染新分支 | 先提交或 stash 变更 |

### 分支管理 Red Flags

| 场景 | 为什么危险 | 正确做法 |
|------|----------|---------|
| 从非 develop 分支创建 | 分支基线不正确 | 先 checkout 到 develop |
| 分支名不规范 | 难以识别和管理 | 遵循 `{type}/{module}/{task_id}-{desc}` 格式 |
| 子模块分支忘记更新指针 | 主仓库指针过期 | 完成后更新子模块指针 |
| Worktree 完成后不清理 | 磁盘空间浪费 | 运行 `git worktree prune` 清理 |

### 何时不应使用 branch-manager

| 场景 | 原因 | 替代方案 |
|------|------|---------|
| 紧急 hotfix 到 main | 需要直接修复主分支 | 直接在 main 分支操作 |
| 实验性探索 | 不需要规范分支 | 使用 `experiment/` 前缀但不推远程 |
| 外部贡献者 PR | 使用 GitHub/Forgejo UI | 通过平台界面创建分支 |

---

## 职责边界 (Responsibility Boundaries)

> **新增于 v2.0.0** | branch-manager 的职责范围和限制

### branch-manager 负责什么

| 职责 | 说明 |
|------|------|
| **分支创建** | 自动创建规范命名的分支 |
| **模式选择** | 根据任务复杂度智能选择 Branch/Worktree |
| **环境验证** | 检查开发环境配置是否正确 |
| **远程推送** | 自动推送分支到远程仓库 |
| **PR 创建** | 集成 Forgejo API 创建 PR |

### branch-manager 不负责什么

| 不负责 | 说明 | 谁负责 |
|--------|------|--------|
| **代码编写** | 不涉及具体代码实现 | 开发者 / AI Assistant |
| **测试执行** | 不负责运行完整测试套件 | phase-b-developer (B.2) |
| **代码审查** | 不负责代码质量审查 | subagent-driver |
| **架构同步** | 不负责更新架构文档 | arch-update (B.3) |
| **依赖安装** | 只验证不安装 (除非 auto_fix) | 开发者手动安装 |

### 与其他 Skills 的协作

```
branch-manager (B.1)
    │
    ├─ 输出到 → phase-b-developer (B.2)
    │              ├─ 测试验证
    │              └─ 调用 tdd-enforcer
    │
    ├─ 输出到 → arch-update (B.3)
    │              └─ 架构文档同步
    │
    └─ 输入来自 → task-planner (A.2/A.3)
                   └─ 任务分配信息
```

### 错误处理职责

| 错误类型 | branch-manager 处理 | 上层处理 |
|---------|-------------------|---------|
| 分支已存在 | ❌ 阻止并提示 | 用户选择新 task_id |
| Git 状态异常 | ❌ 阻止并提示 | 用户修复状态 |
| 包管理器缺失 | ⚠️ 警告但继续 | 后续步骤可能失败 |
| .gitignore 缺失 | ✅ 提示并自动修复 | - |
| 磁盘空间不足 | ❌ 阻止并提示 | 用户清理磁盘 |

---

## 错误处理

### 常见错误

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| 工作目录不干净 | 有未提交的变更 | `git stash` 或 commit 变更 |
| 分支已存在 | 分支名冲突 | 选择不同的 task_id 或 description |
| Rebase 冲突 | develop 有新变更 | 手动解决冲突后 `git rebase --continue` |
| PR 创建失败 | Forgejo API 错误 | 检查环境变量和网络连接 |
| 权限不足 | 仓库权限问题 | 联系仓库管理员 |

### 恢复操作

```bash
# 如果分支创建出错，删除分支
git branch -d {branch_name}
git push origin --delete {branch_name}

# 如果 rebase 出错，中止
git rebase --abort

# 如果需要重置到远程状态
git fetch origin
git reset --hard origin/{branch_name}
```

---

## 相关文档

- [十步循环概览](../../../standards/core/ten-step-cycle/README.md)
- [Phase B: 开发执行](../../../standards/core/ten-step-cycle/phase-b-development.md)
- [Phase C: 提交集成](../../../standards/core/ten-step-cycle/phase-c-integration.md)
- [分支管理指南](../../../standards/workflow/branch-management-guide.md)
- [Forgejo API 使用指南](../../docs/FORGEJO_API_GUIDE.md)
- [Git Commit 规范](../../../standards/conventions/git-commit.md)

---

**最后更新**: 2026-01-20
**Skill版本**: 2.0.0 (自动模式决策)

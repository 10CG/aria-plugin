# 子模块处理指南

> **版本**: 2.2.0
> **职责**: Git Submodule 操作参考与最佳实践

本文档提供子模块扫描、提交、引用更新的完整命令参考和最佳实践。

**📚 文档导航**:
- **入口文档** → [SKILL.md](./SKILL.md)
- **类型E流程** → [WORKFLOW_TYPE_E.md](./WORKFLOW_TYPE_E.md)
- **子模块指南（本文档）** → 您正在阅读

---

## 子模块扫描命令

### 获取子模块列表

```bash
# 列出所有子模块及其状态
git submodule status

# 示例输出:
# +abc1234 backend (heads/develop)    # + 表示有未提交的变更
#  def5678 mobile (heads/develop)     # 空格表示同步
# -ghi9012 shared (heads/main)        # - 表示未初始化
```

### 检测子模块内部变更

```bash
# 方法1: foreach 遍历
git submodule foreach --quiet '
  changes=$(git status --short 2>/dev/null | wc -l)
  if [ "$changes" -gt 0 ]; then
    echo "$name:$changes files changed"
  fi
'

# 方法2: 使用 git status
git status --short
# M  standards (modified content, untracked content)
# M  mobile (modified content)
```

### 获取子模块详细变更

```bash
# 进入子模块查看详情
cd standards
git status --short
git diff --stat

# 返回主项目
cd ..
```

---

## 子模块提交流程

### 单个子模块提交

```bash
# 1. 进入子模块
cd {submodule_path}

# 2. 确认变更
git status
git diff --stat

# 3. 分组暂存
git add {files}

# 4. 提交 (使用增强标记)
git commit -m "$(cat <<'EOF'
<type>(<scope>): 中文描述 / English description

<body>

🤖 Executed-By: {subagent} subagent
📋 Context: {Phase}-{Cycle} {context}
🔗 Module: {submodule_name}
EOF
)"

# 5. 记录 hash
echo "Committed: $(git rev-parse --short HEAD)"

# 6. 返回主项目
cd ..
```

### 多个子模块串行提交

```bash
# 定义有变更的子模块列表
CHANGED_SUBMODULES="standards shared"

for submodule in $CHANGED_SUBMODULES; do
  echo "=== Processing $submodule ==="
  cd $submodule

  # 执行提交流程
  # ...

  cd ..
  echo "=== $submodule completed ==="
done
```

---

## 子模块引用更新

### 更新单个子模块引用

```bash
# 将子模块的新 commit 添加到主项目暂存区
git add standards

# 查看将要提交的变更
git diff --cached --submodule

# 提交引用更新
git commit -m "$(cat <<'EOF'
chore(submodule): 更新 standards 子模块引用 / Update standards submodule reference

更新至 abc1234，包含 N 个提交。

🤖 Executed-By: knowledge-manager subagent
📋 Context: {Phase}-{Cycle} {context}
🔗 Module: standards
EOF
)"
```

### 更新多个子模块引用

```bash
# 批量添加
git add standards mobile backend

# 查看变更
git diff --cached --submodule

# 提交
git commit -m "$(cat <<'EOF'
chore(submodule): 更新多个子模块引用 / Update multiple submodule references

更新以下子模块:
- standards: old_hash → new_hash (N commits)
- mobile: old_hash → new_hash (M commits)
- backend: old_hash → new_hash (K commits)

🤖 Executed-By: tech-lead subagent
📋 Context: {Phase}-{Cycle} {context}
🔗 Module: main
🔗 Submodules: standards@new, mobile@new, backend@new
EOF
)"
```

---

## 变更地图结构

### 完整结构定义

```yaml
change_map:
  # 扫描时间戳
  scanned_at: "2026-01-01T10:00:00Z"

  # 主项目变更
  main_project:
    has_changes: boolean
    file_count: number
    files: string[]
    change_type: "B"  # 始终为B
    groups: []  # 分组后填充

  # 子模块列表
  submodules:
    {submodule_name}:
      path: string              # 相对路径
      has_changes: boolean
      file_count: number
      files: string[]           # 变更文件列表
      change_type: "A" | "C"    # 业务模块A，共享基础设施C
      has_upm: boolean          # 是否有UPM文档
      groups: []                # 分组后填充
      commit_hash: string       # 提交后填充
      commit_count: number      # 本次提交数量

  # 执行计划
  execution:
    order: string[]             # 执行顺序
    parallel: boolean           # 是否并行
    strategy: "sequential" | "parallel" | "hybrid"

  # 汇总
  summary:
    total_submodules: number
    changed_submodules: number
    main_has_changes: boolean
    overall_type: "E"
    total_files: number
    estimated_commits: number
```

### 示例

```yaml
change_map:
  scanned_at: "2026-01-01T10:00:00Z"

  main_project:
    has_changes: true
    file_count: 5
    files:
      - .claude/skills/state-scanner/SKILL.md
      - CLAUDE.md
    change_type: B
    groups: []

  submodules:
    standards:
      path: "standards"
      has_changes: true
      file_count: 15
      files:
        - methodology/aria-brand-guide.md
        - core/upm/upm-requirements-extension.md
      change_type: C
      has_upm: false
      groups: []
      commit_hash: null
      commit_count: 0

    mobile:
      path: "mobile"
      has_changes: false
      file_count: 0
      files: []
      change_type: A
      has_upm: true
      groups: []
      commit_hash: null
      commit_count: 0

  execution:
    order: ["standards"]
    parallel: false
    strategy: "sequential"

  summary:
    total_submodules: 5
    changed_submodules: 1
    main_has_changes: true
    overall_type: E
    total_files: 20
    estimated_commits: 8
```

---

## 执行策略配置

### 串行执行 (默认)

```yaml
execution:
  strategy: sequential
  parallel: false
  order:
    - standards    # 1. 基础设施
    - shared       # 2. 契约
    - backend      # 3. 后端
    - mobile       # 4. 前端
    - main         # 5. 主项目 (始终最后)
```

**优点**: 安全、可控、易于调试
**缺点**: 耗时较长

### 并行执行

```yaml
execution:
  strategy: parallel
  parallel: true
  order:
    # 并行组1: 独立子模块
    - [standards, shared]
    # 并行组2: 业务模块
    - [backend, mobile]
    # 串行: 主项目
    - main
```

**优点**: 速度快
**缺点**: 可能有冲突，需要确保子模块间无依赖

### 混合执行

```yaml
execution:
  strategy: hybrid
  phases:
    - name: "基础设施"
      parallel: false
      items: [standards]
    - name: "业务模块"
      parallel: true
      items: [backend, mobile]
    - name: "主项目"
      parallel: false
      items: [main]
```

---

## 常见问题与解决方案

### Q1: 子模块显示 "modified content" 但没有实际变更

```bash
# 原因: 子模块内有未跟踪文件或缓存问题

# 解决方案1: 清理子模块
cd {submodule}
git status
git clean -fd  # 删除未跟踪文件 (谨慎使用)
cd ..

# 解决方案2: 重置子模块
git submodule update --init --recursive
```

### Q2: 子模块引用更新后冲突

```bash
# 原因: 远程有新提交

# 解决方案
git fetch
git submodule update --remote --merge
```

### Q3: 忘记先提交子模块就提交了主项目

```bash
# 回滚主项目提交
git reset --soft HEAD~1

# 先完成子模块提交
cd {submodule}
# ... 提交
cd ..

# 重新添加并提交
git add {submodule}
git commit -m "..."
```

### Q4: 子模块在错误的分支上

```bash
# 切换子模块分支
cd {submodule}
git checkout {correct_branch}
git pull
cd ..

# 更新主项目引用
git add {submodule}
git commit -m "chore(submodule): 切换子模块分支"
```

---

## 子模块变更类型映射

| 子模块 | 路径 | 变更类型 | UPM | 典型Subagent |
|--------|------|---------|-----|--------------|
| standards | `standards/` | C | 无 | knowledge-manager |
| agents | `.claude/agents/` | C | 无 | tech-lead |
| mobile | `mobile/` | A | 有 | mobile-developer |
| backend | `backend/` | A | 有 | backend-architect |
| shared | `shared/` | A | 无 | api-documenter |

---

## 最佳实践

### 1. 提交顺序

```
基础设施 (standards, agents)
    ↓
共享契约 (shared)
    ↓
后端实现 (backend)
    ↓
前端实现 (mobile, frontend)
    ↓
主项目 (main + 子模块引用)
```

### 2. 提交粒度

- 每个子模块独立分组，不跨子模块合并
- 子模块引用更新单独提交
- 大型变更拆分为多个逻辑提交

### 3. 验证流程

```bash
# 每个子模块提交后
git status  # 确认干净

# 所有子模块完成后
git submodule foreach git log -1 --oneline

# 主项目提交后
git log --oneline -10
git submodule status
```

### 4. 错误恢复

- 记录每个子模块提交前的 HEAD
- 子模块失败不影响其他已完成的子模块
- 主项目失败只需回滚主项目

---

*本文档是 strategic-commit-orchestrator v2.2.0 的子模块处理指南。*

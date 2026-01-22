# Branch Finisher (分支完成器)

> **版本**: 1.0.0 | **十步循环**: B.2 (执行验证) → C.1 (提交)
> **更新**: 2026-01-21 - 初始版本

---

description: |
  分支开发完成后的收尾工作执行器。
  负责测试验证、4 选项完成流程、worktree 清理决策。

  特性: 测试前置验证、4 选项完成流程、worktree 清理、与 subagent-driver 集成
---

# 分支完成器 (Branch Finisher)

> **版本**: 1.0.0 | **十步循环**: B.2 → C.1
> **更新**: 2026-01-21 - 初始版本

## 快速开始

### 我应该使用这个 skill 吗？

| 场景 | 使用 branch-finisher? |
|------|----------------------|
| 完成分支开发，准备提交 | ✅ 是 |
| 需要运行测试验证 | ✅ 是 |
| 需要清理 worktree | ✅ 是 |
| 刚开始开发 | ❌ 否，使用 branch-manager |
| 代码审查中 | ❌ 否，使用 subagent-driver |

### 不应该使用的场景

- 分支刚创建 → 使用 branch-manager
- 任务执行中 → 使用 subagent-driver
- 需要创建 PR → 使用 branch-manager (C.2)

---

## 核心功能

| 功能 | 说明 |
|------|------|
| **测试前置验证** | 确保所有测试通过后才能继续 |
| **4 选项完成流程** | 提供标准化的完成选项 |
| **Worktree 清理** | 智能决策是否清理 worktree |
| **状态同步** | 与 subagent-driver 状态同步 |

---

## 执行流程

```
┌─────────────────────────────────────────────────────────────┐
│                  Branch Finisher 执行流程                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. 接收完成信号                                             │
│     ├─ 来自 subagent-driver (所有任务完成)                   │
│     └─ 来自用户手动触发                                      │
│                                                             │
│  2. 测试前置验证                                             │
│     ├─ 运行测试套件                                          │
│     ├─ 检查测试覆盖率                                        │
│     └─ 验证构建成功                                          │
│                                                             │
│  3. 变更摘要                                                 │
│     ├─ 收集所有变更文件                                      │
│     ├─ 统计代码行数变化                                      │
│     └─ 列出完成的任务                                        │
│                                                             │
│  4. 4 选项完成流程                                           │
│     ├─ [1] 提交并创建 PR                                    │
│     ├─ [2] 继续修改                                         │
│     ├─ [3] 放弃变更                                         │
│     └─ [4] 暂停保存                                         │
│                                                             │
│  5. Worktree 清理决策                                        │
│     ├─ 选项 1: 清理 worktree                                │
│     ├─ 选项 2: 保留 worktree                                │
│     └─ 选项 3: 稍后决定                                     │
│                                                             │
│  6. 执行选择的操作                                           │
│     └─ 调用相应的后续 skill                                  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 测试前置验证

### 验证项目

| 验证项 | 说明 | 阻塞级别 |
|--------|------|---------|
| **单元测试** | 所有单元测试通过 | 阻塞 |
| **集成测试** | 集成测试通过 (如有) | 阻塞 |
| **类型检查** | TypeScript/mypy 等类型检查 | 阻塞 |
| **Lint 检查** | ESLint/Pylint 等代码检查 | 警告 |
| **构建验证** | 项目可以成功构建 | 阻塞 |
| **覆盖率检查** | 测试覆盖率达标 (可选) | 警告 |

### 验证流程

```yaml
测试验证流程:
  1. 检测项目类型:
     - Node.js: npm test / pnpm test
     - Python: pytest / python -m unittest
     - Rust: cargo test
     - Flutter: flutter test
     - Go: go test ./...

  2. 运行测试:
     - 执行测试命令
     - 收集测试结果
     - 记录失败的测试

  3. 验证结果:
     - 全部通过 → 继续
     - 有失败 → 阻塞，显示失败详情
     - 有警告 → 显示警告，询问是否继续
```

### 验证输出

```yaml
成功输出:
  tests:
    total: 42
    passed: 42
    failed: 0
    skipped: 0
  coverage: 85%
  build: success
  lint: pass

失败输出:
  tests:
    total: 42
    passed: 40
    failed: 2
    skipped: 0
  failed_tests:
    - test_auth.py::test_login_invalid_password
    - test_auth.py::test_register_duplicate_email
  build: success
  lint: 3 warnings
```

---

## 4 选项完成流程

### 选项定义

```
┌─────────────────────────────────────────────────────────────┐
│                    4 选项完成流程                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  [1] 提交并创建 PR (Commit & PR)                            │
│      → 提交所有变更                                          │
│      → 创建 Pull Request                                    │
│      → 清理 worktree (如适用)                               │
│                                                             │
│  [2] 继续修改 (Continue Editing)                            │
│      → 返回开发状态                                          │
│      → 保留所有变更                                          │
│      → 可以继续使用 subagent-driver                         │
│                                                             │
│  [3] 放弃变更 (Discard Changes)                             │
│      → 撤销所有变更                                          │
│      → 删除分支                                              │
│      → 清理 worktree (如适用)                               │
│                                                             │
│  [4] 暂停保存 (Pause & Save)                                │
│      → 保存当前状态                                          │
│      → 可以稍后恢复                                          │
│      → 保留 worktree                                        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 交互示例

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  ✅ 分支开发完成                                             │
│                                                             │
│  分支: feature/backend/TASK-001-user-auth                   │
│  模式: Worktree (L2 隔离)                                   │
│                                                             │
│  测试验证: ✅ 通过 (42/42)                                   │
│  覆盖率: 85%                                                │
│  构建: ✅ 成功                                               │
│                                                             │
│  变更摘要:                                                   │
│    - 修改: 5 个文件 (+142, -28)                             │
│    - 新增: 2 个文件 (+85)                                   │
│    - 删除: 0 个文件                                         │
│                                                             │
│  完成的任务:                                                 │
│    ✅ TASK-001: 实现用户认证                                 │
│    ✅ TASK-002: 添加登录 API                                 │
│    ✅ TASK-003: 添加注册 API                                 │
│                                                             │
│  请选择下一步:                                               │
│    [1] 提交并创建 PR                                        │
│    [2] 继续修改                                             │
│    [3] 放弃变更                                             │
│    [4] 暂停保存                                             │
│                                                             │
│  选择 [1/2/3/4]: _                                          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Worktree 清理决策

### 清理时机

| 选项 | 清理 Worktree? | 原因 |
|------|---------------|------|
| [1] 提交并创建 PR | ✅ 是 (默认) | 开发完成，不再需要 |
| [2] 继续修改 | ❌ 否 | 还需要继续开发 |
| [3] 放弃变更 | ✅ 是 | 变更已撤销 |
| [4] 暂停保存 | ❌ 否 | 稍后可能恢复 |

### 清理流程

```yaml
Worktree 清理流程:
  1. 确认清理:
     - 显示 worktree 路径
     - 询问用户确认

  2. 执行清理:
     - cd 回主目录
     - git worktree remove {path}
     - git worktree prune

  3. 验证清理:
     - 检查 worktree 已删除
     - 检查分支状态
```

### 清理选项

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  Worktree 清理                                              │
│                                                             │
│  路径: .git/worktrees/TASK-001-user-auth                    │
│  大小: 约 50MB                                              │
│                                                             │
│  请选择:                                                     │
│    [1] 立即清理 (推荐)                                       │
│    [2] 保留 worktree                                        │
│    [3] 稍后决定                                             │
│                                                             │
│  选择 [1/2/3]: _                                            │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 输入参数

| 参数 | 必需 | 说明 | 示例 |
|------|------|------|------|
| `branch_name` | ✅ | 分支名 | `feature/backend/TASK-001-user-auth` |
| `session_id` | ❌ | subagent-driver 会话 ID | `sess-20260121-001` |
| `worktree_path` | ❌ | worktree 路径 (如适用) | `.git/worktrees/TASK-001` |
| `skip_tests` | ❌ | 跳过测试验证 (不推荐) | `false` |
| `auto_cleanup` | ❌ | 自动清理 worktree | `false` |

---

## 输出

```yaml
成功输出 (选项 1):
  action: "commit_and_pr"
  branch_name: "feature/backend/TASK-001-user-auth"
  commit_hash: "abc1234"
  pr_url: "https://forgejo.example.com/repo/pulls/42"
  worktree_cleaned: true
  next_step: "等待 PR 审核"

成功输出 (选项 2):
  action: "continue_editing"
  branch_name: "feature/backend/TASK-001-user-auth"
  worktree_path: ".git/worktrees/TASK-001-user-auth"
  next_step: "继续开发"

成功输出 (选项 3):
  action: "discard_changes"
  branch_deleted: true
  worktree_cleaned: true
  next_step: "返回 develop 分支"

成功输出 (选项 4):
  action: "pause_and_save"
  state_file: ".claude/branch-state/TASK-001.yaml"
  resume_command: "branch-finisher --resume TASK-001"
  next_step: "稍后恢复"
```

---

## 与其他 Skills 集成

### 与 subagent-driver 集成

```yaml
集成点:
  输入:
    - session_id: 从 subagent-driver 获取
    - completed_tasks: 已完成的任务列表
    - changes: 所有变更文件

  触发:
    - subagent-driver 所有任务完成时自动触发
    - 或用户手动调用

  输出:
    - 完成状态反馈给 subagent-driver
    - 更新会话状态
```

### 与 branch-manager 集成

```yaml
集成点:
  选项 1 (提交并创建 PR):
    - 调用 commit-msg-generator 生成提交消息
    - 调用 branch-manager C.2 创建 PR

  选项 3 (放弃变更):
    - 调用 branch-manager 删除分支

  Worktree 清理:
    - 使用 branch-manager 的 worktree 清理模板
```

### 与 tdd-enforcer 集成

```yaml
集成点:
  测试验证:
    - 调用 tdd-enforcer 运行测试
    - 获取测试结果和覆盖率
    - 验证 TDD 流程完整性
```

---

## Red Flags

### 使用 branch-finisher 的危险信号

| 场景 | 为什么危险 | 正确做法 |
|------|----------|---------|
| 跳过测试验证 | 可能提交有 bug 的代码 | 始终运行测试 |
| 测试失败仍提交 | 破坏主分支稳定性 | 修复测试后再提交 |
| 不清理 worktree | 磁盘空间浪费 | 完成后清理 |
| 放弃大量变更 | 工作丢失 | 确认前仔细检查 |

---

## 职责边界

### branch-finisher 负责什么

| 职责 | 说明 |
|------|------|
| **测试验证** | 确保代码质量 |
| **完成流程** | 提供标准化的完成选项 |
| **Worktree 清理** | 管理 worktree 生命周期 |
| **状态同步** | 与其他 skills 协调 |

### branch-finisher 不负责什么

| 不负责 | 说明 | 谁负责 |
|--------|------|--------|
| **代码编写** | 具体实现 | subagent-driver |
| **分支创建** | 创建新分支 | branch-manager |
| **PR 创建** | 创建 Pull Request | branch-manager (C.2) |
| **代码审查** | 审查代码质量 | subagent-driver |

---

## 使用示例

### 基本使用

```bash
# 完成分支开发
branch-finisher --branch feature/backend/TASK-001-user-auth

# 从 subagent-driver 会话恢复
branch-finisher --session sess-20260121-001

# 跳过测试 (不推荐)
branch-finisher --branch feature/backend/TASK-001 --skip-tests

# 自动清理 worktree
branch-finisher --branch feature/backend/TASK-001 --auto-cleanup
```

### 与 workflow-runner 集成

```yaml
# workflow-runner 调用
Phase B:
  B.1: branch-manager --mode auto
  B.2: subagent-driver --tasks ${TASK_LIST}
  B.2.5: branch-finisher --session ${SESSION_ID}  # 新增

Phase C:
  C.1: commit-msg-generator
  C.2: branch-manager --create-pr
```

---

## 相关文档

- [branch-manager](../branch-manager/SKILL.md) - 分支管理
- [subagent-driver](../subagent-driver/SKILL.md) - 子代理驱动
- [tdd-enforcer](../tdd-enforcer/SKILL.md) - TDD 强制执行

---

**最后更新**: 2026-01-21
**Skill版本**: 1.0.0

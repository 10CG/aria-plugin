# Workflow Runner 输出格式

> 工作流执行的标准输出格式定义

## 执行计划

```
╔══════════════════════════════════════════════════════════════╗
║              WORKFLOW EXECUTION PLAN                          ║
╚══════════════════════════════════════════════════════════════╝

Workflow: feature-dev
Phases: A → B → C

───────────────────────────────────────────────────────────────
A.0.5 brainstorm (可选)
   problem 模式            → 问题空间探索
   requirements 模式       → 需求分解
   technical 模式          → 技术方案设计

Phase A (规划)
   A.1 spec-drafter      → Spec 管理 (基于决策预填充)
   A.2 task-planner      → 任务规划
   A.3 task-planner      → Agent 分配

Phase B (开发)
   B.1 branch-manager    → 分支创建
   B.2 test-verifier     → 测试验证
   B.3 arch-update       → 架构同步 (跳过)

Phase C (集成)
   C.1 commit-msg-gen    → Git 提交
   C.2 branch-manager    → PR 创建
───────────────────────────────────────────────────────────────

Execute this workflow? [Yes/No]
```

## 执行报告

```
╔══════════════════════════════════════════════════════════════╗
║              WORKFLOW EXECUTION REPORT                        ║
╚══════════════════════════════════════════════════════════════╝

Workflow: feature-dev
Duration: 2m 15s
Status: SUCCESS

───────────────────────────────────────────────────────────────
PHASE RESULTS:

  Phase A (规划) - 45s
     spec_id: add-auth-feature
     tasks: 5

  Phase B (开发) - 60s
     branch: feature/add-auth
     tests: 15/15 passed (87.5% coverage)

  Phase C (集成) - 30s
     commit: abc1234
     pr: #123
───────────────────────────────────────────────────────────────

Workflow completed successfully!
```

## 使用示例

### 示例 1: 接收推荐执行

```yaml
# state-scanner 推荐
recommendation:
  workflow: quick-fix
  reason: "检测到 3 个文件变更，类型为 bugfix"

# workflow-runner 执行
执行: Phase B → Phase C
结果: commit_sha: "abc1234"
```

### 示例 2: 自定义 Phase 组合

```yaml
输入:
  phases: [B, C]
  config:
    context:
      branch_name: "existing-branch"

执行:
  Phase B: 使用现有分支，运行测试
  Phase C: 提交代码
```

### 示例 3: 仅提交

```yaml
输入:
  workflow: commit-only

执行:
  Phase C: 仅执行 C.1 (commit-msg-generator)
```

---

**来源**: 从 [SKILL.md](../SKILL.md) 输出格式和使用示例章节提取

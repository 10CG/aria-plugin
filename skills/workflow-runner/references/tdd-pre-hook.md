# TDD 双保险 Pre-Hook (v2.1.0)

> **设计目标**: 在工作流级别自动启用 TDD，保护主会话的代码编写

## 方案 B 实现

workflow-runner 是 TDD 双保险中"方案 B"的实现者：

```yaml
workflow-runner (方案 B)
    │
    ├── 检测工作流包含 Phase B
    ├── Pre-Hook: 调用 tdd-enforcer
    │   ├── 启用主会话 TDD Hook
    │   └── 返回 tdd_session_id
    │
    ├──▶ phase-b-developer (方案 A)
    │       └── 传递 TDD 给 subagent-driver
    │           └── 保护 Fresh Subagent
    │
    └── Post-Hook: 可选关闭 TDD Hook
```

## Pre-Hook 触发条件

```yaml
触发条件:
  - 工作流包含 Phase B
  - phase_b_config.tdd.session_level.enabled = true
  - 项目未禁用 TDD (.claude/tdd-config.json)

不触发场景:
  - 工作流不包含 Phase B (如 commit-only)
  - 项目级配置禁用 TDD
  - 文档类工作流 (doc-update)
```

## Pre-Hook 执行流程

```yaml
Pre-Hook 执行:
  1. 检测工作流:
     - 解析 phases 列表
     - 检查是否包含 "B" 或 "phase-b-developer"

  2. 读取 TDD 配置:
     - 读取 .claude/tdd-config.json (如果存在)
     - 或使用 phase_b_config.tdd.session_level

  3. 启用 TDD Hook:
     - 调用 tdd-enforcer skill
     - 传递 strict_mode 和 skip_patterns
     - 获取 tdd_session_id

  4. 记录状态:
     - 保存 tdd_session_id 到上下文
     - 传递给 phase-b-developer
```

## Post-Hook 清理

```yaml
Post-Hook 执行:
  1. 检测 Phase B 完成:
     - phase-b-developer 返回成功状态

  2. 决策 TDD Hook 去留:
     - 默认: 关闭 Hook (释放资源)
     - 可选: 保持 Hook (连续开发场景)

  3. 清理或保持:
     - 关闭: 调用 tdd-enforcer --disable
     - 保持: 记录 tdd_session_id 供后续使用
```

## 配置示例

```yaml
# workflow-runner 输入
workflow: feature-dev
phases: [A, B, C]

config:
  tdd:
    session_level:            # 方案 B 配置
      enabled: true
      strict_mode: false
      skip_patterns:
        - "**/*.md"
        - "**/*.json"
    persist_after_phase_b: false  # Phase B 后是否保持
```

## 执行报告增强

```yaml
执行报告 (v2.1.0):

╔══════════════════════════════════════════════════════════════╗
║              WORKFLOW EXECUTION REPORT                        ║
╚══════════════════════════════════════════════════════════════╝

Workflow: feature-dev
Duration: 3m 45s
Status: SUCCESS

───────────────────────────────────────────────────────────────
TDD 双保险状态:
  方案 A (Fresh Subagent): 启用
  方案 B (主会话):        启用
  tdd_session_id: sess-20260122-001

───────────────────────────────────────────────────────────────
PHASE RESULTS:

  Phase A (规划) - 45s
     spec_id: add-auth-feature
     tasks: 5

  Phase B (开发) - 120s
     branch: feature/add-auth
     tests: 15/15 passed (87.5% coverage)
     tdd_compliance: passed

  Phase C (集成) - 30s
     commit: abc1234
     pr: #123
───────────────────────────────────────────────────────────────

Workflow completed successfully!
```

## 双保险协作

```yaml
完整保护流程:

  [用户] "开发新功能"
     │
     ▼
  state-scanner
     │ 推荐工作流: feature-dev (A→B→C)
     ▼
  workflow-runner
     │
     ├── [Pre-Hook] 方案 B: 启用主会话 TDD
     │   └── tdd-enforcer --enable
     │
     ▼
  phase-a-planner (规划)
     │
     ▼
  phase-b-developer (开发)
     │
     ├── 方案 A: 传递 TDD 配置
     │   └── subagent-driver (tdd_config)
     │       └── Fresh Subagent (TDD 约束)
     │
     └── 用户直接编辑 ← 方案 B 保护
         └── tdd-enforcer Hook 拦截
     │
     ▼
  phase-c-integrator (集成)
     │
     ├── [Post-Hook] 可选关闭 TDD
     │   └── tdd-enforcer --disable
     │
     ▼
  完成
```

---

**来源**: 从 [SKILL.md](../SKILL.md) v2.1.0 TDD 双保险章节提取

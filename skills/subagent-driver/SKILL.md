# Subagent Driver (子代理驱动器)

> **版本**: 1.2.0 | **十步循环**: B.2 (执行验证)
> **更新**: 2026-01-22 - 集成 agent-router 智能路由

---

description: |
  子代理驱动开发 (Subagent-Driven Development) 的核心执行器。
  管理 Fresh Subagent 启动、任务间代码审查、上下文隔离验证。

  特性: Fresh Subagent 模式、任务间代码审查、4 选项完成流程、上下文隔离、TDD 配置传递、智能 Agent 路由
---

# 子代理驱动器 (Subagent Driver)

> **版本**: 1.2.0 | **十步循环**: B.2 (执行验证)
> **更新**: 2026-01-22 - 集成 agent-router 智能路由

## 快速开始

### 我应该使用这个 skill 吗？

| 场景 | 使用 subagent-driver? |
|------|----------------------|
| 需要隔离上下文执行任务 | ✅ 是 |
| 多任务需要独立审查 | ✅ 是 |
| 简单单任务修改 | ❌ 否，直接开发 |
| 需要任务间代码审查 | ✅ 是 |

### 不应该使用的场景

- 单文件简单修改 → 直接编辑
- 紧急 hotfix → 直接修复
- 探索性调试 → 使用 Explore agent

---

## 核心概念

### Subagent-Driven Development (SDD)

```
传统模式:
  主 Agent → 任务1 → 任务2 → 任务3 → 完成
  (上下文累积，可能污染)

SDD 模式:
  主 Agent → Fresh Subagent 1 → 审查 → Fresh Subagent 2 → 审查 → ...
  (每个任务独立上下文，任务间审查)
```

### 核心原则

1. **Fresh Subagent**: 每个任务启动全新的子代理，无历史上下文污染
2. **任务间审查**: 任务完成后，由独立审查者检查代码质量
3. **4 选项完成**: 每个任务完成时提供 4 个选项供用户选择
4. **上下文隔离**: 子代理之间不共享运行时上下文
5. **TDD 传递** (v1.1.0): 将 TDD 配置传递给 Fresh Subagent 强制执行
6. **智能路由** (v1.2.0): 通过 agent-router 自动选择最合适的 Agent

---

## 核心功能

| 功能 | 说明 |
|------|------|
| **Fresh Subagent 启动** | 为每个任务创建全新的子代理实例 |
| **任务间代码审查** | 任务完成后自动触发代码审查 |
| **4 选项完成流程** | 提供标准化的任务完成选项 |
| **上下文隔离验证** | 确保子代理之间上下文独立 |
| **任务状态追踪** | 跟踪每个子代理任务的执行状态 |
| **TDD 配置传递** (v1.1.0) | 将 TDD 约束传递给 Fresh Subagent |
| **Agent 智能路由** (v1.2.0) | 自动选择最合适的专业 Agent |

---

## Fresh Subagent 机制

### 什么是 Fresh Subagent?

Fresh Subagent 是一个全新启动的子代理实例，具有以下特点：

```yaml
Fresh Subagent 特性:
  上下文: 空白 (无历史对话)
  工具访问: 完整 (与主 Agent 相同)
  工作目录: 继承 (或 Worktree 隔离)
  生命周期: 单任务 (任务完成后销毁)
```

### 为什么需要 Fresh Subagent?

| 问题 | 传统模式 | Fresh Subagent |
|------|---------|----------------|
| 上下文污染 | 累积的对话可能误导 | 每次全新开始 |
| 注意力分散 | 长对话导致遗忘 | 专注单一任务 |
| 错误传播 | 早期错误影响后续 | 隔离错误影响 |
| 审查盲区 | 自己审查自己 | 独立审查者 |

### 启动流程

```yaml
Fresh Subagent 启动流程:
  1. 接收任务定义:
     - task_id: 任务标识
     - description: 任务描述
     - files: 相关文件列表
     - acceptance_criteria: 验收标准

  2. 准备上下文:
     - 读取任务相关文件
     - 加载项目配置 (CLAUDE.md)
     - 不加载历史对话

  3. 启动子代理:
     - 创建新的 Agent 实例
     - 传递任务上下文
     - 设置超时和资源限制

  4. 执行任务:
     - 子代理独立完成任务
     - 记录执行日志
     - 收集变更文件列表

  5. 任务完成:
     - 触发 4 选项完成流程
     - 等待用户选择
```

---

## 任务间代码审查

### 审查时机

```
任务 1 完成 → [代码审查] → 任务 2 开始
                  ↓
            发现问题? → 修复后继续
```

### 审查内容

| 审查项 | 说明 | 严重程度 |
|--------|------|---------|
| **代码质量** | 可读性、命名、结构 | 中 |
| **逻辑正确性** | 业务逻辑是否正确 | 高 |
| **安全漏洞** | XSS、SQL 注入等 | 高 |
| **测试覆盖** | 是否有对应测试 | 中 |
| **文档同步** | 注释和文档是否更新 | 低 |

### 审查流程

```yaml
代码审查流程:
  1. 收集变更:
     - git diff 获取变更内容
     - 识别变更文件类型

  2. 启动审查 Agent:
     - 使用 feature-dev:code-reviewer agent
     - 传递变更内容和上下文

  3. 生成审查报告:
     - 问题列表 (按严重程度排序)
     - 建议修复方案
     - 通过/不通过判定

  4. 处理审查结果:
     - 通过 → 继续下一任务
     - 不通过 → 返回修复
```

### 审查报告格式

```yaml
审查报告:
  task_id: "TASK-001"
  reviewer: "code-reviewer"
  timestamp: "2026-01-21T10:30:00Z"

  verdict: "pass" | "fail" | "pass_with_warnings"

  issues:
    - severity: "high"
      file: "src/auth.py"
      line: 42
      message: "SQL 注入风险"
      suggestion: "使用参数化查询"

    - severity: "medium"
      file: "src/auth.py"
      line: 58
      message: "函数过长 (>50 行)"
      suggestion: "拆分为多个小函数"

  summary:
    high: 1
    medium: 1
    low: 0
```

---

## 4 选项完成流程

### 选项定义

每个任务完成时，提供以下 4 个选项：

```yaml
选项 1 - 继续下一任务:
  描述: 当前任务完成，继续执行下一个任务
  触发: 用户确认当前任务满意
  动作: 启动下一个 Fresh Subagent

选项 2 - 修改当前任务:
  描述: 当前任务需要调整
  触发: 用户发现问题或需要改进
  动作: 在当前子代理中继续修改

选项 3 - 回退并重做:
  描述: 放弃当前变更，重新开始
  触发: 当前方向错误，需要重来
  动作: git reset，启动新的 Fresh Subagent

选项 4 - 暂停并保存:
  描述: 保存当前进度，稍后继续
  触发: 需要中断工作
  动作: 保存状态到 .claude/subagent-state/
```

### 交互示例

```
✅ 任务 TASK-001 完成

变更摘要:
  - 修改: src/auth.py (+42, -10)
  - 新增: tests/test_auth.py (+85)
  - 修改: docs/api.md (+15)

代码审查: ✅ 通过 (0 高, 1 中, 2 低)

请选择下一步:
  [1] 继续下一任务 (TASK-002: 实现用户注册)
  [2] 修改当前任务 (继续调整 TASK-001)
  [3] 回退并重做 (放弃变更，重新开始)
  [4] 暂停并保存 (保存进度，稍后继续)

选择 [1/2/3/4]:
```

---

## 上下文隔离验证

### 隔离级别

| 级别 | 说明 | 适用场景 |
|------|------|---------|
| **L1 - 对话隔离** | 不共享对话历史 | 默认级别 |
| **L2 - 文件隔离** | 使用 Worktree 隔离文件系统 | 复杂任务 |
| **L3 - 完全隔离** | 独立进程 + Worktree | 高风险任务 |

### 验证检查

```yaml
上下文隔离验证:
  L1 检查:
    - 子代理无法访问主 Agent 对话历史
    - 子代理无法访问其他子代理的对话
    - 验证方法: 检查 conversation_id 不同

  L2 检查:
    - 子代理工作在独立 Worktree
    - 文件变更不影响主工作目录
    - 验证方法: 检查 pwd 和 git worktree list

  L3 检查:
    - 子代理运行在独立进程
    - 资源使用独立计量
    - 验证方法: 检查 PID 和资源隔离
```

---

## 任务状态追踪

### 状态定义

```yaml
任务状态:
  pending:     等待执行
  in_progress: 正在执行
  reviewing:   代码审查中
  completed:   已完成
  failed:      执行失败
  paused:      已暂停
```

### 状态文件

```yaml
# .claude/subagent-state/current.yaml
session_id: "sess-20260121-001"
started_at: "2026-01-21T09:00:00Z"

tasks:
  - id: "TASK-001"
    status: "completed"
    subagent_id: "sub-001"
    started_at: "2026-01-21T09:00:00Z"
    completed_at: "2026-01-21T09:30:00Z"
    review_result: "pass"
    changes:
      - "src/auth.py"
      - "tests/test_auth.py"

  - id: "TASK-002"
    status: "in_progress"
    subagent_id: "sub-002"
    started_at: "2026-01-21T09:35:00Z"

current_task: "TASK-002"
next_task: "TASK-003"
```

---

## 输入参数

| 参数 | 必需 | 说明 | 示例 |
|------|------|------|------|
| `tasks` | ✅ | 任务列表 | `["TASK-001", "TASK-002"]` |
| `isolation_level` | ❌ | 隔离级别 (默认 L1) | `L1`, `L2`, `L3` |
| `enable_review` | ❌ | 启用任务间审查 (默认 true) | `true`, `false` |
| `review_threshold` | ❌ | 审查严重程度阈值 | `high`, `medium`, `low` |
| `auto_continue` | ❌ | 自动继续下一任务 (默认 false) | `true`, `false` |
| `tdd_config` | ❌ | TDD 配置 (v1.1.0) | 见下方 TDD 配置 |

### TDD 配置 (v1.1.0 新增)

```yaml
tdd_config:
  enabled: true              # 是否启用 TDD
  mode: "enforce"             # enforce | monitor | off
  rules:
    test_before_code: true    # 必须先写测试
    fail_first: true          # 测试必须先失败
    minimal_implementation: true  # 最小实现原则
  skip_patterns:              # 跳过的文件模式
    - "**/*.md"
    - "**/*.json"
    - "**/config/**"
```

**传递机制**:

```yaml
Fresh Subagent 启动时:
  1. 接收 tdd_config
  2. 写入到子代理的系统提示词
  3. 子代理执行时自动应用 TDD 约束
  4. 任务完成后报告 TDD 合规状态

TDD 合规报告:
  tdd_compliance:
    status: "passed" | "failed" | "skipped"
    rules_violated: []
    tests_written: 3
    red_green_cycle: "complete"
```

---

## 输出

```yaml
成功输出:
  session_id: "sess-20260121-001"
  tasks_completed: 3
  tasks_total: 5
  current_status: "in_progress"
  last_review: "pass"
  next_task: "TASK-004"
  tdd_compliance:          # v1.1.0 新增
    status: "passed"
    rules_violated: []
    tests_written: 3

暂停输出:
  session_id: "sess-20260121-001"
  state_file: ".claude/subagent-state/current.yaml"
  resume_command: "subagent-driver --resume sess-20260121-001"

失败输出:
  error: "任务 TASK-002 执行失败"
  task_id: "TASK-002"
  reason: "测试未通过"
  suggestion: "检查 test_auth.py 中的断言"
```

---

## 与 branch-manager 集成

### 协作流程

```
branch-manager (B.1)
    │
    ├─ mode=branch → subagent-driver (L1 隔离)
    │
    └─ mode=worktree → subagent-driver (L2 隔离)
                           │
                           └─ 每个任务在 worktree 中执行
```

### 隔离级别自动选择

```yaml
自动选择规则:
  branch-manager mode=branch:
    → subagent-driver isolation_level=L1
    → 对话隔离，共享文件系统

  branch-manager mode=worktree:
    → subagent-driver isolation_level=L2
    → 对话隔离 + 文件系统隔离

  高风险任务 (risk_level=high):
    → subagent-driver isolation_level=L3
    → 完全隔离
```

---

## Red Flags

### 使用 subagent-driver 的危险信号

| 场景 | 为什么危险 | 正确做法 |
|------|----------|---------|
| 单任务使用 SDD | 开销大于收益 | 直接开发 |
| 禁用代码审查 | 失去质量保障 | 保持 enable_review=true |
| 过高隔离级别 | 资源浪费 | 根据任务复杂度选择 |
| 忽略审查结果 | 问题累积 | 认真处理审查反馈 |

---

## 职责边界

### subagent-driver 负责什么

| 职责 | 说明 |
|------|------|
| **子代理生命周期** | 创建、监控、销毁子代理 |
| **任务分发** | 将任务分配给子代理 |
| **代码审查协调** | 触发和收集审查结果 |
| **状态管理** | 追踪任务执行状态 |

### subagent-driver 不负责什么

| 不负责 | 说明 | 谁负责 |
|--------|------|--------|
| **具体代码实现** | 由子代理完成 | Fresh Subagent |
| **分支管理** | 分支创建和合并 | branch-manager |
| **测试执行** | 运行测试套件 | tdd-enforcer |
| **架构同步** | 更新架构文档 | arch-update |

---

## 使用示例

### 基本使用

```bash
# 启动 SDD 模式执行任务列表
subagent-driver --tasks "TASK-001,TASK-002,TASK-003"

# 使用 L2 隔离级别
subagent-driver --tasks "TASK-001,TASK-002" --isolation-level L2

# 禁用自动审查 (不推荐)
subagent-driver --tasks "TASK-001" --enable-review false

# 恢复暂停的会话
subagent-driver --resume sess-20260121-001
```

### 与 workflow-runner 集成

```yaml
# workflow-runner 调用
Phase B:
  B.1: branch-manager --mode auto
  B.2: subagent-driver --tasks ${TASK_LIST}
  B.3: arch-update
```

---

## 相关文档

- [branch-manager](../branch-manager/SKILL.md) - 分支管理
- [tdd-enforcer](../tdd-enforcer/SKILL.md) - TDD 强制执行
- [phase-b-developer](../phase-b-developer/SKILL.md) - Phase B 编排
- [workflow-runner](../workflow-runner/SKILL.md) - 工作流编排

---

## TDD 配置传递 (v1.1.0 新增)

### 方案 A 实现

subagent-driver 是 TDD 双保险中"方案 A"的实现者：

```yaml
phase-b-developer (B.2)
    │
    ├── tdd_config:
    │   enabled: true
    │   mode: "enforce"
    │
    └──▶ subagent-driver
            │
            ├── 接收 tdd_config
            ├── 传递给 Fresh Subagent
            └── Fresh Subagent 执行时应用 TDD
```

### Fresh Subagent TDD 约束

```yaml
Fresh Subagent 系统提示词增强:

  原始提示词:
    "你是执行 {task} 的子代理..."

  TDD 增强后:
    "你是执行 {task} 的子代理...

    TDD 约束 (强制):
    1. 编写任何业务代码前，必须先编写测试
    2. 测试必须先失败 (RED 阶段)
    3. 编写最小实现使测试通过 (GREEN 阶段)
    4. 仅在测试通过后才能重构 (REFACTOR 阶段)

    违规行为将被阻止并警告。"
```

### 配置优先级

```yaml
TDD 配置优先级 (subagent-driver):

  1. phase-b-developer 传递的 tdd_config
     └── 最高优先级，Phase B 级别

  2. 项目的 .claude/tdd-config.json
     └── 项目级配置

  3. 默认值 (enabled: false)
     └── 兜底
```

---

## Agent 智能路由 (v1.2.0 新增)

### 集成 agent-router

```yaml
subagent-driver 执行流程 (增强版):

  1. 接收任务列表
     └── tasks: [TASK-001, TASK-002, ...]

  2. for each task:
     │
     ├── a. Agent 选择 (新增)
     │   ├── 调用 agent-router
     │   │   ├── task: 任务描述
     │   │   ├── files: 相关文件
     │   │   └── mode: recommend
     │   │
     │   ├── 获取路由结果:
     │   │   ├── auto: 直接使用
     │   │   ├── recommend: 询问用户
     │   │   └── manual: 使用用户指定
     │   │
     │   └── 确定目标 Agent
     │
     ├── b. 准备 Fresh Subagent 上下文
     │   ├── 加载 Agent 配置
     │   ├── 应用 TDD 约束
     │   └── 准备任务上下文
     │
     ├── c. 启动 Fresh Subagent
     │   └── 使用选定 Agent (而非 general-purpose)
     │
     ├── d. 执行任务
     │
     └── e. 任务间审查
```

### 路由模式

```yaml
路由模式配置:

  自动模式 (auto):
    触发: 置信度 >= threshold (默认 0.9)
    行为: 直接使用推荐的 Agent
    示例:
      任务: "实现用户登录 API"
      路由: backend-architect (0.95)
      动作: 自动使用

  推荐模式 (recommend) - 默认:
    触发: 置信度 < threshold 或多个候选
    行为: 展示 Top-3 供用户选择
    示例:
      任务: "优化数据库查询"
      推荐:
        [1] backend-architect (0.85)
        [2] qa-engineer (0.60)
        [3] general-purpose (0.50)
      动作: 等待用户选择

  手动模式 (manual):
    触发: 用户在任务中指定 Agent
    行为: 使用用户指定的 Agent
    示例:
      任务: "用 backend-architect 实现用户认证"
      动作: 直接使用 backend-architect
```

### 配置参数

```yaml
agent_routing:
  enabled: true              # 是否启用智能路由
  default_mode: recommend     # auto | recommend | manual
  confidence_threshold: 0.9   # 自动模式阈值
  max_candidates: 3           # 推荐模式候选数
  fallback_agent: general-purpose  # 无匹配时的兜底

  per_task_overrides:         # 任务级覆盖
    TASK-001:
      agent: backend-architect
      reason: "复杂后端重构"
```

### 执行示例

```yaml
示例 1: 自动匹配

  任务: TASK-001
  描述: "实现用户登录 REST API"
  文件: backend/api/auth.js

  agent-router 输出:
    status: auto_match
    agent: backend-architect
    confidence: 0.95

  subagent-driver 动作:
    - 直接使用 backend-architect
    - 启动 Fresh Subagent
```

```yaml
示例 2: 推荐模式

  任务: TASK-002
  描述: "优化用户注册流程性能"
  文件: backend/api/register.js, database/schema.sql

  agent-router 输出:
    status: recommend
    candidates:
      - [1] backend-architect (0.85)
      - [2] qa-engineer (0.65)
      - [3] general-purpose (0.50)

  subagent-driver 动作:
    - 展示推荐选项
    - 等待用户选择
    - 使用选定的 Agent
```

```yaml
示例 3: 手动指定

  任务: TASK-003
  描述: "用 tech-lead 规划系统重构"
  user_agent: tech-lead

  agent-router 输出:
    status: manual
    agent: tech-lead
    source: user_override

  subagent-driver 动作:
    - 直接使用 tech-lead
    - 启动 Fresh Subagent
```

### 与 TDD 双保险协作

```yaml
完整配置传递:

  phase-b-developer
      │
      ├── tdd_config (TDD 双保险)
      │   └── 传递给 Fresh Subagent
      │
      └── agent_routing (Agent 路由)
          └── 选择专业 Agent

  Fresh Subagent 启动时:
    - Agent: backend-architect (专业)
    - TDD: 启用 (约束)
    - 上下文: 任务相关文件

  结果:
    - 专业 Agent + TDD 约束
    - 高质量、可测试的代码输出
```

---

**最后更新**: 2026-01-22
**Skill版本**: 1.2.0

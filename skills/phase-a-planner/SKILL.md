---
name: phase-a-planner
description: |
  十步循环 Phase A - 规划阶段执行器，编排 A.1-A.3 步骤。

  使用场景："执行规划阶段"、"Phase A"、"创建 Spec 并规划任务"
disable-model-invocation: false
user-invocable: true
allowed-tools: Read, Write, Glob, Grep, Task, Skill, Bash, AskUserQuestion
---

# Phase A - 规划阶段 (Planner)

> **版本**: 1.1.0 | **十步循环**: A.1-A.3

## 快速开始

### 我应该使用这个 Skill 吗？

**使用场景**:
- 需要创建或选择 OpenSpec
- 需要规划任务分解
- 需要分配 Agent 执行
- 新功能开发的第一阶段

**不使用场景**:
- 简单修复 (Level 1) → 直接跳过 Phase A
- 已有 approved Spec → 跳过 A.1
- 已有 detailed-tasks.yaml → 跳过 A.2/A.3

---

## 核心功能

| 步骤 | Skill | 职责 | 输出 |
|------|-------|------|------|
| A.1 | spec-drafter | Spec 创建/选择 | spec_id, spec_status |
| A.2 | task-planner | 任务规划 | task_list, task_count |
| A.3 | task-planner | Agent 分配 | assigned_agents |

---

## 执行流程

### 输入

```yaml
context:
  phase_cycle: "Phase4-Cycle9"    # 当前进度
  module: "mobile"                # 目标模块
  changed_files: []               # 变更文件 (如有)
  user_intent: "开发用户认证"      # 用户意图

config:
  skip_steps: []                  # 跳过的步骤
  params:
    spec_level: 2                 # Spec 级别 (1/2/3)
```

### 前置: REQUIRE claim (A.1, MUST)

**起草任何 Spec 之前**先认领, 不可跳过。

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-aria}/skills/state-scanner/scripts/phase1_gate.py" \
  --raw-track-id "<spec-slug>-<container_uuid>" \
  --phase A.1 --mode advisory \
  --linked-issue "<org>/<repo>#<n>" \
  --include-terminal \
  --repo-path "<主仓根>"
```

**为什么在这里**: 十步循环的 10 轮闸门, 没有任何一条问过「远端是不是已经有人在做同一件事」。
它们审的都是**这份产物做得对不对**, 从不问**它该不该存在** —— 已经有 5 次两个容器对同一个 issue
各自起草、各跑数轮审计、互不知情, 直到一方 ship 才发现。认领必须**早于投入**, 否则它记录的
只是既成事实。

**实参怎么来**:
- `--raw-track-id`: 逐字拼 `<spec-slug>-<container_uuid>` —— slug = 本 Spec 目录名
  `openspec/changes/<slug>/` **逐字**(不预归一, 归一在 CLI 内部做); uuid 段取
  `~/.aria/container-id` 的 **`uuid` 字段**, **不是 `label`** —— 改一行装饰性 label 不该换掉 track-id。
- `--linked-issue`: **两阶段**取法。若
  `${CLAUDE_PLUGIN_ROOT:-aria}/skills/state-scanner/scripts/linked_issue_field_probe.py` 存在,
  实参 = `python3 <该脚本> --emit-arg <本 Spec 的 proposal.md>` 的 stdout(**输出为空 ⇒ 整个参数省略**);
  否则按字段 Spec E6 手工判 —— 只有字段行冒号后首个 code span 的第一个元素形如 `<org>/<repo>#<n>`
  且非哨兵时才传。**哨兵 / `BAD_TOKEN` / `NO_TOKEN` / `NO_FIELD` 一律省略整个参数**,
  绝不可把哨兵当值传: 任何非空字符串都 truthy, 两份毫无关系的 Spec 只要都写哨兵就会互相命中。

**幂等** —— 已经认领过就不要再认领一次:

```yaml
check: coordination ref 内按 (container_id, session_id) 定位到本 session 的 active claim
       (claims/<container>/<session>.yaml 存在且 status == active)
if_missing: 跑上面的命令; 已存在则跳过, 不重复 acquire
```

**输出怎么读 (四态, 两两不同)**:

| 信号 | 含义 | 措辞 |
|---|---|---|
| 键**缺席** | 未检测(没传 `--linked-issue`) | 「本轮未检测」 |
| `linked_issue_overlap == []` | 已检测, 无碰撞 | 「无碰撞」 |
| `unknown_schema_claims > 0` | 有 N 条读不懂 schema 的 claim | 「已检测到 N 条无法解析的 claim —— 存在性已确认、内容未知, **按存在处理**」 |
| `linked_issue_overlap == null` 且 `linked_issue_overlap_error` 非空 | 本轮没取到任何证据 | 「**未能核实**, 建议重试」 |

⚠️ 最后一行绝不可渲染成「无碰撞」—— 零证据不是正证据。同理不要用 `.get(key, [])` / `.get(key, 0)`
去读这几个键, 那正好把四态压成一态。

**退出义务** (两条, 缺一就留下永不释放的僵尸 claim):
- `改名 ⇒ release 旧 + acquire 新` —— Spec 目录改名就是换了 track-id, 必须两步走。
- `放弃方向 ⇒ release_gate.py --raw-track-id <同一串> --status abandoned`

**overlap 非空时按对方 claim 的 `status` 分档请裁**(经 `AskUserQuestion`, 不自行放行):

| 对方 status | 处置 |
|---|---|
| `active` | 有人正在做 —— 请裁: 合并方向 / 换方向 / 确认确实是两件事 |
| `unknown` | 读不懂其 schema, **视同 `active`** 处理(存在性已确认) |
| `done` / `abandoned` | 同一件事可能**已经做完或已被放弃**。按 `active` 同档请裁, 并注明该终态也可能是 GC 产物而非真的做完。**不要提议去释放对方的 claim** —— 那是对方的东西 |

**skip 三条**(其余任何理由都不构成 skip):
1. `state_scanner.coordination.enabled` 显式 `false` ⇒ 本块整体零调用。
2. `skip_if: complexity: Level1` 命中 ⇒ 零调用 —— 否则每个 typo 修复都写一条永不 release 的
   僵尸 claim 外加一次外向 push。
3. `state_scanner.coordination.unattended == true` ⇒ **零 `AskUserQuestion`**: 改为写一条
   「待复议」记录并置 `awaiting_owner`, 由产品负责人事后复议。
   ⚠️ 不得以「AskUserQuestion 现在能不能用」做运行期推断 —— 有没有人可问是**配置事实**。

### 步骤执行

```yaml
A.1 - Spec 管理:
  precondition: 见「前置: REQUIRE claim」小节 (MUST, 在本表之前执行)
  skill: spec-drafter
  skip_if:
    - has_openspec: true          # 已有活跃 Spec
    - complexity: Level1          # 简单任务
  action:
    - 检查现有 Spec
    - 创建新 Spec 或选择现有
  output:
    spec_id: "add-auth-feature"
    spec_status: "approved"

A.2 - 任务规划:
  skill: task-planner
  action: plan
  skip_if:
    - has_detailed_tasks: true    # 已有 detailed-tasks.yaml
  depends_on: A.1
  action:
    - 分解 Spec 为具体任务
    - 生成 tasks.md 和 detailed-tasks.yaml
  output:
    task_list: [TASK-001, TASK-002, ...]
    task_count: 5

A.3 - Agent 分配:
  skill: task-planner
  action: assign
  depends_on: A.2
  action:
    - 为每个任务分配最佳 Agent
    - 更新 detailed-tasks.yaml
  output:
    assigned_agents:
      TASK-001: backend-architect
      TASK-002: mobile-developer
```

### 输出

```yaml
success: true
steps_executed: [A.1, A.2, A.3]
steps_skipped: []
results:
  A.1:
    spec_id: "add-auth-feature"
    spec_status: "approved"
  A.2:
    task_count: 5
  A.3:
    agents_assigned: 5

context_for_next:
  spec_id: "add-auth-feature"
  task_list: [TASK-001, TASK-002, ...]
  assigned_agents: {...}
```

---

## 跳过规则

| 条件 | 跳过步骤 | 检测方法 |
|------|---------|----------|
| 已有活跃 Spec | A.1 | 扫描 openspec/changes/ |
| 复杂度 Level1 | A.1 | 变更文件 ≤3 + 简单类型 |
| 已有 tasks.yaml | A.2, A.3 | 检查 detailed-tasks.yaml |
| **emergency hotfix lane** | A.1, A.2, A.3 | `hotfix/*` 分支 (见下) |

### emergency hotfix lane (#58, v1.35.0, advisory)

prod 紧急修复走 lighter lane (state-scanner `emergency_hotfix` 规则触发, `hotfix/*` 分支)。**跳 Phase A.1-A.3** (无独立 spec; commit body + `Prod-Validated:` trailer 取代)。lane 概览:

- **本 skill (Phase A)**: 跳 A.1-A.3
- **phase-b-developer**: B.2 单测可被 manual prod validation 替代 —— 仅当 commit 含 `Prod-Validated:` trailer + 根因块 (phase-b 机检; 无 → block 回标准 lane)
- **audit-engine / phase-c-integrator**: pre_merge audit (若 enabled) 降级 convergence
- 仍走 Phase C/D

详见各 phase skill + `standards/conventions/git-commit.md §6.4` (Prod-Validated trailer)。

### 跳过逻辑

```yaml
skip_evaluation:
  A.1:
    - condition: openspec/changes/{any}/proposal.md exists
      with_status: [approved, in_progress]
      action: skip A.1, use existing spec_id

  A.2_A.3:
    - condition: detailed-tasks.yaml exists
      with_status: not all completed
      action: skip A.2 and A.3, use existing tasks
```

### Post-Spec 审计 (audit-engine)

```yaml
A.post - 审计引擎 (可选):
  checkpoint: post_spec
  trigger: A.1 完成后 (Spec 创建或更新)
  condition: 读取 .aria/config.json (via config-loader)
             audit.enabled == true
             AND checkpoints.post_spec != "off"

  步骤:
    1. 通过 config-loader 读取 .aria/config.json audit 块
    2. 检查 audit.enabled — false 则跳过，保持现有行为不变
    3. 检查 audit.checkpoints.post_spec — "off" 则跳过
    4. 如启用: 调用 audit-engine
       - checkpoint: "post_spec"
       - mode: 来自配置 (convergence / challenge / adaptive)
       - context: openspec/changes/{spec_id}/proposal.md
    5. 处理 verdict:
       - PASS / PASS_WITH_WARNINGS → 继续执行 A.2
       - FAIL → 阻塞，输出审计报告，提示修订 Spec

  backward_compat:
    audit.enabled=false: 完全跳过，Phase A 行为与之前完全相同
    旧配置 experiments.agent_team_audit: 由 audit-engine 内部映射处理

  fallback_description: |
    audit-engine 内部通过 agent-team-audit 单轮引擎执行审计。
    直接调用 agent-team-audit 已由 audit-engine 编排层取代。

  on_audit_fail: 阻塞进入 A.2，输出审计报告路径
  on_skip: 继续执行 A.2 (审计未启用)
  output:
    audit_verdict: "PASS"         # PASS | PASS_WITH_WARNINGS | FAIL (如启用)
    audit_report: ".aria/audit-reports/post_spec-{timestamp}.md"
```

---

## 输出格式

```
╔══════════════════════════════════════════════════════════════╗
║              PHASE A - PLANNING                              ║
╚══════════════════════════════════════════════════════════════╝

📋 执行计划
───────────────────────────────────────────────────────────────
  A.1 spec-drafter      → 创建/选择 Spec
  A.2 task-planner      → 任务规划
  A.3 task-planner      → Agent 分配

🚀 执行中...
───────────────────────────────────────────────────────────────
  ✅ A.1 完成 → Spec: add-auth-feature (approved)
  ✅ A.2 完成 → 任务数: 5
  ✅ A.3 完成 → Agent 已分配

📤 上下文输出
───────────────────────────────────────────────────────────────
  spec_id: add-auth-feature
  task_count: 5
  ready_for: Phase B
```

---

## 使用示例

### 示例 1: 完整规划

```yaml
输入:
  context:
    user_intent: "添加用户认证功能"
    module: "backend"

执行:
  A.1: 创建 Level 2 Spec → add-auth-feature
  A.2: 分解为 5 个任务
  A.3: 分配 Agent

输出:
  context_for_next:
    spec_id: "add-auth-feature"
    task_list: [TASK-001, ..., TASK-005]
```

### 示例 2: 跳过 A.1

```yaml
输入:
  context:
    openspec_id: "add-auth-feature"  # 已有 Spec

执行:
  A.1: 跳过 (已有 Spec)
  A.2: 规划任务
  A.3: 分配 Agent

输出:
  steps_skipped: [A.1]
```

### 示例 3: 全部跳过

```yaml
输入:
  context:
    has_detailed_tasks: true

执行:
  全部跳过 (已有完整规划)

输出:
  steps_skipped: [A.1, A.2, A.3]
  context_for_next:
    # 使用现有规划数据
```

---

## 错误处理

| 错误 | 原因 | 处理 |
|------|------|------|
| Spec 创建失败 | 信息不足 | 提示用户补充意图 |
| 任务规划失败 | Spec 不完整 | 回退到 A.1 完善 |
| Agent 分配失败 | 未知任务类型 | 使用 general-purpose |

---

## 与其他 Phase 的关系

```
state-scanner
    │
    ▼
phase-a-planner (本 Skill)
    │
    │ context_for_next:
    │   - spec_id
    │   - task_list
    │   - assigned_agents
    ▼
phase-b-developer
```

---

## 相关文档

- [spec-drafter](../spec-drafter/SKILL.md) - A.1 Spec 管理
- [task-planner](../task-planner/SKILL.md) - A.2/A.3 任务规划
- [phase-b-developer](../phase-b-developer/SKILL.md) - 下一阶段

---

**最后更新**: 2026-03-27
**Skill版本**: 1.1.0

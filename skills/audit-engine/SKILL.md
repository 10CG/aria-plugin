---
name: audit-engine
description: |
  多轮收敛审计编排引擎。在十步循环关键检查点编排 agent-team-audit 执行多轮审计，
  通过结论集合比较和投票机制判定收敛，支持 convergence 和 challenge 两种模式。

  触发场景 (由 Phase Skills 调用，非用户直接调用):
  - phase-a-planner 完成 Spec 后 (post_spec)
  - brainstorm 完成后 (post_brainstorm)
  - task-planner 完成后 (post_planning)
  - phase-b-developer 任务进度达阈值 (mid_implementation)
  - phase-b-developer 实现完成后 (post_implementation)
  - phase-c-integrator 合并前 (pre_merge)
  - phase-d-closer 收尾后 (post_closure, 限 convergence + max_rounds=1)
experimental: true
user-invocable: false
allowed-tools: Read, Glob, Grep, Bash, Skill
---

# 审计引擎 (Audit Engine)

> **版本**: 1.0.0 | **状态**: 实验性 (Experimental)
> **创建**: 2026-03-27
> **依赖**: [agent-team-audit](../agent-team-audit/SKILL.md) (单轮执行引擎)

---

## 架构关系

```
audit-engine (多轮编排层)
    |
    | 调用 (每轮)
    v
agent-team-audit (单轮执行引擎)
    |
    | spawn
    v
各 Agent (按检查点配置的 team)
```

**组合而非替代**: audit-engine 负责多轮编排和收敛判定，agent-team-audit 保持为
单轮执行引擎。并发控制、超时策略、去重算法全部复用 agent-team-audit 现有实现。

---

## 输入参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `checkpoint` | string | 是 | 检查点名称 (见下方检查点列表) |
| `mode` | string | 否 | `convergence` / `challenge` / `adaptive`，默认从配置读取 |
| `context` | string | 是 | 被审计内容路径 (proposal.md / diff / UPM) |
| `agents_config` | object | 否 | Agent 分组覆盖，默认从 config.json teams 读取 |

### 检查点列表

| 检查点 | 阶段 | 侧重 | 调用方 |
|--------|------|------|--------|
| post_brainstorm | A | 决策验证 | brainstorm |
| post_spec | A.1 | 决策验证 | phase-a-planner |
| post_planning | A.2 | 质量保障 | task-planner |
| mid_implementation | B.2 | 质量保障 | phase-b-developer (条件触发) |
| post_implementation | B.2 | 质量保障 | phase-b-developer |
| pre_merge | C.2 | 共识构建 | phase-c-integrator |
| post_closure | D.1 | 经验积累 | phase-d-closer |

**post_closure 限制**: 代码已合并，限 convergence 模式 + max_rounds=1，侧重经验提取。

---

## 执行流程

### 入口逻辑

```
1. 读取配置: config-loader → audit.* 块
   - audit.enabled == false → 静默返回
   - checkpoint 未启用 → 静默返回

2. 确定模式:
   - mode 参数显式指定 → 使用指定值
   - audit.mode == "adaptive" → 按 adaptive_rules 推导
   - checkpoints 显式配置 > adaptive_rules 推导 > 默认 off

3. 加载 Agent 分组:
   - agents_config 参数 > config.json teams[checkpoint] > 默认分组

4. 执行审计 (按模式分支)
```

### Convergence 模式

全员讨论 → 汇总引擎 → 结论提取 → 四元组比较 → 收敛/振荡检测。

```
Round N:
  1. 调用 agent-team-audit 单轮引擎
     - spawn Agent team (convergence_agents)
     - 各 Agent 独立分析
     - 返回原始 issues 列表

  2. 汇总引擎处理
     - 合并所有 Agent 输出
     - 去重: 基于 {category, scope} (复用 agent-team-audit 算法)
     - 冲突标记: 同 scope 矛盾意见保留双方, 标记 conflicted
     - 结构化提取: 转换为结论记录 (见数据 Schema)

  3. 收敛判定 (详见收敛判定算法)
     - 四元组集合比较: Round N vs Round N-1
     - 振荡检测: Round N vs Round N-2
     - 全票 PASS 检查

  4. 路由:
     收敛 → 计算 verdict → 生成审计报告
     振荡 → 取最后轮结论 → 报告 + 振荡标记
     未收敛 + 有余量 → Round N+1
     未收敛 + max_rounds 耗尽 → 降级策略
```

### Challenge 模式

讨论组提案 → 挑战组质疑 → 全员合并 → objections resolved 判定。

```
Round N (一个完整周期):
  Step 1: 讨论组 spawn → discussion_output
     - proposal (统一提案文本)
     - decisions [{severity, category, scope, summary}]
     - rationale [string]

  Step 2: 挑战组 spawn (输入: discussion_output) → challenge_output
     - objections [{agent, target_decision, severity, point, status: "new"}]

  Step 3: 全员讨论 (输入: discussion_output + challenge_output) → 修正 proposal

  Step 4: 挑战组再审 (输入: 修正 proposal) → 更新 objections status
     - status: new → resolved | overruled

  收敛判定:
     - 提案结论四元组集合无变化 (vs Round N-1)
     - AND objections 全部 status=resolved (无 unresolved)
     - 满足 → 生成审计报告
     - 不满足 → Round N+1 或降级策略
```

**Round 计数**: 一个 Round = 讨论组提案 + 挑战组质疑的完整周期。
全员合并讨论属于下一 Round 的开头。max_rounds=5 意味着最多 5 个完整周期。

详细 Schema 见 [references/challenge-mode-schema.md](./references/challenge-mode-schema.md)。

---

## 数据 Schema

### 结论记录

每条结论提取为结构化记录:

```json
{
  "id": "auto-generated-hash",
  "type": "decision | issue | risk",
  "severity": "critical | major | minor",
  "category": "architecture | implementation | testing | documentation",
  "scope": "affected module or file",
  "summary": "truncated to 50 words"
}
```

### 四元组 (比较键)

```
comparison_key = {type, severity, category, scope}
```

`summary` 不参与比较，消除 AI 措辞差异的噪声。

### 轮次状态记录

```yaml
round_state:
  round: integer
  conclusions: [conclusion_record]
  comparison_keys: set of tuples
  vote: PASS | REVISE
  incomplete: boolean          # 有 Agent 失败/超时时为 true
  timestamp: ISO 8601
```

---

## 汇总引擎

audit-engine 的内部组件，非独立 Skill。

```
输入: 同一轮所有 Agent 的原始 issues 列表

处理步骤:
  1. 合并: 收集所有 Agent 输出到统一列表
  2. 去重: 基于 {category, scope} 匹配 (复用 agent-team-audit 去重算法)
     - 相同 → 合并 found_by, 取最高 severity
  3. 冲突标记: 同 scope 矛盾意见 → 保留双方, 标记 conflicted: true
     - 不自动裁决, 留给下一轮或人工决策
  4. 结构化提取: 自由文本 → conclusion_record 格式
     - type: 从 issue 内容推断 (decision/issue/risk)
     - severity: 继承 agent-team-audit 的 Critical/Major/Minor
     - category: 归类到 architecture/implementation/testing/documentation
     - scope: 提取 affected module or file
     - summary: 截取前 50 词

输出: [conclusion_record]
```

---

## 收敛判定算法

### 四元组集合比较

```
current_keys  = { (r.type, r.severity, r.category, r.scope) for r in round_N }
previous_keys = { (r.type, r.severity, r.category, r.scope) for r in round_N_minus_1 }

conclusions_stable = (current_keys == previous_keys)
```

### 全票 PASS 检查

```
convergence 模式: convergence_agents 全员 vote == PASS
challenge 模式: objections 全部 status == resolved (无 unresolved)
```

### 振荡检测

```
if N >= 3:
  keys_N   = comparison_keys(round_N)
  keys_N_2 = comparison_keys(round_N_minus_2)

  if keys_N == keys_N_2 and keys_N != keys_N_minus_1:
    → 标记 oscillation: true
    → 取最后轮结论为最终结果
    → 不要求人工介入
```

### 收敛条件汇总

```
converged = conclusions_stable AND unanimous_pass
oscillation = (Round N == Round N-2) AND (Round N != Round N-1)

if converged → 输出最终报告
if oscillation → 取最后轮, 报告标记 oscillation: true
if max_rounds exhausted → 降级策略
else → continue to Round N+1
```

详细算法说明见 [references/convergence-algorithm.md](./references/convergence-algorithm.md)。

---

## 降级策略

当 max_rounds 耗尽且未收敛:

```
1. 展示摘要:
   - 最后轮结论列表
   - 各轮差异对比 (新增/移除的四元组)
   - 未收敛原因分析 (哪些结论在变动)

2. 三路径选择 (AskUserQuestion):
   [1] 接受当前结论
       → converged: false, overridden_by_user: true
       → 继续后续流程

   [2] 增加轮次
       → max_rounds += 2
       → 继续审计循环

   [3] 降级为单轮
       → 取最后轮结论作为最终结果
       → converged: false, degraded: true
```

---

## 错误处理

| 场景 | 行为 |
|------|------|
| Agent spawn 失败 | 跳过该 Agent, 当轮 `incomplete: true`, 不阻塞收敛 |
| Agent 超时 (继承 120s) | 同 spawn 失败处理 |
| API 限流 (529) | 等待 30s 重试一次, 仍失败则跳过 |
| 部分收敛 (结论无变化但有 REVISE) | 继续下一轮 |
| 全部 Agent 失败 | 当轮作废, 输出错误报告, 不计入 max_rounds |

---

## 并发控制

继承 agent-team-audit 参数, 多轮场景补充约束:

| 参数 | 值 | 说明 |
|------|-----|------|
| 单轮并发 | max_parallel: 2, hard_cap: 3 | 每轮内的 Agent 并发 |
| 轮次间 | 串行 | 下一轮依赖上一轮结论 |
| 每轮超时 | 继承 300s/轮 | 独立计时, 不跨轮累计 |
| challenge 组间 | 串行 | 讨论组 → 挑战组 → 全员 (数据依赖) |

---

## 审计报告生成

存储位置: `.aria/audit-reports/{checkpoint}-{timestamp}.md`

### Verdict 计算

```
verdict = PASS               if 0 Critical + 0 Major
verdict = PASS_WITH_WARNINGS  if 0 Critical + >=1 Major
verdict = FAIL               if >=1 Critical
```

继承 agent-team-audit 的 severity/verdict 体系。审计报告同时包含:
- `converged`: 收敛状态 (true/false)
- `verdict`: 质量判定 (PASS/PASS_WITH_WARNINGS/FAIL)

### 组合含义

| converged | verdict | 含义 |
|-----------|---------|------|
| true | PASS | 正常通过 |
| true | PASS_WITH_WARNINGS | 收敛但有 Major 问题 |
| true | FAIL | 收敛但有 Critical 问题, 阻塞流程 |
| false | * | 未收敛, 触发降级策略 |

### 报告 Frontmatter

```yaml
---
checkpoint: {checkpoint_name}
mode: convergence | challenge
rounds: {N}
converged: true | false
oscillation: false
overridden_by_user: false
degraded: false
verdict: PASS | PASS_WITH_WARNINGS | FAIL
timestamp: {ISO 8601}
context: {被审计内容路径}
agents: [{agent_list}]
---
```

详细报告格式见 [references/report-format.md](./references/report-format.md)。

---

## 配置依赖

通过 `.aria/config.json` 的 `audit.*` 块控制。参见 [config-loader](../config-loader/SKILL.md)。

```yaml
关键字段:
  audit.enabled: boolean        # 总开关, 默认 false
  audit.mode: string            # adaptive | convergence | challenge | manual
  audit.max_rounds: integer     # 默认 5
  audit.checkpoints: object     # 各检查点 off/convergence/challenge
  audit.teams: object           # 各检查点 Agent 分组
  audit.adaptive_rules: object  # Level → mode 映射
  audit.mid_implementation: object  # 条件触发配置
```

**优先级**: checkpoints 显式配置 > adaptive_rules 推导 > 默认 off

**旧配置兼容**: `experiments.agent_team_audit: true` 自动映射为
`audit.enabled: true` + `audit.mode: "manual"` + 旧触发点映射。

---

## 相关文档

- [references/convergence-algorithm.md](./references/convergence-algorithm.md) -- 收敛判定详细算法与边界情况
- [references/challenge-mode-schema.md](./references/challenge-mode-schema.md) -- Challenge 模式完整数据流
- [references/report-format.md](./references/report-format.md) -- 审计报告完整格式规范
- [agent-team-audit](../agent-team-audit/SKILL.md) -- 单轮执行引擎 (被本 Skill 调用)

---

**最后更新**: 2026-03-27

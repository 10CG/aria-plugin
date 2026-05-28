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

### Pre-merge: Checkpoint Report Completeness Gate

> **新增**: 2026-04-23, 修复 Forgejo Issue #26 checkpoint 完整性 gate — 与 Issue #27
> (change_id dangling reference gate, 见"审计报告生成 → Pre-write Validation"章节) 互补。
>
> **#26 + #27 互补说明**:
> - **#26 (本节)** = 横向完整性 — 该跑的 checkpoint 都跑了 (completeness)
> - **#27 (写盘前)** = 纵向真实性 — 报告引用的 change_id 都真实存在 (authenticity)
> 两者均在 pre_merge 阶段运行，错误输出均走 audit trail。

**触发条件**: 仅在 `checkpoint == "pre_merge"` 时执行，在调用任何 Agent 之前运行。

```
Checkpoint Report Completeness Gate (pre_merge 专属):

  Step 1: 读取配置
    config-loader → audit.checkpoints.*
    config-loader → audit.allow_incomplete_checkpoints (默认 false)

  Step 2: 豁免检查
    如果 audit.allow_incomplete_checkpoints == true
      → 跳过校验，继续执行 pre_merge 审计
      → 记录 [WARN] incomplete checkpoint gate bypassed by config，写入 audit trail

  Step 3: 枚举需校验的 checkpoint
    对 audit.checkpoints 中每个 key，满足以下全部条件则纳入校验：
      - value == "on"（字符串）或 value 为非 "off" 的模式字符串
      - key != "pre_merge"（排除自身）
      - key != "post_closure"（事后审计，不做前置依赖）

  Step 4: 检查报告文件存在性
    对每个纳入校验的 checkpoint_name：
      扫描目录: {project_root}/.aria/audit-reports/
      匹配模式:
        - {checkpoint_name}-*.md         (无 change_id 变体)
        - {checkpoint_name}-*-*.md       (含 change_id 变体)
      任意文件匹配 → 该 checkpoint 通过
      无文件匹配   → 记录为 missing_checkpoint

  Step 5: 校验结果路由
    missing_checkpoints 为空 → 校验通过，进入正常 pre_merge 审计流程
    missing_checkpoints 非空 → 拒绝执行 pre_merge 审计，输出 ERROR (见下方)，中止
```

**校验失败输出**:

```
ERROR: pre_merge audit 前序 checkpoint 报告缺失:
  - {checkpoint_name} 配置 "on" 但未找到 .aria/audit-reports/{checkpoint_name}-*.md
  [若多个缺失则逐行列出]

Fix 任一:
  1. 补跑缺失 checkpoint 审计 (对应 Phase Skill 重新调用)
  2. 在 .aria/config.json 将该 checkpoint 改为 "off" (若本轮确实不需要)
  3. 在 .aria/config.json 设 audit.allow_incomplete_checkpoints: true
     (不推荐, 豁免需 audit trail 记录 [WARN])
```

**豁免设计原则**: `allow_incomplete_checkpoints` 默认 `false`，需在 `.aria/config.json`
显式声明才能开启。豁免模式下 pre_merge 审计继续执行，但 audit trail 必须记录
`[WARN] incomplete checkpoint gate bypassed: missing={checkpoint_names}`。

---

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
  "id": "<sha256(category + ':' + scope + ':' + severity + ':' + type)[:8]>",
  "type": "decision | issue | risk",
  "severity": "critical | major | minor",
  "category": "architecture | implementation | testing | documentation",
  "scope": "affected module or file",
  "summary": "truncated to 50 words"
}
```

**`id` 字段哈希规范** (mechanical determinism, v1.17.5+):

```python
import hashlib
def finding_id(category: str, scope: str, severity: str, type: str) -> str:
    canonical = f"{category}:{scope}:{severity}:{type}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8]
```

**输入字段** (与 4-tuple `comparison_key` 对齐, 顺序固定):
1. `category` (architecture | implementation | testing | documentation)
2. `scope` (affected module or file path)
3. `severity` (critical | major | minor)
4. `type` (decision | issue | risk)

**输入字段不包括**: `summary` (LLM 措辞每轮不同, 哈希污染), `timestamp` (轮次间漂移),
`agent_role` (跨 agent 同 finding 应同 ID).

**输出**: 8 字符 hex prefix (e.g. `a3f2c9b1`), 足够 4-tuple 笛卡尔积去重 (~10^4 量级远低于 16^8 = ~4.3×10^9).

**为何 SHA-256**: 跨语言/跨 agent 可复现 (Python stdlib + JS crypto + LLM 心算近似都能产生一致结果);
truncate to 8 chars 兼顾可读性 (报告文件名 + inline fix 引用 `R1-a3f2c9b1`).

**跨轮稳定性保证**:
- 同一 finding 在 R1 / R2 / RN 由不同 agent 报告 → 同 8-char ID
- finding 升级 severity (minor → major) → ID 改变 (符合 4-tuple `comparison_key` 不收敛逻辑)
- finding 改 category/scope → ID 改变 (设计如此, 表示语义变化)

详见 `references/convergence-algorithm.md` "comparison_key 与 finding.id 关系" 章节。

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

### Agent dispatch contract: 强制 frontmatter 输出 (Forgejo Issue #126, 2026-05-28)

> **不可协商**: 任何通过 audit-engine spawn 的 agent (经由 agent-team-audit, 含 convergence /
> challenge 模式所有 round) 必须在 agent prompt 中嵌入 frontmatter template 要求, 否则 agent
> 自由发挥会导致 audit report 缺 YAML frontmatter, dashboard parser 无法解析 (40% reports
> 在 Issue #126 dogfood 中无 frontmatter, 最新 R1/R2 audit 全部不可见)。

**调用方契约** (Phase Skills → audit-engine → agent-team-audit → Agent):

在 dispatch agent 时, prompt **必须** 显式包含以下指令 (原文嵌入, 不得简化):

```
你的输出必须以 YAML frontmatter 开头, 严格按以下 template (字段全填, 不要省略):

---
checkpoint: {checkpoint_name}      # post_spec / post_implementation / pre_merge / post_closure 等
mode: convergence | challenge       # 当前 audit 模式
rounds: {N}                         # 本 agent 参与的当前 round 号 (R1/R2/...)
converged: {true|false|null}        # 本 round 后是否收敛 (单 agent 视角无法判定时填 null)
oscillation: false                  # 振荡标记 (单 agent 默认 false, 由 audit-engine 聚合时覆盖)
overridden_by_user: false           # owner 强制 override 标记
degraded: false                     # 降级模式标记
verdict: PASS | PASS_WITH_WARNINGS | FAIL   # 本 agent 视角的 verdict
timestamp: {ISO 8601 ms}            # 你的输出生成时间 (UTC, 如 2026-05-28T13:24:00.123Z)
context: {被审计内容路径或 spec_id}
agents: [{your_role}]               # 单元素数组, 如 [tech-lead] 或 [qa-engineer]
---

(frontmatter 之后是 Markdown 正文, 含 ## 审计结论 / ## Verdict / ## 轮次记录 等章节)
```

**完整模板**: 见 [references/report-format.md](./references/report-format.md)。
**Phase Skill 调用方**: phase-a-planner / phase-b-developer / phase-c-integrator / phase-d-closer
在调用 audit-engine 时, 由 audit-engine 自身负责把上述指令注入 agent prompt — 调用方传入
checkpoint / mode / context / agent_role 等参数即可, 不需要重复 frontmatter 模板。

**违反后果**: agent 输出无 frontmatter → dashboard parser 跳过该报告 (Issue #126 实测 40% 丢失) →
audit history 不可见 → 跨项目 dogfood 时 owner 误判 "最近无 audit"。

**Backward-compat for legacy reports** (Issue #126 fix 之前生成的 42 个无 frontmatter 报告):
aria-dashboard parse-audit 已加 markdown-header fallback (parser 优先 frontmatter, 缺失时
扫描 `**Verdict**:` / `**Date**:` / `**Round**:` 等 markdown header 行)。新报告强制 frontmatter,
旧报告通过 fallback 兜底可见 — 但 fallback 字段不全, owner 倾向跑 one-shot backfill 时,
脚本路径预留为未来 follow-up (本 fix 不强制 backfill, 仅供给侧约束 + 消费侧 fallback)。

---

### Pre-write Validation: change_id 锚点检查

> **新增**: 2026-04-23, 修复 Forgejo Issue #27 dangling reference — 与 Issue #26 FR-1
> (checkpoint 报告完整性 gate) 互补。

在任何审计报告写盘前，必须先验证 `change_id` 有对应的 proposal.md 背书。
验证在 verdict 计算完成后、文件 I/O 开始前执行。

```
Pre-write validation (写盘前强制执行):

  输入: change_id (从调用方 context 读取)

  Step 1: 检查豁免配置
    config-loader → audit.allow_dangling_change_ids
    如果 == true → 跳过校验, 直接写盘 (记录 warn 级日志)

  Step 2: 查找活跃 Spec
    路径: {project_root}/openspec/changes/{change_id}/proposal.md
    存在 → 校验通过, 继续写盘

  Step 3: 查找已归档 Spec (通配日期前缀)
    路径: {project_root}/openspec/archive/*-{change_id}/proposal.md
    任意匹配 → 校验通过, 继续写盘

  Step 4: 校验失败
    → 拒绝写盘
    → 输出以下 ERROR 并中止:
```

```
ERROR: change_id "{change_id}" 未在 openspec/changes/ 或 openspec/archive/ 找到对应 proposal.md
Fix 任一:
  1. 创建 openspec/changes/{change_id}/proposal.md 并 draft
  2. 归档的 change 确认命名匹配 (archive/{YYYY-MM-DD}-{change_id}/)
  3. 在 .aria/config.json 设 audit.allow_dangling_change_ids: true (不推荐, 仅临时)
```

**作用域**: 所有 checkpoint 均受此校验保护 (post_spec / pre_merge / post_closure 等)。
审计 mode (convergence / challenge) 不影响校验逻辑。

**豁免设计原则**: `allow_dangling_change_ids` 默认 `false`，需在 `.aria/config.json`
显式声明才能开启。豁免不改变 ERROR 为 WARN 的语义 — 写盘仍执行，但日志必须记录
`[WARN] dangling change_id allowed by config: {change_id}`，便于事后审计。

---

存储位置 (v1.17.4+ 唯一性 schema):

```
.aria/audit-reports/{checkpoint}-R{round}-{timestamp_ms}-{spec_id}-{agent_role}.md
```

**字段定义**:

| 字段 | 来源 | 示例 |
|---|---|---|
| `{checkpoint}` | audit-engine config (post_spec / pre_merge / post_implementation 等) | `pre_merge` |
| `{round}` | audit-engine 内部计数器 (R1=首轮, R2..N=收敛轮) | `R1` |
| `{timestamp_ms}` | UTC 毫秒精度 ISO 8601 (替换 `:` 为 `-` 兼容文件系统) | `2026-04-25T220340-123Z` |
| `{spec_id}` | OpenSpec change_id (从 dispatch context) | `audit-engine-report-filename-uniqueness` |
| `{agent_role}` | 4-agent fixed roster | `qa-engineer` / `code-reviewer` / `backend-architect` / `tech-lead` |

**完整示例**:
```
.aria/audit-reports/pre_merge-R1-2026-04-25T220340-123Z-audit-engine-report-filename-uniqueness-qa-engineer.md
```

**碰撞防护设计**:
- `agent_role` suffix 区分 4 个并行 dispatch 的 agent (即使同毫秒落盘也不冲突)
- `timestamp_ms` 毫秒精度 (1ms 内 4 个文件并行写, agent_role 兜底唯一性)
- `R{round}` 区分多轮收敛输出 (R1 / R2 / R3 不冲突)
- `{spec_id}` 区分多 Spec 共享同 round 的并发审计

**向后兼容 (reader 行为)**:
- audit-engine 扫描 `.aria/audit-reports/*.md` 时同时接受新旧 schema
- 旧文件名 `{checkpoint}-{timestamp}.md` (无 round/role suffix) 视为单 agent 单轮 (R1, role=`legacy`)
- finding aggregation 时 legacy 文件归入对应 checkpoint 的 R1, 与新 R1 文件并集
- writer 仅生成新 schema (本 Spec 合并即生效, 不再回写旧格式)

**为何引入此 schema** (Round-2 audit P0.2 finding):
旧 schema `{checkpoint}-{timestamp}.md` 时间戳实际粒度仅到分钟/秒, 4-agent strict 模式
并行 dispatch → 同一秒/分钟落盘 → 后写覆盖前写, agent finding 永久丢失,
导致 `R_N == R_{N-1}` 收敛比较缺少完整 finding 集。新 schema 通过
`{round}-{timestamp_ms}-{agent_role}` 三重唯一性消除碰撞。

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
  audit.allow_dangling_change_ids: boolean  # 默认 false — 豁免 change_id 锚点校验
                                            # 仅用于临时场景 (如遗留 change_id 迁移期)
                                            # 开启后写盘仍执行但记录 [WARN] 日志
                                            # (2026-04-23 新增, 修复 Issue #27)
  audit.allow_incomplete_checkpoints: boolean  # 默认 false — 豁免 pre_merge 前序 checkpoint
                                               # 报告完整性校验
                                               # 开启后 pre_merge 仍执行但记录 [WARN] 日志
                                               # (2026-04-23 新增, 修复 Issue #26)
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

**最后更新**: 2026-04-23 (Issue #26: checkpoint 完整性 gate + Issue #27: change_id 锚点校验)

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

4 阶段: (1) 入口逻辑 (config + mode + agents 加载) → (2) **Pre-merge gate** — `pre_merge` checkpoint 专属横向完整性检查 (Issue #26, 与 #27 互补) → (3) **Convergence 模式** (全员讨论 → 汇总 → 四元组比较 → 收敛/振荡) → (4) **Challenge 模式** (讨论组+挑战组对抗 → objections resolved 判定)。

**完整流程定义 (4 阶段 详细 step / pre_merge gate 5-step 流程 + 错误输出 / convergence 4-step / challenge 4-step + Round 计数)**: 见 [references/execution-modes.md](./references/execution-modes.md)。

**Schema 细节**: convergence 见 [references/convergence-algorithm.md](./references/convergence-algorithm.md), challenge 见 [references/challenge-mode-schema.md](./references/challenge-mode-schema.md)。

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

### Agent dispatch contract (v1.30.1+)

audit-engine 在 dispatch agent (经 agent-team-audit) 时**必须**把 8-field YAML frontmatter template 嵌入 prompt 原文, 否则 agent 自由发挥会导致 audit report 缺 frontmatter, dashboard parser 无法解析 (Forgejo Aria #126 实测 40% 报告无 frontmatter 不可见)。

**完整契约 + 模板原文 + 责任分工 + backward-compat**: 见 [references/agent-dispatch-contract.md](./references/agent-dispatch-contract.md)。

### Pre-write validation: change_id 锚点检查 (2026-04-23, Issue #27)

写盘前验证 `change_id` 有对应的 `openspec/changes/{id}/proposal.md` 或 `openspec/archive/*-{id}/proposal.md` 背书; 缺失则拒绝写盘并提示 fix。豁免开关: `.aria/config.json` `audit.allow_dangling_change_ids=true` (默认 false)。

**完整 4-step 验证流程 + ERROR 提示文本 + 豁免设计**: 见 [references/pre-write-validation.md](./references/pre-write-validation.md)。

---

### 报告存储 + Verdict (v1.17.4+ schema)

存储路径: `.aria/audit-reports/{checkpoint}-R{round}-{timestamp_ms}-{spec_id}-{agent_role}.md` — 5-field uniqueness schema 防 4-agent 并行同毫秒落盘碰撞 (Round-2 audit P0.2 fix)。

Verdict 计算: PASS (0 Critical + 0 Major) / PASS_WITH_WARNINGS (0 Critical + ≥1 Major) / FAIL (≥1 Critical)。报告 frontmatter 11 字段含 checkpoint/mode/rounds/converged/verdict/timestamp 等。

**完整 schema (5-field uniqueness 字段定义 / 碰撞防护 / backward-compat reader / 引入背景) + Verdict 计算 + converged×verdict 组合含义 + 报告 Frontmatter 模板**: 见 [references/report-storage.md](./references/report-storage.md)。

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

### file-scope 二次过滤 (#58, v1.35.0)

mode **解析完成后** (checkpoints/adaptive_rules 得出 `resolved_mode`), 加一道 **file-scope 二次判定** —— 当本次变更**全部** ⊆ `audit.scope_skip_paths` (ops/docs-only) 时, 把 mode cap 到 convergence (challenge → convergence; off/convergence 不变)。避免 ops-only / docs-only PR 跑无意义 challenge audit (~5min vs 15-30min)。

> **仅 audit-on 项目生效** (audit 默认全 off)。**降级非 skip** (DEC-4): issue #58 实证 deploy script 改动 challenge 能找到真退化 (wget HTTP 4xx 退出 0) → deploy 不能全 skip, convergence 保留安全网。

```
# 变更文件来源: audit-engine 自取 (不读 snapshot — audit-engine 由 Phase Skill 调用)
base = .aria/config 配置的 base  OR  git symbolic-ref refs/remotes/origin/HEAD
       (fallback origin/main → origin/master; 全部失败 → file-scope skip + warn, 不 crash)
changed_files = git diff --name-only $(git merge-base HEAD <base>)
  # merge-base diff: 捕获 base→工作树的 committed+staged+unstaged 全部变更, 跨 checkpoint 正确
  # (注: 不能用 `git diff HEAD` — pre_merge 时 hotfix 已 commit 到 HEAD, diff HEAD 会漏掉)

if len(changed_files) == 0:            # 防 vacuous-true 空集误触
    pass-through (不降级)
elif all(f matches scope_skip_paths for f in changed_files):
    resolved_mode = min(resolved_mode, convergence)   # challenge → convergence
else:                                   # 任一业务文件 ∉ skip_paths
    resolved_mode 不变 (标准 audit)

# 匹配语义: 目录项 (尾斜杠规范化, 如 "deploy/") → path.startswith(prefix)
#          后缀项 (如 "*.md") → path.endswith(".md")
```

### emergency hotfix lane: pre_merge → convergence (#58)

当 emergency_hotfix lane (state-scanner `emergency_hotfix` 规则触发) 时, pre_merge audit **仅 `audit.enabled=true` 且 pre_merge checkpoint != off** 时降级到 convergence (不 challenge)。与 file-scope 过滤双降级时幂等 (都 → convergence)。phase-c-integrator 在 pre_merge 调用点传递此 lane 信号。

---

## 相关文档

- [references/convergence-algorithm.md](./references/convergence-algorithm.md) -- 收敛判定详细算法与边界情况
- [references/challenge-mode-schema.md](./references/challenge-mode-schema.md) -- Challenge 模式完整数据流
- [references/report-format.md](./references/report-format.md) -- 审计报告完整格式规范
- [agent-team-audit](../agent-team-audit/SKILL.md) -- 单轮执行引擎 (被本 Skill 调用)

---

**最后更新**: 2026-04-23 (Issue #26: checkpoint 完整性 gate + Issue #27: change_id 锚点校验)

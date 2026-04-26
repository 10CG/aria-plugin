# 收敛判定算法详解 (Convergence Algorithm)

## 概述

收敛判定是 audit-engine 的核心机制，确保多轮审计在意见稳定时自动终止，
避免无限循环和资源浪费。

---

## 四元组集合比较

### 比较键定义

每条结论提取四元组作为比较键:

```
comparison_key = (type, severity, category, scope)
```

| 字段 | 值域 | 示例 |
|------|------|------|
| type | decision, issue, risk | issue |
| severity | critical, major, minor | major |
| category | architecture, implementation, testing, documentation | testing |
| scope | 模块或文件路径 | src/auth.ts |

**为何排除 summary**: AI 每轮措辞不同但含义相同，summary 参与比较会导致
永远无法收敛。四元组捕获结论的结构化本质。

**`finding.id` 与 `comparison_key` 的关系** (v1.17.5+):

`finding.id = sha256(category:scope:severity:type)[:8]` 是 `comparison_key` 的
**确定性投影**, 两者同步: 4-tuple 相等 ⇔ ID 相等。

这意味着:
- 集合比较可用 ID 集合 (更快, O(N) 哈希查找) 或 4-tuple 集合 (更显式) 任选其一
- 跨 agent 报相同 finding → 同 ID, 不重复计数
- audit-driven fix inline 注释 `R1-a3f2c9b1 fix: ...` 跨轮稳定可追溯
- 详细哈希函数规范见 `aria/skills/audit-engine/SKILL.md` "结论记录" 章节

### 集合比较逻辑

```
current_set  = { key(r) for r in round_N.conclusions }
previous_set = { key(r) for r in round_N_minus_1.conclusions }

conclusions_stable = (current_set == previous_set)

其中 == 表示集合相等:
  - current_set 中每个元素都在 previous_set 中
  - previous_set 中每个元素都在 current_set 中
  - 两集合大小相同
```

### 边界情况

| 情况 | 处理 |
|------|------|
| Round 1 (无上一轮) | 无法判定收敛, 必须进入 Round 2 |
| Round 1 = ∅ (首个 0-finding 轮) | **不视为收敛**, 必须进入 Round 2 作 stability confirmation (v1.17.5+) |
| Round N = ∅ ∧ Round N-1 = ∅ ∧ N >= 2 | 视为收敛 (双轮稳定性确认) |
| 单元素差异 | 不收敛 (严格集合相等) |
| severity 升级 (minor→major) | 不收敛 (severity 参与比较) |

**首轮 0-finding 必须 stability confirmation** (v1.17.5+ 引入, 修复 latent bug):

经验来源: `aria-plugin v1.16.0` 实战 trajectory `24→2→1→0→0` — R5=∅ 后**仍跑 R6=∅** 才声称收敛。
若 R5 直接 stop, 风险是 agent 在 R5 因 context 问题假阴性 0 finding, 错过真 bug。

**机械实现**:
- audit-engine 在判定 `current_set == previous_set` 后, 增加守卫: 若 `current_set = ∅`, 至少需 2 轮历史 (`round_number >= 2`) + 上一轮也 = ∅
- 等价表达: `converged = (current_set == previous_set) AND (current_set != ∅ OR round_number >= 2)`
- Round 2 = ∅ 后仍 stop (因 round_number >= 2 满足), 但 Round 1 = ∅ 后**强制进入 Round 2** (stability gate)

**memory 来源**: `feedback_audit_convergence_pattern.md` (3x 验证 invariant) + `project_premerge_iteration_pattern.md` (pre_merge 严格收敛需稳定性确认轮)。

---

## 全票 PASS 检查

### Convergence 模式

```
unanimous_pass = all(agent.vote == PASS for agent in convergence_agents)
```

- 每个 Agent 在审查完结论后投票 PASS 或 REVISE
- REVISE 表示 Agent 认为还有遗漏或分歧
- skipped Agent (超时/失败) 不参与投票

### Challenge 模式

```
objections_resolved = all(
  obj.status == "resolved"
  for obj in challenge_output.objections
)
```

- 所有 objections 必须标记为 resolved
- overruled 状态的 objection 视为已处理 (不阻塞收敛)
- status=new 的 objection 阻塞收敛

---

## 振荡检测

### 定义

振荡: Round N 的结论集合与 Round N-2 的结论集合相同，但与 Round N-1 不同。
说明意见在两个状态之间来回切换。

### 检测条件

```
if round_number >= 3:
  keys_N   = comparison_keys(round_N)
  keys_N_1 = comparison_keys(round_N_minus_1)
  keys_N_2 = comparison_keys(round_N_minus_2)

  oscillation = (keys_N == keys_N_2) AND (keys_N != keys_N_1)
```

### 振荡处理

```
if oscillation:
  → 取最后轮 (Round N) 结论作为最终结果
  → 报告标记 oscillation: true
  → 不要求人工介入
  → 正常计算 verdict 和生成报告
```

**设计理由**: 同模型在相同输入下可能产生非确定性输出，振荡通常是 AI 行为
噪声而非真正的意见分歧。自动取最后轮避免浪费人类注意力。

### 更长周期振荡

仅检测隔一轮振荡 (N vs N-2)。更长周期 (N vs N-3, N vs N-4) 不检测,
由 max_rounds 保护兜底。

---

## 完整判定流程

```
function check_convergence(round_N, round_N_minus_1, round_N_minus_2, max_rounds):

  # Round 1: 无法判定
  if round_N.number == 1:
    return CONTINUE

  # 四元组比较
  keys_N = extract_keys(round_N)
  keys_N_1 = extract_keys(round_N_minus_1)
  conclusions_stable = (keys_N == keys_N_1)

  # 全票 PASS
  unanimous = check_unanimous(round_N)

  # 收敛判定
  if conclusions_stable AND unanimous:
    return CONVERGED

  # 振荡检测
  if round_N.number >= 3 AND round_N_minus_2 is not None:
    keys_N_2 = extract_keys(round_N_minus_2)
    if keys_N == keys_N_2 AND keys_N != keys_N_1:
      return OSCILLATION

  # max_rounds 检查
  if round_N.number >= max_rounds:
    return MAX_ROUNDS_EXHAUSTED

  return CONTINUE
```

---

## 收敛统计 (Token 消耗参考)

| 场景 | 预期轮次 | 预期 Token |
|------|---------|-----------|
| 简单变更 (少量文件) | 2 轮收敛 | ~8K |
| 中等变更 (convergence, 3 agents) | 2-3 轮 | ~12K |
| 复杂变更 (challenge, 4 agents) | 3-4 轮 | ~30K |
| 最坏 (5 轮 x 4 agents) | 5 轮 | ~50K/检查点 |

---

**最后更新**: 2026-03-27

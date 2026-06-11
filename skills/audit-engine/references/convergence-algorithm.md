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
| Round 1 drift check (#17) | **跳过** (`drift_ratio` 不计算, `consecutive_refocus_count` 不变) — 无前序稳定基线 |
| max_rounds < 3 (#17) | max_rounds<3 时 DRIFT_TERMINATED 不可达 (consecutive_refocus>=2 需至少 3 轮), drift guard 降级为 max_rounds 兜底 |
| 首次 REFOCUS 撞 max_rounds (#17) | round == max_rounds 时无剩余配额, refocus 不可发放 → MAX_ROUNDS_EXHAUSTED (max_rounds 仍是总轮数硬上界) |

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
  obj.status != "new"   # resolved 或 overruled 均视为已处理 (与 challenge-mode-schema.md 对齐; #17 顺带统一, 原 =="resolved" 会误判 overruled 阻塞收敛)
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
# 振荡豁免 (#17): keys_N / keys_N_1 / keys_N_2 均取 normal-round 逻辑序列 —
# is_refocus == true 轮从振荡比较序列剔除后重新索引 (refocus 轮不进入 N/N-2 序列,
# 与 stability 基线替换保持同一索引语义, 见 "Refocus 轮语义" 节)
normal_rounds = [r for r in all_rounds if not r.is_refocus]   # 剔除后重新索引

if len(normal_rounds) >= 3:
  keys_N   = comparison_keys(normal_rounds[-1])
  keys_N_1 = comparison_keys(normal_rounds[-2])
  keys_N_2 = comparison_keys(normal_rounds[-3])

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

## Refocus 轮语义 (#17, v1.44.0)

drift_ratio `>= refocus_threshold` 触发**强制 refocus 轮** (REFOCUS_ROUND, prompt 回锚 anchor):

- **消耗 max_rounds 配额** (防活锁, token 护栏始终有效 — issue 原案 "round 计数不前进" 有活锁风险, 已否决);
- **非冻结重号**: 底层逻辑 round 为整数 N + `is_refocus: true` 字段, 展示标签 `R{N}-refocus` (`per_round[].is_refocus`); `rounds` 整数 + `is_refocus` 组合唯一标识一轮;
- refocus 轮输出**替换 round_N 作下轮 stability 比较基线** (下一 normal 轮的 `conclusions_stable` 比较对象 = refocus 轮输出);
- refocus 轮**不进入** oscillation N/N-2 比较序列 (见 "检测条件" 振荡豁免注释)。

### consecutive_refocus_count

| 事件 | 行为 |
|------|------|
| refocus 触发 | `consecutive_refocus_count += 1` |
| normal round (未触发 refocus) | **归零** |
| `consecutive_refocus_count >= 2` | **终止** → DRIFT_TERMINATED (`drift_terminated: true → verdict=FAIL`, 见 report-storage.md §Verdict) |
| drift_check_skipped 轮 (fail-open) | **不增加** (见 audit-engine/SKILL.md 错误处理表) |

### Trajectory 示例 (逐轮标注 stability / oscillation 比较对象)

**示例 1: normal → refocus → normal**

| 轮 | is_refocus | drift / 计数 | stability 比较对象 | oscillation 比较对象 |
|----|-----------|--------------|--------------------|----------------------|
| R1 | false | drift check 跳过 (Round 1) | — (Round 1 无法判定) | — |
| R2 | false | drift_ratio >= refocus_threshold → REFOCUS_ROUND, count=1 | R1 | — (normal 序列长度 < 3) |
| R3-refocus | true | 回锚轮, 消耗配额 | R2 | **剔除** (不作 keys_N) |
| R4 | false | 未触发 → count **归零** | **R3-refocus 输出** (基线替换) | normal 序列 = [R1, R2, R4] → keys_N=R4, keys_N_1=R2, keys_N_2=R1 |

**示例 2: normal → refocus → refocus (DRIFT_TERMINATED 路径)**

| 轮 | is_refocus | drift / 计数 | stability 比较对象 | oscillation 比较对象 |
|----|-----------|--------------|--------------------|----------------------|
| R1 | false | drift check 跳过 (Round 1) | — | — |
| R2 | false | drift_ratio >= refocus_threshold → 第一次 refocus 触发, count=1 | R1 | — (normal 序列长度 < 3) |
| R3-refocus | true | 输出仍 drift_ratio >= refocus_threshold → **第二次连续 refocus 触发**, count=2 → **DRIFT_TERMINATED** | R2 | **当轮不作 keys_N** (is_refocus 剔除, normal 序列仍 = [R1, R2] 长度 < 3) — 防 DRIFT_TERMINATED 误判为 OSCILLATION; 且优先级链 DRIFT_TERMINATED 先于 OSCILLATION 双保险 |

---

## 完整判定流程

**四终局优先级链 return 顺序显式** (与 DEC-20260611-001 §4.4 逐字): `CONVERGED → DRIFT_TERMINATED (含边界轮 round==max_rounds 时优先于 MAX_ROUNDS_EXHAUSTED) → OSCILLATION → MAX_ROUNDS_EXHAUSTED`; "(优先)" 限定仅 vs MAX_ROUNDS_EXHAUSTED 语境; converged=false + drift_terminated=true **不触发** max_rounds 三路径降级 (直接以 FAIL 结束, 见 report-storage.md §Verdict converged×verdict 表)。REFOCUS_ROUND 为**独立返回状态** (非终局, 触发强制 refocus 轮并消耗 max_rounds 配额)。

```
function check_convergence(round_N, round_N_minus_1, round_N_minus_2, max_rounds, anchor):

  # Round 1: 无法判定; drift 检查同步跳过 (无前序稳定基线, 见边界情况表)
  if round_N.number == 1:
    return CONTINUE

  # Drift Check 节点 (#17, Round-1 guard 之后嵌入)
  # fail-open: drift-checker 失败/超时 → drift_ratio=null 按 < warn 档处理
  #            (drift_action=NONE + drift_check_skipped: true)
  # mode 与 consecutive_refocus_count 为引擎级状态 (非函数入参), 此处直接引用
  drift_action = check_drift(round_N, anchor)
  # drift_action ∈ {NONE, WARN, REFOCUS, TERMINATE}
  # TERMINATE = consecutive_refocus_count >= 2 (见 consecutive_refocus_count 章节)

  # 四元组比较 (refocus 轮输出已替换 round_N 作 stability 基线, 见 "Refocus 轮语义" 节)
  keys_N = extract_keys(round_N)
  keys_N_1 = extract_keys(round_N_minus_1)
  conclusions_stable = (keys_N == keys_N_1)

  # normal-round 逻辑序列 (振荡豁免, 见 "检测条件" 节): is_refocus==true 轮剔除后重新索引。
  # 引擎级状态; oscillation 比较**不得复用**上方 stability 的 keys_N/keys_N_1
  # (post-refocus 轮上两种取法发散 — stability 基线含 refocus 替换, oscillation 序列不含)。
  normal_rounds = [r for r in all_rounds if not r.is_refocus]

  # 全票 PASS
  unanimous = check_unanimous(round_N)

  # warn 档独立分支 — 仅 convergence 模式 (模式限定词, 防双模式误阻塞):
  #   challenge 模式收敛判据为 objections_resolved, 与 unanimous_pass 无关,
  #   warn 档降格为仅标注 drift_warning (见 challenge-mode-schema.md), 不进本分支。
  # 实现点限汇总层覆盖, 不注入 agent prompt (R10: 防 agent 知晓 drift 产生迎合性副作用)。
  # 每轮独立重新评估: drift_ratio 回落则收敛正常恢复, 持续触发由 max_rounds 降级兜底。
  if mode == "convergence" AND drift_action == WARN:
    unanimous = false     # 强制 unanimous_pass=false → 该轮不允许全票 PASS 收敛
                          # → 后续落入 return CONTINUE

  # ===== 四终局优先级链 (return 顺序显式, 与 DEC §4.4 逐字):
  #       CONVERGED → DRIFT_TERMINATED → OSCILLATION → MAX_ROUNDS_EXHAUSTED =====

  # 终局 1: CONVERGED
  # challenge 模式: 此处 unanimous 替换为 objections_resolved
  # (= all(obj.status != "new")), 见 challenge-mode-schema.md §收敛判定 —
  # 与 WARN 分支的 mode 限定词同构, 本伪代码默认展示 convergence 形态
  if conclusions_stable AND unanimous:
    return CONVERGED

  # 终局 2: DRIFT_TERMINATED (consecutive_refocus_count >= 2)
  #   含边界轮: 第二次连续 refocus 恰逢 round == max_rounds 时,
  #   DRIFT_TERMINATED 优先于 MAX_ROUNDS_EXHAUSTED ("(优先)" 限定仅此语境)
  #   → drift_terminated: true → verdict=FAIL override (report-storage.md §Verdict);
  #     converged=false + drift_terminated=true 不触发 max_rounds 三路径降级
  if drift_action == TERMINATE:
    return DRIFT_TERMINATED

  # 独立返回状态 (非终局): 强制 refocus 轮, 消耗 max_rounds 配额。
  # 边界守卫 (DEC §4.4 留白的实施层补全, 勘误注: DEC 仅规定第二次连续 refocus 撞边界
  # 时 DRIFT_TERMINATED 优先; 首次 REFOCUS 恰逢 round == max_rounds 时无剩余配额,
  # refocus 不可发放 — max_rounds 仍是总轮数硬上界, 约束 C8 token 护栏):
  if drift_action == REFOCUS:
    if round_N.number >= max_rounds:
      return MAX_ROUNDS_EXHAUSTED   # 无剩余配额, refocus 不可发放
    return REFOCUS_ROUND

  # 终局 3: OSCILLATION (keys_* 全部按 normal_rounds 重取, 不复用 stability 变量)
  if len(normal_rounds) >= 3:
    keys_osc_N   = comparison_keys(normal_rounds[-1])
    keys_osc_N_1 = comparison_keys(normal_rounds[-2])
    keys_osc_N_2 = comparison_keys(normal_rounds[-3])
    if keys_osc_N == keys_osc_N_2 AND keys_osc_N != keys_osc_N_1:
      return OSCILLATION

  # 终局 4: MAX_ROUNDS_EXHAUSTED
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
| drift-checker 增量 (#17, challenge 默认开) | 每轮 (Round 2 起) | **~+1-2K/轮** (refocus 轮消耗 max_rounds 配额 + 增量入表 → 总成本仍有硬上界) |

**超时口径: 单次 spawn 超时 vs 整轮 wall-clock 区分** (#17):

- **单次 agent spawn 超时 = 120s** (继承 agent-team-audit, 见 audit-engine/SKILL.md 错误处理表);
- **整轮 wall-clock = 300s/轮** (见 audit-engine/SKILL.md §并发控制); challenge 模式整轮 = 4×串行 spawn + drift-checker 独立配额 (30-60s, 不占 300s/轮);
- **勘误**: DEC-20260611-001 §4.2 "单次 agent spawn 超时 (300s)" 为**误标** — 超时数字以 audit-engine/SKILL.md 真实值为准 (spawn 120s / 每轮 300s), 本勘误仅在此处处理。

---

**最后更新**: 2026-06-11 (#17 audit-drift-guard — Drift Guard 原始目的锚定)

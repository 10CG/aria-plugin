# 审计报告格式规范 (Report Format)

## 存储位置

存储位置 schema (v1.17.4+ 5-field uniqueness schema) 的 SOT 在 [report-storage.md §存储位置](./report-storage.md#存储位置-v1174-唯一性-schema), 本文件不重复声明。旧 schema `{checkpoint}-{timestamp}.md` 已废弃 (仅 reader 向后兼容, 见 report-storage.md)。

---

## 完整报告模板

```markdown
---
checkpoint: {checkpoint_name}
mode: convergence | challenge
rounds: {N}
converged: true | false
oscillation: false
overridden_by_user: false
degraded: false
drift_terminated: false
drift_check_skipped: false
drift_warning: false          # challenge 模式 warn 档标注 (仅标注不阻塞, 见 challenge-mode-schema.md); convergence 模式恒 false (warn 经 unanimous_pass=false 表达)
is_refocus: false
verdict: PASS | PASS_WITH_WARNINGS | FAIL
timestamp: {ISO 8601}
context: {被审计内容路径}
agents: [{agent_list}]
---

## 审计结论

### Decisions (收敛)
- [{severity}] {category}/{scope}: {summary}

### Issues (已解决)
- [{severity}] {category}/{scope}: {summary}

### Risks (已识别)
- [{severity}] {category}/{scope}: {summary}

## Verdict

{verdict} -- {rationale}

计算依据:
- Critical issues: {count}
- Major issues: {count}
- Minor issues: {count}

## 轮次记录

### Round 1
- Agents: {agent_list}
- Conclusions: {count}
- Vote: {PASS/REVISE}
- Duration: {seconds}s

### Round 2
- Agents: {agent_list}
- Conclusions: {count}
- Delta vs Round 1: +{added} / -{removed}
- Vote: {PASS/REVISE}
- Duration: {seconds}s

...

### Round N (Final)
- Agents: {agent_list}
- Conclusions: {count}
- Converged: {true/false}
- Duration: {seconds}s

## 统计

| 指标 | 值 |
|------|-----|
| 总轮次 | {N} |
| 总耗时 | {seconds}s |
| Agent 参与率 | {completed}/{total} |
| 去重前/后 issues | {raw}/{deduped} |
| 收敛轮次 | {M} (or N/A) |
```

---

## Verdict 计算规则

Verdict 计算规则 (含 severity → verdict 映射 + drift_terminated override 规则) 的 **SOT 在 [report-storage.md §Verdict 计算](./report-storage.md#verdict-计算)**, 本文件不重复声明 (一处声明一处 cross-ref, 防双文件漂移)。

### 阻塞行为

| 检查点 | PASS | PASS_WITH_WARNINGS | FAIL |
|--------|------|--------------------|------|
| post_brainstorm | 继续 | 继续 (附警告) | 继续 (仅记录) |
| post_spec | 继续 | 继续 (附警告) | 继续 (仅记录) |
| post_planning | 继续 | 继续 (附警告) | 继续 (仅记录) |
| mid_implementation | 继续 | 继续 (附警告) | **阻塞** |
| mid_post_spec | 继续 | 继续 (附警告) | 继续 (仅记录 amendment 建议, advisory #79) |
| post_implementation | 继续 | 继续 (附警告) | **阻塞** |
| pre_merge | 继续 | 继续 (附警告) | **阻塞** |
| post_closure | 继续 | 继续 | 继续 (仅记录, 代码已合并) |

> **drift-FAIL 补注 (#17)**: drift 终止 (`drift_terminated: true → FAIL`, override 规则见 report-storage.md §Verdict) **继承本表 per-checkpoint 既有处置** — 不引入新阻塞路径, drift-FAIL 在哪个 checkpoint 发生就按该行 FAIL 列处置。blocking checkpoint (mid_implementation / post_implementation / pre_merge) 的 owner remediation 路径 (重跑 / 收窄 context / 显式 override, 区别于普通 FAIL 修 finding) cross-ref [report-storage.md §Verdict 计算](./report-storage.md#verdict-计算)。

---

## 特殊标记字段

### oscillation

```yaml
oscillation: true
# Round N 结论 == Round N-2 结论, 检测到振荡
# 自动取最后轮结论, 不要求人工介入
```

### overridden_by_user

```yaml
converged: false
overridden_by_user: true
# 用户在降级策略中选择了 [1] 接受当前结论
```

### degraded

```yaml
converged: false
degraded: true
# 用户在降级策略中选择了 [3] 降级为单轮
```

### incomplete

```yaml
# 轮次级别标记, 出现在轮次记录中
round_incomplete: true
# 有 Agent spawn 失败或超时, 当轮结论可能不完整
skipped_agents: ["qa-engineer"]
```

### drift_terminated / drift_check_skipped / is_refocus (#17 Drift Guard)

```yaml
drift_terminated: false
drift_check_skipped: false
is_refocus: false
# 三字段为无条件默认字段 (oscillation pattern 同构, 非条件注入):
# template 恒声明默认 false, 单 agent 报告默认 false, 由 audit-engine 聚合时覆盖;
# 仅 dispatch 时已知字段 (is_refocus、上一轮 drift_check_skipped) 注入实值。
# drift_terminated: true → verdict=FAIL (override 规则 SOT 见 report-storage.md §Verdict 计算)
```

`rounds` 整数 N + `is_refocus` 组合**唯一标识一轮**: refocus 轮底层 round 计数不冻结 (消耗 max_rounds 配额), 展示标签 `R{N}-refocus` 仅由该组合派生。

### drift_metrics backward-compat (#17)

旧报告 / 未升级 agent 报告缺 drift 字段时, 消费侧容错语义 (additive, 不回填历史报告):

- 缺 `drift_terminated` / `drift_check_skipped` / `is_refocus` → 视为 `false`
- 缺 `drift_metrics` 章节 → 视为 `drift_ratio=0`, `converged_on_anchor=null`, **不告警**

---

## drift_metrics 章节骨架 (#17 Drift Guard)

drift guard 生效的审计 (challenge 默认开 / convergence 经 `audit.drift_guard.convergence_mode` opt-in) 报告 body 须含 `drift_metrics` 章节。本文件为 drift_metrics schema SOT (report-storage.md cross-ref 至此); 结构性验收标准: `drift_metrics.per_round 条目数 == 实际轮次数` (含 drift_ratio=0 正常轮与 is_refocus 轮)。

```yaml
drift_metrics:
  # —— 顶层兄弟字段 ——
  anchor:                            # Step 0 固化快照 (Round 1 前一次性, 审计周期内不可变)
    checkpoint: {checkpoint_name}
    primary_goal: {原始目的}
    in_scope: [{...}]
    out_of_scope_hints: [{...}]
    source_sha: {freeze 时 git SHA}
  anchor_engagement: normal | none   # none = 末轮 on_topic 计数 == 0 时标注
                                     # (annotation only, 不改收敛/verdict 行为; 末轮 drift_ratio=null [skipped] 时不触发 none)
  consecutive_refocus_count: {N}     # 字段定义见 report-storage.md (refocus +1 / normal 归零 / >=2 终止)
  converged_on_anchor: true | false | null   # 末轮 drift_ratio=null (skipped) 按 fail-open <warn 语义视为满足 "< warn_threshold" 条件
  # —— per_round 表 (每轮一条; Round 1 [跳过计算] 与 drift_check_skipped 轮 → drift_ratio: null, 非 0) ——
  per_round:
    - round: {N}                     # 底层逻辑 round 整数
      is_refocus: false
      on_topic: {count}              # 三类计数
      adjacent: {count}
      off_topic: {count}
      off_topic_ids: []              # 条目保留来源 namespace 前缀: d-* (decision) / obj-* (objection)
      drift_ratio: {off_topic / all}
```

**converged_on_anchor 计算规则** (显式): `converged_on_anchor = converged AND 末轮 drift_ratio < warn_threshold`; `drift_terminated: true` 时**恒 `false`**。

---

## Challenge 模式补充字段

Challenge 模式的报告额外包含 objections 历史:

```markdown
## Objections 历史

### Round 1
| ID | Agent | Target | Severity | Point | Status |
|----|-------|--------|----------|-------|--------|
| obj-001 | qa-engineer | d-001 | major | ... | resolved |
| obj-002 | knowledge-manager | d-003 | minor | ... | overruled |

### Round 2
| ID | Agent | Target | Severity | Point | Status |
|----|-------|--------|----------|-------|--------|
| (无新 objections) |
```

---

## 输出示例

### PASS (Convergence, 2 轮收敛)

```
---
checkpoint: post_spec
mode: convergence
rounds: 2
converged: true
verdict: PASS
timestamp: 2026-03-27T14:30:00Z
context: openspec/changes/feature-x/proposal.md
agents: [tech-lead, backend-architect, qa-engineer, knowledge-manager]
---

## 审计结论

### Decisions (收敛)
- [minor] architecture/config-loader: 建议增加字段校验

### Risks (已识别)
- [minor] documentation/README: 版本号需同步更新

## Verdict
PASS -- 无 Critical 或 Major 问题, 审计通过。

## 轮次记录
### Round 1
- Agents: 4/4
- Conclusions: 3
- Vote: REVISE (tech-lead 建议细化)

### Round 2 (Final)
- Agents: 4/4
- Conclusions: 2
- Delta vs Round 1: +0 / -1 (1 条去重合并)
- Converged: true

## 统计
| 指标 | 值 |
|------|-----|
| 总轮次 | 2 |
| 总耗时 | 85s |
| Agent 参与率 | 4/4 |
| 去重前/后 issues | 5/2 |
| 收敛轮次 | 2 |
```

### FAIL (Challenge, 3 轮收敛)

```
---
checkpoint: pre_merge
mode: challenge
rounds: 3
converged: true
verdict: FAIL
timestamp: 2026-03-27T16:45:00Z
context: git diff master...feature-branch
agents: [code-reviewer, qa-engineer, tech-lead, knowledge-manager]
---

## 审计结论

### Issues (已解决)
- [critical] implementation/src/auth.ts: 未验证 JWT 签名
- [major] testing/tests/auth.test.ts: 缺少无效 token 边界测试

## Verdict
FAIL -- 发现 1 个 Critical 问题 (JWT 签名验证缺失), 阻塞合并。

## Objections 历史
### Round 1
| ID | Agent | Target | Severity | Point | Status |
|----|-------|--------|----------|-------|--------|
| obj-001 | qa-engineer | d-001 | critical | JWT 签名未验证 | resolved |

## 轮次记录
### Round 1-3 ...
```

---

**最后更新**: 2026-06-11 (#17 audit-drift-guard — Drift Guard 原始目的锚定)

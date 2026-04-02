# 审计报告格式规范 (Report Format)

## 存储位置

```
.aria/audit-reports/{checkpoint}-{timestamp}.md

示例:
  .aria/audit-reports/post_spec-2026-03-27T14.md
  .aria/audit-reports/pre_merge-2026-03-27T16.md
```

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

继承 agent-team-audit 的 severity/verdict 体系:

```
verdict = PASS               if critical == 0 AND major == 0
verdict = PASS_WITH_WARNINGS  if critical == 0 AND major >= 1
verdict = FAIL               if critical >= 1
```

### 阻塞行为

| 检查点 | PASS | PASS_WITH_WARNINGS | FAIL |
|--------|------|--------------------|------|
| post_brainstorm | 继续 | 继续 (附警告) | 继续 (仅记录) |
| post_spec | 继续 | 继续 (附警告) | 继续 (仅记录) |
| post_planning | 继续 | 继续 (附警告) | 继续 (仅记录) |
| mid_implementation | 继续 | 继续 (附警告) | **阻塞** |
| post_implementation | 继续 | 继续 (附警告) | **阻塞** |
| pre_merge | 继续 | 继续 (附警告) | **阻塞** |
| post_closure | 继续 | 继续 | 继续 (仅记录, 代码已合并) |

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

**最后更新**: 2026-03-27

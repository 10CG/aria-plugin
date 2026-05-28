# Audit Report Storage Schema

> 报告存储 schema (v1.17.4+ uniqueness schema). 从 SKILL.md §审计报告生成 提取 (iter-2, 2026-05-28)。

## 存储位置 (v1.17.4+ 唯一性 schema)

```
.aria/audit-reports/{checkpoint}-R{round}-{timestamp_ms}-{spec_id}-{agent_role}.md
```

### 字段定义

| 字段 | 来源 | 示例 |
|---|---|---|
| `{checkpoint}` | audit-engine config (post_spec / pre_merge / post_implementation 等) | `pre_merge` |
| `{round}` | audit-engine 内部计数器 (R1=首轮, R2..N=收敛轮) | `R1` |
| `{timestamp_ms}` | UTC 毫秒精度 ISO 8601 (替换 `:` 为 `-` 兼容文件系统) | `2026-04-25T220340-123Z` |
| `{spec_id}` | OpenSpec change_id (从 dispatch context) | `audit-engine-report-filename-uniqueness` |
| `{agent_role}` | 4-agent fixed roster | `qa-engineer` / `code-reviewer` / `backend-architect` / `tech-lead` |

### 完整示例

```
.aria/audit-reports/pre_merge-R1-2026-04-25T220340-123Z-audit-engine-report-filename-uniqueness-qa-engineer.md
```

### 碰撞防护设计

- `agent_role` suffix 区分 4 个并行 dispatch 的 agent (即使同毫秒落盘也不冲突)
- `timestamp_ms` 毫秒精度 (1ms 内 4 个文件并行写, agent_role 兜底唯一性)
- `R{round}` 区分多轮收敛输出 (R1 / R2 / R3 不冲突)
- `{spec_id}` 区分多 Spec 共享同 round 的并发审计

### 向后兼容 (reader 行为)

- audit-engine 扫描 `.aria/audit-reports/*.md` 时同时接受新旧 schema
- 旧文件名 `{checkpoint}-{timestamp}.md` (无 round/role suffix) 视为单 agent 单轮 (R1, role=`legacy`)
- finding aggregation 时 legacy 文件归入对应 checkpoint 的 R1, 与新 R1 文件并集
- writer 仅生成新 schema (本 Spec 合并即生效, 不再回写旧格式)

### 为何引入此 schema (Round-2 audit P0.2 finding)

旧 schema `{checkpoint}-{timestamp}.md` 时间戳实际粒度仅到分钟/秒, 4-agent strict 模式并行 dispatch → 同一秒/分钟落盘 → 后写覆盖前写, agent finding 永久丢失, 导致 `R_N == R_{N-1}` 收敛比较缺少完整 finding 集。新 schema 通过 `{round}-{timestamp_ms}-{agent_role}` 三重唯一性消除碰撞。

## Verdict 计算

```
verdict = PASS               if 0 Critical + 0 Major
verdict = PASS_WITH_WARNINGS  if 0 Critical + >=1 Major
verdict = FAIL               if >=1 Critical
```

继承 agent-team-audit 的 severity/verdict 体系。审计报告同时包含:
- `converged`: 收敛状态 (true/false)
- `verdict`: 质量判定 (PASS/PASS_WITH_WARNINGS/FAIL)

### 组合含义 (converged × verdict)

| converged | verdict | 含义 |
|-----------|---------|------|
| true | PASS | 正常通过 |
| true | PASS_WITH_WARNINGS | 收敛但有 Major 问题 |
| true | FAIL | 收敛但有 Critical 问题, 阻塞流程 |
| false | * | 未收敛, 触发降级策略 |

## 报告 Frontmatter

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

详细报告格式见 [report-format.md](./report-format.md)。

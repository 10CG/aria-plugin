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

> 本节为 verdict 计算规则的 **SOT** — report-format.md 仅 cross-ref 至此, 双文件不重复声明 (防漂移)。

```
verdict = PASS               if 0 Critical + 0 Major
verdict = PASS_WITH_WARNINGS  if 0 Critical + >=1 Major
verdict = FAIL               if >=1 Critical
```

继承 agent-team-audit 的 severity/verdict 体系。审计报告同时包含:
- `converged`: 收敛状态 (true/false)
- `verdict`: 质量判定 (PASS/PASS_WITH_WARNINGS/FAIL)

### drift_terminated override 规则 (#17 Drift Guard)

**`drift_terminated: true → verdict=FAIL`** — drift 终止 (连续 2 次 refocus 未回锚, DRIFT_TERMINATED 终局) **覆盖**上表 severity 计算结果: 即使 Critical=0 也判 FAIL, 复用既有 FAIL verdict 通道正常结束 (advisory-over-hardlock, 不发明新硬中止路径)。

- **frontmatter `verdict` 恒为裸枚举** (`FAIL`), drift override rationale **仅**出现在 body `## Verdict` 节 (#125/#126 dashboard parser 防护)。rationale 锚点示例: `FAIL (drift override) — 连续 2 次 refocus 未回锚, Critical=0`。
- **owner remediation 路径** (区别于普通 FAIL 的"修 finding"路径): **重跑审计 / 收窄 context / 显式 override**。drift-FAIL 表示"讨论漂离原始目的", 而非"被审计对象有 Critical 缺陷", 修 finding 通常不是正确处置。

### 组合含义 (converged × verdict)

| converged | verdict | 含义 |
|-----------|---------|------|
| true | PASS | 正常通过 |
| true | PASS_WITH_WARNINGS | 收敛但有 Major 问题 |
| true | FAIL | 收敛但有 Critical 问题, 阻塞流程 |
| false (`drift_terminated: true`) | FAIL | DRIFT_TERMINATED 终局, drift override; **不触发 max_rounds 三路径降级**, 直接以 FAIL 结束走 owner remediation 路径 |
| false (`drift_terminated: false`) | * | 未收敛, 触发降级策略 (本行**排除** `drift_terminated: true` 情形) |

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
drift_terminated: false
drift_check_skipped: false
is_refocus: false
verdict: PASS | PASS_WITH_WARNINGS | FAIL
timestamp: {ISO 8601}
context: {被审计内容路径}
agents: [{agent_list}]
---
```

### Drift Guard 字段定义 (#17)

- `drift_terminated`: 默认 `false`; DRIFT_TERMINATED 终局时由 audit-engine **聚合层**置 `true` (→ verdict=FAIL override, 见 §Verdict 计算)。
- `drift_check_skipped`: 默认 `false`; drift-checker spawn 失败/超时 fail-open 时置 `true` (该轮 `drift_ratio=null` 按 <warn 档处理, `consecutive_refocus_count` 不增加)。
- `is_refocus`: 默认 `false`; refocus 轮 dispatch 时注入 `true`。`rounds` 整数 N + `is_refocus` 组合唯一标识一轮 (展示标签 `R{N}-refocus`, 底层 round 计数不冻结)。
- `consecutive_refocus_count` (本节为字段定义 SOT; 字段本体落报告 body `drift_metrics` 章节, 非 frontmatter): refocus 触发 +1, normal round 后归零, `drift_check_skipped` 轮不增加; >= 2 → DRIFT_TERMINATED。

drift_metrics 见 [report-format.md (SOT)](./report-format.md#drift_metrics-章节骨架-17-drift-guard)。

详细报告格式见 [report-format.md](./report-format.md)。

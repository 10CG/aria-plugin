# step 3b 项目级增补 — structural fixture 验证 (Rule #6 substitute, #145)

> `agent-team-audit` = prose/process skill (非确定性 code) → Rule #6 substitute = structural fixture + dogfood
> (per memory `feedback_deterministic_structural_skill_rule6_substitute`)。本文档对 step 3b 算法
> (见 `../agent-selection-matrix.md §step 3b`) 逐 fixture trace, 验证 AC-1/2/3/4/6。

## Fixture 集 (本目录)

| 文件 | capabilities | 代表场景 |
|------|--------------|----------|
| `project-security-auditor.md` | `[security-audit, shell-safety, egress-security]` | AC-6 case-a (specialist 命中) |
| `project-doc-helper.md` | `[documentation-audit, code-review]` | AC-6 case-b (通用标签不命中) |
| `project-malformed.md` | (无 capabilities 字段) | AC-4 边界 (skip-as-error) |
| `project-empty-caps.md` | `[]` (空 list) | AC-4 边界 (合法无命中) |

> `security-auditor` 的 `shell-safety` / `egress-security` 为 reporter 领域写实标签, **尚未入** `capabilities-taxonomy.yaml` (OOS: 细粒度 specialist 标签留后续 cycle) —— 命中**仅靠** taxonomy 内的 `security-audit`, 其余两标签不 load-bearing。

## 增补白名单 (来自 agent-selection-matrix.md)

| 触发点 | 白名单 |
|--------|--------|
| pre_merge | `security-audit`, `performance-optimization` |
| post_implementation | `security-audit`, `performance-optimization` |
| post_spec | (空) |

## Trace — pre_merge 检查点

step 3a 基线 = Tech Lead + Code Reviewer + Knowledge Manager (3)。
step 3b 对每个 fixture 算 `capabilities ∩ 白名单{security-audit, performance-optimization}`:

| fixture | capabilities ∩ 白名单 | 命中? | 动作 | 对应 AC |
|---------|----------------------|-------|------|---------|
| project-security-auditor | `{security-audit}` ≠ ∅ | ✅ | **加入本批** | **AC-1 ✅** (基线已带 security-audit 仍纳入项目 agent — 验证非 baseline 减法) |
| project-doc-helper | `{}` (documentation-audit/code-review 不在白名单) | ❌ | 不纳入 | **AC-2 ✅** (通用标签不注水) |
| project-malformed | capabilities 缺失 → 无法求交 | — | **skip 该 agent** (skip-as-error), 基线不受影响 | **AC-4 ✅** (graceful skip) |
| project-empty-caps | `[] ∩ 白名单 = ∅` | ❌ | 不纳入 (合法无命中, 非 skip) | **AC-4 ✅** (空 list 合法边界) |

→ pre_merge 批次 = 3 基线 + 1 增补 (security-auditor) = **4 agent**, "Agents 参与: 4/4" (分母 = 基线+增补)。**AC-1 + AC-2 + AC-4 通过**。

> **AC-4 两边界对照**: `project-malformed` (字段缺失) = skip-as-error (防崩); `project-empty-caps` (空 list) = 合法无命中 (正常不纳入)。两者动作不同 (skip vs 不纳入), 但对批次结果都是"该 agent 不在批次", 区别在**是否当异常处理**。

## Trace — post_spec 检查点 (白名单空)

白名单 = ∅ → 任何 fixture 的 `capabilities ∩ ∅ = ∅` → 无命中 → step 3b 空集。
→ post_spec 批次 = 纯基线 (Tech Lead + Knowledge Manager) = 2 agent。**验证白名单空 → 纯基线**。

## Trace — 空目录 / 目录不存在 (AC-3 零回归)

`.aria/agents/` 不存在 (如本 Aria 项目) 或空 → step 3b 无 fixture 可扫 → 空集 → 退化为纯基线。
→ 任何检查点批次 = 与改造前**逐字节相同**。**AC-3 ✅ 零回归**。

## 空 list 边界 (AC-4 补充)

`capabilities: []` (空 list, 非缺失) → `[] ∩ 白名单 = ∅` → **合法无命中** (等价不纳入), **非 skip-as-error**。
与"字段缺失→skip"区分: 空 list 是合法声明 (该 agent 无任何能力标签), 不报错。**AC-4 边界 ✅**。

## AC-5 dogfood 记录 (本 Aria 项目, 2026-06-21)

机械核实 (实施期实跑):
- `.aria/agents/` 在本 Aria 仓 **ABSENT** (不存在) → step 3b 扫描无源 → 空集。
- `experiments.agent_team_audit = false` (默认关) → 即使有目录也静默返回。
- ∴ 本 Aria 项目跑任一检查点 = **纯固定基线** (与改造前逐字节相同)。**AC-5 ✅ 零回归确认**。
- fixture frontmatter 全部可解析: security-auditor=`[security-audit,...]` / doc-helper=`[documentation-audit,code-review]` / empty-caps=`[]` / malformed=`MISSING`。
- 说明 (proposal AC-5 范围限定): 因 Aria 无 `.aria/agents/`, dogfood **只能验 AC-3 纯基线零回归**; AC-1/AC-2/AC-4 的命中/不命中/skip 由上方 structural fixture trace 验证 (AC-6 载体)。

## 结论

step 3b 算法对 5 个验证点 (AC-1 specialist 命中纳入 / AC-2 通用不纳入 / AC-3 空目录零回归 /
AC-4 缺失skip + 空list合法 / 白名单空→纯基线) 全部产出正确结果。baseline-减法缺陷已规避
(security-auditor 在 code-reviewer 也带 security-audit 时仍被纳入)。降级路径三处覆盖零回归。

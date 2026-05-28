# Agent Dispatch Contract — 强制 frontmatter 输出

> **关联**: Forgejo Aria #126 (2026-05-28) — supply-side enforcement to prevent dashboard parser invisibility (实测 40% reports 无 frontmatter, 最新 R1/R2 全部不可见)。

## 不可协商规则

任何通过 audit-engine spawn 的 agent (经由 agent-team-audit, 含 convergence / challenge 模式所有 round) 必须在 agent prompt 中嵌入下方 frontmatter template 要求, 否则 agent 自由发挥会导致 audit report 缺 YAML frontmatter, dashboard parser 无法解析。

## 调用方契约

调用链: Phase Skills → audit-engine → agent-team-audit → Agent

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

## 责任分工

- **完整模板**: 见 [report-format.md](./report-format.md)。
- **Phase Skill 调用方** (phase-a-planner / phase-b-developer / phase-c-integrator / phase-d-closer): 在调用 audit-engine 时, 由 audit-engine 自身负责把上述指令注入 agent prompt — 调用方传入 checkpoint / mode / context / agent_role 等参数即可, 不需要重复 frontmatter 模板。

## 违反后果

agent 输出无 frontmatter → dashboard parser 跳过该报告 (Issue #126 实测 40% 丢失) → audit history 不可见 → 跨项目 dogfood 时 owner 误判 "最近无 audit"。

## Backward-compat for legacy reports

Issue #126 fix 之前生成的 42 个无 frontmatter 报告通过 aria-dashboard parse-audit 的 markdown-header fallback 兜底 (parser 优先 frontmatter, 缺失时扫描 `**Verdict**:` / `**Date**:` / `**Round**:` 等 markdown header 行)。

新报告强制 frontmatter, 旧报告通过 fallback 兜底可见 — 但 fallback 字段不全。owner 倾向跑 one-shot backfill 时, 脚本路径预留为未来 follow-up (本 fix 不强制 backfill, 仅供给侧约束 + 消费侧 fallback)。

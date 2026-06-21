---
name: agent-team-audit
description: |
  Agent Team 集体审计（实验功能）。
  在关键节点触发多 Agent 协同审查，检测版本不一致、安全漏洞、架构违规等问题。

  默认关闭，需在 .aria/config.json 中启用 experiments.agent_team_audit。
experimental: true
user-invocable: false
disable-model-invocation: true
allowed-tools: Read, Glob, Grep, Bash
---

# Agent Team 审计 (Agent Team Audit)

> **版本**: 1.1.0 | **状态**: 实验性 (Experimental)
> **创建**: 2026-03-18 | **更新**: 2026-06-21 (#145 项目级 agent 增补: step 3 拆 3a 基线/3b capabilities 增补)

---

## 实验声明

此 Skill 为**实验功能**，默认关闭。首次启用时会显示以下提示：

```
⚠️ 实验功能: Agent Team 审计
此功能正在验证中，行为可能在后续版本变更。
启用方式: .aria/config.json → experiments.agent_team_audit: true
```

---

## 配置 (config-loader)

通过 `.aria/config.json` 控制，参见 [config-loader](../config-loader/SKILL.md)。

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `experiments.agent_team_audit` | `false` | 启用/关闭审计 |
| `experiments.agent_team_audit_points` | `["pre_merge"]` | 触发点列表 |

---

## 审计触发点

详细定义见 [references/audit-points.md](./references/audit-points.md)。

| 触发点 | 位置 | Agents (固定基线 + 项目级增补) | 阻塞性 |
|--------|------|--------|--------|
| `pre_merge` | C.2 合并前 | Tech Lead + Code Reviewer + Knowledge Manager (+ 项目级增补, 见 step 3b) | Critical 阻塞 |
| `post_implementation` | B.2 完成后 | QA Engineer + Code Reviewer (+ 项目级增补, 见 step 3b) | Critical 阻塞 |
| `post_spec` | A.1 完成后 | Tech Lead + Knowledge Manager (白名单空, 通常纯基线) | 非阻塞 (建议性) |

> **项目级增补 (#145)**: 除固定基线外, `.aria/agents/` 中 capabilities 命中该检查点"增补白名单"的项目专属 agent 会被加入审计批次 (step 3b)。详见 [agent-selection-matrix.md](./references/agent-selection-matrix.md)。`.aria/agents/` 空 / 无命中 → 纯基线 (零回归)。

---

## Issue Severity 分级

```yaml
Critical (阻塞):
  - 数据丢失风险
  - 安全漏洞
  - 版本号不一致
  - 架构规则违反

Major (记录但不阻塞):
  - 测试覆盖不足
  - 文档过时
  - 代码规范违反

Minor (仅建议):
  - 排版问题
  - 命名建议
  - 优化机会
```

---

## Verdict 判定

详细格式见 [references/verdict-format.md](./references/verdict-format.md)。

```
verdict = PASS               如果: 0 Critical + 0 Major
verdict = PASS_WITH_WARNINGS  如果: 0 Critical + >=1 Major
verdict = FAIL               如果: >=1 Critical (任一 Agent)

FAIL 阻塞: pre_merge, post_implementation
FAIL 不阻塞: post_spec
```

---

## 问题去重算法

```
1. 收集所有 Agent 的 issues 列表
2. 对每个 issue 提取: {severity, category, affected_file}
3. 两个 issue 被视为相同当: category 相同 且 affected_file 相同
4. 去重后标注: "发现者: Agent A, Agent B" (交叉验证证据)
5. 最终报告中同时展示去重后列表和各 Agent 原始发现数
```

---

## 并发控制

```yaml
max_parallel_agents: 2    # 默认值, 可在 config.json 中覆盖
hard_cap: 3               # 不可超过

超时策略:
  single_agent: 120s      # 单 Agent 超时
  overall: 300s            # 整体超时
  on_timeout: skipped      # 超时标记为 skipped, 不视为 FAIL

规则:
  - 调用方 (phase-b/c) 不应在其他 subagent 运行时触发审计
  - 超时 Agent 标记为 skipped, 不阻塞其他 Agent
  - 529 错误时等待 30s 后重试一次, 仍失败则 skip
```

---

## 输出格式

> **"Agents 参与: N/N" 分母语义 (#145)**: 分母 = **当次实际批次总数 = 固定基线 + 项目级增补之和** (非固定基线数)。无项目级增补时分母 = 基线数 (下方纯基线示例 3/3 不变)。增补 agent 在列表中标注来源 `(项目级)`。

### PASS (无项目级增补 — 纯基线)

```
╔══════════════════════════════════════════════════════════════╗
║                    AGENT TEAM AUDIT REPORT                    ║
╚══════════════════════════════════════════════════════════════╝

🎯 触发点: pre_merge
📊 Verdict: ✅ PASS

Agents 参与: 3/3
  ✅ Tech Lead — 0 issues
  ✅ Code Reviewer — 0 issues
  ✅ Knowledge Manager — 0 issues

总耗时: 45s
```

### PASS (含项目级增补 — #145 示例)

```
🎯 触发点: pre_merge
📊 Verdict: ✅ PASS

Agents 参与: 4/4   ← 分母 = 3 基线 + 1 增补
  ✅ Tech Lead — 0 issues
  ✅ Code Reviewer — 0 issues
  ✅ Knowledge Manager — 0 issues
  ✅ shell-safety-auditor (项目级) — 0 issues   ← capabilities 含 security-audit, 命中白名单

总耗时: 58s
```

### PASS_WITH_WARNINGS

```
🎯 触发点: pre_merge
📊 Verdict: ⚠️ PASS_WITH_WARNINGS

Issues (去重后): 2
  ⚠️ [Major] 测试覆盖不足 — src/auth.ts
    发现者: Code Reviewer, QA Engineer
  ⚠️ [Major] 文档未更新 — docs/api.md
    发现者: Knowledge Manager

Agents 参与: 3/3
总耗时: 62s
```

### FAIL

```
🎯 触发点: pre_merge
📊 Verdict: ❌ FAIL (阻塞合并)

Issues (去重后): 3
  🔴 [Critical] 版本号不一致 — plugin.json vs VERSION
    发现者: Tech Lead, Knowledge Manager
  🔴 [Critical] 安全漏洞 — src/auth.ts (未验证 token)
    发现者: Code Reviewer
  ⚠️ [Major] 缺少 CHANGELOG 条目
    发现者: Knowledge Manager

Agents 参与: 3/3
总耗时: 78s

⛔ 合并已阻塞。修复 Critical 问题后重新审计。
```

---

## 执行流程

```
1. 检查 config: experiments.agent_team_audit == true?
   - false → 静默返回, 不执行审计
   - true → 继续

2. 确认触发点在 agent_team_audit_points 列表中?
   - 不在 → 静默返回
   - 在 → 继续

3a. 按触发点选择固定基线 Agent 组合 (见 agent-selection-matrix.md)

3b. 项目级 agent 增补 (#145, 见 agent-selection-matrix.md §step 3b 算法)
   - 读 .aria/agents/*.md frontmatter 的 capabilities (冷路径直读,
     .aria/cache/project-agents.json 仅可选加速; 不依赖 agent-router 先跑)
   - 取本检查点"增补 capabilities 白名单"
   - 项目 agent capabilities ∩ 白名单 ≠ ∅ → 加入本批
   - frontmatter 缺/非list/parse-fail → skip 该 agent (不阻断基线);
     空 list → 合法 (无命中)
   - .aria/agents/ 空 / 无命中 → 空集 → 纯基线 (零回归)

4. 并发启动 Agents (基线 + 增补, 受 max_parallel_agents 节流但不丢弃,
   增补 agent 排入后续 batch 串行跑)
   - 每个 Agent 独立审查, 输出 issues 列表

5. 收集结果, 执行去重算法

6. 计算 verdict

7. 输出审计报告

8. 如果 FAIL 且触发点阻塞性=true → 返回阻塞信号给调用方
```

---

## 相关文档

- [references/audit-points.md](./references/audit-points.md) — 审计触发点详细定义
- [references/agent-selection-matrix.md](./references/agent-selection-matrix.md) — Agent 选择矩阵
- [references/verdict-format.md](./references/verdict-format.md) — Verdict 格式规范

---

**最后更新**: 2026-06-21 (agent-team-audit-project-agent-augmentation #145: step 3 拆 3a 固定基线 / 3b 项目级 capabilities 增补 + 触发点表/输出格式分母同步)

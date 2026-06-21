# Agent 选择矩阵 (Agent Selection Matrix)

每检查点的审计团队 = **固定基线** (内置 4 agent 子集, step 3a) **+ 项目级增补** (`.aria/agents/` 中 capabilities 命中"增补白名单"的项目 agent, step 3b, #145)。

## 触发点 → 固定基线映射 (step 3a)

| 触发点 | Tech Lead | Code Reviewer | QA Engineer | Knowledge Manager |
|--------|:---------:|:-------------:|:-----------:|:-----------------:|
| pre_merge | ✅ | ✅ | — | ✅ |
| post_implementation | — | ✅ | ✅ | — |
| post_spec | ✅ | — | — | ✅ |

## 触发点 → 增补 capabilities 白名单 (step 3b, #145)

| 触发点 | 增补 capabilities 白名单 |
|--------|--------------------------|
| pre_merge | `security-audit`, `performance-optimization` |
| post_implementation | `security-audit`, `performance-optimization` |
| post_spec | (空 → 纯基线) |

白名单标签锚定 `aria/references/capabilities-taxonomy.yaml` (aria-plugin 子模块**根** `references/`, 非本 skill 的 `references/`) 既有词表。**只放 specialist 标签** —— 基线本职通用维度 (`code-review` / `documentation-audit`) **不放**, 防通用标签注水。`mid_post_spec` 漂移检查点不在增补范围 (scope = drift_point_only, 设计为 1-2 基线 agent)。

### step 3b — 项目 agent 增补算法

```
1. 发现: 读 .aria/agents/*.md frontmatter 的 capabilities
   (agent-router 扫的同一源; .aria/cache/project-agents.json 仅可选加速,
    不依赖 agent-router 是否先跑过 — 冷路径直读 frontmatter)
2. 取本检查点的"增补 capabilities 白名单" (上表)
3. 对每个项目 agent: capabilities ∩ 白名单 ≠ ∅ → 加入本批
   (不管基线是否名义上也带该标签 — 基线通用维度 + 项目专家纵深 = 互补非冗余)
4. 调度: 增补 agent 进入与基线同一 batch 队列, 受 max_parallel_agents
   节流但不丢弃 (超出预算的多出 agent 串行分批跑, 同下 §并发调度)
```

**判据 = 专有标签阈值 (非 baseline 减法)**: 为何不按 `gap = 白名单 − ∪(基线.capabilities)` 派生? 基线 `code-reviewer` 已带 `security-audit` 标签 → 派生减法会把 `security-audit` 盖住, 致项目 security-auditor 被错误排除, 恰好打不中其用例 (#145 reporter 实证)。故用**显式白名单**解耦: 项目 agent 命中白名单即加入。

**边界 (frontmatter 健壮性)**: 项目 agent `capabilities` 字段缺失 / 非 list 类型 / 文件 YAML parse 失败 → **skip 该 agent**, 不阻断基线; `capabilities` 空 list → **合法** (= 无白名单命中, 等价不纳入, 非 skip-as-error)。

**降级 (零回归)**: `.aria/agents/` 空 / 目录不存在 / 无白名单命中 → step 3b 空集 → 退化为纯基线行为 (与改造前逐字节相同)。

## Agent 职责

### Tech Lead
- 架构决策审查
- 版本一致性验证
- 依赖关系分析
- 技术债务评估

### Code Reviewer
- 代码质量检查
- 安全漏洞扫描
- 性能问题检测
- 编码规范验证

### QA Engineer
- 测试覆盖率评估
- 边界条件检查
- 错误处理验证
- 回归风险评估

### Knowledge Manager
- 文档同步检查
- CHANGELOG 完整性
- README 一致性
- 术语规范性

## 并发调度

基线 + 增补 agent 共用同一 batch 队列, 受 `max_parallel_agents` (默认 2) 节流分批 — 增补 agent **节流但不丢弃** (排入后续 batch 串行跑)。

```
pre_merge (3 基线 + N 增补):
  Batch 1: Tech Lead + Code Reviewer (并行)
  Batch 2: Knowledge Manager (等 Batch 1 或并行, 取决于 max_parallel_agents)
  Batch 3+: 项目级增补 agent (按 max_parallel_agents 续批; N=0 时无此批 = 纯基线)

post_implementation (2 基线 + N 增补):
  Batch 1: QA Engineer + Code Reviewer (并行)
  Batch 2+: 项目级增补 agent (N=0 时无此批)

post_spec (2 基线, 白名单空 → 通常无增补):
  Batch 1: Tech Lead + Knowledge Manager (并行)
```

---

**最后更新**: 2026-06-21 (agent-team-audit-project-agent-augmentation #145: +固定基线/增补白名单二分 + step 3b 算法 + 增补调度)

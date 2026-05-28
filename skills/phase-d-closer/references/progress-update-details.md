# Phase D.1 Progress Update Details

> D.1 更新模式 (single-pass vs milestone-driven) + UPMv2-STATE 字段 + Spec 归档操作. 从 SKILL.md §进度更新内容 提取 (iter-3, 2026-05-28)。

## D.1 更新模式

D.1 支持两种更新模式, 通过 `.aria/config.json` 中的 `upm.milestone_driven` 控制:

| 维度 | 默认模式 (single-pass) | Milestone-driven 模式 |
|------|----------------------|----------------------|
| 配置 | `upm.milestone_driven: false` | `upm.milestone_driven: true` |
| C.2.6 行为 | 不执行 | 每次 PR 合并后追加 sub-bullet + 状态升级为 `[~]` |
| D.1 工作量 | 完整 single-pass 更新所有 Story | 仅 finalize: 将 `[~]` → `[x]` + 关联 spec archive 路径 |
| 适用场景 | 单 PR 功能 / 快速迭代 | multi-PR cycle (如 schema expand-migrate-contract 3 PR) |
| 中间透明度 | 低 (1-2 周期间 UPM 停留在 `[ ]`) | 高 (每次 PR 合并即可见进度) |
| 向后兼容 | 原有行为不变 | opt-in, 不影响已有配置 |

**Milestone-driven 模式下 D.1 的 finalize 职责**:

1. 将所有 `[~]` Story 标记升级为 `[x] COMPLETED`
2. 在 Story 的最后一条 sub-bullet 后追加 `archive: openspec/archive/{spec_id}/`
3. 更新 UPMv2-STATE Header (`lastUpdateAt`, `stateToken`, `completedTasks`)
4. 不重建历史记录 — sub-bullets 已由 C.2.6 在过程中实时写入

**相关文档**: 参见 [phase-c-integrator C.2.6](../../phase-c-integrator/SKILL.md) — 修复 Forgejo #22 (2026-04-23)

## UPMv2-STATE 更新

```yaml
更新字段:
  - cycleNumber: +1 或保持
  - lastUpdateAt: 当前时间
  - stateToken: 重新计算
  - completedTasks: 添加已完成任务
  - kpiSnapshot: 更新覆盖率等指标
```

## Spec 归档

```yaml
归档操作:
  1. 验证 tasks.md 所有任务标记 [x]
  2. 更新 proposal.md 状态为 Complete
  3. 移动目录: changes/{id}/ → archive/{id}/
  4. 记录归档时间和提交信息
```

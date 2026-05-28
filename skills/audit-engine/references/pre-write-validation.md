# Pre-write Validation: change_id 锚点检查

> **关联**: Forgejo Aria #27 dangling reference fix (2026-04-23), 与 Issue #26 FR-1 (checkpoint 报告完整性 gate) 互补。

## 目的

在任何审计报告写盘前, 必须先验证 `change_id` 有对应的 proposal.md 背书。验证在 verdict 计算完成后、文件 I/O 开始前执行。这防止 audit-engine 产出引用不存在 spec_id 的 dangling reports, 后续 `aria-dashboard` 等 consumer 解析时报 stale cross-ref。

## 验证流程

```
Pre-write validation (写盘前强制执行):

  输入: change_id (从调用方 context 读取)

  Step 1: 检查豁免配置
    config-loader → audit.allow_dangling_change_ids
    如果 == true → 跳过校验, 直接写盘 (记录 warn 级日志)

  Step 2: 查找活跃 Spec
    路径: {project_root}/openspec/changes/{change_id}/proposal.md
    存在 → 校验通过, 继续写盘

  Step 3: 查找已归档 Spec (通配日期前缀)
    路径: {project_root}/openspec/archive/*-{change_id}/proposal.md
    任意匹配 → 校验通过, 继续写盘

  Step 4: 校验失败
    → 拒绝写盘
    → 输出以下 ERROR 并中止:
```

```
ERROR: change_id "{change_id}" 未在 openspec/changes/ 或 openspec/archive/ 找到对应 proposal.md
Fix 任一:
  1. 创建 openspec/changes/{change_id}/proposal.md 并 draft
  2. 归档的 change 确认命名匹配 (archive/{YYYY-MM-DD}-{change_id}/)
  3. 在 .aria/config.json 设 audit.allow_dangling_change_ids: true (不推荐, 仅临时)
```

## 作用域

所有 checkpoint 均受此校验保护 (post_spec / pre_merge / post_closure 等)。审计 mode (convergence / challenge) 不影响校验逻辑。

## 豁免设计原则

`allow_dangling_change_ids` 默认 `false`, 需在 `.aria/config.json` 显式声明才能开启。豁免不改变 ERROR 为 WARN 的语义 — 写盘仍执行, 但日志必须记录 `[WARN] dangling change_id allowed by config: {change_id}`, 便于事后审计。

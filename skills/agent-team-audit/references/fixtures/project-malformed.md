---
name: project-malformed
description: 边界样本 — capabilities 字段缺失 (fixture for #145 AC-4 边界)
---

# Project Malformed (structural fixture)

> AC-4 边界样本: 无 `capabilities` 字段 → step 3b **skip 该 agent** (不阻断基线)。
> 另一边界 (空 list `capabilities: []`) 为**合法** = 无白名单命中 = 等价不纳入 (非 skip-as-error)。

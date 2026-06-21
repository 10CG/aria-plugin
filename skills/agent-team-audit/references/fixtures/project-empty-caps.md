---
name: project-empty-caps
description: 边界样本 — capabilities 为空 list (fixture for #145 AC-4 空 list 边界)
capabilities: []
---

# Project Empty Caps (structural fixture)

> AC-4 空 list 边界样本: `capabilities: []` (空 list, **非**字段缺失) → `[] ∩ 白名单 = ∅` →
> **合法无命中** (等价不纳入), **非 skip-as-error**。与 `project-malformed.md` (字段缺失→skip) 对照:
> 缺失字段是异常 (skip 防崩), 空 list 是合法声明 (该 agent 无能力标签, 正常不纳入)。

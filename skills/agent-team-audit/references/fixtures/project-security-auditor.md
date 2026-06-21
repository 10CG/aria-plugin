---
name: project-security-auditor
description: 项目专属安全审计 agent — shell 命令注入 / egress 出网 / 路径注入领域深审 (fixture for #145 AC-6 case-a)
capabilities: [security-audit, shell-safety, egress-security]
---

# Project Security Auditor (structural fixture)

> AC-6 case-a 样本: capabilities 含 `security-audit` → 命中 pre_merge/post_implementation 增补白名单 → **应被纳入** 审计批次。
> 代表 #145 reporter 的 10cg.local 项目 shell-safety-auditor / ssh-egress-security-auditor。

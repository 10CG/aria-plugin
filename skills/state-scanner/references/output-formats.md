# State Scanner - 输出格式参考

> 状态扫描器各场景的输出格式定义

---

## 完整输出格式 (标准场景)

```
╔══════════════════════════════════════════════════════════════╗
║                    PROJECT STATE ANALYSIS                     ║
╚══════════════════════════════════════════════════════════════╝

📍 当前状态
───────────────────────────────────────────────────────────────
  分支: feature/add-auth
  模块: mobile
  Phase/Cycle: Phase4-Cycle9
  变更: 3 文件 (lib/*.dart, test/*.dart)
  OpenSpec: add-auth-feature (approved)

📊 变更分析
───────────────────────────────────────────────────────────────
  类型: 功能代码 + 测试
  复杂度: Level 2
  架构影响: 无
  测试覆盖: ✅ 有对应测试

📄 需求状态
───────────────────────────────────────────────────────────────
  配置状态: ✅ 已配置
  PRD: prd-todo-app-v1.md (Draft)
  User Stories: 8 个 (ready: 3, in_progress: 2, done: 3)
  OpenSpec 覆盖: 5/8 (62.5%)

🏗️ 架构状态
───────────────────────────────────────────────────────────────
  System Architecture: ✅ 存在
  路径: docs/architecture/system-architecture.md
  状态: active
  最后更新: 2026-01-01
  需求链路: ✅ PRD → Architecture 完整

📋 OpenSpec 状态
───────────────────────────────────────────────────────────────
  活跃变更: 2 个 (approved: 1, in_progress: 1)
  已归档: 5 个
  待归档: 0 个

🛡️ 审计状态
───────────────────────────────────────────────────────────────
  审计系统: ✅ 已启用 (adaptive 模式)
  活跃检查点: post_spec, post_implementation, pre_merge
  上次审计: post_spec — PASS (收敛, 2 轮)

🔧 自定义检查
───────────────────────────────────────────────────────────────
  ✅ db-migration-status: OK
  ⚠️ benchmark-summary-freshness: STALE (warning)
     修复建议: python3 scripts/aggregate-results.py
  ✅ license-audit: OK

📝 README 同步状态
───────────────────────────────────────────────────────────────
  README.md: ✅ 版本一致 (v1.7.0) | 日期一致 (2026-03-18)

📦 插件依赖状态
───────────────────────────────────────────────────────────────
  standards 子模块: ✅ 正常

🔬 Skill 变更 AB 状态
───────────────────────────────────────────────────────────────
  检测到 SKILL.md 变更: state-scanner
  AB 验证: ✅ delta +0.375 (2026-03-19)

🎯 推荐工作流
───────────────────────────────────────────────────────────────
  ➤ [1] feature-dev (推荐)
      执行: B.1 → B.2 → C.1
      跳过: A.* (已有 Spec), B.3 (无架构变更)
      理由: 已有 OpenSpec，代码和测试就绪

  ○ [2] quick-fix
      执行: B.2 → C.1
      理由: 如果只是小修复

  ○ [3] full-cycle
      执行: A.0 → D.2 (完整)
      理由: 如果需要完整流程

  ○ [4] 自定义组合
      输入格式: "B.2 + C.1" 或 "Phase B"

🤔 选择 [1-4] 或输入自定义:
```

---

## 需求未配置时

```
📄 需求状态
───────────────────────────────────────────────────────────────
  配置状态: ❌ 未配置需求追踪
  期望路径: docs/requirements/
  建议操作:
    - 如需启用需求追踪，参考 standards/templates/prd-template.md
    - 或使用 OpenSpec 作为轻量替代方案
```

---

## 架构未配置时

```
🏗️ 架构状态
───────────────────────────────────────────────────────────────
  System Architecture: ❌ 不存在
  期望路径: docs/architecture/system-architecture.md
  建议操作:
    - 如需启用架构追踪，创建 System Architecture 文档
    - 参考 standards/core/documentation/system-architecture-spec.md
```

---

## 需求链路不完整时

```
🏗️ 架构状态
───────────────────────────────────────────────────────────────
  System Architecture: ⚠️ 存在但链路不完整
  路径: docs/architecture/system-architecture.md
  状态: active
  需求链路: ❌ 问题:
    - Architecture 未引用 PRD
    - PRD 更新时间晚于 Architecture
```

---

## OpenSpec 未配置时

```
📋 OpenSpec 状态
───────────────────────────────────────────────────────────────
  配置状态: ❌ 未配置 OpenSpec
  期望路径: openspec/changes/, openspec/archive/
  建议操作:
    - 如需使用 OpenSpec，参考 standards/openspec/templates/
    - 或使用 /spec-drafter 创建新的 proposal
```

---

## OpenSpec 干净状态 (目录存在但无活跃变更)

```
📋 OpenSpec 状态
───────────────────────────────────────────────────────────────
  活跃变更: 0 个 (干净 — 所有 Spec 已归档)
  已归档: 18 个
  待归档: 0 个
```

---

## 有待归档 Spec 时

```
📋 OpenSpec 状态
───────────────────────────────────────────────────────────────
  活跃变更: 3 个
  已归档: 5 个
  待归档: ⚠️ 1 个
    - completed-feature (Status=Complete)
  建议操作:
    - 使用 /openspec-archive 归档已完成的 Spec
```

---

## Skill 变更需要 AB 验证时

```
🔬 Skill 变更 AB 状态
───────────────────────────────────────────────────────────────
  检测到 SKILL.md 变更: state-scanner, workflow-runner
  AB 验证:
    ⚠️ state-scanner — 未找到新鲜结果
    ✅ workflow-runner — delta +0.33 (2026-03-18)
  建议操作: /skill-creator benchmark state-scanner
  规则依据: CLAUDE.md 规则 #6
```

---

## README 版本不一致时

```
📝 README 同步状态
───────────────────────────────────────────────────────────────
  README.md: ⚠️ 版本不一致
    期望: v1.7.0 (来源: VERSION)
    实际: v1.6.0
  建议操作: 更新 README.md 版本号为 v1.7.0
```

---

## README 日期不一致时

```
📝 README 同步状态
───────────────────────────────────────────────────────────────
  README.md: ⚠️ 日期不一致
    期望: 2026-03-18 (来源: CHANGELOG.md)
    实际: 2026-03-10
  建议操作: 更新 README.md 最后更新日期
```

---

## Standards 子模块未初始化时

```
📦 插件依赖状态
───────────────────────────────────────────────────────────────
  standards 子模块: ⚠️ 已注册但未初始化
  建议操作: git submodule update --init standards
```

---

## Standards 子模块不需要时 (无条目)

此区块不输出 (非 Aria 项目无需提示)。

---

## 头脑风暴建议 (模糊需求)

```
💡 头脑风暴建议
───────────────────────────────────────────────────────────────
  检测到模糊需求 (fuzziness: 0.7)
  建议先进行问题空间探索，澄清真需求 vs 伪需求

  [1] 开始头脑风暴 (problem 模式)
  [2] 直接创建 PRD
  [3] 跳过，稍后处理
```

---

## 头脑风暴建议 (PRD 需要细化)

```
💡 头脑风暴建议
───────────────────────────────────────────────────────────────
  PRD 已存在但缺少 User Stories
  建议通过头脑风暴将 PRD 细化为 User Stories

  [1] 开始头脑风暴 (requirements 模式)
  [2] 手动创建 User Stories
  [3] 跳过，稍后处理
```

---

## 头脑风暴建议 (需要技术方案)

```
💡 头脑风暴建议
───────────────────────────────────────────────────────────────
  有就绪的 User Story 但缺少技术方案
  建议先通过头脑风暴讨论技术方案

  [1] 开始头脑风暴 (technical 模式)
  [2] 直接创建 OpenSpec
  [3] 跳过，稍后处理
```

---

## 审计未启用时

此区块不输出 (`audit.enabled=false` 或配置缺失时静默跳过)。

---

## 审计已启用且有未收敛报告时

```
🛡️ 审计状态
───────────────────────────────────────────────────────────────
  审计系统: ✅ 已启用 (challenge 模式)
  活跃检查点: post_spec, post_implementation, pre_merge
  上次审计: ⚠️ post_implementation — PASS_WITH_WARNINGS (未收敛)
    时间: 2026-03-27T14:00:00Z
    报告: .aria/audit-reports/post_implementation-2026-03-27T14.md
  建议操作:
    - 查看审计报告了解未收敛原因
    - 或重新触发审计 (workflow-runner 会在对应阶段自动触发)
```

---

## 审计已启用, adaptive 模式, 无最近审计

```
🛡️ 审计状态
───────────────────────────────────────────────────────────────
  审计系统: ✅ 已启用 (adaptive 模式)
  活跃检查点: 由 adaptive_rules 决定 (Level 1=off, Level 2=convergence, Level 3=challenge)
  上次审计: 无
```

---

## 自定义检查未配置时

此区块不输出 (`.aria/state-checks.yaml` 不存在时静默跳过)。

---

## 自定义检查配置解析失败时

```
🔧 自定义检查
───────────────────────────────────────────────────────────────
  配置状态: ⚠️ .aria/state-checks.yaml 解析失败
  错误: YAML syntax error at line 5
  建议操作: 修复配置文件语法
```

---

## 自定义检查全部通过时

```
🔧 自定义检查
───────────────────────────────────────────────────────────────
  ✅ db-migration-status: OK
  ✅ benchmark-summary-freshness: OK
  ✅ license-audit: OK
```

---

## 自定义检查有 error 级别失败时

```
🔧 自定义检查
───────────────────────────────────────────────────────────────
  🔴 license-audit: EXPIRED (error)
     修复建议: npm run license-check -- --fix
  ⚠️ benchmark-summary-freshness: STALE (warning)
     修复建议: python3 scripts/aggregate-results.py
  ✅ db-migration-status: OK
```

---

## 自定义检查超时时

```
🔧 自定义检查
───────────────────────────────────────────────────────────────
  ✅ db-migration-status: OK
  ⏱️ slow-integration-check: TIMEOUT (15s) (warning)
  ✅ license-audit: OK
```

---

**最后更新**: 2026-04-03

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
  ✅ 主项目版本号: 一致 (v1.5.0)
  ✅ 主项目日期: 一致 (2026-04-12)
  ✅ 子模块版本号: 一致 (v1.14.0)
  ✅ Skill 数量: 一致 (33)
  ℹ️ Skill 列表: 完整
  ✅ Plugin badge: 一致

# 有漂移时:
  ⚠️ 子模块版本号: 不一致 (plugin.json: v1.14.0, aria/README: v1.13.0)
  ⚠️ Skill 数量: 不一致 (实际: 36, README: 33)
  ⚠️ Skill 列表: 缺失 3 项 (project-analyzer, agent-gap-analyzer, agent-creator)
  ⚠️ Plugin badge: 不一致 (plugin.json: v1.14.0, badge: v1.13.0)
  ℹ️ Skill 列表: 无法解析 Skill 列表格式

📦 插件依赖状态
───────────────────────────────────────────────────────────────
  standards 子模块: ✅ 正常

🔗 Forgejo 配置检查
───────────────────────────────────────────────────────────────
  ✅ Forgejo 配置: 已配置 (forgejo.10cg.pub)

# 文件缺失时:
  ⚠️ 检测到 Forgejo 远程 (forgejo.10cg.pub) 但缺少 CLAUDE.local.md
     建议: 运行 /forgejo-sync 可引导创建配置 (需确认)

# 文件存在但缺少 forgejo 块:
  ⚠️ CLAUDE.local.md 存在但缺少 forgejo 配置块
     建议: 运行 /forgejo-sync 可引导追加配置 (需确认)

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
  设计未实施: ⚠️ 1 个 (design_deferred, #134 v1.42.0+)
    - deferred-feature (status=unknown, staleness 14d) — 设计定稿但实施未做, 勿误判完成
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

## Handoff doc surfaced (Phase 1.15, H0 spec 2026-05-14)

正常情况 (canonical dir 有文件, 无漂移):

```
📜 Session Handoff
───────────────────────────────────────────────────────────────
  上次 handoff: 2026-05-13-issue-101-cycle-closeout.md
  写入时间: 2026-05-13T20:31:00+00:00 (~24h ago)
  路径: docs/handoff/2026-05-13-issue-101-cycle-closeout.md
  ✅ AI 已读取本 doc, §next session 入口指引已纳入推荐
```

无 handoff (空 canonical dir):

```
📜 Session Handoff
───────────────────────────────────────────────────────────────
  上次 handoff: 无 (docs/handoff/ 为空)
  提示: Phase D.3 (phase-d-closer) 在 session 结束时会引导写 handoff
```

stale handoff (age > 30 天 / 720h):

```
📜 Session Handoff
───────────────────────────────────────────────────────────────
  上次 handoff: 2026-04-01-old.md
  ⚠️ 写入时间: 2026-04-01 (~960h ago, > 30 天)
  路径: docs/handoff/2026-04-01-old.md
  提示: handoff 已过期, 内容仅供参考, 不作为优先级依据
```

---

## Handoff drift detected (Phase 1.15 + handoff_drift rule, H0 spec 2026-05-14)

`snapshot.handoff.misplaced_files != []` 时触发 `handoff_drift` rule (priority 1.91):

```
📜 Session Handoff
───────────────────────────────────────────────────────────────
  上次 handoff: docs/handoff/latest.md (~45h ago)
  🔄 检测到 6 个 handoff 文件写错位置 (.aria/handoff/, canonical 是 docs/handoff/)

  漂移文件:
    .aria/handoff/2026-04-23-aria-plugin-17-vs-18-triage.md
    .aria/handoff/2026-04-23-state-scanner-mechanical-b2-resume.md
    .aria/handoff/2026-04-24-session-closeout-final.md
    .aria/handoff/2026-04-24-session-closeout.md
    .aria/handoff/2026-04-25-session-final-closeout.md
    .aria/handoff/2026-05-13-issue-101-cycle-closeout.md

  修复建议 (Layer 3 of 5-layer enforcement):
    git mv .aria/handoff/*.md docs/handoff/
    # 然后更新 docs/handoff/latest.md pointer + rmdir .aria/handoff/
  Convention SOT: standards/conventions/session-handoff.md

🎯 推荐工作流
───────────────────────────────────────────────────────────────
  ➤ [1] migrate-handoff-drift (推荐, 优先级 1.91)
        理由: 6 个 handoff 文件位于 forbidden dir, 阻塞 next session
              自动 surface 上次 handoff。1-line `git mv` 可修复。
```

---

## 跨 worktree 交接 (Phase 1.15b, #139)

**条件区块** — 仅 `snapshot.handoff_worktrees.global_latest_elsewhere != null` 时显示 (单 worktree / 当前树即全局最新时整段不输出)。

全局最新 handoff 落在他树且 `status == "active"` (阶段 2 advisory 触发, 带编号选项):

```
🌲 跨 worktree 交接
───────────────────────────────────────────────────────────────
  ⚠️ 检测到更新的 handoff 位于其他 worktree (非当前树)
  他树: ../silknode-cut2 (分支 feat/cut2-batch1)
  handoff: docs/handoff/2026-06-04-cut2-batch1-closeout.md (active, ~3h ago)

  当前树未续上该 track — 续棒前请确认是否切换:
  ➤ [1] EnterWorktree 切过去续 track (推荐)
    [2] 留在当前 worktree
    [3] 先看该 handoff (打印路径, 不切换)
  提示: advisory 非自动切换, 选 [1] 才执行 (advisory-over-hardlock)
```

非 Claude Code 环境 (无 `EnterWorktree` 工具) 降级打印 `cd` 指引:

```
🌲 跨 worktree 交接
───────────────────────────────────────────────────────────────
  ⚠️ 检测到更新的 handoff 位于其他 worktree (非当前树)
  他树: ../silknode-cut2 (分支 feat/cut2-batch1)
  handoff: docs/handoff/2026-06-04-cut2-batch1-closeout.md (active, ~3h ago)

  当前环境无 EnterWorktree 工具, 手动切换:
    cd ../silknode-cut2
  续棒前请确认是否切换 (advisory, 非强制)
```

全局最新 doc 在他树但 `status` 为 `done`/`abandoned`/`legacy` (仅列表展示, 阶段 2 **不触发** advisory):

```
🌲 跨 worktree 交接
───────────────────────────────────────────────────────────────
  ℹ️ 全局最新 handoff 位于其他 worktree: ../silknode-cut2 (分支 feat/cut2-batch1)
  handoff: docs/handoff/2026-06-04-cut2-batch1-closeout.md (done, ~3h ago)
  提示: 该 track 已收尾/身份不明 (status=done), 仅供参考, 不触发切换建议
```

> **字段对齐** (`handoff_worktrees.global_latest_elsewhere`): `path` / `branch` / `doc` / `status` / `age_hours`。`status == "active"` 才触发 `[1]/[2]/[3]` 编号选项; 其余 status 仅展示。`others[]` (各他树明细: `path` / `branch` / `doc` / `updated_at` / `status` / `track_id` / `cmp_key_source`) 不在此区块逐条渲染, 仅供机读/调试。

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

---

## 同步状态 (Phase 1.12, 始终展示)

### 变体 1: 正常状态 (所有子模块同步，无 behind)

```
🔄 同步状态
───────────────────────────────────────────────────────────────
  当前分支: master (最新，与 origin/master 同步)
  远程引用: 45m 前同步
  子模块:
    ✅ standards: 同步
    ✅ aria: 同步
```

---

### 变体 2: 落后状态 (branch 落后 3 commits + 1 子模块 drift)

```
🔄 同步状态
───────────────────────────────────────────────────────────────
  当前分支: master (⚠️ 落后 origin/master 3 commits)
  远程引用: 2h 前同步
  建议操作: git pull
  子模块:
    ✅ standards: 同步
    ⚠️  aria: 落后远程 4 commits
        修复建议: git submodule update --remote aria
```

---

### 变体 3: 浅克隆 (shallow clone 降级)

```
🔄 同步状态
───────────────────────────────────────────────────────────────
  当前分支: master (浅克隆 — 无法计算落后数)
  远程引用: 3h 前同步
  ⚠️ 浅克隆仓库: ahead/behind 信息不可用
     如需完整历史: git fetch --unshallow
  子模块:
    ✅ standards: 同步
    ✅ aria: 同步
```

---

### 变体 4: 无 remote (纯本地仓库)

```
🔄 同步状态
───────────────────────────────────────────────────────────────
  当前分支: master
  远程引用: 无 remote (纯本地仓库)
  ℹ️ 未配置远程仓库，跳过同步检测
```

---

### 变体 5: Upstream 未配置 (detached HEAD 或 branch 无 upstream)

```
🔄 同步状态
───────────────────────────────────────────────────────────────
  当前分支: feature/new-feature (upstream 未配置)
  远程引用: 1d 前同步
  ⚠️ 当前分支无 upstream 配置，无法计算 ahead/behind
     如需配置: git branch --set-upstream-to=origin/feature/new-feature
  子模块:
    ✅ standards: 同步
    ✅ aria: 同步
```

---

## 多远程一致性 (Phase 1.12 v1.15.0+, enabled=true 时展示)

### 变体 1: 所有远程一致

```
🌐 多远程一致性
───────────────────────────────────────────────────────────────
  ✅ 主仓库: 所有远程一致 (origin, github)
  ✅ aria 子模块: 所有远程一致 (origin, github)
  ✅ standards 子模块: 所有远程一致 (origin, github)
```

---

### 变体 2: 子模块远程落后 (behind)

```
🌐 多远程一致性
───────────────────────────────────────────────────────────────
  ✅ 主仓库: 所有远程一致 (origin, github)
  ⚠️ aria 子模块: github 落后 2 commits
     修复: git -C aria push github master
     当前: origin=19f2861 | github=f55e130 (behind 2)
  ✅ standards 子模块: 所有远程一致 (origin, github)
```

---

### 变体 3: 主仓库远程落后 + 子模块不可达

```
🌐 多远程一致性
───────────────────────────────────────────────────────────────
  ⚠️ 主仓库: github 落后 1 commit
     修复: git push github master
     当前: origin=5b7a5f7 | github=e476a2b (behind 1)
  ✅ aria 子模块: 所有远程一致 (origin, github)
  ❓ upstream 子模块: github 不可达 (auth_failed)
     提示: 检查 CF_ACCESS_CLIENT_ID 环境变量
```

---

### 变体 4: diverged (需人工决策)

```
🌐 多远程一致性
───────────────────────────────────────────────────────────────
  ✅ 主仓库: 所有远程一致 (origin, github)
  ❗ aria 子模块: github 与本地分歧 (behind 2, ahead 3)
     需人工决策: git -C aria pull/rebase 或 git -C aria push --force-with-lease github master
     当前: local=abc1234 | github=def5678 (diverged)
```

---

### 变体 5: 仅单远程 (不展示此区块或显示 N/A)

当项目仅配置一个 remote 时, 此区块不输出 (避免单远程项目产生噪音)。

---

### 变体 6: multi_remote.enabled=false

此区块不输出 (配置关闭时静默跳过)。

---

## Open Issues (Phase 1.13, 仅 enabled=true 展示)

### 变体 1: 正常 (3 open issues + 启发式关联成功)

```
🎫 Open Issues
───────────────────────────────────────────────────────────────
  平台: Forgejo (10CG/Aria) — 3 open
  📌 #6  state-scanner: add issue scan and sync detection  [enhancement, skill]
         → 已关联 OpenSpec: state-scanner-issue-awareness
  📌 #5  Pulse 项目集成                                    [feature]
  📌 #4  登录页面样式问题                                  [bug]
  数据来源: live | 刚刚获取 | ttl: 15m
```

---

### 变体 2: 离线降级 (fetch_error: network_unavailable)

```
🎫 Open Issues
───────────────────────────────────────────────────────────────
  平台: Forgejo (10CG/Aria)
  ⚠️ 无法获取 Issues: 网络不可达 (network_unavailable)
     跳过 Issue 感知 — 请检查网络连接后重试
```

---

### 变体 3: Token 未配置 (fetch_error: auth_missing)

```
🎫 Open Issues
───────────────────────────────────────────────────────────────
  平台: Forgejo (10CG/Aria)
  ⚠️ 未配置访问 Token (auth_missing)
     跳过 Issue 感知 — 请配置 forgejo CLI token 后重试
```

---

### 变体 4: 缓存命中 (source: cache, fresh)

```
🎫 Open Issues
───────────────────────────────────────────────────────────────
  平台: Forgejo (10CG/Aria) — 3 open
  📌 #6  state-scanner: add issue scan and sync detection  [enhancement, skill]
         → 已关联 OpenSpec: state-scanner-issue-awareness
  📌 #5  Pulse 项目集成                                    [feature]
  📌 #4  登录页面样式问题                                  [bug]
  数据来源: cache (2m ago) | ttl: 15m
```

---

### 变体 5: Rate limited (fetch_error: rate_limited, 使用旧缓存)

```
🎫 Open Issues
───────────────────────────────────────────────────────────────
  平台: Forgejo (10CG/Aria) — 3 open (缓存数据)
  📌 #6  state-scanner: add issue scan and sync detection  [enhancement, skill]
  📌 #5  Pulse 项目集成                                    [feature]
  📌 #4  登录页面样式问题                                  [bug]
  ⚠️ API 请求频率超限 (rate_limited) — 使用旧缓存 (18m ago)
     数据来源: cache (stale) | 建议稍后重试
```

---

**最后更新**: 2026-06-11 (#139 — added cross-worktree handoff (Phase 1.15b) conditional block: active advisory + cd 降级 + non-active 列表展示)
> 前次 2026-05-14 (H0 spec — added handoff doc surfaced + drift detected variants)

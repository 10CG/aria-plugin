---
name: state-scanner
description: |
  项目状态扫描与智能工作流推荐，十步循环的统一入口。
  收集项目状态、分析变更、推荐最佳工作流、引导用户确认执行。

  使用场景："查看项目当前状态"、"我要提交代码"、"开发新功能"
argument-hint: "[intent]"
disable-model-invocation: false
user-invocable: true
allowed-tools: Read, Glob, Grep, Bash
---

# 状态扫描与智能推荐 (State Scanner v3.0)

> **版本**: 3.0.0 | **角色**: 十步循环统一入口
> **机械化**: v3.0.0 起 Phase 1.x 由 `scripts/scan.py` (stdlib-only Python) 机械产出 JSON snapshot, AI 读 snapshot 进入阶段 2 推荐。v2.x prose 路径保留 `mechanical_mode=false` opt-out 至 v1.18.0 移除 (AD-SSME-5)。

## 快速开始

### 我应该使用这个 Skill 吗？

**使用场景**:
- 开始任何开发任务前的状态检查
- 不确定应该使用哪个工作流
- 需要系统推荐最佳执行路径
- 查询多模块项目的整体进度

**不使用场景**:
- 已知要执行特定 Phase → 直接调用 Phase Skill
- 只想运行特定步骤 → 直接调用步骤 Skill

---

## 核心功能

| 功能 | 描述 |
|------|------|
| **状态感知** | 收集 Git 状态、UPM 进度、OpenSpec 状态、审计状态、自定义检查、变更分析 |
| **智能推荐** | 基于状态生成工作流推荐，附带理由说明 |
| **用户确认** | 展示选项，让用户确认或自定义工作流 |
| **工作流启动** | 将确认的工作流传递给 workflow-runner 执行 |

---

## 配置 (config-loader)

执行前读取 `.aria/config.json`，缺失则使用默认值。参见 [config-loader](../config-loader/SKILL.md)。

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `state_scanner.confidence_threshold` | `90` | 置信度阈值 (0-100) |
| `state_scanner.auto_execute_enabled` | `false` | 高置信度自动执行 |
| `state_scanner.auto_execute_rules` | `["commit_only", "quick_fix", "doc_only"]` | 允许自动执行的规则 |
| `state_scanner.audit_log_path` | `".aria/audit.log"` | 审计日志路径 |
| `state_scanner.mechanical_mode` | `true` | v3.0.0+: `true` 走 scan.py 路径, `false` 回退 v2.x prose 路径 (v1.18.0 移除) |
| `workflow.auto_proceed` | `false` | Phase 间自动推进 |

---

## 执行流程

### Step 0: 机械执行 scan.py (v3.0.0 硬约束)

> **不可协商**: Phase 1 所有字段由 `scripts/scan.py` 机械采集, AI 不得跳过 / 不得逐字段手工 Bash 替代 / 不得在失败时"降级"到手工采集。

**执行命令**:

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-aria}/skills/state-scanner/scripts/scan.py" \
  --output .aria/state-snapshot.json
```

**退出码契约** (详见 [state-snapshot-schema.md](./references/state-snapshot-schema.md) §Exit code consumer contract):

| 退出码 | 含义 | AI 动作 |
|--------|------|---------|
| 0 | 全部采集成功 | 读 `.aria/state-snapshot.json`, 进入阶段 2 |
| 10 | 部分采集软错误 (snapshot 仍可用, 见 `errors[]`) | 读 snapshot, 对受影响子阶段展示 warning, 继续阶段 2 |
| 20 | 硬前置失败 (非 git repo / 输出路径写入失败) | abort, 不读 snapshot, 展示 stderr |
| 30 | 未捕获异常 (scan.py 内部 bug) | abort, 展示 stderr, 提示 report bug |

**Schema 版本契约**: snapshot 顶层 `snapshot_schema_version` 当前 `"1.0"`, 采用 additive-only 演进 (新字段兼容, 删/改字段需 bump). 详见 [state-snapshot-schema.md](./references/state-snapshot-schema.md) §Versioning。

**AI 禁区 (v3.0.0 机械化契约)**:

| 行为 | 允许 |
|------|------|
| 用 `git status` / `ls openspec/` 等命令逐字段采集替代 scan.py | ❌ 不允许 |
| scan.py 失败时手工 Bash 补齐 snapshot (绕过 Phase 1.11/1.13 opt-in) | ❌ 不允许 |
| scan.py 成功后读取 snapshot 引用的外部文件 (audit report 原文 / Story body 细节) | ✅ 允许 |
| Phase 3 展示 / Phase 4 传递给 workflow-runner 走 prose 路径 | ✅ 允许 (这些不是数据采集) |

**Opt-out** (过渡期): `.aria/config.json` 设 `state_scanner.mechanical_mode=false` → 回退 v2.x prose 路径. 该 flag 计划 v1.18.0 移除 (AD-SSME-5), 期间零告警使用量 = 安全移除信号。

---

### 阶段 0: 中断检测 (scan.py `collectors/interrupt.py`)

> 详细逻辑见 [interrupt-recovery.md](./references/interrupt-recovery.md) | 状态格式见 [workflow-state-schema.md](../workflow-runner/references/workflow-state-schema.md)

snapshot 字段: `interrupt` (含 `.aria/workflow-state.json` 解析结果, `git_anchor.branch` 验证, 并发冲突检测).

AI 负责: 根据 `interrupt.status` 值:
- `none` / 文件缺失 → 直接进入阶段 2 推荐
- `in_progress` / `suspended` → 展示 **[1]Resume [2]Abandon [3]Inspect**; Resume → workflow-runner(resume=true), Abandon → 提示删 `.aria/workflow-state.json` 后进阶段 2, Inspect → 展示 `interrupt.context` 后回选择
- `failed` → 展示 **[1]Retry [2]Abandon [3]Inspect**

---

### 阶段 1: 状态采集 (scan.py 机械产出)

> **字段完整定义 (source-of-truth)**: [state-snapshot-schema.md](./references/state-snapshot-schema.md)

scan.py 按顺序执行以下子阶段, 每个子阶段对应一个 collector 模块, 产出固定 snapshot 顶层字段:

| 子阶段 | 职责 | Snapshot 顶层字段 | collector 模块 |
|--------|------|-------------------|---------------|
| 1      | Git / UPM / 变更 | `git`, `upm`, `changes` | `collectors/git.py`, `collectors/upm.py`, `collectors/changes.py` |
| 1.5    | 需求追踪 | `requirements` | `collectors/requirements.py` |
| 1.6    | OpenSpec | `openspec` | `collectors/openspec.py` |
| 1.7    | 架构文档 | `architecture` | `collectors/architecture.py` |
| 1.8    | README 同步 | `readme` | `collectors/readme.py` |
| 1.9    | Standards 子模块 | `standards` | `collectors/standards.py` |
| 1.10   | 审计 | `audit` | `collectors/audit.py` |
| 1.11   | 自定义检查 (opt-in) | `custom_checks` | `collectors/custom_checks.py` |
| 1.12   | 同步检测 (单 + 多远程 parity) | `sync_status` | `collectors/sync.py`, `collectors/multi_remote.py` |
| 1.13   | Issue 感知 (opt-in) | `issue_status` *(仅 `issue_scan.enabled=true` 时出现)* | `collectors/issue_scan.py` |
| 1.14   | Forgejo 配置 | `forgejo_config` | `collectors/forgejo_config.py` |
| 聚合   | 失败软错误列表 | `errors` | scan.py 聚合 |

**opt-in 阶段** (未启用则对应 snapshot 字段 `configured: false`, scan.py 不阻塞):

- **1.11 custom_checks**: 需项目根有 `.aria/state-checks.yaml`
- **1.13 issue_scan**: 默认 `false`, 需 `.aria/config.json` 设 `state_scanner.issue_scan.enabled=true`
- **1.12 sync_check**: 默认 `true`, 可关闭 `state_scanner.sync_check.enabled=false`

**子阶段深度参考** (实现 + schema 细节):
- Phase 1.12 同步检测 (方向性守卫 / 多远程 parity): [sync-detection.md](./references/sync-detection.md)
- Phase 1.13 Issue 感知 (平台检测 / 10 种 fetch_error / submodule 聚合): [issue-scanning.md](./references/issue-scanning.md)
- 所有字段 enum / 边界条件 / additive 演进规则: [state-snapshot-schema.md](./references/state-snapshot-schema.md)

**AI 阶段 1 职责**: 仅验证 scan.py 退出码 (0/1/2 语义见 Step 0 表格), 读 snapshot 传入阶段 2。不得手动逐字段解析或补齐。

---

### 阶段 2: 推荐决策

**入口断言 (v3.0.0 硬约束)**:

1. 读取 `.aria/state-snapshot.json`:
   - 文件缺失 → abort, 提示 "Step 0 未执行或 scan.py 失败, 请重跑 /state-scanner"
2. 验证 `snapshot_schema_version`:
   - 字段缺失 → abort, 提示 "snapshot 格式异常, 可能是过期版本"
   - 值 != `"1.0"` → abort, 提示 "scan.py schema 版本 (X.Y) 与 SKILL.md 契约 (1.0) 不兼容, 请升级 aria-plugin"
3. 通过 → 基于 snapshot 各字段按优先级匹配推荐规则

**推荐规则类别** (详见 [RECOMMENDATION_RULES.md](./RECOMMENDATION_RULES.md)):

- 基础工作流: commit_only → quick_fix → feature_with_spec → feature_new
- 需求相关: requirements_issues, pending_stories, missing_prd, missing_openspec
- 审计相关: audit_unconverged (存在未收敛审计报告)
- 自定义检查: custom_check_failed (severity=error 阻断) / custom_check_warning (severity=warning 降级 + fix 提示)
- 同步检测: submodule_drift / branch_behind_upstream / multi_remote_drift
- Issue 感知: open_blocker_issues (blocker/critical label 降级)
- PRD 状态: prd_draft_blocking (Draft PRD 关联 ≥5 Story 时优先推荐审阅拍板)

**audit 状态集成**: 当 `audit.enabled == true` 时, 推荐输出中展示:
- 上次审计的 `verdict` 和 `converged` 状态
- 若 `audit.has_unconverged == true`, 提示用户处理 (查看报告 / 重新审计 / 接受当前结论)

### 阶段 3: 用户确认

```yaml
展示内容:
  - 当前状态摘要
  - 主推荐工作流 (标记 "推荐")
  - 2-3 个备选方案
  - 自定义组合选项

用户可以:
  - 选择推荐 [1]
  - 选择备选 [2-4]
  - 输入自定义 (如 "B.2 + C.1")
```

**默认行为: 必须展示 [1]-[4] 编号选项并等待用户选择。** 高置信度自动执行仅在 `.aria/config.json` 中 `auto_proceed=true` 且置信度 >90% 时触发，否则始终展示编号选项。详见 [references/confidence-scoring.md](./references/confidence-scoring.md)。

### 阶段 4: 工作流启动

```yaml
输出到 workflow-runner:
  workflow: 确认的工作流名称或自定义步骤
  context:
    phase_cycle: 当前进度
    module: 活跃模块
    changed_files: 变更文件列表
    skip_steps: 智能跳过的步骤
    complexity_level: Level1/Level2/Level3   # 传递给 workflow-runner
    audit:                                   # 审计配置摘要 (仅 audit.enabled=true 时)
      enabled: true
      mode: adaptive                        # 当前审计模式
      active_checkpoints: [post_spec, ...]  # 启用的检查点
```

**adaptive 集成**: state-scanner 的复杂度评估 (`changes.complexity`, scan.py 输出字段) 通过 `context.complexity_level` 传递给 workflow-runner。workflow-runner 在调用 Phase Skills 时将 Level 信息传递给 audit-engine，用于 adaptive 模式下按 `adaptive_rules` 决定各检查点使用 convergence 还是 challenge 模式 (Level 1 = off, Level 2 = convergence, Level 3 = challenge，可通过 config 覆盖)。

---

## 输出格式

> 完整输出格式参见 [references/output-formats.md](./references/output-formats.md)

### 标准输出示例

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
  ⚠️ PRD Draft 待拍板: prd-phase3-commercial-launch.md
     关联: 20 US | Soft Launch: 2026-04-30
  ✅ PRD Approved: prd-aria-v2.md (7 US)
  User Stories: 8 个 (ready: 3, in_progress: 2, done: 3)
  OpenSpec 覆盖: 5/8 (62.5%)
  (注: 无 Draft PRD 或无 prd_files 数据时省略 PRD 行, 保持原简洁格式)

🏗️ 架构状态
───────────────────────────────────────────────────────────────
  System Architecture: ✅ 存在
  状态: active | 需求链路: ✅ 完整

📋 OpenSpec 状态
───────────────────────────────────────────────────────────────
  活跃变更: 2 个 | 已归档: 5 个 | 待归档: 0 个

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

🔄 同步状态
───────────────────────────────────────────────────────────────
  当前分支: master (落后 origin/master 3 commits)
  远程引用: 2h 前同步
  子模块:
    ✅ standards: 同步
    ⚠️  aria: 落后远程 4 commits
        修复建议: git submodule update --remote aria

🎫 Open Issues
───────────────────────────────────────────────────────────────
  平台: Forgejo (10CG/Aria) — 3 open
  📌 #6  state-scanner issue scan         [enhancement]
         → 已关联 OpenSpec: state-scanner-issue-awareness
  数据来源: cache (2m ago) | ttl: 15m

🎯 推荐工作流
───────────────────────────────────────────────────────────────
  ➤ [1] feature-dev (推荐)
      理由: 已有 OpenSpec，代码和测试就绪
  ○ [2] quick-fix
  ○ [3] full-cycle
  ○ [4] 自定义组合

🤔 选择 [1-4] 或输入自定义:
```

各场景的输出变体 (未配置、链路不完整、待归档、头脑风暴建议等) 见 [references/output-formats.md](./references/output-formats.md)。

---

## 输入参数

| 参数 | 必需 | 说明 | 示例 |
|------|------|------|------|
| `intent` | ❌ | 用户意图 (影响推荐) | "提交代码", "开发功能" |
| `module` | ❌ | 目标模块 (自动检测) | `mobile`, `backend` |
| `skip_recommendation` | ❌ | 跳过推荐直接扫描 | `true`, `false` |

---

## 使用示例

### 示例 1: 智能推荐

```yaml
用户: "我要提交代码"

state-scanner 执行:
  Step 0: python3 scripts/scan.py --output .aria/state-snapshot.json
  阶段 2: 读 snapshot, changes.file_types=[code, test] + openspec add-auth=approved
           → 匹配 feature_with_spec 规则
  阶段 3: 展示推荐 feature-dev, 等待确认
  阶段 4: 用户选 [1], 调 workflow-runner

输出到 workflow-runner:
  workflow: feature-dev
  skip_steps: [A.1, A.2, A.3, B.3]
```

### 示例 2: 自定义组合

```yaml
用户: "只运行测试和提交"

state-scanner 执行:
  Step 0: scan.py 产出 snapshot
  阶段 2-3: 展示推荐

用户: "B.2 + C.1"

输出到 workflow-runner:
  workflow: custom
  steps: [B.2, C.1]
```

### 示例 3: 仅查看状态

```yaml
用户: "查看项目状态"
输入: skip_recommendation: true

state-scanner 执行:
  Step 0: scan.py 产出 snapshot
  阶段 1: 展示 snapshot 摘要 (format 见 output-formats.md)

结束，不调用 workflow-runner
```

---

## 推荐规则配置

详细推荐规则 (优先级、条件、自定义扩展) 见 [RECOMMENDATION_RULES.md](./RECOMMENDATION_RULES.md)。

---

## 与 Phase Skills 的关系

```
state-scanner v3.0 (本 Skill)
    │
    │ Step 0: scan.py → snapshot.json
    │ 阶段 2-4: 推荐 + 用户确认
    ▼
workflow-runner v2.0
    │
    ├──▶ phase-a-planner (A.1-A.3)
    ├──▶ phase-b-developer (B.1-B.3)
    ├──▶ phase-c-integrator (C.1-C.2)
    └──▶ phase-d-closer (D.1-D.2)
```

---

## 实现注意事项

> **重要**: Claude Code 在 Windows 上使用 Git Bash/WSL。scan.py 是 stdlib-only Python, 本身跨平台兼容; AI 辅助命令 (展示 / 文件读取) 仍需遵循跨平台语法。

### 跨平台命令规范

| ✅ 正确 | ❌ 错误 |
|---------|---------|
| `ls path/*.md 2>/dev/null \|\| echo "NO"` | `if exist path\*.md (dir ...) else (echo NO)` |
| `ls docs/requirements/` | `dir docs\requirements\` |
| `[ -f file ] && cat file` | `if exist file (type file) else ...` |
| 路径使用 `/` | 路径使用 `\` |
| `2>/dev/null` | `2>nul` |

### 参考文档

详细的跨平台命令示例和调试技巧，见 **[`references/cross-platform-commands.md`](./references/cross-platform-commands.md)**。

---

## 错误处理

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| scan.py exit 20 | 非 git repo / 输出路径写入失败 (硬前置失败) | 根据 stderr 提示修复, 重跑 |
| scan.py exit 30 | 未捕获异常 (scan.py 内部 bug) | 收集 stderr 提交 issue, 临时 opt-out `mechanical_mode=false` |
| snapshot 文件缺失 | Step 0 未执行或被中断 | 重跑 `/state-scanner` |
| snapshot_schema_version 不匹配 | scan.py 与 SKILL.md 版本漂移 | 升级 aria-plugin 至匹配版本 |
| 推荐冲突 | 多规则同时匹配 | 按优先级选择第一个 (见 RECOMMENDATION_RULES.md) |
| Bash 语法错误 (辅助命令) | 使用了 Windows CMD 语法 | 参考跨平台命令规范 |

---

## 检查清单

### 使用前
- [ ] 有待处理的变更或任务
- [ ] 了解大致想做什么

### 使用后
- [ ] Step 0 scan.py 成功 (exit 0/10) 产出 snapshot
- [ ] 已了解当前项目状态 (读 snapshot)
- [ ] 已确认执行的工作流
- [ ] workflow-runner 已接收执行计划

---

## 相关文档

### 参考文件
- [state-snapshot-schema.md](./references/state-snapshot-schema.md) - **scan.py 输出 schema (source-of-truth)**
- [RECOMMENDATION_RULES.md](./RECOMMENDATION_RULES.md) - 推荐规则定义 (含置信度评分)
- [confidence-scoring.md](./references/confidence-scoring.md) - 置信度评分与自动执行策略
- [interrupt-recovery.md](./references/interrupt-recovery.md) - 中断恢复详细逻辑
- [output-formats.md](./references/output-formats.md) - 各场景输出格式定义
- [migration-v1-to-v2.md](./references/migration-v1-to-v2.md) - v1.0 → v2.0 迁移说明
- [cross-platform-commands.md](./references/cross-platform-commands.md) - 跨平台命令参考
- [sync-detection.md](./references/sync-detection.md) - 同步检测详细逻辑 (Phase 1.12)
- [issue-scanning.md](./references/issue-scanning.md) - Issue 扫描详细逻辑 (Phase 1.13)
### 审计相关
- [audit-engine](../audit-engine/SKILL.md) - 多轮收敛审计编排引擎
### 工作流相关
- [brainstorm](../brainstorm/SKILL.md) - 头脑风暴引擎
- [workflow-runner](../workflow-runner/SKILL.md) - 工作流执行器
- [phase-a-planner](../phase-a-planner/SKILL.md) - 规划阶段
- [phase-b-developer](../phase-b-developer/SKILL.md) - 开发阶段
- [phase-c-integrator](../phase-c-integrator/SKILL.md) - 集成阶段
- [phase-d-closer](../phase-d-closer/SKILL.md) - 收尾阶段

---

**最后更新**: 2026-04-24
**Skill版本**: 3.0.0 (2026-04-24: T5 机械化契约 — Step 0 scan.py 硬约束 + Phase 2 入口断言 + 阶段 1 prose → schema.md 引用)

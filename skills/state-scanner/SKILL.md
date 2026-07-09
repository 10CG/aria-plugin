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
> **机械化**: v3.0.0 起 Phase 1.x 由 `scripts/scan.py` (stdlib-only Python) 机械产出 JSON snapshot, AI 读 snapshot 进入阶段 2 推荐。v2.x prose 路径保留 `mechanical_mode=false` opt-out, 计划下一 minor (v1.19.0+) 移除 (AD-SSME-5;v1.18.0 ship 时仍保留 — 监测使用量后决定)。

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
| `state_scanner.mechanical_mode` | `true` | v3.0.0+: `true` 走 scan.py 路径, `false` 回退 v2.x prose 路径 (计划 v1.19.0+ 移除, v1.18.0 ship 时仍保留) |
| `state_scanner.issue_scan.platform_hostnames.forgejo` | `["forgejo.10cg.pub"]` | v1.30.0+: Forgejo hosts 可通过 `ARIA_FORGEJO_HOSTS` env var (comma-separated) 覆盖, 优先级 env > config > default; 同时影响 `forgejo_config` 和 `issue_scan` 两 collector (per OpenSpec aria-forgejo-hosts-parameterization) |
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

**Opt-out** (过渡期): `.aria/config.json` 设 `state_scanner.mechanical_mode=false` → 回退 v2.x prose 路径. 该 flag 计划下一 minor (v1.19.0+) 移除 (AD-SSME-5);v1.18.0 ship 时仍保留, 期间零告警使用量 = 安全移除信号。

---

### 阶段 0: 中断检测 (scan.py `collectors/interrupt.py`)

> 详细逻辑见 [interrupt-recovery.md](./references/interrupt-recovery.md) | 状态格式见 [workflow-state-schema.md](../workflow-runner/references/workflow-state-schema.md)

snapshot 字段: `interrupt` (含 `.aria/workflow-state.json` 解析结果, `git_anchor.branch` 验证, 并发冲突检测).

AI 负责: 根据 `interrupt.status` 值:
- `none` / 文件缺失 → 直接进入阶段 2 推荐
- `in_progress` / `suspended` → 展示 **[1]Resume [2]Abandon [3]Inspect**; Resume → workflow-runner(resume=true), Abandon → 提示删 `.aria/workflow-state.json` 后进阶段 2, Inspect → 展示 `interrupt.context` 后回选择
- `failed` → 展示 **[1]Retry [2]Abandon [3]Inspect**

**git 操作感知 (Aria #135, v1.39.0+, 与 interrupt 正交)**: snapshot 另有 `git.git_operation_in_progress` 字段 (collectors/git.py 采集), 检测暂停中的 git 层操作 (`operation` ∈ {none, rebase, merge, cherry_pick, revert, bisect} + `has_conflicts`)。这与 `interrupt.status` **正交、互不篡改** —— interrupt 只看 `.aria/workflow-state.json`, 检测不到 git 中间态 (rebase 暂停态 `detached_head` 仍为 False)。`operation != "none"` 时, 阶段 2 由 `git_operation_in_progress` 规则 (priority 0.5, 见 RECOMMENDATION_RULES.md) **降级/阻止含 checkout·分支操作的常规推荐**, 引导先 `git <op> --continue`/`--abort` (`has_conflicts=true` 措辞升级)。绝不代用户操作 git。

---

### 阶段 1: 状态采集 (scan.py 机械产出)

scan.py 按顺序执行 15 个 collector 子阶段, 每个产出 snapshot 一个固定顶层字段 (`git` / `upm` / `changes` / `requirements` / `openspec` / `architecture` / `readme` / `standards` / `audit` / `custom_checks` / `sync_status` / `issue_status` (opt-in) / `forgejo_config` / `handoff` / `handoff_worktrees` (Step 1.15b, #139 cross-worktree discovery) / `coordination_fetch` (Step 1.16, multi-terminal) / `tracks_multibranch` (Step 1.17, multi-terminal) + `errors[]` 聚合)。

**Opt-in 子阶段**: 1.11 custom_checks (需 `.aria/state-checks.yaml`) / 1.13 issue_scan (config flag) / 1.12 sync_check (可关闭)。

**AI 职责**: 仅验证 scan.py 退出码, 读 snapshot 传入阶段 2。**不得**手动逐字段解析或补齐。

**完整 collector 子阶段表 + opt-in 配置 + Step 1.16/1.17 multi-terminal detail + 子阶段深度参考链接 + TASK-005/006 design decision notes**: 见 [references/phase-1-collectors.md](./references/phase-1-collectors.md)。

**字段定义 source-of-truth**: [references/state-snapshot-schema.md](./references/state-snapshot-schema.md)。

---

## Layer L Phase B 集成 (multi-terminal-coordination v1.22.x+; advisory 接活 DEC-20260704-002)

P2 Layer L 已 ship (TASK-010~022, 108 tests PASS)。**DEC-20260704-002 完成了母 spec 从未落地的 TASK-024 集成** —— `run_gate()` 从死代码 (零生产调用) 接活成 **advisory 认领**: AI 编排层 (本 skill 阶段 2 / Phase B-entry) 首次成为 `run_gate` 的调用者。

### 编排契约 (AI 阶段 2 → Phase B-entry, 非 scan.py)

**接线点 = AI 编排层, 不是 `scan.py`** (layer-l-integration.md:15 Design A: 闸门仅在用户确认进 Phase B 时调用, 不在只读 collector 内自动跑)。触发条件 (**opt-in**): `state_scanner.coordination.enabled == true` **且** `tracks_multibranch.collision.kind` 非空 (cross-owner / self_multi_container)。

调用时序:
```
scan.py → snapshot (含 tracks_multibranch.collision.kind)
  → 阶段 2 推荐: AI 读 collision.kind + 读最新 handoff §6 选定 carry-id (raw_track_id)
  → 用户确认进入 Phase B (phase-b-developer B.1 / branch-manager)
  → AI 编排层经 subprocess 调 phase1_gate CLI (Phase B 启动前, 对齐 :44):
      python3 "${CLAUDE_PLUGIN_ROOT:-aria}/skills/state-scanner/scripts/phase1_gate.py" \
        --raw-track-id "<§6 选定 carry-id 原始串>" --phase B --mode advisory --repo-path "<repo root>"
  → 解析 stdout JSON (GateResult projection); exit 0 = 可进 Phase B
```

- **carry-id 原始串直接传入** `--raw-track-id`; 归一 (`derive_track_id`) 在 `run_gate` 内部完成, 编排层不预归一 (R1-m6)。carry-id 来源 = handoff §6 结构化 `{id, desc}` (见 `standards/conventions/session-handoff.md §2.3`)。
- **mode 由 `state_scanner.coordination.mode` 决定** (默认 `advisory`)。advisory = 放行 + 写推自己 claim + 返回 surface 告警 (advisory-over-hardlock); reconcile 仍是最终仲裁 (earliest claimed_at 胜)。
- **CLI 是 advisory 设计**: 单次 JSON I/O 传不了活体 user_decision 回调; `mode=block` 经 CLI 退化为安全默认 abort (已知限制, 生产默认 advisory)。

### JSON 消费 + surface 渲染 (阶段 2 推荐区)

CLI 输出 `{outcome, proceed, track_id, error, own_claim, competing_winner, surface, push_success}`。渲染规则:
- `proceed == true` (outcome ∈ passed / advisory_proceed / user_takeover / user_override_proceed) → 放行进 Phase B。
- `surface != null` → 在推荐区渲染 🔴 告警行 (**按 `surface.kind` 分化, 不 blanket 静默** R2-Major-B):
  - `kind == "occupied"` → 🔴 `surface.message` (含 `<owner/container> <age> 已认领 <carry-id>`), **回显 `surface.carry_id` 供逐字 copy** (R1-m5, 减少转录漂移)。
  - `kind == "clock_skew"` → 🔴 `surface.message` (含 `max_clock_skew_seconds`) —— 最高风险路径, 提示查容器时钟同步; advisory **不吞** 此告警。
  - `kind == "push_failed"` → 🔴 claim 已写本地未同步远端, reconcile 下次 fetch 仲裁。
- `enabled == false` (默认) → **零调用** `run_gate` (向后兼容, 无 collision surface)。

**完整设计意图 (phase1_gate 9-step 序列 / acquire_claim+heartbeat+release 调用关系 / advisory outcome 映射 / track_board+latest_md_writer 输出)**: 见 [references/layer-l-integration.md](./references/layer-l-integration.md)。

---

### 阶段 2/3/4: 推荐决策 / 用户确认 / 工作流启动

阶段 2 = 推荐决策 (snapshot 入口断言 + 推荐规则匹配 + audit 集成 + **handoff awareness mandatory** [H0 spec 防 4 起历史 bug] + inter-cycle resume sanity check)。
阶段 3 = 用户确认 ([1]-[4] 编号选项 + 自定义组合, auto_proceed 仅 ≥90% confidence 触发)。
阶段 4 = 工作流启动 (输出 workflow + context 给 workflow-runner, 含 complexity_level for adaptive audit)。

**完整流程 (阶段 2 入口断言 + 推荐规则类别 + audit 集成 + handoff awareness 3-branch logic + inter-cycle sanity check / 阶段 3 用户确认 / 阶段 4 workflow-runner 输出 schema + adaptive 集成)**: 见 [references/recommendation-stages.md](./references/recommendation-stages.md)。

---

## 输出格式

推荐输出含以下 **10 个 canonical 区块 (按顺序)**。每区块只在数据可用时显示, 空状态优雅降级。下方骨架给出**每区块的关键字段**, 使「不读 reference 也能正确排版到字段层」成立 (#72: 仅列区块名会致字段层漂移)。完整字段措辞 / 各漂移变体仍以 `references/output-formats.md` 为准。

1. **📍 当前状态** — 分支 / 模块 / Phase·Cycle / 变更文件数 / 关联 OpenSpec
2. **📊 变更分析** — 变更类型 / 复杂度 Level / 架构影响 / 测试覆盖
3. **📄 需求状态** — 配置状态 / PRD (名 + status) / User Stories (按 status 计数) / OpenSpec 覆盖率
4. **🏗️ 架构状态** — System Architecture 存在? / 路径 / status / 最后更新 / 需求链路完整性
5. **📋 OpenSpec 状态** — 活跃变更 (按 status 计数) / 已归档数 / 待归档数 / 设计未实施 (`design_deferred[]` 非空时: ⚠️ N 个 — id + status + staleness_days, #134 v1.42.0+)
6. **🛡️ 审计状态** — 审计系统 enabled? + 模式 / 活跃检查点 / 上次审计 verdict (含收敛轮数)
7. **🔧 自定义检查** — 逐 check: ✅OK / ⚠️STALE / ❌FAIL + 修复建议 (失败项)
8. **🔄 同步状态** — 当前分支 ahead/behind + upstream / 多远程 parity。条件子项: 📝 README 版本一致性 / 📦 插件依赖 (standards 子模块) / 🔗 Forgejo 配置检查 — 仅相关时显示
9. **🎫 Open Issues** — open_count / 按 repo 分组 / 关键 issue (number + 标题 + linked US) — opt-in, 仅 `issue_scan.enabled=true` 显示
10. **🎯 推荐工作流** — 编号选项 [1]-[4] (推荐项标注) + 执行步骤 + 跳过项 + 理由

> 另有条件块在特定场景插入 (见 output-formats.md): 🔬 Skill 变更 AB 状态 (检出 SKILL.md 变更时) / handoff awareness (Phase 1.15, handoff doc surfaced 或 drift) / 🌲 跨 worktree 交接 (Phase 1.15b, #139, `handoff_worktrees.global_latest_elsewhere` 为 active 时)。

**完整标准输出示例 + 各场景输出变体 (未配置、链路不完整、待归档、头脑风暴建议等)**: 见 [references/output-formats.md](./references/output-formats.md)。

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

## Status 字段最佳实践

`_normalize_status` 归一化 11 个 lifecycle state (archived / deprecated / pending / in_progress / implemented / approved / reviewed / active / ready / done / unknown), 驱动 pending_archive / requirements / 推荐规则。首段截断规则 (aria-plugin #50): em-dash 后 narrative 不参与归类。

**完整 token set 表 / 推荐 Status 格式 / 首段截断分隔符规则 / Anti-pattern substring shadows / Implementation note**: 见 [references/status-field-guide.md](./references/status-field-guide.md)。

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
- [migration-v2.9-to-v3.0.md](./references/migration-v2.9-to-v3.0.md) - v2.9 → v3.0 机械化迁移 (含 mechanical_mode opt-out 说明)
- [cross-platform-commands.md](./references/cross-platform-commands.md) - 跨平台命令参考
- [sync-detection.md](./references/sync-detection.md) - 同步检测详细逻辑 (Phase 1.12)
- [issue-scanning.md](./references/issue-scanning.md) - Issue 扫描详细逻辑 (Phase 1.13)
- [runtime-probe-declaration.md](./references/runtime-probe-declaration.md) - 归档门 runtime_probe 声明 schema (给声明作者, #95 follow-up A)
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

**最后更新**: 2026-05-22 (state-scanner-status-extraction-range #50: `_status` 首段截断 + delivered/shipped token + soft_error)
**Skill版本**: 3.1.1 (2026-05-22: `_status_lifecycle_head` 首段截断修复 aria-plugin #50 — 长单行 Status token shadow;3.1.0: 2026-05-09 inter-cycle-surfacing G2/G3/G4 — 见 v1.18.0 CHANGELOG)

# Layer L Phase B Integration (multi-terminal-coordination v1.22.x+)

> **状态**: P2 Layer L 已 ship (TASK-010~022, 108 tests PASS).
> **TASK-024 已完成 / advisory 接活**(`interactive-session-dedup-coordination`, DEC-20260704-002): `phase1_gate` 已集成到 state-scanner 主流程的 AI 编排层(阶段 2 推荐 → 用户确认进入 Phase B → CLI 调用, 非 scan.py 自动执行), advisory 为默认模式(本文档记录设计意图与实际调用关系)。

本文档概览 Phase 1 结束后、Phase 2 推荐决策前的 Layer L 多终端协调集成点。

## 何时触发 phase1_gate

`scripts/phase1_gate.py` 实现**急切认领闸门 (eager-claim gate)**, 在以下条件下触发:

- 当前项目 `state_scanner.coordination.enabled == true` (**默认 `true`, opt-out** — coordination-claim-lifecycle-and-overlap Part A1 把默认 false→true; 显式设 false 退回 rule 1.54 advisory)
- **同容器并发检测 (TASK-023)**: 同一 `container-id` 内有 ≥2 个 active claim (Phase B 或以上) 时强提示
- **cross-owner collision**: `tracks_multibranch` snapshot 包含同一 `track-id`、不同 `owner` 的活跃 track → 触发闸门;**advisory(默认)**: claim 先写(acquire_claim), reconcile 事后仲裁, 不阻塞用户继续;**block(可选模式)**: 保留原姿态, 要求用户 reconcile 后再 claim
- **Design A 条件触发**: 闸门在用户确认要进入 Phase B 时调用, **不在 scan.py 内自动执行**。自 `a1-entry-claim-duplicate-work-guard` 起另有一个**更早**的触发点: **A.1 起草前**的入口认领 (`--phase A.1`) —— Phase B 的认领只能保护「已经做完 Phase A 的人不被打扰」, 保护不了「正要开始的人不做重复功」; 以及 `/state-scanner` 每次入口的 `--heartbeat-only` 刷新 (见下方设计段)。三个触发点同受 `coordination.enabled` 门控。

> **Disjointness 与切口2 (#133 concurrent_churn_detected, rule 1.54)**: phase1_gate 在 `coordination.enabled == true` 时处理 cross-owner collision;切口2 advisory (rule 1.54) 在 `coordination.enabled == false` 时 surface collision 提示。两者在 `enabled` 上**严格互斥**, 同一 scan **绝不双触发** (#133 AC-2)。

调用时序:

```
Phase 1.17 (handoff_multibranch) 产出 tracks_multibranch
          │
          ▼
阶段 2 推荐: AI 检查 tracks_multibranch.collision.kind
    ├── cross_owner → 强提示 + 触发 phase1_gate (pre-Phase B)
    ├── self_multi_container → soft hint (不阻塞)
    └── none → 正常推荐 Phase B
          │
          ▼ (用户确认进入 Phase B)
phase1_gate 9-step 序列:
    1. 二次 git fetch (fresh view)
    2. acquire_claim (orphan ref 写入 claim YAML)
    3. heartbeat 周期设置 (10min, 由 phase-b-developer mid-cycle 调用)
    4. 放行 Phase B 工作流
```

## acquire_claim / heartbeat / release 调用关系

这三个操作均由 `lib/` 模块实现 (TASK-010~018 ship):

| 操作 | 调用方 | 时机 | 实现位置 |
|------|--------|------|---------|
| `acquire_claim` | `phase1_gate` | Phase B 启动前 | `lib/coordination_ref.py` + `lib/claim_lifecycle.py` |
| `heartbeat` | AI 编排层, `/state-scanner` 每次入口 | 每次调用 (非定时器), 受 `coordination.enabled` 门控 | `lib/claim_lifecycle.py::heartbeat()` (按 `(container, session)`) / `heartbeat_by_track()` (按 `(container, 归一 track_id)`, 跨 session) |
| `release` | `phase-d-closer` D.2 归档后 | cycle 完成 / 放弃时 | `lib/claim_lifecycle.py::release_claim()` + `lib/reconcile.py` |

> **P2 已 ship**: `acquire_claim` / `heartbeat` API 已完成 (单测覆盖); `release` + GC `archive_done_claims` 写路径 deferred to P3 (code-reviewer 确认)。

## Layer L A.1 heartbeat 集成

`/state-scanner` 每次入口调一次 `phase1_gate.py --heartbeat-only`。命令行与
`state-scanner/SKILL.md` 的同名小节**逐字节相同**:

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-aria}/skills/state-scanner/scripts/phase1_gate.py" \
  --heartbeat-only --raw-track-id "<carry-id>" --phase A.1 --repo-path "<repo root>"
```

### carry-id 三级回落 (编排层负责, CLI 不推断)

| 级 | 来源 | 说明 |
|----|------|------|
| ① | 本 session 已持有的 claim 的 `track_id` | 最可靠 —— 就是自己刚认领的那一串 |
| ② | 最新 handoff §6 的结构化 carry-id (`standards/conventions/session-handoff.md §2.3.8` 的 `{id, desc}` 之 `id`) | 跨 session 接力时的唯一书面来源 |
| ③ | 两级都取不到 | **仍然调用**, 但不传 `--raw-track-id` ⇒ 遥测记一条 `skipped_no_track` |

③ 是刻意的: 静默不调用与「调了但没东西可刷」在事后完全不可分辨, 而这两件事的处置截然不同。
**CLI 不做推断** —— 它拿到什么刷什么, 三级判断全在编排层, 否则同一份回落逻辑会在两处各写一遍并分叉。

### 遥测分区边界

心跳遥测带 `source == "heartbeat"`, 路由到**非 production** 分区。
`coordination_probe` 的计数口径**不放宽**: 它判的是「闸门最近真被调用过」, 而心跳是每次入口都触发的高频动作 ——
把它计进去会让那个探针无论闸门死活都恒绿, 恰好废掉它存在的理由。

### fail-CLOSED 新鲜度谓词

「本轮拿到的协调视图是否新鲜」只有在
`coordination_fetch.success == true` **且** `coordination_ref_present == true`
时才成立 (字段见 `references/state-snapshot-schema.md` 的 `coordination_fetch` 段)。
两者任一不成立即按**未核实**处理, 不得当作「无碰撞」。

### degraded 处置

fetch 降级时**不重跑 fetch** —— 心跳的职责是刷新, 不是把协调视图修好。
处置是: 照常写本地, push 尝试一次即止 (fail-soft, 失败留给下次 fetch/reconcile 收敛)。
**代价披露**: 若违反「不自带 fetch」这条, 每次入口要多付约 **13.8s** (spike S2 实测) ——
那是把一个应当无感的心跳变成每次扫描都卡一下的东西。本地写 + 单次 push 的实测耗时待 B.2 回填。

## track_board 与 latest_md_writer 输出关系

```
Phase 1.17 tracks_multibranch snapshot
          │
          ├──▶ renderers/track_board.render_track_board(snapshot)
          │         → 多 track 表格 (阶段 2 推荐前展示给用户)
          │         → 渲染 collision badge (🔴 cross-owner / 🟡 self-multi)
          │
          └──▶ writers/latest_md_writer.write_latest_md(snapshot)
                    → D.3 scoped (由 phase-d-closer 调用, 非 scan.py 自动)
                    → 单 track: 更新 latest.md pointer
                    → 多 track: 写 deprecation banner (不覆盖 track pointer)
```

`latest_md_writer` **不**在 scan.py 内自动触发 (Finding #2, P1 closeout)。它是 D.3 工具, Phase 1 防接错棒来自 `render_track_board` 读全分支 frontmatter, 不依赖 `latest.md`。

## worktree 自动创建触发条件 (P3 scope — 仍未实施)

> **与上文消歧**: 上文"TASK-024 已完成"指 `phase1_gate` **闸门集成**(阶段 2 检查 collision.kind → 用户确认 → CLI 调用, 已由 `interactive-session-dedup-coordination` 接活)。本节 worktree **自动创建**(独立 checkout, 母 Spec `worktree_manager.py`)是 Layer L 另一子任务, **不因上文 gate 集成完成而连带完成** —— 明确划界避免重演 §Why.2 批判的自相矛盾(#95)。

worktree 自动创建的 **Design A 条件触发**设计(待实施):

- **触发**: `tracks_multibranch.collision.kind == "cross_owner"` → 推荐 worktree 独立 checkout
- **不触发**: no collision / self-multi-container → 正常单 worktree 工作流
- **实施(待做)**: phase1_gate 在检测到 cross-owner collision 后, 询问用户 "是否创建独立 worktree (推荐) 或强制使用当前 worktree (高风险)?"

> **与 #139 正交互补**: worktree 自动创建(cross_owner **创建** worktree)与 #139 cross-worktree-handoff-discovery (single-owner **进入**已存在 worktree, Phase 1.15b `handoff_worktrees` collector) 正交互补 — 前者在 owner 冲突时建议新建隔离 worktree, 后者在单 owner 多 worktree 并行时发现散落在他树的最新 handoff 并 advisory 引导 EnterWorktree。

> **状态**: worktree 自动创建仍是 P3 待实施 scope, 本文档仅记录设计意图供未来实施参考; 与上文已完成的 phase1_gate 闸门集成分属不同子任务。

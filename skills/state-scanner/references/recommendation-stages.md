# Recommendation Stages — 阶段 2 / 3 / 4

> Phase 1 (scan.py 机械采集) 之后的 AI-driven 阶段: 推荐决策 / 用户确认 / 工作流启动。从 SKILL.md §阶段 2/3/4 提取 (iter-2, 2026-05-28)。

## 阶段 2: 推荐决策

### 入口断言 (v3.0.0 硬约束)

1. 读取 `.aria/state-snapshot.json`:
   - 文件缺失 → abort, 提示 "Step 0 未执行或 scan.py 失败, 请重跑 /state-scanner"
2. 验证 `snapshot_schema_version`:
   - 字段缺失 → abort, 提示 "snapshot 格式异常, 可能是过期版本"
   - 值 != `"1.0"` → abort, 提示 "scan.py schema 版本 (X.Y) 与 SKILL.md 契约 (1.0) 不兼容, 请升级 aria-plugin"
3. 通过 → 基于 snapshot 各字段按优先级匹配推荐规则

### git 操作安全闸 (Aria #135, v1.39.0+, priority 0.5 先于一切常规规则)

入口断言通过后、匹配常规规则前, **先查 `git.git_operation_in_progress.operation`**:
- `== "none"` (或字段缺失, 向后兼容) → 正常进入推荐规则匹配。
- `!= "none"` (rebase/merge/cherry_pick/revert/bisect 暂停态) → 触发 `git_operation_in_progress` 规则 (RECOMMENDATION_RULES.md priority 0.5): **降级/阻止含 checkout·新分支操作的常规推荐**, 展示 warning + 引导先 `git <op> --continue`/`--abort`; `has_conflicts=true` 时措辞升级 (先解决冲突)。

> 该闸与阶段 0 `interrupt.status` **正交、互不篡改** —— interrupt 只看 `.aria/workflow-state.json`, 检测不到 git 中间态 (rebase 暂停态 `detached_head` 仍为 False, 故必须独立 collector 字段)。绝不代用户操作 git (只检测 + 警示)。

### 推荐规则类别

详见 [../RECOMMENDATION_RULES.md](../RECOMMENDATION_RULES.md):

- git 操作安全: git_operation_in_progress (priority 0.5, 暂停中 git 操作 → 阻断/降级常规推荐, Aria #135)
- 基础工作流: commit_only → quick_fix → feature_with_spec → feature_new
- 需求相关: requirements_issues, pending_stories, missing_prd, missing_openspec
- 审计相关: audit_unconverged (存在未收敛审计报告)
- 自定义检查: custom_check_failed (severity=error 阻断) / custom_check_warning (severity=warning 降级 + fix 提示)
- 同步检测: submodule_drift / branch_behind_upstream / multi_remote_drift
- Issue 感知: open_blocker_issues (blocker/critical label 降级)
- PRD 状态: prd_draft_blocking (Draft PRD 关联 ≥5 Story 时优先推荐审阅拍板)

### audit 状态集成

当 `audit.enabled == true` 时, 推荐输出中展示:
- 上次审计的 `verdict` 和 `converged` 状态
- 若 `audit.has_unconverged == true`, 提示用户处理 (查看报告 / 重新审计 / 接受当前结论)

### handoff awareness 集成 (Phase 1.15, H0 spec 2026-05-14)

AI 在阶段 2 推荐生成 **之前** MUST 检查 `snapshot.handoff`:

1. 若 `handoff.exists == true` 且 `handoff.age_hours < 720` (30 days):
   - **Read `handoff.latest_path`** — 读最新 session handoff 完整内容, 理解上 session 写明的 carry-forward 优先级 / next-step 建议
   - **H5 fix (2026-05-16)**: `handoff.latest_path` 已经是 pointer-resolved (collector 机械优先 `docs/handoff/latest.md` pointer target, mtime 仅 fallback)。AI **不再需要** 单独 parse latest.md — 直接信任 `latest_path`。`latest_source` 字段透明展示来源 (`pointer`/`mtime`); 若 `mtime` 且存在 `handoff_pointer_target_missing` soft_error, 提示用户 latest.md pointer stale 需修
   - 推荐输出 §当前状态 段展示 `latest_filename` + `age_hours` + `latest_source` (例: "上次 handoff: 2026-05-15-foo.md (12.1h ago, via pointer)")
   - 推荐生成时, handoff §next session 入口 / §未完成 列表的 priority items 应**优先**于 generic 推荐规则

2. 若 `handoff.misplaced_files != []`:
   - 触发 `RECOMMENDATION_RULES.md` `handoff_drift` rule (Layer 3 enforcement)
   - 推荐输出 §同步状态 段展示 misplaced count + canonical_dir reminder
   - 主推荐应是 "迁移漂移文件" 工作流 (优先于其他常规工作流, 但低于 audit_unconverged)

3. 若 `handoff.exists == false`:
   - 不阻塞推荐, 但提示首次 session 用户 phase-d-closer D.3 会引导写 handoff

4. 若 `handoff_worktrees.global_latest_elsewhere != null` (#139 cross-worktree, Phase 1.15b):
   - **触发条件**: 全局最新 handoff 在**其他** worktree 且其 `status == "active"` — 单人多 worktree 并行时, 上 session 把 handoff 写在 feature worktree (分支未合 main), 新 session 在主 worktree 启动会读不到它 (2026-06-04 SilkNode 事故)。
   - **advisory 输出** (advisory-over-hardlock, 非自动切): 警示该 handoff 的 `path` + `branch` + 编号选项 `[1] EnterWorktree 切过去续 track / [2] 留在当前 worktree / [3] 先看该 handoff`; 用户选 [1] 才执行。非 Claude Code 环境 (无 EnterWorktree 工具) → 降级打印 `cd <path>` 指引。
   - **`status` 为 `done`/`abandoned`/`legacy`**: `global_latest_elsewhere` 仍如实指向该 doc (仲裁诚实, 仅阶段 2 advisory 不触发 — 非字段级排除), **不触发** advisory (防误引导已收尾/身份不明 track), 仅在 §跨 worktree 交接 列表展示。
   - 与上方 1-3 (当前 worktree 的 `handoff.*`) 正交: 1-3 看当前树, 本分支看其他树。与 `RECOMMENDATION_RULES.md` 优先级数值表无关 (本 mandatory 集成步骤的分支, 触发时序在所有表内规则之前)。

**避免 4 次 dogfood 痛点重演**: 跳过 handoff 读取直接出推荐是历史已 4 起的 bug (SilkNode 2026-05-09 + Aria self 2026-05-13 ×3), H0 spec 的根本目的就是机械化此步骤。

### 完整性兜底 (inter-cycle resume — sanity check, post-G2/G3/G4 ship)

> 自 v1.18.0 起 (state-scanner-inter-cycle-surfacing G2/G3/G4 已实装), inter-cycle 优先级信号由 collector 字段直接产出 (`upm.followups[]` / `upm.handoff_doc` / `requirements.stories.priority_items[]`)。AI 不再需要主动 Read/Grep。
>
> Sanity check: 若 `upm.configured == true` 且 `raw_block != null`, 但以下任一字段缺失 — 检查 collector 实现可能退化:
> - `upm.followups` 字段不存在, 但 UPM 文本含 `## Pending Followups` 标题 (mechanical grep 验证)
> - `upm.handoff_doc` 键缺失 (而非 null), 表示 scan.py 版本可能过旧
> - `requirements.stories.priority_items` 字段不存在但 `stories.items[]` 含 in_progress 项
>
> 任一失配 → soft warn: "snapshot 字段构造异常, inter-cycle 优先级可能不完整。检查 collectors/upm.py 与 collectors/requirements.py 版本"。此 sanity check 不阻塞推荐, 但提示开发者排查 collector 版本漂移。

## 阶段 3: 用户确认

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

**默认行为: 必须展示 [1]-[4] 编号选项并等待用户选择。** 高置信度自动执行仅在 `.aria/config.json` 中 `auto_proceed=true` 且置信度 >90% 时触发, 否则始终展示编号选项。详见 [confidence-scoring.md](./confidence-scoring.md)。

## 阶段 4: 工作流启动

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

**adaptive 集成**: state-scanner 的复杂度评估 (`changes.complexity`, scan.py 输出字段) 通过 `context.complexity_level` 传递给 workflow-runner。workflow-runner 在调用 Phase Skills 时将 Level 信息传递给 audit-engine, 用于 adaptive 模式下按 `adaptive_rules` 决定各检查点使用 convergence 还是 challenge 模式 (Level 1 = off, Level 2 = convergence, Level 3 = challenge, 可通过 config 覆盖)。

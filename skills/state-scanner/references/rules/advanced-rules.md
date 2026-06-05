# State Scanner — 进阶规则

> 从 [RECOMMENDATION_RULES.md](../../RECOMMENDATION_RULES.md) 拆出。包含 Git 操作安全 (0.5) + Inter-cycle surfacing (1.85-1.895) + 审计 (1.9-1.91) + 自定义检查 (1.95-1.99) + Multi-Terminal 协调 (1.51-1.54) 5 个 cluster。

---

## Git 操作安全规则 (2026-06-05, state-scanner-git-operation-awareness / Aria #135)

### 0.5 git_operation_in_progress

```yaml
id: git_operation_in_progress
priority: 0.5   # 最高 — 安全闸, 先于一切常规工作流推荐
description: 仓库处于暂停中的 git 操作 (rebase/merge/cherry_pick/revert/bisect), 阻断/降级常规推荐

conditions:
  all:
    - git.git_operation_in_progress exists (key present)
    - git.git_operation_in_progress.operation != "none"

  detection:
    snapshot_path: "git.git_operation_in_progress.operation"
    field_check: "operation in {rebase, merge, cherry_pick, revert, bisect}"
    escalation: "git.git_operation_in_progress.has_conflicts == true → 措辞升级"

recommendation:
  workflow: null  # 不强推工作流, 触发阻断/降级提示
  info: "⚠️ 检测到暂停中的 git {operation} 操作 — 请先完成或放弃再继续"
  display:
    - "operation 类型 + detail (rebase head-name/onto 若有)"
    - "has_conflicts=true 时: 提示先解决冲突 (git diff --diff-filter=U)"
  suggestion:
    - "完成: git {operation} --continue"
    - "放弃: git {operation} --abort"
    - "降级/阻止本轮含 checkout·新分支操作的常规推荐, 避免破坏中间态"
  blocking: true   # 阻断常规推荐 (与 interrupt.status 正交, 不篡改既有中断恢复语义)
```

**Rationale (placement 0.5)**: 高于 `commit_only` (1)。暂停中的 git 操作是安全前置 —— 阶段 0 的 `interrupt.status` 只感知 `.aria/workflow-state.json`, 检测不到 git 层中间态 (Aria #135: rebase 暂停态 `detached_head` 仍为 False)。若不先浮出, 阶段 2 可能给出 checkout/分支推荐破坏 rebase·merge 中间态。该规则与 `interrupt.status` **正交**: 独立 collector 字段 `git.git_operation_in_progress`, 不改写中断恢复状态。

---

## Inter-cycle surfacing 相关规则详情 (2026-05-09, state-scanner-inter-cycle-surfacing G2/G3/G4)

### 1.85 pending_followups_p1

```yaml
id: pending_followups_p1
priority: 1.85
description: UPM Pending Followups 表存在 P1 行 — inter-cycle backlog 优先级提醒

conditions:
  all:
    - upm.followups exists (key present)
    - any(f.priority == "P1" for f in upm.followups)

  detection:
    snapshot_path: "upm.followups[]"
    field_check: "any row with priority == 'P1'"

recommendation:
  workflow: null  # 不强推工作流，触发降级提示
  info: "📌 UPM Pending Followups 含 {p1_count} 条 P1 项 — 跨 session backlog 待处理"
  display:
    - 前 5 条 P1 项 (item / source / tracking 摘要)
    - handoff_doc 路径 (若 upm.handoff_doc.exists=true)
  suggestion:
    - "Review UPM `## Pending Followups` 表"
    - "若指向 issue/PR, 可调 /aria:state-scanner 重新扫描"
  non_blocking: true
```

**Rationale (placement 1.85)**: 介于 architecture_chain_broken (1.8 — 项目健康) 与 audit_unconverged (1.9 — 流程健康) 之间。架构断链优先于 backlog 提醒, 但 P1 cross-cycle followup 应早于审计未收敛信号浮出 (因为它直接暗示用户该接续什么工作)。

---

### 1.88 resume_in_progress_us

```yaml
id: resume_in_progress_us
priority: 1.88
description: 存在 in_progress User Story — 推荐 inter-cycle resume 续做

conditions:
  all:
    - requirements.stories.priority_items exists
    - any(it.status_normalized == "in_progress" for it in priority_items)

  detection:
    snapshot_path: "requirements.stories.priority_items[]"
    field_check: "any item with status_normalized == 'in_progress'"

recommendation:
  workflow: continue-in-progress
  info: "🔄 续做进行中: {us_id} — {raw_status_first_line}"
  display:
    - in_progress US id + raw_status 第一行
    - 文件路径 (`docs/requirements/user-stories/{id}.md`)
  suggestion:
    - "调 /aria:phase-b-developer 续作 {us_id}"
    - "或 Read {file} 查看当前进度详情"
  non_blocking: false  # in_progress 是强信号，建议直接续做
```

**Rationale (placement 1.88)**: 紧邻 pending_followups_p1 (1.85) 之后。in_progress US 是当前 cycle 进行中的工作信号,优先级与 P1 followup 同级但稍后, 让 cross-cycle backlog 先浮出 (P1 可能是上 cycle 遗留, in_progress 是本 cycle 半成品)。

---

### 1.89 carry_forward_info (INFO tier, 1-4 items)

> 自 v1.23.0 起 (state-scanner-inline-carry-forward-surfacing, 2026-05-20),Phase 1.6.1 collector 扫描 active `openspec/changes/*/tasks.md` 浮出 inline carry-forward 注释。

```yaml
id: carry_forward_info
priority: 1.89
description: 1-4 inline carry-forward annotations in active openspec changes — INFO tier reminder

conditions:
  all:
    - openspec.carry_forward_inventory.total > 0
    - openspec.carry_forward_inventory.total < 5

  detection:
    snapshot_path: "openspec.carry_forward_inventory"
    field_check: "0 < total < 5"

recommendation:
  workflow: null  # INFO 不打断 primary workflow
  info: "ℹ {total} inline carry-forward annotation(s) across {by_change.keys() | join(', ')}"
  display:
    - 单行 summary,出现在 state-scanner 标准输出 "📌 Carry-forward inventory" section
  suggestion:
    - "若已是 known WIP,可继续推进;若漏遗,在当前 phase 完成前处理"
  non_blocking: true
```

### 1.895 carry_forward_pile (WARNING tier, ≥5 items)

```yaml
id: carry_forward_pile
priority: 1.895
description: ≥5 inline carry-forward annotations accumulated — advisory WARNING,suggest consolidation

conditions:
  all:
    - openspec.carry_forward_inventory.total >= 5

  detection:
    snapshot_path: "openspec.carry_forward_inventory"
    field_check: "total >= 5"

recommendation:
  workflow: null  # advisory, does not downgrade primary recommendation
  info: "⚠ Active OpenSpec changes have {total} accumulated inline carry-forward annotations."
  display:
    - 多行 indented 块, 出现在 "📌 Carry-forward inventory" section
    - 列前 3 changes by count (含 samples truncated 80 chars)
  suggestion:
    - "consolidate to project_v<XX>_carry_forward.md before next major checkpoint"
    - "或 address in current implementation phase"
  non_blocking: true
```

**Rationale (placement 1.89 / 1.895)**: 紧邻 resume_in_progress_us (1.88) 之后,与 in-flight signals 一族;在 audit_unconverged (1.9) 之前。INFO tier 用 priority 1.89,WARNING tier 用 1.895 ensure INFO 先于 WARNING 渲染时 visual ordering 正确(若同时触发,只 ≥5 命中 WARNING,1-4 命中 INFO,互斥)。

**Source incident**: TH v0.3.2 chat MVP 8 sessions / 14 days / 7 inline annotations 全 invisible until owner asked "是否会被遗忘?"。Forgejo Issues #90 (primary) + #89 (superset variant B)。

---


---

## 审计相关规则详情

### 1.9 audit_unconverged

```yaml
id: audit_unconverged
priority: 1.9
description: 最新审计报告未收敛，建议处理

conditions:
  all:
    - audit_enabled: true
    - has_unconverged: true           # 最新审计报告 converged == false

  detection:
    config_check: "config-loader → audit.enabled"
    report_scan: "ls .aria/audit-reports/*.md 2>/dev/null | sort | tail -1"
    frontmatter_check: "converged: false"

recommendation:
  workflow: null  # 不推荐工作流，仅提示
  info: "⚠️ 最新审计报告未收敛 ({checkpoint})"
  suggestion:
    - "查看报告: {report_path}"
    - "workflow-runner 会在对应阶段自动重新触发审计"
  non_blocking: true  # 建议性，不阻塞工作流
```

### 1.91 handoff_drift (2026-05-14 新增, H0 spec)

```yaml
id: handoff_drift
priority: 1.91
description: 检测到 handoff doc 写错位置 — .aria/handoff/*.md 存在 (canonical 是 docs/handoff/)

conditions:
  all:
    - handoff_misplaced_present: true   # snapshot.handoff.misplaced_files 非空

  detection:
    field: "snapshot.handoff.misplaced_files"
    expected: "[]"
    actual: "list of paths under .aria/handoff/*.md"

recommendation:
  workflow: migrate-handoff-drift
  steps:
    - "git mv .aria/handoff/*.md docs/handoff/"
    - "更新 docs/handoff/latest.md pointer 到迁移后的最新 doc"
    - "rmdir .aria/handoff/ (验证空 dir)"
    - "git commit -m 'chore(handoff): migrate misplaced files to canonical docs/handoff/'"
  info: "🔄 检测到 {misplaced_count} 个 handoff 文件写错位置 (.aria/handoff/, canonical 是 docs/handoff/)"
  suggestion:
    - "迁移漂移文件 (Layer 3 of 5-layer enforcement)"
    - "Convention SOT: standards/conventions/session-handoff.md"
  reason: |
    .aria/ 是机器状态 namespace (workflow-state.json / audit logs / cache 等),
    docs/ 是人类/AI 可读 prose namespace。handoff doc 是 prose,属于 docs/handoff/。
    H0 spec (Forgejo #92) ship 后,本 rule 是 5 层防漂移的 Layer 3 (推荐降级)。
  non_blocking: false       # 阻断性降级 (同 prd_draft_blocking 语义)
  degradation: true         # 降级推荐优先级, 常规 feature/fix 作为备选展示
```

**`non_blocking` 三态语义 (H1 follow-up, PR #46 audit Important-2 澄清)**:

`non_blocking` 不是布尔二态,是三态优先级 gate (与既有规则 prd_draft_blocking L335 / resume_in_progress_us L537 一致):

| 取值 | 语义 | 用例 |
|------|------|------|
| `non_blocking: true` | 建议性 — 仅提示,不改变常规推荐排序 | `audit_unconverged` (1.9), `multi_remote_drift` (1.35) |
| `non_blocking: false` (单独) | 强信号 — 该 rule 推荐优先, 但不显式抑制常规流 | `resume_in_progress_us` (1.88) |
| `non_blocking: false` + `degradation: true` | **阻断性降级** — 抑制常规 workflow 推荐, 该 rule 的修复 workflow 上位为主推荐, 用户须明确选择忽略才回到常规流 | `prd_draft_blocking` (5), **`handoff_drift` (1.91)** |
| `blocking: true` | 硬阻断 — 完全不出常规推荐, 必须先修复 | `custom_check_failed` (1.95) |

`handoff_drift` 取 `degradation` 态 (同 `prd_draft_blocking`): 不硬阻断 (用户当前仍可工作), 但 migrate-handoff-drift 上位为主推荐, 常规 feature/fix 降为备选 (因为漂移会让下次 session 漏读 handoff — H0 痛点)。

**Rationale (placement 1.91)**: 在 `audit_unconverged` (1.9 — 流程未收敛) 之后, `custom_check_failed` (1.95 — 硬阻断) 之前。审计未收敛是更紧迫的流程问题; handoff 漂移虽影响下次 session 但当前可继续工作。优先级数字大于 1.9 表示 "稍后处理 OK", 但应在常规工作流 (commit_only / quick_fix 等) **之前** surface 给 AI 看到。

**配合的其他防御层**:
- **Layer 1 (L1)**: PreToolUse hook `handoff-location-guard.sh` — 阻止新写入 `.aria/handoff/*.md`
- **Layer 2 (L2)**: scan.py `collectors/handoff.py` — 检测 misplaced_files (本 rule 的信号源)
- **Layer 3 (L3, 本 rule)**: state-scanner 推荐迁移工作流
- **Layer 4 (L4)**: `standards/conventions/session-handoff.md` — Convention SOT
- **Layer 5 (L5)**: `phase-d-closer` D.3 template hardcode 写 `docs/handoff/`

完整 spec: `openspec/changes/aria-ten-step-session-handoff-stage/`

---


---

## 自定义检查相关规则详情

### 1.95 custom_check_failed

```yaml
id: custom_check_failed
priority: 1.95
description: severity=error 的自定义健康检查失败，阻断推荐

conditions:
  all:
    - custom_checks_configured: true
    - custom_checks_has_error_failure: true  # 至少一个 severity=error 的检查 fail

  detection:
    config_check: ".aria/state-checks.yaml exists"
    result_scan: "custom_checks.results[].status == fail AND severity == error"

recommendation:
  workflow: null  # 阻断推荐，要求用户先修复
  info: "🔴 自定义检查失败 ({failed_check_names})"
  suggestion:
    - "修复建议: {fix_command}"
    - "跳过检查: 在 .aria/state-checks.yaml 中设置 enabled: false"
  blocking: true  # 阻断其他推荐
```

### 1.96 custom_check_warning

```yaml
id: custom_check_warning
priority: 1.96
description: severity=warning 的自定义健康检查失败，降级推荐

conditions:
  all:
    - custom_checks_configured: true
    - custom_checks_has_warning_failure: true  # 至少一个 severity=warning 的检查 fail
    - custom_checks_no_error_failure: true     # 无 severity=error 的失败 (否则由 1.95 处理)

  detection:
    config_check: ".aria/state-checks.yaml exists"
    result_scan: "custom_checks.results[].status == fail AND severity == warning"

recommendation:
  workflow: null  # 不推荐工作流，仅提示
  info: "⚠️ 自定义检查警告 ({warning_check_names})"
  suggestion:
    - "修复建议: {fix_command}"
  non_blocking: true  # 不阻塞，附加到推荐输出
```

### 1.97 submodule_drift

```yaml
id: submodule_drift
priority: 1.97
description: 子模块主仓库记录落后远程 (本地 behind remote), 建议更新后再做状态分析

conditions:
  any:
    # **关键修复 (Round 1 pre_merge audit M1)**:
    # 必须同时满足 tree_vs_remote==true AND behind_count > 0
    # 理由: behind_count==0 表示 "本地领先远程" (aria-orchestrator 场景), 此时发出
    # "git submodule update --remote" 是**破坏性**的, 会丢弃本地未推送的 commits.
    # 单独 tree_vs_remote==true 只说明 tree_commit != remote_commit, 方向未明.
    - sync_status.submodules[]:
        all:
          - drift.tree_vs_remote: true
          - drift.behind_count: "> 0"  # 必须真正落后, 不是领先
          - drift.behind_count: "!= null"

  detection:
    source: "Phase 1.12 sync_status.submodules[]"
    field_check: "drift.tree_vs_remote == true AND drift.behind_count > 0"
    prerequisite: "sync_status 存在且 has_remote: true"
    direction_guard: |
      drift.behind_count 是 "tree..remote" rev-list count,
      表示 "主仓库记录落后远程多少 commits".
      若 behind_count == 0 AND tree_vs_remote == true, 意味着本地领先远程
      (local commits 未推送), 此时**不触发**本规则, 应走 submodule_ahead_unpushed 规则
      (后续版本新增) 或仅作 info 级日志.

recommendation:
  workflow: null  # 不推荐工作流，仅降级提示
  info: "⚠️ 子模块 {path} 主仓库记录落后远程 {behind_count} commits, 建议: git submodule update --remote {path}"
  suggestion:
    - "git submodule update --remote {path}"  # 每个 drift 子模块一条
  non_blocking: true  # 降级，不阻断任何现有推荐

# === 补充规约 (Round 1 pre_merge audit M1 fix) ===
safety_note: |
  破坏性操作守卫: 本规则仅在 behind_count > 0 (真正落后) 时触发破坏性 hint.
  当 behind_count == 0 (本地领先远程) 时, 应由 state-scanner 在 output 中
  展示 "本地领先远程 N commits, 建议 git push" 的 info 级提示, 而非调用
  submodule_drift 规则. 此行为需在 references/sync-detection.md 中同步实现.
```

### 1.98 branch_behind_upstream

```yaml
id: branch_behind_upstream
priority: 1.98
description: 当前分支落后 upstream，建议先拉取再开发

conditions:
  all:
    - sync_status.current_branch.behind: ">= 5"
    - sync_status.current_branch.upstream_configured: true

  detection:
    source: "Phase 1.12 sync_status.current_branch"
    field_check: "behind >= 5"
    skip_conditions:
      - "behind == null"   # upstream 未配置或浅克隆，跳过
      - "reason != null"   # detached_head / no_upstream / shallow_clone，跳过

recommendation:
  workflow: null  # 不推荐工作流，仅降级提示
  info: "⚠️ 当前分支落后 {upstream} {behind} commits, 建议先 git pull"
  suggestion:
    - "git pull"
  non_blocking: true  # 降级，不阻断任何现有推荐
```

### 1.99 open_blocker_issues

```yaml
id: open_blocker_issues
priority: 1.99
description: 存在阻塞性 Issue，建议先 triage (v1.1.0+ 聚合所有 repo)

conditions:
  all:
    - issue_scan_enabled: true          # issue_scan.enabled == true (opt-in)
    - issue_status.source: "!= unavailable"  # 数据可用 (非离线/平台未知)
  any:
    - issue_status.items[].labels: contains "blocker"
    - issue_status.items[].labels: contains "critical"

  detection:
    source: "Phase 1.13 issue_status.items[] (aggregated flat view, v1.1.0+ 含所有 repos)"
    label_check: "any(labels contains 'blocker' OR labels contains 'critical')"
    prerequisite: "issue_status.source in [cache, live]"
    # v1.1.0+ 聚合语义:
    #   - scan_submodules=false: items 仅含主 repo, 行为与 v1.0 一致
    #   - scan_submodules=true: items 含所有 repos 的扁平化聚合, 每个 item 带 repo 字段
    # 任一 repo 的 blocker/critical 触发本规则 (不区分主 repo / submodule 的 severity)

recommendation:
  workflow: null  # 不推荐工作流，仅降级提示
  info: "⚠️ 存在 {N} 个阻塞性 Issue (blocker/critical), 跨 {M} 个 repo, 建议先 triage"
  context:
    blocker_issues:
      - "#{number} [{repo}] {title}"  # v1.1.0+: 每个匹配的 issue 一条, 含 repo 来源
  non_blocking: true  # 降级，不阻断任何现有推荐
```

---


---

## Multi-Terminal 协调规则 (v1.30.2 新增, Forgejo aria-plugin #56)

3 个规则消费 `tracks_multibranch` snapshot key (v1.22.0 已实装 Layer H + Layer L collector). 让 follower-container 跑 `/aria:state-scanner` 时不再需要 AI/user 自行判断 race 风险, scanner 直接 surface follower 状态 + 安全候选任务 + D.3 多 track handoff 指南。

**前提**: `coordination_fetch` + `handoff_multibranch` 数据可用 (v1.30.2 修了 #57 双 zero-day, sandbox 内现在能产生有效 `tracks_multibranch` 数据)。

### 1.51 multi_terminal_follower_detected

```yaml
id: multi_terminal_follower_detected
priority: 1.51
description: 本 container 在 multi-track 看板中无 active owned track, 是 follower 角色

conditions:
  all:
    - tracks_multibranch.exists: true
    - len(tracks_multibranch.tracks) >= 2
    - NOT exists track in tracks where (
        track.owner_container == current_container_id
        AND track.status in ["active", "in_progress"]
      )
    - exists track in tracks where (
        track.owner_container != current_container_id
        AND track.status in ["active", "in_progress"]
      )

  detection:
    snapshot_path: "tracks_multibranch.tracks[]"
    field_check: "current container has no active track; other container has ≥1 active"
    current_container_id_source: "ARIA_CONTAINER_ID env, OR git config user.email, OR hostname"

recommendation:
  workflow: standby-observer
  info: "🚦 本 container 是 follower — leader '{leader_owner}' 在 track '{track_id}' Phase {phase} active"
  context:
    leader_owner: "from track.owner_container"
    leader_track: "from track.track_id"
    leader_phase: "from track.phase"
  suggestion:
    - "不开 us-类 PR 启动 (避免与 leader 主线 race)"
    - "查看 leader 的 latest handoff (docs/handoff/latest.md → leader's pointer)"
  non_blocking: false  # follower 检测是强信号, 建议直接 ack
```

**Rationale (placement 1.51)**: 紧邻 `requirements_issues` (1.5) 之后, 在 architecture/state 检测之前 — multi-terminal 协调状态是当前 cycle 的 in-flight context, 应在所有"建议执行什么"类规则之前 surface。

### 1.52 follower_safe_tasks_suggested

```yaml
id: follower_safe_tasks_suggested
priority: 1.52
description: Rule 1.51 触发后, 推荐 follower 可安全做的 non-conflict 候选 task

conditions:
  all:
    - multi_terminal_follower_detected: true   # Rule 1.51 已触发

recommendation:
  workflow: null  # 信息提示, 不强制 workflow
  info: "📋 Follower-safe 候选任务 (避免撞 leader 主线):"
  display:
    - "**(a) Local hygiene** — `git branch --merged main` cleanup + cache cleanup"
    - "**(b) Cross-repo work** — aria-plugin / aria-standards / aria-orchestrator 的 issue/PR (跨 repo 不撞主仓 leader)"
    - "**(c) Carry-forward items** — openspec `[carry-forward|TODO|defer]` 注释 (Phase 1.6.1 已浮出)"
    - "**(d) Docs / audit** — handoff doc retrofit (legacy frontmatter), CLAUDE.md currency audit *(谨慎 — 若 leader 同时 touch CLAUDE.md 仍有 race)*"
  anti_suggestions:
    explicit_warn:
      - "❌ 启动新 OpenSpec change in active tracks scope"
      - "❌ 写 leader-track 的 phase-d-closer handoff (用 Rule 1.53 separate handoff)"
      - "❌ bump submodule pointer (leader 可能在 in-flight)"
  non_blocking: true  # 候选清单仅供参考
```

### 1.53 multi_terminal_handoff_dual

```yaml
id: multi_terminal_handoff_dual
priority: 1.53
description: D.3 阶段 + 多 track + leader pointer 仍在 latest.md → 推荐 follower 写 separate handoff

conditions:
  all:
    - phase_context == "D.3"  # 来自调用方 (phase-d-closer 触发 state-scanner)
    - tracks_multibranch.exists: true
    - len(tracks_multibranch.tracks) >= 2
    - exists track in tracks where (
        track.owner_container != current_container_id
        AND track.status == "active"
      )
    - handoff.latest_path != null
    # handoff.latest_path 指向 leader 的 doc (不是本 cycle 即将写的 doc)

recommendation:
  workflow: phase-d-closer-follower
  info: "✍️ D.3 多 track 模式 — 推荐写 separate follower handoff (slug 含 follower track-id)"
  guidance:
    - "新 handoff filename: `docs/handoff/{YYYY-MM-DD}-{follower-track-id}-{slug}.md`"
    - "**不要** overwrite `docs/handoff/latest.md` pointer 行 (保留 leader 主线 doc)"
    - "**仍要** prepend follower entry 到 latest.md History 表格 (per phase-d-closer SKILL.md §latest.md 维护 子步骤 1, v1.30.2 mechanical 拆分)"
    - "frontmatter 必填 5 字段, 标 `status: active`"
  non_blocking: false  # phase-d-closer 阶段强建议
```

### 1.54 concurrent_churn_detected (切口2, #133 concurrent-session-upm-safety)

```yaml
id: concurrent_churn_detected
priority: 1.54
description: >
  检测到跨 track collision 但 coordination 协调机制未启用 →
  advisory 提示用户可启用 coordination 以获得更强的并发协调。
  本规则是 #133 的"辅助·早发现"切口 (主解药是 standards
  concurrent-session-write-safety convention, 见 Rationale)。

conditions:
  all:
    - tracks_multibranch.collision.kind: "!= none"   # TASK-000 持久化字段 (cross_owner | self_multi_container)
    - coordination_enabled: false                    # config 读: state_scanner.coordination.enabled == false (默认)

  detection:
    source: "tracks_multibranch.collision (TASK-000 #133 additive 字段) + config-loader"
    field_check: "collision.kind != 'none' AND config coordination.enabled == false"
    config_check:
      source: "config-loader → state_scanner.coordination.enabled (config 键, 非 snapshot 字段)"
      default: false
      note: "enabled 是 .aria/config.json 配置键, scan.py 不采集到 snapshot; AI 在阶段 2 读 config 判定"

  # ── disjointness (与 phase1_gate 互斥, #133 AC-2) ──────────────────────
  # 两态在 coordination.enabled 上严格互斥, 绝不双触发:
  #   enabled == false → 本规则 (切口2 advisory, 仅提示)
  #   enabled == true  → cross_owner collision 由 phase1_gate 处理 (急切认领闸门),
  #                      本规则不触发 (conditions.coordination_enabled: false 已排除)
  disjointness:
    this_rule_iff: "coordination.enabled == false"
    phase1_gate_iff: "coordination.enabled == true (见 references/layer-l-integration.md)"
    invariant: "两者在 enabled 上互斥; 同一 scan 不会同时触发切口2 + phase1_gate"

recommendation:
  workflow: null   # 仅 advisory 降级提示, 不推荐工作流, 不阻塞
  info: >
    🔀 检测到并发 collision ({collision_kind}) 但 coordination 未启用 —
    多 session 可能撞同一共享区。建议遵循 concurrent-session-write-safety
    convention (主解药); 可选: 启用 coordination 协调机制获得 claim/reconcile。
  context:
    collision_kind: "from tracks_multibranch.collision.kind"
    collision_groups: "from tracks_multibranch.collision.groups (参与 collision 的 owner_container 成员)"
  suggestion:
    - "主解药: 遵循 standards/conventions/concurrent-session-write-safety.md (共享区 append-friendly / per-session 隔离 / followup sub-row)"
    - "可选一键启用 coordination (.aria/config.json):"
    - '  { "state_scanner": { "coordination": { "enabled": true } } }'
    - "判定不依赖\"谁\" (collision helper 已按 owner+container 归类, 同 owner/container 全相同→none 不触发)"
  non_blocking: true   # advisory 降级, 不阻断任何现有推荐, 不 auto-enable (advisory-over-hardlock)
```

**Rationale (placement 1.54)**: 紧随 1.51-1.53 multi-terminal cluster — 同属并发协调上下文。
**不 auto-enable** (DEC-20260519-001 advisory-over-hardlock): 仅提示用户可启用, 绝不自动改 config。
**与 convention 关系**: 本规则是 #133 的**辅助早发现**信号; **主解药**是 standards
`concurrent-session-write-safety.md` 的写法约定 (检测拦不住 write-time thrash, convention 结构改写才是 forcing function — 本 Spec audit C1)。

---

### 自定义检查状态检测

```yaml
custom_checks_detection:
  config_path: ".aria/state-checks.yaml"

  step_1:
    command: "[ -f .aria/state-checks.yaml ] && echo 'EXISTS' || echo 'NOT_EXISTS'"
    result: configured (boolean)

  step_2:
    condition: configured == true
    action: "parse YAML, validate schema version == '1'"
    on_parse_error: "configured = false, parse_error = message"

  step_3:
    condition: configured == true AND checks list non-empty
    action: "串行执行每个 enabled != false 的检查"
    execution:
      working_dir: project root
      timeout_per_check: timeout_seconds (default 15, max 60)
      timeout_total: 60s
      exit_code: 0 = pass, non-zero = fail
      stdout: first line as output
      on_timeout: status = timeout, severity treated as warning
      on_command_not_found: status = error, severity treated as warning

  aggregation:
    total: count(all checks)
    passed: count(status == pass)
    failed: count(status != pass)
    has_error_failure: any(status == fail AND severity == error)
    has_warning_failure: any(status == fail AND severity == warning)
```

---


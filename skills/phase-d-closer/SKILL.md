---
name: phase-d-closer
description: |
  十步循环 Phase D - 收尾阶段执行器，编排 D.1-D.3 步骤。

  使用场景："执行收尾阶段"、"Phase D"、"更新进度并归档 Spec"、"写 session handoff"
disable-model-invocation: false
user-invocable: true
allowed-tools: Read, Write, Glob, Grep, Bash, Task
---

# Phase D - 收尾阶段 (Closer)

> **版本**: 1.1.0 | **十步循环**: D.1-D.3 (D.3 added by H0 spec 2026-05-14)

## 快速开始

### 我应该使用这个 Skill 吗？

**使用场景**:
- 需要更新 UPM 进度状态
- 需要归档完成的 OpenSpec
- 功能开发完成后的收尾阶段
- 里程碑完成时的状态同步

**不使用场景**:
- 无 UPM 配置 → 跳过 D.1
- 无活跃 OpenSpec → 跳过 D.2
- 快速修复 (Level 1) → 通常跳过整个 Phase D

---

## 核心功能

| 步骤 | Skill | 职责 | 输出 |
|------|-------|------|------|
| D.1 | progress-updater | 进度更新 | upm_updated |
| D.2 | openspec-archive | Spec 归档 (自动修正 CLI bug) | spec_archived |
| D.3 | session-handoff (本 Skill 内嵌) | 写 session handoff doc 到 `docs/handoff/` | handoff_written |

---

## 执行流程

### 输入

```yaml
context:
  phase_cycle: "Phase4-Cycle9"
  module: "mobile"
  spec_id: "add-auth-feature"         # 来自 Phase A
  commit_sha: "abc1234"               # 来自 Phase C
  pr_url: "https://..."               # 来自 Phase C

config:
  skip_steps: []
  params:
    update_kpi: true
    archive_spec: true
```

### 步骤执行

```yaml
D.1 - 进度更新:
  skill: progress-updater
  skip_if:
    - no_upm: true                    # 模块无 UPM 配置
  action:
    - 读取当前 UPMv2-STATE
    - 更新 Cycle 进度
    - 写入新的状态
    # milestone_driven 模式: 若 C.2.6 已追加 sub-bullets，
    # D.1 只需 finalize (标记 COMPLETED + 关联 spec archive 路径)
    # 不需要重建历史，sub-bullets 已在过程中由 C.2.6 实时写入
  output:
    upm_updated: true
    new_state:
      cycle: 10
      completed_tasks: [TASK-001, ...]

D.post - post_closure 审计检查点 (新增):
  checkpoint: post_closure
  trigger: D.1 完成后、D.2 归档前
  condition: audit.enabled == true
             AND audit.checkpoints.post_closure != "off"
  限制: 仅使用 convergence 模式 + max_rounds=1 (侧重经验提取，非质量阻塞)

  步骤:
    1. 检查触发条件 (audit.enabled + checkpoint enabled)
    2. 如启用: 调用 audit-engine
       - checkpoint: "post_closure"
       - mode: "convergence"  # 强制 convergence，忽略全局 mode 配置
       - max_rounds: 1        # 强制单轮，忽略全局 max_rounds 配置
       - context: 本次交付的 UPM 路径 (经验积累上下文)
    3. 不阻塞: 无论 verdict 结果如何，均继续执行 D.2
       (代码已合并，此检查点仅做经验提取，不做质量门禁)

  on_fail: 记录审计报告但不阻塞，继续 D.2
  on_skip: 直接进入 D.2

D.2 - Spec 归档:
  skill: openspec-archive
  skip_if:
    - no_openspec: true               # 无活跃 Spec
    - spec_not_complete: true         # Spec 未完成
  action:
    - 验证所有任务完成
    - 移动 Spec 到 archive/
    - 更新 Spec 状态
  output:
    spec_archived: true
    archive_path: "openspec/archive/add-auth-feature/"

D.3 - Session handoff (新增 2026-05-14 by H0 spec):
  trigger_check: 任一满足即 prompt (用户可拒, 不强制)
  output_path_hardcoded: "docs/handoff/{YYYY-MM-DD}-{slug}.md"
  template: "aria/templates/session-handoff.md"
  forbidden_path: ".aria/handoff/"   # L1 hook 会拦, L5 此处也硬约束
  skip_if:
    - user_declines: true
  action:
    1. 评估触发条件 (见 §D.3 触发条件 below)
    2. 触发命中 → fill template (9-section skeleton) → write to docs/handoff/
    3. 更新 docs/handoff/latest.md pointer
    4. (optional) 提示 user commit handoff doc
  output:
    handoff_written: true
    handoff_path: "docs/handoff/2026-05-14-h0-cycle-done.md"
    latest_pointer_updated: true
```

### 输出

```yaml
success: true
steps_executed: [D.1, D.2, D.3]
steps_skipped: []
results:
  D.1:
    upm_updated: true
    new_cycle: 10
  D.2:
    spec_archived: true
    archive_path: "..."
  D.3:
    handoff_written: true
    handoff_path: "docs/handoff/2026-05-14-h0-cycle-done.md"
    latest_pointer_updated: true

context_for_next: null  # Phase D 是最后阶段
```

---

## 跳过规则

| 条件 | 跳过步骤 | 检测方法 |
|------|---------|----------|
| 无 UPM | D.1 | UPM 文档不存在 |
| 无 OpenSpec | D.2 | openspec/changes/ 为空 |
| Spec 未完成 | D.2 | tasks.md 有未完成项 |
| 触发条件未满足且 user prompt 拒绝 | D.3 | 见 §D.3 触发条件 |
| Level 1 quick fix (无 spec, 单 commit) | D.3 | 启发式 — Level 标记或 changes.complexity |

### 跳过逻辑

```yaml
skip_evaluation:
  D.1:
    - check: UPM file exists
      paths:
        - mobile/docs/project-planning/unified-progress-management.md
        - backend/project-planning/unified-progress-management.md
      skip_if: not exists
      reason: "模块无 UPM 配置"

  D.2:
    - check: active OpenSpec
      command: "ls openspec/changes/"
      skip_if: empty
      reason: "无活跃 OpenSpec"

    - check: tasks completion
      file: "openspec/changes/{spec_id}/tasks.md"
      skip_if: has uncompleted tasks
      reason: "Spec 任务未全部完成"
```

---

## 输出格式

```
╔══════════════════════════════════════════════════════════════╗
║              PHASE D - CLOSURE                               ║
╚══════════════════════════════════════════════════════════════╝

📋 执行计划
───────────────────────────────────────────────────────────────
  D.1 progress-updater   → 更新 UPM 进度
  D.2 openspec:archive   → 归档 Spec

🚀 执行中...
───────────────────────────────────────────────────────────────
  ✅ D.1 完成 → UPM 已更新
     Module: mobile
     Cycle: 9 → 10

  ✅ D.2 完成 → Spec 已归档
     Spec: add-auth-feature
     Archive: openspec/archive/add-auth-feature/

🎉 工作流完成
───────────────────────────────────────────────────────────────
  状态: 所有步骤成功
  总耗时: 45s
```

---

## 使用示例

### 示例 1: 完整收尾

```yaml
输入:
  context:
    module: "mobile"
    spec_id: "add-auth-feature"

执行:
  D.1: 更新 UPM → Cycle 10
  D.2: 归档 Spec → archive/

输出:
  upm_updated: true
  spec_archived: true
```

### 示例 2: 仅更新进度

```yaml
输入:
  context:
    spec_id: null  # 无关联 Spec

执行:
  D.1: 更新 UPM
  D.2: 跳过 (无 Spec)

输出:
  steps_skipped: [D.2]
  upm_updated: true
```

### 示例 3: 全部跳过

```yaml
输入:
  context:
    module: "shared"  # 无 UPM
    spec_id: null     # 无 Spec

执行:
  D.1: 跳过 (无 UPM)
  D.2: 跳过 (无 Spec)

输出:
  steps_skipped: [D.1, D.2]
  reason: "收尾阶段无需执行"
```

---

## 进度更新内容

### D.1 更新模式

D.1 支持两种更新模式，通过 `.aria/config.json` 中的 `upm.milestone_driven` 控制:

| 维度 | 默认模式 (single-pass) | Milestone-driven 模式 |
|------|----------------------|----------------------|
| 配置 | `upm.milestone_driven: false` | `upm.milestone_driven: true` |
| C.2.6 行为 | 不执行 | 每次 PR 合并后追加 sub-bullet + 状态升级为 `[~]` |
| D.1 工作量 | 完整 single-pass 更新所有 Story | 仅 finalize: 将 `[~]` → `[x]` + 关联 spec archive 路径 |
| 适用场景 | 单 PR 功能 / 快速迭代 | multi-PR cycle (如 schema expand-migrate-contract 3 PR) |
| 中间透明度 | 低 (1-2 周期间 UPM 停留在 `[ ]`) | 高 (每次 PR 合并即可见进度) |
| 向后兼容 | 原有行为不变 | opt-in，不影响已有配置 |

**Milestone-driven 模式下 D.1 的 finalize 职责**:
1. 将所有 `[~]` Story 标记升级为 `[x] COMPLETED`
2. 在 Story 的最后一条 sub-bullet 后追加 `archive: openspec/archive/{spec_id}/`
3. 更新 UPMv2-STATE Header (`lastUpdateAt`, `stateToken`, `completedTasks`)
4. 不重建历史记录 — sub-bullets 已由 C.2.6 在过程中实时写入

**相关文档**: 参见 [phase-c-integrator C.2.6](../phase-c-integrator/SKILL.md) — 修复 Forgejo #22 (2026-04-23)

### UPMv2-STATE 更新

```yaml
更新字段:
  - cycleNumber: +1 或保持
  - lastUpdateAt: 当前时间
  - stateToken: 重新计算
  - completedTasks: 添加已完成任务
  - kpiSnapshot: 更新覆盖率等指标
```

### Spec 归档

```yaml
归档操作:
  1. 验证 tasks.md 所有任务标记 [x]
  2. 更新 proposal.md 状态为 Complete
  3. 移动目录: changes/{id}/ → archive/{id}/
  4. 记录归档时间和提交信息
```

---

## 错误处理

| 错误 | 原因 | 处理 |
|------|------|------|
| UPM 更新失败 | 并发冲突 | 重新读取并合并 |
| Spec 归档失败 | 任务未完成 | 列出未完成任务 |
| 状态写入失败 | 文件权限 | 提示检查权限 |

### 并发冲突处理

```yaml
on_upm_conflict:
  action: retry
  max_retries: 3
  strategy:
    1. 重新读取 UPMv2-STATE
    2. 合并变更
    3. 重新计算 stateToken
    4. 再次尝试写入
```

---

## §D.3 详细说明 (新增 2026-05-14, H0 spec)

### 目的

session 结束时**标准化引导**写 handoff doc, 让下一个 session AI/人 zero-context 可恢复优先级 + carry-forward。

历史问题: handoff 写不写、写哪个 dir、什么格式各项目自发演进, 导致跨 session 上下文丢失 (4 起 dogfood 实证, 见 H0 spec)。

### 触发条件 (任一满足即 prompt user)

按 fallback 优先级评估 (F2 audit fix per backend-M1 — 信号缺失也能 prompt):

```yaml
trigger_level_1_primary:
  signal: workflow-state.json::session.started_at
  check: now - started_at > 4h
  fallback_if_missing: go to level 2

trigger_level_2_cycles_shipped:
  signal: git log since last `docs/handoff/*.md` mtime
  check: count distinct openspec/archive/{date}-*/ entries created > N >= 2
  command_hint_linux: |
    last_handoff_mtime=$(stat -c '%Y' $(ls -t docs/handoff/*.md | head -1))
  command_hint_macos: |
    last_handoff_mtime=$(stat -f '%m' $(ls -t docs/handoff/*.md | head -1))
  command_hint_portable: |
    # Python alternative (cross-platform, recommended for AI implementations):
    last_handoff_mtime=$(python3 -c "import os, glob; files=sorted(glob.glob('docs/handoff/*.md'), key=os.path.getmtime, reverse=True); print(int(os.path.getmtime(files[0])) if files else 0)")
  count_command: |
    git log --since="@$last_handoff_mtime" --diff-filter=A --name-only -- "openspec/archive/*/proposal.md" | sort -u | wc -l
  fallback_if_missing: go to level 3

trigger_level_3_phase_count:
  signal: count distinct "Phase {A,B,C,D}" markers in commit subjects since last handoff
  check: distinct phase count >= 2
  command_hint: |
    # uses $last_handoff_mtime computed in level 2 (portable)
    git log --since="@$last_handoff_mtime" --format="%s" | grep -oE "Phase [ABCD]" | sort -u | wc -l
  fallback_if_missing: go to level 4

trigger_level_4_user_prompt:
  prompt: |
    "本 session 是否符合 D.3 触发条件之一?
       (a) 跨度 > 4h
       (b) ship >= 2 cycles
       (c) 跨 >= 2 phases
     默认 yes (D.2 archive 已成功通常意味本 session 完整闭环)。
     选择: y / n / 详情 (查看 fallback 信号原始值)"
  default_if_silent: "yes" (D.2 archive 成功且 user 在场)
```

### 输出路径硬编码 (L5 enforcement, 不可修改)

```
docs/handoff/{YYYY-MM-DD}-{slug}.md

slug 规则 (优先级):
  1. user 提供 (如 "h0-cycle-done")
  2. cycle change_id 后缀 (如 "aria-ten-step-session-handoff-stage" → "h0-stage")
  3. fallback: "session-handoff"

同日重名 fallback:
  docs/handoff/{YYYY-MM-DD}-{HHMM}-{slug}.md
```

**绝对禁止**: 写 `.aria/handoff/*` (L1 PreToolUse hook 会拦; L4 convention SOT 显式 forbidden)。

### 模板使用

读 `aria/templates/session-handoff.md` (9-section skeleton), 按 variable 字典 substitute:

| Variable | 来源 |
|----------|------|
| `{project}` | `.aria/config.json::project.name` 或 git remote 推断 |
| `{date}` | `date -u +%Y-%m-%d` |
| `{cycle_name}` | spec change_id 或 user 提供 |
| `{session_duration}` | level 1/2/3 信号计算的实测值 |
| `{shipped_cycles}` | level 2 信号 count |
| `{memory_entries_count}` | `ls ~/.claude/projects/*/memory/*.md` since last handoff |
| `{next_session_entry}` | "/aria:state-scanner" (Aria projects); 其他项目按 `.aria/config.json::next_session_command` |
| `{start_date}` | 上次 handoff 的 last_modified_iso (from snapshot.handoff) |

### latest.md pointer 更新

新 handoff 写完后, 自动更新 `docs/handoff/latest.md`:
- Latest 字段指向新 doc 的相对路径
- "历史 handoff" 表格首行 prepend 新条目 (Status: **Active (Latest)**)
- 前一 Latest 改为 "Active (parallel predecessor)" 或 "superseded" (由 user 判断)

### Forbidden patterns (L5 hardcode)

- ❌ 写到 `.aria/handoff/` (L1 hook 会拦)
- ❌ 文件名含空格或特殊字符 (用 hyphen)
- ❌ 跳过 latest.md 更新 (导致 stale pointer)
- ❌ 用 datetime.now() 计算 — 用 UTC `date -u`

---

## 与其他 Phase 的关系

```
phase-c-integrator
    │
    │ context:
    │   - commit_sha
    │   - pr_url
    ▼
phase-d-closer (本 Skill)
    │
    ├── D.1 progress-updater (UPM 更新)
    ├── D.post audit checkpoint (经验提取, convergence 1 round)
    ├── D.2 openspec-archive (Spec 归档)
    └── D.3 session-handoff (写 handoff to docs/handoff/, latest.md update)
    │
    │ 工作流结束 → 下次 session: /aria:state-scanner 自动 surface handoff
    ▼
  (完成)
```

---

## 相关文档

- [progress-updater](../progress-updater/SKILL.md) - D.1 进度更新
- [openspec:archive](../../commands/openspec/archive.md) - D.2 Spec 归档
- [session-handoff template](../../templates/session-handoff.md) - D.3 9-section skeleton (H0 spec 2026-05-14)
- [session-handoff convention](../../../standards/conventions/session-handoff.md) - L4 SOT (added by H0)
- [phase-c-integrator](../phase-c-integrator/SKILL.md) - 上一阶段
- [UPM 规范](../../../standards/core/upm/unified-progress-management-spec.md)
- [state-scanner Phase 1.15 handoff awareness](../state-scanner/SKILL.md) - D.3 输出在下次 session start 自动 surface

---

**最后更新**: 2026-05-14 (H0 spec — D.3 session-handoff step added)
**Skill版本**: 1.1.0

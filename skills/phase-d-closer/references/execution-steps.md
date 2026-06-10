# Phase D Execution Steps — Detailed Reference

> 完整 D.1/D.post/D.2/D.3 step-by-step + 输入/输出 schema. 从 SKILL.md §执行流程 提取 (iter-3, 2026-05-28)。

## 输入

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

## 步骤执行

```yaml
D.1 - 进度更新:
  skill: progress-updater
  skip_if:
    - no_upm: true                    # 模块无 UPM 配置
  action:
    - 读取当前 UPMv2-STATE
    - 更新 Cycle 进度
    - 写入新的状态
    # milestone_driven 模式: 若 C.2.6 已追加 sub-bullets,
    # D.1 只需 finalize (标记 COMPLETED + 关联 spec archive 路径)
    # 不需要重建历史, sub-bullets 已在过程中由 C.2.6 实时写入
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
  限制: 仅使用 convergence 模式 + max_rounds=1 (侧重经验提取, 非质量阻塞)

  步骤:
    1. 检查触发条件 (audit.enabled + checkpoint enabled)
    2. 如启用: 调用 audit-engine
       - checkpoint: "post_closure"
       - mode: "convergence"  # 强制 convergence, 忽略全局 mode 配置
       - max_rounds: 1        # 强制单轮, 忽略全局 max_rounds 配置
       - context: 本次交付的 UPM 路径 (经验积累上下文)
    3. 不阻塞: 无论 verdict 结果如何, 均继续执行 D.2
       (代码已合并, 此检查点仅做经验提取, 不做质量门禁)

  on_fail: 记录审计报告但不阻塞, 继续 D.2
  on_skip: 直接进入 D.2

D.2 - Spec 归档:
  skill: openspec-archive
  skip_if:  # 三路 (#134 v1.42.0+): 无活跃→skip / incomplete→skip 不归档 / complete→进归档
    - no_openspec: true               # 无活跃 Spec
    - spec_not_complete: true         # 完成判定 = Bash 调单一可执行 SOT (与 openspec-archive Step 1 gate 同脚本同 verdict):
                                      #   python3 "${CLAUDE_PLUGIN_ROOT:-aria}/skills/state-scanner/scripts/lib/spec_complete.py" "openspec/changes/{spec_id}"
                                      #   exit != 0 → skip 不归档 (Level 2 无 tasks.md 由脚本走 Status 归一化分支, 不 vacuously 放行)
  action:
    - 完成 gate 通过后移动 Spec 到 archive/ (gate 细节见 openspec-archive SKILL.md Step 1)
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
    1. 评估触发条件 (见 [handoff-mechanics.md](./handoff-mechanics.md))
    2. 触发命中 → fill template (9-section skeleton) → write to docs/handoff/
    3. 更新 docs/handoff/latest.md pointer (mechanical, 子步骤 1+2 详见 handoff-mechanics.md)
    4. (optional) 提示 user commit handoff doc
  output:
    handoff_written: true
    handoff_path: "docs/handoff/2026-05-14-h0-cycle-done.md"
    latest_pointer_updated: true
```

## 输出

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

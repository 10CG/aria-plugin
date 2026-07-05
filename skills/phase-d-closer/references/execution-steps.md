# Phase D Execution Steps — Detailed Reference

> 完整 D.1/D.post/D.2/D.3 step-by-step + 输入/输出 schema. 从 SKILL.md §执行流程 提取 (iter-3, 2026-05-28)。
> **D.2 更新 (2026-07-05, #95)**: gate 命令改走 `spec_complete.py --gate` tri-state 契约, 新增
> `verdict=block` BLOCK 分支 (与 legacy `complete=false` skip 分支并列, 语义不同); D auto-issue 单一
> owner 委托 openspec-archive 自身处理, phase-d-closer 不重复建 issue。

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
  skip_if:  # 四路 (#134 v1.42.0+ 二路 ⊗ #95 tri-state verdict 扩展):
            # 无活跃→skip / complete=false 且 verdict≠block→skip 不归档(legacy) /
            # verdict=block→**BLOCK**(非仅 skip, 见下) / 其余(complete=true ∧ verdict∈{pass,warn})→进归档
    - no_openspec: true               # 无活跃 Spec
    - spec_not_complete: true         # legacy #134 分支不变: complete=false 且 verdict≠block → skip
    - spec_c_block: true              # #95 新增分支: verdict=block → **BLOCK** (与 spec_not_complete 语义
                                      # 不同 — 这是高置信死代码判定, 报告须显式区分, 不与"未完成"混为一谈)
  gate_command: |
    # Bash 调单一可执行 SOT (与 openspec-archive Step 1 gate 同脚本同 verdict, AC-1 一致性不变量)
    python3 "${CLAUDE_PLUGIN_ROOT:-aria}/skills/state-scanner/scripts/lib/spec_complete.py" \
      --gate "openspec/changes/{spec_id}"
  gate_read: "stdout JSON 全字段 (complete/complete_reason/verdict/blocking_reasons/warnings/unverified_claims/d_payload/soft_errors) — 解析 verdict 字段做路由, 不能只看 exit code (0=pass|warn 二合一, 无法区分)"
  routing:
    "verdict == block": "**BLOCK** (#95 PP-R1 cr fix, 非仅委托) — 回显 blocking_reasons; 不自动调用 openspec-archive, 不自动传 --archive-design-only 绕过 (owner/AI 需另行显式直接调用 openspec-archive skill 强制豁免)"
    "complete == false 且 verdict != block": "skip 不归档 (legacy #134 行为不变) — 回显 complete_reason"
    "complete == true 且 verdict in (pass, warn)": "进 openspec-archive 归档 (调用该 skill, 内部 Step 1-7 含 warn frontmatter 写入 + D auto-issue 单一 owner 处理)"
  action:
    - 完成 gate 通过后移动 Spec 到 archive/ (gate 细节见 openspec-archive SKILL.md Step 1)
    - 更新 Spec 状态
    - "verdict=warn 或归档产出 d_payload 时: **全部委托** openspec-archive 自身 Step 2 (frontmatter) + Step 7 (D auto-issue) 处理; phase-d-closer 不重复解读 unverified_claims / 不自建 tracker issue (单一 owner, #95 §2)"
  output:
    spec_archived: true
    archive_path: "openspec/archive/add-auth-feature/"
    # #95 新增 (verdict=block 时 spec_archived=false 且 blocked=true; 干净归档时以下字段省略):
    gate_verdict: "pass"|"warn"|"block"
    blocked: false
    blocking_reasons: []

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
    2b. 写后 frontmatter 自校验 (#137 v1.43.0+, warn-then-fix 非硬 abort):
        head -8 <handoff> | grep -cE '^(track-id|owner-container|phase|status|updated-at):'
        须 ==5; 不足 → 按模板派生规则补齐后重验。不得带缺字段 handoff 进子步 3。
        (口径注: 勿在 frontmatter 内插注释行, 可能把字段推出 head -8 窗口致误报)
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
    gate_verdict: "pass"     # #95: "pass"|"warn"|"block"; 干净归档时省略 blocked/blocking_reasons
  D.3:
    handoff_written: true
    handoff_path: "docs/handoff/2026-05-14-h0-cycle-done.md"
    latest_pointer_updated: true

context_for_next: null  # Phase D 是最后阶段
```

### D.2 verdict=block 时的输出变体 (#95)

```yaml
success: true                 # D.1/D.3 仍可正常完成, Phase D 整体不因 D.2 BLOCK 而失败
steps_executed: [D.1, D.3]
steps_skipped: []
steps_blocked: [D.2]          # 与 steps_skipped 区分: BLOCK 是需要 owner 关注的判定, 不是常规跳过
results:
  D.1:
    upm_updated: true
    new_cycle: 10
  D.2:
    spec_archived: false
    blocked: true
    gate_verdict: "block"
    blocking_reasons:
      - "symbol 'phase1_gate' (claim: '集成 state-scanner') has zero production semantic reference (dead-code-on-arrival)"
    guidance: "补齐集成后重试; 或 owner/AI 直接调用 openspec-archive skill 并显式带 --archive-design-only + reason 强制归档"
  D.3:
    handoff_written: true
    handoff_path: "docs/handoff/2026-07-05-blocked-archive.md"
    latest_pointer_updated: true

context_for_next: null
```

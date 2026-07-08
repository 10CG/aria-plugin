---
name: phase-d-closer
description: |
  十步循环 Phase D - 周期收尾阶段执行器，编排 D.1-D.3 步骤 (更新 cycle 进度 + 归档 Spec + 周期 handoff)。

  使用场景："Phase D"、"周期收尾"、"收尾阶段"、"更新进度并归档 Spec"、"更新 cycle 进度"

  不适用 (用 session-closer): "对话收尾" / "会话收尾" / "写交接" / "session closeout"
  —— 那是会话维度收尾, 非开发周期收尾。
disable-model-invocation: false
user-invocable: true
allowed-tools: Read, Write, Glob, Grep, Bash, Task
---

# Phase D - 收尾阶段 (Closer)

> **版本**: 1.3.0 | **十步循环**: D.1-D.4 (D.3 added by H0 2026-05-14; D.4 estimator capture by #18 2026-05-30; D.2 gate 扩展 tri-state verdict + BLOCK by #95 2026-07-05)

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
| D.2 | openspec-archive | Spec 归档 (自动修正 CLI bug; **#95 完成度 + C 分级证据闸 tri-state verdict, verdict=block 时本步 BLOCK**) | spec_archived |
| D.3 | session-handoff (本 Skill 内嵌) | 写 session handoff doc 到 `docs/handoff/` | handoff_written |
| D.4 | ai-native-estimator (capture) | 采集本 cycle token 工作量 (advisory, 非阻塞, #18 v1) | estimator_captured |

---

## 执行流程

4 步: **D.1 进度更新** (progress-updater skill, single-pass / milestone-driven 双模) → **D.post post_closure audit** (可选, audit.enabled+checkpoint enabled 时触发 convergence/max_rounds=1, 经验提取非阻塞) → **D.2 Spec 归档** (openspec-archive skill) → **D.3 Session handoff** (4-level fallback 触发, 路径硬编码 `docs/handoff/`)。

**完整 step-by-step (输入 context schema + D.1/D.post/D.2/D.3 详细 action + 输出)**: 见 [references/execution-steps.md](./references/execution-steps.md)。

## 跳过规则

| 条件 | 跳过步骤 | 检测方法 |
|------|---------|----------|
| 无 UPM | D.1 | UPM 文档不存在 |
| 无 OpenSpec | D.2 | openspec/changes/ 为空 |
| Spec 未完成 (legacy) | D.2 (skip) | `spec_complete.py --gate` `complete=false` 且 `verdict≠block` (Level 2 无 tasks.md 走 Status 归一化) |
| **C-block 死代码判定 (#95)** | D.2 (**BLOCK**, 非仅 skip) | `spec_complete.py --gate` `verdict=block` (可与 `complete=true` 共存 — 点名符号零生产语义引用) |
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

  D.2:  # 四路 (#134 v1.42.0+ 二路 ⊗ #95 tri-state verdict 扩展): 无活跃→skip /
        # complete=false 且 verdict≠block→skip 不归档(legacy) / verdict=block→**BLOCK**(非仅 skip) / 其余→进归档
    - check: active OpenSpec
      command: "ls openspec/changes/"
      skip_if: empty
      reason: "无活跃 OpenSpec"

    - check: spec completeness + C 分级证据闸 tri-state verdict  # #95 TG-3: Bash 调单一可执行 SOT,
      # 与 openspec-archive Step 1 gate 同一脚本同一 verdict (AC-1 多入口一致性不变量)
      command: 'python3 "${CLAUDE_PLUGIN_ROOT:-aria}/skills/state-scanner/scripts/lib/spec_complete.py" --gate "openspec/changes/{spec_id}"'
      读取: stdout JSON 全字段 (complete/complete_reason/verdict/blocking_reasons/warnings/unverified_claims/d_payload/soft_errors);
        本 D.2 preview 检查 **不能只看 exit code** (0=pass|warn 二合一, 无法区分), 须解析 `verdict` 字段做路由
      verdict_routing:
        "verdict == block":
          结果: "**BLOCK** (#95 PP-R1 cr fix, 非仅委托 openspec-archive — phase-d-closer 自身在 D.2
                 报告 BLOCKED, 不静默跳过)"
          行为: 回显 blocking_reasons; **不**自动传 `--archive-design-only` 绕过 (phase-d-closer 不代
                owner/AI 做豁免决定) — 若需强制归档, 由 owner/AI 显式另行直接调用 openspec-archive
                skill 并带 `--archive-design-only` + reason
          不调用: 本轮不进入 openspec-archive (openspec-archive 的 Step 7 D auto-issue 也就不会跑到 —
                  这是刻意的: BLOCK 场景下归档尚未发生, 没有"归档残留"可言, 待 owner 后续显式强制
                  归档时, 走 openspec-archive 自己的 Step 1 escape-hatch 分支, Step 7 会在那时补建 issue)
        "complete == false ∧ verdict != block":
          结果: "skip 不归档 (legacy #134 行为不变)"
          行为: 回显 complete_reason
        "complete == true ∧ verdict in (pass, warn)":
          结果: "进 openspec-archive 归档"
          行为: "verdict=warn 时 frontmatter 写入 + D auto-issue 全部由 openspec-archive 自身
                 Step 2/Step 7 处理 (单一 owner, 见下), phase-d-closer 不重复解读 warnings"
      on_complete: "verdict∈{pass,warn} 且 complete=true → 调用 openspec-archive skill 归档"
      单一 owner 委托 (#95 §2 "单一 owner"): 若 openspec-archive 归档后产出 d_payload
        (deferred 未完成项 / unverified_claims), issue 创建**完全委托** openspec-archive 自身
        Step 7 完成 — phase-d-closer **不**各自再建一份 tracker issue (防双入口重复开 issue)。
        phase-d-closer 的 D.2 只负责"要不要调 openspec-archive"这一层路由决策, 不掺和
        "归档内部如何处理 deferred/unverified" 这一层实现细节。
```

> **动态子检查 (runtime_probe, #95 follow-up A)**: 上表 verdict 三态判定现覆盖**声明式可选
> 动态子检查** —— spec 若在 `proposal.md` frontmatter 声明 `runtime_probe:` (partition/symbol/
> max_age_days/enabled_when), gate 会额外核验"该符号近期是否真被生产入口调用过", 结果按
> fail-toward-warn 折入同一 `verdict` (绝不因此升级到 block; 已是 block 的不受影响)。声明是
> **完全可选**的 —— 无声明 spec 的 D.2 行为逐字节不变 (SC-1)。phase-d-closer 本身不解析该
> 声明, 只按上表既有 verdict 路由消费折入后的结果; 声明 schema + 解析约束见
> [runtime-probe-declaration.md](../state-scanner/references/runtime-probe-declaration.md),
> 折入裁决与归档写入契约见 [openspec-archive SKILL.md §Step
> 1-2](../openspec-archive/SKILL.md) (本节不复制契约细节)。

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

> 上图为 D.2 放行 (verdict∈{pass,warn}) 的正常路径展示。**verdict=block (#95) 时** D.2 报告
> BLOCKED 而非"完成", D.1/D.3 仍可正常执行 — 完整 BLOCK 输出变体见
> [references/execution-steps.md §D.2 verdict=block 时的输出变体](./references/execution-steps.md)。

---

## 使用示例

3 个典型场景: (1) 完整收尾 (D.1+D.2 都跑) / (2) 仅更新进度 (D.2 跳过, 无关联 Spec) / (3) 全部跳过 (D.1+D.2 都跳过, 无 UPM 无 Spec)。

**完整 YAML 示例 (输入 context / 执行过程 / 输出 schema)**: 见 [references/usage-examples.md](./references/usage-examples.md)。

## 进度更新内容

D.1 支持 **single-pass** (默认, 完整 update) 和 **milestone-driven** (multi-PR cycle, C.2.6 增量追加 + D.1 finalize) 两种模式。UPMv2-STATE 5 字段更新 (cycleNumber/lastUpdateAt/stateToken/completedTasks/kpiSnapshot)。Spec 归档 4-step (验证 [x] / 更新 status / 移动 dir / 记录 commit info)。

**完整模式对比表 + Milestone-driven 4-step finalize 职责 + UPMv2-STATE 字段定义 + Spec 归档操作**: 见 [references/progress-update-details.md](./references/progress-update-details.md)。

## 错误处理

| 错误 | 原因 | 处理 |
|------|------|------|
| UPM 更新失败 | 并发冲突 | 重新读取并合并 |
| Spec 归档失败 (skip, legacy) | 任务未完成 (`complete=false`) | 列出未完成任务 (回显 `complete_reason`) |
| **Spec 归档 BLOCK (#95)** | `verdict=block` — 点名符号零生产语义引用 (可与 `complete=true` 共存) | 回显 `blocking_reasons`; 不自动豁免 — 需 owner/AI 直接调用 `openspec-archive` skill 并显式带 `--archive-design-only` + reason 才能强制归档 |
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

## §D.3 Session Handoff (2026-05-14, H0 spec)

session 结束时引导写 handoff doc, 让下一个 session zero-context 可恢复优先级 + carry-forward。

**触发**: 4-level fallback (workflow-state session_age > 4h / cycles_shipped ≥ 2 / phase_count ≥ 2 / user prompt)。
**输出路径**: `docs/handoff/{YYYY-MM-DD}-{slug}.md` (L5 hardcode, 绝对禁止 `.aria/handoff/*`)。
**模板**: `aria/templates/session-handoff.md` (9-section skeleton) + variable substitution。
**latest.md 维护**: 2 个 mechanical 子步骤 — 子步骤 1 History prepend (always) + 子步骤 2 Pointer 更新 (conditional by `snapshot.tracks_multibranch` multi-track detection)。

**完整说明 (触发条件 4 级 fallback / 输出路径 slug 规则 / 模板 variable 字典 / latest.md 2 子步骤 + 3-row decision table + edge cases / Forbidden patterns)**: 见 [references/handoff-mechanics.md](./references/handoff-mechanics.md)。

---

## §D.4 Estimator Capture (2026-05-30, #18 v1)

收尾**末位**子步 (D.3 之后), 自动采集本 cycle 的 token 工作量到 estimator 历史 (advisory, **非阻塞**)。

**触发**: `ai_native_estimator.enabled != false` (config-loader)。

**执行**:
```bash
EST="${CLAUDE_PLUGIN_ROOT:-aria}/skills/ai-native-estimator/scripts/estimator.py"
python3 "$EST" --project-root . capture \
  --spec-slug <本 cycle Spec slug> \
  --spec-level <读 openspec/changes/{spec}/proposal.md frontmatter `Level` 行; 无 Spec 省略> \
  --n-tasks <detailed-tasks.yaml task 数; 无省略>
```

- **幂等**: 无新 turn → `{"skipped": true}` (watermark 空区间, 安全可重跑)
- **非阻塞**: 任何失败 (无 transcript / config disabled) → skip + warn, **不影响收尾闭环**
- cycle_id 由 estimator 从 transcript range 末 uuid 生成 (phase-d 不传时刻)

**完整数据模型 + 查询**: 见 [ai-native-estimator](../ai-native-estimator/SKILL.md)。

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
    ├── D.2 openspec-archive (Spec 归档; #95 tri-state verdict gate — verdict=block 时本步自身 BLOCK,
    │       不调用 openspec-archive; 放行时调用 openspec-archive, 委托其内部 Step 7 处理 D auto-issue
    │       (单一 owner, phase-d-closer 自身不建 issue))
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
- [openspec-archive](../openspec-archive/SKILL.md) - D.2 委托的归档 Skill (Step 1 C-gate + Step 7 D auto-issue, #95)
- **#95 Spec**: `openspec/changes/aria-archive-gate-runtime-reality/proposal.md` (主仓, tri-state verdict 契约设计 SOT)

---

**最后更新**: 2026-07-05 (#95 — D.2 gate 扩展 tri-state verdict + verdict=block BLOCK)
**Skill版本**: 1.3.0

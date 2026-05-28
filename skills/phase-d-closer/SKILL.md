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

4 步: **D.1 进度更新** (progress-updater skill, single-pass / milestone-driven 双模) → **D.post post_closure audit** (可选, audit.enabled+checkpoint enabled 时触发 convergence/max_rounds=1, 经验提取非阻塞) → **D.2 Spec 归档** (openspec-archive skill) → **D.3 Session handoff** (4-level fallback 触发, 路径硬编码 `docs/handoff/`)。

**完整 step-by-step (输入 context schema + D.1/D.post/D.2/D.3 详细 action + 输出)**: 见 [references/execution-steps.md](./references/execution-steps.md)。

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

3 个典型场景: (1) 完整收尾 (D.1+D.2 都跑) / (2) 仅更新进度 (D.2 跳过, 无关联 Spec) / (3) 全部跳过 (D.1+D.2 都跳过, 无 UPM 无 Spec)。

**完整 YAML 示例 (输入 context / 执行过程 / 输出 schema)**: 见 [references/usage-examples.md](./references/usage-examples.md)。

## 进度更新内容

D.1 支持 **single-pass** (默认, 完整 update) 和 **milestone-driven** (multi-PR cycle, C.2.6 增量追加 + D.1 finalize) 两种模式。UPMv2-STATE 5 字段更新 (cycleNumber/lastUpdateAt/stateToken/completedTasks/kpiSnapshot)。Spec 归档 4-step (验证 [x] / 更新 status / 移动 dir / 记录 commit info)。

**完整模式对比表 + Milestone-driven 4-step finalize 职责 + UPMv2-STATE 字段定义 + Spec 归档操作**: 见 [references/progress-update-details.md](./references/progress-update-details.md)。

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

## §D.3 Session Handoff (2026-05-14, H0 spec)

session 结束时引导写 handoff doc, 让下一个 session zero-context 可恢复优先级 + carry-forward。

**触发**: 4-level fallback (workflow-state session_age > 4h / cycles_shipped ≥ 2 / phase_count ≥ 2 / user prompt)。
**输出路径**: `docs/handoff/{YYYY-MM-DD}-{slug}.md` (L5 hardcode, 绝对禁止 `.aria/handoff/*`)。
**模板**: `aria/templates/session-handoff.md` (9-section skeleton) + variable substitution。
**latest.md 维护**: 2 个 mechanical 子步骤 — 子步骤 1 History prepend (always) + 子步骤 2 Pointer 更新 (conditional by `snapshot.tracks_multibranch` multi-track detection)。

**完整说明 (触发条件 4 级 fallback / 输出路径 slug 规则 / 模板 variable 字典 / latest.md 2 子步骤 + 3-row decision table + edge cases / Forbidden patterns)**: 见 [references/handoff-mechanics.md](./references/handoff-mechanics.md)。

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

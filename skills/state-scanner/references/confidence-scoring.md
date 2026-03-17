# Confidence Scoring - 置信度评分方法论

> 推荐引擎置信度评分与自动执行策略

## 评分方法

每条推荐规则的置信度基于三个维度综合评估:

### 三维评估模型

| 维度 | 权重 | 说明 |
|------|------|------|
| **信号清晰度 (Signal Clarity)** | 40% | 触发条件的信号是否明确无歧义 |
| **风险等级 (Risk Level)** | 35% | 执行推荐后产生错误的潜在影响 |
| **可逆性 (Reversibility)** | 25% | 操作是否容易撤销 |

### 评分公式

```
confidence = signal_clarity * 0.4 + (1 - risk_level) * 0.35 + reversibility * 0.25
```

每个维度取值范围 0.0 ~ 1.0，最终置信度 = 加权和 * 100%。

### 各规则评分明细

| 规则 | 信号清晰度 | 风险等级 | 可逆性 | 置信度 |
|------|-----------|---------|--------|--------|
| `commit_only` | 1.0 (git 状态明确) | 0.05 (仅提交) | 1.0 (git reset) | **95%** |
| `quick_fix` | 0.9 (文件数+类型) | 0.1 (小范围) | 0.9 (易回滚) | **92%** |
| `doc_only` | 0.95 (文件后缀明确) | 0.02 (纯文档) | 1.0 (git reset) | **93%** |
| `requirements_issues` | 0.85 (验证器输出) | 0.15 (可能误报) | 0.8 | **85%** |
| `feature_with_spec` | 0.9 (Spec 状态明确) | 0.3 (进入开发) | 0.6 | **88%** |
| `architecture_missing` | 0.8 (文件存在性) | 0.2 | 0.8 | **80%** |
| `architecture_outdated` | 0.8 (状态字段) | 0.2 | 0.8 | **80%** |
| `architecture_chain_broken` | 0.8 (链路检查) | 0.2 | 0.8 | **80%** |
| `pending_stories` | 0.7 (状态字段) | 0.3 | 0.7 | **75%** |
| `missing_openspec` | 0.65 (关联检查) | 0.3 | 0.7 | **70%** |
| `feature_new` | 0.6 (复杂度估算) | 0.4 (完整循环) | 0.5 | **70%** |
| `missing_prd` | 0.6 (目录检查) | 0.3 | 0.7 | **65%** |
| `prd_refinement` | 0.6 (完整性检查) | 0.3 | 0.7 | **65%** |
| `fuzziness_requirement` | 0.5 (语义分析) | 0.3 | 0.7 | **60%** |

---

## 自动执行策略 (Auto-Execute Policy)

### 启用条件

自动执行**仅在同时满足以下两个条件时**触发:

1. **规则置信度 > 90%**
2. **项目启用 `auto_proceed`** (在 `.aria/config.json` 中配置)

```json
// .aria/config.json
{
  "workflow_runner": {
    "auto_proceed": true
  },
  "state_scanner": {
    "confidence_threshold": 90
  }
}
```

### 可自动执行的场景

当前仅有 3 条规则满足自动执行条件:

| 规则 | 置信度 | 自动执行的工作流 | 理由 |
|------|--------|-----------------|------|
| `commit_only` | 95% | commit-only | 已暂存 + 无未暂存 = 信号完全明确，提交可逆 |
| `quick_fix` | 92% | quick-fix | ≤3 文件 + 简单类型 = 范围小且清晰 |
| `doc_only` | 93% | doc-update | 纯 *.md 文件 = 零代码风险，完全可逆 |

### 自动执行流程

```
state-scanner 检测状态
    │
    ├─ 置信度 ≤ 阈值 → 正常流程: 展示推荐，等待用户确认
    │
    └─ 置信度 > 阈值 且 auto_proceed = true
        │
        ├─ 写入审计日志
        ├─ 输出: "⚡ 自动执行: {workflow} (置信度 {confidence}%)"
        └─ 直接传递给 workflow-runner 执行
```

### 阈值覆盖

用户可在 `.aria/config.json` 中自定义置信度阈值:

```json
{
  "state_scanner": {
    "confidence_threshold": 95
  }
}
```

- **默认值**: 90
- **有效范围**: 50 ~ 100
- **设为 100**: 等效于禁用自动执行

---

## 审计日志 (Audit Logging)

每次自动执行时，必须写入审计日志到 `.aria/audit.log`。

### 日志格式

```
[{ISO8601_TIMESTAMP}] AUTO-EXECUTE: rule={rule_id} confidence={confidence}% workflow={workflow_id}
```

### 示例

```
[2026-03-16T10:30:00Z] AUTO-EXECUTE: rule=commit_only confidence=95% workflow=commit-only
[2026-03-16T10:45:00Z] AUTO-EXECUTE: rule=doc_only confidence=93% workflow=doc-update
[2026-03-16T11:00:00Z] AUTO-EXECUTE: rule=quick_fix confidence=92% workflow=quick-fix
```

### 日志轮转

- 文件大小上限: 1MB
- 超限时: 重命名为 `audit.log.1`，创建新的 `audit.log`
- 最多保留: 3 个历史文件

---

## 安全保障 (Safeguards)

### Gate 不可绕过

**关键规则**: 即使规则满足自动执行条件，workflow-runner 中定义的 Gate 仍然有效且不可绕过。

```
自动执行 ≠ 绕过 Gate

Gate 1 (Spec Approval): 始终在 A → B 时检查
Gate 2 (Main Merge):    始终在合并到 main/master 时检查
```

这意味着:
- `commit_only` 自动执行 C.1 → 不涉及 Gate，正常执行
- `quick_fix` 自动执行 Phase B+C → 不涉及 Gate 1 (无 Phase A)，Gate 2 视目标分支而定
- `doc_only` 自动执行 B.3+C.1 → 不涉及 Gate，正常执行

### 自动执行禁止列表

以下场景永远不会自动执行，无论置信度多高:

1. **合并到 main/master 分支** — 需人工确认
2. **涉及 `.env`、credentials 等敏感文件** — 需人工确认
3. **首次在新仓库中运行** — 需人工确认建立信任

### 回退机制

如果自动执行结果不符预期:
- `commit_only`: `git reset HEAD~1` 撤销提交
- `quick_fix`: `git reset HEAD~1` 或 `git revert`
- `doc_only`: `git reset HEAD~1` 撤销提交

---

## 配置参考

### 完整 `.aria/config.json` 示例

```json
{
  "workflow_runner": {
    "auto_proceed": true
  },
  "state_scanner": {
    "confidence_threshold": 90,
    "auto_execute_enabled": true,
    "auto_execute_rules": ["commit_only", "quick_fix", "doc_only"],
    "audit_log_path": ".aria/audit.log"
  }
}
```

### 字段说明

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `confidence_threshold` | number | 90 | 自动执行的最低置信度 (%) |
| `auto_execute_enabled` | boolean | true | 是否启用自动执行 (需 auto_proceed 也为 true) |
| `auto_execute_rules` | string[] | 见上 | 允许自动执行的规则白名单 |
| `audit_log_path` | string | `.aria/audit.log` | 审计日志路径 |

---

**最后更新**: 2026-03-16
**版本**: 1.0.0

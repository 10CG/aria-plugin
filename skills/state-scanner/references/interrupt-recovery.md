# 中断恢复参考 (Interrupt Recovery Reference)

> **版本**: 1.0.0 | **适用于**: state-scanner 阶段 0

## 概述

当 state-scanner 在 `.aria/workflow-state.json` 中发现未完成的工作流时，
阶段 0 负责检测、验证、并引导用户做出恢复决策。本文档定义详细的恢复逻辑。

---

## 恢复决策树

```
.aria/workflow-state.json 存在？
├── 否 → 正常进入阶段 1
├── 解析失败 (corrupt) → 记录警告，视为不存在，进入阶段 1
└── 是 → 检查 status 字段
    ├── "completed" / "archived" → 忽略，进入阶段 1
    ├── "failed" → 失败恢复流程 (见下方)
    └── "in_progress" / "suspended" → 中断恢复流程
        ├── Git 一致性检查
        │   ├── 通过 → 并发会话检测
        │   │   ├── 检测到冲突 → 警告并发冲突，要求确认
        │   │   └── 无冲突 → 展示 Resume/Abandon/Inspect 选项
        │   └── 失败 → 警告不一致，仅提供 Abandon/Inspect
        └── 用户选择
            ├── Resume → 传递 context 给 workflow-runner
            ├── Abandon → 删除 state file，进入阶段 1
            └── Inspect → 显示详情，再次提供选择
```

---

## Git 一致性验证规则

在尝试恢复工作流之前，必须确认 Git 状态与工作流状态一致。

### 验证项

| 检查项 | 状态文件字段 | Git 命令 | 失败条件 |
|--------|-------------|----------|----------|
| 分支匹配 | `git_anchor.branch` | `git branch --show-current` | 当前分支 != 记录分支 |
| 提交可达 | `git_anchor.commit_sha` | `git log --oneline -1 {sha}` | SHA 不在历史中 |
| 无强制回退 | `git_anchor.commit_sha` | `git merge-base --is-ancestor {sha} HEAD` | 锚定提交不是 HEAD 祖先 |

### 验证逻辑

```yaml
步骤:
  1. 读取 git_anchor.branch 和 git_anchor.commit_sha
  2. 获取当前分支: git branch --show-current
  3. 分支匹配检查:
     - 不匹配 → 标记 branch_mismatch
  4. SHA 可达检查:
     - git merge-base --is-ancestor {commit_sha} HEAD
     - 返回非 0 → 标记 sha_drift
  5. 综合判定:
     - 全部通过 → consistent: true
     - 任一失败 → consistent: false, 附带 issues 列表

输出:
  git_consistency:
    consistent: true | false
    issues:
      - type: branch_mismatch
        expected: "feature/add-auth"
        actual: "main"
      - type: sha_drift
        anchor_sha: "abc1234"
        detail: "锚定提交不是当前 HEAD 的祖先"
```

### 不一致时的处理

当 Git 状态不一致时，**不允许直接 Resume**，因为恢复可能基于错误的代码状态。

用户选项:
1. **Abandon** - 删除状态文件，从当前 Git 状态重新开始
2. **Inspect** - 显示完整不一致详情，帮助用户理解发生了什么

展示格式:
```
⚠️ 工作流状态与 Git 状态不一致
───────────────────────────────────────
  记录分支: feature/add-auth
  当前分支: main
  问题: 分支不匹配 (可能已手动切换)

  [1] 放弃工作流状态 (Abandon)
  [2] 查看详细信息 (Inspect)
```

---

## 并发会话检测协议

防止多个 AI 会话同时操作同一工作流。

### 检测条件

```yaml
并发冲突判定:
  条件 (ALL):
    - state file 中 session.last_active_at 在当前时间 5 分钟以内
    - state file 中 session.session_id != 当前会话 ID

  当前会话 ID 生成:
    - 使用 PID + 时间戳组合: "{PID}-{timestamp}"
    - 或读取环境变量 CLAUDE_SESSION_ID (如果可用)
```

### 冲突时的处理

```
⚠️ 检测到可能的并发会话
───────────────────────────────────────
  活跃会话 ID: session-abc-123
  最后活跃: 2 分钟前
  当前会话 ID: session-def-456

  另一个会话可能正在操作此工作流。
  继续操作可能导致状态冲突。

  [1] 强制接管 (Force Resume) - 覆盖会话所有权
  [2] 等待并重试 (Wait) - 30 秒后重新检测
  [3] 放弃 (Abandon) - 删除状态，重新扫描
```

### 接管逻辑

选择 Force Resume 时:
1. 更新 `session.session_id` 为当前会话
2. 更新 `session.last_active_at` 为当前时间
3. 正常进入恢复流程

---

## 失败状态恢复

当 `status` 为 `"failed"` 时的处理流程。

### 展示格式

```
❌ 上次工作流执行失败
───────────────────────────────────────
  工作流: feature-dev
  失败位置: Phase B.2 (执行验证)
  失败原因: {error.message}
  失败时间: {error.timestamp}

  [1] 从失败点重试 (Retry)
  [2] 放弃并重新扫描 (Abandon)
  [3] 查看详细错误 (Inspect)
```

### 处理逻辑

```yaml
Retry:
  - 先执行 Git 一致性验证
  - 通过 → 传递 context 给 workflow-runner (resume=true, retry_from={failed_phase})
  - 不通过 → 降级为 Abandon/Inspect 选项

Abandon:
  - 删除 state file
  - 进入阶段 1 正常扫描

Inspect:
  - 显示完整 error 对象
  - 显示 execution_history (已执行步骤及结果)
  - 再次提供 Retry/Abandon 选项
```

---

## 状态文件损坏处理

### 损坏判定

```yaml
损坏条件 (ANY):
  - JSON 解析失败
  - 缺少必需字段: status, workflow_name
  - status 值不在允许范围内
  - git_anchor 字段缺失或不完整

允许的 status 值:
  - "in_progress"
  - "suspended"
  - "failed"
  - "completed"
  - "archived"
```

### 处理逻辑

```yaml
步骤:
  1. 尝试 JSON.parse
  2. 失败 → 记录警告:
     "⚠️ .aria/workflow-state.json 损坏，将忽略"
  3. 成功但缺少必需字段 → 同上
  4. 备份损坏文件: 重命名为 .aria/workflow-state.json.corrupt.{timestamp}
  5. 进入阶段 1 正常扫描
```

---

## 场景示例

### 场景 1: 正常中断恢复

用户在 Phase B.2 开发过程中关闭了终端，重新打开后执行 `/state-scanner`:

```
⚠️ 检测到未完成的工作流
───────────────────────────────────────
  工作流: feature-dev
  中断位置: Phase B.2
  分支: feature/add-auth
  最后活跃: 2026-03-16 10:30

  [1] 恢复工作流 (Resume)
  [2] 放弃并重新扫描 (Abandon)
  [3] 查看详细状态 (Inspect)
```

用户选择 [1] → workflow-runner 从 B.2 继续执行。

### 场景 2: 分支已切换

用户中断后手动切换到了 main 分支:

```
⚠️ 工作流状态与 Git 状态不一致
───────────────────────────────────────
  记录分支: feature/add-auth
  当前分支: main
  问题: 分支不匹配

  [1] 放弃工作流状态 (Abandon)
  [2] 查看详细信息 (Inspect)
```

### 场景 3: 并发会话检测

两个终端窗口同时运行 state-scanner:

```
⚠️ 检测到可能的并发会话
───────────────────────────────────────
  活跃会话 ID: session-1234-1710579000
  最后活跃: 2 分钟前

  [1] 强制接管 (Force Resume)
  [2] 等待并重试 (Wait)
  [3] 放弃 (Abandon)
```

### 场景 4: 失败后恢复

上次执行 Phase C.1 时 Git commit 失败:

```
❌ 上次工作流执行失败
───────────────────────────────────────
  工作流: feature-dev
  失败位置: Phase C.1 (提交)
  失败原因: pre-commit hook 检查失败
  失败时间: 2026-03-16 09:15

  [1] 从失败点重试 (Retry)
  [2] 放弃并重新扫描 (Abandon)
  [3] 查看详细错误 (Inspect)
```

### 场景 5: 损坏的状态文件

状态文件无法解析:

```
(内部日志) ⚠️ .aria/workflow-state.json 损坏，已备份为
  .aria/workflow-state.json.corrupt.1710579000
(无用户交互，直接进入阶段 1 正常扫描)
```

---

## 与其他组件的交互

### workflow-runner 恢复接口

```yaml
传递给 workflow-runner 的恢复 context:
  resume: true
  state_file: ".aria/workflow-state.json"
  resume_from: "{中断的 phase}"     # 如 "B.2"
  retry_from: "{失败的 phase}"      # 仅失败恢复时
  original_context:
    workflow_name: "{工作流名称}"
    phase_cycle: "{进度}"
    module: "{模块}"
```

### state-scanner 阶段 0 输出

```yaml
# 当恢复时，阶段 0 的输出直接传递给 workflow-runner，跳过阶段 1-4
phase_0_result:
  action: "resume" | "abandon" | "normal"
  workflow_context: { ... }  # 仅 resume 时
```

---

**创建**: 2026-03-16
**版本**: 1.0.0

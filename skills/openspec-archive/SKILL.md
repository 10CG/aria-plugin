---
name: openspec-archive
description: |
  归档已完成的 OpenSpec 变更到正确的 archive/ 目录，自动修正 CLI bug。

  使用场景："归档 Spec"、"Phase D.2"、"完成变更归档"
argument-hint: "[change-name]"
disable-model-invocation: false
user-invocable: true
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# OpenSpec Archive (归档器)

> **版本**: 1.0.0 | **十步循环**: D.2
> **更新**: 2026-02-08 - 初始版本，修复 CLI 归档位置 bug

## 快速开始

### 我应该使用这个 Skill 吗？

**使用场景**:
- Spec 所有任务已完成，需要归档
- Phase D.2 收尾阶段
- 清理已完成的变更

**不使用场景**:
- Spec 仍有活跃任务 → 完成任务后再归档
- 需要继续修改 Spec → 保持变更活跃状态

---

## 核心功能

| 功能 | 说明 |
|------|------|
| **状态验证** | 检查 Spec 完成状态和任务完成度 |
| **执行归档** | 调用 openspec archive CLI |
| **自动修正** | 修正 CLI 的归档目录位置 bug |
| **清理验证** | 清理空目录，验证最终结果 |

---

## ⚠️ 已知 Bug: OpenSpec CLI 归档位置错误

**问题**: `openspec archive` CLI 命令有 bug，输出到错误位置：

```
❌ CLI 输出: openspec/changes/archive/YYYY-MM-DD-{feature}/
✅ 正确位置: openspec/archive/YYYY-MM-DD-{feature}/
```

**本 Skill 会自动修正此问题**。

---

## 正确的目录结构

```
openspec/
├── archive/                    # ✅ 正确的归档位置
│   └── YYYY-MM-DD-{feature}/
│       ├── proposal.md
│       ├── tasks.md
│       └── detailed-tasks.yaml
└── changes/                    # 活跃变更
    └── {active-feature}/
```

---

## 执行流程

### 输入

```yaml
change_name:
  required: true
  description: 要归档的变更目录名
  example: "cloudflare-access-auto-handling"

options:
  skip_verification: false    # 跳过完成状态验证
  keep_changes_copy: false     # 在 changes/ 中保留副本
  dry_run: false               # 仅验证不执行
```

### 步骤

```yaml
Step 1 - 验证完成状态:
  检查: openspec/changes/{change_name}/tasks.md
  验证: 所有任务标记为 [x] (完成)
  失败: 提示未完成任务，中止归档

Step 2 - 更新 proposal.md 状态:
  读取: openspec/changes/{change_name}/proposal.md
  更新: Status: Implemented → Complete
  保存: 更新后的 proposal.md

Step 3 - 执行 CLI 归档命令:
  命令: openspec archive {change_name} --yes
  等待: CLI 完成

Step 4 - 检测并修正归档位置:
  检测: openspec/changes/archive/ 是否存在
  如果存在:
    → 移动: openspec/changes/archive/* → openspec/archive/
    → 清理: rmdir openspec/changes/archive/
  如果不存在:
    → 验证: openspec/archive/YYYY-MM-DD-{change_name}/ 是否存在

Step 5 - 清理活跃变更目录 (可选):
  删除: openspec/changes/{change_name}/
  除非: keep_changes_copy = true

Step 6 - 验证归档结果:
  确认: 归档目录在 openspec/archive/ 下
  确认: 包含完整的 proposal.md, tasks.md, detailed-tasks.yaml
```

---

## 输出格式

```yaml
success: true
change_name: "cloudflare-access-auto-handling"
archive_path: "openspec/archive/2026-02-08-cloudflare-access-auto-handling"
cli_bug_fixed: true
warnings: []
verification:
  archive_exists: true
  contains_proposal: true
  contains_tasks: true
  contains_detailed_tasks: true
  wrong_dir_cleaned: true
```

---

## 使用示例

### 示例 1: 标准归档

```yaml
输入:
  change_name: "cloudflare-access-auto-handling"

执行:
  Step 1: ✅ 验证所有任务完成
  Step 2: ✅ 更新 proposal.md 状态
  Step 3: ✅ 执行 openspec archive
  Step 4: ✅ 修正归档位置 (检测到 CLI bug)
  Step 5: ✅ 清理活跃变更目录
  Step 6: ✅ 验证归档结果

输出:
  ✅ 归档成功
  📍 位置: openspec/archive/2026-02-08-cloudflare-access-auto-handling
  🐛 CLI bug 已自动修正
```

### 示例 2: 未完成任务

```yaml
输入:
  change_name: "incomplete-feature"

执行:
  Step 1: ❌ 检测到未完成任务
  未完成:
    - [ ] Task 3: 实现错误处理
    - [ ] Task 4: 添加单元测试

输出:
  ❌ 归档中止
  原因: 存在未完成的任务
  建议: 完成所有任务后再执行归档
```

### 示例 3: Dry Run

```yaml
输入:
  change_name: "test-feature"
  dry_run: true

输出:
  📋 Dry Run 结果
  验证: ✅ 所有任务已完成
  预期归档路径: openspec/archive/2026-02-08-test-feature
  建议: 可以安全执行归档
```

---

## 错误处理

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| 变更目录不存在 | change_name 拼写错误 | 检查 openspec/changes/ 目录 |
| 存在未完成任务 | tasks.md 有未完成项 | 完成任务或使用 --force |
| CLI 命令失败 | openspec CLI 未安装 | 安装 openspec CLI |
| 归档目录冲突 | 目标归档目录已存在 | 检查是否已归档 |
| 权限不足 | 无法移动/删除文件 | 检查文件权限 |

---

## 与其他 Phase 的关系

```
phase-d-closer
    │
    │ D.1 - 进度更新 (progress-updater)
    │   └── 更新 UPM 进度状态
    │
    │ D.2 - Spec 归档 (openspec-archive) ◄── 本 Skill
    │   ├── 验证完成状态
    │   ├── 执行归档
    │   ├── 修正 CLI bug
    │   └── 验证结果
    │
    ▼
完成闭环
```

---

## 相关文档

- **Phase D 规范**: `standards/core/ten-step-cycle/phase-d-closure.md`
- **OpenSpec 项目规范**: `standards/openspec/project.md`
- **归档目录说明**: `openspec/archive/README.md`
- **已知 Bug 列表**: `standards/openspec/AGENTS.md`

---

## 变更历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-02-08 | 初始版本，实现 CLI bug 自动修正 |

---

**最后更新**: 2026-02-08
**Skill版本**: 1.0.0

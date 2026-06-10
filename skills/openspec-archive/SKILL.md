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
  skip_verification: false     # 仅跳过 tasks.md [x] 校验 (v1.42.0+ 收口: 不绕过 Status 归一化 gate)
  keep_changes_copy: false     # 在 changes/ 中保留副本
  dry_run: false               # 仅验证不执行 (三路输出, 见示例 3)
  archive_design_only: false   # 逃生舱 (--archive-design-only): 归档未实施稿, 须配 reason
  reason: ''                   # archive_design_only 必填; ≥10 非空白字符, 拒纯空白
```

### 步骤

```yaml
Step 1 - 完成 gate (验证完成状态, #134 v1.42.0+):
  # ── 前置 (最前): already-archived 检查 ──
  already_archived_precheck:
    检查: ls openspec/archive/ | grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}-{change_name}$'  # 日期前缀锚定防后缀误匹配  # 已存在对应条目?
    若已存在: 立即 abort (BLOCKED-already-archived)
    约束: 不进入完成度判定、不写任何标记 (标记写入属 Step 2, abort 路径零残留)

  # ── 完成判定: Bash 调单一可执行 SOT, 不再由 AI 解释 prose ──
  completeness_verdict:
    命令: |
      python3 "${CLAUDE_PLUGIN_ROOT:-aria}/skills/state-scanner/scripts/lib/spec_complete.py" \
        "openspec/changes/{change_name}"
    读取: stdout JSON {complete: bool, reason: str} + exit code
    exit_code: 0 = complete / 1 = incomplete / 2 = usage 或非预期错误 (视同 incomplete)
    # 多入口一致 verdict 不变量 (AC-1): 本 gate 与 collectors/openspec.py import 调用、
    # phase-d-closer D.2 skip_evaluation 必须对同一 spec_dir 得到相同 verdict

  # ── verdict 路由 ──
  verdict_routing:
    complete=true: 放行 → 进 Step 2 路径 (a) 正常归档
    complete=false 且 archive_design_only=true:
      reason 校验: 去除空白字符后 ≥10 字符 (拒纯空白/过短)
      校验失败: abort (BLOCKED-invalid-reason)
      校验通过: 放行 → 进 Step 2 路径 (b) design-only 归档
    complete=false 且未配逃生舱:
      默认 BLOCK — 回显 spec_complete.py 的 reason 列出缺口
      (未完成 task 数 / Status 归一化值 / carry-forward 注释数), 中止归档

  # ── skip_verification 收口 (v1.42.0+) ──
  skip_verification_scope:
    语义: 仅跳过 tasks.md [x] 校验, 不绕过 Status 归一化 gate
    约束: 缺 tasks.md 且 normalized Status 非 'done' 时, skip_verification=true 也 BLOCK
    backward_compat_shim: 旧 skip_verification=true 且未配 archive_design_only
      → WARN + abort (不静默降级), 提示改用 --archive-design-only + reason

Step 2 - 写 proposal.md (三路径分叉; 标记写入属本步, 非 Step 1 副作用):
  读取: openspec/changes/{change_name}/proposal.md
  路径 (a) 正常归档 (complete=true):
    更新: Status 非 done 时更新为 Complete (向后兼容既有行为)
  路径 (b) design-only 归档 (archive_design_only=true):
    不改 Status — 仅 frontmatter 追加机读字段:
      archive_type: implementation-deferred
      archived_reason: "{reason}"
    # 消费侧: state-scanner collectors/openspec.py archive 循环读 archive_type (round-trip)
  路径 (c) dry_run=true:
    不写入任何文件 (见 dry_run 三路输出说明)
  保存: (a)/(b) 路径写回 proposal.md; (c) 路径无写入

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
  Step 1: ❌ 完成 gate BLOCK (spec_complete.py exit 1)
  reason 回显: "tasks.md has 2/4 unchecked task(s); normalized Status = 'approved' (≠ done)"
  未完成:
    - [ ] Task 3: 实现错误处理
    - [ ] Task 4: 添加单元测试

输出:
  ❌ 归档中止 (默认 BLOCK)
  原因: spec_complete.py 判定 complete=false (缺口见 reason 回显)
  建议: 完成所有任务后再执行归档; 确需归档未实施稿 → --archive-design-only + reason
```

### 示例 3: Dry Run (三路输出)

> dry_run=true 执行 Step 1 gate 全部判断 (already-archived 前置 + tasks.md + Status + 标记读取),
> 报告三路结果并保持"不实际写入"不变量。
> **注**: dry_run 三路完全基于 (a) CLI flag (b) 本地 tasks.md (c) proposal.md Status —
> 均由本 Skill 直接读取, **不依赖** state-scanner snapshot 预计算字段。

#### 3a: BLOCKED (未完成且未配逃生舱)

```yaml
输入:
  change_name: "test-feature"
  dry_run: true

输出:
  📋 Dry Run 结果: ❌ BLOCKED
  verdict: complete=false
  reason 回显: "tasks.md has 1/4 unchecked task(s); normalized Status = 'approved' (≠ done)"
  声明: 未发生任何写入 (dry_run)
  建议: 完成缺口后重试, 或 --archive-design-only + reason
```

#### 3b: ALLOWED (完成, 正常归档可执行)

```yaml
输入:
  change_name: "test-feature"
  dry_run: true

输出:
  📋 Dry Run 结果: ✅ ALLOWED
  verdict: complete=true ("tasks.md 全 [x] (4 task(s), 无 carry-forward/defer 注释)")
  预期归档路径: openspec/archive/2026-02-08-test-feature
  声明: 未发生任何写入 (dry_run)
  建议: 可以安全执行归档
```

#### 3c: ALLOWED-design-only (逃生舱 + reason 回显)

```yaml
输入:
  change_name: "design-doc-feature"
  dry_run: true
  archive_design_only: true
  reason: "方案被 DEC-20260609-001 替代, 仅存档设计稿供追溯"

输出:
  📋 Dry Run 结果: ✅ ALLOWED-design-only
  verdict: complete=false (逃生舱放行)
  reason 回显: "方案被 DEC-20260609-001 替代, 仅存档设计稿供追溯"
  若执行将写入 frontmatter: "archive_type: implementation-deferred" + archived_reason
  声明: 未发生任何写入 (dry_run)
```

#### 3d: reason 校验拒绝 (BLOCKED-invalid-reason)

```yaml
输入:
  change_name: "design-doc-feature"
  dry_run: true
  archive_design_only: true
  reason: "  存档  "        # 去除空白后 < 10 字符

输出:
  📋 Dry Run 结果: ❌ BLOCKED-invalid-reason
  原因: reason 不足 10 非空白字符 (拒纯空白)
  声明: 未发生任何写入 (dry_run)
  建议: 提供 ≥10 非空白字符的实质性 reason
```

---

## 错误处理

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| 变更目录不存在 | change_name 拼写错误 | 检查 openspec/changes/ 目录 |
| 完成 gate BLOCK | spec_complete.py 判定 complete=false | 完成缺口后重试; 确需归档未实施稿 → `--archive-design-only` + reason |
| BLOCKED-invalid-reason | reason 不足 10 非空白字符 (含纯空白) | 提供 ≥10 非空白字符的实质性 reason |
| BLOCKED-already-archived | openspec/archive/ 已存在对应条目 (Step 1 前置 abort) | 检查是否已归档; 不重复写标记 |
| `--force` (DEPRECATED) | 旧绕过通道, v1.42.0+ 收口 | 改用 `--archive-design-only` + reason (可追溯逃生舱) |
| skip_verification=true 未配逃生舱 | backward-compat shim 触发 | WARN + abort (不静默降级); 改用 `--archive-design-only` + reason |
| CLI 命令失败 | openspec CLI 未安装 | 安装 openspec CLI |
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

# Changelog

All notable changes to the `branch-manager` skill will be documented in this file.

## [2.0.0] - 2026-01-20

### Added

- **Auto Mode Decision**: 智能模式决策系统
  - 5 维度评分算法 (file_count, cross_directory, task_count, risk_level, parallel_needed)
  - 自动选择 Branch 或 Worktree 模式
  - 阈值: score >= 3 → Worktree, score < 3 → Branch
  - 风险等级自动检测 (low/medium/high)

- New Input Parameters:
  - `mode`: `auto` | `branch` | `worktree`
  - `files`: 预期修改的文件列表
  - `task_count`: 预计任务数量
  - `risk_level`: 风险等级
  - `parallel_needed`: 是否需要并行开发

- New Internal Module:
  - `internal/MODE_DECISION_LOGIC.md`: 模式决策逻辑详细文档
  - 伪代码实现示例
  - 决策示例和评分规则

### Changed

- B.1 执行流程新增 B.1.0 模式决策步骤
- 输出格式新增 `mode` 和 `decision_reason` 字段
- 支持两种模式的分支创建流程

### Migration Guide

从 v1.x 升级到 v2.0:

```yaml
# 旧版本 (隐式 Branch 模式)
branch-manager --task-id TASK-001

# 新版本 (显式 Auto 模式 - 推荐)
branch-manager --mode auto --task-id TASK-001

# 新版本 (强制 Branch 模式)
branch-manager --mode branch --task-id TASK-001

# 新版本 (强制 Worktree 模式)
branch-manager --mode worktree --task-id TASK-001
```

**向后兼容**: 默认 `mode=auto`，对于简单任务会自动选择 Branch 模式。

### Related

- OpenSpec: `openspec/changes/enforcement-mechanism-redesign/`
- Phase 1.1: 模式决策逻辑实现

---

## [1.2.0] - 2026-01-18

### Added

- Git Worktrees 集成
- `use_worktree` 参数支持
- Worktree 创建、管理、清理命令
- Worktree 目录结构文档

---

## [1.0.0] - 2025-12-16

### Added

- Initial release of branch-manager skill
- B.1: Branch creation functionality
  - Support for main repository branches
  - Support for submodule branches
  - Multiple branch types (feature, bugfix, hotfix, release, experiment)
  - Module identifiers (backend, mobile, shared, cross, docs, standards)
- C.2: PR creation functionality
  - Integration with Forgejo API
  - PR template with Summary, Changes, Test Plan sections
  - Support for squash, merge, and rebase strategies
  - Branch cleanup after merge
- Submodule workflow documentation
- Error handling and recovery procedures

### Related Documents

- Ten-Step Cycle: Phase B (B.1-B.3), Phase C (C.1-C.2)
- Branch Management Guide
- Forgejo API Guide

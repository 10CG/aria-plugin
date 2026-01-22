# Changelog

All notable changes to the `subagent-driver` skill will be documented in this file.

## [1.0.0] - 2026-01-21

### Added

- **Fresh Subagent Mechanism**: 每个任务启动全新的子代理实例
  - 对话隔离 (L1)
  - 文件隔离 (L2, 使用 Worktree)
  - 完全隔离 (L3, 独立进程)

- **Inter-Task Code Review**: 任务间代码审查
  - 自动触发审查
  - 安全检查、代码质量检查、测试覆盖检查
  - 审查报告生成

- **Four-Option Completion Flow**: 4 选项完成流程
  - [1] 继续下一任务
  - [2] 修改当前任务
  - [3] 回退并重做
  - [4] 暂停并保存

- **Context Isolation Verification**: 上下文隔离验证
  - L1/L2/L3 隔离级别验证
  - 自动隔离级别选择

- **Task State Tracking**: 任务状态追踪
  - 会话状态管理
  - 暂停/恢复支持
  - 状态文件持久化

### Internal Modules

- `internal/FRESH_SUBAGENT_LAUNCHER.md` - Fresh Subagent 启动逻辑
- `internal/INTER_TASK_REVIEW.md` - 任务间代码审查机制
- `internal/FOUR_OPTION_COMPLETION.md` - 4 选项完成流程
- `internal/CONTEXT_ISOLATION.md` - 上下文隔离验证
- `internal/TASK_STATE_TRACKING.md` - 任务状态追踪

### Integration

- 与 branch-manager v2.0.0 集成
  - branch 模式 → L1 隔离
  - worktree 模式 → L2 隔离
- 与 feature-dev:code-reviewer agent 集成

### Related

- OpenSpec: `openspec/changes/enforcement-mechanism-redesign/`
- Phase 2: subagent-driver 技能实现

---

**最后更新**: 2026-01-21
**Skill版本**: 1.0.0

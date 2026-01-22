# Changelog

All notable changes to the `branch-finisher` skill will be documented in this file.

## [1.0.0] - 2026-01-21

### Added

- **Test Pre-Validation**: 测试前置验证
  - 单元测试、集成测试验证
  - 类型检查、Lint 检查
  - 构建验证
  - 覆盖率检查 (可选)

- **Four-Option Completion Flow**: 4 选项完成流程
  - [1] 提交并创建 PR
  - [2] 继续修改
  - [3] 放弃变更
  - [4] 暂停保存

- **Worktree Cleanup Decision**: Worktree 清理决策
  - 智能清理时机判断
  - 用户确认流程
  - 自动清理选项

- **Integration**: 集成支持
  - 与 subagent-driver 集成
  - 与 branch-manager 集成
  - 与 tdd-enforcer 集成

### Related

- OpenSpec: `openspec/changes/enforcement-mechanism-redesign/`
- Phase 3: branch-finisher 技能实现

---

**最后更新**: 2026-01-21
**Skill版本**: 1.0.0

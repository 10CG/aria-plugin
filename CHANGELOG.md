# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.0] - 2026-02-05

### Added

- **brainstorm** Skill - AI-DDD 协作思考引擎，通过多轮对话澄清需求、记录设计决策
  - 三种工作模式: `problem` (问题空间探索), `requirements` (需求分解), `technical` (技术方案设计)
  - 对话状态机: INIT → CLARIFY → EXPLORE → CONVERGE → SUMMARY → COMPLETE
  - 决策记录系统: 结构化记录"为什么选 A 而非 B"
  - 约束管理: 支持 business/technical/team 三类约束
  - 与 state-scanner/spec-drafter 深度集成

- **state-scanner 增强** - 新增头脑风暴推荐规则
  - `fuzziness_requirement`: 检测模糊需求，推荐 problem 模式
  - `missing_prd`: 复杂功能变更，推荐创建 PRD
  - `prd_refinement`: PRD 需要细化，推荐 requirements 模式
  - `tech_design_needed`: 有就绪 Story 无 OpenSpec，推荐 technical 模式

- **spec-drafter 增强** - 内置头脑风暴流程
  - PRD 创建时自动触发 requirements 模式
  - OpenSpec 创建时自动触发 technical 模式
  - 基于讨论结果预填充 proposal.md
  - 决策引用系统，支持完整追溯链

### Changed

- **workflow-runner** - 新增 A.0.5 步骤 (问题空间头脑风暴)
- **Skills 总数**: 24 → 25
- **Progressive Disclosure**: brainstorm SKILL.md 采用三层加载架构 (357 行主文件 + 按需引用)

### Fixed

- 优化 SKILL.md 文件大小 (1723 → 357 行, -79%)，符合最佳实践

## [1.1.1] - 2026-01-28

### Fixed

- **Skills 调用链配置优化** - 修复 `disable-model-invocation` 配置可能阻断 skill-to-skill 嵌套调用的问题

### Changed

- 采用分层控制策略，所有 24 个 skills 显式配置 `disable-model-invocation` 参数
- **入口层 (3个)** - 保持 `disable-model-invocation: true`
  - `workflow-runner` - 十步循环总入口
  - `api-doc-generator` - 独立功能，需用户指定框架
  - `arch-scaffolder` - 独立功能，需用户指定 PRD 路径
- **功能层 (21个)** - 改为 `disable-model-invocation: false`，允许被其他 skills 调用
  - Phase 阶段: phase-a-planner, phase-b-developer, phase-c-integrator, phase-d-closer
  - 核心功能: spec-drafter, task-planner, branch-manager, subagent-driver, commit-msg-generator, progress-updater, arch-update, branch-finisher, strategic-commit-orchestrator
  - 验证/扫描: state-scanner, requirements-validator, tdd-enforcer
  - 同步/搜索: forgejo-sync, requirements-sync, arch-search
  - 内部工具: agent-router, arch-common
- `agent-router` 和 `arch-common` 设置 `user-invocable: false`（内部工具，用户不需要直接调用）

## [1.1.0] - 2026-01-26

### Added

- 初始版本发布
- 24 个 Skills
- 10 个 Agents
- Hooks 系统 (SessionStart, SessionEnd, PreToolUse)

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.5.0] - 2026-02-08

### Changed

- **Cloudflare Access 自动处理重构** - 彻底解决 AI 不自动使用 CF Access 配置的问题
  - 新增 `FORGEJO_API_PRE_CHECK.md` - 统一的前置检查规范，作为所有 Forgejo API 调用的唯一真理来源
  - **branch-manager/SKILL.md** - 将前置检查嵌入执行流程 C.2.3，不再作为文档说明
  - **forgejo-sync/SKILL.md** - 引用统一检查规范文档
  - **phase-c-integrator/SKILL.md** - 更新引用统一规范

### Design Philosophy

```yaml
v1.4.1 问题:
  - 检查规则放在文档章节，AI 需要主动理解
  - 配置在 forgejo-sync，但 PR 创建在 branch-manager
  - 没有强制执行点

v1.5.0 解决方案:
  - 创建统一的 FORGEJO_API_PRE_CHECK.md
  - 检查规则嵌入执行流程步骤中
  - AI 按步骤执行时强制检查
  - 所有 Skills 引用同一规范
```

### Fixed

- **AI 自动检测 Cloudflare Access** - 前置检查成为执行流程的一部分，AI 必须执行

---

## [1.4.1] - 2026-02-07

### Added

- **Cloudflare Access AI 自动处理** - AI 主动识别和处理 Forgejo 的 Cloudflare Access 保护
  - 新增 `cloudflare_access` 配置项 - 控制 AI 是否使用 CF Access 模式
  - 新增 `API_CALL_PATTERN.md` - 统一的 Forgejo API 调用模式文档
  - AI 执行前检查规则 - API 调用前自动检测 `cloudflare_access.enabled`
  - 错误自动检测 - API 返回 403/CF 错误时自动提示配置
  - 自动配置提示模板 - 检测到 CF 保护时输出配置示例

### Changed

- **forgejo-sync SKILL.md** - 新增 "AI 执行前检查 (不可协商规则)" 章节
- **branch-manager SKILL.md** - 更新 Forgejo API 调用，支持 CF Access 头部
- **phase-c-integrator SKILL.md** - 添加 Cloudflare Access 引用
- **forgejo-sync 规范 (standards)** - 新增 Cloudflare Access 支持要求

---

## [1.4.0] - 2026-02-07

### Added

- **两阶段代码审查** - Superpowers 风格的代码审查机制
  - 新增 `aria:code-reviewer` Agent - 执行 Phase 1 (规范合规性) + Phase 2 (代码质量) 检查
  - 新增 `requesting-code-review` Skill - 用户可调用入口，自动填充模板并启动审查
  - **subagent-driver** 集成两阶段审查 - 新增 `enable_two_phase` 参数 (默认: true)
  - 审查结果分类: Critical (必须修复) / Important (应该修复) / Minor (建议修复)
  - 支持无计划降级模式 - 无 detailed-tasks.yaml 时仅执行 Phase 2
  - 中英双语支持 - 审查结果可用中文或英文输出
  - 7 个完整示例场景 - 覆盖 PASS/FAIL/WARN/Fallback/分批/调用等场景

### Changed

- **subagent-driver** v1.3.0
  - 新增 `enable_two_phase` 参数控制两阶段审查开关
  - 新增两阶段审查流程图和文档说明
  - 审查模式对比: 传统模式 vs 两阶段模式

- **Skills 总数**: 25 → 26
- **Agents 总数**: 10 → 11

### Design Philosophy

```yaml
两阶段代码审查:
  Phase 1: 规范合规性检查 (Specification Compliance)
    - 验证实现与计划一致
    - 检查功能完整性
    - 检测范围变更
    - 阻塞性: FAIL 终止审查

  Phase 2: 代码质量检查 (Code Quality)
    - 检查代码风格
    - 检查测试覆盖
    - 检查安全性
    - 检查架构设计
    - 阻塞性: 仅 Critical 阻塞

参考实现:
  - obra/superpowers requesting-code-review
  - Superpowers Code Review 最佳实践
```

## [1.3.2] - 2026-02-06

### Changed

- **brainstorm** - v2.0.0 重大重构：基于 Superpowers 最佳实践简化对话流程
  - 移除复杂的 6 状态机 (INIT/CLARIFY/EXPLORE/CONVERGE/SUMMARY/COMPLETE)
  - 采用简洁的 3 阶段流程 (Understanding → Exploring → Presenting)
  - 新增"不可协商规则"强制对话控制
  - SKILL.md 精简 (357 → 262 行, -27%)
  - 新增 `references/principles.md` - 核心原则详解
  - 新增 `references/question-patterns.md` - 提问模式库

### Fixed

- **brainstorm** - 修复 AI 跳过对话直接生成 User Stories 的问题
  - 添加"每次只能问 1 个问题"强制约束
  - 添加"禁止一次性生成所有 User Stories"规则
  - 添加"分段验证"机制 (200-300 词/段)

## [1.3.1] - 2026-02-06

### Fixed

- **state-scanner** - 修复 Windows 环境下 Bash 命令兼容性问题
  - Claude Code 在 Windows 上使用 Git Bash/WSL，而非 Windows CMD
  - 添加跨平台命令对照表 (正确/错误语法对比)
  - 新增 `references/cross-platform-commands.md` 详细参考文档
  - 采用 Progressive Disclosure 最佳实践 (SKILL.md 精简至 1,362 词)

### Changed

- **state-scanner** v2.3.0
  - 精简 SKILL.md 中的实现注意事项章节
  - 将详细命令示例移至 references/cross-platform-commands.md
  - 更新相关文档章节结构，分类更清晰

## [1.3.0] - 2026-02-06

### Changed

- **版本规范化** - 统一所有配置文件版本信息
  - 更新 `marketplace.json` 版本: 1.1.1 → 1.3.0
  - 更新 `hooks.json` 版本: 1.1.0 → 1.3.0
  - 新增 `VERSION` 文件作为人类可读版本快照
  - Skills 数量: 24 → 25

- **tdd-enforcer** - v2.0 重大重构：从代码驱动设计改为**文档驱动设计**
  - 参考 Superpowers 的实现方式，AI 读取文档理解并执行 TDD 规则
  - 移除所有 Python 实现文件 (17+ 模块: test_runners/, validators/, hooks/, tests/)
  - 重写 SKILL.md (798 → 355 行)，采用 Progressive Disclosure 架构
  - 新增 references/ 目录包含 4 个详细参考文档
  - 配置格式变更: `strict_mode` → `strictness` (advisory|strict|superpowers)

- **brainstorm** - v1.1.0 结构优化完成
  - SKILL.md 优化 (1723 → 357 行, -79%)
  - 完整实现 Phase 1-4 核心框架

### Removed

- tdd-enforcer Python 实现:
  - `cache.py`, `config.py`, `diff_analyzer.py`
  - `state_persistence.py`, `state_tracker.py`
  - `test_runners/`, `validators/`, `hooks/`, `tests/` 目录

### Design Philosophy

```yaml
v1.x (错误):
  问题: 把 Skill 当作 Python 包来开发
  - 创建大量 Python 模块
  - 实现复杂的类继承结构
  - 编写单元测试
  根本问题: Claude Code 不会导入执行这些 Python 代码

v2.0 (正确):
  方案: 参考 Superpowers，文档驱动设计
  - SKILL.md 描述工作流
  - AI 读取并理解流程
  - AI 按流程执行检查
  优势: 符合 Agent Skills 设计原则
```

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

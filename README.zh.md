[English](README.md) | **中文**

# Aria Plugin

> **版本**: 1.7.2 | **发布日期**: 2026-03-20
>
> Claude Code 的 AI-DDD 方法论完整插件 — 28 个 Skills + 11 个 Agents + Hooks 系统

## 前置条件

- [Claude Code](https://claude.ai/code) 已安装并完成登录

## 安装

```bash
# 添加 marketplace
/plugin marketplace add 10CG/aria-plugin

# 安装 (Skills + Agents + Hooks 一起安装)
/plugin install aria@10CG-aria-plugin
```

## 包含内容

### Hooks 系统（自动触发）

| Hook 点 | 触发时机 | 功能 |
|--------|----------|------|
| `SessionStart` | 会话开始时 | 检测中断的工作流并提示恢复 |

**禁用 Hooks**：
```bash
# 设置环境变量
export ARIA_HOOKS_DISABLED=true

# 或禁用插件
/plugin disable aria@10CG-aria-plugin
```

### Skills（28 个面向用户 + 1 个内部）

**十步循环核心**
- state-scanner — 项目状态扫描与智能工作流推荐
- workflow-runner — 十步循环轻量编排器
- phase-a-planner — Phase A 规划阶段执行器
- phase-b-developer — Phase B 开发阶段执行器
- phase-c-integrator — Phase C 集成阶段执行器
- phase-d-closer — Phase D 收尾阶段执行器
- spec-drafter — 创建 OpenSpec proposal.md
- task-planner — 将 OpenSpec 分解为可执行任务
- progress-updater — 更新项目进度状态

**协作思考**
- brainstorm — AI 辅助的决策讨论和需求澄清（problem/requirements/technical 模式）

**Git 工作流**
- commit-msg-generator — 生成符合 Conventional Commits 的提交消息
- strategic-commit-orchestrator — 跨模块/批量/里程碑提交编排
- branch-manager — 分支创建与 PR 管理
- branch-finisher — 分支完成收尾

**开发工具**
- subagent-driver — 子代理驱动开发（SDD），支持两阶段代码审查
- agent-router — 任务到 Agent 的智能路由器
- tdd-enforcer — 强制执行 TDD 工作流
- requesting-code-review — 两阶段代码审查（Phase 1: 规范合规性 → Phase 2: 代码质量）

**架构文档**
- arch-common *（内部，非用户调用）* — 架构工具共享组件
- arch-search — 搜索架构文档
- arch-update — 更新架构文档
- arch-scaffolder — 从 PRD 生成架构骨架
- api-doc-generator — API 文档生成

**需求管理**
- requirements-validator — PRD/Story/Architecture 验证
- requirements-sync — Story ↔ UPM 状态同步
- forgejo-sync — Story ↔ Issue 同步
- openspec-archive — 归档已完成的 OpenSpec 变更（自动修正 CLI bug）

**基础设施**
- config-loader *（内部，非用户调用）* — 配置加载

**实验功能**
- agent-team-audit *（默认关闭，需通过 `.aria/config.json` 启用）* — 多 Agent 团队审计

### Agents（11 个）

**核心管理**
- tech-lead — 技术架构决策、任务规划、跨团队协调
- context-manager — 多 Agent 协作、上下文管理
- knowledge-manager — 知识库管理、文档同步
- code-reviewer — 两阶段代码审查（Phase 1: 规范合规性 + Phase 2: 代码质量）

**开发相关**
- backend-architect — 后端架构、API 设计、数据库模式
- mobile-developer — React Native/Flutter、离线同步
- qa-engineer — 质量保证、代码审查、测试策略

**专业领域**
- ai-engineer — LLM 应用、RAG 系统、Agent 编排
- api-documenter — OpenAPI 规范、SDK 生成
- ui-ux-designer — 界面设计、线框图、设计系统
- legal-advisor — 隐私政策、服务条款、GDPR 合规

## 使用方式

### Hooks 自动触发

安装后，hooks 会在关键节点自动触发：

```bash
# 会话开始 - 检测中断的工作流
# → 检查 .aria/workflow-state.json 中的未完成工作
```

### 手动调用

```bash
# Skills
/aria:state-scanner
/aria:spec-drafter
/aria:workflow-runner
/aria:brainstorm
/aria:requesting-code-review

# Agents
/aria:tech-lead
/aria:backend-architect
/aria:code-reviewer
/aria:knowledge-manager
```

## 相关项目

- [Aria](https://github.com/10CG/Aria) — Aria 主项目（方法论研究）
- [aria-standards](https://github.com/10CG/aria-standards) — Aria 方法论规范

## 许可证

MIT — [10CG Lab](https://github.com/10CG)

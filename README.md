# Aria Plugin

> Aria AI-DDD 方法论完整插件 - 23个 Skills + 9个 Agents + Hooks系统

## 安装

```bash
# 添加 marketplace
/plugin marketplace add 10CG/aria-plugin

# 安装
/plugin install aria@10CG-aria-plugin
```

## 包含内容

### Hooks 系统 (自动触发)

| Hook 点 | 触发时机 | 对应 Skill | 功能 |
|--------|----------|-----------|------|
| `SessionStart` | 会话开始时 | `state-scanner` | 自动状态扫描和环境检查 |
| `SessionEnd` | 会话结束时 | `progress-updater` | 检查进度更新和归档 |
| `PreToolUse` | 工具调用前 | `tdd-enforcer` | 强制执行 TDD 规则 |

**禁用 Hooks**：
```bash
# 设置环境变量
export ARIA_HOOKS_DISABLED=true

# 或在插件设置中禁用
/plugin disable aria@10cg-aria-plugin
```

### Skills (23个)

**十步循环核心**
- state-scanner - 项目状态扫描与智能工作流推荐
- workflow-runner - 十步循环轻量编排器
- phase-a-planner - Phase A 规划阶段执行器
- phase-b-developer - Phase B 开发阶段执行器
- phase-c-integrator - Phase C 集成阶段执行器
- phase-d-closer - Phase D 收尾阶段执行器
- spec-drafter - 创建 OpenSpec proposal.md
- task-planner - 将 OpenSpec 分解为可执行任务
- progress-updater - 更新项目进度状态

**Git 工作流**
- commit-msg-generator - 生成符合 Conventional Commits 的提交消息
- strategic-commit-orchestrator - 跨模块/批量/里程碑提交编排
- branch-manager - 分支创建与 PR 管理
- branch-finisher - 分支完成收尾

**开发工具**
- subagent-driver - 子代理驱动开发 (SDD)
- tdd-enforcer - 强制执行 TDD 工作流

**架构文档**
- arch-common - 架构工具共享组件
- arch-search - 搜索架构文档
- arch-update - 更新架构文档
- arch-scaffolder - 从 PRD 生成架构骨架
- api-doc-generator - API 文档生成

**需求管理**
- requirements-validator - PRD/Story/Architecture 验证
- requirements-sync - Story ↔ UPM 状态同步
- forgejo-sync - Story ↔ Issue 同步

### Agents (9个)

**核心管理**
- tech-lead - 技术架构决策、任务规划、跨团队协调
- context-manager - 多 Agent 协作、上下文管理
- knowledge-manager - 知识库管理、文档同步

**开发相关**
- backend-architect - 后端架构、API 设计、数据库模式
- mobile-developer - React Native/Flutter、离线同步
- qa-engineer - 质量保证、代码审查、测试策略

**专业领域**
- ai-engineer - LLM 应用、RAG 系统、Agent 编排
- api-documenter - OpenAPI 规范、SDK 生成
- ui-ux-designer - 界面设计、线框图、设计系统
- legal-advisor - 隐私政策、服务条款、GDPR 合规

## 使用方式

### Hooks 自动触发

安装后，hooks 会在关键节点自动触发：

```bash
# 会话开始 - 自动执行状态扫描
# → 等同于调用 /aria:state-scanner

# 编写代码 - 自动检查 TDD 规则
# → 等同于调用 /aria:tdd-enforcer

# 会话结束 - 自动检查进度
# → 等同于调用 /aria:progress-updater
```

### 手动调用 Skills

```bash
# Skills
/aria:state-scanner
/aria:spec-drafter
/aria:workflow-runner

# Agents
/aria:tech-lead
/aria:backend-architect
/aria:knowledge-manager
```

## 相关项目

- [aria-standards](https://forgejo.10cg.pub/10CG/aria-standards) - Aria 方法论规范
- [Aria](https://forgejo.10cg.pub/10CG/Aria) - Aria 主项目

## License

MIT - 10CG Lab

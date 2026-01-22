# Aria Agents

> Aria AI-DDD 方法论配套的 Claude Code Agents

## 安装方式

### Plugin Marketplace (推荐)

```bash
# 添加 marketplace
/plugin marketplace add 10CG/aria-agents

# 安装
/plugin install aria-agents@10cg-aria-agents
```

### 手动克隆到 Personal Agents

```bash
# Linux/macOS
git clone ssh://forgejo@forgejo.10cg.pub/10CG/aria-agents.git ~/.claude/agents

# Windows
git clone ssh://forgejo@forgejo.10cg.pub/10CG/aria-agents.git %USERPROFILE%\.claude\agents
```

## Agents 列表 (9个)

### 核心管理

| Agent | Model | 描述 |
|-------|-------|------|
| tech-lead | Opus | 技术架构决策、任务规划、跨团队协调 |
| context-manager | Opus | 多 Agent 协作、上下文管理 (10k+ token 必用) |
| knowledge-manager | Sonnet | 知识库管理、文档同步、AI-DDD 方法论专家 |

### 开发相关

| Agent | Model | 描述 |
|-------|-------|------|
| backend-architect | Sonnet | 后端架构、API 设计、数据库模式 |
| mobile-developer | Sonnet | React Native/Flutter、离线同步、推送通知 |
| qa-engineer | Sonnet | 质量保证、代码审查、测试策略 |

### 专业领域

| Agent | Model | 描述 |
|-------|-------|------|
| ai-engineer | Opus | LLM 应用、RAG 系统、Agent 编排 |
| api-documenter | Haiku | OpenAPI 规范、SDK 生成、开发者文档 |
| ui-ux-designer | Sonnet | 界面设计、线框图、设计系统 |
| legal-advisor | Haiku | 隐私政策、服务条款、GDPR 合规 |

## 使用方式

安装后，在 Claude Code 中可以直接调用：

```
请使用 aria-agents:tech-lead 规划这个功能的架构
```

或使用 Agent Skill 工具自动选择最合适的 Agent。

## SDD 模式集成

配合 `aria-skills` 的 `subagent-driver` 和 `agent-router`，实现：

1. **智能路由** - 根据任务类型自动选择 Agent
2. **Fresh Subagent** - 每个任务独立上下文
3. **任务间审查** - 自动代码质量检查

## 相关项目

- [aria-skills](https://forgejo.10cg.pub/10CG/aria-skills) - Aria 工作流 Skills
- [aria-standards](https://forgejo.10cg.pub/10CG/aria-standards) - Aria 方法论规范
- [Aria](https://forgejo.10cg.pub/10CG/Aria) - Aria 主项目

## License

MIT - 10CG Lab

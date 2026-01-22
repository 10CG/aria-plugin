# Aria Skills

> Aria AI-DDD 方法论配套的 Claude Code Skills

## 安装方式

### Plugin Marketplace (推荐)

```bash
# 添加 marketplace
/plugin marketplace add 10CG/aria-skills

# 安装
/plugin install aria-skills@10cg-aria-skills
```

### 手动克隆到 Personal Skills

```bash
# Linux/macOS
git clone ssh://forgejo@forgejo.10cg.pub/10CG/aria-skills.git ~/.claude/skills

# Windows
git clone ssh://forgejo@forgejo.10cg.pub/10CG/aria-skills.git %USERPROFILE%\.claude\skills
```

## Skills 列表 (23个)

### 十步循环核心

| Skill | 描述 |
|-------|------|
| state-scanner | 项目状态扫描与智能工作流推荐 |
| workflow-runner | 十步循环轻量编排器 |
| phase-a-planner | Phase A 规划阶段执行器 |
| phase-b-developer | Phase B 开发阶段执行器 |
| phase-c-integrator | Phase C 集成阶段执行器 |
| phase-d-closer | Phase D 收尾阶段执行器 |
| spec-drafter | 创建 OpenSpec proposal.md |
| task-planner | 将 OpenSpec 分解为可执行任务 |
| progress-updater | 更新项目进度状态 |

### Git 工作流

| Skill | 描述 |
|-------|------|
| commit-msg-generator | 生成符合 Conventional Commits 的提交消息 |
| strategic-commit-orchestrator | 跨模块/批量/里程碑提交编排 |
| branch-manager | 分支创建与 PR 管理 |
| branch-finisher | 分支完成收尾 |

### 开发工具

| Skill | 描述 |
|-------|------|
| subagent-driver | 子代理驱动开发 (SDD) |
| tdd-enforcer | 强制执行 TDD 工作流 |

### 架构文档

| Skill | 描述 |
|-------|------|
| arch-common | 架构工具共享组件 |
| arch-search | 搜索架构文档 |
| arch-update | 更新架构文档 |
| arch-scaffolder | 从 PRD 生成架构骨架 |
| api-doc-generator | API 文档生成 |

### 需求管理

| Skill | 描述 |
|-------|------|
| requirements-validator | PRD/Story/Architecture 验证 |
| requirements-sync | Story ↔ UPM 状态同步 |
| forgejo-sync | Story ↔ Issue 同步 |

## 使用方式

安装后，调用格式：

```
/aria-skills:state-scanner
/aria-skills:workflow-runner
/aria-skills:spec-drafter
```

## 相关项目

- [aria-agents](https://forgejo.10cg.pub/10CG/aria-agents) - Aria 专业 Agents
- [aria-standards](https://forgejo.10cg.pub/10CG/aria-standards) - Aria 方法论规范
- [Aria](https://forgejo.10cg.pub/10CG/Aria) - Aria 主项目

## License

MIT - 10CG Lab

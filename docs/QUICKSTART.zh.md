[English](QUICKSTART.md) | **中文**

# Aria 插件快速上手指南

10 分钟内从零开始体验 AI-DDD 工作流。

## 前置条件

- [Claude Code](https://claude.ai/code) 已安装并完成登录
- 一个 Git 仓库（已有项目或新项目均可）

## 第一步：安装

```bash
# 添加 marketplace
/plugin marketplace add 10CG/aria-plugin

# 安装
/plugin install aria@10CG-aria-plugin
```

验证安装：
```bash
/aria:state-scanner
```

你应该能看到项目状态分析和工作流推荐。

## 第二步：配置（可选）

创建 `.aria/config.json` 进行项目级配置：

```bash
mkdir -p .aria
```

```json
{
  "workflow": {
    "auto_proceed": false
  },
  "state_scanner": {
    "confidence_threshold": 90,
    "auto_execute_enabled": false
  },
  "tdd": {
    "strictness": "advisory"
  }
}
```

所有字段都是可选的 — 默认值适用于大多数项目。

## 第三步：你的第一个十步循环

### 场景：为项目添加一个新功能

**1. 扫描项目状态**

```
/aria:state-scanner
```

扫描器分析 Git 状态、变更和项目上下文，然后推荐工作流。

**2. 创建规范（Phase A）**

根据提示选择推荐的工作流。如果是添加功能，扫描器会引导你创建 OpenSpec：

```
/aria:spec-drafter
```

这会创建 `openspec/changes/<功能>/proposal.md` — 结构化地描述你要做什么、为什么做。

**3. 规划任务（Phase A）**

```
/aria:task-planner
```

将规范分解为可执行的任务，包含依赖关系和复杂度评估。

**4. 开发（Phase B）**

开始编码！扫描器会跟踪你的进度。需要提交时：

```
/aria:commit-msg-generator
```

根据暂存区变更生成符合 Conventional Commits 规范的提交消息。

**5. 集成（Phase C）**

```
/aria:state-scanner
```

扫描器检测到变更就绪，推荐集成流程，处理分支管理和 PR 创建。

**6. 收尾（Phase D）**

合并后，扫描器推荐归档已完成的规范：

```
/aria:state-scanner
```

你的 OpenSpec 移动到 `openspec/archive/`，进度随之更新。

## 功能一览

| 功能 | 使用方式 |
|------|---------|
| 项目状态分析 | `/aria:state-scanner` |
| 规范驱动开发 | `/aria:spec-drafter` |
| 任务分解 | `/aria:task-planner` |
| 提交消息生成 | `/aria:commit-msg-generator` |
| 代码审查 | `/aria:requesting-code-review` |
| 协作头脑风暴 | `/aria:brainstorm` |
| TDD 强制执行 | `/aria:tdd-enforcer` |
| Bug/功能反馈 | `/aria:report` |

## 核心概念

**十步循环**: 4 个阶段的结构化工作流（规划 → 开发 → 集成 → 收尾）。不需要每步都走 — 扫描器会推荐相关步骤。

**OpenSpec**: 轻量级规范格式 (`proposal.md`)，记录要做什么、为什么做、怎样算完成。Level 1（跳过）用于小修复，Level 2（最小）用于功能。

**Skills vs Agents**: Skills 是你调用的工作流（如 `/aria:state-scanner`）。Agents 是 Skills 委托的专业角色（如 `code-reviewer`、`tech-lead`）。

## 小贴士

- **从扫描器开始**: 总是用 `/aria:state-scanner` 开始。它告诉你在哪、该做什么。
- **跳过不需要的步骤**: 循环是灵活的。小 bug 修复？扫描器会推荐 `quick-fix`，完全跳过 Phase A。
- **需求不清时用头脑风暴**: 功能模糊时，`/aria:brainstorm` 帮你在写规范前理清思路。

## Standards（可选）

需要完整方法论（约定、模板、进度管理）的团队：

```bash
git submodule add https://github.com/10CG/aria-standards.git standards
```

详见 [aria-standards README](https://github.com/10CG/aria-standards)。

## 常见问题

| 问题 | 解决方案 |
|------|---------|
| Skills 没有出现 | 执行 `/reload-plugins` 或重启 Claude Code |
| 扫描器没有推荐 | 确保在 Git 仓库中且有变更 |
| 配置未加载 | 检查 `.aria/config.json` 是否为有效 JSON |
| 需要帮助 | `/aria:report question` 向维护团队提问 |

## 下一步

- 浏览所有 [28 个 Skills 和 11 个 Agents](../README.md)
- 了解 [Aria 方法论](https://github.com/10CG/Aria)
- 报告问题：`/aria:report`

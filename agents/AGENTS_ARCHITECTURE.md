# AI代理配置系统架构 v3.2

## 🤖 AI快速索引
- **模块类型**: AI代理配置管理系统
- **核心功能**: 管理9个专业AI代理的配置、权限和协作关系
- **关键文件**: settings.local.json, CLAUDE.md, CLAUDE.local.md
- **主要依赖**: Claude Code平台、MCP服务器、权限管理系统
- **更新状态**: 2026-01-22 v3.2 (新增 agent-router 智能路由)

## 🎯 核心价值
统一管理多AI代理协作开发环境，实现权限精准控制和任务智能分配

## 📁 快速导航
| 子模块 | 功能边界 | 文件数 | 详细文档 |
|--------|----------|--------|----------|
| 权限管理 | AI代理工具使用权限控制 | 1 | settings.local.json |
| 配置体系 | 全局和项目级AI指令管理 | 2 | CLAUDE.md系列 |
| MCP服务器 | 外部服务集成和能力扩展 | 9 | MCP配置 |
| 任务协作 | 多代理任务分配和执行 | - | 动态协作 |

## 💡 关键设计决策
1. **分层权限管理** - 全局权限+项目权限的双层控制机制
2. **专业代理分工** - 9个专业AI代理各司其职避免能力重叠
3. **MCP服务集成** - 通过MCP协议扩展AI代理外部能力
4. **配置文件分离** - 全局配置、项目配置、本地配置三级分离

## 📄 AI代理配置架构

### 核心AI代理体系 (9个专业代理)
**功能边界**: 专业化任务处理和协作开发
**核心价值**: 提升开发效率和代码质量

- **general-purpose** - 通用任务处理和复杂搜索
- **ui-ux-designer** - 界面设计和用户体验优化
- **tech-lead** - 技术架构决策和任务规划
- **qa-engineer** - 质量保证和代码审查
- **mobile-developer** - 移动端开发和优化
- **legal-advisor** - 法律合规和文档审查
- **knowledge-manager** - 知识库管理和文档同步
- **context-manager** - 上下文管理和长期任务协调
- **backend-architect** - 后端架构设计和API规范

### 权限控制系统
**功能边界**: 精确控制AI代理工具使用权限
**核心价值**: 安全性和操作精确性保障

- **allow列表**: 113个预授权命令和工具权限
- **deny列表**: 禁用命令控制机制
- **工具分类**: Bash命令、MCP服务器、WebFetch域名限制

### MCP服务器集成
**功能边界**: 外部服务能力扩展和集成
**核心价值**: 增强AI代理的专业能力

- **promptx系列**: 智能提示和记忆管理
- **shrimp-task-manager**: 任务规划和执行管理
- **context7**: 库文档和代码上下文分析
- **deepwiki**: 知识库深度检索
- **Sequential-Thinking**: 顺序思维推理
- **time-mcp**: 时间管理和计算

## ✅ 质量指标
- **代理响应效率**: <2秒任务分配
- **权限精确度**: 100%工具权限控制
- **协作成功率**: >95%多代理任务完成率
- **配置一致性**: 100%配置文件同步率

## 🔗 依赖关系
- **上级模块**: Claude Code平台核心系统
- **依赖模块**: 项目开发环境、Git版本控制、文档系统
- **被依赖**: 全栈开发流程、质量保证体系、知识管理系统

## 🚀 协作机制

### 任务智能分配
**工作流程**: 用户请求 → 任务分析 → 代理选择 → 执行协调 → 结果整合

### 代理间通信
**协作模式**: 任务传递、上下文共享、结果验证

### 配置同步策略
**同步层级**: 全局配置→项目配置→本地配置的层级覆盖机制

---

## 🔄 SDD 模式 (Subagent-Driven Development)

> **新增于 v3.1** - 集成 enforcement-mechanism-redesign 提案

### 概述

SDD 模式是 Aria v2.0 引入的子代理驱动开发模式，借鉴 Superpowers 的 Fresh Subagent 理念，为每个任务启动独立上下文的子代理。

### 核心组件

```
┌─────────────────────────────────────────────────────────────┐
│                    SDD 模式架构                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  subagent-driver (驱动器)                                    │
│  ├── 任务加载 (tasks.md / detailed-tasks.yaml)              │
│  ├── Fresh Subagent 启动                                    │
│  ├── 逐任务执行                                              │
│  └── 任务间代码审查                                          │
│                                                             │
│  隔离级别:                                                   │
│  ├── L1: 对话隔离 (简单任务)                                 │
│  ├── L2: 对话 + Worktree (中等复杂度)                        │
│  └── L3: 完全隔离 (高风险/并行)                              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Fresh Subagent 模式

```yaml
原理:
  - 每个任务启动新的子代理
  - 子代理拥有干净的上下文
  - 防止上下文污染和累积错误

生命周期:
  1. 启动: 加载任务描述 + 相关文件
  2. 执行: 完成单一任务
  3. 审查: 输出审查报告
  4. 结束: 释放上下文

优势:
  - 避免上下文累积导致的质量下降
  - 每个任务独立验证
  - 问题隔离，便于定位
```

### 任务间代码审查

```yaml
审查机制:
  timing: 每个任务完成后
  reviewer: 新的 Fresh Subagent

严重程度分类:
  Critical:
    description: "关键问题，必须修复"
    action: 阻塞后续任务
    examples:
      - 编译错误
      - 测试失败
      - 安全漏洞

  Major:
    description: "重要问题，建议修复"
    action: 警告，记录待处理
    examples:
      - 代码风格违规
      - 性能问题
      - 架构偏离

  Minor:
    description: "小问题，可忽略"
    action: 记录，不阻塞
    examples:
      - 命名建议
      - 文档补充
      - 优化建议
```

### 与专业代理集成

| 任务类型 | 推荐代理 | SDD 配置 |
|---------|---------|---------|
| 后端 API | backend-architect | L2 隔离 |
| 移动端 UI | mobile-developer | L2 隔离 |
| 代码审查 | qa-engineer | L1 隔离 |
| 架构文档 | knowledge-manager | L1 隔离 |
| 技术决策 | tech-lead | L2 隔离 |

### 相关技能

- [subagent-driver](../skills/subagent-driver/SKILL.md) - SDD 核心驱动
- [branch-manager](../skills/branch-manager/SKILL.md) - 隔离模式决策
- [branch-finisher](../skills/branch-finisher/SKILL.md) - 完成流程
- [agent-router](../skills/agent-router/SKILL.md) - Agent 智能路由 (v3.2 新增)

---

## 📊 覆盖统计
- **总配置文件数**: 3个核心配置文件
- **文档覆盖率**: 100%
- **主要技术栈**: Claude Code、MCP协议、JSON配置、Markdown文档

---

## 🤖 Agent 智能路由 (v3.2 新增)

> **设计目标**: 自动选择最合适的专业 Agent，减少手动选择负担

### 路由架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Agent 路由流程                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  subagent-driver (驱动器)                                               │
│       │                                                                 │
│       ├── 任务元数据                                                     │
│       │   ├── task_description                                        │
│       │   ├── related_files                                            │
│       │   └── task_type                                                │
│       │                                                                 │
│       ▼                                                                 │
│  agent-router (路由器)                                                  │
│       │                                                                 │
│       ├── 规则匹配                                                       │
│       │   ├── 文件路径 (FP-*)                                           │
│       │   ├── 任务类型 (TT-*)                                           │
│       │   └── 关键词匹配                                                │
│       │                                                                 │
│       ├── 置信度计算                                                     │
│       │   └── base_confidence + boosters                                │
│       │                                                                 │
│       └── 模式决策                                                       │
│           ├── auto (>= 0.9)                                              │
│           ├── recommend (默认)                                           │
│           └── manual (用户指定)                                          │
│       │                                                                 │
│       ▼                                                                 │
│  Fresh Subagent                                                         │
│       └── 使用选定的专业 Agent                                         │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 路由规则概览

**文件路径规则**:
- `backend/**/*` → backend-architect (0.90)
- `api/**/*` → backend-architect (0.95)
- `mobile/**/*` → mobile-developer (0.95)
- `docs/**/*` → knowledge-manager (0.85)
- `*.dart` → mobile-developer (0.90)

**任务类型规则**:
- `code-review` → qa-engineer (0.95)
- `architecture` → knowledge-manager (0.90)
- `llm` / `rag` → ai-engineer (0.95)
- `planning` → tech-lead (0.85)

### 三种路由模式

```yaml
自动模式 (auto):
  条件: confidence >= 0.9
  行为: 直接使用推荐的 Agent
  适用: 明确的任务类型

推荐模式 (recommend) - 默认:
  条件: confidence < 0.9 或多个候选
  行为: 展示 Top-3 供用户选择
  适用: 大多数场景

手动模式 (manual):
  条件: 用户显式指定
  行为: 使用用户指定的 Agent
  优先级: 最高 (覆盖其他模式)
```

### 配置示例

```yaml
# 项目级配置 (.claude/agent-router-config.json)
{
  "enabled": true,
  "default_mode": "recommend",
  "confidence_threshold": 0.9,
  "max_candidates": 3,
  "fallback_agent": "general-purpose"
}

# 任务级覆盖 (detailed-tasks.yaml)
tasks:
  - id: TASK-001
    description: "实现用户认证"
    agent: backend-architect  # 手动指定
```

### 执行示例

```yaml
示例 1: 自动匹配
  输入: "实现用户登录 REST API"
  文件: backend/api/auth.js
  输出: backend-architect (0.95)
  动作: 自动使用

示例 2: 推荐模式
  输入: "优化数据库查询"
  文件: backend/api/, database/
  输出:
    [1] backend-architect (0.85)
    [2] qa-engineer (0.65)
    [3] general-purpose (0.50)
  动作: 等待用户选择

示例 3: 手动指定
  输入: "用 tech-lead 规划重构"
  输出: tech-lead (手动)
  动作: 直接使用
```

### 与 SDD 集成

```yaml
完整 SDD + Agent Router 流程:

  subagent-driver (v1.2.0)
      │
      ├── 接收任务列表
      │
      ├── for each task:
      │   │
      │   ├── agent-router (新增)
      │   │   ├── 分析任务特征
      │   │   ├── 匹配路由规则
      │   │   └── 返回推荐的 Agent
      │   │
      │   ├── 确认 Agent (auto/recommend/manual)
      │   │
      │   └── 启动 Fresh Subagent
      │       └── 使用专业 Agent (而非 general-purpose)
      │
      └── 任务间审查
```

### 优势

| 之前 (v3.1) | 之后 (v3.2) |
|--------------|--------------|
| 默认使用 general-purpose | 智能选择专业 Agent |
| 手动指定 Agent | 自动推荐最佳 Agent |
| 不确定用哪个 Agent | 置信度评分指导选择 |
| 专业知识利用不足 | 充分利用专业 Agent |

---

**最后更新**: 2026-01-22
**版本**: v3.2
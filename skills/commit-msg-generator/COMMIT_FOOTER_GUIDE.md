# Git Commit Footer 字段使用指南

> **版本**: 1.0.0
> **适用**: commit-msg-generator v2.0.0+
> **状态**: 📚 标准指南（Standard Guide）
> **创建**: 2025-12-12

---

## 📋 文档概述

### 目的

本文档定义 Git Commit 消息中 **Footer 字段**的使用规范，包括 `Refs`、`Closes`、`BREAKING CHANGE` 等标准字段的使用决策和格式要求。

### 适用范围

- ✅ 所有 Git commit 消息（无论是否使用增强标记）
- ✅ 基于 Conventional Commits 规范的项目
- ✅ 需要关联 Issue、文档或 API 契约的提交

### 文档关系

```
本文档 (COMMIT_FOOTER_GUIDE.md)
  ↓ 被引用
├─ commit-msg-generator/SKILL.md (引用本指南的决策树)
├─ ENHANCED_MARKERS_SPEC.md (说明Footer位置，引用本指南)
└─ CLAUDE.md (引用本指南)
```

---

## 🎯 Footer 字段概述

### Footer 在 Commit 中的位置

```
<type>(<scope>): <subject>

<body>

[增强标记 - 可选]

<footer>
```

**说明**:
- Footer 位于 commit 消息的最后
- 如果有增强标记（🤖📋🔗），Footer 在增强标记之后
- 与前面内容保留一个空行

---

## 📎 Refs 字段规范

### 什么是 Refs

`Refs` 用于引用相关的文档、Issue 或其他资源，帮助理解提交的背景和上下文。

### 何时使用 Refs

| 场景 | 是否使用 | 格式 | 示例 |
|------|---------|------|------|
| **引用Issue** | ✅ 强烈推荐 | `Refs #123` | 实现Issue #123中提到的功能 |
| **引用规划文档** | ✅ 强烈推荐 | `Refs: path/to/doc.md` | 基于某个架构设计文档实现 |
| **引用API契约** | ✅ 强烈推荐 | `Refs: shared/contracts/api.yaml` | 实现或修改API时 |
| **引用多个资源** | ✅ 推荐 | `Refs #123, #456` 或多行 | 涉及多个Issue或文档 |
| **简单修改** | ❌ 不需要 | - | 修复typo、格式化等 |

### 决策树

```yaml
是否引用了规划文档？
  ├─ 是 → 添加 "Refs: 文档路径"
  │   示例: Refs: .claude/docs/SKILLS_OPTIMIZATION_ANALYSIS.md
  │
  └─ 否 → 检查是否关联Issue
      ├─ 是 → 添加 "Refs #123"
      │   注意: 如果是修复Issue，使用 "Closes #123"
      │
      └─ 否 → 检查是否涉及API契约
          ├─ 是 → 添加 "Refs: 契约路径"
          │   示例: Refs: shared/contracts/openapi/tasks.yaml
          │
          └─ 否 → 无需Refs（简单修改）
```

### 格式规范

**单个引用**:
```
Refs #123
Refs: path/to/document.md
Refs: shared/contracts/api.yaml
```

**多个引用（同类型）**:
```
Refs #123, #456
Refs: doc1.md, doc2.md
```

**多个引用（不同类型，推荐多行）**:
```
Refs #123
Refs: .claude/docs/ARCHITECTURE.md
Refs: shared/contracts/openapi/tasks.yaml
```

### 典型场景示例

#### 场景1: 基于规划文档实现功能

```
docs(skills): 优化commit-msg-generator文档结构

执行P0和P1优化，标准化YAML frontmatter并改进用户体验。

P0优化:
- 标准化license字段为字符串格式
- 统一allowed-tools为列表格式

P1优化:
- 添加快速导航章节
- 提取版本历史到CHANGELOG.md

🤖 Executed-By: tech-lead subagent
📋 Context: Phase1-Cycle2 skills-optimization
🔗 Module: skills

Refs: .claude/docs/SKILLS_OPTIMIZATION_RECOMMENDATIONS.md
```

#### 场景2: 实现Issue功能

```
feat(auth): 添加JWT用户认证功能

实现token生成和验证逻辑，支持用户登录和会话管理。

- 创建AuthService处理认证逻辑
- 实现token生成和刷新机制
- 添加中间件验证token

🤖 Executed-By: backend-architect subagent
📋 Context: Phase3-Cycle7 backend-api-development
🔗 Module: backend

Refs #123
```

#### 场景3: 实现API契约

```
feat(api): 实现任务优先级功能

Backend和Mobile协同实现任务优先级功能，包括API和UI。

Backend变更:
- 扩展Task模型添加priority字段
- 更新任务创建/更新API端点

Mobile变更:
- 更新任务模型支持优先级
- 实现优先级选择UI组件

🤖 Executed-By: tech-lead subagent
📋 Context: Phase4-Cycle2 cross-module-feature
🔗 Module: backend

Refs: shared/contracts/openapi/tasks.yaml
```

#### 场景4: 简单修改（无需Refs）

```
style(format): 统一代码缩进格式

使用prettier格式化代码。

🤖 Executed-By: general-purpose subagent
📋 Context: Phase2-Cycle3 code-cleanup
🔗 Module: backend
```

---

## 🔒 Closes 字段规范

### 什么是 Closes

`Closes` 用于自动关闭相关的 Issue。当提交被合并到默认分支时，引用的 Issue 会自动关闭。

### 何时使用 Closes

| 场景 | 使用 |
|------|------|
| **修复Bug（Issue）** | ✅ 必需 - `Closes #123` |
| **完成功能（Issue）** | ✅ 必需 - `Closes #456` |
| **部分实现** | ❌ 使用 `Refs #123` |
| **只是引用** | ❌ 使用 `Refs #123` |

### 格式规范

**单个Issue**:
```
Closes #123
```

**多个Issue**:
```
Closes #123, #456
```

或多行（推荐）:
```
Closes #123
Closes #456
```

### 典型场景示例

#### 场景1: 修复Bug

```
fix(api): 修复登录超时问题

修复token验证逻辑导致的登录超时问题。

- 调整token过期时间为30分钟
- 添加token刷新机制
- 增加错误日志

🤖 Executed-By: backend-architect subagent
📋 Context: Phase3-Cycle7 backend-bug-fix
🔗 Module: backend

Closes #456
```

#### 场景2: 完成功能

```
feat(mobile): 实现离线模式支持

实现本地数据缓存和离线同步功能。

- 添加SQLite本地存储
- 实现数据同步机制
- 添加离线检测逻辑

🤖 Executed-By: mobile-developer subagent
📋 Context: Phase4-Cycle5 mobile-offline-feature
🔗 Module: mobile

Closes #789
```

#### 场景3: 同时关闭多个Issue

```
feat(api): 完善用户管理API

实现用户查询、更新和删除功能。

- 添加用户查询API
- 实现用户更新功能
- 添加用户删除功能

🤖 Executed-By: backend-architect subagent
📋 Context: Phase3-Cycle8 user-management
🔗 Module: backend

Closes #123
Closes #124
Closes #125
```

---

## ⚠️ BREAKING CHANGE 规范

### 什么是 BREAKING CHANGE

`BREAKING CHANGE` 标记表示此次提交引入了不兼容的 API 变更，可能破坏现有代码。

### 何时使用 BREAKING CHANGE

| 场景 | 使用 |
|------|------|
| **API签名变更** | ✅ 必需 |
| **删除已有API** | ✅ 必需 |
| **修改响应格式** | ✅ 必需 |
| **修改默认行为** | ✅ 强烈推荐 |
| **内部重构（无影响）** | ❌ 不需要 |
| **添加新功能** | ❌ 不需要 |

### 格式规范

**在 Footer 中使用**:
```
BREAKING CHANGE: <详细说明>
```

**在 Subject 中标记**（可选，推荐）:
```
<type>(<scope>)!: <subject>
```

### 典型场景示例

#### 场景1: API响应格式变更

```
feat(api)!: 重构任务API响应格式

统一所有API响应格式，提供更好的错误处理和元数据支持。

- 所有API返回统一的响应结构
- 添加meta字段包含分页信息
- 添加errors字段包含详细错误

🤖 Executed-By: backend-architect subagent
📋 Context: Phase4-Cycle1 api-standardization
🔗 Module: backend

BREAKING CHANGE: 任务API响应格式变更
- 旧格式: { "tasks": [...] }
- 新格式: { "data": [...], "meta": {...} }
客户端需要更新API调用逻辑以适配新格式。

Refs: shared/contracts/openapi/tasks.yaml
```

#### 场景2: 删除已废弃API

```
refactor(api)!: 移除已废弃的v1 API端点

移除在v2.0中标记为废弃的v1 API端点。

- 删除 /api/v1/users 端点
- 删除 /api/v1/tasks 端点
- 更新文档移除v1引用

🤖 Executed-By: backend-architect subagent
📋 Context: Phase5-Cycle1 api-cleanup
🔗 Module: backend

BREAKING CHANGE: 移除v1 API端点
所有 /api/v1/* 端点已被移除，请使用 /api/v2/* 端点。
迁移指南: docs/API_MIGRATION_V1_TO_V2.md

Refs: docs/API_MIGRATION_V1_TO_V2.md
```

---

## 🔀 混合使用 Footer 字段

### 推荐顺序

```
<增强标记 - 可选>

BREAKING CHANGE: <说明>
Closes #123
Refs #456
Refs: path/to/doc.md
```

**规则**:
1. `BREAKING CHANGE` 放在最前面（最重要）
2. `Closes` 其次（影响Issue状态）
3. `Refs` 最后（仅引用）

### 完整示例

```
feat(api)!: 重构认证系统并修复安全问题

重构整个认证系统，修复JWT token验证漏洞。

变更内容:
- 重新设计token生成逻辑
- 添加refresh token机制
- 修复token验证绕过漏洞
- 统一错误响应格式

🤖 Executed-By: backend-architect subagent
📋 Context: Phase3-Cycle9 security-enhancement
🔗 Module: backend

BREAKING CHANGE: 认证API签名变更
- 登录API返回格式变更
- token验证逻辑更新
- 需要更新客户端SDK到v2.0+

Closes #567
Refs #568
Refs: .claude/docs/SECURITY_AUDIT.md
Refs: shared/contracts/openapi/auth.yaml
```

---

## 📚 参考文档

### 相关文档

| 文档 | 关系 | 位置 |
|------|------|------|
| **ENHANCED_MARKERS_SPEC.md** | 定义增强标记格式 | `.claude/skills/commit-msg-generator/ENHANCED_MARKERS_SPEC.md` |
| **commit-msg-generator SKILL.md** | 使用本指南生成Footer | `.claude/skills/commit-msg-generator/SKILL.md` |
| **CLAUDE.md** | 引用本指南 | `CLAUDE.md` |

### 外部标准

- [Conventional Commits](https://www.conventionalcommits.org/) - Footer 格式基础
- [GitHub Linking Issues](https://docs.github.com/en/issues/tracking-your-work-with-issues/linking-a-pull-request-to-an-issue) - Closes 关键词
- [Semantic Versioning](https://semver.org/) - BREAKING CHANGE 影响

---

## 🔍 常见问题（FAQ）

### Q1: Refs 和 Closes 有什么区别？

**A**:
- `Refs #123`: 仅引用Issue，不影响Issue状态
- `Closes #123`: 提交合并后自动关闭Issue

### Q2: 何时必须使用 Footer？

**A**:
- `BREAKING CHANGE`: 有不兼容变更时必需
- `Closes`: 修复或完成Issue时必需
- `Refs`: 推荐使用，但不强制

### Q3: Footer 字段的顺序重要吗？

**A**: 推荐按重要性排序（BREAKING CHANGE → Closes → Refs），但不强制。

### Q4: 可以省略 Footer 吗？

**A**: 可以。简单的提交（如格式化、typo修复）无需Footer。

### Q5: 如何引用多个不同类型的资源？

**A**: 使用多行，每行一个引用：
```
Closes #123
Refs #456
Refs: docs/DESIGN.md
```

### Q6: Refs 后面用冒号还是不用？

**A**:
- 引用Issue: `Refs #123` (无冒号)
- 引用文件: `Refs: path/to/file.md` (有冒号)

---

**最后更新**: 2025-12-12
**文档维护者**: tech-lead
**状态**: 🔒 Active（活跃维护中）

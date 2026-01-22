---
name: commit-msg-generator
description: |
  根据Git暂存区的更改生成符合Conventional Commits规范的commit消息。
  支持可选的增强标记(Agent/Context/Module)，用于复杂场景的提交追溯。

  使用场景：准备提交代码时生成规范消息、自动总结代码变更。

  兼容性: 完全向后兼容v1.0.0
---

# Git Commit 消息生成器

> **版本**: 2.0.0 | **兼容性**: 向后兼容v1.0.0

## 🚀 快速开始

### 我应该使用这个 skill 吗？

**✅ 使用场景**:
- 准备提交代码时需要生成规范的 commit 消息
- 希望遵循 Conventional Commits 标准
- 被 strategic-commit-orchestrator 调用生成增强消息

**❌ 不使用场景**:
- 需要分组提交多个变更 → 使用 `strategic-commit-orchestrator`

### 两种使用模式

| 模式 | 触发方式 | 输出格式 | 适用场景 |
|------|---------|---------|---------|
| **独立模式** | 用户直接调用 | 简洁 commit 消息 | 日常开发提交 |
| **编排模式** | orchestrator 调用 | 包含增强标记 | 多模块协同提交 |

---

## 核心功能

- 分析Git暂存区变更
- 生成符合 Conventional Commits 规范的消息
- 自动确定变更类型（feat, fix, docs等）
- 智能识别 Scope 范围
- 支持中英文双语

### v2.0.0 增强特性
- **可选增强标记**: Agent/Context/Module 标记（orchestrator 调用时）
- **完全向后兼容**: 不传参数时行为与 v1.0.0 完全一致
- **灵活集成**: 可独立使用或被 orchestrator 编排

## 可选参数 (v2.0.0)

| 参数 | 类型 | 示例 | 效果 |
|------|------|------|------|
| `subagent_type` | string | "backend-architect" | 添加 🤖 Executed-By 标记 |
| `phase_cycle` | string | "Phase3-Cycle7" | 添加到 📋 Context 标记 |
| `module` | string | "backend", "mobile" | 添加 🔗 Module 标记 |
| `context` | string | 自定义上下文 | 添加到 📋 Context 标记 |

**注意**: 所有参数均为可选，不传参数时与 v1.0.0 行为一致。

**🔒 格式规范**: [ENHANCED_MARKERS_SPEC.md](./ENHANCED_MARKERS_SPEC.md)

---

## Conventional Commits 快速参考

### 消息格式

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Type 类型（常用）

| Type | 说明 | 示例 |
|------|------|------|
| **feat** | 新功能 | `feat(auth): 添加JWT认证` |
| **fix** | Bug修复 | `fix(api): 修复登录超时问题` |
| **docs** | 文档更新 | `docs(readme): 更新安装说明` |
| **refactor** | 重构 | `refactor(utils): 优化日期处理` |
| **test** | 测试相关 | `test(unit): 添加单元测试` |

**完整类型**: perf, style, build, ci, chore, revert 等，详见 [Conventional Commits](https://www.conventionalcommits.org/)

### Scope 范围

标明变更影响的范围（模块、文件、功能等）

**示例**: `feat(auth)`, `fix(api/users)`, `docs(readme)`

### Subject 主题

**规则**:
- 简洁描述（≤50字符）
- 使用祈使句
- 不以句号结尾
- 首字母小写

### Body 正文（可选）

**何时写**: 变更原因复杂、影响范围大、有重要技术细节

**内容**: 为什么做（WHY）、影响和后果、与之前行为对比

### Footer 页脚（可选）

- `BREAKING CHANGE:` - 破坏性变更
- `Closes #123` - 关联关闭Issue
- `Refs #456` - 引用相关Issue或文档

**📎 完整Footer使用指南**: [COMMIT_FOOTER_GUIDE.md](./COMMIT_FOOTER_GUIDE.md)
- Refs 使用决策树
- Closes 和 BREAKING CHANGE 规范
- 典型场景示例

---

## 执行流程

1. 检查暂存区: `git diff --cached --name-status`
2. 查看变更详情: `git diff --cached`
3. 分析变更类型，确定 type 和 scope
4. 生成符合规范的 commit 消息
5. 添加增强标记（仅 orchestrator 调用时）

---

## 示例

### 示例1: 新功能（独立模式）

**暂存区**:
```
A  backend/src/routes/auth.py
M  backend/src/app.py
```

**生成的消息**:
```
feat(auth): 添加JWT用户认证功能

- 实现token生成和验证逻辑
- 添加登录和注册API端点
- 集成到主应用路由

Refs #123
```

### 示例2: 增强消息（编排模式）

```
feat(auth): 添加JWT用户认证功能

- 实现token生成和验证逻辑
- 添加登录和注册API端点

🤖 Executed-By: backend-architect subagent
📋 Context: Phase3-Cycle7 Backend API完善
🔗 Module: backend

Refs #123
```

### 示例3: Breaking Change

```
feat(api)!: 重构任务API结构

BREAKING CHANGE: 任务API响应格式变更
- 旧格式: { "tasks": [...] }
- 新格式: { "data": [...], "meta": {...} }

客户端需要更新API调用逻辑。
```

---

## 最佳实践

### Subject 写作
- ✅ 祈使句: "添加功能" ❌ "添加了功能"
- ✅ 简洁: ≤50字符 ❌ 啰嗦冗长
- ✅ 小写开头 ❌ 大写开头
- ✅ 无句号 ❌ "添加功能。"

### Body 编写
- ✅ 复杂变更需解释
- ✅ Breaking Change 必须说明
- ✅ 重要架构决策
- ❌ 简单格式化、文档更新

### Issue 关联
- `Closes #123` - 自动关闭
- `Refs #456` - 引用
- `Closes #123, #456` - 多个

### 避免无意义消息
- ❌ "update", "fix bug", "改了一些东西"
- ✅ "fix(auth): 修复登录超时问题"

---

## 特殊场景

### Breaking Change
```
<type>(<scope>)!: <subject>

BREAKING CHANGE: <详细说明>
```

### Hotfix
```
fix(critical): 修复生产环境紧急问题

紧急修复说明。

Closes #999
```

### 回退提交
```
revert: 回退"feat(auth): 添加OAuth支持"

This reverts commit abc1234.
回退原因说明。
```

---

## 输出格式

**详细规范**: [ENHANCED_MARKERS_SPEC.md](./ENHANCED_MARKERS_SPEC.md)

**独立模式**:
```
<type>(<scope>): <subject>

<body>

<footer>
```

**编排模式**:
```
<type>(<scope>): <subject>

<body>

🤖 Executed-By: <subagent> subagent

📋 Context: <phase_cycle> <context>

🔗 Module: <module>

<footer>
```

**注意**:
- 增强标记（🤖📋🔗）在 `<body>` 和 `<footer>` 之间
- 标记之间各保留一个空行（提升可读性）
- `<footer>` 包含 `Closes #123`、`Refs #456` 等（可选）
- Footer 详细规范: [COMMIT_FOOTER_GUIDE.md](./COMMIT_FOOTER_GUIDE.md)

---

## 使用方法

### 独立使用
用户直接调用，无需参数，生成标准commit消息。

### Orchestrator调用
由 `strategic-commit-orchestrator` 调用，传递可选参数，生成增强消息。

---

## 参考资源

### 核心规范
- [Conventional Commits](https://www.conventionalcommits.org/) - 官方标准
- [Angular Commit 规范](https://github.com/angular/angular/blob/master/CONTRIBUTING.md#commit)

### 相关文档
- [COMMIT_FOOTER_GUIDE.md](./COMMIT_FOOTER_GUIDE.md) - Footer 字段使用指南
- [ENHANCED_MARKERS_SPEC.md](./ENHANCED_MARKERS_SPEC.md) - 增强标记格式
- [CHANGELOG.md](./CHANGELOG.md) - 版本历史
- [EXAMPLES.md](./EXAMPLES.md) - 完整示例

### 工具推荐
- [commitizen](https://github.com/commitizen/cz-cli) - 交互式工具
- [commitlint](https://commitlint.js.org/) - 消息验证

---

**最后更新**: 2025-12-11
**Skill版本**: 2.0.1 (精简优化)

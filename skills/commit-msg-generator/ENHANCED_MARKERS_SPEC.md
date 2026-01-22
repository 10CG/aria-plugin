# Git Commit 增强标记格式规范

> **版本**: 1.3.0
> **适用**: commit-msg-generator v2.0.0+
> **状态**: 🔒 权威定义（Authoritative Specification）
> **更新**: 2025-12-12 - 增强标记之间添加空行，提升可读性

---

## 📋 文档概述

### 目的

本文档定义 Git Commit 消息中**增强标记**（Enhanced Markers）的标准格式，是项目中唯一权威的格式定义文档。

### 适用范围

- ✅ 通过 `strategic-commit-orchestrator` skill 生成的 commit 消息
- ✅ 需要追溯执行上下文的提交（多模块协同、阶段性成果等）
- ❌ 手动创建的 commit（禁止手动添加增强标记）
- ❌ 日常简单提交（使用独立模式，无增强标记）

### 文档关系

```
本文档 (ENHANCED_MARKERS_SPEC.md)
  ↓ 被引用
├─ commit-msg-generator/SKILL.md (使用本规范)
├─ strategic-commit-orchestrator/SKILL.md (生成时遵循本规范)
└─ CLAUDE.md (引用本规范)

相关文档:
├─ COMMIT_FOOTER_GUIDE.md (Footer 字段详细指南)
└─ EXAMPLES.md (完整示例)
```

---

## 🎯 增强标记概述

### 三种标记

| 标记 | Emoji | 作用 | 必需性 |
|------|-------|------|--------|
| **Executed-By** | 🤖 | 标识执行该提交的 subagent 类型 | 可选 |
| **Context** | 📋 | 标识项目阶段和上下文描述 | 可选 |
| **Module** | 🔗 | 标识变更所属的模块 | 可选 |

### 在 Commit 中的位置

```
<type>(<scope>): <subject>

<body>

🤖 Executed-By: <subagent_type> subagent

📋 Context: <phase_cycle> <context>

🔗 Module: <module>

<footer>
```

**关键规则**:
- 增强标记位于 `<body>` 之后，`<footer>` 之前
- 与 body 之间保留一个空行
- 三个标记之间各保留一个空行（提升可读性）
- 与 footer 之间保留一个空行
- 顺序固定：Executed-By → Context → Module → Footer

---

## 📐 格式规范详解

### 1. 🤖 Executed-By (执行者标记)

#### 格式定义

```
🤖 Executed-By: <subagent_type> subagent
```

#### 组成部分

| 部分 | 说明 | 示例 |
|------|------|------|
| `🤖` | Robot emoji（U+1F916） | 🤖 |
| `Executed-By:` | 固定标识符，注意大小写和冒号 | `Executed-By:` |
| `<subagent_type>` | Subagent 类型名称 | `backend-architect` |
| `subagent` | 固定后缀 | `subagent` |

#### 格式约束

| 约束项 | 规则 |
|--------|------|
| **Emoji** | ✅ 必须使用 🤖（robot face） |
| **空格** | ✅ Emoji 后一个空格<br>✅ 冒号后一个空格<br>✅ subagent_type 和 "subagent" 之间一个空格 |
| **subagent_type** | ✅ 使用 kebab-case（小写+连字符）<br>✅ 后面必须跟 "subagent" |
| **大小写** | ✅ "Executed-By" 首字母大写<br>✅ subagent_type 使用 kebab-case<br>✅ "subagent" 全部小写 |

#### 有效的 subagent_type

```yaml
常用类型:
  - backend-architect
  - mobile-developer
  - frontend-developer
  - tech-lead
  - qa-engineer
  - ui-ux-designer
  - knowledge-manager
  - api-documenter
  - legal-advisor
```

#### 示例对比

```diff
✅ 正确示例:
+ 🤖 Executed-By: backend-architect subagent
+ 🤖 Executed-By: tech-lead subagent
+ 🤖 Executed-By: knowledge-manager subagent

❌ 错误示例:
- 🤖 Executed-By: backend-architect       (缺少 "subagent" 后缀)
- 🤖 Executed-By: backend-architect agent (错误后缀)
- 🤖 Executed-By: Backend-Architect subagent  (大小写错误)
- 🤖Executed-By: backend-architect subagent   (缺少空格)
- 🤖 Executed-By:backend-architect subagent   (冒号后缺少空格)
- 🤖 Executed-By: backend-architectsubagent   (缺少空格)
- 🛠️ Executed-By: backend-architect subagent  (emoji 错误)
```

---

### 2. 📋 Context (上下文标记)

#### 格式定义

```
📋 Context: <phase_cycle> <context>
```

#### 组成部分

| 部分 | 说明 | 示例 |
|------|------|------|
| `📋` | Clipboard emoji（U+1F4CB） | 📋 |
| `Context:` | 固定标识符 | `Context:` |
| `<phase_cycle>` | 阶段周期标识 | `Phase3-Cycle7` |
| `<context>` | 上下文描述 | `Backend API完善` 或 `backend-api-development` |

#### 格式约束

| 约束项 | 规则 |
|--------|------|
| **Emoji** | ✅ 必须使用 📋（clipboard） |
| **phase_cycle 格式** | ✅ 格式: `Phase[N]-Cycle[M]`<br>✅ N、M 为正整数<br>✅ "Phase" 和 "Cycle" 首字母大写<br>✅ 使用连字符 `-` 连接 |
| **分隔符** | ✅ phase_cycle 和 context 之间一个空格<br>❌ 不使用 ` - `（空格-空格）<br>❌ 不使用 `:`、`_`、`/` 等其他分隔符 |
| **context** | ✅ 中英文均可<br>✅ 可使用 kebab-case 或自然语言<br>✅ 简洁描述（建议 50 字符内） |

#### phase_cycle 来源

```yaml
类型A - 子模块功能变更:
  来源: 读取子模块 UPM 文档的 UPMv2-STATE
  示例: Phase3-Cycle7 (实际的开发阶段)

类型B - 主项目基础设施变更:
  来源: 逻辑 Phase/Cycle（描述工作阶段）
  示例: Phase1-Cycle1 (架构文档)
        Phase1-Cycle2 (Skills优化)

类型C - 跨模块协同变更:
  来源: 读取主模块 UPM 文档
  示例: Phase4-Cycle2 (从 Backend UPM 读取)
```

#### 示例对比

```diff
✅ 正确示例:
+ 📋 Context: Phase3-Cycle7 Backend API完善
+ 📋 Context: Phase1-Cycle2 skills-p2-optimization
+ 📋 Context: Phase4-Cycle1 Mobile UI implementation
+ 📋 Context: Phase2-Cycle5 数据库架构优化
+ 📋 Context: Phase3-Cycle5 backend-api-development

❌ 错误示例:
- 📋 Context: Phase3-Cycle7 - Backend API完善     (多了 " - " 分隔符)
- 📋 Context: Phase3-Cycle7: Backend API完善      (分隔符错误)
- 📋 Context: Phase3-Cycle7_Backend API完善       (分隔符错误)
- 📋 Context: Phase3-Cycle7/Backend API完善       (分隔符错误)
- 📋 Context: phase3-cycle7 Backend API完善       (大小写错误)
- 📋 Context: P3-C7 Backend API完善               (缩写错误)
- 📋Context: Phase3-Cycle7 Backend API完善        (缺少空格)
- 📊 Context: Phase3-Cycle7 Backend API完善       (emoji 错误)
```

---

### 3. 🔗 Module (模块标记)

#### 格式定义

```
🔗 Module: <module>
```

#### 组成部分

| 部分 | 说明 | 示例 |
|------|------|------|
| `🔗` | Link emoji（U+1F517） | 🔗 |
| `Module:` | 固定标识符 | `Module:` |
| `<module>` | 模块名称 | `backend` |

#### 格式约束

| 约束项 | 规则 |
|--------|------|
| **Emoji** | ✅ 必须使用 🔗（link） |
| **module** | ✅ 使用项目定义的模块名称<br>✅ 全部小写<br>✅ 可使用路径格式表示逻辑模块 |

#### 有效的模块名称

```yaml
子模块:
  - backend         # Backend 子模块
  - mobile          # Mobile 子模块
  - frontend        # Frontend 子模块
  - shared          # Shared 子模块
  - standards       # Standards 子模块
  - agents          # Agents 子模块

主项目逻辑模块:
  - skills          # .claude/skills/ 相关
  - .claude/docs    # .claude/docs/ 相关
  - docs            # docs/ 根目录文档
  - scripts         # scripts/ 脚本

特殊情况:
  - 跨模块变更可使用主模块名称
```

#### 示例对比

```diff
✅ 正确示例:
+ 🔗 Module: backend
+ 🔗 Module: mobile
+ 🔗 Module: skills
+ 🔗 Module: .claude/docs

❌ 错误示例:
- 🔗 Module: Backend              (大小写错误)
- 🔗 Module: backend-module       (多余后缀)
- 🔗Module: backend               (缺少空格)
- 🔗 Module:backend               (冒号后缺少空格)
- 🔖 Module: backend              (emoji 错误)
```

---

## 🎓 完整示例

### 示例1: 子模块功能开发（类型A）

```
feat(auth): 添加JWT用户认证功能 / Add JWT user authentication

实现token生成和验证逻辑，支持用户登录和会话管理。

- 创建AuthService处理认证逻辑
- 实现token生成和刷新机制
- 添加中间件验证token
- 添加单元测试覆盖核心逻辑

🤖 Executed-By: backend-architect subagent

📋 Context: Phase3-Cycle7 Backend API authentication implementation

🔗 Module: backend

Refs #123
```

### 示例2: 主项目基础设施变更（类型B）

```
docs(skills): 优化commit-msg-generator文档结构（P0+P1） / Optimize commit-msg-generator doc structure (P0+P1)

执行P0和P1优化，标准化YAML frontmatter并改进用户体验。

P0优化:
- 标准化license字段为字符串格式
- 统一allowed-tools为列表格式
- 添加metadata对象（version, updated, compatibility）

P1优化:
- 添加快速导航章节（我应该使用吗？快速开始）
- 提取版本历史到CHANGELOG.md
- 改进文档结构和可读性

🤖 Executed-By: tech-lead subagent

📋 Context: Phase1-Cycle2 skills-p0-p1-optimization

🔗 Module: skills

Refs: .claude/docs/SKILLS_OPTIMIZATION_ANALYSIS.md
```

### 示例3: 跨模块协同变更（类型C）

```
feat(api): 实现任务优先级功能（Backend+Mobile） / Implement task priority feature (Backend+Mobile)

Backend和Mobile协同实现任务优先级功能，包括API和UI。

Backend变更:
- 扩展Task模型添加priority字段
- 更新任务创建/更新API端点
- 添加按优先级排序的查询接口

Mobile变更:
- 更新任务模型支持优先级
- 实现优先级选择UI组件
- 添加按优先级过滤功能

🤖 Executed-By: tech-lead subagent

📋 Context: Phase4-Cycle2 cross-module-task-priority-feature

🔗 Module: backend

Refs: shared/contracts/openapi/tasks.yaml
```

---

## 📎 Footer 字段

增强标记之后是可选的 Footer 字段，用于引用 Issue、文档或声明破坏性变更。

**Footer 字段包括**:
- `Refs #123` 或 `Refs: path/to/doc.md` - 引用相关资源
- `Closes #123` - 关闭Issue
- `BREAKING CHANGE: ...` - 声明破坏性变更

**📚 完整 Footer 使用指南**: 请参考 [COMMIT_FOOTER_GUIDE.md](./COMMIT_FOOTER_GUIDE.md)
- Footer 字段的详细使用规范
- Refs 使用决策树
- Closes 和 BREAKING CHANGE 规范
- 典型场景示例

---

## ⚠️ 使用限制与注意事项

### 🚫 禁止手动添加

```diff
❌ 错误做法:
- 手动编写 commit 消息时添加增强标记
- 复制粘贴增强标记到 commit 消息中
- 使用 git commit -m 直接写入增强标记

✅ 正确做法:
- 通过 strategic-commit-orchestrator skill 生成提交
- Skill 自动调用 commit-msg-generator 并传递参数
- 增强标记由 skill 自动生成，确保格式正确
```

### 📋 何时使用增强标记

```yaml
✅ 应该使用（通过 orchestrator）:
  - 多模块协同提交
  - 阶段性成果提交
  - 需要追溯执行上下文的重要提交
  - Skills 开发/优化提交
  - 架构文档变更

❌ 不应该使用（独立模式）:
  - 日常简单提交（修复typo、格式化等）
  - 单文件小修改
  - WIP 提交
  - 快速迭代中的临时提交
```

### 🔒 格式一致性保证

1. **单一真相来源**: 本文档是增强标记格式的唯一权威定义
2. **工具强制**: 通过 skill 生成，避免手动错误
3. **文档引用**: 其他文档应引用本文档，不应重新定义格式

---

## 📚 参考文档

### 相关文档

| 文档 | 关系 | 位置 |
|------|------|------|
| **COMMIT_FOOTER_GUIDE.md** | Footer 字段详细指南 | `.claude/skills/commit-msg-generator/COMMIT_FOOTER_GUIDE.md` |
| **commit-msg-generator SKILL.md** | 使用本规范生成提交消息 | `.claude/skills/commit-msg-generator/SKILL.md` |
| **strategic-commit-orchestrator SKILL.md** | 调用 commit-msg-generator 并传递参数 | `.claude/skills/strategic-commit-orchestrator/SKILL.md` |
| **CLAUDE.md** | 引用本规范，提供快速参考 | `CLAUDE.md` |

### 外部标准

- [Conventional Commits](https://www.conventionalcommits.org/)
- [Semantic Versioning](https://semver.org/)
- [Keep a Changelog](https://keepachangelog.com/)

---

## 📝 版本历史

**当前版本**: v1.3.0 (2025-12-12)

**版本列表**:
- **v1.3.0** (2025-12-12) - 增强标记之间添加空行，提升可读性
- **v1.2.0** (2025-12-12) - Footer规范独立到 COMMIT_FOOTER_GUIDE.md
- **v1.1.0** (2025-12-12) - 已废弃，添加Footer字段规范
- **v1.0.1** (2025-12-10) - 修正格式规范（subagent后缀、Context空格）
- **v1.0.0** (2025-12-10) - 初始版本

**📚 完整变更历史**: 请查看 [CHANGELOG.md](./CHANGELOG.md#enhanced_markers_specmd-变更历史)

---

## 🔍 常见问题（FAQ）

### Q1: 为什么不能手动添加增强标记？

**A**: 增强标记需要严格的格式约束，手动添加容易出错。通过 skill 自动生成可以：
- ✅ 保证格式一致性
- ✅ 自动读取 UPM 获取正确的 Phase/Cycle
- ✅ 确保与项目标准对齐

### Q2: 增强标记是必需的吗？

**A**: 不是。commit-msg-generator 支持两种模式：
- **独立模式**（默认）: 无增强标记，用于日常提交
- **编排模式**: 有增强标记，用于复杂/协同提交

### Q3: 如果格式不正确会怎样？

**A**:
- Git 仍会接受提交（增强标记只是元数据）
- 但会导致：
  - 可追溯性降低（难以定位提交上下文）
  - 文档一致性问题（其他开发者可能混淆）
  - 自动化工具解析失败（如统计脚本）

### Q4: 为什么 Executed-By 必须有 "subagent" 后缀？

**A**:
- 语义明确性：明确标识这是一个 subagent 执行的提交
- 区别性：与人类开发者的提交区分开
- 一致性：项目统一使用此格式，便于识别和统计

### Q5: 为什么 Context 不使用 " - " 分隔符？

**A**:
- 简洁性：phase_cycle 和 context 语义上紧密相关，直接空格连接更简洁
- 可读性：减少符号干扰，提高可读性
- 历史原因：项目早期确立的格式标准

### Q6: 如何验证我的增强标记格式正确？

**A**: 对比本文档的示例：
1. 检查 Emoji 是否正确（🤖 📋 🔗）
2. 检查空格位置（emoji 后、冒号后）
3. 检查是否有 "subagent" 后缀
4. 检查 Context 是否只有一个空格分隔（无 " - "）

---

**最后更新**: 2025-12-12
**文档维护者**: tech-lead
**状态**: 🔒 Active（活跃维护中）

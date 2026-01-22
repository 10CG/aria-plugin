# Changelog - commit-msg-generator

All notable changes to the commit-msg-generator skill will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### ENHANCED_MARKERS_SPEC.md 变更历史

#### v1.3.0 - 2025-12-12

**优化原因**:
- 用户反馈：Cursor Git 界面中增强标记显示为"粘在一起"
- 标记之间没有空行导致视觉可读性差
- Emoji 连续排列在某些界面中渲染不佳

**格式优化**:
- ✅ 增强标记之间添加空行（原来是连续三行，现在每个标记间隔一个空行）
- ✅ 更新关键规则：三个标记之间各保留一个空行（提升可读性）
- ✅ 更新所有完整示例（示例1、2、3）使用新格式
- ✅ 保持与 body 和 footer 之间的空行不变

**影响**:
- 提升在 Cursor、GitHub、GitLab 等所有 Git 界面中的可读性
- 提交消息略长（增加 2 个空行）
- 更符合用户视觉习惯和常见的 Git commit 实践

**迁移指南**:
- 旧格式（v1.2.0 及之前）仍然有效，但不推荐
- 新提交应使用新格式（标记之间有空行）
- commit-msg-generator skill 将自动生成新格式

#### v1.2.0 - 2025-12-12

**重构原因**:
- 用户反馈：Footer 规范应该独立文件，符合单一职责原则
- ENHANCED_MARKERS_SPEC.md 应只关注增强标记，不包含标准 Footer 规范

**重大变更**:
- ✅ 创建独立文件 COMMIT_FOOTER_GUIDE.md 专门定义 Footer 规范
- ✅ 从 ENHANCED_MARKERS_SPEC.md 移除 Footer 详细规范章节
- ✅ 添加对 COMMIT_FOOTER_GUIDE.md 的引用

**影响**:
- 文档职责更清晰：ENHANCED_MARKERS_SPEC.md 只定义增强标记
- Footer 规范独立维护，便于复用和扩展
- 文档更简洁（从 615 行减少到约 500 行）

#### v1.1.0 - 2025-12-12 (已废弃)

**优化原因**:
- 用户反馈：AI难以判断何时需要添加Refs字段
- 用户反馈：Footer格式定义与实际示例不一致，导致换行问题

**新增内容**:
- ✅ 添加完整的 Footer 字段规范章节（后移至 COMMIT_FOOTER_GUIDE.md）
- ✅ Refs字段使用决策树（何时使用、何时不用）
- ✅ 典型场景示例（规划文档、Issue、API契约等4种场景）

**格式修正**:
- ✅ 修正Footer位置：增强标记在 body 之后、footer 之前
- ✅ 明确空行规则：body与增强标记间空一行，增强标记与footer间空一行
- ✅ 更新关键规则说明，避免格式混淆

#### v1.0.1 - 2025-12-10

**修正原因**:
- 用户指出原始 CLAUDE.md 格式才是正确的
- v1.0.0 错误地理解了格式规范

**格式修正**:
- ✅ Executed-By: 必须包含 "subagent" 后缀
- ✅ Context: phase_cycle 和 context 之间只有一个空格，不使用 " - " 分隔符

#### v1.0.0 - 2025-12-10

**创建原因**:
- commit-msg-generator SKILL.md 缺少增强标记格式的详细规范
- 需要建立权威的格式定义文档

**内容**:
- ✅ 定义三种增强标记的完整格式规范
- ✅ 提供详细的格式约束和规则说明
- ✅ 包含正确/错误示例对比
- ✅ 明确使用场景和限制
- ✅ 建立文档引用关系

---

## [2.0.0] - 2025-12-09

### 🎉 Added - 增强标记支持

**核心升级**:
- ✅ 添加可选参数支持（subagent_type, phase_cycle, module, context）
- ✅ 生成增强标记（🤖 Executed-By, 📋 Context, 🔗 Module）
- ✅ 完全向后兼容v1.0.0

**主要变更**:
1. **参数化设计**:
   - 所有增强参数都是可选的
   - 不传参数时行为与v1.0.0完全一致
   - 可独立使用或被orchestrator调用

2. **增强标记生成**:
   - 自动添加Agent、Context、Module标记
   - 插入位置：Body之后、Footer之前
   - 遵循一致的格式规范

3. **灵活性**:
   - 支持部分参数（只传subagent_type也可以）
   - 支持完整参数（所有增强信息）
   - 支持无参数（标准消息）

**向后兼容**:
- ✅ 无参数调用与v1.0.0行为一致
- ✅ 不影响现有使用方式
- ✅ 可选择性使用新特性

**配合使用**:
- 与strategic-commit-orchestrator v2.0.0配合
- 支持AI-DDD v3.0.0架构
- 提供更丰富的提交可追溯性

---

## [1.0.0] - 2025-12-09

### 🚀 Initial Release - 初始版本

**核心功能**:
- ✅ 基础Conventional Commits规范支持
- ✅ 自动分析Git暂存区变更
- ✅ 生成规范的commit消息
- ✅ 支持所有标准commit类型（feat, fix, docs, etc.）
- ✅ 双语支持（中文/英文）
- ✅ Scope范围标记
- ✅ Body详细描述
- ✅ Footer关联信息（Closes, Refs, etc.）

**工具权限**:
- Bash: 执行git命令
- Read: 读取文件内容
- Grep: 搜索代码模式

---

*本Skill由 AI Development Team 设计，遵循Conventional Commits规范和AI-DDD最佳实践。*

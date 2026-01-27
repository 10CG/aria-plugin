---
name: arch-update
description: |
  自动化管理代码架构文档的创建、更新和验证，确保文档与代码100%同步。

  使用场景：完成功能开发后同步架构文档、重构后更新文档。
argument-hint: "[module-path]"
disable-model-invocation: false
user-invocable: true
allowed-tools: Read, Write, Glob, Grep, Edit
---

# 架构文档更新器

## 快速开始

### 何时使用？

**✅ 使用场景**:
- 完成功能开发后同步架构文档
- 新建模块（≥5个文件）需要创建架构文档
- 重构后更新文档结构
- 代码变更需要反映到文档中

**❌ 不使用场景**:
- 临时实验性代码
- 配置文件修改
- 文档本身的更新

### 快速示例

```bash
# 场景: 新增了一个 provider_factory.py 文件

# 1. 找到归属文档
find backend/llm_provider -name "*ARCHITECTURE*.md"
# 输出: LLM_PROVIDER_ARCHITECTURE.md

# 2. 更新文件列表
# 在文档中添加:
- `provider_factory.py` - 提供者工厂 ⭐新增

# 3. 更新统计和版本
# 总文件数: 8个 → 9个
# 版本: 1.0.0 → 1.0.1
```

更多详细示例: [EXAMPLES.md](./EXAMPLES.md)

---

## 核心原则

使用本 Skill 前，请确保理解：

1. **三层架构体系** (L0/L1/L2) → 参考 `@.claude/skills/arch-common/SKILL.md`
2. **命名规范**: 代码目录用大写，docs/目录用小写 → 参考 `@.claude/skills/arch-common/SKILL.md`
3. **三步流程**: 生成TREE → 创建INDEX → 验证（不得跳过）
4. **100%覆盖**: 所有代码文件必须在文档中列出
5. **使用工具生成数据**: 禁止手动估算统计数据

共享配置: `@.claude/skills/arch-common/SKILL.md`

---

## 共享配置

三层架构体系 (L0/L1/L2)、命名规范、模块入口表等共享定义请参考：

**`@.claude/skills/arch-common/SKILL.md`**

---

## 标准化三步流程

### 第1步: 生成TREE（强制）

```bash
python scripts/architecture/python/arch_tree_generate.py --target [端名]

# 示例
python scripts/architecture/python/arch_tree_generate.py --target mobile
python scripts/architecture/python/arch_tree_generate.py --target backend
```

**输出**: `[端根目录]/ARCHITECTURE_DOCS_TREE.md`

**强制要求**:
- ❌ 绝对禁止跳过 - TREE是权威数据源
- ❌ 禁止手动估算 - 所有统计必须来自此工具

### 第2步: 创建INDEX（基于TREE）

**数据来源**:
- ✅ 必须读取TREE文档
- ✅ 必须使用标准模板 → [TEMPLATES.md](./TEMPLATES.md)
- ❌ 禁止凭经验编写

### 第3步: 验证（强制）

```bash
./scripts/architecture/arch_check.sh [目标路径]

# 发现问题时自动修复
./scripts/architecture/arch_check.sh [目标路径] fix
```

详细验证方法: [VALIDATION.md](./VALIDATION.md)

---

## 常用场景

### 场景1: 新增代码文件

1. 找到归属文档: `find [目录] -name "*ARCHITECTURE*.md"`
2. 更新文件列表: `- new_file.py - [功能描述] ⭐新增`
3. 更新统计和版本

### 场景2: 创建新模块（≥5个文件）

1. 统计: `find [模块] -name "*.py" | wc -l`
2. 选择模板（≥10用L1，5-10用L2）
3. 创建: `[模块]/[模块名]_ARCHITECTURE.md`
4. 更新父文档和索引

### 场景3: 删除代码文件

1. 查找: `grep -r "file.py" **/*ARCHITECTURE*.md`
2. 标记: `~~- file.py - [功能]~~ ❌已删除`
3. 更新统计

### 场景4: 重构模块

1. 记录变更（移动/删除/新增）
2. 更新文件架构（标记变更）
3. 更新依赖关系
4. 添加设计决策

详细步骤: [EXAMPLES.md](./EXAMPLES.md)

---

## 使用场景决策矩阵

| 场景 | 触发条件 | 操作 | 优先级 |
|------|---------|------|--------|
| **新增代码文件** | 创建.py/.js/.dart等 | 更新对应架构文档 | 高 |
| **新建模块** | ≥5个文件 | 创建独立架构文档 | 高 |
| **删除文件** | 移除代码 | 标记❌删除 | 中 |
| **重构模块** | 结构变化 | 更新架构和依赖 | 高 |
| **修改依赖** | 引入/移除 | 更新依赖关系 | 高 |
| **小改动** | <3个文件 | 批量处理 | 低 |

---

## 最佳实践

### 及时更新

✅ 好的做法: `完成功能 → 立即更新文档 → 一起提交`

❌ 不好的做法: `完成多个功能 → 批量更新文档`

### 100%覆盖

✅ 必须做到:
- 所有代码文件都在架构文档中列出
- 每个文件都有功能描述
- 新增标记⭐，删除标记❌

### 保持简洁

- 文件功能描述: ≤10字
- 核心价值: ≤30字
- 设计决策: 简要理由

---

## 快速检查清单

### 执行前
- [ ] 理解三层架构体系（L0/L1/L2）
- [ ] 了解命名规范

### 执行中
- [ ] 找到正确的归属文档
- [ ] 使用标准模板
- [ ] 标记文件变更（⭐新增，❌删除）
- [ ] 更新统计数据和版本号

### 执行后
- [ ] 验证100%文件覆盖
- [ ] 运行验证工具
- [ ] 与代码一起提交

---

## 相关文档

### Skill 文档
- **详细示例**: [EXAMPLES.md](./EXAMPLES.md)
- **模板集合**: [TEMPLATES.md](./TEMPLATES.md)
- **验证工具**: [VALIDATION.md](./VALIDATION.md)
- **共享配置**: `@.claude/skills/arch-common/SKILL.md`

### 相关 Skills
- **arch-search** - 搜索架构文档
- **arch-common** - 共享配置

### 规范文档
- 共享配置: `@.claude/skills/arch-common/SKILL.md`
- 通用方法论: `@standards/core/architecture/README.md`
- 脚本配置: `scripts/architecture/python/config.yaml`

---

**最后更新**: 2025-12-28
**规范版本**: v4.5
**Skill 版本**: 2.3.0

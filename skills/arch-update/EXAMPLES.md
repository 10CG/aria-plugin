# 架构文档更新器 - 详细示例

> **适用**: architecture-doc-updater skill
> **最后更新**: 2025-12-11

本文档提供详细的架构文档更新操作示例。

---

## 📚 示例目录

- [场景1: 新增单个代码文件](#场景1-新增单个代码文件)
- [场景2: 创建新模块](#场景2-创建新模块-≥5个文件)
- [场景3: 删除代码文件](#场景3-删除代码文件)
- [场景4: 重构模块](#场景4-重构模块)
- [常见错误示例](#常见错误示例)
- [成功输出示例](#成功输出示例)

---

## 场景1: 新增单个代码文件

### 背景
在 `backend/llm_provider/` 目录新增了 `provider_factory.py` 文件。

### 执行步骤

#### 步骤1: 判断是否需要文档

```bash
# 检查文件扩展名和路径
file="backend/llm_provider/provider_factory.py"
ext="${file##*.}"

if [[ "$ext" == "py" ]] && [[ "$file" == */lib/* || "$file" == */src/* || "$file" == */app/* ]]; then
    echo "需要更新架构文档"
fi
```

**结果**: ✅ 需要更新（.py 文件且在代码目录中）

#### 步骤2: 查找归属文档

```bash
# 在当前目录查找
find backend/llm_provider -maxdepth 1 -name "*ARCHITECTURE*.md"

# 输出: backend/llm_provider/LLM_PROVIDER_ARCHITECTURE.md
```

#### 步骤3: 更新文件列表

读取 `LLM_PROVIDER_ARCHITECTURE.md`，找到对应的文件组，添加新文件：

```markdown
### 核心提供者
**功能边界**: LLM服务提供者的核心实现
**核心价值**: 统一的LLM调用接口
- `base_provider.py` - 提供者基类
- `openai_provider.py` - OpenAI实现
- `anthropic_provider.py` - Anthropic实现
- `provider_factory.py` - 提供者工厂 ⭐新增
```

#### 步骤4: 更新统计

```markdown
## 📊 覆盖统计
- **总文件数**: 9个 (+1)
- **文档覆盖率**: 100%
- **主要技术**: Python, LangChain
```

#### 步骤5: 更新版本和时间

```markdown
## 🤖 AI快速索引
- **版本**: 1.0.1  # 从 1.0.0 → 1.0.1
- **更新时间**: 2025-12-11T10:30:00+08:00
```

#### 步骤6: 添加版本历史

```markdown
## 📝 版本历史
| 版本 | 时间 | 类型 | 变更内容 |
|------|------|------|----------|
| 1.0.1 | 2025-12-11T10:30:00+08:00 | 新增 | 添加provider_factory.py工厂模式 |
| 1.0.0 | 2025-12-09T15:00:00+08:00 | 初始 | 创建LLM Provider架构文档 |
```

---

## 场景2: 创建新模块 (≥5个文件)

### 背景
新增 `backend/agents/` 目录，包含 8 个文件，需要创建独立架构文档。

### 执行步骤

#### 步骤1: 统计文件数量

```bash
find backend/agents -name "*.py" | wc -l
# 输出: 8
```

**结论**: ≥5个文件，需要创建独立架构文档

#### 步骤2: 确定层级

```bash
# 8个文件 < 10
# 层级: L2（功能组件架构）
```

#### 步骤3: 选择模板

文件数 < 10 → 使用子目录模板（100-200行）

参考: [TEMPLATES.md](./TEMPLATES.md)

#### 步骤4: 创建架构文档

**位置**: `backend/agents/AGENTS_ARCHITECTURE.md`

**内容** (使用标准模板):

```markdown
# Agents架构

## 🤖 AI快速索引
- **文档类型**: 子模块架构
- **模块类型**: 业务逻辑
- **核心功能**: AI代理系统，提供智能任务处理能力
- **关键文件**: agent_base.py, agent_manager.py, tool_executor.py
- **主要依赖**: LangChain, LLM Provider
- **版本**: 1.0.0
- **创建时间**: 2025-12-11T11:00:00+08:00
- **更新时间**: 2025-12-11T11:00:00+08:00
- **作者**: Backend Team
- **状态**: production

## 🎯 核心价值
基于LangChain的智能代理系统，支持工具调用和任务编排。

## 📄 文件架构

### 核心代理
**功能边界**: 代理的基础实现和管理
**核心价值**: 统一的代理接口和生命周期管理
- `agent_base.py` - 代理基类
- `agent_manager.py` - 代理管理器
- `agent_factory.py` - 代理工厂

### 工具系统
**功能边界**: 代理可用的工具集
**核心价值**: 扩展代理能力的工具库
- `tool_executor.py` - 工具执行器
- `tool_registry.py` - 工具注册表

### 辅助功能
**功能边界**: 支持功能模块
**核心价值**: 提供配置、日志等辅助功能
- `config.py` - 配置管理
- `logger.py` - 日志工具
- `utils.py` - 通用工具函数

## ✅ 质量指标
- **测试覆盖率**: ≥80%
- **代码规范**: 遵循PEP 8
- **文档完整性**: 100%

## 🔗 依赖关系
- **上级模块**: backend/
- **依赖模块**: llm_provider/
- **被依赖**: app/routes/

## 💡 关键设计决策
1. **使用工厂模式** - 支持动态创建不同类型的代理
2. **工具注册表** - 便于扩展和管理代理工具
3. **基于LangChain** - 利用成熟框架降低开发成本

## 📊 覆盖统计
- **总文件数**: 8个
- **文档覆盖率**: 100%
- **主要技术**: Python, LangChain, Pydantic

## 📝 版本历史
| 版本 | 时间 | 类型 | 变更内容 |
|------|------|------|----------|
| 1.0.0 | 2025-12-11T11:00:00+08:00 | 初始 | 创建Agents架构文档 |
```

#### 步骤5: 更新父文档

如果父文档（`BACKEND_ARCHITECTURE.md`）存在，添加快速导航：

```markdown
## 🔍 快速导航
| 子模块 | 职责 | 文件数 | 文档 |
|--------|------|--------|------|
| llm_provider | LLM服务提供者 | 9 | [LLM_PROVIDER_ARCHITECTURE.md](./llm_provider/LLM_PROVIDER_ARCHITECTURE.md) |
| agents | AI代理系统 | 8 | [AGENTS_ARCHITECTURE.md](./agents/AGENTS_ARCHITECTURE.md) |
```

#### 步骤6: 更新索引文档

按照三步流程更新索引（参见主 SKILL.md）

---

## 场景3: 删除代码文件

### 背景
移除了 `backend/llm_provider/legacy_provider.py` 文件。

### 执行步骤

#### 步骤1: 查找文件在哪个架构文档中

```bash
grep -r "legacy_provider.py" backend/**/*ARCHITECTURE*.md

# 输出: backend/llm_provider/LLM_PROVIDER_ARCHITECTURE.md:- `legacy_provider.py` - 遗留提供者
```

#### 步骤2: 标记删除

**不要直接删除条目**，而是使用删除线标记：

```markdown
### 核心提供者
**功能边界**: LLM服务提供者的核心实现
- `base_provider.py` - 提供者基类
- `openai_provider.py` - OpenAI实现
- `anthropic_provider.py` - Anthropic实现
- ~~`legacy_provider.py` - 遗留提供者~~ ❌已删除
```

#### 步骤3: 更新统计

```markdown
## 📊 覆盖统计
- **总文件数**: 8个 (-1)
- **文档覆盖率**: 100%
```

#### 步骤4: 更新版本和时间

```markdown
## 🤖 AI快速索引
- **版本**: 1.1.0  # 从 1.0.1 → 1.1.0（删除是次版本变更）
- **更新时间**: 2025-12-11T14:00:00+08:00
```

#### 步骤5: 添加版本历史

```markdown
## 📝 版本历史
| 版本 | 时间 | 类型 | 变更内容 |
|------|------|------|----------|
| 1.1.0 | 2025-12-11T14:00:00+08:00 | 删除 | 移除legacy_provider.py |
| 1.0.1 | 2025-12-11T10:30:00+08:00 | 新增 | 添加provider_factory.py |
```

---

## 场景4: 重构模块

### 背景
重构 `mobile/lib/services/` 模块：
- 移动 3个文件到 `mobile/lib/api/`
- 删除 2个废弃文件
- 新增 1个工具文件

### 执行步骤

#### 步骤1: 记录所有变更

```
移动:
- task_service.dart → mobile/lib/api/task_api.dart
- user_service.dart → mobile/lib/api/user_api.dart
- auth_service.dart → mobile/lib/api/auth_api.dart

删除:
- legacy_sync.dart
- deprecated_cache.dart

新增:
- service_utils.dart
```

#### 步骤2: 更新文件架构

```markdown
### API服务
**功能边界**: 后端API调用封装
**核心价值**: 统一的API调用接口
- ~~`task_service.dart` - 任务服务~~ ➡️ 移至 api/task_api.dart
- ~~`user_service.dart` - 用户服务~~ ➡️ 移至 api/user_api.dart
- ~~`auth_service.dart` - 认证服务~~ ➡️ 移至 api/auth_api.dart

### 工具模块
**功能边界**: 服务层辅助工具
**核心价值**: 提供通用工具函数
- `service_utils.dart` - 服务工具 ⭐新增

### 废弃模块
~~`legacy_sync.dart` - 旧版同步~~ ❌已删除
~~`deprecated_cache.dart` - 废弃缓存~~ ❌已删除
```

#### 步骤3: 更新功能边界和依赖

如果职责发生变化：

```markdown
## 📄 文件架构

### API客户端
**功能边界**: HTTP客户端和API调用（原"API服务"职责已移至api/目录）
**核心价值**: 轻量级HTTP封装
- `http_client.dart` - HTTP客户端
```

更新依赖关系：

```markdown
## 🔗 依赖关系
- **上级模块**: mobile/lib/
- **依赖模块**: api/, models/  # 新增 api/ 依赖
- **被依赖**: pages/, widgets/
```

#### 步骤4: 添加设计决策

```markdown
## 💡 关键设计决策
1. **分离API层** - 将服务层API调用移至独立api/目录，提升可维护性
2. **删除遗留代码** - 移除legacy_sync和deprecated_cache，减少技术债
3. **统一工具函数** - 新增service_utils.dart集中管理工具方法
```

#### 步骤5: 升级版本

```markdown
## 🤖 AI快速索引
- **版本**: 2.0.0  # 从 1.5.3 → 2.0.0（重大重构）
- **更新时间**: 2025-12-11T16:00:00+08:00
```

#### 步骤6: 添加版本历史

```markdown
## 📝 版本历史
| 版本 | 时间 | 类型 | 变更内容 |
|------|------|------|----------|
| 2.0.0 | 2025-12-11T16:00:00+08:00 | 重构 | 分离API层，移除遗留代码 |
| 1.5.3 | 2025-12-10T10:00:00+08:00 | 修复 | ... |
```

---

## 常见错误示例

### 错误1: 混淆命名规范

#### ❌ 错误示例

```
backend/llm_provider/llm-provider-architecture.md  # 代码目录用小写
backend/docs/architecture/LLM_PROVIDER_ARCHITECTURE.md  # docs/目录用大写
```

#### ✅ 正确示例

```
backend/llm_provider/LLM_PROVIDER_ARCHITECTURE.md  # 代码目录用大写
backend/docs/architecture/llm-provider-architecture.md  # docs/目录用小写
```

**规则**:
- 代码目录中：大写+下划线 (`LLM_PROVIDER_ARCHITECTURE.md`)
- docs/目录中：小写+连字符 (`llm-provider-architecture.md`)

---

### 错误2: 跳过索引文档生成步骤

#### ❌ 错误做法

直接手动编写 INDEX 文档，凭经验填写统计数据：

```markdown
## 📊 架构层级统计
| 层级 | 数量 |
|------|------|
| L0 | 1个 |  # 猜测的
| L1 | 5个 |  # 估算的
| L2 | 12个 | # 不准确
```

#### ✅ 正确做法

1. 执行 `arch_tree_generate.py` 生成 TREE
2. 读取 TREE 文档获取准确数据
3. 基于 TREE 数据创建 INDEX 文档
4. 执行 `arch_check.sh` 验证一致性

```bash
# 步骤1: 生成TREE
python scripts/architecture/python/arch_tree_generate.py --target backend

# 步骤2: 读取TREE数据
cat backend/ARCHITECTURE_DOCS_TREE.md

# 步骤3: 基于TREE创建INDEX（使用准确数据）
# L0: 1个, L1: 5个, L2: 12个（从TREE读取）

# 步骤4: 验证
./scripts/architecture/arch_check.sh backend check
```

---

### 错误3: 文档长度超标

#### ❌ 问题

架构文档写了 300+ 行，包含大量代码示例：

```markdown
# 模块架构

## 文件架构
...（100行）...

## 使用示例
### 示例1: 初始化
\```python
# 30行代码示例
\```

### 示例2: 配置
\```python
# 40行代码示例
\```
...（更多示例，共150行）...
```

#### ✅ 解决方案

1. **删除代码示例** - 架构文档不应包含代码示例
2. **精简描述** - 文件功能描述≤10字
3. **遵守行数限制**:
   - 主目录文档: ≤150行
   - 子目录文档: 100-200行
   - 代码块: ≤10行

**优化后**:

```markdown
# 模块架构

## 文件架构
...（50行，精简描述）...

## 使用说明
参考: docs/guides/module-usage.md  # 详细示例移到专门文档
```

---

### 错误4: 缺少必备要素

#### ❌ 遗漏

```markdown
# 模块架构

## 文件列表
- file1.py
- file2.py
- file3.py

## 说明
这是一个模块。
```

**问题**:
- ❌ 没有 🤖 AI快速索引
- ❌ 没有 🎯 核心价值
- ❌ 设计决策 < 3项
- ❌ 文件没有功能描述
- ❌ 没有依赖关系

#### ✅ 完整示例

```markdown
# 模块架构

## 🤖 AI快速索引
- **文档类型**: 子模块架构
- **模块类型**: 业务逻辑
- **核心功能**: 数据处理和转换
- **关键文件**: processor.py, transformer.py
- **主要依赖**: pandas, numpy
- **版本**: 1.0.0
- **创建时间**: 2025-12-11T10:00:00+08:00
- **更新时间**: 2025-12-11T10:00:00+08:00
- **作者**: Data Team
- **状态**: production

## 🎯 核心价值
高性能数据处理模块，支持批量转换。

## 📄 文件架构

### 核心处理
**功能边界**: 数据处理主流程
- `processor.py` - 数据处理器
- `transformer.py` - 数据转换器
- `validator.py` - 数据验证

## 🔗 依赖关系
- **上级模块**: backend/
- **依赖模块**: utils/, models/
- **被依赖**: api/

## 💡 关键设计决策
1. **使用pandas** - 提升数据处理性能
2. **管道模式** - 支持灵活的处理流程
3. **类型验证** - 确保数据质量

## 📊 覆盖统计
- **总文件数**: 3个
- **文档覆盖率**: 100%
- **主要技术**: Python, pandas
```

---

## 成功输出示例

### 示例: 完整的文档更新流程

```
✅ 架构文档已更新

更新文档:
- backend/llm_provider/LLM_PROVIDER_ARCHITECTURE.md
  · 添加 provider_factory.py ⭐新增
  · 更新文件统计: 8个 → 9个
  · 更新版本: 1.0.0 → 1.0.1
  · 更新时间: 2025-12-11T10:30:00+08:00

验证结果:
✓ AI快速索引完整
✓ 核心价值≤30字
✓ 100%文件覆盖
✓ 依赖关系准确
✓ 设计决策≥3项
✓ 文档长度: 145行 (✅合规)
✓ 代码块: 最大8行 (✅合规)

下一步: 请review更新的文档，然后与代码一起提交
```

---

## 💡 最佳实践提示

### 及时更新

**✅ 好的做法**:
```
完成功能 → 立即更新文档 → 一起提交
```

**❌ 不好的做法**:
```
完成多个功能 → 批量更新文档
提交代码 → 后续补文档
```

### 100%覆盖

**✅ 必须做到**:
- 所有代码文件都在架构文档中列出
- 每个文件都有功能描述
- 新增标记⭐，删除标记❌

**❌ 不允许**:
- 遗漏代码文件
- 文档与实际代码不符
- 没有标记变更

### 保持简洁

**✅ 恰当的详细程度**:
- 文件功能描述: ≤10字
- 核心价值: ≤30字
- 设计决策: 简要理由

**❌ 过度详细**:
- 复制粘贴代码实现
- 详细的实现步骤
- 冗长的技术细节

---

## 🔗 相关文档

- **主 Skill**: [SKILL.md](./SKILL.md)
- **模板集合**: [TEMPLATES.md](./TEMPLATES.md)
- **验证工具**: [VALIDATION.md](./VALIDATION.md)

---

**最后更新**: 2025-12-11
**规范版本**: v4.5

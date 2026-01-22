# 架构文档验证和工具

> **适用**: architecture-doc-updater skill
> **最后更新**: 2025-12-11

本文档提供架构文档的验证标准和常用工具命令。

---

## ✅ 验证检查清单

### 格式验证（自动）

#### 1. 检查行数限制

```bash
# 检查单个文档
wc -l [文档路径] | awk '$1 > 200 { print "❌ 超标: "$1"行" } $1 <= 200 { print "✅ 合规: "$1"行" }'

# 示例
wc -l backend/BACKEND_ARCHITECTURE.md | awk '$1 > 150 { print "❌ 超标" } $1 <= 150 { print "✅ 合规" }'

# 批量检查所有架构文档
find . -name "*ARCHITECTURE*.md" | while read f; do
    lines=$(wc -l < "$f")
    if [ $lines -gt 200 ]; then
        echo "❌ $f: $lines行（超标）"
    else
        echo "✅ $f: $lines行（合规）"
    fi
done
```

**标准**:
- 主目录文档（L0）: ≤150行
- 子目录文档（L1/L2）: 100-200行

#### 2. 检查必备章节

```bash
# 检查单个文档
doc="backend/BACKEND_ARCHITECTURE.md"

grep -q "🤖 AI快速索引" "$doc" || echo "❌ 缺少: AI快速索引"
grep -q "🎯 核心价值" "$doc" || echo "❌ 缺少: 核心价值"
grep -q -E "📄 文件架构|📁 文件架构" "$doc" || echo "❌ 缺少: 文件架构"
grep -q "✅ 质量指标" "$doc" || echo "❌ 缺少: 质量指标"
grep -q "🔗 依赖关系" "$doc" || echo "❌ 缺少: 依赖关系"
grep -q "💡 关键设计决策" "$doc" || echo "❌ 缺少: 关键设计决策"
grep -q "📊 覆盖统计" "$doc" || echo "❌ 缺少: 覆盖统计"

echo "✅ 所有必备章节完整"
```

**必备章节**:
1. 🤖 AI快速索引
2. 🎯 核心价值
3. 📄 文件架构 或 📁 文件架构
4. ✅ 质量指标
5. 🔗 依赖关系
6. 💡 关键设计决策
7. 📊 覆盖统计

#### 3. 检查代码块长度

```bash
# 检查所有架构文档中的代码块
find . -name "*ARCHITECTURE*.md" -exec awk '
/```/{
    if(code==0){
        code=1
        start=NR
    }
    else{
        code=0
        if(NR-start>11) # 11行 = 10行内容 + 1行结束标记
            print FILENAME":"start"-"NR" ("NR-start-1"行)"
    }
}
' {} \;
```

**标准**: 代码块≤10行

---

### 内容验证（半自动）

#### 1. 检查文件覆盖率

**原理**: 实际代码文件数 vs 文档中列出的文件数应该 = 100%

```bash
# 步骤1: 统计实际代码文件数
actual=$(find backend/llm_provider -name "*.py" ! -name "__*" | wc -l)
echo "实际代码文件数: $actual"

# 步骤2: 统计文档中列出的文件数
doc_files=$(grep -c "\.py" backend/llm_provider/LLM_PROVIDER_ARCHITECTURE.md)
echo "文档中列出的文件数: $doc_files"

# 步骤3: 对比
if [ $actual -eq $doc_files ]; then
    echo "✅ 100%覆盖"
else
    echo "❌ 覆盖率: $(($doc_files * 100 / $actual))%"
fi
```

**标准**: 100%覆盖

#### 2. 检查链接有效性

使用 `markdown-link-check` 工具：

```bash
# 安装工具
npm install -g markdown-link-check

# 检查单个文档
markdown-link-check backend/BACKEND_ARCHITECTURE.md

# 批量检查
find . -name "*ARCHITECTURE*.md" -exec markdown-link-check {} \;
```

**标准**: 所有链接可访问

#### 3. 检查依赖准确性

验证依赖关系中提到的模块是否存在：

```bash
# 提取依赖关系章节
doc="backend/llm_provider/LLM_PROVIDER_ARCHITECTURE.md"
dependencies=$(sed -n '/## 🔗 依赖关系/,/^##/p' "$doc" | grep -oP '(?<=- \*\*依赖模块\*\*: ).*')

echo "依赖: $dependencies"

# 检查依赖模块是否存在
for dep in $dependencies; do
    if [ -d "backend/$dep" ]; then
        echo "✅ $dep 存在"
    else
        echo "❌ $dep 不存在"
    fi
done
```

---

### 质量验证（人工审查）

使用以下检查清单进行人工审查：

- [ ] **架构逻辑清晰**：模块划分合理，层次分明
- [ ] **核心价值准确**：≤30字，准确描述模块价值
- [ ] **设计决策充分**：≥3项，有理有据
- [ ] **文件描述清晰**：每个文件功能描述≤10字
- [ ] **与代码同步**：文档内容与实际代码一致
- [ ] **便于AI解析**：格式标准，结构清晰
- [ ] **时间格式正确**：使用 ISO 8601 格式
- **版本号规范**：遵循语义化版本

---

## 🔧 常用工具命令

### 判断和查找

#### 判断文件是否需要文档

```bash
# 方法1: 使用 case 语句
file="backend/service.py"
ext="${file##*.}"

case "$ext" in
    py|js|ts|dart|java|go|kt|swift|c|cpp|rs)
        echo "✅ 需要文档"
        ;;
    *)
        echo "❌ 不需要文档"
        ;;
esac
```

**需要文档的扩展名**:
- Python: `.py`
- JavaScript/TypeScript: `.js`, `.ts`, `.jsx`, `.tsx`
- Dart: `.dart`
- Java/Kotlin: `.java`, `.kt`
- Go: `.go`
- Swift: `.swift`
- C/C++: `.c`, `.cpp`, `.h`, `.hpp`
- Rust: `.rs`

**不需要文档的扩展名**:
- 配置: `.json`, `.yaml`, `.xml`, `.toml`
- 文档: `.md`, `.txt`
- 资源: `.css`, `.html`, `.png`, `.jpg`

#### 查找架构文档

```bash
# 在当前目录查找（不递归）
find [目录] -maxdepth 1 -name "*ARCHITECTURE*.md"

# 示例
find backend/llm_provider -maxdepth 1 -name "*ARCHITECTURE*.md"
# 输出: backend/llm_provider/LLM_PROVIDER_ARCHITECTURE.md
```

#### 向上查找架构文档（最多3层）

```bash
# 从当前目录向上查找
dir="backend/llm_provider/utils"

for i in {1..3}; do
    parent=$(dirname "$dir")
    doc=$(find "$parent" -maxdepth 1 -name "*ARCHITECTURE*.md" 2>/dev/null)
    if [ -n "$doc" ]; then
        echo "找到: $doc"
        break
    fi
    dir="$parent"
done
```

---

### 统计和分析

#### 统计模块文件数

```bash
# 统计指定扩展名的文件
find [模块目录] -name "*.py" -o -name "*.js" | wc -l

# 示例: 统计Python文件
find backend/agents -name "*.py" | wc -l

# 统计多种类型
find backend/agents \( -name "*.py" -o -name "*.js" -o -name "*.ts" \) | wc -l
```

#### 统计文档覆盖率

```bash
# 脚本: scripts/architecture/coverage_report.sh
#!/bin/bash

module=$1
doc="$module/$(basename $module | tr '[:lower:]' '[:upper:]')_ARCHITECTURE.md"

# 统计实际文件
actual=$(find "$module" -name "*.py" ! -name "__*" | wc -l)

# 统计文档中列出的文件
documented=$(grep -c "\.py" "$doc" 2>/dev/null || echo 0)

# 计算覆盖率
if [ $actual -eq 0 ]; then
    echo "⚠️ 模块中无代码文件"
else
    coverage=$((documented * 100 / actual))
    if [ $coverage -eq 100 ]; then
        echo "✅ $module: 100%覆盖 ($documented/$actual)"
    else
        echo "❌ $module: ${coverage}%覆盖 ($documented/$actual)"
    fi
fi
```

使用:
```bash
./scripts/architecture/coverage_report.sh backend/llm_provider
```

---

### 索引和树管理

#### 生成文档树（第1步）

```bash
# 生成指定端的文档树
python scripts/architecture/python/arch_tree_generate.py --target [端名]

# 示例
python scripts/architecture/python/arch_tree_generate.py --target backend
python scripts/architecture/python/arch_tree_generate.py --target mobile
python scripts/architecture/python/arch_tree_generate.py --target frontend
```

**输出**: `[端根目录]/ARCHITECTURE_DOCS_TREE.md`

**重要**:
- ✅ 这是权威数据源
- ✅ 所有统计必须来自此工具
- ❌ 不得手动估算

#### 验证索引一致性（第3步）

```bash
# 检查索引与树的一致性
cd scripts/architecture
./arch_check.sh [目标路径] check

# 示例
./arch_check.sh backend check
./arch_check.sh mobile/app check
```

**输出示例**:
```
✅ TREE文档存在: backend/ARCHITECTURE_DOCS_TREE.md
✅ INDEX文档存在: backend/ARCHITECTURE_DOCS_INDEX.md
✅ 文档数量一致: TREE=15, INDEX=15
✅ L0数量一致: TREE=1, INDEX=1
✅ L1数量一致: TREE=5, INDEX=5
✅ L2数量一致: TREE=9, INDEX=9
✅ 所有检查通过
```

#### 自动修复不一致

```bash
# 发现问题后自动修复
./arch_check.sh [目标路径] fix

# 示例
./arch_check.sh backend fix
```

**修复内容**:
- 更新INDEX文档的统计数据
- 同步TREE和INDEX的文档列表
- 修正层级统计

---

### 单个文档验证

#### 验证脚本

```bash
# scripts/architecture/validate_single.sh
#!/bin/bash

doc=$1

echo "验证: $doc"
echo "=================="

# 1. 检查文件存在
if [ ! -f "$doc" ]; then
    echo "❌ 文件不存在"
    exit 1
fi

# 2. 检查行数
lines=$(wc -l < "$doc")
if [ $lines -gt 200 ]; then
    echo "❌ 行数超标: $lines行 (限制200行)"
else
    echo "✅ 行数: $lines行"
fi

# 3. 检查必备章节
missing=0
for section in "🤖 AI快速索引" "🎯 核心价值" "📄 文件架构" "💡 关键设计决策"; do
    if ! grep -q "$section" "$doc"; then
        echo "❌ 缺少章节: $section"
        missing=1
    fi
done

if [ $missing -eq 0 ]; then
    echo "✅ 必备章节完整"
fi

# 4. 检查代码块长度
long_blocks=$(awk '/```/{if(code==0){code=1;start=NR}else{code=0;if(NR-start>11)print NR-start-1}}' "$doc")
if [ -n "$long_blocks" ]; then
    echo "⚠️ 存在过长代码块: $long_blocks 行"
else
    echo "✅ 代码块长度合规"
fi

# 5. 检查设计决策数量
decisions=$(grep -c "^\*\*\[.*\]\*\*" "$doc" | awk '{ if ($1 >= 3) print "OK"; else print $1 }')
if [ "$decisions" = "OK" ]; then
    echo "✅ 设计决策≥3项"
else
    echo "❌ 设计决策<3项: $decisions项"
fi

echo "=================="
echo "验证完成"
```

使用:
```bash
./scripts/architecture/validate_single.sh backend/BACKEND_ARCHITECTURE.md
```

---

### 批量验证

#### 批量验证所有文档

```bash
# scripts/architecture/validate_all.sh
#!/bin/bash

echo "批量验证架构文档"
echo "=================="

total=0
passed=0
failed=0

find . -name "*ARCHITECTURE*.md" | while read doc; do
    total=$((total + 1))
    echo ""
    echo "[$total] $doc"

    if ./scripts/architecture/validate_single.sh "$doc" 2>&1 | grep -q "❌"; then
        failed=$((failed + 1))
        echo "❌ 验证失败"
    else
        passed=$((passed + 1))
        echo "✅ 验证通过"
    fi
done

echo ""
echo "=================="
echo "总计: $total"
echo "通过: $passed"
echo "失败: $failed"
```

使用:
```bash
./scripts/architecture/validate_all.sh
```

---

## 📊 验证报告示例

### 成功验证输出

```
验证: backend/llm_provider/LLM_PROVIDER_ARCHITECTURE.md
==================
✅ 行数: 145行
✅ 必备章节完整
✅ 代码块长度合规
✅ 设计决策≥3项
✅ 文件覆盖率: 100% (9/9)
✅ 依赖关系准确
✅ 链接有效
==================
验证完成：✅ 所有检查通过
```

### 失败验证输出

```
验证: backend/agents/AGENTS_ARCHITECTURE.md
==================
❌ 行数超标: 245行 (限制200行)
✅ 必备章节完整
⚠️ 存在过长代码块: 15 行
❌ 设计决策<3项: 2项
✅ 文件覆盖率: 100% (8/8)
❌ 依赖关系不准确: utils/ 不存在
⚠️ 链接失效: docs/guide.md
==================
验证完成：❌ 发现 4 个问题
```

---

## 🎯 验证决策矩阵

| 检查项 | 优先级 | 自动化 | 工具 |
|--------|--------|--------|------|
| **行数限制** | 高 | ✅ | wc -l |
| **必备章节** | 高 | ✅ | grep |
| **代码块长度** | 中 | ✅ | awk |
| **文件覆盖率** | 高 | 半自动 | find + grep |
| **链接有效性** | 中 | ✅ | markdown-link-check |
| **依赖准确性** | 中 | 半自动 | 自定义脚本 |
| **设计决策** | 中 | ✅ | grep |
| **内容质量** | 高 | ❌ | 人工审查 |

---

## 💡 验证最佳实践

### 1. 提交前验证

```bash
# 在提交前运行验证
git diff --name-only | grep "ARCHITECTURE.*\.md" | while read doc; do
    ./scripts/architecture/validate_single.sh "$doc"
done
```

### 2. CI/CD集成

```yaml
# .github/workflows/architecture-docs.yml
name: Architecture Docs Validation

on:
  pull_request:
    paths:
      - '**/*ARCHITECTURE*.md'

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2

      - name: Validate Architecture Docs
        run: |
          chmod +x scripts/architecture/validate_all.sh
          ./scripts/architecture/validate_all.sh
```

### 3. 定期审计

```bash
# 每周运行完整验证
crontab -e

# 每周一早上9点
0 9 * * 1 cd /path/to/project && ./scripts/architecture/validate_all.sh > /tmp/arch_audit.log
```

---

## 🔗 相关文档

- **主 Skill**: [SKILL.md](./SKILL.md)
- **详细示例**: [EXAMPLES.md](./EXAMPLES.md)
- **模板集合**: [TEMPLATES.md](./TEMPLATES.md)

---

**最后更新**: 2025-12-11
**规范版本**: v4.5

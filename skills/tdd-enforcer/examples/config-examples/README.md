# TDD Enforcer 配置示例

> **TDD Enforcer v2.0** - 文档驱动设计
> 常用配置文件示例

---

## 配置文件

本目录包含三种严格度级别的配置文件示例：

| 配置文件 | 严格度 | 说明 |
|---------|-------|------|
| `advisory.json` | advisory | 建议模式 - 警告但不阻塞 |
| `strict.json` | strict | 严格模式 - 阻塞违规操作 |
| `superpowers.json` | superpowers | 完整模式 - 所有高级功能 |

---

## 使用方法

将配置文件复制到项目根目录的 `.claude/` 文件夹：

```bash
# 复制配置文件
cp config-examples/strict.json .claude/tdd-config.json

# 或直接使用符号链接（推荐）
ln -s ../config-examples/strict.json .claude/tdd-config.json
```

---

## 配置说明

### Advisory 模式

适合新手学习和探索性开发，TDD 违规时只显示警告。

**特点**：
- 显示友好提示
- 不阻塞任何操作
- 帮助建立 TDD 习惯

### Strict 模式

适合日常开发，TDD 违规时会阻止操作。

**特点**：
- 阻塞违规操作
- 显示修复建议
- 保持代码质量

### Superpowers 模式

适合严肃的 TDD 实践，包含所有高级功能。

**特点**：
- GREEN 阶段代码增量限制
- 金装甲测试自动检测
- 状态持久化
- 完整的 TDD 循环控制

---

## 自定义配置

根据项目需求调整配置：

```json
{
  "$schema": "tdd-config-schema.json",
  "enabled": true,
  "strictness": "strict",
  "skip_patterns": [
    "**/*.md",
    "**/*.json",
    "**/config/**"
  ],
  "test_patterns": {
    "python": ["test_*.py", "*_test.py"],
    "javascript": ["*.test.js", "*.spec.js"],
    "dart": ["*_test.dart"]
  },
  "language_settings": {
    "python": {
      "framework": "pytest",
      "test_dir": "tests"
    }
  }
}
```

---

## 配置字段说明

| 字段 | 类型 | 默认值 | 说明 |
|-----|------|--------|------|
| `enabled` | boolean | `true` | 是否启用 TDD 检查 |
| `strictness` | string | `"advisory"` | 严格度级别 |
| `skip_patterns` | array | 默认列表 | 跳过检查的文件模式 |
| `test_patterns` | object | 默认模式 | 各语言的测试文件模式 |
| `language_settings` | object | - | 语言特定设置 |

完整配置说明：见 `tdd-config-schema.json`

---

**最后更新**: 2026-02-06

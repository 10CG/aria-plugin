# TDD Enforcer 示例项目

> **TDD Enforcer v2.0** - 文档驱动设计
> 本目录包含 TDD Enforcer 在不同语言中的使用示例

---

## 示例列表

| 语言 | 目录 | 测试框架 | 严格度 |
|------|------|---------|--------|
| **Python** | `python/` | pytest | strict |
| **JavaScript** | `javascript/` | Jest | strict |
| **Dart** | `dart/` | test | strict |
| **配置示例** | `config-examples/` | - | advisory/strict/superpowers |

---

## 快速开始

### Python 示例

```bash
cd examples/python
pip install pytest
pytest tests/ -v
```

### JavaScript 示例

```bash
cd examples/javascript
npm install
npm test
```

### Dart 示例

```bash
cd examples/dart
dart pub get
dart test
```

---

## TDD 流程演示

每个示例项目都演示了完整的 TDD RED-GREEN-REFACTOR 循环：

### RED 阶段 - 编写失败测试

```python
# tests/test_calculator.py
def test_add_fails():
    calc = Calculator()
    assert calc.add(2, 3) == 100  # 故意错误的期望
```

运行测试 → 失败 (RED) ✅

### GREEN 阶段 - 最小实现

```python
# src/calculator.py
def add(self, a, b):
    return a + b  # 最小实现
```

运行测试 → 通过 (GREEN) ✅

### REFACTOR 阶段 - 优化代码

```python
# src/calculator.py
def add(self, a: int, b: int) -> int:
    """返回两个数的和"""
    return a + b
```

运行测试 → 通过 (REFACTOR) ✅

---

## 配置文件

### 使用预置配置

从 `config-examples/` 复制配置文件：

```bash
# Advisory 模式 - 新手友好
cp config-examples/advisory.json .claude/tdd-config.json

# Strict 模式 - 日常开发
cp config-examples/strict.json .claude/tdd-config.json

# Superpowers 模式 - 完整 TDD
cp config-examples/superpowers.json .claude/tdd-config.json
```

### 三种模式对比

| 特性 | Advisory | Strict | Superpowers |
|------|----------|--------|-------------|
| 警告提示 | ✅ | ✅ | ✅ |
| 阻塞违规 | ❌ | ✅ | ✅ |
| GREEN 阶段限制 | ❌ | ❌ | ✅ |
| 金装甲测试检测 | ❌ | ❌ | ✅ |
| 状态持久化 | ❌ | ❌ | ✅ |

---

## 项目结构

```
examples/
├── python/                      # Python 示例
│   ├── src/calculator.py
│   ├── tests/test_calculator.py
│   └── .claude/tdd-config.json
├── javascript/                  # JavaScript 示例
│   ├── src/calculator.js
│   ├── tests/calculator.test.js
│   ├── package.json
│   └── .claude/tdd-config.json
├── dart/                        # Dart 示例
│   ├── lib/calculator.dart
│   ├── test/calculator_test.dart
│   ├── pubspec.yaml
│   └── .claude/tdd-config.json
└── config-examples/             # 配置文件示例
    ├── advisory.json
    ├── strict.json
    └── superpowers.json
```

---

## 学习路径

1. **第一步**: 运行示例项目，观察测试结果
2. **第二步**: 尝试编辑源码，触发 TDD 检查
3. **第三步**: 切换严格度级别，体验不同行为
4. **第四步**: 阅读 `../references/` 下的详细文档
5. **第五步**: 在自己的项目中应用

---

## 故障排除

### Python 示例

```bash
# 安装 pytest
pip install pytest

# 验证安装
pytest --version
```

### JavaScript 示例

```bash
# 清除缓存重试
rm -rf node_modules package-lock.json
npm install
```

### Dart 示例

```bash
# 安装 Dart SDK
# 从 https://dart.dev/get-dart 下载

# 验证安装
dart --version
```

---

## 下一步

- 查看 [../references/strictness-levels.md](../references/strictness-levels.md) 了解严格度详解
- 查看 [../references/migration-guide.md](../references/migration-guide.md) 了解迁移指南
- 查看 [../SKILL.md](../SKILL.md) 了解完整功能

---

**最后更新**: 2026-02-06

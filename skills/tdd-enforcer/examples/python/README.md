# TDD Enforcer Python 示例

> **TDD Enforcer v2.0** - 文档驱动设计
> 演示 TDD Enforcer 在 Python 项目中的使用

---

## 项目结构

```
python-example/
├── src/
│   ├── __init__.py
│   └── calculator.py       # 实现代码
├── tests/
│   └── test_calculator.py  # 测试代码
├── .claude/
│   └── tdd-config.json     # TDD 配置
└── README.md
```

---

## TDD 流程演示

### RED 阶段 - 编写失败测试

```python
# tests/test_calculator.py
import pytest
from calculator import Calculator

def test_add_fails():
    """测试加法功能 - 应该失败"""
    calc = Calculator()
    result = calc.add(2, 3)
    assert result == 100  # 故意错误的期望值
```

运行测试：
```bash
pytest tests/test_calculator.py -v
```

结果：失败 (RED) ✅

### GREEN 阶段 - 最小实现

```python
# src/calculator.py
class Calculator:
    def add(self, a, b):
        return a + b  # 最小实现
```

运行测试：
```bash
pytest tests/test_calculator.py -v
```

结果：通过 (GREEN) ✅

### REFACTOR 阶段 - 优化代码

```python
# src/calculator.py
class Calculator:
    """简单的计算器"""

    def add(self, a: int, b: int) -> int:
        """返回两个数的和"""
        return a + b
```

运行测试：
```bash
pytest tests/test_calculator.py -v
```

结果：通过 (REFACTOR) ✅

---

## 配置文件

### Advisory 模式

```json
{
  "$schema": "tdd-config-schema.json",
  "enabled": true,
  "strictness": "advisory"
}
```

### Strict 模式

```json
{
  "$schema": "tdd-config-schema.json",
  "enabled": true,
  "strictness": "strict",
  "test_patterns": {
    "python": ["test_*.py", "*_test.py"]
  }
}
```

### Superpowers 模式

```json
{
  "$schema": "tdd-config-schema.json",
  "enabled": true,
  "strictness": "superpowers",
  "green_phase_limits": {
    "enabled": true,
    "max_lines_after_pass": 50,
    "max_new_functions": 3
  },
  "golden_testing_detection": {
    "enabled": true,
    "patterns": [
      {"pattern": "assert True", "severity": "error"},
      {"pattern": "assert False", "severity": "error"}
    ]
  }
}
```

---

## 安装依赖

```bash
pip install pytest
```

---

## 运行示例

```bash
# 进入示例目录
cd examples/python

# 运行测试
pytest tests/ -v

# 查看 TDD 状态 (Superpowers 模式)
cat .claude/tdd-state.yaml
```

---

**最后更新**: 2026-02-06

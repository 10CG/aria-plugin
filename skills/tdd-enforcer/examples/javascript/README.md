# TDD Enforcer JavaScript 示例

> **TDD Enforcer v2.0** - 文档驱动设计
> 演示 TDD Enforcer 在 JavaScript/TypeScript 项目中的使用

---

## 项目结构

```
javascript-example/
├── src/
│   └── calculator.js       # 实现代码
├── tests/
│   └── calculator.test.js  # 测试代码
├── .claude/
│   └── tdd-config.json     # TDD 配置
├── package.json
└── README.md
```

---

## TDD 流程演示

### RED 阶段 - 编写失败测试

```javascript
// tests/calculator.test.js
const Calculator = require('../src/calculator');

describe('Calculator', () => {
  describe('add', () => {
    it('should return sum of two numbers', () => {
      const calc = new Calculator();
      // 失败的期望 - RED 阶段
      expect(calc.add(2, 3)).toBe(100);
    });
  });
});
```

运行测试：
```bash
npm test
```

结果：失败 (RED) ✅

### GREEN 阶段 - 最小实现

```javascript
// src/calculator.js
class Calculator {
  add(a, b) {
    return a + b; // 最小实现
  }
}

module.exports = Calculator;
```

运行测试：
```bash
npm test
```

结果：通过 (GREEN) ✅

### REFACTOR 阶段 - 优化代码

```javascript
// src/calculator.js
class Calculator {
  /**
   * 返回两个数的和
   * @param {number} a
   * @param {number} b
   * @returns {number}
   */
  add(a, b) {
    return a + b;
  }
}

module.exports = Calculator;
```

运行测试：
```bash
npm test
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
    "javascript": ["*.test.js", "*.spec.js"]
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
      {"pattern": "assert(true)", "severity": "error"},
      {"pattern": "assert(false)", "severity": "error"}
    ]
  }
}
```

---

## package.json

```json
{
  "name": "tdd-enforcer-js-example",
  "version": "2.0.0",
  "description": "TDD Enforcer JavaScript Example",
  "scripts": {
    "test": "jest",
    "test:watch": "jest --watch"
  },
  "devDependencies": {
    "jest": "^29.0.0"
  }
}
```

---

## 安装依赖

```bash
npm install
```

---

## 运行示例

```bash
# 进入示例目录
cd examples/javascript

# 运行测试
npm test

# 查看 TDD 状态 (Superpowers 模式)
cat .claude/tdd-state.yaml
```

---

**最后更新**: 2026-02-06

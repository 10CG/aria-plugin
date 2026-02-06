# TDD Enforcer Dart 示例

> **TDD Enforcer v2.0** - 文档驱动设计
> 演示 TDD Enforcer 在 Dart/Flutter 项目中的使用

---

## 项目结构

```
dart-example/
├── lib/
│   └── calculator.dart     # 实现代码
├── test/
│   └── calculator_test.dart # 测试代码
├── .claude/
│   └── tdd-config.json     # TDD 配置
├── pubspec.yaml
└── README.md
```

---

## TDD 流程演示

### RED 阶段 - 编写失败测试

```dart
// test/calculator_test.dart
import 'package:dart_example/calculator.dart';
import 'package:test/test.dart';

void main() {
  group('Calculator', () {
    test('add should return sum of two numbers', () {
      final calc = Calculator();
      // 失败的期望 - RED 阶段
      expect(calc.add(2, 3), 100);
    });
  });
}
```

运行测试：
```bash
dart test
```

结果：失败 (RED) ✅

### GREEN 阶段 - 最小实现

```dart
// lib/calculator.dart
class Calculator {
  int add(int a, int b) {
    return a + b; // 最小实现
  }
}
```

运行测试：
```bash
dart test
```

结果：通过 (GREEN) ✅

### REFACTOR 阶段 - 优化代码

```dart
// lib/calculator.dart
/// 简单计算器
class Calculator {
  /// 返回两个数的和
  ///
  /// [a] 第一个数
  /// [b] 第二个数
  /// 返回两数之和
  int add(int a, int b) {
    return a + b;
  }
}
```

运行测试：
```bash
dart test
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
    "dart": ["*_test.dart"]
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
      {"pattern": "expect(true, true)", "severity": "error"},
      {"pattern": "expect(false, false)", "severity": "error"}
    ]
  }
}
```

---

## pubspec.yaml

```yaml
name: dart_example
version: 2.0.0
description: TDD Enforcer Dart Example

environment:
  sdk: '>=3.0.0 <4.0.0'

dev_dependencies:
  test: ^1.24.0
```

---

## 安装依赖

```bash
dart pub get
```

---

## 运行示例

```bash
# 进入示例目录
cd examples/dart

# 运行测试
dart test

# 监听模式
dart test --watch

# 查看 TDD 状态 (Superpowers 模式)
cat .claude/tdd-state.yaml
```

---

## Flutter 项目

对于 Flutter 项目，使用:

```bash
flutter test
```

Flutter 项目配置示例：

```json
{
  "$schema": "tdd-config-schema.json",
  "enabled": true,
  "strictness": "strict",
  "language_settings": {
    "dart": {
      "framework": "flutter",
      "test_dir": "test"
    }
  }
}
```

---

**最后更新**: 2026-02-06

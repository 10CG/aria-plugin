# RED 状态检测说明

> **TDD Enforcer** - 测试状态检测机制详解
> **版本**: 2.0.0
> **更新**: 2026-02-06

---

## 概述

RED 状态检测是 TDD 的核心机制，确保在编写实现代码之前存在失败的测试。本文档说明各语言的检测原理和命令。

---

## 检测原理

### 什么是 RED 状态？

```
RED 状态 = 测试文件存在 + 至少一个测试失败
GREEN 状态 = 测试文件存在 + 所有测试通过
UNKNOWN 状态 = 无法确定测试状态
```

### 检测流程

```yaml
1. 定位测试文件
   └─ 根据源文件路径查找对应测试

2. 确定测试框架
   └─ 根据配置文件自动检测

3. 运行测试检测命令
   └─ 收集测试信息而不运行完整测试

4. 判断测试状态
   └─ 分析输出确定 RED/GREEN/UNKNOWN
```

---

## Python 检测

### 框架识别

```bash
# pytest 检测
if [ -f pytest.ini ] || [ -f pyproject.toml ] && grep -q "pytest" pyproject.toml; then
    framework="pytest"
    command="pytest tests/ --collect-only --quiet"
fi

# unittest 检测
if [ -f setup.py ] || grep -q "unittest" setup.py; then
    framework="unittest"
    command="python -m unittest discover -s tests"
fi
```

### 状态判断

| 框架 | RED 状态 | GREEN 状态 |
|------|---------|-----------|
| pytest | exit_code != 0 | exit_code = 0 |
| unittest | 输出包含 "FAILED"/"ERROR" | 输出包含 "OK" |

### 示例命令

```bash
# pytest - 收集测试信息
pytest tests/test_calculator.py --collect-only --quiet

# 输出示例 (有测试)
test_calculator.py::test_add
test_calculator.py::test_subtract
2 tests collected

# 运行测试检查状态
pytest tests/test_calculator.py --quiet

# RED 输出 (exit_code = 1)
FAILED test_add
```

---

## JavaScript/TypeScript 检测

### 框架识别

```bash
# Jest 检测
if [ -f jest.config.js ] || grep -q '"jest"' package.json; then
    framework="jest"
    command="npx jest --listTests --passWithNoTests"
fi

# Mocha 检测
if [ -f mocha.opts ] || grep -q '"mocha"' package.json; then
    framework="mocha"
    command="npx mocha --dry-run"
fi

# Vitest 检测
if grep -q '"vitest"' package.json; then
    framework="vitest"
    command="npx vitest list"
fi
```

### 状态判断

| 框架 | RED 状态 | GREEN 状态 |
|------|---------|-----------|
| jest | 输出包含 "failing" | exit_code = 0 |
| mocha | exit_code != 0 | exit_code = 0 |
| vitest | 输出包含 "FAIL" | exit_code = 0 |

### 示例命令

```bash
# Jest - 列出测试
npx jest tests/calculator.test.js --listTests --passWithNoTests

# 运行测试检查状态
npx jest tests/calculator.test.js --verbose

# RED 输出
FAIL tests/calculator.test.js
  ✕ add should return sum
```

---

## Dart 检测

### 框架识别

```bash
# Flutter 检测
if grep -q "flutter:" pubspec.yaml; then
    framework="flutter"
    command="flutter test --dry-run"
fi

# Dart 检测
if [ -f pubspec.yaml ]; then
    framework="dart"
    command="dart test --dry-run"
fi
```

### 状态判断

| 框架 | RED 状态 | GREEN 状态 |
|------|---------|-----------|
| flutter | 输出包含 "FAIL" 或 exit_code != 0 | exit_code = 0 |
| dart | 输出包含 "FAIL" 或 exit_code != 0 | exit_code = 0 |

### 示例命令

```bash
# Flutter - 测试运行检查
flutter test test/calculator_test.dart --dry-run

# 运行测试
flutter test test/calculator_test.dart

# RED 输出
00:01 +0: test_add - Failed
```

---

## Go 检测

### 框架识别

```bash
# Go 使用内置测试框架
framework="go"
command="go test -list=. ./..."
```

### 状态判断

| 框架 | RED 状态 | GREEN 状态 |
|------|---------|-----------|
| builtin | 输出包含 "FAIL" | exit_code = 0 |

### 示例命令

```bash
# 列出测试
go test -list=. ./...

# 运行测试
go test ./...

# RED 输出
--- FAIL: TestAdd (0.00s)
```

---

## 状态判断逻辑

```python
def determine_test_state(output, exit_code, framework):
    """
    判断测试状态

    返回: "RED" | "GREEN" | "UNKNOWN"
    """
    if framework == "pytest":
        if exit_code == 0:
            return "GREEN"
        elif "collected" in output and int(extract_collected(output)) > 0:
            return "RED"

    elif framework == "unittest":
        if "OK" in output:
            return "GREEN"
        elif "FAILED" in output or "ERROR" in output:
            return "RED"

    elif framework == "jest":
        if exit_code == 0 and "passing" in output:
            return "GREEN"
        elif "failing" in output:
            return "RED"

    # 默认返回 UNKNOWN
    return "UNKNOWN"
```

---

## 文件映射规则

| 语言 | 测试文件模式 | 源文件 → 测试文件 |
|------|------------|------------------|
| Python | `test_*.py`, `*_test.py` | `src/auth.py` → `tests/test_auth.py` |
| JavaScript | `*.test.js`, `*.spec.js` | `src/auth.js` → `src/auth.test.js` |
| TypeScript | `*.test.ts`, `*.spec.ts` | `src/auth.ts` → `src/auth.test.ts` |
| Dart | `*_test.dart` | `lib/auth.dart` → `test/auth_test.dart` |
| Go | `*_test.go` | `auth.go` → `auth_test.go` |

---

## 缓存机制

为避免频繁运行测试，系统会缓存测试状态：

```yaml
缓存键: test_file_path + file_mtime
TTL: 60 秒 (可配置)
失效条件: 测试文件被修改
```

---

**最后更新**: 2026-02-06

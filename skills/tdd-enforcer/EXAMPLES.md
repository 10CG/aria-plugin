# TDD Enforcer 使用示例

> **版本**: 2.0.0 | **设计**: 文档驱动
> **更新**: 2026-02-06

---

## 示例目录

1. [Advisory 模式示例](#advisory-模式示例)
2. [Strict 模式示例](#strict-模式示例)
3. [Superpowers 模式示例](#superpowers-模式示例)
4. [配置文件示例](#配置文件示例)
5. [完整工作流示例](#完整工作流示例)

---

## Advisory 模式示例

### 场景：新功能开发

```yaml
用户操作: 编辑 src/calculator.py

TDD Enforcer 检查:
  1. 读取配置: strictness = "advisory"
  2. 查找测试文件: tests/test_calculator.py
  3. 测试文件不存在

输出:
  ⚠️ TDD 规则警告

  当前文件: src/calculator.py
  期望测试: tests/test_calculator.py

  建议先编写失败测试 (RED 阶段)

  [继续] [了解更多]
```

### 场景：测试已通过

```yaml
用户操作: 继续编辑 src/auth.py

TDD Enforcer 检查:
  1. 读取配置: strictness = "advisory"
  2. 查找测试文件: tests/test_auth.py (存在)
  3. 运行测试: 全部通过

输出:
  ⚠️ TDD 流程建议

  测试已全部通过 (GREEN 状态)
  建议添加新的失败测试后再继续开发

  当前测试: 8/8 通过
  [继续] [查看测试]
```

---

## Strict 模式示例

### 场景：无测试文件

```yaml
配置: .claude/tdd-config.json
{
  "strictness": "strict"
}

用户操作: 编辑 src/user_service.js

TDD Enforcer 检查:
  1. 读取配置: strictness = "strict"
  2. 查找测试文件: tests/user_service.test.js
  3. 测试文件不存在

输出:
  🚫 TDD 严格模式拦截

  当前操作: 编辑 src/user_service.js
  违规: 无对应测试文件

  要求:
    1. 创建 tests/user_service.test.js
    2. 编写至少一个失败的测试
    3. 确认测试失败

  [创建测试] [取消]
```

### 场景：测试已通过

```yaml
配置: strictness = "strict"

用户操作: 尝试添加新功能

TDD Enforcer 检查:
  1. 测试文件存在: tests/test_calculator.py
  2. 运行测试: 全部通过
  3. 判断: 不处于 RED 状态

输出:
  🚫 TDD 严格模式拦截

  当前状态: GREEN (测试全部通过)
  违规: 测试已通过，无法添加新功能代码

  要求:
    1. 添加新的失败测试用例
    2. 确认测试失败
    3. 然后编写实现

  [查看测试] [添加测试] [取消]
```

### 场景：允许编辑 (RED 状态)

```yaml
配置: strictness = "strict"

用户操作: 编辑实现代码

TDD Enforcer 检查:
  1. 测试文件存在
  2. 运行测试: 有失败测试
  3. 判断: 处于 RED 状态

输出:
  ✅ 允许编辑

  当前状态: RED (有失败测试)
  可以继续编写实现代码
```

---

## Superpowers 模式示例

### 场景：金装甲测试检测

```yaml
配置: .claude/tdd-config.json
{
  "strictness": "superpowers",
  "golden_testing_detection": {
    "enabled": true
  }
}

用户操作: 编辑 src/auth.py

TDD Enforcer 检查:
  1. 测试文件存在
  2. 扫描测试内容
  3. 发现: tests/test_auth.py:15 包含 `assert True`

输出:
  🚫 Superpowers 模式拦截

  违规类型: 金装甲测试检测

  发现问题:
    - tests/test_auth.py:15: assert True
    - tests/test_auth.py:23: 空测试 (无断言)

  说明:
    金装甲测试 (Golden Testing) 指永远通过的测试，
    无法验证实际行为，违反 TDD 原则。

  要求:
    1. 修复 assert True 为有意义的断言
    2. 为空测试添加断言
    3. 确认测试失败

  [修复测试] [取消]
```

### 场景：GREEN 阶段代码增量检查

```yaml
配置:
{
  "strictness": "superpowers",
  "green_phase_limits": {
    "enabled": true,
    "max_lines_after_pass": 50,
    "max_new_functions": 3
  }
}

TDD 状态: 测试刚从失败变为通过

用户操作: 继续添加代码

TDD Enforcer 检查:
  1. 检测上次测试通过时间
  2. 计算代码增量: +65 行
  3. 判断: 超过限制 (50 行)

输出:
  🚫 Superpowers 模式拦截

  违规类型: GREEN 阶段代码增量超限

  统计:
    - 新增代码: 65 行 (限制: 50)
    - 新增函数: 5 个 (限制: 3)

  说明:
    GREEN 阶段应编写最小实现使测试通过。
    如需添加更多功能，请先编写新的失败测试。

  要求:
    1. 添加新功能的测试用例
    2. 确认测试失败
    3. 继续实现

  [添加测试] [回滚代码] [取消]
```

### 场景：完整 TDD 循环验证

```yaml
配置: strictness = "superpowers"

状态持久化: .claude/tdd-state.yaml

阶段转换:
  NONE → RED:     编写第一个测试，确认失败
  RED → GREEN:    实现功能，测试通过
  GREEN → REFACTOR: 重构代码，测试仍通过
  REFACTOR → RED:  添加新测试，开始新循环

输出示例:
  📊 TDD 状态报告

  当前阶段: GREEN
  测试状态: 8/8 通过
  代码增量: 35 行 (限制: 50)
  循环次数: 3

  允许操作:
    - 重构现有代码
    - 添加新测试 (进入下一 RED)
```

---

## 配置文件示例

### 最小配置 (Advisory)

```json
{
  "$schema": "tdd-config-schema.json",
  "enabled": true,
  "strictness": "advisory"
}
```

### 生产环境配置 (Strict)

```json
{
  "$schema": "tdd-config-schema.json",
  "enabled": true,
  "strictness": "strict",
  "skip_patterns": [
    "**/*.md",
    "**/*.json",
    "**/config/**",
    "**/migrations/**"
  ],
  "test_patterns": {
    "python": ["test_*.py", "*_test.py"],
    "javascript": ["*.test.js", "*.spec.js"],
    "dart": ["*_test.dart"]
  }
}
```

### 高质量项目配置 (Superpowers)

```json
{
  "$schema": "tdd-config-schema.json",
  "enabled": true,
  "strictness": "superpowers",
  "skip_patterns": [
    "**/*.md",
    "**/*.json",
    "**/config/**",
    "**/fixtures/**"
  ],
  "test_patterns": {
    "python": ["test_*.py", "*_test.py"],
    "javascript": ["*.test.js", "*.spec.js"],
    "dart": ["*_test.dart"]
  },
  "green_phase_limits": {
    "enabled": true,
    "max_lines_after_pass": 50,
    "max_new_functions": 3,
    "warn_on_exceed": true
  },
  "golden_testing_detection": {
    "enabled": true,
    "patterns": [
      {"pattern": "assert True", "severity": "error"},
      {"pattern": "assert False", "severity": "error"},
      {"pattern": "@skip", "severity": "warning"},
      {"pattern": "test.skip\\(", "severity": "warning"}
    ]
  },
  "state_persistence": {
    "enabled": true,
    "state_file": ".claude/tdd-state.yaml"
  }
}
```

### 多语言项目配置

```json
{
  "$schema": "tdd-config-schema.json",
  "enabled": true,
  "strictness": "strict",
  "test_patterns": {
    "python": ["test_*.py", "*_test.py"],
    "javascript": ["*.test.js", "*.spec.js", "*.test.ts", "*.spec.ts"],
    "dart": ["*_test.dart"],
    "go": ["*_test.go"]
  },
  "language_settings": {
    "python": {
      "framework": "pytest",
      "test_dir": "tests"
    },
    "javascript": {
      "framework": "jest",
      "test_dir": "__tests__"
    },
    "dart": {
      "framework": "flutter",
      "test_dir": "test"
    },
    "go": {
      "framework": "builtin",
      "test_dir": "."
    }
  }
}
```

---

## 完整工作流示例

### Python 项目

```bash
# 1. 项目结构
my_project/
├── src/
│   └── calculator.py
├── tests/
│   └── test_calculator.py
├── .claude/
│   └── tdd-config.json
└── pyproject.toml

# 2. 配置文件
cat .claude/tdd-config.json
{
  "enabled": true,
  "strictness": "strict"
}

# 3. RED 阶段
# 用户: "我要添加加法功能"

# TDD Enforcer 允许: 编辑测试文件
tests/test_calculator.py:
    def test_add_fails():
        result = add(2, 3)
        assert result == 100  # 故意错误

# 运行测试: pytest
# 结果: FAILED

# TDD Enforcer 允许: 编辑实现代码
src/calculator.py:
    def add(a, b):
        return a + b

# 4. GREEN 阶段
# 运行测试: pytest
# 结果: PASSED

# TDD Enforcer 状态: GREEN
# 如果继续编辑实现 → 拦截
# 如果添加新测试 → 允许
```

### Dart 项目

```dart
// RED 阶段 - 编写测试
test('add returns sum of two numbers', () {
  final result = MathUtils.add(2, 3);
  expect(result, equals(5));  // 会失败，函数不存在
});

// 运行: flutter test
// 结果: FAIL - NoSuchMethodError
// ✅ RED 完成

// GREEN 阶段 - 最小实现
class MathUtils {
  static int add(int a, int b) => a + b;
}

// 运行: flutter test
// 结果: PASS
// ✅ GREEN 完成

// REFACTOR 阶段 - 优化
class MathUtils {
  /// Returns the sum of two integers.
  static int add(int a, int b) => a + b;
}

// 运行: flutter test
// 结果: PASS
// ✅ REFACTOR 完成
```

---

## 常见场景

### 场景 1: 测试异步代码

```dart
test('fetchUser returns user data', () async {
  final service = UserService();
  final user = await service.fetchUser('user123');

  expect(user, isNotNull);
  expect(user.name, equals('Test User'));
});
```

### 场景 2: 测试异常情况

```dart
test('throw InvalidInputException for negative value', () {
  final calculator = Calculator();
  expect(
    () => calculator.sqrt(-1),
    throwsA(isA<InvalidInputException>()),
  );
});
```

### 场景 3: Mock 外部依赖

```dart
test('sendEmail uses email service', () async {
  final mockEmailService = MockEmailService();
  final notifier = NotificationNotifier(emailService: mockEmailService);

  await notifier.sendWelcomeEmail('user@example.com');

  verify(mockEmailService.send(
    to: 'user@example.com',
    subject: 'Welcome',
  )).called(1);
});
```

---

## FAQ

### Q: 如果测试一开始就通过了怎么办？

**A**: 检查以下几点：
1. 测试断言是否正确
2. 测试逻辑是否有效
3. 功能是否已存在

如果测试逻辑正确但功能已存在，考虑：
- 删除测试并重新编写
- 或添加新的测试用例

### Q: GREEN 阶段可以写"完美"的代码吗？

**A**: 不应该。GREEN 阶段只写使测试通过的最小代码：
- ❌ 不考虑错误处理
- ❌ 不考虑边界情况
- ❌ 不进行代码优化
- ✅ 仅满足当前测试用例

优化工作在 REFACTOR 阶段完成。

### Q: REFACTOR 阶段测试失败了怎么办？

**A**: 立即回滚重构：
```bash
git diff  # 查看变更
git checkout -- <files>  # 回滚
```
然后重新分析重构策略。

### Q: 什么时候跳过 TDD？

**A**:
- ✅ 文档修改
- ✅ 配置文件修改
- ✅ 紧急 hotfix (使用 `--bypass`)
- ❌ 业务逻辑开发
- ❌ Bug 修复

---

## 最佳实践

1. **小步快跑**: 每个测试用例只测试一个功能点
2. **描述性命名**: 测试名称应该描述被测试的行为
3. **AAA 模式**: Arrange (准备) → Act (执行) → Assert (断言)
4. **独立测试**: 测试之间不应该有依赖关系
5. **快速反馈**: 保持测试运行时间短

---

## 更多示例

- [examples/python/](examples/python/) - Python 完整示例
- [examples/javascript/](examples/javascript/) - JavaScript 完整示例
- [examples/dart/](examples/dart/) - Dart 完整示例

---

**最后更新**: 2026-02-06

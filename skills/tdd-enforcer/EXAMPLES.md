# TDD Enforcer 示例文档

> **版本**: 1.0.0
> **来源**: TASK-005
> **Skill**: tdd-enforcer

---

## 目录

1. [快速开始示例](#快速开始示例)
2. [完整工作流示例](#完整工作流示例)
3. [Bug 修复示例](#bug-修复示例)
4. [重构示例](#重构示例)
5. [常见场景](#常见场景)
6. [FAQ](#faq)

---

## 快速开始示例

### 示例 1: 简单函数开发

**需求**: 创建一个函数，将两个数字相加

#### RED 阶段

```dart
// test/math_utils_test.dart
import 'package:aria/math_utils.dart';

void main() {
  test('add returns sum of two numbers', () {
    final result = MathUtils.add(2, 3);
    expect(result, equals(5));
  });
}
```

```bash
$ flutter test test/math_utils_test.dart
FAIL: NoSuchMethodError: Method 'add' not found
✅ RED 阶段完成
```

#### GREEN 阶段

```dart
// lib/math_utils.dart
class MathUtils {
  static int add(int a, int b) {
    return a + b;
  }
}
```

```bash
$ flutter test test/math_utils_test.dart
PASS: 1/1 test passed
✅ GREEN 阶段完成
```

#### REFACTOR 阶段

```dart
// lib/math_utils.dart (refactored)
class MathUtils {
  /// Returns the sum of two integers.
  ///
  /// Example:
  /// ```dart
  /// MathUtils.add(2, 3) // returns 5
  /// ```
  static int add(int a, int b) => a + b;
}
```

```bash
$ flutter test test/math_utils_test.dart
PASS: 1/1 test passed
Code quality: Improved
✅ REFACTOR 阶段完成
```

---

## 完整工作流示例

### 示例 2: 用户认证功能

**需求**: 实现用户登录功能，验证用户名和密码

#### RED 阶段

```dart
// test/auth_service_test.dart
import 'package:aria/services/auth_service.dart';

void main() {
  group('AuthService', () {
    late AuthService authService;

    setUp(() {
      authService = AuthService();
    });

    test('authenticate returns token for valid credentials', () async {
      final result = await authService.authenticate('user123', 'password123');
      expect(result, isNotNull);
      expect(result?.token, isNotEmpty);
      expect(result?.userId, equals('user123'));
    });

    test('authenticate returns null for invalid credentials', () async {
      final result = await authService.authenticate('user123', 'wrongpassword');
      expect(result, isNull);
    });

    test('authenticate returns null for non-existent user', () async {
      final result = await authService.authenticate('nobody', 'password');
      expect(result, isNull);
    });
  });
}
```

```bash
$ flutter test test/auth_service_test.dart
FAIL: AuthService class not found
✅ RED 阶段完成 - 3 个测试用例定义清晰
```

#### GREEN 阶段

```dart
// lib/services/auth_service.dart
class AuthService {
  Future<AuthResult?> authenticate(String username, String password) async {
    // 模拟用户验证
    if (username == 'user123' && password == 'password123') {
      return AuthResult(
        token: 'mock_token_${DateTime.now().millisecondsSinceEpoch}',
        userId: username,
        expiresAt: DateTime.now().add(Duration(hours: 24)),
      );
    }
    return null;
  }
}

class AuthResult {
  final String token;
  final String userId;
  final DateTime expiresAt;

  AuthResult({
    required this.token,
    required this.userId,
    required this.expiresAt,
  });
}
```

```bash
$ flutter test test/auth_service_test.dart
PASS: 3/3 tests passed
✅ GREEN 阶段完成
```

#### REFACTOR 阶段

```dart
// lib/services/auth_service.dart (refactored)
class AuthService {
  // 依赖注入
  final UserRepository _userRepository;
  final TokenGenerator _tokenGenerator;

  AuthService({
    required UserRepository userRepository,
    required TokenGenerator tokenGenerator,
  })  : _userRepository = userRepository,
        _tokenGenerator = tokenGenerator;

  /// Authenticates a user with username and password.
  ///
  /// Returns [AuthResult] if authentication succeeds,
  /// otherwise returns `null`.
  Future<AuthResult?> authenticate(String username, String password) async {
    // 验证输入
    if (username.isEmpty || password.isEmpty) {
      return null;
    }

    // 查找用户
    final user = await _userRepository.findByUsername(username);
    if (user == null) {
      return null;
    }

    // 验证密码
    if (!user.verifyPassword(password)) {
      return null;
    }

    // 生成 token
    final token = _tokenGenerator.generate(user.id);

    return AuthResult(
      token: token,
      userId: user.id,
      expiresAt: DateTime.now().add(Duration(hours: 24)),
    );
  }
}
```

```bash
$ flutter test test/auth_service_test.dart
PASS: 3/3 tests passed
Code quality: +30%
✅ REFACTOR 阶段完成
```

---

## Bug 修复示例

### 示例 3: 修复登录崩溃问题

**问题**: 用户输入空字符串时应用崩溃

#### RED 阶段 - 复现 Bug

```dart
test('authenticate handles empty username gracefully', () async {
  final authService = AuthService();
  final result = await authService.authenticate('', 'password');
  // 应该返回 null 而不是崩溃
  expect(result, isNull);
});
```

```bash
$ flutter test test/auth_service_test.dart
FAIL: TypeError: Null check operator used on a null value
✅ RED 阶段完成 - Bug 已复现
```

#### GREEN 阶段 - 修复 Bug

```dart
Future<AuthResult?> authenticate(String username, String password) async {
  // 添加空值检查
  if (username.isEmpty || password.isEmpty) {
    return null;
  }
  // ... 原有逻辑
}
```

```bash
$ flutter test test/auth_service_test.dart
PASS: Bug fixed, test passes
✅ GREEN 阶段完成
```

#### REFACTOR 阶段 - 确保无回归

```bash
$ flutter test
PASS: All 4 tests pass (3 existing + 1 new)
✅ REFACTOR 阶段完成 - 无回归
```

---

## 重构示例

### 示例 4: 提取验证逻辑

**目标**: 将重复的验证逻辑提取到单独的类

#### RED 阶段 - 添加验证测试

```dart
test('CredentialValidator validates username format', () {
  expect(CredentialValidator.isValidUsername('user123'), isTrue);
  expect(CredentialValidator.isValidUsername('u'), isFalse);  // 太短
  expect(CredentialValidator.isValidUsername(''), isFalse);  // 空
});
```

#### GREEN 阶段 - 实现验证器

```dart
class CredentialValidator {
  static bool isValidUsername(String username) {
    return username.length >= 3;
  }
}
```

#### REFACTOR 阶段 - 使用验证器

```dart
// 重构前
Future<AuthResult?> authenticate(String username, String password) async {
  if (username.isEmpty || password.isEmpty) return null;
  if (username.length < 3) return null;
  // ...
}

// 重构后
Future<AuthResult?> authenticate(String username, String password) async {
  if (!CredentialValidator.isValidUsername(username)) return null;
  if (!CredentialValidator.isValidPassword(password)) return null;
  // ...
}
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

### Q: 如何处理复杂的测试设置？

**A**: 使用 `setUp` 和 `tearDown`:

```dart
group('DatabaseService', () {
  late DatabaseService db;

  setUp(() async {
    db = DatabaseService.memory();
    await db.initialize();
  });

  tearDown(() async {
    await db.close();
  });

  test('query returns results', () async {
    // 测试代码
  });
});
```

---

## 最佳实践

1. **小步快跑**: 每个测试用例只测试一个功能点
2. **描述性命名**: 测试名称应该描述被测试的行为
3. **AAA 模式**: Arrange (准备) → Act (执行) → Assert (断言)
4. **独立测试**: 测试之间不应该有依赖关系
5. **快速反馈**: 保持测试运行时间短

---

**版本**: 1.0.0
**创建**: 2026-01-18
**相关**: [workflow.md](./workflow.md) | [SKILL.md](./SKILL.md)

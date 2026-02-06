/// 计算器测试 - TDD 演示项目
///
/// 这个模块演示如何使用 TDD 方法编写测试。
///
/// TDD 流程:
/// 1. RED - 编写失败的测试
/// 2. GREEN - 编写最小实现使测试通过
/// 3. REFACTOR - 优化代码结构
library;

import 'package:dart_example/calculator.dart';
import 'package:test/test.dart';

void main() {
  group('Calculator', () {
    late Calculator calc;

    setUp(() {
      calc = Calculator();
    });

    group('add', () {
      group('RED 阶段示例', () {
        // 这是一个 RED 阶段的测试示例
        // 期望值故意设置错误，使测试失败
        test('should demonstrate RED phase (failing test)', () {
          final result = calc.add(2, 3);
          // 这个断言会失败 - RED 状态
          expect(result, 100, reason: '故意设置错误的期望值以演示 RED 阶段');
        });
      });

      group('GREEN 阶段示例', () {
        // 这些是 GREEN 阶段的测试
        // 期望值正确，测试通过

        test('should return sum of two positive numbers', () {
          expect(calc.add(5, 3), 8);
        });

        test('should return sum of negative numbers', () {
          expect(calc.add(-5, -3), -8);
        });

        test('should return sum of mixed sign numbers', () {
          expect(calc.add(-5, 10), 5);
        });

        test('should handle adding zero', () {
          expect(calc.add(5, 0), 5);
          expect(calc.add(0, 5), 5);
          expect(calc.add(0, 0), 0);
        });

        test('should handle decimal numbers', () {
          expect(calc.add(2.5, 3.5), 6.0);
        });
      });
    });

    group('subtract', () {
      test('should return difference of positive numbers', () {
        expect(calc.subtract(10, 3), 7);
      });

      test('should return negative result when subtracting larger number', () {
        expect(calc.subtract(3, 10), -7);
      });

      test('should handle subtracting zero', () {
        expect(calc.subtract(5, 0), 5);
      });
    });

    group('multiply', () {
      test('should return product of two numbers', () {
        expect(calc.multiply(3, 4), 12);
      });

      test('should return zero when multiplying by zero', () {
        expect(calc.multiply(5, 0), 0);
        expect(calc.multiply(0, 5), 0);
      });

      test('should handle negative numbers', () {
        expect(calc.multiply(-3, -4), 12);
        expect(calc.multiply(-3, 4), -12);
      });

      test('should handle decimal numbers', () {
        expect(calc.multiply(2.5, 4), 10.0);
      });
    });

    group('divide', () {
      test('should return quotient of two numbers', () {
        expect(calc.divide(10, 2), 5.0);
      });

      test('should return float for non-divisible numbers', () {
        expect(calc.divide(5, 2), 2.5);
      });

      test('should throw ArgumentError when dividing by zero', () {
        expect(() => calc.divide(5, 0), throwsArgumentError);
      });

      test('should handle decimal division', () {
        expect(calc.divide(7.5, 2.5), 3.0);
      });
    });

    // TDD 演示：金装甲测试示例 (Superpowers 模式会检测到)
    group('Golden Tests (DO NOT USE IN PRODUCTION)', () {
      // ❌ 金装甲测试 1: expect(true, true)
      test('golden test: always passes', () {
        // Superpowers 会检测到这个无意义的断言
        expect(true, true);
      });

      // ❌ 金装甲测试 2: expect(false, false)
      test('golden test: another always-passing assertion', () {
        // Superpowers 会检测到这个
        expect(false, false);
      });

      // ❌ 金装甲测试 3: 跳过测试
      test('golden test: skipped test', skip: true, () {
        // Superpowers 会检测到跳过标记
        expect(true, true);
      });

      // ❌ 金装甲测试 4: 跳过的 group
      group('golden test: skipped group', skip: true, () {
        test('should not run', () {
          expect(true, true);
        });
      });
    });
  });
}

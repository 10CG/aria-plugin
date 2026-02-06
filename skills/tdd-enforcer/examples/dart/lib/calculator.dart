/// 简单计算器示例 - TDD 演示项目
///
/// 这个模块演示如何使用 TDD 方法开发一个简单的计算器。
library;

/// 简单的数学计算器
///
/// 支持基本的算术运算：加、减、乘、除
class Calculator {
  /// 返回两个数的和
  ///
  /// [a] 第一个数
  /// [b] 第二个数
  /// 返回两数之和
  ///
  /// 示例:
  /// ```dart
  /// final calc = Calculator();
  /// calc.add(2, 3); // 5
  /// ```
  num add(num a, num b) {
    return a + b;
  }

  /// 返回两个数的差
  ///
  /// [a] 被减数
  /// [b] 减数
  /// 返回两数之差
  ///
  /// 示例:
  /// ```dart
  /// final calc = Calculator();
  /// calc.subtract(5, 3); // 2
  /// ```
  num subtract(num a, num b) {
    return a - b;
  }

  /// 返回两个数的积
  ///
  /// [a] 第一个数
  /// [b] 第二个数
  /// 返回两数之积
  ///
  /// 示例:
  /// ```dart
  /// final calc = Calculator();
  /// calc.multiply(3, 4); // 12
  /// ```
  num multiply(num a, num b) {
    return a * b;
  }

  /// 返回两个数的商
  ///
  /// [a] 被除数
  /// [b] 除数
  /// 返回两数之商
  ///
  /// 抛出 [ArgumentError] 当除数为零时
  ///
  /// 示例:
  /// ```dart
  /// final calc = Calculator();
  /// calc.divide(10, 2); // 5.0
  /// ```
  double divide(num a, num b) {
    if (b == 0) {
      throw ArgumentError('Cannot divide by zero');
    }
    return a / b;
  }
}

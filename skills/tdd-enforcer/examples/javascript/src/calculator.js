/**
 * 简单计算器示例 - TDD 演示项目
 *
 * 这个模块演示如何使用 TDD 方法开发一个简单的计算器。
 */

class Calculator {
  /**
   * 创建计算器实例
   */
  constructor() {
    this.result = 0;
  }

  /**
   * 返回两个数的和
   * @param {number} a - 第一个数
   * @param {number} b - 第二个数
   * @returns {number} 两数之和
   *
   * @example
   * const calc = new Calculator();
   * calc.add(2, 3); // 5
   */
  add(a, b) {
    return a + b;
  }

  /**
   * 返回两个数的差
   * @param {number} a - 被减数
   * @param {number} b - 减数
   * @returns {number} 两数之差
   *
   * @example
   * const calc = new Calculator();
   * calc.subtract(5, 3); // 2
   */
  subtract(a, b) {
    return a - b;
  }

  /**
   * 返回两个数的积
   * @param {number} a - 第一个数
   * @param {number} b - 第二个数
   * @returns {number} 两数之积
   *
   * @example
   * const calc = new Calculator();
   * calc.multiply(3, 4); // 12
   */
  multiply(a, b) {
    return a * b;
  }

  /**
   * 返回两个数的商
   * @param {number} a - 被除数
   * @param {number} b - 除数
   * @returns {number} 两数之商
   * @throws {Error} 当除数为零时
   *
   * @example
   * const calc = new Calculator();
   * calc.divide(10, 2); // 5
   */
  divide(a, b) {
    if (b === 0) {
      throw new Error('Cannot divide by zero');
    }
    return a / b;
  }
}

module.exports = Calculator;

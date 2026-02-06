/**
 * 计算器测试 - TDD 演示项目
 *
 * 这个模块演示如何使用 TDD 方法编写测试。
 *
 * TDD 流程:
 * 1. RED - 编写失败的测试
 * 2. GREEN - 编写最小实现使测试通过
 * 3. REFACTOR - 优化代码结构
 */

const Calculator = require('../src/calculator');

describe('Calculator', () => {
  let calc;

  beforeEach(() => {
    calc = new Calculator();
  });

  describe('add', () => {
    describe('RED 阶段示例', () => {
      // 这是一个 RED 阶段的测试示例
      // 期望值故意设置错误，使测试失败
      it('should demonstrate RED phase (failing test)', () => {
        const result = calc.add(2, 3);
        // 这个断言会失败 - RED 状态
        expect(result).toBe(100);
      });
    });

    describe('GREEN 阶段示例', () => {
      // 这些是 GREEN 阶段的测试
      // 期望值正确，测试通过
      it('should return sum of two positive numbers', () => {
        expect(calc.add(5, 3)).toBe(8);
      });

      it('should return sum of negative numbers', () => {
        expect(calc.add(-5, -3)).toBe(-8);
      });

      it('should return sum of mixed sign numbers', () => {
        expect(calc.add(-5, 10)).toBe(5);
      });

      it('should handle adding zero', () => {
        expect(calc.add(5, 0)).toBe(5);
        expect(calc.add(0, 5)).toBe(5);
        expect(calc.add(0, 0)).toBe(0);
      });
    });
  });

  describe('subtract', () => {
    it('should return difference of positive numbers', () => {
      expect(calc.subtract(10, 3)).toBe(7);
    });

    it('should return negative result when subtracting larger number', () => {
      expect(calc.subtract(3, 10)).toBe(-7);
    });

    it('should handle subtracting zero', () => {
      expect(calc.subtract(5, 0)).toBe(5);
    });
  });

  describe('multiply', () => {
    it('should return product of two numbers', () => {
      expect(calc.multiply(3, 4)).toBe(12);
    });

    it('should return zero when multiplying by zero', () => {
      expect(calc.multiply(5, 0)).toBe(0);
      expect(calc.multiply(0, 5)).toBe(0);
    });

    it('should handle negative numbers', () => {
      expect(calc.multiply(-3, -4)).toBe(12);
      expect(calc.multiply(-3, 4)).toBe(-12);
    });
  });

  describe('divide', () => {
    it('should return quotient of two numbers', () => {
      expect(calc.divide(10, 2)).toBe(5);
    });

    it('should return float for non-divisible numbers', () => {
      expect(calc.divide(5, 2)).toBe(2.5);
    });

    it('should throw error when dividing by zero', () => {
      expect(() => calc.divide(5, 0)).toThrow('Cannot divide by zero');
    });
  });

  // TDD 演示：金装甲测试示例 (Superpowers 模式会检测到)
  describe('Golden Tests (DO NOT USE IN PRODUCTION)', () => {
    // ❌ 金装甲测试 1: expect(true).toBe(true)
    it('golden test: always passes', () => {
      // Superpowers 会检测到这个无意义的断言
      expect(true).toBe(true);
    });

    // ❌ 金装甲测试 2: expect(false).toBe(false)
    it('golden test: another always-passing assertion', () => {
      // Superpowers 会检测到这个
      expect(false).toBe(false);
    });

    // ❌ 金装甲测试 3: 空测试
    it('golden test: empty test', () => {
      // 没有断言 - Superpowers 会检测到这个
      const result = 1 + 1;
    });

    // ❌ 金装甲测试 4: 跳过测试
    it.skip('golden test: skipped test', () => {
      // Superpowers 会检测到跳过标记
      expect(true).toBe(true);
    });

    // ❌ 金装甲测试 5: 跳过的 describe 块
    describe.skip('golden test: skipped describe block', () => {
      it('should not run', () => {
        expect(true).toBe(true);
      });
    });
  });
});

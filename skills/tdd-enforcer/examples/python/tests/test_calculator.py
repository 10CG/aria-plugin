"""
计算器测试 - TDD 演示项目

这个模块演示如何使用 TDD 方法编写测试。

TDD 流程:
1. RED - 编写失败的测试
2. GREEN - 编写最小实现使测试通过
3. REFACTOR - 优化代码结构
"""

import pytest

from calculator import Calculator


class TestCalculatorAdd:
    """加法功能测试"""

    def test_add_two_positive_numbers(self):
        """测试两个正数相加"""
        calc = Calculator()
        result = calc.add(5, 3)
        assert result == 8

    def test_add_negative_numbers(self):
        """测试负数相加"""
        calc = Calculator()
        result = calc.add(-5, -3)
        assert result == -8

    def test_add_mixed_sign_numbers(self):
        """测试混合符号数相加"""
        calc = Calculator()
        result = calc.add(-5, 10)
        assert result == 5

    def test_add_with_zero(self):
        """测试与零相加"""
        calc = Calculator()
        assert calc.add(5, 0) == 5
        assert calc.add(0, 5) == 5
        assert calc.add(0, 0) == 0


class TestCalculatorSubtract:
    """减法功能测试"""

    def test_subtract_positive_numbers(self):
        """测试正数相减"""
        calc = Calculator()
        result = calc.subtract(10, 3)
        assert result == 7

    def test_subtract_to_negative(self):
        """测试减法结果为负"""
        calc = Calculator()
        result = calc.subtract(3, 10)
        assert result == -7


class TestCalculatorMultiply:
    """乘法功能测试"""

    def test_multiply_positive_numbers(self):
        """测试正数相乘"""
        calc = Calculator()
        result = calc.multiply(3, 4)
        assert result == 12

    def test_multiply_by_zero(self):
        """测试乘以零"""
        calc = Calculator()
        assert calc.multiply(5, 0) == 0
        assert calc.multiply(0, 5) == 0

    def test_multiply_negative_numbers(self):
        """测试负数相乘"""
        calc = Calculator()
        result = calc.multiply(-3, -4)
        assert result == 12


class TestCalculatorDivide:
    """除法功能测试"""

    def test_divide_positive_numbers(self):
        """测试正数相除"""
        calc = Calculator()
        result = calc.divide(10, 2)
        assert result == 5.0

    def test_divide_returns_float(self):
        """测试除法返回浮点数"""
        calc = Calculator()
        result = calc.divide(5, 2)
        assert result == 2.5
        assert isinstance(result, float)

    def test_divide_by_zero_raises_error(self):
        """测试除以零抛出异常"""
        calc = Calculator()
        with pytest.raises(ZeroDivisionError):
            calc.divide(5, 0)


# TDD 演示：金装甲测试示例 (Superpowers 模式会检测到)

class TestGoldenTests:
    """
    这些是金装甲测试示例 - 不要在生产代码中使用！

    Superpowers 模式会检测并拦截这些测试。
    """

    # ❌ 金装甲测试 1: assert True
    def test_golden_assert_true(self):
        """这是一个金装甲测试 - 永远通过"""
        assert True  # Superpowers 会检测到这个

    # ❌ 金装甲测试 2: 空测试
    def test_golden_empty(self):
        """这是一个空测试 - 没有断言"""
        result = 1 + 1  # Superpowers 会检测到这个

    # ❌ 金装甲测试 3: 跳过测试
    @pytest.mark.skip
    def test_golden_skipped(self):
        """这是一个跳过的测试"""
        assert True  # Superpowers 会检测到这个

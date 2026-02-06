"""
简单计算器示例 - TDD 演示项目

这个模块演示如何使用 TDD 方法开发一个简单的计算器。
"""

from typing import Union


Number = Union[int, float]


class Calculator:
    """
    简单的数学计算器

    支持基本的算术运算：加、减、乘、除
    """

    def add(self, a: Number, b: Number) -> Number:
        """
        返回两个数的和

        Args:
            a: 第一个数
            b: 第二个数

        Returns:
            两数之和

        Examples:
            >>> calc = Calculator()
            >>> calc.add(2, 3)
            5
        """
        return a + b

    def subtract(self, a: Number, b: Number) -> Number:
        """
        返回两个数的差

        Args:
            a: 被减数
            b: 减数

        Returns:
            两数之差

        Examples:
            >>> calc = Calculator()
            >>> calc.subtract(5, 3)
            2
        """
        return a - b

    def multiply(self, a: Number, b: Number) -> Number:
        """
        返回两个数的积

        Args:
            a: 第一个数
            b: 第二个数

        Returns:
            两数之积

        Examples:
            >>> calc = Calculator()
            >>> calc.multiply(3, 4)
            12
        """
        return a * b

    def divide(self, a: Number, b: Number) -> Number:
        """
        返回两个数的商

        Args:
            a: 被除数
            b: 除数

        Returns:
            两数之商

        Raises:
            ZeroDivisionError: 当除数为零时

        Examples:
            >>> calc = Calculator()
            >>> calc.divide(10, 2)
            5.0
        """
        if b == 0:
            raise ZeroDivisionError("Cannot divide by zero")
        return a / b

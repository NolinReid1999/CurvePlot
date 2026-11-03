"""Bounded arithmetic for displayed tick labels only; never writes source values."""

import ast
import math
import operator
from functools import lru_cache

_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}


@lru_cache(maxsize=64)
def parse(expression):
    expression = expression.strip() or "x"
    if len(expression) > 128:
        raise ValueError("显示公式过长")
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, RecursionError) as error:
        raise ValueError("显示公式无效，例如 x/1000 或 x*2+5") from error
    nodes = list(ast.walk(tree))
    if len(nodes) > 32:
        raise ValueError("显示公式过于复杂")
    for node in nodes:
        if isinstance(node, ast.Name):
            if node.id != "x":
                raise ValueError("公式中仅可使用变量 x")
        elif isinstance(node, ast.Constant):
            if type(node.value) not in (int, float) or not math.isfinite(node.value):
                raise ValueError("公式中仅可使用有限数字")
        elif type(node) not in (
            ast.Expression,
            ast.Load,
            ast.BinOp,
            ast.UnaryOp,
            ast.UAdd,
            ast.USub,
            *_BINARY,
        ):
            raise ValueError("仅支持 x、数字、括号及加减乘除和乘方")
    return tree.body


def calculate(expression, x):
    def read(node):
        if isinstance(node, ast.Name):
            result = float(x)
        elif isinstance(node, ast.Constant):
            result = float(node.value)
        elif isinstance(node, ast.UnaryOp):
            result = read(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        else:
            a, b = read(node.left), read(node.right)
            if isinstance(node.op, ast.Pow) and abs(b) > 8:
                raise ValueError("乘方指数需在 -8 至 8 之间")
            result = _BINARY[type(node.op)](a, b)
        if (
            not isinstance(result, (int, float))
            or not math.isfinite(result)
            or abs(result) > 1e300
        ):
            raise ValueError("显示公式结果超出范围")
        return result

    try:
        return read(parse(expression))
    except (ArithmeticError, TypeError) as error:
        raise ValueError("此刻度的公式结果无效") from error

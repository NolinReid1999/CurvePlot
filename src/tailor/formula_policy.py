"""Restrict worksheet expressions to numerical operations before using asteval."""

import ast

FUNCTIONS = frozenset(
    [
        "abs",
        "sin",
        "cos",
        "tan",
        "arcsin",
        "arccos",
        "arctan",
        "arctan2",
        "exp",
        "log",
        "log10",
        "log2",
        "sqrt",
        "floor",
        "ceil",
        "round",
        "minimum",
        "maximum",
        "clip",
        "where",
        "mean",
        "sum",
        "std",
        "var",
        "median",
        "min",
        "max",
        "average",
        "nanmean",
        "nanstd",
        "nansum",
        "nanmin",
        "nanmax",
        "gradient",
        "diff",
        "cumsum",
        "cumprod",
        "isnan",
        "isfinite",
    ]
)
NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Call,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.keyword,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.UAdd,
    ast.USub,
    ast.Compare,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.BitAnd,
    ast.BitOr,
    ast.Invert,
    ast.IfExp,
)


def validate_formula(expression, variables):
    if not isinstance(expression, str) or len(expression) > 4096:
        raise ValueError("Expression is too long")
    tree = ast.parse(expression, mode="eval")
    nodes = list(ast.walk(tree))
    if len(nodes) > 256:
        raise ValueError("Expression is too complex")
    allowed = set(variables) | FUNCTIONS | {"pi", "e", "nan", "inf"}
    for node in nodes:
        if not isinstance(node, NODES):
            raise ValueError("Only numerical worksheet expressions are supported")  # noqa: TRY004 - invalid expression syntax
        if isinstance(node, ast.Name) and node.id not in allowed:
            raise ValueError(f"Unknown variable: {node.id}")
        if isinstance(node, ast.Call) and (
            not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS
        ):
            raise ValueError("Only supported numerical functions can be called")
        if isinstance(node, ast.Constant) and (
            not isinstance(node.value, (int, float, bool)) or abs(node.value) > 1e100
        ):
            raise ValueError("Only bounded numeric constants are supported")
        if (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Pow)
            and not any(isinstance(item, ast.Name) for item in ast.walk(node.left))
        ):
            try:
                exponent = ast.literal_eval(node.right)
            except (ValueError, TypeError) as exc:
                raise ValueError(
                    "Scalar powers require a bounded literal exponent"
                ) from exc
            if not isinstance(exponent, (int, float)) or abs(exponent) > 1024:
                raise ValueError("Unbounded scalar exponent")

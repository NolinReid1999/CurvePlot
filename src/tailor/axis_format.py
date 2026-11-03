"""Numeric tick labels; local 14B draft corrected after contract review."""

import math


def format_tick(value, notation="auto", precision=4):
    if (
        isinstance(precision, bool)
        or not isinstance(precision, int)
        or not 0 <= precision <= 12
        or notation not in {"auto", "fixed", "scientific"}
    ):
        raise ValueError("Invalid tick notation or precision")
    if not math.isfinite(value):
        return ""
    kind = {"auto": "g", "fixed": "f", "scientific": "e"}[notation]
    digits = max(1, precision) if notation == "auto" else precision
    result = format(value, f".{digits}{kind}")
    return result.lstrip("-") if float(result) == 0 else result

"""Pure, JSON-compatible summaries for the forthcoming analysis plugin layer.

Local model draft reviewed and corrected: preserve original row positions after
filtering missing values, reject bool ddof, and return native Python scalars.
"""

import numpy as np
import pandas as pd


def summarize(values, ddof=1, ignore_missing=True):
    """Summarize one numeric column without mutating its source values."""
    if type(ddof) is not int or ddof not in (0, 1):
        raise ValueError("ddof must be a Python integer 0 or 1")
    if type(ignore_missing) is not bool:
        raise ValueError("ignore_missing must be a boolean")
    try:
        array = np.asarray(values, dtype=float)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("Input must contain numeric values") from error
    if array.ndim != 1:
        raise ValueError("Input must be one-dimensional")

    positions = np.flatnonzero(np.isfinite(array))
    result = dict.fromkeys(
        ("mean", "std", "sem", "minimum", "maximum", "argmin", "argmax")
    )
    result.update(n_total=int(array.size), n_valid=int(positions.size))
    if not positions.size or (not ignore_missing and positions.size != array.size):
        return result

    column = pd.Series(array[positions], index=positions)
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        statistics = {
            "mean": column.mean(),
            "minimum": column.min(),
            "maximum": column.max(),
            "std": column.std(ddof=ddof) if len(column) > ddof else None,
            "sem": column.sem(ddof=ddof) if len(column) > ddof else None,
        }
    for name, value in statistics.items():
        # A library overflow is unavailable, never a non-standard JSON NaN/Inf.
        result[name] = (
            float(value) if value is not None and np.isfinite(value) else None
        )
    result.update(argmin=int(column.idxmin()), argmax=int(column.idxmax()))
    return result

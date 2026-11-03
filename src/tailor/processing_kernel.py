"""Small pure data processing adapter around NumPy, pandas and SciPy."""

import numpy as np
import pandas as pd
from numpy.polynomial import Polynomial
from scipy import ndimage, signal


def process_xy(
    x, y, method, window=5, value=0.0, reference=None, polyorder=2, edge="auto"
):
    x, y = np.array(x, dtype=float, copy=True), np.array(y, dtype=float, copy=True)
    if x.ndim != 1 or y.shape != x.shape or not x.size:
        raise ValueError("X/Y 必须为长度相同的非空一维数据。")
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("数据含缺失值或无穷值，请先清理或缩小范围。")
    if method in {"moving_average", "savgol", "block_average"} and (
        type(window) is not int or not 1 <= window <= len(y)
    ):
        raise ValueError("窗口点数必须为正整数且不超过数据点数。")
    if method == "moving_average":
        if edge != "auto":
            return x, ndimage.uniform_filter1d(y, size=window, mode=edge)
        return x, pd.Series(y).rolling(
            window, center=True, min_periods=1
        ).mean().to_numpy()
    elif method == "savgol":
        if window % 2 == 0 or window < 3:
            raise ValueError(
                "window must be an odd integer greater than or equal to 3 for savgol method."
            )
        if (
            not np.allclose(np.diff(x), np.diff(x)[0], rtol=1e-5, atol=1e-12)
            or not (np.diff(x) > 0).all()
        ):
            raise ValueError(
                "x must be evenly spaced and increasing for savgol method."
            )
        if not 0 <= polyorder < window:
            raise ValueError("平滑多项式阶数必须小于窗口点数。")
        return x, signal.savgol_filter(
            y,
            window_length=window,
            polyorder=int(polyorder),
            mode="interp" if edge == "auto" else edge,
        )
    elif method == "block_average":
        groups = np.arange(len(y)) // window
        return (
            pd.Series(x).groupby(groups).mean().to_numpy(),
            pd.Series(y).groupby(groups).mean().to_numpy(),
        )
    elif method == "baseline_constant":
        if not np.isfinite(value):
            raise ValueError(
                "value must be a finite number for baseline_constant method."
            )
        return x, y - float(value)
    elif method == "baseline_linear":
        k = max(1, len(y) // 10)
        bx = [x[:k].mean(), x[-k:].mean()]
        by = [y[:k].mean(), y[-k:].mean()]
        if bx[0] == bx[1]:
            raise ValueError("两端背景的平均 X 相同，无法建立直线基线。")
        baseline = Polynomial.fit(bx, by, 1)
        return x, y - baseline(x)
    elif method == "normalize_max":
        if np.max(np.abs(y)) == 0:
            raise ValueError("y must not be zero for normalize_max method.")
        return x, y / np.max(np.abs(y))
    elif method == "normalize_range":
        if np.min(y) == np.max(y):
            raise ValueError("y must not be constant for normalize_range method.")
        return x, (y - np.min(y)) / (np.max(y) - np.min(y))
    elif method == "subtract":
        if not (
            isinstance(reference, np.ndarray)
            and reference.ndim == 1
            and reference.size == y.size
            and np.isfinite(reference).all()
        ):
            raise ValueError(
                "reference must be a 1D array of the same shape as y with finite values for subtract method."
            )
        if not np.isfinite(value):
            raise ValueError("value must be a finite number for subtract method.")
        return x, y - reference * float(value)
    else:
        raise ValueError(f"Unknown method: {method}")

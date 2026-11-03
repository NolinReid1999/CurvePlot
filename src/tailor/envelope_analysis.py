"""Envelope and repeated-measurement adapters to installed SciPy/NumPy."""

import numpy as np
from scipy import interpolate, ndimage, signal

ENVELOPES = [
    ("Hilbert振幅包络", "envelope_hilbert"),
    ("峰值检测＋PCHIP", "envelope_peaks"),
    ("滑动最大/最小值", "envelope_sliding"),
]


def envelopes(x, y, method, options):
    return envelope_details(x, y, method, options)["series"]


def envelope_details(x, y, method, options):
    if len(x) < 4 or np.any(np.diff(x) <= 0):
        raise ValueError("包络要求至少4个点，X严格递增且无重复。")
    mode = options.get("envelope_output", "both")
    markers = {}
    if method == "envelope_hilbert":
        if not np.allclose(np.diff(x), np.diff(x)[0], rtol=1e-5, atol=1e-12):
            raise ValueError("Hilbert包络要求等间距X，请先重采样。")
        center = float(np.mean(y))
        # SciPy's analytic-signal envelope retains the even-length Nyquist bin.
        # The previous positive-bin bandpass silently discarded that component.
        amplitude = np.abs(signal.hilbert(y - center))
        upper, lower = center + amplitude, center - amplitude
    elif method == "envelope_sliding":
        window = int(options.get("window", 11))
        if not 2 <= window <= len(y):
            raise ValueError("滑动窗口须为2至有效点数之间。")
        upper = ndimage.maximum_filter1d(y, size=window, mode="nearest")
        lower = ndimage.minimum_filter1d(y, size=window, mode="nearest")
    else:
        prominence = float(options.get("prominence", 0))
        distance = int(options.get("distance", 1))
        output = []
        for name, values in (("上包络", y), ("下包络", -y)):
            if (mode == "upper" and name == "下包络") or (
                mode == "lower" and name == "上包络"
            ):
                output.append(None)
                continue
            peaks, _ = signal.find_peaks(
                values, prominence=prominence, distance=distance
            )
            if len(peaks) < 2:
                raise ValueError(
                    "峰值法的上/下包络均需至少两个有效峰；请调整显著性、最小间距或选用其他算法。"
                )
            # Include observed endpoints, never extrapolate outside the sampled X.
            anchors = np.unique(np.r_[0, peaks, len(x) - 1])
            anchor_y = values[anchors].copy()
            if options.get("endpoints", "observed") == "hold":
                anchor_y[0], anchor_y[-1] = values[peaks[0]], values[peaks[-1]]
            if options.get("show_marks", True):
                markers[name] = {"x": x[peaks], "y": y[peaks]}
            output.append(
                interpolate.PchipInterpolator(x[anchors], anchor_y, extrapolate=False)(
                    x
                )
            )
        upper, lower = output[0], -output[1] if output[1] is not None else None
    series = {
        name: values
        for name, values in [("上包络", upper), ("下包络", lower)]
        if mode == "both"
        or (name == "上包络" and mode == "upper")
        or (name == "下包络" and mode == "lower")
    }
    smooth = int(options.get("smooth", 1))
    if not 1 <= smooth <= len(y):
        raise ValueError("包络平滑窗口须在1至有效点数之间。")
    if smooth > 1:
        series = {
            k: ndimage.uniform_filter1d(v, size=smooth, mode="nearest")
            for k, v in series.items()
        }
    return {"series": series, "markers": markers}


def repeated_measurements(x, matrix, error="sd", minimum_count=1):
    matrix = np.asarray(matrix, dtype=float)
    if matrix.ndim != 2 or len(matrix) < 2 or matrix.shape[1] != len(x):
        raise ValueError("重复测量至少需要同表、同X的两列Y。")
    matrix = np.where(np.isfinite(matrix), matrix, np.nan)
    count = np.sum(np.isfinite(matrix), axis=0)
    mean = np.divide(
        np.nansum(matrix, axis=0), count, out=np.full(len(x), np.nan), where=count > 0
    )
    variance = np.divide(
        np.nansum((matrix - mean) ** 2, axis=0),
        count - 1,
        out=np.full(len(x), np.nan),
        where=count > 1,
    )
    spread = np.sqrt(variance)
    if error == "sem":
        spread = np.divide(
            spread, np.sqrt(count), out=np.full(len(x), np.nan), where=count > 1
        )
    if np.isinf(mean).any() or np.isinf(spread).any():
        raise ValueError('重复测量数值溢出，请先缩放数据后处理。')
    threshold=max(1,int(minimum_count))
    mean[count<threshold]=np.nan
    spread[count<threshold]=np.nan
    return {
        "x": np.asarray(x),
        "y": None,
        "metrics": {},
        "aligned": True,
        "series": {
            "均值": mean,
            "SEM" if error == "sem" else "SD": spread,
            "有效次数N": count.astype(float),
        },
    }

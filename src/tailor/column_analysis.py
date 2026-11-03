"""Column-operation adapters to NumPy/SciPy; never mutate source snapshots.

Reuse: scipy integrate/_quadrature.py, interpolate/_cubic.py and signal's SOS
filter examples (BSD-3-Clause); calls stay in the installed SciPy implementation.
"""

import numpy as np
from scipy import fft, integrate, interpolate, signal, stats

from tailor.processing_kernel import process_xy

STATISTICS = {
    "mean": "均值",
    "median": "中位数",
    "std": "标准差",
    "sem": "标准误",
    "q1": "Q1",
    "q2": "Q2",
    "q3": "Q3",
    "min": "最小值",
    "max": "最大值",
    "count": "有效点数",
}
PREPROCESS = [
    ("移动平均", "moving_average"),
    ("Savitzky–Golay平滑", "savgol"),
    ("分组平均", "block_average"),
    ("减常数基线", "baseline_constant"),
    ("减直线基线", "baseline_linear"),
    ("参考列相减", "subtract"),
    ("最大绝对值归一化", "normalize_max"),
    ("0–1归一化", "normalize_range"),
]
MATHEMATICS = [
    ("微分 · dy/dx", "derivative"),
    ("积分 · ∫y dx", "integral"),
    ("累计积分 · ∫₀ˣy dx", "cumulative"),
    ("插值 · y(x)", "interpolate"),
    ("重采样 · 等间距X", "resample"),
    ("相加 · α＋β", "add"),
    ("相减 · α−β", "subtract_columns"),
    ("相乘 · α×β", "multiply"),
    ("相除 · α÷β", "divide"),
]
SIGNALS = [
    ("FFT · 单边幅度谱", "fft_amplitude"),
    ("FFT · 功率谱密度", "fft_power"),
    ("低通滤波", "lowpass"),
    ("高通滤波", "highpass"),
    ("带通滤波", "bandpass"),
    ("带阻滤波", "bandstop"),
]
REGIONS = [
    ("描述统计", "region_stats"),
    ("定积分/面积", "region_integral"),
    ("累计积分", "cumulative"),
    ("线性斜率", "region_slope"),
    ("极值及其位置", "extrema"),
]
BINARY = {"add", "subtract_columns", "multiply", "divide", "subtract"}


def aligned_reference(x, reference, align=False):
    if reference is None:
        raise ValueError("请选择参考列。")
    rx, ry = (np.asarray(a, dtype=float) for a in reference)
    if len(rx) == len(x) and np.array_equal(rx, x):
        return ry
    if not align:
        raise ValueError("X不一致，请显式选择“线性插值对齐”；不会自动按行错配。")
    good = np.isfinite(rx) & np.isfinite(ry)
    rx, ry = rx[good], ry[good]
    order = np.argsort(rx)
    rx, ry = rx[order], ry[order]
    if len(rx) < 2 or np.any(np.diff(rx) <= 0):
        raise ValueError("参考X须至少两个互异有效点。")
    if np.min(x) < rx[0] or np.max(x) > rx[-1]:
        raise ValueError("对象X超出参考列范围；请缩小处理范围，不进行隐式外推。")
    return np.interp(x, rx, ry)


def analyze(x, y, method, options=None, reference=None):
    o = options or {}
    x, y = np.array(x, dtype=float, copy=True), np.array(y, dtype=float, copy=True)
    if x.ndim != 1 or y.shape != x.shape or not len(y):
        raise ValueError("处理范围没有有效数据。")
    result = {"x": x, "y": None, "metrics": {}, "aligned": True}
    finite = np.isfinite(y)
    if method in {"statistics", "region_stats"}:
        values = y[finite]
        if not len(values):
            raise ValueError("所选列没有有效数值。")
        ddof = int(o.get("ddof", 1))
        if ddof not in (0, 1):
            raise ValueError("统计自由度仅支持总体0或样本1。")
        if o.get("missing", "omit") == "reject" and not finite.all():
            raise ValueError("所选数据含缺失/非有限数值；请清理数据或选择忽略缺失。")
        std = float(np.std(values, ddof=ddof)) if len(values) > ddof else np.nan
        q = np.quantile(values, [0.25, 0.5, 0.75])
        metrics = {
            "mean": float(np.mean(values)),
            "median": float(np.median(values)),
            "std": std,
            "sem": std / np.sqrt(len(values)),
            "q1": q[0],
            "q2": q[1],
            "q3": q[2],
            "min": float(np.min(values)),
            "max": float(np.max(values)),
            "count": float(len(values)),
        }
        result["metrics"] = {
            STATISTICS[k]: metrics[k] for k in o.get("statistics", list(STATISTICS))
        }
        for name,value in result['metrics'].items():
            undefined_sample = name in {STATISTICS['std'],STATISTICS['sem']} and len(values)<=ddof
            if not np.isfinite(value) and not undefined_sample:
                raise ValueError('统计结果数值溢出，请先缩放数据后处理。')
        return result
    if not np.isfinite(x).all() or not finite.all():
        raise ValueError(
            "范围内含缺失值/无穷值；请缩小范围或清理后处理，原始数据保留。"
        )
    if method.startswith("envelope_"):
        from tailor.envelope_analysis import envelope_details

        result.update(envelope_details(x, y, method, o))
        result['metrics']={'起点X':float(x[0]),'终点X':float(x[-1]),'有效点数':float(len(x))}
        for label,values in result.get('series',{}).items():
            if not np.isfinite(values).all():
                raise ValueError('包络计算数值溢出，请先缩放数据后处理。')
            result['metrics'][label+'均值']=float(np.mean(values))
        if any(not np.isfinite(v) for v in result['metrics'].values()):
            raise ValueError('包络统计数值溢出，请先缩放数据后处理。')
        return result
    if method in BINARY:
        if reference is None and "reference_value" in o:
            b = np.full_like(x,float(o["reference_value"]))
        else:
            b = aligned_reference(x, reference, o.get("align", False))
        if not np.isfinite(b).all():
            raise ValueError("参考列包含缺失值。")
        if method == "divide" and np.any(b == 0):
            raise ValueError("参考列存在零，不能相除。")
        result["y"] = {
            "add": np.add,
            "subtract_columns": np.subtract,
            "multiply": np.multiply,
            "divide": np.divide,
            "subtract": lambda a, b: a - b * o.get("value", 1),
        }[method](y, b)
    elif method in {v for _, v in PREPROCESS}:
        xx, yy = process_xy(
            x,
            y,
            method,
            window=int(o.get("window", 5)),
            value=o.get("value", 0),
            polyorder=int(o.get("polyorder", 2)),
            edge=o.get("edge", "auto"),
        )
        result.update(x=xx, y=yy, aligned=len(xx) == len(x) and np.array_equal(xx, x))
    elif method in {
        "derivative",
        "integral",
        "region_integral",
        "cumulative",
        "interpolate",
        "resample",
        "region_slope",
        "extrema",
    }:
        if len(x) < 2:
            raise ValueError("该方法至少需要两个点。")
        if method == "extrema":
            i, j = int(np.argmin(y)), int(np.argmax(y))
            result["metrics"] = {
                "最小值": y[i],
                "最小值X": x[i],
                "最大值": y[j],
                "最大值X": x[j],
            }
            result.update(x=np.asarray([x[i],x[j]]),y=np.asarray([y[i],y[j]]),aligned=False)
            return result
        if np.any(np.diff(x) <= 0):
            raise ValueError("X须严格递增且无重复，未自动改变原始点顺序。")
        if method == "derivative":
            result["y"] = np.gradient(y, x, edge_order=2 if len(x) > 2 else 1)
        elif method in {"integral", "region_integral"}:
            values=y
            if method=='region_integral' and o.get('region_baseline')=='endpoints':
                values=y-np.interp(x,[x[0],x[-1]],[y[0],y[-1]])
            result["metrics"] = {"积分": float(integrate.trapezoid(values, x)),"起点X":float(x[0]),"终点X":float(x[-1])}
            if method=='region_integral':result['y']=values
        elif method == "cumulative":
            result["y"] = integrate.cumulative_trapezoid(y, x, initial=0)
        elif method == "region_slope":
            fit = stats.linregress(x, y)
            result['y']=fit.intercept+fit.slope*x
            result["metrics"] = {
                "斜率": fit.slope,
                "截距": fit.intercept,
                "R²": fit.rvalue**2,
                "斜率标准误": fit.stderr,
            }
        else:
            count = int(o.get("points", len(x)))
            if not 2 <= count <= 1000000:
                raise ValueError("采样点数需在2到1000000之间。")
            if o.get("sampling", "points") == "step":
                step = float(o.get("step", 1))
                if not np.isfinite(step) or step <= 0:
                    raise ValueError("采样步长必须为正数。")
                count = int(np.floor((x[-1] - x[0]) / step + 1e-10)) + 1
                if not 2 <= count <= 1000000:
                    raise ValueError("该步长生成的点数须在2到1000000之间。")
                grid = x[0] + np.arange(count) * step
            else:
                grid = np.linspace(x[0], x[-1], count)
            kind = o.get("interpolation", "linear")
            curve = (
                interpolate.PchipInterpolator(x, y, extrapolate=False)
                if kind == "pchip"
                else interpolate.CubicSpline(x, y, extrapolate=False)
                if kind == "cubic"
                else interpolate.interp1d(x, y, kind="linear", bounds_error=True)
            )
            result.update(x=grid, y=curve(grid), aligned=False)
    elif method in {v for _, v in SIGNALS}:
        if method.startswith("fft_") and o.get("detrend", "none") != "none":
            y = signal.detrend(y, type=o["detrend"])
        if (
            len(x) < 4
            or np.any(np.diff(x) <= 0)
            or not np.allclose(np.diff(x), np.diff(x)[0], rtol=1e-5, atol=1e-12)
        ):
            raise ValueError("FFT和滤波要求至少4个等间距递增X；请先重采样。")
        fs = 1 / float(np.diff(x)[0])
        window = o.get("fft_window", "boxcar")
        if method == "fft_amplitude":
            weights = signal.get_window(window, len(y))
            amp = np.abs(fft.rfft(y * weights)) / weights.sum()
            amp[1 : -1 if len(y) % 2 == 0 else None] *= 2
            result.update(x=fft.rfftfreq(len(y), 1 / fs), y=amp, aligned=False)
        elif method == "fft_power":
            freq, power = signal.periodogram(
                y, fs=fs, window=window, detrend=False, scaling="density"
            )
            result.update(x=freq, y=power, aligned=False)
        else:
            lo, hi = float(o.get("cutoff", 0.1)), float(o.get("cutoff2", 0.3))
            cutoff = [lo, hi] if method in {"bandpass", "bandstop"} else lo
            if not 0 < lo < fs / 2 or (
                isinstance(cutoff, list) and not lo < hi < fs / 2
            ):
                raise ValueError(
                    f"截止频率须大于0且低于奈奎斯特频率 {fs / 2:.8g}，带通/带阻上下限须递增。"
                )
            sos = signal.butter(
                int(o.get("order", 4)), cutoff, btype=method, fs=fs, output="sos"
            )
            try:
                result["y"] = signal.sosfiltfilt(sos, y)
            except ValueError as error:
                raise ValueError(
                    "有效点数不足以执行该阶数的零相位滤波，请增加点数或降低阶数。"
                ) from error
    else:
        raise ValueError("未知处理方法。")
    if any(not np.isfinite(v) for v in result['metrics'].values()):
        raise ValueError('计算结果数值溢出，请先缩放数据后处理。')
    if result["y"] is not None and not np.isfinite(result["y"]).all():
        raise ValueError("运算产生无穷值或溢出；未生成结果。")
    return result

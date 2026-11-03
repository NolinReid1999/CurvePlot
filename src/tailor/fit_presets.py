"""Common lmfit model metadata used by the existing Tailor fitting UI."""

from dataclasses import dataclass

from lmfit.models import (
    ExponentialModel,
    GaussianModel,
    LinearModel,
    LorentzianModel,
    PolynomialModel,
    QuadraticModel,
    SineModel,
)


@dataclass(frozen=True)
class FitPreset:
    key: str
    title: str
    expression: str
    has_offset: bool
    peak: bool


LINEAR = FitPreset(
    key="linear",
    title="线性",
    expression="slope*x+intercept",
    has_offset=False,
    peak=False,
)

QUADRATIC = FitPreset(
    key="quadratic",
    title="二次多项式",
    expression="a*x**2+b*x+c",
    has_offset=False,
    peak=False,
)

GAUSSIAN = FitPreset(
    key="gaussian",
    title="Gaussian（含常数基线）",
    expression="offset+gaussian(x, amplitude, center, sigma)",
    has_offset=True,
    peak=True,
)

LORENTZIAN = FitPreset(
    key="lorentzian",
    title="Lorentzian（含常数基线）",
    expression="offset+lorentzian(x, amplitude, center, sigma)",
    has_offset=True,
    peak=True,
)

EXPONENTIAL = FitPreset(
    key="exponential",
    title="指数衰减（含常数基线）",
    expression="offset+exponential(x, amplitude, decay)",
    has_offset=True,
    peak=False,
)


DOUBLE_GAUSSIAN = FitPreset(
    "double_gaussian",
    "双高斯（常数基线）",
    "offset+gaussian(x,p1_amplitude,p1_center,p1_sigma)+gaussian(x,p2_amplitude,p2_center,p2_sigma)",
    True,
    True,
)
DOUBLE_LORENTZIAN = FitPreset(
    "double_lorentzian",
    "双洛伦兹（常数基线）",
    "offset+lorentzian(x,p1_amplitude,p1_center,p1_sigma)+lorentzian(x,p2_amplitude,p2_center,p2_sigma)",
    True,
    True,
)
SINE = FitPreset(
    "sine", "正弦（常数偏置）", "offset+amplitude*sin(frequency*x+shift)", True, False
)
DAMPED_SINE = FitPreset(
    "damped_sine",
    "阻尼正弦（常数偏置）",
    "offset+amplitude*exp(-(x-origin)/decay)*sin(frequency*(x-origin)+shift)",
    True,
    False,
)
POLYNOMIALS = tuple(
    FitPreset(
        f"polynomial_{degree}",
        f"{degree} 次多项式",
        "+".join(f"c{i}*x**{i}" for i in range(degree + 1)),
        False,
        False,
    )
    for degree in range(3, 7)
)
TREND_PRESETS = (
    FitPreset("trend_power", "幂函数趋势", "offset+amplitude*x**exponent", True, False),
    FitPreset("trend_log", "对数趋势", "offset+amplitude*log(x+shift)", True, False),
    FitPreset("trend_exp", "指数趋势", "offset+amplitude*exp(rate*x)", True, False),
    FitPreset(
        "trend_piece2",
        "两段线性趋势",
        "intercept+slope*x+delta*maximum(0,x-breakpoint)",
        False,
        False,
    ),
    FitPreset(
        "trend_piece3",
        "三段线性趋势",
        "intercept+slope*x+delta*maximum(0,x-breakpoint)+delta2*maximum(0,x-breakpoint2)",
        False,
        False,
    ),
)
PRESETS = (
    *TREND_PRESETS,
    LINEAR,
    QUADRATIC,
    *POLYNOMIALS,
    GAUSSIAN,
    LORENTZIAN,
    DOUBLE_GAUSSIAN,
    DOUBLE_LORENTZIAN,
    SINE,
    DAMPED_SINE,
    EXPONENTIAL,
)


def list_presets():
    return PRESETS


def get_preset(key):
    if isinstance(key, str) and key.startswith(
        ("multi_gaussian_", "multi_lorentzian_")
    ):
        family, n = key[len("multi_") :].rsplit("_", 1)
        n = int(n)
        if not 2 <= n <= 20:
            raise ValueError("峰数需在2到20之间")
        expression = "offset+" + "+".join(
            f"{family}(x,p{i}_amplitude,p{i}_center,p{i}_sigma)"
            for i in range(1, n + 1)
        )
        return FitPreset(key, f"{n}峰 {family}", expression, True, True)
    for preset in PRESETS:
        if preset.key == key:
            return preset
    raise ValueError(f"Unknown preset key: {key}")


def create_library_model(key):
    if key.startswith("multi_"):
        get_preset(key)
        family, n = key[len("multi_") :].rsplit("_", 1)
        cls = GaussianModel if family == "gaussian" else LorentzianModel
        parts = [cls(prefix=f"p{i}_") for i in range(1, int(n) + 1)]
        model = parts[0]
        for component in parts[1:]:
            model += component
        return model
    if key.startswith("polynomial_"):
        return PolynomialModel(degree=int(key.rsplit("_", 1)[1]))
    if key in {"sine", "damped_sine"}:
        return SineModel()
    if key in {"double_gaussian", "double_lorentzian"}:
        cls = GaussianModel if key == "double_gaussian" else LorentzianModel
        return cls(prefix="p1_") + cls(prefix="p2_")
    if key == "linear":
        return LinearModel()
    elif key == "quadratic":
        return QuadraticModel()
    elif key == "gaussian":
        return GaussianModel()
    elif key == "lorentzian":
        return LorentzianModel()
    elif key == "exponential":
        return ExponentialModel()
    else:
        raise ValueError(f"Unknown preset key: {key}")


def guess_parameters(key, x, y):
    """Initial-value adapter; optimization remains in Tailor/lmfit."""
    import numpy as np
    from scipy.signal import find_peaks

    preset = get_preset(key)
    x, y = np.asarray(x), np.asarray(y)
    if key.startswith("multi_"):
        n = int(key.rsplit("_", 1)[1])
        baseline = np.median(
            np.r_[y[: max(1, len(y) // 20)], y[-max(1, len(y) // 20) :]]
        )
        sign = -1 if baseline - y.min() > y.max() - baseline else 1
        peaks, _ = find_peaks(sign * (y - baseline), distance=max(1, len(y) // (n * 4)))
        ranked = sorted(peaks, key=lambda i: sign * (y[i] - baseline), reverse=True)[:n]
        centers = (
            sorted(x[ranked])
            if len(ranked) == n
            else np.quantile(x, np.linspace(0, 1, n + 2)[1:-1])
        )
        return peak_seeds(key, x, y, centers)
    if key.startswith("trend_"):
        from lmfit.models import LinearModel, PowerLawModel

        inf = float("inf")
        if len(x) < 3 or np.ptp(x) <= 0:
            raise ValueError("有效点不足或 X 没有变化")
        if key == "trend_power":
            positive = (x > 0) & (y > 0)
            if positive.sum() < 3:
                raise ValueError("幂函数趋势初值需要至少三个 X、Y 为正的数据点")
            params = PowerLawModel().guess(y[positive], x=x[positive])
            return {
                "offset": (0, -inf, inf),
                "amplitude": (float(params["amplitude"]), -inf, inf),
                "exponent": (float(params["exponent"]), -inf, inf),
            }
        if key == "trend_log":
            if np.any(x <= 0):
                raise ValueError("对数趋势要求 X 为正")
            params = LinearModel().guess(y, x=np.log(x))
            return {
                "offset": (float(params["intercept"]), -inf, inf),
                "amplitude": (float(params["slope"]), -inf, inf),
                "shift": (0, -float(np.min(x)) * 0.99, inf),
            }
        if key == "trend_exp":
            if not np.any(y > 0):
                raise ValueError("指数趋势初值需要正的 Y 数据")
            good = y > 0
            params = LinearModel().guess(np.log(y[good]), x=x[good])
            return {
                "offset": (0, -inf, inf),
                "amplitude": (float(np.exp(params["intercept"])), 0, inf),
                "rate": (float(params["slope"]), -inf, inf),
            }
        params = LinearModel().guess(y, x=x)
        first, second = np.quantile(x, [0.33, 0.67])
        eps = np.finfo(float).eps
        seeds = {
            "intercept": (float(params["intercept"]), -inf, inf),
            "slope": (float(params["slope"]), -inf, inf),
            "delta": (0.01, -inf, inf),
            "breakpoint": (
                float(first),
                float(x.min() + eps),
                float(np.median(x)) if key == "trend_piece3" else float(x.max() - eps),
            ),
        }
        if key == "trend_piece3":
            seeds.update(
                delta2=(0.01, -inf, inf),
                breakpoint2=(float(second), float(np.median(x)), float(x.max() - eps)),
            )
        return seeds
    order = np.argsort(x)
    x, y = x[order], y[order]
    if len(x) < 3 or np.ptp(x) <= 0:
        raise ValueError("有效点不足或 X 没有变化")
    offset = 0.0
    negative = False
    if preset.peak:
        edge = max(1, len(x) // 20)
        offset = float(np.median(np.r_[y[:edge], y[-edge:]]))
        negative = offset - y.min() > y.max() - offset
    elif key in {"sine", "damped_sine"}:
        offset = float(np.mean(y))
    elif preset.has_offset:
        offset = float(y[-1])
    native = create_library_model(key)
    if key.startswith("double_"):
        sign = -1 if negative else 1
        peaks, _ = find_peaks(sign * (y - offset), distance=max(1, len(x) // 15))
        ranked = sorted(peaks, key=lambda i: sign * (y[i] - offset), reverse=True)[:2]
        centers = (
            sorted(x[ranked]) if len(ranked) == 2 else np.quantile(x, [0.33, 0.67])
        )
        middle = float(np.mean(centers))
        params = native.make_params()
        for component, mask, center in zip(
            native.components, (x <= middle, x > middle), centers
        ):
            if mask.sum() >= 3 and np.ptp(x[mask]) > 0:
                guessed = component.guess(
                    y[mask] - offset, x=x[mask], negative=negative
                )
                params.update(guessed)
            else:
                params[component.prefix + "amplitude"].set(
                    value=float(np.ptp(y) * np.ptp(x) / 6) * sign
                )
                params[component.prefix + "sigma"].set(
                    value=float(np.ptp(x) / 10), min=0
                )
            params[component.prefix + "center"].set(
                value=float(center), min=float(x.min()), max=float(x.max())
            )
    elif key in {"sine", "damped_sine"}:
        # Native SineModel.guess expects evenly spaced ascending samples.
        unique, index = np.unique(x, return_index=True)
        grid = np.linspace(unique[0], unique[-1], min(4096, len(unique)))
        yy = np.interp(grid, unique, y[index] - offset)
        params = native.guess(yy, x=grid - (x[0] if key == "damped_sine" else 0))
    else:
        params = native.guess(
            y - offset, x=x, **({"negative": negative} if preset.peak else {})
        )
    seeds = {
        name: (float(v.value), float(v.min), float(v.max))
        for name, v in params.items()
        if v.expr is None
    }
    if preset.has_offset:
        seeds["offset"] = (offset, -np.inf, np.inf)
    if key in {"exponential", "damped_sine"}:
        value = seeds.get("decay", (np.ptp(x) / 2, 0, np.inf))[0]
        seeds["decay"] = (
            max(abs(value), np.finfo(float).eps),
            np.finfo(float).eps,
            np.inf,
        )
    if key == "damped_sine":
        seeds["origin"] = (float(x[0]), -np.inf, np.inf)
    return seeds


def peak_seeds(key, x, y, centers):
    """Adapt lmfit's prefixed peak models (builtin_models, multi-peak example)."""
    import numpy as np

    x, y = np.asarray(x), np.asarray(y)
    order = np.argsort(x)
    x, y = x[order], y[order]
    if len(x) < 3 or np.ptp(x) <= 0:
        raise ValueError("至少需要3个有效点和变化的X")
    native = create_library_model(key)
    edge = max(1, len(x) // 20)
    baseline = float(np.median(np.r_[y[:edge], y[-edge:]]))
    negative = baseline - y.min() > y.max() - baseline
    boundaries = np.r_[
        -np.inf, (np.asarray(centers[:-1]) + np.asarray(centers[1:])) / 2, np.inf
    ]
    params = native.make_params()
    for component, center, low, high in zip(
        native.components, centers, boundaries[:-1], boundaries[1:], strict=True
    ):
        mask = (x >= low) & (x <= high)
        if mask.sum() >= 3:
            params.update(
                component.guess(y[mask] - baseline, x=x[mask], negative=negative)
            )
        else:
            sigma = max(np.ptp(x) / (len(centers) * 8), np.finfo(float).eps)
            height = float(y[np.argmin(abs(x - center))] - baseline)
            area = height * sigma * (np.sqrt(2 * np.pi) if "gaussian" in key else np.pi)
            params[component.prefix + "sigma"].set(value=sigma, min=np.finfo(float).eps)
            params[component.prefix + "amplitude"].set(value=area)
        params[component.prefix + "center"].set(
            value=float(center), min=float(x.min()), max=float(x.max())
        )
    seeds = {
        name: (float(v.value), float(v.min), float(v.max))
        for name, v in params.items()
        if v.expr is None
    }
    seeds["offset"] = (baseline, -np.inf, np.inf)
    return seeds

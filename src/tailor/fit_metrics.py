"""Small numerical summaries for stored fit results."""

import numpy as np


def fit_statistics(y, predicted, nvarys):
    y, predicted = np.asarray(y, dtype=float), np.asarray(predicted, dtype=float)
    if (
        y.ndim != 1
        or y.shape != predicted.shape
        or not y.size
        or not np.all(np.isfinite(y))
        or not np.all(np.isfinite(predicted))
    ):
        raise ValueError("Invalid or empty arrays")
    if not isinstance(nvarys, (int, np.integer)) or nvarys < 0:
        raise ValueError("nvarys must be a nonnegative integer")

    residuals = y - predicted
    sse = np.sum(residuals**2)
    rmse = np.sqrt(sse / y.size)

    if np.all(y == y[0]):
        r2 = None
        adjusted_r2 = None
    else:
        ssr = sse
        sst = np.sum((y - np.mean(y)) ** 2)
        r2 = 1 - ssr / sst
        adjusted_r2 = (
            1 - (ssr / (y.size - nvarys)) / (sst / (y.size - 1))
            if y.size - nvarys > 0
            else None
        )

    return {
        "ndata": y.size,
        "nvarys": nvarys,
        "sse": sse,
        "rmse": rmse,
        "r2": r2,
        "adjusted_r2": adjusted_r2,
    }


def peak_features(kind, parameters):
    from tailor.fit_presets import create_library_model, get_preset

    if kind is None or not get_preset(kind).peak:
        return {}
    model = create_library_model(kind)

    params = model.make_params()
    for name, value in parameters.items():
        if name.endswith("sigma") and value <= 0:
            raise ValueError("Sigma must be positive")
        if name in params:
            params[name].value = value

    params.update_constraints()
    features = {}

    for prefix in [component.prefix for component in model.components]:
        amplitude = params[prefix + "amplitude"].value
        center = params[prefix + "center"].value
        fwhm = params[prefix + "fwhm"].value
        height = params[prefix + "height"].value
        area = amplitude

        features.update(
            {
                prefix + "fwhm": fwhm,
                prefix + "height": height,
                prefix + "center": center,
                prefix + "area": area,
            }
        )

    return features

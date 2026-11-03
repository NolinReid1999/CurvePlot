from copy import copy, deepcopy
from dataclasses import dataclass

import asteval
import lmfit
import numpy as np
import pandas as pd
import xxhash
from numpy.typing import ArrayLike

from tailor.cst_names import rename_variables
from tailor.data_model import DataModel


@dataclass
class Parameter:
    """A fit parameter with boundaries."""

    name: str
    value: float = 1.0
    min: float = float("-inf")
    max: float = float("inf")
    vary: bool = True


class FitError(Exception):
    """Error while performing fit procedure."""


class PlotModel:
    data_model: DataModel
    x_col: str
    y_col: str
    x_err_col: str | None
    y_err_col: str | None
    x_label: str = ""
    y_label: str = ""

    x_min: float | None = None
    x_max: float | None = None
    y_min: float | None = None
    y_max: float | None = None

    _model_expression: str = ""
    _model: lmfit.models.ExpressionModel | None = None
    _parameters: dict[str, Parameter]
    _fit_domain: tuple[float, float] = (float("-inf"), float("inf"))
    _use_fit_domain: bool = False
    _fit_data_checksum: int | None = None

    best_fit: lmfit.model.ModelResult | None = None
    fit_preset_key: str | None = None
    legend_label: str = ""
    legend_visible: bool = True

    def __init__(
        self,
        data_model: DataModel,
        x_col: str,
        y_col: str,
        x_err_col: str | None = None,
        y_err_col: str | None = None,
    ) -> None:
        self.data_model = data_model
        self.x_col = x_col
        self.y_col = y_col
        self.x_err_col = x_err_col
        self.y_err_col = y_err_col
        self._axis_modes = {}
        raw_x = pd.Series(data_model.get_column(x_col))
        if (
            raw_x.notna().any()
            and not pd.to_numeric(raw_x, errors="coerce").notna().any()
        ):
            dates = pd.to_datetime(raw_x, errors="coerce", utc=True, format="mixed")
            self._axis_modes["x"] = (
                "datetime"
                if dates.notna().sum() >= raw_x.notna().sum() * 0.8
                else "category"
            )
        self.x_label = self.get_x_col_name()
        self.y_label = self.get_y_col_name()

        self._parameters = {}
        self.fit_preset_key = None
        self._math_symbols = set(asteval.Interpreter().symtable.keys())

    def get_x_col_name(self) -> str:
        """Get the name of the x variable."""
        return self.data_model.get_column_name(self.x_col)

    def get_y_col_name(self) -> str:
        """Get the name of the y variable."""
        return self.data_model.get_column_name(self.y_col)

    def get_x_err_col_name(self) -> str:
        """Get the name of the x error variable.

        Returns:
            A string with the name of the variable or None if there is no such variable.
        """
        try:
            return self.data_model.get_column_name(self.x_err_col)
        except KeyError:
            return None

    def get_y_err_col_name(self) -> str:
        """Get the name of the y error variable.

        Returns:
            A string with the name of the variable or None if there is no such variable.
        """
        try:
            return self.data_model.get_column_name(self.y_err_col)
        except KeyError:
            return None

    def uses(self, model: DataModel, labels: list[str]) -> bool:
        """Test whether columns are in use by this plot.

        If the listed column labels are in use as an x, y axis or error flags,
        returns True, but only if the columns are from the same data sheet as
        this plot. For example, if you create a plot with columns 'time' and
        'position' from 'Sheet 2', then the columns 'time' and 'position' from
        'Sheet 1' are _not_ used.

        Args:
            model (DataModel): the data model containing the columns under test
            labels (list[str]): the column labels to check

        Returns:
            bool: True if any of the columns are in use.
        """
        if model is not self.data_model:
            return False
        return bool(
            set(labels) & {self.x_col, self.y_col, self.x_err_col, self.y_err_col}
        )

    def get_fit_domain(self) -> tuple[float, float]:
        """Get fit domain.

        Returns:
            tuple[float, float]: a tuple of xmin, xmax values.
        """
        return self._fit_domain

    def set_fit_domain(
        self, xmin: float | None = None, xmax: float | None = None
    ) -> None:
        """Set fit domain.

        Sets the fit domain to xmin, xmax. Either of these values may be None.
        In that case that value is not updated. This allows for only setting the
        lower or upper bound of the fit domain.

        Args:
            xmin (float | None, optional): The new lower bound. Defaults to None.
            xmax (float | None, optional): The new upper bound. Defaults to None.
        """
        new_min, new_max = self._fit_domain
        if xmin is not None:
            new_min = xmin
        if xmax is not None:
            new_max = xmax
        if (new_min, new_max) != self._fit_domain:
            self.best_fit = None
            self._fit_domain = (new_min, new_max)

    def get_fit_domain_enabled(self) -> bool:
        """Return if fit domain is used in fitting procedure.

        Returns:
            bool: True if fit domain is used, False otherwise.
        """
        return self._use_fit_domain

    def set_fit_domain_enabled(self, is_enabled: bool) -> None:
        """Set whether fit domain must be used in fitting procedure.

        If this setting is changed, the best fit is invalidated.

        Args:
            is_enabled (bool): True if fit domain must be used, False otherwise.
        """
        if self._use_fit_domain != is_enabled:
            self._use_fit_domain = is_enabled
            self.best_fit = None

    def get_data(self) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Get data values from model.

        If error values are not specified, returns 0.0 for all errors.

        Returns:
            A tuple of NumPy arrays containing x, y, x-error and y-error values.
        """
        df = self._get_data_as_dataframe()
        x, y, x_err, y_err = df.to_numpy().T

        return x, y, x_err, y_err

    def get_data_in_fit_domain(
        self,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Get data values from model in fit domain.

        If the fit domain is not specified, return all data. The fit domain
        bounds are inclusive.

        Returns:
            A tuple of NumPy arrays containing x, y, x-error and y-error values.
        """
        if hasattr(self, "_fit_input"):
            return self._fit_input
        from tailor.exclusions import rows_for

        if not self._use_fit_domain and not rows_for(
            self.data_model, (self.x_col, self.y_col, self.x_err_col, self.y_err_col)
        ):
            return self.get_data()
        df = self._get_data_as_dataframe(include_excluded=False)
        if self._use_fit_domain is False:
            return tuple(df.to_numpy().T)

        x0, x1 = self._fit_domain

        x = df["x"]
        df = df[(x0 <= x) & (x <= x1)]

        x, y, x_err, y_err = df.to_numpy().T
        return x, y, x_err, y_err

    def _get_data_as_dataframe(self, include_excluded=True) -> pd.DataFrame:
        """Get data values from model as dataframe.

        If error values are not specified, returns 0.0 for all errors.

        Returns:
            A Pandas DataFrame containing x, y, x-error and y-error values.
        """
        x = self.data_model.get_column(self.x_col)
        y = self.data_model.get_column(self.y_col)
        if self.x_err_col is not None:
            x_err = self.data_model.get_column(self.x_err_col)
        else:
            x_err = 0.0
        if self.y_err_col is not None:
            y_err = self.data_model.get_column(self.y_err_col)
        else:
            y_err = 0.0

        from tailor.axis_extensions import convert_series

        modes = getattr(self, "_axis_modes", {})
        x, x_labels = convert_series(x, modes.get("x", "numeric"))
        y, y_labels = convert_series(y, modes.get("y", "numeric"))
        self._axis_categories = {"x": x_labels, "y": y_labels}
        # Drop NaN and Inf values
        df = pd.DataFrame.from_dict({"x": x, "y": y, "x_err": x_err, "y_err": y_err})
        if not all(pd.api.types.is_numeric_dtype(dtype) for dtype in df.dtypes):
            df = df.apply(pd.to_numeric, errors="coerce")
        array=df.to_numpy()
        if array.dtype.kind not in 'biufc':
            array=df.to_numpy(dtype=float,na_value=np.nan)
        if np.any(array[:,2:]<0):
            raise ValueError("Uncertainty columns contain negative values")
        valid=np.isfinite(array).all(axis=1)
        if not valid.all():df=df.loc[valid]
        if not include_excluded:
            from tailor.exclusions import rows_for

            excluded = rows_for(
                self.data_model,
                [self.x_col, self.y_col, self.x_err_col, self.y_err_col],
            )
            df = df.loc[~df.index.isin(excluded)]
        return df

    def get_limits_from_data(self, padding=0.05) -> tuple[float]:
        """Get plot limits from the data points.

        Return the minimum and maximum values of the data points, taking the
        error bars into account.

        Args:
            padding: the relative amount of padding to add to the axis limits.
                Default is .05.

        Returns:
            Tuple of four float values (xmin, xmax, ymin, ymax).
        """
        x, y, x_err, y_err = self.get_data()

        try:
            xmin = float(np.min(x - x_err))
            xmax = float(np.max(x + x_err))
        except ValueError:
            xmin = -1
            xmax = 1
        try:
            ymin = float(np.min(y - y_err))
            ymax = float(np.max(y + y_err))
        except ValueError:
            ymin = -1
            ymax = 1

        xrange = xmax - xmin
        yrange = ymax - ymin

        xmin -= padding * xrange
        xmax += padding * xrange
        ymin -= padding * yrange
        ymax += padding * yrange

        return xmin, xmax, ymin, ymax

    def update_model_expression(self, expression: str, *, use_column_ids=False) -> bool:
        """Update the model expression.

        Update the stored (transformed) model expression independent of column
        names. After calling this method, the `parameters` attribute has an
        updated dictionary of model parameters.

        Note: a model should not only depend on the indepent (x) variable and
        parameters, not the values of other data columns.

        Args:
            expression (str): the model expression.

        Returns:
            True if the expression is successfully updated, False otherwise.
        """
        # Project files and preset adapters already contain stable column IDs.
        if not use_column_ids:
            self.fit_preset_key = None
        if not expression.strip():
            changed=bool(self._model_expression or self._parameters or self._model is not None)
            self._model_expression='';self._model=None;self._parameters={};self.best_fit=None
            return changed
        mapping = {self.data_model.get_column_name(self.x_col): self.x_col}
        try:
            transformed = (
                expression if use_column_ids else rename_variables(expression, mapping)
            )
        except SyntaxError:
            # expression could not be parsed
            if self._model_expression != expression:
                # expression was changed
                self._model_expression = expression
                self._model = None
                self.best_fit = None
                return True
            else:
                # expression was unchanged
                return False
        else:
            if self._model_expression != transformed:
                self._model_expression = transformed
                try:
                    self._model = lmfit.models.ExpressionModel(
                        transformed, independent_vars=[self.x_col]
                    )
                except ValueError:
                    # independent (x) variable not present in expression
                    self._model = None
                else:
                    self.update_model_parameters()
                self.best_fit = None
                return True
        return False

    def is_model_valid(self) -> bool:
        """Return if the model expression is a valid model.

        Returns:
            bool: True if the model is valid, False otherwise.
        """
        return self._model is not None

    def update_model_parameters(self):
        """Update model parameters.

        Comparing the stored model to the stored parameters, determine which
        parameters are newly-defined in the model and must be created and which
        stored parameters are no longer used in the model and must be discarded.
        """
        stored = set(self._parameters.keys())
        current = set(self._model.param_names)

        new = current - stored
        discard = stored - current

        # discard unneeded parameters
        for key in discard:
            self._parameters.pop(key)

        # Preserve the native expression parameter order in the existing UI.
        for key in self._model.param_names:
            if key in new:
                self._parameters[key] = Parameter(name=key)
        self._parameters = {
            key: self._parameters[key] for key in self._model.param_names
        }

    def get_parameter_names(self) -> list[str]:
        """Get the names of the model parameters.

        Returns:
            list[str]: a list of parameter names.
        """
        return list(self._parameters.keys())

    def get_parameter_by_name(self, name: str) -> Parameter:
        """Get parameter by name.

        Use the `get_parameter_names()` method to get a list of parameter names.

        Args:
            name (str): the name of the parameter.

        Returns:
            Parameter: the requested parameter object.
        """
        return self._parameters[name]

    def set_parameter_value(self, name: str, value: float) -> None:
        """Set initial value of a parameter.

        Setting a new initial value for the parameter will invalidate the best
        fit.

        Args:
            name (str): name of the parameter
            value (float): new initial value
        """
        self._parameters[name].value = value
        self.best_fit = None

    def set_parameter_min_value(self, name: str, value: float) -> None:
        """Set lower bound of a parameter.

        Setting a new lower bound will invalidate the best fit.

        Args:
            name (str): name of the parameter
            value (float): new lower bound
        """
        self._parameters[name].min = value
        self.best_fit = None

    def set_parameter_max_value(self, name: str, value: float) -> None:
        """Set upper bound of a parameter.

        Setting a new upper bound will invalidate the best fit.

        Args:
            name (str): name of the parameter
            value (float): new upper bound
        """
        self._parameters[name].max = value
        self.best_fit = None

    def set_parameter_vary_state(self, name: str, state: bool) -> None:
        """Set whether to vary a parameter value during fit.

        Setting the vary state to False will fix the parameter value.

        Args:
            name (str): name of the parameter
            state (bool): new vary state
        """
        self._parameters[name].vary = state
        self.best_fit = None

    def get_model_expression(self) -> str:
        """Get model expression.

        Note: a model should not only depend on the indepent (x) variable and
        parameters, not the values of other data columns.

        Returns:
            str: the model expression.
        """
        mapping = {
            self.x_col: "x"
            if self.fit_preset_key
            else self.data_model.get_column_name(self.x_col)
        }
        try:
            return rename_variables(self._model_expression, mapping)
        except SyntaxError:
            # expression could not be parsed
            return self._model_expression

    def evaluate_model(self, x: np.ndarray) -> np.ndarray | None:
        """Evaluate the fit model.

        Evaluate the fit model using the current values for the initial
        parameters at the supplied x-values. If no model is currently defined,
        return None.

        Args:
            x (np.ndarray): the x-values for which to evaluate the model.

        Returns:
            np.ndarray | None: the evaluated y-values or None
        """
        if self._model:
            kwargs = {k: v.value for k, v in self._parameters.items()}
            kwargs[self.x_col] = x
            return self._model.eval(**kwargs)
        else:
            return None

    def fit_snapshot(self):
        """Copy only fit inputs and rebuild the interpreter; never share live state."""
        snapshot = copy(self)
        snapshot._fit_input = tuple(
            np.array(values, copy=True) for values in self.get_data_in_fit_domain()
        )
        snapshot.data_model = None
        snapshot._parameters = deepcopy(self._parameters)
        snapshot._model = None
        if self._model is not None:
            snapshot._model = lmfit.models.ExpressionModel(
                self._model_expression, independent_vars=[self.x_col]
            )
            snapshot._model.param_hints = deepcopy(self._model.param_hints)
        snapshot.best_fit = None
        snapshot._fit_data_checksum = None
        return snapshot

    def perform_fit(self, iter_cb=None):
        """Reuse lmfit's executor with explicit validity and weighting checks."""
        self.best_fit = None
        self._fit_data_checksum = None
        try:
            if "category" in getattr(self, "_axis_modes", {}).values():
                raise ValueError("分类坐标仅用于绘图，数值拟合请使用数值或日期时间X。")
            if self._model is None:
                raise ValueError("请选择模型或填写有效公式。")
            for parameter in self._parameters.values():
                if (
                    not np.isfinite(parameter.value)
                    or np.isnan(parameter.min)
                    or np.isnan(parameter.max)
                    or parameter.min >= parameter.max
                    or not parameter.min <= parameter.value <= parameter.max
                ):
                    raise ValueError(f"参数 {parameter.name} 的初值或上下界无效。")
            params = self._model.make_params(
                **{
                    key: {
                        "min": value.min,
                        "value": value.value,
                        "max": value.max,
                        "vary": value.vary,
                    }
                    for key, value in self._parameters.items()
                }
            )
            data = self.get_data_in_fit_domain()
            x, y, _, y_err = data
            variables = sum(
                parameter.vary
                for parameter in params.values()
                if parameter.expr is None
            )
            if variables == 0 or len(x) < variables:
                raise ValueError("有效点不足，或全部参数已固定。请调整拟合区间和参数。")
            if self.fit_preset_key and np.ptp(x) == 0:
                raise ValueError("X 没有变化，不能确定该模型的参数。")
            if self.fit_preset_key in {"gaussian", "lorentzian"} and (
                params["sigma"].value <= 0 or params["sigma"].min < 0
            ):
                raise ValueError("峰模型 sigma 必须为正，且下界不能小于零。")
            if self.fit_preset_key == "exponential" and (
                params["decay"].value <= 0 or params["decay"].min < 0
            ):
                raise ValueError("指数衰减模型的 decay 必须为正，且下界不能小于零。")
            for name, parameter in params.items():
                if (
                    self.fit_preset_key
                    and (name.endswith("sigma") or name == "decay")
                    and (parameter.value <= 0 or parameter.min < 0)
                ):
                    raise ValueError(f"{name} 必须为正，且下界不能小于零。")
            weights = None
            if self.y_err_col is not None:
                if np.any(y_err <= 0):
                    raise ValueError(
                        "用于加权的 Y 误差必须全部为正；请修正误差或移除 Y 误差关联。"
                    )
                with np.errstate(over="ignore", divide="ignore"):
                    weights = 1 / y_err
                if not np.all(np.isfinite(weights)):
                    raise ValueError("Y 误差过小，权重超出数值范围。")
            result = self._model.fit(
                data=y,
                params=params,
                weights=weights,
                **{self.x_col: x},
                nan_policy="omit",
                iter_cb=iter_cb,
            )
            if not result.success or not np.isfinite(result.chisqr):
                raise ValueError(f"拟合未成功收敛：{result.message}")
            if (
                self.fit_preset_key in {"gaussian", "lorentzian"}
                and result.params["sigma"].value <= 0
            ):
                raise ValueError("拟合峰宽无效，请调整初值或范围。")
            if (
                self.fit_preset_key == "exponential"
                and result.params["decay"].value <= 0
            ):
                raise ValueError("拟合衰减常数无效，请调整初值或范围。")
            self.best_fit = result
            self._fit_data_checksum = self.hash_data(data)
        except Exception as exc:
            raise FitError(str(exc)) from exc

    def hash_data(self, data: ArrayLike) -> int:
        """Calculate a hash (checksum) of the data.

        A deterministic hash is calculated for the provided data. This hash can
        then be used as a checksum to determine if some other data is identical
        or different. This determination is slower using checksums than by
        direct comparison, but the checksum has the benefit of being able to
        store just a hash and not a complete copy of the data. Also, by using a
        fast hashing algorithm like xxHash, the slowdown is only a factor 1.5x -
        2x for larger datasets and almost 1x for small datasets.

        Args:
            data (ArrayLike): the data for which to calculate the hash.

        Returns:
            int: the calculated hash (checksum).
        """
        return xxhash.xxh3_64(np.array(data)).intdigest()

    def verify_best_fit_data(self) -> bool:
        """Determine if the given data is identical to the fitted data.

        Sometime after a best fit of the model to the experimental data has been
        determined, that data may change due to the user changing values or
        expressions. This method can determine if the possibly new data is
        identical to the data that was used in the fitting procedure. It returns
        a boolean; True means that the data is identical, False means it is not.
        Furthermore, if the data is not identical, the best fit is invalidated.

        Returns:
            bool: whether the given data is identical or not
        """
        data = self.get_data_in_fit_domain()
        if self.hash_data(data) == self._fit_data_checksum:
            return True
        else:
            self.best_fit = None
            self._fit_data_checksum = None
            return False

    def evaluate_best_fit(self, x: np.ndarray) -> np.ndarray | None:
        """Evaluate the fit model with best-fit parameters.

        Evaluate the fit model using the values for the best-fit parameters at
        the supplied x-values. If no model is currently defined, return None.

        Args:
            x (np.ndarray): the x-values for which to evaluate the model.

        Returns:
            np.ndarray | None: the evaluated y-values or None
        """
        if self.best_fit:
            return self.best_fit.eval(**{self.x_col: x})
        else:
            return None

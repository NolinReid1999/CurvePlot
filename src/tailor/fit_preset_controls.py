"""Thin preset and result controls around Tailor's existing fitting workflow."""

from pathlib import Path

import numpy as np
from PySide6 import QtCore, QtWidgets

from tailor.cst_names import rename_variables
from tailor.fit_presets import get_preset, guess_parameters, list_presets
from tailor.parameter_history import configuration_edit


class FitPresetControls(QtCore.QObject):
    def __init__(self, plot):
        super().__init__(plot)
        self.plot = plot
        self._custom_selected=False
        group = QtWidgets.QGroupBox("常见拟合模型", plot)
        self.group = group
        self.export_buttons = []
        form = QtWidgets.QVBoxLayout(group)
        self.selector = QtWidgets.QComboBox(group)
        from tailor.choice_state import MODEL_EMPTY
        self.selector.addItem('—',MODEL_EMPTY)
        self.selector.addItem("自定义公式", None)
        for preset in list_presets():
            self.selector.addItem(preset.title, preset.key)
        self.selector.addItem("多峰 Gaussian", "multi_gaussian_3")
        self.selector.addItem("多峰 Lorentzian", "multi_lorentzian_3")
        from tailor.manual_peaks import ManualPeaks

        self.manual_peaks = ManualPeaks(self)
        from tailor.popup_controls import HelpPopup

        self.help_popup = HelpPopup(group)
        help_button = QtWidgets.QToolButton(group)
        self.help_button = help_button
        help_button.setText("?")
        help_button.setFixedSize(28, 28)
        help_button.setToolTip("模型说明")
        help_button.clicked.connect(lambda: self.help_popup.open_at(help_button))
        selector_row = QtWidgets.QHBoxLayout()
        selector_row.addWidget(self.selector, 1)
        selector_row.addWidget(help_button)
        form.addLayout(selector_row)
        self.guess_button = QtWidgets.QPushButton("重新估计初值", group)
        self.guess_button.clicked.connect(
            lambda: self.estimate_initial(reset_bounds=False)
        )
        form.addWidget(self.guess_button)
        self.description = self.help_popup.label
        row = QtWidgets.QHBoxLayout()
        for text, callback in (
            ("打开结果页", self.open_result),
            ("另存为新拟合", self.new_result),
        ):
            button = QtWidgets.QPushButton(text, group)
            button.clicked.connect(callback)
            row.addWidget(button)
        form.addLayout(row)
        self.selector.currentIndexChanged.connect(self.select_current)
        plot.ui.model_func.textChanged.connect(self.sync_execute)
        plot.ui.verticalLayout_2.insertWidget(0, group)
        actions = QtWidgets.QHBoxLayout()
        for label, callback in (
            ("复制结果", self.copy_result),
            ("参数 CSV", self.export_parameters),
            ("残差 CSV", self.export_residuals),
        ):
            button = QtWidgets.QPushButton(label, plot)
            button.clicked.connect(callback)
            actions.addWidget(button)
            self.export_buttons.append(button)
        plot.ui.verticalLayout_2.addLayout(actions)
        self.clear_button = QtWidgets.QPushButton("撤销拟合", plot)
        self.clear_button.setProperty("intent", "destructive")
        self.clear_button.setToolTip(
            "清除当前图的全部拟合记录、结果页、拟合曲线和专属输出列；保留原始数据和模型设置。"
        )
        self.clear_button.clicked.connect(self.clear_fit)
        self.clear_button.hide()
        self.sync_model()

    def clear_fit(self):
        from tailor.fit_results import clear_fits

        clear_fits(self.plot)

    def open_result(self):
        from tailor.fit_results import show_result

        show_result(self.plot)

    def new_result(self):
        if self.plot.main_window.data_operation_busy():
            return
        self.plot.active_fit_id = None
        self.plot.perform_fit()

    def sync_model(self):
        key = self.plot.model.fit_preset_key
        from tailor.choice_state import MODEL_EMPTY
        selected=MODEL_EMPTY if key is None and not self.plot.model._model_expression.strip() and not self._custom_selected else key
        index = self.selector.findData(
            key.rsplit("_", 1)[0] + "_3" if key and key.startswith("multi_") else selected
        )
        blocked = self.selector.blockSignals(True)
        self.selector.setCurrentIndex(max(0, index))
        self.selector.blockSignals(blocked)
        self.plot.ui.model_func.setReadOnly(key is not None)
        self.guess_button.setEnabled(key is not None)
        detail = (
            f"自定义公式使用当前X列变量 {self.plot.model.get_x_col_name()}，"
            f"例如 a*{self.plot.model.get_x_col_name()}+b；其余符号作为待拟合参数。"
            "下方可设置初值、上下界和固定参数；参数单位需根据公式自行判断。"
        )
        if key is not None:
            preset = get_preset(key)
            detail = (
                "x 表示源 X 列；初值由 lmfit 估计，下方可编辑初值、上下界及固定参数。"
            )
            if preset.peak:
                width = "标准差" if "gaussian" in key else "半高半宽"
                detail += f" amplitude 为峰面积，sigma 为{width}；拟合后显示 FWHM。"
        if key in {"sine", "damped_sine"}:
            detail += " frequency 为角频率（rad/X单位），shift 为相位（rad）；结果页同时给出普通频率和周期。"
        if key == "damped_sine":
            detail += " origin 为时间原点，默认固定在拟合区间起点。"
        self.description.setText(detail)
        self.manual_peaks.sync()
        self.sync_execute()

    def sync_execute(self,*args):
        if getattr(self.plot,'_fit_job',None) is None:
            self.plot.ui.fit_button.setEnabled(self.plot.model.is_model_valid())

    def select_current(self, *args):
        self.choose(self.selector.currentData())

    @configuration_edit
    def choose(self, key):
        model = self.plot.model
        from tailor.choice_state import MODEL_EMPTY
        if key==MODEL_EMPTY:
            self._custom_selected=False
            model.fit_preset_key=None
            model.update_model_expression('')
            self.manual_peaks.arm(False)
            self.sync_model()
            self.plot.update_model_widget();self.plot.update_model_curves()
            self.plot.main_window.mark_project_dirty()
            return
        if key is None:
            self._custom_selected=True
            model.fit_preset_key = None
            model.update_model_expression('')
            self.manual_peaks.arm(False)
            self.sync_model()
            self.plot.update_model_widget()
            self.plot.update_info_box()
            self.plot.main_window.mark_project_dirty()
            return
        preset = get_preset(key)
        self._custom_selected=False
        model.fit_preset_key = key
        canonical = rename_variables(preset.expression, {"x": model.x_col})
        model.update_model_expression(canonical, use_column_ids=True)
        self.sync_model()
        self.plot.update_model_widget()
        self.plot.update_model_curves()
        self.plot.main_window.mark_project_dirty()
        self.estimate_initial(reset_bounds=True)

    def estimate_initial(self, reset_bounds=False):
        model = self.plot.model
        key = model.fit_preset_key
        if key is None:
            return
        try:
            x, y, _, _ = model.get_data_in_fit_domain()
            seeds = guess_parameters(key, x, y)
            for name, (value, lower, upper) in seeds.items():
                if name not in model._parameters:
                    continue
                parameter = model._parameters[name]
                if reset_bounds:
                    parameter.min, parameter.max, parameter.vary = (
                        lower,
                        upper,
                        name != "origin",
                    )
                if parameter.vary or reset_bounds:
                    parameter.value = float(
                        np.clip(value, parameter.min, parameter.max)
                    )
            model.best_fit = None
            self.plot.update_params_ui_values_from_model()
            self.plot.update_model_curves()
            self.plot.main_window.mark_project_dirty()
            self.plot.main_window.statusBar().showMessage(
                "已使用 lmfit 的初值建议；可继续调整参数后执行拟合。"
            )
        except (
            ValueError,
            TypeError,
            KeyError,
            FloatingPointError,
            np.linalg.LinAlgError,
        ) as error:
            self.plot.main_window.statusBar().showMessage(f"未能估计初值：{error}")

    def current_fit(self):
        model = self.plot.model
        model.verify_best_fit_data()
        if model.best_fit is None:
            self.plot.update_info_box()
            self.plot.main_window.statusBar().showMessage(
                "请先拟合；数据或设置改变后需重新拟合。"
            )
        return model.best_fit

    def derived_values(self):
        model = self.plot.model
        if model.best_fit is None or model.fit_preset_key is None:
            return {}
        preset = get_preset(model.fit_preset_key)
        if not preset.peak:
            return {}
        from tailor.fit_metrics import peak_features

        return peak_features(
            preset.key, {k: v.value for k, v in model.best_fit.params.items()}
        )

    def result_summary(self):
        model = self.plot.model
        fit = model.best_fit
        if fit is None:
            return ""
        title = (
            get_preset(model.fit_preset_key).title
            if model.fit_preset_key
            else "自定义公式"
        )
        text = f"\n模型：{title}\n有效点：{fit.ndata}；加权：{'Y 误差 (1/σ)' if model.y_err_col else '未加权'}\n"
        if model.x_err_col is not None:
            text += "本次最小二乘未将 X 误差纳入权重。\n"
        value = getattr(fit, "rsquared", None)
        if value is not None and np.isfinite(value):
            text += f"R²：{value:.8g}\n"
        values = self.derived_values()
        if values:
            for prefix in (
                tuple(
                    f"p{i}_"
                    for i in range(1, int(model.fit_preset_key.rsplit("_", 1)[1]) + 1)
                )
                if model.fit_preset_key.startswith("multi_")
                else ("p1_", "p2_")
                if model.fit_preset_key.startswith("double_")
                else ("",)
            ):
                text += f"{prefix}FWHM：{values[prefix + 'fwhm']:.10g}；峰高：{values[prefix + 'height']:.10g}\n"
            text += "宽度使用 X 单位；峰高使用 Y 单位；派生值暂未传播标准误。\n"
        if not fit.errorbars:
            text += "参数标准误不可用；请检查数据与参数是否可辨识。\n"
        return text

    def copy_result(self):
        if self.current_fit() is not None:
            QtWidgets.QApplication.clipboard().setText(
                self.plot.ui.result_box.toPlainText()
            )

    def write_result_csv(self, columns):
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self.plot, "导出拟合结果", "", "CSV (*.csv)"
        )
        if not filename:
            return
        path = Path(filename)
        if not path.suffix:
            path = path.with_suffix(".csv")
        self.plot.main_window.start_csv_snapshot_export(
            {key: np.asarray(values).copy() for key, values in columns.items()}, path
        )

    def export_parameters(self):
        fit = self.current_fit()
        if fit is None:
            return
        values = {name: parameter.value for name, parameter in fit.params.items()}
        values.update(self.derived_values())
        from tailor.analysis_units import parameter_unit
        sheet=self.plot.data_sheet.model
        labels=list(sheet.columnLabels())
        units={axis:sheet.column_metadata(labels.index(key))['unit'] for axis,key in (('x',self.plot.model.x_col),('y',self.plot.model.y_col))}
        self.write_result_csv(
            {
                "parameter": list(values),
                "value": list(values.values()),
                "unit": [parameter_unit(self.plot.model.fit_preset_key,k,units) for k in values],
                "stderr": [
                    fit.params[name].stderr
                    if name in fit.params and fit.params[name].stderr is not None
                    else np.nan
                    for name in values
                ],
            }
        )

    def export_residuals(self):
        fit = self.current_fit()
        if fit is None:
            return
        model = self.plot.model
        frame = model._get_data_as_dataframe()
        if model.get_fit_domain_enabled():
            lower, upper = model.get_fit_domain()
            frame = frame[frame["x"].between(lower, upper, inclusive="both")]
        self.write_result_csv(
            {
                "source_row": frame.index.to_numpy() + 1,
                "x": frame["x"].to_numpy(),
                "y": frame["y"].to_numpy(),
                "y_fit": fit.best_fit,
                "residual_y_minus_fit": frame["y"].to_numpy() - fit.best_fit,
            }
        )

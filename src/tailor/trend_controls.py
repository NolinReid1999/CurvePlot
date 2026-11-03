"""Origin-style quick trend fitting, reusing Tailor/lmfit and processing kernels."""

from tailor.compact_controls import CheckButton

import numpy as np
from PySide6 import QtWidgets

from tailor.graph_controls import combo, row


class TrendControls(QtWidgets.QWidget):
    def __init__(self, plot):
        super().__init__()
        self.plot = plot
        form = QtWidgets.QFormLayout(self)
        self.kind = combo(
            [
                (title, key)
                for title, key in [
                    ("线性", "linear"),
                    ("多项式", "polynomial"),
                    ("幂函数", "trend_power"),
                    ("对数", "trend_log"),
                    ("指数", "trend_exp"),
                    ("移动平均", "average"),
                    ("分段线性", "piecewise"),
                ]
            ]
        )
        self.degree = QtWidgets.QSpinBox()
        self.degree.setRange(2, 6)
        self.degree.setValue(2)
        self.window = QtWidgets.QSpinBox()
        self.window.setRange(2, 100001)
        self.window.setValue(5)
        self.segments = QtWidgets.QSpinBox()
        self.segments.setRange(2, 3)
        self.equation = CheckButton("显示公式")
        self.equation.setChecked(True)
        self.r2 = CheckButton("显示 R²")
        self.r2.setChecked(True)
        self.fix = CheckButton("固定截距")
        self.fix.setToolTip('固定截距／偏置为0')
        self.message = QtWidgets.QLabel()
        self.message.setWordWrap(True)
        form.addRow("类型", self.kind)
        from tailor.compact_controls import MultiParameter
        self.shared_parameters=MultiParameter([self.degree,self.window,self.segments],['阶数','窗口','线段'],['阶','点','段'])
        form.addRow(self.shared_parameters)
        for button in (self.equation,self.r2,self.fix):
            button.setSizePolicy(QtWidgets.QSizePolicy.Ignored,QtWidgets.QSizePolicy.Fixed)
        form.addRow(row(self.equation, self.r2,self.fix))
        add = QtWidgets.QPushButton("添加趋势线")
        add.clicked.connect(self.add)
        form.addRow(add)
        form.addRow(self.message)
        self.kind.currentIndexChanged.connect(self.sync)
        self.sync()
        plot.data_refreshed.connect(self.fit_finished)
        from tailor.parameter_domains import Domains,source_for,limit
        def bounds(stats,source):
            limit(self.window,2,max(2,stats[1][2]),preserve=False);self.shared_parameters.sync()
        self.parameter_domains=Domains(self,lambda:source_for(plot),bounds)
        plot.data_refreshed.connect(self.parameter_domains.invalidate)
        self.pending = False
        self.average_pending = False
        plot.processing_controls.resultReady.connect(self.average_finished)

    def sync(self, *args):
        key = self.kind.currentData()
        self.degree.setEnabled(key == "polynomial")
        self.window.setEnabled(key == "average")
        self.segments.setEnabled(key == "piecewise")
        self.fix.setEnabled(key not in {"average", "piecewise"})
        self.equation.setEnabled(key != "average")
        self.r2.setEnabled(key != "average")
        current={'polynomial':0,'average':1,'piecewise':2}.get(key,0)
        self.shared_parameters.choose(current)

    def add(self):
        p = self.plot
        if self.kind.currentData() == "average":
            control = p.processing_controls
            self.average_pending = True
            control.start(
                "moving_average", self.window.value(), 0, 0, True, "移动平均趋势线"
            )
            self.message.setText(
                "移动平均结果生成完整数据表，并叠加到当前图；不计算拟合 R²。"
            )
            return
        key = self.kind.currentData()
        if key == "polynomial":
            key = (
                "quadratic"
                if self.degree.value() == 2
                else f"polynomial_{self.degree.value()}"
            )
        if key == "piecewise":
            key = "trend_piece3" if self.segments.value() == 3 else "trend_piece2"
        if key in {"trend_power", "trend_log"}:
            x, y, _, _ = p.model.get_data_in_fit_domain()
            if np.any(x <= 0) or (
                key == "trend_power" and self.fix.isChecked() and np.any(y <= 0)
            ):
                self.message.setText(
                    "当前幂／对数趋势要求 X 为正；零偏置幂函数还要求 Y 为正。原数据未修改。"
                )
                return
        p.preset_controls.choose(key)
        if self.fix.isChecked():
            candidates = ["intercept", "c0", "c", "offset"]
            for name in candidates:
                if name in p.model._parameters:
                    parameter = p.model._parameters[name]
                    parameter.value = 0
                    parameter.vary = False
                    break
        if (
            key == "trend_log"
            and self.fix.isChecked()
            and "shift" in p.model._parameters
        ):
            p.model._parameters["shift"].value = 0
            p.model._parameters["shift"].vary = False
        p.update_params_ui_values_from_model()
        self.pending = True
        self.message.setText("正在拟合趋势线…")
        p.perform_fit()

    def fit_finished(self, *args):
        if not self.pending or self.plot.model.best_fit is None:
            return
        self.pending = False
        p = self.plot
        fit = p.model.best_fit
        parts = []
        if self.equation.isChecked():
            parts.append(p.model.get_model_expression())
            parts.append(
                "，".join(
                    f"{key}={value.value:.5g}"
                    for key, value in fit.params.items()
                    if value.expr is None
                )
            )
        if self.r2.isChecked():
            y = np.asarray(fit.data)
            den = float(np.sum((y - y.mean()) ** 2))
            score = (
                1
                - float(np.sum((np.asarray(fit.data) - np.asarray(fit.best_fit)) ** 2))
                / den
                if den
                else float("nan")
            )
            parts.append(f"R² = {score:.6g}")
        if parts:
            manager = p.annotations
            manager.add("text", "canvas", [0.06, 0.92, 0.06, 0.92])
            record = manager.current()
            if record:
                manager.replace({**record, "text": "<br>".join(parts), "size": 10.0})
        self.message.setText("趋势线已生成；拟合数据列、结果页沿用现有拟合流程。")

    def average_finished(self, payload):
        if not self.average_pending:
            return
        self.average_pending = False
        import uuid

        if not payload:
            return
        sheet = payload[0]["sheet"]
        keys = payload[0]["keys"]
        if len(keys) == 1:
            keys = [self.plot.model.x_col, keys[0]]
        self.plot.presentation.trend_sources.append(
            {
                "id": uuid.uuid4().hex,
                "sheet": sheet.id,
                "x": keys[0],
                "y": keys[1],
                "name": "移动平均趋势线",
                "style": {"mode": "line", "color": "#2878cc", "line_width": 1.5},
            }
        )
        self.plot.presentation.apply_legend()
        self.plot.main_window.ui.tabWidget.setCurrentWidget(self.plot)
        self.plot.main_window.mark_project_dirty()

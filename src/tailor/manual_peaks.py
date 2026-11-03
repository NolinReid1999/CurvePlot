"""Peak initial values from source samples; optimization stays in lmfit."""

import numpy as np
import pyqtgraph as pg
import shiboken6
from PySide6 import QtCore, QtWidgets

from tailor.compact_controls import toggle_button
from tailor.graph_controls import number, row


class ManualPeaks(QtCore.QObject):
    def __init__(self, control):
        super().__init__(control)
        self.control = control
        self.plot = control.plot
        self.centers = []
        self.button = toggle_button("手动选峰")
        self.button.toggled.connect(self.arm)
        self.count = number(2, 20, 3, 0,unit="个")
        self.count.setSingleStep(1)
        self.count.valueChanged.connect(self.change_count)
        self.count_row = row("峰数", self.count)
        self.widget = QtWidgets.QWidget(self.plot)
        layout = QtWidgets.QVBoxLayout(self.widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.count_row)
        layout.addWidget(self.button)
        self.marker = pg.ScatterPlotItem(size=12, brush="#d05b23", pen="w")
        self.plot.ui.plot_widget.addItem(self.marker, ignoreBounds=True)
        self.plot.ui.plot_widget.scene().sigMouseClicked.connect(self.clicked)
        install_guard(self)

    def sync(self):
        key = self.plot.model.fit_preset_key or ""
        allowed=any(k in key for k in ("gaussian", "lorentzian"))
        # This compatibility container is no longer the parameter page once
        # its controls are moved into the shared fitter. Never show an orphan.
        self.widget.setVisible(self.button.parentWidget() is self.widget)
        self.button.setEnabled(allowed)
        if not allowed and self.button.isChecked():self.button.setChecked(False)
        self.count_row.setVisible(key.startswith("multi_"))
        if key.startswith("multi_"):
            with QtCore.QSignalBlocker(self.count):
                self.count.setValue(int(key.rsplit("_", 1)[1]))

    def change_count(self, *args):
        key = self.plot.model.fit_preset_key or ""
        if key.startswith("multi_"):
            self.control.choose(
                key.rsplit("_", 1)[0] + "_" + str(int(self.count.value()))
            )

    def arm(self, active):
        self.centers = []
        self.marker.setData([], [])
        if active:
            graph=getattr(self.plot,'_fit_host',self.plot)
            graph.annotations.arm(None)
            graph.point_inspector.enabled.setChecked(False)
            self.plot.annotations.arm(None)
            self.plot.point_inspector.enabled.setChecked(False)
            self.plot.main_window.statusBar().showMessage(
                f"请依次点击{self.required()}个峰顶。再次点击手动选峰可取消。"
            )

    def required(self):
        key = self.plot.model.fit_preset_key or ""
        return (
            int(key.rsplit("_", 1)[1])
            if key.startswith("multi_")
            else 2
            if key.startswith("double_")
            else 1
        )

    def snapshot(self):
        import copy
        return (list(self.centers), copy.deepcopy(self.plot.model._parameters), self.button.isChecked())

    def restore(self, state):
        import copy
        self.centers = list(state[0])
        self.plot.model._parameters = copy.deepcopy(state[1])
        with QtCore.QSignalBlocker(self.button):
            self.button.setChecked(state[2])
        self.refresh_marker()
        self.plot.update_params_ui_values_from_model()

    def refresh_marker(self):
        from tailor.graph_presentation import display
        frame = self.plot.model._get_data_as_dataframe()
        xx, yy = frame.x.to_numpy(), frame.y.to_numpy()
        indices = [int(np.argmin(abs(xx-c))) for c in self.centers]
        graph=getattr(self.plot,'_fit_host',self.plot)
        info=graph.model.get_plot_info(self.plot) if graph.presentation.multi else None
        sides = {'x':info.x_axis,'y':info.axis} if info else self.plot.presentation.single_sides
        xkey = "top" if sides["x"] == "top" else "x"
        ykey = "right" if sides["y"] == "right" else "y"
        target = graph.presentation.box_for(info) if info else graph.presentation.right_box if ykey == "right" else graph.ui.plot_widget.getViewBox()
        target = target or graph.ui.plot_widget.getViewBox()
        if self.marker.getViewBox() is not target:
            box=self.marker.getViewBox()
            if box is not None:box.removeItem(self.marker)
            target.addItem(self.marker, ignoreBounds=True)
        self.marker.setData(display(xx[indices], graph.presentation.axes[xkey]), display(yy[indices], graph.presentation.axes[ykey]))

    def clicked(self, event):
        if getattr(self.plot, "_graph_disposed", False) or not shiboken6.isValid(self.button):
            return
        if not self.button.isChecked() or event.button() != QtCore.Qt.LeftButton:
            return
        from tailor.graph_presentation import display
        graph=getattr(self.plot,'_fit_host',self.plot)
        info=graph.model.get_plot_info(self.plot) if graph.presentation.multi else None
        sides = {'x':info.x_axis,'y':info.axis} if info else self.plot.presentation.single_sides
        xkey = "top" if sides["x"] == "top" else "x"
        ykey = "right" if sides["y"] == "right" else "y"
        view = graph.presentation.box_for(info) if info else graph.presentation.right_box if ykey == "right" else graph.ui.plot_widget.getViewBox()
        view = view or graph.ui.plot_widget.getViewBox()
        if not view.sceneBoundingRect().contains(event.scenePos()):
            return
        frame = self.plot.model._get_data_as_dataframe(include_excluded=False)
        xx, yy = frame.x.to_numpy(), frame.y.to_numpy()
        if not len(xx):
            return
        pos = view.mapSceneToView(event.scenePos())
        shown = display(xx, graph.presentation.axes[xkey])
        shown_y = display(yy, graph.presentation.axes[ykey])
        valid = np.flatnonzero(np.isfinite(shown) & np.isfinite(shown_y))
        if not len(valid):
            return
        # Match the drawn source sample in logical scene pixels. Selecting only
        # by X can move the marker several pixels vertically on a steep peak,
        # especially when a scaled screen rounds the mouse coordinate.
        px, py = view.viewPixelSize()
        distance = ((shown[valid] - pos.x()) / max(abs(px), 1e-12)) ** 2
        distance += ((shown_y[valid] - pos.y()) / max(abs(py), 1e-12)) ** 2
        i = int(valid[np.argmin(distance)])
        center = float(xx[i])
        if center in self.centers:
            return
        before = self.snapshot()
        self.centers.append(center)
        self.refresh_marker()
        if len(self.centers) == self.required():
            from tailor.fit_presets import peak_seeds
            seeds = peak_seeds(self.plot.model.fit_preset_key, xx, yy, sorted(self.centers))
            for name, (value, low, high) in seeds.items():
                if name in self.plot.model._parameters:
                    p = self.plot.model._parameters[name]
                    p.value, p.min, p.max = value, low, high
            self.plot.update_params_ui_values_from_model()
            with QtCore.QSignalBlocker(self.button):
                self.button.setChecked(False)
            self.plot.main_window.statusBar().showMessage("已更新初值；点击执行拟合开始优化，可撤销重新选峰。")
        after = self.snapshot()
        from tailor.spreadsheet_model import Edit
        self.plot.data_sheet.model._record(Edit("手动选择峰顶", lambda: self.restore(before), lambda: self.restore(after), 8192))
        self.plot.main_window.mark_project_dirty()


def picking(plot):
    if plot is None or not shiboken6.isValid(plot) or getattr(plot, "_graph_disposed", False):
        return False
    router=getattr(plot,'fit_router',None)
    if router is not None:
        if not shiboken6.isValid(router) or not shiboken6.isValid(router.choice):return False
        source=router.choice.currentData()
        return picking(source) if source is not None else False
    control = getattr(plot, "preset_controls", None)
    return bool(control and shiboken6.isValid(control.manual_peaks.button) and control.manual_peaks.button.isChecked())


class PeakGuard(QtCore.QObject):
    def __init__(self,app):
        super().__init__(app)
        import weakref
        self.controls=weakref.WeakSet()

    def eventFilter(self,watched,event):
        if event.type() not in (QtCore.QEvent.MouseButtonPress,QtCore.QEvent.MouseButtonDblClick,QtCore.QEvent.MouseMove,QtCore.QEvent.MouseButtonRelease):return False
        for control in list(self.controls):
            if not shiboken6.isValid(control) or not picking(control.plot):continue
            graph=getattr(control.plot,'_fit_host',control.plot)
            if watched is not graph.ui.plot_widget.viewport():continue
            if event.type()==QtCore.QEvent.MouseButtonPress and event.button()==QtCore.Qt.LeftButton:
                from types import SimpleNamespace
                pos=graph.ui.plot_widget.mapToScene(event.position().toPoint())
                control.clicked(SimpleNamespace(button=lambda:QtCore.Qt.LeftButton,scenePos=lambda:pos))
            return True
        return False


def install_guard(control):
    app=QtWidgets.QApplication.instance()
    if not hasattr(app,'_curve_peak_guard'):
        app._curve_peak_guard=PeakGuard(app);app.installEventFilter(app._curve_peak_guard)
    app._curve_peak_guard.controls.add(control)

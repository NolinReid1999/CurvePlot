"""Inspect real source samples and expose the existing draggable X fit range."""

from tailor.compact_controls import CheckButton

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

from tailor.compact_controls import point_selection_grid, toggle_button
from tailor.selection_history import selection_edit


class PointInspector(QtCore.QObject):
    def __init__(self, plot, layout):
        super().__init__(plot)
        self.plot = plot
        self.source_row = None
        self.selected_coordinates = None
        group = QtWidgets.QGroupBox("选点与 X 区间", plot)
        self.group = group
        controls = QtWidgets.QVBoxLayout(group)
        self.enabled = toggle_button("选择数据点")
        self.enabled.hide()
        self.single = toggle_button("选择单个数据点")
        self.continuous = toggle_button("选择连续数据点")
        self.mode_group = QtWidgets.QButtonGroup(self)
        self.mode_group.setExclusive(False)
        self.mode_group.addButton(self.single)
        self.mode_group.addButton(self.continuous)
        self.start_row = None
        self.selected_frame = None
        self.single.toggled.connect(self.sync_mode)
        self.continuous.toggled.connect(self.sync_mode)
        self.enabled.toggled.connect(self.enable_mode)
        self.details = QtWidgets.QLabel("", group)
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.details.hide()
        self.locate = QtWidgets.QPushButton("定位到原工作表", group)
        self.locate.setEnabled(False)
        self.locate.clicked.connect(self.locate_source)
        self.copy = QtWidgets.QPushButton("复制坐标", group)
        self.copy.setEnabled(False)
        self.copy.clicked.connect(self.copy_coordinates)
        controls.addWidget(point_selection_grid(self.single, self.continuous, self.locate, self.copy,self.details))
        from tailor.exclusions import selection_buttons

        controls.addWidget(selection_buttons(self))
        self.region = CheckButton("拖动 X 区间用于拟合", group)
        self.region.setChecked(plot.ui.use_fit_domain.isChecked())
        self.region.toggled.connect(plot.ui.use_fit_domain.setChecked)
        plot.ui.use_fit_domain.toggled.connect(self.region.setChecked)
        controls.addWidget(self.region)
        self.range_info = QtWidgets.QLabel(group)
        self.range_info.setWordWrap(True)
        controls.addWidget(self.range_info)
        plot.fit_domain_area.sigRegionChangeFinished.connect(self.update_range)
        self.region.toggled.connect(self.update_range)
        plot.data_refreshed.connect(self.update_range)
        self.marker = pg.ScatterPlotItem(
            size=17, pen=pg.mkPen("#2878cc", width=2), brush=pg.mkBrush(None)
        )
        self.highlight = pg.ScatterPlotItem(
            size=9, pen=pg.mkPen("#ffffff", width=1), brush=pg.mkBrush("#2878cc")
        )
        self.marker.setZValue(100)
        self.highlight.setZValue(101)
        plot.ui.plot_widget.addItem(self.marker, ignoreBounds=True)
        plot.ui.plot_widget.addItem(self.highlight, ignoreBounds=True)
        plot.ui.plot_widget.scene().sigMouseClicked.connect(self.mouse_clicked)
        self.enabled.toggled.connect(
            lambda active: self.invalidate() if not active else None
        )
        layout.addWidget(group)
        self.update_range()

    def sync_mode(self, *args):
        if self.sender() in (self.single, self.continuous) and self.sender().isChecked():
            other = self.continuous if self.sender() is self.single else self.single
            with QtCore.QSignalBlocker(other):
                other.setChecked(False)
        self.enabled.setChecked(self.single.isChecked() or self.continuous.isChecked())
        self.invalidate()

    def enable_mode(self, active):
        if active and not (self.single.isChecked() or self.continuous.isChecked()):
            self.single.setChecked(True)
        elif not active:
            self.mode_group.setExclusive(False)
            self.single.setChecked(False)
            self.continuous.setChecked(False)
            self.mode_group.setExclusive(False)

    def invalidate(self):
        clear_point_feedback(self)
        self.start_row = None
        self.selected_frame = None
        self.source_row = None
        self.marker.setData([], [])
        self.highlight.setData([], [])
        self.selected_coordinates = None
        self.copy.setEnabled(False)
        self.locate.setEnabled(False)
        self.details.setText("")
        self.details.hide()

    def mouse_clicked(self, event):
        if point_active(self.plot):
            select_scene_point(self, event)

    @selection_edit
    def select_near(self, x, y, pixel, radius=10):
        """Select within a pixel radius, using full source values, not display sampling."""
        try:
            frame = self.plot.model._get_data_as_dataframe()
            if frame.empty or pixel[0] == 0 or pixel[1] == 0:
                self.invalidate()
                return None
            from tailor.graph_presentation import display

            axes = self.plot.presentation.axes
            dx = display(frame["x"].to_numpy(), axes["x"])
            dy = display(frame["y"].to_numpy(), axes["y"])
            with np.errstate(over="ignore", invalid="ignore"):
                distance = ((dx - x) / abs(pixel[0])) ** 2
                distance += ((dy - y) / abs(pixel[1])) ** 2
            distance[~np.isfinite(distance)] = np.inf
            closest = int(np.argmin(distance))
            if not np.isfinite(distance[closest]) or distance[closest] > radius**2:
                self.invalidate()
                self.details.setText("附近没有真实数据点，请靠近曲线点击。")
                return None
            row = int(frame.index[closest])
            values = frame.iloc[closest]
            if self.continuous.isChecked():
                if self.start_row is None:
                    self.invalidate()
                    self.start_row = row
                    self.marker.setData([dx[closest]], [dy[closest]])
                    self.highlight.setData([dx[closest]], [dy[closest]])
                    self.details.setText(f"起点：第{row + 1}行；请点击结束点。")
                    self.details.show()
                    return row
                lo, hi = sorted((self.start_row, row))
                selected = (frame.index >= lo) & (frame.index <= hi)
                self.selected_frame = frame.loc[selected, ["x", "y"]].copy()
                self.source_row = lo
                self.start_row = None
                shown = np.flatnonzero(selected)[::max(1, int(np.count_nonzero(selected) / 2000))]
                self.marker.setData(dx[shown], dy[shown])
                self.highlight.setData(dx[shown], dy[shown])
                self.selected_coordinates = (
                    self.plot.model.get_x_col_name(),
                    self.plot.model.get_y_col_name(),
                    0,
                    0,
                )
                self.locate.setEnabled(True)
                self.copy.setEnabled(True)
                self.details.setText(
                    f"第{lo + 1}–{hi + 1}行 · {len(self.selected_frame)}个有效点"
                )
                self.details.show()
                return row
            for button in getattr(self,"exclusion_buttons",()):button.setEnabled(True)
            self.selected_frame = frame.iloc[[closest]][["x", "y"]].copy()
            self.source_row = row
            self.marker.setData([dx[closest]], [dy[closest]])
            self.highlight.setData([dx[closest]], [dy[closest]])
            model = self.plot.model
            x_name = model.data_model.get_column_name(model.x_col)
            y_name = model.data_model.get_column_name(model.y_col)
            text = (
                f"{self.plot.data_sheet.name} · 第 {row + 1:,} 行\n"
                f"{x_name} = {values['x']:.12g}\n{y_name} = {values['y']:.12g}"
            )
            if model.x_err_col is not None:
                text += f"\nX 误差 = {values['x_err']:.12g}"
            if model.y_err_col is not None:
                text += f"\nY 误差 = {values['y_err']:.12g}"
            self.details.setText(text)
            self.details.show()
            self.locate.setEnabled(True)
            self.selected_coordinates = (
                x_name,
                y_name,
                float(values["x"]),
                float(values["y"]),
            )
            self.copy.setEnabled(True)
            return row
        except (KeyError, ValueError, IndexError, TypeError):
            self.invalidate()
            return None

    def copy_coordinates(self):
        if self.selected_coordinates is not None:
            x_name, y_name, x, y = self.selected_coordinates
            text = f"{x_name}\t{y_name}\n"
            if self.selected_frame is not None:
                raw = self.selected_frame[['x', 'y']]
                text += raw.to_csv(
                    sep="\t", index=False, header=False, float_format="%.17g"
                )
            else:
                text += f"{x:.17g}\t{y:.17g}"
            QtWidgets.QApplication.clipboard().setText(text)
            self.plot.main_window.statusBar().showMessage(
                "已复制所选源数据点的 X/Y 坐标。"
            )

    def locate_source(self):
        if self.source_row is None:
            return
        sheet = self.plot.data_sheet
        self.plot.main_window.ui.tabWidget.setCurrentWidget(sheet)
        sheet.go_to_row(self.source_row)
        column = list(sheet.model.columnLabels()).index(self.plot.model.y_col)
        sheet.ui.data_view.setCurrentIndex(
            sheet.page_model.index(self.source_row, column)
        )
        if self.selected_frame is not None and len(self.selected_frame) > 1:
            lo, hi = (
                int(self.selected_frame.index.min()),
                int(self.selected_frame.index.max()),
            )
            selection = QtCore.QItemSelection(
                sheet.page_model.index(lo, column), sheet.page_model.index(hi, column)
            )
            sheet.ui.data_view.selectionModel().select(
                selection, QtCore.QItemSelectionModel.ClearAndSelect
            )

    def update_range(self, *args):
        if not self.region.isChecked():
            self.range_info.setText("X 区间关闭，拟合使用全部有效数据。")
            return
        lower, upper = sorted(self.plot.fit_domain_area.getRegion())
        try:
            frame = self.plot.model._get_data_as_dataframe()
            count = int(frame["x"].between(lower, upper, inclusive="both").sum())
        except (KeyError, ValueError, IndexError, TypeError):
            count = 0
        self.range_info.setText(
            f"X：{lower:.8g} 至 {upper:.8g}\n有效点：{count:,}；边界点包含在内。"
        )


def point_active(plot):
    inspector = getattr(plot, 'point_inspector', None)
    from tailor.manual_peaks import picking
    return bool(inspector and inspector.enabled.isChecked() and not picking(plot))


def intercept_curve(plot, key, event):
    """Give point picking priority without creating an editable curve target."""
    if not point_active(plot):
        return False
    if event is not None:
        plot.curve_selection._handled_click = event
    return True


def point_candidates(plot):
    """Adapt existing rendered curves, keeping real source rows for raw curves."""
    from tailor.preference_pages import available_curves
    from tailor.fit_workflow import fit_owner
    seen = set()
    sources = list(plot.model._plots) if plot.presentation.multi else [plot]
    for key, (item, title) in available_curves(plot, include_hidden=False).items():
        if id(item) in seen or not item.isVisible():
            continue
        seen.add(id(item))
        source = next((s for s in sources if key == (f'plot:{s.id}:data' if plot.presentation.multi else 'data')), None)
        raw = source is not None
        if not raw:
            fitted = fit_owner(plot, key)
            source = fitted[0] if fitted else next((s for s in sources if key.startswith(f'plot:{s.id}:')), sources[0])
        info = plot.model.get_plot_info(source) if plot.presentation.multi else None
        box = plot.presentation.box_for(info) if info else plot.ui.plot_widget.getViewBox()
        xkey = 'top' if info and info.x_axis == 'top' else 'x'
        ykey = 'right' if info and info.axis == 'right' else 'y'
        try:
            if raw:
                frame = source.model._get_data_as_dataframe()[['x', 'y']]
            else:
                xx, yy = item.xData, item.yData
                if xx is None or yy is None or len(xx) != len(yy):
                    continue
                frame = pd.DataFrame({'x': xx, 'y': yy})
            if not frame.empty:
                yield dict(key=key, item=item, title=title, source=source, frame=frame,
                           raw=raw, box=box, xkey=xkey, ykey=ykey)
        except (KeyError, ValueError, TypeError):
            continue


def clear_point_feedback(control):
    control.curve_key = None
    control.sampled_curve = False
    control._start_curve = None
    for button in getattr(control,'exclusion_buttons',()):button.setEnabled(False)
    selection = getattr(control.plot, 'curve_selection', None)
    if selection:
        selection.feedback_item = None
        selection.refresh()


def show_point_feedback(control, candidate):
    control.curve_key = candidate['key']
    control.sampled_curve = not candidate['raw']
    for button in getattr(control,'exclusion_buttons',()):button.setEnabled(candidate['raw'])
    selection = control.plot.curve_selection
    selection.feedback_item = candidate['item']
    selection.refresh()
    if hasattr(control, 'marker_box') and control.marker_box is not candidate['box']:
        if control.marker_box is not None:
            control.marker_box.removeItem(control.marker)
            control.marker_box.removeItem(control.highlight)
        candidate['box'].addItem(control.marker, ignoreBounds=True)
        candidate['box'].addItem(control.highlight, ignoreBounds=True)
        control.marker_box = candidate['box']


@selection_edit
def select_scene_point(control, event):
    plot = control.plot
    if not point_active(plot) or event.button() != QtCore.Qt.LeftButton:
        return
    from tailor.graph_focus import is_inset_event
    if is_inset_event(plot, event):return
    legend = plot.presentation.legend_item
    if legend.isVisible() and legend.sceneBoundingRect().contains(event.scenePos()):return
    from tailor.graph_presentation import display
    nearest = None
    for candidate in point_candidates(plot):
        box = candidate['box']
        if not box.sceneBoundingRect().contains(event.scenePos()):continue
        point = box.mapSceneToView(event.scenePos())
        px, py = box.viewPixelSize()
        if not px or not py:continue
        frame = candidate['frame']
        xx = display(frame.x.to_numpy(), plot.presentation.axes[candidate['xkey']])
        yy = display(frame.y.to_numpy(), plot.presentation.axes[candidate['ykey']])
        with np.errstate(invalid='ignore', over='ignore'):
            distance = ((xx-point.x())/abs(px))**2 + ((yy-point.y())/abs(py))**2
        distance[~np.isfinite(distance)] = np.inf
        index = int(np.argmin(distance))
        if distance[index] <= 100 and (nearest is None or distance[index] < nearest[0]):
            nearest = (distance[index], candidate, index, xx, yy)
    start, start_key = control.start_row, getattr(control, '_start_curve', None)
    control.invalidate()
    if nearest is None:return
    _, candidate, index, xx, yy = nearest
    show_point_feedback(control, candidate)
    source, frame = candidate['source'], candidate['frame']
    row = int(frame.index[index])
    if control.continuous.isChecked():
        if start is None or start_key != candidate['key']:
            control.start_row = (source, row) if hasattr(control, 'selected') else row
            control._start_curve = candidate['key']
            control.marker.setData([xx[index]], [yy[index]])
            control.highlight.setData([xx[index]], [yy[index]])
            label = '行' if candidate['raw'] else '拟合/绘制采样点'
            control.details.setText(f"{candidate['title']} · 起点：第{row+1}{label}；请点击同一曲线的结束点。")
            control.details.show()
            return row
        lo, hi = sorted((start[1] if isinstance(start, tuple) else start, row))
        indices = np.flatnonzero((frame.index >= lo) & (frame.index <= hi))
    else:
        indices = np.array([index])
    selected = frame.iloc[indices][['x', 'y']].copy()
    control.selected_frame = selected
    shown = indices[::max(1, (len(indices)+1999)//2000)]
    control.marker.setData(xx[shown], yy[shown])
    control.highlight.setData(xx[shown], yy[shown])
    values = frame.iloc[index]
    control.selected_coordinates = (source.model.get_x_col_name(), candidate['title'], float(values.x), float(values.y))
    if hasattr(control, 'source_row'):control.source_row = int(selected.index.min()) if candidate['raw'] else None
    if hasattr(control, 'selected'):control.selected = (source, int(selected.index.min()), float(values.x), float(values.y))
    label = '源数据行' if candidate['raw'] else '绘制采样点（不对应原始数据行）'
    control.details.setText(f"{candidate['title']} · {label} {int(selected.index.min())+1}–{int(selected.index.max())+1}\nX = {values.x:.12g} · Y = {values.y:.12g} · 共{len(selected)}点")
    control.details.show()
    control.locate.setEnabled(candidate['raw'])
    control.copy.setEnabled(True)
    return row

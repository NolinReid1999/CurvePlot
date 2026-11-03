
from tailor.compact_controls import CheckButton
import itertools
from functools import partial
from typing import TYPE_CHECKING

import numpy as np
import pyqtgraph as pg
from pyqtgraph import ColorButton
from PySide6 import QtCore, QtWidgets
from tailor.graph_defaults import derived_width

from tailor.appearance import ink
from tailor.curve_controls import build_overlay_panel
from tailor.curve_style import CurveStyle
from tailor.graph_presentation import (
    ErrorItems,
    GraphPresentation,
    display,
    mpl_error_values,
    mpl_errors,
    physical,
)
from tailor.multiplot_model import MultiPlotModel
from tailor.plot_tab import PlotTab
from tailor.ui_multiplot_tab import Ui_MultiPlotTab

if TYPE_CHECKING:
    from tailor.app import MainWindow

NUM_POINTS = 1000


class MultiPlotTab(QtWidgets.QWidget):
    inspector_ready = QtCore.Signal()
    start_inspector = PlotTab.start_inspector
    _advance_inspector = PlotTab._advance_inspector
    name: str
    id: int
    main_window: "MainWindow"
    model: MultiPlotModel
    _plots: dict[PlotTab, QtWidgets.QHBoxLayout]
    _remembered_x_range: tuple[float, float] | None = None
    _remembered_y_range: tuple[float, float] | None = None
    _block_range_signal: bool = False

    def __init__(
        self, main_window: "MainWindow", name: str, id: int, x_label: str, y_label: str,
        *, defer_inspector=False, inset_parent=None,
    ) -> None:
        super().__init__()
        if inset_parent is not None:
            self._inset_parent = inset_parent
        self.ui = Ui_MultiPlotTab()
        self.ui.setupUi(self)
        from tailor.appearance import initialize_canvas
        initialize_canvas(self.ui.plot_widget)

        self.name = name
        self.id = id
        self.main_window = main_window
        self._inspector_initializing = defer_inspector
        self.model = MultiPlotModel(x_label, y_label)
        self._plots = {}
        from tailor.graph_defaults import new_style

        self.curve_style = new_style()
        self.presentation = GraphPresentation(self, multi=True)
        self._series = {}
        self._remembered_right_range = None
        self._color = itertools.cycle(
            [
                "black",
                "blue",
                "green",
                "red",
                "orange",
                "purple",
                "gray",
                "darkcyan",
                "pink",
                "olive",
            ]
        )
        self._source_timer = QtCore.QTimer(self)
        self._source_timer.setSingleShot(True)
        self._source_timer.setInterval(80)
        self._source_timer.timeout.connect(self.draw_plot)
        self.finish_ui()
        self.refresh_ui()
        self.connect_ui_events()
        self.setup_overlay_controls()

    def setup_overlay_controls(self):
        build_overlay_panel(self)

    def queue_source_draw(self):
        self._source_timer.start()

    def finish_ui(self) -> None:
        """Finish some final UI stuff from code."""
        self.ui.xlabel.setText(self.model.x_label)
        self.ui.ylabel.setText(self.model.y_label)

        self.ui.groupBox.setFixedWidth(400)
        self.ui.plot_selection_layout = QtWidgets.QVBoxLayout()
        self.ui.plot_selection_layout.setContentsMargins(4, 0, 0, 0)
        self.ui.plot_selection_layout.setSpacing(0)
        # add stretch to prevent excessive widget sizes for small numbers of
        # parameters
        self.ui.plot_selection_layout.addStretch()
        self.ui.plot_selection.setLayout(self.ui.plot_selection_layout)

    def connect_ui_events(self) -> None:
        self.ui.xlabel.textChanged.connect(self.update_xlabel)
        self.ui.ylabel.textChanged.connect(self.update_ylabel)
        for box in (self.ui.x_min, self.ui.x_max, self.ui.y_min, self.ui.y_max):
            box.returnPressed.connect(self.on_set_limits_clicked)
        self.ui.set_limits_button.clicked.connect(self.on_set_limits_clicked)
        self.presentation.right_box.sigYRangeChanged.connect(self.remember_right)
        self.ui.plot_widget.sigXRangeChanged.connect(self.updated_plot_range)

    def refresh_ui(self, *, activation=False):
        """Refresh UI.

        This method is called when this tab is made visible, or when another tab
        is added or removed.
        """
        self.update_axis_settings_from_model()
        self.update_plots_ui()
        self.rebuild_plot_selection_ui()
        required = {source for source,info in self.model._plots.items() if info.visible}
        stale = self._source_timer.isActive() or any(getattr(source,'_source_changed',True) for source in self.model._plots)
        if not activation or stale or set(self._series) != required:
            self.draw_plot()
        if hasattr(self, "curve_manager"):
            self.curve_manager.refresh()
        if hasattr(self,'fit_router'):
            self.fit_router.refresh()
        if hasattr(self, "axis_controls"):
            self.axis_controls.sync()

    def update_plots_ui(self) -> None:
        """Add and/or remove parameters if necessary."""
        old_plots = set(self._plots.keys())
        current_plots = self.main_window.get_plots()
        self.add_plots_to_ui([p for p in current_plots if p not in old_plots])
        self.remove_plots_from_ui(old_plots - set(current_plots))

    def add_plots_to_ui(self, plots: list[PlotTab]) -> None:
        """Add plots to the list of plots.

        Args:
            plots (list[PlotTab]): the plots to be added to the UI.
        """
        for plot, color in zip(plots, self._color):
            is_enabled = CheckButton(plot.name)
            is_enabled.setObjectName("is_enabled_checkbox")
            plot_label = QtWidgets.QLineEdit(plot.name)
            plot_label.setObjectName("plot_label")
            color_button = ColorButton(color=color)
            color_button.setObjectName("plot_color")
            hbox = QtWidgets.QHBoxLayout()
            hbox.addWidget(is_enabled)
            hbox.addStretch()
            hbox.addWidget(plot_label)
            hbox.addWidget(color_button)
            layout_widget = QtWidgets.QWidget()
            layout_widget.setContentsMargins(0, 0, 0, 0)
            layout_widget.setLayout(hbox)
            self._plots[plot] = layout_widget
            plot.data_refreshed.connect(self.queue_source_draw)
            plot.labels_refreshed.connect(self.refresh_labels)
            is_enabled.stateChanged.connect(
                partial(self.update_checkbox, plot, is_enabled)
            )
            plot_label.textEdited.connect(partial(self.update_plot_label, plot))
            color_button.sigColorChanging.connect(partial(self.update_color, plot))

    def remove_plots_from_ui(self, plots: list[PlotTab]) -> None:
        """Remove plots from the list of plots.

        Args:
            plots (list[PlotTab]): the plots to be removed from the UI.
        """
        for plot in plots:
            try:
                plot.data_refreshed.disconnect(self.queue_source_draw)
                plot.labels_refreshed.disconnect(self.refresh_labels)
            except (RuntimeError, TypeError):
                pass
            self.model.remove_plot(plot)
            widget = self._plots.pop(plot)
            # FIXME: removeWidget does nothing?!
            # self.ui.plot_selection_layout.removeWidget(widget)
            widget.deleteLater()

    def rebuild_plot_selection_ui(self) -> None:
        """Build up list of plots.

        This will (re)insert all plot names in the plots list in the UI in the
        correct order and will update the checkbox and color from the underlying
        model. Note that the widgets are not being created, that must be handled
        by the `update_plots_ui()` method.
        """
        for idx, plot in enumerate(self.main_window.get_plots()):
            widget = self._plots[plot]
            # force an update on the plot name
            checkbox = widget.findChild(QtWidgets.QAbstractButton, "is_enabled_checkbox")
            checkbox.setText(plot.name)
            # force an update on the checkbox state
            checkbox.blockSignals(True)
            if plot_info := self.model.get_plot_info(plot):
                checkbox.setChecked(True)
                # force an update on the plot color
                color_button: pg.ColorButton = widget.findChild(
                    QtWidgets.QWidget, "plot_color"
                )
                color_button.blockSignals(True)
                color_button.setColor(plot_info.color)
                color_button.blockSignals(False)
                # force an update on the plot label
                label: QtWidgets.QLineEdit = widget.findChild(
                    QtWidgets.QLineEdit, "plot_label"
                )
                label.setText(plot_info.label)
            else:
                checkbox.setChecked(False)
            checkbox.blockSignals(False)
            self.ui.plot_selection_layout.insertWidget(idx, self._plots[plot])

    def update_checkbox(
        self, plot: PlotTab, widget: QtWidgets.QCheckBox, state: QtCore.Qt.CheckState
    ) -> None:
        if widget.isChecked():
            self.add_plot(plot)
        else:
            self.model.remove_plot(plot)
        self.draw_plot()
        self.main_window.mark_project_dirty()

    def add_plot(self, plot: PlotTab) -> None:
        widget = self._plots.get(plot)
        color = widget.findChild(pg.ColorButton, "plot_color").color().name() if widget is not None else plot.curve_style.color
        if not self.model.uses_plot(plot):
            from tailor.series_colors import next_colour, occupied
            if color in occupied(self):
                color = next_colour(self)
            self.model.add_plot(plot, "", color)

    def update_plot_label(self, plot: PlotTab, text: str) -> None:
        plot_info = self.model.get_plot_info(plot)
        if plot_info is None:
            return
        plot_info.label = text
        self.draw_plot()
        self.main_window.mark_project_dirty()

    def update_color(self, plot: PlotTab, color_button: pg.ColorButton) -> None:
        plot_info = self.model.get_plot_info(plot)
        if plot_info is None:
            return
        plot_info.color = color_button.color().name()
        self.draw_plot()
        self.main_window.mark_project_dirty()

    def apply_curve_style(self, style, dirty=True):
        from tailor.text_style_controls import (
            apply_text_styles,
            record_view_edit,
            sync_font_controls,
        )

        before = self.curve_style
        self.curve_style = style
        apply_text_styles(self)
        if hasattr(self, "style_target"):
            sync_font_controls(self)
        if dirty:
            record_view_edit(
                self,
                "图形字体",
                before,
                style,
                lambda target, value: target.apply_curve_style(value, dirty=False),
            )
            self.main_window.mark_project_dirty()

    def _draw_plot_items(self):
        """Reuse source PlotModels, caching native items instead of clearing scene."""
        active = {p for p, i in self.model._plots.items() if i.visible}
        for source in list(self._series):
            info = self.model.get_plot_info(source)
            expected = self.presentation.box_for(info) if info else None
            series = self._series[source]
            if source not in active or series["box"] is not expected:
                for item in (series["data"], series["fit"]):
                    if series["box"] is self.ui.plot_widget.getViewBox():
                        self.ui.plot_widget.removeItem(item)
                    else:
                        series["box"].removeItem(item)
                series["errors"].close()
                del self._series[source]
        legend = self.presentation.legend_item
        legend.clear()
        for source, info in self.model._plots.items():
            if not info.visible:
                continue
            key = "right" if info.axis == "right" else "y"
            box = self.presentation.box_for(info)
            if source not in self._series:
                data, fit = pg.PlotDataItem(), pg.PlotDataItem()
                for item in (data,fit):
                    if box is self.ui.plot_widget.getViewBox():
                        self.ui.plot_widget.addItem(item)
                    else:
                        box.addItem(item)
                # PlotItem.addItem applies its own (normally disabled) sampling
                # policy. Set the display policy after registration, or a
                # 500k series is painted in full on every inset/overlay frame.
                data.setDownsampling(auto=True, method="peak")
                data.setClipToView(True)
                data._legend_key = f"plot:{source.id}:data"
                fit._legend_key = f"plot:{source.id}:fit"
                self._series[source] = {
                    "box": box,
                    "data": data,
                    "fit": fit,
                    "errors": ErrorItems(box),
                }
            series = self._series[source]
            try:
                x, y, ex, ey = self.source_values(source)
            except (KeyError, ValueError):
                x = y = ex = ey = np.array([])
            series['data']._curve_source_count=len(x)
            style = CurveStyle(**info.style) if info.style else source.curve_style
            from tailor.appearance import ink
            from tailor.line_styles import curve_pen

            pen = (
                None
                if style.mode == "scatter"
                else curve_pen(info.color, style.line_width, style.line_style)
            )
            xlog, ylog = (
                self.presentation.axes["top" if info.x_axis == "top" else "x"]["log"],
                self.presentation.axes[key]["log"],
            )
            from tailor.plot_types import geometry

            advanced_bar = getattr(source, '_advanced_bar', False)
            gx, gy = geometry(x, y, 'line' if advanced_bar else style.mode)
            series["data"].setLogMode(xlog, ylog)
            series["data"].setData(
                gx,
                gy,
                pen=pen,
                symbol=style.marker
                if style.mode in {"scatter", "line_scatter"}
                else None,
                symbolSize=style.marker_size,
                symbolPen=ink(info.color),
                symbolBrush=ink(info.color),
                connect="finite",
            )
            from tailor.line_styles import apply_curve_extras

            if advanced_bar:
                from dataclasses import replace
                apply_curve_extras(series['data'], replace(style,mode='line',fill=False,step_mode=False))
                series['data'].hide()
            else:
                apply_curve_extras(series["data"], style)
            series["errors"].update(
                x,
                y,
                ex,
                ey,
                info.errors,
                ink(info.color),
                self.presentation.axes["top" if info.x_axis == "top" else "x"],
                self.presentation.axes[key],
            )
            if advanced_bar:
                series['errors'].x.hide();series['errors'].y.hide()
            legend.addItem(series["data"], __import__("tailor.column_titles",fromlist=["remark"]).remark(source.data_sheet.model,source.model.y_col))
        self.update_fit_items()
        legend.clear()
        for source, info in self.model._plots.items():
            if source not in self._series:
                continue
            series = self._series[source]
            label = source.model.legend_label or __import__("tailor.column_titles",fromlist=["remark"]).remark(source.data_sheet.model,source.model.y_col)
            legend.addItem(series["data"], label)
            if series["fit"].xData is not None and len(series["fit"].xData):
                record = next(
                    (r for r in source.fit_records if r["id"] == source.active_fit_id),
                    None,
                )
                stale = source.model.best_fit is None and record and record["stale"]
                legend.addItem(
                    series["fit"], (record["name"] if record else label + "拟合")
                    + (" · 已过期" if stale else "")
                )
        from tailor.fit_workflow import mirror_results
        mirror_results(self)
        self.apply_curve_style(self.curve_style, dirty=False)
        if hasattr(self, "curve_selection"):
            self.curve_selection.bind()

    def update_fit_items(self):
        xlimits = physical(
            self.ui.plot_widget.viewRange()[0], self.presentation.axes["x"]
        )
        for source, series in self._series.items():
            if source.model.best_fit is None and not source.fit_records:
                series["fit"].setData([],[])
                continue
            info = self.model.get_plot_info(source)
            key = "right" if info.axis == "right" else "y"
            xkey = "top" if info.x_axis == "top" else "x"
            xlimits = physical(
                series["box"].viewRange()[0], self.presentation.axes[xkey]
            )
            low, high = source.get_fit_curve_x_limits_for_range(*xlimits)
            x = np.linspace(low, high, NUM_POINTS)
            y = source.model.evaluate_best_fit(x)
            stale = False
            if y is None:
                record = next(
                    (r for r in source.fit_records if r["id"] == source.active_fit_id),
                    None,
                )
                if record:
                    x, y, stale = record["curve_x"], record["curve_y"], record["stale"]
            if y is None:
                series["fit"].setData([], [])
            else:
                series["fit"].setLogMode(
                    self.presentation.axes[xkey]["log"],
                    self.presentation.axes[key]["log"],
                )
                active_record=next((r for r in source.fit_records if r['id']==source.active_fit_id),{})
                series['fit'].setVisible(info.visible and not active_record.get('hidden',False))
                from tailor.series_colors import fit_colour
                series["fit"].setData(
                    x,
                    y,
                    pen=pg.mkPen(
                        ink(fit_colour(self,source,source.active_fit_id)),
                        width=derived_width(self),
                        style=QtCore.Qt.DashLine if stale else QtCore.Qt.SolidLine,
                    ),
                    connect="finite",
                )
                # During zoom, update existing fit items without adding duplicate labels.
                legend = self.presentation.legend_item
                if not any(
                    getattr(sample, '_source_item', sample.item) is series["fit"] for sample, label in legend.items
                ):
                    legend.addItem(
                        series["fit"],
                        (active_record["name"] if active_record else source.model.get_y_col_name() + "拟合")
                        + (" · 已过期" if stale else ""),
                    )

    def draw_plot(self):
        right_range=self._remembered_right_range
        self._draw_plot_items()
        if self._remembered_x_range is None:
            self.update_limits()
            # A right-Y-only pan/zoom does not emit the main X-range signal.
            # Preserve it across queued source/metadata draws too.
            if right_range is not None:
                self._block_range_signal=True
                try:self.presentation.right_box.setYRange(*right_range,padding=0)
                finally:self._block_range_signal=False
        else:
            self._block_range_signal = True
            try:
                self.ui.plot_widget.setRange(
                    xRange=self._remembered_x_range,
                    yRange=self._remembered_y_range,
                    padding=0,
                    disableAutoRange=True,
                )
                if self._remembered_right_range:
                    self.presentation.right_box.setYRange(
                        *self._remembered_right_range, padding=0
                    )
            finally:
                self._block_range_signal = False
        self.presentation.apply_axes()
        if hasattr(self, "point_inspector"):
            self.point_inspector.invalidate()
        if hasattr(self, "extras"):
            self.extras.refresh()
        if hasattr(self, "excluded_points"):
            self.excluded_points.refresh()

    def refresh_labels(self):
        if not hasattr(self,"preferences") or getattr(self,"_graph_disposed",False):
            return
        from tailor.column_titles import display, remark
        legend=self.presentation.legend_item
        legend.clear()
        for source,info in self.model._plots.items():
            info.label=display(source.data_sheet.model,source.model.y_col)
            series=self._series.get(source)
            if series is None or not info.visible:
                continue
            label=source.model.legend_label or remark(source.data_sheet.model,source.model.y_col)
            legend.addItem(series["data"],label)
            if series["fit"].isVisible() and series["fit"].xData is not None:
                record=next((r for r in source.fit_records if r['id']==source.active_fit_id),None)
                legend.addItem(series["fit"],record['name'] if record else label+'拟合')
        self.curve_manager.refresh()
        self.axis_controls.sync()
        self.presentation.apply_legend()
        self.legend_controls.sync()
        self.preferences.refresh_targets()
        if hasattr(self, 'fit_router'):
            self.fit_router.refresh()

    def _clear_remembered_zoom(self):
        self._remembered_x_range = self._remembered_y_range = (
            self._remembered_right_range
        ) = None

    def remember_right(self, *args):
        if not self._block_range_signal:
            self._remembered_right_range = tuple(
                self.presentation.right_box.viewRange()[1]
            )

    def refresh_fit_results(self):
        """Refresh only fit items and labels after an explicit fit command."""
        if getattr(self,'_graph_disposed',False) or getattr(self,'_refreshing_fit_results',False):
            return
        self._refreshing_fit_results=True
        try:
            self.update_fit_items()
            self.refresh_labels()
            from tailor.fit_workflow import mirror_results
            from tailor.text_style_controls import apply_text_styles
            mirror_results(self)
            apply_text_styles(self)
            self.presentation.apply_legend()
            self.legend_controls.refresh_entries()
            self.preferences.refresh_targets()
        finally:
            self._refreshing_fit_results=False

    def updated_plot_range(self, *args):
        if self._block_range_signal:
            return
        self._remembered_x_range, self._remembered_y_range = (
            self.ui.plot_widget.viewRange()
        )
        self.update_fit_items()

    def source_values(self, source):
        if getattr(self, '_inset_parent', None) is None:
            return source.model.get_data()
        import copy

        model = copy.copy(source.model)
        info = self.model.get_plot_info(source)
        model._axis_modes = {
            'x': self.presentation.axes['top' if info.x_axis == 'top' else 'x'].get('axis_type', 'numeric'),
            'y': self.presentation.axes['right' if info.axis == 'right' else 'y'].get('axis_type', 'numeric'),
        }
        values = model.get_data()
        if not hasattr(self, '_inset_categories'):
            self._inset_categories = {}
        self._inset_categories[source] = model._axis_categories
        return values

    def all_limits(self):
        values = {"x": [], "top": [], "y": [], "right": []}
        for source, info in self.model._plots.items():
            if not info.visible:
                continue
            try:
                x, y, ex, ey = self.source_values(source)
            except (KeyError, ValueError):
                continue
            values["top" if info.x_axis == "top" else "x"].extend((x - ex, x + ex, x))
            values["right" if info.axis == "right" else "y"].extend((y - ey, y + ey, y))
            style = CurveStyle(**info.style) if info.style else source.curve_style
            if style.mode in {"bar", "area", "stem"}:
                values["right" if info.axis == "right" else "y"].append(np.array([0.0]))
            if style.mode == "bar":
                from tailor.plot_types import geometry

                gx, _ = geometry(x, y, style.mode)
                values["top" if info.x_axis == "top" else "x"].append(gx)

        limits = {}
        for key, low, high in (
            ("x", self.model.x_min, self.model.x_max),
            ("y", self.model.y_min, self.model.y_max),
            ("right", self.presentation.right_min, self.presentation.right_max),
            ("top", self.presentation.top_min, self.presentation.top_max),
        ):
            array = np.concatenate(values[key]) if values[key] else np.array([])
            limits[key] = self.presentation.bounds(key, array, low, high)
        return limits

    def export_graph(self, filename, dpi=None):
        from tailor.canvas_export import export_canvas

        return export_canvas(self, filename, dpi)

    def _legacy_matplotlib_export(self, filename, dpi=300):
        import matplotlib.pyplot as plt

        figure, left = plt.subplots()
        try:
            right = left.twinx() if self.presentation.has_right() else None
            limits = self.all_limits()
            handles, labels = [], []
            for source, info in self.model._plots.items():
                if not info.visible:
                    continue
                axes = right if info.axis == "right" else left
                style = CurveStyle(**info.style) if info.style else source.curve_style
                x, y, ex, ey = self.source_values(source)
                label = info.label or source.model.get_y_col_name()
                handle = axes.errorbar(
                    x,
                    y,
                    xerr=mpl_error_values(
                        x,
                        ex,
                        self.presentation.axes["x"]["log"],
                        info.errors["x_visible"],
                    ),
                    yerr=mpl_error_values(
                        y,
                        ey,
                        self.presentation.axes[
                            "right" if info.axis == "right" else "y"
                        ]["log"],
                        info.errors["y_visible"],
                    ),
                    **style.mpl_options(color=info.color),
                    **mpl_errors(info.errors, info.color),
                    label=label,
                )
                handles.append(handle)
                labels.append(label)
                low, high = source.get_fit_curve_x_limits_for_range(*limits["x"])
                xx = np.linspace(low, high, NUM_POINTS)
                yy = source.model.evaluate_best_fit(xx)
                stale = False
                if yy is None:
                    record = next(
                        (
                            r
                            for r in source.fit_records
                            if r["id"] == source.active_fit_id
                        ),
                        None,
                    )
                    if record:
                        xx, yy, stale = (
                            record["curve_x"],
                            record["curve_y"],
                            record["stale"],
                        )
                if yy is not None:
                    from tailor.series_colors import fit_colour
                    (h,) = axes.plot(
                        xx,
                        yy,
                        color=fit_colour(self,source),
                        linestyle="--" if stale else "-",
                        linewidth=derived_width(self),
                    )
                    handles.append(h)
                    labels.append(label + (" · 已过期" if stale else " 拟合"))
            self.presentation.mpl_axis(
                left, "x", self.model.x_label, limits["x"], self.curve_style
            )
            self.presentation.mpl_axis(
                left, "y", self.model.y_label, limits["y"], self.curve_style
            )
            left.spines["top"].set_visible(self.presentation.frame["top"])
            left.spines["right"].set_visible(False)
            if right is not None:
                self.presentation.mpl_axis(
                    right,
                    "right",
                    self.presentation.right_label,
                    limits["right"],
                    self.curve_style,
                )
                right.spines["top"].set_visible(False)
                right.spines["left"].set_visible(False)
                right.spines["bottom"].set_visible(False)
            self.presentation.mpl_legend(left, handles, labels)
            self.annotations.export(left, right)
            figure.savefig(
                filename,
                dpi=dpi,
                transparent=self.curve_style.transparent,
                bbox_inches="tight",
            )
        finally:
            plt.close(figure)

    def update_axis_settings_from_model(self) -> None:
        """Update axis labels from model."""
        blockers=[QtCore.QSignalBlocker(getattr(self.ui,key)) for key in
                  ('xlabel','ylabel','x_min','x_max','y_min','y_max')]
        self.ui.xlabel.setText(self.model.x_label)
        self.ui.ylabel.setText(self.model.y_label)
        self.ui.x_min.setText("" if self.model.x_min is None else str(self.model.x_min))
        self.ui.x_max.setText("" if self.model.x_max is None else str(self.model.x_max))
        self.ui.y_min.setText("" if self.model.y_min is None else str(self.model.y_min))
        self.ui.y_max.setText("" if self.model.y_max is None else str(self.model.y_max))
        del blockers

    def update_xlabel(self):
        """Update the x-axis label of the plot."""
        self.model.x_label = self.ui.xlabel.text()
        self.ui.plot_widget.getAxis("bottom").enableAutoSIPrefix(False)
        self.ui.plot_widget.setLabel("bottom", self.model.x_label, units="")
        self.main_window.mark_project_dirty()

    def update_ylabel(self):
        """Update the y-axis label of the plot."""
        self.model.y_label = self.ui.ylabel.text()
        self.ui.plot_widget.getAxis("left").enableAutoSIPrefix(False)
        self.ui.plot_widget.setLabel("left", self.model.y_label, units="")
        self.main_window.mark_project_dirty()

    def on_set_limits_clicked(self):
        names = ("x_min", "x_max", "y_min", "y_max")
        old = tuple(getattr(self.model, name) for name in names)
        try:
            values = tuple(
                float(getattr(self.ui, name).text())
                if getattr(self.ui, name).text().strip()
                else None
                for name in names
            )
            for name, value in zip(names, values):
                setattr(self.model, name, value)
            self.all_limits()
            self._clear_remembered_zoom()
            self.update_limits()
            self.main_window.mark_project_dirty()
            self.main_window.statusBar().showMessage("已应用坐标范围。")
        except ValueError as error:
            for name, value in zip(names, old):
                setattr(self.model, name, value)
            self.main_window.statusBar().showMessage(str(error))

    def update_limits(self):
        limits = self.all_limits()
        self._block_range_signal = True
        try:
            self.ui.plot_widget.setRange(
                xRange=display(limits["x"], self.presentation.axes["x"]),
                yRange=display(limits["y"], self.presentation.axes["y"]),
                padding=0,
                disableAutoRange=True,
            )
            self.presentation.right_box.setYRange(
                *display(limits["right"], self.presentation.axes["right"]),
                padding=0,
            )
            self.presentation.top_box.setXRange(
                *display(limits["top"], self.presentation.axes["top"]),
                padding=0,
            )
        finally:
            self._block_range_signal = False
        self.update_fit_items()

    def get_adjusted_limits(self):
        limits = self.all_limits()
        return (*limits["x"], *limits["y"])

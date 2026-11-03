"""Tab widget containing plot with associated user interface.

A widget containing a scatter plot of some data columns with user interface
elements to specify a mathematical model to fit to the model.
"""

from tailor.compact_controls import CheckButton

import enum
import functools
from typing import TYPE_CHECKING

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets
from tailor.graph_defaults import derived_width

from tailor.appearance import ink
from tailor.curve_controls import apply_style, build_panel
from tailor.data_sheet import DataSheet
from tailor.plot_model import PlotModel
from tailor.ui_plot_tab import Ui_PlotTab

if TYPE_CHECKING:
    from tailor.app import MainWindow


NUM_POINTS = 1000
MSG_TIMEOUT = 0


DrawCurve = enum.IntEnum("DrawCurve", ["ON_DATA", "ON_DOMAIN", "ON_AXIS"])
DRAW_CURVE_OPTIONS = {
    DrawCurve.ON_DATA: "On data points",
    DrawCurve.ON_DOMAIN: "Only on fit domain",
    DrawCurve.ON_AXIS: "On full axis",
}

FITERROR_MSG = (
    "请检查模型、拟合区间、参数初值/上下界及误差列；有效点数不能少于待估参数数。"
)


class VariableError(RuntimeError):
    pass


class PlotTab(QtWidgets.QWidget):
    """Tab widget containing plot with associated user interface.

    A widget containing a scatter plot of some data columns with user interface
    elements to specify a mathematical model to fit to the model.
    """

    data_refreshed = QtCore.Signal()
    labels_refreshed = QtCore.Signal()
    inspector_ready = QtCore.Signal()

    name: str
    id: int
    main_window: "MainWindow"
    data_sheet: DataSheet
    model: PlotModel
    _params: dict[str, QtWidgets.QWidget]
    _cursor_pos: int = 0
    _remembered_x_range: tuple[float, float] | None = None
    _remembered_y_range: tuple[float, float] | None = None
    _block_range_signal: bool = False

    def __init__(
        self,
        main_window: "MainWindow",
        name: str,
        id: int,
        data_sheet: DataSheet,
        x_col: str,
        y_col: str,
        x_err_col: str | None = None,
        y_err_col: str | None = None,
        *,
        defer_inspector: bool | None = None,
        initial_style=None,
        hidden_source=False,
        inset_parent=None,
    ) -> None:
        """Initialize the widget.

        Args:
            data_sheet: the data sheet holding the data.
        """
        super().__init__(main_window if hidden_source else None)
        if hidden_source:
            # An internal curve source is parented to the project for lifetime
            # ownership. Explicitly hide it: otherwise Qt auto-shows this child
            # (including its plot/fit panel) when the project becomes visible.
            self.hide()
        if inset_parent is not None:
            self._inset_parent = inset_parent
        self.ui = Ui_PlotTab()
        self.ui.setupUi(self)
        if getattr(main_window, '_creating_advanced', False):
            self.ui.plot_widget.hide()
        from tailor.appearance import initialize_canvas
        initialize_canvas(self.ui.plot_widget)
        self.ui.show_initial_fit.setChecked(False)

        self.name = name
        self.id = id
        self.main_window = main_window
        self._defer_inspector = defer_inspector
        self._hidden_curve_source = hidden_source
        self.model = PlotModel(
            data_sheet.model.data_model, x_col, y_col, x_err_col, y_err_col
        )
        self.data_sheet = data_sheet
        self._params = {}
        self._fit_job = None
        self.fit_records = []
        self.active_fit_id = None

        from tailor.graph_defaults import new_style

        from dataclasses import replace
        self.curve_style = initial_style if initial_style is not None else new_style()
        mode = getattr(main_window, "_drawing_mode", None)
        if isinstance(mode, str):
            from dataclasses import replace
            self.curve_style = replace(self.curve_style, mode=mode)
        from tailor.graph_presentation import GraphPresentation

        self.presentation = GraphPresentation(self)
        from tailor.graph_defaults import derived_width
        derived_width(self)
        self.create_plot()
        self.finish_ui()
        self.set_fit_domain_from_data()
        # Populate the initial widgets before wiring edits. Initial spin-box
        # values and combo insertion are not user edits and must not repeatedly
        # redraw or scan the full source while this document is constructed.
        self.connect_ui_events()
        self._source_model = None
        self._source_connections = []
        self._source_timer = QtCore.QTimer(self)
        self._source_timer.setSingleShot(True)
        self._source_timer.setInterval(80)
        self._source_timer.timeout.connect(self.refresh_from_source)
        self.bind_source_events()
        self.setup_curve_controls()
        self.setup_fit_presets()

    def setup_curve_controls(self):
        build_panel(self)

    def setup_fit_presets(self):
        from tailor.fit_preset_controls import FitPresetControls

        self.preset_controls = FitPresetControls(self)
        from tailor.panel_layout import organize_single

        deferred = self._defer_inspector
        if deferred is None:
            deferred = getattr(self.main_window, "_defer_inspector", False) is True
        self._inspector_initializing = bool(deferred)
        if not self._inspector_initializing:
            organize_single(self)
            return
        self.start_inspector(organize_single(self, deferred=True))

    def start_inspector(self, stages):
        self.property_tabs.setEnabled(False)
        self._inspector_steps = stages
        self._inspector_timer = QtCore.QTimer(self)
        self._inspector_timer.setSingleShot(True)
        self._inspector_timer.setTimerType(QtCore.Qt.PreciseTimer)
        self._inspector_timer.timeout.connect(self._advance_inspector)
        self._inspector_timer.start(16)

    def _advance_inspector(self):
        if getattr(self, "_graph_disposed", False):
            self._inspector_initializing = False
            self._inspector_steps = None
            return
        try:
            # A blocker must not survive an event-loop turn: the user may close
            # the document before the next stage and Qt may destroy its tabs.
            with QtCore.QSignalBlocker(self.property_tabs):
                next(self._inspector_steps)
        except StopIteration:
            self._inspector_initializing = False
            self._inspector_steps = None
            self.property_tabs.setEnabled(True)
            self.refresh_ui()
            from tailor.appearance import manager
            manager().show_document(self)
            self.inspector_ready.emit()
            return
        except Exception as error:
            import traceback
            traceback.print_exc()
            self._inspector_initializing = False
            self._inspector_error = str(error)
            self._inspector_steps = None
            self.main_window.statusBar().showMessage("图形设置初始化失败：" + str(error))
            return
        self._inspector_timer.start(16)

    def apply_curve_style(self, style, dirty=True):
        apply_style(self, style, dirty=dirty)

    def bind_source_events(self):
        for signal, callback in self._source_connections:
            try:
                signal.disconnect(callback)
            except (RuntimeError, TypeError):
                pass
        self._source_connections = []
        self._source_model = self.data_sheet.model
        for name in (
            "dataChanged",
            "modelReset",
            "rowsInserted",
            "rowsRemoved",
            "columnsMoved",
            "columnsRemoved",
        ):
            signal = getattr(self._source_model, name)
            callback = self.data_source_changed
            signal.connect(callback)
            self._source_connections.append((signal, callback))
        signal = self._source_model.headerDataChanged
        callback = self.header_source_changed
        signal.connect(callback)
        self._source_connections.append((signal, callback))

    def data_source_changed(self, *args):
        self._source_changed = True
        if len(args) >= 2 and all(isinstance(index, QtCore.QModelIndex) for index in args[:2]):
            first, last = args[:2]
            labels = list(self.data_sheet.model.columnLabels())
            used = {self.model.x_col, self.model.y_col, self.model.x_err_col, self.model.y_err_col}
            affected = set(labels[max(0, first.column()):last.column()+1])
            if used & affected and not getattr(self, "_publishing_fit", False):
                # Never expose a fitted result as current during the debounce
                # interval. Writes to independent result columns do not revoke
                # the source fit merely because they share the same table.
                if self.model.best_fit is not None:
                    # Bulk edits also notify the full table when only an
                    # unrelated result column changed. Verify the actual fit
                    # input (including calculated columns/exclusions), instead
                    # of invalidating a correct result by notification bounds.
                    try:
                        valid = self.model.verify_best_fit_data()
                    except (KeyError, ValueError, IndexError):
                        valid = False
                        self.model.best_fit = None
                    if not valid:
                        self.fit_plot.setData([], [])
        self.queue_source_refresh(True)

    def header_source_changed(self, *args):
        self.refresh_labels()

    def refresh_labels(self):
        if getattr(self,"_graph_disposed",False):
            return
        # Undo keeps generated curve documents alive for redo, but removes
        # their columns first. Ignore table header notifications while the
        # source is absent; the next notification after redo refreshes it.
        if self.model.y_col not in self.data_sheet.model.columnLabels():
            return
        if getattr(self,"_hidden_curve_source",False):
            self.update_model_widget()
            self.refresh_legend()
            self.labels_refreshed.emit()
            return
        if not hasattr(self,"preferences"):
            return
        from tailor.column_titles import display, remark
        caption=remark(self.data_sheet.model,self.model.y_col)
        old=getattr(self,"_last_source_caption",None)
        from tailor.legend_entries import update_source_text
        update_source_text(self,"data",old,caption)
        if old is not None and self.model.legend_label == old:
            self.model.legend_label=""
        self._last_source_caption=caption
        self.update_model_widget()
        self.refresh_legend()
        self.legend_controls.sync()
        if hasattr(self,"curve_selector"):
            self.curve_selector.setItemText(0,display(self.data_sheet.model,self.model.y_col))
        self.axis_controls.sync()
        self.preferences.refresh_targets()
        self.labels_refreshed.emit()

    def queue_source_refresh(self, data_changed):
        if data_changed and hasattr(self, "point_inspector"):
            self.point_inspector.invalidate()
            from tailor.processing_controls import clear_graph_previews

            clear_graph_previews(self.main_window, {self})
        self._source_timer.start()

    def refresh_from_source(self):
        view = getattr(self, "advanced_view", None)
        if view and view.native:
            view.schedule()
            return
        self.model.data_model = self.data_sheet.model.data_model
        from tailor.fit_results import refresh_records

        refresh_records(self, check_data=True)
        try:
            self.refresh_ui()
        except (KeyError, ValueError, IndexError, TypeError) as exc:
            self.plot.setData([], [])
            for item in (self.error_items.x, self.error_items.y):
                item.setData(
                    x=np.array([]),
                    y=np.array([]),
                    left=np.array([]),
                    right=np.array([]),
                    top=np.array([]),
                    bottom=np.array([]),
                )
            self.fit_plot.setData([], [])
            self.initial_param_plot.setData([], [])
            self.main_window.statusBar().showMessage(
                f"图形 {self.name} 暂无可绘制数据：{exc}"
            )
        self.data_refreshed.emit()

    def __repr__(self) -> None:
        return f"PlotTab(id={self.id}, name={self.name})"

    def connect_ui_events(self):
        # Connect signals
        self.ui.model_func.textChanged.connect(self.update_model_expression)
        self.ui.model_func.cursorPositionChanged.connect(self.store_cursor_position)
        self.ui.show_initial_fit.stateChanged.connect(
            self.show_initial_fit_option_changed
        )
        self.ui.fit_start_box.sigValueChanging.connect(self.update_fit_domain_xmin)
        self.ui.fit_end_box.sigValueChanging.connect(self.update_fit_domain_xmax)
        self.ui.use_fit_domain.stateChanged.connect(self.set_use_fit_domain)
        self.fit_domain_area.sigRegionChanged.connect(self.fit_domain_region_changed)
        self.ui.xlabel.textChanged.connect(self.update_xlabel)
        self.ui.ylabel.textChanged.connect(self.update_ylabel)
        self.ui.set_limits_button.clicked.connect(self.on_set_limits_clicked)
        self.ui.fit_button.clicked.connect(self.perform_fit)
        self.ui.plot_widget.sigXRangeChanged.connect(self.updated_plot_range)
        self.ui.draw_curve_option.currentIndexChanged.connect(
            self.draw_curve_option_changed
        )

    def finish_ui(self):
        self.ui.param_layout = QtWidgets.QVBoxLayout()
        self.ui.param_layout.setContentsMargins(4, 0, 0, 0)
        self.ui.param_layout.setSpacing(0)
        # add stretch to prevent excessive widget sizes for small numbers of
        # parameters
        self.ui.param_layout.addStretch()
        self.ui.parameter_list.setLayout(self.ui.param_layout)

        # Set options affecting the UI
        self.ui.fit_start_box.setOpts(
            value=-np.inf, dec=True, step=0.1, finite=True, compactHeight=False
        )
        self.ui.fit_end_box.setOpts(
            value=np.inf, dec=True, step=0.1, finite=True, compactHeight=False
        )
        self.ui.fit_start_box.setMaximumWidth(75)
        self.ui.fit_end_box.setMaximumWidth(75)
        self.ui.draw_curve_option.addItems(DRAW_CURVE_OPTIONS.values())

        self.ui.plot_widget.setMenuEnabled(False)
        self.ui.plot_widget.hideButtons()

    def create_plot(self):
        """Create a plot in the widget.

        Create a plot from data in the columns specified by the given column
        names.
        """
        self.plot = self.ui.plot_widget.plot(
            symbol="o",
            pen=None,
            symbolSize=5,
            symbolPen="k",
            symbolBrush="k",
            autoDownsample=True, downsampleMethod="peak", clipToView=True,
        )
        from tailor.graph_presentation import ErrorItems

        self.error_items = ErrorItems(self.ui.plot_widget.getViewBox())
        self.error_bars = self.error_items.y
        self.initial_param_plot = self.ui.plot_widget.plot(
            symbol=None, pen=pg.mkPen(color="#DDF", width=4)
        )
        self.fit_plot = self.ui.plot_widget.plot(
            symbol=None, pen=pg.mkPen(color="#00F", width=4)
        )
        self.fit_plot.setZValue(10)
        self.fit_domain_area = pg.LinearRegionItem(movable=True, brush="#00F1")

        self.ui.plot_widget.getAxis("bottom").enableAutoSIPrefix(False)
        self.ui.plot_widget.setLabel("bottom", self.model.x_label, units="")
        self.ui.plot_widget.getAxis("left").enableAutoSIPrefix(False)
        self.ui.plot_widget.setLabel("left", self.model.y_label, units="")

    def refresh_ui(self):
        """Refresh UI after switching tabs.

        When the plot tab becomes visible again, update all data and
        information. Explicitly refresh all things that may have changed: the
        model (x-axis name change), plot curves and info box (x- and y-axis name
        changes) and possibly invalidated best fit. Because changes are
        propagated this may actually result in certain methods being called
        multiple times. Since this only happens on tab switches, we don't
        optimize that away to keep the code simple.
        """
        self.update_model_widget()
        self.update_axis_settings_from_model()
        if getattr(self,"_source_changed",True):
            self.update_plot()
            self.model.verify_best_fit_data()
        self.update_params_ui_values_from_model()
        self.update_fit_domain_from_model()
        self.update_model_curves()
        self.update_info_box()
        if hasattr(self, "preset_controls"):
            self.preset_controls.sync_model()

    def set_fit_domain_from_data(self):
        """Set fit domain using x limits from data."""
        xmin, xmax, _, _ = self.model.get_limits_from_data(padding=0)
        self.model.set_fit_domain(xmin=xmin, xmax=xmax)

    def change_data_source(
        self,
        data_sheet: DataSheet,
        x_col_name: str,
        y_col_name: str,
        x_err_col_name: str | None = None,
        y_err_col_name: str | None = None,
        *,
        refresh: bool = True,
    ) -> None:
        """Change data source of the plot.

        This method will let you change the sheet containing the underlying data, but also change the axes or error bars to other data columns. The model expression is left unchanged. That is, if you had something like `a * x + b` and your x-axis is now called `t`, you'll have to manually update the model expression.

        Args:
            data_sheet (DataSheet): the new data sheet containing the data.
            x_col_name (str): the new x column name.
            y_col_name (str): the new y column name.
            x_err_col_name (str | None, optional): the new x error column name.
                Defaults to None.
            y_err_col_name (str | None, optional): the new y error column name.
                Defaults to None.
        """
        # Save model expression using variable names. This is necessary because
        # the model is stored using column labels like col1, col2, etc. If you
        # change plot sources, you want the 'x' in your model to point to the
        # 'x' column in the data, not 'col1' to 'col1', which might be something
        # different on another data sheet.
        current_model = self.model.get_model_expression()

        # change data source
        if hasattr(self, "point_inspector"):
            self.point_inspector.invalidate()
        self.data_sheet = data_sheet
        self.bind_source_events()
        self.model.data_model = data_sheet.model.data_model
        self.model.x_col = self.model.data_model.get_column_label_by_name(x_col_name)
        self.model.y_col = self.model.data_model.get_column_label_by_name(y_col_name)
        self.model.x_err_col = (
            self.model.data_model.get_column_label_by_name(x_err_col_name)
            if x_err_col_name
            else None
        )
        self.model.y_err_col = (
            self.model.data_model.get_column_label_by_name(y_err_col_name)
            if y_err_col_name
            else None
        )

        # restore model expression using variable names
        if self.model.fit_preset_key:
            from tailor.cst_names import rename_variables
            from tailor.fit_presets import get_preset

            canonical = rename_variables(
                get_preset(self.model.fit_preset_key).expression,
                {"x": self.model.x_col},
            )
            self.model.update_model_expression(canonical, use_column_ids=True)
        else:
            self.model.update_model_expression(current_model)
        # refresh the plot UI
        self._source_changed = True
        if refresh:
            self.refresh_ui()
        else:
            # Batched operations redraw the visible host once after all
            # sources switch. Keep the reusable fitter current without
            # rendering each hidden source canvas along the way.
            self.update_model_widget()
            self.update_fit_domain_from_model()
        self.main_window.mark_project_dirty()

    def draw_curve_option_changed(self) -> None:
        """Updates UI when draw curve option is changed."""
        self.update_model_curves()
        self.main_window.mark_project_dirty()

    def get_draw_curve_option(self) -> DrawCurve:
        """Get the currently selected draw curve option.

        Returns:
            DrawCurve: the currently selected option
        """
        option_idx = self.ui.draw_curve_option.currentIndex()
        options = list(DRAW_CURVE_OPTIONS.keys())
        return options[option_idx]

    def update_model_widget(self):
        """Update function label."""
        variable = self.model.get_y_col_name()
        new_label_text = f"Function: {variable} ="
        self.ui.model_func_label.setText("拟合函数")
        self.ui.model_func_label.setToolTip(new_label_text)
        # The caption changes after the card's initial label-width pass.
        # Reuse its alignment policy so four glyphs cannot retain a two-glyph width.
        from tailor.label_alignment import align_labels
        align_labels(self.ui.model_func_label.parentWidget())
        cursor_pos = self._cursor_pos
        was_blocked = self.ui.model_func.blockSignals(True)
        self.ui.model_func.setPlainText(self.model.get_model_expression())
        self.ui.model_func.blockSignals(was_blocked)
        # cursor is reset after setting text
        cursor = self.ui.model_func.textCursor()
        cursor.setPosition(min(cursor_pos,self.ui.model_func.document().characterCount()-1))
        self.ui.model_func.setTextCursor(cursor)
        if self.model.fit_preset_key:
            self.ui.model_func_label.setText("拟合函数")
            self.ui.model_func_label.setToolTip(
                f"函数中 x 表示 {self.model.get_x_col_name()}"
            )
        self.update_expression_border()
        self.update_params_ui()

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

    def update_plot(self):
        """Update plot and restore remembered zoom range if available."""
        self._source_changed = False
        # x_err, y_err will be 0.0 if no errors are specified
        x, y, x_err, y_err = self.model.get_data()
        self.plot._curve_source_count=len(x)

        # set data for scatter plot and error bars
        from tailor.plot_types import geometry

        px, py = geometry(x, y, "line" if getattr(self, "_advanced_bar", False) else self.curve_style.mode)
        self.plot.setDownsampling(
            auto=getattr(self, "_advanced_bar", False) or self.curve_style.mode not in {"bar", "stem", "step"}, method="peak"
        )
        if self.plot.xData is None:
            # Establish the physical view before the first dataset. Otherwise
            # the initial 0..1 view prevents PG's display downsampling and the
            # scatter item allocates a marker for every source row, only to
            # discard almost all of them when update_limits runs below.
            self.update_limits()
        self.plot.setData(px, py, connect="finite")
        self.update_error_items((x, y, x_err, y_err))

        # Restore remembered zoom if available, otherwise use default limits
        if (
            self._remembered_x_range is not None
            and self._remembered_y_range is not None
        ):
            # Block signals to prevent triggering updated_plot_range() when
            # restoring the remembered zoom but blockSignals does not work
            # self.ui.plot_widget.blockSignals(True)
            self._block_range_signal = True
            self.ui.plot_widget.setRange(
                xRange=self._remembered_x_range,
                yRange=self._remembered_y_range,
                padding=0,
                disableAutoRange=True,
            )
            # self.ui.plot_widget.blockSignals(False)
            self._block_range_signal = False
        else:
            self.update_limits()
        self.presentation.apply_single_items()
        if (
            self.curve_style.mode in {"bar", "area", "stem"}
            and not self._remembered_y_range
        ):
            box = self.ui.plot_widget.getViewBox()
            if (
                not self.presentation.axes["y"]["log"]
                and self.model.y_min is None
                and self.model.y_max is None
            ):
                bounds = box.viewRange()[1]
                box.setYRange(min(0, bounds[0]), max(0, bounds[1]), padding=0)
            if (
                self.curve_style.mode == "bar"
                and self.model.x_min is None
                and self.model.x_max is None
                and not self.presentation.axes["x"]["log"]
            ):
                finite = px[np.isfinite(px)]
                if len(finite):
                    bounds = box.viewRange()[0]
                    box.setXRange(
                        min(bounds[0], float(finite.min())),
                        max(bounds[1], float(finite.max())),
                        padding=0.02,
                    )

    def update_error_items(self, data=None):
        data = self.model.get_data() if data is None else data
        self.error_items.update(
            *data,
            self.presentation.errors,
            ink(self.curve_style.color),
            self.presentation.axes["x"],
            self.presentation.axes["y"],
        )

    def _clear_remembered_zoom(self):
        """Clear the remembered zoom range.

        This should be called when the user manually changes axis limits,
        as the remembered zoom is no longer valid.
        """
        self._remembered_x_range = None
        self._remembered_y_range = None

    def update_info_box(self):
        """Update the information box."""
        msgs = []
        msgs.append(f"来源：{self.data_sheet.name} · {self.model.get_y_col_name()}")
        if self.model.best_fit is not None:
            msgs.append(self.format_fit_results())
        self.ui.result_box.setPlainText("\n".join(msgs))
        self.refresh_legend()

    def refresh_legend(self):
        if not hasattr(self, "fit_plot"):
            return
        legend = self.ui.plot_widget.getPlotItem().legend
        if legend is None:
            legend = self.ui.plot_widget.addLegend(offset=(-12, 12))
        legend.clear()
        self.plot._legend_key = "data"
        self.fit_plot._legend_key = "fit"
        from tailor.column_titles import remark
        label = self.model.legend_label or remark(self.data_sheet.model, self.model.y_col)
        self._last_source_caption=remark(self.data_sheet.model,self.model.y_col)
        if self.curve_style.visible:
            legend.addItem(self.plot, label)
        if self.model.best_fit is not None and self.fit_plot.isVisible():
            active = next(
                (r for r in self.fit_records if r["id"] == self.active_fit_id), None
            )
            legend.addItem(
                self.fit_plot,
                active["name"] if active else label + "拟合",
            )
            for i, curve in enumerate(getattr(self, "_component_curves", []), 1):
                curve._legend_key = f"component:{i}"
                from tailor.fit_results import curve_column
                key = curve_column(active or {}, f'component:{i}')
                caption = remark(self.data_sheet.model, key) if key in self.data_sheet.model.columnLabels() else f"分峰 {i}（含基线）"
                legend.addItem(curve, caption)
        elif self.active_fit_id is not None and self.fit_plot.isVisible():
            record = next(
                (r for r in self.fit_records if r["id"] == self.active_fit_id), None
            )
            if record:
                legend.addItem(
                    self.fit_plot,
                    record["name"] + (" · 已过期" if record["stale"] else ""),
                )
        if hasattr(self, "fit_actions"):
            for key, item in self.fit_actions.curves.items():
                record = next((r for r in self.fit_records if r["id"] == key), None)
                if record and item.isVisible():
                    legend.addItem(item, record["name"])
        if hasattr(self, "processing_controls"):
            preview = self.processing_controls.preview
            if preview.xData is not None and len(preview.xData):
                preview._legend_key = "processing"
                legend.addItem(preview, "处理预览")
        legend.setVisible(self.model.legend_visible)
        from tailor.text_style_controls import apply_text_styles

        apply_text_styles(self)
        self.presentation.apply_legend()
        if hasattr(self, 'curve_selection'):
            self.curve_selection.refresh()

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

    def update_x_min(self):
        """Update the minimum x axis limit."""
        try:
            value = float(self.ui.x_min.text())
        except ValueError:
            value = None
        self.model.x_min = value
        self._clear_remembered_zoom()
        self.update_limits()
        self.main_window.mark_project_dirty()

    def update_x_max(self):
        """Update the minimum x axis limit."""
        try:
            value = float(self.ui.x_max.text())
        except ValueError:
            value = None
        self.model.x_max = value
        self._clear_remembered_zoom()
        self.update_limits()
        self.main_window.mark_project_dirty()

    def update_y_min(self):
        """Update the minimum x axis limit."""
        try:
            value = float(self.ui.y_min.text())
        except ValueError:
            value = None
        self.model.y_min = value
        self._clear_remembered_zoom()
        self.update_limits()
        self.main_window.mark_project_dirty()

    def update_y_max(self):
        """Update the minimum x axis limit."""
        try:
            value = float(self.ui.y_max.text())
        except ValueError:
            value = None
        self.model.y_max = value
        self._clear_remembered_zoom()
        self.update_limits()
        self.main_window.mark_project_dirty()

    def on_set_limits_clicked(self):
        self.range_controls.apply()

    def apply_axis_bounds(self, values, dirty=True):
        from tailor.text_style_controls import record_view_edit

        original = tuple(
            getattr(self.model, key) for key in ("x_min", "x_max", "y_min", "y_max")
        )
        self.presentation.single_limits(values)
        for key, value in zip(
            ("x_min", "x_max", "y_min", "y_max"), values, strict=True
        ):
            setattr(self.model, key, value)
            blocker = QtCore.QSignalBlocker(getattr(self.ui, key))
            getattr(self.ui, key).setText("" if value is None else f"{value:g}")
            del blocker
        self._clear_remembered_zoom()
        self.update_limits()
        if dirty:
            record_view_edit(
                self,
                "坐标范围",
                original,
                tuple(values),
                lambda target, state: target.apply_axis_bounds(state, dirty=False),
            )
            self.main_window.mark_project_dirty()

    def update_limits(self):
        """Update the axis limits of the plot."""
        self.presentation.set_single_limits()

    def get_adjusted_limits(self):
        return self.presentation.single_limits()

    def update_model_expression(self):
        """Update the model expression and related UI."""
        expression = self.ui.model_func.toPlainText()
        is_updated = self.model.update_model_expression(expression)
        self.update_expression_border()
        self.update_params_ui()
        self.plot_initial_model()
        self.plot_best_fit()
        if is_updated:
            self.main_window.mark_project_dirty()
        self.update_info_box()
        if hasattr(self, "preset_controls"):
            self.preset_controls.sync_model()

    def update_expression_border(self) -> None:
        """Update border of the model expression widget.

        If the model expression is not valid, draw a red border around the
        widget.
        """
        if self.model.is_model_valid():
            self.ui.model_func.setStyleSheet("border: 0px")
        else:
            self.ui.model_func.setStyleSheet("border: 1px solid red")

    def store_cursor_position(self):
        """Store the cursor position inside the model expression."""
        self._cursor_pos = self.ui.model_func.textCursor().position()

    def update_params_ui(self):
        """Add and/or remove parameters if necessary."""
        old_params = set(self._params)
        current_params = set(self.model.get_parameter_names())
        self.add_params_to_ui(current_params - old_params)
        self.remove_params_from_ui(old_params - current_params)

    def add_params_to_ui(self, params):
        """Add parameters to user interface.

        When the model function is changed and certain parameters are now part
        of the expression, they need to be added to the user interface.

        Args:
            params: a list of parameter names to add to the user interface.
        """
        for param in self.model.get_parameter_names():
            if param not in params:
                continue
            # create widgets
            from tailor.fit_results import parameter_label

            label = QtWidgets.QLabel(parameter_label(param, self.model.fit_preset_key))
            label.setToolTip(param)
            label.setFixedWidth(78)
            value_box = pg.SpinBox(
                value=1.0,
                dec=True,
                step=0.1,
                minStep=0,
                finite=True,
                compactHeight=False,
            )
            value_box.setObjectName("value")
            value_box._parameter = param
            min_box = pg.SpinBox(value=-np.inf, finite=False, compactHeight=False)
            min_box.setObjectName("min")
            min_box._parameter = param
            max_box = pg.SpinBox(value=+np.inf, finite=False, compactHeight=False)
            max_box.setObjectName("max")
            max_box._parameter = param
            is_fixed_checkbox = CheckButton("", objectName="is_fixed")
            is_fixed_checkbox.setText('定')
            is_fixed_checkbox.setStyleSheet('QPushButton {padding:0;min-width:0;}')
            is_fixed_checkbox._parameter = param
            is_fixed_checkbox.setToolTip("固定 " + param)
            is_fixed_checkbox.setFixedWidth(22)

            from tailor.parameter_history import ParameterHistory
            parameter_history = ParameterHistory(self,param,(value_box,min_box,max_box),is_fixed_checkbox)
            # connect signals to changes in parameter values or bounds
            value_box.sigValueChanging.connect(self.update_parameter_value)
            min_box.sigValueChanging.connect(self.update_parameter_min_bound)
            max_box.sigValueChanging.connect(self.update_parameter_max_bound)
            is_fixed_checkbox.stateChanged.connect(
                functools.partial(self.update_parameter_fixed_state, is_fixed_checkbox)
            )

            is_fixed_checkbox.stateChanged.connect(parameter_history.finish)
            # build parameter layout
            layout = QtWidgets.QHBoxLayout()
            layout.addWidget(label)
            layout.addWidget(value_box)
            layout.addWidget(min_box)
            layout.addWidget(max_box)
            layout.addWidget(is_fixed_checkbox)
            layout.setSpacing(3)
            value_box.setMinimumWidth(48)
            value_box.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
            min_box.setMinimumWidth(40)
            min_box.setMaximumWidth(68)
            min_box.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
            max_box.setMinimumWidth(40)
            max_box.setMaximumWidth(68)
            max_box.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
            layout.setContentsMargins(0, 0, 0, 0)

            # put layout into widget
            layout_widget = QtWidgets.QWidget()
            layout_widget.setLayout(layout)
            parameter_history.setParent(layout_widget)

            # store parameter layout
            self._params[param] = layout_widget
            # determine position to insert the parameter in alphabetical order
            sorted_params = sorted(self._params.keys(), key=lambda x: x.lower())
            idx = sorted_params.index(param)
            self.ui.param_layout.insertWidget(idx, layout_widget)
            # A spin box may already be polished before it is inserted into
            # this inspector. Apply the same row/display policy explicitly.
            from tailor.fold_panel import normalize_control_heights
            normalize_control_heights(layout_widget)

    def remove_params_from_ui(self, params):
        """Remove parameters from user interface.

        When the model function is changed and certain parameters are no longer
        part of the expression, remove them from the user interface.

        Args:
            params: a list of parameter names to remove from the user interface.
        """
        for param in params:
            layout_widget = self._params.pop(param)
            self.ui.param_layout.removeWidget(layout_widget)
            layout_widget.deleteLater()

    def update_parameter_value(self, widget, value):
        self.model.set_parameter_value(widget._parameter, value)
        self.update_model_curves()
        self.main_window.mark_project_dirty()

    def update_parameter_min_bound(self, widget, value):
        self.model.set_parameter_min_value(widget._parameter, value)
        self.update_model_curves()
        self.main_window.mark_project_dirty()

    def update_parameter_max_bound(self, widget, value):
        self.model.set_parameter_max_value(widget._parameter, value)
        self.update_model_curves()
        self.main_window.mark_project_dirty()

    def update_parameter_fixed_state(self, widget, fixed_state):
        vary_state = not fixed_state
        self.model.set_parameter_vary_state(widget._parameter, vary_state)
        self.update_model_curves()
        self.main_window.mark_project_dirty()

    def update_params_ui_values_from_model(self):
        """Update the parameters UI to sync with model.

        Changed parameter values in the UI will propagate to the PlotModel
        instance managing all plot data, but you will need to call this method
        to propagate changed model values back to the UI.

        This method expects that all model parameters already exist within the
        UI.
        """
        for name in self.model.get_parameter_names():
            parameter = self.model.get_parameter_by_name(name)
            widget = self._params[parameter.name]
            for w in widget.findChildren(QtWidgets.QWidget):
                w.blockSignals(True)
            widget.findChild(QtWidgets.QWidget, "min").setValue(parameter.min)
            widget.findChild(QtWidgets.QWidget, "value").setValue(parameter.value)
            widget.findChild(QtWidgets.QWidget, "max").setValue(parameter.max)
            widget.findChild(QtWidgets.QWidget, "is_fixed").setChecked(
                not parameter.vary
            )
            for w in widget.findChildren(QtWidgets.QWidget):
                w.blockSignals(False)

    def set_use_fit_domain(self, state):
        """Enable or disable use of fit domain.

        Args:
            state: integer (enum Qt::CheckState) with the checkbox state.
        """
        if state == QtCore.Qt.Checked.value:
            self.model.set_fit_domain_enabled(True)
            self.ui.plot_widget.removeItem(self.fit_domain_area)
        else:
            self.model.set_fit_domain_enabled(False)
            self.ui.plot_widget.removeItem(self.fit_domain_area)
        self.update_model_curves()
        self.main_window.mark_project_dirty()

    def fit_domain_region_changed(self):
        """Update the fit domain values.

        When the fit domain region is dragged by the user, the values in the
        start and end boxes need to be updated.
        """
        xmin, xmax = self.fit_domain_area.getRegion()
        self.ui.fit_start_box.setValue(xmin)
        self.ui.fit_end_box.setValue(xmax)
        self.main_window.mark_project_dirty()

    def update_fit_domain_xmin(self, widget, xmin: float) -> None:
        """Update fit domain lower bound.

        Update the lower bound of the fit domain in the model and update the
        shaded region in the plot. If the lower bound is greater than the upper
        bound, the upper bound is pushed to the right and both bounds are equal.

        Args:
            widget (Any): the spinbox widget (ignored).
            xmin (float): the new value for the lower bound.
        """
        xmax = self.ui.fit_end_box.value()
        if xmax < xmin:
            xmax = xmin
            self.ui.fit_end_box.setValue(xmax)
        self.model.set_fit_domain(xmin=xmin, xmax=xmax)
        self.fit_domain_area.blockSignals(True)
        self.fit_domain_area.setRegion((xmin, xmax))
        self.fit_domain_area.blockSignals(False)
        self.update_model_curves()
        self.main_window.mark_project_dirty()

    def update_fit_domain_xmax(self, widget, xmax: float) -> None:
        """Update fit domain upper bound.

        Update the upper bound of the fit domain in the model and update the
        shaded region in the plot. If the upper bound is smaller than the lower
        bound, the lower bound is pushed to the left and both bounds are equal.

        Args:
            widget (Any): the spinbox widget (ignored).
            xmin (float): the new value for the upper bound.
        """
        xmin = self.ui.fit_start_box.value()
        if xmin > xmax:
            xmin = xmax
            self.ui.fit_start_box.setValue(xmin)
        self.model.set_fit_domain(xmin=xmin, xmax=xmax)
        self.fit_domain_area.blockSignals(True)
        self.fit_domain_area.setRegion((xmin, xmax))
        self.fit_domain_area.blockSignals(False)
        self.update_model_curves()
        self.main_window.mark_project_dirty()

    def update_fit_domain_from_model(self) -> None:
        """Update fit domain parameters from model.

        Update the fit domain UI widgets with values taken from the plot model.
        Makes sure signals are not unnecessarily triggered which would result in
        invalidating the best fit. The best fit is preserved by this method.
        """
        self.ui.fit_start_box.blockSignals(True)
        self.ui.fit_end_box.blockSignals(True)
        self.ui.use_fit_domain.blockSignals(True)
        self.fit_domain_area.blockSignals(True)
        xmin, xmax = self.model.get_fit_domain()
        self.ui.fit_start_box.setValue(xmin)
        self.ui.fit_end_box.setValue(xmax)
        if self.model.get_fit_domain_enabled():
            state = QtCore.Qt.CheckState.Checked
        else:
            state = QtCore.Qt.CheckState.Unchecked
        self.ui.use_fit_domain.setCheckState(state)
        self.fit_domain_area.setRegion((xmin, xmax))
        self.ui.fit_start_box.blockSignals(False)
        self.ui.fit_end_box.blockSignals(False)
        self.ui.use_fit_domain.blockSignals(False)
        self.fit_domain_area.blockSignals(False)

    def update_model_curves(self):
        """Update initial and best fit curves."""
        from tailor.fit_results import refresh_records

        refresh_records(self)
        self.plot_initial_model()
        self.plot_best_fit()
        self.update_info_box()
        self.presentation.apply_single_items()

    def updated_plot_range(self):
        """Handle updated plot range.

        If the fitted curves are drawn on the full axis, they need to be updated
        when the plot range is changed. Also remember the current zoom range so
        it can be restored when returning to this tab.
        """
        # Only remember zoom after initial setup is complete
        if not self._block_range_signal:
            [[x_min, x_max], [y_min, y_max]] = self.ui.plot_widget.viewRange()
            self._remembered_x_range = (x_min, x_max)
            self._remembered_y_range = (y_min, y_max)

        if self.get_draw_curve_option() == DrawCurve.ON_AXIS:
            self.update_model_curves()

    def show_initial_fit_option_changed(self) -> None:
        """Updates UI when show initial fit option is changed."""
        self.plot_initial_model()
        self.main_window.mark_project_dirty()

    def plot_initial_model(self):
        """Plot model with initial parameters.

        Plots the model with the initial parameters as given in the user
        interface.
        """
        if self.ui.show_initial_fit.isChecked():
            x_min, x_max = self.get_fit_curve_x_limits()
            x = np.linspace(x_min, x_max, NUM_POINTS)
            y = self.model.evaluate_model(x)
            if y is not None:
                self.initial_param_plot.setData(x, y)
                self.initial_param_plot.setLogMode(
                    self.presentation.axes["x"]["log"],
                    self.presentation.axes["y"]["log"],
                )
                return
        # in all other cases: reset data
        self.initial_param_plot.setData([], [])

    def perform_fit(self):
        owner = self.main_window
        if self._fit_job is not None:
            self._fit_job.requestInterruption()
            self.ui.fit_button.setEnabled(False)
            self.ui.fit_button.setText("正在取消…")
            owner.statusBar().showMessage("已请求取消；等待当前计算返回。")
            return
        if hasattr(owner, "data_operation_busy") and owner.data_operation_busy():
            owner.statusBar().showMessage("请等待当前后台操作结束或取消。")
            return
        try:
            snapshot = self.model.fit_snapshot()
        except Exception as error:  # noqa: BLE001 - keep live data on snapshot failure
            owner.statusBar().showMessage(f"无法开始拟合：{error}")
            return
        from tailor.fit_results import fit_token
        from tailor.fit_worker import FitJob

        self._fit_token = fit_token(self.model)
        owner._fit_busy = True
        self._fit_button_text = self.ui.fit_button.text()
        self.ui.fit_button.setText("取消拟合")
        self._fit_job = FitJob(snapshot, owner)
        self._fit_job.progress.connect(self._fit_progress)
        self._fit_job.finished.connect(self._fit_finished)
        owner.statusBar().showMessage(
            "正在后台拟合；可继续操作，修改后旧结果将被丢弃。"
        )
        self._fit_job.start()

    def _fit_progress(self, evaluations):
        if self._fit_job is not None and not self._fit_job.isInterruptionRequested():
            self.main_window.statusBar().showMessage(
                f"正在拟合：已评估 {evaluations:,} 次；点击“取消拟合”可停止。"
            )

    def _fit_finished(self):
        job = self._fit_job
        owner = self.main_window
        owner._fit_busy = False
        self.ui.fit_button.setEnabled(True)
        self.ui.fit_button.setText(self._fit_button_text)
        try:
            if job.isInterruptionRequested() or job.outcome == "cancelled":
                message = "拟合已取消；原数据保留。"
            elif not self.fit_inputs_unchanged():
                message = "数据或设置已改变，已丢弃过期拟合结果，请重新拟合。"
            elif job.outcome != "success":
                message = f"拟合未完成：{job.error}。{FITERROR_MSG}"
            else:
                # Do not retain the worker through lmfit's iteration callback.
                job.result.iter_cb = None
                from tailor.fit_results import publish_result

                try:
                    publish_result(self, job.result)
                except (ValueError, KeyError, IndexError) as error:
                    message = f"拟合结果未写入：{error}"
                else:
                    self.model.best_fit = job.result
                    self.model._fit_data_checksum = job.checksum
                    owner.mark_project_dirty()
                    message = "拟合完成：源表已写入拟合列，顶部蓝色结果页可查看参数。"
            self.plot_best_fit()
            self.update_info_box()
            owner.statusBar().showMessage(message)
            self.data_refreshed.emit()
            host=getattr(self,'_fit_host',None)
            if host is not None and not getattr(host,'_graph_disposed',False):
                host.refresh_fit_results()
        finally:
            if job.snapshot.best_fit is not None:
                job.snapshot.best_fit.iter_cb = None
            job.deleteLater()
            self._fit_job = None
            if hasattr(self, "fit_actions"):
                self.fit_actions.sync()

    def fit_inputs_unchanged(self):
        from tailor.fit_results import fit_token

        try:
            return fit_token(self.model) == self._fit_token
        except (ValueError, KeyError, IndexError):
            return False

    def plot_best_fit(self):
        """Update the plot of the best-fit model curve.

        Plots the model with the best fit parameters if they are previously
        determined by performing a fit.
        """
        if self.model.best_fit is None and not self.fit_records:
            self.fit_plot.setData([], [])
            for component in getattr(self,"_component_curves",[]):
                self.ui.plot_widget.removeItem(component)
            self._component_curves=[]
            if hasattr(self,"fit_actions"):
                self.fit_actions.render()
            if hasattr(self,"extras"):
                self.extras.refresh()
            return
        from tailor.series_colors import fit_colour
        x_min, x_max = self.get_fit_curve_x_limits()
        x = np.linspace(x_min, x_max, NUM_POINTS)
        y = self.model.evaluate_best_fit(x)
        if y is not None:
            self.fit_plot.setData(x, y)
            self.fit_plot.setPen(color=fit_colour(self,self), width=derived_width(self))
        else:
            record = next(
                (r for r in self.fit_records if r["id"] == self.active_fit_id), None
            )
            if record:
                self.fit_plot.setData(record["curve_x"], record["curve_y"])
                self.fit_plot.setPen(
                    color=fit_colour(self,self), width=derived_width(self)
                )
            else:
                self.fit_plot.setData([], [])
        for component in getattr(self, "_component_curves", []):
            self.ui.plot_widget.removeItem(component)
        self._component_curves = []
        if self.model.best_fit is not None and str(
            self.model.fit_preset_key
        ).startswith(("double_", "multi_")):
            from tailor.fit_presets import create_library_model

            native = create_library_model(self.model.fit_preset_key)
            values = {
                name: parameter.value
                for name, parameter in self.model.best_fit.params.items()
            }
            params = native.make_params(
                **{k: v for k, v in values.items() if k != "offset"}
            )
            for i, component in enumerate(native.components):
                color = fit_colour(self,self,self.active_fit_id,i+1)
                curve = self.ui.plot_widget.plot(
                    x,
                    component.eval(params=params, x=x) + values.get("offset", 0),
                    pen=pg.mkPen(color, width=derived_width(self), style=QtCore.Qt.DashLine),
                )
                curve.setZValue(11)
                self._component_curves.append(curve)

        if hasattr(self, "fit_actions"):
            self.fit_actions.render()
        if hasattr(self, "extras"):
            self.extras.refresh()

    def get_fit_curve_x_limits(self):
        """Get x-axis limits for fit curve.

        This method respects the choice in the 'Draw curve' option box.

        Returns:
            x_min, x_max: tuple of floats with the x-axis limits
        """
        option = self.get_draw_curve_option()
        if option == DrawCurve.ON_DATA:
            x_min, x_max, _, _ = self.model.get_limits_from_data(padding=0)
        elif option == DrawCurve.ON_DOMAIN:
            x_min, x_max = self.model.get_fit_domain()
        elif option == DrawCurve.ON_AXIS:
            from tailor.graph_presentation import physical

            [[x_min, x_max], _] = self.ui.plot_widget.viewRange()
            x_min, x_max = physical([x_min, x_max], self.presentation.axes["x"])
        return x_min, x_max

    def get_fit_curve_x_limits_for_range(self, x_min=None, x_max=None):
        """Get x-axis limits for fit curve with optional override range.

        This method respects the choice in the 'Draw curve' option box.
        When the option is 'ON_AXIS' and override limits are provided,
        those limits are returned instead of the plot tab's own view range.
        This is useful when drawing the fit curve on a multiplot with
        different axis limits.

        Args:
            x_min (float, optional): override x minimum limit for ON_AXIS option
            x_max (float, optional): override x maximum limit for ON_AXIS option

        Returns:
            x_min, x_max: tuple of floats with the x-axis limits
        """
        option = self.get_draw_curve_option()
        if option == DrawCurve.ON_DATA:
            x_min, x_max, _, _ = self.model.get_limits_from_data(padding=0)
        elif option == DrawCurve.ON_DOMAIN:
            x_min, x_max = self.model.get_fit_domain()
        elif option == DrawCurve.ON_AXIS and (x_min is None or x_max is None):
            # Use override limits if provided, otherwise use plot widget range
            from tailor.graph_presentation import physical

            [[x_min, x_max], _] = self.ui.plot_widget.viewRange()
            x_min, x_max = physical([x_min, x_max], self.presentation.axes["x"])
        return x_min, x_max

    def format_plot_info(self):
        """Format basic plot information in the results box.

        Returns:
            A string containing the formatted plot information.
        """
        msg = make_header("数据来源")
        msg += make_table(
            [
                # make sure everything is a string, even None
                (
                    "X: ",
                    str(self.model.get_x_col_name()),
                    " +- ",
                    str(self.model.get_x_err_col_name() or 0),
                    f" (from {self.data_sheet.name})",
                ),
                (
                    "Y: ",
                    str(self.model.get_y_col_name()),
                    " +- ",
                    str(self.model.get_y_err_col_name() or 0),
                    f" (from {self.data_sheet.name})",
                ),
            ]
        )
        return msg

    def format_fit_results(self):
        """Format the results of the fit in the user interface.

        Returns:
            A string containing the formatted fit results.
        """
        fit = self.model.best_fit
        msg = make_header("拟合参数（值 ± 标准误）")
        for name, parameter in fit.params.items():
            error = (
                f" ± {parameter.stderr:.4g}"
                if parameter.stderr is not None
                else "（误差未知）"
            )
            msg += f"{name}: {parameter.value:.6g}{error}\n"
        msg += "\n"
        msg += make_header("拟合统计")
        msg += make_table(
            [
                ("评估次数", " = ", f"{fit.nfev:<9.4g}"),
                ("约化卡方", " = ", f"{fit.redchi:<9.4g}"),
                ("自由度", " = ", f"{fit.nfree:<9.4g}"),
            ]
        )
        if hasattr(self, "preset_controls"):
            msg += self.preset_controls.result_summary()
        return msg

    def export_graph(self, filename, dpi=None):
        if getattr(self, 'advanced_view', None) is not None:
            return self.advanced_view.export(filename, dpi)
        from tailor.canvas_export import export_canvas

        return export_canvas(self, filename, dpi)

    def _legacy_matplotlib_export(self, filename, dpi=300):
        import matplotlib.pyplot as plt

        """Export graph to a file.

        Args:
            filename: path to the file.
        """
        # x_err, y_err will be 0.0 if no errors are specified
        x, y, x_err, y_err = self.model.get_data()
        xmin, xmax, ymin, ymax = self.get_adjusted_limits()

        from tailor.graph_presentation import mpl_error_values, mpl_errors

        errors = self.presentation.errors
        figure = plt.figure()
        try:
            plt.errorbar(
                x,
                y,
                xerr=mpl_error_values(
                    x, x_err, self.presentation.axes["x"]["log"], errors["x_visible"]
                ),
                yerr=mpl_error_values(
                    y, y_err, self.presentation.axes["y"]["log"], errors["y_visible"]
                ),
                **self.curve_style.mpl_options(),
                **mpl_errors(errors, self.curve_style.color),
                label=self.model.legend_label or self.model.get_y_col_name(),
            )

            x_min, x_max = self.get_fit_curve_x_limits()
            x = np.linspace(x_min, x_max, NUM_POINTS)
            y = self.model.evaluate_best_fit(x)
            if y is not None:
                from tailor.fit_presets import get_preset

                title = (
                    get_preset(self.model.fit_preset_key).title
                    if self.model.fit_preset_key
                    else "自定义"
                )
                from tailor.series_colors import fit_colour
                plt.plot(x, y, color=fit_colour(self,self), linewidth=derived_width(self), label=title + " 拟合")
                if self.model.fit_preset_key in {
                    "double_gaussian",
                    "double_lorentzian",
                }:
                    from tailor.fit_presets import create_library_model

                    native = create_library_model(self.model.fit_preset_key)
                    values = {
                        name: parameter.value
                        for name, parameter in self.model.best_fit.params.items()
                    }
                    params = native.make_params(
                        **{k: v for k, v in values.items() if k != "offset"}
                    )
                    for i, component in enumerate(native.components, 1):
                        color = fit_colour(self,self,self.active_fit_id,i)
                        plt.plot(
                            x,
                            component.eval(params=params, x=x)
                            + values.get("offset", 0),
                            color=color,
                            linestyle="--",
                            label=f"分峰 {i}（含基线）",
                        )
            else:
                record = next(
                    (r for r in self.fit_records if r["id"] == self.active_fit_id), None
                )
                if record:
                    plt.plot(
                        record["curve_x"],
                        record["curve_y"],
                        color="#b78787",
                        label=record["title"] + " · 已过期",
                    )

            if self.ui.show_initial_fit.isChecked():
                y = self.model.evaluate_model(x)
                if y is not None:
                    plt.plot(x, y, "b-", alpha=0.2)

            if self.model.get_fit_domain_enabled():
                plt.axvspan(*self.model.get_fit_domain(), facecolor="k", alpha=0.1)

            from tailor.text_style_controls import export_font_families, font_spec

            if self.model.legend_visible:
                spec = font_spec(self.curve_style, "legend")
                plt.legend(
                    loc="upper right",
                    prop={
                        "size": spec["size"],
                        "family": export_font_families(spec["family"]),
                    },
                )
            axes = plt.gca()
            for prefix, title, setter, ticks in (
                ("x", self.model.x_label, axes.set_xlabel, axes.get_xticklabels()),
                ("y", self.model.y_label, axes.set_ylabel, axes.get_yticklabels()),
            ):
                spec = font_spec(self.curve_style, prefix + "_label")
                setter(
                    title,
                    fontsize=spec["size"],
                    fontfamily=export_font_families(spec["family"]),
                )
                spec = font_spec(self.curve_style, prefix + "_ticks")
                for tick in ticks:
                    tick.set_fontsize(spec["size"])
                    tick.set_fontfamily(export_font_families(spec["family"]))
            plt.xlim(xmin, xmax)
            plt.ylim(ymin, ymax)
            self.presentation.mpl_axis(
                axes, "x", self.model.x_label, (xmin, xmax), self.curve_style
            )
            self.presentation.mpl_axis(
                axes, "y", self.model.y_label, (ymin, ymax), self.curve_style
            )
            axes.spines["top"].set_visible(self.presentation.frame["top"])
            axes.spines["right"].set_visible(self.presentation.frame["right"])
            self.presentation.mpl_legend(axes)
            self.annotations.export(axes)
            plt.savefig(filename, dpi=dpi, transparent=self.curve_style.transparent)
        finally:
            plt.close(figure)


def make_header(text):
    """Make header text with underlined with dashed.

    Returns:
        A string with the formatted header text.
    """
    return text + "\n" + len(text) * "-" + "\n"


def make_table(data):
    """Format data in a table.

    Calculates the width of the column texts to lay out the table. All values must be passed as string to make the layout work correctly.

    Args:
        data: list of (text1, text2, ...) tuples of string values.

    Returns:
        A string with the formatted table text.
    """
    cols = zip(*data)
    widths = [max([len(row) for row in col]) for col in cols]
    table = ""
    for row in data:
        for txt, col_width in zip(row, widths):
            fmt = f"{{:{col_width}s}}"
            table += fmt.format(txt)
        table += "\n"
    return table


def make_param_table(params):
    """Format parameter values in a table.

    Calculates the width of the first column based on parameter names. Formats the parameter values and uncertainties in a general format with precision 4.

    Args:
        params: a lmfit.Parameters object.

    Returns:
        A string with the formatted table text.
    """
    if params:
        width = max([len(p) for p in params])
        text = ""
        fmt = "{:" + str(width) + "s} = {:< 12.6g} +/- {:< 12.6g} ({:s} %)\n"
        for p in sorted(params, key=lambda x: x.lower()):
            value = params[p].value
            stderr = params[p].stderr
            if stderr is None:
                stderr = 0
            try:
                rel_err = f"{abs(stderr / value * 100):.1f}"
            except ZeroDivisionError:
                rel_err = "--"
            text += fmt.format(p, value, stderr, rel_err)
        return text
    else:
        return ""

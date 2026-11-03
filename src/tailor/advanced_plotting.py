"""Advanced views on existing PlotTab/DataModel, native PG bars/panels, mpl Axes3D."""

import copy
import math
import os
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from tailor.compact_controls import preference_button, toggle_button
from tailor.fold_panel import FoldPanel
from tailor.graph_controls import combo, number, row
from tailor.ui_widgets import data_index

KINDS = [("组图", "panels"), ("三维图", "3d"), ("柱状图", "bar")]
COLORS = ["#2878cc", "#d47532", "#40936b", "#9660b8", "#d34d6b", "#3f9da9", "#9b853c"]


def sheets(owner):
    return {sheet.id: sheet for sheet in owner.get_data_sheets()}


def column_info(owner, ref):
    sheet = sheets(owner)[ref[0]]
    keys = list(sheet.model.columnLabels())
    meta = sheet.model.column_metadata(keys.index(ref[1]))
    return sheet, meta


def set_mode(sheet, mode):
    # Advanced mode belongs to the resulting graph, never locks the whole sheet.
    sheet._advanced_mode = None
    picker = getattr(sheet,"plot_type_picker",None)
    if picker:
        picker.setEnabled(True)


def samples(owner, ref):
    from tailor.plot_model import PlotModel

    sheet, meta = column_info(owner, ref)
    x, xkey = sheet.processing_controls.x_values(sheet, ref[1], allow_category=True)
    if xkey is None:
        # Display-only row numbers; no invented source column is written.
        y = (
            pd.to_numeric(
                sheet.model.data_model.get_column(ref[1]), errors="coerce"
            ).to_numpy()
            if isinstance(sheet.model.data_model.get_column(ref[1]), pd.Series)
            else np.asarray(
                pd.to_numeric(
                    sheet.model.data_model.get_column(ref[1]), errors="coerce"
                )
            )
        )
        good = np.isfinite(x) & np.isfinite(y)
        return x[good], y[good], np.zeros(good.sum()), str(meta["name"]), None, []
    keys = list(sheet.model.columnLabels())
    i = keys.index(ref[1])
    error_key = (
        keys[i + 1]
        if i + 1 < len(keys) and sheet.model.column_metadata(i + 1)["role"] == "YErr"
        else None
    )
    model = PlotModel(sheet.model.data_model, xkey, ref[1], y_err_col=error_key)
    frame = model._get_data_as_dataframe()
    labels = model._axis_categories.get("x", [])
    return (
        frame.x.to_numpy(),
        frame.y.to_numpy(),
        frame.y_err.to_numpy(),
        str(meta["name"]),
        model,
        labels,
    )


def percent_values(values):
    """Normalize positive/negative stacks in float without integer overflow."""
    values=np.asarray(values,dtype=float)
    scale=np.max(np.abs(values),axis=0)
    scaled=np.divide(values,scale,out=np.zeros_like(values),where=scale>0)
    denominator=np.where(scaled>=0,np.maximum(scaled,0).sum(axis=0),np.maximum(-scaled,0).sum(axis=0))
    return np.divide(100*scaled,denominator,out=np.zeros_like(scaled),where=denominator>0)


def restrict_advanced(plot):
    """Keep inspectable pages; disable operations unsupported by advanced plots."""
    for i in range(plot.property_tabs.count()):
        if plot.property_tabs.tabText(i)=='拟合':
            plot.property_tabs.setTabEnabled(i,True)
            plot.property_tabs.widget(i).setEnabled(False)
    graph=plot.preferences.graph
    for section in graph.sections:
        if section[1].property('sectionTitle')=='局部放大':section[3].setEnabled(False)
    if hasattr(plot,'quick_actions'):plot.quick_actions.buttons['inset'].setEnabled(False)


def install_view(plot, cfg, *, deferred=False, restoring=False):
    from tailor.panel_layout import ensure_advanced_controls
    controls=ensure_advanced_controls(plot)
    view = getattr(plot, "advanced_view", None)
    if view is not None:
        view.cfg = cfg
        view.deferred_documents = deferred
        view.schedule(True)
    else:
        plot.advanced_view = AdvancedView(plot, cfg, deferred=deferred)
    plot.advanced_view._restore_initial_view=restoring
    if controls is not None:
        controls.load(cfg)
        tabs = plot.property_tabs
        tabs.setTabVisible(tabs.indexOf(controls), True)
    restrict_advanced(plot)
    return plot.advanced_view


class AdvancedView(QtCore.QObject):
    def __init__(self, plot, cfg, *, deferred=False):
        super().__init__(plot)
        self.plot, self.cfg = plot, cfg
        self.deferred_documents = deferred
        self.initializing = deferred
        self._transition_token=getattr(plot,'_advanced_notice_token',('advanced',id(self)))
        self.canvas = None
        self.native = None
        self.last_error = None
        self.items = []
        self.rendering = False
        self.data_epoch = 0
        self.reset = True
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.render)
        plot.data_refreshed.connect(self.schedule)
        self.connections = []
        from tailor.app_preferences import preferences
        self._preferences_connection = preferences().changed.connect(self.preferences_changed)
        for sheet in sheets(plot.main_window).values():
            for signal in (sheet.model.dataChanged, sheet.model.modelReset):
                signal.connect(self.source_changed)
                self.connections.append(signal)
        from tailor.appearance import manager

        manager().changed.connect(self.theme_changed)
        self.dark = manager().dark(True)
        plot.installEventFilter(self)
        self.schedule(True)

    def eventFilter(self, obj, event):
        if obj is self.plot and event.type() == QtCore.QEvent.Show:
            QtCore.QTimer.singleShot(0, self, self.schedule)
        return False

    def theme_changed(self):
        from tailor.appearance import manager

        dark = manager().dark(True)
        if dark != self.dark:
            self.dark = dark
            if self.native:
                for doc in [
                    *self.native.sources.values(),
                    *self.native.panels.values(),
                ]:
                    manager().apply_document(doc, force=True)
                self.native.place()
            self.schedule()

    def begin_transition(self,text='正在更新高级图形…'):
        notice=getattr(self.plot.main_window,'_notice',None)
        if notice:notice.begin(self._transition_token,text,priority=True)

    def preferences_changed(self, key):
        if key.startswith('performance/') and not getattr(self.plot, '_graph_disposed', False):
            if self.visible(): self.begin_transition()
            self.schedule()

    def finish_transition(self):
        notice=getattr(self.plot.main_window,'_notice',None)
        if notice:notice.finish(self._transition_token)

    def source_changed(self, *args):
        self.data_epoch += 1
        self.schedule(True)

    def visible(self):
        mode = getattr(self.plot.main_window, "window_mode", None)
        win = mode.windows.get(self.plot) if mode and mode.enabled else None
        return self.plot.isVisible() or bool(win and win.isVisible())

    def schedule(self, reset=False, *args):
        if getattr(self.plot, "_graph_disposed", False):
            return
        if self.rendering:
            self._render_again=True
            self._render_again_reset=getattr(self,'_render_again_reset',False) or reset is True
            return
        if isinstance(reset, bool):
            self.reset = self.reset or reset
        if not self.visible() and not self.initializing:
            self.pending = True
            self.finish_transition()
            return
        self.pending = False
        large=any(sheets(self.plot.main_window).get(ref[0]) is not None and
                  sheets(self.plot.main_window)[ref[0]].model.rowCount()>10_000
                  for ref in self.cfg.get('refs',[]) if ref)
        if self.reset or self.initializing or large:self.begin_transition()
        from tailor.app_preferences import preferences
        state = preferences()
        delay = state.get('performance/debounce') if state.get('performance/mode') == 'responsive' else 35
        self.timer.start(delay)

    def switch_canvas(self, kind):
        if getattr(self, "canvas_kind", None) == kind:
            return
        self.clear_items()
        old = self.canvas
        if old is not None:
            self.plot.ui.plot_widget.parentWidget().layout().removeWidget(old)
            old.hide()
            old.deleteLater()
        self.canvas = None
        self.plot.ui.plot_widget.setVisible(kind == "bar")
        if kind == "panels":
            self.canvas = pg.GraphicsLayoutWidget()
            self.canvas.ci.layout.setContentsMargins(20, 18, 28, 38)
        elif kind == "3d":
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
            from matplotlib.figure import Figure

            self.figure = Figure()
            self.figure.subplots_adjust(left=0.03, right=0.86, bottom=0.09, top=0.97)
            self.canvas = FigureCanvasQTAgg(self.figure)
            self.canvas.mpl_connect("button_release_event", self.view_changed)
            self.canvas.mpl_connect("pick_event", self.pick_three_d)
        if self.canvas is not None:
            self.plot.ui.plot_widget.parentWidget().layout().insertWidget(
                0, self.canvas, 1
            )
            self.canvas.show()
        self.canvas_kind = kind
        self.reset = True

    def clear_items(self):
        for item in self.items:
            self.plot.ui.plot_widget.removeItem(item)
        self.items = []

    def render(self):
        if getattr(self.plot,'_graph_disposed',False):
            self.timer.stop();self.finish_transition();return
        if self.rendering:return
        # An explicit refresh/export supersedes the queued timer update.
        self.timer.stop()
        if not self.visible() and not self.initializing and not getattr(self, "exporting", False):
            self.pending = True
            self.finish_transition()
            return
        if self.rendering or getattr(self.plot, "_graph_disposed", False):
            return
        self.rendering = True
        self.last_error = None
        # Restoring a saved view is not a user request for Default View.
        if getattr(self,'_restore_initial_view',False):self.reset=False
        try:
            if self.cfg["kind"] in {"bar", "panels"}:
                from tailor.native_panels import NativePanels

                if self.native is None:
                    self.native = NativePanels(self)
                    self.plot.advanced_controls.refresh_panel_layout()
                    self.plot.ui.plot_widget.hide()
                    self.canvas = self.native.canvas
                    self.plot.ui.plot_widget.parentWidget().layout().insertWidget(
                        0, self.canvas, 1
                    )
                    self.canvas.show()
                    self.begin_transition()
                else:
                    self.native.cfg = self.cfg
                    self.native.reconcile()
                if self.native.initializing:
                    return
                if self.cfg["kind"] == "bar":
                    self.native_bars()
                self.panel_items = [
                    doc.ui.plot_widget.getPlotItem()
                    for doc in self.native.panels.values()
                ]
                if self.reset:
                    self.native.reset()
            else:
                self.switch_canvas("3d")
                self.three_d()
                self.initializing = False
            self.reset = False
            self._restore_initial_view=False
            if hasattr(self.plot, "advanced_controls"):
                self.plot.advanced_controls.message.setText(
                    f"原始 {self.source_count:,} 点 · 显示 {self.display_count:,} 点；显示密度可调，源数据保留。"
                    if self.cfg["kind"] == "3d"
                    else "已绘制；数据仍关联原工作表。"
                )
        except (ValueError, KeyError, TypeError, RuntimeError) as error:
            self.initializing=False
            self.last_error = str(error)
            if hasattr(self.plot, "advanced_controls"):
                self.plot.advanced_controls.message.setText("未绘制：" + str(error))
            self.plot.main_window.statusBar().showMessage("高级绘图：" + str(error))
        finally:
            self.rendering = False
            if getattr(self,'_render_again',False):
                reset=getattr(self,'_render_again_reset',False)
                self._render_again=self._render_again_reset=False
                self.schedule(reset)
            elif not self.initializing:self.finish_transition()

    def style(self, index):
        from tailor.curve_style import CurveStyle

        spec = self.cfg.get("styles", {}).get(str(index))
        if spec:
            return CurveStyle(**spec)
        from dataclasses import replace

        return replace(
            self.plot.curve_style,
            color=COLORS[index % len(COLORS)] if index else self.plot.curve_style.color,
        )

    def native_bars(self):
        self.native.bars()

    def bars(self):
        from tailor.line_styles import curve_pen

        old_range = self.plot.ui.plot_widget.viewRange()
        self.clear_items()
        plotitem = self.plot.ui.plot_widget.getPlotItem()
        self.plot.plot.hide()
        self.plot.fit_plot.hide()
        self.plot.initial_param_plot.hide()
        self.plot.error_items.x.hide()
        self.plot.error_items.y.hide()
        legend = self.plot.presentation.legend_item
        legend.clear()
        from tailor.text_style_controls import font_spec

        legend.setLabelTextSize(
            str(font_spec(self.plot.curve_style, "legend")["size"]) + "pt"
        )
        data = [samples(self.plot.main_window, ref) for ref in self.cfg["refs"]]
        if not data:
            raise ValueError("请选择Y列。")
        x = data[0][0]
        if any(not np.array_equal(values[0], x) for values in data):
            raise ValueError("柱状图的各列X须相同；请先对齐数据。")
        width = float(self.cfg.get("width", 0.8))
        step = np.diff(np.unique(x))
        width *= float(np.median(step[step > 0])) if np.any(step > 0) else 1
        mode = self.cfg.get("bar_mode", "grouped")
        horizontal = self.cfg.get("horizontal", False)
        yy = np.stack([d[1] for d in data])
        if mode == "percent":
            yy = percent_values(yy)
        top, bottom = np.zeros(len(x)), np.zeros(len(x))
        for index, values in enumerate(data):
            style = self.style(index)
            if not style.visible:
                continue
            y = yy[index]
            if mode == "grouped":
                span = width / len(data)
                position = x - width / 2 + span * (index + 0.5)
                base = np.zeros(len(x))
            else:
                span, position = width, x
                base = np.where(y >= 0, top, bottom).copy()
                top += np.where(y >= 0, y, 0)
                bottom += np.where(y < 0, y, 0)
            brush = pg.mkColor(style.color)
            brush.setAlphaF(style.opacity)
            pen = curve_pen(style.color, style.line_width, style.line_style)
            params = (
                {"y": position, "height": span, "x0": base, "width": y}
                if horizontal
                else {"x": position, "width": span, "y0": base, "height": y}
            )
            bar = pg.BarGraphItem(**params, pen=pen, brush=brush)
            plotitem.addItem(bar)
            self.items.append(bar)
            legend.addItem(bar, values[3])
            if (
                self.cfg.get("errors", True)
                and mode != "percent"
                and np.any(values[2] > 0)
            ):
                error = values[2]
                opts = (
                    {"x": base + y, "y": position, "left": error, "right": error}
                    if horizontal
                    else {"x": position, "y": base + y, "top": error, "bottom": error}
                )
                item = pg.ErrorBarItem(**opts, beam=span / 3, pen=pen)
                plotitem.addItem(item)
                self.items.append(item)
        self.style_legends([legend])
        legend.setVisible(self.plot.presentation.legend["visible"])
        if data[0][5]:
            labels = list(enumerate(data[0][5], 1))
            plotitem.getAxis("left" if horizontal else "bottom").setTicks([labels])
        if horizontal:
            plotitem.setLabel(
                "bottom",
                "百分比（%）" if mode == "percent" else self.plot.model.y_label,
            )
            plotitem.setLabel("left", self.plot.model.x_label)
        elif mode == "percent":
            plotitem.setLabel("left", "百分比（%）")
        if self.reset:
            plotitem.vb.autoRange(padding=0.06)
        else:
            plotitem.vb.setRange(xRange=old_range[0], yRange=old_range[1], padding=0)

    def style_legends(self, legends):
        from tailor.text_style_controls import font_spec, styled_html

        spec = font_spec(self.plot.curve_style, "legend")
        for legend in legends:
            for _sample, label in legend.items:
                label.setText(styled_html(label.text, spec))

    def panels(self):
        from tailor.graph_presentation import NumberAxis
        from tailor.line_styles import curve_pen
        from tailor.text_style_controls import font_spec

        prior = [item.viewRange() for item in getattr(self, "panel_items", [])]
        self.canvas.clear()
        self.canvas.setBackground("#000000" if self.dark else "#ffffff")
        refs = self.cfg["refs"]
        cols = max(1, int(self.cfg.get("columns", 2)))
        rows = max(int(self.cfg.get("rows", 1)), math.ceil(len(refs) / cols))
        self.cfg["rows"] = rows
        legend = pg.LegendItem(offset=None)
        unified = self.cfg.get("unified_legend", True)
        legend.setLabelTextSize(
            str(font_spec(self.plot.curve_style, "legend")["size"]) + "pt"
        )
        if unified:
            self.canvas.ci.addItem(legend, row=0, col=0, colspan=cols)
        self.panel_items = []
        self._syncing_panels = True
        data_bounds = [[], []]
        ink = "#eeeeee" if self.dark else "#202020"
        for index, ref in enumerate(refs):
            x, y, error, name, _model, labels = samples(self.plot.main_window, ref)
            from tailor.graph_presentation import display

            for dim, values, key in (
                (0, x, "x"),
                (1, np.r_[y - error, y + error], "y"),
            ):
                values = display(values, self.plot.presentation.axes[key])
                good = values[np.isfinite(values)]
                if len(good):
                    data_bounds[dim].extend([float(good.min()), float(good.max())])
            rownum, col = divmod(index, cols)
            axes = {
                side: NumberAxis(side, copy.deepcopy(self.plot.presentation.axes[key]))
                for side, key in [("bottom", "x"), ("left", "y")]
            }
            if labels:
                axes["bottom"].settings.update(
                    axis_type="category", category_labels=labels
                )
            item = self.canvas.addPlot(
                row=rownum + int(unified), col=col, axisItems=axes
            )
            self.panel_items.append(item)
            style = self.style(index)
            from tailor.plot_types import geometry

            gx, gy = geometry(x, y, style.mode)
            curve = item.plot(
                gx,
                gy,
                pen=None
                if style.mode == "scatter"
                else curve_pen(style.color, style.line_width, style.line_style),
                symbol=style.marker
                if style.mode in {"scatter", "line_scatter"}
                else None,
                symbolSize=style.marker_size,
                symbolPen=style.color,
                symbolBrush=style.color,
                connect="finite",
            )
            from tailor.line_styles import apply_curve_extras

            apply_curve_extras(curve, style)
            curve.setVisible(style.visible)
            curve.setLogMode(
                self.plot.presentation.axes["x"]["log"],
                self.plot.presentation.axes["y"]["log"],
            )
            if np.any(error > 0) and not any(
                self.plot.presentation.axes[k]["log"] for k in ("x", "y")
            ):
                item.addItem(
                    pg.ErrorBarItem(x=x, y=y, top=error, bottom=error, pen=style.color)
                )
            if unified:
                legend.addItem(curve, name)
            else:
                item.addLegend().addItem(curve, name)
            if self.cfg.get("numbering", True):
                item.setTitle(
                    f"({chr(97 + index) if index < 26 else index + 1}) {name}",
                    color=ink,
                )
            item.setLabel("bottom", self.plot.model.x_label)
            first_name = column_info(self.plot.main_window, refs[0])[1]["name"]
            item.setLabel(
                "left",
                self.plot.model.y_label
                if self.plot.model.y_label != first_name
                else name,
            )
            for side, key in [("bottom", "x"), ("left", "y")]:
                axis = item.getAxis(side)
                spec = font_spec(self.plot.curve_style, key + "_ticks")
                font = QtGui.QFont(spec["family"])
                font.setPointSizeF(spec["size"])
                font.setBold(spec["bold"])
                font.setItalic(spec["italic"])
                axis.setStyle(tickFont=font)
                axis.setPen(ink)
                axis.setTextPen(ink)
                title = font_spec(self.plot.curve_style, key + "_label")
                from tailor.text_style_controls import styled_html

                axis.label.setHtml(styled_html(axis.label.toPlainText(), title))
                item.showGrid(
                    x=self.plot.presentation.axes["x"]["grid"],
                    y=self.plot.presentation.axes["y"]["grid"],
                    alpha=0.2,
                )
            if self.cfg.get("share_x"):
                item.sigXRangeChanged.connect(
                    lambda source, limits: self.link_panel_range(source, limits, 0)
                )
            if self.cfg.get("share_y"):
                item.sigYRangeChanged.connect(
                    lambda source, limits: self.link_panel_range(source, limits, 1)
                )
            if not self.reset and index < len(prior):
                item.setRange(xRange=prior[index][0], yRange=prior[index][1], padding=0)
        self._syncing_panels = False
        self.style_legends(
            [legend] if unified else [item.legend for item in self.panel_items]
        )
        if self.reset and self.panel_items:
            for dim, key in [(0, "share_x"), (1, "share_y")]:
                if self.cfg.get(key):
                    bounds = data_bounds[dim]
                    if bounds:
                        low, high = min(bounds), max(bounds)
                        pad = max((high - low) * 0.06, abs(low) * 0.01, 1e-9)
                        (
                            self.panel_items[0].setXRange
                            if dim == 0
                            else self.panel_items[0].setYRange
                        )(low - pad, high + pad, padding=0)

        if not self.reset and prior and self.panel_items:
            for dim, key in ((0, "share_x"), (1, "share_y")):
                if self.cfg.get(key):
                    self.link_panel_range(None, prior[0][dim], dim)

    def link_panel_range(self, source, limits, dimension):
        # Native numeric ranges linked by signals, independent of screen alignment.
        # ViewBox.setYLink aligns scene pixels, which shifts ranges when the scene
        # layout is reconstructed or font metrics change. These panels need equal
        # numeric ranges even when their label margins have different geometry.
        if getattr(self, "_syncing_panels", False):
            return
        self._syncing_panels = True
        try:
            for item in self.panel_items:
                box = item.getViewBox()
                if box is not source:
                    (box.setXRange if dimension == 0 else box.setYRange)(
                        *limits, padding=0
                    )
        finally:
            self._syncing_panels = False

    def three_state(self):
        """Native artists can survive camera-only edits; data/style edits cannot."""
        cfg=copy.deepcopy(self.cfg)
        cfg.pop('azimuth',None);cfg.pop('elevation',None)
        presentation=self.plot.presentation.to_dict()
        presentation.get('extra_settings',{}).pop('advanced',None)
        from tailor.app_preferences import advanced_limit
        return (self.data_epoch,cfg,presentation,copy.deepcopy(self.plot.curve_style),
                self.plot.model.x_label,self.plot.model.y_label,self.plot.model.legend_label,
                tuple(getattr(self.plot.model,k) for k in ('x_min','x_max','y_min','y_max')),
                tuple(label.text for _,label in self.plot.presentation.legend_item.items),
                self.dark,bool(getattr(self,'exporting',False)),
                advanced_limit(int(self.cfg.get('display_limit',20000)),getattr(self,'exporting',False)))

    def three_d(self):
        from dataclasses import replace

        from matplotlib.font_manager import FontProperties

        from tailor.appearance import ink as text_ink
        from tailor.text_style_controls import font_spec

        if (not self.reset and hasattr(self,'ax') and
                getattr(self,'_three_state',None)==self.three_state()):
            self.ax.view_init(elev=self.cfg.get('elevation',30),azim=self.cfg.get('azimuth',-60))
            self.canvas.draw_idle()
            return
        refs = self.cfg["xyz"]
        token = (tuple(tuple(r) for r in refs), self.data_epoch)
        if getattr(self, "_xyz_token", None) != token:
            self._xyz_arrays = [
                np.asarray(
                    pd.to_numeric(
                        column_info(self.plot.main_window, ref)[
                            0
                        ].model.data_model.get_column(ref[1]),
                        errors="coerce",
                    ),
                    dtype=float,
                )
                for ref in refs
            ]
            self._xyz_token = token
        arrays = self._xyz_arrays
        if len({len(a) for a in arrays}) != 1:
            raise ValueError("XYZ列须同表且逐行对应。")
        good = np.all(np.isfinite(arrays), axis=0)
        source_indices = np.flatnonzero(good)
        x, y, z = [a[good] for a in arrays]
        if not len(x):
            raise ValueError("XYZ没有同行有效数值。")
        self.source_count = len(x)
        limit = int(self.cfg.get("display_limit", 20000))
        from tailor.app_preferences import advanced_limit
        limit = advanced_limit(limit, getattr(self, 'exporting', False))
        if len(x) > limit:
            keep = np.unique(
                np.r_[
                    np.linspace(0, len(x) - 1, limit, dtype=int),
                    *[np.array([np.argmin(a), np.argmax(a)]) for a in (x, y, z)],
                ]
            )
            x, y, z = x[keep], y[keep], z[keep]
            source_indices = source_indices[keep]
        self._three_source_indices = source_indices
        self.display_count = len(x)
        from tailor.three_controls import colormap
        palette=colormap(self.cfg)
        self.figure.clear()
        self.ax = self.figure.add_subplot(projection="3d")
        style = self.plot.curve_style
        color = "#eeeeee" if self.dark and style.color == "#202020" else style.color
        mode = self.cfg.get("three_mode", "scatter")
        if mode == "scatter":
            artist = self.ax.scatter(
                x,
                y,
                z,
                c=z if self.cfg.get("colorbar", True) else color,
                cmap=palette if self.cfg.get("colorbar",True) else None,
                s=style.marker_size**2,
                marker={
                    "o": "o",
                    "s": "s",
                    "t": "^",
                    "t1": "v",
                    "t2": ">",
                    "t3": "<",
                    "d": "D",
                    "+": "+",
                    "x": "x",
                    "star": "*",
                }.get(style.marker, "o"),
                alpha=style.opacity,
            )
        elif mode == "line":
            # Retain missing-observation gaps even after display sampling.
            # Matplotlib's native NaN handling breaks the path, without adding
            # invented source values or connecting across an unobserved span.
            coordinates=[x,y,z]
            if not good.all():
                missing_before=np.cumsum(~good)
                gaps=np.flatnonzero(np.diff(missing_before[source_indices])>0)+1
                coordinates=[np.insert(values,gaps,np.nan) for values in coordinates]
            (artist,) = self.ax.plot(
                *coordinates,
                color=color,
                linewidth=style.line_width,
                alpha=style.opacity,
                linestyle=replace(style, mode="line").mpl_options()["linestyle"],
            )
        else:
            if len(x) < 3 or len(np.unique(np.column_stack((x, y)), axis=0)) != len(x):
                raise ValueError(
                    "曲面/线框需要至少3个互异XY位置；重复位置请先整理或改用散点。"
                )
            if mode == "wire":
                from matplotlib.tri import Triangulation
                from mpl_toolkits.mplot3d.art3d import Line3DCollection

                triangles = Triangulation(x, y).triangles
                edges = np.unique(
                    np.sort(
                        np.vstack(
                            [
                                triangles[:, [0, 1]],
                                triangles[:, [1, 2]],
                                triangles[:, [2, 0]],
                            ]
                        ),
                        axis=1,
                    ),
                    axis=0,
                )
                vertices = np.column_stack((x, y, z))
                artist = Line3DCollection(
                    vertices[edges],
                    colors=color,
                    linewidths=style.line_width,
                    alpha=style.opacity,
                )
                self.ax.add_collection3d(artist)
                self.ax.auto_scale_xyz(x, y, z)
            else:
                artist = self.ax.plot_trisurf(
                    x,
                    y,
                    z,
                    cmap=palette,
                    alpha=style.opacity,
                    edgecolor="none",
                )
        if mode in {"surface", "scatter"}:
            from matplotlib import colormaps

            artist.set_cmap(
                palette.resampled(
                    int(self.cfg.get("levels", 64))
                )
            )
        ink, background = (
            ("#eeeeee", "#000000") if self.dark else ("#202020", "#ffffff")
        )
        self.figure.set_facecolor(background)
        self.ax.set_facecolor(background)
        titles = [
            self.plot.model.x_label,
            self.plot.model.y_label,
            self.plot.presentation.right_label,
        ]
        for axis, title, key in zip(
            (self.ax.xaxis, self.ax.yaxis, self.ax.zaxis), titles, ("x", "y", "right")
        ):
            axis.labelpad = 8
            spec = font_spec(style, key + "_label")
            family = [spec["family"], "PingFang SC", "DejaVu Sans"]
            axis.set_label_text(
                QtGui.QTextDocumentFragment.fromHtml(title).toPlainText(),
                color=text_ink(spec["color"]),
                fontproperties=FontProperties(
                    family=family,
                    size=spec["size"],
                    weight="bold" if spec["bold"] else "normal",
                    style="italic" if spec["italic"] else "normal",
                ),
            )
            tick = font_spec(style, key + "_ticks")
            for label in axis.get_ticklabels():
                label.set_fontproperties(
                    FontProperties(
                        family=[tick["family"], "PingFang SC", "DejaVu Sans"],
                        size=tick["size"],
                        weight="bold" if tick["bold"] else "normal",
                        style="italic" if tick["italic"] else "normal",
                    )
                )
                label.set_color(text_ink(tick["color"]))
            axis.line.set_color(ink)
            axis.set_pane_color((*pg.mkColor(background).getRgbF()[:3], 1))
        self.ax.tick_params(color=ink)
        self.ax.set_proj_type(self.cfg.get("projection", "persp"))
        self.ax.view_init(
            elev=self.cfg.get("elevation", 30), azim=self.cfg.get("azimuth", -60)
        )
        from tailor.three_d_axes import apply, apply_colorbar

        apply(self)
        artist.set_picker(True)
        self.three_artist = artist
        if self.cfg.get("colorbar", True) and mode in {"surface", "scatter"}:
            limits = (self.plot.presentation.top_min, self.plot.presentation.top_max)
            if limits[0] is not None or limits[1] is not None:
                low = limits[0] if limits[0] is not None else float(z.min())
                high = limits[1] if limits[1] is not None else float(z.max())
                if low >= high:
                    raise ValueError("色标最小值须小于最大值。")
                artist.set_clim(low, high)
            bar = self.figure.colorbar(artist, ax=self.ax, shrink=0.65, pad=0.1)
            apply_colorbar(self, bar)
            self.color_bar = bar
        self.render_three_legend()
        self.canvas.draw_idle()
        domains=getattr(self.plot.axis_controls,"parameter_domains",None)
        if domains is not None:domains.refresh_range()
        self._three_state=self.three_state()

    def render_three_legend(self):
        from matplotlib.font_manager import FontProperties
        from matplotlib.lines import Line2D

        from tailor.appearance import ink
        from tailor.text_style_controls import font_spec

        p = self.plot.presentation
        self.three_legend_keys = []
        if not p.legend.get("visible", True):
            return
        handles, names = [], []
        for sample, label in p.legend_item.items:
            item = sample.item
            key = getattr(item, "_legend_key", "data")
            if key in p.legend.get("hidden_entries", []):
                continue
            spec = p.legend.get("samples", {}).get(key, {})
            style = self.plot.curve_style
            handles.append(
                Line2D(
                    [],
                    [],
                    color=ink(spec.get("color", style.color)),
                    linewidth=spec.get("line_width", style.line_width),
                    linestyle={
                        "solid": "-",
                        "dash": "--",
                        "dot": ":",
                        "dashdot": "-.",
                    }.get(spec.get("line_style", style.line_style), "-"),
                    marker=spec.get("marker", style.marker)
                    if self.cfg.get("three_mode") == "scatter"
                    else None,
                )
            )
            names.append(__import__('tailor.text_layout',fromlist=['mpl_text']).mpl_text(label.text))
            self.three_legend_keys.append(key)
        if not names:
            return
        position = p.legend.get("position")
        legend = self.ax.legend(
            handles,
            names,
            loc="upper right" if position is None else "upper left",
            bbox_to_anchor=None if position is None else (position[0], 1 - position[1]),
            frameon=p.legend.get("border", False) or p.legend.get("background", False),
            labelspacing=max(0, p.legend.get("spacing", 2)) / 10,
            ncol=p.legend.get("columns", 1),
        )
        border = p.legend.get("border_style", {})
        bg = p.legend.get("background_style", {})
        frame = legend.get_frame()
        frame.set_edgecolor(
            ink(border.get("color", "#888888")) if p.legend.get("border") else "none"
        )
        frame.set_linewidth(border.get("line_width", 1))
        frame.set_facecolor(
            bg.get("color", "#ffffff") if p.legend.get("background") else "none"
        )
        frame.set_alpha(bg.get("opacity", 1))
        for key, text in zip(self.three_legend_keys, legend.get_texts()):
            spec = {
                **font_spec(self.plot.curve_style, "legend"),
                **p.legend.get("entries", {}).get(key, {}).get("style", {}),
            }
            text.set_fontproperties(
                FontProperties(
                    family=[spec["family"], "PingFang SC", "DejaVu Sans"],
                    size=spec["size"],
                    weight="bold" if spec["bold"] else "normal",
                    style="italic" if spec["italic"] else "normal",
                )
            )
            text.set_color(ink(spec["color"]))
            text.set_picker(True)
        self.three_legend = legend

    def close(self):
        self.finish_transition()
        QtCore.QObject.disconnect(self._preferences_connection)
        self.timer.stop()
        if self.native:
            self.native.close()
        try:
            self.plot.data_refreshed.disconnect(self.schedule)
        except (RuntimeError, TypeError):
            pass
        for signal in self.connections:
            try:
                signal.disconnect(self.source_changed)
            except (RuntimeError, TypeError):
                pass
        from tailor.appearance import manager

        try:
            manager().changed.disconnect(self.theme_changed)
        except (RuntimeError, TypeError):
            pass
        if self.canvas is not None:
            self.canvas.close()

    def pick_three_d(self, event):
        from tailor.text_style_controls import reveal_section

        artist = event.artist
        legend = getattr(self, "three_legend", None)
        if legend is not None and artist in legend.get_texts():
            index = legend.get_texts().index(artist)
            self.plot.legend_controls.select_entry(self.three_legend_keys[index])
            reveal_section(self.plot, self.plot.preferences.graph, "图例")
            if event.mouseevent.dblclick:
                self.plot.preferences.open_font(self.plot.legend_controls.editor)
            return
        for key, axis in (
            ("x", self.ax.xaxis),
            ("y", self.ax.yaxis),
            ("right", self.ax.zaxis),
        ):
            if artist is axis.label or artist in axis.get_ticklabels():
                kind = "label" if artist is axis.label else "ticks"
                if kind=='ticks':
                    labels=axis.get_ticklabels();index=labels.index(artist);values=axis.get_majorticklocs()
                    if index<len(values):self.plot.axis_controls.selected_tick=(key,float(values[index]),artist.get_text())
                self.plot.axis_controls.select_axis(key, kind)
                reveal_section(
                    self.plot,
                    self.plot.axis_controls,
                    "标题与轴线" if kind == "label" else "刻度文字格式",
                )
                artist.set_bbox({"edgecolor": "#348ad5", "facecolor": "none", "pad": 2})
                if event.mouseevent.dblclick:
                    self.plot.axis_controls.open_font(kind)
                self.canvas.draw_idle()
                return
        if artist is getattr(self, "three_artist", None):
            self.plot.preferences.select_curve(
                "data", self.plot, event.mouseevent.dblclick
            )

    def view_changed(self, event):
        if self.cfg.get("kind") == "3d" and hasattr(self, "ax"):
            self.cfg.update(elevation=float(self.ax.elev), azimuth=float(self.ax.azim))
            controls=getattr(self.plot,'advanced_controls',None)
            if controls is not None:
                for key in ('azimuth','elevation'):
                    field=getattr(controls,key)
                    with QtCore.QSignalBlocker(field):field.setValue(self.cfg[key])
                if hasattr(controls,'view_parameters'):controls.view_parameters.sync()
            self.plot.main_window.mark_project_dirty()

    def export(self, filename, dpi):
        self.exporting = True
        try:
            self.render()
        finally:
            self.exporting = False
        if self.last_error:
            raise ValueError(self.last_error)
        if self.cfg["kind"] != "3d":
            from tailor.canvas_export import export_canvas

            return export_canvas(self.plot, filename, dpi, view_override=self.canvas)
        path = Path(filename)
        from tailor.app_preferences import export_options
        dpi, background_mode = export_options(dpi)
        fd, temporary = tempfile.mkstemp(
            prefix="." + path.stem, suffix=path.suffix, dir=path.parent
        )
        os.close(fd)
        try:
            self.figure.savefig(
                temporary, dpi=dpi,
                transparent=background_mode == 'transparent' or (background_mode == 'graph' and self.plot.curve_style.transparent),
                facecolor=self.figure.get_facecolor()
            )
            os.replace(temporary, path)
        finally:
            if Path(temporary).exists():
                Path(temporary).unlink()
            from tailor.app_preferences import preferences
            if preferences().get('performance/mode') == 'responsive':
                self.schedule()


class AdvancedControls(FoldPanel):
    def __init__(self, document):
        super().__init__(document)
        self.document, self.owner = document, document.main_window
        self.plot = document if hasattr(document, "presentation") else None
        self.loading = False
        self.kind = combo(KINDS)
        self.objects = QtWidgets.QToolButton()
        self.objects.setProperty("choiceField", True)
        self.objects.setText("选择Y列")
        self.objects.setMinimumWidth(80)
        self.objects.setFixedHeight(30)
        self.objects.setSizePolicy(
            QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed
        )
        self.objects.setStyleSheet("QToolButton {padding-right: 28px;}")
        self.objects.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        from tailor.processing_controls import ColumnMenu

        self.object_menu = ColumnMenu(self.objects)
        self.objects.setMenu(self.object_menu)
        self.object_menu.aboutToShow.connect(self.fill_objects)
        self.refs = []
        if not self.plot:
            document.ui.data_view.selectionModel().selectionChanged.connect(
                self.follow_selection
            )
        self.order = QtWidgets.QListWidget()
        self.order.setMaximumHeight(90)
        self.order.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.order.model().rowsMoved.connect(self.order_changed)
        up, down = QtWidgets.QPushButton("上移"), QtWidgets.QPushButton("下移")
        up.clicked.connect(lambda: self.move(-1))
        down.clicked.connect(lambda: self.move(1))
        source = QtWidgets.QVBoxLayout()
        source.addWidget(row("绘图类型", self.kind))
        self.object_row = row("对象", self.objects)
        self.order_row = row(up, down)
        source.addWidget(self.object_row)
        source.addWidget(self.order)
        source.addWidget(self.order_row)
        self.exit_button = QtWidgets.QPushButton("退出高级模式")
        self.exit_button.clicked.connect(self.exit_mode)
        source.addWidget(self.exit_button)
        self.add_section("高级绘图", source, True)
        self.bar_mode = combo(
            [("分组", "grouped"), ("堆叠", "stacked"), ("百分比堆叠", "percent")]
        )
        self.horizontal = toggle_button("横向柱状图")
        self.width = number(0.1, 1, 0.8, 2)
        self.errors = toggle_button("显示误差棒")
        self.errors.setChecked(True)
        form = QtWidgets.QVBoxLayout()
        form.addWidget(row("排列方式", self.bar_mode))
        form.addWidget(row("柱宽比例", self.width))
        form.addWidget(row(self.horizontal, self.errors))
        self.add_section("柱状图设置", form, True)
        self.three_mode = combo(
            [
                ("XYZ散点", "scatter"),
                ("三维折线", "line"),
                ("曲面", "surface"),
                ("线框", "wire"),
            ]
        )
        self.xyz = [QtWidgets.QComboBox() for _ in range(3)]
        self.cmap = combo(
            [
                ("蓝绿黄", "viridis"),
                ("暖色", "plasma"),
                ("冷暖", "coolwarm"),
                ("灰度", "gray"),
                ("自定义", "custom"),
            ]
        )
        self.colorbar = toggle_button("显示色标")
        self.colorbar.setChecked(True)
        self.azimuth = number(-180, 180, -60, 1,unit="°")
        self.elevation = number(-90, 90, 30, 1,unit="°")
        self.projection = combo([("透视", "persp"), ("正交", "ortho")])
        form = QtWidgets.QVBoxLayout()
        form.addWidget(row("绘制方式", self.three_mode))
        for name, box in zip(("X列", "Y列", "Z列"), self.xyz):
            form.addWidget(row(name, box))
            box.activated.connect(self.sync_target_actions)
        form.addWidget(row("配色", self.cmap))
        form.addWidget(self.colorbar)
        form.addWidget(row("方位角", self.azimuth))
        form.addWidget(row("仰角", self.elevation))
        form.addWidget(row("投影方式", self.projection))
        self.levels = number(2, 256, 64, 0,unit="级")
        self.levels.setSingleStep(1)
        form.addWidget(row("色阶数量", self.levels))
        self.display_limit = number(1000, 200000, 20000, 0,unit="点")
        form.addWidget(row("显示点上限", self.display_limit))
        self.display_limit.setToolTip(
            "只限制交互图形的显示密度；原表与计算保留全部点，导出使用当前显示密度。为保留XYZ极值，最多额外保留6个点。"
        )
        self.add_section("三维图设置", form, True)
        self.rows = number(1, 20, 1, 0,unit="行")
        self.columns = number(1, 8, 2, 0,unit="列")
        self.share_x = toggle_button("共享X轴")
        self.share_y = toggle_button("共享Y轴")
        self.unified = toggle_button("统一图例")
        self.unified.setChecked(True)
        self.numbering = toggle_button("子图编号")
        self.numbering.setChecked(True)
        form = QtWidgets.QVBoxLayout()
        form.addWidget(row("行数", self.rows))
        form.addWidget(row("列数", self.columns))
        form.addWidget(row(self.share_x, self.share_y))
        form.addWidget(row(self.unified, self.numbering))
        self.add_section("组图设置", form, True)
        self.layout_target = QtWidgets.QComboBox()
        self.layout_slot = combo(
            [
                ("自动行列", "auto"),
                ("A · 左上", "A"),
                ("B · 右上", "B"),
                ("C · 左下", "C"),
                ("D · 右下", "D"),
                ("自定义", "custom"),
            ]
        )
        self.layout_fields = [number(0, 100, v, 2) for v in (0, 0, 50, 50)]
        for field in self.layout_fields:
            field.setSingleStep(1)
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(row("作用子图", self.layout_target))
        layout.addWidget(row("位置预设", self.layout_slot))
        for label, field in zip(
            ("水平位置", "垂直位置", "子图宽度", "子图高度"), self.layout_fields
        ):
            layout.addWidget(row(label, field, "%"))
        apply_layout = QtWidgets.QPushButton("应用大小与位置")
        apply_layout.clicked.connect(self.apply_panel_layout)
        layout.addWidget(apply_layout)
        self.layout_target.activated.connect(self.choose_layout_target)
        self.layout_slot.activated.connect(self.choose_layout_slot)
        for label, callback in (
            ("新增子图", lambda: self.manage_panel("add")),
            ("删除子图", lambda: self.manage_panel("remove")),
            ("上移子图", lambda: self.manage_panel("up")),
            ("下移子图", lambda: self.manage_panel("down")),
        ):
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(callback)
            layout.addWidget(button)
        add_curves = QtWidgets.QPushButton("将所选对象加入当前子图")
        add_curves.clicked.connect(self.add_panel_curves)
        layout.addWidget(add_curves)
        align = combo(
            [
                ("左侧对齐", "left"),
                ("顶部对齐", "top"),
                ("统一宽度", "width"),
                ("统一高度", "height"),
            ]
        )
        align_button = QtWidgets.QPushButton("应用到全部子图")
        align_button.clicked.connect(lambda: self.align_panels(align.currentData()))
        layout.addWidget(row(align, align_button))
        layout.addWidget(
            QtWidgets.QLabel(
                "位置从画布左上角起算；ABCD分别占画布四分之一，可用于两、三或四张图。"
            )
        )
        self.add_section("子图布局", layout, True)
        self.bar_gap = number(0, 0.9, 0.1, 2)
        self.bar_gap.setSingleStep(0.01)
        self.baseline = number(-1e12, 1e12, 0, 3)
        self.baseline.setSingleStep(0.1)
        # Existing bar card, with separate group width and within-group gap.
        bar_card = next(
            r[3] for r in self.sections if r[1].property("sectionTitle") == "柱状图设置"
        )
        bar_card.layout().addWidget(row("柱间距比例", self.bar_gap))
        bar_card.layout().addWidget(row("柱图基线", self.baseline))
        self.style_target = QtWidgets.QComboBox()
        self.line = preference_button("curve")
        self.font_button = preference_button("font")
        self.line.clicked.connect(self.open_line)
        self.font_button.clicked.connect(self.open_font)
        self.text_target = combo(
            [
                ('—',None),
                ("X轴标题", "x_label"),
                ("Y轴标题", "y_label"),
                ("Z轴标题", "right_label"),
                ("X轴刻度", "x_ticks"),
                ("Y轴刻度", "y_ticks"),
                ("Z轴刻度", "right_ticks"),
                ("图例", "legend"),
            ]
        )
        self.text_target.currentIndexChanged.connect(lambda *args:self.font_button.setEnabled(self.plot is not None and self.text_target.currentData() is not None))
        self.style_target.currentIndexChanged.connect(lambda *args:self.line.setEnabled(self.plot is not None and self.style_target.currentData() is not None))
        form = QtWidgets.QVBoxLayout()
        form.addWidget(row("线条对象", self.style_target, self.line))
        form.addWidget(row("文字对象", self.text_target, self.font_button))
        self.add_section("字体与线条", form, True)
        from tailor.workflow_templates import GraphTemplateControls

        self.graph_templates = GraphTemplateControls(document)
        self.add_section("图形模板", self.graph_templates)
        self.draw = QtWidgets.QPushButton("高级绘图")
        self.draw.setProperty("intent", "primary")
        self.draw.clicked.connect(lambda: self.create(deferred=True))
        self.layout().addWidget(self.draw)
        self.message = QtWidgets.QLabel("选择高级类型与数据，使用此页绘图。")
        self.message.setWordWrap(True)
        self.message.setParent(self)
        self.message.hide()
        self.kind.currentIndexChanged.connect(self.choose)
        self.three_mode.currentIndexChanged.connect(self.choose)
        self.bar_mode.currentIndexChanged.connect(self.choose)
        self.colorbar.toggled.connect(self.choose)
        self.sync_refs()
        self.choose()
        from tailor.advanced_ui import install

        install(self)
        observed=list(sheets(self.owner).values())
        candidate=getattr(document,'data_sheet',document)
        if hasattr(getattr(candidate,'model',None),'columnLabels') and candidate not in observed:observed.append(candidate)
        for sheet in observed:
            sheet.model.headerDataChanged.connect(self.refresh_column_choices)
            sheet.model.modelReset.connect(self.refresh_column_choices)

    def refresh_column_choices(self,*args):
        self.sync_refs()

    def follow_selection(self, *args):
        if self.loading or self.plot:
            return
        sheet = self.document
        keys = list(sheet.model.columnLabels())
        selected = sorted(
            {
                c
                for b in sheet.ui.data_view.selectionModel().selection()
                for c in range(b.left(), b.right() + 1)
            }
        )
        refs = [
            (sheet.id, keys[c])
            for c in selected
            if c < len(keys)
            and sheet.model.column_metadata(c)["role"] not in {"X", "XErr", "YErr"}
        ]
        self.refs = refs
        self.sync_refs()

    def fill_objects(self):
        self.object_menu.keep_open = (
            self.multi.isChecked() if hasattr(self, "multi") else True
        )

        self.object_menu.clear()
        self.object_menu.addAction('—',self.clear_refs)
        self.children_menus = []
        for sheet in sheets(self.owner).values():
            child = self.object_menu
            child.keep_open = (
                getattr(self, "multi", None) is None or self.multi.isChecked()
            )
            for key in __import__("tailor.choice_catalog",fromlist=["visible_columns"]).visible_columns(sheet.model):
                i=list(sheet.model.columnLabels()).index(key)
                meta = sheet.model.column_metadata(i)
                if meta["role"] in {"X", "XErr", "YErr"}:
                    continue
                ref = (sheet.id, key)
                action = child.addAction(__import__("tailor.column_titles",fromlist=["display"]).display(sheet.model,key))
                action.setCheckable(True)
                action.setChecked(ref in self.refs)
                action.toggled.connect(
                    lambda checked, r=ref: self.toggle_ref(r, checked)
                )
        self.fill_xyz()
        if hasattr(self,'panel_setup'):self.panel_setup.sync_draft()
        if hasattr(self,'draw'):self.sync_target_actions()

    def toggle_ref(self, ref, checked):
        if checked and hasattr(self, "multi") and not self.multi.isChecked():
            self.refs = [ref]
        elif checked and ref not in self.refs:
            self.refs.append(ref)
        if not checked and ref in self.refs:
            self.refs.remove(ref)
        self.sync_refs()

    def clear_refs(self):
        self.refs=[];self.sync_refs()

    def sync_refs(self):
        available = sheets(self.owner)
        self.refs = [ref for ref in self.refs if ref[0] in available and ref[1] in __import__("tailor.choice_catalog",fromlist=["visible_columns"]).visible_columns(available[ref[0]].model)]
        self.order.clear()
        old_style=self.style_target.currentData()
        self.style_target.blockSignals(True)
        self.style_target.clear();self.style_target.addItem('—',None)
        for i, ref in enumerate(self.refs):
            try:
                _sheet, _meta = column_info(self.owner, ref)
            except (KeyError, ValueError):
                continue
            item = QtWidgets.QListWidgetItem(__import__("tailor.column_titles",fromlist=["display"]).display(_sheet.model,ref[1]))
            item.setData(QtCore.Qt.UserRole, ref)
            self.order.addItem(item)
            self.style_target.addItem(__import__("tailor.column_titles",fromlist=["display"]).display(_sheet.model,ref[1]), i)
        self.style_target.setCurrentIndex(max(0,self.style_target.findData(old_style)))
        self.style_target.blockSignals(False)
        self.objects.setText(f"已选 {len(self.refs)} 列" if self.refs else "—")
        if hasattr(self,'baseline'):
            units={str(column_info(self.owner,ref)[1].get('unit','') or '') for ref in self.refs}
            from tailor.parameter_domains import set_unit
            unit=next(iter(units)) if len(units)==1 else ''
            set_unit(self.baseline,unit)
            if hasattr(self,'bar_parameters'):
                self.bar_parameters.units[2]=unit;self.bar_parameters.sync()
            self.baseline.setToolTip('基线采用所选Y列单位；混合单位时不显示统一单位。')
        self.fill_xyz()
        if hasattr(self, 'bar_setup'):
            self.bar_setup.sync()
        if hasattr(self,'panel_setup'):self.panel_setup.sync_draft()
        if hasattr(self,'draw'):self.sync_target_actions()

    def fill_xyz(self):
        old = [box.currentData() for box in self.xyz]
        for index, box in enumerate(self.xyz):
            with QtCore.QSignalBlocker(box):
                box.clear()
                box.addItem('—',None)
                for sheet in sheets(self.owner).values():
                    for key in __import__("tailor.choice_catalog",fromlist=["visible_columns"]).visible_columns(sheet.model):
                        box.addItem(
                            __import__("tailor.column_titles",fromlist=["display"]).display(sheet.model,key),
                            (sheet.id, key),
                        )
                found = data_index(box, old[index])
                box.setCurrentIndex(
                    found if found >= 0 else 0
                )

    def order_changed(self, *args):
        self.refs = [
            tuple(self.order.item(i).data(QtCore.Qt.UserRole))
            for i in range(self.order.count())
        ]

    def move(self, delta):
        index = self.order.currentRow()
        other = index + delta
        if index >= 0 and 0 <= other < len(self.refs):
            self.refs[index], self.refs[other] = self.refs[other], self.refs[index]
            self.sync_refs()
            self.order.setCurrentRow(other)

    def choose(self, *args):
        kind = self.kind.currentData()
        if not self.loading:
            target = (
                self.document.data_sheet
                if self.plot and hasattr(self.document, "data_sheet")
                else self.document
                if not self.plot
                else None
            )
            if (
                target
                and getattr(self.document, "property_tabs", None)
                and self.document.property_tabs.currentWidget() is self
            ):
                set_mode(target, kind)
        for record in self.sections:
            title = record[1].property("sectionTitle")
            record[0].setVisible(
                title in {"高级绘图", "图形模板"}
                or title == "子图布局"
                and kind == "panels"
                or title
                == {"bar": "柱状图设置", "3d": "三维图设置", "panels": "组图设置"}.get(
                    kind
                )
            )
        for widget in (self.object_row, self.order, self.order_row):
            widget.setVisible(kind != "3d")
        self.colorbar.setEnabled(
            self.three_mode.currentData() in {"scatter", "surface"}
        )
        mapped=self.three_mode.currentData() in {'scatter','surface'} and self.colorbar.isChecked()
        self.cmap.setEnabled(mapped);self.levels.setEnabled(mapped)
        self.errors.setEnabled(self.bar_mode.currentData()!='percent')
        self.errors.setToolTip('百分比堆叠不直接使用原量纲误差棒。' if self.bar_mode.currentData()=='percent' else '显示已关联Y误差列的绝对误差棒。')
        if hasattr(self,'density_parameters'):self.density_parameters.sync()
        self.sync_target_actions()
        self.font_button.setEnabled(self.plot is not None and self.text_target.currentData() is not None)
        self.line.setEnabled(self.plot is not None and self.style_target.currentData() is not None)
        if hasattr(self, 'bar_setup'):
            self.bar_setup.sync()
        if hasattr(self,"three_setup"):self.three_setup.sync_roles()

    def sync_target_actions(self,*args):
        kind=self.kind.currentData()
        xyz=[box.currentData() for box in self.xyz]
        valid=all(ref is not None for ref in xyz) and len({tuple(ref) for ref in xyz if ref is not None})==3 if kind=='3d' else bool(self.refs)
        if kind in {'bar','panels'} and hasattr(self, 'bar_setup'):
            valid = valid and self.bar_x_ref is not None
        self.draw.setEnabled(kind is not None and valid)

    def exit_mode(self):
        target = getattr(self.document, "data_sheet", self.document)
        set_mode(target, None)
        self.message.setText("已退出高级绘图；普通绘图已恢复。")
        for sheet in sheets(self.owner).values():
            set_mode(sheet, None)
        self.message.setText("已退出高级模式，已有高级图保留；普通绘图按钮恢复。")

    def config(self):
        kind = self.kind.currentData()
        if kind is None:
            raise ValueError("请先选择高级类型。")
        if kind != "3d" and not self.refs:
            raise ValueError("请选择至少一列Y。")
        xyz = [box.currentData() for box in self.xyz]
        if kind == "3d" and (
            any(ref is None for ref in xyz)
            or len({r[0] for r in xyz}) != 1
            or len({r[1] for r in xyz}) != 3
        ):
            raise ValueError("XYZ须为同表中三列不同的数值列。")
        return {
            **({"nodes":self.panel_setup.config_nodes()} if kind=="panels" and self.plot is None else {}),
            "kind": kind,
            "display_limit": int(self.display_limit.value()),
            "refs": self.refs.copy(),
            "bar_x_ref": getattr(self, 'bar_x_ref', None),
            "bar_series": copy.deepcopy(getattr(self, 'bar_series', [])),
            "xyz": xyz,
            "bar_mode": self.bar_mode.currentData(),
            "bar_gap": self.bar_gap.value(),
            "baseline": self.baseline.value(),
            "horizontal": self.horizontal.isChecked(),
            "width": self.width.value(),
            "errors": any(entry.get('error') is not None for entry in getattr(self, 'bar_series', [])) if kind == 'bar' else self.errors.isChecked(),
            "three_mode": self.three_mode.currentData(),
            "cmap": self.cmap.currentData(),
            "custom_colors":list(getattr(getattr(self,"three_setup",None),"custom_colors",["#204e9a","#f4f4f4","#ca3c4a"])),
            "levels": int(self.levels.value()),
            "colorbar": self.colorbar.isChecked(),
            "elevation": self.elevation.value(),
            "azimuth": self.azimuth.value(),
            "projection": self.projection.currentData(),
            "rows": int(self.rows.value()),
            "columns": int(self.columns.value()),
            "share_x": self.share_x.isChecked(),
            "share_y": self.share_y.isChecked(),
            "unified_legend": self.unified.isChecked(),
            "numbering": self.numbering.isChecked(),
        }

    def create(self, *, deferred=False):
        notice=getattr(self.owner,'_notice',None)
        token=('advanced-request',id(self));handed_off=False
        self.owner._creating_advanced = True
        try:
            set_mode(
                getattr(self.document, "data_sheet", self.document),
                self.kind.currentData(),
            )
            cfg = self.config()
            if notice:notice.begin(token,'正在创建高级图形…',priority=True)
            target = (
                self.plot
                if self.plot
                and getattr(self.plot, "advanced_view", None) is not None
                and self.plot.advanced_view.cfg["kind"] == cfg["kind"]
                else None
            )
            created = target is None
            if target is None:
                ref = cfg["xyz"][1] if cfg["kind"] == "3d" else cfg["refs"][0]
                sheet, _ = column_info(self.owner, ref)
                _, xkey = sheet.processing_controls.x_values(
                    sheet, ref[1], allow_category=True
                )
                if cfg['kind'] in {'bar','panels'} and cfg.get('bar_x_ref'):
                    xkey = cfg['bar_x_ref'][1]
                if xkey is None:
                    raise ValueError("高级绘图请先给一列指定X角色。")
                old_deferred = getattr(self.owner, "_defer_inspector", False)
                self.owner._defer_inspector = deferred
                try:
                    target = self.owner.create_plot_tab(sheet, xkey, ref[1])
                finally:
                    self.owner._defer_inspector = old_deferred
                if target is None:
                    return
                target.name = {"bar": "柱状图", "3d": "三维图", "panels": "组图"}[
                    cfg["kind"]
                ]
                self.owner.ui.tabWidget.setTabText(
                    self.owner.ui.tabWidget.indexOf(target), target.name
                )
            target._advanced_notice_token=token
            if notice:
                watched=getattr(target,'_advanced_notice_watch',set())
                if token not in watched:
                    target.destroyed.connect(lambda obj=None:notice.finish(token))
                    watched.add(token);target._advanced_notice_watch=watched
            handed_off=True
            if getattr(target, "_inspector_initializing", False):
                target.presentation.extra_settings["advanced"] = cfg
                target.inspector_ready.connect(
                    lambda: self.finish_create(target, cfg, created, deferred)
                )
            else:
                self.finish_create(target, cfg, created, deferred)
        except (ValueError, KeyError, TypeError) as error:
            handed_off=False
            self.message.setText(str(error))
            self.owner.statusBar().showMessage(str(error),8000)
        finally:
            if notice and not handed_off:notice.finish(token)
            self.owner._creating_advanced = False
            self.owner.window_mode.changed()

    def finish_create(self, target, cfg, created, deferred):
        old = target.presentation.extra_settings.get("advanced", {})
        if old.get("kind") == cfg["kind"] and old.get("nodes"):
            existing_view=getattr(target,"advanced_view",None)
            if existing_view and existing_view.native:existing_view.native.snapshot()
            cfg["nodes"] = copy.deepcopy(old["nodes"])
            cfg["active_node"] = old.get("active_node")
            if cfg["kind"] == "bar":
                cfg["nodes"][0]["refs"] = copy.deepcopy(cfg["refs"])
            if "global_legend" in old:
                cfg["global_legend"] = copy.deepcopy(old["global_legend"])
        if old.get("styles"):
            cfg["styles"] = copy.deepcopy(old["styles"])
        if cfg["kind"] == "3d" and (
            created or old.get("kind") != "3d" or old.get("xyz") != cfg["xyz"]
        ):
            target.presentation.axes["right"].update(
                visible=True, title_visible=True
            )
            target.presentation.top_label = old.get("colorbar_title", "强度")
            from tailor.column_titles import remark
            def label(ref):
                source,_=column_info(self.owner,ref)
                return remark(source.model,ref[1])
            target.model.legend_label=label(cfg['xyz'][2])
            target.model.x_label=label(cfg['xyz'][0])
            target.model.y_label=label(cfg['xyz'][1])
            target.presentation.right_label=label(cfg['xyz'][2])
            target.refresh_legend()
        target.presentation.extra_settings["advanced"] = cfg
        view=install_view(target, cfg, deferred=deferred)
        token=getattr(target,'_advanced_notice_token',None)
        notice=getattr(self.owner,'_notice',None)
        if notice and token!=view._transition_token:notice.finish(token)
        from tailor.workflow_templates import apply_graph_template, store

        template = store("graphs").get(
            getattr(self.document, "_graph_template_name", "")
        )
        if template:
            apply_graph_template(target, template)
        if created:
            from tailor.column_titles import remark
            target._curve_own_name = "、".join(dict.fromkeys(remark(column_info(self.owner,r)[0].model,r[1]) for r in cfg["refs"]))
            self.owner.tab_controls.refresh()
        target.property_tabs.setCurrentWidget(target.advanced_controls)
        target.advanced_view.schedule(True)
        self.owner.mark_project_dirty()

    def load(self, cfg):
        self.loading = True
        if hasattr(self,"three_setup"):self.three_setup.custom_colors=list(cfg.get("custom_colors",["#204e9a","#f4f4f4","#ca3c4a"]))
        if hasattr(self, 'bar_setup'):
            self.bar_setup.load(cfg)
        self.refs = [tuple(r) for r in cfg.get("refs", [])]
        self.sync_refs()
        self.kind.setCurrentIndex(self.kind.findData(cfg["kind"]))
        for name, key in [
            ("bar_mode", "bar_mode"),
            ("three_mode", "three_mode"),
            ("cmap", "cmap"),
            ("projection", "projection"),
        ]:
            box = getattr(self, name)
            box.setCurrentIndex(max(0, box.findData(cfg.get(key))))
        for name in (
            "width",
            "bar_gap",
            "levels",
            "baseline",
            "rows",
            "columns",
            "azimuth",
            "elevation",
        ):
            if name in cfg:
                getattr(self, name).setValue(cfg[name])
        for name, key in [
            ("horizontal", "horizontal"),
            ("errors", "errors"),
            ("colorbar", "colorbar"),
            ("share_x", "share_x"),
            ("share_y", "share_y"),
            ("unified", "unified_legend"),
            ("numbering", "numbering"),
        ]:
            getattr(self, name).setChecked(cfg.get(key, False))
        for box, ref in zip(self.xyz, cfg.get("xyz", [])):
            box.setCurrentIndex(
                max(0, data_index(box, tuple(ref)))
            ) if ref is not None else box.setCurrentIndex(0)
        self.loading = False
        self.choose()
        if hasattr(self,"three_setup"):self.three_setup.sync_roles()

    def open_line(self):
        if self.plot and getattr(self.plot, "advanced_view", None) and self.style_target.currentData() is not None:
            self.plot.preferences.select_curve(
                "advanced", self.style_target.currentData() or 0, True
            )

    def open_font(self):
        if not self.plot or self.text_target.currentData() is None:
            return
        key = self.text_target.currentData()
        if key == "legend":
            self.plot.preferences.open_font(self.plot.legend_controls.editor, "图例")
        else:
            axis, kind = key.rsplit("_", 1)
            self.plot.axis_controls.select_axis(axis, kind)
            self.plot.preferences.open_font(
                self.plot.axis_controls.text_editor, "高级绘图文字"
            )

    def native_context(self):
        return getattr(getattr(self.plot, "advanced_view", None), "native", None)

    def refresh_panel_layout(self):
        native = self.native_context()
        if not native:
            if hasattr(self,"panel_setup"):self.panel_setup.refresh_layout()
            return
        with QtCore.QSignalBlocker(self.layout_target):
            self.layout_target.clear()
            for i, node in enumerate(native.cfg["nodes"]):
                self.layout_target.addItem(f"子图{i + 1}", node["id"])
            self.layout_target.setCurrentIndex(
                max(0, self.layout_target.findData(native.active))
            )
        node = next((n for n in native.cfg["nodes"] if n["id"] == native.active), native.cfg["nodes"][0])
        self.layout_slot.setCurrentIndex(
            max(0, self.layout_slot.findData(node.get("slot", "auto")))
        )
        rect = node.get("rect")
        if not rect:
            i = native.cfg["nodes"].index(node)
            cols = int(native.cfg.get("columns", 2))
            rows = max(
                int(native.cfg.get("rows", 1)),
                math.ceil(len(native.cfg["nodes"]) / cols),
            )
            rect = [
                100 * (i % cols) / cols,
                100 * (i // cols) / rows,
                100 / cols,
                100 / rows,
            ]
        for field, value in zip(self.layout_fields, rect):
            with QtCore.QSignalBlocker(field):
                field.setValue(value)
        from tailor.advanced_ui import sync_layout

        sync_layout(self)

    def choose_layout_target(self, index):
        from tailor.native_panels import SLOTS
        from tailor.advanced_ui import commit_layout
        if self._layout_before is not None:self._layout_timer.stop();commit_layout(self)
        pending=self._pending_slot
        native=self.native_context()
        if native:
            identifier=self.layout_target.itemData(index)
            if identifier is None:return
            native.activate(identifier)
            if pending in SLOTS:native.layout(identifier,SLOTS[pending],pending)
        elif hasattr(self,'panel_setup'):
            self.panel_setup.select(index)
            if pending in SLOTS:self.panel_setup.position(SLOTS[pending],pending)
        self._pending_slot=None
        self.refresh_panel_layout()

    def choose_layout_slot(self, index):
        from tailor.native_panels import SLOTS

        key = self.layout_slot.currentData()
        if key in SLOTS:
            for field, value in zip(self.layout_fields, SLOTS[key]):
                field.setValue(value)
            self.apply_panel_layout()
        elif key == "auto":
            native = self.native_context()
            if native:
                before = native.snapshot()
                node = next(n for n in native.cfg["nodes"] if n["id"] == native.active)
                node.pop("rect", None)
                node["slot"] = "auto"
                native.place()
                native.record(before, "恢复自动布局")
                self.refresh_panel_layout()

    def apply_panel_layout(self):
        native = self.native_context()
        if not native:
            self.panel_setup.position([f.value() for f in self.layout_fields],self.layout_slot.currentData())
            return
        try:
            native.layout(
                native.active,
                [field.value() for field in self.layout_fields],
                self.layout_slot.currentData(),
            )
            self.message.setText("子图位置和尺寸已应用；随工程保存，可撤销。")
        except ValueError as error:
            self.message.setText(str(error))

    def manage_panel(self, action):
        from tailor.native_panels import uid

        native = self.native_context()
        if not native:
            self.message.setText("请先创建组图。")
            return
        before = native.snapshot()
        nodes = native.cfg["nodes"]
        i = next(i for i, n in enumerate(nodes) if n["id"] == native.active)
        if action == "add":
            refs = self.refs[:1] or list(nodes[i]["refs"][:1])
            nodes.append({"id": uid(), "refs": refs, "sources": [], "slot": "auto"})
        elif action == "remove":
            if len(nodes) == 1:
                self.message.setText("至少保留一个子图。")
                return
            nodes.pop(i)
        else:
            j = i + (-1 if action == "up" else 1)
            if 0 <= j < len(nodes):
                nodes[i], nodes[j] = nodes[j], nodes[i]
        native.reconcile()
        native.record(before, "调整组图对象")
        self.refresh_panel_layout()

    def add_panel_curves(self):
        native = self.native_context()
        if native:
            native.add_curves(self.refs)

    def align_panels(self, action):
        native = self.native_context()
        if not native:
            return
        before = native.snapshot()
        base = next(n for n in native.cfg["nodes"] if n["id"] == native.active)
        rect = base.get("rect") or [self.layout_fields[i].value() for i in range(4)]
        position = {"left": 0, "top": 1, "width": 2, "height": 3}[action]
        updates = []
        for i, node in enumerate(native.cfg["nodes"]):
            cols = int(native.cfg.get("columns", 2))
            rows = max(
                int(native.cfg.get("rows", 1)),
                math.ceil(len(native.cfg["nodes"]) / cols),
            )
            value = list(
                node.get("rect")
                or [
                    100 * (i % cols) / cols,
                    100 * (i // cols) / rows,
                    100 / cols,
                    100 / rows,
                ]
            )
            value[position] = rect[position]
            if value[0] + value[2] > 100.00001 or value[1] + value[3] > 100.00001:
                self.message.setText("对齐会使子图超出画布，请先调整大小。")
                return
            updates.append((node, value))
        for node, value in updates:
            node.update(rect=value, slot="custom")
        native.place()
        native.record(before, "对齐子图")

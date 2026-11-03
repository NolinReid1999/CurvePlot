"""Inset/ROI and uncertainty bands using native pyqtgraph and lmfit adapters.

The ROI/ViewBox geometry follows pyqtgraph's ROI and MultiplePlotAxes examples
(MIT). Uncertainty uses lmfit ModelResult.eval_uncertainty, not a new fitter.
"""

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets
from scipy.stats import t

from tailor.compact_controls import preference_button, toggle_button
from tailor.graph_controls import row


def fit_bands(model, fit, x, level, record=None):
    from tailor.fit_results import fit_frame

    frame = fit_frame(model) if record is None else None
    dof = (len(frame) if record is None else record['statistics']['ndata']) - fit.nvarys
    if fit.covar is None or dof <= 0:
        raise ValueError("当前拟合没有有效协方差，无法计算带。")
    names = getattr(
        fit, "var_names", [name for name, p in fit.params.items() if p.vary]
    )
    if any(fit.params[name].stderr is None for name in names):
        raise ValueError("当前拟合缺少参数不确定度，请重新拟合。")
    predicted = np.asarray(fit.eval(**{model.x_col: x}), dtype=float)
    if all(fit.params[name].stderr == 0 for name in names):
        half = np.zeros_like(x)
    else:
        half = np.asarray(
            fit.eval_uncertainty(sigma=level / 100, **{model.x_col: x}), dtype=float
        )
    if record is None:
        observed = np.asarray(fit.eval(**{model.x_col: frame.x.to_numpy()}), dtype=float)
        noise = float(np.sum((frame.y.to_numpy() - observed) ** 2) / dof)
    else:
        noise = float(record['statistics']['sse'] / dof)
    prediction = np.sqrt(half**2 + t.ppf((1 + level / 100) / 2, dof) ** 2 * noise)
    if not all(np.isfinite(v).all() for v in (predicted, half, prediction)):
        raise ValueError("不确定度计算未产生有效结果。")
    return predicted, half, prediction


class PlotExtras(QtCore.QObject):
    def __init__(self, plot, graph):
        super().__init__(plot)
        self.plot = plot
        self.graph = graph
        self.loading = False
        self.refreshing = False
        self.band_items = {}
        self.inset_items = []
        self._inset_geometry_before = None
        self.range_timer = QtCore.QTimer(self)
        self.range_timer.setSingleShot(True)
        self.range_timer.setInterval(16)
        self.range_timer.timeout.connect(self.apply_inset_range)
        self.position_timer = QtCore.QTimer(self)
        self.position_timer.setSingleShot(True)
        self.position_timer.setInterval(16)
        self.position_timer.timeout.connect(self.position_inset)
        self.cfg = plot.presentation.extra_settings
        self.inset_toggle = toggle_button("显示局部放大图")
        self.inset_toggle.clicked.connect(self.change_inset)
        self.connection = preference_button("curve")
        self.connection.setText("连接线偏好")
        self.connection.clicked.connect(
            lambda: plot.preferences.select_curve("inset_connection", None, True)
        )
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.inset_toggle)
        self.shape_buttons = {}
        from tailor.inset_shapes import shape_icon

        for key, label in [("source", "放大框"), ("plot", "绘图框")]:
            choices = []
            for kind, tip in [
                ("rectangle", "方形"),
                ("rounded", "圆角方形"),
                ("circle", "圆形"),
                ("ellipse", "椭圆形"),
            ]:
                b = QtWidgets.QToolButton()
                b.setIcon(shape_icon(kind))
                b.setCheckable(True)
                b.setMinimumSize(32, 34)
                b.setIconSize(QtCore.QSize(40, 30))
                b.setSizePolicy(
                    QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
                )
                b.setStyleSheet(
                    "QToolButton {padding:0; border:0; background:transparent;} QToolButton:checked {background:#e4edf9;} QToolButton:hover {background:#f0f5fb;}"
                )
                b.setToolTip(tip)
                b.clicked.connect(
                    lambda checked=False, k=key, v=kind: self.set_shape(k, v)
                )
                self.shape_buttons[(key, kind)] = b
                choices.append(b)
            preference = preference_button("curve")
            preference.setText("")
            preference.setFixedSize(32, 34)
            preference.setIconSize(QtCore.QSize(23, 23))
            preference.setStyleSheet("QPushButton {padding:0;}")
            preference.clicked.connect(
                lambda checked=False, k=key: plot.preferences.select_curve(
                    "inset_" + k, None, True
                )
            )
            choices_row = row(*choices)
            choices_row.layout().setSpacing(4)
            layout.addWidget(row(label, choices_row, preference))
        self.auto_connect = toggle_button("自动")
        self.manual_connect = toggle_button("手动")
        self.auto_connect.setChecked(True)
        group = QtWidgets.QButtonGroup(self)
        group.addButton(self.auto_connect)
        group.addButton(self.manual_connect)
        self.auto_connect.clicked.connect(lambda: self.set_connection_mode(False))
        self.manual_connect.clicked.connect(lambda: self.set_connection_mode(True))
        self.connection.setText("")
        self.connection.setFixedSize(32, 34)
        self.connection.setIconSize(QtCore.QSize(23, 23))
        self.connection.setStyleSheet("QPushButton {padding:0;}")
        layout.addWidget(
            row("连接线", row(self.auto_connect, self.manual_connect), self.connection)
        )
        graph.add_section("局部放大", layout)
        from tailor.fit_band_controls import FitBands
        self.bands = FitBands(self, graph)
        self.band_controls = self.bands.controls
        self.band_items = self.bands.items
        self.band_dual = dict.fromkeys(self.band_controls, self.bands.dual)
        plot.ui.plot_widget.getViewBox().sigResized.connect(self.resize_inset)
        if hasattr(plot, "data_refreshed"):
            plot.data_refreshed.connect(self.refresh)
        self.load()
        from tailor.inset_collection import InsetCollection
        self.collection = InsetCollection(self, graph)

    def load(self):
        self.loading = True
        self.inset_toggle.setChecked(self.cfg.get("inset", {}).get("enabled", False))
        if hasattr(self, 'bands'):
            self.bands.load()
        self.loading = False
        self._restoring = True
        if hasattr(self, "range_roi") and self.cfg.get("inset", {}).get("range"):
            a, b, c, d = self.cfg["inset"]["range"]
            with QtCore.QSignalBlocker(self.range_roi):
                self.range_roi.setPos([a, b])
                pg.ROI.setSize(self.range_roi,[c - a, d - b])
        self.change_inset()
        self._restoring = False
        self.refresh()

    def band_color(self, kind, color):
        self.band_controls[kind][3].setText(color)
        self.update_band(kind)

    def update_band(self, kind):
        self.bands.update(kind)

    def clear_band(self, key):
        self.bands.clear(key)

    def draw_band(self, kind):
        if self.bands.selected() is not None:
            self.bands.draw(self.bands.selected(), kind, self.bands.entries())

    def change_inset(self):
        if self.loading:
            return
        import copy

        cfg = self.cfg.setdefault("inset", {})
        before = copy.deepcopy(cfg)
        cfg["enabled"] = self.inset_toggle.isChecked()
        if cfg["enabled"]:
            self.ensure_inset()
            self.range_roi.show()
            self.layout_roi.show()
            self.inset.show()
            self.refresh_inset()
            if (
                hasattr(self, "collection")
                and not getattr(self, "_collection_entry", False)
                and not hasattr(self.plot, "data_refreshed")
            ):
                for entry in self.collection.live():
                    if entry is not self:
                        entry.refresh()
        elif hasattr(self, "inset"):
            for item in (
                self.range_roi,
                self.layout_roi,
                self.inset,
                *self.lines,
                *getattr(self, "endpoint_handles", []),
            ):
                item.hide()
            from tailor.graph_focus import restore_main

            restore_main(getattr(self.plot, "_embedded_parent", self.plot))
        if not getattr(self, "_restoring", False):
            from tailor.text_style_controls import record_view_edit

            def restore(plot, value):
                self.restore_inset(value)

            record_view_edit(
                self.plot, "显示局部放大图", before, copy.deepcopy(cfg), restore
            )
            self.plot.main_window.mark_project_dirty()

    def restore_inset(self, value):
        self.cfg["inset"].clear()
        self.cfg["inset"].update(__import__("copy").deepcopy(value))
        self.load()
        if hasattr(self,"inset"):
            self.resize_inset()
        if hasattr(self,"collection"):
            self.collection.sync()

    def inset_source(self):
        if not self.plot.presentation.multi:
            sides=self.plot.presentation.single_sides
            return (self.plot.ui.plot_widget.getViewBox(),
                    'top' if sides['x']=='top' else 'x',
                    'right' if sides['y']=='right' else 'y')
        sources = self.plot.model._plots
        sid = self.cfg.get("inset", {}).get("source_id")
        source = next((s for s in sources if s.id == sid), None)
        source = (
            source
            or self.plot.curve_manager.current_plot()
            or next(iter(sources), None)
        )
        if source is None:
            return self.plot.ui.plot_widget.getViewBox(), "x", "y"
        self.cfg["inset"]["source_id"] = source.id
        info = sources[source]
        return (
            self.plot.presentation.box_for(info),
            "top" if info.x_axis == "top" else "x",
            "right" if info.axis == "right" else "y",
        )

    def ensure_inset(self):
        if hasattr(self, "inset"):
            return
        box = self.plot.ui.plot_widget.getViewBox()
        cfg = self.cfg["inset"]
        source_box, _xkey, _ykey = self.inset_source()
        xr, yr = source_box.viewRange()
        bounds = cfg.get(
            "range",
            [
                xr[0] + np.ptp(xr) * 0.35,
                yr[0] + np.ptp(yr) * 0.35,
                xr[0] + np.ptp(xr) * 0.6,
                yr[0] + np.ptp(yr) * 0.65,
            ],
        )
        from tailor.inset_shapes import ShapedROI
        from tailor.resize_handles import round_roi

        self.range_roi = ShapedROI(
            bounds[:2], [bounds[2] - bounds[0], bounds[3] - bounds[1]], pen="#448ad5"
        )
        self.range_roi.setZValue(25)
        source_box.addItem(self.range_roi, ignoreBounds=True)
        self.range_box = source_box
        self.layout_roi = ShapedROI(
            [0, 0],
            [200, 160],
            parent=box,
            pen="#448ad5",
            maxBounds=QtCore.QRectF(0, 0, box.width(), box.height()),
        )
        round_roi(self.range_roi)
        round_roi(self.layout_roi)
        self.layout_roi.setZValue(40)
        from tailor.graph_focus import create_inset_document

        self.inset = create_inset_document(self)
        # A user-sized inset frame owns its geometry. New default outer
        # margins must not let the child layout silently enlarge that frame.
        self.inset.setMinimumSize(0,0)
        self.inset.setZValue(30)
        self.inset_background = QtWidgets.QGraphicsRectItem(self.inset)
        self.inset_background.setZValue(-10000)
        self.inset_background.setPen(pg.mkPen(None))
        self.inset.setMenuEnabled(False)
        self.inset.hideButtons()
        self.inset.getViewBox().setMouseEnabled(x=False, y=False)
        self.lines = [
            QtWidgets.QGraphicsLineItem(box),
            QtWidgets.QGraphicsLineItem(box),
        ]
        for line in self.lines:
            line.setZValue(20)
        self.endpoint_handles = []
        for i in range(4):
            handle = pg.ROI([0, 0], [1, 1], parent=box, pen=None, movable=False)
            handle.addFreeHandle([0, 0])
            handle.setZValue(70)
            round_roi(handle, "#b66b20")
            for point in handle.getHandles():
                point.radius = 9
                point.buildPath()
                point._shape = None
            handle.sigRegionChangeStarted.connect(lambda *args,i=i:self.endpoint_started(i))
            handle.sigRegionChanged.connect(lambda *args,i=i:self.endpoint_live(i))
            handle.sigRegionChangeFinished.connect(
                lambda *args, i=i: self.endpoint_changed(i)
            )
            self.endpoint_handles.append(handle)
        self.range_roi.sigRegionChangeStarted.connect(self.start_geometry)
        self.layout_roi.sigRegionChangeStarted.connect(self.start_geometry)
        self.range_roi.sigRegionChanged.connect(self.live_range)
        self.range_box.sigRangeChanged.connect(self.live_range)
        self.layout_roi.sigRegionChanged.connect(self.queue_position)
        self.range_roi.sigRegionChangeFinished.connect(self.range_changed)
        self.layout_roi.sigRegionChangeFinished.connect(self.layout_changed)
        self.resize_inset()
        for roi in (self.range_roi,self.layout_roi):
            for handle in roi.getHandles():handle.hide()

    def range_changed(self):
        self.range_timer.stop()
        p = self.range_roi.pos()
        s = self.range_roi.size()
        self.cfg["inset"]["range"] = [p.x(), p.y(), p.x() + s.x(), p.y() + s.y()]
        self.apply_inset_range()
        self.commit_geometry()
        self.plot.main_window.mark_project_dirty()

    def layout_changed(self):
        self.position_timer.stop()
        box = self.plot.ui.plot_widget.getViewBox()
        p = self.layout_roi.pos()
        s = self.layout_roi.size()
        self.cfg["inset"]["layout"] = [
            p.x() / max(box.width(), 1),
            p.y() / max(box.height(), 1),
            s.x() / max(box.width(), 1),
            s.y() / max(box.height(), 1),
        ]
        self.position_inset()
        self.commit_geometry()
        self.plot.main_window.mark_project_dirty()

    def resize_inset(self, *args):
        if not hasattr(self, "inset") or self.refreshing:
            return
        # Layout/axis-label resizing changes pixels, not the saved data ROI.
        # Only an actual parent range change (live_range) normalizes its circle.
        box = self.plot.ui.plot_widget.getViewBox()
        x, y, w, h = self.cfg["inset"].get("layout", [0.64, 0.09, 0.32, 0.32])
        self.layout_roi.maxBounds = QtCore.QRectF(0, 0, box.width(), box.height())
        with QtCore.QSignalBlocker(self.layout_roi):
            self.layout_roi.setPos([x * box.width(), y * box.height()])
            pg.ROI.setSize(self.layout_roi,
                [max(110, w * box.width()), max(90, h * box.height())]
            )
        self.position_inset()

    def queue_position(self, *args):
        # Moving only translates an existing PlotItem; a 16ms trailing timer
        # makes its visible plot lag behind the frame on every second event.
        self.position_timer.stop()
        self.position_inset()

    def position_inset(self):
        if not hasattr(self, "inset"):
            return
        self.layout_roi.ensure_circle()
        p, s = self.layout_roi.pos(), self.layout_roi.size()
        box = self.plot.ui.plot_widget.getViewBox()
        origin = box.mapToScene(QtCore.QPointF(p.x() + 2, p.y() + 2))
        rect = QtCore.QRectF(origin.x(), origin.y(), s.x() - 4, s.y() - 4)
        if self.inset.geometry().size() == rect.size():
            self.inset.setPos(rect.topLeft())
        else:
            self.inset.setGeometry(rect)
            self.inset.getViewBox().prepareForPaint()
        from tailor.inset_shapes import clip_inset
        clip_inset(self.inset, self.cfg['inset'].get('plot_shape', 'rectangle'))
        if hasattr(self, "inset_background"):
            from tailor.appearance import manager

            self.inset_background.setRect(self.inset.boundingRect())
            self.inset_background.setBrush(
                pg.mkBrush("#000000" if manager().dark(True) else "#ffffff")
            )
        self.update_lines()

    def update_lines(self):
        from tailor.line_styles import curve_pen

        if not hasattr(self, "inset"):
            return
        box = self.plot.ui.plot_widget.getViewBox()
        source = box.mapFromScene(
            self.range_roi.mapRectToScene(pg.ROI.boundingRect(self.range_roi))
        ).boundingRect()
        target = box.mapFromScene(
            self.layout_roi.mapRectToScene(pg.ROI.boundingRect(self.layout_roi))
        ).boundingRect()
        style = self.cfg["inset"].get("connector_style", {})
        pen = curve_pen(
            style.get("color", "#448ad5"),
            style.get("line_width", 1),
            style.get("line_style", "dash"),
        )
        pen.setCosmetic(True)
        left_to_right = target.center().x() >= source.center().x()
        starts = (
            [source.topRight(), source.bottomRight()]
            if left_to_right
            else [source.topLeft(), source.bottomLeft()]
        )
        ends = (
            [target.topLeft(), target.bottomLeft()]
            if left_to_right
            else [target.topRight(), target.bottomRight()]
        )
        manual = self.cfg["inset"].get("manual_connection", False)
        saved = self.cfg["inset"].get("endpoints")
        points = [starts[0], ends[0], starts[1], ends[1]]
        if manual and saved and len(saved) == 4:
            rects = [source, target, source, target]
            points = [
                QtCore.QPointF(r.left() + x * r.width(), r.top() + y * r.height())
                for r, (x, y) in zip(rects, saved)
            ]
        from tailor.inset_shapes import boundary

        rects = [source, target, source, target]
        kinds = [
            self.cfg["inset"].get(k + "_shape", "rectangle")
            for k in ("source", "plot", "source", "plot")
        ]
        points = [boundary(r, k, p) for r, k, p in zip(rects, kinds, points)]
        self._placing_endpoints = True
        for handle, point in zip(self.endpoint_handles, points):
            if getattr(self,"_endpoint_dragging",None) is not None:
                continue
            with QtCore.QSignalBlocker(handle):
                handle.setPos(point)
                handle.getHandles()[0].setPos(0, 0)
            selected = getattr(self, "collection", None) and self.collection.current() is self
            handle.setVisible(bool(selected and self.inset_toggle.isChecked()))
        self._placing_endpoints = False
        for line, a, b in zip(self.lines, points[::2], points[1::2], strict=True):
            line.setLine(QtCore.QLineF(a, b))
            line.setPen(pen)
            line.setOpacity(style.get("opacity", 1))
            line.setVisible(self.inset_toggle.isChecked())

    def start_geometry(self, *args):
        if hasattr(self, "collection") and self.collection.current() is not self:
            self.collection.select(self.cfg["inset"].get("id"), self.collection.part)
        import copy

        self._inset_geometry_before = copy.deepcopy(self.cfg.get("inset", {}))
        self.cfg['inset'].pop('preserve_transformed_range',None)

    def commit_geometry(self):
        import copy

        before = self._inset_geometry_before
        if before is None:
            return
        self._inset_geometry_before = None
        from tailor.text_style_controls import record_view_edit

        def restore(plot, value):
            self.restore_inset(value)

        record_view_edit(
            self.plot,
            "局部放大位置与范围",
            before,
            copy.deepcopy(self.cfg["inset"]),
            restore,
        )

    def live_range(self, *args):
        if self.refreshing or not self.inset_toggle.isChecked():
            return
        if (args and args[0] is self.range_box and not getattr(self,'_restoring',False)
                and not getattr(self.plot.main_window,'_project_reveal_pending',False)):
            self._parent_range_changed=True
        if not self.range_timer.isActive():
            self.range_timer.start()

    def apply_inset_range(self):
        if not hasattr(self, "inset"):
            return
        # Reading/applying a saved range must not constrain its geometry using
        # an intermediate ViewBox transform during project initialization.
        # Explicit shape changes, handles and parent view interactions enforce
        # the circle; a mere refresh/load never rewrites a saved data range.
        if getattr(self,'_parent_range_changed',False):
            self._parent_range_changed=False
            self.range_roi.ensure_circle()
            p,size=self.range_roi.pos(),self.range_roi.size()
            self.cfg['inset']['range']=[p.x(),p.y(),p.x()+size.x(),p.y()+size.y()]
        p, s = self.range_roi.pos(), self.range_roi.size()
        from tailor.graph_presentation import display, physical

        _, xkey, ykey = self.inset_source()
        converted = [
            display(
                physical(values, self.plot.presentation.axes[source]),
                self.inset_doc.presentation.axes[target],
            )
            for values, source, target in (
                ((p.x(), p.x() + s.x()), xkey, "x"),
                ((p.y(), p.y() + s.y()), ykey, "y"),
            )
        ]
        if not all(np.isfinite(v).all() for v in converted):
            return
        previous=getattr(self,'_setting_range',False)
        self._setting_range = True
        try:
            self.inset.setRange(xRange=converted[0], yRange=converted[1], padding=0)
            # X may already be unchanged when a circular ROI adjusts only Y.
            # MultiPlot remembers ranges on sigXRangeChanged, so update both
            # caches explicitly before its deferred inspector/source redraw.
            if self.inset_doc.presentation.multi:
                self.inset_doc._remembered_x_range = list(converted[0])
                self.inset_doc._remembered_y_range = list(converted[1])
        finally:
            self._setting_range = previous
        self.cfg["inset"]["range"] = [p.x(), p.y(), p.x() + s.x(), p.y() + s.y()]
        if hasattr(self, "lines"):
            self.update_lines()

    def snapshot(self):
        if hasattr(self,"collection") and not getattr(self,"_collection_entry",False):
            for record in self.collection.records:
                entry=self.collection.controllers[record["id"]]
                if entry is not self:
                    entry.snapshot()
        if hasattr(self, "inset_doc"):
            doc = self.inset_doc
            cfg = self.cfg["inset"]
            cfg["graph_settings"] = doc.presentation.to_dict()
            cfg["curve_style"] = doc.curve_style.to_dict()
            cfg["x_label"] = doc.model.x_label
            cfg["y_label"] = doc.model.y_label

    def sync_inset_curves(self):
        """Follow source styling without rebuilding data on ROI mouse moves."""
        import copy
        from dataclasses import replace

        parent, doc = self.plot, self.inset_doc
        curve_keys = set(parent.curve_style.to_dict()) - {
            "font_size", "font_family", "text_styles", "transparent"
        }
        style = {key: value for key, value in parent.curve_style.to_dict().items()
                 if key in curve_keys}
        infos = ({source: copy.deepcopy(info)
                  for source, info in parent.model._plots.items()}
                 if parent.presentation.multi else {})
        overrides = {key: copy.deepcopy(value)
                     for key, value in parent.presentation.curve_overrides.items()
                     if not key.startswith("annotation:")}
        columns=(() if parent.presentation.multi else
                 (parent.model.x_col,parent.model.y_col,parent.model.x_err_col,parent.model.y_err_col))
        state = (style, infos, overrides, columns)
        previous = getattr(self, "_source_curve_state", None)
        self._source_curve_state = state
        if previous is None or previous == state:
            return
        # Independent inset axis/text settings remain local. Only a changed
        # source curve style replaces its inset counterpart, including undo.
        if parent.presentation.multi:
            doc.add_plots_to_ui([source for source in infos if source not in doc._plots])
            for source in set(doc.model._plots) - set(infos):
                doc.model.remove_plot(source)
            for source, info in infos.items():
                doc.model._plots[source] = copy.deepcopy(info)
        else:
            if previous[0] != style:
                doc.apply_curve_style(replace(doc.curve_style, **style), dirty=False)
            if len(previous)<4 or previous[3]!=columns:
                dm=parent.data_sheet.model.data_model
                names=[dm.get_column_name(key) if key else None for key in columns]
                doc.change_data_source(parent.data_sheet,*names)
        if previous[2] != overrides:
            doc.presentation.curve_overrides = {
                key: value for key, value in doc.presentation.curve_overrides.items()
                if key.startswith("annotation:")
            } | copy.deepcopy(overrides)
        if parent.presentation.multi:
            doc.draw_plot()
        else:
            doc.update_model_curves()
            doc.refresh_legend()
        self.apply_inset_range()

    def refresh_inset(self):
        if not hasattr(self, "inset") or not self.inset_toggle.isChecked():
            return
        self.sync_inset_curves()
        self.apply_inset_range()
        self.resize_inset()
        # Source events already refresh the reused native inset document. ROI
        # movement changes only view range; no 500k-point clones are rebuilt.
        self.apply_shapes()
        from tailor.appearance import manager

        manager().apply_document(self.inset_doc)

    def set_shape(self, key, value):
        self.start_geometry()
        cfg = self.cfg.setdefault("inset", {})
        old = cfg.get(key + "_shape", "rectangle")
        cfg[key + "_shape"] = value
        roi = self.range_roi if key == "source" else self.layout_roi
        # Change the constraint before resizing: the old circle constraint must
        # not turn the requested ellipse back into an enlarged circle.
        roi.shape_name = value
        if value == "ellipse" and old != "ellipse":
            pixel = self.range_box.viewPixelSize() if key == "source" else (1, 1)
            px, py = max(abs(pixel[0]), 1e-12), max(abs(pixel[1]), 1e-12)
            size = roi.size()
            width = size.x() / px
            height = size.y() / py
            if width < height * 1.5:
                center = roi.pos() + size / 2
                size = QtCore.QPointF(height * 1.6 * px, height * py)
                with QtCore.QSignalBlocker(roi):
                    roi.setSize(size)
                    roi.setPos(center - size / 2)
        self.apply_shapes(constrain=True)
        p, size = self.range_roi.pos(), self.range_roi.size()
        cfg["range"] = [p.x(), p.y(), p.x() + size.x(), p.y() + size.y()]
        box = self.plot.ui.plot_widget.getViewBox()
        p, size = self.layout_roi.pos(), self.layout_roi.size()
        cfg["layout"] = [
            p.x() / box.width(),
            p.y() / box.height(),
            size.x() / box.width(),
            size.y() / box.height(),
        ]
        self.commit_geometry()

    def apply_shapes(self, *, constrain=False):
        if not hasattr(self, "inset"):
            return
        from tailor.line_styles import curve_pen

        for key, roi in [("source", self.range_roi), ("plot", self.layout_roi)]:
            kind = self.cfg["inset"].get(key + "_shape", "rectangle")
            roi.shape_name = kind
            spec = self.cfg["inset"].get(key + "_style", {})
            roi.setPen(
                curve_pen(
                    spec.get("color", "#448ad5"),
                    spec.get("line_width", 1),
                    spec.get("line_style", "solid"),
                )
            )
            roi.setOpacity(spec.get("opacity", 1))
            if constrain and kind == "circle" and not (key=='source' and self.cfg['inset'].get('preserve_transformed_range')):
                size = roi.size()
                pixel = self.range_box.viewPixelSize() if key == "source" else (1, 1)
                px, py = max(abs(pixel[0]), 1e-12), max(abs(pixel[1]), 1e-12)
                side = min(size.x() / px, size.y() / py)
                with QtCore.QSignalBlocker(roi):
                    center = roi.pos() + roi.size()/2
                    pg.ROI.setSize(roi, [side * px, side * py])
                    roi.setPos(center - roi.size()/2)
            roi.update()
            for (k, value), button in self.shape_buttons.items():
                if k == key:
                    button.setChecked(value == kind)
        from types import MethodType

        from tailor.inset_shapes import outline, clip_inset

        kind = self.cfg["inset"].get("plot_shape", "rectangle")
        self.inset.shape = MethodType(
            lambda item: outline(item.boundingRect(), kind), self.inset
        )
        self.inset.setFlag(
            QtWidgets.QGraphicsItem.ItemClipsChildrenToShape, kind != "rectangle"
        )
        clip_inset(self.inset, kind)
        self.inset.prepareGeometryChange()
        self.apply_inset_range()
        self.position_inset()
        self.update_lines()

    def set_connection_mode(self, manual):
        self.start_geometry()
        self.cfg.setdefault("inset", {})["manual_connection"] = manual
        self.update_lines()
        self.commit_geometry()

    def endpoint_started(self,index):
        self.start_geometry()
        self._endpoint_dragging=index

    def endpoint_live(self,index):
        if getattr(self,"_endpoint_dragging",None) is not None:
            self.endpoint_changed(index,finished=False)

    def endpoint_changed(self, index, finished=True):
        if getattr(self, "_placing_endpoints", False):
            return
        if self._inset_geometry_before is None:
            self.start_geometry()
        box = self.plot.ui.plot_widget.getViewBox()
        source = box.mapFromScene(
            self.range_roi.mapRectToScene(pg.ROI.boundingRect(self.range_roi))
        ).boundingRect()
        target = box.mapFromScene(
            self.layout_roi.mapRectToScene(pg.ROI.boundingRect(self.layout_roi))
        ).boundingRect()
        values = []
        for i, handle in enumerate(self.endpoint_handles):
            point = handle.mapToParent(handle.getHandles()[0].pos())
            r = source if i % 2 == 0 else target
            x = (point.x() - r.left()) / max(1e-12, r.width())
            y = (point.y() - r.top()) / max(1e-12, r.height())
            kind = self.cfg["inset"].get(
                ("source" if i % 2 == 0 else "plot") + "_shape", "rectangle"
            )
            from tailor.inset_shapes import boundary

            projected = boundary(
                r,
                kind,
                QtCore.QPointF(r.left() + x * r.width(), r.top() + y * r.height()),
            )
            x = (projected.x() - r.left()) / max(1e-12, r.width())
            y = (projected.y() - r.top()) / max(1e-12, r.height())
            values.append([float(x), float(y)])
        self.cfg["inset"]["manual_connection"] = True
        self.cfg["inset"]["endpoints"] = values
        if finished:
            self._endpoint_dragging=None
            self.commit_geometry()
        self.update_lines()

    def refresh(self, *args):
        if self.refreshing:
            return
        self.refreshing = True
        try:
            if hasattr(self, "bands"):
                self.bands.refresh()
            self.refresh_inset()
            if hasattr(self, "collection") and not getattr(self, "_collection_entry", False):
                for entry in self.collection.live():
                    if entry is not self:
                        entry.refresh()
        finally:
            self.refreshing = False

    def close(self):
        if hasattr(self,"collection") and not getattr(self,"_collection_entry",False):
            for entry in list(self.collection.controllers.values()):
                if entry is not self:
                    entry.close()
        self.range_timer.stop()
        self.position_timer.stop()
        self.plot.ui.plot_widget.getViewBox().sigResized.disconnect(self.resize_inset)
        if hasattr(self, "bands"):
            self.bands.close()
        if hasattr(self, "inset"):
            from tailor.curve_controls import dispose_graph

            dispose_graph(self.inset_doc)
            self.inset_doc.deleteLater()
            self.range_box.sigRangeChanged.disconnect(self.live_range)
            self.range_box.removeItem(self.range_roi)
            for item in (
                self.layout_roi,
                self.inset,
                *self.lines,
                *getattr(self, "endpoint_handles", []),
            ):
                scene = item.scene()
                item.setParentItem(None)
                if scene is not None:
                    scene.removeItem(item)

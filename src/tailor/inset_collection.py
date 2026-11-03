"""Multiple inset entries reuse PlotExtras' existing ROI and PlotTab adapters."""

import copy
import uuid

import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from tailor.graph_controls import row


def active(extras):
    collection = getattr(extras, "collection", None)
    return collection.current() or extras if collection else extras


def entries(plot):
    extras = getattr(plot, "extras", None)
    if extras is None:
        return []
    collection = getattr(extras, "collection", None)
    return collection.live() if collection else [extras]


class InsetCollection(QtCore.QObject):
    def __init__(self, primary, graph):
        super().__init__(primary)
        self.primary, self.plot, self.graph = primary, primary.plot, graph
        self.controllers, self.selected = {}, None
        self.restoring = False
        self.part = "source"
        cfg = primary.cfg.setdefault("inset", {})
        cfg.setdefault("id", uuid.uuid4().hex)
        self.controllers[cfg["id"]] = primary
        primary.collection = self
        self.records = []
        self.build_controls()
        self.restore_extra(primary.cfg)
        self.plot.ui.plot_widget.viewport().installEventFilter(self)

    def build_controls(self):
        section = next(
            r
            for r in self.graph.sections
            if r[1].property("sectionTitle") == "局部放大"
        )
        content = section[3]
        old = content.layout()
        park = QtWidgets.QWidget(content)
        park.hide()
        while old.count():
            item = old.takeAt(0)
            if item.widget():
                item.widget().setParent(park)
        from tailor.element_button_group import ElementButtons
        from tailor.compact_controls import equal_row, preference_button
        self.actions = ElementButtons(self.plot, "insets", add=lambda: self.add_entry(deferred=True))
        self.add = self.actions.buttons["add"]
        self.hide = self.actions.buttons["hide"]
        self.delete = self.actions.buttons["delete"]
        self.preference = preference_button("curve")
        self.preference.clicked.connect(self.open_preference)
        old.addWidget(equal_row(self.actions, self.preference))
        self.shapes = {}
        from tailor.inset_shapes import shape_icon

        choices = []
        for key, title in (
            ("circle", "圆形"),
            ("ellipse", "椭圆"),
            ("rounded", "圆角方形"),
        ):
            b = QtWidgets.QToolButton()
            b.setIcon(shape_icon(key))
            b.setIconSize(QtCore.QSize(34, 28))
            b.setMinimumSize(27, 32)
            b.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
            b.setStyleSheet(
                "QToolButton {border:0;padding:0;background:transparent;} QToolButton:checked {background:#dceaff;}"
            )
            b.setCheckable(True)
            b.setToolTip(title)
            b.clicked.connect(lambda checked=False, k=key: self.set_shape(k))
            self.shapes[key] = b
            choices.append(b)
        old.addWidget(row("框线", row(*choices)))
        from tailor.fold_panel import compact
        compact(content)
        self.sync()

    def live(self):
        return [self.controllers[r["id"]] for r in self.records if r.get("enabled")]

    def current(self):
        return (
            self.controllers.get(self.selected)
            if any(r["id"] == self.selected for r in self.records)
            else None
        )

    def new_controller(self, cfg):
        from tailor.plot_extras import PlotExtras

        e = PlotExtras.__new__(PlotExtras)
        QtCore.QObject.__init__(e, self.plot)
        e.plot, e.graph, e.loading, e.refreshing = self.plot, self.graph, False, False
        e.band_items, e.band_controls, e.inset_items, e.shape_buttons = {}, {}, [], {}
        e._inset_geometry_before = None
        e.collection = self
        e._collection_entry = True
        e.cfg = {"inset": cfg}
        e.inset_toggle = QtWidgets.QPushButton()
        e.inset_toggle.setCheckable(True)
        e.inset_toggle.hide()
        for name, callback in (
            ("range_timer", e.apply_inset_range),
            ("position_timer", e.position_inset),
        ):
            timer = QtCore.QTimer(e)
            timer.setSingleShot(True)
            timer.setInterval(16)
            timer.timeout.connect(callback)
            setattr(e, name, timer)
        self.plot.ui.plot_widget.getViewBox().sigResized.connect(e.resize_inset)
        if hasattr(self.plot, "data_refreshed"):
            self.plot.data_refreshed.connect(e.refresh)
        return e

    def snapshot(self):
        for e in self.live():
            e.snapshot()
        return {"records": copy.deepcopy(self.records), "selected": self.selected}

    def restore_extra(self, master):
        if self.restoring:
            return
        stored = master.get("insets")
        if stored is None:
            legacy = master.get("inset", {})
            stored = [legacy] if legacy.get("enabled") or legacy.get("range") else []
        self.restore({"records": copy.deepcopy(stored), "selected": None}, master)

    def restore(self, state, master=None):
        if self.restoring:
            return
        self.restoring = True
        try:
            master = (
                master if master is not None else self.plot.presentation.extra_settings
            )
            self.primary.cfg = master
            wanted = state["records"]
            ids = {r.get("id") for r in wanted}
            for key, e in self.controllers.items():
                if key not in ids:
                    e.cfg.setdefault("inset", {"id": key})["enabled"] = False
                    e.load()
            records = []
            for saved in wanted:
                for field in ("source_shape", "plot_shape"):
                    if saved.get(field, "rectangle") == "rectangle":
                        saved[field] = "rounded"
                saved.setdefault("id", uuid.uuid4().hex)
                key = saved["id"]
                e = self.controllers.get(key)
                if e is None:
                    e = self.new_controller(copy.deepcopy(saved))
                    self.controllers[key] = e
                else:
                    target = e.cfg.setdefault("inset", {})
                    target.clear()
                    target.update(copy.deepcopy(saved))
                e.load()
                records.append(e.cfg["inset"])
            self.records = records
            master["insets"] = records
            self.selected = state.get("selected")
            self.sync()
        finally:
            self.restoring = False

    def edit(self, label, callback):
        before = self.snapshot()
        blocked = getattr(self.plot, "_view_edit_active", False)
        self.plot._view_edit_active = True
        try:
            callback()
        finally:
            self.plot._view_edit_active = blocked
        self.plot.presentation.extra_settings["insets"] = self.records
        after = self.snapshot()
        from tailor.text_style_controls import record_view_edit

        record_view_edit(
            self.plot, label, before, after, lambda p, state: self.restore(state)
        )
        self.plot.main_window.mark_project_dirty()
        self.sync()

    def add_entry(self, *, deferred=False):
        if getattr(getattr(self.plot,'_embedded_parent',self.plot),'advanced_view',None) is not None:return
        def add():
            cfg = {
                "id": uuid.uuid4().hex,
                "enabled": True,
                "source_shape": "circle",
                "plot_shape": "circle",
                "layout": [0.62, 0.08 + min(0.3, len(self.records) * 0.08), 0.32, 0.32],
            }
            from tailor.choice_catalog import seed_objects,object_rank
            seed_objects(self.plot);object_rank(self.plot,'inset',cfg['id'])
            e = self.new_controller(cfg)
            e._defer_inset_inspector = deferred
            self.controllers[cfg["id"]] = e
            self.records.append(cfg)
            e.load()
            e.set_shape('source', 'circle')
            self.select(cfg["id"])

        self.edit("添加局部放大", add)

    def delete_entry(self):
        e = self.current()
        if not e:
            return

        def remove():
            e.cfg["inset"]["enabled"] = False
            e.load()
            self.records = [r for r in self.records if r["id"] != self.selected]
            self.select(None)

        self.edit("删除局部放大", remove)

    def set_hidden(self, key, hidden):
        if key not in self.controllers:
            return
        e = self.controllers[key]

        def change():
            e.cfg["inset"]["enabled"] = not hidden
            e.load()
            self.select(None if hidden else key)
            if hidden and getattr(self.plot,'_active_document',None) is getattr(e,'inset_doc',None):
                from tailor.graph_focus import restore_main
                restore_main(getattr(self.plot,'_embedded_parent',self.plot))

        self.edit("隐藏局部放大" if hidden else "显示局部放大", change)

    def fill_hidden(self):
        self.menu.clear()
        for i, r in enumerate(self.records):
            if not r.get("enabled"):
                self.menu.addAction(
                    f"局部放大{i + 1}",
                    lambda checked=False, k=r["id"]: self.set_hidden(k, False),
                )
        if not self.menu.actions():
            self.menu.addAction("没有隐藏的局部放大").setEnabled(False)
        self.menu.setFixedWidth(self.hide.width())

    def select(self, key, part="source", reveal=False):
        self.selected, self.part = key, part
        if key is not None:
            if hasattr(self.plot, "curve_selection"):
                self.plot.curve_selection.clear()
            if hasattr(self.plot, "text_selection"):
                self.plot.text_selection.select(None)
            if hasattr(self.plot, "annotations") and self.plot.annotations.selected:
                self.plot.annotations.select(None)
        self.sync()
        if reveal:
            from tailor.graph_focus import restore_main
            from tailor.text_style_controls import reveal_section

            restore_main(getattr(self.plot, "_embedded_parent", self.plot))
            if self.plot.preferences.preference_mode() is not None:
                self.plot.preferences.select_curve('inset_' + part, None, True)
                return
            self.plot.preferences.return_to_inspector()
            reveal_section(self.plot, self.plot.preferences.graph, "局部放大")

    def sync(self):
        e = self.current()
        enabled = bool(e and e.cfg["inset"].get("enabled"))
        self.actions.sync()
        self.delete.setEnabled(enabled)
        self.preference.setEnabled(enabled)
        for kind, b in self.shapes.items():
            b.setEnabled(enabled)
            b.setChecked(bool(e and e.cfg["inset"].get("source_shape") == kind))
        panel = getattr(self.plot, "annotation_panel", None)
        if panel is None:
            panel = getattr(self.plot.annotations, "panel", None)
        if panel and hasattr(panel, "position_controls") and not self.restoring:
            panel.position_controls.sync()
        for controller in self.controllers.values():
            if not hasattr(controller, "range_roi"):
                continue
            selected = enabled and controller is e
            for roi in (controller.range_roi, controller.layout_roi):
                for handle in roi.getHandles():
                    handle.setVisible(selected)
            for handle in controller.endpoint_handles:
                handle.setVisible(selected)

    def set_shape(self, kind):
        e = self.current()
        if e:
            self.edit(
                "局部放大框线形状",
                lambda: (e.set_shape("source", kind), e.set_shape("plot", kind)),
            )

    def open_preference(self):
        kind = (
            "inset_connection"
            if self.part == "connection"
            else "inset_plot"
            if self.part == "plot"
            else "inset_source"
        )
        self.plot.preferences.select_curve(kind, None, True)

    def frame_at(self,pos):
        """Frame/resize hit test shared with the inset's inspector focus gate."""
        from tailor.inset_shapes import outline
        for e in reversed(self.live()):
            if not hasattr(e,'inset'):continue
            for part,roi in (('source',e.range_roi),('plot',e.layout_roi)):
                if not roi.isVisible():continue
                rect=roi.mapRectToScene(pg.ROI.boundingRect(roi))
                rect=rect.boundingRect() if hasattr(rect,'boundingRect') else rect
                path=outline(rect,e.cfg['inset'].get(part+'_shape','rounded'))
                stroker=QtGui.QPainterPathStroker();stroker.setWidth(12)
                handles=any(h.isVisible() and h.sceneBoundingRect().adjusted(-3,-3,3,3).contains(pos) for h in roi.getHandles())
                if handles or stroker.createStroke(path).contains(pos):return e,part
        return None

    def select_frame_fast(self,e,part):
        self.selected,self.part=e.cfg['inset']['id'],part
        # Avoid rebuilding object lists or swapping thousand-widget inspectors
        # before the first mouse move. Graphics handles alone are immediate.
        for controller in self.controllers.values():
            if not hasattr(controller,'range_roi'):continue
            selected=controller is e
            for roi in (controller.range_roi,controller.layout_roi):
                for handle in roi.getHandles():handle.setVisible(selected)
            for handle in controller.endpoint_handles:handle.setVisible(selected)

    def eventFilter(self,obj,event):
        from tailor.point_inspector import point_active
        if point_active(self.plot):return False
        # Embedded inset documents share the root viewport, but cannot own
        # nested insets. Their empty collection must not restore root focus.
        if getattr(self.plot, '_inset_parent', None) is not None:
            return False
        if event.type()==QtCore.QEvent.MouseButtonRelease and getattr(self,'_frame_press',None):
            key,part=self._frame_press;self._frame_press=None
            QtCore.QTimer.singleShot(0,self,lambda:self.select(key,part,True) if key in self.controllers else None)
            return False
        if event.type()!=QtCore.QEvent.MouseButtonPress or event.button()!=QtCore.Qt.LeftButton:return False
        pos=self.plot.ui.plot_widget.mapToScene(event.position().toPoint())
        frame=self.frame_at(pos)
        if frame:
            e,part=frame;self.select_frame_fast(e,part);self._frame_press=(e.cfg['inset']['id'],part)
            return False
        for e in reversed(self.live()):
            if not hasattr(e,'inset'):continue
            key=e.cfg['inset']['id']
            if self.current() is e and any(h.sceneBoundingRect().adjusted(-8,-8,8,8).contains(pos) for h in e.endpoint_handles):return False
            for line in e.lines:
                path=QtGui.QPainterPath(line.mapToScene(line.line().p1()));path.lineTo(line.mapToScene(line.line().p2()))
                stroker=QtGui.QPainterPathStroker();stroker.setWidth(10)
                if stroker.createStroke(path).contains(pos):self.select(key,'connection',True);return False
            from tailor.graph_focus import inset_contains
            if inset_contains(e,pos):
                self.select(key,'plot')
                from tailor.graph_focus import activate_inset
                activate_inset(self.plot,e);return False
        self.select(None)
        from tailor.graph_focus import restore_main
        restore_main(getattr(self.plot,'_embedded_parent',self.plot))
        return False

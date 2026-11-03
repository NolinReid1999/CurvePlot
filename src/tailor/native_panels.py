"""Embed existing Tailor documents, canvases and inspectors as advanced panels.

No parallel axes, selection, annotation or fitting engine: each panel uses the
same PlotTab/MultiPlotTab that ordinary graphs use. The adapter manages only
panel identity, layout, active inspector and shared properties.
"""

import copy
import math
import uuid
from time import monotonic
from types import SimpleNamespace

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from tailor.graph_controls import row

SLOTS = {
    "A": [0, 0, 50, 50],
    "B": [50, 0, 50, 50],
    "C": [0, 50, 50, 50],
    "D": [50, 50, 50, 50],
}


def uid():
    return uuid.uuid4().hex


def documents(window):
    """Additional native source documents, never additional visible tabs."""
    result = []
    for i in range(window.ui.tabWidget.count()):
        tab = window.ui.tabWidget.widget(i)
        view = getattr(tab, "advanced_view", None)
        native = getattr(view, "native", None)
        if native:
            for doc in native.live():
                result.extend(native.source_documents(doc))
    return list(dict.fromkeys(result))


class PanelCanvas(QtWidgets.QWidget):
    def __init__(self, native):
        super().__init__()
        self.native = native
        self.setAutoFillBackground(True)
        self.setMinimumSize(200, 180)
        # Match the existing workspace before the first child is ready.
        self.setBackground(native.root.ui.plot_widget.backgroundBrush().color())

    def viewport(self):
        return self

    def backgroundBrush(self):
        return self.palette().brush(QtGui.QPalette.Window)

    def setBackground(self, color):
        palette = self.palette()
        palette.setColor(
            QtGui.QPalette.Window, QtGui.QColor(color or QtCore.Qt.transparent)
        )
        self.setPalette(palette)

    def scene(self):
        return SimpleNamespace(
            items=lambda: [
                item
                for doc in self.native.panels.values()
                for item in doc.ui.plot_widget.scene().items()
            ]
        )

    def setProperty(self, name, value):
        result = super().setProperty(name, value)
        if name == "exportPixelScale":
            for doc in self.native.panels.values():
                doc.ui.plot_widget.setProperty(name, value)
        return result

    def render(self, painter, target, source, aspect):
        painter.save()
        painter.translate(target.topLeft())
        painter.scale(
            target.width() / source.width(), target.height() / source.height()
        )
        QtWidgets.QWidget.render(
            self,
            painter,
            QtCore.QPoint(),
            QtGui.QRegion(source),
            QtWidgets.QWidget.DrawWindowBackground | QtWidgets.QWidget.DrawChildren,
        )
        painter.restore()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.native.place()


class ActivatePanel(QtCore.QObject):
    def __init__(self, native, node, doc):
        super().__init__(doc)
        self.native, self.node, self.doc = native, node, doc
        doc.ui.plot_widget.viewport().installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() in {
            QtCore.QEvent.MouseButtonPress,
            QtCore.QEvent.MouseButtonDblClick,
        }:
            previous=self.native.current();placement=None
            if previous is not None and previous is not self.doc:
                manager=previous.annotations
                if manager.tool:
                    placement=(manager.tool,manager.anchor,getattr(manager,'_new_image_data',None))
                    if hasattr(manager,'_new_image_data'):del manager._new_image_data
                    manager.arm(None)
            self.native.activate(self.node["id"])
            if placement:
                tool,anchor,image=placement
                self.doc.annotations.anchor=anchor
                if image is not None:self.doc.annotations._new_image_data=image
                self.doc.annotations.arm(tool)

        return False


class NativePanels(QtCore.QObject):
    def __init__(self, view):
        super().__init__(view)
        self.view, self.root = view, view.plot
        self.owner = self.root.main_window
        self.sources, self.panels, self.figures, self.gates = {}, {}, {}, []
        self.versions = {}
        self.parked = QtWidgets.QWidget(self.root)
        self.parked.hide()
        self.cfg = view.cfg
        self.original_tabs = self.root.property_tabs
        self.original_host = self.root.preferences
        self.original_quick = self.root.quick_actions
        from tailor.inspector_slots import splitter_for
        self.splitter = splitter_for(self.original_host)
        self.active = None
        self.loading = False
        self.syncing = False
        self.shared_legend = None
        self.initializing = False
        self._reconcile_steps = None
        self._initializing_documents = []
        self._prepared_documents=0
        from tailor.curve_documents import InspectorMoveGuard
        self._move_guard=InspectorMoveGuard(self.root)
        self._initialization_timer = QtCore.QTimer(self)
        self._initialization_timer.setSingleShot(True)
        self._initialization_timer.setTimerType(QtCore.Qt.PreciseTimer)
        self._initialization_timer.timeout.connect(self.advance_initialization)
        self.legend_timer = QtCore.QTimer(self)
        self.legend_timer.setSingleShot(True)
        self.legend_timer.setInterval(30)
        self.legend_timer.timeout.connect(self.refresh_unified)
        self.canvas = PanelCanvas(self)
        self.ensure_nodes()
        self.reconcile()

    def ensure_nodes(self):
        cfg = self.cfg
        refs = [tuple(r) for r in cfg.get("refs", [])]
        if cfg["kind"] == "3d":
            refs = [tuple(cfg["xyz"][1])]
        if "nodes" not in cfg:
            groups = [[ref] for ref in refs] if cfg["kind"] == "panels" else [refs]
            cfg["nodes"] = [
                {"id": uid(), "refs": group, "slot": "auto", "sources": []}
                for group in groups
                if group
            ]
        if not cfg["nodes"]:
            raise ValueError("请至少保留一个包含曲线的子图。")

    def new_source(self, node, ref, saved=None):
        from tailor.advanced_plotting import column_info
        from tailor.plot_tab import PlotTab
        from tailor.project_files import load_plot
        from tailor.project_models import Plot

        sheet, meta = column_info(self.owner, ref)
        if saved:
            doc = load_plot(self.owner, Plot.model_validate(saved), sheet)
            self.owner._plot_num = max(self.owner._plot_num, doc.id)
        else:
            _, xkey = sheet.processing_controls.x_values(
                sheet, ref[1], allow_category=True
            )
            selected_x=self.cfg.get("bar_x_ref")
            if selected_x and selected_x[0]==sheet.id:xkey=selected_x[1]
            if xkey is None:
                raise ValueError("高级绘图需要明确X列。")
            self.owner._plot_num += 1
            keys = list(sheet.model.columnLabels())
            index = keys.index(ref[1])
            error = (
                keys[index + 1]
                if index + 1 < len(keys)
                and sheet.model.column_metadata(index + 1)["role"] == "YErr"
                else None
            )
            doc = PlotTab(
                self.owner,
                meta["name"],
                self.owner._plot_num,
                sheet,
                xkey,
                ref[1],
                y_err_col=error,
                defer_inspector=self.view.deferred_documents,
                hidden_source=len(node['refs']) > 1,
            )
            from tailor.column_titles import remark
            doc.model.x_label = remark(sheet.model, xkey)
            doc.model.y_label = remark(sheet.model, ref[1])
            formats = node.get("template_sources", [])
            index = {tuple(r): i for i, r in enumerate(node["refs"])}.get(
                tuple(ref), -1
            )
            if 0 <= index < len(formats):
                from tailor.curve_style import CurveStyle

                fmt = formats[index]
                doc.presentation.load(copy.deepcopy(fmt["graph_settings"]))
                doc.model.x_label, doc.model.y_label = fmt["x_label"], fmt["y_label"]
                doc.apply_curve_style(CurveStyle(**fmt["curve_style"]), dirty=False)
        doc._embedded_parent = self.root
        if self.cfg['kind'] == 'bar':
            doc._advanced_bar = True
            doc.ui.plot_widget.hide()
        doc._panel_id = node["id"]
        doc.setParent(self.parked)
        doc.hide()
        self.sources[doc.id] = doc
        self.queue_inspector(doc)
        # Reuse ordinary native refresh and model/fit/selection behavior.
        doc.data_refreshed.connect(self.changed)
        doc._advanced_gate = ActivatePanel(self, node, doc)
        self.gates.append(doc._advanced_gate)
        from tailor.appearance import manager

        manager().apply_document(doc, force=True)
        return doc

    def queue_inspector(self, doc):
        if getattr(doc, "_inspector_initializing", False):
            doc._inspector_timer.stop()
            if doc not in self._initializing_documents:
                self._initializing_documents.append(doc)

    def advance_initialization(self):
        if getattr(self.root, "_graph_disposed", False):return
        if self._move_guard.active():
            self._initialization_timer.start(16);return
        # Reuse ordinary multi-curve preparation's small event-loop budget.
        # No fixed 16ms sleep after every inexpensive generator fragment.
        started=monotonic()
        while monotonic()-started<.008:
            if not self._advance_initialization_step():return
        self._initialization_timer.start(0)

    def _advance_initialization_step(self):
        try:
            if self._reconcile_steps is not None:
                try:
                    next(self._reconcile_steps)
                except StopIteration:
                    self._reconcile_steps = None
            elif self._initializing_documents:
                doc = self._initializing_documents[0]
                total=self._prepared_documents+len(self._initializing_documents)
                self.view.begin_transition(f'正在准备图形 {self._prepared_documents+1}/{total}…')
                doc._advance_inspector()
                doc._inspector_timer.stop()
                if not doc._inspector_initializing:
                    if hasattr(doc, "_inspector_error"):
                        raise RuntimeError(doc._inspector_error)
                    self._initializing_documents.pop(0)
                    self._prepared_documents+=1
            else:
                self.initializing = self.view.initializing = False
                for doc in self.panels.values():
                    self.install_context(doc)
                    self.bind_shared(doc)
                self.original_tabs.setEnabled(True)
                self.activate(self.cfg.get("active_node") or self.cfg["nodes"][0]["id"])
                self.refresh_unified()
                self.view.schedule(True)
                return False
        except Exception as error:
            import traceback
            traceback.print_exc()
            self.initializing = self.view.initializing = False
            self.view.last_error = str(error)
            self.original_tabs.setEnabled(True)
            self.view.finish_transition()
            self.owner.statusBar().showMessage("高级图形初始化失败：" + str(error))
            return False
        return True

    def reconcile(self):
        if self.initializing:
            return
        needs_documents = any(
            node["id"] not in self.panels
            or tuple((s.data_sheet.id, s.model.y_col) for s in self.source_documents(self.panels[node["id"]]))
            != tuple(tuple(ref) for ref in node["refs"])
            for node in self.cfg["nodes"]
        )
        if self.view.deferred_documents and needs_documents:
            self.initializing = self.view.initializing = True
            self._prepared_documents=0
            self.view.begin_transition('正在创建高级图形…')
            self.original_tabs.setEnabled(False)
            self._reconcile_steps = self._reconcile_sections()
            self._initialization_timer.start(16)
        else:
            for _ in self._reconcile_sections():
                pass

    def _reconcile_sections(self):
        from tailor.multiplot_tab import MultiPlotTab
        from tailor.project_files import load_multiplot
        from tailor.project_models import MultiPlot

        self.loading = True
        try:
            self.ensure_nodes()
            for node in self.cfg["nodes"]:
                if node["id"] in self.panels:
                    current = self.panels[node["id"]]
                    existing = tuple(
                        (s.data_sheet.id, s.model.y_col)
                        for s in self.source_documents(current)
                    )
                    wanted = tuple(tuple(ref) for ref in node["refs"])
                    if existing == wanted:
                        continue
                    self.versions[(node["id"], existing)] = current
                    self.figures[node["id"]].hide()
                    self.figures[node["id"]].setParent(self.parked)
                    del self.panels[node["id"]]
                    self.active = None
                    cached = self.versions.get((node["id"], wanted))
                    if cached is not None:
                        self.panels[node["id"]] = cached
                        figure = cached.ui.plot_widget.parentWidget()
                        figure.setParent(self.canvas)
                        self.figures[node["id"]] = figure
                        figure.show()
                        continue
                saved_sources = node.get("sources", [])
                sources = []
                for ref in node["refs"]:
                    saved = next(
                        (
                            s
                            for s in saved_sources
                            if s["data_sheet_id"] == ref[0] and s["y_col"] == ref[1]
                        ),
                        None,
                    )
                    sources.append(self.new_source(node, tuple(ref), saved))
                    yield
                if len(sources) == 1:
                    doc = sources[0]
                    if node.get("overlay"):
                        from tailor.curve_style import CurveStyle

                        saved = node["overlay"]
                        info = next(
                            (i for i in saved["plots"] if i["plot_id"] == doc.id), None
                        )
                        if info and info.get("style"):
                            doc.apply_curve_style(
                                CurveStyle(**info["style"]), dirty=False
                            )
                        doc.presentation.load(saved["graph_settings"])
                        doc.model.x_label, doc.model.y_label = (
                            saved["x_label"],
                            saved["y_label"],
                        )
                        if info:
                            doc.presentation.single_sides = {
                                "x": info.get("x_axis", "bottom"),
                                "y": info.get("axis", "left"),
                            }
                elif node.get("overlay"):
                    overlay = copy.deepcopy(node["overlay"])
                    source_by_id = {d.id: d for d in sources}
                    overlay["plots"] = [
                        info
                        for info in overlay["plots"]
                        if info["plot_id"] in source_by_id
                    ]
                    doc = load_multiplot(
                        self.owner,
                        MultiPlot.model_validate(overlay),
                        source_by_id,
                    )
                    for source in sources:
                        if not doc.model.uses_plot(source):
                            doc.add_plot(source)
                    doc.model._plots = {
                        source: doc.model.get_plot_info(source) for source in sources
                    }
                else:
                    self.owner._plot_num += 1
                    doc = MultiPlotTab(
                        self.owner,
                        "子图",
                        self.owner._plot_num,
                        sources[0].model.x_label,
                        sources[0].model.y_label,
                        defer_inspector=self.view.deferred_documents,
                    )
                    for source in sources:
                        doc.add_plot(source)
                    self.queue_inspector(doc)
                doc._embedded_parent, doc._panel_id = self.root, node["id"]
                if self.cfg['kind'] == 'bar':
                    doc.ui.plot_widget.hide()
                if (
                    doc.presentation.multi
                    and node.get("template_overlay")
                    and not node.get("overlay")
                ):
                    from tailor.curve_style import CurveStyle

                    fmt = node["template_overlay"]
                    doc.presentation.load(copy.deepcopy(fmt["graph_settings"]))
                    doc.model.x_label, doc.model.y_label = (
                        fmt["x_label"],
                        fmt["y_label"],
                    )
                    doc.curve_style = CurveStyle(**fmt["curve_style"])
                doc.setParent(self.parked)
                doc.hide()
                if doc.presentation.multi:
                    doc._advanced_gate = ActivatePanel(self, node, doc)
                    self.gates.append(doc._advanced_gate)
                self.panels[node["id"]] = doc
                figure = doc.ui.plot_widget.parentWidget()
                if self.cfg['kind'] == 'panels':
                    # In small panels, label fitting can alternate between no
                    # labels (zero width) and a full label column. Keep the
                    # measured space so painting cannot resize itself forever.
                    for axis in doc.ui.plot_widget.getPlotItem().axes.values():
                        axis['item'].setStyle(autoReduceTextSpace=False)
                figure.setParent(self.canvas)
                figure.show()
                self.figures[node["id"]] = figure
                if not self.initializing:
                    self.install_context(doc)
                    self.bind_shared(doc)
                if doc.presentation.multi:
                    doc.refresh_ui()
                yield
            live = {n["id"] for n in self.cfg["nodes"]}
            for key, figure in self.figures.items():
                figure.setVisible(key in live)
        finally:
            self.loading = False
        wanted = self.cfg.get("active_node")
        self.activate(
            wanted
            if wanted in {n["id"] for n in self.cfg["nodes"]}
            else self.cfg["nodes"][0]["id"]
        )
        self.place()
        if not self.initializing:
            self.refresh_unified()

    def current(self):
        return self.panels.get(self.active)

    def source_documents(self, doc):
        return list(doc.model._plots) if doc.presentation.multi else [doc]

    def install_context(self, doc):
        if getattr(doc, "_panel_context_ready", False):
            return
        doc._panel_context_ready = True
        doc._panel_choices = []
        axes = doc.axis_controls
        from tailor.panel_scope import add_card
        if self.cfg['kind']=='panels':
            add_card(self,axes,axis=True)
            add_card(self,doc.preferences.graph)
        else:
            axes._panel_card=QtWidgets.QFrame(axes);axes._panel_card.hide()
        from tailor.advanced_plotting import restrict_advanced
        restrict_advanced(doc)
        doc._unified_edit = QtWidgets.QPushButton("编辑整图统一图例")

        def edit_unified():
            first = self.cfg["nodes"][0]["id"]
            self.activate(first)
            from tailor.text_style_controls import reveal_section

            reveal_section(
                self.panels[first], self.panels[first].preferences.graph, "图例"
            )

        doc._unified_edit.clicked.connect(edit_unified)
        doc.preferences.graph.open_layout.insertWidget(0, doc._unified_edit)
        doc._unified_edit.hide()
        # Finish any local legend rebuild before Qt paints, so merged legends
        # cannot flash back to independent legends for a queued frame.
        for name in ('refresh_legend','refresh_labels','draw_plot'):
            old=getattr(doc,name,None)
            if old is None:continue
            def rebuild(*args,old=old,**kwargs):
                result=old(*args,**kwargs)
                if self.cfg.get('unified_legend'):self.refresh_unified()
                return result
            setattr(doc,name,rebuild)
        for name in ('apply_axes','apply_legend'):
            old=getattr(doc.presentation,name)
            def apply(*args,old=old,name=name,doc=doc,**kwargs):
                result=old(*args,**kwargs)
                if name=='apply_legend' and not self.loading and self.cfg.get('unified_legend') and self.live():
                    if doc is not self.live()[0]:doc.presentation.legend_item.hide()
                    elif not self.syncing:self.refresh_unified()
                self.changed()
                return result
            setattr(doc.presentation,name,apply)

    def activate(self, key):
        if hasattr(self.root,"_main_inspector_state"):
            from tailor.graph_focus import restore_main
            restore_main(self.root)
        if key not in self.panels:
            return
        if self.owner.data_operation_busy() and self.active not in {None, key}:
            self.owner.statusBar().showMessage("计算中暂不切换子图，避免改变操作对象。")
            return
        doc = self.panels[key]
        if self.initializing:
            self.active = key
            self.cfg["active_node"] = key
            return
        if self.active == key and self.root.preferences is doc.preferences:
            return
        old = self.current()
        if old and self.root.preferences is not old.preferences:
            old = None
        old_page = old.preferences.currentIndex() if old else 0
        title = (
            old.property_tabs.tabText(old.property_tabs.currentIndex())
            if old
            else "高级"
        )
        self.active = key
        self.cfg["active_node"] = key
        advanced = self.root.advanced_controls
        # The same advanced widget travels between native inspectors.
        for tabs in [
            self.original_tabs,
            *[d.property_tabs for d in self.panels.values()],
        ]:
            index = tabs.indexOf(advanced)
            if index >= 0:
                tabs.removeTab(index)
        existing = next(
            (
                i
                for i in range(doc.property_tabs.count())
                if doc.property_tabs.tabText(i) == "高级"
            ),
            -1,
        )
        if existing >= 0:
            old_advanced = doc.property_tabs.widget(existing)
            doc.property_tabs.removeTab(existing)
            old_advanced.setParent(self.parked)
            old_advanced.hide()
        doc.property_tabs.insertTab(
            doc.property_tabs.indexOf(doc.processing_controls) + 1, advanced, "高级"
        )
        from tailor.inspector_slots import InspectorSlot, show
        sizes = self.splitter.sizes()
        for slot, widget in ((1, doc.quick_actions), (2, doc.preferences)):
            if isinstance(self.splitter.widget(slot), InspectorSlot):
                show(self.splitter, slot, widget)
            elif self.splitter.widget(slot) is not widget:
                removed = self.splitter.replaceWidget(slot, widget)
                if removed:
                    removed.hide()
                    removed.setParent(self.parked)
                widget.show()
        self.splitter.setSizes(sizes)
        for name in (
            "property_tabs",
            "preferences",
            "quick_actions",
            "axis_controls",
            "legend_controls",
            "processing_controls",
            "point_inspector",
            "error_controls",
        ):
            setattr(self.root, name, getattr(doc, name))
        self.root._active_document = doc
        for child in self.panels.values():
            for box in getattr(child, "_panel_choices", []):
                with QtCore.QSignalBlocker(box):
                    box.clear()
                    for i, node in enumerate(self.cfg["nodes"]):
                        box.addItem(
                            f"子图{i + 1} · " + self.panels[node["id"]].name, node["id"]
                        )
                    box.setCurrentIndex(max(0, box.findData(key)))
        for page in (doc.axis_controls,doc.preferences.graph):
            if hasattr(page,'_panel_chips'):
                page._panel_chips.set_items([f'子图{i+1}' for i in range(len(self.cfg['nodes']))],
                    next(i for i,n in enumerate(self.cfg['nodes']) if n['id']==key))
        index = next(
            (
                i
                for i in range(doc.property_tabs.count())
                if doc.property_tabs.tabText(i) == title
            ),
            0,
        )
        doc.property_tabs.setCurrentIndex(index)
        doc.preferences.setCurrentIndex(old_page)
        self.place()
        self.owner._refresh_feature_menus()
        if hasattr(advanced, "refresh_panel_layout"):
            advanced.refresh_panel_layout()

    def place(self):
        if not self.canvas or self.canvas.width() < 1:
            return
        self.canvas.setBackground("#000000" if self.view.dark else "#ffffff")
        cols = 1 if self.cfg['kind']=='bar' else max(1, int(self.cfg.get("columns", 2)))
        rows = max(
            int(self.cfg.get("rows", 1)), math.ceil(len(self.cfg["nodes"]) / cols)
        )
        for i, node in enumerate(self.cfg["nodes"]):
            doc = self.panels.get(node["id"])
            if doc is None:
                continue
            r, c = divmod(i, cols)
            rect = ([0,0,100,100] if self.cfg['kind']=='bar' else node.get("rect")) or [
                100 * c / cols,
                100 * r / rows,
                100 / cols,
                100 / rows,
            ]
            x, y, w, h = rect
            figure = self.figures[node["id"]]
            figure.setGeometry(
                round(x * self.canvas.width() / 100),
                round(y * self.canvas.height() / 100),
                max(60, round(w * self.canvas.width() / 100)),
                max(60, round(h * self.canvas.height() / 100)),
            )
            figure.show()
            item = doc.ui.plot_widget.getPlotItem()
            item.setTitle(
                f"({chr(97 + i) if i < 26 else i + 1})"
                if self.cfg["kind"]=="panels" and self.cfg.get("numbering", True)
                else ""
            )
        self.canvas.update()

    def bind_shared(self, doc):
        if getattr(doc, "_panel_range_connections", False):
            return
        doc._panel_range_connections = True
        view = doc.ui.plot_widget.getViewBox()
        view.sigXRangeChanged.connect(
            lambda source, limits: self.sync_ranges(doc, limits, 0)
        )
        view.sigYRangeChanged.connect(
            lambda source, limits: self.sync_ranges(doc, limits, 1)
        )

    def sync_ranges(self, source, limits, dim):
        if (
            self.syncing
            or self.loading
            or not self.cfg.get("share_x" if dim == 0 else "share_y")
        ):
            return
        self.syncing = True
        try:
            for doc in self.live():
                if doc is not source:
                    box = doc.ui.plot_widget.getViewBox()
                    (box.setXRange if dim == 0 else box.setYRange)(*limits, padding=0)
        finally:
            self.syncing = False

    def reset(self):
        self.resetting = True
        self.syncing = True
        bounds = [[], []]
        try:
            for doc in self.live():
                if self.cfg["kind"] != "bar":
                    doc.quick_actions.reset_view()
                else:
                    doc._clear_remembered_zoom()
                if self.cfg["kind"] == "bar":
                    self.bars()
                    boxes = {box for box, _item in self.bar_items}
                    for box in boxes:
                        box.autoRange(
                            items=[
                                item for target, item in self.bar_items if target is box
                            ],
                            padding=0.05,
                        )
                        # Data changes request a bounds refresh, not permission
                        # to discard explicit ranges on the displayed axes.
                        for dimension,key,holder in (
                            (0,'top' if box is doc.presentation.top_box or box is doc.presentation.top_right_box else 'x',None),
                            (1,'right' if box is doc.presentation.right_box or box is doc.presentation.top_right_box else 'y',None)):
                            holder=doc.presentation if key in {'top','right'} else doc.model
                            limits=[getattr(holder,key+'_min'),getattr(holder,key+'_max')]
                            if any(v is not None for v in limits):
                                current=box.viewRange()[dimension]
                                values=[v if v is not None else current[i] for i,v in enumerate(limits)]
                                from tailor.graph_presentation import display
                                (box.setXRange if dimension==0 else box.setYRange)(*display(values,doc.presentation.axes[key]),padding=0)
                for dim in (0, 1):
                    bounds[dim].extend(doc.ui.plot_widget.viewRange()[dim])
            for dim, key in ((0, "share_x"), (1, "share_y")):
                if self.cfg.get(key) and bounds[dim]:
                    for doc in self.panels.values():
                        (
                            doc.ui.plot_widget.setXRange
                            if dim == 0
                            else doc.ui.plot_widget.setYRange
                        )(min(bounds[dim]), max(bounds[dim]), padding=0)
        finally:
            self.syncing = False
            self.resetting = False
        self.refresh_unified()

    def changed(self, *args):
        if self.loading or self.syncing or self.initializing or self.view.rendering:
            return
        self.legend_timer.start()
        if self.cfg["kind"] == "bar" or self.cfg["kind"] == "3d":
            self.view.schedule()
        self.owner.mark_project_dirty()

    def snapshot(self):
        from tailor.project_files import save_multiplot, save_plot

        for node in self.cfg["nodes"]:
            doc = self.panels.get(node["id"])
            if doc is None:
                continue
            sources = self.source_documents(doc)
            node["sources"] = [save_plot(s).model_dump() for s in sources]
            if doc.presentation.multi:
                node["overlay"] = save_multiplot(doc).model_dump()
            else:
                node.pop("overlay", None)
        return copy.deepcopy(self.cfg)

    def record(self, before, title):
        from tailor.text_style_controls import record_view_edit

        after = self.snapshot()

        def restore(root, state):
            root.advanced_view.cfg = copy.deepcopy(state)
            root.presentation.extra_settings["advanced"] = root.advanced_view.cfg
            self.cfg = root.advanced_view.cfg
            self.reconcile()
            from tailor.curve_style import CurveStyle

            for node in self.cfg["nodes"]:
                doc = self.panels[node["id"]]
                for source in self.source_documents(doc):
                    saved = next(
                        (v for v in node.get("sources", []) if v["id"] == source.id),
                        None,
                    )
                    if saved:
                        for name in (
                            "x_label",
                            "y_label",
                            "x_min",
                            "x_max",
                            "y_min",
                            "y_max",
                        ):
                            setattr(source.model, name, saved[name])
                        source.presentation.load(saved["graph_settings"])
                        source.apply_curve_style(
                            CurveStyle(**saved["curve_style"]), dirty=False
                        )
                        source.annotations.load(saved["annotations"])
                        source.refresh_ui()
                if doc.presentation.multi and node.get("overlay"):
                    doc.presentation.load(node["overlay"]["graph_settings"])
                    doc.curve_style = CurveStyle(**node["overlay"]["curve_style"])
                    for info in node["overlay"]["plots"]:
                        source = next(
                            s for s in doc.model._plots if s.id == info["plot_id"]
                        )
                        target = doc.model.get_plot_info(source)
                        target.style = copy.deepcopy(info["style"])
                        target.color = info["color"]
                    doc.refresh_ui()
            self.view.schedule()

        record_view_edit(self.root, title, before, after, restore)
        self.owner.mark_project_dirty()

    def layout(self, key, rect, slot="custom"):
        if (
            len(rect) != 4
            or not all(np.isfinite(rect))
            or min(rect[:2]) < 0
            or min(rect[2:]) <= 0
            or rect[0] + rect[2] > 100.00001
            or rect[1] + rect[3] > 100.00001
        ):
            raise ValueError(
                "位置尺寸以画布百分比计；宽高须为正，子图须位于0～100%画布内。"
            )
        before = self.snapshot()
        from tailor.panel_controls import set_position
        set_position(self.cfg["nodes"],key,rect,slot,self.cfg.get("rows",1),self.cfg.get("columns",2))
        self.place()
        self.record(before, "子图位置与尺寸")

    def close(self):
        from tailor.curve_controls import dispose_graph

        self.loading=True

        self.legend_timer.stop()
        self._initialization_timer.stop()
        self._reconcile_steps = None
        self._initializing_documents.clear()
        for doc in list(
            dict.fromkeys(
                [*self.panels.values(), *self.versions.values(), *self.sources.values()]
            )
        ):
            dispose_graph(doc)
            doc.deleteLater()

    def bars(self):
        """Only bar placement differs; axes/legend/styles/errors remain native."""
        from dataclasses import replace

        from tailor.advanced_plotting import COLORS,percent_values
        from tailor.curve_style import CurveStyle
        from tailor.graph_presentation import display
        from tailor.line_styles import curve_pen

        for box, item in getattr(self, "bar_items", []):
            box.removeItem(item)
        self.bar_items = []
        doc = self.current()
        sources = self.source_documents(doc)
        node=next(n for n in self.cfg['nodes'] if n['id']==self.active)
        input_modes=node.setdefault('bar_input_modes',{})
        dataset = []
        for index, source in enumerate(sources):
            if self.cfg.get('bar_x_ref'):
                source.model.x_col = self.cfg['bar_x_ref'][1]
            series = next((s for s in self.cfg.get('bar_series', [])
                           if tuple(s['ref']) == (source.data_sheet.id, source.model.y_col)), None)
            if 'bar_series' in self.cfg:
                source.model.y_err_col = series.get('error') if series else None
            # Horizontal category axes change display orientation, not how
            # original X/Y columns are parsed, including after project reload.
            modes=input_modes.setdefault(source.model.y_col,dict(source.model._axis_modes))
            source.model._axis_modes=dict(modes)
            cache_key = (
                self.view.data_epoch,
                source.model.x_col,
                source.model.y_col,
                source.model.x_err_col,
                source.model.y_err_col,
            )
            if getattr(source, "_bar_frame_key", None) != cache_key:
                source._bar_frame = source.model._get_data_as_dataframe()
                source._bar_frame_key = cache_key
            frame = source._bar_frame
            if source.model.y_err_col and (frame.y_err < 0).any():
                raise ValueError("误差列不能包含负值。")
            info = doc.model.get_plot_info(source) if doc.presentation.multi else None
            style = (
                CurveStyle(**info.style) if info and info.style else source.curve_style
            )
            if not getattr(source, "_bar_initialized", False) and style.mode != "bar":
                style = replace(
                    style, mode="bar", fill=True, fill_color=COLORS[index % len(COLORS)]
                )
                source.curve_style = style
                if info:
                    info.style = style.to_dict()
                source._bar_initialized = True
            requested = series.get('color') if series else None
            applied = node.setdefault('bar_colors', {})
            if requested and applied.get(source.model.y_col) != requested:
                style = replace(style, color=requested, fill=True, fill_color=requested)
                source.curve_style = style
                if info:
                    info.style = style.to_dict(); info.color = requested
                applied[source.model.y_col] = requested
            dataset.append((source, frame, style, info))
        if not dataset:
            return
        x = dataset[0][1].x.to_numpy()
        if any(not np.array_equal(v[1].x.to_numpy(), x) for v in dataset):
            raise ValueError("柱状图各系列X需相同，不会隐式按行错配。")
        values = np.stack([v[1].y.to_numpy() for v in dataset])
        mode = self.cfg.get("bar_mode", "grouped")
        if mode == "percent":
            values = percent_values(values)
        step = np.diff(np.unique(x))
        interval = np.median(step[step > 0]) if np.any(step > 0) else 1.0
        total = float(self.cfg.get("width", 0.8)) * interval
        gap = float(self.cfg.get("bar_gap", 0.1))
        baseline = float(self.cfg.get("baseline", 0))
        positive = np.full(len(x), baseline)
        negative = positive.copy()
        horizontal = self.cfg.get("horizontal", False)
        category_axis='y' if horizontal else 'x'
        value_axis='x' if horizontal else 'y'
        mode=sources[0].model._axis_modes.get('x','numeric')
        if node.get('bar_horizontal')!=horizontal:
            doc.presentation.axes[category_axis]['axis_type']=mode
            doc.presentation.axes[value_axis]['axis_type']='numeric'
            node['bar_horizontal']=horizontal
        doc.presentation.axes[category_axis]['category_labels']=sources[0].model._axis_categories.get('x',[])
        doc.presentation.axes[value_axis]['category_labels']=[]
        mode = self.cfg.get("bar_mode", "grouped")
        for index, (source, frame, style, info) in enumerate(dataset):
            raw = doc._series[source]["data"] if info else doc.plot
            source._advanced_bar = True
            raw._advanced_bar_visible=bool(style.visible and (info is None or info.visible))
            raw.setSymbol(None)
            raw.hide()
            errors = doc._series[source].get("errors") if info else doc.error_items
            if errors:
                errors.x.hide()
                errors.y.hide()
            if not style.visible or info and not info.visible:
                continue
            y = values[index]
            if mode == "grouped":
                span = total / len(dataset) * (1 - gap)
                center = x - total / 2 + total / len(dataset) * (index + 0.5)
                base = np.full(len(x), baseline)
            else:
                span = total * (1 - gap)
                center = x
                base = np.where(y >= 0, positive, negative).copy()
                positive += np.where(y >= 0, y, 0)
                negative += np.where(y < 0, y, 0)
            xaxis = "top" if info and info.x_axis == "top" else "x"
            yaxis = "right" if info and info.axis == "right" else "y"
            box = (
                doc.presentation.box_for(info)
                if info
                else doc.ui.plot_widget.getViewBox()
            )
            lo, hi = (
                (base, base + y)
                if horizontal
                else (center - span / 2, center + span / 2)
            )
            bottom, top = (
                (center - span / 2, center + span / 2)
                if horizontal
                else (base, base + y)
            )
            if (
                doc.presentation.axes[xaxis]["log"]
                and (np.any(lo <= 0) or np.any(hi <= 0))
                or doc.presentation.axes[yaxis]["log"]
                and (np.any(bottom <= 0) or np.any(top <= 0))
            ):
                raise ValueError("对数柱图的端点须为正；请设置正基线或使用线性轴。")
            lo, hi = (
                display(lo, doc.presentation.axes[xaxis]),
                display(hi, doc.presentation.axes[xaxis]),
            )
            bottom, top = (
                display(bottom, doc.presentation.axes[yaxis]),
                display(top, doc.presentation.axes[yaxis]),
            )
            brush = pg.mkColor(style.fill_color)
            brush.setAlphaF(style.opacity)
            pen = curve_pen(style.color, style.line_width, style.line_style)
            raw._curve_legend_options={'pen':None,'symbol':'s','symbolSize':14,
                'symbolPen':pen,'symbolBrush':pg.mkBrush(brush) if style.fill else None}
            from tailor.dense_bars import DenseBars
            bar = DenseBars(
                horizontal=horizontal,                x0=np.minimum(lo, hi),
                x1=np.maximum(lo, hi),
                y0=np.minimum(bottom, top),
                y1=np.maximum(bottom, top),
                pen=pen,
                brush=brush if style.fill else None,
            )

            def choose(event, source=source, doc=doc):
                self.activate(doc._panel_id)
                doc.preferences.select_curve("data", source, event.double())
                event.accept()

            bar.mouseClickEvent = choose
            bar.setCacheMode(QtWidgets.QGraphicsItem.DeviceCoordinateCache)
            box.addItem(bar)
            self.bar_items.append((box, bar))
            if (
                self.cfg.get("errors", True)
                and np.any(frame.y_err.to_numpy() > 0)
            ):
                e = np.asarray(frame.y_err.to_numpy(), dtype=float)
                if mode == 'percent':
                    # Plot absolute input errors in the normalized ordinate's
                    # units; no invented statistical propagation of the sum.
                    scale = np.max(np.abs(np.stack([v[1].y.to_numpy() for v in dataset])), axis=0)
                    normalized = np.divide(np.stack([v[1].y.to_numpy() for v in dataset]), scale,
                                           out=np.zeros_like(values), where=scale > 0)
                    total = np.where(frame.y.to_numpy() >= 0, np.maximum(normalized, 0).sum(axis=0),
                                     np.maximum(-normalized, 0).sum(axis=0))
                    e = np.divide(np.divide(e, scale, out=np.zeros_like(e), where=scale > 0) * 100,
                                  total, out=np.zeros_like(e), where=total > 0)
                if (
                    not doc.presentation.axes[xaxis]["log"]
                    and not doc.presentation.axes[yaxis]["log"]
                ):
                    opts = (
                        {"x": base + y, "y": center, "left": e, "right": e}
                        if horizontal
                        else {"x": center, "y": base + y, "top": e, "bottom": e}
                    )
                    err = pg.ErrorBarItem(**opts, pen=pen, beam=span / 3)
                    box.addItem(err)
                    self.bar_items.append((box, err))

        from tailor.preference_pages import apply_legend_samples
        before_loading = self.loading
        self.loading = True
        try:
            doc.presentation.apply_legend()
        finally:
            self.loading = before_loading
        apply_legend_samples(doc)
        doc.ui.plot_widget.show()

    def add_curves(self, refs):
        from tailor.multiplot_tab import MultiPlotTab

        node = next(n for n in self.cfg["nodes"] if n["id"] == self.active)
        fresh = [
            tuple(r) for r in refs if tuple(r) not in [tuple(a) for a in node["refs"]]
        ]
        if not fresh:
            return
        before = self.snapshot()
        old = self.current()
        sources = self.source_documents(old)
        signature = tuple((s.data_sheet.id, s.model.y_col) for s in sources)
        self.versions[(node["id"], signature)] = old
        added = [self.new_source(node, ref) for ref in fresh]
        if old.presentation.multi:
            doc = old
            for source in added:
                doc.add_plot(source)
        else:
            self.owner._plot_num += 1
            doc = MultiPlotTab(
                self.owner,
                "子图",
                self.owner._plot_num,
                old.model.x_label,
                old.model.y_label,
            )
            for source in [*sources, *added]:
                doc.add_plot(source)
            doc._embedded_parent, doc._panel_id = self.root, node["id"]
            doc.setParent(self.parked)
            doc.hide()
            self.figures[node["id"]].hide()
            self.figures[node["id"]].setParent(self.parked)
            self.panels[node["id"]] = doc
            figure = doc.ui.plot_widget.parentWidget()
            figure.setParent(self.canvas)
            figure.show()
            self.figures[node["id"]] = figure
            doc._advanced_gate = ActivatePanel(self, node, doc)
            self.gates.append(doc._advanced_gate)
            self.install_context(doc)
            self.bind_shared(doc)
        node["refs"].extend(fresh)
        self.activate(node["id"])
        doc.refresh_ui()
        self.place()
        self.record(before, "向子图添加曲线")

    def live(self):
        return [
            self.panels[n["id"]] for n in self.cfg["nodes"] if n["id"] in self.panels
        ]

    def refresh_unified(self):
        if self.loading or self.syncing or self.initializing:
            return
        docs = self.live()
        if not docs:
            return
        self.syncing = True
        try:
            unified = self.cfg.get("unified_legend", False) and len(docs) > 1
            for node in self.cfg["nodes"]:
                doc = self.panels[node["id"]]
                if not getattr(doc,"_using_global_legend",False):
                    node["local_legend"] = copy.deepcopy(doc.presentation.legend)
                content = next(
                    r
                    for r in doc.preferences.graph.sections
                    if r[1].property("sectionTitle") == "图例"
                )
                content[3].setEnabled(not unified or doc is docs[0])
                doc._unified_edit.setVisible(unified and doc is not docs[0])
                if not unified:
                    if getattr(doc, "_using_global_legend", False):
                        doc.presentation.legend = copy.deepcopy(node["local_legend"])
                        doc._using_global_legend = False
                        doc.presentation._hidden_legend_rows={}
                        doc.refresh_legend() if not doc.presentation.multi else doc.draw_plot()
                    elif getattr(doc,"_merge_hidden",False):doc.presentation.apply_legend()
                    doc._merge_hidden=False
                    continue
                if doc is not docs[0]:
                    doc._merge_hidden=True
                    doc.presentation.legend_item.hide()
            if unified:
                from tailor.text_style_controls import apply_text_styles

                first = docs[0]
                p = first.presentation
                if getattr(first, "_using_global_legend", False):
                    self.cfg["global_legend"] = p.legend
                if not getattr(first,"_using_global_legend",False):p._hidden_legend_rows={}
                p.legend = self.cfg.setdefault("global_legend", copy.deepcopy(p.legend))
                first._using_global_legend = True
                legend = p.legend_item
                legend.clear()
                self.legend_proxies = []
                for node in self.cfg["nodes"]:
                    doc = self.panels[node["id"]]
                    for source in self.source_documents(doc):
                        item = (
                            doc._series[source]["data"]
                            if doc.presentation.multi
                            else source.plot
                        )
                        key = f"panel:{node['id']}:plot:{source.id}:data"
                        visible=doc.model.get_plot_info(source).visible if doc.presentation.multi else source.curve_style.visible
                        if not visible:
                            continue
                        proxy = pg.PlotDataItem(
                            [],
                            [],
                            **{
                                k: v
                                for k, v in item.opts.items()
                                if k
                                in {
                                    "pen",
                                    "symbol",
                                    "symbolSize",
                                    "symbolPen",
                                    "symbolBrush",
                                }
                            },
                        )
                        proxy._legend_key = key
                        self.legend_proxies.append(proxy)
                        legend.addItem(
                            proxy,
                            source.model.legend_label or __import__('tailor.column_titles',fromlist=['remark']).remark(source.data_sheet.model,source.model.y_col),
                        )
                        fit = (
                            doc._series[source]["fit"]
                            if doc.presentation.multi
                            else source.fit_plot
                        )
                        if fit.isVisible() and fit.yData is not None and len(fit.yData):
                            proxy = pg.PlotDataItem(pen=fit.opts.get("pen"))
                            proxy._legend_key = (
                                f"panel:{node['id']}:plot:{source.id}:fit"
                            )
                            self.legend_proxies.append(proxy)
                            legend.addItem(
                                proxy,
                                (
                                    source.model.legend_label
                                    or source.model.get_y_col_name()
                                )
                                + " 拟合",
                            )
                p.apply_legend()
                apply_text_styles(first)
                first.legend_controls.refresh_entries()
        finally:
            self.syncing = False


def show_document(owner, doc):
    parent = getattr(doc, "_embedded_parent", None)
    if parent:
        owner.ui.tabWidget.setCurrentWidget(parent)
        parent.advanced_view.native.activate(doc._panel_id)
    else:
        owner.ui.tabWidget.setCurrentWidget(doc)

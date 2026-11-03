"""Graph-only MDI adapter over Qt's existing windows and shared splitters.

Only figure widgets move: document identity, inspectors, selections and export
continue to belong to the original PlotTab/MultiPlotTab.
"""

from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import isValid
from tailor.crash_diagnostics import valid_event


def graph(doc):
    from tailor.multiplot_tab import MultiPlotTab
    from tailor.plot_tab import PlotTab

    return isinstance(doc, (PlotTab, MultiPlotTab)) and getattr(doc, "advanced_view", None) is None and not getattr(getattr(doc,"presentation",None),"extra_settings",{}).get("advanced") and not getattr(doc.main_window,"_creating_advanced",False)


def key(doc):
    return ("multiplot_" if hasattr(doc, "_series") else "plot_") + str(doc.id)


class GraphWindow(QtWidgets.QMdiSubWindow):
    def __init__(self, control, doc):
        super().__init__()
        self.control, self.doc = control, doc
        self.drag_offset = None
        self.slot = None
        self._layout_before = None
        self.setWindowFlags(QtCore.Qt.SubWindow | QtCore.Qt.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)
        self.setMinimumSize(160, 120)
        self.body = QtWidgets.QFrame()
        self.body.setObjectName("curveGraphWindow")
        self.body.setStyleSheet(
            "QFrame#curveGraphWindow {border:1px solid #b9c5d2;border-radius:10px;background:palette(base);}"
        )
        self.setStyleSheet("QMdiSubWindow {border:0;background:transparent;}")
        layout = QtWidgets.QVBoxLayout(self.body)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        self.title = QtWidgets.QWidget()
        self.title.setFixedHeight(30)
        self.title.installEventFilter(self)
        bar = QtWidgets.QHBoxLayout(self.title)
        bar.setContentsMargins(10, 0, 4, 0)
        self.label = QtWidgets.QLabel(doc.name)
        self.label.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.label.setAlignment(QtCore.Qt.AlignCenter)
        minimize = QtWidgets.QToolButton()
        from tailor.ui_theme import action_icon
        minimize.setIcon(action_icon("minus", minimize, "#795211"))
        minimize.setIconSize(QtCore.QSize(10, 10))
        minimize.setFixedSize(15, 15)
        minimize.setStyleSheet(
            "QToolButton {background:#ffbd2e;border:1px solid #dfa121;border-radius:7px;min-height:0;padding:0;color:#795211;font-size:12px;} QToolButton:hover {background:#ffd266;}"
        )
        minimize.setToolTip("收起窗口；点击图表标签再次展开")
        minimize.clicked.connect(lambda: control.minimize(self))
        bar.addWidget(minimize)
        bar.addWidget(self.label, 1)
        bar.addSpacing(15)
        layout.addWidget(self.title)
        from tailor.resize_handles import ResizeGrip

        self.grip = ResizeGrip(self.body)
        super().setWidget(self.body)

    def set_figure(self, figure):
        self.body.layout().addWidget(figure, 1)
        self.grip.raise_()

    def eventFilter(self, obj, event):
        # Qt can invoke the virtual filter from QMdiSubWindow construction,
        # before our custom title exists (notably with Qt 6.11).
        if obj is getattr(self, 'title', None):
            if event.type() == QtCore.QEvent.MouseButtonPress:
                self.mousePressEvent(event)
                return True
            if event.type() == QtCore.QEvent.MouseMove:
                self.mouseMoveEvent(event)
                return True
            if event.type() == QtCore.QEvent.MouseButtonRelease:
                self.mouseReleaseEvent(event)
                return True
        return False

    def closeEvent(self, event):
        event.ignore()
        self.control.minimize(self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.grip.move(max(0, self.body.width() - 19), max(0, self.body.height() - 19))
        self.grip.raise_()
        path = QtGui.QPainterPath()
        path.addRoundedRect(QtCore.QRectF(self.body.rect()), 10, 10)
        self.body.setMask(QtGui.QRegion(path.toFillPolygon().toPolygon()))
        if self.control.enabled:
            self.control.dirty()

    def changeEvent(self, event):
        if event.type() == QtCore.QEvent.WindowStateChange and self.isMinimized():
            self.setWindowState(QtCore.Qt.WindowNoState)
            self.control.minimize(self)
        super().changeEvent(event)

    def mousePressEvent(self, event):
        p = event.position()
        title = 30
        if (
            event.button() == QtCore.Qt.LeftButton
            and 4 < p.y() < title
            and p.x() > 30
        ):
            self._layout_before = self.control.snapshot()
            self.control.activate(self)
            self.control.drag_hint.show()
            self.control.drag_hint.raise_()
            self.drag_offset = event.globalPosition().toPoint() - self.mapToGlobal(
                QtCore.QPoint()
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drag_offset is None:
            return super().mouseMoveEvent(event)
        if self.slot:
            self.control.undock(self)
        pos = self.control.area.viewport().mapFromGlobal(
            event.globalPosition().toPoint()
        )
        self.move(pos - self.drag_offset)
        if self.control.snap.isVisible() and pos.y()>105:
            self.control.snap.hide()
            self.control.drag_hint.show()
        elif self.control.drag_hint.rect().adjusted(-12,-4,12,12).contains(self.control.drag_hint.mapFromGlobal(event.globalPosition().toPoint())):
            self.control.show_snap()
        event.accept()

    def mouseReleaseEvent(self, event):
        if self.drag_offset is not None:
            self.drag_offset = None
            target = self.control.snap.childAt(
                self.control.snap.mapFromGlobal(event.globalPosition().toPoint())
            )
            slot = target.property("snapSlot") if target is not None else None
            self.control.snap.hide()
            self.control.drag_hint.hide()
            if slot:
                self.control.dock(self, slot)
            self.control.dirty()
            self.control.record_layout(self._layout_before, "移动图窗与分屏")
            self._layout_before = None
            event.accept()
            return
        super().mouseReleaseEvent(event)


class WindowMode(QtCore.QObject):
    def __init__(self, owner, button):
        super().__init__(owner)
        self.owner, self.button = owner, button
        self.enabled, self.busy = False, False
        self._pending_navigation = None
        self._navigation_timer = QtCore.QTimer(self)
        self._navigation_timer.setSingleShot(True)
        self._navigation_timer.timeout.connect(self._navigate)
        self.windows, self.figures, self.splitters = {}, {}, {}
        self.host = None
        self.park = QtWidgets.QWidget(owner)
        self.park.hide()
        self.area = QtWidgets.QMdiArea(self.park)
        self.area.setOption(QtWidgets.QMdiArea.DontMaximizeSubWindowOnActivation, True)
        self.area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.area.subWindowActivated.connect(self.activate)
        self.area.viewport().installEventFilter(self)
        self.area.installEventFilter(self)
        QtWidgets.QApplication.instance().installEventFilter(self)
        self.dock_host = None
        self.dock_layout = None
        self.rows = []
        self.root_split = None
        self.syncing = False
        self.snap = QtWidgets.QFrame(self.area)
        self.snap.setObjectName("windowSnapMenu")
        layout = QtWidgets.QHBoxLayout(self.snap)
        for slots in ((("L", "R"),), (("A", "B"), ("C", "D"))):
            diagram = QtWidgets.QFrame()
            diagram.setFixedSize(112, 66)
            grid = QtWidgets.QGridLayout(diagram)
            grid.setContentsMargins(3, 3, 3, 3)
            grid.setSpacing(3)
            diagram.setStyleSheet(
                "QFrame {border:1px solid #9baec4;border-radius:8px;} QPushButton {border:0;border-radius:4px;background:#dce7f3;padding:0;min-height:0;} QPushButton:hover {background:#579fe8;}"
            )
            for r, items in enumerate(slots):
                for c, slot in enumerate(items):
                    button = QtWidgets.QPushButton("")
                    button.setProperty("snapSlot", slot)
                    button.setSizePolicy(
                        QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
                    )
                    button.setToolTip(
                        {
                            "L": "左半屏",
                            "R": "右半屏",
                            "A": "左上",
                            "B": "右上",
                            "C": "左下",
                            "D": "右下",
                        }[slot]
                    )
                    grid.addWidget(button, r, c)
            layout.addWidget(diagram)
        self.drag_hint = QtWidgets.QLabel("拖到此处排列窗口", self.area)
        self.drag_hint.setAlignment(QtCore.Qt.AlignCenter)
        self.drag_hint.setFixedSize(176, 27)
        self.drag_hint.setStyleSheet(
            "background:#dceaff;color:#2169b0;border:1px dashed #579fe8;border-radius:12px;"
        )
        self.drag_hint.hide()
        self.snap.hide()
        self.button.setCheckable(True)
        self.button.setToolTip("窗口模式：多图窗口、拖到顶部快速排布")
        self.button.setAccessibleName("窗口模式")
        self.button.toggled.connect(self.toggle)
        owner.ui.tabWidget.currentChanged.connect(self.changed)
        owner.ui.tabWidget.tabBar().tabBarClicked.connect(self.clicked)
        self.changed()

    def record_layout(self, before, title):
        if before is None or self.busy or getattr(self, "_restoring_layout", False):
            return
        current = self.owner.ui.tabWidget.currentWidget()
        if not graph(current):
            return
        from tailor.text_style_controls import record_view_edit

        after = self.snapshot()

        def restore(plot, state):
            self._restoring_layout = True
            try:
                self.reset()
                self.restore(state)
            finally:
                self._restoring_layout = False

        record_view_edit(current, title, before, after, restore)

    def dirty(self):
        if not self.busy:
            self.owner.mark_project_dirty()

    def eventFilter(self, obj, event):
        if not valid_event(event, 'WindowMode'):
            return True
        kind = event.type()
        if kind not in (
            QtCore.QEvent.MouseButtonPress,
            QtCore.QEvent.MouseButtonRelease,
            QtCore.QEvent.Resize,
        ):
            return False
        if kind == QtCore.QEvent.MouseButtonPress and isValid(self.owner.ui.tabWidget) and obj is self.owner.ui.tabWidget.tabBar():
            # A real tab click supersedes an MDI activation queued while the
            # previous page was becoming visible. Log before Qt starts showing
            # its children: currentChanged is too late for a native show crash.
            self.cancel_navigation()
            self.trace('tab-press', index=obj.tabAt(event.position().toPoint()))
        resize_target = isinstance(
            obj, (QtWidgets.QSizeGrip, QtWidgets.QSplitterHandle)
        )
        if (
            self.enabled
            and resize_target
            and event.type() == QtCore.QEvent.MouseButtonPress
        ):
            self._resize_before = self.snapshot()
        if (
            event.type() == QtCore.QEvent.MouseButtonRelease
            and getattr(self, "_resize_before", None) is not None
        ):
            before = self._resize_before
            self._resize_before = None
            QtCore.QTimer.singleShot(
                0, self, lambda: self.record_layout(before, "图窗尺寸与分屏边界")
            )
        if (
            event.type() == QtCore.QEvent.MouseButtonPress
            and self.enabled
            and isinstance(obj, QtWidgets.QWidget)
        ):
            widget = obj
            while widget is not None:
                if isinstance(widget, GraphWindow) and widget.control is self:
                    self.activate(widget)
                    break
                widget = widget.parentWidget()
        if obj is self.area.viewport() and event.type() == QtCore.QEvent.Resize:
            if self.dock_host:
                self.dock_host.setGeometry(self.area.viewport().rect())
        if obj is self.area and event.type()==QtCore.QEvent.Resize:
            self.drag_hint.move(max(0,(self.area.width()-176)//2),5)
            self.snap.move(max(0,(self.area.width()-self.snap.width())//2),10)
        return False

    def show_snap(self):
        self.snap.adjustSize()
        self.snap.move(
            max(0, (self.area.width() - self.snap.width()) // 2), 10
        )
        self.drag_hint.hide()
        self.snap.show()
        self.snap.raise_()

    def changed(self, *args):
        if args:
            # A completed document change (including programmatic navigation)
            # takes precedence over activation from the page just hidden.
            self.cancel_navigation()
        doc = self.owner.ui.tabWidget.currentWidget()
        self.button.setEnabled(graph(doc))
        if (
            self.enabled
            and graph(doc)
            and not self.busy
            and (args or self.host is not doc or doc not in self.windows)
        ):
            self.request_navigation(doc)
        elif not graph(doc):
            self.cancel_navigation()
        for document, window in self.windows.items():
            window.setWindowTitle(document.name)
            window.label.setText(document.name)

    def clicked(self, index):
        doc = self.owner.ui.tabWidget.widget(index)
        if self.enabled and graph(doc):
            self.request_navigation(doc)

    def trace(self, action, **extra):
        from tailor.crash_diagnostics import breadcrumb
        doc = self.owner.ui.tabWidget.currentWidget()
        breadcrumb(action, document=type(doc).__name__, document_id=getattr(doc, 'id', None),
                   window_mode=self.enabled, busy=self.busy,
                   host_id=getattr(self.host, 'id', None), windows=len(self.windows), **extra)

    def cancel_navigation(self):
        self._navigation_timer.stop()
        self._pending_navigation = None

    def request_navigation(self, doc, select=False):
        if self.busy or not self.enabled or not isValid(doc):
            return
        # Do not let a routine inspector refresh cancel a user's pending click
        # on an MDI window. A new top-tab press explicitly cancels that request.
        pending = self._pending_navigation
        if pending and pending[1] and not select:
            return
        self._pending_navigation = (doc, select)
        self._navigation_timer.start(0)

    def _navigate(self):
        pending = self._pending_navigation
        self._pending_navigation = None
        if not pending or not self.enabled or self.busy:
            return
        doc, select = pending
        tabs = self.owner.ui.tabWidget
        if not isValid(doc) or tabs.indexOf(doc) < 0 or not graph(doc):
            return
        self.trace('navigation-start', target_id=doc.id, select=select)
        if select:
            tabs.setCurrentWidget(doc)
        if tabs.currentWidget() is doc:
            self.show(doc)
        # currentChanged can enqueue this same document during setCurrentWidget.
        if self._pending_navigation == (doc, False):
            self.cancel_navigation()
        self.trace('navigation-end')

    def toggle(self, checked):
        if self.busy:
            return
        self.cancel_navigation()
        self.enabled = checked
        self.trace('window-mode-toggle')
        with QtCore.QSignalBlocker(self.button):
            self.button.setChecked(checked)
        if checked:
            doc = self.owner.ui.tabWidget.currentWidget()
            if graph(doc):
                self.show(doc)
        else:
            self.restore_figures()
        self.dirty()

    def figure(self, doc):
        # In both ordinary and advanced graphs, the figure is splitter slot 0.
        if doc in self.figures:
            return self.figures[doc]
        host = doc.ui.plot_widget.parentWidget()
        splitter = host.parentWidget()
        if not isinstance(splitter, QtWidgets.QSplitter):
            raise TypeError("图形工作区缺少原生分隔器")
        self.figures[doc], self.splitters[doc] = host, splitter
        return host

    def show(self, doc):
        if self.busy or not isValid(doc) or not graph(doc):
            return
        self.busy = True
        try:
            old_sizes = (
                self.splitters[self.host].sizes()
                if self.host in self.splitters
                else None
            )
            inspector_width = (
                old_sizes[-1] if old_sizes and len(old_sizes) >= 3 else None
            )
            figure = self.figure(doc)
            splitter = self.splitters[doc]
            window = self.windows.get(doc)
            if window is None:
                window = GraphWindow(self, doc)
                self.windows[doc] = window
                self.area.addSubWindow(
                    window, QtCore.Qt.SubWindow | QtCore.Qt.FramelessWindowHint
                )
                window.set_figure(figure)
                window._needs_center = True
            if self.host is not doc:
                self.area.setParent(self.park)
                if splitter.count() and splitter.widget(0) is figure:
                    figure.setParent(window)
                splitter.insertWidget(0, self.area)
                self.host = doc
            self.area.show()
            if inspector_width is not None:
                room = splitter.width() - 2 * splitter.handleWidth()
                splitter.setSizes(
                    [max(160, room - 46 - inspector_width), 46, inspector_width]
                )
            if getattr(window, "_needs_center", False):
                size = self.area.viewport().size()
                width = min(size.width(), max(160, round(size.width() * 0.76)))
                height = min(size.height(), max(120, round(size.height() * 0.76)))
                window.resize(width, height)
                window.move((size.width() - width) // 2, (size.height() - height) // 2)
                window._needs_center = False
            window.setWindowTitle(doc.name)
            window.label.setText(doc.name)
            window.show()
            view = getattr(doc, "advanced_view", None)
            if view and view.native is None:
                view.schedule(True)
            window.raise_()
            if not window.slot:
                self.area.setActiveSubWindow(window)
        finally:
            self.busy = False

    def activate(self, window):
        if window is None or self.busy or not isValid(window):
            return
        # QMdiArea emits this from its showEvent too. Reparenting its splitter
        # synchronously deletes splitter handles in QWidgetPrivate's copied
        # showChildren list, causing the recurring native use-after-free.
        if self.windows.get(window.doc) is window:
            self.request_navigation(window.doc, select=True)

    def minimize(self, window):
        before = self.snapshot()
        if self._pending_navigation and self._pending_navigation[0] is window.doc:
            self.cancel_navigation()
        window.hide()
        self.dirty()
        self.record_layout(before, "收起图窗")

    def undock(self, window):
        if not window.slot:
            return
        window.slot = None
        window.setParent(None)
        window.setWindowFlags(QtCore.Qt.SubWindow | QtCore.Qt.FramelessWindowHint)
        self.area.addSubWindow(
            window, QtCore.Qt.SubWindow | QtCore.Qt.FramelessWindowHint
        )
        window.show()
        window.resize(
            max(280, self.area.viewport().width() // 2),
            max(220, self.area.viewport().height() // 2),
        )
        if self.dock_host and not any(w.slot for w in self.windows.values()):
            self.dock_host.hide()

    def make_docks(self, kind):
        if self.dock_layout == kind:
            self.dock_host.show()
            return
        for window in self.windows.values():
            self.undock(window)
        if self.dock_host:
            self.dock_host.deleteLater()
        self.dock_host = QtWidgets.QWidget(self.area.viewport())
        layout = QtWidgets.QVBoxLayout(self.dock_host)
        layout.setContentsMargins(0, 0, 0, 0)
        self.root_split = QtWidgets.QSplitter(
            QtCore.Qt.Vertical if kind == "grid" else QtCore.Qt.Horizontal
        )
        self.root_split.setChildrenCollapsible(False)
        layout.addWidget(self.root_split)
        self.rows = []
        self.slots = {}
        if kind == "grid":
            for _ in range(2):
                row = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
                row.setChildrenCollapsible(False)
                for _ in range(2):
                    holder = QtWidgets.QWidget()
                    box = QtWidgets.QVBoxLayout(holder)
                    box.setContentsMargins(0, 0, 0, 0)
                    slot = "ABCD"[len(self.slots)]
                    self.slots[slot] = holder
                    row.addWidget(holder)
                self.root_split.addWidget(row)
                row.splitterMoved.connect(
                    lambda pos, index, row=row: self.share_boundary(row, pos, index)
                )
                self.rows.append(row)
        else:
            for slot in ("L", "R"):
                holder = QtWidgets.QWidget()
                box = QtWidgets.QVBoxLayout(holder)
                box.setContentsMargins(0, 0, 0, 0)
                self.slots[slot] = holder
                self.root_split.addWidget(holder)
        self.dock_layout = kind
        self.dock_host.setGeometry(self.area.viewport().rect())
        self.dock_host.show()
        self.dock_host.lower()

    def share_boundary(self, row, pos, index):
        if self.syncing:
            return
        self.syncing = True
        try:
            for other in self.rows:
                if other is not row:
                    other.moveSplitter(pos, index)
        finally:
            self.syncing = False

    def dock(self, window, slot):
        self.make_docks("halves" if slot in ("L", "R") else "grid")
        for other in self.windows.values():
            if other is not window and other.slot == slot:
                self.undock(other)
        if window.slot:
            self.undock(window)
        self.area.removeSubWindow(window)
        window.setParent(
            self.slots[slot], QtCore.Qt.Widget | QtCore.Qt.FramelessWindowHint
        )
        self.slots[slot].layout().addWidget(window)
        window.slot = slot
        window.show()
        self.dock_host.show()
        self.dock_host.lower()
        self.dirty()

    def restore_figures(self):
        self.cancel_navigation()
        self.busy = True
        try:
            self.area.setParent(self.park)
            for doc, window in list(self.windows.items()):
                figure = self.figures[doc]
                figure.setParent(self.park)
                self.splitters[doc].insertWidget(0, figure)
                figure.show()
                self.area.removeSubWindow(window)
                window.hide()
                window.deleteLater()
            self.windows.clear()
            self.figures.clear()
            self.splitters.clear()
            self.host = None
            if self.dock_host:
                self.dock_host.deleteLater()
            self.dock_host, self.dock_layout = None, None
            self.root_split, self.rows, self.slots = None, [], {}
        finally:
            self.busy = False

    def reset(self):
        self.enabled = False
        self.restore_figures()
        with QtCore.QSignalBlocker(self.button):
            self.button.setChecked(False)

    def forget(self, doc):
        if self._pending_navigation and self._pending_navigation[0] is doc:
            self.cancel_navigation()
        previous_busy = self.busy
        self.busy = True
        try:
            window = self.windows.pop(doc, None)
            if self.host is doc:
                self.area.setParent(self.park)
                self.host = None
            if window:
                figure = self.figures.pop(doc)
                figure.setParent(self.park)
                self.splitters.pop(doc).insertWidget(0, figure)
                self.area.removeSubWindow(window)
                window.hide()
                window.deleteLater()
        finally:
            self.busy = previous_busy

    def snapshot(self):
        return {
            "enabled": self.enabled,
            "layout": self.dock_layout,
            "splits": self.root_split.sizes() if self.root_split else [],
            "rows": [row.sizes() for row in self.rows],
            "windows": [
                {
                    "key": key(doc),
                    "visible": not w.isHidden(),
                    "slot": w.slot,
                    "rect": [w.x(), w.y(), w.width(), w.height()],
                }
                for doc, w in self.windows.items()
            ],
        }

    def restore(self, state):
        if not state.get("enabled"):
            return
        tabs = self.owner.ui.tabWidget
        docs = {
            key(tabs.widget(i)): tabs.widget(i)
            for i in range(tabs.count())
            if graph(tabs.widget(i))
        }
        current = tabs.currentWidget()
        self.enabled = True
        with QtCore.QSignalBlocker(self.button):
            self.button.setChecked(True)
        for item in state.get("windows", []):
            doc = docs.get(item["key"])
            if doc is None:
                continue
            self.show(doc)
            window = self.windows[doc]
            if item.get("slot"):
                self.dock(window, item["slot"])
            elif len(item.get("rect", [])) == 4:
                window.setGeometry(*item["rect"])
            window.setVisible(item.get("visible", True))
        if self.root_split and state.get("splits"):
            self.root_split.setSizes(state["splits"])
            for row, sizes in zip(self.rows, state.get("rows", [])):
                row.setSizes(sizes)
        if graph(current):
            self.show(current)
            saved = next(
                (
                    item
                    for item in state.get("windows", [])
                    if item["key"] == key(current)
                ),
                None,
            )
            if saved and not saved.get("visible", True):
                self.windows[current].hide()
        self.cancel_navigation()
        self.changed()

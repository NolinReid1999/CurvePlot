"""Record native ViewBox wheel and drag navigation in sheet undo history."""

from PySide6 import QtCore


class NavigationHistory(QtCore.QObject):
    def __init__(self, document):
        super().__init__(document)
        self.document = document
        self.viewport = None
        self.boxes = set()
        self.before = None
        self.after = None
        self._last_cursor = None
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(220)
        self.timer.timeout.connect(self.finish)
        self.ensure_bindings()

    def ensure_bindings(self):
        if getattr(self.document, "_graph_disposed", False):
            return
        viewport = self.document.ui.plot_widget.viewport()
        if viewport is not self.viewport:
            if self.viewport is not None:
                try:
                    self.viewport.removeEventFilter(self)
                except RuntimeError:
                    pass
            self.viewport = viewport
            viewport.installEventFilter(self)
        presentation = self.document.presentation
        for box in (
            self.document.ui.plot_widget.getViewBox(),
            presentation.right_box,
            presentation.top_box,
        ):
            if box is not None and box not in self.boxes:
                box.sigRangeChangedManually.connect(self.manual_change)
                self.boxes.add(box)

    def eventFilter(self, watched, event):
        if watched is not self.viewport:
            return False
        kind = event.type()
        if kind == QtCore.QEvent.MouseButtonPress:
            if self.timer.isActive():
                self.finish()
            self.before = self.snapshot()
        elif kind == QtCore.QEvent.Wheel:
            model=self.history_model()
            if not self.timer.isActive() or (model and model._cursor != self._last_cursor):
                self.finish()
                self.before = self.snapshot()
        return False

    def snapshot(self):
        from tailor.quick_actions import _view_state

        doc = self.document
        state = {"view": _view_state(doc)}
        extras = getattr(doc, "_inset_extras", None)
        if extras is not None and hasattr(extras, "range_roi"):
            roi = extras.range_roi
            position, size = roi.pos(), roi.size()
            state["roi"] = (
                (float(position.x()), float(position.y())),
                (float(size.x()), float(size.y())),
            )
        return state

    def manual_change(self, *args):
        doc = self.document
        if (
            getattr(doc, "_graph_disposed", False)
            or getattr(doc, "_view_edit_active", False)
            or getattr(getattr(doc, "_inset_extras", None), "_setting_range", False)
        ):
            return
        if self.before is None:
            # An interaction from outside the shared viewport has no reliable
            # pre-event state and must not create a false history entry.
            return
        after = self.snapshot()
        if after == self.before:return
        if self.after is None:
            from tailor.text_style_controls import record_view_edit
            self.after = {'state': after}
            record_view_edit(doc,'缩放与平移视图',{'state': self.before},self.after,
                lambda target,value:restore_navigation(target,value['state']))
            model=self.history_model()
            self._last_cursor=model._cursor if model else None
        else:
            self.after['state']=after
        self.timer.start()

    def history_model(self):
        doc=self.document
        source=next(iter(doc.model._plots),None) if doc.presentation.multi else doc
        return source.data_sheet.model if source is not None else None

    def finish(self):
        self.timer.stop()
        self.before=self.after=None
        self._last_cursor=None


def restore_navigation(doc, state):
    from tailor.quick_actions import _restore_view

    extras = getattr(doc, "_inset_extras", None)
    if extras is not None and "roi" in state and hasattr(extras, "range_roi"):
        roi = extras.range_roi
        (x, y), (width, height) = state["roi"]
        with QtCore.QSignalBlocker(roi):
            roi.setPos((x, y))
            roi.setSize((width, height))
        extras.cfg["inset"]["range"] = [x, y, x + width, y + height]
        if hasattr(extras, "lines"):
            extras.update_lines()
    _restore_view(doc, state["view"])

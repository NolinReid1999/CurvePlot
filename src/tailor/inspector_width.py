"""Persist the user's inspector width, while enforcing content-aware minimums."""

from PySide6 import QtCore


class InspectorWidth(QtCore.QObject):
    def __init__(self, splitter, inspector, kind):
        super().__init__(splitter)
        self.splitter, self.inspector, self.kind = splitter, inspector, kind
        self.settings = QtCore.QSettings("PhysicsPlot", "InspectorLayout")
        inspector.setMinimumWidth(max(380, inspector.minimumWidth()))
        splitter.setChildrenCollapsible(False)
        splitter.splitterMoved.connect(self.remember)
        inspector.installEventFilter(self)
        self.restored = False
        self._restore_timer = QtCore.QTimer(self)
        self._restore_timer.setSingleShot(True)
        self._restore_timer.timeout.connect(self.restore)
        self._restore_timer.start(0)

    def restore(self):
        if self.splitter.width() < 500:
            return
        self.restored = True
        minimum = max(380, self.inspector.minimumWidth())
        width = max(minimum, int(self.settings.value(self.kind + "/width", 440)))
        sizes = self.splitter.sizes()
        if len(sizes) >= 2:
            room = sum(sizes)
            width = min(width, max(minimum, room - 240))
            sizes[-1] = width
            sizes[0] = max(200, room - width - sum(sizes[1:-1]))
            self.splitter.setSizes(sizes)

    def remember(self, *args):
        if self.restored:
            self.settings.setValue(
                self.kind + "/width",
                max(380, self.splitter.widget(self.splitter.count() - 1).width()),
            )

    def protect_minimum(self):
        tabs = getattr(self.inspector, "tabs", self.inspector)
        width = max(380, tabs.minimumWidth())
        # A shared stacked inspector must honor its original tabs' content minimum.
        if self.inspector.minimumWidth() != width:
            self.inspector.setMinimumWidth(width)

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.LayoutRequest:
            self.protect_minimum()
        if event.type() == QtCore.QEvent.Show and not self.restored:
            self._restore_timer.start(0)
        return False


def bind_width(splitter, inspector, kind):
    inspector._width_memory = InspectorWidth(splitter, inspector, kind)

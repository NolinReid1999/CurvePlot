"""Hide intermediate restored frames without hiding or resizing the graphs."""

from PySide6 import QtCore, QtGui, QtWidgets
import shiboken6

from tailor.notices import BusyIndicator


class ProjectLoadCover(QtWidgets.QFrame):
    def __init__(self, owner):
        tabs = owner.ui.tabWidget
        stack = tabs.findChild(QtWidgets.QStackedWidget, 'qt_tabwidget_stackedwidget')
        super().__init__(stack)
        self.owner = owner
        self.setObjectName('projectLoadCover')
        self.setAutoFillBackground(True)
        self.setBackgroundRole(QtGui.QPalette.Window)
        self.setAccessibleName('正在恢复工程图形')
        self.card = QtWidgets.QFrame(self)
        self.card.setObjectName('transientNotice')
        self.card.setAttribute(QtCore.Qt.WA_StyledBackground)
        self.label = QtWidgets.QLabel('正在恢复工程图形…', self.card)
        self.label.setWordWrap(True)
        self.label.setAlignment(QtCore.Qt.AlignCenter)
        self.indicator = BusyIndicator(self.card)
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(12, 9, 12, 9)
        row.addWidget(self.label, 1); row.addWidget(self.indicator)
        self.card.setLayout(row)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(32)
        self.timer.timeout.connect(self.check_ready)
        self.quiet = 0
        self.active = True
        owner._project_reveal_pending = True
        notice=getattr(owner,'_notice',None)
        if notice is not None:
            notice.refresh()
        stack.installEventFilter(self)
        tabs.currentChanged.connect(self.place)
        self.place()
        self.show()

    def place(self, *args):
        self.setGeometry(self.parentWidget().rect())
        self.card.setFixedWidth(max(100, min(520, self.width()-32)))
        self.card.adjustSize()
        self.card.move(max(0,(self.width()-self.card.width())//2),max(0,self.height()-self.card.height()-20))
        if self.active:
            self.raise_()

    def eventFilter(self, watched, event):
        if event.type() in (QtCore.QEvent.Resize, QtCore.QEvent.Show, QtCore.QEvent.LayoutRequest):
            self.place()
            self.quiet = 0
        return False

    def wait_for_frames(self):
        self.place()
        self.timer.start()

    def documents(self):
        tabs = self.owner.ui.tabWidget
        pending = [tabs.widget(i) for i in range(tabs.count())]
        seen = set()
        while pending:
            doc = pending.pop()
            if doc is None or not shiboken6.isValid(doc) or id(doc) in seen:
                continue
            seen.add(id(doc))
            yield doc
            pending.extend(getattr(getattr(doc, 'model', None), '_plots', {}))
            native = getattr(getattr(doc, 'advanced_view', None), 'native', None)
            if native:
                pending.extend(native.live())
            collection = getattr(getattr(doc, 'extras', None), 'collection', None)
            if collection:
                pending.extend(e.inset_doc for e in collection.controllers.values() if hasattr(e, 'inset_doc'))

    def check_ready(self):
        docs = list(self.documents())
        # Failed setup must not leave an endless cover over an otherwise usable
        # project. Existing initialization handlers retain the error notice.
        if any(getattr(doc, '_inspector_error', None) for doc in docs):
            self.finish()
            return
        busy = self.owner.graph_initialization_busy(include_reveal=False)
        for doc in docs:
            advanced = getattr(doc, 'advanced_view', None)
            timers = [getattr(doc, '_source_timer', None), getattr(advanced, 'timer', None)]
            busy |= bool(getattr(doc, '_project_restore_pending', False))
            busy |= bool(getattr(advanced, 'rendering', False))
            native = getattr(advanced, 'native', None)
            timers.append(getattr(native, 'legend_timer', None))
            collection = getattr(getattr(doc, 'extras', None), 'collection', None)
            if collection:
                for entry in collection.controllers.values():
                    timers.extend([getattr(entry, 'range_timer', None), getattr(entry, 'position_timer', None)])
            busy |= any(t is not None and shiboken6.isValid(t) and t.isActive() for t in timers)
        self.quiet = 0 if busy else self.quiet + 1
        # Yield to pending scene/layout/paint work before exposing the first
        # frame. No fixed one-second delay and no second data scan or redraw.
        if self.quiet >= 3:
            self.finish()

    def finish(self):
        if not self.active:
            return
        self.timer.stop()
        self.active = False
        self.owner._project_reveal_pending = False
        self.hide()
        self.parentWidget().removeEventFilter(self)
        self.owner.ui.tabWidget.currentChanged.disconnect(self.place)
        notice=getattr(self.owner,'_notice',None)
        if notice is not None and shiboken6.isValid(notice):
            notice.refresh()
        self.deleteLater()

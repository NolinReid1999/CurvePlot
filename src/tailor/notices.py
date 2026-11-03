"""One bottom-centred Qt notice for status messages and staged work."""

from PySide6 import QtCore, QtGui, QtWidgets
import shiboken6
import weakref


def workspace_viewport(owner):
    tab=getattr(getattr(owner,'ui',None),'tabWidget',None)
    doc=tab.currentWidget() if tab else None
    canvas=getattr(getattr(doc,'advanced_view',None),'canvas',None)
    if canvas is not None and canvas.isVisible():
        return canvas.viewport() if hasattr(canvas,'viewport') else canvas
    ui=getattr(doc,'ui',None)
    view=getattr(ui,'plot_widget',None) or getattr(ui,'data_view',None)
    return view.viewport() if view is not None and view.isVisible() else (tab or owner)


def bottom_center(overlay,viewport,bottom=16):
    parent=overlay.parentWidget()
    point=parent.mapFromGlobal(viewport.mapToGlobal(QtCore.QPoint()))
    overlay.adjustSize()
    overlay.move(point.x()+max(4,(viewport.width()-overlay.width())//2),
                 point.y()+max(4,viewport.height()-overlay.height()-bottom))


class BusyIndicator(QtWidgets.QWidget):
    """Small native Qt paint animation; it never advances a fake percentage."""
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setFixedSize(20,20);self.phase=0
        self.timer=QtCore.QTimer(self);self.timer.setInterval(33)
        self.timer.timeout.connect(self.advance)
        self.setAccessibleName('正在处理')

    def advance(self):
        self.phase=(self.phase+18)%360;self.update()

    def showEvent(self,event):
        super().showEvent(event);self.timer.start()

    def hideEvent(self,event):
        self.timer.stop();super().hideEvent(event)

    def paintEvent(self,event):
        painter=QtGui.QPainter(self);painter.setRenderHint(QtGui.QPainter.Antialiasing)
        pen=QtGui.QPen(self.palette().color(QtGui.QPalette.Highlight),2)
        pen.setCapStyle(QtCore.Qt.RoundCap);painter.setPen(pen)
        painter.drawArc(QtCore.QRectF(3,3,14,14),-self.phase*16,250*16)


class Notice(QtWidgets.QFrame):
    def __init__(self, owner):
        super().__init__(owner)
        self._owner=weakref.ref(owner)
        self.setObjectName('transientNotice')
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.setAttribute(QtCore.Qt.WA_StyledBackground)
        self.label = QtWidgets.QLabel()
        self.label.setWordWrap(True)
        self.busy = BusyIndicator(self)
        self.fade_effect=QtWidgets.QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.fade_effect)
        self.fade=QtCore.QPropertyAnimation(self.fade_effect,b'opacity',self)
        self.fade.setDuration(140);self.fade.setStartValue(0.);self.fade.setEndValue(1.)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(10)
        layout.addWidget(self.label, 1)
        layout.addWidget(self.busy)
        self.tasks = {}
        self.priority_tasks=set()
        self.transient = ''
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.expire)
        owner.installEventFilter(self)
        tabs=getattr(getattr(owner,'ui',None),'tabWidget',None)
        if tabs:tabs.currentChanged.connect(self.refresh)
        self.hide()

    def message(self, text):
        if text.startswith(('PhysicsPlot ', 'Curve ', '字体对象：')):
            return
        self.transient = text
        self.timer.start(4500)
        self.refresh()

    def begin(self, token, text, *, priority=False):
        self.tasks[token] = text
        if priority:self.priority_tasks.add(token)
        self.refresh()

    def finish(self, token):
        if not shiboken6.isValid(self):return
        self.tasks.pop(token, None)
        self.priority_tasks.discard(token)
        self.refresh()

    def expire(self):
        self.transient = ''
        self.refresh()

    def refresh(self):
        owner=self._owner()
        if owner is None or not shiboken6.isValid(owner) or not hasattr(owner,'ui'):return
        active=next((text for key,text in reversed(self.tasks.items()) if key in self.priority_tasks),'')
        text = active or self.transient or next(reversed(self.tasks.values()), '')
        entering=self.isHidden() and bool(text)
        # Restoring owns a bottom-centred cover with its own busy notice.
        # Keep task state, but never paint a second message over the tab bar.
        if not text or getattr(owner,'_project_reveal_pending',False):
            self.fade.stop()
            self.hide()
            return
        self.label.setText(text)
        self.busy.setVisible(bool(self.tasks))
        # Populate and position before showing; new project controllers can
        # still have a provisional 100px geometry until their host activates.
        self.place()
        self.show()
        if entering:self.fade.start()
        self.raise_()

    def showEvent(self,event):
        super().showEvent(event)
        self.place()

    def place(self):
        owner = self._owner()
        if owner is None or not shiboken6.isValid(owner) or not hasattr(owner,'ui'):return
        viewport=workspace_viewport(owner)
        if viewport is not getattr(self,'_anchor',None):
            previous=getattr(self,'_anchor',None)
            if previous is not None and shiboken6.isValid(previous):previous.removeEventFilter(self)
            self._anchor=viewport;viewport.installEventFilter(self)
        self.setFixedWidth(min(520, max(120, viewport.width() - 32)))
        doc=owner.ui.tabWidget.currentWidget()
        doc=getattr(doc,'_active_document',doc)
        crop=getattr(getattr(getattr(doc,'annotations',None),'panel',None),'image_crop',None)
        toolbar=getattr(crop,'toolbar',None)
        bottom=16+(toolbar.height()+8 if toolbar is not None and toolbar.isVisible() else 0)
        bottom_center(self,viewport,bottom)

    def eventFilter(self, owner, event):
        if event.type() in (QtCore.QEvent.Resize,QtCore.QEvent.Move,QtCore.QEvent.Show,QtCore.QEvent.LayoutRequest) and not self.isHidden():
            self.place()
        return False

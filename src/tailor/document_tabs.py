"""Natural-width document tabs with the approved pale type accents."""

from typing import ClassVar

from PySide6 import QtCore, QtGui, QtWidgets

from tailor.ui_theme import action_icon


class CloseDocumentButton(QtWidgets.QToolButton):
    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        if self.underMouse() or self.isDown():
            painter.setPen(QtCore.Qt.NoPen)
            color = self.palette().color(QtGui.QPalette.Text)
            color.setAlpha(25 if not self.isDown() else 45)
            painter.setBrush(color)
            center = QtCore.QPointF(self.rect().center())
            painter.drawRoundedRect(
                QtCore.QRectF(center.x() - 8, center.y() - 8, 16, 16), 4, 4
            )
        self.icon().paint(
            painter,
            QtCore.QRect((self.width() - 14) // 2, (self.height() - 14) // 2, 14, 14),
        )


class DocumentTabStyle(QtWidgets.QProxyStyle):
    """Use the same tab painting for Qt's live tabs and moving-tab pixmap."""
    def __init__(self, bar):
        super().__init__()
        self.setParent(bar)
        self.bar = bar

    def drawControl(self, element, option, painter, widget=None):
        if element == QtWidgets.QStyle.CE_TabBarTab and isinstance(option, QtWidgets.QStyleOptionTab):
            self.bar.draw_tab(painter, option)
        else:
            super().drawControl(element, option, painter, widget)


class DocumentTabBar(QtWidgets.QTabBar):
    ROW_HEIGHT = 28
    VERTICAL_INSET = 3
    CORNER_RADIUS = 5
    ICON_SIZE = 16
    COLORS: ClassVar[dict] = {
        "sheet": ("#27845e", "#e6f2ec"),
        "plot": ("#cb602e", "#fbede5"),
        "fit": ("#367aba", "#e7effb"),
        "processing": ("#77549c", "#f0eafa"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setExpanding(False)
        self.setDrawBase(False)
        self.setElideMode(QtCore.Qt.ElideRight)
        self.setUsesScrollButtons(True)
        self._tab_style = DocumentTabStyle(self)
        self.setStyle(self._tab_style)
        self.setStyleSheet("QTabBar { background: transparent; }")
        self.icons = {
            kind: action_icon(kind, self, self.COLORS[kind][0]) for kind in self.COLORS
        }

    def resizeEvent(self,event):
        super().resizeEvent(event)
        QtCore.QTimer.singleShot(0,self,self.refresh_arrows)

    def showEvent(self,event):
        super().showEvent(event)
        QtCore.QTimer.singleShot(0,self,self.refresh_arrows)

    def refresh_arrows(self):
        from tailor.appearance import manager
        color='#b9c7dc' if manager().dark() else '#637080'
        for button in self.findChildren(QtWidgets.QToolButton,options=QtCore.Qt.FindDirectChildrenOnly):
            name=button.objectName().lower()
            if 'scroll' not in name:continue
            direction='left' if 'left' in name else 'right'
            button.setArrowType(QtCore.Qt.NoArrow)
            button.setIcon(action_icon(direction,button,color))
            button.setIconSize(QtCore.QSize(16,16))
            button.setStyleSheet('QToolButton {background:palette(window);border:1px solid palette(mid);border-radius:4px;padding:0;}')
            button.setToolTip('向左浏览标签' if direction=='left' else '向右浏览标签')

    def label_font(self, selected=False):
        font = self.font()
        font.setBold(selected)
        return font

    def tabSizeHint(self, index):
        font = self.label_font(selected=True)
        width = QtGui.QFontMetrics(font).horizontalAdvance(self.tabText(index))
        return QtCore.QSize(min(300, max(110, width + 78)), self.ROW_HEIGHT)

    def minimumTabSizeHint(self, index):
        return QtCore.QSize(110, self.ROW_HEIGHT)

    def tabInserted(self, index):
        super().tabInserted(index)
        button = CloseDocumentButton(self)
        button.setIcon(action_icon("close", self))
        button.setIconSize(QtCore.QSize(14, 14))
        button.setToolTip("关闭标签")
        button.setAccessibleName("关闭标签")
        button.setFixedSize(24, 24)
        button.setStyleSheet(
            "QToolButton { border: 0; background: transparent; padding: 0; }"
        )
        for side in (QtWidgets.QTabBar.LeftSide, QtWidgets.QTabBar.RightSide):
            previous = self.tabButton(index, side)
            if previous is not None:
                previous.hide()
                self.setTabButton(index, side, None)
                previous.deleteLater()
        self.setTabButton(index, QtWidgets.QTabBar.RightSide, button)
        button.clicked.connect(lambda: self.close_button(button))

    def close_button(self, button):
        for index in range(self.count()):
            if self.tabButton(index, QtWidgets.QTabBar.RightSide) is button:
                self.tabCloseRequested.emit(index)
                break

    def paintEvent(self, event):
        # QTabBar owns drag offsets, clipping and its floating tab snapshot.
        super().paintEvent(event)

    def draw_tab(self, painter, option):
        index = getattr(option, 'tabIndex', -1)
        if not 0 <= index < self.count() or self.tabText(index) != option.text:
            index = next((i for i in range(self.count()) if self.tabText(i) == option.text), -1)
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = option.rect.adjusted(
            2, self.VERTICAL_INSET, -2, -self.VERTICAL_INSET
        )
        kind = self.tabData(index) or "plot"
        accent, background = self.COLORS.get(kind, self.COLORS["plot"])
        from tailor.appearance import manager

        if manager().dark():
            accent, background = {
                "sheet": ("#65d49e", "#072116"),
                "plot": ("#f2a077", "#29170d"),
                "fit": ("#86baff", "#0a1d34"),
                "processing": ("#bb9ce1", "#21162e"),
            }.get(kind, ("#86baff", "#0a1d34"))
        selected = bool(option.state & QtWidgets.QStyle.State_Selected)
        painter.setBrush(QtGui.QColor(background))
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawRoundedRect(rect, self.CORNER_RADIUS, self.CORNER_RADIUS)
        if selected:
            painter.setPen(QtGui.QPen(QtGui.QColor(accent), 1.3))
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawRoundedRect(rect, self.CORNER_RADIUS, self.CORNER_RADIUS)
            painter.drawLine(
                rect.bottomLeft() + QtCore.QPoint(3, 0),
                rect.bottomRight() + QtCore.QPoint(-3, 0),
            )
        icon_rect = QtCore.QRect(
            rect.left() + 8,
            rect.center().y() - self.ICON_SIZE // 2,
            self.ICON_SIZE,
            self.ICON_SIZE,
        )
        action_icon(kind, self, accent).paint(painter, icon_rect)
        label = rect.adjusted(34, 0, -34, 0)
        font = self.label_font(selected)
        painter.setFont(font)
        painter.setPen(QtGui.QColor(accent))
        text = QtGui.QFontMetrics(font).elidedText(
            option.text, QtCore.Qt.ElideRight, max(1, label.width())
        )
        painter.drawText(label, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, text)
        painter.restore()

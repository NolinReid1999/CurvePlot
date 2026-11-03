"""Wrapping Qt choices; same values/signals as the existing hidden combo.

Layout follows Qt's public Flow Layout example (Qt for Python, BSD-3-Clause).
"""

from PySide6 import QtCore, QtWidgets


class FlowLayout(QtWidgets.QLayout):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(6)

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, i):
        return self.items[i] if 0 <= i < len(self.items) else None

    def takeAt(self, i):
        return self.items.pop(i) if 0 <= i < len(self.items) else None

    def expandingDirections(self):
        return QtCore.Qt.Orientations()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self.place(QtCore.QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.place(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        return QtCore.QSize(60, 30)

    def place(self, rect, measure):
        x, y, h = rect.x(), rect.y(), 0
        for item in self.items:
            if item.widget() and item.widget().isHidden():
                continue
            size = item.sizeHint()
            w = min(size.width(), max(30, rect.width()))
            if x > rect.x() and x + w > rect.right() + 1:
                x = rect.x()
                y += h + self.spacing()
                h = 0
            if not measure:
                item.setGeometry(QtCore.QRect(x, y, w, size.height()))
            x += w + self.spacing()
            h = max(h, size.height())
        return y + h - rect.y()


class ChoiceButtons(QtWidgets.QWidget):
    def __init__(self, combo, parent=None, equal=False):
        super().__init__(parent)
        self.combo = combo
        combo.setParent(self)
        combo.hide()
        layout = QtWidgets.QHBoxLayout(self) if equal else FlowLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.buttons = []
        self.group = QtWidgets.QButtonGroup(self)
        for i in range(combo.count()):
            b = QtWidgets.QPushButton(combo.itemText(i))
            b.setCheckable(True)
            b.setMaximumWidth(210)
            b.setToolTip(combo.itemText(i))
            b.clicked.connect(
                lambda checked=False, i=i: (
                    combo.setCurrentIndex(i),
                    combo.activated.emit(i),
                )
            )
            self.group.addButton(b)
            self.buttons.append(b)
            layout.addWidget(b)
            if equal:
                b.setMinimumWidth(0)
                b.setSizePolicy(
                    QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed
                )
        combo.currentIndexChanged.connect(self.sync)
        combo.installEventFilter(self)
        self.sync()

    def sync(self, *args):
        for i, b in enumerate(self.buttons):
            with QtCore.QSignalBlocker(b):
                b.setChecked(i == self.combo.currentIndex())
            b.setEnabled(self.combo.isEnabledTo(self))

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.EnabledChange:
            self.sync()
        return False


class ChipList(QtWidgets.QWidget):
    chosen = QtCore.Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.flow = FlowLayout(self)
        self.buttons = []
        self.current = -1

    def set_items(self, labels, current=0):
        old = [b.text() for b in self.buttons]
        if old != list(labels):
            while self.flow.count():
                item = self.flow.takeAt(0)
                item.widget().deleteLater()
            self.buttons = []
            for i, label in enumerate(labels):
                b = QtWidgets.QPushButton(label)
                b.setCheckable(True)
                b.setMaximumWidth(240)
                b.setToolTip(label)
                b.clicked.connect(lambda checked=False, i=i: self.chosen.emit(i))
                self.flow.addWidget(b)
                self.buttons.append(b)
        self.current = current
        for i, b in enumerate(self.buttons):
            b.setChecked(i == current)
        self.updateGeometry()

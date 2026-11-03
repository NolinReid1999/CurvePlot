"""Independent remembered swatches over the existing color value and dialog."""

import json
import weakref

from PySide6 import QtCore, QtGui, QtWidgets

from tailor.ui_widgets import ColorButton


class Swatch(QtWidgets.QToolButton):
    def __init__(self, color=None, parent=None):
        super().__init__(parent)
        self.color = color
        self.setFixedSize(24, 24)
        self.setCheckable(True)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.setStyleSheet(
            "QToolButton {padding:0; min-width:22px; max-width:22px; "
            "min-height:22px; max-height:22px; border-radius:12px;}"
        )

    def color_rect(self):
        # Derive both dimensions from one diameter, including compact/HiDPI sizes.
        diameter = max(0, min(self.width(), self.height()) - 8)
        return QtCore.QRectF(
            (self.width() - diameter) / 2,
            (self.height() - diameter) / 2,
            diameter,
            diameter,
        )

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = self.color_rect()
        painter.setPen(QtGui.QPen(QtGui.QColor("#7e8998"), 1.2))
        painter.setBrush(QtGui.QColor(self.color) if self.color else QtCore.Qt.NoBrush)
        painter.drawEllipse(rect)
        if not self.color:
            painter.drawLine(rect.bottomLeft(), rect.topRight())
        painter.end()


class ColorPalette(QtWidgets.QWidget):
    instances = weakref.WeakSet()
    changed = QtCore.Signal(str)

    def __init__(self, kind, count=6, compact=False):
        super().__init__()
        self.kind = kind
        self.value = ""
        self.origin = None
        self.custom = None
        self.settings = QtCore.QSettings("PhysicsPlot", "CommonColors")
        self.instances.add(self)
        self.storage_key = "shared-v37"
        initial = ["#202020", "#2878cc", "#d8504a", "#35945b", "#8655b2"]
        try:
            self.colors = json.loads(self.settings.value(self.storage_key, json.dumps(initial)))
        except (ValueError, TypeError):
            self.colors = initial
        if (
            not isinstance(self.colors, list)
            or not 0 < len(self.colors) <= len(initial)
            or any(
                not isinstance(c, str) or not QtGui.QColor(c).isValid()
                for c in self.colors
            )
        ):
            self.colors = initial.copy()
        # Extend the former three annotation colors without replacing user choices.
        self.colors += initial[len(self.colors) :]
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        layout.setProperty("compactSpacing", 3)
        self.current = Swatch(parent=self)
        self.current.setToolTip("当前自定义颜色；再次点击取消颜色")
        self.current.clicked.connect(self.choose_current)
        layout.addWidget(self.current)
        self.swatches = []
        for index in range(count - 1):
            button = Swatch(self.colors[index], self)
            button.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
            button.clicked.connect(lambda checked=False, i=index: self.choose_common(i))
            button.customContextMenuRequested.connect(
                lambda pos, i=index: self.edit_common(i)
            )
            self.swatches.append(button)
            layout.addWidget(button)
        self.code = ColorButton(self.default_color)
        self.code.setMinimumWidth(0)
        self.code.setFixedHeight(28)
        self.code.setToolTip("输入颜色编码或选择颜色")
        self.code.setStyleSheet("QPushButton {padding:2px 4px;}")
        if compact:
            for button in [self.current, *self.swatches]:
                button.setFixedSize(20, 20)
                button.setStyleSheet(
                    "QToolButton {padding:0; min-width:18px; max-width:18px; "
                    "min-height:18px; max-height:18px; border-radius:10px;}"
                )
            self.code.setFixedWidth(80)
        else:
            self.code.setMinimumWidth(78)
        layout.addWidget(self.code, 1)
        self.code.clicked.connect(self.choose_code)
        self.refresh()

    @property
    def default_color(self):
        return "#202020" if self.kind in {"text", "line"} else "#ffffff"

    def showEvent(self, event):
        try:
            colors = json.loads(self.settings.value(self.storage_key, json.dumps(self.colors)))
            if (
                isinstance(colors, list)
                and len(colors) == len(self.colors)
                and all(QtGui.QColor(c).isValid() for c in colors)
            ):
                old = self.value
                self.colors = colors
                if old and self.origin != "custom":
                    self.origin = (
                        self.colors.index(old)
                        if old in self.colors[: len(self.swatches)]
                        else "custom"
                    )
                    self.custom = old if self.origin == "custom" else None
        except (TypeError, ValueError):
            pass
        self.refresh()
        super().showEvent(event)

    def set_value(self, value, explicit=False):
        value = value.lower() if value else ""
        if (
            self.kind in {"text", "line"}
            and value == "#202020"
            and (self.value != value or self.origin is None)
        ):
            value = ""
        if value != self.value:
            self.value = value
            self.origin = (
                self.colors.index(value)
                if value in self.colors[: len(self.swatches)] and not explicit
                else "custom"
                if value
                else None
            )
            self.custom = value if self.origin == "custom" else None
        if explicit:
            self.origin = "custom"
            self.custom = value
        self.refresh()

    def refresh(self):
        self.current.color = self.custom if self.origin == "custom" else None
        self.current.setChecked(self.origin == "custom" and bool(self.value))
        self.current.update()
        for index, button in enumerate(self.swatches):
            button.color = self.colors[index]
            button.setChecked(self.origin == index and bool(self.value))
            button.setToolTip(self.colors[index] + "；右键修改常用色")
            button.update()
        self.code.setText(self.value or self.default_color)
        self.code.setIconSize(QtCore.QSize(14, 14))

    def select(self, value, origin):
        self.value = value
        self.origin = origin if value else None
        self.custom = value if origin == "custom" and value else None
        self.refresh()
        self.changed.emit(value)

    def choose_common(self, index):
        self.select(
            "" if self.origin == index and self.value else self.colors[index], index
        )

    def choose_current(self):
        self.select(
            "" if self.origin == "custom" and self.value else self.custom or "",
            "custom",
        )

    def choose_code(self):
        color = QtWidgets.QColorDialog.getColor(
            QtGui.QColor(self.value or "#202020"), self, "颜色编码"
        )
        if color.isValid():
            self.select(color.name(), "custom")

    def edit_common(self, index):
        color = QtWidgets.QColorDialog.getColor(
            QtGui.QColor(self.colors[index]), self, "修改常用颜色"
        )
        if not color.isValid():
            return
        selected = self.origin == index and bool(self.value)
        self.colors[index] = color.name()
        self.settings.setValue(self.storage_key, json.dumps(self.colors))
        for palette in list(self.instances):
            if palette is self:
                continue
            palette.colors = list(self.colors)
            palette.set_value(palette.value, explicit=palette.origin == "custom")
            palette.refresh()
        # Only the selected swatch changes the object's color; editing another is a palette preference.
        if selected:
            self.select(color.name(), index)
        else:
            self.refresh()

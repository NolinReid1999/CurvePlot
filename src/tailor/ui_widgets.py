"""Shared presentation widgets. Stored values and business signals stay intact."""

from typing import ClassVar

from PySide6 import QtCore, QtGui, QtWidgets


class ColorButton(QtWidgets.QPushButton):
    def __init__(self, value, parent=None):
        super().__init__(parent)
        self.setText(value)

    def setText(self, value):
        super().setText(value)
        color = QtGui.QColor(value)
        if color.isValid():
            pix = QtGui.QPixmap(20, 20)
            pix.fill(QtCore.Qt.transparent)
            painter = QtGui.QPainter(pix)
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            painter.setBrush(color)
            painter.setPen(QtGui.QPen(QtGui.QColor("#c3cbd5"), 1))
            painter.drawEllipse(3, 3, 14, 14)
            painter.end()
            self.setIcon(QtGui.QIcon(pix))
            self.setIconSize(QtCore.QSize(20, 20))


class FontFamilyCombo(QtWidgets.QComboBox):
    ALIASES: ClassVar[dict] = {
        "sans-serif": "系统无衬线",
        "serif": "衬线字体",
        "monospace": "等宽字体",
        "Heiti SC": "黑体（简体）",
        "Heiti TC": "黑体（繁体）",
        "Songti SC": "宋体（简体）",
        "Songti TC": "宋体（繁体）",
        "PingFang SC": "苹方（简体）",
        "PingFang TC": "苹方（繁体）",
        "Kaiti SC": "楷体（简体）",
        "STSong": "华文宋体",
        "STHeiti": "华文黑体",
        "STKaiti": "华文楷体",
        "SimSong": "宋体（SimSong）",
    }

    def add_system_fonts(self):
        # Most graph editors remain hidden. Populate the potentially long OS
        # font list only when its dropdown is actually requested.
        self._system_fonts_pending = True
        self.setMaxVisibleItems(18)
        self.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        if self.completer():
            self.completer().setFilterMode(QtCore.Qt.MatchContains)

    def showPopup(self):
        from tailor.popup_controls import configure_combo
        configure_combo(self)
        if getattr(self,'_system_fonts_pending',False):
            current=self.currentText()
            editor=self.lineEdit()
            with QtCore.QSignalBlocker(self):
                blocker=QtCore.QSignalBlocker(editor) if editor is not None else None
                self._populate_system_fonts()
                self.setCurrentText(current)
                del blocker
            self._system_fonts_pending=False
        # Opening/populating the list is not a font selection. The list popup
        # returns immediately; subsequent real mouse/keyboard choices still
        # emit activated normally.
        with QtCore.QSignalBlocker(self):
            super().showPopup()

    def _populate_system_fonts(self):
        existing = {self.itemData(i) for i in range(self.count())}
        families = QtGui.QFontDatabase.families()
        preferred = [f for f in self.ALIASES if f in families]
        for family in preferred + [f for f in families if f not in preferred]:
            if family not in existing:
                self.addItem(family)

    def addItem(self, text, userData=None):
        super().addItem(
            self.ALIASES.get(text, text), text if userData is None else userData
        )

    def addItems(self, texts):
        for text in texts:
            self.addItem(text)

    def currentText(self):
        display = super().currentText()
        return next(
            (key for key, value in self.ALIASES.items() if value == display), display
        )

    def setCurrentText(self, text):
        super().setCurrentText(self.ALIASES.get(text, text))


class InspectorTabBar(QtWidgets.QTabBar):
    def tabSizeHint(self, index):
        visible = [i for i in range(self.count()) if self.isTabVisible(i)]
        width = max(0, self.parentWidget().width() - 16)
        share, remainder = divmod(width, max(1, len(visible)))
        extra = index in visible[:remainder]
        return QtCore.QSize(max(44, share + int(extra)), 38)


class InspectorTabs(QtWidgets.QTabWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("inspectorTabs")
        self.setTabBar(InspectorTabBar(self))
        self.tabBar().setExpanding(True)
        self.tabBar().setDrawBase(False)
        self.tabBarDoubleClicked.connect(self.collapse_page)
        self._width_timer = QtCore.QTimer(self)
        self._width_timer.setSingleShot(True)
        self._width_timer.timeout.connect(self.fit_minimum_width)
        self.currentChanged.connect(lambda *args: self._width_timer.start(0))
        self.setMinimumWidth(380)

    def addTab(self, widget, *args):
        index = super().addTab(widget, *args)
        if hasattr(widget, "install_category_picker"):
            widget.install_category_picker(self, index)
        return index

    def collapse_page(self, index):
        if index < 0:
            return
        from tailor.fold_panel import FoldPanel

        page = self.widget(index)
        panels = [page] if isinstance(page, FoldPanel) else page.findChildren(FoldPanel)
        for panel in panels:
            for record in panel.sections:
                panel.remember_open(record, False)

    def minimumSizeHint(self):
        return QtCore.QSize(380, 200)

    def fit_minimum_width(self):
        # Content must wrap inside the agreed inspector width; an inactive
        # advanced page must never enlarge the whole document's splitter.
        self.setMinimumWidth(380)
        for index in range(self.count()):
            scroll = getattr(self.widget(index), "scroll", None)
            if isinstance(scroll, QtWidgets.QAbstractScrollArea):
                scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

    def event(self, event):
        if event.type() == QtCore.QEvent.LayoutRequest and hasattr(
            self, "_width_timer"
        ):
            self._width_timer.start(0)
        return super().event(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.tabBar().setFixedWidth(max(0, self.width() - 16))
        self.tabBar().updateGeometry()


def arrange_axis_fields(plot):
    """Reparent the existing name/range controls; retain all returnPressed wiring."""
    ui, grid = plot.ui, plot.ui.gridLayout
    while grid.count():
        item = grid.takeAt(0)
        if isinstance(item.widget(), QtWidgets.QLabel):
            item.widget().hide()
    for label in (ui.label, ui.label_2, ui.label_3, ui.label_4, ui.label_5, ui.label_6):
        label.hide()
    for row, title, first, second in (
        (0, "轴名称", ui.xlabel, ui.ylabel),
        (1, "X 范围", ui.x_min, ui.x_max),
        (2, "Y 范围", ui.y_min, ui.y_max),
    ):
        label = QtWidgets.QLabel(title)
        label.setFixedWidth(72)
        grid.addWidget(label, row, 0)
        grid.addWidget(first, row, 1)
        separator = QtWidgets.QLabel(" / " if row == 0 else "—")
        separator.setAlignment(QtCore.Qt.AlignCenter)
        separator.setProperty("muted", True)
        grid.addWidget(separator, row, 2)
        grid.addWidget(second, row, 3)
        for field in (first, second):
            field.setMinimumWidth(30)
            field.setMaximumWidth(16777215)
    ui.xlabel.setToolTip("X 轴名称")
    ui.ylabel.setToolTip("Y 轴名称")
    for field in (ui.x_min, ui.y_min):
        field.setPlaceholderText("最小 / 自动")
    for field in (ui.x_max, ui.y_max):
        field.setPlaceholderText("最大 / 自动")
    grid.setColumnStretch(1, 1)
    grid.setColumnStretch(3, 1)
    grid.setHorizontalSpacing(6)
    grid.setVerticalSpacing(7)


def data_index(box, value):
    """Find QVariant sequence data without Qt tuple/list conversion ambiguity."""
    for index in range(box.count()):
        candidate = box.itemData(index)
        if isinstance(candidate, (tuple, list)) and isinstance(value, (tuple, list)):
            equal = tuple(candidate) == tuple(value)
        else:
            equal = candidate == value
        if equal:
            return index
    return -1

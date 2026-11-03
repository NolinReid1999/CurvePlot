"""Compact ordered disclosures; every section scrolls in place."""

from PySide6 import QtCore, QtWidgets


def _pin_control_height(control):
    # pyqtgraph SpinBox otherwise resets its maximum in every paintEvent.
    # Its compact-height cache lets the existing Qt size constraint stay put.
    from pyqtgraph import SpinBox
    if isinstance(control, SpinBox):
        control.opts["compactHeight"] = True
        control._lastFontHeight = control.fontMetrics().height()
        from tailor.compact_controls import fit_number_display
        fit_number_display(control)
    if control.minimumHeight() == 30 and control.maximumHeight() == 30:
        return
    control.setFixedHeight(30)
    control.updateGeometry()
    parent = control.parentWidget()
    if parent is not None and parent.layout() is not None:
        parent.layout().invalidate()
        parent.updateGeometry()


class _InspectorControlHeight(QtCore.QObject):
    def eventFilter(self, control, event):
        if event.type() in (QtCore.QEvent.Polish, QtCore.QEvent.StyleChange, QtCore.QEvent.FontChange):
            if not getattr(control, '_height_pin_pending', False):
                control._height_pin_pending = True
                def pin():
                    control._height_pin_pending = False
                    _pin_control_height(control)
                QtCore.QTimer.singleShot(0, control, pin)
        return False


def normalize_control_height(control):
    # Every ordinary operating row is 30 px, including grouped toggle buttons
    # and third-party spin boxes. Keep explicitly large tiles and swatches.
    if type(control).__name__ == "Swatch" or control.property("inspectorHeight"):
        return
    if control.parentWidget() and control.parentWidget().objectName() == "elementButtons":
        return
    if isinstance(control, QtWidgets.QLineEdit) and isinstance(
        control.parentWidget(), (QtWidgets.QAbstractSpinBox, QtWidgets.QComboBox)
    ):
        return
    if not isinstance(control, (QtWidgets.QComboBox, QtWidgets.QLineEdit,
                               QtWidgets.QAbstractSpinBox, QtWidgets.QCheckBox,
                               QtWidgets.QPushButton, QtWidgets.QToolButton)):
        return
    _pin_control_height(control)
    if not hasattr(control, "_inspector_height_filter"):
        event_filter = _InspectorControlHeight(control)
        control._inspector_height_filter = event_filter
        control.installEventFilter(event_filter)


def normalize_control_heights(widget):
    for control in widget.findChildren(QtWidgets.QWidget):
        normalize_control_height(control)


def compact(widget):
    normalize_control_heights(widget)
    for layout in widget.findChildren(QtWidgets.QLayout):
        if layout.parentWidget().objectName() != "elementButtons":
            layout.setContentsMargins(0, 0, 0, 0)
        spacing = layout.property("compactSpacing")
        layout.setSpacing(7 if spacing is None else spacing)
        if isinstance(layout, QtWidgets.QFormLayout):
            layout.setContentsMargins(0, 0, 4, 0)
            layout.setFormAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
            layout.setHorizontalSpacing(8)
            layout.setLabelAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            layout.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
            for index in range(layout.rowCount()):
                item = layout.itemAt(index, QtWidgets.QFormLayout.LabelRole)
                if item and isinstance(item.widget(), QtWidgets.QLabel):
                    label = item.widget()
                    label.setMinimumWidth(0)
                    label.setMaximumWidth(16777215)
                    label.setSizePolicy(
                        QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Preferred
                    )
                    label.setWordWrap(False)
    from tailor.label_alignment import align_labels

    align_labels(widget)
    for label in widget.findChildren(QtWidgets.QLabel):
        if label.wordWrap() and len(label.text()) > 22:
            label.setProperty("muted", True)
    for group in widget.findChildren(QtWidgets.QGroupBox):
        if not group.title():
            group.setFlat(True)
            group.setStyleSheet("QGroupBox { border: 0; margin: 0; padding: 0; }")
    # Layout policies and QSS polishing may recalculate a combo's minimum after
    # the first pass; pin common inspector controls once the card is compact.
    normalize_control_heights(widget)


class FoldPanel(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        # Each application launch starts expanded. Continue remembering clicks
        # within this run, including when another graph creates its inspector.
        app = QtWidgets.QApplication.instance()
        if not getattr(app, '_curve_fold_session_started', False):
            QtCore.QSettings('PhysicsPlot', 'FoldSections').clear()
            app._curve_fold_session_started = True
        self.setProperty("inspectorContent", True)
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.scroll = QtWidgets.QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        body = QtWidgets.QWidget()
        body.setObjectName("inspectorBody")
        body.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        self.open_layout = QtWidgets.QVBoxLayout(body)
        self.open_layout.setContentsMargins(10, 4, 8, 10)
        self.open_layout.setSpacing(8)
        self.open_layout.setSizeConstraint(QtWidgets.QLayout.SetNoConstraint)
        self.open_layout.addStretch()
        self.scroll.setWidget(body)
        root.addWidget(self.scroll)
        self.sections = []

    def pin_header(self, *widgets):
        """Use the same insets as the scrolling cards, without size-hint growth."""
        frame = QtWidgets.QWidget(self)
        frame.setMinimumWidth(0)
        frame.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(20, 4, 18, 4)
        layout.setSpacing(7)
        layout.setSizeConstraint(QtWidgets.QLayout.SetNoConstraint)
        for widget in widgets:
            widget.setMinimumWidth(0)
            widget.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
            layout.addWidget(widget)
        self.layout().insertWidget(0, frame)
        return frame

    def add_section(self, title, content, opened=False, keep_field_titles=False, initially_closed=False):
        section = QtWidgets.QWidget(self)
        section.setProperty("foldCard", True)
        section.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        layout = QtWidgets.QVBoxLayout(section)
        layout.setContentsMargins(10, 4, 10, 10)
        layout.setSpacing(3)
        header = QtWidgets.QPushButton(section)
        header.setText(title)
        header.setAccessibleName(title)
        header.setProperty("sectionTitle", title)
        font = self.font()
        font.setBold(True)
        header.setFont(font)
        header.setCheckable(True)
        header.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
        )
        header.setObjectName("sectionHeader")
        header.setFixedHeight(30)
        header._inspector_height_filter = _InspectorControlHeight(header)
        header.installEventFilter(header._inspector_height_filter)
        header.setIconSize(QtCore.QSize(18, 18))
        layout.addWidget(header)
        if isinstance(content, QtWidgets.QLayout):
            content.setParent(None)
            container = QtWidgets.QWidget(section)
            container.setLayout(content)
            content = container
        layout.addWidget(content)
        if title=='选择数据点':
            help=content.findChild(QtWidgets.QToolButton,'pointSelectionHelp')
            if help is not None:
                bar=QtWidgets.QWidget(section)
                line=QtWidgets.QHBoxLayout(bar);line.setContentsMargins(0,0,0,0);line.setSpacing(7)
                layout.removeWidget(header)
                line.addWidget(header,1);line.addWidget(help)
                help.show();layout.insertWidget(0,bar)
        if keep_field_titles:
            content.setProperty('keepFieldTitles', True)
        compact(content)
        record = [section, header, False, content]
        self.sections.append(record)
        self.open_layout.insertWidget(self.open_layout.count() - 1, section)
        header.clicked.connect(lambda checked: self.remember_open(record, checked))
        settings = QtCore.QSettings("PhysicsPlot", "FoldSections")
        saved = settings.value(type(self).__name__ + "/" + title, True, type=bool)
        self.set_open(record, False if initially_closed else saved)
        return section

    def remember_open(self, record, opened):
        QtCore.QSettings("PhysicsPlot", "FoldSections").setValue(
            type(self).__name__ + "/" + record[1].property("sectionTitle"), opened
        )
        self.set_open(record, opened)

    def set_open(self, record, opened):
        record[2] = opened
        record[1].setChecked(opened)
        from tailor.ui_theme import action_icon

        record[1].setText(record[1].property("sectionCaption") or record[1].property("sectionTitle"))
        record[1].setIcon(action_icon("down" if opened else "right", self))
        record[3].setVisible(opened)
        # Nested help/header rows can retain the expanded parent's allocation
        # for a layout cycle. Bound a closed card to its actual header hint;
        # release that bound when opening so dynamic content remains natural.
        section=record[0];section.layout().invalidate()
        section.setMaximumHeight(16777215 if opened else section.layout().sizeHint().height())
        section.updateGeometry();self.open_layout.invalidate();self.open_layout.activate()

    def collapse_all(self):
        for record in self.sections:
            self.set_open(record, False)


def stack(*widgets):
    container = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(7)
    for widget in widgets:
        layout.addWidget(widget)
    return container

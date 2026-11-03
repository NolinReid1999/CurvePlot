"""Align short Chinese field labels without changing their displayed text."""

from PySide6 import QtCore, QtGui, QtWidgets


SHORT_TITLES = {
    '选中列': '选列', '显示值调整': '显示调整', '当前轴比例': '坐标比例',
    '横轴 / 纵轴': '轴线归属', '拟合线显示': '曲线范围',
    '柱间距比例': '柱距比例', '显示点上限': '点数上限',
    'X 误差列': 'X误差列', 'Y 误差列': 'Y误差列',
    '下 X 轴': '下X轴', '左 Y 轴': '左Y轴',
}


def protected(widget):
    node = widget
    while node is not None:
        if node.property('keepFieldTitles'):
            return True
        node = node.parentWidget()
    return False


def _field_text(text):
    return (1 <= len(text) <= 12 and any('\u3400' <= c <= '\u9fff' for c in text)
            and all(c.isalnum() for c in text))


def _short_cjk_label(text):
    return 2 <= len(text) <= 4 and all("\u3400" <= char <= "\u9fff" for char in text)


class DistributedLabel(QtCore.QObject):
    """Paint only short CJK field labels with distributed glyph spacing."""

    def eventFilter(self, label, event):
        if event.type() != QtCore.QEvent.Paint:
            return False
        text = label.text()
        mixed = label.property('distributedFieldTitle') and _field_text(text)
        if not (_short_cjk_label(text) or mixed):
            return False
        painter = QtGui.QPainter(label)
        painter.setPen(label.palette().color(QtGui.QPalette.Text))
        painter.setFont(label.font())
        metrics = label.fontMetrics()
        widths = [metrics.horizontalAdvance(char) for char in text]
        gap = max(0.0, (label.width() - sum(widths)) / (len(widths) - 1))
        x = 0.0
        for char, width in zip(text, widths, strict=True):
            painter.drawText(
                QtCore.QRectF(x, 0, width + 1, label.height()),
                QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
                char,
            )
            x += width + gap
        painter.end()
        return True


def _is_leading_label(layout, label):
    if isinstance(layout, QtWidgets.QFormLayout):
        return layout.labelForField(label) is None and layout.getWidgetPosition(label)[1] == QtWidgets.QFormLayout.LabelRole
    return isinstance(layout, QtWidgets.QHBoxLayout) and layout.indexOf(label) == 0


def _legacy_align_labels(widget):
    """Give a card's fixed leading labels one width and space 2–4 CJK glyphs."""
    labels = []

    # Follow widgets actually participating in layouts. Parked editors under a
    # card are QObject descendants but must not affect the card's label width.
    def collect(layout):
        if layout is None:
            return
        for index in range(layout.count()):
            item = layout.itemAt(index)
            child = item.widget()
            if isinstance(child, QtWidgets.QLabel):
                if child.property("fieldLabel") or (
                    isinstance(layout, QtWidgets.QFormLayout)
                    and layout.getWidgetPosition(child)[1]
                    == QtWidgets.QFormLayout.LabelRole
                ):
                    labels.append((child, layout))
            if child is not None:
                collect(child.layout())
            elif item.layout() is not None:
                collect(item.layout())

    collect(widget.layout())
    leading = [
        label
        for label, layout in labels
        if _is_leading_label(layout, label)
    ]
    if leading:
        width = max(label.fontMetrics().horizontalAdvance(label.text()) for label in leading)
        for label in leading:
            label.setFixedWidth(width)

    for label, _layout in labels:
        if _short_cjk_label(label.text()) and not hasattr(label, "_distributed_label_filter"):
            event_filter = DistributedLabel(label)
            label._distributed_label_filter = event_filter
            label.installEventFilter(event_filter)
            label.update()


def align_labels(widget):
    """Align only field labels, independently for each existing card."""
    # These sections retain exactly the previous alignment and captions.
    if protected(widget):
        _legacy_align_labels(widget)
        return
    labels = []

    def collect(layout):
        if layout is None:
            return
        for index in range(layout.count()):
            item = layout.itemAt(index)
            child = item.widget()
            if child is not None and child is not widget and child.property('foldCard'):
                align_labels(child)
                continue
            if isinstance(child, QtWidgets.QLabel):
                form_label = (isinstance(layout, QtWidgets.QFormLayout)
                              and layout.getWidgetPosition(child)[1] == QtWidgets.QFormLayout.LabelRole)
                grid_label = (isinstance(layout, QtWidgets.QGridLayout)
                              and layout.getItemPosition(index)[1] == 0)
                if child.property('fieldLabel') or form_label or grid_label:
                    text = SHORT_TITLES.get(child.text(), child.text())
                    if _field_text(text):
                        child.setText(text)
                        labels.append(child)
            if child is not None:
                collect(child.layout())
            elif item.layout() is not None:
                collect(item.layout())

    collect(widget.layout())
    if not labels:
        return
    characters = max(len(label.text()) for label in labels)
    width = max(max(label.fontMetrics().horizontalAdvance('汉' * characters),
                    label.fontMetrics().horizontalAdvance(label.text())) for label in labels)
    for label in labels:
        label.setFixedWidth(width)
        label.setWordWrap(False)
        label.setProperty('fieldTitleCharacters', characters)
        label.setProperty('distributedFieldTitle', True)
        if not hasattr(label, '_distributed_label_filter'):
            event_filter = DistributedLabel(label)
            label._distributed_label_filter = event_filter
            label.installEventFilter(event_filter)
        label.update()

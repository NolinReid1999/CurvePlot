"""Legend line samples use the same left-aligned choice painter as other fields."""
from PySide6 import QtWidgets


class LegendCombo(QtWidgets.QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.currentIndexChanged.connect(lambda *_: self.setToolTip(self.currentText()))

    def paintEvent(self, event):
        from tailor.popup_controls import paint_combo
        paint_combo(self)

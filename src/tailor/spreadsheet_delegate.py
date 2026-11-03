"""Spreadsheet commit and navigation rules, independent of table size."""

from PySide6 import QtCore, QtWidgets


class SpreadsheetDelegate(QtWidgets.QStyledItemDelegate):
    def __init__(self, sheet):
        super().__init__(sheet)
        self.sheet = sheet

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        meta = self.sheet.model.column_metadata(index.column())
        option.displayAlignment = {
            "left": QtCore.Qt.AlignLeft,
            "center": QtCore.Qt.AlignHCenter,
            "right": QtCore.Qt.AlignRight,
        }.get(meta.get("halign"), QtCore.Qt.AlignRight) | {
            "top": QtCore.Qt.AlignTop,
            "center": QtCore.Qt.AlignVCenter,
            "bottom": QtCore.Qt.AlignBottom,
        }.get(meta.get("valign"), QtCore.Qt.AlignVCenter)

    def eventFilter(self, editor, event):
        if event.type() == QtCore.QEvent.KeyPress and event.key() in (
            QtCore.Qt.Key_Return,
            QtCore.Qt.Key_Enter,
            QtCore.Qt.Key_Tab,
            QtCore.Qt.Key_Backtab,
        ):
            if isinstance(editor, QtWidgets.QLineEdit) and self.sheet.model.column_metadata(self.sheet.ui.data_view.currentIndex().column()).get("format", "numeric") == "numeric":
                try:
                    if editor.text().strip():
                        float(editor.text())
                except ValueError:
                    editor.setToolTip("请输入有效数值，或按 Esc 保留原值。")
                    self.sheet.main_window.statusBar().showMessage(
                        "无效数值未写入；请修正或按 Esc 取消。"
                    )
                    editor.selectAll()
                    return True
            index = self.sheet.ui.data_view.currentIndex()
            self.commitData.emit(editor)
            self.closeEditor.emit(editor, QtWidgets.QAbstractItemDelegate.NoHint)
            backwards = (
                bool(event.modifiers() & QtCore.Qt.ShiftModifier)
                or event.key() == QtCore.Qt.Key_Backtab
            )
            self.sheet.move_after_edit(index, event.key(), backwards)
            return True
        return super().eventFilter(editor, event)

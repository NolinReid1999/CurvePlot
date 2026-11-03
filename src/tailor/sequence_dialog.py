"""Generate finite float64 arithmetic sequences into a new worksheet column."""

import numpy as np
from PySide6 import QtWidgets


def make_sequence(count, start=0.0, step=1.0):
    if type(count) is not int or not 0 <= count <= 2000000:
        raise ValueError("序列行数必须是 0–2,000,000 的整数。")
    try:
        if isinstance(start, bool) or isinstance(step, bool):
            raise TypeError
        start, step = float(start), float(step)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("起始值和步长必须是有限数字。") from error
    if not np.isfinite(start) or not np.isfinite(step):
        raise ValueError("起始值和步长必须是有限数字。")
    with np.errstate(over="ignore", invalid="ignore"):
        values = start + step * np.arange(count, dtype=float)
    if not np.all(np.isfinite(values)):
        raise ValueError("生成的序列超出数值范围，请调整起始值或步长。")
    return values


class SequenceDialog(QtWidgets.QDialog):
    def __init__(self, count, parent=None):
        super().__init__(parent)
        self.setWindowTitle("生成等差序列到新列")
        self.count, self.values = count, None
        form = QtWidgets.QFormLayout(self)
        form.addRow(QtWidgets.QLabel(f"生成 {count:,} 行，结果写入新列。", self))
        self.name_edit = QtWidgets.QLineEdit("Sequence", self)
        self.start_edit = QtWidgets.QLineEdit("0", self)
        self.step_edit = QtWidgets.QLineEdit("1", self)
        for title, widget in (
            ("列名", self.name_edit),
            ("起始值", self.start_edit),
            ("步长", self.step_edit),
        ):
            form.addRow(title, widget)
        self.error_label = QtWidgets.QLabel(self)
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #b42318")
        form.addRow(self.error_label)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self
        )
        buttons.accepted.connect(self.create_values)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def create_values(self):
        if not self.name_edit.text().strip():
            self.error_label.setText("请填写新列名称。")
            return
        try:
            self.values = make_sequence(
                self.count, self.start_edit.text(), self.step_edit.text()
            )
        except ValueError as error:
            self.error_label.setText(str(error))
            return
        self.accept()

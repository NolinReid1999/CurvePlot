"""Matching fixed header rows for the existing fit and processing panels."""
from PySide6 import QtWidgets
from tailor.graph_controls import row
from tailor.fold_panel import normalize_control_heights


def header_row(title, *controls):
    widget = row(title, *controls)
    label = widget.layout().itemAt(0).widget()
    label.setFixedWidth(label.fontMetrics().horizontalAdvance('选择曲线'))
    from tailor.label_alignment import DistributedLabel
    label._distributed_label_filter=DistributedLabel(label)
    label.installEventFilter(label._distributed_label_filter)
    for control in controls:
        control.setMinimumWidth(0)
        control.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
    normalize_control_heights(widget)
    widget.setFixedHeight(30)
    return widget

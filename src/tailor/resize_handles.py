"""One rounded blue resize affordance for graph windows, ROIs and images."""

from types import MethodType

from PySide6 import QtCore, QtGui, QtWidgets


def draw_handle(painter, point, size=8, color="#2878cc"):
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.setPen(QtGui.QPen(QtGui.QColor(color), 1.3))
    painter.setBrush(QtGui.QColor("#ffffff"))
    painter.drawRoundedRect(
        QtCore.QRectF(point.x() - size / 2, point.y() - size / 2, size, size), 2.5, 2.5
    )


def round_roi(roi, color="#2878cc"):
    def paint(handle, painter, option, widget=None):
        # PG ROI handles live in data coordinates; draw the affordance in pixels.
        painter.save()
        center = painter.worldTransform().map(QtCore.QPointF())
        painter.resetTransform()
        draw_handle(painter, center, 8, color)
        painter.restore()

    for handle in roi.getHandles():
        handle.paint = MethodType(paint, handle)


class ResizeGrip(QtWidgets.QSizeGrip):
    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedSize(17, 17)
        self.setCursor(QtCore.Qt.SizeFDiagCursor)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        draw_handle(painter, QtCore.QPointF(9, 9), 8)

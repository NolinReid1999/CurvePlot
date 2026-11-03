"""Screen-consistent outlines for the existing ROI and inset PlotItem."""

import pyqtgraph as pg
from PySide6 import QtCore, QtGui


def outline(rect, kind):
    path = QtGui.QPainterPath()
    if kind in {"circle", "ellipse"}:
        path.addEllipse(rect)
    elif kind == "rounded":
        path.addRoundedRect(rect, 24, 24, QtCore.Qt.RelativeSize)
    else:
        path.addRect(rect)
    return path


def clip_inset(item, kind):
    """Give cached axis pictures an explicit, axis-local vector clip."""
    import weakref

    frame = outline(item.boundingRect(), kind)
    for side in ('left', 'bottom', 'top', 'right'):
        axis = item.getAxis(side)
        path = item.mapToItem(axis, frame)
        if getattr(axis, '_curve_inset_path', None) != path:
            axis._curve_shape_clipped = True
            axis._curve_inset_frame = weakref.ref(item)
            axis._curve_inset_path = path
            axis.picture = None
            axis.update()
    item._curve_outline_kind = kind


def boundary(rect, kind, point):
    """Project a requested endpoint along a center ray onto the actual outline."""
    center = rect.center()
    delta = point - center
    if abs(delta.x()) + abs(delta.y()) < 1e-9:
        delta = QtCore.QPointF(rect.width(), 0)
    scale = max(
        abs(delta.x()) / max(rect.width() / 2, 1e-12),
        abs(delta.y()) / max(rect.height() / 2, 1e-12),
        1e-9,
    )
    delta = delta / scale * 1.01
    path = outline(rect, kind)
    lo, hi = 0.0, 1.0
    for _ in range(22):
        mid = (lo + hi) / 2
        if path.contains(center + delta * mid):
            lo = mid
        else:
            hi = mid
    return center + delta * ((lo + hi) / 2)


class ShapedROI(pg.RectROI):
    shape_name = "rectangle"

    def shape(self):
        # Hit only a fixed-width outline in scene pixels; the empty interior
        # must pass through to the inset's curves, axes and labels.
        transform=self.sceneTransform()
        rect=transform.mapRect(pg.ROI.boundingRect(self))
        stroker=QtGui.QPainterPathStroker();stroker.setWidth(10)
        path=stroker.createStroke(outline(rect,self.shape_name))
        inverse,ok=transform.inverted()
        return inverse.map(path) if ok else QtGui.QPainterPath()

    def circle_size(self, size, changed=True):
        import math
        transform = self.sceneTransform()
        px = max(1e-12, math.hypot(transform.m11(), transform.m12()))
        py = max(1e-12, math.hypot(transform.m21(), transform.m22()))
        w, h = abs(size[0]), abs(size[1])
        old = self.size()
        # Native handles request absolute sizes throughout a drag. Comparing
        # against the previous constrained circle makes the driving axis flip
        # on successive events; use pyqtgraph's unchanged gesture-start size.
        if hasattr(self, "preMoveState") and any(
            getattr(handle, "isMoving", False) for handle in self.getHandles()
        ):
            old = pg.Point(self.preMoveState["size"])
        if changed:
            use_width = abs(w-old.x())/max(abs(old.x()),1e-12) >= abs(h-old.y())/max(abs(old.y()),1e-12)
            side = w*px if use_width else h*py
        else:
            side = min(w*px,h*py)
        return pg.Point(side/px,side/py)

    def setSize(self, size, *args, **kwargs):
        if self.shape_name == "circle" and self.scene() is not None:
            size = self.circle_size(pg.Point(size))
        return super().setSize(size, *args, **kwargs)

    def ensure_circle(self):
        if self.shape_name == "circle":
            size = self.circle_size(self.size(), changed=False)
            if abs(size.x()-self.size().x())+abs(size.y()-self.size().y()) > 1e-10:
                with QtCore.QSignalBlocker(self):
                    super().setSize(size)

    def paint(self, painter, option, widget=None):
        # Qt does not clip an item's paint to boundingRect. Keep cosmetic strokes
        # inside it and build rounded corners in screen space (not data units).
        painter.save()
        transform = painter.worldTransform()
        rect = transform.mapRect(pg.ROI.boundingRect(self))
        pen = QtGui.QPen(self.currentPen)
        pen.setCosmetic(True)
        inset = max(0.5, pen.widthF() / 2)
        rect.adjust(inset, inset, -inset, -inset)
        painter.resetTransform()
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawPath(outline(rect, self.shape_name))
        painter.restore()


def shape_icon(kind):
    pix = QtGui.QPixmap(84, 64)
    pix.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setPen(QtGui.QPen(QtGui.QColor("#448ad5"), 3))
    p.setBrush(QtCore.Qt.NoBrush)
    rect = QtCore.QRectF(
        15 if kind == "circle" else 4,
        13 if kind == "ellipse" else 4,
        54 if kind == "circle" else 76,
        38 if kind == "ellipse" else 54,
    )
    p.drawPath(outline(rect, kind))
    p.end()
    pix.setDevicePixelRatio(2)
    return QtGui.QIcon(pix)


def cap_icon(kind):
    pix = QtGui.QPixmap(96, 52)
    pix.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    pen = QtGui.QPen(QtGui.QColor("#448ad5"), 13)
    pen.setCapStyle(
        {
            "round": QtCore.Qt.RoundCap,
            "flat": QtCore.Qt.FlatCap,
            "square": QtCore.Qt.SquareCap,
        }[kind]
    )
    p.setPen(pen)
    p.drawLine(20, 26, 73, 26)
    p.setPen(QtGui.QPen(QtGui.QColor("#8594a6"), 1, QtCore.Qt.DashLine))
    p.drawLine(20, 8, 20, 44)
    p.drawLine(73, 8, 73, 44)
    p.end()
    pix.setDevicePixelRatio(2)
    return QtGui.QIcon(pix)

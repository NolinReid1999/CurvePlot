"""Lightweight grid decoration drawn from native AxisItem tick positions."""

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets


class AxisGrid(QtWidgets.QGraphicsObject):
    def __init__(self, presentation):
        self.presentation = presentation
        self.box = presentation.owner.ui.plot_widget.getViewBox()
        super().__init__(self.box)
        self.setZValue(-1)
        self.setAcceptedMouseButtons(QtCore.Qt.NoButton)
        self.box.sigRangeChanged.connect(lambda *args: self.update())
        self.box.sigResized.connect(self.resized)

    def resized(self):
        self.prepareGeometryChange()
        self.update()

    def boundingRect(self):
        return self.box.rect()

    def paint(self, painter, option, widget):
        from tailor.graph_presentation import AXES

        rect = self.boundingRect()
        painter.setClipRect(rect)
        for key, side in AXES.items():
            cfg = self.presentation.axes[key]
            if not (cfg["grid"] or cfg["minor_grid"]):
                continue
            box = (
                self.presentation.right_box
                if key == "right"
                else self.presentation.top_box
                if key == "top"
                else self.box
            )
            horizontal = key in {"x", "top"}
            box = box or self.box
            bounds = box.viewRange()[0 if horizontal else 1]
            axis = self.presentation.owner.ui.plot_widget.getAxis(side)
            ticks = axis.tickValues(
                *bounds, rect.width() if horizontal else rect.height()
            )
            while len(ticks) < 2:
                ticks.append((1, []))
            if cfg["minor_grid"] and not len(ticks[1][1]) and ticks[0][0] > 0:
                # Grid decoration remains available when minor tick marks are off.
                step = cfg.get("minor") or ticks[0][0] / 5
                values = (
                    np.arange(np.ceil(bounds[0] / step), np.floor(bounds[1] / step) + 1)
                    * step
                    if (bounds[1] - bounds[0]) / step < 2500
                    else []
                )
                values = np.asarray(values)
                values = values[
                    ~np.isclose(values / ticks[0][0], np.rint(values / ticks[0][0]))
                ]
                ticks[1] = (step, values)
            for level, (_, values) in enumerate(ticks[:2]):
                if not cfg["grid" if level == 0 else "minor_grid"]:
                    continue
                count = cfg.get("grid_count" if level == 0 else "minor_grid_count", 0)
                if count:
                    values = np.linspace(bounds[0], bounds[1], count + 2)[1:-1]
                color = QtGui.QColor(cfg["grid_color"])
                color.setAlpha(
                    round((200 if level == 0 else 110) * cfg.get("grid_opacity", 1.0))
                )
                from tailor.line_styles import curve_pen

                pen = curve_pen(
                    color,
                    cfg["grid_width"]
                    * (
                        self.presentation.owner.ui.plot_widget.property(
                            "exportPixelScale"
                        )
                        or 1
                    ),
                    cfg["grid_style"],
                )
                painter.setPen(pen)
                for value in values[:500]:
                    pt = box.mapViewToScene(
                        QtCore.QPointF(
                            value if horizontal else 0, 0 if horizontal else value
                        )
                    )
                    pt = self.mapFromScene(pt)
                    if horizontal:
                        painter.drawLine(
                            QtCore.QPointF(pt.x(), rect.top()),
                            QtCore.QPointF(pt.x(), rect.bottom()),
                        )
                    else:
                        painter.drawLine(
                            QtCore.QPointF(rect.left(), pt.y()),
                            QtCore.QPointF(rect.right(), pt.y()),
                        )

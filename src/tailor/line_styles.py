"""Shared Qt line patterns for single and combined curves."""

import pyqtgraph as pg
from PySide6 import QtCore

LINE_STYLES = [
    ("实线", "solid"),
    ("虚线", "dash"),
    ("点线", "dot"),
    ("点划线", "dashdot"),
    ("双点划线", "dashdotdot"),
    ("长虚线", "longdash"),
    ("短虚线", "shortdash"),
]


def curve_pen(color, width, pattern):
    from tailor.appearance import ink

    pen = pg.mkPen(
        ink(color),
        width=width,
        style={
            "solid": QtCore.Qt.SolidLine,
            "dash": QtCore.Qt.DashLine,
            "dot": QtCore.Qt.DotLine,
            "dashdot": QtCore.Qt.DashDotLine,
            "dashdotdot": QtCore.Qt.DashDotDotLine,
        }.get(pattern, QtCore.Qt.DashLine),
    )
    if pattern in {"longdash", "shortdash"}:
        pen.setDashPattern([8, 3] if pattern == "longdash" else [2, 2])
    return pen


def apply_curve_extras(item, style):
    from PySide6 import QtGui

    item.setOpacity(style.opacity)
    pen = item.opts.get("pen")
    if pen is not None:
        pen = pg.mkPen(pen)
        pen.setCapStyle(
            {
                "round": QtCore.Qt.RoundCap,
                "flat": QtCore.Qt.FlatCap,
                "square": QtCore.Qt.SquareCap,
            }[style.cap]
        )
        pen.setJoinStyle(
            {
                "round": QtCore.Qt.RoundJoin,
                "bevel": QtCore.Qt.BevelJoin,
                "miter": QtCore.Qt.MiterJoin,
            }[style.join]
        )
        item.setPen(pen)
    from tailor.appearance import ink

    item.setSymbolBrush(ink(style.color) if style.marker_fill else None)
    item.setFillLevel(0 if style.fill or style.mode in {"area", "bar"} else None)
    color = QtGui.QColor(style.fill_color)
    color.setAlphaF(0.18)
    item.setBrush(color if style.fill or style.mode in {"area", "bar"} else None)
    item.opts["stepMode"] = (
        "left"
        if style.mode == "step"
        or (style.step_mode and style.mode in {"line", "line_scatter", "area"})
        else None
    )
    if (
        int(style.marker_step) > 1
        and item.xData is not None
        and style.mode in {"scatter", "line_scatter"}
    ):
        symbols = [None] * len(item.xData)
        symbols[:: int(style.marker_step)] = [style.marker] * len(
            symbols[:: int(style.marker_step)]
        )
        item.setSymbol(symbols)
    item.updateItems(styleUpdate=True)

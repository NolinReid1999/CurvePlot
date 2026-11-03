"""Recolor existing scene items without reading source columns or rebuilding plots."""

import pyqtgraph as pg
from PySide6 import QtCore

from tailor.appearance import ink
from tailor.graph_presentation import AXES
from tailor.line_styles import curve_pen


def style_colors(item, style):
    if item is None:
        return
    pen = (
        None
        if style.mode == "scatter"
        else curve_pen(style.color, style.line_width, style.line_style)
    )
    if pen is not None:
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
    if item.opts.get("symbol") is not None:
        item.setSymbolPen(ink(style.color))
        item.setSymbolBrush(ink(style.color) if style.marker_fill else None)


def apply_plot_theme(plot, background):
    from tailor.curve_style import CurveStyle
    from tailor.text_style_controls import apply_text_styles

    plot.setUpdatesEnabled(False)
    try:
        plot.ui.plot_widget.setBackground(background)
        pres = plot.presentation
        if pres.multi:
            for source, series in plot._series.items():
                info = plot.model.get_plot_info(source)
                style = (
                    CurveStyle(**info.style)
                    if info and info.style
                    else source.curve_style
                )
                if info:
                    from dataclasses import replace
                    style = replace(style, color=info.color)
                style_colors(series.get("data"), style)
        else:
            style_colors(plot.plot, plot.curve_style)
        for item in plot.ui.plot_widget.listDataItems():
            key = getattr(item, "_legend_key", None)
            spec = pres.curve_overrides.get(key)
            if spec:
                style_colors(item, CurveStyle(**spec))
        for key, side in AXES.items():
            config = pres.axes[key]
            axis = plot.ui.plot_widget.getAxis(side)
            axis.setPen(pg.mkPen(ink(config["color"]), width=config["axis_width"]))
        apply_text_styles(plot)
        pres.grid_item.update()
        if hasattr(plot, "annotations"):
            plot.annotations.redraw()
        if hasattr(plot, "extras"):
            from tailor.inset_collection import entries
            for entry in entries(plot):
                entry.refresh_inset()
    finally:
        plot.setUpdatesEnabled(True)
        plot.ui.plot_widget.update()

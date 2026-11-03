"""Export the existing Qt plot scene without rebuilding it in a second renderer."""

import os
import tempfile
from pathlib import Path

import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtSvg


def scale_cosmetic_pens(view, factor):
    """Scale device-pixel strokes for raster density; return a restoration list."""
    changes = []
    if factor == 1:
        return changes

    def scaled(value):
        pen = pg.mkPen(value)
        if not pen.isCosmetic():
            return value
        pen.setWidthF((pen.widthF() or 1.0) * factor)
        return pen

    for item in view.scene().items():
        if isinstance(item, pg.AxisItem):
            changes.append(("axis", item, (item._pen, item._tickPen, item.picture)))
            pen, tick = item.pen(), item.tickPen()
            item._pen, item._tickPen, item.picture = scaled(pen), scaled(tick), None
        else:
            opts = getattr(item, "opts", None)
            if isinstance(opts, dict):
                for key in ("pen", "shadowPen", "symbolPen"):
                    if opts.get(key) is not None:
                        changes.append(("option", opts, (key, opts[key])))
                        opts[key] = scaled(opts[key])
            elif isinstance(getattr(item, "pen", None), QtGui.QPen):
                changes.append(("attribute", item, item.pen))
                item.pen = scaled(item.pen)
    return changes


def restore_cosmetic_pens(changes):
    for kind, obj, value in reversed(changes):
        if kind == "axis":
            obj._pen, obj._tickPen, obj.picture = value
        elif kind == "option":
            key, pen = value
            obj[key] = pen
        else:
            obj.pen = value


def export_canvas(plot, filename, dpi=None, view_override=None):
    from tailor.app_preferences import export_options
    dpi, background_mode = export_options(dpi)
    path = Path(filename)
    suffix = path.suffix.lower()
    if suffix not in {".png", ".svg", ".pdf"}:
        raise ValueError("请选择 PNG、SVG 或 PDF。")
    view = view_override if view_override is not None else plot.ui.plot_widget
    source = view.viewport().rect()
    if source.isEmpty():
        raise ValueError("图形尚未显示，无法导出。")
    width, height = source.width(), source.height()
    # Qt point fonts use the paint device DPI, independently of render() scaling.
    # Keep it identical to the live viewport while painting; only raster pixels
    # and the final file's print-resolution metadata use the requested export DPI.
    logical_x, logical_y = view.viewport().logicalDpiX(), view.viewport().logicalDpiY()
    fd, temp = tempfile.mkstemp(
        prefix="." + path.stem + "-", suffix=suffix, dir=path.parent
    )
    os.close(fd)
    hidden = []
    native_selections = []
    native = getattr(getattr(plot, "advanced_view", None), "native", None)
    if native:
        for doc in native.live():
            annotations = getattr(doc, "annotations", None)
            if annotations:
                native_selections.append((annotations, annotations.selected))
                annotations.selected = None
            for obj, attrs in (
                (getattr(doc, "point_inspector", None), ("marker", "highlight")),
                (getattr(doc, "text_selection", None), ("rect",)),
                (getattr(doc, "curve_selection", None), ("halo",)),
                (getattr(doc, "processing_controls", None), ("analysis_region",)),
                (annotations, ("preview",)),
                (getattr(doc, "extras", None), ("layout_roi",)),
                (
                    getattr(
                        getattr(doc, "preset_controls", None), "manual_peaks", None
                    ),
                    ("marker",),
                ),
            ):
                for attr in attrs:
                    item = getattr(obj, attr, None)
                    if item is not None:
                        hidden.append((item, item.isVisible()))
                        item.hide()
            extras = getattr(doc, "extras", None)
            if extras is not None and hasattr(extras, "range_roi"):
                for handle in extras.range_roi.getHandles():
                    hidden.append((handle, handle.isVisible()))
                    handle.hide()
    # UI selection decorations are never part of the scientific figure.
    for obj, attrs in (
        (getattr(plot, "point_inspector", None), ("marker", "highlight")),
        (getattr(plot, "text_selection", None), ("rect",)),
        (getattr(plot, "annotations", None), ("preview",)),
        (getattr(plot, "curve_selection", None), ("halo",)),
        (getattr(plot, "processing_controls", None), ("analysis_region",)),
        (getattr(plot, "extras", None), ("layout_roi",)),
        (
            getattr(getattr(plot, "preset_controls", None), "manual_peaks", None),
            ("marker",),
        ),
    ):
        for attr in attrs:
            item = getattr(obj, attr, None)
            if item is not None:
                hidden.append((item, item.isVisible()))
                item.hide()
    extras = getattr(plot, "extras", None)
    if extras is not None and hasattr(extras, "range_roi"):
        for handle in extras.range_roi.getHandles():
            hidden.append((handle, handle.isVisible()))
            handle.hide()
    annotations = getattr(plot, "annotations", None)
    if annotations is not None:
        for item in getattr(annotations, "handles", []):
            if hasattr(item, "hide"):
                hidden.append((item, item.isVisible()))
                item.hide()
    selection = getattr(plot, "curve_selection", None)
    if selection is not None:
        selection.suspended = True
        selection.refresh()
    annotation_selection = annotations.selected if annotations else None
    if annotations:
        annotations.selected = None
        annotations.redraw()
    background = view.backgroundBrush()
    transparent = background_mode == 'transparent' or (background_mode == 'graph' and plot.curve_style.transparent)
    vectors = []
    for item in view.scene().items():
        if isinstance(item, pg.ScatterPlotItem):
            vectors.append((item, item._exportOpts))
            item.setExportMode(True, {"antialias": True})
    painter = QtGui.QPainter()
    pen_changes = []
    try:
        if transparent:
            view.setBackground(None)
        if suffix == ".png":
            scale = max(1, dpi / logical_x)
            device = QtGui.QImage(
                round(width * scale),
                round(height * scale),
                QtGui.QImage.Format_ARGB32_Premultiplied,
            )
            device.fill(QtCore.Qt.transparent)
            # Device pixels, rather than a view transform, scale cosmetic pens,
            # fixed-pixel scatter symbols and ItemIgnoresTransformations legends.
            device.setDevicePixelRatio(scale)
            device.setDotsPerMeterX(round(logical_x / 0.0254))
            device.setDotsPerMeterY(round(logical_y / 0.0254))
            target = QtCore.QRectF(0, 0, width, height)
        elif suffix == ".svg":
            device = QtSvg.QSvgGenerator()
            device.setFileName(temp)
            device.setSize(QtCore.QSize(width, height))
            device.setViewBox(QtCore.QRect(0, 0, width, height))
            device.setResolution(logical_x)
            target = QtCore.QRectF(0, 0, width, height)
        else:
            device = QtGui.QPdfWriter(temp)
            device.setResolution(logical_x)
            device.setPageSize(
                QtGui.QPageSize(
                    QtCore.QSizeF(width * 25.4 / logical_x, height * 25.4 / logical_y),
                    QtGui.QPageSize.Millimeter,
                )
            )
            device.setPageMargins(QtCore.QMarginsF(0, 0, 0, 0))
            target = QtCore.QRectF(0, 0, device.width(), device.height())
        stroke_scale = device.devicePixelRatioF() / view.viewport().devicePixelRatioF()
        pen_changes = scale_cosmetic_pens(view, stroke_scale)
        view.setProperty("exportPixelScale", stroke_scale)
        if not painter.begin(device):
            raise OSError("无法创建导出画布。")
        painter.setRenderHints(
            QtGui.QPainter.Antialiasing | QtGui.QPainter.TextAntialiasing
        )
        if not transparent:
            painter.fillRect(target, background)
        view.render(painter, target, source, QtCore.Qt.KeepAspectRatio)
        painter.end()
        if suffix == ".png":
            device.setDevicePixelRatio(1)
            device.setDotsPerMeterX(round(dpi / 0.0254))
            device.setDotsPerMeterY(round(dpi / 0.0254))
            if not device.save(temp, "PNG"):
                raise OSError("PNG 写入失败。")
        if Path(temp).stat().st_size == 0:
            raise OSError("导出为空，未覆盖目标文件。")
        os.replace(temp, path)
    finally:
        if painter.isActive():
            painter.end()
        restore_cosmetic_pens(pen_changes)
        view.setProperty("exportPixelScale", None)
        for item, options in vectors:
            item.setExportMode(
                options is not False, options if options is not False else None
            )
        if transparent:
            view.setBackground(background)
        if selection is not None:
            selection.suspended = False
            selection.refresh()
        if annotations:
            annotations.selected = annotation_selection
            annotations.redraw()
        for item, visible in hidden:
            item.setVisible(visible)
        for manager, selected in native_selections:
            manager.selected = selected
            manager.redraw()
        if os.path.exists(temp):
            os.unlink(temp)

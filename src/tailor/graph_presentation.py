"""Presentation adapters for Tailor plots, using native Qt/Matplotlib axes.

All ranges and source arrays remain in physical coordinates. Only Qt display
coordinates are logarithmic. No display filter is written back to a worksheet.
"""

import copy
import math

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui

from tailor.axis_format import format_tick

AXES = {"x": "bottom", "top": "top", "y": "left", "right": "right"}


def axis_defaults():
    return {
        "log": False,
        "inverted": False,
        "major": None,
        "major_count": 5,
        "minor": None,
        "minor_visible": True,
        "major_visible": True,
        "expression": "",
        "grid_count": 0,
        "minor_grid_count": 0,
        "notation": "fixed",
        "precision": 0,
        "tick_angle": 0.0,
        "direction": "out",
        "grid": False,
        "visible": True,
        "color": "#202020",
        "minor_count": 4,
        "labels": True,
        "title_visible": True,
        "axis_width": 1.0,
        "tick_length": 5.0,
        "minor_length": 3.0,
        "divisor": 1.0,
        "prefix": "",
        "suffix": "",
        "minor_grid": False,
        "grid_color": "#9ba5b1",
        "grid_width": 0.5,
        "grid_style": "solid",
    }


def display(values, log=False):
    values = np.asarray(values, dtype=float)
    if isinstance(log, dict):
        from tailor.axis_extensions import map_break

        transformed = display(values, log["log"])
        return map_break(transformed, log)
    if not log:
        return values
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(values > 0, np.log10(values), np.nan)


def physical(values, log=False):
    if isinstance(log, dict):
        from tailor.axis_extensions import map_break

        return physical(map_break(values, log, inverse=True), log["log"])
    if not log:
        return np.asarray(values)
    with np.errstate(over="ignore"):
        return 10.0 ** np.asarray(values)


def data_limits(values, log=False, padding=0.05):
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite) & ((finite > 0) if log else True)]
    if not len(finite):
        return (1.0, 10.0) if log else (0.0, 1.0)
    low, high = float(np.min(finite)), float(np.max(finite))
    if low == high:
        return (
            (low / 1.1, high * 1.1)
            if log
            else (low - max(abs(low) * 0.05, 0.5), high + max(abs(high) * 0.05, 0.5))
        )
    a, b = display([low, high], log)
    pad = (b - a) * padding
    return tuple(physical([a - pad, b + pad], log))


class NumberAxis(pg.AxisItem):
    def boundingRect(self):
        rect = super().boundingRect()
        if getattr(self, "settings", {}).get("break_enabled"):
            # AxisItem clips its picture to this rect after drawing labels.
            # Include both halves of the break mark and its clearing stroke.
            return (
                rect.adjusted(0, -8, 0, 8)
                if self.orientation in {"top", "bottom"}
                else rect.adjusted(-8, 0, 8, 0)
            )
        return rect

    def __init__(self, orientation, settings):
        self.settings = settings
        super().__init__(orientation=orientation)
        self.enableAutoSIPrefix(False)
        self.setStyle(maxTextLevel=0,hideOverlappingLabels=False)

    def tickStrings(self, values, scale, spacing):
        values = physical(values, self.settings)
        from tailor.tick_expression import calculate
        from tailor.axis_tick_policy import label_precision,numeric_spacing,display_format

        labels = []
        from tailor.axis_extensions import special_string

        for value in values:
            special = special_string(self, value)
            if special is not None:
                labels.append(special)
                continue
            try:
                expression = self.settings.get("expression", "")
                number = (
                    calculate(expression, value)
                    if expression
                    else value / self.settings["divisor"]
                )
                physical_step=(value*abs(np.expm1((spacing or 0)*np.log(10)))) if self.settings['log'] else (spacing or 0)
                label_step=numeric_spacing(self.settings,physical_step,value)
                formatted=display_format(self.settings,label_step)
                labels.append(
                    self.settings["prefix"]
                    + format_tick(number,formatted['notation'],label_precision(formatted,label_step,number))
                    + self.settings["suffix"]
                )
            except ValueError:
                labels.append("")
        from tailor.axis_text import custom
        from tailor.text_accents import caption
        labels=[caption(custom(self,v)) if custom(self,v) is not None else text for v,text in zip(values,labels)]
        self._tick_candidates=getattr(self,'_tick_candidates',[])+list(zip(values,labels))
        return labels

    def generateDrawSpecs(self,painter):
        self._tick_candidates=[]
        from tailor.axis_text import specs
        return specs(self,super().generateDrawSpecs(painter))

    def _updateMaxTextSize(self,value):
        from tailor.axis_text import effective_angle
        if effective_angle(self.settings) or self.settings.get('tick_text'):
            value=max(value,getattr(self,'_tick_rotated_extent',0))
        super()._updateMaxTextSize(value)

    def tickValues(self, minVal, maxVal, size):
        from tailor.axis_extensions import special_ticks

        special = special_ticks(self, minVal, maxVal, size)
        if special is not None:
            return special
        from tailor.axis_tick_policy import major_spacing
        major=major_spacing(self.settings,minVal,maxVal)
        levels = super().tickValues(minVal, maxVal, size)
        if major is None or major <= 0 or not math.isfinite(minVal / major):
            return levels[:1]
        from tailor.axis_tick_policy import linear_ticks
        result = []
        count = self.settings['minor_count'] if self.settings['minor_visible'] else 0
        for step in (major,(self.settings.get('minor') or major/(count+1))
                     if self.settings['minor_visible'] and (count or self.settings.get('minor')) else None):
            if step is None:continue
            values=np.asarray(linear_ticks(minVal,maxVal,step))
            if result:values=values[~np.isclose(values/major,np.rint(values/major),atol=1e-8,rtol=0)]
            result.append((step,values.tolist()))
        self._tick_density_reduced=(maxVal-minVal)/major>500
        return result

    def drawPicture(self, painter, axisSpec, tickSpecs, textSpecs):
        # Retain native layout but reject colliding labels across a compressed
        # break. A physical discontinuity must not turn two labels into one.
        if self.settings.get("break_enabled"):
            horizontal = self.orientation in {"top", "bottom"}
            ordered = sorted(
                textSpecs,
                key=lambda spec: spec[0].left() if horizontal else spec[0].top(),
            )
            accepted = []
            end = -float("inf")
            for spec in ordered:
                rect = spec[0]
                start = rect.left() if horizontal else rect.top()
                if start >= end + 7:
                    accepted.append(spec)
                    end = rect.right() if horizontal else rect.bottom()
            textSpecs = accepted
        # Retain the native axis layout; expose explicit short/long tick lengths.
        from PySide6 import QtCore

        self._curve_tick_text_rects = [
            QtCore.QRectF(rect) for rect, flags, text in textSpecs
        ]
        self._curve_axis_line = (
            QtCore.QRectF(axisSpec[1], axisSpec[2]).normalized().adjusted(-4, -4, 4, 4)
        )
        adjusted = []
        for pen, start, end in tickSpecs:
            if self.style["tickLength"] == 0:
                continue
            delta = end - start
            length = math.hypot(delta.x(), delta.y())
            main = abs(self.style["tickLength"])
            if length and abs(length - main) > 0.1:
                end = QtCore.QPointF(
                    start.x() + delta.x() * self.settings["minor_length"] / length,
                    start.y() + delta.y() * self.settings["minor_length"] / length,
                )
            # Qt offsets the axis line by one pixel. Anchor every tick on that
            # exact line, so outward ticks never straddle it.
            horizontal = self.orientation in {"top", "bottom"}
            if abs(length - main) < 0.1 and not self.settings.get(
                "major_visible", True
            ):
                continue
            requested = (
                self.settings["tick_length"]
                if abs(length - main) < 0.1
                else self.settings["minor_length"]
            )
            sign = -1 if self.orientation in {"top", "left"} else 1
            if self.settings["direction"] == "in":
                sign *= -1
            start = QtCore.QPointF(start)
            end = QtCore.QPointF(start)
            if horizontal:
                start.setY(axisSpec[1].y())
                end.setY(start.y() + sign * requested)
            else:
                start.setX(axisSpec[1].x())
                end.setX(start.x() + sign * requested)
            adjusted.append((pen, start, end))
        # Keep pyqtgraph's axis/tick strokes; all text uses the same Qt layout.
        inset_clip = getattr(self, '_curve_shape_clipped', False)
        if inset_clip:
            from tailor.inset_shapes import outline
            frame = self._curve_inset_frame()
            clip_path = frame.mapToItem(self, outline(frame.boundingRect(), frame._curve_outline_kind))
            painter.save()
            painter.setClipPath(clip_path, QtCore.Qt.IntersectClip)
        super().drawPicture(painter, axisSpec, adjusted, [])
        if inset_clip:
            # AxisItem records a replacement clip in its cached picture.
            # Its cached replacement clip must not escape the inset outline.
            painter.setClipPath(clip_path, QtCore.Qt.IntersectClip)
        painter.setPen(self.textPen())
        if self.style['tickFont'] is not None:painter.setFont(self.style['tickFont'])
        from tailor.axis_text import draw
        draw(self,painter,textSpecs)
        if self.settings.get("break_enabled"):
            from tailor.axis_extensions import break_limits

            low, _high, gap = break_limits(self.settings)
            span = max(self.range[1] - self.range[0], 1e-12)
            fractions = [
                (low - self.range[0]) / span,
                (low + gap - self.range[0]) / span,
            ]
            if fractions[1] > 0 and fractions[0] < 1:
                a, b = axisSpec[1], axisSpec[2]
                horizontal = self.orientation in {"top", "bottom"}
                points = [
                    (
                        QtCore.QPointF(a.x() + (b.x() - a.x()) * f, a.y())
                        if horizontal
                        else QtCore.QPointF(a.x(), a.y() + (b.y() - a.y()) * (1 - f))
                    )
                    for f in fractions
                ]
                from tailor.appearance import manager

                painter.save()
                painter.setRenderHint(QtGui.QPainter.Antialiasing)
                painter.setPen(
                    QtGui.QPen(
                        QtGui.QColor("#000000" if manager().dark(True) else "#ffffff"),
                        10,
                    )
                )
                painter.drawLine(points[0], points[1])
                pen = QtGui.QPen(axisSpec[0])
                pen.setWidthF(max(1.8, pen.widthF()))
                painter.setPen(pen)
                for point, fraction in zip(points, fractions):
                    if not 0 < fraction < 1:
                        continue
                    path = QtGui.QPainterPath()
                    if horizontal:
                        path.moveTo(point + QtCore.QPointF(-4, 0))
                        path.lineTo(point + QtCore.QPointF(-2, -5))
                        path.lineTo(point + QtCore.QPointF(2, 5))
                        path.lineTo(point + QtCore.QPointF(4, 0))
                    else:
                        path.moveTo(point + QtCore.QPointF(0, -4))
                        path.lineTo(point + QtCore.QPointF(-5, -2))
                        path.lineTo(point + QtCore.QPointF(5, 2))
                        path.lineTo(point + QtCore.QPointF(0, 4))
                    painter.drawPath(path)
                painter.restore()
        if inset_clip:
            painter.restore()


class SelectionSample(
    __import__("pyqtgraph.graphicsItems.LegendItem", fromlist=["ItemSample"]).ItemSample
):
    """Legend samples select via the scene route; they never toggle visibility."""

    def mouseClickEvent(self, event):
        event.accept()


class MovableLegend(pg.LegendItem):
    def __init__(self, presentation):
        self.presentation = presentation
        self._anchor_parent = None
        super().__init__(offset=(-12, 12), sampleType=SelectionSample)

    def addItem(self, item, name):
        # Samples may hold a styled proxy; identify the real curve and its
        # stable key before any caller adds a label during queued redraw/zoom.
        key = getattr(item, '_legend_key', None)
        for sample, label in self.items:
            source = getattr(sample, '_source_item', sample.item)
            if source is item or (key is not None and getattr(source, '_legend_key', None) == key):
                sample._source_item = item
                sample.item = item
                label._original_text = name
                label.setText(name)
                sample.update()
                self.updateSize()
                return
        return super().addItem(item, name)

    def anchor(self, *args, **kwargs):
        super().anchor(*args, **kwargs)
        parent = self.parentItem()
        if parent is not self._anchor_parent:
            if self._anchor_parent is not None:
                self._anchor_parent.destroyed.disconnect(self.release_anchor)
            self._anchor_parent = parent
            parent.destroyed.connect(self.release_anchor)

    def release_anchor(self, *_):
        # pyqtgraph has no public unanchor operation. Its queued geometry slot
        # can outlive a ViewBox during scene teardown. Clear the anchor before
        # that slot runs, including when Qt destroys a scene at app shutdown.
        self._GraphicsWidgetAnchor__parent = None
        self._GraphicsWidgetAnchor__itemAnchor = None
        self._anchor_parent = None

    def _GraphicsWidgetAnchor__geometryChanged(self):
        # Qt can delete the parent before emitting destroyed to this widget.
        # Guard the inherited slot itself, not just the close signal order.
        import shiboken6
        from pyqtgraph.graphicsItems.GraphicsWidgetAnchor import GraphicsWidgetAnchor

        parent = getattr(self, "_GraphicsWidgetAnchor__parent", None)
        if parent is not None and shiboken6.isValid(self) and shiboken6.isValid(parent):
            GraphicsWidgetAnchor._GraphicsWidgetAnchor__geometryChanged(self)

    def mouseDragEvent(self, event):
        if event.isStart():
            self._drag_before = dict(self.presentation.legend)
        super().mouseDragEvent(event)
        if event.isFinish():
            parent = self.parentItem().boundingRect()
            self.presentation.legend["position"] = [
                self.pos().x() / max(1, parent.width()),
                self.pos().y() / max(1, parent.height()),
            ]
            import copy

            from tailor.text_style_controls import record_view_edit

            def restore(plot, state):
                plot.presentation.legend = copy.deepcopy(state)
                plot.presentation.apply_legend()
                controls = getattr(plot, 'legend_controls', None)
                if controls is not None:
                    controls.sync()

            record_view_edit(
                self.presentation.owner,
                "移动图例",
                getattr(self, "_drag_before", dict(self.presentation.legend)),
                copy.deepcopy(self.presentation.legend),
                restore,
            )
            controls = getattr(self.presentation.owner, 'legend_controls', None)
            if controls is not None:
                controls.sync()
            self.presentation.owner.main_window.mark_project_dirty()


class ErrorItems:
    """Separate native error items give X and Y caps a constant pixel size."""

    def __init__(self, box):
        self.box = box
        self.x = pg.ErrorBarItem()
        self.y = pg.ErrorBarItem()
        box.addItem(self.x, ignoreBounds=True)
        box.addItem(self.y, ignoreBounds=True)
        self.cap = 0
        box.sigRangeChanged.connect(self.update_caps)

    def update(self, x, y, ex, ey, config, color, xlog=False, ylog=False):
        px, py = display(x, xlog), display(y, ylog)
        valid = np.isfinite(px) & np.isfinite(py)
        pen = pg.mkPen(config.get("color") or color, width=config.get("width", 1.0))
        self.cap = config.get("cap", 4.0)
        for item, err, values, is_log, horizontal, enabled in (
            (self.x, ex, x, xlog, True, config.get("x_visible", True)),
            (self.y, ey, y, ylog, False, config.get("y_visible", True)),
        ):
            err = np.broadcast_to(err, np.shape(values))
            mask = valid & np.isfinite(err) & (err > 0) & enabled
            # A log error crossing zero has no representable lower endpoint.
            # Omit that side, retaining center and positive side; data is untouched.
            center = display(values, is_log)
            lower = center - display(values - err, is_log)
            upper = display(values + err, is_log) - center
            lower = np.where(np.isfinite(lower), lower, 0)
            upper = np.where(np.isfinite(upper), upper, 0)
            sides = (
                {"left": lower[mask], "right": upper[mask]}
                if horizontal
                else {"bottom": lower[mask], "top": upper[mask]}
            )
            item.setData(x=px[mask], y=py[mask], pen=pen, **sides)
        self.update_caps()

    def update_caps(self, *args):
        dx, dy = self.box.viewPixelSize()
        self.x.setData(beam=abs(dy) * self.cap * 2)
        self.y.setData(beam=abs(dx) * self.cap * 2)

    def close(self):
        try:
            self.box.sigRangeChanged.disconnect(self.update_caps)
        except (RuntimeError, TypeError):
            pass
        self.box.removeItem(self.x)
        self.box.removeItem(self.y)


def error_defaults():
    return {"x_visible": False, "y_visible": False, "cap": 4.0, "width": 1.0, "color": ""}


class GraphPresentation:
    def __init__(self, owner, multi=False):
        self.owner, self.multi = owner, multi
        self.axes = {key: axis_defaults() for key in AXES}
        if not multi:
            for key, mode in getattr(owner.model, "_axis_modes", {}).items():
                self.axes[key]["axis_type"] = mode
        for key in ("top", "right"):
            self.axes[key].update(visible=False, title_visible=False)
        self.curve_overrides = {}
        self.extra_settings = {}
        self.trend_sources = []
        self._trend_items = {}
        self.text_offsets = {}
        self.single_sides = {"x": "bottom", "y": "left"}
        from tailor.graph_defaults import axis_settings
        defaults = axis_settings()
        import json

        for key in AXES:
            try:
                candidate = {**self.axes[key], **json.loads(defaults.value(key, "{}"))}
                self.validate_axis(candidate)
                self.axes[key].update(candidate)
            except (ValueError, TypeError):
                pass
        self.legend = {
            "columns": 1,
            "border": False,
            "background": False,
            "position": None,
            "visible": True,
        }
        self.errors = error_defaults()
        self.frame = {"top": False, "right": False, "bottom": True, "left": True}
        self.margins = {"left": 20, "right": 20, "top": 20, "bottom": 20}
        self.top_label = "上 X"
        self.top_min = self.top_max = None
        self.top_box = self.top_right_box = None
        self.right_label = "右 Y"
        self.right_min = self.right_max = None
        self.right_box = None
        from tailor.graph_defaults import apply

        apply(self)
        item = owner.ui.plot_widget.getPlotItem()
        item.setAxisItems(
            {side: NumberAxis(side, self.axes[key]) for key, side in AXES.items()}
        )
        item.setMenuEnabled(False)
        item.hideButtons()
        self.legend_item = MovableLegend(self)
        self.legend_item.setParentItem(item.vb)
        item.legend = self.legend_item
        if multi:
            # Adapted from pyqtgraph's MultiplePlotAxes example.
            self.right_box = pg.ViewBox(enableMenu=False)
            item.scene().addItem(self.right_box)
            item.getAxis("right").linkToView(self.right_box)
            self.right_box.setXLink(item.vb)
            item.vb.sigResized.connect(self.resize)
            self.right_box.setMouseEnabled(x=False, y=True)
            self.top_box = pg.ViewBox(enableMenu=False)
            self.top_right_box = pg.ViewBox(enableMenu=False)
            for box in (self.top_box, self.top_right_box):
                item.scene().addItem(box)
                box.setZValue(-10)
            item.getAxis("top").linkToView(self.top_box)
            self.top_box.setYLink(item.vb)
            self.top_right_box.setXLink(self.top_box)
            self.top_right_box.setYLink(self.right_box)
            self.top_box.setMouseEnabled(x=True, y=False)
            self.top_right_box.setMouseEnabled(x=False, y=False)
            self.resize()
        item.vb.sigResized.connect(self.place_legend)
        from tailor.axis_grid import AxisGrid

        self.grid_item = AxisGrid(self)
        for box in (self.right_box, self.top_box):
            if box is not None:
                box.sigRangeChanged.connect(lambda *args: self.grid_item.update())

    def resize(self):
        vb = self.owner.ui.plot_widget.getViewBox()
        for box in (self.right_box, self.top_box, self.top_right_box):
            if box is not None:
                box.setGeometry(vb.sceneBoundingRect())
        self.right_box.linkedViewChanged(vb, self.right_box.XAxis)
        if self.top_box is not None:
            self.top_box.linkedViewChanged(vb, self.top_box.YAxis)

    def to_dict(self):
        return copy.deepcopy(
            {
                "independent_axis_visibility": True,
                "curve_overrides": self.curve_overrides,
                "extra_settings": self.extra_settings,
                "trend_sources": self.trend_sources,
                "text_offsets": self.text_offsets,
                "single_sides": self.single_sides,
                "frame": self.frame,
                "axes": self.axes,
                "legend": self.legend,
                "errors": self.errors,
                "top_label": self.top_label,
                "top_min": self.top_min,
                "top_max": self.top_max,
                "margins": self.margins,
                "right_label": self.right_label,
                "right_min": self.right_min,
                "right_max": self.right_max,
            }
        )

    def load(self, state):
        self.extra_settings = copy.deepcopy(state.get("extra_settings", {}))
        self.curve_overrides = copy.deepcopy(state.get("curve_overrides", {}))
        self.trend_sources = copy.deepcopy(state.get("trend_sources", []))
        self.text_offsets = copy.deepcopy(state.get("text_offsets", {}))
        self.single_sides = dict(
            state.get("single_sides", {"x": "bottom", "y": "left"})
        )
        if not state:
            return
        for key in AXES:
            values = {**axis_defaults(), **state.get("axes", {}).get(key, {})}
            self.validate_axis(values)
            self.axes[key].update(values)
        if not self.multi:
            self.owner.model._axis_modes = {
                key: self.axes[key].get("axis_type", "numeric") for key in ("x", "y")
            }
        self.frame.update(state.get("frame", {}))
        if not state.get("independent_axis_visibility", False):
            for key, side in AXES.items():
                assigned = (
                    self.has_top()
                    if key == "top"
                    else self.has_right()
                    if key == "right"
                    else self.single_sides["x"] == "bottom"
                    if key == "x"
                    else self.single_sides["y"] == "left"
                )
                self.axes[key]["visible"] = self.axes[key]["visible"] and (
                    assigned or self.frame[side]
                )
        self.top_label = state.get("top_label", "上 X")
        self.top_min, self.top_max = state.get("top_min"), state.get("top_max")
        for value in (self.top_min, self.top_max):
            if value is not None and not math.isfinite(value):
                raise ValueError("Invalid top axis bound")
        margins = {**self.margins, **state.get("margins", {})}
        if any(
            not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 300
            for v in margins.values()
        ):
            raise ValueError("Invalid plot margins")
        self.margins = margins
        self.legend.update(state.get("legend", {}))
        self.errors.update(state.get("errors", {}))
        self.right_label = state.get("right_label", "右 Y")
        self.right_min, self.right_max = state.get("right_min"), state.get("right_max")
        for value in (self.right_min, self.right_max):
            if value is not None and not math.isfinite(value):
                raise ValueError("Invalid right axis bound")
        self.validate_errors(self.errors)
        if (
            not isinstance(self.legend["columns"], int)
            or not 1 <= self.legend["columns"] <= 20
        ):
            raise ValueError("Invalid legend columns")
        position = self.legend["position"]
        if position is not None and (
            len(position) != 2
            or not all(
                isinstance(v, (int, float)) and math.isfinite(v) for v in position
            )
        ):
            raise ValueError("Invalid legend position")
        if hasattr(self.owner, "extras"):
            self.owner.extras.cfg = self.extra_settings
            if hasattr(self.owner.extras, "collection"):
                self.owner.extras.collection.restore_extra(self.extra_settings)
            else:
                self.owner.extras.load()
        if hasattr(self.owner, "axis_controls"):
            self.owner.axis_controls.advanced.sync()
        if self.extra_settings.get("advanced") and not getattr(self.owner,"_project_restore_pending",False):
            from tailor.advanced_plotting import install_view

            install_view(self.owner, self.extra_settings["advanced"])

    @staticmethod
    def validate_errors(config):
        import re

        for key, low, high in (("cap", 0, 20), ("width", 0.1, 10)):
            value = config[key]
            if (
                not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not low <= value <= high
            ):
                raise ValueError("Invalid error-bar style")
        if (
            config["color"]
            and re.fullmatch(r"#[0-9a-fA-F]{6}", config["color"]) is None
        ):
            raise ValueError("Invalid error-bar color")
        if any(not isinstance(config[k], bool) for k in ("x_visible", "y_visible")):
            raise ValueError("Invalid error-bar visibility")

    @staticmethod
    def validate_axis(config):
        import re

        if re.fullmatch(r"#[0-9a-fA-F]{6}", config["color"]) is None:
            raise ValueError("Invalid axis color")
        if any(
            not isinstance(config[k], bool)
            for k in ("log", "inverted", "grid", "visible", "minor_visible")
        ):
            raise ValueError("Invalid axis setting")
        if isinstance(config["precision"], bool) or not isinstance(
            config["precision"], int
        ):
            raise ValueError("Invalid tick precision")  # noqa: TRY004 - project validation contract
        if config["notation"] not in {"auto", "fixed", "scientific"} or config[
            "direction"
        ] not in {"in", "out"}:
            raise ValueError("刻度格式无效")
        if not 0 <= config["precision"] <= 12:
            raise ValueError("刻度精度需在 0–12 之间")
        for key in ("labels", "title_visible", "minor_grid", "tick_angle_enabled"):
            if not isinstance(config.get(key, True), bool):
                raise ValueError("显示开关无效")  # noqa: TRY004 - project validation contract
        for key, low, high in (
            ("divisor", 1e-300, 1e300),
            ("axis_width", 0.1, 20),
            ("grid_width", 0.1, 3),
            ("tick_length", 0, 20),
            ("minor_length", 0, 20),
            ("minor_count", 0, 20),
            ("tick_angle", -90, 90),
        ):
            value = config.get(key, axis_defaults()[key])
            if (
                not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not low <= value <= high
            ):
                raise ValueError("轴参数无效：" + key)
        if (
            config.get("grid_style", "solid")
            not in {
                "solid",
                "dash",
                "dot",
                "dashdot",
                "dashdotdot",
                "longdash",
                "shortdash",
            }
            or re.fullmatch(r"#[0-9a-fA-F]{6}", config.get("grid_color", "#9ba5b1"))
            is None
        ):
            raise ValueError("网格样式无效")
        if any(
            not isinstance(config.get(k, ""), str) or len(config.get(k, "")) > 128
            for k in ("prefix", "suffix")
        ):
            raise ValueError("刻度前后缀过长")
        if config.get("axis_type", "numeric") not in {
            "numeric",
            "category",
            "datetime",
        }:
            raise ValueError("坐标类型无效")
        if not isinstance(config.get("break_enabled", False), bool):
            raise ValueError("断轴开关无效")  # noqa: TRY004 - project validation contract
        for key, default in (
            ("break_low", 1),
            ("break_high", 2),
            ("break_ratio", 0.03),
        ):
            value = config.get(key, default)
            if type(value) not in (float, int) or not math.isfinite(value):
                raise ValueError("断轴参数无效")
        if not 0 < config.get("break_ratio", 0.03) <= 0.5:
            raise ValueError("断轴间隙比例无效")
        reference = config.get("break_reference_span")
        if reference is not None and (
            type(reference) not in (int, float)
            or not math.isfinite(reference)
            or reference <= 0
        ):
            raise ValueError("断轴参考范围无效")
        if config.get("break_enabled") and (
            config.get("break_low", 1) >= config.get("break_high", 2)
            or (config["log"] and config.get("break_low", 1) <= 0)
        ):
            raise ValueError("断轴范围无效")
        ticks = config.get("custom_ticks", [])
        if not isinstance(ticks, list) or len(ticks) > 1000:
            raise ValueError("自定义刻度无效")
        for tick in ticks:
            if (
                not isinstance(tick, (list, tuple))
                or len(tick) != 2
                or type(tick[0]) not in (int, float)
                or not math.isfinite(tick[0])
                or not isinstance(tick[1], str)
            ):
                raise ValueError("自定义刻度无效")
        labels = config.get("category_custom", [])
        if not isinstance(labels, list) or not all(
            isinstance(label, str) for label in labels
        ):
            raise ValueError("分类标签无效")
        from tailor.tick_expression import parse

        parse(config.get("expression", ""))
        for key in ("grid_count", "minor_grid_count"):
            value = config.get(key, 0)
            if type(value) is not int or not 0 <= value <= 100:
                raise ValueError("网格数量需在0–100之间")
        count=config.get('major_count',5)
        if type(count) is not int or not 2<=count<=100:raise ValueError('主刻度目标数量须为2～100的整数')
        for key in ("major", "minor"):
            value = config[key]
            if value is not None and (not math.isfinite(value) or value <= 0):
                raise ValueError("刻度间距应为正数；留空为自动")

    def has_right(self):
        if not self.multi:
            return self.single_sides["y"] == "right"
        return any(
            i.axis == "right" and i.visible for i in self.owner.model._plots.values()
        )

    def has_top(self):
        if not self.multi:
            return self.single_sides["x"] == "top"
        return any(
            i.x_axis == "top" and i.visible for i in self.owner.model._plots.values()
        )

    def box_for(self, info):
        if info.x_axis == "top":
            return self.top_right_box if info.axis == "right" else self.top_box
        return (
            self.right_box
            if info.axis == "right"
            else self.owner.ui.plot_widget.getViewBox()
        )

    def apply_axes(self):
        view = getattr(self.owner, "advanced_view", None)
        if view and view.cfg["kind"] == "3d":
            view.schedule()
        plot = self.owner
        item = plot.ui.plot_widget.getPlotItem()
        vb = item.vb
        if not self.multi and not (view and view.cfg['kind']=='3d'):
            self.apply_single_sides()
        if getattr(plot, '_inset_parent', None) is not None:
            item.layout.setSpacing(0)
        item.layout.setContentsMargins(
            *(self.margins[k] + (0 if getattr(plot, '_inset_parent', None) is not None else 14)
              for k in ("left", "top", "right", "bottom"))
        )
        if self.top_box is not None:
            self.top_box.invertX(self.axes["top"]["inverted"])
            self.top_box.invertY(self.axes["y"]["inverted"])
            self.top_right_box.invertX(self.axes["top"]["inverted"])
            self.top_right_box.invertY(self.axes["right"]["inverted"])
        vb.invertX(self.axes["x"]["inverted"])
        vb.invertY(self.axes["y"]["inverted"])
        if self.right_box:
            self.right_box.invertY(self.axes["right"]["inverted"])
            self.right_box.invertX(self.axes["x"]["inverted"])
            # Right axis owns its view and labels; its canvas stays behind left
            # so ordinary drag zoom uses left Y. Right Y has explicit range controls.
            self.right_box.setZValue(-10)
        for key, side in AXES.items():
            config = self.axes[key]
            axis = item.getAxis(side)
            axis.settings = config
            axis.setLogMode(config["log"])
            from tailor.appearance import ink

            axis.setStyle(
                tickLength=(-1 if config["direction"] == "in" else 1)
                * max(1, math.ceil(max(config["tick_length"], config["minor_length"]))),
                showValues=config["labels"] and config.get("major_visible",True),
                maxTextLevel=2 if config.get("axis_type")=="datetime" else 0,
            )
            axis.setGrid(False)
            axis.setPen(pg.mkPen(ink(config["color"]), width=config["axis_width"]))
            axis.setTextPen(ink(config["color"]))
            item.showAxis(side, config["visible"])
            axis.picture = None
            axis.update()
        from tailor.axis_extensions import wrap_display_items

        wrap_display_items(self)
        for dimension, key in (("x", "x"), ("y", "y"), ("x", "top"), ("y", "right")):
            source = plot
            if self.multi:
                source = next(
                    (
                        p
                        for p, info in plot.model._plots.items()
                        if (
                            info.x_axis == ("top" if key == "top" else "bottom")
                            if dimension == "x"
                            else info.axis == ("right" if key == "right" else "left")
                        )
                    ),
                    None,
                )
            cfg = self.axes[key]
            root=getattr(plot,'_embedded_parent',None)
            advanced=getattr(root,'advanced_view',None)
            if advanced and advanced.cfg.get('kind')=='bar' and advanced.cfg.get('horizontal'):
                dimension='y' if dimension=='x' else 'x'
            categories = getattr(plot, '_inset_categories', {}).get(source)
            if categories is None:
                categories = getattr(getattr(source, "model", None), "_axis_categories", {})
            cfg["category_labels"] = cfg.get("category_custom") or categories.get(dimension, [])
        from tailor.text_style_controls import apply_text_styles

        apply_text_styles(plot)
        self.grid_item.update()
        from tailor.axis_shared_controls import draw_factors
        draw_factors(self)
        self.apply_legend()
        if hasattr(plot, "annotations"):
            plot.annotations.redraw()
        from tailor.processing_controls import refresh_frequency_axes

        refresh_frequency_axes(plot)
        # Axis/title visibility and multiplier text are also selectable position
        # objects. Update their small catalog in this same transaction, including
        # undo/load and inset paths, instead of waiting for an unrelated click.
        position = getattr(getattr(getattr(plot, 'annotations', None), 'panel', None), 'position_controls', None)
        if position is not None:
            position.sync()

    def apply_single_sides(self):
        item = self.owner.ui.plot_widget.getPlotItem()
        for source, target in (("x", "top"), ("y", "right")):
            alternate = self.single_sides[source] in {"top", "right"}
            side = "bottom" if source == "x" else "left"
            if alternate:
                for field in (
                    "log",
                    "inverted",
                    "axis_type",
                    "category_custom",
                    "custom_ticks",
                    "date_format",
                    "break_enabled",
                    "break_low",
                    "break_high",
                    "break_ratio",
                ):
                    if field in self.axes[target]:
                        self.axes[source][field] = self.axes[target][field]
                    elif field in self.axes[source]:
                        self.axes[source].pop(field)
                item.getAxis(target).linkToView(item.vb)
            else:
                item.getAxis(side).linkToView(item.vb)
        for side in ("bottom", "left", "top", "right"):
            item.getAxis(side).linkToView(item.vb)
        # Source bounds remain the single authoritative range for this curve.
        self.right_min, self.right_max = self.owner.model.y_min, self.owner.model.y_max
        self.top_min, self.top_max = self.owner.model.x_min, self.owner.model.x_max

    def apply_single_items(self):
        if self.multi:
            return
        for item in self.owner.ui.plot_widget.getPlotItem().listDataItems():
            if isinstance(item, pg.PlotDataItem):
                item.setLogMode(self.axes["x"]["log"], self.axes["y"]["log"])
        self.apply_axes()

    def place_legend(self, *args):
        position = self.legend["position"]
        if position is None:
            self.legend_item.anchor((1, 0), (1, 0), offset=(-12, 12))
        else:
            rect = self.legend_item.parentItem().boundingRect()
            self.legend_item.anchor(
                (0, 0),
                (0, 0),
                offset=(position[0] * rect.width(), position[1] * rect.height()),
            )

    def apply_legend(self):
        parent = getattr(self.owner, "_embedded_parent", None)
        native = getattr(getattr(parent, "advanced_view", None), "native", None)
        if native and not native.syncing and not native.loading:
            native.legend_timer.start()
        view = getattr(self.owner, "advanced_view", None)
        if view and view.cfg.get("kind") == "3d":
            view.schedule()
        self.draw_trends()
        from tailor.legend_entries import reconcile

        reconcile(self.owner)
        legend = self.legend_item
        legend.setColumnCount(self.legend["columns"])
        legend.layout.setVerticalSpacing(self.legend.get("spacing", 2))
        legend.layout.invalidate()
        legend.layout.activate()
        legend.setMinimumSize(0, 0)
        legend.setPreferredSize(
            legend.layout.effectiveSizeHint(QtCore.Qt.PreferredSize)
        )
        legend.resize(legend.layout.effectiveSizeHint(QtCore.Qt.PreferredSize))
        # QText custom objects can finish their intrinsic sizing after the
        # grid's cached preferred hint. Include actual child bounds before
        # anchoring, otherwise a long decorated label extends off the canvas.
        content = QtCore.QRectF()
        for sample, label in legend.items:
            for child in (sample, label):
                content = content.united(child.mapRectToParent(child.boundingRect()))
        if not content.isEmpty():
            _left, _top, right, bottom = legend.layout.getContentsMargins()
            legend.resize(max(legend.width(), content.right()+right), max(legend.height(), content.bottom()+bottom))
        from tailor.line_styles import curve_pen

        border = self.legend.get("border_style", {})
        from PySide6 import QtGui

        from tailor.appearance import manager

        color = QtGui.QColor(border.get("color", "#888888"))
        color.setAlphaF(border.get("opacity", 1.0))
        legend.setPen(
            curve_pen(
                color, border.get("line_width", 1.0), border.get("line_style", "solid")
            )
            if self.legend["border"]
            else None
        )
        background = self.legend.get("background_style", {})
        color = QtGui.QColor(
            background.get("color", "#000000" if manager().dark(True) else "#ffffff")
        )
        color.setAlphaF(background.get("opacity", 1.0))
        legend.setBrush(pg.mkBrush(color) if self.legend["background"] else None)
        visible = self.legend["visible"] and getattr(
            self.owner.model, "legend_visible", True
        )
        legend.setVisible(visible)
        self.place_legend()

    def draw_trends(self):
        from tailor.curve_style import CurveStyle
        from tailor.line_styles import apply_curve_extras, curve_pen

        plot = self.owner
        sheets = {sheet.id: sheet for sheet in plot.main_window.get_data_sheets()}
        for record in self.trend_sources:
            sheet = sheets.get(record["sheet"])
            if sheet is None:
                continue
            identity = record["id"]
            series = self._trend_items.get(identity)
            if series is None:
                series = pg.PlotDataItem()
                series._legend_key = "trend:" + identity
                series.setDownsampling(auto=True, method="peak")
                plot.ui.plot_widget.getViewBox().addItem(series)
                self._trend_items[identity] = series
                sheet.model.historyChanged.connect(self.apply_legend)
            style = CurveStyle(**record["style"])
            x = np.asarray(sheet.model.data_model.get_column(record["x"]), dtype=float)
            y = np.asarray(sheet.model.data_model.get_column(record["y"]), dtype=float)
            series.setData(
                display(x, self.axes["x"]),
                display(y, self.axes["y"]),
                pen=curve_pen(style.color, style.line_width, style.line_style),
                connect="finite",
            )
            apply_curve_extras(series, style)
            if not any(
                sample.item is series or getattr(sample, "_source_item", None) is series
                for sample, label in self.legend_item.items
            ):
                self.legend_item.addItem(series, record["name"])

    def bounds(self, key, values, lower=None, upper=None):
        log = self.axes[key]["log"]
        cfg=self.axes[key]
        if not log and cfg.get('axis_type','numeric')=='numeric':
            # Friendly ticks decorate the view; they must never enlarge it.
            limits=list(data_limits(values, padding=0.03 if key in {'x','top'} else 0.05))
        else:limits = list(data_limits(values, log))
        for i, value in enumerate((lower, upper)):
            if value is not None:
                limits[i] = value
        if (
            not np.isfinite(limits).all()
            or limits[0] >= limits[1]
            or (log and limits[0] <= 0)
        ):
            raise ValueError(
                "坐标范围无效：最小值必须小于最大值；对数轴范围必须大于 0。"
            )
        return tuple(limits)

    def single_limits(self, values=None):
        model = self.owner.model
        x, y, ex, ey = model.get_data()
        bounds = (
            values
            if values is not None
            else (model.x_min, model.x_max, model.y_min, model.y_max)
        )
        return (
            *self.bounds("top" if self.single_sides['x']=='top' else "x", np.concatenate((x - ex, x + ex, x)), *bounds[:2]),
            *self.bounds("right" if self.single_sides['y']=='right' else "y", np.concatenate((y - ey, y + ey, y)), *bounds[2:]),
        )

    def set_single_limits(self):
        a, b, c, d = self.single_limits()
        plot = self.owner
        plot._block_range_signal = True
        try:
            plot.ui.plot_widget.setRange(
                xRange=display([a, b], self.axes["x"]),
                yRange=display([c, d], self.axes["y"]),
                padding=0,
                disableAutoRange=True,
            )
        finally:
            plot._block_range_signal = False

    def close(self):
        self.legend_item.release_anchor()
        for side in ("right", "top"):
            self.owner.ui.plot_widget.getAxis(side).unlinkFromView()
        for name in ("top_right_box", "top_box", "right_box"):
            box = getattr(self, name)
            if box is not None:
                box.setXLink(None)
                box.setYLink(None)
                box.close()
                scene = box.scene()
                if scene:
                    scene.removeItem(box)
                setattr(self, name, None)

    def mpl_axis(self, axes, key, label, limits, style):
        from matplotlib import ticker

        from tailor.text_style_controls import export_font_families, font_spec

        config = self.axes[key]
        horizontal = key == "x"
        axis = axes.xaxis if horizontal else axes.yaxis
        setter = axes.set_xscale if horizontal else axes.set_yscale
        setter("log", nonpositive="mask") if config["log"] else setter("linear")
        (axes.set_xlim if horizontal else axes.set_ylim)(
            *(reversed(limits) if config["inverted"] else limits)
        )
        major, minor = config["major"], config["minor"]
        if major is None and not config['log']:
            from tailor.axis_tick_policy import smart_ticks
            _,ticks=smart_ticks(*limits,config.get('major_count',5))
            axis.set_major_locator(ticker.FixedLocator(ticks))
        span = float(np.diff(display(limits, config))[0])
        if major is not None and span / major <= 500:
            if config["log"]:
                a, b = display(limits, True)
                ticks = (
                    np.arange(math.ceil(a / major), math.floor(b / major) + 1) * major
                )
                axis.set_major_locator(ticker.FixedLocator(physical(ticks, True)))
            else:
                axis.set_major_locator(ticker.MultipleLocator(major))
        if minor is not None and span / minor > 500:
            minor = None
        if not config["minor_visible"]:
            axis.set_minor_locator(ticker.NullLocator())
        elif minor is not None:
            if config["log"]:
                a, b = display(limits, True)
                count = (b - a) / minor
                if count <= 500:
                    axis.set_minor_locator(
                        ticker.FixedLocator(
                            physical(
                                np.arange(
                                    math.ceil(a / minor), math.floor(b / minor) + 1
                                )
                                * minor,
                                True,
                            )
                        )
                    )
            else:
                axis.set_minor_locator(ticker.MultipleLocator(minor))
        elif not config["log"]:
            axis.set_minor_locator(ticker.AutoMinorLocator(int(config["minor_count"])+1))
        def caption(value,pos):
            from tailor.axis_tick_policy import label_precision,numeric_spacing,display_format
            located=axis.get_majorticklocs()
            spacing=abs(located[1]-located[0]) if len(located)>1 else 1
            active=display_format(config,numeric_spacing(config,spacing,value))
            return config.get('prefix','')+format_tick(value/config.get('divisor',1),active['notation'],
                label_precision(active,numeric_spacing(config,spacing,value),value))+config.get('suffix','')
        axis.set_major_formatter(ticker.FuncFormatter(caption))
        axes.tick_params(
            axis="x" if horizontal else "y",
            which="both",
            direction=config["direction"],
            colors=config["color"],
        )
        if config["grid"]:
            axis.grid(True, which="major", alpha=0.2)
        else:
            axis.grid(False, which="both")
        side = AXES[key]
        side = "bottom" if side == "bottom" else side
        axes.spines[side].set_visible(config["visible"])
        axis.set_visible(config["visible"])
        axes.spines[side].set_color(config["color"])
        title = font_spec(style, key + "_label")
        (axes.set_xlabel if horizontal else axes.set_ylabel)(
            label,
            color=config["color"],
            fontsize=title["size"],
            fontfamily=export_font_families(title["family"]),
        )
        tick = font_spec(style, key + "_ticks")
        for text in axis.get_ticklabels():
            text.set_fontsize(tick["size"])
            text.set_fontfamily(export_font_families(tick["family"]))

    def mpl_legend(self, axes, handles=None, labels=None):
        from tailor.text_style_controls import export_font_families, font_spec

        if not self.legend["visible"] or not getattr(
            self.owner.model, "legend_visible", True
        ):
            old = axes.get_legend()
            if old:
                old.remove()
            return
        spec = font_spec(self.owner.curve_style, "legend")
        opts = {
            "ncol": self.legend["columns"],
            "frameon": self.legend["border"] or self.legend["background"],
            "facecolor": "white" if self.legend["background"] else "none",
            "edgecolor": "#888888" if self.legend["border"] else "none",
            "prop": {
                "size": spec["size"],
                "family": export_font_families(spec["family"]),
            },
        }
        position = self.legend["position"]
        if position is not None:
            opts.update(
                loc="upper left",
                bbox_to_anchor=(position[0], 1 - position[1]),
                borderaxespad=0,
            )
        else:
            opts["loc"] = "upper right"
        if handles is None:
            axes.legend(**opts)
        else:
            axes.legend(handles, labels, **opts)


def mpl_errors(config, color):
    return {
        "capsize": config.get("cap", 4),
        "elinewidth": config.get("width", 1),
        "ecolor": config.get("color") or color,
    }


def mpl_error_values(values, errors, log, enabled=True):
    """Match Qt: omit only the unrepresentable lower side of a log error."""
    if not enabled:
        return None
    errors = np.broadcast_to(errors, np.shape(values))
    if log:
        lower = np.where(np.asarray(values) - errors > 0, errors, 0)
        return np.vstack((lower, errors))
    return errors

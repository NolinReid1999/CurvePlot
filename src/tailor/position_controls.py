"""Pixel position nudges adapting axis titles, whole legends and annotations."""

import copy

from PySide6 import QtCore, QtWidgets

from tailor.compact_controls import stepper
from tailor.graph_controls import row


class PositionControls(QtWidgets.QWidget):
    def __init__(self, host, font=False):
        super().__init__()
        self.host, self.font, self.dimension, self.loading = host, font, 0, False
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 6)
        from tailor.compact_controls import ArrowParameter
        self.arrows=ArrowParameter(-4000,4000,1,self)
        layout.addWidget(self.arrows)
        self.direction='right'
        self.buttons=[(self.arrows.buttons[key],glyph,dimension) for key,glyph,dimension in [('up','↑',1),('down','↓',1),('left','←',0),('right','→',0)]]
        self.arrows.chosen.connect(self.select_direction)
        self.value=self.arrows.value
        self.value.valueChanged.connect(self.move_to)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(180)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()

    def target(self):
        p, h = self.host.plot, self.host
        if hasattr(self, "explicit_target"):
            return self.explicit_target
        if getattr(p, "_graph_disposed", False):
            return None
        if getattr(p, "advanced_view", None) and p.advanced_view.cfg["kind"] in {
            "3d",
            "panels",
        }:
            return None
        if self.font:
            if h.editor is p.axis_controls.text_editor:
                a = p.axis_controls
                return (
                    ("axis", a.current)
                    if a.text_target.currentData() == "label"
                    else None
                )
            if h.editor is p.legend_controls.editor:
                return "legend", None
            if (
                h.editor is getattr(p, "annotation_font_editor", None)
                and p.annotations.current()
            ):
                return "annotation", p.annotations.selected
            return None
        kind, value = h.curve_target
        if kind.startswith("legend"):
            return "legend", None
        return (kind, value) if kind == "annotation" else None

    def coordinates(self):
        target = self.target()
        if target is None:
            return None
        p = self.host.plot
        box = p.ui.plot_widget.getViewBox()
        center = box.boundingRect().center()
        origin = getattr(self, "origin", "center")
        if origin == "left":
            center.setX(box.boundingRect().left())
        elif origin == "right":
            center.setX(box.boundingRect().right())
        elif origin == "bottom":
            center.setY(box.boundingRect().bottom())
        kind, key = target
        if kind in {'axis','factor'}:
            side = {"x": "bottom", "y": "left", "top": "top", "right": "right"}[key]
            axis=p.ui.plot_widget.getAxis(side)
            item=axis.label if kind=='axis' else getattr(axis,'factor_item',None)
            if item is None:return None
            pos = box.mapFromScene(item.sceneBoundingRect().center())
        elif kind == "legend":
            item = p.presentation.legend_item
            pos = box.mapFromScene(item.sceneBoundingRect().center())
        elif kind == "inset":
            collection=p.extras.collection
            e=collection.controllers.get(key)
            if e is None or not hasattr(e,"inset"):
                return None
            rect=e.range_roi.sceneBoundingRect().united(e.layout_roi.sceneBoundingRect())
            pos=box.mapFromScene(rect.center())
        else:
            record = next((r for r in p.annotations.records if r["id"] == key), None)
            if record is None or not p.annotations.representable(record):
                return None
            points = p.annotations.to_pixels(record)
            pos = (points[0] + points[1]) / 2
        return [pos.x() - center.x(), center.y() - pos.y()]

    def refresh(self):
        if getattr(self, "disabled", False) or getattr(
            self.host.plot, "_graph_disposed", False
        ):
            self.timer.stop()
            return
        self.arrows.setEnabled(self.target() is not None)
        if self.target() is None:return
        if self.parentWidget() and not self.parentWidget().isVisible():
            return
        value = self.coordinates()
        self.arrows.setEnabled(value is not None)
        if (
            value is None
            or self.value.hasFocus()
            or self.value.parentWidget().slider.isSliderDown()
        ):
            return
        self.loading = True
        self.arrows.sync({'up':value[1],'down':value[1],'left':value[0],'right':value[0]},self.direction)
        self.loading = False

    def select_direction(self,key):
        repeat=self.direction==key
        self.direction=key;self.dimension=1 if key in {'up','down'} else 0
        if repeat:self.nudge(self.dimension,1 if key in {'up','right'} else -1)
        else:self.refresh()

    def nudge(self, dimension, amount):
        value = self.coordinates()
        if value is not None:
            self.dimension = dimension
            self.set_position(
                value[0] + (amount if dimension == 0 else 0),
                value[1] + (amount if dimension == 1 else 0),
            )
            self.refresh()

    def move_to(self, value):
        if self.loading:
            return
        coords = self.coordinates()
        if coords is not None:
            coords[self.dimension] = value
            self.set_position(*coords)

    def set_position(self, x, y):
        p = self.host.plot
        box = p.ui.plot_widget.getViewBox()
        kind, key = self.target()
        previous = self.coordinates()
        delta = QtCore.QPointF(x - previous[0], previous[1] - y)
        if kind == "inset":
            collection=p.extras.collection
            e=collection.controllers[key]
            def translate():
                start=box.mapToScene(QtCore.QPointF())
                end=box.mapToScene(delta)
                source_delta=e.range_box.mapSceneToView(end)-e.range_box.mapSceneToView(start)
                with QtCore.QSignalBlocker(e.range_roi):
                    e.range_roi.setPos(e.range_roi.pos()+source_delta)
                with QtCore.QSignalBlocker(e.layout_roi):
                    e.layout_roi.setPos(e.layout_roi.pos()+delta)
                e.range_changed();e.layout_changed()
            collection.edit("移动整个局部放大",translate)
        elif kind == "annotation":
            record = p.annotations.current()
            points = [pt + delta for pt in p.annotations.to_pixels(record)]
            p.annotations.replace(
                {
                    **record,
                    "points": p.annotations.from_pixels(record["anchor"], points),
                }
            )
        else:
            from tailor.text_style_controls import record_view_edit

            if kind in {'axis','factor'}:
                if kind=='factor':key=key+'_factor'
                before = copy.deepcopy(p.presentation.text_offsets)
                old = before.get(key, [0, 0])
                p.presentation.text_offsets[key] = [
                    old[0] + delta.x(),
                    old[1] + delta.y(),
                ]
                p.text_drag.restore()
                after = copy.deepcopy(p.presentation.text_offsets)

                def restore(plot, state):
                    plot.presentation.text_offsets = copy.deepcopy(state)
                    plot.text_drag.restore()
            else:
                before = copy.deepcopy(p.presentation.legend)
                item = p.presentation.legend_item
                rect = item.parentItem().boundingRect()
                position = item.pos() + delta
                p.presentation.legend["position"] = [
                    position.x() / max(1, rect.width()),
                    position.y() / max(1, rect.height()),
                ]
                p.presentation.place_legend()
                after = copy.deepcopy(p.presentation.legend)

                def restore(plot, state):
                    plot.presentation.legend = copy.deepcopy(state)
                    plot.presentation.apply_legend()

            record_view_edit(p, "调整位置", before, after, restore)
        p.main_window.mark_project_dirty()

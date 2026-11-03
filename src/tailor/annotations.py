"""Thin editable annotation layer over Tailor's existing pyqtgraph ViewBoxes."""

import copy
import math
import uuid

from PySide6 import QtCore, QtGui, QtWidgets

from tailor.annotation_validation import validate_annotation
from tailor.appearance import ink

KINDS = {
    "text": "文字",
    "image": "图片",
    "arrow": "箭头",
    "double_arrow": "双箭头",
    "line": "直线",
    "rectangle": "矩形",
    "ellipse": "椭圆",
    "hline": "水平参考线",
    "vline": "竖直参考线",
}
ONE_POINT = {"text", "hline", "vline"}


def annotation_caption(record, records):
    """Use the stored kind/ID, never the shared default text of other shapes."""
    kind = record['kind']
    same = [r['id'] for r in records if r['kind'] == kind]
    title = KINDS.get(kind, kind) + f' {same.index(record["id"]) + 1}'
    if kind == 'text':
        from tailor.text_accents import caption
        title += ' · ' + caption(record.get('text', '')).replace('\n', ' / ')[:24]
    return title


STYLES = {
    "solid": QtCore.Qt.SolidLine,
    "dash": QtCore.Qt.DashLine,
    "dot": QtCore.Qt.DotLine,
    "dashdot": QtCore.Qt.DashDotLine,
}


class AnnotationEdit(QtGui.QUndoCommand):
    def __init__(self, manager, before, after, title):
        super().__init__(title)
        self.manager, self.before, self.after = manager, before, after

    def undo(self):
        self.manager.restore(self.before, dirty=True)

    def redo(self):
        self.manager.restore(self.after, dirty=True)


class AnnotationItem(QtWidgets.QGraphicsObject):
    def __init__(self, manager, record):
        super().__init__(manager.box)
        self.manager, self.record = manager, record
        self.path = QtGui.QPainterPath()
        self.outline = QtCore.QRectF()
        self.ends = []
        self.drag = None
        self.text = QtWidgets.QGraphicsTextItem(self)
        self.text.document().setDocumentMargin(0)
        self.text.setAcceptedMouseButtons(QtCore.Qt.NoButton)
        self.setAcceptedMouseButtons(QtCore.Qt.LeftButton)
        self.setFlag(QtWidgets.QGraphicsItem.ItemClipsChildrenToShape, True)
        self.rebuild()

    def rebuild(self):
        self.prepareGeometryChange()
        r = self.record
        self.path = QtGui.QPainterPath()
        self.text.hide()
        if not self.manager.representable(r):
            self.hide()
            return
        self.setVisible(r["visible"])
        self.setOpacity(
            self.manager.plot.presentation.curve_overrides.get(
                "annotation:" + r["id"], {}
            ).get("opacity", 1.0)
        )
        a, b = self.manager.to_pixels(r)
        self.ends = [a] if r["kind"] in ONE_POINT else [a, b]
        rect = QtCore.QRectF(a, b).normalized()
        kind = r["kind"]
        transform = QtGui.QTransform()
        if kind not in {"text", "hline", "vline"}:
            center = rect.center()
            transform.translate(center.x(), center.y())
            transform.rotate(-r["rotation"])
            transform.translate(-center.x(), -center.y())
        self.setTransform(transform)
        if kind == "text":
            font = QtGui.QFont(r["family"])
            font.setPointSizeF(r["size"])
            font.setBold(r["bold"])
            self.text.setFont(font)
            from tailor.text_style_controls import font_spec, styled_html

            spec = font_spec(self.manager.plot.curve_style, "annotation:" + r["id"])
            from tailor.text_style_controls import native_font
            self.text.document().setDefaultFont(native_font(spec))
            self.text.setHtml(styled_html(r["text"], {**spec, "background": ""}))
            from tailor.cjk_text import apply_weight
            apply_weight(self.text.document(),spec)
            from tailor.text_accents import install_vector_objects
            install_vector_objects(self.text.document())
            self.text.setDefaultTextColor(QtGui.QColor(ink(r["color"])))
            self.text.setPos(a)
            from tailor.text_layout import rotation
            self.text.setRotation(-r["rotation"] + rotation(spec))
            self.text.show()
            self.path.addPolygon(self.text.mapToParent(self.text.boundingRect()))
        elif kind == "image" or kind == "rectangle":
            self.path.addRect(rect)
        elif kind == "ellipse":
            self.path.addEllipse(rect)
        else:
            bounds = self.manager.box.boundingRect()
            if kind == "hline":
                a, b = (
                    QtCore.QPointF(bounds.left(), a.y()),
                    QtCore.QPointF(bounds.right(), a.y()),
                )
            elif kind == "vline":
                a, b = (
                    QtCore.QPointF(a.x(), bounds.top()),
                    QtCore.QPointF(a.x(), bounds.bottom()),
                )
            self.path.moveTo(a)
            self.path.lineTo(b)
            if kind in {"arrow", "double_arrow"}:
                pairs = [(a, b)] + ([(b, a)] if kind == "double_arrow" else [])
                for start, end in pairs:
                    angle = math.atan2(end.y() - start.y(), end.x() - start.x())
                    for offset in (-0.45, 0.45):
                        tip = end - QtCore.QPointF(
                            11 * math.cos(angle + offset), 11 * math.sin(angle + offset)
                        )
                        self.path.moveTo(end)
                        self.path.lineTo(tip)
        self.outline = self.path.boundingRect().adjusted(-8, -8, 8, 8)
        if not self.ratio_button_rect().isEmpty():
            self.outline = self.outline.united(self.ratio_button_rect().adjusted(-2,-2,2,2))
        self.update()

    def ratio_button_rect(self):
        if self.record['kind'] != 'image' or self.manager.selected != self.record['id'] or not self.manager.active() or getattr(self.manager,'_cropping',None) == self.record['id']:
            return QtCore.QRectF()
        rect=self.path.boundingRect()
        return QtCore.QRectF(rect.right()-32,rect.bottom()-32,25,25)

    def boundingRect(self):
        return self.outline

    def shape(self):
        stroke = QtGui.QPainterPathStroker()
        stroke.setWidth(max(10, self.record["width"] + 6))
        shape = stroke.createStroke(self.path)
        if self.record["kind"] in {"text", "image"} or self.record["fill"]:
            shape = shape.united(self.path)
        if not self.ratio_button_rect().isEmpty():
            shape.addRect(self.ratio_button_rect())
        clip = QtGui.QPainterPath()
        clip.addRect(self.manager.box.boundingRect())
        return shape.intersected(clip)

    def paint(self, painter, option, widget=None):
        r = self.record
        painter.setClipRect(self.manager.box.boundingRect())
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        from tailor.line_styles import curve_pen

        painter.setPen(curve_pen(r["color"], r["width"], r["linestyle"]))
        fill = QtGui.QColor(r["fill"]) if r["fill"] else None
        if fill:
            fill.setAlphaF(r.get("fill_opacity", 0.18))
        painter.setBrush(QtGui.QBrush(fill) if fill else QtCore.Qt.NoBrush)
        if r["kind"] == "text":
            painter.setPen(QtCore.Qt.NoPen)
        if r["kind"] == "image":
            import base64

            if getattr(self, "_image_payload", None) != r.get("image_data"):
                self._image_payload = r.get("image_data")
                self._image = QtGui.QImage.fromData(
                    base64.b64decode(self._image_payload or "")
                )
            painter.drawImage(self.path.boundingRect(), self._image)
        else:
            painter.drawPath(self.path)
        if self.manager.selected == r["id"] and self.manager.active() and getattr(self.manager, "_cropping", None) != r["id"]:
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.setPen(QtGui.QPen(QtGui.QColor("#2685ef"), 1, QtCore.Qt.DashLine))
            painter.drawRect(self.path.boundingRect().adjusted(-3, -3, 3, 3))
            if not r["locked"]:
                painter.setBrush(QtGui.QColor("#ffffff"))
                for point in self.ends:
                    from tailor.resize_handles import draw_handle

                    draw_handle(painter, point)
            rect=self.ratio_button_rect()
            if not rect.isEmpty():
                locked=r.get('aspect_locked',True)
                if not hasattr(self,'_ratio_icons'):
                    from tailor.plot_types import icon
                    self._ratio_icons={True:icon('link',color='#448ad5'),False:icon('unlink',color='#718096')}
                palette=self.manager.plot.palette()
                painter.setBrush(palette.color(QtGui.QPalette.Base))
                painter.setPen(QtGui.QPen(palette.color(QtGui.QPalette.Mid),1))
                painter.drawRoundedRect(rect,4,4)
                self._ratio_icons[locked].paint(painter,rect.adjusted(3,3,-3,-3).toRect())

    def mousePressEvent(self, event):
        from tailor.point_inspector import point_active
        if point_active(self.manager.plot):
            event.ignore()
            return
        if getattr(self.manager,"_cropping",None) == self.record["id"]:
            event.accept()
            return
        if self.manager.tool:
            event.ignore()
            return
        self.manager.select(self.record["id"])
        if self.ratio_button_rect().contains(event.pos()) and not self.record['locked']:
            points=self.manager.from_pixels(self.record['anchor'],self.manager.to_pixels(self.record))
            locked=not self.record.get('aspect_locked',True)
            self.manager.replace({**self.record,'points':points,'aspect_locked':locked})
            self.manager.plot.main_window.statusBar().showMessage('图片比例已锁定' if locked else '图片比例已解锁，可自由拉伸')
            event.accept()
            return
        if not self.record["locked"]:
            handle = next(
                (
                    i
                    for i, p in enumerate(self.ends)
                    if QtCore.QLineF(p, event.pos()).length() < 9
                ),
                None,
            )
            self.drag_scene_start = event.scenePos()
            self.drag = (
                copy.deepcopy(self.manager.records),
                event.pos(),
                self.manager.to_pixels(self.record),
                handle,
            )
        event.accept()

    def mouseDoubleClickEvent(self, event):
        self.manager.select(self.record["id"])
        prefs = getattr(self.manager.plot, "preferences", None)
        if prefs:
            if self.record["kind"] == "text":
                prefs.open_font(self.manager.plot.annotation_font_editor, "标注文字")
            else:
                prefs.select_curve("annotation", self.record["id"], True)
        event.accept()

    def mouseMoveEvent(self, event):
        if not self.drag:
            return
        _, start, points, handle = self.drag
        delta = event.pos() - start
        moved = [
            p + delta if handle is None or handle == i else p
            for i, p in enumerate(points)
        ]
        if self.record["kind"] not in {"text", "hline", "vline"}:
            parent = self.manager.box
            shift = parent.mapFromScene(event.scenePos()) - parent.mapFromScene(
                self.drag_scene_start
            )
            if handle is None:
                moved = [p + shift for p in points]
            else:
                # Resize in the rotated frame, keeping the opposite visual corner fixed.
                center = (points[0] + points[1]) / 2
                rotate = QtGui.QTransform().rotate(-self.record["rotation"])
                visual = [center + rotate.map(p - center) for p in points]
                visual[handle] += shift
                if self.record['kind']=='image' and self.record.get('aspect_locked',True):
                    fixed=1-handle;inverse=rotate.inverted()[0]
                    delta=inverse.map(visual[handle]-visual[fixed])
                    ratio=self.manager.image_ratio(self.record)
                    w,h=abs(points[1].x()-points[0].x()),abs(points[1].y()-points[0].y())
                    if abs(delta.x())/max(w,1e-9)>=abs(delta.y())/max(h,1e-9):
                        delta.setY(math.copysign(abs(delta.x())/ratio,delta.y() or 1))
                    else:
                        delta.setX(math.copysign(abs(delta.y())*ratio,delta.x() or 1))
                    visual[handle]=visual[fixed]+rotate.map(delta)
                new_center = (visual[0] + visual[1]) / 2
                inverse = rotate.inverted()[0]
                moved = [new_center + inverse.map(p - new_center) for p in visual]
        if self.record["kind"] in ONE_POINT:
            moved[1] = moved[0]
        coords = self.manager.from_pixels(self.record["anchor"], moved)
        candidate = {**self.record, "points": coords}
        try:
            self.manager.validate(candidate)
        except ValueError:
            return
        self.record["points"] = coords
        self.rebuild()

    def mouseReleaseEvent(self, event):
        if self.drag:
            before = self.drag[0]
            self.drag = None
            self.manager.commit(before, "移动标注")
        event.accept()


class AnnotationManager(QtCore.QObject):
    changed = QtCore.Signal()

    def __init__(self, plot):
        super().__init__(plot)
        self.plot = plot
        self.box = plot.ui.plot_widget.getViewBox()
        self.records, self.items = [], {}
        self.selected = None
        self.tool, self.start = None, None
        self.preview = None
        self.anchor = "left"
        self.panel = None
        self.history = QtGui.QUndoStack(self)
        self.history.setUndoLimit(200)
        self.history.indexChanged.connect(self.refresh_toolbar)
        self.box.sigRangeChanged.connect(self.redraw)
        self.box.sigResized.connect(self.redraw)
        if plot.presentation.right_box is not None:
            plot.presentation.right_box.sigRangeChanged.connect(self.redraw)
        self._event_scene = plot.ui.plot_widget.scene()
        self._event_scene.sigMouseClicked.connect(self.scene_clicked)
        plot.ui.plot_widget.scene().sigMouseMoved.connect(self.scene_moved)
        plot.ui.plot_widget.viewport().installEventFilter(self)

    def active(self):
        return (
            self.panel is not None
            and self.plot.property_tabs.currentWidget()
            is getattr(self, "graph_page", self.panel)
        )

    def refresh_toolbar(self, *args):
        toolbar = getattr(self.plot.main_window, "tab_controls", None)
        if toolbar:
            toolbar.refresh()

    def page_changed(self, *args):
        if not self.active():
            self.arm(None)
        self.redraw()
        self.refresh_toolbar()

    def eventFilter(self, watched, event):
        if event.type() != QtCore.QEvent.KeyPress or not self.active():
            return False
        if event.key() == QtCore.Qt.Key_Escape:
            self.arm(None)
        elif event.key() in (QtCore.Qt.Key_Delete, QtCore.Qt.Key_Backspace):
            self.delete()
        elif event.matches(QtGui.QKeySequence.Undo):
            self.plot.main_window.tab_controls.replay("undo")
        elif event.matches(QtGui.QKeySequence.Redo):
            self.plot.main_window.tab_controls.replay("redo")
        else:
            return False
        return True

    def validate(self, record):
        validate_annotation(record)
        if not self.representable(record):
            raise ValueError(
                "当前坐标轴无法显示此标注；请检查右轴是否启用、对数轴坐标是否大于 0"
            )

    def representable(self, r):
        if r["anchor"] == "canvas":
            return True
        p = self.plot.presentation
        if r["anchor"] == "right" and not p.has_right():
            return False
        for index, key in ((0, "x"), (1, "right" if r["anchor"] == "right" else "y")):
            if (r["kind"] == "hline" and index == 0) or (
                r["kind"] == "vline" and index == 1
            ):
                continue
            values = (
                r["points"][index : index + 1]
                if r["kind"] in ONE_POINT
                else r["points"][index::2]
            )
            if p.axes[key]["log"] and any(v <= 0 for v in values):
                return False
        return True

    def view(self, anchor):
        return self.plot.presentation.right_box if anchor == "right" else self.box

    def to_pixels(self, record):
        coords, anchor = record["points"], record["anchor"]
        bounds = self.box.boundingRect()
        result = []
        for index in (0, 2):
            source_index = 0 if record["kind"] in ONE_POINT else index
            x, y = coords[source_index : source_index + 2]
            if anchor == "canvas":
                point = QtCore.QPointF(
                    bounds.left() + x * bounds.width(),
                    bounds.bottom() - y * bounds.height(),
                )
            else:
                vb = self.view(anchor)
                axes = self.plot.presentation.axes
                if record["kind"] == "hline":
                    x = vb.viewRange()[0][0]
                elif axes["x"]["log"]:
                    x = math.log10(x)
                key = "right" if anchor == "right" else "y"
                if record["kind"] == "vline":
                    y = vb.viewRange()[1][0]
                elif axes[key]["log"]:
                    y = math.log10(y)
                point = self.box.mapFromScene(vb.mapViewToScene(QtCore.QPointF(x, y)))
            result.append(point)
        if record['kind']=='image' and record.get('aspect_locked',True):
            rect=QtCore.QRectF(result[0],result[1]).normalized();ratio=self.image_ratio(record)
            w=min(rect.width(),rect.height()*ratio);h=w/ratio;center=rect.center()
            result=[center-QtCore.QPointF(w/2,h/2),center+QtCore.QPointF(w/2,h/2)]
        return result

    def image_ratio(self,record):
        import base64
        cache=getattr(self,'_image_ratios',{});self._image_ratios=cache
        payload=record.get('image_data','');saved=cache.get(record['id'])
        if saved is None or saved[0]!=payload:
            image=QtGui.QImage.fromData(base64.b64decode(payload))
            saved=(payload,image.width()/max(1,image.height()) if not image.isNull() else 1.)
            cache[record['id']]=saved
        return max(1e-9,saved[1])

    def from_pixels(self, anchor, points):
        bounds = self.box.boundingRect()
        result = []
        for point in points:
            if anchor == "canvas":
                x, y = (
                    (point.x() - bounds.left()) / max(1, bounds.width()),
                    (bounds.bottom() - point.y()) / max(1, bounds.height()),
                )
            else:
                value = self.view(anchor).mapSceneToView(self.box.mapToScene(point))
                x, y = value.x(), value.y()
                axes = self.plot.presentation.axes
                try:
                    x = 10**x if axes["x"]["log"] else x
                    y = (
                        10**y
                        if axes["right" if anchor == "right" else "y"]["log"]
                        else y
                    )
                except OverflowError:
                    x = y = math.inf
            result.extend((x, y))
        return result

    def redraw(self, *args):
        for i, record in enumerate(self.records):
            item = self.items.get(record["id"])
            if item:
                item.setZValue(1000 + i)
                item.rebuild()

    def restore(self, records, dirty=False):
        self.records = copy.deepcopy(records)
        ids = {r["id"] for r in self.records}
        for key in list(self.items):
            if key not in ids:
                item = self.items.pop(key)
                item.setParentItem(None)
                self.plot.ui.plot_widget.scene().removeItem(item)
                item.deleteLater()
        for r in self.records:
            if r["id"] not in self.items:
                self.items[r["id"]] = AnnotationItem(self, r)
            else:
                self.items[r["id"]].record = r
        if self.selected not in ids or not next((r['visible'] for r in self.records if r['id'] == self.selected), False):
            self.selected = None
        self.redraw()
        self.changed.emit()
        if dirty:
            self.plot.main_window.mark_project_dirty()

    def load(self, records):
        if not isinstance(records, list) or len(records) > 500:
            raise ValueError("每张图最多 500 个标注")
        for r in records:
            validate_annotation(r)
        if len({r["id"] for r in records}) != len(records):
            raise ValueError("标注标识重复")
        self.restore(records)
        self.history.clear()

    def commit(self, before, title):
        after = copy.deepcopy(self.records)
        if before != after:
            from tailor.text_style_controls import record_view_edit

            record_view_edit(
                self.plot,
                title,
                before,
                after,
                lambda plot, state: plot.annotations.restore(state, dirty=True),
            )
            self.restore(after, dirty=True)

    def current(self):
        return next((r for r in self.records if r["id"] == self.selected), None)

    def select(self, key):
        if key is not None and not any(r['id'] == key and r['visible'] for r in self.records):
            key = None
        if key:
            from tailor.graph_focus import activate_inset, restore_main

            parent = getattr(self.plot, "_inset_parent", None)
            if parent is not None:
                activate_inset(parent, getattr(self.plot,"_inset_extras",None))
            else:
                restore_main(getattr(self.plot, "_embedded_parent", self.plot))
            self.plot.curve_selection.clear()
            collection = getattr(getattr(self.plot, 'extras', None), 'collection', None)
            if collection is not None and collection.selected is not None:
                collection.select(None)
        self.selected = key
        if self.panel and key:
            from tailor.text_style_controls import reveal_section

            reveal_section(
                self.plot, getattr(self, "graph_page", self.panel), "添加标注"
            )
            self.plot.text_selection.select(None)
            self.plot.curve_selection.current = None
            self.plot.curve_selection.refresh()
        self.changed.emit()
        self.redraw()

    def add(self, kind, anchor, points):
        if len(self.records) >= 500:
            raise ValueError("每张图最多 500 个标注")
        record = {
            "id": uuid.uuid4().hex,
            "kind": kind,
            "anchor": anchor,
            "points": points,
            "text": "文字",
            "color": "#202020",
            "fill": "",
            "width": 1.5,
            "size": 14,
            "family": "sans-serif",
            "bold": False,
            "visible": True,
            "locked": False,
            "rotation": 0,
            "linestyle": "solid",
        }
        if kind == "image":
            record["image_data"] = getattr(self, "_new_image_data", "")
            record['aspect_locked']=True
        self.validate(record)
        from tailor.choice_catalog import seed_objects,object_rank
        seed_objects(self.plot);object_rank(self.plot,'annotation',record['id'])
        before = copy.deepcopy(self.records)
        self.records.append(record)
        self.commit(before, "添加标注")
        self.select(record["id"])
        return record["id"]

    def replace(self, record):
        self.validate(record)
        # Hidden-menu callbacks operate on their own ID, regardless of which
        # annotation happens to be selected when the menu is activated.
        old = next((r for r in self.records if r['id'] == record['id']), None)
        if old is None:
            return
        if (
            old["locked"]
            and record["locked"]
            and any(
                old.get(k) != record[k] for k in record if k not in {"visible", "locked"}
            )
        ):
            raise ValueError("请先取消锁定再修改标注")
        before = copy.deepcopy(self.records)
        self.records[self.records.index(old)] = copy.deepcopy(record)
        self.commit(before, "修改标注")

    def delete(self):
        record = self.current()
        if record is None or record["locked"]:
            return
        before = copy.deepcopy(self.records)
        self.records.remove(record)
        self.commit(before, "删除标注")

    def duplicate(self):
        record = self.current()
        if record is None or len(self.records) >= 500:
            return
        record = copy.deepcopy(record)
        record["id"] = uuid.uuid4().hex
        record["locked"] = False
        before = copy.deepcopy(self.records)
        self.records.append(record)
        self.commit(before, "复制标注")
        self.select(record["id"])

    def reorder(self, delta):
        record = self.current()
        if record is None or record["locked"]:
            return
        before = copy.deepcopy(self.records)
        i = self.records.index(record)
        self.records.insert(
            max(0, min(len(self.records) - 1, i + delta)), self.records.pop(i)
        )
        self.commit(before, "调整标注层次")

    def clear_preview(self):
        if self.preview is not None:
            self.preview.setParentItem(None)
            self.plot.ui.plot_widget.scene().removeItem(self.preview)
            self.preview.deleteLater()
            self.preview = None

    def scene_moved(self, pos):
        if self.tool and self.start is not None:
            point = self.box.mapFromScene(pos)
            # Temporary item is deliberately absent from records/history/export.
            template = {
                "id": "__preview__",
                "kind": self.tool,
                "anchor": self.anchor,
                "points": self.from_pixels(self.anchor, [self.start, point]),
                "text": "",
                "color": "#2878cc",
                "fill": "",
                "width": 1.5,
                "size": 14,
                "family": "sans-serif",
                "bold": False,
                "visible": True,
                "locked": False,
                "rotation": 0,
                "linestyle": "solid",
            }
            if self.preview is None:
                self.preview = AnnotationItem(self, template)
                self.preview.setAcceptedMouseButtons(QtCore.Qt.NoButton)
                self.preview.setZValue(1000)
            else:
                self.preview.record = template
                self.preview.rebuild()

    def add_image(self, filename):
        import base64
        from pathlib import Path

        data = Path(filename).read_bytes()
        if len(data) > 12 * 1024 * 1024:
            raise ValueError("图片请小于12MB")
        image = QtGui.QImage.fromData(data)
        if image.isNull():
            raise ValueError("无法读取该图片")
        self._new_image_data = base64.b64encode(data).decode("ascii")
        root=getattr(self.plot,'_embedded_parent',None)
        view=getattr(root,'advanced_view',None)
        if view is not None and view.cfg.get('kind')=='panels':
            self.arm('place_image')
        else:
            self.add("image", "canvas", [0.35, 0.35, 0.65, 0.65])
            del self._new_image_data

    def arm(self, tool):
        if tool == "image":
            filename, _ = QtWidgets.QFileDialog.getOpenFileName(
                self.plot,
                "添加图片",
                "",
                "图片 (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)",
            )
            if filename:
                try:
                    self.add_image(filename)
                except (ValueError, OSError) as error:
                    self.plot.main_window.statusBar().showMessage(str(error))
            return
        self.clear_preview()
        self.tool, self.start = tool, None
        self.plot.ui.plot_widget.viewport().setCursor(
            QtCore.Qt.CrossCursor if tool else QtCore.Qt.ArrowCursor
        )
        if self.panel:
            self.panel.message.setText(
                "点击图中放置；双点图形依次点击起点、终点。Esc 取消。"
                if tool
                else "点击对象选择；拖动移动，拖动端点调整大小。"
            )

    def scene_clicked(self, event):
        from tailor.point_inspector import point_active
        if point_active(self.plot):return
        from tailor.graph_focus import is_inset_event

        if is_inset_event(self.plot, event):
            return
        if event.button() != QtCore.Qt.LeftButton:
            return
        if not self.tool:
            if not self.blocks_point(event) and self.box.sceneBoundingRect().contains(
                event.scenePos()
            ):
                self.select(None)
            return
        point = self.box.mapFromScene(event.scenePos())
        if not self.box.boundingRect().contains(point):
            return
        if self.anchor == "right" and not self.plot.presentation.has_right():
            self.panel.message.setText("请先在图形页启用右 Y 轴曲线。")
            return
        if self.tool=='place_image':
            center=self.from_pixels('canvas',[point,point])[:2]
            x,y=center
            self.add('image','canvas',[x-.15,y-.15,x+.15,y+.15])
            self.arm(None)
            del self._new_image_data
            event.accept()
            return
        if self.tool not in ONE_POINT and self.start is None:
            self.start = point
            self.scene_moved(event.scenePos() + QtCore.QPointF(1, 0))
            self.panel.message.setText("起点已选，请点击终点；Esc 取消。")
            event.accept()
            return
        try:
            self.add(
                self.tool,
                self.anchor,
                self.from_pixels(self.anchor, [self.start or point, point]),
            )
            self.arm(None)
        except ValueError as error:
            self.panel.message.setText(str(error))
        event.accept()

    def blocks_point(self, event):
        return bool(self.tool) or any(
            item.isVisible()
            and item.shape().contains(item.mapFromScene(event.scenePos()))
            for item in self.items.values()
        )

    def export(self, left, right=None):
        from tailor.annotation_export import export_annotations

        export_annotations(self, left, right)

    def close(self):
        self.arm(None)
        self.box.sigRangeChanged.disconnect(self.redraw)
        self.box.sigResized.disconnect(self.redraw)
        if self.plot.presentation.right_box is not None:
            self.plot.presentation.right_box.sigRangeChanged.disconnect(self.redraw)
        self._event_scene.sigMouseClicked.disconnect(self.scene_clicked)
        self._event_scene.sigMouseMoved.disconnect(self.scene_moved)
        self.restore([])
        self.history.clear()

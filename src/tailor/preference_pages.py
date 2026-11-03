"""Shared inspector overlays adapting existing per-object editors and styles."""

import copy
import json
from dataclasses import replace

from PySide6 import QtCore, QtGui, QtWidgets

from tailor.compact_controls import (
    IconChoices,
    card,
    equal_row,
    preference_button,
    stepper,
    toggle_button,
)
from tailor.curve_style import CurveStyle
from tailor.graph_controls import combo, number, row
from tailor.object_text_editor import ObjectTextEditor
from tailor.view_history import view_transaction


class Presets(QtWidgets.QWidget):
    def __init__(self, kind, read, apply):
        super().__init__()
        self.settings = QtCore.QSettings("PhysicsPlot", "StylePresets")
        self.kind, self.read, self.apply = kind, read, apply
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 0)
        heading = QtWidgets.QLabel("已存格式")
        heading.setProperty("cardTitle", True)
        layout.addWidget(heading)
        self.slots = []
        for i in range(3):
            line = QtWidgets.QHBoxLayout()
            apply_button = QtWidgets.QPushButton()
            save = QtWidgets.QToolButton()
            save.setText("✓")
            save.setToolTip("完成设置，保存到此预设")
            apply_button.clicked.connect(lambda checked=False, i=i: self.load(i))
            save.clicked.connect(lambda checked=False, i=i: self.save(i))
            line.addWidget(apply_button, 1)
            line.addWidget(save)
            layout.addLayout(line)
            self.slots.append(apply_button)
        self.refresh()

    def value(self, i):
        try:
            return json.loads(self.settings.value(f"{self.kind}/{i}", "null"))
        except (ValueError, TypeError):
            return None

    def refresh(self):
        for i, button in enumerate(self.slots):
            value = self.value(i)
            button.setText(value["name"] if value else f"空预设 {i + 1}")
            button.setEnabled(value is not None)

    def save(self, i):
        old = self.value(i)
        name, ok = QtWidgets.QInputDialog.getText(
            self, "保存格式", "格式名称", text=old["name"] if old else f"格式{i + 1}"
        )
        if ok and name.strip():
            self.settings.setValue(
                f"{self.kind}/{i}",
                json.dumps(
                    {"name": name.strip(), "style": self.read()}, ensure_ascii=False
                ),
            )
            self.refresh()

    def load(self, i):
        value = self.value(i)
        if value:
            self.apply(copy.deepcopy(value["style"]))


class CurveEditor(QtWidgets.QWidget):
    def __init__(self, host, *, deferred=False):
        super().__init__()
        self._build_steps = self._build(host)
        if not deferred:
            for _ in self._build_steps:
                pass

    def _build(self, host):
        self.host = host
        self.loading = False
        self.form = QtWidgets.QFormLayout(self)
        self.mode = combo(
            __import__("tailor.plot_types", fromlist=["MODE_ITEMS"]).MODE_ITEMS
        )
        from tailor.graph_controls import MARKERS, color_button
        from tailor.line_styles import LINE_STYLES

        self.pattern = combo(LINE_STYLES)
        self.color = color_button("#202020", lambda c: self.apply())
        from tailor.color_palette import ColorPalette

        self.color.setParent(self)
        self.color.hide()
        self.color_palette = ColorPalette("line")
        self.color_palette.changed.connect(self.palette_color)
        self.fill_palette = ColorPalette("line-fill")
        self.fill_palette.changed.connect(lambda value: self.apply())
        self.width = number(0.1, 20, 1.5)
        self.size = number(1, 30, 5)
        self.marker = combo(MARKERS)
        self.opacity = number(0, 100, 100, 0)
        self.opacity.setAccessibleName('整体不透明度')
        self.opacity.setToolTip('整体不透明度：同时影响当前对象的描边、标记和填充；100%为不透明。')
        self.cap = combo(
            [("圆形端点", "round"), ("平直端点", "flat"), ("方形延伸端点", "square")]
        )
        self.join = combo([("圆", "round"), ("斜角", "bevel"), ("尖角", "miter")])
        self.fill = toggle_button("曲线下方填充")
        self.marker_fill = toggle_button("填充数据点")
        self.step = QtWidgets.QSpinBox()
        self.step.setRange(1, 10000)
        self.stair = toggle_button("阶梯线")
        from tailor.line_styles import curve_pen
        from tailor.plot_types import ICONS, icon

        yield
        mode_icons = [icon(name, self, "#448ad5") for name in ICONS]
        mode_choices = IconChoices(self.mode, mode_icons)
        style_icons = []
        for title, key in LINE_STYLES:
            pix = QtGui.QPixmap(80, 34)
            pix.fill(QtCore.Qt.transparent)
            painter = QtGui.QPainter(pix)
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            painter.setPen(curve_pen("#448ad5", 2, key))
            painter.drawLine(5, 17, 75, 17)
            painter.end()
            pix.setDevicePixelRatio(2)
            style_icons.append(QtGui.QIcon(pix))
        patterns = IconChoices(self.pattern, style_icons)
        basics = QtWidgets.QFormLayout()
        for title, widget in (
            ("绘制方式", mode_choices),
            ("样式", patterns),
            ("颜色", self.color_palette),
            ("线宽", row(self.width, "px")),
            ("点形状", self.marker),
            ("点大小", row(self.size, "px")),
            ("不透明度", row(self.opacity, "%")),
        ):
            basics.addRow(title, widget)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setSpacing(8)
        self.closed_fill = ColorPalette("line-fill")
        self.closed_fill.changed.connect(lambda value: self.apply())
        self.closed_opacity = number(0, 100, 18, 0)
        self.closed_opacity.setAccessibleName('封闭标注填充不透明度')
        self.closed_opacity.setToolTip('仅控制封闭标注的内部填充，与整体不透明度独立。')
        self.closed_opacity.valueChanged.connect(self.apply)
        basics.addRow("填充", self.closed_fill)
        basics.addRow("填充透明", row(self.closed_opacity, "%"))
        yield
        self.form.addRow(card("基础", basics))
        yield
        advanced = QtWidgets.QFormLayout()
        from tailor.inset_shapes import cap_icon

        cap_choices = IconChoices(self.cap, [cap_icon(k) for k in ("round", "flat", "square")])
        cap_choices.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self.join.setMinimumWidth(0)
        self.join.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
        advanced.addRow(row("线端", cap_choices, "连接", self.join))
        self.fill.setText('填充颜色')
        self.fill.setToolTip('开启或关闭曲线与零基线之间的填充；右侧设置填充颜色。')
        advanced.addRow(row(self.fill,self.fill_palette))
        self.marker_fill.setToolTip('控制点标记的实心/空心；仅散点或折线加散点可用。')
        self.stair.setToolTip('以水平台阶连接相邻点，不修改原始数据或进行插值。')
        advanced.addRow(row(self.marker_fill,self.stair))
        advanced.addRow("标记间隔", row(self.step,"点"))
        self.advanced_card=card("高级绘图", advanced)
        self.form.addRow(self.advanced_card)
        yield
        self.form.addRow(card(None, Presets("curve", self.spec, self.load_preset)))
        for c in (self.mode, self.pattern, self.marker, self.cap, self.join):
            c.activated.connect(self.apply)
        for c in (self.width, self.size, self.opacity, self.step):
            c.valueChanged.connect(self.apply)
        for c in (self.fill, self.marker_fill, self.stair):
            c.toggled.connect(self.apply)

    def spec(self):
        result = {
            "mode": self.mode.currentData(),
            "line_style": self.pattern.currentData(),
            "color": self.color.text(),
            "line_width": self.width.value(),
            "marker_size": self.size.value(),
            "marker": self.marker.currentData(),
            "opacity": self.opacity.value() / 100,
            "cap": self.cap.currentData(),
            "join": self.join.currentData(),
            "fill": self.fill.isChecked(),
            "fill_color": self.fill_palette.value or "#cfe8ff",
            "marker_fill": self.marker_fill.isChecked(),
            "marker_step": self.step.value(),
            "step_mode": self.stair.isChecked(),
        }
        from tailor.choice_state import actionable_setting
        return {key:value for key,value in result.items() if key not in {'marker','join'} or actionable_setting(value)}

    def palette_color(self, value):
        self.color.setText(value or "#202020")
        self.apply(_force={'color'})

    def load(self, style, limited=False):
        self.loading = True
        for name, key in [
            ("mode", "mode"),
            ("pattern", "line_style"),
            ("marker", "marker"),
            ("cap", "cap"),
            ("join", "join"),
        ]:
            b = getattr(self, name)
            if name in {'marker','join'}:
                from tailor.choice_state import show_setting
                show_setting(b,getattr(style,key))
            else:b.setCurrentIndex(max(0, b.findData(getattr(style, key))))
        self.color.setText(style.color)
        self.color_palette.set_value(style.color)
        self.fill_palette.set_value(style.fill_color)
        self.width.setValue(style.line_width)
        self.size.setValue(style.marker_size)
        self.opacity.setValue(style.opacity * 100)
        self.fill.setChecked(style.fill)
        self.marker_fill.setChecked(style.marker_fill)
        self.step.setValue(style.marker_step)
        self.stair.setChecked(style.step_mode)
        for c in (
            self.mode,
            self.marker,
            self.size,
            self.cap,
            self.join,
            self.fill,
            self.marker_fill,
            self.step,
            self.stair,
        ):
            c.setEnabled(not limited)
        record = self.host.plot.annotations.current() if self.host.curve_target[0] == "annotation" else None
        if record:
            self.closed_fill.set_value(record.get("fill", ""))
            self.closed_opacity.setValue(record.get("fill_opacity", .18) * 100)
        self.loading = False
        self.sync_enabled()
        self._last_spec = self.edit_spec()

    def edit_spec(self):
        spec=self.spec()
        if self.host.curve_target[0]=='annotation':
            record=self.host.plot.annotations.current()
            if record and record['kind'] in {'rectangle','ellipse'}:
                spec.update(annotation_fill=self.closed_fill.value,annotation_fill_opacity=self.closed_opacity.value()/100)
        return spec

    def sync_enabled(self):
        kind = self.host.curve_target[0]
        mode = self.mode.currentData()
        record = self.host.plot.annotations.current() if kind == "annotation" else None
        closed = bool(record and record["kind"] in {"rectangle", "ellipse"})
        self.closed_fill.setEnabled(closed)
        self.closed_opacity.setEnabled(closed)
        restricted = kind in {
            "annotation",
            "axis",
            "grid",
            "legend_border",
            "legend_background",
            "inset_connection",
            "inset_source",
            "inset_plot",
        }
        self.fill_palette.setEnabled(not restricted)
        background = kind == "legend_background"
        self.mode.setEnabled(not restricted)
        self.color.setEnabled(True)
        self.color_palette.setEnabled(True)
        self.pattern.setEnabled(not background and mode != "scatter" and kind != "axis")
        self.opacity.setEnabled(kind != "axis")
        self.width.setEnabled(not background and mode != "scatter")
        self.marker.setEnabled(not restricted and mode in {"scatter", "line_scatter"})
        self.size.setEnabled(not restricted and mode in {"scatter", "line_scatter"})
        for widget in (
            self.cap,
            self.join,
            self.fill,
            self.marker_fill,
            self.step,
            self.stair,
        ):
            widget.setEnabled(not restricted)
        self.marker_fill.setEnabled(not restricted and mode in {'scatter','line_scatter'})
        self.step.setEnabled(not restricted and mode in {'scatter','line_scatter'})
        self.stair.setEnabled(not restricted and mode in {'line','line_scatter','area','step'})
        self.fill.setEnabled(not restricted and mode in {'line','line_scatter','area','step'})
        self.fill_palette.setEnabled(self.fill.isEnabled())

        if kind == 'band':
            for widget in (self.mode, self.pattern, self.width, self.marker,
                           self.size, self.cap, self.join, self.fill,
                           self.marker_fill, self.step, self.stair,
                           self.fill_palette, self.closed_fill, self.closed_opacity):
                widget.setEnabled(False)
        for preset in self.findChildren(Presets):
            preset.setEnabled(kind != 'band')

        if kind == "advanced":
            cfg = self.host.plot.advanced_view.cfg
            advanced_kind = cfg["kind"]
            if advanced_kind != "panels":
                scatter = (
                    advanced_kind == "3d"
                    and cfg.get("three_mode", "scatter") == "scatter"
                )
                self.mode.setEnabled(False)
                self.pattern.setEnabled(advanced_kind == "bar")
                self.width.setEnabled(not scatter)
                surface = advanced_kind == "3d" and cfg.get("three_mode") == "surface"
                self.color_palette.setEnabled(not surface)
                self.marker.setEnabled(scatter)
                self.size.setEnabled(scatter)
                for widget in (
                    self.cap,
                    self.join,
                    self.fill,
                    self.marker_fill,
                    self.step,
                    self.stair,
                ):
                    widget.setEnabled(False)

        root = getattr(self.host.plot, "_embedded_parent", self.host.plot)
        view = getattr(root, "advanced_view", None)
        # Qt pens use screen units; Matplotlib's 3D strokes/markers use points.
        # Describe the existing backend value without converting saved styles.
        unit='pt' if view and view.cfg['kind']=='3d' else 'px'
        for field in (self.width,self.size):
            control=stepper(field)
            control.value_unit_label.setText(unit)
            field.setProperty('sliderUnit',unit)
        if view and kind in {"data", "all", "advanced"}:
            advanced_kind = view.cfg["kind"]
            if advanced_kind == "bar":
                self.mode.setEnabled(False)
                self.marker.setEnabled(False)
                self.size.setEnabled(False)
                self.fill.setText('填充颜色')
            elif advanced_kind == "3d":
                self.fill_palette.setEnabled(False)
                mode = view.cfg.get("three_mode", "scatter")
                self.mode.setEnabled(False)
                self.pattern.setEnabled(mode in {"line", "wire"})
                self.width.setEnabled(mode in {"line", "wire"})
                self.marker.setEnabled(mode == "scatter")
                self.size.setEnabled(mode == "scatter")
                self.color_palette.setEnabled(
                    mode in {"line", "wire"}
                    or mode == "scatter"
                    and not view.cfg.get("colorbar", True)
                )
                for widget in (
                    self.cap,
                    self.join,
                    self.fill,
                    self.marker_fill,
                    self.step,
                    self.stair,
                ):
                    widget.setEnabled(False)

    def apply(self, *args, _force=None, _all=False):
        if self.loading or not self.host._curve_allowed:
            return
        self.sync_enabled()
        spec=self.edit_spec()
        previous=getattr(self,'_last_spec',{})
        changed=spec if _all else {key:value for key,value in spec.items() if previous.get(key)!=value or key in (_force or ())}
        if changed:self.host.apply_curve(changed)
        self._last_spec=spec

    def load_preset(self, spec):
        style = replace(self.host.curve_style(), **spec)
        self.load(style, self.host.curve_target[0] == "axis")
        self.apply(_all=True)


class PreferenceHost(QtWidgets.QStackedWidget):
    def __init__(self, plot, graph):
        super().__init__()
        self.plot, self.graph = plot, graph
        self.tabs = plot.property_tabs
        self.editor = None
        self.font_target = None
        self._font_allowed = False
        self._curve_allowed = False
        self.curve_target = ('none',None)
        self.addWidget(self.tabs)
        if graph is not None:
            self.setup_pages()

    def setup_pages(self, *, deferred=False):
        steps = self._setup_pages()
        if deferred:
            return steps
        for _ in steps:
            pass

    def _setup_pages(self):
        self.font_page, self.font_layout, self.font_title = self.page("字体偏好")
        self.editor_container = QtWidgets.QVBoxLayout()
        self.font_layout.addLayout(self.editor_container)
        self.font_layout.addWidget(
            card(
                None,
                Presets(
                    "font",
                    lambda: self.editor.spec() if self.editor else {},
                    self.apply_font_preset,
                ),
            )
        )
        self.font_layout.addStretch()
        self.curve_page, layout, self.curve_title = self.page("线条偏好")
        yield
        self.curve_editor = CurveEditor(self, deferred=True)
        yield from self.curve_editor._build_steps
        layout.addWidget(self.curve_editor)
        layout.addStretch()

    def minimumSizeHint(self):
        return QtCore.QSize(380, 200)

    def sizeHint(self):
        return QtCore.QSize(440, 600)

    def page(self, title):
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        body = QtWidgets.QWidget()
        body.setProperty("inspectorContent", True)
        body.setSizePolicy(
            QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred
        )
        layout = QtWidgets.QVBoxLayout(body)
        layout.setSizeConstraint(QtWidgets.QLayout.SetNoConstraint)
        layout.setContentsMargins(12, 10, 12, 10)
        back = QtWidgets.QPushButton("‹ 返回功能区")
        back.clicked.connect(self.return_to_inspector)
        layout.addWidget(back)
        label = QtWidgets.QLabel(title)
        label.setProperty("cardTitle", True)
        label.setWordWrap(True)
        layout.addWidget(label)
        scroll.setWidget(body)
        self.addWidget(scroll)
        return scroll, layout, label

    def remember_inspector(self):
        if self.currentIndex() != 0:
            return
        page = self.tabs.currentWidget()
        self._return_tab=page
        if not isinstance(getattr(page,'scroll',None),QtWidgets.QAbstractScrollArea) and hasattr(page,'stack'):
            page=page.stack.currentWidget()
        if page is None or not isinstance(getattr(page,'scroll',None),QtWidgets.QAbstractScrollArea):
            self._return_view=None;return
        self._return_view = (
            page,
            page.scroll.verticalScrollBar().value(),
            [(r, r[2]) for r in getattr(page, "sections", [])],
        )

    def preference_mode(self):
        if self.currentWidget() is getattr(self,'font_page',None):return 'font'
        if self.currentWidget() is getattr(self,'curve_page',None):return 'curve'
        return None

    def follow_preference_mode(self,mode):
        if mode:self.setCurrentWidget(self.font_page if mode=='font' else self.curve_page)

    def return_to_inspector(self):
        saved = getattr(self, "_return_view", None)
        self.setCurrentIndex(0)
        if saved:
            page, value, sections = saved
            self.tabs.setCurrentWidget(getattr(self,'_return_tab',page))
            for record, opened in sections:
                page.set_open(record, opened)
            page.scroll.verticalScrollBar().setValue(value)
            QtCore.QTimer.singleShot(
                0, page, lambda: page.scroll.verticalScrollBar().setValue(value)
            )

    def select_font(self, editor, title):
        follow=self.preference_mode() is not None
        self.font_target = (editor, title)
        old = self.editor
        if old is not editor:
            if old is not None:
                self.editor_container.removeWidget(old)
                old.setParent(self.parking)
                old.hide()
            self.editor = editor
            self.editor_container.addWidget(editor)
            editor.show()
        editor.set_target_selected(True)
        editor.set_annotation_mode(editor is getattr(self.plot, "annotation_font_editor", None))
        if editor is getattr(self.plot.axis_controls,'factor_editor',None):
            editor.orientation.setEnabled(True);editor.orientation_buttons.setEnabled(True)
        editor.layout().setContentsMargins(10, 10, 10, 10)
        from tailor.fold_panel import normalize_control_heights
        normalize_control_heights(editor)
        editor.sync_field_titles()
        editor.schedule_field_titles()
        self.font_title.setText("字体偏好 · " + title)
        axis = self.plot.axis_controls
        ticks = editor is axis.text_editor and axis.text_target.currentData() == "ticks"
        for widget in (
            editor.align,
            editor.spacing,
            editor.has_background,
            editor.background,
            editor.background_palette,
            editor.overline,
            editor.wave,
            editor.dot,
            editor.greek,
        ):
            widget.setEnabled(not ticks and not (widget is editor.spacing and editor.property('spacingAllowed') is False))
        view = getattr(self.plot, "advanced_view", None)
        if view and view.cfg["kind"] in {"3d", "panels"}:
            # Content editability is defined by the selected text target's load().
            # Native child documents of grouped plots use the same editor.
            pass
            if view.cfg["kind"] == "3d":
                editor.setProperty('wholeTargetFont',True)
                for widget in (
                    editor.align,
                    editor.spacing,
                    editor.has_background,
                    editor.background,
                    editor.background_palette,
                    editor.underline,
                ):
                    widget.setEnabled(False)
        self._font_allowed = True
        if editor is self.plot.legend_controls.editor:
            key = self.plot.legend_controls.target.currentData()
            self.curve_target = (
                ("legend_all", None) if key == "__all__" else ("legend", key)
            )
            self._curve_allowed = key is not None
        else:
            self._curve_allowed = False
        self.plot.quick_actions.buttons["font"].setEnabled(True)
        self.plot.quick_actions.buttons["curve"].setEnabled(self._curve_allowed)
        if follow:self.setCurrentWidget(self.font_page)

    def clear_group_selection(self):
        """A panel button owns its local target, rather than the last scene pick."""
        self.plot.curve_selection.clear()
        self.plot.annotations.select(None)
        collection=getattr(getattr(self.plot,'extras',None),'collection',None)
        if collection is not None:collection.select(None)
        self.plot.text_selection.select(None)

    def open_group_curve(self,kind,value):
        self.clear_group_selection()
        if kind.startswith('legend'):
            self.plot.text_selection.select('legend')
        elif kind=='axis':
            self.plot.text_selection.select('axis:'+value)
        self.select_curve(kind,value,True)
        if kind=='none':self.open_curve()

    def open_font(self, editor=None, title=None):
        self.remember_inspector()
        if editor is None and not self._font_allowed:
            if self.editor is None:
                self.editor=self.plot.axis_controls.text_editor
                self.editor_container.addWidget(self.editor)
                self.editor.show()
            if self.editor is not None:
                self.editor.set_target_selected(False)
            self.font_title.setText('字体偏好 · —')
            self.setCurrentWidget(self.font_page)
            return
        if editor is None and self.font_target is not None:
            editor, title = self.font_target
        if editor is not None:
            self.select_font(editor, title or "当前文字")
        if self.editor is None:
            axis = self.plot.axis_controls
            self.select_font(axis.text_editor, axis.current_label.text())
        self.setCurrentWidget(self.font_page)

    def apply_font_preset(self, spec):
        if self.editor:
            value = (
                self.editor.content.text() if self.editor.content.isEnabled() else None
            )
            self.editor.load(spec, value)
            self.editor.notify()

    def select_curve(self, kind, value, open_page=False):
        open_page=open_page or self.preference_mode() is not None
        if kind=='none':
            self.plot.curve_selection.current=None
            self.plot.curve_selection.override_item=None
            self.plot._selected_drawn_key=None
            if hasattr(self.plot,'fit_actions'):self.plot.fit_actions.clear_selection()
            self.plot.curve_selection.refresh()
            self.clear_curve_target()
            return
        if open_page:
            self.remember_inspector()
        self.curve_target = (kind, value)
        if kind == "all":
            self.plot._selected_drawn_key = None
            self.plot.curve_selection.current = None
            self.plot.curve_selection.override_item = None
            self.plot.curve_selection.refresh()
        if kind == "data":
            self.plot._selected_drawn_key = None
            self.plot.curve_selection.current = value
            self.plot.curve_selection.override_item=None
        elif kind == "drawn":
            self.plot._selected_drawn_key = value
            self.plot.curve_selection.current = None
            self.plot.curve_selection.override_item=drawn_item(self.plot,value)
        self._font_allowed = kind in {"legend", "legend_all"} or (kind == "annotation" and bool(self.plot.annotations.current()) and self.plot.annotations.current()["kind"] == "text")
        self._curve_allowed = True
        if kind in {"legend", "legend_all"}:
            legend = self.plot.legend_controls
            legend.select_entry("__all__" if kind == "legend_all" else value)
            self.select_font(legend.editor, legend.target.currentText())
        elif kind == "annotation" and self._font_allowed:
            self.select_font(self.plot.annotation_font_editor, "文字标注")
        elif self.editor:
            self.editor.set_target_selected(False)
        self.curve_editor.setEnabled(self._curve_allowed)
        self.plot.quick_actions.buttons["font"].setEnabled(self._font_allowed)
        self.plot.quick_actions.buttons["curve"].setEnabled(self._curve_allowed)
        if kind == "data" and self.plot.presentation.multi:
            manager = self.plot.curve_manager
            manager.curves.setCurrentIndex(manager.curves.findData(value))
        self.refresh_targets()
        self.plot.curve_selection.refresh()
        self.plot.axis_controls.sync()
        self.sync_curve_context(kind,value)
        if kind=='data' and hasattr(self.plot,'fit_router'):
            router=self.plot.fit_router
            if open_page:
                with QtCore.QSignalBlocker(router.choice):
                    router.choice.setCurrentIndex(max(0,router.choice.findData(value)))
            else:router.select_source(value)
        self.curve_editor.load(self.curve_style(), kind == "axis")
        if kind=='all':
            from tailor.choice_state import show_setting
            styles=[CurveStyle(**info.style) if info.style else source.curve_style
                    for source,info in self.plot.model._plots.items()] if self.plot.presentation.multi else [self.plot.curve_style]
            for name in ('marker','join'):
                values={getattr(style,name) for style in styles}
                show_setting(getattr(self.curve_editor,name),next(iter(values),None),mixed=len(values)>1)
        self.curve_title.setText("线条偏好 · " + self.target_name(kind, value))
        from tailor.text_style_controls import reveal_section

        page = self.plot.axis_controls if kind in {"axis", "grid"} else self.graph
        title = (
            '置信带与预测带'
            if kind == 'band'
            else
            "网格"
            if kind == "grid"
            else "标题与轴线"
            if kind == "axis"
            else "局部放大"
            if kind.startswith("inset_")
            else "添加标注"
            if kind == "annotation"
            else "图例"
            if kind.startswith("legend")
            else "曲线"
        )
        if kind=='band':
            self.plot.extras.bands.reveal()
        else:
            reveal_section(self.plot, page, title)
        if open_page:
            self.setCurrentWidget(self.curve_page)
        self.plot.quick_actions.sync()

    def open_curve(self):
        if not self._curve_allowed:
            self.remember_inspector()
            self.curve_editor.setEnabled(False)
            self.setCurrentWidget(self.curve_page)
            return
        if self.curve_target[0] == "annotation" and not self.plot.annotations.current():
            self.curve_editor.setEnabled(False)
            return
        self.select_curve(*self.curve_target, open_page=True)

    def target_name(self, kind, value):
        if kind == 'band':
            key, band_kind = value
            entry = self.plot.extras.bands.entries().get(key)
            return ('置信带' if band_kind == 'confidence' else '预测带') + ' · ' + (entry[2] if entry else '—')
        if kind == "advanced":
            return "高级绘图对象 " + str(int(value) + 1)
        if kind in {"inset_connection", "inset_source", "inset_plot"}:
            return "局部放大连接线"
        names = {
            "all": "全部曲线",
            "legend_all": "全部图例",
            "legend_border": "图例边框",
            "legend_background": "图例底色",
            "grid": "网格",
        }
        if kind in names:
            return names[kind]
        if kind == "axis":
            return {
                "x": "下 X 轴",
                "y": "左 Y 轴",
                "top": "上 X 轴",
                "right": "右 Y 轴",
            }[value]
        if kind == "annotation":
            from tailor.annotations import KINDS

            record = next(
                (r for r in self.plot.annotations.records if r["id"] == value), None
            )
            return "标注 · " + (KINDS.get(record["kind"], "对象") if record else "对象")
        if kind in {"drawn", "legend"}:
            from tailor.text_style_controls import legend_rows

            label = next(
                (name for key, name, _ in legend_rows(self.plot) if key == value),
                "曲线",
            )
            from tailor.text_accents import caption
            return (
                "绘制曲线 · " if kind == "drawn" else "图例线条 · "
            ) + caption(label)
        if kind == "data" and value is not None:
            from tailor.column_titles import display
            return display(value.data_sheet.model, value.model.y_col)
        return value.name if value else "曲线"

    def refresh_targets(self):
        if not hasattr(self, "targets"):
            return
        with QtCore.QSignalBlocker(self.targets):
            self.targets.clear()
            self.targets.addItem('—',('none',None))
            from tailor.choice_catalog import sorted_sources
            sources = sorted_sources(self.plot)
            for source in sources:
                if source.id in self.plot.presentation.extra_settings.get("deleted_curves", []):
                    continue
                self.targets.addItem(self.target_name("data", source), ("data", source))
            for key, (item, name) in available_curves(self.plot,include_hidden=False).items():
                if key != "data" and not key.endswith(":data"):
                    self.targets.addItem(name, ("drawn", key))
            if self.targets.count()>1:self.targets.addItem("全部曲线", ("all", None))
            from tailor.choice_catalog import sort_combo
            sort_combo(self.targets)
            for i in range(self.targets.count()):
                if self.targets.itemData(i) == self.curve_target:
                    self.targets.setCurrentIndex(i)
                    break
        if self.targets.currentIndex()==0 and self.curve_target[0] in {'data','drawn','all'}:
            self.plot._selected_drawn_key=None
            self.plot.curve_selection.current=None
            self.plot.curve_selection.override_item=None
            self.plot.curve_selection.refresh()
            self.curve_target=('none',None)
            self._curve_allowed=False
        self.curve_editor.setEnabled(self._curve_allowed)
        if not self._curve_allowed:
            for box in self.curve_editor.findChildren(QtWidgets.QComboBox):
                with QtCore.QSignalBlocker(box):
                    box.setPlaceholderText('—');box.setCurrentIndex(-1)

    def clear_curve_target(self):
        self.curve_target=('none',None)
        self._curve_allowed=False
        text=getattr(self.plot,'text_selection',None)
        annotation=getattr(self.plot,'annotations',None)
        if not getattr(text,'key',None) and not (annotation and annotation.current()):
            self._font_allowed=False
            if self.editor is not None:self.editor.set_target_selected(False)
        self.refresh_targets()
        if hasattr(self.plot,'quick_actions'):self.plot.quick_actions.sync()

    def sync_curve_context(self,kind,value):
        ref=None
        if kind=='data' and value is not None:ref=(value.data_sheet.id,value.model.y_col)
        elif kind=='drawn':
            from tailor.fit_workflow import fit_owner
            fitted=fit_owner(self.plot,value)
            if fitted:
                source,identifier=fitted
                record=next((r for r in source.fit_records if r['id']==identifier),None)
                if record:
                    from tailor.fit_results import curve_column
                    key = curve_column(record, value)
                    if key in source.data_sheet.model.columnLabels():
                        ref = (source.data_sheet.id, key)
        control=getattr(self.plot,'processing_controls',None)
        if ref and control is not None:
            control.targets=[ref];control.sync_objects_text()
        elif control is not None and kind=='drawn' and (':component:' in value or value.startswith('component:')):
            control.targets=[];control.sync_objects_text()

    def curve_style(self, target=None):
        kind, value = target or self.curve_target
        p = self.plot
        if kind == 'band':
            return p.extras.bands.style(value)
        if kind == "advanced":
            return p.advanced_view.style(int(value))
        if kind in {"inset_connection", "inset_source", "inset_plot"}:
            return replace(
                CurveStyle(mode="line"),
                **__import__("tailor.inset_collection",fromlist=["active"]).active(p.extras).cfg.get("inset", {}).get(
                    {
                        "inset_connection": "connector_style",
                        "inset_source": "source_style",
                        "inset_plot": "plot_style",
                    }[kind],
                    {},
                ),
            )
        if kind == "all":
            source = next(iter(p.model._plots), None) if p.presentation.multi else p
            return self.curve_style(('data',source)) if source else CurveStyle()
        if kind in {"legend_border", "legend_background"}:
            spec = p.presentation.legend.get(
                "border_style" if kind == "legend_border" else "background_style", {}
            )
            return replace(CurveStyle(mode="line"), **spec)
        if kind == "grid":
            cfg = p.presentation.axes[value]
            return CurveStyle(
                mode="line",
                color=cfg["grid_color"],
                line_width=cfg["grid_width"],
                line_style=cfg["grid_style"],
                opacity=cfg.get("grid_opacity", 1.0),
            )
        if kind == "axis":
            cfg = p.presentation.axes[value]
            return CurveStyle(
                mode="line", color=cfg["color"], line_width=cfg["axis_width"]
            )
        if kind == "annotation":
            r = next((r for r in p.annotations.records if r["id"] == value), None)
            return (
                replace(CurveStyle(
                    mode="line",
                    color=r["color"],
                    line_width=r["width"],
                    line_style=r["linestyle"],
                    fill=bool(r.get("fill")), fill_color=r.get("fill") or "#ffffff",
                ), **p.presentation.curve_overrides.get('annotation:'+value,{}))
                if r
                else CurveStyle()
            )
        if kind == "drawn":
            item = drawn_item(p, value)
            return replace(
                rendered_curve_style(item),
                **p.presentation.curve_overrides.get(value, {}),
            )
        if kind in {'legend','legend_all'}:
            if kind=='legend_all':
                from tailor.text_style_controls import legend_rows
                rows=legend_rows(p)
                value=rows[0][0] if rows else None
            legend = p.presentation.legend_item
            item = next(
                (
                    sample.item
                    for sample, label in legend.items
                    if getattr(sample.item, "_legend_key", None) == value
                ),
                None,
            )
            color = "#202020"
            width = 1.5
            if item is not None:
                import pyqtgraph as pg

                line_pen = item.opts.get("pen")
                has_line = line_pen is not None and pg.mkPen(line_pen).style() != QtCore.Qt.NoPen
                pen = pg.mkPen(line_pen if has_line else item.opts.get("symbolPen"))
                color = pen.color().name()
                width = max(0.1, pen.widthF())
                opacity = pen.color().alphaF()
                line_style = {QtCore.Qt.SolidLine:'solid',QtCore.Qt.DashLine:'dash',QtCore.Qt.DotLine:'dot',
                              QtCore.Qt.DashDotLine:'dashdot',QtCore.Qt.DashDotDotLine:'dashdotdot'}.get(pen.style(),'solid')
                if pen.style()==QtCore.Qt.CustomDashLine:
                    line_style='longdash' if list(pen.dashPattern())==[8,3] else 'shortdash' if list(pen.dashPattern())==[2,2] else 'dash'
            else:
                has_line = False
                opacity = 1.0
                line_style = 'solid'
            symbol = item.opts.get("symbol") if item is not None else None
            mode = (
                "line_scatter"
                if symbol and has_line
                else "scatter"
                if symbol
                else "line"
            )
            marker = symbol if isinstance(symbol, str) and symbol in {"o", "s", "t", "d", "+", "x", "star"} else "o"
            size = item.opts.get("symbolSize", 5) if item is not None else 5
            return replace(
                CurveStyle(
                    mode=mode,
                    color=color,
                    line_width=width,
                    line_style=line_style,
                    opacity=opacity,
                    marker=marker,
                    marker_size=float(size),
                    marker_fill=(pg.mkBrush(item.opts.get("symbolBrush")).style() != QtCore.Qt.NoBrush) if item is not None else True,
                ),
                **p.presentation.legend.get("samples", {}).get(value, {}),
            )
        if value is None:
            return CurveStyle()
        if p.presentation.multi:
            info = p.model.get_plot_info(value)
            return replace(
                CurveStyle(**info.style) if info.style else value.curve_style,
                color=info.color,
            )
        return value.curve_style

    @view_transaction("线条偏好")
    def apply_curve(self, spec):
        p = self.plot
        kind, value = self.curve_target
        changes=dict(spec)
        has_annotation_fill='annotation_fill' in changes
        annotation_fill=changes.pop('annotation_fill',None)
        annotation_fill_opacity=changes.pop('annotation_fill_opacity',None)
        spec={**self.curve_style().to_dict(),**changes}
        if kind == 'band':
            p.extras.bands.apply_style(value, spec)
        elif kind == "advanced":
            style = replace(self.curve_style(), **spec)
            p.advanced_view.cfg.setdefault("styles", {})[str(int(value))] = (
                style.to_dict()
            )
            if p.advanced_view.cfg["kind"] == "3d":
                p.apply_curve_style(style)
            p.advanced_view.schedule()
        elif kind in {"inset_connection", "inset_source", "inset_plot"}:
            selected_extras = __import__("tailor.inset_collection",fromlist=["active"]).active(p.extras)
            selected_extras.cfg.setdefault("inset", {})[
                {
                    "inset_connection": "connector_style",
                    "inset_source": "source_style",
                    "inset_plot": "plot_style",
                }[kind]
            ] = spec
            selected_extras.update_lines()
            selected_extras.apply_shapes()
        elif kind in {"legend_border", "legend_background"}:
            p.presentation.legend[
                "border_style" if kind == "legend_border" else "background_style"
            ] = spec
            p.presentation.apply_legend()
        elif kind == "grid":
            cfg = p.presentation.axes[value]
            cfg.update(
                grid_color=spec["color"],
                grid_width=min(3, spec["line_width"]),
                grid_style=spec["line_style"],
                grid_opacity=spec["opacity"],
            )
            p.presentation.grid_item.update()
            p.axis_controls.sync()
        elif kind == "all":
            catalog=available_curves(p,include_hidden=False)
            raw=set()
            if p.presentation.multi:
                for source, info in p.model._plots.items():
                    raw.add(f'plot:{source.id}:data')
                    if not info.visible:continue
                    style = replace(
                        self.curve_style(('data',source)),
                        **changes,
                    )
                    info.style, info.color = style.to_dict(), style.color
            else:
                from tailor.curve_controls import apply_style
                raw.add('data')
                apply_style(p, replace(p.curve_style, **changes))
            for key,(item,_) in catalog.items():
                if key in raw:continue
                original=self.curve_style(('drawn',key)).to_dict()
                original.update(changes)
                p.presentation.curve_overrides[key]=original
            if p.presentation.multi:p.draw_plot()
            apply_drawn_styles(p)
            p.presentation.apply_legend()
        elif kind == "axis":
            cfg = p.presentation.axes[value]
            cfg.update(color=spec["color"], axis_width=spec["line_width"])
            p.presentation.apply_axes()
            p.axis_controls.sync()
        elif kind == "annotation":
            p.presentation.curve_overrides["annotation:" + value] = spec
            r = next((r for r in p.annotations.records if r["id"] == value), None)
            if r:
                p.annotations.replace(
                    {
                        **r,
                        "color": spec["color"],
                        "width": spec["line_width"],
                        "linestyle": spec["line_style"],
                        **({'fill':annotation_fill or ''} if has_annotation_fill else {}),
                        **({'fill_opacity':annotation_fill_opacity} if annotation_fill_opacity is not None else {}),
                    }
                )
        elif kind == "drawn":
            p.presentation.curve_overrides[value] = spec
            apply_drawn_styles(p)
        elif kind == "legend_all":
            from tailor.text_style_controls import legend_rows
            for key, _, _ in legend_rows(p):
                original=self.curve_style(('legend',key)).to_dict()
                original.update(changes)
                p.presentation.legend.setdefault("samples", {})[key] = original
            apply_legend_samples(p)
            p.legend_controls.refresh_entries()
        elif kind == "legend":
            p.presentation.legend.setdefault("samples", {})[value] = spec
            apply_legend_samples(p)
            p.legend_controls.refresh_entries()
        elif value:
            style = replace(self.curve_style(), **spec)
            if p.presentation.multi:
                info = p.model.get_plot_info(value)
                info.style = style.to_dict()
                info.color = style.color
                p.draw_plot()
            else:
                from tailor.curve_controls import apply_style

                apply_style(p, style)
        if hasattr(p, "extras"):
            p.extras.refresh()
        p.main_window.mark_project_dirty()


def available_curves(plot, include_hidden=True):
    catalog = {}

    def name_for(key, item, name=None):
        from tailor.choice_catalog import curve_column
        ref=curve_column(plot,key)
        if ref:
            from tailor.column_titles import display
            label=display(*ref)
            if label:return label
        from tailor.fit_workflow import fit_owner
        fitted=fit_owner(plot,key)
        if fitted:
            source,identifier=fitted
            record=next((r for r in source.fit_records if r['id']==identifier),None)
            if record:
                from tailor.column_titles import display
                from tailor.fit_results import curve_column
                label=display(source.data_sheet.model,curve_column(record, key))
                if label:
                    return label
                if key.startswith('component:') or ':component:' in key:
                    return '分峰' + key.rsplit(':', 1)[1] + '（未生成数据列）'
        if key == "data":
            from tailor.column_titles import display
            return display(plot.data_sheet.model, plot.model.y_col)
        if key == "fit":
            return "拟合预览"
        if key.startswith("component:"):
            return "拟合预览 · 分峰" + key.split(":")[-1]
        if key.startswith("trend:"):
            return name or "趋势线"
        if key == "processing":
            return "处理预览"
        return name or "绘制曲线"

    def add(key, item, name=None):
        if (
            not key
            or key.startswith("custom:")
        ):
            return
        if item.xData is None or not len(item.xData):
            # A saved fit is a real target before the queued graph repaint.
            from tailor.fit_workflow import fit_owner
            owner=fit_owner(plot,key)
            if not owner or not any(r['id']==owner[1] and r.get('column_id') in owner[0].data_sheet.model.columnLabels() for r in owner[0].fit_records):return
        from tailor.text_accents import caption
        catalog[key] = (item, name_for(key, item, caption(name or "")))

    for sample, label in plot.presentation.legend_item.items:
        item = getattr(sample, "_source_item", sample.item)
        add(
            getattr(item, "_legend_key", None),
            item,
            getattr(label, "_original_text", label.text),
        )
    for item in plot.ui.plot_widget.getPlotItem().listDataItems():
        key = getattr(item, "_legend_key", None)
        if key not in catalog:
            add(key, item)
    if plot.presentation.multi:
        for series in getattr(plot,'_series',{}).values():
            item=series.get('fit')
            if item is not None:
                key=getattr(item,'_legend_key',None)
                if key not in catalog:add(key,item)
    for key, (item, name) in getattr(
        plot.presentation, "_hidden_legend_rows", {}
    ).items():
        if key not in catalog:
            add(key, item, name)
    from tailor.choice_catalog import curve_rank,curve_visible
    return dict(sorted(((key,value) for key,value in catalog.items()
                        if include_hidden or curve_visible(plot,key,value[0])),
                       key=lambda pair:curve_rank(plot,pair[0])))


def apply_legend_samples(plot):
    import pyqtgraph as pg

    from tailor.line_styles import curve_pen

    cfg = plot.presentation.legend
    catalog = available_curves(plot)
    for sample, label in plot.presentation.legend_item.items:
        key = getattr(sample.item, "_legend_key", None)
        if not key:
            continue
        if not hasattr(sample, "_source_item"):
            sample._source_item = sample.item
        source_key = cfg.get("matches", {}).get(key, key)
        source = catalog.get(source_key, (None, None))[0]
        spec = cfg.get("samples", {}).get(key)
        if spec:
            color = QtGui.QColor(spec["color"])
            color.setAlphaF(spec.get("opacity", 1))
            opts = {
                "pen": None
                if spec["mode"] == "scatter"
                else curve_pen(color, spec["line_width"], spec["line_style"]),
                "symbol": spec["marker"]
                if spec["mode"] in {"scatter", "line_scatter"}
                else None,
                "symbolSize": spec["marker_size"],
                "symbolPen": color,
                "symbolBrush": color if spec.get("marker_fill", True) else None,
            }
        elif source is not None:
            opts = getattr(source,'_curve_legend_options',None) or {
                k: source.opts.get(k)
                for k in ("pen", "symbol", "symbolSize", "symbolPen", "symbolBrush")
            }
        else:
            opts = {"pen": pg.mkPen("#9ca3af", width=1.5), "symbol": None}
        # ItemSample reads PlotDataItem.scatter.opts for native marker paint.
        # Empty PlotDataItem proxies never propagate their symbol options there.
        proxy = pg.PlotDataItem([0], [0], **opts)
        proxy._legend_key = key
        sample.item = proxy
        sample.update()


class LegendSampleIcon(QtGui.QIconEngine):
    def __init__(self, plot, key):
        super().__init__()
        import weakref

        self.plot, self.key = weakref.ref(plot), key

    def isNull(self):
        return False

    def clone(self):
        return LegendSampleIcon(self.plot(), self.key)

    def availableSizes(self, mode=QtGui.QIcon.Normal, state=QtGui.QIcon.Off):
        # Cocoa requires an advertised raster size when bridging QIcon to NSImage.
        return [QtCore.QSize(34, 16), QtCore.QSize(68, 32)]

    def paint(self, painter, rect, mode, state):
        import pyqtgraph as pg

        plot = self.plot()
        if plot is None or getattr(plot, "_graph_disposed", False):
            return
        sample = next(
            (
                s
                for s, _ in plot.presentation.legend_item.items
                if getattr(s.item, "_legend_key", None) == self.key
            ),
            None,
        )
        item = (
            sample.item
            if sample is not None
            else available_curves(plot).get(self.key, (None, None))[0]
        )
        opts = item.opts if item is not None else {"pen": pg.mkPen("#9ca3af", width=2)}
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.translate(rect.x(), rect.y())
        painter.scale(rect.width() / 64, rect.height() / 30)
        from tailor.appearance import manager

        def readable(color):
            if manager().dark() and color.valueF() < .3:
                return QtGui.QColor("#dce3ed")
            if not manager().dark() and color.lightnessF() > .85:
                return QtGui.QColor("#303b49")
            return color

        pen = opts.get("pen")
        if pen is not None:
            pen = pg.mkPen(pen)
            pen.setWidthF(max(2, min(4, pen.widthF())))
            pen.setColor(readable(pen.color()))
            painter.setPen(pen)
            painter.drawLine(3, 15, 61, 15)
        symbol = opts.get("symbol")
        if symbol:
            from pyqtgraph.graphicsItems.ScatterPlotItem import Symbols

            symbol = symbol if isinstance(symbol, str) else "o"
            symbol_pen = pg.mkPen(opts.get("symbolPen") or "#202020")
            symbol_pen.setColor(readable(symbol_pen.color()))
            brush = pg.mkBrush(opts.get("symbolBrush"))
            if brush.style() != QtCore.Qt.NoBrush:
                brush.setColor(readable(brush.color()))
            painter.setPen(symbol_pen)
            painter.setBrush(brush)
            painter.translate(32, 15)
            size = float(opts.get("symbolSize", 5))
            painter.scale(size, size)
            painter.drawPath(Symbols.get(symbol, Symbols["o"]))
        painter.restore()

    def pixmap(self, size, mode, state):
        pix = QtGui.QPixmap(size)
        pix.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pix)
        self.paint(painter, QtCore.QRect(QtCore.QPoint(), size), mode, state)
        painter.end()
        return pix


def legend_sample_icon(plot, key):
    engine = LegendSampleIcon(plot, key)
    icon = QtGui.QIcon()
    for scale in (1, 2):
        size = QtCore.QSize(34 * scale, 16 * scale)
        pix = engine.pixmap(size, QtGui.QIcon.Normal, QtGui.QIcon.Off)
        pix.setDevicePixelRatio(scale)
        icon.addPixmap(pix)
    return icon


def editor_button(plot, editor, title):
    parent = editor.parentWidget()
    layout = parent.layout() if parent else None
    if layout:
        layout.removeWidget(editor)
    editor.setParent(plot.preferences.parking)
    editor.hide()
    button = preference_button("font")
    button.clicked.connect(
        lambda: plot.preferences.open_font(
            editor, title() if callable(title) else title
        )
    )
    if isinstance(layout, QtWidgets.QFormLayout):
        layout.addRow(button)
    elif layout:
        layout.addWidget(button)
    return button


def setup_preferences(plot, graph, annotation, deferred=False):
    stages = _preference_sections(plot, graph, annotation)
    if deferred:
        return stages
    for _ in stages:
        pass


def _preference_sections(plot, graph, annotation):
    tabs = plot.property_tabs
    host = getattr(plot, "_preference_container", None)
    splitter = (host or tabs).parentWidget()
    slot = splitter.indexOf(host or tabs) if isinstance(splitter, QtWidgets.QSplitter) else -1
    if host is None:
        host = PreferenceHost(plot, None)
        host.graph = graph
        yield from host.setup_pages(deferred=True)
    else:
        host.graph = graph
        yield from host.setup_pages(deferred=True)
    plot.preferences = host
    host.parking = QtWidgets.QWidget(plot)
    host.parking.setObjectName("hiddenLegacyControls")
    host.parking.hide()
    if isinstance(splitter, QtWidgets.QSplitter) and splitter.indexOf(host) < 0:
        splitter.insertWidget(slot, host)
    elif not isinstance(splitter, QtWidgets.QSplitter):
        raise TypeError("属性面板容器无效")
    host.setMinimumWidth(max(380, tabs.minimumWidth()))
    from tailor.inspector_width import bind_width

    bind_width(splitter, host, "plot")
    yield
    graph.plot = plot
    for section in list(graph.sections):
        if section[1].property("sectionTitle") == "曲线":
            graph.open_layout.removeWidget(section[0])
            section[0].setParent(host.parking)
            section[0].hide()
            graph.sections.remove(section)
    for section in list(annotation.sections):
        annotation.open_layout.removeWidget(section[0])
        graph.open_layout.insertWidget(graph.open_layout.count() - 1, section[0])
        graph.sections.append(section)
    annotation.setParent(host.parking)
    annotation.hide()
    plot.annotations.graph_page = graph
    from tailor.plot_extras import PlotExtras

    plot.extras = PlotExtras(plot, graph)
    from tailor.exclusions import ExcludedPoints

    plot.excluded_points = ExcludedPoints(plot)
    yield
    layout = QtWidgets.QVBoxLayout()
    host.targets = QtWidgets.QComboBox()
    curve = preference_button("curve")
    host.curve_button = curve
    def open_group_curve():
        target=host.targets.currentData() or ('none',None)
        host.open_group_curve(*target)
    curve.clicked.connect(open_group_curve)
    layout.addWidget(row("对象", host.targets))
    from tailor.element_button_group import ElementButtons
    host.curve_actions = ElementButtons(plot, "curves")
    layout.addWidget(equal_row(host.curve_actions, curve))
    card = graph.add_section("曲线", layout, True)
    section = graph.sections.pop()
    graph.sections.insert(0, section)
    graph.open_layout.removeWidget(card)
    graph.open_layout.insertWidget(0, card)

    def selected(i):
        plot.annotations.select(None)
        plot.text_selection.select(None)
        if hasattr(plot, "extras"):
            plot.extras.collection.select(None)
        host.select_curve(*host.targets.itemData(i))

    host.targets.activated.connect(selected)
    # Existing axis and legend editors are parked until opened in the shared page.
    for editor in (plot.axis_controls.text_editor, plot.legend_controls.editor):
        editor.setParent(host.parking)
        editor.hide()
    plot.annotation_font_editor = ObjectTextEditor(host.parking)
    plot.annotation_font_editor.hide()
    yield

    @view_transaction("标注文字")
    def annotation_text_changed(control):
        record = plot.annotations.current()
        if not record or record["kind"] != "text":
            return
        editor = plot.annotation_font_editor
        spec = editor.spec()
        plot.curve_style = replace(
            plot.curve_style,
            text_styles={
                **plot.curve_style.text_styles,
                "annotation:" + record["id"]: spec,
            },
        )
        plot.annotations.replace(
            {
                **record,
                "text": editor.content.text(),
                "family": spec["family"],
                "size": spec["size"],
                "bold": spec["bold"],
                "color": spec["color"],
                "fill": spec.get("text_fill", ""),
                "fill_opacity": spec.get("text_fill_opacity", .18),
            }
        )
        # Orientation/italic-only edits may leave record fields unchanged.
        plot.annotations.redraw()
        plot.annotations.changed.emit()

    plot.annotation_font_editor.changed.connect(lambda: annotation_text_changed(host))
    font, stroke = preference_button("font"), preference_button("curve")
    annotation.add_controls.insertWidget(1, row(font, stroke))
    annotation.font_button, annotation.stroke_button = font, stroke
    def open_annotation_font():
        record=plot.annotations.current()
        if record and record['kind']=='text':
            plot.annotations.select(record['id'])
            annotation_selected()
            host.open_font(plot.annotation_font_editor,'标注文字')
    def open_annotation_curve():
        record=plot.annotations.current()
        if record and record['kind']!='text':
            plot.annotations.select(record['id'])
            host.select_curve('annotation',record['id'],True)
    font.clicked.connect(open_annotation_font)
    stroke.clicked.connect(open_annotation_curve)

    def annotation_selected():
        record = plot.annotations.current()
        font.setEnabled(bool(record and record["kind"] == "text"))
        stroke.setEnabled(bool(record and record["kind"] != "text"))
        if not record:
            if host.editor is plot.annotation_font_editor:
                plot.annotation_font_editor.setEnabled(False)
            if host.curve_target[0] == "annotation":
                host.curve_editor.setEnabled(False)
            return
        if record["kind"] == "text":
            from tailor.text_style_controls import font_spec

            spec = {
                **font_spec(plot.curve_style, "annotation:" + record["id"]),
                "family": record["family"],
                "size": record["size"],
                "bold": record["bold"],
                "color": record["color"],
            }
            plot.annotation_font_editor.load(spec, record["text"])
            host.select_font(plot.annotation_font_editor, "标注文字")
        else:
            host.select_curve("annotation", record["id"])

    plot.annotations.changed.connect(annotation_selected)
    annotation_selected()
    plot.text_selection.changed.connect(annotation.position_controls.sync)
    plot.legend_controls.refresh_entries()
    host.refresh_targets()
    from tailor.text_drag import TextDrag

    plot.text_drag = TextDrag(plot)
    from tailor.appearance import manager

    manager().register(plot)
    if hasattr(plot, "preset_controls") and getattr(plot, '_inset_parent', None) is None:
        from tailor.trend_controls import TrendControls

        trend = TrendControls(plot)
        fit = next(
            (tabs.widget(i) for i in range(tabs.count()) if tabs.tabText(i) == "拟合"),
            None,
        )
        if fit:
            fit.add_section("趋势线", trend)

    # Late adapters add controls after their cards were initially compacted.
    # Normalize heights once without resetting any layout/margins or icon groups.
    from tailor.fold_panel import normalize_control_heights
    normalize_control_heights(host)
    from tailor.label_alignment import align_labels, protected
    for page in (graph, plot.axis_controls, annotation):
        for record in page.sections:
            if not protected(record[3]):
                align_labels(record[3])
    for i in range(tabs.count()):
        page = tabs.widget(i)
        if hasattr(page, 'sections'):
            for record in page.sections:
                if not protected(record[3]):
                    align_labels(record[3])
    positions={record[1].property('sectionTitle'):record for record in graph.sections}
    if '位置与坐标' in positions and '局部放大' in positions:
        first,second=positions['位置与坐标'],positions['局部放大']
        a,b=graph.sections.index(first),graph.sections.index(second)
        ia,ib=graph.open_layout.indexOf(first[0]),graph.open_layout.indexOf(second[0])
        graph.sections[a],graph.sections[b]=second,first
        graph.open_layout.removeWidget(first[0]);graph.open_layout.removeWidget(second[0])
        for index,widget in sorted(((ia,second[0]),(ib,first[0]))):graph.open_layout.insertWidget(index,widget)


def rendered_curve_style(item):
    """Read this curve's effective appearance, never a different target's style."""
    import pyqtgraph as pg
    if item is None:return CurveStyle()
    opts=item.opts
    has_line=opts.get('pen') is not None and pg.mkPen(opts['pen']).style()!=QtCore.Qt.NoPen
    pen=pg.mkPen(opts.get('pen') if has_line else opts.get('symbolPen'))
    symbol=opts.get('symbol')
    marker=symbol if isinstance(symbol,str) and symbol in {'o','s','t','d','+','x','star'} else 'o'
    pattern={QtCore.Qt.SolidLine:'solid',QtCore.Qt.DashLine:'dash',QtCore.Qt.DotLine:'dot',QtCore.Qt.DashDotLine:'dashdot',QtCore.Qt.DashDotDotLine:'dashdotdot'}.get(pen.style(),'solid')
    if pen.style()==QtCore.Qt.CustomDashLine:pattern='longdash' if list(pen.dashPattern())==[8,3] else 'shortdash'
    return CurveStyle(mode='line_scatter' if symbol is not None and has_line else 'scatter' if symbol is not None else 'line',
                      color=pen.color().name(),line_width=max(.1,pen.widthF()),line_style=pattern,
                      marker=marker,marker_size=float(opts.get('symbolSize',5)),opacity=item.opacity(),
                      marker_fill=pg.mkBrush(opts.get('symbolBrush')).style()!=QtCore.Qt.NoBrush,
                      cap={QtCore.Qt.FlatCap:'flat',QtCore.Qt.SquareCap:'square',QtCore.Qt.RoundCap:'round'}.get(pen.capStyle(),'round'),
                      join={QtCore.Qt.MiterJoin:'miter',QtCore.Qt.BevelJoin:'bevel',QtCore.Qt.RoundJoin:'round'}.get(pen.joinStyle(),'round'),
                      fill=opts.get('fillLevel') is not None,
                      fill_color=pg.mkBrush(opts.get('fillBrush')).color().name(),
                      step_mode=bool(opts.get('stepMode')))


def drawn_item(plot, key):
    for sample, label in plot.presentation.legend_item.items:
        item = getattr(sample, "_source_item", sample.item)
        if getattr(item, "_legend_key", None) == key:
            return item
    return available_curves(plot).get(key, (None, None))[0]


def apply_drawn_styles(plot):
    from tailor.line_styles import apply_curve_extras, curve_pen

    # Curves remain editable when their legend entry alone is hidden/deleted.
    for key, (item, _caption) in available_curves(plot).items():
        spec = plot.presentation.curve_overrides.get(key)
        if spec:
            style = CurveStyle(**spec)
            item.setPen(
                None
                if style.mode == "scatter"
                else curve_pen(style.color, style.line_width, style.line_style)
            )
            item.setSymbol(style.marker if style.mode in {"scatter", "line_scatter"} else None)
            item.setSymbolSize(style.marker_size)
            apply_curve_extras(item, style)
        if (
            hasattr(plot, "preferences")
            and key != "data"
            and not key.endswith(":data")
            and not getattr(item, "_pref_bound", False)
        ):
            item._pref_bound = True
            item.setCurveClickable(True, width=10)

            def select(*args, key=key, item=item):
                from tailor.manual_peaks import picking
                if picking(plot):
                    return
                from tailor.fit_workflow import pick
                event=next((a for a in args if hasattr(a,'scenePos') and hasattr(a,'button')),None)
                if event is not None and getattr(plot.curve_selection,'_handled_click',None) is event:return
                plot.curve_selection._handled_click=event
                from tailor.point_inspector import intercept_curve
                if intercept_curve(plot, key, event):return
                if pick(plot,key,item,event):return
                plot._selected_drawn_key = key
                plot.preferences.select_curve(
                    "drawn",
                    key,
                    any(getattr(a, "double", lambda: False)() for a in args),
                )
                plot.curve_selection.current = None
                plot.curve_selection.override_item = item
                plot.curve_selection.refresh()

            item.sigClicked.connect(select)
            item.curve.sigClicked.connect(select)

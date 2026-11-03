"""Per-object font controls using the existing pyqtgraph scene and curve style."""

import html
import weakref

import shiboken6
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from tailor.appearance import ink
from tailor.spreadsheet_model import Edit

TARGETS = (
    ("横轴刻度", "x_ticks"),
    ("横轴名称", "x_label"),
    ("纵轴刻度", "y_ticks"),
    ("纵轴名称", "y_label"),
    ("图例", "legend"),
)


class TextSelectionFrame(QtCore.QObject):
    """Selection decoration lives in the scene, never in export/project data."""
    changed=QtCore.Signal(object)

    def __init__(self, plot):
        super().__init__(plot)
        self.plot = plot
        self.key = None
        self.rect = QtWidgets.QGraphicsRectItem()
        self.rect.setPen(QtGui.QPen(QtGui.QColor("#1976d2"), 1.5, QtCore.Qt.DashLine))
        self.rect.setBrush(QtGui.QColor(25, 118, 210, 18))
        self.rect.setAcceptedMouseButtons(QtCore.Qt.NoButton)
        self.rect.setZValue(10000)
        plot.ui.plot_widget.scene().addItem(self.rect)
        self.rect.hide()
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(120)
        self.timer.timeout.connect(self.refresh)

    def select(self, key):
        old=self.key
        self.key = key
        if key is None:
            self.timer.stop()
            self.rect.hide()
        else:
            self.refresh()
            self.timer.start()
        if old!=key:self.changed.emit(key)

    def refresh(self):
        if getattr(self.plot, "_graph_disposed", False):
            self.timer.stop()
            return
        if self.key is None or not getattr(self.plot,"_embedded_parent",self.plot).isVisible():
            self.rect.hide()
            return
        bounds = None
        if self.key == "legend":
            target = self.plot.presentation.legend_item
            bounds = target.sceneBoundingRect() if target.isVisible() else None
        elif self.key.startswith(("legend-text:", "legend-sample:")):
            kind, key = self.key.split(":", 1)
            pair = next(
                (
                    (sample, label)
                    for sample, label in self.plot.presentation.legend_item.items
                    if getattr(sample.item, "_legend_key", None) == key
                ),
                None,
            )
            if pair:
                target = pair[1] if kind == "legend-text" else pair[0]
                bounds = target.sceneBoundingRect()
        else:
            is_line = self.key.startswith("axis:")
            prefix = self.key.split(":", 1)[1] if is_line else self.key.split("_", 1)[0]
            kind = "line" if is_line else self.key.split("_", 1)[1]
            axis = self.plot.ui.plot_widget.getAxis(
                {"x": "bottom", "y": "left", "top": "top", "right": "right"}[prefix]
            )
            if axis.isVisible():
                if kind == "label":
                    bounds = axis.label.sceneBoundingRect()
                elif kind == "factor":
                    factor = getattr(axis, "factor_item", None)
                    bounds = factor.sceneBoundingRect() if factor is not None and factor.isVisible() else None
                elif kind == "line":
                    bounds = axis.mapToScene(
                        getattr(axis, "_curve_axis_line", axis.boundingRect())
                    ).boundingRect()
                else:
                    rect = QtCore.QRectF()
                    for value in getattr(axis, "_curve_tick_text_rects", []):
                        rect = rect.united(value)
                    bounds = (
                        axis.mapToScene(rect).boundingRect()
                        if not rect.isEmpty()
                        else None
                    )
        if bounds is None:
            self.rect.hide()
            return
        bounds = bounds.adjusted(-3, -3, 3, 3).intersected(
            self.plot.ui.plot_widget.scene().sceneRect().adjusted(1, 1, -1, -1)
        )
        self.rect.setRect(bounds)
        self.rect.show()


def font_spec(style, key):
    return {
        "size": style.font_size,
        "family": style.font_family,
        "italic": False,
        "bold": False,
        "color": "#202020",
        **(style.text_styles.get('annotation:default', {}) if key.startswith('annotation:') else {}),
        **style.text_styles.get(key, {}),
    }


def record_view_edit(plot, label, before, after, setter):
    if getattr(plot, "_view_edit_active", False) or before == after:
        return
    from tailor.panel_scope import wrap_edit
    setter = wrap_edit(plot, label, before, after, setter)
    ref = weakref.ref(plot)

    def apply(value):
        target = ref()
        if target is not None and shiboken6.isValid(target):
            setter(target, value)
            target.main_window.mark_project_dirty()

    sheet = getattr(plot, "data_sheet", None)
    if sheet is None:
        sources = list(plot.model._plots)
        sheet = sources[0].data_sheet if sources else None
    if sheet is None:
        return
    sheet.model._record(Edit(label, lambda: apply(before), lambda: apply(after), 4096))


def legend_rows(plot):
    legend = plot.ui.plot_widget.getPlotItem().legend
    if legend is None:
        return []
    rows = []
    for index, (sample, label) in enumerate(legend.items):
        item = sample.item
        key = getattr(item, "_legend_key", f"entry:{index}")
        if not hasattr(label, "_original_text"):
            label._original_text = label.text
        rows.append((key, label._original_text, label))
    return rows



def native_font(spec):
    family=spec.get("family","sans-serif")
    if family=="sans-serif":
        font=QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.GeneralFont)
    elif family=="monospace":
        font=QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
    else:
        font=QtGui.QFont(family)
    font.setPointSizeF(spec.get("size",14))
    font.setWeight(QtGui.QFont.Bold if spec.get("bold") else QtGui.QFont.Normal)
    font.setItalic(spec.get("italic",False))
    font.setUnderline(spec.get("underline",False))
    if hasattr(QtGui.QFont,"ContextFontMerging"):
        font.setStyleStrategy(QtGui.QFont.ContextFontMerging)
    return font


def apply_text_styles(plot):
    from tailor.text_accents import install_vector_objects
    style, p = plot.curve_style, plot.presentation
    for prefix, side in (
        ("x", "bottom"),
        ("y", "left"),
        ("right", "right"),
        ("top", "top"),
    ):
        tick, title = (
            font_spec(style, prefix + "_ticks"),
            font_spec(style, prefix + "_label"),
        )
        font = native_font(tick)
        axis = plot.ui.plot_widget.getAxis(side)
        if axis.style.get('tickFont')!=font:axis.setStyle(tickFont=font)
        text_pen=pg.mkPen(ink(tick['color']))
        if axis.textPen()!=text_pen:axis.setTextPen(text_pen)
        if axis.autoSIPrefix:axis.enableAutoSIPrefix(False)
        label = getattr(
            p if prefix in {"top", "right"} else plot.model, prefix + "_label"
        )
        # Preserve the rich-text engine, but do not repeatedly reparse an
        # unchanged document during data/range/style synchronization.
        signature=(label,dict(title),p.axes[prefix]['title_visible'],ink(title['color']))
        cached=getattr(axis.label,'_curve_styled_text',None)
        if cached and cached[0]==signature and cached[1]==axis.label.toHtml():continue
        axis.label.document().setDefaultFont(native_font(title))
        axis.setLabel(
            styled_html(label, title) if p.axes[prefix]["title_visible"] else "",
            units="",
            **{
                "font-size": f"{title['size']}pt",
                "font-family": title["family"],
                "font-style": "italic" if title["italic"] else "normal",
                "font-weight": "bold" if title["bold"] else "normal",
                "color": ink(title["color"]),
            },
        )
        from tailor.cjk_text import apply_weight
        apply_weight(axis.label.document(),title)
        if install_vector_objects(axis.label.document()):
            axis.label.document().adjustSize()
            axis.resizeEvent()
        axis.label._curve_styled_text=(signature,axis.label.toHtml())
    from tailor.legend_entries import reconcile

    reconcile(plot)
    base = font_spec(style, "legend")
    entries = p.legend.get("entries", {})
    for key, original, label in legend_rows(plot):
        entry = entries.get(key, {})
        spec = {**base, **entry.get("style", {}), 'spacing': 1.0}
        signature=(entry.get('text',original),dict(spec),ink(spec['color']))
        cached=getattr(label,'_curve_styled_text',None)
        if cached and cached[0]==signature and cached[1]==label.item.toHtml():continue
        label.item.document().setDefaultFont(native_font(spec))
        label.setText(
            styled_html(entry.get("text", original), spec),
            size=f"{spec['size']}pt",
            family=spec["family"],
            color=ink(spec["color"]),
            italic=spec["italic"],
            bold=spec["bold"],
        )

        from tailor.cjk_text import apply_weight
        apply_weight(label.item.document(),spec)
        if install_vector_objects(label.item.document()):
            label.item.document().adjustSize()
            label.updateMin()
            label.resizeEvent(None)
        label._curve_styled_text=(signature,label.item.toHtml())

    from tailor.preference_pages import apply_legend_samples

    apply_legend_samples(plot)
    # Components are recreated by plot_best_fit; bind their native hit areas
    # whenever legend/text styling reconciles the newly drawn series.
    from tailor.preference_pages import apply_drawn_styles
    apply_drawn_styles(plot)
    from tailor.processing_controls import refresh_frequency_axes

    refresh_frequency_axes(plot)
    if getattr(plot, 'advanced_view', None) is not None:
        plot.advanced_view.schedule()


def styled_html(text, spec):
    from tailor.text_accents import restyle
    text = restyle(text, {**spec, "color": ink(spec.get("color", "#202020"))})
    align = spec.get("align", "left")
    background = spec.get("background", "")
    decorations = "text-decoration:underline;" if spec.get("underline") else ""
    weight = "bold" if spec.get("bold") else "normal"
    italic = "italic" if spec.get("italic") else "normal"
    family = html.escape(spec.get("family", "sans-serif"), quote=True)
    color = ink(spec.get("color", "#202020"))
    return f'<div style="font-family:{family};font-size:{spec.get("size", 12)}pt;font-weight:{weight};font-style:{italic};color:{color};text-align:{align};line-height:{spec.get("spacing", 1.0) * 100}%;background-color:{background or "transparent"};{decorations}">{text}</div>'


def sync_font_controls(plot):
    # Old generated controls stay hidden for loading older project files.
    if hasattr(plot, "style_font") and hasattr(plot, "style_family"):
        blockers = [QtCore.QSignalBlocker(plot.style_font), QtCore.QSignalBlocker(plot.style_family)]
        plot.style_font.setValue(plot.curve_style.font_size)
        plot.style_family.setEditText(plot.curve_style.font_family)
        del blockers
    for name in ("legend_controls", "axis_controls"):
        control = getattr(plot, name, None)
        if control is not None and not getattr(control, "loading", False):
            control.sync_text()


def reveal_section(plot, page, title):
    # Scene selections follow the active editor without moving its return page.
    preferences = getattr(plot, 'preferences', None)
    if preferences is not None and preferences.preference_mode() is not None:
        return
    plot.property_tabs.setCurrentWidget(page)
    if hasattr(page, 'select_category') and title != '对象':
        page.select_category(title)
    for section in page.sections:
        if section[1].property("sectionTitle") == title:
            page.set_open(section, True)
            page.scroll.ensureWidgetVisible(section[0])
            break


def connect_font_controls(plot):
    # Reuse the scene picking path, with editors owned by their functional page.
    hidden = QtWidgets.QWidget(plot)
    hidden.setLayout(plot.font_form)
    hidden.hide()
    plot._legacy_font_controls = hidden
    # Keep the compatibility editor coherent when older integrations still use
    # it. Empty input must never replace a valid stored family.
    plot.style_family.lineEdit().editingFinished.connect(
        lambda: sync_font_controls(plot) if not plot.style_family.currentText().strip() else None
    )
    plot.text_selection = TextSelectionFrame(plot)

    def select(event):
        from tailor.point_inspector import point_active
        if point_active(plot):return
        if getattr(getattr(plot, 'curve_selection', None), '_handled_click', None) is event:
            return
        from tailor.manual_peaks import picking
        if picking(plot):
            return
        from tailor.graph_focus import is_inset_event
        if is_inset_event(plot, event):
            return
        if hasattr(plot, "annotations") and plot.annotations.blocks_point(event):
            return
        if event.button() != QtCore.Qt.LeftButton or not hasattr(plot, "axis_controls"):
            return
        pos = event.scenePos()
        if getattr(plot,'_inset_parent',None) is not None:
            from tailor.graph_focus import inset_contains
            if not inset_contains(getattr(plot,'_inset_extras',None),pos):return
        legend = plot.presentation.legend_item

        def clear_other():
            parent = getattr(plot, "_inset_parent", None)
            from tailor.graph_focus import activate_inset, restore_main
            if parent is not None:
                activate_inset(parent, getattr(plot,"_inset_extras",None))
            else:
                restore_main(getattr(plot, "_embedded_parent", plot))
            if hasattr(plot, "curve_selection"):
                plot.curve_selection.clear()
            collection = getattr(getattr(plot, 'extras', None), 'collection', None)
            if collection is not None and collection.selected is not None:
                collection.select(None)
            if plot.annotations.selected:
                plot.annotations.selected = None
                plot.annotations.changed.emit()
                plot.annotations.redraw()

        if legend.isVisible() and legend.sceneBoundingRect().contains(pos):
            clear_other()
            reveal_section(plot, plot.preferences.graph, "图例")
            for sample, label in legend.items:
                key = getattr(sample.item, "_legend_key", None)
                if label.sceneBoundingRect().contains(pos):
                    plot.legend_controls.select_entry(key)
                    plot.text_selection.select("legend-text:" + key)
                    plot.preferences.select_font(
                        plot.legend_controls.editor,
                        plot.legend_controls.target.currentText(),
                    )
                    if event.double():
                        plot.preferences.open_font()
                    return
                if sample.sceneBoundingRect().contains(pos):
                    plot.legend_controls.select_entry(key)
                    plot.text_selection.select("legend-sample:" + key)
                    plot.preferences.select_curve("legend", key, event.double())
                    return
            plot.legend_controls.select_entry("__all__")
            plot.text_selection.select("legend")
            plot.preferences.select_curve("legend_all", None)
            return
        for prefix, side in (
            ("x", "bottom"),
            ("y", "left"),
            ("top", "top"),
            ("right", "right"),
        ):
            axis = plot.ui.plot_widget.getAxis(side)
            if not axis.isVisible():
                continue
            local = axis.mapFromScene(pos)
            factor = getattr(axis, "factor_item", None)
            if factor is not None and factor.isVisible() and factor.sceneBoundingRect().contains(pos):
                clear_other()
                controls = plot.axis_controls
                controls.select_axis(prefix, "ticks")
                cfg = plot.presentation.axes[prefix]
                controls.factor_editor.load(
                    cfg.get("factor_style") or font_spec(plot.curve_style, prefix + "_ticks"),
                    cfg.get("factor_text", ""),
                )
                plot.text_selection.select(prefix + "_factor")
                reveal_section(plot, controls, "高级刻度格式")
                plot.preferences.font_target = (controls.factor_editor, "轴端倍率")
                plot.preferences._font_allowed = True
                plot.preferences._curve_allowed = False
                plot.quick_actions.buttons["font"].setEnabled(True)
                plot.quick_actions.buttons["curve"].setEnabled(False)
                if event.double() or plot.preferences.preference_mode() is not None:
                    plot.preferences.open_font()
                return
            title = axis.label.isVisible() and axis.label.sceneBoundingRect().contains(
                pos
            )
            text = any(
                rect.contains(local)
                for rect in getattr(axis, "_curve_tick_text_rects", [])
            )
            line = getattr(axis, "_curve_axis_line", QtCore.QRectF()).contains(local)
            if title or text or line:
                clear_other()
                if text:
                    entry=next((e for e in getattr(axis,'_curve_tick_entries',[]) if e['rect'].contains(local)),None)
                    if entry is not None and entry['value'] is not None:
                        plot.axis_controls.selected_tick=(prefix,entry['value'],entry['text'])
                plot.axis_controls.select_axis(prefix, "label" if title else "ticks")
                if line and not title and not text:
                    plot.text_selection.select("axis:" + prefix)
                    reveal_section(plot, plot.axis_controls, "标题与轴线")
                    plot.preferences.select_curve("axis", prefix, event.double())
                else:
                    plot.text_selection.select(
                        prefix + ("_label" if title else "_ticks")
                    )
                    reveal_section(
                        plot,
                        plot.axis_controls,
                        "标题与轴线" if title else "高级刻度格式",
                    )
                    # Axis selection needs only its outline and functional page.
                    # Prepare/reparent the full font editor on explicit opening.
                    plot.preferences.font_target = (
                        plot.axis_controls.text_editor,
                        plot.axis_controls.current_label.text(),
                    )
                    plot.preferences._font_allowed=True
                    plot.quick_actions.buttons['font'].setEnabled(True)
                    if event.double() or plot.preferences.preference_mode() is not None:
                        plot.preferences.open_font(plot.axis_controls.text_editor,plot.axis_controls.current_label.text())
                return
        plot.text_selection.select(None)
        plot.preferences.font_target = None
        plot.preferences._font_allowed = False
        if plot.ui.plot_widget.getViewBox().sceneBoundingRect().contains(pos):
            plot.preferences.return_to_inspector()

    plot._select_presentation = select
    plot._presentation_scene=plot.ui.plot_widget.scene()
    plot._presentation_scene.sigMouseClicked.connect(select)


def export_font_families(family):
    """Keep the selected face, with installed CJK fallback for missing glyphs."""
    from matplotlib import font_manager

    available = {font.name for font in font_manager.fontManager.ttflist}
    for fallback in ("PingFang SC", "Heiti SC", "Noto Sans CJK SC", "Arial Unicode MS"):
        if fallback in available and fallback != family:
            return [family, fallback]
    return [family]

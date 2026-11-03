"""Compact additions to the existing four Tailor properties pages."""

from tailor.compact_controls import CheckButton

import copy
from dataclasses import replace

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from tailor.compact_controls import stepper, CompactDoubleSpinBox
from tailor.curve_style import CurveStyle
from tailor.ui_widgets import ColorButton, FontFamilyCombo
from tailor.view_history import view_transaction


def combo(items):
    widget = QtWidgets.QComboBox()
    for title, value in items:
        widget.addItem(title, value)
    return widget


def number(low, high, value, decimals=1, *, unit=""):
    widget = CompactDoubleSpinBox()
    widget.setRange(low, high)
    widget.setDecimals(decimals)
    widget.setValue(value)
    widget.setSingleStep(0.1 if low > 0 and low < 1 else 0.5)
    widget.setKeyboardTracking(False)
    widget.setProperty("sliderUnit",unit)
    return widget


def row(*widgets):
    result = QtWidgets.QWidget()
    # Reserve the common operating height before native style polishing;
    # nested advanced/template rows can otherwise retain a 27/28px hint.
    result.setMinimumHeight(30)
    layout = QtWidgets.QHBoxLayout(result)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    skipped=set()
    units={'%','px','pt','°','s','ms','Hz','kHz','个','点','次','条','阶','倍','行','列','份'}
    for index, widget in enumerate(widgets):
        if index in skipped:continue
        numeric=isinstance(widget,(QtWidgets.QSpinBox,QtWidgets.QDoubleSpinBox))
        numeric_container=None
        if numeric and index+1<len(widgets) and isinstance(widgets[index+1],str) and widgets[index+1] in units:
            from tailor.compact_controls import style_slider_value
            numeric_container=stepper(widget)
            style_slider_value(widget,numeric_container,widgets[index+1]);skipped.add(index+1)
        if isinstance(widget, str):
            label = QtWidgets.QLabel(widget)
            label.setProperty("fieldLabel", True)
            label.setFixedWidth(label.sizeHint().width())
            layout.addWidget(label)
        else:
            if isinstance(widget, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)) and hasattr(widget, "singleStep"):
                widget = numeric_container if numeric_container is not None else stepper(widget)
            if isinstance(widget, QtWidgets.QLabel):
                # Value labels change after construction; never freeze an empty
                # sizeHint at zero pixels (roles and shared numeric values).
                widget.setMinimumWidth(0)
                widget.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Preferred)
            layout.addWidget(
                widget,
                0 if isinstance(widget, (QtWidgets.QCheckBox, QtWidgets.QLabel)) else 1,
            )
    return result


def color_button(initial, changed):
    button = ColorButton(initial or "随曲线")

    def choose():
        value = QtWidgets.QColorDialog.getColor(
            QtGui.QColor(button.text() if button.text().startswith("#") else "#202020"),
            button,
            "选择颜色",
        )
        if value.isValid():
            button.setText(value.name())
            changed(value.name())

    button.clicked.connect(choose)
    return button


class LegendControls(QtWidgets.QWidget):
    def __init__(self, plot):
        super().__init__()
        self.plot, self.loading = plot, False
        from tailor.compact_controls import preference_button, toggle_button
        from tailor.object_text_editor import ObjectTextEditor

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        from tailor.legend_combo import LegendCombo
        self.target = LegendCombo()
        self.target.setIconSize(QtCore.QSize(34,16))
        self.editor = ObjectTextEditor(self)
        self.editor.setProperty('spacingAllowed', False)
        self.editor.spacing.setEnabled(False)
        self.editor.spacing.setToolTip('图例间距请在“图形－图例”的间距中调整。')
        self.editor.hide()
        self.font_button = preference_button("font")
        self.font_button.clicked.connect(
            lambda: self.open_font()
        )
        from tailor.plot_types import icon

        self.delete = QtWidgets.QToolButton()
        self.delete.setIcon(icon("trash-2", self.delete, "#d34b48"))
        self.delete.setFixedSize(30, 30)
        self.delete.setIconSize(QtCore.QSize(18, 18))
        self.delete.setStyleSheet("QToolButton { padding:0; }")
        self.delete.setToolTip("删除此行图例，保留曲线和数据")
        self.delete.clicked.connect(self.delete_entry)
        self.add_button = QtWidgets.QToolButton()
        self.add_button.setIcon(icon("plus", self.add_button))
        self.add_button.setFixedSize(30, 30)
        self.add_button.setIconSize(QtCore.QSize(18, 18))
        self.add_button.setStyleSheet("QToolButton { padding:0; }")
        self.add_button.setToolTip("新增图例行")
        self.add_button.clicked.connect(self.add_entry)
        self.match_button = QtWidgets.QToolButton()
        self.match_button.setText("匹配")
        self.match_button.setIcon(icon("link", self.match_button))
        self.match_button.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.match_button.setToolTip("关联当前图例样本与已有曲线")
        self.match_menu = QtWidgets.QMenu(self.match_button)
        self.match_button.setMenu(self.match_menu)
        self.match_button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.match_button.setStyleSheet(
            "QToolButton {padding:3px 22px 3px 5px;} QToolButton::menu-indicator {width:12px;right:5px;}"
        )
        self.match_menu.aboutToShow.connect(self.fill_matches)
        from tailor.compact_controls import equal_row

        self.match_button.setMinimumWidth(0)
        self.match_button.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
        )

        self.position = combo([
            ("右上", None), ("左上", [0.02, 0.02]),
            ("左下", [0.02, 0.75]), ("右下", [0.72, 0.75]),
        ])
        self.position.addItem('自定义','__custom__')
        from tailor.element_button_group import ElementButtons
        self.actions = ElementButtons(plot, "legend", add=self.add_entry)
        objects=row('对象',self.target);positions=row('位置',self.position)
        header=QtWidgets.QWidget();header_layout=QtWidgets.QHBoxLayout(header)
        header_layout.setContentsMargins(0,0,0,0);header_layout.setSpacing(8)
        header_layout.addWidget(objects,3);header_layout.addWidget(positions,2)
        objects.setMinimumWidth(0);positions.setMinimumWidth(0)
        layout.addWidget(header)
        layout.addWidget(equal_row(self.actions, self.match_button))
        self.sample_button = preference_button("curve")
        self.sample_button.clicked.connect(
            self.open_sample
        )
        layout.addWidget(row(self.font_button, self.sample_button))
        self.columns = QtWidgets.QSpinBox(self)
        self.columns.setRange(1, 20)
        self.columns.hide()
        self.spacing = number(0, 30, 2,unit="px")
        self.border = toggle_button("边框")
        self.background = toggle_button("底色")
        self.visible = toggle_button("显示图例")
        self.visible.hide()
        self.hide_button = QtWidgets.QPushButton("隐藏图例")
        self.hide_button.clicked.connect(
            lambda: self.visible.setChecked(not self.visible.isChecked())
        )
        border_pref = preference_button("curve")
        border_pref.setText("")
        border_pref.setFixedWidth(34)
        border_pref.setToolTip("边框线条偏好")
        border_pref.clicked.connect(
            lambda: plot.preferences.open_group_curve("legend_border", None)
        )
        bg_pref = preference_button("curve")
        bg_pref.setText("")
        bg_pref.setFixedWidth(34)
        bg_pref.setToolTip("底色颜色与不透明度")
        bg_pref.clicked.connect(
            lambda: plot.preferences.open_group_curve("legend_background", None)
        )
        layout.addWidget(row(self.border, border_pref, self.background, bg_pref))
        layout.addWidget(row("间距", self.spacing))
        self.sync()
        self.spacing.valueChanged.connect(self.apply)
        for box in (self.visible, self.border, self.background):
            box.toggled.connect(self.apply)
        self.position.activated.connect(self.position_changed)
        self.target.activated.connect(self.choose_target)
        self.editor.changed.connect(self.apply_text)
        from tailor.appearance import manager
        manager().changed.connect(self.refresh_entries)

    def add_entry(self):
        from tailor.legend_entries import add

        before = self.state()
        self.plot.presentation.legend.pop('deleted', None)
        self.plot.presentation.legend['visible'] = True
        key = add(self.plot)
        self.finish_edit(before, "新增图例行")
        self.select_entry(key)

    def fill_matches(self):
        from tailor.plot_types import icon
        from tailor.preference_pages import available_curves

        self.match_menu.clear()
        self.match_menu.addAction(
            icon("unlink", self), "不匹配", lambda: self.match(None)
        )
        self.match_menu.addSeparator()
        for key, (item, name) in available_curves(self.plot,include_hidden=False).items():
            self.match_menu.addAction(
                name, lambda checked=False, key=key: self.match(key)
            )

    def match(self, curve_key):
        key = self.target.currentData()
        if key in {None, "__all__"}:
            return
        before = self.state()
        cfg = self.plot.presentation.legend
        cfg.setdefault("matches", {})[key] = curve_key
        cfg.setdefault("samples", {}).pop(key, None)
        if curve_key is not None and key.startswith('custom:'):
            cfg.get('entries', {}).get(key, {}).pop('text', None)
        self.finish_edit(before, "匹配图例曲线")

    def sync(self):
        cfg = self.plot.presentation.legend
        self.loading = True
        try:
            self.columns.setValue(cfg["columns"])
            self.spacing.setValue(cfg.get("spacing", 2))
            for key in ("visible", "border", "background"):
                getattr(self, key).setChecked(cfg[key])
            from tailor.ui_widgets import data_index
            position_index=data_index(self.position,cfg['position'])
            self.position.setCurrentIndex(position_index if position_index>=0 else self.position.findData('__custom__'))
            self.hide_button.setText("隐藏图例" if cfg["visible"] else "显示图例")
            self.refresh_entries()
        finally:
            self.loading = False
        self.sync_text()

    def refresh_entries(self):
        if getattr(self.plot,"_graph_disposed",False):
            return
        from tailor.legend_entries import reconcile
        from tailor.text_accents import caption
        from tailor.text_style_controls import legend_rows

        reconcile(self.plot)
        old = self.target.currentData()
        with QtCore.QSignalBlocker(self.target):
            self.target.clear()
            self.target.addItem('全部','__all__')
            from tailor.choice_catalog import curve_rank
            rows=legend_rows(self.plot) if self.plot.presentation.legend.get('visible',True) else []
            for key, original, _ in sorted(rows,key=lambda r:curve_rank(self.plot,r[0])):
                name = caption(
                    self.plot.presentation.legend.get("entries", {})
                    .get(key, {})
                    .get("text", original)
                )
                self.target.addItem(name.replace("\n", " / "), key)
                from tailor.preference_pages import legend_sample_icon

                self.target.setItemIcon(
                    self.target.count() - 1, legend_sample_icon(self.plot, key)
                )
            self.target.setCurrentIndex(max(0, self.target.findData(old)))
        selected = self.target.currentData() not in {None, "__all__", "__add__"}
        self.delete.setEnabled(selected)
        self.sample_button.setEnabled(self.target.count() > 1)
        self.match_button.setEnabled(selected)

    def choose_target(self, *args):
        self.plot.annotations.select(None)
        self.plot.curve_selection.clear()
        collection = getattr(getattr(self.plot, 'extras', None), 'collection', None)
        if collection is not None and collection.selected is not None:
            collection.select(None)
        key = self.target.currentData()
        self.plot.text_selection.select("legend" if key == "__all__" else "legend-text:" + str(key))
        self.actions.sync()
        if self.target.currentData() == "__add__":
            from tailor.legend_entries import add

            before = self.state()
            key = add(self.plot)
            self.finish_edit(before, "新增图例行")
            self.select_entry(key)
        else:
            self.sync_text()
        if hasattr(self.plot, "preferences"):
            self.plot.preferences.select_font(self.editor, self.target.currentText())
            self.plot.preferences.select_curve(
                "legend_all" if self.target.currentData() == "__all__" else "legend",
                None
                if self.target.currentData() == "__all__"
                else self.target.currentData(),
            )

    def open_sample(self):
        self.choose_target()
        self.plot.preferences.select_curve(
            'legend_all' if self.target.currentData()=='__all__' else 'legend',
            None if self.target.currentData()=='__all__' else self.target.currentData(),True)

    def open_font(self):
        # The local legend choice is authoritative, even after another editor was used.
        self.choose_target()
        self.plot.preferences.open_font(self.editor,self.target.currentText())

    def select_entry(self, key):
        self.refresh_entries()
        self.target.setCurrentIndex(max(0, self.target.findData(key)))
        self.sync_text()

    def sync_text(self, *args):
        if self.loading:
            return
        from tailor.text_style_controls import font_spec, legend_rows

        self.refresh_entries()
        key = self.target.currentData()
        base = font_spec(self.plot.curve_style, "legend")
        entries = self.plot.presentation.legend.get("entries", {})
        rows = legend_rows(self.plot)
        if key == "__all__":
            text = "<br>".join(
                entries.get(k, {}).get("text", original) for k, original, _ in rows
            )
        else:
            entry = entries.get(key, {})
            text = entry.get(
                "text", next((original for k, original, _ in rows if k == key), "")
            )
            base = {**base, **entry.get("style", {})}
        self.editor.load(base, text)
        self._text_editor_spec = self.editor.spec()
        self._text_editor_content = self.editor.content.text()
        if key=='__all__':
            families={entries.get(k,{}).get('style',{}).get('family',base.get('family','sans-serif')) for k,_,_ in rows}
            if len(families)>1:
                self.editor._mixed_family=True
                with QtCore.QSignalBlocker(self.editor.family):self.editor.family.setEditText('多种值')
        self.editor.content.setPlaceholderText("全部图例时每行对应一项；单项图例中Enter换行")

    def state(self):
        return self.plot.curve_style, copy.deepcopy(self.plot.presentation.legend)

    def finish_edit(self, before, title):
        from tailor.text_style_controls import apply_text_styles, record_view_edit

        apply_text_styles(self.plot)
        self.plot.presentation.apply_legend()
        self.plot.main_window.mark_project_dirty()
        after = self.state()

        def restore(plot, state):
            plot.curve_style, plot.presentation.legend = (
                state[0],
                copy.deepcopy(state[1]),
            )
            apply_text_styles(plot)
            plot.presentation.apply_legend()
            plot.legend_controls.sync()

        record_view_edit(self.plot, title, before, after, restore)
        self.refresh_entries()

    def delete_entry(self):
        key = self.target.currentData()
        if key in {None, "__all__", "__add__"}:
            return
        from tailor.legend_entries import remove

        before = self.state()
        remove(self.plot, key)
        self.finish_edit(before, "删除图例行")
        self.sync_text()

    def apply_text(self):
        if self.loading:
            return
        import re

        from tailor.legend_entries import add, remove
        from tailor.text_style_controls import legend_rows, font_spec

        before = self.state()
        key, spec = self.target.currentData(), self.editor.spec()
        text = self.editor.content.text()
        previous = getattr(self, '_text_editor_spec', {})
        changed = {k:v for k,v in spec.items() if previous.get(k) != v}
        text_changed = text != getattr(self, '_text_editor_content', None)
        self._text_editor_spec, self._text_editor_content = dict(spec), text
        cfg = self.plot.presentation.legend
        entries = cfg.setdefault("entries", {})
        if key == "__all__":
            lines = re.split(r"<br\s*/?>|[\n\u2028\u2029]", text)
            rows = legend_rows(self.plot)
            for i, line in enumerate(lines):
                row_key = rows[i][0] if i < len(rows) else add(self.plot, line)
                old_entry = entries.get(row_key, {})
                style={**old_entry.get('style', {}), **changed}
                if not text_changed:
                    line = old_entry.get('text', rows[i][1] if i < len(rows) else line)
                if getattr(self.editor,'_mixed_family',False):
                    style['family']=entries.get(row_key,{}).get('style',{}).get('family',spec['family'])
                entries[row_key] = {"text": line, "style": style}
            for row_key, _, _ in rows[len(lines) :]:
                remove(self.plot, row_key)
            self.plot.curve_style = replace(
                self.plot.curve_style,
                text_styles={**self.plot.curve_style.text_styles, "legend": {
                    **font_spec(self.plot.curve_style,"legend"), **changed}},
            )
        elif key not in {None, "__add__"}:
            entries[key] = {"text": text, "style": spec}
        self.finish_edit(before, "图例文字")

    def position_changed(self):
        if self.position.currentData()=='__custom__':return
        self.apply(position_changed=True)

    def apply(self, *args, position_changed=False):
        if self.loading:
            return
        before = self.state()
        self.plot.presentation.legend.update(
            columns=1,
            spacing=self.spacing.value(),
            visible=self.visible.isChecked(),
            border=self.border.isChecked(),
            background=self.background.isChecked(),
        )
        if position_changed:
            self.plot.presentation.legend["position"] = self.position.currentData()
        self.hide_button.setText("隐藏图例" if self.visible.isChecked() else "显示图例")
        if not self.plot.presentation.multi:
            self.plot.model.legend_visible = self.visible.isChecked()
            with QtCore.QSignalBlocker(self.plot.legend_toggle):
                self.plot.legend_toggle.setChecked(self.visible.isChecked())
        self.finish_edit(before, "图例布局")


class ErrorControls(QtWidgets.QWidget):
    def __init__(self, plot):
        super().__init__()
        self.document = plot
        self.loading = False
        # This card contains full-width composite rows, not a two-column form.
        # Keep wrapped notes and each full-width row independent when the
        # fitting page is moved between graph hosts.
        form = QtWidgets.QVBoxLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(7)
        self.source_note = QtWidgets.QLabel()
        self.source_note.setWordWrap(True)
        form.addWidget(self.source_note)
        self.x, self.y = QtWidgets.QComboBox(), QtWidgets.QComboBox()
        self.x_on, self.y_on = (
            CheckButton("X误差列"),
            CheckButton("Y误差列"),
        )
        for button in (self.x_on, self.y_on):
            button.setFixedWidth(max(button.fontMetrics().horizontalAdvance('X误差列'),button.fontMetrics().horizontalAdvance('Y误差列'))+18)
            button.setToolTip('点击切换该方向误差棒的显示，误差列关联保持不变')
        form.addWidget(row(self.x_on, self.x))
        form.addWidget(row(self.y_on, self.y))
        self.cap, self.width = number(0, 20, 4, unit="px"), number(0.1, 10, 1, unit="px")
        from tailor.compact_controls import DualParameter
        self.shared_size=DualParameter(self.cap,self.width,'端帽','线宽',suffix='px')
        form.addWidget(self.shared_size)
        self.color = color_button("", lambda value: self.apply())
        auto = QtWidgets.QPushButton("随曲线")
        auto.clicked.connect(lambda: (self.color.setText("选择颜色"), self.color.setIcon(QtGui.QIcon()), self.apply()))
        self.auto_color=auto
        form.addWidget(row("颜色", self.color, auto))
        self.message = QtWidgets.QLabel(
            "误差列为绝对 ± 值，须非负；对数轴上跨越零的那一侧不显示。"
        )
        self.message.setWordWrap(True)
        form.addWidget(self.message)
        self.sync()
        for widget in (self.x, self.y):
            widget.activated.connect(self.apply)
        for widget in (self.x_on, self.y_on):
            widget.toggled.connect(self.apply)
        for widget in (self.cap, self.width):
            widget.valueChanged.connect(self.apply)

    @property
    def plot(self):
        # FitRouter reuses a source's native fitting page inside the displayed
        # multi-curve graph. Appearance/history belong to that actual host;
        # error-column bindings continue to belong to the selected source.
        from tailor.fit_workflow import FitRouter
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, FitRouter):
                return parent.graph
            parent = parent.parentWidget()
        return self.document

    def target(self):
        if self.document.presentation.multi:
            return (
                self.document.curve_manager.current_plot()
                if hasattr(self.document, "curve_manager")
                else None
            )
        return self.document

    def sync(self):
        source = self.target()
        self.setEnabled(source is not None)
        if source is None:
            self.source_note.setText('作用曲线：—')
            for box in (self.x,self.y):
                with QtCore.QSignalBlocker(box):box.clear();box.addItem('—',None)
            return
        self.loading = True
        info = (
            self.plot.model.get_plot_info(source)
            if self.plot.presentation.multi
            else None
        )
        config = info.errors if info else self.plot.presentation.errors
        from tailor.column_titles import display
        self.source_note.setText(
            f"作用曲线：{display(source.data_sheet.model,source.model.y_col)}\n误差列关联同时用于该源曲线拟合；外观仅用于当前图。"
        )
        for box, key in (
            (self.x, source.model.x_err_col),
            (self.y, source.model.y_err_col),
        ):
            box.clear()
            box.addItem("—", None)
            from tailor.choice_catalog import visible_columns
            for label in visible_columns(source.data_sheet.model):
                box.addItem(__import__("tailor.column_titles",fromlist=["display"]).display(source.data_sheet.model,label), label)
            box.setCurrentIndex(max(0, box.findData(key)))
        self.x_on.setChecked(config["x_visible"])
        self.y_on.setChecked(config["y_visible"])
        self.cap.setValue(config["cap"])
        self.width.setValue(config["width"])
        self.color.setText(config["color"] or "选择颜色")
        if not config["color"]:
            self.color.setIcon(QtGui.QIcon())
        self.loading = False
        self.sync_enabled()

    def sync_enabled(self):
        valid=(self.x.currentData() is not None,self.y.currentData() is not None)
        for button,available in zip((self.x_on,self.y_on),valid):
            button.setEnabled(available)
            if not available:
                with QtCore.QSignalBlocker(button):button.setChecked(False)
        active=any(available and button.isChecked() for button,available in zip((self.x_on,self.y_on),valid))
        self.shared_size.setEnabled(active)
        self.color.setEnabled(active);self.auto_color.setEnabled(active)
        self.align_error_labels()

    def align_error_labels(self):
        width=self.shared_size.buttons[0].width()
        if width>0:
            for button in (self.x_on,self.y_on):
                if button.width()!=width:
                    button.setFixedWidth(width)
                    layout=button.parentWidget().layout()
                    if layout is not None:layout.invalidate();layout.activate()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        QtCore.QTimer.singleShot(0,self,self.align_error_labels)

    @view_transaction("误差棒设置")
    def apply(self, *args):
        if self.loading:
            return
        source = self.target()
        if source is None:
            return
        if source.main_window.data_operation_busy():
            self.message.setText("请等待当前后台操作结束。")
            return
        keys = (self.x.currentData(), self.y.currentData())
        try:
            for key in keys:
                if key is not None:
                    values = source.model.data_model.get_column(key)
                    if np.any(np.isfinite(values) & (values < 0)):
                        raise ValueError("误差列包含负数，未应用。")
            changed = keys != (source.model.x_err_col, source.model.y_err_col)
            source.model.x_err_col, source.model.y_err_col = keys
            config = {
                "x_visible": self.x_on.isChecked() and keys[0] is not None,
                "y_visible": self.y_on.isChecked() and keys[1] is not None,
                "cap": self.cap.value(),
                "width": self.width.value(),
                "color": self.color.text() if self.color.text().startswith("#") else "",
            }
            if self.plot.presentation.multi:
                self.plot.model.get_plot_info(source).errors = config
            else:
                self.plot.presentation.errors = config
            if changed:
                source._source_changed = True
                source.refresh_from_source()
            else:
                source.update_plot()
            if self.plot.presentation.multi:
                self.plot.draw_plot()
            self.plot.main_window.mark_project_dirty()
            self.message.setText(
                "已应用。修改误差列后，已有拟合需重新检查并手动重拟合。"
            )
        except (ValueError, KeyError) as error:
            self.message.setText(str(error))
        self.sync_enabled()


MARKERS = [
    ("圆", "o"),
    ("方", "s"),
    ("三角", "t"),
    ("菱形", "d"),
    ("加号", "+"),
    ("叉", "x"),
    ("星", "star"),
]


class CurveManager(QtWidgets.QWidget):
    def __init__(self, plot):
        super().__init__()
        self.plot, self.loading = plot, False
        form = QtWidgets.QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        self.curves = QtWidgets.QComboBox()
        self.available = QtWidgets.QComboBox(self)
        self.available.hide()
        form.addRow("当前曲线", self.curves)
        self.visible = CheckButton("显示")
        self.visible.hide()
        from tailor.curve_selection import hide_button

        form.addRow(hide_button(plot))
        self.axis = combo([("左 Y", "left"), ("右 Y（双轴）", "right")])
        self.axis.setParent(self)
        self.axis.hide()
        self.label = QtWidgets.QLineEdit()
        self.label.setPlaceholderText("留空跟随源列名称")
        self.label.setParent(self)
        self.label.hide()
        self.mode = combo(
            __import__("tailor.plot_types", fromlist=["MODE_ITEMS"]).MODE_ITEMS
        )
        self.color = color_button("#202020", self.set_color)
        form.addRow("绘制方式", self.mode)
        form.addRow("颜色", self.color)
        from tailor.line_styles import LINE_STYLES

        self.line = combo(LINE_STYLES)
        self.width = number(0.1, 20, 1.5,unit="px")
        form.addRow("线型 / 宽", row(self.line, self.width))
        self.marker = combo(MARKERS)
        self.size = number(1, 30, 5,unit="px")
        form.addRow("点型 / 大小", row(self.marker, self.size))
        # Per-object fonts reuse the existing clickable font target system.
        plot.style_target = combo(
            [
                ("X 刻度", "x_ticks"),
                ("X 名称", "x_label"),
                ("左 Y 刻度", "y_ticks"),
                ("左 Y 名称", "y_label"),
                ("右 Y 刻度", "right_ticks"),
                ("右 Y 名称", "right_label"),
                ("图例", "legend"),
            ]
        )
        plot.style_font = number(6, 48, 12,unit="pt")
        plot.style_family = FontFamilyCombo()
        plot.style_family.setEditable(True)
        plot.style_family.addItems(["sans-serif", "serif", "monospace"])
        plot.font_form = QtWidgets.QFormLayout()
        plot.font_form.addRow("文字对象", plot.style_target)
        plot.font_form.addRow("字体", row(plot.style_family, plot.style_font))
        from tailor.text_style_controls import connect_font_controls

        connect_font_controls(plot)
        self.curves.currentIndexChanged.connect(self.sync_fields)
        self.curves.activated.connect(lambda *args:self.plot.preferences.select_curve('data' if self.curves.currentData() is not None else 'none',self.curves.currentData()))
        for c in (self.axis, self.mode, self.line, self.marker):
            c.currentIndexChanged.connect(self.apply)
        for c in (self.width, self.size):
            c.valueChanged.connect(self.apply)
        self.visible.toggled.connect(self.apply)
        self.label.editingFinished.connect(self.apply)
        self.refresh()

    def current_plot(self):
        return self.curves.currentData()

    def refresh(self):
        old = getattr(getattr(self.plot,'curve_selection',None),'current',None)
        self.loading = True
        self.curves.clear()
        self.curves.addItem('—',None)
        from tailor.choice_catalog import sorted_sources
        from tailor.column_titles import display
        for source in sorted_sources(self.plot):
            self.curves.addItem(display(source.data_sheet.model,source.model.y_col),source)
        self.curves.setCurrentIndex(max(0, self.curves.findData(old)))
        self.available.clear()
        for source in self.plot.main_window.get_plots():
            if source not in self.plot.model._plots:
                self.available.addItem(source.name, source)
        self.loading = False
        self.sync_fields()

    def sync_fields(self):
        if self.loading:
            return
        source = self.current_plot()
        self.loading = True
        info = self.plot.model.get_plot_info(source)
        if info:
            style = CurveStyle(**info.style) if info.style else source.curve_style
            for widget, value in (
                (self.axis, info.axis),
                (self.mode, style.mode),
                (self.line, style.line_style),
                (self.marker, style.marker),
            ):
                widget.setCurrentIndex(widget.findData(value))
            self.width.setValue(style.line_width)
            self.size.setValue(style.marker_size)
            self.visible.setChecked(info.visible)
            self.label.setText(info.label)
            self.color.setText(info.color)
            self.width.setEnabled(style.mode != "scatter")
            self.line.setEnabled(style.mode != "scatter")
            self.marker.setEnabled(style.mode != "line")
            self.size.setEnabled(style.mode != "line")
        for widget in (self.axis, self.mode, self.label, self.color, self.visible):
            widget.setEnabled(info is not None)
        self.loading = False
        if hasattr(self.plot, "error_controls"):
            self.plot.error_controls.sync()

    @view_transaction("曲线设置")
    def apply(self, *args):
        if self.loading:
            return
        source = self.current_plot()
        info = self.plot.model.get_plot_info(source)
        if info is None:
            return
        style = CurveStyle(**info.style) if info.style else source.curve_style
        info.style = replace(
            style,
            mode=self.mode.currentData(),
            line_style=self.line.currentData(),
            line_width=self.width.value(),
            marker=self.marker.currentData(),
            marker_size=self.size.value(),
            color=info.color,
        ).to_dict()
        info.axis, info.visible, info.label = (
            self.axis.currentData(),
            self.visible.isChecked(),
            self.label.text().strip(),
        )
        if info.axis == "right" and self.plot.presentation.right_label == "右 Y":
            self.plot.presentation.right_label = source.model.y_label
            if hasattr(self.plot, "axis_controls"):
                self.plot.axis_controls.sync()
        self.plot._clear_remembered_zoom()
        self.plot.draw_plot()
        self.plot.main_window.mark_project_dirty()
        self.refresh()

    def set_color(self, value):
        info = self.plot.model.get_plot_info(self.current_plot())
        if info:
            info.color = value
            self.apply()

    def add_existing(self):
        source = self.available.currentData()
        if source is not None:
            self.plot.add_plot(source)
            self.plot._clear_remembered_zoom()
            self.plot.refresh_ui()
            self.plot.main_window.mark_project_dirty()

    def remove(self):
        self.plot.model.remove_plot(self.current_plot())
        self.plot.draw_plot()
        self.refresh()
        self.plot.main_window.mark_project_dirty()

    def move(self, delta):
        keys = list(self.plot.model._plots)
        index = self.curves.currentIndex()
        new = index + delta
        if 0 <= index < len(keys) and 0 <= new < len(keys):
            keys[index], keys[new] = keys[new], keys[index]
            self.plot.model._plots = {key: self.plot.model._plots[key] for key in keys}
            self.plot.draw_plot()
            self.refresh()
            self.plot.main_window.mark_project_dirty()


def add_from_sheet(plot):
    window = plot.main_window
    dialog = QtWidgets.QDialog(plot)
    dialog.setWindowTitle("添加曲线")
    form = QtWidgets.QFormLayout(dialog)
    sheets = combo([(s.name, s) for s in window.get_data_sheets()])
    x, y = QtWidgets.QComboBox(), QtWidgets.QComboBox()
    form.addRow("工作表", sheets)
    form.addRow("X", x)
    form.addRow("Y", y)
    axis = combo([("左 Y", "left"), ("右 Y（双轴）", "right")])
    form.addRow("归属", axis)

    def fill():
        sheet = sheets.currentData()
        for box in (x, y):
            box.clear()
            if sheet:
                for key in sheet.model.columnLabels():
                    box.addItem(__import__("tailor.column_titles",fromlist=["display"]).display(sheet.model,key), key)
        if y.count() > 1:
            y.setCurrentIndex(1)

    sheets.currentIndexChanged.connect(fill)
    fill()
    buttons = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    if (
        dialog.exec() != QtWidgets.QDialog.Accepted
        or x.currentData() is None
        or y.currentData() is None
    ):
        return
    sheet = sheets.currentData()
    source = next(
        (
            p
            for p in window.get_plots()
            if p.data_sheet is sheet
            and p.model.x_col == x.currentData()
            and p.model.y_col == y.currentData()
        ),
        None,
    )
    if source is None:
        source = window.create_plot_tab(sheet, x.currentData(), y.currentData())
    if source is None:
        return
    if plot.presentation.multi:
        overlay = plot
    else:
        window.ui.tabWidget.setCurrentWidget(plot)
        overlay = window.create_multiplot()
        overlay.curve_style = copy.deepcopy(plot.curve_style)
        overlay.presentation.load(plot.presentation.to_dict())
    overlay.update_plots_ui()
    overlay.add_plot(source)
    info = overlay.model.get_plot_info(source)
    info.axis = axis.currentData()
    if info.axis == "right":
        overlay.presentation.right_label = source.model.y_label
    overlay._clear_remembered_zoom()
    window.ui.tabWidget.setCurrentWidget(overlay)
    overlay.refresh_ui()
    overlay.axis_controls.sync()
    overlay.legend_controls.sync()
    window.mark_project_dirty()

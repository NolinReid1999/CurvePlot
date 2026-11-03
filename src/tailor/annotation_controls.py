"""Compact annotation controls in the existing ordered FoldPanel."""

from tailor.compact_controls import CheckButton

import copy

from PySide6 import QtWidgets

from tailor.annotations import KINDS, ONE_POINT
from tailor.compact_controls import toggle_button
from tailor.fold_panel import FoldPanel
from tailor.graph_controls import combo, number, row
from tailor.ui_widgets import ColorButton, FontFamilyCombo


class AnnotationPanel(FoldPanel):
    def __init__(self, manager):
        super().__init__(manager.plot)
        self.manager = manager
        manager.panel = self
        choices = [("左轴数据", "left"), ("画布相对", "canvas")]
        if manager.plot.presentation.multi:
            choices.insert(1, ("右轴数据", "right"))
        self.new_anchor = combo(choices)
        self.new_anchor.currentIndexChanged.connect(
            lambda: setattr(manager, "anchor", self.new_anchor.currentData())
        )
        add = QtWidgets.QVBoxLayout()
        grid = QtWidgets.QGridLayout()
        for i, (key, label) in enumerate(KINDS.items()):
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(lambda checked=False, key=key: manager.arm(key))
            grid.addWidget(button, i // 3, i % 3)
        self.add_menu = QtWidgets.QMenu(self)
        for key, label in KINDS.items():
            self.add_menu.addAction(label, lambda checked=False, k=key: manager.arm(k))

        self.message = QtWidgets.QLabel("点击工具后在图中放置；点击对象选择并拖动。")
        self.message.setWordWrap(True)
        self.message.setProperty("muted", True)
        self.message.hide()
        objects = QtWidgets.QVBoxLayout()
        self.objects = QtWidgets.QComboBox()
        self.objects.setPlaceholderText("选择已有标注")
        self.objects.activated.connect(self.choose)
        from tailor.element_button_group import ElementButtons
        from tailor.compact_controls import equal_row
        self.actions = ElementButtons(manager.plot, "annotations", add=self.open_add_menu)
        objects.addWidget(equal_row(self.actions, self.objects))
        self.anchor_group = QtWidgets.QButtonGroup(self)
        self.anchor_buttons = {}
        for text, key in choices:
            button = toggle_button(text)
            self.anchor_group.addButton(button)
            self.anchor_buttons[key] = button
            button.clicked.connect(lambda checked=False, k=key: self.set_anchor(k))
        buttons = []
        for label, action in (
            ("复制", self.copy_annotation),
            ("粘贴", self.paste_annotation),
            ("上移", lambda: manager.reorder(1)),
            ("下移", lambda: manager.reorder(-1)),

        ):
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(action)
            if label == "删除":
                from tailor.plot_types import icon

                button.setText("")
                button.setIcon(icon("trash-2", button, "#d34b48"))
                button.setToolTip("删除标注")
                button.setFixedWidth(30)
            buttons.append(button)
        object_actions = buttons
        crop = QtWidgets.QPushButton("裁剪")
        from tailor.image_crop import ImageCrop
        self.image_crop = ImageCrop(manager, crop)
        object_actions.append(crop)
        self.visible = toggle_button("显示")
        self.locked = toggle_button("锁定")
        self.visible.setParent(self)
        self.visible.hide()
        action_row = row(self.locked, *object_actions)
        action_row.layout().setSpacing(4)
        for action in (self.visible, self.locked, *object_actions):
            action.setMinimumWidth(0)
            action.setStyleSheet("QPushButton {padding:4px 3px;}")
        objects.addWidget(action_row)
        self.visible.clicked.connect(
            lambda: self.toggle("visible", self.visible.isChecked())
        )
        self.locked.clicked.connect(
            lambda: self.toggle("locked", self.locked.isChecked())
        )
        add.addLayout(objects)
        self.add_controls = add

        self.text = QtWidgets.QPlainTextEdit()
        self.text.setPlaceholderText("文字内容（纯文本）")
        self.text.setMaximumHeight(65)
        self.family = FontFamilyCombo()
        self.family.addItems(
            ["sans-serif", "serif", "monospace", "Arial", "PingFang SC"]
        )
        self.family.setEditable(True)
        self.size = number(6, 72, 12,unit="pt")
        self.bold = CheckButton("粗体")
        self.rotation = number(-180, 180, 0)
        self.rotation.setSuffix(' °')
        self.color = ColorButton("#202020")
        self.fill = ColorButton("#ffffff")
        self.filled = CheckButton("填充")
        self.fill_opacity = number(0, 100, 18, 0,unit="%")
        for button in (self.color, self.fill):
            button.clicked.connect(
                lambda checked=False, button=button: self.pick_color(button)
            )
        self.width = number(0.1, 20, 1.5,unit="pt")
        self.linestyle = combo(
            [
                ("实线", "solid"),
                ("虚线", "dash"),
                ("点线", "dot"),
                ("点划线", "dashdot"),
            ]
        )
        # Hidden compatibility controls retain loading and existing record format.
        self.legacy = QtWidgets.QWidget(self)
        for widget in (
            self.text,
            self.family,
            self.size,
            self.bold,
            self.color,
            self.width,
            self.linestyle,
        ):
            widget.setParent(self.legacy)
        self.legacy.hide()
        add.addWidget(row("旋转", self.rotation))
        self.filled.setText("")
        from tailor.color_palette import ColorPalette

        self.fill_palette = ColorPalette("annotation_fill")
        self.fill_palette.changed.connect(self.palette_fill)
        self.filled.setParent(self.legacy)
        self.filled.hide()
        self.fill.setParent(self.legacy)
        self.fill.hide()
        for widget in (self.fill_palette, self.fill_opacity):
            widget.setParent(self.legacy)
            widget.hide()
        self.fill_opacity.setAccessibleName("不透明度")
        self.fill_opacity.setToolTip("不透明度：0为透明，100为不透明")
        self.add_section("添加标注", add, True)
        position = QtWidgets.QVBoxLayout()
        self.anchor = combo(choices)
        self.anchor.setParent(self.legacy)
        self.anchor.hide()
        self.anchor.activated.connect(self.change_anchor)
        self.coords = [QtWidgets.QLineEdit() for _ in range(4)]
        for field in self.coords:
            field.setParent(self.legacy)
            field.hide()
        from tailor.object_position import ObjectPosition

        self.position_controls = ObjectPosition(manager.plot)
        position.addWidget(self.position_controls)
        self.add_section("位置与坐标", position)
        self.loading = False
        self.rotation.valueChanged.connect(self.apply)
        self.filled.clicked.connect(self.apply)
        self.fill_opacity.valueChanged.connect(self.apply)
        for field in self.coords:
            field.editingFinished.connect(self.apply)
        manager.changed.connect(self.sync)
        self.sync()

    def copy_annotation(self):
        import json
        record = self.manager.current()
        if record is None:
            return
        # Let Qt own its plain-text MIME object; transferring a Python-owned
        # QMimeData can double-delete in the offscreen platform at shutdown.
        QtWidgets.QApplication.clipboard().setText("Curve 标注\n" + json.dumps(record, ensure_ascii=False))

    def paste_annotation(self):
        import json
        import uuid
        from tailor.annotation_validation import validate_annotation
        text = QtWidgets.QApplication.clipboard().text()
        if not text.startswith("Curve 标注\n"):
            return
        try:
            record = json.loads(text.split("\n", 1)[1])
            validate_annotation(record)
            record["id"] = uuid.uuid4().hex
            record["locked"], record["visible"] = False, True
            before = copy.deepcopy(self.manager.records)
            record["points"] = [v + (0.02 if record["anchor"] == "canvas" else 0) for v in record["points"]]
            self.manager.records.append(record)
            self.manager.commit(before, "粘贴标注")
            self.manager.select(record["id"])
        except (ValueError, TypeError, KeyError):
            self.manager.plot.main_window.statusBar().showMessage("剪贴板中的标注无效，未粘贴。", 5000)

    def open_add_menu(self):
        from PySide6 import QtCore
        self.add_menu.setMinimumWidth(max(self.actions.width(), 150))
        self.add_menu.popup(self.actions.mapToGlobal(QtCore.QPoint(0, self.actions.height())))

    def palette_fill(self, value):
        self.fill.setText(value or "#ffffff")
        self.filled.setChecked(bool(value))
        self.apply()

    def set_anchor(self, key):
        self.manager.anchor = key
        self.new_anchor.setCurrentIndex(self.new_anchor.findData(key))
        if self.manager.current():
            self.anchor.setCurrentIndex(self.anchor.findData(key))
            self.change_anchor()

    def choose(self, index):
        self.manager.select(self.objects.itemData(index))

    def pick_color(self, button):
        from PySide6 import QtGui

        color = QtWidgets.QColorDialog.getColor(QtGui.QColor(button.text()), self)
        if color.isValid():
            button.setText(color.name())
            self.apply()

    def toggle(self, key, value):
        record = self.manager.current()
        if record:
            # Visibility/locking must also work for annotations hidden by log or right-axis settings.
            before = copy.deepcopy(self.manager.records)
            record[key] = value
            self.manager.commit(before, "修改标注")

    def change_anchor(self, *args):
        record = self.manager.current()
        if record is None:
            return
        candidate = copy.deepcopy(record)
        anchor = self.anchor.currentData()
        try:
            if anchor == "right" and not self.manager.plot.presentation.has_right():
                raise ValueError("请先启用右 Y 轴曲线")
            if not self.manager.representable(record):
                raise ValueError("请先恢复原坐标轴，使标注可见后再转换定位方式")
            candidate["points"] = self.manager.from_pixels(
                anchor, self.manager.to_pixels(record)
            )
            candidate["anchor"] = anchor
            self.manager.replace(candidate)
        except ValueError as error:
            self.message.setText(str(error))
            self.message.show()
            self.anchor.setCurrentIndex(self.anchor.findData(record["anchor"]))

    def apply(self):
        if self.loading:
            return
        record = self.manager.current()
        if record is None:
            self.message.setText("请先在图中或对象列表中选择一个标注。")
            return
        try:
            candidate = {
                **record,
                "points": [float(field.text()) for field in self.coords],
                "text": self.text.toPlainText(),
                "family": self.family.currentText(),
                "size": self.size.value(),
                "bold": self.bold.isChecked(),
                "rotation": self.rotation.value(),
                "color": self.color.text(),
                "fill": self.fill.text() if self.filled.isChecked() else "",
                "fill_opacity": self.fill_opacity.value() / 100,
                "width": self.width.value(),
                "linestyle": self.linestyle.currentData(),
            }
            if candidate["kind"] in ONE_POINT:
                candidate["points"][2:] = candidate["points"][:2]
            self.manager.replace(candidate)
            self.message.setText("标注已更新。")
        except ValueError as error:
            self.message.setText(str(error))
            self.message.show()

    def sync(self):
        self.loading = True
        self._sync()
        self.loading = False
        self.actions.sync()

    def _sync(self):
        record = self.manager.current()
        self.objects.blockSignals(True)
        self.objects.clear()
        self.objects.addItem('—',None)
        from tailor.choice_catalog import object_rank
        for r in sorted(self.manager.records,key=lambda r:object_rank(self.manager.plot,'annotation',r['id'])):
            if not r['visible']:
                continue
            from tailor.annotations import annotation_caption
            text = annotation_caption(r, self.manager.records) + (' · 锁定' if r['locked'] else '')
            self.objects.addItem(text, r["id"])
        self.objects.setCurrentIndex(max(0,self.objects.findData(self.manager.selected)))
        self.objects.blockSignals(False)
        anchor = record["anchor"] if record else self.manager.anchor
        self.anchor_buttons[anchor].setChecked(True)
        for widget in (
            self.visible,
            self.locked,
            self.text,
            self.family,
            self.size,
            self.bold,
            self.rotation,
            self.color,
            self.fill,
            self.filled,
            self.fill_opacity,
            self.fill_palette,
            self.width,
            self.linestyle,
            self.anchor,
            *self.coords,
        ):
            widget.setEnabled(record is not None)
        if not record:
            return
        self.visible.setChecked(record["visible"])
        self.locked.setChecked(record["locked"])
        self.text.setPlainText(record["text"])
        self.family.setCurrentText(record["family"])
        self.size.setValue(record["size"])
        self.bold.setChecked(record["bold"])
        self.rotation.setValue(record["rotation"])
        self.color.setText(record["color"])
        self.fill.setText(record["fill"] or "#ffffff")
        self.filled.setChecked(bool(record["fill"]))
        self.fill_palette.set_value(record["fill"])
        self.fill_opacity.setValue(record.get("fill_opacity", 0.18) * 100)
        self.width.setValue(record["width"])
        self.linestyle.setCurrentIndex(self.linestyle.findData(record["linestyle"]))
        self.anchor.setCurrentIndex(self.anchor.findData(record["anchor"]))
        for i, field in enumerate(self.coords):
            field.setText(format(record["points"][i], ".12g"))
            field.setEnabled(
                not (i >= 2 and record["kind"] in ONE_POINT)
                and not (i == 0 and record["kind"] == "hline")
                and not (i == 1 and record["kind"] == "vline")
            )
        is_text = record["kind"] == "text"
        for widget in (self.filled, self.fill, self.fill_opacity, self.fill_palette):
            widget.setEnabled(record["kind"] in {"rectangle", "ellipse"})
        self.rotation.setEnabled(record["kind"] not in {"hline", "vline"})
        for widget in (self.text, self.family, self.size, self.bold):
            widget.setEnabled(is_text)


def setup_annotations(plot):
    from tailor.annotations import AnnotationManager

    plot.annotations = AnnotationManager(plot)
    panel = AnnotationPanel(plot.annotations)
    plot.property_tabs.currentChanged.connect(plot.annotations.page_changed)
    return panel

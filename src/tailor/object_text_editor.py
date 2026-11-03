"""Reusable controls for a selected axis title, tick label or legend entry."""

from tailor.compact_controls import CheckButton

from PySide6 import QtCore, QtGui, QtWidgets

from tailor.compact_controls import RichTextEdit, stepper, toggle_button
from tailor.graph_controls import color_button, number, row
from tailor.ui_widgets import FontFamilyCombo


class ObjectTextEditor(QtWidgets.QWidget):
    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.loading = False
        self._global = {
            "family": "sans-serif",
            "size": 12.0,
            "bold": False,
            "italic": False,
            "color": "#202020",
            "underline": False,
        }
        form = QtWidgets.QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        self.content = RichTextEdit()
        self.family = FontFamilyCombo()
        self.family.setEditable(True)
        self.family.addItems(["sans-serif", "serif", "monospace"])
        self.family.add_system_fonts()
        self.size = number(6, 48, 12)
        self.bold = QtWidgets.QToolButton()
        self.bold.setText("B")
        self.bold.setCheckable(True)
        self.bold.setToolTip("粗体")
        self.italic = QtWidgets.QToolButton()
        self.italic.setText("I")
        self.italic.setCheckable(True)
        self.italic.setToolTip("斜体")
        self.super_button = QtWidgets.QToolButton()
        self.super_button.setText("x²")
        self.super_button.setToolTip("所选字母上标（不作用于中文和数字）")
        self.sub_button = QtWidgets.QToolButton()
        self.sub_button.setText("x₂")
        self.sub_button.setToolTip("所选字母下标（不作用于中文和数字）")
        for button, kind in ((self.super_button, "sup"), (self.sub_button, "sub")):
            button.setFocusPolicy(QtCore.Qt.NoFocus)
            button.clicked.connect(
                lambda checked=False, k=kind: self.content.apply_script(k)
            )
        self.color = color_button("#202020", self.choose_color)
        self.align = QtWidgets.QComboBox()
        for label, key in (("左对齐", "left"), ("居中", "center"), ("右对齐", "right")):
            self.align.addItem(label, key)
        self.spacing = number(0.7, 3, 1.0, 2)
        self.background = color_button("#ffffff", lambda color: self.notify())
        self.has_background = toggle_button("文字底色")
        self.underline = QtWidgets.QToolButton()
        self.underline.setText("U̲")
        self.underline.setCheckable(True)
        self.underline.setToolTip("下划线")
        self.overline = QtWidgets.QToolButton()
        self.overline.setText("x̅")
        self.overline.setToolTip("所选字母上划线（不作用于中文和数字）")
        self.overline.clicked.connect(lambda: self.decorate("overline"))
        self.wave = QtWidgets.QToolButton()
        self.wave.setText("x̃")
        self.wave.setToolTip("所选字母上波浪线（不作用于中文和数字）")
        self.dot = QtWidgets.QToolButton()
        self.dot.setText("ẋ")
        self.dot.setToolTip("所选字母上点（不作用于中文和数字）")
        self.wave.clicked.connect(lambda: self.decorate("wave"))
        self.dot.clicked.connect(lambda: self.decorate("dot"))
        self.clear = QtWidgets.QToolButton()
        self.clear.setText("T×")
        self.clear.setToolTip("清除格式")
        self.clear.clicked.connect(self.clear_format)
        self.greek = QtWidgets.QToolButton()
        self.greek.setText("Ω")
        self.greek.setToolTip("插入希腊字母")
        self.greek.setToolTip("插入常用符号")
        self.greek.clicked.connect(self.open_symbols)
        form.addRow("文字内容", self.content)
        form.addRow("字体", self.family)
        form.addRow("大小", stepper(self.size, 0.5))
        form.addRow(row(self.bold, self.italic, self.super_button, self.sub_button))
        form.addRow("文字颜色", self.color)
        form.addRow("对齐", self.align)
        form.addRow("行距", row(self.spacing,"倍"))
        form.addRow(row(self.has_background, self.background))
        form.addRow(
            row(
                self.underline,
                self.overline,
                self.wave,
                self.dot,
                self.greek,
                self.clear,
            )
        )
        for button in (
            self.bold,
            self.italic,
            self.underline,
            self.overline,
            self.wave,
            self.dot,
            self.clear,
        ):
            button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.align.activated.connect(self.notify)
        self.spacing.valueChanged.connect(self.notify)
        self.has_background.toggled.connect(self.notify)
        self.underline.toggled.connect(
            lambda checked: self.char_style("underline", checked)
        )
        self.content.selectionChanged.connect(self.selection_changed)
        self.content.cursorPositionChanged.connect(self.selection_changed)
        self.content.editingFinished.connect(self.notify)
        self.family.activated.connect(
            lambda: self.char_style("family", self.family.currentText())
        )
        self.family.lineEdit().editingFinished.connect(
            lambda: self.char_style("family", self.family.currentText())
        )
        self.size.valueChanged.connect(
            lambda: self.char_style("size", self.size.value())
        )
        self.bold.toggled.connect(lambda checked: self.char_style("bold", checked))
        self.italic.toggled.connect(lambda checked: self.char_style("italic", checked))
        self.rebuild_layout(form)
        self.selection_changed()

    def rebuild_layout(self, form):
        from tailor.compact_controls import format_icon

        parking = QtWidgets.QWidget(self)
        parking.hide()
        self._old_rows = parking
        while form.count():
            item = form.takeAt(0)
            if item.widget():
                item.widget().setParent(parking)
        self.setProperty("foldCard", True)
        self.setAttribute(QtCore.Qt.WA_StyledBackground)
        form.setContentsMargins(10, 10, 10, 10)
        form.setSpacing(8)
        form.addRow("内容", self.content)
        self.content.show()
        form.addRow("字体", self.family)
        self.family.show()
        from tailor.color_palette import ColorPalette

        self.color_palette = ColorPalette("text")
        self.background_palette = ColorPalette("background")
        self.color_palette.changed.connect(self.palette_color)
        self.background_palette.changed.connect(self.palette_background)
        self.color.hide()
        self.color.setParent(parking)
        self.background.hide()
        self.background.setParent(parking)
        form.addRow("颜色", self.color_palette)
        from tailor.choice_buttons import ChoiceButtons

        form.addRow("对齐", ChoiceButtons(self.align, equal=True))
        tools = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(tools)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(3)
        grid.setAlignment(QtCore.Qt.AlignLeft)
        self.format_buttons = [
            (self.bold, "bold"),
            (self.italic, "italic"),
            (self.super_button, "sup"),
            (self.sub_button, "sub"),
            (self.underline, "underline"),
            (self.overline, "overline"),
            (self.wave, "wave"),
            (self.dot, "dot"),
            (self.greek, "greek"),
            (self.clear, "clear"),
        ]
        for i, (button, kind) in enumerate(self.format_buttons):
            button.setText("")
            button.setIcon(format_icon(kind, self))
            button.setIconSize(QtCore.QSize(24, 24))
            button.setFixedSize(26, 30)
            button.setStyleSheet("QToolButton {padding:0;}")
            button.show()
            grid.addWidget(button, 0, i)
        self.greek.setStyleSheet(
            "QToolButton {padding:0;} QToolButton::menu-indicator {image:none;width:0;height:0;}"
        )
        form.addRow(tools)
        old = self.has_background
        old.hide()
        self.has_background = CheckButton()
        self.has_background.toggled.connect(self.notify)
        self.has_background.setParent(parking)
        self.has_background.hide()
        form.addRow("底色", self.background_palette)
        form.addRow("大小", row(self.size,"pt"))
        form.addRow("行距", row(self.spacing,"倍"))
        self.orientation = QtWidgets.QComboBox(self)
        from tailor.text_layout import ORIENTATIONS
        for title,key in ORIENTATIONS:self.orientation.addItem(title,key)
        self.orientation.activated.connect(self.notify)
        self.orientation_buttons = ChoiceButtons(self.orientation, equal=True)
        form.addRow("文本排列", self.orientation_buttons)
        self.box_fill = ColorPalette("annotation_fill")
        self.box_fill.changed.connect(lambda value: self.notify())
        self.box_opacity = number(0, 100, 18, 0)
        self.box_opacity.valueChanged.connect(self.notify)
        form.addRow("填充", self.box_fill)
        form.addRow("不透明度", row(self.box_opacity, "%"))
        self.sync_field_titles()
        self.set_annotation_mode(False)
        from tailor.appearance import manager

        manager().changed.connect(self.refresh_icons)

    def sync_field_titles(self):
        self._field_titles_pending = False
        if not hasattr(self, 'box_opacity'):
            return
        form = self.layout()
        for i in range(form.rowCount()):
            item = form.itemAt(i, QtWidgets.QFormLayout.LabelRole)
            if item and item.widget():
                item.widget().ensurePolished()
        from tailor.label_alignment import align_labels
        align_labels(self)

    def set_target_selected(self,selected):
        with QtCore.QSignalBlocker(self.family):
            if not selected:
                if self.family.currentText()!='—':self._last_target_family=self.family.currentText()
                self.family.setCurrentIndex(-1)
                self.family.setEditText('—')
            elif self.family.currentText()=='—':
                self.family.setCurrentText(getattr(self,'_last_target_family',self._global.get('family','sans-serif')))
        self.setEnabled(selected)

    def schedule_field_titles(self):
        if getattr(self, '_field_titles_pending', False):
            return
        self._field_titles_pending = True
        QtCore.QTimer.singleShot(0, self, self.sync_field_titles)

    def showEvent(self, event):
        super().showEvent(event)
        self.schedule_field_titles()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QtCore.QEvent.FontChange, QtCore.QEvent.StyleChange):
            self.schedule_field_titles()

    def set_annotation_mode(self, enabled):
        for control in (self.orientation, self.orientation_buttons, self.box_fill, self.box_opacity):
            control.setEnabled(enabled)

    def open_symbols(self):
        dialog = QtWidgets.QDialog(self)
        dialog.setObjectName("commonSymbols")
        dialog._curve_theme_document = True
        dialog.setWindowTitle("常用数学与物理符号")
        dialog.resize(560, 370)
        dialog.setMinimumSize(520, 340)
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        category_row = QtWidgets.QHBoxLayout()
        category_row.setSpacing(8)
        category_group = QtWidgets.QButtonGroup(dialog)
        pages = QtWidgets.QStackedWidget(dialog)
        layout.addLayout(category_row)
        layout.addWidget(pages, 1)
        categories = [
            ("希腊字母", "αβγδεζηθικλμνξοπρστυφχψωΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ"),
            ("数学", "±∓×÷·√∛∞≈≠≡≤≥∝∑∏∫∬∭∮∂∇∆∈∉∅∩∪⊂⊆∀∃ℝℂℕℤℏ"),
            ("物理与单位", [*"°℃℉ÅµΩ‰%′″→←↑↓↔⇒⇌⊥∥∠ħℓ", "ε₀", "μ₀"]),
        ]
        for index, (title, chars) in enumerate(categories):
            category = toggle_button(title)
            category.setFixedHeight(30)
            category_group.addButton(category, index)
            category_row.addWidget(category, 1)
            category.clicked.connect(lambda checked=False, index=index: pages.setCurrentIndex(index))
            category.setChecked(index == 0)
            page = QtWidgets.QFrame(pages)
            page.setProperty("foldCard", True)
            page.setAttribute(QtCore.Qt.WA_StyledBackground, True)
            grid = QtWidgets.QGridLayout(page)
            grid.setContentsMargins(12, 12, 12, 12)
            grid.setSpacing(7)
            for i, char in enumerate(chars):
                button = QtWidgets.QPushButton(char, page)
                button.setFixedHeight(38)
                button.setMinimumWidth(36)
                button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
                button.setFocusPolicy(QtCore.Qt.NoFocus)
                button.setToolTip("插入 " + char)
                button.setStyleSheet("QPushButton {font-size:18px; padding:0; min-height:36px; max-height:36px;}")
                button.clicked.connect(lambda checked=False, c=char: self.insert_symbol(c))
                grid.addWidget(button, i // 10, i % 10)
            for column in range(10):
                grid.setColumnStretch(column, 1)
            grid.setRowStretch(grid.rowCount(), 1)
            pages.addWidget(page)
        footer = QtWidgets.QHBoxLayout()
        footer.addStretch()
        close = QtWidgets.QPushButton("完成", dialog)
        close.setProperty("intent", "primary")
        close.setFixedHeight(30)
        close.setMinimumWidth(92)
        close.clicked.connect(dialog.accept)
        footer.addWidget(close)
        layout.addLayout(footer)
        dialog.exec()

    def palette_color(self, value):
        self.color.setText(value or "#202020")
        self.choose_color(value or "#202020")

    def palette_background(self, value):
        self.background.setText(value or "#ffffff")
        with QtCore.QSignalBlocker(self.has_background):
            self.has_background.setChecked(bool(value))
        self.notify()

    def refresh_icons(self):
        self.content.refresh_accents()
        from tailor.compact_controls import format_icon

        for button, kind in self.format_buttons:
            button.setIcon(format_icon(kind, self))

    def selection_changed(self):
        from tailor.text_layout import selected_letters
        cursor=self.content.textCursor()
        selected=self.content.isEnabled() and bool(selected_letters(cursor))
        for button in (self.super_button,self.sub_button,self.overline,self.wave,self.dot):button.setEnabled(selected)
        if self.loading:return
        probe=QtGui.QTextCursor(cursor)
        if cursor.hasSelection():
            probe.setPosition(cursor.selectionStart())
            probe.movePosition(QtGui.QTextCursor.NextCharacter,QtGui.QTextCursor.KeepAnchor)
        fmt=probe.charFormat();spec=dict(self._global)
        if cursor.hasSelection():
            for key,prop,value in [('bold',QtGui.QTextFormat.FontWeight,fmt.fontWeight()>=QtGui.QFont.Bold),
                                    ('italic',QtGui.QTextFormat.FontItalic,fmt.fontItalic()),
                                    ('underline',QtGui.QTextFormat.TextUnderlineStyle,fmt.fontUnderline()),
                                    ('size',QtGui.QTextFormat.FontPointSize,fmt.fontPointSize()),
                                    ('color',QtGui.QTextFormat.ForegroundBrush,fmt.foreground().color().name())]:
                if fmt.hasProperty(prop):spec[key]=value
        blockers=[QtCore.QSignalBlocker(w) for w in (self.bold,self.italic,self.underline,self.size,self.family)]
        if cursor.hasSelection() and fmt.fontFamilies():spec['family']=fmt.fontFamilies()[0]
        self.family.setCurrentText(spec.get('family','sans-serif'))
        self.bold.setChecked(spec.get('bold',False));self.italic.setChecked(spec.get('italic',False))
        self.underline.setChecked(spec.get('underline',False));self.size.setValue(spec.get('size',12))
        self.color.setText(spec.get('color','#202020'))
        self.color_palette.set_value(spec.get('color','#202020'))
        del blockers

    def notify(self, *args):
        if self.loading or getattr(self,'_notifying',False):return
        payload=(self.content.text(),self.spec())
        if payload==getattr(self,'_last_notified',None):return
        self._last_notified=payload
        self._notifying=True
        try:self.changed.emit()
        finally:self._notifying=False

    def load(self, spec, text=None):
        self.loading = True
        self._mixed_family=False
        self._global = dict(spec)
        content_blocker=QtCore.QSignalBlocker(self.content)
        try:
            from tailor.text_style_controls import native_font
            self.content.document().setDefaultFont(native_font(spec))
            self.content.fit_content()
            self.orientation.setCurrentIndex(max(0, self.orientation.findData(('ccw90' if spec.get('text_orientation')=='vertical' else spec.get('text_orientation','horizontal')))))
            self.box_fill.set_value(spec.get("text_fill", ""))
            self.box_opacity.setValue(spec.get("text_fill_opacity", 0.18) * 100)
            self.family.setCurrentText(spec["family"])
            self.size.setValue(spec["size"])
            self.bold.setChecked(spec.get("bold", False))
            self.italic.setChecked(spec.get("italic", False))
            self.color.setText(spec.get("color", "#202020"))
            if not self.content.textCursor().hasSelection():
                self.color_palette.set_value(spec.get("color", "#202020"))
            self.background_palette.set_value(spec.get("background", ""))
            self.align.setCurrentIndex(
                max(0, self.align.findData(spec.get("align", "left")))
            )
            self.spacing.setValue(spec.get("spacing", 1.0) if self.property('spacingAllowed') is not False else 1.0)
            self.underline.setChecked(spec.get("underline", False))
            self.has_background.setChecked(bool(spec.get("background", "")))
            self.background.setText(spec.get("background") or "#ffffff")
            self.content.setEnabled(text is not None)
            value = text if text is not None else "点击图中的某一个刻度文字后，可编辑其显示内容。"
            if (self.content.text()!=value and not getattr(self,'_notifying',False)
                    and not self.content._commit_timer.isActive()):
                self.content.setText(value)
            palette=self.content.palette()
            color=QtGui.QColor(spec.get('color','#202020'))
            if color.lightness()<50 and palette.color(QtGui.QPalette.Base).lightness()<70:
                color=self.palette().color(QtGui.QPalette.Text)
            palette.setColor(QtGui.QPalette.Text,color);self.content.setPalette(palette)
            from tailor.cjk_text import apply_weight
            apply_weight(self.content.document(),spec,resolve_family=False)
            self.content.fit_content()
            self.selection_changed()
        finally:
            self.loading = False
        del content_blocker
        self.selection_changed()
        if not getattr(self,'_notifying',False):self._last_notified=(self.content.text(),self.spec())

    def spec(self):
        return {
            "size": self._global.get("size", self.size.value()),
            "family": self._global.get("family", self.family.currentText()),
            "italic": self._global.get("italic", self.italic.isChecked()),
            "bold": self._global.get("bold", self.bold.isChecked()),
            "color": self._global.get("color", self.color.text()),
            "underline": self._global.get("underline", self.underline.isChecked()),
            "text_orientation": self.orientation.currentData(),
            "text_fill": self.box_fill.value,
            "text_fill_opacity": self.box_opacity.value() / 100,
            "align": self.align.currentData(),
            "spacing": self.spacing.value() if self.property('spacingAllowed') is not False else 1.0,
            "background": self.background.text()
            if self.has_background.isChecked()
            else "",
        }

    def char_style(self, kind, value):
        if self.loading:
            return
        if kind=='family':
            if value in {'—','多种值'}:return
            self._mixed_family=False
        cursor = self.content.textCursor()
        if self.content.isEnabled():
            if not cursor.hasSelection() or self.property('wholeTargetFont') is True:cursor.select(QtGui.QTextCursor.Document)
            if cursor.selectionStart()==0 and cursor.selectionEnd()==self.content.document().characterCount()-1:
                self._global[kind]=value
            fmt = QtGui.QTextCharFormat()
            if kind == "bold":
                fmt.setFontWeight(QtGui.QFont.Bold if value else QtGui.QFont.Normal)
            elif kind == "italic":
                fmt.setFontItalic(value)
            elif kind == "underline":
                fmt.setFontUnderline(value)
            elif kind == "family":
                fmt.setFontFamilies([value])
            elif kind == "size":
                fmt.setFontPointSize(value)
            elif kind == "color":
                fmt.setForeground(QtGui.QColor(value))
            cursor.mergeCharFormat(fmt)
            self.content.setTextCursor(cursor)
            if "data:image/png;base64," in cursor.selection().toHtml():
                from tailor.text_accents import restyle
                cursor.insertHtml(restyle(cursor.selection().toHtml(), {kind: value}, explicit=True))
        else:
            self._global[kind] = value
        self.notify()
        self.selection_changed()

    def choose_color(self, color):
        self.char_style("color", color)

    def insert_symbol(self, char):
        self.content.textCursor().insertText(char)
        self.notify()

    def decorate(self, kind):
        from tailor.text_layout import selected_letters,format_letters
        cursor=self.content.textCursor();letters=selected_letters(cursor)
        if not letters:return
        if kind=='overline':
            probe=QtGui.QTextCursor(self.content.document());p,n,_=letters[0]
            probe.setPosition(p);probe.setPosition(p+n,QtGui.QTextCursor.KeepAnchor)
            active=probe.charFormat().fontOverline()
            format_letters(cursor,lambda fmt,old:fmt.setFontOverline(not active))
        else:
            mark='\u0307' if kind=='dot' else '\u0303'
            document=self.content.document();edit=QtGui.QTextCursor(document)
            edit.beginEditBlock()
            try:
                for pos,count,char in reversed(letters):
                    edit.setPosition(pos);edit.setPosition(pos+count,QtGui.QTextCursor.KeepAnchor)
                    text=edit.selectedText();fmt=edit.charFormat()
                    edit.insertText(text.replace(mark,'') if mark in text else text+mark,fmt)
            finally:edit.endEditBlock()
        self.notify()

    def clear_format(self):
        if self.loading:
            return
        cursor = self.content.textCursor()
        if not cursor.hasSelection():
            cursor.select(QtGui.QTextCursor.Document)
        if "data:image/png;base64," in cursor.selection().toHtml():
            import html
            import re

            from tailor.text_accents import decode
            def original(match):
                payload = decode(match[1])
                return html.escape(payload["text"]) if payload else match[0]
            markup = re.sub(r'<img\b[^>]*\bsrc="(data:image/png;base64,[^"]+)"[^>]*>',original,cursor.selection().toHtml())
            document = QtGui.QTextDocument()
            document.setHtml(markup)
            cursor.insertText(document.toPlainText(),QtGui.QTextCharFormat())
        if any(c in cursor.selectedText() for c in ('\u0303','\u0307')):
            cursor.insertText(cursor.selectedText().replace('\u0303','').replace('\u0307',''),QtGui.QTextCharFormat())
        cursor.setCharFormat(QtGui.QTextCharFormat())
        self.content.setTextCursor(cursor)
        self.loading = True
        self.bold.setChecked(False)
        self.italic.setChecked(False)
        self.underline.setChecked(False)
        self.has_background.setChecked(False)
        self.loading = False
        self.background_palette.set_value("")
        self.notify()

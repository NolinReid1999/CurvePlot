"""Small adapters around existing Qt input widgets; no secondary value model."""

import html

from PySide6 import QtCore, QtGui, QtWidgets


class CompactDoubleSpinBox(QtWidgets.QDoubleSpinBox):
    """Keep decimal input precision without padding integers with zeroes."""
    def textFromValue(self,value):
        if getattr(self, '_automatic', False) and value < 0:return 'Auto'
        return format(value,'.12g').replace('.',self.locale().decimalPoint())

    def valueFromText(self,text):
        if getattr(self, '_automatic', False) and text.strip().lower() in {'','auto','自动'}:return -1.
        return super().valueFromText(text)

    def validate(self,text,pos):
        if getattr(self, '_automatic', False):
            if text.strip().lower() in {'','a','au','aut','auto','自动'}:
                return (QtGui.QValidator.Acceptable if text.strip().lower() in {'auto','自动'} else QtGui.QValidator.Intermediate, text, pos)
            if text.strip().startswith('-'):return QtGui.QValidator.Invalid,text,pos
        return super().validate(text,pos)

    def stepBy(self,steps):
        if getattr(self, '_automatic', False):
            if getattr(self, '_positive_auto', False):
                if self.value()<0 and steps<0:return
                from tailor.axis_tick_policy import advance_interval
                self.setValue(advance_interval(self.value(),steps,self.singleStep(),self._auto_step_base))
                return
            value=self.value()
            if value < 0:
                if steps>0:
                    automatic=getattr(self,'_auto_step_base',None)
                    self.setValue(max(0,automatic()+steps*self.singleStep()) if callable(automatic) else max(0,(steps-1)*self.singleStep()))
                return
            if value==0 and steps<0:self.setValue(-1);return
            self.setValue(max(0,value+steps*self.singleStep()))
            return
        super().stepBy(steps)


class _FittedNumberDisplay(QtCore.QObject):
    """Use the existing SpinBox formatter without quantizing its stored value."""
    def __init__(self, spin):
        super().__init__(spin)
        import weakref
        self.spin=weakref.ref(spin)
        self.original=type(spin).formatText
        self.tooltip=spin.toolTip()
        self.editing=False
        spin.formatText=self.format_text
        spin.installEventFilter(self)
        spin.lineEdit().installEventFilter(self)
        spin.updateText()

    def format_text(self):
        spin=self.spin()
        if spin is None:return ''
        decimals=spin.opts['decimals']
        full=repr(spin.value())
        spin.setToolTip((self.tooltip+'\n' if self.tooltip else '')+'完整数值：'+full)
        try:
            if self.editing or spin.hasFocus():
                spin.opts['decimals']=17
                return self.original(spin)
            text=self.original(spin)
            width=spin.lineEdit().contentsRect().width()
            if width<=0:return text
            for precision in range(decimals-1,0,-1):
                if spin.fontMetrics().horizontalAdvance(text)<=width:break
                spin.opts['decimals']=precision
                text=self.original(spin)
            return spin.fontMetrics().elidedText(text,QtCore.Qt.ElideRight,width)
        finally:
            spin.opts['decimals']=decimals

    def eventFilter(self,watched,event):
        spin=self.spin()
        if spin is None:return False
        kind=event.type()
        if kind==QtCore.QEvent.Paint and not spin.hasFocus():
            # A hidden/reparented editor can retain text formatted for its
            # previous width without another resize signal. Refresh before
            # paint, only when the existing formatter's result has changed.
            if spin.text()!=self.format_text():spin.updateText()
            return False
        if kind in (QtCore.QEvent.Resize,QtCore.QEvent.FontChange,QtCore.QEvent.StyleChange,QtCore.QEvent.FocusOut,QtCore.QEvent.FocusIn,QtCore.QEvent.WindowDeactivate):
            if kind==QtCore.QEvent.FocusIn:
                self.editing=True
                try:spin.updateText();spin.selectNumber()
                finally:self.editing=False
            elif kind==QtCore.QEvent.FocusOut:
                self.editing=False
                QtCore.QTimer.singleShot(0,spin,spin.updateText)
            elif not spin.hasFocus():
                # Let focus-out commit genuine edits before reformatting.
                QtCore.QTimer.singleShot(0,spin,spin.updateText)
        return False


def fit_number_display(spin):
    if not hasattr(spin,'_fitted_number_display'):
        spin._fitted_number_display=_FittedNumberDisplay(spin)
        spin.setStyleSheet(spin.styleSheet()+' QAbstractSpinBox {padding-left:3px;padding-right:3px;}')


class CheckButton(QtWidgets.QPushButton):
    """Text toggle retaining existing checkbox state signals and stored values."""
    stateChanged = QtCore.Signal(int)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setCheckable(True)
        self.setFixedHeight(30)
        self.setMinimumWidth(0)
        self.toggled.connect(lambda checked: self.stateChanged.emit(2 if checked else 0))

    def checkState(self):
        return QtCore.Qt.Checked if self.isChecked() else QtCore.Qt.Unchecked

    def setCheckState(self, state):
        self.setChecked(state == QtCore.Qt.Checked or state == 2)


class Stepper(QtWidgets.QWidget):
    def __init__(self, spin):
        super().__init__()
        self.spin = spin
        self.setObjectName("numberStepper")
        # The composite must reserve the same height as its input/buttons;
        # cached pre-polish size hints otherwise compress grid rows to 12px.
        self.setFixedHeight(30)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setProperty('compactSpacing', 4)
        layout.setSpacing(4)
        spin.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        spin.setKeyboardTracking(False)
        spin.setAlignment(QtCore.Qt.AlignCenter)
        spin.setMinimumWidth(42)
        self.buttons = []
        for text, direction in (("−", -1), ("+", 1)):
            button = QtWidgets.QToolButton(self)
            button.setText(text)
            button.setFixedWidth(24)
            button.setAutoRepeat(True)
            button.setFocusPolicy(QtCore.Qt.NoFocus)
            button.setAccessibleName("减小" if direction < 0 else "增大")
            button.clicked.connect(lambda checked=False, d=direction: spin.stepBy(d))
            self.buttons.append(button)
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.setMinimumWidth(36)
        self.slider.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
        )
        self.slider.setFocusPolicy(QtCore.Qt.NoFocus)
        self.slider.setToolTip("拖动调整数值；也可输入或使用减/加按钮")
        self.slider.valueChanged.connect(self.slide)
        spin.valueChanged.connect(self.sync_value)
        self.slider.installEventFilter(self)
        spin.setFixedWidth(72)
        layout.addWidget(self.slider, 1)
        layout.addWidget(spin)
        layout.addWidget(self.buttons[0])
        layout.addWidget(self.buttons[1])
        self.sync_value()
        spin.installEventFilter(self)
        style_slider_value(spin, self, spin.property("sliderUnit") or spin.suffix().strip())
        self.sync()

    def sync_value(self, *args):
        step = max(float(self.spin.singleStep()), 1e-12)
        self.slider_automatic=getattr(self.spin,'_automatic',False)
        self.slider_domain=getattr(self.spin,'_slider_domain',None)
        if self.slider_domain is not None:
            lo,hi,self.slider_log=self.slider_domain
            self.slider_low,self.slider_high=lo,hi
            self.slider_step=step
            value=float(self.spin.value())
            if self.slider_log:
                import math
                fraction=(math.log10(max(lo,value))-math.log10(lo))/(math.log10(hi)-math.log10(lo))
            else:fraction=(value-lo)/max(hi-lo,1e-300)
            offset=1 if self.slider_automatic else 0
            index=0 if self.slider_automatic and value<0 else offset+round(max(0,min(1,fraction))*1000)
            with QtCore.QSignalBlocker(self.slider):
                self.slider.setRange(0,1000+offset);self.slider.setValue(index)
            return
        self.slider_log=False
        minimum, maximum = self.spin.minimum(), self.spin.maximum()
        value = float(self.spin.value())
        if self.slider_automatic:
            minimum=step if getattr(self.spin,'_positive_auto',False) else 0
            self.slider_low,self.slider_high,self.slider_step=minimum,maximum,step
            with QtCore.QSignalBlocker(self.slider):
                self.slider.setRange(0,max(2,min(10001,round((maximum-minimum)/step)+1)))
                self.slider.setValue(0 if value<0 else max(1,1+round((value-minimum)/step)))
            return
        span = step * 10000
        limits = (minimum, maximum, step)
        if maximum - minimum > span:
            old_low = getattr(self, "slider_low", minimum)
            if (
                getattr(self, "_slider_limits", None) == limits
                and old_low <= value <= old_low + span
            ):
                lo = old_low
            else:
                lo = max(minimum, min(value - span / 2, maximum - span))
            hi = lo + span
        else:
            lo, hi = minimum, maximum
        self._slider_limits = limits
        self.slider_step = step
        self.slider_low = lo
        self.slider_high = hi
        with QtCore.QSignalBlocker(self.slider):
            self.slider.setRange(0, max(1, min(10000, round((hi - lo) / step))))
            self.slider.setValue(
                max(0, min(self.slider.maximum(), round((value - lo) / step)))
            )

    def slide(self, value):
        if self.slider_automatic and value==0:self.spin.setValue(-1);return
        offset=1 if self.slider_automatic else 0
        if self.slider_domain is not None:
            fraction=(value-offset)/1000
            lo,hi=self.slider_low,self.slider_high
            if self.slider_log:
                import math
                result=10**(math.log10(lo)+fraction*(math.log10(hi)-math.log10(lo)))
            else:result=lo+fraction*(hi-lo)
            if self.slider_automatic and 0<value<self.slider.maximum():
                result=round(result/self.slider_step)*self.slider_step
            self.spin.setValue(result)
        else:self.spin.setValue(self.slider_low+(value-offset)*self.slider_step)

    def sync(self):
        self.slider.setEnabled(self.spin.isEnabled())
        if hasattr(self,'value_unit_label'):self.value_unit_label.setEnabled(self.spin.isEnabled())
        for button in self.buttons:
            button.setEnabled(self.spin.isEnabled())

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.Wheel:
            event.ignore()
            return True
        if event.type() == QtCore.QEvent.EnabledChange:
            self.sync()
        return False


def stepper(spin, step=None):
    if isinstance(spin.parentWidget(), Stepper):
        return spin.parentWidget()
    if step is not None:
        spin.setSingleStep(step)
    return Stepper(spin)


class RichTextEdit(QtWidgets.QTextEdit):
    """Native multiline rich text with coalesced updates and explicit commit."""

    editingFinished = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptRichText(True)
        self.setContentsMargins(0, 0, 0, 0)
        self.document().setDocumentMargin(5)
        self.setFixedHeight(30)
        self.document().documentLayout().documentSizeChanged.connect(self.fit_content)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setTabChangesFocus(True)
        self._commit_timer = QtCore.QTimer(self)
        self._commit_timer.setSingleShot(True)
        self._commit_timer.setInterval(100)
        self._commit_timer.timeout.connect(self.commit)
        self._dirty=False
        self.textChanged.connect(self.schedule_commit)
        self.setToolTip('支持换行、选区格式、复制粘贴和撤销；Ctrl/⌘+Enter立即应用。')

    def schedule_commit(self):
        self._dirty=True;self._commit_timer.start()

    def commit(self):
        pending=self._dirty
        self._dirty=False;self._commit_timer.stop()
        if pending:self.editingFinished.emit()

    def fit_content(self, *args):
        import math

        frame = self.frameWidth() * 2
        # QSS padding belongs to the viewport, outside QTextDocument.size().
        chrome = max(frame, self.height() - self.viewport().height())
        needed=max(30,math.ceil(self.document().size().height())+chrome+2)
        height=min(180,needed)
        policy=QtCore.Qt.ScrollBarAsNeeded if needed>180 else QtCore.Qt.ScrollBarAlwaysOff
        if self.verticalScrollBarPolicy()!=policy:self.setVerticalScrollBarPolicy(policy)
        if self.height()!=height:self.setFixedHeight(height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_content()

    def keyPressEvent(self, event):
        if (event.key() in (QtCore.Qt.Key_Return,QtCore.Qt.Key_Enter)
                and event.modifiers() & (QtCore.Qt.ControlModifier|QtCore.Qt.MetaModifier)):
            self.commit();event.accept();return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.commit()

    def setText(self, value):
        from tailor.text_accents import restyle

        with QtCore.QSignalBlocker(self):
            self.setHtml(restyle(value, {}))
        self._commit_timer.stop();self._dirty=False
        self.fit_content()

    def load_plain_text(self, value):
        """Synchronize stored plain text without scheduling a user edit."""
        with QtCore.QSignalBlocker(self):
            self.setPlainText(value)
        self._commit_timer.stop()
        self._dirty = False
        self.fit_content()

    def text(self):
        # Do not serialize the editor's default font, which would override object styles.
        rows = []
        block = self.document().begin()
        while block.isValid():
            parts = []
            it = block.begin()
            while not it.atEnd():
                fragment = it.fragment()
                if fragment.isValid():
                    fmt = fragment.charFormat()

                    def format_part(value, fmt=fmt):
                        text = html.escape(value)
                        align = fmt.verticalAlignment()
                        if align == QtGui.QTextCharFormat.AlignSuperScript:
                            text = "<sup>" + text + "</sup>"
                        elif align == QtGui.QTextCharFormat.AlignSubScript:
                            text = "<sub>" + text + "</sub>"
                        if fmt.fontWeight() >= QtGui.QFont.Bold:
                            text = "<b>" + text + "</b>"
                        if fmt.fontItalic():
                            text = "<i>" + text + "</i>"
                        css = []
                        if fmt.hasProperty(QtGui.QTextFormat.FontWeight) and fmt.fontWeight()<QtGui.QFont.Bold:
                            css.append('font-weight:normal')
                        if fmt.hasProperty(QtGui.QTextFormat.FontItalic) and not fmt.fontItalic():
                            css.append('font-style:normal')
                        if fmt.hasProperty(QtGui.QTextFormat.TextUnderlineStyle) and not fmt.fontUnderline():
                            css.append('text-decoration:none')
                        if fmt.hasProperty(QtGui.QTextFormat.ForegroundBrush):
                            css.append("color:" + fmt.foreground().color().name())
                        if fmt.hasProperty(QtGui.QTextFormat.BackgroundBrush):
                            css.append(
                                "background-color:" + fmt.background().color().name()
                            )
                        if fmt.hasProperty(QtGui.QTextFormat.FontFamily) or fmt.hasProperty(QtGui.QTextFormat.FontFamilies):
                            css.append(
                                "font-family:"
                                + html.escape((fmt.fontFamilies() or [fmt.font().family()])[0], quote=True)
                            )
                        if fmt.hasProperty(QtGui.QTextFormat.FontPointSize):
                            css.append(f"font-size:{fmt.fontPointSize()}pt")
                        decorations = []
                        if fmt.fontUnderline():
                            decorations.append("underline")
                        if fmt.fontOverline():
                            decorations.append("overline")
                        if decorations:
                            css.append("text-decoration:" + " ".join(decorations))
                        if css:
                            text = (
                                '<span style="'
                                + ";".join(css)
                                + '">'
                                + text
                                + "</span>"
                            )
                        return text

                    if fmt.isImageFormat():
                        image = fmt.toImageFormat()
                        parts.append(
                            f'<img src="{html.escape(image.name(), quote=True)}" width="{image.width()}" height="{image.height()}">'
                        )
                        it += 1
                        continue
                    parts.append(
                        "<br>".join(
                            format_part(value)
                            for value in fragment.text().split("\u2028")
                        )
                    )
                it += 1
            rows.append("".join(parts))
            block = block.next()
        return "<br>".join(rows)

    def refresh_accents(self, spec=None):
        from tailor.text_accents import restyle

        text = self.text()
        if "data:image/png;base64," not in text:
            return
        style = spec or {"color": self.palette().color(QtGui.QPalette.Text).name()}
        updated = restyle(text, style)
        if updated == text:
            return
        cursor = self.textCursor()
        position, anchor = cursor.position(), cursor.anchor()
        with QtCore.QSignalBlocker(self):
            self.setHtml(updated)
            cursor = self.textCursor()
            length = self.document().characterCount() - 1
            cursor.setPosition(min(anchor, length))
            cursor.setPosition(min(position, length), QtGui.QTextCursor.KeepAnchor)
            self.setTextCursor(cursor)
        self.fit_content()

    def apply_script(self, kind):
        from tailor.text_layout import selected_letters,format_letters
        cursor=self.textCursor();letters=selected_letters(cursor)
        if not letters:return
        desired=QtGui.QTextCharFormat.AlignSuperScript if kind=='sup' else QtGui.QTextCharFormat.AlignSubScript
        formats=[]
        for pos,count,_ in letters:
            probe=QtGui.QTextCursor(self.document());probe.setPosition(pos);probe.setPosition(pos+count,QtGui.QTextCursor.KeepAnchor)
            formats.append(probe.charFormat().verticalAlignment())
        value=QtGui.QTextCharFormat.AlignNormal if all(a==desired for a in formats) else desired
        format_letters(cursor, lambda fmt, old:fmt.setVerticalAlignment(value))
        self.commit()


def toggle_button(text):
    button = QtWidgets.QPushButton(text)
    button.setCheckable(True)
    return button


def preference_button(kind, parent=None):
    from tailor.ui_theme import action_icon

    button = QtWidgets.QPushButton("字体偏好" if kind == "font" else "线条偏好", parent)
    button.setIcon(action_icon("font" if kind == "font" else "curve", button))
    button.setProperty("preferenceKind", kind)
    from tailor.appearance import manager

    manager().register_emphasis(button, kind)
    button.setToolTip(button.text())
    return button


def help_button(text):
    button = QtWidgets.QToolButton()
    button.setText("?")
    button.setToolTip("使用说明")
    button.setFixedSize(26, 30)
    from tailor.popup_controls import HelpPopup

    popup = HelpPopup(button)
    button._help_popup = popup
    popup.label.setText(text)
    button.clicked.connect(lambda: popup.open_at(button))
    return button


def equal_row(left, right):
    box = QtWidgets.QWidget()
    layout = QtWidgets.QHBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    for child in (left, right):
        if isinstance(child, QtWidgets.QAbstractButton):
            child.setFixedHeight(30)
        child.setMinimumWidth(0)
        child.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
        layout.addWidget(child, 1)
    return box


def card(title, content):
    frame = QtWidgets.QFrame()
    frame.setProperty("foldCard", True)
    frame.setAttribute(QtCore.Qt.WA_StyledBackground)
    layout = QtWidgets.QVBoxLayout(frame)
    layout.setContentsMargins(10, 10, 10, 10)
    layout.setSpacing(8)
    if title:
        heading = QtWidgets.QLabel(title)
        heading.setProperty("cardTitle", True)
        layout.addWidget(heading)
    if isinstance(content, QtWidgets.QLayout):
        layout.addLayout(content)
    else:
        layout.addWidget(content)
    from tailor.fold_panel import compact

    compact(frame)
    layout.setContentsMargins(10, 10, 10, 10)
    return frame


class IconChoices(QtWidgets.QWidget):
    """Icon buttons backed by the original combo values and signals."""

    def __init__(self, combo, icons):
        super().__init__()
        self.combo = combo
        combo.setParent(self)
        combo.hide()
        layout = QtWidgets.QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.setProperty('compactSpacing',4)
        self.buttons = []
        self.group = QtWidgets.QButtonGroup(self)
        for i in range(combo.count()):
            button = QtWidgets.QToolButton()
            button.setIcon(icons[i])
            button.setIconSize(QtCore.QSize(30, 22))
            button.setFixedSize(32, 30)
            button.setStyleSheet("QToolButton {padding:0;}")
            button.setToolTip(combo.itemText(i))
            button.setCheckable(True)
            self.group.addButton(button)
            self.buttons.append(button)
            layout.addWidget(button, i // 7, i % 7)
            button.clicked.connect(lambda checked=False, i=i: self.choose(i))
        columns=min(7,combo.count())
        self.setMinimumWidth(columns*32+max(0,columns-1)*4)
        combo.currentIndexChanged.connect(self.sync)
        combo.installEventFilter(self)
        self.sync()

    def sync(self, *args):
        for i, button in enumerate(self.buttons):
            button.setChecked(i == self.combo.currentIndex())
        for button in self.buttons:
            button.setEnabled(self.combo.isEnabledTo(self))

    def choose(self, i):
        self.combo.setCurrentIndex(i)
        self.combo.activated.emit(i)

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.EnabledChange:
            self.sync()
        return False


class FormatIcon(QtGui.QIconEngine):
    def __init__(self, kind):
        super().__init__()
        self.kind = kind

    def clone(self):
        return FormatIcon(self.kind)

    def paint(self, painter, rect, mode, state):
        role = (
            QtGui.QPalette.Dark if mode == QtGui.QIcon.Disabled else QtGui.QPalette.Text
        )
        color = QtWidgets.QApplication.palette().color(role)
        side = min(rect.width(), rect.height())
        painter.save()
        painter.translate(
            rect.x() + (rect.width() - side) / 2, rect.y() + (rect.height() - side) / 2
        )
        painter.scale(side / 48, side / 48)
        paint_format_icon(painter, self.kind, color)
        painter.restore()

    def pixmap(self, size, mode, state):
        pix = QtGui.QPixmap(size)
        pix.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pix)
        self.paint(painter, QtCore.QRect(QtCore.QPoint(), size), mode, state)
        painter.end()
        return pix


def format_icon(kind, widget):
    # Resolve ink at paint time; hidden editors may still have an old widget palette.
    return QtGui.QIcon(FormatIcon(kind))


def paint_format_icon(painter, kind, color):
    # Pixel-aligned explicit marks avoid combining-glyph clipping and tiny scripts.
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.setPen(QtGui.QPen(color, 2.2))
    font = QtGui.QFont("Arial")
    font.setPixelSize(29)
    font.setBold(kind == "bold")
    font.setItalic(kind == "italic")
    painter.setFont(font)
    text = {
        "bold": "B",
        "italic": "I",
        "underline": "U",
        "overline": "x",
        "wave": "x",
        "dot": "x",
        "greek": "Ω",
        "clear": "T",
        "sup": "x",
        "sub": "x",
    }[kind]
    rect = QtCore.QRectF(7, 7, 31, 34)
    if kind in {"sup", "sub"}:
        rect = QtCore.QRectF(3, 9, 28, 34)
    painter.drawText(rect, QtCore.Qt.AlignCenter, text)
    if kind == "underline":
        painter.drawLine(10, 41, 35, 41)
    elif kind == "overline":
        painter.drawLine(11, 10, 35, 10)
    elif kind == "wave":
        path = QtGui.QPainterPath()
        path.moveTo(11, 9)
        path.cubicTo(18, 1, 27, 17, 36, 9)
        painter.drawPath(path)
    elif kind == "dot":
        painter.setBrush(painter.pen().color())
        painter.drawEllipse(QtCore.QPointF(23, 8), 2.5, 2.5)
    elif kind == "clear":
        painter.drawLine(29, 30, 42, 43)
        painter.drawLine(42, 30, 29, 43)
    elif kind in {"sup", "sub"}:
        font.setPixelSize(18)
        painter.setFont(font)
        painter.drawText(
            QtCore.QRectF(29, 2 if kind == "sup" else 27, 18, 21),
            QtCore.Qt.AlignCenter,
            "2",
        )


def point_selection_grid(single, continuous, locate, copy, details=None):
    """One shared grid keeps both selection rows on precisely the same columns."""
    from tailor.graph_controls import row

    box = QtWidgets.QWidget()
    grid = QtWidgets.QGridLayout(box)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setSpacing(7)
    help = help_button(
        "单点：点击一个真实点；连续：依次点击起点和终点，按源数据行选择。"
    )
    help.setFixedWidth(26)
    help.setObjectName('pointSelectionHelp')
    help.setParent(box)
    help.hide()
    for widget in (single, continuous, locate, copy):
        widget.setMinimumWidth(0)
        widget.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
    grid.addWidget(single, 0, 0)
    grid.addWidget(continuous, 0, 1)
    if details is not None:grid.addWidget(details,1,0,1,2)
    grid.addWidget(locate, 2, 0)
    grid.addWidget(copy, 2, 1)
    grid.setColumnStretch(0, 1)
    grid.setColumnStretch(1, 1)
    return box


class SplitHideButton(QtWidgets.QWidget):
    """Two standard Qt buttons; the restore arrow remains usable without selection."""

    clicked = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setProperty("compactSpacing", 0)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.main = QtWidgets.QPushButton()
        self.main.setObjectName("splitHideMain")
        self.main.setMinimumWidth(0)
        self.main.setSizePolicy(
            QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed
        )
        self.arrow = QtWidgets.QToolButton()
        self.arrow.setObjectName("splitHideArrow")
        self.arrow.setFixedWidth(26)
        self.setFixedHeight(30)
        for button in (self.main, self.arrow):
            button.setFixedHeight(30)
            button.setStyleSheet("QPushButton#splitHideMain, QToolButton#splitHideArrow {border:0; border-radius:0; background:transparent; padding:0; margin:0; min-height:0;} QPushButton#splitHideMain:disabled {background:transparent;}")
        self.main.clicked.connect(self.clicked)
        self.arrow.clicked.connect(self.open_menu)
        layout.addWidget(self.main, 1)
        layout.addWidget(self.arrow)
        self._menu = None
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        from tailor.appearance import manager

        manager().changed.connect(self.refresh_icon)
        self.refresh_icon()

    def refresh_icon(self):
        from tailor.ui_theme import action_icon

        self.arrow.setIcon(
            action_icon("down", self, self.palette().color(QtGui.QPalette.Text).name())
        )
        self.arrow.setIconSize(QtCore.QSize(16, 12))
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setPen(QtGui.QPen(self.palette().color(QtGui.QPalette.Mid), 1))
        painter.setBrush(self.palette().color(QtGui.QPalette.Button))
        painter.drawRoundedRect(QtCore.QRectF(self.rect()).adjusted(.5,.5,-.5,-.5), 5, 5)
        x = self.width() - self.arrow.width()
        painter.drawLine(x, 1, x, self.height()-2)

    def setText(self, text):
        self.main.setText(text)

    def text(self):
        return self.main.text()

    def setEnabled(self, enabled):
        self.main.setEnabled(enabled)

    def setMenu(self, menu):
        self._menu = menu

    def open_menu(self):
        if self._menu:
            self._menu.setFixedWidth(self.width())
            self._menu.popup(self.mapToGlobal(QtCore.QPoint(0, self.height())))


def style_numeric_value(field):
    """Shared neutral number surface; action buttons retain their outlines."""
    css = ("background:palette(alternate-base);border:1px solid transparent;"
           "border-radius:5px;padding:3px 4px;font-weight:400;color:palette(text);")
    disabled = "background:palette(alternate-base);color:palette(dark);border-color:transparent;"
    selector = "QAbstractSpinBox" if isinstance(field,QtWidgets.QAbstractSpinBox) else "QLineEdit"
    field.setStyleSheet(selector+" {"+css+"} "+selector+":focus {border-color:palette(link);} "+selector+":disabled {"+disabled+"}"+
                       (" QAbstractSpinBox QLineEdit {border:0;background:transparent;padding:0;}" if isinstance(field,QtWidgets.QAbstractSpinBox) else ""))
    field.setProperty('numericValueFrame', True)


def style_slider_value(spin, slider, unit=""):
    style_numeric_value(spin)
    spin.setProperty('sliderUnit',unit)
    spin.setSuffix("")
    spin.setFixedWidth(max(64,spin.fontMetrics().horizontalAdvance('99.9')+24))
    label=getattr(slider, 'value_unit_label', None)
    if label is not None:
        label.setText(unit)
        label.setFixedWidth(max(24,label.fontMetrics().horizontalAdvance(unit)))
        return label
    label=QtWidgets.QLabel(unit, slider)
    slider.value_unit_label=label
    label.setProperty('muted',True)
    # Empty-unit rows reserve the same column as px/% rows so sibling sliders
    # keep identical start/end positions (ticks and broken axes in particular).
    label.setFixedWidth(max(24,label.fontMetrics().horizontalAdvance(unit)))
    layout=slider.layout()
    layout.insertWidget(layout.indexOf(spin)+1,label)
    return label


class MultiParameter(QtWidgets.QWidget):
    """Existing numeric controls sharing the same buttons, fields and slider."""
    def __init__(self, sources, names, units=None, row_label=None, automatic=False):
        super().__init__()
        self.sources=list(sources);self.values=self.sources
        self.current=0;self.loading=False;self.automatic=automatic
        self.units=list(units or ['']*len(sources))
        self.setMinimumWidth(0)
        layout=QtWidgets.QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(7)
        heading=QtWidgets.QWidget();line=QtWidgets.QHBoxLayout(heading)
        self.headings=[heading]
        line.setContentsMargins(0,0,0,0);line.setSpacing(5)
        self.group=QtWidgets.QButtonGroup(self);self.buttons=[];self.labels=[]
        for i,name in enumerate(names):
            if len(sources)>3 and i and i%2==0:
                layout.addWidget(heading)
                heading=QtWidgets.QWidget();line=QtWidgets.QHBoxLayout(heading)
                self.headings.append(heading)
                line.setContentsMargins(0,0,0,0);line.setSpacing(5)
            button=toggle_button(name);button.setMinimumWidth(0)
            button.setStyleSheet('QPushButton {padding:3px;}')
            self.group.addButton(button);self.buttons.append(button)
            button.clicked.connect(lambda checked=False,i=i:self.choose(i))
            field=QtWidgets.QLineEdit();field.setAlignment(QtCore.Qt.AlignCenter)
            field.setFixedWidth(44 if len(sources)==3 else 58)
            field.setPlaceholderText('Auto' if automatic else '')
            field.editingFinished.connect(lambda i=i:self.enter(i));self.labels.append(field)
            line.addWidget(button,1);line.addWidget(field)
        self.fields=self.labels;layout.addWidget(heading)
        self.editor=CompactDoubleSpinBox();self.stepper=stepper(self.editor);self.editor.setFixedWidth(72)
        from tailor.graph_controls import row
        self.slider_row=row(row_label,self.stepper) if row_label else self.stepper
        self.slider_title=self.slider_row.findChild(QtWidgets.QLabel) if row_label else None
        layout.addWidget(self.slider_row)
        self.editor.valueChanged.connect(self.change)
        self.editor.editingFinished.connect(self.commit_editor)
        self.stepper.slider.sliderReleased.connect(self.commit_editor)
        for button in self.stepper.buttons:
            button.clicked.connect(self.commit_editor)
        for source in self.sources:
            source.setParent(self);source.hide();source.valueChanged.connect(self.sync)
        self.choose(0)
        self.use_numeric_value_style()
        # A fitting page can move between stacked graph inspectors. Qt's
        # layout cache may still carry the pre-polish field heights,
        # allocating less than the two 30 px rows and clipping their children.
        # Retain the existing row height without imposing a content min width.
        for heading in self.headings:
            heading.setFixedHeight(30)
        self.slider_row.setFixedHeight(30)
        self.setMinimumHeight(30*(len(self.headings)+1)+layout.spacing()*len(self.headings))

    def use_numeric_value_style(self):
        """Opt-in sample: quiet filled number inputs, with units outside them."""
        if getattr(self, "_external_units", False):
            return
        self._external_units = True
        self.unit_labels = []
        for field, unit in zip(self.fields, self.units):
            style_numeric_value(field)
            field.setFixedWidth(44 if len(self.sources)==3 else max(54,field.fontMetrics().horizontalAdvance('99.9')+18))
            line = field.parentWidget().layout()
            # Parent before showing: a unit label without a parent is a native
            # top-level window on macOS. Showing then reparenting dozens of
            # these windows blocks setup and steals focus from the graph.
            label = QtWidgets.QLabel(unit, field.parentWidget())
            label.setProperty('muted', True)
            line.insertWidget(line.indexOf(field)+1,label)
            label.setVisible(bool(unit))
            self.unit_labels.append(label)
        self.editor_unit = style_slider_value(self.editor,self.stepper,self.units[self.current])
        self.sync()

    def choose(self,index):
        self.current=index;self.sync()

    def changeEvent(self,event):
        super().changeEvent(event)
        if event.type()==QtCore.QEvent.EnabledChange and hasattr(self,'editor'):self.sync()

    def sync(self,*args):
        value=self.sources[self.current]
        self.loading=True
        with QtCore.QSignalBlocker(self.editor):
            self.editor._automatic=self.automatic
            self.editor._positive_auto=getattr(value,"_positive_auto",False)
            self.editor._slider_domain=getattr(value,'_slider_domain',None)
            self.editor.setRange(-1 if self.automatic else value.minimum(),value.maximum())
            self.editor.setDecimals(getattr(value,'decimals',lambda:0)());self.editor.setSingleStep(value.singleStep())
            unit=self.units[self.current]
            self.editor.setSuffix(' '+unit if unit and not getattr(self,'_external_units',False) else '')
            self.editor.setValue(value.value())
        self.stepper.sync_value()
        self.group.setExclusive(False)
        for i,(button,field,source) in enumerate(zip(self.buttons,self.labels,self.sources)):
            button.setEnabled(source.isEnabled())
            button.setChecked(i==self.current and source.isEnabled())
            field.setText('Auto' if self.automatic and source.value()<0 else f'{source.value():g}'+((' '+self.units[i]) if self.units[i] and not getattr(self,'_external_units',False) else ''))
            field.setEnabled(i==self.current and source.isEnabled())
        self.group.setExclusive(True)
        self.editor.setEnabled(value.isEnabled())
        if getattr(self,'_external_units',False):
            self.editor_unit.setText(self.units[self.current])
            for label,unit,source in zip(self.unit_labels,self.units,self.sources):
                label.setText(unit);label.setVisible(bool(unit));label.setEnabled(source.isEnabled())
        self.loading=False

    def enter(self,index):
        source=self.sources[index];text=self.labels[index].text().strip()
        unit=self.units[index]
        if unit and text.endswith(unit):text=text[:-len(unit)].strip()
        try:
            value=-1 if self.automatic and text.lower() in {'','auto','自动'} else float(text)
            if not (source.minimum()<=value<=source.maximum()) or (self.automatic and value<0 and value!=-1):
                self.sync();return
            if getattr(source,"_positive_auto",False) and value==0:value=-1
            source.setValue(value if isinstance(source,QtWidgets.QDoubleSpinBox) else int(value));self.choose(index)
        except ValueError:self.sync()

    def sync_value(self,*args):self.sync()

    def change(self,value):
        if not self.loading:
            source=self.sources[self.current]
            if getattr(source,"_positive_auto",False) and value==0:
                source.setValue(-1);self.sync();return
            source.setValue(value if isinstance(source,QtWidgets.QDoubleSpinBox) else int(value))

    def commit_editor(self, *args):
        # In auto mode the source is -1 while the editor is already at zero;
        # an explicit zero still needs committing even without valueChanged.
        self.change(self.editor.value())


class DualParameter(MultiParameter):
    def __init__(self,first,second,first_name,second_name,suffix='%',row_label=None):
        super().__init__([first,second],[first_name,second_name],[suffix,suffix],row_label)


class ArrowParameter(QtWidgets.QWidget):
    """One compact row of direction/value buttons over a shared slider."""
    chosen=QtCore.Signal(str)
    def __init__(self,low,high,decimals=0,parent=None):
        super().__init__(parent)
        layout=QtWidgets.QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(7)
        line=QtWidgets.QHBoxLayout();line.setSpacing(7)
        self.buttons={};self.glyphs={'up':'↑','down':'↓','left':'←','right':'→'}
        self.group=QtWidgets.QButtonGroup(self)
        for key,glyph in self.glyphs.items():
            button=toggle_button(glyph);button.setMinimumWidth(0);button.setStyleSheet('QPushButton {padding:3px;}')
            self.group.addButton(button);self.buttons[key]=button;line.addWidget(button,1)
            button.clicked.connect(lambda checked=False,key=key:self.chosen.emit(key))
        layout.addLayout(line)
        self.value=CompactDoubleSpinBox();self.value.setRange(low,high);self.value.setDecimals(decimals);self.value.setSingleStep(1)
        self.stepper=stepper(self.value)
        self.unit_label=style_slider_value(self.value,self.stepper,'px')
        layout.addWidget(self.stepper)
    def sync(self,values,current):
        for key,button in self.buttons.items():
            # Button captions are a quick whole-pixel readout. The native spin
            # box retains the underlying coordinate and its configured precision.
            button.setText(f'{self.glyphs[key]} {int(round(float(values[key])))}');button.setChecked(key==current)
        with QtCore.QSignalBlocker(self.value):self.value.setValue(values[current or 'left'])
        self.stepper.sync_value()


def aligned_slider_rows(rows,parent=None):
    """Give sibling sliders a single label column and identical right columns."""
    box=QtWidgets.QWidget(parent);grid=QtWidgets.QGridLayout(box)
    grid.setContentsMargins(0,0,0,0);grid.setHorizontalSpacing(8);grid.setVerticalSpacing(7)
    grid.setColumnStretch(1,1)
    for index,(title,control) in enumerate(rows):
        label=title if isinstance(title,QtWidgets.QWidget) else QtWidgets.QLabel(title)
        grid.addWidget(label,index,0)
        grid.setRowMinimumHeight(index,30)
        grid.addWidget(control,index,1)
    box.setMinimumHeight(30*len(rows)+grid.verticalSpacing()*max(0,len(rows)-1))
    return box

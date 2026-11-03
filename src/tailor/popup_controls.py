"""Bounded list popups for Qt combo boxes."""

import shiboken6
from PySide6 import QtCore, QtGui, QtWidgets
from tailor.crash_diagnostics import valid_event


def section_colors():
    from tailor.appearance import manager

    return ('#262a30', '#e3e8ef') if manager().dark() else ('#eef0f3', '#3e4b5b')


def style_section_label(label):
    label.setProperty('choiceSection', True)
    background, foreground = section_colors()
    css = f'QLabel {{background:{background};color:{foreground};border-radius:4px;font-weight:600;text-decoration:underline;}}'
    if label.styleSheet() != css:
        label.setStyleSheet(css)


def inspector_for(widget):
    """Resolve a functional inspector, excluding in-table column editors."""
    node=widget
    while node is not None:
        if isinstance(node,QtWidgets.QTableView):return None
        if type(node).__name__=='PreferenceHost':return node
        host=getattr(node,'preferences',None)
        if isinstance(host,QtWidgets.QWidget):return host
        tabs=getattr(node,'property_tabs',None)
        if isinstance(tabs,QtWidgets.QTabWidget):return tabs
        node=node.parentWidget()
    return None


def fit_menu(menu):
    # Keep QMenu's original mouse/column anchor, adapting only readable width.
    screen=menu.screen().availableGeometry()
    widths=[menu.fontMetrics().horizontalAdvance(action.text().replace('&','')) for action in menu.actions()]
    width=min(screen.width()-12,max(120,max(widths,default=0)+72))
    menu.setFixedWidth(width)
    # Row padding can change on first Show. Fit the current style's actual
    # height too, rather than keeping the native pre-polish compact rectangle.
    height=min(screen.height()-12,menu.sizeHint().height())
    menu.resize(width,height)
    pos=menu.pos();pos.setX(max(screen.left()+6,min(pos.x(),screen.right()-width-5)))
    pos.setY(max(screen.top()+6,min(pos.y(),screen.bottom()-height-5)))
    menu.move(pos)


def round_popup(widget):
    if not widget.isWindow():
        return
    from tailor.appearance import manager

    dark = manager().dark()
    bg, edge = ("#000000", "#30343a") if dark else ("#ffffff", "#d5dce5")
    widget.setObjectName("roundedChoicePopup")
    widget.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
    if isinstance(widget, QtWidgets.QFrame):
        widget.setFrameShape(QtWidgets.QFrame.NoFrame)
    css = f"QWidget#roundedChoicePopup {{ background: {bg}; border: 1px solid {edge}; border-radius: 8px; padding: 4px; }}"
    if isinstance(widget,QtWidgets.QMenu):
        for action in widget.actions():
            if action.isSeparator() and action.text():
                action.setSeparator(False);action.setEnabled(False);action.setProperty('choiceSection',True)
            if action.property('choiceSection') and not action.font().underline():
                font=QtGui.QFont(action.font());font.setBold(True);font.setUnderline(True);action.setFont(font)
        css += " QMenu::item {padding:8px 8px;min-height:18px;} QMenu::separator {height:7px;margin:0 8px;} QMenu::section {padding:8px 8px;min-height:18px;font-weight:600;text-decoration:underline;}"
    if widget.styleSheet() != css:
        widget.setStyleSheet(css)
    # A QRegion mask has integer-pixel edges and visibly stair-steps on HiDPI.
    # The existing antialiased popup painter provides the transparent corners.
    widget.clearMask()
    widget.setAutoFillBackground(False)


class HelpPopup(QtWidgets.QFrame):
    def __init__(self, owner):
        super().__init__(owner, QtCore.Qt.Popup | QtCore.Qt.FramelessWindowHint)
        self.setFixedWidth(330)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        self.label = QtWidgets.QLabel()
        self.label.setWordWrap(True)
        layout.addWidget(self.label)

    def open_at(self, button):
        import weakref

        self._anchor = weakref.ref(button)
        self.fit_content()
        self.show()

    def fit_content(self):
        button = self._anchor()
        if button is None or not shiboken6.isValid(button):
            return
        round_popup(self)
        self.ensurePolished()
        screen = button.screen().availableGeometry()
        width = min(330, screen.width()-12)
        while True:
            self.setFixedWidth(width)
            outer, inner = self.contentsMargins(), self.layout().contentsMargins()
            text_width = max(40, width-outer.left()-outer.right()-inner.left()-inner.right())
            for label in self.findChildren(QtWidgets.QLabel):
                if label is not self.label and label.isHidden():
                    continue
                label.setMaximumHeight(16777215)
                label.setMinimumHeight(0)
                label.setMinimumHeight(max(label.fontMetrics().height(), label.heightForWidth(text_width)))
            self.layout().invalidate(); self.layout().activate()
            height = self.layout().totalHeightForWidth(width)
            if height < 0:height = self.layout().sizeHint().height()
            height += outer.top()+outer.bottom()
            if height <= screen.height()-12 or width >= screen.width()-12:
                break
            width = min(screen.width()-12, width+120)
        self.setFixedHeight(height)
        pos = button.mapToGlobal(QtCore.QPoint(0, button.height() + 4))
        if pos.y()+height > screen.bottom()-6:
            pos.setY(button.mapToGlobal(QtCore.QPoint()).y()-height-4)
        pos.setX(
            max(screen.left() + 4, min(pos.x(), screen.right() - self.width() - 4))
        )
        pos.setY(
            max(screen.top() + 4, min(pos.y(), screen.bottom() - self.height() - 4))
        )
        self.move(pos)

    def event(self, event):
        result = super().event(event)
        if event.type() == QtCore.QEvent.LayoutRequest and self.isVisible() and hasattr(self, '_anchor'):
            if not getattr(self, '_fit_pending', False):
                self._fit_pending = True
                QtCore.QTimer.singleShot(0, self, self.refit)
        return result

    def refit(self):
        self._fit_pending = False
        if self.isVisible():
            self.fit_content()


class ChoiceDelegate(QtWidgets.QStyledItemDelegate):
    def __init__(self, combo, parent):
        super().__init__(parent)
        self.combo = combo

    def paint(self, painter, option, index):
        opt = QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        icon = index.data(QtCore.Qt.DecorationRole) or QtGui.QIcon()
        opt.text = ""
        opt.icon = QtGui.QIcon()
        opt.features &= ~QtWidgets.QStyleOptionViewItem.HasCheckIndicator
        style = opt.widget.style() if opt.widget else QtWidgets.QApplication.style()
        style.drawControl(QtWidgets.QStyle.CE_ItemViewItem, opt, painter, opt.widget)
        painter.save()
        role = (QtGui.QPalette.HighlightedText
                if opt.state & QtWidgets.QStyle.State_Selected else QtGui.QPalette.Text)
        painter.setPen(opt.palette.color(role))
        rect = opt.rect.adjusted(8, 0, -26, 0)
        if not icon.isNull():
            icon.paint(painter, QtCore.QRect(rect.left(), rect.center().y()-8, 32, 16))
            rect.adjust(40, 0, 0, 0)
        painter.drawText(rect, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
                         opt.fontMetrics.elidedText(text, QtCore.Qt.ElideRight, max(0, rect.width())))
        if index.row() == self.combo.currentIndex():
            painter.drawText(opt.rect.adjusted(0, 0, -8, 0),
                             QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter, "✓")
        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(max(34, size.height()))
        size.setWidth(
            size.width()
            + (50 if not index.data(QtCore.Qt.DecorationRole) is None else 32)
        )
        return size


class FullChoiceView(QtWidgets.QListView):
    def __init__(self,combo):
        super().__init__(combo)
        import weakref
        self.combo_ref=weakref.ref(combo)
    def showEvent(self, event):
        super().showEvent(event)
        round_popup(self.window())
        QtCore.QTimer.singleShot(0, self, self.fit_short_list)

    def fit_short_list(self):
        if not self.isVisible() or self.model() is None:
            return
        count = self.model().rowCount()
        if count == 0:
            return
        # A compact editor must not constrain the popup's readable text width.
        text_width = max(
            self.fontMetrics().horizontalAdvance(
                str(self.model().index(i, 0).data() or "")
            )
            for i in range(count)
        )
        needed = min(count, 30) * max(1, self.sizeHintForRow(0))
        popup = self.window()
        screen = popup.screen().availableGeometry()
        extra = max(0, needed - self.viewport().height())
        height = min(screen.height() - 12, popup.height() + extra)
        combo=self.combo_ref()
        if combo is None:return
        decorated=any(self.model().index(i,0).data(QtCore.Qt.DecorationRole) is not None for i in range(count))
        width = min(screen.width() - 12, max(combo.width(),120,text_width+(120 if decorated else 56)))
        self.setMinimumWidth(width-8);self.setMaximumWidth(width-8)
        self.updateGeometry()
        popup.setFixedWidth(width)
        popup.resize(width, height)
        left=combo.mapToGlobal(QtCore.QPoint()).x()
        popup.move(
            min(max(left, screen.left() + 6), screen.right() - width - 5),
            min(max(popup.y(), screen.top() + 6), screen.bottom() - height - 5),
        )
        if needed <= height:
            self.scrollToTop()
        round_popup(popup)


def configure_combo(combo):
    if getattr(combo, "_list_popup_configured", False):
        return
    combo._list_popup_configured = True
    # Qt's stylesheet style hint avoids replacing/owning native QStyle objects.
    # https://github.com/qt/qtbase/blob/v6.9.3/src/widgets/styles/qstylesheetstyle.cpp
    combo.setStyleSheet(combo.styleSheet() + "\nQComboBox { combobox-popup: 0; }\nQComboBox QLineEdit { border:0; padding:0; background:transparent; min-height:0; }")
    view = FullChoiceView(combo)
    view.setUniformItemSizes(True)
    view.setItemDelegate(ChoiceDelegate(combo, view))
    view.setFrameShape(QtWidgets.QFrame.NoFrame)
    view.setViewportMargins(4, 4, 4, 4)
    view.setStyleSheet("QListView { background: transparent; border: 0; }")
    view.viewport().setAutoFillBackground(False)
    view.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    view.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
    combo.setMaxVisibleItems(30)
    combo.setView(view)


def paint_combo(combo):
    """Use one left origin for native, placeholder and icon-bearing choices."""
    painter = QtWidgets.QStylePainter(combo)
    option = QtWidgets.QStyleOptionComboBox()
    combo.initStyleOption(option)
    text, icon = option.currentText, option.currentIcon
    option.currentText, option.currentIcon = '', QtGui.QIcon()
    painter.drawComplexControl(QtWidgets.QStyle.CC_ComboBox, option)
    rect = combo.rect().adjusted(8, 0, -30, 0)
    if combo.property('columnRole'):
        arrow=combo.style().subControlRect(QtWidgets.QStyle.CC_ComboBox,option,QtWidgets.QStyle.SC_ComboBoxArrow,combo)
        rect=combo.rect().adjusted(5,0,0,0)
        rect.setRight(arrow.left()-4)
    if not icon.isNull():
        icon.paint(painter, QtCore.QRect(rect.left(), rect.center().y()-8, 32, 16))
        rect.adjust(40, 0, 0, 0)
    group = QtGui.QPalette.Active if combo.isEnabled() else QtGui.QPalette.Disabled
    painter.setPen(combo.palette().color(group, QtGui.QPalette.Text))
    painter.drawText(rect, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
                     painter.fontMetrics().elidedText(text, QtCore.Qt.ElideRight, max(0, rect.width())))
    painter.end()


def paint_choice_menu(menu):
    """Adapt existing multi-select QMenus to the same text/check columns."""
    painter = QtWidgets.QStylePainter(menu)
    panel = QtWidgets.QStyleOption()
    panel.initFrom(menu)
    painter.drawPrimitive(QtWidgets.QStyle.PE_PanelMenu, panel)
    for action in menu.actions():
        if not action.isVisible():
            continue
        option = QtWidgets.QStyleOptionMenuItem()
        menu.initStyleOption(option, action)
        option.rect = menu.actionGeometry(action)
        text, icon, checked = option.text, option.icon, action.isChecked()
        section = (action.isSeparator() and bool(text)) or bool(action.property('choiceSection'))
        if section:
            option.menuItemType = QtWidgets.QStyleOptionMenuItem.Normal
            option.state &= ~QtWidgets.QStyle.State_Selected
        option.text, option.icon = '', QtGui.QIcon()
        option.checkType = QtWidgets.QStyleOptionMenuItem.NotCheckable
        option.checked = False
        painter.drawControl(QtWidgets.QStyle.CE_MenuItem, option)
        if action.isSeparator() and not section:
            continue
        painter.save()
        font=QtGui.QFont(option.font)
        if section:
            font.setBold(True);font.setUnderline(True)
            background, foreground = section_colors()
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor(background))
            painter.drawRoundedRect(QtCore.QRectF(option.rect).adjusted(2,2,-2,-2),4,4)
        painter.setFont(font)
        group = QtGui.QPalette.Active if action.isEnabled() else QtGui.QPalette.Disabled
        role = QtGui.QPalette.HighlightedText if option.state & QtWidgets.QStyle.State_Selected else QtGui.QPalette.Text
        painter.setPen(QtGui.QColor(foreground) if section else option.palette.color(group, role))
        rect = option.rect.adjusted(8, 0, -26, 0)
        if not icon.isNull():
            icon.paint(painter, QtCore.QRect(rect.left(), rect.center().y()-8, 32, 16))
            rect.adjust(40, 0, 0, 0)
        painter.drawText(rect, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
                         painter.fontMetrics().elidedText(text, QtCore.Qt.ElideRight, max(0, rect.width())))
        if checked:
            painter.drawText(option.rect.adjusted(0, 0, -8, 0), QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter, '✓')
        painter.restore()
    painter.end()


def paint_choice_button(button):
    painter = QtWidgets.QStylePainter(button)
    option = QtWidgets.QStyleOptionToolButton()
    button.initStyleOption(option)
    text = option.text
    option.text, option.icon = '', QtGui.QIcon()
    painter.drawComplexControl(QtWidgets.QStyle.CC_ToolButton, option)
    group = QtGui.QPalette.Active if button.isEnabled() else QtGui.QPalette.Disabled
    painter.setPen(button.palette().color(group, QtGui.QPalette.ButtonText))
    rect = button.rect().adjusted(8, 0, -30, 0)
    painter.drawText(rect, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
                     painter.fontMetrics().elidedText(text, QtCore.Qt.ElideRight, max(0, rect.width())))
    painter.end()


class PopupPolicy(QtCore.QObject):
    def eventFilter(self, watched, event):
        if not valid_event(event, 'PopupPolicy'):
            return True
        kind=event.type()
        if kind not in (QtCore.QEvent.Paint,QtCore.QEvent.Show,QtCore.QEvent.Resize,QtCore.QEvent.Polish,QtCore.QEvent.StyleChange):return False
        if (kind in (QtCore.QEvent.Show,QtCore.QEvent.StyleChange)
                and isinstance(watched,QtWidgets.QLabel) and watched.property('choiceSection')):
            style_section_label(watched)
        if (kind == QtCore.QEvent.Paint and isinstance(watched,QtWidgets.QMenu)
                and any((a.isSeparator() and a.text()) or a.property('choiceSection') for a in watched.actions())):
            paint_choice_menu(watched)
            return True
        if (kind == QtCore.QEvent.Paint and isinstance(watched, QtWidgets.QToolButton)
                and watched.property('choiceField')):
            paint_choice_button(watched)
            return True
        if isinstance(watched, QtWidgets.QComboBox):
            if kind == QtCore.QEvent.Paint and not watched.isEditable():
                paint_combo(watched)
                return True
            if watched.isEditable() and watched.lineEdit() is not None:
                alignment = QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter
                if watched.lineEdit().alignment() != alignment:
                    watched.lineEdit().setAlignment(alignment)
        if (
            kind == QtCore.QEvent.Paint
            and isinstance(watched, QtWidgets.QWidget)
            and watched.objectName() == "roundedChoicePopup"
            and not isinstance(watched, QtWidgets.QMenu)
        ):
            from tailor.appearance import manager

            dark = manager().dark()
            painter = QtGui.QPainter(watched)
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            painter.setPen(
                QtGui.QPen(QtGui.QColor("#30343a" if dark else "#d5dce5"), 1)
            )
            painter.setBrush(QtGui.QColor("#000000" if dark else "#ffffff"))
            painter.drawRoundedRect(
                QtCore.QRectF(watched.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8
            )
            painter.end()
            return True
        if (
            kind in (QtCore.QEvent.Show, QtCore.QEvent.Resize)
            and isinstance(watched, QtWidgets.QWidget)
            and (
                isinstance(watched, QtWidgets.QMenu)
                or watched.objectName() == "roundedChoicePopup"
            )
        ):
            round_popup(watched)
            if isinstance(watched,QtWidgets.QMenu) and kind==QtCore.QEvent.Show:
                QtCore.QTimer.singleShot(0,watched,lambda:fit_menu(watched) if shiboken6.isValid(watched) else None)
        if (
            kind == QtCore.QEvent.Show
            and isinstance(watched, QtWidgets.QComboBox)
            and not getattr(watched, "_list_popup_configured", False)
            and not getattr(watched, "_popup_pending", False)
        ):
            watched._popup_pending = True
            # Never replace a popup/style inside Qt's polish/paint dispatch.
            QtCore.QTimer.singleShot(
                0, watched,
                lambda: (
                    configure_combo(watched) if shiboken6.isValid(watched) else None
                ),
            )
        return False


def install_popup_policy(window):
    app = QtWidgets.QApplication.instance()
    if not hasattr(app, "_popup_policy"):
        app._popup_policy = PopupPolicy(app)
        app.installEventFilter(app._popup_policy)
    for combo in window.findChildren(QtWidgets.QComboBox):
        configure_combo(combo)

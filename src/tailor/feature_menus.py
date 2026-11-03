"""Native macOS menus forwarding to the existing inspector widgets."""

from PySide6 import QtWidgets


def control_name(widget):
    if widget.accessibleName():
        return widget.accessibleName()
    child = widget
    parent = widget.parentWidget()
    fallback = None
    while parent is not None:
        layout = parent.layout()
        if isinstance(layout, QtWidgets.QFormLayout):
            label = layout.labelForField(child)
            if label is not None:
                return label.text()
        if layout is not None and fallback is None:
            for i in range(layout.count()):
                label = layout.itemAt(i).widget()
                if isinstance(label, QtWidgets.QLabel) and label.property("fieldLabel"):
                    fallback = label.text()
                    break
        if parent.property("foldCard"):
            break
        child = parent
        parent = parent.parentWidget()
    return (
        fallback
        or widget.accessibleName()
        or widget.toolTip().split("；")[0]
        or "编辑数值"
    )


def populate_controls(menu, content):
    if not hasattr(menu, "_curve_children"):
        menu._curve_children = []
    for widget in [content, *content.findChildren(QtWidgets.QWidget)]:
        if widget.isHidden() or widget.property("sectionTitle"):
            continue
        if isinstance(widget, QtWidgets.QAbstractButton):
            name = widget.text() or widget.accessibleName() or widget.toolTip()
            if not name:
                continue
            if (
                widget.parentWidget()
                and widget.parentWidget().objectName() == "numberStepper"
            ):
                continue
            source_menu = widget.menu() if hasattr(widget, "menu") else None
            if source_menu is not None:
                # Cocoa omits an empty menu before aboutToShow can populate it.
                source_menu.aboutToShow.emit()
                source_menu.setTitle(name)
                menu.addMenu(source_menu)
                menu._curve_children.append(source_menu)
                if (
                    isinstance(widget, QtWidgets.QToolButton)
                    and widget.popupMode() == QtWidgets.QToolButton.InstantPopup
                ):
                    continue
            action = menu.addAction(widget.icon(), name)
            action.setEnabled(widget.isEnabled())
            if widget.isCheckable():
                action.setCheckable(True)
                action.setChecked(widget.isChecked())
            action.triggered.connect(lambda checked=False, w=widget: w.click())
        elif isinstance(widget, QtWidgets.QComboBox):
            child = menu.addMenu(control_name(widget))
            menu._curve_children.append(child)
            child.setEnabled(widget.isEnabled())
            for index in range(widget.count()):
                action = child.addAction(widget.itemIcon(index), widget.itemText(index))
                action.setCheckable(True)
                action.setChecked(index == widget.currentIndex())

                def choose(checked=False, w=widget, i=index):
                    w.setCurrentIndex(i)
                    w.activated.emit(i)

                action.triggered.connect(choose)
        elif isinstance(
            widget,
            (
                QtWidgets.QAbstractSpinBox,
                QtWidgets.QLineEdit,
                QtWidgets.QTextEdit,
                QtWidgets.QPlainTextEdit,
            ),
        ):
            if isinstance(widget, QtWidgets.QLineEdit) and isinstance(
                widget.parentWidget(), QtWidgets.QAbstractSpinBox
            ):
                continue
            title = control_name(widget)
            action = menu.addAction(title + "…")
            action.setEnabled(widget.isEnabled() and not widget.isReadOnly())

            def edit(checked=False, w=widget, title=title):
                if isinstance(w, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
                    value, ok = QtWidgets.QInputDialog.getDouble(
                        content,
                        title,
                        title,
                        float(w.value()),
                        float(w.minimum()),
                        float(w.maximum()),
                        getattr(w, "decimals", lambda: 0)(),
                    )
                    if ok:
                        w.setValue(
                            int(value) if isinstance(w, QtWidgets.QSpinBox) else value
                        )
                        w.editingFinished.emit()
                else:
                    value, ok = QtWidgets.QInputDialog.getMultiLineText(
                        content,
                        title,
                        title,
                        w.text()
                        if isinstance(w, QtWidgets.QLineEdit)
                        else w.toPlainText(),
                    )
                    if ok:
                        (
                            w.setText
                            if isinstance(w, QtWidgets.QLineEdit)
                            else w.setPlainText
                        )(value)
                        if hasattr(w, "editingFinished"):
                            w.editingFinished.emit()

            action.triggered.connect(edit)


def clear_generated(menu):
    # QMenu.clear() removes actions but leaves QObject-owned generated submenus
    # alive. Their callbacks retain editors and complete closed spreadsheets.
    # Menus borrowed from a document button keep their original owner.
    for child in getattr(menu, "_curve_children", []):
        if child.parent() is menu:
            child.deleteLater()
    menu.clear()
    menu._curve_children = []


def populate(menu, window, title):
    if getattr(menu, "_curve_populating", False):
        return
    menu._curve_populating = True
    try:
        _populate(menu, window, title)
    finally:
        menu._curve_populating = False


def _populate(menu, window, title):
    clear_generated(menu)
    plot = window.ui.tabWidget.currentWidget()
    plot = getattr(plot, "_active_document", plot)
    tabs = getattr(plot, "property_tabs", None)
    index = (
        next((i for i in range(tabs.count()) if tabs.tabText(i) == title), -1)
        if tabs
        else -1
    )
    if index < 0:
        if title == "图形" and hasattr(plot, "plot_type_picker"):
            from tailor.plot_types import MODE_ITEMS

            for name, key in MODE_ITEMS:
                button = plot.plot_type_picker.buttons[key]
                menu.addAction(
                    button.icon(), name, lambda checked=False, b=button: b.click()
                )
            return
        item = menu.addAction("请先选择图形")
        item.setEnabled(False)
        return
    if not tabs.isTabEnabled(index):
        action = menu.addAction("请使用高级标签中的对应功能")
        action.setEnabled(False)
        return
    page = tabs.widget(index)
    action = menu.addAction("打开" + title + "功能区")
    action.triggered.connect(lambda: tabs.setCurrentIndex(index))
    if title == "坐标轴":
        axes = menu.addMenu("选择坐标轴")
        menu._curve_children.append(axes)
        for key, button in plot.axis_controls.axis_buttons.items():
            axes.addAction(
                button.icon(),
                button.text(),
                lambda checked=False, k=key: plot.axis_controls.select_axis(k),
            )
    for section, header, opened, content in getattr(page, "sections", []):
        name = header.property("sectionTitle")
        child = menu.addMenu(name)
        menu._curve_children.append(child)
        from tailor.text_style_controls import reveal_section

        child.addAction(
            "打开" + name,
            lambda checked=False, p=page, n=name: reveal_section(plot, p, n),
        )
        populate_controls(child, content)
    if title == "图形":
        for kind, name in (("font", "字体偏好"), ("curve", "线条偏好")):
            child = menu.addMenu(name)
            menu._curve_children.append(child)
            child.setEnabled(getattr(plot.preferences, "_" + kind + "_allowed", True))
            child.addAction(
                "打开" + name,
                lambda checked=False, k=kind: getattr(plot.preferences, "open_" + k)(),
            )
            editor = (
                plot.preferences.editor
                if kind == "font"
                else plot.preferences.curve_editor
            )
            if editor is not None:
                populate_controls(child, editor)


def setup_feature_menus(window):
    window._feature_menus = {}
    bar = window.menuBar()
    for title in ("图形", "坐标轴", "拟合", "处理", "高级", "导出"):
        menu = window.ui.menuPlot if title == "图形" else QtWidgets.QMenu(title, window)
        menu.setTitle(title)
        if title != "图形":
            bar.insertMenu(window.ui.menuHelp.menuAction(), menu)
        menu.aboutToShow.connect(lambda m=menu, t=title: populate(m, window, t))
        window._feature_menus[title] = menu
        populate(menu, window, title)

    def refresh(*args):
        # Expanding a borrowed object menu can sync a control and emit a
        # history/selection refresh before Cocoa marks the menu visible.
        # Never destroy the actions that are still being constructed.
        if any(
            getattr(menu, "_curve_populating", False)
            for menu in window._feature_menus.values()
        ):
            return
        for title, menu in window._feature_menus.items():
            if not menu.isVisible():
                # Keep native menus nonempty, but defer hundreds of action/icon
                # bindings until aboutToShow. A document switch must only swap
                # canvases/inspectors, not rebuild every unopened feature menu.
                clear_generated(menu)
                action = menu.addAction("打开" + title + "功能区")

                def open_page(checked=False, title=title):
                    document = window.ui.tabWidget.currentWidget()
                    tabs = getattr(document, "property_tabs", None)
                    if tabs:
                        index = next(
                            (
                                i
                                for i in range(tabs.count())
                                if tabs.tabText(i) == title
                            ),
                            -1,
                        )
                        if index >= 0 and tabs.isTabEnabled(index):
                            tabs.setCurrentIndex(index)

                action.triggered.connect(open_page)

    window.ui.tabWidget.currentChanged.connect(refresh)
    window._refresh_feature_menus = refresh

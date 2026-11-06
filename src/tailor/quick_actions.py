"""A shared narrow action rail between the document and inspector."""

import shiboken6
from PySide6 import QtCore, QtGui, QtWidgets

from tailor.ui_theme import action_icon


def _view_state(doc):
    """Small view snapshot; source arrays and ROI geometry stay with their owners."""
    box = doc.ui.plot_widget.getViewBox()
    presentation = doc.presentation
    return {
        "limits": tuple(getattr(doc.model, key) for key in ("x_min", "x_max", "y_min", "y_max")),
        "secondary": tuple(getattr(presentation, key) for key in ("right_min", "right_max", "top_min", "top_max")),
        "remembered": tuple(getattr(doc, key, None) for key in (
            "_remembered_x_range", "_remembered_y_range", "_remembered_right_range"
        )),
        "main": tuple(tuple(axis) for axis in box.viewRange()),
        "right": tuple(tuple(axis) for axis in presentation.right_box.viewRange()) if presentation.right_box else None,
        "top": tuple(tuple(axis) for axis in presentation.top_box.viewRange()) if presentation.top_box else None,
    }


def _restore_view(doc, state):
    if getattr(doc, "_graph_disposed", False) or not shiboken6.isValid(doc):
        return
    old = _view_state(doc)
    for key, value in zip(("x_min", "x_max", "y_min", "y_max"), state["limits"]):
        setattr(doc.model, key, value)
    for key, value in zip(("right_min", "right_max", "top_min", "top_max"), state["secondary"]):
        setattr(doc.presentation, key, value)
    if old["limits"] != state["limits"] or old["secondary"] != state["secondary"]:
        doc.refresh_ui()
    doc._block_range_signal = True
    extras = getattr(doc, "_inset_extras", None)
    prior_inset_setting = getattr(extras, "_setting_range", False)
    if extras is not None:
        extras._setting_range = True
    try:
        if state["right"] is not None and doc.presentation.right_box is not None:
            doc.presentation.right_box.setYRange(*state["right"][1], padding=0)
        if state["top"] is not None and doc.presentation.top_box is not None:
            doc.presentation.top_box.setXRange(*state["top"][0], padding=0)
        doc.ui.plot_widget.setRange(
            xRange=state["main"][0], yRange=state["main"][1], padding=0,
            disableAutoRange=True,
        )
    finally:
        doc._block_range_signal = False
        if extras is not None:
            extras._setting_range = prior_inset_setting
    for key, value in zip(("_remembered_x_range", "_remembered_y_range", "_remembered_right_range"), state["remembered"]):
        setattr(doc, key, value)
    if hasattr(doc, "axis_controls"):
        doc.axis_controls.sync()


def _record_view_reset(doc, before, after):
    from tailor.text_style_controls import record_view_edit

    record_view_edit(doc, "默认视图", before, after,
                     lambda _target, entries: [
                         _restore_view(target, state)
                         for target, state in entries
                         if shiboken6.isValid(target)
                     ])


class QuickActions(QtWidgets.QWidget):
    def __init__(self, document):
        super().__init__(document)
        self.document = document
        self.setObjectName("quickActions")
        self.setAttribute(QtCore.Qt.WA_StyledBackground)
        self.setFixedWidth(46)
        root=QtWidgets.QVBoxLayout(self);root.setContentsMargins(0,0,0,0)
        self.scroll=QtWidgets.QScrollArea(self);self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.scroll.verticalScrollBar().setFixedWidth(4)
        self.scroll.verticalScrollBar().setStyleSheet('QScrollBar:vertical {width:4px;min-width:4px;max-width:4px;}')
        self.body=QtWidgets.QWidget();self.scroll.setWidget(self.body);root.addWidget(self.scroll)
        layout = QtWidgets.QVBoxLayout(self.body)
        layout.setSizeConstraint(QtWidgets.QLayout.SetMinimumSize)
        layout.setContentsMargins(1, 8, 1, 8)
        layout.setSpacing(6)
        self.buttons = {}
        self._bound = False
        self._inspector = None
        self._rail_connections = []
        for key, title in (
            ("undo", "撤销"),
            ("redo", "重做"),
            ("plot", "绘图"),
            ("font", "字体偏好"),
            ("curve", "曲线偏好"),
            ("delete", "删除选中元素"),
            ("hide", "隐藏选中元素；右键查看全部隐藏元素"),
            ("point", "开启 / 关闭点击选点"),
            ("inset", "添加局部放大"),
            ("right_axis", "显示右Y轴与轴标题"),
            ("range", "范围与比例"),
            ("annotation", "添加标注"),
            ("position", "位置与坐标"),
            ("home", "默认视图 · 显示全部数据"),
            ("save", "保存工程（.cur）"),
            ("export", "快捷导出 PNG / SVG / PDF"),
            ("updates", "检查更新"),
            ("settings", "设置"),
        ):
            button = QtWidgets.QToolButton(self)
            button.setFixedSize(36, 36)
            button.setIconSize(QtCore.QSize(21, 21))
            button.setIcon(action_icon(key, self))
            button.setToolTip(title)
            button.setAccessibleName(title)
            if key in {"font", "curve"}:
                button.setProperty("preferenceKind", key)
            self.buttons[key] = button
            if key in {'inset','right_axis','range','annotation','position'}:button.setEnabled(False)
            layout.addWidget(button)
        from tailor.element_actions import hide, remove
        from tailor.element_actions import menu as inspector_menu
        self.buttons["save"].clicked.connect(lambda:self.document.main_window.save_project_or_dialog())
        self.buttons["delete"].clicked.connect(lambda: remove(self.document))
        self.buttons["hide"].clicked.connect(lambda: hide(self.document))
        for key in ("undo","redo","hide"):
            button = self.buttons[key]
            button.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
            button.customContextMenuRequested.connect(lambda pos,key=key: inspector_menu(self.document,"hidden" if key=="hide" else key))
        self.buttons["point"].setCheckable(True)
        self.buttons['right_axis'].setCheckable(True)
        self._annotation_menus=set()
        self.buttons["point"].toggled.connect(self.toggle_points)
        self.buttons["home"].clicked.connect(self.reset_view)
        menu = QtWidgets.QMenu(self)
        menu.addAction('默认导出…', lambda: self.document.main_window.export_graph())
        menu.addSeparator()
        for suffix in (".png", ".svg", ".pdf"):
            menu.addAction(
                suffix[1:].upper() + "…",
                lambda suffix=suffix: self.document.main_window.export_graph(suffix),
            )
        # Keep the export icon centered: a full-size click opens the menu, no overlaid arrow.
        self.buttons["export"].clicked.connect(
            lambda: menu.popup(self.buttons["export"].mapToGlobal(QtCore.QPoint(36, 0)))
        )
        self.buttons["plot"].clicked.connect(self.create_plot)
        self.buttons["font"].clicked.connect(lambda: self.open_preferences("font"))
        self.buttons["curve"].clicked.connect(lambda: self.open_preferences("curve"))
        self.buttons["settings"].clicked.connect(self.open_settings)
        from tailor.update_check import check_now
        self.buttons["updates"].clicked.connect(check_now)
        self.buttons['inset'].clicked.connect(self.add_inset)
        self.buttons['right_axis'].clicked.connect(self.enable_right_axis)
        self.buttons['range'].clicked.connect(lambda:self.jump('范围与比例'))
        self.buttons['annotation'].clicked.connect(lambda:self.jump('添加标注',open_add=True))
        self.buttons['position'].clicked.connect(lambda:self.jump('位置与坐标'))
        # Reuse the same actions in framed groups, with deliberate separation.
        for button in self.buttons.values():
            layout.removeWidget(button)
        def frame(keys):
            box = QtWidgets.QFrame(self)
            box.setObjectName("quickActionGroup")
            box.setStyleSheet("QFrame#quickActionGroup {border:1px solid palette(mid);border-radius:6px;}")
            line = QtWidgets.QVBoxLayout(box)
            line.setContentsMargins(3, 3, 3, 3)
            line.setSpacing(0)
            box.setFixedSize(40, len(keys)*32+8)
            for key in keys:
                self.buttons[key].setFixedSize(32,32)
                line.addWidget(self.buttons[key])
            layout.addWidget(box, alignment=QtCore.Qt.AlignHCenter)
            return box
        frame(("undo", "redo"))
        layout.addSpacing(8)
        self.file_group = frame(("save", "export"))
        layout.addSpacing(8)
        from tailor.element_button_group import ElementButtons
        self.element_actions = ElementButtons(document, scope=None, vertical=True)
        for key in ("delete", "hide"):
            self.buttons[key].hide()
            self.buttons[key].setParent(self)
            self.buttons[key] = self.element_actions.buttons[key]
        self.buttons['add'] = self.element_actions.buttons['add']
        self.buttons['down'] = self.element_actions.buttons['down']
        # ElementButtons already owns its commands, so no second signal binding.
        layout.addWidget(self.element_actions, alignment=QtCore.Qt.AlignHCenter)
        layout.addSpacing(8)
        frame(("font", "curve"))
        layout.addSpacing(8)
        self.tools=QtWidgets.QWidget(self.body)
        tools_layout=QtWidgets.QVBoxLayout(self.tools)
        tools_layout.setContentsMargins(0,0,0,0);tools_layout.setSpacing(2)
        tools_layout.setSizeConstraint(QtWidgets.QLayout.SetMinimumSize)
        for key in ("plot", "point", "inset", "right_axis", "range", "annotation", "position", "home"):
            tools_layout.addWidget(self.buttons[key], alignment=QtCore.Qt.AlignHCenter)
        layout.addWidget(self.tools)
        layout.addStretch()
        layout.addWidget(self.buttons["updates"], alignment=QtCore.Qt.AlignHCenter)
        layout.addWidget(self.buttons["settings"], alignment=QtCore.Qt.AlignHCenter)
        for key,button in self.buttons.items():
            button.setProperty('railSize',32 if key in {'undo','redo','save','export','font','curve','add','delete','hide','down'} else 36)
            button.installEventFilter(self)
        from tailor.appearance import manager

        self._rail_connections.append(manager().changed.connect(self.refresh_icons))
        self.refresh_icons()
        self._selection_timer = QtCore.QTimer(self)
        self._selection_timer.setInterval(200)
        self._selection_timer.timeout.connect(self.sync)
        self._selection_timer.start()
        from tailor.navigation_history import NavigationHistory

        self.navigation_history = NavigationHistory(document) if hasattr(document, "presentation") else None
        QtCore.QTimer.singleShot(0, self, self.sync)

    def focused_document(self):
        return getattr(self.document,'_active_document',None) or self.document

    def jump(self,title,open_add=False):
        doc=self.focused_document()
        if not hasattr(doc,'preferences') or getattr(doc,'_graph_disposed',False) or getattr(doc,'_inspector_initializing',False):return
        doc.preferences.return_to_inspector()
        page=doc.axis_controls if title=='范围与比例' else doc.preferences.graph
        from tailor.text_style_controls import reveal_section
        reveal_section(doc,page,title)
        record=next((r for r in page.sections if r[1].property('sectionTitle')==title),None)
        if record:QtCore.QTimer.singleShot(0,page,lambda:page.scroll.ensureWidgetVisible(record[0]))
        if open_add:
            panel=doc.annotations.panel
            menu=panel.add_menu
            if menu not in self._annotation_menus:
                self._annotation_menus.add(menu)
                self._rail_connections.append(menu.aboutToHide.connect(self.reset_annotation_button))
            def open_menu():
                self.reset_annotation_button()
                panel.open_add_menu()
                self.reset_annotation_button()
            QtCore.QTimer.singleShot(0,doc,open_menu)

    def reset_annotation_button(self):
        button=self.buttons['annotation']
        button.setDown(False)
        button.clearFocus()
        button.setAttribute(QtCore.Qt.WA_UnderMouse,False)
        QtWidgets.QApplication.sendEvent(button,QtCore.QEvent(QtCore.QEvent.Leave))
        button.update()

    def add_inset(self):
        doc=self.focused_document()
        collection=getattr(getattr(doc,'extras',None),'collection',None)
        if collection is not None and collection.add.isEnabled() and not getattr(doc,'_inspector_initializing',False):collection.add_entry(deferred=True)

    def enable_right_axis(self):
        import copy
        doc=self.focused_document()
        if not hasattr(doc,'presentation'):return
        before=copy.deepcopy(doc.presentation.axes['right'])
        enabled=not (before['visible'] and before['title_visible'])
        doc.presentation.axes['right'].update(visible=enabled,line_visible=enabled,title_visible=enabled)
        doc.presentation.apply_axes();doc.axis_controls.sync()
        self.sync()
        after=copy.deepcopy(doc.presentation.axes['right'])
        def restore(plot,value):
            plot.presentation.axes['right']=copy.deepcopy(value)
            plot.presentation.apply_axes();plot.axis_controls.sync()
            if shiboken6.isValid(self):self.sync()
        from tailor.text_style_controls import record_view_edit
        record_view_edit(doc,'显示右Y轴与轴标题' if enabled else '隐藏右Y轴与轴标题',before,after,restore)
        doc.main_window.mark_project_dirty()

    def open_settings(self):
        from tailor.product_shell import show_settings

        show_settings()

    @QtCore.Slot()
    def refresh_icons(self, *args):
        if not shiboken6.isValid(self) or getattr(self.document, "_graph_disposed", False):
            return
        from tailor.appearance import manager

        normal, disabled = (
            ("#a6b1c0", "#444c57") if manager().dark() else ("#637080", "#c0c7d0")
        )
        for key, button in self.buttons.items():
            accent = {"font": "#2f9958", "curve":"#bb6a22", "delete":"#d34b48", "hide":"#8655b2", "down":"#8655b2", "add":"#35945b"}.get(key, normal)
            icon = action_icon("plus" if key == "add" else key, self, accent)
            faded = action_icon("plus" if key == "add" else key, self, disabled)
            for state in (QtGui.QIcon.Off, QtGui.QIcon.On):
                icon.addPixmap(
                    faded.pixmap(48, 48, QtGui.QIcon.Normal, QtGui.QIcon.Off),
                    QtGui.QIcon.Disabled,
                    state,
                )
            button.setIcon(icon)

    def eventFilter(self, watched, event):
        if event.type() in {QtCore.QEvent.Polish,QtCore.QEvent.StyleChange,QtCore.QEvent.FontChange} and watched.property('railSize'):
            size=int(watched.property('railSize'))
            QtCore.QTimer.singleShot(0,watched,lambda:watched.setFixedSize(size,size))
        if event.type() == QtCore.QEvent.EnabledChange:
            self.refresh_icons()
        return False

    @QtCore.Slot()
    def sync(self, *args):
        if not shiboken6.isValid(self):
            return
        if getattr(self.document,"_graph_disposed",False):
            if shiboken6.isValid(self._selection_timer):
                self._selection_timer.stop()
            return
        if self.navigation_history is not None:
            self.navigation_history.ensure_bindings()
        owner = self.document.main_window
        controls = getattr(owner, "tab_controls", None)
        if controls is not None and not self._bound:
            self.buttons["undo"].setDefaultAction(controls.undo)
            self.buttons["redo"].setDefaultAction(controls.redo)
            self._rail_connections.append(controls.undo.changed.connect(self.refresh_icons))
            self._rail_connections.append(controls.redo.changed.connect(self.refresh_icons))
            self._bound = True
            self.refresh_icons()
        has_plot = hasattr(self.document, "presentation")
        self.buttons['plot'].setEnabled(not has_plot)
        focused=self.focused_document()
        kind=getattr(getattr(focused,'advanced_view',None),'cfg',{}).get('kind')
        two_dimensional=hasattr(focused,'axis_controls') and hasattr(focused,'preferences') and not getattr(focused,'_inspector_initializing',False) and kind!='3d'
        for key in ('right_axis','range','annotation','position'):self.buttons[key].setEnabled(two_dimensional)
        right=getattr(getattr(focused,'presentation',None),'axes',{}).get('right',{})
        enabled=bool(right.get('visible') and right.get('line_visible',True) and right.get('title_visible'))
        with QtCore.QSignalBlocker(self.buttons['right_axis']):
            self.buttons['right_axis'].setChecked(enabled)
        add=getattr(getattr(getattr(focused,'extras',None),'collection',None),'add',None)
        advanced_root=getattr(focused,'_embedded_parent',focused)
        advanced=getattr(advanced_root,'advanced_view',None) is not None
        self.buttons['inset'].setEnabled(two_dimensional and not advanced and add is not None and add.isEnabled())
        from tailor.element_actions import target
        selected = target(self.document) is not None
        from tailor.element_button_group import ElementButtons
        for actions in self.document.findChildren(ElementButtons):
            actions.sync()
        self.element_actions.sync()
        self.buttons["delete"].setEnabled(selected)
        # The global hide control also opens restoration by right-click even
        # with no selected element. Left-click without a target is a no-op.
        self.buttons["hide"].setEnabled(True)
        self.buttons["home"].setEnabled(has_plot)
        self.buttons["font"].setEnabled(
            has_plot
        )
        self.buttons["curve"].setEnabled(
            has_plot
        )
        self.buttons["export"].setEnabled(has_plot)
        inspector = getattr(self.document, "point_inspector", None)
        self.buttons["point"].setEnabled(inspector is not None)
        if inspector is not None:
            if self._inspector is not inspector:
                self._rail_connections.append(inspector.enabled.toggled.connect(self.sync))
                self._inspector = inspector
            with QtCore.QSignalBlocker(self.buttons["point"]):
                self.buttons["point"].setChecked(inspector.enabled.isChecked())

    def dispose(self):
        self._selection_timer.stop()
        if self.navigation_history is not None:
            self.navigation_history.timer.stop()
        for connection in self._rail_connections:
            try:
                QtCore.QObject.disconnect(connection)
            except (RuntimeError, TypeError):
                pass
        self._rail_connections.clear()

    def toggle_points(self, checked):
        inspector = getattr(self.document, "point_inspector", None)
        if inspector is not None:
            if checked and hasattr(self.document, "annotations"):
                self.document.annotations.arm(None)
            inspector.enabled.setChecked(checked)

    def reset_view(self):
        doc = self.document
        if not hasattr(doc, "presentation"):
            return
        if hasattr(doc, "_inset_extras"):
            # This inset's default is its source ROI, including inside a
            # multi-panel graph. Keep the ROI and parent plot unchanged.
            before = [(doc, _view_state(doc))]
            doc._inset_extras.apply_inset_range()
            _record_view_reset(doc, before, [(doc, _view_state(doc))])
            return
        parent = getattr(self.document, "_embedded_parent", self.document)
        native = getattr(getattr(parent, "advanced_view", None), "native", None)
        if native and not getattr(native, "resetting", False):
            targets = list(dict.fromkeys(native.live()))
            before = [(target, _view_state(target)) for target in targets]
            native.reset()
            _record_view_reset(doc, before, [(target, _view_state(target)) for target in targets])
            return
        record = not (native and getattr(native, "resetting", False))
        before = [(doc, _view_state(doc))] if record else None
        if getattr(doc, 'advanced_view', None) is not None:
            doc.advanced_view.schedule(True)
            return
        doc._clear_remembered_zoom()
        for name in ("x_min", "x_max", "y_min", "y_max"):
            setattr(doc.model, name, None)
        doc.presentation.right_min = doc.presentation.right_max = None
        doc.presentation.top_min = doc.presentation.top_max = None
        doc.refresh_ui()
        from tailor.processing_controls import full_preview_range

        full_preview_range(doc)
        if hasattr(doc, "axis_controls"):
            doc.axis_controls.sync()
        doc.main_window.mark_project_dirty()
        if record:
            _record_view_reset(doc, before, [(doc, _view_state(doc))])

    def create_plot(self):
        if hasattr(self.document,'presentation'):return
        owner = self.document.main_window
        sheets = owner.get_data_sheets()
        if not sheets:
            return
        sheet = sheets[0]
        owner.ui.tabWidget.setCurrentWidget(sheet)
        picker = sheet.plot_type_picker
        if picker.mode is None:
            index = next((i for i in range(sheet.property_tabs.count()) if sheet.property_tabs.tabText(i)=="导入与绘图"),0)
            sheet.property_tabs.setCurrentIndex(index)
            owner.statusBar().showMessage("请先选择绘图风格，再点击绘图。",6000)
        else:
            picker.draw()

    def open_preferences(self, kind):
        prefs = getattr(self.document, "preferences", None)
        if prefs:
            getattr(prefs, "open_" + kind)()

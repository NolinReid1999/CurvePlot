"""Project switcher, colored documents and native title-toolbar history."""

from PySide6 import QtCore, QtGui, QtWidgets

from tailor.data_sheet import DataSheet
from tailor.document_tabs import DocumentTabBar


class ProjectControls(QtWidgets.QWidget):
    def sizeHint(self):
        # QTabWidget positions its corner from the hint, not the fixed height.
        size = super().sizeHint()
        size.setHeight(DocumentTabBar.ROW_HEIGHT)
        return size


class TabControls(QtCore.QObject):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.connected = set()
        box = ProjectControls(owner.ui.tabWidget)
        box.setObjectName("projectControls")
        row = QtWidgets.QHBoxLayout(box)
        inset = DocumentTabBar.VERTICAL_INSET
        button_height = DocumentTabBar.ROW_HEIGHT - 2 * inset
        row.setContentsMargins(2, inset, 8, inset)
        row.setSpacing(4)
        self.new_project = QtWidgets.QToolButton(box)
        from tailor.ui_theme import action_icon

        self.new_project.setIcon(action_icon("plus", owner))
        self.new_project.setIconSize(
            QtCore.QSize(DocumentTabBar.ICON_SIZE, DocumentTabBar.ICON_SIZE)
        )
        self.new_project.setToolTip("新建项目")
        self.new_project.setAccessibleName("新建项目")
        self.new_project.setFixedSize(28, button_height)
        self.new_project.clicked.connect(owner.new_project)
        self.project_button = QtWidgets.QToolButton(box)
        self.project_button.setProperty("projectSelector", True)
        self.project_button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.project_button.setToolTip("切换项目；菜单中可重命名当前项目")
        self.project_menu = QtWidgets.QMenu(self.project_button)
        self.project_menu.aboutToShow.connect(self.populate_projects)
        self.project_button.setMenu(self.project_menu)
        self.project_button.installEventFilter(self)
        self.project_button.setFixedHeight(button_height)
        box.setFixedHeight(DocumentTabBar.ROW_HEIGHT)
        for button in (self.new_project, self.project_button):
            button.setFont(owner.ui.tabWidget.tabBar().label_font(selected=True))
        row.addWidget(self.new_project)
        row.addWidget(self.project_button)
        separator = QtWidgets.QFrame()
        separator.setFrameShape(QtWidgets.QFrame.VLine)
        separator.setFixedSize(1, 18)
        separator.setStyleSheet("background: #d7dee7; border: 0;")
        row.addSpacing(6)
        row.addWidget(separator)
        owner.ui.tabWidget.setCornerWidget(box, QtCore.Qt.TopLeftCorner)
        # The pane has a 1px top divider; keep the corner on the tab bar baseline.
        owner.ui.tabWidget.setStyleSheet(
            "QTabWidget::tab-bar { alignment: left; }"
            "QTabWidget::left-corner { subcontrol-origin: border;"
            " subcontrol-position: top left; position: absolute; top: -1px; left: 0px; }"
            "QTabWidget::right-corner { subcontrol-origin: border;"
            " subcontrol-position: top right; position: absolute; top: -1px; right: 0px; }"
        )
        # Keep the ordinary macOS title bar draggable. No expanded client area.
        from tailor.ui_theme import action_icon

        for title, method in (("撤销", "undo"), ("重做", "redo")):
            action = QtGui.QAction(action_icon(method, owner), title, owner)
            # The visible graph rail associates this action with its window.
            # Hidden graph rails do not conflict with the table/editor undo keys.
            action.setShortcut(QtGui.QKeySequence.Undo if method=="undo" else QtGui.QKeySequence.Redo)
            action.triggered.connect(
                lambda checked=False, method=method: self.replay(method)
            )
            setattr(self, method, action)
        self.counts = QtWidgets.QLabel(owner.ui.tabWidget)
        self.counts.setObjectName("documentCounts")
        self.counts.setAlignment(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignRight)
        self.counts.setFixedHeight(DocumentTabBar.ROW_HEIGHT)
        self.counts.setContentsMargins(8, 0, 10, 0)
        corner = ProjectControls(owner.ui.tabWidget)
        corner.setObjectName("projectControls")
        right = QtWidgets.QHBoxLayout(corner)
        corner.setFixedHeight(DocumentTabBar.ROW_HEIGHT)
        right.setContentsMargins(0, inset, 6, inset)
        right.setAlignment(QtCore.Qt.AlignVCenter)
        self.counts.setFixedHeight(button_height)
        right.addWidget(self.counts)
        window_button = QtWidgets.QToolButton(corner)
        window_button.setIcon(action_icon("panels-top-left", owner))
        window_button.setText("窗口模式")
        window_button.setIconSize(QtCore.QSize(DocumentTabBar.ICON_SIZE, DocumentTabBar.ICON_SIZE))
        window_button.setFixedHeight(button_height)
        window_button.setFont(owner.ui.tabWidget.tabBar().label_font(selected=True))
        window_button.setStyleSheet(
            "QToolButton {padding:0 9px;border:1px solid #bfc9d6;border-radius:5px;background:transparent;} QToolButton:checked {background:#e5dcf7;border-color:#9466c7;color:#7045a1;}"
        )
        window_button.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        right.addWidget(window_button)
        owner.ui.tabWidget.setCornerWidget(corner, QtCore.Qt.TopRightCorner)
        from tailor.window_mode import WindowMode

        owner.window_mode = WindowMode(owner, window_button)
        self.count_timer = QtCore.QTimer(self)
        self.count_timer.setInterval(500)
        self.count_timer.timeout.connect(self.refresh_counts)
        self.count_timer.start()
        owner.ui.tabWidget.currentChanged.connect(self.refresh)
        self.refresh()
        from tailor.document_names import install

        install(owner)
        # These corners can be built while the system is dark, then first
        # displayed after the user selects light. Keep the cached palette's
        # construction mode so the existing Show refresh repolishes it.
        from tailor.appearance import manager
        dark=manager().dark()
        for group in (box,corner):
            for widget in [group,*group.findChildren(QtWidgets.QWidget)]:
                if getattr(widget,'_curve_app_dark',None) is None:widget._curve_app_dark=dark

    def eventFilter(self, watched, event):
        if (
            watched is self.project_button
            and event.type() == QtCore.QEvent.Enter
            and not self.project_menu.isVisible()
        ):
            QtCore.QTimer.singleShot(
                170, self,
                lambda: (
                    self.project_menu.popup(
                        self.project_button.mapToGlobal(
                            QtCore.QPoint(0, self.project_button.height())
                        )
                    )
                    if self.project_button.underMouse()
                    and not self.project_menu.isVisible()
                    else None
                ),
            )
        return False

    def populate_projects(self):
        self.project_menu.clear()
        for window in self.owner.projects.windows:
            action = self.project_menu.addAction(
                window.project_name + (" *" if window._is_dirty else "")
            )
            action.setCheckable(True)
            action.setChecked(window is self.owner)
            action.triggered.connect(
                lambda checked=False, window=window: self.owner.projects.activate(
                    window
                )
            )
        self.project_menu.addSeparator()
        self.project_menu.addAction("重命名当前项目…", self.rename_project)
        self.project_menu.addAction("关闭当前项目", self.owner.close)

    def rename_project(self):
        name, accepted = QtWidgets.QInputDialog.getText(
            self.owner, "重命名项目", "项目名称", text=self.owner.project_name
        )
        if accepted and name.strip():
            from tailor.document_names import rename
            sheets = self.owner.get_data_sheets()
            if sheets:
                rename(self.owner, sheets[0], name.strip())

    def refresh_project_name(self):
        for sheet in self.owner.get_data_sheets():
            sheet.name = self.owner.project_name
        self.project_button.setText(
            self.owner.project_name + (" *" if self.owner._is_dirty else "")
        )

    def sheet(self):
        tab = self.owner.ui.tabWidget.currentWidget()
        tab = getattr(tab, "_active_document", tab)
        return tab if isinstance(tab, DataSheet) else getattr(tab, "data_sheet", None)

    def annotation_history(self):
        # Every document edit, including annotations, uses the source sheet's
        # chronological Edit history. A selected graph page must not steal Undo.
        return None

    def replay(self, method):
        history = self.annotation_history()
        if history is not None:
            getattr(history, method)()
            return
        sheet = self.sheet()
        if sheet is not None:
            getattr(sheet.model, method)()

    def refresh(self, *args):
        from tailor.document_names import sync

        sync(self.owner)
        tabs = self.owner.ui.tabWidget
        for index in range(tabs.count()):
            tab = tabs.widget(index)
            tabs.setTabIcon(index, QtGui.QIcon())
            tabs.setTabText(index, tab.name)
            tabs.setTabToolTip(index, tab.name)
            if (
                isinstance(tab, DataSheet) and getattr(tab, "_default_sheet", False)
            ) or hasattr(tab, "result_kind"):
                bar = tabs.tabBar()
                button = bar.tabButton(index, QtWidgets.QTabBar.RightSide)
                if button is not None:
                    button.hide()
                    bar.setTabButton(index, QtWidgets.QTabBar.RightSide, None)
                    button.deleteLater()
            tabs.tabBar().setTabData(
                index,
                "sheet"
                if isinstance(tab, DataSheet)
                else getattr(tab, "document_kind", "plot"),
            )
            if isinstance(tab, DataSheet) and id(tab) not in self.connected:
                self.connected.add(id(tab))
                tab.model.historyChanged.connect(self.refresh)
                key = id(tab)
                tab.destroyed.connect(
                    lambda obj=None, key=key: self.connected.discard(key)
                )
        sheet = self.sheet()
        history = self.annotation_history()
        self.undo.setEnabled(
            history.canUndo()
            if history is not None
            else sheet is not None and sheet.model.can_undo
        )
        self.redo.setEnabled(
            history.canRedo()
            if history is not None
            else sheet is not None and sheet.model.can_redo
        )
        for action, label in ((self.undo, "撤销"), (self.redo, "重做")):
            action.setToolTip(
                label
                + (
                    "（当前图形标注）"
                    if history is not None
                    else "（当前工作表及其图形）"
                )
            )
        self.refresh_project_name()
        for index in range(tabs.count()):
            rail = getattr(tabs.widget(index), "quick_actions", None)
            if rail is not None:
                rail.sync()
        self.refresh_counts()
        self.owner.window_mode.changed()
        tabs.tabBar().update()

    def refresh_counts(self):
        tab = self.owner.ui.tabWidget.currentWidget()
        tab = getattr(tab, "_active_document", tab)
        if hasattr(tab, "result_kind"):
            tab = tab.tabs.currentWidget()
        points, curves = 0, 0
        if isinstance(tab, DataSheet):
            points = tab.model.rowCount()
        elif hasattr(tab, "_series"):
            for source, series in tab._series.items():
                info = tab.model._plots.get(source)
                if info is not None and info.visible:
                    data = series["data"].xData
                    points += getattr(series['data'],'_curve_source_count',0 if data is None else len(data))
                    curves += 1
        elif getattr(tab, "document_kind", "") == "fit":
            points = tab.record["statistics"]["ndata"]
            curves = 1
        elif hasattr(getattr(tab, "plot", None), "xData"):
            data = tab.plot.xData
            points = getattr(tab.plot,'_curve_source_count',0 if data is None else len(data))
            curves = int(points > 0 and tab.curve_style.visible)
            points = points if curves else 0
        self.counts.setText(f"{points:,} 点 · {curves} 条曲线")
        tabs=self.owner.ui.tabWidget;bar=tabs.tabBar()
        left=tabs.cornerWidget(QtCore.Qt.TopLeftCorner)
        right=tabs.cornerWidget(QtCore.Qt.TopRightCorner)
        needed=sum(bar.tabSizeHint(i).width() for i in range(bar.count()))
        available=tabs.width()-(left.sizeHint().width() if left else 0)-100
        visible=needed+self.counts.sizeHint().width()<available
        if self.counts.isVisible()!=visible:self.counts.setVisible(visible)
        if hasattr(bar,'refresh_arrows'):bar.refresh_arrows()
        self.counts.setToolTip(
            "表格：数据行数；图形：显示曲线的源点数（未降采样），不含拟合线。"
        )

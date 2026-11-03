"""Shared four-action frame; delegates edits to existing element commands."""

from PySide6 import QtCore, QtWidgets
from tailor.ui_theme import action_icon


class ElementButtons(QtWidgets.QFrame):
    def __init__(self, doc, scope="curves", add=None, vertical=False):
        super().__init__()
        self.doc, self.scope, self.add_callback = doc, scope, add
        self.setObjectName("elementButtons")
        self.setStyleSheet("QFrame#elementButtons {border:1px solid palette(mid);border-radius:6px;} QToolButton {border:0;background:transparent;padding:0;} QToolButton:hover {background:palette(alternate-base);border-radius:4px;}")
        layout = (QtWidgets.QVBoxLayout if vertical else QtWidgets.QHBoxLayout)(self)
        layout.setProperty("compactSpacing", 0)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)
        self.buttons = {}
        for key, text, color in [("add", "新增", "#35945b"),
                                 ("delete", "删除选中元素", "#d34b48"),
                                 ("hide", "隐藏选中元素", "#8655b2"),
                                 ("down", "已隐藏元素", "#8655b2")]:
            button = QtWidgets.QToolButton(self)
            button.setIcon(action_icon("plus" if key == "add" else key, button, color))
            button.setIconSize(QtCore.QSize(20, 20))
            button.setToolTip(text)
            button.setAccessibleName(text)
            button.setMinimumSize(26, 28)
            button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            layout.addWidget(button, 1)
            self.buttons[key] = button
            if key in {"delete", "hide"}:
                button.installEventFilter(self)
        self.vertical = vertical
        if vertical:
            self.setFixedSize(40, 136)
            for button in self.buttons.values():button.setFixedSize(34, 32)
        else:
            self.setFixedHeight(30)
            for button in self.buttons.values():
                button.setFixedHeight(24)
        self.buttons['add'].clicked.connect(self.add)
        self.buttons['delete'].clicked.connect(lambda: self.command('remove'))
        self.buttons['hide'].clicked.connect(lambda: self.command('hide'))
        self.buttons['down'].clicked.connect(self.show_hidden)
        for key in ('hide','down'):
            button=self.buttons[key]
            button.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
            button.customContextMenuRequested.connect(lambda pos:self.open_hidden_panel())
        self.sync()

    def command(self, name):
        from tailor import element_actions
        doc, chosen = self.command_target()
        if self.scope=='legend' and element_actions.target(doc) is None:
            doc.legend_controls.choose_target()
        getattr(element_actions, name)(doc, chosen=chosen)
        self.sync()

    def command_target(self):
        from tailor.element_actions import target
        doc = self.action_document()
        chosen = target(doc)
        # The legend group has always acted on its displayed object when no
        # scene element is selected. Use that same fallback for hints/commands.
        if chosen is None and self.scope == "legend":
            key = doc.legend_controls.target.currentData()
            if key == "__all__":
                chosen = ("legend", None)
            elif key is not None:
                chosen = ("legend-row", key)
        return doc, chosen

    def refresh_action_hints(self):
        from tailor.element_hints import target_caption
        doc, chosen = self.command_target()
        caption = target_caption(doc, chosen)
        for key, verb in (("delete", "删除"), ("hide", "隐藏")):
            text = verb + "：" + caption
            if key == "hide":
                text += "；右键查看已隐藏元素"
            self.buttons[key].setToolTip(text)
            self.buttons[key].setAccessibleName(text)

    def eventFilter(self, watched, event):
        if event.type() in {QtCore.QEvent.Enter, QtCore.QEvent.ToolTip}:
            self.refresh_action_hints()
        return super().eventFilter(watched, event)

    def action_document(self):
        host=getattr(self.doc,'_fit_host',None) if self.scope=='fit' else None
        if getattr(self.doc,'_visible_graph_document',None) is self.doc:host=None
        return host if host is not None and not getattr(host,'_graph_disposed',False) else self.doc

    def add(self):
        if self.add_callback:
            self.add_callback()
        elif self.scope is None:
            from tailor.element_actions import target
            chosen = target(self.doc)
            kind = chosen[0] if chosen else None
            if kind == "annotation":
                self.doc.annotations.panel.open_add_menu()
            elif kind == "inset":
                self.doc.extras.collection.add_entry(deferred=True)
            elif kind in {"legend", "legend-row"}:
                self.doc.legend_controls.add_entry()
            else:
                self.add_curves()
        else:
            self.add_curves()

    def add_curves(self):
        from tailor.document_names import sources
        from tailor.column_titles import display
        from tailor.curve_documents import add_column
        source = sources(self.doc)
        if not source:
            return
        sheet = source[0].data_sheet
        deleted = self.doc.presentation.extra_settings.get("deleted_curves", [])
        used = {p.model.y_col for p in source if p.id not in deleted}
        menu = QtWidgets.QMenu(self)
        for key in __import__("tailor.choice_catalog",fromlist=["visible_columns"]).visible_columns(sheet.model):
            if key not in used and key != source[0].model.x_col:
                menu.addAction(display(sheet.model, key),
                    lambda checked=False, k=key: add_column(self.doc, sheet, k))
        if not menu.actions():
            menu.addAction("没有未绘制的数据列").setEnabled(False)
        self.popup(menu)

    def popup(self, menu):
        self._popup = menu
        menu.setMinimumWidth(max(self.width(), 170))
        menu.popup(self.mapToGlobal(QtCore.QPoint(0, self.height())))

    def open_hidden_panel(self):
        from tailor.element_actions import menu
        menu(self.action_document(), 'hidden', scope=self.scope)

    def show_hidden(self):
        if self.vertical:
            self.open_hidden_panel()
            return
        from tailor.element_actions import hidden_items
        menu = QtWidgets.QMenu(self)
        for text, callback in hidden_items(self.action_document(), self.scope):
            menu.addAction(text, lambda checked=False, cb=callback: (cb(), self.sync()))
        if not menu.actions():
            menu.addAction("没有隐藏的元素").setEnabled(False)
        self.popup(menu)

    def sync(self):
        from tailor.element_actions import target
        selected = target(self.action_document()) is not None
        if self.scope=='legend':
            legend=getattr(self.doc,'legend_controls',None)
            selected = selected or bool(legend and legend.target.count()>1)
        self.buttons['delete'].setEnabled(selected)
        self.buttons['hide'].setEnabled(selected or self.vertical)
        if self.scope=='processing' and not hasattr(self.doc,'presentation'):
            self.buttons['hide'].setEnabled(False)
            self.buttons['down'].setEnabled(False)

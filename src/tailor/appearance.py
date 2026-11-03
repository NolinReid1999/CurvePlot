"""Independent application/workspace appearance; no changes to macOS settings."""

import weakref

import shiboken6
from PySide6 import QtCore, QtGui, QtWidgets
from tailor.crash_diagnostics import valid_event


class Appearance(QtCore.QObject):
    changed = QtCore.Signal()

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.settings = QtCore.QSettings("PhysicsPlot", "Appearance")
        self.documents = []
        self.emphasis = []
        self._pending_widgets = {}
        self._show_timer = QtCore.QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.timeout.connect(self.flush_shown_widgets)
        app.installEventFilter(self)
        self._applied_app = None
        self._applied_workspace = None
        self.system_dark = app.styleHints().colorScheme() == QtCore.Qt.ColorScheme.Dark
        self.app_mode = self.settings.value("app", "system")
        self.workspace_mode = self.settings.value("workspace", "light")
        app.styleHints().colorSchemeChanged.connect(self.system_changed)

    def dark(self, workspace=False):
        mode = self.workspace_mode if workspace else self.app_mode
        return self.system_dark if mode == "system" else mode == "dark"

    def system_changed(self, scheme):
        self.system_dark = scheme == QtCore.Qt.ColorScheme.Dark
        self.apply()

    def set_mode(self, key, mode):
        if mode not in {"light", "dark", "system"}:
            return
        if getattr(self, key + "_mode") == mode:
            return
        setattr(self, key + "_mode", mode)
        self.settings.setValue(key, mode)
        self.apply()

    def register(self, document):
        if not any(ref() is document for ref in self.documents):
            self.documents.append(weakref.ref(document))
            document._curve_theme_document = True
        QtCore.QTimer.singleShot(
            0, document,
            lambda: (
                self.apply_document(document)
                if shiboken6.isValid(document) and document.isVisible()
                else None
            ),
        )

    def register_emphasis(self, widget, kind):
        self.emphasis.append((weakref.ref(widget), kind))
        self.emphasize(widget, kind)

    def emphasize(self, widget, kind):
        colors = (
            {
                "font": ("#102a1a", "#9cd6af", "#396c49"),
                "curve": ("#38200b", "#ffbd79", "#80532a"),
            }
            if self.dark()
            else {
                "font": ("#e5f5eb", "#237342", "#a3cdb0"),
                "curve": ("#fff0df", "#a44b0a", "#e7b482"),
            }
        )[kind]
        palette = QtGui.QPalette(self.app.palette())
        for role, color in zip(
            (QtGui.QPalette.Button, QtGui.QPalette.ButtonText, QtGui.QPalette.Mid),
            colors,
            strict=True,
        ):
            palette.setColor(role, QtGui.QColor(color))
        widget.setPalette(palette)
        css = f"QPushButton {{background:{colors[0]};color:{colors[1]};border:1px solid {colors[2]};}} QPushButton:disabled {{background:palette(alternate-base);color:palette(dark);border-color:palette(mid);}}"
        if not widget.text():
            css += "QPushButton {padding:0;}"
        if widget.styleSheet() != css:
            widget.setStyleSheet(css)

    def refresh_widgets(self, root):
        for widget in [root, *root.findChildren(QtWidgets.QWidget)]:
            if shiboken6.isValid(widget) and getattr(widget, "_curve_app_dark", None) != self.dark():
                previous = getattr(widget, "_curve_app_dark", None)
                widget._curve_app_dark = self.dark()
                # Fresh widgets inherit the current application palette and
                # stylesheet. Re-polishing thousands of them after staged
                # construction repeats Qt's own initial polish synchronously.
                if previous is None:
                    continue
                # Ask QWidget directly: business/third-party widgets can use
                # "style" for their own data. Never call unpolish on that data.
                style = QtWidgets.QWidget.style(widget)
                if not isinstance(style, QtWidgets.QStyle) or not shiboken6.isValid(style):
                    from tailor.crash_diagnostics import breadcrumb
                    breadcrumb('style-wrapper-reset', widget_type=type(widget).__name__, returned_type=type(style).__name__)
                    QtWidgets.QWidget.setStyle(widget, self.app.style())
                    style = QtWidgets.QWidget.style(widget)
                style.unpolish(widget)
                widget.setPalette(self.app.palette())
                QtWidgets.QWidget.style(widget).polish(widget)
                QtWidgets.QWidget.update(widget)

    def eventFilter(self, document, event):
        if not valid_event(event, 'Appearance'):
            return True
        kind=event.type()
        if kind==QtCore.QEvent.Polish and isinstance(document,QtWidgets.QWidget):
            # Hidden pages can already have cached stylesheet brushes before
            # their first Show. Remember that theme instead of treating them
            # as freshly constructed when opened after a later theme switch.
            document._curve_app_dark=self.dark()
            return False
        if kind != QtCore.QEvent.Show or not isinstance(document, QtWidgets.QWidget):
            return False
        # QWidget::showChildren is walking the native child list here. Never
        # unpolish/repolish the subtree or alter its ownership from this callback.
        if getattr(document, "_curve_app_dark", None) != self.dark() or getattr(document, "_curve_theme_document", False):
            self._pending_widgets[id(document)] = weakref.ref(document)
            self._show_timer.start(0)
        return False

    def flush_shown_widgets(self):
        pending, self._pending_widgets = self._pending_widgets, {}
        live = [ref() for ref in pending.values() if ref() is not None and shiboken6.isValid(ref())]
        ids = {id(w) for w in live}
        for widget in live:
            parent = widget.parentWidget()
            while parent is not None and id(parent) not in ids:
                parent = parent.parentWidget()
            if parent is None:
                self.refresh_widgets(widget)
        for widget in live:
            if getattr(widget, "_curve_theme_document", False):
                self.apply_document(widget)

    def show_document(self, document):
        self.refresh_widgets(document)
        self.apply_document(document)

    def apply(self):
        from tailor.ui_theme import palette_stylesheet

        dark = self.dark()
        workspace = self.dark(True)
        app_changed = dark != self._applied_app
        workspace_changed = workspace != self._applied_workspace
        if app_changed:
            palette = self.app.style().standardPalette()
            bg, fg = ("#000000", "#e9edf4") if dark else ("#f4f6f8", "#303b49")
            base = "#000000" if dark else "#ffffff"
            for role, color in (
                (QtGui.QPalette.Window, bg),
                (QtGui.QPalette.Base, base),
                (QtGui.QPalette.AlternateBase, "#101820" if dark else "#f8f9fb"),
                (QtGui.QPalette.Button, base),
                (QtGui.QPalette.Text, fg),
                (QtGui.QPalette.WindowText, fg),
                (QtGui.QPalette.ButtonText, fg),
                (QtGui.QPalette.ToolTipBase, base),
                (QtGui.QPalette.ToolTipText, fg),
                (QtGui.QPalette.Mid, "#303640" if dark else "#d5dce5"),
                (QtGui.QPalette.Midlight, "#3a424e" if dark else "#c7ced8"),
                (QtGui.QPalette.Dark, "#697786" if dark else "#a5adb7"),
                (QtGui.QPalette.PlaceholderText, "#a6b1c0" if dark else "#7b8795"),
                (QtGui.QPalette.Link, "#70b4ff" if dark else "#246fc2"),
                (QtGui.QPalette.Highlight, "#173b62" if dark else "#dceaff"),
                (QtGui.QPalette.HighlightedText, "#ffffff"),
            ):
                palette.setColor(role, QtGui.QColor(color))
            self.app.setPalette(palette)
            if not getattr(self, "_css_installed", False):
                self.app.setStyleSheet(palette_stylesheet())
                self._css_installed = True
            for ref, kind in list(self.emphasis):
                widget = ref()
                if widget is not None and shiboken6.isValid(widget):
                    self.emphasize(widget, kind)
                else:
                    self.emphasis.remove((ref, kind))
            # Qt caches palette() brushes in stylesheet rules. Repolish visible UI only.
            for window in self.app.topLevelWidgets():
                if isinstance(window, QtWidgets.QWidget) and shiboken6.isValid(window) and window.isVisible():
                    self.refresh_widgets(window)
            self._applied_app = dark
        if workspace_changed or app_changed:
            self._applied_workspace = workspace
            for ref in list(self.documents):
                obj = ref()
                if obj is None or not shiboken6.isValid(obj):
                    self.documents.remove(ref)
                elif obj.isVisible():
                    self.apply_document(obj, force=app_changed)
        if app_changed or workspace_changed:
            self.changed.emit()

    def apply_document(self, doc, force=False):
        if getattr(doc, "_graph_disposed", False):
            return
        dark = self.dark(True)
        if not force and getattr(doc, "_workspace_dark", None) == dark:
            return
        doc._workspace_dark = dark
        bg, fg = ("#000000", "#eeeeee") if dark else ("#ffffff", "#303b49")
        edge = "#30343a" if dark else "#e1e6ed"
        selection_bg,selection_fg = ("#285b92","#ffffff") if dark else ("#e1edfc","#203c60")
        sheet = f"""QWidget {{ color: {fg}; background: {bg}; }}
            QTableView {{ background: {bg}; alternate-background-color: {bg}; gridline-color: {edge}; selection-background-color: {selection_bg}; selection-color: {selection_fg}; }}
            QHeaderView::section {{ background: {bg}; color: {fg}; border-right: 1px solid {edge}; border-bottom: 1px solid {edge}; }}
            QLineEdit, QComboBox {{ background: {bg}; color: {fg}; }}
            QWidget[foldCard="true"] {{ background: {bg}; border-color: {edge}; }}"""
        ui = getattr(doc, "ui", None)
        table = getattr(ui, "data_view", None)
        if table is not None:
            table.setStyleSheet(sheet)
            palette = QtGui.QPalette(self.app.palette())
            for role, color in (
                (QtGui.QPalette.Window, bg),
                (QtGui.QPalette.Base, bg),
                (QtGui.QPalette.AlternateBase, bg),
                (QtGui.QPalette.Text, fg),
                (QtGui.QPalette.Highlight, selection_bg),
                (QtGui.QPalette.HighlightedText, selection_fg),
                (QtGui.QPalette.WindowText, fg),
                (QtGui.QPalette.Mid, edge),
            ):
                palette.setColor(role, QtGui.QColor(color))
            table.setPalette(palette)
            table.horizontalHeader().setPalette(palette)
            table.verticalHeader().setPalette(palette)
        if getattr(doc, "document_kind", "") == "fit":
            doc.setStyleSheet(sheet)
            doc.residual.setBackground(bg)
            for side in ("bottom", "left"):
                doc.residual.getAxis(side).setPen(fg)
                doc.residual.getAxis(side).setTextPen(fg)
        if hasattr(doc, "presentation"):
            from tailor.workspace_theme import apply_plot_theme

            apply_plot_theme(doc, bg)


def initialize_canvas(widget):
    """Give new canvases their workspace colour before staged UI can paint."""
    color = QtGui.QColor('#000000' if manager().dark(True) else '#ffffff')
    widget.setBackground(color)
    palette = QtGui.QPalette(widget.palette())
    palette.setColor(QtGui.QPalette.Base, color)
    palette.setColor(QtGui.QPalette.Window, color)
    widget.viewport().setPalette(palette)


def manager():
    app = QtWidgets.QApplication.instance()
    if not hasattr(app, "_physicsplot_appearance"):
        from tailor.ui_theme import setup_application_style

        setup_application_style()
    return app._physicsplot_appearance


def ink(color, workspace=True):
    """Keep black/white ink legible on the chosen canvas; saved colors stay intact."""
    appearance = getattr(
        QtWidgets.QApplication.instance(), "_physicsplot_appearance", None
    )
    if appearance is None:
        return color
    if appearance.dark(workspace) and QtGui.QColor(color).name().lower() in {
        "#202020",
        "#000000",
        "#303b49",
    }:
        return "#eeeeee"
    return color


def settings_page(document):
    from tailor.fold_panel import FoldPanel
    from tailor.graph_controls import combo
    from tailor.physicsplot_desktop import APP_NAME, FULL_NAME, version_label

    state = manager()
    panel = FoldPanel(document)
    form = QtWidgets.QFormLayout()
    for title, key in (("应用颜色", "app"), ("工作区颜色", "workspace")):
        box = combo(
            [("浅色", "light"), ("深色 · 纯黑", "dark"), ("跟随系统", "system")]
        )
        box.setCurrentIndex(box.findData(getattr(state, key + "_mode")))
        box.activated.connect(
            lambda index, box=box, key=key: state.set_mode(key, box.itemData(index))
        )

        def sync(box=box, key=key):
            if not shiboken6.isValid(box):
                return
            with QtCore.QSignalBlocker(box):
                box.setCurrentIndex(box.findData(getattr(state, key + "_mode")))

        state.changed.connect(sync)
        box.destroyed.connect(lambda *args, sync=sync: state.changed.disconnect(sync))
        form.addRow(title, box)
    note = QtWidgets.QLabel(
        "应用颜色控制标签和功能区；工作区颜色控制图、表和拟合结果。导出沿用当前图形背景，也可选择透明背景。"
    )
    note.setWordWrap(True)
    form.addRow(note)
    panel.add_section("颜色模式", form, True)
    panel.add_section(
        "关于", QtWidgets.QLabel(f"{APP_NAME} · {FULL_NAME}\n{version_label()}\n主开发者：NolinReid\n协作开发：Codex\n基于 Tailor，GPL-3.0-or-later"), True
    )
    state.register(document)
    return panel

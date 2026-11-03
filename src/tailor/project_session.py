"""Reuse Tailor project controllers inside one persistent native window."""

from pathlib import Path

from PySide6 import QtCore, QtWidgets


class ProjectHost(QtWidgets.QMainWindow):
    def __init__(self, session):
        super().__init__()
        self.session = session
        self.stack = QtWidgets.QStackedWidget(self)
        self.setCentralWidget(self.stack)
        self.menuBar().setNativeMenuBar(True)
        self._geometry_settings = QtCore.QSettings("PhysicsPlot", "Window")
        self._geometry_timer = QtCore.QTimer(self)
        self._geometry_timer.setSingleShot(True)
        self._geometry_timer.timeout.connect(self.save_window_geometry)
        self.resize(1100, 750)
        saved = self._geometry_settings.value("geometry")
        if isinstance(saved, QtCore.QByteArray):
            self.restoreGeometry(saved)
            self.setWindowState(self.windowState() & ~QtCore.Qt.WindowMinimized)
        QtWidgets.QApplication.instance().aboutToQuit.connect(self.save_window_geometry)

    def save_window_geometry(self):
        self._geometry_timer.stop()
        self._geometry_settings.setValue("geometry", self.saveGeometry())
        self._geometry_settings.sync()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.isVisible():
            self._geometry_timer.start(300)

    def moveEvent(self, event):
        super().moveEvent(event)
        if self.isVisible():
            self._geometry_timer.start(300)

    def hideEvent(self, event):
        self.save_window_geometry()
        super().hideEvent(event)

    def closeEvent(self, event):
        app = QtWidgets.QApplication.instance()
        if self.session.quitting or getattr(app, "_allow_quit", False):
            event.accept()
            return
        # The red window button only hides the workspace, retaining unsaved projects.
        event.ignore()
        self.hide()


class ProjectSession(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.windows = []
        self.serial = 0
        self.quitting = False
        self.host = ProjectHost(self)
        self.active = None
        self.project_type = None

    def next_name(self):
        self.serial += 1
        return f"项目{self.serial}"

    def register(self, window):
        self.project_type = type(window)
        self.windows.append(window)
        window.setParent(self.host.stack, QtCore.Qt.Widget)
        window.menuBar().hide()
        self.host.stack.addWidget(window)
        window.windowTitleChanged.connect(
            lambda title, w=window: (
                self.host.setWindowTitle(title) if self.active is w else None
            )
        )
        self.refresh()

    def refresh(self):
        for window in self.windows:
            if hasattr(window, "tab_controls"):
                window.tab_controls.refresh_project_name()

    def activate(self, window):
        if window not in self.windows:
            return
        self.active = window
        self.host.setUpdatesEnabled(False)
        try:
            self.host.stack.setCurrentWidget(window)
            menus = self.host.menuBar()
            menus.clear()
            for action in window.menuBar().actions():
                menus.addAction(action)
            self.host.setWindowTitle(window.windowTitle())
            self.host.setWindowIcon(window.windowIcon())
        finally:
            self.host.setUpdatesEnabled(True)
        if not self.host.isVisible():
            self.host.show()
        self.host.raise_()
        self.host.activateWindow()
        QtWidgets.QApplication.instance().window = window
        self.refresh()

    def reopen(self):
        if self.windows:
            self.activate(
                self.active if self.active in self.windows else self.windows[-1]
            )
        elif self.project_type is not None:
            self.activate(self.project_type(projects=self))

    def create(self, owner):
        window = type(owner)(projects=self)
        self.activate(window)
        return window

    def open(self, owner, filename):
        path = Path(filename).resolve()
        for window in self.windows:
            if (
                window._project_filename
                and Path(window._project_filename).resolve() == path
            ):
                self.activate(window)
                return window
        # Opening a file never consumes the current project, even if it is an
        # untouched blank. load_project remains the low-level restore operation
        # and only runs on this new controller.
        previous = self.active
        window = type(owner)(projects=self)
        if window.load_project(path):
            self.activate(window)
            return window
        window.mark_project_dirty(False)
        window.close()
        if previous in self.windows:
            self.activate(previous)
        return None

    def closed(self, window):
        if window in self.windows:
            self.windows.remove(window)
            self.host.stack.removeWidget(window)
            window.hide()
            # Closing a project is permanent for this session, whereas the
            # host's red window button deliberately only hides the workspace.
            window.deleteLater()
        if self.quitting:
            QtCore.QTimer.singleShot(0, self, self.quit_all)
        elif self.windows:
            self.activate(self.windows[-1])
        else:
            self.active = None
            QtWidgets.QApplication.instance().window=None
            self.host.hide()
        self.refresh()

    def quit_all(self):
        app = QtWidgets.QApplication.instance()
        if not self.windows:
            app._allow_quit = True
            app.quit()
            return
        self.quitting = True
        window = self.active if self.active in self.windows else self.windows[-1]
        # Keep saved/unsaved-project protection, but do not cycle native windows.
        self.activate(window)
        if not window.close() and not window.project_save_busy():
            self.quitting = False

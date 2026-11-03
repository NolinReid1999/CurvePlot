"""Recoverable .cur copies using the existing detached snapshot writer."""
import uuid
import json
from datetime import datetime
from pathlib import Path
from PySide6 import QtCore, QtWidgets
from tailor.app_preferences import preferences
from tailor.project_writer import ProjectWriter


def folder():
    return Path(QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.GenericDataLocation)) / 'Curve' / 'Recovery'


def entries():
    found=[]
    for path in folder().glob('*.cur'):
        try:
            if path.is_file(): found.append((path.stat().st_mtime,path))
        except OSError:
            continue
    return [path for _,path in sorted(found, reverse=True)]


class Inventory(QtCore.QObject):
    changed = QtCore.Signal()


def inventory():
    app = QtWidgets.QApplication.instance()
    if not hasattr(app, '_curve_recovery_inventory'):
        app._curve_recovery_inventory = Inventory(app)
    return app._curve_recovery_inventory


class Recovery(QtCore.QObject):
    updated = QtCore.Signal()

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.token = uuid.uuid4().hex
        self.job = None
        self.pending = False
        self.saved_revision = -1
        self.last_error = ''
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.capture)
        preferences().changed.connect(self.configure)
        self.configure()
        app = QtWidgets.QApplication.instance()
        if not getattr(app, '_curve_recovery_hint', False):
            app._curve_recovery_hint = True
            if entries():
                QtCore.QTimer.singleShot(500, self, lambda: owner.statusBar().showMessage('发现本地恢复快照，可在设置“自动保存与恢复”中查看。'))

    def busy(self):
        return self.pending or bool(self.job and self.job.isRunning())

    def configure(self, key='recovery/'):
        if key.startswith('recovery/'):
            self.timer.stop()
            if preferences().get('recovery/enabled'):
                self.timer.start(preferences().get('recovery/minutes') * 60000)

    def capture(self, force=False):
        owner = self.owner
        if self.busy() or owner.data_operation_busy() or not owner._is_dirty:
            return False
        if not force and self.saved_revision == owner._project_revision:
            return False
        try:
            from tailor.project_files import capture_project_snapshot
            snapshot = capture_project_snapshot(owner)
            folder().mkdir(parents=True, exist_ok=True, mode=0o700)
            name = f'{self.token}-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.cur'
            self.revision = owner._project_revision
            if self.job:
                self.job.deleteLater()
            self.job = ProjectWriter(snapshot, folder() / name, self)
            self.job.finished.connect(self.finished)
            self.pending = True
            self.job.start()
            return True
        except Exception as error:
            self.pending = False
            self.last_error = str(error)
            owner.statusBar().showMessage('自动恢复快照未保存，请手动保存工程。')
            self.updated.emit()
            return False

    def finished(self):
        self.pending = False
        if self.job.outcome == 'saved':
            self.saved_revision = self.revision
            self.last_error = ''
            try:
                self.job.filename.with_suffix('.json').write_text(json.dumps({'project': self.owner.project_name}, ensure_ascii=False))
            except OSError:
                pass
            own = [p for p in entries() if p.name.startswith(self.token + '-')]
            for path in own[preferences().get('recovery/versions'):]:
                try:
                    path.unlink()
                    path.with_suffix('.json').unlink(missing_ok=True)
                except OSError:
                    pass
        else:
            self.last_error = self.job.error or '恢复快照已取消'
        self.updated.emit()
        inventory().changed.emit()
        if self.owner.projects.quitting:
            QtCore.QTimer.singleShot(0, self.owner.projects, self.owner.projects.quit_all)


def restore(owner, path):
    """Open a separate editable project, then require Save As for the recovery."""
    if owner.data_operation_busy():
        return None
    window = owner.projects.create(owner)
    if not window.load_project(path, record_recent=False):
        window.mark_project_dirty(False)
        window.close()
        return None
    window._project_filename = None
    window.mark_project_dirty()
    return window

"""Project-save coordination; only the GUI thread decides clean/close state."""

from pathlib import Path

from PySide6 import QtCore, QtWidgets

from tailor import project_files
from tailor.app import CSV_FILE_FILTER, TAILOR_PROJECT_FILTER
from tailor.project_writer import CsvWriter, ProjectWriter


class ProjectActions:
    def project_save_busy(self):
        import shiboken6
        if not shiboken6.isValid(self):
            return False
        if self._saver is not None and not shiboken6.isValid(self._saver):
            return False
        recovery = getattr(self, 'recovery', None)
        return bool(recovery and recovery.busy()) or self._saver is not None and (
            self._save_pending or self._saver.isRunning()
        )

    def csv_import_busy(self):
        return self._reader is not None and (
            self._reader_pending or self._reader.isRunning()
        )

    def data_operation_busy(self):
        return (
            getattr(self, "_project_reveal_pending", False)
            or getattr(self, "_fit_busy", False)
            or getattr(self, "_axis_transform_busy", False)
            or getattr(self, "_processing_busy", False)
            or self.project_save_busy()
            or self.csv_export_busy()
            or self.csv_import_busy()
            or any(sheet.clipboard_busy() for sheet in self.get_data_sheets())
            or self.graph_initialization_busy()
        )

    def graph_initialization_busy(self, *, include_reveal=True):
        if include_reveal and getattr(self, '_project_reveal_pending', False):
            return True
        tabs = self.ui.tabWidget
        pending = [tabs.widget(index) for index in range(tabs.count())]
        seen = set()
        while pending:
            plot = pending.pop()
            if id(plot) in seen:
                continue
            seen.add(id(plot))
            if getattr(plot, "_inspector_initializing", False):
                return True
            # Multi-curve sources are intentionally absent from the tab bar.
            # Their inspectors are staged after the host; saving/fitting must
            # stay blocked until those source documents are ready as well.
            pending.extend(getattr(getattr(plot, "model", None), "_plots", {}))
            advanced = getattr(plot, "advanced_view", None)
            if advanced and getattr(advanced, "initializing", False):
                return True
            native = getattr(advanced, "native", None)
            if native:
                pending.extend(native.live())
            collection = getattr(getattr(plot, "extras", None), "collection", None)
            if collection:
                pending.extend(
                    e.inset_doc for e in collection.controllers.values()
                    if hasattr(e, "inset_doc")
                )
        return False

    def csv_export_busy(self):
        return self._csv_writer is not None and (
            self._csv_pending or self._csv_writer.isRunning()
        )

    def export_csv(self):
        if self.data_operation_busy():
            self.statusBar().showMessage("后台数据操作尚未结束，请等待或取消后导出。")
            return
        sheet = self._on_data_sheet()
        if sheet is None:
            return
        filename = self.get_save_filename_dialog(filter=CSV_FILE_FILTER)
        if filename:
            self.set_recent_directory(Path(filename).parent)
            self.start_csv_export(sheet, filename)

    def export_excel(self):
        if self.data_operation_busy():
            self.statusBar().showMessage("请等待当前数据操作结束后导出")
            return
        sheet = self._on_data_sheet()
        if sheet is None:
            return
        filename = self.get_save_filename_dialog(filter="Excel 工作簿 (*.xlsx)")
        if filename:
            filename = str(Path(filename).with_suffix(".xlsx"))
            self.set_recent_directory(Path(filename).parent)
            self.start_csv_export(sheet, filename)

    def start_csv_export(self, sheet, filename):
        if self.data_operation_busy():
            return False
        data = sheet.model.data_model
        snapshot = {
            name: data._data[label].to_numpy(copy=True)
            for label, name in zip(
                data.get_column_labels(), data.get_column_names(), strict=True
            )
        }
        return self.start_csv_snapshot_export(snapshot, filename)

    def start_csv_snapshot_export(self, snapshot, filename):
        """Share the existing atomic background exporter with fit results."""
        if self.data_operation_busy():
            self.statusBar().showMessage("后台数据操作尚未结束，请等待或取消后导出。")
            return False
        if self._csv_writer is not None:
            self._csv_writer.deleteLater()
        if hasattr(self, "_csv_progress"):
            self._csv_progress.deleteLater()
        self._csv_progress = QtWidgets.QProgressDialog(
            "正在导出 Excel…"
            if Path(filename).suffix.lower() == ".xlsx"
            else "正在导出 CSV…",
            "取消导出",
            0,
            100,
            self,
        )
        self._csv_progress.setWindowModality(QtCore.Qt.NonModal)
        self._csv_progress.setMinimumDuration(0)
        self._csv_progress.setAutoClose(False)
        self._csv_progress.setValue(0)
        self._csv_writer = CsvWriter(snapshot, filename, self)
        self._csv_progress.canceled.connect(self._csv_writer.requestInterruption)
        self._csv_writer.progress.connect(self._csv_progress.setValue)
        self._csv_writer.finished.connect(self._after_csv_export)
        self._csv_pending = True
        self._csv_writer.start()
        return True

    def _after_csv_export(self):
        self._csv_pending = False
        self._csv_progress.reset()
        self._csv_progress.hide()
        job = self._csv_writer
        if job.outcome == "saved":
            self.statusBar().showMessage(f"已导出开始时的数据快照：{job.filename.name}")
        elif job.outcome == "cancelled":
            self.statusBar().showMessage("已取消导出，原文件和工作表均保留。")
        else:
            QtWidgets.QMessageBox.warning(
                self, "导出失败，原文件和工作表均保留", job.error
            )

    def mark_project_dirty(self, is_dirty=True):
        if is_dirty:
            self._project_revision += 1
        super().mark_project_dirty(is_dirty)

    def save_project_or_dialog(self, checked=False, *, after_save=None):
        if self.project_save_busy():
            self.statusBar().showMessage("工程正在保存，请等待完成或取消。")
            return False
        if self._project_filename is None:
            return self.save_as_project_dialog(after_save=after_save)
        return self.save_project(self._project_filename, after_save=after_save)

    def save_as_project_dialog(self, checked=False, *, after_save=None):
        if self.project_save_busy():
            return False
        filename = self.get_save_filename_dialog(filter=TAILOR_PROJECT_FILTER)
        if not filename:
            return False
        filename = (
            str(Path(filename).with_suffix(".cur"))
            if Path(filename).suffix.lower() != ".cur"
            else filename
        )
        self.set_recent_directory(Path(filename).parent)
        return self.save_project(filename, after_save=after_save)

    def save_project(self, filename, *, after_save=None):
        if self.data_operation_busy():
            self.statusBar().showMessage("后台数据操作尚未结束，请等待或取消后保存。")
            return False
        try:
            snapshot = project_files.capture_project_snapshot(self)
        except Exception as error:  # noqa: BLE001 - snapshot failures must preserve dirty project
            QtWidgets.QMessageBox.warning(
                self, "未能准备保存，当前工程已保留", str(error)
            )
            return False
        if self._saver is not None:
            self._saver.deleteLater()
        self._save_revision = self._project_revision
        self._save_continuation = after_save
        if hasattr(self, "_save_progress"):
            self._save_progress.deleteLater()
        previous = getattr(self, "_save_progress", None)
        if previous is not None:
            previous.deleteLater()
        self._save_progress = QtWidgets.QProgressDialog(
            "正在后台保存工程…", "取消保存", 0, 100, self
        )
        self._save_progress.setWindowModality(QtCore.Qt.NonModal)
        self._save_progress.setMinimumDuration(0)
        self._save_progress.setAutoClose(False)
        self._save_progress.setValue(0)
        self._saver = ProjectWriter(snapshot, filename, self)
        self._save_progress.canceled.connect(self._saver.requestInterruption)
        self._saver.progress.connect(self._save_progress.setValue)
        self._saver.finished.connect(self._after_project_save)
        self._save_pending = True
        self._saver.start()
        return True

    def _after_project_save(self):
        job = self._saver
        self._save_pending = False
        self._save_progress.reset()
        self._save_progress.hide()
        continuation, self._save_continuation = self._save_continuation, None
        if hasattr(self, "projects") and (
            job.outcome != "saved" or self._save_revision != self._project_revision
        ):
            self.projects.quitting = False
        if job.outcome == "saved":
            self._set_project_path(job.filename)
            self.update_recent_files(str(job.filename))
            revision = self._save_revision
            if revision == self._project_revision:
                self.mark_project_dirty(False)
                self.statusBar().showMessage("工程已保存。")
                if continuation is not None:

                    def proceed():
                        # An input event can arrive between completion and this callback.
                        if revision == self._project_revision and not self._is_dirty:
                            continuation()
                        else:
                            if hasattr(self, "projects"):
                                self.projects.quitting = False
                            self.statusBar().showMessage(
                                "工程有新的修改，未执行关闭或替换。"
                            )

                    QtCore.QTimer.singleShot(0, self, proceed)
            else:
                self.statusBar().showMessage(
                    "已保存开始时的工程快照；后续修改尚未保存，未执行关闭或替换。"
                )
        elif job.outcome == "cancelled":
            self.statusBar().showMessage("已取消保存，原工程文件和当前修改均保留。")
        else:
            QtWidgets.QMessageBox.warning(
                self, "保存失败，原文件和当前修改均保留", job.error
            )

    def _can_replace_project(self, after_save):
        previous = getattr(self, "_after_save_action", None)
        self._after_save_action = after_save
        try:
            return self.confirm_project_close_dialog()
        finally:
            self._after_save_action = previous

    def confirm_project_close_dialog(self):
        if self.project_save_busy():
            self.statusBar().showMessage('正在保存工程或恢复快照，请等待完成后关闭。')
            return False
        if not self._is_dirty:
            return True
        answer = QtWidgets.QMessageBox.warning(
            self,
            "保存工程",
            "当前工程有未保存的修改。",
            buttons=(
                QtWidgets.QMessageBox.Save
                | QtWidgets.QMessageBox.Discard
                | QtWidgets.QMessageBox.Cancel
            ),
            defaultButton=QtWidgets.QMessageBox.Cancel,
        )
        if answer == QtWidgets.QMessageBox.Discard:
            return True
        if answer == QtWidgets.QMessageBox.Save:
            self.save_project_or_dialog(
                after_save=getattr(self, "_after_save_action", None)
            )
        # Save-as cancellation, worker failure and cancellation never authorize discard.
        return False

    def open_project_dialog(self, event=None, filename=None):
        session = getattr(self, 'projects', None)
        if session is not None:
            # A separate project does not replace or discard this controller,
            # so its dirty state/background tasks do not need closing approval.
            if filename is None:
                filename = self.get_open_filename_dialog(filter=TAILOR_PROJECT_FILTER)
            if filename:
                self.set_recent_directory(Path(filename).parent)
                return session.open(self, filename)
            return None
        if self.data_operation_busy():
            self.statusBar().showMessage(
                "后台数据操作尚未结束，请等待或取消后打开工程。"
            )
            return
        if not self._can_replace_project(
            lambda: self.open_project_dialog(filename=filename)
        ):
            return
        if filename is None:
            filename = self.get_open_filename_dialog(filter=TAILOR_PROJECT_FILTER)
        if filename:
            self.set_recent_directory(Path(filename).parent)
            self.load_project(filename)

    def open_recent_project_action(self, filename):
        self.open_project_dialog(filename=filename)

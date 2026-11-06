"""PhysicsPlot trial entry point, retaining Tailor's existing workflows."""

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from tailor import config, project_files
from tailor.crash_diagnostics import valid_event
from tailor.app import MainWindow
from tailor.csv_format_dialog import CSVFormatDialog, FormatParameters
from tailor.data_model import DataModel
from tailor.data_sheet import DataSheet
from tailor.project_actions import ProjectActions

from tailor.version import VERSION, BUILD, version_label
APP_NAME = "Curve"
FULL_NAME = "CurvePlot"


class CsvReader(QtCore.QThread):
    loaded = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, filename, parameters, parent=None):
        super().__init__(parent)
        self.filename, self.parameters = filename, parameters

    def run(self):
        try:
            data = DataModel()
            if isinstance(self.parameters, dict) and "excel_sheet" in self.parameters:
                from tailor.excel_import import read_excel

                data = read_excel(self.filename, self.parameters)
            else:
                data.import_csv(self.filename, self.parameters)
            self.loaded.emit(data)
        except Exception as exc:  # noqa: BLE001 - relay worker failure
            self.failed.emit(str(exc))


class PhysicsPlotWindow(ProjectActions, MainWindow):
    def __init__(self, projects=None):
        from tailor.gui_lifecycle import install_gui_collector
        install_gui_collector()
        from tailor.project_session import ProjectSession

        self.projects = projects if projects is not None else ProjectSession()
        self.project_name = self.projects.next_name()
        self._reader = None
        self._reader_pending = False
        self._saver = None
        self._save_pending = False
        self._csv_writer = None
        self._csv_pending = False
        self._project_revision = 0
        self._csv_queue = []
        from tailor.ui_theme import setup_application_style

        setup_application_style()
        super().__init__(add_sheet=True)
        self.setAcceptDrops(True)
        from tailor.popup_controls import install_popup_policy

        install_popup_policy(self)
        from tailor.ui_theme import apply_theme

        apply_theme(self)
        self.setup_project_navigation()
        self.ui.actionAdd_Data_Sheet.setVisible(False)
        self.ui.actionDuplicate_Data_Sheet.setVisible(False) if hasattr(
            self.ui, "actionDuplicate_Data_Sheet"
        ) else None
        self.projects.register(self)
        self.ui.actionQuit.triggered.disconnect()
        self.ui.actionQuit.triggered.connect(self.projects.quit_all)
        self.ui.actionClose.triggered.disconnect()
        self.ui.actionClose.triggered.connect(self.projects.host.hide)
        self.ui.actionAbout_Tailor.setText(f"关于 {APP_NAME}…")
        self.ui.actionCheck_for_updates.setText("检查更新…")
        self.ui.actionCheck_for_updates.setVisible(True)
        self.svg_export_action = QtGui.QAction("导出图形为 SVG…", self)
        self.svg_export_action.triggered.connect(lambda: self.export_graph(".svg"))
        self.ui.menuFile.addAction(self.svg_export_action)
        example = QtGui.QAction("打开合成示例", self)
        example.triggered.connect(self.open_example)
        from tailor.product_shell import setup_menus

        setup_menus(self)
        self.ui.menuHelp.addAction(example)
        self.manual_action = QtGui.QAction("新功能详尽手册…", self)
        self.manual_action.triggered.connect(self.open_manual)
        self.ui.menuHelp.addAction(self.manual_action)
        bands_help = QtGui.QAction("置信带与预测带指南…", self)
        def open_bands():
            import sys
            base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
            candidates = [base/"docs/Curve-置信带与预测带指南-0.5.pdf", base/"output/pdf/Curve-置信带与预测带指南-0.5.pdf"]
            path = next((p for p in candidates if p.exists()), None)
            if path:
                QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))
        bands_help.triggered.connect(open_bands)
        self.ui.menuHelp.addAction(bands_help)
        from tailor.recovery import Recovery
        self.recovery = Recovery(self)

    def check_for_updates(self, silent=False):
        from tailor.update_check import for_application
        return for_application().check(manual=not silent)

    def manual_path(self):
        if getattr(sys, "frozen", False):
            return Path(sys._MEIPASS) / "docs/Curve-功能手册-alpha.27.pdf"
        return (
            Path(__file__).resolve().parents[2]
            / "output/pdf/Curve-功能手册-alpha.27.pdf"
        )

    def open_manual(self):
        path = self.manual_path()
        if path.exists():
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))
        else:
            self.statusBar().showMessage("未找到功能手册，请检查安装文件。")

    def create_plot_tab(self, data_sheet, x_var, y_var, x_err=None, y_err=None):
        if any(p.data_sheet is data_sheet and p.model.y_col == y_var and p.model.x_col != x_var for p in self.get_plots()):
            self.statusBar().showMessage("不支持同一Y列同时对应不同X列；请复制Y列后再绘图。", 8000)
            return None
        for label in (x_err, y_err):
            if label is not None:
                values = np.asarray(data_sheet.model.data_model.get_column(label))
                if np.any(np.isfinite(values) & (values < 0)):
                    self.statusBar().showMessage(
                        f"误差列 {data_sheet.model.data_model.get_column_name(label)} 包含负值，未创建图形。"
                    )
                    return None
        plot = super().create_plot_tab(data_sheet, x_var, y_var, x_err, y_err)
        from tailor.column_titles import remark
        from tailor.text_style_controls import apply_text_styles

        plot.model.x_label = remark(data_sheet.model, x_var)
        plot.model.y_label = remark(data_sheet.model, y_var)
        apply_text_styles(plot)
        return plot

    def ask_and_create_plot_tab(self, columns=None):
        if isinstance(columns,bool):columns=None  # QAction.triggered(bool) compatibility
        if (
            getattr(self.ui.tabWidget.currentWidget(), "advanced_view", None)
            is not None
        ):
            self.statusBar().showMessage(
                "当前为高级绘图，请使用高级标签，或切回工作表退出高级模式。"
            )
            return None
        sheet = self._on_data_sheet()
        if sheet is not None and getattr(sheet, "_advanced_mode", None):
            self.statusBar().showMessage(
                "高级模式中请在高级标签绘图，或先退出高级模式。"
            )
            return None
        if sheet is None:
            return None
        if sheet.model.columnCount() == 1 and sheet.model.rowCount():
            # A one-column instrument trace uses a generated index, never overwrites its values.
            sheet.model.set_column_metadata(0, role="Y")
            if not sheet.model.append_column(
                np.arange(1, sheet.model.rowCount() + 1, dtype=float),
                name="Row",
                role="X",
                source="生成行号；原始数据保持不变",
            ):
                return None
        selected = sorted(
            {
                column
                for block in sheet.selection.selection()
                for column in range(block.left(), block.right() + 1)
            }
        )
        roles = [
            sheet.model.column_metadata(column)["role"]
            for column in range(sheet.model.columnCount())
        ]
        xs = [column for column in selected if roles[column] == "X"]
        if not xs:
            xs = [column for column, role in enumerate(roles) if role == "X"]
        candidates = [c for c in selected if roles[c] == "Y"]
        if len(candidates) == 1 and not any(roles[c] == "X" for c in selected):
            import json

            keys = list(sheet.model.columnLabels())
            try:
                source = json.loads(
                    sheet.model.column_metadata(candidates[0]).get("source") or "{}"
                )
                paired = source.get("result_x") or source.get("x")
                if paired in keys:
                    xs = [keys.index(paired)]
            except (ValueError, TypeError):
                pass
        picker=getattr(sheet,'plot_type_picker',None)
        if columns is None and picker is not None and picker._axis_y_keys is not None:
            columns=picker.axis_columns()
        if columns is not None:xs=list(columns[0])
        if len(xs) != 1:
            if columns is not None:
                self.statusBar().showMessage('请选择一个X列和至少一个Y列。',5000);return None
            return super().ask_and_create_plot_tab()
        x = xs[0]
        ys = [
            column
            for column in selected
            if column != x and roles[column] not in {"X", "XErr", "YErr"}
        ]
        if not ys:
            ys = [column for column, role in enumerate(roles) if role == "Y"]
        if columns is not None:ys=list(columns[1])
        if not ys:
            if columns is not None:
                self.statusBar().showMessage('请添加至少一个Y列。',5000);return None
            return super().ask_and_create_plot_tab()
        labels = sheet.model.columnLabels()
        x_values = np.asarray(
            __import__("pandas").to_numeric(
                sheet.model.data_model.get_column(labels[x]), errors="coerce"
            ),
            dtype=float,
        )
        if not np.isfinite(x_values).any():
            import pandas as pd

            from tailor.axis_extensions import convert_series

            raw = pd.Series(sheet.model.data_model.get_column(labels[x]))
            dates = pd.to_datetime(raw, errors="coerce", utc=True, format="mixed")
            converted, _ = convert_series(
                raw,
                "datetime"
                if dates.notna().sum() >= max(1, raw.notna().sum()) * 0.8
                else "category",
            )
            x_values = np.asarray(converted, dtype=float)
        for column in ys:
            y_values = np.asarray(
                __import__("pandas").to_numeric(
                    sheet.model.data_model.get_column(labels[column]), errors="coerce"
                ),
                dtype=float,
            )
            if not np.any(np.isfinite(x_values) & np.isfinite(y_values)):
                self.statusBar().showMessage(
                    f"列 {sheet.model.columnName(column)} 没有与 X 对应的有效数值，未创建图形。"
                )
                return None
        xerr = [column for column, role in enumerate(roles) if role == "XErr"]
        yerr = [column for column, role in enumerate(roles) if role == "YErr"]
        if any(
            np.any(
                np.isfinite(sheet.model.data_model.get_column(labels[column]))
                & (sheet.model.data_model.get_column(labels[column]) < 0)
            )
            for column in xerr + yerr
        ):
            self.statusBar().showMessage("误差角色的列中包含负值，请修正后绘图。")
            return None
        from tailor.curve_documents import create_source, create_group
        plots = []
        for column in ys:
            error = (column + 1 if column + 1 in yerr else
                     yerr[0] if len(yerr) == 1 and len(ys) == 1 else None)
            plot = (self.create_plot_tab if len(ys) == 1 else
                    lambda *args: create_source(self, *args))(
                sheet, labels[x], labels[column],
                labels[xerr[0]] if len(xerr) == 1 else None,
                labels[error] if error is not None else None,
            )
            if plot is None:
                return None
            plots.append(plot)
        result = plots[0] if len(plots) == 1 else create_group(self, plots)
        self.refresh_project_tree()
        return result

    def close_tab_with_children(self, close_idx):
        tab = self.ui.tabWidget.widget(close_idx)
        if isinstance(tab, DataSheet) and getattr(tab, "_default_sheet", False):
            return
        from tailor.window_mode import graph
        if graph(tab):
            from tailor.document_names import delete
            delete(self,tab)
            return
        from tailor.app import TabbedWidget

        tab = self.ui.tabWidget.widget(close_idx)
        if tab is None or self.data_operation_busy():
            return
        associated = (
            []
            if not isinstance(tab, DataSheet) and tab not in self.get_plots()
            else self.get_associated_tabs(TabbedWidget(widget=tab, index=close_idx))
        )
        self.close_tabs([tab, *associated])

    def setup_project_navigation(self):
        from tailor.tab_controls import TabControls

        self.tab_controls = TabControls(self)
        if self.ui.centralwidget.layout() is not None:
            self.ui.centralwidget.layout().setContentsMargins(0, 0, 0, 0)
        self.ui.tabWidget.tabBar().setMovable(True)
        self.ui.tabWidget.tabBar().tabMoved.connect(
            lambda *_: self.mark_project_dirty()
        )
        view_menu = self.menuBar().addMenu("视图")
        self.properties_action = view_menu.addAction("属性面板")
        self.properties_action.setCheckable(True)
        self.properties_action.setChecked(True)
        self.properties_action.toggled.connect(self.toggle_properties)
        self.ui.tabWidget.currentChanged.connect(self.refresh_project_tree)

    def refresh_project_tree(self, *args):
        if hasattr(self, "tab_controls"):
            self.tab_controls.refresh()
        if hasattr(self, "properties_action"):
            self.toggle_properties(self.properties_action.isChecked())

    def toggle_properties(self, visible):
        for sheet in self.get_data_sheets():
            sheet.property_tabs.setVisible(visible)
        for index in range(self.ui.tabWidget.count()):
            plot = self.ui.tabWidget.widget(index)
            if hasattr(plot, "property_tabs"):
                getattr(plot, "preferences", plot.property_tabs).setVisible(visible)

    def clear_all(self, add_sheet=False):
        from tailor.document_tabs import DocumentTabBar

        if not isinstance(self.ui.tabWidget.tabBar(), DocumentTabBar):
            self.ui.tabWidget.setTabBar(DocumentTabBar(self.ui.tabWidget))
        if self.project_save_busy() or self.csv_export_busy():
            self.statusBar().showMessage("数据正在写入文件，未清空当前数据。")
            return
        old = list(dict.fromkeys([self.ui.tabWidget.widget(i) for i in range(self.ui.tabWidget.count())] + self.get_plots()))
        if any(isinstance(tab, DataSheet) and tab.clipboard_busy() for tab in old):
            self.statusBar().showMessage("后台剪贴板操作尚未结束，未清空工程。")
            return
        super().clear_all(add_sheet)
        if add_sheet:
            self.ui.tabWidget.currentWidget()._initial_placeholder = True
            self.ui.tabWidget.currentWidget()._default_sheet = True
        for tab in old:
            if isinstance(tab, DataSheet):
                tab.model.clear_history()
            if hasattr(tab.ui, "plot_widget"):
                from tailor.curve_controls import dispose_graph

                dispose_graph(tab)
            tab.deleteLater()
        self.refresh_project_tree()

    def close_tabs(self, tabs):
        tabs = [
            tab
            for tab in dict.fromkeys(getattr(tab, "widget", tab) for tab in tabs)
            if not isinstance(tab, DataSheet)
        ]
        if getattr(self, "_processing_busy", False) or getattr(
            self, "_fit_busy", False
        ):
            self.statusBar().showMessage("计算尚未结束，请先取消或等待。")
            return
        if any(isinstance(tab, DataSheet) and tab.clipboard_busy() for tab in tabs):
            self.statusBar().showMessage("粘贴解析尚未完成，请等待或取消。")
            return
        from tailor.fit_results import FitResultTab
        from tailor.result_pages import remove_fit_tab

        for tab in tabs:
            if isinstance(tab, FitResultTab):
                remove_fit_tab(self, tab)
            else:
                self.window_mode.forget(tab)
        tabs = [tab for tab in tabs if not isinstance(tab, FitResultTab)]
        indexes = sorted((self.ui.tabWidget.indexOf(tab) for tab in tabs), reverse=True)
        for index in indexes:
            if index >= 0:
                self.ui.tabWidget.removeTab(index)
        self.mark_project_dirty()
        for tab in tabs:
            if isinstance(tab, DataSheet):
                tab.model.clear_history()
            if hasattr(tab.ui, "plot_widget"):
                from tailor.curve_controls import dispose_graph

                dispose_graph(tab)
            tab.deleteLater()
        self.refresh_project_tree()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(
            url.isLocalFile()
            and Path(url.toLocalFile()).suffix.lower()
            in {".csv", ".tsv", ".txt", ".xlsx", ".xls", ".cur"}
            for url in event.mimeData().urls()
        ):
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.isLocalFile()
            and Path(url.toLocalFile()).suffix.lower()
            in {".csv", ".tsv", ".txt", ".xlsx", ".xls", ".cur"}
        ]
        if paths:
            event.acceptProposedAction()
            self.projects.activate(self)
            data_paths = []
            for path in paths:
                if Path(path).suffix.lower() == ".cur":
                    self.open_project_dialog(filename=path)
                else:
                    data_paths.append(path)
            if data_paths:
                (self.projects.active or self).queue_csv_paths(data_paths)

    def add_data_sheet(self, new_sheet=None):
        sheets = self.get_data_sheets()
        if sheets:
            self.ui.tabWidget.setCurrentWidget(sheets[0])
            return sheets[0]
        sheet = super().add_data_sheet(new_sheet)
        sheet._default_sheet = True
        return sheet

    def import_csv(self):
        filenames, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            "导入数据",
            self.get_recent_directory(),
            "表格文件 (*.csv *.tsv *.txt *.xlsx *.xls);;所有文件 (*)",
        )
        if filenames:
            self.queue_csv_paths(filenames)

    def queue_csv_paths(self, paths):
        if self.csv_import_busy():
            self.statusBar().showMessage("当前导入尚未完成，请完成后再导入下一批文件。")
            return
        self.projects.activate(self)
        self._csv_queue = list(paths)
        self._next_csv()

    def _next_csv(self):
        if self._csv_queue:
            entry = self._csv_queue.pop(0)
            if isinstance(entry, tuple):
                self.start_csv_import(*entry)
            else:
                self.choose_csv_format(entry)

    def choose_csv_format(self, filename):
        if Path(filename).suffix.lower() in {".xlsx", ".xls"}:
            from tailor.excel_import import choose_excel

            return choose_excel(self, filename)
        if self.csv_import_busy():
            self.statusBar().showMessage("正在读取文件，请等待完成。")
            return
        dialog = CSVFormatDialog(filename, self)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            self.start_csv_import(filename, dialog.get_format_parameters())
        else:
            self._csv_queue.clear()

    def start_csv_import(self, filename, parameters):
        if self.csv_import_busy():
            return False
        previous = getattr(self, "_progress", None)
        if previous is not None:
            previous.deleteLater()
        self._progress = QtWidgets.QProgressDialog(
            "正在后台读取数据…", "取消导入", 0, 0, self
        )
        self._progress.setWindowModality(QtCore.Qt.NonModal)
        self._progress.setMinimumDuration(0)
        self._cancel_import = False
        self._progress.canceled.connect(lambda: setattr(self, "_cancel_import", True))
        if self._reader is not None:
            self._reader.deleteLater()
        self._reader = CsvReader(filename, parameters, self)
        self._reader.loaded.connect(lambda data: self.finish_csv_import(filename, data))
        self._reader.failed.connect(self.csv_import_failed)
        self._reader.finished.connect(self._after_csv_thread)
        self._reader_pending = True
        self._reader.start()
        return True

    def _after_csv_thread(self):
        self._reader_pending = False
        if self._cancel_import:
            self._csv_queue.clear()
        elif self._csv_queue:
            QtCore.QTimer.singleShot(0, self, self._next_csv)

    def csv_import_failed(self, message):
        self._csv_queue.clear()
        self._progress.reset()
        QtWidgets.QMessageBox.warning(self, "导入失败", message)

    def finish_csv_import(self, filename, data):
        self._progress.reset()
        if self._cancel_import:
            return
        sheet = self.get_data_sheets()[0]
        from tailor.single_sheet import overwrite_import

        keys = overwrite_import(sheet, data, str(Path(filename)))
        sheet._initial_placeholder = False
        self.ui.tabWidget.setCurrentWidget(sheet)
        self.refresh_project_tree()
        sheet.go_to_row(0)
        self.mark_project_dirty()
        warnings = getattr(data, "import_warnings", {})
        suffix = (
            f" · 警告：{sum(warnings.values()):,} 个非数值单元格为空值（见列提示）"
            if warnings
            else ""
        )
        for index, label in enumerate(keys):
            if str(data.get_column_names()[index]) in warnings:
                sheet.model._metadata[label]["comment"] = (
                    f"导入时 {warnings[str(data.get_column_names()[index])]} 个非数值单元格转换为空值；原文件数据记录示例：{getattr(data, 'import_samples', {}).get(str(data.get_column_names()[index]), [])}"
                )
        self.statusBar().showMessage(
            f"已从A列覆盖导入 {data.num_rows():,} 行 × {data.num_columns()} 列 · {Path(filename).name}{suffix}"
        )

    def eventFilter(self, watched, event):
        if not valid_event(event, 'PhysicsPlotWindow'):
            return True
        if watched is self and event.type() == QtCore.QEvent.Close:
            if self.data_operation_busy():
                event.ignore()
                self.statusBar().showMessage(
                    "后台数据操作尚未结束，请等待或取消后关闭。"
                )
                return True
            continuation = (
                self.projects.quit_all if self.projects.quitting else self.close
            )
            if self._can_replace_project(continuation):
                self.clear_all(False)
                self.projects.closed(self)
                event.accept()
                return False
            event.ignore()
            return True
        return super().eventFilter(watched, event)

    def load_project(self, filename, *, record_recent=True):
        if self.data_operation_busy():
            self.statusBar().showMessage("后台数据操作尚未结束，请稍后打开工程。")
            return False
        from tailor.project_load_cover import ProjectLoadCover
        cover = ProjectLoadCover(self)
        tabs = self.ui.tabWidget
        old = [tabs.widget(i) for i in range(tabs.count())]
        reusable = None
        if (len(old) == 1 and isinstance(old[0], DataSheet)
                and getattr(old[0], '_initial_placeholder', False)
                and not old[0].model.can_undo and not old[0].model.can_redo
                and old[0].model.rowCount() <= 1000
                and old[0].model.data_model._data.isna().all().all()):
            reusable = old[0]
        # Fresh windows already own an empty table with the complete inspector.
        # Reuse that widget only; never replace/borrow a user's populated sheet.
        reuse_state = ((reusable.name, reusable.id, getattr(reusable,'_default_sheet',False),
                        reusable.model._snapshot()) if reusable is not None else None)
        self._restore_reusable_sheet = reusable
        old_documents=list(old)
        old_documents.extend(s for s in getattr(self,'_axis_owned_sources',[]) if s not in old_documents)
        for doc in old_documents:
            for source in getattr(getattr(doc,'model',None),'_plots',{}):
                if source not in old_documents:old_documents.append(source)
        old_name = self.project_name
        old_windows = self.window_mode.snapshot()
        notebooks = {}
        for name in ("_fit_result_page", "_processing_result_page"):
            if hasattr(self, name):
                notebooks[name] = getattr(self, name)
                delattr(self, name)
        state = (
            self._sheet_num,
            self._plot_num,
            self._project_filename,
            self._is_dirty,
            tabs.currentIndex(),
        )
        tabs.blockSignals(True)
        self.window_mode.reset()
        tabs.clear()
        success = False
        self._defer_project_restore = True
        self._restore_created=[]
        try:
            project_files.load_project_from_path(self, Path(filename))
            success = True
        except Exception as exc:  # noqa: BLE001 - restore live tabs on any loading failure
            cover.finish()
            self.window_mode.reset()
            failed=[tabs.widget(i) for i in range(tabs.count())]
            tabs.clear()
            failed.extend(w for w in self._restore_created if w not in failed)
            for widget in reversed(failed):
                if widget is reusable:
                    continue
                if hasattr(widget, "result_kind"):
                    widget.dispose()
                elif hasattr(widget.ui, "plot_widget"):
                    from tailor.curve_controls import dispose_graph

                    dispose_graph(widget)
                widget.deleteLater()
            if reusable is not None:
                reusable.name,reusable.id,reusable._default_sheet,snapshot = reuse_state
                reusable.model._restore(snapshot)
                reusable._initial_placeholder = True
            for name in ("_fit_result_page", "_processing_result_page"):
                if hasattr(self, name):
                    delattr(self, name)
            for name, notebook in notebooks.items():
                setattr(self, name, notebook)
            (
                self._sheet_num,
                self._plot_num,
                self._project_filename,
                self._is_dirty,
                current,
            ) = state
            for widget in old:
                tabs.addTab(widget, widget.name)
            tabs.setCurrentIndex(current)
            self.window_mode.restore(old_windows)
            self._is_dirty = state[3]
            self.project_name = old_name
            QtWidgets.QMessageBox.warning(self, "工程打开失败，原工程已保留", str(exc))
        finally:
            self._defer_project_restore = False
            del self._restore_created
            del self._restore_reusable_sheet
            tabs.blockSignals(False)
        if success:
            self._axis_owned_sources=[]
            for widget in reversed(old_documents):
                if widget is reusable:
                    continue
                if isinstance(widget, DataSheet):
                    widget.model.clear_history()
                if hasattr(widget, "result_kind"):
                    widget.dispose()
                elif hasattr(widget.ui, "plot_widget"):
                    from tailor.curve_controls import dispose_graph

                    dispose_graph(widget)
                widget.deleteLater()
            self.project_name = (
                getattr(self, "_loaded_project_name", None) or Path(filename).stem
            )
            self._set_project_path(filename)
            if record_recent:
                self.update_recent_files(str(filename))
            self.mark_project_dirty(False)
            self.update_plot_tab(tabs.currentIndex())
        else:
            self.update_window_title()
        self.refresh_project_tree()
        if success:
            cover.wait_for_frames()
        return success

    def import_placeholder(self):
        for sheet in self.get_data_sheets():
            if (
                getattr(sheet, "_initial_placeholder", False)
                and sheet.name == "Sheet 1"
                and not sheet.model.can_undo
                and not sheet.model.can_redo
                and not any(plot.data_sheet is sheet for plot in self.get_plots())
                and sheet.model.data_model._data.isna().all().all()
            ):
                return sheet
        return None

    def is_pristine_project(self):
        return (
            not self._is_dirty
            and self._project_filename is None
            and self.ui.tabWidget.count() == 1
            and self.import_placeholder() is not None
        )

    def new_project(self):
        return self.projects.create(self)

    def open_project_dialog(self, event=None, filename=None):
        return super().open_project_dialog(event=event, filename=filename)

    def update_window_title(self):
        title = f"{APP_NAME}—{self.project_name}"
        self.setWindowTitle(title)
        self.projects.refresh()

    def show_about_dialog(self):
        QtWidgets.QMessageBox.about(
            self,
            f"关于 {APP_NAME}",
            f"<h3>{APP_NAME}</h3><p>{FULL_NAME} · {version_label()}</p>"
            "<p>主开发者：NolinReid；协作开发：Codex。</p>"
            "<p>开发试用版，基于 Tailor 2.1.4。支持连续表格、撤销重做和列属性。</p>"
            "<p>当前仍需真实原始文件及完整绘图流程验收，详见版本说明。</p>"
            "<p>Tailor：David Fokkema 与贡献者；GPL-3.0-or-later。"
            '<a href="https://github.com/davidfokkema/tailor">原项目与源代码</a></p>',
        )

    def open_example(self):
        sheet = self.get_data_sheets()[0]
        x = np.linspace(0, 10, 41)
        y = 2.4 * x + 0.7 + np.random.default_rng(42).normal(0, 0.06, x.size)
        labels = sheet.model.append_results([
            {"name": "示例X", "values": x}, {"name": "示例Y", "values": y},
            {"name": "示例误差", "values": np.full_like(x, .06)}])
        keys = list(sheet.model.columnLabels())
        for key, role in zip(labels, ("X", "Y", "YErr")):
            sheet.model.set_column_metadata(keys.index(key), role=role)
        plot = self.create_plot_tab(sheet, labels[0], labels[1], y_err=labels[2])
        plot.preset_controls.choose("linear")
        plot.property_tabs.setCurrentIndex(
            next(
                i
                for i in range(plot.property_tabs.count())
                if plot.property_tabs.tabText(i) == "拟合"
            )
        )
        plot.perform_fit()
        return plot


class DesktopApplication(QtWidgets.QApplication):
    def open_path(self, path):
        window = getattr(self, 'window', None)
        if window is None:
            if not hasattr(self, 'pending_paths'):
                self.pending_paths = []
            self.pending_paths.append(path)
            return
        if Path(path).suffix.lower() in {'.csv', '.tsv', '.txt', '.xlsx', '.xls'}:
            window.choose_csv_format(path)
        else:
            window.open_project_dialog(filename=path)

    def open_pending_files(self, paths=()):
        pending = [*paths, *getattr(self, 'pending_paths', ())]
        self.pending_paths = []
        for path in pending:
            self.open_path(path)

    def event(self, event):
        window = getattr(self, "window", None)
        if (
            event.type() == QtCore.QEvent.Quit
            and window is not None
            and not getattr(self, "_allow_quit", False)
        ):
            window.projects.quit_all()
            event.ignore()
            return True
        if (
            event.type() == QtCore.QEvent.ApplicationActivate
            and window is not None
            and not window.projects.host.isVisible()
            and not window.projects.quitting
        ):
            window.projects.reopen()
        if event.type() == QtCore.QEvent.FileOpen:
            # Cocoa can replay the Python launcher itself as a FileOpen event.
            # Only supported data/project files may enter project-opening UI.
            if Path(event.file()).suffix.lower() not in {'.csv','.tsv','.txt','.xlsx','.xls','.cur','.tlr'}:
                return True
            self.open_path(event.file())
            return True
        return super().event(event)


def wait_for_fit(plot, timeout_ms=15000):
    """Pump events only in the explicit release check, never in normal UI actions."""
    deadline = QtCore.QDeadlineTimer(timeout_ms)
    while plot._fit_job is not None and not deadline.hasExpired():
        QtWidgets.QApplication.processEvents()
        QtCore.QThread.msleep(5)
    if plot._fit_job is not None:
        plot._fit_job.requestInterruption()
        plot._fit_job.wait()
        QtWidgets.QApplication.processEvents()
        raise TimeoutError("Background fit did not finish within check timeout")


def smoke_check(window, output: Path):
    """Exercise bundled imports, fitting, project round-trip and PDF export."""
    output.mkdir(parents=True, exist_ok=True)
    plot = window.open_example()
    wait_for_fit(plot)
    assert plot.model.best_fit is not None
    assert abs(plot.model.best_fit.params["slope"].value - 2.4) < 0.02
    from tailor.fit_presets import create_library_model

    peak_sheet = window.add_data_sheet()
    peak_x = np.linspace(-5, 5, 101)
    native = create_library_model("gaussian")
    peak_y = 1.5 + native.eval(x=peak_x, amplitude=12, center=0.3, sigma=0.8)
    peak_sheet.model.setDataFromArray(
        peak_sheet.model.index(0, 0), np.column_stack((peak_x, peak_y))
    )
    peak_labels = peak_sheet.model.columnLabels()
    peak = window.create_plot_tab(peak_sheet, peak_labels[0], peak_labels[1])
    peak.preset_controls.choose("gaussian")
    peak.perform_fit()
    wait_for_fit(peak)
    peak.update_info_box()
    expected_fwhm = native.make_params(sigma=0.8)["fwhm"].value
    assert abs(peak.preset_controls.derived_values()["fwhm"] - expected_fwhm) < 1e-6
    assert "FWHM" in peak.ui.result_box.toPlainText()
    from tailor.curve_style import CurveStyle

    style = CurveStyle(
        mode="line_scatter", color="#2458a6", line_width=2.0, font_size=13.0
    )
    plot.apply_curve_style(style, dirty=False)
    path = output / "trial-check.tlr"
    project_files.save_project_to_path(window, path)
    restored = PhysicsPlotWindow()
    restored.clear_all()
    project_files.load_project_from_path(restored, path)
    assert restored.ui.tabWidget.count() == window.ui.tabWidget.count(), (
        restored.ui.tabWidget.count(),
        window.ui.tabWidget.count(),
    )
    assert restored.get_plots()[0].curve_style == style
    assert restored.get_plots()[1].model.fit_preset_key == "gaussian"
    assert restored.get_plots()[1].model.best_fit is not None
    plot.export_graph(output / "trial-check.png", dpi=150)
    image = QtGui.QImage(str(output / "trial-check.png"))
    assert not image.isNull() and image.width() > 100 and image.height() > 100
    plot.export_graph(output / "trial-check.pdf")
    assert (output / "trial-check.pdf").stat().st_size > 100
    plot.export_graph(output / "trial-check.svg")
    from xml.etree import ElementTree

    svg = ElementTree.parse(output / "trial-check.svg").getroot()
    assert svg.tag.endswith("svg")
    assert any(node.tag.endswith("path") for node in svg.iter())
    assert not any(node.tag.endswith("image") for node in svg.iter())
    result = {
        "version": VERSION,
        "status": "passed",
        "frozen": bool(getattr(sys, "frozen", False)),
        "checks": [
            "window",
            "linear fit",
            "preset Gaussian fit and native FWHM",
            "fit preset project roundtrip",
            "dual Y and logarithmic right axis",
            "SVG export",
            "schema4 annotations/project save/reopen",
            "curve style roundtrip",
            "PNG export",
            "PDF export",
            "SVG export",
        ],
    }
    # Exercise the actual threaded import in the standalone packaged app too.
    large_csv = output / "large-check.csv"
    x = np.arange(500000)
    np.savetxt(
        large_csv,
        np.column_stack((x, 2 * x)),
        delimiter=",",
        header="x,y",
        comments="",
        fmt="%d",
    )
    window.start_csv_import(str(large_csv), FormatParameters())
    loop = QtCore.QEventLoop()
    window._reader.finished.connect(loop.quit)
    QtCore.QTimer.singleShot(30000, loop.quit)
    loop.exec()
    QtWidgets.QApplication.processEvents()
    sheet = window.ui.tabWidget.currentWidget()
    assert sheet.model.rowCount() == 500000
    assert sheet.model.data_model.get_value(499999, 1) == 999998
    sheet.add_row()
    assert sheet.model.rowCount() == 500001
    assert sheet.model.setData(sheet.model.index(500000, 0), "42")
    assert sheet.model.data_model.get_value(500000, 0) == 42
    assert sheet.page_model.rowCount() == 500001
    sheet.ui.data_view.selectColumn(1)
    sheet.go_to_row(400000)
    sheet.ui.data_view.viewport().repaint()
    assert sheet.ui.data_view.currentIndex().row() == 400000
    sheet.model.undo()
    assert np.isnan(sheet.model.data_model.get_value(500000, 0))
    sheet.model.redo()
    assert sheet.model.data_model.get_value(500000, 0) == 42
    sheet.model.set_column_metadata(
        1, role="Y", unit="mV", comment="bundle verification"
    )
    meta_path = output / "metadata-check.tlr"
    project_files.save_project_to_path(window, meta_path)
    assert restored.load_project(meta_path)
    restored_sheet = restored.get_data_sheets()[-1]
    assert restored_sheet.model.column_metadata(1)["unit"] == "mV"
    assert restored_sheet.model.rowCount() == 500001
    # Exercise the user-facing asynchronous writers in the installed bundle too.
    assert window.save_project(output / "background-check.tlr")
    loop = QtCore.QEventLoop()
    window._saver.finished.connect(loop.quit)
    QtCore.QTimer.singleShot(30000, loop.quit)
    loop.exec()
    QtWidgets.QApplication.processEvents()
    assert not window.project_save_busy() and window._saver.outcome == "saved"
    assert window.start_csv_export(sheet, output / "worksheet-check.csv")
    loop = QtCore.QEventLoop()
    window._csv_writer.finished.connect(loop.quit)
    QtCore.QTimer.singleShot(30000, loop.quit)
    loop.exec()
    QtWidgets.QApplication.processEvents()
    assert not window.csv_export_busy() and window._csv_writer.outcome == "saved"
    assert (output / "worksheet-check.csv").stat().st_size > 100
    x, y, _, _ = plot.model.get_data()
    assert plot.point_inspector.select_near(x[0], y[0], (0.01, 0.01)) == 0
    result_path = output / "result.json"
    result["checks"] += [
        "500000-row background CSV import",
        "append row",
        "edit last row",
        "continuous full-row model",
        "undo/redo",
        "metadata project roundtrip",
        "background project save",
        "background worksheet CSV export",
        "original source point mapping",
    ]
    result_path.write_text(json.dumps(result, indent=2))
    window.mark_project_dirty(False)
    restored.mark_project_dirty(False)
    restored.close()


def quick_check(window, output):
    """Small explicit standalone-package check over the current workflow."""
    from tailor.release_analysis_check import run_core
    result = run_core(window, output)
    result.update(version=VERSION, build=BUILD,
                  frozen=bool(getattr(sys, 'frozen', False)), status='passed')
    (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    for project in window.projects.windows:
        project.mark_project_dirty(False)


def main():
    parser = argparse.ArgumentParser(description=f"{FULL_NAME} desktop")
    parser.add_argument("project", nargs="*")
    parser.add_argument("--smoke-test", type=Path, metavar="OUTPUT_DIRECTORY")
    parser.add_argument("--quick-check", action="store_true")
    args = parser.parse_args()
    startup_check = os.environ.get("CURVE_STARTUP_CHECK")
    check_dir = Path(startup_check) if startup_check else args.smoke_test
    if check_dir:
        check_dir.mkdir(parents=True, exist_ok=True)
        config.get_config_path = lambda: check_dir / "config.toml"
        QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
        QtCore.QSettings.setPath(
            QtCore.QSettings.IniFormat, QtCore.QSettings.UserScope, str(check_dir)
        )
        # Explicit QSettings(org, app) uses the native format despite the
        # default above. Isolate those constructors in diagnostic runs too.
        original_settings = QtCore.QSettings
        class CheckSettings(original_settings):
            def __init__(self, *values, **kwargs):
                if len(values) >= 2 and all(isinstance(v, str) for v in values[:2]):
                    path = check_dir / values[0] / (values[1] + '.ini')
                    path.parent.mkdir(parents=True, exist_ok=True)
                    super().__init__(str(path), original_settings.IniFormat, *values[2:], **kwargs)
                else:
                    super().__init__(*values, **kwargs)
        QtCore.QSettings = CheckSettings
        from tailor import recovery
        recovery.folder = lambda: check_dir / 'Recovery'
    if args.smoke_test:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        # Never touch the user's normal preferences during packaging checks.
        args.smoke_test.mkdir(parents=True, exist_ok=True)
        config.get_config_path = lambda: args.smoke_test / "config.toml"
    # Keep the existing preference directory when changing the visible brand.
    config.APP_NAME = "PhysicsPlot"
    app = DesktopApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(version_label())
    from tailor.product_shell import install_translations

    install_translations(app)
    window = PhysicsPlotWindow()
    app.window = window
    app.open_pending_files(args.project)
    window = window.projects.active or window
    window.projects.activate(window)
    if not check_dir:
        from tailor.update_check import for_application
        checker = for_application()
        QtCore.QTimer.singleShot(1500, checker, lambda: checker.check(manual=False))
    if startup_check:

        def finish_startup_check():
            payload = {
                "version": VERSION,
                "build": BUILD,
                "native_menu": window.projects.host.menuBar().isNativeMenuBar(),
                "platform": app.platformName(),
                "settings_role": window._settings_action.menuRole().name,
                "title": window.windowTitle(),
                "icon": not app.windowIcon().isNull(),
            }
            if os.environ.get("CURVE_ANALYSIS_CHECK") == "1":
                from tailor.release_analysis_check import run

                payload["analysis"] = run(window, Path(startup_check))
            (Path(startup_check) / "startup.json").write_text(
                json.dumps(payload, ensure_ascii=False)
            )
            for project in list(window.projects.windows):
                project.clear_all(False)
            QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
            app._allow_quit = True
            QtCore.QCoreApplication.exit(0)

        QtCore.QTimer.singleShot(
            min(
                60000,
                max(500, int(os.environ.get("CURVE_STARTUP_CHECK_DELAY_MS", "500"))),
            ),
            finish_startup_check,
        )
    if args.smoke_test:
        (quick_check if args.quick_check else smoke_check)(window, args.smoke_test)
        app._allow_quit = True
        QtCore.QTimer.singleShot(200, app.quit)
    return app.exec()

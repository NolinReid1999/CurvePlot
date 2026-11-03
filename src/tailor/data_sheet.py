import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from tailor import dialogs
from tailor.clipboard_matrix import parse_matrix
from tailor.clipboard_worker import ClipboardReader, ClipboardWriter
from tailor.continuous_table import ContinuousTable, ContinuousTableView, FastHeader
from tailor.qdata_model import MSG_TIMEOUT
from tailor.sequence_dialog import SequenceDialog
from tailor.spreadsheet_delegate import SpreadsheetDelegate
from tailor.spreadsheet_model import SpreadsheetModel as QDataModel
from tailor.ui_data_sheet import Ui_DataSheet


class DataSheet(QtWidgets.QWidget):
    model: QDataModel = None
    selection: QtCore.QItemSelectionModel
    name: str = None
    id: int

    def __init__(self, name, id, main_window):
        super().__init__()
        self.ui = Ui_DataSheet()
        self.ui.setupUi(self)
        self.setup_virtual_table()

        self.name = name
        self.id = id
        self.main_window = main_window
        self.clipboard = QtWidgets.QApplication.clipboard()

        self._clipboard_job = None
        self._clipboard_pending = False
        self._edit_revision = 0
        self.setup_data_model()
        self.model.historyChanged.connect(self._revision_changed)

        self.connect_ui_events()
        self.setup_keyboard_shortcuts()

        # Header highlighting must not scan every source row during repaint.
        # FastHeader is installed before UI signal wiring in setup_data_model.
        # Make columns resizable
        self.ui.data_view.horizontalHeader().setSectionResizeMode(
            self.ui.data_view.horizontalHeader().ResizeMode.Interactive
        )

        self.ui.data_view.setItemDelegate(SpreadsheetDelegate(self))
        self.setup_operation_panel()
        self.setup_table_splitter()
        self.ui.data_view.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)

        def cell_menu(point):
            from tailor.exclusions import set_cells, table_cells

            menu = QtWidgets.QMenu(self)
            menu.addAction(
                "排除选中数据", lambda: set_cells(self.model, table_cells(self), True)
            )
            menu.addAction(
                "恢复选中数据", lambda: set_cells(self.model, table_cells(self), False)
            )
            menu.addSeparator()
            self.column_preferences.add_context_menu(menu)
            menu.exec(self.ui.data_view.viewport().mapToGlobal(point))
            menu.deleteLater()

        self.ui.data_view.customContextMenuRequested.connect(cell_menu)
        self.ui.horizontalLayout.setContentsMargins(0, 0, 0, 0)
        self.ui.horizontalLayout.setSpacing(3)
        header = self.ui.data_view.verticalHeader()
        header.setSectionResizeMode(QtWidgets.QHeaderView.Fixed)
        header.setDefaultSectionSize(25)
        self.ui.data_view.setAlternatingRowColors(True)
        self.ui.data_view.setSelectionMode(
            QtWidgets.QAbstractItemView.ExtendedSelection
        )
        self.ui.data_view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectItems)
        self.ui.data_view.setEditTriggers(
            QtWidgets.QAbstractItemView.DoubleClicked
            | QtWidgets.QAbstractItemView.EditKeyPressed
            | QtWidgets.QAbstractItemView.AnyKeyPressed
        )
        self.ui.data_view.setHorizontalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.ui.data_view.setVerticalScrollMode(
            QtWidgets.QAbstractItemView.ScrollPerPixel
        )
        for header, kind in (
            (self.ui.data_view.verticalHeader(), "row"),
            (self.ui.data_view.horizontalHeader(), "column"),
        ):
            header.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
            header.customContextMenuRequested.connect(
                lambda point, h=header, k=kind: self.header_menu(h, k, point)
            )

        # Start at (0, 0)
        self.ui.data_view.setCurrentIndex(self.page_model.index(0, 0))
        from tailor.appearance import manager

        manager().register(self)

    def setup_virtual_table(self):
        original_view = self.ui.data_view
        self.ui.data_view = ContinuousTableView(self)
        self.ui.data_view.setObjectName(original_view.objectName())
        self.ui.data_view.setSizePolicy(original_view.sizePolicy())
        self.ui.horizontalLayout.replaceWidget(original_view, self.ui.data_view)
        original_view.deleteLater()

    def setup_table_splitter(self):
        self.ui.horizontalLayout.removeWidget(self.ui.data_view)
        self.ui.horizontalLayout.removeWidget(self.ui.groupBox)
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal, self)
        splitter.addWidget(self.ui.data_view)
        from tailor.ui_widgets import InspectorTabs

        self.property_tabs = InspectorTabs(self)
        self.ui.groupBox.setTitle("")
        self.ui.groupBox.setStyleSheet(
            "QGroupBox { border: 0; margin: 0; padding: 0; }"
        )
        from tailor.fold_panel import FoldPanel, stack

        panel = FoldPanel(self)
        source = self.ui.verticalLayout
        buttons = {}
        remainder = []
        while source.count():
            item = source.takeAt(0)
            widget = item.widget()
            if isinstance(widget, QtWidgets.QPushButton):
                buttons[widget.text()] = widget
            elif widget is not None:
                remainder.append(widget)
        from tailor.compact_controls import help_button
        from tailor.graph_controls import row

        excel = QtWidgets.QPushButton("Excel")
        exporter = getattr(self.main_window, "export_excel", None)
        if callable(exporter):
            excel.clicked.connect(exporter)
        else:
            excel.setEnabled(False)
        csv = buttons["导出表格 CSV…"]
        csv.setText("CSV")
        panel.add_section(
            "导入与导出", stack(buttons["导入数据…"], row("导出", excel, csv)), True
        )
        for name in ("在末尾添加行…", "添加列"):
            buttons[name].hide()
        calculation = QtWidgets.QWidget()
        calculation_layout = QtWidgets.QVBoxLayout(calculation)
        calculation_layout.addLayout(self.ui.formLayout)
        calculation_layout.addWidget(buttons["添加计算列"])
        calculation.setParent(self)
        calculation.hide()
        from tailor.plot_types import PlotTypePicker

        self.plot_type_picker = PlotTypePicker(self, buttons["绘图…"])
        panel.add_section("绘图", self.plot_type_picker, True)
        location = QtWidgets.QVBoxLayout()
        for widget in remainder:
            if widget is self.jump or widget is self.page_label:
                location.addWidget(widget)
            else:
                widget.hide()
        location.addWidget(
            help_button(
                "双击或直接输入编辑；Tab横移；右键列名进行列操作；⌘C/⌘V复制粘贴。"
            )
        )
        self.ui.groupBox.hide()
        from tailor.column_preferences import ColumnPreferences

        self.column_preferences = ColumnPreferences(self)
        self.property_tabs.addTab(self.column_preferences, "列偏好")
        from tailor.processing_controls import ProcessingControls

        self.processing_controls = ProcessingControls(self)
        self.property_tabs.addTab(self.processing_controls, "处理")
        self.column_preferences.add_section("定位", location)
        self.property_tabs.addTab(panel, "导入与绘图")
        from tailor.advanced_plotting import AdvancedControls
        self.advanced_controls = AdvancedControls(self)
        self.property_tabs.addTab(self.advanced_controls, '高级')
        self.property_tabs.setCurrentWidget(panel)
        self.property_tabs.setMinimumWidth(380)
        self.property_tabs.setMaximumWidth(16777215)
        from tailor.quick_actions import QuickActions

        self.quick_actions = QuickActions(self)
        splitter.addWidget(self.quick_actions)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(6)
        splitter.addWidget(self.property_tabs)
        splitter.setStretchFactor(0, 1)
        splitter.setSizes([720, 46, 390])
        self.ui.horizontalLayout.addWidget(splitter)
        from tailor.inspector_width import bind_width

        bind_width(splitter, self.property_tabs, "table")

    def setup_operation_panel(self):
        # One compact operation area; row/column context menus follow spreadsheet conventions.
        for button in self.ui.groupBox.findChildren(QtWidgets.QPushButton):
            button.hide()
        layout = self.ui.verticalLayout
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().hide()
        self.ui.groupBox.setTitle("数据与绘图")
        self.ui.groupBox.setMaximumWidth(440)
        for title, callback in (
            ("撤销 ⌘Z", self.model.undo),
            ("重做 ⇧⌘Z", self.model.redo),
            ("导入数据…", self.main_window.import_csv),
            ("导出表格 CSV…", self.main_window.export_csv),
            ("在末尾添加行…", self.add_rows_dialog),
            ("添加列", self.add_column),
            ("添加计算列", self.add_calculated_column),
            ("绘图…", self.main_window.ask_and_create_plot_tab),
        ):
            button = QtWidgets.QPushButton(title, self)
            button.clicked.connect(callback)
            if title.startswith("撤销"):
                self.undo_button = button
            elif title.startswith("重做"):
                self.redo_button = button
            layout.addWidget(button)
            if title.startswith(("撤销", "重做")):
                button.hide()
        self.model.historyChanged.connect(self.update_history_buttons)
        self.update_history_buttons()
        layout.addLayout(self.ui.formLayout)
        self.ui.nameLabel.setText("列名")
        self.ui.formulaLabel.setText("公式")
        layout.addSpacing(12)
        label = QtWidgets.QLabel("连续表格", self)
        layout.addWidget(label)
        self.page_label = QtWidgets.QLabel(self)
        layout.addWidget(self.page_label)
        self.jump = QtWidgets.QSpinBox(self)
        self.jump.setRange(1, 2147483647)
        self.jump.setPrefix("定位行 ")
        self.jump.editingFinished.connect(lambda: self.go_to_row(self.jump.value() - 1))
        layout.addWidget(self.jump)
        hint = QtWidgets.QLabel(
            "双击或直接输入编辑 · Tab 横移\n右键行号/列名：插入、删除\n⌘C / ⌘V：复制、粘贴",
            self,
        )
        layout.addWidget(hint)
        layout.addStretch()
        for signal in (
            self.page_model.modelReset,
            self.page_model.rowsInserted,
            self.page_model.rowsRemoved,
            self.page_model.columnsInserted,
            self.page_model.columnsRemoved,
        ):
            signal.connect(self.update_page_label)
        self.update_page_label()

    def _revision_changed(self):
        self._edit_revision += 1

    def clipboard_busy(self):
        return self._clipboard_job is not None and (
            self._clipboard_pending or self._clipboard_job.isRunning()
        )

    def update_history_buttons(self):
        self.undo_button.setEnabled(self.model.can_undo)
        self.redo_button.setEnabled(self.model.can_redo)

    def update_page_label(self, *args):
        total = self.model.rowCount()
        header = self.ui.data_view.verticalHeader()
        header.setMinimumWidth(
            header.fontMetrics().horizontalAdvance(str(max(1, total))) + 18
        )
        self.jump.setMaximum(max(1, total))
        self.jump.setValue(min(max(1, total), self.page_model.offset + 1))
        self.page_label.setText(f"{total:,} 行 × {self.model.columnCount()} 列")

    def go_to_row(self, row):
        row = max(0, min(row, self.model.rowCount() - 1))
        self.page_model.show_row(row)
        index = self.page_model.mapFromSource(self.model.index(row, 0))
        self.ui.data_view.setCurrentIndex(index)
        self.ui.data_view.scrollTo(index)
        self.jump.setValue(row + 1)

    def fit_selected_columns(self):
        from tailor.selected_column_fit import fit_selected_columns

        fit_selected_columns(self)

    def header_menu(self, header, kind, point):
        section = header.logicalIndexAt(point)
        if section < 0:
            return
        if kind == "column" and section not in self.selected_full_columns():
            self.ui.data_view.selectColumn(section)
        elif kind == "row" and not any(
            block.top() <= section <= block.bottom()
            and block.left() == 0
            and block.right() == self.model.columnCount() - 1
            for block in self.selection.selection()
        ):
            self.ui.data_view.selectRow(section)
        menu = QtWidgets.QMenu(self)
        from tailor.exclusions import set_cells, table_cells

        menu.addAction(
            "排除选中数据", lambda: set_cells(self.model, table_cells(self), True)
        )
        menu.addAction(
            "恢复选中数据", lambda: set_cells(self.model, table_cells(self), False)
        )
        menu.addSeparator()
        if kind == "column":
            self.column_preferences.add_context_menu(menu)
            menu.exec(header.mapToGlobal(point))
            menu.deleteLater()
            return
        properties = None
        fit_columns = None
        if kind == "column":
            fit_columns = menu.addAction("拟合选中列…")
            properties = menu.addAction("列属性…（变量名、单位、名称、角色）")
            menu.addSeparator()
        sequence = menu.addAction("生成行号到新列")
        arithmetic = menu.addAction("生成等差序列到新列…")
        menu.addSeparator()
        insert = menu.addAction("在上方插入行…" if kind == "row" else "在左侧插入列…")
        delete = menu.addAction("删除选中行" if kind == "row" else "删除选中列")
        action = menu.exec(header.mapToGlobal(point))
        position = section + (self.page_model.offset if kind == "row" else 0)
        if fit_columns is not None and action == fit_columns:
            self.fit_selected_columns()
        elif action == sequence:
            self.model.append_column(
                np.arange(1, self.model.rowCount() + 1, dtype=float),
                name="Row",
                source="生成行号",
            )
        elif action == arithmetic:
            self.generate_sequence()
        elif properties is not None and action == properties:
            self.edit_column_properties(section)
        elif action == insert:
            count, ok = QtWidgets.QInputDialog.getInt(
                self, "插入", "数量：", 1, 1, 1000000 if kind == "row" else 1000
            )
            if ok:
                if kind == "row":
                    self.model.insertRows(position, count)
                else:
                    self.model.insertColumns(position, count)
        elif action == delete:
            if kind == "row":
                self.remove_selected_row()
            else:
                self.main_window.remove_selected_columns()

    def generate_sequence(self):
        dialog = SequenceDialog(self.model.rowCount(), self)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            self.model.append_column(
                dialog.values,
                name=dialog.name_edit.text(),
                source=f"等差序列：起始值={dialog.start_edit.text()}；步长={dialog.step_edit.text()}",
            )

    def edit_column_properties(self, column):
        meta = self.model.column_metadata(column)
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("列属性")
        form = QtWidgets.QFormLayout(dialog)
        fields = {}
        for key, title in (("name", "变量名"), ("unit", "单位"), ("comment", "名称")):
            fields[key] = QtWidgets.QLineEdit(meta[key], dialog)
            form.addRow(title, fields[key])
        role = QtWidgets.QComboBox(dialog)
        role.addItems(["none", "X", "Y", "XErr", "YErr"])
        role.setCurrentText(meta["role"])
        form.addRow("角色", role)
        form.addRow("稳定 ID", QtWidgets.QLabel(meta["id"], dialog))
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, dialog
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            self.model.set_column_metadata(
                column,
                role=role.currentText(),
                **{key: field.text() for key, field in fields.items()},
            )

    def connect_ui_events(self):
        # connect button signals
        self.ui.add_column_button.clicked.connect(self.add_column)
        self.ui.add_calculated_column_button.clicked.connect(self.add_calculated_column)
        # user interface events
        self.ui.data_view.horizontalHeader().sectionMoved.connect(self.column_moved)
        self.ui.name_edit.textEdited.connect(self.rename_selected_column)
        self.ui.formula_edit.textEdited.connect(self.update_column_expression)
        self.ui.create_plot_button.clicked.connect(
            self.main_window.ask_and_create_plot_tab
        )
        # Set up selection events
        self.selection = self.ui.data_view.selectionModel()
        self.selection.selectionChanged.connect(self.selection_changed)

    def setup_keyboard_shortcuts(self):
        self.ui.data_view.installEventFilter(self)
        cut = QtGui.QShortcut(QtGui.QKeySequence(QtGui.QKeySequence.Cut), self)
        cut.setContext(QtCore.Qt.WidgetWithChildrenShortcut)
        cut.activated.connect(self.cut_selected_cells)
        for sequence, callback in (
            (QtGui.QKeySequence.Undo, self.model.undo),
            (QtGui.QKeySequence.Redo, self.model.redo),
        ):
            shortcut = QtGui.QShortcut(QtGui.QKeySequence(sequence), self)
            shortcut.setContext(QtCore.Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)
        for sequence, row in (
            ("Ctrl+Home", 0),
            ("Ctrl+End", -1),
            ("Meta+Home", 0),
            ("Meta+End", -1),
        ):
            shortcut = QtGui.QShortcut(QtGui.QKeySequence(sequence), self)
            shortcut.setContext(QtCore.Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(
                lambda r=row: self.go_to_row(self.model.rowCount() - 1 if r < 0 else r)
            )
        # Shortcut for backspace and delete: clear cell contents
        for key in QtCore.Qt.Key_Backspace, QtCore.Qt.Key_Delete:
            shortcut = QtGui.QShortcut(QtGui.QKeySequence(key), self.ui.data_view)
            shortcut.setContext(QtCore.Qt.WidgetShortcut)
            shortcut.activated.connect(self.clear_selected_cells)

    def eventFilter(self, watched, event):
        if (
            watched is self.ui.data_view
            and event.type() == QtCore.QEvent.KeyPress
            and event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter)
            and self.ui.data_view.state() != QtWidgets.QAbstractItemView.EditingState
        ):
            self.move_after_edit(
                self.ui.data_view.currentIndex(),
                event.key(),
                bool(event.modifiers() & QtCore.Qt.ShiftModifier),
            )
            return True
        return super().eventFilter(watched, event)

    def move_after_edit(self, index, key, backwards=False):
        if not index.isValid():
            return
        row, col = index.row(), index.column()
        direction = -1 if backwards else 1
        if key in (QtCore.Qt.Key_Tab, QtCore.Qt.Key_Backtab):
            col += direction
            if col >= self.model.columnCount():
                col, row = 0, row + 1
            elif col < 0:
                if row == 0:
                    col = 0
                else:
                    col, row = self.model.columnCount() - 1, row - 1
        else:
            row = max(0, row + direction)
        if row >= self.model.rowCount() and not self.model.insertRow(
            self.model.rowCount()
        ):
            return
        self.go_to_row(row)
        self.ui.data_view.setCurrentIndex(self.page_model.index(row, col))

    def setup_data_model(self):
        """Set up the data model with some initial data."""
        self.model = QDataModel(main_window=self.main_window)
        self.model.setParent(self)
        from tailor.column_titles import metadata_changed, table_changed

        self.model.title_callback = lambda key: table_changed(self, key)
        self.model.metadata_callback = lambda key: metadata_changed(self, key)
        self.model.modelReset.connect(lambda: metadata_changed(self, None))
        self.model.removal_guard = lambda labels: (
            self.main_window.get_plots_which_use_columns(self, labels)
        )
        self.model.insertColumns(0, 2)
        self.model.insertRows(0, 5)
        self.model.renameColumn(0, "x")
        self.model.renameColumn(1, "y")
        self.model.set_column_metadata(0, role="X")
        self.model.set_column_metadata(1, role="Y")
        self.model.clear_history()
        self.model.editRejected.connect(
            lambda message: self.main_window.statusBar().showMessage(message)
        )

        # Set view and selection model
        self.page_model = ContinuousTable(self)
        self.page_model.setSourceModel(self.model)
        from tailor.metadata_header import MetadataHeader

        self.ui.data_view.setHorizontalHeader(MetadataHeader(self))
        self.ui.data_view.setVerticalHeader(FastHeader(QtCore.Qt.Vertical, self))
        self.ui.data_view.setModel(self.page_model)
        self.ui.data_view.setDragDropMode(QtWidgets.QTableView.NoDragDrop)

        # Set up header
        header = self.ui.data_view.horizontalHeader()
        header.setSectionsMovable(True)
        header.setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        header.setMinimumSectionSize(150)
        header.setHighlightSections(False)
        self.ui.data_view.verticalHeader().setHighlightSections(False)

    def add_column(self):
        """Add column to data model and select it."""
        col_index = self.model.columnCount()
        self.model.insertColumn(col_index)
        self.ui.data_view.selectColumn(col_index)
        self.ui.name_edit.selectAll()
        self.ui.name_edit.setFocus()

    def add_calculated_column(self):
        """Add a calculated column to data model and select it."""
        col_index = self.model.columnCount()
        self.model.insertCalculatedColumn(col_index)
        self.ui.data_view.selectColumn(col_index)
        self.ui.name_edit.selectAll()
        self.ui.name_edit.setFocus()

    def add_row(self):
        """Add row to data model."""
        self.model.insertRow(self.model.rowCount())
        self.page_model.show_row(self.model.rowCount() - 1)
        index = self.page_model.mapFromSource(
            self.model.index(self.model.rowCount() - 1, 0)
        )
        self.ui.data_view.setCurrentIndex(index)
        self.ui.data_view.scrollTo(index)

    def add_rows_dialog(self):
        count, accepted = QtWidgets.QInputDialog.getInt(
            self, "添加行", "在表格末尾添加的行数：", 100, 1, 1000000
        )
        if accepted:
            self.model.insertRows(self.model.rowCount(), count)
            self.page_model.show_row(self.model.rowCount() - 1)
            index = self.page_model.mapFromSource(
                self.model.index(self.model.rowCount() - 1, 0)
            )
            self.ui.data_view.setCurrentIndex(index)
            self.ui.data_view.scrollTo(index)

    def selected_full_columns(self):
        # Qt selectedColumns() checks flags for every row in a full column.
        # All source rows are selectable; determine coverage from rectangle bounds.
        ranges = list(self.selection.selection())
        result = []
        for column in range(self.model.columnCount()):
            intervals = sorted(
                (block.top(), block.bottom())
                for block in ranges
                if block.left() <= column <= block.right()
            )
            end = -1
            for first, last in intervals:
                if first > end + 1:
                    break
                end = max(end, last)
            if end >= self.model.rowCount() - 1 and self.model.rowCount():
                result.append(column)
        return result

    def get_selected_column_labels(self) -> list[str]:
        return [
            self.model.columnLabel(column) for column in self.selected_full_columns()
        ]

    def remove_selected_columns(self):
        """Remove selected column(s) from data model."""
        selected_columns = self.selected_full_columns()
        if selected_columns:
            self.model.remove_spans(
                [(column, 1) for column in selected_columns], columns=True
            )
        else:
            dialogs.show_warning_dialog(
                parent=self, msg="You must select one or more columns."
            )

    def remove_selected_row(self):
        """Remove selected row(s) from data model."""
        ranges = list(self.page_model.mapSelectionToSource(self.selection.selection()))
        spans = [
            (block.top(), block.height())
            for block in ranges
            if block.left() == 0 and block.right() == self.model.columnCount() - 1
        ]
        if spans:
            self.model.remove_spans(spans)
        else:
            self.main_window.statusBar().showMessage("请先选中要删除的整行。")

    def rename_selected_column(self, name):
        """Rename a column.

        Renames the currently selected column.

        Args:
            name: a QString containing the new name.
        """
        col_idx = self._selected_col_idx
        if col_idx is not None and name and name not in self.model.columnNames():
            new_name = self.model.renameColumn(col_idx, name)
            # Set the normalized name to the name edit field. This can
            # change the cursor position because characters may be replaced
            # (like spaces or digits at the start of the string). Move the
            # cursor to the 'expected' position: static with respect to the
            # end of the string.
            pos_from_end = len(name) - self.ui.name_edit.cursorPosition()
            new_pos = len(new_name) - pos_from_end
            self.ui.name_edit.setText(new_name)
            self.ui.name_edit.setCursorPosition(new_pos)

    def update_column_expression(self, expression):
        """Update a column expression.

        Tries to recalculate the values of the currently selected column in the
        data model.

        Args:
            expression: a QString containing the mathematical expression.
        """
        if self._selected_col_idx is not None:
            self.model.updateColumnExpression(self._selected_col_idx, expression)
            self.update_expression_border(self._selected_col_idx)

    def selection_changed(self, selected=None, deselected=None):
        """Handle selectionChanged events in the data view.

        When the selection is changed, the column index of the left-most cell in
        the first selection is used to identify the column name and the
        mathematical expression that is used to calculate the column values.
        These values are used to update the column information in the user
        interface.

        Note: the selected and deselected parameters are ignored. They only tell
        you about the changes in selection being made. So, for example, if you
        first select a column and then select a single cell within that column,
        selected will be empty (no extra cells selected) and deselected will
        contain all other cells in the column. This is not very useful to
        determine the current selection. Therefore, the current selection is
        retrieved instead of using the arguments.

        Args:
            selected: QItemSelection containing the newly selected cells.
            deselected: QItemSelection containing previously selected, and now
            deselected, items.
        """
        selected = self.selection.selection()
        if not selected.isEmpty():
            self.ui.nameLabel.setEnabled(True)
            self.ui.name_edit.setEnabled(True)
            first_selection = selected.first()
            col_idx = first_selection.left()
            self._selected_col_idx = col_idx
            self.ui.name_edit.setText(self.model.columnName(col_idx))
            self.ui.formula_edit.setText(self.model.columnExpression(col_idx))
            if self.model.isCalculatedColumn(col_idx):
                self.ui.formulaLabel.setEnabled(True)
                self.ui.formula_edit.setEnabled(True)
            else:
                self.ui.formulaLabel.setEnabled(False)
                self.ui.formula_edit.setEnabled(False)
            self.update_expression_border(col_idx)
        else:
            self.ui.nameLabel.setEnabled(False)
            self.ui.name_edit.clear()
            self.ui.name_edit.setEnabled(False)
            self.ui.formulaLabel.setEnabled(False)
            self.ui.formula_edit.clear()
            self.ui.formula_edit.setEnabled(False)

    def update_expression_border(self, col_idx: int) -> None:
        """Update border of the calculated column expression widget.

        If the expression is not valid, draw a red border around the widget.

        Args:
            col_idx (int): the column index.
        """
        if self.model.data_model.is_column_valid(self.model.columnLabel(col_idx)):
            self.ui.formula_edit.setStyleSheet("border: 0px")
        else:
            self.ui.formula_edit.setStyleSheet("border: 1px solid red")

    def column_moved(self, logidx, oldidx, newidx):
        """Move column in reaction to UI signal.

        Dragging a column to a new location triggers execution of this method.
        Since the UI only reorders the column visually and does not change the
        underlying data, things can get tricky when trying to determine which
        variables are available to the left of calculated columns and which
        columns include the bouding box of a selection for copy/paste. So, we
        will immediately move back the column in the view and move the
        underlying data instead. That way, visual and logical ordering are
        always in sync.

        Qt conventions are a bit weird and inconsistent, unfortunately. Moving a
        column requires calling the moveColumn() method with sourceIndex and
        destinationChild parameters. DestinationChild is the would-be index in
        the initial table, _before_ the move operation is completed. So, if you
        have the initial state:

            col0, col1, col2, col3

        and you want to end up with the final state:

            col1, col2, col0, col3

        you want the operation:

            col0, col1, col2, col3
              |--------------^

        and you should call `moveColumn(0, 3)` to move col0 from index 0 to be
        inserted at index 3, i.e. you want to place col0 _before_ col3. This +1
        behaviour does not occur when moving a column to the left instead of to
        the right since then you don't have to adjust for the removal of the
        source column.

        The problem is that newidx does _not_ behave that way. The argument
        oldidx works on the initial state and the argument newidx works on the
        final state. So the above move operation `moveColumn(0, 3)` has
        oldidx = 0 and newidx = 2 (check the final state).

        Args:
            logidx (int): the logical column index (index in the dataframe)
            oldidx (int): the old visual index newidx (int): the new visual
            index
        """
        # Raise an exception when column ordering has been messed up
        assert logidx == oldidx

        header = self.ui.data_view.horizontalHeader()
        header.blockSignals(True)
        # move the column back, keep the header in logical order
        header.moveSection(newidx, oldidx)
        header.blockSignals(False)
        # move the underlying data column instead
        if newidx > oldidx:
            # moving to the right
            destidx = newidx + 1
        else:
            destidx = newidx
        self.model.moveColumn(sourceColumn=oldidx, destinationChild=destidx)
        # select the column that was just moved at the new location
        self.ui.data_view.selectColumn(newidx)
        self._selected_col_idx = newidx

    def edit_or_move_down(self):
        """Edit cell or move cursor down a row.

        Start editing a cell. If the cell was already being edited, move the
        cursor down a row, stopping the edit in the process. Trigger a
        recalculation of all calculated columns.
        """
        cur_index = self.ui.data_view.currentIndex()
        if not self.ui.data_view.isPersistentEditorOpen(cur_index):
            # is not yet editing, so start an edit
            self.ui.data_view.edit(cur_index)
        else:
            # is already editing, what index is below?
            new_index = self.get_index_below_selected_cell()
            if new_index == cur_index:
                # already on bottom row, create a new row and take that index
                self.add_row()
                new_index = self.get_index_below_selected_cell()
            # move to it (finishing editing in the process)
            self.ui.data_view.setCurrentIndex(new_index)

    def clear_selected_cells(self):
        """Clear contents of selected cells."""
        self.model.clearData(
            self.page_model.mapSelectionToSource(self.selection.selection())
        )

    def get_index_below_selected_cell(self):
        """Get index directly below the selected cell."""
        return self.ui.data_view.moveCursor(
            QtWidgets.QTableView.MoveDown, QtCore.Qt.NoModifier
        )

    def cut_selected_cells(self):
        if self.selection.selection().isEmpty():
            return
        self.copy_selected_cells(cut=True)

    def copy_selected_cells(self, cut=False):
        """Copy selected cells to clipboard."""

        if self.selection.selection().isEmpty():
            return
        if self.clipboard_busy():
            self.main_window.statusBar().showMessage("剪贴板操作尚未结束，请等待完成。")
            return
        selected = self.page_model.mapSelectionToSource(self.selection.selection())
        data = self.model.dataFromSelection(selected)
        if data.size >= 50000:
            if self._clipboard_job is not None:
                self._clipboard_job.deleteLater()
            revision = self._edit_revision
            self._paste_cancelled = False
            self._paste_progress = QtWidgets.QProgressDialog(
                "正在准备复制数据…", "取消", 0, 0, self
            )
            self._paste_progress.setWindowModality(QtCore.Qt.NonModal)
            self._paste_progress.setMinimumDuration(0)
            self._paste_progress.canceled.connect(
                lambda: setattr(self, "_paste_cancelled", True)
            )
            self._clipboard_job = ClipboardWriter(data, self)
            self._clipboard_job.loaded.connect(
                lambda text: self.finish_copy(text, cut, revision, selected)
            )
            self._clipboard_job.failed.connect(self.paste_failed)
            self._clipboard_pending = True
            self._clipboard_job.start()
            return
        self.clipboard.setText(self.array_to_text(data))
        if cut:
            self.model.clearData(selected)

    def finish_copy(self, text, cut, revision, selection):
        self._clipboard_pending = False
        self._paste_progress.reset()
        if self._paste_cancelled:
            return
        self.clipboard.setText(text)
        if cut:
            if revision == self._edit_revision:
                self.model.clearData(selection)
            else:
                self.main_window.statusBar().showMessage(
                    "已复制；表格已改变，因此未执行剪切清空。"
                )

    def paste_cells(self):
        """Paste cells from clipboard."""

        selection = self.selection.selection()
        current = self.ui.data_view.currentIndex()
        row = (
            min((r.top() for r in selection), default=max(0, current.row()))
            + self.page_model.offset
        )
        col = min((r.left() for r in selection), default=max(0, current.column()))
        text = self.clipboard.text()
        formats = tuple(
            self.model.column_metadata(c).get("format", "numeric")
            for c in range(col, self.model.columnCount())
        )
        if self.clipboard_busy():
            self.main_window.statusBar().showMessage("正在解析上一次粘贴，请等待完成。")
            return
        if len(text) >= 100000:
            if self._clipboard_job is not None:
                self._clipboard_job.deleteLater()
            revision = self._edit_revision
            self._paste_cancelled = False
            self._paste_progress = QtWidgets.QProgressDialog(
                "正在解析粘贴数据…", "取消", 0, 0, self
            )
            self._paste_progress.setWindowModality(QtCore.Qt.NonModal)
            self._paste_progress.setMinimumDuration(0)
            self._paste_progress.canceled.connect(
                lambda: setattr(self, "_paste_cancelled", True)
            )
            self._clipboard_job = ClipboardReader(text, self, formats)
            self._clipboard_job.loaded.connect(
                lambda values: self.finish_paste(row, col, revision, values)
            )
            self._clipboard_job.failed.connect(self.paste_failed)
            self._clipboard_pending = True
            self._clipboard_job.start()
            return
        values = self.text_to_array(text, formats)
        self.apply_paste(row, col, values)

    def paste_failed(self, message):
        self._clipboard_pending = False
        self._paste_progress.reset()
        self.main_window.statusBar().showMessage(f"粘贴失败，原表保留：{message}")

    def finish_paste(self, row, col, revision, values):
        self._clipboard_pending = False
        self._paste_progress.reset()
        if self._paste_cancelled:
            return
        if self._edit_revision != revision:
            self.main_window.statusBar().showMessage(
                "粘贴解析期间表格已改变，已丢弃过期结果，请重新粘贴。"
            )
            return
        self.apply_paste(row, col, values)

    def apply_paste(self, row, col, values):
        if values is None:
            return
        if not self.model.setDataFromArray(self.model.createIndex(row, col), values):
            return
        self.page_model.show_row(row)
        first = self.page_model.mapFromSource(self.model.index(row, col))
        last = self.page_model.index(
            min(first.row() + values.shape[0] - 1, self.page_model.rowCount() - 1),
            col + values.shape[1] - 1,
        )
        self.selection.select(
            QtCore.QItemSelection(first, last),
            self.selection.SelectionFlag.ClearAndSelect,
        )

    def array_to_text(self, data: np.ndarray) -> str:
        # create tab separated values from data, NaN -> empty string, e.g.
        # 1 2 3
        # 2   4
        # 5 5 6
        return "\n".join(
            [
                "\t".join(
                    [
                        __import__(
                            "tailor.clipboard_worker", fromlist=["cell_text"]
                        ).cell_text(v)
                        for v in row
                    ]
                )
                for row in data
            ]
        )

    def text_to_array(self, text: str, formats=()) -> np.ndarray | None:
        """Convert tab-separated values to an array.

        Args:
            text (str): a multi-line string of tab-separated values.

        Returns:
            np.ndarray: the data as a NumPy array
        """
        try:
            result = parse_matrix(text, formats)
        except ValueError as exc:
            self.main_window.ui.statusbar.showMessage(
                f"粘贴失败：{exc}", timeout=MSG_TIMEOUT
            )
            return None
        return (
            np.asarray(
                result, dtype=object if any(k != "numeric" for k in formats) else float
            )
            if result
            else None
        )

"""Sequential selected-column fitting through the existing lmfit worker/results."""

import shiboken6
from PySide6 import QtCore, QtWidgets


class ColumnFitQueue(QtCore.QObject):
    def __init__(self, sheet, x, ys, preset):
        super().__init__(sheet.main_window)
        self.sheet, self.window = sheet, sheet.main_window
        self.x, self.ys, self.preset = x, list(ys), preset
        self.completed = 0
        self.window._column_fit_queue = self

    def start_next(self):
        if not shiboken6.isValid(self.sheet):
            self.finish("源工作表已关闭，停止后续拟合。")
            return
        if not self.ys:
            self.finish(
                f"已完成 {self.completed} 列拟合；每列都有拟合数据和蓝色结果页。"
            )
            return
        y = self.ys.pop(0)
        if (
            y not in self.sheet.model.columnLabels()
            or self.x not in self.sheet.model.columnLabels()
        ):
            self.finish("源列已删除，停止后续拟合。")
            return
        source = next(
            (
                p
                for p in self.window.get_plots()
                if p.data_sheet is self.sheet
                and p.model.x_col == self.x
                and p.model.y_col == y
            ),
            None,
        )
        if source is None:
            source = self.window.create_plot_tab(self.sheet, self.x, y)
        source.model.set_fit_domain_enabled(False)
        source.update_fit_domain_from_model()
        source.preset_controls.choose(self.preset)
        source.property_tabs.setCurrentIndex(next(i for i in range(source.property_tabs.count()) if source.property_tabs.tabText(i) == '拟合'))
        self.window.ui.tabWidget.setCurrentWidget(source)
        source.perform_fit()
        job = source._fit_job
        if job is None:
            self.finish("未能开始拟合，请检查数据与模型。")
            return
        # Existing completion slot publishes results first. Queue only after it returns.
        job.finished.connect(lambda: self.after_job(job, source))

    def after_job(self, job, source):
        success = (
            job.outcome == "success"
            and not job.isInterruptionRequested()
            and source.model.best_fit is job.result
        )
        if not success:
            self.finish("批量拟合已停止；已完成的结果保留。")
            return
        self.completed += 1
        QtCore.QTimer.singleShot(0, self, self.start_next)

    def finish(self, message):
        self.window.statusBar().showMessage(message)
        self.window._column_fit_queue = None
        self.deleteLater()


def fit_selected_columns(sheet):
    window = sheet.main_window
    if window.data_operation_busy() or getattr(window, "_column_fit_queue", None):
        window.statusBar().showMessage("请等待当前计算完成。")
        return
    columns = sorted(
        {
            c
            for block in sheet.selection.selection()
            for c in range(block.left(), block.right() + 1)
        }
    )
    roles = [
        sheet.model.column_metadata(c)["role"] for c in range(sheet.model.columnCount())
    ]
    ys = [c for c in columns if roles[c] not in {"X", "XErr", "YErr"}]
    if not ys:
        window.statusBar().showMessage("请先点击列字母选择 Y 列；按住 ⌘ 可选择多列。")
        return
    from tailor.fit_presets import list_presets
    from tailor.graph_controls import combo

    dialog = QtWidgets.QDialog(sheet)
    dialog.setWindowTitle("拟合选中列")
    layout = QtWidgets.QFormLayout(dialog)
    labels = list(sheet.model.columnLabels())
    x = combo(
        [
            (__import__("tailor.column_titles",fromlist=["display"]).display(sheet.model,labels[c]), labels[c])
            for c in range(len(labels))
            if c not in ys and labels[c] in __import__("tailor.choice_catalog",fromlist=["visible_columns"]).visible_columns(sheet.model)
        ]
    )
    xs = [c for c, role in enumerate(roles) if role == "X"]
    if xs:
        x.setCurrentIndex(max(0, x.findData(labels[xs[0]])))
    if not x.count():
        window.statusBar().showMessage(
            "请留出一列作为 X；先将该列角色设为 X，再选择 Y 列。"
        )
        return
    preset = combo([(p.title, p.key) for p in list_presets()])
    preset.setCurrentIndex(max(0, preset.findData("linear")))
    selected = QtWidgets.QLabel("、".join(__import__("tailor.column_titles",fromlist=["display"]).display(sheet.model,labels[c]) for c in ys))
    selected.setWordWrap(True)
    layout.addRow("Y 列", selected)
    layout.addRow("共用 X 列", x)
    layout.addRow("拟合模型", preset)
    note = QtWidgets.QLabel(
        "各列依次独立拟合，使用完整数据范围；结果写入对应拟合列与蓝色结果页。复杂初值/指定区间可在各源图的拟合页调整后重拟合。取消当前拟合会停止队列。"
    )
    note.setWordWrap(True)
    note.setMaximumWidth(420)
    layout.addRow(note)
    buttons = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
    )
    buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("执行拟合")
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addRow(buttons)
    if dialog.exec() == QtWidgets.QDialog.Accepted:
        queue = ColumnFitQueue(
            sheet, x.currentData(), [labels[c] for c in ys], preset.currentData()
        )
        queue.start_next()

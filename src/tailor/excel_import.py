"""Pandas Excel adapters feeding Tailor's existing background importer."""

from tailor.compact_controls import CheckButton

from pathlib import Path

import pandas as pd
from PySide6 import QtWidgets

from tailor.data_model import DataModel


def choose_excel(window, filename):
    try:
        book = pd.ExcelFile(filename)
        names = book.sheet_names
        book.close()
    except Exception as exc:  # noqa: BLE001 - file/parser engines return heterogeneous errors
        QtWidgets.QMessageBox.warning(window, "Excel 导入失败", str(exc))
        return
    dialog = QtWidgets.QDialog(window)
    dialog.setWindowTitle("导入 Excel — " + Path(filename).name)
    layout = QtWidgets.QVBoxLayout(dialog)
    sheets = QtWidgets.QListWidget()
    sheets.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
    sheets.addItems(names)
    sheets.selectAll()
    header = CheckButton("首行作为列名")
    header.setChecked(True)
    layout.addWidget(QtWidgets.QLabel("选择工作表（可多选）"))
    layout.addWidget(sheets)
    layout.addWidget(header)
    buttons = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
    )
    layout.addWidget(buttons)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    if dialog.exec() != dialog.Accepted:
        window._csv_queue.clear()
        return
    selected = [i.text() for i in sheets.selectedItems()]
    if selected:
        # Queue sheet imports on the same single reader; no parallel data engines.
        window._csv_queue[0:0] = [
            (filename, {"excel_sheet": name, "header": header.isChecked()})
            for name in selected[1:]
        ]
        window.start_csv_import(
            filename, {"excel_sheet": selected[0], "header": header.isChecked()}
        )


def read_excel(filename, options):
    frame = pd.read_excel(
        filename,
        sheet_name=options["excel_sheet"],
        header=0 if options["header"] else None,
    )
    model = DataModel()
    for i, column in enumerate(frame.columns):
        model.insert_columns(i, 1)
        key = model.get_column_label(i)
        series = frame[column]
        # Store dates as ISO strings; presentation preference controls date/time display.
        if pd.api.types.is_datetime64_any_dtype(series):
            series = series.dt.strftime("%Y-%m-%d %H:%M:%S").where(series.notna(), "")
        model._data[key] = series.to_numpy(copy=True)
        base = (
            str(column)
            if options["header"]
            else chr(65 + i)
            if i < 26
            else f"列{i + 1}"
        )
        name = model.normalize_column_name(base) or f"列{i + 1}"
        used = set(model._col_names.values()) - {model._col_names[key]}
        candidate, n = name, 2
        while candidate in used:
            candidate, n = f"{name}_{n}", n + 1
        model._col_names[key] = candidate
    model.excel_sheet_name = options["excel_sheet"]
    return model

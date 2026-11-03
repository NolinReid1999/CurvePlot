"""Category-specific previews read the existing provenance and result columns."""

import json
from types import SimpleNamespace

import numpy as np
import shiboken6
from PySide6 import QtWidgets

from tailor.analysis_records import records
from tailor.column_titles import display


def render(control):
    if not shiboken6.isValid(control) or not hasattr(control, "preview_table"):
        return
    table = control.preview_table
    if not shiboken6.isValid(table) or not shiboken6.isValid(control.owner):
        return
    table.setRowCount(0)
    category = control.category
    outputs = []
    sheets = control.sheets()
    for record in records(control.owner):
        recipe = record["recipe"]
        if ("平滑与校正" if recipe["title"]=="数据预处理" else recipe["title"]) != category:
            continue
        if any(
            o["sheet"] not in sheets
            or o["key"] not in sheets[o["sheet"]].model.columnLabels()
            for o in recipe["objects"]
        ):
            continue
        for sheet, key, slot, _ in record["outputs"]:
            meta = sheet.model.column_metadata(
                list(sheet.model.columnLabels()).index(key)
            )
            source = json.loads(meta["source"])
            original = source["column"]
            name = display(sheet.model, original)
            values = np.asarray(sheet.model.data_model.get_column(key))
            finite = np.flatnonzero(np.isfinite(values))
            index = sorted(set(list(finite[:12]) + list(finite[-3:])))
            label = meta.get("comment") or meta["name"]
            outputs.extend(
                (
                    name,
                    label + (f" / 行{i + 1}" if len(index) > 1 else ""),
                    f"{values[i]:.10g}",
                )
                for i in index
            )
    if not outputs:
        cached = getattr(control, "_preview_by_category", {}).get(category)
        if cached and all(
            sid in sheets and key in sheets[sid].model.columnLabels()
            for sid, key in cached["sources"]
        ):
            outputs = cached["rows"]
    table.setRowCount(len(outputs))
    for i, row in enumerate(outputs):
        for j, text in enumerate(row):
            table.setItem(i, j, QtWidgets.QTableWidgetItem(text))
    control.preview_card.setVisible(bool(outputs))
    control.message.hide()


def remember(control):
    if not hasattr(control, "_preview_by_category"):
        control._preview_by_category = {}
    if control.create_result:
        control._preview_by_category.pop(control.title,None)
        render(control)
        return
    table = control.preview_table
    control._preview_by_category[control.title] = {
        "sources": [(c["sheet"], c["key"]) for c in control.inputs],
        "rows": [
            tuple(table.item(i, j).text() for j in range(3))
            for i in range(table.rowCount())
        ],
    }
    render(control)


def delete_menu(control, button):
    from tailor.result_pages import delete_processing

    menu = QtWidgets.QMenu(button)
    menu._keepalive = []
    for record in records(control.owner):
        if record["recipe"]["title"] != control.category:
            continue
        tab = SimpleNamespace(
            owner=control.owner, record=record, record_id=record["recipe"]["id"]
        )
        menu._keepalive.append(tab)
        title = "、".join(display(s.model, k) for s, k, *_ in record["outputs"])
        menu.addAction(
            title,
            lambda checked=False, tab=tab: (delete_processing(tab), render(control)),
        )
    if not menu.actions():
        menu.addAction("当前类别没有已生成结果").setEnabled(False)
    menu.exec(button.mapToGlobal(button.rect().bottomLeft()))

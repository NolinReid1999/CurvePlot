"""One visible worksheet; append imports and migrate old sheets without losing rows."""

import copy
import json
import re

from PySide6 import QtCore

from tailor.qdata_model import QDataModel


def overwrite_import(sheet, data, origin=""):
    """Import at A, preserving positional identities and one structural undo."""
    model = sheet.model
    keys = []

    def apply():
        model.beginResetModel()
        try:
            target = model.data_model
            while model.columnCount() < data.num_columns():
                target.insert_columns(model.columnCount(), 1)
            keys.extend(list(model.columnLabels())[:data.num_columns()])
            rows = max(model.rowCount(), data.num_rows()) if model.columnCount() > len(keys) else data.num_rows()
            target._data = target._data.reindex(range(rows))
            # Free only overwritten names before normalizing the incoming ones.
            for key in keys:
                target._col_names.pop(key, None)
                target._calculated_column_expression.pop(key, None)
                target._is_calculated_column_valid.pop(key, None)
                target._excluded.pop(key, None)
            for i, (old, key) in enumerate(zip(data.get_column_labels(), keys)):
                original = data.get_column_name(old)
                base = data.normalize_column_name(original) or "Column"
                name, n = base, 2
                while name in target._col_names.values():
                    name = f"{base}_{n}"
                    n += 1
                target._col_names[key] = name
                target._data[key] = data._data[old].reset_index(drop=True).reindex(range(rows))
                model._metadata[key] = {
                    "source": origin if i == 0 else json.dumps({"import": origin, "result_x": keys[0]}, ensure_ascii=False),
                    "import_name": original, "comment": original,
                    "role": "X" if i == 0 else "Y" if i == 1 else "none",
                    "format": "numeric" if data._data[old].dtype.kind in "biufc" else "text",
                }
            target.recalculate_all_columns()
        finally:
            model.endResetModel()

    if not model._structural("从A列覆盖导入", apply):
        raise ValueError("导入超过撤销内存上限，未覆盖原数据。")
    sheet._last_imported_keys = keys
    return keys


def append_import(sheet, data, origin=""):
    model = sheet.model
    mapping = {}
    added = []

    def apply():
        rows = max(model.rowCount(), data.num_rows())
        if rows > model.rowCount():
            QDataModel.insertRows(model, model.rowCount(), rows - model.rowCount())
        for old in data.get_column_labels():
            column = model.columnCount()
            QDataModel.insertColumns(model, column, 1)
            key = model.columnLabel(column)
            mapping[old] = key
            added.append(key)
            original = data.get_column_name(old)
            name = model.data_model.normalize_column_name(original) or "Column"
            base = name
            n = 2
            while name in model.data_model._col_names.values():
                name = f"{base}_{n}"
                n += 1
            model.data_model._col_names[key] = name
            model.data_model._data[key] = (
                data._data[old].reset_index(drop=True).reindex(range(rows))
            )
            model._metadata[key] = {
                "source": origin,
                "import_name": original,
                "role": "X" if len(added) == 1 else "Y",
                "format": "numeric"
                if data._data[old].dtype.kind in "biufc"
                else "text",
            }
        if added:
            for key in added[1:]:
                model._metadata[key]["source"] = json.dumps(
                    {"import": origin, "result_x": added[0]}, ensure_ascii=False
                )
        model._notify_data()
        model.headerDataChanged.emit(
            QtCore.Qt.Horizontal, 0, max(0, model.columnCount() - 1)
        )

    if not model._structural("导入并追加列", apply):
        raise ValueError("导入超过当前撤销内存上限，原表已保留，请拆分文件。")
    sheet._last_imported_keys = added
    return added


def migrate_project(project):
    sheets = project.get("sheets", [])
    if len(sheets) <= 1:
        if sheets:
            sheets[0]["default_sheet"] = True
        return project
    project = copy.deepcopy(project)
    sheets = project["sheets"]
    main = sheets[0]
    sid = main["id"]
    mapping = {}
    names = {}
    counter = max([s.get("new_col_num", 0) for s in sheets] + [0])
    used = set(main["data"])
    used_names = set(main["col_names"].values())
    rows = max(len(v) for s in sheets for v in s["data"].values())
    for sheet in sheets:
        for key in sheet["data"]:
            if sheet is main:
                new = key
            else:
                counter += 1
                new = f"col{counter}"
                while new in used:
                    counter += 1
                    new = f"col{counter}"
            used.add(new)
            mapping[(sheet["id"], key)] = new
            name = sheet["col_names"][key]
            base = name
            n = 2
            if sheet is not main:
                while name in used_names:
                    name = f"{base}_{n}"
                    n += 1
                used_names.add(name)
            names[(sheet["id"], sheet["col_names"][key])] = name
    column_fields = {
        "x",
        "y",
        "x_col",
        "y_col",
        "x_err_col",
        "y_err_col",
        "column_id",
        "xkey",
        "key",
        "column",
        "result_x",
    }

    def remap(value, context=None, field=""):
        if isinstance(value, list):
            if (
                len(value) >= 2
                and isinstance(value[0], int)
                and isinstance(value[1], str)
                and (value[0], value[1]) in mapping
            ):
                return [
                    sid,
                    mapping[(value[0], value[1])],
                    *[remap(v, context, field) for v in value[2:]],
                ]
            return [remap(v, context, field) for v in value]
        if isinstance(value, dict):
            context = value.get("data_sheet_id", value.get("sheet", context))
            result = {}
            for k, v in value.items():
                if (
                    k in {"data_sheet_id", "sheet"}
                    and isinstance(v, int)
                    and any(old == v for old, _ in mapping)
                ):
                    result[k] = sid
                elif k in column_fields and isinstance(v, str):
                    result[k] = mapping.get((context, v), v)
                else:
                    result[k] = remap(v, context, k)
            return result
        return value

    combined = {
        k: {}
        for k in (
            "data",
            "col_names",
            "column_metadata",
            "calculated_column_expression",
            "excluded",
        )
    }
    for sheet in sheets:
        source_x = next(
            (
                k
                for k, m in sheet.get("column_metadata", {}).items()
                if m.get("role") == "X"
            ),
            None,
        )
        for old, values in sheet["data"].items():
            new = mapping[(sheet["id"], old)]
            combined["data"][new] = values + [None] * (rows - len(values))
            combined["col_names"][new] = names[(sheet["id"], sheet["col_names"][old])]
            meta = copy.deepcopy(sheet.get("column_metadata", {}).get(old, {}))
            source = meta.get("source", "")
            try:
                payload = remap(json.loads(source), sheet["id"]) if source else {}
            except (ValueError, TypeError):
                payload = {"import": source}
            if source_x and old != source_x:
                payload["result_x"] = mapping[(sheet["id"], source_x)]
            if payload:
                meta["source"] = json.dumps(payload, ensure_ascii=False)
            combined["column_metadata"][new] = meta
            if old in sheet.get("excluded", {}):
                combined["excluded"][new] = sheet["excluded"][old]
            expr = sheet.get("calculated_column_expression", {}).get(old)
            if expr:
                replacements = {
                    **{k: v for (s, k), v in mapping.items() if s == sheet["id"]},
                    **{k: v for (s, k), v in names.items() if s == sheet["id"]},
                }
                combined["calculated_column_expression"][new] = re.sub(
                    r"\b[A-Za-z_]\w*\b",
                    lambda m, replacements=replacements: replacements.get(m[0], m[0]),
                    expr,
                )
    project = remap(project)
    main = project["sheets"][0]
    main.update(combined, new_col_num=counter, default_sheet=True)
    project["sheets"] = [main]
    project["sheet_num"] = max(project.get("sheet_num", 1), sid)
    project["tab_order"] = [
        t
        for t in project.get("tab_order", [])
        if not t.startswith("sheet_") or t == f"sheet_{sid}"
    ]
    project["current_tab"] = min(
        project.get("current_tab", 0), max(0, len(project["tab_order"]) - 1)
    )
    return project


def from_dataframe(frame):
    from tailor.data_model import DataModel

    data = DataModel()
    labels = [f"col{i + 1}" for i in range(len(frame.columns))]
    data._data = frame.copy()
    data._data.columns = labels
    data._col_names = dict(zip(labels, map(str, frame.columns)))
    data._new_col_num = len(labels)
    data._calculated_column_expression = {}
    data._is_calculated_column_valid = {}
    data._excluded = {}
    return data

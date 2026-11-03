"""Transactional numeric spreadsheet edits with bounded undo and stable metadata."""

import copy
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd
from PySide6 import QtCore, QtGui

from tailor.qdata_model import QDataModel

INVALID = QtCore.QModelIndex()


@dataclass
class Edit:
    label: str
    backward: Callable
    forward: Callable
    size: int


class SpreadsheetModel(QDataModel):
    historyChanged = QtCore.Signal()
    editRejected = QtCore.Signal(str)
    HISTORY_BYTES = 128 * 1024 * 1024
    HISTORY_ENTRIES = 1000

    def __init__(self, main_window):
        super().__init__(main_window)
        self._history = []
        self._cursor = 0
        self._replaying = False
        self._metadata = {}
        self.removal_guard = None
        self.configure_history()
        from tailor.app_preferences import preferences
        preferences().changed.connect(self.preferences_changed)

    @property
    def can_undo(self):
        return self._cursor > 0

    @property
    def can_redo(self):
        return self._cursor < len(self._history)

    @property
    def history_bytes(self):
        return sum(item.size for item in self._history)

    def clear_history(self):
        self._history.clear()
        self._cursor = 0
        self.historyChanged.emit()

    def _accept(self, estimate):
        if estimate > self.HISTORY_BYTES:
            self.editRejected.emit("此操作超过撤销内存上限，未修改数据。请分批操作。")
            return False
        return True

    def _record(self, edit):
        if self._replaying:
            return
        del self._history[self._cursor :]
        self._history.append(edit)
        trimmed = False
        while len(self._history) > 1 and (
            self.history_bytes > self.HISTORY_BYTES
            or len(self._history) > self.HISTORY_ENTRIES
        ):
            self._history.pop(0)
            trimmed = True
        if trimmed:
            self.editRejected.emit(
                "撤销历史达到内存上限，最早的记录已释放；本次编辑可撤销。"
            )
        self._cursor = len(self._history)
        self.main_window.mark_project_dirty()
        self.historyChanged.emit()

    def configure_history(self):
        from tailor.app_preferences import preferences
        state = preferences()
        self.HISTORY_BYTES = state.get('undo/mib') * 1024 * 1024
        self.HISTORY_ENTRIES = state.get('undo/entries')

    def preferences_changed(self, key):
        if key.startswith('undo/'):
            self.configure_history()

    def undo(self):
        if self.can_undo:
            self._replaying = True
            try:
                if self._history[self._cursor - 1].backward() is False:
                    return
            finally:
                self._replaying = False
            self._cursor -= 1
            self.main_window.mark_project_dirty()
            self.historyChanged.emit()

    def redo(self):
        if self.can_redo:
            self._replaying = True
            try:
                if self._history[self._cursor].forward() is False:
                    return
            finally:
                self._replaying = False
            self._cursor += 1
            self.main_window.mark_project_dirty()
            self.historyChanged.emit()

    def column_metadata(self, column):
        from tailor.column_titles import letters

        label = self.columnLabel(column)
        return {
            "id": label,
            "title": letters(column),
            "name": self.columnName(column),
            "role": "none",
            "unit": "",
            "comment": "",
            "source": "",
            **self._metadata.get(label, {}),
        }

    def set_column_metadata(self, column, *, _record_edit=True, **values):
        if not 0 <= column < self.columnCount():
            return False
        if set(values) - {
            "name",
            "title",
            "role",
            "unit",
            "comment",
            "source",
            "format",
            "notation",
            "decimals",
            "halign",
            "valign",
            "hidden",
        }:
            raise ValueError("Unknown column metadata")
        if "role" in values and values["role"] not in {
            "none",
            "X",
            "Y",
            "XErr",
            "YErr",
        }:
            raise ValueError("Invalid column role")
        if not all(isinstance(value, str) for value in values.values()):
            raise ValueError("Column properties must be text")
        label = self.columnLabel(column)
        old_name = self.columnName(column)
        old = copy.deepcopy(self._metadata.get(label, {}))
        new = {**old, **{key: value for key, value in values.items() if key != "name"}}
        new_name = self.data_model.normalize_column_name(values.get("name", old_name))
        if not new_name or any(
            name == new_name and key != label
            for key, name in self.data_model._col_names.items()
        ):
            self.editRejected.emit("列名不能为空或与其他列重复。")
            return False
        if old == new and old_name == new_name:
            return True

        def apply(name, metadata):
            self.data_model._col_names[label] = name
            self._metadata[label] = copy.deepcopy(metadata)
            self.headerDataChanged.emit(
                QtCore.Qt.Horizontal, 0, max(0, self.columnCount() - 1)
            )
            if "title" in values and hasattr(self, "title_callback"):
                self.title_callback(label)
            callback = getattr(self, "metadata_callback", None)
            if callback is not None:
                callback(label)

        size = (
            512
            + len(old_name.encode())
            + len(new_name.encode())
            + sum(
                len(str(value).encode())
                for mapping in (old, new)
                for value in mapping.values()
            )
        )
        if not self._accept(size):
            return False
        apply(new_name, new)
        if _record_edit:
            self._record(
                Edit(
                    "列属性",
                    lambda: apply(old_name, old),
                    lambda: apply(new_name, new),
                    size,
                )
            )
        return True

    def renameColumn(self, column, name):
        self.set_column_metadata(column, name=name)
        return self.columnName(column)

    def set_columns_metadata(self, columns, *, title='设置所选列属性', **values):
        """Group metadata-only column edits into one bounded undo operation."""
        if 'name' in values:
            raise ValueError('Batch names must be assigned individually')
        keys=[self.columnLabel(c) for c in sorted(set(columns)) if 0<=c<self.columnCount()]
        before={key:copy.deepcopy(self._metadata.get(key,{})) for key in keys}
        size=1024*len(keys)+2*sum(len(repr(meta).encode()) for meta in before.values())
        if not self._accept(size):return False
        def restore(state):
            for key,meta in state.items():
                if key not in self.columnLabels():continue
                self._metadata[key]=copy.deepcopy(meta)
            self.headerDataChanged.emit(QtCore.Qt.Horizontal,0,max(0,self.columnCount()-1))
            callback=getattr(self,'metadata_callback',None)
            if callback:
                for key in state:
                    if key in self.columnLabels():callback(key)
        try:
            for key in keys:
                if not self.set_column_metadata(list(self.columnLabels()).index(key),_record_edit=False,**values):
                    restore(before);return False
        except Exception:
            restore(before)
            raise
        after={key:copy.deepcopy(self._metadata.get(key,{})) for key in keys}
        if before!=after:self._record(Edit(title,lambda:restore(before),lambda:restore(after),size))
        return True

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if orientation == QtCore.Qt.Horizontal and 0 <= section < self.columnCount():
            meta = self.column_metadata(section)
            if role == QtCore.Qt.ToolTipRole:
                return f"ID: {meta['id']}\n单位: {meta['unit']}\n名称: {meta['comment']}\n来源: {meta['source']}"
            if role == QtCore.Qt.DisplayRole:
                designation = f" [{meta['role']}]" if meta["role"] != "none" else ""
                unit = f" ({meta['unit']})" if meta["unit"] else ""
                return f"{meta['name']}{designation}{unit}"
        return super().headerData(section, orientation, role)

    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid():
            return None
        excluded = index.row() in self.data_model._excluded.get(
            self.columnLabel(index.column()), ()
        )
        if excluded and role == QtCore.Qt.ForegroundRole:
            return QtGui.QBrush(QtGui.QColor("#bc702b"))
        if excluded and role == QtCore.Qt.FontRole:
            font = QtGui.QFont()
            font.setStrikeOut(True)
            return font
        if excluded and role == QtCore.Qt.ToolTipRole:
            return "已排除：原值保留，不参与拟合与统计。"
        if role in (QtCore.Qt.DisplayRole, QtCore.Qt.EditRole):
            value = self.data_model.get_value(index.row(), index.column())
            if pd.isna(value):
                return ""
            if role == QtCore.Qt.EditRole:
                return str(value)
            meta = self.column_metadata(index.column())
            kind = meta.get("format", "numeric")
            if kind == "text":
                return str(value)
            if kind in {"date", "time"}:
                try:
                    if isinstance(value, (int, float, np.number)):
                        stamp = pd.Timestamp("1899-12-30") + pd.to_timedelta(
                            float(value), unit="D"
                        )
                    else:
                        stamp = pd.Timestamp(value)
                    return stamp.strftime("%Y-%m-%d" if kind == "date" else "%H:%M:%S")
                except (ValueError, TypeError, OverflowError):
                    return str(value)
            try:
                number = float(value)
                digits = int(meta.get("decimals", "6"))
                style = meta.get("notation", "decimal")
                if style == "grouped":
                    return f"{number:,.{digits}f}"
                if style == "scientific":
                    return f"{number:.{digits}e}"
                if style == "power":
                    mantissa, exponent = f"{number:.{digits}e}".split("e")
                    sup = str(int(exponent)).translate(
                        str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")
                    )
                    return mantissa + "×10" + sup
                return (
                    f"{number:.{digits}f}" if "decimals" in meta else f"{number:.10g}"
                )
            except (ValueError, TypeError):
                return str(value)
        return super().data(index, role)

    def setData(self, index, value, role=QtCore.Qt.EditRole):
        if (
            role != QtCore.Qt.EditRole
            or not index.isValid()
            or not (
                0 <= index.row() < self.rowCount()
                and 0 <= index.column() < self.columnCount()
            )
        ):
            return False
        if self.isCalculatedColumn(index.column()):
            self.editRejected.emit("计算列为只读，请修改源数据或计算表达式。")
            return False
        kind = self.column_metadata(index.column()).get("format", "numeric")
        if kind in {"text", "date", "time"}:
            key = self.columnLabel(index.column())
            if kind in {"date", "time"} and str(value).strip():
                try:
                    pd.Timestamp(value)
                except (ValueError, TypeError):
                    self.editRejected.emit(
                        "请输入有效日期或时间，例如 2026-10-23 12:00:00。"
                    )
                    return False

            def apply():
                self.data_model._data[key] = self.data_model._data[key].astype(object)
                self.data_model._data.iat[index.row(), index.column()] = str(value)
                self.data_model.recalculate_columns_from(key)
                self._notify_data()

            return self._structural("编辑单元格", apply)
        try:
            number = float(value) if str(value).strip() else np.nan
        except (TypeError, ValueError):
            self.editRejected.emit(
                f"第 {index.row() + 1} 行、第 {index.column() + 1} 列不是有效数值；原值保留。"
            )
            return False
        return self.setDataFromArray(index, np.array([[number]]))

    def _notify_data(self):
        if self.rowCount() and self.columnCount():
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(self.rowCount() - 1, self.columnCount() - 1),
            )

    def _snapshot(self):
        data = self.data_model
        return (
            data._data.copy(deep=True),
            copy.deepcopy(data._col_names),
            copy.deepcopy(data._calculated_column_expression),
            copy.deepcopy(data._is_calculated_column_valid),
            copy.deepcopy(self._metadata),
            data._new_col_num,
            copy.deepcopy(data._excluded),
        )

    def _restore(self, state):
        removed = set(self.data_model._data.columns) - set(state[0].columns)
        if (
            removed
            and self.removal_guard is not None
            and self.removal_guard(list(removed))
        ):
            self.editRejected.emit(
                "此操作会移除图形引用的列；请先移除相应图形，再撤销或重做。"
            )
            return False
        self.beginResetModel()
        data = self.data_model
        counter = data._new_col_num
        frame, names, expressions, valid, metadata, sequence, excluded = state
        data._data = frame.copy(deep=True)
        data._col_names = copy.deepcopy(names)
        data._calculated_column_expression = copy.deepcopy(expressions)
        data._is_calculated_column_valid = copy.deepcopy(valid)
        data._new_col_num = max(counter, sequence)
        self._metadata = copy.deepcopy(metadata)
        data._excluded = copy.deepcopy(excluded)
        self.endResetModel()
        return True

    def _structural(self, label, operation):
        if self._replaying:
            operation()
            return True
        estimate = (
            int(self.data_model._data.memory_usage(index=True, deep=True).sum()) * 2
            + 8192
        )
        if not self._accept(estimate):
            return False
        from tailor.column_titles import letters

        for column, key in enumerate(self.columnLabels()):
            self._metadata.setdefault(key, {}).setdefault("title", letters(column))
        before = self._snapshot()
        try:
            self._replaying = True
            operation()
        except Exception:
            self._restore(before)
            raise
        finally:
            self._replaying = False
        self._metadata = {
            key: value
            for key, value in self._metadata.items()
            if key in self.data_model._data.columns
        }
        for column, key in enumerate(self.columnLabels()):
            self._metadata.setdefault(key, {}).setdefault("title", letters(column))
        after = self._snapshot()
        size = (
            sum(
                int(state[0].memory_usage(index=True, deep=True).sum())
                for state in (before, after)
            )
            + 8192
        )
        if size > self.HISTORY_BYTES:
            self._restore(before)
            self.editRejected.emit("扩展后的表格超过撤销上限，已保留原始数据。")
            return False
        self._record(
            Edit(
                label, lambda: self._restore(before), lambda: self._restore(after), size
            )
        )
        return True

    def setDataFromArray(self, index, values):
        mixed = any(
            self.column_metadata(c).get("format", "numeric") != "numeric"
            for c in range(
                max(0, index.column()),
                min(self.columnCount(), index.column() + np.asarray(values).shape[1]),
            )
        )
        if mixed:
            return self.set_mixed_block(index, values)
        try:
            values = np.asarray(values, dtype=float)
        except (ValueError, TypeError):
            self.editRejected.emit("数值列不能写入文本，原数据保留。")
            return False
        if values.ndim != 2 or not values.size or not index.isValid():
            return False
        row, col = index.row(), index.column()
        height, width = values.shape
        if row < 0 or col < 0:
            return False
        for column in range(col, min(col + width, self.columnCount())):
            if self.isCalculatedColumn(column):
                self.editRejected.emit("粘贴区域包含计算列，未修改数据。")
                return False
        if row + height > self.rowCount() or col + width > self.columnCount():
            estimate = (
                self.rowCount() * self.columnCount()
                + max(self.rowCount(), row + height)
                * max(self.columnCount(), col + width)
            ) * 8 + 8192
            if not self._accept(estimate):
                return False
            return self._structural(
                "粘贴并扩展表格",
                lambda: QDataModel.setDataFromArray(self, index, values),
            )
        old = self.data_model.get_values(
            row, col, row + height - 1, col + width - 1
        ).copy()
        new = values.copy()
        if not self._accept(old.nbytes + new.nbytes + 512):
            return False

        def apply(block):
            self.data_model.set_values_from_array(row, col, block)
            self._notify_data()

        apply(new)
        self._record(
            Edit(
                "编辑单元格" if values.size == 1 else "粘贴",
                lambda: apply(old),
                lambda: apply(new),
                old.nbytes + new.nbytes + 512,
            )
        )
        return True

    def set_mixed_block(self, index, values):
        values = np.asarray(values, dtype=object)
        if values.ndim != 2 or not values.size or not index.isValid():
            return False
        row, col = index.row(), index.column()
        height, width = values.shape
        converted = []
        try:
            for i in range(width):
                column = col + i
                if column < self.columnCount() and self.isCalculatedColumn(column):
                    raise ValueError("计算列为只读")
                kind = (
                    self.column_metadata(column).get("format", "numeric")
                    if column < self.columnCount()
                    else "numeric"
                )
                block = values[:, i]
                if kind == "numeric":
                    block = np.asarray(
                        [float(v) if str(v).strip() else np.nan for v in block]
                    )
                else:
                    block = np.asarray(
                        ["" if pd.isna(v) else str(v) for v in block], dtype=object
                    )
                    if kind in {"date", "time"}:
                        for v in block:
                            if v:
                                pd.Timestamp(v)
                converted.append((kind, block))
        except (ValueError, TypeError):
            self.editRejected.emit("粘贴内容不符合目标列格式，原数据保留。")
            return False

        def apply():
            if row + height > self.rowCount():
                QDataModel.insertRows(
                    self, self.rowCount(), row + height - self.rowCount()
                )
            if col + width > self.columnCount():
                QDataModel.insertColumns(
                    self, self.columnCount(), col + width - self.columnCount()
                )
            for i, (kind, block) in enumerate(converted):
                key = self.columnLabel(col + i)
                if kind != "numeric":
                    self.data_model._data[key] = self.data_model._data[key].astype(
                        object
                    )
                self.data_model._data.iloc[row : row + height, col + i] = block
                self.data_model.recalculate_columns_from(key)
            self._notify_data()

        return self._structural("粘贴混合格式单元格", apply)

    def clearData(self, selection):
        ranges = list(selection)
        if not ranges:
            return False
        blocks = []
        for block in ranges:
            for column in range(block.left(), block.right() + 1):
                if self.isCalculatedColumn(column):
                    self.editRejected.emit("选区包含计算列，未清空。")
                    return False
            values = self.data_model.get_values(
                block.top(), block.left(), block.bottom(), block.right()
            ).copy()
            blocks.append((block.top(), block.left(), values))
        size = sum(values.nbytes + 512 for _, _, values in blocks)
        if not self._accept(size):
            return False

        def apply(clear):
            for row, col, values in blocks:
                self.data_model.set_values_from_array(
                    row, col, np.full_like(values, np.nan) if clear else values
                )
            self._notify_data()

        apply(True)
        self._record(Edit("清空", lambda: apply(False), lambda: apply(True), size))
        return True

    def append_results(self, columns, title="生成处理结果"):
        """Append a result bundle in one existing structural undo transaction."""
        if not columns:
            return []
        arrays = [np.asarray(c["values"], dtype=float) for c in columns]
        if any(a.ndim != 1 for a in arrays):
            raise ValueError("结果必须是一维数值列。")
        rows = max(self.rowCount(), *(len(a) for a in arrays))
        if not self._accept(rows * (self.columnCount() * 2 + len(arrays)) * 8 + 16384):
            raise ValueError("结果超过撤销内存上限，请分批处理。")
        added = []

        def apply():
            if rows > self.rowCount():
                QDataModel.insertRows(self, self.rowCount(), rows - self.rowCount())
            for spec, values in zip(columns, arrays, strict=True):
                column = self.columnCount()
                QDataModel.insertColumns(self, column, 1)
                key = self.columnLabel(column)
                base = self.data_model.normalize_column_name(spec["name"]) or "Result"
                name, suffix = base, 2
                while name in self.data_model._col_names.values():
                    name = f"{base}_{suffix}"
                    suffix += 1
                self.data_model._col_names[key] = name
                source = spec.get("source", "")
                if spec.get("paired_x") and added:
                    import json

                    info = json.loads(source or "{}")
                    info["result_x"] = added[-1]
                    source = json.dumps(info, ensure_ascii=False)
                self._metadata[key] = {
                    "role": spec.get("role", "Y"),
                    "title": __import__("tailor.column_titles", fromlist=["letters"]).letters(column),
                    "comment": spec["name"],
                    "source": source,
                    "unit": spec.get("unit", ""),
                }
                if len(values):
                    self.data_model.set_values_from_array(
                        0, column, values.reshape(-1, 1)
                    )
                added.append(key)
            self._notify_data()
            self.headerDataChanged.emit(
                QtCore.Qt.Horizontal,
                self.columnCount() - len(columns),
                self.columnCount() - 1,
            )

        if not self._structural(title, apply):
            raise ValueError("结果超过撤销内存上限，原数据已保留。")
        return added

    def replace_results(self, columns, keys, title="重新计算"):
        if len(columns) != len(keys) or any(k not in self.columnLabels() for k in keys):
            raise ValueError("原结果列不完整，请另存为新结果。")
        arrays = [np.asarray(c["values"], dtype=float) for c in columns]

        def apply():
            rows = max(self.rowCount(), *(len(a) for a in arrays))
            if rows > self.rowCount():
                QDataModel.insertRows(self, self.rowCount(), rows - self.rowCount())
            for index, (spec, values, key) in enumerate(
                zip(columns, arrays, keys, strict=True)
            ):
                if self.isCalculatedColumn(list(self.columnLabels()).index(key)):
                    raise ValueError("原结果列已改为计算列，不能覆盖。")
                column = list(self.columnLabels()).index(key)
                output = np.full(self.rowCount(), np.nan)
                output[: len(values)] = values
                self.data_model.set_values_from_array(0, column, output.reshape(-1, 1))
                source = spec.get("source", "")
                if spec.get("paired_x") and index:
                    import json

                    info = json.loads(source)
                    info["result_x"] = keys[index - 1]
                    source = json.dumps(info, ensure_ascii=False)
                self._metadata[key].update(
                    source=source,
                    comment=spec["name"],
                    role=spec.get("role", "Y"),
                    unit=spec.get("unit", self._metadata[key].get("unit", "")),
                )
            self._notify_data()

        if not self._structural(title, apply):
            raise ValueError("超过撤销内存限制，结果未更新。")
        return keys

    def append_column(self, values, name="Result", role="none", source=""):
        values = np.asarray(values, dtype=float)
        if (
            values.ndim != 1
            or len(values) != self.rowCount()
            or role not in {"none", "X", "Y", "XErr", "YErr"}
        ):
            return False
        if not self._accept(self.rowCount() * (2 * self.columnCount() + 1) * 8 + 8192):
            return False

        def apply():
            column = self.columnCount()
            QDataModel.insertColumns(self, column, 1)
            label = self.columnLabel(column)
            base = self.data_model.normalize_column_name(name) or "Result"
            unique, suffix = base, 2
            while unique in self.data_model._col_names.values():
                unique = f"{base}_{suffix}"
                suffix += 1
            self.data_model._col_names[label] = unique
            self._metadata[label] = {"role": role, "source": source}
            self.data_model.set_values_from_array(0, column, values.reshape(-1, 1))
            self._notify_data()
            self.headerDataChanged.emit(QtCore.Qt.Horizontal, column, column)

        return self._structural("生成新列", apply)

    def keep_rows(self, mask, shift_column=None, shift=0.0):
        """Crop all columns together in one existing undo transaction."""
        mask = np.asarray(mask, dtype=bool)
        if mask.shape != (self.rowCount(),) or not mask.any():
            return False
        if shift_column is not None and self.isCalculatedColumn(shift_column):
            self.editRejected.emit("X 为计算列，不能直接归零；请先复制到普通列。")
            return False
        if mask.all() and (shift_column is None or shift == 0):
            return True

        def apply():
            self.beginResetModel()
            try:
                from tailor.exclusions import remap_rows

                remap_rows(self.data_model, np.flatnonzero(mask))
                self.data_model._data = self.data_model._data.loc[mask].reset_index(
                    drop=True
                )
                if shift_column is not None:
                    key = self.columnLabel(shift_column)
                    self.data_model._data[key] = self.data_model._data[key] - shift
                self.data_model.recalculate_all_columns()
            finally:
                self.endResetModel()

        return self._structural(
            "裁切并归零" if shift_column is not None else "裁切范围外数据", apply
        )

    def remove_spans(self, spans, columns=False):
        maximum = self.columnCount() if columns else self.rowCount()
        merged = []
        for first, count in sorted(spans):
            if first < 0 or count < 1 or first + count > maximum:
                return False
            end = first + count
            if merged and first <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((first, end))
        if not merged:
            return False
        operation = QDataModel.removeColumns if columns else QDataModel.removeRows

        def apply():
            for first, end in reversed(merged):
                operation(self, first, end - first)

        return self._structural("删除选中列" if columns else "删除选中行", apply)

    def insertRows(self, row, count, parent=INVALID):
        if (
            parent.isValid()
            or count < 1
            or not 0 <= row <= self.rowCount()
            or not self.columnCount()
        ):
            return False
        if not self._accept(
            (2 * self.rowCount() + count) * self.columnCount() * 8 + 8192
        ):
            return False
        return self._structural(
            "插入行", lambda: QDataModel.insertRows(self, row, count, parent)
        )

    def removeRows(self, row, count, parent=INVALID):
        if parent.isValid() or count < 1 or row < 0 or row + count > self.rowCount():
            return False
        return self._structural(
            "删除行", lambda: QDataModel.removeRows(self, row, count, parent)
        )

    def insertColumns(self, column, count, parent=INVALID):
        if parent.isValid() or count < 1 or not 0 <= column <= self.columnCount():
            return False
        if not self._accept(
            self.rowCount() * (2 * self.columnCount() + count) * 8 + 8192
        ):
            return False
        return self._structural(
            "插入列", lambda: QDataModel.insertColumns(self, column, count, parent)
        )

    def removeColumns(self, column, count, parent=INVALID):
        if (
            parent.isValid()
            or count < 1
            or column < 0
            or column + count > self.columnCount()
        ):
            return False
        return self._structural(
            "删除列", lambda: QDataModel.removeColumns(self, column, count, parent)
        )

    def moveColumn(
        self,
        sourceParent=INVALID,
        sourceColumn=0,
        destinationParent=INVALID,
        destinationChild=0,
    ):
        if (
            sourceParent.isValid()
            or destinationParent.isValid()
            or not 0 <= sourceColumn < self.columnCount()
            or not 0 <= destinationChild <= self.columnCount()
            or destinationChild in (sourceColumn, sourceColumn + 1)
        ):
            return False
        return self._structural(
            "移动列",
            lambda: QDataModel.moveColumn(
                self, sourceParent, sourceColumn, destinationParent, destinationChild
            ),
        )

    def insertCalculatedColumn(self, column, parent=INVALID):
        if parent.isValid() or not 0 <= column <= self.columnCount():
            return False
        return self._structural(
            "添加计算列",
            lambda: QDataModel.insertCalculatedColumn(self, column, parent),
        )

    def updateColumnExpression(self, column, expression):
        if not self.isCalculatedColumn(column):
            return False
        return self._structural(
            "计算表达式",
            lambda: QDataModel.updateColumnExpression(self, column, expression),
        )

"""Column operations over the existing pandas model and transactional history."""

from tailor.compact_controls import CheckButton

import datetime

import numpy as np
import pandas as pd
from PySide6 import QtCore, QtWidgets

from tailor.fold_panel import FoldPanel
from tailor.graph_controls import combo, row


def tool(text, tip, callback):
    button = QtWidgets.QPushButton(tip)
    button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
    button.setText(tip)
    button.setToolTip(tip)
    button.setAccessibleName(tip)
    button.setMinimumSize(30, 28)
    button.clicked.connect(callback)
    return button


class ColumnPreferences(FoldPanel):
    def __init__(self, sheet):
        super().__init__(sheet)
        self.sheet, self.loading = sheet, False
        sheet.column_preferences=self
        self.actions = []
        form = QtWidgets.QGridLayout()
        form.setColumnStretch(1,1)
        def label(text):
            widget=QtWidgets.QLabel(text)
            widget.setProperty('fieldLabel',True)
            return widget
        def add_row(title,widget):
            index=form.count()//2
            form.addWidget(label(title),index,0)
            form.addWidget(widget,index,1)
        self.current = QtWidgets.QLabel("请选择列")
        self.current.setWordWrap(True)
        self.current.setMinimumWidth(0)
        self.current.setSizePolicy(QtWidgets.QSizePolicy.Ignored,QtWidgets.QSizePolicy.Preferred)
        add_row("选中列", self.current)

        def buttons(title, items, add=True):
            widgets = [
                tool(
                    symbol,
                    {
                        "左侧插入列": "左侧",
                        "右侧插入列": "右侧",
                        "填充行号": "行号",
                        "填充随机数": "随机数",
                        "填充时间": "时间",
                        "升序（整行联动）": "升序",
                        "降序（整行联动）": "降序",
                        "移到最前": "最前",
                        "向左移动": "向左",
                        "向右移动": "向右",
                        "移到最后": "最后",
                    }.get(title, title),
                    action,
                )
                for symbol, title, action in items
            ]
            self.actions.extend(widgets)
            if add:add_row(title, row(*widgets))
            return widgets

        buttons(
            "填充",
            [
                ("1…", "填充行号", lambda: self.fill("rows")),
                ("⚄", "填充随机数", lambda: self.fill("random")),
                ("◷", "填充时间", lambda: self.fill("time")),
            ],
        )
        buttons(
            "排序",
            [
                ("↑", "升序（整行联动）", lambda: self.sort(True)),
                ("↓", "降序（整行联动）", lambda: self.sort(False)),
            ],
        )
        moving=buttons(
            "移动",
            [
                ("⇤", "移到最前", lambda: self.move("first")),
                ("←", "向左移动", lambda: self.move("left")),
                ("→", "向右移动", lambda: self.move("right")),
                ("⇥", "移到最后", lambda: self.move("last")),
            ],add=False,
        )
        from tailor.plot_types import icon
        self.hide_button = __import__("tailor.compact_controls",fromlist=["SplitHideButton"]).SplitHideButton()
        self.hide_button.setText("隐藏列")
        self.hidden_menu = QtWidgets.QMenu(self.hide_button)
        self.hidden_menu.aboutToShow.connect(self.unhide_menu)
        self.hide_button.setMenu(self.hidden_menu)
        self.hide_button.clicked.connect(self.hide_columns)
        self.delete_button = tool("", "删除列", self.delete_columns)
        self.delete_button.setIcon(icon("trash-2", self, "#d34b48"))
        self.delete_button.setProperty("intent", "destructive")
        from tailor.element_button_group import ElementButtons
        self.column_actions=ElementButtons(sheet,'columns',add=self.append_column)
        self.column_actions.buttons['add'].setToolTip('在表格最右端追加一列')
        left=tool('','左侧',lambda:self.insert(False));right=tool('','右侧',lambda:self.insert(True))
        self.actions.extend([left,right])
        controls=QtWidgets.QWidget()
        grid=QtWidgets.QGridLayout(controls)
        grid.setContentsMargins(0,0,0,0);grid.setSpacing(7)
        for index,button in enumerate(moving):
            grid.addWidget(button,0,index)
            grid.setColumnStretch(index,1)
        grid.addWidget(left,1,0);grid.addWidget(right,1,1)
        grid.addWidget(self.column_actions,1,2,1,2)
        index=form.count()//2
        form.addWidget(label('移动'),index,0)
        form.addWidget(label('插入'),index+1,0)
        form.setRowMinimumHeight(index,30);form.setRowMinimumHeight(index+1,30)
        form.addWidget(controls,index,1,2,1)
        self.hide_button.setParent(self);self.delete_button.setParent(self)
        self.hide_button.hide();self.delete_button.hide()
        self.add_section("列操作", form, True)
        form = QtWidgets.QFormLayout()
        self.kind = combo(
            [("数值", "numeric"), ("文本", "text"), ("时间", "time"), ("日期", "date")]
        )
        self.notation = combo(
            [
                ("十进制 · 1000", "decimal"),
                ("千位分隔 · 1,000", "grouped"),
                ("科学计数 · 1.00e+03", "scientific"),
                ("科学计数 · 1.00×10³", "power"),
            ]
        )
        self.decimals = QtWidgets.QSpinBox()
        self.decimals.setRange(0, 15)
        self.decimals.setProperty("sliderUnit","位")
        self.decimals.setValue(6)
        form.addRow("格式", self.kind)
        form.addRow("显示", self.notation)
        form.addRow("小数位数", row(self.decimals))
        form.addRow(
            "对齐方式",
            row(
                *[
                    tool(
                        symbol,
                        tip,
                        lambda checked=False, a=value: self.set_alignment(a),
                    )
                    for symbol, tip, value in [
                        ("", "左", "left"),
                        ("", "右", "right"),
                        ("", "上", "top"),
                        ("", "下", "bottom"),
                        ("", "居中", "center"),
                    ]
                ]
            ),
        )
        self.add_section("单元格属性", form, True)
        self.kind.activated.connect(self.apply_format)
        self.notation.activated.connect(self.apply_format)
        self.decimals.valueChanged.connect(self.apply_format)
        sheet.selection.selectionChanged.connect(self.sync)
        sheet.model.modelReset.connect(self.sync_hidden)
        sheet.model.headerDataChanged.connect(self.sync_hidden)
        self.sync()

    def delete_columns(self):
        columns = self.columns()
        if not columns:
            return
        # Use the existing dependency guard and structural undo; select whole columns.
        select = self.sheet.selection
        proxy=self.sheet.ui.data_view.model()
        blocks=QtCore.QItemSelection()
        for c in columns:
            blocks.select(proxy.index(0,c),proxy.index(proxy.rowCount()-1,c))
        select.select(blocks,QtCore.QItemSelectionModel.ClearAndSelect)
        self.sheet.main_window.ui.tabWidget.setCurrentWidget(self.sheet)
        self.sheet.main_window.remove_selected_columns()

    def columns(self):
        return sorted(
            {
                c
                for b in self.sheet.selection.selection()
                for c in range(b.left(), b.right() + 1)
            }
        )

    def sync(self, *args):
        columns = self.columns()
        self.loading = True
        self.current.setText(
            "、".join(__import__("tailor.column_titles", fromlist=["display"]).display(self.sheet.model, self.sheet.model.columnLabel(c)) for c in columns) or "请选择列"
        )
        for button in self.actions:
            button.setEnabled(bool(columns))
        for widget in (self.kind, self.notation, self.decimals):
            widget.setEnabled(bool(columns))
        if columns:
            metas=[self.sheet.model.column_metadata(c) for c in columns]
            meta=metas[0]
            from tailor.choice_state import show_setting
            show_setting(self.kind,meta.get('format','numeric'),mixed=len({m.get('format','numeric') for m in metas})>1)
            show_setting(self.notation,meta.get('notation','decimal'),mixed=len({m.get('notation','decimal') for m in metas})>1)
            self.decimals.setValue(int(meta.get("decimals", "6")))
        else:
            from tailor.choice_state import show_setting
            show_setting(self.kind,selected=False)
            show_setting(self.notation,selected=False)
        self.loading = False

    def change(self, title, fn):
        model = self.sheet.model

        def apply():
            model.beginResetModel()
            try:
                fn()
            finally:
                model.endResetModel()

        return model._structural(title, apply)

    def append_column(self):
        self.sheet.model.insertColumns(self.sheet.model.columnCount(),1)

    def insert(self, right):
        columns = self.columns()
        if columns:
            self.sheet.model.insertColumns(
                (max(columns) + 1) if right else min(columns), 1
            )

    def sort(self, ascending):
        columns = self.columns()
        if not columns:
            return
        model = self.sheet.model
        keys = [model.columnLabel(c) for c in columns]

        def apply():
            frame = model.data_model._data
            # Per-key temporary sort values; raw cells and all linked rows stay together.
            order = pd.DataFrame(
                {
                    k: (
                        pd.to_numeric(frame[k], errors="coerce")
                        if model.column_metadata(c).get("format", "numeric")
                        == "numeric"
                        else frame[k].astype(str)
                    )
                    for c, k in zip(columns, keys)
                }
            )
            indexes = order.sort_values(
                keys, ascending=ascending, kind="mergesort", na_position="last"
            ).index
            from tailor.exclusions import remap_rows
            remap_rows(model.data_model, indexes)
            model.data_model._data = frame.loc[indexes].reset_index(drop=True)
            model.data_model.recalculate_all_columns()

        self.change("整行联动排序", apply)

    def fill(self, kind):
        columns = self.columns()
        if not columns:
            return
        model = self.sheet.model
        if any(model.isCalculatedColumn(c) for c in columns):
            model.editRejected.emit("计算列为只读，未填充。")
            return
        options = {}
        if kind in {"random", "time"}:
            d = QtWidgets.QDialog(self)
            d.setWindowTitle("随机数填充" if kind == "random" else "时间填充")
            f = QtWidgets.QFormLayout(d)
            if kind == "random":
                low, high = QtWidgets.QDoubleSpinBox(), QtWidgets.QDoubleSpinBox()
                for b in (low, high):
                    b.setRange(-1e12, 1e12)
                    b.setDecimals(6)
                high.setValue(1)
                integer = CheckButton("整数")
                f.addRow("最小值", low)
                f.addRow("最大值", high)
                f.addRow(integer)
            else:
                start = QtWidgets.QDateTimeEdit(QtCore.QDateTime.currentDateTime())
                start.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
                step = QtWidgets.QDoubleSpinBox()
                step.setRange(0.001, 86400000)
                step.setValue(1)
                step.setDecimals(3)
                f.addRow("起始时间", start)
                f.addRow("步长（秒）", step)
            buttons = QtWidgets.QDialogButtonBox(
                QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
            )
            buttons.accepted.connect(d.accept)
            buttons.rejected.connect(d.reject)
            f.addRow(buttons)
            if d.exec() != QtWidgets.QDialog.DialogCode.Accepted:
                return
            if kind == "random":
                if low.value() > high.value():
                    model.editRejected.emit('最小值不能大于最大值。')
                    return
                if integer.isChecked() and np.ceil(low.value()) > np.floor(high.value()):
                    model.editRejected.emit('此范围内没有可填充的整数。')
                    return
                options = {
                    "low": low.value(),
                    "high": high.value(),
                    "integer": integer.isChecked(),
                }
            else:
                options = {"start": start.dateTime().toPython(), "step": step.value()}
        blocks = list(self.sheet.selection.selection())

        def apply():
            for c in columns:
                key = model.columnLabel(c)
                intervals = [
                    (b.top(), b.bottom() + 1)
                    for b in blocks
                    if b.left() <= c <= b.right()
                ]
                for begin, end in intervals or [(0, model.rowCount())]:
                    count = end - begin
                    if kind == "rows":
                        values = np.arange(begin + 1, end + 1, dtype=float)
                    elif kind == "random":
                        rng = np.random.default_rng()
                        values = (
                            rng.integers(
                                int(np.ceil(options["low"])),
                                int(np.floor(options["high"])) + 1,
                                count,
                            )
                            if options["integer"]
                            else rng.uniform(options["low"], options["high"], count)
                        )
                        if not options['integer']:
                            # Preserve every unselected value, including text
                            # and integers too large for exact float storage.
                            column = model.data_model._data[key]
                            model.data_model._data[key] = column.astype(float if pd.api.types.is_float_dtype(column.dtype) else object)
                    else:
                        values = [
                            (
                                options["start"]
                                + datetime.timedelta(seconds=i * options["step"])
                            ).isoformat(sep=" ")
                            for i in range(count)
                        ]
                        model.data_model._data[key] = model.data_model._data[
                            key
                        ].astype(object)
                        model._metadata.setdefault(key, {})["format"] = "time"
                    model.data_model._data.iloc[begin:end, c] = values
                model.data_model.recalculate_columns_from(key)

        self.change("填充数据", apply)

    def hide_columns(self):
        self.sheet.model.set_columns_metadata(self.columns(),title='隐藏所选列',hidden='true')
        self.sync_hidden()

    def sync_hidden(self, *args):
        view = self.sheet.ui.data_view
        for c in range(self.sheet.model.columnCount()):
            view.setColumnHidden(
                c, self.sheet.model.column_metadata(c).get("hidden") == "true"
            )
        view.horizontalHeader().sync()
        view.horizontalHeader().viewport().update()
        self.sync()

    def unhide_menu(self):
        self.hidden_menu.clear()
        hidden = [
            c
            for c in range(self.sheet.model.columnCount())
            if self.sheet.model.column_metadata(c).get("hidden") == "true"
        ]
        for c in hidden:
            self.hidden_menu.addAction(
                self.sheet.model.columnName(c),
                lambda checked=False, c=c: self.sheet.model.set_column_metadata(
                    c, hidden="false"
                ),
            )
        self.hidden_menu.addSeparator()
        self.hidden_menu.addAction(
            "全部取消隐藏",
            lambda: [
                self.sheet.model.set_column_metadata(c, hidden="false") for c in hidden
            ],
        )

    def move(self, direction):
        columns = self.columns()
        if not columns:
            return
        model = self.sheet.model
        keys = list(model.columnLabels())
        chosen = [keys[c] for c in columns]
        rest = [k for k in keys if k not in chosen]
        pos = {
            "first": 0,
            "last": len(rest),
            "left": max(0, min(columns) - 1),
            "right": min(len(rest), min(columns) + 1),
        }[direction]
        order = rest[:pos] + chosen + rest[pos:]
        self.change(
            "移动列",
            lambda: setattr(
                model.data_model, "_data", model.data_model._data.loc[:, order]
            ),
        )

    def set_alignment(self, value):
        model = self.sheet.model
        columns = self.columns()
        if not columns:
            return
        before = {
            c: {
                key: model.column_metadata(c).get(key)
                for key in ("halign", "valign")
            }
            for c in columns
        }
        for values in before.values():
            values["halign"] = values["halign"] or "right"
            values["valign"] = values["valign"] or "center"
        if value == "center":
            changes = {c: {"halign": "center", "valign": "center"} for c in columns}
        elif value in {"left", "right"}:
            changes = {c: {"halign": value} for c in columns}
        elif value in {"top", "bottom"}:
            changes = {c: {"valign": value} for c in columns}
        else:
            raise ValueError(f"Unknown cell alignment: {value}")

        after = {
            c: {**before[c], **updates}
            for c, updates in changes.items()
        }
        if before == after:
            return

        def apply(state):
            for column, values in state.items():
                model.set_column_metadata(
                    column,
                    _record_edit=False,
                    **values,
                )

        # One multi-column alignment action is one entry in the existing sheet
        # history, so a single Undo restores both axes on every selected column.
        apply(after)
        from tailor.spreadsheet_model import Edit

        model._record(
            Edit(
                "设置单元格对齐",
                lambda: apply(before),
                lambda: apply(after),
                256 + 64 * len(columns),
            )
        )
        self.sheet.model._notify_data()

    def apply_format(self, *args):
        if self.loading:
            return
        from tailor.choice_state import actionable_setting
        sender=self.sender()
        if isinstance(sender,QtWidgets.QComboBox) and not actionable_setting(sender.currentData()):return
        values={'decimals':str(self.decimals.value())}
        for key,box in [('format',self.kind),('notation',self.notation)]:
            if actionable_setting(box.currentData()):values[key]=box.currentData()
        if sender is self.kind:values={'format':self.kind.currentData()}
        elif sender is self.notation:values={'notation':self.notation.currentData()}
        elif sender is self.decimals:values={'decimals':str(self.decimals.value())}
        for c in self.columns():self.sheet.model.set_column_metadata(c,**values)
        self.sheet.model._notify_data()

    def add_context_menu(self, menu):
        menu._column_submenus = []
        enabled = bool(self.columns())

        def action(parent, title, callback):
            a = parent.addAction(title)
            a.setEnabled(enabled)
            a.triggered.connect(callback)

        for name, items in (
            (
                "插入列",
                [
                    ("左侧", lambda: self.insert(False)),
                    ("右侧", lambda: self.insert(True)),
                ],
            ),
            (
                "填充",
                [
                    ("行号", lambda: self.fill("rows")),
                    ("随机数…", lambda: self.fill("random")),
                    ("时间…", lambda: self.fill("time")),
                ],
            ),
            (
                "列排序",
                [("升序", lambda: self.sort(True)), ("降序", lambda: self.sort(False))],
            ),
            (
                "移动列",
                [
                    ("移到最前", lambda: self.move("first")),
                    ("向左移动", lambda: self.move("left")),
                    ("向右移动", lambda: self.move("right")),
                    ("移到最后", lambda: self.move("last")),
                ],
            ),
            (
                "单元格格式",
                [
                    (
                        label,
                        lambda checked=False, k=key: self.context_format("format", k),
                    )
                    for label, key in (
                        ("数值", "numeric"),
                        ("文本", "text"),
                        ("时间", "time"),
                        ("日期", "date"),
                    )
                ],
            ),
            (
                "数字显示",
                [
                    (
                        label,
                        lambda checked=False, k=key: self.context_format("notation", k),
                    )
                    for label, key in (
                        ("十进制", "decimal"),
                        ("千位分隔", "grouped"),
                        ("科学计数 e", "scientific"),
                        ("科学计数 ×10ⁿ", "power"),
                    )
                ],
            ),
            (
                "对齐方式",
                [
                    (label, lambda checked=False, k=key: self.set_alignment(k))
                    for label, key in (
                        ("左对齐", "left"),
                        ("右对齐", "right"),
                        ("顶部", "top"),
                        ("底部", "bottom"),
                    )
                ],
            ),
        ):
            submenu = menu.addMenu(name)
            menu._column_submenus.append(submenu)
            for title, callback in items:
                action(submenu, title, callback)
        action(menu, "小数位数…", self.context_decimals)
        from tailor.plot_types import icon
        delete = menu.addAction(icon("trash-2", self, "#d34b48"), "删除列", self.delete_columns)
        delete.setEnabled(enabled)
        action(menu, "隐藏列", self.hide_columns)
        unhide = menu.addMenu("取消隐藏列")
        menu._column_submenus.append(unhide)
        for c in range(self.sheet.model.columnCount()):
            if self.sheet.model.column_metadata(c).get("hidden") == "true":
                unhide.addAction(
                    __import__("tailor.column_titles",fromlist=["display"]).display(self.sheet.model,self.sheet.model.columnLabel(c)),
                    lambda c=c: self.sheet.model.set_column_metadata(c, hidden="false"),
                )
        unhide.addAction("全部取消隐藏", self.unhide_all)

    def unhide_all(self):
        for c in range(self.sheet.model.columnCount()):
            if self.sheet.model.column_metadata(c).get("hidden") == "true":
                self.sheet.model.set_column_metadata(c, hidden="false")

    def context_format(self, key, value):
        for c in self.columns():
            self.sheet.model.set_column_metadata(c, **{key: value})
        self.sync()

    def context_decimals(self):
        value, ok = QtWidgets.QInputDialog.getInt(
            self, "小数位数", "小数位数", self.decimals.value(), 0, 15
        )
        if ok:
            self.context_format("decimals", str(value))

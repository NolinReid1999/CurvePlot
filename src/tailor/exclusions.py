"""Cell masks over Tailor source rows; values never change when a mask changes."""

import copy

import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets


def rows_for(data, keys):
    excluded = getattr(data, "_excluded", {})
    rows = set()
    for key in keys:
        rows.update(excluded.get(key, ()))
    return rows


def remap_rows(data, order):
    inverse = {int(old): new for new, old in enumerate(order)}
    data._excluded = {
        key: {inverse[r] for r in values if r in inverse}
        for key, values in getattr(data, "_excluded", {}).items()
        if key in data._data.columns
    }


def set_cells(model, cells, active):
    from tailor.spreadsheet_model import Edit

    data = model.data_model
    before = copy.deepcopy(getattr(data, "_excluded", {}))
    after = copy.deepcopy(before)
    for key, rows in cells.items():
        if key not in data._data.columns:
            continue
        selected = {int(r) for r in rows if 0 <= r < len(data._data)}
        values = after.setdefault(key, set())
        values.update(selected) if active else values.difference_update(selected)
    after = {key: rows for key, rows in after.items() if rows}
    if after == before:
        return False
    size = sum(len(v) for state in (before, after) for v in state.values()) * 32 + 1024
    if not model._accept(size):
        return False

    def apply(value):
        data._excluded = copy.deepcopy(value)
        model._notify_data()

    apply(after)
    model._record(
        Edit(
            "排除数据" if active else "恢复数据",
            lambda: apply(before),
            lambda: apply(after),
            size,
        )
    )
    return True


def table_cells(sheet):
    keys = list(sheet.model.columnLabels())
    cells = {}
    for block in sheet.ui.data_view.selectionModel().selection():
        for column in range(block.left(), block.right() + 1):
            if column < len(keys):
                cells.setdefault(keys[column], set()).update(
                    range(block.top(), block.bottom() + 1)
                )
    return cells


def selected_points(inspector, active):
    if inspector.selected_frame is None or getattr(inspector, "sampled_curve", False):
        return
    source = (
        inspector.plot
        if hasattr(inspector.plot, "data_sheet")
        else inspector.selected[0]
    )
    set_cells(
        source.data_sheet.model,
        {source.model.y_col: inspector.selected_frame.index},
        active,
    )


def selection_buttons(inspector):
    from tailor.graph_controls import row

    buttons = []
    for title, active in [("排除所选点", True), ("恢复所选点", False)]:
        button = QtWidgets.QPushButton(title)
        button.clicked.connect(
            lambda checked=False, a=active: selected_points(inspector, a)
        )
        button.setEnabled(False)
        buttons.append(button)
    inspector.exclusion_buttons = buttons
    return row(*buttons)


class ExcludedPoints(QtCore.QObject):
    def __init__(self, plot):
        super().__init__(plot)
        self.plot = plot
        self.items = []
        if hasattr(plot, "data_refreshed"):
            plot.data_refreshed.connect(self.refresh)
        self.refresh()

    def refresh(self, *args):
        from tailor.graph_presentation import display

        for box, item in self.items:
            box.removeItem(item)
        self.items = []
        plot = self.plot
        sources = plot.model._plots if plot.presentation.multi else [plot]
        for source in sources:
            info = plot.model.get_plot_info(source) if plot.presentation.multi else None
            if info and not info.visible:
                continue
            excluded = rows_for(
                source.model.data_model, [source.model.x_col, source.model.y_col]
            )
            if not excluded:
                continue
            frame = source.model._get_data_as_dataframe()
            frame = frame.loc[frame.index.isin(excluded)]
            box = (
                plot.presentation.box_for(info)
                if info
                else plot.ui.plot_widget.getViewBox()
            )
            xkey = "top" if info and info.x_axis == "top" else "x"
            ykey = "right" if info and info.axis == "right" else "y"
            item = pg.ScatterPlotItem(
                display(frame.x, plot.presentation.axes[xkey]),
                display(frame.y, plot.presentation.axes[ykey]),
                symbol="x",
                size=12,
                pen=pg.mkPen("#d47526", width=2),
            )
            item.setZValue(95)
            box.addItem(item, ignoreBounds=True)
            self.items.append((box, item))

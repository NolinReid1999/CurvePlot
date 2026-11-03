"""Source-row selection for Tailor overlays, in the owning Y view coordinates."""

import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

from tailor.compact_controls import point_selection_grid, toggle_button
from tailor.point_inspector import PointInspector


class OverlayInspector(QtWidgets.QWidget):
    def __init__(self, plot):
        super().__init__()
        self.plot, self.selected = plot, None
        self.marker = pg.ScatterPlotItem(
            size=17, pen=pg.mkPen("#2878cc", width=2), brush=pg.mkBrush(None)
        )
        self.marker.setZValue(101)
        self.highlight = pg.ScatterPlotItem(
            size=7, pen=None, brush=pg.mkBrush("#2878cc")
        )
        self.highlight.setZValue(102)
        self.marker_box = None
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.enabled = toggle_button("选择数据点")
        self.enabled.hide()
        self.single = toggle_button("选择单个数据点")
        self.continuous = toggle_button("选择连续数据点")
        self.mode_group = QtWidgets.QButtonGroup(self)
        self.mode_group.setExclusive(False)
        self.mode_group.addButton(self.single)
        self.mode_group.addButton(self.continuous)
        self.single.toggled.connect(self.sync_mode)
        self.continuous.toggled.connect(self.sync_mode)
        self.enabled.toggled.connect(self.enable_mode)
        self.start_row = None
        self.selected_frame = None
        self.selected_coordinates = None
        self.details = QtWidgets.QLabel("点击曲线附近；数值和行号始终来自源工作表。")
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.locate = QtWidgets.QPushButton("定位到原工作表")
        self.copy = QtWidgets.QPushButton("复制坐标")
        self.locate.clicked.connect(self.locate_source)
        self.copy.clicked.connect(self.copy_coordinates)
        self.enabled.toggled.connect(self.invalidate)
        layout.addWidget(point_selection_grid(self.single, self.continuous, self.locate, self.copy,self.details))
        from tailor.exclusions import selection_buttons

        layout.addWidget(selection_buttons(self))
        plot.ui.plot_widget.scene().sigMouseClicked.connect(self.clicked)
        self.invalidate()

    def sync_mode(self, *args):
        PointInspector.sync_mode(self)

    def enable_mode(self, active):
        PointInspector.enable_mode(self, active)

    def invalidate(self, *args):
        from tailor.point_inspector import clear_point_feedback
        clear_point_feedback(self)
        self.details.clear()
        self.details.hide()
        self.start_row = None
        self.selected_frame = None
        self.selected_coordinates = None
        self.selected = None
        self.marker.setData([], [])
        self.highlight.setData([], [])
        self.locate.setEnabled(False)
        self.copy.setEnabled(False)

    def clicked(self, event):
        from tailor.point_inspector import point_active, select_scene_point
        if point_active(self.plot):
            select_scene_point(self, event)

    def locate_source(self):
        if self.selected:
            source, index, _, _ = self.selected
            sheet = source.data_sheet
            self.plot.main_window.ui.tabWidget.setCurrentWidget(sheet)
            sheet.go_to_row(index)
            column = list(sheet.model.columnLabels()).index(source.model.y_col)
            sheet.ui.data_view.setCurrentIndex(sheet.page_model.index(index, column))
            if self.selected_frame is not None:
                selection = QtCore.QItemSelection(
                    sheet.page_model.index(index, column),
                    sheet.page_model.index(
                        int(self.selected_frame.index.max()), column
                    ),
                )
                sheet.ui.data_view.selectionModel().select(
                    selection, QtCore.QItemSelectionModel.ClearAndSelect
                )

    def copy_coordinates(self):
        PointInspector.copy_coordinates(self)

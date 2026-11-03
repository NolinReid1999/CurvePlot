from PySide6 import QtWidgets

from tailor.data_sheet import DataSheet
from tailor.plot_tab import PlotTab
from tailor.ui_data_source_dialog import Ui_DataSourceDialog


class DataSourceDialog(QtWidgets.QDialog):
    def __init__(
        self, parent: QtWidgets.QWidget, plot: PlotTab, data_sheets: list[DataSheet]
    ) -> None:
        super().__init__(parent=parent)
        self.ui = Ui_DataSourceDialog()
        self.ui.setupUi(self)

        self.plot = plot
        self.data_sheets = data_sheets
        self.ui.data_source_box.addItems([s.name for s in data_sheets])
        self.ui.data_source_box.setCurrentIndex(data_sheets.index(plot.data_sheet))
        self.update_vars()

        self.ui.data_source_box.currentIndexChanged.connect(self.update_vars)

    def update_vars(self) -> None:
        data_sheet = self.data_sheets[self.ui.data_source_box.currentIndex()]
        from tailor.choice_catalog import visible_columns
        from tailor.column_titles import display
        keys=visible_columns(data_sheet.model)
        for var in ["x", "y", "x_err", "y_err"]:
            box: QtWidgets.QComboBox = getattr(self.ui, f"{var}_box")
            box.clear();box.addItem('—',None)
            for key in keys:
                box.addItem(display(data_sheet.model,key),data_sheet.model.data_model.get_column_name(key))
            try:
                label=getattr(self.plot.model,f'{var}_col')
                name=self.plot.model.data_model.get_column_name(label)
            except KeyError:
                continue
            box.setCurrentIndex(max(0,box.findData(name)))

    def selected_name(self,var):
        # The UI displays letters and user captions; source changes still use
        # the original DataModel column name expected by Tailor's API.
        return getattr(self.ui,f'{var}_box').currentData() or ''

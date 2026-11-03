"""Bounded spreadsheet view over the complete source model, without data copies."""

from PySide6 import QtCore

INVALID_INDEX = QtCore.QModelIndex()


class PagedTable(QtCore.QAbstractProxyModel):
    PAGE_SIZE = 2000

    def __init__(self, source, parent=None):
        super().__init__(parent)
        self.offset = 0
        self.setSourceModel(source)
        for signal in (
            source.modelReset,
            source.rowsInserted,
            source.rowsRemoved,
            source.columnsInserted,
            source.columnsRemoved,
            source.columnsMoved,
            source.layoutChanged,
        ):
            signal.connect(self.refresh)
        source.dataChanged.connect(self.changed)
        source.headerDataChanged.connect(self.headerDataChanged)

    def refresh(self, *args):
        self.beginResetModel()
        total = self.sourceModel().rowCount()
        self.offset = min(
            self.offset, max(0, (total - 1) // self.PAGE_SIZE * self.PAGE_SIZE)
        )
        self.endResetModel()

    def show_row(self, row):
        self.beginResetModel()
        self.offset = max(0, row // self.PAGE_SIZE * self.PAGE_SIZE)
        self.endResetModel()

    def changed(self, *args):
        if self.rowCount() and self.columnCount():
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(self.rowCount() - 1, self.columnCount() - 1),
            )

    def rowCount(self, parent=INVALID_INDEX):
        return (
            0
            if parent.isValid()
            else max(
                0, min(self.PAGE_SIZE, self.sourceModel().rowCount() - self.offset)
            )
        )

    def columnCount(self, parent=INVALID_INDEX):
        return 0 if parent.isValid() else self.sourceModel().columnCount()

    def index(self, row, column, parent=INVALID_INDEX):
        if (
            not parent.isValid()
            and 0 <= row < self.rowCount()
            and 0 <= column < self.columnCount()
        ):
            return self.createIndex(row, column)
        return QtCore.QModelIndex()

    def parent(self, index):
        return QtCore.QModelIndex()

    def mapToSource(self, index):
        return (
            self.sourceModel().index(index.row() + self.offset, index.column())
            if index.isValid()
            else QtCore.QModelIndex()
        )

    def mapFromSource(self, index):
        return (
            self.index(index.row() - self.offset, index.column())
            if index.isValid()
            else QtCore.QModelIndex()
        )

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if orientation == QtCore.Qt.Vertical:
            section += self.offset
        return self.sourceModel().headerData(section, orientation, role)

    def mapSelectionToSource(self, selection):
        result = QtCore.QItemSelection()
        for block in selection:
            result.select(
                self.mapToSource(block.topLeft()), self.mapToSource(block.bottomRight())
            )
        return result

    def mapSelectionFromSource(self, selection):
        result = QtCore.QItemSelection()
        for block in selection:
            first = max(block.top(), self.offset)
            last = min(block.bottom(), self.offset + self.rowCount() - 1)
            if first <= last:
                result.select(
                    self.index(first - self.offset, block.left()),
                    self.index(last - self.offset, block.right()),
                )
        return result

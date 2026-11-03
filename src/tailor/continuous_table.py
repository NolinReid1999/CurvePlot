"""Continuous virtual table with range-based selection and bounded header painting."""

import weakref

from PySide6 import QtCore, QtGui, QtWidgets


class ContinuousTable(QtCore.QIdentityProxyModel):
    """Expose all source rows; QTableView requests only visible cell values."""

    offset = 0  # Compatibility for source-coordinate helpers; never a page offset.

    def show_row(self, row):
        """No model reset is needed to scroll to a source row."""

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
            result.select(
                self.mapFromSource(block.topLeft()),
                self.mapFromSource(block.bottomRight()),
            )
        return result


class FastHeader(QtWidgets.QHeaderView):
    """Avoid Qt's full-column flag scan when painting selected header sections."""

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.setHighlightSections(False)
        self.setSectionsClickable(True)

    def paintSection(self, painter, rect, section):
        # initStyleOptionForIndex/paintSection can call isColumnSelected(),
        # which walks every row even when only a header needs repainting.
        option = QtWidgets.QStyleOptionHeader()
        self.initStyleOption(option)
        option.rect = rect
        option.section = section
        option.orientation = self.orientation()
        option.textAlignment = QtCore.Qt.AlignCenter
        text = str(
            self.model().headerData(section, self.orientation(), QtCore.Qt.DisplayRole)
            or ""
        )
        option.text = self.fontMetrics().elidedText(
            text, QtCore.Qt.ElideRight, max(0, rect.width() - 12)
        )
        painter.save()
        self.style().drawControl(QtWidgets.QStyle.CE_Header, option, painter, self)
        painter.restore()
        selection = self.selectionModel()
        if selection is None:
            return
        horizontal = self.orientation() == QtCore.Qt.Horizontal
        for block in selection.selection():
            first, last = (
                (block.left(), block.right())
                if horizontal
                else (block.top(), block.bottom())
            )
            if first <= section <= last:
                painter.save()
                color = self.palette().color(QtGui.QPalette.Highlight)
                stripe = QtCore.QRect(rect.left(), rect.bottom() - 2, rect.width(), 3)
                painter.fillRect(stripe, color)
                painter.restore()
                break


class VirtualTableAccessibility(QtWidgets.QAccessibleWidget):
    """Expose keyboard focus and a current-cell summary, never millions of AX children.

    macOS eagerly constructs native children for a Qt table notification. The
    full data grid remains in the model; cell-by-cell screen-reader navigation
    needs a separate virtual accessibility implementation in a later stage.
    """

    def __init__(self, view):
        super().__init__(view, QtGui.QAccessible.Pane, "工作表数据")
        self._view = weakref.ref(view)

    def childCount(self):
        return 0

    def child(self, index):
        return None

    def childAt(self, x, y):
        return None

    def indexOfChild(self, child):
        return -1

    def text(self, kind):
        view = self._view()
        if (
            kind in (QtGui.QAccessible.Description, QtGui.QAccessible.Value)
            and view is not None
        ):
            model = view.model()
            if model is not None:
                index = view.currentIndex()
                count = sum(
                    block.width() * block.height()
                    for block in view.selectionModel().selection()
                )
                value = model.data(index) if index.isValid() else ""
                return (
                    f"{model.rowCount():,} 行 × {model.columnCount()} 列；"
                    f"当前第 {index.row() + 1} 行，第 {index.column() + 1} 列，值 {value}；"
                    f"选中 {count:,} 个单元格。方向键移动，F2 编辑。"
                )
        return super().text(kind)


def table_accessibility_factory(class_name, obj):
    if isinstance(obj, ContinuousTableView):
        interface = VirtualTableAccessibility(obj)
        obj._virtual_accessibility = interface
        return interface
    return None


class ContinuousTableView(QtWidgets.QTableView):
    """Keep bulk selection notifications bounded with accessibility enabled.

    Qt 6.9 QTableView expands both selection deltas just to obtain their first
    cell for accessibility. A range notification avoids enumerating all source
    rows; the selection model remains intact for navigation and data operations.
    """

    def selectionChanged(self, selected, deselected):
        QtWidgets.QAbstractItemView.selectionChanged(self, selected, deselected)
        if QtGui.QAccessible.isActive():
            event = QtGui.QAccessibleEvent(self, QtGui.QAccessible.SelectionWithin)
            QtGui.QAccessible.updateAccessibility(event)
        self.horizontalHeader().viewport().update()
        self.verticalHeader().viewport().update()

    def currentChanged(self, current, previous):
        # QTableView's currentChanged also emits a flattened virtual child ID.
        # Our accessible pane reports the source coordinates on the root instead.
        QtWidgets.QAbstractItemView.currentChanged(self, current, previous)
        if QtGui.QAccessible.isActive():
            kind = (
                QtGui.QAccessible.Focus
                if self.hasFocus()
                else QtGui.QAccessible.DescriptionChanged
            )
            QtGui.QAccessible.updateAccessibility(QtGui.QAccessibleEvent(self, kind))


# Register only our table type; other widgets retain Qt's normal accessibility.
QtGui.QAccessible.installFactory(table_accessibility_factory)

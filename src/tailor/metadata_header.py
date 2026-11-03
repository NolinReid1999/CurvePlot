"""Fixed role/name editors, bounded to visible columns; no synthetic data rows."""

from PySide6 import QtCore, QtGui, QtWidgets

from tailor.continuous_table import FastHeader


class MetadataHeader(FastHeader):
    ROLES = (
        ("—", "none"),
        ("X", "X"),
        ("Y", "Y"),
        ("X误差", "XErr"),
        ("Y误差", "YErr"),
    )

    def __init__(self, sheet):
        super().__init__(QtCore.Qt.Horizontal, sheet.ui.data_view)
        self.sheet = sheet
        self.editors = {}
        self._visible_editor_keys = set()
        self._sync_timer = QtCore.QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.setInterval(16)
        self._sync_timer.timeout.connect(self.sync)
        self.setFixedHeight(62)
        self.setMinimumSectionSize(150)
        self.setDefaultSectionSize(self.minimumSectionSize())
        sheet.ui.data_view.verticalHeader().setMinimumWidth(38)
        QtCore.QTimer.singleShot(0, self, self.label_corner)
        self.sectionResized.connect(self.queue_sync)
        self.sectionMoved.connect(self.queue_sync)
        sheet.ui.data_view.horizontalScrollBar().valueChanged.connect(self.queue_sync)
        for signal in (
            sheet.model.modelReset,
            sheet.model.columnsInserted,
            sheet.model.columnsRemoved,
            sheet.model.headerDataChanged,
        ):
            signal.connect(self.sync)

    def label_corner(self):
        for button in self.sheet.ui.data_view.findChildren(QtWidgets.QAbstractButton):
            if button.metaObject().className() == "QTableCornerButton":
                self.corner_label = MetadataCorner(button)
                break

    def sizeHint(self):
        return QtCore.QSize(super().sizeHint().width(), 62)

    def role_width(self, width):
        text=max(self.fontMetrics().horizontalAdvance(title) for title,_ in self.ROLES)
        return min(max(40,width-40),max(56,text+34))

    def paintSection(self, painter, rect, section):
        painter.save()
        painter.fillRect(rect, self.palette().color(QtGui.QPalette.Window))
        painter.setPen(self.palette().color(QtGui.QPalette.Mid))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.drawLine(rect.left(), rect.top() + 31, rect.right(), rect.top() + 31)
        painter.drawLine(rect.topRight(), rect.bottomRight())
        painter.setPen(self.palette().color(QtGui.QPalette.Text))
        from tailor.column_titles import letters

        label = letters(section)
        split=rect.width()-self.role_width(rect.width())-6
        label = painter.fontMetrics().elidedText(label,QtCore.Qt.ElideRight,split-12)
        painter.drawText(
            QtCore.QRect(rect.left() + 4, rect.top(), split - 8, 30),
            QtCore.Qt.AlignCenter,
            label,
        )
        selection = self.selectionModel()
        if selection is not None and any(
            block.left() <= section <= block.right()
            and block.top()==0 and block.bottom()>=self.model().rowCount()-1
            for block in selection.selection()
        ):
            painter.fillRect(
                QtCore.QRect(rect.left(), rect.bottom() - 2, rect.width(), 3),
                QtGui.QColor("#2878cc"),
            )
        if section > 0 and self.isSectionHidden(section - 1):
            painter.setPen(QtGui.QPen(QtGui.QColor("#e48a23"), 3))
            painter.drawLine(
                rect.left() + 1, rect.top() + 4, rect.left() + 1, rect.bottom() - 4
            )
            painter.drawText(
                QtCore.QRect(rect.left() + 3, rect.top(), 18, 30),
                QtCore.Qt.AlignCenter,
                "⋮",
            )
        if section + 1 < self.count() and self.isSectionHidden(section + 1):
            painter.setPen(QtGui.QPen(QtGui.QColor("#e48a23"), 3))
            painter.drawLine(
                rect.right() - 1, rect.top() + 4, rect.right() - 1, rect.bottom() - 4
            )
            painter.drawText(
                QtCore.QRect(rect.right() - 21, rect.top(), 18, 30),
                QtCore.Qt.AlignCenter,
                "⋮",
            )
        painter.restore()

    def mouseDoubleClickEvent(self, event):
        # Column letters are identities. Edit the remark in the second header row.
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        self._drag_anchor = None
        column = self.logicalIndexAt(event.position().toPoint())
        mods = event.modifiers()
        if event.button() == QtCore.Qt.LeftButton and column >= 0:
            edge = self.sectionViewportPosition(column) + self.sectionSize(column)
            if abs(event.position().x() - edge) > 4 and abs(event.position().x() - self.sectionViewportPosition(column)) > 4:
                view = self.sheet.ui.data_view
                model, selection = view.model(), view.selectionModel()
                if model.rowCount():
                    first = column
                    if mods & QtCore.Qt.ShiftModifier:
                        first = getattr(self, "_column_anchor", column)
                    else:
                        self._column_anchor = column
                    block = QtCore.QItemSelection(
                        model.index(0, min(first, column)),
                        model.index(model.rowCount() - 1, max(first, column)),
                    )
                    flag = (
                        QtCore.QItemSelectionModel.Toggle
                        if mods & (QtCore.Qt.ControlModifier | QtCore.Qt.MetaModifier)
                        else QtCore.QItemSelectionModel.ClearAndSelect
                    )
                    selection.select(block, flag)
                    selection.setCurrentIndex(
                        model.index(0, column), QtCore.QItemSelectionModel.NoUpdate
                    )
                    self._drag_anchor = first
                    self._drag_initial = QtCore.QItemSelection(selection.selection()) if mods & (QtCore.Qt.ControlModifier | QtCore.Qt.MetaModifier) else QtCore.QItemSelection()
                    self.viewport().update()
                    event.accept()
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        anchor = getattr(self, '_drag_anchor', None)
        if anchor is not None and event.buttons() & QtCore.Qt.LeftButton:
            point = event.position().toPoint()
            column = self.logicalIndexAt(point)
            if column >= 0:
                model = self.sheet.ui.data_view.model()
                block = QtCore.QItemSelection(self._drag_initial)
                block.select(model.index(0, min(anchor, column)),
                             model.index(model.rowCount()-1, max(anchor, column)))
                self.selectionModel().select(block, QtCore.QItemSelectionModel.ClearAndSelect)
                self.viewport().update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton and getattr(self, '_drag_anchor', None) is not None:
            self._drag_anchor = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.sync()

    def showEvent(self, event):
        super().showEvent(event)
        self.sync()

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        self.queue_sync()

    def queue_sync(self, *args):
        if not self._sync_timer.isActive():
            self._sync_timer.start()

    def sync(self, *args):
        model = self.sheet.model
        visible = set()
        # Column count only; never inspect source rows or cell selections.
        first = max(0,self.visualIndexAt(0))
        last = self.visualIndexAt(max(0,self.viewport().width()-1))
        if last<0:last=self.count()-1
        for visual in range(first,last+1):
            col=self.logicalIndex(visual)
            if col<0:continue
            left, width = self.sectionViewportPosition(col), self.sectionSize(col)
            if (
                left + width <= 0
                or left >= self.viewport().width()
                or self.isSectionHidden(col)
            ):
                continue
            key = model.columnLabel(col)
            visible.add(key)
            if key not in self.editors:
                role = QtWidgets.QComboBox(self.viewport())
                role.setProperty("columnRole", True)
                for title, value in self.ROLES:
                    role.addItem(title, value)
                name = QtWidgets.QLineEdit(self.viewport())
                # Header cells have their own compact geometry. The inspector's
                # minimum height/padding otherwise expands this editor over the
                # bottom divider, clipping focus and selection indicators.
                name.setStyleSheet("QLineEdit { min-height:0; padding:0 7px; border:1px solid transparent; border-radius:0; background:transparent; } QLineEdit:focus { border-color:palette(highlight); }")
                name.setFixedHeight(27)
                name.setAttribute(QtCore.Qt.WA_MacShowFocusRect, False)
                role.setToolTip("列角色（元数据，不计入数据行）")
                name.setToolTip("名称（列名称，不计入数据行）")
                role.activated.connect(lambda index, key=key: self.commit(key, "role"))
                name.editingFinished.connect(lambda key=key: self.commit(key, "name"))
                self.editors[key] = (role, name)
            role, name = self.editors[key]
            split = width-self.role_width(width)-6
            role.setGeometry(left + split + 2, 2, width - split - 6, 28)
            name.setGeometry(left + 4, 32, max(36, width - 8), 27)
            metadata = model.column_metadata(col)
            role.setCurrentIndex(max(0, role.findData(metadata["role"])))
            value=metadata.get("comment") or model.columnName(col)
            if not name.hasFocus() and name.text()!=value:
                name.setText(value)
            if key not in self._visible_editor_keys:
                role.show()
                name.show()
        for key in self._visible_editor_keys-visible:
            if key in self.editors:
                for widget in self.editors[key]:widget.hide()
        self._visible_editor_keys=visible
        valid_keys=set(model.columnLabels())
        for key in list(self.editors):
            if key not in visible and (key not in valid_keys or len(self.editors)>64):
                for widget in self.editors.pop(key):widget.deleteLater()

    def commit(self, key, field):
        labels = list(self.sheet.model.columnLabels())
        if key not in labels or key not in self.editors:
            return
        role, name = self.editors[key]
        column = labels.index(key)
        value = role.currentData() if field == "role" else name.text()
        if field == 'role' and value == 'Y':
            selection = self.sheet.ui.data_view.selectionModel().selection()
            # Only complete column selections participate; ordinary cell blocks
            # must not silently change roles of unrelated columns.
            selected = {c for block in selection
                        if block.top() == 0 and block.bottom() == self.model().rowCount()-1
                        for c in range(block.left(), block.right()+1)}
            if column in selected and len(selected) > 1:
                self.sheet.model.set_columns_metadata(selected, title='所选列设为 Y', role='Y')
                return
        self.sheet.model.set_column_metadata(column, **{("comment" if field == "name" else field): value})
        name.setText(self.sheet.model.column_metadata(column).get("comment") or self.sheet.model.columnName(column))


class MetadataCorner(QtWidgets.QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        parent.installEventFilter(self)
        self.setGeometry(parent.rect())
        self.show()

    def eventFilter(self, parent, event):
        if event.type() == QtCore.QEvent.Resize:
            self.setGeometry(parent.rect())
        return False

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setPen(self.palette().color(QtGui.QPalette.Mid))
        painter.drawLine(0, 31, self.width(), 31)
        painter.setPen(self.palette().color(QtGui.QPalette.Text))
        painter.drawText(
            QtCore.QRect(0, 32, self.width(), self.height() - 32),
            QtCore.Qt.AlignCenter,
            "名称",
        )

"""Common plot geometries over unchanged source arrays and native PlotDataItem."""

from pathlib import Path

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

MODE_ITEMS = [
    ("折线", "line"),
    ("散点", "scatter"),
    ("线点", "line_scatter"),
    ("柱形", "bar"),
    ("面积", "area"),
    ("阶梯", "step"),
    ("针状", "stem"),
]
ICONS = [
    "chart-line",
    "chart-scatter",
    "chart-no-axes-combined",
    "chart-column",
    "chart-area",
    "chart-spline",
    "chart-no-axes-column",
]


class PaletteSvgIcon(QtGui.QIconEngine):
    """Render neutral UI glyphs with the current app palette on every request."""

    def __init__(self, source):
        super().__init__()
        self.source = source

    def clone(self):
        return PaletteSvgIcon(self.source)

    def paint(self, painter, rect, mode, state):
        from PySide6.QtSvg import QSvgRenderer

        role = (
            QtGui.QPalette.Dark
            if mode == QtGui.QIcon.Disabled
            else QtGui.QPalette.PlaceholderText
        )
        color = QtWidgets.QApplication.palette().color(role).name()
        # QSvgRenderer stretches explicit bounds; keep square glyphs proportional.
        side = min(rect.width(), rect.height())
        bounds = QtCore.QRectF(0, 0, side, side)
        bounds.moveCenter(QtCore.QRectF(rect).center())
        QSvgRenderer(self.source.replace(b"currentColor", color.encode())).render(
            painter, bounds
        )

    def pixmap(self, size, mode, state):
        pix = QtGui.QPixmap(size)
        pix.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pix)
        self.paint(painter, QtCore.QRect(QtCore.QPoint(), size), mode, state)
        painter.end()
        return pix


def icon(name, widget=None, color=None):
    path = Path(__file__).parent / "resources/lucide" / (name + ".svg")
    if not path.exists():
        return QtGui.QIcon()
    if color is None:
        return QtGui.QIcon(PaletteSvgIcon(path.read_bytes()))
    from PySide6.QtSvg import QSvgRenderer

    renderer = QSvgRenderer(path.read_bytes().replace(b"currentColor", color.encode()))
    pix = QtGui.QPixmap(48, 48)
    pix.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pix)
    renderer.render(painter)
    painter.end()
    pix.setDevicePixelRatio(2)
    return QtGui.QIcon(pix)


def geometry(x, y, mode):
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if mode in {"bar", "stem"}:
        if mode == "stem":
            return np.column_stack(
                (x, x, np.full(len(x), np.nan))
            ).ravel(), np.column_stack(
                (np.zeros(len(y)), y, np.full(len(y), np.nan))
            ).ravel()
        finite = np.sort(np.unique(x[np.isfinite(x)]))
        diffs = np.diff(finite)
        width = float(np.median(diffs[diffs > 0])) * 0.8 if len(diffs) else 0.8
        return np.column_stack(
            (
                x - width / 2,
                x - width / 2,
                x + width / 2,
                x + width / 2,
                np.full(len(x), np.nan),
            )
        ).ravel(), np.column_stack(
            (np.zeros(len(y)), y, y, np.zeros(len(y)), np.full(len(y), np.nan))
        ).ravel()
    return x, y


class PlotTypePicker(QtWidgets.QWidget):
    def __init__(self, sheet, plot_button):
        super().__init__()
        self.sheet = sheet
        self.mode = "line"
        self._axis_y_keys = None
        self._axis_loading = False
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        layout.setAlignment(QtCore.Qt.AlignTop)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Maximum)
        line = QtWidgets.QHBoxLayout()
        line.setSpacing(5)
        group = QtWidgets.QButtonGroup(self)
        self.buttons = {}
        for (title, key), glyph in zip(MODE_ITEMS, ICONS, strict=True):
            button = QtWidgets.QToolButton()
            button.setIcon(icon(glyph, button))
            button.setIconSize(QtCore.QSize(23, 23))
            button.setMinimumWidth(30)
            button.setFixedHeight(36)
            button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            button.setStyleSheet("QToolButton {padding:0;}")
            button.setToolTip(title)
            button.setAccessibleName(title)
            button.setCheckable(True)
            group.addButton(button)
            self.buttons[key] = button
            button.clicked.connect(lambda checked=False, k=key: self.choose(k))
            line.addWidget(button, 1)
        self.x_display = RolePickerRow("X", sheet.model)
        self.y_display = RolePickerRow("Y", sheet.model)
        self.axis_grid = QtWidgets.QGridLayout()
        self.axis_grid.setContentsMargins(0,0,0,0)
        self.axis_grid.setHorizontalSpacing(8);self.axis_grid.setVerticalSpacing(7)
        self.axis_grid.setColumnStretch(1,1)
        for index,(title,control) in enumerate((("作为X轴",self.x_display),("作为Y轴",self.y_display))):
            label=QtWidgets.QLabel(title);label.setProperty('fieldLabel',True)
            label.setFixedHeight(30)
            label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            self.axis_grid.addWidget(label,index,0,QtCore.Qt.AlignTop)
            self.axis_grid.addWidget(control,index,1)
        layout.addLayout(self.axis_grid)
        self.x_display.removeRequested.connect(lambda column: self.remove_column("X", column))
        self.y_display.removeRequested.connect(lambda column: self.remove_column("Y", column))
        self.x_display.addRequested.connect(lambda column: self.add_column("X", column))
        self.y_display.addRequested.connect(lambda column: self.add_column("Y", column))
        layout.addLayout(line)
        sheet.model.headerDataChanged.connect(self.sync_roles)
        sheet.model.modelReset.connect(self.sync_roles)
        sheet.selection.selectionChanged.connect(self.follow_selection)
        self.sync_roles()
        plot_button.setText("绘图")
        plot_button.setProperty("intent", "primary")
        try:
            plot_button.clicked.disconnect()
        except RuntimeError:
            pass
        plot_button.clicked.connect(self.draw)
        self.draw_button = plot_button
        self.choose("line")
        layout.addWidget(plot_button)
        plot_button.show()
        self.setStyleSheet(
            "QToolButton:hover {background:#dceaff; border-color:#448ad5;}"
        )

    def follow_selection(self,*args):
        if self._axis_loading:return
        self._axis_y_keys=None
        self.sync_roles()

    def sync_roles(self,*args):
        if self._axis_loading:return
        from tailor.column_titles import letters
        model=self.sheet.model;keys=list(model.columnLabels())
        roles=[model.column_metadata(i).get('role') for i in range(len(keys))]
        xs=[i for i,role in enumerate(roles) if role=='X']
        if self._axis_y_keys is not None:
            ys=[keys.index(key) for key in self._axis_y_keys if key in keys
                and roles[keys.index(key)] not in {'X','XErr','YErr'}]
            self._axis_y_keys=[keys[i] for i in ys]
        else:
            selected={c for block in self.sheet.selection.selection()
                      for c in range(block.left(),block.right()+1) if c<len(keys)}
            ys=[i for i in sorted(selected) if roles[i] not in {'X','XErr','YErr'}]
            if not ys:ys=[i for i,role in enumerate(roles) if role=='Y']
        self.x_display.set_items([(i,letters(i)) for i in xs])
        self.y_display.set_items([(i,letters(i)) for i in ys])
        self.x_display.set_available(i for i,role in enumerate(roles) if role not in {'X','XErr','YErr'})
        self.y_display.set_available(i for i,role in enumerate(roles) if role not in {'X','XErr','YErr'} and i not in ys)
        if hasattr(self,'draw_button'):
            self.draw_button.setEnabled(self.isEnabled() and self.mode is not None and len(xs)==1 and bool(ys))

    def axis_columns(self):
        return ([column for column,_ in self.x_display.items],
                [column for column,_ in self.y_display.items])

    def _apply_axis_edit(self,changes,ys,title):
        model=self.sheet.model;keys=list(model.columnLabels())
        before=({keys[i]:model.column_metadata(i)['role'] for i in changes},
                [keys[i] for i,_ in self.y_display.items])
        after=({keys[i]:value for i,value in changes.items()},list(ys))
        if before==after:return
        def apply(state):
            self._axis_loading=True
            try:
                current=list(model.columnLabels())
                for key,role in state[0].items():
                    if key in current:model.set_column_metadata(current.index(key),_record_edit=False,role=role)
                self._axis_y_keys=[key for key in state[1] if key in current]
            finally:self._axis_loading=False
            self.sync_roles()
        apply(after)
        from tailor.spreadsheet_model import Edit
        model._record(Edit(title,lambda:apply(before),lambda:apply(after),512))

    def add_column(self,role,column):
        model=self.sheet.model;keys=list(model.columnLabels())
        if not 0<=column<len(keys):return
        current=model.column_metadata(column)['role']
        if current in {'XErr','YErr'} or (role=='Y' and current=='X'):return
        ys=[keys[i] for i,_ in self.y_display.items]
        if role=='X':
            changes={i:'none' for i in range(len(keys)) if model.column_metadata(i)['role']=='X' and i!=column}
            changes[column]='X';ys=[key for key in ys if key!=keys[column]]
        else:
            changes={column:'Y'}
            if keys[column] not in ys:ys.append(keys[column])
        self._apply_axis_edit(changes,ys,'设置绘图 X 列' if role=='X' else '添加绘图 Y 列')

    def remove_column(self,role,column):
        model=self.sheet.model;keys=list(model.columnLabels())
        if not 0<=column<len(keys):return
        changes={column:'none'} if model.column_metadata(column)['role']==role else {}
        ys=[keys[i] for i,_ in self.y_display.items if role!='Y' or i!=column]
        self._apply_axis_edit(changes,ys,f'移除绘图 {role} 列')

    def choose(self, key):
        self.mode = key
        self.buttons[key].setChecked(True)
        self.sync_roles()

    def draw(self):
        if self.mode is None or not self.draw_button.isEnabled():
            return
        from dataclasses import replace

        from tailor.curve_controls import apply_style

        owner = self.sheet.main_window
        owner.ui.tabWidget.setCurrentWidget(self.sheet)
        owner._drawing_mode = self.mode
        owner._defer_inspector = not bool(getattr(self.sheet, "_graph_template_name", ""))
        waiting='、' in self.y_display.text()
        if waiting:QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            plot = owner.ask_and_create_plot_tab(columns=self.axis_columns())
        finally:
            if waiting:QtWidgets.QApplication.restoreOverrideCursor()
            owner._drawing_mode = None
            owner._defer_inspector = False
        if plot is None:
            return
        sources = list(plot.model._plots) if plot.presentation.multi else [plot]
        for source in sources:
            if source.curve_style.mode != self.mode:
                apply_style(source, replace(source.curve_style, mode=self.mode))
            if plot.presentation.multi:
                info = plot.model._plots[source]
                info.style = source.curve_style.to_dict()
        if plot.presentation.multi:
            plot.draw_plot()
        from tailor.workflow_templates import apply_graph_template, store
        template = store('graphs').get(getattr(self.sheet, '_graph_template_name', ''))
        if template:
            try:
                apply_graph_template(plot, template)
            except (ValueError,KeyError,StopIteration) as error:
                owner.statusBar().showMessage('模板列映射不匹配：' + str(error))


class RolePickerRow(QtWidgets.QWidget):
    """Resident column buttons in the existing wrapping Qt layout."""
    removeRequested=QtCore.Signal(int)
    addRequested=QtCore.Signal(int)

    def __init__(self,role,model=None):
        super().__init__()
        self.role,self.model=role,model
        self.items=[];self.available=[];self._buttons={}
        self.setMinimumWidth(0)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding,QtWidgets.QSizePolicy.Fixed)
        layout=QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0,0,0,0);layout.setSpacing(6)
        self.chips=QtWidgets.QWidget()
        self.chips.setMinimumWidth(0)
        self.chips.installEventFilter(self)
        from tailor.choice_buttons import FlowLayout
        self.chip_layout=FlowLayout(self.chips);self.chip_layout.setSpacing(4)
        self.placeholder=QtWidgets.QLabel('未选择',self.chips)
        self.placeholder.setProperty('muted',True)
        self.placeholder.setFixedHeight(30)
        self.placeholder.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        self.add_button=QtWidgets.QToolButton(self)
        self.add_button.setIcon(icon('plus',self.add_button,'#35945b'))
        self.add_button.setIconSize(QtCore.QSize(18,18))
        self.add_button.setFixedSize(30,30)
        self.add_button.setToolTip(f'添加{role}列');self.add_button.setAccessibleName(f'添加{role}列')
        self.add_button.setStyleSheet('QToolButton {padding:0;min-height:28px;max-height:28px;min-width:28px;max-width:28px;}')
        self.add_menu=QtWidgets.QMenu(self.add_button)
        self.add_menu.aboutToShow.connect(self.populate_menu)
        self.add_button.clicked.connect(lambda:self.add_menu.popup(self.add_button.mapToGlobal(QtCore.QPoint(0,self.add_button.height()))))
        layout.addWidget(self.chips,1);layout.addWidget(self.add_button,0,QtCore.Qt.AlignTop)
        self.set_items([])

    def text(self):
        return '、'.join(letter for _,letter in self.items) or '—'

    def column_key(self,column):
        return list(self.model.columnLabels())[column] if self.model is not None else column

    def request(self,key,signal):
        keys=list(self.model.columnLabels()) if self.model is not None else None
        if keys is None:signal.emit(key)
        elif key in keys:signal.emit(keys.index(key))

    def set_items(self,items):
        self.items=list(items)
        wanted={self.column_key(column) for column,_ in self.items}
        for key in list(self._buttons):
            if key not in wanted:
                button=self._buttons.pop(key);button.hide();button.deleteLater()
        while self.chip_layout.count():self.chip_layout.takeAt(0)
        for column,letter in self.items:
            key=self.column_key(column)
            button=self._buttons.get(key)
            if button is None:
                button=QtWidgets.QToolButton(self.chips)
                button.setCheckable(True);button.setFixedHeight(30);button.setMinimumWidth(30)
                button.setStyleSheet('QToolButton {padding:0 7px;min-height:0;border:1px solid palette(mid);border-radius:5px;} QToolButton:checked {background:palette(highlight);color:palette(link);border-color:palette(link);}')
                button.clicked.connect(lambda checked=False,key=key:self.request(key,self.removeRequested))
                self._buttons[key]=button
            button.setText(letter);button.setChecked(True)
            button.setFixedWidth(max(30,button.fontMetrics().horizontalAdvance(letter)+18))
            button.setProperty('columnLetter',letter);button.setProperty('columnKey',key)
            button.setToolTip(f'点击取消{letter}列');button.setAccessibleName(f'移除{letter}列')
            self.chip_layout.addWidget(button);button.show()
        from tailor.fold_panel import normalize_control_heights
        normalize_control_heights(self.chips)
        self.placeholder.setVisible(not self.items)
        if not self.items:self.chip_layout.addWidget(self.placeholder)
        self.chip_layout.invalidate()
        self.update_height();self.chips.updateGeometry();self.updateGeometry()
        QtCore.QTimer.singleShot(0,self,self.update_height)

    def update_height(self):
        for button in self._buttons.values():
            button.setFixedWidth(max(30,button.fontMetrics().horizontalAdvance(button.text())+18))
        margins=self.layout().contentsMargins()
        available=max(30,self.width()-self.add_button.width()-max(0,self.layout().spacing())-margins.left()-margins.right())
        height=max(30,self.chip_layout.heightForWidth(available))
        if self.height()!=height:self.setFixedHeight(height)
        # Measure and arrange with the same post-polish spacing/width. A stale
        # FlowLayout geometry can otherwise keep the last row below the clip.
        self.chip_layout.setGeometry(QtCore.QRect(0,0,available,height))

    def eventFilter(self,watched,event):
        if event.type() in (QtCore.QEvent.LayoutRequest,QtCore.QEvent.Resize,QtCore.QEvent.FontChange,QtCore.QEvent.StyleChange):
            QtCore.QTimer.singleShot(0,self,self.update_height)
        return super().eventFilter(watched,event)

    def resizeEvent(self,event):
        super().resizeEvent(event);self.update_height()

    def set_available(self,columns):
        visible=set(__import__('tailor.choice_catalog',fromlist=['visible_columns']).visible_columns(self.model)) if self.model is not None else None
        self.available=[c for c in columns if visible is None or self.column_key(c) in visible]
        self.add_button.setEnabled(bool(self.available))

    def populate_menu(self):
        from tailor.column_titles import letters,display
        self.add_menu.clear()
        for column in self.available:
            key=self.column_key(column)
            title=display(self.model,key) if self.model is not None else letters(column)
            action=self.add_menu.addAction(title)
            action.setData(key)
            action.triggered.connect(lambda checked=False,key=key:self.request(key,self.addRequested))
        if not self.available:self.add_menu.addAction('没有可添加的列').setEnabled(False)

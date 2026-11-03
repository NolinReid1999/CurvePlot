"""Compact advanced inspector using the existing controls and native panels."""

from PySide6 import QtCore, QtWidgets

from tailor.choice_buttons import ChipList, ChoiceButtons
from tailor.graph_controls import row


def install(control):
    c = control
    c._layout_sync = False
    c._layout_before = None
    c._pending_slot = None
    c._layout_timer = QtCore.QTimer(c)
    c._layout_timer.setSingleShot(True)
    c._layout_timer.setInterval(150)
    c._layout_timer.timeout.connect(lambda: commit_layout(c))
    c._ui_park = QtWidgets.QWidget(c)
    c._ui_park.hide()

    def empty(layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(c._ui_park)
                w.hide()

    main = next(
        r[3].layout() for r in c.sections if r[1].property("sectionTitle") == "高级绘图"
    )
    empty(main)
    c.multi = QtWidgets.QPushButton("多选")
    c.multi.setCheckable(True)
    c.multi.setChecked(True)
    c.multi.toggled.connect(lambda active: single(c) if not active else None)
    type_row=row("绘图类型", ChoiceButtons(c.kind, equal=True))
    object_row=row("对象", c.objects, c.multi)
    c.object_row = object_row
    c.multi.setMaximumWidth(52)
    c.objects.show()
    # The object picker already contains the selection. Remove the redundant
    # column summary and its empty card; the existing refs retain selection order.
    source_record=next(r for r in c.sections if r[1].property('sectionTitle')=='高级绘图')
    c.sections.remove(source_record);c.open_layout.removeWidget(source_record[0])
    source_record[0].setParent(c._ui_park);source_record[0].hide()
    c.fixed_header=c.pin_header(type_row,object_row,c.draw)
    c.draw.show()
    c.exit_button.hide()
    card = next(
        r[3].layout() for r in c.sections if r[1].property("sectionTitle") == "子图布局"
    )
    empty(card)
    c.panel_chips = ChipList()
    c.panel_chips.chosen.connect(lambda i: c.choose_layout_target(i))
    c.panel_chips.set_items([f"子图{i+1}" for i in range(4)])
    panel_row = row("作用子图", c.panel_chips)
    c.preset_buttons = {}
    presets = QtWidgets.QHBoxLayout()
    presets.setContentsMargins(0, 0, 0, 0)
    for text, key, tip in [
        ("▣", "A", "左上"),
        ("▣", "B", "右上"),
        ("▣", "C", "左下"),
        ("▣", "D", "右下"),
        ("自定义", "custom", "自定义位置与尺寸"),
    ]:
        b = QtWidgets.QPushButton(text)
        b.setCheckable(True)
        b.setToolTip(tip)
        b.setMinimumWidth(0)
        if key != "custom":
            b.setIcon(slot_icon(key))
            b.setIconSize(QtCore.QSize(44, 32))
            b.setMinimumHeight(34)
            b.setStyleSheet("QPushButton {padding:0;border:0;background:transparent;} QPushButton:checked {background:#dceaff;} QPushButton:hover {background:#eef5fc;}")
            b.setText("")
        b.clicked.connect(lambda checked=False, key=key: choose_preset(c, key))
        c.preset_buttons[key] = b
        presets.addWidget(b)
    card.addLayout(presets)
    card.addWidget(panel_row)
    for field in c.layout_fields:
        field.valueChanged.connect(lambda *args: live_layout(c))
    c.layout_axes = [LayoutAxis(c.layout_fields[:2], ("水平", "垂直")), LayoutAxis(c.layout_fields[2:], ("宽度", "高度"))]
    for axis in c.layout_axes:
        card.addWidget(axis)
        axis.setEnabled(False)
    # Reuse the global shared-slider model, retaining all existing source
    # controls/signals as the sole numeric state.
    from tailor.compact_controls import MultiParameter
    def replace_parameters(title,widgets):
        target=next(r[3].layout() for r in c.sections if r[1].property('sectionTitle')==title)
        empty(target)
        for widget in widgets:target.addWidget(widget);widget.show()
    c.panel_parameters=MultiParameter([c.rows,c.columns],['行数','列数'],['行','列'])
    c.view_parameters=MultiParameter([c.azimuth,c.elevation],['方位角','仰角'],['°','°'])
    c.density_parameters=MultiParameter([c.levels,c.display_limit],['色阶','点数'],['级','点'])
    c.bar_parameters=MultiParameter([c.width,c.bar_gap,c.baseline],['柱宽','柱距','基线'],['','',''])
    for field in (c.rows,c.columns,c.levels,c.display_limit):field.setSingleStep(1)
    replace_parameters('组图设置',([c.panel_parameters] if c.plot is not None else [])+[row(c.share_x,c.share_y),row(c.unified,c.numbering)])
    replace_parameters('三维图设置',[row('绘制方式',c.three_mode),
        row('配色',c.cmap),c.colorbar,row('投影方式',c.projection),c.view_parameters,c.density_parameters])
    replace_parameters('柱状图设置',[row('排列方式',c.bar_mode),c.bar_parameters,row(c.horizontal,c.errors)])
    from tailor.fold_panel import compact
    compact(c.fixed_header)
    c.fixed_header.layout().setContentsMargins(20,4,18,4)
    from tailor.bar_controls import BarControls
    c.bar_setup = BarControls(c)
    from tailor.panel_controls import PanelControls
    c.panel_setup = PanelControls(c)
    c.panel_setup.sync_draft()
    from tailor.three_controls import ThreeControls
    c.three_setup = ThreeControls(c)
    c.choose()
    for record in c.sections:compact(record[3])

    compact(card.parentWidget())
    from tailor.appearance import manager
    dark=manager().dark()
    for widget in [c,*c.findChildren(QtWidgets.QWidget)]:
        if getattr(widget,'_curve_app_dark',None) is None:widget._curve_app_dark=dark


def slot_icon(key):
    from PySide6 import QtGui

    pix = QtGui.QPixmap(96, 72)
    pix.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pix)
    p.scale(2, 2)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setPen(QtGui.QPen(QtGui.QColor("#8da0b5"), 1))
    p.setBrush(QtGui.QColor("#f2f6fc"))
    p.drawRoundedRect(4, 3, 40, 30, 4, 4)
    x, y = {"A": (5, 4), "B": (25, 4), "C": (5, 19), "D": (25, 19)}[key]
    p.setBrush(QtGui.QColor("#579fe8"))
    p.setPen(QtCore.Qt.NoPen)
    p.drawRoundedRect(x, y, 18, 13, 2, 2)
    p.end()
    pix.setDevicePixelRatio(2)
    return QtGui.QIcon(pix)


def single(c):
    c.refs = c.refs[:1]
    c.sync_refs()


def choose_preset(c, key):
    if c._layout_before is not None:
        c._layout_timer.stop();commit_layout(c)
    if key in {'A','B','C','D'}:
        c._pending_slot=key
    else:
        c._pending_slot=None
        c.layout_slot.setCurrentIndex(c.layout_slot.findData(key))
        c.choose_layout_slot(c.layout_slot.currentIndex())
    sync_layout(c)


def sync_layout(c):
    if not hasattr(c, "panel_chips"):
        return
    native = c.native_context()
    draft = getattr(c, "panel_setup", None)
    nodes = native.cfg["nodes"] if native else draft.nodes if draft else []
    active = native.active if native else draft.active if draft else None
    c._layout_sync = True
    try:
        count = len(nodes)
        index = next((i for i,n in enumerate(nodes) if n["id"] == active), 0)
        c.panel_chips.set_items([f"子图{i+1}" for i in range(4)], index)
        for i, button in enumerate(c.panel_chips.buttons):
            button.setEnabled(i < count)
        key = c._pending_slot or c.layout_slot.currentData()
        for k, b in c.preset_buttons.items():
            b.setChecked(k == key)
            b.setEnabled(bool(nodes))
        for axis in c.layout_axes:
            axis.setEnabled(bool(nodes) and key == "custom")
            axis.sync()
    finally:
        c._layout_sync = False


def live_layout(c):
    if c._layout_sync or c.loading or c.layout_slot.currentData() != "custom":
        return
    native = c.native_context()
    draft = getattr(c, "panel_setup", None)
    if not native and (draft is None or not draft.nodes):return
    rect = [f.value() for f in c.layout_fields]
    if rect[2] <= 0 or rect[3] <= 0:
        return
    rect[0] = min(rect[0], 100 - rect[2])
    rect[1] = min(rect[1], 100 - rect[3])
    if c._layout_before is None:
        c._layout_before = native.snapshot() if native else __import__("copy").deepcopy(draft.nodes)
    nodes = native.cfg["nodes"] if native else draft.nodes
    active = native.active if native else draft.active
    node = next(n for n in nodes if n["id"] == active)
    node.update(rect=rect, slot="custom")
    if native:native.place()
    c._layout_timer.start()


def commit_layout(c):
    if c._layout_before is not None:
        native=c.native_context()
        if native:native.record(c._layout_before, "子图位置与尺寸")
        else:c.panel_setup.record_draft(c._layout_before)
        c._layout_before = None


class LayoutAxis(__import__('tailor.compact_controls',fromlist=['DualParameter']).DualParameter):
    """Advanced positions use the same shared-slider layout as axis/band controls."""
    def __init__(self,fields,labels):
        super().__init__(fields[0],fields[1],labels[0],labels[1],suffix='%')
        self.fields=fields
        self.slider=self.stepper.slider
        self.minus,self.plus=self.stepper.buttons

    @property
    def active(self):return self.current

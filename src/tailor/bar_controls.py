"""Column roles and per-series bar settings over existing advanced plotting."""
import copy
from PySide6 import QtCore, QtWidgets
from tailor.graph_controls import row, color_button
from tailor.plot_types import RolePickerRow
from tailor.column_titles import letters, display


class BarControls:
    def __init__(self, c):
        self.c, self.loading = c, False
        self._y_initialized = False
        self._live_before = None
        self._history_timer = QtCore.QTimer(c)
        self._history_timer.setSingleShot(True)
        self._history_timer.setInterval(180)
        self._history_timer.timeout.connect(self.commit_live)
        self.sheet = c.document.data_sheet if c.plot and hasattr(c.document, 'data_sheet') else c.document
        if not hasattr(self.sheet.model, 'columnLabels'):
            self.sheet = c.owner.get_data_sheets()[0]
        self.model = self.sheet.model
        c.bar_series = []
        keys = list(self.model.columnLabels())
        c.bar_x_ref = next(((self.sheet.id, k) for i, k in enumerate(keys)
                           if self.model.column_metadata(i)['role'] == 'X'), None)
        self.x, self.y = RolePickerRow('X', self.model), RolePickerRow('Y', self.model)
        for role, control in [('X', self.x), ('Y', self.y)]:
            control.addRequested.connect(lambda i, r=role: self.role_change(r, i, True))
            control.removeRequested.connect(lambda i, r=role: self.role_change(r, i, False))
        form = QtWidgets.QVBoxLayout()
        self.x_row=row('作为X轴',self.x);self.y_row=row('作为Y轴',self.y)
        form.addWidget(self.x_row);form.addWidget(self.y_row)
        if c.plot is None:form.addWidget(c.panel_parameters)
        form.addWidget(c.horizontal)
        c.add_section('高级绘图', form, True)
        self.record = c.sections.pop()
        c.sections.insert(0, self.record)
        c.open_layout.removeWidget(self.record[0])
        c.open_layout.insertWidget(0, self.record[0])
        self.form = form
        self.data = QtWidgets.QComboBox()
        self.error = QtWidgets.QComboBox()
        self.color = color_button('#2878cc', self.color_changed)
        self.data.activated.connect(lambda *_: self.sync_values())
        self.error.activated.connect(self.error_changed)
        card = next(r[3] for r in c.sections if r[1].property('sectionTitle') == '柱状图设置')
        # Keep arrangement and the existing three-parameter/two-row module.
        old = card.layout().takeAt(card.layout().count() - 1).widget()
        old.setParent(c._ui_park); old.hide()
        card.layout().addWidget(row('数据选择', self.data))
        card.layout().addWidget(row('颜色选择', self.color, '误差值', self.error))
        c.errors.setChecked(True)
        c.errors.hide()
        c.horizontal.toggled.connect(lambda *_: self.sync())
        for field in (c.width, c.bar_gap, c.baseline):
            field.valueChanged.connect(self.live)
        c.bar_mode.currentIndexChanged.connect(self.live)
        self.sync()

    def role_change(self, role, column, adding):
        c = self.c
        key = list(self.model.columnLabels())[column]
        ref = (self.sheet.id, key)
        category = (role == 'X') != (c.kind.currentData() == 'bar' and c.horizontal.isChecked())
        if category:
            c.bar_x_ref = ref if adding else None
            if adding and ref in c.refs: c.refs.remove(ref)
        elif adding:
            if ref != c.bar_x_ref and ref not in c.refs: c.refs.append(ref)
        elif ref in c.refs:
            c.refs.remove(ref)
        c.sync_refs(); c.sync_target_actions()

    def entry(self, ref):
        from tailor.advanced_plotting import COLORS
        for entry in self.c.bar_series:
            if tuple(entry['ref']) == tuple(ref): return entry
        entry = dict(ref=list(ref), color=COLORS[self.c.refs.index(tuple(ref)) % len(COLORS)], error=None)
        self.c.bar_series.append(entry)
        return entry

    def sync(self):
        c = self.c
        if self.loading: return
        self.loading = True
        try:
            bar = c.kind.currentData() == 'bar'
            roles = c.kind.currentData() in {'bar','panels','3d'}
            if bar and not self._y_initialized:
                self._y_initialized = True
                if not c.refs:
                    c.refs = [(self.sheet.id, k) for i, k in enumerate(self.model.columnLabels())
                              if self.model.column_metadata(i)['role'] == 'Y']
                    c.sync_refs()
            self.record[0].setVisible(roles and c.plot is None)
            c.horizontal.setVisible(bar)
            self.x_row.setVisible(c.kind.currentData()!='3d');self.y_row.setVisible(c.kind.currentData()!='3d')
            if c.plot is None:c.panel_parameters.setVisible(c.kind.currentData()=='panels')
            if hasattr(c,'three_setup'):c.three_setup.sync_roles()
            c.object_row.hide()
            parent = self.form if roles else c.fixed_header.layout()
            if c.draw.parentWidget() is not parent.parentWidget():
                c.draw.parentWidget().layout().removeWidget(c.draw)
                parent.addWidget(c.draw)
            c.draw.setVisible(c.plot is None)
            keys = list(self.model.columnLabels())
            if c.bar_x_ref and c.bar_x_ref[1] not in keys:
                c.bar_x_ref = None
            category = [tuple(c.bar_x_ref)] if c.bar_x_ref and c.bar_x_ref[1] in keys else []
            values = [tuple(ref) for ref in c.refs if ref[0] == self.sheet.id and ref[1] in keys]
            for control, refs in ((self.x, values if bar and c.horizontal.isChecked() else category),
                                  (self.y, category if bar and c.horizontal.isChecked() else values)):
                control.set_items([(keys.index(ref[1]), letters(keys.index(ref[1]))) for ref in refs])
                control.set_available([i for i, k in enumerate(keys) if (self.sheet.id, k) not in refs])
            selected = self.data.currentData()
            with QtCore.QSignalBlocker(self.data):
                self.data.clear()
                for ref in values:
                    self.entry(ref)
                    self.data.addItem(display(self.model, ref[1]), ref)
                self.data.setCurrentIndex(max(0, next((i for i in range(self.data.count())
                    if tuple(self.data.itemData(i)) == tuple(selected or ())), 0)))
            self.sync_values()
        finally:
            self.loading = False

    def sync_values(self):
        ref = self.data.currentData()
        self.color.setEnabled(ref is not None); self.error.setEnabled(ref is not None)
        if ref is None:
            self.error.clear(); self.error.addItem('—', None); return
        entry = self.entry(tuple(ref))
        if entry.get('error') not in self.model.columnLabels():
            entry['error'] = None
        self.color.setText(entry['color'])
        with QtCore.QSignalBlocker(self.error):
            self.error.clear(); self.error.addItem('—', None)
            from tailor.choice_catalog import visible_columns
            for key in visible_columns(self.model):
                if key != ref[1] and (self.sheet.id, key) != self.c.bar_x_ref:
                    self.error.addItem(display(self.model, key), key)
            self.error.setCurrentIndex(max(0, self.error.findData(entry.get('error'))))
        self.error.setToolTip('选择绝对误差列；百分比堆叠时按同组总量换算为百分点。')

    def color_changed(self, value):
        if self.data.currentData() is not None:
            self.entry(tuple(self.data.currentData()))['color'] = value
            self.live()

    def error_changed(self, *_):
        if self.data.currentData() is not None:
            self.entry(tuple(self.data.currentData()))['error'] = self.error.currentData()
            self.live()

    def live_state(self):
        c = self.c
        return dict(width=c.width.value(), bar_gap=c.bar_gap.value(), baseline=c.baseline.value(),
                    bar_mode=c.bar_mode.currentData(), bar_series=copy.deepcopy(c.bar_series),
                    errors=any(entry.get('error') is not None for entry in c.bar_series))

    def live(self, *_):
        c = self.c
        view = getattr(c.plot, 'advanced_view', None)
        if c.loading or self.loading or view is None or view.cfg.get('kind') != 'bar':
            return
        after = self.live_state()
        before = {key:copy.deepcopy(view.cfg.get(key)) for key in after}
        if before == after: return
        if self._live_before is None: self._live_before = before
        reset = any(before[key] != after[key] for key in ('baseline','bar_mode'))
        view.cfg.update(copy.deepcopy(after))
        self.queue_draw(view, reset)
        self._history_timer.start()
        c.owner.mark_project_dirty()

    @staticmethod
    def queue_draw(view, reset=False):
        view.reset = view.reset or reset
        if view.visible():
            # Do not restart the deadline on every mouse move: render during
            # slider dragging, coalescing changes into one pending frame.
            if not view.timer.isActive(): view.timer.start(16)
        else:
            view.pending = True

    def commit_live(self):
        c = self.c
        view = getattr(c.plot, 'advanced_view', None)
        if self._live_before is None or view is None: return
        before, self._live_before = self._live_before, None
        after = {key:copy.deepcopy(view.cfg.get(key)) for key in before}
        from tailor.text_style_controls import record_view_edit
        def restore(root, state):
            current = root.advanced_view
            current.cfg.update(copy.deepcopy(state))
            root.advanced_controls.load(current.cfg)
            self.queue_draw(current, True)
        record_view_edit(c.plot, '柱状图设置', before, after, restore)

    def load(self, cfg):
        self.c.bar_series = copy.deepcopy(cfg.get('bar_series', []))
        if 'bar_x_ref' in cfg:
            self.c.bar_x_ref = tuple(cfg['bar_x_ref']) if cfg['bar_x_ref'] else None

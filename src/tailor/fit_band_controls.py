"""Per-result controls over the existing lmfit/pyqtgraph uncertainty bands."""
import copy
import json

import numpy as np
import pyqtgraph as pg
import shiboken6
from PySide6 import QtCore, QtWidgets

from tailor.compact_controls import DualParameter, equal_row, help_button, preference_button, toggle_button
from tailor.graph_controls import number, row

KINDS = ('confidence', 'prediction')
TITLES = ('置信带', '预测带')
COLORS = ('#2878cc', '#d78b38')


class FitBands(QtCore.QObject):
    def __init__(self, extras, graph):
        super().__init__(extras)
        self.extras, self.plot = extras, extras.plot
        self.loading = False
        self.items, self.controls, self.cache = {}, {}, {}
        self.bound = set()
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(35)
        self.timer.timeout.connect(self.refresh)
        self.choice = QtWidgets.QComboBox()
        self.choice.addItem('—', None)
        self.choice.activated.connect(self.choose)
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(row('选择拟合', self.choice))
        for kind, title, color in zip(KINDS, TITLES, COLORS):
            enabled = toggle_button('显示' + title)
            level = number(50, 99.9, 95, 1)
            level.setSingleStep(.1)
            # Retain these backing values for the shared line-preference page;
            # there are no colour/opacity rows in the band section itself.
            opacity = number(0, 100, 18, 0)
            ink = QtWidgets.QLineEdit(color)
            message = QtWidgets.QLabel()
            message.setWordWrap(True)
            for widget in (opacity, ink):
                widget.setParent(graph); widget.hide()
            self.controls[kind] = (enabled, level, opacity, ink, message)
            enabled.clicked.connect(lambda checked=False, k=kind: self.toggle(k))
            level.valueChanged.connect(lambda value, k=kind: self.update(k))
        layout.addWidget(row(*(self.controls[k][0] for k in KINDS)))
        self.dual = DualParameter(*(self.controls[k][1] for k in KINDS), '置信水平', '预测水平')
        for button in self.dual.buttons:
            button.clicked.connect(self.sync_style_target)
        layout.addWidget(self.dual)
        self.preference = preference_button('curve')
        self.preference.clicked.connect(self.open_style)
        layout.addWidget(equal_row(self.preference, QtWidgets.QWidget()))
        section = graph.add_section('置信带与预测带', layout)
        self.section = section
        section._fit_bands=self
        self.page=graph;self.record=graph.sections[-1]
        header = graph.sections[-1][1]
        section.layout().removeWidget(header)
        info = help_button('两种带均针对所选完整拟合，不包含分峰。置信带表示平均趋势的逐点不确定范围；预测带还包含新观测的噪声，同一水平下通常更宽。两者可同时显示，各自保存水平和样式。水平默认95%，并非整条曲线同时覆盖的保证。失效或无协方差的拟合需重新拟合。')
        for kind in KINDS:
            info._help_popup.layout().addWidget(self.controls[kind][-1])
        section.layout().insertWidget(0, row(header, info))
        self.load()
        self.mount_default()

    def mount_default(self):
        router=getattr(self.plot,'fit_router',None)
        page=router.stack.currentWidget() if router else getattr(getattr(self.plot,'fit_actions',None),'page',None)
        if router and page is None:
            for source in self.plot.model._plots:
                if hasattr(source,'fit_actions'):
                    page=source.fit_actions.page;break
                bound=getattr(self,'_mount_sources',set())
                if source.id not in bound:
                    source.inspector_ready.connect(self.mount_default);bound.add(source.id);self._mount_sources=bound
            if page is None and self.record in self.page.sections:
                self.page.sections.remove(self.record);self.page.open_layout.removeWidget(self.section)
                self.section.setParent(self.plot);self.section.hide()
        if page is not None:self.mount(page)

    def mount(self,page):
        if page is self.page and self.record in page.sections:return
        old=self.page
        if self.record in old.sections:
            old.sections.remove(self.record);old.open_layout.removeWidget(self.section)
        # Multi-curve routing shares this graph's explicit-fit selector. Park
        # the hidden source's private card while its existing fit page is used.
        for other in list(page.sections):
            if other[1].property('sectionTitle')=='置信带与预测带' and other is not self.record:
                page.sections.remove(other);page.open_layout.removeWidget(other[0])
                controller=getattr(other[0],'_fit_bands',None)
                other[0].setParent(controller.plot if controller else page);other[0].hide()
        index=next((i for i,r in enumerate(page.sections) if r[1].property('sectionTitle')=='误差棒'),len(page.sections))
        page.sections.insert(index,self.record);page.open_layout.insertWidget(index,self.section)
        self.section.show();self.record[3].setEnabled(True);self.page=page
        self.record[1].clicked.disconnect()
        self.record[1].clicked.connect(lambda checked: self.page.remember_open(self.record,checked))
        page.set_open(self.record,self.record[2])

    def reveal(self):
        router=getattr(self.plot,'fit_router',None)
        if router:
            self.plot.property_tabs.setCurrentWidget(router);router.choose(force=True)
        else:self.plot.property_tabs.setCurrentWidget(self.page)
        self.page.set_open(self.record,True)
        self.page.scroll.ensureWidgetVisible(self.section)

    @property
    def cfg(self):
        return self.extras.cfg

    def entries(self):
        parent = getattr(self.plot, '_inset_parent', self.plot)
        sources = list(parent.model._plots) if parent.presentation.multi else [parent]
        entries={}
        from tailor.choice_catalog import fit_entries
        for source,record,title in fit_entries(parent):
            model=source.data_sheet.model
            if id(model) not in self.bound:
                self.bound.add(id(model))
                model.headerDataChanged.connect(self.schedule)
                model.historyChanged.connect(self.schedule)
            entries[f'{source.id}:{record["id"]}']=(source,record,title)
        return entries

    @QtCore.Slot()
    def schedule(self, *args):
        if not getattr(self.plot, '_graph_disposed', False):
            self.timer.start()

    def selected(self):
        return self.choice.currentData()

    def config(self, key, kind):
        return self.cfg.get('fit_bands', {}).get(key, {}).get(kind, {})

    def refresh_choices(self, entries):
        # One-time migration of the old graph-wide settings to the active
        # complete fit. New projects start with an explicit empty selection.
        legacy = {k: self.cfg[k] for k in KINDS if k in self.cfg}
        if legacy:
            key = next((k for k, (s, r, _) in entries.items() if s.active_fit_id == r['id']), None)
            if key:
                self.cfg.setdefault('fit_bands', {}).setdefault(key, {}).update(copy.deepcopy(legacy))
                self.cfg.setdefault('band_target', key)
                for kind in legacy: self.cfg.pop(kind, None)
        selected = self.cfg.get('band_target')
        contents = [('—', None)] + [(entry[2], key) for key, entry in entries.items()]
        if [(self.choice.itemText(i), self.choice.itemData(i)) for i in range(self.choice.count())] != contents:
            with QtCore.QSignalBlocker(self.choice):
                self.choice.clear()
                for title, key in contents: self.choice.addItem(title, key)
        with QtCore.QSignalBlocker(self.choice):
            self.choice.setCurrentIndex(max(0, self.choice.findData(selected)))

    def load(self):
        self.refresh_choices(self.entries())
        self.loading = True
        key = self.selected()
        for kind, color in zip(KINDS, COLORS):
            enabled, level, opacity, ink, _ = self.controls[kind]
            cfg = self.config(key, kind)
            with QtCore.QSignalBlocker(enabled), QtCore.QSignalBlocker(level), QtCore.QSignalBlocker(opacity):
                enabled.setChecked(cfg.get('enabled', False))
                level.setValue(cfg.get('level', 95))
                opacity.setValue(cfg.get('opacity', .18) * 100)
            ink.setText(cfg.get('color', color))
            enabled.setEnabled(key is not None)
            level.setEnabled(key is not None and enabled.isChecked())
        active=[i for i,k in enumerate(KINDS) if key is not None and self.controls[k][0].isChecked()]
        if active and self.dual.current not in active:self.dual.current=active[0]
        self.dual.setEnabled(bool(active))
        self.dual.sync()
        self.preference.setEnabled(bool(active))
        self.loading = False

    def choose(self, index):
        self.cfg['band_target'] = self.choice.itemData(index)
        self.load()
        self.sync_style_target()

    def toggle(self, kind):
        self.dual.choose(KINDS.index(kind))
        self.update(kind)

    def sync_style_target(self, *args):
        host = getattr(self.plot, 'preferences', None)
        if host is not None and host.curve_target[0] == 'band':
            if self.selected() is None or not self.dual.isEnabled():
                host.clear_curve_target()
            else:
                host.select_curve('band', (self.selected(), KINDS[self.dual.current]))

    def open_style(self):
        if self.selected() is not None and self.dual.isEnabled():
            self.plot.preferences.open_group_curve('band', (self.selected(), KINDS[self.dual.current]))

    def update(self, kind):
        if self.loading or self.selected() is None: return
        key = self.selected()
        before = copy.deepcopy(self.config(key, kind))
        enabled, level, opacity, ink, _ = self.controls[kind]
        after = dict(enabled=enabled.isChecked(), level=level.value(), opacity=opacity.value()/100, color=ink.text())
        self.cfg.setdefault('fit_bands', {}).setdefault(key, {})[kind] = after
        self.draw(key, kind, self.entries())
        from tailor.text_style_controls import record_view_edit
        def restore(plot, value):
            bands = plot.extras.bands
            bands.cfg.setdefault('fit_bands', {}).setdefault(key, {})[kind] = copy.deepcopy(value)
            bands.refresh()
        record_view_edit(self.plot, TITLES[KINDS.index(kind)], before, copy.deepcopy(after), restore)
        self.plot.main_window.mark_project_dirty()
        self.load()
        self.sync_style_target()

    def style(self, target):
        key, kind = target
        cfg = self.config(key, kind)
        from tailor.curve_style import CurveStyle
        return CurveStyle(mode='line', color=cfg.get('color', COLORS[KINDS.index(kind)]), opacity=cfg.get('opacity', .18))

    def apply_style(self, target, spec):
        key, kind = target
        if key not in self.entries(): return
        cfg = self.cfg.setdefault('fit_bands', {}).setdefault(key, {}).setdefault(kind, {})
        cfg.update(color=spec['color'], opacity=spec['opacity'])
        self.draw(key, kind, self.entries())
        self.load()

    def clear(self, key):
        for item in self.items.pop(key, []):
            box = item._curve_extra_box
            if shiboken6.isValid(box): box.removeItem(item)

    def values(self, source, record, level):
        # Use the selected record's settings and residual variance, never the
        # current editor's pending model/range or its sampled residual preview.
        signature = json.dumps([record['settings'], record['parameters'], record['covariance'], record['statistics'], record['source_hash']], sort_keys=True)
        key = (source.id, record['id'], signature, level)
        if key not in self.cache:
            from tailor.fit_results import StoredFit
            from tailor.plot_extras import fit_bands
            model = copy.copy(source.model)
            model.x_col, model.y_col, model.x_err_col, model.y_err_col = record['settings']['columns']
            model._fit_domain = tuple(record['settings']['domain'])
            model._use_fit_domain = record['settings']['use_domain']
            fit = StoredFit(record, model)
            xx = record['curve_x']
            x = np.linspace(float(xx[0]), float(xx[-1]), 500)
            values = fit_bands(model, fit, x, level, record=record)
            if len(self.cache) >= 32: self.cache.pop(next(iter(self.cache)))
            self.cache[key] = x, values
        return self.cache[key]

    def draw(self, key, kind, entries):
        identity = (key, kind)
        cfg = self.config(key, kind)
        message = self.controls[kind][-1]
        if key not in entries or not cfg.get('enabled'):
            self.clear(identity); return
        source, record, _ = entries[key]
        parent = getattr(self.plot, '_inset_parent', self.plot)
        info = parent.model.get_plot_info(source) if parent.presentation.multi else None
        if record.get('hidden') or (info is not None and not info.visible) or source.id in parent.presentation.extra_settings.get('deleted_curves', []):
            self.clear(identity); return
        try:
            if record.get('stale'): raise ValueError('拟合已过期，请重新拟合后显示带。')
            x, (y, confidence, prediction) = self.values(source, record, cfg.get('level', 95))
            half = confidence if kind == 'confidence' else prediction
            own_info = self.plot.model.get_plot_info(source) if self.plot.presentation.multi else None
            box = self.plot.presentation.box_for(own_info) if own_info else self.plot.ui.plot_widget.getViewBox()
            xkey = 'top' if info and info.x_axis == 'top' else 'x'
            ykey = 'right' if info and info.axis == 'right' else 'y'
            items = self.items.get(identity)
            if items and items[0]._curve_extra_box is not box:
                self.clear(identity); items = None
            if items is None:
                curves = [pg.PlotDataItem(), pg.PlotDataItem()]
                area = pg.FillBetweenItem(*curves)
                items = self.items[identity] = [*curves, area]
                for item in items:
                    item._curve_extra_box = box; box.addItem(item)
                area.setZValue(-2)
            from tailor.appearance import ink
            color = pg.mkColor(ink(cfg.get('color', COLORS[KINDS.index(kind)])))
            opacity = cfg.get('opacity', .18)
            for curve, values in zip(items[:2], (y-half, y+half)):
                curve.setData(x, values, pen=pg.mkPen(color, width=.8))
                curve.setOpacity(opacity)
                curve.setLogMode(self.plot.presentation.axes[xkey]['log'], self.plot.presentation.axes[ykey]['log'])
            color.setAlphaF(opacity)
            items[2].setBrush(pg.mkBrush(color))
            from tailor.axis_extensions import wrap_display_items
            wrap_display_items(self.plot.presentation)
            if self.selected() == key:
                message.setText('逐点平均趋势范围。' if kind == 'confidence' else '新观测范围；按该次拟合残差估计同方差噪声。')
        except (ValueError, TypeError, AttributeError, ZeroDivisionError, KeyError, IndexError) as error:
            self.clear(identity)
            if self.selected() == key: message.setText(str(error))

    @QtCore.Slot()
    def refresh(self, *args):
        if getattr(self.plot, '_graph_disposed', False): return
        entries = self.entries()
        tabs=self.plot.main_window.ui.tabWidget
        if tabs.currentWidget() is self.plot:self.mount_default()
        self.load()
        for identity in list(self.items):
            if identity[0] not in entries: self.clear(identity)
        for key in self.cfg.get('fit_bands', {}):
            for kind in KINDS: self.draw(key, kind, entries)

    def close(self):
        self.timer.stop()
        for identity in list(self.items): self.clear(identity)

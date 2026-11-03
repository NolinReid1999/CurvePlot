"""Shared-axis widgets adapt existing axis settings, locators and edit history."""
from PySide6 import QtCore, QtWidgets, QtGui
from tailor.compact_controls import stepper, toggle_button, help_button, preference_button, DualParameter, style_slider_value
from tailor.graph_controls import row, number


class Pair(__import__('tailor.compact_controls',fromlist=['MultiParameter']).MultiParameter):
    """Auto-capable axis adapter using the same shared-slider component."""
    def __init__(self,names,ranges,changed,automatic=False,units=None,label='间隔'):
        self.ranges=ranges;self.changed=changed
        fields=[number(-1 if automatic else lo,hi,-1 if automatic else lo,dec) for lo,hi,dec,step in ranges]
        for field,(_,_,_,step) in zip(fields,ranges):field.setSingleStep(step)
        super().__init__(fields,names,units,label,automatic)
        self.spin=self.editor
        self.values=[field.value() for field in fields]
        for field in fields:field.valueChanged.connect(self.send)

    def send(self,*args):
        if self.loading:return
        self.values=[field.value() for field in self.sources]
        self.changed(self.values)

    def load(self,values):
        self.loading=True
        for field,value in zip(self.sources,values):
            with QtCore.QSignalBlocker(field):field.setValue(value)
        self.values=list(values);self.loading=False;self.sync()

    def sync(self,*args):
        super().sync(*args)
        self.editor._auto_step_base=getattr(self.sources[self.current],'_auto_step_base',None)
        if hasattr(self,'length_spin'):
            width=max(24,self.editor_unit.fontMetrics().horizontalAdvance(self.units[self.current]))
            self.editor_unit.setFixedWidth(width)
            self.length_spin.parentWidget().value_unit_label.setFixedWidth(width)

    def render(self):self.sync()

    def choose(self,index):
        super().choose(index)
        if hasattr(self,'length_spin'):self.sync_length()
        if hasattr(self,'interval_title'):self.interval_title.setText('间隔' if index==0 else '数量')

    def add_lengths(self,first,second):
        self.length_values=[first,second];self.length_spin=number(0,20,5)
        self.length_spin.valueChanged.connect(self.change_length)
        self.length_spin.setSuffix(' px');self.length_spin.setSingleStep(1);self.length_spin.setFixedWidth(72)
        from tailor.compact_controls import aligned_slider_rows
        self.layout().removeWidget(self.slider_row)
        self.slider_row.layout().removeWidget(self.stepper);self.slider_row.hide()
        length_stepper=stepper(self.length_spin)
        style_slider_value(self.length_spin,length_stepper,'px')
        self.interval_title=QtWidgets.QLabel('间隔');self.slider_title=self.interval_title
        self.slider_row=aligned_slider_rows([(self.interval_title,self.stepper),('长度',length_stepper)],self)
        self.layout().addWidget(self.slider_row)
        self.setMinimumHeight(30*len(self.headings)+self.slider_row.minimumHeight()+self.layout().spacing()*len(self.headings))
        self.sync_length()

    def sync_length(self):
        with QtCore.QSignalBlocker(self.length_spin):self.length_spin.setValue(self.length_values[self.current].value())

    def change_length(self,value):self.length_values[self.current].setValue(value)


def replace_contents(control,title):
    record=next(r for r in control.sections if r[1].property('sectionTitle')==title)
    content=record[3];old=content.layout()
    park=QtWidgets.QWidget(control);park.hide()
    while old.count():
        item=old.takeAt(0)
        if item.widget():item.widget().setParent(park)
        elif item.layout():
            holder=QtWidgets.QWidget(park);holder.setLayout(item.layout())
    return old,record


class FactorRows(QtWidgets.QWidget):
    """Two genuinely equal field widths, leaving an odd spare pixel at right."""
    def resizeEvent(self,event):
        super().resizeEvent(event)
        layout=self.layout()
        if layout is None:return
        fields=[layout.itemAtPosition(row,col).widget() for row in range(2) for col in (1,2)]
        for field in fields:field.setMaximumWidth(16777215)
        layout.invalidate();layout.activate()
        width=min(layout.cellRect(0,col).width() for col in (1,2))
        if width>0:
            for field in fields:field.setMaximumWidth(width)


def install(c, *, deferred=False):
    steps = _install_steps(c)
    if deferred:
        return steps
    for _ in steps:
        pass


def _install_steps(c):
    c._pair_loading=False
    layout,record=replace_contents(c,'主刻度与次刻度')
    def ticks(values):
        if c.loading or c._pair_loading:return
        major,minor=values
        with QtCore.QSignalBlocker(c.major_visible),QtCore.QSignalBlocker(c.minor_visible),QtCore.QSignalBlocker(c.minor_count):
            c.major_visible.setChecked(True);c.minor_visible.setChecked(True)
            c.minor_count.setValue(4 if minor<=0 else int(minor))
        c.major.setText('' if major<=0 else f'{major:g}')
        c.minor.setText('')
        c._pending_minor_auto=minor<=0
        if c.tick_pair.current==0:c._pending_precision_follow=True
        c.apply()
    c.tick_pair=Pair(('主刻度','次刻度'),[(0,1e12,6,1),(0,20,0,1)],ticks,True,units=['','个'])
    for field in c.tick_pair.sources:field._positive_auto=True
    c.tick_pair.sources[1]._auto_step_base=lambda:4.
    c.tick_pair.add_lengths(c.tick_length,c.minor_length)
    layout.addWidget(c.tick_pair)
    layout.addWidget(row('刻度方向',*c.direction_buttons.values()))
    header=record[1];record[0].layout().removeWidget(header)
    record[0].layout().insertWidget(0,row(header,help_button('主、次刻度按钮只切换下方间隔和长度的作用对象。主刻度数值表示间隔，次刻度数值表示每两个主刻度之间的短刻度数量。清空、输入0或Auto均恢复自动；正数指定间隔或数量，减至下限恢复Auto。')))
    yield
    layout,_=replace_contents(c,'网格')
    def grid(values):
        if c.loading or c._pair_loading:return
        for button,spin,value in zip((c.grid,c.minor_grid),(c.grid_count,c.minor_grid_count),values):
            with QtCore.QSignalBlocker(button),QtCore.QSignalBlocker(spin):
                button.setChecked(value!=0);spin.setValue(max(0,int(value)))
        c.apply()
    c.grid_pair=Pair(('主网格线','次网格线'),[(0,100,0,1)]*2,grid,True,units=['条','条'],label='数量')
    layout.addWidget(c.grid_pair);layout.addWidget(c.grid_stroke)
    yield
    # Break endpoints use existing throttling and physical-range mapping.
    a=c.advanced;layout,_=replace_contents(c,'断轴')
    layout.addWidget(a.enabled)
    c.break_pair=DualParameter(a.low,a.high,'断轴起点','断轴终点',suffix='',row_label='位置')
    layout.addWidget(c.break_pair)
    c.break_gap=number(.1,50,a.ratio.value()*100,1);c.break_gap.setSuffix(' %');c.break_gap.setFixedWidth(72)
    c.break_gap.valueChanged.connect(lambda v:a.ratio.setValue(v/100))
    def gap_sync(v):
        with QtCore.QSignalBlocker(c.break_gap):c.break_gap.setValue(v*100)
    a.ratio.valueChanged.connect(gap_sync)
    from tailor.compact_controls import aligned_slider_rows
    c.break_pair.layout().removeWidget(c.break_pair.slider_row)
    c.break_pair.slider_row.layout().removeWidget(c.break_pair.stepper);c.break_pair.slider_row.hide()
    c.break_pair.setMinimumHeight(30)
    gap_stepper=stepper(c.break_gap)
    style_slider_value(c.break_gap,gap_stepper,'%')
    c.break_slider_rows=aligned_slider_rows([('位置',c.break_pair.stepper),('间隙',gap_stepper)])
    layout.addWidget(c.break_slider_rows)
    def sync_break_enabled(*args):
        enabled=a.enabled.isChecked()
        for widget in (c.break_pair,c.break_slider_rows,a.low,a.high,a.ratio,c.break_gap):
            widget.setEnabled(enabled)
    a.enabled.toggled.connect(sync_break_enabled)
    sync_break_enabled()
    proxy=c.break_pair.editor.parentWidget()
    proxy.slider.sliderPressed.connect(a.start_drag);proxy.slider.sliderReleased.connect(a.finish_drag)
    for spin in (a.low,a.high):
        spin.valueChanged.connect(c.break_pair.sync)
    yield
    # Factor label and style are stored alongside this axis, not a data column.
    record=next(r for r in c.sections if r[1].property('sectionTitle')=='刻度文字格式')
    c.tick_angle=number(-90,90,0,6)
    c.tick_angle.setSingleStep(1);c.tick_angle.setSuffix(' °')
    c.tick_angle.valueChanged.connect(lambda value:angle_changed(c,value))
    c.angle_label=QtWidgets.QLabel('角度')
    for i in range(record[3].layout().count()):
        widget=record[3].layout().itemAt(i).widget()
        if widget and (widget is c.precision or widget.isAncestorOf(c.precision)):
            precision_stepper=stepper(c.precision)
            widget.layout().removeWidget(precision_stepper)
            record[3].layout().removeWidget(widget)
            widget.hide()
            c.format_slider_rows=aligned_slider_rows([('小数位数',precision_stepper),(c.angle_label,stepper(c.tick_angle))])
            record[3].layout().insertWidget(i,c.format_slider_rows)
            break
    tick_record=next(r for r in c.sections if r[1].property('sectionTitle')=='主刻度与次刻度')
    tick_layout=tick_record[3].layout();format_layout=record[3].layout()
    index=format_layout.indexOf(c.format_slider_rows)+1
    while tick_layout.count():
        item=tick_layout.takeAt(0)
        if item.widget():format_layout.insertWidget(index,item.widget());index+=1
    c.sections.remove(tick_record);c.open_layout.removeWidget(tick_record[0]);tick_record[0].hide()
    c._tick_section_park=tick_record[0]
    record[0].layout().removeWidget(record[1])
    record[0].layout().insertWidget(0,row(record[1],help_button('主刻度调间隔，次刻度调数量。Auto随当前显示范围调整；输入0或清空恢复Auto，不再隐藏刻度。次刻度默认只显示短线。')))
    yield
    c.factor_text=QtWidgets.QLineEdit();c.factor_text.setPlaceholderText('例如 ×10³')
    c.factor_font=preference_button('font')
    c.factor_text.setMinimumWidth(30);c.factor_text.setSizePolicy(QtWidgets.QSizePolicy.Ignored,QtWidgets.QSizePolicy.Fixed)
    c.factor_editor=__import__('tailor.object_text_editor',fromlist=['ObjectTextEditor']).ObjectTextEditor(c)
    c.factor_editor.hide()
    c.factor_side=QtWidgets.QButtonGroup(c);c.factor_buttons={}
    for title,key in [('左','left'),('右','right')]:
        b=toggle_button(title);c.factor_side.addButton(b);c.factor_buttons[key]=b
        b.clicked.connect(lambda checked=False,key=key:factor_changed(c,side=key))
    c.factor_rows=FactorRows()
    factor_grid=QtWidgets.QGridLayout(c.factor_rows)
    factor_grid.setContentsMargins(0,0,0,0);factor_grid.setSpacing(7)
    factor_grid.setColumnStretch(1,1);factor_grid.setColumnStretch(2,1)
    for index,(title,left,right) in enumerate((('轴端倍率',c.factor_text,c.factor_font),('位置',c.factor_buttons['left'],c.factor_buttons['right']))):
        label=QtWidgets.QLabel(title);label.setProperty('fieldLabel',True)
        factor_grid.addWidget(label,index,0)
        for column,field in enumerate((left,right),1):
            field.setMinimumWidth(0)
            field.setSizePolicy(QtWidgets.QSizePolicy.Ignored,QtWidgets.QSizePolicy.Fixed)
            factor_grid.addWidget(field,index,column)
    record[3].layout().addWidget(c.factor_rows)
    c.factor_text.editingFinished.connect(lambda:factor_changed(c))
    c.factor_font.clicked.connect(lambda:open_factor(c))
    c.factor_editor.changed.connect(lambda:factor_changed(c,editor=True))
    from tailor.tick_count_controls import install as install_counts
    install_counts(c)
    sync(c)
    from tailor.parameter_domains import AxisDomains
    c.parameter_domains=AxisDomains(c)


def sync(c):
    if not hasattr(c,'tick_pair'):return
    cfg=c.plot.presentation.axes[c.current]
    c._pair_loading=True
    from tailor.tick_count_controls import sync as sync_counts
    if not sync_counts(c,cfg):
        c.tick_pair.load([cfg['major'] if cfg['major'] is not None else -1,
                         -1 if cfg.get('minor_auto') or cfg['minor_count']==0 else cfg['minor_count']])
        c.tick_pair.sync_length()
    c.grid_pair.load([0 if not cfg['grid'] else cfg['grid_count'] or -1,
                      0 if not cfg['minor_grid'] else cfg['minor_grid_count'] or -1])
    from tailor.text_layout import plain_text
    c.factor_text.setText(plain_text(cfg.get('factor_text','')))
    sync_angle(c,cfg)
    c.factor_buttons['left'].setText('左' if c.current in {'x','top'} else '下')
    c.factor_buttons['right'].setText('右' if c.current in {'x','top'} else '上')
    if getattr(getattr(c.plot,'preferences',None),'editor',None) is c.factor_editor:
        from tailor.text_style_controls import font_spec
        c.factor_editor.load(cfg.get('factor_style') or font_spec(c.plot.curve_style,c.current+'_ticks'),cfg.get('factor_text',''))
    c.factor_buttons[cfg.get('factor_side','right')].setChecked(True)
    sync_backend_capabilities(c)
    c._pair_loading=False
    if hasattr(c,'parameter_domains'):
        from tailor.parameter_domains import axis_source
        if axis_source(c) is None:
            c.tick_pair.units=['个','个'];c.break_pair.units=['',''];c.tick_pair.sync();c.break_pair.sync()
        c.parameter_domains.request()



def sync_backend_capabilities(c):
    view=getattr(c.plot,'advanced_view',None)
    three_d=bool(view and view.cfg.get('kind')=='3d')
    if not three_d and not getattr(c,'_three_grid_restricted',False):return
    c._three_grid_restricted=three_d
    c.grid_pair.sources[1].setEnabled(not three_d)
    c.grid_pair.sources[1].setToolTip('三维后端不绘制独立次网格线。' if three_d else '')
    if three_d and c.grid_pair.current==1:c.grid_pair.choose(0)
    else:c.grid_pair.sync()
    active=not three_d or c.current!='top'
    c.grid_pair.setEnabled(active);c.grid_stroke.setEnabled(active)


def open_factor(c):
    c.plot.preferences.clear_group_selection()
    c.plot.text_selection.select(c.current+'_factor')
    from tailor.text_style_controls import font_spec
    cfg=c.plot.presentation.axes[c.current]
    c.factor_editor.load(cfg.get('factor_style') or font_spec(c.plot.curve_style,c.current+'_ticks'),cfg.get('factor_text',''))
    c.plot.preferences.open_font(c.factor_editor,'轴端倍率')


def factor_changed(c,side=None,editor=False):
    if c.loading or c._pair_loading:return
    import copy
    from tailor.text_style_controls import record_view_edit
    cfg=c.plot.presentation.axes[c.current];key=c.current;before=(copy.deepcopy(cfg),copy.deepcopy(c.plot.presentation.text_offsets))
    from tailor.text_layout import plain_text
    if editor:cfg['factor_text']=c.factor_editor.content.text()
    elif c.factor_text.text()!=plain_text(cfg.get('factor_text','')):cfg['factor_text']=c.factor_text.text()
    if editor:cfg['factor_style']=c.factor_editor.spec()
    if side:
        cfg['factor_side']=side
        c.plot.presentation.text_offsets.pop(key+'_factor',None)
    after=(copy.deepcopy(cfg),copy.deepcopy(c.plot.presentation.text_offsets))
    def restore(p,value):
        p.presentation.axes[key] = copy.deepcopy(value[0])
        p.presentation.text_offsets=copy.deepcopy(value[1])
        p.presentation.apply_axes()
        sync(p.axis_controls)
    restore(c.plot,after)
    record_view_edit(c.plot,'轴端倍率',before,after,restore)


def draw_factors(p):
    from tailor.graph_presentation import AXES
    from tailor.text_style_controls import font_spec,styled_html,native_font
    for key,side in AXES.items():
        axis=p.owner.ui.plot_widget.getAxis(side);cfg=p.axes[key]
        if not hasattr(axis,'factor_item'):
            axis.factor_item=QtWidgets.QGraphicsTextItem(axis)
            axis.factor_item.setAcceptedMouseButtons(QtCore.Qt.NoButton)
            axis.factor_item.setZValue(100)
            axis.geometryChanged.connect(lambda a=axis:place_factor(a))
        item=axis.factor_item
        item.setVisible(bool(cfg.get('factor_text')) and cfg.get('visible',True))
        spec=cfg.get('factor_style') or font_spec(p.owner.curve_style,key+'_ticks')
        item.document().setDefaultFont(native_font(spec));item.setHtml(styled_html(cfg.get('factor_text',''),spec))
        from tailor.text_layout import rotation
        item.setRotation(rotation(spec))
        from tailor.cjk_text import apply_weight
        apply_weight(item.document(),spec)
        axis._factor_presentation=p
        axis._factor_side=cfg.get('factor_side','right');place_factor(axis)


def place_factor(axis):
    import shiboken6
    if not shiboken6.isValid(axis):return
    item=axis.factor_item
    if not shiboken6.isValid(item):return
    rect=axis.geometry();size=item.mapRectToParent(item.boundingRect()).translated(-item.pos())
    end=getattr(axis,'_factor_side','right')=='right'
    if axis.orientation in {'bottom','top'}:
        x=max(0,rect.width()-size.width()) if end else 0
        y=max(0,rect.height()-size.height()) if axis.orientation=='bottom' else 0
    else:
        x=0 if axis.orientation=='left' else max(0,rect.width()-size.width())
        y=0 if end else max(0,rect.height()-size.height())
    item.setPos(x-size.left(),y-size.top())
    presentation=getattr(axis,'_factor_presentation',None)
    drag=getattr(presentation.owner,'text_drag',None) if presentation else None
    if drag:drag.restore()


def sync_angle(c,cfg):
    # Legacy disabled angles display their effective value; new edits are direct.
    angle=cfg.get('tick_angle',0) if cfg.get('tick_angle_enabled',True) else 0
    with QtCore.QSignalBlocker(c.tick_angle):
        c.tick_angle.setValue(angle)
    stepper(c.tick_angle).setEnabled(True)


def angle_changed(c,value):
    if c.loading or c._pair_loading:return
    from tailor.text_style_controls import record_view_edit
    key=c.current;cfg=c.plot.presentation.axes[key]
    before=(cfg.get('tick_angle',0),cfg.get('tick_angle_enabled',bool(cfg.get('tick_angle',0))))
    after=(value,True)
    if before==after:return
    def restore(plot,state):
        angle,active=state
        plot.presentation.axes[key]['tick_angle']=angle
        plot.presentation.axes[key]['tick_angle_enabled']=active
        axis=plot.ui.plot_widget.getAxis({'x':'bottom','top':'top','y':'left','right':'right'}[key])
        axis.settings=plot.presentation.axes[key];axis._tick_rotated_extent=0;axis.picture=None;axis.update()
        controls=plot.axis_controls
        if controls.current==key:
            sync_angle(controls,plot.presentation.axes[key])
        view=getattr(plot,'advanced_view',None)
        if view and view.cfg.get('kind')=='3d' and hasattr(view,'ax'):
            from tailor.three_d_axes import apply
            apply(view);view.canvas.draw_idle()
    restore(c.plot,after)
    record_view_edit(c.plot,'刻度文字角度',before,after,restore)

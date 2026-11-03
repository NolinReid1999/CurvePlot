"""Quantity/custom-interval controls over the existing axis models and editor."""
from PySide6 import QtCore,QtWidgets
from tailor.compact_controls import DualParameter,stepper,toggle_button
from tailor.graph_controls import row


def install(c):
    from tailor.axis_shared_controls import Pair,replace_contents
    c.custom_interval=toggle_button('自定义刻度间隔')
    c.major.editingFinished.disconnect(c.apply)
    def interval_edited():
        if c.loading:return
        c._pending_precision_follow=True
        c.apply()
    c.major.editingFinished.connect(interval_edited)
    c.major.setPlaceholderText('输入正数间隔')
    c.major.setToolTip('启用后使用等间隔刻度；与主刻度数量互斥。')

    class Counts(Pair):
        def sync(self,*args):
            super().sync(*args)
            custom=c.custom_interval.isChecked()
            self.labels[0].setText('—' if custom else f'{self.sources[0].value():g}')
            self.labels[0].setEnabled(self.current==0 and not custom)
            self.stepper.setEnabled(not (self.current==0 and custom))
            c.custom_interval.setEnabled(self.current==0)
            c.major.setEnabled(self.current==0 and custom)

    def changed(values):
        if c.loading or c._pair_loading:return
        count=int(values[0]);cfg=c.plot.presentation.axes[c.current]
        previous=cfg.get('major_count',5)
        if count!=previous and cfg.get('axis_type','numeric')=='numeric' and not cfg.get('log') and not cfg.get('custom_ticks') and not c.custom_interval.isChecked():
            from tailor.axis_tick_policy import current_bounds,reachable_tick_count
            count=reachable_tick_count(*current_bounds(c),count,previous)
            with QtCore.QSignalBlocker(c.tick_pair.sources[0]):c.tick_pair.sources[0].setValue(count)
        c._pending_major_count=count
        with QtCore.QSignalBlocker(c.minor_count):c.minor_count.setValue(int(values[1]))
        with QtCore.QSignalBlocker(c.major_visible),QtCore.QSignalBlocker(c.minor_visible):
            c.major_visible.setChecked(True);c.minor_visible.setChecked(True)
        c._pending_precision_follow=True
        c.apply()
        c.tick_pair.sync()
    c.tick_pair=Counts(('主刻度','次刻度'),[(2,100,0,1),(1,20,0,1)],changed,units=['个','个'],label='刻度数量')
    c.tick_pair.quantity_mode=True

    def custom_changed(on):
        if c.loading or c._pair_loading:return
        cfg=c.plot.presentation.axes[c.current]
        if on:
            from tailor.axis_tick_policy import auto_spacing
            c.major.setText(f"{cfg.get('custom_interval_value',auto_spacing(c)):g}")
        else:
            try:c._pending_custom_interval=float(c.major.text())
            except ValueError:pass
            c.major.clear()
        c._pending_precision_follow=True
        c.apply();c.tick_pair.sync()
    c.custom_interval.clicked.connect(custom_changed)

    # Reuse the original card, keeping the original controls under Qt ownership.
    layout,record=replace_contents(c,'刻度文字格式')
    header=record[1]
    from tailor.compact_controls import help_button
    old_header=record[0].layout().itemAt(0).widget()
    record[0].layout().removeWidget(old_header);old_header.hide()
    record[0].layout().insertWidget(0,row(header,help_button('主刻度数量是智能刻度的目标个数，实际数量允许略有增减；次刻度数量是每段内部短刻度个数。仅主刻度支持自定义间隔，与数量调节互斥。')))
    header.setText('刻度格式');header.setProperty('sectionTitle','刻度格式');header.setAccessibleName('刻度格式')
    layout.addWidget(row(c.labels,c.tick_font))
    layout.addWidget(c.tick_pair)
    layout.addWidget(row(c.custom_interval,c.major))
    from tailor.fold_panel import compact
    compact(record[3])

    advanced=QtWidgets.QVBoxLayout();advanced.setSpacing(7)
    c.precision_label.setText('小数位数')
    advanced.addWidget(row('数字格式',c.notation))
    advanced.addWidget(row('小数位数',stepper(c.precision)))
    advanced.addWidget(row('显示调整',c.expression))
    c.expression.setToolTip('输入公式并按回车：追加新列并切换当前图对应轴的数据源；原列保留。变量x为当前原始值。')
    advanced.addWidget(c.factor_rows)
    factor_labels=c.factor_rows.findChildren(QtWidgets.QLabel)
    for label in factor_labels:
        if label.property('fieldLabel') and label.text()=='位置':label.setText('倍率位置')
    advanced.addWidget(row('文字角度',stepper(c.tick_angle)))
    advanced.addWidget(row('文字前缀',c.prefix,'文字后缀',c.suffix))
    c.tick_length_pair=DualParameter(c.tick_length,c.minor_length,'主刻度','次刻度',suffix='px',row_label='刻度长度')
    advanced.addWidget(c.tick_length_pair)
    advanced.addWidget(row('刻度方向',*c.direction_buttons.values()))
    c.add_section('高级刻度格式',advanced,True)
    new=c.sections.pop();index=c.sections.index(record)+1;c.sections.insert(index,new)
    c.open_layout.removeWidget(new[0]);c.open_layout.insertWidget(index,new[0])
    c.expression.editingFinished.connect(lambda:apply_transform(c))


def sync(c,cfg):
    if not getattr(getattr(c,'tick_pair',None),'quantity_mode',False):return False
    with QtCore.QSignalBlocker(c.custom_interval):c.custom_interval.setChecked(cfg.get('major') is not None)
    c.tick_pair.load([cfg.get('major_count',5),max(1,cfg.get('minor_count',4))])
    if hasattr(c,'tick_length_pair'):c.tick_length_pair.sync()
    return True


def apply_transform(c):
    from tailor.axis_transform import apply_transform
    if c.loading or c._pair_loading:return
    expression=c.expression.text().strip()
    if not expression or c.plot.presentation.axes[c.current].get('display_transform',{}).get('expression')==expression:return
    owner=c.plot.main_window
    if owner.data_operation_busy():
        c.message.setText('请等待当前数据操作结束后再调整坐标数据。');c.message.show();return
    def execute():
        try:
            apply_transform(c,expression)
            c.message.hide()
        except (ValueError,ArithmeticError,RuntimeError,KeyError,TypeError) as error:
            c.message.setText(str(error));c.message.show()
    if max((s.model.rowCount() for s in owner.get_data_sheets()),default=0)<100_000:
        execute();return
    # Let the existing busy indicator paint before the short atomic commit.
    # No Qt objects or project mutations are moved to a worker thread.
    import shiboken6
    token=('axis-transform',id(c),object())
    notice=getattr(owner,'_notice',None)
    owner._axis_transform_token=token;owner._axis_transform_busy=True
    enabled=c.isEnabled();c.setEnabled(False)
    if notice:notice.begin(token,'正在换算坐标数据…',priority=True)
    def finish(*args):
        if shiboken6.isValid(owner) and getattr(owner,'_axis_transform_token',None)==token:
            owner._axis_transform_busy=False;owner._axis_transform_token=None
        if notice and shiboken6.isValid(notice):notice.finish(token)
    c.destroyed.connect(finish)
    def commit():
        try:
            if not getattr(c.plot,'_graph_disposed',False):execute()
        finally:
            finish()
            if shiboken6.isValid(c):
                c.setEnabled(enabled);c.destroyed.disconnect(finish)
    QtCore.QTimer.singleShot(16,c,commit)

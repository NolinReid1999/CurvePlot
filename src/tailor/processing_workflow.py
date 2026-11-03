"""Column-processing workflow controls over the existing worker and provenance."""
import json
import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore,QtWidgets
from tailor.graph_defaults import derived_width
from tailor.compact_controls import toggle_button,equal_row
from tailor.graph_controls import row,number
from tailor.element_button_group import ElementButtons

DETAILS={
 'statistics':'描述统计将每个统计量写入一个结果列，不生成曲线。均值是算术平均；中位数是一半数据位于两侧的位置；标准差描述离散程度；标准误为标准差/√N；Q1/Q2/Q3为25%、50%、75%分位数。样本使用n−1，总体使用n。',
 'derivative':'微分：计算dy/dx，使用相邻采样点的数值梯度，适合观察变化速率。X须严格递增。噪声会被放大，可先平滑。',
 'integral':'积分：使用梯形法计算所选范围的定积分，结果是一个数，单位为X单位×Y单位。',
 'cumulative':'累计积分：每个位置输出从范围起点到该点的梯形积分，起点为0，输出可绘制。',
 'interpolate':'插值：在新X位置估算Y；线性连接相邻点，PCHIP尽量保持曲线形状，三次样条较光滑。不会补回未知真实测量信息。',
 'resample':'重采样：按点数或步长建立等间距X，再按所选插值方法计算Y，生成配对的新X/Y列。',
 'add':'α＋β：α是选中的对象列；β可选参考列或常数。常数等价于同长度的常数序列，不在表格中新增该列。',
 'subtract_columns':'α−β：从对象列减去参考列或常数。参考列与参考值互斥。',
 'multiply':'α×β：对象列乘以参考列或常数，可用于标定倍率。',
 'divide':'α÷β：对象列除以参考列或常数；β出现0时停止，避免生成无穷值。',
 'moving_average':'移动平均：窗口内取平均抑制高频噪声。窗口越大越平滑，也更容易削弱窄峰。边缘处理决定首尾如何补齐窗口。',
 'savgol':'Savitzky–Golay平滑：窗口内做多项式拟合，较好保持峰形；窗口应为奇数且大于多项式阶数。',
 'block_average':'分组平均：每组若干点合并为一个点，同时平均X与Y；尾部不足一组也保留。',
 'baseline_constant':'减常数基线：从所有Y值减去指定常数。',
 'baseline_linear':'减直线基线：减去连接两端的线性背景，便于比较曲线相对变化。',
 'subtract':'参考列相减：减去参考序列乘以数值系数。',
 'normalize_max':'最大绝对值归一化：除以最大绝对值，保持正负号。',
 'normalize_range':'0–1归一化：减最小值后除以极差。常数列不能执行。',
 'region_integral':'交互面积：拖动分析区间或输入起止X；可选择零基线或连接端点的直线基线。输出积分和范围信息，绘图区可显示参与计算的数据。',
 'region_slope':'区间线性斜率：对范围内数据进行线性回归，输出斜率、截距、R²及斜率标准误，并可显示回归线。',
 'extrema':'区间极值：输出最小/最大Y及对应X；可在图上显示两个极值位置。',
 'fft_amplitude':'FFT幅度谱：把等间距采样信号转换为频率和幅度。频率单位是1/X单位；窗口影响泄漏与幅值。频谱独立显示在处理结果页，避免混用原始X轴。',
 'fft_power':'FFT功率谱密度：显示功率在频率上的分布。要求等间距X；排除点造成的采样缺口不会被自动插值。',
 'lowpass':'低通滤波：保留低于截止频率的信号。使用Butterworth二阶节和零相位双向滤波，频率须低于奈奎斯特频率。',
 'highpass':'高通滤波：保留高于截止频率的信号，可抑制缓慢基线。',
 'bandpass':'带通滤波：仅保留上下截止频率之间的频段，要求0＜下限＜上限＜采样频率/2。',
 'bandstop':'带阻滤波：抑制指定频段，保留其他频率。',
 'envelope_hilbert':'Hilbert包络：对去均值信号求振幅，并加回均值形成上下边界。适合等间距的振荡信号。',
 'envelope_peaks':'峰值包络：检测极大/极小值，使用保形PCHIP连接。调整峰显著性与最小峰距排除噪声小峰；每侧至少需要两个有效峰。',
 'envelope_sliding':'滑动包络：每个窗口取最大/最小值，适合估算局部上下边界。窗口和后续平滑会改变包络细节。',
 'replicate':'重复测量：选择同一工作表、完全相同X的至少两列Y，逐位置计算均值、样本SD或SEM和有效次数N。可设每个位置最低有效次数，不满足时均值/误差留空，N保留。',
}


def install(c):
    c.live_timer=QtCore.QTimer(c);c.live_timer.setSingleShot(True);c.live_timer.setInterval(220)
    c.live_timer.timeout.connect(lambda:live(c))
    c._live_pending=False;c._workflow_loading=False
    section=next(r for r in c.sections if r[1].property('sectionTitle')=='处理')
    old=section[3].layout()
    park=QtWidgets.QWidget(c);park.hide()
    while old.count():
        item=old.takeAt(0)
        if item.widget():item.widget().setParent(park)
    old.setDirection(QtWidgets.QBoxLayout.TopToBottom)
    c.draw_result=toggle_button('绘制处理')
    c.draw_result.setChecked(bool(c.plot))
    c.preview_toggle=toggle_button('预览')
    c.preview_toggle.toggled.connect(lambda on:(schedule(c) if on else c.clear_preview()))
    c.execute=QtWidgets.QPushButton('执行处理');c.execute.setProperty('intent','primary')
    c.execute.clicked.connect(lambda:c.run(c.category,True))
    c.process_actions=ElementButtons(c.document,'processing',add=lambda:reset(c))
    c.execution=QtWidgets.QWidget(c)
    execution=QtWidgets.QVBoxLayout(c.execution)
    execution.setContentsMargins(0,0,0,0);execution.setSpacing(6)
    execution.addWidget(row(c.draw_result,c.preview_toggle))
    execution.addWidget(c.execute)
    section[1].setText('处理结果')
    section[1].setProperty('sectionCaption', '处理结果')
    section[1].setAccessibleName('处理结果')
    c.details=QtWidgets.QLabel();c.details.setWordWrap(True);c.details.setTextFormat(QtCore.Qt.PlainText)
    c.add_section('详情',c.details,True)
    c.spectrum=pg.PlotWidget();c.spectrum.setMinimumHeight(180);c.spectrum.setMaximumHeight(290)
    c.spectrum.setLabel('bottom','频率');c.spectrum.setLabel('left','幅度 / 功率谱密度')
    c.preview_card.layout().addWidget(c.spectrum);c.spectrum.hide()
    # Reference column/value are two explicit, cancellable and exclusive rows.
    opts=c.options['基础数学']
    from PySide6 import QtGui
    c.beta_column=toggle_button('参考列');c.beta_value=toggle_button('参考值')
    for legacy in (c.beta_column,c.beta_value):legacy.setParent(park);legacy.hide()
    opts['reference_value']=QtWidgets.QLineEdit()
    opts['reference_value'].setPlaceholderText('手动输入数值')
    opts['reference_value'].setValidator(QtGui.QDoubleValidator(opts['reference_value']))
    c.clear_reference=QtWidgets.QPushButton('取消')
    c.clear_reference_value=QtWidgets.QPushButton('取消')
    for button in (c.clear_reference,c.clear_reference_value):
        button.setFixedWidth(48)
    reference_row=c.rows[('基础数学','reference')]
    reference_row.layout().addWidget(c.clear_reference)
    fields=reference_row.parentWidget().layout()
    value_row=row('参考值',opts['reference_value'],c.clear_reference_value)
    fields.insertWidget(fields.indexOf(reference_row)+1,value_row)
    c.rows[('基础数学','reference_value')]=value_row
    def ref_column(*args,opts=opts):
        selected=opts['reference'].currentData() is not None
        if selected:
            with QtCore.QSignalBlocker(opts['reference_value']):opts['reference_value'].clear()
        c.beta_column.setChecked(selected);c.beta_value.setChecked(False)
        schedule(c)
    def ref_value(*args,opts=opts):
        active=bool(opts['reference_value'].text().strip())
        if active:
            with QtCore.QSignalBlocker(opts['reference']):opts['reference'].setCurrentIndex(0)
        c.beta_column.setChecked(False);c.beta_value.setChecked(active)
        schedule(c)
    opts['reference'].currentIndexChanged.connect(ref_column)
    opts['reference_value'].textChanged.connect(ref_value)
    c.clear_reference.clicked.connect(lambda checked=False,opts=opts:opts['reference'].setCurrentIndex(0))
    c.clear_reference_value.clicked.connect(opts['reference_value'].clear)
    opts['reference_value'].setToolTip('β为手动输入的常数；输入后取消参考列，选择参考列后清空本值。')
    opts['align'].setToolTip('X相同直接逐点运算；不同X需主动选择线性插值，不自动外推。参考值不需要对齐。')
    # Region endpoints and baseline are actual numeric algorithm inputs.
    opts=c.options['交互区域分析']
    opts['region_low']=number(-1e12,1e12,0,6);opts['region_high']=number(-1e12,1e12,1,6)
    from tailor.graph_controls import combo
    from tailor.choice_buttons import ChoiceButtons
    opts['region_baseline']=combo([('零基线','zero'),('端点直线','endpoints')])
    record=next(r for r in c.sections if r[1].property('sectionTitle')=='交互区域分析')
    for key,title in (('region_low','开始'),('region_high','结束'),('region_baseline','面积基线')):
        line=row(title,ChoiceButtons(opts[key],equal=True) if key=='region_baseline' else opts[key])
        record[3].layout().addWidget(line)
        c.rows[('交互区域分析',key)]=line
    for name in ('region_low','region_high'):
        opts[name].valueChanged.connect(lambda value:region_changed(c))
    opts=c.options['重复测量'];opts['minimum_count']=number(1,1000,2,0,unit='次')
    record=next(r for r in c.sections if r[1].property('sectionTitle')=='重复测量')
    line=row('最少次数',opts['minimum_count']);record[3].layout().addWidget(line)
    c.rows[('重复测量','minimum_count')]=line
    for title,options in c.options.items():
        for value in options.values():
            widgets=value.values() if isinstance(value,dict) else [value]
            for widget in widgets:
                if isinstance(widget,QtWidgets.QAbstractSpinBox):widget.valueChanged.connect(lambda *a:schedule(c))
                elif isinstance(widget,QtWidgets.QComboBox):widget.currentIndexChanged.connect(lambda *a:schedule(c))
                elif isinstance(widget,QtWidgets.QAbstractButton):widget.toggled.connect(lambda *a:schedule(c))
    for selector in c.methods.values():selector.currentIndexChanged.connect(lambda *a:refresh(c))
    for button in c.options['描述统计']['statistics'].values():button.toggled.connect(lambda *args:refresh(c))
    c.operationFinished.connect(lambda outcome:finish_result(c,outcome))
    from tailor.fold_panel import compact
    for record in c.sections:compact(record[3])
    refresh(c)
    from tailor.parameter_domains import install_column_domains
    c.parameter_domains=install_column_domains(c)
    from tailor.processing_history import ProcessingHistory
    c.input_history=ProcessingHistory(c)


def refresh(c):
    if not hasattr(c,'draw_result'):return
    if c.category in c.methods:
        content=next(r[3] for r in c.sections if r[1].property('sectionTitle')==c.category)
        if c.execution.parentWidget() is not content:
            content.layout().addWidget(c.execution)
        c.execution.show()
    else:c.execution.hide()
    method=c.methods[c.category].currentData() if c.category in c.methods else ''
    if hasattr(c,'spectrum'):
        c.spectrum.setVisible(method.startswith('fft_') and bool(c.spectrum.listDataItems()))
    drawable=bool(c.plot) and method not in {'statistics','integral'}
    c.draw_result.setEnabled(drawable);c.preview_toggle.setEnabled(drawable)
    c.process_actions.buttons['hide'].setEnabled(bool(c.plot))
    c.process_actions.buttons['down'].setEnabled(bool(c.plot))
    if not drawable and c.preview_toggle.isChecked():c.preview_toggle.setChecked(False)
    if c.category=='基础数学':
        binary=method in {'add','subtract_columns','multiply','divide'}
        c.rows[('基础数学','reference_value')].setVisible(binary)
    content=DETAILS.get(method,'选择已有分析记录可以查看来源、参数、过期状态；手动重算默认更新原结果列，另存为新结果保留旧列。自动重算仅在主动开启后执行。')
    if method=='statistics':
        selected=[b.text() for b in c.options['描述统计']['statistics'].values() if b.isChecked()]
        content='已选：'+'、'.join(selected)+'\n'+content
    c.details.setText(content)
    schedule(c)


def schedule(c):
    if not hasattr(c,'preview_toggle') or c._workflow_loading:return
    if c.preview_toggle.isChecked() and c.preview_toggle.isEnabled():
        c._live_pending=True;c.live_timer.start()


def live(c):
    if not c.preview_toggle.isChecked():return
    if c.job is not None or c.owner.data_operation_busy():
        c._live_pending=True;return
    c._live_pending=False
    c.run(c.category,False)


def finish_live(c):
    if c._live_pending and c.preview_toggle.isChecked():c.live_timer.start()


def reset(c):
    if c.job is not None:return
    c._workflow_loading=True
    try:
        c.clear_preview()
        with QtCore.QSignalBlocker(c.preview_toggle):c.preview_toggle.setChecked(False)
        for key,widget in c.options.get(c.category,{}).items():
            if isinstance(widget,QtWidgets.QComboBox):widget.setCurrentIndex(0)
            elif isinstance(widget,QtWidgets.QLineEdit):widget.clear()
            elif isinstance(widget,QtWidgets.QDoubleSpinBox):
                defaults={'window':5,'polyorder':2,'value':0,'reference_value':0,'points':200,'step':1,'cutoff':.1,'cutoff2':.3,'order':4,'minimum_count':2,'smooth':1,'distance':1}
                widget.setValue(defaults.get(key,max(widget.minimum(),0)))
            elif isinstance(widget,dict):
                for name,b in widget.items():b.setChecked(name=='mean')
        c.recompute_record=None
        c.selected_result=None
        refresh_results(c)
    finally:c._workflow_loading=False
    refresh(c)


def region_changed(c):
    if c._workflow_loading or not c.plot:return
    opts=c.options['交互区域分析'];low,high=opts['region_low'].value(),opts['region_high'].value()
    if low>=high:return
    c._workflow_loading=True
    try:
        c.show_region(True)
        with QtCore.QSignalBlocker(opts['region']):opts['region'].setChecked(True)
        from tailor.graph_presentation import display
        with QtCore.QSignalBlocker(c.analysis_region):
            c.analysis_region.setRegion(display([low,high],c.plot.presentation.axes['x']))
    finally:
        c._workflow_loading=False
    schedule(c)


def region_to_fields(c):
    if c._workflow_loading or not hasattr(c,'analysis_region'):return
    from tailor.graph_presentation import physical
    values=physical(c.analysis_region.getRegion(),c.plot.presentation.axes['x'])
    c._workflow_loading=True
    for key,value in zip(('region_low','region_high'),values):
        with QtCore.QSignalBlocker(c.options['交互区域分析'][key]):c.options['交互区域分析'][key].setValue(value)
    c._workflow_loading=False;schedule(c)


def draw_spectrum(c,result):
    c.spectrum.clear();c.spectrum.plot(result['x'],result['y'],pen=pg.mkPen('#2878cc',width=derived_width(c.plot)))
    c.spectrum.show();c.preview_card.show()


def install_result_picker(c):
    c.selected_result=None
    c.result_choice=QtWidgets.QComboBox()
    c.result_choice.setMinimumWidth(0)
    c.result_choice.setSizePolicy(QtWidgets.QSizePolicy.Ignored,QtWidgets.QSizePolicy.Fixed)
    section=next(r for r in c.sections if r[1].property('sectionTitle')=='处理')
    section[3].layout().addWidget(row('选择结果',c.result_choice))
    c.open_result=QtWidgets.QPushButton('跳转到处理结果页')
    c.open_result.clicked.connect(lambda:open_result(c))
    section[3].layout().addWidget(equal_row(c.open_result,c.process_actions))
    from tailor.fold_panel import normalize_control_heights
    normalize_control_heights(section[3])
    c.result_choice.activated.connect(lambda index:choose_result(c,c.result_choice.itemData(index)))
    from tailor.analysis_records import monitor
    monitor(c.owner).changed.connect(c.refresh_result_choice)
    for sheet in c.sheets().values():
        sheet.model.modelReset.connect(c.refresh_result_choice)
        sheet.model.headerDataChanged.connect(c.refresh_result_choice)
    refresh_results(c)


def refresh_results(c):
    import shiboken6
    if not shiboken6.isValid(c) or not hasattr(c,'result_choice') or not shiboken6.isValid(c.result_choice):return
    from tailor.analysis_records import records
    from tailor.column_titles import display
    with QtCore.QSignalBlocker(c.result_choice):
        c.result_choice.clear();c.result_choice.addItem('—',None)
        for record in records(c.owner):
            title=record['recipe']['title']
            if ('平滑与校正' if title=='数据预处理' else title)!=c.category:continue
            names='、'.join(display(sheet.model,key) for sheet,key,*_ in record['outputs'])
            c.result_choice.addItem(names,record['recipe']['id'])
        from tailor.choice_catalog import sort_combo,graph_columns
        if c.plot:
            hidden=graph_columns(getattr(c.plot,'_visible_graph_document',c.plot))[1]
            for index in range(c.result_choice.count()-1,0,-1):
                identifier=c.result_choice.itemData(index)
                result=next((r for r in records(c.owner) if r['recipe']['id']==identifier),None)
                outputs=[(s.id,k) for s,k,*_ in result['outputs']] if result else []
                plotted=graph_columns(getattr(c.plot,'_visible_graph_document',c.plot))[0]
                drawn=[ref for ref in outputs if ref in plotted]
                if drawn and all(ref in hidden for ref in drawn):c.result_choice.removeItem(index)
        sort_combo(c.result_choice)
        index=c.result_choice.findData(c.selected_result)
        c.result_choice.setCurrentIndex(max(0,index))
        if index<0:c.selected_result=None
    if hasattr(c,'process_actions'):c.process_actions.sync()
    if hasattr(c,'open_result'):c.open_result.setEnabled(selected_record(c) is not None)


def selected_record(c):
    from tailor.analysis_records import records
    return next((r for r in records(c.owner) if r['recipe']['id']==getattr(c,'selected_result',None)),None)


def choose_result(c,identifier):
    c.selected_result=identifier
    doc=c.document
    if c.plot:
        doc.annotations.select(None);doc.text_selection.select(None)
        doc.curve_selection.current=None;doc.curve_selection.override_item=None
        doc._selected_drawn_key=None;doc.curve_selection.refresh()
        doc.preferences.clear_curve_target()
        doc.preferences._font_allowed=False
    c.process_actions.sync()
    c.open_result.setEnabled(selected_record(c) is not None)
    if hasattr(doc,'quick_actions'):doc.quick_actions.sync()


def open_result(c):
    if selected_record(c) is None:return
    from tailor.result_pages import refresh_processing,page
    refresh_processing(c.owner)
    notebook=page(c.owner,'processing',False)
    if notebook is None:return
    for i in range(notebook.tabs.count()):
        if notebook.tabs.widget(i).record_id==c.selected_result:
            notebook.tabs.setCurrentIndex(i)
            c.owner.ui.tabWidget.setCurrentWidget(notebook)
            break


def hide_selected(c):
    record=selected_record(c)
    if record is None or not c.plot:return
    from tailor.element_actions import curve_visible,combine
    from tailor.document_names import sources
    graph=getattr(c.plot,'_visible_graph_document',c.plot)
    keys={(sheet.id,key) for sheet,key,*_ in record['outputs']}
    sheet=record['outputs'][0][0];history=list(sheet.model._history[:sheet.model._cursor])
    for source in sources(graph):
        if (source.data_sheet.id,source.model.y_col) in keys:
            curve_visible(graph,source,False)
    combine(sheet.model,history,'隐藏处理结果')


def finish_result(c,outcome):
    finish_live(c)
    if outcome.get('success') and outcome.get('recipe'):
        c.selected_result=outcome['recipe']['id']
    refresh_results(c)

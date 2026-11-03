"""Reuse each native PlotTab fitter inside a multi-curve graph inspector."""
import copy
from types import SimpleNamespace
from PySide6 import QtCore,QtWidgets
from tailor.graph_defaults import derived_width
from tailor.graph_controls import row
from tailor.compact_controls import equal_row,toggle_button
from tailor.element_button_group import ElementButtons


def reset_new(plot):
    plot.fit_actions.modify_id=plot.fit_actions.current_id=None
    plot.active_fit_id=None
    plot.model.best_fit=None
    plot.model.fit_preset_key=None
    plot.model.update_model_expression('')
    plot.model._parameters={}
    plot.preset_controls._custom_selected=False
    plot.preset_controls.manual_peaks.arm(False)
    with QtCore.QSignalBlocker(plot.preset_controls.manual_peaks.button):
        plot.preset_controls.manual_peaks.button.setChecked(False)
    plot.preset_controls.sync_model()
    plot.update_model_widget();plot.update_model_curves();plot.plot_best_fit();plot.fit_actions.sync()
    plot.ui.result_box.clear()
    host=getattr(plot,'_fit_host',None)
    if host is not None:host.draw_plot()


def build_single(plot,fit,use_axis,range_box):
    from tailor.column_titles import display
    from tailor.workflow_header import header_row
    choice=QtWidgets.QComboBox()
    choice.addItem('—',None)
    choice.addItem(display(plot.data_sheet.model,plot.model.y_col),plot)
    choice.setCurrentIndex(1)
    plot.fit_curve_choice=choice
    plot.fit_curve_row=header_row('选择曲线',choice)
    plot.fit_all_data=toggle_button('全部数据')
    plot.fit_current_data=toggle_button('当前显示数据')
    ranges=QtWidgets.QButtonGroup(fit)
    ranges.addButton(plot.fit_all_data);ranges.addButton(plot.fit_current_data)
    plot.fit_range_buttons=ranges
    plot.fit_all_data.setChecked(not plot.model._use_fit_domain)
    plot.fit_range_row=header_row('范围',plot.fit_all_data,plot.fit_current_data)
    plot.fit_model_row=header_row('选择模型',plot.preset_controls.selector,plot.preset_controls.help_button)
    previous=plot.fit_header
    fit.layout().removeWidget(previous);previous.hide()
    plot.fit_header=fit.pin_header(plot.fit_curve_row,plot.fit_range_row,plot.fit_model_row)
    choice.activated.connect(lambda index:set_source_enabled(plot,choice.itemData(index) is not None))
    fit.layout().setSpacing(0)
    def all_data():
        with QtCore.QSignalBlocker(use_axis):use_axis.setChecked(False)
        plot.model.set_fit_domain_enabled(False)
        with QtCore.QSignalBlocker(plot.ui.use_fit_domain):plot.ui.use_fit_domain.setChecked(False)
        plot.custom_fit_range.setChecked(False)
        plot.update_model_curves()
        plot.main_window.mark_project_dirty()
    plot.fit_all_data.clicked.connect(all_data)
    plot.fit_current_data.clicked.connect(lambda:use_axis.click() if not use_axis.isChecked() else use_axis.clicked.emit(True))
    def sync_range(*args):
        ranges.setExclusive(False)
        plot.fit_all_data.setChecked(not plot.model._use_fit_domain)
        plot.fit_current_data.setChecked(plot.model._use_fit_domain and use_axis.isChecked())
        ranges.setExclusive(True)
    use_axis.toggled.connect(sync_range)
    from tailor.axis_shared_controls import replace_contents
    layout,_=replace_contents(fit,'参数与执行')
    peaks=plot.preset_controls.manual_peaks
    layout.addWidget(peaks.count_row)
    layout.addWidget(plot.ui.parameter_box)
    layout.addWidget(row(peaks.button,plot.preset_controls.guess_button))
    peaks.widget.hide()
    actions=ElementButtons(plot,'fit',add=lambda:reset_new(plot))
    plot.fit_actions.actions=actions
    layout.addWidget(plot.ui.fit_button)
    plot.fit_result_choice=QtWidgets.QComboBox()
    plot.fit_result_choice.setMinimumWidth(0)
    result_layout,result_record=replace_contents(fit,'拟合结果')
    result_layout.addWidget(row('选择结果',plot.fit_result_choice))
    plot.fit_open_result=QtWidgets.QPushButton('跳转到拟合结果页')
    plot.fit_open_result.clicked.connect(lambda:open_result(plot))
    result_layout.addWidget(equal_row(plot.fit_open_result,actions))
    from tailor.fold_panel import normalize_control_heights
    normalize_control_heights(result_record[3])
    plot.fit_result_choice.activated.connect(lambda index:choose_result(plot,index))
    sheet=plot.data_sheet.model
    for signal in (sheet.headerDataChanged,sheet.modelReset,sheet.columnsMoved,sheet.columnsInserted,sheet.columnsRemoved):
        signal.connect(plot.fit_actions.refresh_result_choices)
    layout,_=replace_contents(fit,'拟合范围')
    layout.addWidget(use_axis)
    custom=toggle_button('自定义范围')
    plot.custom_fit_range=custom
    fields=(plot.ui.fit_start_box,plot.ui.fit_end_box)
    custom.setStyleSheet('QPushButton {padding:3px 4px;}')
    custom.setMinimumWidth(0)
    layout.addWidget(row(custom,'开始',fields[0],'结束',fields[1]))
    layout.addWidget(row('拟合线显示',plot.ui.draw_curve_option))
    def manual(*args):
        if plot._fit_range_loading:return
        with QtCore.QSignalBlocker(use_axis):use_axis.setChecked(False)
        custom.setChecked(True)
        plot.model.set_fit_domain_enabled(True)
        sync_range()
    for field in fields:field.sigValueChanging.connect(manual)
    custom.clicked.connect(lambda checked: (use_axis.setChecked(False),plot.model.set_fit_domain_enabled(checked)))
    use_axis.toggled.connect(lambda checked: custom.setChecked(not checked) if checked else None)
    custom.clicked.connect(sync_range)
    # Independent result notebook already owns one tab per saved fit.
    titles=['拟合函数','参数与执行','拟合结果','拟合范围','误差棒']
    fit.sections.sort(key=lambda r:titles.index(r[1].property('sectionTitle')) if r[1].property('sectionTitle') in titles else len(titles))
    for i,record in enumerate(fit.sections):
        fit.open_layout.removeWidget(record[0]);fit.open_layout.insertWidget(i,record[0])
    peaks.sync()
    refresh_results(plot)


def result_sources(plot):
    host=getattr(plot,'_fit_host',plot)
    return list(host.model._plots) if host.presentation.multi else [plot]


def set_source_enabled(source,enabled):
    source.fit_range_row.setEnabled(enabled)
    source.fit_model_row.setEnabled(enabled)
    for record in source.fit_actions.page.sections:
        if record[1].property('sectionTitle') not in {'拟合结果','置信带与预测带'}:record[3].setEnabled(enabled)
    if enabled:source.preset_controls.sync_model()
    else:
        with QtCore.QSignalBlocker(source.preset_controls.selector):
            source.preset_controls.selector.setCurrentIndex(0)
    if hasattr(source,'error_controls'):
        if enabled:source.error_controls.sync()
        else:
            for box in (source.error_controls.x,source.error_controls.y):
                with QtCore.QSignalBlocker(box):box.setCurrentIndex(max(0,box.findData(None)))


def refresh_results(plot):
    if not hasattr(plot,'fit_result_choice'):return
    from tailor.column_titles import display
    choice=plot.fit_result_choice
    selected=plot.fit_actions.current()
    host=getattr(plot,'_fit_host',plot)
    if not host.presentation.multi:
        selector=plot.fit_curve_choice
        chosen=selector.currentData()
        from tailor.choice_catalog import source_visible
        with QtCore.QSignalBlocker(selector):
            selector.clear();selector.addItem('—',None)
            if source_visible(plot,plot):selector.addItem(display(plot.data_sheet.model,plot.model.y_col),plot)
            selector.setCurrentIndex(max(0,selector.findData(chosen)))
        enabled = selector.currentData() is plot
        if plot.fit_range_row.isEnabled() != enabled:
            set_source_enabled(plot, enabled)
    with QtCore.QSignalBlocker(choice):
        choice.clear();choice.addItem('—',None)
        from tailor.choice_catalog import fit_entries
        for source,record,caption in fit_entries(plot):
            choice.addItem(caption,(source,record['id']))
            if source is plot and selected is record:choice.setCurrentIndex(choice.count()-1)
    visible_selected=selected is not None and choice.currentData() is not None
    if selected is not None and not visible_selected:
        plot.fit_actions.current_id=plot.fit_actions.modify_id=None
        if plot._fit_job is None:plot.ui.fit_button.setText('执行拟合')
    plot.fit_open_result.setEnabled(visible_selected)
    plot.fit_actions.actions.sync()


def choose_result(plot,index):
    selected=plot.fit_result_choice.itemData(index)
    if selected is None:
        plot.fit_actions.modify_id=plot.fit_actions.current_id=None
        host=getattr(plot,'_fit_host',plot)
        host.curve_selection.select(None)
        plot.fit_actions.sync()
        return
    source,identifier=selected
    host=getattr(plot,'_fit_host',plot)
    def select():
        if getattr(source,'_inspector_initializing',False):
            QtCore.QTimer.singleShot(30,plot,select)
            return
        if host.presentation.multi:source._fit_host=host
        source.fit_actions.select(identifier,edit=True)
    select()


def open_result(plot):
    record=plot.fit_actions.current()
    if record is not None:
        from tailor.fit_results import show_result
        show_result(plot,record)


class FitRouter(QtWidgets.QWidget):
    def __init__(self,graph):
        super().__init__(graph)
        self.graph=graph;self.bound={}
        layout=QtWidgets.QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
        self.choice=QtWidgets.QComboBox()
        header=QtWidgets.QWidget(self)
        header_layout=QtWidgets.QVBoxLayout(header)
        header_layout.setContentsMargins(20,4,18,0)
        header_layout.setSpacing(6)
        from tailor.workflow_header import header_row
        header_layout.addWidget(header_row('选择曲线',self.choice))
        layout.addWidget(header)
        self.stack=QtWidgets.QStackedWidget();layout.addWidget(self.stack)
        self.choice.activated.connect(lambda *args:self.choose(force=True))
        graph.property_tabs.currentChanged.connect(self.activate)
        self.refresh()

    def refresh(self):
        from tailor.column_titles import display
        old=self.choice.currentData()
        with QtCore.QSignalBlocker(self.choice):
            self.choice.clear()
            self.choice.addItem('—',None)
            from tailor.choice_catalog import sorted_sources
            for source in sorted_sources(self.graph):
                labels=list(source.data_sheet.model.columnLabels())
                if source.model.y_col not in labels:continue
                meta=source.data_sheet.model.column_metadata(labels.index(source.model.y_col))
                if meta.get('source','').startswith('fit:'):continue
                self.choice.addItem(display(source.data_sheet.model,source.model.y_col),source)
            current=getattr(self.graph.curve_selection,'current',None) if hasattr(self.graph,'curve_selection') else None
            wanted=old or current
            index=self.choice.findData(wanted)
            if wanted is None and self.choice.count()==2:index=1
            self.choice.setCurrentIndex(max(0,index))
        self.choose()

    def activate(self,*args):
        if self.graph.property_tabs.currentWidget() is self:
            self.choose(force=True)

    def displayed(self):
        root=self.graph
        while getattr(root,'_inset_parent',None) is not None or getattr(root,'_embedded_parent',None) is not None:
            root=getattr(root,'_inset_parent',None) or root._embedded_parent
        return root.main_window.ui.tabWidget.currentWidget() is root

    def choose(self,*args,force=False):
        if not force and not self.displayed():return
        if not force:
            # Creating or refreshing an inactive inset must never steal the
            # parent's live fitting page or replace its viewport context.
            if self.graph.property_tabs.currentWidget() is not self:return
        source=self.choice.currentData()
        enabled=source is not None
        if source is None:source=self.choice.itemData(1) if self.choice.count()>1 else None
        if source is None:return
        if getattr(source,'_inspector_initializing',False):
            # A delayed request belongs to the visible document, not to an
            # inspector that was active before a rapid graph/tab switch.
            QtCore.QTimer.singleShot(30,self,lambda:self.choose(force=force) if self.displayed() else None);return
        source._fit_host=self.graph
        page=source.fit_actions.page
        if self.stack.indexOf(page)<0:
            self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)
        source.fit_curve_choice.parentWidget().hide()
        source.fit_header.layout().setContentsMargins(20,6,18,4)
        set_source_enabled(source,enabled)
        bands=getattr(getattr(self.graph,'extras',None),'bands',None)
        if bands is not None:bands.mount(page)
        refresh_results(source)
        if source not in self.bound:
            source.data_refreshed.connect(self.graph.queue_source_draw)
            source.labels_refreshed.connect(self.refresh)
            self.bound[source]=True

    def select_source(self,source):
        index=self.choice.findData(source)
        if index>=0:self.choice.setCurrentIndex(index);self.choose(force=True)


def fit_owner(graph,key):
    if not graph.presentation.multi:
        if key=='fit':return graph,graph.active_fit_id
        if key.startswith('fit:'):
            try:return graph,int(key.split(':')[1])
            except ValueError:return None
        if key.startswith('component:'):return graph,graph.active_fit_id
    parts=key.split(':')
    if len(parts)>=3 and parts[0]=='plot' and parts[2]=='fit':
        source=next((s for s in graph.model._plots if str(s.id)==parts[1]),None)
        if source is not None:
            return source,int(parts[3]) if len(parts)>3 else source.active_fit_id
    return None


def pick(graph,key,item,event=None):
    target=fit_owner(graph,key)
    if not target:return False
    from tailor.point_inspector import intercept_curve
    if intercept_curve(graph, key, event):return True
    if graph.preferences.preference_mode() is not None:
        if event is not None:graph.curve_selection._handled_click=event
        graph.preferences.select_curve('drawn',key,True)
        return True
    source,result_id=target
    if event is not None:graph.curve_selection._handled_click=event
    if result_id is None:return False
    from tailor.manual_peaks import picking
    if picking(graph):return True
    if graph.presentation.multi:
        graph.fit_router.select_source(source)
        source._fit_host=graph
    source.fit_actions.select(result_id,edit=True)
    from tailor.preference_pages import available_curves
    if not (key.startswith('component:') or ':component:' in key):
        key = f'plot:{source.id}:fit' if graph.presentation.multi else 'fit'
    item=available_curves(graph).get(key,(item,None))[0]
    graph._selected_drawn_key=key
    graph.annotations.select(None);graph.text_selection.select(None)
    graph.curve_selection.current=None;graph.curve_selection.override_item=item;graph.curve_selection.refresh()
    graph.preferences.curve_target=('drawn',key)
    graph.preferences._curve_allowed=True
    graph.preferences.refresh_targets()
    graph.preferences.sync_curve_context('drawn',key)
    if graph.presentation.multi:
        graph.property_tabs.setCurrentWidget(graph.fit_router)
    return True


def mirror_results(graph):
    import numpy as np
    import pyqtgraph as pg
    from tailor.series_colors import fit_colour
    registry=getattr(graph,'_fit_mirrors',{})
    graph._fit_mirrors=registry
    wanted=set()
    for source,info in graph.model._plots.items():
        series=graph._series.get(source)
        if not series:continue
        box=series['box']
        for record in source.fit_records:
            if record['id']==source.active_fit_id:continue
            key=f"plot:{source.id}:fit:{record['id']}";wanted.add(key)
            if key not in registry:
                item=pg.PlotDataItem(pen=pg.mkPen(info.color,width=derived_width(graph)))
                item._legend_key=key;item.setZValue(11 if ':component:' in key else 10);box.addItem(item);registry[key]=(item,box)
            elif registry[key][1] is not box:
                item,previous=registry[key];previous.removeItem(item);box.addItem(item);registry[key]=(item,box)
            item=registry[key][0];item.setData(record['curve_x'],record['curve_y'],pen=pg.mkPen(fit_colour(graph,source,record['id']),width=derived_width(graph)))
            item.setLogMode(graph.presentation.axes['top' if info.x_axis=='top' else 'x']['log'],graph.presentation.axes['right' if info.axis=='right' else 'y']['log'])
            item.setVisible(info.visible and not record.get('hidden',False))
            graph.presentation.legend_item.addItem(item,record['name'])
        for i,component in enumerate(getattr(source,'_component_curves',[]),1):
            if source.active_fit_id is None:continue
            key=f'plot:{source.id}:fit:{source.active_fit_id}:component:{i}';wanted.add(key)
            if key not in registry:
                item=pg.PlotDataItem(pen=pg.mkPen(info.color,width=derived_width(graph),style=QtCore.Qt.DashLine))
                item._legend_key=key;item.setZValue(11 if ':component:' in key else 10);box.addItem(item);registry[key]=(item,box)
            elif registry[key][1] is not box:
                item,previous=registry[key];previous.removeItem(item);box.addItem(item);registry[key]=(item,box)
            item=registry[key][0]
            item.setData(component.xData,component.yData,pen=pg.mkPen(fit_colour(graph,source,source.active_fit_id,i),width=derived_width(graph),style=QtCore.Qt.DashLine))
            item.setLogMode(graph.presentation.axes['top' if info.x_axis=='top' else 'x']['log'],graph.presentation.axes['right' if info.axis=='right' else 'y']['log'])
            active=next((r for r in source.fit_records if r['id']==source.active_fit_id),{})
            item.setVisible(info.visible and not active.get('hidden',False))
            from tailor.fit_results import curve_column
            from tailor.column_titles import remark
            column = curve_column(active, key)
            caption = remark(source.data_sheet.model, column) if column in source.data_sheet.model.columnLabels() else f'分峰{i}'
            graph.presentation.legend_item.addItem(item, caption)
    for key in list(registry):
        if key not in wanted:
            item,box=registry.pop(key);box.removeItem(item)

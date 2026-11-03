"""Selectable result information, rendered through Qt into existing image annotations."""
import base64
import json
import math
import weakref

import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets


class ResultViewBox(pg.ViewBox):
    def wheelEvent(self, event, axis=None):
        event.ignore()


def result_plot():
    return pg.PlotWidget(viewBox=ResultViewBox())


def value_text(value):
    if value is None:
        return '—'
    if isinstance(value, (float, int)):
        return f'{value:.7g}' if math.isfinite(value) else '—'
    return str(value)


def fit_rows(record,language='zh'):
    from tailor.fit_results import parameter_label
    from tailor.analysis_units import parameter_unit
    from tailor.text_layout import plain_text
    cfg, stats = record['settings'], record['statistics']
    domain = '全部有效数据' if not cfg['use_domain'] else f"{value_text(cfg['domain'][0])} ≤ X ≤ {value_text(cfg['domain'][1])}"
    rows = [
        ('model','拟合模型',record['title'],True),
        ('equation','拟合方程',plain_text(record['expression']),True),
        ('source','数据来源',f"{record['x_name']} → {record['y_name']}",True),
        ('range','拟合范围',domain,False),
        ('status','结果状态','源数据已改变，需重新拟合' if record['stale'] else '拟合完成',True),
        ('created','完成时间',record['created'],False),
        ('n','有效点数',value_text(stats['ndata']),True),
    ]
    for key, parameter in record['parameters'].items():
        unit = parameter.get('unit',parameter_unit(cfg['preset'],key,record['units']))
        value = f"{value_text(parameter['value'])} ± {value_text(parameter['stderr'])}"
        if unit:
            value += ' ' + unit
        if not parameter['vary']:
            value += '（固定）'
        rows.append(('parameter:'+key,parameter_label(key,cfg['preset']),value,True))
    for key,label in [('r2','R²'),('adjusted_r2','调整 R²'),('rmse','RMSE'),('sse','残差平方和'),('nvarys','自由参数')]:
        rows.append((key,label,value_text(stats.get(key)),key in {'r2','adjusted_r2'}))
    weighted = bool(cfg['columns'][3])
    variance=value_text(record['redchi'])
    if not weighted and record['units'].get('y'):
        variance+=' '+record['units']['y']+'²'
    rows += [('weight','拟合权重','使用 Y 误差加权' if weighted else '未加权',False),
             ('dof','自由度',value_text(stats['ndata']-stats['nvarys']),False),
             ('redchi','约化 χ²' if weighted else '残差方差',variance,weighted),
             ('evaluations','评估次数',value_text(record['nfev']),False),
             ('message','收敛信息',str(record.get('message','—')),False)]
    for key,value in record.get('features',{}).items():
        unit=parameter_unit(cfg['preset'],key,record['units'])
        rows.append(('feature:'+key,parameter_label(key),value_text(value)+(' '+unit if unit else ''),True))
    if language=='en':
        from tailor.result_language import fit_rows_english
        return fit_rows_english(rows,record)
    return rows


def processing_rows(tab,language='zh'):
    from tailor.column_analysis import STATISTICS
    from tailor.column_titles import display
    rows=[]
    for line in tab.details.text().splitlines():
        if '：' in line:
            label,value=line.split('：',1)
            chosen=label!='状态' and (label!='方法' or value!=tab.record['recipe']['title'])
            rows.append(('context:'+label,label,value or '—',chosen))
    metric_names=set(STATISTICS.values())|{'积分','斜率','截距','R²','斜率标准误','起点X','终点X','有效点数'}
    for sheet,key,slot,*_ in tab.record['outputs']:
        metadata=sheet.model.column_metadata(list(sheet.model.columnLabels()).index(key))
        source=json.loads(metadata.get('source') or '{}')
        label=slot.split(':',2)[-1]
        scalar=source.get('scalar',source.get('type')=='statistics' or label in metric_names)
        title=display(sheet.model,key)
        unit=metadata.get('unit','')
        values=sheet.model.data_model.get_column(key)
        text=value_text(values[0] if len(values) else None) if scalar else title
        if scalar and unit:
            text+=' '+unit
        rows.append(('output:'+key,title if scalar else '结果列',text,scalar))
        counts=source.get('counts',{})
        if counts:
            text='；'.join(label+' '+str(counts.get(k,'—')) for k,label in [('valid','有效'),('missing','缺失'),('excluded','排除')])
            rows.append(('counts:'+key,title+' · 计数',text,False))
    if language=='en':
        from tailor.result_language import processing_rows_english
        return processing_rows_english(rows,tab)
    return rows


def processing_method_title(method):
    from tailor.column_analysis import PREPROCESS,MATHEMATICS,SIGNALS,REGIONS
    from tailor.envelope_analysis import ENVELOPES
    names={key:title for title,key in [*PREPROCESS,*MATHEMATICS,*SIGNALS,*REGIONS,*ENVELOPES]}
    names.update(statistics='描述统计',replicate='重复测量',replicates='重复测量')
    return names.get(method,method)


class ResultInformation(QtWidgets.QTableWidget):
    informationChanged=QtCore.Signal()
    def __init__(self, kind, parent=None):
        super().__init__(0,2,parent)
        self.kind=kind
        self.language='zh'
        self.provider=None
        self.choices={}
        self.rows=[]
        self.setHorizontalHeaderLabels(['图中信息','内容'])
        self.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.setAlternatingRowColors(True)
        self.setWordWrap(True)
        self.verticalHeader().hide()
        self.horizontalHeader().setSectionResizeMode(0,QtWidgets.QHeaderView.Interactive)
        self.horizontalHeader().setSectionResizeMode(1,QtWidgets.QHeaderView.Stretch)
        self.setColumnWidth(0,190)
        self.itemChanged.connect(self.changed)
        self.setMinimumHeight(240)

    def set_language(self,language):
        self.language='en' if language=='en' else 'zh'
        self.setHorizontalHeaderLabels(['Graph information','Value'] if self.language=='en' else ['图中信息','内容'])
        if self.provider is not None:self.set_rows(self.provider(self.language))

    def changed(self,item):
        if item.column()==0:
            before=dict(self.choices)
            self.choices[item.data(QtCore.Qt.UserRole)]=item.checkState()==QtCore.Qt.Checked
            owner=getattr(self,'owner',None)
            if owner is not None and before!=self.choices:
                from tailor.spreadsheet_model import Edit
                import shiboken6
                ref=weakref.ref(self)
                def apply(choices):
                    target=ref()
                    if target is not None and shiboken6.isValid(target):
                        target.choices=dict(choices);target.set_rows(target.rows)
                after=dict(self.choices)
                sheets=owner.get_data_sheets()
                if sheets:
                    sheets[0].model._record(Edit('结果信息选择',lambda:apply(before),lambda:apply(after),4096))
            self.informationChanged.emit()

    def set_rows(self,rows):
        # Source/status notifications can arrive on every view-range change.
        # Rebuilding identical tables creates more layout/range notifications
        # and can keep a restored graph busy indefinitely.
        if rows==self.rows and self.rowCount()==len(rows):
            changed=False
            with QtCore.QSignalBlocker(self):
                for row,(key,_,_,default) in enumerate(rows):
                    state=QtCore.Qt.Checked if self.choices.get(key,default) else QtCore.Qt.Unchecked
                    if self.item(row,0).checkState()!=state:
                        self.item(row,0).setCheckState(state);changed=True
            if changed:self.informationChanged.emit()
            return
        self.rows=list(rows)
        with QtCore.QSignalBlocker(self):
            self.setRowCount(len(rows))
            for row,(key,label,value,default) in enumerate(rows):
                name=QtWidgets.QTableWidgetItem(label)
                name.setData(QtCore.Qt.UserRole,key)
                name.setFlags(name.flags()|QtCore.Qt.ItemIsUserCheckable)
                name.setCheckState(QtCore.Qt.Checked if self.choices.get(key,default) else QtCore.Qt.Unchecked)
                self.setItem(row,0,name)
                self.setItem(row,1,QtWidgets.QTableWidgetItem(str(value)))
            self.resizeRowsToContents()
        self.informationChanged.emit()

    def selected_rows(self):
        return [(label,str(value)) for row,(_,label,value,_) in enumerate(self.rows)
                if self.item(row,0).checkState()==QtCore.Qt.Checked]

    def image(self):
        rows=self.selected_rows()
        if not rows:
            raise ValueError('请先勾选要添加到图中的信息。')
        width=640
        font=QtGui.QFont(QtWidgets.QApplication.font());font.setPointSize(12);font.setBold(False)
        documents=[]
        for label,value in rows:
            left,right=QtGui.QTextDocument(),QtGui.QTextDocument()
            for doc,text,w in [(left,label,175),(right,value,405)]:
                doc.setDefaultFont(font);doc.setDocumentMargin(0)
                doc.setPlainText(text);doc.setTextWidth(w)
            documents.append((left,right,max(32,int(max(left.size().height(),right.size().height()))+16)))
        height=74+sum(row[2] for row in documents)+16
        if height>10000:
            raise ValueError('所选信息过长，请减少勾选项后分次添加。')
        result=QtGui.QImage(width*2,height*2,QtGui.QImage.Format_ARGB32_Premultiplied)
        result.fill(QtCore.Qt.transparent)
        painter=QtGui.QPainter(result);painter.scale(2,2)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        color='#2878cc' if self.kind=='拟合结果' else '#8b5ac5'
        painter.setPen(QtGui.QPen(QtGui.QColor('#d5dfea'),1))
        painter.setBrush(QtGui.QColor('#ffffff'));painter.drawRoundedRect(QtCore.QRectF(.5,.5,width-1,height-1),14,14)
        painter.setPen(QtCore.Qt.NoPen);painter.setBrush(QtGui.QColor('#edf3fb' if self.kind=='拟合结果' else '#f3edfb'))
        painter.drawRoundedRect(QtCore.QRectF(12,12,width-24,46),9,9)
        title=QtGui.QFont(font);title.setPointSize(15);title.setBold(True)
        painter.setFont(title);painter.setPen(QtGui.QColor(color))
        title_text=({'拟合结果':'Fit results','处理结果':'Processing results'}.get(self.kind,self.kind)
                    if self.language=='en' else self.kind)
        painter.drawText(QtCore.QRectF(28,12,width-56,46),QtCore.Qt.AlignVCenter,title_text)
        y=70
        for index,(left,right,h) in enumerate(documents):
            if index%2==0:
                painter.fillRect(QtCore.QRectF(16,y,width-32,h),QtGui.QColor('#f6f8fc'))
            for doc,x,foreground in [(left,28,'#596d87'),(right,215,'#27364a')]:
                painter.save();painter.translate(x,y+8)
                context=QtGui.QAbstractTextDocumentLayout.PaintContext()
                context.palette.setColor(QtGui.QPalette.Text,QtGui.QColor(foreground))
                doc.documentLayout().draw(painter,context);painter.restore()
            y+=h
        painter.end()
        return result


def graph_documents(owner):
    return [doc for doc in [owner.ui.tabWidget.widget(i) for i in range(owner.ui.tabWidget.count())]
            if hasattr(doc,'presentation') and not getattr(doc,'_hidden_curve_source',False)
            and not hasattr(doc,'_inset_parent')]


def add_image_to_graph(owner,graph,information):
    advanced=getattr(graph,'advanced_view',None)
    if advanced is not None and advanced.cfg.get('kind')=='3d':
        raise ValueError('当前三维图不支持图片标注，请选择普通图、柱状图或组图。')
    native=getattr(advanced,'native',None)
    target=native.current() if native is not None else graph
    if target is None:
        raise ValueError('请先显示目标图后再添加结果信息。')
    image=information.image()
    data=QtCore.QByteArray();buffer=QtCore.QBuffer(data);buffer.open(QtCore.QIODevice.WriteOnly)
    if not image.save(buffer,'PNG'):
        raise ValueError('无法生成结果信息图片。')
    buffer.close()
    annotations=target.annotations
    annotations._new_image_data=base64.b64encode(bytes(data)).decode('ascii')
    try:
        view=target.ui.plot_widget.viewport()
        aspect=image.height()/image.width()*max(1,view.width())/max(1,view.height())
        width=min(.42,.65/max(aspect,1e-9));height=width*aspect
        key=annotations.add('image','canvas',[.97-width,.97-height,.97,.97])
    finally:
        del annotations._new_image_data
    if hasattr(owner,'projects'):
        owner.projects.activate(owner)
    owner.ui.tabWidget.setCurrentWidget(graph)
    mode=getattr(owner,'window_mode',None)
    if mode and mode.enabled and not getattr(graph,'advanced_view',None):
        mode.show(graph)
    return key

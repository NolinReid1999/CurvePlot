"""Explicit saved-fit export using existing CSV snapshot/background writers."""
import copy
from pathlib import Path

import numpy as np
from PySide6 import QtCore, QtWidgets

from tailor.compact_controls import toggle_button
from tailor.fold_panel import stack
from tailor.graph_controls import row


class FitExportControls(QtCore.QObject):
    def __init__(self,plot,panel):
        super().__init__(plot)
        self.plot=plot;self.bound=set()
        self.save_project=QtWidgets.QPushButton('保存工程（.cur）')
        self.save_project.clicked.connect(lambda:plot.main_window.save_project_or_dialog())
        self.choice=QtWidgets.QComboBox();self.choice.addItem('—',None)
        self.all=toggle_button('全部')
        self.all.setFixedWidth(56)
        self.choice.setMinimumWidth(0)
        self.choice.setSizePolicy(QtWidgets.QSizePolicy.Ignored,QtWidgets.QSizePolicy.Fixed)
        self.all.clicked.connect(self.sync_enabled)
        self.choice.activated.connect(self.sync_enabled)
        layout=QtWidgets.QVBoxLayout();layout.addWidget(row('拟合选择',self.choice,self.all))
        buttons=[]
        for title,kind in [('复制结果','copy'),('参数 CSV','parameters'),('残差 CSV','residuals')]:
            button=QtWidgets.QPushButton(title)
            button.clicked.connect(lambda checked=False,k=kind:self.export(k));buttons.append(button)
        self.buttons=buttons;layout.addWidget(row(*buttons))
        panel.add_section('导出拟合结果',layout)
        self.data=QtWidgets.QPushButton('导出所有数据 CSV…')
        self.data.clicked.connect(self.export_data)
        panel.add_section('导出数据',stack(self.data))
        panel.add_section('保存工程',stack(self.save_project),True)
        self.timer=QtCore.QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(30)
        self.timer.timeout.connect(self.refresh)
        plot.property_tabs.currentChanged.connect(self.schedule)
        self.refresh()

    def entries(self):
        from tailor.fit_workflow import result_sources
        from tailor.column_titles import display
        entries={}
        from tailor.choice_catalog import fit_entries
        for source,record,title in fit_entries(self.plot):
            model=source.data_sheet.model
            if id(model) not in self.bound:
                self.bound.add(id(model))
                model.headerDataChanged.connect(self.schedule)
                model.historyChanged.connect(self.schedule)
            entries[f'{source.id}:{record["id"]}']=(source,record,title)
        return entries

    @QtCore.Slot()
    def schedule(self,*args):
        if not getattr(self.plot,'_graph_disposed',False):self.timer.start()

    @QtCore.Slot()
    def refresh(self,*args):
        if getattr(self.plot,'_graph_disposed',False):return
        entries=self.entries();selected=self.choice.currentData()
        with QtCore.QSignalBlocker(self.choice):
            self.choice.clear();self.choice.addItem('—',None)
            for key,(_,_,title) in entries.items():self.choice.addItem(title,key)
            self.choice.setCurrentIndex(max(0,self.choice.findData(selected)))
        self.sync_enabled()

    def selected(self):
        entries=self.entries()
        return list(entries.values()) if self.all.isChecked() else ([entries[self.choice.currentData()]] if self.choice.currentData() in entries else [])

    def sync_enabled(self,*args):
        self.choice.setEnabled(not self.all.isChecked())
        for button in self.buttons:button.setEnabled(bool(self.selected()))

    def columns(self,kind):
        selected=self.selected()
        rows=[]
        if kind=='parameters':
            for source,record,title in selected:
                values={key:(p['value'],p.get('stderr')) for key,p in record['parameters'].items()}
                values.update({key:(value,None) for key,value in record.get('features',{}).items() if value is None or isinstance(value,(int,float))})
                for name,(value,stderr) in values.items():
                    from tailor.analysis_units import parameter_unit
                    unit=record['parameters'].get(name,{}).get('unit',parameter_unit(record['settings']['preset'],name,record['units']))
                    rows.append((title,record['expression'],name,value,np.nan if stderr is None else stderr,unit,record.get('stale',False)))
            names=('fit','model','parameter','value','stderr','unit','stale')
        else:
            from tailor.fit_results import StoredFit,fit_frame,record_source_hash
            names=('fit','worksheet','source_row','x','y','y_fit','residual_y_minus_fit')
            pieces={name:[] for name in names}
            for source,record,title in selected:
                if record.get('stale') or record_source_hash(source.model,record)!=record['source_hash']:
                    raise ValueError('拟合已过期，不能用当前数据替代原残差；请重新拟合后导出。')
                model=copy.copy(source.model);cfg=record['settings']
                model.x_col,model.y_col,model.x_err_col,model.y_err_col=cfg['columns']
                model._fit_domain=tuple(cfg['domain']);model._use_fit_domain=cfg['use_domain']
                frame=fit_frame(model);fit=StoredFit(record,model)
                x,y=frame.x.to_numpy(),frame.y.to_numpy()
                predicted=np.asarray(fit.eval(**{model.x_col:x}),dtype=float)
                columns=(np.full(len(frame),title,dtype=object),np.full(len(frame),source.data_sheet.name,dtype=object),
                         frame.index.to_numpy(dtype=np.int64)+1,x.copy(),y.copy(),predicted,y-predicted)
                for name,values in zip(names,columns):pieces[name].append(values)
            return {name:np.concatenate(parts) if parts else np.array([]) for name,parts in pieces.items()}
        # Keep each column's type; a mixed numpy matrix would stringify numbers.
        return {name:np.asarray([row[i] for row in rows]) for i,name in enumerate(names)}

    def export(self,kind):
        if not self.selected():return
        if kind=='copy':
            from tailor.fit_results import record_text
            QtWidgets.QApplication.clipboard().setText('\n\n'.join(title+'\n'+record_text(record) for _,record,title in self.selected()))
            return
        from tailor.app_preferences import preferences
        folder=preferences().get('export/directory') or self.plot.main_window.get_recent_directory()
        filename,_=QtWidgets.QFileDialog.getSaveFileName(self.plot,'导出拟合结果',str(folder),'CSV (*.csv)')
        if not filename:return
        try:columns=self.columns(kind)
        except (ValueError,KeyError,TypeError) as error:
            self.plot.main_window.statusBar().showMessage(str(error));return
        path=Path(filename)
        if not path.suffix:path=path.with_suffix('.csv')
        self.plot.main_window.start_csv_snapshot_export(columns,path)

    def export_data(self):
        sheets=self.plot.main_window.get_data_sheets()
        if not sheets:return
        from tailor.app_preferences import preferences
        folder=preferences().get('export/directory') or self.plot.main_window.get_recent_directory()
        filename,_=QtWidgets.QFileDialog.getSaveFileName(self.plot,'导出所有数据',str(folder),'CSV (*.csv)')
        if filename:
            path=Path(filename)
            if not path.suffix:path=path.with_suffix('.csv')
            self.plot.main_window.start_csv_export(sheets[0],path)

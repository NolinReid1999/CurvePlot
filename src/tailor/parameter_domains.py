"""Small asynchronous domain summaries; numeric source data is never modified."""
import numpy as np
import shiboken6
from PySide6 import QtCore


class DomainSignals(QtCore.QObject):
    ready=QtCore.Signal(object,object)


class DomainJob(QtCore.QRunnable):
    def __init__(self,token,arrays,signals):
        super().__init__();self.token,self.arrays,self.signals=token,arrays,signals
    def run(self):
        result=[]
        for array in self.arrays:
            if np.asarray(array).dtype.kind in 'iufb':
                data=np.asarray(array,dtype=float)
            else:
                import pandas as pd
                data=np.asarray(pd.to_numeric(array,errors='coerce'),dtype=float)
            data=data[np.isfinite(data)]
            if len(data):
                spacing=float(np.median(np.abs(np.diff(data)))) if len(data)>1 else 0
                result.append((float(data.min()),float(data.max()),len(data),spacing))
            else:result.append((0.,1.,0,0.))
        try:self.signals.ready.emit(self.token,result)
        except RuntimeError:pass


def source_for(plot):
    if not plot.presentation.multi:return plot
    manager=getattr(plot,'curve_manager',None)
    return manager.current_plot() if manager and manager.current_plot() is not None else next(iter(plot.model._plots),None)


class Domains(QtCore.QObject):
    def __init__(self,parent,source,apply):
        super().__init__(parent);self.source,self.apply=source,apply
        self.revision=0;self.cache=None;self.token=None;self.pending=None
        self.signals=DomainSignals(self);self.signals.ready.connect(self.finished)
        self.timer=QtCore.QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(80);self.timer.timeout.connect(self.capture)
        self.request()
    def invalidate(self,*args):
        self.revision+=1;self.cache=None;self.request()
    def request(self,*args):
        if not self.timer.isActive():self.timer.start()
    def capture(self):
        source=self.source()
        if source is None or not shiboken6.isValid(source) or getattr(source,'_graph_disposed',False):return
        token=(self.revision,source.id,source.model.x_col,source.model.y_col)
        if token==self.token and self.cache is not None:
            self.apply(self.cache,source);return
        if token==self.pending:return
        bound=getattr(self,'_bound_sources',set())
        if source.id not in bound and hasattr(source,'data_refreshed'):
            source.data_refreshed.connect(self.invalidate);bound.add(source.id);self._bound_sources=bound
        self.pending=token;self._capture_source=source;self._arrays=[]
        # Copy one source column per event-loop turn; scans run on the pool.
        self.copy_column(token,0)
    def copy_column(self,token,index):
        if not shiboken6.isValid(self) or token!=self.pending:return
        source=self._capture_source
        if not shiboken6.isValid(source) or getattr(source,'_graph_disposed',False):
            self.pending=None;return
        try:
            key=source.model.x_col if index==0 else source.model.y_col
            self._arrays.append(np.array(source.model.data_model.get_column(key),copy=True))
        except (KeyError,RuntimeError):self.pending=None;return
        if index==0:
            QtCore.QTimer.singleShot(0,self,lambda:self.copy_column(token,1))
        else:
            QtCore.QThreadPool.globalInstance().start(DomainJob(token,self._arrays,self.signals))
    def finished(self,token,result):
        if token!=self.pending:return
        self.pending=None
        if token[0]!=self.revision:self.request();return
        source=self.source()
        if source is None or not shiboken6.isValid(source) or getattr(source,'_graph_disposed',False):return
        if (source.id,source.model.x_col,source.model.y_col)!=token[1:]:self.request();return
        self.token,self.cache=token,result;self.apply(result,source)


def limit(field,low,high,step=None,preserve=True):
    # Preserve an explicitly stored value from an older project, without
    # silently rewriting its settings while the background summary arrives.
    with QtCore.QSignalBlocker(field):
        if preserve:high=max(high,field.value())
        field.setRange(low,high)
        if step is not None:field.setSingleStep(step)


def axis_source(control):
    plot=control.plot
    if not plot.presentation.multi:return plot
    key=control.current
    selected=getattr(getattr(plot,'curve_selection',None),'current',None)
    candidates=[]
    for source,info in plot.model._plots.items():
        if not info.visible:continue
        matches=(info.x_axis==('top' if key=='top' else 'bottom')) if key in {'x','top'} else (info.axis==('right' if key=='right' else 'left'))
        if matches:candidates.append(source)
    return selected if selected in candidates else next(iter(candidates),None)


class AxisDomains(Domains):
    def __init__(self,control):
        self.control=control
        super().__init__(control,lambda:axis_source(control),self.adapt)
        if hasattr(control.plot,'data_refreshed'):control.plot.data_refreshed.connect(self.invalidate)
        self.view_timer=QtCore.QTimer(self);self.view_timer.setSingleShot(True);self.view_timer.setInterval(16)
        self.view_timer.timeout.connect(self.refresh_range)
        self._bound_boxes=set();self.bind_views()
        control.tick_pair.sources[0]._auto_step_base=lambda:__import__('tailor.axis_tick_policy',fromlist=['auto_spacing']).auto_spacing(control)
        self.refresh_range()

    def bind_views(self):
        p=self.control.plot.presentation
        boxes=[self.control.plot.ui.plot_widget.getViewBox(),getattr(p,'right_box',None),getattr(p,'top_box',None)]
        for box in boxes:
            if box is not None and box not in self._bound_boxes:
                box.sigRangeChanged.connect(self.range_changed);self._bound_boxes.add(box)

    def range_changed(self,*_):
        if not self.view_timer.isActive():self.view_timer.start()

    def refresh_range(self):
        c=self.control
        if getattr(c.plot,'_graph_disposed',False) or not shiboken6.isValid(c.plot):return
        from tailor.axis_tick_policy import current_bounds,interval_step,decimal_places,auto_spacing,follows_interval,label_precision,numeric_spacing
        self.bind_views()
        low,high=current_bounds(c);span=high-low
        if not np.isfinite(span) or span<=0:return
        if not getattr(c.tick_pair,'quantity_mode',False):
            field=c.tick_pair.sources[0];step=interval_step(span)
            with QtCore.QSignalBlocker(field):
                field.setDecimals(min(15,max(6,decimal_places(step),decimal_places(field.value()))))
                field.setRange(-1,max(span,field.value(),step));field.setSingleStep(step)
            field._slider_domain=(float(step),float(max(span,step)*1.000000000001),False)
        cfg=c.plot.presentation.axes[c.current]
        if follows_interval(cfg) and cfg.get('axis_type','numeric')=='numeric' and not cfg.get('custom_ticks') and not cfg.get('log'):
            spacing=cfg.get('major') or auto_spacing(c)
            from tailor.axis_tick_policy import display_format,decimal_places
            if cfg.get('smart_notation') and decimal_places(numeric_spacing(cfg,spacing,low))<=12:
                cfg['notation']='fixed';cfg['smart_notation']=False
                with QtCore.QSignalBlocker(c.notation):c.notation.setCurrentIndex(c.notation.findData('fixed'))
            formatted=display_format(cfg,numeric_spacing(cfg,spacing,low))
            if formatted['notation']!=cfg['notation']:
                cfg['notation']=formatted['notation'];cfg['smart_notation']=True
                with QtCore.QSignalBlocker(c.notation):c.notation.setCurrentIndex(c.notation.findData(cfg['notation']))
            precision=label_precision(cfg,numeric_spacing(cfg,spacing,low),high)
            cfg['precision_follow_interval']=True;cfg['precision']=precision
            with QtCore.QSignalBlocker(c.precision):c.precision.setValue(precision)
        c.tick_pair.sync()

    def adapt(self,stats,source):
        c=self.control;index=0 if c.current in {'x','top'} else 1
        lo,hi,count,spacing=stats[index]
        key=source.model.x_col if index==0 else source.model.y_col
        labels=list(source.data_sheet.model.columnLabels())
        unit=source.data_sheet.model.column_metadata(labels.index(key)).get('unit','') if key in labels else ''
        unit=unit or ''
        view=getattr(c.plot,'advanced_view',None)
        if view is not None and view.cfg.get('kind')=='3d':
            refs=view.cfg.get('xyz',[])
            i={'x':0,'y':1,'right':2,'top':2}[c.current]
            if len(refs)>i and refs[i] is not None:
                sid,zkey=refs[i]
                sheet=next((s for s in c.plot.main_window.get_data_sheets() if s.id==sid),None)
                keys=list(sheet.model.columnLabels()) if sheet else []
                if zkey in keys:unit=sheet.model.column_metadata(keys.index(zkey)).get('unit','') or ''
        c.tick_pair.units=['个','个'] if getattr(c.tick_pair,'quantity_mode',False) else [unit,'个'];c.break_pair.units=[unit,unit]
        self.refresh_range()
        limit(c.tick_pair.sources[1],1 if getattr(c.tick_pair,'quantity_mode',False) else -1,max(1,min(count,20)))
        for field in c.grid_pair.sources:limit(field,-1,max(1,min(count,100)))
        c.tick_pair.sync();c.grid_pair.sync();c.break_pair.sync()


def column_unit(source,key):
    keys=list(source.data_sheet.model.columnLabels())
    return str(source.data_sheet.model.column_metadata(keys.index(key)).get('unit','') or '') if key in keys else ''


def set_unit(field,unit):
    field.setProperty('sliderUnit',unit)
    from tailor.compact_controls import Stepper,style_slider_value
    parent=field.parentWidget()
    if isinstance(parent,Stepper):style_slider_value(field,parent,unit)


def install_column_domains(control):
    def adapt(stats,source):
        count=stats[1][2]
        xu,yu=column_unit(source,source.model.x_col),column_unit(source,source.model.y_col)
        for category,options in control.options.items():
            for name,unit in {'step':xu,'region_low':xu,'region_high':xu,'prominence':yu,
                              'cutoff':('Hz' if xu=='s' else '1/'+xu if xu else ''),
                              'cutoff2':('Hz' if xu=='s' else '1/'+xu if xu else '')}.items():
                if name in options:set_unit(options[name],unit)
            if 'value' in options:
                method=control.methods[category].currentData()
                set_unit(options['value'],yu if method=='baseline_constant' else '')
            if 'window' in options:limit(options['window'],1,max(1,count),preserve=False)
            if 'distance' in options:limit(options['distance'],1,max(1,count),preserve=False)
            if stats[0][3]>0:
                nyquist=.5/stats[0][3]
                for name in ('cutoff','cutoff2'):
                    if name in options:limit(options[name],max(nyquist/1e6,1e-9),nyquist*.999,nyquist/1000,preserve=False)
    def source():
        from types import SimpleNamespace
        if control.plot and not control.targets:return source_for(control.plot)
        available=control.sheets()
        selected=next(((available[sid],key) for sid,key in control.targets if sid in available and key in available[sid].model.columnLabels()),None)
        sheet=selected[0] if selected else control.document if not control.plot else source_for(control.plot).data_sheet
        model=sheet.model;keys=list(model.columnLabels())
        if not keys:return None
        y=selected[1] if selected else keys[min(1,len(keys)-1)]
        if control.plot:
            candidates=list(control.plot.model._plots) if control.plot.presentation.multi else [control.plot]
            original=next((s for s in candidates if s.data_sheet is sheet and s.model.y_col==y),None)
            if original:return original
        x=next((key for i,key in enumerate(keys) if model.column_metadata(i).get('role')=='X'),keys[0])
        return SimpleNamespace(id=sheet.id,data_sheet=sheet,model=SimpleNamespace(x_col=x,y_col=y,data_model=model.data_model))
    domains=Domains(control,source,adapt)
    if control.plot:
        if hasattr(control.plot,'data_refreshed'):control.plot.data_refreshed.connect(domains.invalidate)
    else:
        control.document.model.dataChanged.connect(domains.invalidate)
        control.document.model.modelReset.connect(domains.invalidate)
    for sheet in control.sheets().values():
        sheet.model.headerDataChanged.connect(domains.request)
        sheet.model.dataChanged.connect(domains.invalidate)
    return domains

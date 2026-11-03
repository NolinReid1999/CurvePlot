"""Worksheet-backed axis transforms, reusing Tailor columns, plots and undo edits."""
import copy
import json
import numpy as np
from tailor.spreadsheet_model import Edit


def values(expression,array):
    from tailor.tick_expression import parse,calculate
    import asteval
    array=np.asarray(array,dtype=float);valid=np.isfinite(array)
    if not valid.any():raise ValueError('所选列没有有效数值')
    parse(expression);calculate(expression,float(array[valid][0]))
    engine=asteval.Interpreter(minimal=True,symtable={'x':array[valid]})
    with np.errstate(all='ignore'):result=engine(expression)
    if engine.error:raise ValueError('显示调整公式不能用于所选列')
    result=np.asarray(result,dtype=float)
    if result.ndim==0:result=np.full(valid.sum(),float(result))
    if result.shape!=(valid.sum(),) or not np.isfinite(result).all():
        raise ValueError('公式在部分有效数据处无定义或超出数值范围，未生成结果')
    output=np.full(array.shape,np.nan);output[valid]=result
    return output


def graphs(owner):
    result=[owner.ui.tabWidget.widget(i) for i in range(owner.ui.tabWidget.count())]
    from tailor.native_panels import documents
    result.extend(d for d in documents(owner) if d not in result)
    for graph in list(result):
        native=getattr(getattr(graph,'advanced_view',None),'native',None)
        if native:result.extend(d for d in native.live() if d not in result)
    return [g for g in result if hasattr(g,'presentation')]


def clone(source):
    from tailor.project_files import save_plot,load_plot
    owner=source.main_window;owner._plot_num+=1
    model=save_plot(source).model_copy(update={'id':owner._plot_num})
    previous=getattr(owner,'_defer_project_restore',False)
    owner._defer_project_restore=True
    try:result=load_plot(owner,model,source.data_sheet,hidden_source=True)
    finally:owner._defer_project_restore=previous
    result._inspector_timer.start(0)
    owner._axis_owned_sources=getattr(owner,'_axis_owned_sources',[])+[result]
    return result


def source_state(source):
    names=('x_col','y_col','x_err_col','y_err_col','_model_expression','_parameters',
           '_fit_domain','_use_fit_domain','_axis_modes','_fit_data_checksum')
    return ({k:copy.deepcopy(getattr(source.model,k)) for k in names},
            copy.deepcopy(source.fit_records),source.active_fit_id,source.model.best_fit)


def restore_source(source,state):
    fields,records,active,best=state
    for name,value in fields.items():
        if name!='_model_expression':setattr(source.model,name,copy.deepcopy(value))
    source.model.update_model_expression(fields['_model_expression'],use_column_ids=True)
    source.model._parameters=copy.deepcopy(fields['_parameters'])
    source.fit_records=copy.deepcopy(records);source.active_fit_id=active;source.model.best_fit=best
    source._source_changed=True


def rekey(value,mapping):
    if isinstance(value,str):
        for old,new in mapping.items():
            prefix=f'plot:{old}:'
            if value.startswith(prefix):return f'plot:{new}:'+value[len(prefix):]
        return value
    if isinstance(value,list):return [rekey(v,mapping) for v in value]
    if isinstance(value,dict):return {rekey(k,mapping):(mapping.get(v,v) if k=='source_id' and isinstance(v,int) else rekey(v,mapping)) for k,v in value.items()}
    return copy.deepcopy(value)


def interval(expression, limits, previous=None, samples=None):
    """Map a viewed interval, including interior extrema, in original units."""
    low,high=sorted(limits)
    original=np.linspace(low,high,1025)
    if previous:
        # Formula edits are relative to the original data, not compounded.
        domain=previous.get('domain')
        if domain:
            raw=np.linspace(*domain,4097);mapped=values(previous['expression'],raw)
            differences=np.diff(mapped)
            if np.all(differences>0):original=np.interp(original,mapped,raw)
            elif np.all(differences<0):original=np.interp(original,mapped[::-1],raw[::-1])
            else:raise ValueError('已有变换不是单调函数，请恢复原数据后再调整有界范围')
    if samples is not None:
        samples=np.asarray(samples);samples=samples[np.isfinite(samples)]
        current=values(previous['expression'],samples) if previous else samples
        original=np.concatenate((original,samples[(current>=low)&(current<=high)]))
    result=values(expression,original)
    return [float(result.min()),float(result.max())]


def apply_transform(c,expression):
    if not expression:return
    plot=c.plot;axis=c.current;horizontal=axis in {'x','top'}
    if getattr(plot,'_inset_parent',None) is not None:
        raise ValueError('放大图与原图共用数据，请在原图进行显示调整')
    cfg=plot.presentation.axes[axis]
    if cfg.get('display_transform',{}).get('expression')==expression:return
    owner=plot.main_window
    root=getattr(plot,'_embedded_parent',plot)
    native=getattr(getattr(root,'advanced_view',None),'native',None) if root is not plot else None
    if native and native.cfg['kind']=='bar' and native.cfg.get('horizontal'):
        horizontal=not horizontal
    view=getattr(plot,'advanced_view',None)
    three=bool(view and view.cfg.get('kind')=='3d')
    all_graphs=graphs(owner)
    if three:
        dimension={'x':0,'y':1,'right':2}.get(axis)
        if dimension is None:raise ValueError('色标不是数据轴，不能生成变换列')
        sid,key=view.cfg['xyz'][dimension]
        sheet=next(s for s in owner.get_data_sheets() if s.id==sid)
        targets=[];keys=[key]
    else:
        dimension=None
        if plot.presentation.multi:
            targets=[s for s,i in plot.model._plots.items() if
                     (i.x_axis==('top' if axis=='top' else 'bottom') if horizontal else i.axis==('right' if axis=='right' else 'left'))]
        else:targets=[plot]
        if not targets:raise ValueError('当前轴没有数据曲线')
        sheet=targets[0].data_sheet
        if any(s.data_sheet is not sheet for s in targets):raise ValueError('当前轴须使用同一工作表')
        keys=list(dict.fromkeys(getattr(s.model,'x_col' if horizontal else 'y_col') for s in targets))
    model=sheet.model;dm=model.data_model;column_keys=list(model.columnLabels())
    from tailor.column_titles import remark
    previous=cfg.get('display_transform',{})
    base=dict(zip(previous.get('results',[]),previous.get('sources',[])))
    keys=list(dict.fromkeys(base.get(k,k) for k in keys))
    error_base=previous.get('error_sources',{})
    specs=[];slots={};exclusions={};error_formulas={}
    from tailor.cst_names import rename_variables
    from tailor.formula_policy import validate_formula
    for key in keys:
        raw=np.asarray(dm.get_column(key),dtype=float)
        adjusted=values(expression,raw)
        validate_formula(rename_variables(expression,{'x':key}),column_keys)
        if cfg.get('log') and np.any(adjusted[np.isfinite(adjusted)]<=0):
            raise ValueError('对数轴的变换结果必须为正数，请先改为线性轴')
        slots[key]=len(specs);exclusions[key]=copy.deepcopy(dm._excluded.get(key,set()))
        specs.append({'name':remark(model,key)+'调整','values':adjusted,'role':'X' if horizontal else 'Y',
                      'source':json.dumps({'type':'axis_transform','column':key,'expression':expression},ensure_ascii=False)})
    # Symmetric error columns are transformed only when they remain symmetric.
    errors={}
    for source in targets:
        key=base.get(getattr(source.model,'x_col' if horizontal else 'y_col'),getattr(source.model,'x_col' if horizontal else 'y_col'))
        err=getattr(source.model,'x_err_col' if horizontal else 'y_err_col')
        err=error_base.get(err,err)
        if err is None or (key,err) in errors:continue
        raw=np.asarray(dm.get_column(key),dtype=float);error=np.asarray(dm.get_column(err),dtype=float)
        valid=np.isfinite(raw)&np.isfinite(error)
        if not valid.any():raise ValueError('误差列没有有效值')
        if np.any(error[valid]<0):raise ValueError('误差值必须非负')
        center=values(expression,raw[valid]);above=values(expression,raw[valid]+error[valid]);below=values(expression,raw[valid]-error[valid])
        plus=above-center;minus=center-below
        if not np.allclose(plus,minus,rtol=1e-7,atol=max(1e-14,np.max(np.abs(center))*1e-13)):
            raise ValueError('此变换使正负误差不再对称；请先处理不对称误差，原数据与原图已保留')
        output=np.full(raw.shape,np.nan);output[valid]=(np.abs(plus)+np.abs(minus))/2
        errors[(key,err)]=len(specs)
        import ast
        def substitute(replacement):
            class Substitute(ast.NodeTransformer):
                def visit_Name(self,node):return ast.parse(replacement,mode='eval').body if node.id=='x' else node
            return '('+ast.unparse(Substitute().visit(ast.parse(expression,mode='eval')).body)+')'
        plus_expr=substitute(f'({key}+{err})')+'-'+substitute(key)
        minus_expr=substitute(key)+'-'+substitute(f'({key}-{err})')
        error_formula=f'where(abs(({plus_expr})-({minus_expr}))<=1e-7*maximum(abs({plus_expr}),abs({minus_expr}))+1e-14,(abs({plus_expr})+abs({minus_expr}))/2,nan)'
        validate_formula(error_formula,column_keys)
        error_formulas[(key,err)]=error_formula
        specs.append({'name':remark(model,err)+'调整','values':output,'role':'XErr' if horizontal else 'YErr',
                      'source':json.dumps({'type':'axis_transform_error','column':err,'expression':expression},ensure_ascii=False)})
    single=not plot.presentation.multi and not three
    holder=plot.model if axis in {'x','y'} or single else plot.presentation
    bound_axis=('x' if axis in {'x','top'} else 'y') if single else axis
    bound_names=(bound_axis+'_min',bound_axis+'_max')
    old_limits=[getattr(holder,n) for n in bound_names]
    new_limits=list(old_limits)
    finite=np.concatenate([np.asarray(dm.get_column(k),dtype=float) for k in keys])
    finite=finite[np.isfinite(finite)]
    domain=[float(finite.min()),float(finite.max())]
    if not previous:
        specified=[v for v in old_limits if v is not None]
        domain=[min([domain[0],*specified]),max([domain[1],*specified])]
    elif previous.get('domain'):
        domain=list(previous['domain'])
    if any(v is not None for v in old_limits):
        old_domain=values(previous['expression'],np.asarray(domain)) if previous else domain
        endpoints=[v if v is not None else float(old_domain[i]) for i,v in enumerate(old_limits)]
        converted=interval(expression,endpoints,previous,finite)
        new_limits=[converted[i] if v is not None else None for i,v in enumerate(old_limits)]
        if all(v is not None for v in new_limits) and new_limits[0]>=new_limits[1]:
            raise ValueError('变换后的手动范围没有跨度，请先恢复自动范围')
    from tailor.inset_collection import entries as inset_entries
    from tailor.graph_presentation import physical,display
    inset_ranges={}
    for entry in inset_entries(plot):
        _,xkey,ykey=entry.inset_source()
        bounds=entry.cfg.get('inset',{}).get('range')
        if bounds and axis in {xkey,ykey}:
            indices=(0,2) if axis==xkey else (1,3)
            source_limits=physical(np.asarray(bounds)[list(indices)],cfg)
            inset_ranges[entry.cfg['inset']['id']]=(indices,interval(expression,source_limits,previous,finite))
    # Validate every result before touching the worksheet or graph mappings.
    before_axes=copy.deepcopy(plot.presentation.axes)
    before_bounds={key:getattr(plot.model,key) for key in ('x_min','x_max','y_min','y_max')}
    before_sides={key:getattr(plot.presentation,key) for key in ('top_min','top_max','right_min','right_max')}
    before_extra=copy.deepcopy(plot.presentation.extra_settings)
    mappings={g:dict(g.model._plots) for g in all_graphs if hasattr(g.model,'_plots')}
    affected=set(targets);switches={};foreign={}
    for source in targets:
        others=[g for g in mappings if g is not plot and source in mappings[g]]
        if plot.presentation.multi and (others or owner.ui.tabWidget.indexOf(source)>=0):
            switches[source]=clone(source);affected.add(switches[source])
        elif source is plot and others:
            foreign[source]=[(g,clone(source)) for g in others]
            affected.update(s for _,s in foreign[source])
    before_sources={s:source_state(s) for s in affected}
    changed_graphs=list(dict.fromkeys([plot,*([root] if native else []),*[g for entries in foreign.values() for g,_ in entries]]))
    if native:native.snapshot()
    before_presentations={g:g.presentation.to_dict() for g in changed_graphs}
    dirty_before=owner._is_dirty
    original=model._snapshot()
    history_before=list(model._history);cursor_before=model._cursor
    refresh_graphs=[plot]+[g for entries in foreign.values() for g,_ in entries]
    try:
        def write():
            nonlocal added
            added=model.append_results(specs,title='显示调整')
            from tailor.cst_names import rename_variables
            for key,slot in slots.items():
                new=added[slot]
                dm._calculated_column_expression[new]=rename_variables(expression,{'x':key})
                dm._is_calculated_column_valid[new]=True
                dm._excluded[new]=copy.deepcopy(exclusions[key])
            for (key,err),slot in errors.items():
                new=added[slot]
                dm._calculated_column_expression[new]=error_formulas[(key,err)]
                dm._is_calculated_column_valid[new]=True
                dm._excluded[new]=copy.deepcopy(dm._excluded.get(err,set()))
        added=[]
        if not model._structural('坐标轴显示调整',write):raise ValueError('无法为本次调整保留撤销记录')
        table_edit=model._history[model._cursor-1]
        for source,entries in foreign.items():
            for graph,new in entries:
                graph.model._plots={new if s is source else s:i for s,i in graph.model._plots.items()}
                new._fit_host=graph
                graph.presentation.load(rekey(graph.presentation.to_dict(),{source.id:new.id}))
        if plot.presentation.multi:
            plot.model._plots={switches.get(s,s):i for s,i in plot.model._plots.items()}
            if switches:
                mapping={s.id:n.id for s,n in switches.items()}
                state=rekey(plot.presentation.to_dict(),mapping);plot.presentation.load(state)
        for old in targets:
            source=switches.get(old,old);key=getattr(source.model,'x_col' if horizontal else 'y_col')
            key=base.get(key,key)
            err=getattr(source.model,'x_err_col' if horizontal else 'y_err_col')
            err=error_base.get(err,err)
            x,y=source.model.x_col,source.model.y_col
            ex,ey=source.model.x_err_col,source.model.y_err_col
            if horizontal:
                x=added[slots[key]];ex=added[errors[(key,err)]] if err else None
            else:
                y=added[slots[key]];ey=added[errors[(key,err)]] if err else None
            name=lambda k:dm.get_column_name(k) if k else None
            source.change_data_source(sheet,name(x),name(y),name(ex),name(ey),refresh=False)
            source.model.best_fit=None
            for record in source.fit_records:record['stale']=True
            source.set_fit_domain_from_data();source.model._use_fit_domain=False
            if hasattr(source,'fit_actions'):source.fit_actions.sync()
            if plot.presentation.multi:source._fit_host=plot
        if three:
            view.cfg['xyz'][dimension]=[sheet.id,added[slots[key]]]
            view.cfg['refs']=[view.cfg['xyz'][1]]
        if native:
            node=next(n for n in native.cfg['nodes'] if n['id']==plot._panel_id)
            node['refs']=[[s.data_sheet.id,s.model.y_col] for s in native.source_documents(plot)]
            native.cfg['refs']=[r for n in native.cfg['nodes'] for r in n['refs']]
            if native.cfg['kind']=='bar':
                if horizontal:native.cfg['bar_x_ref']=[sheet.id,added[slots[keys[0]]]]
                else:
                    for series in native.cfg.get('bar_series',[]):
                        old_key=base.get(series['ref'][1],series['ref'][1])
                        if old_key in slots:series['ref']=[sheet.id,added[slots[old_key]]]
            native.snapshot()
        cfg=plot.presentation.axes[axis]
        cfg.update(expression='',divisor=1.,major=None,precision_follow_interval=True,
                   display_transform={'expression':expression,'sources':keys,'results':[added[slots[k]] for k in keys],
                                      'domain':domain,'error_sources':{added[slot]:err for (key,err),slot in errors.items()}})
        if cfg.get('break_enabled'):
            limits=interval(expression,[cfg['break_low'],cfg['break_high']],previous)
            cfg['break_low'],cfg['break_high']=limits
            cfg['break_reference_span']=float(np.ptp(values(expression,np.asarray(domain))))
        for name,value in zip(bound_names,new_limits):setattr(holder,name,value)
        plot._clear_remembered_zoom()
        if single:plot.update_limits()
        refresh(plot,refresh_graphs)
        for entry in inset_entries(plot):
            item=inset_ranges.get(entry.cfg['inset']['id'])
            if item:
                indices,limits=item
                # Both dimensions must come from the pre-transform snapshot:
                # source redraws can temporarily constrain circular ROIs.
                original_entries=before_extra.get('insets',[])
                original_entry=next((r for r in original_entries if r.get('id')==entry.cfg['inset']['id']),None)
                bounds=list(original_entry['range'] if original_entry else before_extra['inset']['range'])
                for i,v in zip(indices,display(limits,cfg)):bounds[i]=float(v)
                entry.range_box.updateMatrix()
                entry.cfg['inset']['range']=bounds
                entry.cfg['inset']['preserve_transformed_range']=True
                entry.load()
        after_sources={s:source_state(s) for s in affected}
        after_mappings={g:dict(g.model._plots) for g in mappings}
        after_axes=copy.deepcopy(plot.presentation.axes)
        after_bounds={key:getattr(plot.model,key) for key in before_bounds}
        after_sides={key:getattr(plot.presentation,key) for key in before_sides}
        after_extra=copy.deepcopy(plot.presentation.extra_settings)
        if native:native.snapshot();native.view.schedule(True)
        after_presentations={g:g.presentation.to_dict() for g in changed_graphs}
    except Exception:
        for g,mapping in mappings.items():g.model._plots=dict(mapping)
        for s,state in before_sources.items():restore_source(s,state)
        plot.presentation.axes=before_axes
        plot.presentation.extra_settings=before_extra
        for name,value in before_bounds.items():setattr(plot.model,name,value)
        for name,value in before_sides.items():setattr(plot.presentation,name,value)
        guard=model.removal_guard;model.removal_guard=None
        try:model._restore(original)
        finally:model.removal_guard=guard
        model._history=history_before;model._cursor=cursor_before;model.historyChanged.emit()
        for g,state in before_presentations.items():g.presentation.load(state)
        refresh(plot,refresh_graphs)
        owner.mark_project_dirty(dirty_before)
        raise
    def restore(forward):
        states=after_sources if forward else before_sources
        maps=after_mappings if forward else mappings
        # Undo source references before removing their newly generated columns.
        if forward:
            if table_edit.forward() is False:return False
        for g,mapping in maps.items():g.model._plots=dict(mapping)
        for s,state in states.items():restore_source(s,state)
        plot.presentation.axes=copy.deepcopy(after_axes if forward else before_axes)
        plot.presentation.extra_settings=copy.deepcopy(after_extra if forward else before_extra)
        for key,value in (after_bounds if forward else before_bounds).items():setattr(plot.model,key,value)
        for key,value in (after_sides if forward else before_sides).items():setattr(plot.presentation,key,value)
        if not forward and table_edit.backward() is False:
            for g,mapping in after_mappings.items():g.model._plots=dict(mapping)
            for s,state in after_sources.items():restore_source(s,state)
            plot.presentation.axes=copy.deepcopy(after_axes)
            plot.presentation.extra_settings=copy.deepcopy(after_extra)
            for key,value in after_bounds.items():setattr(plot.model,key,value)
            for key,value in after_sides.items():setattr(plot.presentation,key,value)
            for g,state in after_presentations.items():g.presentation.load(state)
            refresh(plot,refresh_graphs)
            return False
        for g,state in (after_presentations if forward else before_presentations).items():g.presentation.load(state)
        if three:
            view.cfg=plot.presentation.extra_settings['advanced']
            if hasattr(plot,'advanced_controls'):plot.advanced_controls.load(view.cfg)
        plot._clear_remembered_zoom();refresh(plot,refresh_graphs)
    model._history[model._cursor-1]=Edit('坐标轴显示调整',lambda:restore(False),lambda:restore(True),table_edit.size+16384)
    model.historyChanged.emit();owner.mark_project_dirty()
    return added


def refresh(plot,refresh_graphs):
    for graph in list(dict.fromkeys([plot,*refresh_graphs])):
        if getattr(graph,'_graph_disposed',False):continue
        graph.refresh_ui()
        from tailor.inset_collection import entries
        for entry in entries(graph):entry.load()
        if hasattr(graph,'preferences'):graph.preferences.refresh_targets()
        if hasattr(graph,'axis_controls'):graph.axis_controls.sync()
        if hasattr(graph,'fit_router'):graph.fit_router.refresh()
    view=getattr(plot,'advanced_view',None)
    if view:
        view.schedule(True)
        if hasattr(plot,'advanced_controls'):plot.advanced_controls.load(view.cfg)

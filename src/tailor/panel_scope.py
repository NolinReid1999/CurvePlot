"""Immediate, field-specific style scopes over existing panel transactions.

The original edit remains the authority. Only the properties changed by that edit
are mirrored; data, selections and hide/delete commands never acquire a scope.
"""
import copy
from dataclasses import replace
from PySide6 import QtCore, QtWidgets
from tailor.graph_controls import row
from tailor.choice_buttons import ChipList, ChoiceButtons


def context(doc):
    root=getattr(doc,'_embedded_parent',None)
    native=getattr(getattr(root,'advanced_view',None),'native',None)
    return native if native and native.cfg.get('kind')=='panels' else None


def add_card(native, page, axis=False):
    box=QtWidgets.QComboBox(page)
    for text,key in [('仅当前','current'),('全部子图','all')]:box.addItem(text,key)
    scope_key='axis_scope' if axis else 'curve_scope'
    box.setCurrentIndex(max(0,box.findData(native.cfg.get(scope_key,'current'))))
    def scope_changed():
        native.cfg[scope_key]=box.currentData()
        for other in native.live():
            peer=other.axis_controls if axis else other.preferences.graph
            other_box=getattr(peer,'_group_scope',None)
            if other_box is not None and other_box is not box:
                with QtCore.QSignalBlocker(other_box):other_box.setCurrentIndex(box.currentIndex())
    box.currentIndexChanged.connect(scope_changed)
    box.setToolTip('同步全部子图的同侧轴设置；隐藏和删除仍仅作用于选中对象。' if axis else '同步本次修改的曲线样式；隐藏和删除仍仅作用于选中对象。')
    frame=QtWidgets.QFrame(page);frame.setObjectName('advancedElementContext')
    frame.setStyleSheet('QFrame#advancedElementContext {background:palette(highlight);border:1px solid palette(mid);border-radius:7px;}')
    layout=QtWidgets.QVBoxLayout(frame);layout.setContentsMargins(9,9,9,9);layout.setSpacing(6)
    layout.addWidget(QtWidgets.QLabel('高级绘图功能'))
    chips=ChipList();chips.chosen.connect(lambda i:native.activate(native.cfg['nodes'][i]['id']))
    layout.addWidget(row('作用子图',chips));layout.addWidget(row('应用范围',ChoiceButtons(box,equal=True)))
    from tailor.fold_panel import compact
    compact(frame)
    layout.setContentsMargins(9,9,9,9)
    page.open_layout.insertWidget(0,frame)
    page._panel_card,page._panel_chips,page._group_scope=frame,chips,box
    return frame


def difference(old,new):
    return {k:copy.deepcopy(v) for k,v in new.items() if old.get(k)!=v}


def capture(doc):
    from tailor.view_history import state
    return state(doc)


def old_state(doc,label,before):
    value=capture(doc);axis=doc.axis_controls.current
    if isinstance(before,dict):
        if {'model','presentation','style'}<=before.keys():return before
        if 'axes' in before:value['presentation']=copy.deepcopy(before);return value
    if label=='坐标轴设置':
        value['presentation']=copy.deepcopy(before[0]);value['model'].update(before[1])
    elif label=='坐标轴文字':
        holder=value['presentation'] if axis in {'top','right'} else value['model']
        holder[axis+'_label']=before[0];value['style']=before[1].to_dict()
        value['presentation']['axes'][axis]['tick_text']=copy.deepcopy(before[2])
    elif label=='轴端倍率':
        value['presentation']['axes'][axis]=copy.deepcopy(before[0])
        value['presentation']['text_offsets']=copy.deepcopy(before[1])
    elif label=='刻度文字角度':
        value['presentation']['axes'][axis].update(tick_angle=before[0],tick_angle_enabled=before[1])
    else:return None
    return value


def curve_delta(before,after):
    # Typography is handled per axis below, never copied as part of a line edit.
    ignored={'visible','font_size','font_family','text_styles','transparent'}
    changes=difference(before['style'],after['style'])
    for (source,old,_),(target,new,_) in zip(before['sources'],after['sources']):
        if source is target:
            changes.update(difference(old.style or source.curve_style.to_dict(),new.style or source.curve_style.to_dict()))
            if old.color!=new.color:changes['color']=new.color
    old=before['presentation'].get('curve_overrides',{})
    for key,new in after['presentation'].get('curve_overrides',{}).items():
        if key.startswith('annotation:'):continue
        if old.get(key)!=new:changes.update(difference(old.get(key,{}),new))
    return {k:v for k,v in changes.items() if k not in ignored}


def apply_delta(doc,old,new,axis,axis_scope,curve_scope):
    p=doc.presentation
    if axis_scope:
        cfg=difference(old['presentation']['axes'][axis],new['presentation']['axes'][axis])
        p.axes[axis].update(cfg)
        oldholder=old['presentation'] if axis in {'top','right'} else old['model']
        newholder=new['presentation'] if axis in {'top','right'} else new['model']
        holder=p if axis in {'top','right'} else doc.model
        for suffix in ('label','min','max'):
            key=axis+'_'+suffix
            if oldholder.get(key)!=newholder.get(key):setattr(holder,key,newholder.get(key))
        styles=copy.deepcopy(doc.curve_style.text_styles)
        for suffix in ('_label','_ticks','_factor'):
            key=axis+suffix;before=old['style'].get('text_styles',{}).get(key,{})
            after=new['style'].get('text_styles',{}).get(key,{})
            if before!=after:
                from tailor.text_style_controls import font_spec
                styles[key]={**font_spec(doc.curve_style,key),**difference(before,after)}
        doc.curve_style=replace(doc.curve_style,text_styles=styles)
        for key,value in difference(old['presentation'].get('text_offsets',{}),new['presentation'].get('text_offsets',{})).items():
            if key.startswith(axis+'_'):p.text_offsets[key]=value
        for key,value in difference(old['presentation'].get('frame',{}),new['presentation'].get('frame',{})).items():p.frame[key]=value
        if any(oldholder.get(axis+'_'+k)!=newholder.get(axis+'_'+k) for k in ('min','max')):
            doc._clear_remembered_zoom();doc.update_limits()
    if curve_scope:
        changes=curve_delta(old,new)
        if changes:
            if p.multi:
                for source,info in doc.model._plots.items():
                    from tailor.curve_style import CurveStyle
                    style=replace(CurveStyle(**info.style) if info.style else source.curve_style,color=info.color)
                    style=replace(style,**changes);info.style=style.to_dict();info.color=style.color
            else:
                from tailor.curve_controls import apply_style
                apply_style(doc,replace(doc.curve_style,**changes))
            from tailor.preference_pages import available_curves,apply_drawn_styles,rendered_curve_style
            for key,(item,_) in available_curves(doc,include_hidden=False).items():
                if key=='data' or key.endswith(':data'):continue
                p.curve_overrides[key]={**rendered_curve_style(item).to_dict(),**p.curve_overrides.get(key,{}),**changes}
            if p.multi:doc.draw_plot()
            apply_drawn_styles(doc)
    p.apply_axes()
    from tailor.text_style_controls import apply_text_styles
    apply_text_styles(doc);doc.axis_controls.sync()


def wrap_edit(doc,label,before,after,setter):
    native=context(doc)
    if native is None or native.syncing or native.loading:return setter
    axis_scope=doc.axis_controls._group_scope.currentData()=='all'
    graph=doc.preferences.graph
    curve_scope=graph._group_scope.currentData()=='all'
    if not (axis_scope or curve_scope):return setter
    old=old_state(doc,label,before)
    if old is None:return setter
    new=capture(doc);others=[d for d in native.live() if d is not doc]
    axis=doc.axis_controls.current
    pref=doc.preferences.curve_target
    if pref[0] in {'axis','grid'}:axis=pref[1]
    oldholder=old['presentation'] if axis in {'top','right'} else old['model']
    newholder=new['presentation'] if axis in {'top','right'} else new['model']
    axis_change=(old['presentation']['axes'][axis]!=new['presentation']['axes'][axis]
        or any(oldholder.get(axis+'_'+k)!=newholder.get(axis+'_'+k) for k in ('label','min','max'))
        or any(old['style'].get('text_styles',{}).get(axis+k)!=new['style'].get('text_styles',{}).get(axis+k) for k in ('_label','_ticks'))
        or old['presentation'].get('frame')!=new['presentation'].get('frame')
        or old['presentation'].get('text_offsets')!=new['presentation'].get('text_offsets'))
    axis_scope=axis_scope and axis_change
    curve_scope=curve_scope and bool(curve_delta(old,new))
    if not (axis_scope or curve_scope):return setter
    saved=[(d,capture(d)) for d in others]
    native.syncing=True
    try:
        for d in others:apply_delta(d,old,new,axis,axis_scope,curve_scope)
        applied=[(d,capture(d)) for d in others]
    finally:native.syncing=False
    native.refresh_unified()
    from tailor.view_history import restore
    def group_restore(target,value):
        native.syncing=True
        try:
            setter(target,value)
            for d,state in saved if value is before else applied:restore(d,state)
        finally:native.syncing=False
        native.refresh_unified()
    return group_restore

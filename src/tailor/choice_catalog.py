"""Ordering/visibility adapters for existing Qt selectors; no new data model."""
import re
from PySide6 import QtCore, QtGui


def visible_columns(model):
    return [key for i,key in enumerate(model.columnLabels())
            if str(model.column_metadata(i).get('hidden','false')).lower()!='true']


def column_rank(model,key):
    keys=list(model.columnLabels())
    return keys.index(key) if key in keys else 10**9


def source_visible(graph,source):
    if source.id in graph.presentation.extra_settings.get('deleted_curves',[]):return False
    info=graph.model.get_plot_info(source) if graph.presentation.multi else None
    return bool(info.visible if info is not None else source.curve_style.visible)


def sorted_sources(graph,visible=True):
    from tailor.document_names import sources
    return sorted((s for s in sources(graph) if not visible or source_visible(graph,s)),
                  key=lambda s:column_rank(s.data_sheet.model,s.model.y_col))


def fit_entries(graph,hidden=False):
    from tailor.fit_workflow import result_sources
    from tailor.column_titles import display
    rows=[]
    for source in result_sources(graph):
        for record in source.fit_records:
            title=display(source.data_sheet.model,record.get('column_id'))
            if not title or bool(record.get('hidden',False))!=hidden:continue
            context=getattr(graph,'_fit_host',graph)
            if not hidden:
                if context.presentation.multi and not source_visible(context,source):continue
                prefix=f'plot:{source.id}:' if context.presentation.multi else ''
                aliases=[prefix+'fit:'+str(record['id'])]
                if source.active_fit_id==record['id']:aliases.append(prefix+'fit')
                flags=context.presentation.extra_settings.get('drawn_visibility',{})
                if any(flags.get(key) in {'hidden','deleted'} for key in aliases):continue
            rows.append((source,record,title))
    return sorted(rows,key=lambda r:column_rank(r[0].data_sheet.model,r[1].get('column_id')))


def curve_column(graph,key):
    from tailor.fit_workflow import fit_owner
    if not key:return None
    fitted=fit_owner(graph,key)
    if fitted:
        source,identifier=fitted
        record=next((r for r in source.fit_records if r['id']==identifier),None)
        if record:
            from tailor.fit_results import curve_column as result_column
            return source.data_sheet.model,result_column(record,key)
    if key=='data' and not graph.presentation.multi:return graph.data_sheet.model,graph.model.y_col
    for source in sorted_sources(graph,visible=False):
        if key==f'plot:{source.id}:data':return source.data_sheet.model,source.model.y_col
    if key.startswith('trend:'):
        record=next((r for r in graph.presentation.trend_sources if r['id']==key[6:]),None)
        if record:
            sheet=next((s for s in graph.main_window.get_data_sheets() if s.id==record['sheet']),None)
            if sheet:return sheet.model,record['y']
    return None


def curve_rank(graph,key):
    match=graph.presentation.legend.get('matches',{}).get(key)
    ref=curve_column(graph,match or key)
    return column_rank(*ref) if ref else 10**9


def curve_visible(graph,key,item=None):
    if graph.presentation.extra_settings.get('drawn_visibility',{}).get(key) in {'hidden','deleted'}:return False
    from tailor.fit_workflow import fit_owner
    fitted=fit_owner(graph,key)
    if fitted:
        source,identifier=fitted
        record=next((r for r in source.fit_records if r['id']==identifier),None)
        return bool(record and not record.get('hidden') and (not graph.presentation.multi or source_visible(graph,source)))
    for source in sorted_sources(graph,visible=False):
        if key==('data' if not graph.presentation.multi else f'plot:{source.id}:data'):
            return source_visible(graph,source)
    return item is None or item.isVisible()


def title_rank(text):
    text=text.strip()
    if text=='—':return (0,0)
    if text.startswith('全部'):return (1,0)
    match=re.match(r'^([A-Z]+)\s*[·.]',text)
    if match:
        number=0
        for ch in match[1]:number=number*26+ord(ch)-64
        return (2,number)
    return (3,0)


def sort_combo(combo,key=None):
    """Sort within Qt's model without transferring native item ownership."""
    count=combo.count();old=combo.currentIndex()
    order=sorted(range(count),key=lambda i:(key(combo.itemData(i),i) if key else title_rank(combo.itemText(i)),i))
    if order==list(range(count)):return
    model=combo.model()
    if not isinstance(model,QtGui.QStandardItemModel):return
    # takeRow/appendRow repeatedly exposes temporary QStandardItem wrappers to
    # Python. Reusing native-owned rows avoids that lifetime boundary entirely.
    # A temporary rank role permits the existing semantic order while keeping
    # all original roles, flags, icons, object IDs and the selected item.
    role=int(QtCore.Qt.UserRole)+0x4F00
    previous_role=model.sortRole()
    saved=[model.data(model.index(i,0),role) for i in range(count)]
    with QtCore.QSignalBlocker(combo):
        try:
            for rank,i in enumerate(order):model.setData(model.index(i,0),rank,role)
            model.setSortRole(role)
            model.sort(0,QtCore.Qt.AscendingOrder)
        finally:
            for rank,i in enumerate(order):model.setData(model.index(rank,0),saved[i],role)
            model.setSortRole(previous_role)
        combo.setCurrentIndex(order.index(old) if old>=0 else -1)


def object_rank(graph,kind,identifier=None):
    """Persist logical creation order independently from z-order and redraws."""
    order=graph.presentation.extra_settings.setdefault('object_creation_order',{})
    token=kind+':'+str(identifier or '')
    if token not in order:order[token]=max(order.values(),default=0)+1
    return order[token]


def seed_objects(graph):
    # Legacy documents have no cross-kind timestamp: preserve their existing
    # relative list order once, then store it for future hide/restore cycles.
    for record in graph.annotations.records:object_rank(graph,'annotation',record['id'])
    collection=getattr(getattr(graph,'extras',None),'collection',None)
    for record in collection.records if collection else []:object_rank(graph,'inset',record['id'])
    object_rank(graph,'legend')
    for key in ('x','y','top','right'):
        object_rank(graph,'axis',key)
        if graph.presentation.axes[key].get('factor_text'):object_rank(graph,'factor',key)


def graph_columns(graph):
    """All plotted column identities and the hidden subset, including fits."""
    plotted,hidden=set(),set()
    for source in sorted_sources(graph,visible=False):
        ref=(source.data_sheet.id,source.model.y_col);plotted.add(ref)
        if not source_visible(graph,source):hidden.add(ref)
        for record in source.fit_records:
            for entry in [record]+record.get('components',[]):
                key=entry.get('column_id')
                if key is None:continue
                ref=(source.data_sheet.id,key);plotted.add(ref)
                if record.get('hidden') or (graph.presentation.multi and not source_visible(graph,source)):hidden.add(ref)
    for key,status in graph.presentation.extra_settings.get('drawn_visibility',{}).items():
        if status not in {'hidden','deleted'}:continue
        ref=curve_column(graph,key)
        if ref:
            sheet=next((s for s in graph.main_window.get_data_sheets() if s.model is ref[0]),None)
            if sheet:hidden.add((sheet.id,ref[1]))
    return plotted,hidden


def refresh_object_choices(graph):
    """Notify existing selectors after visibility edits, without reading data."""
    if getattr(graph,'_graph_disposed',False):return
    annotations=getattr(graph,'annotations',None)
    panel=getattr(annotations,'panel',None)
    if panel is not None and hasattr(panel,'position_controls'):panel.position_controls.sync()
    preferences=getattr(graph,'preferences',None)
    if preferences is not None:preferences.refresh_targets()
    axes=getattr(graph,'axis_controls',None)
    if axes is not None:axes.sync()
    actions=getattr(graph,'fit_actions',None)
    if actions is not None:actions.sync()
    router=getattr(graph,'fit_router',None)
    if router is not None:router.refresh()
    processing=getattr(graph,'processing_controls',None)
    if processing is not None:
        visible=set((s.id,key) for s in processing.sheets().values() for key in visible_columns(s.model))
        hidden=graph_columns(graph)[1]
        processing.targets=[ref for ref in processing.targets if ref in visible and ref not in hidden]
        processing.sync_objects_text();processing.refresh_result_choice()
    for name in ('export_controls',):
        control=getattr(graph,name,None)
        if control is not None:control.refresh()

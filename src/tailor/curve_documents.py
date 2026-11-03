"""Thin document adapters: native Tailor series without unwanted graph tabs."""

from time import monotonic
from PySide6 import QtCore,QtWidgets


class InspectorMoveGuard(QtCore.QObject):
    """Yield inspector setup while the user moves the containing window."""
    def __init__(self,group):
        super().__init__(group)
        self.until=0.0
        group.main_window.projects.host.installEventFilter(self)

    def eventFilter(self,watched,event):
        from tailor.crash_diagnostics import valid_event
        if not valid_event(event,'InspectorMoveGuard'):return True
        if event.type()==QtCore.QEvent.Move:self.until=monotonic()+.15
        return False

    def active(self):
        return monotonic()<self.until or QtWidgets.QApplication.mouseButtons()!=QtCore.Qt.NoButton


def create_source(owner, sheet, x, y, xerr=None, yerr=None):
    from tailor.plot_tab import PlotTab
    from tailor.column_titles import remark, title
    if any(p.data_sheet is sheet and p.model.y_col == y and p.model.x_col != x
           for p in owner.get_plots()):
        owner.statusBar().showMessage("不支持同一Y列同时对应不同X列；请复制Y列后再绘图。", 8000)
        return None
    owner._plot_num += 1
    source = PlotTab(owner, remark(sheet.model, y), owner._plot_num,
                     sheet, x, y, xerr, yerr, defer_inspector=True, hidden_source=True)
    source.model.x_label = title(sheet.model, x)
    source.model.y_label = title(sheet.model, y)
    source._curve_own_name = source.name
    source.hide()
    return source


def create_group(owner, sources, replace_doc=None, *, placements=None):
    from tailor.multiplot_tab import MultiPlotTab
    owner._plot_num += 1
    if replace_doc:
        name = replace_doc.name
    else:
        import re
        used = [int(match[1]) for i in range(owner.ui.tabWidget.count())
                if (match := re.fullmatch(r"绘图(\d+)", getattr(owner.ui.tabWidget.widget(i), "name", "")))]
        serial = max([getattr(owner, "_graph_caption_serial", 0), *used]) + 1
        owner._graph_caption_serial = serial
        name = f"绘图{serial}"
    pending=[source for source in sources if getattr(source,'_inspector_initializing',False)]
    for source in pending:source._inspector_timer.stop()
    group = MultiPlotTab(owner, name, owner._plot_num,
                         sources[0].model.x_label, sources[0].model.y_label,
                         defer_inspector=True)
    group._curve_own_name = name
    if replace_doc:
        import copy
        group.presentation.extra_settings['series_colors'] = copy.deepcopy(replace_doc.presentation.extra_settings.get('series_colors', {}))
    group.presentation.extra_settings["document_name"] = name
    for source in sources:
        if getattr(source, '_hidden_curve_source', False):
            source._fit_host = group
        group.add_plot(source)
        if placements and source in placements:
            info=group.model.get_plot_info(source)
            info.axis,info.x_axis=placements[source]
    if replace_doc:
        replace_doc._visible_graph_document = group
        import copy
        group.curve_style = copy.deepcopy(replace_doc.curve_style)
        # Both documents retain their own series; only the visible tab changes.
        group.presentation.load(replace_doc.presentation.to_dict())
        group.presentation.extra_settings["document_name"] = name
    tabs = owner.ui.tabWidget
    with QtCore.QSignalBlocker(tabs):
        index = tabs.indexOf(replace_doc) if replace_doc else -1
        if index >= 0:
            owner.window_mode.forget(replace_doc)
            tabs.removeTab(index)
            replace_doc.hide()
            tabs.insertTab(index, group, name)
        else:
            tabs.addTab(group, name)
    tabs.setCurrentWidget(group)
    group.refresh_ui()
    if replace_doc is not None:
        group.inspector_ready.connect(lambda:transfer_processing(replace_doc,group))
    stage_inspectors(group,pending)
    owner.refresh_project_tree()
    owner.mark_project_dirty()
    return group


def stage_inspectors(group,sources,*,message="曲线已显示，正在准备编辑控件…"):
    """Show existing native series first; prepare one inspector stage per turn."""
    group._inspector_timer.stop()
    queue=[group,*sources]
    scheduled={id(doc) for doc in queue}
    group._source_inspector_queue=queue
    notice=getattr(group.main_window,'_notice',None)
    token=('inspector',group.id)
    if notice:notice.begin(token,message)
    guard=group._inspector_move_guard=InspectorMoveGuard(group)
    timer=QtCore.QTimer(group);timer.setInterval(0);group._batch_inspector_timer=timer
    def advance():
        if getattr(group,'_graph_disposed',False):
            timer.stop()
            if notice:notice.finish(token)
            return
        if guard.active():return
        # Drain cheap adjacent steps within a small budget. A fixed timer per
        # tiny step adds seconds of idle waits to a multi-curve document.
        started=monotonic()
        while monotonic()-started < .008:
            while queue and not getattr(queue[0],'_inspector_initializing',False):queue.pop(0)
            if not queue:
                timer.stop()
                if notice:notice.finish(token)
                return
            doc=queue[0];doc._advance_inspector();doc._inspector_timer.stop()
            # A restore stage can create an inset. Reuse this same bounded
            # queue instead of synchronously building it or adding a separate
            # 16 ms wait for every one of its inspector steps.
            collection=getattr(getattr(doc,'extras',None),'collection',None)
            if collection:
                for entry in collection.controllers.values():
                    child=getattr(entry,'inset_doc',None)
                    if child is not None and id(child) not in scheduled and getattr(child,'_inspector_initializing',False):
                        scheduled.add(id(child));child._inspector_timer.stop();queue.append(child)
            if hasattr(doc,'_inspector_error'):
                timer.stop()
                if notice:
                    notice.finish(token);notice.message('编辑控件初始化失败：'+doc._inspector_error)
                return
    timer.timeout.connect(advance);timer.start()


def add_column(doc, sheet, y, x=None, *, initial_style=None, initial_axes=None):
    from tailor.document_names import sources
    existing = sources(doc)
    found = next((p for p in existing if p.data_sheet is sheet and p.model.y_col == y), None)
    if found is not None:
        from tailor.element_actions import curve_visible
        curve_visible(doc, found, True)
        return doc
    x = x or (existing[0].model.x_col if existing else None)
    if x not in sheet.model.columnLabels():
        return None
    source = create_source(doc.main_window, sheet, x, y)
    if source is None:
        return None
    import copy
    source.apply_curve_style(copy.deepcopy(initial_style or existing[0].curve_style),dirty=False)
    from tailor.spreadsheet_model import Edit
    owner = doc.main_window
    if doc.presentation.multi:
        before = dict(doc.model._plots)
        doc.add_plot(source)
        if initial_axes:
            info=doc.model.get_plot_info(source)
            info.axis,info.x_axis=initial_axes
        after = dict(doc.model._plots)
        def restore(state):
            doc.model._plots = dict(state)
            doc.refresh_ui()
            owner.refresh_project_tree()
        restore(after)
        sheet.model._record(Edit("新增绘制曲线", lambda: restore(before), lambda: restore(after), 4096))
        owner.mark_project_dirty()
        return doc
    placements=None
    if initial_axes:
        placements={doc:(doc.presentation.single_sides['y'],doc.presentation.single_sides['x']),source:initial_axes}
    group = create_group(owner, [doc, source], replace_doc=doc, placements=placements)
    def activate(target, other):
        tabs = owner.ui.tabWidget
        index = tabs.indexOf(other)
        if index < 0:
            return
        with QtCore.QSignalBlocker(tabs):
            owner.window_mode.forget(other)
            tabs.removeTab(index)
            other.hide()
            tabs.insertTab(index, target, target.name)
        if target is doc:doc._visible_graph_document=doc
        elif target is group:doc._visible_graph_document=group
        tabs.setCurrentWidget(target)
        target.refresh_ui()
        owner.refresh_project_tree()
    sheet.model._record(Edit("新增绘制曲线", lambda: activate(doc, group), lambda: activate(group, doc), 4096))
    return group


def add_processing_results(owner, payload, graph=None):
    """Attach numeric result series to graphs which actually use their source Y."""
    import json
    import numpy as np
    tabs = owner.ui.tabWidget
    graphs = [getattr(graph,'_visible_graph_document',graph)] if graph else [tabs.widget(i) for i in range(tabs.count())
              if hasattr(tabs.widget(i), "presentation") and not getattr(tabs.widget(i), "advanced_view", None)]
    for bundle in payload:
        sheet = bundle["sheet"]
        keys = list(sheet.model.columnLabels())
        for key in bundle["keys"]:
            meta = sheet.model.column_metadata(keys.index(key))
            try:
                info = json.loads(meta.get("source") or "{}")
            except (ValueError, TypeError):
                continue
            slot = info.get("slot", "").rsplit(":", 1)[-1]
            if not info.get("column") or slot in {"X", "有效次数N"} or meta.get("role") in {"X", "XErr", "YErr"}:
                continue
            values = np.asarray(sheet.model.data_model.get_column(key))
            if len(values) <= 1 or np.count_nonzero(np.isfinite(values)) <= 1:
                continue
            for i, graph in enumerate(list(graphs)):
                from tailor.processing_controls import source_on_graph
                origin=source_on_graph(graph,sheet,info['column'])
                if origin is not None:
                    from tailor.graph_defaults import new_style
                    placement=graph.model.get_plot_info(origin) if graph.presentation.multi else None
                    axes=(placement.axis,placement.x_axis) if placement else (graph.presentation.single_sides['y'],graph.presentation.single_sides['x'])
                    result = add_column(graph, sheet, key, info.get("result_x") or info.get("x"), initial_style=new_style(),initial_axes=axes)
                    if result is not None:
                        graphs[i] = result
                        produced=next((s for s in result.model._plots if s.data_sheet is sheet and s.model.y_col==key),None) if result.presentation.multi else result
                        if produced is not None:
                            for other in bundle['keys']:
                                other_meta=sheet.model.column_metadata(list(sheet.model.columnLabels()).index(other))
                                if other_meta.get('role')=='YErr':
                                    produced.model.y_err_col=other
                                    produced.refresh_from_source()
                                    break


def transfer_processing(old,new):
    """Keep the current column-processing form when a single curve gains a series."""
    first=getattr(old,'processing_controls',None)
    second=getattr(new,'processing_controls',None)
    if first is None or second is None:return
    # Reuse the input history's typed snapshot, including text constants and
    # the input-history baseline. A partial widget-type copy lost newer fields.
    second.input_history.restore(first.input_history.snapshot())
    second._workflow_loading=True
    try:
        second.selected_result=getattr(first,'selected_result',None)
        if first.category in second.methods:second.select_category(first.category)

        second.sync_objects_text()
        if old.property_tabs.currentWidget() is first:new.property_tabs.setCurrentWidget(second)
    finally:second._workflow_loading=False

"""Global element commands adapt existing annotation, legend, curve and fit edits."""

import copy
from dataclasses import replace
from types import SimpleNamespace

from PySide6 import QtCore, QtWidgets

from tailor.spreadsheet_model import Edit


def data_setting():
    return QtCore.QSettings("PhysicsPlot", "ElementActions").value(
        "delete_data", True, type=bool
    )


def delete_data_choice(owner, dependencies, default=None):
    # An explicit choice has already been made by the composite operation.
    if default is not None:
        return bool(default)
    if not dependencies:
        return data_setting() if default is None else default
    box = QtWidgets.QMessageBox(owner)
    # Use the same Qt controls as the inspector. Cocoa's native helper owns a
    # separate button set and does not reliably round-trip the custom buttons.
    box.setOption(QtWidgets.QMessageBox.DontUseNativeDialog, True)
    box.setWindowTitle("数据仍被引用")
    box.setText(
        "以下对象仍使用这些数据：\n"
        + "\n".join(dependencies)
        + "\n连同数据删除后这些引用将失效；可撤销整个操作。"
    )
    only = box.addButton("仅删除元素", QtWidgets.QMessageBox.AcceptRole)
    both = box.addButton("连同数据删除", QtWidgets.QMessageBox.DestructiveRole)
    box.addButton(QtWidgets.QMessageBox.Cancel)
    box.setDefaultButton(only)
    box.exec()
    return (
        False
        if box.clickedButton() is only
        else True
        if box.clickedButton() is both
        else None
    )


def root(plot):
    parent = getattr(plot, "_inset_parent", plot)
    return parent


def target(doc):
    import shiboken6
    if doc is None or not shiboken6.isValid(doc) or getattr(doc, '_graph_disposed', False):
        return None
    tabs = getattr(doc, 'property_tabs', None)
    if tabs is not None and not shiboken6.isValid(tabs):
        return None
    if not hasattr(doc, "presentation"):
        return ("columns", None) if doc.column_preferences.columns() else None
    if not all(hasattr(doc,name) for name in ("annotations","text_selection","curve_selection")):
        return None
    if doc.annotations.current():
        return "annotation", doc.annotations.selected
    key = doc.text_selection.key
    if key:
        if key.startswith("legend-text:"):
            return "legend-row", key.split(":", 1)[1]
        if key.startswith("legend"):
            return "legend", None
        if key.endswith("_label"):
            return "axis", key.split("_", 1)[0]
        if key.endswith('_factor'):
            return 'axis-factor', key.split('_',1)[0]
    drawn = getattr(doc, "_selected_drawn_key", None)
    if drawn:
        return "drawn", drawn
    processing = getattr(doc, 'processing_controls', None)
    if processing is not None and doc.property_tabs.currentWidget() is processing:
        selected = getattr(processing, 'selected_result', None)
        if selected:
            return 'processing-result', selected
    if getattr(getattr(doc, 'preferences', None), 'curve_target', (None,))[0] == 'all':
        return 'curves-all', None
    pref=getattr(getattr(doc,'preferences',None),'curve_target',('none',None))
    if pref[0]=='legend_all':return 'legend',None
    if pref[0]=='legend' and pref[1] is not None:return 'legend-row',pref[1]
    selection = doc.curve_selection
    if selection.current is not None:
        return "curve", selection.current
    if (
        hasattr(doc, "fit_actions")
        and doc.fit_actions.current() is not None
        and (doc.property_tabs.currentWidget() is doc.fit_actions.page or hasattr(doc,'_fit_host'))
    ):
        return "fit", doc.fit_actions.current()["id"]
    base = root(doc)
    collection = getattr(getattr(base, "extras", None), "collection", None)
    if collection and collection.current():
        return "inset", collection.selected
    return None


def change_legend(doc, visible, deleted=False):
    from tailor.text_style_controls import record_view_edit

    before = copy.deepcopy(doc.presentation.legend)
    after = {**before, "visible": visible}
    if deleted:
        after['deleted'] = True
        # Deleting the container deletes its existing rows too. A later add
        # creates only a new row, rather than resurrecting this deleted content.
        from tailor.text_style_controls import legend_rows
        keys={key for key,_,_ in legend_rows(doc)}
        keys.update(getattr(doc.presentation,'_hidden_legend_rows',{}))
        keys.update(before.get('hidden_entries',[]))
        keys.update(row['key'] for row in before.get('custom_entries',[]))
        after['deleted_entries']=sorted(set(before.get('deleted_entries',[])) | keys)
    elif visible: after.pop('deleted', None)

    def restore(plot, value):
        plot.presentation.legend = copy.deepcopy(value)
        if not value.get('visible', True):
            selection = getattr(plot, 'text_selection', None)
            if selection is not None and (selection.key or '').startswith('legend'):
                selection.select(None)
            preferences = getattr(plot, 'preferences', None)
            if preferences is not None and preferences.curve_target[0].startswith('legend'):
                preferences.clear_curve_target()
        plot.presentation.apply_legend()
        plot.legend_controls.sync()
        from tailor.choice_catalog import refresh_object_choices
        refresh_object_choices(plot)

    restore(doc, after)
    record_view_edit(doc, "删除图例" if deleted else "显示图例" if visible else "隐藏图例", before, after, restore)


def factor_visible(doc,key,visible,deleted=False):
    from tailor.text_style_controls import record_view_edit
    before=(doc.presentation.axes[key].get('factor_text',''),
            copy.deepcopy(doc.presentation.extra_settings.get('hidden_factors',{})))
    saved=copy.deepcopy(before[1]);text=before[0]
    if visible:text=saved.pop(key,text)
    else:
        if not deleted:saved[key]=text
        text=''
    after=(text,saved)
    def restore(plot,state):
        plot.presentation.axes[key]['factor_text']=state[0]
        plot.presentation.extra_settings['hidden_factors']=copy.deepcopy(state[1])
        plot.presentation.apply_axes()
    restore(doc,after)
    record_view_edit(doc,'显示轴端倍率' if visible else '删除轴端倍率' if deleted else '隐藏轴端倍率',before,after,restore)


def curve_visible(doc, source, visible, deleted=False):
    from tailor.text_style_controls import record_view_edit

    before = (
        copy.deepcopy(doc.presentation.extra_settings.get("deleted_curves", [])),
        source.curve_style.visible
        if not doc.presentation.multi
        else doc.model.get_plot_info(source).visible,
    )

    def restore(plot, state):
        plot.presentation.extra_settings["deleted_curves"] = copy.deepcopy(state[0])
        if plot.presentation.multi:
            plot.model.get_plot_info(source).visible = state[1]
            plot.draw_plot()
        else:
            plot.apply_curve_style(
                replace(plot.curve_style, visible=state[1]), dirty=False
            )
        from tailor.choice_catalog import refresh_object_choices
        refresh_object_choices(plot)

    deleted_ids = list(before[0])
    if visible and source.id in deleted_ids:
        deleted_ids.remove(source.id)
    if deleted and source.id not in deleted_ids:
        deleted_ids.append(source.id)
    after = (deleted_ids, visible)
    restore(doc, after)
    record_view_edit(
        doc,
        "删除曲线" if deleted else "显示曲线" if visible else "隐藏曲线",
        before,
        after,
        restore,
    )


def combine(model, start, label):
    old = {id(edit) for edit in start}
    edits = [edit for edit in model._history[: model._cursor] if id(edit) not in old]
    if not edits:
        return
    start = next(i for i, edit in enumerate(model._history) if edit is edits[0])
    if len(edits) < 2:
        return

    def backward():
        for edit in reversed(edits):
            if edit.backward() is False:
                return False
        return True

    def forward():
        for edit in edits:
            if edit.forward() is False:
                return False
        return True

    model._history[start : model._cursor] = [
        Edit(label, backward, forward, sum(e.size for e in edits))
    ]
    model._cursor = start + 1
    model.historyChanged.emit()


def remove_column_graphs(owner, sheet, keys):
    from tailor.document_names import delete, sources

    tabs = owner.ui.tabWidget
    affected = [
        tabs.widget(i)
        for i in range(tabs.count())
        if any(
            s.data_sheet is sheet
            and any(
                k in keys
                for k in (
                    s.model.x_col,
                    s.model.y_col,
                    s.model.x_err_col,
                    s.model.y_err_col,
                )
            )
            for s in sources(tabs.widget(i))
        )
    ]
    for graph in affected:
        if tabs.indexOf(graph) < 0:
            continue
        if graph.presentation.multi:
            before = dict(graph.model._plots)
            after = {source: info for source, info in before.items()
                     if not (source.data_sheet is sheet and any(k in keys for k in
                             (source.model.x_col, source.model.y_col, source.model.x_err_col, source.model.y_err_col)))}
            if after:
                from tailor.text_style_controls import record_view_edit
                def restore(plot, state):
                    plot.model._plots = dict(state)
                    plot.refresh_ui()
                restore(graph, after)
                record_view_edit(graph, "移除关联曲线", before, after, restore)
                continue
        delete(owner, graph)


def drawn_visible(doc, key, visible, deleted=False):
    from tailor.text_style_controls import record_view_edit
    before = copy.deepcopy(doc.presentation.extra_settings.get("drawn_visibility", {}))
    after = {**before, key: "deleted" if deleted else "visible" if visible else "hidden"}
    def restore(plot, state):
        plot.presentation.extra_settings["drawn_visibility"] = copy.deepcopy(state)
        if plot.presentation.multi:
            plot.draw_plot()
        else:
            plot.refresh_legend()
        plot.presentation.apply_legend()
        if hasattr(plot, "preferences"):
            plot.preferences.refresh_targets()
        from tailor.choice_catalog import refresh_object_choices
        refresh_object_choices(plot)
    restore(doc, after)
    record_view_edit(doc, "删除曲线" if deleted else "显示曲线" if visible else "隐藏曲线", before, after, restore)


def legend_visible(doc, key, visible, deleted=False):
    from tailor.text_style_controls import record_view_edit
    before = copy.deepcopy(doc.presentation.legend)
    after = copy.deepcopy(before)
    field = "deleted_entries" if deleted else "hidden_entries"
    values = set(after.get(field, []))
    values.discard(key) if visible else values.add(key)
    after[field] = sorted(values)
    def restore(plot, cfg):
        plot.presentation.legend = copy.deepcopy(cfg)
        plot.presentation.apply_legend()
        plot.legend_controls.sync()
        from tailor.choice_catalog import refresh_object_choices
        refresh_object_choices(plot)
    restore(doc, after)
    record_view_edit(doc, "删除图例行" if deleted else "显示图例行" if visible else "隐藏图例行", before, after, restore)


def remove(doc, chosen=None, delete_data=None):
    chosen = chosen or target(doc)
    if chosen is None:
        return
    kind, key = chosen
    if kind == 'axis-factor':
        return factor_visible(doc, key, False, deleted=True)
    if kind == 'curves-all':
        return bulk_curves(doc, delete=True)
    if kind == 'processing-result':
        from tailor.processing_workflow import selected_record
        from tailor.result_pages import delete_processing
        record = selected_record(doc.processing_controls)
        if record:
            return delete_processing(SimpleNamespace(owner=doc.main_window,
                record=record, record_id=key))
        return
    if kind == "columns":
        doc.column_preferences.delete_columns()
        return
    if kind == "drawn":
        from tailor.fit_workflow import fit_owner
        fitted=fit_owner(doc,key)
        if fitted and ':component:' not in key and not key.startswith('component:'):
            source,result_id=fitted
            record=next((r for r in source.fit_records if r['id']==result_id),None)
            if record:
                from tailor.result_pages import delete_fit
                delete_fit(SimpleNamespace(plot=source,record=record), delete_data=delete_data)
                if doc.presentation.multi:doc.queue_source_draw()
                return
        if key == "fit" or key.startswith("fit:"):
            record = next((r for r in doc.fit_records if r["id"] == (doc.active_fit_id if key == "fit" else key.split(":", 1)[1])), None)
            if record:
                from tailor.result_pages import delete_fit
                delete_fit(SimpleNamespace(plot=doc, record=record), delete_data=delete_data)
                return
        drawn_visible(doc, key, False, True)
        return
    if kind == "annotation":
        doc.annotations.delete()
        return
    if kind == "inset":
        root(doc).extras.collection.delete_entry()
        return
    if kind == "fit":
        from tailor.result_pages import delete_fit

        record = next(r for r in doc.fit_records if r["id"] == key)
        delete_fit(SimpleNamespace(plot=doc, record=record), delete_data=delete_data)
        return
    if kind == "legend-row":
        legend_visible(doc, key, False, True)
        return
    if kind == "legend":
        change_legend(doc, False, deleted=True)
        return
    if kind == "axis":
        from tailor.text_style_controls import record_view_edit

        old = doc.presentation.axes[key]["title_visible"]

        def restore(plot, value):
            plot.presentation.axes[key]["title_visible"] = value
            plot.presentation.apply_axes()

        restore(doc, False)
        record_view_edit(doc, "删除轴标题", old, False, restore)
        return
    if kind == "curve":
        from tailor.result_pages import dependencies

        sheet = key.data_sheet
        model = sheet.model
        column = key.model.y_col
        deps = dependencies(doc.main_window, {(sheet.id, column)}, skip_graph=key)
        # The selected curve itself is being explicitly removed.
        with_data = delete_data_choice(doc.main_window, deps, delete_data)
        if with_data is None:
            return
        start = list(model._history[: model._cursor])
        curve_visible(doc, key, False, True)
        if with_data and column in model.columnLabels():
            remove_column_graphs(doc.main_window, sheet, {column})
            if not model.remove_spans(
                [(list(model.columnLabels()).index(column), 1)], columns=True
            ):
                while any(
                    id(e) not in {id(old) for old in start}
                    for e in model._history[: model._cursor]
                ):
                    model.undo()
                return
        combine(model, start, "删除曲线及数据" if with_data else "删除曲线")


def hide(doc, chosen=None):
    chosen = chosen or target(doc)
    if chosen is None:
        return
    kind, key = chosen
    if kind == 'axis-factor':
        return factor_visible(doc,key,False)
    if kind == 'curves-all':
        return bulk_curves(doc)
    if kind == 'processing-result':
        from tailor.processing_workflow import hide_selected
        return hide_selected(doc.processing_controls)
    if kind == "columns":
        doc.column_preferences.hide_columns()
    elif kind == "annotation":
        doc.annotations.replace({**doc.annotations.current(), "visible": False})
    elif kind == "inset":
        root(doc).extras.collection.set_hidden(key, True)
    elif kind == "fit":
        doc.fit_actions.set_hidden(key, True)
    elif kind == "legend-row":
        legend_visible(doc, key, False)
    elif kind == "legend":
        change_legend(doc, False)
    elif kind == "drawn":
        from tailor.fit_workflow import fit_owner
        fitted=fit_owner(doc,key)
        if fitted and ':component:' not in key and not key.startswith('component:'):
            fitted[0].fit_actions.set_hidden(fitted[1],True)
            if doc.presentation.multi:doc.queue_source_draw()
        else:
            drawn_visible(doc, key, False)
    elif kind == "curve":
        curve_visible(doc, key, False)


def bulk_curve_targets(doc):
    sources = list(doc.model._plots) if doc.presentation.multi else [doc]
    fits = [(source, record['id']) for source in sources
            for record in getattr(source, 'fit_records', [])]
    return sources, fits


def bulk_curves(doc, delete=False):
    """Delegate every curve to the existing command, sharing one undo entry."""
    sources, fits = bulk_curve_targets(doc)
    if not sources:
        return
    model = sources[0].data_sheet.model
    before = list(model._history[:model._cursor])
    with_data = False
    if delete:
        from tailor.result_pages import dependencies
        outputs = {(source.data_sheet.id, source.model.y_col) for source in sources}
        from tailor.fit_results import record_columns
        outputs.update((source.data_sheet.id, key)
                       for source in sources for record in source.fit_records
                       for key in record_columns(record))
        deps = dependencies(doc.main_window, outputs, skip_graph=doc)
        with_data = delete_data_choice(doc.main_window, deps)
        if with_data is None:
            return
    for source, record_id in fits:
        if delete:
            from tailor.result_pages import delete_fit
            record = next((r for r in source.fit_records if r['id'] == record_id), None)
            if record:
                delete_fit(SimpleNamespace(plot=source, record=record), delete_data=with_data)
        else:
            source.fit_actions.set_hidden(record_id, True)
    for source in sources:
        if doc.presentation.multi and source not in doc.model._plots:
            continue
        if source.model.y_col not in source.data_sheet.model.columnLabels():
            continue
        if delete:
            remove(doc, ('curve', source), delete_data=with_data)
        else:
            curve_visible(doc, source, False)
    if doc.presentation.multi and not delete:
        doc.draw_plot()
    combine(model, before, '删除全部曲线' if delete else '隐藏全部曲线')


def hidden_items(doc, scope=None):
    """Each hidden selector uses the same canonical order as its visible list."""
    from tailor.choice_catalog import column_rank,curve_rank,object_rank,seed_objects
    from tailor.column_titles import display
    from tailor.annotations import annotation_caption
    from tailor.preference_pages import available_curves
    owner=doc.main_window
    result=[]
    if scope in (None,'columns'):
        for sheet in owner.get_data_sheets():
            for i,key in enumerate(sheet.model.columnLabels()):
                if str(sheet.model.column_metadata(i).get('hidden','false')).lower()=='true':
                    result.append(('列 · '+display(sheet.model,key),lambda s=sheet,k=key:s.model.set_column_metadata(list(s.model.columnLabels()).index(k),hidden='false')))
    graphs=[doc] if scope else [owner.ui.tabWidget.widget(i) for i in range(owner.ui.tabWidget.count())]
    for plot in graphs:
        if not hasattr(plot,'presentation'):continue
        seed_objects(plot)
        groups={name:[] for name in ('曲线','拟合','图例','标注','局部放大','轴端倍率')}
        seen=set()
        def add(group,identity,title,callback,rank):
            if identity in seen:return
            seen.add(identity);groups[group].append((rank,title,callback))
        sources=list(plot.model._plots) if plot.presentation.multi else [plot]
        for source in sources:
            if scope in {None,'curves','fit'}:
                for record in source.fit_records:
                    if record.get('hidden'):
                        add('拟合',('fit',source.id,record['id']),display(source.data_sheet.model,record.get('column_id')) or '结果列已删除',
                            lambda s=source,k=record['id']:s.fit_actions.set_hidden(k,False),column_rank(source.data_sheet.model,record.get('column_id')))
            if scope not in {None,'curves','processing'}:continue
            info=plot.model.get_plot_info(source) if plot.presentation.multi else None
            visible=info.visible if info is not None else source.curve_style.visible
            if scope=='processing':
                labels=list(source.data_sheet.model.columnLabels())
                if source.model.y_col not in labels:continue
                meta=source.data_sheet.model.column_metadata(labels.index(source.model.y_col))
                try: provenance=__import__('json').loads(meta.get('source') or '{}')
                except (ValueError,TypeError):provenance={}
                if not isinstance(provenance,dict) or not provenance.get('recipe'):continue
            if not visible and source.id not in plot.presentation.extra_settings.get('deleted_curves',[]):
                add('曲线',('source',source.id),display(source.data_sheet.model,source.model.y_col),
                    lambda p=plot,s=source:curve_visible(p,s,True),column_rank(source.data_sheet.model,source.model.y_col))
        if scope in {None,'curves','processing','fit'}:
            catalog=available_curves(plot)
            from tailor.fit_workflow import fit_owner
            for key,state in plot.presentation.extra_settings.get('drawn_visibility',{}).items():
                if state!='hidden':continue
                fitted=fit_owner(plot,key)
                if scope=='fit' and fitted is None:continue
                if scope=='processing' and not key.startswith('processing'):continue
                identity=('drawn',key)
                if fitted and ':component:' not in key and not key.startswith('component:'):
                    identity=('fit',fitted[0].id,fitted[1])
                add('拟合' if fitted else '曲线',identity,catalog.get(key,(None,key))[1],lambda p=plot,k=key:drawn_visible(p,k,True),curve_rank(plot,key))
        if scope in {None,'legend'} and not plot.presentation.legend.get('deleted',False):
            if not plot.presentation.legend.get('visible',True):
                add('图例',('legend',None),'整个图例',lambda p=plot:change_legend(p,True),-1)
            from tailor.legend_entries import entry_caption
            for i,key in enumerate(plot.presentation.legend.get('hidden_entries',[])):
                if key in plot.presentation.legend.get('deleted_entries',[]):continue
                rank=curve_rank(plot,key)
                if rank==10**9:
                    order=plot.presentation.legend.get('entry_order',[]);rank+=order.index(key) if key in order else i
                add('图例',('legend',key),entry_caption(plot,key),lambda p=plot,k=key:legend_visible(p,k,True),rank)
        if scope in {None,'annotations'}:
            for record in plot.annotations.records:
                if not record['visible']:
                    add('标注',('annotation',record['id']),annotation_caption(record,plot.annotations.records),
                        lambda p=plot,k=record['id']:p.annotations.replace({**next(r for r in p.annotations.records if r['id']==k),'visible':True}),object_rank(plot,'annotation',record['id']))
        collection=getattr(getattr(plot,'extras',None),'collection',None)
        if collection and scope in {None,'insets'}:
            for i,record in enumerate(collection.records):
                if not record.get('enabled'):
                    add('局部放大',('inset',record['id']),f'局部放大{i+1}',lambda c=collection,k=record['id']:c.set_hidden(k,False),object_rank(plot,'inset',record['id']))
        if scope is None:
            for key in plot.presentation.extra_settings.get('hidden_factors',{}):
                add('轴端倍率',('factor',key),key,lambda p=plot,k=key:factor_visible(p,k,True),object_rank(plot,'factor',key))
        for group,entries in groups.items():
            if not entries:continue
            if scope is None:result.append((plot.name+' · '+group,None))
            result.extend((title,callback) for _,title,callback in sorted(entries,key=lambda row:row[0]))
    # Curves/fits from different sources interleave by their actual result column.
    if scope in {'curves','processing','fit','columns'}:
        from tailor.choice_catalog import title_rank
        result.sort(key=lambda row:title_rank(row[0]))
    return result


class InspectorMenu(QtWidgets.QFrame):
    def __init__(self, parent, title, items):
        super().__init__(parent)
        self.setObjectName("inspectorBody")
        self.setAutoFillBackground(True)
        self.setGeometry(parent.rect())
        self.setAttribute(QtCore.Qt.WA_StyledBackground)
        layout = QtWidgets.QVBoxLayout(self)
        back = QtWidgets.QPushButton("‹ 返回功能区")
        back.clicked.connect(self.deleteLater)
        layout.addWidget(back)
        layout.addWidget(QtWidgets.QLabel(title))
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
        body = QtWidgets.QWidget()
        rows = QtWidgets.QVBoxLayout(body)
        for label, callback in items:
            if callback is None:
                heading=QtWidgets.QLabel(label)
                from tailor.popup_controls import style_section_label
                style_section_label(heading)
                font=heading.font();font.setBold(True);font.setUnderline(True);heading.setFont(font)
                heading.setContentsMargins(8,6,8,6);rows.addWidget(heading)
                continue
            button = QtWidgets.QPushButton(label)
            button.setFixedHeight(34)
            button.setStyleSheet('QPushButton {text-align:left;padding:0 8px;}')
            button.setToolTip(label)
            button.clicked.connect(
                lambda checked=False, callback=callback: (
                    self.deleteLater(),
                    callback(),
                )
            )
            rows.addWidget(button)
        if not items:
            rows.addWidget(QtWidgets.QLabel("暂无记录"))
        rows.addStretch()
        scroll.setWidget(body)
        layout.addWidget(scroll)
        parent.installEventFilter(self)
        self.show()
        self.raise_()

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.Resize:
            self.setGeometry(self.parentWidget().rect())
        return False


def menu(doc, kind, scope=None):
    parent = getattr(doc, "preferences", doc.property_tabs)
    if kind == "hidden":
        InspectorMenu(parent, "已隐藏元素", hidden_items(doc, scope))
        return
    controls = doc.main_window.tab_controls
    sheet = controls.sheet()
    if sheet is None:
        return
    model = sheet.model
    indices = (
        list(range(model._cursor - 1, -1, -1))
        if kind == "undo"
        else list(range(model._cursor, len(model._history)))
    )

    def replay(count):
        for _ in range(count):
            getattr(model, kind)()

    items = [
        (f"{j + 1} · " + model._history[i].label, lambda n=j + 1: replay(n))
        for j, i in enumerate(indices)
    ]
    InspectorMenu(parent, "撤销历史" if kind == "undo" else "重做历史", items)

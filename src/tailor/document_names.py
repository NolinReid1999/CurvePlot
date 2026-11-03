"""Document naming and tab actions over existing graph/source identities."""

from PySide6 import QtCore, QtWidgets

from tailor.spreadsheet_model import Edit


def sources(doc):
    native = getattr(getattr(doc, "advanced_view", None), "native", None)
    if native:
        return list(
            dict.fromkeys(
                s for panel in native.live() for s in native.source_documents(panel)
            )
        )
    return (
        list(doc.model._plots)
        if getattr(getattr(doc, "presentation", None), "multi", False)
        else [doc]
        if hasattr(doc, "data_sheet")
        else []
    )


def own_name(doc):
    return getattr(doc, "_curve_own_name", doc.name)


def y_prefix(doc):
    from tailor.column_titles import letters
    return ",".join(dict.fromkeys(
        letters(list(item.data_sheet.model.columnLabels()).index(item.model.y_col))
        for item in sources(doc)
        if item.model.y_col in item.data_sheet.model.columnLabels()
    ))


def sync_graph_pickers(owner, roots):
    from tailor.graph_focus import GraphPicker
    for picker in owner.findChildren(GraphPicker):
        if getattr(picker.doc,'_embedded_parent',picker.doc) in roots:
            picker.sync()


def sync(owner):
    # A graph caption is an independent document property. Column metadata only
    # supplies the initial single-Y caption; later edits never rename the graph.
    changed=set()
    for i in range(owner.ui.tabWidget.count()):
        doc = owner.ui.tabWidget.widget(i)
        items = sources(doc)
        if not items:
            continue
        if not hasattr(doc, "_curve_own_name"):
            from tailor.column_titles import remark
            saved = doc.presentation.extra_settings.get("document_name")
            doc._curve_own_name = saved or (
                remark(items[0].data_sheet.model, items[0].model.y_col)
                if len(items) == 1 else f"绘图{doc.id}"
            )
        if doc.name!=doc._curve_own_name:changed.add(doc)
        doc.name = doc._curve_own_name
        doc.presentation.extra_settings["document_name"] = doc.name
    if changed:sync_graph_pickers(owner,changed)


def rename(owner, doc, value):
    value = value.strip()
    if not value:
        return False
    items = sources(doc)
    if items:
        sync(owner)
        model = items[0].data_sheet.model
        before = doc.name
        def restore(name):
            doc._curve_own_name = name
            doc.name = name
            doc.presentation.extra_settings["document_name"] = name
            doc.presentation.extra_settings["custom_document_name"] = True
            owner.tab_controls.refresh()
            sync_graph_pickers(owner,{doc})
        restore(value)
        model._record(Edit("图形重命名", lambda: restore(before), lambda: restore(value), 1024))
    else:
        model = doc.model
        before = doc.name

        def restore(name):
            doc.name = name
            owner.project_name = name
            owner.tab_controls.refresh_project_name()
            owner.tab_controls.refresh()

        restore(value)
        model._record(Edit("工作表重命名", lambda: restore(before), lambda: restore(value), 1024))
    owner.tab_controls.refresh()
    owner.mark_project_dirty()
    return True


def delete(owner, doc):
    if not sources(doc):
        return
    from tailor.result_pages import page

    tabs = owner.ui.tabWidget
    sheet = sources(doc)[0].data_sheet.model
    graphs = [doc]
    positions = [(g, tabs.indexOf(g)) for g in graphs if tabs.indexOf(g) >= 0]
    notebook = page(owner, "fit", False)
    fit_entries = []
    notebook_index = tabs.indexOf(notebook) if notebook is not None else -1
    if notebook is not None:
        fit_entries = [
            (notebook.tabs.widget(i), i)
            for i in range(notebook.tabs.count())
            if notebook.tabs.widget(i).plot in graphs
        ]
    state = owner.window_mode.snapshot()

    def remove():
        blocker = QtCore.QSignalBlocker(tabs)
        for graph, index in positions:
            owner.window_mode.forget(graph)
            if tabs.indexOf(graph) >= 0:
                tabs.removeTab(tabs.indexOf(graph))
            graph.hide()
        if notebook is not None:
            for widget, index in fit_entries:
                slot = notebook.tabs.indexOf(widget)
                if slot >= 0:
                    notebook.tabs.removeTab(slot)
                widget.hide()
            notebook.sync()
            if not notebook.tabs.count() and tabs.indexOf(notebook) >= 0:
                tabs.removeTab(tabs.indexOf(notebook))
        del blocker
        owner.refresh_project_tree()

    def restore():
        blocker = QtCore.QSignalBlocker(tabs)
        for graph, index in sorted(positions, key=lambda v: v[1]):
            tabs.insertTab(min(index, tabs.count()), graph, graph.name)
        if notebook is not None:
            if notebook_index >= 0 and tabs.indexOf(notebook) < 0:
                tabs.insertTab(
                    min(notebook_index, tabs.count()), notebook, notebook.name
                )
            for widget, index in fit_entries:
                notebook.tabs.insertTab(
                    min(index, notebook.tabs.count()), widget, widget.name
                )
                widget.show()
            notebook.sync()
        del blocker
        tabs.setCurrentWidget(doc)
        if state.get("enabled"):
            owner.window_mode.restore(state)
        owner.tab_controls.refresh()

    remove()
    sheet._record(Edit("删除图形", restore, remove, 4096))


def install(owner):
    bar = owner.ui.tabWidget.tabBar()
    bar.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)

    def show(point):
        index = bar.tabAt(point)
        if index < 0:
            return
        doc = owner.ui.tabWidget.widget(index)
        items = sources(doc)
        menu = QtWidgets.QMenu(bar)
        if items or hasattr(doc, "model") and hasattr(doc.model, "columnLabels"):
            action = menu.addAction("重命名…")

            def ask():
                value, accepted = QtWidgets.QInputDialog.getText(
                    owner,
                    "重命名",
                    "图名称" if items else "工作表名称",
                    text=own_name(doc) if items else doc.name,
                )
                if accepted:
                    rename(owner, doc, value)

            action.triggered.connect(ask)
            if len(items) > 1:
                info = menu.addMenu("包含的列")
                for item in items:
                    action = info.addAction(__import__("tailor.column_titles",fromlist=["display"]).display(item.data_sheet.model,item.model.y_col))
                    action.setEnabled(False)
            from tailor.plot_types import icon
            action = menu.addAction(icon("trash-2",bar,"#d34b48"),"删除")
            action.setEnabled(bool(items))
            action.triggered.connect(lambda: delete(owner, doc))
        else:
            action = menu.addAction("在结果页删除单项记录")
            action.setEnabled(False)
        menu.exec(bar.mapToGlobal(point))
        menu.deleteLater()

    bar.customContextMenuRequested.connect(show)

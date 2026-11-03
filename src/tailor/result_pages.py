"""Project result notebooks; original fit widgets and column provenance are reused."""

import copy
import json
from types import SimpleNamespace

from PySide6 import QtCore, QtWidgets


class ResultPage(QtWidgets.QWidget):
    def __init__(self, owner, kind):
        super().__init__()
        self.owner, self.result_kind = owner, kind
        self.language = 'zh'
        self.ui = SimpleNamespace()
        self.document_kind = "fit" if kind == "fit" else "processing"
        self.name = "拟合结果" if kind == "fit" else "处理记录"
        self.tabs = QtWidgets.QTabWidget()
        from tailor.document_tabs import DocumentTabBar

        self.tabs.setTabBar(DocumentTabBar(self.tabs))
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.delete)
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.addWidget(self.tabs)
        self.delete_button = QtWidgets.QPushButton("删除当前结果")
        self.delete_button.clicked.connect(
            lambda: self.delete(self.tabs.currentIndex())
        )
        self.info_button = QtWidgets.QPushButton('添加当前信息到图')
        self.info_button.clicked.connect(self.add_information)
        self.info_menu = QtWidgets.QMenu(self.info_button)
        buttons = QtWidgets.QHBoxLayout()
        self.language_label = QtWidgets.QLabel('信息语言')
        buttons.addWidget(self.language_label)
        self.language_buttons = {}
        language_group = QtWidgets.QButtonGroup(self)
        language_group.setExclusive(True)
        from tailor.compact_controls import toggle_button
        for code, title in (('zh', '中文'), ('en', 'English')):
            button = toggle_button(title)
            button.setChecked(code == self.language)
            button.setFixedHeight(30)
            language_group.addButton(button)
            button.clicked.connect(lambda checked=False, code=code: self.set_language(code))
            self.language_buttons[code] = button
            buttons.addWidget(button)
        buttons.addStretch()
        buttons.addWidget(self.info_button); buttons.addWidget(self.delete_button)
        for button in (self.info_button,self.delete_button):
            button.setFixedHeight(30)
        root.addLayout(buttons)
        self.tabs.currentChanged.connect(self.sync)

    def set_language(self, language, record_history=True):
        language = 'en' if language == 'en' else 'zh'
        before, self.language = self.language, language
        for code, button in self.language_buttons.items():
            with QtCore.QSignalBlocker(button):
                button.setChecked(code == language)
        english = language == 'en'
        self.language_label.setText('Language' if english else '信息语言')
        self.info_button.setText('Add selected information to graph' if english else '添加当前信息到图')
        self.delete_button.setText('Delete current result' if english else '删除当前结果')
        for index in range(self.tabs.count()):
            self.tabs.widget(index).set_language(language)
        self.update_information_button()
        if record_history and before != language:
            from tailor.spreadsheet_model import Edit
            import weakref
            import shiboken6
            reference = weakref.ref(self)
            def apply(value):
                target = reference()
                if target is not None and shiboken6.isValid(target):
                    target.set_language(value, False)
            sheets = self.owner.get_data_sheets()
            if sheets:
                sheets[0].model._record(Edit('结果信息语言', lambda: apply(before), lambda: apply(language), 1024))

    def sync(self,*args):
        self.tabs.tabBar().setVisible(self.tabs.count() > 1)
        self.delete_button.setEnabled(self.tabs.count() > 0)
        self.update_information_button()
        for i in range(self.tabs.count()):
            self.tabs.setTabText(i, self.tabs.widget(i).name)
            self.tabs.tabBar().setTabData(
                i, "processing" if self.result_kind == "processing" else "fit"
            )

    def update_information_button(self):
        from tailor.result_information import graph_documents
        item=self.tabs.currentWidget()
        eligible=any(getattr(getattr(g,'advanced_view',None),'cfg',{}).get('kind')!='3d'
                     for g in graph_documents(self.owner))
        selected=bool(item and hasattr(item,'information') and item.information.selected_rows())
        self.info_button.setEnabled(eligible and selected)
        if self.language == 'en':
            tip = 'Insert a movable, resizable image snapshot. Add a new snapshot after recalculation.' if eligible else 'Create a graph that supports image annotations first.'
        else:
            tip = '添加为可拖动、缩放的图片快照；重算后需重新添加。' if eligible else '请先创建支持图片标注的图形。'
        self.info_button.setToolTip(tip)

    def add_information(self):
        from tailor.result_information import graph_documents, add_image_to_graph
        if self.owner.data_operation_busy():
            self.owner.statusBar().showMessage('请等待当前操作完成后添加结果信息。')
            return
        current=self.tabs.currentWidget()
        if current is None:
            return
        def insert(graph):
            try:
                if graph not in graph_documents(self.owner):
                    raise ValueError('目标图已关闭，请重新选择。')
                return add_image_to_graph(self.owner,graph,current.information)
            except ValueError as error:
                self.owner.statusBar().showMessage(str(error))
        graphs=graph_documents(self.owner)
        if len(graphs)==1:
            return insert(graphs[0])
        if graphs:
            self.info_menu.clear()
            from tailor.document_names import own_name
            for graph in graphs:
                action=self.info_menu.addAction(own_name(graph),lambda checked=False,g=graph:insert(g))
                if getattr(getattr(graph,'advanced_view',None),'cfg',{}).get('kind')=='3d':
                    action.setEnabled(False);action.setToolTip('三维图暂不支持图片标注。')
            self.info_menu.popup(self.info_button.mapToGlobal(QtCore.QPoint(0,self.info_button.height())))

    def add(self, widget):
        if hasattr(widget,'information'):
            widget.information.owner=self.owner
            widget.information.informationChanged.connect(self.update_information_button)
        widget.set_language(self.language)
        self.tabs.addTab(widget, widget.name)
        self.sync()

    def remove(self, widget):
        index = self.tabs.indexOf(widget)
        if index >= 0:
            self.tabs.removeTab(index)
            if hasattr(getattr(widget, "ui", None), "plot_widget"):
                widget.ui.plot_widget.close()
            widget.deleteLater()
        self.sync()
        if self.tabs.count() == 0:
            self.owner.ui.tabWidget.removeTab(self.owner.ui.tabWidget.indexOf(self))

    def delete(self, index):
        if index < 0 or self.owner.data_operation_busy():
            return
        item = self.tabs.widget(index)
        if self.result_kind == "fit":
            delete_fit(item)
        else:
            delete_processing(item)

    def dispose(self):
        for index in range(self.tabs.count()):
            child = self.tabs.widget(index)
            if hasattr(getattr(child, "ui", None), "plot_widget"):
                child.ui.plot_widget.close()


def page(owner, kind, create=True):
    attr = "_" + kind + "_result_page"
    result = getattr(owner, attr, None)
    if result is None and create:
        result = ResultPage(owner, kind)
        setattr(owner, attr, result)
    if result is not None and create and owner.ui.tabWidget.indexOf(result) < 0:
        owner.ui.tabWidget.addTab(result, result.name)
    return result


def fit_tabs(owner):
    result = page(owner, "fit", False)
    return (
        []
        if result is None
        else [result.tabs.widget(i) for i in range(result.tabs.count())]
    )


def remove_fit_tab(owner, tab):
    result = page(owner, "fit", False)
    if result is not None:
        result.remove(tab)


def dependencies(owner, outputs, skip_fit=None, skip_recipe=None, skip_graph=None):
    """Use stable sheet/column keys, never display labels, to find consumers."""
    from tailor.analysis_records import records
    from tailor.cst_names import get_variable_names

    found = set()
    for plot in owner.get_plots():
        model = plot.model
        if plot is not skip_graph and any(
            (plot.data_sheet.id, key) in outputs
            for key in (model.x_col, model.y_col, model.x_err_col, model.y_err_col)
        ):
            found.add("曲线：" + plot.name)
        for record in plot.fit_records:
            if (plot, record["id"]) == skip_fit:
                continue
            if any(
                (plot.data_sheet.id, key) in outputs
                for key in record["settings"]["columns"]
            ):
                found.add("拟合：" + record["name"])
    for item in records(owner):
        recipe = item["recipe"]
        if recipe["id"] == skip_recipe:
            continue
        refs = {(c["sheet"], c["key"]) for c in recipe["objects"]}
        refs |= {(c["sheet"], c["xkey"]) for c in recipe["objects"] if c.get("xkey")}
        reference = recipe["options"].get("reference")
        if reference:
            refs.add(tuple(reference))
        if refs & outputs:
            found.add("处理：" + recipe["title"])
    for sheet in owner.get_data_sheets():
        for (
            key,
            expression,
        ) in sheet.model.data_model._calculated_column_expression.items():
            if (sheet.id, key) not in outputs and any(
                (sheet.id, k) in outputs for k in get_variable_names(expression)
            ):
                found.add("计算列：" + sheet.model.data_model.get_column_name(key))
    return sorted(found)


def allow_delete(owner, dependents):
    if not dependents:
        return True
    answer = QtWidgets.QMessageBox.question(
        owner,
        "结果仍被引用",
        "以下对象依赖此结果：\n"
        + "\n".join(dependents)
        + "\n\n继续将删除记录并保留结果列，避免破坏这些对象。",
        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel,
        QtWidgets.QMessageBox.Cancel,
    )
    return answer == QtWidgets.QMessageBox.Yes


def delete_fit(tab, delete_data=None):
    from tailor.fit_results import StoredFit, show_result, record_columns
    from tailor.spreadsheet_model import Edit

    plot, record = tab.plot, tab.record
    initial_history = list(plot.data_sheet.model._history[:plot.data_sheet.model._cursor])
    owner, sheet = plot.main_window, plot.data_sheet.model
    columns = set(record_columns(record))
    deps = dependencies(
        owner, {(plot.data_sheet.id, key) for key in columns}, skip_fit=(plot, record["id"])
    )
    from tailor.element_actions import delete_data_choice
    delete_data = delete_data_choice(owner, deps, delete_data)
    if delete_data is None:
        return False
    before = copy.deepcopy(plot.fit_records)
    prior_active = plot.active_fit_id
    after = [r for r in before if r["id"] != record["id"]]
    labels = list(sheet.columnLabels())
    edit = None
    tags = {f"fit:{record['id']}"} | {
        f"fit:{record['id']}:component:{c['index']}" for c in record.get('components', [])}
    owned = {k for k in columns if k in labels and sheet._metadata.get(k, {}).get('source') in tags}
    if owned and delete_data:
        from tailor.element_actions import remove_column_graphs
        remove_column_graphs(owner, plot.data_sheet, owned)
        labels = list(sheet.columnLabels())
        if not sheet.remove_spans([(labels.index(k), 1) for k in owned], columns=True):
            return False
        edit = sheet._history[sheet._cursor - 1]

    def restore(records, active):
        plot.fit_records = copy.deepcopy(records)
        plot.active_fit_id = active
        current = next((r for r in plot.fit_records if r["id"] == active), None)
        plot.model.best_fit = (
            StoredFit(current, plot.model)
            if current and not current.get("stale")
            else None
        )
        for child in list(fit_tabs(owner)):
            if child.plot is plot:
                remove_fit_tab(owner, child)
        for r in plot.fit_records:
            show_result(plot, r, focus=False)
        plot.plot_best_fit()
        plot.refresh_legend()
        owner.mark_project_dirty()

    next_active = (
        prior_active
        if any(r["id"] == prior_active for r in after)
        else (after[-1]["id"] if after else None)
    )

    def replay(records, active, forward):
        if edit and (edit.forward() if forward else edit.backward()) is False:
            return False
        restore(records, active)
        return True

    restore(after, next_active)
    history = Edit(
        "删除拟合结果",
        lambda: replay(before, prior_active, False),
        lambda: replay(after, next_active, True),
        (edit.size if edit else 0) + len(json.dumps(before).encode()) + 4096,
    )
    if edit:
        sheet._history[sheet._cursor - 1] = history
        sheet.historyChanged.emit()
    else:
        sheet._record(history)
    from tailor.element_actions import combine

    combine(sheet, initial_history, "删除拟合及关联数据")
    return True


class ProcessingRecord(QtWidgets.QWidget):
    def __init__(self, owner, record):
        super().__init__()
        self.owner = owner
        self.record_id = record["recipe"]["id"]
        self.name = record["recipe"]["title"]
        layout = QtWidgets.QVBoxLayout(self)
        self.details = QtWidgets.QLabel()
        self.details.setWordWrap(True)
        self.details.setTextFormat(QtCore.Qt.PlainText)
        self.details.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.details.setParent(self); self.details.hide()
        from tailor.result_information import ResultInformation, result_plot
        from tailor.fold_panel import FoldPanel
        self.panel=FoldPanel(self)
        layout.addWidget(self.panel)
        self.information=ResultInformation('处理结果',self)
        from tailor.result_information import processing_rows
        self.information.provider=lambda language: processing_rows(self,language)
        self.panel.add_section('结果信息',self.information,True)
        self.outputs = QtWidgets.QTableWidget(0, 5)
        self.outputs.setHorizontalHeaderLabels(
            ["工作表", "结果列", "结果名称（可编辑）", "处理类型", "有效 / 缺失 / 排除"]
        )
        self.outputs.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.Interactive
        )
        self.outputs.horizontalHeader().setStretchLastSection(True)
        self.outputs.itemChanged.connect(self.rename)
        self.outputs.cellDoubleClicked.connect(self.locate)
        self.panel.add_section('结果列',self.outputs,True)
        self.spectrum=result_plot()
        self.spectrum.setMinimumHeight(220)
        self.spectrum.setLabel('bottom','频率')
        self.spectrum.hide()
        self.spectrum_section=self.panel.add_section('结果图',self.spectrum,True)
        row = QtWidgets.QHBoxLayout()
        self.action_buttons = {}
        for title, callback in (
            ("定位结果列", self.locate),
            ("重算并更新", lambda: self.rerun(False)),
            ("另存为新结果", lambda: self.rerun(True)),
        ):
            b = QtWidgets.QPushButton(title)
            b.clicked.connect(callback)
            self.action_buttons[title] = b
            row.addWidget(b)
        layout.addLayout(row)
        self.update_record(record)

    def update_record(self, record):
        from tailor.analysis_records import stale
        from tailor.column_titles import display
        from tailor.result_information import processing_method_title

        self.record = record
        recipe = record["recipe"]
        if hasattr(self,'spectrum'):
            self.spectrum.clear()
            fft=recipe.get('method','').startswith('fft_')
            self.spectrum.setVisible(fft)
            self.spectrum_section.setVisible(fft)
            if fft:
                from tailor.column_titles import remark
                for sheet,key,slot,*_ in record['outputs']:
                    meta=sheet.model.column_metadata(list(sheet.model.columnLabels()).index(key))
                    try: info=json.loads(meta.get('source') or '{}')
                    except (ValueError,TypeError):continue
                    xkey=info.get('result_x')
                    if xkey and xkey in sheet.model.columnLabels():
                        self.spectrum.plot(sheet.model.data_model.get_column(xkey),sheet.model.data_model.get_column(key),pen='#2878cc',name=remark(sheet.model,key))

        first_sheet, first_key, *_ = record["outputs"][0]
        self.name = (
            recipe["title"]
            + " · "
            + first_sheet.model.data_model.get_column_name(first_key)
        )
        sheets = {s.id: s for s in self.owner.get_data_sheets()}
        sources = []
        for obj in recipe["objects"]:
            sheet = sheets.get(obj["sheet"])
            sources.append(
                (
                    sheet.name + " · "
                    + display(sheet.model,obj['key'])
                )
                if sheet and obj["key"] in sheet.model.columnLabels()
                else "来源已删除"
            )
        labels = {
            "statistics": "统计量",
            "ddof": "标准差自由度",
            "missing": "缺失策略",
            "sampling": "采样方式",
            "points": "采样点数",
            "step": "采样步长",
            "interpolation": "插值方式",
            "reference": "参考列",
            "align": "插值对齐",
            "window": "窗口点数",
            "polyorder": "多项式阶数",
            "edge": "边缘处理",
            "value": "数值",
            "fft_window": "FFT窗函数",
            "detrend": "去趋势",
            "cutoff": "截止频率",
            "cutoff2": "上限频率",
            "order": "滤波阶数",
            "envelope_output": "包络输出",
            "endpoints": "端点策略",
            "smooth": "平滑窗口",
            "show_marks": "显示峰点",
            "prominence": "峰显著性",
            "distance": "最小峰距",
            "replicate_error": "误差类型",
        }
        def option_text(key,value):
            from tailor.column_analysis import STATISTICS
            if key=='statistics':
                return '、'.join(STATISTICS.get(k,k) for k in value)
            if key=='reference' and value:
                sheet=sheets.get(value[0])
                if sheet and value[1] in sheet.model.columnLabels():
                    from tailor.column_titles import display
                    return display(sheet.model,value[1])
            choices={
                'ddof':{0:'总体（n）',1:'样本（n−1）'},
                'missing':{'omit':'忽略并报告','raise':'遇到缺失停止'},
                'sampling':{'points':'按点数','step':'按步长'},
                'interpolation':{'linear':'线性','pchip':'保形插值','cubic':'三次样条'},
                'fft_window':{'none':'矩形窗','hann':'汉宁窗','hamming':'汉明窗','blackman':'布莱克曼窗'},
                'envelope_output':{'both':'上下包络','upper':'上包络','lower':'下包络'},
                'replicate_error':{'SD':'标准差 SD','SEM':'标准误 SEM'},
            }
            if isinstance(value,(str,int)) and key in choices:
                return choices[key].get(value,str(value))
            if isinstance(value,bool):return '开启' if value else '关闭'
            return '—' if value is None else str(value)
        parameters = "；".join(labels.get(k,k)+'：'+option_text(k,v) for k,v in recipe['options'].items())
        scopes = []
        for obj in recipe["objects"]:
            scope = obj.get("scope", {"mode": "all"})
            scopes.append(
                "全部数据"
                if scope["mode"] == "all"
                else "X范围 " + str(scope.get("range"))
                if scope["mode"] == "x"
                else "所选行 "
                + "、".join(f"{a + 1}–{b + 1}" for a, b in scope.get("ranges", []))
            )
        self.details.setText(
            "处理类型："
            + recipe["title"]
            + "\n方法："
            + processing_method_title(recipe['method'])
            + "\n来源："
            + "、".join(sources)
            + "\n参数："
            + parameters
            + "\n处理范围："
            + "；".join(scopes)
            + "\n状态："
            + (
                "已过期，源数据或输出已改变"
                if stale(self.owner, record)
                else "与源数据一致"
            )
        )
        with QtCore.QSignalBlocker(self.outputs):
            self.outputs.setRowCount(len(record["outputs"]))
            for row, (sheet, key, *_rest) in enumerate(record["outputs"]):
                from tailor.column_titles import letters

                label = sheet.model.data_model.get_column_name(key)
                provenance = json.loads(
                    sheet.model._metadata.get(key, {}).get("source") or "{}"
                )
                counts = provenance.get("counts", {})
                summary = (
                    " / ".join(str(counts[k]) for k in ("valid", "missing", "excluded"))
                    if counts
                    else "—"
                )
                for col, text in enumerate(
                    (
                        sheet.name,
                        letters(list(sheet.model.columnLabels()).index(key)),
                        label,
                        recipe["title"],
                        summary,
                    )
                ):
                    item = QtWidgets.QTableWidgetItem(text)
                    if col != 2:
                        item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
                    self.outputs.setItem(row, col, item)
        self.set_language(self.information.language)

    def set_language(self, language):
        from tailor.result_language import CATEGORIES, section_language
        self.information.set_language(language)
        english = self.information.language == 'en'
        section_language(self.panel, {'结果信息':'Result information','结果列':'Output columns','结果图':'Result plot'}, self.information.language)
        headers = ['Worksheet','Column','Result name (editable)','Operation','Valid / Missing / Excluded'] if english else ['工作表','结果列','结果名称（可编辑）','处理类型','有效 / 缺失 / 排除']
        with QtCore.QSignalBlocker(self.outputs):
            self.outputs.setHorizontalHeaderLabels(headers)
            for row in range(self.outputs.rowCount()):
                title = self.record['recipe']['title']
                self.outputs.item(row,3).setText(CATEGORIES.get(title,title) if english else title)
        actions = {'定位结果列':'Locate output','重算并更新':'Recalculate','另存为新结果':'Save as new result'}
        for title, button in self.action_buttons.items():
            button.setText(actions[title] if english else title)
        self.spectrum.setLabel('bottom','Frequency' if english else '频率')

    def rename(self, item):
        if item.column() != 2:
            return
        sheet, key, *_ = self.record["outputs"][item.row()]
        accepted = sheet.model.set_column_metadata(
            list(sheet.model.columnLabels()).index(key), name=item.text().strip()
        )
        if not accepted:
            self.update_record(self.record)

    def locate(self, *args):
        row = max(0, self.outputs.currentRow())
        sheet, key, *_ = self.record["outputs"][row]
        self.owner.ui.tabWidget.setCurrentWidget(sheet)
        index = sheet.page_model.index(0, list(sheet.model.columnLabels()).index(key))
        sheet.ui.data_view.setCurrentIndex(index)
        sheet.ui.data_view.scrollTo(index)

    def rerun(self, as_new):
        from tailor.analysis_records import rerun

        sheet = self.record["outputs"][0][0]
        rerun(sheet.processing_controls, self.record, as_new)


def refresh_processing(owner):
    from tailor.analysis_records import records

    items = {r["recipe"]["id"]: r for r in records(owner)}
    from tailor.processing_workflow import refresh_results
    for doc in [owner.ui.tabWidget.widget(i) for i in range(owner.ui.tabWidget.count())]:
        control=getattr(doc,'processing_controls',None)
        if control is not None:refresh_results(control)
    notebook = page(owner, "processing", bool(items))
    if notebook is None:
        return
    for i in reversed(range(notebook.tabs.count())):
        child = notebook.tabs.widget(i)
        if child.record_id not in items:
            notebook.remove(child)
    existing = {
        notebook.tabs.widget(i).record_id: notebook.tabs.widget(i)
        for i in range(notebook.tabs.count())
    }
    for identifier, record in items.items():
        if identifier in existing:
            existing[identifier].update_record(record)
        else:
            notebook.add(ProcessingRecord(owner, record))
    notebook.sync()


def delete_processing(tab):
    from tailor.analysis_records import monitor

    owner, record = tab.owner, tab.record
    outputs = {(s.id, k) for s, k, *_ in record["outputs"]}
    deps = dependencies(owner, outputs, skip_recipe=tab.record_id)
    if not allow_delete(owner, deps):
        return False
    # All outputs normally belong to one source sheet; use its existing atomic
    # structural transaction, including provenance, data and metadata for undo.
    for sheet in {s for s, *_ in record["outputs"]}:
        keys = {k for s, k, *_ in record["outputs"] if s is sheet}
        if deps:

            def detach(sheet=sheet, keys=keys):
                for key in keys:
                    sheet.model._metadata[key]["source"] = ""

            sheet.model._structural("删除处理记录（保留引用数据）", detach)
        else:
            labels = list(sheet.model.columnLabels())
            if not sheet.model.remove_spans(
                [(labels.index(k), 1) for k in keys], columns=True
            ):
                return False
    refresh_processing(owner)
    monitor(owner).timer.start()
    return True


def snapshot(owner):
    result = {}
    for kind in ("fit", "processing"):
        notebook = page(owner, kind, False)
        if notebook is not None:
            result[kind] = {
                "order": [
                    getattr(
                        notebook.tabs.widget(i),
                        "record_id",
                        getattr(notebook.tabs.widget(i), "id", None),
                    )
                    for i in range(notebook.tabs.count())
                ],
                "current": notebook.tabs.currentIndex(),
                "language": notebook.language,
                "information": {
                    str(getattr(notebook.tabs.widget(i),'record_id',getattr(notebook.tabs.widget(i),'id',None))):
                        dict(notebook.tabs.widget(i).information.choices)
                    for i in range(notebook.tabs.count()) if hasattr(notebook.tabs.widget(i),'information')
                },
            }
    return result


def restore_order(owner, state):
    for kind, config in state.items():
        notebook = page(owner, kind, False)
        if notebook is None:
            continue
        notebook.set_language(config.get('language','zh'), False)
        bar = notebook.tabs.tabBar()
        for target, identifier in enumerate(config.get("order", [])):
            for i in range(notebook.tabs.count()):
                item = notebook.tabs.widget(i)
                if getattr(item, "record_id", getattr(item, "id", None)) == identifier:
                    bar.moveTab(i, target)
                    break
        notebook.tabs.setCurrentIndex(config.get("current", 0))
        for i in range(notebook.tabs.count()):
            item=notebook.tabs.widget(i)
            identifier=str(getattr(item,'record_id',getattr(item,'id',None)))
            information=getattr(item,'information',None)
            if information is not None:
                choices=config.get('information',{}).get(identifier,{})
                information.choices={k:v for k,v in choices.items() if isinstance(k,str) and isinstance(v,bool)}
                information.set_rows(information.rows)

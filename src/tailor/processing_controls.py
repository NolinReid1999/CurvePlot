"""Shared column processing inspector over existing spreadsheet/plot engines."""

import json
from collections import defaultdict

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

from tailor.column_analysis import (
    BINARY,
    MATHEMATICS,
    PREPROCESS,
    REGIONS,
    SIGNALS,
    STATISTICS,
    analyze,
)
from tailor.compact_controls import toggle_button
from tailor.graph_defaults import derived_width
from tailor.envelope_analysis import ENVELOPES
from tailor.fold_panel import FoldPanel
from tailor.graph_controls import combo, number, row
from tailor.ui_widgets import data_index


class ColumnMenu(QtWidgets.QMenu):
    def addSection(self,text):
        # A native separator can be only 7 px high even when it has text.
        # Keep a real, disabled text row for a readable category heading.
        action=self.addAction(text)
        action.setEnabled(False);action.setProperty('choiceSection',True)
        font=action.font();font.setBold(True);font.setUnderline(True);action.setFont(font)
        return action

    def paintEvent(self, event):
        from tailor.popup_controls import paint_choice_menu
        paint_choice_menu(self)

    def mouseReleaseEvent(self, event):
        action = self.actionAt(event.pos())
        if (
            action is not None
            and getattr(self, "keep_open", True)
            and action.isCheckable()
            and event.button() == QtCore.Qt.LeftButton
        ):
            action.trigger()
            return
        super().mouseReleaseEvent(event)


class ProcessingJob(QtCore.QThread):
    def __init__(self, inputs, method, options, parent):
        super().__init__(parent)
        self.inputs, self.method, self.options = inputs, method, options
        self.result = []
        self.error = ""

    def run(self):
        try:
            if self.method == "replicate":
                from tailor.envelope_analysis import repeated_measurements

                context = self.inputs[0]
                self.result = [
                    repeated_measurements(
                        context["x"],
                        context["matrix"],
                        self.options.get("replicate_error", "sd"),
                        minimum_count=int(self.options.get("minimum_count", 1)),
                    )
                ]
                return
            for context in self.inputs:
                if self.isInterruptionRequested():
                    return
                self.result.append(
                    analyze(
                        context["x"],
                        context["y"],
                        self.method,
                        self.options,
                        context.get("reference"),
                    )
                )
                self.result[-1]["counts"] = context.get("counts", {})
        except Exception as error:  # noqa: BLE001 - relay worker errors to UI
            self.error = str(error)


def source_graph(sheet, key, preferred=None):
    if preferred is not None:
        preferred = getattr(preferred, '_visible_graph_document', preferred)
        if source_on_graph(preferred, sheet, key) is not None:
            return preferred
    owner = sheet.main_window
    tabs = owner.ui.tabWidget
    graphs = [tabs.currentWidget()] + [tabs.widget(i) for i in range(tabs.count())]
    for graph in graphs:
        if not hasattr(graph, "presentation") or getattr(graph, "advanced_view", None):
            continue
        if source_on_graph(graph, sheet, key) is not None:
            return graph
    return None


def source_on_graph(graph, sheet, key):
    if graph is None:
        return None
    from tailor.document_names import sources
    candidates = [source for source in sources(graph) if source.data_sheet is sheet]
    # Prefer a directly plotted column over a fit that happens to reference
    # that column. Fitted totals/components otherwise inherit their owner's
    # axes, just like their already-visible curves.
    direct = next((source for source in candidates if source.model.y_col == key), None)
    if direct is not None:
        return direct
    return next((source for source in candidates
        if any(entry.get('column_id') == key for record in source.fit_records
               for entry in [record] + record.get('components', []))), None)


def clear_graph_previews(owner, graphs=None):
    registry = getattr(owner, "_column_previews", [])
    remaining = []
    affected = set()
    for graph, item in registry:
        if graphs is not None and graph not in graphs:
            remaining.append((graph, item))
            continue
        affected.add(graph)
        if not getattr(graph, "_graph_disposed", False):
            box = getattr(item, "_curve_preview_box", None)
            (box if box is not None else graph.ui.plot_widget).removeItem(item)
    owner._column_previews = remaining
    for graph in affected:
        if getattr(graph, "_graph_disposed", False):
            continue
        for box in getattr(graph, "_curve_preview_boxes", []):
            graph.ui.plot_widget.getViewBox().sigResized.disconnect(box._curve_resize)
            box.scene().removeItem(box)
            box.deleteLater()
        graph._curve_preview_boxes = []
        graph.presentation.apply_axes()


def frequency_box(graph):
    if graph.presentation.has_top() or graph.presentation.has_right():
        raise ValueError(
            "频域预览需要空闲的上X和右Y轴，请先关闭这些轴的曲线归属；仍可生成结果列。"
        )
    boxes = getattr(graph, "_curve_preview_boxes", [])
    if boxes:
        return boxes[0]
    plotitem = graph.ui.plot_widget.getPlotItem()
    box = pg.ViewBox(enableMenu=False)
    plotitem.scene().addItem(box)
    box.setZValue(-8)

    def resize():
        box.setGeometry(plotitem.vb.sceneBoundingRect())

    plotitem.vb.sigResized.connect(resize)
    box._curve_resize = resize
    resize()
    graph._curve_preview_boxes = [box]
    refresh_frequency_axes(graph)
    return box


def refresh_frequency_axes(graph):
    boxes = getattr(graph, "_curve_preview_boxes", [])
    if not boxes:
        return
    from tailor.graph_presentation import axis_defaults

    plotitem = graph.ui.plot_widget.getPlotItem()
    for side, label in (
        ("top", "频率（X单位的倒数）"),
        ("right", "频域幅度 / 功率密度"),
    ):
        axis = plotitem.getAxis(side)
        axis.settings = axis_defaults()
        axis.linkToView(boxes[0])
        axis.setLogMode(False)
        axis.setLabel(label)
        plotitem.showAxis(side, True)


def full_preview_range(plot):
    """Home includes previews without changing ranges when a preview is generated."""
    boxes = [plot.ui.plot_widget.getViewBox()]
    boxes += [
        b
        for b in (
            plot.presentation.right_box,
            plot.presentation.top_box,
            plot.presentation.top_right_box,
        )
        if b is not None
    ]
    boxes += getattr(plot, "_curve_preview_boxes", [])
    for box in boxes:
        values = [[], []]
        for item in box.addedItems:
            if (
                not isinstance(item, pg.PlotDataItem)
                or not item.isVisible()
                or item.xData is None
            ):
                continue
            xx, yy = item.getData()
            if xx is None or yy is None:
                continue
            good = np.isfinite(xx) & np.isfinite(yy)
            if good.any():
                values[0].extend([float(np.min(xx[good])), float(np.max(xx[good]))])
                values[1].extend([float(np.min(yy[good])), float(np.max(yy[good]))])
        if values[0] and values[1]:
            box.setRange(
                xRange=(min(values[0]), max(values[0])),
                yRange=(min(values[1]), max(values[1])),
                padding=0.05,
            )


class ProcessingControls(FoldPanel):
    resultReady = QtCore.Signal(object)
    operationFinished = QtCore.Signal(object)

    def __init__(self, document, *, deferred=False):
        super().__init__(document)
        self._build_steps = self._build(document)
        if not deferred:
            for _ in self._build_steps:
                pass

    def _build(self, document):
        self.setProperty('keepFieldTitles', True)
        self.document = document
        self.plot = document if hasattr(document, "presentation") else None
        self.owner = document.main_window
        self.job = None
        self.targets = []
        self.rows = {}
        self.preview_items = []
        self.preview = pg.PlotDataItem(pen=pg.mkPen("#d05b23", width=derived_width(self.plot)))
        self.objects = QtWidgets.QToolButton()
        self.objects.setProperty("choiceField", True)
        self.objects.setText("选择列")
        self.objects.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.objects.setSizePolicy(
            QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed
        )
        self.objects.setMinimumWidth(80)
        self.objects.setFixedHeight(30)
        self.objects.setStyleSheet("QToolButton {padding:3px 28px 3px 8px;}")
        self.object_menu = ColumnMenu(self.objects)
        self.objects.setMenu(self.object_menu)
        self.object_menu.aboutToShow.connect(self.fill_objects)
        self.multi = toggle_button("多选")
        self.multi.toggled.connect(self.multiple_changed)
        self.all_data = toggle_button("全部数据")
        self.current_data = toggle_button("当前显示数据")
        self.all_data.setChecked(True)
        group = QtWidgets.QButtonGroup(self)
        group.addButton(self.all_data)
        group.addButton(self.current_data)
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(row("对象", self.objects, self.multi))
        layout.addWidget(row("范围", self.all_data, self.current_data))
        self.add_section("对象", layout, True)
        self.options = {}
        self.methods = {}
        self.forms = {}
        yield
        self.add_method(
            "描述统计",
            [("选择统计量", "statistics")],
            ["statistics", "ddof", "missing"],
        )
        yield
        self.add_method(
            "基础数学",
            MATHEMATICS,
            ["sampling", "points", "step", "interpolation", "reference", "align"],
        )
        yield
        self.add_method(
            "平滑与校正",
            PREPROCESS,
            ["window", "polyorder", "edge", "value", "reference", "align"],
        )
        yield
        self.add_method(
            "交互区域分析",
            [(name, key) for name, key in REGIONS if key != "region_stats"],
            ["region"],
        )
        yield
        self.add_method(
            "信号分析", SIGNALS, ["fft_window", "detrend", "cutoff", "cutoff2", "order"]
        )
        yield
        self.add_method(
            "包络",
            ENVELOPES,
            [
                "envelope_output",
                "window",
                "prominence",
                "distance",
                "endpoints",
                "smooth",
                "show_marks",
            ],
        )
        yield
        self.add_method("重复测量", [("均值与误差", "replicate")], ["replicate_error"])
        from tailor.analysis_records import AnalysisControls, monitor

        yield
        self.analysis_controls = AnalysisControls(self)
        self.add_section("结果与重算", self.analysis_controls)
        from tailor.workflow_templates import WorkflowControls

        yield
        self.workflow_controls = WorkflowControls(self)
        self.add_section("模板与批处理", self.workflow_controls)
        if not self.plot:
            monitor(self.owner).attach(document)
        actions = QtWidgets.QHBoxLayout()
        from tailor.plot_types import icon
        for label, callback in [
            ("预览", lambda: self.run(self.category, False)),
            ("清除预览", self.clear_preview),
            ("生成结果", lambda: self.run(self.category, True)),
        ]:
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(callback)
            button.setMinimumWidth(0)
            button.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
            actions.addWidget(button)
        self.delete_result = QtWidgets.QToolButton()
        self.delete_result.setIcon(icon("trash-2", self, "#d34b48"))
        self.delete_result.setToolTip("删除当前类别的处理结果")
        self.delete_result.setFixedWidth(28)
        self.delete_result.setStyleSheet("QToolButton {padding:0;}")
        self.delete_result.clicked.connect(lambda: __import__("tailor.processing_preview", fromlist=["delete_menu"]).delete_menu(self, self.delete_result))
        actions.addWidget(self.delete_result)
        self.add_section("处理", actions, True)
        self.category = "描述统计"
        self.category_actions = {}
        self.select_category(self.category,expand=False)
        self.cancel = QtWidgets.QPushButton("取消处理")
        self.cancel.clicked.connect(self.cancel_job)
        self.cancel.hide()
        self.layout().addWidget(self.cancel)
        self.message = QtWidgets.QLabel()
        self.message.setWordWrap(True)
        self.message.setProperty("muted", True)
        self.layout().addWidget(self.message)
        self.message.hide()
        self.preview_card = QtWidgets.QFrame()
        self.preview_card.setProperty("foldCard", True)
        preview_layout = QtWidgets.QVBoxLayout(self.preview_card)
        preview_layout.addWidget(QtWidgets.QLabel("数据预览"))
        self.preview_table = QtWidgets.QTableWidget(0, 3)
        self.preview_table.setHorizontalHeaderLabels(["列", "项目 / X", "结果"])
        self.preview_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.preview_table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.Interactive
        )
        self.preview_table.horizontalHeader().setStretchLastSection(True)
        self.preview_table.setMinimumHeight(160)
        self.preview_table.setMaximumHeight(300)
        preview_layout.addWidget(self.preview_table)
        self.open_layout.insertWidget(self.open_layout.count() - 1, self.preview_card)
        self.preview_card.hide()
        if not self.plot:
            document.ui.data_view.selectionModel().selectionChanged.connect(
                self.follow_selection
            )
        else:
            document.ui.plot_widget.getViewBox().sigRangeChanged.connect(
                self.sync_region
            )
        yield
        from tailor.processing_workflow import install
        install(self)
        self.sync_objects_text()
        sources = [document] if not self.plot else [document.data_sheet] if hasattr(document,"data_sheet") else self.owner.get_data_sheets()
        for source in sources:
            source.model.modelReset.connect(self.render_preview)
            source.model.headerDataChanged.connect(self.refresh_column_choices)
            source.model.modelReset.connect(self.refresh_column_choices)

    @QtCore.Slot()
    def render_preview(self):
        from tailor.processing_preview import render
        render(self)

    def select_category(self, title, *, expand=True):
        title = "平滑与校正" if title == "数据预处理" else title
        self.category = title
        if hasattr(self,'category_choice'):
            with QtCore.QSignalBlocker(self.category_choice):self.category_choice.setCurrentIndex(max(0,self.category_choice.findData(title)))
        for record in self.sections:
            name = record[1].property("sectionTitle")
            record[0].setVisible(name in {title, "处理", "详情"} and (name != "处理" or title in self.methods))
            if name==title and expand:self.set_open(record,True)
        for name, action in getattr(self, "category_actions", {}).items():
            action.setChecked(name == title)
        self.scroll.verticalScrollBar().setValue(0)
        from tailor.processing_preview import render
        render(self)
        from tailor.processing_workflow import refresh_results
        refresh_results(self)
        from tailor.processing_workflow import refresh
        refresh(self)

    def install_category_picker(self,tabs,index):
        # Category selection lives in the page's fixed header, never in the tab.
        tabs.tabBar().setTabButton(index,QtWidgets.QTabBar.RightSide,None)
        if hasattr(self,'category_choice'):return
        self.category_choice=QtWidgets.QComboBox()
        for record in self.sections:
            title=record[1].property('sectionTitle')
            if title in {'对象','处理','详情'}:continue
            if not self.plot and title not in {'描述统计','基础数学','平滑与校正','重复测量','结果与重算','模板与批处理'}:continue
            self.category_choice.addItem(title,title)
        self.category_choice.setCurrentIndex(max(0,self.category_choice.findData(self.category)))
        self.category_choice.activated.connect(lambda i:self.select_category(self.category_choice.itemData(i)))
        from tailor.workflow_header import header_row
        self.object_header_row=header_row('选择数据',self.objects,self.multi)
        # The multi-select action has the same footprint as the fit help action;
        # the curve/data and model/type fields share the remaining width.
        self.multi.setFixedWidth(48)
        self.range_header_row=header_row('范围',self.all_data,self.current_data)
        self.type_header_row=header_row('处理类型',self.category_choice)
        self.category_header=self.pin_header(self.object_header_row,self.range_header_row,self.type_header_row)
        self.layout().setSpacing(0)
        from tailor.processing_workflow import install_result_picker
        install_result_picker(self)

    def sheets(self):
        return {sheet.id: sheet for sheet in self.owner.get_data_sheets()}

    def multiple_changed(self, active):
        if not active and self.targets:
            self.targets = self.targets[:1]
        self.sync_objects_text()

    @QtCore.Slot()
    def refresh_result_choice(self):
        from tailor.processing_workflow import refresh_results
        refresh_results(self)

    def fill_objects(self):
        self.object_menu.clear()
        self.object_menu.addAction('—',self.clear_objects)
        self.object_menu.keep_open = self.multi.isChecked()
        from tailor.document_names import sources
        graph=getattr(self.plot,'_visible_graph_document',self.plot) if self.plot else None
        from tailor.choice_catalog import visible_columns,graph_columns
        plotted,hidden=graph_columns(graph) if graph else (set(),set())
        allowed={(sheet.id,key) for sheet in self.sheets().values() for key in visible_columns(sheet.model)}-hidden
        self.targets=[ref for ref in self.targets if ref in allowed]
        for label,want in [('已绘制曲线',True),('未绘制曲线',False)] if graph else [('数据列',False)]:
            self.object_menu.addSection(label)
            for sheet in self.sheets().values():
                for key in visible_columns(sheet.model):
                    ref=(sheet.id,key)
                    if ref not in allowed or (ref in plotted)!=want:continue
                    action=self.object_menu.addAction(__import__('tailor.column_titles',fromlist=['display']).display(sheet.model,key))
                    action.setCheckable(True);action.setChecked(ref in self.targets)
                    action.triggered.connect(lambda active,sid=sheet.id,key=key:self.set_target(sid,key,active))
        self.sync_objects_text()
        self.fill_references()

    def set_target(self, sid, key, active):
        ref = (sid, key)
        if active and not self.multi.isChecked():
            self.targets = [ref]
        elif active and ref not in self.targets:
            self.targets.append(ref)
        elif not active and ref in self.targets:
            self.targets.remove(ref)
        self.sync_objects_text()
        if hasattr(self,'input_history'):self.input_history.commit()

    def clear_objects(self):
        self.targets=[];self.sync_objects_text()
        if hasattr(self,'input_history'):self.input_history.commit()

    def sync_objects_text(self,*args):
        available = self.sheets()
        self.targets = [ref for ref in self.targets if ref[0] in available and ref[1] in __import__("tailor.choice_catalog",fromlist=["visible_columns"]).visible_columns(available[ref[0]].model)]
        names = []
        sheets = self.sheets()
        self.targets = [
            (sid, key)
            for sid, key in self.targets
            if sid in sheets and key in sheets[sid].model.columnLabels()
        ]
        for sid, key in self.targets:
            sheet = sheets[sid]
            names.append(__import__("tailor.column_titles", fromlist=["display"]).display(sheet.model, key))
        self.objects.setText(
            names[0]
            if len(names) == 1
            else f"已选 {len(names)} 列"
            if names
            else "—"
        )
        self.objects.setToolTip("\n".join(names) or "选择一个或多个处理列")
        if hasattr(self,'execute'):self.execute.setEnabled(bool(self.targets))
        if hasattr(self,'parameter_domains'):self.parameter_domains.request()

    def follow_selection(self, *args):
        columns = set()
        for block in self.document.ui.data_view.selectionModel().selection():
            columns.update(range(block.left(), block.right() + 1))
        if columns:
            keys = list(self.document.model.columnLabels())
            self.targets = [
                (self.document.id, keys[i]) for i in sorted(columns) if i < len(keys)
            ]
            if not self.multi.isChecked():
                self.targets = self.targets[:1]
            self.sync_objects_text()
        else:
            self.targets=[]
            self.sync_objects_text()

    def add_method(self, title, methods, parameters):
        form = QtWidgets.QVBoxLayout()
        selector = combo(methods)
        from tailor.choice_buttons import ChoiceButtons

        method_row = ChoiceButtons(selector)
        form.addWidget(method_row)
        if title == "描述统计":
            method_row.hide()
        self.methods[title] = selector
        box = {}
        self.options[title] = box
        fields = QtWidgets.QVBoxLayout()
        form.addLayout(fields)
        for key in parameters:
            if key == "statistics":
                fields.addWidget(QtWidgets.QLabel("统计量（可多选，每项各生成一列）"))
                area = QtWidgets.QWidget()
                grid = QtWidgets.QGridLayout(area)
                grid.setContentsMargins(0, 0, 0, 0)
                buttons = {}
                for i, (name, label) in enumerate(STATISTICS.items()):
                    b = toggle_button(label)
                    b.setChecked(name == "mean")
                    buttons[name] = b
                    grid.addWidget(b, i // 3, i % 3)
                box[key] = buttons
                fields.addWidget(area)
                self.rows[(title, key)] = area
                continue
            choices = {
                "sampling": ("采样方式", [("按点数", "points"), ("按步长", "step")]),
                "ddof": ("统计口径", [("样本（n−1）", 1), ("总体（n）", 0)]),
                "missing": (
                    "缺失数据",
                    [("忽略并报告", "omit"), ("遇到缺失停止", "reject")],
                ),
                "edge": (
                    "边缘处理",
                    [
                        ("自动", "auto"),
                        ("镜像", "mirror"),
                        ("最近值", "nearest"),
                        ("周期", "wrap"),
                        ("零填充", "constant"),
                    ],
                ),
                "detrend": (
                    "FFT去趋势",
                    [
                        ("不去趋势", "none"),
                        ("去均值", "constant"),
                        ("去线性趋势", "linear"),
                    ],
                ),
                "endpoints": (
                    "端点策略",
                    [("原始端点", "observed"), ("保持最近峰值", "hold")],
                ),
                "show_marks": ("检测峰点", [("显示", True), ("隐藏", False)]),
            }
            if key in choices:
                label, items = choices[key]
                widget = combo(items)
                if key == "sampling":
                    widget.currentIndexChanged.connect(
                        lambda _i, t=title: self.sync_method(t)
                    )
            elif key == "envelope_output":
                widget = combo(
                    [("上下包络", "both"), ("仅上包络", "upper"), ("仅下包络", "lower")]
                )
                label = "输出结果"
            elif key == "replicate_error":
                widget = combo([("样本标准差SD", "sd"), ("标准误SEM", "sem")])
                label = "误差类型"
            elif key == "reference":
                widget = QtWidgets.QComboBox()
                label = "参考列"
            elif key == "align":
                widget = combo([("要求X相同", False), ("线性插值对齐", True)])
                label = "对齐方式"
            elif key == "interpolation":
                widget = combo(
                    [("线性", "linear"), ("保形PCHIP", "pchip"), ("三次样条", "cubic")]
                )
                label = "插值方式"
            elif key == "fft_window":
                widget = combo(
                    [("矩形窗", "boxcar"), ("Hann窗", "hann"), ("Hamming窗", "hamming")]
                )
                label = "窗函数"
            elif key == "region":
                if self.plot:
                    widget = toggle_button("显示分析区间")
                    widget.toggled.connect(self.show_region)
                    fields.addWidget(widget)
                    box[key] = widget
                    self.rows[(title, key)] = widget
                continue
            else:
                limits = {
                    "step": (0.000000001, 1e9, 1, 9),
                    "polyorder": (0, 20, 2, 0),
                    "smooth": (1, 10001, 1, 0),
                    "window": (1, 10001, 5, 0),
                    "value": (-1000000, 1000000, 0, 3),
                    "points": (2, 1000000, 200, 0),
                    "cutoff": (0.000001, 1000000, 0.1, 6),
                    "cutoff2": (0.000001, 1000000, 0.3, 6),
                    "order": (1, 12, 4, 0),
                    "prominence": (0, 1e12, 0, 6),
                    "distance": (1, 1000000, 1, 0),
                }
                label = {
                    "step": "采样步长",
                    "polyorder": "多项阶数",
                    "smooth": "包络平滑",
                    "window": "窗口点数",
                    "value": "数值",
                    "points": "采样点数",
                    "cutoff": "截止频率",
                    "cutoff2": "上限频率",
                    "order": "滤波阶数",
                    "prominence": "峰显著性",
                    "distance": "最小峰距",
                }[key]
                unit={'polyorder':'阶','smooth':'点','window':'点','points':'点','order':'阶','distance':'点'}.get(key,'')
                widget = number(*limits[key],unit=unit)
                widget.setSingleStep(
                    1
                    if key
                    in {"window", "points", "order", "distance", "polyorder", "smooth"}
                    else 0.01
                )
            box[key] = widget
            line = row(
                label,
                ChoiceButtons(widget, equal=key in {"ddof", "missing"})
                if isinstance(widget, QtWidgets.QComboBox) and key != "reference"
                else widget,
            )
            fields.addWidget(line)
            self.rows[(title, key)] = line
        if title == "信号分析":
            self.cutoff_picker = QtWidgets.QPushButton("图选截止频率")
            self.cutoff_picker.clicked.connect(self.pick_cutoffs)
            form.addWidget(self.cutoff_picker)
        summary = QtWidgets.QLabel()
        summary.setWordWrap(True)
        form.addWidget(summary)
        box["summary"] = summary
        summary.hide()
        self.add_section(title, form, title == "描述统计")
        selector.currentIndexChanged.connect(lambda *args, t=title: self.sync_method(t))
        self.sync_method(title)

    def sync_method(self, title):
        if hasattr(self,"parameter_domains"):self.parameter_domains.request()
        method = self.methods[title].currentData()
        visible = {
            "sampling": method in {"interpolate", "resample"},
            "step": method in {"interpolate", "resample"}
            and self.options[title]["sampling"].currentData() == "step",
            "statistics": method in {"statistics", "region_stats"},
            "points": method in {"interpolate", "resample"},
            "interpolation": method in {"interpolate", "resample"},
            "window": method
            in {"moving_average", "savgol", "block_average", "envelope_sliding"},
            "envelope_output": method.startswith("envelope_"),
            "prominence": method == "envelope_peaks",
            "distance": method == "envelope_peaks",
            "replicate_error": method == "replicate",
            "value": method in {"baseline_constant", "subtract"},
            "reference": method in BINARY,
            "align": method in BINARY,
            "fft_window": method.startswith("fft_"),
            "cutoff": method in {"lowpass", "highpass", "bandpass", "bandstop"},
            "cutoff2": method in {"bandpass", "bandstop"},
            "order": method in {"lowpass", "highpass", "bandpass", "bandstop"},
            "region": True,
            "region_baseline": method == "region_integral",
            "polyorder": method == "savgol",
            "edge": method in {"savgol", "moving_average"},
            "detrend": method.startswith("fft_"),
            "endpoints": method == "envelope_peaks",
            "show_marks": method == "envelope_peaks",
        }
        if "sampling" in self.options[title]:
            visible["points"] = (
                method in {"interpolate", "resample"}
                and self.options[title]["sampling"].currentData() == "points"
            )
        if title == "信号分析":
            self.cutoff_picker.setVisible(
                method in {"lowpass", "highpass", "bandpass", "bandstop"}
            )
        for (section, key), widget in self.rows.items():
            if section == title:
                widget.setVisible(visible.get(key, True))
        if method == "subtract" and self.options[title]["value"].value() == 0:
            self.options[title]["value"].setValue(1)
        self.fill_references()
        from tailor.processing_workflow import refresh
        refresh(self)

    def refresh_column_choices(self,*args):
        if not hasattr(self,'options'):return
        self.sync_objects_text();self.fill_references()

    def fill_references(self):
        for options in self.options.values():
            box = options.get("reference")
            if box is None:
                continue
            old = box.currentData()
            with QtCore.QSignalBlocker(box):
                box.clear()
                box.addItem("—", None)
                for sheet in self.sheets().values():
                    for key in __import__("tailor.choice_catalog",fromlist=["visible_columns"]).visible_columns(sheet.model):
                        box.addItem(
                            __import__("tailor.column_titles",fromlist=["display"]).display(sheet.model,key),
                            (sheet.id, key),
                        )
                if old is not None:
                    box.setCurrentIndex(max(0, data_index(box, old)))

    def x_values(self, sheet, key, allow_category=False):
        model = sheet.model
        keys = list(model.columnLabels())
        xkey = next(
            (k for i, k in enumerate(keys) if model.column_metadata(i)["role"] == "X"),
            None,
        )
        # A graph's explicit X is authoritative for its own Y source.
        try:
            info = json.loads(
                model.column_metadata(keys.index(key)).get("source") or "{}"
            )
            paired = info.get("result_x") or info.get("x")
            if paired in keys:
                xkey = paired
        except (ValueError, TypeError):
            pass
        # The inspector's own curve is authoritative, including embedded
        # advanced panels. A different visible graph may use the same Y with
        # its original X after an explicitly isolated axis transformation.
        source=source_on_graph(self.plot,sheet,key) if self.plot is not None else None
        if source is None:
            graph = source_graph(sheet, key)
            source = source_on_graph(graph, sheet, key) if graph else None
        if source:
            xkey = source.model.x_col
        if not xkey:
            return np.arange(1, model.rowCount() + 1, dtype=float), None
        values = pd.Series(model.data_model.get_column(xkey))
        mode = (
            getattr(source.model, "_axis_modes", {}).get("x", "numeric")
            if source
            else "numeric"
        )
        if mode == "category" and allow_category:
            from tailor.axis_extensions import convert_series

            values, _ = convert_series(values, "category")
        elif mode == "category":
            raise ValueError("数值处理需要数值或日期时间X列，分类轴不能计算数值间距。")
        if mode == "datetime" or (
            pd.to_numeric(values, errors="coerce").notna().sum() == 0
            and pd.to_datetime(values, errors="coerce", utc=True, format="mixed").notna().any()
        ):
            from tailor.axis_extensions import convert_series

            values, _ = convert_series(values, "datetime")
        return np.asarray(pd.to_numeric(values, errors="coerce"), dtype=float), xkey

    def show_region(self, active):
        if not hasattr(self, "analysis_region"):
            x = self.plot.ui.plot_widget.getViewBox().viewRange()[0]
            self.analysis_region = pg.LinearRegionItem(
                x, brush=pg.mkBrush(40, 120, 204, 35)
            )
            self.plot.ui.plot_widget.addItem(self.analysis_region, ignoreBounds=True)
            from tailor.processing_workflow import region_to_fields
            self.analysis_region.sigRegionChanged.connect(lambda:region_to_fields(self))
        self.analysis_region.setVisible(active)
        if hasattr(self,'draw_result'):
            from tailor.processing_workflow import region_to_fields
            region_to_fields(self)

    def sync_region(self, *args):
        pass

    def mask(self, sheet, x, title):
        mask = np.ones(len(x), dtype=bool)
        if (
            title == "交互区域分析"
            and self.plot
            and self.options[title].get("region")
            and self.options[title]["region"].isChecked()
        ):
            limits = sorted(self.analysis_region.getRegion())
            from tailor.graph_presentation import physical

            limits = physical(limits, self.plot.presentation.axes["x"])
            return (x >= limits[0]) & (x <= limits[1])
        if not self.current_data.isChecked():
            return mask
        if self.plot:
            from tailor.graph_presentation import physical

            limits = physical(
                sorted(self.plot.ui.plot_widget.getViewBox().viewRange()[0]),
                self.plot.presentation.axes["x"],
            )
            return (x >= limits[0]) & (x <= limits[1])
        mask[:] = False
        for block in sheet.ui.data_view.selectionModel().selection():
            mask[max(0, block.top()) : min(len(x), block.bottom() + 1)] = True
        return mask

    def run(self, title, create):
        title = "平滑与校正" if title == "数据预处理" else title
        options = {}
        for key, widget in self.options[title].items():
            if key in {"summary", "region"}:
                continue
            if key == 'reference_value':
                text = widget.text().strip()
                if text:
                    try:
                        value = float(text)
                        if not np.isfinite(value):raise ValueError
                    except ValueError:
                        self.owner.statusBar().showMessage('参考值必须是有限数值。',6000);return
                    options[key] = value
                continue
            options[key] = (
                [k for k, b in widget.items() if b.isChecked()]
                if isinstance(widget, dict)
                else widget.currentData()
                if isinstance(widget, QtWidgets.QComboBox)
                else widget.value()
            )
        if title=='基础数学' and self.methods[title].currentData() in BINARY and not options.get('reference') and 'reference_value' not in options:
            self.owner.statusBar().showMessage('请选择参考列β，或输入参考值β。',6000)
            return
        if title=='交互区域分析' and options.get('region_low',0)>=options.get('region_high',1):
            self.owner.statusBar().showMessage('分析区间开始须小于结束。',6000)
            return
        if not options.get("statistics", ["mean"]):
            self.message.setText("请选择至少一项统计量。")
            self.owner.statusBar().showMessage(self.message.text(),6000)
            return
        self.launch(self.methods[title].currentData(), options, create, title)

    def start(self, method, window, value, reference, create, title):
        # Compatibility adapter for the existing moving-average trend action.
        if self.plot and not self.targets:
            self.targets = [(self.plot.data_sheet.id, self.plot.model.y_col)]
        self.launch(
            method, {"window": int(window), "value": float(value)}, create, title
        )

    def launch(self, method, options, create, title, record=None, as_new=False):
        if self.owner.data_operation_busy():
            self.message.setText("请等待当前操作结束。")
            self.owner.statusBar().showMessage(self.message.text(),6000)
            return
        self.sync_objects_text()
        self.recompute_record = record
        self.recompute_as_new = as_new
        from tailor.analysis_records import values_hash

        self.destination_guard = (
            [
                (sheet, key, values_hash(sheet.model.data_model.get_column(key)))
                for sheet, key, _slot, _expected in record["outputs"]
            ]
            if record and not as_new
            else []
        )
        self.title = title
        try:
            sheets = self.sheets()
            inputs = []
            reference = options.get("reference")
            ref = None
            if reference:
                rs, rk = reference
                sheet = sheets[rs]
                rx, rxkey = self.x_values(sheet, rk)
                ref = (
                    rx,
                    np.asarray(
                        pd.to_numeric(
                            sheet.model.data_model.get_column(rk), errors="coerce"
                        ),
                        dtype=float,
                    ),
                )
                from tailor.exclusions import rows_for

                ref_excluded = rows_for(sheet.model.data_model, [rxkey, rk])
                if ref_excluded:
                    if not options.get("align", False):
                        raise ValueError(
                            "参考列包含排除点；请恢复数据，或主动选择插值对齐。"
                        )
                    keep = np.ones(len(rx), dtype=bool)
                    keep[[i for i in ref_excluded if i < len(keep)]] = False
                    ref = (ref[0][keep], ref[1][keep])
            for sid, key in self.targets:
                sheet = sheets[sid]
                xx, xkey = self.x_values(
                    sheet, key, allow_category=method in {"statistics", "region_stats"}
                )
                yy = np.array(
                    pd.to_numeric(
                        sheet.model.data_model.get_column(key), errors="coerce"
                    ),
                    dtype=float,
                    copy=True,
                )
                if record:
                    obj = next(
                        c
                        for c in record["recipe"]["objects"]
                        if c["sheet"] == sid and c["key"] == key
                    )
                    previous_xkey = xkey
                    xkey = obj.get("xkey")
                    if xkey and xkey != previous_xkey:
                        xx = np.asarray(
                            pd.to_numeric(
                                sheet.model.data_model.get_column(xkey), errors="coerce"
                            ),
                            dtype=float,
                        )
                    scope = obj["scope"]
                    mask = np.ones(len(xx), dtype=bool)
                    if scope["mode"] == "x":
                        mask = (xx >= scope["range"][0]) & (xx <= scope["range"][1])
                    elif scope["mode"] == "rows":
                        mask[:] = False
                        for first, last in scope["ranges"]:
                            mask[first : last + 1] = True
                else:
                    mask = self.mask(sheet, xx, title)
                    scope = {"mode": "all"}
                    if self.plot and (
                        self.current_data.isChecked()
                        or title == "交互区域分析"
                        and self.options[title].get("region")
                        and self.options[title]["region"].isChecked()
                    ):
                        from tailor.graph_presentation import physical

                        limits = (
                            self.analysis_region.getRegion()
                            if title == "交互区域分析"
                            and self.options[title]["region"].isChecked()
                            else self.plot.ui.plot_widget.getViewBox().viewRange()[0]
                        )
                        scope = {
                            "mode": "x",
                            "range": sorted(
                                float(v)
                                for v in physical(
                                    limits, self.plot.presentation.axes["x"]
                                )
                            ),
                        }
                    elif not self.plot and self.current_data.isChecked():
                        scope = {
                            "mode": "rows",
                            "ranges": [
                                [b.top(), b.bottom()]
                                for b in sheet.ui.data_view.selectionModel().selection()
                            ],
                        }
                from tailor.exclusions import rows_for

                excluded = rows_for(sheet.model.data_model, [xkey, key])
                excluded_mask = np.zeros(len(mask), dtype=bool)
                excluded_mask[[r for r in excluded if r < len(mask)]] = True
                counts = {
                    "selected": int(mask.sum()),
                    "excluded": int((mask & excluded_mask).sum()),
                    "valid": int((mask & ~excluded_mask & np.isfinite(yy)).sum()),
                    "missing": int((mask & ~excluded_mask & ~np.isfinite(yy)).sum()),
                }
                if (
                    method in {"statistics", "region_stats"}
                    and options.get("missing") == "reject"
                    and counts["missing"]
                ):
                    raise ValueError(
                        "所选数据含缺失/非有限数值；请清理数据或选择忽略缺失。"
                    )
                if (
                    excluded
                    and (
                        method in {v for _, v in SIGNALS}
                        or method == "envelope_hilbert"
                    )
                    and any(r < len(mask) and mask[r] for r in excluded)
                ):
                    raise ValueError(
                        "选区包含排除点，FFT/滤波/Hilbert不能自动补齐采样缺口；请恢复数据或改选连续范围。"
                    )
                if method == "replicate":
                    yy[[r for r in excluded if r < len(yy)]] = np.nan
                else:
                    mask[[r for r in excluded if r < len(mask)]] = False
                indices = np.flatnonzero(mask)
                if len(indices):
                    populated = (
                        ~np.isnan(xx[indices])
                        if method == "replicate"
                        else ~np.isnan(yy[indices])
                    )
                    if method not in {"statistics", "region_stats"}:
                        populated &= ~np.isnan(xx[indices])
                    positions = np.flatnonzero(populated)
                    if len(positions):
                        indices = indices[positions[0] : positions[-1] + 1]
                        mask[:] = False
                        mask[indices] = True
                if not len(indices):
                    raise ValueError(sheet.name + " 的当前范围没有选中数据。")
                labels=list(sheet.model.columnLabels())
                units={axis:sheet.model.column_metadata(labels.index(col))['unit'] if col in labels else ''
                       for axis,col in (('x',xkey),('y',key))}
                reference_unit=None
                if reference:
                    rs,rk=reference
                    rm=sheets[rs].model
                    reference_unit=rm.column_metadata(list(rm.columnLabels()).index(rk))['unit']
                    if method in {'add','subtract_columns','subtract'} and units['y'] and reference_unit and units['y']!=reference_unit:
                        raise ValueError(f'对象与参考列单位不同（{units["y"]} / {reference_unit}）；请先统一单位，不进行隐式换算。')
                inputs.append(
                    {
                        "units": units,
                        "reference_unit": reference_unit,
                        "sheet": sid,
                        "key": key,
                        "scope": scope,
                        "counts": counts,
                        "xkey": xkey,
                        "x": xx[mask].copy(),
                        "y": yy[mask].copy(),
                        "indices": indices,
                        "rows": len(yy),
                        "reference": (ref[0][mask].copy(), ref[1][mask].copy())
                        if ref is not None
                        and np.array_equal(ref[0], xx, equal_nan=True)
                        else ref,
                    }
                )
            if not inputs:
                raise ValueError("请选择至少一列。")
            self.recipe_objects = [
                {k: c[k] for k in ("sheet", "key", "xkey", "scope")} for c in inputs
            ]
            if method == "replicate":
                if len(inputs) < 2 or len({c["sheet"] for c in inputs}) != 1:
                    raise ValueError("初版重复测量只支持同表至少两列Y。")
                base = inputs[0]
                if any(
                    not np.array_equal(c["indices"], base["indices"])
                    or not np.array_equal(c["x"], base["x"], equal_nan=True)
                    for c in inputs
                ):
                    raise ValueError("重复测量要求各列X和处理范围完全相同。")
                base["matrix"] = np.stack([c["y"] for c in inputs])
                inputs = [base]
            self.inputs = inputs
            self.create_result = create
            self.title = title
            self.revision = self.owner._project_revision
            from tailor.analysis_records import input_signature

            self.guard_recipe = {"objects": self.recipe_objects, "options": options}
            self.guard_signature = input_signature(self.owner, self.guard_recipe)
            self.job = ProcessingJob(inputs, method, options, self.owner)
            self.owner._processing_busy = True
            self.job.finished.connect(self.finished)
            self.cancel.show()
            self.message.setText("正在计算所选列的数据快照…")
            self.job.start()
        except (ValueError, TypeError, KeyError) as error:
            self.message.setText(str(error))
            self.owner.statusBar().showMessage(self.message.text(),6000)

    def cancel_job(self):
        if self.job:
            self.job.requestInterruption()

    def clear_preview(self):
        getattr(self, "_preview_by_category", {}).pop(self.category, None)
        if hasattr(self, "preview_card"):
            self.preview_table.setRowCount(0)
            self.preview_card.hide()
            self.message.setText("")
            self.message.hide()
        self.pending_cutoffs = None
        current=getattr(self.plot,'_visible_graph_document',self.plot) if self.plot else None
        clear_graph_previews(self.owner,{current} if current is not None else set())
        self.preview_items = []
        self.preview.setData([], [])
        from tailor.processing_preview import render
        render(self)

    def pick_cutoffs(self):
        if self.job is not None:
            return
        options = self.options["信号分析"]
        self.pending_cutoffs = self.methods["信号分析"].currentData()
        self.launch(
            "fft_amplitude",
            {
                "fft_window": options["fft_window"].currentData(),
                "detrend": options["detrend"].currentData(),
            },
            False,
            "信号分析",
        )
        if self.job is None:
            self.pending_cutoffs = None

    def show_data_preview(self, results):
        self.preview_table.setRowCount(0)
        sheets = self.sheets()
        for context, result in zip(self.inputs, results):
            sheet = sheets[context["sheet"]]
            name = sheet.model.data_model.get_column_name(context["key"])
            rows = []
            counts = result.get("counts", context.get("counts", {}))
            rows += [
                (label, str(counts[key]))
                for key, label in [
                    ("valid", "有效"),
                    ("missing", "缺失"),
                    ("excluded", "排除"),
                ]
                if key in counts
            ]
            rows += [
                (STATISTICS.get(label,label), f"{value:.10g}")
                for label, value in result.get("metrics", {}).items()
            ]
            if not result.get("metrics") and result.get("y") is not None:
                xx, yy = result["x"], result["y"]
                indices = sorted(
                    set(
                        list(range(min(12, len(xx))))
                        + list(range(max(12, len(xx) - 3), len(xx)))
                    )
                )
                rows += [(f"{xx[i]:.8g}", f"{yy[i]:.10g}") for i in indices]
            for label, value in rows:
                row_index = self.preview_table.rowCount()
                self.preview_table.insertRow(row_index)
                for col, text in enumerate((name, label, value)):
                    self.preview_table.setItem(
                        row_index, col, QtWidgets.QTableWidgetItem(text)
                    )
        self.preview_card.setVisible(self.preview_table.rowCount() > 0)
        self.message.setVisible(not self.preview_card.isVisible())

    def finished(self):
        from tailor.analysis_records import monitor, recipe_for, result_columns

        job = self.job
        cutoff_method = getattr(self, "pending_cutoffs", None)
        self.owner._processing_busy = False
        self.cancel.hide()
        outcome = {"success": False, "payload": []}
        try:
            if job.error:
                raise ValueError(job.error)
            if job.isInterruptionRequested():
                raise ValueError("已取消，原数据保留。")
            from tailor.analysis_records import input_signature, values_hash

            if any(
                key not in sheet.model.columnLabels()
                or values_hash(sheet.model.data_model.get_column(key)) != expected
                for sheet, key, expected in self.destination_guard
            ):
                raise ValueError("计算期间结果列发生变化，未覆盖您的编辑。请重新计算。")
            if input_signature(self.owner, self.guard_recipe) != self.guard_signature:
                raise ValueError("源数据或排除状态已变化，请重新处理。")
            sheets, summaries, bundles = self.sheets(), [], defaultdict(list)
            recipe = recipe_for(self, job.method, job.options, self.recipe_objects)
            method_title = {
                value: label
                for label, value in [
                    *MATHEMATICS,
                    *PREPROCESS,
                    *REGIONS,
                    *SIGNALS,
                    *ENVELOPES,
                    ("描述统计", "statistics"),
                    ("重复测量", "replicate"),
                ]
            }.get(job.method, self.title)
            if not self.create_result:
                self.clear_preview()
            for context, result in zip(self.inputs, job.result, strict=True):
                sheet = sheets[context["sheet"]]
                key = context["key"]
                name = sheet.model.data_model.get_column_name(key)
                if job.method.startswith('fft_') and hasattr(self,'spectrum'):
                    from tailor.processing_workflow import draw_spectrum
                    draw_spectrum(self,result)
                if result.get("counts") and job.method in {
                    "statistics",
                    "region_stats",
                }:
                    counts = result["counts"]
                    summaries.append(
                        f"{name}：有效{counts['valid']}，缺失{counts['missing']}，排除{counts['excluded']}；标准差采用"
                        + ("样本n−1" if job.options.get("ddof", 1) else "总体n")
                    )
                if result["metrics"]:
                    summaries.append(
                        name
                        + "："
                        + "；".join(
                            f"{k}={v:.8g}" for k, v in result["metrics"].items()
                        )
                    )
                if self.create_result:
                    bundles[sheet.id].extend(
                        result_columns(context, result, name, method_title, recipe)
                    )
                    continue
                series = result.get("series") or (
                    {"预览": result["y"]} if result["y"] is not None else {}
                )
                graph = source_graph(sheet, key, self.plot)
                if job.method.startswith('fft_'):
                    continue
                if series and graph is None:
                    raise ValueError(name + "尚未绘图，请先绘制原始曲线。")
                if graph is not None:
                    source=source_on_graph(graph,sheet,key)
                    placement=graph.model.get_plot_info(source) if graph.presentation.multi else None
                    source_box=graph.presentation.box_for(placement) if placement else graph.ui.plot_widget.getViewBox()
                    for mark in result.get("markers", {}).values():
                        item = pg.PlotDataItem(
                            mark["x"],
                            mark["y"],
                            pen=None,
                            symbol="o",
                            symbolSize=8,
                            symbolBrush="#d05b23",
                        )
                        item._curve_processing_preview = True
                        source_box.addItem(item)
                        item._curve_preview_box = source_box
                        self.preview_items.append((graph, item))
                        if not hasattr(self.owner, "_column_previews"):
                            self.owner._column_previews = []
                        self.owner._column_previews.append((graph, item))
                from tailor.series_colors import colour_for
                for label, values in series.items():
                    color = colour_for(graph, f'processing-preview:{sheet.id}:{key}:{job.method}:{label}')
                    if label in {"SD", "SEM", "有效次数N"}:
                        continue
                    item = pg.PlotDataItem(
                        result["x"], values, pen=pg.mkPen(color, width=derived_width(self.plot)), name=label
                    )
                    item._curve_processing_preview = True
                    source = source_on_graph(graph, sheet, key)
                    info = (
                        graph.model.get_plot_info(source)
                        if graph.presentation.multi
                        else None
                    )
                    xaxis = "top" if info and info.x_axis == "top" else "x"
                    yaxis = "right" if info and info.axis == "right" else "y"
                    item.setLogMode(
                        graph.presentation.axes[xaxis]["log"],
                        graph.presentation.axes[yaxis]["log"],
                    )
                    box = (
                        frequency_box(graph)
                        if job.method.startswith("fft_")
                        else graph.presentation.box_for(info)
                        if info
                        else graph.ui.plot_widget.getViewBox()
                    )
                    if job.method.startswith("fft_"):
                        item.setLogMode(False, False)
                    item._curve_preview_box = box
                    box.addItem(item)
                    from tailor.axis_extensions import wrap_display_items

                    wrap_display_items(graph.presentation)
                    self.preview_items.append((graph, item))
                    if not hasattr(self.owner, "_column_previews"):
                        self.owner._column_previews = []
                    self.owner._column_previews.append((graph, item))
                    from tailor.native_panels import show_document

                    show_document(self.owner, graph)
            if self.create_result:
                histories={sid:list(sheets[sid].model._history[:sheets[sid].model._cursor]) for sid in bundles}
                payload = []
                for sid, columns in bundles.items():
                    sheet = sheets[sid]
                    if self.recompute_record and not self.recompute_as_new:
                        slots = {
                            slot: key
                            for oldsheet, key, slot, _ in self.recompute_record[
                                "outputs"
                            ]
                            if oldsheet is sheet
                        }
                        keys = [
                            slots[json.loads(spec["source"])["slot"]]
                            for spec in columns
                        ]
                        sheet.model.replace_results(
                            columns, keys, "重新计算 · " + self.title
                        )
                    else:
                        keys = sheet.model.append_results(columns, self.title)
                    payload.append({"sheet": sheet, "keys": keys})
                from tailor.curve_documents import add_processing_results
                # Committing replaces this graph's transient preview. Keeping
                # it produces a second, nonselectable copy beside the saved
                # result; generated series inherit their source's axis below.
                if self.plot:
                    self.clear_preview()
                if self.plot and (not hasattr(self,'draw_result') or self.draw_result.isChecked()) and not job.method.startswith('fft_'):
                    add_processing_results(self.owner, payload, graph=self.plot)
                from tailor.element_actions import combine
                for sid,start in histories.items():combine(sheets[sid].model,start,'执行处理 · '+self.title)
                self.resultReady.emit(payload)
                outcome.update(success=True, payload=payload, recipe=recipe)
                self.message.setText(
                    "结果已更新原列。"
                    if self.recompute_record and not self.recompute_as_new
                    else "结果已追加回原工作表，名称已标注处理类型。"
                )
                from tailor.result_pages import refresh_processing
                refresh_processing(self.owner)
                monitor(self.owner).timer.start()
            else:
                outcome["success"] = True
                if cutoff_method:
                    for graph, item in self.preview_items[:1]:
                        box = item._curve_preview_box
                        nyquist = float(item.xData[-1])
                        for key in (
                            ["cutoff", "cutoff2"]
                            if cutoff_method in {"bandpass", "bandstop"}
                            else ["cutoff"]
                        ):
                            widget = self.options["信号分析"][key]
                            line = pg.InfiniteLine(
                                pos=min(
                                    max(widget.value(), nyquist * 0.01), nyquist * 0.99
                                ),
                                movable=True,
                                bounds=(nyquist * 1e-6, nyquist * 0.999999),
                                pen=pg.mkPen("#45935f", width=2),
                            )
                            line.sigPositionChanged.connect(
                                lambda line, widget=widget: widget.setValue(
                                    line.value()
                                )
                            )
                            box.addItem(line)
                            line._curve_preview_box = box
                            self.preview_items.append((graph, line))
                            self.owner._column_previews.append((graph, line))
                    self.pending_cutoffs = None
                self.message.setText("预览已显示；默认视图可显示全部预览曲线。")
            if self.title in self.options:
                summary = self.options[self.title]["summary"]
                summary.setText("\n".join(summaries))
                summary.hide()
            self.show_data_preview(job.result)
            from tailor.processing_preview import remember
            remember(self)
        except (ValueError, KeyError, TypeError) as error:
            outcome["error"] = str(error)
            self.message.setText("未生成结果：" + str(error))
            self.owner.statusBar().showMessage(self.message.text())
        finally:
            job.deleteLater()
            self.job = None
            self.operationFinished.emit(outcome)

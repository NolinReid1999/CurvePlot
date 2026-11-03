"""Named style/analysis recipes, executing existing import/analysis/fitting APIs."""

from tailor.compact_controls import CheckButton

import copy
import json
import re
import uuid
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from PySide6 import QtCore, QtWidgets

from tailor.graph_controls import combo, row


def store(kind):
    settings = QtCore.QSettings("PhysicsPlot", "Templates")
    try:
        value = json.loads(settings.value(kind, "{}"))
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def save_named(kind, name, value):
    values = store(kind)
    values[name] = value
    QtCore.QSettings("PhysicsPlot", "Templates").setValue(
        kind, json.dumps(values, ensure_ascii=False)
    )


def descriptor(sheet, key):
    keys = list(sheet.model.columnLabels())
    return {
        "name": sheet.model.data_model.get_column_name(key),
        "index": keys.index(key),
    }


def resolve(sheet, spec, mode="name", keys=None):
    keys = list(sheet.model.columnLabels()) if keys is None else list(keys)
    if mode == "name":
        matches = [
            k for k in keys if sheet.model.data_model.get_column_name(k) == spec["name"] or sheet.model._metadata.get(k,{}).get("import_name")==spec["name"]
        ]
        if len(matches) != 1:
            raise ValueError("列名缺失或重复：" + str(spec["name"]))
        return matches[0]
    return keys[int(spec["index"])]


def graph_template(plot, include_ranges=False):
    native = getattr(getattr(plot, "advanced_view", None), "native", None)
    if native:
        native.snapshot()
    state = plot.presentation.to_dict()
    state["trend_sources"] = []
    advanced = state.get("extra_settings", {}).get("advanced")
    if advanced:
        from tailor.advanced_plotting import column_info

        for name in ("refs", "xyz"):
            if name in advanced:
                advanced[name] = [
                    descriptor(column_info(plot.main_window, ref)[0], ref[1])
                    for ref in advanced[name]
                ]
        for node in advanced.get("nodes", []):
            node["refs"] = [
                descriptor(column_info(plot.main_window, ref)[0], ref[1])
                for ref in node["refs"]
            ]
            node["template_sources"] = [
                {
                    k: source[k]
                    for k in ("curve_style", "graph_settings", "x_label", "y_label")
                }
                for source in node.get("sources", [])
            ]
            node["sources"] = []
            overlay = node.pop("overlay", None)
            if overlay:
                node["template_overlay"] = {
                    k: overlay[k]
                    for k in ("curve_style", "graph_settings", "x_label", "y_label")
                }
            if not include_ranges:
                for fmt in [
                    *node["template_sources"],
                    *([node["template_overlay"]] if "template_overlay" in node else []),
                ]:
                    for k in ("right_min", "right_max", "top_min", "top_max"):
                        fmt["graph_settings"][k] = None
        if advanced.get("global_legend"):
            advanced["global_legend"].pop("entries", None)
            advanced["global_legend"].pop("samples", None)
    if not include_ranges:
        for k in ("right_min", "right_max", "top_min", "top_max"):
            state[k] = None
    return {
        "style": plot.curve_style.to_dict(),
        "presentation": state,
        "include_ranges": include_ranges,
        "ranges": [getattr(plot.model, k) for k in ("x_min", "x_max", "y_min", "y_max")]
        if include_ranges
        else [None] * 4,
    }


def apply_graph_template(plot, template):
    from tailor.curve_controls import apply_style
    from tailor.curve_style import CurveStyle

    state = copy.deepcopy(template["presentation"])
    advanced = state.get("extra_settings", {}).get("advanced")
    if advanced:
        for name in ("refs", "xyz"):
            if name in advanced:
                advanced[name] = [
                    (plot.data_sheet.id, resolve(plot.data_sheet, d))
                    for d in advanced[name]
                ]
        for node in advanced.get("nodes", []):
            node["refs"] = [
                (plot.data_sheet.id, resolve(plot.data_sheet, d)) for d in node["refs"]
            ]
    old_view = getattr(plot, "advanced_view", None)
    if old_view and not advanced:
        # Applying an ordinary template retains the active advanced data layout.
        state.setdefault("extra_settings", {})["advanced"] = copy.deepcopy(old_view.cfg)
    plot.presentation.load(state)
    apply_style(plot, CurveStyle(**template["style"]), dirty=False)
    if template.get("include_ranges"):
        for name, value in zip(
            ("x_min", "x_max", "y_min", "y_max"), template["ranges"]
        ):
            setattr(plot.model, name, value)
    plot.refresh_ui()
    if getattr(plot, "advanced_view", None):
        plot.advanced_view.schedule(True)
    plot.main_window.mark_project_dirty()


class GraphTemplateControls(QtWidgets.QWidget):
    def __init__(self, document):
        super().__init__()
        self.document = document
        layout = QtWidgets.QVBoxLayout(self)
        self.names = QtWidgets.QComboBox()
        self.names.addItem("—", "")
        self.name = QtWidgets.QLineEdit()
        self.name.setPlaceholderText("模板名称")
        self.ranges = CheckButton("模板包含固定坐标范围")
        self.save = QtWidgets.QPushButton("保存当前整图")
        self.apply = QtWidgets.QPushButton("应用模板")
        layout.addWidget(self.names)
        layout.addWidget(self.name)
        layout.addWidget(self.ranges)
        layout.addWidget(row(self.save, self.apply))
        self.note = QtWidgets.QLabel("模板保存样式、坐标轴和布局，不保存原始数据。")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.save.clicked.connect(self.save_current)
        self.apply.clicked.connect(self.apply_current)
        self.names.currentIndexChanged.connect(self.remember)
        self.refresh()
        if not hasattr(document, "presentation") or not hasattr(document, "data_sheet"):
            self.save.setEnabled(False)
            self.apply.setText("用于下次绘图")
        from tailor.fold_panel import normalize_control_heights
        normalize_control_heights(self)

    def refresh(self):
        old = self.names.currentData()
        with QtCore.QSignalBlocker(self.names):
            self.names.clear()
            self.names.addItem("—", "")
            for name in store("graphs"):
                self.names.addItem(name, name)
            self.names.setCurrentIndex(max(0, self.names.findData(old)))
        self.apply.setEnabled(bool(self.names.currentData()))

    def showEvent(self, event):
        self.refresh()
        super().showEvent(event)

    def remember(self, *args):
        self.document._graph_template_name = self.names.currentData()
        self.apply.setEnabled(bool(self.names.currentData()))

    def save_current(self):
        if not hasattr(self.document, "presentation") or not hasattr(
            self.document, "data_sheet"
        ):
            return
        name = self.name.text().strip()
        if not name:
            self.note.setText("请输入模板名称。")
            return
        save_named(
            "graphs", name, graph_template(self.document, self.ranges.isChecked())
        )
        self.refresh()
        self.names.setCurrentIndex(self.names.findData(name))
        self.note.setText("整图模板已保存。")

    def apply_current(self):
        self.remember()
        if not hasattr(self.document, "presentation"):
            self.note.setText("已选模板，将应用于下一张绘图。")
            return
        template = store("graphs").get(self.names.currentData())
        if template:
            try:
                apply_graph_template(self.document, template)
                self.note.setText("模板已应用。")
            except (ValueError, KeyError, StopIteration) as error:
                self.note.setText("模板列映射不匹配：" + str(error))


def source_plot(owner, sheet, key):
    return next(
        (
            p
            for p in owner.get_plots()
            if getattr(p, "data_sheet", None) is sheet
            and p.model.y_col == key
            and getattr(p, "advanced_view", None) is None
        ),
        None,
    )


def attach_import(owner,path,data):
    from tailor.single_sheet import append_import
    sheet=owner.get_data_sheets()[0]
    append_import(sheet,data,str(path));owner.refresh_project_tree();return sheet


class BatchRunner(QtCore.QObject):
    changed = QtCore.Signal(str)
    finished = QtCore.Signal()

    def __init__(self, control, flow, tasks, folder=None):
        super().__init__(control.owner)
        self.control, self.owner, self.flow = (
            control,
            control.owner,
            copy.deepcopy(flow),
        )
        self.tasks = list(tasks)
        self.folder = Path(folder) if folder else None
        self.index = 0
        self.step_index = 0
        self.results = []
        self.paused = False
        self.cancelled = False
        self.waiting = False
        self.last_plot = None
        self.reader = None
        self.current_targets = []
        self.owner._batch_runner = self

    def start(self):
        if self.folder:
            self.folder.mkdir(parents=True, exist_ok=False)
        self.next_task()

    def next_task(self):
        if self.cancelled or self.index >= len(self.tasks):
            self.complete()
            return
        self.task = self.tasks[self.index]
        self.step_index = 0
        self.last_plot = None
        if "file" in self.task:
            self.read_file()
            return
        self.original_targets = list(self.task["targets"])
        self.binding_keys=self.task.get("imported_keys")
        self.current_targets = self.original_targets.copy()
        self.summary = {"来源": self.task.get("name", ""), "状态": "完成"}
        self.advance()

    def read_file(self):
        from tailor.csv_format_dialog import FormatParameters
        from tailor.physicsplot_desktop import CsvReader

        path = Path(self.task["file"])
        options = self.flow.get("import", {})
        params = (
            {
                "excel_sheet": options.get("excel_sheet") or 0,
                "header": options.get("header", True),
            }
            if path.suffix.lower() in {".xlsx", ".xls", ".xlsm"}
            else FormatParameters(
                delimiter=options.get("delimiter"),
                header=0 if options.get("header", True) else None,
                encoding=options.get("encoding", "utf-8-sig"),
            )
        )
        self.owner._processing_busy = True
        self.waiting = True
        self.reader = CsvReader(path, params, self.owner)
        self.reader.loaded.connect(lambda data: self.file_loaded(path, data))
        self.reader.failed.connect(self.file_failed)
        self.reader.finished.connect(self.reader_finished)
        self.reader.start()
        self.changed.emit("正在导入：" + path.name)

    def file_loaded(self, path, data):
        self.owner._processing_busy = False
        if self.cancelled:
            return
        sheet = attach_import(self.owner, path, data)
        try:
            mapping = self.flow["columns"]
            mode = mapping.get("mode", "name")
            xkey = resolve(sheet, mapping["x"], mode, sheet._last_imported_keys)
            for i, key in enumerate(sheet.model.columnLabels()):
                if key in sheet._last_imported_keys and sheet.model.column_metadata(i)["role"] == "X":
                    sheet.model._metadata[key]["role"] = "Y"
            sheet.model._metadata.setdefault(xkey, {})["role"] = "X"
            refs = [(sheet.id, resolve(sheet, entry, mode,sheet._last_imported_keys)) for entry in mapping["ys"]]
            groups = (
                [refs]
                if any(step.get("method") == "replicate" for step in self.flow["steps"])
                else [[ref] for ref in refs]
            )
            replacements = [
                {
                    "targets": group,
                    "imported_keys":list(sheet._last_imported_keys),
                    "name": str(path)
                    + " · "
                    + sheet.model.data_model.get_column_name(group[0][1]),
                }
                for group in groups
            ]
            self.tasks[self.index : self.index + 1] = replacements
            self._file_ok = True
        except (KeyError, StopIteration, IndexError, ValueError) as error:
            self.file_failed("列映射不匹配：" + str(error))

    def file_failed(self, message):
        self.paused = True
        self.changed.emit("已暂停：" + message + "；可重试或跳过当前组。")

    def reader_finished(self):
        self.owner._processing_busy = False
        self.waiting = False
        self.reader = None
        if self.cancelled:
            self.complete()
        elif getattr(self, "_file_ok", False):
            self._file_ok = False
            self.next_task()

    def advance(self):
        if self.cancelled:
            self.complete()
            return
        if self.paused:
            return
        if self.step_index >= len(self.flow["steps"]):
            self.finish_task()
            return
        step = self.flow["steps"][self.step_index]
        self.changed.emit(
            f"第{self.index + 1}/{len(self.tasks)}组 · 步骤{self.step_index + 1}："
            + step["title"]
        )
        targets = (
            self.original_targets
            if step.get("input") == "original"
            else self.current_targets
        )
        if not targets:
            self.fail("上一步没有可继续处理的Y列。")
            return
        sheets = {s.id: s for s in self.owner.get_data_sheets()}
        try:
            sheet = sheets[targets[0][0]]
            if step["kind"] == "process":
                control = sheet.processing_controls
                control.targets = list(targets)
                options = copy.deepcopy(step["options"])
                if step.get("reference"):
                    options["reference"] = (
                        sheet.id,
                        resolve(
                            sheet,
                            step["reference"],
                            self.flow["columns"].get("mode", "name"),
                            getattr(self, "binding_keys", None),
                        ),
                    )
                objects = []
                for sid, key in targets:
                    source = sheets[sid]
                    _, xkey = source.processing_controls.x_values(
                        source,
                        key,
                        allow_category=step["method"] in {"statistics", "region_stats"},
                    )
                    objects.append(
                        {
                            "sheet": sid,
                            "key": key,
                            "xkey": xkey,
                            "scope": copy.deepcopy(step.get("scope", {"mode": "all"})),
                        }
                    )
                recipe = {
                    "id": uuid.uuid4().hex,
                    "auto": False,
                    "title": step["title"],
                    "method": step["method"],
                    "options": options,
                    "objects": objects,
                }
                self.active_control = control
                control.operationFinished.connect(self.process_finished)
                control.launch(
                    step["method"],
                    options,
                    True,
                    step["title"],
                    record={"recipe": recipe, "outputs": []},
                    as_new=True,
                )
                if control.job is None:
                    control.operationFinished.disconnect(self.process_finished)
                    self.fail(control.message.text())
                    return
                self.waiting = True
            elif step["kind"] == "fit":
                from tailor.cst_names import rename_variables

                key = targets[0][1]
                plot = source_plot(self.owner, sheet, key)
                if plot is None:
                    _, xkey = sheet.processing_controls.x_values(sheet, key)
                    if not xkey:
                        raise ValueError("拟合需要指定X列。")
                    plot = self.owner.create_plot_tab(sheet, xkey, key)
                self.last_plot = plot
                cfg = step["fit"]
                preset = cfg.get("preset")
                if preset:
                    plot.preset_controls.choose(preset)
                else:
                    plot.model.update_model_expression(
                        rename_variables(cfg["expression"], {"x": plot.model.x_col}),
                        use_column_ids=True,
                    )
                    plot.update_model_widget()
                    plot.update_params_ui()
                for name, values in cfg.get("parameters", {}).items():
                    if name in plot.model._parameters:
                        p = plot.model._parameters[name]
                        p.value, p.min, p.max, p.vary = (
                            values["value"],
                            values["min"],
                            values["max"],
                            values["vary"],
                        )
                if cfg.get("guess", True) and preset:
                    plot.preset_controls.estimate_initial(False)
                plot.model.set_fit_domain_enabled(cfg.get("use_domain", False))
                if cfg.get("domain"):
                    plot.model.set_fit_domain(*cfg["domain"])
                plot.perform_fit()
                job = plot._fit_job
                if job is None:
                    raise ValueError("未能执行拟合，请检查模型和数据。")
                self.waiting = True
                job.finished.connect(lambda: self.fit_finished(plot, job))
        except (ValueError, KeyError, StopIteration, IndexError, TypeError) as error:
            self.fail(str(error))

    def process_finished(self, outcome):
        self.active_control.operationFinished.disconnect(self.process_finished)
        self.waiting = False
        if self.cancelled:
            self.complete()
            return
        if not outcome["success"]:
            self.fail(outcome.get("error", "处理失败"))
            return
        refs = []
        for result in outcome["payload"]:
            sheet = result["sheet"]
            for key in result["keys"]:
                meta = sheet.model.column_metadata(
                    list(sheet.model.columnLabels()).index(key)
                )
                if meta["role"] == "Y":
                    refs.append((sheet.id, key))
                values = sheet.model.data_model.get_column(key)
                finite = np.asarray(pd.to_numeric(values, errors="coerce"), dtype=float)
                if np.isfinite(finite).sum() == 1:
                    self.summary[f"步骤{self.step_index + 1}·{meta['name']}"] = float(
                        finite[np.isfinite(finite)][0]
                    )
        step = self.flow["steps"][self.step_index]
        self.current_targets = (
            refs
            if step.get("output") == "all"
            else refs[:1]
            if len(self.original_targets) == 1
            else refs
        )
        self.last_plot = None
        self.step_index += 1
        QtCore.QTimer.singleShot(0, self, self.advance)

    def fit_finished(self, plot, job):
        self.waiting = False
        if self.cancelled:
            self.complete()
            return
        if job.outcome != "success" or plot.model.best_fit is not job.result:
            self.fail("拟合失败或已取消，已完成结果保留。")
            return
        fit = plot.model.best_fit
        for name, p in fit.params.items():
            if p.expr is None:
                self.summary[f"拟合{self.step_index + 1}·{name}"] = float(p.value)
                self.summary[f"拟合{self.step_index + 1}·{name}标准误"] = (
                    float(p.stderr) if p.stderr is not None else np.nan
                )
        self.summary[f"拟合{self.step_index + 1}·约化卡方"] = float(fit.redchi)
        record = next(
            (r for r in plot.fit_records if r["id"] == plot.active_fit_id), None
        )
        if record and record.get("column_id"):
            self.current_targets = [(plot.data_sheet.id, record["column_id"])]
        self.step_index += 1
        QtCore.QTimer.singleShot(0, self, self.advance)

    def finish_task(self):
        try:
            formats = self.flow.get("export", [])
            if formats:
                if self.last_plot is None:
                    sid, key = self.current_targets[0]
                    sheet = next(s for s in self.owner.get_data_sheets() if s.id == sid)
                    _, xkey = sheet.processing_controls.x_values(sheet, key)
                    if not xkey:
                        raise ValueError("导出绘图需要X列。")
                    self.last_plot = source_plot(
                        self.owner, sheet, key
                    ) or self.owner.create_plot_tab(sheet, xkey, key)
                template = store("graphs").get(self.flow.get("graph_template"))
                if template:
                    apply_graph_template(self.last_plot, template)
                stem = re.sub(r"[^\w.-]+", "_", self.summary["来源"])[-100:] or str(
                    self.index + 1
                )
                for fmt in formats:
                    self.last_plot.export_graph(
                        self.folder / f"{self.index + 1:03d}_{stem}.{fmt}", 300
                    )
            self.results.append(self.summary)
            self.index += 1
            self.next_task()
        except (ValueError, KeyError, OSError, IndexError, StopIteration) as error:
            self.fail(str(error))

    def fail(self, message):
        self.owner._processing_busy = False
        self.waiting = False
        self.paused = True
        self.changed.emit(
            "已暂停：" + message + "；已完成结果保留。可重试或跳过当前组。"
        )

    def resume(self):
        if not self.paused or self.waiting:
            return
        self.paused = False
        if "file" in self.task:
            self.next_task()
        else:
            self.advance()

    def skip(self):
        if not self.paused or self.waiting:
            return
        self.results.append(
            {
                "来源": self.task.get("name", self.task.get("file", "")),
                "状态": "跳过（失败）",
            }
        )
        self.paused = False
        self.index += 1
        self.next_task()

    def cancel(self):
        self.cancelled = True
        if (
            self.waiting
            and getattr(self, "active_control", None)
            and self.active_control.job
        ):
            self.active_control.cancel_job()
        elif self.waiting and self.last_plot and self.last_plot._fit_job:
            self.last_plot._fit_job.requestInterruption()
        elif not self.waiting:
            self.complete()

    def complete(self):
        if getattr(self, "_completed", False):
            return
        self._completed = True
        if self.results:
            frame = pd.DataFrame(self.results)
            from tailor.single_sheet import append_import, from_dataframe
            data=from_dataframe(frame.fillna(''))
            sheet=self.owner.get_data_sheets()[0];keys=append_import(sheet,data,'批处理参数汇总')
            for key in keys:sheet.model._metadata[key]['comment']='批处理参数汇总'
            if self.folder:
                frame.to_csv(
                    self.folder / "参数汇总.csv", index=False, encoding="utf-8-sig"
                )
        self.owner._batch_runner = None
        self.changed.emit(
            "已停止。" if self.cancelled else f"批处理完成：{len(self.results)}组。"
        )
        self.finished.emit()


class WorkflowControls(QtWidgets.QWidget):
    def __init__(self, control):
        super().__init__()
        self.control = control
        self.owner = control.owner
        self.steps = []
        self.files = []
        self.selected_sheets = set()
        layout = QtWidgets.QVBoxLayout(self)
        self.saved = QtWidgets.QComboBox()
        self.name = QtWidgets.QLineEdit()
        self.name.setPlaceholderText("分析流程名称")
        self.saved.currentIndexChanged.connect(self.load_flow)
        layout.addWidget(row("已存流程", self.saved))
        layout.addWidget(row("流程名称", self.name))
        save = QtWidgets.QPushButton("保存流程")
        save.clicked.connect(self.save_flow)
        layout.addWidget(save)
        self.step_list = QtWidgets.QListWidget()
        self.step_list.setMaximumHeight(155)
        layout.addWidget(self.step_list)
        self.category = combo([(title, title) for title in control.methods])
        self.input = combo([("上一步结果", "previous"), ("原始对象", "original")])
        self.input.setCurrentIndex(1)
        self.output = combo([("首个Y结果", "first"), ("全部Y结果", "all")])
        add = QtWidgets.QPushButton("加入处理步骤")
        self.add_process_button = add
        self.editing = None
        add.clicked.connect(self.add_process)
        configure = QtWidgets.QPushButton("配置参数")
        configure.clicked.connect(
            lambda: control.select_category(self.category.currentData())
        )
        layout.addWidget(row("处理类别", self.category))
        layout.addWidget(row("输入对象", self.input))
        layout.addWidget(row("后续使用", self.output))
        layout.addWidget(row(configure, add))
        from tailor.fit_presets import list_presets

        self.fit_preset = combo(
            [('—',None), ('当前图模型', '__current_model__')]+[(p.title, p.key) for p in list_presets()]
            + [
                ("多峰Gaussian（3峰）", "multi_gaussian_3"),
                ("多峰Lorentzian（3峰）", "multi_lorentzian_3"),
            ]
        )
        self.guess = CheckButton("每组重新估计拟合初值")
        self.guess.setChecked(True)
        fit = QtWidgets.QPushButton("加入拟合步骤")
        fit.clicked.connect(self.add_fit)
        layout.addWidget(row("拟合模型", self.fit_preset))
        layout.addWidget(self.guess)
        layout.addWidget(fit)
        up, down, remove = (
            QtWidgets.QPushButton("上移"),
            QtWidgets.QPushButton("下移"),
            QtWidgets.QPushButton("删除步骤"),
        )
        up.clicked.connect(lambda: self.move(-1))
        down.clicked.connect(lambda: self.move(1))
        remove.clicked.connect(self.remove)
        layout.addWidget(row(up, down, remove))
        edit = QtWidgets.QPushButton("编辑所选步骤")
        edit.clicked.connect(self.edit_step)
        layout.addWidget(edit)
        preflight = QtWidgets.QPushButton("检查列映射与流程")
        preflight.clicked.connect(self.preflight)
        layout.addWidget(preflight)
        self.source = combo(
            [
                ("对象中所选列", "columns"),
                ("项目工作表", "sheets"),
                ("多个文件", "files"),
            ]
        )
        layout.addWidget(row("批处理来源", self.source))
        self.sheet_button = QtWidgets.QToolButton()
        self.sheet_button.setProperty('choiceField', True)
        self.sheet_button.setText("选择工作表")
        self.sheet_button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        from tailor.processing_controls import ColumnMenu
        self.sheet_menu = ColumnMenu(self.sheet_button)
        self.sheet_menu.keep_open = False
        self.sheet_menu.aboutToShow.connect(self.fill_sheets)
        self.sheet_button.setMenu(self.sheet_menu)
        choose = QtWidgets.QPushButton("选择文件")
        choose.clicked.connect(self.choose_files)
        layout.addWidget(row(self.sheet_button, choose))
        self.mapping = combo([("按列名匹配", "name"), ("按列序号匹配", "index")])
        layout.addWidget(row("列映射", self.mapping))
        self.encoding = combo([("UTF-8", "utf-8-sig"), ("GB18030", "gb18030")])
        self.delimiter = combo(
            [("自动识别", None), ("逗号", ","), ("制表符", "\t"), ("分号", ";")]
        )
        self.header = CheckButton("首行是列名")
        self.header.setChecked(True)
        self.excel_sheet = QtWidgets.QLineEdit()
        self.excel_sheet.setPlaceholderText("留空使用第一个工作表")
        layout.addWidget(row("文件编码", self.encoding))
        layout.addWidget(row("分隔符", self.delimiter))
        layout.addWidget(self.header)
        layout.addWidget(row("Excel工作表", self.excel_sheet))
        self.graph = QtWidgets.QComboBox()
        self.graph.addItem("不使用整图模板", "")
        for name in store("graphs"):
            self.graph.addItem(name, name)
        layout.addWidget(row("图形模板", self.graph))
        self.formats = {}
        line = QtWidgets.QHBoxLayout()
        for name in ("png", "svg", "pdf"):
            button = CheckButton(name.upper())
            self.formats[name] = button
            line.addWidget(button)
        layout.addLayout(line)
        self.run = QtWidgets.QPushButton("开始批处理")
        self.run.setProperty("intent", "primary")
        self.run.clicked.connect(self.start)
        self.resume_button = QtWidgets.QPushButton("重试当前组")
        self.skip_button = QtWidgets.QPushButton("跳过当前组")
        self.stop = QtWidgets.QPushButton("停止")
        self.resume_button.clicked.connect(
            lambda: self.runner.resume() if getattr(self, "runner", None) else None
        )
        self.skip_button.clicked.connect(
            lambda: self.runner.skip() if getattr(self, "runner", None) else None
        )
        self.stop.clicked.connect(
            lambda: self.runner.cancel() if getattr(self, "runner", None) else None
        )
        layout.addWidget(self.run)
        layout.addWidget(row(self.resume_button, self.skip_button, self.stop))
        self.status = QtWidgets.QLabel(
            "在各处理类别配置参数后加入步骤；默认使用上一步的结果。"
        )
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.refresh()

    def refresh(self):
        old=self.saved.currentData()
        with QtCore.QSignalBlocker(self.saved):
            self.saved.clear()
            self.saved.addItem("—", "")
            for name in store("flows"):
                self.saved.addItem(name, name)
            self.saved.setCurrentIndex(max(0,self.saved.findData(old)))

    def showEvent(self, event):
        name = self.graph.currentData()
        with QtCore.QSignalBlocker(self.graph):
            self.graph.clear()
            self.graph.addItem("不使用整图模板", "")
            for item in store("graphs"):
                self.graph.addItem(item, item)
            self.graph.setCurrentIndex(max(0, self.graph.findData(name)))
        super().showEvent(event)

    def refresh_steps(self):
        self.step_list.clear()
        for index, step in enumerate(self.steps):
            self.step_list.addItem(
                f"{index + 1}. "
                + step["title"]
                + " · "
                + ("原始对象" if step.get("input") == "original" else "上一步结果")
            )
        if self.editing is None:
            self.input.setCurrentIndex(self.input.findData('previous' if self.steps else 'original'))

    def add_process(self):
        title = self.category.currentData()
        options = {}
        for key, widget in self.control.options[title].items():
            if key in {"summary", "region"}:
                continue
            options[key] = (
                [k for k, b in widget.items() if b.isChecked()]
                if isinstance(widget, dict)
                else widget.currentData()
                if isinstance(widget, QtWidgets.QComboBox)
                else widget.value()
            )
        reference = options.pop("reference", None)
        refspec = None
        if reference:
            sheet = next(
                s for s in self.owner.get_data_sheets() if s.id == reference[0]
            )
            refspec = descriptor(sheet, reference[1])
        scope = {"mode": "all"}
        region = (
            self.control.options[title].get("region")
            if title == "交互区域分析"
            else None
        )
        if self.control.current_data.isChecked() or region and region.isChecked():
            if self.control.plot:
                from tailor.graph_presentation import physical

                limits = physical(
                    self.control.analysis_region.getRegion()
                    if region and region.isChecked()
                    else self.control.plot.ui.plot_widget.viewRange()[0],
                    self.control.plot.presentation.axes["x"],
                )
                scope = {"mode": "x", "range": sorted(float(v) for v in limits)}
            else:
                scope = {
                    "mode": "rows",
                    "ranges": [
                        [b.top(), b.bottom()]
                        for b in self.control.document.ui.data_view.selectionModel().selection()
                    ],
                }
        step = {
            "kind": "process",
            "method": self.control.methods[title].currentData(),
            "title": title,
            "options": options,
            "reference": refspec,
            "scope": scope,
            "input": self.input.currentData(),
            "output": self.output.currentData(),
        }
        if self.editing is not None and 0 <= self.editing < len(self.steps):
            step["scope"] = copy.deepcopy(self.steps[self.editing].get("scope", scope))
            self.steps[self.editing] = step
            self.editing = None
            self.add_process_button.setText("加入处理步骤")
        else:
            self.steps.append(step)
        self.refresh_steps()

    def edit_step(self):
        index = self.step_list.currentRow()
        if index < 0:
            return
        step = self.steps[index]
        self.output.setCurrentIndex(
            max(0, self.output.findData(step.get("output", "first")))
        )
        self.input.setCurrentIndex(
            max(0, self.input.findData(step.get("input", "previous")))
        )
        if step["kind"] == "fit":
            # Fit settings are edited in one small dialog, preserving explicit
            # parameter bounds/values already captured from the native fitter.
            text, accepted = QtWidgets.QInputDialog.getMultiLineText(
                self,
                "编辑拟合步骤",
                "拟合设置（模型、初值和约束）",
                json.dumps(step["fit"], ensure_ascii=False, indent=2),
            )
            if accepted:
                try:
                    value = json.loads(text)
                    if not isinstance(value, dict) or not value.get("preset"):
                        raise ValueError("拟合设置必须包含preset。")
                    self.steps[index]["fit"] = value
                    self.steps[index]["input"] = self.input.currentData()
                    self.refresh_steps()
                except (ValueError, TypeError) as error:
                    self.status.setText(str(error))
            return
        title = step["title"]
        self.category.setCurrentIndex(self.category.findData(title))
        self.control.methods[title].setCurrentIndex(
            self.control.methods[title].findData(step["method"])
        )
        for key, value in step["options"].items():
            widget = self.control.options[title].get(key)
            if isinstance(widget, dict):
                for name, button in widget.items():
                    button.setChecked(name in value)
            elif isinstance(widget, QtWidgets.QComboBox):
                widget.setCurrentIndex(max(0, widget.findData(value)))
            elif hasattr(widget, "setValue"):
                widget.setValue(value)
        if step.get("reference"):
            try:
                sheet = self.control.sheets()[self.control.targets[0][0]]
                ref = (
                    sheet.id,
                    resolve(sheet, step["reference"], self.mapping.currentData()),
                )
                from tailor.ui_widgets import data_index

                widget = self.control.options[title]["reference"]
                widget.setCurrentIndex(data_index(widget, ref))
            except (KeyError, IndexError, ValueError):
                self.status.setText("参考列映射已失效，请重新选择参考列。")
        self.editing = index
        self.add_process_button.setText("更新所选处理步骤")
        self.control.select_category(title)
        self.status.setText("修改上方参数后，返回分析流程，点击“更新所选处理步骤”。")

    def preflight(self):
        try:
            flow = self.configuration()
            messages = []
            if not flow["steps"] and not flow["export"]:
                raise ValueError("请添加步骤或导出格式。")
            if self.source.currentData() == "files":
                if not self.files:
                    raise ValueError("未选择文件。")
                for name in self.files:
                    path = Path(name)
                    if not path.is_file():
                        raise ValueError("文件不存在：" + path.name)
                    header = 0 if self.header.isChecked() else None
                    frame = (
                        pd.read_excel(
                            path,
                            nrows=0,
                            header=header,
                            sheet_name=self.excel_sheet.text().strip() or 0,
                        )
                        if path.suffix.lower() in {".xlsx", ".xls", ".xlsm"}
                        else pd.read_csv(
                            path,
                            sep=self.delimiter.currentData(),
                            encoding=self.encoding.currentData(),
                            header=header,
                            engine="python",
                            nrows=0,
                        )
                    )
                    names = list(frame.columns)
                    for descriptor_ in [
                        flow["columns"]["x"],
                        *flow["columns"]["ys"],
                        *[
                            step["reference"]
                            for step in flow["steps"]
                            if step.get("reference")
                        ],
                    ]:
                        if (
                            self.mapping.currentData() == "name"
                            and names.count(descriptor_["name"]) != 1
                        ):
                            raise ValueError(
                                path.name + " 缺少唯一列：" + descriptor_["name"]
                            )
                        if (
                            self.mapping.currentData() != "name"
                            and not 0 <= descriptor_["index"] < len(names)
                        ):
                            raise ValueError(path.name + " 列序号越界。")
                    messages.append(path.name + "：列映射可用")
            else:
                ids = (
                    self.selected_sheets
                    if self.source.currentData() == "sheets"
                    else {sid for sid, _ in self.control.targets}
                )
                if not ids:
                    raise ValueError("未选择源列/工作表。")
                for sid in ids:
                    sheet = self.control.sheets()[sid]
                    for spec in [flow["columns"]["x"], *flow["columns"]["ys"]]:
                        resolve(sheet, spec, self.mapping.currentData())
                    for step in flow["steps"]:
                        if step.get("reference"):
                            resolve(
                                sheet, step["reference"], self.mapping.currentData()
                            )
                    messages.append(sheet.name + "：X/Y/参考列映射可用")
            for i, step in enumerate(flow["steps"]):
                messages.append(
                    f"{i + 1}. {step['title']} · 输入："
                    + ("原始对象" if step.get("input") == "original" else "上一步输出")
                    + " → 原表结果列"
                )
            self.status.setText(
                "检查通过（只读，执行时仍重新校验数据）。\n" + "\n".join(messages)
            )
            return True
        except (ValueError, KeyError, IndexError, OSError, TypeError) as error:
            self.status.setText("检查未通过：" + str(error))
            return False

    def add_fit(self):
        plot = self.control.plot
        selected = self.fit_preset.currentData()
        if selected is None:
            self.status.setText('请先选择拟合模型。')
            return
        if selected == '__current_model__':
            if plot is not None and getattr(plot.presentation, 'multi', False):
                router = getattr(plot, 'fit_router', None)
                plot = router.choice.currentData() if router is not None else None
            if plot is None or not getattr(plot.model, '_model_expression', '').strip():
                self.status.setText('当前图没有可用的拟合模型。')
                return
            from tailor.cst_names import rename_variables

            cfg = {
                "preset": plot.model.fit_preset_key,
                "expression": rename_variables(
                    plot.model._model_expression, {plot.model.x_col: "x"}
                ),
                "parameters": {
                    name: {"value": p.value, "min": p.min, "max": p.max, "vary": p.vary}
                    for name, p in plot.model._parameters.items()
                },
                "domain": list(plot.model.get_fit_domain()),
                "use_domain": plot.model.get_fit_domain_enabled(),
                "guess": self.guess.isChecked(),
            }
        else:
            cfg = {"preset": selected, "guess": self.guess.isChecked()}
        self.steps.append(
            {
                "kind": "fit",
                "title": "拟合 · " + self.fit_preset.currentText(),
                "fit": cfg,
                "input": self.input.currentData(),
                "output": self.output.currentData(),
            }
        )
        self.refresh_steps()

    def move(self, delta):
        index = self.step_list.currentRow()
        other = index + delta
        if index >= 0 and 0 <= other < len(self.steps):
            self.steps[index], self.steps[other] = self.steps[other], self.steps[index]
            self.refresh_steps()
            self.step_list.setCurrentRow(other)

    def remove(self):
        index = self.step_list.currentRow()
        if index >= 0:
            self.steps.pop(index)
            self.refresh_steps()

    def configuration(self):
        refs = self.control.targets
        if not refs:
            raise ValueError("请先在对象中选列，以确定流程的列映射。")
        sheet = next(s for s in self.owner.get_data_sheets() if s.id == refs[0][0])
        _, xkey = sheet.processing_controls.x_values(
            sheet, refs[0][1], allow_category=True
        )
        if not xkey:
            raise ValueError("请先指定X列。")
        ys = [descriptor(sheet, key) for sid, key in refs if sid == sheet.id]
        return {
            "steps": copy.deepcopy(self.steps),
            "columns": {
                "mode": self.mapping.currentData(),
                "x": descriptor(sheet, xkey),
                "ys": ys,
            },
            "import": {
                "encoding": self.encoding.currentData(),
                "delimiter": self.delimiter.currentData(),
                "header": self.header.isChecked(),
                "excel_sheet": self.excel_sheet.text().strip(),
            },
            "graph_template": self.graph.currentData(),
            "export": [name for name, b in self.formats.items() if b.isChecked()],
        }

    def save_flow(self):
        try:
            name = self.name.text().strip()
            if not name:
                raise ValueError("请输入流程名称。")
            value = self.configuration()
            save_named("flows", name, value)
            self.refresh()
            self.saved.setCurrentIndex(self.saved.findData(name))
            self.status.setText("流程、列映射、处理参数、拟合及导出设置已保存。")
        except (ValueError, KeyError, StopIteration) as error:
            self.status.setText(str(error))

    def load_flow(self, *args):
        value = store("flows").get(self.saved.currentData())
        if not value:
            self.name.clear()
            return
        self.steps = copy.deepcopy(value["steps"])
        self.name.setText(self.saved.currentData())
        self.refresh_steps()
        self.mapping.setCurrentIndex(
            max(0, self.mapping.findData(value["columns"].get("mode", "name")))
        )
        options = value.get("import", {})
        self.encoding.setCurrentIndex(
            max(0, self.encoding.findData(options.get("encoding")))
        )
        self.delimiter.setCurrentIndex(
            max(0, self.delimiter.findData(options.get("delimiter")))
        )
        self.header.setChecked(options.get("header", True))
        self.excel_sheet.setText(options.get("excel_sheet", ""))
        for name, b in self.formats.items():
            b.setChecked(name in value.get("export", []))
        self.graph.setCurrentIndex(
            max(0, self.graph.findData(value.get("graph_template")))
        )
        self.loaded_columns = copy.deepcopy(value["columns"])

    def fill_sheets(self):
        self.sheet_menu.clear()
        for sheet in self.owner.get_data_sheets():
            action = self.sheet_menu.addAction(sheet.name)
            action.setCheckable(True)
            action.setChecked(sheet.id in self.selected_sheets)
            action.toggled.connect(
                lambda checked, sid=sheet.id: (
                    self.selected_sheets.add(sid)
                    if checked
                    else self.selected_sheets.discard(sid)
                )
            )

    def choose_files(self):
        self.files, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            "选择批处理文件",
            "",
            "数据文件 (*.csv *.txt *.dat *.tsv *.xls *.xlsx *.xlsm)",
        )
        self.status.setText(f"已选择{len(self.files)}个文件；列映射取当前对象。")

    def start(self):
        if self.owner.data_operation_busy() or getattr(
            self.owner, "_batch_runner", None
        ):
            self.status.setText("请等待当前计算结束。")
            return
        try:
            value = self.configuration()
            if hasattr(self, "loaded_columns"):
                value["columns"] = copy.deepcopy(self.loaded_columns)
                value["columns"]["mode"] = self.mapping.currentData()
            if not value["steps"] and not value["export"]:
                raise ValueError("请添加分析步骤，或选择图形导出格式。")
            mode = self.source.currentData()
            tasks = []
            if mode == "files":
                tasks = [{"file": path} for path in self.files]
            else:
                refs = list(self.control.targets)
                if mode == "sheets":
                    refs = []
                    for sheet in self.owner.get_data_sheets():
                        if sheet.id in self.selected_sheets:
                            refs.extend(
                                (sheet.id, resolve(sheet, d, value["columns"]["mode"]))
                                for d in value["columns"]["ys"]
                            )
                grouped = {}
                if any(step.get("method") == "replicate" for step in value["steps"]):
                    for ref in refs:
                        grouped.setdefault(ref[0], []).append(ref)
                    groups = list(grouped.values())
                else:
                    groups = [[ref] for ref in refs]
                for group in groups:
                    sheet = next(
                        s for s in self.owner.get_data_sheets() if s.id == group[0][0]
                    )
                    tasks.append(
                        {
                            "targets": group,
                            "name": sheet.name
                            + " · "
                            + sheet.model.data_model.get_column_name(group[0][1]),
                        }
                    )
            if not tasks:
                raise ValueError("没有待处理对象或文件。")
            folder = None
            if value["export"]:
                chosen = QtWidgets.QFileDialog.getExistingDirectory(
                    self, "选择批处理导出位置"
                )
                if not chosen:
                    return
                folder = Path(chosen) / (
                    "Curve_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                )
            self.runner = BatchRunner(self.control, value, tasks, folder)
            self.runner.changed.connect(self.status.setText)
            self.runner.finished.connect(self.batch_finished)
            self.run.setEnabled(False)
            self.runner.start()
        except (ValueError, KeyError, StopIteration, IndexError, OSError) as error:
            self.status.setText(str(error))
            self.run.setEnabled(True)

    def batch_finished(self):
        self.run.setEnabled(True)

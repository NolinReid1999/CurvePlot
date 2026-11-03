"""Analysis provenance in existing column metadata and existing undo transactions."""

from tailor.compact_controls import CheckButton

import copy
import json
import uuid

import numpy as np
import pandas as pd
import xxhash
from PySide6 import QtCore, QtWidgets


def values_hash(values):
    series = pd.Series(values)
    finite = np.flatnonzero(series.notna().to_numpy())
    series = series.iloc[: int(finite[-1]) + 1] if len(finite) else series.iloc[:0]
    return xxhash.xxh3_64(
        pd.util.hash_pandas_object(series, index=False).to_numpy().tobytes()
    ).hexdigest()


def input_signature(owner, recipe):
    sheets = {s.id: s for s in owner.get_data_sheets()}
    digest = xxhash.xxh3_64()
    refs = [(c["sheet"], c["key"]) for c in recipe["objects"]]
    refs += [(c["sheet"], c["xkey"]) for c in recipe["objects"] if c.get("xkey")]
    reference = recipe["options"].get("reference")
    if reference:
        refs.append(tuple(reference))
        sheet = sheets.get(reference[0])
        if sheet:
            _, xkey = sheet.processing_controls.x_values(sheet, reference[1])
            if xkey:
                refs.append((sheet.id, xkey))
    for sid, key in sorted(set(refs)):
        sheet = sheets[sid]
        digest.update(f"{sid}:{key}:".encode())
        digest.update(values_hash(sheet.model.data_model.get_column(key)).encode())
        digest.update(
            np.asarray(
                sorted(sheet.model.data_model._excluded.get(key, ())), dtype=np.int64
            ).tobytes()
        )
    return digest.hexdigest()


def records(owner):
    grouped = {}
    for sheet in owner.get_data_sheets():
        for key in sheet.model.columnLabels():
            try:
                source = json.loads(
                    sheet.model._metadata.get(key, {}).get("source") or "{}"
                )
                recipe = source.get("recipe")
                if recipe:
                    record = grouped.setdefault(
                        recipe["id"], {"recipe": recipe, "outputs": []}
                    )
                    record["outputs"].append(
                        (sheet, key, source["slot"], source["output_hash"])
                    )
            except (ValueError, KeyError, TypeError):
                continue
    order=getattr(owner,'_analysis_choice_order',None)
    if order is None:order={};owner._analysis_choice_order=order
    for identifier in grouped:
        if identifier not in order:order[identifier]=len(order)
    return sorted(grouped.values(),key=lambda row:(row['recipe'].get('created_order',0),order[row['recipe']['id']]))


def stale(owner, record):
    try:
        if input_signature(owner, record["recipe"]) != record["recipe"]["signature"]:
            return True
        return any(
            values_hash(sheet.model.data_model.get_column(key)) != expected
            for sheet, key, _slot, expected in record["outputs"]
        )
    except (ValueError, KeyError, TypeError):
        return True


def recipe_for(control, method, options, objects):
    old = getattr(control, "recompute_record", None)
    recipe = (
        copy.deepcopy(old["recipe"])
        if old
        else {
            "id": uuid.uuid4().hex,
            "title": control.title,
            "auto": False,
            "method": method,
            "options": copy.deepcopy(options),
            "objects": objects,
        }
    )
    if old and control.recompute_as_new:
        recipe["id"] = uuid.uuid4().hex
        recipe["auto"] = False
    if not old or control.recompute_as_new:
        import time
        recipe['created_order']=time.time_ns()
    recipe["signature"] = input_signature(control.owner, recipe)
    return recipe


def result_columns(context, result, name, title, recipe):
    specs = []
    if result["metrics"]:
        specs = [
            {"name": name + "_" + __import__("tailor.column_analysis",fromlist=["STATISTICS"]).STATISTICS.get(k,k), "values": np.array([v]), "slot": k}
            for k, v in result["metrics"].items()
        ]
    elif result.get("series"):
        for label, values in result["series"].items():
            padded = np.full(context["rows"], np.nan)
            padded[context["indices"]] = values
            specs.append(
                {
                    "name": name + "_" + label,
                    "values": padded,
                    "slot": label,
                    "role": "YErr" if label in {"SD", "SEM"} else "Y",
                }
            )
    elif result["aligned"]:
        values = np.full(context["rows"], np.nan)
        values[context["indices"]] = result["y"]
        specs = [{"name": name + "_" + title, "values": values, "slot": "Y"}]
    else:
        specs = [
            {
                "name": name + "_" + title + "_X",
                "values": result["x"],
                "role": "X",
                "slot": "X",
            },
            {
                "name": name + "_" + title,
                "values": result["y"],
                "paired_x": True,
                "slot": "Y",
            },
        ]
    curve_specs=[]
    if result['metrics'] and (result.get('series') or result.get('y') is not None):
        curve_specs=result_columns(context,{**result,'metrics':{}},name,title,recipe)
    from tailor.analysis_units import processing_unit
    for spec in specs:
        spec['unit']=processing_unit(recipe['method'],spec['slot'],context.get('units',{}),context.get('reference_unit'))
        source = {
            "counts": result.get("counts", {}),
            "scalar": bool(result.get('metrics')),
            "type": recipe["method"],
            "column": context["key"],
            "x": context["xkey"],
            "options": recipe["options"],
            "recipe": recipe,
            "slot": f"{context['sheet']}:{context['key']}:{spec.pop('slot')}",
            "output_hash": values_hash(spec["values"]),
        }
        spec.update(
            comment=title + "；原始数据保留；误差未传播",
            source=json.dumps(source, ensure_ascii=False),
        )
    return specs+curve_specs


def rerun(control, record, as_new=False):
    if control.owner.data_operation_busy():
        control.owner.statusBar().showMessage("请等待当前计算完成。")
        return False
    recipe = record["recipe"]
    control.targets = [(c["sheet"], c["key"]) for c in recipe["objects"]]
    control.launch(
        recipe["method"],
        copy.deepcopy(recipe["options"]),
        True,
        recipe["title"],
        record=record,
        as_new=as_new,
    )
    return control.job is not None


class AnalysisMonitor(QtCore.QObject):
    changed = QtCore.Signal()

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.failed = set()
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.scan)
        self.pages = []

    def attach(self, sheet):
        sheet.model.historyChanged.connect(lambda: self.timer.start())

    def scan(self):
        from tailor.result_pages import refresh_processing

        refresh_processing(self.owner)
        self.changed.emit()
        if getattr(self.owner,"data_operation_busy",lambda:False)() or getattr(
            self.owner, "_batch_runner", None
        ):
            self.timer.start(300)
            return
        for record in records(self.owner):
            recipe = record["recipe"]
            if not recipe.get("auto") or not stale(self.owner, record):
                continue
            try:
                signature = input_signature(self.owner, recipe)
            except (KeyError, ValueError, TypeError):
                continue
            token = (recipe["id"], signature)
            if token in self.failed:
                continue
            control = record["outputs"][0][0].processing_controls
            self.failed.add(token)
            if rerun(control, record):
                self.timer.start(300)
                return


def monitor(owner):
    if not hasattr(owner, "_analysis_monitor"):
        owner._analysis_monitor = AnalysisMonitor(owner)
    return owner._analysis_monitor


class AnalysisControls(QtWidgets.QWidget):
    def __init__(self, control):
        super().__init__()
        self.control = control
        self.current = QtWidgets.QComboBox()
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        self.auto = CheckButton("自动重算此结果")
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.current)
        layout.addWidget(self.status)
        layout.addWidget(self.auto)
        row = QtWidgets.QHBoxLayout()
        self.result_actions=[]
        for title, new in [("重算并更新", False), ("另存为新结果", True)]:
            button = QtWidgets.QPushButton(title)
            button.clicked.connect(lambda checked=False, n=new: self.calculate(n))
            row.addWidget(button)
            self.result_actions.append(button)
        layout.addLayout(row)
        self.current.currentIndexChanged.connect(self.describe)
        self.auto.toggled.connect(self.set_auto)
        monitor(control.owner).changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        old = self.current.currentData()
        self.items = records(self.control.owner)
        with QtCore.QSignalBlocker(self.current):
            self.current.clear()
            self.current.addItem('—',None)
            for item in self.items:
                recipe = item["recipe"]
                prefix = "已过期 · " if stale(self.control.owner, item) else "有效 · "
                self.current.addItem(
                    prefix + recipe["title"] + " · " + item["outputs"][0][0].name,
                    recipe["id"],
                )
            self.current.setCurrentIndex(max(0, self.current.findData(old)))
        self.describe()

    def record(self):
        return next(
            (r for r in self.items if r["recipe"]["id"] == self.current.currentData()),
            None,
        )

    def describe(self):
        record = self.record()
        self.auto.setEnabled(record is not None)
        for button in self.result_actions:button.setEnabled(record is not None)
        with QtCore.QSignalBlocker(self.auto):
            self.auto.setChecked(bool(record and record["recipe"].get("auto")))
        if not record:
            self.status.setText(
                "生成处理结果后，可在这里查看来源、更新结果及设置自动重算。"
            )
            return
        recipe = record["recipe"]
        sheets = {s.id: s for s in self.control.owner.get_data_sheets()}
        names = []
        for obj in recipe["objects"]:
            sheet = sheets.get(obj["sheet"])
            if sheet and obj["key"] in sheet.model.columnLabels():
                names.append(
                    sheet.name
                    + " · "
                    + sheet.model.data_model.get_column_name(obj["key"])
                )
        self.status.setText(
            "来源："
            + "、".join(names)
            + "\n参数："
            + json.dumps(recipe["options"], ensure_ascii=False)
            + "\n"
            + (
                "数据或结果已变化，请重新计算。"
                if stale(self.control.owner, record)
                else "结果与来源一致。"
            )
        )

    def calculate(self, as_new):
        record = self.record()
        if record:
            rerun(self.control, record, as_new)

    def set_auto(self, enabled):
        record = self.record()
        if not record:
            return
        if enabled:
            inputs = {(c["sheet"], c["key"]) for c in record["recipe"]["objects"]}
            outputs = {(s.id, key) for s, key, *_ in record["outputs"]}
            if inputs & outputs:
                with QtCore.QSignalBlocker(self.auto):
                    self.auto.setChecked(False)
                self.status.setText("来源与输出重叠，不能自动重算。")
                return
        for sheet in {s for s, *_ in record["outputs"]}:

            def apply(sheet=sheet):
                for source_sheet, key, *_ in record["outputs"]:
                    if source_sheet is sheet:
                        source = json.loads(sheet.model._metadata[key]["source"])
                        source["recipe"]["auto"] = enabled
                        sheet.model._metadata[key]["source"] = json.dumps(
                            source, ensure_ascii=False
                        )

            sheet.model._structural("自动重算设置", apply)
        monitor(self.control.owner).failed.clear()
        monitor(self.control.owner).timer.start()

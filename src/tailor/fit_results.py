"""Persistent result documents around Tailor's existing lmfit execution."""

import copy
import json
import re
from datetime import datetime
from types import SimpleNamespace

import lmfit
import numpy as np
import pyqtgraph as pg
import xxhash
from PySide6 import QtCore, QtWidgets

from tailor.analysis_units import parameter_unit
from tailor.fit_metrics import fit_statistics, peak_features
from tailor.fit_presets import get_preset
from tailor.fold_panel import FoldPanel, stack


def fit_frame(model):
    frame = model._get_data_as_dataframe(include_excluded=False)
    if model.get_fit_domain_enabled():
        lower, upper = model.get_fit_domain()
        frame = frame[frame.x.between(lower, upper, inclusive="both")]
    return frame


def source_hash(model):
    frame = fit_frame(model)
    digest = xxhash.xxh3_64(frame.to_numpy().tobytes())
    digest.update(frame.index.to_numpy(dtype=np.int64).tobytes())
    # Include total rows so inserting empty rows cannot silently keep alignment.
    digest.update(str(len(model.data_model._data)).encode())
    return digest.hexdigest()


def settings(model):
    return {
        "expression": model._model_expression,
        "preset": model.fit_preset_key,
        "columns": [model.x_col, model.y_col, model.x_err_col, model.y_err_col],
        "domain": list(model.get_fit_domain()),
        "use_domain": model.get_fit_domain_enabled(),
        "initial": {
            k: {"value": p.value, "min": p.min, "max": p.max, "vary": p.vary}
            for k, p in model._parameters.items()
        },
    }


def fit_token(model):
    return source_hash(model), json.dumps(settings(model), sort_keys=True)


def record_source_hash(model, record):
    source = copy.copy(model)
    cfg = record["settings"]
    source.x_col, source.y_col, source.x_err_col, source.y_err_col = cfg["columns"]
    source._fit_domain = tuple(cfg["domain"])
    source._use_fit_domain = cfg["use_domain"]
    return source_hash(source)


def short_model_name(key, title):
    short = {
        "linear": "线性", "quadratic": "二次", "gaussian": "高斯",
        "lorentzian": "洛伦兹", "double_gaussian": "双高斯",
        "double_lorentzian": "双洛伦兹", "sine": "正弦",
        "damped_sine": "阻尼正弦", "exponential": "指数衰减",
    }.get(key)
    if short is not None:
        return short
    key = key or ""
    for prefix, ending in (
        ("polynomial_", "次多项式"),
        ("multi_gaussian_", "峰高斯"),
        ("multi_lorentzian_", "峰洛伦兹"),
    ):
        if key.startswith(prefix):
            return key[len(prefix):] + ending
    return title.split("（", 1)[0].replace(" ", "")


class StoredFit:
    """Read-only ModelResult subset: evaluate stored parameters, never optimize."""

    def __init__(self, record, model):
        self.record = record
        cfg = record["settings"]
        self.model = lmfit.models.ExpressionModel(
            cfg["expression"], independent_vars=[cfg["columns"][0]]
        )
        self.params = lmfit.Parameters()
        for name, p in record["parameters"].items():
            self.params.add(
                name, value=p["value"], min=p["min"], max=p["max"], vary=p["vary"]
            )
            self.params[name].stderr = p["stderr"]
        stats = record["statistics"]
        self.ndata = stats["ndata"]
        self.nvarys = stats["nvarys"]
        self.var_names = record.get(
            "var_names", [name for name, p in self.params.items() if p.vary]
        )
        self.userkws = {}
        self.nfree = self.ndata - self.nvarys
        self.chisqr = record["chisqr"]
        self.redchi = record["redchi"]
        self.nfev = record["nfev"]
        self.rsquared = stats["r2"]
        self.errorbars = record["errorbars"]
        self.success = True
        self.message = record["message"]
        self.covar = (
            np.asarray(record["covariance"])
            if record.get("covariance") is not None
            else None
        )
        self._source = model

    def eval(self, **kwargs):
        return self.model.eval(params=self.params, **kwargs)

    def eval_uncertainty(self, **kwargs):
        return lmfit.model.ModelResult.eval_uncertainty(self, **kwargs)

    @property
    def best_fit(self):
        return self.eval(**{self._source.x_col: fit_frame(self._source).x.to_numpy()})


def make_record(plot, fit, result_id):
    model = plot.model
    frame = fit_frame(model)
    predicted = np.asarray(fit.best_fit, dtype=float)
    if len(frame) != len(predicted) or not np.all(np.isfinite(predicted)):
        raise ValueError("拟合数据与源行不一致，未写入结果")
    statistics = fit_statistics(frame.y.to_numpy(), predicted, int(fit.nvarys))
    parameters = {
        k: {
            "value": float(p.value),
            "stderr": float(p.stderr)
            if p.stderr is not None and np.isfinite(p.stderr)
            else None,
            "min": float(p.min),
            "max": float(p.max),
            "vary": bool(p.vary),
        }
        for k, p in fit.params.items()
    }
    values = {k: p["value"] for k, p in parameters.items()}
    features = peak_features(model.fit_preset_key, values)
    if model.fit_preset_key in {"sine", "damped_sine"}:
        omega = abs(values["frequency"])
        features.update(
            frequency_cycles=omega / (2 * np.pi),
            period=2 * np.pi / omega if omega else None,
        )
    title = (
        get_preset(model.fit_preset_key).title if model.fit_preset_key else "自定义公式"
    )
    curve_x = np.linspace(float(frame.x.min()), float(frame.x.max()), 1000)
    curve_y = np.asarray(fit.eval(**{model.x_col: curve_x}))
    sample = np.linspace(0, len(frame) - 1, min(len(frame), 3000), dtype=int)
    columns = list(plot.data_sheet.model.columnLabels())
    units = {
        axis: plot.data_sheet.model.column_metadata(columns.index(col))["unit"]
        for axis, col in (("x", model.x_col), ("y", model.y_col))
    }
    for name, parameter in parameters.items():
        parameter['unit'] = parameter_unit(model.fit_preset_key, name, units)
    from tailor.column_titles import remark
    result_name = remark(plot.data_sheet.model,model.y_col) + short_model_name(model.fit_preset_key, title) + "拟合"
    record = {
        "id": result_id,
        "name": result_name,
        "title": title,
        "plot_id": plot.id,
        "sheet_id": plot.data_sheet.id,
        "sheet_name": plot.data_sheet.name,
        "x_name": model.get_x_col_name(),
        "y_name": model.get_y_col_name(),
        "units": units,
        "created": datetime.now().isoformat(timespec="seconds"),
        "settings": settings(model),
        "source_hash": source_hash(model),
        "expression": model.get_model_expression(),
        "parameters": parameters,
        "statistics": statistics,
        "features": features,
        "chisqr": float(fit.chisqr),
        "redchi": float(fit.redchi),
        "nfev": int(fit.nfev),
        "errorbars": bool(fit.errorbars),
        "message": str(fit.message),
        "covariance": fit.covar.tolist() if fit.covar is not None else None,
        "var_names": list(fit.var_names),
        "stale": False,
        "column_id": None,
        "curve_x": curve_x.tolist(),
        "curve_y": curve_y.tolist(),
        "residual_x": frame.x.to_numpy()[sample].tolist(),
        "residual_y": (frame.y.to_numpy() - predicted)[sample].tolist(),
    }
    output = np.full(plot.data_sheet.model.rowCount(), np.nan)
    output[frame.index.to_numpy(dtype=int)] = predicted
    return record, output


def record_columns(record):
    """All real worksheet outputs owned by one fit, including its peaks."""
    return [key for key in [record.get('column_id')] +
            [c.get('column_id') for c in record.get('components', [])] if key is not None]


def curve_column(record, key):
    if key.startswith('component:') or ':component:' in key:
        try:
            index = int(key.rsplit(':', 1)[1])
        except ValueError:
            return None
        return next((c.get('column_id') for c in record.get('components', [])
                     if c.get('index') == index), None)
    return record.get('column_id')


def component_outputs(plot, fit, record):
    """Evaluate the existing lmfit peak components on original source rows.

    Each peak includes the common offset, matching the displayed peak curves;
    summing these columns therefore repeats that baseline once per peak.
    """
    key = plot.model.fit_preset_key or ''
    if not key.startswith(('double_', 'multi_')):
        return []
    from tailor.fit_presets import create_library_model
    native = create_library_model(key)
    values = {name: p.value for name, p in fit.params.items()}
    params = native.make_params(**{k: v for k, v in values.items() if k != 'offset'})
    frame = fit_frame(plot.model)
    outputs = []
    for index, component in enumerate(native.components, 1):
        y = np.asarray(component.eval(params=params, x=frame.x.to_numpy()), dtype=float)
        y = y + values.get('offset', 0)
        if y.shape != (len(frame),) or not np.all(np.isfinite(y)):
            raise ValueError('分峰数据与源行不一致，未写入结果')
        output = np.full(plot.data_sheet.model.rowCount(), np.nan)
        output[frame.index.to_numpy(dtype=int)] = y
        outputs.append({'index': index, 'name': record['name'] + f'分峰{index}',
                        'values': output, 'baseline_included': True})
    return outputs


def result_tabs(owner):
    from tailor.result_pages import fit_tabs

    tabs = owner.ui.tabWidget
    return fit_tabs(owner) + [
        tabs.widget(i)
        for i in range(tabs.count())
        if isinstance(tabs.widget(i), FitResultTab)
    ]


def publish_result(plot, fit):
    """Prepare all output before one guarded spreadsheet write; preserve old fit on failure."""
    records = plot.fit_records
    before = (copy.deepcopy(records), plot.active_fit_id)
    selected = getattr(getattr(plot, "fit_actions", None), "modify_id", None)
    active = next((r for r in records if r["id"] == selected), None)
    all_records = [r for p in plot.main_window.get_plots() for r in p.fit_records]
    used_ids = [r["id"] for r in all_records]
    for source_sheet in plot.main_window.get_data_sheets():
        for metadata in source_sheet.model._metadata.values():
            tag = metadata.get("source", "")
            parts = tag.split(':')
            if len(parts) >= 2 and parts[0] == 'fit' and parts[1].isdigit():
                used_ids.append(int(parts[1]))
    result_id = active["id"] if active else max(used_ids, default=0) + 1
    record, output = make_record(plot, fit, result_id)
    sheet = plot.data_sheet.model
    outputs = component_outputs(plot, fit, record)
    specs = [{'name': record['name'], 'values': output, 'source': f'fit:{result_id}', 'role': 'none', 'unit': record['units']['y']}]
    specs += [{'name': c['name'], 'values': c['values'],
               'source': f'fit:{result_id}:component:{c["index"]}', 'role': 'none', 'unit': record['units']['y']} for c in outputs]
    old_components = {c['index']: c for c in (active or {}).get('components', [])}
    old_keys = [(active or {}).get('column_id')] + [old_components.get(c['index'], {}).get('column_id') for c in outputs]
    unused = [c['column_id'] for i, c in old_components.items()
              if i > len(outputs) and c.get('column_id') in sheet.columnLabels()
              and sheet._metadata.get(c['column_id'], {}).get('source') == f'fit:{result_id}:component:{i}']
    if unused:
        from tailor.result_pages import dependencies
        deps = dependencies(plot.main_window, {(plot.data_sheet.id, k) for k in unused},
                            skip_fit=(plot, result_id))
        if deps:
            raise ValueError('待移除的分峰列被其他对象引用，请另存新拟合：' + '；'.join(deps))
    keys = [None] * len(specs)

    def write_outputs():
        labels = list(sheet.columnLabels())
        reuse, append = [], []
        for index, (spec, old_key) in enumerate(zip(specs, old_keys, strict=True)):
            if (old_key in labels and old_key not in record['settings']['columns']
                    and (not active or active['settings']['columns']==record['settings']['columns'])
                    and sheet._metadata.get(old_key, {}).get('source') == spec['source']):
                keys[index] = old_key
                reuse.append((index, spec, old_key))
            else:
                append.append((index, spec))
        if reuse:
            sheet.replace_results([s for _, s, _ in reuse], [k for _, _, k in reuse], title='更新拟合结果列')
            for _, spec, old_key in reuse:
                desired = sheet.data_model.normalize_column_name(spec['name'])
                taken = {sheet.column_metadata(i)['name'] for i, k in enumerate(labels) if k != old_key}
                unique, suffix = desired, 2
                while unique in taken:
                    unique = f'{desired}_{suffix}'; suffix += 1
                if not sheet.set_column_metadata(labels.index(old_key), name=unique, comment=unique, _record_edit=False):
                    raise ValueError('无法更新拟合列名称')
        if append:
            added = sheet.append_results([s for _, s in append], title='生成拟合结果列')
            for (index, _), key in zip(append, added, strict=True):
                keys[index] = key
                column = list(sheet.columnLabels()).index(key)
                unique = sheet.column_metadata(column)['name']
                if not sheet.set_column_metadata(column, comment=unique, _record_edit=False):
                    raise ValueError('无法设置拟合列名称')
        if unused:
            labels = list(sheet.columnLabels())
            if not sheet.remove_spans([(labels.index(k), 1) for k in unused], columns=True):
                raise ValueError('无法移除旧分峰列')
        if source_hash(plot.model) != record['source_hash']:
            raise ValueError('输出列影响了拟合源数据，已撤回写入，请使用独立源列')

    plot._publishing_fit = True
    try:
        if not sheet._structural('保存拟合及分峰数据', write_outputs):
            raise ValueError('无法写入拟合列（可能超过撤销历史内存限制），旧结果保留')
    finally:
        plot._publishing_fit = False
    record['column_id'] = keys[0]
    record['name'] = sheet.column_metadata(list(sheet.columnLabels()).index(keys[0]))['name']
    record['components'] = [dict(index=c['index'], column_id=k,
                                 name=sheet.column_metadata(list(sheet.columnLabels()).index(k))['name'],
                                 baseline_included=True)
                            for c, k in zip(outputs, keys[1:], strict=True)]
    if active:
        records[records.index(active)] = record
    else:
        records.append(record)
    plot.active_fit_id = result_id
    if hasattr(plot, "fit_actions"):
        plot.fit_actions.modify_id = None
        plot.fit_actions.current_id = result_id
    peaks=plot.preset_controls.manual_peaks
    peaks.centers=[];peaks.marker.setData([],[])
    with QtCore.QSignalBlocker(peaks.button):peaks.button.setChecked(False)
    show_result(plot, record, focus=False)
    from tailor.fit_actions import attach_history
    attach_history(plot, before, sheet._history[sheet._cursor-1])
    return record


def show_result(plot, record=None, focus=True):
    record = record or next(
        (r for r in plot.fit_records if r["id"] == plot.active_fit_id), None
    )
    if record is None:
        plot.main_window.statusBar().showMessage("请先完成一次拟合")
        return
    owner = plot.main_window
    tab = next(
        (
            t
            for t in result_tabs(owner)
            if t.plot is plot and t.record["id"] == record["id"]
        ),
        None,
    )
    if tab is None:
        tab = FitResultTab(plot, record)
        from tailor.result_pages import page

        page(owner, "fit").add(tab)
    else:
        tab.set_record(record)
    if hasattr(owner, "tab_controls"):
        owner.tab_controls.refresh()
    if focus:
        from tailor.result_pages import page

        notebook = page(owner, "fit")
        notebook.tabs.setCurrentWidget(tab)
        owner.ui.tabWidget.setCurrentWidget(notebook)


def clear_fits(plot):
    """Remove only output columns owned by this plot's fit records, as one edit."""
    from tailor.spreadsheet_model import Edit

    owner, sheet = plot.main_window, plot.data_sheet.model
    if owner.data_operation_busy():
        owner.statusBar().showMessage("请等待当前拟合或数据操作结束后撤销拟合。")
        return False
    records = copy.deepcopy(plot.fit_records)
    if not records and plot.model.best_fit is None:
        return False
    labels = list(sheet.columnLabels())
    owned = {
        key
        for r in records for key in record_columns(r)
        if key in labels and sheet._metadata.get(key, {}).get('source') in
        {f"fit:{r['id']}"} | {f"fit:{r['id']}:component:{c['index']}" for c in r.get('components', [])}
    }
    # A generated column may later have become another plot's source. Do not
    # silently invalidate that source graph (or a calculated-column dependency).
    for source in owner.get_plots():
        if source.data_sheet is plot.data_sheet and any(
            key in owned
            for key in (
                source.model.x_col,
                source.model.y_col,
                source.model.x_err_col,
                source.model.y_err_col,
            )
        ):
            owner.statusBar().showMessage(
                "拟合列正被曲线作为源数据使用，请先修改该曲线的数据来源。未清除拟合。"
            )
            return False
    from tailor.cst_names import get_variable_names

    for key, expression in sheet.data_model._calculated_column_expression.items():
        if key not in owned and owned.intersection(get_variable_names(expression)):
            owner.statusBar().showMessage("拟合列正被计算列引用，未清除拟合。")
            return False
    prior = {
        "records": records,
        "active": plot.active_fit_id,
        "checksum": plot.model._fit_data_checksum,
        "open_ids": {
            tab.record["id"] for tab in result_tabs(owner) if tab.plot is plot
        },
        "legend": copy.deepcopy(plot.presentation.legend),
        "initial": plot.ui.show_initial_fit.isChecked(),
    }
    empty = {
        "records": [],
        "active": None,
        "checksum": None,
        "open_ids": set(),
        "legend": copy.deepcopy(plot.presentation.legend),
        "initial": False,
    }
    empty["legend"]["entries"] = {
        key: value
        for key, value in empty["legend"].get("entries", {}).items()
        if key != "fit" and not key.startswith("component:")
    }
    extra = len(json.dumps(records, ensure_ascii=False).encode("utf-8")) + 4096
    estimated = (
        int(sheet.data_model._data.memory_usage(index=True, deep=True).sum()) * 2
        + 8192
        + extra
    )
    if not sheet._accept(estimated):
        return False
    spans = [(labels.index(key), 1) for key in owned]
    data_edit = None
    if spans:
        if not sheet.remove_spans(spans, columns=True):
            return False
        data_edit = sheet._history[sheet._cursor - 1]

    def restore(state):
        import shiboken6

        if not shiboken6.isValid(plot) or getattr(plot, "_graph_disposed", False):
            return
        for tab in result_tabs(owner):
            if tab.plot is plot:
                from tailor.result_pages import remove_fit_tab

                remove_fit_tab(owner, tab)
        plot.fit_records = copy.deepcopy(state["records"])
        plot.active_fit_id = state["active"]
        active = next(
            (
                r
                for r in plot.fit_records
                if r["id"] == state["active"] and not r["stale"]
            ),
            None,
        )
        plot.model.best_fit = StoredFit(active, plot.model) if active else None
        plot.model._fit_data_checksum = state["checksum"]
        plot.presentation.legend = copy.deepcopy(state["legend"])
        with QtCore.QSignalBlocker(plot.ui.show_initial_fit):
            plot.ui.show_initial_fit.setChecked(state["initial"])
        for record in plot.fit_records:
            if record["id"] in state["open_ids"]:
                show_result(plot, record, focus=False)
        plot.update_model_curves()
        plot.plot_best_fit()
        plot.update_info_box()
        plot.refresh_legend()
        for associated in owner.get_associated_multiplots(plot):
            associated.widget.draw_plot()
        owner.tab_controls.refresh()
        owner.mark_project_dirty()

    def replay(state, forward):
        if (
            data_edit is not None
            and (data_edit.forward() if forward else data_edit.backward()) is False
        ):
            return False
        restore(state)
        return True

    restore(empty)
    edit = Edit(
        "撤销拟合",
        lambda: replay(prior, False),
        lambda: replay(empty, True),
        (data_edit.size if data_edit else 0) + extra,
    )
    if data_edit is not None:
        sheet._history[sheet._cursor - 1] = edit
        sheet.historyChanged.emit()
    else:
        sheet._record(edit)
    owner.statusBar().showMessage(
        f"已清除 {len(records)} 个拟合结果及 {len(owned)} 列拟合数据。原始数据保留。"
    )
    return True


def refresh_records(plot, check_data=False):
    changed = False
    source_cache = {}
    for record in plot.fit_records:
        if record["stale"]:
            continue
        try:
            stale = False
            if check_data:
                cfg = record["settings"]
                key = (tuple(cfg["columns"]), tuple(cfg["domain"]), cfg["use_domain"])
                if key not in source_cache:
                    source_cache[key] = record_source_hash(plot.model, record)
                stale = source_cache[key] != record["source_hash"]
            # Records own immutable model/range/parameter snapshots. Preparing
            # another fit in the editor does not invalidate the saved result;
            # source edits are checked against that record's own source hash.
        except (ValueError, KeyError, IndexError):
            stale = True
        # Once obsolete, a record remains explicitly obsolete until refit.
        if stale and not record["stale"]:
            record["stale"] = True
            changed = True
    if changed or check_data:
        for tab in result_tabs(plot.main_window):
            if tab.plot is plot:
                tab.refresh_status()
    return changed


def format_value(value):
    return "不可计算" if value is None or not np.isfinite(value) else f"{value:.10g}"


def record_text(record):
    stats = record["statistics"]
    lines = [
        record["name"],
        "状态：" + ("已过期，需重新拟合" if record["stale"] else "拟合完成"),
        f"来源：{record['sheet_name']} / {record['x_name']} → {record['y_name']}",
        "函数：" + record["expression"],
        "R²：" + format_value(stats["r2"]),
        "RMSE：" + format_value(stats["rmse"]),
    ]
    for name, p in record["parameters"].items():
        lines.append(
            f"{name}: {format_value(p['value'])} ± {format_value(p['stderr'])} {p.get('unit', '')}"
        )
    for name, value in record["features"].items():
        lines.append(f"{name}: {format_value(value)}")
    return "\n".join(lines)


class FitResultTab(QtWidgets.QWidget):
    document_kind = "fit"

    def __init__(self, plot, record):
        super().__init__()
        from tailor.appearance import manager

        manager().register(self)
        self.plot = plot
        self.main_window = plot.main_window
        self.data_sheet = plot.data_sheet
        self.ui = SimpleNamespace()
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(5, 4, 5, 4)
        actions = QtWidgets.QHBoxLayout()
        self.action_buttons = {}
        for title, callback in (
            ("重新拟合", self.refit),
            ("另存为新结果", self.save_new),
            ("定位源表", self.locate_sheet),
            ("定位源图", self.locate_plot),
            ("复制结果", self.copy_result),
            ("参数 CSV…", self.export),
        ):
            b = QtWidgets.QPushButton(title)
            b.clicked.connect(callback)
            self.action_buttons[title] = b
            if title == "另存为新结果":
                b.setToolTip(
                    "保留本结果，使用本模型设置重新拟合当前源数据，生成独立结果列与结果页"
                )
            actions.addWidget(b)
        actions.addStretch()
        root.addLayout(actions)
        self.panel = FoldPanel(self)
        root.addWidget(self.panel)
        from tailor.result_information import ResultInformation, result_plot
        self.information = ResultInformation('拟合结果', self)
        from tailor.result_information import fit_rows
        self.information.provider = lambda language: fit_rows(self.record, language)
        self.overview = QtWidgets.QLabel()
        self.overview.setTextFormat(QtCore.Qt.PlainText)
        self.overview.setWordWrap(True)
        self.overview.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.parameters = QtWidgets.QTableWidget()
        self.parameters.setColumnCount(7)
        self.parameters.setHorizontalHeaderLabels(
            ["参数", "值", "标准误", "单位", "下界", "上界", "固定"]
        )
        self.parameters.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.parameters.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.Stretch
        )
        self.stats = QtWidgets.QLabel()
        self.stats.setTextFormat(QtCore.Qt.PlainText)
        self.stats.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.features = QtWidgets.QLabel()
        self.features.setTextFormat(QtCore.Qt.PlainText)
        self.features.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.residual = result_plot()
        self.residual.setMinimumHeight(220)
        self.residual.setLabel("bottom", "X")
        self.residual.setLabel("left", "Y − 拟合值")
        self.residual_note = QtWidgets.QLabel()
        self.residual_note.setWordWrap(True)
        self.ui.plot_widget = self.residual
        for legacy in (self.overview, self.stats, self.features):
            legacy.setParent(self); legacy.hide()
        self.panel.add_section("结果信息", self.information, True)
        self.panel.add_section("参数详情", self.parameters, True)
        self.panel.add_section("残差", stack(self.residual_note, self.residual), False)
        self.set_record(record)

    def set_record(self, record):
        self.record = record
        self.id = record["id"]
        self.name = record["name"]
        self.refresh_status()
        self.parameters.setRowCount(len(record["parameters"]))
        for row, (name, p) in enumerate(record["parameters"].items()):
            cells = [
                parameter_label(name, record["settings"]["preset"]),
                format_value(p["value"]),
                format_value(p["stderr"]),
                p.get('unit', parameter_unit(record['settings']['preset'], name, record['units'])) or '未指定',
                str(p["min"]),
                str(p["max"]),
                "是" if not p["vary"] else "否",
            ]
            for col, value in enumerate(cells):
                item = QtWidgets.QTableWidgetItem(value)
                item.setToolTip(name)
                self.parameters.setItem(row, col, item)
        self.parameters.setFixedHeight(min(400, 34 + len(record["parameters"]) * 30))
        s = record["statistics"]
        self.stats.setText(
            f"有效点：{s['ndata']:,}    自由参数：{s['nvarys']}    评估次数：{record['nfev']}\n"
            f"R²：{format_value(s['r2'])}    调整 R²：{format_value(s['adjusted_r2'])}\n"
            f"RMSE：{format_value(s['rmse'])}    残差平方和：{format_value(s['sse'])}\n"
            + (
                f"Y 误差加权 χ²：{format_value(record['chisqr'])}    约化 χ²：{format_value(record['redchi'])}"
                if record["settings"]["columns"][3]
                else "未加权最小二乘；R² 与 RMSE 按原始 Y 残差计算"
            )
        )
        units = record["units"]
        lines = []
        for key, value in record["features"].items():
            unit = parameter_unit(record['settings']['preset'], key, units)
            lines.append(f"{parameter_label(key)}：{format_value(value)} {unit}")
        if not lines:
            lines = ["斜率、截距、系数或时间常数见上方参数表。"]
        note = ""
        if record["features"]:
            note = "\n派生特征暂未传播标准误。"
            if any(key.endswith("area") for key in record["features"]):
                note += "峰面积单位为 X 单位 × Y 单位。"
            if "frequency_cycles" in record["features"]:
                note += "频率单位为 1/X 单位。"
        self.features.setText("\n".join(lines) + note)
        self.residual.clear()
        self.residual.plot(
            record["residual_x"],
            record["residual_y"],
            pen=None,
            symbol="o",
            symbolSize=3,
            symbolBrush="#3185d5",
        )
        self.residual.addLine(y=0, pen=pg.mkPen("#999", style=QtCore.Qt.DashLine))
        self.residual_note.setText(
            f"显示 {len(record['residual_x']):,} / {s['ndata']:,} 个残差点（大数据仅抽样显示，统计使用全部点）。"
        )
        self.set_language(self.information.language)

    def set_language(self, language):
        from tailor.result_language import parameter_name, section_language
        self.information.set_language(language)
        english = self.information.language == 'en'
        section_language(self.panel, {'结果信息':'Result information','参数详情':'Parameter details','残差':'Residuals'}, self.information.language)
        self.parameters.setHorizontalHeaderLabels(
            ['Parameter','Value','Standard error','Unit','Lower bound','Upper bound','Fixed'] if english else
            ['参数','值','标准误','单位','下界','上界','固定'])
        for row, (name, parameter) in enumerate(self.record['parameters'].items()):
            self.parameters.item(row,0).setText(parameter_name(name,self.record['settings']['preset']) if english else parameter_label(name,self.record['settings']['preset']))
            unit = parameter.get('unit', parameter_unit(self.record['settings']['preset'],name,self.record['units']))
            self.parameters.item(row,3).setText(unit or ('Not specified' if english else '未指定'))
            self.parameters.item(row,6).setText(('No' if parameter['vary'] else 'Yes') if english else ('否' if parameter['vary'] else '是'))
        actions = {'重新拟合':'Refit','另存为新结果':'Save as new result','定位源表':'Locate source sheet',
                   '定位源图':'Locate source plot','复制结果':'Copy results','参数 CSV…':'Parameters CSV…'}
        for title, button in self.action_buttons.items():
            button.setText(actions[title] if english else title)
        self.residual.setLabel('left','Y − fit' if english else 'Y − 拟合值')
        if english:
            self.residual_note.setText(f"Showing {len(self.record['residual_x']):,} / {self.record['statistics']['ndata']:,} residual points. Large datasets are sampled for display only; statistics use all points.")
        else:
            self.residual_note.setText(f"显示 {len(self.record['residual_x']):,} / {self.record['statistics']['ndata']:,} 个残差点（大数据仅抽样显示，统计使用全部点）。")

    def refresh_status(self):
        r = self.record
        cfg = r["settings"]
        domain = (
            f"{cfg['domain'][0]:.8g} ≤ X ≤ {cfg['domain'][1]:.8g}"
            if cfg["use_domain"]
            else "全部有效数据"
        )
        labels = list(self.data_sheet.model.columnLabels())
        from tailor.column_titles import display
        column = '；'.join(display(self.data_sheet.model, k) for k in record_columns(r) if k in labels) or '结果列已移除'
        self.overview.setText(
            f"{'已过期 · 点击重新拟合更新' if r['stale'] else '拟合完成'}  ·  {r['created']}\n"
            f"来源：{self.data_sheet.name} / {r['x_name']} → {r['y_name']}\n范围：{domain}    输出：{column}\n函数：{r['expression']}"
        )
        from tailor.result_information import fit_rows
        self.information.set_rows(fit_rows(r,self.information.language))

    def locate_sheet(self):
        self.main_window.ui.tabWidget.setCurrentWidget(self.data_sheet)
        labels = list(self.data_sheet.model.columnLabels())
        if self.record["column_id"] in labels:
            # Avoid selecting 500k cells merely to navigate.
            index = self.data_sheet.page_model.index(
                0, labels.index(self.record["column_id"])
            )
            view = self.data_sheet.ui.data_view
            view.setCurrentIndex(index)
            view.scrollTo(index)

    def locate_plot(self):
        from tailor.native_panels import show_document

        show_document(self.main_window, self.plot)
        self.plot.property_tabs.setCurrentIndex(next(i for i in range(self.plot.property_tabs.count()) if self.plot.property_tabs.tabText(i) == '拟合'))

    def refit(self):
        if self.main_window.data_operation_busy():
            self.main_window.statusBar().showMessage("请等待当前后台操作结束")
            return
        restore_settings(self.plot, self.record)
        self.plot.active_fit_id = self.record["id"]
        self.locate_plot()
        self.plot.perform_fit()

    def save_new(self):
        if self.main_window.data_operation_busy():
            return
        # Preserve this historical result; next successful fit creates new output.
        restore_settings(self.plot, self.record)
        self.plot.active_fit_id = None
        self.locate_plot()
        self.plot.perform_fit()

    def copy_result(self):
        if self.information.language == 'en':
            text = '\n'.join(label+': '+str(value) for _,label,value,_ in self.information.rows)
        else:
            text = record_text(self.record)
        QtWidgets.QApplication.clipboard().setText(text)

    def export(self):
        values = {name: p["value"] for name, p in self.record["parameters"].items()}
        values.update(self.record["features"])
        self.plot.preset_controls.write_result_csv(
            {
                "parameter": list(values),
                "value": list(values.values()),
                "unit": [self.record['parameters'].get(k,{}).get('unit',parameter_unit(self.record['settings']['preset'],k,self.record['units'])) for k in values],
                "stderr": [
                    self.record["parameters"].get(k, {}).get("stderr", np.nan)
                    for k in values
                ],
            }
        )


def restore_settings(plot, record):
    from tailor.plot_model import Parameter

    cfg = record["settings"]
    model = plot.model
    model.x_col, model.y_col, model.x_err_col, model.y_err_col = cfg["columns"]
    model.fit_preset_key = cfg["preset"]
    model.update_model_expression(cfg["expression"], use_column_ids=True)
    model._parameters = {
        name: Parameter(name=name, **values) for name, values in cfg["initial"].items()
    }
    model._fit_domain = tuple(cfg["domain"])
    model._use_fit_domain = cfg["use_domain"]
    model.best_fit = None
    plot.preset_controls.sync_model()
    plot.update_model_widget()
    plot.update_fit_domain_from_model()


def parameter_label(name, preset=None):
    prefix = ""
    match = re.fullmatch(r"p(\d+)_(.+)", name)
    if match:
        prefix = "峰" + match[1] + " · "
        name = match[2]
    if name == "amplitude":
        return prefix + (
            "峰面积"
            if preset and ("gaussian" in preset or "lorentzian" in preset)
            else "振幅"
            if preset in {"sine", "damped_sine"}
            else "幅度"
        )
    return prefix + {
        "slope": "斜率",
        "intercept": "截距",
        "amplitude": "幅度／峰面积",
        "sigma": "宽度 σ",
        "center": "峰位",
        "fwhm": "半高全宽 FWHM",
        "height": "峰高",
        "area": "峰面积",
        "frequency": "角频率 ω",
        "frequency_cycles": "频率 f",
        "period": "周期",
        "shift": "相位 φ",
        "decay": "时间常数 τ",
        "origin": "时间原点",
        "offset": "常数基线",
    }.get(name, name)

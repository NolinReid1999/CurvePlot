import copy
import gzip
import importlib.metadata
import json
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6 import QtCore, QtWidgets
import pandas as pd
from packaging.version import Version

from tailor import plot_model
from tailor.curve_style import CurveStyle
from tailor.data_sheet import DataSheet
from tailor.fit_results import FitResultTab, StoredFit, refresh_records
from tailor.legacy_project_files import load_legacy_project
from tailor.multiplot_tab import MultiPlotTab
from tailor.plot_tab import DRAW_CURVE_OPTIONS, PlotTab
from tailor.project_models import (
    MultiPlot,
    MultiPlotInfo,
    Parameter,
    Plot,
    Project,
    Sheet,
)

if TYPE_CHECKING:
    from tailor.app import MainWindow

metadata = importlib.metadata.metadata("tailor")
NAME = metadata["name"]
VERSION = metadata["version"]


def save_project_to_path(project: "MainWindow", path: Path) -> None:
    path = Path(path)
    # Complete serialization and durable temporary write before replacing a valid project.
    text = save_project_to_json(project)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=3) as zipped:
                zipped.write(text.encode("utf-8"))
            raw.flush()
            os.fsync(raw.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_project_from_path(project: "MainWindow", path: Path) -> None:
    with gzip.open(path, mode="rt", encoding="utf-8") as f:
        load_project_from_json(project, f.read())


def save_project_to_json(project: "MainWindow") -> str:
    model = save_project_to_model(project)
    return json.dumps(model.model_dump(), indent=4)


def load_project_from_json(project: "MainWindow", jsondata: str) -> None:
    jsondict = json.loads(jsondata)
    from tailor.single_sheet import migrate_project

    jsondict = migrate_project(jsondict)
    if jsondict.get("schema_version", 1) not in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10):
        raise ValueError("Unsupported CurvePlot project schema version")
    if jsondict["application"] != "tailor":
        raise ValueError("Unrecognized project application")
    if jsondict["application"] == "tailor":
        file_version = Version(jsondict["version"])
        if Version(file_version.base_version) < Version("2.0"):
            model = load_legacy_project(jsondict)
        else:
            model = Project.model_validate(jsondict)
        load_project_from_model(project, model)


def save_project_to_model(project: "MainWindow"):
    return Project(**collect_project_state(project, save_data_sheet))


def capture_project_snapshot(project: "MainWindow"):
    """Copy mutable numeric data on the GUI thread; defer lists/JSON to a worker."""
    state = collect_project_state(project, snapshot_data_sheet)
    state["schema_version"] = 10
    state["plots"] = [plot.model_dump() for plot in state["plots"]]
    state["multiplots"] = [plot.model_dump() for plot in state["multiplots"]]
    return state


def snapshot_data_sheet(sheet):
    data = sheet.model.data_model
    return {
        "name": sheet.name,
        "id": sheet.id,
        "default_sheet": getattr(sheet, "_default_sheet", False),
        "data": {
            label: data._data[label].to_numpy(copy=True) for label in data._data.columns
        },
        "new_col_num": data._new_col_num,
        "col_names": copy.deepcopy(data._col_names),
        "calculated_column_expression": copy.deepcopy(
            data._calculated_column_expression
        ),
        "column_metadata": copy.deepcopy(sheet.model._metadata),
        "excluded": {key: sorted(rows) for key, rows in data._excluded.items()},
    }


def collect_project_state(project, sheet_serializer):
    tabs = [
        project.ui.tabWidget.widget(idx) for idx in range(project.ui.tabWidget.count())
    ]
    sheet_models = []
    plot_models = []
    multiplot_models = []
    tab_order = []
    for tab in tabs:
        if hasattr(tab, "result_kind"):
            tab_order.append(tab.result_kind + "_page")
        elif isinstance(tab, DataSheet):
            sheet_models.append(sheet_serializer(tab))
            tab_order.append(f"sheet_{tab.id}")
        elif isinstance(tab, PlotTab):
            plot = save_plot(tab)
            plot_models.append(plot)
            tab_order.append(f"plot_{plot.id}")
        elif isinstance(tab, FitResultTab):
            tab_order.append(f"fit_{tab.id}")
        elif isinstance(tab, MultiPlotTab):
            multiplot = save_multiplot(tab)
            multiplot_models.append(multiplot)
            tab_order.append(f"multiplot_{multiplot.id}")

    known = {p.id for p in plot_models}
    for source in project.get_plots():
        if source.id not in known:
            plot_models.append(save_plot(source))
            known.add(source.id)
    from tailor.result_pages import snapshot

    return {
        "project_name": getattr(project, "project_name", None),
        "application": NAME,
        "version": VERSION,
        "sheet_num": project._sheet_num,
        "plot_num": project._plot_num,
        "sheets": sheet_models,
        "plots": plot_models,
        "multiplots": multiplot_models,
        "tab_order": tab_order,
        "current_tab": project.ui.tabWidget.currentIndex(),
        "view_state": {
            "windows": project.window_mode.snapshot()
            if hasattr(project, "window_mode")
            else {},
            "results": snapshot(project),
        },
    }


def load_project_from_model(project: "MainWindow", model: Project):
    from tailor.annotation_validation import validate_annotation
    for saved in [*model.plots,*model.multiplots]:
        if len(saved.annotations)>500 or len({r.get('id') for r in saved.annotations})!=len(saved.annotations):
            raise ValueError('标注数量或标识无效')
        for record in saved.annotations:validate_annotation(record)
    # load some application state
    project._sheet_num = model.sheet_num
    project._plot_num = model.plot_num

    # load all data sheets for reference
    data_sheet_by_id: dict[int, DataSheet] = {}
    for sheet_model in model.sheets:
        sheet = load_data_sheet(project, sheet_model)
        data_sheet_by_id[sheet.id] = sheet

    # load plots and add tabs to app
    plot_tab_by_id: dict[int, PlotTab] = {}
    for saved_plot in model.plots:
        sheet = data_sheet_by_id[saved_plot.data_sheet_id]
        plot_tab = load_plot(project=project, model=saved_plot, data_sheet=sheet,
                             hidden_source=f"plot_{saved_plot.id}" not in model.tab_order)
        plot_tab_by_id[plot_tab.id] = plot_tab

    # load multiplots and add tabs to app
    multiplot_tab_by_id: dict[int, MultiPlotTab] = {}
    for multiplot_model in model.multiplots:
        multiplot_tab = load_multiplot(
            project=project, model=multiplot_model, plots=plot_tab_by_id
        )
        multiplot_tab_by_id[multiplot_tab.id] = multiplot_tab

    from tailor.result_pages import page, refresh_processing, restore_order

    # Restore source documents before notebooks and native panel adapters.
    # restore tabs in order
    for id_string in model.tab_order:
        if id_string in {"fit_page", "processing_page"} or id_string.startswith("fit_"):
            continue
        type_, id = id_string.split("_")
        id = int(id)
        if type_ == "sheet":
            tab = data_sheet_by_id[id]
        elif type_ == "plot":
            tab = plot_tab_by_id[id]
        elif type_ == "multiplot":
            tab = multiplot_tab_by_id[id]
        else:
            raise ValueError(f"Unknown document type: {type_}")
        project.ui.tabWidget.addTab(tab, tab.name)
    for plot in plot_tab_by_id.values():
        view = getattr(plot, "advanced_view", None)
        if view is not None:
            view.render()
    from tailor.fit_results import show_result

    for plot in project.get_plots():
        for record in plot.fit_records:
            show_result(plot, record, focus=False)
    refresh_processing(project)
    # One aggregate tab replaces legacy individual result tabs, preserving the
    # first occurrence's position. Missing optional notebooks are ignored.
    order = []
    for token in model.tab_order:
        token = "fit_page" if token.startswith("fit_") else token
        if token not in order:
            order.append(token)
    bar = project.ui.tabWidget.tabBar()
    for target, token in enumerate(order):
        if token.endswith("_page"):
            widget = page(project, token.split("_")[0], False)
        else:
            kind, identifier = token.split("_")
            widget = {
                "sheet": data_sheet_by_id,
                "plot": plot_tab_by_id,
                "multiplot": multiplot_tab_by_id,
            }[kind].get(int(identifier))
        index = project.ui.tabWidget.indexOf(widget) if widget else -1
        if index >= 0:
            bar.moveTab(index, min(target, bar.count() - 1))
    restore_order(project, model.view_state.get("results", {}))
    project.ui.tabWidget.setCurrentIndex(model.current_tab)
    if hasattr(project, "window_mode"):
        project.window_mode.restore(model.view_state.get("windows", {}))
    if getattr(project,'_defer_project_restore',False):
        documents=[*multiplot_tab_by_id.values(),*plot_tab_by_id.values()]
        pending=[doc for doc in documents if getattr(doc,'_inspector_initializing',False)]
        current=project.ui.tabWidget.currentWidget()
        if current in pending:pending.remove(current);pending.insert(0,current)
        if pending:
            from tailor.curve_documents import stage_inspectors
            stage_inspectors(pending[0],pending[1:],message="工程已载入，正在准备编辑控件…")
    project._loaded_project_name = model.project_name
    if model.project_name and hasattr(project, "project_name"):
        project.project_name = model.project_name
        if hasattr(project,"tab_controls"):
            project.tab_controls.refresh_project_name()


def save_data_sheet(data_sheet: DataSheet) -> Sheet:
    data_model = data_sheet.model.data_model
    return Sheet(
        name=data_sheet.name,
        id=data_sheet.id,
        default_sheet=getattr(data_sheet, "_default_sheet", False),
        data=data_model._data.to_dict(orient="list"),
        new_col_num=data_model._new_col_num,
        col_names=data_model._col_names,
        calculated_column_expression=data_model._calculated_column_expression,
        column_metadata=data_sheet.model._metadata,
        excluded={key: sorted(rows) for key, rows in data_model._excluded.items()},
    )


def load_data_sheet(app: "MainWindow", model: Sheet) -> DataSheet:
    data_sheet = getattr(app, '_restore_reusable_sheet', None)
    if data_sheet is None:
        data_sheet = DataSheet(name=model.name, id=model.id, main_window=app)
    else:
        app._restore_reusable_sheet = None
        data_sheet.name, data_sheet.id = model.name, model.id
        data_sheet._initial_placeholder = False
    if hasattr(app,"_restore_created"):app._restore_created.append(data_sheet)
    data_sheet._default_sheet = model.default_sheet
    data_sheet.model.beginResetModel()
    data = data_sheet.model.data_model
    data._data = pd.DataFrame.from_dict(model.data)
    data._new_col_num = model.new_col_num
    data._col_names = model.col_names
    data._calculated_column_expression = model.calculated_column_expression
    data._excluded = {
        key: set(rows)
        for key, rows in model.excluded.items()
        if key in data._data.columns
    }
    data_sheet.model._metadata = model.column_metadata
    data_sheet.model.clear_history()
    data_sheet.model.data_model.recalculate_all_columns()
    data_sheet.model.endResetModel()
    # force updating column information in UI
    data_sheet.selection_changed()
    return data_sheet


def save_plot(plot: PlotTab):
    if hasattr(plot, "extras"):
        plot.extras.snapshot()
    view = getattr(plot, "advanced_view", None)
    if view and view.native:
        view.native.snapshot()
    parameters = [
        Parameter(name=p.name, value=p.value, min=p.min, max=p.max, vary=p.vary)
        for p in plot.model._parameters.values()
    ]
    refresh_records(plot, check_data=True)
    plot.model.verify_best_fit_data()
    best_fit = plot.model.best_fit is not None
    return Plot(
        name=plot.name,
        id=plot.id,
        data_sheet_id=plot.data_sheet.id,
        x_col=plot.model.x_col,
        y_col=plot.model.y_col,
        x_err_col=plot.model.x_err_col,
        y_err_col=plot.model.y_err_col,
        x_label=plot.model.x_label,
        y_label=plot.model.y_label,
        x_min=plot.model.x_min,
        x_max=plot.model.x_max,
        y_min=plot.model.y_min,
        y_max=plot.model.y_max,
        modelexpression=plot.model._model_expression,
        parameters=parameters,
        fit_domain=plot.model._fit_domain,
        use_fit_domain=plot.model._use_fit_domain,
        best_fit=best_fit,
        show_initial_fit=plot.ui.show_initial_fit.isChecked(),
        draw_curve_option=plot.get_draw_curve_option(),
        curve_style=plot.curve_style.to_dict(),
        fit_preset_key=plot.model.fit_preset_key,
        legend_label=plot.model.legend_label,
        legend_visible=plot.model.legend_visible,
        fit_records=copy.deepcopy(plot.fit_records),
        active_fit_id=plot.active_fit_id,
        graph_settings=plot.presentation.to_dict(),
        annotations=copy.deepcopy(plot.annotations.records),
    )


def hold_restoring_inspector(doc):
    # Thousands of controls are attached in batches. Avoid recalculating the
    # same hidden stack geometry after each insertion; restore it once when
    # the complete inspector is ready. Graph viewport/layout remains live.
    doc._restore_layouts=[]
    for widget in (doc.property_tabs, doc._preference_container):
        layout=widget.layout()
        doc._restore_layouts.append((widget,widget.updatesEnabled(),layout,layout.isEnabled() if layout else False))
        widget.setUpdatesEnabled(False)
        if layout:layout.setEnabled(False)
    for i in range(doc.property_tabs.count()):
        page=doc.property_tabs.widget(i)
        content=page.widget() if isinstance(page,QtWidgets.QScrollArea) else page
        if content is not None:content.hide()
    host=doc._preference_container
    placeholder=QtWidgets.QWidget(host)
    doc._restore_placeholder=placeholder
    host.addWidget(placeholder);host.setCurrentWidget(placeholder)


def release_restoring_inspector(doc):
    placeholder=getattr(doc,'_restore_placeholder',None)
    if placeholder is not None:
        host=doc._preference_container
        host.setCurrentWidget(doc.property_tabs)
        host.removeWidget(placeholder);placeholder.deleteLater()
        del doc._restore_placeholder
    for widget,updates,layout,enabled in getattr(doc,'_restore_layouts',[]):
        if layout:
            layout.setEnabled(enabled)
            if enabled:layout.invalidate();layout.activate()
        widget.setUpdatesEnabled(updates)
    if hasattr(doc,'_restore_layouts'):del doc._restore_layouts


def load_plot(project: "MainWindow", model: Plot, data_sheet: DataSheet, *, hidden_source=False) -> PlotTab:
    deferred=bool(getattr(project,"_defer_project_restore",False))
    plot_tab = PlotTab(
        main_window=project,
        name=model.name,
        id=model.id,
        data_sheet=data_sheet,
        x_col=model.x_col,
        y_col=model.y_col,
        x_err_col=model.x_err_col,
        y_err_col=model.y_err_col,
        defer_inspector=deferred,
        initial_style=CurveStyle(**model.curve_style),
        hidden_source=hidden_source,
    )
    if hasattr(project,"_restore_created"):project._restore_created.append(plot_tab)
    if deferred:
        plot_tab._inspector_timer.stop()
        hold_restoring_inspector(plot_tab)
    plot_tab._project_restore_pending=deferred
    # Restoring controls is not an edit: avoid their connected redraw/model slots.
    blockers=[QtCore.QSignalBlocker(w) for w in (
        plot_tab.ui.show_initial_fit,plot_tab.ui.draw_curve_option)]
    plot_tab.model.legend_label = model.legend_label
    plot_tab.model.legend_visible = model.legend_visible
    plot_tab.model.x_label = model.x_label
    plot_tab.model.y_label = model.y_label
    plot_tab.model.x_min = model.x_min
    plot_tab.model.x_max = model.x_max
    plot_tab.model.y_min = model.y_min
    plot_tab.model.y_max = model.y_max
    from tailor.fit_presets import get_preset

    try:
        get_preset(model.fit_preset_key)
        plot_tab.model.fit_preset_key = model.fit_preset_key
    except (ValueError, TypeError):
        plot_tab.model.fit_preset_key = None
    plot_tab.model.update_model_expression(model.modelexpression, use_column_ids=True)
    for parameter in model.parameters:
        plot_tab.model._parameters[parameter.name] = plot_model.Parameter(
            **parameter.model_dump()
        )
    plot_tab.model._fit_domain = model.fit_domain
    plot_tab.model._use_fit_domain = model.use_fit_domain
    plot_tab.fit_records = copy.deepcopy(model.fit_records)
    plot_tab.active_fit_id = model.active_fit_id
    refresh_records(plot_tab, check_data=True)
    active = next(
        (r for r in plot_tab.fit_records if r["id"] == model.active_fit_id), None
    )
    if model.best_fit and active and not active["stale"]:
        plot_tab.model.best_fit = StoredFit(active, plot_tab.model)
        plot_tab.model._fit_data_checksum = plot_tab.model.hash_data(
            plot_tab.model.get_data_in_fit_domain()
        )
    elif model.best_fit and not active:
        project.statusBar().showMessage(
            "旧工程的源数据与模型已恢复；旧格式未保存完整拟合结果，请手动重新拟合。"
        )
    plot_tab.ui.show_initial_fit.setChecked(model.show_initial_fit)
    option_idx = list(DRAW_CURVE_OPTIONS.keys()).index(model.draw_curve_option)
    plot_tab.ui.draw_curve_option.setCurrentIndex(option_idx)
    if model.graph_settings.get("extra_settings",{}).get("advanced"):plot_tab.ui.plot_widget.hide()
    plot_tab.presentation.load(model.graph_settings)
    plot_tab.presentation.extra_settings.setdefault('derived_default_width', 5.0)
    plot_tab.presentation.legend["visible"] = model.legend_visible
    plot_tab._clear_remembered_zoom()
    plot_tab.apply_curve_style(CurveStyle(**model.curve_style), dirty=False)
    del blockers
    def finish():
        plot_tab._project_restore_pending=False
        if hasattr(plot_tab,'legend_name_edit'):
            with QtCore.QSignalBlocker(plot_tab.legend_name_edit),QtCore.QSignalBlocker(plot_tab.legend_toggle):
                plot_tab.legend_name_edit.setText(model.legend_label)
                plot_tab.legend_toggle.setChecked(model.legend_visible)
        if hasattr(plot_tab,'axis_controls'):plot_tab.axis_controls.sync()
        if hasattr(plot_tab,'legend_controls'):plot_tab.legend_controls.sync()
        plot_tab.error_controls.sync()
        plot_tab.preset_controls.sync_model()
        plot_tab.annotations.load(model.annotations)
        advanced=plot_tab.presentation.extra_settings.get('advanced')
        if advanced and not hidden_source:
            from tailor.advanced_plotting import install_view
            install_view(plot_tab,advanced,deferred=True,restoring=True)
        plot_tab.presentation.apply_axes()
        plot_tab.refresh_ui()
        release_restoring_inspector(plot_tab)
        for host in getattr(plot_tab,'_restore_hosts',[]):
            if hasattr(host,'fit_router'):host.fit_router.refresh()
    if deferred:plot_tab.inspector_ready.connect(finish)
    else:finish()
    plot_tab._source_changed = True
    plot_tab.refresh_ui()
    plot_tab.presentation.apply_axes()
    return plot_tab


def save_multiplot(plot: MultiPlotTab) -> MultiPlot:
    plot_info = [
        MultiPlotInfo(
            plot_id=p.id,
            label=i.label,
            color=i.color,
            axis=i.axis,
            x_axis=i.x_axis,
            visible=i.visible,
            style=copy.deepcopy(i.style),
            errors=copy.deepcopy(i.errors),
        )
        for p, i in plot.model._plots.items()
    ]
    return MultiPlot(
        name=plot.name,
        id=plot.id,
        x_label=plot.model.x_label,
        y_label=plot.model.y_label,
        x_min=plot.model.x_min,
        x_max=plot.model.x_max,
        y_min=plot.model.y_min,
        y_max=plot.model.y_max,
        plots=plot_info,
        graph_settings=plot.presentation.to_dict(),
        annotations=copy.deepcopy(plot.annotations.records),
        curve_style=plot.curve_style.to_dict(),
    )


def load_multiplot(
    project: "MainWindow", model: MultiPlot, plots: dict[int, PlotTab]
) -> MultiPlotTab:
    deferred=bool(getattr(project,"_defer_project_restore",False))
    multiplot_tab = MultiPlotTab(
        main_window=project,
        name=model.name,
        id=model.id,
        x_label=model.x_label,
        y_label=model.y_label,
        defer_inspector=deferred,
    )
    if hasattr(project,"_restore_created"):project._restore_created.append(multiplot_tab)
    if deferred:
        multiplot_tab._inspector_timer.stop()
        hold_restoring_inspector(multiplot_tab)
    multiplot_tab._project_restore_pending=deferred
    multiplot_tab.model.x_min = model.x_min
    multiplot_tab.model.x_max = model.x_max
    multiplot_tab.model.y_min = model.y_min
    multiplot_tab.model.y_max = model.y_max
    multiplot_tab.curve_style = CurveStyle(**model.curve_style)
    for plot_info in model.plots:
        plot = plots[plot_info.plot_id]
        multiplot_tab.model.add_plot(
            plot=plot, label=plot_info.label, color=plot_info.color
        )
        plot._restore_hosts=getattr(plot,'_restore_hosts',[])+[multiplot_tab]
        if getattr(plot,'_hidden_curve_source',False):plot._fit_host=multiplot_tab
        info = multiplot_tab.model.get_plot_info(plot)
        if plot_info.axis not in {"left", "right"}:
            raise ValueError("Unknown curve axis")
        if plot_info.x_axis not in {"bottom", "top"}:
            raise ValueError("Unknown curve X axis")
        info.x_axis = plot_info.x_axis
        info.axis, info.visible = plot_info.axis, plot_info.visible
        info.style = CurveStyle(**plot_info.style).to_dict() if plot_info.style else {}
        info.errors.update(plot_info.errors)
        multiplot_tab.presentation.validate_errors(info.errors)
    # Insets reuse the source documents, so restore them only after their
    # source identities and per-series styles have been restored.
    if model.graph_settings.get("extra_settings",{}).get("advanced"):multiplot_tab.ui.plot_widget.hide()
    multiplot_tab.presentation.load(model.graph_settings)
    multiplot_tab.presentation.extra_settings.setdefault('derived_default_width', 5.0)
    def finish():
        multiplot_tab._project_restore_pending=False
        multiplot_tab.curve_manager.refresh()
        multiplot_tab.axis_controls.sync()
        multiplot_tab.legend_controls.sync()
        multiplot_tab.annotations.load(model.annotations)
        advanced=multiplot_tab.presentation.extra_settings.get('advanced')
        if advanced:
            from tailor.advanced_plotting import install_view
            install_view(multiplot_tab,advanced,deferred=True,restoring=True)
        multiplot_tab.draw_plot()
        release_restoring_inspector(multiplot_tab)
    if deferred:multiplot_tab.inspector_ready.connect(finish)
    else:finish()
    # Per-series style/axis assignment must reach the very first frame.
    multiplot_tab.draw_plot()
    return multiplot_tab

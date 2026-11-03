"""Opt-in small installed-bundle closure; isolated startup-check preferences only."""

import numpy as np
from PySide6 import QtWidgets


def run_core(window, directory):
    """Opt-in release check using the same public GUI/model entry points."""
    import copy
    import hashlib
    from PySide6 import QtCore, QtTest
    from tailor import project_files
    from tailor.csv_format_dialog import FormatParameters

    def wait(predicate):
        deadline = QtCore.QDeadlineTimer(45000)
        while not predicate() and not deadline.hasExpired():
            QtTest.QTest.qWait(10)
        assert predicate(), 'Core release workflow did not finish'

    window.projects.host.resize(1400, 900)
    x = np.linspace(0, 10, 101)
    raw = np.column_stack((x, 3*x+2, 2*x+5))
    csv = directory / 'core.csv'
    np.savetxt(csv, raw, delimiter=',', header='time,signal1,signal2', comments='', fmt='%.15g')
    digest = hashlib.sha256(csv.read_bytes()).hexdigest()
    window.start_csv_import(str(csv), FormatParameters())
    wait(lambda: not window.csv_import_busy())
    sheet = window.get_data_sheets()[0]
    np.testing.assert_allclose(sheet.model.data_model._data.to_numpy(), raw, atol=1e-12)
    picker = sheet.plot_type_picker
    picker.choose('line')
    picker.draw_button.click()
    wait(lambda: not window.graph_initialization_busy())
    single = window.ui.tabWidget.currentWidget()
    assert single.curve_style.mode == 'line' and not single.presentation.multi
    window.ui.tabWidget.setCurrentWidget(sheet)
    picker.add_column('Y', 2)
    picker.draw_button.click()
    wait(lambda: not window.graph_initialization_busy())
    graph = window.ui.tabWidget.currentWidget()
    assert graph.presentation.multi and len(graph.model._plots) == 2
    import pyqtgraph as pg
    assert len({pg.mkPen(item['data'].opts['pen']).color().name()
                for item in graph._series.values()}) == 2
    source = next(iter(graph.model._plots))
    source.preset_controls.choose('linear')
    source.ui.fit_button.click()
    wait(lambda: source._fit_job is None)
    assert source.model.best_fit.success and len(source.fit_records) == 1
    np.testing.assert_allclose(source.model.best_fit.best_fit, 3*x+2, atol=1e-7)
    graph.draw_plot()
    assert len(graph.presentation.legend_item.items) == 3
    c = graph.axis_controls
    c.select_axis('x')
    graph.ui.plot_widget.setXRange(0, 10, padding=0)
    c.custom_interval.click()
    c.major.setText('3'); c.major.editingFinished.emit()
    assert graph.ui.plot_widget.getAxis('bottom').tickValues(0, 10, 600)[0][1] == [0, 3, 6, 9]
    c.custom_interval.click()
    c.tick_pair.sources[0].setValue(7)
    assert graph.presentation.axes['x']['major_count'] == 11
    for suffix in ('svg', 'pdf', 'png'):
        graph.export_graph(directory / ('core.' + suffix))
        assert (directory / ('core.' + suffix)).stat().st_size > 100
    path = directory / 'core.cur'
    project_files.save_project_to_path(window, path)
    snapshot = sheet.model.data_model._data.copy(deep=True)
    ids = list(sheet.model.columnLabels())
    styles = [copy.deepcopy(graph.model.get_plot_info(s).style) for s in graph.model._plots]
    opened = window.open_project_dialog(filename=path)
    wait(lambda: not opened.graph_initialization_busy())
    assert opened is not window and window in window.projects.windows
    loaded = next(opened.ui.tabWidget.widget(i) for i in range(opened.ui.tabWidget.count())
                  if getattr(getattr(opened.ui.tabWidget.widget(i), 'presentation', None), 'multi', False))
    assert [loaded.model.get_plot_info(s).style for s in loaded.model._plots] == styles
    assert sum(len(s.fit_records) for s in loaded.model._plots) == 1
    assert opened.get_data_sheets()[0].model.data_model._data.equals(snapshot)
    assert list(opened.get_data_sheets()[0].model.columnLabels()) == ids
    assert loaded.presentation.axes['x']['major_count'] == 11
    second = directory / 'second.cur'
    second.write_bytes(path.read_bytes())
    another = opened.open_project_dialog(filename=second)
    wait(lambda: not another.graph_initialization_busy())
    assert len(window.projects.windows) == 3
    assert window.open_project_dialog(filename=path) is opened
    first_model = opened.get_data_sheets()[0].model
    first_model.setData(first_model.index(0, 1), '777')
    assert another.get_data_sheets()[0].model.data_model._data.equals(snapshot)
    assert sheet.model.data_model._data.equals(snapshot)
    first_model.undo()
    assert first_model.data_model._data.equals(snapshot)
    np.testing.assert_allclose(snapshot.iloc[:, :3].to_numpy(), raw, atol=1e-12)
    assert hashlib.sha256(csv.read_bytes()).hexdigest() == digest
    for project in window.projects.windows:
        for internal in project.get_plots():
            if getattr(internal, '_hidden_curve_source', False):
                assert not internal.isVisible(), 'Internal source plot overlaps the project'
    active = window.projects.active
    bar = active.ui.tabWidget.tabBar()
    point = window.projects.host.mapFromGlobal(bar.mapToGlobal(bar.tabRect(0).center()))
    target = window.projects.host.childAt(point)
    assert target is bar or (target is not None and bar.isAncestorOf(target)), 'Document tabs are obstructed'
    window.projects.host.grab().save(str(directory / 'core-window.png'))
    return {'passed': True, 'sourceRows': 101, 'originalColumns': 3,
            'csvSingleMultiFit': True, 'legendDistinctColors': True,
            'tickCustomAndReachableCount': True, 'svgPdfPng': True,
            'editableProjectRoundtrip': True, 'independentProjectsAndUndo': True,
            'internalSourcesHiddenAndTabsUnobstructed': True}


def run(window, directory):
    from tailor import project_files
    from tailor.canvas_export import export_canvas
    from tailor.column_analysis import analyze

    # Use the same documented native-window size as source visual checks.
    # This affects only the opt-in isolated check, never user preferences.
    window.projects.host.resize(1400, 900)
    sheet = window.get_data_sheets()[0]
    model = sheet.model
    xkey, ykey = list(model.columnLabels())
    x = np.linspace(0, 10, 201)
    y = 0.2 + sum(np.exp(-0.5 * ((x - c) / 0.3) ** 2) for c in (2, 5, 8))
    y += np.random.default_rng(25).normal(0, 0.005, len(x))
    raw = np.column_stack((x, y))
    model.setDataFromArray(model.index(0, 0), raw)
    model.set_column_metadata(0, role="X")
    model.set_column_metadata(1, role="Y")
    plot = window.create_plot_tab(sheet, xkey, ykey)
    plot.preset_controls.choose("multi_gaussian_3")
    plot.model.perform_fit()
    assert plot.model.best_fit is not None
    np.testing.assert_allclose(
        [plot.model.best_fit.params[f"p{i}_center"].value for i in (1, 2, 3)],
        [2, 5, 8],
        atol=0.01,
    )
    np.testing.assert_allclose(analyze(x, x * x, "derivative")["y"], 2 * x, atol=1e-10)
    signal = np.sin(2 * np.pi * np.arange(1000) / 20)
    assert (
        abs(analyze(np.arange(1000) / 1000, signal, "fft_amplitude")["y"][50] - 1)
        < 1e-10
    )
    assert np.isfinite(analyze(x, y, "lowpass", {"cutoff": 2})["y"]).all()
    assert (
        len(
            analyze(x, y, "interpolate", {"points": 301, "interpolation": "pchip"})["y"]
        )
        == 301
    )
    assert len(analyze(x, y, "statistics")["metrics"]) == 10
    added = model.append_results(
        [
            {
                "name": "导数",
                "values": analyze(x, y, "derivative")["y"],
                "comment": "微分",
            }
        ],
        "基础数学",
    )
    assert len(added) == 1
    np.testing.assert_array_equal(model.data_model._data.iloc[:, :2].to_numpy(), raw)
    model.undo()
    assert model.columnCount() == 2
    window.ui.tabWidget.setCurrentWidget(plot)
    for _ in range(8):
        QtWidgets.QApplication.processEvents()
    from tailor.fit_results import publish_result
    fit_record = publish_result(plot, plot.model.best_fit)
    bands = plot.extras.bands
    bands.refresh()
    band_key = f'{plot.id}:{fit_record["id"]}'
    bands.choice.setCurrentIndex(bands.choice.findData(band_key))
    bands.choose(bands.choice.currentIndex())
    for kind in ("confidence", "prediction"):
        plot.extras.band_controls[kind][0].setChecked(True)
        plot.extras.update_band(kind)
        assert len(plot.extras.band_items[(band_key, kind)]) == 3
    plot.extras.collection.add_entry()
    plot.extras.collection.add_entry()
    assert len(plot.extras.collection.live()) == 2
    for _ in range(8):
        QtWidgets.QApplication.processEvents()
    export_canvas(plot, directory / "analysis.svg", 150)
    project_files.save_project_to_path(window, directory / "analysis.cur")
    # The explicit band target now owns real fit output columns; verify the
    # original two source columns independently of these generated outputs.
    np.testing.assert_array_equal(model.data_model._data.iloc[:, :2].to_numpy(), raw)
    from PySide6 import QtCore, QtTest

    from tailor.analysis_records import records, rerun, stale
    from tailor.exclusions import set_cells

    set_cells(model, {ykey: [10]}, True)
    assert len(plot.model.get_data_in_fit_domain()[0]) == 200
    set_cells(model, {ykey: [10]}, False)
    env = analyze(x, y, "envelope_sliding", {"window": 11})
    assert set(env["series"]) == {"上包络", "下包络"}
    control = sheet.processing_controls
    control.targets = [(sheet.id, ykey)]
    control.launch("statistics", {"statistics": ["mean"]}, True, "描述统计")
    deadline = QtCore.QDeadlineTimer(10000)
    while control.job is not None and not deadline.hasExpired():
        QtTest.QTest.qWait(5)
    assert control.job is None
    record = records(window)[0]
    assert not stale(window, record)
    assert rerun(control, record)
    while control.job is not None and not deadline.hasExpired():
        QtTest.QTest.qWait(5)
    assert control.job is None and not stale(window, records(window)[0])
    advanced = sheet.advanced_controls
    second = model.append_results([{"name": "第二曲线", "values": y * 1.5}])[0]
    advanced.refs = [(sheet.id, ykey), (sheet.id, second)]
    for kind in ("bar", "panels"):
        window.ui.tabWidget.setCurrentWidget(sheet)
        advanced.kind.setCurrentIndex(advanced.kind.findData(kind))
        advanced.create()
        graph = window.ui.tabWidget.currentWidget()
        graph.advanced_view.render()
        assert graph.advanced_view.last_error is None
        graph.export_graph(directory / (kind + ".svg"), 120)
    xyz = sheet
    a, b = np.meshgrid(np.linspace(-1, 1, 5), np.linspace(-1, 1, 5))
    xyzkeys = model.append_results([{"name":"XYZ-X","values":a.ravel()},{"name":"XYZ-Y","values":b.ravel()},{"name":"XYZ-Z","values":(a*a+b*b).ravel()}])
    model.set_column_metadata(list(model.columnLabels()).index(xyzkeys[0]),role="X")
    zctrl = xyz.advanced_controls
    zctrl.kind.setCurrentIndex(zctrl.kind.findData("3d"))
    zctrl.fill_xyz()
    from tailor.ui_widgets import data_index
    for box, key in zip(zctrl.xyz, xyzkeys):
        box.setCurrentIndex(data_index(box,(xyz.id,key)))
    zctrl.create()
    three = window.ui.tabWidget.currentWidget()
    three.advanced_view.render()
    assert three.advanced_view.last_error is None
    three.export_graph(directory / "three-d.pdf", 120)
    assert window.manual_path().exists()
    from tailor.fit_results import publish_result
    from tailor.result_pages import page

    # One result already exists for the band checks. Each unselected new
    # execution appends a result; selecting a displayed result is not refitting.
    initial_ids = {r['id'] for r in plot.fit_records}
    assert len(initial_ids) == 1
    plot.model.perform_fit()
    next_fit = publish_result(plot, plot.model.best_fit)
    plot.active_fit_id = None
    last_fit = publish_result(plot, plot.model.best_fit)
    expected_ids = initial_ids | {next_fit['id'], last_fit['id']}
    assert len(expected_ids) == 3
    assert {r['id'] for r in plot.fit_records} == expected_ids
    assert page(window, "fit").tabs.count() == 3
    from tailor.result_pages import refresh_processing

    refresh_processing(window)
    assert page(window, "processing").tabs.count() == 1
    group = next(
        g
        for g in window.get_plots()
        if getattr(g, "advanced_view", None) and g.advanced_view.cfg["kind"] == "panels"
    )
    titles = {}
    native = group.advanced_view.native
    for i, (key, doc) in enumerate(native.panels.items(), 1):
        native.activate(key)
        for axis in ("x", "y", "top", "right"):
            control = doc.axis_controls
            control.select_axis(axis, "label")
            before = getattr(control.holder(axis), axis + "_label")
            text = f"Panel {i} {axis}"
            control.text_editor.content.setPlainText(text)
            control.apply_text()
            model.undo()
            assert getattr(control.holder(axis), axis + "_label") == before
            model.redo()
            assert getattr(control.holder(axis), axis + "_label") == text
            titles[(key, axis)] = text
    window.ui.tabWidget.setCurrentWidget(plot)
    window.window_mode.toggle(True)
    ordinary = window.create_plot_tab(sheet,xkey,ykey)
    assert ordinary is not None
    window.ui.tabWidget.setCurrentWidget(ordinary)
    deadline = QtCore.QDeadlineTimer(45000)
    while ordinary not in window.window_mode.windows and not deadline.hasExpired():
        QtTest.QTest.qWait(10)
    assert ordinary in window.window_mode.windows, "New graph window was not prepared"
    window.window_mode.dock(window.window_mode.windows[plot], "L")
    window.window_mode.dock(window.window_mode.windows[ordinary], "R")
    assert group not in window.window_mode.windows
    for _ in range(8):
        QtWidgets.QApplication.processEvents()
    window.projects.host.grab().save(str(directory / "windows-installed.png"))
    project_files.save_project_to_path(window, directory / "analysis.cur")
    restored = type(window)()
    assert restored.load_project(directory / "analysis.cur")
    restored.projects.activate(restored)
    deadline = QtCore.QDeadlineTimer(45000)
    while restored.graph_initialization_busy() and not deadline.hasExpired():
        QtTest.QTest.qWait(10)
    assert not restored.graph_initialization_busy(), "Restored editors did not finish preparing"
    assert len(restored.window_mode.windows) == 2
    assert page(restored, "fit").tabs.count() == 3
    restored_source = next(g for g in restored.get_plots() if g.id == plot.id)
    assert {r['id'] for r in restored_source.fit_records} == expected_ids
    assert max(len(g.extras.collection.live()) for g in restored.get_plots()) == 2
    assert page(restored, "processing").tabs.count() == 1
    loaded_graph = next(
        g
        for g in restored.get_plots()
        if getattr(g, "advanced_view", None) and g.advanced_view.cfg["kind"] == "panels"
    )
    # Advanced graphs are intentionally excluded from window mode. They render
    # lazily when opened, so activate the saved graph before checking its axes.
    restored.window_mode.toggle(False)
    restored.ui.tabWidget.setCurrentWidget(loaded_graph)
    loaded = loaded_graph.advanced_view
    loaded.schedule()
    until = QtCore.QDeadlineTimer(15000)
    while (loaded.native is None or loaded.native.initializing) and not until.hasExpired():
        QtTest.QTest.qWait(20)
    assert loaded.native is not None, loaded.last_error if hasattr(loaded,"last_error") else "not rendered"
    assert not loaded.native.initializing, "Restored panels did not finish preparing"
    loaded = loaded.native
    for key, doc in loaded.panels.items():
        for axis in ("x", "y", "top", "right"):
            assert (
                getattr(doc.axis_controls.holder(axis), axis + "_label")
                == titles[(key, axis)]
            )
    np.testing.assert_array_equal(model.data_model._data.iloc[:, :2].to_numpy(), raw)
    return {
        "passed": True,
        "envelopeMasksRecompute": True,
        "barsPanelsThreeDExports": True,
        "bundledManual": True,
        "sourceRows": 201,
        "multiPeakFit": True,
        "statisticsMathFFTFilter": True,
        "sameSheetUndo": True,
        "bandsInsetExport": True,
        "twoInsetsSaveRestore": True,
        "advancedExcludedFromWindows": True,
        "projectSave": True,
        "windowModeDockRestore": True,
        "aggregateResultPages": True,
        "nativePanelInspectors": True,
        "eightIndependentAxisTitlesUndoRestore": True,
    }

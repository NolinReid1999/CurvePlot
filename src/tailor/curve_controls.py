"""One properties panel for graph appearance and fitting, using existing widgets."""

from tailor.compact_controls import CheckButton

from dataclasses import replace

import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from tailor.line_styles import LINE_STYLES
from tailor.plot_types import MODE_ITEMS
from tailor.ui_widgets import (
    ColorButton,
    FontFamilyCombo,
    InspectorTabs,
    arrange_axis_fields,
)


def apply_style(plot, style, dirty=True):
    previous = plot.curve_style
    plot.curve_style = style
    from tailor.appearance import ink
    from tailor.line_styles import curve_pen

    pen = (
        None
        if style.mode == "scatter"
        else curve_pen(style.color, style.line_width, style.line_style)
    )
    plot.plot.setVisible(style.visible and not getattr(plot,'_advanced_bar',False))
    plot.plot.setPen(pen)
    plot.plot.setSymbol(
        style.marker if style.mode in {"scatter", "line_scatter"} else None
    )
    plot.plot.setSymbolSize(style.marker_size)
    plot.plot.setSymbolPen(ink(style.color))
    plot.plot.setSymbolBrush(ink(style.color))
    from tailor.line_styles import apply_curve_extras

    if getattr(plot,'_advanced_bar',False):
        from dataclasses import replace
        apply_curve_extras(plot.plot, replace(style,mode='line',fill=False,step_mode=False))
    else:
        apply_curve_extras(plot.plot, style)
    plot.error_bars.setData(pen=pg.mkPen(ink(style.color), width=style.line_width))
    if hasattr(plot, "error_items"):
        visible = style.visible and not getattr(plot,'_advanced_bar',False)
        plot.error_items.x.setVisible(visible)
        plot.error_items.y.setVisible(visible)
    from tailor.text_style_controls import (
        apply_text_styles,
        record_view_edit,
        sync_font_controls,
    )

    apply_text_styles(plot)
    if hasattr(plot, "style_mode"):
        controls = (
            plot.style_mode,
            plot.style_line,
            plot.style_width,
            plot.style_marker,
            plot.style_shape,
            plot.style_font,
            plot.style_family,
            plot.style_transparent,
        )
        blockers = [QtCore.QSignalBlocker(control) for control in controls]
        plot.style_mode.setCurrentIndex(
            [key for _, key in MODE_ITEMS].index(style.mode)
        )
        plot.style_line.setCurrentIndex(
            [key for _, key in LINE_STYLES].index(style.line_style)
        )
        plot.style_width.setValue(style.line_width)
        plot.style_shape.setCurrentIndex(plot.style_shape.findData(style.marker))
        plot.style_shape.setEnabled(style.mode != "line")
        plot.style_marker.setValue(style.marker_size)
        sync_font_controls(plot)
        plot.style_transparent.setChecked(style.transparent)
        plot.style_color.setText(style.color)
        plot.style_width.setEnabled(style.mode != "scatter")
        plot.style_line.setEnabled(style.mode != "scatter")
        plot.style_marker.setEnabled(style.mode != "line")
        del blockers
    if hasattr(plot, "error_items") and previous.color != style.color:
        plot.update_error_items()
    if hasattr(plot, "curve_selection"):
        plot.curve_selection.refresh()
    if hasattr(plot, "presentation"):
        plot.refresh_legend()
        if previous.mode != style.mode:
            plot.update_plot()
    if hasattr(plot, "extras"):
        plot.extras.refresh()
    if dirty:
        record_view_edit(
            plot,
            "图形样式",
            previous,
            style,
            lambda target, value: target.apply_curve_style(value, dirty=False),
        )
        plot.main_window.mark_project_dirty()
        plot.data_refreshed.emit()


def build_panel(plot):
    # Remove the old bottom controls and right-side layout without losing signals.
    main = plot.ui.horizontalLayout
    main.removeItem(plot.ui.verticalLayout_2)
    plot.ui.verticalLayout_2.setParent(None)
    fit = QtWidgets.QWidget(plot)
    fit.setLayout(plot.ui.verticalLayout_2)
    plot.property_tabs = InspectorTabs(plot)
    graph = QtWidgets.QWidget(plot.property_tabs)
    graph_layout = QtWidgets.QVBoxLayout(graph)
    form = QtWidgets.QFormLayout()
    plot.style_mode = QtWidgets.QComboBox(graph)
    plot.style_mode.addItems([title for title, _ in MODE_ITEMS])
    form.addRow("绘图方式", plot.style_mode)
    plot.style_color = ColorButton(plot.curve_style.color, graph)
    form.addRow("颜色", plot.style_color)
    plot.style_line = QtWidgets.QComboBox(graph)
    from tailor.line_styles import LINE_STYLES

    plot.style_line.addItems([title for title, _ in LINE_STYLES])
    form.addRow("线型", plot.style_line)
    for attribute, title, minimum, maximum, value in (
        ("style_width", "线宽", 0.1, 20, 1.5),
        ("style_marker", "点大小", 1, 30, 5),
        ("style_font", "字号", 6, 48, 12),
    ):
        control = QtWidgets.QDoubleSpinBox(graph)
        control.setRange(minimum, maximum)
        control.setDecimals(1)
        control.setValue(value)
        setattr(plot, attribute, control)
        form.addRow(title, control)
    plot.style_family = FontFamilyCombo(graph)
    plot.style_family.setEditable(True)
    plot.style_family.addItems(["sans-serif", "serif", "monospace"])
    plot.style_target = QtWidgets.QComboBox(graph)
    from tailor.text_style_controls import TARGETS

    for title, key in TARGETS:
        plot.style_target.addItem(title, key)
    form.insertRow(5, "字体对象", plot.style_target)
    form.addRow("字体", plot.style_family)
    plot.style_transparent = CheckButton("透明背景导出", graph)
    form.addRow(plot.style_transparent)
    plot.style_width.setMaximumWidth(80)
    plot.style_marker.setMaximumWidth(80)
    plot.style_font.setMaximumWidth(80)
    # Pair related fields instead of leaving eight full-width rows.
    while form.count():
        item = form.takeAt(0)
        if isinstance(item.widget(), QtWidgets.QLabel):
            item.widget().deleteLater()

    def pair(*widgets):
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(4)
        for widget in widgets:
            if isinstance(widget, str):
                widget = QtWidgets.QLabel(widget)
                widget.setSizePolicy(
                    QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Preferred
                )
            if isinstance(widget, QtWidgets.QAbstractSpinBox):
                from tailor.compact_controls import stepper

                widget = stepper(widget, 0.1 if widget is plot.style_width else 0.5)
            row.addWidget(widget)
        return row

    form.setFormAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
    form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
    source = QtWidgets.QComboBox()
    source.addItem(plot.model.y_label, plot)
    plot.curve_selector = source
    source.setToolTip("当前图只有一条数据曲线，样式默认作用于它。")
    source.setProperty("muted", True)
    form.addRow("作用曲线", source)
    form.addRow("绘制方式", plot.style_mode)
    form.addRow("线条", pair(plot.style_line, plot.style_width, "pt"))
    from tailor.graph_controls import MARKERS, combo

    plot.style_shape = combo(MARKERS)
    form.addRow("数据点", pair(plot.style_shape, plot.style_marker, "px"))
    form.addRow("颜色", plot.style_color)
    from tailor.curve_selection import hide_button

    form.addRow(hide_button(plot))
    plot.font_form = QtWidgets.QFormLayout()
    plot.font_form.addRow("文字对象", plot.style_target)
    plot.font_form.addRow("字体", pair(plot.style_family, plot.style_font))
    graph_layout.addLayout(form)
    arrange_axis_fields(plot)
    graph_layout.addWidget(plot.ui.groupBox_2)
    plot.ui.groupBox_2.setTitle("坐标轴")
    graph_layout.addWidget(plot.ui.set_limits_button)
    plot.ui.set_limits_button.setText("应用坐标范围")
    plot.ui.verticalLayout_2.insertWidget(0, plot.ui.fit_button)
    plot.ui.fit_button.setText("执行拟合")
    export = QtWidgets.QHBoxLayout()
    for title, suffix in (("PNG", ".png"), ("SVG", ".svg"), ("PDF", ".pdf")):
        button = QtWidgets.QPushButton(title, graph)
        button.clicked.connect(
            lambda checked=False, suffix=suffix: plot.main_window.export_graph(suffix)
        )
        export.addWidget(button)
    graph_layout.addLayout(export)
    from tailor.point_inspector import PointInspector

    plot.point_inspector = PointInspector(plot, graph_layout)
    graph_layout.addStretch()
    for widget, title in ((graph, "图形"), (fit, "拟合")):
        scroll = QtWidgets.QScrollArea(plot.property_tabs)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)
        plot.property_tabs.addTab(scroll, title)
    plot.ui.verticalLayout_5.removeItem(plot.ui.horizontalLayout_2)
    main.removeItem(plot.ui.verticalLayout_5)
    plot.ui.verticalLayout_5.setParent(None)
    figure = QtWidgets.QWidget(plot)
    figure.setLayout(plot.ui.verticalLayout_5)
    figure.layout().setContentsMargins(0, 0, 0, 0)
    main.setContentsMargins(0, 0, 0, 0)
    main.setSpacing(2)
    plot.ui.plot_widget.getPlotItem().layout.setContentsMargins(0, 0, 0, 0)
    splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal, plot)
    splitter.addWidget(figure)
    from tailor.quick_actions import QuickActions

    plot.quick_actions = QuickActions(plot)
    splitter.addWidget(plot.quick_actions)
    splitter.setChildrenCollapsible(False)
    splitter.setHandleWidth(6)
    # Establish the final parent while the tab tree is still small. Moving all
    # completed inspectors into a stack later repolishes thousands of widgets
    # synchronously and stalls the first plot on Cocoa.
    from tailor.preference_pages import PreferenceHost
    plot._preference_container = PreferenceHost(plot, None)
    plot._preference_container.setMinimumWidth(380)
    splitter.addWidget(plot._preference_container)
    splitter.setStretchFactor(0, 1)
    splitter.setSizes([720, 46, 390])
    main.addWidget(splitter)
    plot.property_tabs.setMinimumWidth(380)
    plot.property_tabs.setMaximumWidth(16777215)

    def update(*args):
        try:
            style = replace(
                plot.curve_style,
                mode=MODE_ITEMS[plot.style_mode.currentIndex()][1],
                line_style=[key for _, key in LINE_STYLES][
                    plot.style_line.currentIndex()
                ],
                line_width=plot.style_width.value(),
                marker_size=plot.style_marker.value(),
                marker=plot.style_shape.currentData(),
                transparent=plot.style_transparent.isChecked(),
            )
            apply_style(plot, style)
        except ValueError as exc:
            apply_style(plot, plot.curve_style, dirty=False)
            plot.main_window.statusBar().showMessage(f"样式未改变：{exc}")

    for control in (plot.style_mode, plot.style_line, plot.style_shape):
        control.currentIndexChanged.connect(update)
    for control in (plot.style_width, plot.style_marker):
        control.valueChanged.connect(update)
    plot.style_transparent.toggled.connect(update)

    def color():
        chosen = QtWidgets.QColorDialog.getColor(
            QtGui.QColor(plot.curve_style.color), plot, "曲线颜色"
        )
        if chosen.isValid():
            apply_style(plot, replace(plot.curve_style, color=chosen.name()))

    plot.style_color.clicked.connect(color)
    from tailor.text_style_controls import connect_font_controls

    connect_font_controls(plot)
    apply_style(plot, plot.curve_style, dirty=False)


def build_overlay_panel(plot):
    """Keep overlay axes, export and curve selection in the same right-side area."""
    main = plot.ui.horizontalLayout
    main.removeItem(plot.ui.verticalLayout_2)
    plot.ui.verticalLayout_2.setParent(None)
    curves = QtWidgets.QWidget(plot)
    curves.setLayout(plot.ui.verticalLayout_2)
    graph = QtWidgets.QWidget(plot)
    layout = QtWidgets.QVBoxLayout(graph)
    arrange_axis_fields(plot)
    layout.addWidget(plot.ui.groupBox_2)
    layout.addWidget(plot.ui.set_limits_button)
    plot.ui.set_limits_button.setText("应用坐标范围")
    export = QtWidgets.QHBoxLayout()
    for title, suffix in (("PNG", ".png"), ("SVG", ".svg"), ("PDF", ".pdf")):
        button = QtWidgets.QPushButton(title, graph)
        button.clicked.connect(
            lambda checked=False, suffix=suffix: plot.main_window.export_graph(suffix)
        )
        export.addWidget(button)
    layout.addLayout(export)
    description = QtWidgets.QLabel(
        "在“曲线”页勾选要显示的曲线，编辑图例及颜色。\n选择下方曲线进入其线型与拟合设置。",
        graph,
    )
    description.setWordWrap(True)
    layout.addWidget(description)
    choices = QtWidgets.QComboBox(graph)
    for source in plot.main_window.get_plots():
        choices.addItem(source.name, source)
    layout.addWidget(choices)
    edit = QtWidgets.QPushButton("编辑曲线…", graph)

    def open_curve():
        source = choices.currentData()
        if source is not None and plot.main_window.ui.tabWidget.indexOf(source) >= 0:
            plot.main_window.ui.tabWidget.setCurrentWidget(source)

    edit.clicked.connect(open_curve)
    layout.addWidget(edit)
    layout.addStretch()
    plot.property_tabs = InspectorTabs(plot)
    for widget, title in ((graph, "图形"), (curves, "曲线")):
        scroll = QtWidgets.QScrollArea(plot.property_tabs)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)
        plot.property_tabs.addTab(scroll, title)
    plot.ui.verticalLayout_5.removeItem(plot.ui.horizontalLayout_2)
    main.removeItem(plot.ui.verticalLayout_5)
    plot.ui.verticalLayout_5.setParent(None)
    figure = QtWidgets.QWidget(plot)
    figure.setLayout(plot.ui.verticalLayout_5)
    figure.layout().setContentsMargins(0, 0, 0, 0)
    main.setContentsMargins(0, 0, 0, 0)
    main.setSpacing(2)
    plot.ui.plot_widget.getPlotItem().layout.setContentsMargins(0, 0, 0, 0)
    splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal, plot)
    splitter.addWidget(figure)
    from tailor.quick_actions import QuickActions

    plot.quick_actions = QuickActions(plot)
    splitter.addWidget(plot.quick_actions)
    splitter.setChildrenCollapsible(False)
    splitter.setHandleWidth(6)
    from tailor.preference_pages import PreferenceHost
    plot._preference_container = PreferenceHost(plot, None)
    plot._preference_container.setMinimumWidth(380)
    splitter.addWidget(plot._preference_container)
    splitter.setStretchFactor(0, 1)
    splitter.setSizes([720, 46, 390])
    main.addWidget(splitter)
    plot.property_tabs.setMinimumWidth(380)
    plot.property_tabs.setMaximumWidth(16777215)

    from tailor.panel_layout import organize_overlay

    if plot._inspector_initializing:
        plot.start_inspector(organize_overlay(plot, deferred=True))
    else:
        organize_overlay(plot)


def dispose_graph(plot):
    """Use pyqtgraph's ordered shutdown before Qt tears down scene children."""
    if getattr(plot, "_graph_disposed", False):
        return
    from tailor.processing_controls import clear_graph_previews

    clear_graph_previews(plot.main_window, {plot})
    plot._graph_disposed = True
    if getattr(plot, "advanced_view", None):
        plot.advanced_view.close()
    if hasattr(plot, "extras"):
        plot.extras.close()
    if hasattr(plot, "quick_actions"):
        plot.quick_actions.dispose()
    if hasattr(plot, "_inspector_timer"):
        plot._inspector_timer.stop()
        plot._inspector_steps = None
        plot._inspector_initializing = False
    if hasattr(plot, "_source_timer"):
        plot._source_timer.stop()
    # Anchored legend widgets can receive geometry signals while Qt destroys
    # their ViewBox. Freeze notifications only for the scene being disposed;
    # pyqtgraph then closes its items without calling into a deleted parent.
    for child in plot.ui.plot_widget.scene().items():
        if isinstance(child, QtCore.QObject):
            child.blockSignals(True)
        if isinstance(child, pg.LegendItem):
            # Both the legend and its ViewBox notify the anchor. Disconnect the
            # legend's own geometry callback as well as freezing its parent.
            if hasattr(child,"release_anchor"):child.release_anchor()
    item = plot.ui.plot_widget.getPlotItem()
    if item is not None and item.legend is not None:
        item.legend.blockSignals(True)
    if hasattr(plot, "annotations"):
        plot.annotations.close()
    if hasattr(plot, "presentation"):
        plot.presentation.close()
    plot.ui.plot_widget.close()

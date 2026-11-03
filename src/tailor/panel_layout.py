"""Reorganize existing Tailor controls into four compact, collapsible pages."""

from tailor.compact_controls import CheckButton

import numpy as np
from PySide6 import QtCore, QtWidgets

from tailor.fold_panel import FoldPanel, stack
from tailor.processing_controls import ProcessingControls


class RangeControls(QtWidgets.QWidget):
    def __init__(self, plot):
        super().__init__(plot)
        self.plot = plot
        self.on_range_edit = None
        self.after_crop = None
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        form = QtWidgets.QFormLayout()
        self.crop_boxes = tuple(QtWidgets.QLineEdit() for _ in range(4))
        from tailor.graph_controls import row

        self.x_label, self.y_label = (
            QtWidgets.QLabel("下 X 轴"),
            QtWidgets.QLabel("左 Y 轴"),
        )
        form.addRow(self.x_label, row(self.crop_boxes[0], "—", self.crop_boxes[1]))
        form.addRow(self.y_label, row(self.crop_boxes[2], "—", self.crop_boxes[3]))
        layout.addLayout(form)
        self.info = QtWidgets.QLabel()
        self.info.hide()
        self.info.setProperty("muted", True)
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        crop = QtWidgets.QPushButton("裁切范围外数据")
        crop.setProperty("intent", "destructive")
        self.crop_button = crop
        crop.clicked.connect(self.crop)
        layout.addWidget(crop)
        for index, box in enumerate(self.boxes()):
            box.setPlaceholderText("最小 / 自动" if index in (0, 2) else "最大 / 自动")
            box.setMaximumWidth(16777215)
            box.editingFinished.connect(self.edited)

    def boxes(self):
        return self.crop_boxes

    def bounds(self, require_any=True):
        try:
            values = tuple(
                float(box.text()) if box.text().strip() else None
                for box in self.boxes()
            )
        except ValueError:
            raise ValueError("边界请输入数字，也可以留空。") from None
        if any(value is not None and not np.isfinite(value) for value in values):
            raise ValueError("边界必须为有限数字。")
        for lower, upper in (values[:2], values[2:]):
            if lower is not None and upper is not None and lower >= upper:
                raise ValueError("最小值必须小于最大值。")
        if require_any and all(value is None for value in values):
            raise ValueError("至少填写一个裁切边界。")
        return values

    def mask(self):
        bounds = self.bounds()
        model = self.plot.model
        mask = np.ones(self.plot.data_sheet.model.rowCount(), dtype=bool)
        for key, lower, upper in (
            (model.x_col, *bounds[:2]),
            (model.y_col, *bounds[2:]),
        ):
            values = np.asarray(model.data_model.get_column(key))
            if lower is not None:
                mask &= values >= lower
            if upper is not None:
                mask &= values <= upper
        return mask

    def edited(self):
        if self.on_range_edit is not None:
            self.on_range_edit()
        else:
            self.apply()

    def notify(self, message):
        if self.plot is not None:
            self.plot.main_window.statusBar().showMessage(message, 6000)
        self.info.setText(message)
        self.info.setVisible(bool(message))

    def apply(self):
        if self.on_range_edit is not None:
            self.on_range_edit()
            return
        try:
            values = self.bounds(False)
            self.plot.apply_axis_bounds(values)
            self.notify("已应用坐标范围。")
        except ValueError as error:
            self.notify(str(error))

    def crop(self):
        if self.plot.main_window.data_operation_busy():
            self.notify("请等待当前后台操作结束后裁切。")
            return
        try:
            values = self.bounds()
            mask = self.mask()
            if not mask.any():
                raise ValueError("范围内没有数据，未删除工作表。")
            source = self.plot.data_sheet.model
            shift = values[0]
            column = (
                list(source.columnLabels()).index(self.plot.model.x_col)
                if shift is not None
                else None
            )
            if source.keep_rows(mask, shift_column=column, shift=shift or 0.0):
                self.reset(record=False)
                self.plot.refresh_from_source()
                if self.after_crop is not None:
                    self.after_crop()
                self.notify(
                    "已裁切"
                    + ("并将 X 起点归零" if shift is not None else "")
                    + "；可用中间按钮列撤销，原 CSV 保留。"
                )
            else:
                self.notify("未裁切：检查撤销容量，X 归零需使用普通数值列。")
        except (ValueError, TypeError) as error:
            self.notify(str(error))

    def reset(self, checked=False, record=True):
        for box in self.boxes():
            blocker = QtCore.QSignalBlocker(box)
            box.clear()
            del blocker
        self.plot.apply_axis_bounds((None, None, None, None), dirty=record)
        self.notify("自动显示完整数据。")


def ensure_advanced_controls(plot):
    """Create the advanced inspector only for a graph that uses it."""
    existing=getattr(plot,'advanced_controls',None)
    if existing is not None:return existing
    tabs=plot.property_tabs
    process=getattr(plot,'processing_controls',None)
    index=tabs.indexOf(process) if process is not None else -1
    if index<0:return None
    from tailor.advanced_plotting import AdvancedControls
    plot.advanced_controls=AdvancedControls(plot)
    tabs.insertTab(index+1,plot.advanced_controls,'高级')
    tabs.setTabVisible(tabs.indexOf(plot.advanced_controls),False)
    return plot.advanced_controls


def organize_single(plot, deferred=False):
    stages = _single_sections(plot)
    if deferred:
        return stages
    with QtCore.QSignalBlocker(plot.property_tabs):
        for _ in stages:
            pass


def _single_sections(plot):
    tabs = plot.property_tabs
    fit_only = getattr(plot, "_hidden_curve_source", False)
    graph_old = tabs.widget(0).widget()
    style_form = graph_old.layout().takeAt(0).layout()
    if fit_only:
        # A suspended generator can be cancelled before the fitting page is
        # complete. Qt must own the detached layout throughout that interval.
        parking = QtWidgets.QWidget(plot)
        parking.setLayout(style_form);parking.hide()
        plot._source_style_parking = parking
    tabs.widget(0).hide()
    old_pages = [tabs.widget(i) for i in range(tabs.count())]
    tabs.clear()
    for old in old_pages:
        old.setParent(plot)
        old.hide()
    graph, fit, export = FoldPanel(plot), FoldPanel(plot), FoldPanel(plot)
    plot.range_controls = RangeControls(plot)
    from tailor.graph_controls import (
        ErrorControls,
        LegendControls,
        row,
    )

    if not fit_only:
        graph.add_section("曲线", style_form, True)
        inspector = plot.point_inspector
        inspector.group.setTitle("")
        inspector.region.hide()
        inspector.range_info.hide()
        from tailor.graph_defaults import read

        inspector.enabled.setChecked(bool(read("points")))
        inspector.details.setText("")
        legend = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(legend)
        plot.legend_name_edit = QtWidgets.QLineEdit(plot.model.legend_label)
        plot.legend_toggle = CheckButton("显示右上角图例")
        plot.legend_toggle.setChecked(plot.model.legend_visible)
        form.addRow("数据名称", plot.legend_name_edit)
        plot.legend_name_edit.setPlaceholderText("留空跟随源列名称")
        plot.legend_toggle.hide()

        def legend_changed():
            plot.model.legend_label = plot.legend_name_edit.text().strip()
            plot.model.legend_visible = plot.legend_toggle.isChecked()
            plot.refresh_legend()
            plot.main_window.mark_project_dirty()

        plot.legend_name_edit.editingFinished.connect(legend_changed)
        plot.legend_toggle.toggled.connect(legend_changed)
        plot.legend_controls = LegendControls(plot)
        legend.setParent(plot)
        legend.hide()
        graph.add_section("图例", plot.legend_controls)
        from tailor.axis_controls import AxisControls

        yield
        axis_controls = AxisControls(plot, deferred=True)
        yield from axis_controls._build_steps
        plot.axis_controls = axis_controls
        yield
        plot.ui.groupBox_2.hide()
        plot.ui.set_limits_button.hide()
    plot.error_controls = ErrorControls(plot)
    if not fit_only:
        from tailor.margin_controls import MarginControls

        plot.margin_controls = MarginControls(plot)
        graph.add_section("图形边距", plot.margin_controls)
        graph.add_section("选择数据点", inspector.group, True)
    yield
    for widget in (
        plot.ui.groupBox,
        plot.ui.parameter_box,
        plot.ui.groupBox_3,
        plot.ui.groupBox_4,
    ):
        widget.setMinimumWidth(0)
        widget.setTitle("")
    plot.ui.model_func.setFixedHeight(48)
    plot.ui.model_func_label.setText("公式")
    plot.preset_controls.group.setTitle("")
    # Reuse the native parameter controls without a second scrolling surface.
    parameter_list = plot.ui.scrollArea.takeWidget()
    parameter_list.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
    plot.ui.parameter_box.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
    parameter_list.setObjectName("fitParameterList")
    parameter_list.setAutoFillBackground(False)
    plot.ui.verticalLayout_4.removeWidget(plot.ui.scrollArea)
    plot.ui.scrollArea.hide()
    labels = QtWidgets.QHBoxLayout()
    for title, width in (
        ("参数", 78),
        ("初值", 0),
        ("下界", 68),
        ("上界", 68),
        ("固定", 22),
    ):
        label = QtWidgets.QLabel(title)
        if width:
            label.setFixedWidth(width)
        labels.addWidget(label)
    plot.ui.verticalLayout_4.addLayout(labels)
    plot.ui.verticalLayout_4.addWidget(parameter_list)
    plot.ui.result_box.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)
    plot.ui.result_box.setMinimumHeight(150)
    plot.ui.result_box.setMaximumHeight(250)
    plot.ui.show_initial_fit.setText("显示初值参考线（非拟合结果）")
    plot.ui.show_initial_fit.setToolTip(
        "根据当前初值计算的参考线，用于判断起始参数是否合理；执行拟合后显示的是优化得到的结果，两者通常不同。"
    )
    plot.ui.use_fit_domain.setText("使用 X 范围")
    plot.ui.label_7.setText("开始")
    plot.ui.label_8.setText("结束")
    plot.ui.label_9.setText("拟合线显示")
    for i, label in enumerate(("数据范围", "拟合范围", "完整坐标轴")):
        plot.ui.draw_curve_option.setItemText(i, label)
    model_group = plot.preset_controls.group
    selector = plot.preset_controls.selector
    help_button = plot.preset_controls.help_button
    selector.setMinimumWidth(0)
    plot.fit_header = fit.pin_header(row("选择模型", selector, help_button))
    model_group.hide()
    from tailor.fit_actions import FitActions
    plot.fit_actions = FitActions(plot, fit)
    fit.add_section("拟合函数", plot.ui.groupBox, False, initially_closed=True)
    use_axis = QtWidgets.QPushButton("使用 X 显示范围")
    use_axis.setCheckable(True)
    plot._fit_range_loading = False

    def use_range():
        try:
            lower, upper = plot.model.x_min, plot.model.x_max
            x = plot.model.get_data()[0]
            lower = float(np.min(x)) if lower is None else lower
            upper = float(np.max(x)) if upper is None else upper
            host=getattr(plot,'_fit_host',plot)
            info=host.model.get_plot_info(plot) if host.presentation.multi else None
            box=host.presentation.box_for(info) if info else host.ui.plot_widget.getViewBox()
            xkey='top' if info and info.x_axis=='top' else 'x'
            shown = box.viewRange()[0]
            from tailor.graph_presentation import physical
            lower, upper = sorted(physical(shown, host.presentation.axes[xkey]))
            plot._fit_range_loading = True
            plot.model.set_fit_domain(lower, upper)
            plot.model.set_fit_domain_enabled(True)
            plot.update_fit_domain_from_model()
            plot._fit_range_loading = False
            plot.update_model_curves()
            plot.main_window.mark_project_dirty()
        except ValueError as error:
            plot.main_window.statusBar().showMessage(str(error))

    use_axis.clicked.connect(lambda checked: use_range() if checked else None)
    def manual_range(*args):
        if not plot._fit_range_loading:
            use_axis.setChecked(False)
            plot.model.set_fit_domain_enabled(True)
            with QtCore.QSignalBlocker(plot.ui.use_fit_domain):
                plot.ui.use_fit_domain.setChecked(True)
    plot.ui.fit_start_box.sigValueChanging.connect(manual_range)
    plot.ui.fit_end_box.sigValueChanging.connect(manual_range)
    plot.ui.use_fit_domain.hide()
    range_box = QtWidgets.QWidget()
    range_layout = QtWidgets.QVBoxLayout(range_box)
    range_layout.setContentsMargins(0,0,0,0)
    for field in (plot.ui.fit_start_box, plot.ui.fit_end_box):
        field.setMinimumWidth(42)
        field.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
    range_layout.addWidget(row("开始", plot.ui.fit_start_box, "结束", plot.ui.fit_end_box))
    range_layout.addWidget(row("拟合线显示", plot.ui.draw_curve_option))
    plot.ui.groupBox_4.hide()
    fit.add_section(
        "参数与执行",
        stack(
            plot.preset_controls.manual_peaks.widget,
            plot.ui.parameter_box,
            row(plot.ui.fit_button, plot.preset_controls.guess_button),
            row(plot.fit_actions.hidden, plot.fit_actions.delete),
        ),
        True,
        keep_field_titles=True,
    )
    fit.add_section("拟合范围", stack(use_axis, range_box))
    fit.add_section("误差棒", plot.error_controls)
    fit.add_section("拟合结果", plot.ui.groupBox_3, True)
    from tailor.fit_workflow import build_single
    build_single(plot, fit, use_axis, range_box)
    if fit_only:
        # Keep the legacy source controls under a Qt owner even though their
        # layout is not used by the visible group's shared inspector.
        from tailor.annotations import AnnotationManager
        from tailor.curve_selection import CurveSelection
        plot.annotations = AnnotationManager(plot)
        plot.curve_selection = CurveSelection(plot)
        tabs.addTab(fit, "拟合")
        yield
        plot.refresh_legend()
        return
    buttons = []
    for label in ("PNG", "SVG", "PDF"):
        buttons.extend(
            button
            for button in graph_old.findChildren(QtWidgets.QPushButton)
            if button.text() == label
        )
    from tailor.graph_controls import row

    for button in buttons:
        button.setToolTip(
            {"PNG": "PNG 位图", "SVG": "SVG 矢量图", "PDF": "PDF 矢量图"}[button.text()]
        )
    export.add_section(
        "导出叠加图",
        stack(QtWidgets.QLabel("选择格式"), row(*buttons), plot.style_transparent),
        True,
    )
    from tailor.fit_export_controls import FitExportControls
    plot.export_controls=FitExportControls(plot,export)
    yield
    if getattr(plot, '_inset_parent', None) is None:
        process = plot.processing_controls = ProcessingControls(plot, deferred=True)
        yield from process._build_steps
    else:
        # This tab is permanently disabled on an inset. Keep the existing tab
        # arrangement without allocating an unusable analysis inspector.
        process = FoldPanel(plot)
    yield
    from tailor.annotation_controls import setup_annotations

    annotation = setup_annotations(plot)
    yield
    for widget, title in (
        (graph, "图形"),
        (plot.axis_controls, "坐标轴"),
        (fit, "拟合"),
        (process, "处理"),
        (export, "导出"),
    ):
        tabs.addTab(widget, title)
        yield
    if plot.presentation.extra_settings.get('advanced'):
        ensure_advanced_controls(plot)
    yield
    from tailor.curve_selection import CurveSelection

    plot.curve_selection = CurveSelection(plot)
    from tailor.preference_pages import setup_preferences

    for _ in setup_preferences(plot, graph, annotation, deferred=True):
        yield
    plot.refresh_legend()
    for name in ("bottom", "left"):
        axis = plot.ui.plot_widget.getAxis(name)
        axis.enableAutoSIPrefix(False)
        axis.setLabel(units="")
    yield


def organize_overlay(plot, deferred=False):
    stages = _overlay_sections(plot)
    if deferred:
        return stages
    with QtCore.QSignalBlocker(plot.property_tabs):
        for _ in stages:
            pass


def _overlay_sections(plot):
    tabs = plot.property_tabs
    graph_old, curves_old = tabs.widget(0).widget(), tabs.widget(1).widget()
    old_pages = [tabs.widget(i) for i in range(tabs.count())]
    tabs.clear()
    for old in old_pages:
        old.setParent(plot)
        old.hide()
    graph, fit, export = (FoldPanel(plot) for _ in range(3))
    embedded = getattr(plot, '_inset_parent', None) is not None
    if embedded:
        process = FoldPanel(plot)
    else:
        process = plot.processing_controls = ProcessingControls(plot, deferred=True)
        yield from process._build_steps
    yield
    from tailor.graph_controls import (
        CurveManager,
        ErrorControls,
        LegendControls,
    )
    from tailor.overlay_inspector import OverlayInspector

    curves_old.hide()
    plot.curve_manager = CurveManager(plot)
    graph.add_section("曲线", plot.curve_manager, True)
    plot.legend_controls = LegendControls(plot)
    graph.add_section("图例", plot.legend_controls)
    from tailor.axis_controls import AxisControls

    plot.range_controls = RangeControls(None)
    plot.range_controls.setEnabled(False)
    yield
    axis_controls = AxisControls(plot, deferred=True)
    yield from axis_controls._build_steps
    plot.axis_controls = axis_controls
    yield
    plot.ui.groupBox_2.hide()
    plot.ui.set_limits_button.hide()

    def crop_target():
        source = plot.curve_manager.current_plot()
        plot.range_controls.plot = source
        plot.range_controls.setEnabled(source is not None)

    plot.curve_manager.curves.currentIndexChanged.connect(crop_target)
    crop_target()
    plot.error_controls = ErrorControls(plot)
    fit.add_section("误差棒", plot.error_controls)
    plot.point_inspector = OverlayInspector(plot)
    from tailor.margin_controls import MarginControls

    plot.margin_controls = MarginControls(plot)
    graph.add_section("图形边距", plot.margin_controls)
    graph.add_section("选择数据点", plot.point_inspector, True)
    yield

    from tailor.fit_workflow import FitRouter
    fit.hide()
    if not embedded:
        fit = plot.fit_router = FitRouter(plot)
    buttons = [
        button
        for button in graph_old.findChildren(QtWidgets.QPushButton)
        if button.text() in {"PNG", "SVG", "PDF"}
    ]
    from tailor.graph_controls import row

    export.add_section("导出叠加图", row(*buttons), True)
    from tailor.fit_export_controls import FitExportControls
    if not embedded:
        plot.export_controls=FitExportControls(plot,export)
    from tailor.annotation_controls import setup_annotations

    annotation = setup_annotations(plot)
    yield
    for page, title in (
        (graph, "图形"),
        (plot.axis_controls, "坐标轴"),
        (fit, "拟合"),
        (process, "处理"),
        (export, "导出"),
    ):
        tabs.addTab(page, title)
        yield
    if plot.presentation.extra_settings.get('advanced'):
        ensure_advanced_controls(plot)
    yield
    from tailor.curve_selection import CurveSelection

    plot.curve_selection = CurveSelection(plot)
    from tailor.preference_pages import setup_preferences

    yield from setup_preferences(plot, graph, annotation, deferred=True)
    plot.presentation.apply_legend()
    for name in ("bottom", "left"):
        plot.ui.plot_widget.getAxis(name).enableAutoSIPrefix(False)
        plot.ui.plot_widget.getAxis(name).setLabel(units="")

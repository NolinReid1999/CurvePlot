"""Four-axis inspector; native pyqtgraph axes and existing source-row cropping."""

import copy
from dataclasses import replace

from PySide6 import QtCore, QtGui, QtWidgets

from tailor.compact_controls import preference_button, toggle_button
from tailor.fold_panel import FoldPanel
from tailor.graph_controls import color_button, combo, number, row
from tailor.object_text_editor import ObjectTextEditor
from tailor.view_history import view_transaction

AXIS_NAMES = {"x": "下 X 轴", "y": "左 Y 轴", "top": "上 X 轴", "right": "右 Y 轴"}


def axis_icon(key):
    pix = QtGui.QPixmap(64, 48)
    pix.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pix)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.setPen(QtGui.QPen(QtGui.QColor("#9ba8b8"), 2))
    painter.drawRect(12, 8, 40, 30)
    painter.setPen(QtGui.QPen(QtGui.QColor("#2878cc"), 4))
    ends = {
        "x": (12, 38, 52, 38),
        "top": (12, 8, 52, 8),
        "y": (12, 8, 12, 38),
        "right": (52, 8, 52, 38),
    }
    painter.drawLine(*ends[key])
    painter.setPen(QtGui.QPen(QtGui.QColor("#2878cc"), 2))
    if key in {"x", "top"}:
        y, dy = (38, 5) if key == "x" else (8, -5)
        for x in (22, 32, 42):
            painter.drawLine(x, y, x, y + dy)
    else:
        x, dx = (12, -5) if key == "y" else (52, 5)
        for y in (16, 23, 30):
            painter.drawLine(x, y, x + dx, y)
    painter.end()
    pix.setDevicePixelRatio(2)
    return QtGui.QIcon(pix)


class AxisControls(FoldPanel):
    def __init__(self, plot, *, deferred=False):
        super().__init__(plot)
        self._build_steps = self._build(plot)
        if not deferred:
            for _ in self._build_steps:
                pass

    def _build(self, plot):
        self.plot, self.loading = plot, True
        self.current, self.horizontal, self.vertical = "x", "x", "y"
        self.axis_buttons = {}
        self.axis_group = QtWidgets.QButtonGroup(self)
        for key, label in AXIS_NAMES.items():
            button = QtWidgets.QToolButton()
            button.setText(label)
            button.setProperty("axisSelector", True)
            button.setIcon(axis_icon(key))
            button.setIconSize(QtCore.QSize(28, 22))
            button.setProperty("inspectorHeight", 54)
            button.setFixedSize(64, 54)
            button.setToolButtonStyle(QtCore.Qt.ToolButtonTextUnderIcon)
            button.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
            )
            button.setCheckable(True)
            self.axis_group.addButton(button)
            self.axis_buttons[key] = button
            button.clicked.connect(lambda checked=False, k=key: self.select_axis(k))
        axis_row = row(*self.axis_buttons.values())
        from tailor.graph_focus import GraphPicker
        self.graph_picker=GraphPicker(plot)
        self.fixed_header = self.pin_header(axis_row, row("当前图形",self.graph_picker))
        form = QtWidgets.QFormLayout()
        self.curves = QtWidgets.QComboBox()
        self.x_side = combo([("下 X 轴", "bottom"), ("上 X 轴", "top")])
        self.side = combo([("左 Y 轴", "left"), ("右 Y 轴", "right")])
        form.addRow("当前曲线", self.curves)
        form.addRow("横轴 / 纵轴", row(self.x_side, self.side))
        self.add_section("曲线所属坐标轴", form, True)
        yield
        self.curves.activated.connect(self.choose_curve)
        self.side.activated.connect(self.assign_side)
        self.x_side.activated.connect(self.assign_side)

        form = QtWidgets.QFormLayout()
        self.range = plot.range_controls
        self.range.on_range_edit = self.apply_ranges
        self.range.after_crop = self.after_crop
        form.addRow(self.range)
        self.scale = combo([("线性（等差）", False), ("对数（log₁₀）", True)])
        self.inverted = toggle_button("反转坐标轴")
        self.inverted.setToolTip("只反转显示方向，例如从 0→10 改为 10→0，源数据不变")
        form.addRow("当前轴比例", self.scale)
        auto = QtWidgets.QPushButton("当前轴自动范围")
        auto.clicked.connect(self.auto_range)
        form.addRow(row(self.inverted, auto))
        self.message = QtWidgets.QLabel()
        self.message.setWordWrap(True)
        self.message.hide()
        form.addRow(self.message)
        self.add_section("范围与比例", form, True)
        yield

        form = QtWidgets.QVBoxLayout()
        self.major = QtWidgets.QLineEdit()
        self.major.setPlaceholderText("自动")
        self.major_visible = toggle_button("显示主刻度")
        self.minor_count = QtWidgets.QSpinBox()
        self.minor_count.setRange(0, 20)
        self.minor_visible = toggle_button("显示次刻度")
        self.minor = QtWidgets.QLineEdit()
        self.minor.setPlaceholderText("自动")
        form.addWidget(row(self.major_visible, "主刻度间隔", self.major))
        self.direction = combo([("朝外", "out"), ("朝内", "in")])
        self.direction.hide()
        self.tick_length = number(0, 20, 5,unit="px")
        self.minor_length = number(0, 20, 3,unit="px")
        form.addWidget(row("主刻度长度", self.tick_length))
        form.addWidget(row(self.minor_visible, "次刻度间隔", self.minor))
        form.addWidget(row("每段次刻度", self.minor_count))
        form.addWidget(row("次刻度长度", self.minor_length))
        self.direction_buttons = {}
        directions = QtWidgets.QButtonGroup(self)
        for key, text in (("in", "朝内"), ("out", "朝外")):
            button = toggle_button(text)
            directions.addButton(button)
            self.direction_buttons[key] = button
            button.clicked.connect(
                lambda checked=False, key=key: self.set_direction(key)
            )
        form.addWidget(row("刻度方向", *self.direction_buttons.values()))
        self.add_section("主刻度与次刻度", form)
        yield

        form = QtWidgets.QVBoxLayout()
        self.labels = toggle_button("显示刻度文字")
        self.notation = combo(
            [
                ("自动 · 1000 / 1e+06", "auto"),
                ("小数 · 1000.00", "fixed"),
                ("科学计数 · 1.00e+03", "scientific"),
            ]
        )
        self.precision = QtWidgets.QSpinBox()
        self.precision.setRange(0, 12)
        self.precision.setProperty("sliderUnit","位")
        self.precision_label = QtWidgets.QLabel("有效位数")
        self.divisor = QtWidgets.QLineEdit("1")
        self.divisor.hide()
        self.expression = QtWidgets.QLineEdit()
        self.expression.setPlaceholderText("x，例如 x/1000 或 x*2+5")
        self.expression.setToolTip(
            "仅调整刻度显示，不改变原始数据或坐标范围；变量 x 表示原值"
        )
        self.prefix, self.suffix = QtWidgets.QLineEdit(), QtWidgets.QLineEdit()
        self.tick_font = preference_button("font")
        self.tick_font.clicked.connect(lambda: self.open_font("ticks"))
        form.addWidget(row("数字格式", self.notation))
        form.addWidget(row(self.precision_label, self.precision))
        form.addWidget(row("文字前缀", self.prefix, "文字后缀", self.suffix))
        form.addWidget(row("显示值调整", self.expression))
        self.add_section("刻度文字格式", form)
        yield

        form = QtWidgets.QVBoxLayout()
        self.text_target = combo([("轴标题", "label"), ("刻度文字", "ticks")])
        self.text_target.hide()
        self.current_label = QtWidgets.QLabel()
        self.current_label.hide()
        self.title_visible = toggle_button("显示轴标题")
        self.text_editor = ObjectTextEditor(self)
        self.text_editor.hide()
        self.title_font = preference_button("font")
        self.title_font.clicked.connect(lambda: self.open_font("label"))
        self.visible = toggle_button("显示轴线")
        self.ticks_visible = toggle_button("显示刻度")
        self.color = color_button("#202020", lambda value: self.apply())
        self.color.hide()
        self.axis_width = number(0.1, 20, 1,unit="px")
        self.axis_width.hide()
        self.axis_stroke = preference_button("curve")
        self.axis_stroke.clicked.connect(
            lambda: plot.preferences.open_group_curve("axis", self.current)
        )
        self.tick_stroke = preference_button("curve")
        self.tick_stroke.clicked.connect(
            lambda: plot.preferences.open_group_curve("axis", self.current)
        )
        grid = QtWidgets.QGridLayout()
        for index, (button, preference) in enumerate((
                (self.title_visible, self.title_font), (self.labels, self.tick_font),
                (self.ticks_visible, self.tick_stroke), (self.visible, self.axis_stroke))):
            preference.setText("")
            preference.setFixedWidth(34)
            grid.addWidget(row(button, preference), index // 2, index % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        form.addLayout(grid)
        self.borders = {}
        self.add_section("标题与轴线", form)
        yield
        self.text_target.currentIndexChanged.connect(self.sync_text)
        self.text_editor.changed.connect(self.apply_text)

        form = QtWidgets.QVBoxLayout()
        self.grid = toggle_button("显示主网格线")
        self.minor_grid = toggle_button("显示次网格线")
        self.grid_count, self.minor_grid_count = (
            QtWidgets.QSpinBox(),
            QtWidgets.QSpinBox(),
        )
        for box in (self.grid_count, self.minor_grid_count):
            box.setRange(0, 100)
            box.setSpecialValueText("自动")
            box.setToolTip("网格线数量；0为跟随刻度，不改变刻度位置")
        self.grid_color = color_button("#9ba5b1", lambda value: self.apply())
        self.grid_width = number(0.1, 3, 0.5,unit="px")
        from tailor.line_styles import LINE_STYLES

        self.grid_style = combo(LINE_STYLES)
        for widget in (self.grid_color, self.grid_width, self.grid_style):
            widget.hide()
        form.addWidget(row(self.grid, self.grid_count))
        form.addWidget(row(self.minor_grid, self.minor_grid_count))
        self.grid_stroke = preference_button("curve")
        self.grid_stroke.clicked.connect(
            lambda: plot.preferences.open_group_curve("grid", self.current)
        )
        form.addWidget(self.grid_stroke)
        self.add_section("网格", form)
        yield
        order = [
            "标题与轴线",
            "刻度文字格式",
            "主刻度与次刻度",
            "范围与比例",
            "网格",
            "曲线所属坐标轴",
        ]
        self.sections.sort(key=lambda r: order.index(r[1].property("sectionTitle")))
        for i, section in enumerate(self.sections):
            self.open_layout.removeWidget(section[0])
            self.open_layout.insertWidget(i, section[0])
        for name, title in {
            "precision": "有效位数",
            "prefix": "文字前缀",
            "suffix": "文字后缀",
            "divisor": "显示值除数",
            "grid_count": "主网格线数量",
            "minor_grid_count": "次网格线数量",
            "x_side": "横轴归属",
            "side": "纵轴归属",
        }.items():
            getattr(self, name).setAccessibleName(title)
        for box, title in zip(
            self.range.boxes(),
            ("横轴最小值", "横轴最大值", "纵轴最小值", "纵轴最大值"),
            strict=True,
        ):
            box.setAccessibleName(title)
        self.loading = False
        self.sync()
        for box in (
            self.major,
            self.minor,
            self.divisor,
            self.prefix,
            self.suffix,
        ):
            box.editingFinished.connect(self.apply)
        for box in (self.scale, self.direction, self.notation, self.grid_style):
            box.activated.connect(self.apply)
        for box in (
            self.inverted,
            self.major_visible,
            self.minor_visible,
            self.grid,
            self.minor_grid,
            *self.borders.values(),
        ):
            box.toggled.connect(self.apply)
        for button, key in ((self.labels, 'labels'), (self.title_visible, 'title_visible'),
                            (self.visible, 'line_visible'), (self.ticks_visible, 'ticks_visible')):
            button.toggled.connect(lambda checked, key=key: self.set_display(key, checked))
        for box in (
            self.minor_count,
            self.tick_length,
            self.minor_length,
            self.axis_width,
            self.grid_width,
            self.grid_count,
            self.minor_grid_count,
        ):
            box.valueChanged.connect(self.apply)

        self.precision.valueChanged.connect(self.precision_changed)

        from tailor.axis_extensions import AdvancedAxes

        self.advanced = AdvancedAxes(self)
        yield
        from tailor.axis_shared_controls import install
        yield from install(self, deferred=True)

    def set_direction(self, key):
        self.direction.setCurrentIndex(self.direction.findData(key))
        self.apply()

    def set_display(self, key, checked):
        if self.loading:
            return
        self._pending_display = (key, checked)
        self.apply()

    def sync_display(self, cfg):
        for button, key in ((self.visible, 'line_visible'), (self.ticks_visible, 'ticks_visible'),
                            (self.labels, 'labels'), (self.title_visible, 'title_visible')):
            checked = cfg['visible'] and cfg.get(key, True)
            if key == 'ticks_visible':
                checked = checked and max(cfg['tick_length'], cfg['minor_length']) > 0
            with QtCore.QSignalBlocker(button):
                button.setChecked(checked)
        for key in ('tick_length', 'minor_length'):
            with QtCore.QSignalBlocker(getattr(self, key)):
                getattr(self, key).setValue(cfg[key])

    def open_font(self, kind):
        self.plot.preferences.clear_group_selection()
        self.plot.text_selection.select(self.current+'_'+kind)
        self.text_target.setCurrentIndex(self.text_target.findData(kind))
        self.sync_text()
        self.plot.preferences.open_font(self.text_editor, self.current_label.text())

    def save_tick_default(self):
        import json

        keys = ("notation", "precision", "divisor", "prefix", "suffix", "expression")
        cfg = self.plot.presentation.axes[self.current]
        QtCore.QSettings("PhysicsPlot", "AxisDefaults").setValue(
            self.current, json.dumps({k: cfg[k] for k in keys})
        )

    def axis_name(self, key):
        view = getattr(self.plot, "advanced_view", None)
        if view and view.cfg["kind"] == "3d":
            from tailor.three_d_axes import NAMES

            return NAMES[key]
        return AXIS_NAMES[key]

    def holder(self, key):
        return self.plot.presentation if key in {"right", "top"} else self.plot.model

    def select_axis(self, key, kind=None):
        if hasattr(self,'text_editor'):self.text_editor.content.commit()
        if hasattr(self,'factor_editor'):self.factor_editor.content.commit()
        if (getattr(self,'selected_tick',None) or (None,))[0]!=key:self.selected_tick=None
        self.current = key
        if key in {"x", "top"}:
            self.horizontal = key
        else:
            self.vertical = key
        if kind:
            with QtCore.QSignalBlocker(self.text_target):
                self.text_target.setCurrentIndex(self.text_target.findData(kind))
        self.sync()
        self.advanced.sync()

    def choose_curve(self):
        source=self.curves.currentData()
        if hasattr(self.plot,'preferences'):
            self.plot.preferences.select_curve('data' if source is not None else 'none',source)
        if self.plot.presentation.multi:
            manager = self.plot.curve_manager
            manager.curves.setCurrentIndex(
                manager.curves.findData(self.curves.currentData())
            )
        self.sync_side()

    def sync_side(self):
        source = self.curves.currentData()
        info = (
            self.plot.model.get_plot_info(source)
            if self.plot.presentation.multi
            else None
        )
        for box, value in (
            (
                self.side,
                info.axis if info else self.plot.presentation.single_sides["y"],
            ),
            (
                self.x_side,
                info.x_axis if info else self.plot.presentation.single_sides["x"],
            ),
        ):
            with QtCore.QSignalBlocker(box):
                from tailor.choice_state import show_setting
                show_setting(box,value,selected=source is not None)
        self.range.plot = source or self.plot
        self.range.setEnabled(True)

    @view_transaction("曲线坐标轴归属")
    def assign_side(self, *args):
        if self.loading or self.curves.currentData() is None:
            return
        xside, yside = self.x_side.currentData(), self.side.currentData()
        plot = self.plot
        if not plot.presentation.multi:
            p = plot.presentation
            old = dict(p.single_sides)
            for key, alternate, wanted, normal in (
                ("x", "top", xside, "bottom"),
                ("y", "right", yside, "left"),
            ):
                active = alternate if old[key] == alternate else key
                dest = alternate if wanted == alternate else key
                p.axes[dest].update(copy.deepcopy(p.axes[active]))
                if active != dest:
                    source_holder = p if active in {"top", "right"} else plot.model
                    target_holder = p if dest in {"top", "right"} else plot.model
                    setattr(
                        target_holder,
                        dest + "_label",
                        getattr(source_holder, active + "_label"),
                    )
                p.axes[key]["visible"] = wanted == normal
                p.axes[alternate]["visible"] = wanted == alternate
                p.frame[normal] = wanted == normal
                p.frame[alternate] = wanted == alternate
            p.single_sides = {"x": xside, "y": yside}
            self.horizontal = "top" if xside == "top" else "x"
            self.vertical = "right" if yside == "right" else "y"
            plot._clear_remembered_zoom()
            plot.update_plot()
            plot.update_limits()
            p.apply_axes()
            self.sync()
            plot.main_window.mark_project_dirty()
            return
        source = self.curves.currentData()
        info = plot.model.get_plot_info(source)
        if info is None:
            return
        info.axis, info.x_axis = yside, xside
        p = plot.presentation
        if xside == "top":
            p.top_label = source.model.x_label
        if yside == "right":
            p.right_label = source.model.y_label
        self.horizontal, self.vertical = (
            ("top" if xside == "top" else "x"),
            ("right" if yside == "right" else "y"),
        )
        plot._clear_remembered_zoom()
        plot.draw_plot()
        plot.curve_manager.sync_fields()
        self.sync()
        plot.main_window.mark_project_dirty()

    def sync(self):
        if self.loading:
            return
        self.loading = True
        try:
            cfg = self.plot.presentation.axes[self.current]
            self.axis_buttons[self.current].setChecked(True)
            source=getattr(getattr(self.plot,'curve_selection',None),'current',None)
            with QtCore.QSignalBlocker(self.curves):
                self.curves.clear()
                self.curves.addItem('—',None)
                from tailor.choice_catalog import sorted_sources
                sources=sorted_sources(self.plot)
                for item in sources:
                    self.curves.addItem(__import__("tailor.column_titles",fromlist=["display"]).display(item.data_sheet.model,item.model.y_col), item)
                self.curves.setCurrentIndex(max(0, self.curves.findData(source)))
            self.sync_side()
            for name in ("direction", "notation", "grid_style"):
                box = getattr(self, name)
                box.setCurrentIndex(box.findData(cfg[name]))
            self.scale.setCurrentIndex(self.scale.findData(cfg["log"]))
            for name in (
                "inverted",
                "major_visible",
                "minor_visible",
                "grid",
                "minor_grid",
            ):
                getattr(self, name).setChecked(cfg[name])
            self.sync_display(cfg)
            for name in (
                "precision",
                "minor_count",
                "tick_length",
                "minor_length",
                "axis_width",
                "grid_width",
                "grid_count",
                "minor_grid_count",
            ):
                getattr(self, name).setValue(cfg[name])
            for name in ("color", "grid_color", "prefix", "suffix"):
                getattr(self, name).setText(cfg[name])
            self.divisor.setText(str(cfg["divisor"]))
            self.major.setText("" if cfg["major"] is None else str(cfg["major"]))
            self.minor.setText("" if cfg["minor"] is None else str(cfg["minor"]))
            self.expression.setText(cfg.get("display_transform",{}).get("expression",cfg.get("expression", "")))
            self.direction_buttons[cfg["direction"]].setChecked(True)
            for side, box in self.borders.items():
                box.setChecked(self.plot.presentation.frame[side])
            for key, boxes in (
                (self.horizontal, self.range.boxes()[:2]),
                (self.vertical, self.range.boxes()[2:]),
            ):
                for suffix, box in zip(("min", "max"), boxes, strict=True):
                    value = getattr(self.holder(key), key + "_" + suffix)
                    box.setText("" if value is None else str(value))
            self.range.x_label.setText(self.axis_name(self.horizontal))
            self.range.y_label.setText(self.axis_name(self.vertical))
        finally:
            self.loading = False
        self.explain()
        self.sync_text()
        from tailor.axis_shared_controls import sync
        sync(self)

    def explain(self):
        auto = self.notation.currentData() == "auto"
        self.precision_label.setText("小数位数" if getattr(getattr(self,"tick_pair",None),"quantity_mode",False) else "有效位数" if auto else "小数位数")
        with QtCore.QSignalBlocker(self.precision):
            self.precision.setMinimum(1 if auto else 0)
        self.major.setToolTip(
            "对数轴间隔 1：1、10、100；0.5：半个数量级。"
            if self.scale.currentData()
            else "相邻主刻度的数值差。例如 10：0、10、20。"
        )
        self.minor_count.setToolTip("每两个相邻主刻度之间插入的短刻度数量。")
        self.direction_buttons[self.direction.currentData()].setChecked(True)
        self.minor_count.setEnabled(
            self.minor_visible.isChecked() and not self.minor.text().strip()
        )
        self.minor.setEnabled(self.minor_visible.isChecked())
        self.minor_length.setEnabled(self.minor_visible.isChecked())

    def sync_text(self, *args):
        if self.loading:
            return
        from tailor.text_style_controls import font_spec

        kind = self.text_target.currentData()
        key = self.current + "_" + kind
        self.current_label.setText(
            self.axis_name(self.current) + ("标题" if kind == "label" else "刻度文字")
        )
        self.title_visible.setVisible(True)
        text = (
            getattr(self.holder(self.current), self.current + "_label")
            if kind == "label"
            else None
        )
        selected=getattr(self,'selected_tick',None)
        if kind=='ticks' and selected and selected[0]==self.current:
            from tailor.axis_text import token
            text=self.plot.presentation.axes[self.current].get('tick_text',{}).get(token(selected[1]),selected[2])
        self.text_editor.setProperty('wholeTargetFont',kind=='ticks')
        self.text_editor.load(font_spec(self.plot.curve_style, key), text)

    def apply_text(self):
        if self.loading:
            return
        from tailor.text_style_controls import apply_text_styles, record_view_edit

        kind = self.text_target.currentData()
        axis = self.current
        key = axis + "_" + kind
        import copy
        before = (getattr(self.holder(axis), axis + "_label"),self.plot.curve_style,
                  copy.deepcopy(self.plot.presentation.axes[axis].get('tick_text',{})))
        selected=getattr(self,'selected_tick',None)
        if kind=='ticks' and selected and selected[0]==axis and self.text_editor.content.isEnabled():
            from tailor.axis_text import token
            self.plot.presentation.axes[axis].setdefault('tick_text',{})[token(selected[1])]=self.text_editor.content.text()
        if kind == "label":
            setattr(
                self.holder(self.current),
                self.current + "_label",
                self.text_editor.content.text(),
            )
        self.plot.curve_style = replace(
            self.plot.curve_style,
            text_styles={
                **self.plot.curve_style.text_styles,
                key: self.text_editor.spec(),
            },
        )
        if kind == "label":
            from tailor.column_titles import axis_changed

            axis_changed(self.plot, axis, self.text_editor.content.text(), record=False)
        apply_text_styles(self.plot)
        after = (getattr(self.holder(axis), axis + "_label"),self.plot.curve_style,
                 copy.deepcopy(self.plot.presentation.axes[axis].get('tick_text',{})))
        native=self.plot.ui.plot_widget.getAxis({'x':'bottom','top':'top','y':'left','right':'right'}[axis])
        native.picture=None;native.update()

        def restore(plot, state):
            holder = plot.presentation if axis in {"top", "right"} else plot.model
            setattr(holder, axis + "_label", state[0])
            plot.curve_style = state[1]
            plot.presentation.axes[axis]['tick_text']=copy.deepcopy(state[2])
            native.picture=None;native.update()
            if kind == "label":
                from tailor.column_titles import axis_changed

                axis_changed(plot, axis, state[0], record=False)
            apply_text_styles(plot)
            plot.axis_controls.sync_text()

        record_view_edit(self.plot, "坐标轴文字", before, after, restore)
        self.plot.main_window.mark_project_dirty()

    def auto_range(self):
        boxes = (
            self.range.boxes()[:2]
            if self.current in {"x", "top"}
            else self.range.boxes()[2:]
        )
        for box in boxes:
            box.clear()
        self.apply_ranges()

    def after_crop(self):
        for box in self.range.boxes():
            box.clear()
        self.apply_ranges()

    def precision_changed(self,*_):
        if self.loading:return
        self._pending_precision_follow=False
        self.apply()

    def apply_ranges(self):
        self.apply(include_ranges=True)

    def apply(self, *args, include_ranges=False):
        if self.loading:
            return
        plot, p = self.plot, self.plot.presentation
        before = p.to_dict()
        model_state = {
            k: getattr(plot.model, k) for k in ("x_min", "x_max", "y_min", "y_max")
        }
        try:
            cfg = copy.deepcopy(p.axes[self.current])
            for name in (
                "inverted",
                "major_visible",
                "minor_visible",
                "grid",
                "minor_grid",
            ):
                cfg[name] = getattr(self, name).isChecked()
            for name in (
                "precision",
                "minor_count",
                "tick_length",
                "minor_length",
                "axis_width",
                "grid_width",
                "grid_count",
                "minor_grid_count",
            ):
                cfg[name] = getattr(self, name).value()
            pending = getattr(self, '_pending_display', None)
            if pending is not None:
                del self._pending_display
                key, enabled = pending
                if not cfg['visible'] and enabled:
                    # Inactive legacy axes retain enabled defaults internally.
                    # Activating one display item must not reveal the other three.
                    if max(cfg['tick_length'], cfg['minor_length']) > 0:
                        cfg['saved_tick_lengths'] = [cfg['tick_length'], cfg['minor_length']]
                    cfg.update(line_visible=False, labels=False, title_visible=False,
                               ticks_visible=False, tick_length=0, minor_length=0)
                cfg[key] = enabled
                cfg['visible'] = cfg['visible'] or enabled
                if key == 'ticks_visible':
                    if not enabled:
                        cfg['saved_tick_lengths'] = [cfg['tick_length'], cfg['minor_length']]
                        cfg['tick_length'] = cfg['minor_length'] = 0
                    elif max(cfg['tick_length'], cfg['minor_length']) <= 0:
                        saved = cfg.get('saved_tick_lengths', [5, 3])
                        if (not isinstance(saved, (list, tuple)) or len(saved) != 2
                                or not all(isinstance(v, (int, float)) and 0 <= v <= 30 for v in saved)
                                or max(saved) <= 0):
                            saved = [5, 3]
                        cfg['tick_length'], cfg['minor_length'] = saved
            elif any(cfg[k] != p.axes[self.current][k] for k in ('tick_length', 'minor_length')):
                cfg['ticks_visible'] = max(cfg['tick_length'], cfg['minor_length']) > 0
            for name in ("direction", "notation", "grid_style"):
                cfg[name] = getattr(self, name).currentData()
            for name in ("color", "grid_color", "prefix", "suffix"):
                cfg[name] = getattr(self, name).text()
            cfg.update(
                log=self.scale.currentData(),
                major=float(self.major.text()) if self.major.text().strip() else None,
                minor=float(self.minor.text()) if self.minor.text().strip() else None,
                expression=cfg.get('expression',''),
                divisor=float(self.divisor.text()),
            )
            if hasattr(self,'_pending_major_count'):
                cfg['major_count']=self._pending_major_count
                del self._pending_major_count
            if hasattr(self,'_pending_custom_interval'):
                cfg['custom_interval_value']=self._pending_custom_interval
                del self._pending_custom_interval
            if hasattr(self, "_pending_minor_auto"):
                cfg["minor_auto"] = self._pending_minor_auto
                del self._pending_minor_auto
            if hasattr(self,'_pending_precision_follow'):
                cfg['precision_follow_interval']=self._pending_precision_follow
                del self._pending_precision_follow
                if cfg['precision_follow_interval'] and not cfg['log']:
                    from tailor.axis_tick_policy import auto_spacing,label_precision,numeric_spacing,current_bounds
                    from tailor.axis_tick_policy import major_spacing
                    spacing=major_spacing(cfg,*current_bounds(self))
                    cfg['precision']=label_precision(cfg,numeric_spacing(cfg,spacing),current_bounds(self)[1])
                    with QtCore.QSignalBlocker(self.precision):self.precision.setValue(cfg['precision'])
            p.validate_axis(cfg)
            p.axes[self.current].update(cfg)
            p.frame.update(
                {side: box.isChecked() for side, box in self.borders.items()}
            )
            if include_ranges:
                values = self.range.bounds(False)
                for key, bounds in (
                    (self.horizontal, values[:2]),
                    (self.vertical, values[2:]),
                ):
                    for suffix, value in zip(("min", "max"), bounds, strict=True):
                        setattr(self.holder(key), key + "_" + suffix, value)
                        if not p.multi and not (
                            getattr(plot, "advanced_view", None)
                            and plot.advanced_view.cfg["kind"] == "3d"
                            and key in {"right", "top"}
                        ):
                            setattr(
                                plot.model,
                                ("x" if key in {"x", "top"} else "y") + "_" + suffix,
                                value,
                            )
            redraw=include_ranges or cfg['log']!=before['axes'][self.current]['log']
            if redraw:
                plot.all_limits() if p.multi else p.single_limits()
                plot._clear_remembered_zoom()
                if p.multi:plot.draw_plot()
                else:
                    plot.update_plot();plot.update_limits();p.apply_axes()
            else:
                # Formatting/visibility never resets a user's viewport or
                # recomputes bounds from untransformed source data (bar stacks).
                p.apply_axes()
            inset=getattr(plot,'_inset_extras',None)
            if inset is not None:
                if include_ranges:
                    inset.sync_inset_range()
                else:
                    inset.apply_inset_range()
            from tailor.text_style_controls import apply_text_styles

            apply_text_styles(plot)
            plot.main_window.mark_project_dirty()
            self.sync_display(cfg)
            self.message.hide()
            self.explain()
            from tailor.text_style_controls import record_view_edit
            after = p.to_dict()
            after_model = {k: getattr(plot.model, k) for k in model_state}
            def restore(target, state):
                graph, bounds = state
                target.presentation.load(graph)
                for key, value in bounds.items():
                    setattr(target.model, key, value)
                if redraw:target.refresh_ui()
                else:target.presentation.apply_axes()
                inset=getattr(target,'_inset_extras',None)
                if inset is not None:inset.apply_inset_range()
                target.axis_controls.sync()
            record_view_edit(plot, "坐标轴设置", (before, model_state), (after, after_model), restore)
        except (ValueError, OverflowError) as error:
            p.load(before)
            for key, value in model_state.items():
                setattr(plot.model, key, value)
            self.sync()
            self.message.setText(str(error))
            self.message.show()

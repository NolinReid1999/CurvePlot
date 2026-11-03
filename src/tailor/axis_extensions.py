"""Native axis adapters: categorical/date/custom ticks and display-only breaks.

Date tick spacing reuses pyqtgraph DateAxisItem. Breaks wrap PlotDataItem's display
mapping, preserving its original arrays and the existing table/fitting engine.
"""

import types

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from tailor.compact_controls import RichTextEdit, toggle_button
from tailor.graph_controls import combo, number, row


def convert_series(values, mode):
    values = pd.Series(values)
    # Numeric instrument columns cannot contain whitespace. Regex replacement
    # copies their full arrays on every source/range/fit refresh.
    if not pd.api.types.is_numeric_dtype(values):
        values=values.replace(r"^\s*$",np.nan,regex=True)
    if mode == "category":
        codes, labels = pd.factorize(values, sort=False)
        return pd.Series(np.where(codes >= 0, codes + 1, np.nan), index=values.index), [
            str(v) for v in labels
        ]
    if mode == "datetime" and not pd.api.types.is_numeric_dtype(values):
        dates = pd.to_datetime(values, errors="coerce", utc=True)
        return pd.Series(
            np.where(dates.notna(), dates.astype("int64") / 1e9, np.nan),
            index=values.index,
        ), []
    return values, []


def break_limits(cfg):
    low, high = cfg.get("break_low", 1.0), cfg.get("break_high", 2.0)
    if cfg.get("log"):
        low, high = np.log10([low, high])
    span = cfg.get("break_reference_span", high - low)
    return low, high, span * cfg.get("break_ratio", 0.06)


def map_break(values, cfg, inverse=False):
    values = np.asarray(values, dtype=float)
    if not cfg.get("break_enabled"):
        return values
    low, high, gap = break_limits(cfg)
    removed = high - low - gap
    if inverse:
        return np.where(
            values >= low + gap,
            values + removed,
            np.where(values > low, np.nan, values),
        )
    return np.where(
        values >= high, values - removed, np.where(values > low, np.nan, values)
    )


def special_ticks(axis, low, high, size):
    cfg = axis.settings
    from tailor.graph_presentation import display, physical

    custom = cfg.get("custom_ticks", [])
    if custom:
        vals = display([p[0] for p in custom], cfg)
        return [(1, [float(v) for v in vals if np.isfinite(v) and low <= v <= high])]
    if cfg.get("axis_type") == "category":
        vals = display(np.arange(1, len(cfg.get("category_labels", [])) + 1), cfg)
        visible = [float(v) for v in vals if np.isfinite(v) and low <= v <= high]
        if cfg.get('major'):
            from tailor.axis_tick_policy import linear_ticks
            ticks=display(linear_ticks(*physical([low,high],cfg),cfg['major']),cfg)
            return [(cfg['major'],[float(v) for v in ticks if np.isfinite(v)])]
        stride = max(1,round(len(visible)/max(2,cfg.get('major_count',5))),
                     int(np.ceil(len(visible) / max(1, size / 65))))
        return [(stride, visible[::stride])]
    if cfg.get("axis_type") == "datetime":
        if not hasattr(axis, "_date_axis"):
            axis._date_axis = pg.DateAxisItem(orientation=axis.orientation,utcOffset=0)
        date=axis._date_axis
        metrics=QtGui.QFontMetrics(axis.style.get('tickFont') or QtWidgets.QApplication.font())
        date.fontMetrics=metrics
        a,b=physical([low,high],cfg)
        # DateAxisItem's example format can be shorter than the user's Qt
        # format. Feed its native calendar locator spacing based on that real
        # caption and logical width, avoiding a whole detail layer being culled.
        extent=axis.width() if axis.orientation in {'bottom','top'} else axis.height()
        logical=max(20,min(size,extent))
        density=(b-a)/logical
        sample=QtCore.QDateTime.fromSecsSinceEpoch(round((a+b)/2),QtCore.QTimeZone.UTC).toString(cfg.get('date_format','yyyy-MM-dd'))
        pixels=metrics.horizontalAdvance(sample) if axis.orientation in {'bottom','top'} else metrics.height()
        date.setZoomLevelForDensity(density)
        date.minSpacing=max(date.minSpacing,density*(pixels+10)*1.5)
        if cfg.get('major'):
            from tailor.axis_tick_policy import linear_ticks
            return [(cfg['major'],[float(v) for v in display(linear_ticks(a,b,cfg['major']),cfg) if np.isfinite(v)])]
        # TickSpec skips at equality, so an exact 15-minute target otherwise
        # jumps to 50 minutes. Keep its calendar steps, accepting equality.
        target=(b-a)/max(1,cfg.get('major_count',5)-1)
        date.minSpacing=max(date.minSpacing,np.nextafter(target,0.))
        levels=date.zoomLevel.tickValues(a,b,minSpc=date.minSpacing)
        if not cfg.get("break_enabled"):
            return levels
        return [
            (spacing, [float(v) for v in display(vals, cfg) if np.isfinite(v)])
            for spacing, vals in levels
        ]
    if cfg.get("break_enabled"):
        from tailor.axis_tick_policy import linear_ticks
        a,b=sorted(physical([low,high],cfg))
        if not np.isfinite([a,b]).all():return []
        limits=[(a,min(b,cfg['break_low'])),(max(a,cfg['break_high']),b)]
        bounds=np.log10([a,b]) if cfg.get('log') else [a,b]
        spacing=cfg.get('major')
        if spacing is None:
            from tailor.axis_tick_policy import major_spacing
            spacing=major_spacing(cfg,*bounds)
        count=cfg['minor_count'] if cfg.get('minor_visible') else 0
        minor=(cfg.get('minor') or spacing/(count+1)) if count or cfg.get('minor') else None
        result=[]
        for step in (spacing,minor):
            if step is None:continue
            values=[]
            for lo,hi in limits:
                if lo>hi:continue
                segment=np.log10([lo,hi]) if cfg.get('log') else [lo,hi]
                values.extend(linear_ticks(*segment,step,budget=250))
            values=np.unique(values)
            if result:values=values[~np.isclose(values/spacing,np.rint(values/spacing),atol=1e-8,rtol=0)]
            mapped=map_break(values,cfg)
            result.append((step,[float(v) for v in mapped if np.isfinite(v)]))
        return result
    return None


def special_string(axis, value):
    cfg = axis.settings
    if cfg.get("custom_ticks"):
        return next(
            (
                str(label)
                for position, label in cfg["custom_ticks"]
                if np.isclose(position, value, rtol=1e-10, atol=1e-10)
            ),
            "",
        )
    if cfg.get("axis_type") == "category":
        labels = cfg.get("category_labels", [])
        i = round(value) - 1
        return (
            labels[i]
            if abs(value - round(value)) < 1e-7 and 0 <= i < len(labels)
            else ""
        )
    if cfg.get("axis_type") == "datetime":
        return QtCore.QDateTime.fromSecsSinceEpoch(
            round(value), QtCore.QTimeZone.UTC
        ).toString(cfg.get("date_format", "yyyy-MM-dd"))
    return None


def wrap_display_items(presentation, additional=None):
    from pyqtgraph.graphicsItems.PlotDataItem import PlotDataset

    boxes = {presentation.owner.ui.plot_widget.getViewBox(): ("x", "y")}
    for attr, keys in [
        ("right_box", ("x", "right")),
        ("top_box", ("top", "y")),
        ("top_right_box", ("top", "right")),
    ]:
        box = getattr(presentation, attr)
        if box is not None:
            boxes[box] = keys
    if additional is not None:
        boxes = additional
    for box, keys in boxes.items():
        for item in box.addedItems:
            if not isinstance(item, pg.PlotDataItem):
                continue
            item._curve_axis_keys = keys
            if not hasattr(item, "_curve_native_display"):
                item._curve_native_display = item._getDisplayDataset

                def dataset(this):
                    native = this._curve_native_display()
                    kx, ky = this._curve_axis_keys
                    cx, cy = presentation.axes[kx], presentation.axes[ky]
                    if native is None or not (
                        cx.get("break_enabled") or cy.get("break_enabled")
                    ):
                        return native
                    token = (
                        id(native),
                        tuple(
                            (
                                c.get("break_enabled"),
                                c.get("break_low"),
                                c.get("break_high"),
                                c.get("break_ratio"),
                                c.get("log"),
                            )
                            for c in (cx, cy)
                        ),
                    )
                    if getattr(this, "_curve_break_token", None) != token:
                        xx, yy = map_break(native.x, cx), map_break(native.y, cy)
                        connect = np.ones(len(xx), dtype=bool)
                        for values, cfg in ((native.x, cx), (native.y, cy)):
                            if cfg.get("break_enabled"):
                                low, high, _ = break_limits(cfg)
                                connect[:-1] &= ~(
                                    ((values[:-1] <= low) & (values[1:] >= high))
                                    | ((values[:-1] >= high) & (values[1:] <= low))
                                )
                        connect[:-1] &= (
                            np.isfinite(xx[:-1])
                            & np.isfinite(xx[1:])
                            & np.isfinite(yy[:-1])
                            & np.isfinite(yy[1:])
                        )
                        this._curve_break_dataset = PlotDataset(
                            xx, yy, False, False, connect
                        )
                        this._curve_break_token = token
                    return this._curve_break_dataset

                item._getDisplayDataset = types.MethodType(dataset, item)
            item._curve_break_token = None
            if not hasattr(item, "_curve_break_clip"):
                item._curve_break_clip = item.opts.get("clipToView", False)
            if any(presentation.axes[k].get("break_enabled") for k in keys):
                item.setClipToView(False)
                item.setDownsampling(auto=True, method="peak")
                item.opts["connect"] = "finite"
            else:
                item.setClipToView(item._curve_break_clip)
            item.updateItems(styleUpdate=False)


class AdvancedAxes(QtCore.QObject):
    def __init__(self, control):
        super().__init__(control)
        self.control = control
        self.plot = control.plot
        self.loading = False
        self.apply_timer = QtCore.QTimer(self)
        self.apply_timer.setSingleShot(True)
        self.apply_timer.setInterval(16)
        self._dragging = False
        self._drag_before = None
        self.apply_timer.timeout.connect(self.apply)
        self.mode = combo(
            [("数值", "numeric"), ("分类", "category"), ("日期/时间", "datetime")]
        )
        self.date = combo(
            [
                ("日期", "yyyy-MM-dd"),
                ("时间", "HH:mm:ss"),
                ("日期与时间", "yyyy-MM-dd HH:mm"),
            ]
        )
        self.labels = RichTextEdit()
        self.labels.setPlaceholderText("分类标签：一行一个；留空采用数据列内容")
        self.ticks = RichTextEdit()
        self.ticks.setPlaceholderText("自定义刻度：位置=文字，一行一个；留空自动")
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(row("坐标类型", self.mode))
        self.date_row = row("时间格式", self.date)
        self.date.setMinimumWidth(0)
        self.date.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
        layout.addWidget(self.date_row)
        layout.addWidget(self.labels)
        layout.addWidget(self.ticks)
        control.add_section("坐标类型与自定义刻度", layout)
        self.enabled = toggle_button("显示断轴")
        self.low = number(-1e12, 1e12, 1, 3)
        self.high = number(-1e12, 1e12, 2, 3)
        self.ratio = number(0.001, 0.5, 0.06, 3)
        self.ratio.setSingleStep(0.001)
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.enabled)
        layout.addWidget(row("断轴起点", self.low))
        layout.addWidget(row("断轴终点", self.high))
        layout.addWidget(row("间隙比例", self.ratio))
        control.add_section("断轴", layout)
        for widget in (self.mode, self.date):
            widget.activated.connect(self.apply)
        for widget in (self.labels, self.ticks):
            widget.editingFinished.connect(self.apply)
        for widget in (self.low, self.high, self.ratio):
            widget.valueChanged.connect(self.queue_apply)
            slider = widget.parentWidget().slider
            slider.sliderPressed.connect(self.start_drag)
            slider.sliderReleased.connect(self.finish_drag)
        self.enabled.clicked.connect(self.toggle_break)
        control.axis_group.buttonClicked.connect(lambda *args: self.sync())
        self.domain_timer=QtCore.QTimer(self);self.domain_timer.setSingleShot(True)
        self.domain_timer.setInterval(20);self.domain_timer.timeout.connect(self.refresh_domain)
        self._domain_boxes=set()
        self.sync()

    def sync(self):
        self.loading = True
        cfg = self.plot.presentation.axes[self.control.current]
        self.mode.setCurrentIndex(
            max(0, self.mode.findData(cfg.get("axis_type", "numeric")))
        )
        self.date.setCurrentIndex(
            max(0, self.date.findData(cfg.get("date_format", "yyyy-MM-dd")))
        )
        self.labels.load_plain_text("\n".join(cfg.get("category_custom", [])))
        self.ticks.load_plain_text(
            "\n".join(f"{p}={label}" for p, label in cfg.get("custom_ticks", []))
        )
        self.enabled.setChecked(cfg.get("break_enabled", False))
        self.refresh_domain()
        self.low.setValue(cfg.get("break_low", 1))
        self.high.setValue(cfg.get("break_high", 2))
        self.ratio.setValue(cfg.get("break_ratio", 0.06))
        self.loading = False
        self.control.scale.setEnabled(self.mode.currentData() == "numeric")
        self.date.setVisible(True)
        self.date.setEnabled(self.mode.currentData() == "datetime")
        self.labels.setVisible(self.mode.currentData() == "category")

    def queue_apply(self, *args):
        if self._dragging and self.enabled.isChecked() and self.low.value() >= self.high.value():
            pair = getattr(self.control, 'break_pair', None)
            low_active = pair.current == 0 if pair is not None else self.low.parentWidget().slider.isSliderDown()
            field = self.low if low_active else self.high
            limit = self.high.value() - self.low.singleStep() if low_active else self.low.value() + self.high.singleStep()
            with QtCore.QSignalBlocker(field):
                field.setValue(limit)
            field.parentWidget().sync_value()
        if not self.loading and not self.apply_timer.isActive():
            self.apply_timer.start()

    def start_drag(self):
        import copy

        self._dragging = True
        self._drag_before = copy.deepcopy(self.plot.presentation.to_dict())

    def finish_drag(self):
        self.apply_timer.stop()
        self._dragging = False
        self.apply()
        self._drag_before = None
        self.domain_timer.start()

    def toggle_break(self, *args):
        if self.enabled.isChecked():
            self.match_bounds()
        self.apply_timer.stop()
        self.apply()

    def visible_domain(self):
        from tailor.graph_presentation import physical
        key=self.control.current
        cfg=self.plot.presentation.axes[key]
        box=self.plot.ui.plot_widget.getViewBox()
        if key in {'top','right'}:
            box=getattr(self.plot.presentation,'top_box' if key=='top' else 'right_box',None) or box
        if box not in self._domain_boxes:
            box.sigRangeChanged.connect(self.queue_domain)
            self._domain_boxes.add(box)
        values=physical(box.viewRange()[0 if key in {'x','top'} else 1],cfg)
        low,high=sorted(values)
        if not np.isfinite(values).all() or high<=low or (cfg['log'] and low<=0):return None
        return float(low),float(high),bool(cfg['log'])

    def queue_domain(self,*args):
        if not self._dragging and not self.domain_timer.isActive():self.domain_timer.start()

    def refresh_domain(self):
        if getattr(self.plot,'_graph_disposed',False) or self._dragging:return
        domain=self.visible_domain()
        if domain is None:return
        low,high,log=domain
        cfg=self.plot.presentation.axes[self.control.current]
        # The input can retain a saved endpoint outside the visible viewport;
        # the slider itself always maps exactly to the current visible range.
        for field,name,default in ((self.low,'break_low',1),(self.high,'break_high',2)):
            saved=cfg.get(name,default)
            with QtCore.QSignalBlocker(field):
                field.setRange(min(low,saved,field.value()),max(high,saved,field.value()))
                field.setSingleStep(max((high-low)/1000,1e-12))
            field._slider_domain=domain
            parent=field.parentWidget()
            if hasattr(parent,'sync_value'):parent.sync_value()
        pair=getattr(self.control,'break_pair',None)
        if pair:pair.sync()

    def match_bounds(self):
        domain=self.visible_domain()
        if domain is None:return
        low,high,log=domain
        cfg=self.plot.presentation.axes[self.control.current]
        cfg['break_reference_span']=float(np.log10(high)-np.log10(low) if log else high-low)
        self.refresh_domain()
        if 'break_low' not in cfg:
            with QtCore.QSignalBlocker(self.low),QtCore.QSignalBlocker(self.high):
                self.low.setValue(low+(high-low)*.4)
                self.high.setValue(low+(high-low)*.6)
        pair=getattr(self.control,'break_pair',None)
        if pair:pair.sync()

    def physical_ranges(self):
        from tailor.graph_presentation import physical

        pres = self.plot.presentation
        result = []
        boxes = [(self.plot.ui.plot_widget.getViewBox(), ("x", "y"))]
        if pres.multi:
            boxes += [
                (getattr(pres, name), keys)
                for name, keys in (
                    ("right_box", ("x", "right")),
                    ("top_box", ("top", "y")),
                    ("top_right_box", ("top", "right")),
                )
                if getattr(pres, name) is not None
            ]
        for box, keys in boxes:
            result.append(
                (
                    box,
                    keys,
                    [physical(v, pres.axes[k]) for v, k in zip(box.viewRange(), keys)],
                )
            )
        return result

    def refresh_break(self, ranges):
        from tailor.graph_presentation import AXES, display

        pres = self.plot.presentation
        if not pres.multi:
            pres.apply_single_sides()
        # Keep source bounds and all unrelated fonts, legends and fit results intact.
        wrap_display_items(pres)
        self.plot._block_range_signal = True
        try:
            for box, keys, values in ranges:
                x, y = [display(v, pres.axes[k]) for v, k in zip(values, keys)]
                if np.isfinite(x).all() and np.isfinite(y).all():
                    box.setRange(xRange=x, yRange=y, padding=0, disableAutoRange=True)
        finally:
            self.plot._block_range_signal = False
        for key, side in AXES.items():
            axis = self.plot.ui.plot_widget.getAxis(side)
            axis.settings = pres.axes[key]
            axis.picture = None
            axis.update()
        pres.grid_item.update()

    def apply(self, *args):
        import shiboken6
        if not shiboken6.isValid(self.plot.main_window):
            return
        widget=self.plot.ui.plot_widget
        item=getattr(widget,'plotItem',None)
        if (self.loading or getattr(self.plot,'_graph_disposed',False)
                or not shiboken6.isValid(widget) or item is None or not shiboken6.isValid(item)):
            return
        try:
            import copy

            before = copy.deepcopy(self.plot.presentation.to_dict())
            # Older/default axis dictionaries omit these optional fields.
            # A merge-style presentation restore must still undo the first
            # explicit break/category edit back to its actual default state.
            edited = self.control.current
            affected = [edited]
            if not self.plot.presentation.multi and edited in {'x', 'y'}:
                alternate = {'x': 'top', 'y': 'right'}[edited]
                if self.plot.presentation.single_sides[edited] == alternate:
                    affected.append(alternate)
            defaults = dict(axis_type='numeric',date_format='yyyy-MM-dd',
                    category_custom=[],custom_ticks=[],break_enabled=False,
                    break_low=1.,break_high=2.,break_ratio=.06)
            for side in affected:
                for key,value in defaults.items():
                    before['axes'][side].setdefault(key,value)
            ranges = self.physical_ranges()
            for side in ("bottom", "left", "top", "right"):
                self.plot.ui.plot_widget.getAxis(side).prepareGeometryChange()
            cfg = self.plot.presentation.axes[self.control.current]
            old_mode = cfg.get("axis_type", "numeric")
            low, high = self.low.value(), self.high.value()
            if self.enabled.isChecked() and (low >= high or (cfg["log"] and low <= 0)):
                raise ValueError("断轴起点须小于终点；对数轴断轴范围须为正。")
            ticks = []
            for text in self.ticks.toPlainText().splitlines():
                if not text.strip():
                    continue
                position, label = text.split("=", 1)
                position = float(position)
                if not np.isfinite(position):
                    raise ValueError("刻度位置须为有限数字")
                ticks.append([position, label])
            if len(ticks) > 1000:
                raise ValueError("自定义刻度最多1000个")
            cfg.update(
                axis_type=self.mode.currentData(),
                date_format=self.date.currentData(),
                category_custom=self.labels.toPlainText().splitlines(),
                custom_ticks=ticks,
                break_enabled=self.enabled.isChecked(),
                break_low=low,
                break_high=high,
                break_ratio=self.ratio.value(),
            )
            if self.mode.currentData() != "numeric":
                cfg["log"] = False
            self.plot.presentation.validate_axis(cfg)
            if not self.plot.presentation.multi:
                # A single curve uses the alternate side as its transform
                # authority. Update that authority before it mirrors back to
                # the logical source axis; otherwise it erases this edit.
                for side in affected[1:]:
                    for field in (*defaults, 'log'):
                        self.plot.presentation.axes[side][field] = cfg[field]
                self.plot.presentation.apply_single_sides()
            # Axis types apply to source coordinates before rendering, never to stored cells.
            sources = (
                list(self.plot.model._plots)
                if self.plot.presentation.multi
                else [self.plot]
            )
            for source in sources:
                if self.plot.presentation.multi and getattr(self.plot, '_inset_parent', None) is not None:
                    # Inset sources are shared with the main graph. Its own
                    # renderer applies local modes without mutating them.
                    continue
                info = (
                    self.plot.model.get_plot_info(source)
                    if self.plot.presentation.multi
                    else None
                )
                xkey = "top" if info and info.x_axis == "top" else "x"
                ykey = "right" if info and info.axis == "right" else "y"
                source.model._axis_modes = {
                    "x": self.plot.presentation.axes[xkey].get("axis_type", "numeric"),
                    "y": self.plot.presentation.axes[ykey].get("axis_type", "numeric"),
                }
            if old_mode != cfg["axis_type"]:
                self.plot.draw_plot() if self.plot.presentation.multi else self.plot.update_plot()
            else:
                self.refresh_break(ranges)
            if old_mode != cfg["axis_type"]:
                self.plot._clear_remembered_zoom()
                self.plot.update_limits()
            from tailor.text_style_controls import record_view_edit

            def restore(plot, state):
                plot.presentation.load(state)
                plot.refresh_ui()
                plot.axis_controls.advanced.sync()

            if not self._dragging:
                record_view_edit(
                    self.plot,
                    "坐标类型与断轴",
                    self._drag_before if self._drag_before is not None else before,
                    copy.deepcopy(self.plot.presentation.to_dict()),
                    restore,
                )
                self.plot.main_window.mark_project_dirty()
                self.sync()
        except (ValueError, TypeError) as error:
            self.plot.main_window.statusBar().showMessage(str(error))

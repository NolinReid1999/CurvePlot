"""Translate the shared axis inspector settings to Matplotlib's native XYZ axes."""

import numpy as np
from matplotlib import ticker
from matplotlib.font_manager import FontProperties
from PySide6 import QtGui

from tailor.appearance import ink
from tailor.axis_format import format_tick
from tailor.text_style_controls import font_spec
from tailor.tick_expression import calculate

NAMES = {"x": "X轴", "y": "Y轴", "right": "Z轴", "top": "色标"}


def plain(value,spec=None):
    from tailor.text_layout import mpl_text
    return mpl_text(value,spec)


def format_value(cfg, value, spec=None):
    from tailor.axis_text import token
    override=cfg.get('tick_text',{}).get(token(value))
    if override is not None:return plain(override,spec)
    custom = cfg.get("custom_ticks", [])
    for x, label in custom:
        if np.isclose(x, value):
            return label
    number = (
        calculate(cfg["expression"], value)
        if cfg.get("expression")
        else value / cfg.get("divisor", 1)
    )
    return (
        cfg.get("prefix", "")
        + format_tick(number, cfg["notation"], cfg["precision"])
        + cfg.get("suffix", "")
    )


def interval_locator(axis, spacing):
    """Bound only the rendered tick sample, preserving the saved interval."""
    low,high=sorted(axis.get_view_interval())
    if (high-low)/spacing>500:
        from tailor.axis_tick_policy import linear_ticks
        return ticker.FixedLocator(linear_ticks(low,high,spacing))
    return ticker.MultipleLocator(spacing)


def apply(view):
    p, plot, ax = view.plot.presentation, view.plot, view.ax
    for key, axis, dim in (
        ("x", ax.xaxis, "x"),
        ("y", ax.yaxis, "y"),
        ("right", ax.zaxis, "z"),
    ):
        cfg = p.axes[key]
        title = getattr(p if key == "right" else plot.model, key + "_label")
        spec = font_spec(plot.curve_style, key + "_label")
        tick = font_spec(plot.curve_style, key + "_ticks")
        axis.set_label_text(
            plain(title,spec) if cfg["title_visible"] else "",
            color=ink(spec["color"]),
            fontproperties=FontProperties(
                family=[spec["family"], "PingFang SC", "DejaVu Sans"],
                size=spec["size"],
                weight="bold" if spec["bold"] else "normal",
                style="italic" if spec["italic"] else "normal",
            ),
        )
        axis.labelpad = 8 + (cfg["tick_length"] if cfg["direction"] == "out" else 0)
        getattr(ax, "set_" + dim + "scale")("log" if cfg["log"] else "linear")
        holder = p if key == "right" else plot.model
        low, high = getattr(holder, key + "_min"), getattr(holder, key + "_max")
        if low is not None or high is not None:
            current = getattr(ax, "get_" + dim + "lim")()
            values = (
                low if low is not None else current[0],
                high if high is not None else current[1],
            )
            if values[0] >= values[1] or cfg["log"] and min(values) <= 0:
                raise ValueError("三维轴范围须递增，对数轴须为正。")
            getattr(ax, "set_" + dim + "lim")(*values)
        if cfg["inverted"]:
            getattr(ax, "invert_" + dim + "axis")()
        custom = cfg.get("custom_ticks", [])
        if custom:
            axis.set_major_locator(ticker.FixedLocator([v[0] for v in custom]))
        elif cfg.get("major"):
            axis.set_major_locator(
                ticker.LogLocator(base=10, subs=[1])
                if cfg["log"]
                else interval_locator(axis,cfg["major"])
            )
        else:
            if cfg['log']:
                axis.set_major_locator(ticker.LogLocator(base=10,numticks=cfg.get('major_count',5)))
            else:
                from tailor.axis_tick_policy import smart_ticks
                _,ticks=smart_ticks(*axis.get_view_interval(),cfg.get('major_count',5))
                axis.set_major_locator(ticker.FixedLocator(ticks))
        dense=bool(cfg.get("major") and not cfg["log"] and np.ptp(axis.get_view_interval())/cfg["major"]>500)
        if cfg.get("minor_visible") and not dense:
            axis.set_minor_locator(
                interval_locator(axis,cfg["minor"])
                if cfg.get("minor")
                else ticker.AutoMinorLocator(int(cfg["minor_count"]) + 1)
                if not cfg["log"]
                else ticker.LogLocator(base=10, subs=np.arange(2, 10))
            )
        else:
            axis.set_minor_locator(ticker.NullLocator())
        def label(value,pos,cfg=cfg,tick=tick,axis=axis):
            from tailor.axis_tick_policy import label_precision,numeric_spacing,display_format
            values=axis.get_majorticklocs();spacing=abs(values[1]-values[0]) if len(values)>1 else 1
            active=display_format(cfg,numeric_spacing(cfg,spacing,value))
            active['precision']=label_precision(active,numeric_spacing(cfg,spacing,value),value)
            return format_value(active,value,tick)
        axis.set_major_formatter(ticker.FuncFormatter(label))
        axis.line.set_color(ink(cfg["color"]))
        axis.line.set_linewidth(cfg["axis_width"])
        axis.line.set_visible(cfg["visible"])
        adapt_projected_ticks(axis,cfg)
        ax.tick_params(
            axis=dim,
            which="major",
            length=cfg["tick_length"] if cfg["major_visible"] else 0,
            width=cfg["axis_width"],
            direction=cfg["direction"],
            labelsize=tick["size"],
            colors=ink(tick["color"]),
        )
        ax.tick_params(
            axis=dim,
            which="minor",
            length=cfg["minor_length"] if cfg["minor_visible"] else 0,
            direction=cfg["direction"],
        )
        for label in axis.get_ticklabels():
            label.set_fontproperties(
                FontProperties(
                    family=[tick["family"], "PingFang SC", "DejaVu Sans"],
                    size=tick["size"],
                    weight="bold" if tick["bold"] else "normal",
                    style="italic" if tick["italic"] else "normal",
                )
            )
            from tailor.axis_text import effective_angle
            label.set_rotation(effective_angle(cfg))
            label.set_rotation_mode('anchor')
            label.set_visible(cfg["labels"] and cfg["visible"] and cfg["major_visible"])
            label.set_picker(True)
        axis.label.set_picker(True)
        axis._axinfo["grid"].update(
            color=ink(cfg["grid_color"]),
            linewidth=cfg["grid_width"] if cfg["grid"] else 0,
            linestyle={"solid": "-", "dash": "--", "dot": ":", "dashdot": "-."}.get(
                cfg["grid_style"], "-"
            ),
        )
    ax.grid(any(p.axes[k]["grid"] for k in ("x", "y", "right")))
    control = plot.axis_controls
    for key, button in control.axis_buttons.items():
        button.setText(NAMES[key])
    # Unsupported dimension-specific options are disabled individually.
    for widget in (control.minor_grid, control.minor_grid_count):
        widget.setEnabled(False)
        widget.setToolTip("三维后端不绘制独立次网格线；主网格可按X/Y/Z分别调整。")
    from tailor.axis_shared_controls import sync_backend_capabilities
    sync_backend_capabilities(control)
    control.advanced.enabled.setEnabled(False)
    control.advanced.mode.setEnabled(False)
    for record in plot.preferences.graph.sections:
        if record[1].property("sectionTitle") in {
            "添加标注",
            "选择数据点",
            "局部放大",
            "置信带与预测带",
        }:
            record[3].setEnabled(False)
    for i in range(plot.property_tabs.count()):
        if plot.property_tabs.tabText(i) == "拟合":
            plot.property_tabs.setTabEnabled(i, True)
            plot.property_tabs.widget(i).setEnabled(False)
            plot.property_tabs.setTabToolTip(
                i, "XYZ三维图不使用二维拟合；请对相应原始列建立二维图后拟合。"
            )


def apply_colorbar(view, bar):
    p = view.plot.presentation
    cfg = p.axes["top"]
    spec = font_spec(view.plot.curve_style, "top_label")
    tick = font_spec(view.plot.curve_style, "top_ticks")
    bar.set_label(
        plain(p.top_label,spec) if cfg["title_visible"] else "",
        fontsize=spec["size"],
        color=ink(spec["color"]),
    )
    bar.ax.tick_params(
        labelsize=tick["size"],
        colors=ink(tick["color"]),
        length=cfg["tick_length"] if cfg["visible"] and cfg["major_visible"] else 0,
        direction=cfg["direction"],
    )
    bar.formatter = ticker.FuncFormatter(lambda value, pos: format_value(cfg, value))
    bar.update_ticks()
    bar.outline.set_visible(cfg["visible"])
    bar.outline.set_edgecolor(ink(cfg["color"]))
    bar.outline.set_linewidth(cfg["axis_width"])
    for label in bar.ax.get_yticklabels():
        label.set_visible(cfg["labels"] and cfg["visible"] and cfg["major_visible"])


def adapt_projected_ticks(axis, cfg):
    """Use mplot3d's own projection, then apply the shared tick controls.

    Matplotlib 3.11 Axis._get_updated_ticks regenerates visible line geometry
    and ignores the usual marker length/direction. Keep its projection and
    labels; adjust only those returned tick artists (no global monkey patch).
    https://github.com/matplotlib/matplotlib/blob/v3.11.2/lib/mpl_toolkits/mplot3d/axis3d.py
    """
    axis._curve_tick_cfg=cfg
    if getattr(axis,'_curve_tick_adapter',False):return
    from types import MethodType
    from mpl_toolkits.mplot3d import proj3d
    def style_ticks(self,ticks,centers):
        settings=self._curve_tick_cfg
        trans=self.axes.transData;inverse=trans.inverted()
        center=np.asarray(proj3d.proj_transform(*centers,self.axes.M)[:2])
        center=trans.transform(center)
        info=self._axinfo['tick'];outward=info['outward_factor'];inward=info['inward_factor']
        for tick in ticks:
            line=tick.tick1line
            xy=np.column_stack(line.get_data())
            if len(xy)!=2:continue
            base=(inward*xy[0]+outward*xy[1])/max(1e-12,inward+outward)
            base=trans.transform(base);vector=trans.transform(xy[0])-trans.transform(xy[1])
            norm=np.linalg.norm(vector)
            enabled=settings['major_visible'] if tick._major else settings['minor_visible']
            length=settings['tick_length'] if tick._major else settings['minor_length']
            line.set_visible(bool(settings['visible'] and enabled and length>0 and norm>1e-12))
            tick.tick2line.set_visible(False)
            tick.label1.set_visible(bool(tick._major and settings['labels'] and settings['visible'] and settings['major_visible']))
            tick.label2.set_visible(False)
            if norm<=1e-12:continue
            vector=vector/norm
            if np.dot(vector,center-base)<0:vector=-vector
            if settings['direction']=='out':vector=-vector
            pixels=length*getattr(self.get_figure().canvas,'device_pixel_ratio',1)
            coords=inverse.transform([base,base+vector*pixels])
            line.set_data(coords[:,0],coords[:,1]);line.set_color(ink(settings['color']))
        return ticks
    original=getattr(axis,'_get_updated_ticks',None)
    if original is not None:
        def update(self,edge,centers,deltas,highs,points,pos):
            return style_ticks(self,original(edge,centers,deltas,highs,points,pos),centers)
        axis._get_updated_ticks=MethodType(update,axis)
    else:
        # Older supported Matplotlib releases draw each Tick immediately after
        # projecting it. Apply the same artist-only adapter at that draw point.
        def bind(getter):
            def get_ticks(*args,**kwargs):
                ticks=getter(*args,**kwargs)
                for tick in ticks:
                    if getattr(tick,'_curve_draw_adapter',False):continue
                    draw=tick.draw
                    def draw_tick(renderer,tick=tick,draw=draw):
                        centers=[np.mean(native.get_transform().transform(native.get_view_interval()))
                                 for native in (axis.axes.xaxis,axis.axes.yaxis,axis.axes.zaxis)]
                        style_ticks(axis,[tick],centers)
                        return draw(renderer)
                    tick.draw=draw_tick;tick._curve_draw_adapter=True
                return ticks
            return get_ticks
        axis.get_major_ticks=bind(axis.get_major_ticks);axis.get_minor_ticks=bind(axis.get_minor_ticks)
    axis._curve_tick_adapter=True

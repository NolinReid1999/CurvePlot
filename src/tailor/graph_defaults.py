"""Opt-in defaults for new graphs, isolated from existing project presentation."""

from tailor.compact_controls import CheckButton

import copy
import json
import math
from dataclasses import asdict

from PySide6 import QtCore, QtWidgets

DEFAULT_LINE_WIDTH = 5.0

GROUPS = {
    "curve": (
        "绘图曲线",
        (
            "mode",
            "color",
            "line_width",
            "marker_size",
            "marker",
            "line_style",
            "opacity",
            "cap",
            "join",
            "fill",
            "fill_color",
            "marker_fill",
            "marker_step",
            "step_mode",
        ),
    ),
    "fonts": ("绘图文字", ("font_size", "font_family", "text_styles")),
    "margins": ("图形边距", ()),
    "points": ("选择数据点", ()),
    "axes": ("四轴显示", ("visible", "title_visible", "labels", "line_visible",
                         "ticks_visible", "saved_tick_lengths", "axis_width", "color")),
    "ticks": (
        "主次刻度",
        (
            "major",
            "major_count",
            "custom_interval_value",
            "minor",
            "major_visible",
            "minor_visible",
            "minor_count",
            "minor_auto",
            "tick_length",
            "minor_length",
            "direction",
        ),
    ),
    "format": (
        "刻度格式",
        ("notation", "precision", "precision_follow_interval", "divisor", "expression", "prefix", "suffix", "tick_angle"),
    ),
    "grid": (
        "网格",
        (
            "grid",
            "minor_grid",
            "grid_count",
            "minor_grid_count",
            "grid_color",
            "grid_width",
            "grid_style",
        ),
    ),
    "scales": ("坐标比例", ("log", "inverted")),
    "legend": ("图例外观", ()),
}

LEGEND_FIELDS = {'columns', 'border', 'background', 'visible', 'spacing',
                 'border_style', 'background_style'}


def legend_defaults(value):
    """Translate older flat settings to the styles used by the current renderer."""
    result = {k: copy.deepcopy(v) for k, v in value.items() if k in LEGEND_FIELDS}
    border = result.get('border_style', {})
    if isinstance(border, str):
        border = {'line_style': border}
    if not isinstance(border, dict):
        raise ValueError('invalid legend border style')
    border = dict(border)
    for old, new in [('border_color', 'color'), ('border_width', 'line_width')]:
        if old in value:
            border.setdefault(new, value[old])
    background = result.get('background_style', {})
    if not isinstance(background, dict):
        raise ValueError('invalid legend background style')
    background = dict(background)
    for old, new in [('background_color', 'color'), ('background_opacity', 'opacity')]:
        if old in value:
            background.setdefault(new, value[old])
    from tailor.curve_style import CurveStyle
    for key, spec in [('border_style', border), ('background_style', background)]:
        if spec:
            CurveStyle(mode='line', **{k:v for k,v in spec.items() if k != 'mode'})
            result[key] = spec
    return result


def settings():
    store = QtCore.QSettings("PhysicsPlot", "GraphDefaults")
    store.setFallbacksEnabled(False)
    return store


def axis_settings():
    store = QtCore.QSettings('PhysicsPlot', 'AxisDefaults')
    store.setFallbacksEnabled(False)
    return store


def clear_all():
    """Clear only drawing defaults, never presentation in existing projects."""
    store = settings(); store.clear(); store.sync()
    legacy = axis_settings()
    legacy.clear(); legacy.sync()
    _invalid_noted.clear()


_invalid_noted = set()


def read(key):
    """Validate persisted defaults before any native widgets consume them."""
    try:
        value = json.loads(settings().value(key, "null"))
        if value is None:
            return None
        if key == 'points':
            if type(value) is not bool: raise ValueError('invalid point mode')
            return value
        if not isinstance(value, dict): raise ValueError('invalid default group')
        if key in {'curve','fonts'}:
            from tailor.curve_style import CurveStyle
            value = {k:v for k,v in value.items() if k in GROUPS[key][1]}
            candidate = {'mode':'line','line_width':DEFAULT_LINE_WIDTH,**value}
            if key == 'fonts':
                styles = candidate.get('text_styles',{})
                if not isinstance(styles,dict): raise ValueError('invalid text defaults')
                merged = {}
                for name,spec in styles.items():
                    if not isinstance(spec,dict): raise ValueError('invalid text style')
                    size = 18 if name.endswith('_label') else 16 if name.endswith('_ticks') else candidate.get('font_size',14)
                    merged[name] = {'size':size,'family':candidate.get('font_family','sans-serif'),**spec}
                candidate['text_styles'] = merged
            else:
                for name in ('fill','marker_fill','step_mode'):
                    if name in value and type(value[name]) is not bool: raise ValueError('invalid toggle')
                if 'marker_step' in value and type(value['marker_step']) is not int: raise ValueError('invalid marker interval')
            CurveStyle(**candidate)
            if key == 'fonts' and 'text_styles' in value:
                value['text_styles'] = candidate['text_styles']
        elif key in {'axes','ticks','format','grid','scales'}:
            from tailor.graph_presentation import GraphPresentation,axis_defaults
            filtered = {}
            for axis,config in value.items():
                if axis not in {'x','y','right','top'}: continue
                if not isinstance(config,dict): raise ValueError('invalid axis defaults')
                config = {k:v for k,v in config.items() if k in GROUPS[key][1]}
                for flag in ('line_visible', 'ticks_visible', 'major_visible', 'minor_auto', 'precision_follow_interval'):
                    if flag in config and type(config[flag]) is not bool:
                        raise ValueError('invalid default axis toggle')
                if 'major_count' in config and (type(config['major_count']) is not int or not 2 <= config['major_count'] <= 100):
                    raise ValueError('invalid default tick count')
                if 'custom_interval_value' in config:
                    interval = config['custom_interval_value']
                    if type(interval) not in (int,float) or not math.isfinite(interval) or interval <= 0:
                        raise ValueError('invalid default custom interval')
                if 'saved_tick_lengths' in config:
                    lengths = config['saved_tick_lengths']
                    if (not isinstance(lengths,(list,tuple)) or len(lengths) != 2 or
                            any(type(v) not in (int,float) or not math.isfinite(v) or not 0 <= v <= 20 for v in lengths)):
                        raise ValueError('invalid default saved tick lengths')
                GraphPresentation.validate_axis({**axis_defaults(),**config})
                filtered[axis] = config
            value = filtered
        elif key == 'margins':
            value = {k:v for k,v in value.items() if k in {'left','right','top','bottom'}}
            if any(type(v) not in (int,float) or not math.isfinite(v) or not 0 <= v <= 300 for v in value.values()):
                raise ValueError('invalid default margins')
        elif key == 'legend':
            value = legend_defaults(value)
            if type(value.get('columns',1)) is not int or not 1 <= value.get('columns',1) <= 20: raise ValueError('invalid legend columns')
            for name,lo,hi in [('spacing',0,30)]:
                if name in value and (type(value[name]) not in (int,float) or not math.isfinite(value[name]) or not lo <= value[name] <= hi): raise ValueError('invalid legend size')
            for name in ('border','background','visible'):
                if name in value and type(value[name]) is not bool: raise ValueError('invalid legend toggle')
        _invalid_noted.discard(key)
        return value
    except (TypeError, ValueError, KeyError, AttributeError, OverflowError):
        if key not in _invalid_noted:
            from tailor.crash_diagnostics import breadcrumb
            breadcrumb('invalid-default-format',group=key)
            _invalid_noted.add(key)
        return None


def current_plot():
    import shiboken6
    app = QtWidgets.QApplication.instance()
    window = getattr(app, "window", None)
    if window is None or not shiboken6.isValid(window):
        return None
    active = getattr(getattr(window, "projects", None), "active", None) or window
    if not shiboken6.isValid(active): return None
    tabs = getattr(getattr(active,'ui',None),'tabWidget',None)
    if tabs is None or not shiboken6.isValid(tabs): return None
    tab = tabs.currentWidget()
    target = getattr(tab, '_active_document', tab)
    for candidate in (target, tab):
        if candidate is not None and shiboken6.isValid(candidate) and not getattr(candidate,'_graph_disposed',False) and hasattr(candidate,'presentation'):
            return candidate
    return None


def capture(plot, key):
    pres = plot.presentation
    if key in ("curve", "fonts"):
        data = asdict(plot.curve_style)
        result = {k: data[k] for k in GROUPS[key][1]}
        if key == "fonts":
            result["text_styles"] = {
                k: v
                for k, v in result["text_styles"].items()
                if not k.startswith("annotation:") or k == "annotation:default"
            }
        return result
    if key == "margins":
        return copy.deepcopy(pres.margins)
    if key == "points":
        return bool(plot.point_inspector.enabled.isChecked())
    if key == "legend":
        return legend_defaults(pres.legend)
    return {
        axis: {k: config[k] for k in GROUPS[key][1] if k in config}
        for axis, config in pres.axes.items()
    }


def save(plot, key):
    settings().setValue(key, json.dumps(capture(plot, key), ensure_ascii=False))


def new_style():
    from tailor.curve_style import CurveStyle

    values = {"mode": "line", "line_width": DEFAULT_LINE_WIDTH,
              **(read("curve") or {}), **(read("fonts") or {})}
    axis_fonts = {prefix + suffix: {"size": size, "family": values.get("font_family", "sans-serif")}
                  for prefix in ("x", "y", "right", "top")
                  for suffix, size in (("_label", 18), ("_ticks", 16))}
    for key, spec in values.get("text_styles", {}).items():
        axis_fonts[key] = {**axis_fonts.get(key, {}), **spec}
    values["text_styles"] = axis_fonts
    return CurveStyle(**values)


def derived_width(plot=None):
    """Freeze the common width per graph, so changing defaults is not retroactive."""
    presentation = getattr(plot, 'presentation', None)
    if presentation and 'derived_default_width' in presentation.extra_settings:
        return presentation.extra_settings['derived_default_width']
    width = float((read('curve') or {}).get('line_width', DEFAULT_LINE_WIDTH))
    return presentation.extra_settings.setdefault('derived_default_width', width) if presentation else width


def apply(pres):
    for key in ("axes", "ticks", "format", "grid", "scales"):
        for axis, config in (read(key) or {}).items():
            if axis in pres.axes:
                pres.axes[axis].update(config)
    for config in pres.axes.values():
        if not config.get('ticks_visible', True):
            if max(config['tick_length'], config['minor_length']) > 0:
                config.setdefault('saved_tick_lengths', [config['tick_length'], config['minor_length']])
            config['tick_length'] = config['minor_length'] = 0
    pres.margins.update(read("margins") or {})
    pres.legend.update(read("legend") or {})


class DefaultsPage(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        from tailor.settings_formats import build
        build(self)

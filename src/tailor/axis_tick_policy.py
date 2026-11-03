"""Shared numeric tick interaction over native pyqtgraph/Matplotlib locators."""
import math
from functools import lru_cache
from decimal import Decimal
import numpy as np


def interval_step(span):
    span=abs(float(span))
    if not math.isfinite(span) or span<=0:return 1.
    if span<=1:
        exponent=math.ceil(math.log10(span)-1e-12)-1
        return 10.**max(-15,exponent)
    if span<=10:return 1.
    if span<=1000:return 10.
    return 10.**(math.ceil(math.log10(span)-1e-12)-2)


def decimal_places(value):
    if not math.isfinite(value) or value==0:return 0
    return max(0,-Decimal(format(abs(value),'.12g')).normalize().as_tuple().exponent)


def follows_interval(cfg):
    # Older explicitly formatted projects keep their precision; old zero-place
    # defaults gain the new adaptive behaviour without a schema migration.
    return cfg.get('precision_follow_interval',cfg.get('precision',0)==0)


def label_precision(cfg,spacing,value=0):
    stored=int(cfg.get('precision',0))
    if not follows_interval(cfg) or not math.isfinite(spacing) or spacing<=0:return stored
    places=decimal_places(spacing)
    notation=cfg.get('notation','fixed')
    if notation in {'auto','scientific'}:
        if value==0:return stored
        magnitude=math.floor(math.log10(abs(value)))
        places=max(0,magnitude+places)+(1 if notation=='auto' else 0)
    return min(12,places)


def linear_ticks(low,high,spacing,budget=500):
    """Mature equidistant locator, with bounded display sampling only."""
    from matplotlib.ticker import MultipleLocator
    if not all(math.isfinite(v) for v in (low,high,spacing)) or spacing<=0:return []
    low,high=sorted((low,high))
    stride=max(1,math.ceil((high-low)/spacing/max(1,budget-2)))
    located=MultipleLocator(spacing*stride).tick_values(low,high)
    return located[(located>=np.nextafter(low,-np.inf)) & (located<=np.nextafter(high,np.inf))].tolist()


def native_axis(control):
    return control.plot.ui.plot_widget.getAxis({'x':'bottom','top':'top','y':'left','right':'right'}[control.current])


def current_bounds(control):
    plot=control.plot;key=control.current;cfg=plot.presentation.axes[key]
    view=getattr(plot,'advanced_view',None)
    if view and view.cfg.get('kind')=='3d' and hasattr(view,'ax'):
        if key=='top':
            artist=getattr(view,'three_artist',None)
            limits=artist.get_clim() if hasattr(artist,'get_clim') else view.ax.get_zlim()
            if not np.isfinite(np.asarray(limits,dtype=float)).all():limits=view.ax.get_zlim()
        else:limits=getattr(view.ax,{'x':'get_xlim','y':'get_ylim','right':'get_zlim'}[key])()
        limits=np.asarray(limits,dtype=float)
        return tuple(sorted(np.log10(limits) if cfg['log'] else limits))
    axis=native_axis(control);box=axis.linkedView() or plot.ui.plot_widget.getViewBox()
    values=box.viewRange()[0 if key in {'x','top'} else 1]
    if cfg.get('break_enabled'):
        from tailor.graph_presentation import physical,display
        values=display(physical(values,cfg),cfg['log'])
    return tuple(sorted(float(v) for v in values))


def auto_spacing(control):
    low,high=current_bounds(control)
    return major_spacing(control.plot.presentation.axes[control.current],low,high)


def numeric_spacing(cfg,spacing,value=0):
    if cfg.get('expression'):
        from tailor.tick_expression import calculate
        try:return abs(calculate(cfg['expression'],value+spacing)-calculate(cfg['expression'],value))
        except (ValueError,OverflowError):return spacing
    return spacing/abs(cfg.get('divisor',1))


def advance_interval(value, steps, step, automatic):
    """Explicit positive values or Auto; decimal arithmetic keeps repeated edits stable."""
    base = automatic() if value < 0 else value
    result = Decimal(str(base)) + Decimal(steps) * Decimal(str(step))
    return float(result) if result > 0 else -1.


def smart_ticks(low, high, count=5, *, expand=False):
    """MaxNLocator candidates: equal, friendly steps and complete automatic coverage.

    Manual view limits are never changed; expand is only used for data bounds.
    The requested count is a target, not permission to use awkward fractions.
    """
    from matplotlib.ticker import MaxNLocator
    low,high=sorted((float(low),float(high)))
    if not np.isfinite([low,high]).all():raise ValueError('坐标范围必须为有限数字')
    if low==high:
        if low==0:low,high=0.,1.
        else:
            delta=abs(low)*.05
            low,high=low-delta,high+delta
    count=max(2,min(100,int(count or 5)))
    span=high-low
    magnitude=span if math.isfinite(span) else max(abs(low),abs(high))
    scale=10.**max(-323,min(308,math.floor(math.log10(magnitude))))
    # Center ranges far from zero before calling the native locator. Its
    # nonsingular expansion otherwise turns a narrow 1e15..1e15+1 view into
    # hundreds of units, despite those values being representable as floats.
    offset=math.floor(low/scale/1000)*1000*scale if abs(low/scale)>1000 else 0.
    a,b=(low-offset)/scale,(high-offset)/scale
    candidates=[]
    for bins in sorted({max(1,count-2),count-1,count,count+1}):
        normalized=MaxNLocator(nbins=bins,steps=[1,2,2.5,5,10],min_n_ticks=2).tick_values(a,b)
        step=float(format(float(normalized[1]-normalized[0])*scale,'.12g'))
        with np.errstate(over='ignore'):ticks=normalized*scale+offset
        ticks=np.unique(ticks[np.isfinite(ticks)])
        if not expand:
            tol=abs(step)*1e-9
            ticks=ticks[(ticks>=low-tol)&(ticks<=high+tol)]
        if not len(ticks):continue
        padding=max(0,low-ticks[0])+max(0,ticks[-1]-high)
        score=(abs(len(ticks)-count),padding/span if span else 0,step)
        candidates.append((score,step,ticks))
    _,step,values=min(candidates,key=lambda item:item[0])
    values=np.array(values,copy=True)
    values[np.abs(values)<abs(step)*1e-10]=0.
    return step,values


def major_spacing(cfg,low,high):
    if cfg.get('major') is not None:return float(cfg['major'])
    spacing,_=smart_ticks(low,high,cfg.get('major_count',5),expand=False)
    return spacing


@lru_cache(maxsize=64)
def available_tick_counts(low, high):
    """Count stops supported by the existing friendly locator, not a new locator.

    Cache is bounded and keyed by view limits; it never scans source data.
    Only fixed points are exposed: choosing N must actually draw N ticks.
    """
    counts=set()
    for target in range(2,101):
        _,ticks=smart_ticks(low,high,target)
        count=len(ticks)
        if 2<=count<=100:counts.add(count)
    return tuple(sorted(n for n in counts if len(smart_ticks(low,high,n)[1])==n))


def reachable_tick_count(low, high, requested, previous):
    choices=available_tick_counts(float(low),float(high))
    if not choices:return int(requested)
    if requested>previous:
        return next((n for n in choices if n>=requested),choices[-1])
    if requested<previous:
        return next((n for n in reversed(choices) if n<=requested),choices[0])
    return int(requested)


def display_format(cfg,spacing):
    """Default precision follows the locator; tiny steps use scientific captions."""
    result=dict(cfg)
    if follows_interval(cfg) and cfg.get('notation','fixed')=='fixed' and decimal_places(spacing)>12:
        result['notation']='scientific'
    return result

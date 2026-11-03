"""Stable default colours for the existing data/fit/preview items in a graph."""
from PySide6 import QtGui

PALETTE = ('#202020', '#2878cc', '#d65a31', '#31905e', '#8b5bb5',
           '#b68a16', '#2399a5', '#d0508f', '#657b32', '#805640')


def occupied(graph):
    colours = set(graph.presentation.extra_settings.get('series_colors', {}).values())
    if graph.presentation.multi:
        colours.update(QtGui.QColor(i.color).name() for i in graph.model._plots.values())
    else:
        colours.add(QtGui.QColor(graph.curve_style.color).name())
    for spec in graph.presentation.curve_overrides.values():
        if spec.get('color'):
            colours.add(QtGui.QColor(spec['color']).name())
    # Desktop defaults may use pure black while the shared palette uses ink
    # black. They are one visual default, not two distinct series colours.
    if colours & {'#000000', '#202020'}:
        colours.update(('#000000', '#202020'))
    return colours


def next_colour(graph):
    used = occupied(graph)
    for colour in PALETTE:
        if colour not in used:
            return colour
    # Keep distinct defaults beyond the small palette, without a cycling clash.
    index = 0
    while True:
        colour = QtGui.QColor.fromHsvF((index * .61803398875) % 1., .68, .76).name()
        if colour not in used:
            return colour
        index += 1


def colour_for(graph, identity):
    colours = graph.presentation.extra_settings.setdefault('series_colors', {})
    if identity not in colours:
        colours[identity] = next_colour(graph)
    return colours[identity]


def fit_colour(graph, source, record_id=None, component=None):
    record_id = source.active_fit_id if record_id is None else record_id
    identity = f'fit:{source.id}:{record_id if record_id is not None else "preview"}'
    if component is not None:
        identity += f':component:{component}'
    return colour_for(graph, identity)

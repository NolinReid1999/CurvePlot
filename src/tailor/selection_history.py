"""Compact selection snapshots in the existing sheet Edit history."""

from functools import wraps

import numpy as np


def snapshot(control):
    frame = control.selected_frame
    points = control.marker.getData()
    # Selection interval identifies the full source selection; only a bounded
    # display marker is stored, never a second full copy of the data table.
    markers = tuple(
        tuple(np.asarray(a)[:: max(1, len(a) // 2000)].tolist())
        if a is not None
        else ()
        for a in points
    )
    selected = getattr(control, "selected", None)
    source = (
        selected[0]
        if selected
        else control.start_row[0]
        if isinstance(control.start_row, tuple)
        else control.plot
    )
    return {
        "curve_key": getattr(control, 'curve_key', None),
        "start_curve": getattr(control, '_start_curve', None),
        "sampled": getattr(control, 'sampled_curve', False),
        "source": source,
        "start": control.start_row,
        "row": getattr(control, "source_row", None),
        "selected": selected,
        "range": None
        if frame is None or frame.empty
        else (int(frame.index.min()), int(frame.index.max())),
        "coordinates": control.selected_coordinates,
        "markers": markers,
        "text": control.details.text(),
        "copy": control.copy.isEnabled(),
        "locate": control.locate.isEnabled(),
    }


def restore(control, state):
    control.invalidate()
    source = state["source"]
    from tailor.point_inspector import point_candidates, show_point_feedback
    candidate = next((c for c in point_candidates(control.plot) if c['key'] == state.get('curve_key')), None) if state.get('curve_key') else None
    if state.get('sampled') and candidate is None:return
    if candidate:show_point_feedback(control, candidate)
    control._start_curve = state.get('start_curve')
    if state["range"] is not None:
        frame = candidate['frame'] if candidate else source.model._get_data_as_dataframe()
        lo, hi = state["range"]
        control.selected_frame = frame.loc[
            (frame.index >= lo) & (frame.index <= hi), ["x", "y"]
        ].copy()
    control.start_row = state["start"]
    control.selected_coordinates = state["coordinates"]
    if hasattr(control, "source_row"):
        control.source_row = state["row"]
    if hasattr(control, "selected"):
        control.selected = state["selected"]
    if hasattr(control, "marker_box") and source is not control.plot:
        box = control.plot.presentation.box_for(
            control.plot.model.get_plot_info(source)
        )
        if control.marker_box is not box:
            if control.marker_box is not None:
                control.marker_box.removeItem(control.marker)
                control.marker_box.removeItem(control.highlight)
            box.addItem(control.marker, ignoreBounds=True)
            box.addItem(control.highlight, ignoreBounds=True)
            control.marker_box = box
    control.marker.setData(*state["markers"])
    control.highlight.setData(*state["markers"])
    control.details.setText(state["text"])
    control.details.setVisible(bool(state["text"]))
    control.copy.setEnabled(state["copy"])
    control.locate.setEnabled(state["locate"])


def selection_edit(callback):
    @wraps(callback)
    def select(control, *args, **kwargs):
        before = snapshot(control)
        result = callback(control, *args, **kwargs)
        after = snapshot(control)
        from tailor.text_style_controls import record_view_edit

        record_view_edit(
            control.plot,
            "选择数据点",
            before,
            after,
            lambda plot, state: restore(plot.point_inspector, state),
        )
        return result

    return select

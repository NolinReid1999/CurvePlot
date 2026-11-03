"""One undo transaction for composite inspector changes; no source data copies."""

import copy
from functools import wraps

MODEL_FIELDS = (
    "x_err_col",
    "y_err_col",
    "x_label",
    "y_label",
    "x_min",
    "x_max",
    "y_min",
    "y_max",
)


def model_state(model):
    return {
        key: copy.deepcopy(getattr(model, key))
        for key in MODEL_FIELDS
        if hasattr(model, key)
    }


def state(plot):
    return {
        "model": model_state(plot.model),
        "presentation": plot.presentation.to_dict(),
        "style": plot.curve_style.to_dict(),
        "sources": [
            (source, copy.deepcopy(info), model_state(source.model))
            for source, info in plot.model._plots.items()
        ]
        if plot.presentation.multi
        else [],
        "annotations": copy.deepcopy(plot.annotations.records),
    }


def restore(plot, value):
    from tailor.curve_style import CurveStyle

    plot._view_edit_active = True
    try:
        changed_sources = []
        plot.presentation.load(copy.deepcopy(value["presentation"]))
        plot.curve_style = CurveStyle(**value["style"])
        previous_errors = (getattr(plot.model, 'x_err_col', None), getattr(plot.model, 'y_err_col', None))
        for key, val in value["model"].items():
            setattr(plot.model, key, val)
        if previous_errors != (getattr(plot.model, 'x_err_col', None), getattr(plot.model, 'y_err_col', None)):
            plot._source_changed = True
            changed_sources.append(plot)
        for source, info, fields in value["sources"]:
            plot.model._plots[source] = copy.deepcopy(info)
            previous_errors = (source.model.x_err_col, source.model.y_err_col)
            for key, val in fields.items():
                setattr(source.model, key, val)
            if previous_errors != (source.model.x_err_col, source.model.y_err_col):
                source._source_changed = True
                changed_sources.append(source)
        plot.annotations.load(value["annotations"])
        plot.refresh_ui()
        for source in changed_sources:
            if source is not plot:
                source.refresh_from_source()
            else:
                source.data_refreshed.emit()
        if hasattr(plot, 'error_controls'):
            plot.error_controls.sync()
        plot.extras.cfg = plot.presentation.extra_settings
        plot.extras.load()
        if hasattr(plot, "advanced_view"):
            plot.advanced_view.cfg = plot.presentation.extra_settings["advanced"]
            plot.advanced_view.schedule()
    finally:
        plot._view_edit_active = False


def view_transaction(label):
    def decorate(callback):
        @wraps(callback)
        def run(control, *args, **kwargs):
            plot = control.plot
            if (
                getattr(plot, "_view_edit_active", False)
                or getattr(control, "loading", False)
                or not hasattr(plot, "annotations")
            ):
                return callback(control, *args, **kwargs)
            before = state(plot)
            plot._view_edit_active = True
            try:
                result = callback(control, *args, **kwargs)
            finally:
                plot._view_edit_active = False
            from tailor.text_style_controls import record_view_edit

            record_view_edit(plot, label, before, state(plot), restore)
            return result

        return run

    return decorate

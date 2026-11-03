"""Commit native parameter edits to the existing chronological sheet history."""

from PySide6 import QtCore


class ParameterHistory(QtCore.QObject):
    def __init__(self, plot, name, fields, fixed):
        super().__init__(plot)
        self.plot, self.name, self.before = plot, name, None
        self.fixed = fixed
        for field in fields:
            field.sigValueChanging.connect(self.begin)
            field.sigValueChanged.connect(self.finish)
        fixed.stateChanged.connect(self.begin)

    def state(self):
        p = self.plot.model._parameters[self.name]
        return (
            (p.value, p.min, p.max, p.vary),
            {r["id"]: r["stale"] for r in self.plot.fit_records},
        )

    def begin(self, *args):
        if self.before is None:
            self.before = self.state()

    def finish(self, *args):
        if self.before is None:
            return
        before, self.before = self.before, None
        after = self.state()
        from tailor.text_style_controls import record_view_edit

        name = self.name

        def restore(plot, state):
            if name not in plot.model._parameters:
                return
            p = plot.model._parameters[name]
            p.value, p.min, p.max, p.vary = state[0]
            for record in plot.fit_records:
                if record["id"] in state[1]:
                    record["stale"] = state[1][record["id"]]
            plot.update_params_ui_values_from_model()
            plot.update_model_curves()

        record_view_edit(self.plot, "修改拟合参数 · " + name, before, after, restore)


def configuration_edit(method):
    """Model changes precede point edits in the same existing undo timeline."""
    import copy
    from functools import wraps

    @wraps(method)
    def edit(control, *args, **kwargs):
        plot = control.plot

        def snapshot():
            actions = getattr(plot, "fit_actions", None)
            return {
                "expression": plot.model._model_expression,
                "preset": plot.model.fit_preset_key,
                "custom_selected":control._custom_selected,
                "parameters": copy.deepcopy(plot.model._parameters),
                "active": plot.active_fit_id,
                "modify": actions.modify_id if actions else None,
                "current": actions.current_id if actions else None,
                "centers": list(control.manual_peaks.centers),
                "armed": control.manual_peaks.button.isChecked(),
                "stale": {r["id"]: r["stale"] for r in plot.fit_records},
            }

        before = snapshot()
        result = method(control, *args, **kwargs)
        if hasattr(plot, "fit_actions") and before["modify"] is None:
            plot.fit_actions.modify_id = None
            plot.fit_actions.current_id = None
        if hasattr(plot, "fit_actions"):
            plot.fit_actions.sync()
        control.manual_peaks.arm(False)
        with QtCore.QSignalBlocker(control.manual_peaks.button):
            control.manual_peaks.button.setChecked(False)
        after = snapshot()

        def restore(target, state):
            target.preset_controls._custom_selected=state['custom_selected']
            target.model.fit_preset_key = state["preset"]
            target.model.update_model_expression(
                state["expression"], use_column_ids=True
            )
            target.model._parameters = copy.deepcopy(state["parameters"])
            target.active_fit_id = state["active"]
            for record in target.fit_records:
                if record["id"] in state["stale"]:
                    record["stale"] = state["stale"][record["id"]]
            if hasattr(target, "fit_actions"):
                target.fit_actions.modify_id = state["modify"]
                target.fit_actions.current_id = state["current"]
            target.preset_controls.sync_model()
            target.update_model_widget()
            target.update_params_ui_values_from_model()
            peaks = target.preset_controls.manual_peaks
            peaks.centers = list(state["centers"])
            with QtCore.QSignalBlocker(peaks.button):
                peaks.button.setChecked(state["armed"])
            peaks.refresh_marker()
            from tailor.fit_results import StoredFit
            active = next((r for r in target.fit_records if r["id"]==target.active_fit_id and not r["stale"]),None)
            target.model.best_fit = StoredFit(active,target.model) if active else None
            target.update_model_curves()
            target.plot_best_fit()

        from tailor.text_style_controls import record_view_edit

        record_view_edit(plot, "选择拟合模型", before, after, restore)
        return result

    return edit

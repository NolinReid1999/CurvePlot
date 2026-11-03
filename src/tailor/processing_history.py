"""Remember processing input edits in the project's existing Edit history."""
import copy
import weakref

import shiboken6
from PySide6 import QtCore, QtWidgets
from tailor.spreadsheet_model import Edit


class ProcessingHistory:
    def __init__(self, control):
        self.control = control
        self.replaying = False
        self.previous = self.snapshot()
        widgets = list(control.methods.values())
        for options in control.options.values():
            for value in options.values():
                widgets.extend(value.values() if isinstance(value, dict) else [value])
        widgets += [control.all_data, control.current_data, control.multi,
                    control.draw_result, control.preview_toggle]
        for widget in widgets:
            if isinstance(widget, QtWidgets.QComboBox):
                widget.activated.connect(self.commit)
            elif isinstance(widget, (QtWidgets.QAbstractSpinBox, QtWidgets.QLineEdit)):
                widget.editingFinished.connect(self.commit)
                step = widget.parentWidget()
                if hasattr(step, 'slider'):
                    step.slider.sliderReleased.connect(self.commit)
                    for button in step.buttons:button.clicked.connect(self.commit)
            elif isinstance(widget, QtWidgets.QAbstractButton):
                widget.clicked.connect(self.commit)
        for button in (control.clear_reference, control.clear_reference_value,
                       control.process_actions.buttons['add']):
            button.clicked.connect(self.commit)

    def fields(self):
        c = self.control
        fields = {'method:'+k:v for k,v in c.methods.items()}
        for title, options in c.options.items():
            for key, value in options.items():
                for sub, widget in (value.items() if isinstance(value, dict) else [('', value)]):
                    if isinstance(widget,(QtWidgets.QComboBox,QtWidgets.QAbstractSpinBox,
                                          QtWidgets.QLineEdit,QtWidgets.QAbstractButton)):
                        fields[(title,key,sub)] = widget
        for name in ('all_data','current_data','multi','draw_result','preview_toggle'):
            fields[name] = getattr(c,name)
        return fields

    def snapshot(self):
        result = {'targets': list(self.control.targets)}
        for name, widget in self.fields().items():
            result[name] = (copy.deepcopy(widget.currentData()) if isinstance(widget,QtWidgets.QComboBox)
                else widget.text() if isinstance(widget,QtWidgets.QLineEdit)
                else widget.value() if isinstance(widget,QtWidgets.QAbstractSpinBox)
                else widget.isChecked())
        return result

    def restore(self, state):
        c = self.control
        was_preview = c.preview_toggle.isChecked()
        self.replaying = c._workflow_loading = True
        try:
            c.targets = list(state['targets'])
            for name, widget in self.fields().items():
                if name not in state:continue
                with QtCore.QSignalBlocker(widget):
                    if isinstance(widget,QtWidgets.QComboBox):
                        from tailor.ui_widgets import data_index
                        widget.setCurrentIndex(max(0,data_index(widget,state[name])))
                    elif isinstance(widget,QtWidgets.QLineEdit):widget.setText(state[name])
                    elif isinstance(widget,QtWidgets.QAbstractSpinBox):widget.setValue(state[name])
                    else:widget.setChecked(state[name])
            for title in c.methods:c.sync_method(title)
            from tailor.choice_buttons import ChoiceButtons
            for choices in c.findChildren(ChoiceButtons):choices.sync()
            c.sync_objects_text()
            # Signals are intentionally blocked while restoring fields. Apply
            # the corresponding canvas state explicitly, without writing the
            # newly created region's default range back into the stored inputs.
            region = c.options.get('交互区域分析', {}).get('region')
            if c.plot and region is not None and (region.isChecked() or hasattr(c, 'analysis_region')):
                c.show_region(region.isChecked())
                options = c.options['交互区域分析']
                low, high = options['region_low'].value(), options['region_high'].value()
                if low < high:
                    from tailor.graph_presentation import display
                    with QtCore.QSignalBlocker(c.analysis_region):
                        c.analysis_region.setRegion(display([low, high], c.plot.presentation.axes['x']))
            if was_preview and not c.preview_toggle.isChecked():
                c.clear_preview()
            self.previous = self.snapshot()
        finally:
            self.replaying = c._workflow_loading = False
        from tailor.processing_workflow import refresh
        refresh(c)

    def commit(self, *args):
        c = self.control
        if self.replaying or c._workflow_loading:return
        after = self.snapshot()
        before = self.previous
        if before == after:return
        self.previous = copy.deepcopy(after)
        sheets = c.owner.get_data_sheets()
        if not sheets:return
        ref = weakref.ref(c)
        def apply(state):
            target = ref()
            if target is not None and shiboken6.isValid(target):
                target.input_history.restore(state)
        sheets[0].model._record(Edit('处理参数',lambda:apply(before),lambda:apply(after),4096))

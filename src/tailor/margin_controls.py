"""One-row arrow margin selectors with the common value/slider layout."""
from PySide6 import QtWidgets
from tailor.compact_controls import ArrowParameter


class MarginControls(QtWidgets.QWidget):
    def __init__(self,plot):
        super().__init__(plot);self.plot=plot;self.current=None;self.loading=False
        self.arrows=ArrowParameter(0,300,parent=self)
        layout=QtWidgets.QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.addWidget(self.arrows)
        self.buttons={key:self.arrows.buttons[{'top':'up','bottom':'down'}.get(key,key)] for key in ('left','top','right','bottom')}
        self.value=self.arrows.value
        self.arrows.chosen.connect(lambda key:self.select({'up':'top','down':'bottom'}.get(key,key)))
        self.value.valueChanged.connect(self.apply);self.sync()
    def select(self,key):
        repeat=self.current==key;self.current=key;self.sync()
        if repeat:self.value.stepBy(1)
    def sync(self):
        self.loading=True
        values={ {'top':'up','bottom':'down'}.get(k,k):v for k,v in self.plot.presentation.margins.items() }
        self.arrows.sync(values,{'top':'up','bottom':'down'}.get(self.current,self.current));self.loading=False
    def apply(self,*args):
        if self.loading:return
        self.current=self.current or 'left'
        before=dict(self.plot.presentation.margins)
        self.plot.presentation.margins[self.current]=self.value.value()
        self.plot.presentation.apply_axes();self.plot.main_window.mark_project_dirty();self.sync()
        from tailor.text_style_controls import record_view_edit

        def restore(plot, margins):
            plot.presentation.margins=dict(margins)
            plot.presentation.apply_axes()
            if hasattr(plot, 'margin_controls'):
                plot.margin_controls.sync()

        record_view_edit(self.plot, '调整图形边距', before,
                         dict(self.plot.presentation.margins), restore)

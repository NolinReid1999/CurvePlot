"""Single position editor for annotations, complete legend and axis titles."""

from types import SimpleNamespace

from PySide6 import QtCore, QtWidgets

from tailor.graph_controls import combo, row
from tailor.position_controls import PositionControls


class ObjectPosition(QtWidgets.QWidget):
    def __init__(self, plot):
        super().__init__()
        self.plot = plot
        self.loading = False
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.objects = QtWidgets.QComboBox()
        self.origin = combo([("中心", "center"), ("左轴", "left"), ("下轴", "bottom")])
        from tailor.choice_buttons import ChoiceButtons

        layout.addWidget(row("对象", self.objects))
        layout.addWidget(row("相对原点", ChoiceButtons(self.origin, equal=True)))
        self.controls = PositionControls(SimpleNamespace(plot=plot), font=False)
        self.controls.explicit_target = None
        layout.addWidget(self.controls)
        self.objects.activated.connect(self.choose)
        self.origin.activated.connect(self.change_origin)
        plot.annotations.changed.connect(self.sync)
        self.sync()

    def sync(self, *args):
        if self.loading:
            return
        self.loading = True
        old = self.objects.currentData()
        with QtCore.QSignalBlocker(self.objects):
            self.objects.clear()
            self.objects.addItem('—',None)
            from tailor.choice_catalog import seed_objects,object_rank
            seed_objects(self.plot)
            entries=[]
            for record in self.plot.annotations.records:
                if not record['visible']:continue
                from tailor.annotations import annotation_caption
                entries.append((annotation_caption(record,self.plot.annotations.records),('annotation',record['id'])))
            collection=getattr(getattr(self.plot,'extras',None),'collection',None)
            if collection:
                for i,record in enumerate(collection.records):
                    if record.get('enabled'):entries.append((f'局部放大{i+1}',('inset',record['id'])))
            if self.plot.presentation.legend.get('visible',True):entries.append(('整个图例',('legend',None)))
            for key,label in [('x','下X轴标题'),('y','左Y轴标题'),('top','上X轴标题'),('right','右Y轴标题')]:
                cfg=self.plot.presentation.axes[key]
                if cfg.get('visible',False) and cfg.get('title_visible',False):entries.append((label,('axis',key)))
                if cfg.get('factor_text') and cfg.get('visible',False):entries.append((label.replace('标题','倍率'),('factor',key)))
            for caption,target in sorted(entries,key=lambda row:object_rank(self.plot,*row[1])):
                self.objects.addItem(caption,target)
            key=getattr(getattr(self.plot,'text_selection',None),'key',None)
            target=None
            if self.plot.annotations.selected:target=('annotation',self.plot.annotations.selected)
            elif key and key.startswith('legend'):target=('legend',None)
            elif key and key.endswith('_label'):target=('axis',key.rsplit('_',1)[0])
            elif key and key.endswith('_factor'):target=('factor',key.rsplit('_',1)[0])
            elif collection and collection.selected:target=('inset',collection.selected)
            self.objects.setCurrentIndex(
                max(
                    0,
                    next(
                        (
                            i
                            for i in range(self.objects.count())
                            if self.objects.itemData(i) == target
                        ),
                        0,
                    ),
                )
            )
        self.loading = False
        self.controls.explicit_target = (
            tuple(self.objects.currentData()) if self.objects.currentData() else None
        )
        self.origin.setEnabled(self.controls.explicit_target is not None)
        self.controls.refresh()

    def choose(self, *args):
        selected=self.objects.currentData()
        if selected is None:
            self.controls.explicit_target=None
            self.plot.annotations.select(None)
            self.plot.text_selection.select(None)
            collection=getattr(getattr(self.plot,'extras',None),'collection',None)
            if collection:collection.select(None)
            self.controls.refresh()
            return
        target = tuple(selected)
        self.plot.curve_selection.clear()
        collection = getattr(getattr(self.plot, 'extras', None), 'collection', None)
        if target[0] != 'inset' and collection is not None and collection.selected is not None:
            collection.select(None)
        self.controls.explicit_target = target
        if target[0] == "annotation":
            self.plot.annotations.select(target[1])
        elif target[0] == "inset":
            self.plot.extras.collection.select(target[1])
        elif target[0] == 'factor':
            self.plot.annotations.select(None)
            self.plot.axis_controls.select_axis(target[1],'ticks')
            self.plot.text_selection.select(target[1]+'_factor')
        elif target[0] == "axis":
            self.plot.annotations.selected = None
            self.plot.annotations.redraw()
            self.plot.axis_controls.select_axis(target[1], "label")
            self.plot.text_selection.select(target[1] + "_label")
        else:
            self.plot.annotations.selected = None
            self.plot.annotations.redraw()
            self.plot.text_selection.select("legend")
        self.controls.refresh()

    def change_origin(self, *args):
        self.controls.origin = self.origin.currentData()
        self.controls.refresh()

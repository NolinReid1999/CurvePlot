"""XYZ role chips, editable three-color palettes and live existing 3D settings."""
import copy
from PySide6 import QtCore,QtWidgets
from tailor.plot_types import RolePickerRow
from tailor.column_titles import letters
from tailor.graph_controls import color_button,row
from tailor.bar_controls import BarControls
from tailor.ui_widgets import data_index

DEFAULT_COLORS=['#204e9a','#f4f4f4','#ca3c4a']


def colormap(cfg):
    from matplotlib import colormaps
    from matplotlib.colors import LinearSegmentedColormap,is_color_like
    if cfg.get('cmap')!='custom':return colormaps[cfg.get('cmap','viridis')]
    colors=cfg.get('custom_colors',DEFAULT_COLORS)
    if len(colors)!=3 or not all(is_color_like(c) for c in colors):raise ValueError('自定义配色需要三个有效颜色。')
    return LinearSegmentedColormap.from_list('curve_custom',colors)


class ThreeControls:
    def __init__(self,c):
        self.c=c;self.loading=False;self.initialized=False;self.before=None
        self.custom_colors=DEFAULT_COLORS.copy();self.last_palette=c.cmap.currentData()
        self.history_timer=QtCore.QTimer(c);self.history_timer.setSingleShot(True)
        self.history_timer.setInterval(180);self.history_timer.timeout.connect(self.commit)
        self.model=c.bar_setup.model;self.sheet=c.bar_setup.sheet
        self.roles=[RolePickerRow(role,self.model) for role in 'XYZ']
        self.source_row=QtWidgets.QWidget(c)
        layout=QtWidgets.QHBoxLayout(self.source_row);layout.setContentsMargins(0,0,0,0);layout.setSpacing(8)
        for i,(name,control) in enumerate(zip('XYZ',self.roles)):
            field=QtWidgets.QWidget();field.setMinimumWidth(0)
            form=QtWidgets.QHBoxLayout(field);form.setContentsMargins(0,0,0,0);form.setSpacing(4)
            label=QtWidgets.QLabel(name+'轴');label.setToolTip('作为'+name+'轴')
            form.addWidget(label);form.addWidget(control,1);layout.addWidget(field,1)
            control.addRequested.connect(lambda column,i=i:self.change_role(i,column,True))
            control.removeRequested.connect(lambda column,i=i:self.change_role(i,column,False))
            c.xyz[i].currentIndexChanged.connect(self.sync_roles)
        c.bar_setup.form.insertWidget(0,self.source_row)
        for widget in (c.three_mode,c.projection):widget.currentIndexChanged.connect(self.live)
        c.cmap.currentIndexChanged.connect(self.palette_changed)
        c.cmap.activated.connect(self.edit_palette)
        c.colorbar.toggled.connect(self.live)
        for field in (c.azimuth,c.elevation,c.levels,c.display_limit):field.valueChanged.connect(self.live)
        self.sync_roles()

    def sync_roles(self,*_):
        c=self.c
        if self.loading:return
        self.loading=True
        try:
            active=c.kind.currentData()=='3d'
            self.source_row.setVisible(active and c.plot is None)
            keys=list(self.model.columnLabels())
            if active and not c.loading and c.plot is None and not self.initialized:
                self.initialized=True
                if all(box.currentData() is None for box in c.xyz):
                    for box,key in zip(c.xyz,keys[:3]):
                        with QtCore.QSignalBlocker(box):box.setCurrentIndex(data_index(box,(self.sheet.id,key)))
            selected=[box.currentData() for box in c.xyz]
            for i,control in enumerate(self.roles):
                ref=selected[i]
                index=keys.index(ref[1]) if ref and ref[0]==self.sheet.id and ref[1] in keys else None
                control.set_items([(index,letters(index))] if index is not None else [])
                used={tuple(r) for j,r in enumerate(selected) if r is not None and j!=i}
                control.set_available([j for j,k in enumerate(keys) if (self.sheet.id,k) not in used and j!=index])
            c.sync_target_actions()
        finally:self.loading=False

    def change_role(self,axis,column,adding):
        keys=list(self.model.columnLabels());ref=(self.sheet.id,keys[column])
        box=self.c.xyz[axis]
        box.setCurrentIndex(data_index(box,ref) if adding else 0)
        self.sync_roles()

    def palette_changed(self,*_):
        if self.c.cmap.currentData()!='custom':
            self.last_palette=self.c.cmap.currentData();self.live()

    def edit_palette(self,*_):
        c=self.c
        if c.cmap.currentData()!='custom' or c.loading:return
        view=getattr(c.plot,'advanced_view',None)
        previous=view.cfg.get('cmap','viridis') if view else self.last_palette
        dialog=QtWidgets.QDialog(c);dialog.setWindowTitle('自定义三色配色')
        layout=QtWidgets.QVBoxLayout(dialog);layout.setSpacing(7)
        values=self.custom_colors.copy()
        for i,name in enumerate(('起始颜色','中间颜色','结束颜色')):
            def changed(value,i=i):values[i]=value
            layout.addWidget(row(name,color_button(values[i],changed)))
        actions=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        actions.accepted.connect(dialog.accept);actions.rejected.connect(dialog.reject);layout.addWidget(actions)
        dialog.resize(360,180)
        if dialog.exec()==QtWidgets.QDialog.Accepted:
            self.custom_colors=values;self.last_palette='custom';self.live()
        else:c.cmap.setCurrentIndex(max(0,c.cmap.findData(previous)))

    def values(self):
        c=self.c
        return dict(three_mode=c.three_mode.currentData(),cmap=c.cmap.currentData(),custom_colors=self.custom_colors.copy(),
                    colorbar=c.colorbar.isChecked(),projection=c.projection.currentData(),azimuth=c.azimuth.value(),
                    elevation=c.elevation.value(),levels=int(c.levels.value()),display_limit=int(c.display_limit.value()))

    def live(self,*_):
        c=self.c;view=getattr(c.plot,'advanced_view',None)
        if c.loading or self.loading or view is None or view.cfg.get('kind')!='3d':return
        values=self.values();before={k:copy.deepcopy(view.cfg.get(k)) for k in values}
        if before==values:return
        if self.before is None:self.before=before
        view.cfg.update(copy.deepcopy(values));BarControls.queue_draw(view)
        self.history_timer.start();c.owner.mark_project_dirty()

    def commit(self):
        c=self.c;view=getattr(c.plot,'advanced_view',None)
        if self.before is None or view is None:return
        before,self.before=self.before,None;after={k:copy.deepcopy(view.cfg.get(k)) for k in before}
        from tailor.text_style_controls import record_view_edit
        def restore(root,state):
            view=root.advanced_view;view.cfg.update(copy.deepcopy(state));root.advanced_controls.load(view.cfg)
            BarControls.queue_draw(view)
        record_view_edit(c.plot,'三维图设置',before,after,restore)

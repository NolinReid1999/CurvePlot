"""Live panel settings and pre-draw layout using the existing native nodes."""
import copy
import math
from PySide6 import QtCore
from tailor.native_panels import SLOTS, uid


def resolved_rect(nodes, node, rows, columns):
    if node.get('rect'): return list(node['rect'])
    columns=max(1,int(columns)); rows=max(1,int(rows),math.ceil(len(nodes)/columns))
    i=nodes.index(node)
    return [100*(i%columns)/columns,100*(i//columns)/rows,100/columns,100/rows]


def set_position(nodes, identifier, rect, slot, rows, columns):
    node=next(n for n in nodes if n['id']==identifier)
    old=resolved_rect(nodes,node,rows,columns)
    if slot in SLOTS:
        other=next((n for n in nodes if n is not node and
                    all(abs(a-b)<1e-7 for a,b in zip(resolved_rect(nodes,n,rows,columns),rect))),None)
        if other:
            previous=next((key for key,value in SLOTS.items() if value==old),'custom')
            other.update(rect=old,slot=previous)
    node.update(rect=list(rect),slot=slot)


class PanelControls:
    def __init__(self,c):
        self.c=c;self.nodes=[];self.active=None;self.loading=False
        c.unified.setText('合并图例')
        for field in (c.rows,c.columns):field.valueChanged.connect(self.live)
        for button in (c.share_x,c.share_y,c.unified,c.numbering):button.toggled.connect(self.live)

    def sync_draft(self):
        c=self.c
        if c.plot is not None or self.loading:return
        old={tuple(n['refs'][0]):n for n in self.nodes}
        self.nodes=[old.get(tuple(ref),dict(id=uid(),refs=[tuple(ref)],slot='auto',sources=[])) for ref in c.refs]
        if not any(n['id']==self.active for n in self.nodes):self.active=self.nodes[0]['id'] if self.nodes else None
        if c.kind.currentData()=='panels':self.refresh_layout()

    def refresh_layout(self):
        c=self.c
        if not self.nodes:
            from tailor.advanced_ui import sync_layout
            sync_layout(c)
            return
        self.loading=True;c._layout_sync=True
        try:
            with QtCore.QSignalBlocker(c.layout_target):
                c.layout_target.clear()
                for i,n in enumerate(self.nodes):c.layout_target.addItem(f'子图{i+1}',n['id'])
                c.layout_target.setCurrentIndex(max(0,c.layout_target.findData(self.active)))
            node=next(n for n in self.nodes if n['id']==self.active)
            c.layout_slot.setCurrentIndex(max(0,c.layout_slot.findData(node.get('slot','auto'))))
            for field,value in zip(c.layout_fields,resolved_rect(self.nodes,node,c.rows.value(),c.columns.value())):
                with QtCore.QSignalBlocker(field):field.setValue(value)
            from tailor.advanced_ui import sync_layout
            sync_layout(c)
        finally:self.loading=False;c._layout_sync=False

    def select(self,index):
        if 0<=index<len(self.nodes):self.active=self.nodes[index]['id'];self.refresh_layout()

    def position(self,rect,slot):
        if not self.nodes:return
        before=copy.deepcopy(self.nodes)
        set_position(self.nodes,self.active,rect,slot,self.c.rows.value(),self.c.columns.value())
        self.refresh_layout();self.record_draft(before)

    def record_draft(self,before):
        after=copy.deepcopy(self.nodes)
        if before==after:return
        from tailor.spreadsheet_model import Edit
        def restore(value):self.nodes=copy.deepcopy(value);self.refresh_layout()
        self.c.document.model._record(Edit('子图布局',lambda:restore(before),lambda:restore(after),4096))

    def live(self,*_):
        c=self.c
        if self.loading or c.loading or c.kind.currentData()!='panels':return
        native=c.native_context()
        if native is None:self.refresh_layout();return
        values=dict(rows=int(c.rows.value()),columns=int(c.columns.value()),share_x=c.share_x.isChecked(),
                    share_y=c.share_y.isChecked(),unified_legend=c.unified.isChecked(),numbering=c.numbering.isChecked())
        before={key:copy.deepcopy(native.cfg.get(key)) for key in values}
        if before==values:return
        from tailor.quick_actions import _view_state,_restore_view
        prior_views=[(node["id"],_view_state(native.panels[node["id"]])) for node in native.cfg["nodes"]]
        native.cfg.update(copy.deepcopy(values))
        changed={key for key in values if before[key]!=values[key]}
        native.place()
        if changed & {'share_x','share_y'}:native.reset()
        if 'unified_legend' in changed:native.refresh_unified()
        from tailor.text_style_controls import record_view_edit
        previous=dict(settings=before,views=prior_views)
        after=dict(settings=values,views=[(node['id'],_view_state(native.panels[node['id']])) for node in native.cfg['nodes']])
        def restore(root,state):
            view=root.advanced_view;view.cfg.update(copy.deepcopy(state['settings']))
            root.advanced_controls.load(view.cfg)
            target=view.native;target.cfg=view.cfg;target.syncing=True
            try:
                target.place()
                for identifier,ranges in state['views']:
                    if identifier in target.panels:_restore_view(target.panels[identifier],ranges)
            finally:target.syncing=False
            target.refresh_unified()
        record_view_edit(c.plot,'组图设置',previous,after,restore)
        c.refresh_panel_layout()

    def config_nodes(self):
        self.sync_draft()
        return copy.deepcopy(self.nodes)

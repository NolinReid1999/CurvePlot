"""Drag axis titles; tick labels stay fixed. Legend/annotations retain native dragging."""

import copy

from PySide6 import QtCore


class TextDrag(QtCore.QObject):
    def __init__(self, plot):
        super().__init__(plot)
        self.plot = plot
        self.drag = None
        plot.ui.plot_widget.viewport().installEventFilter(self)
        plot.ui.plot_widget.getViewBox().sigResized.connect(self.restore)
        QtCore.QTimer.singleShot(0, self, self.restore)

    def targets(self):
        for key, side in [
            ("x", "bottom"),
            ("top", "top"),
            ("y", "left"),
            ("right", "right"),
        ]:
            axis = self.plot.ui.plot_widget.getAxis(side)
            factor=getattr(axis,'factor_item',None)
            if axis.isVisible() and factor is not None and factor.isVisible():yield key+'_factor',factor
            if axis.isVisible() and axis.label.isVisible():yield key,axis.label

    def restore(self, *args):
        if getattr(self.plot, "_graph_disposed", False):
            return
        for key, label in self.targets():
            old = getattr(label, "_curve_drag_offset", QtCore.QPointF())
            offset = self.plot.presentation.text_offsets.get(key, [0, 0])
            value = QtCore.QPointF(*offset)
            # Axis geometry may have reset label placement; keep a separate native base.
            if label.pos() != getattr(label, "_curve_drag_result", None):
                label._curve_drag_base = label.pos()
            base = getattr(label, "_curve_drag_base", label.pos() - old)
            label.setPos(base + value)
            label._curve_drag_offset = value
            label._curve_drag_result = label.pos()

    def eventFilter(self, view, event):
        if getattr(self.plot, "_graph_disposed", False):
            return False
        from tailor.manual_peaks import picking
        from tailor.point_inspector import point_active
        if picking(self.plot) or point_active(self.plot):
            return False
        t = event.type()
        if (
            t == QtCore.QEvent.MouseButtonPress
            and event.button() == QtCore.Qt.LeftButton
        ):
            pos = self.plot.ui.plot_widget.mapToScene(event.position().toPoint())
            if getattr(self.plot, '_inset_parent', None) is not None:
                from tailor.graph_focus import inset_contains
                if not inset_contains(getattr(self.plot, '_inset_extras', None), pos):
                    return False
            for key, label in self.targets():
                if label.sceneBoundingRect().contains(pos):
                    from tailor.graph_focus import activate_inset, restore_main
                    parent=getattr(self.plot,"_inset_parent",None)
                    if parent is not None:
                        activate_inset(parent,getattr(self.plot,"_inset_extras",None))
                    else:
                        restore_main(getattr(self.plot,"_embedded_parent",self.plot))
                    self.drag = (
                        key,
                        label,
                        pos,
                        label.pos(),
                        copy.deepcopy(self.plot.presentation.text_offsets),
                    )
                    self.select_target(key)
                    return True
        elif t == QtCore.QEvent.MouseMove and self.drag:
            key, label, start, base, before = self.drag
            pos = self.plot.ui.plot_widget.mapToScene(event.position().toPoint())
            delta = pos - start
            label.setPos(base + delta)
            old = before.get(key, [0, 0])
            self.plot.presentation.text_offsets[key] = [
                old[0] + delta.x(),
                old[1] + delta.y(),
            ]
            label._curve_drag_result = label.pos()
            label._curve_drag_offset = QtCore.QPointF(
                *self.plot.presentation.text_offsets[key]
            )
            return True
        elif t == QtCore.QEvent.MouseButtonRelease and self.drag:
            key, label, start, base, before = self.drag
            self.drag = None
            after = copy.deepcopy(self.plot.presentation.text_offsets)
            from tailor.text_style_controls import record_view_edit

            def restore(plot, state):
                plot.presentation.text_offsets = copy.deepcopy(state)
                plot.text_drag.restore()

            record_view_edit(self.plot, "移动轴端倍率" if key.endswith('_factor') else "移动轴标题", before, after, restore)
            self.plot.main_window.mark_project_dirty()
            return True
        elif t == QtCore.QEvent.MouseButtonDblClick:
            pos = self.plot.ui.plot_widget.mapToScene(event.position().toPoint())
            if getattr(self.plot, '_inset_parent', None) is not None:
                from tailor.graph_focus import inset_contains
                if not inset_contains(getattr(self.plot, '_inset_extras', None), pos):
                    return False
            for key, label in self.targets():
                if label.sceneBoundingRect().contains(pos):
                    from tailor.graph_focus import activate_inset, restore_main
                    parent=getattr(self.plot,"_inset_parent",None)
                    if parent is not None:
                        activate_inset(parent,getattr(self.plot,"_inset_extras",None))
                    else:
                        restore_main(getattr(self.plot,"_embedded_parent",self.plot))
                    self.drag = None
                    self.select_target(key,open_editor=True)
                    return True
        return False

    def select_target(self,key,open_editor=False):
        factor=key.endswith('_factor');axis_key=key[:-7] if factor else key
        controls=self.plot.axis_controls
        self.plot.text_selection.select(key if factor else key+'_label')
        controls.select_axis(axis_key,'ticks' if factor else 'label')
        if factor:
            from tailor.text_style_controls import font_spec
            cfg=self.plot.presentation.axes[axis_key]
            editor=controls.factor_editor
            editor.load(cfg.get('factor_style') or font_spec(self.plot.curve_style,axis_key+'_ticks'),cfg.get('factor_text',''))
        else:editor=controls.text_editor
        self.plot.preferences.select_font(editor,'轴端倍率' if factor else controls.current_label.text())
        if open_editor:self.plot.preferences.open_font(editor,'轴端倍率' if factor else controls.current_label.text())
        else:
            from tailor.text_style_controls import reveal_section
            reveal_section(self.plot,controls,'高级刻度格式' if factor else '标题与轴线')

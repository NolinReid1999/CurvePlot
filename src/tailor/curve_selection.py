"""Native curve hit testing and temporary highlight, independent of point picking."""

import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets


class CurveSelection(QtCore.QObject):
    def __init__(self, plot):
        super().__init__(plot)
        self.plot, self.current, self.item = plot, None, None
        self.override_item = None
        self.feedback_item = None
        plot._selected_drawn_key = None
        self.suspended = False
        self.bind()
        plot.ui.plot_widget.scene().sigMouseClicked.connect(self.background_clicked)

    def bind(self):
        items = (
            [(source, series["data"]) for source, series in self.plot._series.items()]
            if self.plot.presentation.multi
            else [(self.plot, self.plot.plot)]
        )
        for source, item in items:
            if getattr(item, "_selection_bound", False):
                continue
            item._selection_bound = True
            item.setCurveClickable(True, width=10)
            clicked=lambda *args,source=source:self.clicked(source,args)
            item.sigClicked.connect(clicked)
            item.curve.sigClicked.connect(clicked)
            item.sigPointsClicked.connect(
                lambda *args, source=source: self.select(source)
            )
        self.refresh()

    def clicked(self, source, args):
        event=next((a for a in args if hasattr(a,'scenePos') and hasattr(a,'button')),None)
        if event is not None and getattr(self,'_handled_click',None) is event:return
        self._handled_click=event
        from tailor.point_inspector import intercept_curve
        key = f"plot:{source.id}:data" if self.plot.presentation.multi else "data"
        if intercept_curve(self.plot, key, event):
            return
        from tailor.manual_peaks import picking
        if picking(self.plot):
            return
        from tailor.graph_focus import activate_inset, restore_main

        parent = getattr(self.plot, "_inset_parent", None)
        if parent is not None:
            activate_inset(parent, getattr(self.plot,"_inset_extras",None))
        else:
            restore_main(getattr(self.plot, "_embedded_parent", self.plot))
        self.select(source)
        if hasattr(self.plot, "preferences"):
            double = any(getattr(a, "double", lambda: False)() for a in args)
            self.plot.preferences.select_curve("data", source, double)

    def select(self, source):
        from tailor.point_inspector import point_active
        if point_active(self.plot):
            return
        from tailor.manual_peaks import picking
        if picking(self.plot):
            return
        if hasattr(self.plot, "fit_actions"):
            self.plot.fit_actions.clear_selection()
        elif self.plot.presentation.multi:
            for fitted in self.plot.model._plots:
                if hasattr(fitted,'fit_actions'):fitted.fit_actions.clear_selection()
        inspector = getattr(self.plot, "point_inspector", None)
        if inspector is not None and inspector.enabled.isChecked():
            return
        if hasattr(self.plot, "annotations") and self.plot.annotations.tool is not None:
            return
        self.override_item = None
        self.plot._selected_drawn_key = None
        if hasattr(self.plot,"annotations") and self.plot.annotations.selected:self.plot.annotations.select(None)
        if hasattr(self.plot,"text_selection"):self.plot.text_selection.select(None)
        self.current = source
        if self.plot.presentation.multi:
            manager = self.plot.curve_manager
            manager.curves.setCurrentIndex(manager.curves.findData(source))
        self.refresh()
        if source is None and hasattr(self.plot,'preferences'):
            self.plot.preferences.clear_curve_target()

    def background_clicked(self, event):
        from tailor.point_inspector import point_active
        if point_active(self.plot):
            return
        if event.button() != QtCore.Qt.LeftButton or getattr(self,'_handled_click',None) is event:
            return
        box = self.plot.ui.plot_widget.getViewBox()
        if not box.sceneBoundingRect().contains(event.scenePos()):
            return
        legend = self.plot.presentation.legend_item
        if legend.isVisible() and legend.sceneBoundingRect().contains(event.scenePos()):
            return
        annotations = getattr(self.plot, "annotations", None)
        if annotations is not None and annotations.blocks_point(event):
            return
        self.current = None
        self.plot._selected_drawn_key = None
        if hasattr(self.plot, "fit_actions"):
            self.plot.fit_actions.clear_selection()
        if self.plot.presentation.multi:
            for source in self.plot.model._plots:
                if hasattr(source,'fit_actions'):source.fit_actions.clear_selection()
        self.override_item = None
        self.refresh()
        if hasattr(self.plot,'preferences'):
            self.plot.text_selection.select(None)
            self.plot.annotations.select(None)
            self.plot.preferences.clear_curve_target()
            self.plot.axis_controls.sync()

    def clear_decoration(self):
        if self.item is not None:
            import shiboken6

            if shiboken6.isValid(self.item):
                self.item.setShadowPen(None)
                self.item.scatter.setPen(self.item.opts.get("symbolPen"))
        self.item = None

    def clear(self):
        """Release the old curve target when another kind of object is picked."""
        self.current = self.override_item = None
        self.plot._selected_drawn_key = None
        self.refresh()
        if hasattr(self.plot, 'preferences'):
            self.plot.preferences.clear_curve_target()
        sources = list(self.plot.model._plots) if self.plot.presentation.multi else [self.plot]
        for source in sources:
            actions = getattr(source, 'fit_actions', None)
            if actions is not None:
                actions.clear_selection()

    def refresh(self):
        key = getattr(self.plot, '_selected_drawn_key', None)
        if key:
            from tailor.preference_pages import available_curves
            resolved = available_curves(self.plot).get(key)
            if resolved is not None:
                self.override_item = resolved[0]
        self.clear_decoration()
        from tailor.point_inspector import point_active
        feedback = self.feedback_item if point_active(self.plot) else None
        if self.suspended or (self.current is None and self.override_item is None and feedback is None):
            return
        item = (
            self.plot._series.get(self.current, {}).get("data")
            if self.plot.presentation.multi
            else self.plot.plot
        )
        item = feedback or self.override_item or item
        if item is None or not item.isVisible():
            return
        self.item = item
        pen = item.opts.get("pen")
        width = pg.mkPen(pen).widthF() if pen is not None else 1.5
        item.setShadowPen(pg.mkPen("#3d9dff", width=width + 5))
        if item.opts.get("symbol") is not None:
            item.scatter.setPen(pg.mkPen("#3d9dff", width=1.5))


def hide_button(plot, parent=None):
    from dataclasses import replace

    button = __import__("tailor.compact_controls",fromlist=["SplitHideButton"]).SplitHideButton(parent)
    button.setText("隐藏当前曲线")
    button.setMinimumSize(150, 30)
    button.setToolTip("点击隐藏当前曲线；右侧下拉菜单可恢复已隐藏曲线。源数据保留。")
    menu = QtWidgets.QMenu(button)
    button.setMenu(menu)

    def visibility(source, visible):
        if plot.presentation.multi:
            info = plot.model.get_plot_info(source)
            if info is None:
                return
            old = info.visible
            info.visible = visible
            plot.draw_plot()
            plot.curve_manager.refresh()
            from tailor.text_style_controls import record_view_edit
            def restore(target, state):
                target.model.get_plot_info(source).visible = state
                target.draw_plot()
                target.curve_manager.refresh()
            record_view_edit(plot,"显示与隐藏曲线",old,visible,restore)
        else:
            plot.apply_curve_style(replace(plot.curve_style, visible=visible))
        plot.main_window.mark_project_dirty()

    def fill():
        menu.clear()
        if plot.presentation.multi:
            hidden = [s for s, i in plot.model._plots.items() if not i.visible]
        else:
            hidden = [plot] if not plot.curve_style.visible and plot.id not in plot.presentation.extra_settings.get("deleted_curves",[]) else []
        for source in hidden:
            menu.addAction(
                "显示 · " + source.model.get_y_col_name(),
                lambda source=source: visibility(source, True),
            )
        if not hidden:
            menu.addAction("没有隐藏的曲线").setEnabled(False)

    def hide_selected():
        prefs = getattr(plot,"preferences",None)
        if prefs and prefs.curve_target[0] == "all":
            for source in (list(plot.model._plots) if plot.presentation.multi else [plot]):
                visibility(source,False)
        else:
            visibility(prefs.curve_target[1] if prefs and prefs.curve_target[0]=="data" else plot.curve_manager.current_plot() if plot.presentation.multi else plot,False)
    button.clicked.connect(hide_selected)
    menu.aboutToShow.connect(fill)
    menu.aboutToShow.connect(lambda: menu.setFixedWidth(button.width()))
    return button

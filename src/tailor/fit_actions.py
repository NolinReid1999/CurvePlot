"""Selection and controls for existing persistent lmfit result records."""

import copy

import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets
from tailor.graph_defaults import derived_width

from tailor.spreadsheet_model import Edit


class FitActions(QtCore.QObject):
    def __init__(self, plot, page):
        super().__init__(plot)
        self.plot, self.page = plot, page
        self.modify_id = None
        self.current_id = None
        self.curves = {}
        self.hidden = __import__("tailor.compact_controls",fromlist=["SplitHideButton"]).SplitHideButton()
        self.hidden.setText("隐藏拟合")
        self.menu = QtWidgets.QMenu(self.hidden)
        self.hidden.setMenu(self.menu)
        self.menu.aboutToShow.connect(self.fill_hidden)
        self.hidden.clicked.connect(self.hide)
        self.delete = QtWidgets.QPushButton("删除拟合")
        self.delete.clicked.connect(self.remove)
        self.bind(plot.fit_plot, None)
        self.sync()

    def bind(self,item,result_id):
        if getattr(item,'_fit_click_bound',False):return
        item._fit_click_bound=True;item._pref_bound=True
        item.setCurveClickable(True,width=12)
        def picked(*args):
            from tailor.fit_workflow import pick
            key='fit' if result_id is None else 'fit:'+str(result_id)
            event=next((a for a in args if hasattr(a,'scenePos') and hasattr(a,'button')),None)
            if event is not None and getattr(self.plot.curve_selection,'_handled_click',None) is event:return
            pick(self.plot,key,item,event)
        item.sigClicked.connect(picked)
        item.curve.sigClicked.connect(picked)

    def current(self):
        return next(
            (
                r
                for r in self.plot.fit_records
                if r["id"] == (self.modify_id or self.current_id)
            ),
            None,
        )

    def select_index(self, index):
        if 0 <= index < len(self.plot.fit_records):
            self.select(self.plot.fit_records[index]["id"])

    def select(self, result_id, *, edit=False):
        from tailor.manual_peaks import picking

        if picking(self.plot):
            return
        record = next((r for r in self.plot.fit_records if r["id"] == result_id), None)
        if record is None:
            return
        self.plot.curve_selection.current = None
        self.plot.curve_selection.override_item=None
        self.plot._selected_drawn_key=None
        self.plot.curve_selection.refresh()
        self.plot.text_selection.select(None)
        self.plot.annotations.select(None)
        host=getattr(self.plot,'_fit_host',self.plot)
        if host is not self.plot:
            host.curve_selection.current=None;host.curve_selection.override_item=None
            host._selected_drawn_key=None;host.curve_selection.refresh()
            host.text_selection.select(None);host.annotations.select(None)
        from tailor.fit_results import StoredFit, restore_settings

        restore_settings(self.plot, record)
        self.plot.active_fit_id = result_id
        self.plot.model.best_fit = StoredFit(record, self.plot.model)
        self.modify_id = result_id if edit else None
        self.current_id = result_id
        if hasattr(self.plot,'preferences'):self.plot.preferences.clear_curve_target()
        host=getattr(self.plot,'_fit_host',None)
        if host is not None and hasattr(host,'preferences'):host.preferences.clear_curve_target()
        self.plot.preset_controls.sync_model()
        self.plot.plot_best_fit()
        self.plot.refresh_legend()
        self.sync()
        host=getattr(self.plot,'_fit_host',None)
        if host is not None and hasattr(host,'fit_router'):
            host.fit_router.select_source(self.plot)
            host.property_tabs.setCurrentWidget(host.fit_router)
            host.queue_source_draw()
        else:
            self.plot.property_tabs.setCurrentWidget(self.page)
        graph=host or self.plot
        key=f'plot:{self.plot.id}:fit' if graph.presentation.multi else 'fit'
        item=graph._series.get(self.plot,{}).get('fit') if graph.presentation.multi else self.plot.fit_plot
        graph._selected_drawn_key=key
        graph.curve_selection.override_item=item
        graph.curve_selection.refresh()
        graph.preferences.curve_target=('drawn',key)
        graph.preferences._curve_allowed=True
        graph.preferences.refresh_targets()
        graph.preferences.sync_curve_context('drawn',key)
        graph.quick_actions.sync()
        from tailor.text_style_controls import reveal_section

        reveal_section(self.plot, self.page, "参数与执行")

    def refresh_result_choices(self,*args):
        if getattr(self.plot, '_publishing_fit', False):
            return
        from tailor.fit_workflow import refresh_results
        from tailor.column_titles import remark
        changed = False
        sheet = self.plot.data_sheet.model
        for record in self.plot.fit_records:
            for entry in [record] + record.get('components', []):
                key = entry.get('column_id')
                if key in sheet.columnLabels():
                    name = remark(sheet, key)
                    if entry.get('name') != name:
                        entry['name'] = name
                        changed = True
        refresh_results(self.plot)
        if changed and not getattr(self.plot, '_publishing_fit', False):
            self.plot.refresh_legend()

    def sync(self):
        active = self.current() is not None
        self.hidden.setEnabled(active)
        self.delete.setEnabled(active)
        if self.plot._fit_job is None:
            self.plot.ui.fit_button.setText(
                "修改拟合" if self.modify_id is not None else "执行拟合"
            )
            self.plot.ui.fit_button.setEnabled(bool(self.plot.model._model_expression.strip()))
        from tailor.fit_workflow import refresh_results
        refresh_results(self.plot)

    def clear_selection(self):
        if self.modify_id is not None or self.current_id is not None:
            self.modify_id = None
            self.current_id = None
            self.sync()

    def set_hidden(self, record_id, hidden):
        from tailor.text_style_controls import record_view_edit

        record = next(r for r in self.plot.fit_records if r["id"] == record_id)
        if record.get('hidden',False) == hidden:
            return
        before = ('hidden' in record, record.get("hidden", False))
        after = (True, hidden)

        def restore(plot, value):
            current = next((r for r in plot.fit_records if r["id"] == record_id), None)
            if current:
                if value[0]:current['hidden'] = value[1]
                else:current.pop('hidden',None)
                plot.plot_best_fit()
                plot.refresh_legend()
                from tailor.choice_catalog import refresh_object_choices
                refresh_object_choices(plot)
                hosts=[item.widget for item in plot.main_window.get_associated_multiplots(plot)]
                host=getattr(plot,'_fit_host',None)
                if host is not None and host not in hosts:hosts.append(host)
                for host in hosts:
                    if getattr(host,'_graph_disposed',False):continue
                    host.refresh_fit_results()
                    host.extras.bands.refresh()
                    refresh_object_choices(host)

        restore(self.plot, after)
        record_view_edit(
            self.plot, "隐藏拟合" if hidden else "显示拟合", before, after, restore
        )

    def hide(self):
        record = self.current()
        if record:
            self.set_hidden(record["id"], True)

    def fill_hidden(self):
        self.menu.clear()
        from tailor.choice_catalog import column_rank
        for r in sorted(self.plot.fit_records,key=lambda r:column_rank(self.plot.data_sheet.model,r.get('column_id'))):
            if r.get("hidden"):
                self.menu.addAction(
                    __import__('tailor.column_titles', fromlist=['display']).display(self.plot.data_sheet.model, r.get('column_id')) or '结果列已删除',
                    lambda checked=False, key=r["id"]: self.set_hidden(key, False),
                )
        if not self.menu.actions():
            self.menu.addAction("没有隐藏的拟合").setEnabled(False)
        self.menu.setFixedWidth(self.hidden.width())

    def remove(self):
        record = self.current()
        if record:
            from types import SimpleNamespace

            from tailor.result_pages import delete_fit

            delete_fit(SimpleNamespace(plot=self.plot, record=record), delete_data=True)
            self.modify_id = None
            self.current_id = None
            self.sync()

    def render(self):
        records = {r["id"]: r for r in self.plot.fit_records}
        from tailor.series_colors import fit_colour
        for key in list(self.curves):
            if key not in records:
                self.plot.ui.plot_widget.removeItem(self.curves.pop(key))
        for key, record in records.items():
            if key == self.plot.active_fit_id:
                continue
            if key not in self.curves:
                item = pg.PlotDataItem(pen=pg.mkPen("#526dc4", width=derived_width(self.plot)))
                item._legend_key = "fit:" + str(key)
                item.setZValue(10)
                self.plot.ui.plot_widget.addItem(item)
                self.bind(item, key)
                self.curves[key] = item
            item = self.curves[key]
            item.setData(record["curve_x"], record["curve_y"], pen=pg.mkPen(fit_colour(self.plot,self.plot,key),width=derived_width(self.plot)))
            item.setLogMode(
                self.plot.presentation.axes["x"]["log"],
                self.plot.presentation.axes["y"]["log"],
            )
            item.setVisible(not record.get("hidden", False))
        if self.plot.active_fit_id in self.curves:
            self.curves[self.plot.active_fit_id].hide()
        active = records.get(self.plot.active_fit_id)
        self.plot.fit_plot.setVisible(bool(active and not active.get("hidden")))
        for curve in getattr(self.plot, "_component_curves", []):
            curve.setVisible(bool(active and not active.get("hidden")))
        host=getattr(self.plot,'_fit_host',None)
        if host is not None and not getattr(host,'_graph_disposed',False):host.queue_source_draw()
        self.sync()


def attach_history(plot, before, data_edit):
    """The existing spreadsheet write and fit records become one undo entry."""
    from tailor.fit_results import StoredFit, show_result
    from tailor.result_pages import fit_tabs, remove_fit_tab

    sheet = plot.data_sheet.model
    after = (copy.deepcopy(plot.fit_records), plot.active_fit_id)

    def restore(state):
        plot.fit_records = copy.deepcopy(state[0])
        plot.active_fit_id = state[1]
        current = next((r for r in plot.fit_records if r["id"] == state[1]), None)
        plot.model.best_fit = StoredFit(current, plot.model) if current else None
        for tab in list(fit_tabs(plot.main_window)):
            if tab.plot is plot:
                remove_fit_tab(plot.main_window, tab)
        for record in plot.fit_records:
            show_result(plot, record, focus=False)
        if hasattr(plot, "fit_actions"):
            plot.fit_actions.modify_id = None
            plot.fit_actions.current_id = state[1]
        plot.plot_best_fit()
        plot.refresh_legend()

    def replay(state, forward):
        plot._publishing_fit = True
        try:
            if (data_edit.forward() if forward else data_edit.backward()) is False:
                return False
        finally:
            plot._publishing_fit = False
        restore(state)
        return True

    sheet._history[sheet._cursor - 1] = Edit(
        "执行拟合与保存结果",
        lambda: replay(before, False),
        lambda: replay(after, True),
        data_edit.size + 65536,
    )
    sheet.historyChanged.emit()

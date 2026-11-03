"""Shared focused-graph picker and actual inspector switching, including insets."""

from PySide6 import QtCore, QtWidgets


class GraphPicker(QtWidgets.QComboBox):
    def __init__(self, doc):
        super().__init__()
        self.doc = doc
        self.setMinimumWidth(0)
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
        self.setAccessibleName("当前图形")
        self.activated.connect(self.choose)
        self.sync()

    def sync(self):
        root = getattr(self.doc, "_embedded_parent", self.doc)
        with QtCore.QSignalBlocker(self):
            caption = root.name
            native = getattr(getattr(root, "advanced_view", None), "native", None)
            panel = getattr(self.doc, "_inset_parent", self.doc)
            if native and panel in native.live():
                caption += f" / 子图{native.live().index(panel)+1}"
            extras = getattr(self.doc, "_inset_extras", None)
            if extras is not None:
                index = next(
                    (
                        i
                        for i, r in enumerate(extras.collection.records)
                        if r["id"] == extras.cfg["inset"]["id"]
                    ),
                    0,
                )
                caption += f" - 放大图{index + 1}"
            if self.count()==1 and self.currentText()==caption and self.currentData()==(root,self.doc):
                return
            self.clear()
            self.addItem(caption, (root, self.doc))

    def showEvent(self,event):
        self.sync()
        super().showEvent(event)

    def showPopup(self):
        self.clear()
        owner = self.doc.main_window
        root = getattr(self.doc, "_embedded_parent", self.doc)
        for root in [root]:
            if not hasattr(root, "presentation"):
                continue
            target = getattr(root, "_active_document", root)
            if getattr(target, "_inset_parent", None):
                target = target._inset_parent
            self.addItem(root.name, (root, target))
            native = getattr(getattr(root, "advanced_view", None), "native", None)
            targets = native.live() if native else [root]
            for j, parent in enumerate(targets):
                extras = getattr(parent, "extras", None)
                if extras:
                    collection = getattr(extras, "collection", None)
                    entries = [collection.controllers[r["id"]] for r in collection.records] if collection else [extras]
                    for k, entry in enumerate(entries):
                        if hasattr(entry, "inset_doc") and entry.cfg['inset'].get('enabled'):
                            self.addItem(
                                root.name
                                + (f" / 子图{j + 1}" if native else "")
                                + f" - 放大图{k + 1}",
                                (root, entry.inset_doc),
                            )
        current_root = getattr(self.doc, "_embedded_parent", self.doc)
        index = next(
            (
                i
                for i in range(self.count())
                if self.itemData(i) == (current_root, self.doc)
            ),
            0,
        )
        self.setCurrentIndex(index)
        super().showPopup()

    def choose(self, index):
        root, target = self.itemData(index)
        owner = root.main_window
        owner.ui.tabWidget.setCurrentWidget(root)
        if owner.window_mode.enabled:
            owner.window_mode.show(root)
        if getattr(target, "_inset_parent", None):
            extras = getattr(target, "_inset_extras", None)
            if extras and not extras.cfg["inset"].get("enabled"):
                extras.collection.set_hidden(extras.cfg["inset"]["id"], False)
            activate_inset(target._inset_parent, extras)
        else:
            restore_main(root)
            native = getattr(getattr(root, "advanced_view", None), "native", None)
            if native and getattr(target, "_panel_id", None):
                native.activate(target._panel_id)
        if getattr(target, "_inspector_initializing", False):
            target._inset_pending_axis = True
            return
        target.property_tabs.setCurrentWidget(target.axis_controls)
        target.axis_controls.graph_picker.sync()
        if self is not target.axis_controls.graph_picker:
            self.sync()


def activate_inset(parent, extras=None):
    from tailor.inset_collection import active

    extras = extras or active(parent.extras)
    doc = extras.inset_doc
    if hasattr(extras, "collection"):
        extras.collection.select(extras.cfg["inset"]["id"], "plot")
    if getattr(doc, "_inspector_initializing", False):
        doc._inset_pending_focus = True
        return
    root = getattr(parent, "_embedded_parent", parent)
    preference_mode = root.preferences.preference_mode()
    if getattr(root, "_active_document", None) is doc:
        doc.axis_controls.graph_picker.sync()
        return
    native = getattr(getattr(root, "advanced_view", None), "native", None)
    if native:
        native.activate(parent._panel_id)
    if not hasattr(root, "_main_inspector_state"):
        root._main_inspector_state = {
            name: getattr(root, name)
            for name in ("preferences", "property_tabs", "quick_actions")
        }
        root._main_inspector_document = parent
    previous_title = root.property_tabs.tabText(root.property_tabs.currentIndex())
    wanted_index = next(
        (
            i
            for i in range(doc.property_tabs.count())
            if doc.property_tabs.tabText(i) == previous_title
        ),
        0,
    )
    doc.property_tabs.setCurrentIndex(wanted_index)
    splitter = extras.root_splitter
    from tailor.inspector_slots import show
    for slot, name in ((1, "quick_actions"), (2, "preferences")):
        show(splitter, slot, getattr(doc, name))
    for name in ("preferences", "property_tabs", "quick_actions"):
        setattr(root, name, getattr(doc, name))
    root._main_inspector_extras = extras
    root._active_document = doc
    if preference_mode:doc.preferences.follow_preference_mode(preference_mode)
    if hasattr(doc,'fit_router'):doc.fit_router.activate()
    doc.axis_controls.graph_picker.sync()
    root.main_window._refresh_feature_menus()


def restore_main(root):
    state = getattr(root, "_main_inspector_state", None)
    if not state:
        return
    parent = root._main_inspector_document
    preference_mode = root.preferences.preference_mode()
    title = root.property_tabs.tabText(root.property_tabs.currentIndex())
    original_tabs = state["property_tabs"]
    original_tabs.setCurrentIndex(
        next(
            (
                i
                for i in range(original_tabs.count())
                if original_tabs.tabText(i) == title
            ),
            0,
        )
    )
    extras = root._main_inspector_extras
    splitter = extras.root_splitter
    from tailor.inspector_slots import show
    for slot, name in ((1, "quick_actions"), (2, "preferences")):
        show(splitter, slot, state[name])
    for name, value in state.items():
        setattr(root, name, value)
    root._active_document = parent
    if preference_mode:root.preferences.follow_preference_mode(preference_mode)
    if hasattr(parent,'fit_router'):parent.fit_router.activate()
    del root._main_inspector_state


class InsetGate(QtCore.QObject):
    def __init__(self, extras):
        super().__init__(extras)
        self.extras = extras
        extras.plot.ui.plot_widget.viewport().installEventFilter(self)

    def eventFilter(self, obj, event):
        e = self.extras
        if event.type() in (
            QtCore.QEvent.MouseButtonPress,
            QtCore.QEvent.MouseButtonDblClick,
        ):
            pos = e.plot.ui.plot_widget.mapToScene(event.position().toPoint())
            collection=getattr(e,'collection',None)
            if collection and collection.frame_at(pos):return False
            if e.cfg["inset"].get("enabled") and inset_contains(e, pos):
                doc = e.inset_doc
                axes = [
                    doc.ui.plot_widget.getAxis(side)
                    for side in ("bottom", "left", "top", "right")
                ]
                hit = any(
                    a.isVisible() and a.sceneBoundingRect().contains(pos) for a in axes
                )
                legend = doc.presentation.legend_item
                hit = hit or (
                    legend.isVisible() and legend.sceneBoundingRect().contains(pos)
                )
                hit = hit or any(
                    i.isVisible() and i.sceneBoundingRect().contains(pos)
                    for i in getattr(getattr(doc, "annotations", None), "items", {}).values()
                )
                if hit:
                    activate_inset(e.plot)
            elif not e.range_roi.sceneBoundingRect().contains(
                pos
            ) and not e.layout_roi.sceneBoundingRect().contains(pos):
                # Object handlers on the main graph restore focus themselves.
                pass
        return False


class InsetWidget:
    """Expose the existing moved PlotItem with the real containing viewport."""

    def __init__(self, original, container, item):
        self.original, self.container, self.item = original, container, item

    def getPlotItem(self):
        return self.item

    def getViewBox(self):
        return self.item.vb

    def close(self):
        self.item.close()
        self.original.plotItem = None
        self.original.centralWidget = None
        QtWidgets.QWidget.close(self.original)

    def scene(self):
        return self.item.scene()

    def viewport(self):
        return self.container.viewport()

    def mapToScene(self, *args):
        return self.container.mapToScene(*args)

    def mapFromScene(self, *args):
        return self.container.mapFromScene(*args)

    def __getattr__(self, name):
        return (
            getattr(self.item, name)
            if hasattr(self.item, name)
            else getattr(self.original, name)
        )


def create_inset_document(extras):
    import copy

    from tailor.plot_tab import PlotTab
    from tailor.text_style_controls import apply_text_styles

    parent = extras.plot
    owner = parent.main_window
    deferred = bool(getattr(extras, '_defer_inset_inspector', False)
                    or getattr(owner, '_project_reveal_pending', False))
    source = (
        (parent.curve_manager.current_plot() or next(iter(parent.model._plots)))
        if parent.presentation.multi else parent
    )
    owner._plot_num += 1
    if parent.presentation.multi:
        from dataclasses import replace

        from tailor.multiplot_tab import MultiPlotTab

        doc = MultiPlotTab(
            owner,
            parent.name + " - 放大图",
            owner._plot_num,
            parent.model.x_label,
            parent.model.y_label,
            defer_inspector=deferred, inset_parent=parent,
        )
        for source, info in parent.model._plots.items():
            doc.add_plot(source)
            doc.model._plots[source] = replace(info, style=copy.deepcopy(info.style))
        doc.draw_plot()
    else:
        doc = PlotTab(
            owner, parent.name + " - 放大图", owner._plot_num,
            source.data_sheet, source.model.x_col, source.model.y_col,
            source.model.x_err_col, source.model.y_err_col,
            defer_inspector=deferred, inset_parent=parent,
            initial_style=copy.deepcopy(source.curve_style),
        )
    doc._inset_parent = parent
    if deferred and getattr(owner, '_project_reveal_pending', False):
        from tailor.project_files import hold_restoring_inspector
        hold_restoring_inspector(doc)
    doc._inset_extras = extras
    doc._embedded_parent = getattr(parent, "_embedded_parent", parent)
    doc.curve_style = copy.deepcopy(source.curve_style)
    if not parent.presentation.multi:
        doc.model = copy.copy(source.model)
        doc.model._parameters = copy.deepcopy(source.model._parameters)
        doc.fit_records = copy.deepcopy(source.fit_records)
        doc.active_fit_id = source.active_fit_id

        def sync_fit(*args):
            if getattr(doc, "_graph_disposed", False):
                return
            doc.model.best_fit = source.model.best_fit
            doc.fit_records = copy.deepcopy(source.fit_records)
            doc.active_fit_id = source.active_fit_id
            doc.update_model_curves()

        source.data_refreshed.connect(sync_fit)
        sync_fit()
    doc.model.x_label, doc.model.y_label = parent.model.x_label, parent.model.y_label
    cfg = extras.cfg["inset"]
    state = copy.deepcopy(cfg.get("graph_settings", parent.presentation.to_dict()))
    if not cfg.get("graph_settings"):
        from tailor.text_style_controls import font_spec

        state['margins'] = {side: 0 for side in ('left', 'right', 'top', 'bottom')}
        for prefix, axis in state['axes'].items():
            axis['title_visible'] = False
            key = prefix + '_ticks'
            spec = font_spec(parent.curve_style, key)
            spec['size'] = max(6, spec['size'] - 3)
            doc.curve_style.text_styles[key] = spec
    state["extra_settings"] = {}
    state["trend_sources"] = []
    doc.presentation.load(state)
    doc.presentation.legend["visible"] = False
    doc.refresh_ui()
    item = doc.ui.plot_widget.getPlotItem()
    scene = item.scene()
    scene.removeItem(item)
    parent.ui.plot_widget.scene().addItem(item)
    # Selection frames use scene coordinates and stay in the containing scene.
    if hasattr(doc, "text_selection"):
        old_scene = doc.text_selection.rect.scene()
        old_scene.removeItem(doc.text_selection.rect)
        item.scene().addItem(doc.text_selection.rect)
    original = doc.ui.plot_widget
    original.centralWidget = None
    doc.ui.plot_widget = InsetWidget(original, parent.ui.plot_widget, item)
    if hasattr(doc, "text_drag"):
        doc.text_drag.plot.ui.plot_widget.viewport().installEventFilter(doc.text_drag)
    if hasattr(doc, "point_inspector"):
        doc.point_inspector.enabled.setChecked(False)
    extras.park = QtWidgets.QWidget(parent)
    extras.park.hide()
    from tailor.inspector_slots import splitter_for
    extras.root_splitter = splitter_for(parent.preferences)

    def inspector_ready():
        # Use the same staged native inspector as ordinary Draw; only the
        # containing viewport changes. No source data or second renderer exists.
        for i in range(doc.property_tabs.count()):
            if doc.property_tabs.tabText(i) in {"拟合", "处理", "高级", "导出"}:
                doc.property_tabs.setTabEnabled(i, False)
        doc.point_inspector.enabled.setChecked(False)
        doc.range_controls.crop_button.setEnabled(False)
        doc.extras.inset_toggle.setEnabled(False)
        doc.extras.collection.add.setEnabled(False)
        doc.extras.collection.add.setToolTip("放大图复用公共坐标轴与线条设置")
        from tailor.inspector_slots import prepare
        for slot, name in ((1, "quick_actions"), (2, "preferences")):
            prepare(extras.root_splitter, slot, getattr(doc, name),
                    anchor=getattr(parent, name))
        selected = not hasattr(extras, "collection") or extras.collection.selected == cfg["id"]
        if cfg.get("enabled") and selected and getattr(doc, "_inset_pending_focus", False):
            activate_inset(parent, extras)
            if getattr(doc, "_inset_pending_axis", False):
                doc.property_tabs.setCurrentWidget(doc.axis_controls)
        doc._inset_pending_focus = doc._inset_pending_axis = False
        if hasattr(doc, '_restore_placeholder'):
            from tailor.project_files import release_restoring_inspector
            release_restoring_inspector(doc)

    if getattr(doc, "_inspector_initializing", False):
        doc.inspector_ready.connect(inspector_ready)
    else:
        inspector_ready()
    doc.setParent(extras.park)
    doc.hide()

    def persist(*args):
        cfg = extras.cfg["inset"]
        cfg["graph_settings"] = doc.presentation.to_dict()
        cfg["curve_style"] = doc.curve_style.to_dict()
        cfg["x_label"] = doc.model.x_label
        cfg["y_label"] = doc.model.y_label

    for name in ("apply_axes", "apply_legend"):
        callback = getattr(doc.presentation, name)

        def apply(*args, callback=callback, **kw):
            result = callback(*args, **kw)
            persist()
            return result

        setattr(doc.presentation, name, apply)
    if cfg.get("curve_style"):
        from tailor.curve_style import CurveStyle

        doc.curve_style = CurveStyle(**cfg["curve_style"])
    doc.model.x_label = cfg.get("x_label", doc.model.x_label)
    doc.model.y_label = cfg.get("y_label", doc.model.y_label)
    apply_text_styles(doc)
    doc.apply_curve_style(doc.curve_style, dirty=False)
    if hasattr(doc, "data_refreshed"):
        doc.data_refreshed.connect(persist)
    else:
        original_draw = doc.draw_plot

        def draw(*args, **kwargs):
            result = original_draw(*args, **kwargs)
            persist()
            return result

        doc.draw_plot = draw

    def sync_range(*args):
        if getattr(extras, "_setting_range", False) or not hasattr(extras, "range_roi"):
            return
        from tailor.graph_presentation import display, physical

        _, xkey, ykey = extras.inset_source()
        xr, yr = [
            display(
                physical(values, doc.presentation.axes[source]),
                parent.presentation.axes[target],
            )
            for values, source, target in zip(
                item.vb.viewRange(), ("x", "y"), (xkey, ykey)
            )
        ]
        if not all(__import__("numpy").isfinite(v).all() for v in (xr, yr)):
            return
        with QtCore.QSignalBlocker(extras.range_roi):
            extras.range_roi.setPos([xr[0], yr[0]])
            extras.range_roi.setSize([xr[1] - xr[0], yr[1] - yr[0]])
        extras.cfg["inset"]["range"] = [xr[0], yr[0], xr[1], yr[1]]
        if hasattr(extras, "lines"):
            extras.update_lines()

    # Layout, font and axis-visibility updates also emit sigRangeChanged.
    # Only an intentional range edit may redefine the source ROI.
    item.vb.sigRangeChangedManually.connect(sync_range)
    extras.sync_inset_range=sync_range
    extras.inset_doc = doc
    extras.inset = item

    def pick(event):
        if getattr(doc,'_presentation_scene',None) is item.scene():return
        if inset_contains(extras, event.scenePos()):
            doc._select_presentation(event)

    item.scene().sigMouseClicked.connect(pick)
    return item


def inset_contains(extras, scene_pos):
    """Invisible cropped corners do not own clicks, focus or text dragging."""
    import shiboken6

    item = getattr(extras, 'inset', None)
    return bool(item is not None and shiboken6.isValid(item) and item.isVisible()
                and item.shape().contains(item.mapFromScene(scene_pos)))


def is_inset_event(plot, event):
    from tailor.inset_collection import entries

    return any(
        inset_contains(e, event.scenePos())
        for e in entries(plot)
    )

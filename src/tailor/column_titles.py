"""Column display titles bind only to their first associated graph."""


def letters(column):
    n, text = column + 1, ""
    while n:
        n, d = divmod(n - 1, 26)
        text = chr(65 + d) + text
    return text


def title(model, key):
    labels = list(model.columnLabels())
    if key not in labels:
        return ""
    column = labels.index(key)
    return model.column_metadata(column).get("title", letters(column))


def first_graph(sheet, key):
    return next(
        (
            p
            for p in sheet.main_window.get_plots()
            if p.data_sheet is sheet and key in (p.model.x_col, p.model.y_col)
        ),
        None,
    )


def table_changed(sheet, key):
    plot = first_graph(sheet, key)
    if plot is None:
        return
    from tailor.text_style_controls import apply_text_styles

    for axis, column in (("x", plot.model.x_col), ("y", plot.model.y_col)):
        if key == column:
            value = title(sheet.model, key)
            target = (
                ("top" if axis == "x" else "right")
                if plot.presentation.single_sides[axis] in {"top", "right"}
                else axis
            )
            holder = plot.presentation if target in {"top", "right"} else plot.model
            setattr(holder, target + "_label", value)
    apply_text_styles(plot)
    if hasattr(plot, "axis_controls"):
        plot.axis_controls.sync_text()


def axis_changed(plot, axis, value, *, record=True):
    if plot.presentation.multi:
        return
    dimension = "x" if axis in {"x", "top"} else "y"
    assigned = plot.presentation.single_sides[dimension]
    active = (
        "top" if assigned == "top" else "right" if assigned == "right" else dimension
    )
    if axis != active:
        return
    key = plot.model.x_col if dimension == "x" else plot.model.y_col
    sheet = plot.data_sheet
    if first_graph(sheet, key) is plot:
        labels = list(sheet.model.columnLabels())
        if key in labels:
            sheet.model.set_column_metadata(
                labels.index(key), title=value, _record_edit=record
            )


def display(model, key):
    """UI labels only; stable column IDs and expression names remain untouched."""
    keys = list(model.columnLabels())
    if key not in keys:
        return ""
    index = keys.index(key)
    meta = model.column_metadata(index)
    return letters(index) + " · " + (meta.get("comment") or meta["name"])


def remark(model, key):
    keys = list(model.columnLabels())
    if key not in keys:
        return ""
    meta = model.column_metadata(keys.index(key))
    return meta.get("comment") or meta["name"]


def metadata_changed(sheet, key):
    """Refresh labels synchronously without refitting or copying numeric arrays."""
    from tailor.document_names import sources
    import shiboken6
    owner = sheet.main_window
    if not shiboken6.isValid(sheet) or not shiboken6.isValid(owner) or not shiboken6.isValid(owner.ui.tabWidget):
        return
    sheet.ui.data_view.viewport().update()
    tabs = owner.ui.tabWidget
    for i in range(tabs.count()):
        doc = tabs.widget(i)
        items = sources(doc)
        if items and any(s.data_sheet is sheet and (key is None or s.model.y_col == key) for s in items):
            captions = tuple((s.data_sheet.id, s.model.y_col, remark(s.data_sheet.model, s.model.y_col)) for s in items)
            doc._source_name_captions = captions
    controls = getattr(owner,"tab_controls",None)
    if controls is not None:
        controls.refresh()
    for i in range(tabs.count()):
        doc=tabs.widget(i)
        for attr in ("processing_controls","advanced_controls"):
            control=getattr(doc,attr,None)
            if control is not None and shiboken6.isValid(control):
                if hasattr(control,"sync_objects_text"):
                    control.sync_objects_text()
                elif hasattr(control,"sync_refs"):
                    control.sync_refs()

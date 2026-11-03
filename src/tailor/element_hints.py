"""Describe an already resolved element command without changing selection."""


def target_caption(doc, chosen):
    if chosen is None:
        return "请先选择对象"
    from tailor.column_titles import display

    kind, key = chosen
    if kind == "columns":
        labels = list(doc.model.columnLabels())
        names = [display(doc.model, labels[i]) for i in doc.column_preferences.columns()
                 if 0 <= i < len(labels)]
        return "列 · " + "、".join(names)
    if kind == "curve":
        return display(key.data_sheet.model, key.model.y_col) or "数据曲线"
    if kind == "drawn":
        from tailor.preference_pages import available_curves
        return available_curves(doc).get(key, (None, "绘制曲线"))[1]
    if kind == "fit":
        record = next((r for r in doc.fit_records if r["id"] == key), None)
        return (display(doc.data_sheet.model, record.get("column_id")) or "拟合曲线") if record else "拟合曲线"
    if kind == "curves-all":
        from tailor.element_actions import bulk_curve_targets
        sources, fits = bulk_curve_targets(doc)
        return f"全部曲线（{len(sources) + len(fits)}项）"
    if kind == "annotation":
        from tailor.annotations import annotation_caption
        record = next((r for r in doc.annotations.records if r["id"] == key), None)
        return annotation_caption(record, doc.annotations.records) if record else "标注"
    if kind == "inset":
        from tailor.element_actions import root
        records = root(doc).extras.collection.records
        return next((f"局部放大{i + 1}" for i, r in enumerate(records) if r["id"] == key), "局部放大")
    if kind == "legend":
        return "整个图例"
    if kind == "legend-row":
        from tailor.legend_entries import entry_caption
        return "图例 · " + entry_caption(doc, key)
    if kind in {"axis", "axis-factor"}:
        axis = {"x": "下X轴", "y": "左Y轴", "top": "上X轴", "right": "右Y轴"}.get(key, str(key))
        return axis + ("标题" if kind == "axis" else "倍率")
    if kind == "processing-result":
        from tailor.processing_workflow import selected_record
        record = selected_record(doc.processing_controls)
        if record:
            return "、".join(display(sheet.model, column) for sheet, column, *_ in record["outputs"])
        return "处理结果"
    return "选中元素"

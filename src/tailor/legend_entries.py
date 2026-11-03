"""Legend-only rows; removing a label never removes a plotted series."""

import uuid

import pyqtgraph as pg


def entry_text(plot, key):
    """Resolve hidden rows from live metadata and explicit legend overrides."""
    cfg = plot.presentation.legend
    override = cfg.get('entries', {}).get(key, {}).get('text')
    if override is not None:
        return override
    if key.startswith('panel:'):
        parts=key.split(':',2)
        root=getattr(plot,'_embedded_parent',None)
        native=getattr(getattr(root,'advanced_view',None),'native',None)
        doc=native.panels.get(parts[1]) if native else None
        if doc is not None:
            local=parts[2]
            if not doc.presentation.multi and local.startswith(f'plot:{doc.id}:'):local=local.split(':',2)[2]
            return entry_text(doc,local)
    matched=cfg.get('matches',{}).get(key)
    if key.startswith('custom:') and matched and matched!=key:
        return entry_text(plot,matched)
    custom = next((r['text'] for r in cfg.get('custom_entries', []) if r['key'] == key), None)
    if custom is not None:
        return custom
    from tailor.column_titles import remark
    sources = list(plot.model._plots) if plot.presentation.multi else [plot]
    for source in sources:
        if key == ('data' if not plot.presentation.multi else f'plot:{source.id}:data'):
            return source.model.legend_label or remark(source.data_sheet.model,source.model.y_col)
    from tailor.fit_workflow import fit_owner
    fitted = fit_owner(plot,key)
    if fitted:
        source, identifier = fitted
        record = next((r for r in source.fit_records if r['id'] == identifier), None)
        if record:
            from tailor.fit_results import curve_column
            return remark(source.data_sheet.model,curve_column(record,key)) or record['name']
    cached = getattr(plot.presentation,'_hidden_legend_rows',{}).get(key)
    return cached[1] if cached else '图例项'


def entry_caption(plot, key):
    from tailor.text_accents import caption
    return caption(entry_text(plot,key)).replace('\n',' / ')


def update_source_text(plot, key, previous, current):
    """Formatting an automatic name must not freeze it to an old column title."""
    if previous == current or previous is None:
        return
    from tailor.text_accents import caption, retitle
    entry=plot.presentation.legend.get("entries",{}).get(key,{})
    if "text" in entry:
        if caption(entry["text"]) == previous:
            replacement = retitle(entry["text"], current)
            if replacement is None:
                entry.pop("text")
            else:
                entry["text"] = replacement


def reconcile(plot):
    p, legend = plot.presentation, plot.presentation.legend_item
    cfg = p.legend
    order=cfg.setdefault('entry_order',[])
    for sample,label in legend.items:
        key=getattr(sample.item,'_legend_key',None)
        if key is not None and key not in order:order.append(key)
    hidden = set(cfg.get("hidden_entries", [])) | set(cfg.get("deleted_entries", []))
    visibility = p.extra_settings.get("drawn_visibility", {})
    for sample, label in list(legend.items):
        item = getattr(sample, "_source_item", sample.item)
        key = getattr(item, "_legend_key", None)
        if key in visibility:
            item.setVisible(visibility[key] == "visible")
        if not getattr(item,'_advanced_bar_visible',item.isVisible()):
            hidden.add(key)
    cache = getattr(p, "_hidden_legend_rows", {})
    p._hidden_legend_rows = cache
    for sample, label in list(legend.items):
        key = getattr(sample.item, "_legend_key", None)
        if key in hidden:
            cache[key] = (
                getattr(sample, "_source_item", sample.item),
                getattr(label, "_original_text", label.text),
            )
            legend.removeItem(sample.item)
    for key in list(cache):
        if key not in hidden and getattr(cache[key][0], '_advanced_bar_visible', cache[key][0].isVisible()):
            item, text = cache.pop(key)
            if not any(
                getattr(s.item, "_legend_key", None) == key for s, _ in legend.items
            ):
                legend.addItem(item, entry_text(plot, key))
    custom = {row["key"]: row["text"] for row in cfg.get("custom_entries", [])}
    for sample, label in list(legend.items):
        key = getattr(sample.item, "_legend_key", "")
        if key.startswith("custom:") and key not in custom:
            legend.removeItem(sample.item)
    for key, text in custom.items():
        if key not in hidden and not any(
            getattr(s.item, "_legend_key", None) == key for s, _ in legend.items
        ):
            item = pg.PlotDataItem(pen=pg.mkPen("#9ca3af", width=1.5), symbol=None)
            item._legend_key = key
            legend.addItem(item, entry_text(plot,key))

    # Restored labels retain canonical row order and their effective font.
    keys=[getattr(sample.item,'_legend_key',None) for sample,label in legend.items]
    for key in keys:
        if key not in order:order.append(key)
    ordered=sorted(legend.items,key=lambda row:order.index(getattr(row[0].item,'_legend_key',None)))
    if ordered!=legend.items:
        for i in range(legend.layout.count()-1,-1,-1):legend.layout.removeAt(i)
        legend.items=ordered;legend.rowCount=0
        for sample,label in ordered:legend._addItemToLayout(sample,label)
        legend.updateSize()
    from tailor.text_style_controls import font_spec,native_font,styled_html
    from tailor.appearance import ink
    base=font_spec(plot.curve_style,'legend')
    for sample,label in legend.items:
        key=getattr(sample.item,'_legend_key',None)
        spec={**base,**cfg.get('entries',{}).get(key,{}).get('style',{}), 'spacing': 1.0}
        text=entry_text(plot,key) if key.startswith('custom:') and cfg.get('matches',{}).get(key) else cfg.get('entries',{}).get(key,{}).get('text',getattr(label,'_original_text',label.text))
        if not hasattr(label,'_original_text') or key.startswith('custom:') and cfg.get('matches',{}).get(key):label._original_text=text
        label.item.document().setDefaultFont(native_font(spec))
        label.setText(styled_html(text,spec),size=f"{spec['size']}pt",family=spec['family'],color=ink(spec['color']),italic=spec['italic'],bold=spec['bold'])
        from tailor.cjk_text import apply_weight
        apply_weight(label.item.document(),spec)


def add(plot, text="新图例"):
    key = "custom:" + uuid.uuid4().hex
    plot.presentation.legend.setdefault("custom_entries", []).append(
        {"key": key, "text": text}
    )
    reconcile(plot)
    return key


def remove(plot, key):
    cfg = plot.presentation.legend
    if key.startswith("custom:"):
        cfg["custom_entries"] = [
            r for r in cfg.get("custom_entries", []) if r["key"] != key
        ]
    elif key not in cfg.setdefault("deleted_entries", []):
        cfg["deleted_entries"].append(key)
    reconcile(plot)

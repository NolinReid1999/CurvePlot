"""Tick text adapters over pyqtgraph's positions and Qt's rich text layout."""
import html, json, math
from PySide6 import QtCore, QtGui


def token(value):return format(float(value),'.15g')


def custom(axis,value):
    return axis.settings.get('tick_text',{}).get(token(value))


def specs(axis, result):
    if result is None:return result
    line,ticks,texts=result
    candidates=getattr(axis,'_tick_candidates',[])
    if axis._tickLevels is not None:
        from tailor.graph_presentation import physical
        candidates=[(float(physical([v],axis.settings)[0]),str(s)) for level in axis._tickLevels for v,s in level]
    entries=[];view=axis.linkedView();horizontal=axis.orientation in {'bottom','top'}
    if texts and view is not None and axis.settings.get('labels',True):
        # AxisItem may drop an entire minor text level when its aggregate
        # labels are dense. An explicitly edited label must remain at its
        # original numeric position; leave all native tick marks untouched.
        from tailor.graph_presentation import display
        from tailor.text_accents import caption
        template,flags,_=texts[0]
        for key,rich in axis.settings.get('tick_text',{}).items():
            try:value=float(key);position=float(display([value],axis.settings)[0])
            except (ValueError,TypeError):continue
            low,high=view.viewRange()[0 if horizontal else 1]
            if not math.isfinite(position) or not low<=position<=high:continue
            point=view.mapViewToScene(QtCore.QPointF(position if horizontal else 0,0 if horizontal else position))
            mapped=axis.mapFromScene(point)
            if any(str(text)==caption(rich) and abs((rect.center().x()-mapped.x()) if horizontal else (rect.center().y()-mapped.y()))<2 for rect,_,text in texts):continue
            rect=QtCore.QRectF(template)
            rect.moveCenter(QtCore.QPointF(mapped.x(),rect.center().y()) if horizontal else QtCore.QPointF(rect.center().x(),mapped.y()))
            texts.append((rect,flags,caption(rich)))
            candidates.append((value,caption(rich)))
    for rect,flags,text in texts:
        possible=[(v,s) for v,s in candidates if str(s)==str(text)] or candidates
        value=None
        if possible:
            if view is not None:
                point=view.mapSceneToView(axis.mapToScene(rect.center()))
                from tailor.graph_presentation import physical
                guess=float(physical([point.x() if horizontal else point.y()],axis.settings)[0])
                value=min(possible,key=lambda pair:abs(pair[0]-guess))[0]
            else:value=possible[0][0]
        rich=custom(axis,value) if value is not None else None
        entries.append(dict(rect=QtCore.QRectF(rect),source_rect=QtCore.QRectF(rect),value=value,text=str(text),rich=rich))
    axis._curve_tick_entries=entries
    return result


def document(axis,entry,font):
    from tailor.text_style_controls import styled_html
    from tailor.text_accents import caption
    rich=entry['rich'] if entry['rich'] is not None else html.escape(entry['text']).replace('\n','<br>')
    cfg={'family':font.family(),'size':font.pointSizeF(),'bold':font.bold(),'italic':font.italic(),
         'color':axis.textPen().color().name(),'spacing':1.0,'align':'left'}
    key=(rich,json.dumps(cfg,sort_keys=True))
    cache=getattr(axis,'_tick_documents',{});axis._tick_documents=cache
    if key not in cache:
        if len(cache)>256:cache.clear()
        doc=QtGui.QTextDocument();doc.setDocumentMargin(0);doc.setDefaultFont(font)
        doc.setHtml(styled_html(rich,cfg))
        from tailor.cjk_text import apply_weight
        apply_weight(doc,cfg)
        doc.adjustSize();cache[key]=doc
    return cache[key]


def effective_angle(settings):
    return float(settings.get('tick_angle',0)) if settings.get('tick_angle_enabled',True) else 0.0


def draw(axis,painter,texts):
    angle=effective_angle(axis.settings);entries=getattr(axis,'_curve_tick_entries',[])
    font=axis.style.get('tickFont') or painter.font();rects=[];extent=0
    horizontal=axis.orientation in {'top','bottom'}
    visible=[]
    for i,(rect,flags,text) in enumerate(texts):
        entry=next((e for e in entries if e.get('source_rect',e['rect'])==rect and e['text']==str(text)),dict(rect=rect,value=None,text=text,rich=None))
        visible.append(entry)
        if angle==0 and entry['rich'] is None:
            painter.drawText(rect,int(flags),text);bounds=QtCore.QRectF(rect)
        else:
            doc=document(axis,entry,font);size=doc.size();w,h=size.width(),size.height()
            # The text end is the anchor along the axis; move only outward.
            local=QtCore.QRectF(-w,-h/2,w,h) if angle else QtCore.QRectF(-w/2,-h/2,w,h)
            anchor=rect.center();transform=QtGui.QTransform();transform.rotate(-angle)
            bounds=transform.mapRect(local).translated(anchor)
            if axis.orientation=='bottom':anchor.setY(anchor.y()+rect.top()-bounds.top())
            elif axis.orientation=='top':anchor.setY(anchor.y()+rect.bottom()-bounds.bottom())
            elif axis.orientation=='left':anchor.setX(anchor.x()+rect.right()-bounds.right())
            else:anchor.setX(anchor.x()+rect.left()-bounds.left())
            bounds=transform.mapRect(local).translated(anchor)
            painter.save();painter.setClipping(False);painter.translate(anchor);painter.rotate(-angle)
            painter.translate(local.topLeft())
            # Qt's default document paint palette follows the application,
            # while axis ink follows the independently selected workspace.
            # Supply the same resolved pen used by unrotated labels. Explicit
            # rich-text run colours remain owned by the document's formats.
            context=QtGui.QAbstractTextDocumentLayout.PaintContext()
            context.palette.setColor(QtGui.QPalette.Text,axis.textPen().color())
            doc.documentLayout().draw(painter,context)
            painter.restore()
        rects.append(bounds);entry['rect']=bounds
        extent=max(extent,bounds.height() if horizontal else bounds.width())
    axis._curve_tick_text_rects=rects
    axis._curve_tick_entries=visible
    if abs(getattr(axis,'_tick_rotated_extent',0)-extent)>1:
        axis._tick_rotated_extent=extent
        if not getattr(axis,'_tick_extent_pending',False):
            axis._tick_extent_pending=True
            def resize():
                axis._tick_extent_pending=False
                axis._updateMaxTextSize(extent)
            QtCore.QTimer.singleShot(0,axis,resize)

"""Qt-painted inline accents for fonts without usable combining-mark anchors.

QTextDocument natively embeds data-URI PNGs. Keeping the original text and
format in PNG metadata makes these runs portable and editable after reload.
Scene documents render those records with QTextObjectInterface instead of an
image, preserving vector strokes in SVG/PDF. The editor keeps portable HTML.
"""

import base64
import html
import json
import math
import re
from functools import lru_cache

from PySide6 import QtCore, QtGui


@lru_cache(maxsize=256)
def decode(uri):
    if not uri.startswith("data:image/png;base64,") or len(uri) > 2_000_000:
        return None
    image = QtGui.QImage.fromData(base64.b64decode(uri.split(",", 1)[1]))
    data = image.text("curve-accent")
    try:
        return json.loads(data) if data else None
    except (ValueError, TypeError):
        return None


@lru_cache(maxsize=256)
def metrics(text, encoded):
    spec = json.loads(encoded)
    font = QtGui.QFont(spec.get("family", "Helvetica"))
    font.setPointSizeF(float(spec.get("size", 12)))
    font.setBold(bool(spec.get("bold")))
    font.setItalic(bool(spec.get("italic")))
    font.setUnderline(bool(spec.get("underline")))
    font.setOverline(bool(spec.get("overline")))
    fm = QtGui.QFontMetricsF(font)
    width = max(2, math.ceil(fm.horizontalAdvance(text)) + 2)
    top = max(4, math.ceil(fm.height() * 0.22))
    height = math.ceil(fm.height()) + top
    return font, fm, width, height, top


def paint_accent(painter, text, kind, spec):
    font, fm, _, _, top = metrics(text, json.dumps(spec, sort_keys=True))
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    color = QtGui.QColor(spec.get("color", "#202020"))
    # Qt performs shaping/fallback; painter paths keep the selected glyphs
    # independent of the fonts installed on the machine opening an export.
    glyphs = QtGui.QPainterPath()
    glyphs.addText(QtCore.QPointF(1, top + fm.ascent()), font, text)
    painter.fillPath(glyphs, color)
    bounds = fm.tightBoundingRect(text)
    cx = 1 + bounds.center().x()
    y = max(1.4, top + fm.ascent() + bounds.top() - 2.5)
    if kind == "dot":
        painter.setBrush(color)
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawEllipse(QtCore.QPointF(cx, y), 1.15, 1.15)
    else:
        half = max(3, min(6, bounds.width() * 0.35))
        path = QtGui.QPainterPath(QtCore.QPointF(cx - half, y))
        path.cubicTo(cx - half * 0.3, y - 3, cx + half * 0.3, y + 3, cx + half, y)
        painter.setPen(QtGui.QPen(color, 1.1))
        painter.drawPath(path)


@lru_cache(maxsize=256)
def render(text, kind, encoded):
    spec = json.loads(encoded)
    _, _, width, height, _ = metrics(text, encoded)
    image = QtGui.QImage(
        width * 4, height * 4, QtGui.QImage.Format_ARGB32_Premultiplied
    )
    image.fill(QtCore.Qt.transparent)
    image.setText(
        "curve-accent",
        json.dumps({"text": text, "kind": kind, "style": spec}, ensure_ascii=False),
    )
    painter = QtGui.QPainter(image)
    painter.scale(4, 4)
    paint_accent(painter, text, kind, spec)
    painter.end()
    data = QtCore.QByteArray()
    buffer = QtCore.QBuffer(data)
    buffer.open(QtCore.QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return "data:image/png;base64," + bytes(data.toBase64()).decode(), width, height


def markup(text, kind, spec):
    uri, width, height = render(text, kind, json.dumps(spec, sort_keys=True))
    return f'<img src="{uri}" width="{width}" height="{height}" alt="{html.escape(text, quote=True)}">'


def caption(text):
    """Recover source characters for names without changing portable rich text."""
    def replace(match):
        payload = decode(match[1])
        return html.escape(payload["text"]) if payload else match[0]

    document = QtGui.QTextDocument()
    document.setHtml(re.sub(
        r'<img\b[^>]*\bsrc="(data:image/png;base64,[^"]+)"[^>]*>', replace, text
    ))
    plain=document.toPlainText()
    return re.sub(r'(?<=[A-Za-z\u0370-\u03ff])[\u0303\u0307]', '', plain)


def retitle(text, current):
    """Keep a uniform whole-name accent when its automatic source name changes."""
    payloads = [decode(uri) for uri in re.findall(
        r'<img\b[^>]*\bsrc="(data:image/png;base64,[^"]+)"', text
    )]
    payloads = [payload for payload in payloads if payload]
    if not payloads:
        from tailor.text_layout import selected_letters,alphabetic
        document=QtGui.QTextDocument();document.setHtml(text)
        plain=document.toPlainText();cursor=QtGui.QTextCursor(document);cursor.select(QtGui.QTextCursor.Document)
        rules=[]
        for position,count,char in selected_letters(cursor):
            probe=QtGui.QTextCursor(document);probe.setPosition(position);probe.setPosition(position+count,QtGui.QTextCursor.KeepAnchor)
            fmt=probe.charFormat();chunk=probe.selectedText()
            rules.append(('\u0303' if '\u0303' in chunk else '\u0307' if '\u0307' in chunk else '',
                          fmt.fontOverline(),fmt.verticalAlignment()))
        if not rules or any(rule!=rules[0] for rule in rules):return None
        mark,overline,alignment=rules[0]
        if not mark and not overline and alignment==QtGui.QTextCharFormat.AlignNormal:return None
        def character(char):
            if char=='\n':return '<br>'
            value=html.escape(char)
            if not alphabetic(char):return value
            value+=mark
            if overline:value='<span style="text-decoration:overline">'+value+'</span>'
            if alignment==QtGui.QTextCharFormat.AlignSuperScript:value='<sup>'+value+'</sup>'
            elif alignment==QtGui.QTextCharFormat.AlignSubScript:value='<sub>'+value+'</sub>'
            return value
        return ''.join(character(c) for c in current)
    first = payloads[0]
    if not all(p["kind"] == first["kind"] and p["style"] == first["style"] for p in payloads):
        return None
    return ''.join(
        '<br>' if char == '\n' else html.escape(char) if char.isspace()
        else markup(char, first["kind"], first["style"])
        for char in current
    )


def restyle(text, spec, explicit=False):
    """Migrate old image accents to native shaped Unicode in QTextDocument.

    Native combining marks retain the base glyph's baseline and work identically
    in QTextEdit, QGraphicsTextItem and vector exports. Only explicit run style
    is embedded; the object's global style remains editable.
    """
    from tailor.text_layout import alphabetic
    def replace(match):
        payload=decode(match[1])
        if not payload:return match[0]
        mark={'dot':'\u0307','wave':'\u0303'}.get(payload['kind'],'')
        value=''.join(c+mark if alphabetic(c) else c for c in payload['text'])
        style=dict(payload['style']);fields=set(style.get('_explicit', []))
        style.update({k:v for k,v in spec.items() if explicit or k not in fields})
        if explicit:fields|=set(spec)
        css=[]
        for key,property in [('color','color'),('family','font-family'),('size','font-size')]:
            if key in fields:css.append(f'{property}:{style[key]}' + ('pt' if key=='size' else ''))
        if 'bold' in fields:css.append('font-weight:'+('bold' if style.get('bold') else 'normal'))
        if 'italic' in fields:css.append('font-style:'+('italic' if style.get('italic') else 'normal'))
        value=html.escape(value)
        return '<span style="'+html.escape(';'.join(css),quote=True)+'">'+value+'</span>' if css else value
    return re.sub(r'<img\b[^>]*\bsrc="(data:image/png;base64,[^"]+)"[^>]*>',replace,text)


ACCENT_OBJECT = QtGui.QTextFormat.UserObject + 35
ACCENT_PAYLOAD = QtGui.QTextFormat.UserProperty + 35


class AccentObject(QtGui.QPyTextObject):
    def intrinsicSize(self, document, position, fmt):
        payload = json.loads(fmt.property(ACCENT_PAYLOAD))
        _, _, width, height, _ = metrics(payload["text"], json.dumps(payload["style"], sort_keys=True))
        return QtCore.QSizeF(width, height)

    def drawObject(self, painter, rect, document, position, fmt):
        payload = json.loads(fmt.property(ACCENT_PAYLOAD))
        natural = self.intrinsicSize(document, position, fmt)
        painter.save()
        painter.translate(rect.topLeft())
        painter.scale(rect.width()/natural.width(), rect.height()/natural.height())
        paint_accent(painter, payload["text"], payload["kind"], payload["style"])
        painter.restore()


def install_vector_objects(document):
    """Adapt only accent runs in a scene document; keep persisted HTML intact.

    Uses Qt's registered custom-object interface, without replacing its text
    layout. Retain a Python reference as well as QObject parent ownership.
    """
    if "\ufffc" not in document.toPlainText():
        return False
    handler = getattr(document, "_curve_accent_handler", None)
    if handler is None:
        handler = AccentObject(document)
        document.documentLayout().registerHandler(ACCENT_OBJECT, handler)
        document._curve_accent_handler = handler
    changes = []
    block = document.begin()
    while block.isValid():
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            fmt = fragment.charFormat()
            if fmt.isImageFormat():
                payload = decode(fmt.toImageFormat().name())
                if payload:
                    fmt.setObjectType(ACCENT_OBJECT)
                    fmt.setProperty(ACCENT_PAYLOAD, json.dumps(payload, sort_keys=True))
                    changes.append((fragment.position(), fragment.length(), fmt))
            iterator += 1
        block = block.next()
    for position, length, fmt in changes:
        cursor = QtGui.QTextCursor(document)
        cursor.setPosition(position)
        cursor.setPosition(position+length, QtGui.QTextCursor.KeepAnchor)
        cursor.setCharFormat(fmt)
    return bool(changes)

"""Make CJK fallback explicit so Qt rich text selects the requested font weight."""

import html
import re
from functools import lru_cache

from PySide6 import QtGui


@lru_cache(maxsize=128)
def family_for(requested):
    font = QtGui.QFont(requested)
    if QtGui.QRawFont.fromFont(font).supportsCharacter(0x4E2D):
        return requested
    available = set(QtGui.QFontDatabase.families())
    return next(
        (
            f
            for f in (
                "PingFang SC",
                "Microsoft YaHei",
                "Noto Sans CJK SC",
                "WenQuanYi Micro Hei",
                "SimSun",
                "Arial Unicode MS",
            )
            if f in available
        ),
        requested,
    )


def explicit_fallback(text, spec):
    if not re.search(r"[\u3400-\u9fff]", text):
        return text
    family = html.escape(family_for(spec.get("family", "sans-serif")), quote=True)
    # Inherit the effective run weight. A global bold setting must not override
    # an explicitly normal selection nested inside the rich-text content.
    css = f"font-family:'{family}';"
    parts = re.split(r"(<[^>]*>)", text)
    for i in range(0, len(parts), 2):
        parts[i] = re.sub(
            r"[\u3400-\u9fff]+",
            lambda m: f'<span style="{css}">{m[0]}</span>',
            parts[i],
        )
    return "".join(parts)


def apply_weight(document, spec, resolve_family=True):
    """Qt rich-text fallback can omit CJK emboldening in a Latin font run.

    A small same-color Qt text outline makes requested bold weight consistent
    with Latin glyphs, while retaining native editable/searchable Unicode text.
    """
    from PySide6 import QtCore

    from tailor.appearance import ink

    position = 0
    for char in document.toPlainText():
        units = 2 if ord(char) > 0xFFFF else 1
        if "\u3400" <= char <= "\u9fff":
            cursor = QtGui.QTextCursor(document)
            cursor.setPosition(position)
            cursor.setPosition(position + units, QtGui.QTextCursor.KeepAnchor)
            current = cursor.charFormat()
            if resolve_family:
                requested=(current.fontFamilies() or [spec.get('family','sans-serif')])[0]
                family=family_for(requested)
                family_format=QtGui.QTextCharFormat();family_format.setFontFamilies([family])
                cursor.mergeCharFormat(family_format)
            if current.fontWeight() >= QtGui.QFont.Bold:
                fmt = QtGui.QTextCharFormat()
                fmt.setFontWeight(QtGui.QFont.Bold)
                color = (
                    current.foreground().color()
                    if current.hasProperty(QtGui.QTextFormat.ForegroundBrush)
                    else QtGui.QColor(ink(spec.get("color", "#202020")))
                )
                pen = QtGui.QPen(
                    color,
                    max(0.2, min(0.7, float(spec.get("size", 14)) * 0.035)),
                    QtCore.Qt.SolidLine,
                )
                fmt.setTextOutline(pen)
                cursor.mergeCharFormat(fmt)
            elif current.hasProperty(QtGui.QTextFormat.TextOutline):
                fmt=QtGui.QTextCharFormat();fmt.setTextOutline(QtGui.QPen(QtCore.Qt.NoPen));cursor.mergeCharFormat(fmt)
        position += units

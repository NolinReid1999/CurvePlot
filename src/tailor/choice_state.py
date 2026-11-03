"""Small empty/mixed-state adapters around existing Qt combo boxes."""
from PySide6 import QtCore

EMPTY = '—'
MODEL_EMPTY = '__unselected_model__'
SETTING_EMPTY = '__unselected_setting__'
SETTING_MIXED = '__mixed_setting__'


def show_setting(box, value=None, *, selected=True, mixed=False):
    """Keep real settings intact; never coerce an absent target to item zero."""
    with QtCore.QSignalBlocker(box):
        for data in (SETTING_EMPTY, SETTING_MIXED):
            index=box.findData(data)
            if index>=0:box.removeItem(index)
        if not selected or mixed:
            box.insertItem(0,'多种值' if mixed else EMPTY,SETTING_MIXED if mixed else SETTING_EMPTY)
            box.setCurrentIndex(0)
        else:
            box.setCurrentIndex(box.findData(value))
    box.setEnabled(selected)


def actionable_setting(value):
    return value is not None and value not in (SETTING_EMPTY, SETTING_MIXED)

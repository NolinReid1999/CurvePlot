"""Validated application options; keep project presentation in project files."""
from PySide6 import QtCore, QtWidgets

SCHEMA = {
    'recovery/enabled': (bool, True, None),
    'recovery/minutes': (int, 5, (1, 60)),
    'recovery/versions': (int, 5, (1, 20)),
    'performance/mode': (str, 'balanced', ('balanced', 'responsive')),
    'performance/points': (int, 5000, (1000, 50000)),
    'performance/debounce': (int, 80, (35, 250)),
    'export/dpi': (int, 300, (72, 1200)),
    'export/format': (str, 'png', ('png', 'svg', 'pdf')),
    'export/background': (str, 'graph', ('graph', 'transparent')),
    'export/directory': (str, '', None),
    'project/directory': (str, '', None),
    'undo/entries': (int, 1000, (20, 10000)),
    'undo/mib': (int, 128, (32, 2048)),
}


class Preferences(QtCore.QObject):
    changed = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.store = QtCore.QSettings('PhysicsPlot', 'Preferences')
        self.values = {}
        for key, (kind, default, limits) in SCHEMA.items():
            value = self.store.value(key, default)
            try:
                if kind is bool:
                    if not isinstance(value, bool):
                        text = str(value).lower()
                        if text not in {'true','false','1','0'}: raise ValueError('invalid boolean')
                        value = text in {'true','1'}
                else:
                    value = kind(value)
                self.validate(key, value)
            except (ValueError, TypeError, OverflowError):
                value = default
            self.values[key] = value

    def validate(self, key, value):
        kind, default, limits = SCHEMA[key]
        if type(value) is not kind:
            raise ValueError('无效设置类型：' + key)
        if limits and ((kind is int and not limits[0] <= value <= limits[1]) or
                       (kind is str and value not in limits)):
            raise ValueError('设置超出允许范围：' + key)

    def get(self, key):
        return self.values[key]

    def set(self, key, value):
        self.validate(key, value)
        if self.values[key] != value:
            self.values[key] = value
            self.store.setValue(key, value)
            self.changed.emit(key)


def preferences():
    app = QtWidgets.QApplication.instance()
    if app is None:
        return Preferences()
    if not hasattr(app, '_curve_preferences'):
        app._curve_preferences = Preferences(app)
    return app._curve_preferences


def advanced_limit(configured, exporting=False):
    state = preferences()
    return min(configured, state.get('performance/points')) if not exporting and state.get('performance/mode') == 'responsive' else configured


def export_options(dpi=None):
    state = preferences()
    return (state.get('export/dpi') if dpi is None else dpi,
            state.get('export/background'))

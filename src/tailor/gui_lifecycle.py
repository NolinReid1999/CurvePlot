"""Keep cyclic collection outside native widget construction/event callbacks."""

from PySide6 import QtCore, QtWidgets


def install_gui_collector():
    """Reuse pyqtgraph's GUI-thread collector once per application process.

    Reference counting remains normal. Only cyclic collection is scheduled by
    the existing Qt timer, avoiding automatic collection nested in a native
    callback or in a numeric worker. No environment/system setting is changed.
    """
    app = QtWidgets.QApplication.instance()
    if app is None or QtCore.QThread.currentThread() != app.thread():
        raise RuntimeError('GUI collection policy must be installed on the application thread')
    collector = getattr(app, '_curve_gui_collector', None)
    if collector is None:
        from pyqtgraph.util.garbage_collector import GarbageCollector
        collector = GarbageCollector(interval=1.0)
        collector.timer.setParent(app)
        app._curve_gui_collector = collector
        app.aboutToQuit.connect(collector.timer.stop)
    elif not collector.timer.isActive():
        collector.timer.start(1000)
    return collector

"""Local crash stacks for native failures; never records cell or image contents."""

import faulthandler
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

_log = None
_event_class = None


def valid_event(event, handler):
    """Do not dereference PySide's occasional incorrect borrowed wrapper.

    Same boundary check as Spyder's DebuggingWidget.eventFilter (MIT):
    https://github.com/spyder-ide/spyder/blob/master/spyder/plugins/ipythonconsole/widgets/debugging.py
    The binding's underlying cause is unknown; this is a compatibility guard.
    """
    global _event_class
    if _event_class is None:
        from PySide6.QtCore import QEvent
        _event_class = QEvent
    if isinstance(event, _event_class):
        return True
    breadcrumb('invalid-event-wrapper', handler=handler, returned_type=type(event).__name__)
    return False


def log_folder():
    return Path(os.environ['CURVE_STARTUP_CHECK']) if os.environ.get('CURVE_STARTUP_CHECK') else Path.home()/'Library/Logs/Curve'


def breadcrumb(action, **state):
    """Bounded local navigation evidence; no titles, paths or source values."""
    try:
        folder = log_folder()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder/'navigation.jsonl'
        if path.exists() and path.stat().st_size > 256*1024:
            path.replace(folder/'navigation-previous.jsonl')
        with path.open('a') as stream:
            stream.write(json.dumps(dict(time=datetime.now().isoformat(), pid=os.getpid(), action=action, **state))+'\n')
    except OSError:
        pass


def install():
    global _log
    try:
        folder = log_folder()
        folder.mkdir(parents=True,exist_ok=True)
        path=folder/'faults.log'
        if path.exists() and path.stat().st_size > 2*1024*1024:
            path.replace(folder/'faults-previous.log')
        _log=path.open('a',buffering=1)
        _log.write(f'\nStartup {datetime.now().isoformat()} pid={os.getpid()}\n')
        faulthandler.enable(file=_log,all_threads=True)
        original=sys.excepthook

        def hook(kind,error,stack):
            traceback.print_exception(kind,error,stack,file=_log)
            _log.flush()
            original(kind,error,stack)
        sys.excepthook=hook
    except OSError:
        pass

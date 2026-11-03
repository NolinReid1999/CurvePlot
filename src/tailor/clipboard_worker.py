"""Prepare large clipboard rectangles away from the Qt event loop."""

import time

import numpy as np
from PySide6 import QtCore

from tailor.clipboard_matrix import parse_matrix


def cell_text(value):
    return (
        ""
        if value is None or isinstance(value, (float, np.floating)) and np.isnan(value)
        else str(value)
    )


class ClipboardReader(QtCore.QThread):
    loaded = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, text, parent=None, formats=()):
        super().__init__(parent)
        self.text = text
        self.formats = formats

    def run(self):
        try:
            rows = parse_matrix(self.text, self.formats)
            self.loaded.emit(
                np.asarray(
                    rows,
                    dtype=object
                    if any(k != "numeric" for k in self.formats)
                    else float,
                )
                if rows
                else None
            )
        except (ValueError, MemoryError) as exc:
            self.failed.emit(str(exc))
        finally:
            self.text = ""


class ClipboardWriter(QtCore.QThread):
    loaded = QtCore.Signal(str)
    failed = QtCore.Signal(str)

    def __init__(self, values, parent=None):
        super().__init__(parent)
        self.values = values

    def run(self):
        try:
            chunks = []
            for start in range(0, len(self.values), 2048):
                chunks.append(
                    "\n".join(
                        "\t".join(cell_text(value) for value in row)
                        for row in self.values[start : start + 2048]
                    )
                )
                # CPython string joins can retain the GIL across generator resumes.
                # Yield between bounded chunks so Qt's main thread can handle input.
                time.sleep(0.001)
            text = "\n".join(chunks)
            self.loaded.emit(text)
        except (ValueError, MemoryError) as exc:
            self.failed.emit(str(exc))
        finally:
            self.values = None

"""Cancellable, bounded-chunk serialization of detached project snapshots."""

import gzip
import json
import os
import tempfile
import time
from pathlib import Path

import numpy as np
from PySide6 import QtCore


class SaveCancelled(Exception):
    """The user cancelled before atomic replacement of the destination."""


def write_snapshot(
    snapshot, filename, cancelled=lambda: False, progress=lambda _: None
):
    """Write the existing gzip/JSON format, preserving any prior destination.

    The snapshot contains only copied arrays and ordinary Python values, no Qt
    objects. Chunking/yielding bounds GIL occupancy during numeric conversion.
    Cancellation is effective until the single atomic replacement commit point.
    """
    path = Path(filename)
    total = sum(
        len(column) for sheet in snapshot["sheets"] for column in sheet["data"].values()
    )
    done = 0

    def checkpoint():
        if cancelled():
            raise SaveCancelled
        time.sleep(0.001)

    def encode(value):
        nonlocal done
        if isinstance(value, np.ndarray):
            yield "["
            for start in range(0, len(value), 4096):
                checkpoint()
                if start:
                    yield ","
                values = value[start : start + 4096].tolist()
                yield json.dumps(values, ensure_ascii=False)[1:-1]
                done += len(values)
                progress(min(99, int(100 * done / max(1, total))))
            yield "]"
        elif isinstance(value, dict):
            yield "{"
            for index, (key, item) in enumerate(value.items()):
                if index:
                    yield ","
                yield json.dumps(key, ensure_ascii=False) + ":"
                yield from encode(item)
            yield "}"
        elif isinstance(value, (list, tuple)):
            yield "["
            for index, item in enumerate(value):
                if index:
                    yield ","
                yield from encode(item)
            yield "]"
        else:
            yield json.dumps(value, ensure_ascii=False)

    checkpoint()
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as raw:
            # Level 3 keeps the existing lossless format with much less CPU
            # work than level 9 for long scientific numeric columns.
            with gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=3) as zipped:
                for chunk in encode(snapshot):
                    if cancelled():
                        raise SaveCancelled
                    zipped.write(chunk.encode("utf-8"))
            raw.flush()
            os.fsync(raw.fileno())
        checkpoint()
        os.replace(temporary, path)
        progress(100)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class ProjectWriter(QtCore.QThread):
    progress = QtCore.Signal(int)

    def __init__(self, snapshot, filename, parent=None):
        super().__init__(parent)
        self.snapshot = snapshot
        self.filename = Path(filename)
        self.outcome = None
        self.error = ""

    def write(self):
        write_snapshot(
            self.snapshot,
            self.filename,
            self.isInterruptionRequested,
            self.progress.emit,
        )

    def run(self):
        try:
            self.write()
            self.outcome = "saved"
        except SaveCancelled:
            self.outcome = "cancelled"
        except Exception as error:  # noqa: BLE001 - propagate worker errors without mutating GUI state
            self.outcome, self.error = "failed", str(error)
        finally:
            self.snapshot = None


def write_csv_snapshot(
    snapshot, filename, cancelled=lambda: False, progress=lambda _: None
):
    """Use pandas for CSV formatting, yielding between bounded row blocks."""
    import pandas as pd

    frame = pd.DataFrame(snapshot, copy=False)
    path = Path(filename)
    if cancelled():
        raise SaveCancelled
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            for start in range(0, max(1, len(frame)), 4096):
                if cancelled():
                    raise SaveCancelled
                frame.iloc[start : start + 4096].to_csv(
                    stream, index=False, header=start == 0
                )
                progress(
                    min(
                        99,
                        int(100 * min(start + 4096, len(frame)) / max(1, len(frame))),
                    )
                )
                time.sleep(0.001)
            stream.flush()
            os.fsync(stream.fileno())
        if cancelled():
            raise SaveCancelled
        os.replace(temporary, path)
        progress(100)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_excel_snapshot(
    snapshot, filename, cancelled=lambda: False, progress=lambda _: None
):
    """Openpyxl streaming export with the same atomic replacement/cancel contract."""
    import math

    import numpy as np
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell

    names = list(snapshot)
    rows = len(snapshot[names[0]]) if names else 0
    if rows > 1048575 or len(names) > 16384:
        raise ValueError("超出Excel单表行列上限，请选择CSV导出")
    path = Path(filename)
    fd, temporary = tempfile.mkstemp(
        prefix="." + path.stem + "-", suffix=".xlsx", dir=path.parent
    )
    os.close(fd)
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("数据")

    def values(items):
        result = []
        for value in items:
            if isinstance(value, np.generic):
                value = value.item()
            if isinstance(value, float) and not math.isfinite(value):
                value = None
            if isinstance(value, str):
                cell = WriteOnlyCell(sheet, value=value)
                cell.data_type = "s"  # Text is data, never an executable Excel formula.
                value = cell
            result.append(value)
        return result

    try:
        if cancelled():
            raise SaveCancelled
        sheet.append(values(names))
        for index in range(rows):
            if cancelled():
                raise SaveCancelled
            sheet.append(values(snapshot[name][index] for name in names))
            if index % 4096 == 0:
                progress(min(99, round(100 * index / max(1, rows))))
                time.sleep(0.001)
        workbook.save(temporary)
        if cancelled():
            raise SaveCancelled
        os.replace(temporary, path)
        progress(100)
    finally:
        if not sheet.closed:
            sheet.close()
        workbook.close()
        if os.path.exists(temporary):
            os.unlink(temporary)


class CsvWriter(ProjectWriter):
    def write(self):
        writer = (
            write_excel_snapshot
            if self.filename.suffix.lower() == ".xlsx"
            else write_csv_snapshot
        )
        writer(
            self.snapshot,
            self.filename,
            self.isInterruptionRequested,
            self.progress.emit,
        )

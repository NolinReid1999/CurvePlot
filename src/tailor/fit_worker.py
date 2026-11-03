"""Worker for an isolated PlotModel snapshot."""

from PySide6 import QtCore


class FitJob(QtCore.QThread):
    progress = QtCore.Signal(int)

    def __init__(self, snapshot, parent=None):
        super().__init__(parent)
        self.snapshot = snapshot
        self.result = None
        self.checksum = None
        self.outcome = "pending"
        self.error = ""

    def run(self):
        if self.isInterruptionRequested():
            self.outcome = "cancelled"
            return

        def callback(params, iteration, residual, *args, **kwargs):
            if iteration >= 0 and iteration % 25 == 0:
                self.progress.emit(max(0, iteration))
            return self.isInterruptionRequested()

        try:
            self.snapshot.perform_fit(iter_cb=callback)
            if self.isInterruptionRequested():
                self.outcome = "cancelled"
            else:
                self.result = self.snapshot.best_fit
                self.checksum = self.snapshot._fit_data_checksum
                self.outcome = "success"
        except Exception as e:  # noqa: BLE001 - relay worker failure to GUI
            if self.isInterruptionRequested():
                self.outcome = "cancelled"
            else:
                self.outcome = "failed"
                self.error = str(e)

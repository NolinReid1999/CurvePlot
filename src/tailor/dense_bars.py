"""Pixel-envelope rendering of dense bars; full source geometry stays untouched."""

import numpy as np
import pyqtgraph as pg


class DenseBars(pg.BarGraphItem):
    def __init__(self, *, horizontal=False, **options):
        self.horizontal = horizontal
        self._preview = None
        self._preview_token = None
        super().__init__(**options)

    def paint(self, painter, *args):
        n = len(np.atleast_1d(self.opts.get("x0", [])))
        box = self.getViewBox()
        if n < 5000 or box is None:
            return super().paint(painter, *args)
        dimension = 1 if self.horizontal else 0
        lo, hi = box.viewRange()[dimension]
        view = box.getViewWidget()
        scale = float(view.property("exportPixelScale") or 1) if view else 1
        pixels = max(
            64,
            min(
                16384, round((box.height() if self.horizontal else box.width()) * scale)
            ),
        )
        token = (round(lo, 9), round(hi, 9), pixels)
        if self._preview_token != token:
            x0, x1, y0, y1 = [
                np.asarray(self.opts[key], dtype=float)
                for key in ("x0", "x1", "y0", "y1")
            ]
            center = (y0 + y1) / 2 if self.horizontal else (x0 + x1) / 2
            bins = np.floor((center - lo) / max(hi - lo, 1e-12) * pixels).astype(
                np.int64
            )
            mask = (bins >= 0) & (bins < pixels) & np.isfinite(x0 + x1 + y0 + y1)
            bins = bins[mask]
            if not len(bins):
                return
            arrays = []
            present = np.bincount(bins, minlength=pixels) > 0
            for values, minimum in ((x0, True), (x1, False), (y0, True), (y1, False)):
                result = np.full(pixels, np.inf if minimum else -np.inf)
                (np.minimum.at if minimum else np.maximum.at)(
                    result, bins, values[mask]
                )
                arrays.append(result[present])
            self._preview = pg.BarGraphItem(
                **dict(zip(("x0", "x1", "y0", "y1"), arrays)),
                pen=self.opts["pen"],
                brush=self.opts["brush"],
            )
            self._preview_token = token
        if self._preview is not None:
            self._preview.paint(painter, *args)

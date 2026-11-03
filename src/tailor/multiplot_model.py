from dataclasses import dataclass, field

import numpy as np

from tailor.plot_tab import PlotTab


@dataclass
class PlotInfo:
    label: str
    color: str
    axis: str = "left"
    x_axis: str = "bottom"
    visible: bool = True
    style: dict = field(default_factory=dict)
    errors: dict = field(
        default_factory=lambda: {
            "x_visible": False,
            "y_visible": False,
            "cap": 4.0,
            "width": 1.0,
            "color": "",
        }
    )


class MultiPlotModel:
    x_label: str
    y_label: str
    x_min: float | None = None
    x_max: float | None = None
    y_min: float | None = None
    y_max: float | None = None
    _plots: dict[PlotTab, PlotInfo]

    def __init__(self, x_label: str, y_label: str) -> None:
        self.x_label = x_label
        self.y_label = y_label
        self._plots = {}

    def add_plot(self, plot: PlotTab, label: str, color: str) -> None:
        self._plots[plot] = PlotInfo(label=label, color=color)

    def remove_plot(self, plot: PlotTab) -> None:
        self._plots.pop(plot, None)

    def uses_plot(self, plot: PlotTab) -> None:
        return plot in self._plots

    def get_plot_info(self, plot: PlotTab) -> PlotInfo | None:
        return self._plots.get(plot, None)

    def get_limits_from_data(self, padding=0.05) -> tuple[float]:
        """Get plot limits from the data points.

        Return the minimum and maximum values of the data points, taking the
        error bars into account.

        Args:
            padding: the relative amount of padding to add to the axis limits.
                Default is .05.

        Returns:
            Tuple of four float values (xmin, xmax, ymin, ymax).
        """
        if not self._plots:
            return -1, 1, -1, 1
        limits = []
        for plot in self._plots:
            x, y, x_err, y_err = plot.model.get_data()

            if not len(x):
                continue
            xmin = float(np.min(x - x_err))
            xmax = float(np.max(x + x_err))
            ymin = float(np.min(y - y_err))
            ymax = float(np.max(y + y_err))

            xrange = xmax - xmin
            yrange = ymax - ymin

            xmin -= padding * xrange
            xmax += padding * xrange
            ymin -= padding * yrange
            ymax += padding * yrange

            limits.append((xmin, xmax, ymin, ymax))

        if not limits:
            return -1, 1, -1, 1
        xmins, xmaxs, ymins, ymaxs = zip(*limits)
        return min(xmins), max(xmaxs), min(ymins), max(ymaxs)

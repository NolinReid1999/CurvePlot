"""Serializable curve presentation shared by Qt previews and Matplotlib exports."""

import math
import re
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class CurveStyle:
    mode: str = "scatter"
    color: str = "#202020"
    line_width: float = 1.5
    marker_size: float = 5.0
    marker: str = "o"
    line_style: str = "solid"
    font_size: float = 14.0
    font_family: str = "sans-serif"
    transparent: bool = False
    visible: bool = True
    text_styles: dict = field(default_factory=dict)
    opacity: float = 1.0
    cap: str = "round"
    join: str = "round"
    fill: bool = False
    fill_color: str = "#cfe8ff"
    marker_fill: bool = True
    marker_step: int = 1
    step_mode: bool = False

    def __post_init__(self):
        if self.mode not in {
            "scatter",
            "line",
            "line_scatter",
            "bar", "area", "step", "stem",
        } or self.line_style not in {
            "solid",
            "dash",
            "dot",
            "dashdot",
            "dashdotdot",
            "longdash",
            "shortdash",
        }:
            raise ValueError("Unknown curve mode or line style")
        if self.marker not in {"o", "s", "t", "d", "+", "x", "star"}:
            raise ValueError("Unknown marker")
        if (
            not isinstance(self.color, str)
            or re.fullmatch(r"#[0-9a-fA-F]{6}", self.color) is None
        ):
            raise ValueError("Curve color must be #RRGGBB")
        for name, lower, upper in (
            ("line_width", 0.1, 20),
            ("marker_size", 1, 30),
            ("font_size", 6, 48),
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (float, int))
                or not math.isfinite(value)
                or not lower <= value <= upper
            ):
                raise ValueError(f"Invalid {name}: expected {lower}–{upper}")
        if (
            not isinstance(self.font_family, str)
            or not 1 <= len(self.font_family) <= 128
            or not isinstance(self.transparent, bool)
            or not isinstance(self.visible, bool)
        ):
            raise ValueError("Invalid font or transparency setting")

        if (
            not 0 <= self.opacity <= 1
            or self.cap not in {"round", "flat", "square"}
            or self.join not in {"round", "bevel", "miter"}
            or not 1 <= self.marker_step <= 10000
        ):
            raise ValueError("无效曲线外观设置")
        if not isinstance(self.text_styles, dict) or {
            key for key in self.text_styles if not key.startswith("annotation:")
        } - {
            "x_ticks",
            "x_label",
            "y_ticks",
            "y_label",
            "legend",
            "right_ticks",
            "right_label",
            "top_ticks",
            "top_label",
        }:
            raise ValueError("Invalid text targets")
        for spec in self.text_styles.values():
            if (
                not isinstance(spec, dict)
                or not {"size", "family"} <= set(spec)
                or set(spec)
                - {
                    "size",
                    "family",
                    "italic",
                    "bold",
                    "color",
                    "underline",
                    "align",
                    "spacing",
                    "background", "text_orientation", "text_fill", "text_fill_opacity",
                }
                or spec.get("text_orientation", "horizontal") not in {"horizontal", "vertical", "ccw90", "cw90"}
                or (spec.get("text_fill", "") != "" and re.fullmatch(r"#[0-9a-fA-F]{6}", spec.get("text_fill", "")) is None)
                or not isinstance(spec.get("text_fill_opacity", .18), (int, float))
                or not 0 <= spec.get("text_fill_opacity", .18) <= 1
                or not isinstance(spec.get("italic", False), bool)
                or not isinstance(spec.get("bold", False), bool)
                or re.fullmatch(r"#[0-9a-fA-F]{6}", spec.get("color", "#202020"))
                is None
                or not isinstance(spec["size"], (int, float))
                or not math.isfinite(spec["size"])
                or not 6 <= spec["size"] <= 48
                or not isinstance(spec["family"], str)
                or not 1 <= len(spec["family"]) <= 128
            ):
                raise ValueError("Invalid object font")

    def to_dict(self):
        return asdict(self)

    def mpl_options(self, color=None):
        return {
            "color": color or self.color,
            "alpha": self.opacity,
            "linestyle": "none"
            if self.mode == "scatter"
            else {
                "solid": "-",
                "dash": "--",
                "dot": ":",
                "dashdot": "-.",
                "dashdotdot": (0, (3, 2, 1, 2, 1, 2)),
                "longdash": (0, (8, 3)),
                "shortdash": (0, (2, 2)),
            }[self.line_style],
            "marker": "None"
            if self.mode == "line"
            else {"t": "^", "star": "*"}.get(self.marker, self.marker),
            "linewidth": self.line_width,
            "markersize": self.marker_size,
        }

"""Bounded, non-executable annotation records; local-model draft hardened here."""

import math
import re


def validate_annotation(record):
    def numeric(value, low=-math.inf, high=math.inf):
        try:
            return (
                type(value) in (int, float)
                and math.isfinite(value)
                and low <= value <= high
            )
        except OverflowError:
            return False

    def choice(value, choices):
        return isinstance(value, str) and value in choices

    def color(value):
        return (
            isinstance(value, str)
            and re.fullmatch(r"#[0-9a-fA-F]{6}", value) is not None
        )

    fields = {
        "id": lambda v: isinstance(v, str) and 0 < len(v) <= 64,
        "kind": lambda v: choice(
            v,
            {
                "text",
                "image",
                "arrow",
                "double_arrow",
                "line",
                "rectangle",
                "ellipse",
                "hline",
                "vline",
            },
        ),
        "anchor": lambda v: choice(v, {"left", "right", "canvas"}),
        "points": lambda v: (
            isinstance(v, list) and len(v) == 4 and all(numeric(p) for p in v)
        ),
        "text": lambda v: isinstance(v, str) and len(v) <= 4096,
        "color": color,
        "fill": lambda v: isinstance(v, str) and (v == "" or color(v)),
        "width": lambda v: numeric(v, 0.1, 20),
        "size": lambda v: numeric(v, 6, 72),
        "family": lambda v: isinstance(v, str) and 0 < len(v) <= 128,
        "bold": lambda v: isinstance(v, bool),
        "visible": lambda v: isinstance(v, bool),
        "locked": lambda v: isinstance(v, bool),
        "rotation": lambda v: numeric(v, -180, 180),
        "linestyle": lambda v: choice(
            v,
            {"solid", "dash", "dot", "dashdot", "dashdotdot", "longdash", "shortdash"},
        ),
    }
    if (
        not isinstance(record, dict)
        or set(record) - set(fields) - {"fill_opacity", "image_data", "aspect_locked"}
        or set(fields) - set(record)
    ):
        raise ValueError("标注字段不完整或含未知字段")
    if not numeric(record.get("fill_opacity", 0.18), 0, 1):
        raise ValueError("填充不透明度无效")
    if record.get("kind") == "image":
        if type(record.get('aspect_locked',True)) is not bool:
            raise ValueError('图片比例锁定状态无效')
        import base64

        payload = record.get("image_data", "")
        if not isinstance(payload, str) or len(payload) > 17 * 1024 * 1024:
            raise ValueError("图片数据过大")
        try:
            base64.b64decode(payload, validate=True)
        except (ValueError, TypeError) as error:
            raise ValueError("图片数据无效") from error
    for key, check in fields.items():
        if not check(record[key]):
            raise ValueError(f"标注字段无效：{key}")

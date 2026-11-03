"""Vector export using Matplotlib artists, matching native screen-space shapes."""

from matplotlib import colors, patches

from tailor.text_style_controls import export_font_families


def export_annotations(manager, left, right=None):
    # Put every annotation on the top axes, preserving order across dual Y axes.
    host = right if right is not None else left
    for index, r in enumerate(manager.records):
        if not r["visible"] or not manager.representable(r):
            continue
        target = right if r["anchor"] == "right" else left
        if target is None:
            continue
        transform = left.transAxes if r["anchor"] == "canvas" else target.transData
        x1, y1, x2, y2 = r["points"]
        kind = r["kind"]
        zorder = 1000 + index
        fill = colors.to_rgba(r["fill"], 0.18) if r["fill"] else "none"
        options = {
            "edgecolor": r["color"],
            "facecolor": fill,
            "linewidth": r["width"],
            "linestyle": {"solid": "-", "dash": "--", "dot": ":", "dashdot": "-."}[
                r["linestyle"]
            ],
            "zorder": zorder,
            "clip_on": True,
        }
        if kind == "text":
            host.text(
                x1,
                y1,
                r["text"],
                transform=transform,
                color=r["color"],
                fontsize=r["size"],
                fontfamily=export_font_families(r["family"]),
                fontweight="bold" if r["bold"] else "normal",
                rotation=r["rotation"],
                rotation_mode="anchor",
                ha="left",
                va="top",
                parse_math=False,
                bbox={"facecolor": fill, "edgecolor": "none", "pad": 0}
                if r["fill"]
                else None,
                clip_on=True,
                zorder=zorder,
            )
            continue
        if kind in {"hline", "vline"}:
            # Blended axes/data transform gives a full-width/height reference line.
            if kind == "hline":
                transform = (
                    left.transAxes
                    if r["anchor"] == "canvas"
                    else target.get_yaxis_transform()
                )
                a, b = (0, y1), (1, y1)
            else:
                transform = (
                    left.transAxes
                    if r["anchor"] == "canvas"
                    else target.get_xaxis_transform()
                )
                a, b = (x1, 0), (x1, 1)
        else:
            a, b = (x1, y1), (x2, y2)
        if kind in {"rectangle", "ellipse"}:
            # Qt shapes are straight-sided/elliptical in displayed coordinates,
            # also on log axes. Build MPL patches in axes fractions to match.
            a, b = target.transAxes.inverted().transform(transform.transform([a, b]))
            xmin, ymin = min(a[0], b[0]), min(a[1], b[1])
            width, height = abs(b[0] - a[0]), abs(b[1] - a[1])
            if kind == "rectangle":
                artist = patches.Rectangle(
                    (xmin, ymin), width, height, transform=target.transAxes, **options
                )
            else:
                artist = patches.Ellipse(
                    (xmin + width / 2, ymin + height / 2),
                    width,
                    height,
                    transform=target.transAxes,
                    **options,
                )
        else:
            artist = patches.FancyArrowPatch(
                a,
                b,
                arrowstyle={"arrow": "->", "double_arrow": "<->"}.get(kind, "-"),
                shrinkA=0,
                shrinkB=0,
                mutation_scale=12,
                transform=transform,
                **options,
            )
        host.add_patch(artist)

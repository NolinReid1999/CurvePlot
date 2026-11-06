"""Single Curve release identity, shared by desktop and packaging (no GUI imports)."""
VERSION = "1.0.2"
BUILD = None


def version_label():
    return VERSION if BUILD is None else f"{VERSION} build{BUILD}"


def bundle_version():
    return VERSION if BUILD is None else str(BUILD)


def windows_version():
    parts = tuple(int(v) for v in VERSION.split('.'))
    if len(parts) != 3:
        raise ValueError('Curve VERSION must have three numeric components')
    return (*parts, BUILD or 0)

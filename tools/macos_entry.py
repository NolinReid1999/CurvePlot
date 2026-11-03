"""Frozen macOS app bootstrap."""

import os

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("QT_API", "pyside6")

from tailor.physicsplot_desktop import main

if __name__ == "__main__":
    from tailor.crash_diagnostics import install

    install()
    raise SystemExit(main())

# PyInstaller specification: standalone Apple Silicon trial application.
from pathlib import Path
from runpy import run_path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

project = Path(SPECPATH).parent
version = run_path(str(project / "src/tailor/version.py"))
data = collect_data_files("tailor") + copy_metadata("tailor")
data += [(str(project / "packaging/compiled-native-icons/Assets.car"), "."),
         (str(project / "LICENSE"), "licenses"),
         (str(project / "output/pdf/Curve-置信带与预测带指南-0.5.pdf"), "docs"),
         (str(project / "docs/physicsplot/TRIAL.md"), "docs"),
         (str(project / "output/pdf/Curve-功能手册-alpha.27.pdf"), "docs"),
         (str(project / "docs/physicsplot/Curve-功能手册-alpha.27.md"), "docs")]

a = Analysis(
    [str(project / "tools/macos_entry.py")],
    pathex=[str(project / "src")],
    binaries=[], datas=data,
    hiddenimports=["matplotlib.backends.backend_pdf", "matplotlib.backends.backend_svg", "openpyxl", "xlrd", "mpl_toolkits.mplot3d"],
    hookspath=[], hooksconfig={"matplotlib": {"backends": ["Agg", "QtAgg"]}},
    runtime_hooks=[],
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2", "IPython", "pytest", "briefcase"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Curve", debug=False,
          strip=False, upx=False, console=False, argv_emulation=False,
          target_arch="arm64", codesign_identity=None, entitlements_file=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Curve")
app = BUNDLE(
    coll, name="Curve.app", icon=str(project / "packaging/compiled-native-icons/CurveIcon.icns"),
    bundle_identifier="local.physicsplot.desktop",
    info_plist={
        "CFBundleName": "Curve", "CFBundleDisplayName": "Curve", "CFBundleShortVersionString": version["VERSION"],
        "CFBundleVersion": version["bundle_version"](), "NSHighResolutionCapable": True,
        "UIDesignRequiresCompatibility": True,
        "CFBundleIconName": "CurveIcon",
        "CFBundleDevelopmentRegion": "zh_CN", "CFBundleLocalizations": ["zh-Hans", "en"],
        "CFBundleDocumentTypes": [{"CFBundleTypeName": "Curve 项目", "CFBundleTypeIconFile": "CurveIcon.icns", "CFBundleTypeRole": "Editor", "LSHandlerRank": "Owner", "LSItemContentTypes": ["local.curve.project"], "CFBundleTypeExtensions": ["cur"]}],
        "UTExportedTypeDeclarations": [{"UTTypeIdentifier": "local.curve.project", "UTTypeDescription": "CurvePlot 项目", "UTTypeConformsTo": ["public.data", "public.content"], "UTTypeTagSpecification": {"public.filename-extension": ["cur"], "public.mime-type": "application/x-curve-project"}}],
        "NSHumanReadableCopyright": "Based on Tailor by David Fokkema and contributors. GPL-3.0-or-later.",
    },
)

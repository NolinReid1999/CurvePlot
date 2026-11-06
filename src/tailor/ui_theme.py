"""Shared compact Qt styling; native window frame and existing engines retained."""

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets
from tailor.crash_diagnostics import valid_event


def action_icon(name, widget, color="#637080"):
    if name == "settings":
        from tailor.plot_types import icon

        return icon("settings-2", widget, color)
    paths = {
        "updates": '<path d="M20 7v5h-5"/><path d="M19.2 12a7.3 7.3 0 1 1-2-5.2L20 10"/>',
        "panels-top-left": '<rect x="2" y="3" width="13" height="11" rx="1"/><rect x="9" y="10" width="13" height="11" rx="1"/>',
        "sheet": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M3 14h18M9 4v16"/>',
        "plot": '<path d="M3 3v18h18M6 16l4-5 4 3 4-8 3 3"/>',
        "fit": '<path d="M4 18h5l3-12c.6-3 4-3 6-1M7 10h11"/>',
        "processing": '<path d="M4 4h16v16H4zM8 8h8M8 12h3M8 16h3M15 12v4m-2-2h4"/>',
        "close": '<path d="m6 6 12 12M18 6 6 18"/>',
        "down": '<path d="m5 8 7 7 7-7"/>',
        "right": '<path d="m9 5 7 7-7 7"/>',
        "left": '<path d="m15 5-7 7 7 7"/>',
        "minus": '<path d="M6 12h12"/>',
        "plus": '<path d="M12 4v16M4 12h16"/>',
        "undo": '<path d="M9 5 4 10l5 5M4 10h9a6 6 0 0 1 6 6v3"/>',
        "redo": '<path d="m15 5 5 5-5 5m5-5h-9a6 6 0 0 0-6 6v3"/>',
        "save": '<path d="M5 3h12l4 4v14H3V3h2Zm2 0v6h9V3M7 21v-8h10v8"/>',
        "save_as": '<path d="M11 3H3v18h12M7 3v6h4M7 21v-6h4m2-5 6-6 3 3-6 6-4 1Z"/>',
        "home": '<path d="m3 11 9-8 9 8M6 9v12h12V9M10 21v-7h4v7"/>',
        "export": '<path d="M12 3v12m-4-4 4 4 4-4M4 16v5h16v-5"/>',
        "font": '<path d="M4 5h16M12 5v15M8 20h8M4 5v3M20 5v3"/>',
        "delete": '<path d="M3 6h18M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7m4-7v7"/>',
        "hide": '<path d="M3 3l18 18M10 5a11 11 0 0 1 11 7 14 14 0 0 1-4 5M6 6a15 15 0 0 0-3 6 12 12 0 0 0 12 7M10 10a3 3 0 0 0 4 4"/>',
        "curve": '<path d="M3 19c5 0 5-14 10-14s4 12 8 12M3 22h18"/>',
        "point": '<circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="1.5"/><path d="M12 2v4m0 12v4M2 12h4m12 0h4"/>',
        "inset": '<circle cx="10" cy="10" r="7"/><path d="M7 10h6M10 7v6M15 15l6 6"/>',
        "right_axis": '<path d="M20 3v18H3M17 5h3m-3 5h3m-3 5h3M4 17c4 0 3-11 7-11s3 8 6 8"/>',
        "range": '<path d="M4 4v16m16-16v16M4 12h16m-4-4 4 4-4 4M8 8l-4 4 4 4"/>',
        "annotation": '<path d="M3 4h18v13H9l-5 4v-4H3ZM7 8h10M7 12h6"/>',
        "position": '<path d="M12 2v20M2 12h20M9 5l3-3 3 3M9 19l3 3 3-3M5 9l-3 3 3 3M19 9l3 3-3 3"/>',
    }
    from PySide6.QtSvg import QSvgRenderer

    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><g fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{paths[name]}</g></svg>'
    pix = QtGui.QPixmap(48, 48)
    pix.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pix)
    QSvgRenderer(svg.encode()).render(painter)
    painter.end()
    pix.setDevicePixelRatio(2)
    icon = QtGui.QIcon(pix)
    if name == "point":
        selected = QtGui.QPixmap(48, 48)
        selected.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(selected)
        QSvgRenderer(svg.replace(color, "#17467d").encode()).render(painter)
        painter.end()
        selected.setDevicePixelRatio(2)
        icon.addPixmap(selected, QtGui.QIcon.Normal, QtGui.QIcon.On)
    return icon


class QuietFocusStyle(QtWidgets.QProxyStyle):
    def drawPrimitive(self, element, option, painter, widget=None):
        if element == QtWidgets.QStyle.PE_FrameFocusRect:
            return
        super().drawPrimitive(element, option, painter, widget)


def setup_application_style():
    app = QtWidgets.QApplication.instance()
    if getattr(app, "_physicsplot_light_style", False):
        return
    app._physicsplot_light_style = True
    app.setStyle(QuietFocusStyle("Fusion"))
    from tailor.appearance import Appearance

    app._physicsplot_appearance = Appearance(app)
    app._physicsplot_appearance.apply()
    app._physicsplot_component_policy = ComponentPolicy(app)
    app.installEventFilter(app._physicsplot_component_policy)


class ComponentPolicy(QtCore.QObject):
    def eventFilter(self, widget, event):
        if not valid_event(event, 'ComponentPolicy'):
            return True
        kind=event.type()
        if kind not in (QtCore.QEvent.Wheel,QtCore.QEvent.Polish):return False
        if kind == QtCore.QEvent.Wheel and isinstance(
            widget, (QtWidgets.QAbstractSpinBox, QtWidgets.QComboBox)
        ):
            parent = widget.parentWidget()
            while parent is not None and not isinstance(
                parent, QtWidgets.QAbstractScrollArea
            ):
                parent = parent.parentWidget()
            if parent is not None:
                viewport = parent.viewport()
                forwarded = QtGui.QWheelEvent(
                    QtCore.QPointF(
                        viewport.mapFromGlobal(event.globalPosition().toPoint())
                    ),
                    event.globalPosition(),
                    event.pixelDelta(),
                    event.angleDelta(),
                    event.buttons(),
                    event.modifiers(),
                    event.phase(),
                    event.inverted(),
                )
                QtWidgets.QApplication.sendEvent(viewport, forwarded)
            event.accept()
            return True
        if kind == QtCore.QEvent.Polish:
            # Dynamic fit/processing controls are created after card compacting.
            # Apply the same height policy when they enter an inspector page.
            if isinstance(widget, (QtWidgets.QAbstractButton, QtWidgets.QComboBox,
                                   QtWidgets.QLineEdit, QtWidgets.QAbstractSpinBox)):
                parent = widget.parentWidget()
                while parent is not None and not parent.property("inspectorContent") and not parent.isWindow():
                    parent = parent.parentWidget()
                if parent is not None and parent.property('inspectorContent'):
                    from tailor.fold_panel import normalize_control_height
                    normalize_control_height(widget)
            if isinstance(widget, QtWidgets.QAbstractButton):
                widget.setAttribute(QtCore.Qt.WA_MacShowFocusRect, False)
            if isinstance(widget, QtWidgets.QAbstractSpinBox):
                # Typing and up/down keys remain; remove tiny native arrow halves.
                widget.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
                widget.setKeyboardTracking(False)
            if isinstance(widget, QtWidgets.QComboBox):
                widget.setMinimumContentsLength(6)
                widget.setSizeAdjustPolicy(
                    QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon
                )
                widget.setMinimumWidth(0)
                widget.setSizePolicy(
                    QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
                )
            if isinstance(widget, QtWidgets.QPushButton):
                text = widget.text()
                if widget.objectName() == "sectionHeader":
                    return False
                if text.startswith(("裁切", "删除", "移除")):
                    widget.setProperty("intent", "destructive")
                    if text.startswith(("删除", "移除")):
                        from tailor.plot_types import icon
                        widget.setIcon(icon("trash-2", widget, "#d34b48"))
                        widget.setToolTip(widget.toolTip() or text)
                        widget.setAccessibleName(widget.accessibleName() or text)
                elif text.startswith(("应用", "执行拟合", "生成结果", "开始导出")):
                    widget.setProperty("intent", "primary")
        return False


def stylesheet(dark=False):
    from tailor.document_tabs import DocumentTabBar

    arrow = (Path(__file__).parent / "resources" / "ui-chevron.svg").as_posix()
    check = (Path(__file__).parent / "resources" / "ui-check.svg").as_posix()
    result = f"""
        QWidget {{ font-size: 13px; color: #303b49; }}
        QMainWindow, QTabWidget, QScrollArea, QWidget#inspectorBody {{ background: #f4f6f8; }}
        QGroupBox {{ border: 0; margin: 0; padding: 0; background: transparent; }}
        QPushButton, QToolButton {{ background: #ffffff; border: 1px solid #d5dce5; border-radius: 5px; padding: 4px 9px; min-height: 20px; }}
        QPushButton:hover, QToolButton:hover {{ background: #f0f5fb; border-color: #b6c7dc; }}
        QPushButton:pressed, QToolButton:pressed {{ background: #e4edf9; }}
        QPushButton:disabled, QToolButton:disabled {{ color: #a5adb7; border-color: #e4e8ed; background: #f8f9fb; }}
        QPushButton[intent="primary"] {{ color: white; background: #2878cc; border-color: #2878cc; font-weight: 600; }}
        QPushButton[intent="primary"]:hover {{ background: #216bb9; }}
        QPushButton[intent="primary"]:disabled {{ color: #a5adb7; background: #edf1f5; border-color: #dce2e9; }}
        QPushButton:checked, QToolButton:checked {{ background: #e4edf9; border-color: #448ad5; }}
        QPushButton[preferenceKind="font"], QToolButton[preferenceKind="font"] {{ background: #e5f5eb; color: #237342; border: 1px solid #a3cdb0; }}
        QPushButton[preferenceKind="curve"], QToolButton[preferenceKind="curve"] {{ background: #fff0df; color: #a44b0a; border: 1px solid #e7b482; }}
        QPushButton[preferenceKind]:disabled {{ color: #a5adb7; background: #f8f9fb; border-color: #e4e8ed; }}
        QSlider::groove:horizontal {{ height: 4px; background: #c7ced8; border-radius: 2px; }}
        QSlider::handle:horizontal {{ background: #2878cc; width: 14px; margin: -5px 0; border-radius: 7px; }}
        QSlider::groove:vertical {{ width: 4px; background: #c7ced8; border-radius: 2px; }}
        QSlider::handle:vertical {{ background: #2878cc; height: 14px; margin: 0 -5px; border-radius: 7px; }}
        QSlider::handle:horizontal:disabled, QSlider::handle:vertical:disabled {{ background: palette(dark); }}
        QSlider::groove:horizontal:disabled, QSlider::groove:vertical:disabled {{ background: palette(mid); }}
        QPushButton[intent="destructive"] {{ color: #b64b48; border-color: #e5c7c5; background: #fffafa; }}
        QLineEdit, QAbstractSpinBox, QComboBox {{ background: #ffffff; border: 1px solid #d5dce5; border-radius: 5px; padding: 3px 7px; min-height: 22px; selection-background-color: #dceaff; selection-color: #174b84; }}
        QLineEdit:focus, QAbstractSpinBox:focus, QComboBox:focus {{ border-color: #448ad5; }}
        QLineEdit:disabled, QAbstractSpinBox:disabled, QComboBox:disabled {{ color: #a5adb7; background: #f8f9fb; border-color: #e4e8ed; }}
        QToolButton[splitHide="true"] {{ padding:3px 29px 3px 7px; min-height:22px; }}
        QToolButton[splitHide="true"]::menu-button {{ width:25px; border-left:1px solid #d5dce5; }}
        QToolButton[splitHide="true"]::menu-arrow {{ image:url("{arrow}"); width:16px; height:12px; }}
        QComboBox {{ padding: 3px 28px 3px 8px; }}
        QComboBox::drop-down {{ subcontrol-origin: border; subcontrol-position: top right; width: 26px; border: 0; }}
        QComboBox::down-arrow {{ image: url("{arrow}"); width: 16px; height: 12px; }}
        QComboBox QAbstractItemView {{ background: #ffffff; selection-background-color: #e5effb; selection-color: #205e9e; outline: 0; }}
        QComboBox QAbstractItemView::item {{ min-height: 26px; padding: 1px 8px; border: 0; }}
        QComboBox QAbstractItemView::item:hover {{ background: #f0f5fb; }}
        QWidget#numberStepper QToolButton {{ min-height: 24px; padding: 0; border-radius: 4px; }}
        QWidget#numberStepper QAbstractSpinBox {{ border: 0; background: transparent; border-radius: 0; padding: 2px; }}
        QWidget#numberStepper QAbstractSpinBox:focus {{ border:0; background:#e3efff; }}
        QHeaderView QComboBox[columnRole="true"] {{ border: 1px solid #bfc9d6; border-radius: 4px; background: #ffffff; padding: 1px 0px 1px 5px; }}
        QHeaderView QComboBox[columnRole="true"]::drop-down {{ width: 18px; }}
        QHeaderView QComboBox[columnRole="true"]::down-arrow {{ width: 12px; height: 10px; }}
        QToolButton[axisSelector="true"] {{ padding: 3px; min-height: 46px; max-height: 46px; }}
        QToolButton[axisSelector="true"]:checked {{ background: #e4edf9; border-color: #2878cc; color: #246fc2; }}
        QToolButton::menu-indicator {{ image: url("{arrow}"); width: 16px; height: 12px; subcontrol-position: right center; right: 7px; }}
        QToolButton::menu-button {{ width: 26px; border-left: 1px solid #d5dce5; }}
        QToolButton::menu-arrow {{ image: url("{arrow}"); width: 16px; height: 12px; }}
        QWidget#projectControls QToolButton {{ background: transparent; border: 1px solid #d5dce5; border-radius: {DocumentTabBar.CORNER_RADIUS}px; padding: 0; font-weight: bold; }}
        QWidget#projectControls QToolButton[projectSelector="true"] {{ padding: 0 30px 0 8px; }}
        QWidget#projectControls QToolButton:hover, QWidget#projectControls QToolButton:focus {{ background: transparent; border-color: #b6c7dc; }}
        QWidget#projectControls QToolButton:pressed, QWidget#projectControls QToolButton:checked {{ background: transparent; border-color: #637080; }}
        QTextEdit, QPlainTextEdit, QListWidget {{ background: #ffffff; border: 1px solid #dfe4eb; border-radius: 5px; padding: 5px; }}
        QCheckBox {{ spacing: 6px; min-height: 24px; background: transparent; }}
        QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid #bfc9d6; border-radius: 4px; background: white; }}
        QCheckBox::indicator:checked {{ image: url("{check}"); background: #2878cc; border-color: #2878cc; }}
        QCheckBox::indicator:disabled {{ background: #eef1f5; border-color: #dce2e9; }}
        QPushButton, QToolButton {{ outline: none; }}
        QWidget#fitParameterList, QWidget#fitParameterList QWidget {{ background: transparent; }}
        QWidget#fitParameterList QLineEdit, QWidget#fitParameterList QAbstractSpinBox {{ background: #ffffff; }}
        QMenu {{ border: 1px solid #d5dce5; border-radius: 8px; background: #ffffff; padding: 5px; }}
        QMenu::item {{ padding: 8px 8px; min-height:18px; border-radius: 4px; }}
        QMenu::item:selected {{ background: #e5effb; color: #205e9e; }}
        QTabWidget::pane {{ border: 0; }}
        QTabWidget::tab-bar {{ alignment: left; }}
        QTabWidget#inspectorTabs::tab-bar {{ left: 8px; }}
        QTabWidget#inspectorTabs QTabBar::tab {{ font-size:14px; font-weight:600; background: transparent; color: #768191; border: 0; border-bottom: 2px solid transparent; padding: 7px 5px; margin: 4px 0; }}
        QTabWidget#inspectorTabs QTabBar::tab:selected {{ color: #246fc2; background: #e4edf9; border-bottom-color: #2878cc; border-top-left-radius: 6px; border-top-right-radius: 6px; font-weight: 600; }}
        QWidget[foldCard="true"] {{ background: #ffffff; border: 1px solid #dfe4eb; border-radius: 8px; }}
        QPushButton#sectionHeader {{ font-size:14px; text-align: left; font-weight: 600; background: transparent; border: 0; padding: 2px 0; }}
        QLabel[cardTitle="true"] {{font-size:14px;font-weight:600;}}
        QLabel[muted="true"] {{ color: #7b8795; font-size: 11px; }}
        QTableView {{ background: white; alternate-background-color: #f9fafc; gridline-color: #e6eaf0; border: 0; selection-background-color: #e1edfc; selection-color: #203c60; }}
        QHeaderView::section {{ background: #f5f7fa; color: #788493; border: 0; border-right: 1px solid #e1e6ed; border-bottom: 1px solid #e1e6ed; padding: 4px; }}
        QHeaderView QLineEdit {{ background: transparent; border: 1px solid transparent; }}
        QHeaderView QLineEdit:focus {{ background: white; border-color: #448ad5; }}
        QHeaderView QComboBox {{ background: #eaf0f6; border: 0; padding: 2px 5px; padding-right: 22px; }}
        QSplitter::handle {{ background: #e1e6ed; width: 1px; }}
        QWidget#quickActions {{ background: #f4f6f8; }}
        QWidget#quickActions QToolButton {{ padding: 0; border: 0; background: transparent; }}
        QWidget#quickActions QToolButton:hover {{ background: #e5ecf5; }}
        QWidget#quickActions QToolButton:checked {{ background: #dceafb; }}
        QLabel#documentCounts {{ color: #7a8593; font-size: 11px; }}
        QFrame#transientNotice {{ background: #ffffff; border: 1px solid #d5dce5; border-radius: 7px; }}
        QScrollBar:horizontal {{ background: #f4f6f8; height:9px; margin:1px; }}
        QScrollBar::handle:horizontal {{ background:#c7ced8; border-radius:4px; min-width:28px; }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width:0; }}
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background:transparent; }}
        QScrollBar:vertical {{ background: #f4f6f8; width: 9px; margin: 1px; }}
        QScrollBar::handle:vertical {{ background: #c7ced8; border-radius: 4px; min-height: 28px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    """
    result += "QTabWidget#tabWidget::pane { border-top: 1px solid #c6cdd6; } QMenu { background: #ffffff; color: #303b49; } QMenu::item:selected { background: #dceaff; }"
    if dark:
        import re

        replacements = {
            "#303b49": "#e9edf4",
            "#ffffff": "#000000",
            "#f4f6f8": "#000000",
            "#f9fafc": "#000000",
            "#f8f9fb": "#000000",
            "#f5f7fa": "#000000",
            "#fffafa": "#000000",
            "#edf1f5": "#000000",
            "#eef1f5": "#000000",
            "#eaf0f6": "#000000",
            "#d5dce5": "#343a43",
            "#dfe4eb": "#303640",
            "#dfe4ea": "#303640",
            "#e1e6ed": "#303640",
            "#e6eaf0": "#252a31",
            "#c6cdd6": "#3a424e",
            "#e4e8ed": "#252a31",
            "#dce2e9": "#303640",
            "#e4edf9": "#122a43",
            "#dceaff": "#173b62",
            "#dceafb": "#173b62",
            "#e1edfc": "#173b62",
            "#e5effb": "#173b62",
            "#e5ecf5": "#122a43",
            "#f0f5fb": "#10243a",
            "#e6ecf3": "#122a43",
            "#174b84": "#b9dcff",
            "#203c60": "#cde5ff",
            "#205e9e": "#b9dcff",
            "#246fc2": "#70b4ff",
            "#c7ced8": "#3a424e",
            "#bfc9d6": "#536070",
            "#7b8795": "#a6b1c0",
            "#768191": "#a6b1c0",
            "#788493": "#a6b1c0",
        }
        result = re.sub(
            r"#[0-9a-fA-F]{6}", lambda m: replacements.get(m[0], m[0]), result
        )
        result = result.replace("background: white", "background: #000000")
    if dark:
        result += 'QPushButton[preferenceKind="font"], QToolButton[preferenceKind="font"] { background:#102a1a; color:#9cd6af; border-color:#396c49; } QPushButton[preferenceKind="curve"], QToolButton[preferenceKind="curve"] { background:#38200b; color:#ffbd79; border-color:#80532a; }'
    result += "QWidget#quickActions QToolButton, QWidget#quickActions QToolButton[preferenceKind] { background:transparent; border:1px solid transparent; padding:0; } QWidget#quickActions QToolButton:pressed, QWidget#quickActions QToolButton:checked { background:#dceaff; border:1px solid #448ad5; } QWidget#quickActions QToolButton:disabled { color:#b8c0ca; background:transparent; border-color:transparent; }"
    if dark:
        result += "QWidget#quickActions QToolButton:pressed, QWidget#quickActions QToolButton:checked {background:#123554;border-color:#59a5f1;} QWidget#quickActions QToolButton:disabled {color:#454b54;}"
    return result


def apply_theme(window):
    window.setPalette(QtGui.QPalette())
    # Preserve useful error/progress messages without a permanent bottom row.
    window.statusBar().hide()
    from tailor.notices import Notice
    notice = Notice(window)
    window.statusBar().messageChanged.connect(notice.message)
    window._notice = notice


def palette_stylesheet():
    """One stable stylesheet; theme switches update palette roles, not every selector."""
    import re

    result = stylesheet(False)
    backgrounds = {
        "#ffffff": "base",
        "#f9fafc": "base",
        "#f5f7fa": "alternate-base",
        "#f4f6f8": "window",
        "#f8f9fb": "alternate-base",
        "#fffafa": "alternate-base",
        "#edf1f5": "alternate-base",
        "#eef1f5": "alternate-base",
        "#f0f5fb": "alternate-base",
        "#eaf0f6": "alternate-base",
        "#dceaff": "highlight",
        "#dceafb": "highlight",
        "#e4edf9": "highlight",
        "#e5effb": "highlight",
        "#e1edfc": "highlight",
        "#e5ecf5": "highlight",
        "#e3efff": "highlight",
        "#e1e6ed": "mid",
        "#c7ced8": "midlight",
    }
    colors = {
        "#303b49": "text",
        "#7b8795": "placeholder-text",
        "#768191": "placeholder-text",
        "#788493": "placeholder-text",
        "#7a8593": "placeholder-text",
        "#637080": "placeholder-text",
        "#a5adb7": "dark",
        "#b8c0ca": "dark",
        "#246fc2": "link",
        "#205e9e": "link",
        "#174b84": "link",
        "#203c60": "text",
    }
    edge = {
        "#d5dce5",
        "#dfe4eb",
        "#e1e6ed",
        "#e4e8ed",
        "#c6cdd6",
        "#bfc9d6",
        "#dce2e9",
        "#b6c7dc",
    }

    def convert(match):
        prop, value = match.group(1), match.group(2).lower()
        role = (
            backgrounds.get(value)
            if prop.startswith("background")
            else colors.get(value)
            if prop == "color"
            else "mid"
            if value in edge
            else None
        )
        return prop + ": " + ("palette(" + role + ")" if role else value)

    result = re.sub(
        r"(background(?:-color)?|color|border-color|border-(?:top|right|bottom|left)-color)\s*:\s*(#[0-9a-fA-F]{6})",
        convert,
        result,
    )
    # Border shorthand contains width/style before the color.
    for color in edge:
        result = re.sub(r"(border[^:;{}]*:[^;{}]*?)" + color, r"\1palette(mid)", result)
    result = result.replace("background: white", "background: palette(base)")
    result += "QPushButton[preferenceKind], QToolButton[preferenceKind] {background:palette(button);color:palette(button-text);border-color:palette(mid);} QPushButton[preferenceKind]:disabled {background:palette(alternate-base);color:palette(dark);border-color:palette(mid);} QWidget#quickActions QToolButton[preferenceKind] {background:transparent;border-color:transparent;} QWidget#quickActions QToolButton:pressed, QWidget#quickActions QToolButton:checked {background:palette(highlight);border-color:palette(link);}"
    return result

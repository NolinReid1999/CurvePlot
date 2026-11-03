"""Native menus and one application-level preferences window."""

from tailor.compact_controls import CheckButton

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets
import shiboken6

RESOURCES = Path(__file__).parent / "resources"


def system_icon():
    dark = (
        QtWidgets.QApplication.instance().styleHints().colorScheme()
        == QtCore.Qt.ColorScheme.Dark
    )
    return QtGui.QIcon(
        str(RESOURCES / ("curve-dark.png" if dark else "curve-light.png"))
    )


def refresh_icon(*args):
    app = QtWidgets.QApplication.instance()
    icon = system_icon()
    app.setWindowIcon(icon)
    for window in app.topLevelWidgets():
        # PySide can return an invalid/wrong borrowed wrapper during native
        # teardown. Never call a QWidget API on that foreign object.
        if isinstance(window, QtWidgets.QWidget) and shiboken6.isValid(window):
            window.setWindowIcon(icon)
    settings = getattr(app, "_curve_settings", None)
    if isinstance(settings, QtWidgets.QWidget) and shiboken6.isValid(settings):
        settings.icon.setPixmap(icon.pixmap(settings.icon.size(), settings.icon.devicePixelRatioF()))


class SettingsWindow(QtWidgets.QDialog):
    def __init__(self):
        super().__init__(None, QtCore.Qt.Window)
        self.setWindowTitle("Curve 设置")
        self.resize(900, 660); self.setMinimumSize(760, 500)
        self.setObjectName("curveSettings"); self._curve_theme_document = True
        root = QtWidgets.QHBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        sidebar = QtWidgets.QWidget(); sidebar.setObjectName("settingsSidebar"); sidebar.setFixedWidth(200)
        side = QtWidgets.QVBoxLayout(sidebar); side.setContentsMargins(14, 24, 14, 16); side.setSpacing(14)
        title = QtWidgets.QLabel("设置"); title.setObjectName("settingsHeading"); side.addWidget(title)
        search = QtWidgets.QLineEdit(); search.setPlaceholderText("搜索设置"); side.addWidget(search)
        self.categories = QtWidgets.QListWidget(); self.categories.setObjectName("settingsCategories")
        self.categories.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.pages = QtWidgets.QStackedWidget(); self.pages.setObjectName("settingsContent")
        from tailor.settings_pages import TITLES, build_pages
        self.page_widgets = build_pages(self)
        from tailor.label_alignment import align_labels
        for name, page in zip(TITLES, self.page_widgets):
            align_labels(page)
            item = QtWidgets.QListWidgetItem(name); item.setSizeHint(QtCore.QSize(170, 38)); self.categories.addItem(item)
            scroll = QtWidgets.QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
            scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn); scroll.setWidget(page); self.pages.addWidget(scroll)
        side.addWidget(self.categories, 1); root.addWidget(sidebar); root.addWidget(self.pages, 1)
        def filter_pages(text):
            for i in range(self.categories.count()): self.categories.item(i).setHidden(text not in self.categories.item(i).text())
            if self.categories.currentItem() and self.categories.currentItem().isHidden():
                visible = next((i for i in range(self.categories.count()) if not self.categories.item(i).isHidden()), -1)
                if visible >= 0: self.categories.setCurrentRow(visible)
        search.textChanged.connect(filter_pages)
        self.categories.currentRowChanged.connect(self.select_page); self.categories.setCurrentRow(0)
        from tailor.appearance import manager
        manager().changed.connect(self.theme); self.theme()

    def select_page(self, index):
        self.pages.setCurrentIndex(index)
        if index >= 0 and hasattr(self.page_widgets[index], 'refresh'): self.page_widgets[index].refresh()

    def theme(self):
        from tailor.appearance import manager
        dark = manager().dark()
        selected, fg = ("#122a43", "#70b4ff") if dark else ("#e4edf9", "#246fc2")
        self.setStyleSheet(f"QListWidget#settingsCategories {{border:0;background:transparent;padding:0;outline:0;}} QListWidget#settingsCategories::item {{border-radius:5px;padding:4px 8px;}} QListWidget#settingsCategories::item:selected {{background:{selected};color:{fg};}} QLabel#settingsHeading {{font-weight:600;font-size:16px;}} QLabel#settingsPageTitle {{font-weight:600;font-size:18px;}}")


def show_settings(about=False):
    app = QtWidgets.QApplication.instance()
    if getattr(app, "_curve_settings", None) is None:
        app._curve_settings = SettingsWindow()
    dialog = app._curve_settings
    if about:
        from tailor.settings_pages import TITLES
        dialog.categories.setCurrentRow(TITLES.index('关于'))
    else:
        dialog.categories.setCurrentRow(0)
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()


TRANSLATIONS = {
    "File": "文件",
    "Edit": "编辑",
    "Sheet": "工作表",
    "Plot": "图形",
    "Help": "帮助",
    "Open…": "打开…",
    "Open...": "打开…",
    "Save": "保存",
    "Save As…": "另存为…",
    "Save As...": "另存为…",
    "New": "新建",
    "Close": "关闭",
    "Quit": "退出 Curve",
    "Copy": "复制",
    "Paste": "粘贴",
    "Cut": "剪切",
    "Delete": "删除",
    "Select All": "全选",
    "Undo": "撤销",
    "Redo": "重做",
    "Preferences": "设置…",
    "Settings": "设置…",
    "Cancel": "取消",
    "OK": "确定",
    "Apply": "应用",
    "Yes": "是",
    "No": "否",
    "Import data…": "导入数据…",
    "Import CSV…": "导入表格…",
    "Import CSV...": "导入表格…",
    "Delimiter": "分隔符",
    "Header": "首行作为列名",
    "Skip rows": "跳过开头行数",
    "Skip footer": "跳过末尾行数",
    "Preview": "预览",
    "Encoding": "编码",
    "Comma": "逗号",
    "Semicolon": "分号",
    "Tab": "制表符",
    "Space": "空格",
    "Detect": "自动检测",
    "Decimal separator": "小数分隔符",
    "Number format": "数字格式",
    "Columns": "列",
    "Rows": "行",
    "New sheet": "新建工作表",
    "New plot": "新建图形",
}

TRANSLATIONS.update(
    {
        "About Tailor": "关于 Curve…",
        "Add Calculated Column": "添加计算列…",
        "Add Column": "添加列",
        "Add Data Sheet": "新建工作表",
        "Add Row": "添加行",
        "Change Plot Source": "更换图形数据源…",
        "Clear Cell Contents": "清空单元格",
        "Clear Menu": "清空最近项目",
        "Create MultiPlot": "创建多曲线图",
        "Create Plot": "绘图…",
        "Duplicate Data Sheet": "复制工作表",
        "Duplicate Data Sheet With Plots": "复制工作表及关联图形",
        "Duplicate Plot": "复制图形",
        "Export CSV": "导出表格 CSV…",
        "Export Graph to PDF": "导出图形为 PDF…",
        "Export Graph to PNG": "导出图形为 PNG…",
        "Import CSV": "导入表格…",
        "Import CSV Into Current Project": "导入表格到当前项目…",
        "Open Recent": "最近项目",
        "Remove Columns": "删除选中列",
        "Remove Rows": "删除选中行",
        "Rename Data Sheet": "重命名工作表…",
        "Rename Plot": "重命名图形…",
        "Preview Graph": "预览图形",
        "Report Issue": "报告问题",
        "Show Documentation": "使用文档",
        "Show Source Code Repository": "开源项目与许可",
        "Type Strange Things": "编辑数据",
        "Column delimiter:": "分隔符：",
        "Number format:": "数字格式：",
        "Use column header:": "首行作为列名：",
        "Header row / number of rows to skip:": "表头所在行／跳过开头行数：",
        "Number of footer rows to skip:": "跳过末尾行数：",
        "Preview:": "预览：",
        "CSV import": "表格预览",
        "Plain text": "原始文本",
        "Dialog": "设置",
        "Uncertainty X:": "X 误差列：",
        "Uncertainty Y:": "Y 误差列：",
        "X-axis:": "X 数据列：",
        "Y-axis:": "Y 数据列：",
        "Data Source:": "工作表：",
        "Name:": "名称：",
    }
)


class ChineseTranslator(QtCore.QTranslator):
    def translate(self, context, source, disambiguation=None, n=-1):
        translated = TRANSLATIONS.get(source.replace("&", ""))
        if translated is not None:
            return translated
        base = getattr(QtWidgets.QApplication.instance(), "_curve_qt_translator", None)
        fallback = base.translate(context, source, disambiguation, n) if base else ""
        return fallback or source


def install_translations(app):
    app._curve_qt_translator = QtCore.QTranslator(app)
    app._curve_qt_translator.load(
        "qtbase_zh_CN", QtCore.QLibraryInfo.path(QtCore.QLibraryInfo.TranslationsPath)
    )
    app.installTranslator(app._curve_qt_translator)
    app._curve_translator = ChineseTranslator(app)
    app.installTranslator(app._curve_translator)


def setup_menus(window):
    app = QtWidgets.QApplication.instance()
    window.menuBar().setNativeMenuBar(True)
    window.projects.host.menuBar().setNativeMenuBar(True)
    if not getattr(app, "_curve_icon_bound", False):
        app.styleHints().colorSchemeChanged.connect(refresh_icon)
        app._curve_icon_bound = True
    refresh_icon()
    action = QtGui.QAction("设置…", window)
    action.setMenuRole(QtGui.QAction.PreferencesRole)
    action.setShortcut(QtGui.QKeySequence("Ctrl+,"))
    action.triggered.connect(lambda: show_settings())
    window.ui.menuFile.addAction(action)
    window._settings_action = action
    about = window.ui.actionAbout_Tailor
    about.setMenuRole(QtGui.QAction.AboutRole)
    about.triggered.disconnect()
    about.triggered.connect(lambda: show_settings(True))
    for menu in window.findChildren(QtWidgets.QMenu):
        title = menu.title().replace("&", "")
        if title in TRANSLATIONS:
            menu.setTitle(TRANSLATIONS[title])
    for a in window.findChildren(QtGui.QAction):
        text = a.text().replace("&", "")
        if text in TRANSLATIONS:
            a.setText(TRANSLATIONS[text])
    window.ui.actionSave.setText("保存")
    window.ui.actionSave_As.setText("另存为…")
    # Functional commands remain in the inspectors and shortcut toolbar.
    # Retain the callback used by graph focus switching without creating menus.
    window.menuBar().removeAction(window.ui.menuPlot.menuAction())
    window._feature_menus = {}
    window._refresh_feature_menus = lambda *args: None

"""Settings cards over the existing project, writer, style and export services."""
import json
from datetime import datetime
from pathlib import Path
from PySide6 import QtCore, QtGui, QtWidgets
from tailor.app_preferences import preferences
from tailor.compact_controls import CheckButton

TITLES = ['自动保存与恢复', '保存位置', '性能选项', '界面外观', '默认格式', '默认导出参数', '撤销容量', '意见反馈', '本地诊断日志', '关于']


def page(title, description):
    widget = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(widget)
    layout.setContentsMargins(28, 28, 28, 24)
    layout.setSpacing(12)
    label = QtWidgets.QLabel(title); label.setObjectName('settingsPageTitle')
    layout.addWidget(label)
    note = QtWidgets.QLabel(description); note.setWordWrap(True); note.setProperty('muted', True)
    layout.addWidget(note)
    return widget, layout


def card(layout, title):
    frame = QtWidgets.QFrame(); frame.setObjectName('settingsCard'); frame.setProperty('foldCard', True)
    frame.setAttribute(QtCore.Qt.WA_StyledBackground)
    outer = QtWidgets.QVBoxLayout(frame); outer.setContentsMargins(14, 12, 14, 12); outer.setSpacing(10)
    label = QtWidgets.QLabel(title); label.setProperty('settingsSection', True); outer.addWidget(label)
    form = QtWidgets.QFormLayout(); form.setHorizontalSpacing(14); form.setVerticalSpacing(7)
    form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
    outer.addLayout(form); layout.addWidget(frame)
    return form


def row(*widgets):
    widget = QtWidgets.QWidget(); layout = QtWidgets.QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(8)
    for item in widgets: layout.addWidget(item, 1 if not isinstance(item, QtWidgets.QLabel) else 0)
    return widget


def button(text, callback):
    result = QtWidgets.QPushButton(text); result.setMinimumHeight(30)
    result.clicked.connect(lambda checked=False: callback())
    return result


def owner():
    window = getattr(QtWidgets.QApplication.instance(), 'window', None)
    return getattr(getattr(window, 'projects', None), 'active', None) or window


def number(key, low, high, unit=''):
    result = QtWidgets.QSpinBox(); result.setRange(low, high); result.setKeyboardTracking(False)
    result.setValue(preferences().get(key)); result.setMinimumWidth(80)
    result.valueChanged.connect(lambda value: preferences().set(key, value))
    return row(result, QtWidgets.QLabel(unit)) if unit else result


def choice(key, items):
    result = QtWidgets.QComboBox()
    for title, value in items: result.addItem(title, value)
    result.setCurrentIndex(result.findData(preferences().get(key)))
    result.activated.connect(lambda index: preferences().set(key, result.itemData(index)))
    return result


def toggle(key, title):
    result = CheckButton(title); result.setChecked(preferences().get(key))
    result.toggled.connect(lambda value: preferences().set(key, value))
    return result


def recovery_page():
    from tailor import recovery
    widget, layout = page(TITLES[0], '定时保存独立的可编辑工程快照；不会覆盖原文件，也不会把未保存的工程标记为已保存。')
    form = card(layout, '自动保存')
    enabled = toggle('recovery/enabled', '启用自动保存')
    interval = number('recovery/minutes', 1, 60, '分钟')
    versions = number('recovery/versions', 1, 20, '份 / 项目会话')
    form.addRow(enabled); form.addRow('保存间隔', interval); form.addRow('保留版本', versions)
    enabled.toggled.connect(interval.setEnabled); interval.setEnabled(enabled.isChecked())
    status = QtWidgets.QLabel(); status.setWordWrap(True)
    table = QtWidgets.QTableWidget(0, 3); table.setHorizontalHeaderLabels(['项目', '保存时间', '大小'])
    table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows); table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
    table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers); table.setMinimumHeight(160)
    table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
    paths = []
    def refresh():
        paths[:] = recovery.entries(); table.setRowCount(len(paths))
        for i, path in enumerate(paths):
            try: name = json.loads(path.with_suffix('.json').read_text()).get('project', '恢复快照')
            except (OSError, ValueError): name = '恢复快照'
            for j, value in enumerate((name, datetime.fromtimestamp(path.stat().st_mtime).strftime('%m-%d %H:%M:%S'), f'{path.stat().st_size/1024:.0f} KB')):
                table.setItem(i, j, QtWidgets.QTableWidgetItem(value))
        status.setText(f'找到 {len(paths)} 份快照。后台计算、导入或初始化期间自动延后。')
    def selected():
        return paths[table.currentRow()] if 0 <= table.currentRow() < len(paths) else None
    def save_now():
        window = owner()
        if window and window.recovery.capture(force=True):
            status.setText('正在后台保存恢复快照…')
        else: status.setText('当前没有待保存的修改，或正在执行其他任务。')
    def restore():
        if selected() and owner(): recovery.restore(owner(), selected())
    def remove():
        path = selected()
        if path and QtWidgets.QMessageBox.question(widget, '删除恢复快照', '仅删除选中的恢复副本，原工程和当前项目不受影响。') == QtWidgets.QMessageBox.Yes:
            try:
                path.unlink(); path.with_suffix('.json').unlink(missing_ok=True); refresh()
            except OSError as error:
                status.setText('无法删除快照：' + str(error))
    form.addRow(button('立即保存快照', save_now))
    layout.addWidget(table)
    layout.addWidget(row(button('刷新列表', refresh), button('恢复为新项目', restore), button('打开快照目录', lambda: open_folder(recovery.folder()))))
    layout.addWidget(button('删除选中快照', remove))
    layout.addWidget(status); layout.addStretch(); refresh()
    connection = recovery.inventory().changed.connect(refresh)
    widget.destroyed.connect(lambda *args: QtCore.QObject.disconnect(connection))
    widget.refresh = refresh; widget.table = table
    return widget


def performance_page():
    widget, layout = page('性能选项', '流畅模式主要改善大规模三维预览和连续调整的响应。完整源数据、拟合及处理精度不变；首次功能组件准备和部分复杂布局仍可能需要等待。')
    form = card(layout, '绘图响应')
    mode = choice('performance/mode', [('均衡（保持现有画质）', 'balanced'), ('流畅（精简三维预览）', 'responsive')])
    points = number('performance/points', 1000, 50000, '点')
    delay = number('performance/debounce', 35, 250, '毫秒')
    form.addRow('性能模式', mode); form.addRow('三维预览', points); form.addRow('重绘合并', delay)
    def changed(*args):
        active = preferences().get('performance/mode') == 'responsive'
        points.setEnabled(active); delay.setEnabled(active)
    mode.activated.connect(changed); changed()
    note = QtWidgets.QLabel('三维预览保留极值，实际显示可能略多于上限。导出沿用图中“点数上限”，不使用流畅模式的额外限制。重绘合并会略延后显示，以合并连续操作；不会加速拟合算法。')
    note.setWordWrap(True); layout.addWidget(note); layout.addStretch()
    return widget


def locations_page():
    widget, layout = page('保存位置', '工程保存为可继续编辑的.cur文件；目录分别用于首次保存/另存为和各类导出。已有工程的再次保存沿用原文件位置。')
    form=card(layout,'默认目录')
    widget.directory_fields={};widget.directory_buttons={};widget.clear_buttons={}
    for name,key,title in [('project','project/directory','工程位置'),('export','export/directory','导出位置')]:
        field=QtWidgets.QLineEdit(preferences().get(key));field.setReadOnly(True)
        field.setMinimumWidth(0);field.setPlaceholderText('沿用最近目录');field.setToolTip(field.text())
        def browse(checked=False,key=key,field=field):
            value=QtWidgets.QFileDialog.getExistingDirectory(widget,'选择默认目录',field.text())
            if value:preferences().set(key,value)
        def clear(checked=False,key=key):preferences().set(key,'')
        choose=button('选择',browse);reset=button('清除',clear)
        for action in (choose,reset):action.setFixedWidth(60)
        form.addRow(title,row(field,choose,reset))
        widget.directory_fields[name]=field;widget.directory_buttons[name]=choose;widget.clear_buttons[name]=reset
    def refresh(key):
        for name,setting in [('project','project/directory'),('export','export/directory')]:
            if key==setting:
                field=widget.directory_fields[name];field.setText(preferences().get(key));field.setToolTip(field.text())
    connection=preferences().changed.connect(refresh)
    widget.destroyed.connect(lambda *args:QtCore.QObject.disconnect(connection))
    layout.addStretch();return widget


def export_page():
    widget, layout = page('默认导出参数', '应用于之后的图形导出；单次明确指定的分辨率优先。SVG/PDF保持矢量输出，DPI主要影响PNG。')
    form = card(layout, '图形导出')
    form.addRow('默认格式', choice('export/format', [('PNG', 'png'), ('SVG', 'svg'), ('PDF', 'pdf')]))
    form.addRow('分辨率', number('export/dpi', 72, 1200, 'DPI'))
    form.addRow('背景', choice('export/background', [('沿用图形', 'graph'), ('透明背景', 'transparent')]))
    layout.addWidget(QtWidgets.QLabel('默认格式用于“默认导出”入口；原PNG/SVG/PDF按钮继续按各自格式导出。'))
    layout.addStretch(); return widget


def undo_page():
    widget, layout = page('撤销容量', '统一控制表格与图形操作使用的全局撤销记录。提高容量会增加内存占用。')
    form = card(layout, '历史容量')
    form.addRow('记录上限', number('undo/entries', 20, 10000, '步'))
    form.addRow('内存上限', number('undo/mib', 32, 2048, 'MiB / 工作表'))
    note = QtWidgets.QLabel('新操作时采用新上限；调低不会立即清除已有历史。超过限制时释放最早记录；单次操作超过内存上限会被拒绝，保留原数据。重开工程不恢复撤销历史。')
    note.setWordWrap(True); layout.addWidget(note)
    from tailor.element_actions import data_setting
    removal = CheckButton('删除曲线时同时删除对应数据'); removal.setChecked(data_setting())
    removal.toggled.connect(lambda value: QtCore.QSettings('PhysicsPlot', 'ElementActions').setValue('delete_data', value))
    form.addRow(removal); layout.addStretch(); return widget


class FeedbackCode(QtWidgets.QWidget):
    """Display the supplied poster intact, without changing its aspect ratio."""
    def __init__(self):
        super().__init__()
        self.setObjectName('feedbackDouyinCode')
        self.source = QtGui.QPixmap(str(Path(__file__).parent / 'resources/feedback-douyin.jpg'))
        self.setMinimumSize(160, 240)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

    def paintEvent(self, event):
        if self.source.isNull():
            return
        size = self.source.size().scaled(self.size().boundedTo(QtCore.QSize(360, 540)), QtCore.Qt.KeepAspectRatio)
        rect = QtCore.QRect(QtCore.QPoint(), size); rect.moveCenter(self.rect().center())
        painter = QtGui.QPainter(self); painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        painter.drawPixmap(rect, self.source)


def feedback_page():
    widget, layout = page('意见反馈', '打开抖音扫一扫，联系 @CurvePlot。')
    layout.addWidget(FeedbackCode(), 1)
    return widget


class AboutContent(QtWidgets.QWidget):
    """Center the icon and credits together as one presentation block."""
    def __init__(self, icon, credits):
        super().__init__()
        self.icon, self.credits = icon, credits
        from tailor.product_shell import system_icon
        icon.setFixedSize(192, 192)
        icon.setPixmap(system_icon().pixmap(icon.size(), self.devicePixelRatioF()))
        box = QtWidgets.QVBoxLayout(self); box.setContentsMargins(0, 0, 0, 0); box.setSpacing(16)
        box.addStretch(); box.addWidget(icon, 0, QtCore.Qt.AlignHCenter)
        box.addWidget(credits); box.addStretch()


def about_page(settings):
    widget, layout = page('关于', 'Curve 科学绘图与数据分析')
    from tailor.physicsplot_desktop import version_label
    settings.icon = QtWidgets.QLabel(); settings.icon.setAlignment(QtCore.Qt.AlignCenter)
    settings.icon.setObjectName('aboutIcon')
    credits = QtWidgets.QWidget(); lines = QtWidgets.QVBoxLayout(credits)
    lines.setContentsMargins(0, 0, 0, 0); lines.setSpacing(6)
    for index, text in enumerate((f'CurvePlot · {version_label()}', '主开发者：NolinReid',
                                  '开发协作：Codex（OpenAI）', '基于 Tailor · GPL-3.0-or-later · David Fokkema 与贡献者')):
        label = QtWidgets.QLabel(text); label.setObjectName(f'aboutCredit{index}')
        label.setAlignment(QtCore.Qt.AlignCenter); label.setWordWrap(True)
        if index < 2:
            label.setStyleSheet('font-size:17px;')
        lines.addWidget(label)
    layout.addWidget(AboutContent(settings.icon, credits), 1)
    return widget


def appearance_page():
    from tailor.appearance import manager
    widget, layout = page('界面外观', '分别设置应用界面与工作区的颜色模式。')
    form = card(layout, '颜色模式'); state = manager()
    for label,key in [('应用颜色','app'),('工作区颜色','workspace')]:
        box = QtWidgets.QComboBox()
        for text,value in [('浅色','light'),('深色','dark'),('跟随系统','system')]: box.addItem(text,value)
        box.setCurrentIndex(box.findData(getattr(state,key+'_mode')))
        box.activated.connect(lambda index,b=box,k=key:state.set_mode(k,b.itemData(index)))
        form.addRow(label,box)
    layout.addStretch(); return widget


def open_folder(path):
    path.mkdir(parents=True, exist_ok=True)
    QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))


def diagnostics_page():
    from tailor.crash_diagnostics import log_folder
    widget, layout = page('本地诊断日志', '日志保留在本机，不自动上传。崩溃堆栈可能包含本机文件路径或异常消息；分享前请查看内容。')
    form = card(layout, '本地日志')
    path = QtWidgets.QLineEdit(str(log_folder())); path.setReadOnly(True); form.addRow('日志目录', path)
    listing = QtWidgets.QListWidget(); listing.setMinimumHeight(140); layout.addWidget(listing)
    def refresh():
        listing.clear()
        for item in sorted(log_folder().glob('*')) if log_folder().exists() else []:
            if item.is_file():
                entry = QtWidgets.QListWidgetItem(f'{item.name}  ·  {item.stat().st_size/1024:.0f} KB'); entry.setData(QtCore.Qt.UserRole, str(item)); listing.addItem(entry)
    def view():
        entry = listing.currentItem()
        if entry:
            dialog = QtWidgets.QDialog(widget); dialog.setWindowTitle('本地诊断日志'); dialog.resize(750, 500)
            box = QtWidgets.QVBoxLayout(dialog); text = QtWidgets.QPlainTextEdit(); text.setReadOnly(True)
            try:
                with Path(entry.data(QtCore.Qt.UserRole)).open('rb') as stream:
                    stream.seek(max(0, Path(entry.data(QtCore.Qt.UserRole)).stat().st_size - 256*1024)); content = stream.read().decode('utf-8', errors='replace')
                text.setPlainText(content)
            except OSError as error: text.setPlainText(str(error))
            box.addWidget(text); box.addWidget(button('关闭', dialog.accept)); dialog.exec()
    form.addRow(row(button('打开日志目录', lambda: open_folder(log_folder())), button('复制目录', lambda: QtWidgets.QApplication.clipboard().setText(str(log_folder())))))
    layout.addWidget(row(button('刷新列表', refresh), button('查看选中日志', view)))
    note = QtWidgets.QLabel('navigation.jsonl记录界面导航，不记录表格和图片内容；faults.log记录Python/原生异常堆栈。较大日志仅预览末尾256KB。')
    note.setWordWrap(True); layout.addWidget(note); layout.addStretch(); refresh(); widget.refresh = refresh
    return widget


def build_pages(settings):
    from tailor.graph_defaults import DefaultsPage
    settings.defaults_page = DefaultsPage()
    return [recovery_page(), locations_page(), performance_page(), appearance_page(), settings.defaults_page, export_page(), undo_page(), feedback_page(), diagnostics_page(), about_page(settings)]

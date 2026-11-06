"""Opt-in UI and nonblocking GitHub update checks; never download or install code."""
import json
import math
import re
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from packaging.version import Version, InvalidVersion
from PySide6 import QtCore, QtGui, QtWidgets, QtNetwork

from tailor.version import version_label

REPOSITORY = 'NolinReid1999/CurvePlot'
ENDPOINT = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
INTERVAL = 24 * 60 * 60
SNOOZE = 7 * INTERVAL
MAX_RESPONSE = 1024 * 1024


@dataclass(frozen=True, order=True)
class ReleaseVersion:
    number: Version
    build: int = 0

    @property
    def identity(self):
        return f'{self.number} build{self.build}'


def parse_version(text):
    if not isinstance(text, str) or len(text) > 100:
        raise ValueError('无效版本号')
    value = text.strip()
    match = re.search(r'(?:\s+build[ .-]?|-build[.-]?)(\d+)$', value, re.I)
    build = int(match[1]) if match else 0
    if match:
        value = value[:match.start()].strip()
    try:
        number = Version(value)
    except InvalidVersion as error:
        raise ValueError('无法识别版本号') from error
    if number.is_prerelease or number.is_devrelease or number.local is not None:
        raise ValueError('仅检测正式版本')
    return ReleaseVersion(number, build)


@dataclass(frozen=True)
class Release:
    tag: str
    version: ReleaseVersion
    notes: str
    url: str


def parse_release(payload):
    if not isinstance(payload, dict):
        raise ValueError('更新服务器返回的数据格式异常')
    if payload.get('draft') or payload.get('prerelease'):
        raise ValueError('未找到正式版本')
    tag = payload.get('tag_name')
    version = parse_version(tag)
    url = payload.get('html_url', '')
    if not isinstance(url, str):
        raise ValueError('更新页面地址无效')
    parts = urlsplit(url)
    if (parts.scheme != 'https' or parts.netloc.lower() != 'github.com'
            or not parts.path.lower().startswith('/' + REPOSITORY.lower() + '/releases/')):
        raise ValueError('更新页面不是 CurvePlot 的 GitHub Release')
    notes = payload.get('body')
    if notes is None or notes == '':
        notes = '此版本未提供更新说明。'
    if not isinstance(notes, str):
        raise ValueError('更新说明格式异常')
    return Release(tag, version, notes, url)


class UpdateDialog(QtWidgets.QDialog):
    def __init__(self, checker, release):
        super().__init__()
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.setWindowTitle('CurvePlot · 发现新版本')
        self.resize(560, 420)
        self.release = release
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        form.addRow('当前版本', QtWidgets.QLabel(version_label()))
        form.addRow('最新版本', QtWidgets.QLabel(release.tag))
        layout.addLayout(form)
        self.notes = QtWidgets.QPlainTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setPlainText(release.notes)
        layout.addWidget(self.notes)
        line = QtWidgets.QHBoxLayout()
        self.later = QtWidgets.QPushButton('稍后提醒')
        self.later.setToolTip('7天内不自动重复提示此版本；仍可手动检查更新')
        self.download = QtWidgets.QPushButton('打开下载页面')
        line.addWidget(self.later)
        line.addWidget(self.download)
        layout.addLayout(line)
        self.later.clicked.connect(self.reject)
        self.rejected.connect(lambda: checker.postpone(release))
        def open_page():
            if QtGui.QDesktopServices.openUrl(QtCore.QUrl(release.url)):
                self.accept()
        self.download.clicked.connect(open_page)


class UpdateChecker(QtCore.QObject):
    """One application-wide manager, same-user device preferences and bounded requests."""
    completed = QtCore.Signal(str)
    def __init__(self, parent=None, *, settings=None, manager=None, clock=None):
        super().__init__(parent)
        self.settings = settings if settings is not None else QtCore.QSettings('PhysicsPlot', 'Updates')
        self.manager = manager if manager is not None else QtNetwork.QNetworkAccessManager(self)
        self.clock = clock or time.time
        self.reply = None
        self.dialog = None
        self.message = None
        self.manual = False
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.timeout)

    def number_setting(self, key):
        try:
            value = float(self.settings.value(key, 0))
            return value if math.isfinite(value) else 0
        except (ValueError, TypeError, OverflowError):
            return 0

    def check(self, manual=False):
        if self.reply is not None:
            self.manual = self.manual or manual
            return False
        now = self.clock()
        last = self.number_setting('last_attempt')
        if not manual and last and now - last < INTERVAL:
            return False
        self.manual = manual
        self.settings.setValue('last_attempt', now)
        self.settings.sync()
        self.buffer = bytearray()
        self.failure = ''
        request = QtNetwork.QNetworkRequest(QtCore.QUrl(ENDPOINT))
        request.setRawHeader(b'Accept', b'application/vnd.github+json')
        request.setRawHeader(b'X-GitHub-Api-Version', b'2022-11-28')
        request.setRawHeader(b'User-Agent', ('CurvePlot/' + version_label()).encode())
        request.setTransferTimeout(8000)
        request.setAttribute(QtNetwork.QNetworkRequest.RedirectPolicyAttribute,
                             QtNetwork.QNetworkRequest.SameOriginRedirectPolicy)
        try:
            self.reply = self.manager.get(request)
            self.reply.setReadBufferSize(MAX_RESPONSE + 1)
            self.reply.readyRead.connect(self.read)
            self.reply.finished.connect(self.finish)
            self.timer.start(10000)
        except Exception:
            self.reply = None
            self.error('无法启动更新检查，请检查网络设置。')
            return False
        return True

    def read(self):
        if self.reply is None:
            return
        self.buffer.extend(bytes(self.reply.readAll()))
        if len(self.buffer) > MAX_RESPONSE:
            self.failure = '更新数据过大，已停止检查。'
            self.reply.abort()

    def timeout(self):
        if self.reply is not None:
            self.failure = '更新检查超时，请稍后重试。'
            self.reply.abort()

    def finish(self):
        reply = self.reply
        if reply is None:
            return
        self.timer.stop()
        self.reply = None
        self.buffer.extend(bytes(reply.readAll()))
        if len(self.buffer) > MAX_RESPONSE:
            self.failure = '更新数据过大，已停止检查。'
        data = bytes(self.buffer)
        self.buffer.clear()
        try:
            code = reply.attribute(QtNetwork.QNetworkRequest.HttpStatusCodeAttribute)
            if self.failure:
                self.error(self.failure)
            elif code == 404:
                self.info('尚未找到可用的正式 Release。', 'no-release')
            elif code in (403, 429):
                self.error('GitHub API 暂时限制访问，请稍后重试。')
            elif reply.error() != QtNetwork.QNetworkReply.NoError or code != 200:
                self.error('无法检查更新，请检查网络或代理设置后重试。')
            else:
                try:
                    release = parse_release(json.loads(data.decode('utf-8')))
                    current = parse_version(version_label())
                except (ValueError, UnicodeError, OverflowError):
                    self.error('版本号或更新数据异常，未执行更新操作。')
                    return
                if release.version <= current:
                    self.info('当前已是最新版本。', 'current')
                elif not self.manual and self.postponed(release):
                    self.completed.emit('postponed')
                else:
                    self.show_release(release)
                    self.completed.emit('available')
        finally:
            reply.deleteLater()

    def show_release(self, release):
        if self.dialog is not None:
            if self.dialog.release.version == release.version:
                self.dialog.raise_()
                return
            self.dialog.close()
        dialog = UpdateDialog(self, release)
        self.dialog = dialog
        dialog.finished.connect(lambda *_: self.clear_dialog(dialog))
        dialog.show()

    def clear_dialog(self, dialog):
        if self.dialog is dialog:
            self.dialog = None

    def postpone(self, release):
        self.settings.setValue('postponed_version', release.version.identity)
        self.settings.setValue('remind_after', self.clock() + SNOOZE)
        self.settings.sync()

    def postponed(self, release):
        try:
            same = parse_version(self.settings.value('postponed_version', '')) == release.version
        except ValueError:
            return False
        return same and self.clock() < self.number_setting('remind_after')

    def info(self, text, outcome):
        if self.manual:
            self.show_message(text)
        self.completed.emit(outcome)

    def error(self, text):
        self.info(text, 'error')

    def show_message(self, text):
        if self.message is not None:
            self.message.close()
        message = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Information,
                                        'CurvePlot · 检查更新', text, QtWidgets.QMessageBox.Ok)
        self.message = message
        message.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        def clear(*_):
            if self.message is message:
                self.message = None
        message.finished.connect(clear)
        message.open()


def for_application():
    app = QtWidgets.QApplication.instance()
    checker = getattr(app, '_curve_update_checker', None)
    if checker is None:
        checker = app._curve_update_checker = UpdateChecker(app)
    return checker


def check_now(*_):
    for_application().check(manual=True)

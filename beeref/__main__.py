#!/usr/bin/env python3

# This file is part of BeeRef.
#
# BeeRef is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# BeeRef is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with BeeRef.  If not, see <https://www.gnu.org/licenses/>.

import logging
import os
import platform
import signal
import sys
import ctypes
from contextlib import contextmanager
from ctypes import wintypes

from PyQt6 import QtCore, QtWidgets, QtGui

from beeref import constants
from beeref.assets import BeeAssets
from beeref.config import CommandlineArgs, BeeSettings, logfile_name
from beeref.utils import create_palette_from_dict
from beeref.view import BeeGraphicsView
from beeref.clipstudio import ClipStudioPinController

logger = logging.getLogger(__name__)

WDA_NONE = 0x00000000
WDA_EXCLUDEFROMCAPTURE = 0x00000011
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_APPWINDOW = 0x00040000
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_NOZORDER = 0x0004
WM_HOTKEY = 0x0312
WM_NCHITTEST = 0x0084
HTTRANSPARENT = -1
ERROR_ALREADY_EXISTS = 183
SINGLE_INSTANCE_MUTEX = r'Local\BeeRef.Overlay.SingleInstance'
MOD_NOREPEAT = 0x4000
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
VK_T = 0x54
VK_R = 0x52
VK_U = 0x55
HOTKEY_TOGGLE_LOCK = 0xBEEF
HOTKEY_RESYNC = HOTKEY_TOGGLE_LOCK + 1
HOTKEY_DETACH = HOTKEY_TOGGLE_LOCK + 2


class WindowsMSG(ctypes.Structure):
    _fields_ = [
        ('hwnd', wintypes.HWND),
        ('message', wintypes.UINT),
        ('wParam', wintypes.WPARAM),
        ('lParam', wintypes.LPARAM),
        ('time', wintypes.DWORD),
        ('pt', wintypes.POINT),
    ]


if platform.system() == 'Windows':
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
    user32.GetWindowDisplayAffinity.argtypes = [
        wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowDisplayAffinity.restype = wintypes.BOOL
    user32.RegisterHotKey.argtypes = [
        wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.UnregisterHotKey.restype = wintypes.BOOL
    kernel32.CreateMutexW.argtypes = [
        wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        get_window_long = user32.GetWindowLongPtrW
        set_window_long = user32.SetWindowLongPtrW
        get_window_long.restype = ctypes.c_ssize_t
        set_window_long.restype = ctypes.c_ssize_t
    else:
        get_window_long = user32.GetWindowLongW
        set_window_long = user32.SetWindowLongW
        get_window_long.restype = ctypes.c_long
        set_window_long.restype = ctypes.c_long
    get_window_long.argtypes = [wintypes.HWND, ctypes.c_int]
    set_window_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]


def get_display_affinity(window):
    if platform.system() != 'Windows':
        return WDA_NONE
    affinity = wintypes.DWORD()
    if not user32.GetWindowDisplayAffinity(
            wintypes.HWND(int(window.winId())), ctypes.byref(affinity)):
        return None
    return affinity.value


@contextmanager
def capture_enabled_for_diagnostics(window):
    """Temporarily allow a diagnostic capture and always restore affinity."""
    if platform.system() != 'Windows':
        yield
        return
    hwnd = wintypes.HWND(int(window.winId()))
    previous = get_display_affinity(window)
    user32.SetWindowDisplayAffinity(hwnd, WDA_NONE)
    try:
        yield
    finally:
        restore = (WDA_EXCLUDEFROMCAPTURE if previous is None
                   else previous)
        user32.SetWindowDisplayAffinity(hwnd, restore)


class HotkeyFilter(QtCore.QAbstractNativeEventFilter):
    def __init__(self, app):
        super().__init__()
        self.app = app

    def nativeEventFilter(self, event_type, message):
        return self.app.nativeEventFilter(event_type, message)


class BeeRefApplication(QtWidgets.QApplication):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.main_window = None
        self._instance_mutex = None
        self._already_running = False
        if platform.system() == 'Windows':
            # A hidden tray application is easy to start repeatedly from a
            # VBS launcher.  Multiple transparent desktop windows look like
            # image trails and only the first process owns Ctrl+T.
            self._instance_mutex = kernel32.CreateMutexW(
                None, True, SINGLE_INSTANCE_MUTEX)
            if self._instance_mutex:
                self._already_running = (
                    ctypes.get_last_error() == ERROR_ALREADY_EXISTS)
            else:
                # Do not make BeeRef unusable if Windows refuses the mutex;
                # the hotkey registration still provides the normal guard.
                logger.warning('Could not create BeeRef single-instance mutex '
                               '(error %s)', ctypes.get_last_error())
        self._hotkey_registered = []
        self._hotkey_filter = HotkeyFilter(self)
        if platform.system() == 'Windows':
            self.installNativeEventFilter(self._hotkey_filter)

    def _register_hotkeys(self):
        if platform.system() != 'Windows':
            return False
        # Test fixtures and a few embedding scenarios can create more than
        # one main window on the same QApplication.  Registering the same
        # system hotkey twice returns ERROR_HOTKEY_ALREADY_REGISTERED and
        # needlessly fills the log; one registration is enough for the app.
        if self._hotkey_registered:
            return True
        registrations = (
            (HOTKEY_TOGGLE_LOCK, MOD_CONTROL | MOD_NOREPEAT, VK_T,
             'Ctrl+T'),
            (HOTKEY_RESYNC, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_R,
             'Ctrl+Shift+R'),
            (HOTKEY_DETACH, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_U,
             'Ctrl+Shift+U'),
        )
        for hotkey_id, modifiers, key, label in registrations:
            if user32.RegisterHotKey(None, hotkey_id, modifiers, key):
                self._hotkey_registered.append(hotkey_id)
            else:
                logger.warning('Could not register global %s hotkey (error %s)',
                               label, ctypes.get_last_error())
        return bool(self._hotkey_registered)

    def _unregister_hotkeys(self):
        if platform.system() != 'Windows':
            return
        registered = getattr(self, '_hotkey_registered', ())
        for hotkey_id in registered:
            user32.UnregisterHotKey(None, hotkey_id)
        if hasattr(self, '_hotkey_registered'):
            self._hotkey_registered.clear()

    def notify_hotkey(self, hotkey_id):
        if self.main_window is None:
            return
        if hotkey_id == HOTKEY_TOGGLE_LOCK:
            self.main_window.handle_ctrl_t()
        elif hotkey_id == HOTKEY_RESYNC:
            self.main_window.pin_controller.resync()
        elif hotkey_id == HOTKEY_DETACH:
            self.main_window.pin_controller.detach()

    def nativeEventFilter(self, event_type, message):
        event_name = bytes(event_type).decode(errors='ignore') \
            if not isinstance(event_type, str) else event_type
        if (event_name == 'windows_generic_MSG'
                and platform.system() == 'Windows'):
            msg = ctypes.cast(
                int(message), ctypes.POINTER(WindowsMSG)).contents
            if msg.message == WM_HOTKEY:
                self.notify_hotkey(msg.wParam)
                return True, 0
            # WS_EX_TRANSPARENT affects paint ordering, not mouse hit
            # testing.  Return HTTRANSPARENT while locked so Krita receives
            # the brush/middle-mouse input underneath the overlay.
            main_window = self.main_window
            if (msg.message == WM_NCHITTEST and main_window is not None
                    and getattr(main_window, '_mouse_passthrough', False)
                    and int(msg.hwnd) == int(main_window.winId())):
                return True, HTTRANSPARENT
        return False, 0

    def __del__(self):
        self._unregister_hotkeys()

    def event(self, event):
        if event.type() == QtCore.QEvent.Type.FileOpen:
            for widget in self.topLevelWidgets():
                if isinstance(widget, BeeRefMainWindow):
                    widget.view.open_from_file(event.file())
                    return True
            return False
        else:
            return super().event(event)


class BeeRefMainWindow(QtWidgets.QMainWindow):

    def __init__(self, app):
        super().__init__(flags=(
            QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
            | QtCore.Qt.WindowType.Tool))
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setStyleSheet('QMainWindow { background: transparent; }')
        self._mouse_passthrough = False
        self._native_state_pending = False
        self.pin_controller = ClipStudioPinController(self)
        self.pin_controller.statusChanged.connect(self._on_pin_status)
        app.setOrganizationName(constants.APPNAME)
        app.setApplicationName(constants.APPNAME)
        self.setWindowIcon(BeeAssets().logo)
        self.view = BeeGraphicsView(app, self)
        self.setCentralWidget(self.view)
        self.setMenuBar(None)
        self.pin_status_label = QtWidgets.QLabel(self)
        self.pin_status_label.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.pin_status_label.setStyleSheet(
            'QLabel { color: white; background: rgba(20, 20, 20, 185); '
            'border-radius: 5px; padding: 5px 9px; }')
        self.pin_status_label.hide()
        self._create_pin_actions()
        self.view.context_menu.addSeparator()
        self.view.context_menu.addAction(self.attach_pin_action)
        self.view.context_menu.addAction(self.resync_pin_action)
        self.view.context_menu.addAction(self.detach_pin_action)
        self._connect_screen_geometry_signals(app)
        self.cover_virtual_desktop()
        self.show()
        app.main_window = self
        app._register_hotkeys()
        self._create_tray_icon(app)
        self.apply_native_state()

    def _create_pin_actions(self):
        self.attach_pin_action = QtGui.QAction(
            'Pin selected image to Krita / Clip Studio (Ctrl+T)', self)
        self.attach_pin_action.triggered.connect(self.pin_controller.attach)
        self.addAction(self.attach_pin_action)
        self.resync_pin_action = QtGui.QAction(
            'Keep current position / Re-sync (Ctrl+Shift+R)', self)
        self.resync_pin_action.triggered.connect(self.pin_controller.resync)
        self.addAction(self.resync_pin_action)
        self.detach_pin_action = QtGui.QAction(
            'Detach pin (Ctrl+Shift+U)', self)
        self.detach_pin_action.triggered.connect(self.pin_controller.detach)
        self.addAction(self.detach_pin_action)

    def _on_pin_status(self, message):
        self.pin_status_label.setText(message)
        self.pin_status_label.adjustSize()
        self.pin_status_label.move(18, 18)
        # The status badge is useful while editing, but should not sit over
        # the artwork during click-through tracing.
        self.pin_status_label.setVisible(
            bool(message) and not self._mouse_passthrough)
        if hasattr(self, 'tray_icon'):
            self.tray_icon.setToolTip(
                f'BeeRef overlay: {message}' if message else
                'BeeRef overlay: editable')

    def _connect_screen_geometry_signals(self, app):
        app.screenAdded.connect(self._on_screen_layout_changed)
        app.screenRemoved.connect(self._on_screen_layout_changed)
        for screen in app.screens():
            screen.geometryChanged.connect(self.cover_virtual_desktop)

    def _on_screen_layout_changed(self, screen):
        if screen is not None:
            try:
                screen.geometryChanged.connect(self.cover_virtual_desktop)
            except RuntimeError:
                pass
        QtCore.QTimer.singleShot(0, self.cover_virtual_desktop)

    def cover_virtual_desktop(self, *_args):
        """Keep the transparent edit surface over every connected monitor."""
        screens = QtGui.QGuiApplication.screens()
        if not screens:
            return
        desktop = QtCore.QRect(screens[0].geometry())
        for screen in screens[1:]:
            desktop = desktop.united(screen.geometry())
        if self.geometry() != desktop:
            self.setGeometry(desktop)
        self.schedule_native_state()

    def _create_tray_icon(self, app):
        self.tray_icon = QtWidgets.QSystemTrayIcon(self.windowIcon(), app)
        menu = QtWidgets.QMenu()
        self.tray_lock_action = menu.addAction(
            'Pin to Krita / Clip Studio (Ctrl+T)')
        self.tray_lock_action.triggered.connect(self.handle_ctrl_t)
        menu.addSeparator()
        quit_action = menu.addAction('Quit BeeRef')
        quit_action.triggered.connect(app.quit)
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.setToolTip('BeeRef overlay: editable')
        self.tray_icon.show()

    def schedule_native_state(self):
        if getattr(self, '_native_state_pending', False):
            return
        self._native_state_pending = True
        QtCore.QTimer.singleShot(0, self.apply_native_state)

    def apply_native_state(self):
        self._native_state_pending = False
        if platform.system() != 'Windows' or not self.windowHandle():
            return
        hwnd = wintypes.HWND(int(self.winId()))
        style = (get_window_long(hwnd, GWL_EXSTYLE)
                 | WS_EX_LAYERED | WS_EX_TOOLWINDOW)
        style &= ~WS_EX_APPWINDOW
        if self._mouse_passthrough:
            style |= WS_EX_TRANSPARENT
        else:
            style &= ~WS_EX_TRANSPARENT
        set_window_long(hwnd, GWL_EXSTYLE, style)
        user32.SetWindowPos(
            hwnd, None, 0, 0, 0, 0,
            SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER
            | SWP_NOACTIVATE | SWP_FRAMECHANGED)
        if not user32.SetWindowDisplayAffinity(
                hwnd, WDA_EXCLUDEFROMCAPTURE):
            logger.warning('Could not exclude BeeRef from capture (error %s)',
                           ctypes.get_last_error())
        affinity = get_display_affinity(self)
        if affinity != WDA_EXCLUDEFROMCAPTURE:
            logger.warning('Unexpected BeeRef display affinity: %r', affinity)

    def event(self, event):
        result = super().event(event)
        if (hasattr(self, '_native_state_pending')
                and event.type() in (QtCore.QEvent.Type.WinIdChange,
                                     QtCore.QEvent.Type.Show)):
            self.schedule_native_state()
        return result

    def _set_mouse_passthrough(self, enabled):
        if platform.system() != 'Windows':
            return
        self._mouse_passthrough = enabled
        # Qt's native flag is the reliable cross-process input pass-through
        # mechanism.  The native WM_NCHITTEST fallback above also covers
        # Windows/Qt combinations that ignore the flag after show().
        self.setWindowFlag(
            QtCore.Qt.WindowType.WindowTransparentForInput, enabled)
        self.pin_controller.set_locked_visuals(enabled)
        if hasattr(self, 'pin_status_label'):
            self.pin_status_label.setVisible(
                bool(self.pin_status_label.text()) and not enabled)
        self.show()
        self.apply_native_state()

    def toggle_mouse_passthrough(self):
        self._set_mouse_passthrough(not self._mouse_passthrough)
        mode = 'locked (click-through)' if self._mouse_passthrough else 'editable'
        self.tray_lock_action.setText(
            'Unlock BeeRef (Ctrl+T)' if self._mouse_passthrough
            else 'Lock BeeRef (Ctrl+T)')
        self.tray_icon.setToolTip(f'BeeRef overlay: {mode}')
        logger.info('Mouse pass-through: %s', self._mouse_passthrough)

    def handle_ctrl_t(self):
        """Pin-and-lock on first press; thereafter toggle editability."""
        controller = self.pin_controller
        if controller.item is None:
            if not controller.attach():
                return
            self._set_mouse_passthrough(True)
            self._update_lock_feedback()
            return
        if self._mouse_passthrough:
            self._set_mouse_passthrough(False)
            self._on_pin_status('Editable — drag image, then press Ctrl+T to pin again')
        else:
            controller.resync()
            self._set_mouse_passthrough(True)
            self._update_lock_feedback()

    def _update_lock_feedback(self):
        locked = self._mouse_passthrough
        self.tray_lock_action.setText(
            'Unlock BeeRef (Ctrl+T)' if locked
            else 'Pin here / Lock (Ctrl+T)')
        self.tray_icon.setToolTip(
            'BeeRef overlay: locked (click-through)' if locked
            else 'BeeRef overlay: editable')

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'pin_status_label'):
            self.pin_status_label.move(18, 18)

    def closeEvent(self, event):
        if hasattr(self, 'view'):
            self.view.shutdown_io()
        if hasattr(self, 'pin_controller'):
            self.pin_controller.detach()
        app = QtWidgets.QApplication.instance()
        if isinstance(app, BeeRefApplication):
            app._unregister_hotkeys()
        event.accept()

    def __del__(self):
        del self.view


def safe_timer(timeout, func, *args, **kwargs):
    """Create a timer that is safe against garbage collection and
    overlapping calls.
    See: http://ralsina.me/weblog/posts/BB974.html
    """
    def timer_event():
        try:
            func(*args, **kwargs)
        finally:
            QtCore.QTimer.singleShot(timeout, timer_event)
    QtCore.QTimer.singleShot(timeout, timer_event)


def handle_sigint(signum, frame):
    logger.info('Received interrupt. Exiting...')
    QtWidgets.QApplication.quit()


def handle_uncaught_exception(exc_type, exc, traceback):
    logger.critical('Unhandled exception',
                    exc_info=(exc_type, exc, traceback))
    QtWidgets.QApplication.quit()


sys.excepthook = handle_uncaught_exception


def main():
    logger.info(f'Starting {constants.APPNAME} version {constants.VERSION}')
    logger.debug('System: %s', ' '.join(platform.uname()))
    logger.debug('Python: %s', platform.python_version())
    logger.debug('LD_LIBRARY_PATH: %s', os.environ.get('LD_LIBRARY_PATH'))
    settings = BeeSettings()
    logger.info(f'Using settings: {settings.fileName()}')
    logger.info(f'Logging to: {logfile_name()}')
    settings.on_startup()
    args = CommandlineArgs(with_check=True)  # Force checking
    assert not args.debug_raise_error, args.debug_raise_error

    os.environ["QT_DEBUG_PLUGINS"] = "1"
    app = BeeRefApplication(sys.argv)
    if getattr(app, '_already_running', False):
        logger.info('BeeRef is already running; ignoring duplicate launch')
        return
    palette = create_palette_from_dict(constants.COLORS)
    app.setPalette(palette)
    bee = BeeRefMainWindow(app)  # NOQA:F841

    signal.signal(signal.SIGINT, handle_sigint)
    # Repeatedly run python-noop to give the interpreter time to
    # handle signals
    # A short periodic callback keeps Python signal handling responsive while
    # Qt owns the event loop.  1 second is plenty for Ctrl+C and avoids
    # waking the process twenty times per second while idle.
    safe_timer(1000, lambda: None)

    app.exec()
    del bee
    del app
    logger.debug('BeeRef closed')
    QtCore.qInstallMessageHandler(None)


if __name__ == '__main__':
    main()  # pragma: no cover

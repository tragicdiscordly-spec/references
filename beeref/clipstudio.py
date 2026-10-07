"""Windows-only Clip Studio attachment and local transform bridge."""

from dataclasses import dataclass
import ctypes
import json
import logging
import math
import ntpath
import os
import platform
import re
import time
from ctypes import wintypes

from PyQt6 import QtCore, QtGui

from beeref.locked_overlay import LockedReferenceOverlay, affine_from_points

logger = logging.getLogger(__name__)


@dataclass
class ClipStudioWindow:
    hwnd: int
    title: str
    executable: str = ''
    application: str = 'Clip Studio Paint'
    pid: int = 0


@dataclass
class DesktopWindow:
    """A visible top-level window, as found by ``visible_windows``."""
    hwnd: int
    rect: QtCore.QRect
    pid: int


if platform.system() == 'Windows':
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR,
                                      ctypes.c_int]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                                ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowRect.argtypes = [wintypes.HWND,
                                     ctypes.POINTER(wintypes.RECT)]
    user32.EnumChildWindows.argtypes = [
        wintypes.HWND,
        ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM),
        wintypes.LPARAM]
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL,
                                     wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    dwmapi = ctypes.WinDLL('dwmapi')
    dwmapi.DwmGetWindowAttribute.argtypes = [
        wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
DWMWA_CLOAKED = 14


def _window_text(hwnd):
    length = user32.GetWindowTextLengthW(hwnd)
    if not length:
        return ''
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def _process_id(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _process_path(hwnd):
    if platform.system() != 'Windows':
        return ''
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False,
                                  _process_id(hwnd))
    if not handle:
        return ''
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(
                handle, 0, buffer, ctypes.byref(size)):
            return buffer.value
        return ''
    finally:
        kernel32.CloseHandle(handle)


def paint_application(title, executable):
    """Return which paint application owns a window, or None.

    Match the executable, so a browser tab titled "Krita" is not mistaken
    for Krita. Fall back to the title only when Windows hides the path,
    as it does for apps running as administrator.
    """
    name = ntpath.basename(executable).lower()
    if name in {'clipstudiopaint.exe', 'clipstudio paint.exe'}:
        return 'Clip Studio Paint'
    if name == 'krita.exe':
        return 'Krita'
    if not executable:
        title = title.lower()
        if 'clip studio paint' in title:
            return 'Clip Studio Paint'
        if 'krita' in title:
            return 'Krita'
    return None


def find_paint_windows():
    """Return visible Clip Studio Paint and Krita top-level windows.

    Krita does not consistently put the canvas zoom in its title bar, so the
    zoom reader below also searches child widgets.
    """
    if platform.system() != 'Windows':
        return []
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        title = _window_text(hwnd)
        executable = _process_path(hwnd)
        application = paint_application(title, executable)
        if application is not None:
            found.append(ClipStudioWindow(int(hwnd), title, executable,
                                          application, _process_id(hwnd)))
        return True

    user32.EnumWindows(callback, 0)
    return found


def _is_cloaked(hwnd):
    # Suspended Store apps keep visible but cloaked, invisible windows.
    cloaked = wintypes.DWORD()
    result = dwmapi.DwmGetWindowAttribute(
        hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
    return result == 0 and cloaked.value != 0


def visible_windows():
    """Return the windows a user can see, topmost first.

    EnumWindows lists top-level windows in z-order. Skip minimized,
    cloaked and click-through windows, which never cover what is below.
    """
    if platform.system() != 'Windows':
        return []
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _):
        if (not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd)
                or user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                & WS_EX_TRANSPARENT
                or _is_cloaked(hwnd)):
            return True
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        found.append(DesktopWindow(
            int(hwnd),
            QtCore.QRect(rect.left, rect.top, rect.right - rect.left,
                         rect.bottom - rect.top),
            _process_id(hwnd)))
        return True

    user32.EnumWindows(callback, 0)
    return found


def window_at(point, windows, own_pid):
    """Return the topmost window at a physical point, except our own.

    ``windows`` are visible windows topmost first, from ``visible_windows``.
    """
    for window in windows:
        if window.pid != own_pid and window.rect.contains(point):
            return window
    return None


def paint_window_for(window, windows, paint_windows):
    """Return the Krita / Clip Studio main window owning ``window``.

    A floating docker belongs to the same process as the main window, which
    is that process's largest window. Returns None for other applications.
    """
    if window is None:
        return None
    candidates = [paint for paint in paint_windows
                  if paint.hwnd == window.hwnd
                  or paint.pid and paint.pid == window.pid]
    if not candidates:
        return None
    rects = {visible.hwnd: visible.rect for visible in windows}

    def area(paint):
        rect = rects.get(paint.hwnd, QtCore.QRect())
        return rect.width() * rect.height()

    return max(candidates, key=area)


def native_point(point, screens=None):
    """Map a point in Qt desktop coordinates to Windows physical pixels.

    Qt keeps each screen's origin in physical pixels and scales distances
    from it by the screen's device pixel ratio.
    """
    if screens is None:
        screens = QtGui.QGuiApplication.screens()
    for screen in screens:
        geometry = screen.geometry()
        if geometry.contains(QtCore.QPoint(math.floor(point.x()),
                                           math.floor(point.y()))):
            ratio = screen.devicePixelRatio()
            return QtCore.QPoint(
                round(geometry.x() + (point.x() - geometry.x()) * ratio),
                round(geometry.y() + (point.y() - geometry.y()) * ratio))
    return QtCore.QPoint(round(point.x()), round(point.y()))


def find_clip_studio_windows():
    """Backward-compatible alias for older callers."""
    return [window for window in find_paint_windows()
            if window.application == 'Clip Studio Paint']


_zoom_cache = {}
_ZOOM_CACHE_SECONDS = 0.06


def window_rect(window):
    if platform.system() != 'Windows':
        return QtCore.QRect()
    rect = wintypes.RECT()
    if not user32.GetWindowRect(wintypes.HWND(window.hwnd),
                                ctypes.byref(rect)):
        return QtCore.QRect()
    return QtCore.QRect(rect.left, rect.top,
                        rect.right - rect.left, rect.bottom - rect.top)


def window_zoom(window, force=False):
    """Read the displayed canvas zoom percentage from a paint window.

    Clip Studio normally exposes it in the title. Krita commonly exposes it
    in a status-bar/tool widget instead, so inspect child-window text too.
    """
    if platform.system() != 'Windows':
        return None
    title = _window_text(wintypes.HWND(window.hwnd))
    now = time.monotonic()
    cached = _zoom_cache.get(window.hwnd)
    if (not force and cached is not None
            and cached[0] == title
            and now - cached[1] < _ZOOM_CACHE_SECONDS):
        return cached[2]
    # The fast path covers current Krita builds as well as Clip Studio.
    # Only enumerate Krita's child widgets when the title has no percentage;
    # this keeps the normal 80 ms tracking loop inexpensive.
    texts = [title]
    if (window.application == 'Krita'
            and not re.search(r'\d+(?:\.\d+)?\s*%', title)):
        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def callback(hwnd, _):
            text = _window_text(hwnd)
            if text:
                texts.append(text)
            return True
        user32.EnumChildWindows(wintypes.HWND(window.hwnd), callback, 0)
    # Prefer an explicit zoom label. Krita can expose several other percent
    # values in child controls (opacity, rotation, etc.), so only use a
    # generic percentage as a fallback.
    explicit_zoom = re.compile(
        r'zoom(?:\s*(?:level|factor))?\s*[:= ]\s*'
        r'(\d+(?:\.\d+)?)\s*%', flags=re.IGNORECASE)
    for text in texts:
        matches = explicit_zoom.findall(text)
        if matches:
            value = float(matches[-1])
            _zoom_cache[window.hwnd] = (title, now, value)
            return value

    value = None
    for text in texts:
        matches = re.findall(r'(?:zoom\s*[: ]\s*)?(\d+(?:\.\d+)?)\s*%',
                             text, flags=re.IGNORECASE)
        if matches:
            value = float(matches[-1])
            break
    _zoom_cache[window.hwnd] = (title, now, value)
    return value


def cursor_position():
    # Use Qt's desktop coordinate space so the fallback and the Krita Qt
    # bridge agree on mixed-DPI Windows desktops.  Win32 GetCursorPos returns
    # physical coordinates, while Qt's widget mapping uses its logical
    # desktop coordinates.
    return QtGui.QCursor.pos()


class LocalTransformBridge(QtCore.QObject):
    """Poll an optional local Clip Studio transform JSON contract.

    A helper/plugin may write
    ``%LOCALAPPDATA%\\BeeRef\\clipstudio_transform.json``
    with ``{"matrix": [a, b, c, d, tx, ty]}``. Missing or invalid data is
    treated as unavailable and never breaks window-follow tracking.
    """

    transformChanged = QtCore.pyqtSignal(QtGui.QTransform)
    stateChanged = QtCore.pyqtSignal(object)
    zoomChanged = QtCore.pyqtSignal(float, object, object, object, float)
    disconnected = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.path = os.path.join(
            os.environ.get('LOCALAPPDATA', ''), 'BeeRef',
            'clipstudio_transform.json')
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(30)
        self._timer.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self.poll)
        self._last_mtime = None
        self._last_error_mtime = None
        self._heartbeat_required = False

    def start(self):
        self._last_mtime = None
        self._timer.start()
        self.poll()

    def stop(self):
        self._timer.stop()

    def poll(self, force=False):
        mtime = None
        try:
            mtime = os.path.getmtime(self.path)
            # The current bridge sends an idle heartbeat. Never lock to a
            # file left behind by an exited/restarted Krita process.
            if self._heartbeat_required and time.time() - mtime > 2.0:
                if self._last_mtime is not None:
                    self._last_mtime = None
                    self.disconnected.emit()
                return
            if mtime == self._last_mtime and not force:
                return
            with open(self.path, encoding='utf-8') as stream:
                data = json.load(stream)
            # An uncaught error in this timer slot would quit BeeRef.
            if not isinstance(data, dict):
                raise ValueError('bridge state must be a JSON object')
            self._heartbeat_required = data.get('protocol', 2) >= 3
            if (self._heartbeat_required
                    and time.time() - float(data.get('timestamp', 0)) > 2.0):
                raise ValueError('Krita bridge heartbeat expired')
            values = data.get('matrix')
            if values is not None:
                if not isinstance(values, list) or len(values) != 6:
                    raise ValueError('matrix must contain six numbers')
                a, b, c, d, tx, ty = [float(value) for value in values]
                matrix = QtGui.QTransform(a, b, 0, c, d, 0, tx, ty, 1)
            else:
                matrix = None
            zoom = data.get('zoom')
            if zoom is not None:
                zoom = float(zoom)
                if zoom <= 0:
                    raise ValueError('zoom must be greater than zero')
                cursor_values = data.get('cursor', [])
                if (not isinstance(cursor_values, (list, tuple))
                        or len(cursor_values) != 2):
                    raise ValueError('cursor must contain two coordinates')
                cursor = QtCore.QPoint(int(cursor_values[0]),
                                       int(cursor_values[1]))
                hwnd = data.get('hwnd')
                hwnd = int(hwnd) if hwnd is not None else None
                center_values = data.get('center')
                if (isinstance(center_values, (list, tuple))
                        and len(center_values) == 2):
                    center = QtCore.QPointF(float(center_values[0]),
                                            float(center_values[1]))
                else:
                    center = None
                rotation = float(data.get('rotation', 0.0))
                canvas_values = data.get('canvas_rect')
                if canvas_values is None:
                    canvas_rect = None
                else:
                    if (not isinstance(canvas_values, (list, tuple))
                            or len(canvas_values) != 4):
                        raise ValueError(
                            'canvas_rect must contain x, y, width, height')
                    canvas_rect = tuple(
                        float(value) for value in canvas_values)
                    if canvas_rect[2] <= 0 or canvas_rect[3] <= 0:
                        raise ValueError('canvas_rect must have positive size')
                view_values = data.get('view_matrix')
                if view_values is None:
                    view_matrix = None
                else:
                    if (not isinstance(view_values, (list, tuple))
                            or len(view_values) != 6):
                        raise ValueError(
                            'view_matrix must contain six numbers')
                    view_matrix = tuple(float(value) for value in view_values)
                view_matrix_space = data.get('view_matrix_space')
            else:
                view_matrix_space = None
            self._last_mtime = mtime
            self._last_error_mtime = None
            if matrix is not None:
                self.transformChanged.emit(matrix)
            if zoom is not None:
                self.stateChanged.emit({
                    'protocol': data.get('protocol', 2),
                    'zoom': zoom,
                    'cursor': cursor,
                    'hwnd': hwnd,
                    'center': center,
                    'rotation': rotation,
                    'canvas_rect': canvas_rect,
                    'view_matrix': view_matrix,
                    'view_matrix_space': view_matrix_space,
                    'canvas_device_pixel_ratio': data.get(
                        'canvas_device_pixel_ratio'),
                    'canvas_screen_name': data.get('canvas_screen_name'),
                    'canvas_screen_origin': data.get('canvas_screen_origin'),
                })
                self.zoomChanged.emit(zoom, cursor, hwnd, center, rotation)
        except (FileNotFoundError, OSError):
            if self._last_mtime is not None:
                self._last_mtime = None
                self.disconnected.emit()
        except (ValueError, TypeError, json.JSONDecodeError):
            # A helper may briefly write a partially formed JSON file. Do not
            # emit a disconnect signal every 150 ms for the same bad write.
            if self._last_error_mtime != mtime:
                self._last_error_mtime = mtime
                self.disconnected.emit()


class ClipStudioPinController(QtCore.QObject):
    """Pin one image to Krita / Clip Studio, or in place on the screen."""

    statusChanged = QtCore.pyqtSignal(str)

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.target = None
        self.item = None
        # Pinned somewhere other than a paint app: the image stays put.
        self.screen_pinned = False
        self._last_rect = QtCore.QRect()
        self._last_zoom = None
        self._bridge_available = False
        self._bridge_zoom = None
        self._bridge_center = None
        self._bridge_rotation = 0.0
        self._bridge_state = None
        self._bridge_initial_state = None
        self._last_status = None
        self._selection_before_lock = False
        self.locked_overlay = LockedReferenceOverlay()
        self._locked_item_to_global = None
        self._locked_item_visible = True
        self._locked = False
        self.window_timer = QtCore.QTimer(self)
        self.window_timer.setInterval(30)
        self.window_timer.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
        self.window_timer.timeout.connect(self._poll_window)
        self.bridge = LocalTransformBridge(self)
        self.bridge.transformChanged.connect(self._on_transform)
        self.bridge.stateChanged.connect(self._on_bridge_state)
        self.bridge.disconnected.connect(self._on_bridge_disconnected)

    def attach(self):
        """Pin the selected image at its current on-screen placement."""
        selected = self.main_window.view.scene.selectedItems(user_only=True)
        if len(selected) != 1 or not getattr(selected[0], 'is_image', False):
            self._set_status('Select one image to attach')
            return False
        return self._pin(selected[0])

    def repin(self):
        """Pin the current image again where it sits now."""
        if self.item is None or self.item.scene() is None:
            return self.attach()
        return self._pin(self.item)

    def _pin(self, item):
        """Follow the paint app under the image, or stay fixed on screen."""
        if self.item is not None and self.item is not item:
            self._end_locked_overlay()
        self.item = item
        self.target = self._paint_window_under(item)
        self.screen_pinned = self.target is None
        self._bridge_available = False
        self._bridge_zoom = None
        self._bridge_center = None
        self._bridge_state = None
        self._bridge_initial_state = None
        if hasattr(self, '_bridge_matrix'):
            del self._bridge_matrix
        if self.screen_pinned:
            self.window_timer.stop()
            self.bridge.stop()
            self._last_rect = QtCore.QRect()
            self._last_zoom = None
            self._set_status('Pinned in place — Ctrl+T unlocks')
            return True
        self._last_rect = window_rect(self.target)
        self._last_zoom = window_zoom(self.target, force=True)
        self.window_timer.start()
        self.bridge.start()
        self._set_status(
            f'Pinned to {self.target.application} — Ctrl+T unlocks; '
            'image follows')
        return True

    def _paint_window_under(self, item):
        """Return the Krita / Clip Studio window shown under the image."""
        item_to_global = self._item_to_global_transform_for(item)
        if item_to_global is None:
            return None
        center = native_point(item_to_global.map(item.crop.center()))
        windows = visible_windows()
        under = window_at(center, windows, os.getpid())
        if under is not None:
            logger.info('Window under the pinned image: %s',
                        ntpath.basename(_process_path(under.hwnd)))
        return paint_window_for(under, windows, find_paint_windows())

    def _set_status(self, message):
        """Avoid repainting the overlay UI for unchanged status text."""
        if message == self._last_status:
            return
        self._last_status = message
        self.statusChanged.emit(message)

    def set_locked_visuals(self, locked):
        """Switch between editable BeeRef and the clipped lock overlay."""
        if self.item is None or self.item.scene() is None:
            return
        if self.screen_pinned:
            # The image stays in the overlay window, which turns
            # click-through; only hide the selection handles.
            self._locked = bool(locked)
            if locked:
                self._selection_before_lock = self.item.isSelected()
                self.item.setSelected(False)
            elif self._selection_before_lock:
                self.item.setSelected(True)
            return
        if locked:
            # Refresh before establishing the baseline, including when an
            # unchanged file was already consumed by the previous attachment.
            self._bridge_state = None
            self.bridge.poll(force=True)
        self._locked = bool(locked)
        if locked:
            self.main_window.view.set_locked_overlay_active(True)
            self._begin_locked_overlay()
            self._selection_before_lock = self.item.isSelected()
            self.item.setSelected(False)
        else:
            self._end_locked_overlay()
            if self._selection_before_lock:
                self.item.setSelected(True)

    def resync(self):
        if self.screen_pinned and self.item is not None:
            self._set_status('Pinned in place — Ctrl+T unlocks')
            return True
        if self.target is None or self.item is None:
            return self.attach()
        self._last_rect = window_rect(self.target)
        self._last_zoom = window_zoom(self.target, force=True)
        self._bridge_zoom = None
        self._bridge_center = None
        self._bridge_initial_state = None
        if self._locked:
            self._locked_item_to_global = self._item_to_global_transform()
            self.locked_overlay.set_reference(
                self.item, self._locked_item_to_global,
                self._bridge_state,
                self._document_to_global_transform(self._bridge_state)
                if self._bridge_state is not None else None)
        self._set_status(
            'Pinned — current image position saved as the new alignment')
        return True

    def detach(self):
        self._end_locked_overlay()
        self.window_timer.stop()
        self.bridge.stop()
        self._bridge_available = False
        self._bridge_zoom = None
        self._bridge_center = None
        self._bridge_state = None
        self._bridge_initial_state = None
        self._last_zoom = None
        if hasattr(self, '_bridge_matrix'):
            del self._bridge_matrix
        self.target = None
        self.item = None
        self.screen_pinned = False
        self._locked_item_to_global = None
        self._locked = False
        self._selection_before_lock = False
        self._set_status('')

    def _poll_window(self):
        if self.target is None or self.item is None:
            return
        rect = window_rect(self.target)
        if (rect.isNull() or not user32.IsWindowVisible(self.target.hwnd)
                or user32.IsIconic(self.target.hwnd)):
            # CSP may recreate its top-level HWND when switching documents or
            # workspace layouts. Re-select the matching visible window so the
            # pin survives that native-handle change.
            old_executable = os.path.basename(self.target.executable).lower()
            old_title = self.target.title.lower()
            replacement = None
            for candidate in find_paint_windows():
                candidate_executable = os.path.basename(
                    candidate.executable).lower()
                if (old_executable and candidate_executable == old_executable
                        or old_title and old_title in candidate.title.lower()):
                    replacement = candidate
                    break
            if replacement is not None:
                self.target = replacement
                self._last_rect = window_rect(replacement)
                self._last_zoom = window_zoom(replacement, force=True)
                self._bridge_zoom = None
                self._bridge_center = None
                self._bridge_state = None
                self._bridge_initial_state = None
                self._set_status(
                    f'Pinned — {self.target.application} window reconnected')
                return
            self._set_status(
                'Disconnected: Krita / Clip Studio window unavailable')
            return
        if (not self._bridge_available and not self._last_rect.isNull()
                and rect != self._last_rect):
            # Follow the native window's center, not only its top-left.  A
            # resize changes the canvas center even when the top-left stays
            # put; ignoring that made the pinned reference jump out of place
            # as soon as the Krita window was resized.
            previous_center = QtCore.QPointF(self._last_rect.center())
            current_center = QtCore.QPointF(rect.center())
            delta = current_center - previous_center
            # Convert the screen-space delta through the BeeRef view instead
            # of adding it directly to the item's scene position.  The view
            # may itself be zoomed, so one desktop pixel is not necessarily
            # one scene pixel.
            if not delta.isNull():
                if not self._locked:
                    scene_delta = self._scene_delta_from_global_delta(delta)
                    self.item.setPos(self.item.pos() + scene_delta)
        self._last_rect = rect
        if self._bridge_available:
            return

        # Clip Studio exposes its current canvas zoom in the document title
        # (for example, ``60.0%``).  This lightweight fallback keeps a pinned
        # reference scaling with that zoom even when no transform bridge/plugin
        # is installed.  The cursor is used as the pivot, matching CSP's
        # normal zoom interaction; the optional matrix bridge takes precedence
        # when it is available.
        zoom = window_zoom(self.target)
        if (zoom is not None and self._last_zoom not in (None, 0)
                and not self._bridge_available):
            ratio = zoom / self._last_zoom
            if 0.25 < ratio < 4.0 and abs(ratio - 1.0) > 1e-4:
                self._scale_about_cursor(ratio)
                self._set_status(
                    f'Pinned ({self.target.application} zoom tracked)')
        if zoom is not None:
            self._last_zoom = zoom

    def _scale_about_cursor(self, ratio, global_pivot=None):
        if self.item is None:
            return
        if global_pivot is None:
            global_pivot = cursor_position()
        if self._locked:
            # The locked copy is driven by the absolute bridge state.
            # Never apply an incremental zoom to it.
            return
        scene_pivot = self._scene_point_from_global(global_pivot)
        local_pivot = self.item.mapFromScene(scene_pivot)
        # BeeRef's item mixin preserves an explicit anchor while scaling.
        # Using it avoids transform-origin jumps and cumulative wobble.
        self.item.setScale(self.item.scale() * ratio, anchor=local_pivot)

    @staticmethod
    def _translation_transform(delta):
        return QtGui.QTransform(
            1, 0, 0, 0, 1, 0, delta.x(), delta.y(), 1)

    def _scene_point_from_global(self, global_point):
        """Map a desktop point to BeeRef scene coordinates without rounding."""
        view = self.main_window.view
        viewport_origin = view.viewport().mapToGlobal(QtCore.QPoint(0, 0))
        viewport_point = QtCore.QPointF(
            float(global_point.x()) - viewport_origin.x(),
            float(global_point.y()) - viewport_origin.y())
        # QGraphicsView exposes mapToScene(QPoint), but not a QPointF
        # overload in PyQt6.  Map the nearest integer point through Qt and
        # map the remaining fractional offset through the inverse view
        # transform so high-DPI/sub-pixel movement is not discarded.
        integer_point = QtCore.QPoint(
            math.floor(viewport_point.x()), math.floor(viewport_point.y()))
        scene_point = view.mapToScene(integer_point)
        fractional = viewport_point - QtCore.QPointF(integer_point)
        inverse, invertible = view.transform().inverted()
        if not invertible:
            return QtCore.QPointF(scene_point)
        zero = inverse.map(QtCore.QPointF(0, 0))
        return QtCore.QPointF(scene_point) + inverse.map(fractional) - zero

    def _scene_delta_from_global_delta(self, global_delta):
        """Map a desktop translation to BeeRef scene coordinates.

        QWidget.mapFromGlobal accepts integer points.  Using it for every
        bridge update discarded fractional canvas-pixel movement, which made
        repeated Krita pans slowly drift out of alignment.  Mapping QPointF
        values from the viewport origin keeps the sub-pixel delta intact.
        """
        inverse, invertible = self.main_window.view.transform().inverted()
        if not invertible:
            return QtCore.QPointF()
        zero = inverse.map(QtCore.QPointF(0, 0))
        return inverse.map(QtCore.QPointF(global_delta)) - zero

    def _scene_from_global_transform(self):
        """Return the current affine transform from desktop to scene.

        QGraphicsView's scrollbars and viewport origin mean that subtracting
        two screen points is not enough when BeeRef itself is zoomed or
        panned.  Sampling three points through the real view mapping gives a
        precise affine transform and retains fractional coordinates.
        """
        origin = self._scene_point_from_global(QtCore.QPointF(0, 0))
        x_axis = (self._scene_point_from_global(QtCore.QPointF(1, 0))
                  - origin)
        y_axis = (self._scene_point_from_global(QtCore.QPointF(0, 1))
                  - origin)
        return QtGui.QTransform(
            x_axis.x(), x_axis.y(), 0,
            y_axis.x(), y_axis.y(), 0,
            origin.x(), origin.y(), 1)

    def _scene_transform_for_global_transform(self, global_transform):
        """Convert a desktop-space transform into BeeRef scene space."""
        scene_from_global = self._scene_from_global_transform()
        global_from_scene, invertible = scene_from_global.inverted()
        if not invertible:
            return QtGui.QTransform()
        # Qt's QTransform mapping order is left-to-right.  A scene point
        # therefore goes scene->desktop, through the desktop delta, then
        # desktop->scene.
        return global_from_scene * global_transform * scene_from_global

    @staticmethod
    def _document_to_global_transform(state):
        """Build Krita's document-pixel to desktop-pixel transform."""
        canvas_rect = state.get('canvas_rect')
        view_matrix = state.get('view_matrix')
        if (state.get('view_matrix_space') in ('document', 'image')
                and view_matrix is not None and canvas_rect is not None
                and len(view_matrix) == 6 and len(canvas_rect) == 4):
            left, top = map(float, canvas_rect[:2])
            a, b, c, d, tx, ty = map(float, view_matrix)
            if (not all(math.isfinite(v)
                        for v in (a, b, c, d, tx, ty, left, top))
                    or abs(a * d - b * c) < 1e-12):
                return None
            # The bridge matrix is document-pixel -> canvas-widget; move its
            # translation into Qt's desktop coordinate space. This is the
            # exact absolute pan/zoom matrix and avoids estimating movement
            # from preferredCenter on every update.
            return QtGui.QTransform(
                a, b, 0,
                c, d, 0,
                tx + left, ty + top, 1)
        # Modern Krita locks must not silently switch between an exact
        # transform and a preferred-center estimate during a gesture.
        if state.get('protocol', 2) >= 3:
            return None
        center = state.get('center')
        zoom = float(state.get('zoom', 0.0))
        if (canvas_rect is None or center is None or zoom <= 0
                or len(canvas_rect) != 4):
            return None

        left, top, width, height = map(float, canvas_rect)
        canvas_center_x = left + width / 2.0
        canvas_center_y = top + height / 2.0
        document_center_x = float(center.x())
        document_center_y = float(center.y())
        angle = math.radians(float(state.get('rotation', 0.0)))
        cosine = math.cos(angle) * zoom
        sine = math.sin(angle) * zoom
        # QTransform maps x' = m11*x + m21*y + m31 and
        # y' = m12*x + m22*y + m32.
        return QtGui.QTransform(
            cosine, sine, 0,
            -sine, cosine, 0,
            canvas_center_x - cosine * document_center_x
            + sine * document_center_y,
            canvas_center_y - sine * document_center_x
            - cosine * document_center_y,
            1)

    def _begin_locked_overlay(self):
        """Arm the dedicated capture-excluded canvas overlay."""
        if self.item is None or self.item.scene() is None:
            return
        self._locked_item_to_global = self._item_to_global_transform()
        self._locked_item_visible = self.item.isVisible()
        self.item.setVisible(False)
        # Clear the old editable image once before the dedicated overlay takes
        # over. After this frame, bridge updates repaint only the small
        # canvas-sized overlay instead of the virtual desktop.
        self.main_window.view.viewport().repaint()
        self.locked_overlay.set_reference(
            self.item, self._locked_item_to_global,
            self._bridge_state,
            self._document_to_global_transform(self._bridge_state)
            if self._bridge_state is not None else None)

    def _end_locked_overlay(self):
        """Hide the render copy and restore the editable BeeRef item."""
        self.locked_overlay.clear_reference()
        if self.item is not None:
            self.item.setVisible(self._locked_item_visible)
        self._locked = False
        self._locked_item_to_global = None
        # This helper is also used by detach/item replacement, not only by
        # set_locked_visuals(False).  Always return the view to its cheap
        # editing repaint mode here so a detach cannot leave FullViewportUpdate
        # enabled indefinitely.
        self.main_window.view.set_locked_overlay_active(False)

    def _item_to_global_transform(self):
        """Return the selected image's exact local-to-desktop transform."""
        return self._item_to_global_transform_for(self.item)

    def _item_to_global_transform_for(self, item):
        if item is None:
            return None
        scene_from_global = self._scene_from_global_transform()
        scene_to_global, invertible = scene_from_global.inverted()
        if not invertible:
            return None
        origin = scene_to_global.map(item.mapToScene(QtCore.QPointF(0, 0)))
        x_point = scene_to_global.map(item.mapToScene(QtCore.QPointF(1, 0)))
        y_point = scene_to_global.map(item.mapToScene(QtCore.QPointF(0, 1)))
        return affine_from_points(origin, x_point, y_point)

    def _on_bridge_state(self, state):
        if self.item is None or not isinstance(state, dict):
            return
        hwnd = state.get('hwnd')
        if (hwnd is not None and self.target is not None
                and int(hwnd) != int(self.target.hwnd)):
            return
        state = self._bridge_state_in_local_pixels(state)
        self._bridge_state = state
        self._bridge_available = True
        self._bridge_zoom = state.get('zoom')
        self._bridge_center = state.get('center')
        self._bridge_rotation = float(state.get('rotation', 0.0))

        if not self._locked:
            self._set_status('Pinned (Krita zoom bridge ready)')
            return

        document_to_global = self._document_to_global_transform(state)
        self.locked_overlay.update_state(state, document_to_global)
        if state.get('canvas_rect') is None or document_to_global is None:
            self._set_status(
                'Pinned — waiting for complete Krita canvas data; '
                'restart Krita if needed')
        else:
            self._set_status('Pinned (Krita canvas locked)')

    @staticmethod
    def _bridge_state_in_local_pixels(state, screens=None):
        """Convert Krita Qt coordinates to this process's Qt coordinates.

        Qt 5 Krita can use DPR 1 while Qt 6 BeeRef uses Windows' fractional
        scale. Windows screen origins stay in native pixels in Qt, so scale
        offsets about the monitor origin, never about desktop (0, 0).
        Image coordinates stay unchanged; all canvas distances scale once.
        """
        source_dpr = state.get('canvas_device_pixel_ratio')
        rect = state.get('canvas_rect')
        if source_dpr is None or rect is None:
            return state  # Preserve pre-DPI bridge contracts.
        if screens is None:
            screens = QtGui.QGuiApplication.screens()
        screen = next((s for s in screens
                       if s.name() == state.get('canvas_screen_name')), None)
        origin = state.get('canvas_screen_origin')
        if screen is None and origin is not None:
            screen = next((s for s in screens
                           if (s.geometry().x(), s.geometry().y())
                           == tuple(origin)), None)
        if screen is None and len(screens) == 1:
            # Build 3.1 already supplies DPR, but not screen identification.
            screen = screens[0]
        if screen is None:
            # Ambiguous old multi-monitor data must not establish a bad lock.
            return dict(state, canvas_rect=None)
        ratio = float(source_dpr) / screen.devicePixelRatio()
        if not math.isfinite(ratio) or ratio <= 0:
            return dict(state, canvas_rect=None)
        destination_x = screen.geometry().x()
        destination_y = screen.geometry().y()
        if origin is not None:
            source_x, source_y = origin
        else:
            source_x, source_y = destination_x, destination_y
        left, top, width, height = rect
        result = dict(state)
        result['canvas_rect'] = (
            destination_x + (left - source_x) * ratio,
            destination_y + (top - source_y) * ratio,
            width * ratio, height * ratio)
        if state.get('view_matrix') is not None:
            result['view_matrix'] = tuple(
                v * ratio for v in state['view_matrix'])
        result['zoom'] = state['zoom'] * ratio
        return result

    @staticmethod
    def _bridge_visual_state_key(state):
        """Return only bridge fields that affect proxy pixels."""
        center = state.get('center')
        if center is None:
            center_key = None
        else:
            center_key = (float(center.x()), float(center.y()))
        canvas_rect = state.get('canvas_rect')
        rect_key = tuple(map(float, canvas_rect)) if canvas_rect else None
        return (float(state.get('zoom', 0.0)), center_key,
                float(state.get('rotation', 0.0)), rect_key,
                tuple(map(float, state['view_matrix']))
                if state.get('view_matrix') else None)

    def _on_bridge_zoom(self, zoom, global_pivot, hwnd, center, rotation):
        if self.item is None:
            return
        if (hwnd is not None and self.target is not None
                and int(hwnd) != int(self.target.hwnd)):
            return
        if self._bridge_zoom not in (None, 0):
            ratio = zoom / self._bridge_zoom
            if 0.25 < ratio < 4.0 and abs(ratio - 1.0) > 1e-4:
                self._scale_about_cursor(ratio, global_pivot)
            elif (center is not None and self._bridge_center is not None
                  and abs(ratio - 1.0) <= 1e-4):
                self._translate_for_canvas_pan(
                    center - self._bridge_center, zoom, rotation)
        self._bridge_zoom = zoom
        self._bridge_center = center
        self._bridge_rotation = rotation
        self._bridge_available = True
        self._set_status('Pinned (Krita zoom bridge active)')

    def _translate_for_canvas_pan(self, center_delta, zoom, rotation):
        # Krita's preferred center is in image/document pixels.  At a
        # constant zoom, moving that center right makes the visible canvas
        # move left.  Use Qt's rotation matrix so the sign/convention matches
        # Krita and retain fractional pixels instead of rounding each update.
        rotated_delta = QtGui.QTransform().rotate(rotation).map(center_delta)
        global_delta = QtCore.QPointF(
            -rotated_delta.x() * zoom,
            -rotated_delta.y() * zoom)
        scene_delta = self._scene_delta_from_global_delta(global_delta)
        self.item.setPos(self.item.pos() + scene_delta)

    def _on_transform(self, matrix):
        if self.item is None:
            return
        # The Krita bridge also publishes a richer state record.  Once that
        # record exists, its absolute document-to-canvas transform is the
        # source of truth; never mutate the hidden editable item from the
        # legacy matrix signal.
        if self._bridge_state is not None or self._locked:
            # Keep the legacy baseline fresh in case the richer state file
            # disappears and the helper falls back to matrix-only updates.
            self._bridge_matrix = matrix
            return
        self._bridge_available = True
        if not hasattr(self, '_bridge_matrix'):
            self._bridge_matrix = matrix
            self._set_status('Pinned (transform bridge active)')
            return
        try:
            delta = matrix * self._bridge_matrix.inverted()[0]
            self.item.setTransform(delta, combine=True)
            self._bridge_matrix = matrix
        except (AttributeError, TypeError):
            self._set_status('Needs resync')

    def _on_bridge_disconnected(self):
        self._bridge_available = False
        self._bridge_zoom = None
        self._bridge_state = None
        self._bridge_initial_state = None
        if self._locked:
            self.locked_overlay.hide()
            self.main_window.view.viewport().update()
        if self.target is not None:
            self._set_status('Pinned (window-follow; resync available)')

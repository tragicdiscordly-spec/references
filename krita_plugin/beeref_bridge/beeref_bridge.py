"""Publish Krita's real canvas zoom for BeeRef tracing overlays.

Krita's Python API exposes the canvas zoom directly, while the native window
title does not. Publish absolute transforms on changes and a lightweight
idle heartbeat so BeeRef can reject data left by an exited Krita instance.
"""

import json
import os
import tempfile
import time
import sys

try:
    # Use Krita's binding, even if a different PyQt is also installed.
    if 'PyQt5.QtCore' in sys.modules:
        raise ImportError
    from PyQt6.QtCore import QTimer, Qt, QPointF
    from PyQt6.QtGui import QCursor
    from PyQt6.QtWidgets import QApplication, QWidget
except ImportError:
    from PyQt5.QtCore import QTimer, Qt, QPointF
    from PyQt5.QtGui import QCursor
    from PyQt5.QtWidgets import QApplication, QWidget

from krita import Extension, Krita


class BeeRefBridgeExtension(Extension):
    def __init__(self, parent):
        super().__init__(parent)
        self.app = Krita.instance()
        self.timer = QTimer(self)
        self.timer.setInterval(30)
        try:
            self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        except AttributeError:
            self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self.publish)
        self.path = os.path.join(
            os.environ.get('LOCALAPPDATA', os.path.expanduser('~')),
            'BeeRef', 'clipstudio_transform.json')
        self._last_state = None
        self._last_publish = 0.0
        self._canvas_widget = None
        self._canvas_window_id = None

    def setup(self):
        self.timer.start()
        self.publish()

    def createActions(self, window):
        # The bridge is intentionally automatic. This action is only a
        # convenient way to confirm that the plugin is installed and active.
        action = window.createAction(
            'beeref_bridge_publish_now',
            'Publish BeeRef zoom now',
            'tools/scripts')
        if action is not None:
            action.triggered.connect(self.publish)

    def publish(self):
        try:
            window = self.app.activeWindow()
            view = window.activeView() if window is not None else None
            canvas = view.canvas() if view is not None else None
            if canvas is None:
                return

            # zoomLevel is a factor; 16 means 1600%, not 16%.
            zoom = float(canvas.zoomLevel())
            preferred_center = canvas.preferredCenter()
            center = [preferred_center.x(), preferred_center.y()]
            rotation = float(canvas.rotation())
            qwindow = window.qwindow() if window is not None else None
            hwnd = int(qwindow.winId()) if qwindow is not None else None
            cursor = QCursor.pos()
            canvas_widget = self._canvas_widget_for(qwindow, canvas)
            canvas_rect = self._widget_global_rect(canvas_widget)
            view_matrix = self._view_matrix(view)
            state = (hwnd, zoom, center[0], center[1], rotation,
                     tuple(canvas_rect or ()), tuple(view_matrix or ()))
            now = time.time()
            if state == self._last_state and now - self._last_publish < 0.5:
                return

            payload = {
                'protocol': 3,
                'bridge_build': 'image-transform-3.2',
                'bridge_source': os.path.abspath(__file__),
                'pid': os.getpid(),
                'timestamp': now,
                'zoom': zoom,
                'cursor': [cursor.x(), cursor.y()],
                'hwnd': hwnd,
                'center': center,
                'rotation': rotation,
            }
            if canvas_widget is not None:
                payload['canvas_widget_class'] = canvas_widget.metaObject().className()
                payload['canvas_device_pixel_ratio'] = float(canvas_widget.devicePixelRatioF())
                screen = canvas_widget.screen()
                if screen is not None:
                    payload['canvas_screen_name'] = screen.name()
                    payload['canvas_screen_origin'] = [screen.geometry().x(), screen.geometry().y()]
            if canvas_rect is not None:
                payload['canvas_rect'] = list(canvas_rect)
            if view_matrix is not None:
                payload['view_matrix'] = list(view_matrix)
                payload['view_matrix_space'] = 'image'
            self._write_json(payload)
            self._last_state = state
            self._last_publish = now
        except (AttributeError, RuntimeError, TypeError, ValueError, OSError):
            # Krita can briefly invalidate a view while switching documents.
            # The next timer tick will retry without interrupting Krita.
            return

    @staticmethod
    def _widget_global_rect(widget):
        if widget is None or not widget.isVisible():
            return None
        try:
            top_left = widget.mapToGlobal(widget.rect().topLeft())
            size = widget.size()
            if size.width() <= 0 or size.height() <= 0:
                return None
            return (int(top_left.x()), int(top_left.y()),
                    int(size.width()), int(size.height()))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return None

    def _canvas_widget_for(self, qwindow, canvas):
        """Return a cached canvas widget, rediscovering it when needed.

        Enumerating every QWidget in Krita every 30 ms is surprisingly
        expensive.  The canvas widget normally survives zooming and panning,
        so keep it until Krita replaces the active native window or the widget
        becomes invalid.
        """
        try:
            window_id = int(qwindow.winId())
        except (AttributeError, RuntimeError, TypeError, ValueError):
            window_id = None

        if (self._canvas_widget is not None
                and self._canvas_window_id == window_id):
            try:
                if self._canvas_widget.isVisible():
                    return self._canvas_widget
            except RuntimeError:
                pass

        self._canvas_window_id = window_id
        self._canvas_widget = self._find_canvas_widget(qwindow, canvas)
        return self._canvas_widget

    @staticmethod
    def _view_matrix(view):
        """Return Krita image-pixel -> canvas-widget coordinates.

        Krita's document space uses physical units, not image pixels. Use
        flakeToImageTransform so resolution never changes the anchor's units.
        flakeToCanvasTransform includes the actual pan, rotation and mirror.
        """
        try:
            flake_to_canvas = view.flakeToCanvasTransform()
            flake_to_document = view.flakeToImageTransform()
            document_to_flake, invertible = flake_to_document.inverted()
            if not invertible:
                return None

            def map_document(point):
                return flake_to_canvas.map(
                    document_to_flake.map(point))

            origin = map_document(QPointF(0, 0))
            x_point = map_document(QPointF(1, 0))
            y_point = map_document(QPointF(0, 1))
            return (
                float(x_point.x() - origin.x()),
                float(x_point.y() - origin.y()),
                float(y_point.x() - origin.x()),
                float(y_point.y() - origin.y()),
                float(origin.x()),
                float(origin.y()),
            )
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return None

    @staticmethod
    def _find_canvas_widget(qwindow, canvas):
        """Find Krita's visible canvas widget and return the best match.

        Canvas is exposed to Python as a Krita API object rather than always
        as the underlying QWidget.  The widget tree is therefore used as a
        compatibility fallback across Krita builds.
        """
        if qwindow is None:
            return None
        if isinstance(canvas, QWidget):
            return canvas

        # A few Krita builds expose the underlying widget through the Canvas
        # wrapper.  Prefer that direct route when available.
        for name in ('canvasWidget', 'widget', 'qwidget', 'view'):
            try:
                candidate = getattr(canvas, name)
                candidate = candidate() if callable(candidate) else candidate
                if isinstance(candidate, QWidget) and candidate.isVisible():
                    return candidate
            except (AttributeError, RuntimeError, TypeError):
                continue

        candidates = []
        try:
            widgets = QApplication.allWidgets()
        except (AttributeError, RuntimeError):
            return None

        try:
            window_id = int(qwindow.winId())
        except (AttributeError, RuntimeError, TypeError, ValueError):
            window_id = None

        excluded_words = (
            'dock', 'toolbar', 'menubar', 'statusbar', 'ruler', 'scrollbar',
            'scrollarea', 'mdi', 'tabbar', 'tabwidget', 'welcome', 'sidebar',
            'workspace')
        preferred_words = (
            'canvas', 'opengl', 'viewport', 'paint', 'image', 'display')
        for widget in widgets:
            try:
                if widget is qwindow or not widget.isVisible():
                    continue
                widget_window = widget.window()
                if (widget_window is None
                        or (window_id is not None
                            and int(widget_window.winId()) != window_id)):
                    continue
                rect = widget.rect()
                width = rect.width()
                height = rect.height()
                if width < 200 or height < 150:
                    continue
                class_name = widget.metaObject().className().lower()
                object_name = widget.objectName().lower()
                label = f'{class_name} {object_name}'
                if any(word in label for word in excluded_words):
                    continue
                score = width * height
                score += 100_000_000 * sum(
                    name in class_name for name in (
                        'kisopenglcanvas2', 'kisqpaintercanvas',
                        'kiscanvaswidgetbase'))
                score += 10_000_000 * sum(
                    word in label for word in preferred_words)
                # Prefer a real viewport over a large generic container.
                score += 2_000_000 * sum(
                    word in label for word in ('qopenglwidget', 'qopengl',
                                                'canvas3d', 'viewport'))
                candidates.append((score, widget))
            except (AttributeError, RuntimeError, TypeError):
                continue

        if not candidates:
            return None
        candidates.sort(key=lambda value: value[0], reverse=True)
        return candidates[0][1]

    def _write_json(self, payload):
        directory = os.path.dirname(self.path)
        os.makedirs(directory, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix='clipstudio_transform-', suffix='.tmp', dir=directory)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(payload, stream, separators=(',', ':'))
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

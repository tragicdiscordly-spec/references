"""A small, capture-excluded overlay for a locked tracing reference.

The normal BeeRef view is a desktop editing surface.  It is deliberately not
used to render the locked copy: a full-desktop QGraphicsView can retain stale
pixels in a translucent Windows backing store when an item moves.  This
overlay is a single canvas-sized QWidget that clears and repaints its whole
surface on every absolute state update.
"""

import ctypes
import platform
from ctypes import wintypes

from PyQt6 import QtCore, QtGui, QtWidgets


WDA_EXCLUDEFROMCAPTURE = 0x00000011

if platform.system() == 'Windows':
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.SetWindowDisplayAffinity.argtypes = [
        wintypes.HWND, wintypes.DWORD]
    user32.SetWindowDisplayAffinity.restype = wintypes.BOOL


def affine_from_points(origin, x_point, y_point):
    """Build an affine transform from the image basis vectors.

    QTransform maps x' = m11*x + m21*y + m31 and
    y' = m12*x + m22*y + m32.  Constructing the matrix from mapped points
    avoids relying on matrix multiplication order when transforms come from
    different Qt components.
    """
    x_axis = x_point - origin
    y_axis = y_point - origin
    return QtGui.QTransform(
        x_axis.x(), x_axis.y(), 0,
        y_axis.x(), y_axis.y(), 0,
        origin.x(), origin.y(), 1)


class LockedReferenceOverlay(QtWidgets.QWidget):
    """Render one reference image in the current Krita canvas only."""

    def __init__(self):
        super().__init__(None, flags=(
            QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
            | QtCore.Qt.WindowType.Tool
            | QtCore.Qt.WindowType.WindowDoesNotAcceptFocus))
        self.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setWindowFlag(
            QtCore.Qt.WindowType.WindowTransparentForInput, True)
        self.setAutoFillBackground(False)
        self.setStyleSheet('background: transparent; border: none;')
        self._source = QtGui.QPixmap()
        self._crop = QtCore.QRectF()
        self._opacity = 1.0
        self._local_to_document = None
        self._coordinate_space = None
        self._item_to_global = None
        self._active = False
        self._last_state = None
        self.hide()

    @property
    def active(self):
        return self._active

    def set_reference(self, item, item_to_global, state, document_to_global):
        """Capture the editable item and establish its lock baseline.

        ``item_to_global`` is the image item's complete BeeRef-local to
        desktop transform at the instant Ctrl+T is pressed.  The baseline is
        converted to document coordinates only after Krita supplies a valid
        document-to-global transform.
        """
        self._source = self._source_pixmap(item)
        self._crop = QtCore.QRectF(item.crop)
        self._opacity = float(item.opacity())
        self._item_to_global = QtGui.QTransform(item_to_global)
        self._local_to_document = None
        self._coordinate_space = None
        self._active = True
        self._last_state = None
        self.update_state(state, document_to_global)

    def clear_reference(self):
        self._active = False
        self._local_to_document = None
        self._item_to_global = None
        self._last_state = None
        self.hide()
        self.update()

    @staticmethod
    def _source_pixmap(item):
        if getattr(item, 'grayscale', False):
            source = getattr(item, '_grayscale_pixmap', None)
            if source is not None and not source.isNull():
                return source.copy()
        return item.pixmap().copy()

    @staticmethod
    def _map_transform(transform, point):
        return transform.map(point)

    @classmethod
    def _compose_by_mapping(cls, first, second):
        """Return a transform equivalent to ``second(first(point))``."""
        origin = second.map(first.map(QtCore.QPointF(0, 0)))
        x_point = second.map(first.map(QtCore.QPointF(1, 0)))
        y_point = second.map(first.map(QtCore.QPointF(0, 1)))
        return affine_from_points(origin, x_point, y_point)

    def _ensure_document_baseline(self, document_to_global):
        if self._local_to_document is not None:
            return True
        if self._item_to_global is None or document_to_global is None:
            return False
        global_to_document, invertible = document_to_global.inverted()
        if not invertible:
            return False
        # local image -> desktop at lock, then desktop -> Krita document.
        self._local_to_document = self._compose_by_mapping(
            self._item_to_global, global_to_document)
        return True

    def update_state(self, state, document_to_global):
        """Repaint from the absolute Krita transform, never a delta."""
        if not self._active or not isinstance(state, dict):
            return
        space = state.get('view_matrix_space') or 'legacy-center'
        if self._coordinate_space is not None and space != self._coordinate_space:
            # Never reinterpret a saved anchor in another set of units.
            self.hide()
            return
        if not self._ensure_document_baseline(document_to_global):
            # The bridge may publish its first state a few milliseconds after
            # Ctrl+T. Stay armed but invisible until that state is complete.
            self.hide()
            return
        self._coordinate_space = space

        canvas_rect = state.get('canvas_rect')
        if (not canvas_rect or len(canvas_rect) != 4
                or float(canvas_rect[2]) <= 0
                or float(canvas_rect[3]) <= 0
                or document_to_global is None):
            self.hide()
            return

        left, top, width, height = map(float, canvas_rect)
        geometry = QtCore.QRect(
            round(left), round(top), round(width), round(height))
        if geometry.width() <= 0 or geometry.height() <= 0:
            self.hide()
            return
        if self.geometry() != geometry:
            self.setGeometry(geometry)

        def to_overlay(point):
            document_point = self._local_to_document.map(point)
            global_point = document_to_global.map(document_point)
            return QtCore.QPointF(
                global_point.x() - geometry.x(), global_point.y() - geometry.y())

        image_to_overlay = affine_from_points(
            to_overlay(QtCore.QPointF(0, 0)),
            to_overlay(QtCore.QPointF(1, 0)),
            to_overlay(QtCore.QPointF(0, 1)))
        self._image_to_overlay = image_to_overlay
        self._last_state = state
        if self.isHidden():
            self.show()
        self.raise_()
        self.update()

    def _apply_capture_exclusion(self):
        if platform.system() != 'Windows' or not self.windowHandle():
            return
        hwnd = wintypes.HWND(int(self.winId()))
        if not user32.SetWindowDisplayAffinity(
                hwnd, WDA_EXCLUDEFROMCAPTURE):
            # Do not throw from a paint/update tick if a Windows build rejects
            # display affinity. The overlay remains usable on screen.
            return

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_capture_exclusion()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        try:
            # Always clear the complete translucent backing store. This is
            # the important difference from the old moving QGraphics clone:
            # old positions cannot remain as trails.
            painter.setCompositionMode(
                QtGui.QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(self.rect(), QtCore.Qt.GlobalColor.transparent)
            if (self._source.isNull()
                    or getattr(self, '_image_to_overlay', None) is None):
                return

            painter.setCompositionMode(
                QtGui.QPainter.CompositionMode.CompositionMode_SourceOver)
            painter.setRenderHint(
                QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.setOpacity(self._opacity)
            painter.setTransform(self._image_to_overlay, combine=False)
            clip = QtGui.QPainterPath()
            clip.addRect(self._crop)
            painter.setClipPath(clip)
            painter.drawPixmap(0, 0, self._source)
        finally:
            painter.end()

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

from importlib.resources import files as rsc_files
import logging

from PyQt6 import QtCore, QtGui, QtWidgets


logger = logging.getLogger(__name__)


def reference_icon():
    """Original purple reference-card icon, legible at Windows tray sizes."""
    icon = QtGui.QIcon()
    for size in (16, 20, 24, 32, 48, 64, 128, 256):
        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.scale(size / 32, size / 32)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor('#5865F2'))
        painter.drawRoundedRect(QtCore.QRectF(1, 1, 30, 30), 8, 8)
        painter.setBrush(QtGui.QColor('#C5CAFF'))
        painter.drawRoundedRect(QtCore.QRectF(7, 7, 17, 17), 3, 3)
        painter.setBrush(QtGui.QColor('white'))
        painter.drawRoundedRect(QtCore.QRectF(10, 10, 16, 16), 3, 3)
        painter.setBrush(QtGui.QColor('#5865F2'))
        painter.drawEllipse(QtCore.QRectF(19, 13, 3, 3))
        path = QtGui.QPainterPath(QtCore.QPointF(12, 23))
        path.lineTo(16, 17)
        path.lineTo(19, 21)
        path.lineTo(22, 18)
        path.lineTo(24, 23)
        path.closeSubpath()
        painter.drawPath(path)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


class BeeAssets:
    _instance = None
    PATH = rsc_files('beeref.assets')

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls, *args, **kwargs)
            cls._instance.on_new()
        return cls._instance

    def on_new(self):
        logger.debug(f'Assets path: {self.PATH}')

        self.logo = reference_icon()
        assert self.logo.isNull() is False
        self.cursor_rotate = self.cursor_from_image(
            'cursor_rotate.png', (20, 20))
        self.cursor_flip_h = self.cursor_from_image(
            'cursor_flip_h.png', (20, 20))
        self.cursor_flip_v = self.cursor_from_image(
            'cursor_flip_v.png', (20, 20))

    def cursor_from_image(self, filename, hotspot):
        app = QtWidgets.QApplication.instance()
        scaling = app.primaryScreen().devicePixelRatio()
        img = QtGui.QImage(str(self.PATH.joinpath(filename)))
        assert img.isNull() is False
        pixmap = QtGui.QPixmap.fromImage(img)
        pixmap.setDevicePixelRatio(scaling)
        return QtGui.QCursor(
            pixmap, int(hotspot[0]/scaling), int(hotspot[1]/scaling))

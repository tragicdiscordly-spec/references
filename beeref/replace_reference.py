"""Undoable phone replacement with a stable locked document anchor."""
from PyQt6 import QtCore, QtGui
from beeref.locked_overlay import LockedReferenceOverlay


class ReplaceReference(QtGui.QUndoCommand):
    def __init__(self, controller, item, image):
        super().__init__('Replace reference from phone')
        self.controller, self.item = controller, item
        self.before = self.snapshot()
        self.after = None
        self.pixmap = QtGui.QPixmap.fromImage(image)
        old = item.crop
        scale = min(old.width() / image.width(), old.height() / image.height())
        self.mapping = QtGui.QTransform(scale, 0, 0, scale,
            old.center().x() - image.width() * scale / 2,
            old.center().y() - image.height() * scale / 2)

    def snapshot(self):
        i = self.item
        return (i.pixmap(), QtCore.QRectF(i.crop), i.scale(),
                QtCore.QPointF(i.pos()), i.filename, i.grayscale)

    def restore(self, state):
        pixmap, crop, scale, pos, filename, gray = state
        self.item.setPixmap(pixmap)
        self.item.crop = crop
        self.item.setScale(scale, anchor=QtCore.QPointF())
        self.item.setPos(pos)
        self.item.filename = filename
        self.item.grayscale = gray

    def refresh_locked(self, mapping):
        c = self.controller
        overlay = c.locked_overlay
        if not c._locked or c.item is not self.item or overlay._local_to_document is None:
            return
        baseline = LockedReferenceOverlay._compose_by_mapping(mapping, overlay._local_to_document)
        state = c._bridge_state
        if state is None:
            overlay._source = overlay._source_pixmap(self.item)
            overlay._crop = QtCore.QRectF(self.item.crop)
            overlay._local_to_document = baseline
            overlay._last_render_key = None
            return
        transform = c._document_to_global_transform(state)
        if transform is not None:
            global_mapping = LockedReferenceOverlay._compose_by_mapping(baseline, transform)
            overlay.set_reference(self.item, global_mapping, state, transform)

    def redo(self):
        if self.after is None:
            center = self.item.mapToScene(self.item.crop.center())
            self.item.setPixmap(self.pixmap)
            self.item.setScale(self.before[2] * self.mapping.m11(), anchor=QtCore.QPointF())
            self.item.setPos(self.item.pos() + center - self.item.mapToScene(self.item.crop.center()))
            self.item.filename = None
            self.item.grayscale = self.before[5]
            self.after = self.snapshot()
        else:
            self.restore(self.after)
        self.refresh_locked(self.mapping)

    def undo(self):
        self.restore(self.before)
        self.refresh_locked(self.mapping.inverted()[0])

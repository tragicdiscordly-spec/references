import http.client
import pytest
from PyQt6 import QtCore, QtGui
from beeref.phone_receiver import PhoneReceiver, MAX_UPLOAD
from beeref.items import BeePixmapItem


def image_bytes():
    image = QtGui.QImage(20, 10, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtCore.Qt.GlobalColor.red)
    data = QtCore.QByteArray()
    buffer = QtCore.QBuffer(data)
    buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, 'PNG')
    return bytes(data)


def test_phone_endpoint_requires_pairing_and_valid_image(qapp, qtbot):
    receiver = PhoneReceiver(bind='127.0.0.1')
    received = []
    receiver.image_received.connect(received.append)
    def request(method, path, data=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', receiver.port, timeout=3)
        connection.request(method, path, data, headers or {})
        response = connection.getresponse()
        result = response.status, response.read()
        connection.close()
        return result
    try:
        assert request('GET', '/')[0] == 404
        assert request('GET', '/' + receiver.token)[0] == 200
        assert request('POST', '/wrong/upload', image_bytes())[0] == 403
        assert request('POST', '/' + receiver.token + '/upload', b'garbage')[0] == 400
        assert request('POST', '/' + receiver.token + '/upload', b'',
                       {'Content-Length': str(MAX_UPLOAD + 1)})[0] == 413
        assert request('POST', '/' + receiver.token + '/upload', image_bytes())[0] == 202
        qtbot.waitUntil(lambda: len(received) == 1)
        assert received[0].size() == QtCore.QSize(20, 10)
    finally:
        receiver.stop()
    assert not receiver.thread.is_alive()


def test_controls_are_children_of_protected_window(main_window):
    view = main_window.view
    view.on_context_menu(QtCore.QPoint(40, 40))
    panel = view.reference_controls
    assert panel.isVisible()
    assert not panel.isWindow()
    assert panel.window() is main_window
    assert not view.context_menu.isVisible()
    main_window._update_lock_feedback()
    assert main_window.tray_icon.contextMenu() is None
    assert main_window.tray_lock_action.parent() is main_window
    panel.open(menu=view.context_menu.actions()[0].menu())
    assert panel.window() is main_window


def test_editing_background_catches_input_but_locked_background_is_transparent(view):
    image = QtGui.QImage(10, 10, QtGui.QImage.Format.Format_ARGB32)
    for locked, alpha in ((False, 1), (True, 0)):
        view._locked_overlay_active = locked
        image.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(image)
        view.drawBackground(painter, QtCore.QRectF(0, 0, 10, 10))
        painter.end()
        assert image.pixelColor(5, 5).alpha() == alpha


@pytest.mark.parametrize('locked', [False, True])
def test_phone_replacement_preserves_center_opacity_grayscale_and_undo(main_window, monkeypatch, locked):
    controller = main_window.pin_controller
    image = QtGui.QImage(100, 100, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtCore.Qt.GlobalColor.blue)
    item = BeePixmapItem(image)
    item.setPos(50, 60)
    item.setScale(2)
    item.setOpacity(.4)
    item.grayscale = True
    main_window.view.scene.addItem(item)
    item.setSelected(True)
    controller.item = item
    state = dict(protocol=3, zoom=1, canvas_rect=(0, 0, 800, 600),
                 view_matrix_space='image', view_matrix=(1, 0, 0, 1, 0, 0))
    monkeypatch.setattr(controller.bridge, 'poll', lambda **kw: controller._on_bridge_state(state))
    if locked:
        controller.set_locked_visuals(True)
        baseline = QtGui.QTransform(controller.locked_overlay._local_to_document)
        document_center = baseline.map(QtCore.QPointF(50, 50))
    center = item.mapToScene(item.crop.center())
    replacement = QtGui.QImage(200, 100, QtGui.QImage.Format.Format_ARGB32)
    replacement.fill(QtCore.Qt.GlobalColor.red)
    main_window._receive_phone_image(replacement)
    assert item.pixmap().size() == QtCore.QSize(200, 100)
    assert item.mapToScene(item.crop.center()) == center
    assert item.opacity() == .4 and item.grayscale
    if locked:
        assert not item.isVisible()
        assert controller._locked
        actual = controller.locked_overlay._local_to_document.map(QtCore.QPointF(100, 50))
        assert actual.x() == pytest.approx(document_center.x())
        assert actual.y() == pytest.approx(document_center.y())
    main_window.view.undo_stack.undo()
    assert item.pixmap().size() == QtCore.QSize(100, 100)
    assert item.mapToScene(item.crop.center()) == center
    if locked:
        actual = controller.locked_overlay._local_to_document.map(QtCore.QPointF(50, 50))
        assert actual.x() == pytest.approx(document_center.x())
        assert actual.y() == pytest.approx(document_center.y())

import http.client
from urllib.parse import urlencode
import pytest
from PyQt6 import QtCore, QtGui
from PyQt6 import QtWidgets
from beeref.phone_receiver import (
    PhoneReceiver, MAX_UPLOAD, check_login, lan_address, make_login)
from PyQt6.QtNetwork import QNetworkInterface
from beeref.items import BeePixmapItem


def image_bytes():
    image = QtGui.QImage(20, 10, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtCore.Qt.GlobalColor.red)
    data = QtCore.QByteArray()
    buffer = QtCore.QBuffer(data)
    buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, 'PNG')
    return bytes(data)


def test_pairing_link_uses_lan_instead_of_wireguard_address():
    from types import SimpleNamespace
    flags = QNetworkInterface.InterfaceFlag
    kinds = QNetworkInterface.InterfaceType
    def interface(kind, address, connected=True):
        return SimpleNamespace(type=lambda: kind,
            flags=lambda: (flags.IsUp | flags.IsRunning) if connected else flags.CanBroadcast,
            addressEntries=lambda: [SimpleNamespace(ip=lambda: SimpleNamespace(toString=lambda: address))])
    assert lan_address([
        interface(kinds.Unknown, '10.5.0.2'),
        interface(kinds.Wifi, '192.168.2.10', False),
        interface(kinds.Ethernet, '169.254.1.2'),
        interface(kinds.Ethernet, '192.168.1.17')]) == '192.168.1.17'
    assert lan_address([interface(kinds.Ethernet, '10.0.0.15')]) == '10.0.0.15'
    with pytest.raises(OSError):
        lan_address([interface(kinds.Unknown, '10.5.0.2')])


@pytest.mark.parametrize('username', ['gloom', 'Zoë', '絵描き'])
def test_check_login_accepts_any_username(username):
    login = make_login(username, 'sécret')
    assert check_login(username, 'sécret', login)
    assert not check_login(username, 'wrong', login)
    assert not check_login(username + 'x', 'sécret', login)


def test_check_login_rejects_malformed_verifier():
    login = make_login('gloom', 'secret')
    login['salt'] = 'not base64!'
    assert not check_login('gloom', 'secret', login)


def test_phone_endpoint_requires_pairing_and_valid_image(qapp, qtbot):
    receiver = PhoneReceiver(bind='127.0.0.1', login=make_login('gloom', 'secret'))
    received = []
    receiver.image_received.connect(received.append)
    def request(method, path, data=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', receiver.port, timeout=3)
        connection.request(method, path, data, headers or {})
        response = connection.getresponse()
        result = response.status, response.read(), dict(response.getheaders())
        connection.close()
        return result
    try:
        assert request('GET', '/')[0] == 404
        login_page = request('GET', '/' + receiver.token)
        assert login_page[0] == 200 and b'<form' in login_page[1]
        wrong = urlencode({'username': 'gloom', 'password': 'wrong'})
        assert request('POST', '/' + receiver.token, wrong,
                       {'Content-Type': 'application/x-www-form-urlencoded'})[0] == 401
        credentials = urlencode({'username': 'gloom', 'password': 'secret'})
        logged_in = request('POST', '/' + receiver.token, credentials,
                            {'Content-Type': 'application/x-www-form-urlencoded'})
        assert logged_in[0] == 303
        cookie = logged_in[2]['Set-Cookie'].split(';', 1)[0]
        session = {'Cookie': cookie}
        assert request('GET', '/' + receiver.token, headers=session)[0] == 200
        assert request('POST', '/wrong/upload', image_bytes())[0] == 403
        assert request('POST', '/' + receiver.token + '/upload', image_bytes())[0] == 401
        assert request('POST', '/' + receiver.token + '/upload', b'garbage', session)[0] == 400
        assert request('POST', '/' + receiver.token + '/upload', b'',
                       {**session, 'Content-Length': str(MAX_UPLOAD + 1)})[0] == 413
        assert request('POST', '/' + receiver.token + '/upload', image_bytes(), session)[0] == 202
        qtbot.waitUntil(lambda: len(received) == 1)
        assert received[0].size() == QtCore.QSize(20, 10)
    finally:
        receiver.stop()
    assert not receiver.thread.is_alive()


def test_cloudflare_start_retries_once(qapp):
    attempts = []
    class Tunnel:
        origin = 'https://retry-worked.trycloudflare.com'
        stopped = False
        def stop(self):
            self.stopped = True
    tunnel = Tunnel()
    def factory(port):
        attempts.append(port)
        if len(attempts) == 1:
            raise OSError('temporary failure')
        return tunnel
    receiver = PhoneReceiver(bind='127.0.0.1', cloudflare=True,
                             tunnel_factory=factory)
    try:
        assert len(attempts) == 2
        assert receiver.url.startswith(tunnel.origin + '/')
    finally:
        receiver.stop()
    assert tunnel.stopped


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


@pytest.mark.parametrize('confirmed', [False, True])
def test_quit_button_uses_app_quit_with_unsaved_changes_check(main_window, qtbot, monkeypatch, confirmed):
    calls = []
    view = main_window.view
    monkeypatch.setattr(view, 'get_confirmation_unsaved_changes', lambda message: confirmed)
    monkeypatch.setattr(type(view.app), 'quit', staticmethod(lambda: calls.append('quit')))
    view.on_context_menu(QtCore.QPoint(20, 20))
    panel = view.reference_controls
    button = next(panel.layout.itemAt(i).widget() for i in range(panel.layout.count())
                  if isinstance(panel.layout.itemAt(i).widget(), QtWidgets.QPushButton)
                  and panel.layout.itemAt(i).widget().text() == 'Quit References ×')
    qtbot.mouseClick(button, QtCore.Qt.MouseButton.LeftButton)
    assert calls == (['quit'] if confirmed else [])


def test_visible_menu_navigation_lays_out_new_children(main_window, qtbot, monkeypatch):
    from types import SimpleNamespace
    view = main_window.view
    image = QtGui.QImage(20, 20, QtGui.QImage.Format.Format_ARGB32)
    item = BeePixmapItem(image)
    view.scene.addItem(item)
    item.setSelected(True)
    panel = view.reference_controls
    monkeypatch.setattr(main_window, 'start_phone_receiver',
                        lambda: SimpleNamespace(
                            url='https://example.trycloudflare.com/test',
                            login={'username': 'gloom'}))
    view.on_context_menu(QtCore.QPoint(20, 20))

    def click(text):
        button = next(panel.layout.itemAt(i).widget()
                      for i in range(panel.layout.count())
                      if isinstance(panel.layout.itemAt(i).widget(), QtWidgets.QPushButton)
                      and text in panel.layout.itemAt(i).widget().text())
        qtbot.mouseClick(button, QtCore.Qt.MouseButton.LeftButton)
        QtWidgets.QApplication.processEvents()

    def check_page():
        assert panel.height() > 80
        for i in range(panel.layout.count()):
            widget = panel.layout.itemAt(i).widget()
            assert widget.isVisible()
            assert widget.height() >= widget.minimumSizeHint().height()
            assert panel.rect().contains(widget.geometry())

    for _ in range(2):
        click('Images')
        check_page()
        click('Opacity')
        check_page()
        click('Back')
        click('Send image from phone')
        check_page()
        assert panel.findChild(QtWidgets.QLineEdit).text().endswith('/test')
        click('Back')


def test_empty_background_stays_click_through_in_both_modes(view):
    image = QtGui.QImage(10, 10, QtGui.QImage.Format.Format_ARGB32)
    for locked, alpha in ((False, 0), (True, 0)):
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


def test_phone_replacement_is_written_when_saved_board_is_saved_again(
        main_window, tmpdir):
    from beeref.fileio.sql import SQLiteIO
    from beeref.scene import BeeGraphicsScene
    view = main_window.view
    path = str(tmpdir / 'board.bee')
    original = QtGui.QImage(100, 100, QtGui.QImage.Format.Format_ARGB32)
    original.fill(QtCore.Qt.GlobalColor.blue)
    item = BeePixmapItem(original)
    view.scene.addItem(item)
    SQLiteIO(path, view.scene, create_new=True).write()

    replacement = QtGui.QImage(200, 100, QtGui.QImage.Format.Format_ARGB32)
    replacement.fill(QtCore.Qt.GlobalColor.red)
    main_window._receive_phone_image(replacement)
    SQLiteIO(path, view.scene).write()

    scenes = []  # Keep reloaded scenes alive while their items are used

    def reload():
        scenes.append(BeeGraphicsScene(QtGui.QUndoStack()))
        SQLiteIO(path, scenes[-1], readonly=True).read()
        scenes[-1].add_queued_items()
        images = [i for i in scenes[-1].items() if i.is_image]
        assert len(images) == 1
        return images[0]

    loaded = reload()
    assert loaded.pixmap().size() == QtCore.QSize(200, 100)
    assert loaded.crop == QtCore.QRectF(0, 0, 200, 100)
    assert loaded.pixmap().toImage().pixelColor(5, 5) == QtGui.QColor('red')

    # Undo restores the original image, which must be written again too.
    view.undo_stack.undo()
    SQLiteIO(path, view.scene).write()
    loaded = reload()
    assert loaded.pixmap().size() == QtCore.QSize(100, 100)
    assert loaded.pixmap().toImage().pixelColor(5, 5) == QtGui.QColor('blue')

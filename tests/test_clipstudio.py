from PyQt6 import QtCore, QtGui, QtWidgets
import json
import time
import pytest
from types import SimpleNamespace

from beeref.__main__ import BeeRefMainWindow
from beeref.clipstudio import ClipStudioPinController, LocalTransformBridge
from beeref.locked_overlay import LockedReferenceOverlay
from beeref.items import BeePixmapItem


@pytest.fixture(autouse=True)
def isolate_live_bridge(monkeypatch, tmp_path):
    # Never let the user's running Krita establish a test's lock baseline.
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))


def _state(zoom, center=(100, 100)):
    return {
        'zoom': zoom,
        'center': QtCore.QPointF(*center),
        'rotation': 0.0,
        'canvas_rect': (0.0, 0.0, 400.0, 300.0),
        'hwnd': None,
    }


def _screen(dpr, x=0, y=0):
    return SimpleNamespace(name=lambda: 'ultrawide',
                           devicePixelRatio=lambda: dpr,
                           geometry=lambda: QtCore.QRect(x, y, 4096, 1152))


def _image_item():
    return BeePixmapItem(
        QtGui.QImage(20, 20, QtGui.QImage.Format.Format_ARGB32))


document_transform = ClipStudioPinController._document_to_global_transform
local_pixels = ClipStudioPinController._bridge_state_in_local_pixels
MINIMAL_UPDATE = (
    QtWidgets.QGraphicsView.ViewportUpdateMode.MinimalViewportUpdate)


def test_krita_physical_pixels_follow_exactly_on_125_percent_desktop(qapp):
    # Reproduce the live bridge values. Krita DPR=1, BeeRef DPR=1.25.
    raw = dict(_state(2 / 3), protocol=3, canvas_device_pixel_ratio=1,
               canvas_rect=(73, 130, 4761, 1198), view_matrix_space='image',
               view_matrix=(2 / 3, 0, 0, 2 / 3, 2019, 172))
    screens = [_screen(1.25)]

    def normalize(state):
        return local_pixels(state, screens)

    transform = document_transform
    state = normalize(raw)
    assert state['canvas_rect'] == pytest.approx((58.4, 104, 3808.8, 958.4))
    assert raw['canvas_rect'] == (73, 130, 4761, 1198)
    image_point = QtCore.QPointF(542.25, 640.5)
    initial = transform(state).map(image_point)
    placement = QtGui.QTransform.fromTranslate(initial.x(), initial.y())
    overlay = LockedReferenceOverlay()
    item = _image_item()
    overlay.set_reference(item, placement, state, transform(state))
    for zoom, tx, ty in [(2 / 3, 2219, 272), (1 / 3, 2400, 300),
                         (.15, 2700.25, 430.75), (2 / 3, 2019, 172)]:
        moved = normalize(
            dict(raw, zoom=zoom, view_matrix=(zoom, 0, 0, zoom, tx, ty)))
        overlay.update_state(moved, transform(moved))
        actual = overlay._image_to_overlay.map(QtCore.QPointF(0, 0))
        # Independently compute where Krita draws this image pixel
        # physically, then convert to BeeRef logical pixels, including
        # integer window origin.
        physical_x = 73 + tx + zoom * image_point.x()
        physical_y = 130 + ty + zoom * image_point.y()
        assert actual.x() + overlay.x() == pytest.approx(
            physical_x / 1.25, abs=1e-7)
        assert actual.y() + overlay.y() == pytest.approx(
            physical_y / 1.25, abs=1e-7)
    overlay.close()


@pytest.mark.parametrize('origin', [(5120, 0), (-2560, -200)])
def test_dpi_conversion_preserves_monitor_origin(origin):
    x, y = origin
    state = dict(_state(1), canvas_device_pixel_ratio=1.5,
                 canvas_screen_name='ultrawide', canvas_screen_origin=origin,
                 canvas_rect=(x + 100, y + 200, 800, 600),
                 view_matrix=(1, 0, 0, 1, 10, 20))
    actual = local_pixels(state, [_screen(2, x, y)])
    assert actual['canvas_rect'] == (x + 75, y + 150, 600, 450)
    assert actual['view_matrix'] == (.75, 0, 0, .75, 7.5, 15)


def test_bridge_preserves_dpi_metadata(qapp, tmp_path):
    bridge = LocalTransformBridge()
    bridge.path = str(tmp_path / 'state.json')
    payload = dict(protocol=3, timestamp=time.time(), zoom=1, cursor=[0, 0],
                   canvas_device_pixel_ratio=1, canvas_screen_name='ultrawide',
                   canvas_screen_origin=[0, 0])
    tmp_path.joinpath('state.json').write_text(json.dumps(payload))
    received = []
    bridge.stateChanged.connect(received.append)
    bridge.poll()
    for key in ('canvas_device_pixel_ratio', 'canvas_screen_name',
                'canvas_screen_origin'):
        assert received[0][key] == payload[key]


def test_document_transform_keeps_canvas_center_fixed():
    before = ClipStudioPinController._document_to_global_transform(
        _state(1.0))
    after = ClipStudioPinController._document_to_global_transform(
        _state(2.0))
    delta = before.inverted()[0] * after

    center = delta.map(QtCore.QPointF(200.0, 150.0))
    corner = delta.map(QtCore.QPointF(100.0, 50.0))

    assert center == QtCore.QPointF(200.0, 150.0)
    assert corner == QtCore.QPointF(0.0, -50.0)


def test_document_transform_prefers_krita_absolute_view_matrix():
    state = _state(1.0)
    state['view_matrix'] = (2.0, 0.0, 0.0, 2.0, 10.0, 20.0)
    state['view_matrix_space'] = 'document'
    transform = ClipStudioPinController._document_to_global_transform(state)

    assert transform.map(QtCore.QPointF(0.0, 0.0)) == (
        QtCore.QPointF(10.0, 20.0))
    assert transform.map(QtCore.QPointF(3.0, 4.0)) == (
        QtCore.QPointF(16.0, 28.0))


def test_locked_proxy_does_not_mutate_source(qapp):
    main = BeeRefMainWindow(qapp)
    item = BeePixmapItem(
        QtGui.QImage(20, 20, QtGui.QImage.Format.Format_ARGB32))
    item.setPos(40, 50)
    item.setScale(1.25)
    main.view.scene.addItem(item)

    controller = main.pin_controller
    controller.item = item
    source_pos = QtCore.QPointF(item.pos())
    source_scale = item.scale()

    controller.set_locked_visuals(True)
    assert (main.view.viewportUpdateMode()
            == QtWidgets.QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
    controller._on_bridge_state(_state(1.0))
    controller._on_bridge_state(_state(2.0))

    assert item.pos() == source_pos
    assert item.scale() == source_scale
    assert controller.locked_overlay.isVisible()
    assert controller.locked_overlay.geometry() == QtCore.QRect(0, 0, 400, 300)

    controller.set_locked_visuals(False)
    assert main.view.viewportUpdateMode() == MINIMAL_UPDATE
    assert item.isVisible()
    assert item.pos() == source_pos
    assert item.scale() == source_scale
    main.close()


def test_locked_window_motion_is_not_scaled_by_existing_transform(
        qapp, monkeypatch):
    main = BeeRefMainWindow(qapp)
    controller = main.pin_controller
    view = main.view
    view.setTransform(QtGui.QTransform.fromScale(2.0, 2.0))
    item = _image_item()
    view.scene.addItem(item)
    controller.item = item
    state = _state(2.0)
    monkeypatch.setattr(controller.bridge, 'poll',
                        lambda **kw: controller._on_bridge_state(state))
    controller.set_locked_visuals(True)
    overlay = controller.locked_overlay
    initial = overlay._image_to_overlay.map(QtCore.QPointF(3, 4))
    for offset in (10, 20):
        state = dict(state, canvas_rect=(offset, 0, 400, 300))
        controller._on_bridge_state(state)
        assert overlay._image_to_overlay.map(QtCore.QPointF(3, 4)) == initial
        assert overlay.x() == offset
    main.close()


def test_absolute_transform_round_trip_has_no_accumulated_drift(qapp):
    overlay = LockedReferenceOverlay()
    item = _image_item()
    state = dict(_state(1), protocol=3, view_matrix_space='image',
                 view_matrix=(1, 0, 0, 1, 0, 0))
    placement = QtGui.QTransform(1.2, 0.1, -0.1, 1.2, 42.25, 58.75)
    overlay.set_reference(item, placement, state, document_transform(state))
    point = QtCore.QPointF(7, 9)
    for i in range(200):
        # Absolute changes include fractional pan, zoom, rotation and mirror.
        changed = dict(state, view_matrix=(0, 2, 2, 0, i / 7, -i / 9))
        overlay.update_state(changed, document_transform(changed))
        expected = document_transform(changed).map(placement.map(point))
        actual = overlay._image_to_overlay.map(point)
        assert actual.x() == pytest.approx(expected.x(), abs=1e-8)
        assert actual.y() == pytest.approx(expected.y(), abs=1e-8)
    overlay.update_state(state, document_transform(state))
    actual = overlay._image_to_overlay.map(point)
    assert actual.x() == pytest.approx(placement.map(point).x(), abs=1e-8)
    assert actual.y() == pytest.approx(placement.map(point).y(), abs=1e-8)
    overlay.close()


def test_modern_bridge_never_estimates_missing_matrix():
    assert document_transform(dict(_state(1), protocol=3)) is None


def test_overlay_skips_idle_redraws_but_repaints_after_motion_or_hide(
        qapp, monkeypatch):
    overlay = LockedReferenceOverlay()
    item = _image_item()
    state = _state(1)
    transform = document_transform
    overlay.set_reference(item, QtGui.QTransform(), state, transform(state))
    redraws, raises = [], []
    monkeypatch.setattr(overlay, 'update', lambda: redraws.append(True))
    monkeypatch.setattr(overlay, 'raise_', lambda: raises.append(True))
    for timestamp in range(100):
        heartbeat = dict(state, timestamp=timestamp)
        overlay.update_state(heartbeat, transform(heartbeat))
    assert redraws == raises == []
    moved = _state(1, center=(101, 100))
    overlay.update_state(moved, transform(moved))
    assert len(redraws) == len(raises) == 1
    overlay.hide()
    overlay.update_state(moved, transform(moved))
    assert overlay.isVisible()
    assert len(redraws) == len(raises) == 2
    overlay.clear_reference()
    assert overlay._source.isNull()
    assert overlay._image_to_overlay is None
    overlay.close()


def test_reference_snapshot_shares_pixels_and_detaches_on_write(qapp):
    pixmap = QtGui.QPixmap(20, 20)
    pixmap.fill(QtCore.Qt.GlobalColor.red)
    item = SimpleNamespace(grayscale=False, pixmap=lambda: pixmap)
    snapshot = LockedReferenceOverlay._source_pixmap(item)
    assert snapshot.cacheKey() == pixmap.cacheKey()
    pixmap.fill(QtCore.Qt.GlobalColor.blue)
    assert snapshot.toImage().pixelColor(0, 0) == QtGui.QColor('red')
    item.grayscale = True
    item._grayscale_pixmap = QtGui.QPixmap(20, 20)
    item._grayscale_pixmap.fill(QtCore.Qt.GlobalColor.gray)
    snapshot = LockedReferenceOverlay._source_pixmap(item)
    assert snapshot.cacheKey() == item._grayscale_pixmap.cacheKey()
    assert snapshot.toImage().pixelColor(0, 0) == QtGui.QColor(
        QtCore.Qt.GlobalColor.gray)


def test_bridge_replays_unchanged_state_on_restart_and_expires(
        qapp, tmp_path, monkeypatch):
    bridge = LocalTransformBridge()
    bridge.path = str(tmp_path / 'state.json')
    now = time.time()
    payload = dict(protocol=3, timestamp=now, zoom=1, cursor=[0, 0],
                   center=[0, 0])
    tmp_path.joinpath('state.json').write_text(json.dumps(payload))
    states, disconnects = [], []
    bridge.stateChanged.connect(states.append)
    bridge.disconnected.connect(lambda: disconnects.append(True))
    bridge.start()
    bridge.stop()
    bridge.start()
    bridge.stop()
    assert len(states) == 2
    monkeypatch.setattr('beeref.clipstudio.time.time', lambda: now + 10)
    bridge.poll()
    assert disconnects == [True]


def test_legacy_static_matrix_remains_supported(qapp, tmp_path, monkeypatch):
    bridge = LocalTransformBridge()
    bridge.path = str(tmp_path / 'state.json')
    tmp_path.joinpath('state.json').write_text(
        json.dumps({'matrix': [1, 0, 0, 1, 10, 20]}))
    matrices = []
    bridge.transformChanged.connect(matrices.append)
    monkeypatch.setattr('beeref.clipstudio.time.time',
                        lambda: time.time_ns() / 1e9 + 100)
    bridge.poll()
    assert len(matrices) == 1


def test_detach_restores_editing_repaint_mode(qapp):
    main = BeeRefMainWindow(qapp)
    item = _image_item()
    main.view.scene.addItem(item)
    controller = main.pin_controller
    controller.item = item

    controller.set_locked_visuals(True)
    assert (main.view.viewportUpdateMode()
            == QtWidgets.QGraphicsView.ViewportUpdateMode.FullViewportUpdate)

    controller.detach()
    assert main.view.viewportUpdateMode() == MINIMAL_UPDATE
    main.close()


@pytest.mark.parametrize('content', ['[1, 2]', '"text"', '{"zoom": "big"}',
                                     '{"protocol": 3, "timestamp": "x"}'])
def test_bridge_ignores_malformed_state(qapp, tmp_path, content):
    bridge = LocalTransformBridge()
    bridge.path = str(tmp_path / 'state.json')
    tmp_path.joinpath('state.json').write_text(content)
    states, disconnects = [], []
    bridge.stateChanged.connect(states.append)
    bridge.disconnected.connect(lambda: disconnects.append(True))
    bridge.poll()
    bridge.poll()
    assert states == []
    assert disconnects == [True]

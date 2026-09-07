"""Exercise the plugin without launching or controlling Krita."""
import importlib.util
import sys
import types
import os
import shutil
import subprocess
from importlib.machinery import PathFinder
from pathlib import Path

import pytest
from PyQt6 import QtCore, QtGui


@pytest.fixture
def plugin(monkeypatch):
    krita = types.ModuleType('krita')
    krita.Extension = QtCore.QObject
    krita.Krita = types.SimpleNamespace(instance=lambda: None)
    monkeypatch.setitem(sys.modules, 'krita', krita)
    path = Path(__file__).parents[1] / 'krita_plugin/beeref_bridge/beeref_bridge.py'
    spec = importlib.util.spec_from_file_location('bridge_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_plugin_uses_image_pixels_at_nonstandard_document_resolution(plugin):
    # At 144 DPI one image pixel is half a document unit. The desired
    # mapping here is 25% zoom, then a 90-degree rotation and translation.
    view = types.SimpleNamespace(
        flakeToImageTransform=lambda: QtGui.QTransform.fromScale(4, 4),
        flakeToDocumentTransform=lambda: QtGui.QTransform.fromScale(2, 2),
        flakeToCanvasTransform=lambda: QtGui.QTransform(0, 1, -1, 0, 13.5, 27.25))
    assert plugin.BeeRefBridgeExtension._view_matrix(view) == pytest.approx(
        (0, .25, -.25, 0, 13.5, 27.25))


def test_plugin_heartbeat_and_high_zoom(plugin, qapp, monkeypatch):
    bridge = plugin.BeeRefBridgeExtension(None)
    canvas = types.SimpleNamespace(zoomLevel=lambda: 16,
                                   preferredCenter=lambda: QtCore.QPointF(10, 20),
                                   rotation=lambda: 0)
    view = types.SimpleNamespace(canvas=lambda: canvas)
    window = types.SimpleNamespace(activeView=lambda: view, qwindow=lambda: None)
    bridge.app = types.SimpleNamespace(activeWindow=lambda: window)
    monkeypatch.setattr(bridge, '_canvas_widget_for', lambda *args: None)
    monkeypatch.setattr(bridge, '_widget_global_rect', lambda *args: (0, 0, 400, 300))
    monkeypatch.setattr(bridge, '_view_matrix', lambda *args: (16, 0, 0, 16, 0, 0))
    published = []
    monkeypatch.setattr(bridge, '_write_json', published.append)
    monkeypatch.setattr(plugin.time, 'time', lambda: 100)
    bridge.publish()
    bridge.publish()
    assert len(published) == 1
    assert published[0]['zoom'] == 16
    assert published[0]['view_matrix_space'] == 'image'
    assert published[0]['bridge_build'] == 'image-transform-3.2'
    assert published[0]['bridge_source'] == str(Path(plugin.__file__).resolve())
    monkeypatch.setattr(plugin.time, 'time', lambda: 101)
    bridge.publish()
    assert len(published) == 2
    assert published[-1]['timestamp'] == 101


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows installer')
def test_installer_removes_shadowing_package_and_is_repeatable(tmp_path):
    roaming = tmp_path / 'Roaming'
    local = tmp_path / 'Local'
    package = roaming / 'krita/pykrita/beeref_bridge'
    nested = package / 'beeref_bridge'
    nested.mkdir(parents=True)
    (nested / '__init__.py').write_text('# old package')
    (package / 'beeref_bridge.py').write_text('# new file that is shadowed')
    assert PathFinder.find_spec('beeref_bridge.beeref_bridge', [str(package)]).origin == str(nested / '__init__.py')
    script = Path(__file__).parents[1] / 'krita_plugin/install-bridge.ps1'
    env = dict(os.environ, APPDATA=str(roaming), LOCALAPPDATA=str(local))
    for _ in range(2):
        subprocess.run([shutil.which('powershell'), '-NoProfile', '-ExecutionPolicy',
                        'Bypass', '-File', str(script)], env=env, check=True,
                       capture_output=True, text=True)
        assert not nested.exists()
        assert PathFinder.find_spec('beeref_bridge.beeref_bridge', [str(package)]).origin == str(package / 'beeref_bridge.py')
        source = script.parent / 'beeref_bridge/beeref_bridge.py'
        assert (package / 'beeref_bridge.py').read_bytes() == source.read_bytes()
    backups = list((local / 'BeeRef/bridge-backups').iterdir())
    assert len(backups) == 2
    assert any((backup / 'beeref_bridge/__init__.py').exists() for backup in backups)

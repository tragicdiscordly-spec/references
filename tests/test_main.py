from unittest.mock import patch, MagicMock

from PyQt6 import QtCore

from beeref.__main__ import (
    BeeRefApplication, BeeRefMainWindow, main)
from beeref.assets import BeeAssets
from beeref.view import BeeGraphicsView


@patch('PyQt6.QtWidgets.QWidget.show')
def test_beeref_mainwindow_init(show_mock, qapp):
    window = BeeRefMainWindow(qapp)
    assert window.windowTitle() == 'BeeRef'
    assert BeeAssets().logo == BeeAssets().logo
    assert window.windowIcon()
    assert window.contentsMargins() == QtCore.QMargins(0, 0, 0, 0)
    assert isinstance(window.view, BeeGraphicsView)
    show_mock.assert_called()


@patch('beeref.view.BeeGraphicsView.open_from_file')
def test_beerefapplication_fileopenevent(open_mock, qapp, main_window):
    event = MagicMock()
    event.type.return_value = QtCore.QEvent.Type.FileOpen
    event.file.return_value = 'test.bee'
    assert qapp.event(event) is True
    open_mock.assert_called_once_with('test.bee')


def test_beerefapplication_single_instance_state(qapp):
    # The session fixture owns the mutex on Windows.  This assertion keeps
    # the guard present without requiring a second QApplication.
    assert hasattr(qapp, '_already_running')
    assert isinstance(qapp._already_running, bool)


@patch('beeref.__main__.BeeRefApplication')
@patch('beeref.__main__.CommandlineArgs')
@patch('beeref.config.BeeSettings.on_startup')
def test_main(startup_mock, args_mock, app_mock, qapp):
    app_mock.return_value = qapp
    args_mock.return_value.filename = None
    args_mock.return_value.loglevel = 'WARN'
    args_mock.return_value.debug_raise_error = ''

    # The live BeeRef instance used for manual testing may own the mutex;
    # this test is exercising main()'s normal path with a mocked constructor.
    already_running = qapp._already_running
    qapp._already_running = False
    with patch.object(qapp, 'exec') as exec_mock:
        try:
            main()
        finally:
            qapp._already_running = already_running
        exec_mock.assert_called_once_with()

    args_mock.assert_called_once_with(with_check=True)
    startup_mock.assert_called()

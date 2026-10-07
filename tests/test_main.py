from unittest.mock import patch, MagicMock

from PyQt6 import QtCore, QtGui, QtWidgets

from beeref.__main__ import BeeRefMainWindow, PrivatePopupFilter, main
from beeref.assets import BeeAssets
from beeref.view import BeeGraphicsView


def test_popup_capture_filter_covers_menus_submenus_and_dialogs(qapp):
    guard = PrivatePopupFilter(qapp)
    menu = QtWidgets.QMenu()
    submenu = menu.addMenu('Images')
    dialog = QtWidgets.QDialog()
    child = QtWidgets.QLabel('child', dialog)
    with patch('beeref.__main__.platform.system', return_value='Windows'), \
            patch.object(guard, 'protect') as protect:
        for widget in (menu, submenu, dialog):
            event = QtCore.QEvent(QtCore.QEvent.Type.Show)
            assert guard.eventFilter(widget, event) is False
            protect.assert_called_with(widget)
        assert protect.call_count == 3
        guard.eventFilter(child, QtCore.QEvent(QtCore.QEvent.Type.Show))
        assert protect.call_count == 3
        guard.eventFilter(menu, QtCore.QEvent(QtCore.QEvent.Type.Paint))
        guard.eventFilter(menu, QtCore.QEvent(QtCore.QEvent.Type.ShowToParent))
        assert protect.call_count == 5
    menu.close()
    dialog.close()


def test_popup_capture_affinity_preserves_input(qapp):
    widget = MagicMock()
    widget.winId.return_value = 123
    with patch('beeref.__main__.QtGui.QGuiApplication.platformName',
               return_value='windows'), \
            patch('beeref.__main__.get_display_affinity', return_value=0), \
            patch('beeref.__main__.get_window_long', return_value=0,
                  create=True), \
            patch('beeref.__main__.set_window_long',
                  create=True) as set_style, \
            patch('beeref.__main__.user32', create=True) as native:
        PrivatePopupFilter.protect(widget)
        assert set_style.call_args.args[2] == 0x00080000
        assert native.SetWindowDisplayAffinity.call_args.args[1] == 0x11
        native.SetLayeredWindowAttributes.assert_called_once()


def test_popup_reprotects_after_qt_resets_affinity(qapp):
    widget = MagicMock()
    widget.winId.return_value = 123
    with patch('beeref.__main__.QtGui.QGuiApplication.platformName',
               return_value='windows'), \
            patch('beeref.__main__.get_display_affinity',
                  side_effect=[0x11, 0, 0x11]), \
            patch('beeref.__main__.get_window_long', return_value=0x80000,
                  create=True), \
            patch('beeref.__main__.user32', create=True) as native:
        PrivatePopupFilter.protect(widget)
        native.SetWindowDisplayAffinity.assert_not_called()
        PrivatePopupFilter.protect(widget)
        native.SetWindowDisplayAffinity.assert_called_once()


def test_reference_menu_keeps_only_requested_image_settings(main_window):
    menu = main_window.view.context_menu
    submenus = {a.text(): a.menu() for a in menu.actions() if a.menu()}
    assert set(submenus) == {'&File', '&Edit', '&Images'}
    from beeref.actions.actions import actions
    assert submenus['&Images'].actions() == [
        actions['change_opacity'].qaction, actions['grayscale'].qaction]


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


def test_edit_surface_leaves_out_docked_taskbar():
    from beeref.__main__ import edit_surface_rect
    monitor = QtCore.QRect(0, 0, 4096, 1152)
    available = QtCore.QRect(0, 0, 4096, 1114)
    assert edit_surface_rect([monitor], [available]) == available


def test_edit_surface_never_covers_a_whole_monitor():
    from beeref.__main__ import edit_surface_rect
    layouts = [
        # Auto-hiding taskbar: the available area is the whole monitor.
        ([QtCore.QRect(0, 0, 4096, 1152)],
         [QtCore.QRect(0, 0, 4096, 1152)]),
        # Taskbar on the left monitor only; the bounding box covers both.
        ([QtCore.QRect(0, 0, 1920, 1080), QtCore.QRect(1920, 0, 1920, 1080)],
         [QtCore.QRect(0, 0, 1920, 1040), QtCore.QRect(1920, 0, 1920, 1080)]),
        # Monitors of different heights aligned at the top.
        ([QtCore.QRect(0, 0, 2560, 1440), QtCore.QRect(2560, 0, 1920, 1080)],
         [QtCore.QRect(0, 0, 2560, 1440), QtCore.QRect(2560, 0, 1920, 1080)]),
    ]
    for geometries, available in layouts:
        rect = edit_surface_rect(geometries, available)
        assert not any(rect.contains(geometry) for geometry in geometries)
        assert all(rect.intersects(area) for area in available)


def test_main_window_does_not_cover_whole_screen(main_window):
    for screen in QtGui.QGuiApplication.screens():
        assert not main_window.geometry().contains(screen.geometry())

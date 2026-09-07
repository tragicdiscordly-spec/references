"""Controls painted inside the capture-excluded editor, never a popup HWND."""
from PyQt6 import QtCore, QtWidgets
from beeref import commands


class ReferenceControls(QtWidgets.QFrame):
    def __init__(self, view):
        super().__init__(view.viewport())
        self.view = view
        self.setObjectName('referenceControls')
        self.setStyleSheet('''
            QFrame#referenceControls { background: #202225; border: 1px solid #555; }
            QLabel, QCheckBox { color: white; background: #202225; }
            QPushButton { color: white; background: #303339; padding: 8px; border: 0; text-align: left; }
            QPushButton:hover { background: #454a54; }
            QLineEdit { background: #303339; color: white; padding: 6px; }
        ''')
        self.layout = QtWidgets.QVBoxLayout(self)
        self.setFixedWidth(350)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.hide()

    def clear(self):
        while self.layout.count():
            widget = self.layout.takeAt(0).widget()
            if widget:
                widget.hide()
                widget.deleteLater()

    def button(self, text, callback, enabled=True):
        button = QtWidgets.QPushButton(text, self)
        button.setEnabled(enabled)
        button.clicked.connect(callback)
        self.layout.addWidget(button)
        return button

    def open(self, point=None, menu=None):
        self.clear()
        self.button('Close ×', self.hide)
        menu = menu or self.view.context_menu
        if menu is not self.view.context_menu:
            self.button('← Back', lambda: self.open())
        for action in menu.actions():
            if action.isSeparator():
                continue
            if action.menu():
                self.button(action.text().replace('&', '') + '  ›',
                            lambda checked=False, m=action.menu(): self.open(menu=m))
            else:
                label = action.text().replace('&', '')
                if action.isCheckable():
                    label = ('✓ ' if action.isChecked() else '') + label
                def trigger(checked=False, a=action):
                    self.hide()
                    a.trigger()
                self.button(label, trigger, action.isEnabled())
        if menu is self.view.context_menu:
            self.button('Send image from phone…', self.phone_page)
        self.present(point)

    def present(self, point=None):
        self.adjustSize()
        point = self.pos() if point is None else point
        bounds = self.parentWidget().rect()
        self.move(max(0, min(point.x(), bounds.width() - self.width())),
                  max(0, min(point.y(), bounds.height() - self.height())))
        self.show()
        self.raise_()
        self.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key.Key_Escape:
            self.hide()
            event.accept()
            return
        super().keyPressEvent(event)

    def opacity_page(self):
        self.clear()
        self.button('← Back', lambda: self.open())
        images = [i for i in self.view.scene.selectedItems(user_only=True) if i.is_image]
        self.layout.addWidget(QtWidgets.QLabel('Opacity', self))
        slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal, self)
        slider.setRange(0, 100)
        slider.setValue(round(images[0].opacity() * 100) if images else 100)
        slider.setEnabled(bool(images))
        self.layout.addWidget(slider)
        self.button('Apply', lambda: self.apply_opacity(images, slider.value()))
        self.present()

    def apply_opacity(self, images, value):
        self.view.undo_stack.push(commands.ChangeOpacity(images, value / 100))
        self.hide()

    def phone_page(self):
        self.clear()
        self.button('← Back', lambda: self.open())
        try:
            receiver = self.view.parent.start_phone_receiver()
            message = 'Open this private link on your phone (same Wi-Fi):'
            url = receiver.url
        except OSError as error:
            message, url = 'Could not start phone receiver: ' + str(error), ''
        label = QtWidgets.QLabel(message, self)
        label.setWordWrap(True)
        self.layout.addWidget(label)
        field = QtWidgets.QLineEdit(url, self)
        field.setReadOnly(True)
        self.layout.addWidget(field)
        self.button('Copy private link', lambda: QtWidgets.QApplication.clipboard().setText(url))
        self.button('Stop phone receiving', self.view.parent.stop_phone_receiver)
        self.present()

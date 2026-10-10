"""
edit/color_picker.py
--------------------
A continuous color picker: a hue/saturation rectangle with a circle
pointer, and a vertical darkness slider on its left, plus a hex field and
an old-vs-new preview. Edit Attributes uses it to choose each trace's color.

Built from plain widgets rather than QColorDialog so the layout is the one
the app wants (darkness slider on the left, the color field darkening live
as the slider moves) and looks identical on every platform.

  pick_color(parent, initial, title)  -> QColor, or None if cancelled
"""

import numpy as np
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QFrame,
)

_MAX_HUE = 0.999  # hue 1.0 is red again; keep the pointer's right edge distinct from its left
_BAR_PAD = 4      # room above/below the darkness slider's track so its handle never clips


def _hue_sat_field(width, height):
    """(height, width, 3) float array in 0..1 for the hue/saturation
    rectangle at full brightness: hue runs left to right, saturation runs
    from full at the top to none (white) at the bottom. Vectorized HSV->RGB
    so a resize costs a few milliseconds rather than a per-pixel Python loop."""
    hue = (np.arange(width) / max(width, 1))[None, :]
    sat = (1.0 - np.arange(height) / max(height - 1, 1))[:, None]
    channels = []
    for n in (5, 3, 1):  # the R, G, B offsets in the standard HSV->RGB formula
        k = (n + hue * 6.0) % 6.0
        channels.append(1.0 - sat * np.clip(np.minimum(k, 4.0 - k), 0.0, 1.0))
    return np.stack(channels, axis=-1)


class _HueSatPlane(QWidget):
    """The rectangle: click or drag anywhere to move the circle pointer."""

    changed = pyqtSignal(float, float)  # hue, saturation — both 0..1

    def __init__(self):
        super().__init__()
        self.setMinimumSize(300, 200)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._hue = self._sat = 0.0
        self._value = 1.0
        self._field = None      # full-brightness field for the current size
        self._image = None      # that field scaled to the current darkness
        self._image_key = None

    def set_state(self, hue, sat, value):
        self._hue, self._sat, self._value = hue, sat, value
        self.update()

    def _current_image(self):
        w, h = max(self.width(), 1), max(self.height(), 1)
        if self._field is None or self._field.shape[:2] != (h, w):
            self._field = _hue_sat_field(w, h)
            self._image_key = None
        key = (w, h, round(self._value * 255))
        if key != self._image_key:
            rgb = (self._field * (self._value * 255.0) + 0.5).astype(np.uint8)
            # The whole field darkens with the slider, so what's under the
            # pointer is always the color that will actually be picked.
            self._image = QImage(rgb.tobytes(), w, h, w * 3, QImage.Format.Format_RGB888).copy()
            self._image_key = key
        return self._image

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.drawImage(0, 0, self._current_image())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        center = QPointF(self._hue * self.width(), (1.0 - self._sat) * (self.height() - 1))
        # A dark ring under a white one: readable on every color, light or dark.
        painter.setPen(QPen(QColor(0, 0, 0), 3.5))
        painter.drawEllipse(center, 8, 8)
        painter.setPen(QPen(QColor(255, 255, 255), 1.5))
        painter.drawEllipse(center, 8, 8)

    def _pick(self, pos):
        hue = min(max(pos.x() / max(self.width(), 1), 0.0), _MAX_HUE)
        sat = 1.0 - min(max(pos.y() / max(self.height() - 1, 1), 0.0), 1.0)
        self.changed.emit(hue, sat)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pick(event.position())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._pick(event.position())


class _DarknessBar(QWidget):
    """The vertical slider: bright at the top, black at the bottom, tinted
    with whatever hue/saturation is currently picked."""

    changed = pyqtSignal(float)  # value (brightness) 0..1

    def __init__(self):
        super().__init__()
        self.setFixedWidth(30)
        self.setMinimumHeight(200)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hue = self._sat = 0.0
        self._value = 1.0

    def set_state(self, hue, sat, value):
        self._hue, self._sat, self._value = hue, sat, value
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        gradient = QLinearGradient(0, 0, 0, h)
        gradient.setColorAt(0.0, QColor.fromHsvF(self._hue, self._sat, 1.0))
        gradient.setColorAt(1.0, QColor(0, 0, 0))
        painter.setPen(QPen(QColor(120, 120, 120), 1))
        painter.setBrush(gradient)
        painter.drawRect(QRectF(6, 0.5, w - 12, h - 1))

        y = _BAR_PAD + (1.0 - self._value) * (h - 2 * _BAR_PAD)
        painter.setPen(QPen(QColor(40, 40, 40), 1))
        painter.setBrush(QColor(255, 255, 255))
        painter.drawRoundedRect(QRectF(1.5, y - 4, w - 3, 8), 3, 3)

    def _pick(self, pos):
        span = max(self.height() - 2 * _BAR_PAD, 1)
        self.changed.emit(1.0 - min(max((pos.y() - _BAR_PAD) / span, 0.0), 1.0))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pick(event.position())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._pick(event.position())


class ColorPicker(QWidget):
    """Darkness slider + hue/saturation rectangle, holding the color as
    hue/saturation/value floats (not a QColor) so dragging never loses
    precision — or the hue, when the color passes through black or grey."""

    colorChanged = pyqtSignal(QColor)

    def __init__(self, color):
        super().__init__()
        self._hue = self._sat = 0.0
        self._value = 1.0
        self.bar = _DarknessBar()
        self.plane = _HueSatPlane()

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(self.bar)          # darkness slider on the left
        row.addWidget(self.plane, 1)

        self.plane.changed.connect(self._on_plane)
        self.bar.changed.connect(self._on_bar)
        self.set_color(color)

    def color(self):
        return QColor.fromHsvF(self._hue, self._sat, self._value)

    def set_color(self, color):
        hue = color.hsvHueF()
        if hue >= 0:  # -1 for greys/black/white: keep whatever hue was there
            self._hue = min(hue, _MAX_HUE)
        self._sat = color.hsvSaturationF()
        self._value = color.valueF()
        self._sync()

    def _sync(self):
        self.plane.set_state(self._hue, self._sat, self._value)
        self.bar.set_state(self._hue, self._sat, self._value)

    def _on_plane(self, hue, sat):
        self._hue, self._sat = hue, sat
        self._sync()
        self.colorChanged.emit(self.color())

    def _on_bar(self, value):
        self._value = value
        self._sync()
        self.colorChanged.emit(self.color())


def _swatch():
    frame = QFrame()
    frame.setFixedSize(40, 22)
    return frame


def _paint_swatch(frame, color):
    frame.setStyleSheet(f"background-color: {color.name()}; border: 1px solid #666;")


class ColorPickerDialog(QDialog):
    def __init__(self, parent, initial, title="Pick a Color"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self._initial = QColor(initial)

        layout = QVBoxLayout(self)
        self.picker = ColorPicker(self._initial)
        layout.addWidget(self.picker, 1)

        row = QHBoxLayout()
        row.addWidget(QLabel("Hex:"))
        self.hex_edit = QLineEdit()
        self.hex_edit.setMaxLength(7)
        self.hex_edit.setFixedWidth(80)
        self.hex_edit.editingFinished.connect(self._commit_hex)
        row.addWidget(self.hex_edit)
        row.addStretch(1)
        row.addWidget(QLabel("Old"))
        old_swatch = _swatch()
        _paint_swatch(old_swatch, self._initial)
        row.addWidget(old_swatch)
        row.addWidget(QLabel("New"))
        self.new_swatch = _swatch()
        row.addWidget(self.new_swatch)
        layout.addLayout(row)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        ok_btn = QPushButton("OK")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(ok_btn)
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)

        self.picker.colorChanged.connect(self._show_color)
        self._show_color(self._initial)

    def _show_color(self, color):
        self.hex_edit.setText(color.name())
        _paint_swatch(self.new_swatch, color)

    def _commit_hex(self):
        """Take whatever's typed in the hex field ("#3a7bd5", "3a7bd5", or a
        color name) — or put the current color back if it doesn't parse."""
        text = self.hex_edit.text().strip()
        if len(text) in (3, 6) and all(c in "0123456789abcdefABCDEF" for c in text):
            text = "#" + text
        color = QColor(text)
        if color.isValid():
            self.picker.set_color(color)
            self._show_color(color)
        else:
            self._show_color(self.picker.color())

    def accept(self):
        self._commit_hex()  # Enter in the hex field can land here before editingFinished
        super().accept()


def pick_color(parent, initial, title="Pick a Color"):
    """Modal picker. Returns the chosen QColor, or None if cancelled."""
    dialog = ColorPickerDialog(parent, initial, title)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.picker.color()
    return None

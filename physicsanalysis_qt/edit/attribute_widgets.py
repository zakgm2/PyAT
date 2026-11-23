"""
edit/attribute_widgets.py
-------------------------
The pieces the two Edit Graph Attributes dialogs have in common — the recording's plot (edit/attributes.py) and the figure of an analysis window
(edit/figure_attributes.py): a line's colour (a swatch that opens the picker, and Reset) and the Points section (a slider and a box for the size of the
dot on every sample of every line).
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QPushButton, QSlider, QSpinBox, QVBoxLayout

from .color_picker import pick_color


def gray_note(text):
    """A wrapped line of explanation in grey, under a section."""
    note = QLabel(text)
    note.setStyleSheet("color: gray;")
    note.setWordWrap(True)
    return note


class ColorRow:
    """One line's colour state in a Line Colors section: a swatch that opens the picker, and a Reset button. `orig` is what the colour is filed under
    (a trace's raw name, a series' key) and `name` is what to call it in the UI."""

    def __init__(self, dialog, orig, name, default_color, override):
        self.dialog = dialog
        self.orig = orig
        self.name = name
        self.default_color = QColor(default_color).name()
        self.override = override  # "#rrggbb" or None (= the color it is drawn in without an override)

        self.color_btn = QPushButton()
        self.color_btn.setFixedSize(60, 22)
        self.color_btn.setToolTip("Choose this line's color")
        self.color_btn.clicked.connect(self._pick)
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setToolTip("Back to the default color")
        self.reset_btn.clicked.connect(self._reset)
        self._refresh()

    @property
    def color(self):
        return self.override or self.default_color

    def _refresh(self):
        self.color_btn.setStyleSheet(
            f"background-color: {self.color}; border: 1px solid #666;")
        self.reset_btn.setEnabled(self.override is not None)

    def _pick(self):
        picked = pick_color(self.dialog, QColor(self.color), f"Line Color — {self.name}")
        if picked is not None:
            # Picking the default color back is the same as having no override.
            self.override = None if picked.name() == self.default_color else picked.name()
            self._refresh()

    def _reset(self):
        self.override = None
        self._refresh()


class PointSizeBox(QGroupBox):
    """The "Points" section: a slider (and a box) for the size, in points, of the dot drawn on every sample of every line; 0 draws none. "As drawn" is
    what the lines have without a choice here (`default`). `touched` says whether the size was moved: only a size that was is carried to Apply, so one
    that was left alone stays as it was."""

    def __init__(self, top, default, current, note, enabled=True):
        super().__init__("Points")
        self.default = float(default)
        self.touched = False
        start = self.default if current is None else float(current)
        outer = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("Point size:"))
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, top)
        self.slider.setMinimumWidth(200)
        row.addWidget(self.slider, stretch=1)
        self.spin = QSpinBox()
        self.spin.setRange(0, top)
        self.spin.setSuffix(" pt")
        self.spin.setKeyboardTracking(False)
        row.addWidget(self.spin)
        self.btn_reset = QPushButton("As drawn")
        self.btn_reset.setToolTip("Back to the points the lines have without a choice here.")
        row.addWidget(self.btn_reset)
        outer.addLayout(row)
        outer.addWidget(gray_note(note))
        for widget in (self.slider, self.spin):
            widget.blockSignals(True)
            widget.setValue(int(round(start)))
            widget.blockSignals(False)
        self.slider.valueChanged.connect(self._changed)
        self.spin.valueChanged.connect(self._changed)
        self.btn_reset.clicked.connect(lambda: self._changed(int(round(self.default))))
        self.setEnabled(enabled)

    def _changed(self, value):
        """The slider or the box moved (or As drawn was pressed): the other follows, and the size is to be applied."""
        self.touched = True
        for widget in (self.slider, self.spin):
            if widget.value() != value:
                widget.blockSignals(True)
                widget.setValue(value)
                widget.blockSignals(False)

    def chosen(self):
        """The size asked for, or None if it was not touched."""
        return self.spin.value() if self.touched else None

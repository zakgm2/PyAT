"""
export/figure_export.py
-----------------------
Exporting a figure for a manuscript, one way for every figure the app shows (an analysis window's plot, the group
analysis figures, the PT2 image, the main plot's Export View):

    export_figure(ctx, fig, "EventPETH", tracking_info, provenance=...)

opens the Export Figure dialog and writes what it asks for:

  - PNG or TIFF at a resolution you pick (300 dpi by default, up to 1200), or PDF / SVG as vector files. In a vector
    file the text stays text (editable in Illustrator or Inkscape, set in the fonts it was drawn with) unless you
    turn that off; dates and random ids are left out of PDF/SVG so exporting the same figure twice gives the same file.
  - The size: as big as the figure is on screen (trimmed to its content), or, with "Set the size", a width and a height
    (sliders, in inches) the figure is laid out again to fit; a PNG then has exactly width x dpi by height x dpi pixels.
    The size is not remembered: it belongs to the figure. The preview follows the sliders as they are dragged.
  - Titles, axis labels, colour-bar labels and legend entries are fields in the dialog: change them and the export
    carries the new words (and so does the data CSV — a renamed legend entry renames the series). The figure on
    screen is not touched. (figures/labels.py.) What was changed in the window with Edit Attributes (figures/restyle.py) is already on the
    figure, so it is exported as it is shown, and the provenance record lists it.
  - The point size: with a slider (and a box) the scatter points and line markers are drawn larger or smaller than they are on screen, as a
    percentage of their size; lines, bars and text are not changed. Like the size, it is not remembered: it belongs to the figure.
  - A CSV of the data behind each plot beside the figure (figures/data.py), unless you untick it: every plotted
    point, band, bar and heatmap cell, as drawn.
  - A live preview, with the pixel/inch size the file will have.
  - **Copy to Clipboard**: the figure as a PNG image on the clipboard, at the resolution, size, point size and words set here, to paste into a slide
    or a document — no file is written (so there is no data CSV or record either), and the dialog closes.
  - The provenance record every export gets (context.export_file), which also lists the data CSV and says what
    was edited.

The last choices are remembered in settings["figure_export"]. The part that writes a file (render_figure) is
figures/render.py, usable without any window.
"""

import datetime
import io
import os
import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from .. import figures
from .. import __version__
from ..app import errorlog
from ..app.toasts import show_error, show_window_toast
from .. import context as _context            # not `from .context import save_settings`: tests replace it on the module
from ..app.window_fit import fit_dialog_to_content, scroll_body

SOFTWARE = f"PyAT {__version__}"                  # named in the metadata of every file it writes
DEFAULTS = {"format": "png", "dpi": 300, "transparent": False, "editable_text": True, "data_csv": True}
MIN_DPI, MAX_DPI = 72, 1200
PREVIEW_DPI = 90
PREVIEW_MAX = (560, 340)                    # pixels the preview may take in the dialog
POINT_PERCENT_RANGE = (10, 500)            # the point size, as a percentage of the size drawn (100: as drawn)
EDIT_POINTS_NOTE = ("This figure has no points to resize. Edit Attributes can draw a point on every sample of the lines "
                    "(the Points section); then they can be made larger or smaller here too.")      # what the Points section says of a figure Edit Attributes can edit
SIZE_STEPS_PER_INCH = 10                    # the sliders move in tenths of an inch (the boxes beside them take hundredths)
TYPING_PREVIEW_MS = 250                     # the preview waits this long after the last keystroke in a title or label
LIVE_PREVIEW_MS = 40                        # the shortest wait between two drawings of the preview while a slider moves
LIVE_PREVIEW_MAX_MS = 600                   # ... and the longest (a very long recording takes a while to draw)


def remembered_settings(ctx):
    """The dialog's starting point: DEFAULTS with whatever valid choices were saved last time."""
    saved = ctx.settings.get("figure_export")
    if not isinstance(saved, dict):                          # a hand-edited settings file can hold anything
        saved = {}
    out = dict(DEFAULTS)
    if saved.get("format") in figures.FORMATS:
        out["format"] = saved["format"]
    if isinstance(saved.get("dpi"), int) and MIN_DPI <= saved["dpi"] <= MAX_DPI:
        out["dpi"] = saved["dpi"]
    for key in ("transparent", "editable_text", "data_csv"):
        if isinstance(saved.get(key), bool):
            out[key] = saved[key]
    return out


class FigureExportDialog(QDialog):
    """Format, resolution, size, what to include, the editable words, and a preview of the result."""

    def __init__(self, ctx, fig, title="Export Figure", parent=None, has_data=True, no_points_note=None):
        super().__init__(parent if parent is not None else ctx.win)
        self.ctx = ctx
        self.fig = fig
        self.no_points_note = no_points_note or "This figure has no points to resize."
        self.setWindowTitle(title)
        outer, layout, body = scroll_body(self)

        self.preview = QLabel("Preview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(*PREVIEW_MAX)
        self.preview.setStyleSheet("background: white; border: 1px solid #888;")
        layout.addWidget(self.preview)
        self.size_label = QLabel("")
        self.size_label.setStyleSheet("color: gray;")
        self.size_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.size_label)

        start = remembered_settings(ctx)
        box = QGroupBox("File")
        form = QFormLayout(box)
        self.format_combo = QComboBox()
        for key, (label, _ext, _filter, _mpl) in figures.FORMATS.items():
            self.format_combo.addItem(label, key)
        self.format_combo.setCurrentIndex(self.format_combo.findData(start["format"]))
        form.addRow("Format:", self.format_combo)
        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(MIN_DPI, MAX_DPI)
        self.dpi_spin.setSuffix(" dpi")
        self.dpi_spin.setValue(start["dpi"])
        self.dpi_spin.setToolTip("Resolution of PNG/TIFF files — and of any heatmap image inside a PDF/SVG. "
                                 "Journals usually ask for 300 or more.")
        form.addRow("Resolution:", self.dpi_spin)
        self.cb_editable = QCheckBox("Keep text as editable text (PDF / SVG)")
        self.cb_editable.setToolTip("On: the words stay words, so Illustrator or Inkscape can edit them — in the font "
                                    "they were drawn with. Off: the letters become outlines and look the same everywhere.")
        self.cb_editable.setChecked(start["editable_text"])
        form.addRow(self.cb_editable)
        self.cb_transparent = QCheckBox("Transparent background")
        self.cb_transparent.setChecked(start["transparent"])
        form.addRow(self.cb_transparent)
        self.cb_data = QCheckBox("Also save the plotted data as CSV")
        self.cb_data.setToolTip("A table beside the figure with every point, band, bar and heatmap cell that is drawn.")
        self.cb_data.setChecked(start["data_csv"])
        self.cb_data.setVisible(has_data)
        form.addRow(self.cb_data)
        layout.addWidget(box)

        layout.addWidget(self._size_box(fig))
        layout.addWidget(self._points_box(fig))

        self.items = figures.text_items(fig)
        self.fields = {}
        if self.items:
            words = QGroupBox("Titles and labels")
            words_form = QFormLayout(words)
            for item in self.items:
                field = QLineEdit(item.text)
                field.setMinimumWidth(300)
                words_form.addRow(item.caption + ":", field)
                field.textChanged.connect(self._schedule_preview)
                self.fields[item] = field
            note = QLabel("Changes go into the exported file only — the figure on screen stays as it is.")
            note.setStyleSheet("color: gray;")
            words_form.addRow(note)
            layout.addWidget(words)

        buttons = QDialogButtonBox()
        self.export_button = buttons.addButton("Export", QDialogButtonBox.ButtonRole.AcceptRole)
        self.export_button.setDefault(True)
        self.copy_button = buttons.addButton("Copy to Clipboard", QDialogButtonBox.ButtonRole.ActionRole)
        self.copy_button.setToolTip("Put the figure on the clipboard as an image (PNG, at the resolution, size and words set here) instead of writing a file.")
        self.copy_button.clicked.connect(self.copy_to_clipboard)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._render_preview)
        self._preview_size_in = None
        self._last_draw_ms = 0.0                                   # how long the last drawing of the preview took
        for signal in (self.format_combo.currentIndexChanged, self.dpi_spin.valueChanged, self.cb_editable.toggled):
            signal.connect(self._on_option_changed)
        self.cb_transparent.toggled.connect(self._on_option_changed)
        self.cb_size.toggled.connect(self._on_size_toggled)
        self.cb_keep.toggled.connect(self._on_keep_toggled)
        self.btn_as_shown.clicked.connect(self._reset_size)
        self.point_slider.valueChanged.connect(lambda value: self._point_size_changed(value, from_slider=True))
        self.point_spin.valueChanged.connect(self._point_size_changed)
        self.btn_points_reset.clicked.connect(lambda: self.point_spin.setValue(100))
        for which, slider, spin in (("w", self.width_slider, self.width_spin), ("h", self.height_slider, self.height_spin)):
            slider.valueChanged.connect(lambda value, w=which: self._size_changed(w, value / SIZE_STEPS_PER_INCH, from_slider=True))
            spin.valueChanged.connect(lambda value, w=which: self._size_changed(w, value))

        self._on_option_changed()
        self._render_preview()
        fit_dialog_to_content(self, body)

    # -- the points: how large they are drawn --------------------------------------------------------------------

    def _points_box(self, fig):
        """The "Points" group: a slider (and a box) for how large the scatter points and line markers are drawn, as a percentage of the size
        they have; 100% is as drawn. A figure with no points says so and leaves it alone."""
        lo, hi = POINT_PERCENT_RANGE
        self.has_points = figures.has_points(fig)
        box = QGroupBox("Points")
        outer = QVBoxLayout(box)
        row = QHBoxLayout()
        row.addWidget(QLabel("Point size:"))
        self.point_slider = QSlider(Qt.Orientation.Horizontal)
        self.point_slider.setRange(lo, hi)
        self.point_slider.setValue(100)
        self.point_slider.setMinimumWidth(220)
        row.addWidget(self.point_slider, stretch=1)
        self.point_spin = QSpinBox()
        self.point_spin.setRange(lo, hi)
        self.point_spin.setSingleStep(5)
        self.point_spin.setSuffix(" %")
        self.point_spin.setValue(100)
        self.point_spin.setKeyboardTracking(False)                 # a typed number counts when it is entered, not on every digit
        row.addWidget(self.point_spin)
        self.btn_points_reset = QPushButton("As drawn")
        self.btn_points_reset.setToolTip("Back to the size the points are drawn at (100%).")
        row.addWidget(self.btn_points_reset)
        outer.addLayout(row)
        note = QLabel("Scatter points and the markers of lines; lines, bars and text are not changed. 100% is as drawn."
                      if self.has_points else self.no_points_note)
        note.setStyleSheet("color: gray;")
        note.setWordWrap(True)
        outer.addWidget(note)
        box.setEnabled(self.has_points)
        return box

    def _point_size_changed(self, value, from_slider=False):
        """The slider or the box moved: the other follows, and the preview is drawn again."""
        for widget in (self.point_slider, self.point_spin):
            if widget.value() != value:
                widget.blockSignals(True)
                widget.setValue(value)
                widget.blockSignals(False)
        self._schedule_live_preview()

    def custom_point_scale(self):
        """The point size as a multiple of the size drawn (1.5 for 150%), or None when it is as drawn (or the figure has no points)."""
        percent = self.point_spin.value()
        return percent / 100.0 if self.has_points and percent != 100 else None

    # -- the size: sliders (and boxes) for the width and the height --------------------

    def _size_box(self, fig):
        """The "Size" group. Off, the file is as big as the figure is on screen; on, the sliders give its width (x) and height (y)."""
        lo, hi = figures.render.MIN_SIZE_IN, figures.render.MAX_SIZE_IN
        self.as_shown = tuple(min(max(float(v), lo), hi) for v in fig.get_size_inches())
        self._ratio = self.as_shown[0] / self.as_shown[1]
        self._syncing = False
        box = QGroupBox("Size")
        outer = QVBoxLayout(box)
        self.cb_size = QCheckBox("Set the size (otherwise as big as the figure is on screen)")
        self.cb_size.setToolTip("Off: the file is the figure as it is on screen, trimmed to its content.\n"
                                "On: the file is exactly this wide and this tall, and the figure is laid out again to fit.\n"
                                "Text keeps its size in points, so a smaller figure has relatively larger text.")
        outer.addWidget(self.cb_size)

        self.size_controls = QWidget()
        form = QFormLayout(self.size_controls)
        form.setContentsMargins(0, 0, 0, 0)
        self.width_slider, self.width_spin = self._size_pair(self.as_shown[0])
        self.height_slider, self.height_spin = self._size_pair(self.as_shown[1])
        form.addRow("Width (x):", self._side_by_side(self.width_slider, self.width_spin))
        form.addRow("Height (y):", self._side_by_side(self.height_slider, self.height_spin))
        keep_row = QHBoxLayout()
        self.cb_keep = QCheckBox("Keep proportions")
        self.cb_keep.setToolTip("Moving one slider moves the other, so the figure keeps its shape.")
        keep_row.addWidget(self.cb_keep)
        self.btn_as_shown = QPushButton("As shown")
        self.btn_as_shown.setToolTip("Back to the size the figure has on screen.")
        keep_row.addWidget(self.btn_as_shown)
        keep_row.addStretch(1)
        form.addRow(keep_row)
        self.size_controls.setEnabled(False)
        outer.addWidget(self.size_controls)
        return box

    @staticmethod
    def _size_pair(inches):
        """(slider, box) showing `inches`: the slider in tenths, the box in hundredths, between the limits figures.render allows."""
        lo, hi = figures.render.MIN_SIZE_IN, figures.render.MAX_SIZE_IN
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(round(lo * SIZE_STEPS_PER_INCH), round(hi * SIZE_STEPS_PER_INCH))
        slider.setValue(round(inches * SIZE_STEPS_PER_INCH))
        spin = QDoubleSpinBox()
        spin.setRange(lo, hi)
        spin.setDecimals(2)
        spin.setSingleStep(1.0 / SIZE_STEPS_PER_INCH)
        spin.setSuffix(" in")
        spin.setKeyboardTracking(False)                            # a typed number counts when it is entered, not on every digit
        spin.setValue(inches)
        return slider, spin

    @staticmethod
    def _side_by_side(slider, spin):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        slider.setMinimumWidth(220)
        layout.addWidget(slider, stretch=1)
        layout.addWidget(spin)
        return row

    def _set_size(self, width, height):
        """Puts the sliders and boxes on (width, height) without telling anyone (the callers do)."""
        self._syncing = True
        try:
            for slider, spin, value in ((self.width_slider, self.width_spin, width), (self.height_slider, self.height_spin, height)):
                spin.setValue(value)
                slider.setValue(round(value * SIZE_STEPS_PER_INCH))
        finally:
            self._syncing = False

    def _size_changed(self, which, value, from_slider=False):
        """A slider or box moved: the other of the pair follows it, and with Keep proportions so does the other dimension."""
        if self._syncing:
            return
        lo, hi = figures.render.MIN_SIZE_IN, figures.render.MAX_SIZE_IN
        width, height = self.width_spin.value(), self.height_spin.value()
        if which == "w":
            width = value
        else:
            height = value
        if self.cb_keep.isChecked():
            if which == "w":
                height = min(max(width / self._ratio, lo), hi)
                width = height * self._ratio                       # (if the other dimension hit a limit, this one stops there too)
            else:
                width = min(max(height * self._ratio, lo), hi)
                height = width / self._ratio
        if self.cb_keep.isChecked() or from_slider:
            self._set_size(width, height)                          # a slider moved (its box follows), or the shape is kept (both follow)
        else:
            self._set_sliders(width, height)                       # a box was typed in: its slider follows
        self._on_option_changed()
        self._schedule_live_preview()

    def _set_sliders(self, width, height):
        """The sliders to the boxes' values (a box takes hundredths; the slider only moves to the nearest tenth)."""
        self._syncing = True
        try:
            self.width_slider.setValue(round(width * SIZE_STEPS_PER_INCH))
            self.height_slider.setValue(round(height * SIZE_STEPS_PER_INCH))
        finally:
            self._syncing = False

    def _on_size_toggled(self, on):
        self.size_controls.setEnabled(on)
        self._on_option_changed()
        self._schedule_live_preview()

    def _on_keep_toggled(self, on):
        if on:
            self._ratio = self.width_spin.value() / self.height_spin.value()          # the shape it has now

    def _reset_size(self):
        self._set_size(*self.as_shown)
        self._ratio = self.as_shown[0] / self.as_shown[1]
        self._on_option_changed()
        self._schedule_live_preview()

    def custom_size(self):
        """(width, height) in inches if "Set the size" is on, else None (the figure as it is on screen)."""
        return (self.width_spin.value(), self.height_spin.value()) if self.cb_size.isChecked() else None

    # -- what the dialog says -------------------------------------------------

    def settings(self):
        """The choices; "size" is only there when a size was set (it is not remembered: it belongs to the figure)."""
        out = {"format": self.format_combo.currentData(), "dpi": self.dpi_spin.value(),
               "transparent": self.cb_transparent.isChecked(), "editable_text": self.cb_editable.isChecked(),
               "data_csv": self.cb_data.isChecked() and not self.cb_data.isHidden()}
        if self.custom_size() is not None:
            out["size"] = self.custom_size()
        if self.custom_point_scale() is not None:
            out["point_scale"] = self.custom_point_scale()
        return out

    def edits(self):
        """{TextItem: new text} for each title/label/legend field that was changed."""
        return {item: field.text() for item, field in self.fields.items() if field.text() != item.text}

    # -- the preview -------------------------------------------------------------

    def _on_option_changed(self, *_):
        vector = self.format_combo.currentData() in figures.VECTOR_FORMATS
        self.cb_editable.setEnabled(vector)
        self._update_size_label()

    def _schedule_preview(self, *_):
        """Typing: draw once the typing pauses (every keystroke starts the wait again)."""
        self._timer.start(TYPING_PREVIEW_MS)

    def _schedule_live_preview(self):
        """The size is moving (a slider is dragged, a box stepped): draw as often as drawing allows, not once it stops: a steady drag
        never pauses, so waiting for a pause would show nothing until the hand lets go. A drawing that is already due is not pushed back
        (it will show the latest size). The wait is twice as long as the last drawing took, so a long recording that takes a while to draw
        leaves the slider time to move."""
        wait = min(max(LIVE_PREVIEW_MS, round(2 * self._last_draw_ms)), LIVE_PREVIEW_MAX_MS)
        if not self._timer.isActive() or self._timer.remainingTime() > wait:
            self._timer.start(wait)

    def _render_preview(self):
        started = time.perf_counter()
        try:
            buf = io.BytesIO()
            figures.render_figure(self.fig, buf, fmt="png", dpi=PREVIEW_DPI, edits=self.edits(), software=SOFTWARE, size=self.custom_size(),
                                   point_scale=self.custom_point_scale())
            pixmap = QPixmap()
            pixmap.loadFromData(buf.getvalue())
            self._preview_size_in = (pixmap.width() / PREVIEW_DPI, pixmap.height() / PREVIEW_DPI)
            self.preview.setPixmap(pixmap.scaled(*PREVIEW_MAX, Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation))
        except Exception:                                      # noqa: BLE001 - a failed preview must not stop an export
            errorlog.error("Could not draw the export preview", exc_info=True)
            self._preview_size_in = None
            self.preview.setText("(no preview)")
        self._last_draw_ms = (time.perf_counter() - started) * 1000
        self._update_size_label()

    def _update_size_label(self):
        """What the file will be: the size set with the sliders if there is one, else what the preview was drawn at. A PNG/TIFF too big to
        write (more pixels than figures.render.MAX_PIXELS) is said so, in red, and cannot be exported."""
        custom = self.custom_size()
        if custom is None and self._preview_size_in is None:
            self.size_label.setText("")
            self._too_big(False)
            return
        w, h = custom or self._preview_size_in
        mm = f"{w * 25.4:.0f} × {h * 25.4:.0f} mm"
        dpi = self.dpi_spin.value()
        if self.format_combo.currentData() in figures.VECTOR_FORMATS:
            self.size_label.setText(f"{w:.2f} × {h:.2f} in ({mm}), vector")
            self._too_big(False)
        elif custom is not None and w * dpi * h * dpi > figures.render.MAX_PIXELS:
            self.size_label.setText(f"Too large: {w * dpi * h * dpi / 1e6:.0f} megapixels (at most {figures.render.MAX_PIXELS / 1e6:.0f}). "
                                    "Make it smaller or lower the dpi.")
            self._too_big(True)
        else:
            self.size_label.setText(f"{round(w * dpi)} × {round(h * dpi)} px at {dpi} dpi  ({w:.2f} × {h:.2f} in, {mm})")
            self._too_big(False)

    def _too_big(self, too_big):
        self.size_label.setStyleSheet("color: #c0392b;" if too_big else "color: gray;")
        self.export_button.setEnabled(not too_big)
        self.copy_button.setEnabled(not too_big)

    # -- the clipboard --------------------------------------------------------------------------------------------------

    def image(self):
        """The figure as a QImage, drawn as a PNG file would be (the dpi, the size, the point size, the transparent background, the words)."""
        settings = self.settings()
        out = io.BytesIO()
        figures.render_figure(self.fig, out, fmt="png", dpi=settings["dpi"], transparent=settings["transparent"], edits=self.edits(), software=SOFTWARE,
                              size=settings.get("size"), point_scale=settings.get("point_scale"))
        image = QImage.fromData(out.getvalue(), "PNG")
        if image.isNull():
            raise ValueError("the figure could not be drawn as an image")
        return image

    def copy_to_clipboard(self):
        """Copy to Clipboard: the figure goes on the clipboard as an image, and the dialog closes without exporting. A failure says so and leaves
        the dialog open."""
        try:
            image = self.image()
            QApplication.clipboard().setImage(image)
        except Exception as e:                                           # noqa: BLE001 - nothing was exported; say why and stay
            errorlog.error("Could not copy the figure to the clipboard", exc_info=True)
            show_error(self.ctx, f"Could not copy the figure: {e}")
            return
        show_window_toast(self.ctx, f"Figure copied to the clipboard ({image.width()} × {image.height()} px)")
        self.reject()


def _file_stem(ctx, default_prefix, tracking_info):
    store = ctx.cache.get('store', 'Data') if ctx.cache else 'Data'
    suffix = f"_{tracking_info}" if tracking_info else ""
    return f"{default_prefix}_{store}{suffix}_{datetime.datetime.now().strftime('%H%M%S')}"


def write_export(ctx, fig, default_prefix, tracking_info, provenance, settings, edits, *, parent=None,
                 data_writer=None, stem=None, **export_kwargs):
    """The export itself, once the choices are made: remembers them, then the figure goes through
    context.export_file (its destination rules, its provenance record) with its data CSV beside it."""
    fmt = settings["format"]
    _label, ext, file_filter, _mpl = figures.FORMATS[fmt]
    ctx.settings["figure_export"] = {k: settings[k] for k in DEFAULTS}
    try:
        _context.save_settings(ctx.settings)
    except OSError:
        errorlog.error("Could not save the Export Figure choices", exc_info=True)

    spec = dict(provenance or {})
    spec["notes"] = [*(spec.get("notes") or []), *figures.figure_notes(settings, edits),
                     *getattr(fig, "pyat_edit_notes", [])]                  # (what was changed with Edit Attributes: figures/restyle.py)

    def _write(path):
        figures.render_figure(fig, path, fmt=fmt, dpi=settings["dpi"], transparent=settings["transparent"],
                      editable_text=settings["editable_text"], edits=edits, software=SOFTWARE, size=settings.get("size"),
                      point_scale=settings.get("point_scale"))
        if not settings["data_csv"]:
            return []
        with figures.edited_texts(edits):                                # the CSV says what the figure says
            writer = data_writer or (lambda base: figures.write_figure_data(fig, base))
            return writer(os.path.splitext(path)[0])

    name = f"{stem or _file_stem(ctx, default_prefix, tracking_info)}.{ext}"
    _context.export_file(ctx, parent if parent is not None else ctx.win, f"Export {default_prefix} Figure", name,
                         file_filter, _write, provenance=spec, **export_kwargs)


def export_figure(ctx, fig, default_prefix, tracking_info="", provenance=None, *, parent=None, data_writer=None,
                  stem=None, no_points_note=None, **export_kwargs):
    """Opens the Export Figure dialog for `fig` and, if it is accepted, writes the figure (and its data) as
    asked. `provenance` is {"kind", "parameters", "notes"} as for context.export_file; `data_writer(base)` writes
    the data CSVs (returning their paths) when the generic extraction (figures/data.py) is not right for the figure;
    `stem` names the file when the default "<prefix>_<recording>_<tracking>_<time>" is not wanted. `no_points_note` is what the Points section
    says when the figure has no points (where to get some). Anything else
    (dest_dir, recording_type, recording_source) goes to export_file."""
    dialog = FigureExportDialog(ctx, fig, f"Export {default_prefix} Figure", parent, has_data=True, no_points_note=no_points_note)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    write_export(ctx, fig, default_prefix, tracking_info, provenance, dialog.settings(), dialog.edits(), parent=parent,
                 data_writer=data_writer, stem=stem, **export_kwargs)

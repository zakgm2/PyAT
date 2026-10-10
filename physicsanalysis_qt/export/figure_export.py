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
  - Titles, axis labels, colour-bar labels and legend entries are fields in the dialog: change them and the export
    carries the new words (and so does the data CSV — a renamed legend entry renames the series). The figure on
    screen is not touched. (figures/labels.py.)
  - A CSV of the data behind each plot beside the figure (figures/data.py), unless you untick it: every plotted
    point, band, bar and heatmap cell, as drawn.
  - A live preview, with the pixel/inch size the file will have.
  - The provenance record every export gets (context.export_file), which also lists the data CSV and says what
    was edited.

The last choices are remembered in settings["figure_export"]. The part that writes a file (render_figure) is
figures/render.py, usable without any window.
"""

import datetime
import io
import os

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QLabel, QLineEdit, QSpinBox,
)

from .. import figures
from .. import __version__
from ..app import errorlog
from .. import context as _context            # not `from .context import save_settings`: tests replace it on the module
from ..app.window_fit import fit_dialog_to_content, scroll_body

SOFTWARE = f"PyAT {__version__}"                  # named in the metadata of every file it writes
DEFAULTS = {"format": "png", "dpi": 300, "transparent": False, "editable_text": True, "data_csv": True}
MIN_DPI, MAX_DPI = 72, 1200
PREVIEW_DPI = 90
PREVIEW_MAX = (560, 340)                    # pixels the preview may take in the dialog


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
    """Format, resolution, what to include, the editable words, and a preview of the result."""

    def __init__(self, ctx, fig, title="Export Figure", parent=None, has_data=True):
        super().__init__(parent if parent is not None else ctx.win)
        self.ctx = ctx
        self.fig = fig
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
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._render_preview)
        self._preview_size_in = None
        for signal in (self.format_combo.currentIndexChanged, self.dpi_spin.valueChanged, self.cb_editable.toggled):
            signal.connect(self._on_option_changed)
        self.cb_transparent.toggled.connect(self._on_option_changed)

        self._on_option_changed()
        self._render_preview()
        fit_dialog_to_content(self, body)

    # -- what the dialog says -------------------------------------------------

    def settings(self):
        return {"format": self.format_combo.currentData(), "dpi": self.dpi_spin.value(),
                "transparent": self.cb_transparent.isChecked(), "editable_text": self.cb_editable.isChecked(),
                "data_csv": self.cb_data.isChecked() and not self.cb_data.isHidden()}

    def edits(self):
        """{TextItem: new text} for each title/label/legend field that was changed."""
        return {item: field.text() for item, field in self.fields.items() if field.text() != item.text}

    # -- the preview -------------------------------------------------------------

    def _on_option_changed(self, *_):
        vector = self.format_combo.currentData() in figures.VECTOR_FORMATS
        self.cb_editable.setEnabled(vector)
        self._update_size_label()

    def _schedule_preview(self, *_):
        self._timer.start()

    def _render_preview(self):
        try:
            buf = io.BytesIO()
            figures.render_figure(self.fig, buf, fmt="png", dpi=PREVIEW_DPI, edits=self.edits(), software=SOFTWARE)
            pixmap = QPixmap()
            pixmap.loadFromData(buf.getvalue())
            self._preview_size_in = (pixmap.width() / PREVIEW_DPI, pixmap.height() / PREVIEW_DPI)
            self.preview.setPixmap(pixmap.scaled(*PREVIEW_MAX, Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation))
        except Exception:                                      # noqa: BLE001 - a failed preview must not stop an export
            errorlog.error("Could not draw the export preview", exc_info=True)
            self._preview_size_in = None
            self.preview.setText("(no preview)")
        self._update_size_label()

    def _update_size_label(self):
        if self._preview_size_in is None:
            self.size_label.setText("")
            return
        w, h = self._preview_size_in
        mm = f"{w * 25.4:.0f} × {h * 25.4:.0f} mm"
        if self.format_combo.currentData() in figures.VECTOR_FORMATS:
            self.size_label.setText(f"{w:.2f} × {h:.2f} in ({mm}), vector")
        else:
            dpi = self.dpi_spin.value()
            self.size_label.setText(f"{round(w * dpi)} × {round(h * dpi)} px at {dpi} dpi  ({w:.2f} × {h:.2f} in, {mm})")


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
    spec["notes"] = [*(spec.get("notes") or []), *figures.figure_notes(settings, edits)]

    def _write(path):
        figures.render_figure(fig, path, fmt=fmt, dpi=settings["dpi"], transparent=settings["transparent"],
                      editable_text=settings["editable_text"], edits=edits, software=SOFTWARE)
        if not settings["data_csv"]:
            return []
        with figures.edited_texts(edits):                                # the CSV says what the figure says
            writer = data_writer or (lambda base: figures.write_figure_data(fig, base))
            return writer(os.path.splitext(path)[0])

    name = f"{stem or _file_stem(ctx, default_prefix, tracking_info)}.{ext}"
    _context.export_file(ctx, parent if parent is not None else ctx.win, f"Export {default_prefix} Figure", name,
                         file_filter, _write, provenance=spec, **export_kwargs)


def export_figure(ctx, fig, default_prefix, tracking_info="", provenance=None, *, parent=None, data_writer=None,
                  stem=None, **export_kwargs):
    """Opens the Export Figure dialog for `fig` and, if it is accepted, writes the figure (and its data) as
    asked. `provenance` is {"kind", "parameters", "notes"} as for context.export_file; `data_writer(base)` writes
    the data CSVs (returning their paths) when the generic extraction (figures/data.py) is not right for the figure;
    `stem` names the file when the default "<prefix>_<recording>_<tracking>_<time>" is not wanted. Anything else
    (dest_dir, recording_type, recording_source) goes to export_file."""
    dialog = FigureExportDialog(ctx, fig, f"Export {default_prefix} Figure", parent, has_data=True)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    write_export(ctx, fig, default_prefix, tracking_info, provenance, dialog.settings(), dialog.edits(), parent=parent,
                 data_writer=data_writer, stem=stem, **export_kwargs)

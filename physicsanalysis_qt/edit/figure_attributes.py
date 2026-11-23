"""
edit/figure_attributes.py
-------------------------
Edit Attributes for the figure of an analysis window (Z-Score, AUC, FFT, Curve Fit, Event PETH, Compare Events, Recording Overview, a result read back
by Open Results): the same dialog the recording's plot has, with what the figure has — every title and label (and the size of each kind), the colour of
each line, the dot on every sample, the legend, the grid. What is edited is kept apart from the figure (figures/restyle.py) and put back on it after
every drawing, so it is still there when the window draws the figure again for another event, view or Recalculate; Export Plot writes the figure as it
is edited, and says so in the record beside the file.

A window gives itself this by making an EditableFigure of its figure and canvas, as `self.editable_figure`, and calling `drawn()` after each drawing:

    self.editable_figure = EditableFigure(ctx, self, self.fig, self.canvas)
    ...
    figures.draw_event_peth(self.fig, ...)
    self.editable_figure.drawn()                 # remembers what the drawing says, puts the edits on it, shows it

The Edit Attributes button (edit/attributes.py), and a button in the header of the window's tab (ui/workspace.py), then edit it.
"""

from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

from .. import figures
from ..app import errorlog
from ..app.toasts import show_error
from ..app.window_fit import fit_dialog_to_content, scroll_body
from .attribute_widgets import ColorRow, PointSizeBox, gray_note

restyle = figures.restyle


class EditableFigure:
    """A figure that a window draws and redraws, and what the person changed about it. `window` is the dialog that shows it (what the Edit Attributes
    dialog is parented to), `canvas` what shows it."""

    def __init__(self, ctx, window, fig, canvas):
        self.ctx = ctx
        self.window = window
        self.fig = fig
        self.canvas = canvas
        self.edits = restyle.FigureEdits()
        self.parts = None                                     # what the figure says on its own, from its last drawing

    def drawn(self, now=False):
        """The figure has just been drawn (again): remember what it says and shows on its own, put the edits on it, and show it (`now`: at once
        rather than when the window next has a moment)."""
        try:
            self.parts = restyle.describe(self.fig)
            self.apply(now)
        except Exception:                                    # noqa: BLE001 - an edit tool must never stop a window from showing its figure
            errorlog.error("Could not put the Edit Attributes edits on the figure", exc_info=True)
            self.parts = None
            self.canvas.draw() if now else self.canvas.draw_idle()

    def apply(self, now=False):
        if self.parts is None:
            return
        restyle.apply(self.fig, self.parts, self.edits)
        self.fig.pyat_edit_notes = restyle.edit_notes(self.parts, self.edits)         # (what Export Plot's provenance record says about it)
        self.canvas.draw() if now else self.canvas.draw_idle()

    def set_edits(self, edits):
        self.edits = edits
        self.apply()

    def reset(self):
        """Every title, label, colour, size and the rest back to what the window drew."""
        self.set_edits(restyle.FigureEdits())

    def edit(self):
        """Opens the dialog."""
        if self.parts is None:
            show_error(self.ctx, "There is nothing to edit yet: the figure has not been drawn.")
            return
        FigureAttributesDialog(self.window, self).exec()


class FigureAttributesDialog(QDialog):
    """Edit Graph Attributes for a figure: the words, the colours, the points, the legend."""

    def __init__(self, parent, editable):
        super().__init__(parent)
        self.editable = editable
        parts, edits = editable.parts, editable.edits
        self.setWindowTitle("Edit Graph Attributes")
        outer, layout, body = scroll_body(self)                # one row per text, line and legend entry: grows with the figure, so it scrolls

        # Labels & font sizes
        labels = QGroupBox("Labels && Font Sizes")                # && — a single & is Qt's shortcut marker
        grid = QGridLayout(labels)
        self.text_fields = {}                                    # {text key: QLineEdit}
        for row, text in enumerate(parts.texts):
            grid.addWidget(QLabel(f"{text.key}:"), row, 0)
            field = QLineEdit(edits.texts.get(text.key, text.default))
            field.setMinimumWidth(260)
            grid.addWidget(field, row, 1)
            self.text_fields[text.key] = field
        sizes = QHBoxLayout()
        self.size_fields = {}                                    # {size kind: QLineEdit}
        for kind in (k for k in parts.kinds() if k != restyle.LEGEND):
            sizes.addWidget(QLabel(f"{restyle.SIZE_NAMES[kind]} size:"))
            field = QLineEdit(str(edits.sizes.get(kind, round(parts.size_default(kind)))))
            field.setFixedWidth(40)
            sizes.addWidget(field)
            self.size_fields[kind] = field
        sizes.addStretch(1)
        grid.addLayout(sizes, len(parts.texts), 0, 1, 2)
        options = QHBoxLayout()
        self.cb_bold = QCheckBox("Bold")
        self.cb_bold.setChecked(parts.bold_default if edits.bold is None else edits.bold)
        self.cb_bold.setEnabled(any(t.kind in restyle.BOLD_KINDS for t in parts.texts))
        options.addWidget(self.cb_bold)
        self.cb_grid = QCheckBox("Show Grid")
        self.cb_grid.setChecked(any(g.on for g in parts.grids) if edits.grid is None else edits.grid)
        self.cb_grid.setEnabled(bool(parts.grids))
        options.addWidget(self.cb_grid)
        options.addStretch(1)
        grid.addLayout(options, len(parts.texts) + 1, 0, 1, 2)
        if not parts.texts:
            grid.addWidget(gray_note("This figure has no titles or labels to edit."), 0, 0, 1, 2)
        layout.addWidget(labels)

        # Line colors
        colors = QGroupBox("Line Colors")
        colors_layout = QVBoxLayout(colors)
        self.color_rows = []
        if parts.series:
            color_grid = QGridLayout()
            color_grid.setColumnStretch(0, 1)
            for i, series in enumerate(parts.series):
                row = ColorRow(self, series.key, series.key, series.default_color, edits.colors.get(series.key))
                color_grid.addWidget(QLabel(row.name), i, 0)
                color_grid.addWidget(row.color_btn, i, 1)
                color_grid.addWidget(row.reset_btn, i, 2)
                self.color_rows.append(row)
            colors_layout.addLayout(color_grid)
        else:
            colors_layout.addWidget(gray_note("This figure has no lines."))
        layout.addWidget(colors)

        self.points = PointSizeBox(
            figures.view.MAX_POINT_SIZE, parts.point_default, edits.point_size,
            "A dot on every sample of every line (0 draws none). In Export Figure the points can be made larger or smaller still.",
            enabled=bool(parts.series))
        layout.addWidget(self.points)

        # Legend
        self.entry_fields = []                                   # [(entry key, show checkbox, name field)]
        self.leg_fs = self.leg_loc_combo = None
        if parts.legends:
            legend = QGroupBox("Legend")
            legend_layout = QVBoxLayout(legend)
            top = QHBoxLayout()
            top.addWidget(QLabel("Font size:"))
            self.leg_fs = QLineEdit(str(edits.sizes.get(restyle.LEGEND, round(parts.size_default(restyle.LEGEND)))))
            self.leg_fs.setFixedWidth(50)
            top.addWidget(self.leg_fs)
            top.addWidget(QLabel("Position:"))
            self.leg_loc_combo = QComboBox()
            self.leg_loc_combo.addItems(figures.view.LEGEND_LOCATIONS)
            self.leg_loc_combo.setCurrentText(edits.legend_loc or parts.legends[0].loc)
            top.addWidget(self.leg_loc_combo)
            top.addStretch(1)
            legend_layout.addLayout(top)
            entries = QGridLayout()
            entries.addWidget(QLabel("Show"), 0, 0)
            entries.addWidget(QLabel("Label"), 0, 1)
            row = 1
            for lp in parts.legends:
                for entry in lp.entries:
                    name, shown = edits.legend_entries.get(entry.key, (entry.default, True))
                    show = QCheckBox()
                    show.setChecked(shown)
                    field = QLineEdit(name)
                    entries.addWidget(show, row, 0)
                    entries.addWidget(field, row, 1)
                    self.entry_fields.append((entry.key, show, field))
                    row += 1
            legend_layout.addLayout(entries)
            legend_layout.addWidget(gray_note("Renaming an entry renames the line itself, so the data file Export Plot writes beside the figure calls it that too."))
            layout.addWidget(legend)

        buttons = QHBoxLayout()
        apply_btn = QPushButton("Apply")
        apply_btn.setDefault(True)
        apply_btn.clicked.connect(self._apply)
        self.btn_reset = QPushButton("Reset All")
        self.btn_reset.setToolTip("Put every title, label, colour, size and the rest back to what the window drew.")
        self.btn_reset.setEnabled(not edits.is_empty())
        self.btn_reset.clicked.connect(self._reset)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(apply_btn)
        buttons.addWidget(self.btn_reset)
        buttons.addWidget(cancel_btn)
        outer.addLayout(buttons)

        fit_dialog_to_content(self, body)

    def _apply(self):
        editable = self.editable
        edits = restyle.edited(
            editable.parts, editable.edits,
            texts={key: field.text() for key, field in self.text_fields.items()},
            sizes={**{kind: field.text() for kind, field in self.size_fields.items()},
                   **({restyle.LEGEND: self.leg_fs.text()} if self.leg_fs is not None else {})},
            bold=self.cb_bold.isChecked() if self.cb_bold.isEnabled() else None,
            grid=self.cb_grid.isChecked() if self.cb_grid.isEnabled() else None,
            colors=[(row.orig, row.override, row.default_color) for row in self.color_rows],
            point_size=self.points.chosen(),
            legend_loc=self.leg_loc_combo.currentText() if self.leg_loc_combo is not None else None,
            entries=[(key, field.text(), show.isChecked()) for key, show, field in self.entry_fields])
        editable.set_edits(edits)
        self.accept()

    def _reset(self):
        self.editable.reset()
        self.accept()

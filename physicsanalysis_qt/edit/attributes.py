"""
edit/attributes.py
------------------
Edit Attributes dialog: title/label text and font sizes, per-trace line
colors, legend font size/position, per-legend-entry show/hide + rename, and
grid visibility. Renaming the legend entry of a recording's signal (a TDT trace) renames the signal itself —
see edit/signal_names.py — so the new name follows it into the analyses and exports. Line colors are picked with edit/color_picker.py's
hue/saturation field and stored in plot_attrs["line_colors"], which every
plotting engine reads through context.trace_color().
"""

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox, QLabel,
    QLineEdit, QComboBox, QCheckBox, QPushButton,
)

from .. import figures
from ..plot import plotting
from .color_picker import pick_color
from ..plot.interaction import _refresh_hover_bg
from .signal_names import apply_signal_renames
from ..app.toasts import show_error
from ..app.window_fit import scroll_body, fit_dialog_to_content


class _ColorRow:
    """One trace's line-color state in the Line Colors section: a swatch
    that opens the picker, and a Reset button. `orig` is the trace's raw
    (un-renamed) name — what plot_attrs["line_colors"] is keyed by — and
    `name` is what to call it in the UI."""

    def __init__(self, dialog, orig, name, default_color, override):
        self.dialog = dialog
        self.orig = orig
        self.name = name
        self.default_color = QColor(default_color).name()
        self.override = override  # "#rrggbb" or None (= the engine's default color)

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


class AttributesDialog(QDialog):
    """Edit graph labels, font sizes, legend size/position, and per-entry legend edits."""

    LEG_LOCS = figures.view.LEGEND_LOCATIONS

    def __init__(self, parent, ctx):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Edit Graph Attributes")
        # One row per legend entry below, so this grows with the dataset
        # (many Oxysoft channels / CSV columns) — scrolls instead of
        # outgrowing the screen. See app/window_fit.py.
        outer, layout, body = scroll_body(self)

        plot_attrs = ctx.plot_attrs
        cur_title = plot_attrs["title"] or ctx._last_title
        cur_xlabel = plot_attrs["xlabel"] or ctx._last_xlabel
        cur_ylabel = plot_attrs["ylabel"] or ctx._last_ylabel

        # Labels & font sizes
        lf = QGroupBox("Labels && Font Sizes")  # && — a single & is Qt's shortcut marker
        grid = QGridLayout(lf)
        self.e_title, self.e_title_fs = self._row(grid, 0, "Title:", cur_title, plot_attrs["title_fs"])
        self.e_xlabel, self.e_xlabel_fs = self._row(grid, 1, "X Label:", cur_xlabel, plot_attrs["xlabel_fs"])
        self.e_ylabel, self.e_ylabel_fs = self._row(grid, 2, "Y Label:", cur_ylabel, plot_attrs["ylabel_fs"])
        self.cb_bold = QCheckBox("Bold")
        self.cb_bold.setChecked(plot_attrs.get("bold", True))
        grid.addWidget(self.cb_bold, 3, 0, 1, 2)
        self.cb_grid = QCheckBox("Show Grid")
        self.cb_grid.setChecked(ctx.show_grid)
        grid.addWidget(self.cb_grid, 3, 2, 1, 2)
        layout.addWidget(lf)

        entries = list(ctx._legend_entries)
        saved_entry_map = figures.attributes.legend_edits(plot_attrs)

        # Line colors — one row per plotted trace, independent of whether
        # (or under what name) it shows in the legend below.
        lc = QGroupBox("Line Colors")
        lc_layout = QVBoxLayout(lc)
        self.color_rows = []  # one _ColorRow per trace
        if entries:
            color_grid = QGridLayout()
            color_grid.setColumnStretch(0, 1)
            for i, l in enumerate(entries):
                row = _ColorRow(self, l, saved_entry_map.get(l, (l, True))[0],
                                ctx._trace_default_colors.get(l, "#808080"),
                                plot_attrs["line_colors"].get(l))
                color_grid.addWidget(QLabel(row.name), i, 0)
                color_grid.addWidget(row.color_btn, i, 1)
                color_grid.addWidget(row.reset_btn, i, 2)
                self.color_rows.append(row)
            lc_layout.addLayout(color_grid)
        else:
            no_lines = QLabel("No lines found — load data first.")
            no_lines.setStyleSheet("color: gray;")
            lc_layout.addWidget(no_lines)
        layout.addWidget(lc)

        # Legend
        lf2 = QGroupBox("Legend")
        lf2_layout = QVBoxLayout(lf2)
        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Font size:"))
        self.e_leg_fs = QLineEdit(str(plot_attrs["leg_fs"]))
        self.e_leg_fs.setFixedWidth(50)
        top_row.addWidget(self.e_leg_fs)
        top_row.addWidget(QLabel("Position:"))
        self.leg_loc_combo = QComboBox()
        self.leg_loc_combo.addItems(self.LEG_LOCS)
        self.leg_loc_combo.setCurrentText(plot_attrs["leg_loc"])
        top_row.addWidget(self.leg_loc_combo)
        top_row.addStretch(1)
        lf2_layout.addLayout(top_row)

        self.entry_widgets = []  # (checkbox, lineedit, original_label)
        if entries:
            entry_grid = QGridLayout()
            entry_grid.addWidget(QLabel("Show"), 0, 0)
            entry_grid.addWidget(QLabel("Label"), 0, 1)
            for i, l in enumerate(entries):
                saved_label, saved_vis = saved_entry_map.get(l, (l, True))
                cb = QCheckBox()
                cb.setChecked(saved_vis)
                le = QLineEdit(saved_label)
                entry_grid.addWidget(cb, i + 1, 0)
                entry_grid.addWidget(le, i + 1, 1)
                self.entry_widgets.append((cb, le, l))
            lf2_layout.addLayout(entry_grid)
            if (ctx.cache or {}).get('signals'):
                hint = QLabel("Renaming a signal here renames it everywhere (analyses, exports); Save Changes keeps it.")
                hint.setStyleSheet("color: gray;")
                hint.setWordWrap(True)
                lf2_layout.addWidget(hint)
        else:
            no_entries = QLabel("No legend entries found — load data first.")
            no_entries.setStyleSheet("color: gray;")
            lf2_layout.addWidget(no_entries)

        layout.addWidget(lf2)

        btn_row = QHBoxLayout()
        apply_btn = QPushButton("Apply")
        apply_btn.setDefault(True)
        apply_btn.clicked.connect(self._apply)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(apply_btn)
        btn_row.addWidget(cancel_btn)
        outer.addLayout(btn_row)

        fit_dialog_to_content(self, body)

    def _row(self, grid, row, label_text, default_text, default_size):
        grid.addWidget(QLabel(label_text), row, 0)
        e_text = QLineEdit(default_text)
        e_text.setFixedWidth(220)
        grid.addWidget(e_text, row, 1)
        grid.addWidget(QLabel("Size:"), row, 2)
        e_size = QLineEdit(str(default_size))
        e_size.setFixedWidth(40)
        grid.addWidget(e_size, row, 3)
        return e_text, e_size

    def _apply(self):
        ctx = self.ctx
        plot_attrs = ctx.plot_attrs

        def rename(wanted):
            # A legend entry that is one of the recording's signals is that signal's name: renaming it renames the signal (and moves
            # its colour and legend edit to the new name); any other entry — an Oxysoft channel group, a CSV column — is only a legend
            # edit. Redrawn below.
            return apply_signal_renames(ctx, wanted, redraw=False)

        try:
            # figures/attributes.py's Apply: the rules for what a typed or picked value becomes. The fields start out
            # holding the plot's own title and labels; only text that differs from them is an edit worth keeping (pinning the automatic
            # text would freeze a name that later changes), and a rename that is refused changes nothing at all.
            result = figures.attributes.apply_edits(
                plot_attrs, auto={"title": ctx._last_title, "xlabel": ctx._last_xlabel, "ylabel": ctx._last_ylabel},
                own_names=list(ctx._legend_entries), signals=(ctx.cache or {}).get('signals'), rename=rename,
                texts={"title": self.e_title.text(), "xlabel": self.e_xlabel.text(), "ylabel": self.e_ylabel.text()},
                sizes={"title_fs": self.e_title_fs.text(), "xlabel_fs": self.e_xlabel_fs.text(), "ylabel_fs": self.e_ylabel_fs.text()},
                leg_fs=self.e_leg_fs.text(), leg_loc=self.leg_loc_combo.currentText(), bold=self.cb_bold.isChecked(),
                entries=[(orig_l, le.text(), cb.isChecked()) for cb, le, orig_l in self.entry_widgets],
                colors=[(row.orig, row.override, row.default_color) for row in self.color_rows])
        except ValueError as e:
            show_error(ctx, str(e))                                         # nothing was changed; the dialog stays open
            return

        plotting.set_grid_visibility(ctx, self.cb_grid.isChecked())

        # Colors are baked into each line when it's drawn, so a color change
        # needs a redraw on every engine; matplotlib's cheaper in-place
        # attribute refresh is only enough when nothing about the lines moved.
        if result.colors_changed or result.renamed or ctx.settings.get("plot_engine") == "pyqtgraph":
            plotting.simple_plot(ctx)  # pyqtgraph has no incremental "apply" — full rebuild
        else:
            plotting._apply_plot_attrs(ctx)
            _refresh_hover_bg(ctx)
        self.accept()


def open_attributes_window(ctx):
    dlg = AttributesDialog(ctx.win, ctx)
    dlg.exec()

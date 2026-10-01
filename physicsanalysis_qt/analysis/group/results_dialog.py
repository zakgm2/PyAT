"""
analysis/group/results_dialog.py
----------------------------------
The results of a group analysis: the text report (design, per-measure tables, notes, methods
paragraph) on one tab, and the figures (plots.py — traces, heatmaps, measures, diagnostics) on
another, each with a plain matplotlib canvas and an Export Plot button (PNG/PDF/SVG, the same
convention as every other analysis's Export Plot — see analysis/dispatch.py).
"""

import os
import subprocess
import sys
from datetime import datetime

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem, QTabWidget,
    QVBoxLayout, QWidget,
)

import PhysicsLibrary as pl
from PhysicsLibrary.analysis.group import METRIC_LABELS

from ...context import export_file
from ...toasts import show_error, show_window_toast
from ...window_fit import fit_to_screen
from .plots import (
    MeasuresDisplayOptions, build_all_figures, build_measures_figure,
    figure_title_text, set_figure_title_text,
)

_FIGURE_LABELS = {"traces": "Mean traces", "measures": "Measures by marker", "diagnostics": "Model diagnostics"}

# A canvas shrunk below this fraction of its figure's own designed size (in inches * dpi) can
# start showing the suptitle overlapping the panel titles below it — layout='constrained' (see
# plots.py) keeps re-solving the layout as a figure resizes, but it can't invent room that
# genuinely isn't there; a small margin above the ~0.55-0.6 fraction where that starts (measured
# empirically) is enough that shrinking the window all the way down never breaks it.
_MIN_CANVAS_SIZE_FRACTION = 0.7


def _min_canvas_size(fig):
    w = max(320, int(fig.get_figwidth() * fig.dpi * _MIN_CANVAS_SIZE_FRACTION))
    h = max(280, int(fig.get_figheight() * fig.dpi * _MIN_CANVAS_SIZE_FRACTION))
    return w, h

# Combo text <-> MeasuresDisplayOptions.legend_position. "Best" is what the app calls it; plots.py
# maps it to a fixed corner internally, since matplotlib's automatic loc="best" doesn't exist for
# a figure-level legend.
_LEGEND_POSITION_LABELS = {
    "best": "Best", "upper right": "Upper right", "upper left": "Upper left",
    "lower right": "Lower right", "lower left": "Lower left", "outside right": "Outside (right)",
}


def open_folder(path):
    """Show a folder in the system's file browser."""
    if sys.platform.startswith("win"):
        os.startfile(path)                                   # noqa: S606 - a folder the analysis just wrote
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def figure_label(key):
    """A figure dict key ("traces", "heatmap_L1P¹", ...) as text for the picker."""
    if key.startswith("heatmap_"):
        return f"Heatmap: {key[len('heatmap_'):]}"
    return _FIGURE_LABELS.get(key, key)


class _ReportTab(QWidget):
    def __init__(self, ctx, results):
        super().__init__()
        self.ctx = ctx
        layout = QVBoxLayout(self)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFont("Consolas", 9)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.text.setFont(font)
        self.text.setPlainText(pl.group_report_text(results))
        layout.addWidget(self.text, stretch=1)

        row = QHBoxLayout()
        btn_copy = QPushButton("Copy report")
        btn_copy.clicked.connect(self._copy)
        row.addWidget(btn_copy)
        row.addStretch(1)
        layout.addLayout(row)

    def _copy(self):
        QApplication.clipboard().setText(self.text.toPlainText())
        show_window_toast(self.ctx, "Report copied")


class _FiguresTab(QWidget):
    """Every figure plots.build_all_figures produced, one at a time via a combo box — each figure
    gets its own canvas, built once and kept (switching tabs back and forth doesn't rebuild it).

    "measures" gets an extra Customize panel (only shown while it's the selected figure): show/hide
    individual sample points, bars vs. box-and-whisker, a legend show/position control, and a rename
    table — renaming two markers to the same text combines them into one pooled bar (see
    plots.MeasuresDisplayOptions). Every control redraws the measures figure immediately; Export Plot
    always exports whatever is currently on screen, customized or not."""

    def __init__(self, ctx, results, group_dir):
        super().__init__()
        self.ctx = ctx
        self.results = results
        self.group_dir = group_dir
        self.figures = build_all_figures(results)
        self.measure_options = MeasuresDisplayOptions()
        self._custom_titles = {}  # {figure key: user-typed text} — see _on_title_edited

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Figure:"))
        self.combo = QComboBox()
        for key in self.figures:
            self.combo.addItem(figure_label(key), userData=key)
        self.combo.currentIndexChanged.connect(self._on_figure_changed)
        top.addWidget(self.combo, stretch=1)
        layout.addLayout(top)

        title_row = QHBoxLayout()
        title_row.addWidget(QLabel("Title:"))
        self.e_title = QLineEdit()
        self.e_title.editingFinished.connect(self._on_title_edited)
        title_row.addWidget(self.e_title, stretch=1)
        layout.addLayout(title_row)

        self.stack = QStackedWidget()
        self.canvases = {}
        for key, fig in self.figures.items():
            canvas = FigureCanvasQTAgg(fig)
            self.canvases[key] = canvas
            self.stack.addWidget(canvas)
        layout.addWidget(self.stack, stretch=1)
        if self.figures:
            # QStackedWidget.minimumSizeHint() is the max across every page it holds, shown or
            # not (Qt's own documented behavior) — a tall diagnostics grid would otherwise force
            # the whole dialog to reserve that much room even while a small single-measure view
            # is what's actually on screen. Setting the minimum on the stack widget itself (not
            # each canvas) overrides that for layout purposes; _on_figure_changed/_redraw_measures
            # keep it in sync with whichever page is current.
            self.stack.setMinimumSize(*_min_canvas_size(next(iter(self.figures.values()))))

        if "measures" in self.figures:
            self.customize_box = self._build_customize_box()
            layout.addWidget(self.customize_box)
            self.customize_box.setVisible(self.combo.currentData() == "measures")
        else:
            self.customize_box = None

        row = QHBoxLayout()
        self.btn_export = QPushButton("Export Plot")
        self.btn_export.clicked.connect(self._export)
        row.addWidget(self.btn_export)
        row.addStretch(1)
        layout.addLayout(row)

        if self.figures:
            self.e_title.setText(figure_title_text(next(iter(self.figures.values()))))
        else:
            self.combo.setEnabled(False)
            self.btn_export.setEnabled(False)

    def _build_customize_box(self):
        box = QGroupBox("Customize")
        outer = QVBoxLayout(box)

        row0 = QHBoxLayout()
        row0.addWidget(QLabel("Measure:"))
        self.combo_measure = QComboBox()
        self.combo_measure.addItem("All (grid)", userData=None)
        for m in self.results.spec.metrics:
            self.combo_measure.addItem(METRIC_LABELS.get(m, m), userData=m)
        self.combo_measure.currentIndexChanged.connect(self._redraw_measures)
        row0.addWidget(self.combo_measure)
        row0.addStretch(1)
        outer.addLayout(row0)

        row1 = QHBoxLayout()
        self.chk_samples = QCheckBox("Show individual data points")
        self.chk_samples.setChecked(self.measure_options.show_samples)
        self.chk_samples.stateChanged.connect(self._redraw_measures)
        row1.addWidget(self.chk_samples)
        self.chk_box = QCheckBox("Show box && whisker")
        self.chk_box.setChecked(self.measure_options.show_box)
        self.chk_box.stateChanged.connect(self._redraw_measures)
        row1.addWidget(self.chk_box)
        row1.addStretch(1)
        outer.addLayout(row1)

        row2 = QHBoxLayout()
        self.chk_legend = QCheckBox("Show legend")
        self.chk_legend.setChecked(self.measure_options.legend_visible)
        self.chk_legend.stateChanged.connect(self._redraw_measures)
        row2.addWidget(self.chk_legend)
        row2.addWidget(QLabel("Position:"))
        self.combo_legend_pos = QComboBox()
        for value, text in _LEGEND_POSITION_LABELS.items():
            self.combo_legend_pos.addItem(text, userData=value)
        self.combo_legend_pos.currentIndexChanged.connect(self._redraw_measures)
        row2.addWidget(self.combo_legend_pos)
        row2.addStretch(1)
        outer.addLayout(row2)

        outer.addWidget(QLabel("Bar labels — rename a marker, or give two the same name to combine them into one bar:"))
        markers = list(self.results.spec.markers)
        self.table_labels = QTableWidget(len(markers), 2)
        self.table_labels.setHorizontalHeaderLabels(["Marker", "Shown as"])
        self.table_labels.verticalHeader().setVisible(False)
        self.table_labels.setMaximumHeight(28 * min(len(markers), 5) + 30)
        for row, marker in enumerate(markers):
            name_item = QTableWidgetItem(marker)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table_labels.setItem(row, 0, name_item)
            self.table_labels.setItem(row, 1, QTableWidgetItem(marker))
        self.table_labels.itemChanged.connect(self._redraw_measures)
        outer.addWidget(self.table_labels)

        caption = QLabel("Combined (pooled) bars have no significance bracket — the model was fit "
                          "on the original markers, not on whatever groups renaming creates here.")
        caption.setStyleSheet("color: gray;")
        caption.setWordWrap(True)
        outer.addWidget(caption)
        return box

    def _on_figure_changed(self, index):
        key = self.combo.currentData()
        self.stack.setCurrentIndex(index)
        self.stack.setMinimumSize(*_min_canvas_size(self.figures[key]))
        if self.customize_box is not None:
            self.customize_box.setVisible(key == "measures")
        self.e_title.setText(self._custom_titles.get(key) or figure_title_text(self.figures[key]))
        self._propagate_size_change()

    def _on_title_edited(self):
        key = self.combo.currentData()
        if key is None:
            return
        text = self.e_title.text()
        self._custom_titles[key] = text
        set_figure_title_text(self.figures[key], text)
        self.canvases[key].draw()

    def _redraw_measures(self, *_args):
        self.measure_options = MeasuresDisplayOptions(
            show_samples=self.chk_samples.isChecked(),
            show_box=self.chk_box.isChecked(),
            marker_labels={
                self.table_labels.item(row, 0).text(): self.table_labels.item(row, 1).text()
                for row in range(self.table_labels.rowCount())
            },
            legend_visible=self.chk_legend.isChecked(),
            legend_position=self.combo_legend_pos.currentData(),
        )
        new_fig = build_measures_figure(self.results, self.measure_options, measure=self.combo_measure.currentData())
        custom_title = self._custom_titles.get("measures")
        if custom_title is not None:
            set_figure_title_text(new_fig, custom_title)
        self.e_title.setText(custom_title or figure_title_text(new_fig))
        self.figures["measures"] = new_fig
        old_canvas = self.canvases["measures"]
        index = self.stack.indexOf(old_canvas)
        new_canvas = FigureCanvasQTAgg(new_fig)
        self.stack.insertWidget(index, new_canvas)
        self.stack.removeWidget(old_canvas)
        old_canvas.deleteLater()
        self.canvases["measures"] = new_canvas
        self.stack.setCurrentIndex(index)
        self.stack.setMinimumSize(*_min_canvas_size(new_fig))  # re-sized, e.g. All (grid) <-> one measure
        self._propagate_size_change()
        new_canvas.draw()

    def _propagate_size_change(self):
        """The stack's new minimum size (above) only reaches the dialog's own minimumSizeHint if
        every widget in between is told its geometry may have changed — a plain setMinimumSize()
        on the stack does NOT bubble that up through the QTabWidget on its own (verified: without
        this, the dialog's minimumSizeHint stays frozen at whatever the first non-default page
        needed, even after switching to a much smaller or much larger one)."""
        self.updateGeometry()
        parent = self.parentWidget()
        while parent is not None:
            parent.updateGeometry()
            parent = parent.parentWidget()

    def _export(self):
        key = self.combo.currentData()
        fig = self.figures[key]
        ts = datetime.now().strftime("%H%M%S")
        # dest_dir always wins (see context.export_file) — this always lands next to the run's own
        # auto-saved figure_<key>.png/.pdf, whatever Options -> Output folder currently says, so the
        # filter string below (which would only matter for a save dialog) never actually gets used.
        export_file(
            self.ctx, self, "Export Figure", f"figure_{key}_{ts}.png",
            "PNG Image (*.png);;PDF Document (*.pdf);;SVG Vector (*.svg)",
            lambda path: fig.savefig(path, dpi=300, bbox_inches="tight"),
            dest_dir=self.group_dir,
        )


class GroupResultsDialog(QDialog):
    def __init__(self, parent, ctx, results, group_dir):
        super().__init__(parent)
        self.ctx = ctx
        self.results = results
        self.group_dir = group_dir
        self.setWindowTitle(f"Group analysis: {results.spec.group_name}")
        fit_to_screen(self, 1080, 820)

        layout = QVBoxLayout(self)
        n_warn = sum(1 for n in results.notes if n["level"] == "warning")
        head = f"Saved in {group_dir}"
        if n_warn:
            head += f"  -  {n_warn} warning{'s' if n_warn != 1 else ''} (under NOTES in the Report tab)"
        lbl = QLabel(head)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color: gray;")
        layout.addWidget(lbl)

        self.tabs = QTabWidget()
        self.tabs.addTab(_ReportTab(ctx, results), "Report")
        self.tabs.addTab(_FiguresTab(ctx, results, group_dir), "Figures")
        layout.addWidget(self.tabs, stretch=1)

        row = QHBoxLayout()
        btn_open = QPushButton("Open folder")
        btn_open.clicked.connect(self._open)
        row.addWidget(btn_open)
        row.addStretch(1)
        btn_close = QPushButton("Close")
        btn_close.setDefault(True)
        btn_close.clicked.connect(self.accept)
        row.addWidget(btn_close)
        layout.addLayout(row)

    def _open(self):
        try:
            open_folder(self.group_dir)
        except Exception as e:
            show_error(self.ctx, f"Could not open the folder: {e}")

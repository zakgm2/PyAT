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
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QStackedWidget, QTabWidget, QVBoxLayout, QWidget,
)

import PhysicsLibrary as pl

from ...context import export_file
from ...toasts import show_error, show_window_toast
from ...window_fit import fit_to_screen
from .plots import build_all_figures

_FIGURE_LABELS = {"traces": "Mean traces", "measures": "Measures by marker", "diagnostics": "Model diagnostics"}


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
    gets its own canvas, built once and kept (switching tabs back and forth doesn't rebuild it)."""

    def __init__(self, ctx, results, group_dir):
        super().__init__()
        self.ctx = ctx
        self.results = results
        self.group_dir = group_dir
        self.figures = build_all_figures(results)

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Figure:"))
        self.combo = QComboBox()
        for key in self.figures:
            self.combo.addItem(figure_label(key), userData=key)
        self.combo.currentIndexChanged.connect(lambda i: self.stack.setCurrentIndex(i))
        top.addWidget(self.combo, stretch=1)
        layout.addLayout(top)

        self.stack = QStackedWidget()
        self.canvases = {}
        for key, fig in self.figures.items():
            canvas = FigureCanvasQTAgg(fig)
            canvas.setMinimumHeight(420)
            self.canvases[key] = canvas
            self.stack.addWidget(canvas)
        layout.addWidget(self.stack, stretch=1)

        row = QHBoxLayout()
        self.btn_export = QPushButton("Export Plot")
        self.btn_export.clicked.connect(self._export)
        row.addWidget(self.btn_export)
        row.addStretch(1)
        layout.addLayout(row)

        if not self.figures:
            self.combo.setEnabled(False)
            self.btn_export.setEnabled(False)

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

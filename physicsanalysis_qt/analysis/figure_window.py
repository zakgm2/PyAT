"""
analysis/figure_window.py
-------------------------
The window for a figure drawn from a finished analysis's tables (Open Results…): the figure, where its numbers are, Export Plot (the Export Figure
dialog, the file landing beside the numbers it was drawn from) and Close.
"""

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ..app.toasts import show_error
from ..app.window_fit import fit_to_screen
from ..export.figure_export import export_figure
from .group.results_dialog import open_folder


class ResultsFigureDialog(QDialog):
    def __init__(self, parent, ctx, fig, name, directory):
        super().__init__(parent)
        self.ctx = ctx
        self.fig = fig
        self.directory = directory
        self.setWindowTitle(f"Results — {name}")
        fit_to_screen(self, 900, 700)

        layout = QVBoxLayout(self)
        head = QLabel(f"Read from {directory}")
        head.setWordWrap(True)
        head.setStyleSheet("color: gray;")
        layout.addWidget(head)
        self.canvas = FigureCanvasQTAgg(fig)
        layout.addWidget(self.canvas, stretch=1)

        row = QHBoxLayout()
        btn_open = QPushButton("Open folder")
        btn_open.clicked.connect(self._open)
        row.addWidget(btn_open)
        btn_export = QPushButton("Export Plot")
        btn_export.clicked.connect(self._export)
        row.addWidget(btn_export)
        row.addStretch(1)
        btn_close = QPushButton("Close")
        btn_close.setDefault(True)
        btn_close.clicked.connect(self.accept)
        row.addWidget(btn_close)
        layout.addLayout(row)

    def _export(self):
        # dest_dir always wins (see context.export_file): the picture lands beside the numbers it was drawn from
        export_figure(self.ctx, self.fig, "Results", parent=self, dest_dir=self.directory)

    def _open(self):
        try:
            open_folder(self.directory)
        except Exception as e:                                          # noqa: BLE001
            show_error(self.ctx, f"Could not open the folder: {e}")

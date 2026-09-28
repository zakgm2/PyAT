"""
loaders/pt2.py
----------------
Terranova Prospa EFNMR/MRI .pt2 image viewer.
"""

import datetime
import os

from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QLineEdit, QPushButton, QFileDialog

import PhysicsLibrary as pl

from ..context import export_file
from ..fonts import fig_font_sizes
from ..toasts import show_error
from ..window_fit import fit_to_screen


class PT2ViewerDialog(QDialog):
    def __init__(self, parent, ctx, path, img):
        super().__init__(parent)
        self.ctx = ctx
        self.path = path
        self.img = img
        self.setWindowTitle(f"EFNMR Image — {os.path.basename(path)}")
        fit_to_screen(self, 600, 660)
        layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Colormap:"))
        self.cmap_combo = QComboBox()
        self.cmap_combo.addItems(["viridis", "gray", "hot", "plasma", "bone", "inferno"])
        self.cmap_combo.currentTextChanged.connect(self._update_cmap)
        toolbar.addWidget(self.cmap_combo)

        toolbar.addWidget(QLabel("Title:"))
        default_title = os.path.splitext(os.path.basename(path))[0]
        self.title_edit = QLineEdit(default_title)
        self.title_edit.textChanged.connect(self._update_title)
        toolbar.addWidget(self.title_edit, stretch=1)

        btn_export = QPushButton("Export")
        btn_export.clicked.connect(self._export)
        toolbar.addWidget(btn_export)
        layout.addLayout(toolbar)

        self.fig2 = Figure(figsize=(5.5, 5.5), tight_layout=True)
        self.ax2 = self.fig2.add_subplot(111)
        self.im = self.ax2.imshow(img, cmap="viridis", origin="lower", aspect="equal")
        cbar = self.fig2.colorbar(self.im, ax=self.ax2, fraction=0.046, pad=0.04)
        self.tfs, self.lfs, _ = fig_font_sizes(self.fig2)
        cbar.set_label("Signal intensity (a.u.)", fontsize=self.lfs)
        self.ax2.set_title(default_title, fontsize=self.tfs, fontweight='bold')
        self.ax2.set_xlabel("Z (pixels)", fontsize=self.lfs)
        self.ax2.set_ylabel("Y (pixels)", fontsize=self.lfs)

        self.canvas2 = FigureCanvasQTAgg(self.fig2)
        layout.addWidget(self.canvas2)

    def _update_title(self, text):
        self.ax2.set_title(text, fontsize=self.tfs, fontweight='bold')
        self.canvas2.draw_idle()

    def _update_cmap(self, cmap_name):
        self.im.set_cmap(cmap_name)
        self.canvas2.draw_idle()

    def _export(self):
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M")
        name = f"{os.path.splitext(os.path.basename(self.path))[0]}_{ts}.png"
        export_file(self.ctx, self, "Export Image", name, "PNG (*.png);;PDF (*.pdf);;SVG (*.svg)",
                    lambda path: self.fig2.savefig(path, dpi=300, bbox_inches='tight'),
                    recording_type="PT2", recording_source=self.path)


def launch_pt2_viewer(ctx):
    start_dir = ctx.last_dir or ctx.settings["default_folder"]
    path, _ = QFileDialog.getOpenFileName(
        ctx.win, "Open EFNMR / MRI Image (.pt2)", start_dir,
        "Prospa 2D image (*.pt2);;All files (*.*)"
    )
    if not path:
        return
    ctx.last_dir = os.path.dirname(path)
    try:
        img = pl.load_pt2(path)
    except Exception as e:
        show_error(ctx, str(e))
        return
    dlg = PT2ViewerDialog(ctx.win, ctx, path, img)
    dlg.exec()

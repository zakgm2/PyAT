"""
loading/pt2.py
--------------
Terranova Prospa EFNMR/MRI .pt2 image viewer.
"""

import datetime
import os

from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QLineEdit, QPushButton, QFileDialog

from .. import figures
from ..app import errorlog
from ..backend.recordings import decode_arrays
from ..app.background import run_engine
from ..export.figure_export import export_figure
from ..app.toasts import show_error
from ..app.window_fit import fit_to_screen


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
        self.tfs, self.lfs, _ = figures.fig_font_sizes(self.fig2)
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
        export_figure(self.ctx, self.fig2, "PT2", parent=self, stem=f"{os.path.splitext(os.path.basename(self.path))[0]}_{ts}",
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
    errorlog.register_recording(path)
    errorlog.action("pt2_opened")

    def _show(answer):                                   # the engine read the file and handed the image over as an .npy file
        img = decode_arrays(answer["image"]["data"], answer["image"]["directory"], mmap=False)["image"]
        PT2ViewerDialog(ctx.win, ctx, path, img).exec()

    run_engine(ctx, "pt2.load", {"path": path}, _show, lambda message: show_error(ctx, message), label=f"Reading {os.path.basename(path)}")

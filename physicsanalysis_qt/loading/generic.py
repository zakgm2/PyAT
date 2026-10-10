"""
loading/generic.py
------------------
Generic tabular file loading (Excel/CSV/TSV/plain text) via
PyATCLI's sub-table detection, with a picker dialog for
table/X/Y column selection. Both steps run in the analysis engine
(backend/): the first reads the file and lists its tables (names, columns,
first rows — what the picker shows), the second opens the chosen table.
"""

import os

from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QLabel, QListWidget, QComboBox,
    QTextEdit, QPushButton, QFileDialog, QAbstractItemView,
)

from .common import open_recording
from ..app.background import run_engine
from ..app.toasts import show_error, show_window_toast
from ..app.window_fit import fit_to_screen


class GenericLoaderDialog(QDialog):
    """Table/column picker for the generic tabular parser. `tables` are the engine's descriptions of them:
    [{"name", "headers", "rows", "preview": [first rows, None for a missing value]}, ...]."""

    def __init__(self, parent, ctx, tables, path):
        super().__init__(parent)
        self.ctx = ctx
        self.tables = tables
        self.path = path
        self.current_table = None

        self.setWindowTitle(f"Generic Loader — {os.path.basename(path)}")
        fit_to_screen(self, 780, 540)
        layout = QHBoxLayout(self)

        # Left: table list
        left = QVBoxLayout()
        left.addWidget(QLabel("Detected tables:"))
        self.tbl_list = QListWidget()
        self.tbl_list.addItems([t["name"] for t in tables])
        self.tbl_list.currentRowChanged.connect(self._on_table_select)
        left.addWidget(self.tbl_list)
        layout.addLayout(left, stretch=1)

        # Right: column pickers + preview
        right = QVBoxLayout()

        xrow = QHBoxLayout()
        xrow.addWidget(QLabel("X:"))
        self.x_combo = QComboBox()
        xrow.addWidget(self.x_combo, stretch=1)
        right.addLayout(xrow)

        right.addWidget(QLabel("Y (multi-select):"))
        self.y_list = QListWidget()
        self.y_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.y_list.setFixedHeight(120)
        right.addWidget(self.y_list)

        right.addWidget(QLabel("Preview:"))
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFontFamily("Consolas")
        right.addWidget(self.preview, stretch=1)

        btn_row = QHBoxLayout()
        btn_load = QPushButton("Load to Main Plot")
        btn_load.clicked.connect(self._do_load)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.reject)
        btn_row.addWidget(btn_load)
        btn_row.addWidget(btn_close)
        right.addLayout(btn_row)

        layout.addLayout(right, stretch=2)

        self.tbl_list.setCurrentRow(0)

    def _refresh_preview(self, t):
        lines = ["\t".join(t["headers"]), "-" * 60]
        for row in t["preview"]:
            lines.append("\t".join("—" if v is None else f"{v:.5g}" for v in row))
        self.preview.setPlainText("\n".join(lines))

    def _on_table_select(self, row):
        if row < 0:
            return
        t = self.tables[row]
        self.current_table = t

        self.x_combo.clear()
        self.x_combo.addItems(t["headers"])

        self.y_list.clear()
        self.y_list.addItems(t["headers"])
        for i in range(1, len(t["headers"])):
            self.y_list.item(i).setSelected(True)

        self._refresh_preview(t)

    def _do_load(self):
        t = self.current_table
        if t is None:
            return
        y_indices = [self.y_list.row(item) for item in self.y_list.selectedItems()]
        if not y_indices:
            show_error(self.ctx, "Select at least one Y column.")
            return

        x_idx = self.x_combo.currentIndex()
        if x_idx < 0:
            x_idx = 0

        # A fresh load starts clean (stale splice, undo history): loading/common.py. The engine replays the
        # saved splices and puts the saved markers, highlights and text boxes on, in that order.
        headers = t["headers"]
        ctx, name = self.ctx, t["name"]
        self.accept()
        open_recording(ctx, self.path, label=f"Loading {name}",
                       load={"table": name, "x_column": headers[x_idx], "y_columns": [headers[i] for i in y_indices]},
                       after=lambda opened: show_window_toast(ctx, f"Loaded: {name}"))


def launch_generic_file_loader(ctx):
    start_dir = ctx.last_dir or ctx.settings["default_folder"]
    path, _ = QFileDialog.getOpenFileName(
        ctx.win, "Open Any Tabular File", start_dir,
        "All tabular (*.xlsx *.xls *.csv *.tsv *.txt *.dat);;Excel (*.xlsx *.xls);;"
        "CSV / TSV (*.csv *.tsv);;Text / data (*.txt *.dat);;All files (*.*)"
    )
    if not path:
        return
    ctx.last_dir = os.path.dirname(path)
    _load_generic_path(ctx, path)


def reload_generic(ctx, path):
    """Re-run the load for a file already on disk — no file dialog, used
    by the toolbar's Reload button. Still shows the table/column picker
    (sub-tables or columns may have changed since the file was edited),
    just skips re-choosing which file to open."""
    _load_generic_path(ctx, path)


def _load_generic_path(ctx, path):
    def _on_success(found):
        if not found["tables"]:
            show_error(ctx, "No usable tabular data found in this file.")
            return
        dlg = GenericLoaderDialog(ctx.win, ctx, found["tables"], path)
        dlg.exec()

    def _on_error(msg):
        show_error(ctx, f"Could not parse file:\n{msg}")

    # Parsing runs in the engine (so a big spreadsheet doesn't freeze the window) with a progress toast;
    # the table/column picker opens afterwards.
    run_engine(ctx, "file.tables", {"path": path}, _on_success, _on_error, label=f"Reading {os.path.basename(path)}")

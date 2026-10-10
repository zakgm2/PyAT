"""
loading/oxysoft.py
------------------
Oxysoft / Artinis NIRS .txt export loading. Native dataset events are
populated automatically as markers.
"""

import os

from PyQt6.QtWidgets import QFileDialog

from .common import open_recording
from ..app.toasts import show_window_toast


def open_file(ctx):
    start_dir = ctx.last_dir or ctx.settings["default_folder"]
    path, _ = QFileDialog.getOpenFileName(
        ctx.win, "Open Data File", start_dir,
        "All supported (*.txt *.csv *.tsv);;Text files (*.txt);;CSV files (*.csv);;All files (*.*)"
    )
    if path:
        ctx.last_dir = os.path.dirname(path)
        _load_single_file(ctx, path)


def reload_file(ctx, file_path):
    """Re-run the load for a file already on disk — no file dialog, used
    by the toolbar's Reload button to re-read the currently loaded
    Oxysoft file from scratch instead of asking the user to pick it again."""
    _load_single_file(ctx, file_path)


def _load_single_file(ctx, file_path):
    # The engine reads the export, replays the saved splices and puts the saved markers, highlights and
    # text boxes on (loading/common.py); native dataset events are already markers in what it hands back.
    # No 'signals' map here — the Plot dropdown hides itself.
    open_recording(ctx, file_path, label="Loading Oxysoft file",
                   after=lambda opened: show_window_toast(ctx, f"File: {os.path.basename(file_path)}"))

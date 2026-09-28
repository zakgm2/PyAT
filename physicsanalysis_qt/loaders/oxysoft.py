"""
loaders/oxysoft.py
--------------------
Oxysoft / Artinis NIRS .txt export loading. Native dataset events are
populated automatically as markers.
"""

import os

import numpy as np
from PyQt6.QtWidgets import QFileDialog

import PhysicsLibrary as pl

from ..background import run_in_background
from ..sidecar import load_markers_from_sidecar
from ..analysis.splice import load_splice_from_sidecar
from ..plot_signal import refresh_plot_signal_options
from ..toasts import show_error, show_window_toast


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
    from ..plotting import simple_plot

    def _work(progress):
        return pl.load_dataset_file(file_path, progress=progress)

    def _on_success(ds):
        n_ch = ds.metadata.get('n_channels', ds.num_channels // 2)
        o2hb = ds.signals[:n_ch]
        hhb = ds.signals[n_ch:]
        # A stale splice from whatever was loaded before this must not
        # carry over — see loaders/tdt.py's identical reset for why.
        ctx.original_cache = None
        ctx._active_splices = []
        ctx._data_generation += 1
        ctx.cache = {
            'source':          'Oxysoft',
            'source_path':     file_path,
            'store':           ds.folder_name,
            'x':               np.arange(ds.num_samples) / ds.sample_rate,
            'o2hb':            o2hb,
            'hhb':             hhb,
            'fs':              ds.sample_rate,
            'fit_factor_mean': ds.metadata.get('fit_factor_mean'),
            'detected_markers': [
                {"time": ev["sample"] / ds.sample_rate, "label": ev["label"],
                 "color": "black", "store": "Events"}
                for ev in ds.events
            ],
            'markers': [],
        }
        if 'thb' in ds.metadata:
            ctx.cache['thb'] = ds.metadata['thb']

        # Splice must replay before markers load — see loaders/tdt.py's
        # identical ordering and its comment for why.
        load_splice_from_sidecar(ctx)
        load_markers_from_sidecar(ctx)
        refresh_plot_signal_options(ctx)  # no 'signals' map here — hides the Plot dropdown
        simple_plot(ctx)
        show_window_toast(ctx, f"File: {os.path.basename(file_path)}")

    def _on_error(msg):
        show_error(ctx, msg)

    run_in_background(ctx, _work, _on_success, _on_error, label="Loading Oxysoft file")

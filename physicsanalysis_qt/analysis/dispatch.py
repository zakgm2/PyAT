"""
analysis/dispatch.py
----------------------
Routes double-clicks on the main plot to the right analysis window, and
the shared figure-export helper used by all of them. get_window() (the
pre/post seconds around a clicked event) lives in window_settings.py
alongside the toolbar button + dialog that configure it.
"""

import csv
import datetime

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QPushButton

from ..app import errorlog
from ..context import export_file
from ..export.figure_export import export_figure
from ..app.toasts import show_error, show_window_toast
from .analysis_picker import disarm_analysis
from .window_settings import get_window  # noqa: F401 — re-exported: existing callers import get_window from here


def export_figure_to_file(ctx, fig_obj, default_prefix, tracking_info="", provenance=None):
    """An analysis window's Export Plot: the Export Figure dialog (format, resolution, editable titles and
    labels, a data CSV beside the figure — see export/figure_export.py), then the figure."""
    export_figure(ctx, fig_obj, default_prefix, tracking_info, provenance=provenance)


def add_stats_export_buttons(ctx, parent, btn_row_layout, *, get_clipboard_text,
                              csv_default_name, csv_header, get_csv_rows, provenance=None):
    """Wires a "Copy" + "Export CSV" QPushButton pair into btn_row_layout,
    matching curve_fit.py's original _copy_params/_export_csv pattern —
    shared here so every stats-bearing analysis dialog (AUC, FFT, PETH,
    Event PETH, Peak Finder) gets identical Copy/Export-CSV behavior from
    one place instead of five near-copies of the same boilerplate that
    could silently drift apart.

    get_clipboard_text : () -> str, called when Copy is clicked.
    csv_default_name : str or () -> str, filename prefix for the save
        dialog's default name. A callable rather than a plain string lets
        a long-lived dialog (e.g. Event PETH, whose event selection can
        change after these buttons are built) resolve the current name at
        click time instead of baking in whatever it was when built.
    csv_header : list[str] or () -> list[str], written as the CSV's first
        row. A callable lets a caller whose column count varies at
        runtime (e.g. Event PETH's variable mean-time-bin columns)
        resolve the current header at click time, same reasoning as
        csv_default_name above.
    get_csv_rows : () -> list[list] or None/[], called when Export CSV is
        clicked; an empty/None result shows a "run it first" error instead
        of opening the save dialog.
    provenance : {"kind", "parameters"} describing the analysis, or a () -> that
        (resolved at click time, for a dialog whose settings can change); written
        beside the CSV as its provenance record — see context.export_file.

    Returns (btn_copy, btn_csv) in case a caller wants to reposition/
    restyle them beyond just having been appended to btn_row_layout.
    """
    def _copy():
        txt = get_clipboard_text()
        if not txt:
            return
        QApplication.clipboard().setText(txt)
        show_window_toast(ctx, "Copied to clipboard")

    def _write_csv(path, rows):
        header = csv_header() if callable(csv_header) else csv_header
        with open(path, 'w', newline='', encoding='utf-8') as fh:
            writer = csv.writer(fh)
            writer.writerow(header)
            writer.writerows(rows)

    def _export_csv():
        rows = get_csv_rows()
        if not rows:
            show_error(ctx, "Nothing to export yet — run the analysis first.")
            return
        name = csv_default_name() if callable(csv_default_name) else csv_default_name
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        export_file(
            ctx, parent, f"Export {name}", f"{name}_{ts}.csv",
            "CSV (*.csv);;Text (*.txt)", lambda path: _write_csv(path, rows),
            provenance=provenance() if callable(provenance) else provenance,
        )

    btn_copy = QPushButton("Copy")
    btn_copy.clicked.connect(_copy)
    btn_csv = QPushButton("Export CSV")
    btn_csv.clicked.connect(_export_csv)
    btn_row_layout.addWidget(btn_copy)
    btn_row_layout.addWidget(btn_csv)
    return btn_copy, btn_csv


def analysis_type(ctx, clicked_x):
    from .auc import launch_auc
    from .fft import launch_fft
    from .peth import launch_zscore_peth

    if clicked_x is None:
        return
    try:
        center_timestamp = float(clicked_x)
    except (ValueError, TypeError):
        show_error(ctx, "Invalid coordinate format captured.")
        return

    current_mode = ctx.analysis_mode
    if current_mode == "Curve Fit":
        show_window_toast(ctx, "In Curve Fit Mode: use single-clicks to anchor two points.")
        return

    # The dialogs below block via QDialog.exec() while this call is still
    # inside on_press's double-click handler. matplotlib dispatches
    # button_press_event to callbacks in registration order — ours runs
    # first, RectangleSelector's own handler runs second — so its handler
    # for this same press hasn't fired yet. Deactivating it now means that
    # pending dispatch is a no-op. Reactivating must NOT happen synchronously
    # in a `finally` here: that would still run before this function returns
    # control to matplotlib's dispatcher, so RectangleSelector's press handler
    # would immediately start a fresh drag with no release event left to end
    # it (the real release already got consumed inside the dialog's nested
    # event loop). Defer reactivation to the next Qt tick instead.
    pre, post = get_window(ctx)
    errorlog.action("analysis", tool=current_mode, center_s=center_timestamp, pre_s=pre, post_s=post)
    ctx.rect_selector.set_active(False)
    try:
        if current_mode is not None:
            # An armed tool is good for one run — disarm before its
            # (blocking) window opens, so the Analysis button is already
            # back to idle by the time it closes.
            disarm_analysis(ctx)
        if current_mode == "FFT":
            launch_fft(ctx, center_timestamp)
        elif current_mode == "Z-Score":
            launch_zscore_peth(ctx, center_timestamp)
        elif current_mode == "AUC":
            launch_auc(ctx, center_timestamp)
    finally:
        def _reactivate():
            ctx.rect_selector.clear()
            ctx.rect_selector.set_active(True)
        QTimer.singleShot(0, _reactivate)

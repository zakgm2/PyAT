"""
analysis/result_window.py
-------------------------
The window the click analyses (Z-Score, AUC, FFT) show their answer in. It used to be written out in each of them: the figure, the numbers
beside it as text, and the buttons under them — Copy and Export CSV (dispatch.add_stats_export_buttons), Export Plot (the Export Figure
dialog) and Done.

    run_click_analysis(ctx, center_t, name, kind, show)   asks the engine for the library's `kind` around the clicked time and calls
                                                          show(ctx, center_t, pre, post, result) with its tables when they come
    show_result_window(ctx, center_t, pre, post, ...)     opens the window for one answer
    report_label(text)                                    the framed, monospaced text the numbers are shown in (Curve Fit's too)

What differs between the three is what they draw and which numbers they print, so that is all each of them is left with.
"""

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ..app.toasts import show_window_toast
from ..app.window_fit import fit_to_screen
from .analysis_picker import add_done_button
from .dispatch import add_stats_export_buttons, export_figure_to_file, get_window
from .windows import request_analysis


def window_parameters(ctx, center_t, pre, post):
    """What a click analysis is asked for (and what its provenance records): the time clicked, the seconds either side, the signal on screen."""
    return {"center_s": float(center_t), "pre_s": float(pre), "post_s": float(post), "signal": ctx.plot_signal}


def run_click_analysis(ctx, center_t, name, kind, show):
    """Asks the engine for the analysis `kind` of the window around `center_t` (the Analysis button's window setting) and, when it answers,
    calls show(ctx, center_t, pre, post, result). `name` is what the progress toast calls it."""
    if ctx.cache is None:
        return
    pre, post = get_window(ctx)
    request_analysis(ctx, kind, window_parameters(ctx, center_t, pre, post),
                     lambda result: show(ctx, center_t, pre, post, result), label=f"{name} at {center_t:.1f}s")


def report_label(text=""):
    """The framed, monospaced, wrapping label an analysis window prints its numbers in."""
    label = QLabel(text)
    label.setFont(QFont("Consolas", 9))
    label.setWordWrap(True)
    label.setFrameShape(QFrame.Shape.Panel)
    label.setStyleSheet("background-color: white; color: black; padding: 8px;")
    return label


def show_result_window(ctx, center_t, pre, post, *, name, prefix, kind, fig, report, csv_header, csv_rows, title=None, report_first=False):
    """Opens the window (and waits for it to be closed).

    name        what the analysis is called in the toast ("Z-Score")
    prefix      the start of the CSV's and the figure's file name ("ZScore")
    kind        the library analysis it is, for the provenance record written beside each export
    fig         the library's figure for it
    report      the numbers, as the text shown beside the figure and copied by Copy
    csv_header  the columns Export CSV writes, and csv_rows() the rows
    title       the window's title if it is not `name`
    report_first  the text above the figure instead of below it
    """
    store = ctx.cache["store"]
    dlg = QDialog(ctx.win)
    dlg.setWindowTitle(f"{title or name} — {store}  |  centre {center_t:.1f}s  |  -{pre:.0f}s/+{post:.0f}s")
    fit_to_screen(dlg, 700, 650)
    layout = QVBoxLayout(dlg)

    label = report_label(report)
    canvas = FigureCanvasQTAgg(fig)
    if report_first:
        layout.addWidget(label)
        layout.addWidget(canvas, stretch=1)
    else:
        layout.addWidget(canvas)
        layout.addWidget(label)

    prov = {"kind": kind, "parameters": window_parameters(ctx, center_t, pre, post)}
    btn_row = QHBoxLayout()
    add_stats_export_buttons(
        ctx, dlg, btn_row,
        get_clipboard_text=lambda: label.text(),
        csv_default_name=f"{prefix}_{store}_{int(center_t)}s",
        csv_header=csv_header,
        get_csv_rows=csv_rows,
        provenance=prov,
    )
    btn_plot = QPushButton("Export Plot")
    btn_plot.clicked.connect(lambda: export_figure_to_file(ctx, fig, prefix, f"{int(center_t)}s", provenance=prov))
    btn_row.addWidget(btn_plot)
    add_done_button(ctx, dlg, btn_row)
    layout.addLayout(btn_row)

    show_window_toast(ctx, f"{name} computed at {center_t:.1f}s")
    dlg.exec()

"""
analysis/open_results.py
------------------------
Open Results…: look at a finished analysis again, from the files it left. The analysis engine reads them back (its results.open: the kind of
analysis, what it was asked, its tables, what it said) and the window draws them: a group analysis in its results window (report and figures),
any other in a window of its figure. Nothing is recomputed, and nothing needs the recording.

    open_results(ctx)               asks which file (a group's analysis_settings.json, a .provenance.json record or a .csv table) and opens it
    open_results(ctx, path)         opens that one (a folder works too)
    show_results(ctx, answer)       the window for what results.open answered
"""

import os

from PyQt6.QtWidgets import QFileDialog

from .. import figures
from ..backend.tables import read_tables
from ..context import get_export_dir
from ..app import errorlog
from ..app.background import run_engine
from ..app.toasts import show_error
from .group.run import results_from_tables

FILE_FILTER = ("Results (*.provenance.json analysis_settings.json *.csv);;Provenance records (*.provenance.json);;"
               "Group analysis settings (analysis_settings.json);;Tables (*.csv);;All files (*)")


def pick_results(ctx):
    """The file the person picks (starting in the output folder, where the results are), or None."""
    path, _filter = QFileDialog.getOpenFileName(ctx.win, "Open Results", get_export_dir(ctx), FILE_FILTER)
    return path or None


def open_results(ctx, path=None):
    path = path or pick_results(ctx)
    if not path:
        return
    errorlog.action("results_open_started")

    def _on_success(answer):
        try:
            show_results(ctx, answer)
        except Exception as e:                                          # noqa: BLE001 — tables that cannot be drawn are this action's failure
            _on_error(str(e))

    def _on_error(msg):
        show_error(ctx, f"Could not open {os.path.basename(path) or path}:\n{msg}")

    run_engine(ctx, "results.open", {"path": path, "tables": "files"}, _on_success, _on_error, label="Opening results")


def show_results(ctx, answer):
    """Opens the window for a results.open answer and waits for it to be closed."""
    from .figure_window import ResultsFigureDialog                      # (the windows are loaded when one is shown)
    from .group.results_dialog import GroupResultsDialog

    kind, directory = answer["kind"], answer["directory"]
    frames = read_tables(answer["tables"])
    errorlog.action("results_opened", kind=kind or "table", n_tables=len(frames))
    if kind == "group_analysis":
        results = results_from_tables(frames, answer["parameters"], answer["notes"], answer["software"], answer["files"])
        GroupResultsDialog(ctx.win, ctx, results, directory).exec()
        return
    fig = figures.build_figure(frames, kind, answer["parameters"])
    ResultsFigureDialog(ctx.win, ctx, fig, os.path.basename(answer["path"]), directory).exec()

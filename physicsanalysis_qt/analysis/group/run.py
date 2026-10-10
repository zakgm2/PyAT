"""
analysis/group/run.py
-----------------------
The app's side of running a group analysis: ask the analysis engine to run it (with a progress toast),
and open the results when it finishes. The analysis itself — loading each recording, cutting and
measuring its trials, fitting the models, writing the tables, the report and the record — is
PyATCLI's group.run operation, which is headless and never draws, so a script can repeat any run from the
analysis_settings.json saved next to its results (`python -m PyATCLI group run`). The figures are the app's:
it draws them from the tables and saves them beside them (PNG and PDF, each with the data behind it).

The engine writes everything to the group's folder and hands the tables back as CSV files; the results
dialog needs them as a GroupResults to draw its figures from and to let the person restyle them, so they
are read and put back together here (the library's group.results_from_tables, through the backend).

Nothing here touches a widget except start_group_run's callbacks.
"""

import os

from ... import __version__
from ...backend import api
from ... import figures
from ...backend.tables import read_tables
from ...app import errorlog
from ...app.background import run_engine
from ...app.toasts import show_error, show_window_toast


def results_from_tables(frames, spec, notes, software, files):
    """The GroupResults for a group's tables ({name: DataFrame}) and the settings they were made with, with the notes and the software the
    analysis reported (which no table holds) and the files it wrote."""
    results = api.group.results_from_tables(frames, spec, notes=notes, software=software)
    if results is None:
        raise ValueError("these are not the tables of a group analysis: there are no mean traces or subject means to show")
    results.files = list(files)
    return results


def results_from_answer(answer):
    """The GroupResults a group.run answer describes: its tables read from the files the engine wrote."""
    return results_from_tables(read_tables(answer["table_data"]), answer["spec"], answer["note_records"], answer["software"], answer["files"])


def save_group_figures(drawn, group_dir):
    """The figures as the results window first draws them, saved beside the tables the engine wrote. Returns the files written ([] if they
    could not be: the analysis itself has finished, and the window still shows them)."""
    try:
        return list(figures.save_figures(drawn, group_dir, software=f"PyAT {__version__}"))
    except Exception:                                                  # noqa: BLE001 — a full disk or a locked file must not lose the results
        errorlog.error("Could not save the group analysis' figures", exc_info=True)
        return []


def start_group_run(ctx, spec, group_dir, scans=()):
    """Run the analysis in the engine (with a progress toast) and open the results when it finishes. The engine saves the settings first
    (analysis_settings.json in `group_dir`, with the digests of the `scans` the wizard was set up from), so a run that fails still leaves
    them."""
    errorlog.action("group_analysis_started", n_subjects=len(spec.subjects), n_markers=len(spec.markers),
                    n_measures=len(spec.metrics), regression_method=spec.regression_method, signal=spec.signal)

    def _on_success(answer):
        from .results_dialog import GroupResultsDialog
        try:
            results = results_from_answer(answer)
        except Exception as e:                                          # noqa: BLE001 — a table that cannot be read back is the run's failure
            _on_error(str(e))
            return
        dialog = GroupResultsDialog(ctx.win, ctx, results, group_dir)           # draws every figure once
        results.files += save_group_figures(dialog.figures, group_dir)
        n_notes = sum(1 for n in results.notes if n["level"] == "warning")
        errorlog.action("group_analysis_finished", n_files=len(results.files), n_warnings=n_notes)
        show_window_toast(ctx, f"Group analysis finished: results saved in {group_dir}"
                               + (f" ({n_notes} warning{'s' if n_notes != 1 else ''}, see the report)" if n_notes else ""),
                          duration=6000)
        dialog.exec()

    def _on_error(msg):
        show_error(ctx, f"The group analysis could not be completed:\n{msg}\n\nYour settings are saved in "
                        f"{os.path.join(group_dir, 'analysis_settings.json')}.")

    run_engine(ctx, "group.run", {"settings": spec.to_dict(), "out": group_dir, "tables": "files",
                                  "write_settings": True, "scans": list(scans)},
               _on_success, _on_error, label="Group analysis")

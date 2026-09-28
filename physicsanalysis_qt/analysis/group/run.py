"""
analysis/group/run.py
-----------------------
Runs a group analysis: each recording of the spec is loaded, its trials cut and measured, and the models fitted
on all of them together (PhysicsLibrary's extract_group_trials and fit_group_models); then the tables, the
report and the figures (plots.py) are written into the group's folder.

Recordings are handled one at a time and dropped again, so a large group never has more than one recording's
signal in memory. Nothing here touches a widget: it runs on a worker thread, reporting progress as it goes.
"""

import os

import pandas as pd

import PhysicsLibrary as pl
from PhysicsLibrary.analysis.group_trials import TRIAL_COLUMNS

from ...background import run_in_background
from ...toasts import show_error, show_window_toast
from .plots import build_all_figures, save_figures
from .recording import load_recording


def run_group_analysis(spec, out_dir=None, progress=None, load=load_recording):
    """
    The whole analysis for `spec` (a GroupSpec). If `out_dir` is given the results are written there.

    `load(folder, regression_method, store_labels, progress)` returns what recording.load_recording returns; it is
    a parameter so the analysis can be run on recordings that are not TDT blocks on disk (and so the tests can).
    Raises RuntimeError naming the subject if a recording cannot be loaded: leaving one out silently would change
    the group, so the person is told and can leave it out on purpose instead.

    Returns the GroupResults.
    """
    subjects = list(spec.subjects)
    stages = [(f"rec{i}", 1.0) for i in range(len(subjects))] + [("models", 1.5), ("writing", 0.3)]
    plan = pl.Plan(progress, stages)

    frames, traces, excluded, notes, grid = [], {}, {m: 0 for m in spec.markers}, [], None
    for i, s in enumerate(subjects):
        name, folder = s["subject"], s["folder"]
        report = plan.sub(f"rec{i}")

        def relay(fraction, message="", _name=name):
            if report is not None:
                report(fraction, f"{_name}: {message}" if message else _name)

        plan.begin(f"rec{i}", f"Loading {name} ({i + 1} of {len(subjects)})")
        try:
            data = load(folder, spec.regression_method, spec.store_labels, relay if report is not None else None)
        except Exception as e:
            raise RuntimeError(f"Could not load '{name}' ({folder}): {e}") from e
        out = pl.extract_group_trials(data["x"], data["y"], data["groups"], spec, subject=name, recording=folder)
        frames.append(out["trials"])
        traces[name] = out["traces"]
        grid = out["grid"]
        for marker, n in out["excluded"].items():
            excluded[marker] = excluded.get(marker, 0) + n
        for w in data.get("warnings", []):
            notes.append({"level": "warning", "measure": "", "text": f"{name}: {w}"})
        del data, out                                       # the signal is not needed again: free it before the next one

    plan.begin("models", "Fitting models")
    trials = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=TRIAL_COLUMNS)
    results = pl.fit_group_models(trials, spec, progress=plan.sub("models"), traces=traces, trace_grid=grid,
                                  excluded=excluded)
    results.notes = notes + results.notes

    if out_dir:
        plan.begin("writing", "Writing the tables and the report")
        results.files = pl.write_group_results(results, out_dir)
        figures = build_all_figures(results)
        results.files += save_figures(figures, out_dir)
        for fig in figures.values():
            fig.clf()                                       # release the Agg buffers now, not whenever GC gets to it
    plan.done()
    return results


def start_group_run(ctx, spec, group_dir):
    """Run the analysis in the background (with a progress toast) and open the results when it finishes."""
    def _work(progress):
        return run_group_analysis(spec, out_dir=group_dir, progress=progress)

    def _on_success(results):
        from .results_dialog import GroupResultsDialog
        n_notes = sum(1 for n in results.notes if n["level"] == "warning")
        show_window_toast(ctx, f"Group analysis finished: results saved in {group_dir}"
                               + (f" ({n_notes} warning{'s' if n_notes != 1 else ''}, see the report)" if n_notes else ""),
                          duration=6000)
        GroupResultsDialog(ctx.win, ctx, results, group_dir).exec()

    def _on_error(msg):
        show_error(ctx, f"The group analysis could not be completed:\n{msg}\n\nYour settings are saved in "
                        f"{os.path.join(group_dir, 'analysis_settings.json')}.")

    run_in_background(ctx, _work, _on_success, _on_error, label="Group analysis")

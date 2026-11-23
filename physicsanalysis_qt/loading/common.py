"""
loading/common.py
-----------------
What every way of opening a recording shares now that the reading happens in the analysis engine (backend/): ask it to open the
file, and when it has, make the recording the app's. The engine applies the recording's saved state itself (splices replayed, markers,
highlights, text boxes and signal names put on) — PyATCLI's load_recording, the same function a script calls — so a loader here
is only what is particular to its source.
"""

from ..app import errorlog
from ..backend import api
from ..backend.recordings import adopt, opened_from_wire
from ..app.background import run_engine
from ..plot.plot_signal import refresh_plot_signal_options
from ..app.toasts import show_error, show_window_toast
from ..ui import drop_overlay


def pipeline_settings(ctx):
    """The pipeline options chosen in Options ({"denoise.cutoff_hz": 8.0, ...}: only those that are not their default) that the library still has: one it
    renamed or removed since the choice was saved is left out, so an old settings file cannot make every load fail."""
    chosen = ctx.settings.get("pipeline") or {}
    if not chosen:
        return {}
    known = api.pipeline.describe()["defaults"]
    return {name: value for name, value in chosen.items() if name in known}


def open_recording(ctx, path, load=None, label="Loading", reset_signal=False, after=None, on_error=None):
    """Opens `path` (read from disk again, even if it was open before — Open and Reload both mean "what is on disk now") in the engine and
    makes it the loaded recording: the cache replaced, the splices and undo history reset, the plot redrawn.

    load          the engine's load options for the source (regression_method, table, x_column, y_columns). The pipeline options chosen in Options
                  go with them (as `pipeline`) unless the load names its own.
    reset_signal  start on the normalized signal, as a TDT load does (a previous dataset's pick may not exist here)
    after         after(opened) once it is on screen: the source's own toast, say
    on_error      on_error(message); the default is the error dialog

    Returns the engine request (or None if one is already running)."""
    from ..plot.plotting import simple_plot

    errorlog.register_recording(path)
    load = dict(load or {})
    if "pipeline" not in load and pipeline_settings(ctx):
        load["pipeline"] = pipeline_settings(ctx)

    def _on_success(wired):
        opened = opened_from_wire(wired)
        adopt(ctx, opened)
        ctx.recording_load = dict(load)
        errorlog.recording_loaded(ctx.cache)
        if reset_signal:
            ctx.plot_signal = "normalized"
        refresh_plot_signal_options(ctx)
        simple_plot(ctx)
        drop_overlay.refresh(ctx)                            # the card for the empty window goes away
        _tell_restored(ctx, opened)
        if after is not None:
            after(opened)
        if opened.warnings:                                  # a saved file that could not be read: the recording is shown without it
            show_error(ctx, "\n".join(opened.warnings))

    def _on_error(message):
        (on_error or (lambda m: show_error(ctx, m)))(message)

    return run_engine(ctx, "recording.open", {"path": path, "load": load, "fresh": True}, _on_success, _on_error, label=label)


def reconnect_recording(ctx):
    """The analysis engine was ended to stop a task (the progress toast's Cancel / Stop now), and the copy of the recording on screen that it held went
    with it: opens the same file again in the new engine, so analyses go on working without a Reload. Nothing on screen changes and nothing unsaved is
    lost — the window keeps its plot, and its markers, splices, highlights and signal names are sent with every request — only the engine's own copy is
    made again. If that is cancelled or fails, the recording stays on screen and asks for a Reload when an analysis needs the engine."""
    path = (ctx.cache or {}).get("source_path")
    if ctx.cache is None or ctx.recording_id is None or not path:
        return
    ctx.recording_generation = None                           # until it is back, a request says so instead of asking an engine that does not have it
    ctx._reconnecting = True
    load = dict(ctx.recording_load or {})
    if ctx.cache.get("source") == "TDT":
        load.setdefault("regression_method", ctx.recording_method)
    if ctx.recording_pipeline:
        load["pipeline"] = dict(ctx.recording_pipeline)            # what is on screen was made with these, saved or not

    def _on_success(wired):
        ctx._reconnecting = False
        ctx.recording_id = wired["id"]
        ctx.recording_generation = ctx.engine.generation
        show_window_toast(ctx, "Reconnected to the recording")

    def _on_failure(error):
        ctx._reconnecting = False
        if error.cancelled:
            show_window_toast(ctx, "Not reconnected: use Reload when you want to analyse this recording again")
        else:
            show_error(ctx, f"The recording could not be reconnected to the analysis engine:\n{error}\n\nUse Reload to open it again.")

    run_engine(ctx, "recording.open", {"path": path, "load": load, "fresh": False}, _on_success, label="Reconnecting to the recording", on_failure=_on_failure)


def reopen_current(ctx, after=None, on_error=None):
    """Reads the loaded recording from disk again, processed with the pipeline options chosen in Options (open_recording adds them) and the motion-correction
    method set there, opened the way it was otherwise (a table's columns, so there is no picker to answer again): Reload for any source, for when the options
    changed. What was not saved with Save Changes is not kept, as with Reload. `after(opened)` and `on_error(message)` are open_recording's. Returns the
    engine request (None if one is already running, or nothing is loaded)."""
    path = (ctx.cache or {}).get("source_path")
    if not path:
        return None
    load = {k: v for k, v in dict(ctx.recording_load or {}).items() if k != "pipeline"}
    if ctx.cache.get("source") == "TDT":
        load["regression_method"] = ctx.settings.get("regression_method", "ols")
    return open_recording(ctx, path, load=load, label="Applying the pipeline options", after=after, on_error=on_error)


def _tell_restored(ctx, opened):
    """The toasts a load of a recording with saved changes has always shown (each replaces the one before; the last one stays)."""
    n = opened.restored.get("splices") or 0
    if n:
        show_window_toast(ctx, f"Restored {n} splice{'s' if n != 1 else ''}")
    if opened.restored.get("markers") is not None:
        show_window_toast(ctx, f"Markers restored ({opened.restored['markers']})")

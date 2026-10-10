"""
loading/common.py
-----------------
What every way of opening a recording shares now that the reading happens in the analysis engine (backend/): ask it to open the
file, and when it has, make the recording the app's. The engine applies the recording's saved state itself (splices replayed, markers,
highlights, text boxes and signal names put on) — PyATCLI's load_recording, the same function a script calls — so a loader here
is only what is particular to its source.
"""

from ..app import errorlog
from ..backend.recordings import adopt, opened_from_wire
from ..app.background import run_engine
from ..plot.plot_signal import refresh_plot_signal_options
from ..app.toasts import show_error, show_window_toast


def open_recording(ctx, path, load=None, label="Loading", reset_signal=False, after=None, on_error=None):
    """Opens `path` (read from disk again, even if it was open before — Open and Reload both mean "what is on disk now") in the engine and
    makes it the loaded recording: the cache replaced, the splices and undo history reset, the plot redrawn.

    load          the engine's load options for the source (regression_method, table, x_column, y_columns)
    reset_signal  start on the normalized signal, as a TDT load does (a previous dataset's pick may not exist here)
    after         after(opened) once it is on screen: the source's own toast, say
    on_error      on_error(message); the default is the error dialog

    Returns the engine request (or None if one is already running)."""
    from ..plot.plotting import simple_plot

    errorlog.register_recording(path)

    def _on_success(wired):
        opened = opened_from_wire(wired)
        adopt(ctx, opened)
        errorlog.recording_loaded(ctx.cache)
        if reset_signal:
            ctx.plot_signal = "normalized"
        refresh_plot_signal_options(ctx)
        simple_plot(ctx)
        _tell_restored(ctx, opened)
        if after is not None:
            after(opened)
        if opened.warnings:                                  # a saved file that could not be read: the recording is shown without it
            show_error(ctx, "\n".join(opened.warnings))

    def _on_error(message):
        (on_error or (lambda m: show_error(ctx, m)))(message)

    return run_engine(ctx, "recording.open", {"path": path, "load": load or {}, "fresh": True}, _on_success, _on_error, label=label)


def _tell_restored(ctx, opened):
    """The toasts a load of a recording with saved changes has always shown (each replaces the one before; the last one stays)."""
    n = opened.restored.get("splices") or 0
    if n:
        show_window_toast(ctx, f"Restored {n} splice{'s' if n != 1 else ''}")
    if opened.restored.get("markers") is not None:
        show_window_toast(ctx, f"Markers restored ({opened.restored['markers']})")

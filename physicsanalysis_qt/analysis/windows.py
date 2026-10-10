"""
analysis/windows.py
---------------------
What the click-triggered analysis windows (Z-Score, AUC, FFT, Curve Fit) and Measure Intervals share now that the analysis itself is the
analysis engine's. Each of them used to pick the recording's channels, smooth the whole signal and compute right here on the window's thread;
now it asks the engine for the library's `run` operation (the same analysis a script or `python -m PyATCLI run` gives, whose tables
are what the window exports) and draws from the tables that come back.

    request_analysis(ctx, kind, parameters, on_result, label)   ask for it; on_result(result) is called with the tables when it is done
    channel_colors(ctx)                                         the colour each channel of the loaded recording is drawn in
    channel_groups(table)                                       [(channel, its rows)] in the order the channels appear
    column(table, name)                                         a table column as floats (a missing value is NaN)

The window opens when the answer arrives, not before; if the recording was replaced meanwhile (another file opened, a splice applied) the answer
is for a recording that is no longer on screen and is dropped with a toast rather than shown against the wrong one.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..backend.errors import BackendError
from ..backend.recordings import recording_ref
from ..app.background import run_engine
from ..context import get_active_signal
from ..app.toasts import show_error, show_window_toast

OXYSOFT_COLORS = {"Mean O2Hb": "#CC0000", "Mean HHb": "#0033CC", "Mean tHb": "#228B22"}
GENERIC_COLOR = "#2196F3"
UNKNOWN_COLOR = "#555555"


@dataclass
class WindowResult:
    """What the engine answered for one analysis: its tables (DataFrames, by name), summary and notes."""
    tables: dict = field(default_factory=dict)
    summary: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)


def tables_from_answer(answer):
    """{name: DataFrame} from a `run` answer asked with tables="inline" ({"columns", "rows", "data": {column: [values]}})."""
    return {name: pd.DataFrame(t["data"], columns=t["columns"]) for name, t in (answer.get("tables") or {}).items()}


def column(table, name):
    """A table column as a float array: a missing value (JSON null) is NaN."""
    return np.asarray(table[name].tolist(), dtype=float)


def channel_groups(table, key="Channel"):
    """[(channel, its rows)] in the order the channels first appear."""
    return [(name, rows) for name, rows in table.groupby(key, sort=False)]


def channel_colors(ctx):
    """{channel label: colour} for the loaded recording, as the windows have always drawn them: Oxysoft's mean channels in their fixed colours,
    a TDT recording's active signal (the one the Plot menu was last ticked on) in its own, a generic file's first column in blue."""
    cache = ctx.cache
    if cache.get("source") == "Oxysoft":
        return dict(OXYSOFT_COLORS)
    if "corr" in cache or "raw" in cache:
        _, label, _, color = get_active_signal(ctx)
        return {label: color}
    return {"Signal": GENERIC_COLOR}


def request_analysis(ctx, kind, parameters, on_result, label=None, on_error=None):
    """Asks the engine to run the analysis `kind` on the loaded recording as it is now (its splices, the window's markers and signal names) and
    calls on_result(WindowResult) when it has. A failure goes to on_error(message) — the error box by default. Returns the engine request, or
    None if nothing was started (the engine was busy, or this recording is not one the engine holds)."""
    try:
        ref = recording_ref(ctx)
    except BackendError as e:
        show_error(ctx, str(e))
        return None
    token = (ctx._data_generation, ctx.recording_id)

    def _on_success(answer):
        if (ctx._data_generation, ctx.recording_id) != token:
            show_window_toast(ctx, "The recording changed while the analysis ran — run it again.")
            return
        on_result(WindowResult(tables_from_answer(answer), answer.get("summary") or {}, answer.get("notes") or []))

    def _on_error(message):
        (on_error or (lambda m: show_error(ctx, m)))(message)

    return run_engine(ctx, "run", {"kind": kind, "recording": ref, "parameters": parameters, "store_labels": dict(ctx.store_labels),
                                   "tables": "inline"}, _on_success, _on_error, label=label)

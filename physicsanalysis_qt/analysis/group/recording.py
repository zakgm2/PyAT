"""
analysis/group/recording.py
------------------------------
Loads one recording for group analysis exactly the way the single-recording analyses see it, without a
window: TDT block processed to dF/F, the recording's saved splices replayed (Cut Out re-fits the dF/F, as
in the app), its saved markers put on top, and the events grouped by name with Event PETH's own grouping.
The signal handed back is the normalized dF/F, the trace every analysis dialog uses.

Nothing here touches a widget, so it runs on a worker thread.
"""

from types import SimpleNamespace

import PhysicsLibrary as pl

from ...context import get_normalized_signal
from ...loaders.tdt import _build_signal_options
from ..event_peth import _group_markers_by_name
from ..splice import _splice_once
from .scan import read_saved_markers, read_saved_splices


def load_recording(folder, regression_method="ols", store_labels=None, progress=None):
    """
    Returns a dict with
        x, y      the time axis and the normalized dF/F after any saved splices
        fs        sampling rate in Hz
        groups    {marker name: sorted event times}, as Event PETH lists them
        n_splices how many saved splices were applied
        warnings  saved files that could not be read (the recording is then used without them)
    Raises ValueError if the folder is not a readable TDT block.
    """
    plan = pl.Plan(progress, [("Reading and processing", 8), ("Applying saved splices", 2)])
    valid, message = pl.validate_tdt_folder(folder)
    if not valid:
        raise ValueError(message)
    warnings = []

    result = pl.process_tdt_folder(folder, regression_method=regression_method,
                                   progress=plan.sub("Reading and processing"))
    cache = {
        "source": "TDT", "source_path": folder,
        "x": result["x"], "raw": result["raw"], "corr": result["corr"], "fs": result["fs"],
        "detected_markers": result.get("markers", []), "markers": [],
        "signals": _build_signal_options(result),
    }

    splices = []
    try:
        splices = read_saved_splices(folder)
    except Exception as e:
        warnings.append(f"Saved splices could not be read ({e}); the recording is used as recorded.")
    n_applied = 0
    if splices:
        steps = pl.Plan(plan.sub("Applying saved splices"), [(f"splice{i}", 1) for i in range(len(splices))])
        for i, s in enumerate(splices):
            steps.begin(f"splice{i}", f"Applying saved splice {i + 1} of {len(splices)}")
            spliced = _splice_once(cache, s["mode"], s["start"], s["end"], regression_method=regression_method,
                                   progress=steps.sub(f"splice{i}"))
            if spliced is not None:                          # a splice that leaves too little is skipped, as in the app
                cache = spliced
                n_applied += 1
        steps.done()
    plan.done()

    try:
        cache["markers"] = read_saved_markers(folder)        # the saved markers replace the (empty) list, after the splices
    except Exception as e:
        warnings.append(f"Saved markers could not be read ({e}); only the recorded events are used.")

    shim = SimpleNamespace(cache=cache, store_labels=dict(store_labels or {}))
    _key, _label, y, _color = get_normalized_signal(shim)
    return {"x": cache["x"], "y": y, "fs": cache["fs"], "groups": _group_markers_by_name(shim),
            "n_splices": n_applied, "warnings": warnings}

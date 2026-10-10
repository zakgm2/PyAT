"""
export/export_provenance.py
---------------------------
The provenance record every export gets, written beside it as <export name>.provenance.json: the software
that made it, the recording it came from (its files' fingerprint, motion-correction method, every splice,
store renames, signal names), what the pipeline does that nobody chose (filter cutoff, smoothing window,
z-score baseline rule) and the parameters of the analysis itself. The layout and what it promises are
PyATCLI's (provenance.py); with the record and the recording, `python -m PyATCLI reproduce <record>`
runs the analysis again without the app and checks the numbers against the export.

The analysis engine writes it (its provenance.write operation): fingerprinting a recording means reading and
hashing the small files of its folder, which may be on a network drive. The request goes out when the export
has been written and nothing waits for it.

Called from context.export_file(), the one function every export goes through, so nothing that exports can
forget to. An analysis dialog describes what it ran as {"kind": <an analyses.py kind>, "parameters": {...}}; an
export that is not a replayable analysis (a screenshot of the plot, the PT2 viewer) gets a record of the
recording and the software only. Turned off by Options -> "Save a provenance record beside every export".
"""

from ..app import errorlog
from ..backend.errors import BackendError
from ..backend.recordings import recording_ref
from ..app.background import run_engine


def regression_method(ctx):
    """The motion-correction method the loaded recording was opened with (TDT only)."""
    if ctx.cache is not None and ctx.cache.get("source") == "TDT":
        return ctx.recording_method
    return None


def request_params(ctx, export_path, spec=None, source_path=None, extra_outputs=()):
    """The provenance.write request for one export. `spec` is {"kind", "parameters", "notes"} (any part optional); `source_path` the
    recording's location when it is not the loaded one (the PT2 viewer, the text field study): such an export is described by that source and
    the software only, not by whatever recording happens to be open."""
    spec = dict(spec or {})
    params = {"export": export_path, "kind": spec.get("kind"), "parameters": spec.get("parameters") or {}, "notes": spec.get("notes"),
              "extra_outputs": list(extra_outputs)}
    loaded = source_path is None and ctx.cache is not None
    if loaded:
        params["source_path"] = ctx.cache.get("source_path")
        params["regression_method"] = regression_method(ctx)
        params["store_labels"] = dict(ctx.store_labels)
        try:
            params["recording"] = recording_ref(ctx)
        except BackendError:                                    # the engine no longer holds this recording: the record has no state for it
            pass
    elif source_path is not None:
        params["source_path"] = source_path
    return params


def write_beside(ctx, export_path, spec=None, source_path=None, extra_outputs=()):
    """Asks the engine for the record of `export_path` (beside it). Does not wait."""
    def _failed(message):                          # the export itself succeeded; say so, and log why there is no record
        errorlog.error(f"Could not write the provenance record beside an export: {message}")

    return run_engine(ctx, "provenance.write", request_params(ctx, export_path, spec, source_path, extra_outputs),
                      lambda answer: None, _failed, exclusive=False)

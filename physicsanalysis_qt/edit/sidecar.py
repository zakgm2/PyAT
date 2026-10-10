"""
edit/sidecar.py
---------------
Save Changes: the markers, signal names, highlights, text boxes and splices kept in the JSON saves folder next to the loaded recording. What is
written, and where, is PyATCLI.saved_state — a script's edit is the app's — and the analysis engine does the writing (its saved.write
operation: the recording's folder may be on a network drive, and the writes are the engine's to make, like the reads when the recording is
opened). This module is the app's side of it: reading ctx.cache, asking, telling the person.

Opening a recording puts its saved changes on it in the engine (loading/common.py), so there is nothing here that reads them back.
"""


from ..backend import api
from ..app import errorlog
from ..app.background import run_engine
from ..app.toasts import show_error, show_window_toast


def _source_path(ctx):
    if ctx.cache is None or not ctx.cache.get('source_path'):
        return None
    return ctx.cache['source_path']


def sidecar_path(ctx):
    """Where this recording's markers.json lives — the folder layout itself is
    PyATCLI.marker_sidecar_path, shared with scripts and group analysis."""
    source = _source_path(ctx)
    return api.recording.marker_sidecar_path(source) if source else None


def write_saved(ctx, lists, on_written=None, noun="changes"):
    """Asks the engine to write `lists` ({"markers": [...], "splices": [...], "signal_labels": {...}, "highlights": [...],
    "text_annotations": [...]}, any of them) as the recording's saved state, replacing what was saved; an empty one takes its file away.
    on_written(files) is called with the paths written once it is done. Does not wait for, nor hold up, anything else the engine is doing.
    Returns the request, or None if there was nothing to save next to."""
    source = _source_path(ctx)
    if source is None:
        if ctx.cache is not None:
            show_error(ctx, f"No source file/folder path to save {noun} next to.")
        return None

    def _done(answer):
        if on_written is not None:
            on_written(answer["files"])

    return run_engine(ctx, "saved.write", {"recording": source, **lists}, _done,
                      lambda message: show_error(ctx, f"Could not save {noun}: {message}"), exclusive=False)


def clear_json_saves(ctx, on_done=None):
    """Deletes every file inside the JSON saves/ folder (not the folder
    itself) — used by Undo All Changes so a previously-saved sidecar
    doesn't get silently reloaded right back after the undo. on_done() is
    called when that is over, whether or not it worked (the person has been told)."""
    source = _source_path(ctx)

    def _failed(message):
        show_error(ctx, f"Could not clear the saved changes: {message}")
        if on_done is not None:
            on_done()

    if not source:
        if on_done is not None:
            on_done()
        return None
    return run_engine(ctx, "saved.clear", {"recording": source, "yes": True}, lambda answer: on_done() if on_done is not None else None,
                      _failed, exclusive=False)


def save_changes(ctx):
    """The Save Changes button: markers, highlights, text boxes, signal names and any active splice, in one request (the engine writes them
    together), and one toast saying what was kept."""
    if ctx.cache is None:
        return
    splices = [dict(s) for s in ctx._active_splices] if ctx.original_cache is not None else []
    lists = {"markers": [dict(m) for m in ctx.cache['markers']], "highlights": [dict(h) for h in ctx.cache.get('highlights', [])],
             "text_annotations": [dict(t) for t in ctx.cache.get('text_annotations', [])], "splices": splices}
    if ctx.cache.get('signals'):
        lists["signal_labels"] = dict(ctx._signal_renames)
    counts = [(len(lists["markers"]), "marker"), (len(splices), "splice"), (len(lists.get("signal_labels", {})), "signal name"),
              (len(lists["highlights"]), "highlight"), (len(lists["text_annotations"]), "text box")]
    plural = {"marker": "markers", "splice": "splices", "signal name": "signal names", "highlight": "highlights", "text box": "text boxes"}
    kept = ", ".join(f"{n} {word if n == 1 else plural[word]}" for n, word in counts if n)

    def _written(files):
        errorlog.action("save_changes", n_markers=len(lists["markers"]), n_splices=len(splices))
        show_window_toast(ctx, f"Changes saved -> JSON saves/ ({kept or 'nothing to keep'})")

    write_saved(ctx, lists, _written)

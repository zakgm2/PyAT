"""
backend/recordings.py
---------------------
The window's side of a recording the engine holds. `recording.open` / `recording.view` / `recording.splice` answer with the recording's
structure as JSON and its arrays as .npy files in the engine's data folder (PyATCLI/engine/wire.py); this module maps those files
back into the cache dict (ctx.cache) the window draws and analyses, and keeps the three things a request needs to name the recording:

    ctx.recording_id          the engine's id for it (None for a source the engine does not hold: PT2, a text field study)
    ctx._active_splices       the splices applied, in order — the engine keeps one variant per list, so Ctrl+Z, removing a splice and
                              Restore Full Recording are asking for an earlier list
    ctx.cache['markers'] ...  the window's own markers, highlights and text boxes, sent with every request (the engine never holds a second
                              copy of them to keep in step)

The arrays are mapped copy-on-write: nothing is read until it is touched and an edit made in the window stays in the window.
"""

from dataclasses import dataclass, field

from PyATCLI.engine.wire import decode

from ..figures.style import signal_color
from .errors import BackendError


@dataclass
class OpenedRecording:
    """What recording.open gives the window, with the arrays mapped."""
    id: str
    path: str
    cache: dict
    original_cache: dict = None        # the recording as recorded, when saved splices were replayed (what Restore Full Recording brings back)
    splices: list = field(default_factory=list)
    signal_labels: dict = field(default_factory=dict)
    restored: dict = field(default_factory=dict)       # {"splices": n, "markers": n | None, "highlights": ..., "text_annotations": ...}
    warnings: list = field(default_factory=list)
    regression_method: str = "ols"


def add_display_colours(cache):
    """Gives each signal the colour the window draws it in (figures/style.py's: the one the plot engines and Export View use). The engine does not
    know about colours, and a colour already set (a person's choice) is kept."""
    for key, sig in (cache.get("signals") or {}).items():
        sig.setdefault("color", signal_color(key))
    return cache


def decode_arrays(structure, directory, mmap=True):
    """A structure the engine sent with its arrays loaded back: mapped from the files in `directory`, or read into memory (mmap=False)."""
    return decode(structure, directory, mmap=mmap)


def decode_cache(structure, directory):
    """A cache from its wire form, its arrays mapped from `directory`, ready to draw."""
    return add_display_colours(decode(structure, directory))


def opened_from_wire(wired):
    """The OpenedRecording for a recording.open answer."""
    directory = wired["directory"]
    cache = decode_cache(wired["cache"], directory)
    original = wired.get("original_cache")
    return OpenedRecording(
        id=wired["id"], path=wired["path"], cache=cache,
        original_cache=decode_cache(original, directory) if original is not None else None,
        splices=list(wired.get("splices") or []), signal_labels=dict(wired.get("signal_labels") or {}),
        restored=dict(wired.get("restored") or {}), warnings=list(wired.get("warnings") or []),
        regression_method=wired.get("regression_method") or "ols")


def variant_from_wire(wired):
    """(cache, splices) for a recording.view / recording.splice answer: the recording with that list of splices applied."""
    return decode_cache(wired["cache"], wired["directory"]), list(wired.get("splices") or [])


def recording_ref(ctx, **extra):
    """How a request names the loaded recording: the engine's id, the splices applied, and the window's own markers, highlights, text
    boxes and signal names (see the module docstring). `extra` adds or replaces fields (a different `splices`, say).
    Raises BackendError (code "no_recording") if the recording is not one the engine holds, or the engine has restarted since it was opened."""
    if ctx.cache is None or ctx.recording_id is None:
        raise BackendError("this recording is not held by the analysis engine", code="no_recording",
                           hint="open it again with Open")
    if ctx.recording_generation != ctx.engine.generation:
        raise BackendError("the analysis engine was restarted and no longer has this recording", code="no_recording",
                           hint="reload it with Reload")
    ref = {"id": ctx.recording_id, "splices": [dict(s) for s in ctx._active_splices], "markers": ctx.cache.get("markers", [])}
    for key in ("highlights", "text_annotations"):
        if key in ctx.cache:
            ref[key] = ctx.cache[key]
    if ctx._signal_renames:
        ref["signal_labels"] = dict(ctx._signal_renames)
    ref.update(extra)
    return ref


def adopt(ctx, opened):
    """Makes `opened` the loaded recording: the state a fresh load starts from (no pending splice choice, a clean undo history — Ctrl+Z
    never swaps one recording for another), and lets the engine go of the recording that was loaded before."""
    previous = ctx.recording_id
    ctx.original_cache = opened.original_cache
    ctx._active_splices = [dict(s) for s in opened.splices]
    ctx._undo_stack.clear()
    ctx._data_generation += 1
    ctx.cache = opened.cache
    ctx.recording_id = opened.id
    ctx.recording_generation = ctx.engine.generation
    ctx.recording_method = opened.regression_method
    ctx._signal_renames = dict(opened.signal_labels)
    if previous is not None and previous != opened.id:
        ctx.engine.request("recording.close", {"id": previous})                  # nobody waits for the answer; a stale id is an error nobody reads


def forget(ctx):
    """The loaded recording is no longer the engine's (a source the engine does not hold took its place)."""
    previous, ctx.recording_id = ctx.recording_id, None
    if previous is not None:
        ctx.engine.request("recording.close", {"id": previous})

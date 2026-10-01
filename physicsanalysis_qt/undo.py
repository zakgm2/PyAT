"""
undo.py
-------
A one-step-at-a-time undo stack (Ctrl+Z) for the two things that mutate a loaded recording:
markers and splices. Not a general app-wide undo — Edit Attributes, the plot engine, window
layout, Options, and so on are unaffected; see repo-layout notes for why this stays scoped.

Every entry is a full snapshot of everything markers/splices touch, taken right before the
action runs and restored wholesale on undo — simpler and far less error-prone than writing a
bespoke inverse for every action (add vs. remove vs. rename a marker, apply vs. remove a splice,
rename vs. reset a store label, ...). The call pattern at every mutation site is the same two
lines:

    before = undo.snapshot(ctx)
    ... the actual mutation ...
    undo.push(ctx, "placed a marker", before)

snapshot() must be called before the mutation (some of what it captures, like cache['markers'],
is mutated in place rather than reassigned, so it has to copy before that happens, not after).
push() is a no-op if snapshot() returned None (nothing was loaded), so callers don't need to
guard that themselves.
"""

UNDO_LIMIT = 50  # oldest steps drop off rather than growing forever across a long session


def snapshot(ctx):
    """Call right BEFORE a marker/splice-mutating action. Returns an opaque token to pass to
    push() afterward, or None if there's nothing loaded to snapshot."""
    if ctx.cache is None:
        return None
    return {
        "cache": dict(ctx.cache),
        "markers": [dict(m) for m in ctx.cache.get("markers", [])],
        "detected_markers": list(ctx.cache.get("detected_markers", [])),
        "active_splices": list(ctx._active_splices),
        "original_cache": ctx.original_cache,
        "store_labels": dict(ctx.store_labels),
    }


def push(ctx, label, before):
    """Call right AFTER the action succeeds, with what snapshot(ctx) returned beforehand. A no-op
    if `before` is None (snapshot() found nothing loaded) — nothing to ever undo back to."""
    if before is None:
        return
    ctx._undo_stack.append({"label": label, **before})
    del ctx._undo_stack[:-UNDO_LIMIT]


def can_undo(ctx):
    return bool(ctx._undo_stack)


def undo(ctx):
    """Ctrl+Z: restores the most recent snapshot and redraws. Returns the action's label, or None
    if the stack was empty (nothing to undo)."""
    if not ctx._undo_stack:
        return None
    entry = ctx._undo_stack.pop()
    ctx.cache = entry["cache"]
    ctx.cache["markers"] = entry["markers"]
    ctx.cache["detected_markers"] = entry["detected_markers"]
    ctx._active_splices = entry["active_splices"]
    ctx.original_cache = entry["original_cache"]
    ctx.store_labels = entry["store_labels"]
    ctx._data_generation += 1
    from .plotting import simple_plot
    simple_plot(ctx)
    return entry["label"]

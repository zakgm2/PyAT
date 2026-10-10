"""
edit/marker_labels.py
---------------------
Display-text helpers for markers, bound to the app's own store-rename state (ctx.store_labels,
set via right-click Edit Marker's "rename all"). The naming rules themselves — store rename
overrides (the raw TDT store code, e.g. 'PP1_' or 'L1P', stays the internal id used for
grouping/filtering everywhere; only how it's *shown* changes) and the high/low phase superscript —
live in PyATCLI's markers.py, so a script names markers exactly as the app does. Used by
both plot engines, the marker dialogs, and the Event Intervals table so they all agree on what a
marker's name and store currently look like.
"""

from ..backend import api


def store_display_name(ctx, store_id):
    """The name shown for a store id — the renamed name if one's been set
    via 'Rename all', otherwise the raw store id unchanged."""
    return api.markers.store_display_name(store_id, ctx.store_labels)


def marker_display_label(ctx, m):
    """Full text to draw for a marker: its store's renamed display name,
    plus a superscript ¹/⁰ if it's a high/low phase marker (see
    PyATCLI.marker_display_label for which markers get the
    store-name substitution)."""
    return api.markers.marker_display_label(m, ctx.store_labels)

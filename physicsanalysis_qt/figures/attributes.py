"""
figures/attributes.py
---------------------
Edit Graph Attributes: the rules that turn what a person typed or picked into the attributes a plot keeps (a dict, `default_plot_attrs()` in
view.py — what Export View and both of PyAT's plot engines draw with). The dialog (edit/attributes.py) and the plot engines apply them here.

The rules, each a small function:

    set_text_override    a title or axis label you retype is kept — unless it is just the text the plot generates, which is no
                         override at all, so the plot goes on following it (a renamed signal is part of the automatic title)
    clamp_size           a font size is a whole number of points, never below 6; something that is not a number is ignored
    legend_edits         {a line's own legend name: (what it is called, shown)} — an entry renamed or hidden; its line is still drawn
    rename_legend_entry  the double-click rename of one entry
    set_line_color       a colour per line, filed under the line's legend name; the colour it is drawn in by default is no override
    migrate_names        a colour and a legend edit follow their signal to its new name (names can swap)

Naming a signal is the recording's rule, not the plot's — a name must say something and two signals cannot share one (api.recording.
name_problem, plan_signal_renames) — and `apply_edits` is the dialog's Apply: every field of Edit Graph Attributes in, the attributes changed,
nothing changed if a rename is refused.
"""

from dataclasses import dataclass, field

from ..backend import api

MIN_FONT_SIZE = 6
TEXT_KEYS = ("title", "xlabel", "ylabel")
SIZE_KEYS = ("title_fs", "xlabel_fs", "ylabel_fs")


# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------

def set_text_override(attrs, key, text, auto):
    """Records the user's own title / x label / y label (`key`: "title", "xlabel" or "ylabel"). Text identical to what the plot
    generates anyway (`auto`) is no override at all (None), so the plot keeps following whatever it generates."""
    attrs[key] = None if text == auto else text
    return attrs


def clamp_size(value, current):
    """A font size from what was typed: a whole number of points, at least MIN_FONT_SIZE; `current` if it is not a number."""
    try:
        return max(MIN_FONT_SIZE, int(value))
    except (TypeError, ValueError):
        return current


def legend_edits(attrs):
    """{a line's own legend name: (what it is called, shown)} from the attributes' `leg_entries` ({} if there are none)."""
    return {orig: (new, shown) for orig, new, shown in (attrs.get("leg_entries") or [])}


def legend_rows(attrs, own_names):
    """[(own name, what it is called, shown)] for each legend entry of the plot, in order — an entry with no edit is called what
    it is and shown."""
    edits = legend_edits(attrs)
    return [(orig, *edits.get(orig, (orig, True))) for orig in own_names]


def rename_legend_entry(attrs, own_names, shown_now, new_label):
    """Renames the entry currently shown as `shown_now` to `new_label` (a double-click on the legend). Returns False, changing
    nothing, if no entry is shown like that."""
    edits = legend_edits(attrs)
    target, visible = None, True
    for orig in own_names:
        shown, vis = edits.get(orig, (orig, True))
        if shown == shown_now:
            target, visible = orig, vis
            break
    if target is None:
        return False
    edits[target] = (new_label, visible)
    attrs["leg_entries"] = [(orig, *edits.get(orig, (orig, True))) for orig in own_names]
    return True


def _hex(color):
    try:
        from matplotlib.colors import to_hex
        return to_hex(color).lower()
    except (ImportError, ValueError):
        return str(color).lower()


def set_line_color(attrs, key, color, default=None):
    """The colour a line is drawn in, filed under its legend name `key`. None, or the colour it has by default, is no override:
    the line goes back to following its default. Returns True if the override changed."""
    colors = attrs["line_colors"]
    if color is not None and default is not None and _hex(color) == _hex(default):
        color = None
    before = colors.get(key)
    if color:
        colors[key] = color
    else:
        colors.pop(key, None)
    return before != colors.get(key)


def migrate_names(attrs, old_to_new):
    """What a plot remembers per line name — its colour override and its legend edit — follows the line to its new name. Done as
    one mapping, so two signals can swap names."""
    colors = attrs["line_colors"]
    moved = {old_to_new.get(name, name): color for name, color in colors.items()}
    colors.clear()
    colors.update(moved)
    if attrs.get("leg_entries"):
        attrs["leg_entries"] = [
            (old_to_new[orig], old_to_new[orig], shown) if orig in old_to_new else (orig, called, shown)
            for orig, called, shown in attrs["leg_entries"]
        ]
    return attrs


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

@dataclass
class EditResult:
    """What an edit did: the signals renamed ({key: new name}), the legend entries that were signals' names ({old name: new name}),
    whether a line's colour changed."""
    changes: dict = field(default_factory=dict)
    renamed: dict = field(default_factory=dict)
    colors_changed: bool = False


def apply_edits(attrs, *, auto, own_names, signals=None, rename, texts=None, sizes=None, leg_fs=None, leg_loc=None, bold=None,
                entries=None, colors=None):
    """Edit Graph Attributes' Apply: the fields the dialog holds, in, and `attrs` changed in place.

    auto        {"title", "xlabel", "ylabel"}: the plot's automatic text
    own_names   the legend entries' own names, in order
    signals     the recording's signals ({key: {"label", ...}}) — an entry that is one of their names is that signal's name
    rename      `rename({key: new name}) -> {key: new name}` makes those names the recording's (everywhere it keeps them, and the
                attributes' names with them — see rename_signals); raises ValueError if refused
    texts       {"title"|"xlabel"|"ylabel": text}; empty text leaves it as it is
    sizes       {"title_fs"|"xlabel_fs"|"ylabel_fs": what was typed}; leg_fs the same for the legend
    leg_loc, bold   the legend's place, bold
    entries     [(own name, text typed, shown)] — the legend rows
    colors      [(own name, colour or None, default colour)] — the line colour rows; None is "the default"

    A rename the recording refuses (ValueError) is raised before anything else is changed. Returns an EditResult."""
    texts, sizes = texts or {}, sizes or {}
    changes, renamed = {}, {}
    if entries and signals:
        by_name = {sig['label']: key for key, sig in signals.items()}
        wanted = {by_name[orig]: text for orig, text, _shown in entries if orig in by_name and text.strip() and text.strip() != orig}
        if wanted:
            changes = rename(wanted)                                       # may raise: nothing has been changed yet
            renamed = {old: changes[key] for old, key in by_name.items() if key in changes}

    for key in TEXT_KEYS:
        text = (texts.get(key) or "").strip()
        if text:
            set_text_override(attrs, key, text, auto[key])
    for key in SIZE_KEYS:
        if key in sizes:
            attrs[key] = clamp_size(sizes[key], attrs[key])
    if leg_fs is not None:
        attrs["leg_fs"] = clamp_size(leg_fs, attrs["leg_fs"])
    if leg_loc is not None:
        attrs["leg_loc"] = leg_loc
    if bold is not None:
        attrs["bold"] = bool(bold)

    if entries:
        attrs["leg_entries"] = [(renamed[orig], renamed[orig], shown) if orig in renamed else (orig, text or orig, shown)
                                for orig, text, shown in entries]

    changed = False
    for orig, color, default in colors or []:
        changed |= set_line_color(attrs, renamed.get(orig, orig), color, default)
    return EditResult(changes, renamed, changed)


def rename_signals(cache, attrs, renames):
    """Makes `renames` ({signal key: new name}) the names of the recording's signals — the cache is updated in place — and carries
    `attrs`' colours and legend edits over to the new names. Returns {key: new name} for what changed; ValueError, with nothing
    changed, if two signals would share a name."""
    changes = api.recording.plan_signal_renames(cache, renames)
    if changes:
        current = api.recording.current_signal_labels(cache)
        api.recording.apply_signal_labels(cache, changes)
        migrate_names(attrs, {current[key]: name for key, name in changes.items()})
    return changes

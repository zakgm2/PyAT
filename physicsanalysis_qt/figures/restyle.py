"""
figures/restyle.py
------------------
Edit Graph Attributes for the figures of the analysis windows: what a person changed about a figure — the words on it, the sizes of the words, the
colour of a line, the dot on every sample, the legend, the grid — kept apart from the figure, so it is still there when the window draws the figure
again (a window rebuilds its figure on every change: another event, another view, Recalculate).

    parts = describe(fig)            what a freshly drawn figure says and shows on its own: every text, line, legend (a record of the defaults)
    apply(fig, parts, edits)         puts `edits` on the figure — every part is set, to the edit or else back to what it was drawn as, so applying
                                     fewer edits undoes the rest
    edited(parts, edits, ...)        the rules for what a dialog's fields become (a text equal to the drawn one is no edit)
    edit_notes(parts, edits)         the edits as sentences, for the provenance record that goes beside an export

A window calls `describe` and `apply` after each drawing (edit/figure_attributes.py's EditableFigure does, for it); the dialog calls `edited` and
`apply`. Everything is matplotlib's own: nothing here needs a window, and what is applied is what Export Figure writes.

What can be edited, each under a name (key) that the drawing gives the same way every time:

    texts      every title, axis label and colour-bar label, by its caption ("Figure title", "Group trace: Y label", the same ones Export Figure lists)
    sizes      the size of the figure title, of the panel titles, of the axis labels and of the legend, in points (one size for each, as the main plot has)
    bold       titles and labels bold or not
    colors     the colour of a series — a line, with the band around it and the unnamed lines drawn in its colour — by "<panel>: <name>"
    point_size the dot on every sample of every line, in points (0: none); None leaves the lines as they were drawn
    grid       the grid on every panel that has a line
    legend     the place of the legend, and for each entry what it is called (renaming the series itself) and whether it is shown
"""

from copy import deepcopy
from dataclasses import dataclass, field

from .attributes import clamp_size, set_line_color
from .data import _is_band, _is_reference_line, _skipped, panel_name
from .labels import COLORBAR_AXES_LABEL, text_items
from .view import LEGEND_LOCATIONS, MAX_POINT_SIZE

FIGURE_TITLE, PANEL_TITLE, LABEL, LEGEND = "figure_title", "panel_title", "label", "legend"
SIZE_KINDS = (FIGURE_TITLE, PANEL_TITLE, LABEL, LEGEND)
SIZE_NAMES = {FIGURE_TITLE: "Title", PANEL_TITLE: "Panel titles", LABEL: "Axis labels", LEGEND: "Legend"}
BOLD_KINDS = (FIGURE_TITLE, PANEL_TITLE, LABEL)
GRID_STYLE = {"linestyle": ":", "alpha": 0.5}                  # the grid a figure is given that was drawn without one


# ---------------------------------------------------------------------------
# What a person changed
# ---------------------------------------------------------------------------

@dataclass
class FigureEdits:
    """The edits to one figure. Each is an override of what the figure draws on its own: a key that is not here (or None) is as drawn."""
    texts: dict = field(default_factory=dict)             # {text key: what it says instead}; "" is no text at all
    sizes: dict = field(default_factory=dict)             # {FIGURE_TITLE | PANEL_TITLE | LABEL | LEGEND: points}
    bold: bool = None
    grid: bool = None
    colors: dict = field(default_factory=dict)            # {series key: "#rrggbb"}
    point_size: float = None
    legend_loc: str = None
    legend_entries: dict = field(default_factory=dict)    # {entry key: (what it is called, shown)}

    def is_empty(self):
        return not (self.texts or self.sizes or self.colors or self.legend_entries
                    or self.bold is not None or self.grid is not None or self.point_size is not None or self.legend_loc is not None)

    def copy(self):
        return deepcopy(self)


# ---------------------------------------------------------------------------
# What a figure is, as drawn
# ---------------------------------------------------------------------------

@dataclass
class Text:
    key: str                  # what the edit is filed under: the caption Export Figure lists it as
    kind: str                 # FIGURE_TITLE, PANEL_TITLE, LABEL, or None for any other text on the figure
    artist: object
    default: str
    size: float
    weight: object


@dataclass
class Series:
    key: str                  # "<panel>: <name>"
    name: str
    panel: str
    lines: list               # the line (and the unnamed ones drawn in its colour)
    bands: list               # the band around it
    default_color: str
    markers: list             # [(marker, markersize)] of each line as drawn
    colors: list = field(default_factory=list)          # the colour each line was drawn in, as it was given (a name, a hex): put back as it was
    band_colors: list = field(default_factory=list)    # [(face colours, edge colours)] of each band as drawn


@dataclass
class Entry:
    key: str
    handle: object
    default: str


@dataclass
class LegendParts:
    key: str                  # the panel's name
    ax: object
    original: object          # the legend as it was drawn
    entries: list
    loc: str
    size: float
    frameon: bool


@dataclass
class Gridded:
    ax: object
    on: bool                  # as drawn
    style: dict               # what its grid looked like, if it was on


@dataclass
class Parts:
    texts: list = field(default_factory=list)
    series: list = field(default_factory=list)
    legends: list = field(default_factory=list)
    grids: list = field(default_factory=list)
    point_default: float = 0.0            # the largest dot the lines were drawn with
    bold_default: bool = True
    laid_out: bool = False                # the text was changed (and the figure laid out again) at some time: it must be again to be put back

    def size_default(self, kind):
        """The size of the first text of that kind as drawn (the legend's: of its first); None if the figure has none."""
        if kind == LEGEND:
            return next((lp.size for lp in self.legends), None)
        return next((t.size for t in self.texts if t.kind == kind), None)

    def kinds(self):
        """The size kinds this figure has something of."""
        return [kind for kind in SIZE_KINDS if self.size_default(kind) is not None]


def _hex(color):
    from matplotlib.colors import to_hex
    return to_hex(color, keep_alpha=False).lower()


def _is_bold(weight):
    """Whether a font weight (a name matplotlib knows, or a number) is a bold one."""
    return weight >= 600 if isinstance(weight, (int, float)) else str(weight) in ("bold", "heavy", "black", "semibold", "demibold", "extra bold")


def _unique(key, taken):
    """`key`, or numbered ("<key> (2)") if another part already has it."""
    if key not in taken:
        return key
    n = 2
    while f"{key} ({n})" in taken:
        n += 1
    return f"{key} ({n})"


def _kinds_of(fig):
    """{id(artist): kind} for the titles and labels of `fig`."""
    kinds = {}
    if getattr(fig, "_suptitle", None) is not None:
        kinds[id(fig._suptitle)] = FIGURE_TITLE
    for ax in fig.axes:
        for artist in (ax.title, getattr(ax, "_left_title", None), getattr(ax, "_right_title", None)):
            if artist is not None:
                kinds[id(artist)] = PANEL_TITLE
        kinds[id(ax.xaxis.label)] = kinds[id(ax.yaxis.label)] = LABEL
    return kinds


def _is_data_axes(ax):
    return ax.get_label() != COLORBAR_AXES_LABEL


def _series_of(ax, panel, prefix):
    """The series of one panel (filed under `prefix` + its name: the panel's name where the figure has several): each named line, then the lines with no name of their own that are drawn in a named line's colour (a fit's faint
    surroundings, its anchor points) with it, otherwise one each; the band round a line goes with it."""
    from matplotlib.colors import to_rgb

    lines = [line for line in ax.lines if not (_skipped(line) or _is_reference_line(ax, line)) and len(line.get_xdata())]
    rgb = lambda line: tuple(round(v, 3) for v in to_rgb(line.get_color()))               # noqa: E731
    series, by_colour, taken = [], {}, set()
    for line in lines:
        label = line.get_label()
        if label and not label.startswith("_"):
            s = Series(_unique(prefix + label, taken), label, panel, [line], [], _hex(line.get_color()), [])
            taken.add(s.key)
            series.append(s)
            by_colour.setdefault(rgb(line), s)
    for n, line in enumerate(lines, 1):
        label = line.get_label()
        if label and not label.startswith("_"):
            continue
        owner = by_colour.get(rgb(line))
        if owner is not None:
            owner.lines.append(line)
        else:
            name = f"line {n}"
            s = Series(_unique(prefix + name, taken), name, panel, [line], [], _hex(line.get_color()), [])
            taken.add(s.key)
            series.append(s)
            by_colour[rgb(line)] = s
    for coll in ax.collections:
        if _skipped(coll) or not _is_band(coll) or len(coll.get_facecolor()) == 0:
            continue
        owner = by_colour.get(tuple(round(float(v), 3) for v in coll.get_facecolor()[0][:3]))
        if owner is not None:
            owner.bands.append(coll)
    for s in series:
        s.markers = [(line.get_marker(), line.get_markersize()) for line in s.lines]
        s.colors = [line.get_color() for line in s.lines]
        s.band_colors = [(band.get_facecolor().copy(), band.get_edgecolor().copy()) for band in s.bands]
    return series


def _legend_parts(ax, panel, prefix):
    from matplotlib.legend import Legend

    original = ax.get_legend()
    if original is None:
        return None
    handles, labels = ax.get_legend_handles_labels()
    entries, taken = [], set()
    for handle, label in zip(handles, labels):
        key = _unique(prefix + label, taken)
        taken.add(key)
        entries.append(Entry(key, handle, label))
    code_names = {code: name for name, code in Legend.codes.items()}
    loc = code_names.get(getattr(original, "_loc", 0), "best")
    texts = original.get_texts()
    size = float(texts[0].get_fontsize()) if texts else 10.0
    return LegendParts(panel, ax, original, entries, loc if loc in LEGEND_LOCATIONS else "best", size, original.get_frame_on())


def _gridded(ax):
    gridlines = ax.xaxis.get_gridlines()
    on = bool(gridlines) and gridlines[0].get_visible()
    style = ({"linestyle": gridlines[0].get_linestyle(), "alpha": gridlines[0].get_alpha() or 1.0, "color": gridlines[0].get_color(),
              "linewidth": gridlines[0].get_linewidth()} if on else dict(GRID_STYLE))
    return Gridded(ax, on, style)


def describe(fig):
    """What `fig` says and shows on its own — call it on a figure that has just been drawn, before any edit is put on it (a record of the defaults)."""
    parts = Parts()
    kinds = _kinds_of(fig)
    in_legends = {id(t) for ax in fig.axes if ax.get_legend() for t in ax.get_legend().get_texts()}
    in_legends |= {id(t) for legend in fig.legends for t in legend.get_texts()}
    taken = set()
    for item in text_items(fig):
        if id(item.artist) in in_legends:
            continue
        key = _unique(item.caption, taken)
        taken.add(key)
        artist = item.artist
        parts.texts.append(Text(key, kinds.get(id(artist)), artist, artist.get_text(), float(artist.get_fontsize()), artist.get_fontweight()))
    titled = [t for t in parts.texts if t.kind in BOLD_KINDS]
    parts.bold_default = (not titled) or 2 * sum(_is_bold(t.weight) for t in titled) >= len(titled)       # (most of them: a colour bar's label is not)
    panels = [(i, ax) for i, ax in enumerate(fig.axes, 1) if _is_data_axes(ax)]
    for i, ax in panels:
        panel = panel_name(ax, i)
        prefix = f"{panel}: " if len(panels) > 1 else ""                   # (as Export Figure captions the texts: the panel's name only if there are several)
        found = _series_of(ax, panel, prefix)
        parts.series += found
        legend = _legend_parts(ax, panel, prefix)
        if legend is not None:
            parts.legends.append(legend)
        if found:
            parts.grids.append(_gridded(ax))
    parts.point_default = max((size for s in parts.series for marker, size in s.markers if marker not in (None, "None", "none", "", " ")), default=0.0)
    return parts


# ---------------------------------------------------------------------------
# Putting the edits on the figure
# ---------------------------------------------------------------------------

def _text_edits(parts, edits):
    for t in parts.texts:
        t.artist.set_text(edits.texts.get(t.key, t.default))
        t.artist.set_fontsize(edits.sizes.get(t.kind, t.size) if t.kind in SIZE_KINDS else t.size)
        t.artist.set_fontweight(("bold" if edits.bold else "normal") if edits.bold is not None and t.kind in BOLD_KINDS else t.weight)


def _series_edits(parts, edits):
    for s in parts.series:
        color = edits.colors.get(s.key)
        for line, drawn, (marker, size) in zip(s.lines, s.colors, s.markers):
            line.set_color(drawn if color is None else color)
            if edits.point_size is None:
                line.set_marker(marker)
                line.set_markersize(size)
            elif edits.point_size > 0:
                line.set_marker("o")
                line.set_markersize(edits.point_size)
            else:
                line.set_marker("None")
        for band, (face, edge) in zip(s.bands, s.band_colors):
            if color is None:
                band.set_facecolor(face)
                band.set_edgecolor(edge)
            else:
                band.set_color(color)


def _grid_edits(parts, edits):
    for g in parts.grids:
        if edits.grid is None:
            g.ax.grid(g.on, **(g.style if g.on else {}))
        else:
            g.ax.grid(edits.grid, **(GRID_STYLE if edits.grid else {}))


def _legend_edits(parts, edits):
    for lp in parts.legends:
        called = [(e, *edits.legend_entries.get(e.key, (e.default, True))) for e in lp.entries]
        for e, name, _shown in called:
            e.handle.set_label(name)                                     # the series is called what its entry says (and so is the figure's data CSV)
        recoloured = any(s.key in edits.colors for s in parts.series)
        if not (edits.legend_loc or LEGEND in edits.sizes or edits.legend_entries or recoloured):
            lp.ax.legend_ = lp.original                                  # nothing about it was edited: the legend as it was drawn
            continue
        shown = [(e.handle, name) for e, name, visible in called if visible]
        if shown:
            lp.ax.legend([h for h, _ in shown], [n for _, n in shown], loc=edits.legend_loc or lp.loc, fontsize=edits.sizes.get(LEGEND, lp.size),
                         frameon=lp.frameon)
        else:
            lp.ax.legend_ = None


def relayout(fig):
    """Lays `fig` out again after its words changed size, as it was laid out when it was drawn (draw.py keeps the rectangle it was fitted into).
    A figure with a layout engine of its own lays itself out at every drawing, so nothing is done for it."""
    import warnings

    engine = fig.get_layout_engine() if hasattr(fig, "get_layout_engine") else None
    if engine is not None and type(engine).__name__ != "PlaceHolderLayoutEngine":
        return
    rect = getattr(fig, "pyat_layout_rect", None)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")                                   # "tight_layout not applied": the figure is left as it is
        fig.tight_layout(rect=rect) if rect is not None else fig.tight_layout()


def apply(fig, parts, edits):
    """Puts `edits` on `fig` (`parts`: describe() of it, taken when it was drawn). Every part is set, to its edit or else back to what it was drawn
    as, so a figure with fewer edits than it had comes back. The figure is laid out again if its words changed (or had)."""
    words = bool(edits.texts or edits.sizes or edits.bold is not None)
    _text_edits(parts, edits)
    _series_edits(parts, edits)
    _grid_edits(parts, edits)
    _legend_edits(parts, edits)
    if words or parts.laid_out:
        relayout(fig)
        parts.laid_out = words


# ---------------------------------------------------------------------------
# The rules: what a dialog's fields become
# ---------------------------------------------------------------------------

def edited(parts, edits, *, texts=None, sizes=None, bold=None, grid=None, colors=None, point_size=None, legend_loc=None, entries=None):
    """`edits` with what the dialog holds put in: a new FigureEdits, `edits` itself untouched. A field that says what the figure says on its own is no
    edit (so the figure goes on following it); empty text is an edit — no text.

    texts       {text key: what the field says}
    sizes       {kind: what was typed}: not a number is left as it was; below the smallest legible size is that size
    bold, grid  the boxes
    colors      [(series key, colour or None, the colour it is drawn in)]
    point_size  the dot, in points (None: not touched)
    legend_loc  the place chosen for the legend
    entries     [(entry key, what the field says, shown)]; empty text is the name it has"""
    out = edits.copy()
    defaults = {t.key: t.default for t in parts.texts}
    for key, text in (texts or {}).items():
        if key in defaults:
            if text == defaults[key]:
                out.texts.pop(key, None)
            else:
                out.texts[key] = text
    for kind, typed in (sizes or {}).items():
        default = parts.size_default(kind)
        if default is None:
            continue
        size = clamp_size(typed, out.sizes.get(kind, round(default)))
        if size == round(default):
            out.sizes.pop(kind, None)
        else:
            out.sizes[kind] = size
    if bold is not None:
        out.bold = None if bool(bold) == parts.bold_default else bool(bold)
    if grid is not None:
        drawn = any(g.on for g in parts.grids)
        out.grid = None if bool(grid) == drawn else bool(grid)
    for key, color, default in colors or []:
        set_line_color({"line_colors": out.colors}, key, color, default)
    if point_size is not None:
        size = min(max(float(point_size), 0.0), float(MAX_POINT_SIZE))
        out.point_size = None if size == float(parts.point_default) else size
    if legend_loc is not None:
        first = parts.legends[0].loc if parts.legends else None
        out.legend_loc = None if legend_loc == first else legend_loc
    for key, text, shown in entries or []:
        default = next((e.default for lp in parts.legends for e in lp.entries if e.key == key), None)
        if default is None:
            continue
        name = text.strip() or default
        if name == default and shown:
            out.legend_entries.pop(key, None)
        else:
            out.legend_entries[key] = (name, bool(shown))
    return out


def edit_notes(parts, edits):
    """The edits as sentences, one each, for the provenance record written beside an export ([] for a figure that is as drawn)."""
    notes = []
    defaults = {t.key: t.default for t in parts.texts}
    for key, text in edits.texts.items():
        notes.append(f"Edit Attributes — text ({key}): {defaults.get(key, '')!r} -> {text!r}")
    for kind in SIZE_KINDS:
        if kind in edits.sizes:
            notes.append(f"Edit Attributes — {SIZE_NAMES[kind].lower()} size: {edits.sizes[kind]} pt")
    if edits.bold is not None:
        notes.append(f"Edit Attributes — titles and labels {'bold' if edits.bold else 'not bold'}")
    if edits.grid is not None:
        notes.append(f"Edit Attributes — grid {'shown' if edits.grid else 'hidden'}")
    for key, color in edits.colors.items():
        notes.append(f"Edit Attributes — line colour ({key}): {color}")
    if edits.point_size is not None:
        notes.append(f"Edit Attributes — a dot on every sample of every line: {edits.point_size:g} pt")
    if edits.legend_loc is not None:
        notes.append(f"Edit Attributes — legend placed {edits.legend_loc}")
    for key, (name, shown) in edits.legend_entries.items():
        notes.append(f"Edit Attributes — legend entry ({key}): called {name!r}, {'shown' if shown else 'hidden'}")
    return notes

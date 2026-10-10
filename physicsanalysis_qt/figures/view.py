"""
figures/view.py
---------------
Export View: the main plot of a recording, redrawn as a publication figure — the same traces, markers, highlights, text boxes, title, labels and
legend, in the range asked for, on a white page with black text. PyAT's main plot (both engines) draws its lines through `view_traces`, so the
export cannot differ from the screen.

What the plot shows — which lines a recording has, under what name, with what numbers, the range, the markers in it — is the analysis library's
(api.view.view_traces / plan_view: its numbers are what the data CSV and a provenance record hold). How it looks is decided here: a line's colour,
width and marker (`style_traces`), the figure, the legend.

    view = build_view(cache, xlim=(40, 120), attrs={"title": "Lever session", "line_colors": {"Normalized (dF/F)": "#1b6ca8"}})
    view.save("fig2.pdf")                                           # fig2.pdf, fig2_data.csv, fig2_markers.csv

The data CSV beside the figure is not read off the drawn lines (they are thinned to a few tens of thousands of points, plenty for a page): it holds
every sample of the visible range, one column per trace, and a second CSV lists the markers in view.

`attrs` is what Edit Graph Attributes edits: a dict with the keys of `default_plot_attrs()` — a title, x and y label (None = the automatic text),
their font sizes, the legend's size, place and per-entry edits (renamed or hidden), bold, and `line_colors` ({the line's legend name: "#rrggbb"}).
"""

from dataclasses import dataclass

import numpy as np

from ..backend import api
from .style import signal_color

EXPORT_MAX_POINTS = 40_000            # per trace in the drawn figure: more than a page can show, far fewer than a recording has
GRID_COLOR = "#b0b0b0"
GENERIC_COLORS = ['#CC0000', '#0033CC', '#228B22', '#CC6600', '#6600CC', '#008888', '#AA0055', '#005588']
LEGEND_LOCATIONS = ["upper left", "upper right", "lower left", "lower right", "upper center", "lower center",
                    "center left", "center right", "center", "best"]
DEFAULT_FIGURE_SIZE = (10.0, 5.5)


# ---------------------------------------------------------------------------
# Attributes (Edit Graph Attributes)
# ---------------------------------------------------------------------------

def default_plot_attrs():
    """What Edit Graph Attributes starts from: no text of its own, the app's font sizes, the legend upper left, bold."""
    return {
        "title":       None,
        "xlabel":      None,
        "ylabel":      None,
        "title_fs":    24,
        "xlabel_fs":   16,
        "ylabel_fs":   16,
        "leg_fs":      14,
        "leg_loc":     "upper left",
        "leg_entries": None,        # [(the entry's own name, what to call it, shown)] or None for every entry as it is
        "bold":        True,
        "line_colors": {},          # {the line's legend name: "#rrggbb"} — user overrides of a line's colour
    }


def plot_attrs(**changes):
    """default_plot_attrs() with `changes` on top, checked: an unknown key, a legend place that is not one of LEGEND_LOCATIONS, a font size
    that is not a number, or a colour that is not a name matplotlib knows is a ValueError that says what is wrong. Returns the dict."""
    return normalize_attrs(changes, check_colours=True)


def normalize_attrs(changes, check_colours=False):
    """`changes` on top of the defaults, everything checked but the colours, which are checked (with matplotlib) when `check_colours` says so."""
    attrs = default_plot_attrs()
    unknown = sorted(set(changes) - set(attrs))
    if unknown:
        raise ValueError(f"unknown plot attribute {', '.join(map(repr, unknown))}; the attributes are: {', '.join(attrs)}")
    attrs.update(changes)
    attrs["line_colors"] = dict(attrs["line_colors"] or {})          # the caller's own dict is never the one edited
    if attrs["leg_loc"] not in LEGEND_LOCATIONS:
        raise ValueError(f"leg_loc must be one of {', '.join(LEGEND_LOCATIONS)}, not {attrs['leg_loc']!r}")
    for key in ("title_fs", "xlabel_fs", "ylabel_fs", "leg_fs"):
        v = attrs[key]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not v > 0:
            raise ValueError(f"{key} is a font size in points, not {v!r}")
    if check_colours and attrs["line_colors"]:
        from matplotlib.colors import is_color_like

        for name, colour in attrs["line_colors"].items():
            if not is_color_like(colour):
                raise ValueError(f"the colour for {name!r} is not a colour: {colour!r}")
    if attrs["leg_entries"] is not None:
        try:
            attrs["leg_entries"] = [(str(orig), str(new), bool(shown)) for orig, new, shown in attrs["leg_entries"]]
        except (TypeError, ValueError) as e:
            raise ValueError("leg_entries is a list of (the entry's own name, what to call it, shown)") from e
    return attrs


def record_attrs(attrs):
    """The attributes as a provenance record keeps them: JSON-ready, the caller's dicts untouched."""
    out = dict(attrs)
    out["line_colors"] = dict(out["line_colors"] or {})
    out["leg_entries"] = [list(e) for e in out["leg_entries"]] if out["leg_entries"] else None
    return out


# ---------------------------------------------------------------------------
# Ranges and thinning
# ---------------------------------------------------------------------------

def padded_xlim(x):
    """(lo, hi) for "fit the full trace with a little breathing room" (the library's, so the plot, its export and a replayed view agree)."""
    return api.view.padded_xlim(x)


def min_max_decimate(x, y, xlim, max_points=2000):
    """Reduces (x, y) to at most `max_points`, keeping the min and max of every bin so peaks and troughs survive (a stride
    would smear them out). Only the visible x range is kept (one sample beyond each edge, so the line reaches the edge)."""
    lo, hi = xlim
    i0 = np.searchsorted(x, lo, side='left')
    i1 = np.searchsorted(x, hi, side='right')
    i0 = max(0, i0 - 1)
    i1 = min(len(x), i1 + 1)
    seg_x = x[i0:i1]
    seg_y = y[i0:i1]
    n = len(seg_x)
    if n <= max_points:
        return seg_x, seg_y

    bins = max(1, max_points // 2)
    bin_size = n // bins
    trim = bins * bin_size
    xb = seg_x[:trim].reshape(bins, bin_size)
    yb = seg_y[:trim].reshape(bins, bin_size)

    idx_min = yb.argmin(axis=1)
    idx_max = yb.argmax(axis=1)
    rows = np.arange(bins)
    order = idx_min <= idx_max
    first = np.where(order, idx_min, idx_max)
    second = np.where(order, idx_max, idx_min)

    xs = np.empty(bins * 2)
    ys = np.empty(bins * 2)
    xs[0::2] = xb[rows, first]
    ys[0::2] = yb[rows, first]
    xs[1::2] = xb[rows, second]
    ys[1::2] = yb[rows, second]
    return xs, ys


def view_figsize(width_px, height_px):
    """Inches for a view figure: the plot area's own proportions (so the export looks like the screen), 10 wide."""
    aspect = height_px / width_px if width_px > 0 and height_px > 0 else 0.55
    return 10.0, 10.0 * min(max(aspect, 0.35), 0.9)


# ---------------------------------------------------------------------------
# The traces: the library's lines, styled
# ---------------------------------------------------------------------------

@dataclass
class Trace:
    """One line of the main plot, as the plot engines draw it. `x`/`y` are what is drawn; `y_full` the same signal over the recording's whole time
    axis (NaN where there is none), which is what the data CSV is made of. `key` is the legend name colour overrides are filed under (a group's
    unnamed lines follow the group's), `default_color` what the line is drawn in without one, `snap` whether the live plot's hover marker
    follows it."""
    label: str                         # legend name; "_nolegend_" for a channel that follows its group's entry
    x: np.ndarray
    y: np.ndarray
    color: str
    lw: float
    alpha: float
    csv_name: str
    y_full: np.ndarray = None
    marker: str = None
    markersize: float = 0.0
    key: str = None
    default_color: str = None
    snap: bool = True


# role of a line (the library's) -> (default colour, line width, alpha, does the hover marker follow it)
_ROLE_STYLES = {
    "o2hb_channel": ("#FF9999", 0.8, 0.5, False),
    "hhb_channel": ("#99BBFF", 0.8, 0.5, False),
    "o2hb_mean": ("#CC0000", 2.0, 1.0, True),
    "hhb_mean": ("#0033CC", 2.0, 1.0, True),
    "thb_mean": ("#228B22", 2.0, 1.0, True),
    "corrected": ("blue", 1.5, 0.8, True),
}


def style_traces(planned, line_colors=None):
    """The library's planned lines as the Traces the plot engines draw: a default colour, width and alpha by what the line is, and the
    person's colour for its legend name on top (`line_colors`, {legend name: colour})."""
    overrides = line_colors or {}
    out, columns = [], 0
    for p in planned:
        marker, markersize = None, 0.0
        if p.role == "column":                                 # a generic table's columns cycle through a palette, drawn with a dot per sample
            default, lw, alpha, snap = GENERIC_COLORS[columns % len(GENERIC_COLORS)], 1.8, 1.0, True
            marker, markersize = 'o', 4
            columns += 1
        elif p.role == "signal":
            default, lw, alpha, snap = p.color or signal_color(p.signal), 1.5, 0.8, True
        else:
            default, lw, alpha, snap = _ROLE_STYLES[p.role]
        out.append(Trace(p.label, p.x, p.y, overrides.get(p.key) or default, lw, alpha, p.csv_name, y_full=p.y_full, marker=marker,
                         markersize=markersize, key=p.key, default_color=default, snap=snap))
    return out


def view_traces(cache, *, signals=None, active=None, line_colors=None):
    """(traces, title, x label, y label) for what the main plot draws for a recording, before any edit of its title, labels or legend.

    signals       a TDT recording's signals ticked in the Plot menu (keys of cache["signals"]: "normalized", "main_driver",
                  "isosbestic", ...); more than one are overlaid, in the recording's order. Default: "normalized".
    active        the signal shown when only one is — default: the one ticked (or the first the recording has)
    line_colors   {legend name: colour} overrides, as in the attributes
    """
    planned, title, x_label, y_label = api.view.view_traces(cache, signals=signals, active=active)
    return style_traces(planned, line_colors), title, x_label, y_label


# ---------------------------------------------------------------------------
# Marks on the plot
# ---------------------------------------------------------------------------

def draw_markers(ax, markers, store_labels=None):
    """A dashed line per marker and its name along the line (an unnamed marker is just the tick). The name is a marker's
    store's renamed name (`store_labels`, {store id: shown name}) plus ¹/⁰ for its phase; only the first marker of a name is in the legend.
    Returns [(marker, label Text)] — what a window needs to let the label be dragged."""
    import matplotlib.transforms as transforms

    trans = transforms.blended_transform_factory(ax.transData, ax.transAxes)
    unique_labels = set()
    label_artists = []
    for m in markers:
        text = api.markers.marker_display_label(m, store_labels)
        label_id = text if text not in unique_labels else "_nolegend_"
        unique_labels.add(text)
        ax.axvline(x=m['time'], color=m['color'], linestyle='--', alpha=0.6, label=label_id)
        if not text:
            continue                                      # an unnamed marker is just the tick above — no label to draw or drag
        label_y = m.get('label_y', 0.98)                  # fraction of the axes height, 0 (bottom) to 1 (top)
        artist = ax.text(m['time'], label_y, f" {text}", transform=trans,
                         rotation=90, va='top' if label_y > 0.5 else 'bottom', clip_on=True,
                         fontsize=m.get('fontsize', 8), color=m['color'], fontweight='bold',
                         bbox=dict(facecolor='white', alpha=0.7, edgecolor='none', pad=1))
        label_artists.append((m, artist))
    return label_artists


def draw_highlights(ax, highlights):
    """A translucent span per highlight, behind everything else."""
    for h in highlights:
        ax.axvspan(h['start'], h['end'], color=h['color'], alpha=api.saved.highlight_alpha, zorder=0)


def draw_text_annotations(ax, annotations):
    """Free-floating text at each box's (x, y) data position. Returns [(annotation, Text)]."""
    artists = []
    for t in annotations:
        artist = ax.text(t['x'], t['y'], t['text'], fontsize=t.get('fontsize', 10), color='black', zorder=5, clip_on=True)
        artists.append((t, artist))
    return artists


def _legend(ax, attrs):
    """The legend as Edit Graph Attributes left it: entries renamed or hidden, its size and place. An entry's line carries the
    name that is shown, so the figure's data (figures/data.py) uses it too."""
    handles, labels = ax.get_legend_handles_labels()
    entries = [(h, label) for h, label in zip(handles, labels) if not label.startswith('_')]
    if not entries:
        return
    edits = {orig: (new, shown) for orig, new, shown in (attrs["leg_entries"] or [])}
    keep_handles, keep_labels = [], []
    for handle, label in entries:
        new, shown = edits.get(label, (label, True))
        if shown:
            handle.set_label(new)
            keep_handles.append(handle)
            keep_labels.append(new)
    if keep_handles:
        ax.legend(keep_handles, keep_labels, fontsize=max(5, attrs["leg_fs"]), loc=attrs["leg_loc"])


# ---------------------------------------------------------------------------
# The view
# ---------------------------------------------------------------------------

@dataclass
class ViewExport:
    """A view of a recording: the library's plan of what is shown (`plan`: the range, the markers in it, the title and labels, the numbers
    of the data CSV), the lines styled (`traces`), the attributes it is drawn with and, once drawn, the figure. `fig` is None for a view
    that was only planned (plan_view) — enough for the data CSVs."""
    fig: object
    plan: object
    traces: list
    attrs: dict

    xlim = property(lambda self: self.plan.xlim)
    ylim = property(lambda self: self.plan.ylim)
    x_name = property(lambda self: self.plan.x_name)
    x = property(lambda self: self.plan.x)
    markers = property(lambda self: self.plan.markers)
    signals = property(lambda self: self.plan.signals)
    show_grid = property(lambda self: self.plan.show_grid)
    title = property(lambda self: self.plan.title)
    x_label = property(lambda self: self.plan.x_label)
    y_label = property(lambda self: self.plan.y_label)
    in_view = property(lambda self: self.plan.in_view)

    def parameters(self):
        """What it takes to make this view again (the library's run_view): the range, the signals, the grid and the attributes. JSON-ready."""
        return self.plan.parameters()

    def data_table(self):
        return self.plan.data_table()

    def markers_table(self):
        return self.plan.markers_table()

    def write_data(self, base):
        """<base>_data.csv (every sample in view) and, if any marker is in view, <base>_markers.csv. Returns the paths."""
        return self.plan.write_data(base)

    def save(self, path, **options):
        """Writes the figure and, unless `data=False`, its data CSVs, as Export Figure does (render.save_figure): the format from
        the extension, `dpi`, `transparent`, `editable_text`, `labels` (rename words for the file only), `software`. Returns the
        files written."""
        from .render import save_figure
        if self.fig is None:
            raise ValueError("this view was planned, not drawn: make it with build_view")
        return save_figure(self.fig, path, data_writer=self.write_data, **options)


def plan_view(cache, *, attrs=None, signals=None, active=None, xlim=None, ylim=None, show_grid=True, store_labels=None):
    """What build_view will draw, without drawing it: a ViewExport with no figure — its data_table() and write_data() are what Export View's
    CSVs hold."""
    attrs = {**default_plot_attrs(), **(attrs or {})}
    plan = api.view.plan_view(cache, signals=signals, active=active, xlim=xlim, ylim=ylim, show_grid=show_grid, store_labels=store_labels,
                              attributes=record_attrs(attrs))
    return ViewExport(None, plan, style_traces(plan.traces, attrs["line_colors"]), attrs)


def build_view(cache, *, attrs=None, signals=None, active=None, xlim=None, ylim=None, show_grid=True, store_labels=None,
               figsize=None, max_points=None, figure=None):
    """The main plot of `cache` (a recording, as load_recording returns it) redrawn as a ViewExport: white page, black text,
    every trace at up to EXPORT_MAX_POINTS points (min/max thinned, so no peak is lost).

    attrs         what Edit Graph Attributes edits (see the module docstring; missing keys take their defaults)
    signals, active   a TDT recording's signals to draw (see view_traces)
    xlim, ylim    the range to show, (low, high) in seconds / signal units. Default: all of the recording with a little room;
                  the y range then follows the data
    show_grid     the grid, as the Show Grid box
    store_labels  {store id: shown name}: the renames in force for marker names
    figsize       inches (default 10 x 5.5)
    figure        the factory that makes the figure (matplotlib.figure.Figure by default, pyplot.figure for a window)
    """
    from matplotlib.figure import Figure

    view = plan_view(cache, attrs=attrs, signals=signals, active=active, xlim=xlim, ylim=ylim, show_grid=show_grid, store_labels=store_labels)
    attrs, (lo, hi) = view.attrs, view.xlim
    limit = max_points if max_points is not None else EXPORT_MAX_POINTS

    fig = (figure or Figure)(figsize=figsize or DEFAULT_FIGURE_SIZE)
    ax = fig.subplots()
    ax.axhline(0, color='black', linewidth=1.0, alpha=0.4, zorder=1)
    if cache.get('source') == 'TDT':
        ax.axvline(0, color='black', linewidth=1.0, alpha=0.4, zorder=1)
    for t in view.traces:
        dx, dy = min_max_decimate(t.x, t.y, (lo, hi), max_points=limit)
        style = dict(marker=t.marker, markersize=t.markersize) if t.marker else {}
        ax.plot(dx, dy, color=t.color, lw=t.lw, alpha=t.alpha, label=t.label, **style)

    draw_markers(ax, view.in_view, store_labels)
    draw_highlights(ax, [h for h in cache.get('highlights', []) if h['end'] >= lo and h['start'] <= hi])
    draw_text_annotations(ax, cache.get('text_annotations', []))

    weight = 'bold' if attrs.get("bold", True) else 'normal'
    ax.set_title(attrs["title"] or view.title, fontweight=weight, pad=15, fontsize=max(8, attrs["title_fs"]))
    ax.set_xlabel(attrs["xlabel"] or view.x_label, fontweight=weight, fontsize=max(6, attrs["xlabel_fs"]))
    ax.set_ylabel(attrs["ylabel"] or view.y_label, fontweight=weight, fontsize=max(6, attrs["ylabel_fs"]))
    _legend(ax, attrs)
    ax.set_xlim(lo, hi)
    if view.ylim is not None:
        ax.set_ylim(*view.ylim)
    if view.show_grid:
        ax.grid(True, linestyle=':', alpha=0.4, color=GRID_COLOR)
    view.fig = fig
    return view

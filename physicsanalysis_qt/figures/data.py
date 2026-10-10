"""
figures/data.py
---------------
The data behind a matplotlib figure, as tables: a CSV of exactly what is drawn, whatever drew it. Read from
the figure's artists rather than rebuilt from the analysis, so it is always what is on the page — the
checked trials only, the edited labels, a customized measures figure — and it works for any figure the app
makes (or will make) without each one needing its own export code.

    tables = figure_tables(fig)
    tables["data"]       one row per plotted point:  panel, series, kind, x, x_tick, y, y_lower, y_upper, x_label, y_label
    tables["image_1"]    a heatmap as a grid: one row per image row (its position, and its label if the figure
                         has them, e.g. the trial or subject), one column per x position

What becomes rows of "data"
    line     a Line2D: x, y            (axvline/axhline and anything not drawn in data coordinates is skipped)
    band     fill_between of two curves: x, y_lower, y_upper      (the SEM band around a mean). Shading down to
             a constant (a trace filled to zero) is not data and is skipped
    bar      a bar: x (its centre), y (its height), y_lower/y_upper (its bottom and top)
    points   scatter: x, y
    errorbar the points of an errorbar plot, with y_lower/y_upper at the ends of its bars
    box      a box plot, as the figure reports it (ax.pyat_series, below): y the median, y_lower/y_upper the quartiles
`x_tick` is the name of a category when the x axis is categorical (bars labelled by group): the label of the tick the
row sits on (or beside, for a jittered dot).

A figure can tell this module more than matplotlib knows:
    ax.pyat_panel          the panel's name, when it has no title
    ax.pyat_row_labels     a heatmap's row labels, one per row (Event PETH: each row's trial number)
    ax.pyat_series         extra rows [{"series", "kind", "x", "y", "y_lower", "y_upper"}, ...] for what the artists
                           don't say (a box plot's statistics)
    artist.pyat_skip       True: decoration, not data (a significance bracket, a box plot's whiskers)
Invisible and animated artists (the hover tracker) are skipped.
"""

import numpy as np
import pandas as pd

# matplotlib is imported inside the functions that look at a figure: importing the library never loads it.

DATA_COLUMNS = ["panel", "series", "kind", "x", "x_tick", "y", "y_lower", "y_upper", "x_label", "y_label"]


def _skipped(artist):
    return getattr(artist, "pyat_skip", False) or not artist.get_visible() or artist.get_animated()


def _is_reference_line(ax, line):
    """axvline/axhline and anything else not drawn in data coordinates on both axes."""
    in_data = line.get_transform().contains_branch_seperately(ax.transData)
    return not all(in_data)


def _band_segments(collection):
    """[(x, y_lower, y_upper), ...] of a fill_between polygon collection: each path is the lower boundary forward
    then the upper boundary back, wrapped in a start/end vertex (1 + n + 1 + n + 1 vertices)."""
    out = []
    for path in collection.get_paths():
        v = np.asarray(path.vertices, dtype=float)
        n = (len(v) - 3) // 2
        if n < 1 or len(v) != 2 * n + 3:
            continue
        x = v[1:1 + n, 0]
        y1 = v[1:1 + n, 1]
        y2 = v[n + 2:2 * n + 2, 1][::-1]
        out.append((x, y1, y2))
    return out


def _is_band(collection):
    """A fill_between of two curves. A fill down to a constant (the shading of a trace to zero, as AUC and Event
    PETH do) is not: it adds nothing the line it shades doesn't already say."""
    if type(collection).__name__ not in ("FillBetweenPolyCollection", "PolyCollection"):
        return False
    segments = _band_segments(collection)
    return bool(segments) and not all(np.ptp(lo) == 0 or np.ptp(hi) == 0 for _x, lo, hi in segments)


def _vertical_segments(collection):
    """(x, low, high) per segment of a LineCollection if all of them are vertical (a y-error bar), else None."""
    segs = collection.get_segments()
    if not segs or any(len(sg) != 2 or sg[0][0] != sg[1][0] for sg in segs):
        return None
    return np.array([[sg[0][0], min(sg[0][1], sg[1][1]), max(sg[0][1], sg[1][1])] for sg in segs], dtype=float)


def panel_name(ax, index):
    """The axes' title if it has one (so an edited title is the panel's name), else the figure's own name for it
    (`ax.pyat_panel`), else "panel <n>"."""
    title = ax.get_title() or ax.get_title(loc="left") or ax.get_title(loc="right")
    return title.strip() or getattr(ax, "pyat_panel", None) or f"panel {index}"


def _category_ticks(ax):
    """{tick position: its label} when the x axis is categorical (its labels were set by hand or by category), else {}."""
    from matplotlib.ticker import FixedFormatter, FuncFormatter

    formatter = ax.xaxis.get_major_formatter()
    if not isinstance(formatter, (FixedFormatter, FuncFormatter)) and type(formatter).__name__ != "StrCategoryFormatter":
        return {}                                           # the plain numeric formatter: its labels are just the numbers
    labels = [t.get_text() for t in ax.get_xticklabels()]
    return {float(p): label for p, label in zip(ax.get_xticks(), labels) if label}


class _Panel:
    def __init__(self, ax, index):
        self.name = panel_name(ax, index)
        self.x_label = ax.get_xlabel()
        self.y_label = ax.get_ylabel()
        self.rows = []
        self.n_series = 0
        self.categories = _category_ticks(ax)
        positions = np.array(sorted(self.categories))
        spacing = np.min(np.diff(positions)) if len(positions) > 1 else 1.0
        self._reach = 0.35 * spacing                     # a jittered dot still belongs to the bar it sits on

    def tick_for(self, x):
        if not self.categories or not np.isfinite(x):
            return ""
        nearest = min(self.categories, key=lambda p: abs(p - x))
        return self.categories[nearest] if abs(nearest - x) <= self._reach else ""

    def add(self, series, kind, x, y=None, y_lower=None, y_upper=None):
        n = len(x)
        y = np.full(n, np.nan) if y is None else y
        y_lower = np.full(n, np.nan) if y_lower is None else y_lower
        y_upper = np.full(n, np.nan) if y_upper is None else y_upper
        for i in range(n):
            self.rows.append([self.name, series, kind, x[i], self.tick_for(x[i]), y[i], y_lower[i], y_upper[i],
                              self.x_label, self.y_label])

    def series_name(self, label, fallback):
        self.n_series += 1
        return label if label and not label.startswith("_") else f"{fallback} {self.n_series}"


def _axes_to_rows(ax, index):
    from matplotlib.collections import LineCollection, PathCollection
    from matplotlib.colors import to_rgb
    from matplotlib.container import BarContainer, ErrorbarContainer
    from matplotlib.patches import Rectangle

    p = _Panel(ax, index)
    skip = set()
    for container in ax.containers:
        if isinstance(container, ErrorbarContainer):
            data_line, caps, bars = container.lines
            for artist in (data_line, *caps, *bars):                                   # the caps are Line2Ds of their own
                if artist is not None:
                    skip.add(id(artist))
            y_bars = next((_vertical_segments(c) for c in bars if isinstance(c, LineCollection) and _vertical_segments(c) is not None), None)
            if data_line is not None:
                x = np.asarray(data_line.get_xdata(), dtype=float)
                y = np.asarray(data_line.get_ydata(), dtype=float)
            elif y_bars is not None:                                                   # fmt="none": the bars alone, so no y of the point
                x, y = y_bars[:, 0], None
            else:
                continue
            lo, hi = np.full(len(x), np.nan), np.full(len(x), np.nan)
            if y_bars is not None and len(y_bars) == len(x):
                lo, hi = y_bars[:, 1], y_bars[:, 2]
            p.add(p.series_name(container.get_label(), "errorbar"), "errorbar", x, y, lo, hi)
        elif isinstance(container, BarContainer):
            for r in container.patches:
                skip.add(id(r))
            rects = [r for r in container.patches if isinstance(r, Rectangle)]
            if rects:
                x = np.array([r.get_x() + r.get_width() / 2 for r in rects])
                bottom = np.array([r.get_y() for r in rects])
                height = np.array([r.get_height() for r in rects])
                p.add(p.series_name(container.get_label(), "bar"), "bar", x, height, bottom, bottom + height)
    line_names = {}                                                                    # colour -> the name of the line drawn in it
    for line in ax.lines:
        if id(line) in skip or _skipped(line) or _is_reference_line(ax, line):
            continue
        x = np.asarray(line.get_xdata(orig=False), dtype=float)
        y = np.asarray(line.get_ydata(orig=False), dtype=float)
        if len(x):
            name = p.series_name(line.get_label(), "line")
            line_names.setdefault(to_rgb(line.get_color()), name)
            p.add(name, "line", x, y)
    for coll in ax.collections:
        if id(coll) in skip or _skipped(coll):
            continue
        if _is_band(coll):
            for x, lo, hi in _band_segments(coll):
                label = coll.get_label()
                if label and not label.startswith("_"):
                    name = label
                else:                                                                  # a band is named for the line it surrounds
                    owner = line_names.get(tuple(coll.get_facecolor()[0][:3]))
                    name = f"{owner} band" if owner else p.series_name(label, "band")
                p.add(name, "band", x, None, lo, hi)
        elif isinstance(coll, PathCollection) and len(coll.get_offsets()):
            off = np.asarray(coll.get_offsets(), dtype=float)
            p.add(p.series_name(coll.get_label(), "points"), "points", off[:, 0], off[:, 1])
    for extra in getattr(ax, "pyat_series", None) or []:
        p.add(extra["series"], extra.get("kind", "points"), [extra["x"]], [extra.get("y", np.nan)],
              [extra.get("y_lower", np.nan)], [extra.get("y_upper", np.nan)])
    return p.rows


def _image_tables(ax, panel, start):
    from matplotlib.image import AxesImage

    out = {}
    for k, im in enumerate(i for i in ax.images if isinstance(i, AxesImage) and i.get_visible()):
        arr = np.ma.filled(np.ma.asarray(im.get_array()).astype(float), np.nan)
        if arr.ndim != 2:
            continue
        x0, x1, y_bottom, y_top = im.get_extent()
        n_rows, n_cols = arr.shape
        xs = x0 + (np.arange(n_cols) + 0.5) * (x1 - x0) / n_cols
        ys = y_top + (np.arange(n_rows) + 0.5) * (y_bottom - y_top) / n_rows         # row 0 is drawn at the top of the extent
        table = pd.DataFrame(arr, columns=[f"{x:.10g}" for x in xs])
        table.insert(0, "row_position", ys)
        labels = getattr(ax, "pyat_row_labels", None)
        if labels is not None and len(labels) == n_rows:
            table.insert(0, "row", list(labels))
        table.insert(0, "panel", panel)
        out[f"image_{start + k}"] = table
    return out


def figure_tables(fig):
    """{name: DataFrame} for everything plotted in `fig` (see the module docstring). Empty tables are left out."""
    rows, images = [], {}
    n_images = 1
    for i, ax in enumerate(fig.axes, 1):
        rows += _axes_to_rows(ax, i)
        found = _image_tables(ax, panel_name(ax, i), n_images)
        n_images += len(found)
        images.update(found)
    tables = {}
    if rows:
        tables["data"] = pd.DataFrame(rows, columns=DATA_COLUMNS)
    tables.update(images)
    return tables


def write_figure_data(fig, base_path):
    """Writes figure_tables(fig) as CSV: <base_path>_data.csv, <base_path>_image_1.csv, ... (UTF-8, full
    precision). `base_path` has no extension. Returns the paths written ([] if the figure plots nothing)."""
    paths = []
    for name, table in figure_tables(fig).items():
        path = f"{base_path}_{name}.csv"
        table.to_csv(path, index=False, encoding="utf-8")
        paths.append(path)
    return paths

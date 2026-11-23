"""
figures/render.py
-----------------
Writing a matplotlib figure to a file for a manuscript, with no window involved — what PyAT's Export Figure dialog,
the group analysis's automatic figures and `plotlatest(save=...)` all do, the same way:

    render_figure(fig, "figure.pdf", fmt="pdf")

  - PNG or TIFF at any resolution, or PDF / SVG as vector files. In a vector file the text stays text (editable in
    Illustrator or Inkscape, set in the fonts it was drawn with) unless editable_text is turned off, when the
    letters become outlines and look the same everywhere.
  - Trimmed to the figure's content with a small margin, or, with `size=(width, height)` in inches, exactly that size: the
    figure is laid out again to fit it (text keeps its size in points, so a smaller figure has relatively larger text), and a
    PNG or TIFF has exactly width x dpi by height x dpi pixels.
  - Points (scatter points, and the markers of lines drawn with them) can be made larger or smaller for the file (`point_scale`, 0.1 to 10 times what
    was drawn); lines, bars, bands, heatmaps and text are not changed.
  - No clock and no random ids in PDF/SVG, so the same figure written twice is the same file.
  - Text can be swapped for the export only (`edits`, see labels.py): the figure is put back after.

and `save_figure()` does what the dialog does around that: the format from the file name, the CSV of the data behind
the figure beside it, and words renamed by what they say now.
"""

import math
import os
import warnings
from contextlib import contextmanager

from .. import __version__
from .data import write_figure_data
from .labels import edited_texts, text_items

# key: (what the dialog calls it, file extension, file-dialog filter, matplotlib's name for it)
FORMATS = {
    "png":  ("PNG image", "png", "PNG Image (*.png)", "png"),
    "pdf":  ("PDF (vector)", "pdf", "PDF Document (*.pdf)", "pdf"),
    "svg":  ("SVG (vector)", "svg", "SVG Vector (*.svg)", "svg"),
    "tiff": ("TIFF image", "tif", "TIFF Image (*.tif *.tiff)", "tiff"),
}
VECTOR_FORMATS = ("pdf", "svg")
DEFAULTS = {"format": "png", "dpi": 300, "transparent": False, "editable_text": True, "data_csv": True}
MIN_DPI, MAX_DPI = 72, 1200
MIN_POINT_SCALE, MAX_POINT_SCALE = 0.1, 10.0                # how much larger or smaller than drawn the points of a figure may be written
PREVIEW_DPI = 90
PREVIEW_MAX = (560, 340)                    # pixels the preview may take in the dialog
PAD_INCHES = 0.1
MIN_SIZE_IN, MAX_SIZE_IN = 1.0, 30.0        # the sizes (inches) a figure can be given
MAX_PIXELS = 120_000_000                    # the most pixels a PNG/TIFF may have (about 480 MB in memory while it is written)


def _metadata(fmt, software=None):
    """What goes in the file's own metadata: the software (`software`, e.g. "PyAT 3.2.0"; PyAT's own name
    and version by default), and no clock — so the same figure exported twice is the same file (the provenance record
    carries the date)."""
    creator = software or f"PyAT {__version__}"
    if fmt == "pdf":
        return {"Creator": creator, "Producer": creator, "CreationDate": None}
    if fmt == "svg":
        return {"Creator": creator, "Date": None}
    if fmt == "png":
        return {"Software": creator}
    return None


def checked_size(size, fmt="png", dpi=300):
    """`size` as (width, height) floats in inches, or None. ValueError if it is not two numbers between MIN_SIZE_IN and MAX_SIZE_IN, or
    if a PNG/TIFF of that size at `dpi` would have more than MAX_PIXELS pixels."""
    if size is None:
        return None
    try:
        w, h = (float(v) for v in size)
    except (TypeError, ValueError):
        raise ValueError(f"size must be (width, height) in inches, not {size!r}") from None
    if not (math.isfinite(w) and math.isfinite(h) and MIN_SIZE_IN <= w <= MAX_SIZE_IN and MIN_SIZE_IN <= h <= MAX_SIZE_IN):
        raise ValueError(f"size must be between {MIN_SIZE_IN:g} and {MAX_SIZE_IN:g} inches each way, not {w:g} x {h:g}")
    if fmt not in VECTOR_FORMATS and w * dpi * h * dpi > MAX_PIXELS:
        raise ValueError(f"{w:g} x {h:g} in at {dpi} dpi is {w * dpi * h * dpi / 1e6:.0f} megapixels; the most a file may have is "
                         f"{MAX_PIXELS / 1e6:.0f}. Make the figure smaller or lower the dpi")
    return w, h


@contextmanager
def _sized(fig, size, dpi, whole_pixels):
    """For the length of the block, `fig` is `size` (inches) and laid out again to fit it; afterwards it is as it was, size and layout (the
    figure on screen is never left changed). A raster file is a whole number of pixels, so its size is put on the pixel grid (matplotlib
    truncates, so a hair over: 3.35 in x 300 dpi is 1005 pixels, not 1004.9999). A figure with a layout engine of its own
    (constrained or tight layout) lays itself out again as it is drawn; any other is fitted with tight_layout."""
    if size is None:
        yield
        return
    w, h = size
    if whole_pixels:
        w, h = (round(w * dpi) + 0.01) / dpi, (round(h * dpi) + 0.01) / dpi
    old_size = tuple(fig.get_size_inches())
    pars = fig.subplotpars
    old_pars = {"left": pars.left, "right": pars.right, "bottom": pars.bottom, "top": pars.top, "wspace": pars.wspace, "hspace": pars.hspace}
    engine = fig.get_layout_engine() if hasattr(fig, "get_layout_engine") else None
    own_layout = engine is not None and type(engine).__name__ != "PlaceHolderLayoutEngine"
    try:
        fig.set_size_inches(w, h, forward=False)                  # forward=False: a window showing the figure is not resized
        if not own_layout:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")                    # "tight_layout not applied": the figure is left as it is
                fig.tight_layout()
        yield
    finally:
        fig.set_size_inches(*old_size, forward=False)
        if not own_layout:
            fig.subplots_adjust(**old_pars)
            if engine is None and hasattr(fig, "set_layout_engine"):
                fig.set_layout_engine(None)                       # tight_layout leaves a do-nothing placeholder behind: back to none


def checked_point_scale(scale):
    """`scale` as a float, or None. ValueError if it is not a number between MIN_POINT_SCALE and MAX_POINT_SCALE."""
    if scale is None:
        return None
    try:
        scale = float(scale)
    except (TypeError, ValueError):
        raise ValueError(f"point_scale must be a number, not {scale!r}") from None
    if not (math.isfinite(scale) and MIN_POINT_SCALE <= scale <= MAX_POINT_SCALE):
        raise ValueError(f"point_scale must be between {MIN_POINT_SCALE:g} and {MAX_POINT_SCALE:g} times the size drawn, not {scale:g}")
    return scale


def _has_marker(line):
    return line.get_marker() not in (None, "None", "none", "", " ") and line.get_markersize() > 0


def _is_scatter(artist):
    return type(artist).__name__ == "PathCollection"


def figure_points(fig):
    """The artists of `fig` that are points: scatter collections, lines drawn with markers (an error bar's caps are not) and the same in its
    legends — what a point size changes."""
    caps = {id(cap) for ax in fig.axes for container in ax.containers for cap in (getattr(container, "lines", None) or (None, (), ()))[1]}
    found = []
    for ax in fig.axes:
        found += [c for c in ax.collections if _is_scatter(c)]
        found += [line for line in ax.lines if _has_marker(line) and id(line) not in caps]
    legends = [ax.get_legend() for ax in fig.axes] + list(fig.legends)
    for legend in legends:
        for handle in (getattr(legend, "legend_handles", None) or getattr(legend, "legendHandles", None) or []) if legend is not None else []:
            if _is_scatter(handle) or (hasattr(handle, "get_marker") and _has_marker(handle)):
                found.append(handle)
    return found


def has_points(fig):
    """Whether `fig` has anything a point size would change."""
    return bool(figure_points(fig))


@contextmanager
def _points_scaled(fig, scale):
    """For the length of the block every point of `fig` is `scale` times as large as it was drawn (a scatter point's width and height, a line's
    marker); afterwards each is as it was. The size of a scatter point is its area, so it is multiplied by scale squared."""
    if scale is None or scale == 1.0:
        yield
        return
    originals = []
    try:
        for artist in figure_points(fig):
            if _is_scatter(artist):
                sizes = artist.get_sizes()
                originals.append((artist, sizes.copy()))
                artist.set_sizes(sizes * scale ** 2)
            else:
                originals.append((artist, artist.get_markersize()))
                artist.set_markersize(artist.get_markersize() * scale)
        yield
    finally:
        for artist, old in originals:
            artist.set_sizes(old) if _is_scatter(artist) else artist.set_markersize(old)


def render_figure(fig, target, *, fmt="png", dpi=300, transparent=False, editable_text=True, edits=None, software=None, size=None, point_scale=None):
    """Writes `fig` to `target` (a path or a binary file object) as `fmt` ("png", "pdf", "svg" or "tiff"), trimmed
    to its content — or, with `size=(width, height)` in inches (MIN_SIZE_IN to MAX_SIZE_IN), at exactly that size, laid out
    again to fit it. `edits` ({TextItem: new text}, see labels.py) is in force while it is written. `software`
    names the program in the file's metadata. `point_scale` makes every point `point_scale` times as large as drawn (0.1 to 10)."""
    from matplotlib import rc_context

    size = checked_size(size, fmt, dpi)
    point_scale = checked_point_scale(point_scale)

    editable = bool(editable_text)
    rc = {
        "svg.fonttype": "none" if editable else "path",         # text stays text / becomes outlines
        "pdf.fonttype": 42 if editable else 3,                  # TrueType (editable) / Type 3
        "ps.fonttype": 42 if editable else 3,
        "svg.hashsalt": "PyAT",                                 # the ids in an SVG are the same every time
    }
    kwargs = {"format": FORMATS[fmt][3], "dpi": int(dpi), "transparent": bool(transparent)}
    if size is None:
        kwargs.update(bbox_inches="tight", pad_inches=PAD_INCHES)
    meta = _metadata(fmt, software)
    if meta:
        kwargs["metadata"] = meta
    if fmt == "tiff":
        kwargs["pil_kwargs"] = {"compression": "tiff_lzw"}
    with rc_context(rc), edited_texts(edits), _points_scaled(fig, point_scale), _sized(fig, size, int(dpi), fmt not in VECTOR_FORMATS):      # (laid out with the edited words)
        fig.savefig(target, **kwargs)


def format_of(path, fmt=None):
    """The format key ("png", "pdf", "svg", "tiff") for a file name's extension — or `fmt`, if it is given."""
    if fmt is None:
        ext = os.path.splitext(os.fspath(path))[1].lstrip(".").lower()
        fmt = "tiff" if ext == "tif" else ext
    if fmt not in FORMATS:
        raise ValueError(f"Cannot write {os.fspath(path)} as a figure: the formats are png, tiff (.tif or .tiff), pdf and svg")
    return fmt


def edits_for(fig, labels):
    """{TextItem: new text} for `labels`, {what the figure says now: what the file should say}. A text that appears more
    than once (an axis label two panels share) is renamed everywhere. A name the figure does not say is an error that
    lists what it does say — a misspelt label is never silently left as it was."""
    if not labels:
        return {}
    items = text_items(fig)
    said = {item.text for item in items}
    unknown = [old for old in labels if old not in said]
    if unknown:
        raise ValueError("The figure does not say " + ", ".join(repr(u) for u in unknown) + "; it says: "
                         + "; ".join(repr(t) for t in sorted(said)))
    return {item: labels[item.text] for item in items if item.text in labels}


def save_figure(fig, path, *, fmt=None, dpi=300, transparent=False, editable_text=True, labels=None, data=True, software=None,
                data_writer=None, size=None, point_scale=None):
    """Writes `fig` to `path` as the Export Figure dialog would, and returns the files written: the figure, then (unless
    `data` is False) the CSV of the data behind it beside it (<name>_data.csv, and <name>_image_<n>.csv for a heatmap).

    The format comes from the extension (png, tif/tiff, pdf, svg) unless `fmt` says. `dpi` (72 to 1200) is for the
    pictures; in a PDF or SVG the text stays editable text unless `editable_text` is False. `labels` renames words for
    the file only, {what the figure says: what it should say} — the figure itself, and so a window showing it, is
    untouched, and the CSV says the new words too. `software` names the program in the file's metadata. `data_writer(base)`
    writes the data CSVs itself (returning their paths) when the generic read-off-the-artists extraction is not right for the
    figure — Export View's is every sample in view. `size` is (width, height) in inches (1 to 30 each) to write the figure at exactly
    that size, laid out again to fit it, instead of trimmed to its content as it is on screen. `point_scale` (0.1 to 10) writes every point
    (scatter points, the markers of lines) that many times as large as drawn; lines, bars and text are as drawn."""
    fmt = format_of(path, fmt)
    if not MIN_DPI <= int(dpi) <= MAX_DPI:
        raise ValueError(f"dpi must be between {MIN_DPI} and {MAX_DPI}, not {dpi}")
    checked_size(size, fmt, dpi)                                    # refused before anything is written
    checked_point_scale(point_scale)
    path = os.fspath(path)
    edits = edits_for(fig, labels)
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    render_figure(fig, path, fmt=fmt, dpi=dpi, transparent=transparent, editable_text=editable_text, edits=edits, software=software, size=size,
                  point_scale=point_scale)
    written = [path]
    if data:
        with edited_texts(edits):                                    # the CSV says what the figure says
            written += (data_writer or (lambda base: write_figure_data(fig, base)))(os.path.splitext(path)[0])
    return written


def figure_notes(settings, edits):
    """The lines about this export that go in its provenance record: how the file was made, and each label
    that was changed from what the figure said."""
    fmt = settings["format"]
    line = f"Figure exported as {FORMATS[fmt][0]}"
    if fmt in VECTOR_FORMATS:
        line += f", text {'kept as editable text' if settings['editable_text'] else 'converted to outlines'}"
    else:
        line += f" at {settings['dpi']} dpi"
    if settings["transparent"]:
        line += ", transparent background"
    if settings.get("size"):
        line += f", size set to {settings['size'][0]:.2f} x {settings['size'][1]:.2f} in"
    if settings.get("point_scale"):
        line += f", points drawn at {settings['point_scale'] * 100:.0f}% of their size"
    notes = [line]
    for item, new in (edits or {}).items():
        notes.append(f"Label edited ({item.caption}): {item.text!r} -> {new!r}")
    return notes

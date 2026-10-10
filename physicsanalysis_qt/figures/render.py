"""
figures/render.py
-----------------
Writing a matplotlib figure to a file for a manuscript, with no window involved — what PyAT's Export Figure dialog,
the group analysis's automatic figures and `plotlatest(save=...)` all do, the same way:

    render_figure(fig, "figure.pdf", fmt="pdf")

  - PNG or TIFF at any resolution, or PDF / SVG as vector files. In a vector file the text stays text (editable in
    Illustrator or Inkscape, set in the fonts it was drawn with) unless editable_text is turned off, when the
    letters become outlines and look the same everywhere.
  - Trimmed to the figure's content with a small margin.
  - No clock and no random ids in PDF/SVG, so the same figure written twice is the same file.
  - Text can be swapped for the export only (`edits`, see labels.py): the figure is put back after.

and `save_figure()` does what the dialog does around that: the format from the file name, the CSV of the data behind
the figure beside it, and words renamed by what they say now.
"""

import os

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
PREVIEW_DPI = 90
PREVIEW_MAX = (560, 340)                    # pixels the preview may take in the dialog
PAD_INCHES = 0.1


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


def render_figure(fig, target, *, fmt="png", dpi=300, transparent=False, editable_text=True, edits=None, software=None):
    """Writes `fig` to `target` (a path or a binary file object) as `fmt` ("png", "pdf", "svg" or "tiff"), trimmed
    to its content. `edits` ({TextItem: new text}, see labels.py) is in force while it is written. `software`
    names the program in the file's metadata."""
    from matplotlib import rc_context

    editable = bool(editable_text)
    rc = {
        "svg.fonttype": "none" if editable else "path",         # text stays text / becomes outlines
        "pdf.fonttype": 42 if editable else 3,                  # TrueType (editable) / Type 3
        "ps.fonttype": 42 if editable else 3,
        "svg.hashsalt": "PyAT",                                 # the ids in an SVG are the same every time
    }
    kwargs = {"format": FORMATS[fmt][3], "dpi": int(dpi), "bbox_inches": "tight", "pad_inches": PAD_INCHES,
              "transparent": bool(transparent)}
    meta = _metadata(fmt, software)
    if meta:
        kwargs["metadata"] = meta
    if fmt == "tiff":
        kwargs["pil_kwargs"] = {"compression": "tiff_lzw"}
    with rc_context(rc), edited_texts(edits):
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
                data_writer=None):
    """Writes `fig` to `path` as the Export Figure dialog would, and returns the files written: the figure, then (unless
    `data` is False) the CSV of the data behind it beside it (<name>_data.csv, and <name>_image_<n>.csv for a heatmap).

    The format comes from the extension (png, tif/tiff, pdf, svg) unless `fmt` says. `dpi` (72 to 1200) is for the
    pictures; in a PDF or SVG the text stays editable text unless `editable_text` is False. `labels` renames words for
    the file only, {what the figure says: what it should say} — the figure itself, and so a window showing it, is
    untouched, and the CSV says the new words too. `software` names the program in the file's metadata. `data_writer(base)`
    writes the data CSVs itself (returning their paths) when the generic read-off-the-artists extraction is not right for the
    figure — Export View's is every sample in view."""
    fmt = format_of(path, fmt)
    if not MIN_DPI <= int(dpi) <= MAX_DPI:
        raise ValueError(f"dpi must be between {MIN_DPI} and {MAX_DPI}, not {dpi}")
    path = os.fspath(path)
    edits = edits_for(fig, labels)
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    render_figure(fig, path, fmt=fmt, dpi=dpi, transparent=transparent, editable_text=editable_text, edits=edits, software=software)
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
    notes = [line]
    for item, new in (edits or {}).items():
        notes.append(f"Label edited ({item.caption}): {item.text!r} -> {new!r}")
    return notes

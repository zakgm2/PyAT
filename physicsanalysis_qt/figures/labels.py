"""
figures/labels.py
-----------------
The words on a matplotlib figure that can be changed before it is exported: its titles, each panel's title
and axis labels, a colour bar's label, the entries of a legend. The export dialog (figure_export.py) lists them
as text fields; what is typed there goes into the exported file — and into the CSV of the figure's data — but
not into the live figure, which is put back exactly as it was when the export is done.

    items = text_items(fig)                 # [TextItem(caption, artist), ...] in reading order
    with edited_texts({items[0]: "My title"}):
        fig.savefig("fig.pdf")              # items[0]'s text is "My title" in here, its old text again after

Only the text is changed — never its font, size, colour or position — so an edited figure keeps the look the
app gave it. A legend entry names a series, so editing one renames the series itself too (the artists whose label
it is), and the figure's data CSV then calls it by the new name.
"""

from contextlib import contextmanager

from .data import panel_name

COLORBAR_AXES_LABEL = "<colorbar>"         # what matplotlib calls the axes of a colour bar


class TextItem:
    """One editable piece of text: what to call it (`caption`) and the matplotlib Text it is. For a legend
    entry, `series` holds the plotted artists that carry that name."""

    def __init__(self, caption, artist, series=()):
        self.caption = caption
        self.artist = artist
        self.series = list(series)

    @property
    def text(self):
        return self.artist.get_text()

    def __repr__(self):
        return f"TextItem({self.caption!r}, {self.text!r})"


def _is_colorbar(ax):
    return ax.get_label() == COLORBAR_AXES_LABEL


def _labelled_artists(ax):
    return [*ax.lines, *ax.collections, *ax.patches, *ax.containers]


def _legend_items(legends, caption_for, artists):
    items = []
    for n, t in enumerate(legends.get_texts(), 1):
        if t.get_text().strip():
            name = t.get_text()
            items.append(TextItem(caption_for(n), t, [a for a in artists if a.get_label() == name]))
    return items


def text_items(fig):
    """The figure's editable texts, top to bottom: its own titles, then each panel's title, x label, y label
    and legend entries, then any colour bar's label. A panel's captions start with its name when the figure
    has more than one. Empty texts (a label nobody set) are left out."""
    items = []
    suptitle = getattr(fig, "_suptitle", None)
    for t in fig.texts:
        if t.get_text().strip():
            items.append(TextItem("Figure title" if t is suptitle else "Figure text", t))

    panels = [(i, ax) for i, ax in enumerate(fig.axes, 1) if not _is_colorbar(ax)]
    many = len(panels) > 1
    for i, ax in panels:
        prefix = f"{panel_name(ax, i)}: " if many else ""
        for caption, artist in (
                ("Title", ax.title), ("Title (left)", getattr(ax, "_left_title", None)),
                ("Title (right)", getattr(ax, "_right_title", None)),
                ("X label", ax.xaxis.label), ("Y label", ax.yaxis.label)):
            if artist is not None and artist.get_text().strip():
                items.append(TextItem(prefix + caption, artist))
        legend = ax.get_legend()
        if legend is not None:
            items += _legend_items(legend, lambda n, prefix=prefix: f"{prefix}Legend {n}", _labelled_artists(ax))
    all_artists = [a for ax in fig.axes for a in _labelled_artists(ax)]
    for legend in fig.legends:
        items += _legend_items(legend, lambda n: f"Figure legend {n}", all_artists)
    for ax in fig.axes:
        if _is_colorbar(ax) and ax.get_ylabel().strip():
            items.append(TextItem("Colour bar label", ax.yaxis.label))
        elif _is_colorbar(ax) and ax.get_xlabel().strip():
            items.append(TextItem("Colour bar label", ax.xaxis.label))
    return items


@contextmanager
def edited_texts(edits):
    """Inside the block each TextItem in `edits` ({TextItem: new text}) reads as its new text; afterwards every
    one has its old text back, even if the block raised. An item whose new text is its old one is left alone."""
    originals = []
    try:
        for item, new in (edits or {}).items():
            old = item.text
            if new != old:
                item.artist.set_text(new)
                for a in item.series:
                    a.set_label(new)
                originals.append((item, old))
        yield
    finally:
        for item, old in originals:
            item.artist.set_text(old)
            for a in item.series:
                a.set_label(old)

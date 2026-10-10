"""
figures/from_tables.py
----------------------
The figure for a finished analysis's tables — what Open Results… shows: the analysis's own window figure drawn from the tables it left (a heatmap
strip over the Z-score trace, the AUC window, the spectrum, the curve fit, the Event PETH), a group analysis's figures, or a plain panel for tables
with no window of their own (a peak finder's results, the time between markers, the processed traces).

    build_figure(tables, kind, parameters)                       the figure for these tables
    build_figure(tables, "event_peth", parameters, view="trials", sort="peak")
    build_figure(tables, "group_analysis", settings, which="measures")

What a table becomes is decided by its columns, not its name, so the CSVs PyAT exports draw the same as the engine's tables: the figure on screen
and the one drawn from the files are the same code (draw.py, group.py).
"""

from . import draw, group, panels
from .errors import NothingToPlot

_KIND_NAMES = {
    "zscore_window": "Z-score window", "auc_window": "AUC window", "fft_window": "FFT window", "curve_fit": "Curve fit",
    "event_peth": "Event PETH", "peak_finder": "Peak finder", "event_intervals": "Event intervals", "process": "Processed traces",
    "group_analysis": "Group analysis",
}


def _title(kind, parameters):
    """The heading of a generic panel figure (the app's own figures carry their own titles)."""
    if not kind:
        return None
    text = _KIND_NAMES.get(str(kind)) or str(kind).replace("_", " ").capitalize()
    if parameters.get("group_name"):
        text += f" — {parameters['group_name']}"
    elif parameters.get("event"):
        text += f" — {parameters['event']}"
    elif parameters.get("center_s") is not None:
        text += f" at {float(parameters['center_s']):g} s"
    return text


def _retitle(fig, title):
    if title is None:
        return
    if getattr(fig, "_suptitle", None) is not None:
        fig._suptitle.set_text(title)
    else:
        fig.suptitle(title, fontweight="bold")


def build_figure(tables, kind=None, parameters=None, *, figure=None, view=None, sort=None, which=None, title=None):
    """The figure for these result tables: what the app draws for that analysis, or a generic panel figure. `figure`
    is the factory that makes it (Figure by default; pyplot.figure for a window). Raises NothingToPlot if there is
    nothing the tables can be drawn as. For an Event PETH, `view` is "zscore" (the default), "trials", "auc", "peak" or "bins" and `sort="peak"`
    orders the heatmap rows by the size of their response; for a group analysis `which` names the figure (traces, heatmap_<marker>, measures,
    diagnostics); `title` replaces the figure's own title."""
    parameters = parameters or {}
    if view is not None and view not in draw.EVENT_PETH_VIEWS:
        raise ValueError(f"view must be one of {', '.join(draw.EVENT_PETH_VIEWS)}, not {view!r}")
    if sort not in (None, "trial", "peak"):
        raise ValueError(f"sort must be \"trial\" or \"peak\", not {sort!r}")
    fig = group.figure_from_tables(tables, parameters, figure, which=which)
    retitle = True
    if fig is None:
        for build, options in ((draw.event_peth_from_tables, {"view": view or "zscore", "sort_by_peak": sort == "peak", "title": title}),
                               (draw.zscore_window_from_tables, {}), (draw.auc_window_from_tables, {}),
                               (draw.fft_window_from_tables, {}), (draw.curve_fit_from_tables, {})):
            fig = build(tables, parameters, figure, **options)
            if fig is not None:
                retitle = build is not draw.event_peth_from_tables      # the Event PETH takes its title into its own drawing
                break
        else:
            fig = panels.panel_figure(tables, parameters, figure, title if title is not None else _title(kind, parameters))
            retitle = False                                             # already the heading
    if fig is None:
        raise NothingToPlot("These tables are not ones PyAT knows how to draw (columns: "
                            + "; ".join(f"{name}: {', '.join(map(str, t.columns))}" for name, t in tables.items())
                            + "). It draws the results of the analyses and the CSVs written from them")
    if retitle:
        _retitle(fig, title)
    return fig

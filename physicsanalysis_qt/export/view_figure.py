"""
export/view_figure.py
---------------------
Export View: the main plot, redrawn as a publication figure. The plot on screen belongs to one of two engines (matplotlib or
PyQtGraph), and only one of them can save a vector file, so the export does not copy the screen: it redraws what the plot
shows — the same traces, markers, highlights, text, title, labels and legend, in the range currently in view — as a matplotlib
figure on a white page with black text, whichever engine is up. That figure goes through the shared Export Figure dialog
(export/figure_export.py): PNG/TIFF at the resolution you pick, PDF/SVG with editable text, titles and labels editable first.

The drawing is figures/view.py's (`build_view`, `view_traces`: the library plans what the plot shows, the app styles and draws it), so the
export and the plot on screen (both engines draw their traces through `view_traces`) cannot differ. What is here: reading the range from
whichever engine is showing, the widget's proportions, the signals ticked in the Plot menu and the attributes the Edit Graph Attributes
dialog holds.

The data CSV beside the figure is not read off the drawn lines (they are thinned to a few tens of thousands of points, plenty
for a page): it holds every sample of the visible range, one column per trace, and a second CSV lists the markers in view.
"""

from ..backend import api
from .. import figures
from ..app.toasts import show_error

EXPORT_MAX_POINTS = figures.view.EXPORT_MAX_POINTS            # per trace in the drawn figure: more than a page can show, far fewer than a recording has
GRID_COLOR = figures.view.GRID_COLOR

__all__ = ["EXPORT_MAX_POINTS", "GRID_COLOR", "build_view", "export_view", "view_range", "view_traces"]


def view_traces(ctx):
    """(traces, title, x label, y label) for what the main plot draws for the loaded recording, before any edit of its title, labels
    or legend — figures.view_traces for the signals ticked in the Plot menu, with the user's colour overrides. Records each
    line's default colour in ctx._trace_default_colors, which is what Edit Graph Attributes shows and resets to."""
    traces, title, x_label, y_label = figures.view_traces(
        ctx.cache, signals=ctx.plot_signals, active=ctx.plot_signal, line_colors=ctx.plot_attrs["line_colors"])
    for t in traces:
        ctx._trace_default_colors[t.key] = t.default_color
    return traces, title, x_label, y_label


def view_range(ctx):
    """((x0, x1), (y0, y1)) of what the main plot is showing, whichever engine is drawing it (y is None if there
    is nothing to read it from)."""
    engine = ctx.settings.get("plot_engine")
    if engine == "pyqtgraph" and ctx.pg_plot_item is not None:
        (x0, x1), (y0, y1) = ctx.pg_plot_item.vb.viewRange()
    elif ctx.ax is not None:
        (x0, x1), (y0, y1) = ctx.ax.get_xlim(), ctx.ax.get_ylim()
    else:                                                      # no plot built yet: the whole recording, y left to the figure
        return api.view.padded_xlim(ctx.cache['x']), None
    return (float(min(x0, x1)), float(max(x0, x1))), (float(min(y0, y1)), float(max(y0, y1)))


def _figure_size(ctx):
    """Inches for the figure: the plot area's own proportions (so the export looks like the screen), 10 wide."""
    widget = getattr(ctx, "stacked_plot_widget", None)
    w, h = (widget.width(), widget.height()) if widget is not None else (0, 0)
    return figures.view.view_figsize(w, h)


def build_view(ctx):
    """The main plot redrawn as a ViewExport (figures.build_view): white page, black text, the range in view, every trace at
    up to EXPORT_MAX_POINTS points (min/max thinned, so no peak is lost)."""
    xlim, ylim = view_range(ctx)
    view_traces(ctx)                                           # keeps the dialog's default colours current
    return figures.build_view(
        ctx.cache, attrs=ctx.plot_attrs, signals=ctx.plot_signals, active=ctx.plot_signal, xlim=xlim, ylim=ylim,
        show_grid=ctx.show_grid, store_labels=ctx.store_labels, figsize=_figure_size(ctx), max_points=EXPORT_MAX_POINTS)


def export_view(ctx):
    """Export View: opens the Export Figure dialog on the redrawn plot."""
    if ctx.cache is None:
        show_error(ctx, "No plot to export.")
        return
    from .figure_export import export_figure
    view = build_view(ctx)
    provenance = {"kind": "view", "parameters": view.parameters()}           # the range, signals and attributes: pl.reproduce_record replays its data CSV
    export_figure(ctx, view.fig, "View", provenance=provenance, data_writer=view.write_data,
                  stem=f"{ctx.cache['store']}_view")

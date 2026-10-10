"""
plot/plotting.py
----------------
Drawing the main plot: simple_plot() builds the figure from cache,
_apply_plot_attrs() re-applies persisted label/font/legend customisations
after any redraw, and export_canvas_action() saves the current view.

Which lines the plot has (their names, colours, widths), the markers, highlights and text boxes on it, and thinning a trace to the
range in view are figures/view.py's — the same code Export View draws with,
so the export is what the plot shows. What is here is the live part: the axes, the theme, hover, decimation as the view changes.
"""

from ..backend import api
from .. import figures
from .fonts import main_plot_scale
from ..app.theme import mpl_colors
from ..app.toasts import show_error

_DECIMATE_MAX_POINTS_DEFAULT = 2000  # fallback if no ctx is available

# padded_xlim and _min_max_decimate are the analysis code's (backend.api.view): the plot, its export and a script share them.
def padded_xlim(x):
    return api.view.padded_xlim(x)


def _min_max_decimate(x, y, xlim, max_points=_DECIMATE_MAX_POINTS_DEFAULT):
    return figures.view.min_max_decimate(x, y, xlim, max_points=max_points)


def update_decimated_lines(ctx):
    """Re-decimate every tracked trace to the axes' current xlim. Cheap
    enough to call on every xlim change (pan/zoom/reset)."""
    if not ctx._decim_lines:
        return
    xlim = ctx.ax.get_xlim()
    max_points = ctx.settings.get("decimate_max_points", _DECIMATE_MAX_POINTS_DEFAULT)
    for line, full_x, full_y in ctx._decim_lines:
        dx, dy = _min_max_decimate(full_x, full_y, xlim, max_points=max_points)
        line.set_data(dx, dy)


def _update_plot_with_notes(ctx, markers, ax=None):
    """Draws the markers (library_view.draw_markers: a dashed line each, and its label along the line). On the live axes (the
    default) ctx._marker_label_artists is refreshed for hit-testing; on another `ax` (the export figure) nothing about the live
    plot is touched."""
    live = ax is None
    label_artists = figures.view.draw_markers(ctx.ax if live else ax, markers, ctx.store_labels)
    if live:
        ctx._marker_label_artists = label_artists


def _draw_highlights(ctx, highlights, ax=None):
    """Highlighter tool (edit/highlight.py): a translucent axvspan per highlight, behind everything else."""
    figures.view.draw_highlights(ctx.ax if ax is None else ax, highlights)


def _draw_text_annotations(ctx, annotations, ax=None):
    """Text tool (edit/text_annotation.py): free-floating text at each one's (x, y) data position. On the live axes
    ctx._text_annotation_artists tracks (annotation dict, Text artist) pairs for plot/interaction.py's right-click drag/delete
    hit-testing, same pattern as marker labels."""
    live = ax is None
    artists = figures.view.draw_text_annotations(ctx.ax if live else ax, annotations)
    if live:
        ctx._text_annotation_artists = artists


def _apply_theme_colors(ctx):
    """Style the matplotlib figure/axes to match the current light/dark
    theme — Qt's palette swap (see app/theme.py) doesn't reach into
    matplotlib's own rendering, so this has to be applied separately."""
    colors = mpl_colors(ctx.settings.get("theme", "light"))
    fig, ax = ctx.fig, ctx.ax
    fig.set_facecolor(colors["figure"])
    ax.set_facecolor(colors["axes"])
    ax.tick_params(colors=colors["text"])
    for spine in ax.spines.values():
        spine.set_color(colors["grid"])
    ax.title.set_color(colors["text"])
    ax.xaxis.label.set_color(colors["text"])
    ax.yaxis.label.set_color(colors["text"])
    legend = ax.get_legend()
    if legend is not None:
        legend.get_frame().set_facecolor(colors["axes"])
        legend.get_frame().set_edgecolor(colors["grid"])
        for text in legend.get_texts():
            text.set_color(colors["text"])


def _apply_plot_attrs(ctx):
    """Always apply persisted font sizes; only override text when the user set one."""
    ax = ctx.ax
    plot_attrs = ctx.plot_attrs
    scale = main_plot_scale(ctx.stacked_plot_widget)
    title_fs = max(8, round(plot_attrs["title_fs"] * scale))
    xlabel_fs = max(6, round(plot_attrs["xlabel_fs"] * scale))
    ylabel_fs = max(6, round(plot_attrs["ylabel_fs"] * scale))
    leg_fs = max(5, round(plot_attrs["leg_fs"] * scale))

    colors = mpl_colors(ctx.settings.get("theme", "light"))
    weight = 'bold' if plot_attrs.get("bold", True) else 'normal'
    title_text = plot_attrs["title"] or ctx._last_title or ax.get_title()
    xlabel_text = plot_attrs["xlabel"] or ctx._last_xlabel or ax.get_xlabel()
    ylabel_text = plot_attrs["ylabel"] or ctx._last_ylabel or ax.get_ylabel()
    ax.set_title(title_text, fontweight=weight, pad=15, fontsize=title_fs, color=colors["text"])
    ax.set_xlabel(xlabel_text, fontweight=weight, fontsize=xlabel_fs, color=colors["text"])
    ax.set_ylabel(ylabel_text, fontweight=weight, fontsize=ylabel_fs, color=colors["text"])

    handles, labels = ax.get_legend_handles_labels()
    entries = [(h, l) for h, l in zip(handles, labels) if not l.startswith('_')]
    ctx._legend_entries = [l for _, l in entries]
    if not entries:
        return

    if plot_attrs["leg_entries"]:
        label_map = figures.attributes.legend_edits(plot_attrs)
        new_h, new_l = [], []
        for h, l in entries:
            if l in label_map:
                new_label, visible = label_map[l]
                if visible:
                    new_h.append(h)
                    new_l.append(new_label)
            else:
                new_h.append(h)
                new_l.append(l)
        if new_h:
            ax.legend(new_h, new_l, fontsize=leg_fs, loc=plot_attrs["leg_loc"])
        else:
            leg = ax.get_legend()
            if leg:
                leg.remove()
    else:
        ax.legend(fontsize=leg_fs, loc=plot_attrs["leg_loc"])

    legend = ax.get_legend()
    if legend is not None:
        legend.get_frame().set_facecolor(colors["axes"])
        legend.get_frame().set_edgecolor(colors["grid"])
        for text in legend.get_texts():
            text.set_color(colors["text"])


def apply_theme_to_canvas(ctx):
    """Recolor the matplotlib figure/axes for the current theme even with
    no data loaded — simple_plot() bails out early with an empty cache,
    so an untouched canvas would otherwise stay white until a file loads."""
    colors = mpl_colors(ctx.settings.get("theme", "light"))
    ctx.fig.set_facecolor(colors["figure"])
    ctx.ax.set_facecolor(colors["axes"])
    ctx.ax.tick_params(colors=colors["text"])
    for spine in ctx.ax.spines.values():
        spine.set_color(colors["grid"])
    ctx.canvas.draw_idle()


def view_traces(ctx):
    from ..export.view_figure import view_traces as _view_traces
    return _view_traces(ctx)


def simple_plot(ctx, draw_now=True):
    cache = ctx.cache
    if cache is None:
        return

    if ctx.settings.get("plot_engine") == "pyqtgraph":
        from .pg_engine import pg_simple_plot
        pg_simple_plot(ctx)
        return

    ax = ctx.ax
    zoom_key = ("matplotlib", ctx._data_generation)
    is_new_dataset = zoom_key != ctx._last_zoomed_key
    prev_xlim = None if is_new_dataset else ax.get_xlim()
    prev_ylim = None if is_new_dataset else ax.get_ylim()

    ax.clear()
    _apply_theme_colors(ctx)
    ax.axhline(0, color='black', linewidth=1.0, alpha=0.4, zorder=1)

    decim_lines = []  # (line, full_x, full_y) — trace lines tracked for decimation

    # Which lines, in what colour and width, under what name: figures.view_traces, the same list Export View draws.
    traces, title, x_label, y_label = view_traces(ctx)
    if cache.get('source') not in ('Oxysoft', 'Generic'):
        ax.axvline(0, color='black', linewidth=1.0, alpha=0.4, zorder=1)
    for t in traces:
        # lw=1.5 for a TDT line, not Oxysoft's 0.8 — the hover tracker below filters visible lines to linewidth >= 1.5
        # (see plot/interaction.py), so a thinner line would be silently un-hoverable.
        style = dict(marker=t.marker, markersize=t.markersize) if t.marker else {}
        ln, = ax.plot(t.x, t.y, color=t.color, lw=t.lw, alpha=t.alpha, label=t.label, **style)
        decim_lines.append((ln, t.x, t.y))
    n_snap_lines = sum(t.snap for t in traces)

    ctx._decim_lines = decim_lines
    ctx._last_title = title
    ctx._last_xlabel = x_label
    ctx._last_ylabel = y_label
    # ax.clear() drops any previously connected callbacks, so this must be
    # reconnected on every redraw. Once wired, every future pan/zoom/reset
    # (all of which go through ax.set_xlim somewhere) automatically keeps
    # each trace decimated to the visible range — no changes needed in
    # plot/interaction.py to benefit from it.
    ax.callbacks.connect('xlim_changed', lambda _ax: update_decimated_lines(ctx))

    _update_plot_with_notes(ctx, cache['markers'])
    _draw_highlights(ctx, cache.get('highlights', []))
    _draw_text_annotations(ctx, cache.get('text_annotations', []))
    ax.set_title(title, fontweight='bold', pad=15)
    ax.set_xlabel(x_label, fontweight='bold')
    ax.set_ylabel(y_label, fontweight='bold')
    ax.legend(loc='upper left', fontsize=ctx.plot_attrs["leg_fs"])
    if is_new_dataset:
        ax.set_xlim(*padded_xlim(cache['x']))
        ctx._last_zoomed_key = zoom_key
    else:
        ax.set_xlim(prev_xlim)
        ax.set_ylim(prev_ylim)
    update_decimated_lines(ctx)  # belt-and-suspenders in case xlim didn't change
    _apply_plot_attrs(ctx)

    if ctx.show_grid:
        ax.grid(True, linestyle=':', alpha=0.4, color=mpl_colors(ctx.settings.get("theme", "light"))["grid"])

    # Hover tracker dots — one per snappable line, drawn via blit
    ctx.tracker_dots = [
        ax.plot([], [], 'o', markersize=6, animated=True, zorder=6)[0]
        for _ in range(n_snap_lines)
    ]
    ctx.connecting_line, = ax.plot([], [], color='black', lw=1.0, alpha=0.6,
                                    animated=True, zorder=5)
    ctx._hover_bg = None

    if draw_now:
        ctx.canvas.draw()
        ctx._hover_bg = ctx.canvas.copy_from_bbox(ctx.fig.bbox)


def set_grid_visibility(ctx, show):
    """Toggle grid lines only — no clear/rebuild, so nothing about the
    current view or items changes (a full simple_plot() redraw for this
    was visibly flashing: PyQtGraph's engine re-adds every line and
    re-measures/re-applies margins on every call, which briefly shows
    intermediate states before settling)."""
    ctx.show_grid = bool(show)
    if ctx.cache is None:
        return
    if ctx.settings.get("plot_engine") == "pyqtgraph":
        from .pg_engine import pg_set_grid_visibility
        pg_set_grid_visibility(ctx)
        return
    if ctx.show_grid:
        # Passing style kwargs alongside grid(False, ...) makes matplotlib
        # force the grid back ON regardless of the False — only pass them
        # when actually turning it on.
        ctx.ax.grid(True, linestyle=':', alpha=0.4, color=mpl_colors(ctx.settings.get("theme", "light"))["grid"])
    else:
        ctx.ax.grid(False)
    ctx.canvas.draw_idle()


def export_canvas_action(ctx):
    """Export View: the plot as it is on screen (the visible range, the checked signals, markers, highlights, text,
    the edited title/labels/legend), redrawn as a publication figure — the same one whichever plot engine is
    showing it — through the shared Export Figure dialog (export/figure_export.py)."""
    if ctx.cache is None:
        show_error(ctx, "No plot to export.")
        return
    from ..export.view_figure import export_view
    export_view(ctx)

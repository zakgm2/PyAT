"""
plotting.py
-----------
Drawing the main plot: simple_plot() builds the figure from cache,
_apply_plot_attrs() re-applies persisted label/font/legend customisations
after any redraw, and export_canvas_action() saves the current view.
"""

import numpy as np
import matplotlib.transforms as transforms

import PhysicsLibrary as pl

from .context import export_file, get_active_signal, get_checked_signals, trace_color
from .fonts import main_plot_scale
from .theme import mpl_colors
from .toasts import show_error

_DECIMATE_MAX_POINTS_DEFAULT = 2000  # fallback if no ctx is available

_FULL_VIEW_PADDING_FRAC = 0.02  # 2% of the data span on each side


def padded_xlim(x):
    """(lo, hi) for "fit the full trace with a little breathing room" —
    matplotlib's set_xlim() has no built-in padding (unlike its own
    autoscale(), and unlike PyQtGraph's autoRange(), both of which already
    add a small default margin), so an exact-bounds set_xlim() leaves the
    trace flush against the axes edges. Used for every "show everything"
    moment (a fresh load/signal switch, and the Rescale button) so they
    all look the same."""
    lo, hi = float(x[0]), float(x[-1])
    pad = (hi - lo) * _FULL_VIEW_PADDING_FRAC
    if pad == 0:
        pad = 1.0  # degenerate single-point/flat data — avoid a zero-width range
    return lo - pad, hi + pad


def _min_max_decimate(x, y, xlim, max_points=_DECIMATE_MAX_POINTS_DEFAULT):
    """
    Reduce (x, y) to at most max_points, keeping the min and max of every
    bin so peaks/troughs survive (a naive stride would smear them out).
    Only the currently visible x-range is kept — this is what makes
    pan/zoom redraw cost independent of how many samples the recording has.
    """
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


def _update_plot_with_notes(ctx, markers):
    from .marker_labels import marker_display_label

    trans = transforms.blended_transform_factory(ctx.ax.transData, ctx.ax.transAxes)
    unique_labels = set()
    ctx._marker_label_artists = []  # (marker dict, Text artist) — right-click-drag hit-testing
    for m in markers:
        text = marker_display_label(ctx, m)
        label_id = text if text not in unique_labels else "_nolegend_"
        unique_labels.add(text)
        ctx.ax.axvline(x=m['time'], color=m['color'], linestyle='--', alpha=0.6, label=label_id)
        if not text:
            continue  # an unnamed marker is just the tick above — no label to draw or drag
        label_y = m.get('label_y', 0.98)  # fraction of the axes height, 0 (bottom) to 1 (top) —
        # draggable (right-click and hold on the label, see interaction.py's label-drag handling)
        artist = ctx.ax.text(m['time'], label_y, f" {text}", transform=trans,
                     rotation=90, va='top' if label_y > 0.5 else 'bottom', clip_on=True,
                     fontsize=m.get('fontsize', 8), color=m['color'], fontweight='bold',
                     bbox=dict(facecolor='white', alpha=0.7, edgecolor='none', pad=1))
        ctx._marker_label_artists.append((m, artist))


def _draw_highlights(ctx, highlights):
    """Highlighter tool (analysis/highlight.py): a translucent axvspan per highlight, behind
    everything else (zorder=0, same as the hover tracker's own reference line)."""
    from .analysis.highlight import HIGHLIGHT_ALPHA
    for h in highlights:
        ctx.ax.axvspan(h['start'], h['end'], color=h['color'], alpha=HIGHLIGHT_ALPHA, zorder=0)


def _draw_text_annotations(ctx, annotations):
    """Text tool (analysis/text_annotation.py): free-floating text at each one's (x, y) data
    position. ctx._text_annotation_artists tracks (annotation dict, Text artist) pairs for
    interaction.py's right-click drag/delete hit-testing, same pattern as marker labels."""
    ctx._text_annotation_artists = []
    for t in annotations:
        artist = ctx.ax.text(t['x'], t['y'], t['text'], fontsize=t.get('fontsize', 10),
                              color='black', zorder=5, clip_on=True)
        ctx._text_annotation_artists.append((t, artist))


def _apply_theme_colors(ctx):
    """Style the matplotlib figure/axes to match the current light/dark
    theme — Qt's palette swap (see theme.py) doesn't reach into
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
        label_map = {orig: (new, vis) for orig, new, vis in plot_attrs["leg_entries"]}
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


def simple_plot(ctx, draw_now=True):
    cache = ctx.cache
    if cache is None:
        return

    if ctx.settings.get("plot_engine") == "pyqtgraph":
        from .pg_engine import pg_simple_plot
        pg_simple_plot(ctx)
        return

    if ctx.settings.get("plot_engine") == "vispy":
        from .vispy_engine import vispy_simple_plot
        vispy_simple_plot(ctx)
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

    if cache.get('source') == 'Oxysoft':
        x = cache['x']
        o2hb = cache['o2hb']
        hhb = cache['hhb']
        # Only the first line of each channel group carries a legend name;
        # the rest ('_nolegend_') follow that entry's color.
        o2hb_color = trace_color(ctx, 'O2Hb channels', '#FF9999')
        hhb_color = trace_color(ctx, 'HHb channels', '#99BBFF')
        for i in range(o2hb.shape[0]):
            ln, = ax.plot(x, o2hb[i], color=o2hb_color, lw=0.8, alpha=0.5,
                           label='O2Hb channels' if i == 0 else '_nolegend_')
            decim_lines.append((ln, x, o2hb[i]))
            ln, = ax.plot(x, hhb[i], color=hhb_color, lw=0.8, alpha=0.5,
                           label='HHb channels' if i == 0 else '_nolegend_')
            decim_lines.append((ln, x, hhb[i]))
        ff = cache.get('fit_factor_mean')
        ff_tag = f"  [FF: {ff:.1f}%]" if ff is not None else ""
        mean_o2hb = pl.mean_channels(o2hb)
        name = f'Mean O2Hb{ff_tag}'
        ln, = ax.plot(x, mean_o2hb, color=trace_color(ctx, name, '#CC0000'), lw=2.0, label=name)
        decim_lines.append((ln, x, mean_o2hb))
        mean_hhb = pl.mean_channels(hhb)
        name = f'Mean HHb{ff_tag}'
        ln, = ax.plot(x, mean_hhb, color=trace_color(ctx, name, '#0033CC'), lw=2.0, label=name)
        decim_lines.append((ln, x, mean_hhb))
        if 'thb' in cache:
            thb = cache['thb']
            mean_thb = pl.mean_channels(thb)
            name = f'Mean tHb{ff_tag}'
            ln, = ax.plot(x, mean_thb, color=trace_color(ctx, name, '#228B22'), lw=2.0, label=name)
            decim_lines.append((ln, x, mean_thb))
        y_label = "Delta Concentration (uM)"
        title = f"NIRS — {cache['store']}"
        x_label = "Time (s)"
        n_snap_lines = 3 if 'thb' in cache else 2
    elif cache.get('source') == 'Generic':
        x = cache['x']
        _GEN_COLORS = ['#CC0000', '#0033CC', '#228B22', '#CC6600',
                       '#6600CC', '#008888', '#AA0055', '#005588']
        for i, (col_name, y) in enumerate(cache['y_columns'].items()):
            mask = ~np.isnan(y)
            xv, yv = x[mask], y[mask]
            ln, = ax.plot(xv, yv, 'o-', lw=1.8, markersize=4,
                           color=trace_color(ctx, col_name, _GEN_COLORS[i % len(_GEN_COLORS)]),
                           label=col_name)
            decim_lines.append((ln, xv, yv))
        y_label = "Value"
        title = cache['store']
        x_label = cache.get('x_label', 'X')
        n_snap_lines = len(cache['y_columns'])
    elif cache.get('source') == 'TDT' and len(ctx.plot_signals) > 1:
        checked = get_checked_signals(ctx)
        ax.axvline(0, color='black', linewidth=1.0, alpha=0.4, zorder=1)
        for key, sig in checked:
            # lw=1.5, not Oxysoft's 0.8 — the hover tracker below filters
            # visible lines to linewidth >= 1.5 (see interaction.py), so a
            # thinner line here would be silently un-hoverable.
            ln, = ax.plot(cache['x'], sig['y'], color=trace_color(ctx, sig['label'], sig['color']),
                           lw=1.5, alpha=0.8, label=sig['label'])
            decim_lines.append((ln, cache['x'], sig['y']))
        y_label = "Amplitude"
        title = f"Overlay ({len(checked)}) — {cache['store']}"
        x_label = "Time (s)"
        n_snap_lines = len(checked)
    else:
        _, label_text, data_to_plot, color_choice = get_active_signal(ctx)
        ax.axvline(0, color='black', linewidth=1.0, alpha=0.4, zorder=1)
        ln, = ax.plot(cache['x'], data_to_plot, color=trace_color(ctx, label_text, color_choice),
                       lw=1.5, alpha=0.8, label=label_text)
        decim_lines.append((ln, cache['x'], data_to_plot))
        y_label = "Amplitude"
        title = f"{label_text} — {cache['store']}"
        x_label = "Time (s)"
        n_snap_lines = 1

    ctx._decim_lines = decim_lines
    ctx._last_title = title
    ctx._last_xlabel = x_label
    ctx._last_ylabel = y_label
    # ax.clear() drops any previously connected callbacks, so this must be
    # reconnected on every redraw. Once wired, every future pan/zoom/reset
    # (all of which go through ax.set_xlim somewhere) automatically keeps
    # each trace decimated to the visible range — no changes needed in
    # interaction.py to benefit from it.
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
    if ctx.settings.get("plot_engine") == "vispy":
        from .vispy_engine import vispy_set_grid_visibility
        vispy_set_grid_visibility(ctx)
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
    if ctx.cache is None:
        show_error(ctx, "No plot to export.")
        return
    if ctx.settings.get("plot_engine") == "pyqtgraph":
        from .pg_engine import pg_export_view
        pg_export_view(ctx)
        return
    if ctx.settings.get("plot_engine") == "vispy":
        from .vispy_engine import vispy_export_view
        vispy_export_view(ctx)
        return
    export_file(ctx, ctx.win, "Export View", f"{ctx.cache['store']}_view.png",
                "PNG (*.png);;PDF (*.pdf);;SVG (*.svg)",
                lambda path: ctx.fig.savefig(path, dpi=300, bbox_inches='tight'))

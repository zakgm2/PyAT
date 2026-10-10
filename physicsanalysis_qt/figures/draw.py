"""
figures/draw.py
---------------
The figures of the analysis windows — Z-score, AUC, FFT, Curve Fit, Event PETH — drawn from plain arrays. PyAT's
windows call these to put the figure on screen and `plotlatest` calls them to draw a result; one piece of drawing code,
so the figure a script saves is the figure the app shows.

Each figure has two forms:

    zscore_window_figure(channels, pre, post)        draws from arrays the caller holds (the GUI's own results)
    zscore_window_from_tables(tables, parameters)    rebuilds those arrays from a result's tables (`run_analysis`, or the
                                                     CSVs that were written from one) — None if the tables are not that
                                                     analysis's

A `channels` list is [{"channel": name, "color": colour, ...the arrays}], one per signal the window analysed. Times are
relative to the centre of the window (or to the event, for Event PETH). Fonts follow the figure's size (style.fig_font_sizes).

matplotlib is imported when a figure is drawn, never when the library is imported.
"""

import numpy as np

from ..backend import api
from .style import channel_color, fig_font_sizes
from .tables import channels as table_channels
from .tables import find, float_array, has


def _figure(figsize, figure=None, **kw):
    """A new figure; `figure` is the factory to make it with (matplotlib.figure.Figure by default, pyplot.figure when
    the result is going to be shown in a window)."""
    if figure is None:
        from matplotlib.figure import Figure
        figure = Figure
    return figure(figsize=figsize, dpi=100, **kw)


def _clear(fig):
    """Empties `fig` as if it were new. clf() alone is not enough: tight_layout writes its result into the figure's own
    subplot parameters, which survive a clf() and are where the next layout starts from — so what a figure showed before
    would change how its next contents are laid out."""
    from matplotlib.figure import SubplotParams

    fig.clf()
    fig.subplotpars = SubplotParams()          # back to the defaults


def _window(parameters, channels, key):
    """(pre, post) of a window: what it was asked for if the parameters say, else how far its data reaches."""
    pre = parameters.get("pre_s")
    post = parameters.get("post_s")
    if pre is None:
        pre = -min(float(np.min(c[key])) for c in channels)
    if post is None:
        post = max(float(np.max(c[key])) for c in channels)
    return float(pre), float(post)


# ---------------------------------------------------------------------------
# Z-score window: a heatmap strip over the trace, per channel
# ---------------------------------------------------------------------------

def zscore_window_figure(channels, pre, post, figure=None):
    """channels: [{"channel", "color", "t" (seconds from the centre), "z" (z-scores)}]."""
    n = len(channels)
    fig = _figure((8, 4.5 * n), figure)
    axes = fig.subplots(2 * n, 1, gridspec_kw={'height_ratios': [1, 2] * n})
    tfs, lfs = 12, 10
    for i, r in enumerate(channels):
        ax_heat, ax_line = axes[2 * i], axes[2 * i + 1]
        z = np.asarray(r["z"], dtype=float)
        z_binned = api.stats.bin_for_heatmap(z)
        # The heatmap's colours are scaled to this channel's own z-score spread rather than a fixed range, so a quiet
        # recording isn't washed out and a big responder doesn't flatten everything else (the line below shows all of it).
        scale = np.nanpercentile(np.abs(z), 98) or 1.0
        ax_heat.imshow(z_binned.reshape(1, -1), aspect='auto', cmap='YlGnBu_r',
                       extent=[-pre, post, 0, 1], vmin=-scale, vmax=scale, interpolation='bilinear')
        ax_heat.set_yticks([])
        tfs, lfs, _ = fig_font_sizes(fig)
        ax_heat.set_ylabel(r['channel'], fontweight='bold', fontsize=lfs)

        ax_line.plot(r["t"], z, color=r['color'], linewidth=1.5)
        ax_line.axvline(0, color='red', linestyle='--', alpha=0.8)
        ax_line.set_xlim([-pre, post])
        finite = np.abs(z[np.isfinite(z)])
        reach = float(finite.max()) * 1.05 if finite.size and finite.max() > 0 else 1.0     # all of the trace in view: its peak is what this window is for
        ax_line.set_ylim([-reach, reach])
        ax_line.set_ylabel("Z-Score", fontweight='bold', fontsize=lfs)
    axes[-1].set_xlabel("Time from Center (s)", fontweight='bold', fontsize=lfs)

    fig.suptitle("Z-Score Analysis", fontsize=tfs, fontweight='bold')
    fig.tight_layout(rect=[0, 0.03, 1, 0.97])
    return fig


def zscore_window_from_tables(tables, parameters, figure=None):
    table = find(tables, "Channel", "time_from_center_s", "z_score")
    if table is None:
        return None
    channels = [{"channel": name, "color": channel_color(name), "t": float_array(g["time_from_center_s"]), "z": float_array(g["z_score"])}
                for name, g in table_channels(table)]
    pre, post = _window(parameters, channels, "t")
    return zscore_window_figure(channels, pre, post, figure)


# ---------------------------------------------------------------------------
# AUC window: the trace with the area under it shaded, per channel
# ---------------------------------------------------------------------------

def auc_window_figure(channels, figure=None):
    """channels: [{"channel", "color", "t" (seconds from the centre), "y" (the signal)}]."""
    n = len(channels)
    fig = _figure((8, 3.5 * n), figure)
    axes = fig.subplots(n, 1) if n > 1 else [fig.add_subplot(111)]
    for ax, r in zip(axes, channels):
        rel_x, seg_y = np.asarray(r["t"], dtype=float), np.asarray(r["y"], dtype=float)
        ax.plot(rel_x, seg_y, color=r['color'], lw=1.5)
        ax.fill_between(rel_x, seg_y, 0, where=(seg_y >= 0), color='green', alpha=0.25)
        ax.fill_between(rel_x, seg_y, 0, where=(seg_y <= 0), color='red', alpha=0.25)
        ax.axhline(0, color='black', lw=0.8, alpha=0.6)
        ax.axvline(0, color='gray', lw=1.0, linestyle='--', alpha=0.6)
        tfs, lfs, _ = fig_font_sizes(fig)
        ax.set_ylabel(r['channel'], fontweight='bold', fontsize=lfs)
    axes[-1].set_xlabel("Time from Center (s)", fontweight='bold', fontsize=lfs)
    fig.suptitle("AUC", fontsize=tfs, fontweight='bold')
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    return fig


def auc_window_from_tables(tables, parameters, figure=None):
    table = find(tables, "Channel", "time_from_center_s", "value")
    if table is None:
        return None
    channels = [{"channel": name, "color": channel_color(name), "t": float_array(g["time_from_center_s"]), "y": float_array(g["value"])}
                for name, g in table_channels(table)]
    return auc_window_figure(channels, figure)


# ---------------------------------------------------------------------------
# FFT window: the spectrum with its top peaks named, per channel
# ---------------------------------------------------------------------------

def _annotate_fft_peaks(ax_f, freqs, power, color, n_peaks=3):
    """Finds the top N peaks (find_fft_peaks) and draws frequency/BPM labels for them directly on the axes."""
    for p in api.stats.find_fft_peaks(freqs, power, n_peaks=n_peaks):
        ax_f.annotate(
            f"{p['freq_hz']:.2f} Hz\n({p['bpm']:.0f} bpm)",
            xy=(p['freq_hz'], p['power']),
            xytext=(p['freq_hz'] + 0.05, p['power'] * 0.92),
            fontsize=7, color=color, fontweight='bold',
            arrowprops=dict(arrowstyle='->', color=color, lw=0.8),
        )
        ax_f.axvline(p['freq_hz'], color=color, lw=0.7, linestyle=':', alpha=0.5)


def fft_window_figure(channels, fs, center=None, pre=None, post=None, figure=None):
    """channels: [{"channel", "color", "freqs", "power"}]; `fs` the sampling rate (the axis runs to fs / 2). The
    grey subtitle says where the window was (`center`, `pre`, `post`) if those are known."""
    n = len(channels)
    fig = _figure((8, 3.5 * n), figure)
    axes = fig.subplots(n, 1) if n > 1 else [fig.add_subplot(111)]
    lfs_f = 10
    for ax_f, r in zip(axes, channels):
        freqs, power = np.asarray(r["freqs"], dtype=float), np.asarray(r["power"], dtype=float)
        if len(freqs) > 0:
            ax_f.plot(freqs, power, color=r["color"], lw=1.5)
            _annotate_fft_peaks(ax_f, freqs, power, r["color"])
        tfs_f, lfs_f, _ = fig_font_sizes(fig)
        ax_f.set_ylabel("Power", fontweight='bold', fontsize=lfs_f)
        ax_f.set_title(r["channel"], fontweight='bold', fontsize=tfs_f)
        ax_f.set_xlim(0.05, fs / 2)
        ax_f.autoscale(axis='y')
    axes[-1].set_xlabel("Frequency (Hz)", fontweight='bold', fontsize=lfs_f)

    if center is not None and pre is not None and post is not None:
        fig.suptitle(f"centre {center:.1f}s  |  -{pre:.0f}s/+{post:.0f}s", fontsize=10, color='gray')
    fig.tight_layout(rect=[0, 0.03, 1, 0.97])
    return fig


def fft_window_from_tables(tables, parameters, figure=None):
    table = find(tables, "Channel", "frequency_hz", "power")
    if table is None:
        return None
    channels = [{"channel": name, "color": channel_color(name), "freqs": float_array(g["frequency_hz"]), "power": float_array(g["power"])}
                for name, g in table_channels(table)]
    top = max((float(np.max(c["freqs"])) for c in channels if len(c["freqs"])), default=0.5)
    fs = parameters.get("fs") or 2 * top                                   # the spectrum runs to fs / 2
    return fft_window_figure(channels, fs, parameters.get("center_s"), parameters.get("pre_s"), parameters.get("post_s"), figure)


# ---------------------------------------------------------------------------
# Curve fit: the data around the fitted stretch, the stretch, the fit
# ---------------------------------------------------------------------------

def new_curve_fit_figure(figure=None):
    """An empty figure for draw_curve_fit — a window keeps it and draws into it each time the fit is recalculated."""
    return _figure((6, 3.5), figure)


def draw_curve_fit(fig, channels, *, model_name, t1, t2, view_start, view_end, x_label="Time", y_label="Signal"):
    """Clears `fig` and draws the fit(s) on a fresh axes, which it returns. The figure is rebuilt each time, not
    redrawn over: matplotlib's tight layout leaves its result in the figure, so a redraw can lay out differently from a
    first draw of the same thing. channels: [{"label", "color", "x_ctx", "y_ctx" (the signal over the wider
    view), "x", "y" (the fitted stretch), "fit" (its fitted curve, or None if the fit failed), "r2"}]. `x_label` is
    without its unit — seconds are added."""
    _clear(fig)
    ax = fig.add_subplot(111)
    is_linear = model_name.startswith("Linear")
    for c in channels:
        color = c["color"]
        ax.plot(c["x_ctx"], c["y_ctx"], color=color, lw=1.0, alpha=0.3)
        ax.plot(c["x"], c["y"], color=color, lw=2.0, label=f"{c['label']}")
        if c.get("fit") is not None:
            ax.plot(c["x"], c["fit"], color=color, lw=2.5, linestyle='--', label=f"{c['label']} fit  R2={c['r2']:.3f}")
            if is_linear:
                ax.plot([t1, t2], [float(c["y"][0]), float(c["y"][-1])], 'o', color=color, markersize=6, zorder=5)

    ax.axvspan(t1, t2, alpha=0.10, color='gold', zorder=0)
    ax.axvline(t1, color='gray', lw=1.0, linestyle='--', alpha=0.6)
    ax.axvline(t2, color='gray', lw=1.0, linestyle='--', alpha=0.6)

    tfs, lfs, lgfs = fig_font_sizes(fig)
    ax.set_xlabel(f"{x_label} (s)", fontweight='bold', fontsize=lfs)
    ax.set_ylabel(y_label, fontweight='bold', fontsize=lfs)
    ax.legend(fontsize=lgfs, loc='best')
    ax.set_title(f"Curve Fit — {model_name.split('(')[0].strip()}", fontweight='bold', fontsize=tfs)
    ax.grid(True, linestyle=':', alpha=0.5)
    fig.tight_layout()
    ax.set_xlim(view_start, view_end)
    return ax


def curve_fit_from_tables(tables, parameters, figure=None, x_label="Time", y_label=None):
    curve = find(tables, "Channel", "time_s", "value", "fit")
    if curve is None:
        return None
    fits = find(tables, "Channel", "Model", "Parameter", "Value", "R2")
    context = next((t for t in tables.values() if has(t, "Channel", "time_s", "value") and "fit" not in t.columns), None)
    model_name = str(curve["Model"].iloc[0]) if "Model" in curve.columns and len(curve) else         str(fits.iloc[0]["Model"]) if fits is not None and len(fits) else "Curve fit"
    r2 = {str(c): float(g["R2"].iloc[0]) for c, g in fits.groupby("Channel", sort=False)} if fits is not None else {}
    ctx_by_channel = {name: g for name, g in table_channels(context)} if context is not None else {}
    channels = []
    for name, g in table_channels(curve):
        fit = float_array(g["fit"])
        wide = ctx_by_channel.get(name, g)
        channels.append({"label": name or "Signal", "color": channel_color(name),
                         "x_ctx": float_array(wide["time_s"]), "y_ctx": float_array(wide["value"]),
                         "x": float_array(g["time_s"]), "y": float_array(g["value"]),
                         "fit": fit if np.isfinite(fit).any() else None, "r2": r2.get(name, float("nan"))})
    t1 = float(fits.iloc[0]["t1 (s)"]) if fits is not None and len(fits) else float(min(c["x"][0] for c in channels))
    t2 = float(fits.iloc[0]["t2 (s)"]) if fits is not None and len(fits) else float(max(c["x"][-1] for c in channels))
    view_start = min(t1, min(float(c["x_ctx"][0]) for c in channels))
    view_end = max(t2, max(float(c["x_ctx"][-1]) for c in channels))
    if y_label is None:                                    # what the app's own plot calls the axis for this kind of recording
        y_label = "Delta Concentration (uM)" if all(c["label"].startswith("Mean ") for c in channels) else "Amplitude"
    fig = new_curve_fit_figure(figure)
    draw_curve_fit(fig, channels, model_name=model_name, t1=t1, t2=t2, view_start=view_start, view_end=view_end,
                   x_label=x_label, y_label=y_label)
    return fig


# ---------------------------------------------------------------------------
# Event PETH: every trial as a heatmap row over the mean (or the trials, or a view's overlay)
# ---------------------------------------------------------------------------

# Cycled (modulo) across trials in the "Trials" overlay view — tab10 + tab20's paler companions, a longer list than
# usual since trial counts run higher than typical column counts.
TRIAL_COLORS = [
    '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
    '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',
    '#aec7e8', '#ffbb78', '#98df8a', '#ff9896', '#c5b0d5',
]
EVENT_PETH_VIEWS = ("zscore", "trials", "auc", "peak", "bins")


def new_event_peth_figure(figure=None):
    """An empty figure for draw_event_peth — a window keeps it and draws into it on every change."""
    return _figure((8, 7), figure)


def row_order(sub_matrix, sort_by_peak):
    """Which row goes where: the trials as they came, or the biggest response first."""
    n = sub_matrix.shape[0]
    if sort_by_peak:
        peak = np.abs(sub_matrix).max(axis=1) if n else np.array([])
        return np.argsort(peak)[::-1]
    return np.arange(n)


def draw_event_peth(fig, *, time_axis, trial_matrix, trial_numbers, pre, post, bin_s=1.0, view="zscore",
                    sort_by_peak=False, signal_label="Normalized", title=None, event_name=""):
    """Clears `fig` and draws the figure for one view on fresh axes, returning them as (ax_heat, ax_line). The figure is
    rebuilt each time, not redrawn over: matplotlib's tight layout leaves its result in the figure, so a redraw can lay out
    differently from a first draw of the same thing — this way the same inputs always give the same picture.

    trial_matrix   the checked trials only, one row each (n_trials x n_samples) — the mean, the SEM, and every overlay
                   are of these; trial_numbers[i] is row i's own number (1-based, as in the trial list and the CSVs)
    view           "zscore" (mean +/- SEM), "trials" (every trial's own trace), "auc" (area under the mean shaded),
                   "peak" (the mean's peak marked), "bins" (the mean-time bins marked)
    sort_by_peak   order the heatmap rows by the size of their response; the labels stay the trials' own numbers
"""
    sub_matrix = np.asarray(trial_matrix, dtype=float)
    n_selected = sub_matrix.shape[0]
    mean_trace, sem_trace = api.stats.group_stats(sub_matrix)
    gp = api.stats.peri_event_from_trace(time_axis, mean_trace, post, bin_s) if n_selected > 0 else \
        {"peak_amplitude": 0.0, "latency": 0.0, "mean_bins": []}

    _clear(fig)
    ax_heat, ax_line = fig.subplots(2, 1, sharex=True, gridspec_kw={'height_ratios': [2, 1]})
    ax_heat.pyat_panel, ax_line.pyat_panel = "Trials heatmap", "Group trace"      # names in the figure-data CSV
    ax_heat.pyat_row_labels = None

    if n_selected == 0:
        ax_heat.text(0.5, 0.5, "No trials selected", ha='center', va='center', transform=ax_heat.transAxes)
        ax_heat.set_yticks([])
    else:
        order = row_order(sub_matrix, sort_by_peak)
        # Scaled to this trial set's own spread rather than a fixed range, so a quiet
        # recording isn't washed out and a big responder isn't clipped.
        scale = np.nanpercentile(np.abs(sub_matrix), 98) or 1.0
        # Row k (1 = top) is centred on y = k, so it spans k - 0.5 .. k + 0.5. With the extent
        # running 0..n instead, integer ticks fell on the edges between rows and the first trial read as "0".
        im = ax_heat.imshow(
            sub_matrix[order], aspect='auto', cmap='YlGnBu_r',
            extent=[-pre, post, n_selected + 0.5, 0.5],
            vmin=-scale, vmax=scale, interpolation='nearest',
        )
        fig.colorbar(im, ax=ax_heat, fraction=0.046, pad=0.04, label="Z-score")
        # Labelled with the trial's own number (the one in the checklist and the CSVs), not its
        # row: sorted by peak amplitude the rows are shuffled, and a row count would mislabel them.
        numbers = [int(trial_numbers[j]) for j in order]
        step = max(1, -(-n_selected // 10))                  # at most ~10 labels, whatever the trial count
        ticks = list(range(1, n_selected + 1, step))
        ax_heat.set_yticks(ticks)
        ax_heat.set_yticklabels([str(numbers[t - 1]) for t in ticks])
        ax_heat.pyat_row_labels = numbers                                             # the data CSV names rows by trial

    tfs, lfs, _ = fig_font_sizes(fig)
    ax_heat.set_ylabel("Trial (sorted by peak)" if sort_by_peak else "Trial", fontweight='bold', fontsize=lfs)
    ax_heat.axvline(0, color='red', linestyle='--', alpha=0.7)

    if view == "trials":
        # Every checked trial's own trace, no mean/SEM — a different color per trial (cycled if there are more
        # trials than colors), so trial-to-trial shape/timing differences are visible directly.
        for local_i in range(n_selected):
            ax_line.plot(time_axis, sub_matrix[local_i],
                         color=TRIAL_COLORS[local_i % len(TRIAL_COLORS)],
                         linewidth=1.0, alpha=0.85, label=f"Trial {int(trial_numbers[local_i])}")
    else:
        ax_line.plot(time_axis, mean_trace, color='black', linewidth=1.5, label="Mean")
        ax_line.fill_between(time_axis, mean_trace - sem_trace, mean_trace + sem_trace,
                             color='black', alpha=0.2, label="SEM")
    ax_line.axvline(0, color='red', linestyle='--', alpha=0.7)

    # View-specific overlay for the group trace — only the active toggle's overlay is drawn. "zscore" (the
    # baseline view) deliberately adds nothing beyond the mean/SEM trace above.
    if n_selected > 0:
        if view == "auc":
            ax_line.fill_between(time_axis, mean_trace, 0, where=(mean_trace >= 0), color='green', alpha=0.25)
            ax_line.fill_between(time_axis, mean_trace, 0, where=(mean_trace <= 0), color='red', alpha=0.25)
        elif view == "peak":
            ax_line.axvline(gp["latency"], color='gray', lw=1.0, linestyle=':', alpha=0.7)
            ax_line.scatter([gp["latency"]], [gp["peak_amplitude"]], color='red', zorder=5, s=35, label="Peak")
        elif view == "bins":
            for b in gp["mean_bins"]:
                ax_line.axvline(b["bin_start"], color='gray', lw=0.5, alpha=0.3)

    ax_line.set_xlim([-pre, post])
    ax_line.set_ylabel(f"Z-Score ({signal_label})", fontweight='bold', fontsize=lfs)
    ax_line.set_xlabel("Time from Event (s)", fontweight='bold', fontsize=lfs)
    if view != "trials":
        # Trials view has no labeled artists (a legend entry per trial would be unreadable past a handful of
        # trials) — color is identified via the trial list instead.
        ax_line.legend(fontsize=lfs * 0.8, loc='upper right')

    fig.suptitle(title or f"Event PETH — {event_name}", fontsize=tfs, fontweight='bold')
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    return ax_heat, ax_line


def event_peth_from_tables(tables, parameters, figure=None, view="zscore", sort_by_peak=False, signal_label="Normalized", title=None):
    trials = find(tables, "Trial", "time_from_event_s", "z_score")
    if trials is None or "Channel" in trials.columns:
        return None
    wide = trials.pivot_table(index="Trial", columns="time_from_event_s", values="z_score", sort=True)
    time_axis, matrix = wide.columns.to_numpy(float), wide.to_numpy(float)
    pre = parameters.get("pre_s")
    post = parameters.get("post_s")
    fig = new_event_peth_figure(figure)
    draw_event_peth(fig, time_axis=time_axis, trial_matrix=matrix, trial_numbers=[int(n) for n in wide.index],
                    pre=float(pre) if pre is not None else -float(time_axis.min()),
                    post=float(post) if post is not None else float(time_axis.max()),
                    bin_s=float(parameters.get("bin_s", 1.0)), view=view, sort_by_peak=sort_by_peak,
                    signal_label=signal_label, title=title, event_name=str(parameters.get("event", "")))
    return fig

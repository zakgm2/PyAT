"""
figures/panels.py
-----------------
The generic figure: one panel per result table, for what the app has no figure of its own for — a peak finder's results,
the intervals between markers, the processed traces, and one table of an Event PETH view exported on its own. The
analysis windows' figures (draw.py) and the group analysis's (group.py) are the app's; these are the library's own.
"""

import numpy as np
import pandas as pd

from .tables import channels as _channels
from .tables import find as _find
from .tables import has as _has
from .tables import numeric as _numeric


def _label(ax, x, y):
    ax.set_xlabel(x)
    ax.set_ylabel(y)


def _legend(ax, handles_needed):
    if handles_needed > 1:
        ax.legend(fontsize=8, frameon=False)


def _bin_columns(table):
    return [c for c in table.columns if str(c).startswith("Bin ") and str(c).endswith("s Mean")]


def _auc_bars(ax, table, tables, fig):
    names = [str(c) or "signal" for c in table["Channel"]]
    where = np.arange(len(table))
    ax.bar(where - 0.2, table["Positive AUC"], 0.4, color="green", alpha=0.6, label="Positive AUC")
    ax.bar(where + 0.2, table["Negative AUC"], 0.4, color="red", alpha=0.6, label="Negative AUC")
    ax.plot(where, table["Total AUC"], "D", color="black", label="Total AUC")
    ax.set_xticks(where)
    ax.set_xticklabels(names)
    ax.axhline(0, color="black", lw=0.6, alpha=0.4)
    _label(ax, "", "Area under the curve")
    ax.legend(fontsize=8, frameon=False)


def _fft_peaks_alone(ax, table, tables, fig):
    for name, g in _channels(table):
        ax.vlines(g["Frequency (Hz)"], 0, g["Power"], lw=2, label=name or None)
        ax.plot(g["Frequency (Hz)"], g["Power"], "o")
    _label(ax, "Frequency (Hz)", "Power")


def _mean_sem(ax, table, tables, fig):
    t, m, s = (table[c].to_numpy(float) for c in ("time_from_event_s", "mean", "sem"))
    ax.plot(t, m, color="black", lw=1.5, label="Mean")
    ax.fill_between(t, m - s, m + s, color="black", alpha=0.2, label="SEM")
    ax.axvline(0, color="red", ls="--", alpha=0.7)
    _label(ax, "Time from event (s)", "Z-score")
    ax.legend(fontsize=8, frameon=False, loc="upper right")


def _peaks_over_time(ax, table, tables, fig):
    colors = {"peak": "tab:red", "trough": "tab:blue"}
    for kind, g in table.groupby("kind", sort=False):
        c = colors.get(str(kind), "tab:gray")
        ax.vlines(g["time_s"], 0, g["z_score"], colors=c, lw=1.2)
        ax.plot(g["time_s"], g["z_score"], "o", color=c, ms=4, label=str(kind))
    ax.axhline(0, color="black", lw=0.6, alpha=0.4)
    _label(ax, "Time (s)", "Z-score")
    _legend(ax, table["kind"].nunique())


def _scan(ax, table, tables, fig):
    t = table.iloc[::-1]
    ax.barh(t["Event"].astype(str), t["Hit Rate"], color="tab:blue")
    for y, (_, r) in enumerate(t.iterrows()):
        ax.text(r["Hit Rate"], y, f"  {int(r['Found'])}/{int(r['Occurrences'])}", va="center", fontsize=8)
    ax.set_xlim(0, 1.15)
    _label(ax, "Hit rate (fraction of occurrences with a significant peak)", "")


def _alignment(ax, table, tables, fig):
    found = table[table["Found"].astype(str).str.lower().isin(["true", "1"])]
    ax.plot(table["Event Time (s)"], np.zeros(len(table)), "|", color="gray", ms=10, label="events")
    ax.plot(found["Event Time (s)"], found["Z-score"], "o", color="tab:red", label="peak near event")
    ax.set_title(f"{len(found)} of {len(table)} events had a peak near them", fontsize=9)
    _label(ax, "Event time (s)", "Z-score of the peak")
    ax.legend(fontsize=8, frameon=False)


def _intervals(ax, table, tables, fig):
    ax.vlines(table["time_s"], 0, table["dt_since_prev_any_s"], colors="tab:blue", lw=1.5, label="since any marker")
    ax.plot(table["time_s"], table["dt_since_prev_any_s"], "o", color="tab:blue", ms=4)
    if "dt_since_prev_same_store_s" in table.columns:
        ax.plot(table["time_s"], table["dt_since_prev_same_store_s"], "s", color="tab:orange", ms=4, label="since the same store's")
    _label(ax, "Marker time (s)", "Time since previous (s)")
    ax.legend(fontsize=8, frameon=False)


def _per_trial(table):
    """(the trials' rows with a numeric `trial` and a boolean `checked`, the group's row or None): an Event PETH table
    has a trial per row and, last, one row for the group of the checked trials."""
    trial = pd.to_numeric(table["Trial"], errors="coerce")
    rows = table[trial.notna()].copy()
    rows["trial"] = trial[trial.notna()].astype(int)
    rows["checked"] = rows["Checked"].astype(str).str.lower().isin(["true", "1"]) if "Checked" in rows else True
    group = table[trial.isna()]
    return rows, (group.iloc[0] if len(group) else None)


def _peth_trace(ax, table, tables, fig):
    ax.plot(table["time_from_event_s"], table["z_score"], color="black", lw=1.5)
    ax.axvline(0, color="red", ls="--", alpha=0.7)
    ax.axhline(0, color="black", lw=0.6, alpha=0.4)
    _label(ax, "Time from event (s)", "Z-score")


def _trial_auc(ax, table, tables, fig):
    rows, group = _per_trial(table)
    alpha = np.where(rows["checked"], 0.85, 0.3)                    # an unchecked trial is faded
    for bars in (ax.bar(rows["trial"], rows["Positive AUC"], 0.8, color="green", label="Positive"),
                 ax.bar(rows["trial"], rows["Negative AUC"], 0.8, color="red", label="Negative")):
        for bar, a in zip(bars, alpha):
            bar.set_alpha(float(a))
    ax.plot(rows["trial"], rows["Total AUC"], "D", color="black", ms=4, label="Total")
    ax.axhline(0, color="black", lw=0.6, alpha=0.4)
    if group is not None:
        ax.set_title(f"Group (checked trials): total {group['Total AUC']:.3g}  (+{group['Positive AUC']:.3g} / {group['Negative AUC']:.3g})", fontsize=9)
    _label(ax, "Trial", "Area under the curve")
    ax.legend(fontsize=8, frameon=False)


def _trial_peak(ax, table, tables, fig):
    rows, group = _per_trial(table)
    for bar, checked in zip(ax.bar(rows["trial"], rows["Peak Amplitude"], 0.8, color="tab:blue"), rows["checked"]):
        bar.set_alpha(0.85 if checked else 0.3)
    ax.axhline(0, color="black", lw=0.6, alpha=0.4)
    if group is not None:
        ax.set_title(f"Group (checked trials): peak {group['Peak Amplitude']:.3g} at +{group['Time-to-Peak (s)']:.2f} s", fontsize=9)
    _label(ax, "Trial", "Peak amplitude (z-score)")


def _trial_bins(ax, table, tables, fig):
    columns = _bin_columns(table)
    values = table[columns].apply(pd.to_numeric, errors="coerce").to_numpy(float)
    labels = [str(t) if str(t).isdigit() else "Group" for t in table["Trial"]]
    finite = np.abs(values[np.isfinite(values)])
    scale = float(np.percentile(finite, 98)) if finite.size else 1.0
    image = ax.imshow(values, aspect="auto", cmap="YlGnBu_r", vmin=-scale or -1.0, vmax=scale or 1.0, interpolation="nearest")
    ax.set_xticks(range(len(columns)))
    ax.set_xticklabels([c[len("Bin "):-len(" Mean")] for c in columns], rotation=45, ha="right", fontsize=8)
    step = max(1, -(-len(labels) // 12))
    ax.set_yticks(range(0, len(labels), step))
    ax.set_yticklabels(labels[::step], fontsize=8)
    ax.set_ylabel("Trial")
    ax.set_xlabel("Time from event, mean in each bin")
    fig.colorbar(image, ax=ax, fraction=0.046, pad=0.02, label="Z-score")


def _traces(ax, table, tables, fig):
    columns = _numeric(table, ("time_s",))[:8]
    for c in columns:
        ax.plot(table["time_s"], table[c], lw=1.0, label=str(c))
    _label(ax, "Time (s)", "Signal")
    _legend(ax, len(columns))


def _plan(tables, parameters):
    """[(weight, painter, table, height)] — what to draw, top to bottom, and how tall each panel is relative to a plain
    trace. Only what the app has no figure of its own for: the analysis windows and the group analysis are drawn by
    draw.py and group.py; this is the rest — a peak finder's results, the intervals between markers, the processed
    traces, and a single table of an Event PETH view exported on its own."""
    plan = []
    whole_peth = _find(tables, "Trial", "time_from_event_s", "z_score") is not None
    has_band = _find(tables, "time_from_event_s", "mean", "sem") is not None
    for table in tables.values():
        if _has(table, "time_from_event_s", "mean", "sem"):
            plan.append((1, _mean_sem, table, 1.0))
        elif _has(table, "time_from_event_s", "z_score") and "Trial" not in table.columns and not has_band:
            plan.append((1, _peth_trace, table, 1.0))                  # one Event PETH view exported on its own
        elif _has(table, "Trial", "Total AUC", "Positive AUC", "Negative AUC") and "Channel" not in table.columns and not whole_peth:
            plan.append((1, _trial_auc, table, 1.0))
        elif _has(table, "Trial", "Peak Amplitude", "Time-to-Peak (s)") and not whole_peth:
            plan.append((1, _trial_peak, table, 1.0))
        elif _has(table, "Trial", "Trial Event Time (s)", "Checked") and _bin_columns(table) and not whole_peth:
            plan.append((1, _trial_bins, table, 1.2))
        elif _has(table, "time_s", "z_score", "kind"):
            plan.append((1, _peaks_over_time, table, 1.0))
        elif _has(table, "Event", "Occurrences", "Hit Rate"):
            plan.append((1, _scan, table, 1.0))
        elif _has(table, "Event Time (s)", "Found", "Z-score"):
            plan.append((2, _alignment, table, 1.0))
        elif _has(table, "time_s", "dt_since_prev_any_s"):
            plan.append((1, _intervals, table, 1.0))
        elif _has(table, "time_s") and "Channel" not in table.columns and len(_numeric(table, ("time_s",))) >= 1 \
                and not _has(table, "z_score"):
            plan.append((1, _traces, table, 1.0))
    if _find(tables, "Channel", "frequency_hz", "power") is None:        # peaks with no spectrum to sit on
        peaks = _find(tables, "Channel", "Frequency (Hz)", "Power")
        if peaks is not None:
            plan.append((1, _fft_peaks_alone, peaks, 1.0))
    if _find(tables, "Channel", "time_from_center_s", "value") is None:   # AUC with no trace under it
        auc = _find(tables, "Channel", "Total AUC", "Positive AUC", "Negative AUC")
        if auc is not None:
            plan.append((1, _auc_bars, auc, 1.0))
    plan.sort(key=lambda item: item[0])
    return plan


def panel_figure(tables, parameters, figure=None, title=None):
    """One figure of panels, one per table that is drawable here; None if none is. `figure` makes it (Figure by default,
    pyplot.figure for a window)."""
    plan = _plan(tables, parameters)
    if not plan:
        return None
    if figure is None:
        from matplotlib.figure import Figure
        figure = Figure
    heights = [height for _w, _painter, _t, height in plan]
    fig = figure(figsize=(9.0, 3.2 * sum(heights) + 0.8), layout="constrained")
    axes = fig.subplots(len(plan), 1, squeeze=False, gridspec_kw={"height_ratios": heights})[:, 0]
    for ax, (_weight, painter, table, _height) in zip(axes, plan):
        painter(ax, table, tables, fig)
    if title:
        fig.suptitle(title, fontweight="bold")
    return fig

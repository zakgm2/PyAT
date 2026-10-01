"""
analysis/group/plots.py
--------------------------
The figures for a finished group analysis (GroupResults), built with matplotlib: mean traces,
a per-marker subject x time heatmap, a measure-by-marker comparison plot with significance
brackets, and a residual/QQ diagnostics plot. Pure functions of `results` -> Figure, so they
can be saved to disk (run.py) and shown in a canvas (results_dialog.py) from the same code.

Output conventions, chosen to match what journals ask for:
  - Colors: the Okabe-Ito 8-color palette (Okabe & Ito 2002; the palette Nature/Nature Methods
    recommend for categorical data) for markers/subjects, so the figures are colorblind-safe by
    construction. Heatmaps use a diverging colormap (RdBu_r) centered on zero, scaled to the
    data instead of a fixed range.
  - Files: PNG (300 DPI) for a quick look and PDF (vector, so it re-scales for a manuscript)
    are both written for every figure — matplotlib's savefig picks the renderer from the
    extension, so the same figure object produces both. This mirrors the app's own Export Plot
    convention (PNG/PDF/SVG at 300 DPI, see analysis/dispatch.py's export_figure_to_file).
"""

from dataclasses import dataclass, field

import numpy as np
import scipy.stats as st
from matplotlib.figure import Figure
from matplotlib.patches import Patch

from PhysicsLibrary.analysis.group import METRIC_LABELS
from PhysicsLibrary.analysis.group_report import measure_units

# Okabe & Ito (2008), "Color Universal Design" — the 8-color qualitative palette Nature Methods
# recommends for categorical data. Black is reserved for reference lines/annotations, not cycled
# through for data series.
OKABE_ITO = ["#E69F00", "#56B4E9", "#009E73", "#F0E442", "#0072B2", "#D55E00", "#CC79A7", "#000000"]

# The measures figure uses grayscale bars (white/light gray/dark gray/black), the classic
# print-journal look for a grouped bar chart — Okabe-Ito stays for the other, colored figures.
BAR_SHADES = ["white", "0.75", "0.35", "0.55", "0.15"]

SAVE_FORMATS = ("png", "pdf")     # a raster for a quick look, a vector one that rescales cleanly
SAVE_DPI = 300

_LEGEND_LOCS = {
    # "best" maps to a fixed corner, not matplotlib's automatic placement — fig.legend() (unlike
    # an axes legend) doesn't support loc="best" at all (raises ValueError).
    "best": "upper right", "upper right": "upper right", "upper left": "upper left",
    "lower right": "lower right", "lower left": "lower left",
}


def categorical_colors(labels):
    """{label: color}, cycling through OKABE_ITO in the given order — used for markers in most
    figures, and for subjects in the per-subject dots of build_measures_figure."""
    return {label: OKABE_ITO[i % len(OKABE_ITO)] for i, label in enumerate(labels)}


def _grayscale_colors(labels):
    return {label: BAR_SHADES[i % len(BAR_SHADES)] for i, label in enumerate(labels)}


@dataclass
class MeasuresDisplayOptions:
    """How build_measures_figure draws — every field has a sensible default, so
    build_measures_figure(results) alone still gives the standard figure.

    marker_labels renames AND combines in one move: markers that map to the same label share one
    bar, with their subject-level values pooled (see _pooled_subject_values). A pooled bar has no
    significance bracket against anything — the mixed model was fit on the original markers, not
    on whatever ad hoc groups the label mapping created, so there is no p-value for it to show.
    """
    show_samples: bool = True
    show_box: bool = False
    marker_labels: dict = field(default_factory=dict)
    legend_visible: bool = True
    legend_position: str = "best"          # one of _LEGEND_LOCS, or "outside right"

    def label_for(self, marker):
        text = self.marker_labels.get(marker, "").strip()
        return text or marker


def _pooled_groups(spec, options):
    """Display labels in first-seen order, and {label: [original markers]} pooled under each."""
    order, members = [], {}
    for m in spec.markers:
        label = options.label_for(m)
        if label not in members:
            order.append(label)
            members[label] = []
        members[label].append(m)
    return order, members


def _pooled_subject_values(means_df, measure, order, members):
    """{label: {subject: pooled mean}} for one measure — a subject contributes to a group the
    average of whichever of that group's original markers it actually has data for."""
    sub = means_df[means_df["measure"] == measure] if len(means_df) else means_df
    by_subject = {}
    if len(sub):
        for _, r in sub.iterrows():
            by_subject.setdefault(r["subject"], {})[r["marker"]] = r["mean"]
    out = {label: {} for label in order}
    for subject, marker_vals in by_subject.items():
        for label in order:
            vals = [marker_vals[m] for m in members[label] if m in marker_vals]
            if vals:
                out[label][subject] = float(np.mean(vals))
    return out


def figure_title_text(fig):
    """The one overall title a figure has, whichever form it takes — fig.suptitle for a
    multi-panel figure (measures, diagnostics), ax.set_title on the figure's main axes for a
    single-panel one (traces, a heatmap) — or "" if neither is set. Pairs with
    set_figure_title_text below; used by results_dialog.py's editable Title field so every
    figure kind is renamable the same way regardless of which of the two matplotlib APIs
    actually holds its title.

    axes[0] (not "the only axes") on purpose: a heatmap figure's colorbar is itself a second,
    auxiliary axes (fig.colorbar() appends it), so "exactly one axes" would never match a
    heatmap at all — the main plotting axes is always added first, whether or not a colorbar
    joins it later."""
    if fig._suptitle is not None:
        return fig._suptitle.get_text()
    if fig.axes:
        return fig.axes[0].get_title()
    return ""


def set_figure_title_text(fig, text):
    if fig._suptitle is not None:
        fig._suptitle.set_text(text)
    elif fig.axes:
        fig.axes[0].set_title(text)


def _no_data_figure(message):
    fig = Figure(figsize=(7, 4), dpi=100)
    ax = fig.subplots()
    ax.text(0.5, 0.5, message, ha="center", va="center", wrap=True, color="gray")
    ax.axis("off")
    return fig


def _style(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def _signal_label(spec):
    return "z-score" if spec.signal == "zscore" else "dF/F"


def build_trace_figure(results):
    """Mean +/- SEM trace per marker, across subjects (each subject already averaged over its own
    trials — see group_trials.extract_group_trials). One panel; the baseline and response windows
    the measures were taken from are shaded for reference."""
    spec = results.spec
    grid = results.trace_grid
    if grid is None or not results.traces:
        return _no_data_figure("No trials to trace.")

    fig = Figure(figsize=(8, 5), dpi=100)
    ax = fig.subplots()
    colors = categorical_colors(spec.markers)
    for marker in spec.markers:
        rows = [d[marker]["mean"] for d in results.traces.values()
                if marker in d and d[marker]["n"] > 0]
        if not rows:
            continue
        stack = np.vstack(rows)
        mean = stack.mean(axis=0)
        sem = stack.std(axis=0, ddof=1) / np.sqrt(len(rows)) if len(rows) > 1 else np.zeros_like(mean)
        color = colors[marker]
        ax.plot(grid, mean, color=color, lw=1.8, label=f"{marker}  (n={len(rows)})")
        ax.fill_between(grid, mean - sem, mean + sem, color=color, alpha=0.25, linewidth=0)

    ax.axvspan(*spec.baseline, color="gray", alpha=0.12, zorder=0, label="baseline")
    ax.axvspan(*spec.response, color="gold", alpha=0.12, zorder=0, label="response")
    ax.axvline(0, color="black", lw=0.8, ls="--", zorder=0)
    ax.set_xlabel("Time from event (s)")
    ax.set_ylabel(f"{_signal_label(spec)} (mean ± SEM across subjects)")
    ax.set_title(f"{spec.group_name}: mean response")
    ax.legend(loc="best", fontsize=9, frameon=False)
    _style(ax)
    fig.tight_layout()
    return fig


def build_heatmap_figures(results):
    """{marker: Figure}: one subject x time heatmap per marker in spec.markers with at least one
    subject's trace. Rows follow spec.subjects order; a subject with no valid trials of that
    marker is shown as a blank row rather than silently dropped, so the row count stays meaningful."""
    spec = results.spec
    grid = results.trace_grid
    if grid is None:
        return {}
    out = {}
    subjects = [s["subject"] for s in spec.subjects]
    for marker in spec.markers:
        rows = []
        present = [s for s in subjects if results.traces.get(s, {}).get(marker, {}).get("n", 0) > 0]
        if not present:
            continue
        for s in subjects:
            d = results.traces.get(s, {}).get(marker)
            rows.append(d["mean"] if d and d["n"] > 0 else np.full(len(grid), np.nan))
        mat = np.vstack(rows)
        # Symmetric around zero, sized off the heatmap's own peak amplitude with 2 units of
        # headroom so the peak doesn't sit right at the colorbar's edge — e.g. a 2.5 peak scales
        # to -4..4, a 7 peak to -9..9.
        finite = mat[np.isfinite(mat)]
        peak = float(np.max(np.abs(finite))) if finite.size else 0.0
        scale = np.floor(peak) + 2

        fig = Figure(figsize=(8, max(2.5, 0.35 * len(subjects) + 1.2)), dpi=100)
        ax = fig.subplots()
        im = ax.imshow(mat, aspect="auto", cmap="RdBu_r", vmin=-scale, vmax=scale,
                       extent=[grid[0], grid[-1], len(subjects) - 0.5, -0.5], interpolation="nearest")
        ax.axvline(0, color="black", lw=0.8, ls="--")
        ax.set_yticks(range(len(subjects)))
        ax.set_yticklabels(subjects, fontsize=8)
        ax.set_xlabel("Time from event (s)")
        ax.set_title(f"{spec.group_name}: {marker}")
        cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02)
        cbar.set_label(_signal_label(spec))
        fig.tight_layout()
        out[marker] = fig
    return out


def _sig_stars(p):
    if not np.isfinite(p):
        return ""
    if p < 0.001:
        return "***"
    if p < 0.01:
        return "**"
    if p < 0.05:
        return "*"
    return "ns"


def _draw_brackets(ax, pairs, x_of, y_top, gap):
    """Draws each (marker_a, marker_b, text) as a bracket above the data, stacked so overlapping
    pairs don't collide — adjacent pairs sit lowest, pairs that span more markers sit higher."""
    order = sorted(pairs, key=lambda p: abs(x_of[p[1]] - x_of[p[0]]))
    levels = []  # (lo, hi, y) already placed
    for a, b, text in order:
        x0, x1 = sorted((x_of[a], x_of[b]))
        y = y_top
        for lo, hi, ly in levels:
            if x0 < hi and x1 > lo:
                y = max(y, ly + gap)
        levels.append((x0, x1, y))
        ax.plot([x0, x0, x1, x1], [y, y + gap * 0.2, y + gap * 0.2, y], color="black", lw=1.0)
        ax.text((x0 + x1) / 2, y + gap * 0.25, text, ha="center", va="bottom", fontsize=9)
    return max((y for _, _, y in levels), default=y_top) + gap if levels else y_top


def _draw_measure_bars(ax, group_values, order, colors, options):
    """Draws one bar (or box-and-whisker) per group, at integer x positions in `order`, plus
    jittered sample dots if asked for. Returns {label: x position} for bracket placement."""
    x_of = {}
    for i, label in enumerate(order):
        x = float(i)
        x_of[label] = x
        vals = list(group_values[label].values())
        color = colors[label]
        if not vals:
            continue
        if options.show_box:
            ax.boxplot([vals], positions=[x], widths=0.55, patch_artist=True, showfliers=False, zorder=2,
                       boxprops=dict(facecolor=color, edgecolor="black", linewidth=1.0),
                       medianprops=dict(color="black", linewidth=1.3),
                       whiskerprops=dict(color="black", linewidth=1.0),
                       capprops=dict(color="black", linewidth=1.0))
        else:
            mean = float(np.mean(vals))
            ax.bar(x, mean, width=0.55, color=color, edgecolor="black", linewidth=1.0, zorder=2)
            if len(vals) > 1:
                sem = float(np.std(vals, ddof=1) / np.sqrt(len(vals)))
                ax.errorbar(x, mean, yerr=sem, color="black", capsize=4, elinewidth=1.2, zorder=3)
        if options.show_samples:
            rng = np.random.RandomState(i)                    # deterministic jitter, same figure every rebuild
            jitter = (rng.rand(len(vals)) - 0.5) * 0.28
            dot_face = "black" if color == "white" else "white"
            ax.scatter(np.full(len(vals), x) + jitter, vals, s=16, zorder=4,
                       facecolor=dot_face, edgecolor="black", linewidth=0.6, alpha=0.9)
    return x_of


def build_measures_figure(results, options=None, measure=None):
    """One panel per measure in spec.metrics (or just the one named by `measure`, full-size —
    see the Customize panel's "Measure:" selector, useful for box-and-whisker especially, which
    is cramped in a small grid cell): a bar (mean +/- SEM across subjects) or a box-and-whisker
    per marker — grouped-bar-chart style, matching a typical journal figure — with individual
    subject values optionally overlaid as jittered dots. Markers renamed to the same label in
    `options` are combined into one pooled bar (see MeasuresDisplayOptions).

    With two or more markers left un-pooled, every pairwise comparison between them gets a
    significance bracket (Holm/Bonferroni/FDR-adjusted p, per spec.correction, from the mixed
    model's trial-level fit) — a pooled bar has no bracket, since the model never saw that
    grouping. With exactly one marker in the original design (pooling aside), a dashed zero line
    and the test-against-zero p-value are shown instead, for the measures that have one (AUC,
    mean amplitude). One shared legend for the whole figure, not one per panel.

    layout='constrained' (not a one-shot fig.tight_layout()) so the title/legend/panel spacing
    keeps re-solving itself as the figure is resized — fig.tight_layout() only computes once, at
    build time, which is what let the suptitle collide with the panel titles below it whenever
    the canvas ended up smaller than whatever size happened to be current when this ran."""
    spec = results.spec
    all_measures = list(spec.metrics)
    if not all_measures:
        return _no_data_figure("No measures selected.")
    measures = [measure] if measure is not None else all_measures
    options = options or MeasuresDisplayOptions()
    order, members = _pooled_groups(spec, options)
    colors = _grayscale_colors(order)
    pure_marker_to_label = {members[label][0]: label for label in order if len(members[label]) == 1}

    n = len(measures)
    if measure is not None:
        ncols, nrows = 1, 1
        fig = Figure(figsize=(6.5, 5.5), dpi=100, layout="constrained")
    else:
        ncols = min(3, n)
        nrows = -(-n // ncols)
        fig = Figure(figsize=(4.2 * ncols, 3.6 * nrows), dpi=100, layout="constrained")
    axes = fig.subplots(nrows, ncols, squeeze=False).ravel()

    for ax, measure in zip(axes, measures):
        label = METRIC_LABELS.get(measure, measure)
        group_values = _pooled_subject_values(results.subject_means, measure, order, members)
        x_of = _draw_measure_bars(ax, group_values, order, colors, options)

        ax.set_xticks([x_of[label] for label in order])
        ax.set_xticklabels(order, rotation=15 if any(len(g) > 6 for g in order) else 0)
        ax.set_xlim(-0.6, len(order) - 0.4)
        ax.set_ylabel(f"{label} ({measure_units(measure, spec.signal)})")
        ax.set_title(label)
        top = ax.get_ylim()[1]
        gap = 0.08 * (ax.get_ylim()[1] - ax.get_ylim()[0]) or 0.1

        if len(pure_marker_to_label) >= 2:
            pw = results.pairwise[(results.pairwise["measure"] == measure)
                                  & (results.pairwise["basis"] == "trials")] if len(results.pairwise) else results.pairwise
            pairs = []
            for _, r in pw.iterrows():
                la, lb = pure_marker_to_label.get(r["marker_a"]), pure_marker_to_label.get(r["marker_b"])
                if la is not None and lb is not None and la != lb:
                    pairs.append((la, lb, _sig_stars(r["p_adjusted"])))
            if pairs:
                new_top = _draw_brackets(ax, pairs, x_of, top + gap, gap)
                ax.set_ylim(ax.get_ylim()[0], new_top + gap)
        elif len(spec.markers) == 1:
            fe = results.fixed_effects[(results.fixed_effects["measure"] == measure)
                                       & (results.fixed_effects["basis"] == "trials")] if len(results.fixed_effects) else results.fixed_effects
            if len(fe) and np.isfinite(fe.iloc[0]["p_t"]):
                ax.axhline(0, color="black", lw=0.8, ls="--", zorder=0)
                ax.text(0.5, 0.98, f"vs. 0: {_sig_stars(fe.iloc[0]['p_t'])} (p={fe.iloc[0]['p_t']:.3g})",
                       transform=ax.transAxes, ha="center", va="top", fontsize=8)
        _style(ax)

    for ax in axes[n:]:
        ax.axis("off")
    title = f"{spec.group_name}: measures by marker"
    if len(measures) == 1:
        title += f" — {METRIC_LABELS.get(measures[0], measures[0])}"
    fig.suptitle(title)

    if options.legend_visible and len(order) > 1:
        handles = [Patch(facecolor=colors[g], edgecolor="black", label=g) for g in order]
        if options.legend_position == "outside right":
            # A real "outside the axes" location, not an inset — constrained layout (see above)
            # shrinks the panels to make room for it and keeps doing so as the figure resizes,
            # unlike the old bbox_to_anchor + one-shot tight_layout(rect=...) this replaced.
            fig.legend(handles=handles, loc="outside right upper", frameon=False, fontsize=9)
        else:
            fig.legend(handles=handles, loc=_LEGEND_LOCS.get(options.legend_position, "best"),
                       frameon=True, edgecolor="none", framealpha=0.85, fontsize=9)
    return fig


def build_diagnostics_figure(results):
    """Residuals vs fitted, and a QQ plot against a normal distribution, for every measure whose
    trial-level model was fitted (mixed-model diagnostics only make sense on that basis — the
    subject-means check has too few points per measure to judge). None if no model fitted."""
    spec = results.spec
    fitted = [m for m in spec.metrics
             if len(results.models) and ((results.models["measure"] == m) & (results.models["basis"] == "trials")
                                         & (results.models["status"] == "fitted")).any()]
    if not fitted or not len(results.diagnostics):
        return None

    fig = Figure(figsize=(8, 3.2 * len(fitted)), dpi=100)
    axes = fig.subplots(len(fitted), 2, squeeze=False)
    colors = categorical_colors(spec.markers)
    for row, measure in zip(axes, fitted):
        d = results.diagnostics[results.diagnostics["measure"] == measure]
        ax_r, ax_q = row
        for marker in spec.markers:
            sub = d[d["marker"] == marker]
            if len(sub):
                ax_r.scatter(sub["fitted"], sub["resid"], s=8, alpha=0.5, color=colors[marker], label=marker)
        ax_r.axhline(0, color="black", lw=0.8, ls="--")
        ax_r.set_xlabel("Fitted")
        ax_r.set_ylabel("Residual")
        ax_r.set_title(f"{METRIC_LABELS.get(measure, measure)}: residuals")
        if len(spec.markers) > 1:
            ax_r.legend(fontsize=7, frameon=False, loc="best")

        (osm, osr), (slope, intercept, _r) = st.probplot(d["resid"].to_numpy(float), dist="norm")
        ax_q.scatter(osm, osr, s=8, alpha=0.5, color="0.4")
        ax_q.plot(osm, slope * osm + intercept, color="black", lw=1.0)
        ax_q.set_xlabel("Theoretical quantiles")
        ax_q.set_ylabel("Residual quantiles")
        ax_q.set_title(f"{METRIC_LABELS.get(measure, measure)}: Q-Q")
        _style(ax_r)
        _style(ax_q)
    fig.suptitle(f"{spec.group_name}: model diagnostics (trial-level)")
    fig.tight_layout()
    return fig


def build_all_figures(results):
    """{name: Figure} for every figure this analysis produces — "traces", "heatmap_<marker>" (one
    per marker with data), "measures", and "diagnostics" if any model was fitted."""
    out = {"traces": build_trace_figure(results)}
    for marker, fig in build_heatmap_figures(results).items():
        out[f"heatmap_{marker}"] = fig
    out["measures"] = build_measures_figure(results)
    diag = build_diagnostics_figure(results)
    if diag is not None:
        out["diagnostics"] = diag
    return out


def save_figures(figures, directory):
    """Saves every figure as PNG (300 DPI) and PDF (vector) into `directory` (created if needed),
    named figure_<key>.<ext>. Returns the paths written."""
    import os
    os.makedirs(directory, exist_ok=True)
    paths = []
    for name, fig in figures.items():
        for ext in SAVE_FORMATS:
            path = os.path.join(directory, f"figure_{name}.{ext}")
            fig.savefig(path, dpi=SAVE_DPI, bbox_inches="tight")
            paths.append(path)
    return paths

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

import numpy as np
import scipy.stats as st
from matplotlib.figure import Figure

from PhysicsLibrary.analysis.group import METRIC_LABELS
from PhysicsLibrary.analysis.group_report import measure_units

# Okabe & Ito (2008), "Color Universal Design" — the 8-color qualitative palette Nature Methods
# recommends for categorical data. Black is reserved for reference lines/annotations, not cycled
# through for data series.
OKABE_ITO = ["#E69F00", "#56B4E9", "#009E73", "#F0E442", "#0072B2", "#D55E00", "#CC79A7", "#000000"]

SAVE_FORMATS = ("png", "pdf")     # a raster for a quick look, a vector one that rescales cleanly
SAVE_DPI = 300


def categorical_colors(labels):
    """{label: color}, cycling through OKABE_ITO in the given order — used for markers in most
    figures, and for subjects in the per-subject dots of build_measures_figure."""
    return {label: OKABE_ITO[i % len(OKABE_ITO)] for i, label in enumerate(labels)}


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
        scale = np.nanpercentile(np.abs(mat), 98) or 1.0

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


def build_measures_figure(results):
    """One panel per measure in spec.metrics: each subject's mean (dots, connected across markers
    by subject so the paired design is visible), the model-estimated marker mean +/- 95% CI
    (basis "trials"), and, with two or more markers, every pairwise comparison as a significance
    bracket (Holm/Bonferroni/FDR-adjusted p, per spec.correction). One marker has nothing to
    compare, so a dashed zero line and the test-against-zero p-value are shown instead, for the
    measures that have one (AUC, mean amplitude)."""
    spec = results.spec
    measures = list(spec.metrics)
    if not measures:
        return _no_data_figure("No measures selected.")
    n = len(measures)
    ncols = min(3, n)
    nrows = -(-n // ncols)
    fig = Figure(figsize=(4.2 * ncols, 3.6 * nrows), dpi=100)
    axes = fig.subplots(nrows, ncols, squeeze=False).ravel()
    colors = categorical_colors([s["subject"] for s in spec.subjects])
    x_of = {m: i for i, m in enumerate(spec.markers)}

    for ax, measure in zip(axes, measures):
        label = METRIC_LABELS.get(measure, measure)
        means = results.subject_means[results.subject_means["measure"] == measure] if len(results.subject_means) else results.subject_means
        for subject in [s["subject"] for s in spec.subjects]:
            row = means[means["subject"] == subject].set_index("marker")["mean"] if len(means) else None
            xs = [x_of[m] for m in spec.markers if row is not None and m in row.index]
            ys = [row[m] for m in spec.markers if row is not None and m in row.index]
            if len(xs) > 1:
                ax.plot(xs, ys, color="0.7", lw=0.6, zorder=1)
            if xs:
                ax.scatter(xs, ys, color=colors.get(subject, "0.4"), s=18, zorder=2, edgecolor="none")

        emm = results.estimated_means[(results.estimated_means["measure"] == measure)
                                      & (results.estimated_means["basis"] == "trials")] if len(results.estimated_means) else results.estimated_means
        for _, r in emm.iterrows():
            x = x_of.get(r["marker"])
            if x is None:
                continue
            lo, hi = r["ci_low"], r["ci_high"]
            if np.isfinite(lo) and np.isfinite(hi):
                ax.errorbar([x], [r["mean"]], yerr=[[r["mean"] - lo], [hi - r["mean"]]],
                           fmt="D", color="black", capsize=4, ms=6, zorder=3)
            else:
                ax.scatter([x], [r["mean"]], marker="D", color="black", s=36, zorder=3)

        ax.set_xticks(range(len(spec.markers)))
        ax.set_xticklabels(spec.markers, rotation=15 if any(len(m) > 4 for m in spec.markers) else 0)
        ax.set_ylabel(f"{label} ({measure_units(measure, spec.signal)})")
        ax.set_title(label)
        top = ax.get_ylim()[1]
        gap = 0.08 * (ax.get_ylim()[1] - ax.get_ylim()[0]) or 0.1

        if len(spec.markers) >= 2:
            pw = results.pairwise[(results.pairwise["measure"] == measure)
                                  & (results.pairwise["basis"] == "trials")] if len(results.pairwise) else results.pairwise
            pairs = [(r["marker_a"], r["marker_b"], _sig_stars(r["p_adjusted"])) for _, r in pw.iterrows()]
            if pairs:
                new_top = _draw_brackets(ax, pairs, x_of, top + gap, gap)
                ax.set_ylim(ax.get_ylim()[0], new_top + gap)
        else:
            fe = results.fixed_effects[(results.fixed_effects["measure"] == measure)
                                       & (results.fixed_effects["basis"] == "trials")] if len(results.fixed_effects) else results.fixed_effects
            if len(fe) and np.isfinite(fe.iloc[0]["p_t"]):
                ax.axhline(0, color="black", lw=0.8, ls="--", zorder=0)
                ax.text(0.5, 0.98, f"vs. 0: {_sig_stars(fe.iloc[0]['p_t'])} (p={fe.iloc[0]['p_t']:.3g})",
                       transform=ax.transAxes, ha="center", va="top", fontsize=8)
        _style(ax)

    for ax in axes[n:]:
        ax.axis("off")
    fig.suptitle(f"{spec.group_name}: measures by marker")
    fig.tight_layout()
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

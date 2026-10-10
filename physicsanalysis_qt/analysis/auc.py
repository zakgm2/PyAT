"""
analysis/auc.py
---------------
Area-Under-Curve window analysis — same click-triggered dispatch as FFT/Z-Score (double-click near an event after picking "AUC" from the
toolbar's Analysis button). Generic/double-click tools like this one deliberately analyze whichever signal the "Plot:" dropdown currently
shows (get_active_signal) rather than always the normalized signal — that's reserved for the dataset-specific tools under Custom Statistics
(Event PETH, Find Significant Peaks), which always analyze the corrected/normalized signal regardless of what's on screen.

The analysis is the analysis engine's (the library's auc_window, see windows.py). This module prints what comes back and draws it; the
window itself is result_window.py's.
"""

from .. import figures
from .result_window import run_click_analysis, show_result_window
from .windows import UNKNOWN_COLOR, channel_colors, channel_groups, column


def launch_auc(ctx, center_t):
    run_click_analysis(ctx, center_t, "AUC", "auc_window", _show_auc)


def _show_auc(ctx, center_t, pre, post, result):
    colors = channel_colors(ctx)
    curves = {name: rows for name, rows in channel_groups(result.tables["window"])}
    last_auc_results = []
    for _, row in result.tables["auc"].iterrows():
        name = row["Channel"]
        rows = curves[name]
        last_auc_results.append({
            "channel": name, "color": colors.get(name, UNKNOWN_COLOR), "total_auc": float(row["Total AUC"]),
            "positive_auc": float(row["Positive AUC"]), "negative_auc": float(row["Negative AUC"]),
            "t": column(rows, "time_from_center_s"), "seg_y": column(rows, "value")})

    lines = []
    for r in last_auc_results:
        lines.append(
            f"[{r['channel']}]\n"
            f"  Total (net) AUC:    {r['total_auc']:.4f}\n"
            f"  Positive-only AUC:  {r['positive_auc']:.4f}\n"
            f"  Negative-only AUC:  {r['negative_auc']:.4f}"
        )
    lines.append(f"Window: -{pre:.1f}s / +{post:.1f}s around {center_t:.2f}s")

    fig = figures.auc_window_figure(
        [{"channel": r["channel"], "color": r["color"], "t": r["t"], "y": r["seg_y"]} for r in last_auc_results])

    show_result_window(
        ctx, center_t, pre, post, name="AUC", prefix="AUC", kind="auc_window", fig=fig, report="\n\n".join(lines), report_first=True,
        csv_header=["Channel", "Total AUC", "Positive AUC", "Negative AUC", "Window Pre (s)", "Window Post (s)"],
        csv_rows=lambda: [
            [r["channel"], f"{r['total_auc']:.6g}", f"{r['positive_auc']:.6g}", f"{r['negative_auc']:.6g}", f"{pre:.4f}", f"{post:.4f}"]
            for r in last_auc_results
        ],
    )

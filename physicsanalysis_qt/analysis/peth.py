"""
analysis/peth.py
----------------
Z-Score window analysis — same click-triggered dispatch as FFT/AUC (double-click near a point after picking "Z-Score" from the toolbar's
Analysis button). Not a PETH (peri-event time histogram, which averages many occurrences of one event) — this analyzes a single clicked
point; see analysis/event_peth.py for the real multi-trial version. Generic/double-click tools like this one deliberately analyze whichever
signal the "Plot:" dropdown currently shows (get_active_signal) rather than always the normalized signal — that's reserved for the
dataset-specific tools under Custom Statistics (Event PETH, Find Significant Peaks), which always analyze the corrected/normalized signal
regardless of what's on screen.

The analysis is the analysis engine's (the library's zscore_window, see windows.py): it picks the channels, smooths the whole signal and
z-scores the window around the click against its own baseline. This module prints what comes back and draws it; the window itself is
result_window.py's.
"""

from .. import figures
from .result_window import run_click_analysis, show_result_window
from .windows import UNKNOWN_COLOR, channel_colors, channel_groups, column


def launch_zscore_peth(ctx, center_t):
    run_click_analysis(ctx, center_t, "Z-Score", "zscore_window", _show_zscore)


def _show_zscore(ctx, center_t, pre, post, result):
    colors = channel_colors(ctx)
    peaks = result.tables["peaks"]
    results = []
    for name, rows in channel_groups(result.tables["window"]):
        peak = peaks[peaks["Channel"] == name].iloc[0]
        results.append({
            "channel": name, "color": colors.get(name, UNKNOWN_COLOR), "t": column(rows, "time_from_center_s"), "z_seg": column(rows, "z_score"),
            "peak_z": float(peak["Peak Z-score"]), "peak_rel_t": float(peak["Peak time from center (s)"]),
        })

    # The figure is figures/draw.py's: the one Open Results draws again from the exported CSV
    fig = figures.zscore_window_figure(
        [{"channel": r["channel"], "color": r["color"], "t": r["t"], "z": r["z_seg"]} for r in results], pre, post)

    blocks = [
        f"[{r['channel']}]\n  Peak Z-score:  {r['peak_z']:.4f} at t = {r['peak_rel_t']:+.2f}s"
        for r in results
    ]
    blocks.append(f"Window: -{pre:.1f}s / +{post:.1f}s around {center_t:.2f}s")

    show_result_window(
        ctx, center_t, pre, post, name="Z-Score", title="Z-Score Analysis", prefix="ZScore", kind="zscore_window", fig=fig,
        report="\n\n".join(blocks),
        csv_header=["Channel", "time_from_center_s", "z_score"],
        csv_rows=lambda: [[r["channel"], f"{t:.4f}", f"{z:.4f}"] for r in results for t, z in zip(r["t"], r["z_seg"])],
    )
